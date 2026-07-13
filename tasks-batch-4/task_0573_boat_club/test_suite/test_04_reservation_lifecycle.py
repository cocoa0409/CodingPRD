"""Reservation / boat / member state machines: invalid transitions, cyclic
lifecycles, and cross-entity state guards.

Translates queue B (Corner) `state_machines` instances and queue A (Difficulty)
instances for non-linear state machines and cross-entity state dependencies.
"""
import test_helpers as th
from test_helpers import validate_success, validate_error, ApiErrorId


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _completed_trip_boat_in_cleaning():
    """Run a full trip so the boat ends in CLEANING (usage_count incremented)."""
    ctx = th.setup_active_basic_member("SAIL")
    m, b1 = ctx["member_id"], ctx["boat_ids"][0]
    r = th.create_confirmed_reservation(m, ctx["dock_id"], "PONTOON", "2026-05-05T10:00:00Z", "2026-05-05T12:00:00Z")
    th.set_clock("2026-05-05T10:00:00Z")
    th.checkout_reservation(m, r["id"], 90)
    th.set_clock("2026-05-05T12:00:00Z")
    th.return_reservation(m, r["id"], 80)
    return ctx, b1, r["id"]


def _boat_in_cleaning_with_confirmed_pending():
    """Single boat serving two CONFIRMED reservations; the first trip leaves the boat
    in CLEANING while the second remains CONFIRMED and un-checked-out."""
    ctx = th.setup_active_basic_member("SAIL")
    m, b1 = ctx["member_id"], ctx["boat_ids"][0]
    re = th.create_confirmed_reservation(m, ctx["dock_id"], "PONTOON", "2026-05-05T08:00:00Z", "2026-05-05T09:00:00Z")
    rl = th.create_confirmed_reservation(m, ctx["dock_id"], "PONTOON", "2026-05-05T10:30:00Z", "2026-05-05T12:00:00Z")
    th.set_clock("2026-05-05T08:00:00Z")
    th.checkout_reservation(m, re["id"], 90)
    th.set_clock("2026-05-05T09:00:00Z")
    th.return_reservation(m, re["id"], 80)  # boat -> CLEANING
    th.set_clock("2026-05-05T10:30:00Z")
    return ctx, b1, rl["id"]


# --------------------------------------------------------------------------- #
# state_machines (queue B)
# --------------------------------------------------------------------------- #
def test_confirm_already_confirmed_returns_invalid_state(api, member_hdr):
    """PRD §2.8: "Sixth, the target resource being in a valid state for the requested
    transition."
    PRD §3.3: "a cancel attempted once the reservation is already `CHECKED_OUT`,
    `RETURNED`, `NO_SHOW`, or `CANCELLED` is rejected as an invalid state transition
    with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/confirm_already_confirmed_returns_invalid_state
    """
    ctx = th.setup_active_basic_member("SAIL")
    m = ctx["member_id"]
    r = th.create_confirmed_reservation(m, ctx["dock_id"], "PONTOON", "2026-05-05T10:00:00Z", "2026-05-05T12:00:00Z")
    boat_first = r["boat_id"]
    resp = api.confirm_reservation(r["id"], member_hdr(m))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert th.get_reservation(r["id"])["boat_id"] == boat_first, "no second boat may be assigned"


