"""The live results feed: forward-looking pace projection, pinned rounding
order, board ordering, and spectator bib tracking."""
from test_helpers import (
    TEST_USERS,
    build_race,
    ingest_reads,
    parse_iso,
    set_clock,
    start_waves,
    validate_success,
)

SP = TEST_USERS["spectator_headers"]

WAVE_7AM = {"key": "w1", "wave_index": 1,
            "scheduled_start_time": "2026-08-01T07:00:00Z", "max_capacity": 100}


def _divergence_board(api):
    """M reaches 7km (elapsed 1770s); N has only reached 3km (elapsed 700s) but
    projects faster. Furthest-point standing would order M first."""
    ctx = build_race(
        name="Live Board 10K", distance_km=10.0, cutoff_minutes=120,
        points=[
            {"key": "start", "point_index": 1, "kind": "START", "distance_km": 0.0},
            {"key": "s3", "point_index": 2, "kind": "SPLIT", "distance_km": 3.0},
            {"key": "s7", "point_index": 3, "kind": "SPLIT", "distance_km": 7.0},
            {"key": "finish", "point_index": 4, "kind": "FINISH",
             "distance_km": 10.0},
        ],
        waves=[WAVE_7AM],
        chips=[{"key": "cm", "chip_code": "CHIP-M"},
               {"key": "cn", "chip_code": "CHIP-N"}],
        registrations=[
            {"key": "m", "wave": "w1", "bib_number": "201",
             "participant_name": "Runner M", "birth_date": "1995-03-10",
             "gender": "M", "chip": "cm"},
            {"key": "n", "wave": "w1", "bib_number": "202",
             "participant_name": "Runner N", "birth_date": "1992-11-20",
             "gender": "M", "chip": "cn"},
        ])
    start_waves(ctx, {"w1": "2026-08-01T07:00:00Z"})
    ingest_reads(ctx, [
        {"point": "start", "chip": "cm", "ts": "2026-08-01T07:00:00.000Z"},
        {"point": "s3", "chip": "cm", "ts": "2026-08-01T07:12:30.000Z"},
        {"point": "s7", "chip": "cm", "ts": "2026-08-01T07:29:30.000Z"},
        {"point": "start", "chip": "cn", "ts": "2026-08-01T07:00:00.000Z"},
        {"point": "s3", "chip": "cn", "ts": "2026-08-01T07:11:40.000Z"},
    ])
    set_clock("2026-08-01T07:35:00Z")
    return ctx


def _rounding_board(api):
    """Segments 740s/3km -> 247 and 770s/3km -> 257; pinned per-segment rounding
    yields projected_total_sec 2518 (the unrounded-then-round order gives 2517)."""
    ctx = build_race(
        name="Rounding 10K", distance_km=10.0, cutoff_minutes=120,
        points=[
            {"key": "start", "point_index": 1, "kind": "START", "distance_km": 0.0},
            {"key": "s3", "point_index": 2, "kind": "SPLIT", "distance_km": 3.0},
            {"key": "s6", "point_index": 3, "kind": "SPLIT", "distance_km": 6.0},
            {"key": "finish", "point_index": 4, "kind": "FINISH",
             "distance_km": 10.0},
        ],
        waves=[WAVE_7AM],
        chips=[{"key": "ce", "chip_code": "CHIP-E"}],
        registrations=[{"key": "e", "wave": "w1", "bib_number": "401",
                        "participant_name": "Runner E", "birth_date": "1988-05-05",
                        "gender": "M", "chip": "ce"}])
    start_waves(ctx, {"w1": "2026-08-01T07:00:00Z"})
    ingest_reads(ctx, [
        {"point": "start", "chip": "ce", "ts": "2026-08-01T07:00:00.000Z"},
        {"point": "s3", "chip": "ce", "ts": "2026-08-01T07:12:20.000Z"},
        {"point": "s6", "chip": "ce", "ts": "2026-08-01T07:25:10.000Z"},
    ])
    set_clock("2026-08-01T07:30:00Z")
    return ctx


