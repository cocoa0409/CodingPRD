"""Prior-authorization lifecycle, claim cascades, and reversal unwinds
(PRD §3.3, §3.4, §3.5, §3.7).

Covers Difficulty queue: non_linear_state_machine (PA deny/appeal/approve, claim
parallel dimensions), transitive_cascade (PA auto-expire, copay-card unwind),
cross_entity_state_dependency (claim requires PA APPROVED / plan ACTIVE),
compensating_invariant (copay card + PA fill restore), dual_variant rebate.
"""
from test_helpers import fixtures as fx, validate_error, ApiErrorId
from test_helpers.api_client import api_client
from test_helpers.test_users import REVIEWER_ID, DIRECTOR_ID
from test_helpers import make_reviewer_headers, make_director_headers


# ─── non_linear_state_machine / pa_deny_appeal_approve_cycle ────────────────
def test_pa_deny_appeal_approve_cycle(api):
    """PRD §3.3: "a `PharmacistReviewer` may appeal it, moving it from `DENIED` to `APPEALED`, which clears `decided_by_user_id` back to null and increments the version"
    PRD §3.3: "An appealed authorization can then be approved or denied exactly as a
    pending one can"
    PRD §3.3: "Approving an authorization moves it from `PENDING_REVIEW` to `APPROVED` (or from `APPEALED` to `APPROVED`), records the deciding director in `decided_by_user_id`, sets `approved_quantity_remaining` equal to `authorized_fills"

    Design: Difficulty/non_linear_state_machine/pa_deny_appeal_approve_cycle
    """
    plan = fx.create_plan(deductible_cents=0, oop_max_cents=200000)
    drug = fx.create_drug(plan["id"], ndc="X", drug_name="X", tier="TIER_2",
                          ingredient_cost_cents=30000, pa_required=True)
    m = fx.create_member(plan["id"])
    pa = fx.submit_pa(m["id"], drug["id"], submitter_id="U_REV", authorized_fills=1)
    denied = fx.decide_pa(pa["id"], "DENY", pa["version"], decider_id="U_DIR")
    assert denied["status"] == "DENIED"
    appealed = fx.appeal_pa(pa["id"], appellant_id="U_REV")
    assert appealed["status"] == "APPEALED"
    assert appealed["decided_by_user_id"] is None

    approved = fx.decide_pa(pa["id"], "APPROVE", appealed["version"], decider_id="U_DIR")
    assert approved["status"] == "APPROVED"
    assert approved["approved_quantity_remaining"] == 1
    assert approved["decided_by_user_id"] == "U_DIR"


def test_appeal_then_deny_keeps_branching_machine(api):
    """PRD §3.3: "Denying an authorization moves it from `PENDING_REVIEW` to `DENIED` (or from `APPEALED` to `DENIED`), records `decided_by_user_id`, and increments the version."
    PRD §3.3: "a `PharmacistReviewer` may appeal it, moving it from `DENIED` to `APPEALED`, which clears `decided_by_user_id` back to null and increments the version"

    Design: Difficulty/non_linear_state_machine/pa_deny_appeal_approve_cycle
    """
    plan = fx.create_plan(deductible_cents=0, oop_max_cents=200000)
    drug = fx.create_drug(plan["id"], ndc="X", drug_name="X", tier="TIER_2",
                          ingredient_cost_cents=30000, pa_required=True)
    m = fx.create_member(plan["id"])
    pa = fx.submit_pa(m["id"], drug["id"], submitter_id="U_REV", authorized_fills=1)
    denied = fx.decide_pa(pa["id"], "DENY", pa["version"], decider_id="U_DIR")
    appealed = fx.appeal_pa(pa["id"], appellant_id="U_REV")
    redenied = fx.decide_pa(pa["id"], "DENY", appealed["version"], decider_id="U_DIR")
    assert redenied["status"] == "DENIED"
    assert redenied["decided_by_user_id"] == "U_DIR"


