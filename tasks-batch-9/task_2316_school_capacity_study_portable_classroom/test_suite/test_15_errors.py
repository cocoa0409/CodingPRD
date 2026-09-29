"""Error identity: envelope codes, the 404 family, uniqueness and state locks."""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    build_user_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ADMIN_HEADERS,
    ASSET_HEADERS,
    OFFICIAL_HEADERS,
    PERMIT_HEADERS,
    PLANNER_HEADERS,
    SCHEDULER_HEADERS,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import (
    legacy_placement_payload,
    permit_decision_payload,
    permit_resubmit_payload,
    placement_request_payload,
    room_payload,
    school_payload,
    site_payload,
    unit_payload,
)
from test_helpers.fixtures import (
    assess_pad,
    build_campus,
    build_request_context,
    certify_study,
    create_policy,
    create_request,
    create_school,
    create_site,
    create_study,
    create_unit,
    set_clock,
    study_version,
    submit_study,
)

CLOCK = "2027-03-01T00:00:00Z"
NORTHSIDE = {"name": "Northside Middle", "site_acreage": 10.0,
             "electrical_spare_capacity_kw": 40, "sewer_spare_connections": 2}
SUMMER_WINDOW = {"requested_window_start": "2027-06-15",
                 "requested_window_end": "2027-06-25"}


def _unused_id(tail: str) -> str:
    return f"00000000-0000-4000-8000-0000000000{tail}"


def test_authentication_outranks_authorisation_which_outranks_the_body(api):
    """PRD §2.6 rule 1: "`X-User-Role` and `X-User-ID` are both present and `X-User-Role`
    is one of the eight declared roles — `ERR_UNAUTHENTICATED`, 401, on every endpoint."
    Rule 2: "The acting role appears in the endpoint's authorized role list —
    `ERR_FORBIDDEN_ROLE`, 403, on every endpoint." Rule 4 comes after both: "Every
    identifier in the request path resolves, left to right — the 404 family, on every
    path-parameterised endpoint", and rule 6 after that: "Required body fields are present
    ... — `ERR_INVALID_REQUEST`, 422, on every endpoint." Rule 7: "`limit` is an integer
    from 1 through 100 and `offset` is an integer of at least 0 —
    `ERR_INVALID_PAGINATION`, 422, on every list endpoint." PRD §2.3: "when it is omitted
    the server uses 10 ... when it is omitted the server uses 0".

    Design: Corner/errors/auth_role_and_pagination_envelope_errors
    """
    set_clock(api, CLOCK)
    school = create_school(api, name="Northside Middle", site_acreage=10.0)

    anonymous = api.get_school(NON_EXISTENT_UUID, {})
    validate_error(anonymous, ApiErrorId.UNAUTHENTICATED, expected_status=401)

    ghost = api.get_school(NON_EXISTENT_UUID,
                           build_user_headers("ghost-1", "SUPERINTENDENT"))
    validate_error(ghost, ApiErrorId.UNAUTHENTICATED, expected_status=401)

    wrong_role = api.create_school(school_payload(name="Planner Middle"),
                                   PLANNER_HEADERS)
    validate_error(wrong_role, ApiErrorId.FORBIDDEN_ROLE, expected_status=403)

    wrong_role_empty_body = api.create_school({}, PLANNER_HEADERS)
    validate_error(wrong_role_empty_body, ApiErrorId.FORBIDDEN_ROLE,
                   expected_status=403)

    assert validate_success(
        api.get_school(school["id"], ADMIN_HEADERS)
    )["name"] == "Northside Middle"

    for params in ({"limit": 0}, {"limit": 101}, {"offset": -1}):
        validate_error(api.list_portable_units(ASSET_HEADERS, params),
                       ApiErrorId.INVALID_PAGINATION, expected_status=422)

    _, meta = validate_paginated(api.list_portable_units(ASSET_HEADERS))
    assert meta["limit"] == 10
    assert meta["offset"] == 0


