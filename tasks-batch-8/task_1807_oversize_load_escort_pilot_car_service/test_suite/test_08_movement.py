"""Movement control: depart/hold/resume/deliver, comms protocol, final billing."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    register_carrier,
    register_escort,
    set_clock,
    get_job,
    get_assignment,
    get_leg,
    setup_booked_job,
    setup_en_route_one_position_job,
    setup_delivered_rear_job,
    advance_to_cleared,
    advance_to_scheduled,
    advance_to_en_route,
    offer_and_accept,
    hold_job,
    resume_job,
    deliver_job,
    check_in,
    make_escort_operator_headers,
    api_client,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]


def test_hold_resume_cycle_reenterable(api):
    """PRD §3.6: "A `Dispatcher` places an `EN_ROUTE` job on hold, moving it to
    `ON_HOLD`, and later resumes an `ON_HOLD` job, returning it to `EN_ROUTE`;
    each action rejects any other source status with `ERR_JOB_INVALID_STATE`.
    The hold–resume loop may repeat as often as operations require."

    Design: Difficulty/non_linear_state_machine/job_hold_resume_cycle
    """
    bundle = setup_en_route_one_position_job(escort_name="Solo Rider")
    job_id = bundle["job"]["id"]

    held = hold_job(job_id)
    assert held["job_status"] == "ON_HOLD"

    resumed = resume_job(job_id)
    assert resumed["job_status"] == "EN_ROUTE", "the cycle closes back to EN_ROUTE"

    held_again = hold_job(job_id)
    assert held_again["job_status"] == "ON_HOLD", (
        "ON_HOLD is re-entered after a resume — not a one-way latch"
    )


def test_hold_resume_version_increments_by_one(api):
    """PRD §2.5: "`version` (integer): a system-managed integer that increments
    by exactly 1 on every modification of the resource, including system-driven
    cascade mutations."

    Design: Difficulty/non_linear_state_machine/job_hold_resume_cycle
    """
    bundle = setup_en_route_one_position_job(escort_name="Solo Rider")
    job_id = bundle["job"]["id"]
    depart_version = bundle["job"]["version"]

    v1 = hold_job(job_id)["version"]
    assert v1 == depart_version + 1
    v2 = resume_job(job_id)["version"]
    assert v2 == v1 + 1
    v3 = hold_job(job_id)["version"]
    assert v3 == v2 + 1
    assert get_job(job_id)["version"] == v3


def test_deliver_requires_en_route(api):
    """PRD §3.6: "Delivery closes the movement. A `Dispatcher` delivers an
    `EN_ROUTE` job — any other status is rejected with `ERR_JOB_INVALID_STATE`"

    Design: Corner/state_machines/deliver_requires_en_route
    """
    carrier = register_carrier(10_000_000, "Deliver Co")
    esc = register_escort(("TX",), "Rider D")
    bundle = setup_booked_job(carrier, load_description="D")
    bundle["escort"] = esc
    advance_to_cleared(bundle)
    offer_and_accept(bundle, esc, "REAR")
    advance_to_scheduled(bundle)

    resp = api.deliver_job(bundle["job"]["id"], DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_JOB_INVALID_STATE)

    advance_to_en_route(bundle, "2026-08-10T09:00:00Z")
    hold_job(bundle["job"]["id"])
    resp2 = api.deliver_job(bundle["job"]["id"], DISPATCHER)
    validate_error(resp2, ApiErrorId.ERR_JOB_INVALID_STATE)
    assert get_job(bundle["job"]["id"])["job_status"] == "ON_HOLD"


def test_resume_requires_on_hold(api):
    """PRD §3.6: "A `Dispatcher` places an `EN_ROUTE` job on hold, moving it to
    `ON_HOLD`, and later resumes an `ON_HOLD` job, returning it to `EN_ROUTE`;
    each action rejects any other source status with `ERR_JOB_INVALID_STATE`."

    Design: Corner/state_machines/resume_requires_on_hold
    """
    bundle = setup_en_route_one_position_job(escort_name="Rider R")
    resp = api.resume_job(bundle["job"]["id"], DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_JOB_INVALID_STATE)
    assert get_job(bundle["job"]["id"])["job_status"] == "EN_ROUTE"


def test_comms_overdue_then_checkin_recovers(api):
    """PRD §3.6: "if any `ACTIVE` assignment's `last_checkin_at` is more than
    90 minutes before the current time, the delivery is rejected with
    `ERR_COMMS_CHECKIN_OVERDUE`."
    PRD §3.6: "Each check-in sets the assignment's `last_checkin_at` to the
    current time."

    Design: Corner/validations/comms_overdue_then_checkin_recovers
    """
    bundle = setup_en_route_one_position_job(escort_name="Rider C")
    job_id = bundle["job"]["id"]
    asg = bundle["assignments"][0]

    set_clock("2026-08-10T10:31:00Z")
    resp = api.deliver_job(job_id, DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_COMMS_CHECKIN_OVERDUE)
    assert get_job(job_id)["job_status"] == "EN_ROUTE", "job remains EN_ROUTE on rejection"

    # A fresh check-in restores deliverability without any state regression.
    check_in(asg["id"], asg["escort_id"])
    set_clock("2026-08-10T11:00:00Z")
    delivered = deliver_job(job_id)
    assert delivered["job_status"] == "DELIVERED"
    assert get_assignment(asg["id"])["assignment_status"] == "COMPLETED"


def test_final_billing_minimum_floor(api):
    """PRD §3.6: "the elapsed time between `activated_at` and `completed_at` is
    measured in whole minutes and rounded up to the next whole 30-minute
    increment; the result, expressed in hours with thirty minutes counting as
    half an hour, becomes the assignment's `billable_hours`, subject to a floor
    of four billable hours per assignment; and the `assignment_fee_cents` is
    the billable hours multiplied by the hourly rate of 9,000 cents."

    Design: Corner/calculations/final_billing_minimum_floor
    """
    bundle = setup_delivered_rear_job(deliver_at="2026-08-10T10:00:00Z")
    asg = bundle["assignments"][0]
    assert asg["assignment_status"] == "COMPLETED"
    # max(4, ceil(60/30)/2 = 1.0) = 4.0 billable hours -> 36000 cents.
    assert asg["billable_hours"] == 4.0
    assert asg["assignment_fee_cents"] == 36000
    assert bundle["leg"]["leg_status"] == "COMPLETED"
    assert bundle["job"]["job_status"] == "DELIVERED"


def test_immediate_mutation_visibility(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."
    PRD §2.5: "`version` (integer): a system-managed integer that increments by
    exactly 1 on every modification of the resource, including system-driven
    cascade mutations."

    Design: Corner/consistency_model/immediate_mutation_visibility
    """
    bundle = setup_en_route_one_position_job(escort_name="Rider IM")
    job_id = bundle["job"]["id"]
    depart_version = bundle["job"]["version"]

    held = validate_success(api.hold_job(job_id, DISPATCHER))
    assert held["job_status"] == "ON_HOLD", "the mutation response itself reflects the new state"
    assert held["version"] == depart_version + 1

    fetched = get_job(job_id)
    assert fetched["job_status"] == "ON_HOLD"
    assert fetched["version"] == depart_version + 1, "no lag between write and read"
