"""Composite setup helpers for the Parcel Pickup Station test suite.

Most interesting test claims require the system to be in a specific
state that takes 5-15 API calls to reach: a Station with a ShelfZone
plus Manager/Clerk Staff so the test holds ownership-bound headers; a
Parcel walked to SHELVED / OVERTIME / AWAITING_RETURN by clock + sweep;
a BillingPeriod with its companion QualityAssessment both CLOSED so
final_total is computable.

Identity threading (PRD §2.1):

- Manager and Clerk are entity-backed -- 'X-User-ID is the id of the
  acting Staff record.' Fixtures create real Staff rows under each
  station and return make_manager_headers(staff_id) /
  make_clerk_headers(staff_id) so any ownership comparison resolves.

- PlatformAdmin, Recipient, CourierCompany, PaymentSystem are opaque;
  the shared TEST_USERS constants are canonical for those roles.

Setup calls use get_success_data (lenient validator) so broken
preconditions surface as obvious 'Setup failed' errors rather than
confusing assertion failures inside tests.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
)

from .api_client import api_client
from .constants import (
    DEFAULT_FREE_STORAGE_HOURS,
    DISPOSAL_GRACE_HOURS,
    ESCALATION_HOURS,
    HANDOVER_FEE_PER_PARCEL,
    LONG_STAY_HOURS,
)
from .factories import (
    clock_advance_payload,
    courier_inbound_handshake_payload,
    courier_response_payload,
    create_authorization_payload,
    create_billing_period_payload,
    create_quality_assessment_payload,
    create_shelf_zone_payload,
    create_staff_payload,
    create_station_payload,
    dispute_bill_payload,
    pay_bill_payload,
    pickup_by_code_payload,
    pickup_by_face_match_payload,
    register_parcel_payload,
    request_return_payload,
    reissue_pickup_code_payload,
    ship_return_payload,
    sweep_payload,
    unique_courier_company_id,
    unique_idempotency_key,
    unique_recipient_phone,
    unique_tracking_number,
)
from .test_users import (
    TEST_USERS,
    make_clerk_headers,
    make_manager_headers,
    make_recipient_headers,
)


# ===========================================================================
# Time helpers (PRD §2.4 / §2.7)
# ===========================================================================
def iso_z(dt: datetime) -> str:
    """Format a datetime as ISO 8601 UTC with three fractional digits.

    PRD §2.4: 'ISO 8601 UTC timestamps with three fractional digits.'
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    millis = f"{dt.microsecond // 1000:03d}"
    return f"{base}.{millis}Z"


def parse_iso(s: str) -> datetime:
    """Parse an ISO 8601 string (with optional trailing 'Z') to tz-aware."""
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def add_seconds(dt_iso: str, seconds: int) -> str:
    return iso_z(parse_iso(dt_iso) + timedelta(seconds=seconds))


def add_hours(dt_iso: str, hours: int) -> str:
    return iso_z(parse_iso(dt_iso) + timedelta(hours=hours))


def add_days(dt_iso: str, days: int) -> str:
    return iso_z(parse_iso(dt_iso) + timedelta(days=days))


# ===========================================================================
# Clock + sweep primitives (PRD §3.5)
# ===========================================================================
def advance_clock(seconds: int) -> Dict[str, Any]:
    """Advance the server's logical clock by `seconds` seconds."""
    resp = api_client.advance_clock(
        clock_advance_payload(seconds),
        TEST_USERS["platform_admin_headers"],
    )
    return get_success_data(resp)


def advance_clock_hours(hours: int) -> Dict[str, Any]:
    return advance_clock(hours * 3600)


