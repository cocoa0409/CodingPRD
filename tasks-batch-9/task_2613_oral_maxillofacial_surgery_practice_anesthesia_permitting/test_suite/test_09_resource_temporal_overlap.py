"""Three resources with three different interval conventions: the padded room, the
unpadded monitor, and the shifted recovery-bay pool."""
import pytest

from test_helpers import (
    SCHEDULER,
    api_client,
    clear_case,
    confirm_case,
    create_block,
    create_case,
    create_patient,
    create_staff,
    draft_case,
    fetch_block,
    fetch_case,
    hold_case_on_block,
    setup_permitted_practice,
    setup_practice_with_roster,
    validate_error,
)

CLOCK = "2026-09-11T10:00:00Z"

# --- operating_room_turnover_buffer_overlap ------------------------------------


def _one_room_with_an_incumbent_case():
    """A 240-minute OR-1 block whose first hour is already committed."""
    env = setup_practice_with_roster(clock=CLOCK, turnover_buffer_minutes=15)
    block = create_block(
        env["practice_id"], env["surgeon"]["id"],
        "2026-09-14T13:00:00Z", "2026-09-14T17:00:00Z", room_code="OR-1",
    )
    incumbent = draft_case(
        env,
        planned_anesthesia_level="LOCAL_ONLY",
        planned_start="2026-09-14T13:00:00Z",
        planned_end="2026-09-14T14:00:00Z",
        with_monitor=False,
    )
    hold_case_on_block(incumbent["id"], block["id"])
    return env, block, incumbent


def test_a_gap_shorter_than_the_turnover_buffer_collides(api):
    """PRD 3.4: "No other case of the same practice in the same `room_code` whose
    `scheduling_status` is `BLOCK_HELD`, `CONFIRMED`, `IN_RECOVERY`, or `COMPLETED` may
    overlap this case's window once the buffer is appended — and the buffer is appended
    to the incumbent case's window *and* to the candidate's, so the effective comparison
    is between the interval from each case's `planned_start` up to its `planned_end` plus
    `turnover_buffer_minutes`."

    Design: Difficulty/resource_temporal_overlap/operating_room_turnover_buffer_overlap
    """
    env, block, incumbent = _one_room_with_an_incumbent_case()
    candidate = draft_case(
        env,
        planned_anesthesia_level="LOCAL_ONLY",
        planned_start="2026-09-14T14:05:00Z",
        planned_end="2026-09-14T15:00:00Z",
        with_monitor=False,
    )

    response = api_client.hold_block(
        candidate["id"], {"block_id": block["id"]}, SCHEDULER
    )
    validate_error(response, "ERR_ROOM_TURNOVER_CONFLICT", 409)

    refused = fetch_case(candidate["id"])
    assert refused["scheduling_status"] == "DRAFT"
    assert refused["block_id"] is None
    assert fetch_block(block["id"])["committed_minutes"] == 60


def test_a_gap_exactly_equal_to_the_buffer_is_admitted(api):
    """PRD 3.4: "The consequence is that a gap shorter than the buffer is a conflict
    while a gap exactly equal to the buffer is not: with the default 15-minute buffer, a
    new case starting 15 minutes after an incumbent ends is admitted, and one starting 14
    minutes after is refused with `ERR_ROOM_TURNOVER_CONFLICT` (HTTP 409)."
    PRD 3.3: "The invariant that holds after every write is that `committed_minutes`,
    `released_minutes`, and `open_minutes` sum to exactly `block_duration_minutes`; a
    two-hundred-minute block carrying ninety committed minutes therefore reports a
    utilization of 45.00 with 110 minutes still open."

    Design: Difficulty/resource_temporal_overlap/operating_room_turnover_buffer_overlap
    """
    env, block, incumbent = _one_room_with_an_incumbent_case()
    candidate = draft_case(
        env,
        planned_anesthesia_level="LOCAL_ONLY",
        planned_start="2026-09-14T14:15:00Z",
        planned_end="2026-09-14T15:15:00Z",
        with_monitor=False,
    )

    held = hold_case_on_block(candidate["id"], block["id"])
    assert held["scheduling_status"] == "BLOCK_HELD"

    ledger = fetch_block(block["id"])
    assert ledger["committed_minutes"] == 120
    assert ledger["released_minutes"] == 0
    assert ledger["open_minutes"] == 120
    assert float(ledger["utilization_pct"]) == pytest.approx(50.00, abs=0.001)


# --- monitor_half_open_overlap_without_buffer ----------------------------------


