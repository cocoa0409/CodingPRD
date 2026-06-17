"""Refund computation, aid clawback, conservation invariants, and OCC.

Covers difficulty queue A:
  - dual_variant_calc / refund_pro_rata_vs_state_table_diverge
  - combinatorial_formula / refund_round_once_sum_then_round
  - transitive_cascade / refund_settle_returns_aid_recomputes_ledger
  - compensating_invariant / refund_settle_conserves_returned_aid_equals_aid_return
And corner queue B:
  - validations / refund_create_on_non_withdrawn_agreement_rejected
  - validations / refund_buyers_remorse_full_refund_within_window
  - cross_cutting_complexity_layers / occ_correct_version_settle_succeeds
  - cross_cutting_complexity_layers / occ_stale_version_settle_rejected_412
"""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
)
from test_helpers import fixtures as fx

FAID = TEST_USERS["financial_aid_officer_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]


# --------------------------------------------------------------------------
# dual_variant_calc / refund_pro_rata_vs_state_table_diverge
# --------------------------------------------------------------------------
def test_refund_pro_rata_vs_state_table_diverge_on_same_agreement(api):
    """PRD §3.7: "the PRO_RATA method earns by actual progress: the earned
    fraction is clock_hours_completed divided by the program's
    required_clock_hours, capped at 1.0, and tuition_earned_cents is that
    fraction multiplied by contract_tuition_cents, rounded half-up once to whole
    cents."
    PRD §3.7: "The STATE_TABLE method earns by scheduled time instead of actual
    hours: compute the term fraction as elapsed divided by the span, then read a
    stepped retain rate ... at or below 0.75 retains 0.75 ... and
    tuition_earned_cents is that retain rate multiplied by contract_tuition_cents,
    rounded half-up once to whole cents."
    PRD §3.7: "The tuition_refund_cents is contract_tuition_cents minus
    tuition_earned_cents, floored at 0."

    Design: Difficulty/dual_variant_calc/refund_pro_rata_vs_state_table_diverge
    """
    # 1000h program, tuition 1,000,000; 250 THEORY hours; span 8; withdraw at term 6.
    _, _, agreement, _ = fx.setup_withdrawn_agreement_for_refund(
        theory_hours=250, contract_tuition_cents=1_000_000, scheduled_aid_cents=0,
        withdrawal_clock_term=6, cancellation_window_term_index=0,
        cohort_overrides={"start_term_index": 0, "end_term_index": 8},
    )
    rc_pr = validate_success(
        api.create_refund_case(
            {"agreement_id": agreement["id"], "method": "PRO_RATA", "withdrawal_term_index": 6}, FAID),
        expected_status=201)
    rc_st = validate_success(
        api.create_refund_case(
            {"agreement_id": agreement["id"], "method": "STATE_TABLE", "withdrawal_term_index": 6}, FAID),
        expected_status=201)

    # PRO_RATA: 250/1000 = 0.25 earned -> 250000 earned -> 750000 refund.
    assert rc_pr["tuition_refund_cents"] == 750_000, rc_pr
    # STATE_TABLE: term_fraction 6/8 = 0.75 -> retain 0.75 -> 750000 earned -> 250000 refund.
    assert rc_st["tuition_refund_cents"] == 250_000, rc_st
    assert rc_pr["tuition_refund_cents"] != rc_st["tuition_refund_cents"]


def test_refund_pro_rata_earned_off_actual_hours(api):
    """PRD §3.7: "the PRO_RATA method earns by actual progress: the earned
    fraction is clock_hours_completed divided by the program's
    required_clock_hours, capped at 1.0, and tuition_earned_cents is that
    fraction multiplied by contract_tuition_cents, rounded half-up once to whole
    cents."

    Design: Difficulty/dual_variant_calc/refund_pro_rata_vs_state_table_diverge
    """
    _, _, agreement, _ = fx.setup_withdrawn_agreement_for_refund(
        theory_hours=250, contract_tuition_cents=1_000_000, scheduled_aid_cents=0,
        withdrawal_clock_term=6, cancellation_window_term_index=0,
        cohort_overrides={"start_term_index": 0, "end_term_index": 8},
    )
    rc_pr = validate_success(
        api.create_refund_case(
            {"agreement_id": agreement["id"], "method": "PRO_RATA", "withdrawal_term_index": 6}, FAID),
        expected_status=201)
    assert rc_pr["tuition_earned_cents"] == 250_000, rc_pr
    assert rc_pr["tuition_refund_cents"] == 750_000, rc_pr


# --------------------------------------------------------------------------
# combinatorial_formula / refund_round_once_sum_then_round
# --------------------------------------------------------------------------
def test_refund_pro_rata_rounds_product_once(api):
    """PRD §3.7: "the PRO_RATA method earns by actual progress: the earned
    fraction is clock_hours_completed divided by the program's
    required_clock_hours, capped at 1.0, and tuition_earned_cents is that
    fraction multiplied by contract_tuition_cents, rounded half-up once to whole
    cents."
    PRD §2.6: "the multiplication is performed once on the full amount and then
    rounded half-up to a whole number of cents — sum-then-round, never per-term
    or per-draw rounding."

    Design: Difficulty/combinatorial_formula/refund_round_once_sum_then_round
    """
    # tuition 1000333, 333 hours / 1000 -> 0.333 fraction.
    _, _, agreement, _ = fx.setup_withdrawn_agreement_for_refund(
        theory_hours=333, contract_tuition_cents=1_000_333, scheduled_aid_cents=0,
        withdrawal_clock_term=5, cancellation_window_term_index=0,
        cohort_overrides={"start_term_index": 0, "end_term_index": 10},
    )
    rc = validate_success(
        api.create_refund_case(
            {"agreement_id": agreement["id"], "method": "PRO_RATA", "withdrawal_term_index": 5}, FAID),
        expected_status=201)
    # round_half_up(1000333 * 0.333) = round_half_up(333110.889) = 333111.
    assert rc["tuition_earned_cents"] == 333_111, rc
    assert rc["tuition_refund_cents"] == 667_222, rc


def test_refund_round_once_refund_equals_contract_minus_earned(api):
    """PRD §3.7: "The tuition_refund_cents is contract_tuition_cents minus
    tuition_earned_cents, floored at 0."
    PRD §2.6: "the multiplication is performed once on the full amount and then
    rounded half-up to a whole number of cents — sum-then-round, never per-term
    or per-draw rounding."

    Design: Difficulty/combinatorial_formula/refund_round_once_sum_then_round
    """
    _, _, agreement, _ = fx.setup_withdrawn_agreement_for_refund(
        theory_hours=333, contract_tuition_cents=1_000_333, scheduled_aid_cents=0,
        withdrawal_clock_term=5, cancellation_window_term_index=0,
        cohort_overrides={"start_term_index": 0, "end_term_index": 10},
    )
    rc = validate_success(
        api.create_refund_case(
            {"agreement_id": agreement["id"], "method": "PRO_RATA", "withdrawal_term_index": 5}, FAID),
        expected_status=201)
    assert rc["tuition_refund_cents"] == 1_000_333 - rc["tuition_earned_cents"], rc
    assert rc["tuition_refund_cents"] == 667_222, rc


# --------------------------------------------------------------------------
# transitive_cascade / refund_settle_returns_aid_recomputes_ledger
# --------------------------------------------------------------------------
def test_refund_settle_returns_aid_in_descending_index_order(api):
    """PRD §3.7: "the agreement's RELEASED aid draws are returned in descending
    disbursement_index order (latest draw first), and for each draw the system
    returns the smaller of the remaining amount to recover and that draw's
    amount_cents, transitions it RELEASED → RETURNED, reduces its amount_cents by
    the clawed-back share, and recomputes the agreement's disbursed_aid_cents and
    ledger_balance_cents; the cascade continues until the full aid_return_cents
    is consumed."
    PRD §3.7: "The aggregate aid_return_cents is the agreement's
    disbursed_aid_cents multiplied by the unearned fraction, rounded half-up once
    to whole cents, and then capped so it never exceeds disbursed_aid_cents."

    Design: Difficulty/transitive_cascade/refund_settle_returns_aid_recomputes_ledger
    """
    # 1000h program, tuition 1,000,000; 250 hours; two RELEASED draws 200000 each
    # (disbursed 400000); withdraw at term 6; PRO_RATA.
    _, _, agreement, disb_ids, refund, version = fx.setup_computed_refund_case(
        theory_hours=250, contract_tuition_cents=1_000_000, scheduled_aid_cents=400_000,
        withdrawal_clock_term=6, method="PRO_RATA", released_draws=(200_000, 200_000),
    )
    d1, d2 = disb_ids
    # earned_fraction 0.25 -> unearned 0.75 -> aid_return round(400000*0.75) = 300000.
    assert refund["aid_return_cents"] == 300_000, refund

    validate_success(
        api.settle_refund_case(refund["id"], {"expected_agreement_version": version}, FAID),
        expected_status=200)

    d2_after = validate_success(api.get_disbursement(d2, FAID))
    d1_after = validate_success(api.get_disbursement(d1, FAID))
    # Descending index: d2 returns first (200000 -> amount 0); d1 returns the
    # remaining 100000 (amount 200000 - 100000 = 100000). Per PRD §3.7 each
    # drawn-against draw "transitions it RELEASED -> RETURNED", so BOTH draws end
    # RETURNED (d1 too, despite only a partial clawback).
    assert d2_after["status"] == "RETURNED" and d2_after["amount_cents"] == 0, d2_after
    assert d1_after["status"] == "RETURNED" and d1_after["amount_cents"] == 100_000, d1_after

    # PRD §3.6: disbursed_aid_cents sums amount_cents over RELEASED draws only
    # (returned draws are excluded). Both draws are now RETURNED -> disbursed 0.
    agr_after = validate_success(api.get_agreement(agreement["id"], FAID))
    assert agr_after["disbursed_aid_cents"] == 0, agr_after


def test_refund_settle_recomputes_ledger_balance(api):
    """PRD §3.6: "The agreement's disbursed_aid_cents is the sum of amount_cents
    over the agreement's draws whose status is RELEASED (scheduled, returned, and
    cancelled draws are excluded)."
    PRD §3.6: "The agreement's ledger_balance_cents is contract_tuition_cents
    minus disbursed_aid_cents."

    Design: Difficulty/transitive_cascade/refund_settle_returns_aid_recomputes_ledger
    """
    _, _, agreement, disb_ids, refund, version = fx.setup_computed_refund_case(
        theory_hours=250, contract_tuition_cents=1_000_000, scheduled_aid_cents=400_000,
        withdrawal_clock_term=6, method="PRO_RATA", released_draws=(200_000, 200_000),
    )
    validate_success(
        api.settle_refund_case(refund["id"], {"expected_agreement_version": version}, FAID),
        expected_status=200)
    agr_after = validate_success(api.get_agreement(agreement["id"], FAID))
    # Per PRD §3.7 the cascade transitions every drawn-against draw RELEASED ->
    # RETURNED; per PRD §3.6 returned draws are excluded from disbursed_aid_cents.
    # Both draws are RETURNED after settle -> disbursed 0.
    # ledger_balance = 1,000,000 - 0 = 1,000,000.
    assert agr_after["disbursed_aid_cents"] == 0, agr_after
    assert agr_after["ledger_balance_cents"] == 1_000_000, agr_after


# --------------------------------------------------------------------------
# compensating_invariant / refund_settle_conserves_returned_aid_equals_aid_return
# --------------------------------------------------------------------------
def test_settle_returned_aid_sum_equals_aid_return_cents(api):
    """PRD §3.7: "the agreement's RELEASED aid draws are returned in descending
    disbursement_index order (latest draw first), and for each draw the system
    returns the smaller of the remaining amount to recover and that draw's
    amount_cents, transitions it RELEASED → RETURNED, reduces its amount_cents by
    the clawed-back share, and recomputes the agreement's disbursed_aid_cents and
    ledger_balance_cents; the cascade continues until the full aid_return_cents
    is consumed."

    Design: Difficulty/compensating_invariant/refund_settle_conserves_returned_aid_equals_aid_return
    """
    _, _, agreement, disb_ids, refund, version = fx.setup_computed_refund_case(
        theory_hours=250, contract_tuition_cents=1_000_000, scheduled_aid_cents=400_000,
        withdrawal_clock_term=6, method="PRO_RATA", released_draws=(200_000, 200_000),
    )
    d1, d2 = disb_ids
    prior = {d1: 200_000, d2: 200_000}
    assert refund["aid_return_cents"] == 300_000, refund

    validate_success(
        api.settle_refund_case(refund["id"], {"expected_agreement_version": version}, FAID),
        expected_status=200)

    clawed = 0
    for did in (d1, d2):
        after = validate_success(api.get_disbursement(did, FAID))
        assert after["status"] == "RETURNED", after
        clawed += prior[did] - after["amount_cents"]
    # Conservation: total clawed back == aid_return_cents.
    assert clawed == refund["aid_return_cents"] == 300_000


def test_settle_conserves_disbursed_aid(api):
    """PRD §3.6: "The agreement's disbursed_aid_cents is the sum of amount_cents
    over the agreement's draws whose status is RELEASED (scheduled, returned, and
    cancelled draws are excluded)."

    Design: Difficulty/compensating_invariant/refund_settle_conserves_returned_aid_equals_aid_return
    """
    _, _, agreement, disb_ids, refund, version = fx.setup_computed_refund_case(
        theory_hours=250, contract_tuition_cents=1_000_000, scheduled_aid_cents=400_000,
        withdrawal_clock_term=6, method="PRO_RATA", released_draws=(200_000, 200_000),
    )
    validate_success(
        api.settle_refund_case(refund["id"], {"expected_agreement_version": version}, FAID),
        expected_status=200)
    agr_after = validate_success(api.get_agreement(agreement["id"], FAID))
    # Per PRD §3.6 disbursed_aid_cents sums only RELEASED draws (returned excluded).
    # The cascade (PRD §3.7) transitions both drawn-against draws to RETURNED, so
    # disbursed drops from 400000 to 0.
    assert agr_after["disbursed_aid_cents"] == 0, agr_after


# --------------------------------------------------------------------------
# corner: refund_create_on_non_withdrawn_agreement_rejected
# --------------------------------------------------------------------------
def test_refund_create_on_enrolled_agreement_rejected(api):
    """PRD §3.7: "When a student withdraws, a financial-aid officer computes a
    RefundCase against the now-WITHDRAWN agreement ..."
    PRD §3.7: "It requires the case to be COMPUTED (else ERR_INVALID_STATE), the
    parent agreement to be WITHDRAWN (else ERR_AGREEMENT_NOT_WITHDRAWN) ..."

    Design: Corner/validations/refund_create_on_non_withdrawn_agreement_rejected
    """
    _, _, agreement = fx.setup_enrolled_agreement(
        program_overrides={"tuition_cents": 500_000},
        agreement_overrides={"contract_tuition_cents": 500_000},
    )
    resp = api.create_refund_case(
        {"agreement_id": agreement["id"], "method": "PRO_RATA", "withdrawal_term_index": 2}, FAID)
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_WITHDRAWN.value)


