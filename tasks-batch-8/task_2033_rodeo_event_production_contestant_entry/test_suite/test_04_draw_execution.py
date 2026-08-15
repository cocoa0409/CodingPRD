"""The draw: OCC, go-round ordering, supersede, stock atomicity, waitlists,
and unlock wipe (PRD §2.9, §3.5)."""
from test_helpers import (
    ApiErrorId,
    assignment_for_entry,
    assignments_for_entry,
    execute_draw,
    get_animal,
    get_entry,
    get_event,
    get_success_data,
    record_timed_result,
    register_contestant,
    enter,
    setup_draw_locked,
    setup_drawn,
    setup_in_progress,
    TEST_USERS,
    transition_rodeo,
    validate_error,
    validate_success,
    verify_result,
)

ADMIN = TEST_USERS["committee_admin_headers"]
OFFICE = TEST_USERS["entry_office_headers"]


def test_draw_stale_version_rejected_redraw_supersedes(api):
    """PRD §2.9: "That request must carry `expected_rodeo_event_version`
    holding the event's `version` as the client last observed it. If the
    event's current `version` has advanced past that value, the request is
    rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.5: "Executing a draw for a go-round that was already drawn — and
    still has no verified results — supersedes the earlier draw: that
    go-round's prior `PENDING` assignments are released, their animals freed
    back to `AVAILABLE`, and its waitlisted entries returned to `ENTERED`, all
    before the new draw is built."

    Design: Corner/complexity_layers/draw_execute_stale_version_rejected
    """
    sc = setup_draw_locked(
        event_code="BARREL_RACING", num_contestants=1, animal_tags=(),
        event_overrides={"per_performance_slots": 5},
        card_prefix="PRCA-497",
    )
    event = sc["event"]
    observed_version = event["version"]

    first = validate_success(
        api.execute_draw(
            event["id"],
            {"go_round_number": 1, "expected_rodeo_event_version": observed_version},
            ADMIN,
        ),
        200,
    )
    assert first["assigned_count"] == 1
    after_first = get_event(event["id"])
    assert after_first["version"] == observed_version + 1, (
        "a successful draw increments the event's version (PRD §3.5)"
    )

    # Replaying the pre-draw observation is stale.
    stale = api.execute_draw(
        event["id"],
        {"go_round_number": 1, "expected_rodeo_event_version": observed_version},
        ADMIN,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

    # A re-draw carrying the current version supersedes the earlier draw.
    second = validate_success(
        api.execute_draw(
            event["id"],
            {"go_round_number": 1,
             "expected_rodeo_event_version": after_first["version"]},
            ADMIN,
        ),
        200,
    )
    assert second["assigned_count"] == 1
    pending = get_success_data(
        api.list_draw_assignments(
            ADMIN, params={"rodeo_event_id": event["id"], "status": "PENDING"}
        ),
        200,
    )
    assert len(pending) == 1, (
        f"supersede must leave exactly one PENDING assignment, got {len(pending)}"
    )


def test_draw_go_round_order_enforced(api):
    """PRD §3.5: "Two parameter rules guard the go-round itself, evaluated
    before the version check: `go_round_number` must lie between 1 and the
    event's `go_rounds` inclusive, and go-round G may be drawn only after
    go-round G−1 already appears in `drawn_rounds` — violations of either are
    rejected with `ERR_GO_ROUND_INVALID`."

    Design: Corner/validations/draw_go_round_order_enforced
    """
    sc = setup_draw_locked(
        event_code="BARREL_RACING", num_contestants=0, animal_tags=(),
        event_overrides={"go_rounds": 2, "per_performance_slots": 5},
    )
    event = sc["event"]

    resp = api.execute_draw(
        event["id"],
        {"go_round_number": 2, "expected_rodeo_event_version": event["version"]},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_GO_ROUND_INVALID)

    after = get_event(event["id"])
    assert after["drawn_rounds"] == [], (
        f"a rejected draw must not record the go-round: {after['drawn_rounds']}"
    )


def test_redraw_blocked_after_verified_results(api):
    """PRD §3.5: "Separately, re-drawing a go-round that already has verified
    results is rejected with `ERR_RESULTS_EXIST`."

    Design: Corner/validations/redraw_blocked_after_verified_results
    """
    sc = setup_in_progress(
        event_code="BARREL_RACING", num_contestants=1, animal_tags=(),
        event_overrides={"per_performance_slots": 5},
        judge_position="TIMER", card_prefix="PRCA-460",
    )
    entry = sc["entries"][0]
    da = assignment_for_entry(entry["id"])
    result = record_timed_result(da["id"], sc["judge"]["id"], 14250)
    verify_result(result["id"])

    # Even with the current version (OCC satisfied), the re-draw is blocked.
    current = get_event(sc["event"]["id"])
    resp = api.execute_draw(
        sc["event"]["id"],
        {"go_round_number": 1,
         "expected_rodeo_event_version": current["version"]},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_RESULTS_EXIST)


def test_insufficient_stock_atomic_reject(api):
    """PRD §3.5: "If the eligible pool cannot cover every assigned entry, the
    entire draw is rejected with `ERR_INSUFFICIENT_STOCK` — draws are atomic
    and never partial."

    Design: Corner/validations/insufficient_stock_atomic_reject
    """
    sc = setup_draw_locked(
        event_code="BULL_RIDING", num_contestants=2, animal_tags=("A100",),
        card_prefix="PRCA-470",
    )
    event = sc["event"]

    resp = api.execute_draw(
        event["id"],
        {"go_round_number": 1, "expected_rodeo_event_version": event["version"]},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_STOCK)

    # Atomicity: nothing persists.
    after = get_event(event["id"])
    assert after["drawn_rounds"] == []
    assignments = get_success_data(
        api.list_draw_assignments(ADMIN, params={"rodeo_event_id": event["id"]}),
        200,
    )
    assert assignments == [], f"no assignment may persist: {assignments}"
    for entry in sc["entries"]:
        assert get_entry(entry["id"])["status"] == "ENTERED"
    assert get_animal(sc["animals"][0]["id"])["status"] == "AVAILABLE"


def test_draw_overflow_waitlists_excess_entries(api):
    """PRD §3.5: "The draw takes the event's `ENTERED` entries, ordered by
    entry `created_at` ascending with ties broken by the contestant's
    `card_number` ascending, and slots them round-robin into the rodeo's
    `SCHEDULED` performances taken in `starts_at` ascending order, never
    exceeding `per_performance_slots` in any one performance." and "Entries
    for which no performance slot is free in the first go-round overflow to
    `WAITLISTED`. A successful draw reports `assigned_count`,
    `waitlisted_count`, and the `go_round_number`, records the go-round in
    `drawn_rounds`, and increments the event's `version`."

    Design: Corner/state_machines/draw_overflow_waitlists_excess_entries
    """
    sc = setup_draw_locked(
        event_code="BARREL_RACING", num_contestants=2, animal_tags=(),
        event_overrides={"per_performance_slots": 1},
        card_prefix="PRCA-50",
    )
    e_first, e_second = sc["entries"]

    draw = execute_draw(sc["event"]["id"], go_round_number=1)
    assert draw["assigned_count"] == 1
    assert draw["waitlisted_count"] == 1
    assert draw["go_round_number"] == 1

    # The earlier-created entry (created_at ASC; card_number ASC on ties)
    # takes the single slot.
    assert get_entry(e_first["id"])["status"] == "DRAWN"
    assert get_entry(e_second["id"])["status"] == "WAITLISTED"
    assert assignments_for_entry(e_second["id"]) == [], (
        "a waitlisted entry holds no draw assignment"
    )


def test_unlock_draw_wipes_pending_assignments(api):
    """PRD §3.5: "Unlocking the draw (`UNLOCK_DRAW`, moving `DRAW_LOCKED` →
    `ENTRIES_OPEN`) wipes the draw rodeo-wide: every `PENDING` assignment of
    the rodeo's events is released with the drawn animals returned to
    `AVAILABLE`, `WAITLISTED` entries and `DRAWN` entries alike revert to
    `ENTERED`, and `drawn_rounds` is cleared on every event of the rodeo — so
    a later lock and draw rebuilds everything from scratch."

    Design: Corner/state_machines/unlock_draw_wipes_pending_assignments
    """
    sc = setup_drawn(
        event_code="BULL_RIDING", num_contestants=2,
        animal_tags=("A100", "A200"), card_prefix="PRCA-23",
    )
    transition_rodeo(sc["rodeo"]["id"], "UNLOCK_DRAW")

    assignments = get_success_data(
        api.list_draw_assignments(
            ADMIN, params={"rodeo_event_id": sc["event"]["id"]}
        ),
        200,
    )
    assert len(assignments) == 2
    for da in assignments:
        assert da["status"] == "RELEASED", f"assignment must be RELEASED: {da}"

    event = get_event(sc["event"]["id"])
    assert event["drawn_rounds"] == []

    rodeo = get_success_data(api.get_rodeo(sc["rodeo"]["id"], ADMIN), 200)
    assert rodeo["posture"] == "ENTRIES_OPEN"

    for entry in sc["entries"]:
        assert get_entry(entry["id"])["status"] == "ENTERED"
    for animal in sc["animals"]:
        assert get_animal(animal["id"])["status"] == "AVAILABLE"