def test_every_entity_owns_its_own_not_found_code(api):
    """PRD §2.5: "Identifiers appearing in the request path are resolved first, left to
    right, and the first one that fails to resolve determines the error:
    `ERR_SCHOOL_NOT_FOUND`, `ERR_ROOM_NOT_FOUND`, `ERR_SET_ASIDE_NOT_FOUND`,
    `ERR_PROJECTION_NOT_FOUND`, `ERR_STUDY_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`,
    `ERR_SITE_NOT_FOUND`, `ERR_REQUEST_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`,
    `ERR_SCHEDULE_NOT_FOUND`, `ERR_BUDGET_NOT_FOUND` or `ERR_DISPOSAL_NOT_FOUND`, each
    carrying 404." The same section names the two remaining members of the family,
    "`ERR_POLICY_NOT_FOUND`" and "`ERR_CREW_NOT_FOUND`". PRD §2.6 rule 4: "Every
    identifier in the request path resolves, left to right — the 404 family, on every
    path-parameterised endpoint."

    Design: Corner/errors/every_not_found_code_is_entity_specific
    """
    set_clock(api, CLOCK)

    probes = (
        (api.get_school, "01", ApiErrorId.SCHOOL_NOT_FOUND),
        (api.get_room, "02", ApiErrorId.ROOM_NOT_FOUND),
        (api.get_program_set_aside, "03", ApiErrorId.SET_ASIDE_NOT_FOUND),
        (api.get_enrollment_projection, "04", ApiErrorId.PROJECTION_NOT_FOUND),
        (api.get_class_size_policy, "05", ApiErrorId.POLICY_NOT_FOUND),
        (api.get_capacity_study, "06", ApiErrorId.STUDY_NOT_FOUND),
        (api.get_portable_unit, "07", ApiErrorId.UNIT_NOT_FOUND),
        (api.get_placement_site, "08", ApiErrorId.SITE_NOT_FOUND),
        (api.get_placement_request, "09", ApiErrorId.REQUEST_NOT_FOUND),
        (api.get_permit, "0a", ApiErrorId.PERMIT_NOT_FOUND),
        (api.get_installation_schedule, "0b", ApiErrorId.SCHEDULE_NOT_FOUND),
        (api.get_capital_budget, "0c", ApiErrorId.BUDGET_NOT_FOUND),
        (api.get_installation_crew, "0d", ApiErrorId.CREW_NOT_FOUND),
        (api.get_disposal_record, "0e", ApiErrorId.DISPOSAL_NOT_FOUND),
    )

    for read, tail, error_id in probes:
        validate_error(read(_unused_id(tail), ADMIN_HEADERS), error_id,
                       expected_status=404)


def test_each_uniqueness_scope_has_its_own_code_and_its_own_reach(api):
    """PRD §2.6 rule 32: "Uniqueness: a class-size policy is unique on the pair
    `grade_band` and `effective_school_year` (`ERR_DUPLICATE_POLICY`); a room is unique on
    the pair `school_id` and `room_number` (`ERR_DUPLICATE_ROOM`); a portable unit is unique
    on `asset_tag` across the whole inventory (`ERR_DUPLICATE_ASSET_TAG`); a pad is unique
    on the pair `school_id` and `pad_code` (`ERR_DUPLICATE_PAD_CODE`). All four carry 409,
    on `POST /facilities/class-size-policies`, `POST /facilities/rooms`, `POST
    /facilities/portable-units` and `POST /facilities/placement-sites` respectively." PRD
    §2.4: "A published class-size policy is never edited".

    Design: Corner/errors/uniqueness_codes_are_scope_specific
    """
    set_clock(api, CLOCK)
    policy = create_policy(api)
    school = create_school(api, name="Northside Middle", site_acreage=10.0)
    other = create_school(api, name="Eastvale Middle", site_acreage=10.0)
    validate_success(
        api.create_room(room_payload(school["id"], room_number="R101"), ADMIN_HEADERS),
        expected_status=201,
    )
    create_unit(api, asset_tag="PU-U101")
    validate_success(
        api.create_placement_site(site_payload(school["id"], pad_code="PAD-A"),
                                  ADMIN_HEADERS),
        expected_status=201,
    )

    duplicate_policy = api.create_class_size_policy(
        {"grade_band": "G7_8", "effective_school_year": "2027-28",
         "max_class_size": 24, "min_area_sqft_per_seat": 32,
         "lab_area_premium_sqft": 25},
        ADMIN_HEADERS,
    )
    validate_error(duplicate_policy, ApiErrorId.DUPLICATE_POLICY, expected_status=409)
    assert validate_success(
        api.get_class_size_policy(policy["id"], ADMIN_HEADERS)
    )["max_class_size"] == 28

    collide = room_payload(school["id"], room_number="R101",
                           room_type="SCIENCE_LAB", area_sqft=1000)
    validate_error(api.create_room(collide, ADMIN_HEADERS),
                   ApiErrorId.DUPLICATE_ROOM, expected_status=409)

    elsewhere = dict(collide)
    elsewhere["school_id"] = other["id"]
    validate_success(api.create_room(elsewhere, ADMIN_HEADERS), expected_status=201)

    duplicate_tag = api.create_portable_unit(
        unit_payload(asset_tag="PU-U101", size_class="DOUBLE_28x64",
                     acquisition_cost_cents=15_000_000),
        ASSET_HEADERS,
    )
    validate_error(duplicate_tag, ApiErrorId.DUPLICATE_ASSET_TAG, expected_status=409)

    duplicate_pad = api.create_placement_site(
        site_payload(school["id"], pad_code="PAD-A"), ADMIN_HEADERS
    )
    validate_error(duplicate_pad, ApiErrorId.DUPLICATE_PAD_CODE, expected_status=409)

    validate_success(
        api.create_placement_site(site_payload(other["id"], pad_code="PAD-A"),
                                  ADMIN_HEADERS),
        expected_status=201,
    )


