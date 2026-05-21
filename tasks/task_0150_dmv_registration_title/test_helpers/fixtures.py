"""Composite setup helpers — multi-step preambles tests can reuse.

Most interesting test claims require the system to be in a late state
that takes 5-15 API calls to reach. Each fixture composes the lower-
level steps so the test body can focus on the rule under assertion.

IDENTITY THREADING — PRD §2.1:

    "When X-User-Role is Applicant, X-User-ID is the id of the acting
    Owner row; ownership checks on any resource that references an Owner
    ... compare the resource's foreign-key field to X-User-ID."

After an Owner is created, fixtures act as that Owner by minting
headers via make_applicant_headers(owner["id"]) — never by reusing the
shared TEST_USERS["applicant_headers"] constant for ownership-gated
operations. The shared constant is reserved for tests that probe auth/
RBAC failure modes without exercising ownership.

CLOCK ANCHORING — PRD §3.8:

    "The platform admin advances the server clock to a supplied to
    instant — an ISO 8601 datetime."

The logical clock is shared across all tests within the process. Each
fixture anchors deadlines to instants the test author can advance to.
The _CURRENT_CLOCK tracker mirrors the server clock so absolute
timestamps in setup payloads (scheduled_start, scheduled_end, etc.)
can be derived without round-trips.

Setup calls use get_success_data (a lenient 2xx validator), so a failed
setup surfaces as 'Setup failed' rather than a confusing test
assertion failure downstream.
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    add_days,
    add_minutes,
    add_seconds,
    approve_salvage_payload,
    clock_advance_payload,
    create_emissions_inspection_payload,
    create_lien_record_payload,
    create_owner_payload,
    create_real_id_application_payload,
    create_transfer_application_payload,
    create_vehicle_payload,
    date_for_age,
    issue_plate_payload,
    iso_utc,
    parse_iso,
    random_plate_number,
    random_station_id,
    random_suffix,
    record_emissions_result_payload,
    release_lien_payload,
    resubmit_real_id_payload,
    salvage_event_payload,
    surrender_plate_payload,
    utcnow,
)
from .test_users import (
    TEST_USERS,
    make_applicant_headers,
    make_plate_issuer_headers,
    make_tax_assessor_headers,
)


# ===========================================================================
# Clock helpers — PRD §3.8 logical clock
# ===========================================================================
_CLOCK_LOCK = threading.Lock()
_CURRENT_CLOCK: Optional[datetime] = None


def _seed_clock() -> datetime:
    global _CURRENT_CLOCK
    with _CLOCK_LOCK:
        if _CURRENT_CLOCK is None:
            _CURRENT_CLOCK = utcnow()
        return _CURRENT_CLOCK


def current_clock() -> datetime:
    """Return the test-process's view of the current logical clock."""
    return _seed_clock()


def current_clock_iso() -> str:
    return iso_utc(current_clock())


def reset_clock_tracker_to(dt: Optional[datetime]) -> None:
    global _CURRENT_CLOCK
    with _CLOCK_LOCK:
        _CURRENT_CLOCK = dt


def advance_clock_to(target_dt: datetime) -> Dict[str, Any]:
    """Advance the logical clock to target_dt.

    PRD §3.8: 'The platform admin advances the server clock to a
    supplied to instant — an ISO 8601 datetime.'
    """
    global _CURRENT_CLOCK
    payload = clock_advance_payload(target_dt)
    resp = api_client.advance_clock(payload, TEST_USERS["platform_admin_headers"])
    data = get_success_data(resp)
    with _CLOCK_LOCK:
        _CURRENT_CLOCK = target_dt
    return data


def advance_clock_by_seconds(seconds: int) -> Dict[str, Any]:
    return advance_clock_to(add_seconds(current_clock(), seconds))


def advance_clock_by_days(days: int) -> Dict[str, Any]:
    return advance_clock_to(add_days(current_clock(), days))


