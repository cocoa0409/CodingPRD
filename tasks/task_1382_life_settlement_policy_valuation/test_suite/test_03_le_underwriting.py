"""Life-expectancy underwriting: blend math, supersede filtering, temporal gates
(PRD §3.2)."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_broker_headers,
    setup_case_in_underwriting, setup_case_marketed, order_and_deliver_le,
    create_offer, set_clock,
)

ADMIN = TEST_USERS["admin_headers"]
CM = TEST_USERS["case_manager_headers"]
UW = TEST_USERS["underwriter_headers"]


class TestLEBlendAndReservePrice:
    def test_le_blend_tiered_weights_multiplicative_debits(self, api):
        """PRD §3.2: "On delivery the report's `adjusted_le_months` is computed:
        start with `base_le_months`, multiply it by one minus each debit in turn
        (that is, by the product of all one-minus-debit factors), floor the result
        to a whole month, and floor the final figure at 1 so a heavily debited life
        still yields at least one month."
        PRD §3.2: "With several, each report is weighted by tier — a tier-`A`
        report weighs 3, a tier-`B` report weighs 1 — and the blend is the weighted
        sum of adjusted months divided by the sum of weights, rounded half-up to a
        whole month."

        Design: Difficulty/combinatorial_formula/le_blend_tiered_weights_multiplicative_debits
        """
        broker, insured, policy, case = setup_case_in_underwriting(
            policy_overrides={"policy_type": "UNIVERSAL_LIFE"},
            insured_overrides={"smoker_status": "TOBACCO"},
        )
        le_a = order_and_deliver_le(case, tier="A", base_le_months=120,
                                    impairment_debits=[0.1, 0.2])
        le_b = order_and_deliver_le(case, tier="B", base_le_months=100,
                                    impairment_debits=[0.05])

        assert le_a["adjusted_le_months"] == 86, "floor(120 * 0.9 * 0.8)"
        assert le_b["adjusted_le_months"] == 95, "floor(100 * 0.95)"

        decided = validate_success(api.uw_decision(case["id"], {"decision": "APPROVE"}, UW))
        assert decided["blended_le_months"] == 88, "round_half_up((3*86 + 1*95)/4) = round_half_up(88.25)"
        assert decided["reserve_price_cents"] == 647131
        assert decided["status"] == "MARKETED"

    def test_le_blend_excludes_ineligible_reports_from_weights(self, api):
        """PRD §3.2: "Reports in `ORDERED`, `SUPERSEDED`, or `EXPIRED` never enter
        the blend."
        PRD §3.2: "With several, each report is weighted by tier — a tier-`A`
        report weighs 3, a tier-`B` report weighs 1 — and the blend is the weighted
        sum of adjusted months divided by the sum of weights, rounded half-up to a
        whole month."
        PRD §2.4: "a `DELIVERED` life-expectancy report whose `valid_through` is
        earlier than the new clock becomes `EXPIRED`"

        Design: Difficulty/combinatorial_formula/le_blend_tiered_weights_multiplicative_debits
        """
        broker, insured, policy, case = setup_case_in_underwriting(
            policy_overrides={"policy_type": "UNIVERSAL_LIFE"},
            insured_overrides={"smoker_status": "TOBACCO"},
            license_overrides={"expiry_date": "2028-12-31"},
        )
        le_a = order_and_deliver_le(case, tier="A", base_le_months=120,
                                    impairment_debits=[0.1, 0.2])
        le_b = order_and_deliver_le(case, tier="B", base_le_months=100,
                                    impairment_debits=[0.05])
        # A third report is ordered but never delivered: ORDERED rows never blend.
        pending = get_success_data(api.order_le_report(case["id"], {"underwriter_tier": "A"}, UW))
        assert pending["status"] == "ORDERED"

        # Delivered at the default clock 2026-08-01, valid_through 2027-01-28;
        # one second past that boundary every delivered report is EXPIRED.
        set_clock("2027-01-29T00:00:00Z")
        assert validate_success(api.get_le_report(le_a["id"], UW))["status"] == "EXPIRED"
        assert validate_success(api.get_le_report(le_b["id"], UW))["status"] == "EXPIRED"

        # A fresh tier-A report (base 150, no debits) re-opens eligibility alone:
        # weight 3 over the sole eligible report yields its own adjusted value.
        fresh = order_and_deliver_le(case, tier="A", base_le_months=150,
                                     impairment_debits=[])
        assert fresh["adjusted_le_months"] == 150
        decided = validate_success(api.uw_decision(case["id"], {"decision": "APPROVE"}, UW))
        assert decided["blended_le_months"] == 150, (
            "EXPIRED and ORDERED reports are excluded from the eligible blend set"
        )

    def test_reserve_price_single_report_literal(self, api):
        """PRD §3.2: "With exactly one eligible report, the case's
        `blended_le_months` is that report's `adjusted_le_months`."
        PRD §3.2: "The present value of the death benefit is the face amount
        multiplied by v raised to the k-th power. The present value of future
        premiums is one twelfth of the annual premium multiplied by the
        annuity-immediate factor over k months — that factor being one minus
        v-to-the-k, divided by the monthly rate. The expense load is a flat 250000
        cents (twenty-five hundred dollars) plus the face amount times 150 basis
        points, the latter rounded half-up to cents. The raw reserve is the benefit
        present value minus the premium present value minus the expense load, with
        intermediate values carried unrounded until the final round. The reserve
        price is then the smaller of two bounds — the face amount times 8000 basis
        points (80 percent of face) rounded half-up, and the raw reserve rounded
        half-up — floored at zero so it can never go negative."

        Design: Corner/calculations/reserve_price_single_report_literal
        """
        broker, insured, policy, case = setup_case_in_underwriting(
            insured_overrides={"smoker_status": "UNKNOWN"})
        order_and_deliver_le(case, tier="A", base_le_months=120,
                             impairment_debits=[0.1, 0.2])
        decided = validate_success(api.uw_decision(case["id"], {"decision": "APPROVE"}, UW))
        assert decided["blended_le_months"] == 86
        assert decided["reserve_price_cents"] == 770484

    def test_same_tier_le_supersedes(self, api):
        """PRD §3.2: "Delivering a new report supersedes any other currently
        `DELIVERED` report on the same case carrying the same `underwriter_tier` —
        the older sibling moves to `SUPERSEDED`."
        PRD §3.2: "Reports in `ORDERED`, `SUPERSEDED`, or `EXPIRED` never enter the
        blend."

        Design: Corner/calculations/same_tier_le_supersedes
        """
        broker, insured, policy, case = setup_case_in_underwriting(
            insured_overrides={"smoker_status": "UNKNOWN"})
        le1 = order_and_deliver_le(case, tier="A", base_le_months=120,
                                   impairment_debits=[0.1, 0.2])
        le2 = order_and_deliver_le(case, tier="A", base_le_months=150,
                                   impairment_debits=[])

        le1_after = validate_success(api.get_le_report(le1["id"], UW))
        assert le1_after["status"] == "SUPERSEDED"
        le2_after = validate_success(api.get_le_report(le2["id"], UW))
        assert le2_after["status"] == "DELIVERED"
        assert le2_after["adjusted_le_months"] == 150

        decided = validate_success(api.uw_decision(case["id"], {"decision": "APPROVE"}, UW))
        assert decided["blended_le_months"] == 150, (
            "only the surviving same-tier DELIVERED report enters the blend"
        )


class TestUWTemporalGates:
    def test_uw_approve_le_required_then_expired(self, api):
        """PRD §3.2: "If no report has ever been delivered for the case, the
        decision is rejected with `ERR_LE_REPORT_REQUIRED` (HTTP 422); if reports
        were delivered but every one has expired, the rejection is
        `ERR_LE_REPORT_EXPIRED` (HTTP 409)."
        PRD §3.2: "The delivered report's `delivered_at` is set to the clock, and
        its `valid_through` to `delivered_at` plus 180 days"
        PRD §3.2: "Independently, a `DELIVERED` report becomes `EXPIRED`
        automatically once the clock passes its `valid_through`."

        Design: Corner/validations/uw_approve_le_required_then_expired
        """
        broker, insured, policy, case = setup_case_in_underwriting(
            insured_overrides={"smoker_status": "UNKNOWN"},
            license_overrides={"expiry_date": "2028-12-31"},
        )
        resp = api.uw_decision(case["id"], {"decision": "APPROVE"}, UW)
        validate_error(resp, ApiErrorId.ERR_LE_REPORT_REQUIRED)

        le = order_and_deliver_le(case, tier="A", base_le_months=120,
                                  impairment_debits=[0.1, 0.2])
        assert le["valid_through"] == "2027-01-28T00:00:00Z", (
            "delivered at the default clock 2026-08-01 plus 180 days"
        )

        set_clock("2027-01-29T00:00:00Z")
        le_after = validate_success(api.get_le_report(le["id"], UW))
        assert le_after["status"] == "EXPIRED"
        resp2 = api.uw_decision(case["id"], {"decision": "APPROVE"}, UW)
        validate_error(resp2, ApiErrorId.ERR_LE_REPORT_EXPIRED)


class TestOrderGate:
    def test_offer_create_rejected_until_case_marketed(self, api):
        """PRD §3.3: "Offer creation on a case that is not `MARKETED` is rejected
        with `ERR_CASE_NOT_MARKETED` (HTTP 409)."
        PRD §3.3: "On a `MARKETED` case, an underwriter creates a provider offer by
        supplying `amount_cents` and optionally `expires_in_days`; the offer starts
        `PENDING` with `round_number` 1."
        PRD §3.2: "An approved case moves from `UNDERWRITING` to `MARKETED`"

        Design: Difficulty/cross_entity_state_dependency/offer_create_rejected_until_case_marketed
        """
        broker, insured, policy, case = setup_case_in_underwriting()
        order_and_deliver_le(case)

        resp = api.create_offer(case["id"], {"amount_cents": 6000000}, UW)
        validate_error(resp, ApiErrorId.ERR_CASE_NOT_MARKETED)

        approved = validate_success(api.uw_decision(case["id"], {"decision": "APPROVE"}, UW))
        assert approved["status"] == "MARKETED"
        offer = validate_success(api.create_offer(case["id"], {"amount_cents": 6000000}, UW),
                                 expected_status=201)
        assert offer["status"] == "PENDING"

    def test_offer_create_rejected_while_case_in_draft(self, api):
        """PRD §3.3: "Offer creation on a case that is not `MARKETED` is rejected
        with `ERR_CASE_NOT_MARKETED` (HTTP 409)."
        PRD §3.1: "A broker originates a case by naming a `policy_id`; the new
        `PolicyCase` is created in `DRAFT`"

        Design: Difficulty/cross_entity_state_dependency/offer_create_rejected_until_case_marketed
        """
        from test_helpers import setup_broker_insured_policy, create_case_for
        broker, insured, policy = setup_broker_insured_policy(with_license=False)
        case = create_case_for(broker, policy)
        assert case["status"] == "DRAFT"
        resp = api.create_offer(case["id"], {"amount_cents": 6000000}, UW)
        validate_error(resp, ApiErrorId.ERR_CASE_NOT_MARKETED)