# ─── non_linear_state_machine / claim_parallel_adjudication_and_rebate ──────
def test_claim_parallel_adjudication_and_rebate_dimensions(api):
    """PRD §3.7: "the originating claim's independent `rebate_status` dimension is set to `ACCRUED`."
    PRD §3.7: "if instead the accrual has already been `FINALIZED`, the system sets the accrual's `clawback_cents` to its `accrued_cents` multiplied by the agreement's `clawback_pct`, rounded half-up to a whole cent, moves the accrual from `FINALIZED` to `CLAWED_BACK` (incrementing its version), and sets the claim's `rebate_status` to `CLAWED_BACK`."

    Design: Difficulty/non_linear_state_machine/claim_parallel_adjudication_and_rebate_dimensions
    """
    plan, drug, member, claim, accrual = fx.setup_finalized_rebate_claim(
        clock="2026-05-01T00:00:00.000Z", clawback_pct=1.0, rebate_per_fill_cents=4000,
        tier="TIER_1", ingredient_cost_cents=10000,
    )
    assert claim["adjudication_status"] == "PAID"
    fx.reverse_claim(claim["id"])

    claim_after = fx.get_claim(claim["id"])
    assert claim_after["adjudication_status"] == "REVERSED"
    assert claim_after["rebate_status"] == "CLAWED_BACK"
    accrual_after = fx.get_accrual_for_claim(claim["id"])
    assert accrual_after["clawback_cents"] == 4000, accrual_after["clawback_cents"]


# ─── dual_variant_calc / rebate_provisional_delete_vs_finalized_clawback ────
def test_finalized_rebate_clawback_on_reversal(api):
    """PRD §3.7: "the system sets the accrual's `clawback_cents` to its `accrued_cents` multiplied by the agreement's `clawback_pct`, rounded half-up to a whole cent, moves the accrual from `FINALIZED` to `CLAWED_BACK` (incrementing its version), and sets the claim's `rebate_status` to `CLAWED_BACK`."
    PRD §3.7: "a 90-day fill counts as three fills and accrues three times the per-fill
    rebate."

    Design: Difficulty/dual_variant_calc/rebate_provisional_delete_vs_finalized_clawback
    """
    plan, drug, member, claim, accrual = fx.setup_finalized_rebate_claim(
        clock="2026-02-01T00:00:00.000Z", clawback_pct=0.5, rebate_per_fill_cents=4000,
        days_supply=90, pharmacy_type="MAIL_ORDER", tier="TIER_2",
        ingredient_cost_cents=30000, mail_multiplier=2.0,
    )
    assert accrual["accrued_cents"] == 12000, accrual["accrued_cents"]
    fx.reverse_claim(claim["id"])

    claim_after = fx.get_claim(claim["id"])
    assert claim_after["rebate_status"] == "CLAWED_BACK"
    accrual_after = fx.get_accrual_for_claim(claim["id"])
    assert accrual_after["status"] == "CLAWED_BACK"
    # round_half_up(12000 * 0.5) = 6000.
    assert accrual_after["clawback_cents"] == 6000, accrual_after["clawback_cents"]
    assert accrual_after["accrued_cents"] == 12000, accrual_after["accrued_cents"]


def test_provisional_rebate_deleted_on_early_reversal(api):
    """PRD §3.7: "if a rebate accrual exists for this claim and it is still `PROVISIONAL`, the accrual is deleted and the claim's `rebate_status` returns to `NONE"

    Design: Difficulty/dual_variant_calc/rebate_provisional_delete_vs_finalized_clawback
    """
    fx.set_clock("2026-02-05T00:00:00.000Z")
    plan = fx.create_plan(deductible_cents=0, oop_max_cents=200000)
    fx.create_rebate_agreement(plan["id"], clawback_pct=0.5)
    drug = fx.create_drug(plan["id"], ndc="RB", drug_name="RB", tier="TIER_2",
                          ingredient_cost_cents=30000, rebate_per_fill_cents=4000)
    m = fx.create_member(plan["id"])
    claim = fx.submit_claim(m["id"], drug["id"], days_supply=30, pharmacy_type="RETAIL")
    assert claim["rebate_status"] == "ACCRUED"
    # No finalize — accrual is PROVISIONAL.
    fx.reverse_claim(claim["id"])
    claim_after = fx.get_claim(claim["id"])
    assert claim_after["rebate_status"] == "NONE", claim_after["rebate_status"]
    assert fx.get_accrual_for_claim(claim["id"]) is None


