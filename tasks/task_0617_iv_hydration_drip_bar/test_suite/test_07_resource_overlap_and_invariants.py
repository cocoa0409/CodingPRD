"""Lounge capacity / operating-window geometry, mobile route turnaround buffers,
FEFO lot selection, quarantine guard, route-locked dispatch, and the conservation
(compensating) invariants for supply units and membership credits.
"""
import pytest
from test_helpers import (
    get_success_data, validate_error,
    set_clock, create_menu_item, create_lounge, create_patient, create_membership,
    create_add_on, create_supply_lot, create_nurse, create_dispatch_route,
    create_requested_appointment, submit_intake, sign_consent, current_version,
    schedule_appointment, add_scheduled_mobile_stop,
    setup_mobile_route_with_dispatched_stop, setup_cleared_lounge_ready_to_schedule,
    TEST_USERS,
)
from test_helpers.api_client import api_client

ADMIN = TEST_USERS["clinic_admin_headers"]
FAR_EXPIRY = "2026-12-31T00:00:00Z"


def _lounge_appt_scheduled(menu_id, lounge_id, start_at, duration=60):
    """Create + intake + consent + schedule a LOUNGE appointment, returning it."""
    patient = create_patient()
    appt = create_requested_appointment(patient["id"], menu_id, lounge_id=lounge_id,
                                        start_at=start_at, duration_minutes=duration)
    submit_intake(appt["id"])
    sign_consent(appt["id"])
    return schedule_appointment(appt["id"])


def _lounge_appt_screen_pending(menu_id, lounge_id, start_at, duration=60):
    """Create + intake + consent a LOUNGE appointment (left SCREEN_PENDING). Returns it."""
    patient = create_patient()
    appt = create_requested_appointment(patient["id"], menu_id, lounge_id=lounge_id,
                                        start_at=start_at, duration_minutes=duration)
    submit_intake(appt["id"])
    sign_consent(appt["id"])
    return get_success_data(api_client.get_appointment(appt["id"], ADMIN))


# ─── Difficulty: resource_temporal_overlap / overlap_lounge_capacity_exceeded ───
def test_lounge_capacity_exceeded_rejects_overlapping_slot(api):
    """PRD §3.8: "The concurrent count is the number of lounge appointments at that lounge
    in `SCHEDULED`, `DISPATCHED`, or `IN_PROGRESS` status whose interval overlaps the
    candidate's; scheduling is rejected when that count is already equal to or greater than
    the lounge's `bay_count`".

    With bay_count=1, a 09:30-10:30 slot overlapping an already-SCHEDULED 09:00-10:00 slot
    is rejected with ERR_SLOT_CONFLICT and stays SCREEN_PENDING.

    Design: Difficulty/resource_temporal_overlap/overlap_lounge_capacity_exceeded
    """
    set_clock("2026-06-22T00:00:00Z")
    myers = create_menu_item(tier="MYERS", requires_standing_order=False)
    lounge = create_lounge(name="Solo", bay_count=1, open_minute_of_day=480,
                           close_minute_of_day=1200)
    create_supply_lot(item_kind="DRIP_BASE", tier_or_code="MYERS", lot_number="MY-1",
                      units_total=5, expires_at=FAR_EXPIRY)
    _lounge_appt_scheduled(myers["id"], lounge["id"], "2026-06-23T09:00:00Z")
    a2 = _lounge_appt_screen_pending(myers["id"], lounge["id"], "2026-06-23T09:30:00Z")
    v = current_version(a2["id"])
    res = api_client.schedule_appointment(a2["id"], {"expected_appointment_version": v}, ADMIN)
    validate_error(res, "ERR_SLOT_CONFLICT", expected_status=409)
    a2_after = get_success_data(api_client.get_appointment(a2["id"], ADMIN))
    assert a2_after["status"] == "SCREEN_PENDING"