class TestProjectionVsFurthestPoint:
    def test_faster_projected_athlete_leads_despite_less_distance(self, api):
        """PRD §3.9: "The projected pace is the mean of the last two segment
        paces, itself rounded half up to a whole second per kilometer; when only
        one segment exists, that segment's pace is used directly. The remaining
        distance is the race's `distance_km` minus the distance of the furthest
        point reached. The projected remaining time in seconds is the remaining
        distance multiplied by the projected pace, rounded half up to a whole
        second. The elapsed time at the last read is the difference between the
        last read and the start read, converted from milliseconds to seconds and
        rounded half up. The projected total is the sum of those elapsed seconds
        and the projected remaining seconds."
        PRD §3.9: "Entries are ordered by projected total ascending; ties break
        by elapsed seconds ascending, then by the registration's `created_at`
        ascending."

        Design: Difficulty/dual_variant_calc/live_projection_vs_furthest_point_standing
        """
        ctx = _divergence_board(api)
        board = validate_success(api.get_live_board(ctx["race"]["id"], SP), 200)
        entries = board["entries"]
        assert len(entries) == 2
        # N: one segment, 700s/3km -> 233; 233 * 7.0km = 1631; 700 + 1631 = 2331.
        assert entries[0]["registration_id"] == ctx["regs"]["n"]["id"]
        assert entries[0]["projected_total_sec"] == 2331

    def test_furthest_along_athlete_projects_slower_total(self, api):
        """PRD §3.9: "For each consecutive pair of points, a segment pace in
        seconds per kilometer is computed as the elapsed time between the two
        reads divided by the distance between the two points, rounded half up to
        a whole second per kilometer — this per-segment rounding happens first."
        PRD §3.9: "Entries are ordered by projected total ascending; ties break
        by elapsed seconds ascending, then by the registration's `created_at`
        ascending."

        Design: Difficulty/dual_variant_calc/live_projection_vs_furthest_point_standing
        """
        ctx = _divergence_board(api)
        board = validate_success(api.get_live_board(ctx["race"]["id"], SP), 200)
        entries = board["entries"]
        # M: segments 250 and 255 -> mean rounds to 253; 253 * 3.0km = 759;
        # elapsed 1770; total 2529 — behind N despite standing two splits deeper.
        assert entries[1]["registration_id"] == ctx["regs"]["m"]["id"]
        assert entries[1]["projected_total_sec"] == 2529
        assert parse_iso(board["generated_at"]) == parse_iso("2026-08-01T07:35:00Z")


class TestPinnedNestedRounding:
    def test_per_segment_rounding_determines_projected_total(self, api):
        """PRD §3.9: "The rounding order is pinned and non-negotiable: each
        segment is rounded before the mean is taken, and the mean is rounded
        before it is multiplied by the remaining distance — computing unrounded
        and rounding only at the end yields different seconds and is
        non-conformant."

        Design: Difficulty/combinatorial_formula/nested_rounding_live_pace_order_pinned
        """
        ctx = _rounding_board(api)
        board = validate_success(api.get_live_board(ctx["race"]["id"], SP), 200)
        entries = board["entries"]
        assert len(entries) == 1
        assert entries[0]["registration_id"] == ctx["regs"]["e"]["id"]
        # Pinned order: 247, 257 -> mean 252 -> 4.0km * 252 = 1008; 1510 + 1008.
        assert entries[0]["projected_total_sec"] == 2518

    def test_unrounded_at_end_would_differ_by_one_second(self, api):
        """PRD §3.9: "For each consecutive pair of points, a segment pace in
        seconds per kilometer is computed as the elapsed time between the two
        reads divided by the distance between the two points, rounded half up to
        a whole second per kilometer — this per-segment rounding happens first.
        The projected pace is the mean of the last two segment paces, itself
        rounded half up to a whole second per kilometer"

        Design: Difficulty/combinatorial_formula/nested_rounding_live_pace_order_pinned
        """
        ctx = _rounding_board(api)
        board = validate_success(api.get_live_board(ctx["race"]["id"], SP), 200)
        total = board["entries"][0]["projected_total_sec"]
        # 2517 is the signature of the forbidden unrounded-then-round order.
        assert total != 2517
        assert total == 2518
        assert parse_iso(board["generated_at"]) == parse_iso("2026-08-01T07:30:00Z")


