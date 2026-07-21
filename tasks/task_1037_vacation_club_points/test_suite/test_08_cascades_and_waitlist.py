"""Suspension and cancellation cascades that drive waitlist promotion.

Queue A: tc_suspension_cascade_depth3_statement_member_reservation_waitlist,
tc_cancel_cascade_refund_freecapacity_promote.
Queue B: waitlist cancel + waitlist-not-found corners.
"""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    generate_statement,
    make_member_headers,
    member_current_bucket,
    new_member,
    new_reservation,
    new_resort,
    new_unit_type,
    new_waitlist,
    run_billing_cycle,
    set_clock,
    setup_member_and_unit_type,
    setup_reservation_with_waiting_member,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


# ─── tc_suspension_cascade_depth3 ─────────────────────────────────────────

def _run_suspension_cascade(api):
    """Member A (delinquent statement) holds Oct 10-14 on a total_units=1 unit;
    member B waits Oct 12-16. Advancing past grace + run_billing_cycle drives the
    depth-3 cascade. Returns the created ids."""
    set_clock("2026-07-01T00:00:00Z")
    member_a = new_member(owned_points=5000)
    bucket_a = member_current_bucket(member_a["id"])
    member_b = new_member(owned_points=5000)
    bucket_b = member_current_bucket(member_b["id"])
    resort = new_resort()
    ut = new_unit_type(resort["id"], total_units=1)
    res_a = new_reservation(member_a["id"], ut["id"], bucket_a["id"], "2026-10-10", "2026-10-14")  # cost 650
    wl_b = new_waitlist(member_b["id"], ut["id"], bucket_b["id"], "2026-10-12", "2026-10-16")  # cost 600
    generate_statement(member_a["id"], member_a["version"])  # total 37100, CURRENT
    set_clock("2026-08-16T00:00:00Z")  # past due (07-31) + 15-day grace
    run_billing_cycle()
    return {
        "member_a": member_a, "bucket_a": bucket_a,
        "member_b": member_b, "bucket_b": bucket_b,
        "res_a": res_a, "wl_b": wl_b,
    }


def test_suspension_cascade_ages_statement_and_suspends_member(api):
    """PRD §3.10: "any `CURRENT` statement whose `due_date` has passed (the clock is
    now after its `due_date`) and whose `payment_status` is not `PAID` moves to
    `PAST_DUE`."
    PRD §3.10: "for any member who is still `ACTIVE` and who has a statement that is
    `PAST_DUE`, not yet `PAID`, and now past its `due_date` plus the 15-day grace
    period (the clock is now more than 15 days beyond the `due_date`), the member is
    suspended, moving `account_status` from `ACTIVE` to `SUSPENDED`."

    Design: Difficulty/transitive_cascade/tc_suspension_cascade_depth3_statement_member_reservation_waitlist
    """
    ctx = _run_suspension_cascade(api)
    statement = validate_success(api.list_member_statements(ctx["member_a"]["id"], ADMIN), 200)[0]
    assert statement["aging_status"] == "PAST_DUE"
    member = validate_success(api.get_member(ctx["member_a"]["id"], ADMIN), 200)
    assert member["account_status"] == "SUSPENDED"


def test_suspension_cascade_cancels_hold_and_promotes_waitlist(api):
    """PRD §3.10: "every reservation of the member still in HELD status is cancelled
    with a full refund — refunded_points set to the reservation's entire points_cost ...
    For each unit type whose capacity is freed by these cancellations, the
    earliest-created ACTIVE waitlist entry that now fits is promoted exactly as in §3.7."
    PRD §3.7: "Promotion sets the entry's status to PROMOTED, creates a new HELD
    reservation for the member, records that reservation on the entry as
    promoted_reservation_id, commits the reservation's points_cost on the paying bucket".

    Design: Difficulty/transitive_cascade/tc_suspension_cascade_depth3_statement_member_reservation_waitlist
    """
    ctx = _run_suspension_cascade(api)
    res_a = validate_success(api.get_reservation(ctx["res_a"]["id"], ADMIN), 200)
    assert res_a["status"] == "CANCELLED"
    assert res_a["refunded_points"] == 650  # full refund via suspension cascade

    wl_b = validate_success(api.get_waitlist_entry(ctx["wl_b"]["id"], ADMIN), 200)
    assert wl_b["status"] == "PROMOTED"
    assert wl_b["promoted_reservation_id"]
    promoted = validate_success(api.get_reservation(wl_b["promoted_reservation_id"], ADMIN), 200)
    assert promoted["status"] == "HELD"
    assert promoted["points_cost"] == 600
    bucket_b = validate_success(api.get_points_bucket(ctx["bucket_b"]["id"], ADMIN), 200)
    assert bucket_b["points_used"] == 600


