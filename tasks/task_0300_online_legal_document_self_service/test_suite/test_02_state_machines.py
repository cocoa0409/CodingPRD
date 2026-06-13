"""Project / review / signature / subscription / reminder state machines:
valid edges, the revision cycle, branch asymmetry, terminal lockdown, and
cross-entity state gates.

Queue A (Difficulty): non_linear_state_machine, cross_entity_state_dependency.
Queue B (Corner): state_machines.
"""
from test_helpers import (
    api_client, get_success_data, validate_success, validate_error,
    create_attorney_payload, create_attorney_review_payload,
    create_document_revision_payload, create_signature_request_payload,
    create_document_project_payload, full_answers, partial_answers,
    make_customer_headers, make_attorney_headers, TEST_USERS,
    setup_active_account, create_clause_templates, create_project,
    setup_assembled_project, setup_review_in_review, setup_finalized_with_sent_envelope,
    setup_assembled_with_revision, create_revision, create_attorney, request_review,
)

ADMIN = TEST_USERS["admin_headers"]


# ─── non_linear_state_machine ─────────────────────────

def test_project_revision_cycle_changes_requested_back_to_in_progress(api):
    """PRD §3.5: "If instead the attorney requests changes, the review moves to
    CHANGES_REQUESTED, the attorney's window is released, the project is driven from
    IN_REVIEW to CHANGES_REQUESTED, and the project's newest DocumentRevision (the one
    currently FINAL) is flipped to SUPERSEDED to reflect that the snapshot the attorney
    reviewed is no longer the live draft."
    PRD §3.5: "A project sitting in CHANGES_REQUESTED reopens its revision loop: the
    customer transitions it back to IN_PROGRESS to make edits, retaining the project's
    accumulated provisional_completeness."

    Design: Difficulty/non_linear_state_machine/project_revision_cycle_changes_requested_back_to_in_progress
    """
    ctx = setup_review_in_review(state="CA", document_type="WILL", mandatory_clauses=1)
    ch, ah = ctx["customer_headers"], ctx["attorney_headers"]
    get_success_data(api.transition_attorney_review(
        ctx["review"]["id"], {"to_status": "CHANGES_REQUESTED"}, ah))
    before = get_success_data(api.get_document_project(ctx["project"]["id"], ch))
    assert before["status"] == "CHANGES_REQUESTED", before
    after = get_success_data(api.transition_document_project(
        ctx["project"]["id"], {"to_status": "IN_PROGRESS"}, ch))
    assert after["status"] == "IN_PROGRESS", after


def test_attorney_review_branch_approved_vs_changes_requested(api):
    """PRD §3.5: "If the attorney approves, the review moves to APPROVED (a terminal
    state), the attorney's window is released, and the project is driven back from
    IN_REVIEW to ASSEMBLED so it can be finalized — no money changes hands at approval,
    because the surcharge was already charged at request. If instead the attorney requests
    changes, the review moves to CHANGES_REQUESTED, the attorney's window is released, the
    project is driven from IN_REVIEW to CHANGES_REQUESTED, and the project's newest
    DocumentRevision (the one currently FINAL) is flipped to SUPERSEDED to reflect that the
    snapshot the attorney reviewed is no longer the live draft."

    Design: Difficulty/non_linear_state_machine/attorney_review_branch_approved_vs_changes_requested
    """
    # Branch A: APPROVED -> project ASSEMBLED
    ctxA = setup_review_in_review(state="CA", document_type="WILL", mandatory_clauses=1)
    get_success_data(api.transition_attorney_review(
        ctxA["review"]["id"], {"to_status": "APPROVED"}, ctxA["attorney_headers"]))
    projA = get_success_data(api.get_document_project(ctxA["project"]["id"], ctxA["customer_headers"]))
    assert projA["status"] == "ASSEMBLED", projA

    # Branch B: CHANGES_REQUESTED -> project CHANGES_REQUESTED
    ctxB = setup_review_in_review(state="CA", document_type="WILL", mandatory_clauses=1)
    get_success_data(api.transition_attorney_review(
        ctxB["review"]["id"], {"to_status": "CHANGES_REQUESTED"}, ctxB["attorney_headers"]))
    projB = get_success_data(api.get_document_project(ctxB["project"]["id"], ctxB["customer_headers"]))
    assert projB["status"] == "CHANGES_REQUESTED", projB