# ===========================================================================
# Owner / Vehicle setup
# ===========================================================================
def create_owner(
    residency_state: str = "CA",
    date_of_birth: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    """Create an Owner. Caller uses the shared applicant header (bootstrap)
    — owner self-creation is permitted to Applicant per PRD §3.1.
    """
    payload = create_owner_payload(
        residency_state=residency_state,
        date_of_birth=date_of_birth,
        **overrides,
    )
    resp = api_client.create_owner(payload, TEST_USERS["applicant_headers"])
    return get_success_data(resp)


def get_owner(owner_id: str,
              headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    h = headers or TEST_USERS["platform_admin_headers"]
    resp = api_client.get_owner(owner_id, h)
    return get_success_data(resp)


def create_vehicle(
    curb_weight_lbs: int = 2500,
    model_year: int = 2026,
    fuel_type: str = "GASOLINE",
    **overrides,
) -> Dict[str, Any]:
    """Create a Vehicle as VinVerifier (PRD §3.2 intake)."""
    payload = create_vehicle_payload(
        curb_weight_lbs=curb_weight_lbs,
        model_year=model_year,
        fuel_type=fuel_type,
        **overrides,
    )
    resp = api_client.create_vehicle(
        payload, TEST_USERS["vin_verifier_headers"],
    )
    return get_success_data(resp)


def get_vehicle(vehicle_id: str,
                headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    h = headers or TEST_USERS["platform_admin_headers"]
    resp = api_client.get_vehicle(vehicle_id, h)
    return get_success_data(resp)


# ===========================================================================
# REAL ID lifecycle helpers
# ===========================================================================
def submit_real_id(owner_id: str,
                   identity: bool = True,
                   residency: bool = True,
                   ssn: bool = True) -> Dict[str, Any]:
    """Submit a REAL ID application. Caller acts as the owning Applicant
    so PRD §3.10 'against their own Owner id' identity check passes.
    """
    payload = create_real_id_application_payload(
        documents_proof_of_identity=identity,
        documents_proof_of_residency=residency,
        documents_proof_of_ssn=ssn,
    )
    headers = make_applicant_headers(owner_id)
    resp = api_client.create_real_id_application(
        owner_id, payload, headers,
    )
    return get_success_data(resp)


def start_review_real_id(app_id: str) -> Dict[str, Any]:
    resp = api_client.start_review_real_id(
        app_id, TEST_USERS["real_id_reviewer_headers"],
    )
    return get_success_data(resp)


def approve_real_id(app_id: str) -> Dict[str, Any]:
    resp = api_client.approve_real_id(
        app_id, TEST_USERS["real_id_reviewer_headers"],
    )
    return get_success_data(resp)


def reject_real_id(app_id: str) -> Dict[str, Any]:
    resp = api_client.reject_real_id(
        app_id, TEST_USERS["real_id_reviewer_headers"],
    )
    return get_success_data(resp)


def resubmit_real_id(owner_id: str, app_id: str,
                     identity: bool = True,
                     residency: bool = True,
                     ssn: bool = True,
                     version: Optional[int] = None) -> Dict[str, Any]:
    payload = resubmit_real_id_payload(
        documents_proof_of_identity=identity,
        documents_proof_of_residency=residency,
        documents_proof_of_ssn=ssn,
        version=version,
    )
    headers = make_applicant_headers(owner_id)
    resp = api_client.resubmit_real_id(app_id, payload, headers)
    return get_success_data(resp)


def revoke_real_id(app_id: str) -> Dict[str, Any]:
    resp = api_client.revoke_real_id(
        app_id, TEST_USERS["platform_admin_headers"],
    )
    return get_success_data(resp)


def approve_owner_to_real_id(
    owner_id: str,
    identity: bool = True,
    residency: bool = True,
    ssn: bool = True,
) -> Dict[str, Any]:
    """Submit + start-review + approve. Returns the approved
    RealIDApplication. Caller is responsible for owner age being in
    [18, 80] so score >= 80 per PRD §3.10.
    """
    app = submit_real_id(owner_id, identity, residency, ssn)
    start_review_real_id(app["id"])
    return approve_real_id(app["id"])


# ===========================================================================
# Transfer application lifecycle helpers
# ===========================================================================
def create_transfer_application(
    owner_id: str,
    vehicle_id: str,
    application_type: str = "TITLE_TRANSFER",
    declared_sale_price: float = 20000.00,
    trade_in_value: Optional[float] = None,
) -> Dict[str, Any]:
    """Create a TransferApplication as the owning Applicant. PRD §3.4."""
    payload = create_transfer_application_payload(
        application_type=application_type,
        applicant_owner_id=owner_id,
        declared_sale_price=declared_sale_price,
        trade_in_value=trade_in_value,
    )
    headers = make_applicant_headers(owner_id)
    resp = api_client.create_transfer_application(
        vehicle_id, payload, headers,
    )
    return get_success_data(resp)


def verify_vin(vehicle_id: str, app_id: str) -> Dict[str, Any]:
    resp = api_client.verify_vin(
        vehicle_id, app_id, TEST_USERS["vin_verifier_headers"],
    )
    return get_success_data(resp)


def assess_fees(
    app_id: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Assess fees. Default is the shared TaxAssessor header. For
    segregation-of-duties tests, pass a custom header carrying a
    distinct opaque operator id.
    """
    h = headers or TEST_USERS["tax_assessor_headers"]
    resp = api_client.assess_fees(app_id, h)
    return get_success_data(resp)


def mark_paid(owner_id: str, app_id: str) -> Dict[str, Any]:
    headers = make_applicant_headers(owner_id)
    resp = api_client.mark_paid(app_id, headers)
    return get_success_data(resp)


def issue_plate(
    app_id: str,
    plate_number: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Issue plate. Default header is the shared PlateIssuer (distinct
    operator id from the shared TaxAssessor). For SoD tests, pass an
    explicit header.
    """
    h = headers or TEST_USERS["plate_issuer_headers"]
    payload = issue_plate_payload(
        plate_number=plate_number or random_plate_number(6),
    )
    resp = api_client.issue_plate(app_id, payload, h)
    return get_success_data(resp)


def approve_salvage(app_id: str,
                    decision: str = "APPROVE") -> Dict[str, Any]:
    payload = approve_salvage_payload(decision=decision)
    resp = api_client.approve_salvage(
        app_id, payload, TEST_USERS["salvage_officer_headers"],
    )
    return get_success_data(resp)


def withdraw_application(owner_id: str, app_id: str) -> Dict[str, Any]:
    headers = make_applicant_headers(owner_id)
    resp = api_client.withdraw_application(app_id, headers)
    return get_success_data(resp)


# ===========================================================================
# Emissions inspection helpers
# ===========================================================================
def schedule_emissions_inspection(
    vehicle_id: str,
    station_id: Optional[str] = None,
    scheduled_start: Optional[datetime] = None,
    scheduled_end: Optional[datetime] = None,
    duration_minutes: int = 30,
) -> Dict[str, Any]:
    """Schedule an inspection. Defaults the slot to now+1h .. +1h30m so
    start-now-grace passes when the test starts it immediately.
    """
    start = scheduled_start or add_minutes(current_clock(), 60)
    end = scheduled_end or add_minutes(start, duration_minutes)
    payload = create_emissions_inspection_payload(
        vehicle_id=vehicle_id,
        station_id=station_id or random_station_id(),
        scheduled_start=iso_utc(start),
        scheduled_end=iso_utc(end),
    )
    resp = api_client.create_emissions_inspection(
        payload, TEST_USERS["emissions_inspector_headers"],
    )
    return get_success_data(resp)


def start_emissions_inspection(inspection_id: str) -> Dict[str, Any]:
    resp = api_client.start_emissions_inspection(
        inspection_id, TEST_USERS["emissions_inspector_headers"],
    )
    return get_success_data(resp)


def record_emissions_result(
    inspection_id: str,
    outcome: str = "PASSED",
    odometer_reading: int = 10000,
) -> Dict[str, Any]:
    payload = record_emissions_result_payload(
        outcome=outcome, odometer_reading=odometer_reading,
    )
    resp = api_client.record_emissions_result(
        inspection_id, payload,
        TEST_USERS["emissions_inspector_headers"],
    )
    return get_success_data(resp)


def cancel_emissions_inspection(inspection_id: str) -> Dict[str, Any]:
    resp = api_client.cancel_emissions_inspection(
        inspection_id, TEST_USERS["emissions_inspector_headers"],
    )
    # Cancellation returns 204 per PRD §2.10; tolerate empty body.
    if resp.status_code == 204:
        return {}
    return get_success_data(resp)


def drive_vehicle_to_emissions_passed(
    vehicle_id: str, odometer_reading: int = 10000,
) -> Dict[str, Any]:
    """Schedule + start + record-PASSED an inspection so that the vehicle
    has a fresh emissions_expires_at (or null for ELECTRIC).
    """
    inspection = schedule_emissions_inspection(vehicle_id)
    # Move the clock to the scheduled_start so /start passes the
    # "now >= start - 15m" grace check.
    start_dt = parse_iso(inspection["scheduled_start"])
    if start_dt > current_clock():
        advance_clock_to(start_dt)
    start_emissions_inspection(inspection["id"])
    return record_emissions_result(
        inspection["id"], outcome="PASSED",
        odometer_reading=odometer_reading,
    )


# ===========================================================================
# Lien helpers
# ===========================================================================
def create_lien_on_title(
    title_id: str,
    lienholder_name: str = "First National Bank",
    principal_amount: float = 12000.00,
) -> Dict[str, Any]:
    payload = create_lien_record_payload(
        lienholder_name=lienholder_name,
        principal_amount=principal_amount,
    )
    resp = api_client.create_lien_record(
        title_id, payload, TEST_USERS["lien_clerk_headers"],
    )
    return get_success_data(resp)


def release_lien_record(
    lien_id: str,
    release_reference: str = "REL-12345",
    version: Optional[int] = None,
) -> Dict[str, Any]:
    payload = release_lien_payload(
        release_reference=release_reference, version=version,
    )
    resp = api_client.release_lien(
        lien_id, payload, TEST_USERS["lien_clerk_headers"],
    )
    return get_success_data(resp)


# ===========================================================================
# Plate helpers
# ===========================================================================
def suspend_plate(plate_id: str) -> Dict[str, Any]:
    resp = api_client.suspend_plate(
        plate_id, TEST_USERS["platform_admin_headers"],
    )
    return get_success_data(resp)


def reinstate_plate(plate_id: str) -> Dict[str, Any]:
    resp = api_client.reinstate_plate(
        plate_id, TEST_USERS["platform_admin_headers"],
    )
    return get_success_data(resp)


def surrender_plate(plate_id: str,
                    surrender_reason: str = "OWNER_REQUEST") -> Dict[str, Any]:
    payload = surrender_plate_payload(surrender_reason=surrender_reason)
    resp = api_client.surrender_plate(
        plate_id, payload, TEST_USERS["platform_admin_headers"],
    )
    return get_success_data(resp)


def get_plate(plate_id: str,
              headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    h = headers or TEST_USERS["platform_admin_headers"]
    resp = api_client.get_plate(plate_id, h)
    return get_success_data(resp)


# ===========================================================================
# Salvage events
# ===========================================================================
def post_salvage_event(vehicle_id: str,
                       severity: str = "PARTIAL") -> Dict[str, Any]:
    payload = salvage_event_payload(severity=severity)
    resp = api_client.post_salvage_event(
        vehicle_id, payload, TEST_USERS["salvage_officer_headers"],
    )
    return get_success_data(resp)


# ===========================================================================
# Fee ledger
# ===========================================================================
def list_fee_ledger(app_id: str,
                    headers: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    h = headers or TEST_USERS["tax_assessor_headers"]
    resp = api_client.list_fee_ledger(app_id, h, params={"limit": 100})
    body = resp.json()
    if "data" not in body:
        raise AssertionError(
            f"Setup failed: list_fee_ledger returned {resp.status_code}: {body!r}"
        )
    data = body["data"]
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "items" in data:
        return data["items"]
    raise AssertionError(f"Setup failed: unexpected fee-ledger payload: {data!r}")


def get_transfer_application(
    app_id: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    h = headers or TEST_USERS["platform_admin_headers"]
    resp = api_client.get_transfer_application(app_id, h)
    return get_success_data(resp)


# ===========================================================================
# Composite pipelines
# ===========================================================================
def setup_owner_with_real_id_approved(
    residency_state: str = "CA",
    age_years: int = 30,
) -> Dict[str, Any]:
    """Create an Owner with age in [18, 80] and APPROVED REAL ID so
    downstream gates pass cleanly. Returns the Owner dict.
    """
    dob = date_for_age(age_years, reference=current_clock())
    owner = create_owner(residency_state=residency_state, date_of_birth=dob)
    approve_owner_to_real_id(owner["id"])
    return get_owner(owner["id"])


def setup_vehicle_with_emissions_passed(
    curb_weight_lbs: int = 2500,
    model_year: int = 2026,
    fuel_type: str = "GASOLINE",
    odometer_reading: int = 10000,
) -> Dict[str, Any]:
    """Create a vehicle and drive a PASSED EmissionsInspection on it so
    Vehicle.emissions_expires_at is set (or null for ELECTRIC).
    Returns the latest vehicle dict.
    """
    vehicle = create_vehicle(
        curb_weight_lbs=curb_weight_lbs,
        model_year=model_year,
        fuel_type=fuel_type,
    )
    drive_vehicle_to_emissions_passed(
        vehicle["id"], odometer_reading=odometer_reading,
    )
    return get_vehicle(vehicle["id"])


def setup_application_at_emissions_passed(
    application_type: str = "TITLE_TRANSFER",
    residency_state: str = "CA",
    age_years: int = 30,
    declared_sale_price: float = 20000.00,
    trade_in_value: Optional[float] = None,
    curb_weight_lbs: int = 2500,
    model_year: int = 2026,
    fuel_type: str = "GASOLINE",
    odometer_reading: int = 10000,
) -> Dict[str, Any]:
    """Drive an application from create through EMISSIONS_PASSED, ready
    for assess-fees.

    Sequence:
      1. Owner created (with APPROVED REAL ID so REAL ID gate is clear)
      2. Vehicle created
      3. TransferApplication created (DRAFT)
      4. verify-vin (DRAFT → VIN_VERIFIED → auto-branch → EMISSIONS_PENDING)
      5. EmissionsInspection scheduled + started + record-PASSED
         which advances the linked TransferApplication EMISSIONS_PENDING
         → EMISSIONS_PASSED per PRD §3.5.

    Returns a dict with keys {owner, vehicle, application,
    inspection}.
    """
    owner = setup_owner_with_real_id_approved(
        residency_state=residency_state, age_years=age_years,
    )
    vehicle = create_vehicle(
        curb_weight_lbs=curb_weight_lbs,
        model_year=model_year,
        fuel_type=fuel_type,
    )
    app = create_transfer_application(
        owner_id=owner["id"],
        vehicle_id=vehicle["id"],
        application_type=application_type,
        declared_sale_price=declared_sale_price,
        trade_in_value=trade_in_value,
    )
    verify_vin(vehicle["id"], app["id"])
    inspection = schedule_emissions_inspection(vehicle["id"])
    start_dt = parse_iso(inspection["scheduled_start"])
    if start_dt > current_clock():
        advance_clock_to(start_dt)
    start_emissions_inspection(inspection["id"])
    record_emissions_result(
        inspection["id"], outcome="PASSED",
        odometer_reading=odometer_reading,
    )
    return {
        "owner": get_owner(owner["id"]),
        "vehicle": get_vehicle(vehicle["id"]),
        "application": get_transfer_application(app["id"]),
        "inspection": inspection,
    }


def setup_application_at_tax_assessed(
    application_type: str = "TITLE_TRANSFER",
    residency_state: str = "CA",
    age_years: int = 30,
    declared_sale_price: float = 20000.00,
    trade_in_value: Optional[float] = None,
    curb_weight_lbs: int = 2500,
    model_year: int = 2026,
    fuel_type: str = "GASOLINE",
    tax_assessor_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Drive an application through assess-fees so it sits in TAX_ASSESSED."""
    base = setup_application_at_emissions_passed(
        application_type=application_type,
        residency_state=residency_state,
        age_years=age_years,
        declared_sale_price=declared_sale_price,
        trade_in_value=trade_in_value,
        curb_weight_lbs=curb_weight_lbs,
        model_year=model_year,
        fuel_type=fuel_type,
    )
    h = tax_assessor_headers or TEST_USERS["tax_assessor_headers"]
    resp = api_client.assess_fees(base["application"]["id"], h)
    base["application"] = get_success_data(resp)
    return base


def setup_application_completed_titled(
    application_type: str = "INITIAL_REGISTRATION",
    residency_state: str = "CA",
    age_years: int = 30,
    declared_sale_price: float = 20000.00,
    trade_in_value: Optional[float] = None,
    curb_weight_lbs: int = 2500,
    model_year: int = 2026,
    fuel_type: str = "GASOLINE",
    plate_number: Optional[str] = None,
    tax_assessor_operator_id: Optional[str] = None,
    plate_issuer_operator_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Drive a full lifecycle through COMPLETED so a Title row exists
    and a Plate row is ACTIVE for the vehicle. Uses distinct operator
    ids for TaxAssessor and PlateIssuer to satisfy PRD §3.8 SoD.
    """
    ta_headers = (
        make_tax_assessor_headers(tax_assessor_operator_id)
        if tax_assessor_operator_id else TEST_USERS["tax_assessor_headers"]
    )
    pi_headers = (
        make_plate_issuer_headers(plate_issuer_operator_id)
        if plate_issuer_operator_id else TEST_USERS["plate_issuer_headers"]
    )
    base = setup_application_at_tax_assessed(
        application_type=application_type,
        residency_state=residency_state,
        age_years=age_years,
        declared_sale_price=declared_sale_price,
        trade_in_value=trade_in_value,
        curb_weight_lbs=curb_weight_lbs,
        model_year=model_year,
        fuel_type=fuel_type,
        tax_assessor_headers=ta_headers,
    )
    mark_paid(base["owner"]["id"], base["application"]["id"])
    issued_plate_app = issue_plate(
        base["application"]["id"],
        plate_number=plate_number, headers=pi_headers,
    )
    base["application"] = get_transfer_application(
        base["application"]["id"],
    )
    base["plate_app_response"] = issued_plate_app
    base["vehicle"] = get_vehicle(base["vehicle"]["id"])
    return base


# ===========================================================================
# Difficulty-design targeted helpers
# ===========================================================================
def setup_pair_for_resident_vs_non_resident(
    declared_sale_price: float = 20000.00,
    trade_in_value: float = 5000.00,
    curb_weight_lbs: int = 2500,
    model_year: int = 2026,
) -> Dict[str, Any]:
    """Two identical TransferApplications at EMISSIONS_PASSED, one for a
    resident Owner (CA) and one for a non-resident Owner (NV). Inputs
    are identical otherwise.

    Used by the resident-vs-non-resident sales-tax dual-variant tests
    (Rule 1 / sales_tax_resident_vs_non_resident_on_transfer).
    """
    resident_base = setup_application_at_emissions_passed(
        application_type="TITLE_TRANSFER",
        residency_state="CA",
        declared_sale_price=declared_sale_price,
        trade_in_value=trade_in_value,
        curb_weight_lbs=curb_weight_lbs,
        model_year=model_year,
    )
    non_resident_base = setup_application_at_emissions_passed(
        application_type="TITLE_TRANSFER",
        residency_state="NV",
        declared_sale_price=declared_sale_price,
        trade_in_value=trade_in_value,
        curb_weight_lbs=curb_weight_lbs,
        model_year=model_year,
    )
    return {"resident": resident_base, "non_resident": non_resident_base}


def setup_vehicle_for_weight_tier(
    curb_weight_lbs: int,
    model_year: int = 2026,
    residency_state: str = "CA",
    declared_sale_price: float = 20000.00,
    trade_in_value: float = 0.00,
) -> Dict[str, Any]:
    """Single application at EMISSIONS_PASSED parametrized by
    curb_weight_lbs. Used by registration-fee weight-tier tests.
    """
    return setup_application_at_emissions_passed(
        application_type="TITLE_TRANSFER",
        residency_state=residency_state,
        declared_sale_price=declared_sale_price,
        trade_in_value=trade_in_value,
        curb_weight_lbs=curb_weight_lbs,
        model_year=model_year,
    )


__all__ = [
    # clock
    "advance_clock_to",
    "advance_clock_by_seconds",
    "advance_clock_by_days",
    "current_clock",
    "current_clock_iso",
    "reset_clock_tracker_to",
    # owner / vehicle
    "create_owner",
    "get_owner",
    "create_vehicle",
    "get_vehicle",
    # real id
    "submit_real_id",
    "start_review_real_id",
    "approve_real_id",
    "reject_real_id",
    "resubmit_real_id",
    "revoke_real_id",
    "approve_owner_to_real_id",
    # transfer
    "create_transfer_application",
    "verify_vin",
    "approve_salvage",
    "assess_fees",
    "mark_paid",
    "issue_plate",
    "withdraw_application",
    "get_transfer_application",
    # emissions
    "schedule_emissions_inspection",
    "start_emissions_inspection",
    "record_emissions_result",
    "cancel_emissions_inspection",
    "drive_vehicle_to_emissions_passed",
    # lien
    "create_lien_on_title",
    "release_lien_record",
    # plate
    "suspend_plate",
    "reinstate_plate",
    "surrender_plate",
    "get_plate",
    # salvage
    "post_salvage_event",
    # fee ledger
    "list_fee_ledger",
    # composites
    "setup_owner_with_real_id_approved",
    "setup_vehicle_with_emissions_passed",
    "setup_application_at_emissions_passed",
    "setup_application_at_tax_assessed",
    "setup_application_completed_titled",
    # difficulty
    "setup_pair_for_resident_vs_non_resident",
    "setup_vehicle_for_weight_tier",
]
