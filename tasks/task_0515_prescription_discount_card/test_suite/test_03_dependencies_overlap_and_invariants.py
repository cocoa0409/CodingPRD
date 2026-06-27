"""Cross-entity state dependencies, validation-priority precedence, temporal
overlap rules, and compensating-action conservation invariants.
"""
import pytest

from test_helpers import (
    api_client, get_success_data, validate_success, validate_error,
    make_member_headers, TEST_USERS,
    create_gold_membership_payload, create_discount_card_payload,
    create_claim_payload, create_price_quote_payload, create_comparison_payload,
    create_mail_order_payload,
    setup_resolved_comparison, setup_discount_card, setup_submitted_claim,
    setup_adjudicated_claim, setup_adjudicated_claim_with_copay,
    setup_placed_mail_order,
    create_member, create_drug, create_pharmacy, create_quote, set_clock,
    assert_claim,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OPERATOR = TEST_USERS["pharmacy_operator_headers"]


# ─────────────────────────────────────────────────────────────────────────────
# Rule 5 / priority_pair_validation_conflict — owner_auth_beats_state_on_card_void
# ─────────────────────────────────────────────────────────────────────────────

def test_owner_check_beats_state_on_card_void(api):
    """PRD §2.7: "then — for an entity-backed member acting on an owned resource —
    ownership (ERR_NOT_RESOURCE_OWNER). Only after authentication and
    authorization does the system verify existence ... Existence is followed by
    state checks ... (ERR_INVALID_STATE)." Authorization (ownership) precedes the
    state check, so a non-owner voiding an already-VOID card gets the owner error.

    Design: Difficulty/priority_pair_validation_conflict/owner_auth_beats_state_on_card_void
    """
    ctx = setup_discount_card(member_overrides={"email": "a@x.com"})
    owner = ctx["member"]
    owner_headers = make_member_headers(owner["id"])
    # Owner voids once -> card is now VOID.
    validate_success(api.void_discount_card(
        ctx["card"]["id"], {"member_id": owner["id"]}, owner_headers), 200)
    # A different member tries to void it: both ownership (P3) and state (P5) fail.
    other = create_member(email="b@x.com")
    other_headers = make_member_headers(other["id"])
    res = api.void_discount_card(ctx["card"]["id"], {"member_id": other["id"]}, other_headers)
    validate_error(res, "ERR_NOT_RESOURCE_OWNER")


def test_owner_check_beats_state_when_card_already_redeemed(api):
    """PRD §2.7: authorization (ownership, ERR_NOT_RESOURCE_OWNER) is evaluated
    before the state check (ERR_INVALID_STATE). A non-owner attempting to void a
    REDEEMED (non-ISSUED) card still receives the ownership rejection first.

    Design: Difficulty/priority_pair_validation_conflict/owner_auth_beats_state_on_card_void
    """
    ctx = setup_adjudicated_claim(quantity=2)  # card is now REDEEMED, owned by ctx member
    other = create_member(email="bb@x.com")
    other_headers = make_member_headers(other["id"])
    res = api.void_discount_card(ctx["card"]["id"], {"member_id": other["id"]}, other_headers)
    validate_error(res, "ERR_NOT_RESOURCE_OWNER")


# ─────────────────────────────────────────────────────────────────────────────
# Rule 5 / priority_pair_validation_conflict — card_state_beats_pharmacy_mismatch
# ─────────────────────────────────────────────────────────────────────────────

def test_card_state_beats_pharmacy_mismatch_on_claim_create(api):
    """PRD §2.7: "a state conflict always surfaces ahead of a business-rule
    rejection." PRD §3.7: "the referenced card must be ISSUED, otherwise the
    submission is rejected with ERR_INVALID_STATE; and the card's pharmacy_id must
    equal the claim's pharmacy_id ... a mismatch is rejected with
    ERR_PHARMACY_MISMATCH." Against a VOID card at a wrong pharmacy, state wins.

    Design: Difficulty/priority_pair_validation_conflict/card_state_beats_pharmacy_mismatch_on_claim_create
    """
    set_clock()
    drug = create_drug()
    ph1 = create_pharmacy(name="PH One", chain_code="CVS", dispense_fee_cents=200)
    ph2 = create_pharmacy(name="PH Two", chain_code="RITE", dispense_fee_cents=100)
    create_quote(drug["id"], ph1["id"])
    create_quote(drug["id"], ph2["id"], cash_price_cents=9000,
                 discount_price_cents=8000, gold_price_cents=7000)
    member = create_member(email="m5@x.com")
    headers = make_member_headers(member["id"])
    # Comparison scoped to CA; selector picks the cheaper PH1 (5500 < 8000).
    cmp = get_success_data(api.create_comparison(
        create_comparison_payload(member["id"], drug["id"]), headers))
    cmp = get_success_data(api.run_comparison(cmp["id"], {"member_id": member["id"]}, headers))
    assert cmp["selected_pharmacy_id"] == ph1["id"]
    card = get_success_data(api.create_discount_card(
        create_discount_card_payload(member["id"], cmp["id"]), headers))
    validate_success(api.void_discount_card(card["id"], {"member_id": member["id"]}, headers), 200)
    # Claim against the VOID card with a mismatched pharmacy (PH2).
    res = api.create_claim(create_claim_payload(card["id"], ph2["id"], quantity=2), OPERATOR)
    validate_error(res, "ERR_INVALID_STATE")


def test_claim_against_void_card_matching_pharmacy_invalid_state(api):
    """PRD §3.7: "the referenced card must be ISSUED, otherwise the submission is
    rejected with ERR_INVALID_STATE". Isolated state failure (correct pharmacy,
    VOID card) confirms the state gate independent of the mismatch rule.

    Design: Difficulty/priority_pair_validation_conflict/card_state_beats_pharmacy_mismatch_on_claim_create
    """
    ctx = setup_discount_card(member_overrides={"email": "m5b@x.com"})
    headers = make_member_headers(ctx["member"]["id"])
    validate_success(api.void_discount_card(
        ctx["card"]["id"], {"member_id": ctx["member"]["id"]}, headers), 200)
    res = api.create_claim(
        create_claim_payload(ctx["card"]["id"], ctx["pharmacy"]["id"], quantity=2), OPERATOR)
    validate_error(res, "ERR_INVALID_STATE")


# ─────────────────────────────────────────────────────────────────────────────
# Rule 6 / boundary_precision_check — comparison_empty_candidate_pool_no_results
# ─────────────────────────────────────────────────────────────────────────────

def test_comparison_empty_pool_drives_no_results(api):
    """PRD §3.3: "if the candidate pool is empty, it advances from OPEN to
    NO_RESULTS with candidate_count set to 0 and selected_pharmacy_id left null."
    A pharmacy in NY does not match a CA-scoped comparison.

    Design: Difficulty/boundary_precision_check/comparison_empty_candidate_pool_no_results
    """
    set_clock()
    drug = create_drug()
    ph = create_pharmacy(name="PH NY", chain_code="CVS", state_code="NY")
    create_quote(drug["id"], ph["id"])
    member = create_member(email="m7@x.com", state_code="CA")
    headers = make_member_headers(member["id"])
    cmp = get_success_data(api.create_comparison(
        create_comparison_payload(member["id"], drug["id"], state_code="CA"), headers))
    cmp = validate_success(api.run_comparison(cmp["id"], {"member_id": member["id"]}, headers), 200)
    assert cmp["status"] == "NO_RESULTS"
    assert cmp["candidate_count"] == 0
    assert cmp["selected_pharmacy_id"] is None


def test_comparison_one_matching_quote_resolves_not_no_results(api):
    """PRD §3.3: "If at least one eligible quote exists, the comparison advances
    from OPEN to RESOLVED". Boundary X+1 (one candidate) confirms the NO_RESULTS
    branch fires only on an empty pool.

    Design: Difficulty/boundary_precision_check/comparison_empty_candidate_pool_no_results
    """
    ctx = setup_resolved_comparison(member_overrides={"email": "m7b@x.com"})
    assert ctx["comparison"]["status"] == "RESOLVED"
    assert ctx["comparison"]["candidate_count"] == 1
    assert ctx["comparison"]["selected_pharmacy_id"] is not None


# ─────────────────────────────────────────────────────────────────────────────
# Rule 7 / cross_entity_state_dependency — adjudicate_requires_card_issued
# ─────────────────────────────────────────────────────────────────────────────

def test_adjudicate_blocked_when_card_voided(api):
    """PRD §3.7: "Adjudicating a SUBMITTED claim requires the claim to be
    SUBMITTED, the referenced card to be ISSUED, the card's pharmacy_id to equal
    the claim's pharmacy_id, and the adjudicating pharmacy to be ACTIVE; a state
    failure surfaces as ERR_INVALID_STATE".

    Design: Difficulty/cross_entity_state_dependency/adjudicate_requires_card_issued_claim_to_pharmacy
    """
    ctx = setup_submitted_claim(quantity=2, member_overrides={"email": "m8@x.com"})
    headers = make_member_headers(ctx["member"]["id"])
    validate_success(api.void_discount_card(
        ctx["card"]["id"], {"member_id": ctx["member"]["id"]}, headers), 200)
    res = api.adjudicate_claim(ctx["claim"]["id"], OPERATOR)
    validate_error(res, "ERR_INVALID_STATE")
    after = validate_success(api.get_claim(ctx["claim"]["id"], OPERATOR), 200)
    assert after["status"] == "SUBMITTED"


def test_adjudicate_succeeds_while_card_issued(api):
    """PRD §3.7: "Adjudicating a SUBMITTED claim requires the claim to be
    SUBMITTED, the referenced card to be ISSUED ... On success the claim moves
    from SUBMITTED to ADJUDICATED". Positive control: with the card left ISSUED,
    the cross-entity precondition is met and adjudication proceeds.

    Design: Difficulty/cross_entity_state_dependency/adjudicate_requires_card_issued_claim_to_pharmacy
    """
    ctx = setup_submitted_claim(quantity=2, member_overrides={"email": "m8b@x.com"})
    assert ctx["card"]["status"] == "ISSUED"
    claim = validate_success(api.adjudicate_claim(ctx["claim"]["id"], OPERATOR), 200)
    assert claim["status"] == "ADJUDICATED"
    card = validate_success(api.get_discount_card(ctx["card"]["id"], ADMIN), 200)
    assert card["status"] == "REDEEMED"


# ─────────────────────────────────────────────────────────────────────────────
# Rule 7 / cross_entity_state_dependency — mail_order_ship_requires_pharmacy_active
# ─────────────────────────────────────────────────────────────────────────────

def test_mail_order_ship_blocked_when_pharmacy_suspended(api):
    """PRD §3.10: "A pharmacy operator ships a PLACED order (which requires the
    pharmacy to be ACTIVE), moving it from PLACED to SHIPPED". Suspending the
    pharmacy first blocks the ship transition.

    Design: Difficulty/cross_entity_state_dependency/mail_order_ship_requires_pharmacy_active
    """
    ctx = setup_placed_mail_order(quantity=2, member_overrides={"email": "m9@x.com"})
    validate_success(api.suspend_pharmacy(ctx["pharmacy"]["id"], ADMIN), 200)
    res = api.ship_mail_order(ctx["mail_order"]["id"], OPERATOR)
    validate_error(res, "ERR_INVALID_STATE")
    after = validate_success(api.get_mail_order(ctx["mail_order"]["id"], ADMIN), 200)
    assert after["status"] == "PLACED"


def test_mail_order_ship_succeeds_while_pharmacy_active(api):
    """PRD §3.10: "A pharmacy operator ships a PLACED order (which requires the
    pharmacy to be ACTIVE), moving it from PLACED to SHIPPED". Positive control:
    with the pharmacy left ACTIVE, the cross-entity precondition is met.

    Design: Difficulty/cross_entity_state_dependency/mail_order_ship_requires_pharmacy_active
    """
    ctx = setup_placed_mail_order(quantity=2, member_overrides={"email": "m9b@x.com"})
    assert ctx["pharmacy"]["status"] == "ACTIVE"
    shipped = validate_success(api.ship_mail_order(ctx["mail_order"]["id"], OPERATOR), 200)
    assert shipped["status"] == "SHIPPED"


# ─────────────────────────────────────────────────────────────────────────────
# Rule 8 / resource_temporal_overlap — price_quote_half_open_window_overlap
# ─────────────────────────────────────────────────────────────────────────────

def test_price_quote_overlapping_window_rejected(api):
    """PRD §3.2: "a new quote whose half-open window intersects an existing
    PUBLISHED quote's half-open window for that same pharmacy_id and drug_id is
    rejected with ERR_QUOTE_PERIOD_OVERLAP."

    Existing [2026-05-01,2026-06-01); new [2026-05-15,2026-07-01) intersects.

    Design: Difficulty/resource_temporal_overlap/price_quote_half_open_window_overlap_rejected
    """
    set_clock("2026-05-02T00:00:00Z")
    drug = create_drug()
    ph = create_pharmacy()
    create_quote(drug["id"], ph["id"],
                 effective_at="2026-05-01T00:00:00Z", expires_at="2026-06-01T00:00:00Z")
    res = api.create_price_quote(create_price_quote_payload(
        drug["id"], ph["id"], cash_price_cents=6900, discount_price_cents=5400,
        gold_price_cents=5100, effective_at="2026-05-15T00:00:00Z",
        expires_at="2026-07-01T00:00:00Z"), ADMIN)
    validate_error(res, "ERR_QUOTE_PERIOD_OVERLAP")


def test_price_quote_abutting_window_allowed(api):
    """PRD §3.2: "Abutment is explicitly permitted — if the new quote's
    effective_at exactly equals an existing quote's expires_at, the windows touch
    but do not overlap, and the new quote is allowed." Boundary case of the
    half-open rule (touch, not intersect).

    Design: Difficulty/resource_temporal_overlap/price_quote_half_open_window_overlap_rejected
    """
    set_clock("2026-05-02T00:00:00Z")
    drug = create_drug()
    ph = create_pharmacy()
    create_quote(drug["id"], ph["id"],
                 effective_at="2026-05-01T00:00:00Z", expires_at="2026-06-01T00:00:00Z")
    q2 = validate_success(api.create_price_quote(create_price_quote_payload(
        drug["id"], ph["id"], cash_price_cents=6900, discount_price_cents=5400,
        gold_price_cents=5100, effective_at="2026-06-01T00:00:00Z",
        expires_at="2026-07-01T00:00:00Z"), ADMIN), 201)
    assert q2["status"] == "PUBLISHED"


# ─────────────────────────────────────────────────────────────────────────────
# Rule 8 / resource_temporal_overlap — gold_membership_closed_buffer_window
# ─────────────────────────────────────────────────────────────────────────────

def test_gold_membership_buffer_violation_rejected(api):
    """PRD §3.5: "a new membership is accepted only if its coverage_start falls at
    least one full day — 86,400 seconds — after an existing membership's
    coverage_end ... any new window that lands within the mandatory one-day buffer
    on either side ... is rejected with ERR_MEMBERSHIP_PERIOD_OVERLAP."

    Existing ends 2026-06-30T00:00:00Z; new starts 2026-06-30T12:00:00Z (only
    43200 s later) -> within the 86400 s buffer.

    Design: Difficulty/resource_temporal_overlap/gold_membership_closed_buffer_window_overlap_rejected
    """
    set_clock()
    member = create_member(email="ov@x.com")
    headers = make_member_headers(member["id"])
    get_success_data(api.create_gold_membership(
        create_gold_membership_payload(member["id"], coverage_start="2026-01-01T00:00:00Z",
                                        coverage_end="2026-06-30T00:00:00Z"), headers))
    res = api.create_gold_membership(
        create_gold_membership_payload(member["id"], coverage_start="2026-06-30T12:00:00Z",
                                        coverage_end="2026-12-31T00:00:00Z"), headers)
    validate_error(res, "ERR_MEMBERSHIP_PERIOD_OVERLAP")


def test_gold_membership_outside_buffer_allowed(api):
    """PRD §3.5: "a new membership is accepted only if its coverage_start falls at
    least one full day — 86,400 seconds — after an existing membership's
    coverage_end". A new start a full day-plus later clears the buffer.

    Existing ends 2026-06-30T00:00:00Z; new starts 2026-07-02T00:00:00Z (172800 s
    later, >= 86400 s) -> accepted.

    Design: Difficulty/resource_temporal_overlap/gold_membership_closed_buffer_window_overlap_rejected
    """
    set_clock()
    member = create_member(email="ov2@x.com")
    headers = make_member_headers(member["id"])
    get_success_data(api.create_gold_membership(
        create_gold_membership_payload(member["id"], coverage_start="2026-01-01T00:00:00Z",
                                        coverage_end="2026-06-30T00:00:00Z"), headers))
    gm2 = validate_success(api.create_gold_membership(
        create_gold_membership_payload(member["id"], coverage_start="2026-07-02T00:00:00Z",
                                        coverage_end="2026-12-31T00:00:00Z"), headers), 201)
    assert gm2["billing_status"] == "PENDING_PAYMENT"


# ─────────────────────────────────────────────────────────────────────────────
# Rule 9 / compensating_invariant — copaycard_benefit_pool_conserved_on_reverse
# ─────────────────────────────────────────────────────────────────────────────

def test_copaycard_benefit_restored_on_reverse(api):
    """PRD §3.9: "the APPLIED copay link transitions from APPLIED to RELEASED, the
    copay card's remaining_benefit_cents is restored by the link's
    applied_offset_cents, the link's applied_offset_cents is reset to 0, and if
    the copay card had been driven to EXHAUSTED it transitions from EXHAUSTED back
    to ACTIVE (the restore conserves the card's total benefit)."

    Design: Difficulty/compensating_invariant/copaycard_benefit_pool_conserved_on_reverse
    """
    ctx = setup_adjudicated_claim_with_copay(quantity=2, max_benefit_cents=3000,
                                             per_fill_cap_cents=8000)
    cc_before = validate_success(api.get_copay_card(ctx["copay_card"]["id"], ADMIN), 200)
    assert cc_before["remaining_benefit_cents"] == 0
    assert cc_before["status"] == "EXHAUSTED"
    reversed_claim = validate_success(api.reverse_claim(
        ctx["claim"]["id"], {"expected_claim_version": ctx["claim_version"]}, OPERATOR), 200)
    assert reversed_claim["status"] == "REVERSED"
    link = validate_success(api.get_copay_link(ctx["copay_link"]["id"], ADMIN), 200)
    assert link["status"] == "RELEASED"
    assert link["applied_offset_cents"] == 0
    cc = validate_success(api.get_copay_card(ctx["copay_card"]["id"], ADMIN), 200)
    assert cc["remaining_benefit_cents"] == 3000
    assert cc["status"] == "ACTIVE"


def test_copaycard_pool_conserved_with_per_fill_binding_offset(api):
    """PRD §3.9: "the copay card's remaining_benefit_cents is restored by the
    link's applied_offset_cents ... (the restore conserves the card's total
    benefit)." With a per-fill-bound draw (offset 4000 of a 50000 pool) the
    invariant remaining + applied == max_benefit holds before (46000+4000) and is
    restored after (50000+0) the reverse.

    Design: Difficulty/compensating_invariant/copaycard_benefit_pool_conserved_on_reverse
    """
    ctx = setup_adjudicated_claim_with_copay(quantity=2, max_benefit_cents=50000,
                                             per_fill_cap_cents=4000)
    cc_before = validate_success(api.get_copay_card(ctx["copay_card"]["id"], ADMIN), 200)
    link_before = validate_success(api.get_copay_link(ctx["copay_link"]["id"], ADMIN), 200)
    assert cc_before["remaining_benefit_cents"] == 46000
    assert link_before["applied_offset_cents"] == 4000
    assert cc_before["remaining_benefit_cents"] + link_before["applied_offset_cents"] == 50000
    validate_success(api.reverse_claim(
        ctx["claim"]["id"], {"expected_claim_version": ctx["claim_version"]}, OPERATOR), 200)
    cc_after = validate_success(api.get_copay_card(ctx["copay_card"]["id"], ADMIN), 200)
    link_after = validate_success(api.get_copay_link(ctx["copay_link"]["id"], ADMIN), 200)
    assert cc_after["remaining_benefit_cents"] == 50000
    assert link_after["applied_offset_cents"] == 0
    assert cc_after["status"] == "ACTIVE"


# ─────────────────────────────────────────────────────────────────────────────
# Rule 9 / compensating_invariant — member_lifetime_savings_conserved_on_reverse
# ─────────────────────────────────────────────────────────────────────────────

def test_member_lifetime_savings_restored_on_reverse(api):
    """PRD §3.9: "The owning member's lifetime_savings_cents is recomputed so that
    the now-reversed claim no longer counts". "The member's lifetime_savings_cents
    is always the reconciled sum of savings_cents over that member's claims that
    are currently ADJUDICATED ... Reversed and rejected claims are excluded".

    Design: Difficulty/compensating_invariant/member_lifetime_savings_conserved_on_reverse
    """
    ctx = setup_adjudicated_claim(quantity=2, member_overrides={"email": "m11@x.com"})
    headers = make_member_headers(ctx["member"]["id"])
    after_adj = validate_success(api.get_member(ctx["member"]["id"], headers), 200)
    assert after_adj["lifetime_savings_cents"] == 3000
    reversed_claim = validate_success(api.reverse_claim(
        ctx["claim"]["id"], {"expected_claim_version": ctx["claim_version"]}, OPERATOR), 200)
    assert reversed_claim["status"] == "REVERSED"
    after_rev = validate_success(api.get_member(ctx["member"]["id"], headers), 200)
    assert after_rev["lifetime_savings_cents"] == 0


def test_member_lifetime_savings_zero_before_first_adjudication(api):
    """PRD §3.9: "The member's lifetime_savings_cents is always the reconciled sum
    of savings_cents over that member's claims that are currently ADJUDICATED ...
    Reversed and rejected claims are excluded from the sum." A member whose only
    claim is still SUBMITTED (not yet ADJUDICATED) contributes 0 to the total,
    confirming the sum counts only ADJUDICATED claims (the conserved baseline a
    reverse must return to).

    Design: Difficulty/compensating_invariant/member_lifetime_savings_conserved_on_reverse
    """
    ctx = setup_submitted_claim(quantity=2, member_overrides={"email": "m11b@x.com"})
    headers = make_member_headers(ctx["member"]["id"])
    member = validate_success(api.get_member(ctx["member"]["id"], headers), 200)
    assert member["lifetime_savings_cents"] == 0
