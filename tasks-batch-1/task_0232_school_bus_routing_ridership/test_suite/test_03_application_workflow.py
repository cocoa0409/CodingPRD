"""Ridership application workflow: the revision cycle, the approval cascade, the
capacity gauntlet, and decision lifecycle guards.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    setup_application_under_review,
    setup_approved_rider,
    create_district_payload,
    create_route_payload,
    create_stop_payload,
    create_student_payload,
    create_application_payload,
    make_admin_headers,
    make_parent_headers,
)

ADMIN = make_admin_headers()


# ===========================================================================
# Difficulty/non_linear_state_machine/ridership_application_revision_cycle_loop
# ===========================================================================
def test_revision_cycle_increments_review_round_each_resubmit(api):
    """PRD §3.3: "The owning `Parent` may then resubmit, returning the application from `CHANGES_REQUESTED` to `UNDER_REVIEW... Resubmission increments `review_round` by one... This forms a cyclic revision loop: an application may bounce between `UNDER_REVIEW` and `CHANGES_REQUESTED` any number of times before it is decided."

    Design: Difficulty/non_linear_state_machine/ridership_application_revision_cycle_loop
    """
    _, _, _, student, application = setup_application_under_review(
        district_overrides={"school_lat": 40.0, "school_lng": -75.0},
        route_overrides={"seat_capacity": 10},
        student_overrides={"home_lat": 40.05, "home_lng": -75.0},
        parent_id="par-1",
        rfid_uid="RF-1",
    )
    par = make_parent_headers("par-1")
    # Round 1: request-changes -> resubmit.
    get_success_data(api.request_changes(application["id"], ADMIN))
    get_success_data(api.resubmit_application(application["id"], {}, par))
    # Round 2: request-changes -> resubmit.
    get_success_data(api.request_changes(application["id"], ADMIN))
    final = validate_success(
        api.resubmit_application(application["id"], {}, par), 200
    )
    assert final["status"] == "UNDER_REVIEW", (
        "after the second resubmit the application is back UNDER_REVIEW"
    )
    assert final["review_round"] == 2, (
        f"review_round increments on each resubmit (0->1->2), got {final['review_round']}"
    )


def test_request_changes_moves_to_changes_requested(api):
    """PRD §3.3: "From `UNDER_REVIEW` the admin may request changes, moving the application to `CHANGES_REQUESTED`; this is legal only from `UNDER_REVIEW` and has no further side effect."

    Design: Difficulty/non_linear_state_machine/ridership_application_revision_cycle_loop
    """
    _, _, _, student, application = setup_application_under_review(
        district_overrides={"school_lat": 40.0, "school_lng": -75.0},
        route_overrides={"seat_capacity": 10},
        rfid_uid="RF-CC",
    )
    changed = validate_success(api.request_changes(application["id"], ADMIN), 200)
    assert changed["status"] == "CHANGES_REQUESTED"
    assert changed["review_round"] == 0, "request-changes has no review_round side effect"


# ===========================================================================
# Difficulty/transitive_cascade/approve_cascades_route_rider_count_recompute
# ===========================================================================
def test_approve_cascades_rider_and_wheelchair_counts(api):
    """PRD §3.4: "The target route's `assigned_rider_count` is recomputed and rises by one, and if the student is special-needs the route's `assigned_wheelchair_count` is likewise recomputed and rises by one."
    PRD §3.4: "The system sets `assigned_route_id` equal to `requested_route_id` and `assigned_stop_id` equal to `requested_stop_id`, both captured at approval time."

    Design: Difficulty/transitive_cascade/approve_cascades_route_rider_count_recompute
    """
    _, route, _, student, application = setup_application_under_review(
        district_overrides={
            "school_lat": 40.0, "school_lng": -75.0, "walk_threshold_miles": 1.5,
        },
        route_overrides={"seat_capacity": 10, "wheelchair_capacity": 2},
        student_overrides={
            "full_name": "WC Kid", "grade": 6,
            "home_lat": 40.05, "home_lng": -75.0, "special_needs": True,
        },
        rfid_uid="RF-WC",
    )
    approved = validate_success(api.approve_application(application["id"], ADMIN), 200)
    assert approved["assigned_route_id"] == route["id"]

    refreshed = validate_success(api.get_route(route["id"], ADMIN), 200)
    assert refreshed["assigned_rider_count"] == 1, (
        "assigned_rider_count recomputes +1 from the approval"
    )
    assert refreshed["assigned_wheelchair_count"] == 1, (
        "special_needs cascade raises assigned_wheelchair_count by 1"
    )


def test_approve_non_special_needs_leaves_wheelchair_count_zero(api):
    """PRD §3.4: "if the student is special-needs the route's `assigned_wheelchair_count` is likewise recomputed and rises by one."

    Design: Difficulty/transitive_cascade/approve_cascades_route_rider_count_recompute
    """
    _, route, _, student, application = setup_application_under_review(
        district_overrides={
            "school_lat": 40.0, "school_lng": -75.0, "walk_threshold_miles": 1.5,
        },
        route_overrides={"seat_capacity": 10, "wheelchair_capacity": 2},
        student_overrides={"home_lat": 40.05, "home_lng": -75.0},
        rfid_uid="RF-NSN",
    )
    validate_success(api.approve_application(application["id"], ADMIN), 200)
    refreshed = validate_success(api.get_route(route["id"], ADMIN), 200)
    assert refreshed["assigned_rider_count"] == 1
    assert refreshed["assigned_wheelchair_count"] == 0, (
        "a non-special-needs approval does not raise assigned_wheelchair_count"
    )


# ===========================================================================
# Corner/consistency_model/approve_immediately_reflects_in_route_read
# ===========================================================================
def test_approve_immediately_reflects_in_route_read(api):
    """PRD §2.5: "every secondary effect is applied synchronously within that same
    operation... In every case the recomputation happens at the moment of the
    triggering event, never lazily."

    Design: Corner/consistency_model/approve_immediately_reflects_in_route_read
    """
    _, route, _, student, application = setup_application_under_review(
        district_overrides={
            "school_lat": 40.0, "school_lng": -75.0, "walk_threshold_miles": 1.5,
        },
        route_overrides={"seat_capacity": 10},
        student_overrides={"home_lat": 40.05, "home_lng": -75.0},
        rfid_uid="RF-IMM",
    )
    validate_success(api.approve_application(application["id"], ADMIN), 200)
    refreshed = validate_success(api.get_route(route["id"], ADMIN), 200)
    assert refreshed["assigned_rider_count"] == 1, (
        "assigned_rider_count is visible immediately after approve (no lag)"
    )


# ===========================================================================
# Corner/state_machines/approve_from_submitted_without_review_returns_invalid_state
# ===========================================================================
def test_approve_from_submitted_returns_invalid_state(api):
    """PRD §3.4: "It is legal only from `UNDER_REVIEW`; attempting it from any other status yields `ERR_INVALID_STATE`."

    Design: Corner/state_machines/approve_from_submitted_without_review_returns_invalid_state
    """
    district = get_success_data(api.create_district(
        create_district_payload(school_lat=40.0, school_lng=-75.0,
                                walk_threshold_miles=1.5), ADMIN))
    route = get_success_data(api.create_route(
        create_route_payload(district["id"], seat_capacity=10), ADMIN))
    stop = get_success_data(api.create_stop(
        create_stop_payload(route["id"], 1, "2026-09-01T07:00:00Z"), ADMIN))
    student = get_success_data(api.create_student(
        create_student_payload(district["id"], "par-1", "RF-1",
                               home_lat=40.05, home_lng=-75.0), ADMIN))
    app = get_success_data(api.create_application(
        create_application_payload(district["id"], student["id"],
                                   route["id"], stop["id"]), ADMIN))
    # SUBMITTED, never reviewed.
    res = api.approve_application(app["id"], ADMIN)
    validate_error(res, "ERR_INVALID_STATE", 409)


# ===========================================================================
# Corner/state_machines/withdraw_already_approved_returns_invalid_state
# ===========================================================================
def test_withdraw_approved_application_returns_invalid_state(api):
    """PRD §3.3: "The statuses `APPROVED`, `DENIED`, and `WITHDRAWN` are terminal."
    PRD §3.3: "A parent may also `WITHDRAW` their own application: withdrawal is legal from `SUBMITTED` and from `CHANGES_REQUESTED`, requires the acting parent to own the student, and moves the application to `WITHDRAWN` with no further effect."

    Design: Corner/state_machines/withdraw_already_approved_returns_invalid_state
    """
    _, _, _, student, application = setup_approved_rider(
        district_overrides={
            "school_lat": 40.0, "school_lng": -75.0, "walk_threshold_miles": 1.5,
        },
        route_overrides={"seat_capacity": 10},
        student_overrides={"home_lat": 40.05, "home_lng": -75.0},
        parent_id="par-1",
        rfid_uid="RF-1",
    )
    par = make_parent_headers("par-1")
    res = api.withdraw_application(application["id"], par)
    validate_error(res, "ERR_INVALID_STATE", 409)


# ===========================================================================
# Corner/validations/approve_ineligible_none_returns_not_eligible
# ===========================================================================
def test_approve_ineligible_none_returns_not_eligible(api):
    """PRD §3.4: "First, the applicant must be eligible: the `eligibility_basis` must be either `DISTANCE` or `HAZARD`. If it is `NONE`, approval is rejected with `ERR_NOT_ELIGIBLE`."

    Design: Corner/validations/approve_ineligible_none_returns_not_eligible
    """
    _, _, _, student, application = setup_application_under_review(
        district_overrides={
            "school_lat": 40.0, "school_lng": -75.0,
            "walk_threshold_miles": 1.5, "hazard_override_enabled": False,
        },
        route_overrides={"seat_capacity": 10},
        student_overrides={"home_lat": 40.01, "home_lng": -75.0},
        rfid_uid="RF-N",
    )
    assert application["eligibility_basis"] == "NONE"
    res = api.approve_application(application["id"], ADMIN)
    validate_error(res, "ERR_NOT_ELIGIBLE", 409)


# ===========================================================================
# Corner/validations/approve_special_needs_wheelchair_full_returns_wheelchair_full
# ===========================================================================
def test_approve_special_needs_wheelchair_full_returns_wheelchair_full(api):
    """PRD §3.4: "and only when the subject student has `special_needs` set to true, the route must also have a free securement position: its `assigned_wheelchair_count` must be strictly less than its `wheelchair_capacity`; if not, approval is rejected with `ERR_WHEELCHAIR_FULL`."

    Design: Corner/validations/approve_special_needs_wheelchair_full_returns_wheelchair_full
    """
    _, _, _, student, application = setup_application_under_review(
        district_overrides={
            "school_lat": 40.0, "school_lng": -75.0, "walk_threshold_miles": 1.5,
        },
        route_overrides={"seat_capacity": 10, "wheelchair_capacity": 0},
        student_overrides={
            "full_name": "WC", "grade": 4,
            "home_lat": 40.05, "home_lng": -75.0, "special_needs": True,
        },
        rfid_uid="RF-WC",
    )
    assert application["eligibility_basis"] == "DISTANCE"
    res = api.approve_application(application["id"], ADMIN)
    validate_error(res, "ERR_WHEELCHAIR_FULL", 409)


# ===========================================================================
# Corner/cross_cutting_complexity_layers/rate_threshold_route_full_at_capacity_boundary
# ===========================================================================
def test_route_full_at_seat_capacity_boundary(api):
    """PRD §3.4: "Third, the route must have a free seat: its `assigned_rider_count` must be strictly less than its `seat_capacity`; if the count has reached capacity, approval is rejected with `ERR_ROUTE_FULL`."

    Design: Corner/cross_cutting_complexity_layers/rate_threshold_route_full_at_capacity_boundary
    """
    district = get_success_data(api.create_district(
        create_district_payload(school_lat=40.0, school_lng=-75.0,
                                walk_threshold_miles=1.5), ADMIN))
    route = get_success_data(api.create_route(
        create_route_payload(district["id"], seat_capacity=1), ADMIN))
    stop = get_success_data(api.create_stop(
        create_stop_payload(route["id"], 1, "2026-09-01T07:00:00Z"), ADMIN))
    # Rider A: approved -> count 1 == capacity (the first approval at 0 < 1 succeeds).
    stu_a = get_success_data(api.create_student(
        create_student_payload(district["id"], "par-1", "RF-A",
                               home_lat=40.05, home_lng=-75.0), ADMIN))
    app_a = get_success_data(api.create_application(
        create_application_payload(district["id"], stu_a["id"],
                                   route["id"], stop["id"]), ADMIN))
    get_success_data(api.start_review(app_a["id"], ADMIN))
    validate_success(api.approve_application(app_a["id"], ADMIN), 200)
    # Rider B: eligible, UNDER_REVIEW -> rejected ERR_ROUTE_FULL.
    stu_b = get_success_data(api.create_student(
        create_student_payload(district["id"], "par-2", "RF-B",
                               home_lat=40.06, home_lng=-75.0, grade=6), ADMIN))
    app_b = get_success_data(api.create_application(
        create_application_payload(district["id"], stu_b["id"],
                                   route["id"], stop["id"]), ADMIN))
    get_success_data(api.start_review(app_b["id"], ADMIN))
    res = api.approve_application(app_b["id"], ADMIN)
    validate_error(res, "ERR_ROUTE_FULL", 409)