def test_lounge_capacity_non_overlapping_slot_at_single_bay_schedules(api):
    """PRD §3.8: "Two lounge appointments at the same lounge conflict exactly when their
    half-open intervals overlap ... The concurrent count is the number of lounge
    appointments ... whose interval overlaps the candidate's; scheduling is rejected when
    that count is already equal to or greater than the lounge's `bay_count`".

    The X-1 partner of the capacity-exceeded test: with bay_count=1, a 11:00-12:00 slot
    that does NOT overlap an already-SCHEDULED 09:00-10:00 slot has concurrent_count 0 < 1,
    so it schedules — confirming capacity is per-overlapping-interval, not per-lounge.

    Design: Difficulty/resource_temporal_overlap/overlap_lounge_capacity_exceeded
    """
    set_clock("2026-06-22T00:00:00Z")
    myers = create_menu_item(tier="MYERS", requires_standing_order=False)
    lounge = create_lounge(name="Solo", bay_count=1, open_minute_of_day=480,
                           close_minute_of_day=1200)
    create_supply_lot(item_kind="DRIP_BASE", tier_or_code="MYERS", lot_number="MY-1",
                      units_total=5, expires_at=FAR_EXPIRY)
    _lounge_appt_scheduled(myers["id"], lounge["id"], "2026-06-23T09:00:00Z")
    a2 = _lounge_appt_screen_pending(myers["id"], lounge["id"], "2026-06-23T11:00:00Z")
    scheduled = schedule_appointment(a2["id"])
    assert scheduled["status"] == "SCHEDULED", \
        f"non-overlapping slot at a single-bay lounge must schedule, got {scheduled['status']}"


# ─── Difficulty: boundary_precision_check / bnd_lounge_back_to_back_gap_zero_allowed ───
def test_lounge_back_to_back_zero_gap_schedules(api):
    """PRD §3.8: "Appointments that merely touch at a boundary (one ending at precisely the
    instant the next begins) do not overlap, so back-to-back lounge bookings are allowed and
    no turnaround buffer is imposed at a lounge."

    With bay_count=1, a 10:00-11:00 slot starting exactly when the first 09:00-10:00 slot
    ends schedules successfully (gap == 0).

    Design: Difficulty/boundary_precision_check/bnd_lounge_back_to_back_gap_zero_allowed
    """
    set_clock("2026-06-22T00:00:00Z")
    myers = create_menu_item(tier="MYERS", requires_standing_order=False)
    lounge = create_lounge(name="Solo", bay_count=1, open_minute_of_day=480,
                           close_minute_of_day=1200)
    create_supply_lot(item_kind="DRIP_BASE", tier_or_code="MYERS", lot_number="MY-1",
                      units_total=5, expires_at=FAR_EXPIRY)
    _lounge_appt_scheduled(myers["id"], lounge["id"], "2026-06-23T09:00:00Z")
    a2 = _lounge_appt_screen_pending(myers["id"], lounge["id"], "2026-06-23T10:00:00Z")
    scheduled = schedule_appointment(a2["id"])
    assert scheduled["status"] == "SCHEDULED", \
        f"back-to-back slot must schedule, got {scheduled['status']}"


def test_lounge_overlapping_by_one_minute_rejected_at_single_bay(api):
    """PRD §3.8: "Two lounge appointments at the same lounge conflict exactly when their
    half-open intervals overlap — that is, when the candidate's `start_at` is strictly
    before the other's end and the other's `start_at` is strictly before the candidate's
    end." The failing side of the zero-gap boundary: a 09:59-10:59 slot starts one minute
    before the 09:00-10:00 slot ends, so it overlaps and (bay_count=1) is rejected with
    ERR_SLOT_CONFLICT.

    Design: Difficulty/boundary_precision_check/bnd_lounge_back_to_back_gap_zero_allowed
    """
    set_clock("2026-06-22T00:00:00Z")
    myers = create_menu_item(tier="MYERS", requires_standing_order=False)
    lounge = create_lounge(name="Solo", bay_count=1, open_minute_of_day=480,
                           close_minute_of_day=1200)
    create_supply_lot(item_kind="DRIP_BASE", tier_or_code="MYERS", lot_number="MY-1",
                      units_total=5, expires_at=FAR_EXPIRY)
    _lounge_appt_scheduled(myers["id"], lounge["id"], "2026-06-23T09:00:00Z")
    a2 = _lounge_appt_screen_pending(myers["id"], lounge["id"], "2026-06-23T09:59:00Z")
    v = current_version(a2["id"])
    res = api_client.schedule_appointment(a2["id"], {"expected_appointment_version": v}, ADMIN)
    validate_error(res, "ERR_SLOT_CONFLICT", expected_status=409)


