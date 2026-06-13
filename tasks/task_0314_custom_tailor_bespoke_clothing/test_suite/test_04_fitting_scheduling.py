"""Fitting scheduling: room cleanup-buffer overlap, tailor strict overlap, the
milestone-vs-overlap validation priority, and OCC on the order version.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_confirmed_order_with_deposit, create_fabric, create_master_tailor,
    create_journeyman_tailor, create_open_room,
    create_fitting_payload,
    TEST_USERS,
)

SA = TEST_USERS["sales_associate_headers"]
FS = TEST_USERS["fitting_specialist_headers"]
SM = TEST_USERS["shop_manager_headers"]


def _schedule(api, order_id, tailor_id, room_id, milestone, version, start_at, end_at):
    return api.create_fitting(
        order_id,
        create_fitting_payload(tailor_id, room_id, milestone, start_at, end_at, version),
        FS)


# ─── Queue A: resource_temporal_overlap ─────────────────────────────────

def test_room_trailing_cleanup_buffer_collision(api):
    """PRD §3.3: "A fitting occupies its room for its half-open interval from `start_at` up to but not including `end_at`, *plus* the room's `cleanup_buffer_minutes` of trailing buffer afterward; that occupied span must not overlap any other scheduled fitting in the same room, or the booking is rejected with `ERR_ROOM_DOUBLE_BOOKED` (HTTP 409)."

    Room buffer 15 min. Existing BASTED 09:00-10:00. A new BASTED 10:10-10:40 starts only
    10 min after the prior end — inside the 15-min trailing buffer — so it collides.

    Design: Difficulty/resource_temporal_overlap/overlap_room_trailing_cleanup_buffer_collision
    """
    fabric = create_fabric(price_per_meter_cents=8000, bolt_meters_initial=100)
    room = create_open_room(cleanup_buffer_minutes=15)
    tailor_a = create_journeyman_tailor(display_name="Jr A")
    tailor_b = create_journeyman_tailor(display_name="Jr B")

    bundle_a = create_confirmed_order_with_deposit(fabric=fabric, bolt_meters_initial=100)
    order_a = get_success_data(api.get_order(bundle_a["order"]["id"], SA))
    validate_success(_schedule(api, order_a["id"], tailor_a["id"], room["id"],
                               "BASTED", order_a["version"],
                               "2026-07-09T09:00:00.000Z", "2026-07-09T10:00:00.000Z"), 201)

    bundle_b = create_confirmed_order_with_deposit(fabric=fabric, bolt_meters_initial=100)
    order_b = get_success_data(api.get_order(bundle_b["order"]["id"], SA))
    res = _schedule(api, order_b["id"], tailor_b["id"], room["id"],
                    "BASTED", order_b["version"],
                    "2026-07-09T10:10:00.000Z", "2026-07-09T10:40:00.000Z")
    validate_error(res, "ERR_ROOM_DOUBLE_BOOKED")


def test_room_overlap_is_per_room_not_global(api):
    """PRD §3.3: "that occupied span must not overlap any other scheduled fitting in the same room, or the booking is rejected with `ERR_ROOM_DOUBLE_BOOKED` (HTTP 409)."

    Second overlap instance proving the room constraint is scoped to the SAME room: the
    identical 09:00-10:00 window in a DIFFERENT open room (and a different tailor) schedules
    successfully — no room collision.

    Design: Difficulty/resource_temporal_overlap/overlap_room_trailing_cleanup_buffer_collision
    """
    fabric = create_fabric(price_per_meter_cents=8000, bolt_meters_initial=100)
    room_one = create_open_room(room_name="RoomOne", cleanup_buffer_minutes=15)
    room_two = create_open_room(room_name="RoomTwo", cleanup_buffer_minutes=15)
    tailor_a = create_journeyman_tailor(display_name="Jr One")
    tailor_b = create_journeyman_tailor(display_name="Jr Two")

    bundle_a = create_confirmed_order_with_deposit(fabric=fabric, bolt_meters_initial=100)
    order_a = get_success_data(api.get_order(bundle_a["order"]["id"], SA))
    validate_success(_schedule(api, order_a["id"], tailor_a["id"], room_one["id"],
                               "BASTED", order_a["version"],
                               "2026-07-09T09:00:00.000Z", "2026-07-09T10:00:00.000Z"), 201)

    bundle_b = create_confirmed_order_with_deposit(fabric=fabric, bolt_meters_initial=100)
    order_b = get_success_data(api.get_order(bundle_b["order"]["id"], SA))
    res = _schedule(api, order_b["id"], tailor_b["id"], room_two["id"],
                    "BASTED", order_b["version"],
                    "2026-07-09T09:00:00.000Z", "2026-07-09T10:00:00.000Z")
    validate_success(res, 201)


def test_tailor_strict_overlap_no_buffer(api):
    """PRD §3.3: "a fitting's half-open interval from `start_at` up to but not including `end_at` must not overlap any other scheduled fitting for the same tailor, with no trailing buffer added, and a clash is rejected with `ERR_TAILOR_DOUBLE_BOOKED` (HTTP 409)."

    Same tailor booked 09:30-10:30 raw-overlaps an existing 09:00-10:00 fitting, even
    though the second fitting is in a different (free) room.

    Design: Difficulty/resource_temporal_overlap/overlap_tailor_no_buffer_strict_halfopen
    """
    fabric = create_fabric(price_per_meter_cents=8000, bolt_meters_initial=100)
    tailor = create_journeyman_tailor(display_name="Jr Shared")
    room_a = create_open_room(room_name="RA")
    room_b = create_open_room(room_name="RB")

    bundle_a = create_confirmed_order_with_deposit(fabric=fabric, bolt_meters_initial=100)
    order_a = get_success_data(api.get_order(bundle_a["order"]["id"], SA))
    validate_success(_schedule(api, order_a["id"], tailor["id"], room_a["id"],
                               "BASTED", order_a["version"],
                               "2026-07-11T09:00:00.000Z", "2026-07-11T10:00:00.000Z"), 201)

    bundle_b = create_confirmed_order_with_deposit(fabric=fabric, bolt_meters_initial=100)
    order_b = get_success_data(api.get_order(bundle_b["order"]["id"], SA))
    res = _schedule(api, order_b["id"], tailor["id"], room_b["id"],
                    "BASTED", order_b["version"],
                    "2026-07-11T09:30:00.000Z", "2026-07-11T10:30:00.000Z")
    validate_error(res, "ERR_TAILOR_DOUBLE_BOOKED")


def test_tailor_adjacent_half_open_no_buffer_allowed(api):
    """PRD §3.3: "a fitting's half-open interval from `start_at` up to but not including `end_at` must not overlap any other scheduled fitting for the same tailor, with no trailing buffer added".

    Second overlap instance on the tailor rule, proving the half-open / no-buffer geometry:
    the same tailor booked back-to-back 10:00-11:00 immediately after a 09:00-10:00 fitting
    does NOT overlap (10:00 is the excluded end of the first, and no buffer is added), so it
    schedules.

    Design: Difficulty/resource_temporal_overlap/overlap_tailor_no_buffer_strict_halfopen
    """
    fabric = create_fabric(price_per_meter_cents=8000, bolt_meters_initial=100)
    tailor = create_journeyman_tailor(display_name="Jr Adjacent")
    room = create_open_room(room_name="RAdj", cleanup_buffer_minutes=0)

    bundle_a = create_confirmed_order_with_deposit(fabric=fabric, bolt_meters_initial=100)
    order_a = get_success_data(api.get_order(bundle_a["order"]["id"], SA))
    validate_success(_schedule(api, order_a["id"], tailor["id"], room["id"],
                               "BASTED", order_a["version"],
                               "2026-07-12T09:00:00.000Z", "2026-07-12T10:00:00.000Z"), 201)

    bundle_b = create_confirmed_order_with_deposit(fabric=fabric, bolt_meters_initial=100)
    order_b = get_success_data(api.get_order(bundle_b["order"]["id"], SA))
    res = _schedule(api, order_b["id"], tailor["id"], room["id"],
                    "BASTED", order_b["version"],
                    "2026-07-12T10:00:00.000Z", "2026-07-12T11:00:00.000Z")
    validate_success(res, 201)


# ─── Queue A: priority_pair_validation_conflict (milestone vs overlap) ──

def test_milestone_ladder_beats_room_overlap(api):
    """PRD §3.3: "the next milestone that may be scheduled or recorded is the lowest rung not yet passed in this round, and any attempt to skip ahead is rejected with `ERR_MILESTONE_OUT_OF_ORDER`."

    The subject order has never had a BASTED fitting, so a FORWARD schedule is out of
    order; its window also collides with another order's BASTED in the same room. The
    milestone-ladder check (priority 9) is reported, not the room overlap (priority 11).

    Design: Difficulty/priority_pair_validation_conflict/priority_safety_milestone_beats_temporal_overlap_on_fitting
    """
    fabric = create_fabric(price_per_meter_cents=8000, bolt_meters_initial=100)
    tailor = create_journeyman_tailor(display_name="Jr PP")
    room = create_open_room(room_name="R8")

    bundle_a = create_confirmed_order_with_deposit(fabric=fabric, bolt_meters_initial=100)
    order_a = get_success_data(api.get_order(bundle_a["order"]["id"], SA))
    validate_success(_schedule(api, order_a["id"], tailor["id"], room["id"],
                               "BASTED", order_a["version"],
                               "2026-07-05T09:00:00.000Z", "2026-07-05T10:00:00.000Z"), 201)

    bundle_b = create_confirmed_order_with_deposit(fabric=fabric, bolt_meters_initial=100)
    order_b = get_success_data(api.get_order(bundle_b["order"]["id"], SA))
    # FORWARD before any BASTED -> milestone out of order; window also overlaps room.
    res = _schedule(api, order_b["id"], tailor["id"], room["id"],
                    "FORWARD", order_b["version"],
                    "2026-07-05T09:30:00.000Z", "2026-07-05T10:30:00.000Z")
    validate_error(res, "ERR_MILESTONE_OUT_OF_ORDER")


def test_milestone_ladder_beats_tailor_overlap(api):
    """PRD §3.3: "the next milestone that may be scheduled or recorded is the lowest rung not yet passed in this round, and any attempt to skip ahead is rejected with `ERR_MILESTONE_OUT_OF_ORDER`."

    Second priority instance: a FINAL-before-BASTED schedule whose window also collides
    with the same tailor's existing fitting is still reported on the milestone-ladder
    check, which precedes the temporal-overlap check.

    Design: Difficulty/priority_pair_validation_conflict/priority_safety_milestone_beats_temporal_overlap_on_fitting
    """
    fabric = create_fabric(price_per_meter_cents=8000, bolt_meters_initial=100)
    tailor = create_master_tailor(display_name="Master PP")
    room_a = create_open_room(room_name="RppA")
    room_b = create_open_room(room_name="RppB")

    bundle_a = create_confirmed_order_with_deposit(fabric=fabric, bolt_meters_initial=100)
    order_a = get_success_data(api.get_order(bundle_a["order"]["id"], SA))
    validate_success(_schedule(api, order_a["id"], tailor["id"], room_a["id"],
                               "BASTED", order_a["version"],
                               "2026-07-15T09:00:00.000Z", "2026-07-15T10:00:00.000Z"), 201)

    bundle_b = create_confirmed_order_with_deposit(fabric=fabric, bolt_meters_initial=100)
    order_b = get_success_data(api.get_order(bundle_b["order"]["id"], SA))
    # FINAL before BASTED -> milestone out of order; window also overlaps the tailor.
    res = _schedule(api, order_b["id"], tailor["id"], room_b["id"],
                    "FINAL", order_b["version"],
                    "2026-07-15T09:30:00.000Z", "2026-07-15T10:30:00.000Z")
    validate_error(res, "ERR_MILESTONE_OUT_OF_ORDER")


def test_deposit_state_gate_beats_fiscal_amount_check(api):
    """PRD §3.4: "a `DEPOSIT` may be captured only while the order is `CONFIRMED`, a `BALANCE` may be captured only while the order is `READY`, and any payment whose amount is not strictly positive is likewise refused — all three conditions, when violated, yield `ERR_PAYMENT_NOT_ALLOWED_NOW` (HTTP 409)."

    A DEPOSIT attempted on a still-DRAFT order fails the state gate (DEPOSIT only while
    CONFIRMED) before any fiscal amount evaluation; the state-gated payment error wins.

    Design: Difficulty/priority_pair_validation_conflict/priority_state_beats_fiscal_on_pickup
    """
    from test_helpers import create_draft_order, create_payment_payload
    bundle = create_draft_order(option_codes=("MONOGRAM",))
    res = api.create_payment(bundle["order"]["id"],
                             create_payment_payload("DEPOSIT", 48750), SA)
    validate_error(res, "ERR_PAYMENT_NOT_ALLOWED_NOW")


def test_balance_state_gate_beats_fiscal_amount_check(api):
    """PRD §3.4: "a `DEPOSIT` may be captured only while the order is `CONFIRMED`, a `BALANCE` may be captured only while the order is `READY`, and any payment whose amount is not strictly positive is likewise refused — all three conditions, when violated, yield `ERR_PAYMENT_NOT_ALLOWED_NOW` (HTTP 409)."

    Second priority instance: a BALANCE payment attempted on a CONFIRMED (not READY) order
    is refused on the state gate (BALANCE only while READY) — the state-gated payment error
    is returned regardless of the amount being otherwise plausible.

    Design: Difficulty/priority_pair_validation_conflict/priority_state_beats_fiscal_on_pickup
    """
    from test_helpers import create_confirmed_order, create_payment_payload
    bundle = create_confirmed_order(option_codes=("MONOGRAM", "CONTRAST_LINING"))
    res = api.create_payment(bundle["order"]["id"],
                             create_payment_payload("BALANCE", 1000), SA)
    validate_error(res, "ERR_PAYMENT_NOT_ALLOWED_NOW")


# ─── Queue B: OCC fitting schedule stale order version ──────────────────

def test_schedule_fitting_with_stale_order_version_rejected(api):
    """PRD §2.9: "Scheduling a fitting on an order requires the request to carry `expected_order_version`, holding the `version` of the target `GarmentOrder` that the client last observed; if that value does not equal the order's current `version` at the moment the server processes the request, the schedule is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    After one fitting is scheduled the order version advances; presenting the pre-schedule
    version on the next schedule is stale.

    Design: Corner/cross_cutting_complexity_layers/occ_fitting_schedule_stale_order_version
    """
    fabric = create_fabric(price_per_meter_cents=8000, bolt_meters_initial=50)
    tailor = create_journeyman_tailor(display_name="Jr OF")
    room = create_open_room()
    bundle = create_confirmed_order_with_deposit(fabric=fabric, bolt_meters_initial=50)
    order = get_success_data(api.get_order(bundle["order"]["id"], SA))
    stale_version = order["version"]

    basted = validate_success(_schedule(api, order["id"], tailor["id"], room["id"],
                                         "BASTED", stale_version,
                                         "2026-07-30T09:00:00.000Z", "2026-07-30T10:00:00.000Z"), 201)
    validate_success(api.record_fitting_outcome(order["id"], basted["id"], {"result": "PASS"}, FS), 200)

    # stale_version is now one behind the order's current version (the schedule bumped it).
    res = _schedule(api, order["id"], tailor["id"], room["id"],
                    "FORWARD", stale_version,
                    "2026-07-31T09:00:00.000Z", "2026-07-31T10:00:00.000Z")
    validate_error(res, "ERR_STALE_VERSION")
