"""Role authorisation and identity-scoped authority.

The endpoint's role list is decided on the declared role alone and therefore ahead of the
state machine; the `Lessee` role is additionally scoped by identity; and the settlement
desk's second-pair-of-eyes rule is enforced on the opaque operator identifier within one
role rather than between roles.
"""

import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    close_month,
    consent_payload,
    create_aircraft,
    create_flight_leg_payload,
    create_lessee,
    dispute_payload,
    file_reliability_report,
    get_success_data,
    issue_insurance_certificate,
    make_billing_admin_headers,
    make_lessee_headers,
    prepare_invoice,
    qualify_crew_member,
    record_determination,
    request_substitution,
    revoke_approval,
    setup_active_lease,
    setup_filed_lease,
    setup_settled_month,
    validate_error,
    validate_paginated,
    validate_success,
)

OPS = TEST_USERS["lessor_ops_headers"]
AUTHORITY = TEST_USERS["regulatory_authority_headers"]
TECH = TEST_USERS["maintenance_controller_headers"]
BILLING = TEST_USERS["billing_admin_headers"]

PREPARER = make_billing_admin_headers("billing-clerk-01")
APPROVER = make_billing_admin_headers("billing-supervisor-02")

CLOCK = "2026-09-01T00:00:00Z"

SUBSTITUTE_AIRFRAME = {
    "tail_number": "G-SUBA",
    "type_designator": "B739",
    "type_family": "B737",
    "seat_count": 189,
    "mtow_kg": 85000,
    "airframe_hours_total": 12000.00,
    "hours_since_last_check": 90.00,
    "cycles_since_last_check": 20,
}


class TestConsentBelongsToTheLesseeAlone:
    @pytest.mark.parametrize(
        "role_headers_key",
        ["lessor_ops_headers", "billing_admin_headers", "regulatory_authority_headers"],
    )
    def test_no_other_role_may_stand_in_for_the_customer_on_consent(
        self, api, role_headers_key
    ):
        """PRD §2.1: If the headers are well-formed but the declared role is not authorised for the endpoint being called, the rejection is `ERR_UNAUTHORIZED` (HTTP 403).
        PRD §2.1: It consents to or withholds consent from substitutions, reviews the monthly reliability report, disputes a settled month, and reads its own leases' resources.
        PRD §3.7: A `Lessee` rules on a pending request by supplying a `decision` of `GRANT` or `WITHHOLD`, optionally with a `consent_note`, and only when its `X-User-ID` matches the lease's `lessee_id`.
        PRD §2.8: **Authorisation** — the acting role is listed for the endpoint, else `ERR_UNAUTHORIZED`.

        Design: Corner/rbac/only_the_lessee_can_grant_substitution_consent_and_the_lessor_cannot
        """
        scenario = setup_active_lease(
            api,
            clock=CLOCK,
            lease_overrides={"substitution_rights": "LESSEE_CONSENT_REQUIRED"},
        )
        substitute = create_aircraft(api, **SUBSTITUTE_AIRFRAME)
        substitution = request_substitution(
            api,
            scenario,
            substitute_aircraft_id=substitute["id"],
            reason="SCHEDULED_MAINTENANCE",
            effective_from="2026-09-20T00:00:00Z",
        )
        assert substitution["status"] == "LESSEE_CONSENT_PENDING", (
            "a consent-required lease must park the request in LESSEE_CONSENT_PENDING, got "
            f"{substitution['status']}"
        )

        validate_error(
            api.consent_substitution(
                substitution["id"], consent_payload("GRANT"), TEST_USERS[role_headers_key]
            ),
            ApiErrorId.ERR_UNAUTHORIZED,
        )

        unchanged = get_success_data(api.get_substitution(substitution["id"], OPS))
        assert unchanged["status"] == "LESSEE_CONSENT_PENDING", (
            "a role-denied consent must be decided ahead of the state machine, so the request "
            f"stays LESSEE_CONSENT_PENDING, got {unchanged['status']}"
        )
        assert unchanged.get("consent_note") is None, (
            f"no consent_note may be recorded, got {unchanged.get('consent_note')!r}"
        )
        lease = get_success_data(api.get_lease(scenario["lease"]["id"], OPS))
        assert lease["primary_aircraft_id"] == scenario["aircraft"]["id"], (
            "the airframe of record must still be the original airframe"
        )

    def test_the_owning_lessee_grants_consent_and_the_request_is_approved(self, api):
        """PRD §3.7: A `Lessee` rules on a pending request by supplying a `decision` of `GRANT` or `WITHHOLD`, optionally with a `consent_note`, and only when its `X-User-ID` matches the lease's `lessee_id`.
        PRD §3.7: `GRANT` moves the request from `LESSEE_CONSENT_PENDING` to `APPROVED`; `WITHHOLD` moves it to the terminal `REJECTED` and the original airframe stays on the lease.

        Design: Corner/rbac/only_the_lessee_can_grant_substitution_consent_and_the_lessor_cannot
        """
        scenario = setup_active_lease(
            api,
            clock=CLOCK,
            lease_overrides={"substitution_rights": "LESSEE_CONSENT_REQUIRED"},
        )
        substitute = create_aircraft(api, **SUBSTITUTE_AIRFRAME)
        substitution = request_substitution(
            api,
            scenario,
            substitute_aircraft_id=substitute["id"],
            reason="SCHEDULED_MAINTENANCE",
            effective_from="2026-09-20T00:00:00Z",
        )

        granted = validate_success(
            api.consent_substitution(
                substitution["id"], consent_payload("GRANT"), scenario["lessee_headers"]
            ),
            200,
        )
        assert granted["status"] == "APPROVED", (
            "the owning lessee's GRANT must move the request to APPROVED, got "
            f"{granted['status']}"
        )