def test_lounge_slot_before_open_window_rejected(api):
    """PRD §3.8: "the start minute must be at or after `open_minute_of_day` and the end
    minute must be at or before `close_minute_of_day` ... A slot that violates either the
    capacity rule or the window rule is rejected with `ERR_SLOT_CONFLICT`."

    A 07:00 slot starts before the default open minute (480 = 08:00).

    Design: Corner/validations/lounge_slot_outside_hours_rejected
    """
    set_clock("2026-06-22T00:00:00Z")
    myers = create_menu_item(tier="MYERS", requires_standing_order=False)
    lounge = create_lounge(bay_count=2, open_minute_of_day=480, close_minute_of_day=1200)
    create_supply_lot(item_kind="DRIP_BASE", tier_or_code="MYERS", lot_number="MY-1",
                      units_total=5, expires_at=FAR_EXPIRY)
    a = _lounge_appt_screen_pending(myers["id"], lounge["id"], "2026-06-23T07:00:00Z")
    v = current_version(a["id"])
    res = api_client.schedule_appointment(a["id"], {"expected_appointment_version": v}, ADMIN)
    validate_error(res, "ERR_SLOT_CONFLICT", expected_status=409)


# ─── Difficulty: resource_temporal_overlap / overlap_mobile_route_turnaround_buffer_violated ───
def test_mobile_route_turnaround_buffer_violation_rejected(api):
    """PRD §3.12: "the candidate is acceptable only if the candidate ends at least the
    buffer ahead of that stop's start, or that stop ends at least the buffer ahead of the
    candidate's start ... a gap exactly equal to the buffer is allowed, and a gap smaller
    than the buffer is rejected. A candidate that violates the buffer against any existing
    stop is rejected with `ERR_SLOT_CONFLICT`."

    First stop 09:00-10:00 DISPATCHED on a turnaround=30 route; a second stop at 10:15
    (15-minute gap < 30) is rejected on dispatch and stays SCHEDULED.

    Design: Difficulty/resource_temporal_overlap/overlap_mobile_route_turnaround_buffer_violated
    """
    ctx = setup_mobile_route_with_dispatched_stop(turnaround_minutes=30,
                                                  first_start="2026-06-23T09:00:00Z",
                                                  duration_minutes=60)
    a2 = add_scheduled_mobile_stop(ctx["menu_item"]["id"], ctx["nurse"]["id"],
                                   "2026-06-23T10:15:00Z", duration_minutes=60)
    res = api_client.dispatch_appointment(
        a2["id"], {"nurse_id": ctx["nurse"]["id"], "route_id": ctx["route"]["id"]}, ADMIN)
    validate_error(res, "ERR_SLOT_CONFLICT", expected_status=409)
    a2_after = get_success_data(api_client.get_appointment(a2["id"], ADMIN))
    assert a2_after["status"] == "SCHEDULED"


def test_mobile_route_buffer_exactly_equal_allowed(api):
    """PRD §3.12: "a gap exactly equal to the buffer is allowed, and a gap smaller than the
    buffer is rejected." First stop 09:00-10:00 DISPATCHED on a turnaround=30 route; a second
    stop at 10:30 (gap == 30) dispatches successfully.

    Design: Difficulty/resource_temporal_overlap/overlap_mobile_route_turnaround_buffer_violated
    """
    ctx = setup_mobile_route_with_dispatched_stop(turnaround_minutes=30,
                                                  first_start="2026-06-23T09:00:00Z",
                                                  duration_minutes=60)
    a2 = add_scheduled_mobile_stop(ctx["menu_item"]["id"], ctx["nurse"]["id"],
                                   "2026-06-23T10:30:00Z", duration_minutes=60)
    dispatched = get_success_data(api_client.dispatch_appointment(
        a2["id"], {"nurse_id": ctx["nurse"]["id"], "route_id": ctx["route"]["id"]}, ADMIN))
    assert dispatched["status"] == "DISPATCHED", \
        f"gap == buffer must dispatch, got {dispatched['status']}"


