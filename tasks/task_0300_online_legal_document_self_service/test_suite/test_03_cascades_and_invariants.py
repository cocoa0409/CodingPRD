"""Multi-hop cascades (subscription cancel -> lock -> review cancel -> refund;
final signature -> SIGNED -> reminder) and the money / credit conservation invariants.

Queue A (Difficulty): transitive_cascade, compensating_invariant.
"""
from test_helpers import (
    api_client, get_success_data, validate_success,
    create_attorney_payload, create_attorney_review_payload,
    create_document_revision_payload, create_signature_request_payload,
    full_answers, make_customer_headers, make_attorney_headers, TEST_USERS,
    setup_active_account, create_clause_templates, create_project,
    setup_review_in_review, setup_finalized_with_sent_envelope,
    assert_money_conserved,
)

ADMIN = TEST_USERS["admin_headers"]


def _order_for(project_id, headers):
    res = api_client.list_orders(headers, params={"document_project_id": project_id})
    return res.json()["data"][0]


# ─── transitive_cascade ───────────────────────────────

def test_subscription_cancel_depth4_cascade_to_order_refund(api):
    """PRD §3.8: "its first hop drives each eligible project (those in DRAFT, IN_PROGRESS,
    ASSEMBLED, IN_REVIEW, CHANGES_REQUESTED, or FINALIZED) to STORAGE_LOCKED, a terminal
    state. Each project entering STORAGE_LOCKED then performs its own hop: every
    AttorneyReview of that project still in REQUESTED, ASSIGNED, or IN_REVIEW is
    transitioned to CANCELLED. And each review so cancelled performs the final hop — a
    refund: the review's surcharge_cents is added to the project's order's
    amount_refunded_cents, the order's net_collected_cents is recomputed, and the
    attorney's window is released."

    Design: Difficulty/transitive_cascade/subscription_cancel_depth4_cascade_to_order_refund
    """
    ctx = setup_review_in_review(state="CA", document_type="WILL", mandatory_clauses=1)
    ch = ctx["customer_headers"]
    proj_id = ctx["project"]["id"]
    # surcharge: round(7500 * 0.85) = 6375 charged on the order at request.
    get_success_data(api.transition_subscription(ctx["subscription"]["id"], {"to_status": "CANCELLED"}, ADMIN))

    proj = get_success_data(api.get_document_project(proj_id, ch))
    assert proj["status"] == "STORAGE_LOCKED", proj  # hop B
    review = get_success_data(api.get_attorney_review(ctx["review"]["id"], ch))
    assert review["status"] == "CANCELLED", review  # hop C

    order = _order_for(proj_id, ch)
    assert order["amount_charged_cents"] == 6375, order
    assert order["amount_refunded_cents"] == 6375, order  # hop D
    assert order["net_collected_cents"] == 0, order
    assert_money_conserved(order)


def test_signature_complete_depth3_cascade_schedules_reminder(api):
    """PRD §3.7: "When the final outstanding signer signs and signed_count reaches the
    length of signer_emails, the envelope becomes COMPLETED; a single-signer envelope goes
    straight from SENT to COMPLETED on its sole signature. Completion bubbles up: the
    owning DocumentProject is driven from FINALIZED to SIGNED, and that transition in turn
    schedules an UpdateReminder."

    Design: Difficulty/transitive_cascade/signature_complete_depth3_cascade_schedules_reminder
    """
    ctx = setup_finalized_with_sent_envelope(
        state="CA", document_type="WILL", signer_emails=["s1@x.com"],
        clock_iso="2026-04-01T00:00:00.000Z", mandatory_clauses=1)
    ch = ctx["customer_headers"]
    proj_id = ctx["project"]["id"]
    sig = get_success_data(api.sign_signature_request(
        ctx["signature_request"]["id"], {"signer_email": "s1@x.com"}, ch))
    assert sig["status"] == "COMPLETED", sig  # hop A

    proj = get_success_data(api.get_document_project(proj_id, ch))
    assert proj["status"] == "SIGNED", proj  # hop B

    res = api.list_update_reminders(ch, params={"document_project_id": proj_id})
    reminders = res.json()["data"]
    assert len(reminders) == 1, reminders  # hop C
    assert reminders[0]["status"] == "SCHEDULED", reminders[0]


# ─── compensating_invariant ───────────────────────────

def test_money_invariant_review_charge_then_refund(api):
    """PRD §3.8: "This refund-on-cancellation closes the money-conservation loop. The
    system guarantees that an order's net_collected_cents always equals its
    amount_charged_cents minus its amount_refunded_cents, and that this net equals the
    document portion charged plus the sum of surcharge_cents across the project's
    non-CANCELLED reviews plus any active notary line. A review surcharge added at request
    and later refunded when the review is cancelled through the cascade nets to zero,
    exactly as a fully-settled forward-and-compensating pair should."

    Design: Difficulty/compensating_invariant/money_invariant_review_charge_then_refund
    """
    # 7 clauses (mandatory 1 + optional 6) for WILL/CA; provisional 6882 (never charged pre-finalize).
    ctx = setup_review_in_review(
        state="CA", document_type="WILL", mandatory_clauses=1, optional_clauses=6,
        tier="STANDARD", included_clause_count=5,
        subscription_discount_pct=0.15, review_discount_pct=0.15)
    ch = ctx["customer_headers"]
    proj_id = ctx["project"]["id"]
    get_success_data(api.transition_subscription(ctx["subscription"]["id"], {"to_status": "CANCELLED"}, ADMIN))
    order = _order_for(proj_id, ch)
    assert order["amount_charged_cents"] == 6375, order
    assert order["amount_refunded_cents"] == 6375, order
    assert order["net_collected_cents"] == 0, order
    assert_money_conserved(order)


def test_credit_invariant_consume_then_return_on_abandon(api):
    """PRD §3.2: "Document projects consume subscription credits" ... "the funding
    subscription's credits_used is incremented by one" ... "A credit is returned to the
    pool only when a project is abandoned before it has been assembled: transitioning a
    project to ABANDONED from either DRAFT or IN_PROGRESS sets the project's credit_held to
    false, decrements the owning subscription's credits_used by one, and recomputes
    credits_remaining."
    PRD §3.2: "The invariant the system maintains is that a subscription's credits_used
    always equals the number of that subscription's projects whose credit_held is true."

    Design: Difficulty/compensating_invariant/credit_invariant_consume_then_return_on_abandon
    """
    plan, cust, ch, sub = setup_active_account(
        state="CA", tier="STANDARD", included_project_credits=3,
        subscription_discount_pct=0.15, review_discount_pct=0.15)
    p1 = create_project(cust, ch, sub, "WILL", "CA", "P1")
    p2 = create_project(cust, ch, sub, "WILL", "CA", "P2")
    p3 = create_project(cust, ch, sub, "WILL", "CA", "P3")
    after3 = get_success_data(api.get_subscription(sub["id"], ch))
    assert after3["credits_used"] == 3, after3
    assert after3["credits_remaining"] == 0, after3

    get_success_data(api.transition_document_project(p3["id"], {"to_status": "ABANDONED"}, ch))
    after_abandon = get_success_data(api.get_subscription(sub["id"], ch))
    assert after_abandon["credits_used"] == 2, after_abandon
    assert after_abandon["credits_remaining"] == 1, after_abandon
