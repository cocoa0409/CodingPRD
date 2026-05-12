"""Composite setup helpers for the Home Nursing test suite.

The PRD's lifecycle has many interlocking phases:

  Nurse (PENDING -> CERTIFIED -> EXPIRING -> CERTIFIED|PENDING|DISQUALIFIED)
  Order (SUBMITTED -> {UNDER_REVIEW|AWAITING_DISPATCH} -> DISPATCHED ->
         IN_PROGRESS -> COMPLETED | CANCELLED | REJECTED)
  Order.payment_status (UNPAID -> AUTHORIZED -> CAPTURED|REFUNDED)
  Dispatch (OFFERED -> ACCEPTED|REJECTED|EXPIRED|CANCELLED)
  ServiceRecord (STARTED -> IN_PROGRESS -> AWAITING_PATIENT_CONFIRM -> COMPLETED)
  WasteEntry (REGISTERED -> HANDED_OVER -> ARCHIVED)
  Complaint (SUBMITTED -> TRIAGE -> MEDIATION -> RESOLVED|REJECTED)

Most interesting tests need the system in a non-initial state; many
ownership-gated calls (Dispatch.accept, ServiceRecord, WasteEntry,
Patient cancel/confirm, Complaint submission) compare X-User-ID to
stored fields per PRD §2.1, so identity threading is mandatory.

Identity threading (PRD §2.1):

- Nurse is entity_backed:Nurse. After create_certified_nurse(), every
  call by that nurse MUST use make_nurse_headers(nurse["id"]) -- not
  the shared TEST_USERS["nurse_headers"] fallback.

- Patient is opaque, but Order.patient_id / Package.patient_id /
  Complaint.patient_id store the X-User-ID at creation time. Helpers
  mint a stable per-test patient_id and thread it through every
  Patient call so cancellation / confirm-completion / get-own-order
  succeed.

Setup calls use get_success_data (lenient validator) so broken
preconditions surface as obvious 'Setup failed' errors, not confusing
assertion failures.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
import math
import uuid

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    abnormal_event,
    checklist_item,
    create_certification_record_payload,
    create_complaint_payload,
    create_nurse_payload,
    create_order_payload,
    create_package_payload,
    create_payout_batch_payload,
    create_service_item_payload,
    create_service_record_payload,
    create_waste_entry_payload,
    emit_event_payload,
    medication_entry,
    patch_service_record_payload,
    patch_waste_entry_payload,
    resolve_complaint_payload,
    review_order_payload,
    unique_id,
    unique_license_number,
    unique_service_item_code,
    unique_user_id,
    vital_entry,
)
from .test_users import (
    TEST_USERS,
    make_compliance_officer_headers,
    make_nurse_headers,
    make_patient_headers,
    make_platform_admin_headers,
)


# ===========================================================================
# Time helpers (PRD §2.6 -- ISO 8601 UTC with three fractional digits)
# ===========================================================================
def iso_z(dt: datetime) -> str:
    """Format a datetime as ISO 8601 UTC with exactly three fractional
    digits.

    PRD §2.6: 'All timestamps in the system are ISO 8601 UTC with three
    fractional digits.'
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    millis = int(dt.microsecond / 1000)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{millis:03d}Z"


def parse_iso(s: str) -> datetime:
    s2 = s.replace("Z", "+00:00")
    return datetime.fromisoformat(s2)


def add_seconds(s: str, n: float) -> str:
    return iso_z(parse_iso(s) + timedelta(seconds=n))


def add_minutes(s: str, n: float) -> str:
    return iso_z(parse_iso(s) + timedelta(minutes=n))


def add_hours(s: str, n: float) -> str:
    return iso_z(parse_iso(s) + timedelta(hours=n))


def add_days(s: str, n: float) -> str:
    return iso_z(parse_iso(s) + timedelta(days=n))


# Default base instant. May 11, 2026 is a Monday; daytime UTC hour 10
# is in the standard band (DAY_BPS, no surcharge).
DEFAULT_NOW_ISO = "2026-05-11T10:00:00.000Z"
# Daytime weekday slot used by most fee tests
DEFAULT_SCHEDULED_START_ISO = "2026-06-01T10:00:00.000Z"  # Monday daytime


