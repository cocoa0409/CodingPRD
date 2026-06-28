"""Corner coverage — state machines: invalid transitions, precondition
enforcement, initial state, guarded transitions, and the reject-limit lock.
"""
from test_helpers import (
    validate_success, validate_error,
    create_office, create_client, create_return, add_document, set_document_received,
    setup_office_with_preparer, setup_return_in_docs_pending, setup_return_prepared,
    setup_return_accepted, create_audit_protection,
    setup_accepted_return_with_disbursed_advance_and_pending_transfer,
    cycle_return_through_rejections,
    api_client, TEST_USERS, make_tax_preparer_headers,
)

OM = TEST_USERS["office_manager_headers"]
FD = TEST_USERS["front_desk_headers"]
BO = TEST_USERS["bank_officer_headers"]


def test_cancel_completed_appointment_invalid_state(api):
    """PRD §3.2: "COMPLETED, NO_SHOW, and CANCELLED are terminal."
    PRD §2.5: "the target resource is in a state from which the requested
    transition is defined (ERR_INVALID_STATE, 409)"

    Design: Corner/state_machines/cancel_appointment_from_completed_returns_invalid_state
    """
    office, _, prep, _ = setup_office_with_preparer(credential_overrides={"ptin": "P60606060"})
    client = create_client(office["id"], full_name="Te Cli", ssn_last4="3838")
    appt = validate_success(api.create_appointment(
        office["id"],
        {"client_id": client["id"], "preparer_id": prep["id"],
         "start_utc": "2026-05-02T09:00:00Z", "end_utc": "2026-05-02T10:00:00Z"}, FD), 201)
    validate_success(api.set_clock({"to_iso8601": "2026-05-02T09:30:00Z"}, OM), 200)
    validate_success(api.transition_appointment(appt["id"], {"to": "CHECKED_IN"}, FD), 200)
    validate_success(api.transition_appointment(appt["id"], {"to": "COMPLETED"}, FD), 200)

    res = api.transition_appointment(appt["id"], {"to": "CANCELLED"}, FD)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    after = validate_success(api.get_appointment(appt["id"], FD), 200)
    assert after["status"] == "COMPLETED"


def test_docs_pending_without_documents_no_documents(api):
    """PRD §3.4: "Moving from INTAKE to DOCS_PENDING requires that at least one
    DocumentIntake row exists for the return; with zero documents the move is
    rejected with ERR_NO_DOCUMENTS."

    Design: Corner/state_machines/docs_pending_without_documents_returns_no_documents
    """
    office = create_office()
    client = create_client(office["id"], full_name="Nd Cli", ssn_last4="3939")
    ret = create_return(office["id"], client["id"], tax_year=2025)
    res = api.transition_return(ret["id"], {"to": "DOCS_PENDING"}, FD)
    validate_error(res, "ERR_NO_DOCUMENTS", expected_status=409)
    after = validate_success(api.get_return(ret["id"], FD), 200)
    assert after["status"] == "INTAKE"


def test_in_prep_with_required_doc_pending_required_docs_missing(api):
    """PRD §3.4: "every DocumentIntake whose is_required is true must be in
    either RECEIVED or WAIVED status (a still-PENDING required document fails),
    else ERR_REQUIRED_DOCS_MISSING"

    Design: Corner/state_machines/in_prep_with_required_doc_pending_returns_required_docs_missing
    """
    office, _, prep, prep_headers = setup_office_with_preparer(credential_overrides={"ptin": "P70707070"})
    client = create_client(office["id"], full_name="Rd Cli", ssn_last4="4040")
    ret = create_return(office["id"], client["id"], tax_year=2025)
    add_document(ret["id"], FD, is_required=True)  # left PENDING
    validate_success(api.assign_return(ret["id"], {"preparer_id": prep["id"]}, OM), 200)
    validate_success(api.transition_return(ret["id"], {"to": "DOCS_PENDING"}, FD), 200)

    res = api.transition_return(ret["id"], {"to": "IN_PREP"}, prep_headers)
    validate_error(res, "ERR_REQUIRED_DOCS_MISSING", expected_status=409)
    after = validate_success(api.get_return(ret["id"], prep_headers), 200)
    assert after["status"] == "DOCS_PENDING"


def test_in_prep_without_preparer_preparer_not_assigned(api):
    """PRD §3.4: "the return must have a non-null preparer_id, else
    ERR_PREPARER_NOT_ASSIGNED"

    Design: Corner/state_machines/in_prep_without_preparer_returns_preparer_not_assigned
    """
    office = create_office()
    client = create_client(office["id"], full_name="Np Cli", ssn_last4="4141")
    ret = create_return(office["id"], client["id"], tax_year=2025)
    doc = add_document(ret["id"], FD, is_required=True)
    validate_success(api.set_document_status(doc["id"], {"status": "WAIVED"}, FD), 200)
    validate_success(api.transition_return(ret["id"], {"to": "DOCS_PENDING"}, FD), 200)

    # No preparer assigned; act as a TaxPreparer (id need not match any preparer).
    res = api.transition_return(
        ret["id"], {"to": "IN_PREP"}, make_tax_preparer_headers("00000000-0000-4000-8000-000000000abc"))
    validate_error(res, "ERR_PREPARER_NOT_ASSIGNED", expected_status=409)
    after = validate_success(api.get_return(ret["id"], FD), 200)
    assert after["status"] == "DOCS_PENDING"


