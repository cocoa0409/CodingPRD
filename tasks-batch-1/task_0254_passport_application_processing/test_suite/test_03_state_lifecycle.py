"""Application lifecycle: the cyclic review loop, the parallel name-change
dimension, valid/invalid transitions, terminal lockdown, idempotency, and
side-effect-bearing transitions.

Difficulty queue: non_linear_state_machine. Corner queue: state_machines section.
"""
from test_helpers import (
    adjudicate_payload,
    make_adjudicator_headers,
    make_agent_headers,
    make_applicant_headers,
    name_change_decide_payload,
    pay_payload,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx


# ════════════════════════════════════════════════════════════════════════
# Difficulty/non_linear_state_machine/application_review_loop_adjudicating_to_review_hold_and_back
# ════════════════════════════════════════════════════════════════════════
def test_return_for_review_sends_adjudicating_to_review_hold(api):
    """PRD §3.9: "Returning for review moves the application from ADJUDICATING back
    to REVIEW_HOLD — a cyclic revert that places the application back in the hold
    queue — appends the corresponding status event, and increments version".

    Design: Difficulty/non_linear_state_machine/application_review_loop_adjudicating_to_review_hold_and_back
    """
    ctx = fx.adjudicating_application(application_type="NEW", product_type="BOOK")
    appl_id = ctx["applicant"]["id"]
    adj_id = ctx["adjudicator"]["id"]
    app_id = ctx["application"]["id"]

    updated = validate_success(
        api.adjudicate(app_id, adjudicate_payload("RETURN_FOR_REVIEW", reason_code="RECHECK"),
                       make_adjudicator_headers(adj_id)), 200)
    assert updated["status"] == "REVIEW_HOLD"


def test_clear_hold_reverts_review_hold_to_in_verification(api):
    """PRD §3.6: "An adjudicator can clear the hold, which reverts the application
    from REVIEW_HOLD back to IN_VERIFICATION (permitted only from REVIEW_HOLD,
    otherwise ERR_INVALID_STATE), appends the corresponding status event, and
    increments version."

    Design: Difficulty/non_linear_state_machine/application_review_loop_adjudicating_to_review_hold_and_back
    """
    ctx = fx.adjudicating_application(application_type="NEW", product_type="BOOK")
    appl_id = ctx["applicant"]["id"]
    adj_id = ctx["adjudicator"]["id"]
    app_id = ctx["application"]["id"]

    validate_success(
        api.adjudicate(app_id, adjudicate_payload("RETURN_FOR_REVIEW", reason_code="RECHECK"),
                       make_adjudicator_headers(adj_id)), 200)
    cleared = validate_success(api.clear_hold(app_id, make_adjudicator_headers(adj_id)), 200)
    assert cleared["status"] == "IN_VERIFICATION"


# ════════════════════════════════════════════════════════════════════════
# Difficulty/non_linear_state_machine/application_name_change_parallel_dimension_independent_of_main_status
#
# Note on PRD-first filtering: the source instance also asserts the main status
# reaches ADJUDICATING after the name-change evidence is accepted. PRD §3.6 states
# the auto-advance out of verification "additionally requires the name-change
# dimension to be either NONE or APPROVED, so a name change that is still pending
# or merely evidence-verified holds the application in verification". Since the
# accept leaves name_change_status == EVIDENCE_VERIFIED, the main status is held at
# IN_VERIFICATION — that is the uniquely-derivable PRD outcome, and is precisely
# the "independent axes" the instance is about. The ADJUDICATING assertion is NOT
# PRD-derivable, so it is dropped (gaps stay gaps).
# ════════════════════════════════════════════════════════════════════════
def test_name_change_status_pending_evidence_at_creation(api):
    """PRD §3.2: "If the application is created with name_change_requested set to
    true, the system immediately moves name_change_status from NONE to
    PENDING_EVIDENCE as a creation-time side effect, while the main status remains
    DRAFT."

    Design: Difficulty/non_linear_state_machine/application_name_change_parallel_dimension_independent_of_main_status
    """
    applicant = fx.create_applicant(date_of_birth="1988-01-01")
    application = fx.create_application(applicant["id"], application_type="RENEWAL",
                                        product_type="BOOK", name_change_requested=True,
                                        prior_name="Jane Old")
    assert application["name_change_status"] == "PENDING_EVIDENCE"
    assert application["status"] == "DRAFT"


def test_name_change_advances_to_evidence_verified_independently_of_main_status(api):
    """PRD §3.4: "The sub-status then advances from PENDING_EVIDENCE to
    EVIDENCE_VERIFIED automatically as a cascade when a supporting document of
    category NAME_CHANGE_EVIDENCE is accepted (moves from PENDING to ACCEPTED)".
    PRD §3.6: the main-status auto-advance "additionally requires the name-change
    dimension to be either NONE or APPROVED, so a name change that is still pending
    or merely evidence-verified holds the application in verification".

    Design: Difficulty/non_linear_state_machine/application_name_change_parallel_dimension_independent_of_main_status
    """
    ctx = fx.name_change_evidence_verified()
    appl_id = ctx["applicant"]["id"]
    app = validate_success(
        api.get_application(ctx["application"]["id"], make_applicant_headers(appl_id)), 200)
    assert app["name_change_status"] == "EVIDENCE_VERIFIED"
    # Main status is held in verification because the name-change is unresolved.
    assert app["status"] == "IN_VERIFICATION"


# ════════════════════════════════════════════════════════════════════════
# Corner/state_machines/application_initial_state_is_draft
# ════════════════════════════════════════════════════════════════════════
def test_application_starts_in_draft(api):
    """PRD §3.2: "The application begins with status equal to DRAFT." PRD §3.2: "The
    application also carries a parallel name-change sub-status, name_change_status,
    which is independent of the main status and which begins at NONE."

    Design: Corner/state_machines/application_initial_state_is_draft
    """
    applicant = fx.create_applicant()
    application = fx.create_application(applicant["id"], application_type="NEW", product_type="BOOK")
    assert application["status"] == "DRAFT"
    assert application["name_change_status"] == "NONE"


# ════════════════════════════════════════════════════════════════════════
# Corner/state_machines/submit_from_draft_valid_transition_creates_fee_and_event
# ════════════════════════════════════════════════════════════════════════
def test_submit_creates_unpaid_fee_and_status_event(api):
    """PRD §3.3: "When submission succeeds, the system performs a coordinated set of
    side effects: it stamps submitted_at to the current clock; ... it creates the
    application's fee assessment with payment_status UNPAID ...; it appends an
    ApplicationStatusEvent recording the move from DRAFT to SUBMITTED".

    Design: Corner/state_machines/submit_from_draft_valid_transition_creates_fee_and_event
    """
    ctx = fx.submitted_application(application_type="NEW", product_type="BOOK")
    appl_id = ctx["applicant"]["id"]
    app_id = ctx["application"]["id"]
    assert ctx["application"]["status"] == "SUBMITTED"
    assert ctx["fee"]["payment_status"] == "UNPAID"

    events, _ = fx._list(api.list_status_events(app_id, make_applicant_headers(appl_id)))
    assert any(e["to_status"] == "SUBMITTED" for e in events), \
        "expected a status event with to_status SUBMITTED"


# ════════════════════════════════════════════════════════════════════════
# Corner/state_machines/begin_verification_from_draft_invalid_state
# ════════════════════════════════════════════════════════════════════════
def test_begin_verification_from_draft_invalid_state(api):
    """PRD §3.6: "After the fee is paid, an acceptance agent begins verification,
    advancing the application from SUBMITTED to IN_VERIFICATION. This is permitted
    only when the application is SUBMITTED (otherwise ERR_INVALID_STATE)".

    Design: Corner/state_machines/begin_verification_from_draft_invalid_state
    """
    facility = fx.create_facility()
    agent = fx.create_agent(facility["id"])
    applicant = fx.create_applicant()
    application = fx.create_application(applicant["id"], application_type="NEW", product_type="BOOK")
    res = api.begin_verification(application["id"], make_agent_headers(agent["id"]))
    validate_error(res, "ERR_INVALID_STATE")


# ════════════════════════════════════════════════════════════════════════
# Corner/state_machines/clear_hold_from_in_verification_invalid_state
# ════════════════════════════════════════════════════════════════════════
def test_clear_hold_from_in_verification_invalid_state(api):
    """PRD §3.6: the clear-hold revert is "permitted only from REVIEW_HOLD,
    otherwise ERR_INVALID_STATE".

    Design: Corner/state_machines/clear_hold_from_in_verification_invalid_state
    """
    ctx = fx.in_verification_application(application_type="NEW", product_type="BOOK")
    adjudicator = fx.create_adjudicator()
    res = api.clear_hold(ctx["application"]["id"], make_adjudicator_headers(adjudicator["id"]))
    validate_error(res, "ERR_INVALID_STATE")


# ════════════════════════════════════════════════════════════════════════
# Corner/state_machines/withdraw_from_issued_terminal_lockdown
# ════════════════════════════════════════════════════════════════════════
def test_withdraw_from_issued_already_terminal(api):
    """PRD §3.9: "ISSUED is terminal." PRD §2.9: "a resource already in a terminal
    state rejects any further transition with ERR_ALREADY_TERMINAL. The terminal
    states are: applications in ISSUED, REJECTED, or WITHDRAWN".

    Design: Corner/state_machines/withdraw_from_issued_terminal_lockdown
    """
    ctx = fx.issued_application(application_type="NEW", product_type="BOOK")
    appl_id = ctx["applicant"]["id"]
    assert ctx["application"]["status"] == "ISSUED"
    res = api.withdraw_application(ctx["application"]["id"], make_applicant_headers(appl_id))
    validate_error(res, "ERR_ALREADY_TERMINAL")


# ════════════════════════════════════════════════════════════════════════
# Corner/state_machines/pay_fee_twice_idempotency_second_rejected
# ════════════════════════════════════════════════════════════════════════
def test_pay_fee_twice_second_rejected_and_ledger_not_doubled(api):
    """PRD §3.5: "A payment attempt on an assessment not in UNPAID is rejected with
    ERR_INVALID_STATE". PRD §3.5: "the owning applicant's total_fees_paid_cents is
    incremented by total_due_cents".

    Design: Corner/state_machines/pay_fee_twice_idempotency_second_rejected
    """
    ctx = fx.paid_application(application_type="NEW", product_type="BOOK")
    appl_id = ctx["applicant"]["id"]
    fee = ctx["fee"]
    res = api.pay_fee_assessment(fee["id"], pay_payload(fee["total_due_cents"]),
                                 make_applicant_headers(appl_id))
    validate_error(res, "ERR_INVALID_STATE")
    applicant = validate_success(api.get_applicant(appl_id, make_applicant_headers(appl_id)), 200)
    assert applicant["total_fees_paid_cents"] == 16500


# ════════════════════════════════════════════════════════════════════════
# Corner/state_machines/issue_marks_booked_appointment_completed_cascade
# ════════════════════════════════════════════════════════════════════════
def test_issue_marks_booked_facility_appointment_completed(api):
    """PRD §3.9: "Issuance marks any BOOKED appointment for the application as
    COMPLETED, appends a status event from APPROVED to ISSUED, and increments
    version."

    Design: Corner/state_machines/issue_marks_booked_appointment_completed_cascade
    """
    ctx = fx.adjudicating_application(application_type="NEW", product_type="BOOK")
    appl_id = ctx["applicant"]["id"]
    adj_id = ctx["adjudicator"]["id"]
    app_id = ctx["application"]["id"]
    facility = ctx["facility"]

    version = fx.current_version(app_id, appl_id)
    appt = fx.book_facility_appointment(app_id, appl_id, facility["id"],
                                        "2026-06-09T09:00:00Z", "2026-06-09T09:30:00Z", version)
    validate_success(api.adjudicate(app_id, adjudicate_payload("APPROVE"),
                                    make_adjudicator_headers(adj_id)), 200)
    validate_success(api.issue_application(app_id, make_adjudicator_headers(adj_id)), 200)

    appt_after = validate_success(api.get_appointment(appt["id"], make_applicant_headers(appl_id)), 200)
    assert appt_after["status"] == "COMPLETED"


# ════════════════════════════════════════════════════════════════════════
# Corner/state_machines/name_change_decide_approve_applies_full_legal_name
# ════════════════════════════════════════════════════════════════════════
def test_name_change_decide_approve_sets_status_approved(api):
    """PRD §3.4: "Deciding to approve advances name_change_status from
    EVIDENCE_VERIFIED to APPROVED, records the new legal name onto the applicant by
    setting the applicant's full_legal_name to the application's recorded new legal
    name, and increments the application's version by one."

    Design: Corner/state_machines/name_change_decide_approve_applies_full_legal_name
    """
    ctx = fx.name_change_evidence_verified()
    adj_id = ctx["adjudicator"]["id"]
    app_id = ctx["application"]["id"]
    updated = validate_success(
        api.decide_name_change(app_id, name_change_decide_payload("APPROVE"),
                               make_adjudicator_headers(adj_id)), 200)
    assert updated["name_change_status"] == "APPROVED"


# ════════════════════════════════════════════════════════════════════════
# Corner/state_machines/appointment_complete_from_cancelled_invalid_state
# ════════════════════════════════════════════════════════════════════════
def test_complete_cancelled_appointment_already_terminal(api):
    """PRD §3.7: "A complete or cancel attempt on an appointment that is not BOOKED
    is rejected with ERR_INVALID_STATE, and on a COMPLETED or CANCELLED appointment
    with ERR_ALREADY_TERMINAL."

    Design: Corner/state_machines/appointment_complete_from_cancelled_invalid_state
    """
    facility = fx.create_facility()
    agent = fx.create_agent(facility["id"])
    ctx = fx.submitted_application(application_type="NEW", product_type="BOOK")
    appl_id = ctx["applicant"]["id"]
    app_id = ctx["application"]["id"]

    version = fx.current_version(app_id, appl_id)
    appt = fx.book_facility_appointment(app_id, appl_id, facility["id"],
                                        "2026-06-09T09:00:00Z", "2026-06-09T09:30:00Z", version)
    validate_success(api.cancel_appointment(appt["id"], make_applicant_headers(appl_id)), 200)

    res = api.complete_appointment(appt["id"], make_agent_headers(agent["id"]))
    validate_error(res, "ERR_ALREADY_TERMINAL")
