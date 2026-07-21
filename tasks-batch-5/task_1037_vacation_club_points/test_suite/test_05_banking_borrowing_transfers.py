"""Banking, borrowing, point conservation, and member-to-member transfers.

Queue A: dv_banking_standard_par_on_pointsbucket, ci_points_conserved_bank_then_borrow,
cesd_transfer_accept_blocked_by_suspended_receiver.
Queue B: late-bank, bank/borrow caps, transfer-complete, closed-bucket, non-pending
accept, transfer-not-found corners.
"""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    accept_transfer_payload,
    bank,
    bank_payload,
    borrow,
    borrow_payload,
    bucket_for_year,
    create_transfer_payload,
    generate_statement,
    make_member_headers,
    member_current_bucket,
    new_member,
    run_billing_cycle,
    set_clock,
    setup_pending_transfer,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


# ─── dv_banking_standard_par_on_pointsbucket ──────────────────────────────

def test_standard_bank_debits_source_at_par(api):
    """PRD §3.2: "The points always leave the source at par: the source bucket's
    banked_out rises by the requested points regardless of timing."

    Design: Difficulty/dual_variant_calc/dv_banking_standard_par_on_pointsbucket
    """
    set_clock("2026-07-01T00:00:00Z")
    member = new_member(owned_points=5000)
    bucket = member_current_bucket(member["id"])
    updated = validate_success(api.bank_points(bucket["id"], bank_payload(1000), make_member_headers(member["id"])), 200)
    assert updated["banked_out"] == 1000
    assert updated["points_available"] == 4000


def test_standard_bank_credits_next_year_at_par(api):
    """PRD §3.2: "If the logical clock's date is on or before that deadline, banking is
    at par and the next year's banked_in rises by the full requested points".

    Design: Difficulty/dual_variant_calc/dv_banking_standard_par_on_pointsbucket
    """
    set_clock("2026-07-01T00:00:00Z")
    member = new_member(owned_points=5000)
    bucket = member_current_bucket(member["id"])
    bank(bucket["id"], member["id"], 1000)
    next_bucket = bucket_for_year(member["id"], 2027)
    assert next_bucket["banked_in"] == 1000  # par, not 500


# ─── ci_points_conserved_bank_then_borrow ─────────────────────────────────

def _bank_then_borrow(api):
    set_clock("2026-07-01T00:00:00Z")
    member = new_member(owned_points=5000)
    bucket = member_current_bucket(member["id"])
    bank(bucket["id"], member["id"], 1000)
    borrow(bucket["id"], member["id"], 1000)
    return member, bucket


def test_bank_then_borrow_restores_source_available(api):
    """PRD §2.6: "The available balance, exposed as points_available, is the annual
    allotment (annual_allotment) plus everything credited in — points banked in from
    the prior year (banked_in), points borrowed in from the next year (borrowed_in) ...
    minus everything debited out: points banked out to the next year (banked_out)".

    Design: Difficulty/compensating_invariant/ci_points_conserved_bank_then_borrow
    """
    member, bucket = _bank_then_borrow(api)
    source = validate_success(api.get_points_bucket(bucket["id"], ADMIN), 200)
    assert source["banked_out"] == 1000
    assert source["borrowed_in"] == 1000
    assert source["points_available"] == 5000  # 5000 + 1000 borrowed_in - 1000 banked_out


def test_bank_then_borrow_conserves_member_total(api):
    """PRD §2.6: "points borrowed out to a prior year (`borrowed_out`)".
    PRD §3.2: "The receiving bucket's `borrowed_in` rises by the requested points and
    the next year's bucket's `borrowed_out` rises by the same amount."

    Design: Difficulty/compensating_invariant/ci_points_conserved_bank_then_borrow
    """
    member, _ = _bank_then_borrow(api)
    next_bucket = bucket_for_year(member["id"], 2027)
    assert next_bucket["banked_in"] == 1000
    assert next_bucket["borrowed_out"] == 1000
    assert next_bucket["points_available"] == 5000  # 5000 + 1000 banked_in - 1000 borrowed_out


