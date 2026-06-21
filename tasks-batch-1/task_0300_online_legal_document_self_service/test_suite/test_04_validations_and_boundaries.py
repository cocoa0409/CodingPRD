"""Business validations, numeric/empty-collection boundaries, validation-priority
pairs, and resource temporal-overlap (attorney windows, lease terms).

Queue A (Difficulty): priority_pair_validation_conflict, boundary_precision_check,
resource_temporal_overlap.
Queue B (Corner): validations.
"""
from test_helpers import (
    api_client, get_success_data, validate_success, validate_error,
    create_attorney_payload, create_attorney_review_payload,
    create_signature_request_payload, create_document_project_payload,
    full_answers, partial_answers, make_customer_headers, make_attorney_headers, TEST_USERS,
    setup_active_account, create_clause_templates, create_project,
    setup_project_in_progress, setup_assembled_project, setup_assembled_with_revision,
    create_clause_template, create_attorney, create_revision,
)

ADMIN = TEST_USERS["admin_headers"]


# ─── priority_pair_validation_conflict ────────────────

def test_state_beats_fiscal_on_review_request(api):
    """PRD §2.9: "the state-validity check that the target resource is in a legal
    from-state for the requested transition (ERR_INVALID_STATE). Only once all of those
    pass does the system evaluate the domain-specific business rules — subscription-active
    gating, add-on election, completeness gates, review-in-progress gates, scheduling
    overlaps, credit availability, and the rest"
    PRD §2.9: "a request that both targets a resource in the wrong state and would also
    violate a business rule surfaces the state error first."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_review_request
    """
    # Project still IN_PROGRESS (not ASSEMBLED) AND subscription PAST_DUE.
    ctx = setup_project_in_progress(
        state="CA", document_type="WILL", answer_count=2, addon=True, mandatory_clauses=1)
    ch = ctx["customer_headers"]
    att = get_success_data(api.create_attorney(create_attorney_payload(bar_state="CA"), ADMIN))
    get_success_data(api.transition_subscription(ctx["subscription"]["id"], {"to_status": "PAST_DUE"}, ADMIN))
    res = api.create_attorney_review(
        create_attorney_review_payload(ctx["project"]["id"], att["id"],
                                       "2026-03-06T10:00:00.000Z", "2026-03-06T12:00:00.000Z"), ch)
    validate_error(res, "ERR_INVALID_STATE")


def test_referential_beats_constraint_on_assemble(api):
    """PRD §3.4: "Two gates guard the action, and both must hold. First, the project's
    provisional_completeness must have reached completion — it must be at least 1.0; if the
    questionnaire is not fully answered, assembly is refused with
    ERR_QUESTIONNAIRE_INCOMPLETE. Second, at least one ClauseTemplate must exist for the
    project's document_type and state_code pairing; if the library is empty for that
    combination, assembly is refused with ERR_NO_CLAUSE_TEMPLATES."

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_constraint_on_assemble
    """
    # POA/TX, NO clause templates, only 1 of 4 answered.
    plan, cust, ch, sub = setup_active_account(state="TX", tier="STANDARD")
    proj = create_project(cust, ch, sub, "POA", "TX", "POA One")
    get_success_data(api.upsert_questionnaire(proj["id"], {"answers": partial_answers(1)}, ch))
    res = api.assemble_document_project(proj["id"], ch)
    validate_error(res, "ERR_QUESTIONNAIRE_INCOMPLETE")


# ─── boundary_precision_check ─────────────────────────

def test_assemble_completeness_threshold_at_seven_eighths_rejected(api):
    """PRD §3.4: "First, the project's provisional_completeness must have reached
    completion — it must be at least 1.0; if the questionnaire is not fully answered,
    assembly is refused with ERR_QUESTIONNAIRE_INCOMPLETE."
    PRD §3.3: "The denominator, captured on the response as total_required_count, is the
    total number of required questions for the project's document type: 8 for a WILL"

    Design: Difficulty/boundary_precision_check/assemble_completeness_threshold_at_exactly_one
    """
    ctx = setup_project_in_progress(
        state="CA", document_type="WILL", answer_count=7, addon=False, mandatory_clauses=1)
    ch = ctx["customer_headers"]
    assert ctx["project"]["provisional_completeness"] == 0.875, ctx["project"]
    res = api.assemble_document_project(ctx["project"]["id"], ch)
    validate_error(res, "ERR_QUESTIONNAIRE_INCOMPLETE")


