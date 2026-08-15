"""Facility onboarding, season publishing, and pass-holder registration."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    assert_facility, assert_pass_holder, assert_season,
    create_facility_payload, create_season_payload, create_pass_holder_payload,
    make_facility, make_season,
)

MANAGER = TEST_USERS["manager_headers"]
GATE = TEST_USERS["gate_headers"]


def test_facility_create_returns_defaults(api):
    """PRD §3.1: "The new facility starts with `current_bather_count` at 0,
    `required_lifeguard_count` at 0, `operational_status` of `OPEN`,
    `chemistry_state` of `IN_RANGE`, and `chemistry_out_of_range_since` null."
    PRD §2.4: "`version` (integer): starts at 1 on creation and increments by
    1 on every mutation of the resource".

    Design: Corner/entities/facility_create_returns_defaults
    """
    data = validate_success(
        api.create_facility(
            create_facility_payload(
                name="F1", address="1 A",
                max_bather_capacity=50, lap_lane_count=4,
            ),
            MANAGER,
        ),
        expected_status=201,
    )
    assert_facility(data)
    assert data["current_bather_count"] == 0
    assert data["required_lifeguard_count"] == 0
    assert data["operational_status"] == "OPEN"
    assert data["chemistry_state"] == "IN_RANGE"
    assert data["chemistry_out_of_range_since"] is None
    assert data["version"] == 1


def test_facility_create_missing_required_field_returns_400(api):
    """PRD §2.10: "Field shape — required fields present, enum values match
    declared members case-sensitively, numeric inputs within their declared
    bounds (`ERR_INVALID_REQUEST`)."

    Design: Corner/entities/facility_create_missing_required_field_returns_400
    """
    resp = api.create_facility(
        {"name": "F1", "address": "1 A", "lap_lane_count": 4}, MANAGER
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_pass_holder_invalid_residency_enum_returns_400(api):
    """PRD §3.2: "Residency is one of `RESIDENT` or `NON_RESIDENT`".
    PRD §2.10: "Field shape — required fields present, enum values match
    declared members case-sensitively, numeric inputs within their declared
    bounds (`ERR_INVALID_REQUEST`)."

    Design: Corner/entities/pass_holder_invalid_residency_enum_returns_400
    """
    resp = api.create_pass_holder(
        create_pass_holder_payload(residency_status="CITIZEN"), GATE
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_facility_get_nonexistent_returns_404(api):
    """PRD §2.9: "The first path identifier that does not resolve to an
    existing resource yields `ERR_NOT_FOUND` (HTTP 404) and stops further
    evaluation."

    Design: Corner/entities/facility_get_nonexistent_returns_404
    """
    resp = api.get_facility("00000000-0000-0000-0000-000000000000", MANAGER)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_pass_holder_banned_until_default_null(api):
    """PRD §3.2: "Each holder also carries two disciplinary fields,
    `strike_count` (initially 0) and `banned_until` (initially null),
    populated by the incident workflow described in §3.8."

    Design: Corner/entities/pass_holder_banned_until_default_null
    """
    data = validate_success(
        api.create_pass_holder(create_pass_holder_payload(), GATE),
        expected_status=201,
    )
    assert_pass_holder(data)
    assert data["strike_count"] == 0
    assert data["banned_until"] is None


def test_season_publish_resident_gt_nonresident_rejected(api):
    """PRD §3.1: "Publishing the season moves it to `PUBLISHED`, but only if
    resident prices do not exceed the corresponding non-resident prices — that
    is, `resident_pass_price_cents` is at most `non_resident_pass_price_cents`
    and `resident_daily_price_cents` is at most
    `non_resident_daily_price_cents` — and only if no other `PUBLISHED` season
    for the same facility overlaps the requested window."
    PRD §3.1: "A violation of either condition is rejected with
    `ERR_SEASON_OVERLAP` (HTTP 409)."

    Design: Corner/entities/season_publish_resident_gt_nonresident_rejected
    """
    facility = make_facility(max_bather_capacity=50, lap_lane_count=2)
    season = get_success_data(
        api.create_season(
            create_season_payload(
                facility["id"],
                season_name="Bad",
                resident_pass_price_cents=20000,
                non_resident_pass_price_cents=15000,
            ),
            MANAGER,
        )
    )
    resp = api.publish_season(season["id"], MANAGER)
    validate_error(resp, ApiErrorId.ERR_SEASON_OVERLAP)
    after = validate_success(api.get_season(season["id"], MANAGER))
    assert_season(after)
    assert after["status"] == "DRAFT"
