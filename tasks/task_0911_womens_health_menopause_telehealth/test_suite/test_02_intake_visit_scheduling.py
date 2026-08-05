"""Intake submission/scoring and visit scheduling.

Difficulty instances: symptom_score_round_per_domain_then_sum,
visit_provider_slot_half_open_adjacency, visit_schedule_temporal_beats_fiscal.
Corner instances: intake_submit_twice, visit_with_draft_intake,
visit_with_foreign_intake, visit_complete_from_cancelled,
visit_completion_creates_visit_charge_computed.
"""
from test_helpers import (
    ApiErrorId,
    validate_success, validate_error, validate_paginated,
    create_visit_payload, create_intake_payload,
    register_patient, register_provider,
    create_submitted_intake, create_draft_intake, create_completed_visit,
    create_subscription,
    make_patient_headers, make_provider_headers, billing_admin_headers,
)


# ---------------------------------------------------------------------------
# Symptom severity score — round-per-domain-then-sum (difficulty)
# ---------------------------------------------------------------------------
def _submitted_scored_intake(api):
    patient = register_patient(api, billing_mode="CASH", menopause_stage="MENOPAUSE")
    ph = make_patient_headers(patient["id"])
    intake = create_draft_intake(
        api, patient["id"],
        symptom_ratings=[{"domain": "VASOMOTOR", "severity": 8},
                         {"domain": "SLEEP", "severity": 5},
                         {"domain": "MOOD", "severity": 7}],
        reported_conditions=["NONE"])
    return validate_success(api.submit_intake(intake["id"], ph))


def test_symptom_score_rounds_each_domain_then_sums(api):
    """PRD §3.2: "For each {domain, severity} entry, the per-domain
    contribution is the severity multiplied by that domain's weight, rounded
    half up to 2 decimal places. The score is the sum of those already-rounded
    per-domain contributions, with that sum itself rounded half up to 2 decimal
    places. The rounding order is pinned: round each per-domain contribution to
    2 decimals first, then sum, then round the total — never sum first and round
    once."
    PRD §3.2: "Each symptom domain carries a weight: VASOMOTOR is 1.0, SLEEP is
    0.833, MOOD is 0.667, GENITOURINARY is 0.75, and COGNITIVE is 0.6."

    Design: Difficulty/combinatorial_formula/symptom_score_round_per_domain_then_sum
    """
    data = _submitted_scored_intake(api)
    # 8*1.0=8.00, 5*0.833=4.165->4.17, 7*0.667=4.669->4.67; sum=16.84
    assert round(data["symptom_severity_score"], 2) == 16.84, \
        f"expected 16.84, got {data['symptom_severity_score']}"
    assert round(data["symptom_severity_score"], 2) != 16.83, \
        "sum-then-round (16.83) must not be used"


def test_symptom_score_clean_intake_transitions_cleared(api):
    """PRD §3.2: "if it contains none of them, the flag is false and the
    assessment transitions DRAFT → CLEARED."

    Design: Difficulty/combinatorial_formula/symptom_score_round_per_domain_then_sum
    """
    data = _submitted_scored_intake(api)
    assert data["status"] == "CLEARED", f"expected CLEARED, got {data['status']}"
    assert data["has_absolute_contraindication"] is False


def test_intake_submit_twice_returns_invalid_state(api):
    """PRD §3.2: "Submitting an intake (a patient action) is permitted only
    while it is DRAFT; a submit from any other state is rejected with
    ERR_INTAKE_INVALID_STATE (409)."

    Design: Corner/state_machines/intake_submit_twice_returns_invalid_state
    """
    patient = register_patient(api)
    ph = make_patient_headers(patient["id"])
    intake = create_submitted_intake(api, patient["id"])
    resp = api.submit_intake(intake["id"], ph)
    validate_error(resp, ApiErrorId.ERR_INTAKE_INVALID_STATE)


# ---------------------------------------------------------------------------
# Visit scheduling — provider slot half-open adjacency (difficulty)
# ---------------------------------------------------------------------------
def _patient_provider_intake(api):
    patient = register_patient(api)
    provider = register_provider(api)
    intake = create_submitted_intake(api, patient["id"])
    return patient, provider, intake


