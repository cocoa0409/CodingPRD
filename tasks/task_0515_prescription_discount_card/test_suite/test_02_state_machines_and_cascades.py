"""State-machine transitions and cascades: Gold parallel dimensions, claim
branching/revert, pharmacy-suspend cascade, copay-card withdraw cascade,
gold-lapse cascade, telehealth lifecycle, comparison resolve/convert, mail-order.
"""
import pytest

from test_helpers import (
    api_client, get_success_data, validate_success,
    make_member_headers, TEST_USERS,
    create_gold_membership_payload, create_discount_card_payload,
    create_claim_payload, create_telehealth_referral_payload,
    create_comparison_payload, create_mail_order_payload,
    setup_resolved_comparison, setup_discount_card, setup_submitted_claim,
    setup_adjudicated_claim, setup_submitted_claim_with_copay_link,
    setup_placed_mail_order, setup_telehealth_referral,
    create_active_gold_member, create_member, create_drug, create_pharmacy,
    create_quote, set_clock,
    assert_gold_membership, assert_claim, assert_discount_card,
    assert_price_comparison, assert_telehealth_referral, assert_mail_order,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OPERATOR = TEST_USERS["pharmacy_operator_headers"]
SPONSOR = TEST_USERS["copay_sponsor_headers"]


# ─────────────────────────────────────────────────────────────────────────────
# Rule 3 / non_linear_state_machine — gold_membership_parallel_billing_access
# ─────────────────────────────────────────────────────────────────────────────

def test_voluntary_revoke_leaves_billing_paid(api):
    """PRD §3.5: "A member may also voluntarily revoke their own membership when
    its access dimension is ACTIVE, moving access from ACTIVE to REVOKED and
    clearing the member's active_gold_membership_id; under a voluntary revoke the
    billing_status is deliberately left unchanged, since the two dimensions are
    independent."

    Design: Difficulty/non_linear_state_machine/gold_membership_parallel_billing_access_dimensions
    """
    member, gm = create_active_gold_member(member_overrides={"email": "g@x.com"})
    assert gm["billing_status"] == "PAID"
    assert gm["access_status"] == "ACTIVE"
    headers = make_member_headers(member["id"])
    revoked = validate_success(api.revoke_gold_membership(
        gm["id"], {"member_id": member["id"]}, headers), 200)
    assert_gold_membership(revoked)
    assert revoked["access_status"] == "REVOKED"
    assert revoked["billing_status"] == "PAID"
    fresh_member = validate_success(api.get_member(member["id"], headers), 200)
    assert fresh_member["active_gold_membership_id"] is None


def test_first_payment_activates_access_dimension(api):
    """PRD §3.5: "Recording a payment on a membership whose billing is
    PENDING_PAYMENT moves the billing dimension to PAID. As a cross-dimension
    side effect of that first successful payment, if the access dimension is
    currently INACTIVE it is set to ACTIVE, and the owning member's
    active_gold_membership_id is set to this membership's id".

    Design: Difficulty/non_linear_state_machine/gold_membership_parallel_billing_access_dimensions
    """
    member = create_member(email="g2@x.com")
    headers = make_member_headers(member["id"])
    gm = get_success_data(api.create_gold_membership(
        create_gold_membership_payload(member["id"]), headers))
    paid = validate_success(api.record_gold_payment(gm["id"], ADMIN), 200)
    assert paid["billing_status"] == "PAID"
    assert paid["access_status"] == "ACTIVE"
    fresh_member = validate_success(api.get_member(member["id"], headers), 200)
    assert fresh_member["active_gold_membership_id"] == gm["id"]


# ─────────────────────────────────────────────────────────────────────────────
# Rule 3 / non_linear_state_machine — claim_branching_revert_cycle_reissues_card
# ─────────────────────────────────────────────────────────────────────────────

def test_reverse_adjudicated_claim_reissues_card(api):
    """PRD §3.9: "On success the claim moves from ADJUDICATED to REVERSED, and the
    compensations fire. The discount card is re-issued, transitioning from
    REDEEMED back to ISSUED so it can be adjudicated again."

    Design: Difficulty/non_linear_state_machine/claim_branching_revert_cycle_reissues_card
    """
    ctx = setup_adjudicated_claim(quantity=2)
    reversed_claim = validate_success(api.reverse_claim(
        ctx["claim"]["id"], {"expected_claim_version": ctx["claim_version"]}, OPERATOR), 200)
    assert_claim(reversed_claim)
    assert reversed_claim["status"] == "REVERSED"
    card = validate_success(api.get_discount_card(ctx["card"]["id"], ADMIN), 200)
    assert card["status"] == "ISSUED"


def test_adjudicate_redeems_card_then_reverse_reissues(api):
    """PRD §3.7: "The card transitions from ISSUED to REDEEMED." PRD §3.9: "Because
    the card returns to ISSUED, a fresh claim can be submitted and adjudicated,
    supporting reversal-and-re-adjudication rounds."

    Design: Difficulty/non_linear_state_machine/claim_branching_revert_cycle_reissues_card
    """
    ctx = setup_adjudicated_claim(quantity=2)
    redeemed = validate_success(api.get_discount_card(ctx["card"]["id"], ADMIN), 200)
    assert redeemed["status"] == "REDEEMED"
    validate_success(api.reverse_claim(
        ctx["claim"]["id"], {"expected_claim_version": ctx["claim_version"]}, OPERATOR), 200)
    reissued = validate_success(api.get_discount_card(ctx["card"]["id"], ADMIN), 200)
    assert reissued["status"] == "ISSUED"


# ─────────────────────────────────────────────────────────────────────────────
# Rule 4 / transitive_cascade — adjudicate_claim_link_copaycard_exhaust_depth3
# ─────────────────────────────────────────────────────────────────────────────

def test_adjudicate_cascades_link_applied_and_card_exhausted(api):
    """PRD §3.8: "the card's remaining_benefit_cents is reduced by it, and the
    link transitions from LINKED to APPLIED — a transitive cascade from claim to
    link to copay card." and "Whenever the draw brings remaining_benefit_cents to
    zero, the copay card itself transitions from ACTIVE to EXHAUSTED as a further
    transitive hop."

    Design: Difficulty/transitive_cascade/adjudicate_claim_link_copaycard_exhaust_depth3
    """
    ctx = setup_submitted_claim_with_copay_link(
        quantity=2, max_benefit_cents=3000, per_fill_cap_cents=8000)
    claim = validate_success(api.adjudicate_claim(ctx["claim"]["id"], OPERATOR), 200)
    assert claim["status"] == "ADJUDICATED"
    link = validate_success(api.get_copay_link(ctx["copay_link"]["id"], ADMIN), 200)
    assert link["status"] == "APPLIED"
    assert link["applied_offset_cents"] == 3000
    cc = validate_success(api.get_copay_card(ctx["copay_card"]["id"], ADMIN), 200)
    assert cc["remaining_benefit_cents"] == 0
    assert cc["status"] == "EXHAUSTED"


def test_adjudicate_cascades_link_applied_card_stays_active_when_not_exhausted(api):
    """PRD §3.8: "the card's remaining_benefit_cents is reduced by it, and the
    link transitions from LINKED to APPLIED — a transitive cascade from claim to
    link to copay card." The third hop is conditional: "Whenever the draw brings
    remaining_benefit_cents to zero, the copay card itself transitions from ACTIVE
    to EXHAUSTED". A per-fill-bound draw (4000 of 50000) leaves the card ACTIVE.

    Design: Difficulty/transitive_cascade/adjudicate_claim_link_copaycard_exhaust_depth3
    """
    ctx = setup_submitted_claim_with_copay_link(
        quantity=2, max_benefit_cents=50000, per_fill_cap_cents=4000)
    claim = validate_success(api.adjudicate_claim(ctx["claim"]["id"], OPERATOR), 200)
    assert claim["status"] == "ADJUDICATED"
    link = validate_success(api.get_copay_link(ctx["copay_link"]["id"], ADMIN), 200)
    assert link["status"] == "APPLIED"
    assert link["applied_offset_cents"] == 4000
    cc = validate_success(api.get_copay_card(ctx["copay_card"]["id"], ADMIN), 200)
    assert cc["remaining_benefit_cents"] == 46000
    assert cc["status"] == "ACTIVE"


# ─────────────────────────────────────────────────────────────────────────────
# Rule 4 / transitive_cascade — suspend_pharmacy_expires_published_quotes_depth2
# ─────────────────────────────────────────────────────────────────────────────

def test_suspend_pharmacy_expires_published_quotes(api):
    """PRD §3.1: "A PlatformAdmin may move a pharmacy that is currently ACTIVE to
    SUSPENDED; this suspension cascades to the pharmacy's quotes — every PriceQuote
    belonging to that pharmacy that is currently PUBLISHED transitions from
    PUBLISHED to EXPIRED (only PUBLISHED quotes are affected)."

    Design: Difficulty/transitive_cascade/suspend_pharmacy_expires_published_quotes_depth2
    """
    set_clock()
    drug = create_drug()
    ph = create_pharmacy()
    q1 = create_quote(drug["id"], ph["id"],
                      effective_at="2026-05-01T00:00:00Z", expires_at="2026-06-01T00:00:00Z")
    q2 = create_quote(drug["id"], ph["id"], cash_price_cents=6800,
                      discount_price_cents=5400, gold_price_cents=5100,
                      effective_at="2026-06-01T00:00:00Z", expires_at="2026-07-01T00:00:00Z")
    suspended = validate_success(api.suspend_pharmacy(ph["id"], ADMIN), 200)
    assert suspended["status"] == "SUSPENDED"
    assert validate_success(api.get_price_quote(q1["id"], ADMIN), 200)["status"] == "EXPIRED"
    assert validate_success(api.get_price_quote(q2["id"], ADMIN), 200)["status"] == "EXPIRED"


def test_suspend_cascade_only_affects_published_quotes(api):
    """PRD §3.1: "every PriceQuote belonging to that pharmacy that is currently
    PUBLISHED transitions from PUBLISHED to EXPIRED (only PUBLISHED quotes are
    affected)." A quote already EXPIRED before the suspend stays EXPIRED, while
    the remaining PUBLISHED quote is cascaded to EXPIRED.

    Design: Difficulty/transitive_cascade/suspend_pharmacy_expires_published_quotes_depth2
    """
    set_clock()
    drug = create_drug()
    ph = create_pharmacy()
    q1 = create_quote(drug["id"], ph["id"],
                      effective_at="2026-05-01T00:00:00Z", expires_at="2026-06-01T00:00:00Z")
    q2 = create_quote(drug["id"], ph["id"], cash_price_cents=6800,
                      discount_price_cents=5400, gold_price_cents=5100,
                      effective_at="2026-06-01T00:00:00Z", expires_at="2026-07-01T00:00:00Z")
    # Explicitly expire q1 first so it is already terminal before the suspend.
    get_success_data(api.expire_price_quote(q1["id"], ADMIN))
    assert validate_success(api.get_price_quote(q1["id"], ADMIN), 200)["status"] == "EXPIRED"
    validate_success(api.suspend_pharmacy(ph["id"], ADMIN), 200)
    assert validate_success(api.get_price_quote(q1["id"], ADMIN), 200)["status"] == "EXPIRED"
    assert validate_success(api.get_price_quote(q2["id"], ADMIN), 200)["status"] == "EXPIRED"


# ─────────────────────────────────────────────────────────────────────────────
# Corner / state_machines — telehealth_referral_full_linear_lifecycle
# ─────────────────────────────────────────────────────────────────────────────

def test_telehealth_referral_full_linear_lifecycle(api):
    """PRD §3.11: "A PlatformAdmin schedules a REQUESTED referral, moving it from
    REQUESTED to SCHEDULED, and later completes a SCHEDULED referral, moving it
    from SCHEDULED to COMPLETED."

    Design: Corner/state_machines/telehealth_referral_full_linear_lifecycle
    """
    ctx = setup_telehealth_referral(reason="PRICE_TOO_HIGH")
    ref = ctx["referral"]
    assert ref["status"] == "REQUESTED"
    scheduled = validate_success(api.schedule_telehealth_referral(ref["id"], ADMIN), 200)
    assert scheduled["status"] == "SCHEDULED"
    completed = validate_success(api.complete_telehealth_referral(ref["id"], ADMIN), 200)
    assert_telehealth_referral(completed)
    assert completed["status"] == "COMPLETED"


# ─────────────────────────────────────────────────────────────────────────────
# Corner / state_machines — complete_telehealth_from_requested_invalid_state
# ─────────────────────────────────────────────────────────────────────────────

def test_complete_telehealth_from_requested_invalid_state(api):
    """PRD §3.11: "later completes a SCHEDULED referral, moving it from SCHEDULED
    to COMPLETED." PRD §2.7: a state conflict "that the target resource is in a
    state from which the requested transition is defined (ERR_INVALID_STATE)".

    Design: Corner/state_machines/complete_telehealth_from_requested_invalid_state
    """
    from test_helpers import validate_error
    ctx = setup_telehealth_referral(reason="NEW_PRESCRIPTION")
    ref = ctx["referral"]
    res = api.complete_telehealth_referral(ref["id"], ADMIN)
    validate_error(res, "ERR_INVALID_STATE")
    after = validate_success(api.get_telehealth_referral(ref["id"], ADMIN), 200)
    assert after["status"] == "REQUESTED"


# ─────────────────────────────────────────────────────────────────────────────
# Corner / state_machines — void_already_void_card_returns_invalid_state
# ─────────────────────────────────────────────────────────────────────────────

def test_void_already_void_card_returns_invalid_state(api):
    """PRD §3.6: "A member may void their own ISSUED card directly (supplying
    their member_id), moving it from ISSUED to VOID". PRD §2.7: a transition from
    a state where it is not defined fails with ERR_INVALID_STATE.

    Design: Corner/state_machines/void_already_void_card_returns_invalid_state
    """
    from test_helpers import validate_error
    ctx = setup_discount_card(member_overrides={"email": "vv@x.com"})
    headers = make_member_headers(ctx["member"]["id"])
    validate_success(api.void_discount_card(
        ctx["card"]["id"], {"member_id": ctx["member"]["id"]}, headers), 200)
    res = api.void_discount_card(ctx["card"]["id"], {"member_id": ctx["member"]["id"]}, headers)
    validate_error(res, "ERR_INVALID_STATE")


# ─────────────────────────────────────────────────────────────────────────────
# Corner / state_machines — gold_lapse_voids_gold_basis_cards_cascade
# ─────────────────────────────────────────────────────────────────────────────

def test_gold_lapse_voids_gold_basis_cards_cascade(api):
    """PRD §3.5: "Lapsing a membership whose billing is PAID moves billing to
    PAST_DUE; this revokes access by moving the access dimension from ACTIVE to
    REVOKED, clears the member's active_gold_membership_id to null, and cascades
    to the member's coupons: every DiscountCard owned by that member that is
    currently ISSUED and whose pricing_basis is GOLD transitions from ISSUED to
    VOID (only GOLD-basis issued cards are voided)."

    Design: Corner/state_machines/gold_lapse_voids_gold_basis_cards_cascade
    """
    member, gm = create_active_gold_member(member_overrides={"email": "gl@x.com"})
    ctx = setup_discount_card(member=member, gold=False)  # member is already gold-active
    assert ctx["card"]["pricing_basis"] == "GOLD"
    lapsed = validate_success(api.lapse_gold_membership(gm["id"], ADMIN), 200)
    assert lapsed["billing_status"] == "PAST_DUE"
    assert lapsed["access_status"] == "REVOKED"
    card = validate_success(api.get_discount_card(ctx["card"]["id"], ADMIN), 200)
    assert card["status"] == "VOID"
    assert card["pricing_basis"] == "GOLD"
    fresh_member = validate_success(api.get_member(member["id"],
                                    make_member_headers(member["id"])), 200)
    assert fresh_member["active_gold_membership_id"] is None


# ─────────────────────────────────────────────────────────────────────────────
# Corner / state_machines — copaycard_withdraw_releases_linked_not_applied
# ─────────────────────────────────────────────────────────────────────────────

def test_copaycard_withdraw_releases_linked_link(api):
    """PRD §3.8: "A sponsor may withdraw an ACTIVE copay card, moving it from
    ACTIVE to WITHDRAWN; this cascades to its links — every CopayLink referencing
    that card that is currently LINKED transitions from LINKED to RELEASED, while
    links already APPLIED are left untouched."

    Design: Corner/state_machines/copaycard_withdraw_releases_linked_not_applied
    """
    ctx = setup_submitted_claim_with_copay_link(quantity=2)
    assert ctx["copay_link"]["status"] == "LINKED"
    withdrawn = validate_success(api.withdraw_copay_card(ctx["copay_card"]["id"], SPONSOR), 200)
    assert withdrawn["status"] == "WITHDRAWN"
    link = validate_success(api.get_copay_link(ctx["copay_link"]["id"], ADMIN), 200)
    assert link["status"] == "RELEASED"


# ─────────────────────────────────────────────────────────────────────────────
# Corner / state_machines — terminal_claim_rejected_cannot_adjudicate
# ─────────────────────────────────────────────────────────────────────────────

def test_terminal_claim_rejected_cannot_adjudicate(api):
    """PRD §3.7: "A pharmacy operator may instead reject a SUBMITTED claim, moving
    it from SUBMITTED to REJECTED with no pricing fields set; REJECTED is
    terminal." PRD §3.7: adjudication "requires the claim to be SUBMITTED".

    Design: Corner/state_machines/terminal_claim_rejected_cannot_adjudicate
    """
    from test_helpers import validate_error
    ctx = setup_submitted_claim(quantity=2)
    validate_success(api.reject_claim(ctx["claim"]["id"], OPERATOR), 200)
    res = api.adjudicate_claim(ctx["claim"]["id"], OPERATOR)
    validate_error(res, "ERR_INVALID_STATE")
    after = validate_success(api.get_claim(ctx["claim"]["id"], OPERATOR), 200)
    assert after["status"] == "REJECTED"


# ─────────────────────────────────────────────────────────────────────────────
# Corner / state_machines — claim_reverse_stale_version_conflict
# ─────────────────────────────────────────────────────────────────────────────

def test_claim_reverse_stale_version_conflict(api):
    """PRD §2.6: "The server compares this value against the claim's current
    version ... if another writer has advanced the claim's version since the
    client last read it, the reversal is rejected with ERR_STALE_VERSION and HTTP
    status 412." The version observed at creation is one behind the post-
    adjudication version.

    Design: Corner/state_machines/claim_reverse_stale_version_conflict
    """
    from test_helpers import validate_error
    ctx = setup_submitted_claim(quantity=2)
    stale_version = ctx["claim"]["version"]
    validate_success(api.adjudicate_claim(ctx["claim"]["id"], OPERATOR), 200)
    res = api.reverse_claim(ctx["claim"]["id"],
                            {"expected_claim_version": stale_version}, OPERATOR)
    validate_error(res, "ERR_STALE_VERSION")
    after = validate_success(api.get_claim(ctx["claim"]["id"], OPERATOR), 200)
    assert after["status"] == "ADJUDICATED"


# ─────────────────────────────────────────────────────────────────────────────
# Corner / state_machines — comparison_resolved_initial_then_convert
# ─────────────────────────────────────────────────────────────────────────────

def test_comparison_opens_resolves_then_converts(api):
    """PRD §3.3: "The comparison begins in status OPEN." and "If at least one
    eligible quote exists, the comparison advances from OPEN to RESOLVED". PRD
    §3.6: "issuance both creates the card and advances the comparison from
    RESOLVED to CONVERTED."

    Design: Corner/state_machines/comparison_resolved_initial_then_convert
    """
    ctx = setup_resolved_comparison(member_overrides={"email": "cv@x.com"})
    assert ctx["comparison"]["status"] == "RESOLVED"
    headers = make_member_headers(ctx["member"]["id"])
    card = validate_success(api.create_discount_card(
        create_discount_card_payload(ctx["member"]["id"], ctx["comparison"]["id"]),
        headers), 201)
    assert card["status"] == "ISSUED"
    cmp = validate_success(api.get_comparison(ctx["comparison"]["id"], headers), 200)
    assert cmp["status"] == "CONVERTED"


# ─────────────────────────────────────────────────────────────────────────────
# Corner / state_machines — mail_order_cancel_from_placed
# ─────────────────────────────────────────────────────────────────────────────

def test_mail_order_cancel_from_placed(api):
    """PRD §3.10: "The ordering member may cancel a PLACED order, moving it from
    PLACED to CANCELLED."

    Design: Corner/state_machines/mail_order_cancel_from_placed
    """
    ctx = setup_placed_mail_order(quantity=2, member_overrides={"email": "mo@x.com"})
    headers = make_member_headers(ctx["member"]["id"])
    cancelled = validate_success(api.cancel_mail_order(
        ctx["mail_order"]["id"], {"member_id": ctx["member"]["id"]}, headers), 200)
    assert_mail_order(cancelled)
    assert cancelled["status"] == "CANCELLED"
