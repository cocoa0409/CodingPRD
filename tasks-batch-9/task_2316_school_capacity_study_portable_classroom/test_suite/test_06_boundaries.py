"""Inclusive boundaries: the 95.0 trigger, the 150 ft hose lay, the empty pool."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import ADMIN_HEADERS, ASSET_HEADERS, PLANNER_HEADERS
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_capacity_fields
from test_helpers.factories import condition_payload, legacy_placement_payload
from test_helpers.fixtures import (
    assess_pad,
    build_campus,
    create_request,
    create_school,
    create_site,
    create_study,
    create_unit,
    submit_study,
)

FOUR_ROOMS = (900, 900, 900, 480)


def _three_campuses_at_the_trigger(api):
    """Three identical 100-seat campuses projecting 94, 95 and 96 pupils."""
    ctx = {}
    policy_id = None
    for key, name, grade_eight in (("below", "Below Middle", 30),
                                   ("exact", "Exact Middle", 31),
                                   ("above", "Above Middle", 32)):
        campus = build_campus(
            api,
            clock="2027-03-01T00:00:00Z" if policy_id is None else None,
            policy_id=policy_id,
            budget_cents=None,
            school_overrides={"name": name, "site_acreage": 10.0,
                              "electrical_spare_capacity_kw": 40,
                              "sewer_spare_connections": 1},
            room_areas=FOUR_ROOMS,
            projections=((6, 32), (7, 32), (8, grade_eight)),
        )
        policy_id = campus["policy_id"]
        study = create_study(api, campus["school_id"], policy_id)
        ctx[f"{key}_study_id"] = study["id"]
        ctx[f"{key}_submitted"] = submit_study(api, study["id"])
    return ctx


def test_utilization_of_exactly_ninety_five_percent_trips_the_trigger_with_no_deficit(api):
    """PRD §3.3: "The portable trigger fires when `utilization_pct` reaches 95.0 or more
    — the boundary is inclusive, so a campus computing exactly 95.0 percent has
    `portable_trigger_met` true. Separately, the district's target loading is also 95
    percent of program capacity: multiply `program_capacity_seats` by 95, divide by 100,
    and take the quotient downward to a whole number to obtain the campus's effective
    capacity at target loading. When the trigger has fired, `seat_deficit` is the
    projected enrolment total reduced by that effective capacity, clamped at 0 from
    below".

    Design: Difficulty/boundary_precision_check/utilization_exactly_at_portable_trigger_percent
    """
    ctx = _three_campuses_at_the_trigger(api)

    submitted = ctx["exact_submitted"]
    assert submitted["status"] == "SUBMITTED"
    assert_capacity_fields(
        submitted,
        program_capacity_seats=100,
        projected_enrollment_total=95,
        utilization_pct=95.0,
        portable_trigger_met=True,
        seat_deficit=0,
        required_portable_count=0,
    )


def test_one_pupil_either_side_of_the_trigger_moves_the_verdict(api):
    """PRD §3.3: "`utilization_pct` is the projected enrolment total multiplied by 100,
    divided by `program_capacity_seats`, and rounded half up to one decimal place. The
    portable trigger fires when `utilization_pct` reaches 95.0 or more ... when the
    trigger has not fired, `seat_deficit` is 0. `required_portable_count` is the seat
    deficit divided by 24 — the seats a standard single-wide portable provides — with
    the quotient taken upward to the next whole number."

    Design: Difficulty/boundary_precision_check/utilization_exactly_at_portable_trigger_percent
    """
    ctx = _three_campuses_at_the_trigger(api)

    below = validate_success(
        api.get_capacity_study(ctx["below_study_id"], PLANNER_HEADERS)
    )
    assert_capacity_fields(
        below,
        program_capacity_seats=100,
        projected_enrollment_total=94,
        utilization_pct=94.0,
        portable_trigger_met=False,
        seat_deficit=0,
        required_portable_count=0,
    )

    above = validate_success(
        api.get_capacity_study(ctx["above_study_id"], PLANNER_HEADERS)
    )
    assert_capacity_fields(
        above,
        program_capacity_seats=100,
        projected_enrollment_total=96,
        utilization_pct=96.0,
        portable_trigger_met=True,
        seat_deficit=1,
        required_portable_count=1,
    )


def _four_pads_around_the_hose_lay_limit(api):
    """Three pads at 149.9, 150.0 and 150.1 ft, plus one behind a narrow lane."""
    compliant = create_school(api, name="Compliant Lane Middle", site_acreage=11.0,
                             fire_lane_clear_width_ft=20.0,
                             electrical_spare_capacity_kw=40,
                             sewer_spare_connections=1)
    narrow = create_school(api, name="Narrow Lane Middle", site_acreage=11.0,
                          fire_lane_clear_width_ft=19.9,
                          electrical_spare_capacity_kw=40,
                          sewer_spare_connections=1)
    return {
        "under_site_id": create_site(api, compliant["id"], pad_code="PAD-149",
                                     distance_to_fire_lane_ft=149.9)["id"],
        "exact_site_id": create_site(api, compliant["id"], pad_code="PAD-150",
                                     distance_to_fire_lane_ft=150.0)["id"],
        "over_site_id": create_site(api, compliant["id"], pad_code="PAD-151",
                                    distance_to_fire_lane_ft=150.1)["id"],
        "narrow_site_id": create_site(api, narrow["id"], pad_code="PAD-NARROW",
                                      distance_to_fire_lane_ft=40.0)["id"],
    }


def test_hose_lay_of_exactly_one_hundred_fifty_feet_still_assesses_feasible(api):
    """PRD §3.4: "The second step is fire access. If `distance_to_fire_lane_ft` is
    greater than 150 feet, or the campus's `fire_lane_clear_width_ft` is less than 20
    feet, the pad is judged `INFEASIBLE` with `infeasible_reason` `FIRE_ACCESS` ... Both
    boundaries are inclusive on the passing side: a hose-lay distance of exactly 150 feet
    passes, 150.1 feet fails, and a campus fire lane of exactly 20 feet of clear width
    passes." PRD §3.4 also fixes the clean verdict: "A pad that collects no flags is
    judged `FEASIBLE` ... `infeasible_reason` is set to null".

    Design: Difficulty/boundary_precision_check/fire_access_hose_lay_exactly_at_maximum_distance
    """
    pads = _four_pads_around_the_hose_lay_limit(api)

    under = assess_pad(api, pads["under_site_id"])
    assert under["feasibility_status"] == "FEASIBLE"
    assert under["infeasible_reason"] is None

    exact = assess_pad(api, pads["exact_site_id"])
    assert exact["feasibility_status"] == "FEASIBLE"
    assert exact["infeasible_reason"] is None
    assert exact["assessed_for_size_class"] == "SINGLE_24x40"
    assert exact["mitigation_flags"] == []


def test_a_tenth_of_a_foot_too_far_or_a_lane_too_narrow_is_infeasible(api):
    """PRD §3.4: "If `distance_to_fire_lane_ft` is greater than 150 feet, or the
    campus's `fire_lane_clear_width_ft` is less than 20 feet, the pad is judged
    `INFEASIBLE` with `infeasible_reason` `FIRE_ACCESS` and an empty `mitigation_flags`,
    and nothing further is evaluated." The two criteria are independent conjuncts, so
    "150.1 feet fails" and a lane narrower than 20 feet fails on its own.

    Design: Difficulty/boundary_precision_check/fire_access_hose_lay_exactly_at_maximum_distance
    """
    pads = _four_pads_around_the_hose_lay_limit(api)

    over = assess_pad(api, pads["over_site_id"])
    assert over["feasibility_status"] == "INFEASIBLE"
    assert over["infeasible_reason"] == "FIRE_ACCESS"
    assert over["mitigation_flags"] == []

    narrow = assess_pad(api, pads["narrow_site_id"])
    assert narrow["feasibility_status"] == "INFEASIBLE"
    assert narrow["infeasible_reason"] == "FIRE_ACCESS"
    assert narrow["mitigation_flags"] == []


def _request_with_no_eligible_unit(api):
    """A unitless request beside four portables, each excluded by one filter."""
    ctx = build_campus(api, school_overrides={"name": "Elmwood Middle",
                                              "site_acreage": 10.0})
    ctx["target_site_id"] = create_site(api, ctx["school_id"],
                                        pad_code="PAD-TARGET")["id"]
    ctx["legacy_site_id"] = create_site(api, ctx["school_id"],
                                        pad_code="PAD-LEGACY")["id"]

    ctx["grade_d_unit_id"] = create_unit(api, asset_tag="PU-D001",
                                        condition_grade="D",
                                        in_service_year=2009)["id"]
    unsafe = create_unit(api, asset_tag="PU-U001")
    validate_success(
        api.record_condition(unsafe["id"], condition_payload("UNSAFE", "B"),
                             ASSET_HEADERS)
    )
    ctx["unsafe_unit_id"] = unsafe["id"]

    installed = create_unit(api, asset_tag="PU-I001", condition_grade="A",
                           in_service_year=2022)
    validate_success(
        api.record_existing_placement(
            installed["id"],
            legacy_placement_payload(ctx["school_id"], ctx["legacy_site_id"]),
            ASSET_HEADERS,
        )
    )
    ctx["installed_unit_id"] = installed["id"]
    ctx["oversize_unit_id"] = create_unit(api, asset_tag="PU-T001",
                                         size_class="TRIPLE_36x64",
                                         condition_grade="A",
                                         acquisition_cost_cents=22_000_000,
                                         in_service_year=2022)["id"]

    study = create_study(api, ctx["school_id"], ctx["policy_id"])
    submit_study(api, study["id"])
    ctx["study_id"] = study["id"]

    ctx["request_id"] = create_request(
        api, study["id"], ctx["target_site_id"], ctx["budget_id"], haul_miles=10,
    )["id"]
    return ctx


def test_auto_assignment_refuses_an_empty_candidate_pool(api):
    """PRD §3.5: "The candidate pool is every portable in the district whose
    `allocation_status` is `IN_STORAGE`, whose `condition_status` is `SERVICEABLE`, whose
    `condition_grade` is `A`, `B` or `C`, whose `lifetime_relocation_count` is strictly
    less than 4, whose `rated_seats` is at least 24, and whose chassis fits the request's
    pad — that is, the chassis length plus 10 feet is at most `pad_length_ft` and the
    chassis width plus 10 feet is at most `pad_width_ft`. ... If the pool is empty the
    operation fails with `ERR_NO_ELIGIBLE_UNIT`."

    Design: Difficulty/boundary_precision_check/empty_eligible_unit_pool_at_auto_assign
    """
    ctx = _request_with_no_eligible_unit(api)

    response = api.auto_assign_unit(ctx["request_id"], {}, PLANNER_HEADERS)
    validate_error(response, ApiErrorId.NO_ELIGIBLE_UNIT, expected_status=409)

    request = validate_success(
        api.get_placement_request(ctx["request_id"], PLANNER_HEADERS)
    )
    assert request["status"] == "DRAFT"
    assert request["portable_unit_id"] is None

    assert validate_success(
        api.get_portable_unit(ctx["grade_d_unit_id"], PLANNER_HEADERS)
    )["allocation_status"] == "IN_STORAGE"


def test_a_single_eligible_portable_is_selected_and_reserved(api):
    """PRD §3.5: "On success the selected unit is reserved by the same `IN_STORAGE →
    RESERVED` move, `estimated_relocation_cost_cents` and `cost_recommendation` are
    recomputed against the newly known chassis, and the request's `version` is
    incremented by 1."

    Design: Difficulty/boundary_precision_check/empty_eligible_unit_pool_at_auto_assign
    """
    ctx = _request_with_no_eligible_unit(api)
    eligible_id = create_unit(api, asset_tag="PU-E001")["id"]

    assigned = validate_success(
        api.auto_assign_unit(ctx["request_id"], {}, PLANNER_HEADERS)
    )
    assert assigned["portable_unit_id"] == eligible_id

    assert validate_success(
        api.get_portable_unit(eligible_id, PLANNER_HEADERS)
    )["allocation_status"] == "RESERVED"


def test_condition_grade_breaks_the_relocation_cost_tie(api):
    """PRD §3.5: "Candidates are then ranked by `accumulated_relocation_cost_cents`
    ascending, so the least-moved-around asset in the fleet is preferred; ties are broken
    by condition grade in the order `A` before `B` before `C`; remaining ties are broken
    by `rated_seats` descending; and the final tie-break is `created_at` ascending. The
    first candidate wins."

    Design: Difficulty/boundary_precision_check/empty_eligible_unit_pool_at_auto_assign
    """
    ctx = _request_with_no_eligible_unit(api)
    grade_b_id = create_unit(api, asset_tag="PU-E001")["id"]
    grade_a_id = create_unit(api, asset_tag="PU-A001", condition_grade="A")["id"]

    assigned = validate_success(
        api.auto_assign_unit(ctx["request_id"], {}, PLANNER_HEADERS)
    )
    assert assigned["portable_unit_id"] == grade_a_id
    assert assigned["portable_unit_id"] != grade_b_id

    assert validate_success(
        api.get_portable_unit(grade_b_id, ADMIN_HEADERS)
    )["allocation_status"] == "IN_STORAGE"
