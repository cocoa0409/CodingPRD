"""Pricing variants (provisional vs final), tiered/rounded document portion,
review surcharge, and the two completeness meanings.

Queue A (Difficulty): dual_variant_calc, combinatorial_formula.
Queue B (Corner): calculations, consistency_model, entities (computed Order fields).
"""
from test_helpers import (
    api_client, get_success_data, validate_success,
    create_subscription_plan_payload, create_customer_payload,
    create_subscription_payload, create_document_project_payload,
    create_attorney_payload, create_attorney_review_payload,
    create_document_revision_payload, create_signature_request_payload,
    full_answers, partial_answers,
    make_customer_headers, make_attorney_headers, TEST_USERS,
    setup_active_account, create_clause_templates, create_project,
    setup_assembled_project, setup_review_approved, create_revision,
)

ADMIN = TEST_USERS["admin_headers"]


def _order_for(project_id, headers):
    """Return the single Order for a project (1:1) via the filtered list endpoint."""
    res = api_client.list_orders(headers, params={"document_project_id": project_id})
    body = res.json()
    return body["data"][0]


def _finalize_will_ca_with_review_and_notary():
    """STANDARD WILL/CA, addon, 7 clauses (2 over included 5), review APPROVED,
    notary-required signature request on the FINAL revision, then FINALIZE.
    Returns (project_id, customer_headers, order-after-finalize)."""
    plan = get_success_data(api_client.create_subscription_plan(
        create_subscription_plan_payload(
            tier="STANDARD", monthly_fee_cents=0, included_project_credits=3,
            included_clause_count=5, subscription_discount_pct=0.15, review_discount_pct=0.15,
        ), ADMIN))
    # 3 mandatory + 4 optional = 7 clauses for WILL/CA
    create_clause_templates("WILL", "CA", 3, 4, key_prefix="W")
    cust = get_success_data(api_client.create_customer(
        create_customer_payload(state_of_residence="CA"), TEST_USERS["customer_headers"]))
    ch = make_customer_headers(cust["id"])
    sub = get_success_data(api_client.create_subscription(
        create_subscription_payload(cust["id"], plan["id"]), ch))
    get_success_data(api_client.transition_subscription(sub["id"], {"to_status": "ACTIVE"}, ADMIN))
    att = get_success_data(api_client.create_attorney(create_attorney_payload(bar_state="CA"), ADMIN))
    ah = make_attorney_headers(att["id"])
    proj = get_success_data(api_client.create_document_project(
        create_document_project_payload(cust["id"], sub["id"], "WILL", "CA", "Will",
                                        attorney_review_addon=True), ch))
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
    order = _order_for(proj["id"], ch)
    return proj["id"], ch, order


def test_provisional_quote_and_final_invoice_diverge(api):
    """PRD §3.4: "The provisional quote is the document portion of the price, and
    nothing more — no review surcharge, no notary fee."
    PRD §3.7: "Finalization recomputes the order's final_invoice_cents as the sum of
    three lines. The document portion is recomputed exactly as the provisional quote
    was (the same three per-line-discounted-and-rounded lines from §3.4). The active
    review line is the sum of surcharge_cents over the project's APPROVED attorney
    reviews — cancelled reviews are excluded because their surcharge was refunded. The
    active notary line is the notary fee of 2500 cents if any SignatureRequest on a
    FINAL revision of the project has notary_required set true, and zero otherwise."

    Design: Difficulty/dual_variant_calc/order_provisional_quote_vs_final_invoice_diverge
    """
    proj_id, ch, order = _finalize_will_ca_with_review_and_notary()
    assert order["provisional_quote_cents"] == 6882, order
    assert order["final_invoice_cents"] == 15757, order
    assert order["final_invoice_cents"] != order["provisional_quote_cents"]


def test_final_invoice_nonlinear_tiered_doc_review_notary(api):
    """PRD §3.7: "Finalization recomputes the order's final_invoice_cents as the sum of
    three lines. The document portion is recomputed exactly as the provisional quote
    was (the same three per-line-discounted-and-rounded lines from §3.4). The active
    review line is the sum of surcharge_cents over the project's APPROVED attorney
    reviews — cancelled reviews are excluded because their surcharge was refunded. The
    active notary line is the notary fee of 2500 cents if any SignatureRequest on a
    FINAL revision of the project has notary_required set true, and zero otherwise."

    Design: Difficulty/combinatorial_formula/final_invoice_nonlinear_multiinput_tiered
    """
    proj_id, ch, order = _finalize_will_ca_with_review_and_notary()
    # 15757 == doc 6882 + review 6375 + notary 2500
    assert order["final_invoice_cents"] == 15757, order