# ─── Corner: validations / dispatch_to_locked_route_rejected ───
def test_dispatch_to_locked_route_rejected(api):
    """PRD §3.12: "a locked route accepts no further stops, and any dispatch attempt that
    would add a stop to a `LOCKED` or `CLOSED` route is rejected with `ERR_ROUTE_LOCKED`
    (HTTP 409)."

    Design: Corner/validations/dispatch_to_locked_route_rejected
    """
    ctx = setup_mobile_route_with_dispatched_stop(turnaround_minutes=30,
                                                  first_start="2026-06-23T09:00:00Z")
    get_success_data(api_client.lock_dispatch_route(ctx["route"]["id"], ADMIN))
    a2 = add_scheduled_mobile_stop(ctx["menu_item"]["id"], ctx["nurse"]["id"],
                                   "2026-06-23T11:00:00Z", duration_minutes=60)
    res = api_client.dispatch_appointment(
        a2["id"], {"nurse_id": ctx["nurse"]["id"], "route_id": ctx["route"]["id"]}, ADMIN)
    validate_error(res, "ERR_ROUTE_LOCKED", expected_status=409)


# ─── Corner: calculations / fefo_picks_earliest_expiry_lot ───
def test_fefo_reserves_from_earliest_expiry_lot(api):
    """PRD §2.9 / §3.10: "Selection of which lot to draw follows First-Expiry-First-Out
    (FEFO): among the candidate lots for a line, the system always chooses the one expiring
    soonest." ... "it sorts by `expires_at` ascending and breaks ties by `created_at`
    ascending, then picks the first."

    Two AVAILABLE MYERS lots (expiry 2026-08-01 vs 2026-12-31): scheduling reserves from the
    earlier-expiry lot; the later lot keeps units_reserved 0.

    Design: Corner/calculations/fefo_picks_earliest_expiry_lot
    """
    set_clock("2026-06-22T00:00:00Z")
    myers = create_menu_item(tier="MYERS", requires_standing_order=False)
    lounge = create_lounge(bay_count=2)
    early = create_supply_lot(item_kind="DRIP_BASE", tier_or_code="MYERS", lot_number="EARLY",
                              units_total=5, expires_at="2026-08-01T00:00:00Z")
    late = create_supply_lot(item_kind="DRIP_BASE", tier_or_code="MYERS", lot_number="LATE",
                             units_total=5, expires_at="2026-12-31T00:00:00Z")
    _lounge_appt_scheduled(myers["id"], lounge["id"], "2026-06-23T09:00:00Z")
    early_after = get_success_data(api_client.get_supply_lot(early["id"], ADMIN))
    late_after = get_success_data(api_client.get_supply_lot(late["id"], ADMIN))
    assert early_after["units_reserved"] == 1, "FEFO must reserve from the earlier-expiry lot"
    assert late_after["units_reserved"] == 0, "the later-expiry lot must stay unreserved"


# ─── Corner: validations / quarantine_lot_with_reservations_rejected ───
def test_quarantine_lot_with_reservations_rejected(api):
    """PRD §3.10: "A `ClinicAdmin` may quarantine an `AVAILABLE` lot ... but only when
    `units_reserved` is 0 ... and attempting to quarantine a lot that still has reserved
    units is rejected with `ERR_LOT_HAS_RESERVATIONS` (HTTP 409)."

    Design: Corner/validations/quarantine_lot_with_reservations_rejected
    """
    set_clock("2026-06-22T00:00:00Z")
    myers = create_menu_item(tier="MYERS", requires_standing_order=False)
    lounge = create_lounge(bay_count=2)
    lot = create_supply_lot(item_kind="DRIP_BASE", tier_or_code="MYERS", lot_number="MY-1",
                            units_total=3, expires_at=FAR_EXPIRY)
    _lounge_appt_scheduled(myers["id"], lounge["id"], "2026-06-23T09:00:00Z")
    res = api_client.quarantine_supply_lot(lot["id"], ADMIN)
    validate_error(res, "ERR_LOT_HAS_RESERVATIONS", expected_status=409)