def test_assemble_completeness_at_exactly_one_accepted(api):
    """PRD §3.4: "Assembling a project advances it from IN_PROGRESS to ASSEMBLED." ...
    "First, the project's provisional_completeness must have reached completion — it must
    be at least 1.0"

    Design: Difficulty/boundary_precision_check/assemble_completeness_threshold_at_exactly_one
    """
    ctx = setup_project_in_progress(
        state="CA", document_type="WILL", answer_count=8, addon=False, mandatory_clauses=1)
    ch = ctx["customer_headers"]
    assert ctx["project"]["provisional_completeness"] == 1.0, ctx["project"]
    assembled = get_success_data(api.assemble_document_project(ctx["project"]["id"], ch))
    assert assembled["status"] == "ASSEMBLED", assembled


def test_signature_request_empty_signer_list_rejected(api):
    """PRD §3.7: "A Customer creates a SignatureRequest (an e-signature envelope) against
    the FINAL revision by document_revision_id, supplying an ordered, non-empty
    signer_emails list"
    PRD §2.8: "Well-formedness of the request body itself — required fields present, enum
    values within their allowed sets, a non-empty signer list — is enforced with
    ERR_INVALID_REQUEST (HTTP 400)."

    Design: Difficulty/boundary_precision_check/signature_request_empty_signer_list_rejected
    """
    ctx = setup_assembled_with_revision(state="CA", document_type="WILL", mandatory_clauses=1)
    ch = ctx["customer_headers"]
    res = api.create_signature_request(
        create_signature_request_payload(ctx["revision"]["id"], []), ch)
    validate_error(res, "ERR_INVALID_REQUEST")


# ─── resource_temporal_overlap ────────────────────────

def test_attorney_window_half_open_overlap_rejected(api):
    """PRD §3.5: "The window is treated as the half-open interval running from window_start
    up to but not including window_end, and it must not overlap any other non-CANCELLED
    review already held by the same attorney; a back-to-back pairing where one window ends
    exactly as the next begins is allowed. A collision is refused with
    ERR_ATTORNEY_WINDOW_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/attorney_window_half_open_overlap
    """
    plan, cust, ch, sub = setup_active_account(
        state="CA", tier="STANDARD", included_project_credits=3)
    create_clause_templates("WILL", "CA", 1, 0, key_prefix="W")
    att = get_success_data(api.create_attorney(create_attorney_payload(bar_state="CA"), ADMIN))
    # Project A: review window [10:00, 12:00)
    projA = create_project(cust, ch, sub, "WILL", "CA", "W A", attorney_review_addon=True)
    get_success_data(api.upsert_questionnaire(projA["id"], {"answers": full_answers("WILL")}, ch))
    get_success_data(api.assemble_document_project(projA["id"], ch))
    get_success_data(api.create_attorney_review(
        create_attorney_review_payload(projA["id"], att["id"],
                                       "2026-03-08T10:00:00.000Z", "2026-03-08T12:00:00.000Z"), ch))
    # Project B: overlapping window [11:00, 13:00)
    projB = create_project(cust, ch, sub, "WILL", "CA", "W B", attorney_review_addon=True)
    get_success_data(api.upsert_questionnaire(projB["id"], {"answers": full_answers("WILL")}, ch))
    get_success_data(api.assemble_document_project(projB["id"], ch))
    res = api.create_attorney_review(
        create_attorney_review_payload(projB["id"], att["id"],
                                       "2026-03-08T11:00:00.000Z", "2026-03-08T13:00:00.000Z"), ch)
    validate_error(res, "ERR_ATTORNEY_WINDOW_CONFLICT")


