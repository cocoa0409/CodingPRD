"""Condition surveys: the two scoring bases, the tier ladder and countersignature."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_score_preview,
    countersign_survey,
    get_success_data,
    list_equipment_surveys,
    make_project_manager_headers,
    make_survey_technician_headers,
    read_car,
    read_posture,
    read_project,
    read_survey,
    setup_project_with_cars,
    submit_survey,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import PM, create_car


def test_score_preview_diverges_between_the_two_bases_for_an_unobserved_machine():
    """Under the **observed-only** basis, a component graded `NOT_OBSERVED` is dropped from
    both the numerator and the denominator: the score is the weighted sum over the
    observed components divided by the sum of the weights of those observed components,
    and that quotient is then rounded half-up to two decimal places.

    Under the **imputed-failed** basis, a component graded `NOT_OBSERVED` scores 0 points and
    *keeps* its weight in the denominator, which stays at the full unity of the three
    weights combined.

    Design: Difficulty/dual_variant_calc/condition_score_observed_only_vs_imputed_failed
    """
    ctx = setup_project_with_cars(num_cars=1)
    survey = submit_survey(
        ctx["car"]["id"],
        controller_condition="GOOD",
        machine_condition="NOT_OBSERVED",
        door_equipment_condition="FAIR",
    )

    observed = get_success_data(
        api_client.get_survey_score_preview(
            survey["id"], PM, params={"basis": "OBSERVED_ONLY"}
        )
    )
    assert_score_preview(observed, "OBSERVED_ONLY")
    assert observed["score"] == 71.07
    assert observed["observed_weight_total"] == 0.70
    assert observed["recommended_scope_tier"] == "CONTROLLER_DOOR"

    imputed = get_success_data(
        api_client.get_survey_score_preview(
            survey["id"], PM, params={"basis": "IMPUTED_FAILED"}
        )
    )
    assert_score_preview(imputed, "IMPUTED_FAILED")
    assert imputed["score"] == 49.75
    assert imputed["observed_weight_total"] == 1.00
    assert imputed["recommended_scope_tier"] == "CONTROLLER_MACHINE"

    assert observed["score"] != imputed["score"]


def test_countersignature_promotes_the_imputed_failed_score_onto_the_car():
    """At submission the survey is scored on the observed-only basis and the result is
    written to `provisional_score`, with the tier it implies written to the survey's
    `recommended_scope_tier`.

    On success the survey moves `SUBMITTED → COUNTERSIGNED`, stores the countersigning
    caller's identifier as `countersigned_by_user_id`, recomputes the composite on the
    imputed-failed basis into `final_score`, derives `recommended_scope_tier` from
    that final score, copies the final score onto the car as `condition_score` and the
    tier onto the car as `recommended_scope_tier`, advances the car `SURVEY_PENDING →
    SURVEYED` on the work dimension while leaving `compliance_status` untouched, moves
    the project `SURVEY → SCOPING` if this is the project's first countersignature,
    and increments the project's `version` by 1.

    Design: Difficulty/dual_variant_calc/condition_score_observed_only_vs_imputed_failed
    """
    ctx = setup_project_with_cars(num_cars=1)
    survey = submit_survey(
        ctx["car"]["id"],
        controller_condition="GOOD",
        machine_condition="NOT_OBSERVED",
        door_equipment_condition="FAIR",
    )
    assert survey["provisional_score"] == 71.07

    countersign_survey(survey["id"])

    stored = read_survey(survey["id"])
    assert stored["provisional_score"] == 71.07
    assert stored["final_score"] == 49.75
    assert stored["recommended_scope_tier"] == "CONTROLLER_MACHINE"
    assert stored["provisional_score"] != stored["final_score"]

    car = read_car(ctx["car"]["id"])
    assert car["condition_score"] == 49.75
    assert car["recommended_scope_tier"] == "CONTROLLER_MACHINE"


def test_score_preview_applies_the_declared_weights_and_point_scale():
    """The scoring converts each grade to points on a fixed scale: `EXCELLENT` is worth
    100 points, `GOOD` 80, `FAIR` 55, `POOR` 25 and `FAILED` 0. The three components
    carry fixed weights — the controller assessment carries forty-five hundredths of the
    total, the hoist machine thirty hundredths, and the door equipment the remaining
    twenty-five hundredths.

    Design: Corner/calculations/score_preview_applies_the_declared_condition_weights_and_point_scale
    """
    ctx = setup_project_with_cars(num_cars=1)
    survey = submit_survey(
        ctx["car"]["id"],
        controller_condition="EXCELLENT",
        machine_condition="GOOD",
        door_equipment_condition="FAIR",
    )

    observed = get_success_data(
        api_client.get_survey_score_preview(
            survey["id"], PM, params={"basis": "OBSERVED_ONLY"}
        )
    )
    assert observed["basis"] == "OBSERVED_ONLY"
    assert observed["score"] == 82.75
    assert observed["observed_weight_total"] == 1.00
    assert observed["recommended_scope_tier"] == "CONTROLLER_ONLY"

    imputed = get_success_data(
        api_client.get_survey_score_preview(
            survey["id"], PM, params={"basis": "IMPUTED_FAILED"}
        )
    )
    assert imputed["score"] == 82.75
    assert imputed["observed_weight_total"] == 1.00

    unchanged = read_survey(survey["id"])
    assert unchanged["status"] == "SUBMITTED"
    assert unchanged["final_score"] is None
    assert read_car(ctx["car"]["id"])["condition_score"] is None


def test_recommended_tier_boundary_is_inclusive_at_exactly_eighty_points():
    """A score of 80.00 or more recommends `CONTROLLER_ONLY`. Otherwise a score of 60.00
    or more recommends `CONTROLLER_DOOR`. The comparison is performed against the
    already-rounded two-decimal score with no further rounding, so exactly 80.00
    recommends `CONTROLLER_ONLY` while 79.99 recommends `CONTROLLER_DOOR`.

    Design: Corner/calculations/recommended_tier_boundary_at_exactly_eighty_points
    """
    ctx = setup_project_with_cars(num_cars=1)
    second_car = create_car(
        ctx["project"]["id"], ctx["group"]["id"], car_designation="CAR-2", duty_rank=2
    )

    all_good = submit_survey(
        ctx["car"]["id"],
        controller_condition="GOOD",
        machine_condition="GOOD",
        door_equipment_condition="GOOD",
    )
    door_fair = submit_survey(
        second_car["id"],
        controller_condition="GOOD",
        machine_condition="GOOD",
        door_equipment_condition="FAIR",
    )

    on_boundary = get_success_data(
        api_client.get_survey_score_preview(
            all_good["id"], PM, params={"basis": "OBSERVED_ONLY"}
        )
    )
    assert on_boundary["score"] == 80.00
    assert on_boundary["recommended_scope_tier"] == "CONTROLLER_ONLY"
    assert on_boundary["observed_weight_total"] == 1.00

    below_boundary = get_success_data(
        api_client.get_survey_score_preview(
            door_fair["id"], PM, params={"basis": "OBSERVED_ONLY"}
        )
    )
    assert below_boundary["score"] == 73.75
    assert below_boundary["recommended_scope_tier"] == "CONTROLLER_DOOR"
    assert below_boundary["observed_weight_total"] == 1.00


def test_new_survey_opens_submitted_with_an_advisory_score_only():
    """The survey records the submitting technician's `X-User-ID` as
    `surveyed_by_user_id`, opens in status `SUBMITTED` with `countersigned_by_user_id`
    null, and immediately computes a provisional score.

    That provisional recommendation is advisory only and gates nothing. The survey's
    `final_score` and the car's `condition_score` and `recommended_scope_tier` all remain
    null at this point.

    Design: Corner/state_machines/equipment_survey_starts_in_submitted_with_advisory_score_only
    """
    ctx = setup_project_with_cars(num_cars=1)

    response = api_client.create_equipment_survey(
        {
            "car_id": ctx["car"]["id"],
            "controller_condition": "EXCELLENT",
            "machine_condition": "GOOD",
            "door_equipment_condition": "FAIR",
        },
        make_survey_technician_headers("tech-001"),
    )
    survey = validate_success(response, expected_status=201)

    assert survey["status"] == "SUBMITTED"
    assert survey["surveyed_by_user_id"] == "tech-001"
    assert survey["provisional_score"] == 82.75
    assert survey["recommended_scope_tier"] == "CONTROLLER_ONLY"
    assert survey["final_score"] is None
    assert survey["countersigned_by_user_id"] is None

    car = read_car(ctx["car"]["id"])
    assert car["work_status"] == "SURVEY_PENDING"
    assert car["condition_score"] is None
    assert car["recommended_scope_tier"] is None
    assert read_project(ctx["project"]["id"])["status"] == "SURVEY"


def test_countersignature_moves_survey_car_and_project_together():
    """On success the survey moves `SUBMITTED → COUNTERSIGNED`, stores the countersigning
    caller's identifier as `countersigned_by_user_id`, recomputes the composite on the
    imputed-failed basis into `final_score`, derives `recommended_scope_tier` from that
    final score, copies the final score onto the car as `condition_score` and the tier
    onto the car as `recommended_scope_tier`, advances the car
    `SURVEY_PENDING → SURVEYED` on the work dimension while leaving `compliance_status`
    untouched, moves the project `SURVEY → SCOPING` if this is the project's first
    countersignature, and increments the project's `version` by 1.

    Design: Corner/state_machines/countersign_promotes_provisional_score_and_advances_car_and_project
    """
    ctx = setup_project_with_cars(num_cars=1)
    survey = submit_survey(
        ctx["car"]["id"],
        controller_condition="GOOD",
        machine_condition="GOOD",
        door_equipment_condition="EXCELLENT",
    )
    version_before = read_project(ctx["project"]["id"])["version"]

    response = api_client.countersign_equipment_survey(
        survey["id"], make_survey_technician_headers("tech-002")
    )
    countersigned = validate_success(response)

    assert countersigned["status"] == "COUNTERSIGNED"
    assert countersigned["countersigned_by_user_id"] == "tech-002"
    assert countersigned["surveyed_by_user_id"] == "tech-001"
    assert countersigned["final_score"] == 85.00
    assert countersigned["recommended_scope_tier"] == "CONTROLLER_ONLY"

    car = read_car(ctx["car"]["id"])
    assert car["work_status"] == "SURVEYED"
    assert car["condition_score"] == 85.00
    assert car["recommended_scope_tier"] == "CONTROLLER_ONLY"
    assert car["compliance_status"] == "NOT_EVALUATED"

    project = read_project(ctx["project"]["id"])
    assert project["status"] == "SCOPING"
    assert project["version"] == version_before + 1


def test_countersigning_an_already_countersigned_survey_is_refused():
    """The survey must be in status `SUBMITTED`; countersigning a survey that is already
    `COUNTERSIGNED`, or one that has been voided, is refused with
    `ERR_SURVEY_STATE_INVALID`.

    Design: Corner/state_machines/countersigning_a_countersigned_survey_twice_is_rejected
    """
    ctx = setup_project_with_cars(num_cars=1)
    survey = submit_survey(
        ctx["car"]["id"],
        controller_condition="GOOD",
        machine_condition="GOOD",
        door_equipment_condition="EXCELLENT",
    )
    countersign_survey(survey["id"], "tech-002")
    version_after_first = read_project(ctx["project"]["id"])["version"]

    response = api_client.countersign_equipment_survey(
        survey["id"], make_survey_technician_headers("tech-003")
    )
    validate_error(response, ApiErrorId.ERR_SURVEY_STATE_INVALID, expected_status=409)

    stored = read_survey(survey["id"])
    assert stored["countersigned_by_user_id"] == "tech-002"
    assert stored["final_score"] == 85.00
    assert read_project(ctx["project"]["id"])["version"] == version_after_first
    assert read_car(ctx["car"]["id"])["work_status"] == "SURVEYED"


def test_replacement_survey_voids_the_prior_survey_and_resets_the_car():
    """When a technician submits a fresh survey for a car whose `work_status` is
    `SURVEY_PENDING` or `SURVEYED`, any prior survey of that car in status `SUBMITTED`
    or `COUNTERSIGNED` becomes `VOID`, the car's `condition_score` and
    `recommended_scope_tier` are reset to null, and the car returns to `work_status`
    `SURVEY_PENDING` — so a car whose latest survey has been voided has no score at
    all and must be countersigned afresh before it can be scoped.

    Design: Corner/state_machines/replacement_survey_voids_the_prior_survey_and_resets_the_car
    """
    ctx = setup_project_with_cars(num_cars=1)
    first = submit_survey(
        ctx["car"]["id"],
        controller_condition="GOOD",
        machine_condition="GOOD",
        door_equipment_condition="EXCELLENT",
    )
    countersign_survey(first["id"], "tech-002")

    response = api_client.create_equipment_survey(
        {
            "car_id": ctx["car"]["id"],
            "controller_condition": "FAIR",
            "machine_condition": "POOR",
            "door_equipment_condition": "GOOD",
        },
        make_survey_technician_headers("tech-004"),
    )
    replacement = validate_success(response, expected_status=201)

    assert replacement["status"] == "SUBMITTED"
    assert replacement["surveyed_by_user_id"] == "tech-004"
    assert replacement["provisional_score"] == 52.25
    assert replacement["recommended_scope_tier"] == "CONTROLLER_MACHINE"

    voided = read_survey(first["id"])
    assert voided["status"] == "VOID"
    assert voided["final_score"] == 85.00

    car = read_car(ctx["car"]["id"])
    assert car["work_status"] == "SURVEY_PENDING"
    assert car["condition_score"] is None

    rows, meta = list_equipment_surveys(car_id=ctx["car"]["id"])
    assert meta["total_count"] == 2
    statuses = sorted(row["status"] for row in rows)
    assert statuses == ["SUBMITTED", "VOID"]


def test_the_surveyor_of_record_cannot_countersign_their_own_survey():
    """Countersignature is what makes the assessment binding, and it is deliberately a
    second pair of eyes: either another `SurveyTechnician` or a `ProjectManager` may
    countersign, and the caller's `X-User-ID` must differ from the survey's
    `surveyed_by_user_id` or the request is refused with `ERR_SEGREGATION_OF_DUTIES`.

    Design: Corner/rbac/the_surveyor_of_record_cannot_countersign_their_own_survey
    """
    ctx = setup_project_with_cars(num_cars=1)
    survey = submit_survey(
        ctx["car"]["id"],
        controller_condition="EXCELLENT",
        machine_condition="GOOD",
        door_equipment_condition="FAIR",
        surveyor_user_id="tech-001",
    )

    response = api_client.countersign_equipment_survey(
        survey["id"], make_survey_technician_headers("tech-001")
    )
    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, expected_status=403)

    stored = read_survey(survey["id"])
    assert stored["status"] == "SUBMITTED"
    assert stored["countersigned_by_user_id"] is None
    assert stored["final_score"] is None
    assert stored["provisional_score"] == 82.75
    assert stored["surveyed_by_user_id"] == "tech-001"

    car = read_car(ctx["car"]["id"])
    assert car["work_status"] == "SURVEY_PENDING"
    assert car["condition_score"] is None
    assert read_project(ctx["project"]["id"])["status"] == "SURVEY"


def test_a_project_manager_may_countersign_as_the_independent_second_party():
    """Countersignature is what makes the assessment binding, and it is deliberately a
    second pair of eyes: either another `SurveyTechnician` or a `ProjectManager` may
    countersign, and the caller's `X-User-ID` must differ from the survey's
    `surveyed_by_user_id` or the request is refused with `ERR_SEGREGATION_OF_DUTIES`.

    Design: Corner/rbac/project_manager_may_countersign_as_the_second_party
    """
    ctx = setup_project_with_cars(num_cars=1)
    survey = submit_survey(
        ctx["car"]["id"],
        controller_condition="EXCELLENT",
        machine_condition="GOOD",
        door_equipment_condition="FAIR",
        surveyor_user_id="tech-001",
    )

    response = api_client.countersign_equipment_survey(
        survey["id"], make_project_manager_headers("pm-009")
    )
    countersigned = validate_success(response)

    assert countersigned["status"] == "COUNTERSIGNED"
    assert countersigned["countersigned_by_user_id"] == "pm-009"
    assert countersigned["final_score"] == 82.75

    car = read_car(ctx["car"]["id"])
    assert car["work_status"] == "SURVEYED"
    assert car["condition_score"] == 82.75
    assert car["recommended_scope_tier"] == "CONTROLLER_ONLY"
    assert read_project(ctx["project"]["id"])["status"] == "SCOPING"


def test_countersign_response_and_the_reads_that_follow_it_agree_at_once():
    """On success the survey moves `SUBMITTED → COUNTERSIGNED`, stores the countersigning
    caller's identifier as `countersigned_by_user_id`, recomputes the composite on the
    imputed-failed basis into `final_score`, derives `recommended_scope_tier` from
    that final score, copies the final score onto the car as `condition_score` and the
    tier onto the car as `recommended_scope_tier`, advances the car `SURVEY_PENDING →
    SURVEYED` on the work dimension while leaving `compliance_status` untouched, moves
    the project `SURVEY → SCOPING` if this is the project's first countersignature,
    and increments the project's `version` by 1.

    It is also available as a computed read that re-evaluates the ladder and returns
    the posture together with the three inputs that decided it — `downtime_posture`,
    `active_outage_count`, `staging_committed_sqft`, and `groups_below_floor`, the
    count of this project's groups whose `cars_in_service` has fallen below their
    `min_cars_in_service` — without writing anything.

    Design: Corner/consistency_model/countersign_response_reflects_the_new_car_and_project_state_immediately
    """
    ctx = setup_project_with_cars(num_cars=1)
    survey = submit_survey(
        ctx["car"]["id"],
        controller_condition="EXCELLENT",
        machine_condition="GOOD",
        door_equipment_condition="FAIR",
    )

    response = api_client.countersign_equipment_survey(
        survey["id"], make_survey_technician_headers("tech-002")
    )
    countersigned = validate_success(response)
    assert countersigned["status"] == "COUNTERSIGNED"
    assert countersigned["final_score"] == 82.75

    car = read_car(ctx["car"]["id"])
    assert car["work_status"] == "SURVEYED"
    assert car["condition_score"] == 82.75
    assert car["recommended_scope_tier"] == "CONTROLLER_ONLY"

    posture = read_posture(ctx["project"]["id"])
    assert posture["downtime_posture"] == "OPEN"
    assert posture["active_outage_count"] == 0
    assert posture["staging_committed_sqft"] == 0
    assert posture["groups_below_floor"] == 0

    project = read_project(ctx["project"]["id"])
    assert project["status"] == "SCOPING"
    assert project["car_count"] == 1