# ─── Difficulty: compensating_invariant / comp_supply_units_conserved_on_schedule_cancel ───
def test_supply_units_conserved_across_schedule_then_cancel(api):
    """PRD §3.13: cancellation "releases any reserved supply units by decrementing
    `units_reserved` by one on each reserved line ... and it sets the appointment's
    `status` to `CANCELLED`".

    Schedule reserves 1 MYERS unit (reserved 0->1); cancel releases it (reserved 1->0),
    consumed stays 0 and units_total is unchanged at 3 — no drift.

    Design: Difficulty/compensating_invariant/comp_supply_units_conserved_on_schedule_cancel
    """
    set_clock("2026-06-22T00:00:00Z")
    myers = create_menu_item(tier="MYERS", requires_standing_order=False)
    lounge = create_lounge(bay_count=2)
    lot = create_supply_lot(item_kind="DRIP_BASE", tier_or_code="MYERS", lot_number="MY-3",
                            units_total=3, expires_at=FAR_EXPIRY)
    scheduled = _lounge_appt_scheduled(myers["id"], lounge["id"], "2026-06-23T09:00:00Z")
    lot_mid = get_success_data(api_client.get_supply_lot(lot["id"], ADMIN))
    assert lot_mid["units_reserved"] == 1, "schedule should reserve exactly one unit"
    cancelled = get_success_data(api_client.cancel_appointment(scheduled["id"], ADMIN))
    assert cancelled["status"] == "CANCELLED"
    lot_after = get_success_data(api_client.get_supply_lot(lot["id"], ADMIN))
    assert lot_after["units_reserved"] == 0
    assert lot_after["units_consumed"] == 0
    assert lot_after["units_total"] == 3


def test_supply_lot_free_units_fully_restored_after_cancel(api):
    """PRD §3.13: cancellation "releases any reserved supply units by decrementing
    `units_reserved` by one on each reserved line".
    PRD §2.9: "The number of free units in a lot is its `units_total` minus
    `units_reserved` minus `units_consumed`."

    A second conservation angle: after schedule-then-cancel, the lot's free-unit count
    (total - reserved - consumed) returns to its full original value of 3.

    Design: Difficulty/compensating_invariant/comp_supply_units_conserved_on_schedule_cancel
    """
    set_clock("2026-06-22T00:00:00Z")
    myers = create_menu_item(tier="MYERS", requires_standing_order=False)
    lounge = create_lounge(bay_count=2)
    lot = create_supply_lot(item_kind="DRIP_BASE", tier_or_code="MYERS", lot_number="MY-3",
                            units_total=3, expires_at=FAR_EXPIRY)
    scheduled = _lounge_appt_scheduled(myers["id"], lounge["id"], "2026-06-23T09:00:00Z")
    lot_mid = get_success_data(api_client.get_supply_lot(lot["id"], ADMIN))
    free_mid = lot_mid["units_total"] - lot_mid["units_reserved"] - lot_mid["units_consumed"]
    assert free_mid == 2, f"one unit should be reserved at schedule, free={free_mid}"
    get_success_data(api_client.cancel_appointment(scheduled["id"], ADMIN))
    lot_after = get_success_data(api_client.get_supply_lot(lot["id"], ADMIN))
    free_after = lot_after["units_total"] - lot_after["units_reserved"] - lot_after["units_consumed"]
    assert free_after == 3, f"all free units restored after cancel, free={free_after}"
    assert lot_after["status"] == "AVAILABLE"


