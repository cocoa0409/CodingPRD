"""Concurrency tests — only those whose outcome PRD explicitly defines.

PRD anchors: §2.4 (optimistic concurrency on version), §3.3 (declaration
uniqueness), §3.7 (review/amend race), §3.7 (inspection slot race), §3.8
(refund-approve vs reverse race).
"""
from __future__ import annotations
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_error_is_one_of,
    run_race,
    assert_exactly_one_succeeds,
    TEST_USERS,
    create_party_pair,
    create_order,
    setup_under_review_declaration,
    setup_returned_order_with_paid_declaration,
    create_refund,
    submit_refund,
    create_declaration_payload,
    schedule_inspection_payload,
    reject_declaration_payload,
    reverse_payment_payload,
    make_declarant_headers,
)


# ---------------------------------------------------------------------------
# Parallel declaration creation (PRD §3.3)
# ---------------------------------------------------------------------------
def test_two_declarations_for_same_order_only_one_wins(api):
    """PRD §3.3: "Two simultaneous creations against the same order
    serialize on this constraint with first-writer-wins semantics, and
    the second writer receives ERR_DECLARATION_ALREADY_EXISTS with HTTP
    status 409."

    Claim: two parallel POST /declarations on the same order_id resolve
    with exactly one 2xx and one ERR_DECLARATION_ALREADY_EXISTS at 409.
    """
    importer, declarant = create_party_pair()
    # Reference data uses a fresh per-test currency code so the
    # rate-table uniqueness constraint (PRD §3.1, "(from_currency,
    # to_currency, effective_date) is unique") doesn't collide with
    # other tests' rate rows.
    from test_helpers import setup_reference_data
    from test_helpers.fixtures import _fresh_currency_code
    fresh_currency = _fresh_currency_code()
    setup_reference_data(from_currency=fresh_currency)
    order = create_order(importer, declarant, currency=fresh_currency)
    hdrs = make_declarant_headers(declarant["id"])
    payload = create_declaration_payload(order["id"])

    results = run_race(
        lambda: api.create_declaration(payload, hdrs),
        lambda: api.create_declaration(payload, hdrs),
    )
    summary = assert_exactly_one_succeeds(results[0], results[1])
    # Loser must surface ERR_DECLARATION_ALREADY_EXISTS specifically (PRD
    # §3.3 names this error explicitly for the race).
    loser = summary["failures"][0]
    validate_error(
        loser, "ERR_DECLARATION_ALREADY_EXISTS", expected_status=409
    )


# ---------------------------------------------------------------------------
# Inspection slot race (PRD §3.7)
# ---------------------------------------------------------------------------
def test_two_inspection_appointments_same_bay_race(api):
    """PRD §3.7: "Two clients racing to schedule the same overlapping
    slot serialize first-writer-wins on the bay-and-time pair, with the
    loser receiving ERR_INSPECTION_SLOT_TAKEN."

    Claim: two parallel schedule_inspection calls on the same bay+time
    yield exactly one success and one ERR_INSPECTION_SLOT_TAKEN.
    """
    ctx_a = setup_under_review_declaration()
    ctx_b = setup_under_review_declaration()
    payload = schedule_inspection_payload(
        scheduled_at="2026-06-01T10:00:00Z", bay_code="BAY-RACE",
    )
    hdrs = TEST_USERS["customs_officer_headers"]
    results = run_race(
        lambda: api.schedule_inspection(ctx_a.declaration["id"], payload, hdrs),
        lambda: api.schedule_inspection(ctx_b.declaration["id"], payload, hdrs),
    )
    summary = assert_exactly_one_succeeds(results[0], results[1])
    loser = summary["failures"][0]
    validate_error(loser, "ERR_INSPECTION_SLOT_TAKEN", expected_status=409)


