"""Half-open interval arithmetic on the two resources that own a timeline.

A device's meter-coverage timeline compares candidate windows against the
stored windows raw, so back-to-back readings that share an instant are both
legal.  A technician's dispatch timeline inflates each already-occupied window
by the travel buffer before the same half-open comparison runs, so windows that
look disjoint on the wire can still collide.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_fields,
    assert_meter_read,
    assert_service_ticket,
    create_ticket,
    dispatch_payload,
    dispatch_ticket,
    fetch_billing_period,
    fetch_device,
    fetch_service_ticket,
    fetch_technician,
    list_reads_for_device,
    make_fleet_ops_headers,
    meter_read_payload,
    setup_print_environment,
    submit_automated_read,
    validate_error,
    validate_success,
)

PERIOD_START = "2026-08-01T00:00:00Z"
PERIOD_END = "2026-09-01T00:00:00Z"
METER_CLOCK = "2026-08-25T00:00:00Z"

# The device's meter-coverage timeline: two back-to-back weeks that share the
# instant 2026-08-08T00:00:00Z.
FIRST_WINDOW = ("2026-08-01T00:00:00Z", "2026-08-08T00:00:00Z")
SECOND_WINDOW = ("2026-08-08T00:00:00Z", "2026-08-15T00:00:00Z")
OVERLAPPING_WINDOW = ("2026-08-14T00:00:00Z", "2026-08-20T00:00:00Z")

# The technician's dispatch timeline.  T1 carries a 30-minute travel buffer, so
# the occupied 09:00-10:00 slot is compared as 08:30-10:30.
DISPATCH_CLOCK = "2026-08-05T08:00:00Z"
OCCUPIED_WINDOW = ("2026-08-05T09:00:00Z", "2026-08-05T10:00:00Z")
INFLATED_END = "2026-08-05T10:30:00Z"

OPS = TEST_USERS["fleet_ops_headers"]


def _assert_same_instant(actual, expected, label):
    """Compare two ISO 8601 UTC instants without pinning the fractional digits."""
    assert actual is not None, f"{label} must be stamped, got None"
    assert actual[:19] == expected[:19], f"expected {label} {expected}, got {actual}"


def _meter_environment():
    """One ACTIVE mono device, an OPEN August period, clock inside the period."""
    return setup_print_environment(
        period=(PERIOD_START, PERIOD_END),
        clock=METER_CLOCK,
    )


def _two_adjacent_accepted_reads(env):
    """Accept the two back-to-back readings that touch at 2026-08-08T00:00:00Z."""
    first = submit_automated_read(
        env["device_id"],
        env["period_id"],
        mono_meter=1_000,
        toner_level_pct=90,
        coverage_start=FIRST_WINDOW[0],
        coverage_end=FIRST_WINDOW[1],
    )
    second = submit_automated_read(
        env["device_id"],
        env["period_id"],
        mono_meter=2_000,
        toner_level_pct=85,
        coverage_start=SECOND_WINDOW[0],
        coverage_end=SECOND_WINDOW[1],
    )
    return first, second


def _dispatch_environment():
    """Two ACTIVE devices at one site, one technician, three STANDARD tickets.

    The first ticket is already dispatched to that technician for
    09:00-10:00 on 2026-08-05, which is the window every candidate is compared
    against.
    """
    env = setup_print_environment(devices=2, clock=DISPATCH_CLOCK)
    first = create_ticket(env["device_ids"][0], env["site_id"], symptom_code="PAPER_JAM")
    second = create_ticket(env["device_ids"][1], env["site_id"], symptom_code="STREAKING")
    third = create_ticket(env["device_ids"][1], env["site_id"], symptom_code="NOISE")
    env["ticket_ids"] = [first["id"], second["id"], third["id"]]
    env["occupied_ticket"] = dispatch_ticket(
        first["id"], env["technician_id"], OCCUPIED_WINDOW[0], OCCUPIED_WINDOW[1]
    )
    return env


class TestMeterCoverageWindowAdjacency:
    """The device's meter-coverage timeline: touching is legal, intersecting is not."""

    def test_back_to_back_coverage_windows_sharing_an_instant_are_both_accepted(self, api):
        """Two weekly windows that meet at 2026-08-08T00:00:00Z both validate.

        PRD: "`coverage_start` is strictly earlier than `coverage_end`, and the
        reading's half-open interval does not intersect the interval of any other
        reading of the same device whose `status` is `PENDING_VALIDATION` or
        `ACCEPTED`; intervals that merely touch (one reading's `coverage_end`
        equal to the next reading's `coverage_start`) are allowed. Otherwise
        `ERR_READ_INTERVAL_OVERLAP` (409)."
        PRD: "The candidate monochrome delta is the submitted `mono_meter` less
        the device's `last_accepted_mono_meter`, and the candidate colour delta is
        the submitted `color_meter` less the device's `last_accepted_color_meter`."
        PRD: "The second hop writes the device: `last_accepted_mono_meter` and
        `last_accepted_color_meter` take the submitted absolute values,
        `last_read_at` takes the reading's `coverage_end`, `toner_level_pct` takes
        the reading's reported level, `lifetime_mono_pages` grows by `mono_delta`,
        `lifetime_color_pages` grows by `color_delta`,
        `pages_since_last_cartridge` grows by the sum of the two deltas, and the
        device's `version` increments."

        Design: Difficulty/resource_temporal_overlap/adjacent_meter_coverage_windows_allowed_overlapping_window_rejected
        """
        env = _meter_environment()

        first = validate_success(
            api.submit_automated_meter_read(
                meter_read_payload(
                    env["device_id"],
                    env["period_id"],
                    mono_meter=1_000,
                    toner_level_pct=90,
                    coverage_start=FIRST_WINDOW[0],
                    coverage_end=FIRST_WINDOW[1],
                ),
                make_fleet_ops_headers("ops-1"),
            ),
            201,
        )
        second = validate_success(
            api.submit_automated_meter_read(
                meter_read_payload(
                    env["device_id"],
                    env["period_id"],
                    mono_meter=2_000,
                    toner_level_pct=85,
                    coverage_start=SECOND_WINDOW[0],
                    coverage_end=SECOND_WINDOW[1],
                ),
                make_fleet_ops_headers("ops-1"),
            ),
            201,
        )

        assert_meter_read(first)
        assert_meter_read(second)
        assert_fields(
            first,
            status="ACCEPTED",
            exception_reason="NONE",
            mono_delta=1_000,
            color_delta=0,
        )
        assert_fields(
            second,
            status="ACCEPTED",
            exception_reason="NONE",
            mono_delta=1_000,
            color_delta=0,
        )

        reads = list_reads_for_device(env["device_id"])
        assert len(reads) == 2, f"both touching readings must persist, got {len(reads)}"

        device = fetch_device(env["device_id"])
        assert_fields(
            device,
            last_accepted_mono_meter=2_000,
            last_accepted_color_meter=0,
            lifetime_mono_pages=2_000,
            lifetime_color_pages=0,
            pages_since_last_cartridge=2_000,
            toner_level_pct=85,
        )
        _assert_same_instant(device["last_read_at"], SECOND_WINDOW[1], "last_read_at")
        assert_fields(fetch_billing_period(env["period_id"]), exception_open_count=0)

    def test_coverage_window_overlapping_an_accepted_read_is_rejected(self, api):
        """A window starting one day before the previous window ends is refused.

        PRD: "`coverage_start` is strictly earlier than `coverage_end`, and the
        reading's half-open interval does not intersect the interval of any other
        reading of the same device whose `status` is `PENDING_VALIDATION` or
        `ACCEPTED`; intervals that merely touch (one reading's `coverage_end`
        equal to the next reading's `coverage_start`) are allowed. Otherwise
        `ERR_READ_INTERVAL_OVERLAP` (409)."
        PRD: "The practical consequence is that two windows which merely touch —
        where the earlier window's upper bound equals the later window's lower
        bound — do **not** overlap and are always allowed; only genuinely
        intersecting windows are rejected."

        Design: Difficulty/resource_temporal_overlap/adjacent_meter_coverage_windows_allowed_overlapping_window_rejected
        """
        env = _meter_environment()
        _two_adjacent_accepted_reads(env)

        response = api.submit_automated_meter_read(
            meter_read_payload(
                env["device_id"],
                env["period_id"],
                mono_meter=3_000,
                toner_level_pct=80,
                coverage_start=OVERLAPPING_WINDOW[0],
                coverage_end=OVERLAPPING_WINDOW[1],
            ),
            make_fleet_ops_headers("ops-1"),
        )

        validate_error(response, ApiErrorId.ERR_READ_INTERVAL_OVERLAP)

        reads = list_reads_for_device(env["device_id"])
        assert len(reads) == 2, f"the rejected reading must not be stored, got {len(reads)}"
        assert all(read["status"] == "ACCEPTED" for read in reads), (
            f"the two stored readings stay ACCEPTED: {[r['status'] for r in reads]}"
        )

        device = fetch_device(env["device_id"])
        assert_fields(
            device,
            last_accepted_mono_meter=2_000,
            lifetime_mono_pages=2_000,
            pages_since_last_cartridge=2_000,
            toner_level_pct=85,
        )
        _assert_same_instant(device["last_read_at"], SECOND_WINDOW[1], "last_read_at")
        assert_fields(fetch_billing_period(env["period_id"]), exception_open_count=0)

    @pytest.mark.parametrize(
        "coverage_start,accepted",
        [
            pytest.param("2026-08-07T23:59:59Z", False, id="one_second_of_overlap"),
            pytest.param("2026-08-08T00:00:00Z", True, id="exactly_touching"),
            pytest.param("2026-08-08T00:00:01Z", True, id="one_second_of_clear_air"),
        ],
    )
    def test_coverage_window_boundary_is_half_open(self, api, coverage_start, accepted):
        """One second either side of the stored `coverage_end` decides the outcome.

        PRD: "Every time window in this system is **half-open**: it includes its
        lower bound and excludes its upper bound."
        PRD: "`coverage_start` is strictly earlier than `coverage_end`, and the
        reading's half-open interval does not intersect the interval of any other
        reading of the same device whose `status` is `PENDING_VALIDATION` or
        `ACCEPTED`; intervals that merely touch (one reading's `coverage_end`
        equal to the next reading's `coverage_start`) are allowed. Otherwise
        `ERR_READ_INTERVAL_OVERLAP` (409)."

        Design: Difficulty/resource_temporal_overlap/adjacent_meter_coverage_windows_allowed_overlapping_window_rejected
        """
        env = _meter_environment()
        submit_automated_read(
            env["device_id"],
            env["period_id"],
            mono_meter=1_000,
            toner_level_pct=90,
            coverage_start=FIRST_WINDOW[0],
            coverage_end=FIRST_WINDOW[1],
        )

        response = api.submit_automated_meter_read(
            meter_read_payload(
                env["device_id"],
                env["period_id"],
                mono_meter=2_000,
                toner_level_pct=85,
                coverage_start=coverage_start,
                coverage_end=SECOND_WINDOW[1],
            ),
            make_fleet_ops_headers("ops-1"),
        )

        if accepted:
            candidate = validate_success(response, 201)
            assert_fields(candidate, status="ACCEPTED", mono_delta=1_000, color_delta=0)
            assert_fields(
                fetch_device(env["device_id"]),
                last_accepted_mono_meter=2_000,
                lifetime_mono_pages=2_000,
                toner_level_pct=85,
            )
            assert len(list_reads_for_device(env["device_id"])) == 2
        else:
            validate_error(response, ApiErrorId.ERR_READ_INTERVAL_OVERLAP)
            assert_fields(
                fetch_device(env["device_id"]),
                last_accepted_mono_meter=1_000,
                lifetime_mono_pages=1_000,
                toner_level_pct=90,
            )
            assert len(list_reads_for_device(env["device_id"])) == 1