# ─── cesd_transfer_accept_blocked_by_suspended_receiver ───────────────────

def _pending_transfer_to_suspended_receiver(api):
    """A->B 500 transfer PENDING while both ACTIVE; then B suspended via delinquency."""
    set_clock("2026-07-01T00:00:00Z")
    member_a = new_member(owned_points=5000)
    member_b = new_member(owned_points=5000)
    transfer = validate_success(
        api.create_transfer(create_transfer_payload(member_a["id"], member_b["id"], 500), make_member_headers(member_a["id"])),
        201,
    )
    generate_statement(member_b["id"], member_b["version"])  # B.version 1 -> 2, statement CURRENT
    set_clock("2026-08-16T00:00:00Z")
    run_billing_cycle()  # ages B's statement PAST_DUE and suspends B (past due + grace)
    return member_a, member_b, transfer


def test_accept_blocked_when_receiver_suspended(api):
    """PRD §3.8: "The receiving member then resolves the transfer by supplying an
    outcome of either ACCEPT or REJECT; a transfer can be resolved only while PENDING,
    and resolving anything else is rejected with ERR_INVALID_STATE, and both members
    must still be ACTIVE."

    Design: Difficulty/cross_entity_state_dependency/cesd_transfer_accept_blocked_by_suspended_receiver
    """
    _, member_b, transfer = _pending_transfer_to_suspended_receiver(api)
    resp = api.accept_transfer(transfer["id"], accept_transfer_payload("ACCEPT"), make_member_headers(member_b["id"]))
    validate_error(resp, ApiErrorId.ERR_MEMBER_SUSPENDED.value, 409)


def test_blocked_accept_leaves_transfer_pending(api):
    """PRD §3.8: "a transfer can be resolved only while `PENDING`, and resolving
    anything else is rejected with `ERR_INVALID_STATE`, and both members must still
    be `ACTIVE`." A blocked accept performs no transition.

    Design: Difficulty/cross_entity_state_dependency/cesd_transfer_accept_blocked_by_suspended_receiver
    """
    _, member_b, transfer = _pending_transfer_to_suspended_receiver(api)
    api.accept_transfer(transfer["id"], accept_transfer_payload("ACCEPT"), make_member_headers(member_b["id"]))
    rows = validate_success(api.list_member_transfers(member_b["id"], ADMIN), 200)
    match = [t for t in rows if t["id"] == transfer["id"]]
    assert match and match[0]["status"] == "PENDING", "a blocked accept must not transition the transfer"


# ─── Queue B corners ──────────────────────────────────────────────────────

def test_late_bank_credits_half(api):
    """PRD §3.2: "if the clock's date is after the deadline, the bank is late and the
    next year's banked_in rises by only the floor of half the requested points (the
    fractional point is dropped)." PRD §3.2: "the banking deadline, which falls 273
    days after January 1 of the source bucket's use year."

    Design: Corner/calculations/corner_late_bank_half_credit
    """
    set_clock("2026-07-01T00:00:00Z")
    member = new_member(owned_points=5000)
    bucket = member_current_bucket(member["id"])
    set_clock("2026-11-01T00:00:00Z")  # past the 2026-10-01 deadline
    updated = validate_success(api.bank_points(bucket["id"], bank_payload(1000), make_member_headers(member["id"])), 200)
    assert updated["banked_out"] == 1000
    assert updated["points_available"] == 4000
    next_bucket = bucket_for_year(member["id"], 2027)
    assert next_bucket["banked_in"] == 500


def test_bank_cap_exceeded(api):
    """PRD §3.2: "the requested points may not exceed the floor of one-half of the
    source bucket's annual_allotment, or the request is rejected with ERR_BANK_CAP_EXCEEDED".

    Design: Corner/calculations/corner_bank_cap_exceeded
    """
    set_clock("2026-07-01T00:00:00Z")
    member = new_member(owned_points=1000)  # cap floor(0.5*1000) = 500
    bucket = member_current_bucket(member["id"])
    resp = api.bank_points(bucket["id"], bank_payload(600), make_member_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_BANK_CAP_EXCEEDED.value, 422)


