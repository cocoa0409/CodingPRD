"""Role and identity gates: exclusive verbs, segregation of duties, crew identity."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    ADMIN_HEADERS,
    CERTIFIER_HEADERS,
    OFFICIAL_HEADERS,
    PERMIT_HEADERS,
    PLANNER_HEADERS,
    TEST_USERS,
    headers_for,
    make_crew_lead_headers,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import projection_payload
from test_helpers.fixtures import (
    build_campus,
    build_request_context,
    create_crew,
    create_study,
    submit_study,
)

CLOCK = "2027-03-01T00:00:00Z"
NORTHSIDE = {"name": "Northside Middle", "site_acreage": 10.0,
             "electrical_spare_capacity_kw": 40, "sewer_spare_connections": 1}


def test_no_role_may_borrow_another_roles_exclusive_verb(api):
    """PRD §2.6 rule 2: "The acting role appears in the endpoint's authorized role list —
    `ERR_FORBIDDEN_ROLE`, 403, on every endpoint", evaluated ahead of rule 4, "Every
    identifier in the request path resolves, left to right — the 404 family". PRD §4 gives
    the exclusive lists: `POST /facilities/capacity-studies/{id}/certify` is
    `CapacityCertifier`, `POST /facilities/capacity-studies/{id}/submit` is
    `FacilitiesPlanner`, `PATCH /facilities/rooms/{id}` is `DistrictAdmin`, `POST
    /facilities/placement-requests/{id}/submit-permits` is `PermitCoordinator`, `POST
    /facilities/enrollment-projections` is "FacilitiesPlanner, DistrictAdmin", and `GET
    /facilities/capacity-studies/{id}` is "All roles except CrewLead". PRD §3.2: a new
    study opens "with `certified_by_user_id` and `certified_on` null".

    Design: Corner/rbac/exclusive_operations_are_refused_to_every_other_role
    """
    ctx = build_campus(api, clock=CLOCK, school_overrides=NORTHSIDE, budget_cents=None)
    study = create_study(api, ctx["school_id"], ctx["policy_id"])
    submit_study(api, study["id"])

    self_certified = api.certify_study(study["id"], {}, PLANNER_HEADERS)
    validate_error(self_certified, ApiErrorId.FORBIDDEN_ROLE, expected_status=403)

    unchanged = validate_success(api.get_capacity_study(study["id"], PLANNER_HEADERS))
    assert unchanged["status"] == "SUBMITTED"
    assert unchanged["certified_by_user_id"] is None

    certifier_submitting = api.submit_study(study["id"], {}, CERTIFIER_HEADERS)
    validate_error(certifier_submitting, ApiErrorId.FORBIDDEN_ROLE, expected_status=403)

    planner_patching = api.patch_room(ctx["room_ids"][0],
                                      {"status": "OUT_OF_SERVICE_RENOVATION"},
                                      PLANNER_HEADERS)
    validate_error(planner_patching, ApiErrorId.FORBIDDEN_ROLE, expected_status=403)

    official_filing = api.submit_permits(study["id"], {}, OFFICIAL_HEADERS)
    body = validate_error(official_filing, ApiErrorId.FORBIDDEN_ROLE,
                          expected_status=403)
    assert body["error_id"] != ApiErrorId.REQUEST_NOT_FOUND

    for headers in (PLANNER_HEADERS, ADMIN_HEADERS):
        validate_success(
            api.create_enrollment_projection(
                projection_payload(ctx["school_id"], grade_level=6,
                                   projected_students=21),
                headers,
            ),
            expected_status=201,
        )

    assert validate_success(
        api.get_capacity_study(study["id"], PERMIT_HEADERS)
    )["id"] == study["id"]


def test_a_certifier_holding_the_authors_identity_is_refused_on_both_review_verbs(api):
    """PRD §2.6 rule 14: "The acting `X-User-ID` differs from the study's
    `authored_by_user_id` — `ERR_SEGREGATION_OF_DUTIES`, 403, on `POST
    /facilities/capacity-studies/{id}/certify` and `POST
    /facilities/capacity-studies/{id}/return`." PRD §3.3: "**Return** is the other outcome
    of review. A `CapacityCertifier` returns a `SUBMITTED` study — again only when the
    acting `X-User-ID` differs from `authored_by_user_id` — supplying a `correction_note`
    that explains what must change." PRD §3.3 on the permitted case: "It stamps
    `certified_by_user_id` from the acting `X-User-ID`".

    Design: Corner/rbac/certifier_may_not_certify_or_return_its_own_authored_study
    """
    ctx = build_campus(api, clock=CLOCK, school_overrides=NORTHSIDE, budget_cents=None)
    study = create_study(api, ctx["school_id"], ctx["policy_id"])
    submit_study(api, study["id"])

    author_identity = headers_for("CapacityCertifier",
                                 TEST_USERS["FacilitiesPlanner"])

    self_review = api.certify_study(study["id"], {}, author_identity)
    validate_error(self_review, ApiErrorId.SEGREGATION_OF_DUTIES, expected_status=403)

    intact = validate_success(api.get_capacity_study(study["id"], PLANNER_HEADERS))
    assert intact["authored_by_user_id"] == TEST_USERS["FacilitiesPlanner"]
    assert intact["status"] == "SUBMITTED"
    assert intact["version"] == 2

    self_return = api.return_study(
        study["id"], {"correction_note": "Recheck the lab loading."}, author_identity
    )
    validate_error(self_return, ApiErrorId.SEGREGATION_OF_DUTIES, expected_status=403)

    certified = validate_success(
        api.certify_study(study["id"], {}, CERTIFIER_HEADERS)
    )
    assert certified["status"] == "CERTIFIED"
    assert certified["certified_by_user_id"] == TEST_USERS["CapacityCertifier"]


def test_a_crew_lead_is_bound_to_the_schedule_of_its_own_crew(api):
    """PRD §2.6 rule 3: "When the acting role is `CrewLead`, `X-User-ID` is equal to the
    target schedule's `installation_crew_id` — `ERR_CREW_NOT_ASSIGNED`, 403, on exactly two
    endpoints: `POST /facilities/installation-schedules/{id}/start` and `POST
    /facilities/installation-schedules/{id}/complete`." That rule precedes rule 10, "The
    target row is in a state from which the requested transition is declared". PRD §3.8:
    "Marking the crew on site moves the schedule `PLANNED → IN_PROGRESS`, requires the
    owning request to be `SCHEDULED`, and — when the actor is a `CrewLead` — requires
    `X-User-ID` to equal the schedule's `installation_crew_id`."

    Design: Corner/rbac/crew_lead_may_only_touch_its_own_crews_schedule
    """
    ctx = build_request_context(
        api, stage="scheduled", clock=CLOCK, school_overrides=NORTHSIDE,
        unit_overrides={"asset_tag": "PU-C101"},
        crew_overrides={"name": "Crew Alpha"},
    )
    other_crew = create_crew(api, name="Crew Beta")

    intruder = api.start_schedule(ctx["schedule_id"], {},
                                  make_crew_lead_headers(other_crew["id"]))
    validate_error(intruder, ApiErrorId.CREW_NOT_ASSIGNED, expected_status=403)

    untouched = validate_success(
        api.get_installation_schedule(ctx["schedule_id"], PLANNER_HEADERS)
    )
    assert untouched["status"] == "PLANNED"
    assert untouched["version"] == 1

    owner = validate_success(
        api.start_schedule(ctx["schedule_id"], {},
                           make_crew_lead_headers(ctx["crew_id"]))
    )
    assert owner["status"] == "IN_PROGRESS"
    assert owner["version"] == 2

    still_refused = api.start_schedule(ctx["schedule_id"], {},
                                       make_crew_lead_headers(other_crew["id"]))
    body = validate_error(still_refused, ApiErrorId.CREW_NOT_ASSIGNED,
                          expected_status=403)
    assert body["error_id"] != ApiErrorId.SCHEDULE_STATE_INVALID