def test_a_unit_already_standing_somewhere_cannot_be_onboarded_a_second_time(api):
    """PRD §3.9: "The unit must be `IN_STORAGE`, its `condition_status` must not be
    `UNSAFE`, and the named pad must belong to the supplied campus and have a null
    `occupied_by_unit_id` ... On success the unit jumps `IN_STORAGE → INSTALLED`, its
    `current_school_id` is set, the pad's `occupied_by_unit_id` is set,
    `lifetime_relocation_count` is incremented by 1, the unit's `rated_seats` are added to
    the campus's `hosted_portable_seats`". PRD §2.6 rule 10: "The target row is in a state
    from which the requested transition is declared — ... or `ERR_UNIT_STATE_INVALID`, 409,
    on every action endpoint", which precedes rule 31, "The target pad's
    `occupied_by_unit_id` is null — `ERR_SITE_OCCUPIED`, 409".

    Design: Corner/errors/unit_state_invalid_on_a_second_legacy_placement
    """
    set_clock(api, CLOCK)
    school = create_school(api, **NORTHSIDE)
    site_a = create_site(api, school["id"], pad_code="PAD-A")
    site_b = create_site(api, school["id"], pad_code="PAD-B")
    unit = create_unit(api, asset_tag="PU-S101", in_service_year=2016)

    validate_success(
        api.record_existing_placement(
            unit["id"],
            legacy_placement_payload(school["id"], site_a["id"],
                                     installed_on="2024-08-01"),
            ASSET_HEADERS,
        )
    )

    second = api.record_existing_placement(
        unit["id"],
        legacy_placement_payload(school["id"], site_b["id"],
                                 installed_on="2025-08-01"),
        ASSET_HEADERS,
    )
    validate_error(second, ApiErrorId.UNIT_STATE_INVALID, expected_status=409)

    untouched = validate_success(api.get_placement_site(site_b["id"], ADMIN_HEADERS))
    assert untouched["occupied_by_unit_id"] is None
    assert untouched["version"] == 1

    assert validate_success(
        api.get_placement_site(site_a["id"], ADMIN_HEADERS)
    )["occupied_by_unit_id"] == unit["id"]

    stored = validate_success(api.get_portable_unit(unit["id"], ASSET_HEADERS))
    assert stored["lifetime_relocation_count"] == 1
    assert stored["version"] == 2

    assert validate_success(
        api.get_school(school["id"], ADMIN_HEADERS)
    )["hosted_portable_seats"] == 24


