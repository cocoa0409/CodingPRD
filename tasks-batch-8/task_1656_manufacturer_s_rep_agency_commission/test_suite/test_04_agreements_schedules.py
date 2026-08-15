"""Line cards (territory agreements) and rate schedules (PRD §3.1, §2.8).

Covers the one-ACTIVE-agreement rule, order booking's dependence on an ACTIVE
agreement, OCC on rate-schedule creation, and the agreement gate on
registration approval.
"""
from datetime import timedelta

from test_helpers import (
    CLOCK_DEFAULT,
    parse_instant,
    TEST_USERS,
    ApiErrorId,
    activate_agreement,
    approve_registration,
    create_agreement,
    create_customer,
    create_principal,
    create_rate_schedule,
    create_rate_schedule_payload,
    create_rep,
    get_agreement,
    get_principal,
    make_order_line,
    make_principal_ops_headers,
    make_rep_headers,
    setup_base_scenario,
    submit_registration,
    suspend_agreement,
    validate_error,
    validate_success,
)


class TestAgreementActivation:
    def test_agreement_conflict_rejected(self, api, agency_admin_headers):
        """PRD §3.1: "Two gates guard activation, in the pipeline order of §2.9: the
        principal must not be `TERMINATED` (else `ERR_LINE_TERMINATED`), and no other
        agreement for the same principal may already be `ACTIVE` (else
        `ERR_AGREEMENT_CONFLICT`). At most one agreement per principal is ever
        `ACTIVE` at a time."

        Design: Corner/validations/agreement_conflict_rejected
        """
        principal = create_principal()
        a1 = create_agreement(principal["id"], territory_codes=["CA"])
        activate_agreement(a1["id"])
        a2 = create_agreement(principal["id"], territory_codes=["AZ"],
                              effective_start="2026-06-01T00:00:00Z")

        resp = api.activate_agreement(a2["id"], agency_admin_headers)
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_CONFLICT)
        assert get_agreement(a2["id"])["status"] == "DRAFT"

    def test_order_requires_active_agreement_rejected(self, api):
        """PRD §3.4: "The principal's single `ACTIVE` agreement must exist
        (`ERR_AGREEMENT_NOT_ACTIVE`), and every line's specifying and ship-to
        territories must fall inside that agreement's `territory_codes`
        (`ERR_TERRITORY_NOT_COVERED`)."

        Design: Corner/validations/order_requires_active_agreement_rejected
        """
        principal = create_principal()
        # Agreement left in DRAFT — never activated.
        create_agreement(principal["id"], territory_codes=["CA"])
        create_rate_schedule(principal["id"], principal["version"])
        customer = create_customer(spec_territory_code="CA", ship_to_territory_code="CA")

        resp = api.create_order(
            {
                "customer_id": customer["id"],
                "principal_id": principal["id"],
                "external_order_ref": "PO-1",
                "placed_at": "2026-08-01T00:00:00Z",
                "lines": [make_order_line(quantity=1, unit_price_cents=1000)],
            },
            TEST_USERS["agency_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)


class TestRateScheduleOcc:
    def test_occ_rate_schedule_stale_version(self, api, agency_admin_headers):
        """PRD §2.8: "Creating a rate schedule with
        `POST /rep-agency/principals/{id}/rate-schedules` requires the request to
        carry `expected_principal_version`, the caller's last observed `version` of
        the parent principal. If the principal's current `version` no longer matches —
        because another schedule was created, a termination notice was issued or
        rescinded, or any other mutation intervened — the create is rejected with
        `ERR_STALE_PRINCIPAL_VERSION` (HTTP 412): the supersede the client priced
        against is no longer current."
        PRD §3.1: "Creation stamps `effective_from` with the current clock, immediately
        flips the new schedule to `ACTIVE`, and atomically supersedes the principal's
        previously `ACTIVE` schedule, which moves to `SUPERSEDED`; at no time does a
        principal have more than one `ACTIVE` schedule."

        Design: Corner/cross_cutting_layers/occ_rate_schedule_stale_version
        """
        principal = create_principal()
        v0 = principal["version"]
        rs1 = create_rate_schedule(principal["id"], v0)
        assert rs1["status"] == "ACTIVE"

        after_rs1 = get_principal(principal["id"])
        assert after_rs1["version"] == v0 + 1, (
            "PRD §3.1: creation increments the principal's version by one"
        )

        # Stale create carrying the pre-supersede version.
        stale = api.create_rate_schedule(
            principal["id"],
            create_rate_schedule_payload(
                v0,
                family_rates=[{"family_code": "CONNECTORS", "base_rate_bp": 500}],
                attainment_tiers=[{"min_attainment_bp": 0, "multiplier_bp": 10000}],
            ),
            agency_admin_headers,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_PRINCIPAL_VERSION, expected_status=412)

        # Fresh create with the current version succeeds and supersedes RS1.
        rs2 = create_rate_schedule(
            principal["id"], after_rs1["version"],
            family_rates=[{"family_code": "CONNECTORS", "base_rate_bp": 500}],
            attainment_tiers=[{"min_attainment_bp": 0, "multiplier_bp": 10000}],
        )
        assert rs2["status"] == "ACTIVE"
        rs1_after = api.get_rate_schedule(rs1["id"], agency_admin_headers)
        assert validate_success(rs1_after)["status"] == "SUPERSEDED"
        assert get_principal(principal["id"])["version"] == v0 + 2


class TestRegistrationApprovalAgreementGate:
    def test_approve_blocked_while_agreement_suspended(self, api):
        """PRD §3.3: "The principal's single `ACTIVE` territory agreement must exist,
        else `ERR_AGREEMENT_NOT_ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/registration_approval_requires_active_agreement
        """
        base = setup_base_scenario()
        principal = base["principal"]
        r1 = base["reps"][0]
        reg = submit_registration(principal["id"], base["customer"]["id"], r1["id"],
                                  project_name="Project Susp")
        suspend_agreement(base["agreement"]["id"])

        resp = api.approve_registration(
            reg["id"], make_principal_ops_headers(principal["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)
        assert api.get_registration(
            reg["id"], make_rep_headers(r1["id"]),
        ).json()["data"]["status"] == "SUBMITTED"

    def test_approve_succeeds_after_agreement_reactivated(self, api):
        """PRD §3.1: "Activation — performed by an `AgencyAdmin` — moves an agreement
        from `DRAFT` to `ACTIVE`, and the same action reactivates a `SUSPENDED`
        agreement back to `ACTIVE`."
        PRD §3.3: "On approval, `protection_start` is set to the current clock and
        `protection_end` to 180 days later."

        Design: Difficulty/cross_entity_state_dependency/registration_approval_requires_active_agreement
        """
        base = setup_base_scenario()
        principal = base["principal"]
        r1 = base["reps"][0]
        reg = submit_registration(principal["id"], base["customer"]["id"], r1["id"],
                                  project_name="Project Susp")
        suspend_agreement(base["agreement"]["id"])
        validate_error(
            api.approve_registration(reg["id"], make_principal_ops_headers(principal["id"])),
            ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE,
        )

        activate_agreement(base["agreement"]["id"])
        approved = approve_registration(reg["id"], principal["id"])
        assert approved["status"] == "APPROVED"
        assert parse_instant(approved["protection_start"]) == parse_instant(CLOCK_DEFAULT)
        assert parse_instant(approved["protection_end"]) - parse_instant(
            approved["protection_start"],
        ) == timedelta(days=180)
