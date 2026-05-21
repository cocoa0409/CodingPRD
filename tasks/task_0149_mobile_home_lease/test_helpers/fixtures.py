"""Composite setup helpers — multi-step preambles tests can reuse.

Most interesting test claims require the system to be in a late state
that takes 5-15 API calls to reach. Each fixture composes the lower-
level steps so the test body can focus on the rule under assertion.

IDENTITY THREADING — PRD §2.1:

    "ParkManager — When X-User-Role is ParkManager, X-User-ID is the
    id of the acting Park; ownership checks on any resource that
    references a Park (a Lot, a Home, or any descendant of those)
    compare the resource's park_id to X-User-ID."

    "Resident — When X-User-Role is Resident, X-User-ID is the id of
    the acting Resident."

After a Park is created, any ParkManager-exclusive call against
resources under that park MUST mint headers via
make_park_manager_headers(park.id) — never fall back to the shared
TEST_USERS["park_manager_headers"] constant.

Similarly, after a Resident is created, any Resident-exclusive call
that exercises the owner_resident_id / resident_id ownership check
MUST use make_resident_headers(resident.id).

Setup calls use get_success_data (a lenient 2xx validator), so a
failed setup surfaces as 'Setup failed' rather than a confusing test
assertion failure downstream.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    add_days,
    advance_clock_payload,
    create_conversion_request_payload,
    create_eviction_case_payload,
    create_home_payload,
    create_home_sale_transfer_payload,
    create_lease_payload,
    create_lot_payload,
    create_park_payload,
    create_rent_increase_notice_payload,
    create_resident_payload,
    iso_utc,
    parse_iso,
    random_suffix,
    sweep_billing_payload,
    utcnow,
)
from .test_users import (
    TEST_USERS,
    make_park_manager_headers,
    make_resident_headers,
    make_platform_admin_headers,
)


# ===========================================================================
# Primitives — Park, Resident, Lot, Home
# ===========================================================================
def create_park(
    state_code: str = "CA",
    master_cpi_pct: float = 2.00,
    utility_apportionment_method: str = "EQUAL_SPLIT",
    billing_period_anchor_day: int = 1,
    name: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
    **overrides,
) -> Dict[str, Any]:
    """Create a Park and return its representation.

    The initial creation uses the shared park_manager_headers constant —
    PRD §2.1 says the ParkManager role can create parks, and the
    just-created park's id is not yet known so ownership cannot be
    verified against it. Subsequent operations on this park should
    use make_park_manager_headers(park.id).
    """
    payload = create_park_payload(
        name=name,
        state_code=state_code,
        master_cpi_pct=master_cpi_pct,
        utility_apportionment_method=utility_apportionment_method,
        billing_period_anchor_day=billing_period_anchor_day,
        **overrides,
    )
    h = headers or TEST_USERS["park_manager_headers"]
    resp = api_client.create_park(payload, h)
    return get_success_data(resp)


def create_resident(
    full_name: Optional[str] = None,
    email: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
    **overrides,
) -> Dict[str, Any]:
    """Create a Resident and return its representation.

    PRD §4: POST /residents is open to ParkManager and PlatformAdmin.
    Resident creation does not depend on the caller owning anything,
    so the shared constants are appropriate here.
    """
    payload = {
        "full_name": full_name or f"R_{random_suffix(6)}",
        "email": email or f"r_{random_suffix(6).lower()}@example.com",
    }
    payload.update(overrides)
    h = headers or TEST_USERS["park_manager_headers"]
    resp = api_client.create_resident(payload, h)
    return get_success_data(resp)


def get_park(park_id: str,
             headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    h = headers or make_park_manager_headers(park_id)
    resp = api_client.get_park(park_id, h)
    return get_success_data(resp)


def get_resident(resident_id: str,
                 headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    h = headers or TEST_USERS["platform_admin_headers"]
    resp = api_client.get_resident(resident_id, h)
    return get_success_data(resp)


def create_lot(
    park_id: str,
    lot_number: Optional[str] = None,
    base_rent_cents: int = 100_000,
    sub_meter_reading_kwh: Optional[float] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Create a Lot under a Park. Uses the actual park_id as the
    ParkManager X-User-ID per PRD §2.1.
    """
    payload = create_lot_payload(
        lot_number=lot_number or f"L{random_suffix(4)}",
        base_rent_cents=base_rent_cents,
        sub_meter_reading_kwh=sub_meter_reading_kwh,
    )
    h = headers or make_park_manager_headers(park_id)
    resp = api_client.create_lot(park_id, payload, h)
    return get_success_data(resp)