def test_provisional_completeness_vs_assembled_completeness_diverge(api):
    """PRD §3.3: "The project's provisional_completeness is then answered_required_count
    divided by total_required_count, a ratio between 0.0 and 1.0."
    PRD §3.7: "The assembled_completeness ratio is the count of mandatory AssembledClause
    rows on the project divided by the number of mandatory clause templates currently in
    the library for the project's document_type and state_code; if there are no mandatory
    templates the ratio is taken to be 1.0."

    Design: Difficulty/dual_variant_calc/project_completeness_provisional_vs_assembled_diverge
    """
    plan, cust, ch, sub = setup_active_account(
        state="CA", tier="STANDARD", included_clause_count=5,
        subscription_discount_pct=0.15, review_discount_pct=0.15)
    create_clause_templates("WILL", "CA", 1, 0, key_prefix="W")
    proj = create_project(cust, ch, sub, "WILL", "CA", "Will Two")
    # 6 of 8 answered -> 0.75
    p6 = get_success_data(api.upsert_questionnaire(proj["id"], {"answers": partial_answers(6)}, ch))
    assert p6["answered_required_count"] == 6
    proj_after6 = get_success_data(api.get_document_project(proj["id"], ch))
    assert proj_after6["provisional_completeness"] == 0.75, proj_after6
    # complete to 8/8 then assemble -> assembled_completeness 1.0
    get_success_data(api.upsert_questionnaire(proj["id"], {"answers": full_answers("WILL")}, ch))
    assembled = get_success_data(api.assemble_document_project(proj["id"], ch))
    assert assembled["assembled_completeness"] == 1.0, assembled
    assert proj_after6["provisional_completeness"] != assembled["assembled_completeness"]


def test_doc_portion_rounding_per_line_then_sum(api):
    """PRD §2.7: "for the document portion of an order each line is discounted and
    rounded before the lines are summed, not after."
    PRD §3.4: "The plan's subscription_discount_pct is applied to each of these three
    lines individually: each line is multiplied by one minus the discount fraction, that
    product is rounded half-up to whole cents, and only then are the three rounded line
    amounts added together to give provisional_quote_cents."

    Design: Difficulty/combinatorial_formula/doc_portion_rounding_order_per_line_then_sum
    """
    plan, cust, ch, sub = setup_active_account(
        state="NY", tier="PREMIUM", included_project_credits=5, included_clause_count=999,
        subscription_discount_pct=0.25, review_discount_pct=0.40)
    create_clause_templates("LLC", "NY", 3, 0, key_prefix="L")
    proj = create_project(cust, ch, sub, "LLC", "NY", "LLC One")
    get_success_data(api.upsert_questionnaire(proj["id"], {"answers": full_answers("LLC")}, ch))
    get_success_data(api.assemble_document_project(proj["id"], ch))
    order = _order_for(proj["id"], ch)
    # round(9999*0.75)=7499 + round(1999*0.75)=1499 + 0 extra = 8998 (per-line), not 8999
    assert order["provisional_quote_cents"] == 8998, order
    assert order["provisional_quote_cents"] != 8999


# ─── Queue B (Corner): calculations ───────────────────

def test_provisional_quote_free_tier_no_discount(api):
    """PRD §3.4: "The base line is the per-type base price: 4999 cents for a WILL, 9999
    for an LLC, 3999 for a POA, and 2999 for a LEASE." ... "The extra-clause line covers
    overage: it is the number of assembled clauses beyond the plan's bundled allowance —
    that is, the project's assembled_clause_count minus the plan's included_clause_count,
    but never less than zero — multiplied by the extra-clause fee of 799 cents per clause."

    Design: Corner/calculations/provisional_quote_free_tier_no_discount
    """
    plan, cust, ch, sub = setup_active_account(
        state="FL", tier="FREE", included_project_credits=3, included_clause_count=0,
        subscription_discount_pct=0.0, review_discount_pct=0.0)
    create_clause_templates("POA", "FL", 1, 1, key_prefix="PA")
    proj = create_project(cust, ch, sub, "POA", "FL", "POA Free")
    get_success_data(api.upsert_questionnaire(proj["id"], {"answers": full_answers("POA")}, ch))
    assembled = get_success_data(api.assemble_document_project(proj["id"], ch))
    assert assembled["provisional_completeness"] == 1.0, assembled
    order = _order_for(proj["id"], ch)
    # 3999 + 0 (FL surcharge) + 2*799 = 5597, no discount
    assert order["provisional_quote_cents"] == 5597, order


