"""State-machine transition guards, terminal-state lockdown, idempotency, and the
cross-entity state dependencies between assignments, storms, and applications.

Corner queue: state_machines section.
Difficulty queue: cross_entity_state_dependency.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    new_operator, new_storm, new_callout,
    setup_closed_storm, setup_started_assignment, setup_planned_assignment,
    setup_completed_callout, setup_recorded_application, setup_open_complaint,
    activate_storm, start_assignment, make_operator_headers,
)

DISPATCH = TEST_USERS["dispatch_headers"]
YARD = TEST_USERS["yard_headers"]
CITIZEN = TEST_USERS["citizen_headers"]


# --- Corner: state_machines -----------------------------------------------

def test_close_planned_storm_rejected(api):
    """PRD §3.2: "Closing a storm requires it to currently be `ACTIVE`." PRD §3.2:
    "A storm that is not in `ACTIVE` cannot be closed, surfacing the state error for
    that transition."

    Design: Corner/state_machines/close_planned_storm_returns_not_active
    """
    storm = new_storm(severity="LIGHT")
    resp = api.close_storm_event(storm["id"], DISPATCH)
    validate_error(resp, ApiErrorId.ERR_STORM_NOT_ACTIVE.value, 409)
    after = validate_success(api.get_storm_event(storm["id"], DISPATCH), 200)
    assert after["operational_status"] == "PLANNED", after


def test_activate_closed_storm_rejected(api):
    """PRD §3.2: "Attempting to activate or close a storm whose `operational_status`
    is already `CLOSED` is rejected with `ERR_STORM_ALREADY_CLOSED`."

    Design: Corner/state_machines/activate_closed_storm_returns_already_closed
    """
    storm = setup_closed_storm()["storm"]
    resp = api.activate_storm_event(storm["id"], DISPATCH)
    validate_error(resp, ApiErrorId.ERR_STORM_ALREADY_CLOSED.value, 409)


def test_finalize_billing_before_close_rejected(api):
    """PRD §3.2: "It carries the single cross-axis guard: the storm's
    `operational_status` must already be `CLOSED`. If billing finalization is attempted
    while the storm is not closed, it is rejected with `ERR_STORM_NOT_CLOSED`".

    Design: Corner/state_machines/finalize_billing_before_close_returns_not_closed
    """
    storm = new_storm(severity="LIGHT")
    activate_storm(storm["id"])
    resp = api.finalize_billing(storm["id"], DISPATCH)
    validate_error(resp, ApiErrorId.ERR_STORM_NOT_CLOSED.value, 409)
    after = validate_success(api.get_storm_event(storm["id"], DISPATCH), 200)
    assert after["billing_status"] == "OPEN", after


def test_finalize_billing_twice_rejected(api):
    """PRD §3.2: "if attempted while `billing_status` is not `OPEN`, it is rejected with
    `ERR_BILLING_NOT_OPEN`."

    Design: Corner/state_machines/finalize_billing_twice_returns_billing_not_open
    """
    storm = setup_closed_storm()["storm"]
    validate_success(api.finalize_billing(storm["id"], DISPATCH), 200)
    resp = api.finalize_billing(storm["id"], DISPATCH)
    validate_error(resp, ApiErrorId.ERR_BILLING_NOT_OPEN.value, 409)


def test_start_already_in_progress_assignment_rejected(api):
    """PRD §3.5: "Starting requires three things: the assignment must currently be
    `PLANNED` (otherwise `ERR_ASSIGNMENT_NOT_PLANNED`), the owning storm must currently
    be `ACTIVE` (otherwise `ERR_STORM_NOT_ACTIVE`), and the vehicle must currently be
    `AVAILABLE`."

    Design: Corner/state_machines/start_already_in_progress_returns_not_planned
    """
    scene = setup_started_assignment(planned_material_tons=2.0)
    resp = api.start_assignment(scene["assignment"]["id"], DISPATCH)
    validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_NOT_PLANNED.value, 409)


def test_complete_callout_twice_rejected(api):
    """PRD §3.3: "the callout must currently be `ISSUED` or the completion is rejected
    with `ERR_CALLOUT_NOT_ISSUED`."

    Design: Corner/state_machines/complete_callout_twice_returns_not_issued
    """
    scene = setup_completed_callout(severity="MODERATE", hours_worked=5)
    resp = api.complete_callout(scene["callout"]["id"], {"hours_worked": 5},
                                make_operator_headers(scene["operator"]["id"]))
    validate_error(resp, ApiErrorId.ERR_CALLOUT_NOT_ISSUED.value, 409)


def test_resolve_open_complaint_rejected(api):
    """PRD §3.8: "Resolution moves an `INVESTIGATING` complaint to `RESOLVED`." PRD §3.8:
    "Any complaint transition attempted from a state that does not permit it is rejected
    with `ERR_COMPLAINT_INVALID_STATE`."

    Design: Corner/state_machines/resolve_open_complaint_returns_invalid_state
    """
    scene = setup_open_complaint(complaint_type="ICY_CONDITIONS")
    resp = api.resolve_complaint(scene["complaint"]["id"], CITIZEN)
    validate_error(resp, ApiErrorId.ERR_COMPLAINT_INVALID_STATE.value, 409)
    after = validate_success(api.get_complaint(scene["complaint"]["id"], CITIZEN), 200)
    assert after["status"] == "OPEN", after


def test_void_already_voided_application_rejected(api):
    """PRD §3.6: "An application must be `RECORDED` to be voided; voiding one already
    `VOIDED` is rejected with `ERR_APPLICATION_ALREADY_VOIDED`."

    Design: Corner/state_machines/void_already_voided_application
    """
    scene = setup_recorded_application(salt_tons=5.0)
    validate_success(api.void_application(scene["application"]["id"], DISPATCH), 200)
    resp = api.void_application(scene["application"]["id"], DISPATCH)
    validate_error(resp, ApiErrorId.ERR_APPLICATION_ALREADY_VOIDED.value, 409)
    depot = validate_success(api.get_depot(scene["depot"]["id"], YARD), 200)
    assert depot["salt_tons_on_hand"] == 100.00, depot


def test_cancel_already_cancelled_callout_rejected(api):
    """PRD §3.3: "Cancelling an already-`CANCELLED` callout is rejected with
    `ERR_CALLOUT_NOT_CANCELLABLE`."

    Design: Corner/state_machines/cancel_cancelled_callout_returns_not_cancellable
    """
    op = new_operator()
    storm = new_storm(severity="MODERATE")
    co = new_callout(storm["id"], op["id"])
    validate_success(api.cancel_callout(co["id"], DISPATCH), 200)
    resp = api.cancel_callout(co["id"], DISPATCH)
    validate_error(resp, ApiErrorId.ERR_CALLOUT_NOT_CANCELLABLE.value, 409)


# --- Difficulty: cross_entity_state_dependency / assignment_start_requires_storm_active

def test_start_assignment_requires_storm_active(api):
    """PRD §3.5: "Starting requires three things: the assignment must currently be
    `PLANNED` (otherwise `ERR_ASSIGNMENT_NOT_PLANNED`), the owning storm must currently
    be `ACTIVE` (otherwise `ERR_STORM_NOT_ACTIVE`), and the vehicle must currently be
    `AVAILABLE`."

    Design: Difficulty/cross_entity_state_dependency/assignment_start_requires_storm_active
    """
    # Assignment created while the storm is still PLANNED (never activated).
    scene = setup_planned_assignment(planned_material_tons=2.0, activate=False)
    resp = api.start_assignment(scene["assignment"]["id"], DISPATCH)
    validate_error(resp, ApiErrorId.ERR_STORM_NOT_ACTIVE.value, 409)
    after = validate_success(api.get_assignment(scene["assignment"]["id"], DISPATCH), 200)
    assert after["status"] == "PLANNED", after


def test_start_assignment_succeeds_once_storm_active(api):
    """PRD §3.5: "Once planned, an assignment is started by a `DispatchSupervisor`, which
    advances it `PLANNED → IN_PROGRESS` and reserves the truck by setting the vehicle's
    `status` to `ASSIGNED`." PRD §3.5: "the owning storm must currently be `ACTIVE`
    (otherwise `ERR_STORM_NOT_ACTIVE`)".

    Design: Difficulty/cross_entity_state_dependency/assignment_start_requires_storm_active
    """
    scene = setup_planned_assignment(planned_material_tons=2.0, activate=False)
    activate_storm(scene["storm"]["id"])
    data = validate_success(api.start_assignment(scene["assignment"]["id"], DISPATCH), 200)
    assert data["status"] == "IN_PROGRESS", data


# --- Difficulty: cross_entity_state_dependency / application_requires_assignment_in_progress

def test_record_application_on_planned_assignment_rejected(api):
    """PRD §3.6: "The assignment must be `IN_PROGRESS`, or the request is rejected with
    `ERR_ASSIGNMENT_NOT_IN_PROGRESS`."

    Design: Difficulty/cross_entity_state_dependency/application_requires_assignment_in_progress
    """
    scene = setup_planned_assignment(planned_material_tons=2.0)  # storm ACTIVE, assignment PLANNED
    op_headers = make_operator_headers(scene["operator"]["id"])
    resp = api.create_application(scene["assignment"]["id"],
                                  {"depot_id": scene["depot"]["id"], "material_type": "SALT",
                                   "salt_tons": 1.0, "lane_miles_treated": 2.0, "pavement_temp_f": 15},
                                  op_headers)
    validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_NOT_IN_PROGRESS.value, 409)
    depot = validate_success(api.get_depot(scene["depot"]["id"], YARD), 200)
    assert depot["salt_tons_on_hand"] == 100.00, depot


def test_record_application_on_in_progress_assignment_succeeds(api):
    """PRD §3.6: "The assignment must be `IN_PROGRESS`, or the request is rejected with
    `ERR_ASSIGNMENT_NOT_IN_PROGRESS`." PRD §3.6: "The application debits inventory at the
    named depot: a salt application decrements that depot's `salt_tons_on_hand` by
    `salt_tons`".

    Design: Difficulty/cross_entity_state_dependency/application_requires_assignment_in_progress
    """
    scene = setup_started_assignment(planned_material_tons=2.0)  # IN_PROGRESS
    op_headers = make_operator_headers(scene["operator"]["id"])
    resp = api.create_application(scene["assignment"]["id"],
                                  {"depot_id": scene["depot"]["id"], "material_type": "SALT",
                                   "salt_tons": 4.0, "lane_miles_treated": 2.0, "pavement_temp_f": 15},
                                  op_headers)
    data = validate_success(resp, 201)
    assert data["status"] == "RECORDED", data
    depot = validate_success(api.get_depot(scene["depot"]["id"], YARD), 200)
    assert depot["salt_tons_on_hand"] == 96.00, depot
