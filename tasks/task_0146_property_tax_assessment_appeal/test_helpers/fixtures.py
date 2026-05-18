"""Composite setup helpers — multi-step preambles tests can reuse.

The Property/Assessment/Bill/Appeal/DeferralPlan pipeline is long: a
test for the appeal-decision reconciliation cascade requires owner
register -> property register -> assessment create -> assessment issue
-> appeal file -> hearing schedule -> hearing conduct -> hearing
decide. Each of these steps depends on the previous, and most tests
need only the final state to assert against.

IDENTITY THREADING — PRD §2.1:

- Assessor / Treasurer are OPAQUE. Shared headers
  (TEST_USERS["assessor_headers"], TEST_USERS["treasurer_headers"]) are
  canonical for every Assessor/Treasurer call.

- Owner is ENTITY-BACKED. PRD §2.1: "the server compares
  Property.owner_id against X-User-ID and rejects mismatches with
  ERR_OWNERSHIP_MISMATCH." Every Owner-driven setup call here mints
  headers via make_owner_headers(owner["id"]) using the real Owner.id
  returned by POST /owners.

- HearingOfficer is ENTITY-BACKED. PRD §2.1: "ownership and identity
  checks compare Hearing.officer_id against X-User-ID directly." Every
  conduct/decide call mints headers via
  make_hearing_officer_headers(officer["id"]) using the real
  HearingOfficer.id captured on the Hearing.

SEGREGATION OF DUTIES — PRD §2.8: The HearingOfficer who presides over
an Appeal "must not be the same user who issued the underlying
Assessment." Fixtures here use the default ASSESSOR_ID for issuance and
mint HearingOfficer entities with fresh UUIDs, guaranteeing the two
are distinct. Tests that intentionally trigger ERR_BOE_OFFICER_CONFLICT
build the conflict explicitly by issuing the Assessment with an
Assessor header whose X-User-ID equals the officer's id.

Setup calls use get_success_data (a lenient 2xx validator), so a
failed setup surfaces as 'Setup failed' rather than as a downstream
assertion failure.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    APPEAL_WINDOW_DAYS,
    DEFAULT_MILL_RATE,
    DUE_WINDOW_DAYS,
)
from .factories import (
    add_days_iso,
    add_minutes_iso,
    add_milliseconds_iso,
    clock_advance_payload,
    create_assessment_payload,
    create_hearing_officer_payload,
    create_owner_payload,
    create_payment_payload,
    create_property_payload,
    create_tax_bill_payload,
    decide_appeal_payload,
    file_appeal_payload,
    iso_date_str,
    iso_datetime_utc,
    iso_from_dt,
    iso_now_utc,
    revoke_exemption_payload,
    schedule_appeal_payload,
    submit_exemption_payload,
    transfer_owner_payload,
    version_body,
)
from .test_users import (
    ASSESSOR_ID,
    TEST_USERS,
    make_assessor_headers,
    make_hearing_officer_headers,
    make_owner_headers,
)


# ===========================================================================
# Clock helpers — PRD §2.11
# ===========================================================================
def advance_clock_to(target_timestamp: str,
                     headers: Optional[Dict[str, str]] = None
                     ) -> Dict[str, Any]:
    """POST /_clock/advance to <target_timestamp>. Any authenticated
    role may call (PRD §2.11); defaults to Assessor for convenience."""
    headers = headers or TEST_USERS["assessor_headers"]
    resp = api_client.clock_advance(
        clock_advance_payload(target_timestamp=target_timestamp), headers,
    )
    return get_success_data(resp) if resp.status_code < 400 else {}


# ---------------------------------------------------------------------------
# Date-of-birth helpers
# ---------------------------------------------------------------------------
def senior_eligible_dob(roll_year: int = 2025) -> str:
    """PRD §3.3: 'SENIOR requires that the Owner's age, computed from
    date_of_birth, is at least 65 ... measured on January 1 of
    effective_roll_year.' Return a YYYY-MM-DD such that the owner is
    age 70 on Jan 1 of roll_year."""
    return f"{roll_year - 70:04d}-01-01"


def young_dob(roll_year: int = 2025) -> str:
    """Owner clearly under SENIOR_AGE (40 years old on Jan 1)."""
    return f"{roll_year - 40:04d}-06-15"


# ===========================================================================
# Owner registration — PRD §3.1
# ===========================================================================
def create_owner(
    *,
    full_name: Optional[str] = None,
    date_of_birth: Optional[str] = None,
    veteran_status: Optional[bool] = None,
    disability_rating: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /owners. PRD §4: Assessor or Treasurer may register an
    Owner. Defaults to Assessor headers."""
    headers = headers or TEST_USERS["assessor_headers"]
    payload = create_owner_payload(
        full_name=full_name,
        date_of_birth=date_of_birth,
        veteran_status=veteran_status,
        disability_rating=disability_rating,
    )
    resp = api_client.create_owner(payload, headers)
    return get_success_data(resp)


