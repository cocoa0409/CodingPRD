"""Second test per Difficulty-design instance — each asserts a distinct, PRD-derivable
facet of the same rule (a different field, boundary, branch side-effect, or hop) so the
instance is covered by two independent observations rather than a duplicate.

Queue A (Difficulty): one additional test per instance.
"""
from test_helpers import (
    api_client, get_success_data, validate_success, validate_error,
    create_attorney_payload, create_attorney_review_payload,
    create_document_revision_payload, create_signature_request_payload,
    create_document_project_payload, full_answers, partial_answers,
    make_customer_headers, make_attorney_headers, TEST_USERS,
    setup_active_account, create_clause_templates, create_project,
    setup_project_in_progress, setup_assembled_project, setup_assembled_with_revision,
    setup_review_in_review, setup_finalized_with_sent_envelope, create_revision,
    create_clause_template, create_attorney, request_review, assert_money_conserved,
)

ADMIN = TEST_USERS["admin_headers"]


def _order_for(project_id, headers):
    res = api_client.list_orders(headers, params={"document_project_id": project_id})
    return res.json()["data"][0]


def _finalize_will_ca_with_review_and_notary():
    """STANDARD WILL/CA, addon, 7 clauses (2 over included 5), review APPROVED, notary
    signature request, FINALIZE. Returns (project_id, customer_headers, order)."""
    plan, cust, ch, sub = setup_active_account(
        state="CA", tier="STANDARD", included_project_credits=3, included_clause_count=5,
        subscription_discount_pct=0.15, review_discount_pct=0.15)
    create_clause_templates("WILL", "CA", 3, 4, key_prefix="W")
    att = get_success_data(api_client.create_attorney(create_attorney_payload(bar_state="CA"), ADMIN))
    ah = make_attorney_headers(att["id"])
    proj = create_project(cust, ch, sub, "WILL", "CA", "Will", attorney_review_addon=True)
    get_success_data(api_client.upsert_questionnaire(proj["id"], {"answers": full_answers("WILL")}, ch))
    get_success_data(api_client.assemble_document_project(proj["id"], ch))
    review = get_success_data(api_client.create_attorney_review(
        create_attorney_review_payload(proj["id"], att["id"],
                                       "2026-03-01T10:00:00.000Z", "2026-03-01T12:00:00.000Z"), ch))
    get_success_data(api_client.transition_attorney_review(review["id"], {"to_status": "IN_REVIEW"}, ah))
    get_success_data(api_client.transition_attorney_review(review["id"], {"to_status": "APPROVED"}, ah))
    live = get_success_data(api_client.get_document_project(proj["id"], ch))
    rev = get_success_data(api_client.create_document_revision(
        create_document_revision_payload(proj["id"], live["version"]), ch))
    get_success_data(api_client.create_signature_request(
        create_signature_request_payload(rev["id"], ["s1@x.com"], notary_required=True), ch))
    get_success_data(api_client.transition_document_project(proj["id"], {"to_status": "FINALIZED"}, ch))
    return proj["id"], ch, _order_for(proj["id"], ch)


# ─── dual_variant_calc ────────────────────────────────

def test_provisional_quote_independent_of_review_and_notary(api):
    """PRD §3.4: "The provisional quote is the document portion of the price, and nothing
    more — no review surcharge, no notary fee."

    Design: Difficulty/dual_variant_calc/order_provisional_quote_vs_final_invoice_diverge
    """
    # Same fully-finalized project as the primary test: the provisional quote must remain
    # the document portion only (6882), unaffected by the review surcharge and notary line.
    proj_id, ch, order = _finalize_will_ca_with_review_and_notary()
    assert order["provisional_quote_cents"] == 6882, order


def test_assembled_completeness_zero_before_assembly(api):
    """PRD §3.7: "The assembled_completeness ratio is the count of mandatory AssembledClause
    rows on the project divided by the number of mandatory clause templates currently in
    the library for the project's document_type and state_code; if there are no mandatory
    templates the ratio is taken to be 1.0."

    Design: Difficulty/dual_variant_calc/project_completeness_provisional_vs_assembled_diverge
    """
    # Before assembly, provisional_completeness can be 1.0 while assembled_completeness is
    # still 0.0 (no AssembledClause rows yet) — the two ratios measure different things.
    ctx = setup_project_in_progress(
        state="CA", document_type="WILL", answer_count=8, addon=False, mandatory_clauses=1)
    proj = ctx["project"]
    assert proj["provisional_completeness"] == 1.0, proj
    assert proj["assembled_completeness"] == 0.0, proj


