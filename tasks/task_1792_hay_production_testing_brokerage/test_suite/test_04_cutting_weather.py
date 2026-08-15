"""Cutting calendar and weather windows: cyclic open/slip, wet-day boundary,
missing reports, mark-cut guards, and cutting uniqueness.

Covers PRD §3.1 (growers, fields, cuttings, weather reports).
"""
from test_helpers import (
    TEST_USERS,
    api_client,
    get_cutting,
    make_grower_headers,
    post_dry_reports,
    post_weather_report,
    setup_scheduled_cutting,
    validate_error,
)
from test_helpers.api_errors import ApiErrorId

ADMIN = TEST_USERS["admin_headers"]


# ===========================================================================
# non_linear_state_machine / cutting_weather_window_cyclic_slip
# ===========================================================================

class TestCuttingWeatherWindowCyclicSlip:
    def _setup_june_cutting(self):
        return setup_scheduled_cutting(
            field_overrides={"forage_type": "GRASS"},
            cutting_overrides={
                "planned_window_start": "2026-06-10",
                "planned_window_end": "2026-06-20",
            },
        )

    def test_three_dry_reports_open_window(self, api):
        """PRD §3.1: "If all three days have reports and each is both dry and
        drying-capable, a `SCHEDULED` cutting flips to `WINDOW_OPEN`."

        Design: Difficulty/non_linear_state_machine/cutting_weather_window_cyclic_slip
        """
        grower, _field, cutting = self._setup_june_cutting()
        assert cutting["status"] == "SCHEDULED"
        post_dry_reports(["2026-06-10", "2026-06-11", "2026-06-12"])
        read = get_cutting(cutting["id"], make_grower_headers(grower["id"]))
        assert read["status"] == "WINDOW_OPEN"

    def test_wet_report_slips_and_dry_streak_reopens(self, api):
        """PRD §3.1: "If any of the three days is wet, not drying-capable, or
        missing a report, a `WINDOW_OPEN` cutting reverts to `SCHEDULED` — the
        weather-slip revert." PRD §3.1: "the cyclic `SCHEDULED` ↔
        `WINDOW_OPEN` dance can repeat as many times as the weather demands."

        Three dry reports open the window; one wet report (5.5mm, drying 40)
        slips it back to SCHEDULED; three further dry reports re-open it.

        Design: Difficulty/non_linear_state_machine/cutting_weather_window_cyclic_slip
        """
        grower, _field, cutting = self._setup_june_cutting()
        reader = make_grower_headers(grower["id"])
        post_dry_reports(["2026-06-10", "2026-06-11", "2026-06-12"])
        assert get_cutting(cutting["id"], reader)["status"] == "WINDOW_OPEN"

        post_weather_report("2026-06-13", precipitation_mm=5.5, drying_index=40)
        assert get_cutting(cutting["id"], reader)["status"] == "SCHEDULED"

        post_dry_reports(["2026-06-14", "2026-06-15", "2026-06-16"])
        assert get_cutting(cutting["id"], reader)["status"] == "WINDOW_OPEN"


# ===========================================================================
# boundary_precision_check / wet_day_threshold_exactly_2mm
# ===========================================================================

class TestWetDayThresholdExactly2mm:
    def _setup_june_cutting(self):
        return setup_scheduled_cutting(
            field_overrides={"forage_type": "GRASS"},
            cutting_overrides={
                "planned_window_start": "2026-06-10",
                "planned_window_end": "2026-06-20",
            },
        )

    def test_three_days_at_exactly_2mm_open_window(self, api):
        """PRD §3.1: "A day counts as dry when its precipitation is no more
        than 2.0 millimeters — exactly 2.0 still counts as dry".

        Three consecutive days at exactly 2.0mm (drying 65) all count dry and
        open the window.

        Design: Difficulty/boundary_precision_check/wet_day_threshold_exactly_2mm
        """
        grower, _field, cutting = self._setup_june_cutting()
        for d in ["2026-06-10", "2026-06-11", "2026-06-12"]:
            post_weather_report(d, precipitation_mm=2.0, drying_index=65)
        read = get_cutting(cutting["id"], make_grower_headers(grower["id"]))
        assert read["status"] == "WINDOW_OPEN"

    def test_single_2point1mm_day_slams_window_shut(self, api):
        """PRD §3.1: "A day counts as dry when its precipitation is no more
        than 2.0 millimeters — exactly 2.0 still counts as dry". A day at
        2.1mm exceeds the threshold and is wet, so "a `WINDOW_OPEN` cutting
        reverts to `SCHEDULED`".

        Design: Difficulty/boundary_precision_check/wet_day_threshold_exactly_2mm
        """
        grower, _field, cutting = self._setup_june_cutting()
        reader = make_grower_headers(grower["id"])
        for d in ["2026-06-10", "2026-06-11", "2026-06-12"]:
            post_weather_report(d, precipitation_mm=2.0, drying_index=65)
        assert get_cutting(cutting["id"], reader)["status"] == "WINDOW_OPEN"
        post_weather_report("2026-06-13", precipitation_mm=2.1, drying_index=65)
        assert get_cutting(cutting["id"], reader)["status"] == "SCHEDULED"


# ===========================================================================
# Corner/calculations / weather_missing_report_day_not_dry
# ===========================================================================