def _shared_monitor_practice():
    """One MINIMAL_SEDATION practice, two surgeons, three rooms and exactly one
    monitor shared by every case."""
    env = setup_permitted_practice("MINIMAL_SEDATION", clock=CLOCK)
    env["surgeon_two"] = create_staff(
        env["practice_id"], "SURGEON", full_name="Dr Second Chair",
        acls_expires_on="2027-06-30T00:00:00Z",
    )
    env["block_one"] = create_block(
        env["practice_id"], env["surgeon"]["id"],
        "2026-09-14T13:00:00Z", "2026-09-14T17:00:00Z", room_code="OR-1",
    )
    env["block_two"] = create_block(
        env["practice_id"], env["surgeon_two"]["id"],
        "2026-09-14T13:00:00Z", "2026-09-14T17:00:00Z", room_code="OR-2",
    )
    env["block_three"] = create_block(
        env["practice_id"], env["surgeon_two"]["id"],
        "2026-09-14T13:00:00Z", "2026-09-14T17:00:00Z", room_code="OR-3",
    )
    return env


def _second_surgeon_case(env, planned_start, planned_end):
    patient = create_patient(env["practice_id"])
    return create_case(
        env["practice_id"], patient["id"], env["surgeon_two"]["id"],
        planned_start, planned_end,
        planned_anesthesia_level="MINIMAL_SEDATION",
        monitor_staff_id=env["monitor"]["id"],
    )


def test_one_monitor_may_hand_off_at_the_very_instant_a_case_ends(api):
    """PRD 3.4: "Tenth, the monitor must not be double-booked: the `monitor_staff_id`
    may not already be assigned to another case in `BLOCK_HELD`, `CONFIRMED`, or
    `IN_RECOVERY` whose half-open window from `planned_start` to `planned_end` overlaps
    this case's. No turnover buffer applies to people — a monitor may finish one case and
    begin another at the same instant — so back-to-back monitoring is legal while any true
    overlap is refused with `ERR_MONITOR_DOUBLE_BOOKED` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/monitor_half_open_overlap_without_buffer
    """
    env = _shared_monitor_practice()
    first = draft_case(
        env,
        planned_anesthesia_level="MINIMAL_SEDATION",
        planned_start="2026-09-14T13:00:00Z",
        planned_end="2026-09-14T14:00:00Z",
    )
    hold_case_on_block(first["id"], env["block_one"]["id"])
    second = _second_surgeon_case(env, "2026-09-14T14:00:00Z", "2026-09-14T15:00:00Z")
    hold_case_on_block(second["id"], env["block_two"]["id"])

    first_evaluation = clear_case(env, first["id"])
    clear_case(env, second["id"])

    assert confirm_case(first["id"], env["block_one"]["id"])["scheduling_status"] == "CONFIRMED"
    assert confirm_case(second["id"], env["block_two"]["id"])["scheduling_status"] == "CONFIRMED"

    assert float(first_evaluation["final_risk_score"]) == pytest.approx(16.0, abs=0.001)
    assert first_evaluation["risk_band"] == "LOW"


def test_a_straddling_third_case_double_books_the_only_monitor(api):
    """PRD 3.4: "No turnover buffer applies to people — a monitor may finish one case and
    begin another at the same instant — so back-to-back monitoring is legal while any true
    overlap is refused with `ERR_MONITOR_DOUBLE_BOOKED` (HTTP 409)."
    PRD 3.4: "the minutes themselves were already committed at hold time and do not move
    again, so `committed_minutes` and `open_minutes` are unchanged by confirmation."

    Design: Difficulty/resource_temporal_overlap/monitor_half_open_overlap_without_buffer
    """
    env = _shared_monitor_practice()
    first = draft_case(
        env,
        planned_anesthesia_level="MINIMAL_SEDATION",
        planned_start="2026-09-14T13:00:00Z",
        planned_end="2026-09-14T14:00:00Z",
    )
    hold_case_on_block(first["id"], env["block_one"]["id"])
    second = _second_surgeon_case(env, "2026-09-14T14:00:00Z", "2026-09-14T15:00:00Z")
    hold_case_on_block(second["id"], env["block_two"]["id"])
    clear_case(env, first["id"])
    clear_case(env, second["id"])
    confirm_case(first["id"], env["block_one"]["id"])
    confirm_case(second["id"], env["block_two"]["id"])

    third = _second_surgeon_case(env, "2026-09-14T13:30:00Z", "2026-09-14T14:30:00Z")
    hold_case_on_block(third["id"], env["block_three"]["id"])
    clear_case(env, third["id"])

    block = fetch_block(env["block_three"]["id"])
    response = api_client.confirm_case(
        third["id"], {"expected_block_version": block["version"]}, SCHEDULER
    )
    validate_error(response, "ERR_MONITOR_DOUBLE_BOOKED", 409)

    assert fetch_case(third["id"])["scheduling_status"] == "BLOCK_HELD"
    for block_key in ("block_one", "block_two", "block_three"):
        assert fetch_block(env[block_key]["id"])["committed_minutes"] == 60