# ─── Difficulty: compensating_invariant / comp_membership_credits_conserved_on_schedule_cancel ───
def test_membership_credits_conserved_across_schedule_then_cancel(api):
    """PRD §3.13: cancellation "restores the membership credits by increasing
    `drip_credits_remaining` by the appointment's `drip_credit_used` and
    `addon_credits_remaining` by its `addon_credits_used`".

    A PLATINUM membership (1 drip + 1 addon credit) is decremented to 0/0 at schedule, then
    restored to 1/1 on cancel — no drift.

    Design: Difficulty/compensating_invariant/comp_membership_credits_conserved_on_schedule_cancel
    """
    set_clock("2026-06-22T00:00:00Z")
    myers = create_menu_item(tier="MYERS", requires_standing_order=False)
    glut = create_add_on(name="Glutathione", code="GLUTATHIONE", price_cents=4500)
    lounge = create_lounge(bay_count=2)
    create_supply_lot(item_kind="DRIP_BASE", tier_or_code="MYERS", lot_number="MY-1",
                      units_total=5, expires_at=FAR_EXPIRY)
    create_supply_lot(item_kind="ADDON", tier_or_code="GLUTATHIONE", lot_number="GL-1",
                      units_total=5, expires_at=FAR_EXPIRY)
    mem = create_membership(tier="PLATINUM", covered_drip_tier="MYERS",
                            drip_credits_total=1, addon_credits_total=1)
    patient = create_patient(membership_id=mem["id"])
    appt = create_requested_appointment(
        patient["id"], myers["id"], addon_ids=[glut["id"]], lounge_id=lounge["id"],
        start_at="2026-06-23T09:00:00Z", membership_id=mem["id"])
    submit_intake(appt["id"])
    sign_consent(appt["id"])
    scheduled = schedule_appointment(appt["id"])
    mem_mid = get_success_data(api_client.get_membership(mem["id"], ADMIN))
    assert mem_mid["drip_credits_remaining"] == 0
    assert mem_mid["addon_credits_remaining"] == 0
    cancelled = get_success_data(api_client.cancel_appointment(scheduled["id"], ADMIN))
    assert cancelled["status"] == "CANCELLED"
    mem_after = get_success_data(api_client.get_membership(mem["id"], ADMIN))
    assert mem_after["drip_credits_remaining"] == 1
    assert mem_after["addon_credits_remaining"] == 1


def test_drip_only_credit_restored_on_cancel(api):
    """PRD §3.11: "When a scheduled or dispatched visit is later cancelled, the credits it
    consumed are restored: `drip_credits_remaining` is increased by `drip_credit_used` and
    `addon_credits_remaining` is increased by its `addon_credits_used`."

    A second conservation angle isolating the drip credit: a PLATINUM membership with a
    single drip credit redeems it at schedule (remaining 1->0), and cancel restores it to 1.

    Design: Difficulty/compensating_invariant/comp_membership_credits_conserved_on_schedule_cancel
    """
    set_clock("2026-06-22T00:00:00Z")
    myers = create_menu_item(tier="MYERS", requires_standing_order=False)
    lounge = create_lounge(bay_count=2)
    create_supply_lot(item_kind="DRIP_BASE", tier_or_code="MYERS", lot_number="MY-1",
                      units_total=5, expires_at=FAR_EXPIRY)
    mem = create_membership(tier="PLATINUM", covered_drip_tier="MYERS",
                            drip_credits_total=1, addon_credits_total=0)
    patient = create_patient(membership_id=mem["id"])
    appt = create_requested_appointment(
        patient["id"], myers["id"], lounge_id=lounge["id"],
        start_at="2026-06-23T09:00:00Z", membership_id=mem["id"])
    submit_intake(appt["id"])
    sign_consent(appt["id"])
    scheduled = schedule_appointment(appt["id"])
    assert scheduled["drip_credit_used"] == 1
    mem_mid = get_success_data(api_client.get_membership(mem["id"], ADMIN))
    assert mem_mid["drip_credits_remaining"] == 0
    get_success_data(api_client.cancel_appointment(scheduled["id"], ADMIN))
    mem_after = get_success_data(api_client.get_membership(mem["id"], ADMIN))
    assert mem_after["drip_credits_remaining"] == 1, "drip credit must be restored on cancel"
