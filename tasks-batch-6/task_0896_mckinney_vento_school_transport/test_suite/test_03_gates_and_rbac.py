"""Trip/activation gates, validation ordering, and RBAC
(corner: validations, rbac; difficulty: priority_pair_validation_conflict,
cross_entity_state_dependency, resource_temporal_overlap)."""
from test_helpers import (
    validate_success, validate_error, get_success_data, build_user_headers,
    ApiErrorId, TEST_USERS,
    create_district, create_student, create_vehicle, create_dispute,
    create_plan, create_trip,
    setup_eligible_student, setup_active_plan, setup_active_plan_with_vehicle,
    setup_approved_plan,
)
from test_helpers.api_client import api_client

SC = TEST_USERS["state_coordinator_headers"]

START = "2026-05-04T08:00:00Z"
END = "2026-05-04T08:30:00Z"


# ---------------------------------------------------------------------------
# Corner: validations
# ---------------------------------------------------------------------------
def test_trip_on_draft_plan_not_active(api):
    """PRD §3.7: "Trip creation enforces several gates in order: the plan must be `ACTIVE` (else `ERR_PLAN_NOT_ACTIVE`) and the vehicle must be `IN_SERVICE` (else `ERR_VEHICLE_NOT_IN_SERVICE`); `scheduled_end` must be strictly after `scheduled_start` (else `ERR_VALIDATION`)."

    Design: Corner/validations/trip_create_on_draft_plan_not_active
    """
    ctx = setup_eligible_student()
    plan = create_plan(ctx["student"]["id"], ctx["district"]["id"], route_miles=20)
    veh = create_vehicle(ctx["district"]["id"])
    resp = api.create_trip(
        {"transportation_plan_id": plan["id"], "vehicle_id": veh["id"],
         "scheduled_start": START, "scheduled_end": END}, SC)
    validate_error(resp, ApiErrorId.ERR_PLAN_NOT_ACTIVE.value, 409)


def test_activate_without_cost_share_referential_error(api):
    """PRD §3.5: "It is permitted only from `APPROVED` and enforces two ordered
    gates. First, a referential gate: a `CostShareAgreement` must already exist for
    the plan, else the activation is refused with `ERR_NO_COST_SHARE`."

    Design: Corner/validations/activate_no_cost_share_referential_error
    """
    ctx = setup_eligible_student()
    plan = create_plan(ctx["student"]["id"], ctx["district"]["id"], route_miles=20)
    api.submit_plan(plan["id"], SC)
    api.approve_plan(plan["id"], SC)
    validate_error(api.activate_plan(plan["id"], SC), ApiErrorId.ERR_NO_COST_SHARE.value, 409)


def test_activate_budget_exceeded_fiscal_error(api):
    """PRD §3.5: "Second, a fiscal gate: the serving district's
    `committed_cost_cents` plus the agreement's `serving_share_cents` must not
    exceed the serving district's `transport_budget_cents`, else activation is
    refused with `ERR_BUDGET_EXCEEDED`."

    Design: Corner/validations/activate_budget_exceeded_fiscal_error
    """
    # Serving district budget 1000; route 20 -> serving_share 43200 > 1000.
    ctx = setup_approved_plan(route_miles=20, budget=1000)
    validate_error(api.activate_plan(ctx["plan"]["id"], SC),
                   ApiErrorId.ERR_BUDGET_EXCEEDED.value, 409)


def test_trip_end_before_start_rejected(api):
    """PRD §2.7: "required fields present, enum values in range, all quantity integers non-negative, and any `scheduled_end` strictly after its `scheduled_start`; otherwise `ERR_VALIDATION` (422)."

    Design: Corner/validations/trip_create_end_before_start_invalid
    """
    ctx = setup_active_plan_with_vehicle(route_miles=20)
    resp = api.create_trip(
        {"transportation_plan_id": ctx["plan"]["id"], "vehicle_id": ctx["vehicle"]["id"],
         "scheduled_start": "2026-05-04T09:00:00Z", "scheduled_end": "2026-05-04T08:00:00Z"}, SC)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, 422)


