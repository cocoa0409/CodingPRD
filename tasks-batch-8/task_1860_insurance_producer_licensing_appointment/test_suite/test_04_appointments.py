"""Appointments: the terminate/rescind cycle, just-in-time filing deadlines,
half-open interval adjacency, the one-open-appointment rule, the for-cause
filing deadline, and the rescission license gate (PRD sections 2.5, 2.9, 3.4, 3.5).
"""
from test_helpers import (
    ApiErrorId,
    advance_clock,
    api_client,
    assert_appointment,
    assert_instant_equals,
    create_appointment,
    create_appointment_payload,
    create_producer,
    get_appointment,
    get_license,
    setup_confirmed_license_action,
    setup_jit_scenario,
    setup_producer_with_active_appointment,
    validate_error,
    validate_success,
    DEFAULT_CLOCK_ISO,
    TEST_USERS,
)

LC = TEST_USERS["licensing_coordinator_headers"]
OFFICER_B = TEST_USERS["compliance_officer_b_headers"]


def test_appointment_terminate_rescind_restores_active():
    """PRD section 3.4: "on success the appointment becomes `ACTIVE` with its
    `effective_date` unchanged from creation"
    PRD section 3.4: "Termination begins when a `LicensingCoordinator`
    terminates an `ACTIVE` appointment, supplying a `termination_reason` of
    `VOLUNTARY` or `FOR_CAUSE` — omitting the reason is rejected with
    `ERR_INVALID_REQUEST`."
    PRD section 3.4: "The appointment moves to `TERMINATION_PENDING`, with
    `termination_initiated_at` stamped to the clock."
    PRD section 3.4: "The coordinator may rescind the termination, returning
    the appointment to `ACTIVE` and clearing `termination_reason` and
    `termination_initiated_at` while leaving `effective_date` untouched".

    Design: Difficulty/non_linear_state_machine/appointment_terminate_rescind_cycle
    """
    bundle = setup_producer_with_active_appointment(
        npn="NPN-2006", lines_of_authority=("LIFE",),
        effective_date="2026-01-15T00:00:00Z",
    )
    appointment = bundle["appointment"]
    assert appointment["status"] == "ACTIVE"
    assert_instant_equals(
        appointment["effective_date"], "2026-01-15T00:00:00Z", "effective_date"
    )

    terminated = validate_success(
        api_client.terminate_appointment(
            appointment["id"], {"termination_reason": "FOR_CAUSE"}, LC
        ),
        200,
    )
    assert terminated["status"] == "TERMINATION_PENDING"
    assert terminated["termination_reason"] == "FOR_CAUSE"
    assert_instant_equals(
        terminated["termination_initiated_at"], DEFAULT_CLOCK_ISO,
        "termination_initiated_at stamped to the clock",
    )

    rescinded = validate_success(
        api_client.rescind_termination(appointment["id"], LC), 200
    )
    assert rescinded["status"] == "ACTIVE"
    assert rescinded["termination_reason"] is None
    assert rescinded["termination_initiated_at"] is None
    assert_instant_equals(
        rescinded["effective_date"], "2026-01-15T00:00:00Z",
        "rescission leaves effective_date untouched",
    )


def test_appointment_termination_filing_completes():
    """PRD section 3.4: "the coordinator may file the termination with the
    state, moving the appointment to `TERMINATED` and stamping
    `termination_date` to the clock".

    Design: Difficulty/non_linear_state_machine/appointment_terminate_rescind_cycle
    """
    bundle = setup_producer_with_active_appointment(
        npn="NPN-2007", lines_of_authority=("LIFE",),
        effective_date="2026-01-15T00:00:00Z",
    )
    appointment = bundle["appointment"]

    pending = validate_success(
        api_client.terminate_appointment(
            appointment["id"], {"termination_reason": "VOLUNTARY"}, LC
        ),
        200,
    )
    assert pending["status"] == "TERMINATION_PENDING"

    terminated = validate_success(
        api_client.file_termination(appointment["id"], LC), 200
    )
    assert_appointment(terminated)
    assert terminated["status"] == "TERMINATED"
    assert_instant_equals(
        terminated["termination_date"], DEFAULT_CLOCK_ISO,
        "termination_date stamped to the clock",
    )