def test_lease_term_closed_overlap_with_buffer_rejected(api):
    """PRD §3.8: "creating a LEASE project checks the proposed term — the closed interval
    from lease_start_date to lease_end_date — against every existing non-ABANDONED LEASE
    project sharing the same lease_property_ref. The terms must not overlap, and
    consecutive terms must additionally be separated by a turnover buffer of 7 days between
    one term's end and the next term's start; a term that overlaps an existing term, or
    that falls within the buffer gap of one, is refused with ERR_LEASE_TERM_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/lease_term_closed_overlap_with_buffer
    """
    plan, cust, ch, sub = setup_active_account(
        state="TX", tier="STANDARD", included_project_credits=3)
    get_success_data(api.create_document_project(
        create_document_project_payload(cust["id"], sub["id"], "LEASE", "TX", "Lease P1 A",
                                        lease_property_ref="P1",
                                        lease_start_date="2026-01-01T00:00:00.000Z",
                                        lease_end_date="2026-06-30T00:00:00.000Z"), ch))
    # Second lease starts 2026-07-03, only 3 days after prior ends -> inside 7-day buffer.
    res = api.create_document_project(
        create_document_project_payload(cust["id"], sub["id"], "LEASE", "TX", "Lease P1 B",
                                        lease_property_ref="P1",
                                        lease_start_date="2026-07-03T00:00:00.000Z",
                                        lease_end_date="2026-12-31T00:00:00.000Z"), ch)
    validate_error(res, "ERR_LEASE_TERM_OVERLAP")


# ─── Queue B (Corner): validations ────────────────────

def test_create_project_state_mismatch_reference_invalid(api):
    """PRD §3.2: "the project's state_code must equal the owning customer's
    state_of_residence; a violation of either is an ERR_REFERENCE_INVALID."

    Design: Corner/validations/create_project_state_mismatch_reference_invalid
    """
    plan, cust, ch, sub = setup_active_account(state="CA", tier="STANDARD")
    res = api.create_document_project(
        create_document_project_payload(cust["id"], sub["id"], "WILL", "NY", "Mismatch"), ch)
    validate_error(res, "ERR_REFERENCE_INVALID")


def test_create_project_no_credits_remaining_402(api):
    """PRD §3.2: "a project may be created only if the funding subscription has at least
    one credit remaining — that is, its credits_remaining is one or greater. If no credit
    remains (credits_remaining is zero), creation is refused with ERR_NO_CREDITS_REMAINING
    (HTTP 402)."

    Design: Corner/validations/create_project_no_credits_remaining_402
    """
    plan, cust, ch, sub = setup_active_account(
        state="CA", tier="FREE", included_project_credits=0, included_clause_count=0,
        subscription_discount_pct=0.0, review_discount_pct=0.0)
    res = api.create_document_project(
        create_document_project_payload(cust["id"], sub["id"], "WILL", "CA", "NoCredit"), ch)
    validate_error(res, "ERR_NO_CREDITS_REMAINING")


def test_assemble_no_clause_templates_after_complete_questionnaire(api):
    """PRD §3.4: "Second, at least one ClauseTemplate must exist for the project's
    document_type and state_code pairing; if the library is empty for that combination,
    assembly is refused with ERR_NO_CLAUSE_TEMPLATES."

    Design: Corner/validations/assemble_no_clause_templates_after_complete_questionnaire
    """
    plan, cust, ch, sub = setup_active_account(state="TX", tier="STANDARD")
    proj = create_project(cust, ch, sub, "WILL", "TX", "NoTmpl")
    get_success_data(api.upsert_questionnaire(proj["id"], {"answers": full_answers("WILL")}, ch))
    res = api.assemble_document_project(proj["id"], ch)
    validate_error(res, "ERR_NO_CLAUSE_TEMPLATES")


def test_finalize_mandatory_clause_missing_after_admin_adds_template(api):
    """PRD §3.7: "The project's assembled_completeness must be at least 1.0 — meaning every
    mandatory clause required for the document is present — or the action is refused with
    ERR_MANDATORY_CLAUSE_MISSING." ... "Because the denominator is read live at finalize
    time while the numerator was snapshotted at assembly, an admin who adds a new mandatory
    ClauseTemplate after a project assembled will drive that project's
    assembled_completeness below 1.0 and block its finalization until it is reassembled."

    Design: Corner/validations/finalize_mandatory_clause_missing_after_admin_adds_template
    """
    ctx = setup_assembled_project(state="CA", document_type="WILL", addon=False, mandatory_clauses=1)
    ch = ctx["customer_headers"]
    # Admin adds a 2nd mandatory WILL/CA template after assembly.
    create_clause_template("W2", "WILL", "CA", is_mandatory=True, body_text="c2")
    res = api.transition_document_project(ctx["project"]["id"], {"to_status": "FINALIZED"}, ch)
    validate_error(res, "ERR_MANDATORY_CLAUSE_MISSING")
    proj = get_success_data(api.get_document_project(ctx["project"]["id"], ch))
    assert proj["assembled_completeness"] == 0.5, proj


