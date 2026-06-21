"""Entity creation, defaults, system-managed fields, and immutability.

Covers corner queue section `entities` and the sponsorship field-value validation.
"""
from test_helpers import (
    validate_success, validate_error,
    create_season, create_team,
    create_season_payload, create_team_payload, create_sponsorship_payload,
    distribute_sponsorship, create_sponsorship,
    NON_EXISTENT_UUID, TEST_USERS,
)

COMMISH = TEST_USERS["commissioner_headers"]


def test_create_season_applies_defaults(api):
    """PRD §3.1: "The roster_min ... defaults to 5". "The roster_max ... defaults to 8".
    "The two_way_max ... defaults to 2". "The penalty_threshold ... defaults to 3."
    PRD §3.1: "A newly created season begins life in phase SETUP with its
    trade_window_state initialized to CLOSED."
    PRD §2.4: "The version begins at 1 on creation".

    Design: Corner/entities/create_season_returns_201_with_defaults_applied
    """
    res = api.create_season(create_season_payload(name="Spring", salary_cap_cents=50_000_000), COMMISH)
    data = validate_success(res, 201)
    assert data["phase"] == "SETUP"
    assert data["trade_window_state"] == "CLOSED"
    assert data["roster_min"] == 5
    assert data["roster_max"] == 8
    assert data["two_way_max"] == 2
    assert data["penalty_threshold"] == 3
    assert data["version"] == 1


def test_create_season_missing_salary_cap_returns_validation(api):
    """PRD §3.3: "Required-field presence and pagination well-formedness yield
    ERR_VALIDATION." PRD §3.2: "a missing required field is rejected with ERR_VALIDATION
    (HTTP 400)."

    Design: Corner/entities/create_season_missing_salary_cap_returns_validation
    """
    res = api.create_season({"name": "NoCap"}, COMMISH)
    validate_error(res, "ERR_VALIDATION")


def test_get_team_nonexistent_returns_not_found(api):
    """PRD §2.5: "if any referenced resource along the path does not exist, the request
    is rejected with ERR_NOT_FOUND (HTTP 404)".

    Design: Corner/entities/get_team_nonexistent_returns_not_found
    """
    res = api.get_team(NON_EXISTENT_UUID, COMMISH)
    validate_error(res, "ERR_NOT_FOUND")


def test_create_team_system_fields_generated(api):
    """PRD §3.2: "A new team starts with payroll_active_cents at 0, penalty_points at 0,
    posture OPEN, seed null, and eliminated false." PRD §2.4: "The version begins at 1
    on creation".

    Design: Corner/entities/create_team_system_fields_generated_input_ignored
    """
    season = create_season()
    res = api.create_team(create_team_payload(season["id"], name="Z", market_size_weight=2), COMMISH)
    data = validate_success(res, 201)
    assert data["version"] == 1
    assert data["penalty_points"] == 0
    assert data["posture"] == "OPEN"
    assert data["seed"] is None


def test_create_team_invalid_market_weight_returns_invalid_field(api):
    """PRD §3.2: "a market_size_weight — the sponsorship revenue-share weight used by the
    revenue waterfall, which must be at least 1."
    PRD §3.3 (validation ordering): "Field-value validity yields ERR_INVALID_FIELD_VALUE."

    Design: Corner/entities/create_team_invalid_market_weight_returns_invalid_field_value
    """
    season = create_season()
    res = api.create_team(create_team_payload(season["id"], name="Bad", market_size_weight=0), COMMISH)
    validate_error(res, "ERR_INVALID_FIELD_VALUE")


def test_revenue_share_immutable_no_version_field(api):
    """PRD §2.4: "The RevenueShare entity is an exception: it is an immutable audit
    record carved at distribution time and carries only an id and a created_at — it has
    neither an updated_at nor a version."

    Design: Corner/entities/revenue_share_immutable_no_version_field
    """
    season = create_season()
    team = create_team(season["id"], name="A", market_size_weight=1)
    spo = create_sponsorship(season["id"], pool_cents=10_000_000, league_share_pct=0.40)
    validate_success(distribute_sponsorship(spo), 200)
    res = api.get_team_revenue_shares(team["id"], COMMISH)
    data = validate_success(res, 200)
    share = data[0]
    assert share["amount_cents"] == 6_000_000
    assert "version" not in share
    assert "updated_at" not in share


def test_create_sponsorship_league_share_out_of_range_returns_invalid_field(api):
    """PRD §3.9: "an optional league_share_pct ... defaults to 0.40 and must be at least
    0 and strictly less than 1; a value outside this range is rejected with
    ERR_INVALID_FIELD_VALUE (HTTP 422)."

    Design: Corner/validations/create_sponsorship_league_share_out_of_range_returns_invalid_field
    """
    season = create_season()
    res = api.create_sponsorship(
        create_sponsorship_payload(season["id"], pool_cents=10_000_000, league_share_pct=1.0),
        COMMISH)
    validate_error(res, "ERR_INVALID_FIELD_VALUE")