def test_jit_filing_at_exact_deadline_timely():
    """PRD section 3.5: "submission automatically creates an appointment with
    `origin` set to `JIT` and status `JIT_PENDING`, whose `lines_of_authority`
    contains exactly the application's `line_of_authority`, whose
    `effective_date` is the application's `submitted_at`, and whose
    `jit_filing_deadline` is fifteen days after `submitted_at`."
    PRD section 3.4: "the clock must not have passed the appointment's
    `jit_filing_deadline`, and filing exactly at the deadline instant is
    timely."

    Design: Difficulty/boundary_precision_check/jit_filing_on_deadline_vs_after
    """
    bundle = setup_jit_scenario(npn="NPN-2012", line_of_authority="LIFE")
    jit = bundle["jit_appointment"]
    assert jit["origin"] == "JIT"
    assert jit["status"] == "JIT_PENDING"
    assert jit["lines_of_authority"] == ["LIFE"]
    assert_instant_equals(
        jit["effective_date"], DEFAULT_CLOCK_ISO,
        "JIT effective_date is the application's submitted_at",
    )
    assert_instant_equals(
        jit["jit_filing_deadline"], "2026-08-16T00:00:00Z",
        "jit_filing_deadline is fifteen days after submitted_at",
    )

    advance_clock("2026-08-16T00:00:00Z")
    filed = validate_success(api_client.file_appointment(jit["id"], LC), 200)
    assert filed["status"] == "ACTIVE", "filing exactly at the deadline is timely"


def test_jit_filing_one_second_late_rejected():
    """PRD section 2.5: "Every just-in-time appointment still `JIT_PENDING`
    whose `jit_filing_deadline` lies strictly before the new time transitions
    to `LAPSED`." PRD section 3.4: "Once the sweep has moved a just-in-time
    appointment to `LAPSED`, filing it is rejected with
    `ERR_JIT_FILING_WINDOW_CLOSED`."

    Design: Difficulty/boundary_precision_check/jit_filing_on_deadline_vs_after
    """
    bundle = setup_jit_scenario(npn="NPN-2013", line_of_authority="LIFE")
    jit = bundle["jit_appointment"]

    # One second past the deadline (submitted 2026-08-01 + 15 days).
    advance_clock("2026-08-16T00:00:01Z")
    lapsed = get_appointment(jit["id"])
    assert lapsed["status"] == "LAPSED"

    resp = api_client.file_appointment(jit["id"], LC)
    validate_error(resp, ApiErrorId.ERR_JIT_FILING_WINDOW_CLOSED)


def test_refile_inside_prior_interval_rejected():
    """PRD section 3.4: "And the requested `effective_date` must not fall
    inside any other of the same subject's appointment intervals in that state,
    where each interval runs from its `effective_date` up to but not including
    its `termination_date`; because the interval is half-open, an effective
    date that exactly equals a prior appointment's termination date does not
    overlap."
    PRD section 3.4: "A violation is rejected with
    `ERR_APPOINTMENT_INTERVAL_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/appointment_refile_adjacency_half_open
    """
    bundle = setup_producer_with_active_appointment(
        npn="NPN-2016", lines_of_authority=("LIFE",),
        effective_date="2026-08-01T00:00:00Z",
    )
    first = bundle["appointment"]
    validate_success(
        api_client.terminate_appointment(
            first["id"], {"termination_reason": "VOLUNTARY"}, LC
        ),
        200,
    )
    advance_clock("2026-08-20T00:00:00Z")
    terminated = validate_success(api_client.file_termination(first["id"], LC), 200)
    assert terminated["status"] == "TERMINATED"
    assert_instant_equals(
        terminated["termination_date"], "2026-08-20T00:00:00Z", "termination_date"
    )

    # 2026-08-19 falls inside [2026-08-01, 2026-08-20).
    resp = api_client.create_appointment(
        create_appointment_payload(
            producer_id=bundle["producer"]["id"], state_code="CA",
            lines_of_authority=["LIFE"],
            effective_date="2026-08-19T00:00:00Z",
        ),
        LC,
    )
    validate_error(resp, ApiErrorId.ERR_APPOINTMENT_INTERVAL_OVERLAP)


def test_refile_at_termination_instant_allowed():
    """PRD section 3.4: "because the interval is half-open, an effective date
    that exactly equals a prior appointment's termination date does not
    overlap."

    Design: Difficulty/resource_temporal_overlap/appointment_refile_adjacency_half_open
    """
    bundle = setup_producer_with_active_appointment(
        npn="NPN-2017", lines_of_authority=("LIFE",),
        effective_date="2026-08-01T00:00:00Z",
    )
    first = bundle["appointment"]
    validate_success(
        api_client.terminate_appointment(
            first["id"], {"termination_reason": "VOLUNTARY"}, LC
        ),
        200,
    )
    advance_clock("2026-08-20T00:00:00Z")
    terminated = validate_success(api_client.file_termination(first["id"], LC), 200)
    assert terminated["status"] == "TERMINATED"

    adjacent = validate_success(
        api_client.create_appointment(
            create_appointment_payload(
                producer_id=bundle["producer"]["id"], state_code="CA",
                lines_of_authority=["LIFE"],
                effective_date="2026-08-20T00:00:00Z",
            ),
            LC,
        ),
        201,
    )
    assert_appointment(adjacent)
    assert adjacent["status"] == "REQUESTED"
    assert_instant_equals(
        adjacent["effective_date"], "2026-08-20T00:00:00Z",
        "adjacent effective date equals the prior termination_date",
    )