def test_checkout_from_requested_returns_invalid_state(api, member_hdr):
    """PRD §3.3: "Checking out is how a member takes possession of a `CONFIRMED`
    reservation's boat."
    PRD §3.3: "a cancel attempted once the reservation is already `CHECKED_OUT`,
    `RETURNED`, `NO_SHOW`, or `CANCELLED` is rejected as an invalid state transition
    with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/checkout_from_requested_returns_invalid_state
    """
    ctx = th.setup_active_basic_member("SAIL")
    m = ctx["member_id"]
    r = th.request_reservation(m, ctx["dock_id"], "PONTOON", "2026-05-05T10:00:00Z", "2026-05-05T12:00:00Z")
    resp = api.checkout_reservation(r["id"], {"fuel_at_checkout": 90}, member_hdr(m))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_cancel_returned_reservation_returns_invalid_state(api, member_hdr):
    """PRD §3.3: "a cancel attempted once the reservation is already `CHECKED_OUT`,
    `RETURNED`, `NO_SHOW`, or `CANCELLED` is rejected as an invalid state transition
    with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/cancel_terminal_returned_reservation_returns_invalid_state
    """
    ctx, b1, rid = _completed_trip_boat_in_cleaning()  # reservation is RETURNED
    m = ctx["member_id"]
    assert th.get_reservation(rid)["status"] == "RETURNED"
    resp = api.cancel_reservation(rid, member_hdr(m))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_waive_already_waived_fee_returns_fee_not_assessed(api, staff):
    """PRD §3.6: "`DockStaff` may waive an `ASSESSED` fee, addressed by its `fee_id`,
    moving it to `WAIVED`; a waive attempted on a fee not in `ASSESSED` is rejected
    with `ERR_FEE_NOT_ASSESSED` (HTTP 409)."

    Design: Corner/state_machines/waive_non_assessed_fee_returns_fee_not_assessed
    """
    ctx = th.setup_active_basic_member("SAIL")
    m, b1 = ctx["member_id"], ctx["boat_ids"][0]
    r = th.request_reservation(m, ctx["dock_id"], "PONTOON", "2026-05-05T10:00:00Z", "2026-05-05T12:00:00Z")
    th.assessed_damage_fee(r["id"], b1, "MINOR", 5000)
    fee = th.find_fees(member_id=m, fee_type="DAMAGE")[0]
    th.waive_fee(fee["id"])  # ASSESSED -> WAIVED
    resp = api.waive_fee(fee["id"], staff)  # second waive on a WAIVED fee
    validate_error(resp, ApiErrorId.ERR_FEE_NOT_ASSESSED)


# --------------------------------------------------------------------------- #
# non_linear_state_machine (queue A) — boat cycle
# --------------------------------------------------------------------------- #
def test_boat_cycle_returns_to_available_with_usage(api, staff):
    """PRD §3.2: "Returning it advances it from `OUT` to `CLEANING`; on that return the
    boat's `needs_cleaning` is set true, its `usage_count` is increased by one".
    PRD §3.2: "`DockStaff` finish the turnaround with a servicing action that carries a
    boat from `CLEANING` back to `AVAILABLE`, clearing `needs_cleaning`".

    Design: Difficulty/non_linear_state_machine/nl_boat_availability_cycle
    """
    ctx, b1, rid = _completed_trip_boat_in_cleaning()
    resp = api.boat_clean_complete(b1, staff)
    data = validate_success(resp, 200)
    assert data["status"] == "AVAILABLE"
    assert data["usage_count"] == 1
    assert data["needs_cleaning"] is False


def test_boat_cycle_intermediate_states_and_refuel(api, staff):
    """PRD §3.2: "its `fuel_level_pct` is set to the fuel gauge reading captured at
    return. `DockStaff` finish the turnaround with a servicing action that carries a
    boat from `CLEANING` back to `AVAILABLE`, clearing `needs_cleaning` and refuelling
    the tank so `fuel_level_pct` returns to 100."

    Design: Difficulty/non_linear_state_machine/nl_boat_availability_cycle
    """
    ctx, b1, rid = _completed_trip_boat_in_cleaning()
    mid = th.get_boat(b1)
    assert mid["status"] == "CLEANING"
    assert mid["needs_cleaning"] is True
    assert mid["fuel_level_pct"] == 80  # gauge captured at return
    after = validate_success(api.boat_clean_complete(b1, staff), 200)
    assert after["status"] == "AVAILABLE"  # cycle closed back to the start state
    assert after["fuel_level_pct"] == 100


# --------------------------------------------------------------------------- #
# non_linear_state_machine (queue A) — member cycle
# --------------------------------------------------------------------------- #
def test_member_suspend_reinstate_cycle_resets_strikes(api, admin):
    """PRD §3.1: "A `ClubAdmin` reinstates a `SUSPENDED` member, moving them back to
    `ACTIVE`; ... On reinstatement the member's `no_show_strikes` is reset to zero and
    `last_reinstated_at` is set to the current clock."

    Design: Difficulty/non_linear_state_machine/nl_member_active_suspend_reinstate_cycle
    """
    th.make_tier("SAIL")
    dock = th.make_dock()["id"]
    m = th.make_member("SAIL", dock)["id"]
    th.certify_orientation(m, dock)  # PENDING_ORIENTATION -> ACTIVE
    th.suspend_member(m)
    resp = api.reinstate_member(m, admin)
    data = validate_success(resp, 200)
    assert data["status"] == "ACTIVE"
    assert data["no_show_strikes"] == 0