# ─── combinatorial_formula ────────────────────────────

def test_final_invoice_review_line_only_counts_approved(api):
    """PRD §3.7: "The active review line is the sum of surcharge_cents over the project's
    APPROVED attorney reviews — cancelled reviews are excluded because their surcharge was
    refunded."

    Design: Difficulty/combinatorial_formula/final_invoice_nonlinear_multiinput_tiered
    """
    # The final invoice's review line is exactly the APPROVED review's surcharge (6375),
    # contributing to the 15757 total alongside doc (6882) and notary (2500).
    proj_id, ch, order = _finalize_will_ca_with_review_and_notary()
    assert order["final_invoice_cents"] - order["provisional_quote_cents"] == 6375 + 2500, order


def test_doc_portion_rounding_sum_then_round_would_differ(api):
    """PRD §2.7: "for the document portion of an order each line is discounted and rounded
    before the lines are summed, not after."

    Design: Difficulty/combinatorial_formula/doc_portion_rounding_order_per_line_then_sum
    """
    # LLC/NY/PREMIUM (3 clauses, 0 extra): per-line rounding gives 8998; the (incorrect)
    # sum-then-round path would yield 8999. Assert the contract's per-line value, not 8999.
    plan, cust, ch, sub = setup_active_account(
        state="NY", tier="PREMIUM", included_project_credits=5, included_clause_count=999,
        subscription_discount_pct=0.25, review_discount_pct=0.40)
    create_clause_templates("LLC", "NY", 3, 0, key_prefix="L")
    proj = create_project(cust, ch, sub, "LLC", "NY", "LLC Round")
    get_success_data(api.upsert_questionnaire(proj["id"], {"answers": full_answers("LLC")}, ch))
    get_success_data(api.assemble_document_project(proj["id"], ch))
    order = _order_for(proj["id"], ch)
    assert order["provisional_quote_cents"] == 8998, order


# ─── non_linear_state_machine ─────────────────────────

def test_changes_requested_supersedes_final_revision(api):
    """PRD §3.5: "the project's newest DocumentRevision (the one currently FINAL) is flipped
    to SUPERSEDED to reflect that the snapshot the attorney reviewed is no longer the live
    draft."

    Design: Difficulty/non_linear_state_machine/project_revision_cycle_changes_requested_back_to_in_progress
    """
    ctx = setup_assembled_project(state="CA", document_type="WILL", addon=True, mandatory_clauses=1)
    ch = ctx["customer_headers"]
    rev = create_revision(ctx["project"], ch)
    att = get_success_data(api.create_attorney(create_attorney_payload(bar_state="CA"), ADMIN))
    ah = make_attorney_headers(att["id"])
    # After a revision the project version advanced; request a review on the ASSEMBLED project.
    proj = get_success_data(api.get_document_project(ctx["project"]["id"], ch))
    review = request_review(proj, ch, att)
    get_success_data(api.transition_attorney_review(review["id"], {"to_status": "IN_REVIEW"}, ah))
    get_success_data(api.transition_attorney_review(review["id"], {"to_status": "CHANGES_REQUESTED"}, ah))
    rev_after = get_success_data(api.get_document_revision(rev["id"], ch))
    assert rev_after["status"] == "SUPERSEDED", rev_after


# ─── transitive_cascade ───────────────────────────────

def test_subscription_cancel_refunds_review_surcharge_on_order(api):
    """PRD §3.8: "And each review so cancelled performs the final hop — a refund: the
    review's surcharge_cents is added to the project's order's amount_refunded_cents, the
    order's net_collected_cents is recomputed, and the attorney's window is released."

    Design: Difficulty/transitive_cascade/subscription_cancel_depth4_cascade_to_order_refund
    """
    # Independent observation of hop D: the refund posts exactly the review surcharge to
    # amount_refunded_cents (6375 = round(7500*0.85)).
    ctx = setup_review_in_review(state="CA", document_type="WILL", mandatory_clauses=1)
    ch = ctx["customer_headers"]
    get_success_data(api.transition_subscription(ctx["subscription"]["id"], {"to_status": "CANCELLED"}, ADMIN))
    order = _order_for(ctx["project"]["id"], ch)
    assert order["amount_refunded_cents"] == 6375, order


