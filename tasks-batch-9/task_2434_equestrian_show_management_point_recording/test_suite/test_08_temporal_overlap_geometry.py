"""Two different overlap geometries over the same bookings: the ring's and the official's."""

from test_helpers import api_client, validate_error, validate_paginated, validate_success
from test_helpers.factories import create_official_assignment_payload, create_ring_slot_payload
from test_helpers.fixtures import (
    approve_license,
    book_slot,
    build_approved_show,
    card_official,
    create_class,
    create_division,
    create_official,
    create_ring,
    create_show,
    get_class,
    get_official,
    get_ring,
    get_slot,
    open_class,
    ring_version,
)
from test_helpers.test_users import TEST_USERS

FIVE_CLASSES = [
    {"class_number": 101, "name": "Open Jumper A", "class_share_bp": 1000},
    {"class_number": 102, "name": "Open Jumper B", "class_share_bp": 1000},
    {"class_number": 103, "name": "Open Jumper C", "class_share_bp": 1000},
    {"class_number": 104, "name": "Open Jumper D", "class_share_bp": 1000},
    {"class_number": 105, "name": "Open Jumper E", "class_share_bp": 1000},
]


def _one_ring_and_five_empty_classes():
    """Five OPEN classes with no entries, so every booking is exactly 20 minutes long."""
    return build_approved_show(class_specs=FIVE_CLASSES, ring_specs=[{}])


def _book(ring_id, class_id, start_utc, expected_ring_version):
    return api_client.create_ring_slot(
        create_ring_slot_payload(ring_id, class_id, start_utc, expected_ring_version),
        TEST_USERS["ring_master_headers"],
    )


def _three_rings_and_four_slots():
    """Rings A, B and C carrying four 20-minute occupancies, and one judge on the first."""
    show = create_show()
    rings = [create_ring(show["id"], name=name) for name in ("Ring A", "Ring B", "Ring C")]
    division = create_division(show["id"])
    classes = [
        create_class(division["id"], class_number=number, name=f"Open Jumper {number}",
                     class_share_bp=1000)
        for number in (101, 102, 103, 104)
    ]
    approve_license(show["id"])
    for row in classes:
        open_class(row["id"])

    slots = {
        "a1": book_slot(rings[0]["id"], classes[0]["id"], "2026-09-10T14:00:00Z"),
        "a2": book_slot(rings[0]["id"], classes[1]["id"], "2026-09-10T14:30:00Z"),
        "b": book_slot(rings[1]["id"], classes[2]["id"], "2026-09-10T15:10:00Z"),
        "c": book_slot(rings[2]["id"], classes[3]["id"], "2026-09-10T15:11:00Z"),
    }
    official = create_official(license_roles=["JUDGE"], licensed_disciplines=["JUMPER"])
    assignment = card_official(official["id"], slots["a1"]["id"], "JUDGE")
    return {
        "show_id": show["id"],
        "slots": slots,
        "official_id": official["id"],
        "assignment": assignment,
    }


def test_the_turnover_buffer_blocks_a_start_one_minute_early_and_admits_the_exact_touch():
    """The first booking occupies 14:00-14:20 on a ring whose turnover buffer is 10 minutes. A
    second class starting at 14:29 collides, because 14:29 is strictly earlier than 14:20 plus
    the buffer; a class starting at exactly 14:30 does not, because the comparison is strict.
    The accepted booking reuses the very ring version the rejected one carried, which proves the
    refused write never incremented it, and the refused class is left unscheduled.

    PRD §3.6: "The comparison is on half-open intervals widened symmetrically by the ring's `turnover_buffer_minutes`."
    PRD §3.6: "The candidate collides with an existing occupancy when the candidate's `start_utc` is strictly earlier than that occupancy's `end_utc` advanced by `turnover_buffer_minutes`, *and* that occupancy's `start_utc` is strictly earlier than the candidate's `end_utc` advanced by `turnover_buffer_minutes`."
    PRD §3.6: "Because both comparisons are strict, a candidate that begins exactly at an existing occupancy's `end_utc` plus the buffer does not collide."
    PRD §2.7: "The value must equal the target `Ring`'s current `version`; when it does not, the booking is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.6: "Booking increments both the ring's and the class's `version`, and moves the class `OPEN → SCHEDULED`."

    Design: Difficulty/resource_temporal_overlap/ring_slot_half_open_plus_turnover_buffer
    """
    ctx = _one_ring_and_five_empty_classes()
    ring_id = ctx["ring_id"]
    first, second, third = ctx["class_ids"][0], ctx["class_ids"][1], ctx["class_ids"][2]

    booked = validate_success(
        _book(ring_id, first, "2026-09-10T14:00:00Z", ring_version(ring_id)), 201
    )
    assert booked["duration_minutes"] == 20
    assert booked["end_utc"] == "2026-09-10T14:20:00Z"
    assert booked["warmup_start_utc"] == "2026-09-10T13:30:00Z"
    assert booked["order_index"] == 1

    version_after_first = ring_version(ring_id)

    validate_error(
        _book(ring_id, second, "2026-09-10T14:29:00Z", version_after_first),
        "ERR_RING_SLOT_OVERLAP",
        409,
    )

    touching = validate_success(
        _book(ring_id, third, "2026-09-10T14:30:00Z", version_after_first), 201
    )
    assert touching["start_utc"] == "2026-09-10T14:30:00Z"
    assert touching["end_utc"] == "2026-09-10T14:50:00Z"

    assert get_class(second)["status"] == "OPEN"
    assert get_class(third)["status"] == "SCHEDULED"