def test_weather_missing_report_day_not_dry(api):
    """PRD §3.1: "A day with no report at all counts as not dry."

    Dry reports on 2026-06-10 and 2026-06-12 with 2026-06-11 unreported leave
    the trailing three days not-all-dry, so the cutting stays SCHEDULED.

    Design: Corner/calculations/weather_missing_report_day_not_dry
    """
    grower, _field, cutting = setup_scheduled_cutting(
        field_overrides={"forage_type": "GRASS"},
        cutting_overrides={
            "planned_window_start": "2026-06-10",
            "planned_window_end": "2026-06-20",
        },
    )
    post_weather_report("2026-06-10")
    post_weather_report("2026-06-12")
    read = get_cutting(cutting["id"], make_grower_headers(grower["id"]))
    assert read["status"] == "SCHEDULED"


# ===========================================================================
# Corner/state_machines / cutting_initial_state_scheduled
# ===========================================================================

def test_cutting_initial_state_scheduled(api):
    """PRD §3.1: "A new cutting starts `SCHEDULED`, and its `actual_cut_date`
    stays null until the crop is actually cut."

    Design: Corner/state_machines/cutting_initial_state_scheduled
    """
    _grower, _field, cutting = setup_scheduled_cutting(
        cutting_overrides={
            "planned_window_start": "2026-08-10",
            "planned_window_end": "2026-08-20",
        },
    )
    assert cutting["status"] == "SCHEDULED"
    assert cutting["actual_cut_date"] is None


# ===========================================================================
# Corner/validations / mark_cut_window_closed_rejected
# ===========================================================================

def test_mark_cut_window_closed_rejected(api):
    """PRD §3.1: "Four guards apply, and their failure codes matter: the
    cutting must actually be `WINDOW_OPEN`, otherwise
    `ERR_CUTTING_NOT_OPEN`".

    With no weather reports the cutting is still SCHEDULED, so mark-cut is
    rejected.

    Design: Corner/validations/mark_cut_window_closed_rejected
    """
    grower, _field, cutting = setup_scheduled_cutting(
        field_overrides={"forage_type": "GRASS"},
    )
    resp = api_client.mark_cut(
        cutting["id"], {"actual_cut_date": "2026-08-01"},
        make_grower_headers(grower["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CUTTING_NOT_OPEN)


# ===========================================================================
# Corner/validations / mark_cut_outside_planned_window
# ===========================================================================

def test_mark_cut_outside_planned_window(api):
    """PRD §3.1: "the `actual_cut_date` must fall within the planned window,
    both endpoints inclusive, otherwise `ERR_CUTTING_WINDOW_RANGE`".

    Dry reports on 2026-08-08/09/10 open the window, and a further dry report
    on 2026-08-11 keeps the trailing three days dry for an 08-11 cut attempt;
    the weather guards all pass, so only the planned-window containment rule
    fires on the out-of-window date.

    Design: Corner/validations/mark_cut_outside_planned_window
    """
    grower, _field, cutting = setup_scheduled_cutting()
    post_dry_reports(["2026-08-08", "2026-08-09", "2026-08-10"])
    assert get_cutting(cutting["id"], make_grower_headers(grower["id"]))[
        "status"
    ] == "WINDOW_OPEN"
    # One more dry report past the window end: the cutting (currently
    # WINDOW_OPEN) is re-evaluated and stays open, and the trailing three
    # days ending 08-11 are all dry for the mark-cut guard.
    post_weather_report("2026-08-11")
    assert get_cutting(cutting["id"], make_grower_headers(grower["id"]))[
        "status"
    ] == "WINDOW_OPEN"
    resp = api_client.mark_cut(
        cutting["id"], {"actual_cut_date": "2026-08-11"},
        make_grower_headers(grower["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CUTTING_WINDOW_RANGE)


# ===========================================================================
# Corner/validations / duplicate_weather_report_rejected
# ===========================================================================

def test_duplicate_weather_report_rejected(api):
    """PRD §3.1: "Only one report may exist per region per date; a duplicate
    posting is rejected with `ERR_DUPLICATE_WEATHER_REPORT`."

    Design: Corner/validations/duplicate_weather_report_rejected
    """
    post_weather_report("2026-06-10")
    resp = api_client.create_weather_report(
        {
            "region_code": "OR-WILLAMETTE", "report_date": "2026-06-10",
            "precipitation_mm": 1.0, "drying_index": 65,
        },
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_WEATHER_REPORT)


# ===========================================================================
# Corner/validations / duplicate_cutting_number_pure
# ===========================================================================

def test_duplicate_cutting_number_pure(api):
    """PRD §3.1: "within one field and one `season_year`, the combination of
    `cutting_number` must be unique among cuttings that have not been
    abandoned; a collision is rejected with `ERR_DUPLICATE_CUTTING_NUMBER`."

    The second cutting's window [2026-07-01, 2026-07-10] does not overlap the
    existing [2026-06-10, 2026-06-20) window, so only the uniqueness rule can
    fire.

    Design: Corner/validations/duplicate_cutting_number_pure
    """
    grower, field, _cutting = setup_scheduled_cutting(
        field_overrides={"forage_type": "GRASS"},
        cutting_overrides={
            "planned_window_start": "2026-06-10",
            "planned_window_end": "2026-06-20",
        },
    )
    resp = api_client.create_cutting(
        {
            "field_id": field["id"], "cutting_number": 1, "season_year": 2026,
            "planned_window_start": "2026-07-01",
            "planned_window_end": "2026-07-10",
        },
        make_grower_headers(grower["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_CUTTING_NUMBER)