def test_signed_transition_schedules_reminder_due_at_present(api):
    """PRD §3.7: "The UpdateReminder scheduled when the project reached SIGNED carries a
    due_at set to the moment of signing plus the reminder interval of 90 days, and is born
    SCHEDULED."

    Design: Difficulty/transitive_cascade/signature_complete_depth3_cascade_schedules_reminder
    """
    ctx = setup_finalized_with_sent_envelope(
        state="CA", document_type="WILL", signer_emails=["s1@x.com"],
        clock_iso="2026-04-01T00:00:00.000Z", mandatory_clauses=1)
    ch = ctx["customer_headers"]
    get_success_data(api.sign_signature_request(
        ctx["signature_request"]["id"], {"signer_email": "s1@x.com"}, ch))
    res = api.list_update_reminders(ch, params={"document_project_id": ctx["project"]["id"]})
    reminders = res.json()["data"]
    assert len(reminders) == 1, reminders
    assert reminders[0]["due_at"], reminders[0]
    assert reminders[0]["status"] == "SCHEDULED", reminders[0]


# ─── priority_pair_validation_conflict ────────────────

def test_state_check_precedes_addon_gate_on_review_request(api):
    """PRD §2.9: "the state-validity check that the target resource is in a legal from-state
    for the requested transition (ERR_INVALID_STATE). Only once all of those pass does the
    system evaluate the domain-specific business rules — subscription-active gating, add-on
    election, completeness gates"

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_review_request
    """
    # Project still IN_PROGRESS (wrong state) AND addon=false: the state error wins.
    ctx = setup_project_in_progress(
        state="CA", document_type="WILL", answer_count=2, addon=False, mandatory_clauses=1)
    ch = ctx["customer_headers"]
    att = get_success_data(api.create_attorney(create_attorney_payload(bar_state="CA"), ADMIN))
    res = api.create_attorney_review(
        create_attorney_review_payload(ctx["project"]["id"], att["id"],
                                       "2026-03-21T10:00:00.000Z", "2026-03-21T12:00:00.000Z"), ch)
    validate_error(res, "ERR_INVALID_STATE")


def test_questionnaire_gate_precedes_no_template_gate(api):
    """PRD §3.4: "First, the project's provisional_completeness must have reached completion
    — it must be at least 1.0; if the questionnaire is not fully answered, assembly is
    refused with ERR_QUESTIONNAIRE_INCOMPLETE. Second, at least one ClauseTemplate must
    exist for the project's document_type and state_code pairing; if the library is empty
    for that combination, assembly is refused with ERR_NO_CLAUSE_TEMPLATES."

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_constraint_on_assemble
    """
    # WILL/TX, no templates, 0 answers: questionnaire gate (priority 10) fires before the
    # no-template gate (priority 11).
    plan, cust, ch, sub = setup_active_account(state="TX", tier="STANDARD")
    proj = create_project(cust, ch, sub, "WILL", "TX", "Order")
    get_success_data(api.upsert_questionnaire(proj["id"], {"answers": partial_answers(0)}, ch))
    res = api.assemble_document_project(proj["id"], ch)
    validate_error(res, "ERR_QUESTIONNAIRE_INCOMPLETE")


# ─── boundary_precision_check ─────────────────────────

def test_assemble_completeness_below_one_at_six_eighths_rejected(api):
    """PRD §3.4: "First, the project's provisional_completeness must have reached completion
    — it must be at least 1.0; if the questionnaire is not fully answered, assembly is
    refused with ERR_QUESTIONNAIRE_INCOMPLETE."

    Design: Difficulty/boundary_precision_check/assemble_completeness_threshold_at_exactly_one
    """
    # X-1 boundary on the far side: 6/8 = 0.75 < 1.0, rejected.
    ctx = setup_project_in_progress(
        state="CA", document_type="WILL", answer_count=6, addon=False, mandatory_clauses=1)
    ch = ctx["customer_headers"]
    assert ctx["project"]["provisional_completeness"] == 0.75, ctx["project"]
    res = api.assemble_document_project(ctx["project"]["id"], ch)
    validate_error(res, "ERR_QUESTIONNAIRE_INCOMPLETE")


