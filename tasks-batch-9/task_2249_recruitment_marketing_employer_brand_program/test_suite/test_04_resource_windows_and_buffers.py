"""Two temporal contracts: half-open flight windows and closed-interval event buffers."""
from prd_bench_local_runner.testing import validate_error

from test_helpers import ApiErrorId
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import media_buyer_headers


def _flight_program(api):
    program = fx.create_program(api)
    family = fx.create_job_family(api, program["id"], dedicated_budget_cents=1000000)
    channel = fx.create_channel(api, program["id"])
    posting = fx.create_posting(api, family["id"])
    return program, family, channel, posting


def _event_program(api):
    program = fx.create_program(api, flex_reserve_cents=0)
    engineering = fx.create_job_family(
        api, program["id"], dedicated_budget_cents=1000000
    )
    sales = fx.create_job_family(
        api,
        program["id"],
        name="Sales",
        code="SALES",
        priority_rank=2,
        dedicated_budget_cents=500000,
    )
    return program, engineering, sales


def test_back_to_back_flights_that_only_touch_are_both_reservable(api):
    """PRD §3.4: "The flight window is **half-open**: `start_date` is the inclusive first day
    and `end_date` is the exclusive last day, so a flight from the 1st to the 8th occupies
    seven days and a flight whose `end_date` equals another flight's `start_date` does not
    overlap it."
    PRD §3.4: "No other flight on the *same channel and the same job family* whose `state` is
    `RESERVED`, `ACTIVE`, `PAUSED_PACING` or `SUSPENDED_CONTENT` may have a half-open window
    intersecting the requested one, or the request is refused with
    `ERR_FLIGHT_WINDOW_OVERLAP`; because the windows are half-open, back-to-back flights that
    merely touch are allowed."

    Design: Difficulty/resource_temporal_overlap/flight_windows_are_half_open_so_touching_is_legal_and_one_day_back_is_not
    """
    program, family, channel, posting = _flight_program(api)
    first = fx.reserve_flight(
        api,
        channel["id"],
        family["id"],
        posting["id"],
        fx.program_version(api, program["id"]),
        start_date="2026-08-01",
        end_date="2026-08-08",
        daily_cap_cents=50000,
    )

    second = fx.reserve_flight(
        api,
        channel["id"],
        family["id"],
        posting["id"],
        fx.program_version(api, program["id"]),
        start_date="2026-08-08",
        end_date="2026-08-15",
        daily_cap_cents=50000,
    )

    assert first["flight_days"] == 7, first
    assert second["flight_days"] == 7, second
    assert second["state"] == "RESERVED", second
    a.assert_cents(second["total_cost_cents"], 360500, "total_cost_cents")
    a.assert_program_budget(
        fx.read_program(api, program["id"]),
        committed_budget_cents=721000,
        available_budget_cents=279000,
    )
    a.assert_family_reservation(
        fx.read_job_family(api, family["id"]),
        reserved_cents=721000,
        dedicated_available_cents=279000,
    )


def test_a_window_reaching_one_day_back_into_a_live_flight_is_refused_as_an_overlap(api):
    """PRD §2.9: "40. No other non-terminal flight on the same channel and job family may have
    a flight window intersecting the requested one, else `ERR_FLIGHT_WINDOW_OVERLAP` (409)."
    PRD §2.4: "Thereafter, every mutation that the service accepts refreshes `updated_at` and
    increments `version` by exactly 1, including mutations that a cascade performed rather than
    the caller requesting directly."

    Design: Difficulty/resource_temporal_overlap/flight_windows_are_half_open_so_touching_is_legal_and_one_day_back_is_not
    """
    program, family, channel, posting = _flight_program(api)
    for start, end in (("2026-08-01", "2026-08-08"), ("2026-08-08", "2026-08-15")):
        fx.reserve_flight(
            api,
            channel["id"],
            family["id"],
            posting["id"],
            fx.program_version(api, program["id"]),
            start_date=start,
            end_date=end,
            daily_cap_cents=50000,
        )
    before = fx.read_program(api, program["id"])

    refused = api.create_media_flight(
        f.flight_payload(
            channel["id"],
            family["id"],
            posting["id"],
            before["version"],
            start_date="2026-08-07",
            end_date="2026-08-14",
            daily_cap_cents=50000,
        ),
        media_buyer_headers(),
    )

    validate_error(refused, ApiErrorId.FLIGHT_WINDOW_OVERLAP, 409)
    assert len(fx.list_flights(api, channel_id=channel["id"])) == 2
    after = fx.read_program(api, program["id"])
    a.assert_cents(after["committed_budget_cents"], 721000, "committed_budget_cents")
    assert after["version"] == before["version"], (
        "a refused reservation must not advance the program version"
    )