# ─── cross_entity_state_dependency ────────────────────

def test_review_request_requires_active_subscription(api):
    """PRD §3.5: "And the project's owning subscription must be ACTIVE at request time;
    if the subscription is PAST_DUE, PENDING_PAYMENT, or CANCELLED, the request is refused
    with ERR_SUBSCRIPTION_NOT_ACTIVE."

    Design: Difficulty/cross_entity_state_dependency/review_request_requires_active_subscription
    """
    ctx = setup_assembled_project(state="CA", document_type="WILL", addon=True, mandatory_clauses=1)
    ch = ctx["customer_headers"]
    att = get_success_data(api.create_attorney(create_attorney_payload(bar_state="CA"), ADMIN))
    # ACTIVE -> PAST_DUE
    get_success_data(api.transition_subscription(ctx["subscription"]["id"], {"to_status": "PAST_DUE"}, ADMIN))
    res = api.create_attorney_review(
        create_attorney_review_payload(ctx["project"]["id"], att["id"],
                                       "2026-03-07T10:00:00.000Z", "2026-03-07T12:00:00.000Z"), ch)
    validate_error(res, "ERR_SUBSCRIPTION_NOT_ACTIVE")


def test_signature_send_requires_final_revision(api):
    """PRD §3.7: "sending requires that the referenced DocumentRevision still be FINAL (a
    SUPERSEDED revision yields ERR_REVISION_SUPERSEDED) and that the owning DocumentProject
    be FINALIZED (otherwise ERR_PROJECT_NOT_FINALIZED)."
    PRD §3.6: "The new revision is the project's FINAL revision; any prior revision of the
    same project that was FINAL is flipped to SUPERSEDED, so exactly one revision per
    project is FINAL at a time."

    Design: Difficulty/cross_entity_state_dependency/signature_send_requires_final_revision
    """
    ctx = setup_assembled_with_revision(state="CA", document_type="WILL", mandatory_clauses=1)
    ch = ctx["customer_headers"]
    rev1 = ctx["revision"]
    sig = get_success_data(api.create_signature_request(
        create_signature_request_payload(rev1["id"], ["s1@x.com"]), ch))
    # A second revision supersedes R1.
    create_revision(ctx["project"], ch)
    get_success_data(api.transition_document_project(ctx["project"]["id"], {"to_status": "FINALIZED"}, ch))
    rev1_after = get_success_data(api.get_document_revision(rev1["id"], ch))
    assert rev1_after["status"] == "SUPERSEDED", rev1_after
    res = api.transition_signature_request(sig["id"], {"to_status": "SENT"}, ch)
    validate_error(res, "ERR_REVISION_SUPERSEDED")


# ─── Queue B (Corner): state_machines ─────────────────

def test_assemble_from_draft_without_questionnaire_invalid_state(api):
    """PRD §3.4: "Assembly is of course only valid from IN_PROGRESS; from any other state
    it is an ERR_INVALID_STATE."

    Design: Corner/state_machines/assemble_from_draft_without_questionnaire_invalid_state
    """
    plan, cust, ch, sub = setup_active_account(state="CA", tier="STANDARD")
    create_clause_templates("WILL", "CA", 1, 0, key_prefix="W")
    proj = create_project(cust, ch, sub, "WILL", "CA", "Draft")
    assert proj["status"] == "DRAFT", proj
    res = api.assemble_document_project(proj["id"], ch)
    validate_error(res, "ERR_INVALID_STATE")