def test_the_buffer_applies_on_the_earlier_side_too_and_the_running_order_is_rebuilt():
    """A candidate that ends before an existing booking begins can still collide, because the
    buffer widens both sides: a 13:31-13:51 window is refused against the 14:00 start, while a
    13:20-13:40 window is admitted. After the insertions the ring counts three occupancies for
    60 minutes — the two refusals contributing nothing — and the running order is renumbered by
    start time across the whole ring, so the late-inserted 13:20 booking takes first place.

    PRD §3.6: "The candidate collides with an existing occupancy when the candidate's `start_utc` is strictly earlier than that occupancy's `end_utc` advanced by `turnover_buffer_minutes`, *and* that occupancy's `start_utc` is strictly earlier than the candidate's `end_utc` advanced by `turnover_buffer_minutes`."
    PRD §3.6: "**Running order.** After every insertion — a class booking or a maintenance hold — the ring's running order is recomputed across the whole ring."
    PRD §3.6: "The occupancies that count are those whose `status` is `SCHEDULED`, `RUNNING` or `COMPLETED`; they are sorted by `start_utc` ascending, with `created_at` ascending as the sole tie-break (`id` is never consulted), and each is assigned a 1-based `order_index` equal to its position in that sorted list."
    PRD §3.6: "The ring's `scheduled_minutes_total` becomes the sum, over those same occupancies, of the whole minutes from each one's `start_utc` to its `end_utc`, and `slot_count` becomes their count."

    Design: Difficulty/resource_temporal_overlap/ring_slot_half_open_plus_turnover_buffer
    """
    ctx = _one_ring_and_five_empty_classes()
    ring_id = ctx["ring_id"]
    first, third, fourth, fifth = (
        ctx["class_ids"][0],
        ctx["class_ids"][2],
        ctx["class_ids"][3],
        ctx["class_ids"][4],
    )

    slot_one = validate_success(
        _book(ring_id, first, "2026-09-10T14:00:00Z", ring_version(ring_id)), 201
    )
    slot_three = validate_success(
        _book(ring_id, third, "2026-09-10T14:30:00Z", ring_version(ring_id)), 201
    )
    version_after_two = ring_version(ring_id)

    validate_error(
        _book(ring_id, fourth, "2026-09-10T13:31:00Z", version_after_two),
        "ERR_RING_SLOT_OVERLAP",
        409,
    )
    slot_five = validate_success(
        _book(ring_id, fifth, "2026-09-10T13:20:00Z", version_after_two), 201
    )
    assert slot_five["end_utc"] == "2026-09-10T13:40:00Z"

    ring = get_ring(ring_id)
    assert ring["slot_count"] == 3
    assert ring["scheduled_minutes_total"] == 60

    assert get_slot(slot_five["id"])["order_index"] == 1
    assert get_slot(slot_one["id"])["order_index"] == 2
    assert get_slot(slot_three["id"])["order_index"] == 3

    assert get_class(fourth)["status"] == "OPEN"

    rows, _meta = validate_paginated(
        api_client.list_ring_slots(
            TEST_USERS["ring_master_headers"],
            params={"ring_id": ring_id, "status": "SCHEDULED"},
        )
    )
    assert len(rows) == 3


