"""Distance (haversine) and ridership eligibility determination.

Covers the home_distance_haversine and eligibility_determination calculations and
the strict-greater-than distance boundary.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    create_district_payload,
    create_student_payload,
    create_route_payload,
    create_stop_payload,
    create_application_payload,
    setup_district_route_stop,
    setup_application_under_review,
    make_admin_headers,
)

ADMIN = make_admin_headers()


# ===========================================================================
# Difficulty/combinatorial_formula/haversine_four_input_nonlinear_distance
# ===========================================================================
def test_home_distance_haversine_far_student(api):
    """PRD §3.2: "Using an Earth radius of 3958.7613 miles, the system takes the
    difference between the home and school latitudes and the difference between the
    home and school longitudes, both converted to radians; forms the haversine term
    as the square of the sine of half the latitude difference plus the product of
    the cosine of the home latitude, the cosine of the school latitude, and the
    square of the sine of half the longitude difference; takes twice the arcsine of
    the square root of that term as the central angle; multiplies the central angle
    by the Earth radius to obtain the distance in miles; and rounds that distance
    half-up to two decimal places."

    Design: Difficulty/combinatorial_formula/haversine_four_input_nonlinear_distance
    """
    district = get_success_data(
        api.create_district(
            create_district_payload(school_lat=40.0, school_lng=-75.0), ADMIN
        )
    )
    res = api.create_student(
        create_student_payload(
            district["id"], "par-1", "RF-1", full_name="Kid", grade=4,
            home_lat=40.05, home_lng=-75.0,
        ),
        ADMIN,
    )
    student = validate_success(res, 201)
    assert student["home_distance_miles"] == 3.45, (
        f"home (40.05,-75.0) vs school (40.0,-75.0) must be 3.45 mi, "
        f"got {student['home_distance_miles']}"
    )


def test_home_distance_haversine_near_student(api):
    """PRD §3.2: "multiplies the central angle by the Earth radius to obtain the
    distance in miles; and rounds that distance half-up to two decimal places.
    This value is stored on the student and is the sole distance input to
    eligibility."

    Design: Difficulty/combinatorial_formula/haversine_four_input_nonlinear_distance
    """
    district = get_success_data(
        api.create_district(
            create_district_payload(school_lat=40.0, school_lng=-75.0), ADMIN
        )
    )
    res = api.create_student(
        create_student_payload(
            district["id"], "par-1", "RF-N", full_name="Near Kid", grade=3,
            home_lat=40.01, home_lng=-75.0,
        ),
        ADMIN,
    )
    student = validate_success(res, 201)
    assert student["home_distance_miles"] == 0.69, (
        f"home (40.01,-75.0) vs school (40.0,-75.0) must be 0.69 mi, "
        f"got {student['home_distance_miles']}"
    )


# ===========================================================================
# Difficulty/combinatorial_formula/eligibility_round_then_compare_boundary_order
# ===========================================================================
def test_eligibility_rounds_distance_before_comparing_to_threshold(api):
    """PRD §3.2: "If the distance is strictly greater than the threshold, the application's `eligibility_basis` is `DISTANCE`."
    PRD §2.9: "Eligibility comparisons are performed against the two-decimal-place `home_distance_miles` value as already stored."

    Design: Difficulty/combinatorial_formula/eligibility_round_then_compare_boundary_order
    """
    district = get_success_data(
        api.create_district(
            create_district_payload(
                school_lat=40.0, school_lng=-75.0,
                walk_threshold_miles=1.5, hazard_override_enabled=True,
            ),
            ADMIN,
        )
    )
    route = get_success_data(
        api.create_route(create_route_payload(district["id"], seat_capacity=10), ADMIN)
    )
    stop = get_success_data(
        api.create_stop(
            create_stop_payload(route["id"], 1, "2026-09-01T07:00:00Z"), ADMIN
        )
    )
    student = get_success_data(
        api.create_student(
            create_student_payload(
                district["id"], "par-1", "RF-EDGE", full_name="Edge Kid", grade=2,
                home_lat=40.02171, home_lng=-75.0, hazard_zone=False,
            ),
            ADMIN,
        )
    )
    # Raw 1.50002 mi rounds to the stored 1.50.
    assert student["home_distance_miles"] == 1.5
    app = get_success_data(
        api.create_application(
            create_application_payload(
                district["id"], student["id"], route["id"], stop["id"]
            ),
            ADMIN,
        )
    )
    reviewed = validate_success(api.start_review(app["id"], ADMIN), 200)
    # 1.50 > 1.50 is false -> not DISTANCE; hazard_zone false -> NONE.
    assert reviewed["eligibility_basis"] == "NONE", (
        "round-then-compare: stored 1.50 is not strictly > threshold 1.50, "
        f"basis must be NONE, got {reviewed['eligibility_basis']}"
    )


def test_eligibility_round_then_compare_distance_stored_value(api):
    """PRD §2.9: "Eligibility comparisons are performed against the two-decimal-place `home_distance_miles` value as already stored."

    Design: Difficulty/combinatorial_formula/eligibility_round_then_compare_boundary_order
    """
    _, _, _, student, application = setup_application_under_review(
        district_overrides={
            "school_lat": 40.0, "school_lng": -75.0,
            "walk_threshold_miles": 1.5, "hazard_override_enabled": True,
        },
        route_overrides={"seat_capacity": 10},
        student_overrides={
            "full_name": "Edge Kid", "grade": 2,
            "home_lat": 40.02171, "home_lng": -75.0, "hazard_zone": False,
        },
        rfid_uid="RF-EDGE2",
    )
    assert student["home_distance_miles"] == 1.5
    assert application["eligibility_basis"] == "NONE"


# ===========================================================================
# Difficulty/dual_variant_calc/eligibility_distance_vs_hazard_basis_diverge
# ===========================================================================
def test_eligibility_distance_basis_for_far_student(api):
    """PRD §3.2: "If the distance is strictly greater than the threshold, the application's `eligibility_basis` is `DISTANCE`."

    Design: Difficulty/dual_variant_calc/eligibility_distance_vs_hazard_basis_diverge
    """
    _, _, _, student, application = setup_application_under_review(
        district_overrides={
            "school_lat": 40.0, "school_lng": -75.0,
            "walk_threshold_miles": 1.5, "hazard_override_enabled": True,
        },
        route_overrides={"seat_capacity": 20},
        student_overrides={
            "full_name": "Far Kid", "grade": 5,
            "home_lat": 40.05, "home_lng": -75.0,
        },
        parent_id="par-1",
        rfid_uid="RF-FAR",
    )
    assert student["home_distance_miles"] == 3.45
    assert application["eligibility_basis"] == "DISTANCE", (
        f"3.45 > 1.5 must yield DISTANCE, got {application['eligibility_basis']}"
    )


def test_eligibility_hazard_basis_for_near_hazard_student(api):
    """PRD §3.2: "Otherwise, if the district's `hazard_override_enabled` is true and the student's `hazard_zone` is true, the basis is `HAZARD`."

    Design: Difficulty/dual_variant_calc/eligibility_distance_vs_hazard_basis_diverge
    """
    _, _, _, student, application = setup_application_under_review(
        district_overrides={
            "school_lat": 40.0, "school_lng": -75.0,
            "walk_threshold_miles": 1.5, "hazard_override_enabled": True,
        },
        route_overrides={"seat_capacity": 20},
        student_overrides={
            "full_name": "Near Kid", "grade": 3,
            "home_lat": 40.01, "home_lng": -75.0, "hazard_zone": True,
        },
        parent_id="par-1",
        rfid_uid="RF-NEAR",
    )
    assert student["home_distance_miles"] == 0.69
    assert application["eligibility_basis"] == "HAZARD", (
        f"near (0.69) hazard_zone student must be HAZARD, got "
        f"{application['eligibility_basis']}"
    )


# ===========================================================================
# Difficulty/boundary_precision_check/eligibility_distance_strict_gt_at_threshold
# ===========================================================================
def test_eligibility_strict_gt_at_threshold_is_none(api):
    """PRD §3.2: "a student whose distance exactly equals the threshold is not distance-eligible — the comparison is strictly greater-than, not greater-than-or-equal — and so falls through to the hazard test, becoming `HAZARD` only if override is enabled and the home is in a hazard zone, and `NONE` otherwise."

    Design: Difficulty/boundary_precision_check/eligibility_distance_strict_gt_at_threshold
    """
    _, _, _, student, application = setup_application_under_review(
        district_overrides={
            "school_lat": 40.0, "school_lng": -75.0, "walk_threshold_miles": 1.5,
        },
        route_overrides={"seat_capacity": 10},
        student_overrides={
            "full_name": "Edge", "grade": 4,
            "home_lat": 40.02171, "home_lng": -75.0, "hazard_zone": False,
        },
        rfid_uid="RF-E",
    )
    assert student["home_distance_miles"] == 1.5
    assert application["eligibility_basis"] == "NONE", (
        "1.50 > 1.50 is false (strict gt), non-hazard => NONE"
    )


def test_eligibility_just_above_threshold_is_distance(api):
    """PRD §3.2: "Let the student's stored `home_distance_miles` be the distance and the district's `walk_threshold_miles` be the threshold. If the distance is strictly greater than the threshold, the application's `eligibility_basis` is `DISTANCE`."

    Design: Difficulty/boundary_precision_check/eligibility_distance_strict_gt_at_threshold
    """
    # Far student (3.45) sits clearly above the 1.5 threshold -> DISTANCE,
    # the X+1 side of the strict-gt boundary.
    _, _, _, student, application = setup_application_under_review(
        district_overrides={
            "school_lat": 40.0, "school_lng": -75.0, "walk_threshold_miles": 1.5,
        },
        route_overrides={"seat_capacity": 10},
        student_overrides={
            "full_name": "Above", "grade": 4, "home_lat": 40.05, "home_lng": -75.0,
        },
        rfid_uid="RF-ABOVE",
    )
    assert student["home_distance_miles"] == 3.45
    assert application["eligibility_basis"] == "DISTANCE"


# ===========================================================================
# Corner/calculations/eligibility_hazard_disabled_makes_near_student_none
# ===========================================================================
def test_eligibility_hazard_disabled_makes_near_student_none(api):
    """PRD §3.2: "When `hazard_override_enabled` is false, hazard is ignored entirely and only distance counts."

    Design: Corner/calculations/eligibility_hazard_disabled_makes_near_student_none
    """
    _, _, _, student, application = setup_application_under_review(
        district_overrides={
            "school_lat": 40.0, "school_lng": -75.0,
            "walk_threshold_miles": 1.5, "hazard_override_enabled": False,
        },
        route_overrides={"seat_capacity": 10},
        student_overrides={
            "full_name": "Near Haz", "grade": 3,
            "home_lat": 40.01, "home_lng": -75.0, "hazard_zone": True,
        },
        rfid_uid="RF-NH",
    )
    assert student["home_distance_miles"] == 0.69
    assert application["eligibility_basis"] == "NONE", (
        "override disabled => hazard ignored => NONE"
    )


# ===========================================================================
# Corner/entities/student_home_distance_is_computed_input_ignored
# ===========================================================================
def test_student_home_distance_is_computed_not_input(api):
    """PRD §3.2: "At the moment a student is created, the system computes `home_distance_miles`: the great-circle straight-line distance from the student's home to the district campus."

    Design: Corner/entities/student_home_distance_is_computed_input_ignored
    """
    district = get_success_data(
        api.create_district(
            create_district_payload(school_lat=40.0, school_lng=-75.0), ADMIN
        )
    )
    payload = create_student_payload(
        district["id"], "par-1", "RF-1", full_name="Kid", grade=4,
        home_lat=40.05, home_lng=-75.0,
    )
    # A client-supplied distance must be ignored by the server-side computation.
    payload["home_distance_miles"] = 999.0
    student = validate_success(api.create_student(payload, ADMIN), 201)
    assert student["home_distance_miles"] == 3.45, (
        "home_distance_miles is server-computed; client value must be ignored"
    )
