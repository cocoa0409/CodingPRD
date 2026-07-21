"""Activity scheduling: facilitator overlap, room setup buffer, active-facilitator gate, final payout."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    set_clock, setup_booking_confirmed, setup_retreat_with_common_room_and_facilitator,
    new_retreat, new_room, new_facilitator,
)
from test_helpers.constants import DEFAULT_CLOCK
from test_helpers.factories import create_activity_slot_payload

_OP = TEST_USERS["operator_headers"]


# ---------------------------------------------------------------------------
# Difficulty: dual_variant_calc / facilitator_payout_flat_vs_per_head_variant
# ---------------------------------------------------------------------------
def test_final_payout_is_per_head_when_retreat_completes(api):
    """PRD §3.5: "The final figure, stamped into `payout_cents` when the retreat transitions to `COMPLETED`, instead pays 3000 cents per confirmed attendee: the sum of `party_size` across the retreat's bookings whose status is `CONFIRMED`, `CHECKED_IN`, or `COMPLETED`, multiplied by 3000 cents, ignoring the slot count."

    Design: Difficulty/dual_variant_calc/facilitator_payout_flat_vs_per_head_variant
    """
    ctx = setup_booking_confirmed(api, party_size=2, retreat_overrides={"base_price_cents": 150000})
    common = new_room(api, ctx["retreat"]["id"], kind="COMMON", bed_count=0, label="Hall")
    fac = new_facilitator(api)
    validate_success(api.create_activity_slot(
        create_activity_slot_payload(ctx["retreat"]["id"], fac["id"], common["id"],
                                     "2026-09-02T09:00:00Z", "2026-09-02T10:00:00Z"), _OP), 201)
    set_clock(api, "2026-09-10T00:00:00Z")  # past end_date 2026-09-08
    validate_success(api.complete_retreat(ctx["retreat"]["id"], _OP), 200)

    fac_after = validate_success(api.get_facilitator(fac["id"], _OP), 200)
    assert fac_after["payout_cents"] == 6000  # 3000 * 2 confirmed attendees
    booking = validate_success(api.get_booking(ctx["booking"]["id"], ctx["guest_headers"]), 200)
    assert booking["status"] == "CONFIRMED"


def test_facilitator_payout_zero_until_completion(api):
    """PRD §3.5: "A facilitator starts in `ACTIVE` and reports a `payout_cents` of 0 until a
    retreat completes."

    Design: Difficulty/dual_variant_calc/facilitator_payout_flat_vs_per_head_variant
    """
    set_clock(api, DEFAULT_CLOCK)
    fac = new_facilitator(api)
    data = validate_success(api.get_facilitator(fac["id"], _OP), 200)
    assert data["status"] == "ACTIVE"
    assert data["payout_cents"] == 0


# ---------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict / temporal_beats_constraint_on_slot_create
# ---------------------------------------------------------------------------
def _retreat_common_and_lodging(api):
    set_clock(api, DEFAULT_CLOCK)
    retreat = new_retreat(api)
    common = new_room(api, retreat["id"], kind="COMMON", bed_count=0, label="Hall A")
    lodging = new_room(api, retreat["id"], kind="LODGING", bed_count=4, label="Room B")
    fac = new_facilitator(api)
    return retreat, common, lodging, fac


def test_overlap_and_bad_room_kind_yields_double_booked(api):
    """PRD §2.9: "Eighth are temporal-window checks. Ninth are capacity and resource-kind
    checks."
    PRD §3.5: "The new interval must not overlap any other SCHEDULED slot led by the same
    facilitator ... any true overlap is rejected with ERR_FACILITATOR_DOUBLE_BOOKED (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_constraint_on_slot_create
    """
    retreat, common, lodging, fac = _retreat_common_and_lodging(api)
    validate_success(api.create_activity_slot(
        create_activity_slot_payload(retreat["id"], fac["id"], common["id"],
                                     "2026-09-02T10:00:00Z", "2026-09-02T11:00:00Z"), _OP), 201)
    # Trigger both overlaps the facilitator's slot AND targets a LODGING room.
    resp = api.create_activity_slot(
        create_activity_slot_payload(retreat["id"], fac["id"], lodging["id"],
                                     "2026-09-02T10:30:00Z", "2026-09-02T11:30:00Z"), _OP)
    validate_error(resp, ApiErrorId.ERR_FACILITATOR_DOUBLE_BOOKED.value)


def test_non_overlapping_bad_room_kind_yields_kind_mismatch(api):
    """PRD §3.5: "The room must be of kind `COMMON` (otherwise `ERR_ROOM_KIND_MISMATCH`, HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_constraint_on_slot_create
    """
    retreat, common, lodging, fac = _retreat_common_and_lodging(api)
    validate_success(api.create_activity_slot(
        create_activity_slot_payload(retreat["id"], fac["id"], common["id"],
                                     "2026-09-02T10:00:00Z", "2026-09-02T11:00:00Z"), _OP), 201)
    # No temporal overlap (12:00-13:00), so the room-kind check is reached.
    resp = api.create_activity_slot(
        create_activity_slot_payload(retreat["id"], fac["id"], lodging["id"],
                                     "2026-09-02T12:00:00Z", "2026-09-02T13:00:00Z"), _OP)
    validate_error(resp, ApiErrorId.ERR_ROOM_KIND_MISMATCH.value)


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency / slot_requires_active_facilitator
# ---------------------------------------------------------------------------
def test_slot_for_withdrawn_facilitator_rejected(api):
    """PRD §3.5: "The facilitator must be `ACTIVE` (a withdrawn facilitator cannot be scheduled; violation is `ERR_INVALID_STATE`)."

    Design: Difficulty/cross_entity_state_dependency/slot_requires_active_facilitator
    """
    ctx = setup_retreat_with_common_room_and_facilitator(api)
    validate_success(api.withdraw_facilitator(ctx["facilitator"]["id"], _OP), 200)
    resp = api.create_activity_slot(
        create_activity_slot_payload(ctx["retreat"]["id"], ctx["facilitator"]["id"],
                                     ctx["common_room"]["id"],
                                     "2026-09-02T09:00:00Z", "2026-09-02T10:00:00Z"), _OP)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_slot_for_active_facilitator_succeeds(api):
    """PRD §3.5: "A successful create places the slot in `SCHEDULED` and sets the retreat's `schedule_ready` to true."

    Design: Difficulty/cross_entity_state_dependency/slot_requires_active_facilitator
    """
    ctx = setup_retreat_with_common_room_and_facilitator(api)
    resp = api.create_activity_slot(
        create_activity_slot_payload(ctx["retreat"]["id"], ctx["facilitator"]["id"],
                                     ctx["common_room"]["id"],
                                     "2026-09-02T09:00:00Z", "2026-09-02T10:00:00Z"), _OP)
    data = validate_success(resp, 201)
    assert data["status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap / facilitator_slot_overlap_half_open
# ---------------------------------------------------------------------------
def test_facilitator_overlapping_slot_rejected(api):
    """PRD §3.5: "The new interval must not overlap any other `SCHEDULED` slot led by the same facilitator; because intervals are half-open, a slot that begins exactly when another ends is allowed, but any true overlap is rejected with `ERR_FACILITATOR_DOUBLE_BOOKED` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/facilitator_slot_overlap_half_open
    """
    set_clock(api, DEFAULT_CLOCK)
    retreat = new_retreat(api)
    room_a = new_room(api, retreat["id"], kind="COMMON", bed_count=0, label="Hall A")
    room_b = new_room(api, retreat["id"], kind="COMMON", bed_count=0, label="Hall B")
    fac = new_facilitator(api)
    validate_success(api.create_activity_slot(
        create_activity_slot_payload(retreat["id"], fac["id"], room_a["id"],
                                     "2026-09-02T10:00:00Z", "2026-09-02T11:00:00Z"), _OP), 201)
    resp = api.create_activity_slot(
        create_activity_slot_payload(retreat["id"], fac["id"], room_b["id"],
                                     "2026-09-02T10:30:00Z", "2026-09-02T11:30:00Z"), _OP)
    validate_error(resp, ApiErrorId.ERR_FACILITATOR_DOUBLE_BOOKED.value)


def test_facilitator_back_to_back_slot_allowed(api):
    """PRD §3.5: "because intervals are half-open, a slot that begins exactly when another ends
    is allowed."

    Design: Difficulty/resource_temporal_overlap/facilitator_slot_overlap_half_open
    """
    set_clock(api, DEFAULT_CLOCK)
    retreat = new_retreat(api)
    room_a = new_room(api, retreat["id"], kind="COMMON", bed_count=0, label="Hall A")
    room_b = new_room(api, retreat["id"], kind="COMMON", bed_count=0, label="Hall B")
    fac = new_facilitator(api)
    validate_success(api.create_activity_slot(
        create_activity_slot_payload(retreat["id"], fac["id"], room_a["id"],
                                     "2026-09-02T10:00:00Z", "2026-09-02T11:00:00Z"), _OP), 201)
    # 11:00 start == previous slot's end -> adjacency allowed. Different room avoids the room buffer.
    resp = api.create_activity_slot(
        create_activity_slot_payload(retreat["id"], fac["id"], room_b["id"],
                                     "2026-09-02T11:00:00Z", "2026-09-02T12:00:00Z"), _OP)
    data = validate_success(resp, 201)
    assert data["status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap / room_slot_setup_buffer_overlap
# ---------------------------------------------------------------------------
def test_room_slot_within_setup_buffer_rejected(api):
    """PRD §3.5: "within the same room, the new slot must not fall within thirty minutes of another `SCHEDULED` slot — a setup buffer applied on both sides of each existing slot — with a violation rejected as `ERR_SPACE_UNAVAILABLE` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/room_slot_setup_buffer_overlap
    """
    set_clock(api, DEFAULT_CLOCK)
    retreat = new_retreat(api)
    room = new_room(api, retreat["id"], kind="COMMON", bed_count=0, label="Hall R")
    fac1 = new_facilitator(api)
    fac2 = new_facilitator(api)
    validate_success(api.create_activity_slot(
        create_activity_slot_payload(retreat["id"], fac1["id"], room["id"],
                                     "2026-09-02T10:00:00Z", "2026-09-02T11:00:00Z"), _OP), 201)
    # Only 15 minutes after the first slot ends -> inside the 30-minute buffer.
    resp = api.create_activity_slot(
        create_activity_slot_payload(retreat["id"], fac2["id"], room["id"],
                                     "2026-09-02T11:15:00Z", "2026-09-02T12:00:00Z"), _OP)
    validate_error(resp, ApiErrorId.ERR_SPACE_UNAVAILABLE.value)


def test_room_slot_outside_setup_buffer_allowed(api):
    """PRD §3.5: "within the same room, the new slot must not fall within thirty minutes of
    another SCHEDULED slot — a setup buffer applied on both sides of each existing slot."

    Design: Difficulty/resource_temporal_overlap/room_slot_setup_buffer_overlap
    """
    set_clock(api, DEFAULT_CLOCK)
    retreat = new_retreat(api)
    room = new_room(api, retreat["id"], kind="COMMON", bed_count=0, label="Hall R")
    fac1 = new_facilitator(api)
    fac2 = new_facilitator(api)
    validate_success(api.create_activity_slot(
        create_activity_slot_payload(retreat["id"], fac1["id"], room["id"],
                                     "2026-09-02T10:00:00Z", "2026-09-02T11:00:00Z"), _OP), 201)
    # 60 minutes after the first slot ends -> comfortably outside the 30-minute buffer.
    resp = api.create_activity_slot(
        create_activity_slot_payload(retreat["id"], fac2["id"], room["id"],
                                     "2026-09-02T12:00:00Z", "2026-09-02T13:00:00Z"), _OP)
    data = validate_success(resp, 201)
    assert data["status"] == "SCHEDULED"