class TestFlightLegReadsAreBroaderThanWrites:
    @pytest.mark.parametrize(
        "denied_role", ["BillingAdmin", "Lessee", "MaintenanceController"]
    )
    def test_only_operations_control_may_schedule_a_leg(self, api, denied_role):
        """PRD §2.1: A `LessorOpsController` is the lessor's operations control desk. It drafts leases, files them with the authority, activates them, registers crew members and enrols them in differences training, schedules and closes out flight legs, requests and effectuates airframe substitutions, serves termination and closes the return record.
        PRD §2.1: If the headers are well-formed but the declared role is not authorised for the endpoint being called, the rejection is `ERR_UNAUTHORIZED` (HTTP 403).
        PRD §2.8: **Authorisation** — the acting role is listed for the endpoint, else `ERR_UNAUTHORIZED`.

        Design: Corner/rbac/reading_flight_legs_is_broad_but_only_lessor_ops_may_create_one
        """
        scenario = setup_active_lease(api, clock=CLOCK)
        headers = {
            "BillingAdmin": BILLING,
            "Lessee": scenario["lessee_headers"],
            "MaintenanceController": TECH,
        }[denied_role]
        payload = create_flight_leg_payload(
            scenario["lease"]["id"],
            scenario["aircraft"]["id"],
            scenario["captain"]["id"],
            scenario["first_officer"]["id"],
            scheduled_out="2026-09-08T06:00:00Z",
            scheduled_in="2026-09-08T08:25:00Z",
        )

        validate_error(
            api.create_flight_leg(payload, headers), ApiErrorId.ERR_UNAUTHORIZED
        )

        legs, meta = validate_paginated(
            api.list_flight_legs(OPS, params={"lease_id": scenario["lease"]["id"]})
        )
        assert meta["total_count"] == 0, (
            f"a role-denied schedule must create no leg, got total_count {meta['total_count']}"
        )
        assert legs == [], "a role-denied schedule must create no leg"

    def test_the_settlement_desk_may_list_the_legs_it_may_not_schedule(self, api):
        """PRD §2.1: A `BillingAdmin` is the block-hour settlement desk. It registers lessees, applies and lifts credit-control suspensions, closes months, prepares, approves, issues and voids invoices, and resolves disputes.
        PRD §2.2: Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for list endpoints.

        Design: Corner/rbac/reading_flight_legs_is_broad_but_only_lessor_ops_may_create_one
        """
        scenario = setup_active_lease(api, clock=CLOCK)

        legs, meta = validate_paginated(
            api.list_flight_legs(BILLING, params={"lease_id": scenario["lease"]["id"]})
        )

        assert meta["total_count"] == 0, (
            "the settlement desk's list must succeed and report the empty programme, got "
            f"total_count {meta['total_count']}"
        )
        assert legs == [], f"no legs exist on this lease yet, got {legs}"


