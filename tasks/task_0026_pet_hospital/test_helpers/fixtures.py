"""Composite setup helpers for multi-step preconditions.

Walking the PRD's lifecycle from REGISTERED to CLOSED with every cascade
in flight is too expensive to repeat in every test. This module captures
the common multi-call sequences once.

Identity threading (PRD §2.1): X-User-ID is opaque per PRD for ownership
purposes (§2.1) — but several flows compare X-User-ID byte-for-byte to
fields recorded earlier from a prior X-User-ID:

- Visit.assigned_vet_id (set by triage routing) is checked against
  X-User-ID for DraftingVet actions on the visit (§3.4, §3.5, §3.6).
- Prescription.drafting_vet_id (set at draft from the drafter's
  X-User-ID) is checked against X-User-ID at submit and at redraft
  (§3.7), and is checked NOT-EQUAL to X-User-ID at approve when any item
  is a controlled-drug item (§3.7 segregation of duties).

These fixtures use stable operator ids so that tests can rely on the
same drafting vet handling consult and prescription submission. When a
test needs to break the equality (e.g., to trigger ERR_SEGREGATION_OF_DUTIES
or to test the assigned_vet_id mismatch path), it provides override
operator ids explicitly.

Setup calls use get_success_data (lenient) so failed pre-conditions
surface as 'Setup failed' messages rather than confusing assertion
mismatches in the assert phase.
"""
from __future__ import annotations
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import ADMISSION_HOLD_CENTS
from .factories import (
    advance_clock_payload,
    amend_treatment_record_payload,
    care_log_payload,
    collect_sample_payload,
    create_bill_payload,
    create_cage_payload,
    create_drug_payload,
    create_hospitalization_payload,
    create_lab_report_payload,
    create_owner_payload,
    create_pet_payload,
    create_prescription_payload,
    create_treatment_record_payload,
    create_vaccine_schedule_payload,
    create_visit_payload,
    deposit_payload,
    external_lab_result_payload,
    make_prescription_item,
    payment_payload,
    record_vaccination_payload,
    refund_request_payload,
    refund_confirm_payload,
    reject_prescription_payload,
    send_to_lab_payload,
    unique_drug_code,
    unique_event_id,
    unique_external_lab_ref,
    unique_vaccine_code,
    verify_contact_payload,
)
from .test_users import (
    TEST_USERS,
    make_drafting_vet_headers,
    make_reviewing_vet_headers,
    make_triage_nurse_headers,
)


# ===========================================================================
# Default operator ids — kept stable so DraftingVet can act on the visit
# they were routed to during triage.
# ===========================================================================
DEFAULT_DRAFTING_VET_ID = "drafting-vet-001"
DEFAULT_REVIEWING_VET_ID = "reviewing-vet-001"
DEFAULT_DRAFTING_VET_HEADERS = make_drafting_vet_headers(DEFAULT_DRAFTING_VET_ID)
DEFAULT_REVIEWING_VET_HEADERS = make_reviewing_vet_headers(DEFAULT_REVIEWING_VET_ID)


