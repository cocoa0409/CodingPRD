"""Composite setup helpers.

Every helper builds its preconditions from scratch through the PRD's own endpoints, because
each test starts against an empty database. Setup calls use the lenient success validator so
that a broken precondition surfaces as a setup failure rather than as a confusing assertion.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CLOCK_COMPLETION,
    CLOCK_DOCUMENTATION,
    CLOCK_EXAM_OPEN,
    CLOCK_SETUP,
    LOCATION_PREMIUMS,
)
from .factories import (
    account_status_payload,
    acknowledge_accept_payload,
    acknowledge_reject_payload,
    alcohol_server_payload,
    approve_decision_payload,
    attendance_payload,
    cancel_session_payload,
    class_session_payload,
    course_approval_payload,
    course_payload,
    course_revision_payload,
    dram_shop_document_payload,
    employer_account_payload,
    employer_location_payload,
    end_assignment_payload,
    enrollment_payload,
    open_exam_payload,
    seat_credit_purchase_payload,
    server_assignment_payload,
    state_jurisdiction_payload,
    submit_attempt_payload,
    trainer_credential_payload,
    trainer_payload,
    withdraw_payload,
)
from .test_users import (
    TEST_USERS,
    make_employer_admin_headers,
    make_trainer_headers,
)

ADMIN = TEST_USERS["program_admin_headers"]
REGULATOR = TEST_USERS["state_regulator_headers"]


# --------------------------------------------------------------------------------------
# Readers
# --------------------------------------------------------------------------------------

def get_course_row(course_id, headers=None) -> dict:
    return get_success_data(api_client.get_course(course_id, headers or ADMIN))


def get_approval(approval_id, headers=None) -> dict:
    return get_success_data(api_client.get_course_approval(approval_id, headers or ADMIN))


def get_trainer_row(trainer_id, headers=None) -> dict:
    return get_success_data(api_client.get_trainer(trainer_id, headers or ADMIN))


def get_session(session_id, headers=None) -> dict:
    return get_success_data(api_client.get_class_session(session_id, headers or ADMIN))


def get_server(server_id, headers=None) -> dict:
    return get_success_data(api_client.get_alcohol_server(server_id, headers or ADMIN))


def get_enrollment_row(enrollment_id, headers=None) -> dict:
    return get_success_data(api_client.get_enrollment(enrollment_id, headers or ADMIN))


def get_certificate_row(certificate_id, headers=None) -> dict:
    return get_success_data(api_client.get_certificate(certificate_id, headers or ADMIN))


def get_account(account_id, headers=None) -> dict:
    return get_success_data(api_client.get_employer_account(account_id, headers or ADMIN))


def get_location(location_id, headers=None) -> dict:
    return get_success_data(api_client.get_employer_location(location_id, headers or ADMIN))


def certificates_for_server(server_id, headers=None) -> list:
    return get_success_data(
        api_client.list_certificates(headers or ADMIN, params={"alcohol_server_id": server_id})
    )


def list_dram_shop_documents_for(account_id, headers=None, params=None) -> list:
    return get_success_data(
        api_client.list_dram_shop_documents(account_id, headers or ADMIN, params=params)
    )


def submissions_for_certificate(certificate_id, headers=None, params=None) -> list:
    return get_success_data(
        api_client.list_registry_submissions(certificate_id, headers or ADMIN, params=params)
    )


def attempts_for_enrollment(enrollment_id, headers=None, params=None) -> list:
    return get_success_data(
        api_client.list_exam_attempts(enrollment_id, headers or ADMIN, params=params)
    )


def assignments_at_location(location_id, headers=None, params=None) -> list:
    return get_success_data(
        api_client.list_location_server_assignments(location_id, headers or ADMIN, params=params)
    )


# --------------------------------------------------------------------------------------
# Tier 1: single-resource creation and simple state progression
# --------------------------------------------------------------------------------------

def set_clock(to_iso8601, headers=None) -> dict:
    """Move the logical clock. Setting the clock mutates no entity."""
    return get_success_data(api_client.set_clock(to_iso8601, headers or ADMIN))


def create_jurisdiction(**overrides) -> dict:
    return get_success_data(
        api_client.create_state_jurisdiction(state_jurisdiction_payload(**overrides), ADMIN)
    )


def create_draft_course(**overrides) -> dict:
    return get_success_data(api_client.create_course(course_payload(**overrides), ADMIN))


def create_published_course(**overrides) -> dict:
    """Create a DRAFT catalogue entry and publish it."""
    course = create_draft_course(**overrides)
    return get_success_data(api_client.publish_course(course["id"], ADMIN))


def revise_course_content(course_id, expected_course_version=None, headers=None,
                          **overrides) -> dict:
    """Apply a content revision, declaring the course revision just read."""
    if expected_course_version is None:
        expected_course_version = get_course_row(course_id)["version"]
    return get_success_data(
        api_client.revise_course(
            course_id,
            course_revision_payload(expected_course_version=expected_course_version,
                                    **overrides),
            headers or ADMIN)
    )


def submit_approval(course_id, jurisdiction_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_course_approval(
            course_approval_payload(course_id, jurisdiction_id, **overrides), ADMIN)
    )


def approve_approval(approval_id, **overrides) -> dict:
    return get_success_data(
        api_client.decide_course_approval(approval_id, approve_decision_payload(**overrides),
                                         REGULATOR)
    )


def create_approved_course(jurisdiction_id, course_overrides=None,
                           decision_overrides=None) -> dict:
    """Publish a course and carry it through to an APPROVED approval in one jurisdiction.

    Returns {"course": ..., "approval": ...} with the course row re-read after publication.
    """
    course = create_published_course(**(course_overrides or {}))
    approval = submit_approval(course["id"], jurisdiction_id)
    approval = approve_approval(approval["id"], **(decision_overrides or {}))
    return {"course": get_course_row(course["id"]), "approval": approval}


def register_trainer(**overrides) -> dict:
    return get_success_data(api_client.create_trainer(trainer_payload(**overrides), ADMIN))


def create_certified_trainer(trainer_overrides=None, credential_overrides=None) -> dict:
    """Register a trainer in PROVISIONAL status and credential them to CERTIFIED."""
    trainer = register_trainer(**(trainer_overrides or {}))
    return get_success_data(
        api_client.credential_trainer(
            trainer["id"], trainer_credential_payload(**(credential_overrides or {})), ADMIN)
    )


def create_scheduled_session(course_id, jurisdiction_id, trainer_id,
                             headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_class_session(
            class_session_payload(course_id, jurisdiction_id, trainer_id, **overrides),
            headers or ADMIN)
    )


def register_alcohol_server(jurisdiction_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_alcohol_server(
            alcohol_server_payload(jurisdiction_id, **overrides), ADMIN)
    )


# --------------------------------------------------------------------------------------
# Tier 2: the training-side hierarchy
# --------------------------------------------------------------------------------------

def setup_training_base(clock=CLOCK_SETUP, jurisdiction_overrides=None,
                        course_overrides=None, decision_overrides=None,
                        trainer_overrides=None, credential_overrides=None,
                        session_overrides=None, with_session=True) -> dict:
    """Jurisdiction, published and APPROVED course, CERTIFIED trainer, SCHEDULED class.

    Returns {"jurisdiction", "course", "approval", "trainer", "trainer_headers", "session"}.
    """
    if clock is not None:
        set_clock(clock)
    jurisdiction = create_jurisdiction(**(jurisdiction_overrides or {}))
    catalogue = create_approved_course(jurisdiction["id"],
                                       course_overrides=course_overrides,
                                       decision_overrides=decision_overrides)
    trainer = create_certified_trainer(trainer_overrides=trainer_overrides,
                                       credential_overrides=credential_overrides)
    trainer_headers = make_trainer_headers(trainer["id"])
    base = {
        "jurisdiction": jurisdiction,
        "course": catalogue["course"],
        "approval": catalogue["approval"],
        "trainer": trainer,
        "trainer_headers": trainer_headers,
        "session": None,
    }
    if with_session:
        base["session"] = create_scheduled_session(
            catalogue["course"]["id"], jurisdiction["id"], trainer["id"],
            headers=trainer_headers, **(session_overrides or {}))
    return base


def add_certified_proctor(base, full_name="Ines Vega", email="ines@tips.example",
                          credential_overrides=None) -> dict:
    """A second CERTIFIED trainer, credentialed for the same track and state."""
    return create_certified_trainer(
        trainer_overrides={"full_name": full_name, "email": email},
        credential_overrides=credential_overrides or {})


# --------------------------------------------------------------------------------------
# Tier 2: the employer-side hierarchy
# --------------------------------------------------------------------------------------

def create_employer_account(**overrides) -> dict:
    return get_success_data(
        api_client.create_employer_account(employer_account_payload(**overrides), ADMIN)
    )


def purchase_seats(account_id, seat_quantity=80, unit_price_cents=2500, headers=None) -> dict:
    """Buy prepaid training seats. Answers with the updated employer account."""
    return get_success_data(
        api_client.purchase_seat_credits(
            account_id,
            seat_credit_purchase_payload(seat_quantity=seat_quantity,
                                         unit_price_cents=unit_price_cents),
            headers or ADMIN)
    )


def add_location(account_id, jurisdiction_id, location_name="Alamo Taproom",
                 premise_type="ON_PREMISE", annual_premium_cents=None,
                 headers=None) -> dict:
    if annual_premium_cents is None:
        annual_premium_cents = LOCATION_PREMIUMS.get(location_name, 4821734)
    return get_success_data(
        api_client.create_employer_location(
            account_id,
            employer_location_payload(jurisdiction_id, location_name=location_name,
                                      premise_type=premise_type,
                                      annual_premium_cents=annual_premium_cents),
            headers or ADMIN)
    )


def set_account_status(account_id, account_status, status_reason=None, headers=None) -> dict:
    payload = account_status_payload(account_status)
    if status_reason is not None:
        payload["status_reason"] = status_reason
    return get_success_data(
        api_client.set_employer_account_status(account_id, payload, headers or ADMIN)
    )


def setup_employer_account(jurisdiction_id, seat_quantity=80, unit_price_cents=2500,
                           location_specs=None, account_overrides=None) -> dict:
    """Open an account, buy seats, then add locations in the order supplied.

    `location_specs` is a list of dicts accepted by add_location (location_name,
    premise_type, annual_premium_cents, and an optional jurisdiction_id override).
    Returns {"account", "locations", "employer_headers"} with the account re-read last.
    """
    account = create_employer_account(**(account_overrides or {}))
    employer_headers = make_employer_admin_headers(account["id"])
    if seat_quantity:
        purchase_seats(account["id"], seat_quantity=seat_quantity,
                       unit_price_cents=unit_price_cents, headers=employer_headers)
    if location_specs is None:
        location_specs = [
            {"location_name": "Alamo Taproom"},
            {"location_name": "Riverwalk Cantina"},
        ]
    locations = []
    for spec in location_specs:
        spec = dict(spec)
        locations.append(add_location(account["id"],
                                      spec.pop("jurisdiction_id", jurisdiction_id),
                                      headers=employer_headers, **spec))
    return {
        "account": get_account(account["id"]),
        "locations": locations,
        "employer_headers": employer_headers,
    }


# --------------------------------------------------------------------------------------
# Tier 3: the seat lifecycle and the proctored exam cycle
# --------------------------------------------------------------------------------------

def enroll_server(session_id, alcohol_server_id, sponsoring_employer_account_id=None,
                  headers=None, expected_class_session_version=None, **overrides) -> dict:
    """Claim a seat, declaring the roster revision just read from the session."""
    if expected_class_session_version is None:
        expected_class_session_version = get_session(session_id)["version"]
    payload = enrollment_payload(session_id, alcohol_server_id,
                                 expected_class_session_version, **overrides)
    if sponsoring_employer_account_id is not None:
        payload["sponsoring_employer_account_id"] = sponsoring_employer_account_id
    return get_success_data(api_client.create_enrollment(payload, headers or ADMIN))


def lock_roster(session_id, headers=None) -> dict:
    return get_success_data(api_client.lock_roster(session_id, headers or ADMIN))


def mark_attendance(enrollment_id, attended=True, headers=None) -> dict:
    return get_success_data(
        api_client.mark_attendance(enrollment_id, attendance_payload(attended),
                                   headers or ADMIN)
    )


def withdraw_seat(enrollment_id, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.withdraw_enrollment(enrollment_id, withdraw_payload(**overrides),
                                       headers or ADMIN)
    )


def open_exam(session_id, proctor_trainer_id, headers=None) -> dict:
    return get_success_data(
        api_client.open_exam(session_id, open_exam_payload(proctor_trainer_id),
                             headers or ADMIN)
    )


def open_attempt(enrollment_id, proctor_headers) -> dict:
    """Opening an attempt is a Trainer action, so the proctor's own headers are required."""
    return get_success_data(api_client.open_exam_attempt(enrollment_id, proctor_headers))


