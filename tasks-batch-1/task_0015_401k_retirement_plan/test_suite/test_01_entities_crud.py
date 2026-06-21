"""Entity CRUD, system-managed defaults, type & enum validation.

Corner queue B — Section: entities.
"""
import pytest

from test_helpers import (
    api_client,
    TEST_USERS,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    assert_plan,
    assert_participant,
    assert_vesting_event,
    create_plan_payload,
    create_participant_payload,
    create_vesting_event_payload,
    setup_active_plan_with_enrolled_participant,
    set_clock,
    create_and_activate_plan,
    DEFAULT_ANNUAL_COMPENSATION_LIMIT_CENTS,
    DEFAULT_ANNUAL_DEFERRAL_LIMIT_CENTS,
)

_ADMIN = TEST_USERS["plan_admin_headers"]


def test_plan_create_minimal_payload_returns_draft_v1(api):
    """PRD §3.1: "A newly created plan begins in `DRAFT` status with `version = 1`."

    Design: Corner/entities/plan_create_minimal_valid_payload_returns_201
    """
    res = api.create_plan(
        create_plan_payload(name="Acme 401k", plan_year=2026,
                            match_formula="TIERED", vesting_schedule="CLIFF_3"),
        _ADMIN,
    )
    data = validate_success(res, expected_status=201)
    assert_plan(data)
    assert data["status"] == "DRAFT"
    assert data["version"] == 1
    assert data["match_formula"] == "TIERED"
    assert data["vesting_schedule"] == "CLIFF_3"


def test_get_plan_with_unknown_id_returns_not_found(api):
    """PRD §2.10: "Existence of every path-templated parent runs third and returns
    `ERR_NOT_FOUND` on the first identifier in the path that does not resolve."

    Design: Corner/entities/plan_get_by_unknown_id_returns_404
    """
    res = api.get_plan("00000000-0000-0000-0000-000000000000", _ADMIN)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND)


def test_participant_create_missing_required_field_returns_invalid_request(api):
    """PRD §3.2: "A participant is brought into a plan by creating a `Participant` resource scoped to a `plan_id`, carrying a legal `full_name`, an ISO 8601 `date_of_birth`, an ISO 8601 `hire_date`, the participant's reported annual gross compensation in integer cents via `annual_compensation_cents` (which must be strictly positive), and optionally an initial elective deferral expressed in basis points via `deferral_rate_bps` (defaulting to 0, bounded between 0 and 10000 inclusive — for example, 600 means 6.00% of compensation)."

    Design: Corner/entities/participant_create_missing_required_field_returns_invalid_request
    """
    plan = create_and_activate_plan(name="P", match_formula="TIERED", vesting_schedule="CLIFF_3")
    # Omit annual_compensation_cents — a required positive-integer field.
    res = api.create_participant(
        {
            "plan_id": plan["id"],
            "full_name": "X",
            "date_of_birth": "1980-01-01T00:00:00Z",
            "hire_date": "2024-01-01T00:00:00Z",
        },
        _ADMIN,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


def test_plan_create_invalid_enum_for_match_formula_returns_invalid_request(api):
    """PRD §3.1: "the employer's chosen `match_formula` — one of `TIERED` or
    `SAFE_HARBOR_ENHANCED`"

    Design: Corner/entities/participant_create_invalid_enum_for_match_formula_on_plan
    """
    res = api.create_plan(
        create_plan_payload(name="Bad", plan_year=2026,
                            match_formula="UNKNOWN", vesting_schedule="CLIFF_3"),
        _ADMIN,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


def test_plan_default_annual_limits_when_omitted(api):
    """PRD §3.1: "`annual_compensation_limit_cents`, the IRC §401(a)(17) compensation
    ceiling that bounds the compensation slice used in match calculations, defaults
    to 34,500,000 cents; and `annual_deferral_limit_cents`, the IRC §402(g) elective
    deferral cap for participants under age 50, defaults to 2,300,000 cents."

    Design: Corner/entities/plan_default_annual_limits_when_omitted
    """
    res = api.create_plan(
        {
            "name": "Dflt",
            "plan_year": 2026,
            "match_formula": "TIERED",
            "vesting_schedule": "CLIFF_3",
        },
        _ADMIN,
    )
    data = validate_success(res, expected_status=201)
    assert data["annual_compensation_limit_cents"] == DEFAULT_ANNUAL_COMPENSATION_LIMIT_CENTS
    assert data["annual_deferral_limit_cents"] == DEFAULT_ANNUAL_DEFERRAL_LIMIT_CENTS


def test_participant_system_fields_default_on_create(api):
    """PRD §3.2: "On creation the participant's enrollment is `PENDING`, their
    computed balances `employee_balance_cents` and `employer_balance_cents` are 0,
    their derived `years_of_service` is 0, their `vested_employer_balance_cents` is
    0, and their `outstanding_loan_principal_cents` is 0."

    Design: Corner/entities/participant_system_fields_generated_on_create
    """
    plan = create_and_activate_plan(name="P", match_formula="TIERED", vesting_schedule="CLIFF_3")
    res = api.create_participant(
        create_participant_payload(plan["id"], full_name="Z",
                                   date_of_birth="1980-01-01T00:00:00Z",
                                   hire_date="2024-01-01T00:00:00Z",
                                   annual_compensation_cents=12_000_000,
                                   deferral_rate_bps=400),
        _ADMIN,
    )
    data = validate_success(res, expected_status=201)
    assert_participant(data)
    assert data["enrollment_status"] == "PENDING"
    assert data["employee_balance_cents"] == 0
    assert data["employer_balance_cents"] == 0


def test_vesting_event_immutable_append_only(api):
    """PRD §2.4: "The `VestingEvent` resource is the single exception: it is an
    immutable, append-only audit row, so it carries only `id` and `created_at` —
    neither `updated_at` nor `version` is present on a `VestingEvent`."

    Design: Corner/entities/vesting_event_immutable_no_version_no_update
    """
    set_clock("2026-06-15T00:00:00Z")
    _plan, participant = setup_active_plan_with_enrolled_participant(
        plan_overrides={"name": "VE", "match_formula": "TIERED", "vesting_schedule": "GRADED_6"},
        participant_overrides={"full_name": "VE Holder",
                               "date_of_birth": "1980-01-01T00:00:00Z",
                               "hire_date": "2024-06-15T00:00:00Z"},
    )
    res = api.create_vesting_event(
        create_vesting_event_payload(participant["id"],
                                     as_of_date="2026-06-15T00:00:00Z",
                                     years_of_service_after=2,
                                     vested_pct_bps_after=4000),
        _ADMIN,
    )
    data = validate_success(res, expected_status=201)
    assert_vesting_event(data)
    assert data["years_of_service_after"] == 2
    assert data["vested_pct_bps_after"] == 4000
    assert data["participant_id"] == participant["id"]
    # PRD §2.4 explicitly states no `updated_at` and no `version` are present.
    assert "updated_at" not in data or data.get("updated_at") in (None, "")
    assert "version" not in data or data.get("version") in (None, 0)
