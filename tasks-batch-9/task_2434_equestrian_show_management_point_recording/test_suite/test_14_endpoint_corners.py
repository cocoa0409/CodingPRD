"""Endpoint behaviour at the edges: the check-in lead window and the ordered call-the-class gates."""

from test_helpers import api_client, validate_error, validate_paginated, validate_success
from test_helpers.fixtures import (
    book_slot,
    build_approved_show,
    build_judge_and_steward,
    card_official,
    create_coverage_shift,
    get_class,
    get_ring,
    get_slot,
    record_footing_maintenance,
    set_clock,
)
from test_helpers.test_users import TEST_USERS

GROUNDS = TEST_USERS["grounds_manager_headers"]
RING_MASTER = TEST_USERS["ring_master_headers"]


def _shift_row(show_id, shift_id, **params):
    rows, meta = validate_paginated(
        api_client.list_show_coverage_shifts(show_id, GROUNDS, params=params or None)
    )
    match = [row for row in rows if row["id"] == shift_id]
    return (match[0] if match else None), meta


def test_check_in_opens_exactly_sixty_minutes_before_the_window_and_closes_after_one_use():
    """The lead window is a boundary, not a courtesy: one minute short of the hour the provider is
    turned away and the window is untouched, still SCHEDULED at its creation version; at exactly
    sixty minutes before it opens the same call succeeds and bumps the version once. A third call
    is refused as a replay rather than as an early check-in, because the window is no longer
    SCHEDULED, and the pair of filters on the collection finds the now-active veterinary window
    while leaving the farrier window out of the answer.

    PRD §3.3: "And it is only permitted once the logical clock has reached one hour before the window opens — that is, at or after the window's `start_utc` minus 60 minutes."
    PRD §3.3: "Earlier than that, the answer is `ERR_COVERAGE_CHECKIN_TOO_EARLY`."
    PRD §3.3: "A provider checks in by activating the window, moving it `SCHEDULED → ACTIVE` and incrementing its `version`."
    PRD §3.3: "Activation is only permitted from `SCHEDULED`; a second activation is refused with `ERR_COVERAGE_SHIFT_NOT_SCHEDULED`."
    PRD §3.3: "A new window has `status` of `SCHEDULED`."
    PRD §2.4: "Filters are exact-match on the named field and may be combined; supplying none returns the whole collection."

    Design: Corner/endpoints/coverage_checkin_lead_window_boundary
    """
    ctx = build_approved_show()
    show_id = ctx["show_id"]

    vet = create_coverage_shift(
        show_id, start_utc="2026-09-10T14:00:00Z", end_utc="2026-09-10T20:00:00Z"
    )
    farrier = create_coverage_shift(
        show_id,
        coverage_type="FARRIER",
        provider_name="Anvil Road Farriers",
        start_utc="2026-09-10T14:00:00Z",
        end_utc="2026-09-10T20:00:00Z",
    )
    assert vet["status"] == "SCHEDULED"
    assert vet["version"] == 1

    set_clock("2026-09-10T12:59:00Z")
    validate_error(
        api_client.activate_coverage_shift(vet["id"], GROUNDS),
        "ERR_COVERAGE_CHECKIN_TOO_EARLY",
        409,
    )
    too_early, _meta = _shift_row(show_id, vet["id"])
    assert too_early["status"] == "SCHEDULED"
    assert too_early["version"] == 1

    set_clock("2026-09-10T13:00:00Z")
    activated = validate_success(api_client.activate_coverage_shift(vet["id"], GROUNDS))
    assert activated["status"] == "ACTIVE"
    assert activated["version"] == 2

    validate_error(
        api_client.activate_coverage_shift(vet["id"], GROUNDS),
        "ERR_COVERAGE_SHIFT_NOT_SCHEDULED",
        409,
    )

    filtered, meta = _shift_row(
        show_id, vet["id"], coverage_type="VETERINARIAN", status="ACTIVE"
    )
    assert meta["total_count"] == 1
    assert filtered["version"] == 2

    still_scheduled, farrier_meta = _shift_row(
        show_id, farrier["id"], coverage_type="FARRIER", status="SCHEDULED"
    )
    assert farrier_meta["total_count"] == 1
    assert still_scheduled["version"] == 1


