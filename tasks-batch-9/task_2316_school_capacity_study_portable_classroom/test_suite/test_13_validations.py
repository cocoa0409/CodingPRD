"""Gates: study preconditions, the summer window, permit validity and headroom."""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ADMIN_HEADERS,
    CERTIFIER_HEADERS,
    OFFICIAL_HEADERS,
    PERMIT_HEADERS,
    PLANNER_HEADERS,
    SCHEDULER_HEADERS,
    TEST_USERS,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_budget_partition,
    assert_capacity_fields,
    assert_clock_stamp,
)
from test_helpers.factories import (
    permit_decision_payload,
    placement_request_payload,
    schedule_payload,
    study_payload,
)
from test_helpers.fixtures import (
    approve_all_permits,
    assess_pad,
    build_campus,
    build_request_context,
    certify_study,
    create_projection,
    create_request,
    create_school,
    create_site,
    create_study,
    create_unit,
    school_version,
    set_clock,
    study_version,
    submit_study,
)

CLOCK = "2027-03-01T00:00:00Z"
# Off-summer (it opens before June 15) but still inside the 180 calendar days of
# permit validity that PRD §2.6 rule 37 requires, so the waiver gate is the only
# thing standing between the booking and a 201.
OFF_SUMMER_WINDOW = {"requested_window_start": "2027-06-01",
                     "requested_window_end": "2027-06-10"}


def test_each_study_gate_surfaces_its_own_error_id(api):
    """PRD §3.1: "Each campus configuration maps to exactly one **primary band**: an
    `ELEMENTARY_K5` campus is governed by the `K_3` band, a `MIDDLE_68` campus by `G7_8`
    ... A study whose pinned policy is published for any other band is rejected with
    `ERR_POLICY_BAND_MISMATCH`, and one whose policy is published for a different year
    than the study measures is rejected with `ERR_POLICY_YEAR_MISMATCH`." PRD §2.6 rules
    25, 26 and 27: "Every grade in the campus's grade set has at least one enrolment
    projection surviving the study method's source filter — `ERR_PROJECTION_COVERAGE_GAP`,
    422, on `POST /facilities/capacity-studies/{id}/submit`." "The program capacity
    computed under the study's method is greater than 0 seats —
    `ERR_ZERO_PROGRAM_CAPACITY`, 422, on `POST /facilities/capacity-studies/{id}/submit`."
    "No selected projection has `confidence_tier` equal to `LOW` when the study's `method`
    is `DISTRICT_POLICY` — `ERR_LOW_CONFIDENCE_PROJECTION`, 422, on `POST
    /facilities/capacity-studies/{id}/certify`."

    Design: Corner/validations/study_gate_violations_return_their_declared_error_ids
    """
    ctx = build_campus(api, clock=CLOCK, school_overrides={"name": "Gap Middle"},
                       projections=((6, 20), (7, 20)), budget_cents=None)
    policy_id = ctx["policy_id"]

    elementary = create_school(api, name="Maple Elementary",
                               grade_configuration="ELEMENTARY_K5", site_acreage=8.0)
    wrong_band = api.create_capacity_study(
        study_payload(elementary["id"], policy_id,
                      school_version(api, elementary["id"])),
        PLANNER_HEADERS,
    )
    validate_error(wrong_band, ApiErrorId.POLICY_BAND_MISMATCH, expected_status=422)

    wrong_year = api.create_capacity_study(
        study_payload(ctx["school_id"], policy_id,
                      school_version(api, ctx["school_id"]), school_year="2028-29"),
        PLANNER_HEADERS,
    )
    validate_error(wrong_year, ApiErrorId.POLICY_YEAR_MISMATCH, expected_status=422)

    gap_study = create_study(api, ctx["school_id"], policy_id)
    validate_error(api.submit_study(gap_study["id"], {}, PLANNER_HEADERS),
                   ApiErrorId.PROJECTION_COVERAGE_GAP, expected_status=422)
    assert validate_success(
        api.get_capacity_study(gap_study["id"], PLANNER_HEADERS)
    )["status"] == "DRAFT"

    gym_campus = build_campus(api, clock=None,
                              school_overrides={"name": "Gymnasium Middle",
                                                "site_acreage": 6.0},
                              policy_id=policy_id,
                              room_areas=(5000,), room_types=("GYM",),
                              projections=((6, 10), (7, 10), (8, 10)),
                              budget_cents=None)
    gym_study = create_study(api, gym_campus["school_id"], policy_id)
    validate_error(api.submit_study(gym_study["id"], {}, PLANNER_HEADERS),
                   ApiErrorId.ZERO_PROGRAM_CAPACITY, expected_status=422)

    low_campus = build_campus(api, clock=None,
                              school_overrides={"name": "Lowconf Middle"},
                              policy_id=policy_id,
                              projections=((6, 20), (7, 20)), budget_cents=None)
    create_projection(api, low_campus["school_id"], 8, 20, confidence_tier="LOW")
    low_study = create_study(api, low_campus["school_id"], policy_id)
    submitted = submit_study(api, low_study["id"])
    assert submitted["utilization_pct"] == 107.1

    validate_error(api.certify_study(low_study["id"], {}, CERTIFIER_HEADERS),
                   ApiErrorId.LOW_CONFIDENCE_PROJECTION, expected_status=422)
    assert validate_success(
        api.get_capacity_study(low_study["id"], PLANNER_HEADERS)
    )["status"] == "SUBMITTED"


