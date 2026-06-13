"""Composite setup helpers.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints, because the server database is reset before each test. Setup calls
use get_success_data() (lenient) so a setup break surfaces as a clear
"Setup failed" rather than an opaque assertion error.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_pharmacist_headers,
    make_technician_headers,
)
from . import factories as F

ADMIN = TEST_USERS["admin_headers"]
PHARM = TEST_USERS["pharmacist_headers"]
TECH = TEST_USERS["technician_headers"]
CASH = TEST_USERS["cashier_headers"]

EPOCH = "2026-01-01T00:00:00.000Z"


# ---------------------------------------------------------------------------
# Clock control
# ---------------------------------------------------------------------------
def set_clock(current_utc=EPOCH):
    return get_success_data(api_client.set_clock(current_utc, ADMIN))


# ---------------------------------------------------------------------------
# Tier 1: reference-data primitives
# ---------------------------------------------------------------------------
def create_drug(**overrides):
    return get_success_data(
        api_client.create_drug_product(F.create_drug_product_payload(**overrides), ADMIN)
    )


def create_plan(**overrides):
    return get_success_data(
        api_client.create_insurance_plan(F.create_insurance_plan_payload(**overrides), ADMIN)
    )


def create_formulary(plan_id, drug_id, **overrides):
    return get_success_data(
        api_client.create_formulary_entry(
            F.create_formulary_entry_payload(plan_id, drug_id, **overrides), ADMIN
        )
    )


def create_interaction(drug_a_id, drug_b_id, **overrides):
    return get_success_data(
        api_client.create_interaction_rule(
            F.create_interaction_rule_payload(drug_a_id, drug_b_id, **overrides), ADMIN
        )
    )


def create_patient(**overrides):
    return get_success_data(
        api_client.create_patient(F.create_patient_payload(**overrides), TECH)
    )


def create_prescriber(**overrides):
    return get_success_data(
        api_client.create_prescriber(F.create_prescriber_payload(**overrides), ADMIN)
    )


def create_prescription(patient_id, prescriber_id, drug_id, **overrides):
    return get_success_data(
        api_client.create_prescription(
            F.create_prescription_payload(patient_id, prescriber_id, drug_id, **overrides),
            TECH,
        )
    )


def create_fill(prescription_id, headers=TECH, **overrides):
    return get_success_data(
        api_client.create_fill(F.create_fill_payload(prescription_id, **overrides), headers)
    )


def get_rx_version(prescription_id):
    rx = get_success_data(api_client.get_prescription(prescription_id, TECH))
    return rx["version"]


# ---------------------------------------------------------------------------
# Tier 2: a fully-wired insured scenario
# ---------------------------------------------------------------------------
def setup_insured_scenario(plan_overrides=None, drug_overrides=None,
                           patient_overrides=None, prescriber_overrides=None,
                           formulary_overrides=None, set_epoch=True):
    """Active plan + drug on formulary + insured patient + prescriber.

    Returns dict(plan, drug, patient, prescriber).
    """
    if set_epoch:
        set_clock(EPOCH)
    plan = create_plan(**(plan_overrides or {}))
    drug = create_drug(**(drug_overrides or {}))
    create_formulary(plan["id"], drug["id"], **(formulary_overrides or {}))
    patient = create_patient(plan_id=plan["id"], **(patient_overrides or {}))
    prescriber = create_prescriber(**(prescriber_overrides or {}))
    return {"plan": plan, "drug": drug, "patient": patient, "prescriber": prescriber}


# ---------------------------------------------------------------------------
# Tier 3: fill lifecycle shortcuts
# ---------------------------------------------------------------------------
def create_fill_at_entered(prescription_id, headers=TECH):
    """A fresh fill (status ENTERED)."""
    return create_fill(prescription_id, headers=headers)


def advance_to_adjudicating(fill, headers=TECH):
    """Drive a freshly run-dur'd fill to ADJUDICATING.

    Per PRD §3.5 the DUR screen raises a MODERATE *duplicate-therapy* finding for
    any non-first fill of the same drug for the same patient (no carve-out for
    refills of the same prescription), and a MODERATE *high-dose* finding when the
    daily dose exceeds the threshold; either leaves the fill in DUR_REVIEW. To
    reach ADJUDICATING the pharmacist must override those alerts (DUR_REVIEW ->
    ADJUDICATING). override-dur is Pharmacist-only and, for CII drugs, the
    overriding pharmacist must differ from the creating technician — PHARM
    (pharmacist-1) always differs from the creators used here.
    """
    if fill["status"] == "DUR_REVIEW":
        fill = get_success_data(
            api_client.override_dur(fill["id"], F.override_dur_payload(), PHARM)
        )
    return fill


def create_fill_at_adjudicating(prescription_id, headers=TECH):
    """Create a fill, run-dur, and ensure it lands in ADJUDICATING.

    A clean (no-DUR-finding) fill auto-advances ENTERED -> DUR_REVIEW ->
    ADJUDICATING on run-dur. A repeat fill of the same drug for the same patient
    settles in DUR_REVIEW on the PRD-mandated duplicate-therapy MODERATE finding;
    we then override it to ADJUDICATING."""
    fill = create_fill(prescription_id, headers=headers)
    fill = get_success_data(api_client.run_dur(fill["id"], headers))
    return advance_to_adjudicating(fill, headers=headers)


def submit_claim(fill_id, prescription_id, headers=TECH):
    """Submit the claim using the current prescription version."""
    v = get_rx_version(prescription_id)
    return get_success_data(
        api_client.submit_claim(fill_id, F.submit_claim_payload(v), headers)
    )


def create_fill_paid(prescription_id, headers=TECH):
    """Clean fill -> run-dur -> submit-claim PAY. Returns READY_FILL fill (PAID)."""
    fill = create_fill_at_adjudicating(prescription_id, headers=headers)
    return submit_claim(fill["id"], prescription_id, headers=headers)


def create_fill_will_call(prescription_id, headers=TECH):
    """Clean fill all the way to WILL_CALL (PAID)."""
    fill = create_fill_paid(prescription_id, headers=headers)
    return get_success_data(api_client.stage_will_call(fill["id"], headers))


def pay_for_fill(fill_id, amount_cents, headers=CASH):
    return get_success_data(
        api_client.create_payment_record(
            F.create_payment_record_payload(fill_id, amount_cents), headers
        )
    )


def dispense_fill(prescription_id, fill_id, amount_cents,
                  create_headers=TECH, dispense_headers=PHARM):
    """Full lifecycle to DISPENSED: assumes a fill already exists in ENTERED.
    Runs run-dur -> (override if duplicate-therapy/high-dose) -> submit-claim ->
    stage -> pay -> dispense."""
    fill = get_success_data(api_client.run_dur(fill_id, create_headers))
    advance_to_adjudicating(fill, headers=create_headers)
    submit_claim(fill_id, prescription_id, headers=create_headers)
    get_success_data(api_client.stage_will_call(fill_id, create_headers))
    pay_for_fill(fill_id, amount_cents)
    return get_success_data(api_client.dispense(fill_id, dispense_headers))


def create_and_dispense_fill(prescription_id, amount_cents,
                             create_headers=TECH, dispense_headers=PHARM):
    """Create a clean fill then run it to DISPENSED. Returns the dispensed fill."""
    fill = create_fill(prescription_id, headers=create_headers)
    return dispense_fill(
        prescription_id, fill["id"], amount_cents,
        create_headers=create_headers, dispense_headers=dispense_headers,
    )


# ---------------------------------------------------------------------------
# Tier 4: controlled-fill accumulation to drive PDMP posture
# ---------------------------------------------------------------------------
def setup_controlled_patient_with_dispenses(
    n_prescribers=1, n_dispenses=3, clock=EPOCH,
    drug_overrides=None, plan_overrides=None,
    qty=10, days_supply=30, copay_amount=910,
):
    """Register a controlled (CII) drug, a plan with formulary, a patient, and
    `n_prescribers` distinct DEA-active prescribers, then dispense `n_dispenses`
    controlled fills (round-robin across prescribers). Each dispense regenerates
    the PDMP report and may tighten the patient's posture.

    Returns dict(plan, drug, patient, prescribers, dispensed_fills).
    """
    set_clock(clock)
    plan = create_plan(**(plan_overrides or {"bin": "611000", "pcn": "CT", "name": "Ctl Plan",
                                             "copay_pct": 0.10, "copay_max_cents": 10000}))
    drug = create_drug(**(drug_overrides or {"ndc": "00000-9100-01", "name": "Controlled CII",
                                             "dea_schedule": "CII", "unit_price_cents": 1000}))
    create_formulary(plan["id"], drug["id"], tier=3, allowed_amount_cents=900)
    patient = create_patient(plan_id=plan["id"], full_name="Ctl Patient",
                             date_of_birth="1960-01-01")
    prescribers = []
    for i in range(n_prescribers):
        prescribers.append(create_prescriber(
            full_name=f"Dr Ctl {i}", npi=f"90000000{i:02d}",
            dea_number=f"BC{i}111111", dea_active=True,
        ))
    dispensed_fills = []
    for i in range(n_dispenses):
        prescriber = prescribers[i % len(prescribers)]
        rx = create_prescription(
            patient["id"], prescriber["id"], drug["id"],
            quantity_per_fill=qty, days_supply=days_supply, written_utc=clock,
        )
        fill = create_and_dispense_fill(rx["id"], copay_amount)
        dispensed_fills.append(fill)
    return {
        "plan": plan, "drug": drug, "patient": patient,
        "prescribers": prescribers, "dispensed_fills": dispensed_fills,
    }


# ---------------------------------------------------------------------------
# Tier 5: PA referral flow
# ---------------------------------------------------------------------------
def setup_pa_referral(clock=EPOCH, drug_overrides=None, plan_overrides=None,
                      prescriber_overrides=None, qty=30, days_supply=30,
                      refills_authorized=0):
    """Create a pa_required drug scenario, take a clean fill through submit-claim
    so it forks to PA_REFERRAL with a PENDING PriorAuthRequest.

    Returns dict(plan, drug, patient, prescriber, rx, fill, pa).
    """
    set_clock(clock)
    plan = create_plan(**(plan_overrides or {"bin": "612000", "pcn": "PA", "name": "PA Plan",
                                             "copay_pct": 0.10, "copay_max_cents": 10000}))
    drug = create_drug(**(drug_overrides or {"ndc": "00000-9200-01", "name": "PA Drug",
                                             "unit_price_cents": 500, "pa_required": True}))
    create_formulary(plan["id"], drug["id"], tier=4, allowed_amount_cents=400)
    patient = create_patient(plan_id=plan["id"], full_name="PA Patient",
                             date_of_birth="1980-01-01")
    prescriber = create_prescriber(**(prescriber_overrides or
                                      {"full_name": "Dr PA", "npi": "9100000001"}))
    rx = create_prescription(patient["id"], prescriber["id"], drug["id"],
                             quantity_per_fill=qty, days_supply=days_supply,
                             refills_authorized=refills_authorized, written_utc=clock)
    fill = create_fill_at_adjudicating(rx["id"])
    submit_claim(fill["id"], rx["id"])
    pa = get_pa_for_fill(fill["id"])
    return {"plan": plan, "drug": drug, "patient": patient, "prescriber": prescriber,
            "rx": rx, "fill": fill, "pa": pa}


def get_pa_for_fill(fill_id):
    """Return the first PriorAuthRequest for the fill (with its current version)."""
    resp = api_client.list_prior_auth_requests(PHARM, params={"fill_id": fill_id})
    data = get_success_data(resp)
    items = data if isinstance(data, list) else data.get("data", data)
    assert items, f"Setup failed: no PriorAuthRequest for fill {fill_id}"
    return items[0]


def approve_pa(pa_id, expected_version):
    return get_success_data(
        api_client.approve_prior_auth(pa_id, F.approve_pa_payload(expected_version), PHARM)
    )


def deny_pa(pa_id, expected_version):
    return get_success_data(
        api_client.deny_prior_auth(pa_id, F.deny_pa_payload(expected_version), PHARM)
    )


# ---------------------------------------------------------------------------
# Tier 6: DUR-finding fill (stays in DUR_REVIEW)
# ---------------------------------------------------------------------------
def setup_fill_in_dur_review_high_dose(clock=EPOCH, with_plan=True, qty=200, days_supply=30):
    """A fill whose qty/days_supply exceeds 4 units/day -> MODERATE high-dose
    finding -> fill settles in DUR_REVIEW. Returns dict(rx, fill, drug, patient,
    prescriber, plan?)."""
    set_clock(clock)
    plan = None
    plan_id = None
    if with_plan:
        plan = create_plan(bin="613000", pcn="DR", name="DUR Plan",
                           copay_pct=0.10, copay_max_cents=10000)
        plan_id = plan["id"]
    drug = create_drug(ndc="00000-9300-01", name="HighDose Drug", unit_price_cents=100)
    if with_plan:
        create_formulary(plan_id, drug["id"], tier=2, allowed_amount_cents=80)
    patient = create_patient(plan_id=plan_id, full_name="DUR Patient",
                             date_of_birth="1980-01-01")
    prescriber = create_prescriber(full_name="Dr DUR", npi="9200000001")
    rx = create_prescription(patient["id"], prescriber["id"], drug["id"],
                             quantity_per_fill=qty, days_supply=days_supply, written_utc=clock)
    fill = create_fill(rx["id"])
    fill = get_success_data(api_client.run_dur(fill["id"], TECH))
    return {"plan": plan, "drug": drug, "patient": patient, "prescriber": prescriber,
            "rx": rx, "fill": fill}


def setup_fill_in_dur_review_severe_allergy(clock=EPOCH, allergy="PENICILLIN"):
    """A fill whose drug name matches the patient allergy class -> SEVERE allergy
    finding -> DUR_REVIEW. Returns dict(rx, fill, drug, patient, prescriber)."""
    set_clock(clock)
    drug = create_drug(ndc="00000-9400-01", name=allergy, unit_price_cents=100)
    patient = create_patient(full_name="Allergy Patient", date_of_birth="1980-01-01",
                             allergy_classes=[allergy])
    prescriber = create_prescriber(full_name="Dr Allergy", npi="9300000001")
    rx = create_prescription(patient["id"], prescriber["id"], drug["id"],
                             quantity_per_fill=10, days_supply=30, written_utc=clock)
    fill = create_fill(rx["id"])
    fill = get_success_data(api_client.run_dur(fill["id"], TECH))
    return {"drug": drug, "patient": patient, "prescriber": prescriber,
            "rx": rx, "fill": fill}