def test_a_permit_and_a_schedule_each_report_their_own_state_lock(api):
    """PRD §2.6 rule 10: "The target row is in a state from which the requested transition
    is declared — `ERR_STUDY_STATE_INVALID`, `ERR_REQUEST_STATE_INVALID`,
    `ERR_PERMIT_STATE_INVALID`, `ERR_SCHEDULE_STATE_INVALID` or `ERR_UNIT_STATE_INVALID`,
    409, on every action endpoint", ahead of rule 19 and rule 24. PRD §3.7: "refiling
    requires the permit to be in `CORRECTIONS_REQUIRED` and the owning request still to be
    `PERMIT_PENDING`", and "Both `APPROVED` and `DENIED` are terminal for a permit." PRD
    §3.8: "Marking the crew on site moves the schedule `PLANNED → IN_PROGRESS`" and
    "Completing the work moves the schedule `IN_PROGRESS → COMPLETED`".

    Design: Corner/errors/permit_and_schedule_state_invalid_codes
    """
    ctx = build_request_context(
        api, stage="scheduled", clock=CLOCK, school_overrides=NORTHSIDE,
        unit_overrides={"asset_tag": "PU-R101"},
    )
    permit_id = ctx["permit_ids"]["DSA_STRUCTURAL"]

    refile = api.resubmit_permit(permit_id, permit_resubmit_payload(), PERMIT_HEADERS)
    validate_error(refile, ApiErrorId.PERMIT_STATE_INVALID, expected_status=409)

    permit = validate_success(api.get_permit(permit_id, PERMIT_HEADERS))
    assert permit["status"] == "APPROVED"
    assert permit["review_cycle_count"] == 0

    late_denial = api.decide_permit(permit_id, permit_decision_payload("DENIED"),
                                   OFFICIAL_HEADERS)
    body = validate_error(late_denial, ApiErrorId.PERMIT_STATE_INVALID,
                          expected_status=409)
    assert body["error_id"] != ApiErrorId.PERMIT_REQUEST_NOT_PENDING

    unstarted = api.complete_schedule(ctx["schedule_id"], {}, SCHEDULER_HEADERS)
    body = validate_error(unstarted, ApiErrorId.SCHEDULE_STATE_INVALID,
                          expected_status=409)
    assert body["error_id"] != ApiErrorId.ADA_NONCOMPLIANT

    planned = validate_success(
        api.get_installation_schedule(ctx["schedule_id"], SCHEDULER_HEADERS)
    )
    assert planned["status"] == "PLANNED"
    assert planned["version"] == 1

    started = validate_success(
        api.start_schedule(ctx["schedule_id"], {}, SCHEDULER_HEADERS)
    )
    assert started["status"] == "IN_PROGRESS"
    validate_error(api.start_schedule(ctx["schedule_id"], {}, SCHEDULER_HEADERS),
                   ApiErrorId.SCHEDULE_STATE_INVALID, expected_status=409)


