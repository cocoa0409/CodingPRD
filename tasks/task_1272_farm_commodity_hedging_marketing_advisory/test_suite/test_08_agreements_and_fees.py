"""Advisory agreements: disclosure workflow, segregation of duties, and the
dual-variant fee statement."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_grower_headers,
    make_advisor_headers,
    make_compliance_headers,
    create_operation,
    create_agreement_for,
    activate_agreement,
    create_active_agreement,
    setup_active_plan_with_buyer,
    create_flat_contract,
    create_confirmed_delivery,
)

ADVISOR = TEST_USERS["advisor_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]


class TestDisclosureGates:
    def test_sign_without_acknowledgment_rejected(self, api):
        """PRD §3.10: "Signing is the grower's final act, moving the agreement
        from `PENDING_SIGNATURE` to `ACTIVE`; signing requires the disclosure
        to be `ACKNOWLEDGED`, failing with `ERR_DISCLOSURE_NOT_ACKNOWLEDGED`
        otherwise, and requires `acknowledged_agreement_version` to equal the
        agreement's current `version`, failing with `ERR_DISCLOSURE_STALE` on a
        stale pin."

        Design: Corner/validations/sign_without_acknowledgment_rejected
        """
        op = create_operation(
            name="NoAck Farm", primary_commodity="CORN", crop_year=2026, risk_profile="BALANCED"
        )
        agreement = create_agreement_for(op["id"], fee_type="PER_BUSHEL", rate_per_bushel=0.02)
        get_success_data(api.submit_agreement(agreement["id"], ADVISOR))
        get_success_data(api.deliver_disclosure(agreement["id"], ADVISOR))
        resp = api.sign_agreement(agreement["id"], make_grower_headers(op["id"]))
        validate_error(resp, ApiErrorId.ERR_DISCLOSURE_NOT_ACKNOWLEDGED)
        after = get_success_data(api.get_agreement(agreement["id"], ADVISOR))
        assert after["status"] == "PENDING_SIGNATURE", "agreement must remain PENDING_SIGNATURE"

    def test_contract_create_disclosure_stale_beats_buyer_suspended(self, api):
        """PRD §2.6: "Seventh, compliance gates are evaluated — disclosure
        acknowledgment, disclosure staleness, and segregation of duties —
        producing `ERR_DISCLOSURE_NOT_ACKNOWLEDGED`, `ERR_DISCLOSURE_STALE`, or
        `ERR_SEGREGATION_OF_DUTIES`. Eighth, referential state requirements are
        checked: a referenced buyer must be `APPROVED`, a referenced baseline
        must be `CERTIFIED`, and a referenced agreement must be `ACTIVE`,
        producing `ERR_BUYER_NOT_APPROVED`, `ERR_BASELINE_NOT_CERTIFIED`, or
        `ERR_AGREEMENT_NOT_ACTIVE`." and "A request failing an earlier check
        never reaches a later one, so the returned error always identifies the
        highest-priority violation present."
        PRD §3.10: "It increments the agreement's `version` by one and, when
        the disclosure was `ACKNOWLEDGED`, flips `disclosure_status` to
        `STALE`, so the grower must re-acknowledge before plan activations,
        resumes, signings, or contract creations proceed."

        Design: Difficulty/priority_pair_validation_conflict/contract_create_disclosure_stale_beats_buyer_suspended
        """
        ctx = setup_active_plan_with_buyer(
            name="Prio Farm 2", risk_profile="AGGRESSIVE", max_priced_pct=1.00,
            agreement_overrides={"fee_type": "PER_BUSHEL", "rate_per_bushel": 0.02, "flat_annual_fee": None},
        )
        # Amendment stales the acknowledgment; then the buyer is suspended.
        get_success_data(api.amend_agreement(ctx["agreement"]["id"], {"rate_per_bushel": 0.03}, ADVISOR))
        staled = get_success_data(api.get_agreement(ctx["agreement"]["id"], ADVISOR))
        assert staled["disclosure_status"] == "STALE", "amendment must flip ACKNOWLEDGED to STALE"
        get_success_data(api.suspend_buyer(ctx["buyer"]["id"], COMPLIANCE))
        resp = api.create_contract(
            {
                "operation_id": ctx["operation"]["id"],
                "plan_id": ctx["plan"]["id"],
                "buyer_id": ctx["buyer"]["id"],
                "contract_type": "FLAT_PRICE",
                "bushels": 1000,
                "fixed_price": 4.50,
                "delivery_window_start": "2026-10-01",
                "delivery_window_end": "2026-11-01",
            },
            ADVISOR,
        )
        validate_error(resp, ApiErrorId.ERR_DISCLOSURE_STALE)

    def test_amendment_marks_acknowledgment_stale(self, api):
        """PRD §3.10: "Amendment is an advisor action on an `ACTIVE` agreement
        — a self-loop that leaves status `ACTIVE`. The amendment may revise
        `rate_per_bushel`, `flat_annual_fee`, or `annual_cap_dollars`. It
        increments the agreement's `version` by one and, when the disclosure
        was `ACKNOWLEDGED`, flips `disclosure_status` to `STALE`, so the grower
        must re-acknowledge before plan activations, resumes, signings, or
        contract creations proceed."

        Design: Difficulty/priority_pair_validation_conflict/contract_create_disclosure_stale_beats_buyer_suspended
        """
        op = create_operation(
            name="Prio Farm 2", primary_commodity="CORN", crop_year=2026, risk_profile="AGGRESSIVE"
        )
        agreement = create_active_agreement(op["id"], fee_type="PER_BUSHEL", rate_per_bushel=0.02)
        assert agreement["disclosure_status"] == "ACKNOWLEDGED"
        amended = get_success_data(api.amend_agreement(agreement["id"], {"rate_per_bushel": 0.03}, ADVISOR))
        assert amended["status"] == "ACTIVE", "amendment is a self-loop on ACTIVE"
        assert amended["version"] == agreement["version"] + 1, "amendment increments the version by one"
        assert amended["disclosure_status"] == "STALE", "amendment invalidates the acknowledgment"


class TestSegregationOfDuties:
    def test_certify_with_same_user_returns_forbidden(self, api):
        """PRD §2.9: "Segregation of duties is enforced on the compliance
        certification: the `ComplianceOfficer` who certifies an agreement's
        disclosure package must not be the same person who submitted it. When
        the certifying officer's `X-User-ID` equals the agreement's
        `submitted_by_user_id`, the certification is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). On success the agreement's
        `compliance_certified` flag becomes true and `certified_by_user_id`
        records the certifier's `X-User-ID`."

        Design: Corner/rbac/certify_with_same_user_returns_forbidden
        """
        op = create_operation(
            name="SoD Farm", primary_commodity="CORN", crop_year=2026, risk_profile="BALANCED"
        )
        adv_1 = make_advisor_headers("adv_1")
        ag_a = create_agreement_for(op["id"], fee_type="PER_BUSHEL", rate_per_bushel=0.02)
        activate_agreement(ag_a, op["id"], submitter_headers=adv_1)
        ag_b = create_agreement_for(op["id"], fee_type="FLAT_ANNUAL", flat_annual_fee=2000)
        activate_agreement(ag_b, op["id"], submitter_headers=adv_1)
        ok = api.certify_compliance(ag_a["id"], make_compliance_headers("comp_1"))
        certified = validate_success(ok, expected_status=200)
        assert certified["compliance_certified"] is True, "a different officer may certify"
        conflict = api.certify_compliance(ag_b["id"], make_compliance_headers("adv_1"))
        validate_error(conflict, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)


class TestFeeStatement:
    def test_per_bushel_fee_scales_with_deliveries(self, api):
        """PRD §3.10: "Billable bushels are the sum of `net_bushels` over
        confirmed, non-voided delivery tickets whose `delivery_date` falls
        within the period inclusive of both endpoints and whose contract
        belongs to the agreement's operation. Under the `PER_BUSHEL` variant
        the fee is the billable bushels multiplied by `rate_per_bushel`,
        rounded to two decimals half-up; it scales with delivered bushels."

        Design: Difficulty/dual_variant_calc/advisory_fee_per_bushel_vs_flat
        """
        ctx = setup_active_plan_with_buyer(
            name="Fee Farm", risk_profile="AGGRESSIVE", planted_acres=100,
            aph_yield_bushels=195.50, trend_yield_bushels=200, max_priced_pct=1.00,
            agreement_overrides={"fee_type": "PER_BUSHEL", "rate_per_bushel": 0.02, "flat_annual_fee": None},
        )
        contract = create_flat_contract(
            ctx, bushels=19550, fixed_price=4.00,
            delivery_window_start="2026-10-01", delivery_window_end="2026-11-01",
        )
        create_confirmed_delivery(ctx, contract, delivery_date="2026-10-10", gross_bushels=10000, moisture_pct=15.0)
        create_confirmed_delivery(ctx, contract, delivery_date="2026-10-11", gross_bushels=9550, moisture_pct=15.0)
        stmt = get_success_data(api.get_fee_statement(
            ctx["agreement"]["id"], ADVISOR,
            params={"period_start": "2026-10-01", "period_end": "2026-10-31"},
        ))
        assert stmt["billable_bushels"] == 19550, (
            f"10000 + 9550 confirmed net bushels in period, got {stmt['billable_bushels']}"
        )
        assert stmt["fee_dollars"] == pytest.approx(391.00, abs=0.005), (
            f"19550 * 0.02 == 391.00, got {stmt['fee_dollars']}"
        )

    def test_flat_annual_fee_diverges_on_identical_history(self, api):
        """PRD §3.10: "Under the `FLAT_ANNUAL` variant the fee is the
        `flat_annual_fee`, charged once per statement period regardless of
        bushels; identical delivery history under the two variants therefore
        yields different totals." and "The statement returns
        `billable_bushels`, `fee_dollars`, and `capped`."

        Design: Difficulty/dual_variant_calc/advisory_fee_per_bushel_vs_flat
        """
        ctx = setup_active_plan_with_buyer(
            name="Fee Farm", risk_profile="AGGRESSIVE", planted_acres=100,
            aph_yield_bushels=195.50, trend_yield_bushels=200, max_priced_pct=1.00,
            agreement_overrides={"fee_type": "PER_BUSHEL", "rate_per_bushel": 0.02, "flat_annual_fee": None},
        )
        op_id = ctx["operation"]["id"]
        contract = create_flat_contract(
            ctx, bushels=19550, fixed_price=4.00,
            delivery_window_start="2026-10-01", delivery_window_end="2026-11-01",
        )
        create_confirmed_delivery(ctx, contract, delivery_date="2026-10-10", gross_bushels=10000, moisture_pct=15.0)
        create_confirmed_delivery(ctx, contract, delivery_date="2026-10-11", gross_bushels=9550, moisture_pct=15.0)
        # Plan auto-CLOSED on full delivery; terminate A and activate a FLAT_ANNUAL B.
        get_success_data(api.amend_agreement(ctx["agreement"]["id"], {"status_change": "TERMINATE"}, ADVISOR))
        ag_b = create_active_agreement(op_id, fee_type="FLAT_ANNUAL", flat_annual_fee=5000)
        stmt = get_success_data(api.get_fee_statement(
            ag_b["id"], ADVISOR,
            params={"period_start": "2026-10-01", "period_end": "2026-10-31"},
        ))
        assert stmt["billable_bushels"] == 19550, "billable history is operation-scoped and unchanged"
        assert stmt["fee_dollars"] == pytest.approx(5000.00, abs=0.005), (
            f"FLAT_ANNUAL charges the flat fee once per period; got {stmt['fee_dollars']}"
        )
        assert stmt["fee_dollars"] != pytest.approx(391.00), (
            "identical delivery history under the two variants must yield different totals"
        )