def test_signature_request_single_signer_list_accepted(api):
    """PRD §3.7: "A Customer creates a SignatureRequest (an e-signature envelope) against
    the FINAL revision by document_revision_id, supplying an ordered, non-empty
    signer_emails list" ... "The envelope is born in DRAFT with signed_count at zero."

    Design: Difficulty/boundary_precision_check/signature_request_empty_signer_list_rejected
    """
    # X+1 boundary: a one-element (non-empty) signer list is accepted.
    ctx = setup_assembled_with_revision(state="CA", document_type="WILL", mandatory_clauses=1)
    ch = ctx["customer_headers"]
    sig = validate_success(api.create_signature_request(
        create_signature_request_payload(ctx["revision"]["id"], ["one@x.com"]), ch), 201)
    assert sig["status"] == "DRAFT", sig


# ─── cross_entity_state_dependency ────────────────────

def test_review_request_succeeds_when_subscription_active(api):
    """PRD §3.5: "And the project's owning subscription must be ACTIVE at request time; if
    the subscription is PAST_DUE, PENDING_PAYMENT, or CANCELLED, the request is refused with
    ERR_SUBSCRIPTION_NOT_ACTIVE."

    Design: Difficulty/cross_entity_state_dependency/review_request_requires_active_subscription
    """
    # Positive counterpart: with an ACTIVE subscription the review request succeeds and the
    # project advances to IN_REVIEW.
    ctx = setup_assembled_project(state="CA", document_type="WILL", addon=True, mandatory_clauses=1)
    ch = ctx["customer_headers"]
    att = get_success_data(api.create_attorney(create_attorney_payload(bar_state="CA"), ADMIN))
    review = validate_success(api.create_attorney_review(
        create_attorney_review_payload(ctx["project"]["id"], att["id"],
                                       "2026-03-22T10:00:00.000Z", "2026-03-22T12:00:00.000Z"), ch), 201)
    assert review["status"] == "ASSIGNED", review
    proj = get_success_data(api.get_document_project(ctx["project"]["id"], ch))
    assert proj["status"] == "IN_REVIEW", proj


def test_signature_send_succeeds_on_final_revision(api):
    """PRD §3.7: "The customer then sends it, transitioning DRAFT → SENT via to_status;
    sending requires that the referenced DocumentRevision still be FINAL (a SUPERSEDED
    revision yields ERR_REVISION_SUPERSEDED) and that the owning DocumentProject be
    FINALIZED (otherwise ERR_PROJECT_NOT_FINALIZED)."

    Design: Difficulty/cross_entity_state_dependency/signature_send_requires_final_revision
    """
    # Positive counterpart: a still-FINAL revision on a FINALIZED project sends cleanly.
    ctx = setup_assembled_with_revision(state="CA", document_type="WILL", mandatory_clauses=1)
    ch = ctx["customer_headers"]
    sig = get_success_data(api.create_signature_request(
        create_signature_request_payload(ctx["revision"]["id"], ["s1@x.com"]), ch))
    get_success_data(api.transition_document_project(ctx["project"]["id"], {"to_status": "FINALIZED"}, ch))
    sent = validate_success(api.transition_signature_request(sig["id"], {"to_status": "SENT"}, ch), 200)
    assert sent["status"] == "SENT", sent


# ─── resource_temporal_overlap ────────────────────────