def test_terminal_stored_rejects_further_transition(api):
    """PRD §3.7: "A signed project enters secure storage: the customer transitions it from
    SIGNED to STORED, and any scheduled reminder remains in place."
    PRD §2.9: "the state-validity check that the target resource is in a legal from-state
    for the requested transition (ERR_INVALID_STATE)."

    Design: Corner/state_machines/terminal_stored_rejects_further_transition
    """
    ctx = setup_finalized_with_sent_envelope(
        state="CA", document_type="WILL", signer_emails=["s@x.com"],
        clock_iso="2026-05-01T00:00:00.000Z", mandatory_clauses=1)
    ch = ctx["customer_headers"]
    sig = ctx["signature_request"]
    get_success_data(api.sign_signature_request(sig["id"], {"signer_email": "s@x.com"}, ch))
    stored = get_success_data(api.transition_document_project(
        ctx["project"]["id"], {"to_status": "STORED"}, ch))
    assert stored["status"] == "STORED", stored
    res = api.transition_document_project(ctx["project"]["id"], {"to_status": "ABANDONED"}, ch)
    validate_error(res, "ERR_INVALID_STATE")


def test_signature_request_initial_state_is_draft(api):
    """PRD §3.7: "The envelope is born in DRAFT with signed_count at zero."

    Design: Corner/state_machines/signature_initial_state_is_draft
    """
    ctx = setup_assembled_with_revision(state="CA", document_type="WILL", mandatory_clauses=1)
    ch = ctx["customer_headers"]
    sig = get_success_data(api.create_signature_request(
        create_signature_request_payload(ctx["revision"]["id"], ["a@x.com", "b@x.com"]), ch))
    assert sig["status"] == "DRAFT", sig
    assert sig["signed_count"] == 0, sig


def test_subscription_past_due_to_active_cure_cycle(api):
    """PRD §3.1: "A PAST_DUE subscription may be cured back to ACTIVE, re-enabling those
    paid features; this PAST_DUE → ACTIVE revert may happen repeatedly over the
    subscription's life."

    Design: Corner/state_machines/subscription_past_due_to_active_cure_cycle
    """
    plan, cust, ch, sub = setup_active_account(state="CA", tier="STANDARD")
    get_success_data(api.transition_subscription(sub["id"], {"to_status": "PAST_DUE"}, ADMIN))
    cured = get_success_data(api.transition_subscription(sub["id"], {"to_status": "ACTIVE"}, ADMIN))
    assert cured["status"] == "ACTIVE", cured


def test_reminder_dispatch_before_due_leaves_scheduled(api):
    """PRD §3.7: "The sweep transitions every SCHEDULED reminder whose due_at is at or
    before the current clock to SENT; a reminder whose due_at is still in the future
    relative to the clock is not yet due and, if a dispatch is attempted against it
    directly, is refused with ERR_REMINDER_NOT_DUE."
    PRD §3.7: "The UpdateReminder scheduled when the project reached SIGNED carries a
    due_at set to the moment of signing plus the reminder interval of 90 days, and is
    born SCHEDULED."

    Design: Corner/state_machines/reminder_dispatch_before_due_rejected
    """
    ctx = setup_finalized_with_sent_envelope(
        state="CA", document_type="WILL", signer_emails=["s@x.com"],
        clock_iso="2026-04-01T00:00:00.000Z", mandatory_clauses=1)
    ch = ctx["customer_headers"]
    sig = ctx["signature_request"]
    get_success_data(api.sign_signature_request(sig["id"], {"signer_email": "s@x.com"}, ch))
    # Clock is 2026-04-01; due_at is signing + 90 days => far in the future. Sweep is a no-op.
    get_success_data(api.dispatch_due_reminders(ADMIN))
    res = api.list_update_reminders(ch, params={"document_project_id": ctx["project"]["id"]})
    reminders = res.json()["data"]
    assert len(reminders) == 1, reminders
    assert reminders[0]["status"] == "SCHEDULED", reminders[0]