def submit_attempt(attempt_id, raw_correct_count, proctor_attestation, proctor_headers) -> dict:
    return get_success_data(
        api_client.submit_exam_attempt(
            attempt_id,
            submit_attempt_payload(raw_correct_count, proctor_attestation),
            proctor_headers)
    )


def sit_exam(enrollment_id, raw_correct_count, proctor_headers,
             proctor_attestation=True) -> dict:
    """Open an attempt on a seat and submit it for scoring."""
    attempt = open_attempt(enrollment_id, proctor_headers)
    return submit_attempt(attempt["id"], raw_correct_count, proctor_attestation,
                          proctor_headers)


def complete_session(session_id, headers=None) -> dict:
    return get_success_data(api_client.complete_class_session(session_id, headers or ADMIN))


def cancel_session(session_id, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.cancel_class_session(session_id, cancel_session_payload(**overrides),
                                        headers or ADMIN)
    )


def run_class_to_completion(base, seats, session=None, proctor_trainer_id=None,
                            proctor_headers=None, exam_open_clock=CLOCK_EXAM_OPEN,
                            completion_clock=CLOCK_COMPLETION) -> dict:
    """Walk a whole class: enrol every seat, lock, mark attendance, open the exam, sit the
    exams, then complete the class so that certificates are issued.

    `seats` is a list of dicts:
      server                  the AlcoholServer row (required)
      attended                default True
      raw_correct_count       default 34; None skips the exam entirely
      proctor_attestation     default True
      sponsor_account_id      default None (a self-pay seat)

    Returns {"session", "enrollments", "attempts", "certificates"} where `certificates`
    lists every certificate now held by the seated servers.
    """
    session = session or base["session"]
    session_id = session["id"]
    trainer_headers = base["trainer_headers"]
    if proctor_trainer_id is None:
        proctor_trainer_id = base["trainer"]["id"]
    if proctor_headers is None:
        proctor_headers = make_trainer_headers(proctor_trainer_id)

    enrollments = []
    for seat in seats:
        enrollments.append(enroll_server(
            session_id, seat["server"]["id"],
            sponsoring_employer_account_id=seat.get("sponsor_account_id")))

    lock_roster(session_id, trainer_headers)
    for seat, enrollment in zip(seats, enrollments):
        mark_attendance(enrollment["id"], seat.get("attended", True), trainer_headers)

    if exam_open_clock is not None:
        set_clock(exam_open_clock)
    open_exam(session_id, proctor_trainer_id, trainer_headers)

    attempts = []
    for seat, enrollment in zip(seats, enrollments):
        if not seat.get("attended", True):
            continue
        raw = seat.get("raw_correct_count", 34)
        if raw is None:
            continue
        attempts.append(sit_exam(enrollment["id"], raw, proctor_headers,
                                 proctor_attestation=seat.get("proctor_attestation", True)))

    if completion_clock is not None:
        set_clock(completion_clock)
    completed = complete_session(session_id, trainer_headers)

    certificates = []
    for seat in seats:
        certificates.extend(certificates_for_server(seat["server"]["id"]))
    return {
        "session": completed,
        "enrollments": [get_enrollment_row(e["id"]) for e in enrollments],
        "attempts": attempts,
        "certificates": certificates,
    }


