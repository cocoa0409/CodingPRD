"""Composite setup helpers — multi-step preambles tests can reuse.

Most interesting test claims require the system to be in a late state
that takes 5-15 API calls to reach. Each fixture composes the lower-
level steps so the test body can focus on the rule under assertion.

IDENTITY THREADING — PRD §2.1:

    "Five of the six roles are entity-backed. When X-User-Role is
    Applicant, X-User-ID is the id of the acting Applicant; ownership
    checks compare resource foreign-key fields (the applicant_id on a
    Voucher, or the Voucher.applicant_id reached transitively from a
    Tenancy.voucher_id) to X-User-ID. When X-User-Role is Landlord,
    X-User-ID is the id of the acting Landlord, and the Unit.landlord_id
    field on each unit is compared to X-User-ID for ownership."

After a fixture creates an Applicant entity, any ownership-gated call
on behalf of that Applicant MUST use make_applicant_headers(applicant.id)
— never the shared TEST_USERS["applicant_headers"] constant. The same
rule applies to Unit.landlord_id (Landlord) and to Inspector PHA
scoping. The shared constants are reserved for tests that probe
auth/role-RBAC failure modes without exercising ownership.

INSPECTOR PHA CONVENTION — PRD §3.5:

    "An Inspector may only complete inspections whose tenancy's voucher
    is administered by the inspector's own PHA; a violation returns
    ERR_INSPECTOR_OUT_OF_SCOPE."

The PRD specifies the gate but not the mechanism by which an Inspector
is linked to a PHA. Following the convention encoded in the test
recipes (e.g., 'Inspector I2 belongs to PHA_002'), tests use Inspector
identifiers shaped `inspector-<PHA_ID>-<suffix>` so the implementer can
parse PHA membership from the X-User-ID prefix.

CLOCK ANCHORING — PRD §2.7:

    "All ... derived deadline fields ... read from this clock."
    "For test and replay purposes, the clock can be advanced explicitly
    by a PHAAdmin capability that accepts a to_timestamp payload and
    sets the logical clock to that instant."

The logical clock is shared across all tests within the process. Each
fixture anchors deadlines to instants the test author can advance to.

Setup calls use get_success_data() (a lenient 2xx validator), so a
failed setup surfaces as 'Setup failed' rather than a confusing test
assertion failure downstream.
"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    DEFAULT_PHA_ID,
    PHA_NETWORK,
    TEST_DEFAULTS,
    VOUCHER_INITIAL_SEARCH_DAYS,
)
from .factories import (
    add_days,
    add_hours,
    add_seconds,
    clock_advance_payload,
    complete_inspection_payload,
    create_applicant_payload,
    create_inspection_payload,
    create_payment_standard_payload,
    create_portability_request_payload,
    create_rent_reasonableness_payload,
    create_tenancy_payload,
    create_unit_payload,
    create_voucher_payload,
    iso_utc,
    monthly_hap_payload,
    move_out_payload,
    parse_iso,
    random_address,
    random_suffix,
    submit_annual_review_payload,
    utcnow,
    yyyymm,
)
from .test_users import (
    PHA_ADMIN_BOOTSTRAP_ID,
    TEST_USERS,
    make_applicant_headers,
    make_case_worker_headers,
    make_inspector_headers,
    make_landlord_headers,
    make_pha_admin_headers,
    make_portability_coordinator_headers,
)


# ===========================================================================
# Clock helpers — PRD §2.7
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
    return _seed_clock()


def current_clock_iso() -> str:
    return iso_utc(current_clock())


def reset_clock_tracker_to(dt: datetime) -> None:
    """Anchor the test-process's view of the clock to an instant."""
    global _CURRENT_CLOCK
    with _CLOCK_LOCK:
        _CURRENT_CLOCK = dt