# ---------------------------------------------------------------------------
# Corner: rbac
# ---------------------------------------------------------------------------
def test_registrar_cannot_create_vehicle(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN`."
    PRD §4: vehicle creation is authorized for "TransportCoordinator, StateCoordinator".

    Design: Corner/rbac/registrar_cannot_create_vehicle_forbidden
    """
    d = create_district()
    resp = api.create_vehicle(
        {"serving_district_id": d["id"], "label": "BusX", "capacity_students": 24},
        TEST_USERS["registrar_headers"])
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value, 403)


def test_transport_coordinator_cannot_begin_review(api):
    """PRD §3.4: "The adjudication path belongs exclusively to a `StateCoordinator`,
    except for one resubmission step reserved for the liaison."

    Design: Corner/rbac/transport_coordinator_cannot_begin_review_forbidden
    """
    d = create_district()
    s = create_student(d["id"])
    dsp = create_dispute(s["id"], dispute_type="ENROLLMENT", description="Denied enrollment")
    resp = api.begin_review(dsp["id"], TEST_USERS["transport_coordinator_headers"])
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value, 403)


def test_liaison_cannot_approve_plan(api):
    """PRD §4: plan approval is authorized for "TransportCoordinator,
    StateCoordinator".
    PRD §2.1: "When the headers are well-formed but the named role is not permitted
    to perform the requested operation, the request is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/liaison_cannot_approve_plan_forbidden
    """
    ctx = setup_eligible_student()
    plan = create_plan(ctx["student"]["id"], ctx["district"]["id"], route_miles=20)
    api.submit_plan(plan["id"], SC)
    resp = api.approve_plan(plan["id"], TEST_USERS["liaison_headers"])
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value, 403)


def test_unknown_role_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or `X-User-Role` is not one of the
    recognized role names, the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    bad = build_user_headers("nobody", "NoSuchRole")
    resp = api.get_district("00000000-0000-4000-8000-0000000000d0", bad)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)


# ---------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict — state beats temporal
# ---------------------------------------------------------------------------
def test_suspended_plan_beats_vehicle_conflict(api):
    """PRD §2.7: "the target resource is in a state that permits the transition, else a 409-class state error (see the workflow narratives in §3 for the specific code each transition raises)."
    PRD §3.7: "Trip creation enforces several gates in order: the plan must be `ACTIVE` (else `ERR_PLAN_NOT_ACTIVE`) and the vehicle must be `IN_SERVICE` (else `ERR_VEHICLE_NOT_IN_SERVICE`); `scheduled_end` must be strictly after `scheduled_start` (else `ERR_VALIDATION`)."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_trip_on_suspended_plan
    """
    ctx = setup_active_plan_with_vehicle(route_miles=20)
    create_trip(ctx["plan"]["id"], ctx["vehicle"]["id"], START, END)
    api.suspend_plan(ctx["plan"]["id"], SC)
    # Second window overlaps the first within the 30-minute buffer AND the plan is SUSPENDED.
    resp = api.create_trip(
        {"transportation_plan_id": ctx["plan"]["id"], "vehicle_id": ctx["vehicle"]["id"],
         "scheduled_start": "2026-05-04T08:15:00Z", "scheduled_end": "2026-05-04T08:45:00Z"}, SC)
    validate_error(resp, ApiErrorId.ERR_PLAN_NOT_ACTIVE.value, 409)


def test_suspended_plan_not_active_even_without_time_conflict(api):
    """PRD §3.7: "the plan must be `ACTIVE` (else `ERR_PLAN_NOT_ACTIVE`)".

    Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_trip_on_suspended_plan
    """
    ctx = setup_active_plan_with_vehicle(route_miles=20)
    create_trip(ctx["plan"]["id"], ctx["vehicle"]["id"], START, END)
    api.suspend_plan(ctx["plan"]["id"], SC)
    # A non-overlapping window still fails on plan state alone.
    resp = api.create_trip(
        {"transportation_plan_id": ctx["plan"]["id"], "vehicle_id": ctx["vehicle"]["id"],
         "scheduled_start": "2026-05-04T12:00:00Z", "scheduled_end": "2026-05-04T12:30:00Z"}, SC)
    validate_error(resp, ApiErrorId.ERR_PLAN_NOT_ACTIVE.value, 409)


# ---------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict — state beats referential
# ---------------------------------------------------------------------------
def test_activate_proposed_plan_state_beats_missing_cost_share(api):
    """PRD §2.7: "the target resource is in a state that permits the transition, else a 409-class state error (see the workflow narratives in §3 for the specific code each transition raises)."
    PRD §3.5: "It is permitted only from `APPROVED`"

    Design: Difficulty/priority_pair_validation_conflict/state_beats_referential_activate_wrong_state_no_cost_share
    """
    ctx = setup_eligible_student()
    plan = create_plan(ctx["student"]["id"], ctx["district"]["id"], route_miles=20)
    api.submit_plan(plan["id"], SC)  # plan is PROPOSED, and has no cost-share agreement
    validate_error(api.activate_plan(plan["id"], SC), ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_activate_proposed_plan_leaves_state_unchanged(api):
    """PRD §3.5: "Every transition is valid only from its named source state,
    raising `ERR_INVALID_STATE` otherwise."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_referential_activate_wrong_state_no_cost_share
    """
    ctx = setup_eligible_student()
    plan = create_plan(ctx["student"]["id"], ctx["district"]["id"], route_miles=20)
    api.submit_plan(plan["id"], SC)
    validate_error(api.activate_plan(plan["id"], SC), ApiErrorId.ERR_INVALID_STATE.value, 409)
    still = validate_success(api.get_plan(plan["id"], SC))
    assert still["status"] == "PROPOSED", "rejected activate does not change plan state"


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency — plan approve blocked
# ---------------------------------------------------------------------------
def test_approve_blocked_until_student_eligible(api):
    """PRD §3.5: "Approval is gated by a cross-entity check: the student's
    `eligibility_status` must be `ELIGIBLE`, and if it is not the approval is
    refused with `ERR_STUDENT_NOT_ELIGIBLE`."

    Design: Difficulty/cross_entity_state_dependency/plan_approve_blocked_until_student_eligible
    """
    d = create_district()
    s = create_student(d["id"])  # left UNDETERMINED
    plan = create_plan(s["id"], d["id"], route_miles=20)
    api.submit_plan(plan["id"], SC)
    validate_error(api.approve_plan(plan["id"], SC), ApiErrorId.ERR_STUDENT_NOT_ELIGIBLE.value, 409)


def test_approve_blocked_leaves_plan_proposed(api):
    """PRD §3.5: "Approval is gated by a cross-entity check: the student's
    `eligibility_status` must be `ELIGIBLE`, and if it is not the approval is
    refused with `ERR_STUDENT_NOT_ELIGIBLE`."

    Design: Difficulty/cross_entity_state_dependency/plan_approve_blocked_until_student_eligible
    """
    d = create_district()
    s = create_student(d["id"])
    plan = create_plan(s["id"], d["id"], route_miles=20)
    api.submit_plan(plan["id"], SC)
    validate_error(api.approve_plan(plan["id"], SC), ApiErrorId.ERR_STUDENT_NOT_ELIGIBLE.value, 409)
    still = validate_success(api.get_plan(plan["id"], SC))
    assert still["status"] == "PROPOSED"


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency — trip blocked on out-of-service vehicle
# ---------------------------------------------------------------------------
def test_trip_blocked_on_out_of_service_vehicle(api):
    """PRD §3.7: "the vehicle must be `IN_SERVICE` (else `ERR_VEHICLE_NOT_IN_SERVICE`)".

    Design: Difficulty/cross_entity_state_dependency/trip_create_blocked_when_vehicle_out_of_service
    """
    ctx = setup_active_plan_with_vehicle(route_miles=20)
    api.set_vehicle_status(ctx["vehicle"]["id"], {"status": "OUT_OF_SERVICE"}, SC)
    resp = api.create_trip(
        {"transportation_plan_id": ctx["plan"]["id"], "vehicle_id": ctx["vehicle"]["id"],
         "scheduled_start": START, "scheduled_end": END}, SC)
    validate_error(resp, ApiErrorId.ERR_VEHICLE_NOT_IN_SERVICE.value, 409)


def test_trip_allowed_after_vehicle_back_in_service(api):
    """PRD §3.7: "`IN_SERVICE` and `OUT_OF_SERVICE` may toggle between each other".
    PRD §3.7: "the vehicle must be `IN_SERVICE` (else `ERR_VEHICLE_NOT_IN_SERVICE`)".

    Design: Difficulty/cross_entity_state_dependency/trip_create_blocked_when_vehicle_out_of_service
    """
    ctx = setup_active_plan_with_vehicle(route_miles=20)
    api.set_vehicle_status(ctx["vehicle"]["id"], {"status": "OUT_OF_SERVICE"}, SC)
    api.set_vehicle_status(ctx["vehicle"]["id"], {"status": "IN_SERVICE"}, SC)
    trip = validate_success(api.create_trip(
        {"transportation_plan_id": ctx["plan"]["id"], "vehicle_id": ctx["vehicle"]["id"],
         "scheduled_start": START, "scheduled_end": END}, SC), 201)
    assert trip["status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap — vehicle buffer turnaround
# ---------------------------------------------------------------------------
def test_vehicle_buffer_turnaround_conflict(api):
    """PRD §3.7: "The new window must not overlap another non-terminal trip — one that is `SCHEDULED` or `COMPLETED` — on the **same vehicle** once each existing window is extended by the `VEHICLE_BUFFER_MINUTES` turnaround buffer of **30 minutes**; a conflict raises `ERR_VEHICLE_TIME_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/vehicle_buffer_turnaround_conflict
    """
    ctx = setup_active_plan_with_vehicle(route_miles=20)
    create_trip(ctx["plan"]["id"], ctx["vehicle"]["id"], START, END)  # 08:00-08:30
    # Second window starts 08:45 — 15 minutes after the first ends, inside the 30-min buffer.
    resp = api.create_trip(
        {"transportation_plan_id": ctx["plan"]["id"], "vehicle_id": ctx["vehicle"]["id"],
         "scheduled_start": "2026-05-04T08:45:00Z", "scheduled_end": "2026-05-04T09:15:00Z"}, SC)
    validate_error(resp, ApiErrorId.ERR_VEHICLE_TIME_CONFLICT.value, 409)


def test_vehicle_second_trip_outside_buffer_allowed(api):
    """PRD §3.7: "The new window must not overlap another non-terminal trip — one that is `SCHEDULED` or `COMPLETED` — on the **same vehicle** once each existing window is extended by the `VEHICLE_BUFFER_MINUTES` turnaround buffer of **30 minutes**; a conflict raises `ERR_VEHICLE_TIME_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/vehicle_buffer_turnaround_conflict
    """
    ctx = setup_active_plan_with_vehicle(route_miles=20)
    create_trip(ctx["plan"]["id"], ctx["vehicle"]["id"], START, END)  # 08:00-08:30
    # A window hours later is comfortably outside the turnaround buffer.
    trip = validate_success(api.create_trip(
        {"transportation_plan_id": ctx["plan"]["id"], "vehicle_id": ctx["vehicle"]["id"],
         "scheduled_start": "2026-05-04T12:00:00Z", "scheduled_end": "2026-05-04T12:30:00Z"}, SC), 201)
    assert trip["status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap — district concurrent cap
# ---------------------------------------------------------------------------
def test_district_concurrent_trip_cap_exceeded(api):
    """PRD §3.7: "the new window must not push the number of `SCHEDULED` trips whose half-open windows overlap it, counted across the **same serving district**, beyond the `DISTRICT_CONCURRENT_TRIP_CAP` of **3**; exceeding it raises `ERR_DISTRICT_CAPACITY`."

    Design: Difficulty/resource_temporal_overlap/district_concurrent_trip_cap_exceeded
    """
    ctx = setup_active_plan_with_vehicle(route_miles=20)
    plan_id, d_id = ctx["plan"]["id"], ctx["district"]["id"]
    v1 = ctx["vehicle"]["id"]
    v2 = create_vehicle(d_id, label="Bus2")["id"]
    v3 = create_vehicle(d_id, label="Bus3")["id"]
    v4 = create_vehicle(d_id, label="Bus4")["id"]
    for v in (v1, v2, v3):
        create_trip(plan_id, v, "2026-05-04T08:00:00Z", "2026-05-04T09:00:00Z")
    resp = api.create_trip(
        {"transportation_plan_id": plan_id, "vehicle_id": v4,
         "scheduled_start": "2026-05-04T08:30:00Z", "scheduled_end": "2026-05-04T09:30:00Z"}, SC)
    validate_error(resp, ApiErrorId.ERR_DISTRICT_CAPACITY.value, 409)


def test_district_third_overlapping_trip_at_cap_allowed(api):
    """PRD §3.7: "the new window must not push the number of `SCHEDULED` trips whose half-open windows overlap it, counted across the **same serving district**, beyond the `DISTRICT_CONCURRENT_TRIP_CAP` of **3**; exceeding it raises `ERR_DISTRICT_CAPACITY`."

    Design: Difficulty/resource_temporal_overlap/district_concurrent_trip_cap_exceeded
    """
    ctx = setup_active_plan_with_vehicle(route_miles=20)
    plan_id, d_id = ctx["plan"]["id"], ctx["district"]["id"]
    v1 = ctx["vehicle"]["id"]
    v2 = create_vehicle(d_id, label="Bus2")["id"]
    v3 = create_vehicle(d_id, label="Bus3")["id"]
    create_trip(plan_id, v1, "2026-05-04T08:00:00Z", "2026-05-04T09:00:00Z")
    create_trip(plan_id, v2, "2026-05-04T08:00:00Z", "2026-05-04T09:00:00Z")
    # Third overlapping trip reaches exactly the cap of 3 and is allowed.
    trip = validate_success(api.create_trip(
        {"transportation_plan_id": plan_id, "vehicle_id": v3,
         "scheduled_start": "2026-05-04T08:30:00Z", "scheduled_end": "2026-05-04T09:30:00Z"}, SC), 201)
    assert trip["status"] == "SCHEDULED"