def get_lot(lot_id: str,
            park_id: Optional[str] = None,
            headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Fetch a lot. Park-scoped role is needed because Lot.park_id is
    used by ownership checks (PRD §2.1). For non-ownership reads, the
    PlatformAdmin role is also legal per PRD §4."""
    h = headers or TEST_USERS["platform_admin_headers"]
    resp = api_client.get_lot(lot_id, h)
    return get_success_data(resp)


def register_home(
    park_id: str,
    lot_id: str,
    assessed_value_cents: int = 5_000_000,
    vin: Optional[str] = None,
    owner_resident_id: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Register a Home onto a Lot.

    PRD §3.1: 'A home registered on a PARK_OWNED lot has its
    owner_resident_id set to null ...; a home registered on a
    RESIDENT_OWNED lot binds its owner_resident_id to the supplied
    value.'
    """
    payload = create_home_payload(
        lot_id=lot_id,
        vin=vin,
        assessed_value_cents=assessed_value_cents,
        owner_resident_id=owner_resident_id,
    )
    h = headers or make_park_manager_headers(park_id)
    resp = api_client.create_home(park_id, payload, h)
    return get_success_data(resp)


def place_home(
    park_id: str,
    lot_id: str,
    assessed_value_cents: int = 5_000_000,
    owner_resident_id: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Alias retained for readability inside fixtures that 'place' a home."""
    return register_home(
        park_id=park_id,
        lot_id=lot_id,
        assessed_value_cents=assessed_value_cents,
        owner_resident_id=owner_resident_id,
        headers=headers,
    )


def get_home(home_id: str,
             headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    h = headers or TEST_USERS["platform_admin_headers"]
    resp = api_client.get_home(home_id, h)
    return get_success_data(resp)


# ===========================================================================
# Lease lifecycle — PRD §3.2, §3.3, §3.4
# ===========================================================================
def create_signed_lease(
    park_id: str,
    lot_id: str,
    resident_id: str,
    start_date: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Draft + sign a lease for the given lot and resident.

    PRD §3.2: 'Activation step — signing the draft, transitioning
    DRAFT → CURRENT — is performed by a ParkManager.'

    Returns the signed lease (status=CURRENT).
    """
    h = headers or make_park_manager_headers(park_id)
    draft_payload = create_lease_payload(
        resident_id=resident_id, start_date=start_date,
    )
    draft = get_success_data(api_client.create_lease(lot_id, draft_payload, h))
    signed = get_success_data(api_client.sign_lease(draft["id"], h))
    return signed


def sign_lease(park_id: str, lease_id: str,
               headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    h = headers or make_park_manager_headers(park_id)
    return get_success_data(api_client.sign_lease(lease_id, h))


def get_lease(lease_id: str,
              headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    h = headers or TEST_USERS["platform_admin_headers"]
    resp = api_client.get_lease(lease_id, h)
    return get_success_data(resp)


def pay_lease(resident_id: str, lease_id: str,
              headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """PRD §3.4: 'A Resident clears their delinquency by invoking the
    pay action on their lease.' This is a Resident-only mutation
    requiring X-User-ID == Lease.resident_id (PRD §2.1)."""
    h = headers or make_resident_headers(resident_id)
    return get_success_data(api_client.pay_lease(lease_id, h))


# ===========================================================================
# Composite setups — Park + Lot + Lease (+ Home / Resident)
# ===========================================================================
def create_park_with_lot_and_lease(
    state_code: str = "CA",
    master_cpi_pct: float = 2.00,
    utility_apportionment_method: str = "EQUAL_SPLIT",
    base_rent_cents: int = 100_000,
    sub_meter_reading_kwh: Optional[float] = None,
    lease_start_offset_days: int = -1,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Create a Park + one PARK_OWNED Lot + a Resident + a signed Lease
    in CURRENT.

    Returns (park, lot, resident, lease).

    The lease start_date defaults to one day before now() so the lease
    is fully active when subsequent billing periods are simulated.
    """
    park = create_park(
        state_code=state_code,
        master_cpi_pct=master_cpi_pct,
        utility_apportionment_method=utility_apportionment_method,
    )
    lot = create_lot(
        park_id=park["id"],
        base_rent_cents=base_rent_cents,
        sub_meter_reading_kwh=sub_meter_reading_kwh,
    )
    resident = create_resident()
    start = iso_utc(
        add_days(utcnow(), lease_start_offset_days).replace(
            hour=0, minute=0, second=0, microsecond=0,
        )
    )
    lease = create_signed_lease(
        park_id=park["id"],
        lot_id=lot["id"],
        resident_id=resident["id"],
        start_date=start,
    )
    return park, lot, resident, lease


def setup_three_occupied_lots(
    state_code: str = "CA",
    utility_apportionment_method: str = "SUB_METER",
    readings_kwh: Tuple[float, float, float] = (1.0, 3.0, 6.0),
    base_rent_cents: int = 100_000,
    lease_start_offset_days: int = -2,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]],
           List[Dict[str, Any]]]:
    """Create a Park with three PARK_OWNED Lots (lot_numbers L01,L02,L03),
    distinct Residents, and signed Leases on all three.

    Used by utility-apportionment tests that need predictable per-lot
    distribution. PRD §3.1 requires base_rent_cents > 0 strictly; the
    default is a positive value, and apportionment-only tests rely on
    lot_share_cents being isolated from rent_due_cents (which they can
    do by either subtracting rent_due_cents or, where strictly needed,
    a lease_start_offset_days that pushes start_date to/after billing
    period end so rent prorates to zero).

    Returns (park, lots, residents, leases) — all parallel lists ordered
    L01, L02, L03.
    """
    park = create_park(
        state_code=state_code,
        utility_apportionment_method=utility_apportionment_method,
    )
    lots: List[Dict[str, Any]] = []
    residents: List[Dict[str, Any]] = []
    leases: List[Dict[str, Any]] = []
    start = iso_utc(
        add_days(utcnow(), lease_start_offset_days).replace(
            hour=0, minute=0, second=0, microsecond=0,
        )
    )
    for i, reading in enumerate(readings_kwh, start=1):
        lot_number = f"L{i:02d}"
        lot = create_lot(
            park_id=park["id"],
            lot_number=lot_number,
            base_rent_cents=base_rent_cents,
            sub_meter_reading_kwh=reading,
        )
        r = create_resident()
        lease = create_signed_lease(
            park_id=park["id"],
            lot_id=lot["id"],
            resident_id=r["id"],
            start_date=start,
        )
        lots.append(lot)
        residents.append(r)
        leases.append(lease)
    return park, lots, residents, leases


# ===========================================================================
# Rent-increase notice — PRD §3.5
# ===========================================================================
def create_draft_rent_increase_notice(
    park_id: str,
    lease_id: str,
    proposed_new_rent_cents: int,
    effective_on_days_from_now: int = 100,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Draft (DRAFT) a RentIncreaseNotice.

    PRD §3.5: 'effective_on must be at least 90 calendar days after the
    moment of issuance.' Default offset of 100 days keeps the notice
    valid for issuance.
    """
    h = headers or make_park_manager_headers(park_id)
    effective_on = iso_utc(
        add_days(utcnow(), effective_on_days_from_now).replace(
            hour=0, minute=0, second=0, microsecond=0,
        )
    )
    payload = create_rent_increase_notice_payload(
        proposed_new_rent_cents=proposed_new_rent_cents,
        effective_on=effective_on,
    )
    resp = api_client.create_rent_increase_notice(lease_id, payload, h)
    return get_success_data(resp)


def issue_rent_increase_notice(
    park_id: str, notice_id: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Transition DRAFT → ISSUED (PRD §3.5)."""
    h = headers or make_park_manager_headers(park_id)
    resp = api_client.issue_rent_increase_notice(notice_id, h)
    return get_success_data(resp)


def get_rent_increase_notice(
    notice_id: str, headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    h = headers or TEST_USERS["platform_admin_headers"]
    resp = api_client.get_rent_increase_notice(notice_id, h)
    return get_success_data(resp)


# ===========================================================================
# Eviction case — PRD §3.6
# ===========================================================================
def create_draft_eviction_case(
    park_id: str, lease_id: str, violation_type: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """File an eviction case. PRD §3.6 auto-advances on creation:
    NONPAYMENT/RULE_VIOLATION -> IN_CURE (lease -> GRACE),
    ILLEGAL_USE -> FINALIZED_FOR_CAUSE (lease -> TERMINATED cascade).
    """
    h = headers or make_park_manager_headers(park_id)
    payload = create_eviction_case_payload(violation_type=violation_type)
    resp = api_client.create_eviction_case(lease_id, payload, h)
    return get_success_data(resp)


def file_eviction_case(park_id: str, lease_id: str, violation_type: str,
                       headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Alias for create_draft_eviction_case."""
    return create_draft_eviction_case(park_id, lease_id, violation_type,
                                      headers)


def cure_eviction_case(resident_id: str, case_id: str,
                       headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """PRD §3.6: Resident-only mutation. X-User-ID must equal the
    lease's resident_id per PRD §2.1."""
    h = headers or make_resident_headers(resident_id)
    return get_success_data(api_client.cure_eviction_case(case_id, h))


def dismiss_eviction_case(park_id: str, case_id: str,
                          headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """PRD §3.6: ParkManager-only mutation."""
    h = headers or make_park_manager_headers(park_id)
    return get_success_data(api_client.dismiss_eviction_case(case_id, h))


def get_eviction_case(case_id: str,
                      headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    h = headers or TEST_USERS["platform_admin_headers"]
    resp = api_client.get_eviction_case(case_id, h)
    return get_success_data(resp)


# ===========================================================================
# Home sale transfer — PRD §3.7
# ===========================================================================
def open_home_sale_transfer(
    home_id: str, seller_resident_id: str, buyer_resident_id: str,
    sale_price_cents: int = 6_000_000,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """PRD §3.7: 'Either a ParkManager or a Resident opens a transfer.'

    The shared ParkManager constant is acceptable for this initial open
    because the resulting transfer's park scoping is verified on later
    approve/close calls, not on the initial open. Tests requiring the
    seller-identity path use make_resident_headers(seller_id).
    """
    h = headers or TEST_USERS["park_manager_headers"]
    payload = create_home_sale_transfer_payload(
        home_id=home_id,
        seller_resident_id=seller_resident_id,
        buyer_resident_id=buyer_resident_id,
        sale_price_cents=sale_price_cents,
    )
    resp = api_client.create_home_sale_transfer(payload, h)
    return get_success_data(resp)


def approve_home_sale_transfer(park_id: str, transfer_id: str,
                               headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    h = headers or make_park_manager_headers(park_id)
    return get_success_data(api_client.approve_home_sale_transfer(transfer_id, h))


def close_home_sale_transfer(park_id: str, transfer_id: str,
                             headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    h = headers or make_park_manager_headers(park_id)
    return get_success_data(api_client.close_home_sale_transfer(transfer_id, h))


def get_home_sale_transfer(transfer_id: str,
                           headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    h = headers or TEST_USERS["platform_admin_headers"]
    resp = api_client.get_home_sale_transfer(transfer_id, h)
    return get_success_data(resp)


# ===========================================================================
# Conversion request — PRD §3.8
# ===========================================================================
def create_conversion_request(park_id: str, lot_id: str,
                              prospective_buyer_resident_id: str,
                              offer_price_cents: int = 5_000_000,
                              headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    h = headers or make_park_manager_headers(park_id)
    payload = create_conversion_request_payload(
        prospective_buyer_resident_id=prospective_buyer_resident_id,
        offer_price_cents=offer_price_cents,
    )
    resp = api_client.create_conversion_request(lot_id, payload, h)
    return get_success_data(resp)


def accept_conversion_request(resident_id: str, conv_id: str,
                              headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """PRD §3.8: Resident-only mutation; the prospective buyer is the
    actor and X-User-ID must equal their Resident.id."""
    h = headers or make_resident_headers(resident_id)
    return get_success_data(api_client.accept_conversion_request(conv_id, h))


def finalize_conversion_request(park_id: str, conv_id: str,
                                headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """PRD §3.8: ParkManager-only mutation."""
    h = headers or make_park_manager_headers(park_id)
    return get_success_data(api_client.finalize_conversion_request(conv_id, h))


def get_conversion_request(conv_id: str,
                           headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    h = headers or TEST_USERS["platform_admin_headers"]
    resp = api_client.get_conversion_request(conv_id, h)
    return get_success_data(resp)


# ===========================================================================
# Test-harness helpers — PRD §2.11
# ===========================================================================
def advance_clock(seconds: int,
                  headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Advance the logical clock by N seconds (PRD §2.11)."""
    h = headers or TEST_USERS["platform_admin_headers"]
    payload = advance_clock_payload(seconds=seconds)
    resp = api_client.advance_clock(payload, h)
    return get_success_data(resp)


def sweep_billing(park_id: str,
                  billing_period_start: str,
                  billing_period_end: str,
                  master_total_cents: int,
                  headers: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    """PRD §3.3 billing sweep."""
    h = headers or TEST_USERS["platform_admin_headers"]
    payload = sweep_billing_payload(
        park_id=park_id,
        billing_period_start=billing_period_start,
        billing_period_end=billing_period_end,
        master_total_cents=master_total_cents,
    )
    resp = api_client.sweep_billing(payload, h)
    data = get_success_data(resp)
    # Sweep returns a list of UtilityBill per occupied lot.
    return data if isinstance(data, list) else data.get("bills", data)


def sweep_evictions(headers: Optional[Dict[str, str]] = None) -> Any:
    h = headers or TEST_USERS["platform_admin_headers"]
    resp = api_client.sweep_evictions(h)
    return get_success_data(resp)


def sweep_rent_effective(headers: Optional[Dict[str, str]] = None) -> Any:
    h = headers or TEST_USERS["platform_admin_headers"]
    resp = api_client.sweep_rent_effective(h)
    return get_success_data(resp)


def sub_meter_billing(park: Dict[str, Any],
                      master_total_cents: int,
                      period_days: int = 30) -> Tuple[str, str, List[Dict[str, Any]]]:
    """Run /_sweep/billing over a freshly-defined period for the park.

    Returns (period_start_iso, period_end_iso, bills). Uses a 30-day
    half-open billing window ending at now() by default; tests that
    require a different period override period_days.
    """
    end = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    start = add_days(end, -period_days)
    period_start = iso_utc(start)
    period_end = iso_utc(end)
    bills = sweep_billing(
        park_id=park["id"],
        billing_period_start=period_start,
        billing_period_end=period_end,
        master_total_cents=master_total_cents,
    )
    return period_start, period_end, bills


# ===========================================================================
# Difficulty-design-targeted composite fixtures
# ===========================================================================
def setup_lease_in_delinquent(
    state_code: str = "CA",
    master_total_cents: int = 5000,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any],
           List[Dict[str, Any]]]:
    """Park + Lot + signed Lease + one /_sweep/billing run leaving the
    lease in DELINQUENT with one unpaid UtilityBill.

    Returns (park, lot, resident, lease, bills).

    PRD §3.3 declares the DELINQUENT transition; PRD §3.4 the return
    path. PRD §3.1 requires base_rent_cents strictly > 0, so we use a
    small positive value here; the test consumers only need a non-zero
    outstanding balance, not a zero-rent precondition.
    """
    park, lot, resident, lease = create_park_with_lot_and_lease(
        state_code=state_code,
        utility_apportionment_method="EQUAL_SPLIT",
        base_rent_cents=100_000,
        lease_start_offset_days=-60,
    )
    _, _, bills = sub_meter_billing(park, master_total_cents)
    # Re-fetch lease to see DELINQUENT status.
    refreshed = get_lease(lease["id"])
    return park, lot, resident, refreshed, bills


def setup_grace_lease_zero_balance() -> Tuple[Dict[str, Any], Dict[str, Any],
                                              Dict[str, Any], Dict[str, Any],
                                              Dict[str, Any]]:
    """Lease in GRACE with outstanding_balance_cents == 0.

    PRD §3.6: filing a RULE_VIOLATION eviction transitions the lease
    CURRENT → GRACE. Because no billing run has occurred, the balance
    is zero.

    Returns (park, lot, resident, lease, case).
    """
    park, lot, resident, lease = create_park_with_lot_and_lease()
    case = create_draft_eviction_case(
        park_id=park["id"], lease_id=lease["id"],
        violation_type="RULE_VIOLATION",
    )
    refreshed = get_lease(lease["id"])
    return park, lot, resident, refreshed, case


def setup_grace_lease_positive_balance(
    master_total_cents: int = 5000,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any],
           Dict[str, Any]]:
    """Lease in GRACE with outstanding_balance_cents > 0.

    Recipe: bill the lease first (push to DELINQUENT), then file a
    RULE_VIOLATION eviction (DELINQUENT → GRACE).

    Returns (park, lot, resident, lease, case).
    """
    park, lot, resident, lease = create_park_with_lot_and_lease(
        base_rent_cents=100_000, lease_start_offset_days=-60,
    )
    sub_meter_billing(park, master_total_cents)
    case = create_draft_eviction_case(
        park_id=park["id"], lease_id=lease["id"],
        violation_type="RULE_VIOLATION",
    )
    refreshed = get_lease(lease["id"])
    return park, lot, resident, refreshed, case


def setup_park_owned_lot_for_conversion(
    state_code: str = "CA",
    base_rent_cents: int = 100_000,
    assessed_value_cents: int = 5_000_000,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Park + a PARK_OWNED Lot + a Home + a prospective-buyer Resident,
    ready for a ConversionRequest.

    Returns (park, lot, home, buyer).

    PRD §3.8: a conversion offers a PARK_OWNED lot to a specific
    resident; the lot must remain PARK_OWNED at finalize time.
    """
    park = create_park(state_code=state_code)
    lot = create_lot(park_id=park["id"], base_rent_cents=base_rent_cents)
    home = register_home(
        park_id=park["id"], lot_id=lot["id"],
        assessed_value_cents=assessed_value_cents,
    )
    buyer = create_resident()
    return park, lot, home, buyer


def setup_resident_owned_lot_with_home(
    state_code: str = "CA",
    base_rent_cents: int = 100_000,
    assessed_value_cents: int = 5_000_000,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any],
           Dict[str, Any]]:
    """Park + a now-RESIDENT_OWNED Lot (reached via conversion) +
    a Home owned by the seller + a signed Lease on that Lot.

    PRD §3.8: conversion finalize sets Lot.ownership_mode := RESIDENT_OWNED.

    Because PRD §3.8 also says 'if the lot has no current_lease_id at
    the moment of finalization (the lot was vacant of any standing
    lease), the system creates a fresh Lease in CURRENT', we drive
    the conversion BEFORE creating any lease so that finalize itself
    plants the lease — the seller of the upcoming home-sale is then
    the buyer from the conversion.

    Returns (park, lot, home, seller, lease).
    """
    park = create_park(state_code=state_code)
    lot = create_lot(park_id=park["id"], base_rent_cents=base_rent_cents)
    home = register_home(
        park_id=park["id"], lot_id=lot["id"],
        assessed_value_cents=assessed_value_cents,
    )
    seller = create_resident()
    # Drive the lot through conversion to RESIDENT_OWNED, with seller as buyer.
    conv = create_conversion_request(
        park_id=park["id"], lot_id=lot["id"],
        prospective_buyer_resident_id=seller["id"],
        offer_price_cents=assessed_value_cents,
    )
    accept_conversion_request(seller["id"], conv["id"])
    finalize_conversion_request(park["id"], conv["id"])
    # After finalize, lot has a Lease in CURRENT for the seller per PRD §3.8.
    refreshed_lot = get_lot(lot["id"])
    lease_id = refreshed_lot.get("current_lease_id")
    if lease_id is None:
        # Defensive: if implementation does not auto-create the lease,
        # the test path will surface its own failure later. Provide a
        # placeholder dict so the unpacking does not crash.
        lease: Dict[str, Any] = {}
    else:
        lease = get_lease(lease_id)
    return park, refreshed_lot, home, seller, lease
