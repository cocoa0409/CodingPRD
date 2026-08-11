"""Season creation defaults, configuration editing, and optimistic concurrency."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_season,
    create_season_payload,
    get_season,
    is_valid_uuid,
    make_season,
    validate_error,
    validate_success,
)


def test_season_creation_applies_defaults(api, operator_headers):
    """PRD §3.1: "A new season begins with `status` `PLANNING`, `readiness_posture`
    initialized to `BLOCKED`, `volunteer_confirmed_hours` and `outstanding_admissions`
    at zero, `version` at 1, and `season_weeks` computed as the number of days from
    opening to closing divided by seven and rounded up to a whole number of weeks — the
    figure booth fees later multiply against."

    Design: Corner/entities/season_creation_applies_defaults
    """
    season = validate_success(
        api.create_season(
            create_season_payload(name="Default Revel"), operator_headers
        ),
        201,
    )
    assert_season(season)
    assert season["status"] == "PLANNING"
    assert season["readiness_posture"] == "BLOCKED"
    assert season["volunteer_confirmed_hours"] == 0
    assert season["outstanding_admissions"] == 0
    # 2026-06-06 .. 2026-06-20 is 14 days -> ceil(14 / 7) == 2 weeks.
    assert season["season_weeks"] == 2
    assert season["version"] == 1
    assert is_valid_uuid(season["id"])


def test_season_missing_required_name_returns_invalid_request(api, operator_headers):
    """PRD §2.9: "Required fields must be present; types, enum memberships, and ranges
    must be valid — end times strictly after their start times, `closing_date` on or
    after `opening_date`, `quantity` at least 1, fraction fields between 0 and 1
    inclusive, jury scores between 0 and 10 inclusive; a `SEASON` order must omit
    `faire_day_id` while `DAY` and `GROUP` orders must include it; unknown fields are
    rejected. All shape failures return `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/season_missing_required_name_returns_invalid_request
    """
    payload = create_season_payload()
    del payload["name"]
    res = api.create_season(payload, operator_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_get_nonexistent_season_returns_not_found(api, any_headers):
    """PRD §2.9: "Resource identifiers in the path are validated left to right, and
    the first missing one produces its resource-specific 404: `ERR_SEASON_NOT_FOUND`,
    `ERR_FAIRE_DAY_NOT_FOUND`, `ERR_PERFORMER_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`,
    `ERR_SLOT_NOT_FOUND`, `ERR_VENDOR_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`,
    `ERR_BOOTH_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
    `ERR_TICKET_NOT_FOUND`, `ERR_RAIN_CHECK_NOT_FOUND`, `ERR_SHIFT_NOT_FOUND`,
    `ERR_CASE_NOT_FOUND`, or `ERR_TASK_NOT_FOUND`."

    Design: Corner/entities/get_nonexistent_season_returns_not_found
    """
    res = api.get_season(NON_EXISTENT_UUID, any_headers)
    validate_error(res, ApiErrorId.ERR_SEASON_NOT_FOUND, expected_status=404)


def test_patch_season_after_planning_rejected(api, operator_headers):
    """PRD §3.1: "Once the season has left `PLANNING`, configuration edits are
    rejected with `ERR_SEASON_NOT_IN_PLANNING`."
    PRD §2.8: "it is evaluated only after every state precondition of the operation
    has passed, so a stale version on an otherwise valid request surfaces
    `ERR_STALE_VERSION`, while a request that also violates a state rule surfaces that
    state error first."

    Design: Corner/validations/patch_season_after_planning_rejected
    """
    season = make_season(name="Frozen Config Revel")
    created_version = season["version"]
    validate_success(api.begin_build(season["id"], operator_headers), 200)

    res = api.patch_season(
        season["id"],
        {"expected_season_version": created_version, "daily_capacity": 600},
        operator_headers,
    )
    # The state gate (season must be PLANNING) fires even though begin-build has
    # also advanced the version past the one the caller carries.
    validate_error(res, ApiErrorId.ERR_SEASON_NOT_IN_PLANNING, expected_status=409)


def test_occ_season_config_edit_success_bumps_version(api, operator_headers):
    """PRD §2.8: "Editing a season's configuration requires the request to carry
    `expected_season_version`, a non-optional field holding the season's `version` as
    the client last observed it."
    PRD §3.1: "the operator may revise its configuration — `daily_capacity`,
    `group_min_size`, `volunteer_min_hours`, `weather_call_deadline_hour`, and
    `rain_check_grace_days` — through the OCC-guarded edit described in §2.8, which
    requires `expected_season_version` and increments the season's `version` by 1 on
    success."

    Design: Corner/cross_cutting_layers/occ_season_config_stale_version
    """
    season = make_season(name="OCC Revel A")
    assert season["version"] == 1

    patched = validate_success(
        api.patch_season(
            season["id"],
            {"expected_season_version": season["version"], "daily_capacity": 600},
            operator_headers,
        ),
        200,
    )
    assert patched["daily_capacity"] == 600
    assert patched["version"] == season["version"] + 1


def test_occ_season_config_stale_version_rejected(api, operator_headers):
    """PRD §2.8: "If the season's current `version` has advanced beyond that value,
    the edit is rejected with `ERR_STALE_VERSION` (HTTP 412). A configuration edit
    keeps the season in `PLANNING`, so without this check a later edit based on a
    previously observed version would silently rebase thresholds — capacity, group
    size, volunteer hours — onto a configuration the caller never saw."

    Design: Corner/cross_cutting_layers/occ_season_config_stale_version
    """
    season = make_season(name="OCC Revel A")
    stale_version = season["version"]
    validate_success(
        api.patch_season(
            season["id"],
            {"expected_season_version": stale_version, "daily_capacity": 600},
            operator_headers,
        ),
        200,
    )

    res = api.patch_season(
        season["id"],
        {"expected_season_version": stale_version, "group_min_size": 12},
        operator_headers,
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    # The rejected edit left no trace.
    reread = get_season(season["id"])
    assert reread["group_min_size"] == 10
    assert reread["daily_capacity"] == 600
