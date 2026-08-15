"""Dark-sky reporting: median variants, grade banding, half-open sweep,
SQM reading range validation."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_sky_quality_reading,
    create_event,
    create_member,
    create_sky_quality_reading_payload,
    create_tier,
    make_member_headers,
    open_dark_sky_report,
    record_reading,
    set_clock,
    validate_error,
    validate_success,
)

OFFICER = TEST_USERS["club_officer_headers"]


class TestDarkSkyMedianVariants:
    def test_provisional_recomputes_while_open(self, api):
        """PRD: "While `OPEN`, the report's `median_sqm` is provisional: it
        is recomputed on every newly recorded reading that falls inside the
        window, and the `advocacy_grade` recomputes alongside it."

        Design: Difficulty/dual_variant_calc/dark_sky_median_provisional_vs_final
        """
        tier = create_tier()
        member = create_member(tier["id"], full_name="Sky Watcher")
        event = create_event(title="Aug PN",
                             window_start="2026-08-10T01:00:00Z",
                             window_end="2026-08-10T05:00:00Z",
                             moon_illumination_pct=20)
        for v in (21.00, 21.40, 21.80):
            record_reading(member, event["id"], v)
        report = open_dark_sky_report("2026-08-01T00:00:00Z",
                                      "2026-09-01T00:00:00Z")
        assert report["median_sqm"] == 21.40, (
            "Odd-count median of [21.00, 21.40, 21.80] is the middle element")
        assert report["reading_count"] == 3

        # A fourth reading inside the window moves the provisional median.
        record_reading(member, event["id"], 10.50)
        moved = validate_success(api.get_dark_sky_report(report["id"], OFFICER))
        assert moved["median_sqm"] == 21.20, (
            "Even-count median of [10.50, 21.00, 21.40, 21.80] averages "
            "(21.00 + 21.40) / 2 = 21.20 — the provisional value moved")
        assert moved["reading_count"] == 4

    def test_final_variant_freezes_median_and_grade(self, api):
        """PRD: "Finalization moves the report `OPEN → FINALIZED` and
        freezes both `median_sqm` and `advocacy_grade` at their
        finalize-time values; readings recorded later inside the window do
        not change the frozen numbers."
        PRD: "at least 20.50 earns `B`"

        Design: Difficulty/dual_variant_calc/dark_sky_median_provisional_vs_final
        """
        tier = create_tier()
        member = create_member(tier["id"], full_name="Freeze Fran")
        event = create_event(title="Aug PN F",
                             window_start="2026-08-10T01:00:00Z",
                             window_end="2026-08-10T05:00:00Z",
                             moon_illumination_pct=20)
        for v in (21.00, 21.40, 21.80):
            record_reading(member, event["id"], v)
        report = open_dark_sky_report("2026-08-01T00:00:00Z",
                                      "2026-09-01T00:00:00Z")
        assert report["median_sqm"] == 21.40

        finalized = validate_success(
            api.finalize_dark_sky_report(report["id"], OFFICER))
        assert finalized["status"] == "FINALIZED"

        # A very bright reading inside the window must NOT move the frozen report.
        record_reading(member, event["id"], 10.50)
        frozen = validate_success(api.get_dark_sky_report(report["id"], OFFICER))
        assert frozen["median_sqm"] == 21.40, (
            "The final variant freezes the median; the later 10.50 reading "
            "inside the window does not move it")
        assert frozen["advocacy_grade"] == "B", (
            "Median 21.40 >= 20.50 and < 21.50 -> grade B, frozen")
        assert frozen["reading_count"] == 3, "The sweep set is frozen too"


class TestSqmReadingRange:
    def test_sqm_reading_range_validation(self, api):
        """PRD: "the `sqm_value` — a decimal magnitudes-per-square-arcsecond
        figure that must lie between 10.00 and 22.99 inclusive"
        PRD: "request shape — required fields present, types correct, enums
        within their declared sets, and numeric ranges honored, any failure
        producing `ERR_INVALID_REQUEST`"

        Design: Corner/entities/sqm_reading_range_validation
        """
        tier = create_tier()
        member = create_member(tier["id"], full_name="SQM Sam")
        event = create_event(title="E", window_start="2026-08-10T01:00:00Z",
                             window_end="2026-08-10T05:00:00Z",
                             moon_illumination_pct=20)

        resp = api.create_sky_quality_reading(
            create_sky_quality_reading_payload(member["id"], event["id"], 23.50),
            make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        assert resp.status_code == 400

        ok = validate_success(
            api.create_sky_quality_reading(
                create_sky_quality_reading_payload(member["id"], event["id"],
                                                   22.99),
                make_member_headers(member["id"])),
            201)
        assert_sky_quality_reading(ok)
        assert ok["sqm_value"] == 22.99, (
            "The inclusive upper bound 22.99 is accepted")


class TestMedianEvenCountAndHalfOpenWindow:
    def test_dark_sky_median_even_count_boundary_grade(self, api):
        """PRD: "For an even count, the median is the average of the two
        middle elements, rounded half-up to two decimal places."
        PRD: "Band edges are inclusive — a median of exactly 21.50 is an
        `A`."
        PRD: "The report begins `OPEN` and immediately sweeps in every
        reading whose `taken_at` falls within the half-open window — a
        reading exactly at `period_end` belongs to the next report."

        Design: Corner/calculations/dark_sky_median_even_count_boundary_grade
        """
        tier = create_tier()
        member = create_member(tier["id"], full_name="Median Mary")
        event = create_event(title="Aug E",
                             window_start="2026-08-10T01:00:00Z",
                             window_end="2026-08-10T05:00:00Z",
                             moon_illumination_pct=20)
        event2 = create_event(title="Sep E",
                              window_start="2026-09-01T01:00:00Z",
                              window_end="2026-09-01T05:00:00Z",
                              moon_illumination_pct=20)
        for v in (21.20, 21.80, 21.60, 21.40):
            record_reading(member, event["id"], v)
        # This reading is stamped at the clock's current instant; advance the
        # clock to exactly the first report's period_end so it lands on the
        # boundary and belongs to the NEXT report (half-open window).
        set_clock("2026-09-01T00:00:00Z")
        record_reading(member, event2["id"], 19.00)

        report = open_dark_sky_report("2026-08-01T00:00:00Z",
                                      "2026-09-01T00:00:00Z")
        assert report["reading_count"] == 4, (
            "The reading stamped exactly at period_end is excluded "
            "(half-open sweep)")
        assert report["median_sqm"] == 21.50, (
            "Even-count median: (21.40 + 21.60) / 2 = 21.50, round-half-up 2dp")
        assert report["advocacy_grade"] == "A", (
            "Median exactly 21.50 lands in the A band — boundary inclusive")
