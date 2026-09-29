"""Values sitting exactly on a declared threshold, where an inclusive bound and
a strict one give opposite answers.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_null,
    assert_operation_sizing,
    assert_posture,
    assert_state,
)
from test_helpers.fixtures import (
    add_budget,
    certify_plan,
    file_incident,
    register_operation,
    register_storage,
    set_clock,
    setup_scenario,
)
from test_helpers.test_users import PLANNER_HEADERS, make_operator_headers

_BOUNDARY_HERD = {
    "county": "Story",
    "animal_type": "BEEF_FEEDER",
    "manure_handling": "DRY",
    "open_lot_area_sqft": 0,
    "discharge_potential": "STORMWATER_ONLY",
    "has_conservation_plan": False,
}


def test_exactly_one_thousand_animal_units_is_large():
    """A thousand beef feeders compute to exactly 1,000.00 animal units, and the
    LARGE threshold is an inclusive lower bound.

    PRD: "The resulting `size_class` is `LARGE` when `animal_units` is at least 1,000; `MEDIUM` when `animal_units` is at least 300 but below 1,000; and `SMALL` otherwise."
    PRD: "Both thresholds are inclusive lower bounds, so an operation computing to exactly 1,000.00 animal units is `LARGE`, not `MEDIUM`."

    Design: Difficulty/boundary_precision_check/animal_units_exactly_one_thousand_is_large
    """
    operation = register_operation(
        name="Boundary Feeders A", head_count=1000, **_BOUNDARY_HERD
    )

    assert_operation_sizing(
        operation,
        animal_units=1000.00,
        size_class="LARGE",
        permit_required=True,
        design_annual_manure_gallons=3600000.00,
        daily_production_gallons=9863.01,
    )


def test_one_head_below_the_threshold_is_still_medium():
    """Nine hundred and ninety-nine head land one animal unit below the bound and
    stay MEDIUM, while coverage is still required on the stormwater pathway.

    PRD: "The operation's `animal_units` is the `head_count` multiplied by that factor, rounded half up to 2 decimal places."
    PRD: "A `MEDIUM` operation requires coverage when its `discharge_potential` is `STORMWATER_ONLY` or `CONTINUOUS`, and not when it is `NONE`."

    Design: Difficulty/boundary_precision_check/animal_units_exactly_one_thousand_is_large
    """
    operation = register_operation(
        name="Boundary Feeders B", head_count=999, **_BOUNDARY_HERD
    )

    assert_operation_sizing(
        operation,
        animal_units=999.00,
        size_class="MEDIUM",
        permit_required=True,
        design_annual_manure_gallons=3596400.00,
        daily_production_gallons=9853.15,
    )


def test_certifying_a_plan_with_no_budgets_at_all_is_refused():
    """Zero is one below the required minimum of one budget, so certification is
    refused and the plan keeps its uncertified state.

    PRD: "At least one field nutrient budget must exist for the plan, or the request is refused with `ERR_NO_FIELD_BUDGETS`."
    PRD: "Certification stamps `certifying_planner_user_id` with the acting planner's `X-User-ID` and `certified_at` with the logical clock."

    Design: Difficulty/boundary_precision_check/certify_with_zero_field_budgets_is_rejected
    """
    ctx = setup_scenario("DRAFT_PLAN")

    response = api_client.certify_nutrient_plan(ctx["plan"]["id"], PLANNER_HEADERS)
    validate_error(response, ApiErrorId.ERR_NO_FIELD_BUDGETS)
    assert response.status_code == 422, (
        f"expected HTTP 422, got {response.status_code}"
    )

    plan = validate_success(
        api_client.get_nutrient_plan(ctx["plan"]["id"], ctx["operator_headers"]), 200
    )
    assert_state(plan, "plan_status", "DRAFT")
    assert_null(plan, "certifying_planner_user_id", "certified_at")


def test_one_budget_is_enough_to_certify_the_same_plan():
    """Adding a single budget satisfies the minimum, and the storage aggregate is
    comfortably clear of the 180-day floor so that is not what was failing.

    PRD: "And the operation's `design_storage_days` must be at least 180 — a full winter-plus of storage — or the request is refused with `ERR_INSUFFICIENT_STORAGE_DAYS`."
    PRD: "Certification by a `CertifiedPlanner` advances the plan `DRAFT → CERTIFIED` and rests on three preconditions."

    Design: Difficulty/boundary_precision_check/certify_with_zero_field_budgets_is_rejected
    """
    ctx = setup_scenario("DRAFT_PLAN")

    operation = validate_success(
        api_client.get_operation(ctx["operation"]["id"], ctx["operator_headers"]), 200
    )
    assert operation["design_storage_days"] == 485, (
        f"design_storage_days: expected 485, got {operation['design_storage_days']}"
    )

    add_budget(ctx["plan"]["id"], ctx["field"]["id"], ctx["soil_test"]["id"])
    plan = certify_plan(ctx["plan"]["id"])

    assert_state(plan, "plan_status", "CERTIFIED")
    assert plan["certifying_planner_user_id"] == "planner-1", (
        f"certifying_planner_user_id: expected planner-1, "
        f"got {plan['certifying_planner_user_id']}"
    )
    assert plan["certified_at"].startswith("2026-08-01T00:00:00"), (
        f"certified_at must come from the logical clock, got {plan['certified_at']}"
    )


def test_a_discharge_that_reached_water_sets_both_notification_deadlines():
    """The report derives a 24-hour oral deadline and a 5-day written deadline
    from the moment of discovery.

    PRD: "For a `DISCHARGE` or a `SPILL`, `requires_oral_notification` is true when `reached_water` is true **or** `released_gallons` is at least 1,000."
    PRD: "When notification is required, `oral_notification_deadline_at` is 24 hours after `discovered_at` and `written_report_deadline_at` is 5 days after `discovered_at`; when it is not required, both are null."

    Design: Difficulty/boundary_precision_check/oral_notification_at_exact_deadline_is_not_late
    """
    operation = register_operation()
    operation_id = operation["id"]
    storage = register_storage(operation_id)
    set_clock("2026-08-10T06:00:00Z")

    incident = file_incident(
        operation_id,
        discovered_at="2026-08-10T06:00:00Z",
        subject_storage_id=storage["id"],
        released_gallons=1500,
        reached_water=True,
        description="Berm seepage reached the county drainage ditch",
    )

    assert incident["requires_oral_notification"] is True, (
        "a discharge that reached water always requires oral notification"
    )
    assert incident["oral_notification_deadline_at"].startswith("2026-08-11T06:00:00"), (
        f"oral_notification_deadline_at: expected 11 August 2026 06:00, "
        f"got {incident['oral_notification_deadline_at']}"
    )
    assert incident["written_report_deadline_at"].startswith("2026-08-15T06:00:00"), (
        f"written_report_deadline_at: expected 15 August 2026 06:00, "
        f"got {incident['written_report_deadline_at']}"
    )
    assert_state(incident, "incident_status", "OPEN")
    assert_null(incident, "oral_notified_at")


def test_notifying_at_exactly_the_deadline_instant_is_on_time():
    """Recording the oral notification at precisely the deadline is not late,
    because lateness is a strictly-later comparison.

    PRD: "Recording stamps `oral_notified_at` from the logical clock and sets `notification_late` to true exactly when `oral_notified_at` is strictly later than `oral_notification_deadline_at` — a notification recorded at exactly the deadline instant is on time."
    PRD: "`SUSPENDED` when `open_discharge_incident_count` is at least 1, **or** any storage structure of the operation has `storage_status` equal to `OVERFLOW_IMMINENT`."

    Design: Difficulty/boundary_precision_check/oral_notification_at_exact_deadline_is_not_late
    """
    operation = register_operation()
    operation_id = operation["id"]
    storage = register_storage(operation_id)
    set_clock("2026-08-10T06:00:00Z")
    incident = file_incident(
        operation_id,
        discovered_at="2026-08-10T06:00:00Z",
        subject_storage_id=storage["id"],
        released_gallons=1500,
        reached_water=True,
        description="Berm seepage reached the county drainage ditch",
    )

    operator_headers = make_operator_headers(operation_id)
    set_clock("2026-08-11T06:00:00Z")
    notified = validate_success(
        api_client.record_oral_notification(incident["id"], operator_headers), 200
    )

    assert notified["oral_notified_at"].startswith("2026-08-11T06:00:00"), (
        f"oral_notified_at: expected 11 August 2026 06:00, "
        f"got {notified['oral_notified_at']}"
    )
    assert notified["notification_late"] is False, (
        "a notification recorded at exactly the deadline instant is on time"
    )
    assert_state(notified, "incident_status", "NOTIFIED")

    operation = validate_success(
        api_client.get_operation(operation_id, operator_headers), 200
    )
    assert_posture(operation, "SUSPENDED", discharges=1)