# ─── tc_cancel_cascade_refund_freecapacity_promote ────────────────────────

def test_cancel_promotes_waiting_member(api):
    """PRD §3.5: "because a night has been freed, the earliest-created ACTIVE waitlist
    entry on that unit type that now fits is promoted, per §3.7." PRD §3.7: "creates a
    new HELD reservation for the member, records that reservation on the entry as
    promoted_reservation_id, commits the reservation's points_cost on the paying bucket".

    Design: Difficulty/transitive_cascade/tc_cancel_cascade_refund_freecapacity_promote
    """
    ctx = setup_reservation_with_waiting_member("2026-08-10", "2026-08-14", "2026-08-12", "2026-08-16")
    validate_success(
        api.cancel_reservation(ctx["reservation_a"]["id"], make_member_headers(ctx["member_a"]["id"])), 200
    )
    wl_b = validate_success(api.get_waitlist_entry(ctx["waitlist_b"]["id"], ADMIN), 200)
    assert wl_b["status"] == "PROMOTED"
    assert wl_b["promoted_reservation_id"]
    promoted = validate_success(api.get_reservation(wl_b["promoted_reservation_id"], ADMIN), 200)
    assert promoted["status"] == "HELD"
    assert promoted["points_cost"] == 1200


def test_cancel_partial_refund_and_promoted_bucket_committed(api):
    """PRD §3.5: "If `days_out` is at least 15 but less than 60, the refund is partial
    and `refunded_points` equals the floor of half the `points_cost`". PRD §3.7:
    "commits the reservation's `points_cost` on the paying bucket, and occupies its
    nights".

    Design: Difficulty/transitive_cascade/tc_cancel_cascade_refund_freecapacity_promote
    """
    ctx = setup_reservation_with_waiting_member("2026-08-10", "2026-08-14", "2026-08-12", "2026-08-16")
    res_a = validate_success(
        api.cancel_reservation(ctx["reservation_a"]["id"], make_member_headers(ctx["member_a"]["id"])), 200
    )
    assert res_a["status"] == "CANCELLED"
    assert res_a["refunded_points"] == 500  # days_out 40 -> PARTIAL floor(1000/2)
    bucket_b = validate_success(api.get_points_bucket(ctx["bucket_b"]["id"], ADMIN), 200)
    assert bucket_b["points_used"] == 1200  # promoted reservation commits its cost


# ─── Queue B corners ──────────────────────────────────────────────────────

def test_cancel_active_waitlist_entry(api):
    """PRD §3.7: "The owning member may leave the waitlist, moving the entry from
    ACTIVE to CANCELLED."

    Design: Corner/state_machines/corner_waitlist_cancel_success
    """
    world = setup_member_and_unit_type(owned_points=5000, total_units=1)
    wl = new_waitlist(world["member"]["id"], world["unit_type"]["id"], world["bucket"]["id"], "2026-08-10", "2026-08-14")
    res = validate_success(api.cancel_waitlist_entry(wl["id"], world["member_headers"]), 200)
    assert res["status"] == "CANCELLED"


def test_cancel_unknown_waitlist_entry_not_found(api):
    """PRD §2.9: "a missing waitlist entry `ERR_WAITLIST_NOT_FOUND`, a missing statement
    `ERR_STATEMENT_NOT_FOUND`".

    Design: Corner/validations/corner_not_found_waitlist_on_cancel
    """
    set_clock("2026-07-01T00:00:00Z")
    member = new_member(owned_points=5000)
    resp = api.cancel_waitlist_entry(NON_EXISTENT_UUID, make_member_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_WAITLIST_NOT_FOUND.value, 404)
