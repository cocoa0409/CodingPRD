"""The prerequisite gate: document approval, the PREREQ_PENDING<->TRAINING edges, and
the cross-entity dependency that completing a session requires a TRAINING enrollment.

Translates queue A (non_linear_state_machine/enrollment_training_prereq_revert_branch,
cross_entity_state_dependency/complete_session_requires_enrollment_training) and queue B
(state_machines) instances.
"""
from test_helpers import (
    api_client,
    validate_success, validate_error, validate_error_is_one_of,
    ApiErrorId, TEST_USERS,
    create_program, create_enrollment, submit_prereq, approve_prereq,
    create_instructor, book_session, create_enrollment_in_training,
    make_instructor_headers,
)

ADMIN = TEST_USERS["school_admin_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]


# ---- Queue A: non_linear_state_machine / enrollment_training_prereq_revert_branch ----

def test_expire_dot_medical_reverts_training_to_prereq_pending():
    """PRD §3.2: "Expiry clears the corresponding flag — a DOT_MEDICAL expiry clears
    dot_medical_verified". PRD §3.2: "If clearing a flag leaves either
    dot_medical_verified false or permit_verified false while the enrollment is in
    TRAINING, the enrollment automatically reverts from TRAINING to PREREQ_PENDING".

    Design: Difficulty/non_linear_state_machine/enrollment_training_prereq_revert_branch
    """
    program = create_program()
    eid, med_id, clp_id = create_enrollment_in_training(program["id"])
    # Confirm we are in TRAINING before the revert.
    pre = validate_success(api_client.get_enrollment(eid, REGISTRAR))
    assert pre["status"] == "TRAINING"

    resp = api_client.expire_prereq_document(med_id, ADMIN)
    doc = validate_success(resp)
    assert doc["status"] == "EXPIRED"

    enr = validate_success(api_client.get_enrollment(eid, REGISTRAR))
    assert enr["dot_medical_verified"] is False
    assert enr["status"] == "PREREQ_PENDING"


def test_revert_to_prereq_pending_observable_via_enrollment_status():
    """PRD §3.2: "The moment both dot_medical_verified and permit_verified are true,
    the enrollment automatically advances from PREREQ_PENDING to TRAINING". PRD §3.2:
    "the enrollment automatically reverts from TRAINING to PREREQ_PENDING; this revert
    cancels all of the enrollment's BOOKED clock sessions".

    Design: Difficulty/non_linear_state_machine/enrollment_training_prereq_revert_branch
    """
    program = create_program()
    eid, med_id, clp_id = create_enrollment_in_training(program["id"])
    # Expire the CLP permit instead of the medical to exercise the same backward edge
    # via the other flag.
    api_client.expire_prereq_document(clp_id, ADMIN)
    enr = validate_success(api_client.get_enrollment(eid, REGISTRAR))
    assert enr["permit_verified"] is False
    assert enr["status"] == "PREREQ_PENDING"


# ---- Queue A: cross_entity_state_dependency / complete_session_requires_enrollment_training ----

def test_complete_session_rejected_when_enrollment_not_training():
    """PRD §3.3: "Completion requires that the session still be BOOKED, that the owning
    enrollment be in TRAINING (otherwise ERR_ENROLLMENT_NOT_TRAINING)". PRD §3.2: "this
    revert cancels all of the enrollment's BOOKED clock sessions and releases the
    reserved minutes those sessions held".

    Design: Difficulty/cross_entity_state_dependency/complete_session_requires_enrollment_training
    """
    program = create_program()
    instructor = create_instructor()
    eid, med_id, clp_id = create_enrollment_in_training(program["id"])
    sess = book_session(eid, "CLASSROOM", instructor["id"], "2026-03-10T09:00:00Z", 60)
    # Expire DOT-medical: reverts enrollment to PREREQ_PENDING and auto-cancels the session.
    api_client.expire_prereq_document(med_id, ADMIN)

    resp = api_client.complete_clock_session(sess["id"], make_instructor_headers(instructor["id"]))
    # The session was auto-cancelled by the revert, so completing it is rejected; the PRD
    # commits to ERR_ENROLLMENT_NOT_TRAINING when the enrollment is not TRAINING, but the
    # session-state path (ERR_INVALID_STATE) is equally faithful since the session is no
    # longer BOOKED — the index accepts either.
    validate_error_is_one_of(
        resp, [ApiErrorId.ERR_ENROLLMENT_NOT_TRAINING.value, ApiErrorId.ERR_INVALID_STATE.value])
    enr = validate_success(api_client.get_enrollment(eid, REGISTRAR))
    assert enr["status"] == "PREREQ_PENDING"


def test_complete_session_after_revert_leaves_enrollment_prereq_pending():
    """PRD §3.3: "Completion requires that the session still be BOOKED, that the owning
    enrollment be in TRAINING (otherwise ERR_ENROLLMENT_NOT_TRAINING)".

    Design: Difficulty/cross_entity_state_dependency/complete_session_requires_enrollment_training
    """
    program = create_program()
    instructor = create_instructor()
    eid, med_id, clp_id = create_enrollment_in_training(program["id"])
    sess = book_session(eid, "CLASSROOM", instructor["id"], "2026-03-10T09:00:00Z", 60)
    api_client.expire_prereq_document(med_id, ADMIN)

    resp = api_client.complete_clock_session(sess["id"], make_instructor_headers(instructor["id"]))
    validate_error_is_one_of(
        resp, [ApiErrorId.ERR_ENROLLMENT_NOT_TRAINING.value, ApiErrorId.ERR_INVALID_STATE.value])
    # The enrollment did not advance; it remains out of training.
    enr = validate_success(api_client.get_enrollment(eid, REGISTRAR))
    assert enr["status"] == "PREREQ_PENDING"


# ---- Queue B: state_machines ----

def test_approve_already_approved_document_returns_invalid_state():
    """PRD §3.2: "When the Registrar approves a document, the system first confirms it
    is still SUBMITTED". PRD §2.8: "if the target resource is not in a state from which
    the requested transition is defined, the request yields ERR_INVALID_STATE."

    Design: Corner/state_machines/approve_already_approved_document_returns_invalid_state
    """
    program = create_program()
    enr = create_enrollment(program["id"])
    doc = submit_prereq(enr["id"], "DOT_MEDICAL")
    approve_prereq(doc["id"])
    resp = api_client.approve_prereq_document(doc["id"], REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_clock_session_initial_state_booked():
    """PRD §3.3: "A new session is created in BOOKED status".

    Design: Corner/state_machines/clock_session_initial_state_booked
    """
    program = create_program()
    instructor = create_instructor()
    eid, _, _ = create_enrollment_in_training(program["id"])
    resp = api_client.create_clock_session(
        eid, {"phase": "CLASSROOM", "instructor_id": instructor["id"],
              "starts_at": "2026-03-10T09:00:00Z", "duration_minutes": 60}, REGISTRAR)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "BOOKED"


def test_approve_expired_document_rejected():
    """PRD §3.2: "approving a document whose expires_on is at or before the current
    clock time is forbidden and rejected with ERR_DOCUMENT_EXPIRED."

    Design: Corner/state_machines/approve_expired_document_rejected
    """
    program = create_program()
    enr = create_enrollment(program["id"])
    # Default clock is 2026-04-01; expires_on 2026-03-01 is already in the past.
    doc = submit_prereq(enr["id"], "DOT_MEDICAL", expires_on="2026-03-01T00:00:00Z")
    resp = api_client.approve_prereq_document(doc["id"], REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_DOCUMENT_EXPIRED.value)


def test_prereq_approve_bubbles_enrollment_to_training():
    """PRD §3.2: "a DOT_MEDICAL approval sets dot_medical_verified true, and a
    CLP_PERMIT approval sets permit_verified true. The moment both dot_medical_verified
    and permit_verified are true, the enrollment automatically advances from
    PREREQ_PENDING to TRAINING".

    Design: Corner/state_machines/prereq_approve_bubbles_enrollment_to_training
    """
    program = create_program()
    enr = create_enrollment(program["id"])
    med = submit_prereq(enr["id"], "DOT_MEDICAL")
    clp = submit_prereq(enr["id"], "CLP_PERMIT")
    approve_prereq(med["id"])  # first approval — still PREREQ_PENDING
    # Approving the second prerequisite makes both flags true and bubbles to TRAINING.
    api_client.approve_prereq_document(clp["id"], REGISTRAR)
    final = validate_success(api_client.get_enrollment(enr["id"], REGISTRAR))
    assert final["permit_verified"] is True
    assert final["status"] == "TRAINING"