# ─── transitive_cascade / claim_paid_consumes_pa_last_fill_auto_expires ─────
def test_claim_paid_consumes_last_pa_fill_auto_expires(api):
    """PRD §3.4: "if the claim consumed a prior authorization, that authorization's `approved_quantity_remaining` is decremented by one; should the remaining count reach zero, the authorization auto-transitions from `APPROVED` to `EXPIRED` and its version increments."

    Design: Difficulty/transitive_cascade/claim_paid_consumes_pa_last_fill_auto_expires
    """
    fx.set_clock("2026-06-01T00:00:00.000Z")
    plan = fx.create_plan(deductible_cents=0, oop_max_cents=200000)
    drug = fx.create_drug(plan["id"], ndc="PA1", drug_name="PA Drug", tier="TIER_2",
                          ingredient_cost_cents=30000, pa_required=True)
    m = fx.create_member(plan["id"])
    pa = fx.submit_and_approve_pa(m["id"], drug["id"], submitter_id="U_REV",
                                  decider_id="U_DIR", authorized_fills=1)
    claim = fx.submit_claim(m["id"], drug["id"], days_supply=30, pharmacy_type="RETAIL",
                            prior_auth_id=pa["id"])
    assert claim["adjudication_status"] == "PAID"
    pa_after = fx.get_pa(pa["id"])
    assert pa_after["approved_quantity_remaining"] == 0
    assert pa_after["status"] == "EXPIRED"


# ─── transitive_cascade / claim_reverse_unwinds_copay_card_to_active ────────
def test_reverse_unwinds_copay_card_to_active(api):
    """PRD §3.7: "If the claim drew on a copay card, that card's `benefit_used_cents` is recomputed excluding this claim, and if the used benefit drops below the card's `max_benefit_cents` the card's `status` returns to `ACTIVE`."

    Design: Difficulty/transitive_cascade/claim_reverse_unwinds_copay_card_to_active
    """
    fx.set_clock("2026-07-01T00:00:00.000Z")
    plan = fx.create_plan(deductible_cents=0, oop_max_cents=200000)
    drug = fx.create_drug(plan["id"], ndc="SP", drug_name="Spec", tier="SPECIALTY",
                          ingredient_cost_cents=200000, is_specialty=True)
    m = fx.create_member(plan["id"])
    card = fx.create_copay_card(m["id"], drug["id"], max_benefit_cents=20000)
    claim = fx.submit_claim(m["id"], drug["id"], days_supply=30, pharmacy_type="SPECIALTY",
                            copay_card_id=card["id"])
    assert claim["adjudication_status"] == "PAID"
    card_mid = fx.get_copay_card(card["id"])
    assert card_mid["status"] == "EXHAUSTED"

    fx.reverse_claim(claim["id"])
    card_after = fx.get_copay_card(card["id"])
    assert card_after["benefit_used_cents"] == 0, card_after["benefit_used_cents"]
    assert card_after["status"] == "ACTIVE", card_after["status"]


# ─── compensating_invariant / reverse_restores_copay_card_benefit_and_pa_fill ─
def test_reverse_restores_copay_card_benefit_and_pa_fill(api):
    """PRD §3.7: "If the claim consumed a prior authorization that has not been expired and consumed elsewhere, the authorization's `approved_quantity_remaining` is incremented by one to restore the consumed fill."
    PRD §3.7: "If the claim drew on a copay card, that card's `benefit_used_cents` is recomputed excluding this claim"

    Design: Difficulty/compensating_invariant/reverse_restores_copay_card_benefit_and_pa_fill
    """
    fx.set_clock("2026-05-15T00:00:00.000Z")
    plan = fx.create_plan(deductible_cents=0, oop_max_cents=500000)
    drug = fx.create_drug(plan["id"], ndc="SPA", drug_name="Spec PA", tier="SPECIALTY",
                          ingredient_cost_cents=200000, is_specialty=True, pa_required=True)
    m = fx.create_member(plan["id"])
    card = fx.create_copay_card(m["id"], drug["id"], max_benefit_cents=20000)
    pa = fx.submit_and_approve_pa(m["id"], drug["id"], submitter_id="U_REV",
                                  decider_id="U_DIR", authorized_fills=2)
    claim = fx.submit_claim(m["id"], drug["id"], days_supply=30, pharmacy_type="SPECIALTY",
                            prior_auth_id=pa["id"], copay_card_id=card["id"])
    assert claim["adjudication_status"] == "PAID"

    fx.reverse_claim(claim["id"])
    card_after = fx.get_copay_card(card["id"])
    pa_after = fx.get_pa(pa["id"])
    assert card_after["benefit_used_cents"] == 0, card_after["benefit_used_cents"]
    assert pa_after["approved_quantity_remaining"] == 2, pa_after["approved_quantity_remaining"]