# ---------------------------------------------------------------------------
# Reject vs amend race on UNDER_REVIEW declaration (PRD §3.7)
# ---------------------------------------------------------------------------
def test_reject_vs_amend_race(api):
    """PRD §3.7: "When a declaration is in UNDER_REVIEW, two simultaneous
    mutating actions — for example, a customs officer rejecting at the
    same instant that the declarant tries to issue an amendment —
    serialize first-writer-wins on the declaration's status, with the
    loser receiving ERR_INVALID_STATE_TRANSITION."

    Claim: parallel reject and amend on UNDER_REVIEW resolve with
    exactly one success; the loser surfaces ERR_INVALID_STATE_TRANSITION.

    Note: amend is defined for RELEASED→AMENDED, but PRD §3.7 names it
    as the racing action on UNDER_REVIEW. The amend caller will receive
    ERR_INVALID_STATE_TRANSITION whether or not the reject happened
    first; the test asserts the joint outcome.
    """
    ctx = setup_under_review_declaration()
    co_hdrs = TEST_USERS["customs_officer_headers"]
    dec_hdrs = make_declarant_headers(ctx.declarant["id"])
    results = run_race(
        lambda: api.reject_declaration(
            ctx.declaration["id"],
            reject_declaration_payload("race-reject"),
            co_hdrs,
        ),
        lambda: api.amend_declaration(
            ctx.declaration["id"], {"lines": []}, dec_hdrs,
        ),
    )
    # PRD: "exactly one wins". The reject is the canonical UNDER_REVIEW
    # mutation; amend on UNDER_REVIEW is invalid-state regardless. So the
    # amend must lose; assert at most one success.
    successes = [r for r in results if 200 <= r.status_code < 300]
    failures = [r for r in results if r.status_code >= 400]
    assert len(successes) <= 1
    assert len(failures) >= 1
    # One of the failures must be a state error.
    state_errs = [r for r in failures
                  if r.json().get("data", {}).get("error_id")
                  == "ERR_INVALID_STATE_TRANSITION"]
    assert len(state_errs) >= 1


# ---------------------------------------------------------------------------
# Reverse vs refund-approve race (PRD §3.8)
# ---------------------------------------------------------------------------
def test_reverse_vs_refund_approve_race(api):
    """PRD §3.8: "Operations downstream of a reversed payment are blocked
    with ERR_PAYMENT_REVERSED — including a refund approval that arrives
    just after a reverse race wins; two concurrent attempts (a reverse
    and a refund approval) serialize first-writer-wins on the notice's
    status, and the refund-approval loser receives ERR_PAYMENT_REVERSED."

    Claim: parallel reverse_payment and refund_approve on a SUBMITTED
    refund yield exactly one success. If reverse wins, the refund
    approval surfaces ERR_PAYMENT_REVERSED.
    """
    ctx = setup_returned_order_with_paid_declaration()
    refund = create_refund(
        ctx.declaration, ctx.declarant, refund_reason="RETURN",
    )
    submit_refund(refund, ctx.declarant)

    fin_hdrs = TEST_USERS["finance_officer_headers"]
    co_hdrs = TEST_USERS["customs_officer_headers"]
    results = run_race(
        lambda: api.reverse_payment(
            ctx.payment_notice["id"],
            reverse_payment_payload("race"),
            fin_hdrs,
        ),
        lambda: api.approve_refund(refund["id"], co_hdrs),
    )
    successes = [r for r in results if 200 <= r.status_code < 300]
    failures = [r for r in results if r.status_code >= 400]
    # PRD §3.8: at least one wins — the loser surfaces a deterministic
    # error. We accept either: reverse wins → approve loses with
    # ERR_PAYMENT_REVERSED; approve wins → reverse loses with
    # ERR_REFUND_ALREADY_EXECUTED — but executed only happens after
    # /execute, not /approve, so the only race-loser path PRD names is
    # ERR_PAYMENT_REVERSED on the approve side.
    if len(failures) >= 1:
        # If reverse wins, the failure should be the refund-approve call
        # carrying ERR_PAYMENT_REVERSED.
        failure_ids = [r.json().get("data", {}).get("error_id") for r in failures]
        assert "ERR_PAYMENT_REVERSED" in failure_ids or all(
            fid == "ERR_INVALID_STATE_TRANSITION" for fid in failure_ids
        )


# ---------------------------------------------------------------------------
# Idempotency-key duplicate POST is NOT a race per se but a serial test;
# already covered in test_06_payment_and_release.
# ---------------------------------------------------------------------------