class TestLesseeOwnershipScopesTheDispute:
    def test_a_lessee_row_that_does_not_own_the_lease_is_unauthorized_not_missing(self, api):
        """PRD §2.1: When `X-User-Role` is `Lessee`, `X-User-ID` is the `id` of the acting `Lessee` row; ownership checks on any resource that references a `Lessee` compare the `lessee_id` of the `LeaseAgreement` that owns the target resource to `X-User-ID`, and a mismatch is rejected with `ERR_UNAUTHORIZED` (HTTP 403).
        PRD §2.8: **Lessee ownership** — when the acting role is `Lessee`, `X-User-ID` must equal the `lessee_id` of the lease owning the target resource, else `ERR_UNAUTHORIZED`.

        Design: Corner/rbac/a_lessee_acting_for_another_lessee_is_unauthorized_on_dispute
        """
        scenario = setup_settled_month(api, leg_plan=[], clock=CLOCK)
        outsider = create_lessee(
            api, name="Northwind Air Charter", icao_code="NWD", home_base_icao="EGGW"
        )
        outsider_headers = make_lessee_headers(outsider["id"])
        period_id = scenario["period"]["id"]

        error = validate_error(
            api.dispute_utilization_period(
                period_id,
                dispute_payload("MGH_PRORATION_CHALLENGED", 1000000),
                outsider_headers,
            ),
            ApiErrorId.ERR_UNAUTHORIZED,
        )
        assert error["error_id"] != ApiErrorId.ERR_PERIOD_NOT_FOUND.value, (
            "the period plainly exists, so a wrong-identity Lessee must be 403 and not a 404"
        )

        period = get_success_data(api.get_utilization_period(period_id, BILLING))
        assert period["status"] == "SETTLED", (
            f"the refused dispute must leave the month SETTLED, got {period['status']}"
        )
        assert period["disputed_amount_cents"] == 0, (
            "the refused dispute must leave disputed_amount_cents untouched, got "
            f"{period['disputed_amount_cents']}"
        )

    def test_the_owning_lessee_identity_may_dispute_the_settled_month(self, api):
        """PRD §3.9: A `Lessee` whose `X-User-ID` matches the lease's `lessee_id` may dispute a `SETTLED` month by supplying a `dispute_reason` and a `disputed_amount_cents`.
        PRD §3.9: The dispute moves the period from `SETTLED` to `DISPUTED`, records both fields, and increments the period's `version`.

        Design: Corner/rbac/a_lessee_acting_for_another_lessee_is_unauthorized_on_dispute
        """
        scenario = setup_settled_month(api, leg_plan=[], clock=CLOCK)

        disputed = validate_success(
            api.dispute_utilization_period(
                scenario["period"]["id"],
                dispute_payload("MGH_PRORATION_CHALLENGED", 1000000),
                scenario["lessee_headers"],
            ),
            200,
        )

        assert disputed["status"] == "DISPUTED", (
            f"the owning lessee's dispute must move the month to DISPUTED, got {disputed['status']}"
        )
        assert disputed["disputed_amount_cents"] == 1000000, (
            f"the contested amount must be recorded, got {disputed['disputed_amount_cents']}"
        )