def test_attorney_window_back_to_back_allowed(api):
    """PRD §3.5: "a back-to-back pairing where one window ends exactly as the next begins is
    allowed. A collision is refused with ERR_ATTORNEY_WINDOW_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/attorney_window_half_open_overlap
    """
    # Touching boundary [10:00,12:00) then [12:00,14:00) does not overlap -> allowed.
    plan, cust, ch, sub = setup_active_account(
        state="CA", tier="STANDARD", included_project_credits=3)
    create_clause_templates("WILL", "CA", 1, 0, key_prefix="W")
    att = get_success_data(api.create_attorney(create_attorney_payload(bar_state="CA"), ADMIN))
    projA = create_project(cust, ch, sub, "WILL", "CA", "W A", attorney_review_addon=True)
    get_success_data(api.upsert_questionnaire(projA["id"], {"answers": full_answers("WILL")}, ch))
    get_success_data(api.assemble_document_project(projA["id"], ch))
    get_success_data(api.create_attorney_review(
        create_attorney_review_payload(projA["id"], att["id"],
                                       "2026-03-08T10:00:00.000Z", "2026-03-08T12:00:00.000Z"), ch))
    projB = create_project(cust, ch, sub, "WILL", "CA", "W B", attorney_review_addon=True)
    get_success_data(api.upsert_questionnaire(projB["id"], {"answers": full_answers("WILL")}, ch))
    get_success_data(api.assemble_document_project(projB["id"], ch))
    res = api.create_attorney_review(
        create_attorney_review_payload(projB["id"], att["id"],
                                       "2026-03-08T12:00:00.000Z", "2026-03-08T14:00:00.000Z"), ch)
    validate_success(res, 201)


def test_lease_term_direct_overlap_rejected(api):
    """PRD §3.8: "The terms must not overlap, and consecutive terms must additionally be
    separated by a turnover buffer of 7 days between one term's end and the next term's
    start; a term that overlaps an existing term, or that falls within the buffer gap of
    one, is refused with ERR_LEASE_TERM_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/lease_term_closed_overlap_with_buffer
    """
    # Direct interval overlap (not just buffer): second term starts inside the first.
    plan, cust, ch, sub = setup_active_account(
        state="TX", tier="STANDARD", included_project_credits=3)
    get_success_data(api.create_document_project(
        create_document_project_payload(cust["id"], sub["id"], "LEASE", "TX", "Lease A",
                                        lease_property_ref="P9",
                                        lease_start_date="2026-01-01T00:00:00.000Z",
                                        lease_end_date="2026-06-30T00:00:00.000Z"), ch))
    res = api.create_document_project(
        create_document_project_payload(cust["id"], sub["id"], "LEASE", "TX", "Lease B",
                                        lease_property_ref="P9",
                                        lease_start_date="2026-03-01T00:00:00.000Z",
                                        lease_end_date="2026-09-30T00:00:00.000Z"), ch)
    validate_error(res, "ERR_LEASE_TERM_OVERLAP")


# ─── compensating_invariant ───────────────────────────

def test_money_conserved_charged_minus_refunded_after_cascade(api):
    """PRD §3.8: "The system guarantees that an order's net_collected_cents always equals
    its amount_charged_cents minus its amount_refunded_cents"

    Design: Difficulty/compensating_invariant/money_invariant_review_charge_then_refund
    """
    # Independent observation of the conservation identity itself after the refund cascade.
    ctx = setup_review_in_review(
        state="CA", document_type="WILL", mandatory_clauses=1, optional_clauses=6,
        tier="STANDARD", included_clause_count=5,
        subscription_discount_pct=0.15, review_discount_pct=0.15)
    ch = ctx["customer_headers"]
    get_success_data(api.transition_subscription(ctx["subscription"]["id"], {"to_status": "CANCELLED"}, ADMIN))
    order = _order_for(ctx["project"]["id"], ch)
    assert_money_conserved(order)
    assert order["net_collected_cents"] == 0, order


def test_credit_held_flips_false_on_abandon(api):
    """PRD §3.2: "A credit is returned to the pool only when a project is abandoned before
    it has been assembled: transitioning a project to ABANDONED from either DRAFT or
    IN_PROGRESS sets the project's credit_held to false, decrements the owning
    subscription's credits_used by one, and recomputes credits_remaining."

    Design: Difficulty/compensating_invariant/credit_invariant_consume_then_return_on_abandon
    """
    # Observe the per-project credit_held flag (the conserved-quantity bookkeeping) directly.
    plan, cust, ch, sub = setup_active_account(
        state="CA", tier="STANDARD", included_project_credits=3,
        subscription_discount_pct=0.15, review_discount_pct=0.15)
    proj = create_project(cust, ch, sub, "WILL", "CA", "Abandon")
    assert proj["credit_held"] is True, proj
    abandoned = get_success_data(api.transition_document_project(
        proj["id"], {"to_status": "ABANDONED"}, ch))
    assert abandoned["status"] == "ABANDONED", abandoned
    assert abandoned["credit_held"] is False, abandoned
