"""Composite setup helpers for the Commercial Leasing test suite.

Most interesting test claims require the system to be in a specific
state reached through 5–15 API calls (building → unit → tenant →
approve → lease → sign → top-up → activate → move-out → inspect →
restore → propose → approve → finalize). These helpers encapsulate those
preambles so test bodies stay focused on assertions.

Identity threading (PRD §2.1):
- Tenant is ENTITY-BACKED: 'When X-User-Role is Tenant, X-User-ID is the
  id of the acting Tenant.' Every ownership-gated call by a Tenant
  principal MUST use make_tenant_headers(tenant['id']), never a shared
  fallback string.
- PropertyManager, LeasingAgent, FinanceOfficer are OPAQUE.

Setup helpers use get_success_data (lenient), so a broken precondition
surfaces as a clear setup error rather than a confusing assertion
failure inside the test body.
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
)

from .api_client import api_client
from .factories import (
    amend_lease_payload,
    clock_payload,
    confirm_restoration_payload,
    create_building_payload,
    create_energy_fee_bill_payload,
    create_lease_payload,
    create_property_fee_bill_payload,
    create_tenant_payload,
    create_unit_payload,
    dispute_fee_bill_payload,
    make_child_unit_spec,
    make_deduction_item,
    make_inspection_finding,
    make_stepped_entry,
    merge_units_payload,
    move_out_request_payload,
    propose_deductions_payload,
    record_inspection_payload,
    renew_lease_payload,
    reserve_unit_payload,
    resolve_dispute_payload,
    split_unit_payload,
    start_renovation_payload,
    top_up_payload,
    unique_unit_code,
)
from .test_users import (
    TEST_USERS,
    make_tenant_headers,
)


# ===========================================================================
# Shared role-header constants (all opaque roles, safe as module constants)
# ===========================================================================
PM = TEST_USERS["property_manager_headers"]
PM_ALT = TEST_USERS["property_manager_headers_alt"]
LA = TEST_USERS["leasing_agent_headers"]
LA_ALT = TEST_USERS["leasing_agent_headers_alt"]
FO = TEST_USERS["finance_officer_headers"]
FO_ALT = TEST_USERS["finance_officer_headers_alt"]


# ===========================================================================
# ISO 8601 helpers (PRD §2.4: ISO 8601 with three fractional digits, UTC)
# ===========================================================================
def iso_z(dt: datetime) -> str:
    """ISO 8601 UTC with millisecond precision, Z-suffixed."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def iso_date(year: int, month: int, day: int) -> str:
    """Date-only ISO 8601 UTC midnight, Z-suffixed."""
    return iso_z(datetime(year, month, day, tzinfo=timezone.utc))


