"""Settlement cascade, the ESTIMATE-vs-FINAL divergence, staleness propagation,
and the settle-then-void accumulator compensation.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, fixtures, TEST_USERS,
)

PROVIDER = TEST_USERS["provider_staff_headers"]
PAYER = TEST_USERS["payer_analyst_headers"]


# ==========================================================================
# Helpers
# ==========================================================================
def _dv_estimate_ready_to_settle(api):
    """Insured estimate issued at fresh accumulators (ESTIMATE PR 122500),
    accepted, then the patient's accumulators moved to dm=100000/om=300000, with
    an appointment scheduled but not yet completed."""
    fixtures.set_clock(api)
    plan = fixtures.new_benefit_plan(api)
    patient = fixtures.new_patient(api, plan["id"])
    contract = fixtures.new_active_contract(api)
    procedure = fixtures.new_procedure(api, gross_charge_cents=300000)
    fixtures.ingest_flat_rate(api, contract["id"], procedure["id"], 200000)
    estimate = fixtures.new_estimate(api, patient["id"], estimate_type="GFE_INSURED",
                                     contract_id=contract["id"])
    fixtures.add_line(api, estimate["id"], procedure["id"])
    issued = fixtures.issue(api, estimate["id"])
    fixtures.accept(api, estimate["id"], patient["id"])
    fixtures.adjust_accumulators(api, patient["id"], 100000, 300000)
    provider = fixtures.new_provider(api)
    room = fixtures.new_room(api)
    appt = fixtures.schedule_appointment(
        api, patient["id"], estimate["id"], provider["id"], room["id"],
        "2026-06-02T10:00:00Z", "2026-06-02T11:00:00Z")
    return {"patient": patient, "estimate_id": estimate["id"],
            "issued": issued, "appt_id": appt["id"]}


def _settlement_chain(api):
    """Patient with E1 (accepted, appointment scheduled) and E2 (issued sibling)."""
    fixtures.set_clock(api)
    plan = fixtures.new_benefit_plan(api)
    patient = fixtures.new_patient(api, plan["id"])
    contract = fixtures.new_active_contract(api)
    procedure = fixtures.new_procedure(api, gross_charge_cents=300000)
    fixtures.ingest_flat_rate(api, contract["id"], procedure["id"], 200000)
    e1 = fixtures.new_estimate(api, patient["id"], estimate_type="GFE_INSURED",
                               contract_id=contract["id"])
    e2 = fixtures.new_estimate(api, patient["id"], estimate_type="GFE_INSURED",
                               contract_id=contract["id"])
    fixtures.add_line(api, e2["id"], procedure["id"])
    fixtures.issue(api, e2["id"])
    fixtures.add_line(api, e1["id"], procedure["id"])
    fixtures.issue(api, e1["id"])
    fixtures.accept(api, e1["id"], patient["id"])
    provider = fixtures.new_provider(api)
    room = fixtures.new_room(api)
    appt = fixtures.schedule_appointment(
        api, patient["id"], e1["id"], provider["id"], room["id"],
        "2026-06-02T10:00:00Z", "2026-06-02T11:00:00Z")
    return {"patient": patient, "e1": e1["id"], "e2": e2["id"], "appt_id": appt["id"]}


# ==========================================================================
# Difficulty — ESTIMATE vs FINAL variant divergence
# ==========================================================================
def test_estimate_variant_at_issue(api):
    """PRD §3.4: "This roll-up runs in two variants that differ only in which
    clock supplies the patient's accumulators: the ESTIMATE variant at issue uses
    the accumulators as of issue time." PRD §3.4: "A successful issue ... sets
    responsibility_basis to ESTIMATE."

    Design: Difficulty/dual_variant_calc/dv_estimate_vs_final_patient_responsibility
    """
    s = _dv_estimate_ready_to_settle(api)
    assert s["issued"]["patient_responsibility_cents"] == 122500
    assert s["issued"]["responsibility_basis"] == "ESTIMATE"


def test_final_variant_at_settlement(api):
    """PRD §3.7: "the deductible-and-coinsurance aggregation and the
    patient-responsibility roll-up of Section 3.4 are re-run in the FINAL variant
    against the patient's accumulators as of settlement ... setting
    responsibility_basis to FINAL." PRD §3.4: "the FINAL figure can differ from
    the ESTIMATE figure even for identical allowed amounts."

    Design: Difficulty/dual_variant_calc/dv_estimate_vs_final_patient_responsibility
    """
    s = _dv_estimate_ready_to_settle(api)
    fixtures.complete_appointment(api, s["appt_id"])
    settled = validate_success(api.get_estimate(s["estimate_id"], PROVIDER), 200)
    assert settled["status"] == "SETTLED"
    assert settled["responsibility_basis"] == "FINAL"
    assert settled["patient_responsibility_cents"] == 42500
    assert settled["plan_paid_cents"] == 157500


# ==========================================================================
# Difficulty — depth-3 settlement cascade
# ==========================================================================
def test_settlement_settles_estimate_and_accumulates(api):
    """PRD §3.7: "the patient's accumulators advance: `deductible_met_cents`
    grows by this estimate's settled `deductible_applied_cents`, `oop_met_cents`
    grows by its settled `patient_responsibility_cents`, and the patient's
    `version` increments by 1."

    Design: Difficulty/transitive_cascade/tc_settlement_chain_depth3
    """
    s = _settlement_chain(api)
    completed = fixtures.complete_appointment(api, s["appt_id"])
    assert completed["status"] == "COMPLETED"
    e1 = validate_success(api.get_estimate(s["e1"], PROVIDER), 200)
    assert e1["status"] == "SETTLED"
    patient = validate_success(api.get_patient(s["patient"]["id"], PROVIDER), 200)
    assert patient["oop_met_cents"] == 122500
    assert patient["deductible_met_cents"] == 100000


def test_settlement_flags_sibling_recompute(api):
    """PRD §3.7: "every other non-`VOID` estimate of the same patient has its
    `recompute_required` set to true, per Section 2.8."

    Design: Difficulty/transitive_cascade/tc_settlement_chain_depth3
    """
    s = _settlement_chain(api)
    fixtures.complete_appointment(api, s["appt_id"])
    e2 = validate_success(api.get_estimate(s["e2"], PROVIDER), 200)
    assert e2["recompute_required"] is True


# ==========================================================================
# Difficulty — depth-2 accumulation staleness
# ==========================================================================
def test_accumulation_advances_accumulators(api):
    """PRD §3.3: "The adjustment adds `deductible_delta_cents` to the patient's
    `deductible_met_cents` and `oop_delta_cents` to the patient's `oop_met_cents`,
    increments the patient's `version` by 1."

    Design: Difficulty/transitive_cascade/tc_accumulation_staleness_depth2
    """
    b = fixtures.setup_insured_issued_single_line(api, set_clock_first=True)
    patient = fixtures.adjust_accumulators(api, b["patient"]["id"], 50000, 50000)
    assert patient["deductible_met_cents"] == 50000
    assert patient["oop_met_cents"] == 50000


def test_accumulation_flags_estimate_recompute(api):
    """PRD §2.8: "Whenever the accumulators move, every estimate belonging to that
    patient that is not in a terminal state ... has its recompute_required flag
    set to true."

    Design: Difficulty/transitive_cascade/tc_accumulation_staleness_depth2
    """
    b = fixtures.setup_insured_issued_single_line(api, set_clock_first=True)
    fixtures.adjust_accumulators(api, b["patient"]["id"], 50000, 50000)
    estimate = validate_success(api.get_estimate(b["estimate"]["id"], PROVIDER), 200)
    assert estimate["recompute_required"] is True


# ==========================================================================
# Corner — completing an already-completed appointment
# ==========================================================================
def test_complete_already_completed_rejected(api):
    """PRD §3.7: "Or ProviderStaff may complete it, moving it from `SCHEDULED` to
    `COMPLETED`, which fires the settlement cascade." Completion is only legal
    from SCHEDULED, so a re-complete hits the own-state precondition
    ERR_INVALID_STATE (PRD §2.7) and does not re-accumulate.

    Design: Corner/state_machines/complete_already_completed_appointment_idempotency
    """
    s = fixtures.setup_settled_estimate(api)
    resp = api.complete_appointment(s["appointment"]["id"], PROVIDER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
    patient = validate_success(api.get_patient(s["patient"]["id"], PROVIDER), 200)
    assert patient["oop_met_cents"] == 122500


# ==========================================================================
# Difficulty — settle then void reverses the accumulation
# ==========================================================================
def test_settlement_applies_accumulation(api):
    """PRD §3.7: "`oop_met_cents` grows by its settled
    `patient_responsibility_cents`, and the patient's `version` increments by 1."

    Design: Difficulty/compensating_invariant/ci_oop_accumulation_settle_then_void
    """
    s = fixtures.setup_settled_estimate(api)
    assert s["patient"]["oop_met_cents"] == 122500
    assert s["patient"]["deductible_met_cents"] == 100000


def test_void_settled_reverses_accumulation(api):
    """PRD §3.8: "Voiding an estimate that had already settled must undo exactly
    the benefit accumulation that settlement applied: the patient's
    deductible_met_cents is reduced by that estimate's deductible_applied_cents,
    the patient's oop_met_cents is reduced by that estimate's
    patient_responsibility_cents."

    Design: Difficulty/compensating_invariant/ci_oop_accumulation_settle_then_void
    """
    s = fixtures.setup_settled_estimate(api)
    voided = validate_success(api.void_estimate(s["estimate"]["id"], PROVIDER), 200)
    assert voided["status"] == "VOID"
    patient = validate_success(api.get_patient(s["patient"]["id"], PROVIDER), 200)
    assert patient["oop_met_cents"] == 0
    assert patient["deductible_met_cents"] == 0