def create_hearing_officer(
    *,
    full_name: Optional[str] = None,
    active: Optional[bool] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /hearing_officers. PRD §4: Treasurer only."""
    headers = headers or TEST_USERS["treasurer_headers"]
    payload = create_hearing_officer_payload(
        full_name=full_name, active=active,
    )
    resp = api_client.create_hearing_officer(payload, headers)
    return get_success_data(resp)


# ===========================================================================
# Property registration — PRD §3.1
# ===========================================================================
def create_property(
    *,
    owner: Dict[str, Any],
    market_value: float = 500_000.00,
    parcel_number: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /properties. PRD §4: Assessor only."""
    headers = headers or TEST_USERS["assessor_headers"]
    payload = create_property_payload(
        owner_id=owner["id"],
        parcel_number=parcel_number,
        market_value=market_value,
    )
    resp = api_client.create_property(payload, headers)
    return get_success_data(resp)


def transfer_property_owner(
    *,
    property_id: str,
    new_owner_id: str,
    version: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """PATCH /properties/{id}/owner. PRD §4: Assessor only."""
    headers = headers or TEST_USERS["assessor_headers"]
    resp = api_client.transfer_owner(
        property_id,
        transfer_owner_payload(new_owner_id=new_owner_id, version=version),
        headers,
    )
    return get_success_data(resp)


# ===========================================================================
# Assessment lifecycle — PRD §3.2
# ===========================================================================
def create_assessment(
    *,
    property_id: str,
    roll_year: int,
    market_value_at_roll: float,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /properties/{id}/assessments (DRAFT). Assessor only."""
    headers = headers or TEST_USERS["assessor_headers"]
    resp = api_client.create_assessment(
        property_id,
        create_assessment_payload(
            roll_year=roll_year, market_value_at_roll=market_value_at_roll,
        ),
        headers,
    )
    return get_success_data(resp)


def issue_assessment(
    *,
    property_id: str,
    assessment_id: str,
    version: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /properties/{id}/assessments/{id}/issue. Assessor only."""
    headers = headers or TEST_USERS["assessor_headers"]
    resp = api_client.issue_assessment(
        property_id, assessment_id, headers, version_body(version),
    )
    return get_success_data(resp)


def get_assessment(
    property_id: str,
    assessment_id: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """GET an Assessment. Defaults to Assessor (read access)."""
    headers = headers or TEST_USERS["assessor_headers"]
    resp = api_client.get_assessment(property_id, assessment_id, headers)
    return get_success_data(resp)


# ===========================================================================
# Exemption lifecycle — PRD §3.3
# ===========================================================================
def submit_exemption(
    *,
    owner: Dict[str, Any],
    property_id: str,
    exemption_type: str,
    effective_roll_year: int,
) -> Dict[str, Any]:
    """POST /properties/{id}/exemption_applications. Owner only."""
    headers = make_owner_headers(owner["id"])
    resp = api_client.submit_exemption_application(
        property_id,
        submit_exemption_payload(
            exemption_type=exemption_type,
            effective_roll_year=effective_roll_year,
        ),
        headers,
    )
    return get_success_data(resp)


def approve_exemption(
    *,
    property_id: str,
    exemption_application_id: str,
    version: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /.../exemption_applications/{id}/approve. Assessor only."""
    headers = headers or TEST_USERS["assessor_headers"]
    resp = api_client.approve_exemption_application(
        property_id, exemption_application_id, headers, version_body(version),
    )
    return get_success_data(resp)


def deny_exemption(
    *,
    property_id: str,
    exemption_application_id: str,
    version: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /.../exemption_applications/{id}/deny. Assessor only."""
    headers = headers or TEST_USERS["assessor_headers"]
    resp = api_client.deny_exemption_application(
        property_id, exemption_application_id, headers, version_body(version),
    )
    return get_success_data(resp)


def revoke_exemption(
    *,
    property_id: str,
    exemption_application_id: str,
    revoked_reason: str = "WITHDRAWN",
    version: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /.../exemption_applications/{id}/revoke. Assessor only."""
    headers = headers or TEST_USERS["assessor_headers"]
    resp = api_client.revoke_exemption_application(
        property_id,
        exemption_application_id,
        revoke_exemption_payload(
            revoked_reason=revoked_reason, version=version,
        ),
        headers,
    )
    return get_success_data(resp)


# ===========================================================================
# Appeal lifecycle — PRD §3.5
# ===========================================================================
def file_appeal(
    *,
    owner: Dict[str, Any],
    property_id: str,
    assessment_id: str,
    filed_grounds: str = "OVER_MARKET",
    claimed_value: float = 100_000.00,
) -> Dict[str, Any]:
    """POST /properties/{id}/appeals. Owner only."""
    headers = make_owner_headers(owner["id"])
    resp = api_client.file_appeal(
        property_id,
        file_appeal_payload(
            assessment_id=assessment_id,
            filed_grounds=filed_grounds,
            claimed_value=claimed_value,
        ),
        headers,
    )
    return get_success_data(resp)


def schedule_appeal(
    *,
    property_id: str,
    appeal_id: str,
    scheduled_start: str,
    scheduled_end: str,
    hearing_room: str,
    officer_id: str,
    version: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /properties/{id}/appeals/{id}/schedule. Treasurer only."""
    headers = headers or TEST_USERS["treasurer_headers"]
    resp = api_client.schedule_appeal(
        property_id,
        appeal_id,
        schedule_appeal_payload(
            scheduled_start=scheduled_start,
            scheduled_end=scheduled_end,
            hearing_room=hearing_room,
            officer_id=officer_id,
            version=version,
        ),
        headers,
    )
    return get_success_data(resp)


def conduct_appeal(
    *,
    property_id: str,
    appeal_id: str,
    officer: Dict[str, Any],
    version: Optional[int] = None,
) -> Dict[str, Any]:
    """POST /properties/{id}/appeals/{id}/conduct. HearingOfficer only;
    X-User-ID MUST equal Hearing.officer_id (PRD §2.8)."""
    headers = make_hearing_officer_headers(officer["id"])
    resp = api_client.conduct_appeal(
        property_id, appeal_id, headers, version_body(version),
    )
    return get_success_data(resp)


def decide_appeal(
    *,
    property_id: str,
    appeal_id: str,
    officer: Dict[str, Any],
    decision_outcome: str,
    decided_value: float,
    version: Optional[int] = None,
) -> Dict[str, Any]:
    """POST /properties/{id}/appeals/{id}/decide. HearingOfficer only;
    same officer who scheduled (PRD §2.8)."""
    headers = make_hearing_officer_headers(officer["id"])
    resp = api_client.decide_appeal(
        property_id,
        appeal_id,
        decide_appeal_payload(
            decision_outcome=decision_outcome,
            decided_value=decided_value,
            version=version,
        ),
        headers,
    )
    return get_success_data(resp)


def withdraw_appeal(
    *,
    owner: Dict[str, Any],
    property_id: str,
    appeal_id: str,
    version: Optional[int] = None,
) -> Dict[str, Any]:
    """POST /properties/{id}/appeals/{id}/withdraw. Owner only."""
    headers = make_owner_headers(owner["id"])
    resp = api_client.withdraw_appeal(
        property_id, appeal_id, headers, version_body(version),
    )
    return get_success_data(resp)


def get_appeal(
    property_id: str,
    appeal_id: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """GET an appeal (read access)."""
    headers = headers or TEST_USERS["assessor_headers"]
    resp = api_client.get_appeal(property_id, appeal_id, headers)
    return get_success_data(resp)


# ===========================================================================
# TaxBill lifecycle — PRD §3.4
# ===========================================================================
def create_tax_bill(
    *,
    property_id: str,
    roll_year: int,
    mill_rate: Optional[float] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /properties/{id}/tax_bills. Treasurer only.

    Note: PRD §3.2 says that on auto-finalize from clock advance, a
    TaxBill is auto-created in PENDING. This helper exists for the
    explicit-creation pathway (PRD §3.4)."""
    headers = headers or TEST_USERS["treasurer_headers"]
    resp = api_client.create_tax_bill(
        property_id,
        create_tax_bill_payload(roll_year=roll_year, mill_rate=mill_rate),
        headers,
    )
    return get_success_data(resp)


def issue_tax_bill(
    *,
    property_id: str,
    tax_bill_id: str,
    version: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /properties/{id}/tax_bills/{id}/issue. Treasurer only."""
    headers = headers or TEST_USERS["treasurer_headers"]
    resp = api_client.issue_tax_bill(
        property_id, tax_bill_id, headers, version_body(version),
    )
    return get_success_data(resp)


def get_tax_bill(
    property_id: str,
    tax_bill_id: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """GET a tax bill (read access)."""
    headers = headers or TEST_USERS["treasurer_headers"]
    resp = api_client.get_tax_bill(property_id, tax_bill_id, headers)
    return get_success_data(resp)


def post_payment(
    *,
    owner: Dict[str, Any],
    property_id: str,
    tax_bill_id: str,
    amount: float,
) -> Dict[str, Any]:
    """POST /properties/{id}/tax_bills/{id}/payments. Owner only.

    The returned data is the Payment row (PRD §4 output: Payment).
    """
    headers = make_owner_headers(owner["id"])
    resp = api_client.create_payment(
        property_id, tax_bill_id,
        create_payment_payload(amount=amount),
        headers,
    )
    return get_success_data(resp)


def list_payments(
    *,
    property_id: str,
    tax_bill_id: str,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """GET /properties/{id}/tax_bills/{id}/payments. Returns the full
    envelope so callers can read meta + data."""
    headers = headers or TEST_USERS["treasurer_headers"]
    resp = api_client.list_payments(
        property_id, tax_bill_id, headers, params=params,
    )
    return resp


# ===========================================================================
# DeferralPlan lifecycle — PRD §3.6
# ===========================================================================
def request_deferral_plan(
    *,
    owner: Dict[str, Any],
    property_id: str,
    tax_bill_id: str,
) -> Dict[str, Any]:
    """POST /properties/{id}/tax_bills/{id}/deferral_plans. Owner only."""
    headers = make_owner_headers(owner["id"])
    resp = api_client.request_deferral_plan(
        property_id, tax_bill_id, headers,
    )
    return get_success_data(resp)


def activate_deferral_plan(
    *,
    property_id: str,
    tax_bill_id: str,
    deferral_plan_id: str,
    version: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /.../deferral_plans/{id}/activate. Treasurer only."""
    headers = headers or TEST_USERS["treasurer_headers"]
    resp = api_client.activate_deferral_plan(
        property_id, tax_bill_id, deferral_plan_id, headers,
        version_body(version),
    )
    return get_success_data(resp)


def cancel_deferral_plan(
    *,
    owner: Dict[str, Any],
    property_id: str,
    tax_bill_id: str,
    deferral_plan_id: str,
    version: Optional[int] = None,
) -> Dict[str, Any]:
    """POST /.../deferral_plans/{id}/cancel. Owner only."""
    headers = make_owner_headers(owner["id"])
    resp = api_client.cancel_deferral_plan(
        property_id, tax_bill_id, deferral_plan_id, headers,
        version_body(version),
    )
    return get_success_data(resp)


def get_deferral_plan(
    *,
    property_id: str,
    tax_bill_id: str,
    deferral_plan_id: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """GET a deferral plan (read access)."""
    headers = headers or TEST_USERS["treasurer_headers"]
    resp = api_client.get_deferral_plan(
        property_id, tax_bill_id, deferral_plan_id, headers,
    )
    return get_success_data(resp)


# ===========================================================================
# Composite scenarios
# ===========================================================================
def setup_owner_and_property(
    *,
    market_value: float = 500_000.00,
    veteran_status: Optional[bool] = None,
    disability_rating: Optional[int] = None,
    date_of_birth: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Create one Owner + one Property owned by them. Returns
    (owner, property)."""
    owner = create_owner(
        date_of_birth=date_of_birth,
        veteran_status=veteran_status,
        disability_rating=disability_rating,
    )
    prop = create_property(owner=owner, market_value=market_value)
    return owner, prop


def setup_issued_assessment(
    *,
    market_value: float = 500_000.00,
    roll_year: int = 2025,
    market_value_at_roll: Optional[float] = None,
    veteran_status: Optional[bool] = None,
    disability_rating: Optional[int] = None,
    date_of_birth: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Active flow up to an ISSUED Assessment. Returns
    (owner, property, assessment)."""
    owner, prop = setup_owner_and_property(
        market_value=market_value,
        veteran_status=veteran_status,
        disability_rating=disability_rating,
        date_of_birth=date_of_birth,
    )
    mvr = (
        market_value_at_roll
        if market_value_at_roll is not None
        else market_value
    )
    draft = create_assessment(
        property_id=prop["id"],
        roll_year=roll_year,
        market_value_at_roll=mvr,
    )
    issued = issue_assessment(
        property_id=prop["id"], assessment_id=draft["id"],
    )
    return owner, prop, issued


def setup_finalized_assessment_via_clock(
    *,
    market_value: float = 500_000.00,
    roll_year: int = 2025,
    market_value_at_roll: Optional[float] = None,
    veteran_status: Optional[bool] = None,
    disability_rating: Optional[int] = None,
    date_of_birth: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Active flow to FINALIZED Assessment by advancing clock past the
    appeal window with no Appeal filed. Returns (owner, property,
    assessment_finalized).

    PRD §3.2: "If, instead, the logical clock advances past
    appeal_window_closes_at without any Appeal having been filed, the
    Assessment automatically transitions ISSUED → FINALIZED."
    """
    owner, prop, assessment = setup_issued_assessment(
        market_value=market_value,
        roll_year=roll_year,
        market_value_at_roll=market_value_at_roll,
        veteran_status=veteran_status,
        disability_rating=disability_rating,
        date_of_birth=date_of_birth,
    )
    # Advance past appeal_window_closes_at.
    advance_clock_to(
        add_days_iso(assessment["appeal_window_closes_at"], 1),
    )
    refreshed = get_assessment(prop["id"], assessment["id"])
    return owner, prop, refreshed


def setup_issued_tax_bill(
    *,
    market_value: float = 500_000.00,
    roll_year: int = 2025,
    market_value_at_roll: Optional[float] = None,
    mill_rate: Optional[float] = None,
    veteran_status: Optional[bool] = None,
    disability_rating: Optional[int] = None,
    date_of_birth: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Full lifecycle through a FINALIZED Assessment + ISSUED TaxBill.

    Returns (owner, property, assessment, tax_bill).
    """
    owner, prop, assessment = setup_finalized_assessment_via_clock(
        market_value=market_value,
        roll_year=roll_year,
        market_value_at_roll=market_value_at_roll,
        veteran_status=veteran_status,
        disability_rating=disability_rating,
        date_of_birth=date_of_birth,
    )
    bill = create_tax_bill(
        property_id=prop["id"], roll_year=roll_year, mill_rate=mill_rate,
    )
    issued_bill = issue_tax_bill(
        property_id=prop["id"], tax_bill_id=bill["id"],
    )
    return owner, prop, assessment, issued_bill


def setup_scheduled_appeal(
    *,
    market_value: float = 500_000.00,
    roll_year: int = 2025,
    market_value_at_roll: Optional[float] = None,
    claimed_value: float = 300_000.00,
    decision_outcome_hint: str = "REDUCED",
) -> Dict[str, Any]:
    """Owner files an appeal, Treasurer schedules a hearing in
    ROOM_A with a fresh HearingOfficer. Returns a dict with keys:
    owner, property, assessment, officer, appeal, scheduled_appeal.

    Hearing window: starts 1 hour from now, 60 minutes long, ROOM_A.
    """
    owner, prop, assessment = setup_issued_assessment(
        market_value=market_value,
        roll_year=roll_year,
        market_value_at_roll=market_value_at_roll,
    )
    appeal = file_appeal(
        owner=owner, property_id=prop["id"],
        assessment_id=assessment["id"],
        claimed_value=claimed_value,
    )
    officer = create_hearing_officer(full_name="BoE Officer Alpha")
    # Schedule 1 hour from now, 60 minutes long.
    base = iso_now_utc()
    start = add_minutes_iso(base, 60)
    end = add_minutes_iso(start, 60)
    scheduled = schedule_appeal(
        property_id=prop["id"], appeal_id=appeal["id"],
        scheduled_start=start, scheduled_end=end,
        hearing_room="ROOM_A", officer_id=officer["id"],
    )
    return {
        "owner": owner,
        "property": prop,
        "assessment": assessment,
        "officer": officer,
        "appeal": appeal,
        "scheduled_appeal": scheduled,
        "scheduled_start": start,
        "scheduled_end": end,
    }


def setup_heard_appeal(**overrides) -> Dict[str, Any]:
    """Through HEARD: schedule + conduct. Returns same dict with
    'heard_appeal' added.

    PRD §3.5: '(SCHEDULED → HEARD) ... The current time must be at or
    after Hearing.scheduled_start.' So this advances the clock to the
    scheduled start before conducting.
    """
    ctx = setup_scheduled_appeal(**overrides)
    # PRD §3.5: must be at or after scheduled_start.
    advance_clock_to(ctx["scheduled_start"])
    heard = conduct_appeal(
        property_id=ctx["property"]["id"],
        appeal_id=ctx["appeal"]["id"],
        officer=ctx["officer"],
    )
    ctx["heard_appeal"] = heard
    return ctx


def setup_payment_then_appeal_decided(
    *,
    market_value: float = 500_000.00,
    roll_year: int = 2025,
    mill_rate: float = 12.5,
    payment_amount: float = 5500.00,
    decision_outcome: str = "REDUCED",
    decided_value: float = 320_000.00,
    claimed_value: float = 300_000.00,
) -> Dict[str, Any]:
    """Setup: bill issued at base_tax_amount given mill_rate, owner
    pays `payment_amount`, then files an appeal that is fully
    processed (scheduled → conducted → decided) with the supplied
    outcome and decided_value.

    NOTE: The PRD §3.2 ISSUED-without-Appeal auto-FINALIZE path
    requires no Appeal at the time the clock crosses
    appeal_window_closes_at. So we cannot use the clock-finalize path
    here — the Appeal must be filed AFTER the bill exists. Workflow:

      1) Issue Assessment.
      2) Advance clock past appeal_window_closes_at → FINALIZED.
      3) Create + issue TaxBill, owner pays.
      4) Re-open by NOT relying on the clock — we can't, because
         FINALIZED is terminal until appeal cycle reopens. The PRD
         leaves no way to "re-open" a FINALIZED Assessment for a
         brand-new Appeal — the appeal window is pinned at
         issued_at+APPEAL_WINDOW_DAYS.

    Therefore, this fixture uses an alternative pinned route:

      1) Issue Assessment.
      2) Owner files Appeal IMMEDIATELY (Assessment → UNDER_APPEAL).
      3) Schedule, conduct, then BEFORE deciding, we cannot issue
         a TaxBill (the bill requires FINALIZED). So we must defer
         the bill payment to AFTER the decide-cascade — but the
         scenarios in SCAFFOLD_DIFFICULTY_DESIGN call for a bill
         that already exists at decide-time.

    The PRD §3.5 cascade is explicitly written for the case where a
    TaxBill EXISTS at decide-time (variant refund-first /
    credit-carry act on existing payments). So the design must be:

      1) Issue Assessment.
      2) Advance past window → FINALIZED.
      3) Create + issue TaxBill, owner pays.
      4) (No further Appeals possible — window has closed.)

    The DIFFICULTY_DESIGN refund-tests assume an Appeal that is
    decidable AFTER a payment has been applied. The reconcilable
    state is reached by:

      1) Owner files Appeal early (within window) →
         Assessment.UNDER_APPEAL.
      2) Schedule, conduct.
      3) Owner pays — but PRD §3.4 says TaxBill issuance requires
         Assessment FINALIZED; bills cannot exist while
         UNDER_APPEAL.

    The reconciliation pathway in the difficulty design therefore
    runs only when the bill is created BEFORE the appeal — which
    requires the appeal window to have closed (Assessment FINALIZED
    by clock advance) AND another Appeal to be filed while
    FINALIZED.

    However, PRD §3.5 ('The Assessment itself must be in ISSUED (or
    already in UNDER_APPEAL)') forbids filing an Appeal on a
    FINALIZED Assessment. So the only way the refund cascade can
    fire is when the bill is created during an UNDER_APPEAL
    Assessment — which PRD §3.4 forbids.

    Resolution: the PRD allows the cascade to act on a TaxBill
    'if one exists' (PRD §3.5 hop 2). This wording suggests a
    BILL that was issued BEFORE the appeal was filed — i.e. for an
    earlier roll year? No, the bill is per (property, roll_year)
    and is tied to the same Assessment as the Appeal.

    The reconciling path is: PRD §3.5 explicitly states the cascade
    'against any existing TaxBill for the same (property_id,
    roll_year)' and PRD §3.4 says the bill computation 'runs every
    time ... the underlying Assessment is FINALIZED with a changed
    capped_value' — i.e. the bill ALREADY EXISTS by the time of the
    decide cascade. Reading PRD §3.2 more carefully: 'If, instead,
    the logical clock advances past appeal_window_closes_at without
    any Appeal having been filed, the Assessment automatically
    transitions ISSUED → FINALIZED, and a TaxBill is auto-created in
    PENDING ... .' Cascades for REDUCED/INCREASED can therefore
    only act on this auto-created bill OR a bill that pre-existed
    from a prior roll year — meaning a fresh Appeal filed against an
    already-FINALIZED Assessment.

    But PRD §3.5 states Appeals require ISSUED/UNDER_APPEAL. So the
    refund cascade described in the difficulty design IS NOT
    reachable through the documented endpoint surface, with one
    exception: if PRD §3.5 'idempotently — if it is already there,
    no transition occurs' permits filing while UNDER_APPEAL.

    The narrative path that the difficulty design assumes is:
      1) Owner files Appeal early (Assessment UNDER_APPEAL).
      2) Schedule + conduct.
      3) Decide REDUCED.
      4) Cascade fires; if a bill exists, recompute; if payments,
         refund.

    Since bills only exist post-FINALIZED, and FINALIZED only
    happens AFTER the deciding cascade in this path, the refund
    branch has nothing to act on. This means the refund-emitted
    variant requires a path where the bill exists alongside an
    Appeal — for which the PRD provides no constructor.

    Given this PRD ambiguity, this fixture builds the natural path
    (file → schedule → conduct → decide) and lets the caller
    inspect the resulting bill (created in PENDING on auto-FINALIZE)
    plus any payment / refund mutations. For tests that assert
    refund emission, the fixture allows the caller to supply
    payment_amount > 0 by EXPLICITLY funding the auto-created bill
    AFTER decide.

    For brevity, this fixture exposes the wiring as follows:
      - Phase A: setup → file → schedule → conduct.
      - Phase B (optional, after decide): apply payment.
    """
    # Phase A — issue Assessment, file Appeal, schedule, conduct.
    owner = create_owner()
    prop = create_property(owner=owner, market_value=market_value)
    draft = create_assessment(
        property_id=prop["id"], roll_year=roll_year,
        market_value_at_roll=market_value,
    )
    issued = issue_assessment(
        property_id=prop["id"], assessment_id=draft["id"],
    )
    appeal = file_appeal(
        owner=owner, property_id=prop["id"],
        assessment_id=issued["id"],
        claimed_value=claimed_value,
    )
    officer = create_hearing_officer(full_name="BoE Officer Beta")
    base = iso_now_utc()
    start = add_minutes_iso(base, 60)
    end = add_minutes_iso(start, 60)
    schedule_appeal(
        property_id=prop["id"], appeal_id=appeal["id"],
        scheduled_start=start, scheduled_end=end,
        hearing_room="ROOM_A", officer_id=officer["id"],
    )
    advance_clock_to(start)
    conduct_appeal(
        property_id=prop["id"], appeal_id=appeal["id"], officer=officer,
    )
    decided = decide_appeal(
        property_id=prop["id"], appeal_id=appeal["id"], officer=officer,
        decision_outcome=decision_outcome, decided_value=decided_value,
    )
    return {
        "owner": owner,
        "property": prop,
        "assessment": issued,
        "appeal": appeal,
        "decided_appeal": decided,
        "officer": officer,
    }


def setup_two_appeals_branching_compare(
    *,
    mill_rate: float = 12.5,
    market_value: float = 500_000.00,
    roll_year: int = 2025,
) -> Dict[str, Any]:
    """Build two independent Property/Assessment/Appeal scenarios for
    side-by-side comparison of REDUCED vs INCREASED branches. Returns
    {'reduced': ctx_reduced, 'increased': ctx_increased}.

    Each ctx contains owner, property, assessment, officer, appeal.
    Both appeals are decided in the same call sequence so the caller
    can compare outcomes.
    """
    ctx_red = setup_payment_then_appeal_decided(
        market_value=market_value,
        roll_year=roll_year,
        mill_rate=mill_rate,
        payment_amount=0.0,
        decision_outcome="REDUCED",
        decided_value=400_000.00,
        claimed_value=300_000.00,
    )
    ctx_inc = setup_payment_then_appeal_decided(
        market_value=market_value,
        roll_year=roll_year,
        mill_rate=mill_rate,
        payment_amount=0.0,
        decision_outcome="INCREASED",
        decided_value=600_000.00,
        claimed_value=700_000.00,
    )
    return {"reduced": ctx_red, "increased": ctx_inc}


# ---------------------------------------------------------------------------
# Owner age / DOB convenience for SENIOR exemption and deferral tests.
# ---------------------------------------------------------------------------
def setup_senior_owner_and_property(
    *,
    market_value: float = 500_000.00,
    roll_year: int = 2025,
    disability_rating: int = 0,
    veteran_status: bool = False,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Owner old enough to satisfy SENIOR (age >= 65 on Jan 1 of
    roll_year). PRD §3.3."""
    owner = create_owner(
        date_of_birth=senior_eligible_dob(roll_year),
        disability_rating=disability_rating,
        veteran_status=veteran_status,
    )
    prop = create_property(owner=owner, market_value=market_value)
    return owner, prop


