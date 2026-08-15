"""Clearance gate ordering, escalation gates, and the high-dollar threshold."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    make_supervisor_headers,
    pledge_and_post_deposit,
    price_estimate,
    request_and_approve_authorization,
    setup_accepted_insured_estimate,
    setup_insured_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)

COUNSELOR = TEST_USERS["counselor_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]

# High-dollar fixture inputs: contracted rate 2000000 with 50% coinsurance and
# no deductible yields patient_responsibility_cents exactly at/under 1000000.
HD_BENEFITS = dict(deductible_total_cents=0, deductible_met_cents=0,
                   oop_max_cents=5000000, oop_met_cents=0, coinsurance_pct=50)


def _setup_high_dollar_case(mrn, rate_cents):
    return setup_accepted_insured_estimate(
        mrn=mrn, cpt_code="90020", list_price_cents=2500000,
        requires_auth_prior=False, bundling_rule="NONE", reduction_pct=None,
        rate_cents=rate_cents, **HD_BENEFITS)


class TestClearGateOrdering:
    def test_clear_auth_failure_beats_deposit_shortfall(self, api):
        """PRD §2.8: "At case clearance, the compliance gate
        (`ERR_AUTH_NOT_SATISFIED`) precedes both escalation gates — the
        missing-high-dollar-approval gate (`ERR_ESCALATION_REQUIRED`) before
        the open-escalation gate (`ERR_ESCALATION_PENDING`) — and the fiscal
        deposit gate (`ERR_DEPOSIT_SHORTFALL`) is evaluated last."

        Design: Difficulty/priority_pair_validation_conflict/clear_auth_failure_beats_deposit_shortfall
        """
        ctx = setup_accepted_insured_estimate(mrn="MRN-PR-1",
                                              requires_auth_prior=True)
        # Both violations hold: no authorization, and 100000 < 125000 posted.
        pledge_and_post_deposit(ctx["case"]["id"], 100000)
        res = api.clear_case(ctx["case"]["id"], SUPERVISOR)
        validate_error(res, ApiErrorId.ERR_AUTH_NOT_SATISFIED)
        case = validate_success(api.get_case(ctx["case"]["id"], SUPERVISOR), 200)
        assert case["status"] == "IN_REVIEW"

    def test_after_auth_fixed_the_deposit_gate_surfaces(self, api):
        """PRD §2.8: "At case clearance, the compliance gate
        (`ERR_AUTH_NOT_SATISFIED`) precedes both escalation gates — the
        missing-high-dollar-approval gate (`ERR_ESCALATION_REQUIRED`) before
        the open-escalation gate (`ERR_ESCALATION_PENDING`) — and the fiscal
        deposit gate (`ERR_DEPOSIT_SHORTFALL`) is evaluated last."
        PRD §3.9: "The fiscal gate comes last: when `deposit_posted_cents`
        falls short of `required_deposit_cents`, the clear is rejected with
        `ERR_DEPOSIT_SHORTFALL` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/clear_auth_failure_beats_deposit_shortfall
        """
        ctx = setup_accepted_insured_estimate(mrn="MRN-PR-1B",
                                              requires_auth_prior=True)
        pledge_and_post_deposit(ctx["case"]["id"], 100000)
        res = api.clear_case(ctx["case"]["id"], SUPERVISOR)
        validate_error(res, ApiErrorId.ERR_AUTH_NOT_SATISFIED)
        # Satisfy the compliance gate; the still-short deposit now surfaces.
        request_and_approve_authorization(ctx["case"]["id"],
                                          cpt_codes=("27447",))
        res2 = api.clear_case(ctx["case"]["id"], SUPERVISOR)
        validate_error(res2, ApiErrorId.ERR_DEPOSIT_SHORTFALL)
        case = validate_success(api.get_case(ctx["case"]["id"], SUPERVISOR), 200)
        assert case["status"] == "IN_REVIEW"


class TestEscalationGates:
    def test_clear_high_dollar_after_rejection_returns_escalation_required(self, api):
        """PRD §3.9: "a high-dollar case with neither an `APPROVED` high-dollar
        escalation for the active estimate nor one still `OPEN` — for instance
        after a rejection — is rejected with `ERR_ESCALATION_REQUIRED`
        (HTTP 409)".

        Design: Corner/validations/clear_high_dollar_after_rejection_returns_escalation_required
        """
        ctx = _setup_high_dollar_case("MRN-V-7", rate_cents=2000000)
        escalations, _m = validate_paginated(
            api.list_case_escalations(ctx["case"]["id"], SUPERVISOR))
        assert len(escalations) == 1 and escalations[0]["reason"] == "HIGH_DOLLAR"
        rejected = validate_success(api.reject_escalation(
            escalations[0]["id"], {"decision_note": "insufficient documentation"},
            make_supervisor_headers("sup-1")), 200)
        assert rejected["status"] == "REJECTED"
        # Deposit gate is satisfied (required = 25% of 1000000).
        pledge_and_post_deposit(ctx["case"]["id"], 250000)
        res = api.clear_case(ctx["case"]["id"], SUPERVISOR)
        validate_error(res, ApiErrorId.ERR_ESCALATION_REQUIRED)
        case = validate_success(api.get_case(ctx["case"]["id"], SUPERVISOR), 200)
        assert case["status"] == "IN_REVIEW"

    def test_clear_with_open_escalation_returns_escalation_pending(self, api):
        """PRD §3.9: "any escalation still `OPEN`, whatever its reason, is
        rejected with `ERR_ESCALATION_PENDING` (HTTP 409)."

        Design: Corner/validations/clear_with_open_escalation_returns_escalation_pending
        """
        ctx = _setup_high_dollar_case("MRN-V-8", rate_cents=2000000)
        escalations, _m = validate_paginated(
            api.list_case_escalations(ctx["case"]["id"], SUPERVISOR))
        assert len(escalations) == 1 and escalations[0]["status"] == "OPEN"
        pledge_and_post_deposit(ctx["case"]["id"], 250000)
        res = api.clear_case(ctx["case"]["id"], SUPERVISOR)
        validate_error(res, ApiErrorId.ERR_ESCALATION_PENDING)
        case = validate_success(api.get_case(ctx["case"]["id"], SUPERVISOR), 200)
        assert case["status"] == "IN_REVIEW"

    def test_clear_with_deposit_shortfall_returns_409(self, api):
        """PRD §3.9: "The fiscal gate comes last: when `deposit_posted_cents`
        falls short of `required_deposit_cents`, the clear is rejected with
        `ERR_DEPOSIT_SHORTFALL` (HTTP 409)."

        Design: Corner/validations/clear_with_deposit_shortfall_returns_409
        """
        ctx = setup_accepted_insured_estimate(mrn="MRN-V-9",
                                              requires_auth_prior=True)
        request_and_approve_authorization(ctx["case"]["id"],
                                          cpt_codes=("27447",))
        # Auth and escalation gates pass; only the fiscal gate can fire.
        pledge_and_post_deposit(ctx["case"]["id"], 100000)
        res = api.clear_case(ctx["case"]["id"], SUPERVISOR)
        validate_error(res, ApiErrorId.ERR_DEPOSIT_SHORTFALL)


class TestHighDollarThreshold:
    def test_exactly_at_threshold_flags_and_opens_escalation(self, api):
        """PRD §3.4: "the threshold is one million cents — ten thousand
        dollars — and an estimate at exactly the threshold counts as
        high-dollar."
        PRD §3.4: "When the flag comes up true, the system opens a high-dollar
        escalation against the estimate, marked `OPEN`, recorded as opened by
        the literal string `"system"`, carrying `trigger_amount_cents` equal to
        the patient responsibility".

        Design: Difficulty/boundary_precision_check/high_dollar_threshold_exact_vs_one_cent_below
        """
        ctx = setup_insured_scenario(
            mrn="MRN-B-1", cpt_code="90020", list_price_cents=2500000,
            bundling_rule="NONE", reduction_pct=None, rate_cents=2000000,
            **HD_BENEFITS)
        priced = price_estimate(ctx["estimate"]["id"])
        assert priced["patient_responsibility_cents"] == 1000000
        assert priced["high_dollar_flag"] is True, "exactly the threshold counts"
        escalations, meta = validate_paginated(
            api.list_case_escalations(ctx["case"]["id"], SUPERVISOR))
        assert meta["total_count"] == 1
        esc = escalations[0]
        assert esc["reason"] == "HIGH_DOLLAR"
        assert esc["status"] == "OPEN"
        assert esc["opened_by_user_id"] == "system"
        assert esc["trigger_amount_cents"] == 1000000
        assert esc["estimate_id"] == ctx["estimate"]["id"]

    def test_one_cent_below_threshold_does_not_flag(self, api):
        """PRD §3.4: "the threshold is one million cents — ten thousand
        dollars — and an estimate at exactly the threshold counts as
        high-dollar."

        Design: Difficulty/boundary_precision_check/high_dollar_threshold_exact_vs_one_cent_below
        """
        ctx = setup_insured_scenario(
            mrn="MRN-B-2", cpt_code="90021", list_price_cents=2499997,
            bundling_rule="NONE", reduction_pct=None, rate_cents=1999998,
            **HD_BENEFITS)
        priced = price_estimate(ctx["estimate"]["id"])
        assert priced["patient_responsibility_cents"] == 999999
        assert priced["high_dollar_flag"] is False, "one cent below the threshold"
        escalations, meta = validate_paginated(
            api.list_case_escalations(ctx["case"]["id"], SUPERVISOR))
        assert meta["total_count"] == 0, "no escalation opens below the threshold"
