"""The chronological coverage-year ledger, reimbursement math, OCC on the
PolicyYear, reversal compensation, and the Wellness bucket.

Difficulty queue: dual_variant_calc (ledger), combinatorial_formula (reimbursement),
compensating_invariant (reverse), adjudicate-stale-policy-year (OCC).
Corner queue: calculations (rounding), state_machines (wellness side_effect),
cross_cutting (version bump, wellness drawdown), consistency_model (immediate).
"""
from test_helpers import (
    validate_success, validate_error,
    set_clock, create_account, create_policy, activate_policy, create_condition,
    build_claim_in_review, adjudicate_approve, get_year_zero, get_year_zero_version,
    open_claim, add_line, upload_invoice, run_ocr, accept_invoice, submit_claim,
    begin_review,
    make_claims_adjuster_headers, make_underwriter_headers,
    ApiErrorId,
)


def _adj():
    return make_claims_adjuster_headers()


def _uw():
    return make_underwriter_headers()


def _open_active_policy(email, **policy_overrides):
    set_clock("2026-06-01T00:00:00Z")
    acct = create_account(email=email)
    pol = create_policy(acct["id"], **policy_overrides)
    activate_policy(acct["id"], pol["id"])
    return acct, pol


def test_ledger_reattributes_by_incident_date_not_approval_order(api):
    """PRD 3.7: "Because the whole year is re-attributed in incident order on each
    approval, a claim approved later but bearing an earlier incident date consumes
    deductible ahead of an already-approved later-incident claim, retroactively
    lowering the latter's reimbursement."

    Claim X (Mar incident, eligible 20000) approved first, then Claim Y (Feb incident,
    eligible 30000) approved second. Chronological re-attribution gives Y the deductible
    (25000) -> Y reimburses 4000 and X reimburses 16000; submission-order would give
    X 16000 then Y 20000.

    Design: Difficulty/dual_variant_calc/ledger_chronological_vs_submission_order_on_claim
    """
    acct, pol = _open_active_policy("dvl@x.com", annual_deductible_cents=25000,
                                    reimbursement_rate_bps=8000, annual_cap_cents=500000,
                                    waiting_period_days=14)
    cond = create_condition(acct["id"], pol["id"], name="ear", first_diagnosed_date="2026-02-15T00:00:00Z")

    cx = build_claim_in_review(acct["id"], pol["id"], condition_id=cond["id"],
                               claim_overrides={"incident_date": "2026-03-01T00:00:00Z"},
                               billed_amount_cents=20000)
    adjudicate_approve(acct["id"], pol["id"], cx["id"])

    cy = build_claim_in_review(acct["id"], pol["id"], condition_id=cond["id"],
                               claim_overrides={"incident_date": "2026-02-01T00:00:00Z"},
                               billed_amount_cents=30000)
    adjudicate_approve(acct["id"], pol["id"], cy["id"])

    y = validate_success(api.get_claim(cy["id"], _adj()))
    x = validate_success(api.get_claim(cx["id"], _adj()))
    assert y["deductible_applied_cents"] == 25000, f"Y deductible: {y['deductible_applied_cents']}"
    assert y["reimbursed_cents"] == 4000, f"Y reimbursed: {y['reimbursed_cents']}"
    assert x["deductible_applied_cents"] == 0, f"X deductible: {x['deductible_applied_cents']}"
    assert x["reimbursed_cents"] == 16000, f"X reimbursed: {x['reimbursed_cents']}"