class TestTechnicianDispatchWindowBuffer:
    """The technician's timeline: every occupied window is inflated before comparison."""

    @pytest.mark.parametrize(
        "window_start,window_end",
        [
            pytest.param(
                "2026-08-05T10:20:00Z", "2026-08-05T11:00:00Z", id="ten_minutes_inside_the_buffer"
            ),
            pytest.param(
                "2026-08-05T10:29:00Z", "2026-08-05T11:29:00Z", id="one_minute_inside_the_buffer"
            ),
        ],
    )
    def test_dispatch_window_inside_the_inflated_travel_buffer_is_rejected(
        self, api, window_start, window_end
    ):
        """A raw-disjoint window still collides once the 30-minute buffer is added.

        PRD: "`window_start` is strictly earlier than `window_end`, `window_start`
        is at or after the logical clock, and the requested window does not
        intersect any window already occupied by the same technician after each
        occupied window is inflated by that technician's `travel_buffer_minutes`
        on both sides. Otherwise `ERR_DISPATCH_WINDOW_CONFLICT` (409)."
        PRD: "The new ticket has `status` `OPEN`, a null `assigned_technician_id`,
        a null `window_start` and `window_end` until a dispatch reserves them, a
        null `hold_started_at` and `responded_at`, a `parts_hold_hours`,
        `hours_late`, `labor_hours`, `labor_cents` and `sla_credit_cents` of 0,
        `opened_at` stamped from the logical clock, and — this is the
        response-time commitment made concrete — a `respond_by` deadline computed
        as `opened_at` plus the contract's `response_sla_hours_critical` hours when
        `severity` is `CRITICAL`, or plus the contract's
        `response_sla_hours_standard` hours when `severity` is `STANDARD`."

        Design: Difficulty/resource_temporal_overlap/technician_dispatch_windows_conflict_after_travel_buffer_inflation
        """
        env = _dispatch_environment()
        candidate_ticket_id = env["ticket_ids"][1]

        response = api.dispatch_service_ticket(
            candidate_ticket_id,
            dispatch_payload(env["technician_id"], window_start, window_end),
            OPS,
        )

        validate_error(response, ApiErrorId.ERR_DISPATCH_WINDOW_CONFLICT)

        ticket = fetch_service_ticket(candidate_ticket_id)
        assert_service_ticket(ticket)
        assert_fields(
            ticket,
            status="OPEN",
            assigned_technician_id=None,
            window_start=None,
            window_end=None,
        )
        assert_fields(fetch_technician(env["technician_id"]), open_dispatch_count=1)
        assert_fields(fetch_device(env["device_ids"][1]), lifecycle_state="ACTIVE")

    def test_dispatch_window_starting_at_the_inflated_boundary_is_accepted(self, api):
        """10:30 is the inflated end of the 09:00-10:00 job, so the slot is free.

        PRD: "The window must be well formed and free: `window_start` strictly
        before `window_end`, `window_start` at or after the logical clock, and no
        intersection with any window already occupied by that same technician on a
        ticket in `DISPATCHED`, `PARTS_HOLD` or `ONSITE` status **after each
        occupied window has been inflated by that technician's
        `travel_buffer_minutes` on both its leading and its trailing edge** — a
        technician carrying the default 30-minute buffer therefore needs a full
        hour of clear air between two adjacent jobs."
        PRD: "The practical consequence is that two windows which merely touch —
        where the earlier window's upper bound equals the later window's lower
        bound — do **not** overlap and are always allowed; only genuinely
        intersecting windows are rejected."
        PRD: "Successful dispatch performs `OPEN → DISPATCHED`, writes
        `assigned_technician_id` from the supplied `technician_id`, recomputes the
        technician's `open_dispatch_count` upward, increments the ticket's
        `version`, and cascades onto the hardware: when the ticket's device has a
        `lifecycle_state` of `ACTIVE`, that device moves `ACTIVE → SERVICE_HOLD`
        and its own `version` increments."

        Design: Difficulty/resource_temporal_overlap/technician_dispatch_windows_conflict_after_travel_buffer_inflation
        """
        env = _dispatch_environment()
        candidate_ticket_id = env["ticket_ids"][1]

        ticket = validate_success(
            api.dispatch_service_ticket(
                candidate_ticket_id,
                dispatch_payload(env["technician_id"], INFLATED_END, "2026-08-05T11:00:00Z"),
                OPS,
            ),
            200,
        )

        assert_service_ticket(ticket)
        assert_fields(
            ticket,
            status="DISPATCHED",
            assigned_technician_id=env["technician_id"],
        )
        _assert_same_instant(ticket["window_start"], INFLATED_END, "window_start")
        _assert_same_instant(ticket["window_end"], "2026-08-05T11:00:00Z", "window_end")
        assert_fields(fetch_technician(env["technician_id"]), open_dispatch_count=2)
        assert_fields(fetch_device(env["device_ids"][1]), lifecycle_state="SERVICE_HOLD")

    def test_each_further_window_is_measured_against_the_newly_inflated_occupancy(self, api):
        """A second job at 10:40 inflates to 12:10, and a third job may start there.

        PRD: "The window must be well formed and free: `window_start` strictly
        before `window_end`, `window_start` at or after the logical clock, and no
        intersection with any window already occupied by that same technician on a
        ticket in `DISPATCHED`, `PARTS_HOLD` or `ONSITE` status **after each
        occupied window has been inflated by that technician's
        `travel_buffer_minutes` on both its leading and its trailing edge** — a
        technician carrying the default 30-minute buffer therefore needs a full
        hour of clear air between two adjacent jobs."
        PRD: "Each technician exposes a derived `open_dispatch_count`: the number
        of tickets assigned to them whose `status` is `DISPATCHED`, `PARTS_HOLD` or
        `ONSITE`."
        PRD: "Successful dispatch performs `OPEN → DISPATCHED`, writes
        `assigned_technician_id` from the supplied `technician_id`, recomputes the
        technician's `open_dispatch_count` upward, increments the ticket's
        `version`, and cascades onto the hardware: when the ticket's device has a
        `lifecycle_state` of `ACTIVE`, that device moves `ACTIVE → SERVICE_HOLD`
        and its own `version` increments."

        Design: Difficulty/resource_temporal_overlap/technician_dispatch_windows_conflict_after_travel_buffer_inflation
        """
        env = _dispatch_environment()
        second_ticket_id, third_ticket_id = env["ticket_ids"][1], env["ticket_ids"][2]

        second = validate_success(
            api.dispatch_service_ticket(
                second_ticket_id,
                dispatch_payload(
                    env["technician_id"], "2026-08-05T10:40:00Z", "2026-08-05T11:40:00Z"
                ),
                OPS,
            ),
            200,
        )
        third = validate_success(
            api.dispatch_service_ticket(
                third_ticket_id,
                dispatch_payload(
                    env["technician_id"], "2026-08-05T12:10:00Z", "2026-08-05T12:40:00Z"
                ),
                OPS,
            ),
            200,
        )

        assert_fields(second, status="DISPATCHED", assigned_technician_id=env["technician_id"])
        _assert_same_instant(second["window_start"], "2026-08-05T10:40:00Z", "window_start")
        _assert_same_instant(second["window_end"], "2026-08-05T11:40:00Z", "window_end")
        assert_fields(third, status="DISPATCHED", assigned_technician_id=env["technician_id"])
        _assert_same_instant(third["window_start"], "2026-08-05T12:10:00Z", "window_start")
        _assert_same_instant(third["window_end"], "2026-08-05T12:40:00Z", "window_end")

        assert_fields(fetch_service_ticket(env["ticket_ids"][0]), status="DISPATCHED")
        assert_fields(fetch_technician(env["technician_id"]), open_dispatch_count=3)
        assert_fields(fetch_device(env["device_ids"][0]), lifecycle_state="SERVICE_HOLD")
        assert_fields(fetch_device(env["device_ids"][1]), lifecycle_state="SERVICE_HOLD")