class TestBibFilterTracking:
    def test_live_board_bib_filter_tracks_single_athlete(self, api):
        """PRD §3.9: "The board answers with an `entries` array and a
        `generated_at` stamp taken from the logical clock, and accepts an
        optional `bib_number` filter for tracking a specific athlete."
        PRD §3.9: "Entries are ordered by projected total ascending; ties break
        by elapsed seconds ascending, then by the registration's `created_at`
        ascending."

        Design: Corner/endpoints/live_board_bib_filter_tracks_single_athlete
        """
        ctx = build_race(
            name="Track 10K", distance_km=10.0, cutoff_minutes=120,
            points=[
                {"key": "start", "point_index": 1, "kind": "START",
                 "distance_km": 0.0},
                {"key": "s3", "point_index": 2, "kind": "SPLIT",
                 "distance_km": 3.0},
                {"key": "finish", "point_index": 3, "kind": "FINISH",
                 "distance_km": 10.0},
            ],
            waves=[WAVE_7AM],
            chips=[{"key": "c1", "chip_code": "CHIP-LB1"},
                   {"key": "c2", "chip_code": "CHIP-LB2"}],
            registrations=[
                {"key": "lb1", "wave": "w1", "bib_number": "201",
                 "participant_name": "LB One", "birth_date": "1990-01-01",
                 "gender": "M", "chip": "c1"},
                {"key": "lb2", "wave": "w1", "bib_number": "202",
                 "participant_name": "LB Two", "birth_date": "1991-01-01",
                 "gender": "F", "chip": "c2"},
            ])
        start_waves(ctx, {"w1": "2026-08-01T07:00:00Z"})
        ingest_reads(ctx, [
            {"point": "start", "chip": "c1", "ts": "2026-08-01T07:00:00.000Z"},
            {"point": "s3", "chip": "c1", "ts": "2026-08-01T07:12:00.000Z"},
            {"point": "start", "chip": "c2", "ts": "2026-08-01T07:00:00.000Z"},
            {"point": "s3", "chip": "c2", "ts": "2026-08-01T07:13:00.000Z"},
        ])
        set_clock("2026-08-01T07:20:00Z")

        filtered = validate_success(api.get_live_board(
            ctx["race"]["id"], SP, params={"bib_number": "202"}), 200)
        assert len(filtered["entries"]) == 1
        assert filtered["entries"][0]["registration_id"] == ctx["regs"]["lb2"]["id"]
        # LB2: 780s/3km -> 260; 260 * 7.0 = 1820; 780 + 1820 = 2600.
        assert filtered["entries"][0]["projected_total_sec"] == 2600

        unfiltered = validate_success(
            api.get_live_board(ctx["race"]["id"], SP), 200)
        entries = unfiltered["entries"]
        assert len(entries) == 2
        # LB1: 720s/3km -> 240; 240 * 7.0 = 1680; 720 + 1680 = 2400.
        assert entries[0]["registration_id"] == ctx["regs"]["lb1"]["id"]
        assert entries[0]["projected_total_sec"] == 2400
        assert entries[1]["registration_id"] == ctx["regs"]["lb2"]["id"]
        assert entries[1]["projected_total_sec"] == 2600
        assert parse_iso(unfiltered["generated_at"]) == parse_iso("2026-08-01T07:20:00Z")
