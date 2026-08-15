"""Slot grid generation, channel derivation, slot listing pagination, and
slot block/unblock transitions including promotion on unblock."""
from test_helpers import (
    ApiErrorId,
    STD_SLOTS_PER_TEACHER,
    add_teacher,
    assert_instant,
    assert_time_slot,
    assert_waitlist_entry,
    assert_window_counters,
    book_slot,
    create_waitlist_entry_payload,
    generate_slots,
    get_success_data,
    list_teacher_slots,
    list_window_slots,
    make_teacher_headers,
    publish_window,
    read_window,
    set_clock,
    setup_booked_slot,
    setup_family_with_students,
    setup_window_at_stage,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_slot_grid_count_and_break_placement(api, school_admin_headers):
    """PRD 3.2: "For each day window and each eligible teacher, a cursor starts
    at the day's `start_at`; while the cursor plus `slot_length_minutes` falls
    on or before the day's `end_at`, a slot is emitted spanning from the cursor
    to the cursor plus the slot length — a slot may end exactly at the day
    window's end. The cursor then advances by the slot length plus
    `buffer_minutes`, and after every fourth slot placed for that teacher on
    that day, the cursor advances an additional fifteen minutes of break before
    the next slot is considered."

    Design: Corner/calculations/slot_grid_count_and_break_placement
    """
    ctx = setup_window_at_stage("PUBLISHED")
    window_id = ctx["window"]["id"]
    assert ctx["window"]["slots_total_count"] == STD_SLOTS_PER_TEACHER

    slots = list_window_slots(window_id)
    assert len(slots) == 8
    for slot in slots:
        assert_time_slot(slot)
    assert_instant(slots[0]["start_at"], "2026-10-05T15:00:00Z", "slot[0].start_at")
    assert_instant(slots[3]["end_at"], "2026-10-05T16:35:00Z", "slot[3].end_at")
    # 5-minute buffer plus the 15-minute break after the fourth slot.
    assert_instant(slots[4]["start_at"], "2026-10-05T16:55:00Z", "slot[4].start_at")
    assert_instant(slots[7]["end_at"], "2026-10-05T18:30:00Z", "slot[7].end_at")


def test_channel_allowed_derivation_and_teacher_skip(api, school_admin_headers):
    """PRD 3.2: "The slot's `channel_allowed` is derived from the teacher's
    channel flags: `EITHER` when the teacher supports both channels,
    `IN_PERSON` when only in-person is supported, and `VIRTUAL` when only
    virtual is supported; a teacher who supports neither channel is skipped
    entirely and produces no inventory."

    Design: Corner/calculations/channel_allowed_derivation_and_teacher_skip
    """
    ctx = setup_window_at_stage(
        "PUBLISHED",
        window_overrides={
            "name": "Sec",
            "format": "SECONDARY",
            "buffer_minutes": 0,
            "day_windows": [{
                "date": "2026-10-05",
                "start_at": "2026-10-05T15:00:00Z",
                "end_at": "2026-10-05T16:20:00Z",
            }],
        },
        teacher_specs=[
            {"full_name": "TIP", "grade_band": "SECONDARY",
             "supports_in_person": True, "supports_virtual": False},
            {"full_name": "TV", "grade_band": "SECONDARY",
             "supports_in_person": False, "supports_virtual": True},
            {"full_name": "TB", "grade_band": "SECONDARY",
             "supports_in_person": True, "supports_virtual": True},
            {"full_name": "TN", "grade_band": "SECONDARY",
             "supports_in_person": False, "supports_virtual": False},
        ],
    )
    t_in, t_virt, t_both, t_neither = ctx["teachers"]
    window_id = ctx["window"]["id"]

    in_person_slots = ctx["teacher_slots"][t_in["id"]]
    virtual_slots = ctx["teacher_slots"][t_virt["id"]]
    both_slots = ctx["teacher_slots"][t_both["id"]]
    neither_slots = ctx["teacher_slots"][t_neither["id"]]

    assert len(in_person_slots) == 4
    assert all(s["channel_allowed"] == "IN_PERSON" for s in in_person_slots)
    assert len(virtual_slots) == 4
    assert all(s["channel_allowed"] == "VIRTUAL" for s in virtual_slots)
    assert len(both_slots) == 4
    assert all(s["channel_allowed"] == "EITHER" for s in both_slots)
    assert neither_slots == []


def test_slots_list_pagination_fields(api, school_admin_headers):
    """PRD 2.3: "Paginated list-based responses include the following fields in
    the `meta` object of the response envelope: `limit`, `offset`,
    `total_count`, and `has_more`."
    PRD 2.3: "Unless otherwise specified, all list endpoints return resources
    sorted by their creation timestamp in ascending order. Slot listings — the
    slots of a window and the slots of a teacher — are the exception: they sort
    by `start_at` ascending, with ties broken by `created_at` ascending."

    Design: Corner/entities/slots_list_pagination_fields
    """
    ctx = setup_window_at_stage("PUBLISHED")
    window_id = ctx["window"]["id"]

    tail, meta_tail = validate_paginated(
        api.list_window_slots(window_id, school_admin_headers, params={"limit": 3, "offset": 6})
    )
    assert len(tail) == 2
    assert meta_tail["total_count"] == 8
    assert meta_tail["limit"] == 3
    assert meta_tail["offset"] == 6
    assert meta_tail["has_more"] is False

    head, meta_head = validate_paginated(
        api.list_window_slots(window_id, school_admin_headers, params={"limit": 3, "offset": 0})
    )
    assert len(head) == 3
    assert meta_head["total_count"] == 8
    assert meta_head["has_more"] is True
    # start_at ascending: the first page leads with the 15:00 slot.
    assert_instant(head[0]["start_at"], "2026-10-05T15:00:00Z", "head[0].start_at")


def test_teacher_block_and_unblock_own_slot_cycle(api, school_admin_headers):
    """PRD 3.2: "Blocking a slot moves it from `OPEN` to `BLOCKED`; the slot
    must currently be `OPEN` (otherwise `ERR_SLOT_NOT_AVAILABLE`), the window
    must be `PUBLISHED` or `BOOKING_OPEN` (otherwise `ERR_INVALID_WINDOW_STATE`),
    and a `Teacher` caller may block only their own slots (otherwise
    `ERR_FORBIDDEN`), while staff may block any slot."
    PRD 3.2: "Unblocking reverses the move from `BLOCKED` back to `OPEN` under
    the same window-state gate, with a slot that is not currently `BLOCKED`
    rejected with `ERR_INVALID_STATE`."
    PRD 2.8: "These counters are recomputed by every operation that can change
    them — slot generation, blocking and unblocking, booking creation,
    cancellation, rescheduling, waitlist promotion, claims, declines,
    withdrawals, the window lock, and the deactivation, restriction, and
    withdrawal cascades — so a read of the window always reflects the current
    state of its children."

    Design: Corner/state_machines/teacher_block_and_unblock_own_slot_cycle
    """
    ctx = setup_window_at_stage("PUBLISHED")
    teacher = ctx["teachers"][0]
    slot = ctx["teacher_slots"][teacher["id"]][0]
    own = make_teacher_headers(teacher["id"])

    blocked = validate_success(api.block_slot(slot["id"], {"reason": "team meeting"}, own))
    assert_time_slot(blocked)
    assert blocked["status"] == "BLOCKED"
    assert_window_counters(read_window(ctx["window"]["id"]), open_=7)

    unblocked = validate_success(api.unblock_slot(slot["id"], own))
    # Window is PUBLISHED, so no promotion runs and the slot returns to OPEN.
    assert unblocked["status"] == "OPEN"
    assert_window_counters(read_window(ctx["window"]["id"]), open_=8)


def test_block_booked_slot_rejected(api):
    """PRD 3.2: "Blocking a slot moves it from `OPEN` to `BLOCKED`; the slot
    must currently be `OPEN` (otherwise `ERR_SLOT_NOT_AVAILABLE`), the window
    must be `PUBLISHED` or `BOOKING_OPEN` (otherwise `ERR_INVALID_WINDOW_STATE`),
    and a `Teacher` caller may block only their own slots (otherwise
    `ERR_FORBIDDEN`), while staff may block any slot."

    Design: Corner/state_machines/block_booked_slot_rejected
    """
    ctx = setup_booked_slot()
    teacher = ctx["teachers"][0]
    response = api.block_slot(ctx["slot"]["id"], {}, make_teacher_headers(teacher["id"]))
    validate_error(response, ApiErrorId.ERR_SLOT_NOT_AVAILABLE, 409)


def test_unblock_open_slot_rejected(api):
    """PRD 3.2: "Unblocking reverses the move from `BLOCKED` back to `OPEN`
    under the same window-state gate, with a slot that is not currently
    `BLOCKED` rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/unblock_open_slot_rejected
    """
    ctx = setup_window_at_stage("BOOKING_OPEN")
    teacher = ctx["teachers"][0]
    slot = ctx["teacher_slots"][teacher["id"]][0]
    response = api.unblock_slot(slot["id"], make_teacher_headers(teacher["id"]))
    validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)


