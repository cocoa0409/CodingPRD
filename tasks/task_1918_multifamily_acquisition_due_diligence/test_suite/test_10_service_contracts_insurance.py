"""Service contracts (notice windows, auto-renew sweep, cancellation) and
insurance policies (loss ratio, risk tiers, HIGH-risk override)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_insurance_policy_payload,
    create_kicked_off_acquisition,
    create_service_contract_payload,
    get_success_data,
    validate_error,
    validate_success,
)

ANALYST = TEST_USERS["analyst_headers"]
UM1 = TEST_USERS["underwriting_manager_headers"]
VM1 = TEST_USERS["vendor_manager_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


class TestServiceContractNoticeDeadlineBoundary:
    def test_notice_on_deadline_day_allowed_day_after_missed(self, api):
        """PRD §3.7: "Notice requires the logical clock to be on or before the
        `decision_deadline` — the deadline day itself is still allowed, and a
        clock past the deadline is rejected with `ERR_NOTICE_WINDOW_MISSED` —
        and requires the acquisition to be in `IN_DILIGENCE`,
        `DILIGENCE_COMPLETE`, or `PRE_CLOSING` (else
        `ERR_INVALID_STATE_TRANSITION`)."
        PRD §3.7: "The contract opens `IDENTIFIED` with its `decision_deadline`
        computed as `term_end_date` minus `cancellation_notice_days` calendar
        days — the last day on which notice may be sent."

        Design: Difficulty/boundary_precision_check/service_contract_notice_deadline_boundary
        """
        acq = create_kicked_off_acquisition(property_name="Boundary Two")
        # term_end 2026-12-31 minus 60 days -> decision_deadline 2026-11-01.
        sc_a = get_success_data(api.create_service_contract(
            create_service_contract_payload(acq["id"], vendor_name="LiftCo"),
            VM1), 201)
        assert sc_a["decision_deadline"].startswith("2026-11-01"), (
            "term_end 2026-12-31 minus 60 calendar days"
        )
        get_success_data(api.begin_review_service_contract(sc_a["id"], VM1))
        sc_b = get_success_data(api.create_service_contract(
            create_service_contract_payload(
                acq["id"], vendor_name="CleanCo", service_type="LANDSCAPING",
                monthly_cost_cents=120000, cancellation_penalty_cents=50000),
            VM1), 201)
        get_success_data(api.begin_review_service_contract(sc_b["id"], VM1))

        get_success_data(api.set_clock("2026-11-01T00:00:00Z", ADMIN))
        noticed = validate_success(api.send_notice_service_contract(
            sc_a["id"], "2026-12-31T00:00:00Z", VM1))
        assert noticed["status"] == "NOTICE_SENT", "the deadline day is inclusive"

        get_success_data(api.set_clock("2026-11-02T00:00:00Z", ADMIN))
        resp = api.send_notice_service_contract(sc_b["id"], "2026-12-31T00:00:00Z", VM1)
        validate_error(resp, ApiErrorId.ERR_NOTICE_WINDOW_MISSED, 409)
        after = get_success_data(api.get_service_contract(sc_b["id"], VM1))
        assert after["status"] == "UNDER_REVIEW", "a missed window must not mutate"

    def test_decision_deadline_is_term_end_minus_notice_days(self, api):
        """PRD §3.7: "The contract opens `IDENTIFIED` with its
        `decision_deadline` computed as `term_end_date` minus
        `cancellation_notice_days` calendar days — the last day on which notice
        may be sent."
        PRD §3.7: "Notice requires the logical clock to be on or before the
        `decision_deadline` — the deadline day itself is still allowed, and a
        clock past the deadline is rejected with `ERR_NOTICE_WINDOW_MISSED`..."

        Design: Difficulty/boundary_precision_check/service_contract_notice_deadline_boundary
        """
        acq = create_kicked_off_acquisition(property_name="Boundary Two C")
        sc = get_success_data(api.create_service_contract(
            create_service_contract_payload(acq["id"]), VM1), 201)
        assert sc["decision_deadline"] == "2026-11-01T00:00:00Z"

        get_success_data(api.begin_review_service_contract(sc["id"], VM1))
        get_success_data(api.set_clock("2026-11-02T00:00:00Z", ADMIN))
        resp = api.send_notice_service_contract(sc["id"], "2026-12-31T00:00:00Z", VM1)
        validate_error(resp, ApiErrorId.ERR_NOTICE_WINDOW_MISSED, 409)


class TestAutoRenewSweep:
    def test_auto_renew_sweep_on_clock_advance(self, api):
        """PRD §2.7: "At startup, before any operator intervention, the logical
        clock reads exactly 2026-08-01T00:00:00Z, and it never falls back to
        wall-clock time."
        PRD §3.7: "Contracts that nobody touches are not inert: when the
        logical clock advances past the `decision_deadline` of an `IDENTIFIED`
        or `UNDER_REVIEW` contract whose `auto_renew` is true, the auto-renew
        sweep moves it to the terminal `AUTO_RENEWED` state."

        Design: Corner/state_machines/auto_renew_sweep_on_clock_advance
        """
        acq = create_kicked_off_acquisition(property_name="Sweep Deal")
        sc_a = get_success_data(api.create_service_contract(
            create_service_contract_payload(acq["id"], vendor_name="LiftCo",
                                            auto_renew=True), VM1), 201)
        get_success_data(api.begin_review_service_contract(sc_a["id"], VM1))
        sc_b = get_success_data(api.create_service_contract(
            create_service_contract_payload(
                acq["id"], vendor_name="CleanCo", service_type="LANDSCAPING",
                monthly_cost_cents=120000, cancellation_penalty_cents=50000),
            VM1), 201)  # auto_renew False, stays IDENTIFIED

        # At the default clock 2026-08-01 the deadline (2026-11-01) has not passed.
        get_success_data(api.set_clock("2026-11-02T00:00:00Z", ADMIN))
        a_now = get_success_data(api.get_service_contract(sc_a["id"], VM1))
        b_now = get_success_data(api.get_service_contract(sc_b["id"], VM1))
        assert a_now["status"] == "AUTO_RENEWED"
        assert b_now["status"] == "IDENTIFIED", (
            "the sweep only touches auto_renew contracts"
        )


class TestMarkCancelled:
    def test_mark_cancelled_waits_for_effective_date(self, api):
        """PRD §3.7: "Once the logical clock reaches the recorded
        `cancellation_effective_date`, the contract may be marked cancelled
        into the terminal `CANCELLED_EFFECTIVE` state; marking earlier is
        rejected with `ERR_CANCELLATION_NOT_YET_EFFECTIVE`."

        Design: Corner/state_machines/mark_cancelled_waits_for_effective_date
        """
        acq = create_kicked_off_acquisition(property_name="Cancel Deal")
        sc = get_success_data(api.create_service_contract(
            create_service_contract_payload(
                acq["id"], vendor_name="CleanCo", service_type="LANDSCAPING",
                monthly_cost_cents=120000, cancellation_penalty_cents=50000),
            VM1), 201)
        get_success_data(api.begin_review_service_contract(sc["id"], VM1))
        get_success_data(api.set_clock("2026-11-01T00:00:00Z", ADMIN))
        get_success_data(api.send_notice_service_contract(
            sc["id"], "2026-12-31T00:00:00Z", VM1))

        resp = api.mark_cancelled_service_contract(sc["id"], VM1)
        validate_error(resp, ApiErrorId.ERR_CANCELLATION_NOT_YET_EFFECTIVE, 409)

        get_success_data(api.set_clock("2026-12-31T00:00:00Z", ADMIN))
        cancelled = validate_success(api.mark_cancelled_service_contract(sc["id"], VM1))
        assert cancelled["status"] == "CANCELLED_EFFECTIVE"


class TestInsuranceRiskTierBoundaryAndOverride:
    def test_insurance_risk_tier_boundary_and_override(self, api):
        """PRD §3.7: "The `loss_ratio` is the `loss_run_total_cents` divided by
        three times the `annual_premium_cents`. The `risk_tier` is `LOW` when
        the ratio is below 0.40, `ELEVATED` when it is at least 0.40 and below
        0.80, and `HIGH` when it is at least 0.80 — the comparison is exact
        decimal, so a ratio of precisely 0.80 is `HIGH`. Assuming a reviewed
        policy moves it to `ASSUMED` and enters it into the prepaid-expense
        proration input set; assuming a `HIGH`-tier policy requires the caller
        to pass `override_high_risk` as true, and is otherwise rejected with
        `ERR_HIGH_RISK_POLICY_REQUIRES_OVERRIDE`."

        Design: Corner/calculations/insurance_risk_tier_boundary_and_override
        """
        acq = create_kicked_off_acquisition(property_name="Ins Deal")
        # ratio exactly 0.80: 2880000 / (1200000 x 3) -> HIGH.
        pol_h = get_success_data(api.create_insurance_policy(
            create_insurance_policy_payload(
                acq["id"], carrier_name="Risky Mutual",
                loss_run_total_cents=2_880_000, open_claims_count=2),
            ANALYST), 201)
        # ratio 2879999/3600000 < 0.80 -> ELEVATED.
        pol_e = get_success_data(api.create_insurance_policy(
            create_insurance_policy_payload(
                acq["id"], policy_type="GENERAL_LIABILITY",
                carrier_name="Calm Mutual",
                loss_run_total_cents=2_879_999, open_claims_count=1),
            ANALYST), 201)

        reviewed_h = get_success_data(api.review_loss_runs(pol_h["id"], UM1))
        reviewed_e = get_success_data(api.review_loss_runs(pol_e["id"], UM1))
        assert reviewed_h["risk_tier"] == "HIGH"
        assert reviewed_e["risk_tier"] == "ELEVATED"

        resp = api.assume_insurance_policy(pol_h["id"], UM1)
        validate_error(resp, ApiErrorId.ERR_HIGH_RISK_POLICY_REQUIRES_OVERRIDE, 409)

        assumed_h = validate_success(api.assume_insurance_policy(
            pol_h["id"], UM1, override_high_risk=True))
        assert assumed_h["status"] == "ASSUMED"

        assumed_e = validate_success(api.assume_insurance_policy(pol_e["id"], UM1))
        assert assumed_e["status"] == "ASSUMED"