# ─── cross_entity_state_dependency / claim_requires_pa_approved_state ───────
def test_claim_rejected_when_pa_still_pending(api):
    """PRD §3.4: "if the drug has `pa_required` set to true, the claim's `prior_auth_id` must reference an `APPROVED` authorization for the very same member and drug with `approved_quantity_remaining` of at least 1; a missing, mismatched, unapproved, or exhausted authorization is rejected with `ERR_PA_REQUIRED`."

    Design: Difficulty/cross_entity_state_dependency/claim_requires_pa_approved_state
    """
    fx.set_clock("2026-11-01T00:00:00.000Z")
    plan = fx.create_plan(deductible_cents=0, oop_max_cents=200000)
    drug = fx.create_drug(plan["id"], ndc="PA", drug_name="PA", tier="TIER_2",
                          ingredient_cost_cents=30000, pa_required=True)
    m = fx.create_member(plan["id"])
    pa = fx.submit_pa(m["id"], drug["id"], submitter_id="U_REV", authorized_fills=1)
    # PA left PENDING_REVIEW.
    resp = api_client.create_claim(
        {"member_id": m["id"], "formulary_drug_id": drug["id"], "days_supply": 30,
         "pharmacy_type": "RETAIL", "prior_auth_id": pa["id"]},
        fx.PROVIDER,
    )
    validate_error(resp, ApiErrorId.ERR_PA_REQUIRED.value)


# ─── cross_entity_state_dependency / claim_requires_plan_active_state ───────
def test_claim_rejected_when_plan_archived(api):
    """PRD §3.4: "all three referenced lifecycle resources must be live: the member must be `ACTIVE`, the drug must be `ACTIVE`, and the plan must be `ACTIVE`; a claim touching a terminated member, an inactive drug, or an archived plan is rejected with `ERR_INACTIVE_RESOURCE`."

    Design: Difficulty/cross_entity_state_dependency/claim_requires_plan_active_state
    """
    fx.set_clock("2026-11-15T00:00:00.000Z")
    plan = fx.create_plan(deductible_cents=0, oop_max_cents=200000)
    drug = fx.create_drug(plan["id"], ndc="Y", drug_name="Y", tier="TIER_1",
                          ingredient_cost_cents=10000)
    m = fx.create_member(plan["id"])
    fx.archive_plan(plan["id"])
    resp = api_client.create_claim(
        {"member_id": m["id"], "formulary_drug_id": drug["id"], "days_supply": 30,
         "pharmacy_type": "RETAIL"},
        fx.PROVIDER,
    )
    validate_error(resp, ApiErrorId.ERR_INACTIVE_RESOURCE.value)


# ─── Corner / calculations.step_satisfied_by_prior_first_line_paid_claim ────
def test_step_satisfied_by_prior_first_line_paid_claim(api):
    """PRD §3.4: "the member holds at least one `PAID` claim for a formulary drug whose `ndc` appears in the protocol's `first_line_ndcs` list."

    Design: Corner/calculations/step_satisfied_by_prior_first_line_paid_claim
    """
    fx.set_clock("2026-07-16T00:00:00.000Z")
    plan = fx.create_plan(deductible_cents=0, oop_max_cents=200000)
    proto = fx.create_protocol(plan["id"], name="ST", first_line_ndcs=["FL1"])
    first = fx.create_drug(plan["id"], ndc="FL1", drug_name="First", tier="TIER_1",
                           ingredient_cost_cents=10000)
    second = fx.create_drug(plan["id"], ndc="SL1", drug_name="Second", tier="TIER_2",
                            ingredient_cost_cents=30000, step_therapy_protocol_id=proto["id"])
    m = fx.create_member(plan["id"])
    fx.submit_claim(m["id"], first["id"], days_supply=30, pharmacy_type="RETAIL")
    claim = fx.submit_claim(m["id"], second["id"], days_supply=30, pharmacy_type="RETAIL")
    assert claim["adjudication_status"] == "PAID", claim["adjudication_status"]
