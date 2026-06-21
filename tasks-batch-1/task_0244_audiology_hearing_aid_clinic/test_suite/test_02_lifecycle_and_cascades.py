"""State-machine lifecycle and cascade tests: severity classification, evaluation
supersession, warranty-claim cycle, fitting-order transitions, supply cycle billing
and loyalty, subscription lifecycle, recall fan-out, and transitive cascades.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    TEST_USERS,
    fixtures,
    factories,
    make_patient_headers,
    ApiErrorId,
)

ADMIN = TEST_USERS["clinic_admin_headers"]
AUD = TEST_USERS["audiologist_headers"]
CLERK = TEST_USERS["billing_clerk_headers"]


# ==========================================================================
# Severity classification boundary (25 vs 26)
# ==========================================================================

def test_severity_boundary_25_classifies_normal(api):
    """PRD §3.2: "a value of 25 dB or below classifies as NORMAL; from 26 through 40
    inclusive as MILD"
    PRD §3.2: "The candidate flag is set true exactly when the resulting severity is
    anything other than NORMAL."

    Design: Difficulty/boundary_precision_check/severity_normal_mild_boundary_25_vs_26
    """
    fixtures.set_clock(fixtures.CLOCK_BASE)
    patient = fixtures.create_patient(date_of_birth="1970-01-01")
    ev = validate_success(api.create_evaluation(
        factories.create_evaluation_payload(patient["id"], pure_tone_avg_db=25), AUD), 201)
    data = validate_success(api.finalize_evaluation(ev["id"], AUD))
    assert data["severity"] == "NORMAL"
    assert data["candidate"] is False


def test_severity_boundary_26_classifies_mild_candidate(api):
    """PRD §3.2: "from 26 through 40 inclusive as MILD"
    PRD §3.2: "The boundary matters: 25 dB yields NORMAL while 26 dB yields MILD."

    Design: Difficulty/boundary_precision_check/severity_normal_mild_boundary_25_vs_26
    """
    fixtures.set_clock(fixtures.CLOCK_BASE)
    patient = fixtures.create_patient(date_of_birth="1970-01-01")
    ev = validate_success(api.create_evaluation(
        factories.create_evaluation_payload(patient["id"], pure_tone_avg_db=26), AUD), 201)
    data = validate_success(api.finalize_evaluation(ev["id"], AUD))
    assert data["severity"] == "MILD"
    assert data["candidate"] is True


def test_is_pediatric_computed_from_dob_and_clock(api):
    """PRD §3.2: "The is_pediatric flag is set true exactly when the patient's age on
    the evaluation date — derived from the patient's date_of_birth and the current
    clock date — is under 18 years."

    Design: Corner/calculations/is_pediatric_computed_from_dob_and_clock
    """
    fixtures.set_clock(fixtures.CLOCK_BASE)
    patient = fixtures.create_patient(date_of_birth="2015-01-01")
    ev = validate_success(api.create_evaluation(
        factories.create_evaluation_payload(patient["id"], pure_tone_avg_db=45), AUD), 201)
    data = validate_success(api.finalize_evaluation(ev["id"], AUD))
    # age 11 at clock 2026-03-01 -> pediatric; ptag 45 -> MODERATE.
    assert data["is_pediatric"] is True
    assert data["severity"] == "MODERATE"


# ==========================================================================
# Loyalty discount boundary (cycle 6 vs 7)
# ==========================================================================

def _build_subscription_with_due_cycles(api, up_to_index):
    """PURCHASED order + ACTIVE subscription (unit 5000, cadence 30) with cycles
    1..up_to_index scheduled, clock advanced far past all due dates. Returns ordered
    cycle list."""
    ctx = fixtures.setup_subscription(unit_price_cents=5_000, cadence_days=30)
    sub_id = ctx["subscription"]["id"]
    # cycle 1 already exists; schedule the rest.
    cycles = fixtures.schedule_additional_cycles(sub_id, up_to_index - 1)
    fixtures.set_clock("2026-12-01T00:00:00Z")  # well past index*30 days for index<=7
    return ctx, cycles


def test_loyalty_cycle_6_bills_full_price(api):
    """PRD §3.9: "for any cycle whose cycle_index is 6 or less, billed_cents is the
    full unit_price_cents with no discount. The boundary is strict — the sixth cycle
    still bills at full price, and the discount first applies at the seventh cycle."

    Design: Difficulty/boundary_precision_check/loyalty_discount_cycle_6_vs_7_boundary
    """
    ctx, cycles = _build_subscription_with_due_cycles(api, 7)
    cyc6 = cycles[5]
    data = validate_success(api.ship_cycle(cyc6["id"], ADMIN))
    assert data["cycle_index"] == 6
    assert data["billed_cents"] == 5_000


def test_loyalty_cycle_7_bills_discounted_price(api):
    """PRD §3.9: "for any cycle whose cycle_index is greater than 6, billed_cents is
    the base multiplied by 90 percent (a 10 percent loyalty discount), rounded half
    up to whole cents"

    Design: Difficulty/boundary_precision_check/loyalty_discount_cycle_6_vs_7_boundary
    """
    ctx, cycles = _build_subscription_with_due_cycles(api, 7)
    cyc7 = cycles[6]
    data = validate_success(api.ship_cycle(cyc7["id"], ADMIN))
    assert data["cycle_index"] == 7
    assert data["billed_cents"] == 4_500


# ==========================================================================
# Warranty claim non-linear cycle: SUBMITTED -> DENIED -> APPEALED -> APPROVED
# ==========================================================================

def test_warranty_claim_deny_appeal_approve_cycle(api):
    """PRD §3.8: "The owning Patient may appeal a denied claim, moving it DENIED →
    APPEALED. From APPEALED, a BillingClerk may again approve it (APPEALED → APPROVED)"
    PRD §3.8: "For a DEFECT, the patient's deductible is 0 and the clinic absorbs the
    full assessed value as clinic_cost_cents."

    Design: Difficulty/non_linear_state_machine/warranty_claim_deny_appeal_approve_cycle
    """
    ctx, claim = fixtures.setup_submitted_claim(
        claim_type="DEFECT", assessed_value_cents=80_000, ptag=35)
    patient_id = ctx["patient"]["id"]
    validate_success(api.deny_warranty_claim(claim["id"], CLERK))
    validate_success(api.appeal_warranty_claim(claim["id"], make_patient_headers(patient_id)))
    approved = validate_success(api.approve_warranty_claim(claim["id"], CLERK))
    assert approved["status"] == "APPROVED"
    assert approved["deductible_cents"] == 0
    assert approved["clinic_cost_cents"] == 80_000


def test_warranty_claim_deny_appeal_deny_again_cycle(api):
    """PRD §3.8: "From APPEALED, a BillingClerk may again approve it (APPEALED →
    APPROVED) or deny it again (APPEALED → DENIED) — so a claim can cycle DENIED →
    APPEALED → APPROVED or DENIED → APPEALED → DENIED."

    Design: Difficulty/non_linear_state_machine/warranty_claim_deny_appeal_approve_cycle
    """
    ctx, claim = fixtures.setup_submitted_claim(
        claim_type="DEFECT", assessed_value_cents=80_000, ptag=35)
    patient_id = ctx["patient"]["id"]
    validate_success(api.deny_warranty_claim(claim["id"], CLERK))
    validate_success(api.appeal_warranty_claim(claim["id"], make_patient_headers(patient_id)))
    denied = validate_success(api.deny_warranty_claim(claim["id"], CLERK))
    assert denied["status"] == "DENIED"


# ==========================================================================
# Transitive cascades
# ==========================================================================

def test_return_releases_allowance_reactivates_benefit(api):
    """PRD §3.5: "For a return out of PURCHASED, the order's allowance is released:
    the system recomputes the benefit pool's consumed_allowance_cents excluding this
    now-returned order (cascade hop two), and if the pool had been EXHAUSTED and the
    recomputed consumed_allowance_cents is now strictly less than total_allowance_cents,
    the pool is reactivated to ACTIVE (cascade hop three)."

    Design: Difficulty/transitive_cascade/return_releases_allowance_reactivates_benefit_depth3
    """
    ctx = fixtures.setup_order_purchased(
        ptag=35,
        model_overrides={"list_price_cents": 400_000, "min_severity": "MILD",
                         "restock_fee_cents": 20_000, "warranty_months": 24},
        use_benefit=True,
        benefit_overrides={"total_allowance_cents": 400_000, "per_device_cap_cents": 400_000,
                           "coinsurance_pct": 0, "period_end": "2026-12-31"},
        order_overrides={"ear_count": 1},
    )
    ben_id = ctx["benefit"]["id"]
    # Purchase consumed 400000 -> benefit EXHAUSTED.
    benefit_before = validate_success(api.get_allowance_benefit(ben_id, CLERK))
    assert benefit_before["consumed_allowance_cents"] == 400_000
    assert benefit_before["status"] == "EXHAUSTED"
    returned = validate_success(api.return_order(ctx["order"]["id"], CLERK))
    assert returned["status"] == "RETURNED"
    benefit_after = validate_success(api.get_allowance_benefit(ben_id, CLERK))
    assert benefit_after["consumed_allowance_cents"] == 0
    assert benefit_after["status"] == "ACTIVE"


def test_purchase_exhausts_benefit_cascade(api):
    """PRD §3.4: "It then recomputes the pool's consumed_allowance_cents (cascade hop
    two, bumping the pool's version and updated_at), and if the recomputed
    consumed_allowance_cents is greater than or equal to the pool's
    total_allowance_cents, the pool transitions to EXHAUSTED (cascade hop three, a
    further mutation)."

    Design: Difficulty/transitive_cascade/return_releases_allowance_reactivates_benefit_depth3
    """
    ctx = fixtures.setup_order_purchased(
        ptag=35,
        model_overrides={"list_price_cents": 400_000, "min_severity": "MILD",
                         "restock_fee_cents": 20_000, "warranty_months": 24},
        use_benefit=True,
        benefit_overrides={"total_allowance_cents": 400_000, "per_device_cap_cents": 400_000,
                           "coinsurance_pct": 0, "period_end": "2026-12-31"},
        order_overrides={"ear_count": 1},
    )
    benefit = validate_success(api.get_allowance_benefit(ctx["benefit"]["id"], CLERK))
    assert benefit["consumed_allowance_cents"] == 400_000
    assert benefit["status"] == "EXHAUSTED"


def test_ship_cycle_bubbles_subscription_totals(api):
    """PRD §3.9: "Shipping appends a SUPPLY_BILLING ledger entry whose amount_cents
    is the positive billed_cents, then recomputes the subscription's cycles_fulfilled
    and lifetime_billed_cents as a cascade (bumping the subscription's version), and
    increments the cycle's version by 1."

    Design: Difficulty/transitive_cascade/ship_cycle_bubbles_subscription_totals_depth2
    """
    ctx = fixtures.setup_subscription(unit_price_cents=5_000, cadence_days=30)
    sub_id = ctx["subscription"]["id"]
    cyc1 = ctx["cycle1"]
    fixtures.set_clock("2026-04-01T00:00:00Z")  # cycle 1 due 2026-03-31.
    cyc_data = validate_success(api.ship_cycle(cyc1["id"], ADMIN))
    assert cyc_data["status"] == "SHIPPED"
    assert cyc_data["billed_cents"] == 5_000
    sub = validate_success(api.get_subscription(sub_id, CLERK))
    assert sub["cycles_fulfilled"] == 1
    assert sub["lifetime_billed_cents"] == 5_000


def test_ship_two_cycles_accumulates_lifetime_billed(api):
    """PRD §3.9: "a computed lifetime_billed_cents (the sum of billed_cents across its
    shipped cycles)"
    PRD §3.9: "then recomputes the subscription's cycles_fulfilled and
    lifetime_billed_cents as a cascade (bumping the subscription's version)"

    Design: Difficulty/transitive_cascade/ship_cycle_bubbles_subscription_totals_depth2
    """
    ctx = fixtures.setup_subscription(unit_price_cents=5_000, cadence_days=30)
    sub_id = ctx["subscription"]["id"]
    cycles = fixtures.schedule_additional_cycles(sub_id, 1)  # now cycles 1 and 2.
    fixtures.set_clock("2026-06-01T00:00:00Z")  # both due (due at +30, +60 days).
    validate_success(api.ship_cycle(cycles[0]["id"], ADMIN))
    validate_success(api.ship_cycle(cycles[1]["id"], ADMIN))
    sub = validate_success(api.get_subscription(sub_id, CLERK))
    assert sub["cycles_fulfilled"] == 2
    assert sub["lifetime_billed_cents"] == 10_000


# ==========================================================================
# Evaluation supersession
# ==========================================================================

def test_finalize_second_evaluation_supersedes_first(api):
    """PRD §3.2: "When a new evaluation for a given patient reaches FINALIZED, the
    system automatically transitions that patient's previously finalized evaluation,
    if any, from FINALIZED → SUPERSEDED, refreshing its updated_at and incrementing
    its version by 1 as a cascade."

    Design: Corner/state_machines/finalize_second_evaluation_supersedes_first
    """
    fixtures.set_clock(fixtures.CLOCK_BASE)
    patient = fixtures.create_patient(date_of_birth="1960-01-01")
    ev1 = validate_success(api.create_evaluation(
        factories.create_evaluation_payload(patient["id"], pure_tone_avg_db=40), AUD), 201)
    validate_success(api.finalize_evaluation(ev1["id"], AUD))
    ev2 = validate_success(api.create_evaluation(
        factories.create_evaluation_payload(patient["id"], pure_tone_avg_db=60), AUD), 201)
    ev2_final = validate_success(api.finalize_evaluation(ev2["id"], AUD))
    ev1_after = validate_success(api.get_evaluation(ev1["id"], AUD))
    assert ev1_after["status"] == "SUPERSEDED"
    assert ev2_final["status"] == "FINALIZED"
    assert ev2_final["severity"] == "SEVERE"


# ==========================================================================
# Subscription lifecycle + conditional cascade
# ==========================================================================

def test_subscription_pause_resume_cycle(api):
    """PRD §3.9: "An ACTIVE subscription may be paused (ACTIVE → PAUSED) and a PAUSED
    one resumed (PAUSED → ACTIVE), forming the cycle ACTIVE → PAUSED → ACTIVE"

    Design: Corner/state_machines/subscription_pause_resume_cycle_back_to_active
    """
    ctx = fixtures.setup_subscription(by_patient=True)
    sub_id = ctx["subscription"]["id"]
    patient_id = ctx["patient"]["id"]
    ph = make_patient_headers(patient_id)
    paused = validate_success(api.pause_subscription(sub_id, ph))
    assert paused["status"] == "PAUSED"
    resumed = validate_success(api.resume_subscription(sub_id, ph))
    assert resumed["status"] == "ACTIVE"


def test_cancel_subscription_skips_scheduled_cycles(api):
    """PRD §3.9: "Cancellation is terminal and carries a conditional cascade: every
    cycle under the subscription that is still SCHEDULED is rolled to SKIPPED, while
    cycles already shipped or already skipped are left untouched"

    Design: Corner/state_machines/cancel_subscription_skips_scheduled_cycles
    """
    ctx = fixtures.setup_subscription(by_patient=True)
    sub_id = ctx["subscription"]["id"]
    cyc1 = ctx["cycle1"]
    ph = make_patient_headers(ctx["patient"]["id"])
    cancelled = validate_success(api.cancel_subscription(sub_id, ph))
    assert cancelled["status"] == "CANCELLED"
    cyc_after = validate_success(api.get_supply_cycle(cyc1["id"], CLERK))
    assert cyc_after["status"] == "SKIPPED"


# ==========================================================================
# Recall fan-out and remediation flow
# ==========================================================================

def test_recall_issue_close_full_remediation_flow(api):
    """PRD §3.10: "On issue the system scans for fitting orders whose
    device_model_id equals the recall's device_model_id, whose fitted_firmware_version
    equals the recall's affected_firmware_version, and whose status is
    WARRANTY_ACTIVE, and sets affected_order_count to the number of matched orders."
    PRD §3.10: "Closing a recall advances it ISSUED → CLOSED and is permitted only
    from ISSUED (otherwise ERR_INVALID_STATE)."

    Design: Corner/state_machines/recall_issue_close_full_remediation_flow
    """
    ctx = fixtures.setup_order_warranty_active(
        ptag=45, model_overrides={"list_price_cents": 200_000, "min_severity": "MILD",
                                  "restock_fee_cents": 10_000, "firmware_version": "1.0.0",
                                  "warranty_months": 24})
    model_id = ctx["model"]["id"]
    order_id = ctx["order"]["id"]
    recall = validate_success(api.create_recall(
        factories.create_recall_payload(
            model_id, affected_firmware_version="1.0.0",
            target_firmware_version="1.0.1", severity_level="MANDATORY"), ADMIN), 201)
    issued = validate_success(api.issue_recall(recall["id"], recall["version"], ADMIN))
    assert issued["affected_order_count"] == 1
    validate_success(api.create_adjustment(
        order_id, factories.create_adjustment_payload(
            reason="RECALL_REPROGRAM", applied_firmware_version="1.0.1",
            recall_notice_id=recall["id"]), AUD), 201)
    closed = validate_success(api.close_recall(recall["id"], ADMIN))
    assert closed["status"] == "CLOSED"
    assert closed["affected_order_count"] == 1


def test_recall_close_without_remediation_rejected(api):
    """PRD §3.10: "If any affected order under a mandatory recall lacks such a
    session, closure is rejected with ERR_RECALL_NOT_REMEDIATED (HTTP 422)."

    Design: Corner/state_machines/recall_close_without_remediation_rejected
    """
    ctx = fixtures.setup_order_warranty_active(
        ptag=45, model_overrides={"list_price_cents": 200_000, "min_severity": "MILD",
                                  "restock_fee_cents": 10_000, "firmware_version": "1.0.0",
                                  "warranty_months": 24})
    recall = validate_success(api.create_recall(
        factories.create_recall_payload(
            ctx["model"]["id"], affected_firmware_version="1.0.0",
            target_firmware_version="1.0.1", severity_level="MANDATORY"), ADMIN), 201)
    validate_success(api.issue_recall(recall["id"], recall["version"], ADMIN))
    resp = api.close_recall(recall["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_RECALL_NOT_REMEDIATED.value)


# ==========================================================================
# Invalid / terminal transitions
# ==========================================================================

def test_finalize_already_finalized_evaluation_invalid_state(api):
    """PRD §3.2: "Finalization is permitted only when the evaluation is in DRAFT and
    its pure_tone_avg_db has been set; otherwise the transition is rejected as an
    invalid state with ERR_INVALID_STATE (HTTP 409)."

    Design: Corner/state_machines/finalize_already_finalized_evaluation_returns_invalid_state
    """
    fixtures.set_clock(fixtures.CLOCK_BASE)
    patient = fixtures.create_patient(date_of_birth="1960-01-01")
    ev = validate_success(api.create_evaluation(
        factories.create_evaluation_payload(patient["id"], pure_tone_avg_db=45), AUD), 201)
    validate_success(api.finalize_evaluation(ev["id"], AUD))
    resp = api.finalize_evaluation(ev["id"], AUD)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_cancel_purchased_order_invalid_state(api):
    """PRD §3.3: "A DRAFT order that was never trialed may be abandoned: an
    Audiologist may cancel it, moving it DRAFT → CANCELLED (an invalid state for
    cancellation yields ERR_INVALID_STATE)."

    Design: Corner/state_machines/cancel_purchased_order_returns_invalid_state
    """
    ctx = fixtures.setup_order_purchased(
        ptag=45, model_overrides={"list_price_cents": 100_000, "min_severity": "MILD",
                                  "restock_fee_cents": 5_000, "warranty_months": 24})
    resp = api.cancel_order(ctx["order"]["id"], AUD)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_terminal_returned_order_no_further_transition(api):
    """PRD §3.5: "Both branches move the order to RETURNED, a terminal state"
    PRD §3.6: "This is permitted only from PURCHASED (otherwise ERR_INVALID_STATE)"

    Design: Corner/state_machines/terminal_returned_order_no_further_transition
    """
    ctx = fixtures.setup_order_purchased(
        ptag=45, model_overrides={"list_price_cents": 100_000, "min_severity": "MILD",
                                  "restock_fee_cents": 5_000, "warranty_months": 24})
    validate_success(api.return_order(ctx["order"]["id"], CLERK))
    resp = api.activate_warranty(ctx["order"]["id"], CLERK)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_order_initial_state_is_draft(api):
    """PRD §3.3: "A fitting order is the spine of the device-fitting, warranty, and
    supply chain, and it is created by an Audiologist in DRAFT status."
    PRD §3.3: "allowance_applied_cents is 0, and refund_cents is 0."

    Design: Corner/state_machines/order_initial_state_is_draft
    """
    fixtures.set_clock(fixtures.CLOCK_BASE)
    patient = fixtures.create_patient(date_of_birth="1960-01-01")
    model = fixtures.create_device_model(
        list_price_cents=100_000, min_severity="MILD", restock_fee_cents=5_000,
        firmware_version="1.0.0", warranty_months=24)
    evaluation = fixtures.create_finalized_evaluation(patient["id"], pure_tone_avg_db=45)
    order = validate_success(api.create_order(
        factories.create_order_payload(patient["id"], evaluation["id"], model["id"], ear_count=1),
        AUD), 201)
    assert order["status"] == "DRAFT"
    assert order["allowance_applied_cents"] == 0
    assert order["refund_cents"] == 0