def test_member_cycle_traverses_active_suspended_active(api, admin):
    """PRD §3.1: "A `ClubAdmin` may suspend an `ACTIVE` member for cause, optionally
    recording a `reason`; the member moves to `SUSPENDED`."
    PRD §3.1: "A `ClubAdmin` reinstates a `SUSPENDED` member, moving them back to
    `ACTIVE`".

    Design: Difficulty/non_linear_state_machine/nl_member_active_suspend_reinstate_cycle
    """
    th.make_tier("SAIL")
    dock = th.make_dock()["id"]
    m = th.make_member("SAIL", dock)["id"]
    th.certify_orientation(m, dock)
    assert th.get_member(m)["status"] == "ACTIVE"
    th.suspend_member(m)
    assert th.get_member(m)["status"] == "SUSPENDED"
    validate_success(api.reinstate_member(m, admin), 200)
    assert th.get_member(m)["status"] == "ACTIVE"  # returned to the start state


# --------------------------------------------------------------------------- #
# cross_entity_state_dependency (queue A)
# --------------------------------------------------------------------------- #
def test_confirm_requires_member_active(api, member_hdr):
    """PRD §3.3: "Confirming a reservation is permitted only when the owning member is
    `ACTIVE`; a confirm by a member who is not `ACTIVE` is rejected with
    `ERR_MEMBER_NOT_ACTIVE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/ce_confirm_requires_member_active
    """
    ctx = th.setup_active_basic_member("SAIL")
    m = ctx["member_id"]
    r1 = th.request_reservation(m, ctx["dock_id"], "PONTOON", "2026-05-05T10:00:00Z", "2026-05-05T12:00:00Z")
    th.suspend_member(m)
    resp = api.confirm_reservation(r1["id"], member_hdr(m))
    validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_ACTIVE)


def test_requested_reservation_survives_suspension(api, member_hdr):
    """PRD §3.1: "Reservations still in `REQUESTED` are deliberately left intact so
    they can be resumed after reinstatement."
    PRD §3.3: "a confirm by a member who is not `ACTIVE` is rejected with
    `ERR_MEMBER_NOT_ACTIVE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/ce_confirm_requires_member_active
    """
    ctx = th.setup_active_basic_member("SAIL")
    m = ctx["member_id"]
    r1 = th.request_reservation(m, ctx["dock_id"], "PONTOON", "2026-05-05T10:00:00Z", "2026-05-05T12:00:00Z")
    th.suspend_member(m)
    api.confirm_reservation(r1["id"], member_hdr(m))  # blocked
    assert th.get_reservation(r1["id"])["status"] == "REQUESTED"


def test_checkout_requires_boat_available(api, member_hdr):
    """PRD §3.3: "Checkout is permitted only when the assigned boat's status is
    `AVAILABLE`; if the boat is not `AVAILABLE`, the checkout is rejected with
    `ERR_BOAT_NOT_AVAILABLE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/ce_checkout_requires_boat_available
    """
    ctx, b1, rl_id = _boat_in_cleaning_with_confirmed_pending()
    m = ctx["member_id"]
    resp = api.checkout_reservation(rl_id, {"fuel_at_checkout": 60}, member_hdr(m))
    validate_error(resp, ApiErrorId.ERR_BOAT_NOT_AVAILABLE)


def test_checkout_blocked_leaves_boat_and_reservation_unchanged(api, member_hdr):
    """PRD §3.3: "Checkout is permitted only when the assigned boat's status is
    `AVAILABLE`; if the boat is not `AVAILABLE`, the checkout is rejected with
    `ERR_BOAT_NOT_AVAILABLE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/ce_checkout_requires_boat_available
    """
    ctx, b1, rl_id = _boat_in_cleaning_with_confirmed_pending()
    m = ctx["member_id"]
    api.checkout_reservation(rl_id, {"fuel_at_checkout": 60}, member_hdr(m))  # blocked
    assert th.get_boat(b1)["status"] == "CLEANING"
    assert th.get_reservation(rl_id)["status"] == "CONFIRMED"