def test_overlapping_provider_slot_rejected(api):
    """PRD §3.3: "First, the new slot must not overlap any other SCHEDULED visit
    for the same provider. Overlap is judged on the half-open interval from
    scheduled_start up to but not including scheduled_end, so two visits that
    merely touch at an endpoint do not conflict; a true overlap is rejected with
    ERR_PROVIDER_SLOT_OVERLAP (409)."

    Design: Difficulty/resource_temporal_overlap/visit_provider_slot_half_open_adjacency
    """
    patient, provider, intake = _patient_provider_intake(api)
    ph = make_patient_headers(patient["id"])
    validate_success(api.create_visit(create_visit_payload(
        patient_id=patient["id"], provider_id=provider["id"],
        intake_assessment_id=intake["id"],
        scheduled_start="2026-05-21T09:00:00Z", scheduled_end="2026-05-21T10:00:00Z"), ph),
        expected_status=201)
    resp = api.create_visit(create_visit_payload(
        patient_id=patient["id"], provider_id=provider["id"],
        intake_assessment_id=intake["id"],
        scheduled_start="2026-05-21T09:30:00Z", scheduled_end="2026-05-21T10:30:00Z"), ph)
    validate_error(resp, ApiErrorId.ERR_PROVIDER_SLOT_OVERLAP)


def test_adjacent_provider_slot_touching_allowed(api):
    """PRD §3.3: "two visits that merely touch at an endpoint do not conflict;
    a true overlap is rejected with ERR_PROVIDER_SLOT_OVERLAP (409). ... A new
    visit is created in SCHEDULED status."

    Design: Difficulty/resource_temporal_overlap/visit_provider_slot_half_open_adjacency
    """
    patient, provider, intake = _patient_provider_intake(api)
    ph = make_patient_headers(patient["id"])
    validate_success(api.create_visit(create_visit_payload(
        patient_id=patient["id"], provider_id=provider["id"],
        intake_assessment_id=intake["id"],
        scheduled_start="2026-05-21T09:00:00Z", scheduled_end="2026-05-21T10:00:00Z"), ph),
        expected_status=201)
    data = validate_success(api.create_visit(create_visit_payload(
        patient_id=patient["id"], provider_id=provider["id"],
        intake_assessment_id=intake["id"],
        scheduled_start="2026-05-21T10:00:00Z", scheduled_end="2026-05-21T11:00:00Z"), ph),
        expected_status=201)
    assert data["status"] == "SCHEDULED", f"adjacent slot must be accepted, got {data['status']}"


def test_visit_with_draft_intake_returns_not_submitted(api):
    """PRD §3.3: "The referenced intake must already be submitted — that is, in
    CLEARED or FLAGGED — otherwise the schedule is rejected with
    ERR_INTAKE_NOT_SUBMITTED (409)."

    Design: Corner/validations/visit_with_draft_intake_returns_not_submitted
    """
    patient = register_patient(api)
    provider = register_provider(api)
    intake = create_draft_intake(api, patient["id"])  # never submitted
    resp = api.create_visit(create_visit_payload(
        patient_id=patient["id"], provider_id=provider["id"],
        intake_assessment_id=intake["id"],
        scheduled_start="2026-05-30T09:00:00Z", scheduled_end="2026-05-30T10:00:00Z"),
        make_patient_headers(patient["id"]))
    validate_error(resp, ApiErrorId.ERR_INTAKE_NOT_SUBMITTED)


def test_visit_with_foreign_intake_returns_patient_mismatch(api):
    """PRD §3.3: "The referenced intake must belong to the same patient, and the
    patient_id in the body must be the acting patient; a mismatch on either body
    foreign key is rejected with ERR_PATIENT_MISMATCH (422)."

    Design: Corner/validations/visit_with_foreign_intake_returns_patient_mismatch
    """
    patient_a = register_patient(api)
    patient_b = register_patient(api)
    provider = register_provider(api)
    intake_a = create_submitted_intake(api, patient_a["id"])
    resp = api.create_visit(create_visit_payload(
        patient_id=patient_b["id"], provider_id=provider["id"],
        intake_assessment_id=intake_a["id"],
        scheduled_start="2026-05-31T09:00:00Z", scheduled_end="2026-05-31T10:00:00Z"),
        make_patient_headers(patient_b["id"]))
    validate_error(resp, ApiErrorId.ERR_PATIENT_MISMATCH)


