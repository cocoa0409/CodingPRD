"""Validation-priority conflicts and RBAC / segregation-of-duties.

Translations of queue A priority_pair_validation_conflict and queue B `rbac`
instances.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    make_technician_headers, make_pharmacist_headers,
    submit_claim_payload, create_prescription_payload,
)
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client

ADMIN = TEST_USERS["admin_headers"]
TECH = TEST_USERS["technician_headers"]
PHARM = TEST_USERS["pharmacist_headers"]
CASH = TEST_USERS["cashier_headers"]


# ---------------------------------------------------------------------------
# Queue A — priority pair: controlled-locked (safety, P11) beats too-soon (temporal, P12)
# ---------------------------------------------------------------------------
def test_refill_too_soon_temporal_beats_controlled_locked_safety(api):
    """PRD §3.6: "For a controlled drug, the patient's `controlled_status` must be
    `ELIGIBLE`, otherwise `ERR_PATIENT_CONTROLLED_LOCKED` (HTTP 403). The
    refill-too-soon edit (§3.8) is then applied."

    Design: Difficulty/priority_pair_validation_conflict/refill_too_soon_temporal_beats_controlled_locked_safety
    """
    fx.set_clock("2026-03-01T00:00:00.000Z")
    plan = fx.create_plan(bin="610009", pcn="PI", name="Plan I", copay_pct=0.10,
                          copay_max_cents=10000, refill_too_soon_threshold_pct=0.80)
    drug = fx.create_drug(ndc="00000-0009-01", name="Hotel CII",
                          dea_schedule="CII", unit_price_cents=1000)
    fx.create_formulary(plan["id"], drug["id"], tier=3, allowed_amount_cents=900)
    patient = fx.create_patient(plan_id=plan["id"], full_name="Pat Nine",
                                date_of_birth="1955-10-10")
    prescribers = [
        fx.create_prescriber(full_name=f"Dr I{i}", npi=f"10000000{90+i}",
                             dea_number=f"BI{i}111111", dea_active=True)
        for i in (1, 2, 3)
    ]
    # Two dispenses from distinct prescribers on single-fill prescriptions.
    for pr in prescribers[:2]:
        rx = fx.create_prescription(patient["id"], pr["id"], drug["id"],
                                    quantity_per_fill=10, days_supply=30,
                                    written_utc="2026-03-01T00:00:00.000Z")
        fx.create_and_dispense_fill(rx["id"], 910)
    # Third prescription authorizes a refill; original dispense at day 0 both
    # arms LOCKED (3rd dispense -> risk 60) and sets last_dispensed_utc.
    rx3 = fx.create_prescription(patient["id"], prescribers[2]["id"], drug["id"],
                                 quantity_per_fill=10, days_supply=30,
                                 refills_authorized=1, written_utc="2026-03-01T00:00:00.000Z")
    fx.create_and_dispense_fill(rx3["id"], 910)
    patient_now = validate_success(api.get_patient(patient["id"], PHARM))
    assert patient_now["controlled_status"] == "LOCKED", "precondition: LOCKED"
    # Refill of rx3 immediately (same day) -> both too-soon AND locked.
    refill = fx.create_fill_at_adjudicating(rx3["id"])
    v = fx.get_rx_version(rx3["id"])
    resp = api.submit_claim(refill["id"], submit_claim_payload(v), TECH)
    # Safety (controlled-locked) is checked before the refill-too-soon edit.
    validate_error(resp, ApiErrorId.ERR_PATIENT_CONTROLLED_LOCKED.value)


def test_controlled_locked_safety_status_403_when_both_too_soon_and_locked(api):
    """PRD §3.6: "For a controlled drug, the patient's `controlled_status` must be
    `ELIGIBLE`, otherwise `ERR_PATIENT_CONTROLLED_LOCKED` (HTTP 403). The
    refill-too-soon edit (§3.8) is then applied."

    Design: Difficulty/priority_pair_validation_conflict/refill_too_soon_temporal_beats_controlled_locked_safety
    """
    # Reproduce the same dual-violation conflict and assert the HTTP status is the
    # safety code (403), confirming the safety check pre-empts the temporal one
    # (which would yield 409).
    fx.set_clock("2026-03-01T00:00:00.000Z")
    plan = fx.create_plan(bin="611009", pcn="PI2", name="Plan I2", copay_pct=0.10,
                          copay_max_cents=10000, refill_too_soon_threshold_pct=0.80)
    drug = fx.create_drug(ndc="00000-1009-01", name="Hotel2 CII",
                          dea_schedule="CII", unit_price_cents=1000)
    fx.create_formulary(plan["id"], drug["id"], tier=3, allowed_amount_cents=900)
    patient = fx.create_patient(plan_id=plan["id"], full_name="Pat Nine2",
                                date_of_birth="1955-10-10")
    prescribers = [
        fx.create_prescriber(full_name=f"Dr I2-{i}", npi=f"10000010{90+i}",
                             dea_number=f"BJ{i}111111", dea_active=True)
        for i in (1, 2, 3)
    ]
    # Two dispenses from distinct prescribers (single-fill prescriptions).
    for pr in prescribers[:2]:
        rx = fx.create_prescription(patient["id"], pr["id"], drug["id"],
                                    quantity_per_fill=10, days_supply=30,
                                    written_utc="2026-03-01T00:00:00.000Z")
        fx.create_and_dispense_fill(rx["id"], 910)
    # Third prescription authorizes a refill; the original dispense both arms the
    # 3rd-dispense LOCK and sets last_dispensed_utc so the same-day refill is too-soon.
    rx3 = fx.create_prescription(patient["id"], prescribers[2]["id"], drug["id"],
                                 quantity_per_fill=10, days_supply=30,
                                 refills_authorized=1, written_utc="2026-03-01T00:00:00.000Z")
    fx.create_and_dispense_fill(rx3["id"], 910)
    assert validate_success(api.get_patient(patient["id"], PHARM))["controlled_status"] == "LOCKED"
    # Same-day refill of rx3 -> both too-soon (0 elapsed < 24 required) AND locked.
    refill = fx.create_fill_at_adjudicating(rx3["id"])
    v = fx.get_rx_version(rx3["id"])
    resp = api.submit_claim(refill["id"], submit_claim_payload(v), TECH)
    err = validate_error(resp, ApiErrorId.ERR_PATIENT_CONTROLLED_LOCKED.value)
    assert err["error_id"] == "ERR_PATIENT_CONTROLLED_LOCKED"


# ---------------------------------------------------------------------------
# Queue A — priority pair: auth (P2) beats state (P6) on dispense
# ---------------------------------------------------------------------------
def test_auth_permission_beats_state_invalid_on_dispense(api):
    """PRD §2.8: "The order is: ... (2) role authorization for the operation
    (`ERR_INSUFFICIENT_PERMISSIONS`); ... (6) the target resource being in a
    valid from-state for the requested transition".

    Design: Difficulty/priority_pair_validation_conflict/auth_permission_beats_state_invalid_on_dispense
    """
    fx.set_clock()
    plan = fx.create_plan(bin="610010", pcn="PJ", name="Plan J",
                          copay_pct=0.10, copay_max_cents=10000)
    drug = fx.create_drug(ndc="00000-0010-01", name="India", unit_price_cents=500)
    patient = fx.create_patient(plan_id=plan["id"], full_name="Pat Ten",
                                date_of_birth="1988-11-11")
    prescriber = fx.create_prescriber(full_name="Dr J", npi="1000000010")
    rx = fx.create_prescription(patient["id"], prescriber["id"], drug["id"],
                                quantity_per_fill=30, days_supply=30)
    fill = fx.create_fill(rx["id"])  # ENTERED (wrong state for dispense)
    # Technician (dispense is Pharmacist-exclusive) -> auth check wins over state.
    resp = api.dispense(fill["id"], TECH)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)


def test_auth_check_precedes_state_check_status_403(api):
    """PRD §2.8: "The order is: ... (2) role authorization for the operation
    (`ERR_INSUFFICIENT_PERMISSIONS`); ... (6) the target resource being in a
    valid from-state for the requested transition (the generic
    `ERR_INVALID_STATE`, or the more specific state error the transition
    nominates)".

    Design: Difficulty/priority_pair_validation_conflict/auth_permission_beats_state_invalid_on_dispense
    """
    # A Cashier (also unauthorized to dispense) calling dispense on an ENTERED
    # (wrong-state) fill must get the auth error with HTTP 403, not the 409 state
    # error — auth is strictly higher priority.
    fx.set_clock()
    drug = fx.create_drug(ndc="00000-1010-01", name="India2", unit_price_cents=500)
    patient = fx.create_patient(full_name="Pat Ten2", date_of_birth="1988-11-11")
    prescriber = fx.create_prescriber(full_name="Dr J2", npi="1000001010")
    rx = fx.create_prescription(patient["id"], prescriber["id"], drug["id"],
                                quantity_per_fill=30, days_supply=30)
    fill = fx.create_fill(rx["id"])  # ENTERED
    resp = api.dispense(fill["id"], CASH)
    err = validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)
    assert err["error_id"] == "ERR_INSUFFICIENT_PERMISSIONS"


# ---------------------------------------------------------------------------
# Queue B — RBAC role denials
# ---------------------------------------------------------------------------
def test_technician_cannot_override_dur(api):
    """PRD §4 (endpoint table): "POST `/fills/{id}/override-dur` ... Pharmacist".
    PRD §2.1: "When an authenticated actor attempts an operation their role is not
    permitted to perform, the request is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

    Design: Corner/rbac/technician_cannot_override_dur
    """
    s = fx.setup_fill_in_dur_review_high_dose(qty=200, days_supply=30, with_plan=False)
    fill = s["fill"]
    assert fill["status"] == "DUR_REVIEW"
    resp = api.override_dur(fill["id"], {"override_reason": "tech tries"}, TECH)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)


def test_cashier_cannot_create_prescription(api):
    """PRD §4 (endpoint table): "POST `/prescriptions` ... PharmacyAdmin,
    Technician".
    PRD §2.1: "When an authenticated actor attempts an operation their role is not
    permitted to perform, the request is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

    Design: Corner/rbac/cashier_cannot_create_prescription
    """
    fx.set_clock()
    drug = fx.create_drug(ndc="77777-0029-01", name="CashRbacDrug", unit_price_cents=100)
    patient = fx.create_patient(full_name="CashRbac P", date_of_birth="1980-01-01")
    prescriber = fx.create_prescriber(full_name="Dr CashRbac", npi="2000000037")
    resp = api.create_prescription(
        create_prescription_payload(patient["id"], prescriber["id"], drug["id"],
                                    quantity_per_fill=10, days_supply=30),
        CASH,
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)


def test_segregation_of_duties_on_cii_dispense(api):
    """PRD §3.9: "As with override, when the drug is Schedule `CII` the dispensing
    pharmacist's `X-User-ID` must differ from the technician who created the fill,
    otherwise `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/segregation_of_duties_covered_by_design
    """
    fx.set_clock()
    plan = fx.create_plan(bin="700016", pcn="CP", name="Sod Plan",
                          copay_pct=0.10, copay_max_cents=10000)
    drug = fx.create_drug(ndc="77777-0030-01", name="SodCII",
                          dea_schedule="CII", unit_price_cents=1000)
    fx.create_formulary(plan["id"], drug["id"], tier=3, allowed_amount_cents=900)
    patient = fx.create_patient(plan_id=plan["id"], full_name="Sod P",
                                date_of_birth="1980-01-01")
    prescriber = fx.create_prescriber(full_name="Dr Sod", npi="2000000038",
                                      dea_number="BS1234567", dea_active=True)
    rx = fx.create_prescription(patient["id"], prescriber["id"], drug["id"],
                                quantity_per_fill=10, days_supply=30)
    same_tech = make_technician_headers("same-id")
    other_tech = make_technician_headers("other-id")
    # Fill created by "same-id" acting as Technician.
    fill = fx.create_fill(rx["id"], headers=same_tech)
    validate_success(api.run_dur(fill["id"], other_tech))
    v = fx.get_rx_version(rx["id"])
    validate_success(api.submit_claim(fill["id"], submit_claim_payload(v), other_tech))
    validate_success(api.stage_will_call(fill["id"], other_tech))
    fx.pay_for_fill(fill["id"], 910)
    # "same-id" now acts as Pharmacist to dispense -> separation-of-duties violation.
    resp = api.dispense(fill["id"], make_pharmacist_headers("same-id"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
