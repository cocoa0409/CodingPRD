"""Rider intake, the independence ladder and the assessment clock."""

from test_helpers import (
    ApiErrorId,
    UNKNOWN_UUID_A,
    assert_rider,
    assert_same_instant,
    book_session,
    file_assessment,
    file_release,
    make_instructor,
    make_instructor_headers,
    make_rider,
    read_assessment,
    read_rider,
    rider_version,
    set_clock,
    setup_active_rider,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ADMIN, CLERK, INTAKE


def test_rider_registration_returns_the_full_intake_projection(api):
    """PRD 3.1: "The new rider lands in `INTAKE` on the lifecycle axis and
    `NEVER_ASSESSED` on the assessment axis, with `independence_level`,
    `required_sidewalker_count`, `requires_leader`, `sidewalker_hold_type` and
    `assessment_next_due_at` all null, `backriding_required` false,
    `goals_met_count` 0, and `medical_hold_incident_id`, `withdraw_reason` and
    `active_release_id` all null."
    PRD 3.1: "`funding_mode` defaults to `PRIVATE_PAY_ALLOWED`, and
    `payer_rate_cents` — the per-charge insurance or payer contribution ceiling
    in cents — defaults to 0."

    Design: Corner/endpoints/rider_create_returns_full_success_envelope
    """
    set_clock("2026-05-01T00:00:00Z")

    response = api.create_rider(
        {
            "full_name": "Rae Rider",
            "date_of_birth": "2012-03-04",
            "weight_lb": 150,
            "household_income_band": "BAND_B",
            "demographic_group": "ADULT",
            "program_code": "THERAPEUTIC_RIDING",
            "condition_codes": ["CP_MILD_ASD"],
        },
        INTAKE,
    )
    rider = validate_success(response, expected_status=201)

    body = response.json()
    assert body["response_type"] == "object", "A single resource is an object payload"
    assert isinstance(body["meta"]["api_request_id"], str) and body["meta"]["api_request_id"]

    assert_rider(rider)
    assert rider["status"] == "INTAKE"
    assert rider["version"] == 1, "PRD 2.4: version begins at 1 when the resource is created"
    assert rider["funding_mode"] == "PRIVATE_PAY_ALLOWED"
    assert rider["payer_rate_cents"] == 0
    assert rider["assessment_status"] == "NEVER_ASSESSED"
    assert rider["independence_level"] is None
    assert rider["required_sidewalker_count"] is None
    assert rider["requires_leader"] is None
    assert rider["sidewalker_hold_type"] is None
    assert rider["assessment_next_due_at"] is None
    assert rider["backriding_required"] is False
    assert rider["goals_met_count"] == 0
    assert rider["medical_hold_incident_id"] is None
    assert rider["withdraw_reason"] is None
    assert rider["active_release_id"] is None


def test_riders_list_applies_default_pagination_and_filters(api):
    """PRD 2.3: "`limit` defaults to 10 when it is not supplied; the smallest
    accepted value is 1 and the largest accepted value is 100."
    PRD 2.3: "The `meta` object of a list response carries `limit`, `offset`,
    `total_count` and `has_more`, where `total_count` is the number of rows
    matching the filters before pagination is applied and `has_more` is true
    exactly when rows remain beyond the current page."

    Design: Corner/endpoints/riders_list_returns_pagination_envelope_with_defaults
    """
    set_clock("2026-05-01T00:00:00Z")
    make_rider(
        full_name="Rider One",
        date_of_birth="2012-03-04",
        household_income_band="BAND_A",
        demographic_group="YOUTH",
        program_code="THERAPEUTIC_RIDING",
        condition_codes=[],
    )
    make_rider(
        full_name="Rider Two",
        date_of_birth="2010-03-04",
        household_income_band="BAND_B",
        demographic_group="ADULT",
        program_code="HIPPOTHERAPY",
        condition_codes=[],
    )
    make_rider(
        full_name="Rider Three",
        date_of_birth="1960-03-04",
        household_income_band="BAND_C",
        demographic_group="SENIOR",
        program_code="EQUINE_LEARNING",
        condition_codes=[],
    )

    response = api.list_riders(INTAKE)
    rows, meta = validate_paginated(response)
    assert response.json()["response_type"] == "array"
    assert meta["limit"] == 10, "limit defaults to 10"
    assert meta["offset"] == 0, "offset defaults to 0"
    assert meta["total_count"] == 3
    assert meta["has_more"] is False
    assert len(rows) == 3

    filtered_rows, filtered_meta = validate_paginated(
        api.list_riders(INTAKE, params={"program_code": "HIPPOTHERAPY"})
    )
    assert filtered_meta["total_count"] == 1
    assert len(filtered_rows) == 1


def test_riders_list_rejects_limit_above_one_hundred(api):
    """PRD 2.3: "A supplied `limit` outside the range 1 through 100 inclusive, a
    supplied `offset` below 0, or either parameter supplied as something other
    than an integer, is rejected with `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/endpoints/riders_list_pagination_limit_above_max_returns_400
    """
    set_clock("2026-05-01T00:00:00Z")

    response = api.list_riders(INTAKE, params={"limit": 101})
    validate_error(response, ApiErrorId.ERR_VALIDATION.value)
    assert response.json()["response_type"] == "error"


def test_get_rider_with_unknown_id_returns_rider_not_found(api):
    """PRD 2.7 rung 9: "A `{rider_id}` path segment resolves to an existing rider
    — otherwise `ERR_RIDER_NOT_FOUND` (404). Applies to every path containing
    `{rider_id}`."

    Design: Corner/entities/get_rider_with_unknown_uuid_returns_404
    """
    set_clock("2026-05-01T00:00:00Z")

    response = api.get_rider(UNKNOWN_UUID_A, INTAKE)
    validate_error(response, ApiErrorId.ERR_RIDER_NOT_FOUND.value)


def test_assessment_derives_combined_score_level_and_next_due(api):
    """PRD 3.1: "The two scores add together into `combined_score`, and
    `combined_score` places the rider on a four-rung independence ladder: 17 or
    more is `LEVEL_4`, 12 through 16 is `LEVEL_3`, 7 through 11 is `LEVEL_2`, and
    6 or less is `LEVEL_1`."
    PRD 3.1: "A `LEVEL_1` rider needs 2 sidewalkers and a leader, with the
    sidewalkers using the `OVER_THE_THIGH` hold."
    PRD 3.1: "Filing an assessment also stamps the assessment's `next_due_at` at
    365 days after `performed_on` (with `performed_on` promoted to midnight UTC
    first), copies that instant onto the rider as `assessment_next_due_at`, and
    moves the rider's previous assessment from `RECORDED` to `SUPERSEDED`; only
    the newest assessment for a rider is ever `RECORDED`."

    Design: Corner/entities/assessment_derives_combined_score_level_and_next_due
    """
    set_clock("2026-05-01T00:00:00Z")
    instructor = make_instructor()
    rider = make_rider(
        household_income_band="BAND_B",
        demographic_group="YOUTH",
        condition_codes=[],
    )
    file_release(rider["id"], expected_rider_version=rider["version"])
    version_before = rider_version(rider["id"])

    response = api.create_assessment(
        rider["id"],
        {
            "assessment_type": "INTAKE",
            "performed_on": "2026-04-01",
            "balance_score": 4,
            "trunk_control_score": 2,
            "rider_weight_lb": 150,
            "backriding_required": True,
            "expected_rider_version": version_before,
        },
        make_instructor_headers(instructor["id"]),
    )
    assessment = validate_success(response, expected_status=201)

    assert assessment["combined_score"] == 6
    assert assessment["independence_level"] == "LEVEL_1"
    assert assessment["required_sidewalker_count"] == 2
    assert assessment["requires_leader"] is True
    assert assessment["sidewalker_hold_type"] == "OVER_THE_THIGH"
    assert_same_instant(assessment["next_due_at"], "2027-04-01T00:00:00.000Z")
    assert assessment["status"] == "RECORDED"

    rider_after = read_rider(rider["id"])
    assert rider_after["independence_level"] == "LEVEL_1"
    assert rider_after["backriding_required"] is True
    assert rider_after["assessment_status"] == "CURRENT"
    assert_same_instant(rider_after["assessment_next_due_at"], "2027-04-01T00:00:00.000Z")

    _, meta = validate_paginated(
        api.list_assessments(ADMIN, params={"rider_id": rider["id"]})
    )
    assert meta["total_count"] == 1


def test_rider_create_with_unknown_income_band_returns_invalid_enum(api):
    """PRD 2.9: "A request-**body** field whose name appears in the following
    list, carrying a value outside that field's declared member set, returns
    `ERR_INVALID_ENUM`: `household_income_band`, `demographic_group`,
    `program_code`, `funding_mode`, `activity_type`, `assessment_type`, `tier`,
    `min_instructor_tier`, `certification_level`, `crew_role`, `hold_type`,
    `incident_type`, `cancellation_reason`, `domain`, `restricted_program_code`,
    `restricted_demographic` and `variant`."

    Design: Corner/validations/rider_create_invalid_enum_band_returns_400
    """
    set_clock("2026-05-01T00:00:00Z")

    response = api.create_rider(
        {
            "full_name": "Rae Rider",
            "date_of_birth": "2012-03-04",
            "weight_lb": 150,
            "household_income_band": "BAND_Z",
            "demographic_group": "ADULT",
            "program_code": "THERAPEUTIC_RIDING",
            "condition_codes": [],
        },
        INTAKE,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_ENUM.value)

    _, meta = validate_paginated(api.list_riders(INTAKE))
    assert meta["total_count"] == 0, "The rejected registration persisted nothing"


def test_riders_list_with_unknown_status_filter_returns_validation(api):
    """PRD 2.9: "an out-of-range value supplied as a *query parameter* —
    including a `status`, `schedule_status`, `billing_status`,
    `assessment_status`, `certification_status`, `charge_type`, `source_type`,
    `severity`, `program_code`, `activity_type`, `crew_role`,
    `certification_level`, `domain` or `variant` used as a list filter or a
    computed-read selector — returns `ERR_VALIDATION` (400) from rung 7; an
    unknown status filter returns `ERR_VALIDATION`"

    Design: Corner/validations/riders_list_invalid_enum_query_filter_returns_400_as_validation
    """
    set_clock("2026-05-01T00:00:00Z")

    response = api.list_riders(INTAKE, params={"status": "BANANA"})
    validate_error(response, ApiErrorId.ERR_VALIDATION.value)


def test_withdraw_is_blocked_while_a_live_session_remains(api):
    """PRD 3.1: "A rider in `INTAKE`, `ACTIVE` or `MEDICAL_HOLD` may be moved to
    `WITHDRAWN` with a supplied `reason`, which is stored as `withdraw_reason`,
    provided the rider holds no session in `CREW_PENDING` or `CONFIRMED`; a rider
    with live sessions is refused with `ERR_INVALID_STATE` until those sessions
    are cancelled."

    Design: Corner/state_machines/withdraw_rider_holding_live_session_returns_invalid_state
    """
    scenario = setup_active_rider()
    session = book_session(
        scenario["rider_id"], scenario["horse_id"], scenario["instructor_id"]
    )

    blocked = api.withdraw_rider(
        scenario["rider_id"], {"reason": "Family relocating"}, INTAKE
    )
    validate_error(blocked, ApiErrorId.ERR_INVALID_STATE.value)

    cancelled = validate_success(
        api.cancel_session(
            session["id"], {"cancellation_reason": "PROGRAM_CLOSURE"}, INTAKE
        )
    )
    assert cancelled["schedule_status"] == "CANCELLED"
    assert cancelled["cancellation_reason"] == "PROGRAM_CLOSURE"

    _, charge_meta = validate_paginated(
        api.list_charges(CLERK, params={"session_id": session["id"]})
    )
    assert charge_meta["total_count"] == 0, "A programme closure is never chargeable"

    withdrawn = validate_success(
        api.withdraw_rider(scenario["rider_id"], {"reason": "Family relocating"}, INTAKE)
    )
    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["withdraw_reason"] == "Family relocating"


def test_activation_without_any_release_returns_release_missing(api):
    """PRD 3.1: "A rider with no release at all is refused with
    `ERR_RELEASE_MISSING` and one whose newest release has lapsed with
    `ERR_RELEASE_EXPIRED`."

    Design: Corner/validations/activation_without_any_release_returns_release_missing
    """
    set_clock("2026-05-01T00:00:00Z")
    instructor = make_instructor()
    rider = make_rider(condition_codes=[])
    file_assessment(
        rider["id"], instructor["id"], expected_rider_version=rider["version"]
    )

    response = api.activate_rider(rider["id"], INTAKE)
    validate_error(response, ApiErrorId.ERR_RELEASE_MISSING.value)

    assert read_rider(rider["id"])["status"] == "INTAKE"
    _, meta = validate_paginated(
        api.list_medical_releases(INTAKE, params={"rider_id": rider["id"]})
    )
    assert meta["total_count"] == 0


def test_assessment_filing_with_a_stale_rider_version_is_rejected(api):
    """PRD 2.4: "Filing an assessment under `POST /riders/{rider_id}/assessments`
    and filing a physician release under `POST /riders/{rider_id}/medical-releases`
    each require a non-optional `expected_rider_version` field carrying the
    client's last observed `version` of the target `Rider`."
    PRD 2.4: "In all three cases, if the supplied value does not equal the parent
    entity's current stored `version`, the request is rejected with
    `ERR_STALE_VERSION` (HTTP 412) and nothing is persisted."

    Design: Corner/cross_cutting_complexity_layers/assessment_filing_with_a_stale_rider_version_returns_412
    """
    set_clock("2026-05-01T00:00:00Z")
    instructor = make_instructor()
    rider = make_rider(condition_codes=[])
    file_release(rider["id"], expected_rider_version=rider["version"])
    stale_version = rider_version(rider["id"])
    first = file_assessment(
        rider["id"],
        instructor["id"],
        expected_rider_version=stale_version,
        balance_score=6,
        trunk_control_score=6,
    )

    reassessment_body = {
        "assessment_type": "ANNUAL_REASSESSMENT",
        "performed_on": "2026-04-15",
        "balance_score": 9,
        "trunk_control_score": 9,
        "rider_weight_lb": 150,
        "backriding_required": False,
        "expected_rider_version": stale_version,
    }
    rejected = api.create_assessment(
        rider["id"], reassessment_body, make_instructor_headers(instructor["id"])
    )
    validate_error(rejected, ApiErrorId.ERR_STALE_VERSION.value)
    assert read_assessment(first["id"])["status"] == "RECORDED"

    reassessment_body["expected_rider_version"] = rider_version(rider["id"])
    retried = validate_success(
        api.create_assessment(
            rider["id"], reassessment_body, make_instructor_headers(instructor["id"])
        ),
        expected_status=201,
    )
    assert retried["independence_level"] == "LEVEL_4"
    assert read_assessment(first["id"])["status"] == "SUPERSEDED"

    rider_after = read_rider(rider["id"])
    assert rider_after["independence_level"] == "LEVEL_4"
    assert rider_after["required_sidewalker_count"] == 0
