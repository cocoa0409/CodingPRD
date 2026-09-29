"""Consistency model: one write settles every dependent read inside the same request.

The world is assembled through the published endpoints against an empty database
with the logical clock parked at 2026-08-01T00:00:00Z (PRD §2.5).
"""
from test_helpers import (
    AQUARIST_HEADERS,
    assertions,
    reading_for,
    validate_paginated,
    validate_success,
)


def test_a_single_critical_reading_is_immediately_visible_on_every_dependent_read(api, build):
    """One CRITICAL sample settles the plant, both exhibits, every session and every list projection.

    PRD §2.4: "A single request may therefore increment the `version` of many resources at once, and the response already reflects every such change — the system is immediately consistent, and no cascade is deferred to a background pass."
    PRD §3.1: "When a reading drives a plant into `CRITICAL`, five things happen in order: the reading is scored and stored; the plant's band, counters and `water_quality_index` are updated; every exhibit the plant serves recomputes its posture and lands on `CLOSED` with `last_posture_reason` set to `LSS_CRITICAL`; every interaction session on each of those exhibits whose `status` is `SCHEDULED` or `ACTIVE` moves to `SUSPENDED` with `suspension_reason` set to `EXHIBIT_CLOSED`, processed in ascending `created_at` order, each incrementing the exhibit's `suspended_session_count`; and any exhibit whose `suspended_session_count` has thereby reached 2 has `interaction_program_enabled` set to false."

    Design: Corner/consistency_model/consistency_a_single_reading_is_immediately_visible_on_every_dependent_read
    """
    plant = build.create_plant(design_habitat="COLD_MARINE", redundancy_test_interval_days=90)
    first_exhibit = build.create_exhibit(
        plant,
        exhibit_code="EX-COLD-1",
        name="Cold Water Reef",
        bioload_capacity_units=100.0,
        interaction_program_enabled=True,
    )
    second_exhibit = build.create_exhibit(
        plant,
        exhibit_code="EX-COLD-2",
        name="Kelp Forest",
        bioload_capacity_units=100.0,
        interaction_program_enabled=True,
    )
    # A clean sample first, so the plant is NORMAL and both exhibits are bookable.
    build.append_graded_reading(plant, "NORMAL")
    # Two bookings on the first exhibit, separated by exactly the 30-minute
    # turnover buffer, and one on the second.
    early_session = build.book_session(
        first_exhibit["id"],
        "2026-08-02T10:00:00Z",
        "2026-08-02T11:00:00Z",
        max_guests=6,
        guest_count=4,
        safety_briefing_confirmed=True,
    )
    later_session = build.book_session(
        first_exhibit["id"],
        "2026-08-02T11:30:00Z",
        "2026-08-02T12:30:00Z",
        max_guests=6,
        guest_count=4,
        safety_briefing_confirmed=True,
    )
    second_exhibit_session = build.book_session(
        second_exhibit["id"],
        "2026-08-02T10:00:00Z",
        "2026-08-02T11:00:00Z",
        max_guests=6,
        guest_count=4,
        safety_briefing_confirmed=True,
    )

    # The single write: a sample whose largest deviation ratio is exactly 2.0.
    response = api.create_water_quality_reading(
        plant["id"], reading_for("COLD_MARINE", "CRITICAL", build.now), AQUARIST_HEADERS
    )

    reading = validate_success(response, 201)
    assert reading["severity"] == "CRITICAL"

    # The very next read already shows the plant in its new band, speaking with
    # the snapshot of the sample just recorded (PRD §3.1).
    read_plant = validate_success(api.get_life_support_system(plant["id"], AQUARIST_HEADERS))
    assertions.assert_alarm(read_plant, "CRITICAL")
    assertions.assert_scaled_equal(
        read_plant["water_quality_index"], reading["water_quality_index_snapshot"]
    )

    # Both served exhibits have already re-derived their posture.
    read_first = validate_success(api.get_exhibit(first_exhibit["id"], AQUARIST_HEADERS))
    assertions.assert_posture(read_first, "CLOSED", "LSS_CRITICAL")
    # Two suspensions on this exhibit, which is exactly the auto-disable threshold.
    assert read_first["suspended_session_count"] == 2
    assert read_first["interaction_program_enabled"] is False

    read_second = validate_success(api.get_exhibit(second_exhibit["id"], AQUARIST_HEADERS))
    assertions.assert_posture(read_second, "CLOSED", "LSS_CRITICAL")
    # One suspension only, so the programme is still enabled here.
    assert read_second["suspended_session_count"] == 1
    assert read_second["interaction_program_enabled"] is True

    # The list projections do not lag behind the single write either.
    closed_rows, closed_meta = validate_paginated(
        api.list_exhibits(AQUARIST_HEADERS, params={"posture": "CLOSED", "limit": 10})
    )
    assert closed_meta["total_count"] == 2
    assert {row["id"] for row in closed_rows} == {first_exhibit["id"], second_exhibit["id"]}

    suspended_rows, suspended_meta = validate_paginated(
        api.list_exhibit_interaction_sessions(
            first_exhibit["id"], AQUARIST_HEADERS, params={"status": "SUSPENDED", "limit": 10}
        )
    )
    assert suspended_meta["total_count"] == 2
    # Sessions are processed, and listed, in ascending creation order (PRD §2.3).
    assert [row["id"] for row in suspended_rows] == [early_session["id"], later_session["id"]]
    assert [row["suspension_reason"] for row in suspended_rows] == [
        "EXHIBIT_CLOSED",
        "EXHIBIT_CLOSED",
    ]

    # The session on the other exhibit is suspended by the same request.
    read_other = validate_success(
        api.get_interaction_session(second_exhibit_session["id"], AQUARIST_HEADERS)
    )
    assertions.assert_interaction_session(read_other)
    assert read_other["status"] == "SUSPENDED"
    assert read_other["suspension_reason"] == "EXHIBIT_CLOSED"