def certify_one_server(base, server=None, raw_correct_count=34, sponsor_account_id=None,
                       session=None, proctor_trainer_id=None,
                       exam_open_clock=CLOCK_EXAM_OPEN,
                       completion_clock=CLOCK_COMPLETION,
                       server_overrides=None) -> dict:
    """One server walks a whole class and leaves it holding a certificate.

    Returns {"server", "enrollment", "certificate", "session"}.
    """
    if server is None:
        server = register_alcohol_server(base["jurisdiction"]["id"],
                                        **(server_overrides or {}))
    outcome = run_class_to_completion(
        base,
        [{"server": server, "raw_correct_count": raw_correct_count,
          "sponsor_account_id": sponsor_account_id}],
        session=session, proctor_trainer_id=proctor_trainer_id,
        exam_open_clock=exam_open_clock, completion_clock=completion_clock)
    certificates = certificates_for_server(server["id"])
    return {
        "server": get_server(server["id"]),
        "enrollment": outcome["enrollments"][0],
        "certificate": certificates[-1] if certificates else None,
        "session": outcome["session"],
    }


def stage_exam_open(base, servers=None, seats=None, session=None,
                    proctor_trainer_id=None, proctor_headers=None,
                    exam_open_clock=CLOCK_EXAM_OPEN) -> dict:
    """Carry a class as far as EXAM_OPEN and stop: no attempt has been opened yet.

    `seats` is the same seat-spec list `run_class_to_completion` takes, minus the exam keys;
    `servers` is the shorthand for a list of plain attending self-pay seats. When neither is
    given a single fresh server is registered and seated.

    Returns {"session", "servers", "enrollments", "proctor_headers", "proctor_trainer_id"}.
    """
    if seats is None:
        if servers is None:
            servers = [register_alcohol_server(base["jurisdiction"]["id"])]
        seats = [{"server": server} for server in servers]
    session = session or base["session"]
    session_id = session["id"]
    trainer_headers = base["trainer_headers"]
    if proctor_trainer_id is None:
        proctor_trainer_id = base["trainer"]["id"]
    if proctor_headers is None:
        proctor_headers = make_trainer_headers(proctor_trainer_id)

    enrollments = [
        enroll_server(session_id, seat["server"]["id"],
                      sponsoring_employer_account_id=seat.get("sponsor_account_id"))
        for seat in seats
    ]
    lock_roster(session_id, trainer_headers)
    for seat, enrollment in zip(seats, enrollments):
        mark_attendance(enrollment["id"], seat.get("attended", True), trainer_headers)
    if exam_open_clock is not None:
        set_clock(exam_open_clock)
    opened = open_exam(session_id, proctor_trainer_id, trainer_headers)
    return {
        "session": opened,
        "servers": [seat["server"] for seat in seats],
        "enrollments": enrollments,
        "proctor_headers": proctor_headers,
        "proctor_trainer_id": proctor_trainer_id,
    }