def test_efile_ack_from_prepared_invalid_state(api):
    """PRD §2.5: "the target resource is in a state from which the requested
    transition is defined (ERR_INVALID_STATE, 409)"
    PRD §3.5: "The IRS acknowledgement is recorded by the TaxPreparer against
    the open transmission"

    Design: Corner/state_machines/efile_ack_from_prepared_returns_invalid_state
    """
    ctx = setup_return_prepared(return_overrides={"complexity_band": "SIMPLE"})
    rid = ctx["return"]["id"]
    res = api.efile_ack_return(rid, {"ack_status": "ACCEPTED"}, ctx["prep_headers"])
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    after = validate_success(api.get_return(rid, ctx["prep_headers"]), 200)
    assert after["status"] == "PREPARED"


def test_efile_ack_rejected_without_code_reject_code_required(api):
    """PRD §3.5: "When ack_status is REJECTED, a reject_code must be supplied,
    else ERR_REJECT_CODE_REQUIRED"

    Design: Corner/state_machines/efile_ack_rejected_without_code_returns_reject_code_required
    """
    ctx = setup_return_prepared(return_overrides={"complexity_band": "SIMPLE"})
    rid = ctx["return"]["id"]
    ph = ctx["prep_headers"]
    validate_success(api.efile_return(rid, ph), 200)
    res = api.efile_ack_return(rid, {"ack_status": "REJECTED"}, ph)
    validate_error(res, "ERR_REJECT_CODE_REQUIRED", expected_status=422)
    after = validate_success(api.get_return(rid, ph), 200)
    assert after["status"] == "EFILED_PENDING"


def test_new_return_initial_state_is_intake(api):
    """PRD §3.3: "A new return opens in INTAKE status"

    Design: Corner/state_machines/initial_state_of_new_return_is_intake
    """
    office = create_office()
    client = create_client(office["id"], full_name="It Cli", ssn_last4="4444")
    ret = create_return(office["id"], client["id"], tax_year=2025)
    assert ret["status"] == "INTAKE"


def test_cancel_audit_protection_after_return_accepted_rejected(api):
    """PRD §3.6: "The officer may later cancel an ACTIVE add-on, moving it to
    CANCELLED, but only while the linked return is not yet EFILED_ACCEPTED;
    cancelling protection once the return has been accepted is rejected with
    ERR_RETURN_ALREADY_ACCEPTED."

    Design: Corner/state_machines/cancel_audit_protection_after_return_accepted_rejected
    """
    # Build PREPARED return at bank office, add AP, then accept the return.
    ctx = setup_return_prepared(
        bank_product_enabled=True,
        client_overrides={"risk_band": "LOW"},
        return_overrides={"complexity_band": "SIMPLE", "expected_refund_cents": 500000})
    rid = ctx["return"]["id"]
    ph = ctx["prep_headers"]
    ap = create_audit_protection(rid)
    validate_success(api.efile_return(rid, ph), 200)
    validate_success(api.efile_ack_return(rid, {"ack_status": "ACCEPTED"}, ph), 200)

    res = api.cancel_audit_protection(ap["id"], BO)
    validate_error(res, "ERR_RETURN_ALREADY_ACCEPTED", expected_status=409)
    ap_after = validate_success(api.get_audit_protection(ap["id"], BO), 200)
    assert ap_after["status"] == "ACTIVE"


def test_refund_transfer_cancel_blocked_when_advance_disbursed(api):
    """PRD §3.7: "A pending transfer can also be cancelled by a
    BankProductOfficer or OfficeManager, moving it to CANCELLED, but only when
    no linked RefundAdvance is in DISBURSED; cancelling while a linked advance is
    disbursed is rejected with ERR_ADVANCE_ALREADY_DISBURSED."

    Design: Corner/state_machines/refund_transfer_cancel_blocked_when_advance_disbursed
    """
    ctx, rt, adv = setup_accepted_return_with_disbursed_advance_and_pending_transfer(
        advance_cents=60000)
    res = api.cancel_refund_transfer(rt["id"], BO)
    validate_error(res, "ERR_ADVANCE_ALREADY_DISBURSED", expected_status=409)
    rt_after = validate_success(api.get_refund_transfer(rt["id"], BO), 200)
    assert rt_after["status"] == "PENDING_FUNDING"


def test_reject_limit_reached_locks_correction_loop(api):
    """PRD §3.5: "provided the return's reject_count is at most 3; once a fourth
    rejection would be in play — that is, when reject_count already exceeds 3 —
    the return is locked and the move is rejected with ERR_REJECT_LIMIT_REACHED."

    Design: Corner/state_machines/reject_limit_reached_locks_correction_loop
    """
    # Cycle through 4 rejections so reject_count == 4 and status == EFILED_REJECTED.
    ctx = cycle_return_through_rejections(4)
    rid = ctx["return"]["id"]
    ph = ctx["prep_headers"]
    assert ctx["return"]["reject_count"] == 4
    assert ctx["return"]["status"] == "EFILED_REJECTED"

    res = api.transition_return(rid, {"to": "PREPARED"}, ph)
    validate_error(res, "ERR_REJECT_LIMIT_REACHED", expected_status=409)
    after = validate_success(api.get_return(rid, ph), 200)
    assert after["status"] == "EFILED_REJECTED"
    assert after["reject_count"] == 4
