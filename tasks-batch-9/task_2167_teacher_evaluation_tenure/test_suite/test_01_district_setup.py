"""District configuration: policies, buildings, educators and cycle creation."""

import pytest

from test_helpers import (
    ApiErrorId,
    MISSING_UUID,
    MISSING_UUIDS,
    TEST_USERS,
    assert_educator,
    assert_evaluation_cycle,
    assert_evaluation_policy,
    assert_millisecond_timestamp,
    assert_school,
    create_educator,
    create_policy,
    create_school,
    educator_payload,
    evaluation_cycle_payload,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

HR = TEST_USERS["hr_admin_headers"]


def test_policy_created_with_only_school_year_carries_every_declared_default(api):
    """PRD §2.5: "The composite split defaults to 60 percent observation and 40
    percent growth: `observation_weight_pct` defaults to 60 and
    `growth_weight_pct` to 40, each must lie between 0 and 100 inclusive, and the
    two must sum to exactly 100."
    PRD §2.5: "The four rubric domain weights default to 22 for
    `planning_weight_pct`, 23 for `environment_weight_pct`, 33 for
    `instruction_weight_pct` and 22 for `professionalism_weight_pct`, and they too
    must sum to exactly 100."
    PRD §2.5: "`required_formal_count` defaults to 2 and must be at least 1;
    `required_informal_count` defaults to 1 and must be at least 0."
    PRD §2.5: "The three banding cut points default to 3.50 for
    `highly_effective_threshold`, 2.50 for `effective_threshold` and 1.50 for
    `developing_threshold`."
    PRD §2.5: "`tenure_required_years` defaults to 3 and
    `tenure_min_consecutive_effective` to 2. `min_days_between_formals` defaults
    to 10."
    PRD §2.5: "`observation_stipend_cents` defaults to 12500 — one hundred and
    twenty-five dollars per formal observation."
    PRD §2.4: "`version` is an integer that begins at 1 when the resource is
    created and increases by exactly 1 on every mutation of that resource,
    whether the mutation was requested directly or arrived as a cascade from
    another entity's transition."

    Design: Corner/entities/create_policy_with_only_school_year_applies_every_declared_default
    """
    response = api.create_evaluation_policy({"school_year": "2026-2027"}, HR)
    policy = validate_success(response, 201)
    assert_evaluation_policy(policy)

    assert policy["observation_weight_pct"] == pytest.approx(60)
    assert policy["growth_weight_pct"] == pytest.approx(40)
    assert policy["planning_weight_pct"] == pytest.approx(22)
    assert policy["environment_weight_pct"] == pytest.approx(23)
    assert policy["instruction_weight_pct"] == pytest.approx(33)
    assert policy["professionalism_weight_pct"] == pytest.approx(22)
    assert policy["required_formal_count"] == 2
    assert policy["required_informal_count"] == 1
    assert policy["effective_threshold"] == pytest.approx(2.50)
    assert policy["highly_effective_threshold"] == pytest.approx(3.50)
    assert policy["developing_threshold"] == pytest.approx(1.50)
    assert policy["min_days_between_formals"] == 10
    assert policy["observation_stipend_cents"] == 12500
    assert policy["version"] == 1, "a freshly created resource carries version 1"


def test_educator_registration_without_service_start_date_is_rejected(api):
    """PRD §3.1: "The registration payload carries the `school_id` of that
    building, the district `employee_number`, the educator's `full_name`, and the
    `service_start_date` on which continuous district service began, written as a
    plain `YYYY-MM-DD` date."
    PRD §2.8: "Body fields present, correctly typed, inside their declared ranges
    and drawn from their declared enumerations, else `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_educator_missing_required_field_returns_invalid_request
    """
    school = create_school()

    response = api.create_educator(
        {"school_id": school["id"], "employee_number": "E-D101", "full_name": "No Date"},
        HR,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    listed, _meta = validate_paginated(
        api.list_educators(HR, params={"school_id": school["id"]})
    )
    assert listed == [], "the rejected registration must persist no Educator"


def test_reading_an_unknown_educator_returns_the_educator_specific_not_found(api):
    """PRD §2.8: "The rejection is the most specific 404 available:
    `ERR_EDUCATOR_NOT_FOUND`, `ERR_EVALUATOR_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND`,
    `ERR_OBSERVATION_NOT_FOUND`, `ERR_PLAN_NOT_FOUND` or `ERR_APPEAL_NOT_FOUND`
    for those six kinds, and `ERR_RESOURCE_NOT_FOUND` for a missing school,
    policy, growth measure, evidence artifact, grievance or calibration review."

    Design: Corner/entities/get_educator_with_unknown_id_returns_not_found
    """
    response = api.get_educator(MISSING_UUID, HR)
    validate_error(response, ApiErrorId.ERR_EDUCATOR_NOT_FOUND.value, 404)


def test_educator_listing_filters_by_building_and_reports_page_metadata(api):
    """PRD §2.3: "`limit` controls page size: it defaults to 10, may not be lower
    than 1, and may not exceed 100."
    PRD §2.3: "The `meta` object of a list response carries `limit`, `offset`,
    `total_count` and `has_more`, where `total_count` is the size of the full
    filtered result set before the page window is applied and `has_more` is true
    exactly when further records remain beyond the current window."
    PRD §2.9: "Educators are filterable by `school_id` and `tenure_status`;
    cycles by `educator_id`, `policy_id`, `school_year`, `status` and
    `dispute_state`;"

    Design: Corner/entities/list_educators_filtered_by_school_paginates_with_total_count
    """
    school_a = create_school(name="Lincoln High", code="LHS", level="HIGH")
    school_b = create_school(name="Grant Middle", code="GMS", level="MIDDLE")
    create_educator(school_a["id"], employee_number="E-D201", full_name="Ann One")
    create_educator(school_a["id"], employee_number="E-D202", full_name="Ben Two")
    educator_c = create_educator(school_b["id"], employee_number="E-D203",
                                 full_name="Cy Three")

    response = api.list_educators(HR, params={"school_id": school_a["id"],
                                              "limit": 1, "offset": 0})
    data, meta = validate_paginated(response)

    assert len(data) == 1, f"limit=1 must return one row, got {len(data)}"
    assert meta["total_count"] == 2, "total_count counts the whole filtered set"
    assert meta["has_more"] is True, "one of the two matching educators is beyond the window"
    assert meta["limit"] == 1 and meta["offset"] == 0
    assert educator_c["id"] not in [row["id"] for row in data], (
        "the educator of the other building must not appear"
    )


def test_new_building_reports_zero_committed_and_full_remaining_budget(api):
    """PRD §2.10: "A school's `evaluation_budget_remaining_cents` is always its
    `evaluation_budget_allocated_cents` minus its
    `evaluation_budget_committed_cents`; `evaluation_budget_allocated_cents`
    defaults to 100000 at building creation and may not be negative, and both
    computed figures start at their derived values of 0 and the full allocation
    respectively."

    Design: Corner/entities/create_school_computes_remaining_budget_from_allocation
    """
    response = api.create_school(
        {"name": "Lincoln High", "code": "LHS", "level": "HIGH",
         "evaluation_budget_allocated_cents": 75000},
        HR,
    )
    school = validate_success(response, 201)
    assert_school(school)

    assert school["evaluation_budget_allocated_cents"] == 75000
    assert school["evaluation_budget_committed_cents"] == 0
    assert school["evaluation_budget_remaining_cents"] == 75000


def test_new_educator_carries_server_minted_identity_and_tenure_fields(api):
    """PRD §2.4: "Every resource the API mints carries an `id` that is a
    server-generated UUID with no type prefix — clients never supply one, and the
    string never encodes the entity kind."
    PRD §2.4: "Alongside it, every resource carries `created_at`, an ISO 8601 UTC
    timestamp with three fractional digits recorded at creation from the logical
    district clock."
    PRD §3.1: "A newly registered educator's `tenure_status` is `PROBATIONARY`,
    their `last_composite_rating` is null, their `tenure_recommended_by_user_id`
    is null, their `tenure_track_hold` is false, and their
    `consecutive_effective_years` is 0."
    PRD §3.1: "Their `completed_service_years` is computed immediately against the
    logical clock: it is the number of whole days elapsed from
    `service_start_date` to the clock's current date, divided by 365 and rounded
    down to a whole number of years."
    PRD §2.11: "Before any operator sets it, the logical clock reads exactly
    `2026-08-01T00:00:00Z`, and it never falls back to real time."

    Design: Corner/entities/educator_system_fields_are_server_minted_on_create
    """
    school = create_school()

    response = api.create_educator(
        educator_payload(school["id"], employee_number="E-D301",
                         full_name="Fresh Hire", service_start_date="2026-07-01"),
        HR,
    )
    educator = validate_success(response, 201)
    assert_educator(educator)

    assert is_valid_uuid(educator["id"]), "id must be a bare server-generated UUID"
    assert educator["version"] == 1
    assert educator["tenure_status"] == "PROBATIONARY"
    assert educator["consecutive_effective_years"] == 0
    assert educator["tenure_track_hold"] is False
    assert educator["last_composite_rating"] is None
    assert educator["completed_service_years"] == 0, (
        "31 days of service against the default clock is less than one whole year"
    )
    assert_millisecond_timestamp(educator["created_at"], "Educator.created_at")


def test_new_cycle_starts_in_scheduling_with_every_composite_field_null(api):
    """PRD §3.1: "A new cycle begins with `status` of `SCHEDULING` and
    `dispute_state` of `NONE`."
    PRD §3.1: "All of the cycle's derived quantities — `completed_formal_count`,
    `completed_informal_count`, `evidence_artifact_count` at 0, and
    `observation_component`, `growth_component`, `composite_score`,
    `composite_rating`, `composite_variant`, `finalized_at` and `appeal_deadline`
    all null, with `evidence_adjustment` at 0 — start empty and are filled by the
    work described below."
    PRD §3.1: "an optional `cycle_type` of `COMPREHENSIVE` or `FOCUSED`,
    defaulting to `COMPREHENSIVE`"

    Design: Corner/entities/create_cycle_starts_in_scheduling_with_null_composite_fields
    """
    policy = create_policy()
    school = create_school()
    educator = create_educator(school["id"], employee_number="E-D601",
                               full_name="Hal Reyes")

    response = api.create_evaluation_cycle(
        evaluation_cycle_payload(educator["id"], policy["id"]), HR
    )
    cycle = validate_success(response, 201)
    assert_evaluation_cycle(cycle)

    assert cycle["status"] == "SCHEDULING"
    assert cycle["dispute_state"] == "NONE"
    assert cycle["cycle_type"] == "COMPREHENSIVE"
    assert cycle["composite_score"] is None
    assert cycle["composite_rating"] is None
    assert cycle["composite_variant"] is None
    assert cycle["observation_component"] is None
    assert cycle["growth_component"] is None
    assert cycle["completed_formal_count"] == 0
    assert cycle["completed_informal_count"] == 0
    assert cycle["evidence_artifact_count"] == 0
    assert cycle["evidence_adjustment"] == pytest.approx(0)
    assert cycle["finalized_at"] is None
    assert cycle["appeal_deadline"] is None


def test_educator_registration_against_an_unknown_building_is_rejected(api):
    """PRD §2.8: "Every resource named in the path and every foreign key in the
    body must exist."
    PRD §2.8: "The rejection is the most specific 404 available:
    `ERR_EDUCATOR_NOT_FOUND`, `ERR_EVALUATOR_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND`,
    `ERR_OBSERVATION_NOT_FOUND`, `ERR_PLAN_NOT_FOUND` or `ERR_APPEAL_NOT_FOUND`
    for those six kinds, and `ERR_RESOURCE_NOT_FOUND` for a missing school,
    policy, growth measure, evidence artifact, grievance or calibration review."

    Design: Corner/entities/create_educator_with_unknown_school_id_returns_not_found
    """
    response = api.create_educator(
        {"school_id": MISSING_UUID, "employee_number": "E-D501",
         "full_name": "Orphan Ed", "service_start_date": "2024-08-15"},
        HR,
    )
    validate_error(response, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value, 404)


def test_each_entity_family_reports_its_own_not_found_code(api):
    """PRD §2.8: "The rejection is the most specific 404 available:
    `ERR_EDUCATOR_NOT_FOUND`, `ERR_EVALUATOR_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND`,
    `ERR_OBSERVATION_NOT_FOUND`, `ERR_PLAN_NOT_FOUND` or `ERR_APPEAL_NOT_FOUND`
    for those six kinds, and `ERR_RESOURCE_NOT_FOUND` for a missing school,
    policy, growth measure, evidence artifact, grievance or calibration review."

    Design: Corner/errors/unknown_ids_return_entity_specific_not_found_codes
    """
    validate_error(api.get_evaluator(MISSING_UUIDS[0], HR),
                   ApiErrorId.ERR_EVALUATOR_NOT_FOUND.value, 404)
    validate_error(api.get_evaluation_cycle(MISSING_UUIDS[1], HR),
                   ApiErrorId.ERR_CYCLE_NOT_FOUND.value, 404)
    validate_error(api.get_observation(MISSING_UUIDS[2], HR),
                   ApiErrorId.ERR_OBSERVATION_NOT_FOUND.value, 404)
    validate_error(api.get_improvement_plan(MISSING_UUIDS[3], HR),
                   ApiErrorId.ERR_PLAN_NOT_FOUND.value, 404)
    validate_error(api.get_appeal(MISSING_UUIDS[4], HR),
                   ApiErrorId.ERR_APPEAL_NOT_FOUND.value, 404)


def test_employee_number_reuse_across_buildings_is_a_conflict(api):
    """PRD §3.1: "Employee numbers are unique across the whole district; a second
    registration reusing one is rejected with `ERR_DUPLICATE_EMPLOYEE_NUMBER`."

    Design: Corner/errors/duplicate_employee_number_is_rejected_as_conflict
    """
    school_a = create_school(name="Lincoln High", code="LHS", level="HIGH")
    school_b = create_school(name="Grant Middle", code="GMS", level="MIDDLE")
    first = create_educator(school_a["id"], employee_number="E-J101",
                            full_name="First Holder", service_start_date="2024-08-15")

    response = api.create_educator(
        {"school_id": school_b["id"], "employee_number": "E-J101",
         "full_name": "Second Holder", "service_start_date": "2025-08-15"},
        HR,
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_EMPLOYEE_NUMBER.value, 409)

    listed, _meta = validate_paginated(
        api.list_educators(HR, params={"school_id": school_b["id"]})
    )
    assert listed == [], "the duplicate registration must persist nothing"
    reread = validate_success(api.get_educator(first["id"], HR))
    assert reread["employee_number"] == "E-J101", "the first holder keeps the number"