def test_borrow_cap_exceeded(api):
    """PRD §3.2: "the requested points may not exceed the floor of one-half of the
    source bucket's annual_allotment, or the request is rejected with ERR_BORROW_CAP_EXCEEDED".

    Design: Corner/calculations/corner_borrow_cap_exceeded
    """
    set_clock("2026-07-01T00:00:00Z")
    member = new_member(owned_points=1000)  # cap floor(0.5*1000) = 500
    bucket = member_current_bucket(member["id"])
    resp = api.borrow_points(bucket["id"], borrow_payload(600), make_member_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_BORROW_CAP_EXCEEDED.value, 422)


def test_accepted_transfer_moves_points(api):
    """PRD §3.8: "On ACCEPT the transfer moves to COMPLETED: the sender's bucket
    releases the escrow by reducing points_used by the transferred points and records
    transferred_out increased by that amount, while the receiver's current-use-year
    bucket records transferred_in increased by the same amount."

    Design: Corner/calculations/corner_transfer_complete_moves_points
    """
    ctx = setup_pending_transfer(points=500, owned_points=5000)
    completed = validate_success(
        api.accept_transfer(ctx["transfer"]["id"], accept_transfer_payload("ACCEPT"), make_member_headers(ctx["member_b"]["id"])),
        200,
    )
    assert completed["status"] == "COMPLETED"
    bucket_a = validate_success(api.get_points_bucket(ctx["bucket_a"]["id"], ADMIN), 200)
    bucket_b = validate_success(api.get_points_bucket(ctx["bucket_b"]["id"], ADMIN), 200)
    assert bucket_a["points_available"] == 4500 and bucket_a["transferred_out"] == 500
    assert bucket_b["points_available"] == 5500 and bucket_b["transferred_in"] == 500


def test_bank_on_closed_bucket_rejected(api):
    """PRD §3.10: "any OPEN points bucket whose use_year is now in the past ... moves
    to CLOSED. Once a bucket is CLOSED, any later attempt to bank from it, borrow
    against it, or reserve using it is rejected with ERR_BUCKET_CLOSED."

    Design: Corner/state_machines/corner_bank_on_closed_bucket
    """
    set_clock("2026-07-01T00:00:00Z")
    member = new_member(owned_points=5000)
    bucket = member_current_bucket(member["id"])
    set_clock("2027-01-02T00:00:00Z")
    run_billing_cycle()  # closes the 2026 bucket (clock year 2027 > use_year 2026)
    resp = api.bank_points(bucket["id"], bank_payload(100), make_member_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_BUCKET_CLOSED.value, 409)


def test_accept_completed_transfer_rejected(api):
    """PRD §3.8: "a transfer can be resolved only while `PENDING`, and resolving
    anything else is rejected with `ERR_INVALID_STATE`".

    Design: Corner/state_machines/corner_accept_nonpending_transfer_invalid_state
    """
    ctx = setup_pending_transfer(points=500, owned_points=5000)
    validate_success(
        api.accept_transfer(ctx["transfer"]["id"], accept_transfer_payload("ACCEPT"), make_member_headers(ctx["member_b"]["id"])),
        200,
    )
    resp = api.accept_transfer(ctx["transfer"]["id"], accept_transfer_payload("ACCEPT"), make_member_headers(ctx["member_b"]["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_accept_unknown_transfer_not_found(api):
    """PRD §2.9: "a missing transfer `ERR_TRANSFER_NOT_FOUND`, each with HTTP 404."

    Design: Corner/validations/corner_not_found_transfer_on_accept
    """
    set_clock("2026-07-01T00:00:00Z")
    member = new_member(owned_points=5000)
    resp = api.accept_transfer(NON_EXISTENT_UUID, accept_transfer_payload("ACCEPT"), make_member_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_TRANSFER_NOT_FOUND.value, 404)