# ===========================================================================
# Time helpers (PRD §2 — ISO 8601 UTC, three fractional digits)
# ===========================================================================
def iso_z(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    millis = int(dt.microsecond / 1000)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{millis:03d}Z"


def parse_iso(s: str) -> datetime:
    s2 = s.replace("Z", "+00:00")
    return datetime.fromisoformat(s2)


def now_iso() -> str:
    return iso_z(datetime.now(timezone.utc))


def add_minutes(s: str, n: int) -> str:
    return iso_z(parse_iso(s) + timedelta(minutes=n))


def add_hours(s: str, n: int) -> str:
    return iso_z(parse_iso(s) + timedelta(hours=n))


def add_days(s: str, n: int) -> str:
    return iso_z(parse_iso(s) + timedelta(days=n))


def advance_clock_seconds(seconds: int) -> Dict[str, Any]:
    """POST /_clock/advance with PlatformAdmin headers (PRD §3.10 — admin-only)."""
    res = api_client.advance_clock(
        advance_clock_payload(seconds=seconds),
        TEST_USERS["platform_admin_headers"],
    )
    return get_success_data(res)


# ===========================================================================
# Tier 1: Owner + Pet (verified, with deposit)
# ===========================================================================
def create_owner(*, with_verification: bool = True,
                 with_deposit_cents: int = 200_000,
                 **overrides: Any) -> Dict[str, Any]:
    """Create owner. Default: verified + deposit_balance=200000 cents (>= admission hold)."""
    res = api_client.create_owner(
        create_owner_payload(**overrides),
        TEST_USERS["owner_service_headers"],
    )
    owner = get_success_data(res)
    if with_verification:
        verify_owner_contact(owner["id"])
        # Re-fetch to get the up-to-date contact_verified flag.
        owner = get_owner(owner["id"])
    if with_deposit_cents > 0:
        top_up_deposit(owner["id"], with_deposit_cents)
        owner = get_owner(owner["id"])
    return owner


def get_owner(owner_id: str) -> Dict[str, Any]:
    res = api_client.get_owner(owner_id, TEST_USERS["owner_service_headers"])
    return get_success_data(res)


def verify_owner_contact(owner_id: str) -> Dict[str, Any]:
    """Issue + verify in one shot. The implementation is required by PRD §3.1
    to accept the cleartext code through the verify-contact action; tests
    that need to drive the failure path do so directly.
    """
    issue_res = api_client.issue_verification(
        owner_id, TEST_USERS["owner_service_headers"]
    )
    issue_data = get_success_data(issue_res)
    # The PRD does not specify an exact code shape returned to the
    # client. Implementations that surface it as `verification_code`,
    # `code`, or in response payload meta are all PRD-faithful; tests
    # that need a deterministic verified flag should use this helper,
    # which falls back to a default code for stub implementations and to
    # the issued code when the implementation echoes one back.
    code = (
        issue_data.get("verification_code")
        or issue_data.get("code")
        or issue_data.get("verification_code_hash")
        or "VERIFIED"
    )
    res = api_client.verify_contact(
        owner_id, verify_contact_payload(code=code),
        TEST_USERS["owner_service_headers"],
    )
    return get_success_data(res)


def top_up_deposit(owner_id: str, amount_cents: int) -> Dict[str, Any]:
    res = api_client.deposit(
        owner_id, deposit_payload(amount_cents=amount_cents),
        TEST_USERS["cashier_headers"],
    )
    return get_success_data(res)


def create_pet(
    *,
    owner_id: str,
    species: str = "DOG",
    birth_date: str = "2024-01-01",
    weight_kg: float = 10.0,
    name: str = "Buddy",
    **overrides: Any,
) -> Dict[str, Any]:
    res = api_client.create_pet(
        create_pet_payload(
            owner_id=owner_id, species=species,
            birth_date=birth_date, weight_kg=weight_kg, name=name,
            **overrides,
        ),
        TEST_USERS["owner_service_headers"],
    )
    return get_success_data(res)


def get_pet(pet_id: str) -> Dict[str, Any]:
    res = api_client.get_pet(pet_id, TEST_USERS["owner_service_headers"])
    return get_success_data(res)


def setup_owner_and_pet(
    *,
    species: str = "DOG",
    birth_date: str = "2024-01-01",
    weight_kg: float = 10.0,
    deposit_cents: int = 200_000,
    verified: bool = True,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    owner = create_owner(with_verification=verified, with_deposit_cents=deposit_cents)
    pet = create_pet(
        owner_id=owner["id"], species=species,
        birth_date=birth_date, weight_kg=weight_kg,
    )
    return owner, pet


# ===========================================================================
# Tier 1: Visit lifecycle helpers
# ===========================================================================
def create_visit(
    *,
    pet_id: str,
    severity_score: int = 5,
    symptom_text: str = "vomiting and lethargy",
    **overrides: Any,
) -> Dict[str, Any]:
    res = api_client.create_visit(
        pet_id,
        create_visit_payload(
            severity_score=severity_score, symptom_text=symptom_text, **overrides,
        ),
        TEST_USERS["triage_nurse_headers"],
    )
    return get_success_data(res)


def get_visit(visit_id: str) -> Dict[str, Any]:
    res = api_client.get_visit(visit_id, TEST_USERS["triage_nurse_headers"])
    return get_success_data(res)


def triage(visit_id: str) -> Dict[str, Any]:
    res = api_client.triage_visit(visit_id, TEST_USERS["triage_nurse_headers"])
    return get_success_data(res)


def start_consult(visit_id: str,
                  vet_headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """PRD §3.4: caller's X-User-ID must equal Visit.assigned_vet_id.

    Tests typically pass the X-User-ID recorded as assigned_vet_id from
    triage. By default we fetch the visit and use that exact id, so the
    fixture cannot accidentally drop the equality check.
    """
    if vet_headers is None:
        v = get_visit(visit_id)
        vet_id = v.get("assigned_vet_id") or DEFAULT_DRAFTING_VET_ID
        vet_headers = make_drafting_vet_headers(vet_id)
    res = api_client.start_consult(visit_id, vet_headers)
    return get_success_data(res)


def end_consult(visit_id: str,
                vet_headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    if vet_headers is None:
        v = get_visit(visit_id)
        vet_id = v.get("assigned_vet_id") or DEFAULT_DRAFTING_VET_ID
        vet_headers = make_drafting_vet_headers(vet_id)
    res = api_client.end_consult(visit_id, vet_headers)
    return get_success_data(res)


def vet_headers_for_visit(visit_id: str) -> Dict[str, str]:
    """Return DraftingVet headers whose X-User-ID equals Visit.assigned_vet_id.

    PRD §3.4 / §3.5 / §3.6 require this equality for several actions on
    the visit. Falling back to a static operator id would silently break
    those checks even when the implementation is correct, so this helper
    threads the actual id through.
    """
    v = get_visit(visit_id)
    vet_id = v.get("assigned_vet_id") or DEFAULT_DRAFTING_VET_ID
    return make_drafting_vet_headers(vet_id)


def setup_visit_in_consult(
    *,
    severity_score: int = 5,
    species: str = "DOG",
    birth_date: str = "2024-01-01",
    weight_kg: float = 10.0,
    symptom_text: str = "vomiting and lethargy",
    deposit_cents: int = 200_000,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """REGISTERED → TRIAGED → IN_CONSULT.

    Returns (owner, pet, visit). The drafting vet acting on this visit
    must use vet_headers_for_visit(visit['id']) to satisfy the
    Visit.assigned_vet_id == X-User-ID rule.
    """
    owner, pet = setup_owner_and_pet(
        species=species, birth_date=birth_date,
        weight_kg=weight_kg, deposit_cents=deposit_cents,
    )
    visit = create_visit(
        pet_id=pet["id"], severity_score=severity_score, symptom_text=symptom_text,
    )
    visit = triage(visit["id"])
    visit = start_consult(visit["id"])
    return owner, pet, visit


# ===========================================================================
# Tier 2: TreatmentRecord helpers
# ===========================================================================
def create_treatment_record(
    *,
    visit_id: str,
    consent_recorded: bool = True,
    diagnosis_code: str = "K30",
    consultation_notes: str = "Standard exam.",
    treatment_plan: str = "Rest and hydration; recheck in one week.",
) -> Dict[str, Any]:
    headers = vet_headers_for_visit(visit_id)
    res = api_client.create_treatment_record(
        create_treatment_record_payload(
            visit_id=visit_id,
            consent_recorded=consent_recorded,
            diagnosis_code=diagnosis_code,
            consultation_notes=consultation_notes,
            treatment_plan=treatment_plan,
        ),
        headers,
    )
    return get_success_data(res)


def finalize_treatment_record(*, visit_id: str, tr_id: str) -> Dict[str, Any]:
    headers = vet_headers_for_visit(visit_id)
    res = api_client.finalize_treatment_record(tr_id, headers)
    return get_success_data(res)


def setup_visit_with_finalized_treatment(
    *, severity_score: int = 5,
    deposit_cents: int = 200_000,
    diagnosis_code: str = "K30",
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Returns (owner, pet, visit, finalized_tr)."""
    owner, pet, visit = setup_visit_in_consult(
        severity_score=severity_score, deposit_cents=deposit_cents,
    )
    tr = create_treatment_record(
        visit_id=visit["id"], diagnosis_code=diagnosis_code,
    )
    tr = finalize_treatment_record(visit_id=visit["id"], tr_id=tr["id"])
    return owner, pet, visit, tr


def setup_visit_consult_done(
    *, severity_score: int = 5,
    deposit_cents: int = 200_000,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """REGISTERED → ... → CONSULT_DONE with one finalized TreatmentRecord.
    Returns (owner, pet, visit, finalized_tr).
    """
    owner, pet, visit, tr = setup_visit_with_finalized_treatment(
        severity_score=severity_score, deposit_cents=deposit_cents,
    )
    visit = end_consult(visit["id"])
    return owner, pet, visit, tr


# ===========================================================================
# Tier 2: Lab Reports
# ===========================================================================
def create_lab_report(
    *,
    visit_id: str,
    test_items: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    headers = vet_headers_for_visit(visit_id)
    res = api_client.create_lab_report(
        create_lab_report_payload(visit_id=visit_id, test_items=test_items),
        headers,
    )
    return get_success_data(res)


def collect_sample(*, lr_id: str, when_iso: Optional[str] = None) -> Dict[str, Any]:
    res = api_client.collect_sample(
        lr_id,
        collect_sample_payload(sample_collected_at=when_iso or now_iso()),
        TEST_USERS["triage_nurse_headers"],
    )
    return get_success_data(res)


def send_to_lab(*, lr_id: str,
                external_lab_ref: Optional[str] = None) -> Tuple[Dict[str, Any], str]:
    ref = external_lab_ref or unique_external_lab_ref()
    res = api_client.send_to_lab(
        lr_id, send_to_lab_payload(external_lab_ref=ref),
        TEST_USERS["triage_nurse_headers"],
    )
    return get_success_data(res), ref


def post_lab_result(
    *,
    external_lab_ref: str,
    results: List[Dict[str, Any]],
    event_id: Optional[str] = None,
) -> Dict[str, Any]:
    res = api_client.external_lab_result(
        external_lab_result_payload(
            external_lab_ref=external_lab_ref,
            results=results,
            event_id=event_id,
        ),
        TEST_USERS["platform_admin_headers"],
    )
    return get_success_data(res)


def finalize_lab_report(*, visit_id: str, lr_id: str) -> Dict[str, Any]:
    headers = vet_headers_for_visit(visit_id)
    res = api_client.finalize_lab_report(lr_id, headers)
    return get_success_data(res)


def lab_report_through_result_received(
    *,
    visit_id: str,
    test_items: List[Dict[str, Any]],
    results: List[Dict[str, Any]],
    external_lab_ref: Optional[str] = None,
) -> Tuple[Dict[str, Any], str]:
    """Create lab report → collect → send → post external result.

    Returns (lab_report_after_result, external_lab_ref).
    """
    lr = create_lab_report(visit_id=visit_id, test_items=test_items)
    collect_sample(lr_id=lr["id"])
    _, ref = send_to_lab(lr_id=lr["id"], external_lab_ref=external_lab_ref)
    lr = post_lab_result(external_lab_ref=ref, results=results)
    return lr, ref


# ===========================================================================
# Tier 2: Drugs
# ===========================================================================
def create_drug(
    *,
    code: Optional[str] = None,
    name: str = "Test Drug",
    controlled: bool = False,
    dosage_min_mg_per_kg: float = 1.0,
    dosage_max_mg_per_kg: float = 10.0,
    interactions: Optional[List[Dict[str, Any]]] = None,
    stock_units: int = 1000,
) -> Dict[str, Any]:
    res = api_client.create_drug(
        create_drug_payload(
            code=code, name=name, controlled=controlled,
            dosage_min_mg_per_kg=dosage_min_mg_per_kg,
            dosage_max_mg_per_kg=dosage_max_mg_per_kg,
            interactions=interactions, stock_units=stock_units,
        ),
        TEST_USERS["platform_admin_headers"],
    )
    return get_success_data(res)


# ===========================================================================
# Tier 3: Prescription full lifecycle helpers
# ===========================================================================
def create_prescription(
    *,
    visit_id: str,
    items: List[Dict[str, Any]],
    drafting_vet_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Draft a prescription. PRD §3.7: drafting_vet_id is taken from the
    caller's X-User-ID, so we honor an override here so tests can recover
    the value for later submit / segregation-of-duties checks.

    The caller's X-User-ID must also equal Visit.assigned_vet_id (§3.4
    rules apply transitively to DraftingVet actions on the visit).
    """
    if drafting_vet_id is None:
        # Use the visit's assigned_vet_id so the "DraftingVet on the visit"
        # equality holds; this is also the value recorded as drafting_vet_id.
        v = get_visit(visit_id)
        drafting_vet_id = v.get("assigned_vet_id") or DEFAULT_DRAFTING_VET_ID
    headers = make_drafting_vet_headers(drafting_vet_id)
    res = api_client.create_prescription(
        create_prescription_payload(visit_id=visit_id, items=items),
        headers,
    )
    return get_success_data(res)


def submit_prescription(
    *,
    rx_id: str,
    drafting_vet_id: str,
) -> Dict[str, Any]:
    """PRD §3.7: caller's X-User-ID must equal Prescription.drafting_vet_id."""
    headers = make_drafting_vet_headers(drafting_vet_id)
    res = api_client.submit_prescription(rx_id, headers)
    return get_success_data(res)


def approve_prescription(
    *,
    rx_id: str,
    reviewing_vet_id: str = DEFAULT_REVIEWING_VET_ID,
    override_acknowledged: Optional[bool] = None,
) -> Dict[str, Any]:
    headers = make_reviewing_vet_headers(reviewing_vet_id)
    payload: Dict[str, Any] = {}
    if override_acknowledged is not None:
        payload["override_acknowledged"] = override_acknowledged
    res = api_client.approve_prescription(rx_id, headers, payload)
    return get_success_data(res)


def reject_prescription(
    *,
    rx_id: str,
    reviewing_vet_id: str = DEFAULT_REVIEWING_VET_ID,
    rejection_reason: str = "Insufficient data; please redraft.",
) -> Dict[str, Any]:
    headers = make_reviewing_vet_headers(reviewing_vet_id)
    res = api_client.reject_prescription(
        rx_id, reject_prescription_payload(rejection_reason=rejection_reason),
        headers,
    )
    return get_success_data(res)


def redraft_prescription(*, rx_id: str, drafting_vet_id: str) -> Dict[str, Any]:
    headers = make_drafting_vet_headers(drafting_vet_id)
    res = api_client.redraft_prescription(rx_id, headers)
    return get_success_data(res)


def dispense_prescription(*, rx_id: str) -> Dict[str, Any]:
    res = api_client.dispense_prescription(rx_id, TEST_USERS["pharmacist_headers"])
    return get_success_data(res)


def setup_approved_prescription(
    *,
    visit_id: str,
    drug_code: str,
    dose_mg_per_kg: float = 5.0,
    frequency_per_day: int = 2,
    duration_days: int = 5,
    pet_weight_kg: float = 10.0,
    units: Optional[int] = None,
    drafting_vet_id: Optional[str] = None,
    reviewing_vet_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Draft → Submit → Approve. Returns the APPROVED Prescription.

    PRD §3.7 dosage-rationality: units == ceil(dose_mg_per_kg * weight_kg
    * frequency_per_day * duration_days). When units is omitted we
    compute the rational value, so the helper never violates the rule
    by accident.
    """
    import math
    if units is None:
        units = math.ceil(
            dose_mg_per_kg * pet_weight_kg * frequency_per_day * duration_days
        )
    if drafting_vet_id is None:
        v = get_visit(visit_id)
        drafting_vet_id = v.get("assigned_vet_id") or DEFAULT_DRAFTING_VET_ID
    if reviewing_vet_id is None:
        # Pick a value distinct from drafting_vet_id to keep
        # segregation-of-duties checks safe by default.
        reviewing_vet_id = (
            DEFAULT_REVIEWING_VET_ID
            if drafting_vet_id != DEFAULT_REVIEWING_VET_ID
            else "reviewing-vet-002"
        )
    item = make_prescription_item(
        drug_code=drug_code,
        dose_mg_per_kg=dose_mg_per_kg,
        frequency_per_day=frequency_per_day,
        duration_days=duration_days,
        units=units,
    )
    rx = create_prescription(
        visit_id=visit_id, items=[item], drafting_vet_id=drafting_vet_id,
    )
    rx = submit_prescription(rx_id=rx["id"], drafting_vet_id=drafting_vet_id)
    rx = approve_prescription(rx_id=rx["id"], reviewing_vet_id=reviewing_vet_id)
    return rx


# ===========================================================================
# Tier 2: Cages and Hospitalizations
# ===========================================================================
def create_cage(
    *,
    capacity: int = 2,
    ward_code: str = "GENERAL",
    cage_code: Optional[str] = None,
) -> Dict[str, Any]:
    res = api_client.create_cage(
        create_cage_payload(
            capacity=capacity, ward_code=ward_code, cage_code=cage_code,
        ),
        TEST_USERS["platform_admin_headers"],
    )
    return get_success_data(res)


def admit_hospitalization(
    *,
    visit_id: str,
    cage_id: str,
) -> Dict[str, Any]:
    headers = vet_headers_for_visit(visit_id)
    res = api_client.create_hospitalization(
        create_hospitalization_payload(visit_id=visit_id, cage_id=cage_id),
        headers,
    )
    return get_success_data(res)


def begin_care(*, visit_id: str, h_id: str) -> Dict[str, Any]:
    headers = vet_headers_for_visit(visit_id)
    res = api_client.begin_care(h_id, headers)
    return get_success_data(res)


def append_care(*, visit_id: str, h_id: str, treatment_executed: bool = False,
                note: str = "Vitals normal") -> Dict[str, Any]:
    headers = vet_headers_for_visit(visit_id)
    res = api_client.append_care_log(
        h_id, care_log_payload(note=note, treatment_executed=treatment_executed),
        headers,
    )
    return get_success_data(res)


def request_discharge(*, visit_id: str, h_id: str) -> Dict[str, Any]:
    headers = vet_headers_for_visit(visit_id)
    res = api_client.request_discharge(h_id, headers)
    return get_success_data(res)


def discharge_hospitalization(*, h_id: str) -> Dict[str, Any]:
    res = api_client.discharge_hospitalization(h_id, TEST_USERS["cashier_headers"])
    return get_success_data(res)


def cancel_hospitalization(*, visit_id: str, h_id: str) -> Dict[str, Any]:
    headers = vet_headers_for_visit(visit_id)
    res = api_client.cancel_hospitalization(h_id, headers)
    return get_success_data(res)


# ===========================================================================
# Tier 2: Bills
# ===========================================================================
def create_bill(
    *,
    visit_id: str,
    package_code: Optional[str] = None,
    insurance_estimate_cents: int = 0,
) -> Dict[str, Any]:
    res = api_client.create_bill(
        create_bill_payload(
            visit_id=visit_id, package_code=package_code,
            insurance_estimate_cents=insurance_estimate_cents,
        ),
        TEST_USERS["cashier_headers"],
    )
    return get_success_data(res)


def recompute_bill(*, bill_id: str) -> Dict[str, Any]:
    res = api_client.recompute_bill(bill_id, TEST_USERS["cashier_headers"])
    return get_success_data(res)


def issue_bill(*, bill_id: str) -> Dict[str, Any]:
    res = api_client.issue_bill(bill_id, TEST_USERS["cashier_headers"])
    return get_success_data(res)


def pay_bill(*, bill_id: str, amount_cents: int,
             event_id: Optional[str] = None) -> Dict[str, Any]:
    res = api_client.post_payment(
        payment_payload(
            bill_id=bill_id, amount_cents=amount_cents, event_id=event_id,
        ),
        TEST_USERS["platform_admin_headers"],
    )
    return get_success_data(res)


def issue_invoice(*, bill_id: str) -> Dict[str, Any]:
    res = api_client.issue_invoice(bill_id, TEST_USERS["cashier_headers"])
    return get_success_data(res)


def request_refund(*, bill_id: str, amount_cents: int,
                   reason: str = "goodwill") -> Dict[str, Any]:
    res = api_client.refund_bill(
        bill_id, refund_request_payload(
            amount_cents=amount_cents, reason=reason,
        ),
        TEST_USERS["cashier_headers"],
    )
    return get_success_data(res)


def confirm_refund(*, bill_id: str, amount_cents: int,
                   event_id: Optional[str] = None) -> Dict[str, Any]:
    res = api_client.confirm_refund(
        refund_confirm_payload(
            bill_id=bill_id, amount_cents=amount_cents, event_id=event_id,
        ),
        TEST_USERS["platform_admin_headers"],
    )
    return get_success_data(res)


# ===========================================================================
# Tier 4: Threshold-targeting fixtures (difficulty-design instances)
# ===========================================================================
def setup_visit_with_consult_line(
    *,
    severity_score: int = 5,
    deposit_cents: int = 200_000,
    package_code: Optional[str] = None,
    insurance_estimate_cents: int = 0,
    diagnosis_code: str = "K30",
) -> Dict[str, Any]:
    """One finalized TreatmentRecord exists → Bill has one CONSULT line.

    Returns dict with owner, pet, visit, treatment_record, bill.
    """
    owner, pet, visit, tr = setup_visit_with_finalized_treatment(
        severity_score=severity_score, deposit_cents=deposit_cents,
        diagnosis_code=diagnosis_code,
    )
    bill = create_bill(
        visit_id=visit["id"], package_code=package_code,
        insurance_estimate_cents=insurance_estimate_cents,
    )
    bill = recompute_bill(bill_id=bill["id"])
    return {
        "owner": owner,
        "pet": pet,
        "visit": visit,
        "treatment_record": tr,
        "bill": bill,
    }


def setup_dental_pkg_at_50000_gross(deposit_cents: int = 0) -> Dict[str, Any]:
    """Dental package at the 500.00 boundary (15% tier) — supports the
    'circular tier keyed on gross_pre_discount' difficulty instance.

    line_total_cents = 50000 (qty=1 * unit_price_cents=50000).
    PRD §3.9 forbids re-keying tier on gross_after_discount; with
    deposit=0 and insurance=0, provisional_total_cents = 42500.
    """
    raise NotImplementedError(
        "This fixture is documented inline in the test that needs it because "
        "PRD does not expose a way to set a CONSULT line's unit_price_cents "
        "directly — see test_19_difficulty_design for the bound."
    )


# ===========================================================================
# Tier 4: Vaccine schedule + Pet helpers (vaccine difficulty instances)
# ===========================================================================
def create_vaccine_schedule(
    *,
    species: str = "DOG",
    vaccine_code: Optional[str] = None,
    age_min_days: int = 84,
    booster_interval_days: Optional[int] = 365,
    required: bool = False,
) -> Dict[str, Any]:
    res = api_client.create_vaccine_schedule(
        create_vaccine_schedule_payload(
            species=species, vaccine_code=vaccine_code,
            age_min_days=age_min_days,
            booster_interval_days=booster_interval_days,
            required=required,
        ),
        TEST_USERS["platform_admin_headers"],
    )
    return get_success_data(res)


def record_vaccination(
    *,
    pet_id: str,
    vaccine_code: str,
    administered_at: str,
    batch_id: Optional[str] = None,
) -> Dict[str, Any]:
    res = api_client.record_vaccination(
        pet_id,
        record_vaccination_payload(
            vaccine_code=vaccine_code,
            administered_at=administered_at,
            batch_id=batch_id,
        ),
        TEST_USERS["drafting_vet_headers"],
    )
    return get_success_data(res)


def get_due_list(pet_id: str) -> List[Dict[str, Any]]:
    res = api_client.get_due_list(pet_id, TEST_USERS["drafting_vet_headers"])
    data = get_success_data(res)
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "due_list" in data:
        return data["due_list"]
    return data  # type: ignore[return-value]


def vaccine_batch_recall(
    *,
    batch_id: str,
    vaccine_code: str,
    event_id: Optional[str] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "batch_id": batch_id,
        "vaccine_code": vaccine_code,
        "event_id": event_id or unique_event_id("evt-recall"),
    }
    res = api_client.vaccine_batch_recall(
        payload, TEST_USERS["platform_admin_headers"],
    )
    return get_success_data(res)


# ===========================================================================
# Tier 4: Prescription-needing helpers — build prescription in IN_CONSULT
#          (PRD §3.7: submit requires Visit==IN_CONSULT) before later
#          transitions move the visit to CONSULT_DONE/HOSPITALIZED.
# ===========================================================================
def setup_visit_consult_done_with_approved_rx(
    *,
    drug_code: str,
    deposit_cents: int = 200_000,
    severity_score: int = 5,
    weight_kg: float = 10.0,
    dose_mg_per_kg: float = 5.0,
    frequency_per_day: int = 2,
    duration_days: int = 5,
    diagnosis_code: str = "K30",
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Build a CONSULT_DONE visit that already carries one APPROVED Rx.

    Sequence respects PRD §3.7 'submit requires Visit==IN_CONSULT' and
    PRD §3.5 'finalize requires Visit==IN_CONSULT' by building the
    prescription and the treatment record while the visit is still in
    IN_CONSULT, then advancing to CONSULT_DONE via end_consult.

    Returns (owner, pet, visit, finalized_tr, approved_rx).
    """
    owner, pet, visit = setup_visit_in_consult(
        severity_score=severity_score, weight_kg=weight_kg,
        deposit_cents=deposit_cents,
    )
    rx = setup_approved_prescription(
        visit_id=visit["id"], drug_code=drug_code,
        dose_mg_per_kg=dose_mg_per_kg,
        frequency_per_day=frequency_per_day, duration_days=duration_days,
        pet_weight_kg=weight_kg,
    )
    tr = create_treatment_record(
        visit_id=visit["id"], diagnosis_code=diagnosis_code,
    )
    tr = finalize_treatment_record(visit_id=visit["id"], tr_id=tr["id"])
    visit = end_consult(visit["id"])
    return owner, pet, visit, tr, rx


# ===========================================================================
# Tier 5: End-to-end CLOSED visit (helper for closure-related tests)
# ===========================================================================
def setup_visit_through_paid_bill(
    *,
    severity_score: int = 5,
    deposit_cents: int = 200_000,
    insurance_estimate_cents: int = 0,
    package_code: Optional[str] = None,
) -> Dict[str, Any]:
    """Drives: visit IN_CONSULT → finalize TR → CONSULT_DONE →
    create bill → recompute → issue → pay → returns context with PAID bill.

    Returns dict with owner, pet, visit, treatment_record, bill (PAID).
    """
    owner, pet, visit, tr = setup_visit_consult_done(
        severity_score=severity_score, deposit_cents=deposit_cents,
    )
    bill = create_bill(
        visit_id=visit["id"], package_code=package_code,
        insurance_estimate_cents=insurance_estimate_cents,
    )
    bill = recompute_bill(bill_id=bill["id"])
    bill = issue_bill(bill_id=bill["id"])
    # The amount due after deposit is the gross_after_discount minus
    # deposit_applied_cents minus min(insurance_estimate, ...).
    amount_due = (
        bill["provisional_total_cents"]
    )
    bill = pay_bill(bill_id=bill["id"], amount_cents=amount_due)
    return {
        "owner": owner,
        "pet": pet,
        "visit": visit,
        "treatment_record": tr,
        "bill": bill,
    }


def setup_visit_closed(**kwargs: Any) -> Dict[str, Any]:
    """Like setup_visit_through_paid_bill, then issue invoice → close visit."""
    ctx = setup_visit_through_paid_bill(**kwargs)
    bill = issue_invoice(bill_id=ctx["bill"]["id"])
    res = api_client.close_visit(
        ctx["visit"]["id"], TEST_USERS["cashier_headers"],
    )
    visit = get_success_data(res)
    ctx["bill"] = bill
    ctx["visit"] = visit
    return ctx


__all__ = [
    # time
    "iso_z",
    "parse_iso",
    "now_iso",
    "add_minutes",
    "add_hours",
    "add_days",
    "advance_clock_seconds",
    # owner / pet
    "create_owner",
    "get_owner",
    "verify_owner_contact",
    "top_up_deposit",
    "create_pet",
    "get_pet",
    "setup_owner_and_pet",
    # visit
    "create_visit",
    "get_visit",
    "triage",
    "start_consult",
    "end_consult",
    "vet_headers_for_visit",
    "setup_visit_in_consult",
    # treatment record
    "create_treatment_record",
    "finalize_treatment_record",
    "setup_visit_with_finalized_treatment",
    "setup_visit_consult_done",
    # lab report
    "create_lab_report",
    "collect_sample",
    "send_to_lab",
    "post_lab_result",
    "finalize_lab_report",
    "lab_report_through_result_received",
    # drug
    "create_drug",
    # prescription
    "create_prescription",
    "submit_prescription",
    "approve_prescription",
    "reject_prescription",
    "redraft_prescription",
    "dispense_prescription",
    "setup_approved_prescription",
    "setup_visit_consult_done_with_approved_rx",
    # cage / hospitalization
    "create_cage",
    "admit_hospitalization",
    "begin_care",
    "append_care",
    "request_discharge",
    "discharge_hospitalization",
    "cancel_hospitalization",
    # bill
    "create_bill",
    "recompute_bill",
    "issue_bill",
    "pay_bill",
    "issue_invoice",
    "request_refund",
    "confirm_refund",
    # composite
    "setup_visit_with_consult_line",
    "setup_visit_through_paid_bill",
    "setup_visit_closed",
    # vaccine
    "create_vaccine_schedule",
    "record_vaccination",
    "get_due_list",
    "vaccine_batch_recall",
    # operator ids
    "DEFAULT_DRAFTING_VET_ID",
    "DEFAULT_REVIEWING_VET_ID",
    "DEFAULT_DRAFTING_VET_HEADERS",
    "DEFAULT_REVIEWING_VET_HEADERS",
]