def test_a_campus_satisfying_every_gate_submits_and_certifies(api):
    """PRD §3.3: "the transition `DRAFT → SUBMITTED` is permitted only when the pinned
    policy's `grade_band` is the primary band of the campus configuration, the policy's
    `effective_school_year` matches the study's `school_year`, every grade in the campus
    grade set has a surviving projection, and the program capacity computes greater than
    0." "**Certification** is performed by a `CapacityCertifier` on a study in
    `SUBMITTED`, moving it `SUBMITTED → CERTIFIED` ... It stamps `certified_by_user_id`
    from the acting `X-User-ID` and `certified_on` from the logical clock ... the campus's
    `certified_study_id` is repointed to the newly certified study".

    Design: Corner/validations/all_study_gates_satisfied_certifies_cleanly
    """
    ctx = build_campus(api, clock=CLOCK,
                       school_overrides={"name": "Northside Middle"},
                       budget_cents=None)
    study = create_study(api, ctx["school_id"], ctx["policy_id"])

    submitted = submit_study(api, study["id"])
    assert submitted["status"] == "SUBMITTED"
    assert_capacity_fields(submitted, program_capacity_seats=56, utilization_pct=107.1)

    certified = validate_success(
        api.certify_study(study["id"], {}, CERTIFIER_HEADERS)
    )
    assert certified["status"] == "CERTIFIED"
    assert certified["certified_by_user_id"] == TEST_USERS["CapacityCertifier"]
    assert_clock_stamp(certified["certified_on"], CLOCK)
    assert certified["program_capacity_seats"] == 56
    assert certified["utilization_pct"] == 107.1

    assert validate_success(
        api.get_school(ctx["school_id"], PLANNER_HEADERS)
    )["certified_study_id"] == study["id"]


def test_an_off_summer_window_needs_a_waiver_and_only_an_admin_may_grant_it(api):
    """PRD §3.8: "An optional `off_summer_waiver` flag, defaulting to false, records a
    board waiver permitting work outside the summer window." "The window must lie entirely
    inside June 15 through August 15 of a single calendar year unless `off_summer_waiver`
    is true (`ERR_OUTSIDE_SUMMER_WINDOW`), and only a `DistrictAdmin` may set that flag
    true (`ERR_WAIVER_ROLE_REQUIRED`)." PRD §2.6 rule 36 fixes the status: "`off_summer_waiver`
    may be set true only by a `DistrictAdmin` — `ERR_WAIVER_ROLE_REQUIRED`, 403, on `POST
    /facilities/installation-schedules`." PRD §3.8 on the accepted booking: "Booking moves
    the request `PERMITTED → SCHEDULED` ... and opens the schedule in `PLANNED` with a null
    `cancellation_reason`."

    Design: Corner/validations/off_summer_waiver_is_a_conditional_gate_with_a_role_gate_behind_it
    """
    ctx = build_request_context(
        api, stage="permitted", clock=CLOCK,
        school_overrides={"name": "Northside Middle"},
        unit_overrides={"asset_tag": "PU-W101"},
        request_overrides=dict(OFF_SUMMER_WINDOW),
    )
    off_summer = {"window_start": "2027-06-01", "window_end": "2027-06-10"}

    no_waiver = api.create_installation_schedule(
        schedule_payload(ctx["request_id"], ctx["crew_id"], **off_summer),
        SCHEDULER_HEADERS,
    )
    validate_error(no_waiver, ApiErrorId.OUTSIDE_SUMMER_WINDOW, expected_status=422)

    self_granted = api.create_installation_schedule(
        schedule_payload(ctx["request_id"], ctx["crew_id"], off_summer_waiver=True,
                         **off_summer),
        SCHEDULER_HEADERS,
    )
    validate_error(self_granted, ApiErrorId.WAIVER_ROLE_REQUIRED, expected_status=403)

    assert validate_success(
        api.get_placement_request(ctx["request_id"], PLANNER_HEADERS)
    )["status"] == "PERMITTED"

    granted = validate_success(
        api.create_installation_schedule(
            schedule_payload(ctx["request_id"], ctx["crew_id"], off_summer_waiver=True,
                             **off_summer),
            ADMIN_HEADERS,
        ),
        expected_status=201,
    )
    assert granted["status"] == "PLANNED"
    assert granted["off_summer_waiver"] is True
    assert granted["window_start"] == "2027-06-01"
    assert granted["cancellation_reason"] is None
    assert validate_success(
        api.get_placement_request(ctx["request_id"], PLANNER_HEADERS)
    )["status"] == "SCHEDULED"


