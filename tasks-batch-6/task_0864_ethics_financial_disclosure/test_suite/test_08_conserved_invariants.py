"""Conserved-quantity invariants and the state-before-fiscal validation precedence.

Queue A: compensating_invariant (penalty ledger money, recusal count),
priority_pair_validation_conflict (invalid-state beats delinquent).
Queue B: pay-already-paid terminal lockdown.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    make_filer_headers,
    setup_accepted_late_statement, setup_filer_with_recusal,
    declare_recusal, get_filer, latest_penalty_for,
    register_jurisdiction, register_filer,
)


def test_assess_then_pay_conserves_outstanding_to_zero(api):
    """PRD 2.9: "at all times it equals the sum of `assessed_amount_cents` across that filer's
    penalties whose status is `ASSESSED`. Penalties that are still accruing, that have been paid,
    or that have been waived contribute nothing to this sum."
    PRD 3.4: "moves it `ASSESSED → PAID`, decrementing the filer's `outstanding_penalty_cents` by
    `assessed_amount_cents` and recomputing `compliance_status`."

    Design: Difficulty/compensating_invariant/penalty_outstanding_conserved
    """
    ctx = setup_accepted_late_statement(category="ELECTED", clock="2026-05-25T00:00:00Z",
                                        due_at="2026-04-15T00:00:00Z")
    pen = ctx["penalty"]
    assert pen["assessed_amount_cents"] == 45000
    paid = validate_success(
        api.pay_penalty(pen["id"], {"payment_ref": "chk-1"}, make_filer_headers(ctx["filer"]["id"])), 200)
    assert paid["status"] == "PAID"
    assert get_filer(ctx["filer"]["id"])["outstanding_penalty_cents"] == 0


def test_pay_restores_compliant(api):
    """PRD 2.9: "the filer is `COMPLIANT` when `outstanding_penalty_cents` is at most the
    delinquency block threshold of 10000 cents (that is, 100 dollars), and `DELINQUENT` when it
    exceeds that threshold."

    Design: Difficulty/compensating_invariant/penalty_outstanding_conserved
    """
    ctx = setup_accepted_late_statement(category="ELECTED", clock="2026-05-25T00:00:00Z",
                                        due_at="2026-04-15T00:00:00Z")
    api.pay_penalty(ctx["penalty"]["id"], {}, make_filer_headers(ctx["filer"]["id"]))
    assert get_filer(ctx["filer"]["id"])["compliance_status"] == "COMPLIANT"


def test_declare_two_resolve_one_leaves_count_one(api):
    """PRD 3.7: "Resolution requires the recusal to be `DECLARED`, moves it `DECLARED → RESOLVED`,
    and decrements the filer's `open_recusal_count` by 1, compensating the increment applied at
    declaration."

    Design: Difficulty/compensating_invariant/recusal_open_count_conserved
    """
    filer, rec1 = setup_filer_with_recusal(
        matter_id="M1", effective_start="2026-06-01T00:00:00Z",
        effective_end="2026-06-10T00:00:00Z")
    get_success_data(declare_recusal(
        filer["id"], matter_id="M2", effective_start="2026-06-01T00:00:00Z",
        effective_end="2026-06-10T00:00:00Z"))
    assert get_filer(filer["id"])["open_recusal_count"] == 2
    resolved = validate_success(
        api.resolve_recusal(rec1["id"], {"resolution_note": "cleared"},
                            make_filer_headers(filer["id"])), 200)
    assert resolved["status"] == "RESOLVED"
    assert get_filer(filer["id"])["open_recusal_count"] == 1


def test_open_recusal_count_matches_declared_after_resolve(api):
    """PRD 3.1: "`open_recusal_count` is the conserved number of the filer's recusals currently
    in `DECLARED` status."

    Design: Difficulty/compensating_invariant/recusal_open_count_conserved
    """
    filer, rec1 = setup_filer_with_recusal(
        matter_id="M1", effective_start="2026-06-01T00:00:00Z",
        effective_end="2026-06-10T00:00:00Z")
    get_success_data(declare_recusal(
        filer["id"], matter_id="M2", effective_start="2026-06-01T00:00:00Z",
        effective_end="2026-06-10T00:00:00Z"))
    api.resolve_recusal(rec1["id"], {}, make_filer_headers(filer["id"]))
    # One DECLARED row remains -> count 1, no drift.
    assert get_filer(filer["id"])["open_recusal_count"] == 1


def test_submit_accepted_statement_state_beats_delinquent(api):
    """PRD 2.11: "that the target is in a state from which the requested transition is defined,
    yielding `ERR_INVALID_STATE`; and then the endpoint-specific business rules described in
    Section 3".
    PRD 2.11: "delinquency block (`ERR_FILER_DELINQUENT`)".

    Design: Difficulty/priority_pair_validation_conflict/submit_invalid_state_beats_delinquent
    """
    ctx = setup_accepted_late_statement(category="ELECTED", clock="2026-05-25T00:00:00Z",
                                        due_at="2026-04-15T00:00:00Z")
    # Filer is now DELINQUENT (outstanding 45000) AND the statement is ACCEPTED.
    assert get_filer(ctx["filer"]["id"])["compliance_status"] == "DELINQUENT"
    res = api.submit_statement(
        ctx["statement"]["id"], {}, make_filer_headers(ctx["filer"]["id"]))
    validate_error(res, "ERR_INVALID_STATE")


def test_submit_on_accepted_statement_leaves_it_accepted(api, registrar_headers):
    """PRD 3.5: "Acceptance requires the statement to be `SUBMITTED` and moves it
    `SUBMITTED → ACCEPTED`".

    Design: Difficulty/priority_pair_validation_conflict/submit_invalid_state_beats_delinquent
    """
    ctx = setup_accepted_late_statement(category="ELECTED", clock="2026-05-25T00:00:00Z",
                                        due_at="2026-04-15T00:00:00Z")
    api.submit_statement(ctx["statement"]["id"], {}, make_filer_headers(ctx["filer"]["id"]))
    stmt = validate_success(api.get_statement(ctx["statement"]["id"], registrar_headers), 200)
    assert stmt["status"] == "ACCEPTED"


def test_pay_already_paid_penalty_invalid_state(api):
    """PRD 3.4: "Attempting to pay or waive a penalty that is not `ASSESSED` is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/pay_already_paid_penalty_returns_invalid_state
    """
    ctx = setup_accepted_late_statement(category="ELECTED", clock="2026-05-25T00:00:00Z",
                                        due_at="2026-04-15T00:00:00Z")
    fh = make_filer_headers(ctx["filer"]["id"])
    validate_success(api.pay_penalty(ctx["penalty"]["id"], {}, fh), 200)
    res = api.pay_penalty(ctx["penalty"]["id"], {}, fh)
    validate_error(res, "ERR_INVALID_STATE")
    assert get_filer(ctx["filer"]["id"])["outstanding_penalty_cents"] == 0