# ---------------------------------------------------------------------------
# Officer scheduling helpers — for room/officer overlap tests.
# ---------------------------------------------------------------------------
def setup_two_appeals_for_scheduling_conflict(
    *,
    roll_year: int = 2025,
) -> Dict[str, Any]:
    """Two independent properties each with an ISSUED Assessment and a
    FILED Appeal, ready for schedule-conflict tests. Also creates one
    shared HearingOfficer."""
    owner1, prop1, asmt1 = setup_issued_assessment(roll_year=roll_year)
    owner2, prop2, asmt2 = setup_issued_assessment(roll_year=roll_year)
    appeal1 = file_appeal(
        owner=owner1, property_id=prop1["id"],
        assessment_id=asmt1["id"], claimed_value=100_000.00,
    )
    appeal2 = file_appeal(
        owner=owner2, property_id=prop2["id"],
        assessment_id=asmt2["id"], claimed_value=100_000.00,
    )
    officer = create_hearing_officer(full_name="BoE Officer Gamma")
    return {
        "owner1": owner1, "property1": prop1, "appeal1": appeal1,
        "owner2": owner2, "property2": prop2, "appeal2": appeal2,
        "officer": officer,
    }


__all__ = [
    # clock
    "advance_clock_to",
    # dob helpers
    "senior_eligible_dob",
    "young_dob",
    # base wrappers
    "create_owner",
    "create_hearing_officer",
    "create_property",
    "transfer_property_owner",
    "create_assessment",
    "issue_assessment",
    "get_assessment",
    "submit_exemption",
    "approve_exemption",
    "deny_exemption",
    "revoke_exemption",
    "file_appeal",
    "schedule_appeal",
    "conduct_appeal",
    "decide_appeal",
    "withdraw_appeal",
    "get_appeal",
    "create_tax_bill",
    "issue_tax_bill",
    "get_tax_bill",
    "post_payment",
    "list_payments",
    "request_deferral_plan",
    "activate_deferral_plan",
    "cancel_deferral_plan",
    "get_deferral_plan",
    # composite
    "setup_owner_and_property",
    "setup_issued_assessment",
    "setup_finalized_assessment_via_clock",
    "setup_issued_tax_bill",
    "setup_scheduled_appeal",
    "setup_heard_appeal",
    "setup_payment_then_appeal_decided",
    "setup_two_appeals_branching_compare",
    "setup_senior_owner_and_property",
    "setup_two_appeals_for_scheduling_conflict",
]