def test_review_surcharge_premium_tier_discount(api):
    """PRD §3.5: "The surcharge is the standard review fee of 7500 cents, reduced by the
    plan's review_discount_pct: the fee is multiplied by one minus that discount fraction
    and rounded half-up to whole cents. The result is stored on the review as
    surcharge_cents, added to the order's amount_charged_cents, and the order's
    net_collected_cents is recomputed."

    Design: Corner/calculations/review_surcharge_premium_tier_discount
    """
    ctx = setup_assembled_project(
        state="NY", document_type="LLC", addon=True, mandatory_clauses=1, optional_clauses=0,
        tier="PREMIUM", included_project_credits=5, included_clause_count=999,
        subscription_discount_pct=0.25, review_discount_pct=0.40)
    ch = ctx["customer_headers"]
    att = get_success_data(api.create_attorney(create_attorney_payload(bar_state="NY"), ADMIN))
    review = get_success_data(api.create_attorney_review(
        create_attorney_review_payload(ctx["project"]["id"], att["id"],
                                       "2026-03-10T10:00:00.000Z", "2026-03-10T12:00:00.000Z"), ch))
    # round(7500 * 0.60) = 4500
    assert review["surcharge_cents"] == 4500, review
    order = _order_for(ctx["project"]["id"], ch)
    assert order["amount_charged_cents"] == 4500, order


# ─── Queue B (Corner): consistency_model ──────────────

def test_assemble_response_reflects_provisional_quote_immediately(api):
    """PRD §3.4: "The system then recomputes the project's assembled_completeness and the
    order's provisional_quote_cents, both described next." ... "each line is multiplied by
    one minus the discount fraction, that product is rounded half-up to whole cents, and
    only then are the three rounded line amounts added together to give
    provisional_quote_cents."

    Design: Corner/consistency_model/assemble_response_reflects_provisional_quote_immediately
    """
    plan, cust, ch, sub = setup_active_account(
        state="CA", tier="STANDARD", included_clause_count=5,
        subscription_discount_pct=0.15, review_discount_pct=0.15)
    create_clause_templates("WILL", "CA", 1, 0, key_prefix="W")
    proj = create_project(cust, ch, sub, "WILL", "CA", "Imm")
    get_success_data(api.upsert_questionnaire(proj["id"], {"answers": full_answers("WILL")}, ch))
    assembled = get_success_data(api.assemble_document_project(proj["id"], ch))
    assert assembled["assembled_clause_count"] == 1, assembled
    order = _order_for(proj["id"], ch)
    # round(4999*0.85)=4249 + round(1500*0.85)=1275 + 0 extra = 5524
    assert order["provisional_quote_cents"] == 5524, order


# ─── Queue B (Corner): entities (computed Order fields) ──

def test_order_auto_created_with_zero_amounts(api):
    """PRD §3.2: "And an Order is created as a side effect, linked to this project by
    document_project_id, with every monetary field — provisional_quote_cents,
    final_invoice_cents, amount_charged_cents, amount_refunded_cents, and
    net_collected_cents — initialized to zero."

    Design: Corner/entities/order_computed_fields_ignore_client_input
    """
    plan, cust, ch, sub = setup_active_account(
        state="CA", tier="STANDARD", included_clause_count=5,
        subscription_discount_pct=0.15, review_discount_pct=0.15)
    proj = create_project(cust, ch, sub, "WILL", "CA", "Ord")
    order = _order_for(proj["id"], ch)
    assert order["provisional_quote_cents"] == 0, order
    assert order["final_invoice_cents"] == 0, order
    assert order["amount_charged_cents"] == 0, order
    assert order["net_collected_cents"] == 0, order