def advance_clock_to(target: datetime,
                     headers: Optional[Dict[str, str]] = None) -> datetime:
    """PRD §2.7: clock-advance capability that sets the logical clock
    to the supplied instant. Advancing backwards is rejected."""
    global _CURRENT_CLOCK
    if headers is None:
        headers = TEST_USERS["pha_admin_headers"]
    target_iso = iso_utc(target)
    get_success_data(
        api_client.advance_clock(
            clock_advance_payload(target_iso), headers,
        ),
    )
    with _CLOCK_LOCK:
        _CURRENT_CLOCK = target
    return target


def advance_clock_by_days(days: int) -> datetime:
    return advance_clock_to(add_days(_seed_clock(), days))


def advance_clock_by_seconds(seconds: int) -> datetime:
    return advance_clock_to(add_seconds(_seed_clock(), seconds))


def advance_clock_by_hours(hours: int) -> datetime:
    return advance_clock_to(add_hours(_seed_clock(), hours))


# ===========================================================================
# Identity helpers — entity-backed role IDs
# ===========================================================================
def new_landlord_id() -> str:
    return f"landlord-{random_suffix(10)}"


def new_inspector_id(pha_id: str = DEFAULT_PHA_ID) -> str:
    """Inspector IDs encode PHA membership via prefix convention so that
    implementations can derive an Inspector's PHA from X-User-ID for the
    ERR_INSPECTOR_OUT_OF_SCOPE gate (PRD §3.5)."""
    return f"inspector-{pha_id}-{random_suffix(8)}"


def new_case_worker_id() -> str:
    return f"caseworker-{random_suffix(10)}"


def new_portability_coordinator_id(pha_id: str = DEFAULT_PHA_ID) -> str:
    return f"portcoord-{pha_id}-{random_suffix(8)}"


