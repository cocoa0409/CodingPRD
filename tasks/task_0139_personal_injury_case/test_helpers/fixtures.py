"""Composite setup helpers — multi-step preambles tests can reuse.

Most interesting test claims require the system to be in a late state
that takes 5-15 API calls to reach. Each fixture composes the lower-
level steps so the test body can focus on the rule under assertion.

IDENTITY THREADING — PRD §2.1:

    "All three roles use opaque identity semantics: X-User-ID is an
    opaque operator identifier and the server does not compare it to
    any entity's id for ownership purposes."

All three roles are OPAQUE; the shared *_headers constants are
canonical for routine calls. The single exception is the segregation-
of-duties check at disbursement approval (PRD §3.10): "the acting
user's X-User-ID must not equal Case.assigned_attorney_id". Fixtures
that set up a SETTLED case for disbursement always make
assigned_attorney_id = ATTORNEY_ID (the canonical attorney id), so a
ManagingPartner approving with MANAGING_PARTNER_ID (a different id)
naturally passes the SoD check, and a deliberately-bad approver call
can be built by minting ManagingPartner headers with X-User-ID equal
to the same attorney id via make_managing_partner_headers(ATTORNEY_ID).

Setup calls use get_success_data (a lenient 2xx validator), so a
failed setup surfaces as 'Setup failed' rather than a confusing test
assertion failure downstream.

CLOCK ANCHORING — PRD §3.6 exposes /_clock/now and /_clock/advance.
Tests anchor incident_date and scheduled_at to the server's logical
clock so the SoL math is consistent regardless of when the suite runs
or how much the clock has been advanced by earlier tests in the same
process.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    approve_disbursement_payload,
    case_costs_payload,
    clock_advance_payload,
    create_case_payload,
    create_client_payload,
    create_contingency_fee_payload,
    create_court_event_payload,
    create_damages_multiplier_payload,
    create_damages_per_diem_payload,
    create_demand_letter_payload,
    create_lien_payload,
    create_medical_record_request_payload,
    create_settlement_offer_payload,
    dismiss_payload,
    iso_utc,
    parse_iso,
    patch_court_event_payload,
    patch_damages_payload,
    patch_lien_payload,
    patch_medical_record_request_payload,
    patch_settlement_offer_payload,
    send_demand_letter_payload,
    toll_payload,
)
from .test_users import (
    ATTORNEY_ID,
    PARALEGAL_ID,
    TEST_USERS,
    make_managing_partner_headers,
)


# ===========================================================================
# Clock helpers — PRD §3.6
# ===========================================================================
def get_server_now_iso(headers: Optional[Dict[str, str]] = None) -> str:
    """GET /_clock/now — returns ISO 8601 string of server's logical
    clock. PRD §3.6: 'a read-only clock-now capability'.
    """
    headers = headers or TEST_USERS["managing_partner_headers"]
    resp = api_client.get_clock_now(headers)
    data = get_success_data(resp)
    # Server may return key as 'now' or under different name; try both.
    for k in ("now", "current_time", "server_time", "time"):
        if k in data:
            return data[k]
    # Fall back to whole payload if just a string
    if isinstance(data, str):
        return data
    raise AssertionError(f"Cannot find server time in clock-now response: {data!r}")


def server_now_dt() -> datetime:
    return parse_iso(get_server_now_iso())


def advance_clock_seconds(seconds: int) -> None:
    """POST /_clock/advance — moves logical clock forward by `seconds`."""
    headers = TEST_USERS["managing_partner_headers"]
    resp = api_client.advance_clock(
        clock_advance_payload(seconds), headers,
    )
    get_success_data(resp)


def advance_clock_to_iso(target_iso: str) -> None:
    """Advance the server's logical clock until it reaches target_iso.
    No-op if already past target.
    """
    now_dt = server_now_dt()
    target_dt = parse_iso(target_iso)
    delta = (target_dt - now_dt).total_seconds()
    if delta <= 0:
        return
    advance_clock_seconds(int(delta) + 1)


def advance_clock_days(days: int) -> None:
    """Move logical clock forward by `days` whole days."""
    advance_clock_seconds(days * 86400)


# ===========================================================================
# Date anchoring — pick incident_date based on server's logical clock so
# the case's SoL is far enough in the future for setup steps to succeed.
# PRD §3.3: "the case's sol_deadline is more than 30 days into the future
# at the moment of the request — paralegals cannot start records work on
# a case whose statute will mature within the next month".
# So we anchor incident_date to roughly (server_now - 90 days) which
# gives ~ (2 years - 90 days) of SoL headroom for CA AUTO cases.
# ===========================================================================
def recent_incident_date(days_ago: int = 90) -> str:
    """Return an incident_date that is `days_ago` days before the
    server's logical clock now. CA AUTO base_years=2 yields a
    sol_deadline ~ (2 years - 90 days) away — well past the 30-day
    records-work guard.
    """
    now_dt = server_now_dt()
    return (now_dt.date() - timedelta(days=days_ago)).isoformat()


def adult_dob_for(incident_date_iso: str, age_at_incident: int = 30) -> str:
    """Return a date_of_birth such that the client is `age_at_incident`
    years old on incident_date (adult by default)."""
    inc = date.fromisoformat(incident_date_iso)
    dob = inc.replace(year=inc.year - age_at_incident)
    return dob.isoformat()


def minor_dob_for(incident_date_iso: str, age_at_incident: int = 14) -> str:
    """Return a date_of_birth such that the client is a minor (<18) on
    incident_date."""
    inc = date.fromisoformat(incident_date_iso)
    dob = inc.replace(year=inc.year - age_at_incident)
    return dob.isoformat()


# ===========================================================================
# Client / Case primitives
# ===========================================================================
def create_client(
    headers: Optional[Dict[str, str]] = None,
    **overrides,
) -> Dict[str, Any]:
    """POST /clients. PRD §3.1."""
    headers = headers or TEST_USERS["paralegal_headers"]
    resp = api_client.create_client(
        create_client_payload(**overrides), headers,
    )
    return get_success_data(resp)


def create_case(
    client_id: str,
    *,
    assigned_attorney_id: Optional[str] = ATTORNEY_ID,
    assigned_paralegal_id: Optional[str] = PARALEGAL_ID,
    headers: Optional[Dict[str, str]] = None,
    **overrides,
) -> Dict[str, Any]:
    """POST /pi-cases. PRD §3.1.

    By default assigned_attorney_id = ATTORNEY_ID, so SoD check at
    disbursement passes when the approver is MANAGING_PARTNER_ID. A
    test that wants to assign the case to a custom attorney id (e.g.
    to set up a SoD positive case) passes assigned_attorney_id
    explicitly.
    """
    headers = headers or TEST_USERS["paralegal_headers"]
    extras: Dict[str, Any] = {}
    if assigned_attorney_id is not None:
        extras["assigned_attorney_id"] = assigned_attorney_id
    if assigned_paralegal_id is not None:
        extras["assigned_paralegal_id"] = assigned_paralegal_id
    extras.update(overrides)
    # Anchor incident_date to server logical clock if caller did not
    # pin one — keeps sol_deadline comfortably in the future so SoL
    # safety check does not pre-empt downstream state-advancing
    # mutations (PRD §2.10).
    if "incident_date" not in extras:
        extras["incident_date"] = recent_incident_date(days_ago=90)
    resp = api_client.create_case(
        create_case_payload(client_id, **extras), headers,
    )
    return get_success_data(resp)


def get_case(case_id: str) -> Dict[str, Any]:
    """GET /pi-cases/{id}."""
    resp = api_client.get_case(case_id, TEST_USERS["paralegal_headers"])
    return get_success_data(resp)


def create_contingency_fee(
    case_id: str,
    *,
    pre_suit_rate_bps: Optional[int] = None,
    post_suit_rate_bps: Optional[int] = None,
    trial_rate_bps: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /pi-cases/{cid}/contingency-fee. PRD §3.1."""
    headers = headers or TEST_USERS["managing_partner_headers"]
    overrides: Dict[str, Any] = {}
    if pre_suit_rate_bps is not None:
        overrides["pre_suit_rate_bps"] = pre_suit_rate_bps
    if post_suit_rate_bps is not None:
        overrides["post_suit_rate_bps"] = post_suit_rate_bps
    if trial_rate_bps is not None:
        overrides["trial_rate_bps"] = trial_rate_bps
    resp = api_client.create_contingency_fee(
        case_id, create_contingency_fee_payload(**overrides), headers,
    )
    return get_success_data(resp)