def test_an_event_gap_of_exactly_forty_eight_hours_confirms(api):
    """PRD §3.9: "The recruiter-team buffer is then checked against every other presence of the
    same job family whose `state` is `CONFIRMED` or `COMPLETED`: for each such neighbour, either
    this presence's `start_at` must be at least 48 hours after the neighbour's `end_at`, or this
    presence's `end_at` plus 48 hours must be at or before the neighbour's `start_at`, with both
    intervals treated as closed on both ends."
    PRD §3.9: "A gap of exactly 48 hours satisfies the rule; anything tighter is refused with
    `ERR_EVENT_BUFFER_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/event_buffer_is_a_closed_interval_gap_of_exactly_48_hours_per_job_family
    """
    program, engineering, _ = _event_program(api)
    fx.confirmed_presence(
        api,
        program["id"],
        engineering["id"],
        venue_code="CAMPUS-A",
        start_at="2026-08-10T09:00:00Z",
        end_at="2026-08-10T17:00:00Z",
    )
    neighbour = fx.plan_presence(
        api,
        program["id"],
        engineering["id"],
        venue_code="CAMPUS-B",
        start_at="2026-08-12T17:00:00Z",
        end_at="2026-08-13T01:00:00Z",
    )

    confirmed = fx.confirm_presence(api, neighbour["id"])

    assert confirmed["state"] == "CONFIRMED", confirmed
    a.assert_cents(confirmed["reserved_cents"], 200000, "reserved_cents")
    entries = fx.ledger_entries_for_source(api, neighbour["id"])
    assert len(entries) == 1, entries
    a.assert_ledger_entry(
        entries[0],
        bucket="FAMILY_DEDICATED",
        entry_type="RESERVE",
        delta_cents=200000,
        reason="EVENT_RESERVATION",
        source_type="EVENT_PRESENCE",
        source_id=neighbour["id"],
    )


def test_an_event_gap_one_minute_short_of_the_buffer_is_refused(api):
    """PRD §3.9: "A gap of exactly 48 hours satisfies the rule; anything tighter is refused with
    `ERR_EVENT_BUFFER_CONFLICT`."
    PRD §3.9: "A newly planned presence is in `state` `PLANNED` with `reserved_cents` 0 and
    `confirmed_at` null, and no budget is committed at this stage."

    Design: Difficulty/resource_temporal_overlap/event_buffer_is_a_closed_interval_gap_of_exactly_48_hours_per_job_family
    """
    program, engineering, _ = _event_program(api)
    fx.confirmed_presence(
        api,
        program["id"],
        engineering["id"],
        venue_code="CAMPUS-A",
        start_at="2026-08-10T09:00:00Z",
        end_at="2026-08-10T17:00:00Z",
    )
    tighter = fx.plan_presence(
        api,
        program["id"],
        engineering["id"],
        venue_code="CAMPUS-C",
        start_at="2026-08-12T16:59:00Z",
        end_at="2026-08-13T00:59:00Z",
    )

    refused = api.confirm_event_presence(tighter["id"], None, media_buyer_headers())

    validate_error(refused, ApiErrorId.EVENT_BUFFER_CONFLICT, 409)
    unchanged = fx.read_presence(api, tighter["id"])
    assert unchanged["state"] == "PLANNED", unchanged
    a.assert_cents(unchanged["reserved_cents"], 0, "reserved_cents")
    assert unchanged["confirmed_at"] is None, unchanged
    assert fx.ledger_entries_for_source(api, tighter["id"]) == []