class TestSegregationOfDutiesOnTheSettlementDesk:
    @staticmethod
    def _prepared_invoice(api):
        """A PENDING_SETTLEMENT 2026-09 month with a PREPARED FINAL invoice by the clerk."""
        scenario = setup_active_lease(api, clock=CLOCK)
        period = close_month(api, scenario["period"]["id"])
        invoice = prepare_invoice(
            api, period, due_on="2026-10-15", variant="FINAL", headers=PREPARER
        )
        file_reliability_report(api, scenario, period_month="2026-09")
        return scenario, invoice

    def test_the_preparer_may_not_approve_the_invoice_it_prepared(self, api):
        """PRD §2.1: The settlement desk operates under a second-pair-of-eyes rule that is enforced on the opaque identifier itself: the `BillingAdmin` whose `X-User-ID` was recorded as `prepared_by_user_id` on an invoice may not be the `BillingAdmin` who approves it.
        PRD §2.1: An attempt to do so is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).
        PRD §3.9: And the approving `X-User-ID` must differ from the invoice's `prepared_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

        Design: Corner/rbac/the_preparer_cannot_approve_their_own_invoice_but_may_issue_the_approved_one
        """
        _, invoice = self._prepared_invoice(api)
        assert invoice["prepared_by_user_id"] == "billing-clerk-01", (
            "preparation must record the acting BillingAdmin identifier, got "
            f"{invoice['prepared_by_user_id']!r}"
        )

        error = validate_error(
            api.approve_settlement_invoice(invoice["id"], PREPARER),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
        )
        assert error["error_id"] != ApiErrorId.ERR_UNAUTHORIZED.value, (
            "the rule is enforced on identity within the BillingAdmin role, so the rejection "
            "is ERR_SEGREGATION_OF_DUTIES and not a role denial"
        )

        unchanged = get_success_data(api.get_settlement_invoice(invoice["id"], BILLING))
        assert unchanged["status"] == "PREPARED", (
            f"the refused self-approval must leave the invoice PREPARED, got {unchanged['status']}"
        )
        assert unchanged["approved_by_user_id"] is None, (
            "the refused self-approval must leave approved_by_user_id null, got "
            f"{unchanged['approved_by_user_id']!r}"
        )

    def test_a_second_pair_of_eyes_approves_and_the_preparer_may_still_issue(self, api):
        """PRD §3.9: Approval moves the invoice from `PREPARED` to `APPROVED` and writes `approved_by_user_id` with the approver's identifier.
        PRD §3.9: Issue moves the invoice from `APPROVED` to `ISSUED`, records `due_on`, adds `amount_cents` to the lessee's `outstanding_balance_usd_cents`, and — when the invoice's `variant` is `FINAL` — drives the period from `PENDING_SETTLEMENT` to `SETTLED`.

        Design: Corner/rbac/the_preparer_cannot_approve_their_own_invoice_but_may_issue_the_approved_one
        """
        scenario, invoice = self._prepared_invoice(api)

        approved = validate_success(
            api.approve_settlement_invoice(invoice["id"], APPROVER), 200
        )
        assert approved["status"] == "APPROVED", (
            f"a different BillingAdmin may approve, got {approved['status']}"
        )
        assert approved["approved_by_user_id"] == "billing-supervisor-02", (
            f"the approver's identifier must be written, got {approved['approved_by_user_id']!r}"
        )
        assert approved["prepared_by_user_id"] == "billing-clerk-01", (
            "the preparer's identifier must survive approval, got "
            f"{approved['prepared_by_user_id']!r}"
        )

        issued = validate_success(api.issue_settlement_invoice(invoice["id"], PREPARER), 200)
        assert issued["status"] == "ISSUED", (
            "the constraint is scoped to approval, so the original preparer may issue, got "
            f"{issued['status']}"
        )

        lessee = get_success_data(api.get_lessee(scenario["lessee"]["id"], BILLING))
        assert lessee["outstanding_balance_usd_cents"] == issued["amount_cents"], (
            "issuing adds the invoice amount to the receivable, expected "
            f"{issued['amount_cents']}, got {lessee['outstanding_balance_usd_cents']}"
        )
        period = get_success_data(
            api.get_utilization_period(scenario["period"]["id"], BILLING)
        )
        assert period["status"] == "SETTLED", (
            f"issuing a FINAL invoice settles the month, got {period['status']}"
        )