# ===========================================================================
# Tier 1: State Progression — Client + Case + Fee through INTAKE
# ===========================================================================
def setup_case_with_fee(
    *,
    jurisdiction_state: str = "CA",
    incident_type: str = "AUTO",
    incident_date: Optional[str] = None,
    is_minor: bool = False,
    assigned_attorney_id: Optional[str] = ATTORNEY_ID,
    pre_suit_rate_bps: Optional[int] = None,
    post_suit_rate_bps: Optional[int] = None,
    trial_rate_bps: Optional[int] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Create a Client + Case + ContingencyFeeAgreement, ready for
    records work. Returns (client, case, fee).

    Case is in INTAKE; fee is recorded. incident_date defaults to
    `recent_incident_date()` (90 days before server now), so the
    sol_deadline is comfortably in the future.
    """
    if incident_date is None:
        incident_date = recent_incident_date(days_ago=90)
    dob = (minor_dob_for if is_minor else adult_dob_for)(incident_date)
    client = create_client(
        date_of_birth=dob, state_of_residence=jurisdiction_state,
    )
    case = create_case(
        client["id"],
        incident_date=incident_date,
        incident_type=incident_type,
        jurisdiction_state=jurisdiction_state,
        assigned_attorney_id=assigned_attorney_id,
    )
    fee = create_contingency_fee(
        case["id"],
        pre_suit_rate_bps=pre_suit_rate_bps,
        post_suit_rate_bps=post_suit_rate_bps,
        trial_rate_bps=trial_rate_bps,
    )
    return client, case, fee


# ===========================================================================
# Medical record request primitives
# ===========================================================================
def create_med_request(
    case_id: str,
    *,
    provider_name: Optional[str] = None,
    date_of_service_start: Optional[str] = None,
    date_of_service_end: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["paralegal_headers"]
    overrides: Dict[str, Any] = {}
    if provider_name is not None:
        overrides["provider_name"] = provider_name
    if date_of_service_start is not None:
        overrides["date_of_service_start"] = date_of_service_start
    if date_of_service_end is not None:
        overrides["date_of_service_end"] = date_of_service_end
    resp = api_client.create_medical_record_request(
        case_id,
        create_medical_record_request_payload(**overrides),
        headers,
    )
    return get_success_data(resp)


def send_med_request(case_id: str, request_id: str,
                     headers: Optional[Dict[str, str]] = None,
                     ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["paralegal_headers"]
    resp = api_client.send_medical_record_request(
        case_id, request_id, headers,
    )
    return get_success_data(resp)


def receive_med_request(
    case_id: str, request_id: str, billed_amount_cents: int,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["paralegal_headers"]
    resp = api_client.patch_medical_record_request(
        case_id, request_id,
        patch_medical_record_request_payload(
            "RECEIVED", billed_amount_cents=billed_amount_cents,
        ),
        headers,
    )
    return get_success_data(resp)


def reject_med_request(case_id: str, request_id: str,
                       headers: Optional[Dict[str, str]] = None,
                       ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["paralegal_headers"]
    resp = api_client.patch_medical_record_request(
        case_id, request_id,
        patch_medical_record_request_payload("REJECTED"),
        headers,
    )
    return get_success_data(resp)


# ===========================================================================
# Damages primitives
# ===========================================================================
def create_damages_multiplier(
    case_id: str,
    *,
    lost_wages_cents: int = 0,
    property_damage_cents: int = 0,
    multiplier_value: float = 1.5,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["paralegal_headers"]
    resp = api_client.create_damages(
        case_id,
        create_damages_multiplier_payload(
            lost_wages_cents=lost_wages_cents,
            property_damage_cents=property_damage_cents,
            multiplier_value=multiplier_value,
        ),
        headers,
    )
    return get_success_data(resp)


def create_damages_per_diem(
    case_id: str,
    per_diem_rate_cents: int,
    per_diem_days: int,
    *,
    lost_wages_cents: int = 0,
    property_damage_cents: int = 0,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["paralegal_headers"]
    resp = api_client.create_damages(
        case_id,
        create_damages_per_diem_payload(
            per_diem_rate_cents=per_diem_rate_cents,
            per_diem_days=per_diem_days,
            lost_wages_cents=lost_wages_cents,
            property_damage_cents=property_damage_cents,
        ),
        headers,
    )
    return get_success_data(resp)


def patch_damages_to_per_diem(
    case_id: str, per_diem_rate_cents: int, per_diem_days: int,
    *, version: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["paralegal_headers"]
    body: Dict[str, Any] = {
        "pain_suffering_method": "PER_DIEM",
        "per_diem_rate_cents": per_diem_rate_cents,
        "per_diem_days": per_diem_days,
    }
    resp = api_client.patch_damages(
        case_id, patch_damages_payload(version=version, **body), headers,
    )
    return get_success_data(resp)


def get_damages(case_id: str) -> Dict[str, Any]:
    resp = api_client.get_damages(case_id, TEST_USERS["paralegal_headers"])
    return get_success_data(resp)


# ===========================================================================
# Lien primitives
# ===========================================================================
def create_lien(
    case_id: str, lien_type: str, face_amount_cents: int,
    *, lienholder_name: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["paralegal_headers"]
    resp = api_client.create_lien(
        case_id,
        create_lien_payload(lien_type, face_amount_cents, lienholder_name),
        headers,
    )
    return get_success_data(resp)


def negotiate_then_reduce_lien(
    case_id: str, lien_id: str, negotiated_amount_cents: int,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Drive a non-statutory lien ASSERTED → NEGOTIATING → REDUCED.

    PRD §3.8: 'a Paralegal opens negotiation by invoking the negotiate
    action against the lien, which moves it from ASSERTED to
    NEGOTIATING. A subsequent patch supplying negotiated_amount_cents
    ... moves the lien from NEGOTIATING to REDUCED.'
    """
    headers = headers or TEST_USERS["paralegal_headers"]
    api_client.negotiate_lien(case_id, lien_id, headers)
    resp = api_client.patch_lien(
        case_id, lien_id,
        patch_lien_payload(negotiated_amount_cents=negotiated_amount_cents),
        headers,
    )
    return get_success_data(resp)


def dispute_lien(case_id: str, lien_id: str,
                 headers: Optional[Dict[str, str]] = None,
                 ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["attorney_headers"]
    resp = api_client.dispute_lien(case_id, lien_id, headers)
    return get_success_data(resp)


# ===========================================================================
# Demand letter primitives
# ===========================================================================
def create_demand_letter(
    case_id: str, demanded_amount_cents: int,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["attorney_headers"]
    resp = api_client.create_demand_letter(
        case_id, create_demand_letter_payload(demanded_amount_cents),
        headers,
    )
    return get_success_data(resp)


def send_demand_letter(
    case_id: str, letter_id: str,
    *, expected_damages_version: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["attorney_headers"]
    body = send_demand_letter_payload(
        expected_damages_version=expected_damages_version,
    )
    resp = api_client.send_demand_letter(
        case_id, letter_id, headers, body,
    )
    return get_success_data(resp)


# ===========================================================================
# Settlement offer primitives
# ===========================================================================
def create_offer(
    case_id: str, offer_party: str, amount_cents: int,
    *, expires_at: Optional[str] = None,
    predecessor_offer_id: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["attorney_headers"]
    if expires_at is None:
        # 7 days in the server's future
        now_dt = server_now_dt()
        expires_at = iso_utc(now_dt + timedelta(days=7))
    resp = api_client.create_settlement_offer(
        case_id,
        create_settlement_offer_payload(
            offer_party, amount_cents, expires_at,
            predecessor_offer_id=predecessor_offer_id,
        ),
        headers,
    )
    return get_success_data(resp)


def accept_offer(
    case_id: str, offer_id: str,
    *, version: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["attorney_headers"]
    resp = api_client.patch_settlement_offer(
        case_id, offer_id,
        patch_settlement_offer_payload("ACCEPTED", version=version),
        headers,
    )
    return get_success_data(resp)


# ===========================================================================
# Court event primitives
# ===========================================================================
def create_court_event(
    case_id: str, event_type: str, scheduled_at: str,
    duration_minutes: int,
    *, courtroom: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["attorney_headers"]
    resp = api_client.create_court_event(
        case_id,
        create_court_event_payload(
            event_type, scheduled_at, duration_minutes, courtroom=courtroom,
        ),
        headers,
    )
    return get_success_data(resp)


def complete_court_event_with_judgment(
    case_id: str, event_id: str, award_amount_cents: int,
    *, version: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["attorney_headers"]
    resp = api_client.patch_court_event(
        case_id, event_id,
        patch_court_event_payload(
            status="COMPLETED",
            award_amount_cents=award_amount_cents,
            version=version,
        ),
        headers,
    )
    return get_success_data(resp)


# ===========================================================================
# Case-management primitives
# ===========================================================================
def patch_case_costs(
    case_id: str, new_costs_cents: int,
    *, version: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["attorney_headers"]
    resp = api_client.patch_case_costs(
        case_id, case_costs_payload(new_costs_cents, version=version),
        headers,
    )
    return get_success_data(resp)


def toll_case(
    case_id: str, additional_days: int, reason: str = "incapacity",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["managing_partner_headers"]
    resp = api_client.toll_case(
        case_id, toll_payload(additional_days, reason), headers,
    )
    return get_success_data(resp)


def dismiss_case(
    case_id: str, reason: str = "client withdrew",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["managing_partner_headers"]
    resp = api_client.dismiss_case(
        case_id, dismiss_payload(reason), headers,
    )
    return get_success_data(resp)


def approve_disbursement(
    case_id: str, strategy: str,
    *, headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /pi-cases/{id}/disbursement/approve. PRD §3.10."""
    headers = headers or TEST_USERS["managing_partner_headers"]
    resp = api_client.approve_disbursement(
        case_id, approve_disbursement_payload(strategy), headers,
    )
    return get_success_data(resp)


# ===========================================================================
# Tier 2: Hierarchy progression — drive Case through state machine
# ===========================================================================
def setup_records_pending(
    *,
    jurisdiction_state: str = "CA",
    incident_type: str = "AUTO",
    incident_date: Optional[str] = None,
    is_minor: bool = False,
    assigned_attorney_id: Optional[str] = ATTORNEY_ID,
    pre_suit_rate_bps: Optional[int] = None,
    post_suit_rate_bps: Optional[int] = None,
    trial_rate_bps: Optional[int] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Drive a case to RECORDS_PENDING by creating one DRAFT
    MedicalRecordRequest. Returns (client, case, fee, request).
    """
    client, case, fee = setup_case_with_fee(
        jurisdiction_state=jurisdiction_state,
        incident_type=incident_type,
        incident_date=incident_date,
        is_minor=is_minor,
        assigned_attorney_id=assigned_attorney_id,
        pre_suit_rate_bps=pre_suit_rate_bps,
        post_suit_rate_bps=post_suit_rate_bps,
        trial_rate_bps=trial_rate_bps,
    )
    # Use incident_date + 1 day as service start so DOS >= incident_date.
    inc = date.fromisoformat(case["incident_date"])
    request = create_med_request(
        case["id"],
        date_of_service_start=(inc + timedelta(days=1)).isoformat(),
        date_of_service_end=(inc + timedelta(days=30)).isoformat(),
    )
    return client, case, fee, request


def setup_ready_for_demand(
    *,
    billed_amount_cents: int = 1_000_000,
    multiplier_value: float = 2.0,
    lost_wages_cents: int = 0,
    property_damage_cents: int = 0,
    jurisdiction_state: str = "CA",
    incident_type: str = "AUTO",
    incident_date: Optional[str] = None,
    assigned_attorney_id: Optional[str] = ATTORNEY_ID,
    pre_suit_rate_bps: Optional[int] = None,
    post_suit_rate_bps: Optional[int] = None,
    trial_rate_bps: Optional[int] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Drive a case to READY_FOR_DEMAND. Returns
    (client, case, fee, request, damages).

    Sequence:
      INTAKE → records request created → status RECORDS_PENDING.
      Damages MULTIPLIER row created.
      Records request SENT then RECEIVED with billed_amount_cents.
      Case status flips to READY_FOR_DEMAND.
    """
    client, case, fee, request = setup_records_pending(
        jurisdiction_state=jurisdiction_state,
        incident_type=incident_type,
        incident_date=incident_date,
        assigned_attorney_id=assigned_attorney_id,
        pre_suit_rate_bps=pre_suit_rate_bps,
        post_suit_rate_bps=post_suit_rate_bps,
        trial_rate_bps=trial_rate_bps,
    )
    damages = create_damages_multiplier(
        case["id"],
        lost_wages_cents=lost_wages_cents,
        property_damage_cents=property_damage_cents,
        multiplier_value=multiplier_value,
    )
    send_med_request(case["id"], request["id"])
    request = receive_med_request(
        case["id"], request["id"], billed_amount_cents=billed_amount_cents,
    )
    damages = get_damages(case["id"])
    return client, case, fee, request, damages


def setup_demand_sent(
    *,
    demanded_amount_cents: Optional[int] = None,
    **kwargs,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Drive a case to DEMAND_SENT. Returns
    (client, case, fee, request, damages, letter).
    """
    client, case, fee, request, damages = setup_ready_for_demand(**kwargs)
    if demanded_amount_cents is None:
        demanded_amount_cents = damages["total_damages_cents"]
    letter = create_demand_letter(case["id"], demanded_amount_cents)
    letter = send_demand_letter(case["id"], letter["id"])
    return client, case, fee, request, damages, letter


def setup_negotiating(
    *,
    defendant_offer_amount_cents: int = 5_000_000,
    **kwargs,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Drive a case to NEGOTIATING by posting the first DEFENDANT offer.
    Returns (client, case, fee, request, damages, letter, offer).
    """
    client, case, fee, request, damages, letter = setup_demand_sent(**kwargs)
    offer = create_offer(
        case["id"], "DEFENDANT", defendant_offer_amount_cents,
    )
    return client, case, fee, request, damages, letter, offer


def setup_settled(
    *,
    gross_settlement_cents: int = 10_000_000,
    case_costs_cents: int = 0,
    pre_suit_rate_bps: Optional[int] = None,
    post_suit_rate_bps: Optional[int] = None,
    trial_rate_bps: Optional[int] = None,
    assigned_attorney_id: Optional[str] = ATTORNEY_ID,
    jurisdiction_state: str = "CA",
    incident_type: str = "AUTO",
    incident_date: Optional[str] = None,
    billed_amount_cents: int = 1_000_000,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Drive a case to SETTLED via the NEGOTIATING route (pre-suit
    contingency tier). Returns (client, case, fee, damages, offer).

    Cascade: client→case (with fee)→records request→damages→send
    request→receive request→demand letter→send demand letter→defendant
    offer (Case → NEGOTIATING)→accept (Case → SETTLED with
    gross_settlement_cents = offer.amount_cents).

    If case_costs_cents > 0, costs are patched after settlement.
    """
    client, case, fee, request, damages, letter, defendant_offer = setup_negotiating(
        defendant_offer_amount_cents=gross_settlement_cents,
        pre_suit_rate_bps=pre_suit_rate_bps,
        post_suit_rate_bps=post_suit_rate_bps,
        trial_rate_bps=trial_rate_bps,
        assigned_attorney_id=assigned_attorney_id,
        jurisdiction_state=jurisdiction_state,
        incident_type=incident_type,
        incident_date=incident_date,
        billed_amount_cents=billed_amount_cents,
    )
    accepted_offer = accept_offer(case["id"], defendant_offer["id"])
    if case_costs_cents > 0:
        patch_case_costs(case["id"], case_costs_cents)
    # Re-fetch case to capture SETTLED status + gross_settlement_cents.
    case = get_case(case["id"])
    return client, case, fee, damages, accepted_offer


# ===========================================================================
# Tier 3: Disbursement scenarios — the most multi-step setups
# ===========================================================================
def setup_settled_with_liens(
    *,
    gross_settlement_cents: int = 10_000_000,
    case_costs_cents: int = 250_000,
    pre_suit_rate_bps: Optional[int] = None,
    medicare_face_cents: Optional[int] = None,
    provider_negotiated_face_cents: Optional[int] = None,
    provider_negotiated_reduced_to_cents: Optional[int] = None,
    extra_liens: Optional[List[Dict[str, Any]]] = None,
    assigned_attorney_id: Optional[str] = ATTORNEY_ID,
    jurisdiction_state: str = "CA",
    incident_type: str = "AUTO",
    incident_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a SETTLED case with liens ready for disbursement.

    Returns a dict with keys: client, case, fee, damages, offer, liens
    (list of {lien, label}).

    `extra_liens` is a list of dicts each with keys:
      lien_type:str, face_amount_cents:int,
      negotiated_amount_cents:Optional[int],
      dispute:bool (default false)
    Provider/non-statutory entries with negotiated_amount_cents set
    are driven through ASSERTED → NEGOTIATING → REDUCED before return.
    """
    client, case, fee, damages, accepted_offer = setup_settled(
        gross_settlement_cents=gross_settlement_cents,
        case_costs_cents=case_costs_cents,
        pre_suit_rate_bps=pre_suit_rate_bps,
        assigned_attorney_id=assigned_attorney_id,
        jurisdiction_state=jurisdiction_state,
        incident_type=incident_type,
        incident_date=incident_date,
    )

    # Important: liens may only be added after case exists. PRD §3.8
    # does NOT restrict the case state for lien creation, so creation
    # works in SETTLED.
    lien_rows: List[Dict[str, Any]] = []

    if medicare_face_cents is not None:
        med = create_lien(
            case["id"], "MEDICARE", medicare_face_cents,
            lienholder_name="Medicare",
        )
        lien_rows.append({"label": "MEDICARE", "lien": med})

    if provider_negotiated_face_cents is not None:
        prov = create_lien(
            case["id"], "PROVIDER_NEGOTIATED", provider_negotiated_face_cents,
            lienholder_name="Provider Negotiated",
        )
        if provider_negotiated_reduced_to_cents is not None:
            prov = negotiate_then_reduce_lien(
                case["id"], prov["id"],
                provider_negotiated_reduced_to_cents,
            )
        lien_rows.append({"label": "PROVIDER_NEGOTIATED", "lien": prov})

    for spec in (extra_liens or []):
        lien_type = spec["lien_type"]
        face = spec["face_amount_cents"]
        l = create_lien(
            case["id"], lien_type, face,
            lienholder_name=spec.get("lienholder_name") or lien_type.title(),
        )
        if spec.get("dispute"):
            l = dispute_lien(case["id"], l["id"])
        elif spec.get("negotiated_amount_cents") is not None:
            l = negotiate_then_reduce_lien(
                case["id"], l["id"], spec["negotiated_amount_cents"],
            )
        lien_rows.append({"label": lien_type, "lien": l})

    return {
        "client": client,
        "case": case,
        "fee": fee,
        "damages": damages,
        "offer": accepted_offer,
        "liens": lien_rows,
    }


# ===========================================================================
# Tier 3: LITIGATION-route SETTLED — post-suit contingency tier
# ===========================================================================
def setup_settled_via_litigation(
    *,
    gross_settlement_cents: int = 10_000_000,
    case_costs_cents: int = 250_000,
    pre_suit_rate_bps: Optional[int] = None,
    post_suit_rate_bps: Optional[int] = None,
    trial_rate_bps: Optional[int] = None,
    assigned_attorney_id: Optional[str] = ATTORNEY_ID,
    jurisdiction_state: str = "CA",
    incident_type: str = "AUTO",
    incident_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Drive a case to SETTLED through LITIGATION (Case.filed_in_court
    == true), producing post-suit attorney-fee tier at disbursement.

    Path: DEMAND_SENT → NEGOTIATING (defendant offer) → COMPLAINT_FILED
    court event → LITIGATION → second defendant offer → ACCEPT → SETTLED.
    """
    client, case, fee, request, damages, letter, first_offer = setup_negotiating(
        defendant_offer_amount_cents=gross_settlement_cents // 2,
        pre_suit_rate_bps=pre_suit_rate_bps,
        post_suit_rate_bps=post_suit_rate_bps,
        trial_rate_bps=trial_rate_bps,
        assigned_attorney_id=assigned_attorney_id,
        jurisdiction_state=jurisdiction_state,
        incident_type=incident_type,
        incident_date=incident_date,
    )

    # Now file a complaint while NEGOTIATING — case → LITIGATION,
    # filed_in_court flips to true, PENDING offers (here the first one)
    # are WITHDRAWN.
    now_dt = server_now_dt()
    scheduled_at = iso_utc(now_dt + timedelta(days=14))
    create_court_event(
        case["id"], "COMPLAINT_FILED",
        scheduled_at=scheduled_at, duration_minutes=30,
    )
    # Issue a new defendant offer (the case is in LITIGATION now), then
    # accept it. Per PRD §3.6: 'Acceptance after the case has already
    # entered LITIGATION follows the same four-hop cascade, but the
    # contingency tier that will later apply at disbursement is the
    # post-suit tier rather than the pre-suit tier.'
    second_offer = create_offer(
        case["id"], "DEFENDANT", gross_settlement_cents,
    )
    accept_offer(case["id"], second_offer["id"])

    if case_costs_cents > 0:
        patch_case_costs(case["id"], case_costs_cents)

    case = get_case(case["id"])
    damages = get_damages(case["id"])
    return {
        "client": client,
        "case": case,
        "fee": fee,
        "damages": damages,
        "request": request,
        "letter": letter,
    }


# ===========================================================================
# Tier 4: Trial-awarded shortcut
# ===========================================================================
def setup_trial_awarded(
    *,
    award_amount_cents: int = 10_000_000,
    case_costs_cents: int = 250_000,
    pre_suit_rate_bps: Optional[int] = None,
    post_suit_rate_bps: Optional[int] = None,
    trial_rate_bps: Optional[int] = None,
    assigned_attorney_id: Optional[str] = ATTORNEY_ID,
    jurisdiction_state: str = "CA",
    incident_type: str = "AUTO",
    incident_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Drive a case to TRIAL_AWARDED via LITIGATION → JUDGMENT.

    Cascade: NEGOTIATING → COMPLAINT_FILED → LITIGATION → JUDGMENT
    court event → advance clock to scheduled_at → mark COMPLETED with
    award_amount_cents > 0 → TRIAL_AWARDED.
    """
    client, case, fee, request, damages, letter, first_offer = setup_negotiating(
        defendant_offer_amount_cents=award_amount_cents // 2,
        pre_suit_rate_bps=pre_suit_rate_bps,
        post_suit_rate_bps=post_suit_rate_bps,
        trial_rate_bps=trial_rate_bps,
        assigned_attorney_id=assigned_attorney_id,
        jurisdiction_state=jurisdiction_state,
        incident_type=incident_type,
        incident_date=incident_date,
    )
    now_dt = server_now_dt()
    complaint_at = iso_utc(now_dt + timedelta(days=14))
    create_court_event(
        case["id"], "COMPLAINT_FILED",
        scheduled_at=complaint_at, duration_minutes=30,
    )
    # Schedule the JUDGMENT for soon and advance the clock past it.
    judgment_at_dt = now_dt + timedelta(days=30)
    judgment_event = create_court_event(
        case["id"], "JUDGMENT",
        scheduled_at=iso_utc(judgment_at_dt), duration_minutes=60,
    )
    # Advance server clock to just after judgment_at so COMPLETED can fire.
    advance_clock_to_iso(iso_utc(judgment_at_dt + timedelta(minutes=1)))
    complete_court_event_with_judgment(
        case["id"], judgment_event["id"], award_amount_cents,
    )

    if case_costs_cents > 0:
        patch_case_costs(case["id"], case_costs_cents)

    case = get_case(case["id"])
    return {
        "client": client,
        "case": case,
        "fee": fee,
        "damages": damages,
        "judgment_event": judgment_event,
    }


# ===========================================================================
# Tier 5: Demand-sent cases for branching tests (DEMAND_SENT_TO_*)
# ===========================================================================
def setup_two_demand_sent_cases() -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Build two parallel cases in DEMAND_SENT for branching tests.
    Returns (case_a, letter_a, case_b, letter_b)."""
    _, case_a, _, _, _, letter_a = setup_demand_sent()
    _, case_b, _, _, _, letter_b = setup_demand_sent()
    return case_a, letter_a, case_b, letter_b


# ===========================================================================
# Tier 6: Negotiation chains
# ===========================================================================
def setup_negotiation_chain(
    *,
    first_offer_amount_cents: int = 5_000_000,
    second_offer_amount_cents: int = 8_000_000,
    third_offer_amount_cents: int = 6_000_000,
) -> Dict[str, Any]:
    """Drive a case to NEGOTIATING with three offers chained as
    O1 (DEFENDANT) → O2 (PLAINTIFF, predecessor=O1) → O3 (DEFENDANT,
    predecessor=O2). After creation: O1.status==COUNTERED,
    O2.status==COUNTERED, O3.status==PENDING.
    """
    client, case, fee, request, damages, letter, o1 = setup_negotiating(
        defendant_offer_amount_cents=first_offer_amount_cents,
    )
    o2 = create_offer(
        case["id"], "PLAINTIFF", second_offer_amount_cents,
        predecessor_offer_id=o1["id"],
    )
    o3 = create_offer(
        case["id"], "DEFENDANT", third_offer_amount_cents,
        predecessor_offer_id=o2["id"],
    )
    return {
        "client": client, "case": case, "fee": fee,
        "letter": letter, "damages": damages,
        "o1": o1, "o2": o2, "o3": o3,
    }


# ===========================================================================
# Tier 7: Pending offers in NEGOTIATING ready for cascade test
# ===========================================================================
def setup_negotiating_with_two_pending_offers() -> Dict[str, Any]:
    """Drive case to NEGOTIATING and add another DEFENDANT offer so
    there are two PENDING offers (O1 countered by O2 plaintiff, then
    O3 defendant pending — but the difficulty design instance asks for
    the COUNTERED-then-new-DEFENDANT-pending shape).

    Returns dict with case, o1 (COUNTERED), o3 (PENDING).
    """
    client, case, fee, request, damages, letter, o1 = setup_negotiating(
        defendant_offer_amount_cents=5_000_000,
    )
    # Counter from PLAINTIFF (o2 created so o1 → COUNTERED)
    o2 = create_offer(
        case["id"], "PLAINTIFF", 8_000_000,
        predecessor_offer_id=o1["id"],
    )
    # New DEFENDANT offer counter to o2 — o2 → COUNTERED, o3 → PENDING
    o3 = create_offer(
        case["id"], "DEFENDANT", 6_000_000,
        predecessor_offer_id=o2["id"],
    )
    return {
        "client": client, "case": case, "fee": fee,
        "letter": letter, "damages": damages,
        "o1": o1, "o2": o2, "o3": o3,
    }


__all__ = [
    # Clock
    "get_server_now_iso", "server_now_dt", "advance_clock_seconds",
    "advance_clock_to_iso", "advance_clock_days",
    # Date helpers
    "recent_incident_date", "adult_dob_for", "minor_dob_for",
    # Primitives
    "create_client", "create_case", "get_case", "create_contingency_fee",
    "create_med_request", "send_med_request", "receive_med_request",
    "reject_med_request",
    "create_damages_multiplier", "create_damages_per_diem",
    "patch_damages_to_per_diem", "get_damages",
    "create_lien", "negotiate_then_reduce_lien", "dispute_lien",
    "create_demand_letter", "send_demand_letter",
    "create_offer", "accept_offer",
    "create_court_event", "complete_court_event_with_judgment",
    "patch_case_costs", "toll_case", "dismiss_case",
    "approve_disbursement",
    # Tier 1+
    "setup_case_with_fee",
    "setup_records_pending",
    "setup_ready_for_demand",
    "setup_demand_sent",
    "setup_negotiating",
    "setup_settled",
    "setup_settled_with_liens",
    "setup_settled_via_litigation",
    "setup_trial_awarded",
    "setup_two_demand_sent_cases",
    "setup_negotiation_chain",
    "setup_negotiating_with_two_pending_offers",
]