def test_review_addon_not_elected_rejected(api):
    """PRD §3.5: "The project's attorney_review_addon must be true; a review requested on a
    project that never elected the add-on is refused with ERR_REVIEW_ADDON_NOT_ELECTED."

    Design: Corner/validations/review_addon_not_elected_rejected
    """
    ctx = setup_assembled_project(state="CA", document_type="WILL", addon=False, mandatory_clauses=1)
    ch = ctx["customer_headers"]
    att = get_success_data(api.create_attorney(create_attorney_payload(bar_state="CA"), ADMIN))
    res = api.create_attorney_review(
        create_attorney_review_payload(ctx["project"]["id"], att["id"],
                                       "2026-03-11T10:00:00.000Z", "2026-03-11T12:00:00.000Z"), ch)
    validate_error(res, "ERR_REVIEW_ADDON_NOT_ELECTED")


def test_notary_referral_not_required_rejected(api):
    """PRD §3.7: "A referral may only be created for an envelope whose notary_required is
    true; a referral against an envelope that does not require notarization is refused with
    ERR_NOTARY_NOT_REQUIRED."

    Design: Corner/validations/notary_referral_not_required_rejected
    """
    ctx = setup_assembled_with_revision(state="CA", document_type="WILL", mandatory_clauses=1)
    ch = ctx["customer_headers"]
    sig = get_success_data(api.create_signature_request(
        create_signature_request_payload(ctx["revision"]["id"], ["s@x.com"], notary_required=False), ch))
    res = api.create_notary_referral(
        {"signature_request_id": sig["id"], "referral_state_code": "CA"}, ch)
    validate_error(res, "ERR_NOTARY_NOT_REQUIRED")


def test_sign_with_uninvited_email_rejected(api):
    """PRD §3.7: "The email must be one of the invited signer_emails, or the request is
    refused with ERR_SIGNER_NOT_INVITED"

    Design: Corner/validations/sign_with_uninvited_email_rejected
    """
    ctx = setup_assembled_with_revision(state="CA", document_type="WILL", mandatory_clauses=1)
    ch = ctx["customer_headers"]
    sig = get_success_data(api.create_signature_request(
        create_signature_request_payload(ctx["revision"]["id"], ["a@x.com"]), ch))
    get_success_data(api.transition_document_project(ctx["project"]["id"], {"to_status": "FINALIZED"}, ch))
    get_success_data(api.transition_signature_request(sig["id"], {"to_status": "SENT"}, ch))
    res = api.sign_signature_request(sig["id"], {"signer_email": "intruder@x.com"}, ch)
    validate_error(res, "ERR_SIGNER_NOT_INVITED")


def test_lease_term_outside_buffer_allowed(api):
    """PRD §3.8: "consecutive terms must additionally be separated by a turnover buffer of
    7 days between one term's end and the next term's start; a term that overlaps an
    existing term, or that falls within the buffer gap of one, is refused with
    ERR_LEASE_TERM_OVERLAP."

    Design: Corner/validations/lease_term_outside_buffer_allowed
    """
    plan, cust, ch, sub = setup_active_account(
        state="TX", tier="STANDARD", included_project_credits=3)
    get_success_data(api.create_document_project(
        create_document_project_payload(cust["id"], sub["id"], "LEASE", "TX", "Lease A",
                                        lease_property_ref="P1",
                                        lease_start_date="2026-01-01T00:00:00.000Z",
                                        lease_end_date="2026-06-30T00:00:00.000Z"), ch))
    # 2026-07-09 is 9 days after prior ends 2026-06-30 -> outside the 7-day buffer.
    res = api.create_document_project(
        create_document_project_payload(cust["id"], sub["id"], "LEASE", "TX", "Lease B",
                                        lease_property_ref="P1",
                                        lease_start_date="2026-07-09T00:00:00.000Z",
                                        lease_end_date="2026-12-31T00:00:00.000Z"), ch)
    validate_success(res, 201)
