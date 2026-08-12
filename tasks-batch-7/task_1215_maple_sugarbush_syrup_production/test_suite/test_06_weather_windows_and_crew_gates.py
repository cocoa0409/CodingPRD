"""Weather-window declaration (OCC, overlap, freeze-thaw), window-open and
crew-activation temporal gates (PRD §2.6, §3.3, §3.5)."""
from test_helpers import (
    ApiErrorId,
    create_weather_window_payload,
    declare_window,
    hire_crew_member,
    open_window,
    set_clock,
    setup_open_season,
    validate_error,
    validate_success,
)


def test_freeze_thaw_exact_boundaries(api, manager_headers):
    """PRD §3.3: "The freeze-thaw eligibility rule requires the forecast low to
    be at most 32.0 degrees and the forecast high to be at least 38.0 degrees —
    a low of exactly 32.0 qualifies, and a high of exactly 38.0 qualifies; a
    warmer low or cooler high is rejected with `ERR_NO_FREEZE_THAW`."

    Design: Corner/validations/freeze_thaw_exact_boundaries
    """
    season = setup_open_season()
    boundary = validate_success(
        api.create_weather_window(
            create_weather_window_payload(
                season["id"], season["version"],
                opens_at="2027-03-01T00:00:00Z", closes_at="2027-03-05T00:00:00Z",
                forecast_min_f=32.0, forecast_max_f=38.0),
            manager_headers),
        201)
    assert boundary["status"] == "FORECAST"

    season_now = validate_success(api.get_season(season["id"], manager_headers), 200)
    res = api.create_weather_window(
        create_weather_window_payload(
            season["id"], season_now["version"],
            opens_at="2027-03-05T00:00:00Z", closes_at="2027-03-10T00:00:00Z",
            forecast_min_f=32.1, forecast_max_f=42.0),
        manager_headers)
    validate_error(res, ApiErrorId.ERR_NO_FREEZE_THAW)


def test_overlapping_window_rejected(api, manager_headers):
    """PRD §3.3: "The new window's half-open interval may not intersect any
    existing `FORECAST` or `OPEN` window of the same season (otherwise
    `ERR_WINDOW_OVERLAP`)"

    Design: Difficulty/resource_temporal_overlap/weather_window_half_open_overlap
    """
    season = setup_open_season()
    declare_window(season["id"], season["version"],
                   opens_at="2027-03-01T00:00:00Z", closes_at="2027-03-10T00:00:00Z")
    season_now = validate_success(api.get_season(season["id"], manager_headers), 200)

    res = api.create_weather_window(
        create_weather_window_payload(
            season["id"], season_now["version"],
            opens_at="2027-03-09T12:00:00Z", closes_at="2027-03-12T00:00:00Z"),
        manager_headers)
    validate_error(res, ApiErrorId.ERR_WINDOW_OVERLAP)


def test_zero_gap_adjacent_window_allowed(api, manager_headers):
    """PRD §3.3: "declaring one takes the `season_id`, an `opens_at` and
    `closes_at` instant forming a half-open interval (open inclusive, close
    exclusive)" and "The new window's half-open interval may not intersect any
    existing `FORECAST` or `OPEN` window of the same season (otherwise
    `ERR_WINDOW_OVERLAP`)" — a successor opening exactly at the predecessor's
    `closes_at` shares no instant with [opens_at, closes_at), so it is allowed.

    Design: Difficulty/resource_temporal_overlap/weather_window_half_open_overlap
    """
    season = setup_open_season()
    declare_window(season["id"], season["version"],
                   opens_at="2027-03-01T00:00:00Z", closes_at="2027-03-10T00:00:00Z")
    season_now = validate_success(api.get_season(season["id"], manager_headers), 200)

    adjacent = validate_success(
        api.create_weather_window(
            create_weather_window_payload(
                season["id"], season_now["version"],
                opens_at="2027-03-10T00:00:00Z", closes_at="2027-03-15T00:00:00Z"),
            manager_headers),
        201)
    assert adjacent["status"] == "FORECAST"


def test_occ_weather_window_stale_season(api, manager_headers):
    """PRD §2.6: "Declaring a weather window requires the request to carry
    `expected_season_version`, the client's last observed `version` of the
    target season. If the season's current `version` has advanced — for example
    because the season was opened, suspended, resumed, or another window was
    declared — the declaration is rejected with `ERR_STALE_VERSION` (HTTP 412).
    Declaring a weather window is itself one of the operations that increments
    the season's `version` by 1."

    Design: Corner/endpoints/occ_weather_window_stale_season
    """
    season = setup_open_season()
    stale_v = season["version"]

    first = validate_success(
        api.create_weather_window(
            create_weather_window_payload(
                season["id"], stale_v,
                opens_at="2027-03-01T00:00:00Z", closes_at="2027-03-05T00:00:00Z"),
            manager_headers),
        201)
    assert first["status"] == "FORECAST"

    res = api.create_weather_window(
        create_weather_window_payload(
            season["id"], stale_v,
            opens_at="2027-03-05T00:00:00Z", closes_at="2027-03-10T00:00:00Z"),
        manager_headers)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)


def test_window_open_before_opens_at_rejected(api, manager_headers):
    """PRD §3.3: "Opening a window moves `FORECAST → OPEN`. It requires the
    season to be in `OPEN` (with the same `ERR_SEASON_NOT_OPEN` /
    `ERR_SEASON_SUSPENDED` split as bush operations) and the logical clock to
    fall within the window's half-open interval (otherwise
    `ERR_OUTSIDE_PRODUCTION_WINDOW`)."

    Design: Corner/validations/window_open_before_opens_at_rejected
    """
    season = setup_open_season()
    window = declare_window(season["id"], season["version"])

    set_clock("2027-02-20T00:00:00Z")  # before opens_at 2027-03-01
    res = api.open_weather_window(window["id"], manager_headers)
    validate_error(res, ApiErrorId.ERR_OUTSIDE_PRODUCTION_WINDOW)

    after = validate_success(api.get_weather_window(window["id"], manager_headers), 200)
    assert after["status"] == "FORECAST"


def test_crew_activate_outside_season_rejected(api, manager_headers):
    """PRD §3.5: "Activating a crew member moves `HIRED → ACTIVE` and requires
    the season to be `OPEN` and the logical clock date to fall within the
    season's `opens_on` through `closes_on` range."
    PRD §2.7: "7. **Clock-vs-window gates** — temporal checks
    (`ERR_OUTSIDE_PRODUCTION_WINDOW`, `ERR_COLLECTED_OUTSIDE_WINDOW`,
    `ERR_AUDIT_NOT_DUE`)."

    Design: Corner/validations/crew_activate_outside_season_rejected
    """
    season = setup_open_season()  # opened while clock reads 2027-02-15
    tapper = hire_crew_member(season["id"], "Tammy Tapper", "TAPPER")

    set_clock("2027-01-15T00:00:00Z")  # before opens_on 2027-02-01
    res = api.activate_crew_member(tapper["id"], manager_headers)
    validate_error(res, ApiErrorId.ERR_OUTSIDE_PRODUCTION_WINDOW)

    after = validate_success(api.get_crew_member(tapper["id"], manager_headers), 200)
    assert after["status"] == "HIRED"