def test_ledger_year_accumulators_reflect_chronological_attribution(api):
    """PRD 2.8: "It records, as computed accumulators, the deductible_met_cents consumed
    so far, the reimbursed_cents paid so far."
    PRD 3.7: "the platform reconciles the covering PolicyYear's deductible_met_cents,
    reimbursed_cents, and wellness_used_cents accumulators."

    After approving X (Mar, 20000) then Y (Feb, 30000) under a 25000 deductible / 80%
    rate, the year's deductible_met == 25000 and reimbursed == 4000 + 16000 == 20000.

    Design: Difficulty/dual_variant_calc/ledger_chronological_vs_submission_order_on_claim
    """
    acct, pol = _open_active_policy("dvl2@x.com", annual_deductible_cents=25000,
                                    reimbursement_rate_bps=8000, annual_cap_cents=500000,
                                    waiting_period_days=14)
    cond = create_condition(acct["id"], pol["id"], name="ear", first_diagnosed_date="2026-02-15T00:00:00Z")
    cx = build_claim_in_review(acct["id"], pol["id"], condition_id=cond["id"],
                               claim_overrides={"incident_date": "2026-03-01T00:00:00Z"}, billed_amount_cents=20000)
    adjudicate_approve(acct["id"], pol["id"], cx["id"])
    cy = build_claim_in_review(acct["id"], pol["id"], condition_id=cond["id"],
                               claim_overrides={"incident_date": "2026-02-01T00:00:00Z"}, billed_amount_cents=30000)
    adjudicate_approve(acct["id"], pol["id"], cy["id"])

    year = get_year_zero(acct["id"], pol["id"])
    assert year["deductible_met_cents"] == 25000, f"deductible_met: {year['deductible_met_cents']}"
    assert year["reimbursed_cents"] == 20000, f"reimbursed: {year['reimbursed_cents']}"


def test_reimbursement_clamped_by_remaining_annual_cap(api):
    """PRD 3.7: "the remaining cap is the greater of zero and the policy's
    annual_cap_cents minus the reimbursement paid so far; and that claim's
    reimbursed_cents is the lesser of the raw reimbursement and the remaining cap."

    First claim exactly meets the 25000 deductible (0 reimbursed); a second 700000
    eligible claim has raw reimbursement 560000 but is clamped to the 500000 cap.

    Design: Difficulty/combinatorial_formula/reimbursement_min_max_nested_deductible_cap
    """
    acct, pol = _open_active_policy("cf1@x.com", annual_deductible_cents=25000,
                                    reimbursement_rate_bps=8000, annual_cap_cents=500000,
                                    waiting_period_days=14)
    cond = create_condition(acct["id"], pol["id"], name="fracture", first_diagnosed_date="2026-01-20T00:00:00Z")

    c1 = build_claim_in_review(acct["id"], pol["id"], condition_id=cond["id"],
                               claim_overrides={"incident_date": "2026-02-01T00:00:00Z"},
                               billed_amount_cents=25000)
    adjudicate_approve(acct["id"], pol["id"], c1["id"])

    c2 = build_claim_in_review(acct["id"], pol["id"], condition_id=cond["id"],
                               claim_overrides={"incident_date": "2026-03-01T00:00:00Z"},
                               billed_amount_cents=700000)
    adjudicate_approve(acct["id"], pol["id"], c2["id"])

    data = validate_success(api.get_claim(c2["id"], _adj()))
    assert data["deductible_applied_cents"] == 0, f"deductible: {data['deductible_applied_cents']}"
    assert data["reimbursed_cents"] == 500000, f"reimbursed: {data['reimbursed_cents']}"


def test_capped_year_reimbursed_accumulator_equals_cap(api):
    """PRD 2.8: "the reimbursed_cents paid so far (which can never exceed the policy's
    annual cap)."
    PRD 3.7: "reimbursed_cents being capped at the policy's annual_cap_cents."

    After the deductible-meeting claim and the 700000-eligible claim clamped to 500000,
    the year's reimbursed_cents accumulator equals the 500000 cap.

    Design: Difficulty/combinatorial_formula/reimbursement_min_max_nested_deductible_cap
    """
    acct, pol = _open_active_policy("cf1b@x.com", annual_deductible_cents=25000,
                                    reimbursement_rate_bps=8000, annual_cap_cents=500000,
                                    waiting_period_days=14)
    cond = create_condition(acct["id"], pol["id"], name="fracture", first_diagnosed_date="2026-01-20T00:00:00Z")
    c1 = build_claim_in_review(acct["id"], pol["id"], condition_id=cond["id"],
                               claim_overrides={"incident_date": "2026-02-01T00:00:00Z"}, billed_amount_cents=25000)
    adjudicate_approve(acct["id"], pol["id"], c1["id"])
    c2 = build_claim_in_review(acct["id"], pol["id"], condition_id=cond["id"],
                               claim_overrides={"incident_date": "2026-03-01T00:00:00Z"}, billed_amount_cents=700000)
    adjudicate_approve(acct["id"], pol["id"], c2["id"])

    year = get_year_zero(acct["id"], pol["id"])
    assert year["reimbursed_cents"] == 500000, f"year reimbursed: {year['reimbursed_cents']}"