def test_a_permit_stays_current_through_exactly_the_one_hundred_and_eightieth_day(api):
    """PRD §3.7: "A decision of `APPROVED` moves the permit `SUBMITTED → APPROVED`, stamps
    `approved_on` from the logical clock ... Approval validity runs 180 calendar days from
    that instant." PRD §3.8: "Every `APPROVED` permit of the request must still be current:
    `window_start` must not fall later than 180 calendar days after that permit's
    `approved_on` (`ERR_PERMIT_EXPIRED`)." PRD §2.6 orders the two window rules: rule 35
    is "The booked window lies entirely inside June 15 through August 15 of a single
    calendar year, unless `off_summer_waiver` is true — `ERR_OUTSIDE_SUMMER_WINDOW`, 422",
    ahead of rule 37, "The booked window's opening date is not later than 180 calendar days
    after `approved_on` for every `APPROVED` permit of the request — `ERR_PERMIT_EXPIRED`,
    409".

    Design: Corner/validations/permit_validity_expires_180_days_after_approval
    """
    approval_clock = "2027-02-16T00:00:00Z"
    ctx = build_request_context(
        api, stage="permitted", clock=approval_clock,
        school_overrides={"name": "Northside Middle"},
        unit_overrides={"asset_tag": "PU-X101"},
    )
    set_clock(api, "2027-05-01T00:00:00Z")

    next_summer = api.create_installation_schedule(
        schedule_payload(ctx["request_id"], ctx["crew_id"],
                         window_start="2028-06-20", window_end="2028-06-30"),
        SCHEDULER_HEADERS,
    )
    validate_error(next_summer, ApiErrorId.PERMIT_EXPIRED, expected_status=409)

    dsa = validate_success(
        api.get_permit(ctx["permit_ids"]["DSA_STRUCTURAL"], OFFICIAL_HEADERS)
    )
    assert dsa["status"] == "APPROVED"
    assert_clock_stamp(dsa["approved_on"], approval_clock)

    one_day_late = api.create_installation_schedule(
        schedule_payload(ctx["request_id"], ctx["crew_id"],
                         window_start="2027-08-16", window_end="2027-08-20"),
        SCHEDULER_HEADERS,
    )
    validate_error(one_day_late, ApiErrorId.OUTSIDE_SUMMER_WINDOW, expected_status=422)

    assert validate_success(
        api.get_placement_request(ctx["request_id"], PLANNER_HEADERS)
    )["status"] == "PERMITTED"

    day_180 = validate_success(
        api.create_installation_schedule(
            schedule_payload(ctx["request_id"], ctx["crew_id"],
                             window_start="2027-08-15", window_end="2027-08-15"),
            SCHEDULER_HEADERS,
        ),
        expected_status=201,
    )
    assert day_180["status"] == "PLANNED"