class TestAuthorityPowersStopAtTheDocket:
    def test_the_authority_may_not_activate_the_lease(self, api):
        """PRD §2.1: A `RegulatoryAuthority` is the civil aviation authority holding the operational-control determination. It records determinations, attaches and clears conditions, and revokes the docket. It cannot touch commercial or fleet resources.
        PRD §2.1: If the headers are well-formed but the declared role is not authorised for the endpoint being called, the rejection is `ERR_UNAUTHORIZED` (HTTP 403).
        PRD §2.8: **Authorisation** — the acting role is listed for the endpoint, else `ERR_UNAUTHORIZED`.

        Design: Corner/rbac/the_authority_decides_and_revokes_the_determination_but_cannot_activate_the_lease
        """
        scenario = setup_filed_lease(api, clock=CLOCK)
        issue_insurance_certificate(api, scenario["lease"]["id"])
        qualify_crew_member(api, scenario["captain"]["id"], scenario["lease"]["id"])

        validate_error(
            api.activate_lease(scenario["lease"]["id"], AUTHORITY),
            ApiErrorId.ERR_UNAUTHORIZED,
        )

        lease = get_success_data(api.get_lease(scenario["lease"]["id"], OPS))
        assert lease["status"] == "PENDING_REGULATORY_APPROVAL", (
            "the refused activation must leave the lease awaiting the determination, got "
            f"{lease['status']}"
        )

    def test_the_authority_determination_and_revocation_reach_through_to_the_lease(self, api):
        """PRD §2.1: A `RegulatoryAuthority` is the civil aviation authority holding the operational-control determination. It records determinations, attaches and clears conditions, and revokes the docket. It cannot touch commercial or fleet resources.
        PRD §3.2: The authority revokes from `APPROVED` or from `CONDITIONAL` by supplying a `revocation_reason`; the docket moves to the terminal `REVOKED`, `decided_at` is set, the lease moves from `ACTIVE` to `SUSPENDED` with `suspension_reason` `REGULATORY_APPROVAL_REVOKED`, every leg on that lease still `SCHEDULED` or `DISPATCHED` is cancelled into `CANCELLED_LESSOR` with `cancel_reason` `REGULATORY`, and each such cancellation recomputes the affected crew members' rolling exposure and the covering open month's charge.

        Design: Corner/rbac/the_authority_decides_and_revokes_the_determination_but_cannot_activate_the_lease
        """
        scenario = setup_filed_lease(api, clock=CLOCK)
        issue_insurance_certificate(api, scenario["lease"]["id"])
        qualify_crew_member(api, scenario["captain"]["id"], scenario["lease"]["id"])

        docket = record_determination(api, scenario["approval"]["id"], "APPROVED")
        assert docket["determination"] == "APPROVED", (
            f"the authority's ruling must be recorded, got {docket['determination']}"
        )

        activated = validate_success(
            api.activate_lease(scenario["lease"]["id"], OPS), 200
        )
        assert activated["status"] == "ACTIVE", (
            f"commercial activation belongs to the lessor, got {activated['status']}"
        )

        revoked = revoke_approval(
            api, scenario["approval"]["id"], "OPERATIONAL_CONTROL_FINDING"
        )
        assert revoked["determination"] == "REVOKED", (
            f"the authority's revocation must land the docket in REVOKED, got {revoked['determination']}"
        )
        assert revoked["revocation_reason"] == "OPERATIONAL_CONTROL_FINDING", (
            f"the revocation reason must be recorded, got {revoked['revocation_reason']!r}"
        )

        lease = get_success_data(api.get_lease(scenario["lease"]["id"], AUTHORITY))
        assert lease["status"] == "SUSPENDED", (
            f"revocation must drive the lease ACTIVE -> SUSPENDED, got {lease['status']}"
        )
        assert lease["suspension_reason"] == "REGULATORY_APPROVAL_REVOKED", (
            "the suspension must be stamped REGULATORY_APPROVAL_REVOKED, got "
            f"{lease['suspension_reason']!r}"
        )