def test_reimbursement_rounds_half_up_per_claim(api):
    """PRD 3.7: "the raw reimbursement is the post-deductible amount multiplied by the
    rate, rounded half up to a whole cent."

    Deductible 0, rate 8000bps, eligible 1001 -> round_half_up(800.8) == 801.

    Design: Corner/calculations/reimbursement_round_half_up_precision
    """
    acct, pol = _open_active_policy("rnd@x.com", annual_deductible_cents=0,
                                    reimbursement_rate_bps=8000, annual_cap_cents=500000,
                                    waiting_period_days=14)
    cond = create_condition(acct["id"], pol["id"], first_diagnosed_date="2026-02-01T00:00:00Z")

    claim = build_claim_in_review(acct["id"], pol["id"], condition_id=cond["id"],
                                  billed_amount_cents=1001)
    adjudicate_approve(acct["id"], pol["id"], claim["id"])

    data = validate_success(api.get_claim(claim["id"], _adj()))
    assert data["reimbursed_cents"] == 801, f"expected 801, got {data['reimbursed_cents']}"


def test_approve_response_carries_computed_amounts_immediately(api):
    """PRD 3.7: "that claim's deductible_applied_cents is the lesser of the remaining
    deductible and the claim's eligible_amount_cents; the post-deductible amount is the
    claim's eligible_amount_cents minus its deductible_applied_cents; the raw
    reimbursement is the post-deductible amount multiplied by the rate, rounded half up
    to a whole cent."

    Eligible 40000, deductible 25000, rate 8000 -> deductible 25000, reimbursed 12000,
    visible in the adjudicate response itself.

    Design: Corner/consistency_model/approval_reflected_in_same_response_immediate
    """
    acct, pol = _open_active_policy("imm@x.com", annual_deductible_cents=25000,
                                    reimbursement_rate_bps=8000, annual_cap_cents=500000,
                                    waiting_period_days=14)
    cond = create_condition(acct["id"], pol["id"], first_diagnosed_date="2026-02-01T00:00:00Z")
    claim = build_claim_in_review(acct["id"], pol["id"], condition_id=cond["id"], billed_amount_cents=40000)

    version = get_year_zero_version(acct["id"], pol["id"])
    data = validate_success(api.adjudicate(
        claim["id"], {"decision": "APPROVE", "expected_policy_year_version": version}, _adj()))
    assert data["status"] == "APPROVED"
    assert data["deductible_applied_cents"] == 25000, f"deductible: {data['deductible_applied_cents']}"
    assert data["reimbursed_cents"] == 12000, f"reimbursed: {data['reimbursed_cents']}"


def test_approve_bumps_covering_policy_year_version(api):
    """PRD 3.7: "After computing the per-claim payable amounts, the platform reconciles
    the covering PolicyYear's deductible_met_cents, reimbursed_cents, and
    wellness_used_cents accumulators ... and increments both the claim version and the
    policy-year version by one."

    A freshly created year is version 1; after one approval it is version 2.

    Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_every_mutation
    """
    acct, pol = _open_active_policy("ver@x.com", annual_deductible_cents=25000,
                                    reimbursement_rate_bps=8000, annual_cap_cents=500000,
                                    waiting_period_days=14)
    cond = create_condition(acct["id"], pol["id"], first_diagnosed_date="2026-02-01T00:00:00Z")
    claim = build_claim_in_review(acct["id"], pol["id"], condition_id=cond["id"], billed_amount_cents=40000)

    before = get_year_zero(acct["id"], pol["id"])
    assert before["version"] == 1, f"year created at version 1, got {before['version']}"
    adjudicate_approve(acct["id"], pol["id"], claim["id"], expected_version=before["version"])

    after = get_year_zero(acct["id"], pol["id"])
    assert after["version"] == 2, f"expected version 2 after approval, got {after['version']}"
    approved = validate_success(api.get_claim(claim["id"], _adj()))
    assert approved["status"] == "APPROVED"