def test_visit_complete_from_cancelled_returns_invalid_state(api):
    """PRD §3.3: "When a provider completes a visit, the visit transitions
    SCHEDULED → COMPLETED; completion is allowed only from SCHEDULED, otherwise
    ERR_VISIT_INVALID_STATE (409)."

    Design: Corner/state_machines/visit_complete_from_cancelled_returns_invalid_state
    """
    patient, provider, intake = _patient_provider_intake(api)
    ph = make_patient_headers(patient["id"])
    visit = validate_success(api.create_visit(create_visit_payload(
        patient_id=patient["id"], provider_id=provider["id"],
        intake_assessment_id=intake["id"],
        scheduled_start="2026-05-25T09:00:00Z", scheduled_end="2026-05-25T10:00:00Z"), ph),
        expected_status=201)
    validate_success(api.cancel_visit(visit["id"], ph))
    resp = api.complete_visit(visit["id"], make_provider_headers(provider["id"]))
    validate_error(resp, ApiErrorId.ERR_VISIT_INVALID_STATE)


def test_visit_completion_creates_visit_charge(api):
    """PRD §3.3: "the system creates a Charge with billable_kind of VISIT,
    billable_id set to the visit's id, allowed_amount_cents set to the
    provider's visit_fee_cents, and billing_mode snapshotted from the patient's
    billing_mode, all in ESTIMATED status."

    Design: Corner/entities/visit_completion_creates_visit_charge_computed
    """
    patient = register_patient(api, billing_mode="CASH")
    provider = register_provider(api, visit_fee_cents=15000)
    intake = create_submitted_intake(api, patient["id"])
    visit = create_completed_visit(api, patient["id"], provider["id"], intake["id"])
    data, _ = validate_paginated(
        api.list_charges(make_provider_headers(provider["id"]),
                         params={"billable_id": visit["id"]}))
    assert len(data) == 1, f"expected exactly one VISIT charge, got {len(data)}"
    assert data[0]["billable_kind"] == "VISIT"
    assert data[0]["allowed_amount_cents"] == 15000


# ---------------------------------------------------------------------------
# Conflict B — provider overlap beats past-due fiscal check (difficulty)
# ---------------------------------------------------------------------------
def _past_due_patient_with_scheduled_visit(api):
    patient = register_patient(api)
    provider = register_provider(api)
    intake = create_submitted_intake(api, patient["id"])
    ph = make_patient_headers(patient["id"])
    sub = create_subscription(api, patient["id"], patient["version"], plan_tier="PLUS")
    validate_success(api.create_visit(create_visit_payload(
        patient_id=patient["id"], provider_id=provider["id"],
        intake_assessment_id=intake["id"],
        scheduled_start="2026-05-17T09:00:00Z", scheduled_end="2026-05-17T10:00:00Z"), ph),
        expected_status=201)
    validate_success(api.mark_past_due(sub["id"], billing_admin_headers()))
    return patient, provider, intake, ph


def test_visit_overlap_and_past_due_returns_overlap_error(api):
    """PRD §2.10: "Conflict B (visit scheduling). The provider slot-overlap
    check (yielding ERR_PROVIDER_SLOT_OVERLAP, 409) is evaluated before the
    past-due-membership fiscal check (yielding ERR_SUBSCRIPTION_PAST_DUE, 402).
    If a visit would both overlap another slot and be blocked by a past-due
    subscription, the response is ERR_PROVIDER_SLOT_OVERLAP."

    Design: Difficulty/priority_pair_validation_conflict/visit_schedule_temporal_beats_fiscal
    """
    patient, provider, intake, ph = _past_due_patient_with_scheduled_visit(api)
    resp = api.create_visit(create_visit_payload(
        patient_id=patient["id"], provider_id=provider["id"],
        intake_assessment_id=intake["id"],
        scheduled_start="2026-05-17T09:30:00Z", scheduled_end="2026-05-17T10:30:00Z"), ph)
    validate_error(resp, ApiErrorId.ERR_PROVIDER_SLOT_OVERLAP)


def test_visit_overlap_masks_past_due_fiscal_error(api):
    """PRD §2.10: "If a visit would both overlap another slot and be blocked by
    a past-due subscription, the response is ERR_PROVIDER_SLOT_OVERLAP."

    Design: Difficulty/priority_pair_validation_conflict/visit_schedule_temporal_beats_fiscal
    """
    patient, provider, intake, ph = _past_due_patient_with_scheduled_visit(api)
    resp = api.create_visit(create_visit_payload(
        patient_id=patient["id"], provider_id=provider["id"],
        intake_assessment_id=intake["id"],
        scheduled_start="2026-05-17T09:30:00Z", scheduled_end="2026-05-17T10:30:00Z"), ph)
    body = resp.json()["data"]
    assert body["error_id"] != "ERR_SUBSCRIPTION_PAST_DUE", \
        "the lower-priority fiscal error must be masked by the overlap check"
    assert body["error_id"] == "ERR_PROVIDER_SLOT_OVERLAP"