# ===========================================================================
# Clock helpers (PRD §3.9)
# ===========================================================================
def advance_clock(to_iso: str,
                  headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """PRD §3.9: 'An admin-only test-driving capability advances the
    logical server clock to a supplied to instant.'"""
    return get_success_data(api_client.advance_clock(
        clock_payload(to=to_iso), headers or PM,
    ))


def run_sweep(headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """PRD §3.9: 'A second admin-only test-driving capability runs the
    scheduled sweep job that auto-voids RentScheduleItem rows whose
    period_start is strictly after the owning lease's terminated_on,
    recomputes the derived Unit.status per §3.1, and recomputes the
    tenant deposit aggregates per §2.9.'"""
    return get_success_data(api_client.run_sweep(headers or PM))


# ===========================================================================
# Building creation
# ===========================================================================
def create_building(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.1: 'Creating a Building requires a human-readable name, a
    postal address, and a floors_count integer.'"""
    return get_success_data(api_client.create_building(
        create_building_payload(**overrides), PM,
    ))


def get_building(building_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_building(building_id, PM))


# ===========================================================================
# Unit creation / queries
# ===========================================================================
def create_unit(building_id: str, **overrides: Any) -> Dict[str, Any]:
    """PRD §3.1: 'Inside a building, a PropertyManager creates Unit rows
    that represent the leasable inventory.'"""
    return get_success_data(api_client.create_unit(
        building_id, create_unit_payload(**overrides), PM,
    ))


def get_unit(building_id: str, unit_id: str,
             headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_unit(
        building_id, unit_id, headers or PM,
    ))


def reserve_unit(building_id: str, unit_id: str,
                 tenant_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.reserve_unit(
        building_id, unit_id, reserve_unit_payload(tenant_id=tenant_id), LA,
    ))


def release_reservation(building_id: str, unit_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.release_reservation(
        building_id, unit_id, LA,
    ))


def start_renovation(building_id: str, unit_id: str,
                     renovation_start_date: str,
                     renovation_end_date: str) -> Dict[str, Any]:
    return get_success_data(api_client.start_renovation(
        building_id, unit_id,
        start_renovation_payload(
            renovation_start_date=renovation_start_date,
            renovation_end_date=renovation_end_date,
        ),
        PM,
    ))


def finish_renovation(building_id: str, unit_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.finish_renovation(
        building_id, unit_id, PM,
    ))


# ===========================================================================
# Tenant creation + qualification
# ===========================================================================
def create_tenant(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.2: 'A LeasingAgent records prospective tenants.'"""
    return get_success_data(api_client.create_tenant(
        create_tenant_payload(**overrides), LA,
    ))


def approve_tenant(tenant_id: str) -> Dict[str, Any]:
    """PRD §3.2: 'transitioning qualification_status from PENDING_REVIEW
    to APPROVED.'"""
    return get_success_data(api_client.approve_tenant(tenant_id, LA))


def reject_tenant(tenant_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.reject_tenant(tenant_id, LA))


def revoke_tenant_approval(tenant_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.revoke_tenant_approval(tenant_id, LA))


def create_approved_tenant(**overrides: Any) -> Dict[str, Any]:
    """Create + approve a tenant in one step. Returns the refreshed
    Tenant row whose qualification_status is APPROVED."""
    tenant = create_tenant(**overrides)
    approved = approve_tenant(tenant["id"])
    return approved


def get_tenant(tenant_id: str,
               headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_tenant(
        tenant_id, headers or LA,
    ))


# ===========================================================================
# Lease creation / signing / activation
# ===========================================================================
def create_lease(*, unit_id: str, tenant_id: str,
                 start_date: str, end_date: str,
                 **overrides: Any) -> Dict[str, Any]:
    """PRD §3.3: 'A leasing agent drafts a lease by supplying the unit_id
    and tenant_id, a start_date and end_date ...' """
    return get_success_data(api_client.create_lease(
        create_lease_payload(
            unit_id=unit_id, tenant_id=tenant_id,
            start_date=start_date, end_date=end_date,
            **overrides,
        ),
        LA,
    ))


def sign_lease(lease_id: str) -> Dict[str, Any]:
    """PRD §3.3: 'Signing a drafted lease moves it from DRAFT to SIGNED.'"""
    return get_success_data(api_client.sign_lease(lease_id, LA))


def activate_lease(lease_id: str) -> Dict[str, Any]:
    """PRD §3.5: 'Once signed, a lease is brought live by activating it.'"""
    return get_success_data(api_client.activate_lease(lease_id, LA))


def amend_lease(lease_id: str, *, effective_from: str,
                **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api_client.amend_lease(
        lease_id,
        amend_lease_payload(effective_from=effective_from, **overrides),
        LA,
    ))


def amend_confirm(lease_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.amend_confirm_lease(lease_id, FO))


def amend_cancel(lease_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.amend_cancel_lease(lease_id, LA))


def renew_lease(lease_id: str, *, new_end_date: str,
                **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api_client.renew_lease(
        lease_id,
        renew_lease_payload(new_end_date=new_end_date, **overrides),
        LA,
    ))


def get_lease(lease_id: str,
              headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_lease(
        lease_id, headers or LA,
    ))


def get_rent_schedule(lease_id: str,
                      headers: Optional[Dict[str, str]] = None,
                      params: Optional[Dict[str, Any]] = None,
                      ) -> List[Dict[str, Any]]:
    res = api_client.get_rent_schedule(
        lease_id, headers or LA, params=params or {"limit": 100},
    )
    rows, _meta = validate_paginated(res)
    return rows


# ===========================================================================
# Deposit
# ===========================================================================
def get_deposit(deposit_id: str,
                headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_deposit(
        deposit_id, headers or LA,
    ))


def top_up_deposit(deposit_id: str, *, tenant_id: str,
                   amount_cents: int) -> Dict[str, Any]:
    """PRD §3.6 + §2.1: top-up is ownership-gated. The acting principal
    must be the deposit's owning lease's tenant; we thread Tenant.id."""
    return get_success_data(api_client.top_up_deposit(
        deposit_id,
        top_up_payload(amount_cents=amount_cents),
        make_tenant_headers(tenant_id),
    ))


def propose_deductions(deposit_id: str,
                       deduction_items: List[Dict[str, Any]],
                       ) -> Dict[str, Any]:
    return get_success_data(api_client.propose_deductions(
        deposit_id,
        propose_deductions_payload(deduction_items=deduction_items),
        PM,
    ))


def approve_deductions(deposit_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.approve_deductions(deposit_id, FO))


def reject_deductions(deposit_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.reject_deductions(deposit_id, FO))


# ===========================================================================
# Move-out workflow
# ===========================================================================
def move_out_request(lease_id: str, *, tenant_id: str,
                     target_move_out_date: str) -> Dict[str, Any]:
    """PRD §3.8 + §2.1: 'a tenant initiates a move-out from an ACTIVE
    lease'. The acting Tenant must be the lease's tenant — thread id."""
    return get_success_data(api_client.move_out_request(
        lease_id,
        move_out_request_payload(target_move_out_date=target_move_out_date),
        make_tenant_headers(tenant_id),
    ))


def record_inspection(request_id: str,
                      inspection_findings: Optional[List[Dict[str, Any]]] = None,
                      ) -> Dict[str, Any]:
    return get_success_data(api_client.record_inspection(
        request_id,
        record_inspection_payload(
            inspection_findings=inspection_findings or [],
        ),
        PM,
    ))


def confirm_restoration(request_id: str,
                        restoration_done: bool = True) -> Dict[str, Any]:
    return get_success_data(api_client.confirm_restoration(
        request_id,
        confirm_restoration_payload(restoration_done=restoration_done),
        PM,
    ))


def reject_move_out(request_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.reject_move_out(request_id, PM))


def finalize_move_out(request_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.finalize_move_out(request_id, FO))


def get_move_out_request(
    request_id: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(api_client.get_move_out_request(
        request_id, headers or FO,
    ))


# ===========================================================================
# Fee bills
# ===========================================================================
def create_property_fee_bill(*, lease_id: str, period_start: str,
                             period_end: str, property_fee_mode: str,
                             **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api_client.create_fee_bill(
        create_property_fee_bill_payload(
            lease_id=lease_id, period_start=period_start,
            period_end=period_end, property_fee_mode=property_fee_mode,
            **overrides,
        ),
        FO,
    ))


def create_energy_fee_bill(*, lease_id: str, period_start: str,
                           period_end: str, energy_mode: str,
                           tariff_per_kwh_cents: int,
                           **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api_client.create_fee_bill(
        create_energy_fee_bill_payload(
            lease_id=lease_id, period_start=period_start,
            period_end=period_end, energy_mode=energy_mode,
            tariff_per_kwh_cents=tariff_per_kwh_cents,
            **overrides,
        ),
        FO,
    ))


def get_fee_bill(bill_id: str,
                 headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_fee_bill(
        bill_id, headers or FO,
    ))


def pay_fee_bill(bill_id: str, *, tenant_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.pay_fee_bill(
        bill_id, make_tenant_headers(tenant_id),
    ))


def dispute_fee_bill(bill_id: str, *, tenant_id: str,
                     dispute_reason: str = "Dispute reason") -> Dict[str, Any]:
    return get_success_data(api_client.dispute_fee_bill(
        bill_id,
        dispute_fee_bill_payload(dispute_reason=dispute_reason),
        make_tenant_headers(tenant_id),
    ))


def resolve_dispute(bill_id: str, *,
                    resolution_keeps_bill: bool) -> Dict[str, Any]:
    return get_success_data(api_client.resolve_dispute_fee_bill(
        bill_id, resolve_dispute_payload(
            resolution_keeps_bill=resolution_keeps_bill,
        ),
        FO,
    ))


def void_fee_bill(bill_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.void_fee_bill(bill_id, FO))


# ===========================================================================
# Audit events
# ===========================================================================
def list_audit_events(
    *,
    subject_kind: Optional[str] = None,
    subject_id: Optional[str] = None,
    action: Optional[str] = None,
    since: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    """PRD §3.9: 'Property managers and finance officers can list the
    audit trail with optional filters: subject_kind, subject_id, action,
    and since.'"""
    params: Dict[str, Any] = {"limit": 100}
    if subject_kind is not None:
        params["subject_kind"] = subject_kind
    if subject_id is not None:
        params["subject_id"] = subject_id
    if action is not None:
        params["action"] = action
    if since is not None:
        params["since"] = since
    res = api_client.list_audit_events(headers or PM, params=params)
    rows, _meta = validate_paginated(res)
    return rows


# ===========================================================================
# Composite Tier 1/2: building + unit
# ===========================================================================
def setup_building_with_unit(
    *,
    floors_count: int = 10,
    floor: int = 1,
    area_sqm: float = 100.0,
    unit_code: Optional[str] = None,
    orientation: str = "N",
    usage_type: str = "OFFICE",
    rent_reference_per_sqm: float = 100.0,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Tier 2: Create an ACTIVE building plus one VACANT unit. Returns
    (building, unit)."""
    building = create_building(floors_count=floors_count)
    unit = create_unit(
        building["id"],
        floor=floor,
        code=unit_code or unique_unit_code(),
        area_sqm=area_sqm,
        orientation=orientation,
        usage_type=usage_type,
        rent_reference_per_sqm=rent_reference_per_sqm,
    )
    return building, unit


def setup_building_with_two_units(
    *,
    area_sqm_a: float = 100.0,
    area_sqm_b: float = 100.0,
    floor: int = 1,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Two VACANT units on the same floor of the same building (used by
    merge and energy-allocation tests)."""
    building = create_building()
    unit_a = create_unit(
        building["id"],
        floor=floor, area_sqm=area_sqm_a, code=unique_unit_code("A"),
    )
    unit_b = create_unit(
        building["id"],
        floor=floor, area_sqm=area_sqm_b, code=unique_unit_code("B"),
    )
    return building, unit_a, unit_b


# ===========================================================================
# Composite Tier 3: lease in a specific lifecycle stage
# ===========================================================================
def setup_draft_lease(
    *,
    start_date: str = "2026-01-01T00:00:00.000Z",
    end_date: str = "2026-12-01T00:00:00.000Z",
    base_monthly_rent_cents: int = 100000,
    deposit_months: int = 1,
    escalation_mode: str = "NONE",
    rent_free_days: Any = "__OMIT__",
    stepped_schedule: Any = "__OMIT__",
    escalation_pct_bps: Any = "__OMIT__",
    unit_area_sqm: float = 100.0,
) -> Dict[str, Any]:
    """Tier 3: minimum viable state to test draft-creation rules.

    Returns a context dict with keys: building, unit, tenant, lease.
    Tenant is APPROVED (signing precondition); unit is VACANT.
    """
    building, unit = setup_building_with_unit(area_sqm=unit_area_sqm)
    tenant = create_approved_tenant()
    extra: Dict[str, Any] = {}
    if rent_free_days != "__OMIT__":
        extra["rent_free_days"] = rent_free_days
    if stepped_schedule != "__OMIT__":
        extra["stepped_schedule"] = stepped_schedule
    if escalation_pct_bps != "__OMIT__":
        extra["escalation_pct_bps"] = escalation_pct_bps
    lease = create_lease(
        unit_id=unit["id"], tenant_id=tenant["id"],
        start_date=start_date, end_date=end_date,
        base_monthly_rent_cents=base_monthly_rent_cents,
        escalation_mode=escalation_mode,
        deposit_months=deposit_months,
        **extra,
    )
    return {
        "building": building, "unit": unit,
        "tenant": tenant, "lease": lease,
    }


def setup_signed_lease(**lease_overrides: Any) -> Dict[str, Any]:
    """Tier 3: lease in SIGNED state, plus the auto-created Deposit row.

    Returns context with keys: building, unit, tenant, lease, deposit.
    PRD §3.3: 'On success ... a Deposit row is created with
    required_cents equal to deposit_months × base_monthly_rent_cents'."""
    ctx = setup_draft_lease(**lease_overrides)
    lease = sign_lease(ctx["lease"]["id"])
    ctx["lease"] = lease
    # Discover the auto-created Deposit by re-reading the lease, then
    # locating its deposit via /audit-events (which references the
    # deposit subject_id) or by /leases/.../get if it exposes it. The
    # simplest path: list deposits for this lease isn't an endpoint, so
    # we recover the deposit_id from an AuditEvent or by scanning
    # /audit-events for action=CONTRACT_SIGNED. PRD does NOT spec a
    # /leases/{id}/deposit endpoint, but the Lease response is allowed
    # to expose deposit_id; we DON'T assume that. We use audit-events.
    audits = list_audit_events(
        subject_kind="LEASE", subject_id=lease["id"],
        action="CONTRACT_SIGNED",
    )
    deposit_id: Optional[str] = None
    for a in audits:
        payload = a.get("payload", {}) or {}
        if "deposit_id" in payload:
            deposit_id = payload["deposit_id"]
            break
    if deposit_id is None:
        # Fallback: PRD §3.3 says Deposit is created at sign-time and is
        # bound 1:1 to the lease. Implementations should expose a way to
        # find it; we look at recent DEPOSIT-kind audit subjects bound
        # to this lease's tenant via the move-out chain (only valid post
        # propose-deductions). Here we retry once via 'Lease' get and
        # rely on a 'deposit_id' field if present.
        relead = get_lease(lease["id"])
        deposit_id = relead.get("deposit_id")
    assert deposit_id is not None, (
        "Setup failed: could not discover Deposit id for signed lease "
        f"{lease['id']}. PRD §3.3 says a Deposit row is created at sign "
        "time — expose deposit_id on Lease or include it in the "
        "CONTRACT_SIGNED audit payload."
    )
    deposit = get_deposit(deposit_id)
    ctx["deposit"] = deposit
    return ctx


def setup_active_lease(
    *,
    clock_to: str = "2026-01-01T00:00:00.000Z",
    **lease_overrides: Any,
) -> Dict[str, Any]:
    """Tier 3: lease in ACTIVE state.

    Walks the full chain: build + unit + tenant + lease + sign +
    deposit top-up to required_cents + clock advance to start_date +
    activate. Returns context with: building, unit, tenant, lease,
    deposit (all freshly re-read).
    """
    # Default start_date is 2026-01-01; clock_to default ensures start
    # is reached.
    ctx = setup_signed_lease(**lease_overrides)
    deposit = ctx["deposit"]
    tenant = ctx["tenant"]
    lease = ctx["lease"]

    # Top up to required.
    required = deposit["required_cents"]
    if required > 0:
        deposit = top_up_deposit(
            deposit["id"], tenant_id=tenant["id"], amount_cents=required,
        )
        ctx["deposit"] = deposit

    # Advance clock to or past start_date.
    advance_clock(clock_to)

    # Activate.
    lease = activate_lease(lease["id"])
    ctx["lease"] = lease
    ctx["deposit"] = get_deposit(deposit["id"])
    ctx["tenant"] = get_tenant(tenant["id"])
    return ctx


# ===========================================================================
# Composite Tier 4: move-out lifecycle stages
# ===========================================================================
def setup_terminating_lease(
    *,
    start_date: str = "2026-01-01T00:00:00.000Z",
    end_date: str = "2026-12-01T00:00:00.000Z",
    activate_clock: str = "2026-01-01T00:00:00.000Z",
    move_out_clock: str = "2026-02-01T00:00:00.000Z",
    target_move_out_date: str = "2026-03-15T00:00:00.000Z",
    **lease_overrides: Any,
) -> Dict[str, Any]:
    """Tier 4: lease in TERMINATING state with a MoveOutRequest in
    SUBMITTED status, Deposit FROZEN+AT_REST. Returns context with:
    building, unit, tenant, lease, deposit, move_out_request."""
    ctx = setup_active_lease(
        start_date=start_date, end_date=end_date,
        clock_to=activate_clock, **lease_overrides,
    )
    advance_clock(move_out_clock)
    mor = move_out_request(
        ctx["lease"]["id"],
        tenant_id=ctx["tenant"]["id"],
        target_move_out_date=target_move_out_date,
    )
    ctx["move_out_request"] = mor
    ctx["lease"] = get_lease(ctx["lease"]["id"])
    ctx["deposit"] = get_deposit(ctx["deposit"]["id"])
    return ctx


def setup_restoration_confirmed(
    *,
    inspection_findings: Optional[List[Dict[str, Any]]] = None,
    **terminating_overrides: Any,
) -> Dict[str, Any]:
    """Tier 4: TERMINATING + inspection done + restoration confirmed.

    MoveOutRequest is in RESTORATION_CONFIRMED; deposit still
    AT_REST+FROZEN; lease still TERMINATING.
    """
    ctx = setup_terminating_lease(**terminating_overrides)
    mor = ctx["move_out_request"]
    mor = record_inspection(mor["id"], inspection_findings or [])
    mor = confirm_restoration(mor["id"], restoration_done=True)
    ctx["move_out_request"] = mor
    return ctx


def setup_deduction_approved(
    *,
    deduction_items: Optional[List[Dict[str, Any]]] = None,
    **restoration_overrides: Any,
) -> Dict[str, Any]:
    """Tier 4: deductions proposed AND approved.

    MoveOutRequest in DEDUCTION_APPROVED; Deposit in SETTLED;
    lease still TERMINATING; ready for finalize.
    """
    ctx = setup_restoration_confirmed(**restoration_overrides)
    deposit = ctx["deposit"]
    if deduction_items is None:
        # PRD §3.8 requires deduction items have kind/amount_cents and
        # the sum must not exceed collected_cents. A single zero-amount
        # CLEANING item is the minimal valid payload that drives the
        # state machine forward without retaining any cents.
        items = [{"kind": "CLEANING", "amount_cents": 0, "note": "n/a"}]
    else:
        items = deduction_items
    propose_deductions(deposit["id"], items)
    deposit = approve_deductions(deposit["id"])
    ctx["deposit"] = deposit
    ctx["move_out_request"] = get_move_out_request(
        ctx["move_out_request"]["id"],
    )
    return ctx


def setup_finalized_lease(**ctx_overrides: Any) -> Dict[str, Any]:
    """Tier 5: full lifecycle through TERMINATED.

    Useful for testing the cascade: Lease=TERMINATED, MoveOut=SETTLED,
    Unit=VACANT, future RentScheduleItem rows=VOIDED, AuditEvent
    CONTRACT_TERMINATED emitted.
    """
    ctx = setup_deduction_approved(**ctx_overrides)
    finalize_move_out(ctx["move_out_request"]["id"])
    ctx["lease"] = get_lease(ctx["lease"]["id"])
    ctx["deposit"] = get_deposit(ctx["deposit"]["id"])
    ctx["unit"] = get_unit(ctx["building"]["id"], ctx["unit"]["id"])
    ctx["move_out_request"] = get_move_out_request(
        ctx["move_out_request"]["id"],
    )
    ctx["tenant"] = get_tenant(ctx["tenant"]["id"])
    return ctx


# ===========================================================================
# Difficulty-design helpers (pre-built setups for SCAFFOLD_DIFFICULTY_DESIGN)
# ===========================================================================
def setup_stepped_vs_annual_pair() -> Dict[str, Any]:
    """SCAFFOLD_DIFFICULTY_DESIGN rule dual_variant_calc / instance
    rent_schedule_stepped_vs_annual: two leases on two different units
    (to avoid overlap), one ANNUAL escalation and one STEPPED.

    Returns context with: building, unit_annual, unit_stepped, tenant,
    lease_annual, lease_stepped.
    """
    building = create_building()
    unit_annual = create_unit(
        building["id"], code=unique_unit_code("A"), area_sqm=100.0,
    )
    unit_stepped = create_unit(
        building["id"], code=unique_unit_code("S"), area_sqm=100.0,
    )
    tenant = create_approved_tenant()
    start = "2026-01-01T00:00:00.000Z"
    end = "2026-12-01T00:00:00.000Z"
    lease_annual = create_lease(
        unit_id=unit_annual["id"], tenant_id=tenant["id"],
        start_date=start, end_date=end,
        base_monthly_rent_cents=100000,
        escalation_mode="ANNUAL",
        escalation_pct_bps=500,
        deposit_months=1,
    )
    stepped_schedule = [
        make_stepped_entry(
            effective_from="2026-01-01T00:00:00.000Z",
            monthly_rent_cents=100000,
        ),
        make_stepped_entry(
            effective_from="2026-07-01T00:00:00.000Z",
            monthly_rent_cents=110000,
        ),
    ]
    lease_stepped = create_lease(
        unit_id=unit_stepped["id"], tenant_id=tenant["id"],
        start_date=start, end_date=end,
        base_monthly_rent_cents=100000,
        escalation_mode="STEPPED",
        stepped_schedule=stepped_schedule,
        deposit_months=1,
    )
    sign_lease(lease_annual["id"])
    sign_lease(lease_stepped["id"])
    return {
        "building": building,
        "unit_annual": unit_annual,
        "unit_stepped": unit_stepped,
        "tenant": tenant,
        "lease_annual": get_lease(lease_annual["id"]),
        "lease_stepped": get_lease(lease_stepped["id"]),
    }


def setup_two_active_leases_for_energy_allocation(
    *,
    area_a: float = 100.0,
    area_b: float = 300.0,
    activate_clock: str = "2026-01-01T00:00:00.000Z",
) -> Dict[str, Any]:
    """SCAFFOLD_DIFFICULTY_DESIGN rule dual_variant_calc / instance
    energy_sub_meter_vs_allocated: two ACTIVE leases on two units in
    the same building so that ALLOCATED energy bills can reference both
    as shared_meter_group_unit_ids."""
    building, unit_a, unit_b = setup_building_with_two_units(
        area_sqm_a=area_a, area_sqm_b=area_b,
    )
    tenant_a = create_approved_tenant()
    tenant_b = create_approved_tenant()

    start = "2026-01-01T00:00:00.000Z"
    end = "2027-01-01T00:00:00.000Z"

    lease_a = create_lease(
        unit_id=unit_a["id"], tenant_id=tenant_a["id"],
        start_date=start, end_date=end,
        base_monthly_rent_cents=100000, deposit_months=1,
    )
    lease_a = sign_lease(lease_a["id"])
    lease_b = create_lease(
        unit_id=unit_b["id"], tenant_id=tenant_b["id"],
        start_date=start, end_date=end,
        base_monthly_rent_cents=100000, deposit_months=1,
    )
    lease_b = sign_lease(lease_b["id"])

    # Top up both deposits and activate both leases.
    dep_a = _deposit_for_lease(lease_a["id"])
    dep_b = _deposit_for_lease(lease_b["id"])
    top_up_deposit(
        dep_a["id"], tenant_id=tenant_a["id"],
        amount_cents=dep_a["required_cents"],
    )
    top_up_deposit(
        dep_b["id"], tenant_id=tenant_b["id"],
        amount_cents=dep_b["required_cents"],
    )
    advance_clock(activate_clock)
    lease_a = activate_lease(lease_a["id"])
    lease_b = activate_lease(lease_b["id"])
    return {
        "building": building,
        "unit_a": unit_a, "unit_b": unit_b,
        "tenant_a": tenant_a, "tenant_b": tenant_b,
        "lease_a": lease_a, "lease_b": lease_b,
        "deposit_a": get_deposit(dep_a["id"]),
        "deposit_b": get_deposit(dep_b["id"]),
    }


def _deposit_for_lease(lease_id: str) -> Dict[str, Any]:
    """Recover the auto-created Deposit row id from CONTRACT_SIGNED
    audit events (whose payload references the deposit) or fall back to
    the lease's deposit_id field."""
    audits = list_audit_events(
        subject_kind="LEASE", subject_id=lease_id,
        action="CONTRACT_SIGNED",
    )
    for a in audits:
        payload = a.get("payload", {}) or {}
        if "deposit_id" in payload:
            return get_deposit(payload["deposit_id"])
    lease = get_lease(lease_id)
    if lease.get("deposit_id"):
        return get_deposit(lease["deposit_id"])
    raise AssertionError(
        f"Setup failed: could not discover Deposit for lease {lease_id}. "
        "PRD §3.3 creates the Deposit at sign time; expose deposit_id "
        "on the Lease or in the CONTRACT_SIGNED audit payload."
    )


__all__ = [
    # role-header shortcuts
    "PM", "PM_ALT", "LA", "LA_ALT", "FO", "FO_ALT",
    # iso helpers
    "iso_z", "iso_date",
    # clock + sweep
    "advance_clock", "run_sweep",
    # buildings
    "create_building", "get_building",
    # units
    "create_unit", "get_unit", "reserve_unit", "release_reservation",
    "start_renovation", "finish_renovation",
    # tenants
    "create_tenant", "approve_tenant", "reject_tenant",
    "revoke_tenant_approval", "create_approved_tenant",
    "get_tenant",
    # leases
    "create_lease", "sign_lease", "activate_lease",
    "amend_lease", "amend_confirm", "amend_cancel",
    "renew_lease", "get_lease", "get_rent_schedule",
    # deposits
    "get_deposit", "top_up_deposit", "propose_deductions",
    "approve_deductions", "reject_deductions",
    # move-out
    "move_out_request", "record_inspection", "confirm_restoration",
    "reject_move_out", "finalize_move_out", "get_move_out_request",
    # fee bills
    "create_property_fee_bill", "create_energy_fee_bill",
    "get_fee_bill", "pay_fee_bill", "dispute_fee_bill",
    "resolve_dispute", "void_fee_bill",
    # audit
    "list_audit_events",
    # composite setups
    "setup_building_with_unit",
    "setup_building_with_two_units",
    "setup_draft_lease",
    "setup_signed_lease",
    "setup_active_lease",
    "setup_terminating_lease",
    "setup_restoration_confirmed",
    "setup_deduction_approved",
    "setup_finalized_lease",
    # difficulty-design helpers
    "setup_stepped_vs_annual_pair",
    "setup_two_active_leases_for_energy_allocation",
]
