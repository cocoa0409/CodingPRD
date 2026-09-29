"""Corner queue - section entities, RespondentBank creation surface."""
from test_helpers import (
    ApiErrorId,
    assert_common_fields,
    assert_millisecond_timestamp,
    new_jurisdiction,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ADMIN, ANALYST, COMMITTEE, RM


def _de():
    return new_jurisdiction(
        jurisdiction_code="DE", name="Germany", basel_aml_index=4.0, corridor_risk_weight=1.0
    )


def _payload(**overrides):
    payload = {
        "legal_name": "Nordbank AG",
        "swift_bic": "NORDDEFF",
        "home_jurisdiction_code": "DE",
        "relationship_manager_user_id": "u-fig-1",
        "expected_monthly_volume_usd": 500000.00,
        "expected_monthly_count": 100,
    }
    payload.update(overrides)
    return payload


def test_create_respondent_returns_201_with_both_initial_dimensions(api):
    """The lifecycle and the payment posture are two parallel dimensions, and both are
    initialised by the same create: PROSPECT alongside BLOCKED, with no rating yet.

    Design: Corner/entities/create_respondent_returns_201_with_both_initial_dimensions
    """
    _de()

    created = validate_success(
        api.create_respondent(_payload(), RM), expected_status=201
    )

    assert created["dd_state"] == "PROSPECT"
    assert created["payment_posture"] == "BLOCKED"
    assert created["risk_rating"] == "UNRATED"
    assert created["version"] == 1


def test_create_respondent_omitted_optionals_take_unverified_defaults(api):
    """The four optional inputs default to an unverified, non-nesting posture, and every
    derived counter starts at zero with no assessment variant in force.

    Design: Corner/entities/create_respondent_omitted_optionals_take_unverified_defaults
    """
    _de()

    created = validate_success(
        api.create_respondent(_payload(), ADMIN), expected_status=201
    )

    assert created["license_status"] == "UNVERIFIED"
    assert created["regulator_standing"] == "UNVERIFIED"
    assert created["nested_activity_permitted"] is False
    assert created["risk_assessment_variant"] == "NONE"
    assert created["nested_exposure_units"] == 0
    assert created["unresponsive_strikes"] == 0


def test_create_respondent_system_fields_are_server_minted(api):
    """The four common fields are minted by the server on create while the three
    transition-stamped instants stay null until their producing transitions run.

    Design: Corner/entities/create_respondent_system_fields_are_server_minted
    """
    _de()

    created = validate_success(
        api.create_respondent(_payload(), RM), expected_status=201
    )

    assert created["license_verified_at"] is None
    assert created["last_approved_at"] is None
    assert created["refresh_due_date"] is None
    assert_common_fields(created)
    assert_millisecond_timestamp(created["created_at"])
    assert_millisecond_timestamp(created["updated_at"])
    assert created["version"] == 1


def test_create_respondent_unknown_home_jurisdiction_returns_not_found(api):
    """The home jurisdiction is a natural-key foreign key carried in the body rather than
    the path, and it is resolved just as strictly, leaving nothing behind.

    Design: Corner/entities/create_respondent_unknown_home_jurisdiction_returns_not_found
    """
    _de()

    response = api.create_respondent(
        _payload(
            legal_name="Ghost Bank", swift_bic="GHSTZZ22", home_jurisdiction_code="ZZ",
            expected_monthly_volume_usd=100000.00, expected_monthly_count=10,
        ),
        RM,
    )
    validate_error(response, ApiErrorId.ERR_JURISDICTION_PROFILE_NOT_FOUND)

    _rows, meta = validate_paginated(api.list_respondents(ANALYST))
    assert meta["total_count"] == 0


def test_get_respondent_unknown_id_returns_respondent_not_found(api):
    """`respondentId` is mapped to its own not-found error id, so an unknown but
    well-formed UUID answers 404 rather than a generic resource error.

    Design: Corner/entities/get_respondent_unknown_id_returns_respondent_not_found
    """
    response = api.get_respondent("99999999-8888-4777-8666-555555555555", ANALYST)
    validate_error(response, ApiErrorId.ERR_RESPONDENT_NOT_FOUND)


def test_list_respondents_filter_by_dd_state_excludes_other_states(api):
    """A successful licensing verification is what moves a PROSPECT to DD_IN_PROGRESS, so
    the `dd_state` filter separates the two rows without touching either.

    Design: Corner/entities/list_respondents_filter_by_dd_state_excludes_other_states
    """
    _de()
    first = validate_success(
        api.create_respondent(_payload(swift_bic="NORDDEFF"), RM), expected_status=201
    )
    second = validate_success(
        api.create_respondent(
            _payload(
                legal_name="Suedbank AG", swift_bic="SUEDDEFF",
                expected_monthly_volume_usd=200000.00, expected_monthly_count=40,
            ),
            RM,
        ),
        expected_status=201,
    )
    validate_success(
        api.verify_licensing(
            second["id"],
            {"license_status": "ACTIVE", "regulator_standing": "GOOD_STANDING",
             "regulator_name": "BaFin"},
            ANALYST,
        )
    )

    rows, meta = validate_paginated(
        api.list_respondents(COMMITTEE, params={"dd_state": "DD_IN_PROGRESS"})
    )

    assert [row["id"] for row in rows] == [second["id"]]
    assert meta["total_count"] == 1
    assert validate_success(api.get_respondent(first["id"], ANALYST))["dd_state"] == "PROSPECT"