# --------------------------------------------------------------------------
# corner: refund_buyers_remorse_full_refund_within_window
# --------------------------------------------------------------------------
def test_refund_buyers_remorse_full_refund_within_window(api):
    """PRD §3.7: "If the withdrawal_term_index is at or before the agreement's
    cancellation_window_term_index, the school retains nothing and
    tuition_earned_cents is 0 regardless of method."
    PRD §3.7: "The tuition_refund_cents is contract_tuition_cents minus
    tuition_earned_cents, floored at 0."

    Design: Corner/validations/refund_buyers_remorse_full_refund_within_window
    """
    # cancellation window 3, withdraw at term 2 (within window), tuition 1,000,000.
    _, _, agreement, _ = fx.setup_withdrawn_agreement_for_refund(
        theory_hours=100, contract_tuition_cents=1_000_000, scheduled_aid_cents=0,
        withdrawal_clock_term=2, cancellation_window_term_index=3,
        cohort_overrides={"start_term_index": 0, "end_term_index": 8},
    )
    rc = validate_success(
        api.create_refund_case(
            {"agreement_id": agreement["id"], "method": "STATE_TABLE", "withdrawal_term_index": 2}, FAID),
        expected_status=201)
    assert rc["tuition_earned_cents"] == 0, rc
    assert rc["tuition_refund_cents"] == 1_000_000, rc


