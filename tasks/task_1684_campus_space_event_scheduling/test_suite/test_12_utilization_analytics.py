"""Utilization analytics: the scheduled/realized dual variants, outage
denominator handling, and the zero-denominator null rule."""

from test_helpers import (
    FACILITIES_MANAGER,
    SCHEDULER,
    approve_event,
    check_in_event,
    confirm_event,
    create_event,
    create_room,
    daily_close,
    get_event,
    set_clock,
    setup_org_room,
    validate_success,
)

DAY_START = "2026-09-10T00:00:00Z"
DAY_END = "2026-09-11T00:00:00Z"


class TestScheduledVsRealizedVariants:
    def test_approved_event_counts_in_scheduled_but_not_realized(self, api):
        """PRD §3.2: "The scheduled variant counts events in `APPROVED`,
        `CONFIRMED`, `IN_PROGRESS`, or `COMPLETED`; the realized variant counts
        `COMPLETED` events only."
        PRD §3.2: "Each utilization figure is ten thousand times the booked
        minutes divided by the denominator minutes, rounded half-up to a whole
        basis point."

        Design: Difficulty/dual_variant_calc/utilization_scheduled_counts_approved_but_realized_excludes
        """
        scn = setup_org_room(
            room_overrides={"name": "PHY-201", "building_code": "PHY", "capacity": 80}
        )
        event = create_event(
            scn.org, scn.room["id"], title="Seminar", expected_attendance=40,
            start_at="2026-09-10T16:00:00Z", end_at="2026-09-10T18:30:00Z",
            setup_minutes=30, teardown_minutes=30,
        )
        approve_event(event["id"])

        data = validate_success(
            api.get_room_utilization(
                scn.room["id"], SCHEDULER,
                params={"window_start": DAY_START, "window_end": DAY_END},
            ),
            200,
        )
        assert data["window_minutes"] == 1440
        assert data["outage_minutes"] == 0
        # Booked interval [15:30, 19:00) = 210 minutes (buffer never counted).
        assert data["scheduled_minutes"] == 210
        assert data["scheduled_utilization_bps"] == 1458, (
            "round_half_up(10000 * 210 / 1440)"
        )
        assert data["realized_minutes"] == 0
        assert data["realized_utilization_bps"] == 0, "nothing COMPLETED yet"

    def test_variants_converge_once_the_event_completes(self, api):
        """PRD §3.2: "The scheduled variant counts events in `APPROVED`,
        `CONFIRMED`, `IN_PROGRESS`, or `COMPLETED`; the realized variant counts
        `COMPLETED` events only."
        PRD §3.2: "Each contributing event books the interval from
        `setup_minutes` before its `start_at` to `teardown_minutes` after its
        `end_at` — the turnaround buffer is never counted — clamped to the
        window."

        Design: Difficulty/dual_variant_calc/utilization_scheduled_counts_approved_but_realized_excludes
        """
        scn = setup_org_room(
            room_overrides={"name": "PHY-201", "building_code": "PHY", "capacity": 80}
        )
        event = create_event(
            scn.org, scn.room["id"], title="Seminar", expected_attendance=40,
            start_at="2026-09-10T16:00:00Z", end_at="2026-09-10T18:30:00Z",
            setup_minutes=30, teardown_minutes=30,
        )
        approve_event(event["id"])
        confirm_event(event["id"], scn.org)

        # Check-in window for a 16:00 start is [15:30, 16:15].
        set_clock("2026-09-10T15:45:00Z")
        check_in_event(event["id"], scn.org)
        set_clock("2026-09-10T20:00:00Z")
        daily_close()

        data = validate_success(
            api.get_room_utilization(
                scn.room["id"], SCHEDULER,
                params={"window_start": DAY_START, "window_end": DAY_END},
            ),
            200,
        )
        assert data["realized_minutes"] == 210
        assert data["realized_utilization_bps"] == 1458, "variants converge"
        assert data["scheduled_utilization_bps"] == 1458


def test_full_day_outage_makes_both_bps_null(api):
    """PRD §3.2: "When the denominator is zero or negative, both basis-point
    fields are null while the minute fields are still reported."

    Design: Corner/calculations/utilization_full_outage_window_null_rate
    """
    room = create_room(name="OUT-9", building_code="OUT", capacity=10)
    validate_success(
        api.room_out_of_service(
            room["id"],
            {
                "outage_start_at": "2026-09-20T00:00:00Z",
                "outage_end_at": "2026-09-21T00:00:00Z",
            },
            FACILITIES_MANAGER,
        ),
        200,
    )
    data = validate_success(
        api.get_room_utilization(
            room["id"], SCHEDULER,
            params={
                "window_start": "2026-09-20T00:00:00Z",
                "window_end": "2026-09-21T00:00:00Z",
            },
        ),
        200,
    )
    assert data["window_minutes"] == 1440
    assert data["outage_minutes"] == 1440
    assert data["scheduled_minutes"] == 0
    assert data["realized_minutes"] == 0
    assert data["scheduled_utilization_bps"] is None
    assert data["realized_utilization_bps"] is None


def test_outage_overlapping_window_shrinks_the_denominator(api):
    """PRD §3.2: "The denominator is the window's length in minutes minus the
    minutes of the room's outage windows overlapping the window, themselves
    merged."
    PRD §3.2: "Overlapping booked intervals are merged before summing so nothing
    is double counted."

    Design: Corner/calculations/utilization_outage_shrinks_denominator
    """
    scn = setup_org_room(
        room_overrides={"name": "UTI-1", "building_code": "UTI", "capacity": 80}
    )
    event = create_event(
        scn.org, scn.room["id"], title="E", expected_attendance=40,
        start_at="2026-09-10T16:00:00Z", end_at="2026-09-10T18:30:00Z",
        setup_minutes=30, teardown_minutes=30,
    )
    approve_event(event["id"])

    # A two-hour morning outage that never touches the event's occupancy.
    validate_success(
        api.room_out_of_service(
            scn.room["id"],
            {
                "outage_start_at": "2026-09-10T08:00:00Z",
                "outage_end_at": "2026-09-10T10:00:00Z",
            },
            FACILITIES_MANAGER,
        ),
        200,
    )

    assert get_event(event["id"])["status"] == "APPROVED", (
        "the outage does not overlap the event, so no bump"
    )

    data = validate_success(
        api.get_room_utilization(
            scn.room["id"], SCHEDULER,
            params={"window_start": DAY_START, "window_end": DAY_END},
        ),
        200,
    )
    assert data["outage_minutes"] == 120
    assert data["scheduled_minutes"] == 210
    assert data["scheduled_utilization_bps"] == 1591, (
        "round_half_up(10000 * 210 / 1320)"
    )