def test_warm_up_time_makes_two_non_colliding_ring_windows_collide_for_the_official():
    """The 14:00 and 14:30 occupancies on one ring are legal for the ring — 14:30 is not earlier
    than 14:20 plus the buffer — yet the same judge cannot take both, because the official's
    interval starts at the warm-up: 13:30-14:20 and 14:00-14:50 do overlap. Moving to a
    different ring widens the comparison by the 20-minute travel gap, and a warm-up beginning
    exactly at 14:20 plus 20 minutes still collides under the non-strict comparison.

    PRD §3.6: "Warm-up windows play no part in ring collision detection — they matter only for officials' occupancy, per the geometry below."
    PRD §3.6: "The official's occupancy of an assignment runs on a *closed* interval from the assigned occupancy's `warmup_start_utc` to its `end_utc` — the supervised warm-up window counts as occupied time."
    PRD §3.6: "A required travel gap widens the comparison: zero minutes when the two occupancies are on the same ring, and 20 minutes when they are on different rings."
    PRD §3.6: "Both comparisons are non-strict, so intervals that merely touch at their endpoints do collide."

    Design: Difficulty/resource_temporal_overlap/official_closed_interval_plus_travel_gap
    """
    ctx = _three_rings_and_four_slots()
    official_id = ctx["official_id"]

    assert ctx["slots"]["a1"]["warmup_start_utc"] == "2026-09-10T13:30:00Z"
    assert ctx["slots"]["a1"]["end_utc"] == "2026-09-10T14:20:00Z"
    assert ctx["slots"]["a2"]["warmup_start_utc"] == "2026-09-10T14:00:00Z"
    assert ctx["slots"]["b"]["warmup_start_utc"] == "2026-09-10T14:40:00Z"
    assert get_official(official_id)["assigned_minutes"] == 50

    validate_error(
        api_client.create_official_assignment(
            create_official_assignment_payload(official_id, ctx["slots"]["a2"]["id"], "JUDGE"),
            TEST_USERS["show_secretary_headers"],
        ),
        "ERR_OFFICIAL_TIME_CONFLICT",
        409,
    )

    validate_error(
        api_client.create_official_assignment(
            create_official_assignment_payload(official_id, ctx["slots"]["b"]["id"], "JUDGE"),
            TEST_USERS["show_secretary_headers"],
        ),
        "ERR_OFFICIAL_TIME_CONFLICT",
        409,
    )

    assert get_official(official_id)["assigned_minutes"] == 50


def test_one_minute_past_the_travel_gap_is_bookable_and_adds_its_whole_window_to_the_load():
    """A third ring's occupancy warms up at 14:41, one minute past the gap-widened boundary that
    refused the 14:40 window, so the card is accepted. The official's load rises by the whole
    14:41-15:31 occupancy to 100 minutes, well under the daily ceiling, and the two refused
    cards left no rows behind: the official holds exactly two active assignments.

    PRD §3.6: "The candidate collides with an existing assignment when the candidate's `warmup_start_utc` is at or before the existing occupancy's `end_utc` advanced by the required gap, *and* the existing occupancy's `warmup_start_utc` is at or before the candidate's `end_utc` advanced by the required gap."
    PRD §3.6: "A new assignment has `status` of `ACTIVE`, and the official's `assigned_minutes` is increased by the whole minutes from the occupancy's `warmup_start_utc` to its `end_utc`; the official's `version` increments."
    PRD §3.6: "Fourth, the daily load ceiling."
    PRD §3.6: "The official's current `assigned_minutes` plus the whole minutes from the candidate occupancy's `warmup_start_utc` to its `end_utc` must not exceed 480 minutes — eight hours of carded duty per official."

    Design: Difficulty/resource_temporal_overlap/official_closed_interval_plus_travel_gap
    """
    ctx = _three_rings_and_four_slots()
    official_id = ctx["official_id"]

    validate_error(
        api_client.create_official_assignment(
            create_official_assignment_payload(official_id, ctx["slots"]["a2"]["id"], "JUDGE"),
            TEST_USERS["show_secretary_headers"],
        ),
        "ERR_OFFICIAL_TIME_CONFLICT",
        409,
    )
    validate_error(
        api_client.create_official_assignment(
            create_official_assignment_payload(official_id, ctx["slots"]["b"]["id"], "JUDGE"),
            TEST_USERS["show_secretary_headers"],
        ),
        "ERR_OFFICIAL_TIME_CONFLICT",
        409,
    )

    assert ctx["slots"]["c"]["warmup_start_utc"] == "2026-09-10T14:41:00Z"
    assert ctx["slots"]["c"]["end_utc"] == "2026-09-10T15:31:00Z"

    accepted = validate_success(
        api_client.create_official_assignment(
            create_official_assignment_payload(official_id, ctx["slots"]["c"]["id"], "JUDGE"),
            TEST_USERS["show_secretary_headers"],
        ),
        201,
    )
    assert accepted["status"] == "ACTIVE"
    assert get_official(official_id)["assigned_minutes"] == 100

    rows, _meta = validate_paginated(
        api_client.list_official_assignments(
            TEST_USERS["show_secretary_headers"], params={"official_id": official_id}
        )
    )
    assert len(rows) == 2
    assert {row["status"] for row in rows} == {"ACTIVE"}
    assert {row["slot_id"] for row in rows} == {ctx["slots"]["a1"]["id"], ctx["slots"]["c"]["id"]}