def run_sweep(station_id: Optional[str] = None,
              admin_headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Run the platform-wide overtime + long-stay sweep."""
    headers = admin_headers or TEST_USERS["platform_admin_headers"]
    resp = api_client.run_sweep(headers, sweep_payload(station_id))
    return get_success_data(resp)


# ===========================================================================
# Station / Zone / Staff bootstrap
# ===========================================================================
def create_station(
    *,
    storage_capacity: int = 50,
    free_storage_hours: int = DEFAULT_FREE_STORAGE_HOURS,
    name: Optional[str] = None,
    status: Optional[str] = None,
    admin_headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Create a Station as PlatformAdmin and return the dict."""
    headers = admin_headers or TEST_USERS["platform_admin_headers"]
    payload = create_station_payload(
        storage_capacity=storage_capacity,
        free_storage_hours=free_storage_hours,
        **overrides,
    )
    if name is not None:
        payload["name"] = name
    resp = api_client.create_station(payload, headers)
    station = get_success_data(resp)
    # If caller asked for a SUSPENDED / CLOSED station, patch it now.
    if status is not None and status != station.get("status"):
        patch_resp = api_client.patch_station(
            station["id"], {"status": status},
            TEST_USERS["platform_admin_headers"],
        )
        station = get_success_data(patch_resp)
    return station


def create_manager_staff(
    station_id: str,
    *,
    full_name: Optional[str] = None,
    phone: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a MANAGER role_kind staff at the station.

    The caller bootstraps via a temporary manager-fallback header to
    create the very first manager; that fallback works because the
    fixture below immediately switches all subsequent manager calls to
    make_manager_headers(staff['id']). Returns the staff dict.
    """
    payload = create_staff_payload(
        full_name=full_name or f"Manager {station_id[:8]}",
        phone=phone or unique_recipient_phone(),
        role_kind="MANAGER",
    )
    resp = api_client.create_staff(
        station_id, payload, TEST_USERS["manager_headers"],
    )
    return get_success_data(resp)


def create_clerk_staff(
    station_id: str,
    manager_headers: Dict[str, str],
    *,
    full_name: Optional[str] = None,
    phone: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a CLERK role_kind staff at the station using manager creds.

    PRD §3.1: 'each staff record is addressed by its staff_id and carries
    the station's station_id, the staff member's full_name, a contact
    phone consisting of 6 to 15 digit characters, and a role_kind of
    either CLERK or MANAGER.'
    """
    payload = create_staff_payload(
        full_name=full_name or f"Clerk {station_id[:8]}",
        phone=phone or unique_recipient_phone(),
        role_kind="CLERK",
    )
    resp = api_client.create_staff(station_id, payload, manager_headers)
    return get_success_data(resp)


def create_shelf_zone(
    station_id: str,
    manager_headers: Dict[str, str],
    *,
    row_count: int = 2,
    column_count: int = 2,
    zone_type: str = "STANDARD",
    zone_code: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a ShelfZone under the station."""
    payload = create_shelf_zone_payload(
        row_count=row_count,
        column_count=column_count,
        zone_type=zone_type,
    )
    if zone_code is not None:
        payload["zone_code"] = zone_code
    resp = api_client.create_shelf_zone(station_id, payload, manager_headers)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Composite station bootstrap: station + manager + clerk + one zone.
# Returns a context dict so tests can grab whichever pieces they need.
# ---------------------------------------------------------------------------
def setup_station_with_staff(
    *,
    storage_capacity: int = 50,
    free_storage_hours: int = DEFAULT_FREE_STORAGE_HOURS,
    zone_row_count: int = 2,
    zone_col_count: int = 2,
    zone_type: str = "STANDARD",
    create_zone: bool = True,
    station_status: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a station, a Manager staff, a Clerk staff, and one zone.

    Returns a dict carrying:
        station, manager, clerk, zone, manager_headers, clerk_headers.

    Identity threading (PRD §2.1): manager_headers and clerk_headers
    are built from the actual Staff.id rows so any ownership check in
    subsequent calls resolves correctly.
    """
    station = create_station(
        storage_capacity=storage_capacity,
        free_storage_hours=free_storage_hours,
    )
    manager = create_manager_staff(station["id"])
    manager_headers = make_manager_headers(manager["id"])
    clerk = create_clerk_staff(station["id"], manager_headers)
    clerk_headers = make_clerk_headers(clerk["id"])
    zone: Optional[Dict[str, Any]] = None
    if create_zone:
        zone = create_shelf_zone(
            station["id"], manager_headers,
            row_count=zone_row_count,
            column_count=zone_col_count,
            zone_type=zone_type,
        )
    # Optionally suspend / close the station AFTER staff + zone are set up.
    if station_status is not None and station_status != station.get("status"):
        patch_resp = api_client.patch_station(
            station["id"], {"status": station_status},
            TEST_USERS["platform_admin_headers"],
        )
        station = get_success_data(patch_resp)
    return {
        "station": station,
        "manager": manager,
        "clerk": clerk,
        "zone": zone,
        "manager_headers": manager_headers,
        "clerk_headers": clerk_headers,
    }


# ===========================================================================
# Parcel lifecycle helpers
# ===========================================================================
def _pick_position(zone: Dict[str, Any], slot_index: int = 0) -> str:
    """Compute a free slot label like 'Rxx-Cyy' inside `zone`."""
    cols = zone["column_count"]
    row = (slot_index // cols) + 1
    col = (slot_index % cols) + 1
    return f"R{row:02d}-C{col:02d}"


def register_shelved_parcel(
    ctx: Dict[str, Any],
    *,
    slot_index: int = 0,
    size_class: str = "M",
    weight_grams: int = 500,
    recipient_phone: Optional[str] = None,
    tracking_number: Optional[str] = None,
    courier_company_id: Optional[str] = None,
    zone: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Register a parcel onto a free slot of the context's shelf zone.

    PRD §3.2 normal acceptance path -- emits the SHELVED transition
    with all the side effects (pickup code mint, reminder, audit, IM
    event). Returns the parcel dict.
    """
    zone = zone or ctx["zone"]
    position = _pick_position(zone, slot_index)
    payload = register_parcel_payload(
        courier_company_id=courier_company_id,
        tracking_number=tracking_number,
        recipient_phone=recipient_phone or unique_recipient_phone(),
        weight_grams=weight_grams,
        size_class=size_class,
        shelf_zone_id=zone["id"],
        shelf_position=position,
    )
    resp = api_client.register_parcel(
        ctx["station"]["id"], payload, ctx["clerk_headers"],
    )
    return get_success_data(resp)


def register_rejected_parcel(
    ctx: Dict[str, Any],
    *,
    exception_type: str = "DAMAGED",
    courier_company_id: Optional[str] = None,
    tracking_number: Optional[str] = None,
    recipient_phone: Optional[str] = None,
) -> Dict[str, Any]:
    """Register an exception parcel -- UNREGISTERED -> REJECTED."""
    payload = register_parcel_payload(
        courier_company_id=courier_company_id,
        tracking_number=tracking_number,
        recipient_phone=recipient_phone or unique_recipient_phone(),
        weight_grams=400,
        size_class="M",
        exception_type=exception_type,
    )
    resp = api_client.register_parcel(
        ctx["station"]["id"], payload, ctx["clerk_headers"],
    )
    return get_success_data(resp)


def fetch_active_pickup_code(parcel_id: str,
                             headers: Dict[str, str]) -> Dict[str, Any]:
    """Return the single ACTIVE PickupCode for the parcel.

    PRD §3.3: 'at most one ACTIVE code exists per parcel at any moment.'
    """
    resp = api_client.list_pickup_codes(
        parcel_id, headers, params={"status": "ACTIVE", "limit": 100},
    )
    data, _meta = validate_paginated(resp)
    if not data:
        raise AssertionError(
            f"Setup failed: no ACTIVE PickupCode found for parcel {parcel_id}"
        )
    return data[0]


def drive_parcel_to_overtime(
    ctx: Dict[str, Any],
    parcel: Dict[str, Any],
) -> Dict[str, Any]:
    """Advance clock past free_storage_deadline and run sweep so the
    parcel transitions SHELVED -> OVERTIME.

    PRD §3.5: 'for each parcel still in SHELVED where the current
    server time is at or after its free_storage_deadline ... the parcel
    is advanced from SHELVED to OVERTIME.'
    """
    free_hours = ctx["station"]["free_storage_hours"]
    advance_clock_hours(free_hours + 1)
    run_sweep()
    refreshed = get_success_data(
        api_client.get_parcel(parcel["id"], ctx["clerk_headers"])
    )
    return refreshed


def drive_parcel_to_awaiting_return(
    ctx: Dict[str, Any],
    parcel: Dict[str, Any],
) -> Dict[str, Any]:
    """Advance clock to >= shelved_at + 168h and sweep so parcel
    transitions OVERTIME -> AWAITING_RETURN.

    PRD §3.5: 'for each parcel currently in OVERTIME where the current
    server time is at or after shelved_at plus 168 hours, the parcel
    is advanced from OVERTIME to AWAITING_RETURN, long_stay_flagged_at
    is stamped to the current time.'
    """
    # If still SHELVED, advance through OVERTIME first.
    parcel = get_success_data(
        api_client.get_parcel(parcel["id"], ctx["clerk_headers"])
    )
    if parcel["status"] == "SHELVED":
        parcel = drive_parcel_to_overtime(ctx, parcel)
    # Now advance enough to cross 168h since shelved_at.
    advance_clock_hours(LONG_STAY_HOURS)
    run_sweep()
    return get_success_data(
        api_client.get_parcel(parcel["id"], ctx["clerk_headers"])
    )


def pickup_with_code(
    ctx: Dict[str, Any],
    parcel: Dict[str, Any],
) -> Dict[str, Any]:
    """Pick up `parcel` using its current ACTIVE pickup code."""
    code = fetch_active_pickup_code(parcel["id"], ctx["clerk_headers"])
    resp = api_client.pickup_parcel(
        parcel["id"],
        pickup_by_code_payload(code["code"]),
        ctx["clerk_headers"],
    )
    return get_success_data(resp)


def pickup_with_face_match(
    ctx: Dict[str, Any],
    parcel: Dict[str, Any],
) -> Dict[str, Any]:
    resp = api_client.pickup_parcel(
        parcel["id"],
        pickup_by_face_match_payload(True),
        ctx["clerk_headers"],
    )
    return get_success_data(resp)


# ===========================================================================
# Authorization helpers
# ===========================================================================
def create_authorization(
    parcel: Dict[str, Any],
    *,
    expires_at_iso: Optional[str] = None,
    delegate_id_number: str = "ID-DELEGATE-1",
    recipient_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Create a PickupAuthorization for `parcel`.

    PRD §3.4: 'the expires_at must be strictly later than the
    just-stamped granted_at and no later than the parcel's
    free_storage_deadline plus seven days.'
    """
    if expires_at_iso is None:
        # Default: free_storage_deadline + 1 day (well inside window).
        deadline = parcel.get("free_storage_deadline")
        if deadline:
            expires_at_iso = add_days(deadline, 1)
        else:
            now = datetime.now(tz=timezone.utc) + timedelta(days=1)
            expires_at_iso = iso_z(now)
    headers = recipient_headers or TEST_USERS["recipient_headers"]
    resp = api_client.create_authorization(
        parcel["id"],
        create_authorization_payload(
            expires_at=expires_at_iso,
            delegate_id_number=delegate_id_number,
        ),
        headers,
    )
    return get_success_data(resp)


# ===========================================================================
# Reissue helper
# ===========================================================================
def reissue_pickup_code(
    parcel_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    reason: str = "LOST",
) -> Dict[str, Any]:
    resp = api_client.reissue_pickup_code(
        parcel_id,
        reissue_pickup_code_payload(reason=reason),
        headers or TEST_USERS["recipient_headers"],
    )
    return get_success_data(resp)


# ===========================================================================
# Return shipment helpers
# ===========================================================================
def request_return_shipment(
    ctx: Dict[str, Any],
    parcel: Dict[str, Any],
    *,
    courier_tracking_return: Optional[str] = None,
) -> Dict[str, Any]:
    """PRD §3.7: 'Once a parcel is in AWAITING_RETURN, a Manager may
    request that the courier reclaim it.'"""
    resp = api_client.request_return_shipment(
        parcel["id"],
        ctx["manager_headers"],
        request_return_payload(courier_tracking_return=courier_tracking_return),
    )
    return get_success_data(resp)


def courier_responds(
    return_shipment_id: str,
    decision: str,
    *,
    courier_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    resp = api_client.courier_response(
        return_shipment_id,
        courier_response_payload(decision=decision),
        courier_headers or TEST_USERS["courier_company_headers"],
    )
    return get_success_data(resp)


def ship_return(
    return_shipment_id: str,
    *,
    courier_tracking_return: Optional[str] = None,
    courier_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    resp = api_client.ship_return(
        return_shipment_id,
        ship_return_payload(courier_tracking_return=courier_tracking_return),
        courier_headers or TEST_USERS["courier_company_headers"],
    )
    return get_success_data(resp)


# ===========================================================================
# Billing / quality assessment helpers
# ===========================================================================
def current_period_yyyymm() -> str:
    """Return the YYYYMM string corresponding to the server's current logical
    clock by reading it from /_clock/advance(0).

    Robust to the test clock having moved arbitrarily forward in a
    previous test: we never rely on the wall-clock now()."""
    snap = advance_clock(0)
    # The PRD describes the response object as carrying the new now
    # value. We read whichever field carries an ISO timestamp.
    for key in ("now", "current_time", "server_time", "timestamp", "logical_now"):
        if isinstance(snap.get(key), str):
            dt = parse_iso(snap[key])
            return f"{dt.year:04d}{dt.month:02d}"
    # Fallback: use wall clock.
    dt = datetime.now(tz=timezone.utc)
    return f"{dt.year:04d}{dt.month:02d}"


def create_billing_period(
    station_id: str,
    period_yyyymm: str,
    manager_headers: Dict[str, str],
) -> Dict[str, Any]:
    resp = api_client.create_billing_period(
        station_id,
        create_billing_period_payload(period_yyyymm=period_yyyymm),
        manager_headers,
    )
    return get_success_data(resp)


def create_quality_assessment(
    station_id: str,
    period_yyyymm: str,
    manager_headers: Dict[str, str],
) -> Dict[str, Any]:
    resp = api_client.create_quality_assessment(
        station_id,
        create_quality_assessment_payload(period_yyyymm=period_yyyymm),
        manager_headers,
    )
    return get_success_data(resp)


def close_quality_assessment(
    station_id: str,
    period_yyyymm: str,
    manager_headers: Dict[str, str],
) -> Dict[str, Any]:
    resp = api_client.close_quality_assessment(
        station_id, period_yyyymm, manager_headers,
    )
    return get_success_data(resp)


def close_billing_period(
    station_id: str,
    period_yyyymm: str,
    manager_headers: Dict[str, str],
) -> Dict[str, Any]:
    resp = api_client.close_billing_period(
        station_id, period_yyyymm, manager_headers,
    )
    return get_success_data(resp)


def advance_clock_to_start_of_next_month() -> str:
    """Advance the logical clock to the first day of the next month at
    00:00 UTC. Returns the new period_yyyymm. Used to ensure subsequent
    register + pickup + period close all happen within the same month.
    """
    snap = advance_clock(0)
    now_iso_s = None
    for key in ("now", "current_time", "server_time", "timestamp", "logical_now"):
        if isinstance(snap.get(key), str):
            now_iso_s = snap[key]
            break
    if now_iso_s is None:
        # Fallback: cannot align; just return current period.
        return current_period_yyyymm()
    now_dt = parse_iso(now_iso_s)
    year, month = now_dt.year, now_dt.month
    if month == 12:
        target = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        target = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    delta_sec = (target - now_dt).total_seconds()
    if delta_sec > 0:
        # Ceil to ensure we land at-or-after target, not before.
        from math import ceil as _ceil
        advance_clock(int(_ceil(delta_sec)))
    return f"{target.year:04d}{target.month:02d}"


def advance_clock_to_next_month(period_yyyymm: str) -> None:
    """Advance the logical clock past period_end for `period_yyyymm`.

    Uses /_clock/advance with a generous overshoot so a re-read of the
    period after advance is guaranteed to satisfy `now() >= period_end`.
    """
    snap = advance_clock(0)
    now_iso = None
    for key in ("now", "current_time", "server_time", "timestamp", "logical_now"):
        if isinstance(snap.get(key), str):
            now_iso = snap[key]
            break
    if now_iso is None:
        # Best-effort: push 40 days.
        advance_clock(40 * 24 * 3600)
        return
    now_dt = parse_iso(now_iso)
    year = int(period_yyyymm[:4])
    month = int(period_yyyymm[4:])
    # period_end = first day of following month at 00:00:00.000 UTC
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    delta_sec = int((end - now_dt).total_seconds())
    if delta_sec <= 0:
        return
    advance_clock(delta_sec + 60)


# ---------------------------------------------------------------------------
# Composite: a station with one shelved parcel that has been picked up
# successfully, leaving a finalized storage fee. Returns ctx + parcel.
# ---------------------------------------------------------------------------
def setup_picked_up_parcel(
    *,
    free_storage_hours: int = 72,
    overdue_hours: int = 0,
    size_class: str = "M",
    storage_capacity: int = 50,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Bring a parcel to PICKED_UP after `overdue_hours` past deadline.

    overdue_hours == 0 means picked up before the free deadline so
    storage_fee_total is 0.
    """
    ctx = setup_station_with_staff(
        storage_capacity=storage_capacity,
        free_storage_hours=free_storage_hours,
    )
    parcel = register_shelved_parcel(ctx, size_class=size_class)
    if overdue_hours > 0:
        # Advance past deadline, run sweep -> OVERTIME, then over the
        # additional overdue window.
        advance_clock_hours(free_storage_hours + overdue_hours)
        run_sweep()
    elif free_storage_hours > 0:
        # Pickup before deadline: do not advance.
        pass
    picked = pickup_with_code(ctx, parcel)
    return ctx, picked


# ---------------------------------------------------------------------------
# Composite: setup_finalization_ready -- a station + zone + N parcels,
# clock advanced past period_end, QualityAssessment created.
# ---------------------------------------------------------------------------
def setup_period_ready_to_close(
    *,
    parcel_count: int = 5,
    overdue_hours_each: int = 0,
    storage_capacity: int = 50,
    free_storage_hours: int = DEFAULT_FREE_STORAGE_HOURS,
    courier_company_id: Optional[str] = None,
    recipient_phone: Optional[str] = None,
    close_quality: bool = True,
    quality_composite_target: Optional[float] = None,
) -> Dict[str, Any]:
    """Create a station with `parcel_count` parcels shelved + picked up,
    then advance past period_end and prepare the BillingPeriod +
    QualityAssessment for close.

    Returns a context dict carrying: station, manager, clerk, zone,
    manager_headers, clerk_headers, parcels (list), period_yyyymm,
    billing_period, quality_assessment.
    """
    # Align the logical clock to the start of a fresh month so that
    # shelved_at, picked_up_at, and the captured period_yyyymm all land
    # in the same month even after an overdue advance. Without this,
    # tests entering near month-end can split handover (rolls up by
    # shelved_at) and recipient (rolls up by picked_up_at) bills into
    # different periods.
    aligned_yyyymm = advance_clock_to_start_of_next_month()

    ctx = setup_station_with_staff(
        storage_capacity=storage_capacity,
        free_storage_hours=free_storage_hours,
        zone_row_count=max(1, (parcel_count + 1) // 2),
        zone_col_count=2,
    )
    # Shared courier + recipient so a single Bill of each kind is produced.
    courier = courier_company_id or unique_courier_company_id()
    recipient = recipient_phone or unique_recipient_phone()

    parcels: List[Dict[str, Any]] = []
    for i in range(parcel_count):
        p = register_shelved_parcel(
            ctx,
            slot_index=i,
            recipient_phone=recipient,
            courier_company_id=courier,
            tracking_number=unique_tracking_number(),
        )
        parcels.append(p)

    # Optionally advance into overdue territory before pickup.
    if overdue_hours_each > 0:
        advance_clock_hours(free_storage_hours + overdue_hours_each)
        run_sweep()

    picked: List[Dict[str, Any]] = []
    for p in parcels:
        picked.append(pickup_with_code(ctx, p))
    period_yyyymm = aligned_yyyymm

    # Create QualityAssessment first (PRD §3.10 -- assessment created
    # in DRAFT, closed by Manager).
    quality = create_quality_assessment(
        ctx["station"]["id"], period_yyyymm, ctx["manager_headers"],
    )

    # Push the clock past period_end.
    advance_clock_to_next_month(period_yyyymm)

    if close_quality:
        quality = close_quality_assessment(
            ctx["station"]["id"], period_yyyymm, ctx["manager_headers"],
        )

    # Lazy-create the billing period (or fetch if auto-created elsewhere).
    period = create_billing_period(
        ctx["station"]["id"], period_yyyymm, ctx["manager_headers"],
    )

    return {
        **ctx,
        "parcels": picked,
        "courier_company_id": courier,
        "recipient_phone": recipient,
        "period_yyyymm": period_yyyymm,
        "billing_period": period,
        "quality_assessment": quality,
    }


def setup_closed_period_with_bills(
    *,
    parcel_count: int = 5,
    overdue_hours_each: int = 0,
    free_storage_hours: int = DEFAULT_FREE_STORAGE_HOURS,
    storage_capacity: int = 50,
) -> Dict[str, Any]:
    """Push setup_period_ready_to_close all the way through close. The
    period's status is CLOSED and child Bills are ISSUED."""
    ctx = setup_period_ready_to_close(
        parcel_count=parcel_count,
        overdue_hours_each=overdue_hours_each,
        free_storage_hours=free_storage_hours,
        storage_capacity=storage_capacity,
    )
    closed_period = close_billing_period(
        ctx["station"]["id"], ctx["period_yyyymm"], ctx["manager_headers"],
    )
    ctx["billing_period"] = closed_period
    # Read bills.
    resp = api_client.list_bills(
        closed_period["id"], ctx["manager_headers"], params={"limit": 100},
    )
    bills, _ = validate_paginated(resp)
    ctx["bills"] = bills
    return ctx


# ---------------------------------------------------------------------------
# Reading helpers
# ---------------------------------------------------------------------------
def list_all_pickup_codes(parcel_id: str,
                          headers: Dict[str, str]) -> List[Dict[str, Any]]:
    resp = api_client.list_pickup_codes(
        parcel_id, headers, params={"limit": 100},
    )
    rows, _ = validate_paginated(resp)
    return rows


def list_all_reminders(parcel_id: str,
                       headers: Dict[str, str]) -> List[Dict[str, Any]]:
    resp = api_client.list_reminders(parcel_id, headers, params={"limit": 100})
    rows, _ = validate_paginated(resp)
    return rows


def list_audit_events(
    headers: Dict[str, str],
    *,
    subject_kind: Optional[str] = None,
    subject_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    # PRD pagination: limit max is 100. Page through to collect all rows.
    out: List[Dict[str, Any]] = []
    offset = 0
    while True:
        params: Dict[str, Any] = {"limit": 100, "offset": offset}
        if subject_kind is not None:
            params["subject_kind"] = subject_kind
        if subject_id is not None:
            params["subject_id"] = subject_id
        resp = api_client.list_audit_events(headers, params=params)
        rows, meta = validate_paginated(resp)
        out.extend(rows)
        if not meta.get("has_more"):
            break
        offset += meta["limit"]
    return out


def list_system_events(
    *,
    target_system: Optional[str] = None,
    event_name: Optional[str] = None,
    subject_id: Optional[str] = None,
    admin_headers: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    # PRD pagination: limit max is 100. Page through to collect all rows.
    headers_to_use = admin_headers or TEST_USERS["platform_admin_headers"]
    out: List[Dict[str, Any]] = []
    offset = 0
    while True:
        params: Dict[str, Any] = {"limit": 100, "offset": offset}
        if target_system is not None:
            params["target_system"] = target_system
        if event_name is not None:
            params["event_name"] = event_name
        if subject_id is not None:
            params["subject_id"] = subject_id
        resp = api_client.list_system_events(headers_to_use, params=params)
        rows, meta = validate_paginated(resp)
        out.extend(rows)
        if not meta.get("has_more"):
            break
        offset += meta["limit"]
    return out


__all__ = [
    "iso_z",
    "parse_iso",
    "add_seconds",
    "add_hours",
    "add_days",
    "advance_clock",
    "advance_clock_hours",
    "run_sweep",
    "create_station",
    "create_manager_staff",
    "create_clerk_staff",
    "create_shelf_zone",
    "setup_station_with_staff",
    "register_shelved_parcel",
    "register_rejected_parcel",
    "fetch_active_pickup_code",
    "drive_parcel_to_overtime",
    "drive_parcel_to_awaiting_return",
    "pickup_with_code",
    "pickup_with_face_match",
    "create_authorization",
    "reissue_pickup_code",
    "request_return_shipment",
    "courier_responds",
    "ship_return",
    "current_period_yyyymm",
    "create_billing_period",
    "create_quality_assessment",
    "close_quality_assessment",
    "close_billing_period",
    "advance_clock_to_next_month",
    "setup_picked_up_parcel",
    "setup_period_ready_to_close",
    "setup_closed_period_with_bills",
    "list_all_pickup_codes",
    "list_all_reminders",
    "list_audit_events",
    "list_system_events",
]