def test_calling_the_class_walks_its_gate_ladder_in_the_declared_order():
    """One sweep across the readiness ladder, each rung failing on its own error while the rungs
    above it are satisfied. An unsafe surface refuses the call; a held ring refuses earlier still,
    with the posture error rather than the footing error, even though its surface is also unsafe —
    which is only visible because the ring gate is declared ahead of the footing gate. With the
    surface sound the missing veterinary window bites, then the officials matrix bites twice: once
    with no chair filled and once with only the judge carded, since a LOCAL show wants a steward
    too. The complete card finally starts the class, and the started occupancy cannot be called a
    second time.

    PRD §3.7: "Only an occupancy whose `status` is `SCHEDULED` may be called, and only one whose `slot_type` is `CLASS`; a maintenance occupancy or an occupancy in any other status is refused with `ERR_SLOT_NOT_SCHEDULED`."
    PRD §3.7: "The ring's `status` must be `AVAILABLE`, otherwise `ERR_RING_NOT_AVAILABLE`."
    PRD §3.7: "The ring's `footing_condition_score` must be at least 60, otherwise `ERR_FOOTING_UNSAFE` — the same threshold that decides whether a footing pass puts the ring on hold, checked again here because a hold can be lifted while the surface is still marginal."
    PRD §3.7: "There must exist a coverage window of the same show whose `coverage_type` is `VETERINARIAN` and whose `status` is `ACTIVE`, with its `start_utc` at or before the occupancy's `start_utc` and its `end_utc` at or after the occupancy's `end_utc` — the coverage must span the whole occupancy, and a `SCHEDULED` window whose provider has not checked in does not count."
    PRD §3.7: "A `LOCAL` show requires 1 judge and 1 steward and no technical delegate."
    PRD §3.7: "A shortfall is `ERR_OFFICIALS_REQUIREMENT_UNMET`."
    PRD §3.7: "On success the occupancy moves `SCHEDULED → RUNNING` and its class moves `SCHEDULED → IN_PROGRESS`; both `version` counters increment."
    PRD §3.3: "A pass that drops an `AVAILABLE` ring's surface below 60 fires the deepest cascade in the system, because an unsafe surface pre-empts whatever was booked on it."

    Design: Corner/endpoints/slot_start_gate_sweep_rejects_unmet_conditions
    """
    ctx = build_approved_show(
        class_specs=[
            {"class_number": 101, "name": "Unsafe Footing Class"},
            {"class_number": 102, "name": "Held Ring Class"},
            {"class_number": 103, "name": "Ready Class"},
        ],
        ring_specs=[
            {"name": "Ring L", "footing_condition_score": 40},
            {"name": "Ring H"},
            {"name": "Ring A"},
        ],
    )
    ring_l, ring_h, ring_a = ctx["rings"]
    class_l, class_h, class_a = ctx["class_ids"]

    slot_l = book_slot(ring_l["id"], class_l, "2026-09-10T14:00:00Z")
    assert slot_l["duration_minutes"] == 20
    assert get_ring(ring_l["id"])["status"] == "AVAILABLE"
    validate_error(
        api_client.start_ring_slot(slot_l["id"], RING_MASTER), "ERR_FOOTING_UNSAFE", 422
    )
    assert get_slot(slot_l["id"])["status"] == "SCHEDULED"

    record_footing_maintenance(
        ring_h["id"],
        start_utc="2026-09-10T13:00:00Z",
        duration_minutes=30,
        new_footing_condition_score=50,
    )
    held = get_ring(ring_h["id"])
    assert held["status"] == "MAINTENANCE_HOLD"
    assert held["footing_condition_score"] == 50
    slot_h = book_slot(ring_h["id"], class_h, "2026-09-11T14:00:00Z")
    validate_error(
        api_client.start_ring_slot(slot_h["id"], RING_MASTER), "ERR_RING_NOT_AVAILABLE", 409
    )

    slot_a = book_slot(ring_a["id"], class_a, "2026-09-10T14:00:00Z")
    validate_error(
        api_client.start_ring_slot(slot_a["id"], RING_MASTER), "ERR_VET_COVERAGE_MISSING", 422
    )

    shift = create_coverage_shift(ctx["show_id"])
    set_clock("2026-09-10T13:30:00Z")
    assert validate_success(api_client.activate_coverage_shift(shift["id"], GROUNDS))["status"] == "ACTIVE"

    validate_error(
        api_client.start_ring_slot(slot_a["id"], RING_MASTER),
        "ERR_OFFICIALS_REQUIREMENT_UNMET",
        422,
    )

    chairs = build_judge_and_steward()
    card_official(chairs["judge_id"], slot_a["id"], "JUDGE")
    validate_error(
        api_client.start_ring_slot(slot_a["id"], RING_MASTER),
        "ERR_OFFICIALS_REQUIREMENT_UNMET",
        422,
    )

    card_official(chairs["steward_id"], slot_a["id"], "STEWARD")
    started = validate_success(api_client.start_ring_slot(slot_a["id"], RING_MASTER))
    assert started["status"] == "RUNNING"
    assert get_class(class_a)["status"] == "IN_PROGRESS"

    validate_error(
        api_client.start_ring_slot(slot_a["id"], RING_MASTER), "ERR_SLOT_NOT_SCHEDULED", 409
    )