# ===========================================================================
# Geographic helpers (PRD §2.6 -- great-circle / Haversine)
# ===========================================================================
EARTH_RADIUS_KM = 6371.0


def haversine_km(lat1: float, lng1: float,
                 lat2: float, lng2: float) -> float:
    """Great-circle distance between two coordinates in km."""
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = (math.sin(dp / 2) ** 2 +
         math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return EARTH_RADIUS_KM * c


def offset_lat_km(lat: float, km: float) -> float:
    """Return a latitude shifted north by `km` (1 deg lat ~ 111.32 km)."""
    return lat + km / 111.32


def offset_lng_km(lat: float, lng: float, km: float) -> float:
    """Return a longitude shifted east by `km` at the given latitude."""
    return lng + km / (111.32 * math.cos(math.radians(lat)))


# ===========================================================================
# Test-driving wrappers (PRD §3.6)
# ===========================================================================
_last_known_clock_iso: Optional[str] = None


def advance_clock(to_iso: str,
                  headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """POST /_clock/advance. PRD §3.6 names this as the admin-only test
    driver that 'advances the logical clock to a supplied to instant'."""
    global _last_known_clock_iso
    res = api_client.advance_clock(
        to_iso, headers or TEST_USERS["platform_admin_headers"]
    )
    data = get_success_data(res)
    _last_known_clock_iso = to_iso
    return data


def emit_event(system: str, event_type: str,
               payload: Optional[Dict[str, Any]] = None,
               headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """POST /_events/emit. PRD §3.6 lists the supported (system, event_type)
    combinations."""
    body = emit_event_payload(
        system=system, event_type=event_type, payload=payload or {}
    )
    res = api_client.emit_event(
        body, headers or TEST_USERS["platform_admin_headers"]
    )
    return get_success_data(res)


def stable_user_id(prefix: str = "u") -> str:
    """Mint a stable id used as X-User-ID for opaque-role threading
    (Patient.patient_id, etc.)."""
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


# ---------------------------------------------------------------------------
# Per-test geographic isolation
# ---------------------------------------------------------------------------
# Tests share a single in-process implementation so leaked rows from prior
# tests can pollute the dispatch selector when subsequent tests share the
# default service coordinates. We rotate a (lat,lng) cluster spaced
# 50+ km apart on every test boundary (autouse pytest fixture in
# conftest) so leaked nurses created by prior tests fall outside the
# 15-kilometre dispatch radius for the current test's order.
_ISOLATION_BASE_LAT = 10.0
_ISOLATION_BASE_LNG = 100.0
_ISOLATION_STEP_DEG = 0.5  # ~55 km between successive clusters
_isolation_counter = 0
_CURRENT_CLUSTER: Tuple[float, float] = (_ISOLATION_BASE_LAT, _ISOLATION_BASE_LNG)


def _next_isolation_coords() -> Tuple[float, float]:
    """Advance to the next unique (lat, lng) cluster and return it.

    Test isolation: rotated by an autouse fixture before every test so
    each test's order/nurse setup defaults land in a fresh cluster
    >50 km from any prior test's cluster.
    """
    global _isolation_counter, _CURRENT_CLUSTER
    _isolation_counter += 1
    n = _isolation_counter
    # Walk a 30x30 grid in 0.5° steps; 30^2 = 900 distinct clusters.
    row, col = divmod(n, 30)
    lat = _ISOLATION_BASE_LAT + row * _ISOLATION_STEP_DEG
    lng = _ISOLATION_BASE_LNG + col * _ISOLATION_STEP_DEG
    _CURRENT_CLUSTER = (lat, lng)
    return lat, lng


def current_cluster_coords() -> Tuple[float, float]:
    """Return the (lat, lng) cluster reserved for the running test."""
    return _CURRENT_CLUSTER


def reset_isolation_for_new_test() -> Tuple[float, float]:
    """Allocate a fresh cluster for a new test. Called from an autouse
    pytest fixture so every test sees a unique default service location.
    """
    return _next_isolation_coords()


# ===========================================================================
# Tier 1 -- Single-entity creation
# ===========================================================================
def create_nurse_raw(
    *,
    home_lat: Optional[float] = None,
    home_lng: Optional[float] = None,
    specialty_tags: Optional[List[str]] = None,
    gender: str = "F",
    languages: Optional[List[str]] = None,
    max_daily_orders: Optional[int] = None,
    revenue_share_bps: Optional[int] = None,
    full_name: Optional[str] = None,
    license_number: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Create a Nurse profile (status PENDING per PRD §3.1).

    When home_lat/home_lng are not supplied, default to the current
    test's isolation cluster so leaked nurses from prior tests are
    >15 km away from this test's order coordinates.
    """
    if home_lat is None or home_lng is None:
        cluster_lat, cluster_lng = current_cluster_coords()
        if home_lat is None:
            home_lat = cluster_lat
        if home_lng is None:
            home_lng = cluster_lng
    payload = create_nurse_payload(
        full_name=full_name,
        gender=gender,
        languages=languages,
        license_number=license_number,
        specialty_tags=specialty_tags,
        home_lat=home_lat,
        home_lng=home_lng,
        max_daily_orders=max_daily_orders,
        revenue_share_bps=revenue_share_bps,
    )
    res = api_client.create_nurse(
        payload, headers or TEST_USERS["platform_admin_headers"]
    )
    return get_success_data(res)


def verify_nurse_identity(
    nurse_id: str,
    *,
    license: bool = True,
    hospital: bool = True,
) -> None:
    """Drive identity-verification handshakes per PRD §3.1, §3.6.

    PRD §3.1: 'Two external handshakes -- a nursing-license verifier and
    a hospital-affiliation verifier -- return through the test event hook
    (system=identity-verification); their successful completion sets
    license_verified or hospital_affiliation_verified to true.'
    """
    if license:
        emit_event(
            "identity-verification", "LICENSE_VERIFIED",
            {"nurse_id": nurse_id},
        )
    if hospital:
        emit_event(
            "identity-verification", "HOSPITAL_AFFILIATION_VERIFIED",
            {"nurse_id": nurse_id},
        )


def certify_nurse(
    nurse_id: str,
    *,
    effective_at: Optional[str] = None,
    training_hours: float = 24.0,
    notes: str = "Initial certification",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Append a CertificationRecord(kind=INITIAL, outcome=PASS).

    PRD §3.1: requires license_verified, hospital_affiliation_verified,
    and cumulative training_hours >= 24 to advance the nurse from
    PENDING to CERTIFIED.
    """
    payload = create_certification_record_payload(
        kind="INITIAL", outcome="PASS",
        effective_at=effective_at or DEFAULT_NOW_ISO,
        training_hours=training_hours, notes=notes,
    )
    res = api_client.create_certification_record(
        nurse_id, payload,
        headers or TEST_USERS["compliance_officer_headers"],
    )
    return get_success_data(res)


def create_certified_nurse(
    *,
    home_lat: Optional[float] = None,
    home_lng: Optional[float] = None,
    specialty_tags: Optional[List[str]] = None,
    gender: str = "F",
    languages: Optional[List[str]] = None,
    max_daily_orders: Optional[int] = None,
    revenue_share_bps: Optional[int] = None,
    full_name: Optional[str] = None,
    effective_at: Optional[str] = None,
) -> Dict[str, Any]:
    """End-to-end: create a Nurse, drive identity-verification, append
    INITIAL CertificationRecord with 24 training_hours -> CERTIFIED.

    Defaults home_lat/home_lng to the current test's isolation cluster
    so that the nurse is co-located with the test's order coordinates
    (also defaulted to the same cluster) and leaked nurses from prior
    tests fall outside the 15 km dispatch radius.

    Returns the freshly fetched Nurse row in CERTIFIED. The caller MUST
    pass nurse['id'] to make_nurse_headers() for any nurse-acting call.
    """
    nurse = create_nurse_raw(
        home_lat=home_lat, home_lng=home_lng,
        specialty_tags=specialty_tags,
        gender=gender, languages=languages,
        max_daily_orders=max_daily_orders,
        revenue_share_bps=revenue_share_bps,
        full_name=full_name,
    )
    verify_nurse_identity(nurse["id"])
    certify_nurse(
        nurse["id"], effective_at=effective_at, training_hours=24,
    )
    # Re-read the nurse to pick up new certification_status.
    res = api_client.get_nurse(
        nurse["id"], TEST_USERS["compliance_officer_headers"]
    )
    return get_success_data(res)


def create_service_item_raw(
    *,
    code: Optional[str] = None,
    required_skill: str = "IV_INFUSION",
    requires_medical_doc: Optional[bool] = None,
    requires_eligibility_review: Optional[bool] = None,
    base_price_cents: int = 20000,
    duration_minutes: int = 30,
    name: Optional[str] = None,
) -> Dict[str, Any]:
    payload = create_service_item_payload(
        code=code,
        name=name,
        required_skill=required_skill,
        requires_medical_doc=requires_medical_doc,
        requires_eligibility_review=requires_eligibility_review,
        base_price_cents=base_price_cents,
        duration_minutes=duration_minutes,
    )
    res = api_client.create_service_item(
        payload, TEST_USERS["platform_admin_headers"]
    )
    return get_success_data(res)


def create_package_raw(
    *,
    patient_id: str,
    service_item_code: str,
    total_credits: int = 3,
    expires_at: Optional[str] = None,
) -> Dict[str, Any]:
    if expires_at is None:
        expires_at = add_days(DEFAULT_NOW_ISO, 365)
    payload = create_package_payload(
        patient_id=patient_id,
        service_item_code=service_item_code,
        total_credits=total_credits,
        expires_at=expires_at,
    )
    res = api_client.create_package(
        payload, TEST_USERS["platform_admin_headers"]
    )
    return get_success_data(res)


# ===========================================================================
# Tier 2 -- Order creation
# ===========================================================================
def create_order_raw(
    *,
    patient_id: str,
    service_item_code: str,
    service_lat: Optional[float] = None,
    service_lng: Optional[float] = None,
    scheduled_start: Optional[str] = None,
    preferred_gender: Optional[str] = None,
    preferred_language: Optional[str] = None,
    medical_doc_url: Optional[str] = None,
    package_id: Optional[str] = None,
    idempotency_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a single Order as the given patient. The X-User-ID stored
    on Order.patient_id will equal `patient_id` per PRD §2.1.

    Defaults service_lat/service_lng to the current test's isolation
    cluster so the test's just-created nurse (also at the same cluster
    via create_certified_nurse) is the only candidate within the 15 km
    dispatch radius.
    """
    if service_lat is None or service_lng is None:
        cluster_lat, cluster_lng = current_cluster_coords()
        if service_lat is None:
            service_lat = cluster_lat
        if service_lng is None:
            service_lng = cluster_lng
    payload = create_order_payload(
        service_item_code=service_item_code,
        service_lat=service_lat,
        service_lng=service_lng,
        scheduled_start=scheduled_start or DEFAULT_SCHEDULED_START_ISO,
        preferred_gender=preferred_gender,
        preferred_language=preferred_language,
        medical_doc_url=medical_doc_url,
        package_id=package_id,
    )
    headers = make_patient_headers(patient_id)
    if idempotency_key is not None:
        headers = dict(headers)
        headers["Idempotency-Key"] = idempotency_key
    res = api_client.create_order(payload, headers)
    return get_success_data(res)


# ===========================================================================
# Tier 3 -- Composite scenarios (Order + Dispatch path)
# ===========================================================================
def setup_basic_dispatched_order(
    *,
    nurse_specialty: str = "IV_INFUSION",
    requires_eligibility_review: bool = False,
    requires_medical_doc: bool = False,
    medical_doc_url: Optional[str] = None,
    base_price_cents: int = 20000,
    revenue_share_bps: Optional[int] = None,
    nurse_home_lat: Optional[float] = None,
    nurse_home_lng: Optional[float] = None,
    service_lat: Optional[float] = None,
    service_lng: Optional[float] = None,
    scheduled_start: Optional[str] = None,
    package_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Set up: ServiceItem, certified Nurse with the required skill close
    to the service address, Patient submits an Order; eligibility review
    APPROVED if required so the Order is in AWAITING_DISPATCH and a
    single OFFERED Dispatch exists.

    By default the nurse's home and the order's service address share a
    unique (lat,lng) cluster spaced > 50 km from every prior setup call
    (see _next_isolation_coords); this puts leaked nurses from earlier
    tests outside the 15 km dispatch radius and keeps the just-created
    nurse the lone candidate.

    Returns dict with: service_item, nurse, nurse_id, patient_id,
    order, dispatch.
    """
    # Cluster default flow: when neither service nor nurse coords are
    # supplied, fall back to the current test's isolation cluster so
    # both end up co-located. Explicit overrides win.
    if service_lat is None or service_lng is None:
        cluster_lat, cluster_lng = current_cluster_coords()
        if service_lat is None:
            service_lat = cluster_lat
        if service_lng is None:
            service_lng = cluster_lng
    if nurse_home_lat is None:
        nurse_home_lat = service_lat
    if nurse_home_lng is None:
        nurse_home_lng = service_lng
    service_item = create_service_item_raw(
        required_skill=nurse_specialty,
        requires_medical_doc=requires_medical_doc,
        requires_eligibility_review=requires_eligibility_review,
        base_price_cents=base_price_cents,
    )
    nurse = create_certified_nurse(
        home_lat=nurse_home_lat, home_lng=nurse_home_lng,
        specialty_tags=[nurse_specialty],
        revenue_share_bps=revenue_share_bps,
    )
    patient_id = stable_user_id("patient")
    order = create_order_raw(
        patient_id=patient_id,
        service_item_code=service_item["code"],
        service_lat=service_lat, service_lng=service_lng,
        scheduled_start=scheduled_start,
        medical_doc_url=medical_doc_url,
        package_id=package_id,
    )
    if requires_eligibility_review:
        res = api_client.review_order(
            order["id"],
            review_order_payload(decision="APPROVE"),
            TEST_USERS["compliance_officer_headers"],
        )
        get_success_data(res)
    # Refetch order to pick up status
    order = get_success_data(api_client.get_order(
        order["id"], make_patient_headers(patient_id)
    ))
    dispatch = _get_first_offered_dispatch(order["id"])
    return {
        "service_item": service_item,
        "nurse": nurse,
        "nurse_id": nurse["id"],
        "patient_id": patient_id,
        "order": order,
        "dispatch": dispatch,
    }


def _get_first_offered_dispatch(order_id: str) -> Optional[Dict[str, Any]]:
    res = api_client.list_dispatches(
        order_id, TEST_USERS["compliance_officer_headers"]
    )
    data = get_success_data(res)
    rows = data if isinstance(data, list) else data.get("data", [])
    if not rows and isinstance(data, dict):
        # framework may return envelope already unwrapped
        rows = data
    if isinstance(rows, dict):
        rows = []
    for d in rows:
        if d.get("status") == "OFFERED":
            return d
    return rows[0] if rows else None


def list_dispatches_for(order_id: str) -> List[Dict[str, Any]]:
    res = api_client.list_dispatches(
        order_id, TEST_USERS["compliance_officer_headers"]
    )
    data = get_success_data(res)
    if isinstance(data, list):
        return data
    return []


def accept_dispatch(dispatch: Dict[str, Any], nurse_id: str) -> Dict[str, Any]:
    """Have the named nurse accept an OFFERED dispatch. Threads the
    nurse's id into X-User-ID per PRD §2.1."""
    res = api_client.accept_dispatch(
        dispatch["id"], make_nurse_headers(nurse_id)
    )
    return get_success_data(res)


def reject_dispatch(dispatch: Dict[str, Any], nurse_id: str,
                    rejection_reason: str = "test reject") -> Dict[str, Any]:
    res = api_client.reject_dispatch(
        dispatch["id"], make_nurse_headers(nurse_id),
        {"rejection_reason": rejection_reason},
    )
    return get_success_data(res)


# ===========================================================================
# Tier 4 -- ServiceRecord / waste / completion
# ===========================================================================
def perform_checkin(
    order_id: str,
    nurse_id: str,
    *,
    checkin_at: Optional[str] = None,
    checkin_lat: float = 31.20,
    checkin_lng: float = 121.40,
    face_verification_passed: bool = True,
    checklist_items: Optional[List[Dict[str, Any]]] = None,
    evidence_urls: Optional[List[str]] = None,
    keep_started: bool = True,
) -> Dict[str, Any]:
    """Post the on-site check-in.

    PRD §3.4: 'A successful check-in creates the ServiceRecord with status
    STARTED, advances the order from DISPATCHED to IN_PROGRESS.'  This
    helper returns the STARTED record by default; callers that need the
    record advanced to IN_PROGRESS for a subsequent /finish call should
    invoke advance_sr_to_in_progress() afterwards.
    """
    payload = create_service_record_payload(
        checkin_at=checkin_at or DEFAULT_SCHEDULED_START_ISO,
        checkin_lat=checkin_lat,
        checkin_lng=checkin_lng,
        face_verification_passed=face_verification_passed,
        checklist_items=checklist_items if checklist_items is not None
        else [checklist_item("vitals", done=True)],
        evidence_urls=evidence_urls if evidence_urls is not None
        else ["https://evidence.example/photo1.jpg"],
    )
    res = api_client.create_service_record(
        order_id, payload, make_nurse_headers(nurse_id)
    )
    return get_success_data(res)


def advance_sr_to_in_progress(order_id: str, nurse_id: str) -> Dict[str, Any]:
    """PATCH the ServiceRecord with an empty append so the record advances
    from STARTED to IN_PROGRESS.

    PRD §3.4: 'The first append after check-in advances the record from
    STARTED to IN_PROGRESS.'  /finish then requires IN_PROGRESS.
    """
    res = api_client.patch_service_record(
        order_id, {}, make_nurse_headers(nurse_id),
    )
    return get_success_data(res)


def finish_service_record(order_id: str, nurse_id: str) -> Dict[str, Any]:
    # PRD §3.4: 'The first append after check-in advances the record from
    # STARTED to IN_PROGRESS.'  /finish requires IN_PROGRESS, so this
    # helper transparently issues an empty PATCH first.
    api_client.patch_service_record(
        order_id, {}, make_nurse_headers(nurse_id),
    )
    res = api_client.finish_service_record(
        order_id, make_nurse_headers(nurse_id)
    )
    return get_success_data(res)


def confirm_completion(order_id: str, patient_id: str) -> Dict[str, Any]:
    res = api_client.confirm_completion(
        order_id, make_patient_headers(patient_id)
    )
    return get_success_data(res)


def setup_in_progress_order(
    *,
    nurse_specialty: str = "ELDERLY_CARE",
    base_price_cents: int = 20000,
    revenue_share_bps: Optional[int] = None,
    nurse_home_lat: Optional[float] = None,
    nurse_home_lng: Optional[float] = None,
    service_lat: Optional[float] = None,
    service_lng: Optional[float] = None,
    scheduled_start: Optional[str] = None,
    checkin_at: Optional[str] = None,
    package_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Set up an Order through to IN_PROGRESS (Dispatch ACCEPTED, check-in
    posted). Uses ELDERLY_CARE by default to avoid waste-producing skills.
    """
    setup = setup_basic_dispatched_order(
        nurse_specialty=nurse_specialty,
        base_price_cents=base_price_cents,
        revenue_share_bps=revenue_share_bps,
        nurse_home_lat=nurse_home_lat, nurse_home_lng=nurse_home_lng,
        service_lat=service_lat, service_lng=service_lng,
        scheduled_start=scheduled_start,
        package_id=package_id,
    )
    accept_dispatch(setup["dispatch"], setup["nurse_id"])
    record = perform_checkin(
        setup["order"]["id"], setup["nurse_id"],
        checkin_at=checkin_at,
        checkin_lat=setup["order"]["service_lat"],
        checkin_lng=setup["order"]["service_lng"],
    )
    # PRD §3.4: 'The first append after check-in advances the record from
    # STARTED to IN_PROGRESS.'  /finish requires IN_PROGRESS, so the
    # in-progress fixture explicitly drives this transition.
    record = advance_sr_to_in_progress(
        setup["order"]["id"], setup["nurse_id"],
    )
    setup["service_record"] = record
    setup["order"] = get_success_data(api_client.get_order(
        setup["order"]["id"],
        make_patient_headers(setup["patient_id"]),
    ))
    return setup


def setup_awaiting_patient_confirm_order(
    *,
    nurse_specialty: str = "ELDERLY_CARE",
    base_price_cents: int = 20000,
    revenue_share_bps: Optional[int] = None,
    nurse_home_lat: Optional[float] = None,
    nurse_home_lng: Optional[float] = None,
    service_lat: Optional[float] = None,
    service_lng: Optional[float] = None,
    scheduled_start: Optional[str] = None,
    checkin_at: Optional[str] = None,
    package_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Drive through to ServiceRecord.status=AWAITING_PATIENT_CONFIRM."""
    setup = setup_in_progress_order(
        nurse_specialty=nurse_specialty,
        base_price_cents=base_price_cents,
        revenue_share_bps=revenue_share_bps,
        nurse_home_lat=nurse_home_lat, nurse_home_lng=nurse_home_lng,
        service_lat=service_lat, service_lng=service_lng,
        scheduled_start=scheduled_start, checkin_at=checkin_at,
        package_id=package_id,
    )
    finish_service_record(setup["order"]["id"], setup["nurse_id"])
    return setup


def setup_completed_order(
    *,
    nurse_specialty: str = "ELDERLY_CARE",
    base_price_cents: int = 20000,
    revenue_share_bps: Optional[int] = None,
    nurse_home_lat: Optional[float] = None,
    nurse_home_lng: Optional[float] = None,
    service_lat: Optional[float] = None,
    service_lng: Optional[float] = None,
    scheduled_start: Optional[str] = None,
    checkin_at: Optional[str] = None,
    package_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Drive through to Order.status=COMPLETED. Returns the same dict
    plus 'settlement'."""
    setup = setup_awaiting_patient_confirm_order(
        nurse_specialty=nurse_specialty,
        base_price_cents=base_price_cents,
        revenue_share_bps=revenue_share_bps,
        nurse_home_lat=nurse_home_lat, nurse_home_lng=nurse_home_lng,
        service_lat=service_lat, service_lng=service_lng,
        scheduled_start=scheduled_start, checkin_at=checkin_at,
        package_id=package_id,
    )
    confirm_completion(setup["order"]["id"], setup["patient_id"])
    setup["order"] = get_success_data(api_client.get_order(
        setup["order"]["id"],
        make_patient_headers(setup["patient_id"]),
    ))
    settlement_res = api_client.get_settlement(
        setup["order"]["id"],
        make_patient_headers(setup["patient_id"]),
    )
    settlement = get_success_data(settlement_res)
    setup["settlement"] = settlement
    return setup


# ===========================================================================
# Tier 5 -- Waste flow
# ===========================================================================
def register_waste(order_id: str, nurse_id: str,
                   category: str = "SHARPS",
                   quantity: float = 1.0,
                   unit: str = "PCS") -> Dict[str, Any]:
    res = api_client.create_waste_entry(
        order_id,
        create_waste_entry_payload(
            category=category, quantity=quantity, unit=unit,
        ),
        make_nurse_headers(nurse_id),
    )
    return get_success_data(res)


def hand_over_waste(order_id: str, waste_id: str, nurse_id: str,
                    *, handover_at: Optional[str] = None,
                    disposal_unit_id: str = "DUI-001") -> Dict[str, Any]:
    res = api_client.patch_waste_entry(
        order_id, waste_id,
        patch_waste_entry_payload(
            sealed=True,
            disposal_unit_id=disposal_unit_id,
            handover_at=handover_at or DEFAULT_NOW_ISO,
        ),
        make_nurse_headers(nurse_id),
    )
    return get_success_data(res)


def archive_waste(waste_id: str,
                  certificate_url: str = "https://disposal.example/c.pdf",
                  ) -> Dict[str, Any]:
    """Drive WasteEntry HANDED_OVER -> ARCHIVED via /_events/emit."""
    return emit_event(
        "medical-waste-disposal", "CERTIFICATE_ISSUED",
        {"waste_id": waste_id, "certificate_url": certificate_url},
    )


# ===========================================================================
# Tier 6 -- Complaint flow
# ===========================================================================
def submit_complaint(order_id: str, patient_id: str, *,
                     category: str = "SERVICE_QUALITY",
                     description: str = "Service not satisfactory",
                     ) -> Dict[str, Any]:
    res = api_client.create_complaint(
        create_complaint_payload(
            order_id=order_id, category=category, description=description,
        ),
        make_patient_headers(patient_id),
    )
    return get_success_data(res)


def triage_complaint(complaint_id: str) -> Dict[str, Any]:
    res = api_client.triage_complaint(
        complaint_id, TEST_USERS["compliance_officer_headers"]
    )
    return get_success_data(res)


def escalate_complaint(complaint_id: str) -> Dict[str, Any]:
    res = api_client.escalate_complaint(
        complaint_id, TEST_USERS["compliance_officer_headers"]
    )
    return get_success_data(res)


def resolve_complaint(
    complaint_id: str,
    *,
    decision: str = "UPHOLD",
    compensation_cents: Optional[int] = None,
    rating_impact: Optional[float] = None,
    resolution_notes: Optional[str] = None,
) -> Dict[str, Any]:
    payload = resolve_complaint_payload(
        decision=decision,
        compensation_cents=compensation_cents,
        rating_impact=rating_impact,
        resolution_notes=resolution_notes,
    )
    res = api_client.resolve_complaint(
        complaint_id, payload, TEST_USERS["compliance_officer_headers"]
    )
    return get_success_data(res)


# ===========================================================================
# Tier 7 -- Audit log helpers
# ===========================================================================
def list_audit_logs(*, subject_type: Optional[str] = None,
                    subject_id: Optional[str] = None) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {"limit": 100}
    if subject_type is not None:
        params["subject_type"] = subject_type
    if subject_id is not None:
        params["subject_id"] = subject_id
    res = api_client.list_audit_logs(
        TEST_USERS["compliance_officer_headers"], params=params
    )
    data = get_success_data(res)
    if isinstance(data, list):
        return data
    return []


# ===========================================================================
# Tier 8 -- Targeted scenarios for difficulty-design instances
# ===========================================================================
def setup_dual_score_scenario(
    *,
    service_lat: float = 31.20,
    service_lng: float = 121.40,
) -> Dict[str, Any]:
    """Two CERTIFIED nurses for the same ServiceItem, with engineered
    distances/loads/ratings so the dispatch score has a deterministic
    winner per PRD §3.3.

    N1 at exactly 10km from service, N2 at exactly 12km.
    Returns dict with service_item, n1, n2, patient_id.
    """
    service_item = create_service_item_raw(required_skill="IV_INFUSION")
    n1_lat = offset_lat_km(service_lat, 10.0)
    n2_lat = offset_lat_km(service_lat, 12.0)
    n1 = create_certified_nurse(
        home_lat=n1_lat, home_lng=service_lng,
        specialty_tags=["IV_INFUSION"],
    )
    n2 = create_certified_nurse(
        home_lat=n2_lat, home_lng=service_lng,
        specialty_tags=["IV_INFUSION"],
    )
    patient_id = stable_user_id("patient")
    return {
        "service_item": service_item,
        "n1": n1, "n2": n2,
        "patient_id": patient_id,
    }


def setup_settled_order_for_refund(
    *,
    base_price_cents: int = 20000,
    revenue_share_bps: int = 7000,
    completed_at_iso: Optional[str] = None,
) -> Dict[str, Any]:
    """Drive an Order through to COMPLETED with a known Settlement
    (FINALIZED). Used by refund tier-boundary tests.
    """
    setup = setup_completed_order(
        base_price_cents=base_price_cents,
        revenue_share_bps=revenue_share_bps,
        scheduled_start=DEFAULT_SCHEDULED_START_ISO,
        checkin_at=DEFAULT_SCHEDULED_START_ISO,
    )
    return setup
