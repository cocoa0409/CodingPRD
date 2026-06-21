"""Unclaimed-item and disposal time windows: the 30-day grace boundary
(too-early vs inclusive lower bound) and the 90-day disposal lower bound.

ready_at is the mark-ready clock. The fixtures mark a ticket ready at
2026-03-01T09:00:00Z, so ready_at + 29 = 2026-03-30, +30 = 2026-03-31,
+31 = 2026-04-01, +90 = 2026-05-30.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success, validate_error,
    TEST_USERS,
    set_clock, setup_ready_for_pickup, setup_flagged_unclaimed,
)

FRONT_DESK = TEST_USERS["front_desk_headers"]
SHOP_MANAGER = TEST_USERS["shop_manager_headers"]


# ── Difficulty: flag-unclaimed too-early boundary (≥2 tests) ─────────────
def test_flag_unclaimed_one_day_before_grace_rejected(api):
    """PRD §3.7: "A `FrontDeskClerk` flags an uncollected ticket as unclaimed, moving its `repair_status` from `READY_FOR_PICKUP` to `UNCLAIMED`, only once the clock has reached or passed `ready_at` plus the 30-day unclaimed grace window; an earlier attempt is rejected with `ERR_UNCLAIMED_TOO_EARLY`."

    Design: Difficulty/boundary_precision_check/unclaimed_flag_too_early_zero_day_boundary
    """
    s = setup_ready_for_pickup(item_category="SHOE")  # ready_at = 2026-03-01T09:00:00Z
    set_clock("2026-03-30T09:00:00Z")  # ready_at + 29 days, one day short of the grace boundary
    res = api.flag_unclaimed(s["ticket"]["id"], FRONT_DESK)
    validate_error(res, "ERR_UNCLAIMED_TOO_EARLY", 409)


def test_flag_unclaimed_at_grace_boundary_succeeds(api):
    """PRD §3.7: "only once the clock has reached or passed `ready_at` plus the 30-day unclaimed grace window".
    PRD §3.7: "Flagging sets the ticket's `notify_status` to `UNCLAIMED_WARNED`, appends an `UNCLAIMED_WARNING` notification, and increments the ticket's `version`."

    Design: Difficulty/boundary_precision_check/unclaimed_flag_too_early_zero_day_boundary
    """
    s = setup_ready_for_pickup(item_category="SHOE")
    set_clock("2026-03-31T09:00:00Z")  # exactly ready_at + 30 days (inclusive boundary)
    flagged = validate_success(api.flag_unclaimed(s["ticket"]["id"], FRONT_DESK), 200)
    assert flagged["repair_status"] == "UNCLAIMED"


# ── Difficulty: grace window inclusive lower bound (≥2 tests) ────────────
def test_grace_boundary_transitions_to_unclaimed(api):
    """PRD §3.7: "A `FrontDeskClerk` flags an uncollected ticket as unclaimed, moving its `repair_status` from `READY_FOR_PICKUP` to `UNCLAIMED`, only once the clock has reached or passed `ready_at` plus the 30-day unclaimed grace window".

    Design: Difficulty/resource_temporal_overlap/unclaimed_grace_window_lower_bound_inclusive
    """
    s = setup_ready_for_pickup(item_category="SHOE")
    set_clock("2026-03-31T09:00:00Z")  # exactly ready_at + 30 days
    flagged = validate_success(api.flag_unclaimed(s["ticket"]["id"], FRONT_DESK), 200)
    assert flagged["repair_status"] == "UNCLAIMED"


def test_grace_boundary_sets_unclaimed_warned(api):
    """PRD §3.7: "Flagging sets the ticket's `notify_status` to `UNCLAIMED_WARNED`, appends an `UNCLAIMED_WARNING` notification, and increments the ticket's `version`."

    Design: Difficulty/resource_temporal_overlap/unclaimed_grace_window_lower_bound_inclusive
    """
    s = setup_ready_for_pickup(item_category="SHOE")
    set_clock("2026-03-31T09:00:00Z")  # exactly ready_at + 30 days
    flagged = validate_success(api.flag_unclaimed(s["ticket"]["id"], FRONT_DESK), 200)
    assert flagged["notify_status"] == "UNCLAIMED_WARNED"


# ── Difficulty: disposal blocked before its lower bound (≥2 tests) ───────
def test_dispose_before_disposal_window_rejected(api):
    """PRD §3.7: "A ticket may be disposed from `UNCLAIMED` only when its `notify_status` is `UNCLAIMED_WARNED` ... and only once the clock has reached or passed `ready_at` plus the 90-day disposal window; an earlier attempt is rejected with `ERR_DISPOSAL_TOO_EARLY`."

    Design: Difficulty/resource_temporal_overlap/disposal_window_blocks_before_lower_bound
    """
    # Flagged unclaimed at the grace boundary (2026-03-31), already UNCLAIMED_WARNED.
    s = setup_flagged_unclaimed(clock="2026-03-01T09:00:00Z", flag_clock="2026-03-31T09:00:00Z")
    set_clock("2026-04-01T09:00:00Z")  # ready_at + 31 days, far short of the 90-day disposal bound
    res = api.dispose(s["ticket"]["id"], SHOP_MANAGER)
    validate_error(res, "ERR_DISPOSAL_TOO_EARLY", 409)


def test_dispose_too_early_leaves_ticket_unclaimed(api):
    """PRD §3.7: "Disposal is the last resort and belongs to a `ShopManager`. A ticket may be disposed from `UNCLAIMED` only when its `notify_status` is `UNCLAIMED_WARNED`".
    PRD §3.7: "Disposal moves the ticket's `repair_status` to `DISPOSED`, voids all of the ticket's remaining non-`VOIDED` service lines, and increments the ticket's `version`."

    Design: Difficulty/resource_temporal_overlap/disposal_window_blocks_before_lower_bound
    """
    s = setup_flagged_unclaimed(clock="2026-03-01T09:00:00Z", flag_clock="2026-03-31T09:00:00Z")
    set_clock("2026-04-01T09:00:00Z")
    api.dispose(s["ticket"]["id"], SHOP_MANAGER)
    ticket = validate_success(api.get_repair_ticket(s["ticket"]["id"], FRONT_DESK), 200)
    assert ticket["repair_status"] == "UNCLAIMED"