# --------------------------------------------------------------------------------------
# Tier 3: staffing, documentation and the registry round trip
# --------------------------------------------------------------------------------------

def assign_server(location_id, alcohol_server_id, role_title="Bartender",
                  headers=None) -> dict:
    return get_success_data(
        api_client.create_server_assignment(
            location_id, server_assignment_payload(alcohol_server_id, role_title=role_title),
            headers or ADMIN)
    )


def end_assignment(assignment_id, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.end_server_assignment(assignment_id, end_assignment_payload(**overrides),
                                         headers or ADMIN)
    )


def issue_dram_shop_document(account_id, headers=None,
                             expected_employer_account_version=None, **overrides) -> dict:
    """Issue documentation, declaring the account revision just read."""
    if expected_employer_account_version is None:
        expected_employer_account_version = get_account(account_id)["version"]
    return get_success_data(
        api_client.issue_dram_shop_document(
            account_id,
            dram_shop_document_payload(expected_employer_account_version, **overrides),
            headers or ADMIN)
    )


def transmit_certificate(certificate_id, headers=None, payload=None) -> dict:
    return get_success_data(
        api_client.transmit_certificate(certificate_id, headers or ADMIN, payload=payload)
    )


def acknowledge_accept(submission_id) -> dict:
    return get_success_data(
        api_client.acknowledge_registry_submission(submission_id,
                                                   acknowledge_accept_payload(), REGULATOR)
    )