# --- recovery_bay_pool_postop_window_capacity ----------------------------------


def _single_bay_practice():
    """A one-bay MODERATE_SEDATION office with a private room and a private
    certified monitor for every case, so the room and monitor gates never fire."""
    env = setup_permitted_practice("MODERATE_SEDATION", clock=CLOCK, recovery_bay_count=1)
    env["surgeon_two"] = create_staff(
        env["practice_id"], "SURGEON", full_name="Dr Second Chair",
        acls_expires_on="2027-06-30T00:00:00Z",
    )
    env["monitors"] = [
        create_staff(
            env["practice_id"], "ANESTHESIA_MONITOR", full_name=f"Monitor {index}",
            monitoring_certified=True, acls_expires_on="2027-06-30T00:00:00Z",
        )
        for index in range(1, 4)
    ]
    return env


def _bay_case(env, index, planned_start, planned_end):
    """Hold and clear one MODERATE_SEDATION case in its own room."""
    surgeon_id = env["surgeon"]["id"] if index == 0 else env["surgeon_two"]["id"]
    block = create_block(
        env["practice_id"], surgeon_id,
        "2026-09-14T13:00:00Z", "2026-09-14T17:00:00Z", room_code=f"OR-{index + 1}",
    )
    patient = create_patient(env["practice_id"])
    case = create_case(
        env["practice_id"], patient["id"], surgeon_id, planned_start, planned_end,
        planned_anesthesia_level="MODERATE_SEDATION",
        monitor_staff_id=env["monitors"][index]["id"],
    )
    hold_case_on_block(case["id"], block["id"])
    clear_case(env, case["id"])
    return case, block


def test_a_second_recovery_inside_the_first_window_exceeds_one_bay(api):
    """PRD 3.4: "A case occupies a bay over the half-open interval that begins at its
    `planned_end` and runs for `recovery_minutes_required` minutes; a `LOCAL_ONLY` case,
    whose `recovery_minutes_required` is zero, never occupies a bay and never triggers this
    test."
    PRD 3.4: "If the case requires recovery time at all and that peak exceeds the
    practice's `recovery_bay_count`, the confirmation is refused with
    `ERR_RECOVERY_CAPACITY_EXCEEDED` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/recovery_bay_pool_postop_window_capacity
    """
    env = _single_bay_practice()
    first, first_block = _bay_case(env, 0, "2026-09-14T13:00:00Z", "2026-09-14T14:00:00Z")
    second, second_block = _bay_case(env, 1, "2026-09-14T13:30:00Z", "2026-09-14T14:30:00Z")

    assert confirm_case(first["id"], first_block["id"])["scheduling_status"] == "CONFIRMED"

    before = fetch_block(second_block["id"])
    response = api_client.confirm_case(
        second["id"], {"expected_block_version": before["version"]}, SCHEDULER
    )
    validate_error(response, "ERR_RECOVERY_CAPACITY_EXCEEDED", 409)

    assert fetch_case(second["id"])["scheduling_status"] == "BLOCK_HELD"
    assert fetch_block(second_block["id"])["version"] == before["version"]


def test_a_recovery_starting_where_the_incumbent_ends_fits_one_bay(api):
    """PRD 3.4: "Because the intervals are half-open, a recovery that ends exactly when
    another begins is not an overlap."
    PRD 3.4: "A confirmation that survives all eleven gates advances the case's
    `scheduling_status` from `BLOCK_HELD` to `CONFIRMED` and increments the case's
    `version`."

    Design: Difficulty/resource_temporal_overlap/recovery_bay_pool_postop_window_capacity
    """
    env = _single_bay_practice()
    first, first_block = _bay_case(env, 0, "2026-09-14T13:00:00Z", "2026-09-14T14:00:00Z")
    third, third_block = _bay_case(env, 2, "2026-09-14T13:45:00Z", "2026-09-14T14:45:00Z")

    confirm_case(first["id"], first_block["id"])

    confirmed = confirm_case(third["id"], third_block["id"])
    assert confirmed["scheduling_status"] == "CONFIRMED"
    assert confirmed["recovery_minutes_required"] == 45
    assert confirmed["version"] > third["version"]