# ===========================================================================
# Read helpers (lenient — for cross-checking inside fixtures or tests)
# ===========================================================================
def get_voucher(voucher_id: str,
                headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    headers = headers or TEST_USERS["case_worker_headers"]
    return get_success_data(api_client.get_voucher(voucher_id, headers))


def get_tenancy(tenancy_id: str,
                headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    headers = headers or TEST_USERS["case_worker_headers"]
    return get_success_data(api_client.get_tenancy(tenancy_id, headers))


def get_inspection(inspection_id: str,
                   headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    headers = headers or TEST_USERS["case_worker_headers"]
    return get_success_data(api_client.get_inspection(inspection_id, headers))


def get_annual_review(review_id: str,
                      headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    headers = headers or TEST_USERS["case_worker_headers"]
    return get_success_data(api_client.get_annual_review(review_id, headers))


def get_unit(unit_id: str,
             headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    headers = headers or TEST_USERS["case_worker_headers"]
    return get_success_data(api_client.get_unit(unit_id, headers))


def get_applicant(applicant_id: str,
                  headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    headers = headers or TEST_USERS["case_worker_headers"]
    return get_success_data(api_client.get_applicant(applicant_id, headers))


def list_hap_payments(params: Optional[Dict[str, Any]] = None,
                      headers: Optional[Dict[str, str]] = None) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    headers = headers or TEST_USERS["pha_admin_headers"]
    resp = api_client.list_hap_payments(headers, params=params)
    body = resp.json()
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, list):
        get_success_data(resp)  # raises with diagnostic
        data = []
    meta = body.get("meta", {}) if isinstance(body, dict) else {}
    return list(data), dict(meta) if isinstance(meta, dict) else {}


# ===========================================================================
# Step builders — Payment Standards (PRD §3.3)
# ===========================================================================
def ensure_payment_standard(zone: str, bedroom_size: int,
                            standard_amount_cents: int = 120_000,
                            mobility_amount_cents: Optional[int] = None,
                            effective_from: Optional[str] = None) -> Dict[str, Any]:
    """Create a PaymentStandard row for (zone, bedroom_size)."""
    if effective_from is None:
        effective_from = iso_utc(add_days(_seed_clock(), -3650))
    payload = create_payment_standard_payload(
        zone=zone,
        bedroom_size=bedroom_size,
        standard_amount_cents=standard_amount_cents,
        mobility_amount_cents=mobility_amount_cents,
        effective_from=effective_from,
    )
    return get_success_data(
        api_client.create_payment_standard(
            payload, TEST_USERS["pha_admin_headers"],
        ),
    )


def seed_payment_standards(rows: Optional[List[Dict[str, Any]]] = None) -> None:
    """Pre-seed PaymentStandard rows for the common (zone, br) cells used
    across tests so that any subsequent Tenancy can freeze a PS."""
    defaults: List[Dict[str, Any]] = []
    for zone in ("ZONE_A", "ZONE_B", "ZONE_C"):
        for br in range(0, 6):
            defaults.append({
                "zone": zone,
                "bedroom_size": br,
                "standard_amount_cents": 60_000 + br * 30_000,
                # mobility = 110% by default (PRD §3.3 typical)
                "mobility_amount_cents": ((60_000 + br * 30_000) * 110) // 100,
            })
    for row in rows or defaults:
        ensure_payment_standard(
            zone=row["zone"],
            bedroom_size=row["bedroom_size"],
            standard_amount_cents=row["standard_amount_cents"],
            mobility_amount_cents=row.get("mobility_amount_cents"),
        )


# ===========================================================================
# Step builders — Applicant (PRD §3.1)
# ===========================================================================
def create_applicant(**overrides) -> Dict[str, Any]:
    payload = create_applicant_payload(**overrides)
    # Created by a CaseWorker on the household's behalf (PRD §3.1).
    headers = make_case_worker_headers(new_case_worker_id())
    return get_success_data(
        api_client.create_applicant(payload, headers),
    )


# ===========================================================================
# Step builders — Voucher (PRD §3.2)
# ===========================================================================
def issue_voucher(
    applicant_id: str,
    zone: str = "ZONE_A",
    special_mobility_flag: Optional[bool] = None,
    administering_pha_id: str = DEFAULT_PHA_ID,
) -> Dict[str, Any]:
    """PRD §3.2: A CaseWorker issues a voucher; status moves immediately
    to SEARCHING."""
    cw_headers = make_case_worker_headers(new_case_worker_id())
    payload = create_voucher_payload(
        applicant_id=applicant_id,
        zone=zone,
        special_mobility_flag=special_mobility_flag,
        administering_pha_id=administering_pha_id,
    )
    return get_success_data(api_client.create_voucher(payload, cw_headers))


# ===========================================================================
# Step builders — Unit (PRD §3.3)
# ===========================================================================
def create_unit(
    zone: str = "ZONE_A",
    bedroom_count: int = 2,
    asking_rent_cents: int = 110_000,
    tenant_paid_utilities_cents: Optional[int] = 10_000,
    landlord_id: Optional[str] = None,
) -> Tuple[Dict[str, Any], str]:
    """Returns (unit_dict, landlord_id) so subsequent ownership-gated
    Landlord operations on this Unit can use make_landlord_headers(landlord_id)."""
    landlord_id = landlord_id or new_landlord_id()
    payload = create_unit_payload(
        zone=zone,
        bedroom_count=bedroom_count,
        asking_rent_cents=asking_rent_cents,
        tenant_paid_utilities_cents=tenant_paid_utilities_cents,
    )
    headers = make_landlord_headers(landlord_id)
    unit = get_success_data(api_client.create_unit(payload, headers))
    return unit, landlord_id


# ===========================================================================
# Step builders — Tenancy (PRD §3.4, §3.5, §3.6, §3.7)
# ===========================================================================
def create_pending_tenancy(
    voucher_id: str,
    unit_id: str,
    lease_start: Optional[str] = None,
) -> Dict[str, Any]:
    """PRD §3.4: tenancy starts in PENDING_INSPECTION."""
    if lease_start is None:
        lease_start = iso_utc(add_days(_seed_clock(), 30))
    cw = make_case_worker_headers(new_case_worker_id())
    return get_success_data(
        api_client.create_tenancy(
            create_tenancy_payload(voucher_id, unit_id, lease_start), cw,
        ),
    )


def schedule_inspection(
    tenancy_id: str,
    inspection_type: str,
    scheduled_for: Optional[str] = None,
    inspector_id: Optional[str] = None,
    pha_id: str = DEFAULT_PHA_ID,
) -> Dict[str, Any]:
    """PRD §3.5: schedule an inspection. Returns the Inspection."""
    if scheduled_for is None:
        scheduled_for = iso_utc(add_days(_seed_clock(), 1))
    inspector_id = inspector_id or new_inspector_id(pha_id)
    headers = make_inspector_headers(inspector_id)
    return get_success_data(
        api_client.create_inspection(
            create_inspection_payload(
                tenancy_id, inspection_type, scheduled_for,
            ),
            headers,
        ),
    )


def complete_inspection(
    inspection_id: str,
    outcome: str,
    defects: Optional[List[str]] = None,
    inspector_id: Optional[str] = None,
    pha_id: str = DEFAULT_PHA_ID,
) -> Dict[str, Any]:
    """PRD §3.5: Inspector files outcome. PRD §3.5 requires
    Inspector-PHA = Tenancy-PHA, so callers must pass an inspector_id
    matching the Tenancy's administering PHA."""
    inspector_id = inspector_id or new_inspector_id(pha_id)
    headers = make_inspector_headers(inspector_id)
    return get_success_data(
        api_client.complete_inspection(
            inspection_id,
            complete_inspection_payload(outcome, defects or []),
            headers,
        ),
    )


def attach_rent_reasonableness(
    tenancy_id: str,
    comparable_rents_cents: Optional[List[int]] = None,
) -> Dict[str, Any]:
    """PRD §3.6: CaseWorker attaches comparables; updates Tenancy.rent_reasonable."""
    if comparable_rents_cents is None:
        comparable_rents_cents = [120_000, 130_000, 140_000, 150_000]
    cw = make_case_worker_headers(new_case_worker_id())
    return get_success_data(
        api_client.create_rent_reasonableness_record(
            create_rent_reasonableness_payload(
                tenancy_id, comparable_rents_cents,
            ),
            cw,
        ),
    )


def finalize_tenancy(tenancy_id: str) -> Dict[str, Any]:
    """PRD §3.7: CaseWorker finalizes — body has no fields beyond version."""
    cw = make_case_worker_headers(new_case_worker_id())
    return get_success_data(
        api_client.finalize_tenancy(tenancy_id, {}, cw),
    )


# ===========================================================================
# Composite Tier 1 — full path to PENDING_RENT_REASONABLE
# ===========================================================================
def setup_eligible_applicant_with_voucher(
    *,
    gross_annual_income_cents: int = 3_000_000,
    household_size: int = 3,
    dependents_count: int = 1,
    elderly_or_disabled_head: bool = False,
    childcare_expense_annual_cents: Optional[int] = None,
    medical_expense_annual_cents: Optional[int] = None,
    zone: str = "ZONE_A",
    special_mobility_flag: Optional[bool] = None,
    administering_pha_id: str = DEFAULT_PHA_ID,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Create an ELIGIBLE Applicant and issue a Voucher to them.

    Returns (applicant, voucher).
    """
    applicant = create_applicant(
        gross_annual_income_cents=gross_annual_income_cents,
        household_size=household_size,
        dependents_count=dependents_count,
        elderly_or_disabled_head=elderly_or_disabled_head,
        childcare_expense_annual_cents=childcare_expense_annual_cents,
        medical_expense_annual_cents=medical_expense_annual_cents,
    )
    voucher = issue_voucher(
        applicant_id=applicant["id"],
        zone=zone,
        special_mobility_flag=special_mobility_flag,
        administering_pha_id=administering_pha_id,
    )
    return applicant, voucher


def setup_unit_with_payment_standard(
    *,
    zone: str = "ZONE_A",
    bedroom_count: int = 2,
    asking_rent_cents: int = 110_000,
    tenant_paid_utilities_cents: int = 10_000,
    standard_amount_cents: int = 120_000,
    mobility_amount_cents: Optional[int] = None,
    landlord_id: Optional[str] = None,
    voucher_bedroom_size_for_ps: Optional[int] = None,
) -> Tuple[Dict[str, Any], str, Dict[str, Any]]:
    """Seed a PaymentStandard row, then create a Unit. Returns
    (unit, landlord_id, payment_standard)."""
    ps_br = (
        voucher_bedroom_size_for_ps
        if voucher_bedroom_size_for_ps is not None
        else bedroom_count
    )
    ps = ensure_payment_standard(
        zone=zone,
        bedroom_size=ps_br,
        standard_amount_cents=standard_amount_cents,
        mobility_amount_cents=mobility_amount_cents,
    )
    unit, landlord_id = create_unit(
        zone=zone,
        bedroom_count=bedroom_count,
        asking_rent_cents=asking_rent_cents,
        tenant_paid_utilities_cents=tenant_paid_utilities_cents,
        landlord_id=landlord_id,
    )
    return unit, landlord_id, ps


def setup_tenancy_pending_rent_reasonable(
    *,
    gross_annual_income_cents: int = 3_000_000,
    household_size: int = 3,
    dependents_count: int = 1,
    elderly_or_disabled_head: bool = False,
    zone: str = "ZONE_A",
    bedroom_count: int = 2,
    asking_rent_cents: int = 110_000,
    tenant_paid_utilities_cents: int = 10_000,
    standard_amount_cents: int = 120_000,
    mobility_amount_cents: Optional[int] = None,
    special_mobility_flag: Optional[bool] = None,
    administering_pha_id: str = DEFAULT_PHA_ID,
    comparable_rents_cents: Optional[List[int]] = None,
    childcare_expense_annual_cents: Optional[int] = None,
    medical_expense_annual_cents: Optional[int] = None,
    lease_start_offset_days: int = 30,
) -> Dict[str, Any]:
    """Drive a Tenancy all the way to PENDING_RENT_REASONABLE (initial
    inspection PASSED, rent-reasonableness record attached).

    Returns a dict {applicant, voucher, unit, landlord_id, tenancy,
    inspection, rent_record}.
    """
    applicant, voucher = setup_eligible_applicant_with_voucher(
        gross_annual_income_cents=gross_annual_income_cents,
        household_size=household_size,
        dependents_count=dependents_count,
        elderly_or_disabled_head=elderly_or_disabled_head,
        childcare_expense_annual_cents=childcare_expense_annual_cents,
        medical_expense_annual_cents=medical_expense_annual_cents,
        zone=zone,
        special_mobility_flag=special_mobility_flag,
        administering_pha_id=administering_pha_id,
    )
    # Use the voucher's bedroom_size (server-derived) for PS lookup.
    voucher_br = voucher.get("bedroom_size", bedroom_count)
    ps_br = min(int(voucher_br), int(bedroom_count))
    unit, landlord_id, ps = setup_unit_with_payment_standard(
        zone=zone,
        bedroom_count=bedroom_count,
        asking_rent_cents=asking_rent_cents,
        tenant_paid_utilities_cents=tenant_paid_utilities_cents,
        standard_amount_cents=standard_amount_cents,
        mobility_amount_cents=mobility_amount_cents,
        voucher_bedroom_size_for_ps=ps_br,
    )
    lease_start = iso_utc(add_days(_seed_clock(), lease_start_offset_days))
    tenancy = create_pending_tenancy(
        voucher_id=voucher["id"],
        unit_id=unit["id"],
        lease_start=lease_start,
    )
    inspection = schedule_inspection(
        tenancy_id=tenancy["id"],
        inspection_type="INITIAL",
        pha_id=administering_pha_id,
    )
    completed_inspection = complete_inspection(
        inspection_id=inspection["id"],
        outcome="PASS",
        defects=[],
        pha_id=administering_pha_id,
    )
    rent_record = attach_rent_reasonableness(
        tenancy_id=tenancy["id"],
        comparable_rents_cents=comparable_rents_cents,
    )
    tenancy = get_tenancy(tenancy["id"])
    return {
        "applicant": applicant,
        "voucher": voucher,
        "unit": unit,
        "landlord_id": landlord_id,
        "payment_standard": ps,
        "tenancy": tenancy,
        "inspection": completed_inspection,
        "rent_record": rent_record,
    }


# ===========================================================================
# Composite Tier 2 — finalize → ACTIVE
# ===========================================================================
def setup_active_tenancy(**kwargs) -> Dict[str, Any]:
    """Drive a Tenancy all the way to ACTIVE."""
    state = setup_tenancy_pending_rent_reasonable(**kwargs)
    finalized = finalize_tenancy(state["tenancy"]["id"])
    state["tenancy"] = finalized
    state["voucher"] = get_voucher(state["voucher"]["id"])
    state["unit"] = get_unit(state["unit"]["id"])
    return state


# ===========================================================================
# Composite Tier 3 — annual review path (PRD §3.9)
# ===========================================================================
def advance_to_review_window(active_state: Dict[str, Any],
                             days_into_window: int = 0) -> datetime:
    """Advance the clock to within the 30-day window centered on
    review_due_date for the AnnualReview attached to this ACTIVE tenancy.

    Returns the new clock instant.
    """
    tenancy = get_tenancy(active_state["tenancy"]["id"])
    # PRD §3.7: lease_start + 365 days = review_due_date.
    lease_start = parse_iso(tenancy["lease_start"])
    target = add_days(lease_start, 365) + timedelta(days=days_into_window)
    return advance_clock_to(target)


def find_due_annual_review_id(tenancy_id: str) -> str:
    """Best-effort: the AnnualReview id isn't exposed by list endpoints
    in the PRD, so fixtures discover it by reading the Tenancy and
    looking for a 'pending_annual_review_id' or by reading from a side
    channel. To avoid that coupling, fixtures that need the AR id should
    track the response of an action that touches the AR (e.g., submit).

    Returns the AR id by walking through the response of get_tenancy
    via a conventional 'annual_review_id' field. The PRD never mandates
    this field, so callers that depend on this should arrange to obtain
    the id through their own action chain.
    """
    t = get_tenancy(tenancy_id)
    # PRD §3.7 says a DUE review row is created at ACTIVE transition.
    # Implementations are free to surface its id on the Tenancy or via a
    # separate list endpoint that PRD doesn't fully constrain. Tests that
    # need this id should construct it through their own observable chain;
    # this helper provides a best-effort lookup that callers may override.
    ar_id = (
        t.get("current_annual_review_id")
        or t.get("annual_review_id")
        or t.get("due_annual_review_id")
        or t.get("pending_annual_review_id")
    )
    if not ar_id:
        raise RuntimeError(
            "fixture: could not locate the DUE annual_review id on the "
            "tenancy — the test should drive submission via its own AR id"
        )
    return ar_id


def submit_review(review_id: str,
                  declared_gross_annual_income_cents: int,
                  declared_household_size: int,
                  applicant_id: str) -> Dict[str, Any]:
    """PRD §3.9: Applicant role submits."""
    headers = make_applicant_headers(applicant_id)
    return get_success_data(
        api_client.submit_annual_review(
            review_id,
            submit_annual_review_payload(
                declared_gross_annual_income_cents,
                declared_household_size,
            ),
            headers,
        ),
    )


def approve_review(review_id: str) -> Dict[str, Any]:
    cw = make_case_worker_headers(new_case_worker_id())
    return get_success_data(api_client.approve_annual_review(review_id, {}, cw))


def deny_review(review_id: str) -> Dict[str, Any]:
    cw = make_case_worker_headers(new_case_worker_id())
    return get_success_data(api_client.deny_annual_review(review_id, {}, cw))


# ===========================================================================
# Composite Tier 4 — abatement / cure cycles (PRD §3.5)
# ===========================================================================
def take_active_tenancy_to_abated(
    active_state: Dict[str, Any],
    *,
    failure_outcome: str = "FAIL_NONLIFETHREATENING",
    defects: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Schedule an ANNUAL inspection on the ACTIVE tenancy and complete
    it with a FAIL outcome — cascades the Tenancy to ABATED (PRD §3.5)."""
    if defects is None:
        defects = ["D1"]
    tenancy = active_state["tenancy"]
    voucher = active_state["voucher"]
    pha_id = voucher.get("administering_pha_id", DEFAULT_PHA_ID)
    # PRD §3.5: 365-day gap from last passing inspection. The active
    # setup just passed an INITIAL inspection, so advance the clock.
    advance_clock_by_days(366)
    annual_inspection = schedule_inspection(
        tenancy_id=tenancy["id"],
        inspection_type="ANNUAL",
        pha_id=pha_id,
    )
    completed = complete_inspection(
        inspection_id=annual_inspection["id"],
        outcome=failure_outcome,
        defects=defects,
        pha_id=pha_id,
    )
    out = dict(active_state)
    out["annual_inspection"] = completed
    out["tenancy"] = get_tenancy(tenancy["id"])
    out["unit"] = get_unit(active_state["unit"]["id"])
    return out


def cure_abatement(
    abated_state: Dict[str, Any],
    *,
    pha_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Schedule a REINSPECTION and complete with outcome=CURED — cascades
    the Tenancy back to ACTIVE (PRD §3.5)."""
    pha_id = pha_id or abated_state["voucher"].get(
        "administering_pha_id", DEFAULT_PHA_ID,
    )
    reinspection = schedule_inspection(
        tenancy_id=abated_state["tenancy"]["id"],
        inspection_type="REINSPECTION",
        pha_id=pha_id,
    )
    completed = complete_inspection(
        inspection_id=reinspection["id"],
        outcome="CURED",
        defects=[],
        pha_id=pha_id,
    )
    out = dict(abated_state)
    out["reinspection"] = completed
    out["tenancy"] = get_tenancy(abated_state["tenancy"]["id"])
    out["unit"] = get_unit(abated_state["unit"]["id"])
    return out


# ===========================================================================
# Composite Tier 5 — portability (PRD §3.10)
# ===========================================================================
def initiate_portability(
    voucher_id: str,
    receiving_pha_id: str = "PHA_002",
    actor_applicant_id: Optional[str] = None,
) -> Dict[str, Any]:
    headers = (
        make_applicant_headers(actor_applicant_id)
        if actor_applicant_id
        else make_case_worker_headers(new_case_worker_id())
    )
    return get_success_data(
        api_client.create_portability_request(
            create_portability_request_payload(
                voucher_id, receiving_pha_id,
            ),
            headers,
        ),
    )


def absorb_portability(
    request_id: str,
    coordinator_pha_id: str = "PHA_002",
) -> Dict[str, Any]:
    """PRD §3.10: PortabilityCoordinator at receiving PHA absorbs."""
    pc_id = new_portability_coordinator_id(coordinator_pha_id)
    headers = make_portability_coordinator_headers(pc_id)
    return get_success_data(
        api_client.absorb_portability_request(request_id, {}, headers),
    )


# ===========================================================================
# Composite Tier 6 — Boundary-targeted scenarios (Difficulty Design)
# ===========================================================================
def setup_burden_at_boundary(*,
                              over_by_one_cent: bool = False) -> Dict[str, Any]:
    """Difficulty Design rule 6.1: build a Tenancy whose rent-burden
    lands at exactly 0.40 (PASS, inclusive) or 0.40001 (FAIL).

    Numbers derived from PRD §3.7 formulas:
      Applicant: gross=1_200_000 cents/yr, no deductions → adjusted=1_200_000.
      monthly_adjusted = floor(1_200_000/12) = 100_000.
      Voucher: ZONE_A, br=0 (1-person household).
      PaymentStandard: standard=60_000.
      PASS Unit: asking_rent=70_000, utilities=0 → gross_rent=70_000.
        TTP = max(ceil(100_000*.30), ceil(100_000*.10), 0, 5000) = 30_000.
        HAP = min(60_000,70_000) - 30_000 = 30_000.
        tenant_share = 70_000 - 30_000 = 40_000.
        burden = 40_000 / 100_000 = 0.40 → INCLUSIVE PASS.
      FAIL Unit: asking_rent=70_001 → tenant_share = 40_001 → 0.40001 → FAIL.
    """
    asking_rent = 70_001 if over_by_one_cent else 70_000
    state = setup_tenancy_pending_rent_reasonable(
        gross_annual_income_cents=1_200_000,
        household_size=1,
        dependents_count=0,
        elderly_or_disabled_head=False,
        zone="ZONE_A",
        bedroom_count=0,
        asking_rent_cents=asking_rent,
        tenant_paid_utilities_cents=0,
        standard_amount_cents=60_000,
        mobility_amount_cents=66_000,
        comparable_rents_cents=[90_000, 100_000, 110_000],
    )
    return state


def setup_special_mobility_with_zone_b_unit() -> Dict[str, Any]:
    """Difficulty Design rule 7.3: special_mobility voucher trying to
    finalize on a ZONE_B unit fails with ERR_MOBILITY_ZONE_VIOLATION."""
    state = setup_tenancy_pending_rent_reasonable(
        gross_annual_income_cents=2_400_000,
        household_size=2,
        dependents_count=0,
        zone="ZONE_B",  # unit zone is B
        bedroom_count=1,
        asking_rent_cents=80_000,
        tenant_paid_utilities_cents=0,
        standard_amount_cents=80_000,
        mobility_amount_cents=88_000,
        special_mobility_flag=True,
        comparable_rents_cents=[70_000, 80_000, 90_000],
    )
    return state


# ===========================================================================
# Test driver — monthly HAP sweep (PRD §3.11)
# ===========================================================================
def sweep_monthly_hap(pay_period_month: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.sweep_monthly_hap(
            monthly_hap_payload(pay_period_month),
            TEST_USERS["pha_admin_headers"],
        ),
    )


def sweep_abatements() -> Dict[str, Any]:
    return get_success_data(
        api_client.sweep_abatements({}, TEST_USERS["pha_admin_headers"]),
    )


def sweep_expirations() -> Dict[str, Any]:
    return get_success_data(
        api_client.sweep_expirations({}, TEST_USERS["pha_admin_headers"]),
    )


def sweep_reviews() -> Dict[str, Any]:
    return get_success_data(
        api_client.sweep_reviews({}, TEST_USERS["pha_admin_headers"]),
    )


__all__ = [
    # Clock
    "current_clock", "current_clock_iso", "reset_clock_tracker_to",
    "advance_clock_to", "advance_clock_by_days", "advance_clock_by_seconds",
    "advance_clock_by_hours",
    # Identity helpers
    "new_landlord_id", "new_inspector_id", "new_case_worker_id",
    "new_portability_coordinator_id",
    # Read helpers
    "get_voucher", "get_tenancy", "get_inspection", "get_annual_review",
    "get_unit", "get_applicant", "list_hap_payments",
    # Payment Standards
    "ensure_payment_standard", "seed_payment_standards",
    # Applicant + Voucher + Unit
    "create_applicant", "issue_voucher", "create_unit",
    # Tenancy step builders
    "create_pending_tenancy", "schedule_inspection", "complete_inspection",
    "attach_rent_reasonableness", "finalize_tenancy",
    # Composite tiers
    "setup_eligible_applicant_with_voucher",
    "setup_unit_with_payment_standard",
    "setup_tenancy_pending_rent_reasonable", "setup_active_tenancy",
    "advance_to_review_window", "find_due_annual_review_id",
    "submit_review", "approve_review", "deny_review",
    "take_active_tenancy_to_abated", "cure_abatement",
    "initiate_portability", "absorb_portability",
    # Difficulty-design boundary fixtures
    "setup_burden_at_boundary", "setup_special_mobility_with_zone_b_unit",
    # Sweeps
    "sweep_monthly_hap", "sweep_abatements", "sweep_expirations", "sweep_reviews",
]