def acknowledge_reject(submission_id, rejection_code="NAME_MISMATCH") -> dict:
    return get_success_data(
        api_client.acknowledge_registry_submission(
            submission_id, acknowledge_reject_payload(rejection_code), REGULATOR)
    )


def transmit_and_reject(certificate_id, rejection_code="NAME_MISMATCH",
                        ack_clock=None) -> dict:
    """Drive the registry rejection cascade: transmit, then record a refusal."""
    submission = transmit_certificate(certificate_id)
    if ack_clock is not None:
        set_clock(ack_clock)
    return acknowledge_reject(submission["id"], rejection_code)


def transmit_and_accept(certificate_id, ack_clock=None) -> dict:
    submission = transmit_certificate(certificate_id)
    if ack_clock is not None:
        set_clock(ack_clock)
    return acknowledge_accept(submission["id"])


def run_compliance(headers=None) -> dict:
    """Advance the compliance epoch through its eight ordered phases."""
    return get_success_data(api_client.create_compliance_run(headers or ADMIN))


# --------------------------------------------------------------------------------------
# Tier 4 / 5: full cross-entity scenarios
# --------------------------------------------------------------------------------------

def setup_certified_server_at_location(location_specs=None, seat_quantity=80,
                                      unit_price_cents=2500, raw_correct_count=34,
                                      jurisdiction_overrides=None,
                                      course_overrides=None, session_overrides=None,
                                      credential_overrides=None,
                                      server_overrides=None,
                                      sponsor_enrollment=True,
                                      clock=CLOCK_SETUP) -> dict:
    """The platform's canonical end-to-end state.

    Jurisdiction, approved course, certified trainer and scheduled class; an employer
    account with purchased seats and locations; one server carried through the exam to a
    certificate; and that server assigned to the first location.

    Returns the training base keys plus {"account", "locations", "employer_headers",
    "server", "enrollment", "certificate", "assignment"}.
    """
    base = setup_training_base(clock=clock,
                               jurisdiction_overrides=jurisdiction_overrides,
                               course_overrides=course_overrides,
                               credential_overrides=credential_overrides,
                               session_overrides=session_overrides)
    employer = setup_employer_account(base["jurisdiction"]["id"],
                                      seat_quantity=seat_quantity,
                                      unit_price_cents=unit_price_cents,
                                      location_specs=location_specs)
    walk = certify_one_server(
        base, raw_correct_count=raw_correct_count,
        sponsor_account_id=employer["account"]["id"] if sponsor_enrollment else None,
        server_overrides=server_overrides)
    assignment = assign_server(employer["locations"][0]["id"], walk["server"]["id"],
                               headers=employer["employer_headers"])
    scenario = dict(base)
    scenario.update({
        "account": get_account(employer["account"]["id"]),
        "locations": [get_location(loc["id"]) for loc in employer["locations"]],
        "employer_headers": employer["employer_headers"],
        "server": get_server(walk["server"]["id"]),
        "enrollment": walk["enrollment"],
        "certificate": walk["certificate"],
        "assignment": assignment,
        "session": walk["session"],
    })
    return scenario


