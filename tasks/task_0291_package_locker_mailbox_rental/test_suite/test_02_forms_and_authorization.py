"""Form 1583 state machine, submission rules, and the activation authorization gate.

Covers corner-design 'state_machines' form instances and one cross-entity
difficulty instance (activation blocked by an unverified form).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    make_facility_operator_headers, make_compliance_officer_headers, make_customer_headers,
    create_facility, create_mailbox, create_customer, create_form, add_recipient,
    create_pending_agreement,
    setup_draft_form, setup_submitted_form, setup_rejected_form, setup_verified_form,
)

OP = make_facility_operator_headers()
CO = make_compliance_officer_headers()


def test_verify_form_from_draft_returns_invalid_state(api):
    """PRD §3.2: "Verifying it transitions SUBMITTED → VERIFIED and stamps
    verified_at with the facility's current clock value; verifying anything not in
    SUBMITTED is ERR_INVALID_STATE."

    Design: Corner/state_machines/verify_form_from_draft_returns_invalid_state
    """
    base = setup_draft_form()
    resp = api.verify_form_1583(base["form"]["id"], CO)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    form = validate_success(api.get_form_1583(base["form"]["id"], OP))
    assert form["status"] == "DRAFT", "form must stay DRAFT after a rejected verify"


def test_submit_form_without_recipients_returns_no_recipients(api):
    """PRD §3.2: "Submitting a form requires that it be in DRAFT (or in REJECTED,
    for a resubmission) and that at least one recipient exist on it; a submit with
    no recipients is rejected with ERR_NO_RECIPIENTS, and a submit from any state
    other than DRAFT or REJECTED is rejected as an illegal ERR_INVALID_STATE."

    Design: Corner/state_machines/submit_form_without_recipients_returns_no_recipients
    """
    base = setup_draft_form(with_recipient=False)
    cust_headers = make_customer_headers(base["customer"]["id"])
    resp = api.submit_form_1583(base["form"]["id"], cust_headers)
    validate_error(resp, ApiErrorId.ERR_NO_RECIPIENTS.value)
    form = validate_success(api.get_form_1583(base["form"]["id"], OP))
    assert form["status"] == "DRAFT", "form must stay DRAFT when submit is rejected"


def test_form_reject_resubmit_cycle_increments_submission_count(api):
    """PRD §3.2: "Each successful submission drives the form to SUBMITTED and
    increments submission_count by one. When the submission comes out of REJECTED,
    it additionally clears rejection_reason back to null."

    Design: Corner/state_machines/form_reject_resubmit_cycle_increments_submission_count
    """
    base = setup_rejected_form()
    resp = api.submit_form_1583(base["form"]["id"], OP)
    data = validate_success(resp)
    assert data["status"] == "SUBMITTED", "resubmit moves REJECTED -> SUBMITTED"
    assert data["submission_count"] == 2, "submission_count must be 2 after the second submit"
    assert data["rejection_reason"] is None, "rejection_reason must clear to null on resubmit"


def test_terminal_form_verified_cannot_resubmit(api):
    """PRD §3.2: "The form's status traverses DRAFT, SUBMITTED, VERIFIED, and
    REJECTED, and VERIFIED is the single terminal state."
    PRD §3.2: "a submit from any state other than DRAFT or REJECTED is rejected as
    an illegal ERR_INVALID_STATE."

    Design: Corner/state_machines/terminal_form_verified_cannot_resubmit
    """
    base = setup_verified_form()
    resp = api.submit_form_1583(base["form"]["id"], OP)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    form = validate_success(api.get_form_1583(base["form"]["id"], OP))
    assert form["status"] == "VERIFIED", "VERIFIED is terminal; status must not change"


def test_verify_stamps_verified_at(api):
    """PRD §3.2: "Verifying it transitions SUBMITTED → VERIFIED and stamps
    verified_at with the facility's current clock value; verifying anything not in
    SUBMITTED is ERR_INVALID_STATE."

    Design: Corner/state_machines/verify_form_from_draft_returns_invalid_state
    """
    base = setup_submitted_form()
    resp = api.verify_form_1583(base["form"]["id"], CO)
    data = validate_success(resp)
    assert data["status"] == "VERIFIED", "verify moves SUBMITTED -> VERIFIED"
    assert data["verified_at"] is not None, "verified_at must be stamped on verify"


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency / activation_blocked_by_unverified_form
# ---------------------------------------------------------------------------
def test_activation_blocked_by_unverified_form(api):
    """PRD §3.3: "Activation is gated by three cross-entity conditions evaluated
    together: the referenced Form1583 must be VERIFIED and the referenced Customer
    must be ACTIVE — either failing yields ERR_AUTH_NOT_VERIFIED — and the
    referenced MailboxUnit must be VACANT, failing which yields ERR_MAILBOX_OCCUPIED."

    Design: Difficulty/cross_entity_state_dependency/activation_blocked_by_unverified_form
    """
    fac = create_facility(name="F13")
    box = create_mailbox(fac["id"], size_tier="MEDIUM", monthly_fee_cents=3000)
    cust = create_customer(fac["id"], email="c13@x.com")
    form = create_form(fac["id"], cust["id"])
    add_recipient(form["id"])
    get_success_data(api.submit_form_1583(form["id"], OP))  # leave SUBMITTED, not VERIFIED
    agr = create_pending_agreement(fac["id"], cust["id"], box["id"], form["id"], term_months=1)

    resp = api.activate_rental_agreement(agr["id"], OP)
    validate_error(resp, ApiErrorId.ERR_AUTH_NOT_VERIFIED.value)
    after = validate_success(api.get_rental_agreement(agr["id"], OP))
    assert after["status"] == "PENDING_AUTH", "agreement must stay PENDING_AUTH while form unverified"


def test_activation_blocked_by_suspended_customer(api):
    """PRD §3.3: "Activation is gated by three cross-entity conditions evaluated
    together: the referenced Form1583 must be VERIFIED and the referenced Customer
    must be ACTIVE — either failing yields ERR_AUTH_NOT_VERIFIED — and the
    referenced MailboxUnit must be VACANT, failing which yields ERR_MAILBOX_OCCUPIED."

    Design: Difficulty/cross_entity_state_dependency/activation_blocked_by_unverified_form
    """
    fac = create_facility(name="F13b")
    box = create_mailbox(fac["id"], size_tier="MEDIUM", monthly_fee_cents=3000)
    cust = create_customer(fac["id"], email="c13b@x.com")
    form = create_form(fac["id"], cust["id"])
    add_recipient(form["id"])
    get_success_data(api.submit_form_1583(form["id"], OP))
    get_success_data(api.verify_form_1583(form["id"], CO))
    agr = create_pending_agreement(fac["id"], cust["id"], box["id"], form["id"], term_months=1)
    # Suspend the customer so the ACTIVE precondition fails.
    get_success_data(api.suspend_customer(cust["id"], CO))

    resp = api.activate_rental_agreement(agr["id"], OP)
    validate_error(resp, ApiErrorId.ERR_AUTH_NOT_VERIFIED.value)
    after = validate_success(api.get_rental_agreement(agr["id"], OP))
    assert after["status"] == "PENDING_AUTH", "agreement must stay PENDING_AUTH while customer suspended"