# --------------------------------------------------------------------------
# corner: occ_correct_version_settle_succeeds
# --------------------------------------------------------------------------
def test_occ_correct_version_settle_succeeds(api):
    """PRD §2.7: "Settlement proceeds only when expected_agreement_version equals
    the agreement's current version."
    PRD §3.7: "On settlement the case moves to SETTLED ..."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_settle_succeeds
    """
    _, _, agreement, _, refund, version = fx.setup_computed_refund_case(
        theory_hours=0, contract_tuition_cents=1_000_000, scheduled_aid_cents=0,
        withdrawal_clock_term=2, method="PRO_RATA", released_draws=None,
    )
    settled = validate_success(
        api.settle_refund_case(refund["id"], {"expected_agreement_version": version}, FAID),
        expected_status=200)
    assert settled["status"] == "SETTLED", settled


# --------------------------------------------------------------------------
# corner: occ_stale_version_settle_rejected_412
# --------------------------------------------------------------------------
def test_occ_stale_version_settle_rejected_412(api):
    """PRD §2.7: "If any other writer has advanced the agreement's version since
    the client read it — a later aid release, an aid return, an attendance
    recompute, or a withdrawal cascade — the settlement is rejected with
    ERR_STALE_VERSION and HTTP status 412."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_settle_rejected_412
    """
    _, _, agreement, _, refund, version = fx.setup_computed_refund_case(
        theory_hours=0, contract_tuition_cents=1_000_000, scheduled_aid_cents=0,
        withdrawal_clock_term=2, method="PRO_RATA", released_draws=None,
    )
    resp = api.settle_refund_case(refund["id"], {"expected_agreement_version": version - 1}, FAID)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
    rc_after = validate_success(api.get_refund_case(refund["id"], FAID))
    assert rc_after["status"] == "COMPUTED", rc_after