def stage_second_class_ready_to_complete(base, server,
                                         schedule_clock="2027-05-01T09:00:00Z",
                                         scheduled_start_at="2027-05-04T14:00:00Z",
                                         scheduled_end_at="2027-05-04T18:00:00Z",
                                         capacity=5,
                                         exam_open_clock="2027-05-04T14:05:00Z",
                                         raw_correct_count=34,
                                         pre_completion_clock="2027-05-04T17:00:00Z") -> dict:
    """Carry `server` through a second class on the same course, stopping one call short.

    The class is left in EXAM_OPEN with the seat already PASSED, so the caller can trigger
    completion itself and observe the certificate that issuance mints.
    Returns {"session", "enrollment", "attempt"}.
    """
    if schedule_clock is not None:
        set_clock(schedule_clock)
    session = create_scheduled_session(
        base["course"]["id"], base["jurisdiction"]["id"], base["trainer"]["id"],
        headers=base["trainer_headers"], scheduled_start_at=scheduled_start_at,
        scheduled_end_at=scheduled_end_at, capacity=capacity)
    enrollment = enroll_server(session["id"], server["id"])
    lock_roster(session["id"], base["trainer_headers"])
    mark_attendance(enrollment["id"], True, base["trainer_headers"])
    if exam_open_clock is not None:
        set_clock(exam_open_clock)
    open_exam(session["id"], base["trainer"]["id"], base["trainer_headers"])
    attempt = sit_exam(enrollment["id"], raw_correct_count, base["trainer_headers"])
    if pre_completion_clock is not None:
        set_clock(pre_completion_clock)
    return {"session": session, "enrollment": enrollment, "attempt": attempt}


def setup_documented_employer(location_specs=None, document_clock=CLOCK_DOCUMENTATION,
                              document_overrides=None, **kwargs) -> dict:
    """The canonical scenario carried one step further: dram-shop documentation issued.

    Adds {"document"} to the scenario dict and re-reads the account.
    """
    scenario = setup_certified_server_at_location(location_specs=location_specs, **kwargs)
    if document_clock is not None:
        set_clock(document_clock)
    document = issue_dram_shop_document(scenario["account"]["id"],
                                        headers=scenario["employer_headers"],
                                        **(document_overrides or {}))
    scenario["document"] = document
    scenario["account"] = get_account(scenario["account"]["id"])
    return scenario