def test_wellness_claim_draws_bucket_not_deductible(api):
    """PRD 3.7: "When the claim being approved is of type WELLNESS, its
    deductible_applied_cents and reimbursed_cents are both set to zero, and instead it
    draws the Wellness allowance bucket: the remaining wellness allowance is the greater
    of zero and a per-year Wellness allowance of 30000 cents minus the year's
    wellness_used_cents, and the claim's wellness_paid_cents is the lesser of its
    eligible_amount_cents and that remaining allowance."

    WELLNESS claim eligible 12000 on a rider policy -> wellness_paid 12000,
    deductible_applied 0, reimbursed 0.

    Design: Corner/state_machines/wellness_claim_draws_bucket_not_deductible
    """
    acct, pol = _open_active_policy("well@x.com", annual_deductible_cents=25000,
                                    reimbursement_rate_bps=8000, annual_cap_cents=500000,
                                    waiting_period_days=14, wellness_rider=True)
    claim = build_claim_in_review(acct["id"], pol["id"],
                                  claim_overrides={"claim_type": "WELLNESS"}, billed_amount_cents=12000)
    adjudicate_approve(acct["id"], pol["id"], claim["id"])

    data = validate_success(api.get_claim(claim["id"], _adj()))
    assert data["wellness_paid_cents"] == 12000, f"wellness_paid: {data['wellness_paid_cents']}"
    assert data["deductible_applied_cents"] == 0
    assert data["reimbursed_cents"] == 0


def test_wellness_bucket_partial_drawdown_reconciles_year(api):
    """PRD 3.7: "the remaining wellness allowance is the greater of zero and a per-year
    Wellness allowance of 30000 cents minus the year's wellness_used_cents, and the
    claim's wellness_paid_cents is the lesser of its eligible_amount_cents and that
    remaining allowance."

    After a first WELLNESS claim used 12000, a second eligible 25000 draws only the
    remaining 18000, and the year's wellness_used_cents reconciles to 30000.

    Design: Corner/cross_cutting_complexity_layers/wellness_bucket_partial_drawdown_reconciliation
    """
    acct, pol = _open_active_policy("well2@x.com", annual_deductible_cents=25000,
                                    reimbursement_rate_bps=8000, annual_cap_cents=500000,
                                    waiting_period_days=14, wellness_rider=True)

    w1 = build_claim_in_review(acct["id"], pol["id"],
                               claim_overrides={"claim_type": "WELLNESS", "incident_date": "2026-03-01T00:00:00Z"},
                               billed_amount_cents=12000)
    adjudicate_approve(acct["id"], pol["id"], w1["id"])

    w2 = build_claim_in_review(acct["id"], pol["id"],
                               claim_overrides={"claim_type": "WELLNESS", "incident_date": "2026-04-01T00:00:00Z"},
                               billed_amount_cents=25000)
    adjudicate_approve(acct["id"], pol["id"], w2["id"])

    data = validate_success(api.get_claim(w2["id"], _adj()))
    assert data["wellness_paid_cents"] == 18000, f"w2 wellness_paid: {data['wellness_paid_cents']}"
    year = get_year_zero(acct["id"], pol["id"])
    assert year["wellness_used_cents"] == 30000, f"year wellness_used: {year['wellness_used_cents']}"


