"""Study and unit state machines: openings, guarded moves and terminal locks."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    ADMIN_HEADERS,
    ASSET_HEADERS,
    CERTIFIER_HEADERS,
    PLANNER_HEADERS,
    TEST_USERS,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_capacity_fields, assert_clock_stamp
from test_helpers.factories import condition_payload, room_payload
from test_helpers.fixtures import (
    assess_pad,
    build_campus,
    certify_study,
    create_request,
    create_site,
    create_study,
    create_unit,
    submit_study,
)

CLOCK = "2027-03-01T00:00:00Z"
NORTHSIDE = {"name": "Northside Middle", "site_acreage": 10.0,
             "electrical_spare_capacity_kw": 40, "sewer_spare_connections": 1}


def test_a_new_study_opens_in_draft_with_every_computed_field_at_its_default(api):
    """PRD §3.2: "A new study opens in `DRAFT` with `revision_round` at 0, with
    `authored_by_user_id` stamped from the acting `X-User-ID`, with `certified_by_user_id`
    and `certified_on` null, and with all seven computed capacity and utilization fields
    at their defaults." PRD §3.1: a campus's "`certified_study_id` begins as null".

    Design: Corner/state_machines/capacity_study_starts_in_draft_with_zeroed_metrics
    """
    ctx = build_campus(api, clock=CLOCK, school_overrides=NORTHSIDE,
                       room_areas=(), projections=(), budget_cents=None)

    study = create_study(api, ctx["school_id"], ctx["policy_id"])
    assert study["status"] == "DRAFT"
    assert study["revision_round"] == 0
    assert study["authored_by_user_id"] == TEST_USERS["FacilitiesPlanner"]
    assert study["certified_by_user_id"] is None
    assert study["certified_on"] is None
    assert_capacity_fields(
        study,
        gross_room_seats=0,
        set_aside_deduction_seats=0,
        program_capacity_seats=0,
        projected_enrollment_total=0,
        utilization_pct=0,
        portable_trigger_met=False,
        seat_deficit=0,
        required_portable_count=0,
    )
    assert validate_success(
        api.get_school(ctx["school_id"], PLANNER_HEADERS)
    )["certified_study_id"] is None


def _northside_with_a_draft_study(api):
    ctx = build_campus(api, clock=CLOCK, school_overrides=NORTHSIDE)
    ctx["study_id"] = create_study(api, ctx["school_id"], ctx["policy_id"])["id"]
    return ctx


def test_submission_freezes_the_whole_capacity_and_utilization_computation(api):
    """PRD §3.3: "On success the server runs both computations and freezes
    `gross_room_seats`, `set_aside_deduction_seats`, `program_capacity_seats`,
    `projected_enrollment_total`, `utilization_pct`, `portable_trigger_met`,
    `seat_deficit` and `required_portable_count` onto the study, and increments the study's
    `version` by 1." PRD §3.2: "take the room's `area_sqft`, divide it by the policy's
    `min_area_sqft_per_seat`, take the quotient downward to a whole number, and then take
    the smaller of that figure and the policy's `max_class_size`".

    Design: Corner/state_machines/capacity_study_submit_computes_capacity_and_moves_to_submitted
    """
    ctx = _northside_with_a_draft_study(api)

    submitted = validate_success(api.submit_study(ctx["study_id"], {}, PLANNER_HEADERS))
    assert submitted["status"] == "SUBMITTED"
    assert_capacity_fields(
        submitted,
        gross_room_seats=56,
        set_aside_deduction_seats=0,
        program_capacity_seats=56,
        projected_enrollment_total=60,
        utilization_pct=107.1,
        portable_trigger_met=True,
        seat_deficit=7,
        required_portable_count=1,
    )
    assert submitted["revision_round"] == 0
    assert submitted["version"] == 2


def test_certification_stamps_the_certifier_and_repoints_the_campus(api):
    """PRD §3.3: "It stamps `certified_by_user_id` from the acting `X-User-ID` and
    `certified_on` from the logical clock ... And because the governing study has changed,
    the campus's `certified_study_id` is repointed to the newly certified study and its
    `reliance_flag` is recomputed."

    Design: Corner/state_machines/capacity_study_certify_stamps_certifier_and_publishes_to_campus
    """
    ctx = _northside_with_a_draft_study(api)
    submit_study(api, ctx["study_id"])

    certified = validate_success(
        api.certify_study(ctx["study_id"], {}, CERTIFIER_HEADERS)
    )
    assert certified["status"] == "CERTIFIED"
    assert certified["certified_by_user_id"] == TEST_USERS["CapacityCertifier"]
    assert_clock_stamp(certified["certified_on"], CLOCK)
    assert certified["authored_by_user_id"] == TEST_USERS["FacilitiesPlanner"]
    assert certified["program_capacity_seats"] == 56
    assert certified["seat_deficit"] == 7
    assert certified["required_portable_count"] == 1

    assert validate_success(
        api.get_school(ctx["school_id"], PLANNER_HEADERS)
    )["certified_study_id"] == ctx["study_id"]


def test_a_draft_study_can_be_neither_reopened_certified_nor_returned(api):
    """PRD §3.3: "A `FacilitiesPlanner` reopens a study in `RETURNED`", "**Certification**
    is performed by a `CapacityCertifier` on a study in `SUBMITTED`" and "A
    `CapacityCertifier` returns a `SUBMITTED` study". PRD §2.6 rule 10: "The target row is
    in a state from which the requested transition is declared — `ERR_STUDY_STATE_INVALID`
    ... 409, on every action endpoint."

    Design: Corner/state_machines/capacity_study_reopen_from_draft_rejected
    """
    ctx = build_campus(api, clock=CLOCK, school_overrides=NORTHSIDE,
                       room_areas=(), projections=(), budget_cents=None)
    study_id = create_study(api, ctx["school_id"], ctx["policy_id"])["id"]

    validate_error(api.reopen_study(study_id, {}, PLANNER_HEADERS),
                   ApiErrorId.STUDY_STATE_INVALID, expected_status=409)

    still_draft = validate_success(api.get_capacity_study(study_id, PLANNER_HEADERS))
    assert still_draft["status"] == "DRAFT"
    assert still_draft["revision_round"] == 0
    assert still_draft["version"] == 1

    validate_error(api.certify_study(study_id, {}, CERTIFIER_HEADERS),
                   ApiErrorId.STUDY_STATE_INVALID, expected_status=409)
    validate_error(
        api.return_study(study_id, {"correction_note": "n/a"}, CERTIFIER_HEADERS),
        ApiErrorId.STUDY_STATE_INVALID, expected_status=409,
    )


def test_a_submitted_study_cannot_be_submitted_again_to_refresh_its_figures(api):
    """PRD §3.3: "A `FacilitiesPlanner` submits a study that is in `DRAFT`", and
    "**Submission** is the moment all of this is frozen." PRD §3.1: a later room revision
    "never retroactively rewrites the capacity already frozen onto a submitted study." PRD
    §2.6 rule 10 supplies the code: "`ERR_STUDY_STATE_INVALID` ... 409".

    Design: Corner/state_machines/capacity_study_second_submit_rejected
    """
    ctx = _northside_with_a_draft_study(api)
    submit_study(api, ctx["study_id"])
    validate_success(
        api.create_room(room_payload(ctx["school_id"], room_number="R103"),
                        ADMIN_HEADERS),
        expected_status=201,
    )

    replay = api.submit_study(ctx["study_id"], {}, PLANNER_HEADERS)
    validate_error(replay, ApiErrorId.STUDY_STATE_INVALID, expected_status=409)

    study = validate_success(api.get_capacity_study(ctx["study_id"], PLANNER_HEADERS))
    assert study["status"] == "SUBMITTED"
    assert study["version"] == 2
    assert study["program_capacity_seats"] == 56


def test_a_superseded_study_accepts_no_further_transition_and_keeps_no_pointer(api):
    """PRD §3.3: "every other study for the same campus and `school_year` whose status is
    `CERTIFIED` moves `CERTIFIED → SUPERSEDED` ... `SUPERSEDED` is terminal: a superseded
    study never transitions again." PRD §3.2 fixes the survivor's arithmetic: under
    `STATE_LOADING_STANDARD` each room contributes "25 seats for a `STANDARD_CLASSROOM`".

    Design: Corner/state_machines/superseded_capacity_study_accepts_no_further_transitions
    """
    ctx = _northside_with_a_draft_study(api)
    first_id = ctx["study_id"]
    submit_study(api, first_id)
    certify_study(api, first_id)

    second_id = create_study(api, ctx["school_id"], ctx["policy_id"],
                             method="STATE_LOADING_STANDARD")["id"]
    submit_study(api, second_id)
    certify_study(api, second_id)

    validate_error(api.certify_study(first_id, {}, CERTIFIER_HEADERS),
                   ApiErrorId.STUDY_STATE_INVALID, expected_status=409)
    assert validate_success(
        api.get_capacity_study(first_id, PLANNER_HEADERS)
    )["status"] == "SUPERSEDED"
    assert validate_success(
        api.get_school(ctx["school_id"], PLANNER_HEADERS)
    )["certified_study_id"] == second_id

    validate_error(api.submit_study(first_id, {}, PLANNER_HEADERS),
                   ApiErrorId.STUDY_STATE_INVALID, expected_status=409)
    validate_error(
        api.return_study(first_id, {"correction_note": "n/a"}, CERTIFIER_HEADERS),
        ApiErrorId.STUDY_STATE_INVALID, expected_status=409,
    )
    validate_error(api.reopen_study(first_id, {}, PLANNER_HEADERS),
                   ApiErrorId.STUDY_STATE_INVALID, expected_status=409)

    survivor = validate_success(api.get_capacity_study(second_id, PLANNER_HEADERS))
    assert survivor["status"] == "CERTIFIED"
    assert survivor["program_capacity_seats"] == 50


def test_downgrading_a_reserved_portable_moves_only_the_condition_dimension(api):
    """PRD §3.9: "A portable unit carries two independent state dimensions on the same
    row, and they move for entirely different reasons. `condition_status` records
    serviceability and moves only when an `AssetManager` records an inspection.
    `allocation_status` records where the unit stands in the allocation lifecycle and moves
    only as a consequence of placement, scheduling and disposal activity ... Recording
    `SERVICEABLE → NEEDS_REHAB` sets `condition_grade` to the supplied grade and increments
    the unit's `version` by 1. Recording the return leg `NEEDS_REHAB → SERVICEABLE` is
    permitted only when the supplied `condition_grade` is `A`, `B` or `C`".

    Design: Corner/state_machines/portable_unit_condition_dimension_moves_while_allocation_holds
    """
    ctx = _northside_with_a_draft_study(api)
    site_id = create_site(api, ctx["school_id"], pad_code="PAD-A")["id"]
    assess_pad(api, site_id)
    unit_id = create_unit(api, asset_tag="PU-G101")["id"]
    submit_study(api, ctx["study_id"])
    certify_study(api, ctx["study_id"])
    request_id = create_request(api, ctx["study_id"], site_id, ctx["budget_id"],
                                portable_unit_id=unit_id)["id"]

    downgraded = validate_success(
        api.record_condition(unit_id, condition_payload("NEEDS_REHAB", "C"),
                             ASSET_HEADERS)
    )
    assert downgraded["condition_status"] == "NEEDS_REHAB"
    assert downgraded["condition_grade"] == "C"
    assert downgraded["allocation_status"] == "RESERVED"
    assert downgraded["current_school_id"] is None

    request = validate_success(api.get_placement_request(request_id, PLANNER_HEADERS))
    assert request["status"] == "DRAFT"
    assert request["portable_unit_id"] == unit_id
    assert validate_success(
        api.get_placement_site(site_id, PLANNER_HEADERS)
    )["occupied_by_unit_id"] is None

    restored = validate_success(
        api.record_condition(unit_id, condition_payload("SERVICEABLE", "B"),
                             ASSET_HEADERS)
    )
    assert restored["condition_status"] == "SERVICEABLE"
    assert restored["allocation_status"] == "RESERVED"