def test_headroom_is_measured_against_uncommitted_not_against_the_authorization(api):
    """PRD §2.6 rule 40: "The appropriation's `uncommitted_cents` is at least the amount
    being committed — the request's `estimated_relocation_cost_cents` when the final permit
    approval commits the encumbrance ... — `ERR_BUDGET_INSUFFICIENT`, 409, on `POST
    /facilities/permits/{id}/decision`". PRD §3.7: "the join is gated on money — the
    appropriation's `uncommitted_cents` must be at least the request's
    `estimated_relocation_cost_cents`, and a shortfall is reported as
    `ERR_BUDGET_INSUFFICIENT`." PRD §2.9: "`authorized_cents` is equal to the sum of
    `uncommitted_cents`, `encumbered_cents` and `expended_cents`."

    Design: Corner/validations/budget_headroom_is_checked_against_the_running_encumbrance
    """
    ctx = build_campus(api, clock=CLOCK,
                       school_overrides={"name": "Northside Middle"},
                       budget_cents=10_000_000)

    site_a = create_site(api, ctx["school_id"], pad_code="PAD-A")
    assess_pad(api, site_a["id"])
    site_b = create_site(api, ctx["school_id"], pad_code="PAD-B")
    assess_pad(api, site_b["id"])
    unit_a = create_unit(api, asset_tag="PU-Y101")
    unit_b = create_unit(api, asset_tag="PU-Y102")

    study = create_study(api, ctx["school_id"], ctx["policy_id"])
    submit_study(api, study["id"])
    certify_study(api, study["id"])

    request_a = create_request(api, study["id"], site_a["id"], ctx["budget_id"],
                               portable_unit_id=unit_a["id"])
    validate_success(api.assess_site(request_a["id"], {}, PLANNER_HEADERS))
    validate_success(api.submit_permits(request_a["id"], {}, PERMIT_HEADERS))
    approve_all_permits(api, request_a["id"])

    request_b = create_request(
        api, study["id"], site_b["id"], ctx["budget_id"],
        portable_unit_id=unit_b["id"],
        requested_window_start="2027-07-06", requested_window_end="2027-07-16",
    )
    assert request_b["estimated_relocation_cost_cents"] == 7_741_440
    validate_success(api.assess_site(request_b["id"], {}, PLANNER_HEADERS))
    validate_success(api.submit_permits(request_b["id"], {}, PERMIT_HEADERS))
    permits_b = approve_all_permits(api, request_b["id"], skip=("ELECTRICAL",))

    final_decision = api.decide_permit(
        permits_b["ELECTRICAL"], permit_decision_payload("APPROVED"), OFFICIAL_HEADERS
    )
    validate_error(final_decision, ApiErrorId.BUDGET_INSUFFICIENT, expected_status=409)

    assert_budget_partition(
        validate_success(api.get_capital_budget(ctx["budget_id"], PLANNER_HEADERS)),
        authorized_cents=10_000_000, encumbered_cents=7_741_440, expended_cents=0,
        uncommitted_cents=2_258_560,
    )

    unchanged = validate_success(
        api.get_permit(permits_b["ELECTRICAL"], OFFICIAL_HEADERS)
    )
    assert unchanged["status"] == "SUBMITTED"
    assert unchanged["approved_on"] is None

    blocked = validate_success(api.get_placement_request(request_b["id"],
                                                         PLANNER_HEADERS))
    assert blocked["status"] == "PERMIT_PENDING"
    assert blocked["encumbered_cost_cents"] == 0

    survivor = validate_success(api.get_placement_request(request_a["id"],
                                                          PLANNER_HEADERS))
    assert survivor["status"] == "PERMITTED"
    assert survivor["encumbered_cost_cents"] == 7_741_440


def test_pad_geometry_is_only_judged_once_the_unit_reference_resolves(api):
    """PRD §2.6: rule 5 — "Every foreign key in the request body resolves, in
    entity-declaration order — the 404 family, on every endpoint that carries body foreign
    keys" — precedes rule 30 — "Pad geometry admits the unit: `pad_length_ft` is at least
    the unit's chassis length plus 10 feet and `pad_width_ft` is at least the unit's
    chassis width plus 10 feet — `ERR_PAD_TOO_SMALL`, 422, on `POST
    /facilities/placement-requests`." PRD §3.4 fixes the chassis: "a `TRIPLE_36x64`
    measures 64 feet by 36 feet ... Every chassis requires 5 feet of clearance on each
    side, so the pad must offer the chassis length plus 10 feet and the chassis width plus
    10 feet."

    Design: Corner/validations/geometry_check_waits_for_the_unit_reference_to_resolve
    """
    ctx = build_campus(api, clock=CLOCK, school_overrides={"name": "Northside Middle"})
    site = create_site(api, ctx["school_id"], pad_code="PAD-A")
    triple = create_unit(api, asset_tag="PU-Z301", size_class="TRIPLE_36x64",
                         acquisition_cost_cents=21_000_000)

    study = create_study(api, ctx["school_id"], ctx["policy_id"])
    submit_study(api, study["id"])
    certify_study(api, study["id"])

    def payload(unit_id):
        return placement_request_payload(
            study["id"], site["id"], ctx["budget_id"], study_version(api, study["id"]),
            portable_unit_id=unit_id,
        )

    unknown_unit = api.create_placement_request(payload(NON_EXISTENT_UUID),
                                                PLANNER_HEADERS)
    validate_error(unknown_unit, ApiErrorId.UNIT_NOT_FOUND, expected_status=404)

    too_small = api.create_placement_request(payload(triple["id"]), PLANNER_HEADERS)
    validate_error(too_small, ApiErrorId.PAD_TOO_SMALL, expected_status=422)

    _, meta = validate_paginated(
        api.list_placement_requests(PLANNER_HEADERS,
                                    {"capacity_study_id": study["id"]})
    )
    assert meta["total_count"] == 0
