"""Evidence logging, review loop, admission, materiality-amount consistency."""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    make_manager_headers,
    create_adjuster, create_investigator, create_claim, create_referral,
    triage_referral, accept_referral, open_case, assign_investigator,
    log_evidence, submit_evidence_review, admit_evidence,
    setup_case_under_investigation, setup_case_with_admitted_evidence,
)
from test_helpers.api_client import api_client


class TestCyclicReviewLoop:
    """Difficulty/non_linear_state_machine/evidence_cyclic_review_loop"""

    def _setup_under_review_evidence(self):
        ctx = setup_case_under_investigation()
        ev = log_evidence(ctx["case"], ctx["investigator"],
                          evidence_type="STATEMENT", materiality="SUPPORTING",
                          fraud_amount_cents=0)
        ev = submit_evidence_review(ctx["case"], ev, ctx["investigator"])
        ctx["evidence"] = ev
        return ctx

    def test_under_review_can_return_to_logged_and_reenter(self, api):
        """PRD §3.4: "returning it for more work moves it back to `LOGGED` with a
        `note` — the review loop is cyclic, and an item may pass through
        `UNDER_REVIEW` more than once."

        Design: Difficulty/non_linear_state_machine/evidence_cyclic_review_loop
        """
        ctx = self._setup_under_review_evidence()
        mh = ctx["manager_headers"]
        case = ctx["case"]
        inv = ctx["investigator"]
        ev = ctx["evidence"]
        # First return
        resp = api_client.return_evidence_for_more_work(
            case["id"], ev["id"], {"note": "need clearer chain"}, mh)
        data = validate_success(resp)
        assert data["status"] == "LOGGED"
        # Re-submit
        resp2 = api_client.submit_evidence_review(case["id"], ev["id"],
                                                  ctx["investigator_headers"])
        data2 = validate_success(resp2)
        assert data2["status"] == "UNDER_REVIEW"

    def test_second_full_cycle_completes(self, api):
        """PRD §3.4: "the review loop is cyclic, and an item may pass through
        `UNDER_REVIEW` more than once."

        Design: Difficulty/non_linear_state_machine/evidence_cyclic_review_loop
        """
        ctx = self._setup_under_review_evidence()
        mh = ctx["manager_headers"]
        case = ctx["case"]
        ev = ctx["evidence"]
        ih = ctx["investigator_headers"]
        # Cycle 1
        api_client.return_evidence_for_more_work(case["id"], ev["id"], {"note": "x"}, mh)
        api_client.submit_evidence_review(case["id"], ev["id"], ih)
        # Cycle 2
        resp = api_client.return_evidence_for_more_work(case["id"], ev["id"],
                                                        {"note": "still not right"}, mh)
        data = validate_success(resp)
        assert data["status"] == "LOGGED"


class TestMaterialityAmountConsistency:
    def test_substantive_with_zero_amount_rejected(self, api):
        """PRD §3.4: "Materiality and amount must agree: a `SUBSTANTIVE` item with
        a zero amount, or an `IMMATERIAL` item with a positive amount, is rejected
        with `ERR_MATERIALITY_AMOUNT_MISMATCH`."

        Design: Corner/validations/substantive_evidence_requires_positive_amount
        """
        ctx = setup_case_under_investigation()
        resp = api_client.create_evidence(
            ctx["case"]["id"],
            {"evidence_type": "RECORDS", "collected_at": "2026-08-10T00:00:00Z",
             "custodian": "I", "materiality": "SUBSTANTIVE", "fraud_amount_cents": 0},
            ctx["investigator_headers"])
        validate_error(resp, ApiErrorId.ERR_MATERIALITY_AMOUNT_MISMATCH)


class TestAdmitIdempotency:
    def test_second_admit_returns_invalid_state(self, api):
        """PRD §3.4: "`ADMITTED`, `EXCLUDED`, and `SEALED` are terminal for
        evidence."
        PRD §2.6: "Target state — a failing state-machine precondition on the
        addressed resource yields `ERR_INVALID_STATE`."

        Design: Corner/state_machines/admit_twice_returns_invalid_state
        """
        ctx = setup_case_with_admitted_evidence(
            evidence_overrides={"materiality": "SUPPORTING", "fraud_amount_cents": 0})
        case = ctx["case"]
        ev = ctx["evidence"]
        mh = ctx["manager_headers"]
        # Evidence is ADMITTED; second admit must fail
        resp = api_client.admit_evidence(
            case["id"], ev["id"], {"expected_case_version": case["version"]}, mh)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestDerivedFieldReconciliation:
    def test_substantiated_total_sums_two_admitted_substantive_items(self, api):
        """PRD §3.4: "That running total is exactly the sum of `fraud_amount_cents`
        over the case's evidence that is both `ADMITTED` and `SUBSTANTIVE`"

        Design: Corner/cross_cutting_layers/derived_field_reconciliation_case_substantiated
        """
        ctx = setup_case_under_investigation(
            claimed_amount_cents=10_000_000,
            red_flag_codes=["PRIOR_FRAUD_CONVICTION"])
        case = ctx["case"]
        inv = ctx["investigator"]
        mh = ctx["manager_headers"]
        ev1 = log_evidence(case, inv, evidence_type="RECORDS",
                           materiality="SUBSTANTIVE", fraud_amount_cents=100_000)
        ev1 = submit_evidence_review(case, ev1, inv)
        ev1, case = admit_evidence(case, ev1, case["version"], manager_headers=mh)
        ev2 = log_evidence(case, inv, evidence_type="SURVEILLANCE",
                           materiality="SUBSTANTIVE", fraud_amount_cents=50_000)
        ev2 = submit_evidence_review(case, ev2, inv)
        ev2, case = admit_evidence(case, ev2, case["version"], manager_headers=mh)
        assert case["substantiated_fraud_cents"] == 150_000, \
            f"expected 150000, got {case['substantiated_fraud_cents']}"


class TestSubstantiatedTotalFiltering:
    def test_immaterial_and_supporting_excluded_from_substantiated_total(self, api):
        """PRD §3.4: "That running total is exactly the sum of `fraud_amount_cents`
        over the case's evidence that is both `ADMITTED` and `SUBSTANTIVE`"

        Design: Corner/calculations/substantiated_total_excludes_immaterial_evidence
        """
        ctx = setup_case_under_investigation(
            claimed_amount_cents=100_000_000,
            red_flag_codes=["PRIOR_FRAUD_CONVICTION"])
        case = ctx["case"]
        inv = ctx["investigator"]
        mh = ctx["manager_headers"]
        ev1 = log_evidence(case, inv, evidence_type="RECORDS",
                           materiality="SUBSTANTIVE", fraud_amount_cents=500_000)
        ev1 = submit_evidence_review(case, ev1, inv)
        ev1, case = admit_evidence(case, ev1, case["version"], manager_headers=mh)
        ev2 = log_evidence(case, inv, evidence_type="STATEMENT",
                           materiality="SUPPORTING", fraud_amount_cents=0)
        ev2 = submit_evidence_review(case, ev2, inv)
        ev2, case = admit_evidence(case, ev2, case["version"], manager_headers=mh)
        assert case["substantiated_fraud_cents"] == 500_000, \
            f"only SUBSTANTIVE contributes; got {case['substantiated_fraud_cents']}"