def test_cancelling_a_neighbour_frees_money_but_another_family_is_never_buffered(api):
    """PRD §3.9: "Note that presences in `PLANNED` or `CANCELLED` are ignored by this check
    entirely, so two plans may be drawn up against each other and only the first one confirmed
    will stand."
    PRD §3.9: "A presence cancelled from `CONFIRMED` writes one mirroring `RELEASE` ledger entry
    per outstanding `RESERVE` entry of that presence — same `bucket`, negated `delta_cents`,
    ascending `sequence_no` of the originals, `reason` `EVENT_CANCELLED` — and sets
    `reserved_cents` to 0, restoring the program's `committed_budget_cents` and the family's
    `reserved_cents` to exactly their pre-confirmation values; the program is versioned because
    money moved."

    Design: Difficulty/resource_temporal_overlap/event_buffer_is_a_closed_interval_gap_of_exactly_48_hours_per_job_family
    """
    program, engineering, sales = _event_program(api)
    fx.confirmed_presence(
        api,
        program["id"],
        engineering["id"],
        venue_code="CAMPUS-A",
        start_at="2026-08-10T09:00:00Z",
        end_at="2026-08-10T17:00:00Z",
    )
    neighbour = fx.confirmed_presence(
        api,
        program["id"],
        engineering["id"],
        venue_code="CAMPUS-B",
        start_at="2026-08-12T17:00:00Z",
        end_at="2026-08-13T01:00:00Z",
    )
    tighter = fx.plan_presence(
        api,
        program["id"],
        engineering["id"],
        venue_code="CAMPUS-C",
        start_at="2026-08-12T16:59:00Z",
        end_at="2026-08-13T00:59:00Z",
    )
    overlapping_other_family = fx.plan_presence(
        api,
        program["id"],
        sales["id"],
        venue_code="CAMPUS-A",
        start_at="2026-08-10T12:00:00Z",
        end_at="2026-08-10T20:00:00Z",
    )

    cancel_response = api.cancel_event_presence(neighbour["id"], media_buyer_headers())
    still_refused = api.confirm_event_presence(tighter["id"], None, media_buyer_headers())
    other_family = fx.confirm_presence(api, overlapping_other_family["id"])

    assert cancel_response.status_code == 200, cancel_response.text
    cancelled = fx.read_presence(api, neighbour["id"])
    assert cancelled["state"] == "CANCELLED", cancelled
    a.assert_cents(cancelled["reserved_cents"], 0, "reserved_cents")
    neighbour_entries = fx.ledger_entries_for_source(api, neighbour["id"])
    a.assert_ledger_buckets(
        neighbour_entries,
        [
            ("FAMILY_DEDICATED", "RESERVE", 200000),
            ("FAMILY_DEDICATED", "RELEASE", -200000),
        ],
    )
    validate_error(still_refused, ApiErrorId.EVENT_BUFFER_CONFLICT, 409)
    assert other_family["state"] == "CONFIRMED", other_family
    a.assert_cents(
        fx.read_program(api, program["id"])["committed_budget_cents"],
        400000,
        "committed_budget_cents",
    )
    a.assert_family_reservation(
        fx.read_job_family(api, engineering["id"]),
        reserved_cents=200000,
        dedicated_available_cents=800000,
    )
    a.assert_family_reservation(
        fx.read_job_family(api, sales["id"]),
        reserved_cents=200000,
        dedicated_available_cents=300000,
    )
    buckets = {entry["bucket"] for entry in fx.list_ledger_entries(api, program_id=program["id"])}
    assert buckets == {"FAMILY_DEDICATED"}, (
        f"an event funded from dedicated money must not touch the flex reserve: {buckets}"
    )