def test_unblock_triggers_promotion(api):
    """PRD 3.2: "When an unblock lands while the window is `BOOKING_OPEN`, the
    waitlist promotion selector runs immediately on the freed slot, so it may
    move straight from `BLOCKED` through `OPEN` to `HELD` without ever being
    visible as bookable."
    PRD 3.6: "An offer moves the entry from `WAITING` to `OFFERED` and the slot
    from `OPEN` to `HELD` in the same sweep."

    Design: Corner/endpoints/unblock_triggers_promotion
    """
    ctx = setup_window_at_stage("BOOKING_OPEN")
    teacher = ctx["teachers"][0]
    slot2 = ctx["teacher_slots"][teacher["id"]][2]
    own = make_teacher_headers(teacher["id"])
    get_success_data(api.block_slot(slot2["id"], {"reason": "prep"}, own))

    party = setup_family_with_students(ctx, 1)
    entry = get_success_data(api.create_waitlist_entry(
        create_waitlist_entry_payload(ctx["window"]["id"], party["students"][0]["id"],
                                      teacher["id"], "EITHER"),
        party["guardian"],
    ))

    unblocked = validate_success(api.unblock_slot(slot2["id"], own))
    assert unblocked["status"] == "HELD"

    entry_after = validate_success(api.get_waitlist_entry(entry["id"], party["guardian"]))
    assert_waitlist_entry(entry_after)
    assert entry_after["status"] == "OFFERED"
    assert entry_after["offered_slot_id"] == slot2["id"]