def test_deny_branch_zeroes_payable_and_leaves_year_untouched(api):
    """PRD 3.7: "Denial sets denial_reason from the supplied reason code, sets
    deductible_applied_cents, reimbursed_cents, and wellness_paid_cents all to zero, and
    increments the claim version by one. Critically, denial performs no ledger mutation:
    the covering PolicyYear's accumulators are left untouched."

    Design: Difficulty/non_linear_state_machine/claim_approve_vs_deny_divergent_branches
    """
    acct, pol = _open_active_policy("deny@x.com", annual_deductible_cents=25000,
                                    reimbursement_rate_bps=8000, annual_cap_cents=500000,
                                    waiting_period_days=14)
    cond = create_condition(acct["id"], pol["id"], name="gi", first_diagnosed_date="2026-02-01T00:00:00Z")
    claim = build_claim_in_review(acct["id"], pol["id"], condition_id=cond["id"], billed_amount_cents=40000)

    denied = validate_success(api.adjudicate(
        claim["id"], {"decision": "DENY", "reason": "ERR_PRE_EXISTING_EXCLUDED"}, _adj()))
    assert denied["status"] == "DENIED"
    assert denied["reimbursed_cents"] == 0

    year = get_year_zero(acct["id"], pol["id"])
    assert year["reimbursed_cents"] == 0, f"year reimbursed should be untouched, got {year['reimbursed_cents']}"


def test_approve_branch_books_reimbursement_into_year(api):
    """PRD 3.7: "Because the whole year is re-attributed in incident order on each
    approval ..." and "the platform reconciles the covering PolicyYear's
    deductible_met_cents, reimbursed_cents, and wellness_used_cents accumulators."

    Contrasting the deny branch: a single APPROVED claim (eligible 40000, deductible
    25000, 80%) books reimbursed_cents 12000 into the covering year.

    Design: Difficulty/non_linear_state_machine/claim_approve_vs_deny_divergent_branches
    """
    acct, pol = _open_active_policy("appr@x.com", annual_deductible_cents=25000,
                                    reimbursement_rate_bps=8000, annual_cap_cents=500000,
                                    waiting_period_days=14)
    cond = create_condition(acct["id"], pol["id"], name="gi", first_diagnosed_date="2026-02-01T00:00:00Z")
    claim = build_claim_in_review(acct["id"], pol["id"], condition_id=cond["id"], billed_amount_cents=40000)
    adjudicate_approve(acct["id"], pol["id"], claim["id"])

    year = get_year_zero(acct["id"], pol["id"])
    assert year["reimbursed_cents"] == 12000, f"year reimbursed: {year['reimbursed_cents']}"


def test_reverse_records_sentinel_denial_reason(api):
    """PRD 3.7: "then zeroes the claim's own deductible_applied_cents, reimbursed_cents,
    and wellness_paid_cents and records the sentinel denial_reason of ERR_CLAIM_REVERSED."

    Design: Difficulty/compensating_invariant/reverse_restores_policy_year_reimbursed
    """
    acct, pol = _open_active_policy("rev2@x.com", annual_deductible_cents=25000,
                                    reimbursement_rate_bps=8000, annual_cap_cents=500000,
                                    waiting_period_days=14)
    cond = create_condition(acct["id"], pol["id"], first_diagnosed_date="2026-02-01T00:00:00Z")
    claim = build_claim_in_review(acct["id"], pol["id"], condition_id=cond["id"], billed_amount_cents=40000)
    adjudicate_approve(acct["id"], pol["id"], claim["id"])
    version = get_year_zero_version(acct["id"], pol["id"])

    reversed_claim = validate_success(api.reverse_claim(
        claim["id"], {"expected_policy_year_version": version}, _adj()))
    assert reversed_claim["status"] == "DENIED"
    assert reversed_claim["denial_reason"] == "ERR_CLAIM_REVERSED", f"got {reversed_claim['denial_reason']}"


