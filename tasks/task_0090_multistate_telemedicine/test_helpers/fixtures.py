"""Composite setup helpers for multi-step test prerequisites.

Most interesting claims require the platform to be in a specific multi-call state
(physician + license + patient + visit, walked through compliance/approval). These
helpers encapsulate those preambles so tests focus on assertions.

All helpers use get_success_data() (lenient 2xx validator) internally so a broken
precondition surfaces as a clear "Setup step failed" message. Identity threading is
mandatory: ownership-gated calls use make_physician_headers / make_patient_headers
with the real entity id (never the shared TEST_USERS fallback).

Standard clock for most fixtures: 2026-04-01T09:00:00.000Z, with all default
licenses spanning [2026-01-01, 2027-01-01) so they are active at that instant.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_physician_payload,
    create_state_license_payload,
    create_patient_payload,
    create_payer_payload,
    create_visit_payload,
    create_prescription_payload,
)
from .test_users import (
    TEST_USERS,
    make_physician_headers,
    make_patient_headers,
)

# Canonical instants reused across fixtures.
DEFAULT_CLOCK = "2026-04-01T09:00:00.000Z"
DEFAULT_LICENSE_EFF = "2026-01-01T00:00:00.000Z"
DEFAULT_LICENSE_EXP = "2027-01-01T00:00:00.000Z"
DEFAULT_VISIT_SCHEDULED = "2026-04-02T10:00:00.000Z"

_BOARD = TEST_USERS["licensing_board_headers"]
_OFFICER = TEST_USERS["compliance_officer_headers"]
_ANON = TEST_USERS["anonymous_headers"]


# ─── Clock ────────────────────────────────────────────

def set_clock(current_utc: str):
    """Set the platform logical clock. Returns ClockState."""
    return get_success_data(api_client.set_clock({"current_utc": current_utc}, _ANON))


# ─── Tier 1: Base entity builders ─────────────────────

def create_physician(**overrides):
    """Register a physician. Returns the Physician."""
    return get_success_data(api_client.create_physician(create_physician_payload(**overrides), _ANON))


def issue_license(physician_id, **overrides):
    """Issue a state license to a physician (LicensingBoard). Returns the StateLicense."""
    return get_success_data(
        api_client.create_state_license(physician_id, create_state_license_payload(**overrides), _BOARD)
    )


def create_patient(**overrides):
    """Register a patient. Returns the Patient."""
    return get_success_data(api_client.create_patient(create_patient_payload(**overrides), _ANON))


def create_payer(**overrides):
    """Register a payer (ComplianceOfficer). Returns the Payer."""
    return get_success_data(api_client.create_payer(create_payer_payload(**overrides), _OFFICER))


def request_visit(physician_id, patient_id, **overrides):
    """A Patient requests a visit (ownership-threaded). Returns the Visit."""
    headers = make_patient_headers(patient_id)
    return get_success_data(
        api_client.create_visit(create_visit_payload(physician_id, patient_id, **overrides), headers)
    )


# ─── Tier 2: Physician + license scaffolding ──────────

def setup_licensed_physician(clock=DEFAULT_CLOCK, controlled=False, dea_number=None,
                             state_code="CA", imlc_eligible=None,
                             eff=DEFAULT_LICENSE_EFF, exp=DEFAULT_LICENSE_EXP):
    """Set clock, register a physician, issue one ACTIVE license in `state_code`.

    Returns (physician, license). `controlled` issues controlled_substance_authority;
    `dea_number` (if given) is set on the physician.
    """
    set_clock(clock)
    phys_overrides = {}
    if dea_number is not None:
        phys_overrides["dea_number"] = dea_number
    if imlc_eligible is not None:
        phys_overrides["imlc_eligible"] = imlc_eligible
    physician = create_physician(**phys_overrides)
    lic_overrides = {"state_code": state_code, "effective_date": eff, "expiration_date": exp}
    if controlled:
        lic_overrides["controlled_substance_authority"] = True
    license_ = issue_license(physician["id"], **lic_overrides)
    return physician, license_


# ─── Tier 3: Visit lifecycle shortcuts ────────────────

def setup_requested_visit(clock=DEFAULT_CLOCK, controlled=False, dea_number=None,
                          patient_overrides=None, visit_overrides=None,
                          state_code="CA", license_state=None,
                          eff=DEFAULT_LICENSE_EFF, exp=DEFAULT_LICENSE_EXP,
                          imlc_eligible=None):
    """Physician (licensed in `license_state`, default == `state_code`) + patient +
    REQUESTED visit. Returns (physician, license, patient, visit)."""
    physician, license_ = setup_licensed_physician(
        clock=clock, controlled=controlled, dea_number=dea_number,
        state_code=(license_state or state_code), imlc_eligible=imlc_eligible,
        eff=eff, exp=exp,
    )
    patient = create_patient(**(patient_overrides or {}))
    v_over = {"determined_state_code": state_code}
    v_over.update(visit_overrides or {})
    visit = request_visit(physician["id"], patient["id"], **v_over)
    return physician, license_, patient, visit


def setup_cleared_visit(clock=DEFAULT_CLOCK, controlled=False, dea_number=None,
                        patient_overrides=None, visit_overrides=None,
                        state_code="CA", eff=DEFAULT_LICENSE_EFF, exp=DEFAULT_LICENSE_EXP):
    """REQUESTED visit walked through run-compliance to COMPLIANCE_CLEARED.
    Returns (physician, license, patient, visit-after-clear)."""
    physician, license_, patient, visit = setup_requested_visit(
        clock=clock, controlled=controlled, dea_number=dea_number,
        patient_overrides=patient_overrides, visit_overrides=visit_overrides,
        state_code=state_code, eff=eff, exp=exp,
    )
    cleared = get_success_data(api_client.run_compliance(visit["id"], make_physician_headers(physician["id"])))
    return physician, license_, patient, cleared


def setup_approved_visit(clock=DEFAULT_CLOCK, insured=False, payer_overrides=None,
                         visit_overrides=None, controlled=False, dea_number=None,
                         state_code="CA"):
    """Cleared visit then approved. When `insured`, a payer is created and the patient
    is enrolled (routes INSURANCE); otherwise routes SELF_PAY.
    Returns dict(physician, license, patient, payer, visit, claim).
    `claim` is the auto-created Claim on the insurance branch (None for self-pay).
    """
    physician, license_ = setup_licensed_physician(
        clock=clock, controlled=controlled, dea_number=dea_number, state_code=state_code
    )
    payer = None
    patient_over = {}
    if insured:
        payer = create_payer(**(payer_overrides or {}))
        patient_over["insurance_payer_id"] = payer["id"]
    patient = create_patient(**patient_over)
    v_over = {"determined_state_code": state_code}
    v_over.update(visit_overrides or {})
    visit = request_visit(physician["id"], patient["id"], **v_over)
    phys_headers = make_physician_headers(physician["id"])
    get_success_data(api_client.run_compliance(visit["id"], phys_headers))
    approved = get_success_data(api_client.approve_visit(visit["id"], phys_headers))
    claim = None
    if insured:
        claims, _ = _list(api_client.list_visit_claims(visit["id"], _OFFICER))
        claim = claims[0] if claims else None
    return {
        "physician": physician, "license": license_, "patient": patient,
        "payer": payer, "visit": approved, "claim": claim,
    }


def complete_visit(visit_id, physician_id):
    """Complete an approved visit. Returns the completed Visit."""
    return get_success_data(api_client.complete_visit(visit_id, make_physician_headers(physician_id)))


# ─── Tier 4: Prescription authoring shortcut ──────────

def author_prescription(visit_id, physician_id, **overrides):
    """Author a prescription on a cleared/approved visit (ownership-threaded).
    Returns the Prescription."""
    headers = make_physician_headers(physician_id)
    return get_success_data(
        api_client.create_prescription(visit_id, create_prescription_payload(**overrides), headers)
    )


def setup_visit_with_active_controlled_rx(clock=DEFAULT_CLOCK, insured=False,
                                          payer_overrides=None, dea_schedule="IV",
                                          drug_name="Lorazepam"):
    """Cleared (and optionally approved-insurance) visit carrying one ACTIVE controlled rx.

    Used by suspension-cascade depth tests. The physician has a dea_number and a CA
    license with controlled authority; the rx is authored while the visit is cleared.
    Returns dict(physician, license, patient, payer, visit, prescription, claim).
    """
    physician, license_ = setup_licensed_physician(
        clock=clock, controlled=True, dea_number="BV1234567", state_code="CA"
    )
    payer = None
    patient_over = {}
    if insured:
        payer = create_payer(**(payer_overrides or {}))
        patient_over["insurance_payer_id"] = payer["id"]
    patient = create_patient(**patient_over)
    visit = request_visit(physician["id"], patient["id"], determined_state_code="CA")
    phys_headers = make_physician_headers(physician["id"])
    get_success_data(api_client.run_compliance(visit["id"], phys_headers))
    rx = get_success_data(api_client.create_prescription(
        visit["id"], create_prescription_payload(
            drug_name=drug_name, dea_schedule=dea_schedule, days_supply=30,
            expected_visit_prescription_version=0,
        ),
        phys_headers,
    ))
    claim = None
    final_visit = get_success_data(api_client.get_visit(visit["id"], phys_headers))
    if insured:
        approved = get_success_data(api_client.approve_visit(visit["id"], phys_headers))
        final_visit = approved
        claims, _ = _list(api_client.list_visit_claims(visit["id"], _OFFICER))
        claim = claims[0] if claims else None
    return {
        "physician": physician, "license": license_, "patient": patient,
        "payer": payer, "visit": final_visit, "prescription": rx, "claim": claim,
    }


# ─── Helpers ──────────────────────────────────────────

def _list(response):
    """Parse a paginated list response into (data, meta) leniently for setup use."""
    body = response.json()
    return body.get("data", []), body.get("meta", {})


def get_visit(visit_id, headers):
    return get_success_data(api_client.get_visit(visit_id, headers))
