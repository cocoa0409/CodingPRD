"""Validation, temporal-window, cross-entity-dependency, and optimistic-concurrency
tests. Includes the validation-priority pairs from the difficulty index, the trial /
warranty / cycle window boundaries, and the two OCC-guarded writes.
"""
from test_helpers import (
    validate_success,
    validate_error,
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
# Validation priority pairs (difficulty Rule 5)
# ==========================================================================

def test_not_candidate_beats_device_not_indicated(api):
    """PRD §3.3: "These three business-safety conditions are evaluated after the
    patient-mismatch check: first the patient match (ERR_EVALUATION_PATIENT_MISMATCH),
    then candidacy (ERR_NOT_A_CANDIDATE), then device indication
    (ERR_DEVICE_NOT_INDICATED)."

    Design: Difficulty/priority_pair_validation_conflict/not_candidate_beats_device_not_indicated_safety_pair
    """
    fixtures.set_clock(fixtures.CLOCK_BASE)
    patient = fixtures.create_patient(date_of_birth="1990-01-01")
    model = fixtures.create_device_model(
        list_price_cents=500_000, min_severity="PROFOUND", restock_fee_cents=25_000,
        firmware_version="1.0.0", warranty_months=24)
    # ptag 20 -> NORMAL (not a candidate). PROFOUND model would also fail indication.
    evaluation = fixtures.create_finalized_evaluation(patient["id"], pure_tone_avg_db=20)
    order = fixtures.create_draft_order(patient["id"], evaluation["id"], model["id"], ear_count=1)
    resp = api.start_trial(order["id"], AUD)
    validate_error(resp, ApiErrorId.ERR_NOT_A_CANDIDATE.value)


def test_trial_expired_beats_benefit_expired(api):
    """PRD §3.4: "Purchase is permitted only from TRIAL (otherwise ERR_INVALID_STATE),
    and only while the trial window is still open: if the current clock instant is
    later than trial_deadline_at, the purchase is rejected with ERR_TRIAL_EXPIRED
    (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/trial_expired_beats_benefit_expired_temporal_pair
    """
    fixtures.set_clock(fixtures.CLOCK_BASE)
    patient = fixtures.create_patient(date_of_birth="1955-02-02")
    model = fixtures.create_device_model(
        list_price_cents=300_000, min_severity="MILD", restock_fee_cents=15_000,
        firmware_version="1.0.0", warranty_months=24)
    # Benefit already expired (period_end before clock).
    benefit = fixtures.create_allowance_benefit(
        patient["id"], total_allowance_cents=500_000, per_device_cap_cents=250_000,
        coinsurance_pct=0.20, period_end="2026-02-28")
    evaluation = fixtures.create_finalized_evaluation(patient["id"], pure_tone_avg_db=50)
    order = fixtures.create_draft_order(
        patient["id"], evaluation["id"], model["id"], ear_count=1,
        allowance_benefit_id=benefit["id"])
    validate_success(api.start_trial(order["id"], AUD))
    fixtures.set_clock("2027-01-01T00:00:00Z")  # past BOTH trial deadline and period_end.
    resp = api.purchase_order(order["id"], CLERK)
    validate_error(resp, ApiErrorId.ERR_TRIAL_EXPIRED.value)


def test_candidacy_check_isolated_normal_evaluation(api):
    """PRD §3.3: "The referenced evaluation must be FINALIZED and its candidate flag
    must be true; a non-candidate evaluation (one classified NORMAL) is rejected with
    ERR_NOT_A_CANDIDATE (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/not_candidate_beats_device_not_indicated_safety_pair
    """
    fixtures.set_clock(fixtures.CLOCK_BASE)
    patient = fixtures.create_patient(date_of_birth="1990-01-01")
    # Indicated model (MILD) so only the candidacy check can fail.
    model = fixtures.create_device_model(
        list_price_cents=200_000, min_severity="MILD", restock_fee_cents=10_000,
        firmware_version="1.0.0", warranty_months=24)
    evaluation = fixtures.create_finalized_evaluation(patient["id"], pure_tone_avg_db=20)
    order = fixtures.create_draft_order(patient["id"], evaluation["id"], model["id"], ear_count=1)
    resp = api.start_trial(order["id"], AUD)
    validate_error(resp, ApiErrorId.ERR_NOT_A_CANDIDATE.value)


def test_trial_expired_isolated(api):
    """PRD §3.4: "if the current clock instant is later than trial_deadline_at, the
    purchase is rejected with ERR_TRIAL_EXPIRED (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/trial_expired_beats_benefit_expired_temporal_pair
    """
    ctx = fixtures.setup_order_in_trial(
        ptag=50, model_overrides={"list_price_cents": 300_000, "min_severity": "MILD",
                                  "restock_fee_cents": 15_000, "warranty_months": 24})
    fixtures.set_clock("2027-01-01T00:00:00Z")  # well past the 30-day deadline.
    resp = api.purchase_order(ctx["order"]["id"], CLERK)
    validate_error(resp, ApiErrorId.ERR_TRIAL_EXPIRED.value)


# ==========================================================================
# Cross-entity state dependencies (difficulty Rule 7)
# ==========================================================================

def test_start_trial_requires_finalized_evaluation(api):
    """PRD §3.3: "The referenced evaluation must be FINALIZED and its candidate flag
    must be true; a non-candidate evaluation (one classified NORMAL) is rejected with
    ERR_NOT_A_CANDIDATE (HTTP 422)."

    The order itself is in DRAFT (a valid source state for start-trial), so the order
    state check passes; the referenced evaluation is still DRAFT (not FINALIZED), so
    the candidacy business check is what fails, yielding ERR_NOT_A_CANDIDATE.

    Design: Difficulty/cross_entity_state_dependency/start_trial_requires_finalized_evaluation
    """
    fixtures.set_clock(fixtures.CLOCK_BASE)
    patient = fixtures.create_patient(date_of_birth="1956-04-04")
    model = fixtures.create_device_model(
        list_price_cents=300_000, min_severity="MILD", restock_fee_cents=15_000,
        firmware_version="1.0.0", warranty_months=24)
    # DRAFT (not finalized) evaluation.
    ev = validate_success(api.create_evaluation(
        factories.create_evaluation_payload(patient["id"], pure_tone_avg_db=50), AUD), 201)
    order = fixtures.create_draft_order(patient["id"], ev["id"], model["id"], ear_count=1)
    resp = api.start_trial(order["id"], AUD)
    validate_error(resp, ApiErrorId.ERR_NOT_A_CANDIDATE.value)


def test_start_trial_blocked_when_evaluation_still_draft_severe(api):
    """PRD §3.3: "The referenced evaluation must be FINALIZED and its candidate flag
    must be true; a non-candidate evaluation (one classified NORMAL) is rejected with
    ERR_NOT_A_CANDIDATE (HTTP 422)."

    The order is in DRAFT (a valid source state for start-trial), so the order state
    check passes; the referenced evaluation is still DRAFT and its candidate flag was
    never computed, so the candidacy business check fails with ERR_NOT_A_CANDIDATE.

    Design: Difficulty/cross_entity_state_dependency/start_trial_requires_finalized_evaluation
    """
    fixtures.set_clock(fixtures.CLOCK_BASE)
    patient = fixtures.create_patient(date_of_birth="1956-04-04")
    model = fixtures.create_device_model(
        list_price_cents=400_000, min_severity="MILD", restock_fee_cents=15_000,
        firmware_version="1.0.0", warranty_months=24)
    # A DRAFT (un-finalized) SEVERE-range evaluation; severity is not even computed yet.
    ev = validate_success(api.create_evaluation(
        factories.create_evaluation_payload(patient["id"], pure_tone_avg_db=65), AUD), 201)
    order = fixtures.create_draft_order(patient["id"], ev["id"], model["id"], ear_count=1)
    resp = api.start_trial(order["id"], AUD)
    validate_error(resp, ApiErrorId.ERR_NOT_A_CANDIDATE.value)


def test_warranty_claim_requires_order_warranty_active(api):
    """PRD §3.8: "A warranty claim is opened against a warranty-active order"
    PRD §2.6: "then, for a transition endpoint, whether the requested transition is
    defined from the target's current state (yielding ERR_INVALID_STATE)"

    Design: Difficulty/cross_entity_state_dependency/warranty_approve_requires_order_warranty_active
    """
    # PURCHASED but trial window not closed, so order is still PURCHASED, not WARRANTY_ACTIVE.
    ctx = fixtures.setup_order_purchased(
        ptag=50, model_overrides={"list_price_cents": 300_000, "min_severity": "MILD",
                                  "restock_fee_cents": 15_000, "warranty_months": 24})
    resp = api.create_warranty_claim(
        ctx["order"]["id"],
        factories.create_warranty_claim_payload(
            claim_type="DEFECT", incident_date="2026-03-02", assessed_value_cents=50_000),
        CLERK)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_approve_on_purchased_order_blocked_after_window_closes_via_state(api):
    """PRD §3.6: "Once the trial window has closed on a purchased order, a BillingClerk
    finalizes the sale by activating warranty coverage, advancing the order
    PURCHASED → WARRANTY_ACTIVE."
    PRD §3.8: "A warranty claim is opened against a warranty-active order"

    Design: Difficulty/cross_entity_state_dependency/warranty_approve_requires_order_warranty_active
    """
    # A claim cannot even be submitted against a still-PURCHASED order; the order must
    # be WARRANTY_ACTIVE. Confirm submission against PURCHASED is rejected as invalid state.
    ctx = fixtures.setup_order_purchased(
        ptag=50, model_overrides={"list_price_cents": 200_000, "min_severity": "MILD",
                                  "restock_fee_cents": 10_000, "warranty_months": 24})
    resp = api.create_warranty_claim(
        ctx["order"]["id"],
        factories.create_warranty_claim_payload(
            claim_type="LOSS", incident_date="2026-03-02", assessed_value_cents=70_000),
        CLERK)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ==========================================================================
# Temporal-interval boundaries (difficulty Rule 8)
# ==========================================================================

def test_purchase_on_trial_deadline_succeeds(api):
    """PRD §3.4: "Purchase is permitted only from TRIAL (otherwise ERR_INVALID_STATE),
    and only while the trial window is still open: if the current clock instant is
    later than trial_deadline_at, the purchase is rejected with ERR_TRIAL_EXPIRED"
    PRD §3.3: "computes trial_deadline_at as trial_started_at plus the trial period —
    a fixed window of 30 days — which is the inclusive cutoff for a no-penalty return
    decision."

    Design: Difficulty/resource_temporal_overlap/trial_window_inclusive_deadline_purchase_on_last_day
    """
    fixtures.set_clock("2026-03-01T00:00:00Z")
    patient = fixtures.create_patient(date_of_birth="1958-06-06")
    model = fixtures.create_device_model(
        list_price_cents=300_000, min_severity="MILD", restock_fee_cents=15_000,
        firmware_version="1.0.0", warranty_months=24)
    evaluation = fixtures.create_finalized_evaluation(patient["id"], pure_tone_avg_db=50)
    order = fixtures.create_draft_order(patient["id"], evaluation["id"], model["id"], ear_count=1)
    validate_success(api.start_trial(order["id"], AUD))
    # deadline = 2026-03-01 + 30 days = 2026-03-31T00:00:00Z. Purchase exactly at deadline.
    fixtures.set_clock("2026-03-31T00:00:00Z")
    data = validate_success(api.purchase_order(order["id"], CLERK))
    assert data["status"] == "PURCHASED"
    assert data["patient_due_cents"] == 300_000


def test_purchase_one_second_past_deadline_rejected(api):
    """PRD §3.4: "if the current clock instant is later than trial_deadline_at, the
    purchase is rejected with ERR_TRIAL_EXPIRED (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/trial_window_inclusive_deadline_purchase_on_last_day
    """
    fixtures.set_clock("2026-03-01T00:00:00Z")
    patient = fixtures.create_patient(date_of_birth="1958-06-06")
    model = fixtures.create_device_model(
        list_price_cents=300_000, min_severity="MILD", restock_fee_cents=15_000,
        firmware_version="1.0.0", warranty_months=24)
    evaluation = fixtures.create_finalized_evaluation(patient["id"], pure_tone_avg_db=50)
    order = fixtures.create_draft_order(patient["id"], evaluation["id"], model["id"], ear_count=1)
    validate_success(api.start_trial(order["id"], AUD))
    fixtures.set_clock("2026-03-31T00:00:01Z")  # one second past the inclusive deadline.
    resp = api.purchase_order(order["id"], CLERK)
    validate_error(resp, ApiErrorId.ERR_TRIAL_EXPIRED.value)


def test_ship_before_due_rejected(api):
    """PRD §3.9: "only once the cycle is due: if the current clock instant is earlier
    than the cycle's due_at, the ship is rejected with ERR_CYCLE_NOT_DUE (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/supply_cycle_due_at_lower_bound_ship_before_due_rejected
    """
    ctx = fixtures.setup_subscription(unit_price_cents=5_000, cadence_days=30)
    cyc1 = ctx["cycle1"]
    # due_at = started_at(2026-03-01) + 30 days = 2026-03-31. Clock just before.
    fixtures.set_clock("2026-03-30T23:59:59Z")
    resp = api.ship_cycle(cyc1["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_CYCLE_NOT_DUE.value)


def test_ship_exactly_at_due_succeeds(api):
    """PRD §3.9: "only once the cycle is due: if the current clock instant is earlier
    than the cycle's due_at, the ship is rejected with ERR_CYCLE_NOT_DUE (HTTP 422)."
    PRD §3.9: "for any cycle whose cycle_index is 6 or less, billed_cents is the full
    unit_price_cents with no discount."

    Design: Difficulty/resource_temporal_overlap/supply_cycle_due_at_lower_bound_ship_before_due_rejected
    """
    ctx = fixtures.setup_subscription(unit_price_cents=5_000, cadence_days=30)
    cyc1 = ctx["cycle1"]
    fixtures.set_clock("2026-03-31T00:00:00Z")  # exactly due_at -> now >= due_at.
    data = validate_success(api.ship_cycle(cyc1["id"], ADMIN))
    assert data["status"] == "SHIPPED"
    assert data["billed_cents"] == 5_000


# ==========================================================================
# Optimistic concurrency control (the two guarded writes)
# ==========================================================================

def test_replace_with_stale_claim_version_rejected(api):
    """PRD §2.8: "Fulfilling an approved warranty claim with a replacement requires the
    request body to carry expected_warranty_claim_version, a non-optional field that
    must equal the target claim's current version. If a writer has advanced the
    claim's version since the client last read it ... the replacement is rejected with
    ERR_STALE_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_replace_stale_claim_version_rejected
    """
    ctx, claim = fixtures.setup_approved_claim(
        claim_type="DEFECT", assessed_value_cents=50_000)
    current_version = claim["version"]
    resp = api.replace_warranty_claim(claim["id"], current_version - 1, CLERK)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def test_replace_with_correct_version_succeeds(api):
    """PRD §3.8: "This write is guarded by optimistic concurrency: the request must
    carry expected_warranty_claim_version equal to the claim's current version"
    PRD §3.8: "On replacement the system appends a WARRANTY_DEDUCTIBLE ledger entry
    whose amount_cents is the positive deductible_cents."

    Design: Corner/cross_cutting_complexity_layers/occ_replace_claim_correct_version_succeeds
    """
    ctx, claim = fixtures.setup_approved_claim(
        claim_type="DEFECT", assessed_value_cents=50_000)
    data = validate_success(api.replace_warranty_claim(claim["id"], claim["version"], CLERK))
    assert data["status"] == "REPLACED"
    assert data["deductible_cents"] == 0


def test_issue_recall_with_stale_version_rejected(api):
    """PRD §2.8: "issuing a recall notice requires the request body to carry
    expected_recall_notice_version, a non-optional field that must equal the target
    recall's current version; if the recall's version has advanced since the client
    last observed it ... the issue is rejected with ERR_STALE_VERSION (HTTP 412)"

    Design: Corner/cross_cutting_complexity_layers/occ_issue_stale_recall_version_rejected
    """
    fixtures.set_clock(fixtures.CLOCK_BASE)
    model = fixtures.create_device_model(
        list_price_cents=200_000, min_severity="MILD", restock_fee_cents=10_000,
        firmware_version="1.0.0", warranty_months=24)
    recall = validate_success(api.create_recall(
        factories.create_recall_payload(
            model["id"], affected_firmware_version="1.0.0",
            target_firmware_version="1.0.1", severity_level="ADVISORY"), ADMIN), 201)
    resp = api.issue_recall(recall["id"], recall["version"] - 1, ADMIN)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def test_loss_replacement_refreshes_fitted_firmware(api):
    """PRD §3.8: "When the claim_type is LOSS, the replacement ships with current
    firmware, so the order's fitted_firmware_version is refreshed to the device
    model's current firmware_version; for DEFECT and DAMAGE claims the fitted firmware
    is left unchanged."

    Design: Corner/cross_cutting_complexity_layers/loss_replacement_refreshes_fitted_firmware
    """
    ctx = fixtures.setup_order_warranty_active(
        ptag=50,
        model_overrides={"list_price_cents": 200_000, "min_severity": "MILD",
                         "restock_fee_cents": 10_000, "firmware_version": "1.0.0",
                         "warranty_months": 24},
        patch_firmware="5.0.0",
    )
    order_id = ctx["order"]["id"]
    claim = validate_success(api.create_warranty_claim(
        order_id, factories.create_warranty_claim_payload(
            claim_type="LOSS", incident_date="2026-04-10", assessed_value_cents=100_000), CLERK), 201)
    approved = validate_success(api.approve_warranty_claim(claim["id"], CLERK))
    validate_success(api.replace_warranty_claim(claim["id"], approved["version"], CLERK))
    order_after = validate_success(api.get_order(order_id, CLERK))
    assert order_after["fitted_firmware_version"] == "5.0.0"
    # LOSS 100000*0.50 = 50000 capped at 40000.
    assert approved["deductible_cents"] == 40_000


def test_version_increments_on_each_mutation(api):
    """PRD §2.4: "The version field is an integer that starts at 1 and increments by
    exactly 1 on every mutation; it is the basis for optimistic concurrency control."
    PRD §3.3: "Starting the trial increments the order's version by 1."

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_each_mutation
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
    assert order["version"] == 1
    started = validate_success(api.start_trial(order["id"], AUD))
    assert started["version"] == 2


def test_allowance_consumed_visible_immediately(api):
    """PRD §3.1: "The pool also exposes a computed consumed_allowance_cents, which the
    system maintains as the sum of allowance_applied_cents across this patient's orders
    whose status is PURCHASED or WARRANTY_ACTIVE; it is recomputed on every order
    purchase, every return, and every warranty replacement."

    Design: Corner/consistency_model/allowance_consumed_visible_same_request_immediate
    """
    ctx = fixtures.setup_order_purchased(
        ptag=60,
        model_overrides={"list_price_cents": 300_000, "min_severity": "MODERATE",
                         "restock_fee_cents": 20_000, "warranty_months": 24},
        use_benefit=True,
        benefit_overrides={"total_allowance_cents": 500_000, "per_device_cap_cents": 250_000,
                           "coinsurance_pct": 0.20, "period_end": "2026-12-31"},
        order_overrides={"ear_count": 2},
    )
    benefit = validate_success(api.get_allowance_benefit(ctx["benefit"]["id"], CLERK))
    assert benefit["consumed_allowance_cents"] == 250_000
    assert benefit["status"] == "ACTIVE"