def test_reverse_restores_policy_year_reimbursed_to_zero(api):
    """PRD 3.7: "Reversal subtracts this claim's deductible_applied_cents,
    reimbursed_cents, and wellness_paid_cents from the covering PolicyYear's
    accumulators, restoring them to their pre-approval values ... The conserved quantity
    is the year's reimbursed_cents: after a reversal it must equal what it was before the
    reversed claim was ever approved."

    A single approved claim reversed leaves reimbursed_cents and deductible_met_cents at 0.

    Design: Difficulty/compensating_invariant/reverse_restores_policy_year_reimbursed
    """
    acct, pol = _open_active_policy("rev@x.com", annual_deductible_cents=25000,
                                    reimbursement_rate_bps=8000, annual_cap_cents=500000,
                                    waiting_period_days=14)
    cond = create_condition(acct["id"], pol["id"], first_diagnosed_date="2026-02-01T00:00:00Z")
    claim = build_claim_in_review(acct["id"], pol["id"], condition_id=cond["id"], billed_amount_cents=40000)
    adjudicate_approve(acct["id"], pol["id"], claim["id"])

    version_after_approve = get_year_zero_version(acct["id"], pol["id"])
    reversed_claim = validate_success(api.reverse_claim(
        claim["id"], {"expected_policy_year_version": version_after_approve}, _adj()))
    assert reversed_claim["status"] == "DENIED"
    assert reversed_claim["reimbursed_cents"] == 0

    year = get_year_zero(acct["id"], pol["id"])
    assert year["reimbursed_cents"] == 0, f"reimbursed should restore to 0, got {year['reimbursed_cents']}"
    assert year["deductible_met_cents"] == 0, f"deductible_met should restore to 0, got {year['deductible_met_cents']}"