def test_each_placement_gate_names_itself_rather_than_the_generic_neighbour(api):
    """PRD §2.6 rule 17: "The pad's `distance_to_fire_lane_ft` is at most 150 and the
    campus's `fire_lane_clear_width_ft` is at least 20 — `ERR_FIRE_ACCESS_NONCOMPLIANT`,
    422, on `POST /facilities/placement-requests/{id}/assess-site`. This rule is
    deliberately evaluated ahead of rule 18 so that a pad already recorded as infeasible
    for fire access reports the specific fire-access failure rather than the generic
    feasibility failure." Rule 18: "The referenced pad's `feasibility_status` is either
    `FEASIBLE` or `FEASIBLE_WITH_MITIGATION`, and its `assessed_for_size_class` is equal to
    the assigned unit's `size_class` — `ERR_SITE_NOT_FEASIBLE`, 422". Rule 16: "The
    referenced portable unit's `condition_grade` is not `D` —
    `ERR_UNIT_GRADE_NOT_PLACEABLE`, 422, on `POST /facilities/placement-requests`." Rule
    29: "The unit's `lifetime_relocation_count` is strictly less than 4 —
    `ERR_UNIT_RELOCATION_LIMIT`, 422". Rule 34: "The closing date of a window is not
    earlier than its opening date ... — `ERR_INVALID_WINDOW`, 422". PRD §3.4: "If
    `distance_to_fire_lane_ft` is greater than 150 feet, or the campus's
    `fire_lane_clear_width_ft` is less than 20 feet, the pad is judged `INFEASIBLE` with
    `infeasible_reason` `FIRE_ACCESS` and an empty `mitigation_flags`, and nothing further
    is evaluated." "A newly registered pad has `feasibility_status` `UNASSESSED`".

    Design: Corner/errors/site_and_unit_eligibility_codes_at_the_request_gates
    """
    ctx = build_request_context(
        api, stage="draft", clock=CLOCK, school_overrides=NORTHSIDE,
        pad_overrides={"pad_code": "PAD-A"},
        unit_overrides={"asset_tag": "PU-G101"},
        request_overrides=dict(SUMMER_WINDOW),
    )
    raw_site = create_site(api, ctx["school_id"], pad_code="PAD-RAW")
    grade_d = create_unit(api, asset_tag="PU-G102", condition_grade="D",
                          in_service_year=2011)
    worn = create_unit(api, asset_tag="PU-G103", in_service_year=2015,
                       prior_relocation_count=4)

    narrow = build_campus(
        api, clock=None, policy_id=ctx["policy_id"], budget_cents=None,
        school_overrides={"name": "Narrowlane Middle", "site_acreage": 6.0,
                          "fire_lane_clear_width_ft": 18,
                          "electrical_spare_capacity_kw": 40,
                          "sewer_spare_connections": 1},
    )
    narrow_site = create_site(api, narrow["school_id"], pad_code="PAD-N")
    narrow_pad = assess_pad(api, narrow_site["id"])
    assert narrow_pad["feasibility_status"] == "INFEASIBLE"
    assert narrow_pad["infeasible_reason"] == "FIRE_ACCESS"

    narrow_unit = create_unit(api, asset_tag="PU-G104")
    narrow_study = create_study(api, narrow["school_id"], ctx["policy_id"])
    submit_study(api, narrow_study["id"])
    certify_study(api, narrow_study["id"])
    narrow_request = create_request(
        api, narrow_study["id"], narrow_site["id"], ctx["budget_id"],
        portable_unit_id=narrow_unit["id"], **SUMMER_WINDOW,
    )

    fire = api.assess_site(narrow_request["id"], {}, PLANNER_HEADERS)
    validate_error(fire, ApiErrorId.FIRE_ACCESS_NONCOMPLIANT, expected_status=422)

    # PRD §3.6: "The `IN_STORAGE → RESERVED` move requires that the unit be
    # `IN_STORAGE`", so every further create that must succeed brings its own
    # unreserved unit rather than re-using the one the draft request holds.
    raw_unit = create_unit(api, asset_tag="PU-G105")
    raw_request = create_request(
        api, ctx["study_id"], raw_site["id"], ctx["budget_id"],
        portable_unit_id=raw_unit["id"], **SUMMER_WINDOW,
    )
    not_feasible = api.assess_site(raw_request["id"], {}, PLANNER_HEADERS)
    validate_error(not_feasible, ApiErrorId.SITE_NOT_FEASIBLE, expected_status=422)
    assert validate_success(
        api.get_placement_site(raw_site["id"], PLANNER_HEADERS)
    )["feasibility_status"] == "UNASSESSED"

    def payload(**overrides):
        return placement_request_payload(
            ctx["study_id"], ctx["site_id"], ctx["budget_id"],
            study_version(api, ctx["study_id"]), **{**SUMMER_WINDOW, **overrides}
        )

    validate_error(
        api.create_placement_request(payload(portable_unit_id=grade_d["id"]),
                                     PLANNER_HEADERS),
        ApiErrorId.UNIT_GRADE_NOT_PLACEABLE, expected_status=422,
    )
    spare = create_unit(api, asset_tag="PU-G106")
    validate_error(
        api.create_placement_request(
            payload(portable_unit_id=spare["id"],
                    requested_window_start="2027-06-25",
                    requested_window_end="2027-06-15"),
            PLANNER_HEADERS,
        ),
        ApiErrorId.INVALID_WINDOW, expected_status=422,
    )
    validate_error(
        api.create_placement_request(payload(portable_unit_id=worn["id"]),
                                     PLANNER_HEADERS),
        ApiErrorId.UNIT_RELOCATION_LIMIT, expected_status=422,
    )
    assert validate_success(
        api.get_portable_unit(worn["id"], ASSET_HEADERS)
    )["lifetime_relocation_count"] == 4

    assert validate_success(
        api.get_portable_unit(spare["id"], ASSET_HEADERS)
    )["lifetime_relocation_count"] == 0
    validate_success(
        api.create_placement_request(payload(portable_unit_id=spare["id"]),
                                     PLANNER_HEADERS),
        expected_status=201,
    )