def test_second_non_terminal_appointment_rejected():
    """PRD section 3.4: "At most one non-terminal appointment — one in
    `REQUESTED`, `JIT_PENDING`, `ACTIVE`, or `TERMINATION_PENDING` — may exist
    per subject and `state_code`; creating a second is rejected with
    `ERR_APPOINTMENT_ALREADY_ACTIVE`."

    Design: Corner/validations/appointment_already_active_rejected
    """
    producer = create_producer(npn="NPN-3021", full_name="Dup Appt")
    first = create_appointment(
        producer_id=producer["id"], state_code="CA", lines_of_authority=["LIFE"],
        effective_date="2026-08-01T00:00:00Z",
    )
    assert first["status"] == "REQUESTED"

    resp = api_client.create_appointment(
        create_appointment_payload(
            producer_id=producer["id"], state_code="CA",
            lines_of_authority=["LIFE"], effective_date="2026-09-01T00:00:00Z",
        ),
        LC,
    )
    validate_error(resp, ApiErrorId.ERR_APPOINTMENT_ALREADY_ACTIVE)


def test_for_cause_filing_thirty_day_boundary():
    """PRD section 3.4: "a `FOR_CAUSE` termination must be filed no later than
    thirty days after `termination_initiated_at`, and filing later is rejected
    with `ERR_TERMINATION_FILING_OVERDUE`." Both appointments were terminated
    at the default clock 2026-08-01T00:00:00Z, so the deadline is
    2026-08-31T00:00:00Z: filing at that exact instant is timely; one second
    later is overdue.

    Design: Corner/validations/for_cause_filing_30d_boundary
    """
    bundle_a = setup_producer_with_active_appointment(
        npn="NPN-3022", lines_of_authority=("LIFE",),
    )
    validate_success(
        api_client.terminate_appointment(
            bundle_a["appointment"]["id"], {"termination_reason": "FOR_CAUSE"}, LC
        ),
        200,
    )
    bundle_b = setup_producer_with_active_appointment(
        npn="NPN-3023", lines_of_authority=("LIFE",),
    )
    validate_success(
        api_client.terminate_appointment(
            bundle_b["appointment"]["id"], {"termination_reason": "FOR_CAUSE"}, LC
        ),
        200,
    )

    # Exactly terminate + 30 days: timely.
    advance_clock("2026-08-31T00:00:00Z")
    filed_a = validate_success(
        api_client.file_termination(bundle_a["appointment"]["id"], LC), 200
    )
    assert filed_a["status"] == "TERMINATED"
    assert_instant_equals(
        filed_a["termination_date"], "2026-08-31T00:00:00Z", "termination_date"
    )

    # One second past the deadline: overdue.
    advance_clock("2026-08-31T00:00:01Z")
    late_b = api_client.file_termination(bundle_b["appointment"]["id"], LC)
    validate_error(late_b, ApiErrorId.ERR_TERMINATION_FILING_OVERDUE)
    assert (
        get_appointment(bundle_b["appointment"]["id"])["status"]
        == "TERMINATION_PENDING"
    )


def test_rescind_termination_requires_active_license():
    """PRD section 3.4: "rescission requires the subject's license in that
    state to be `ACTIVE`, else `ERR_LICENSE_NOT_ACTIVE`." PRD section 3.3:
    "Reinstatement deliberately does not restore the appointments that were
    cascaded into termination when the suspension landed; a coordinator may
    rescue those individually through rescission (§3.4)."

    Design: Corner/state_machines/rescind_termination_requires_license_active_rejected
    """
    bundle = setup_confirmed_license_action(
        npn="NPN-3010", action_type="SUSPENSION", lines_of_authority=("LIFE",),
    )
    appointment = get_appointment(bundle["appointment"]["id"])
    assert appointment["status"] == "TERMINATION_PENDING"
    assert appointment["termination_reason"] == "LICENSE_INACTIVE"
    assert get_license(bundle["license"]["id"])["status"] == "SUSPENDED"

    blocked = api_client.rescind_termination(appointment["id"], LC)
    validate_error(blocked, ApiErrorId.ERR_LICENSE_NOT_ACTIVE)

    reinstated = validate_success(
        api_client.reinstate_license(bundle["license"]["id"], OFFICER_B), 200
    )
    assert reinstated["status"] == "ACTIVE"

    rescued = validate_success(api_client.rescind_termination(appointment["id"], LC), 200)
    assert rescued["status"] == "ACTIVE"
    assert rescued["termination_reason"] is None