class TestPolicyYearOCC:
    """Optimistic concurrency on the covering PolicyYear at adjudicate (PRD 2.7, 3.7)."""

    def _two_in_review_claims(self, email):
        acct, pol = _open_active_policy(email, annual_deductible_cents=25000,
                                        reimbursement_rate_bps=8000, annual_cap_cents=500000,
                                        waiting_period_days=14)
        cond = create_condition(acct["id"], pol["id"], first_diagnosed_date="2026-02-01T00:00:00Z")
        ca = build_claim_in_review(acct["id"], pol["id"], condition_id=cond["id"],
                                   claim_overrides={"incident_date": "2026-03-01T00:00:00Z"},
                                   billed_amount_cents=40000)
        cb = build_claim_in_review(acct["id"], pol["id"], condition_id=cond["id"],
                                   claim_overrides={"incident_date": "2026-04-01T00:00:00Z"},
                                   billed_amount_cents=40000)
        return acct, pol, ca, cb

    def test_stale_policy_year_version_rejected_on_second_adjudicate(self, api):
        """PRD 2.7: "If that value does not equal the covering PolicyYear's current
        version — for example because another adjuster approved a sibling claim against
        the same year and thereby consumed headroom since the caller last read it — the
        operation is rejected with ERR_STALE_POLICY_YEAR_VERSION and HTTP status 412."

        Approving claim A bumps the year version; adjudicating B with the pre-A version
        is rejected 412.

        Design: Difficulty/adjudicate-stale-policy-year/occ_stale_policy_year_on_second_adjudicate
        """
        acct, pol, ca, cb = self._two_in_review_claims("occ1@x.com")
        stale_version = get_year_zero_version(acct["id"], pol["id"])
        adjudicate_approve(acct["id"], pol["id"], ca["id"], expected_version=stale_version)

        resp = api.adjudicate(
            cb["id"], {"decision": "APPROVE", "expected_policy_year_version": stale_version}, _adj())
        validate_error(resp, ApiErrorId.ERR_STALE_POLICY_YEAR_VERSION.value)

        unchanged = validate_success(api.get_claim(cb["id"], _adj()))
        assert unchanged["status"] == "IN_REVIEW", f"B should stay IN_REVIEW, got {unchanged['status']}"

    def test_correct_policy_year_version_succeeds_on_second_adjudicate(self, api):
        """PRD 2.7: "The caller must re-read the PolicyYear and resubmit against its
        current version."
        PRD 3.7: "a claim approved later but bearing an earlier incident date consumes
        deductible ahead of an already-approved later-incident claim, retroactively
        lowering the latter's reimbursement."

        A (Mar incident) approved first consumes the 25000 deductible; B (Apr incident),
        re-read against the bumped version, approves with deductible 0 and reimburses
        32000 (80% of 40000).

        Design: Difficulty/adjudicate-stale-policy-year/occ_correct_policy_year_version_succeeds
        """
        acct, pol, ca, cb = self._two_in_review_claims("occ2@x.com")
        v0 = get_year_zero_version(acct["id"], pol["id"])
        adjudicate_approve(acct["id"], pol["id"], ca["id"], expected_version=v0)
        v1 = get_year_zero_version(acct["id"], pol["id"])

        approved_b = validate_success(api.adjudicate(
            cb["id"], {"decision": "APPROVE", "expected_policy_year_version": v1}, _adj()))
        assert approved_b["status"] == "APPROVED"

        a = validate_success(api.get_claim(ca["id"], _adj()))
        assert a["deductible_applied_cents"] == 25000, f"A deductible: {a['deductible_applied_cents']}"
        assert approved_b["deductible_applied_cents"] == 0, f"B deductible: {approved_b['deductible_applied_cents']}"
        assert approved_b["reimbursed_cents"] == 32000, f"B reimbursed: {approved_b['reimbursed_cents']}"

    def test_stale_version_leaves_year_accumulators_unchanged(self, api):
        """PRD 2.7: "the operation is rejected with ERR_STALE_POLICY_YEAR_VERSION and HTTP
        status 412. The caller must re-read the PolicyYear and resubmit against its
        current version."

        After A is approved (year reimbursed 12000), the rejected stale B adjudicate does
        not further mutate the year accumulators — reimbursed_cents stays at A's 12000.

        Design: Difficulty/adjudicate-stale-policy-year/occ_stale_policy_year_on_second_adjudicate
        """
        acct, pol, ca, cb = self._two_in_review_claims("occ1b@x.com")
        stale_version = get_year_zero_version(acct["id"], pol["id"])
        adjudicate_approve(acct["id"], pol["id"], ca["id"], expected_version=stale_version)
        year_after_a = get_year_zero(acct["id"], pol["id"])

        resp = api.adjudicate(
            cb["id"], {"decision": "APPROVE", "expected_policy_year_version": stale_version}, _adj())
        validate_error(resp, ApiErrorId.ERR_STALE_POLICY_YEAR_VERSION.value)

        year_after_reject = get_year_zero(acct["id"], pol["id"])
        assert year_after_reject["reimbursed_cents"] == year_after_a["reimbursed_cents"], (
            "rejected adjudicate must not change accumulators")
        assert year_after_a["reimbursed_cents"] == 12000, f"A reimbursed into year: {year_after_a['reimbursed_cents']}"

    def test_resubmit_with_current_version_bumps_year_again(self, api):
        """PRD 3.7: "increments both the claim version and the policy-year version by one."

        The first approval takes the year from version 1 to 2; re-reading version 2 and
        approving the second claim takes it to version 3.

        Design: Difficulty/adjudicate-stale-policy-year/occ_correct_policy_year_version_succeeds
        """
        acct, pol, ca, cb = self._two_in_review_claims("occ2b@x.com")
        v0 = get_year_zero_version(acct["id"], pol["id"])
        adjudicate_approve(acct["id"], pol["id"], ca["id"], expected_version=v0)
        v1 = get_year_zero_version(acct["id"], pol["id"])
        assert v1 == v0 + 1, f"expected version bump after first approve, {v0}->{v1}"

        validate_success(api.adjudicate(
            cb["id"], {"decision": "APPROVE", "expected_policy_year_version": v1}, _adj()))
        v2 = get_year_zero_version(acct["id"], pol["id"])
        assert v2 == v1 + 1, f"expected version bump after second approve, {v1}->{v2}"
