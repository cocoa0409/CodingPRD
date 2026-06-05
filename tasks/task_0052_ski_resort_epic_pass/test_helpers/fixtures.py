"""Composite setup helpers.

The recurring precondition across the suite is an ACTIVE pass under a configured
product at a configured resort, frequently with a known number of GRANTED scans
(spaced past the 5-minute anti-passback window via clock advances), reserved
buddy tickets, and/or an open PENDING refund request. These helpers encapsulate
those chains so each test focuses purely on the behavior under assertion.

Every helper uses get_success_data() (lenient) for setup steps, so a broken
precondition surfaces as a clear failure rather than a confusing downstream
assertion error. All three roles are opaque (no ownership), so shared role
constants are used throughout.

The test harness restarts the server (empty DB) before every test, so every
helper builds its preconditions from scratch using only PRD-declared endpoints.
"""
from datetime import datetime, timedelta, timezone

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS
from . import factories as f

ADMIN = TEST_USERS["network_admin_headers"]
OPS = TEST_USERS["resort_ops_headers"]
REFUND = TEST_USERS["refund_admin_headers"]


# ─── Clock helpers ────────────────────────────────────────────

def set_clock(api, iso, headers=ADMIN):
    return get_success_data(api.set_clock(iso, headers))


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ─── Primitive creation helpers ───────────────────────────────

def create_product(api, **overrides):
    """Create a PassProduct (NetworkAdmin). Returns the product dict."""
    return get_success_data(
        api.create_pass_product(f.create_pass_product_payload(**overrides), ADMIN)
    )


def create_resort(api, **overrides):
    """Create a Resort (NetworkAdmin). Returns the resort dict."""
    return get_success_data(
        api.create_resort(f.create_resort_payload(**overrides), ADMIN)
    )


def issue_pass(api, product_id, **overrides):
    """Issue an ISSUED pass under a product (ResortOps). Returns the pass dict."""
    return get_success_data(
        api.create_pass(f.create_pass_payload(product_id, **overrides), OPS)
    )


def activate_pass(api, pass_id):
    """Activate (or reinstate) a pass (ResortOps). Returns the pass dict."""
    return get_success_data(api.activate_pass(pass_id, OPS))


def get_pass(api, pass_id, headers=OPS):
    return get_success_data(api.get_pass(pass_id, headers))


def create_interchange_agreement(api, resort_id, max_interchange_days=1):
    return get_success_data(
        api.create_interchange_agreement(
            f.create_interchange_agreement_payload(resort_id, max_interchange_days),
            ADMIN,
        )
    )


# ─── Tier 1/2: active pass at a resort ────────────────────────

def setup_active_pass(api, clock_iso=None, product_overrides=None,
                      resort_overrides=None, holder_name="Setup Holder"):
    """Clock (optional) + product + resort + issued+activated pass.

    Returns (product, resort, pass_data, token). The pass is ACTIVE with its
    refund_basis_cents copied from price_cents and buddy_tickets_remaining set to
    the product allotment.
    """
    if clock_iso is not None:
        set_clock(api, clock_iso)
    product = create_product(api, **(product_overrides or {}))
    resort = create_resort(api, **(resort_overrides or {}))
    issued = issue_pass(api, product["id"], holder_name=holder_name)
    token = issued["magnetic_token"]
    active = activate_pass(api, issued["id"])
    return product, resort, active, token


def setup_issued_pass(api, clock_iso=None, product_overrides=None,
                      resort_overrides=None, holder_name="Issued Holder"):
    """Product + resort + an ISSUED (not activated) pass.

    Returns (product, resort, pass_data, token).
    """
    if clock_iso is not None:
        set_clock(api, clock_iso)
    product = create_product(api, **(product_overrides or {}))
    resort = create_resort(api, **(resort_overrides or {}))
    issued = issue_pass(api, product["id"], holder_name=holder_name)
    return product, resort, issued, issued["magnetic_token"]


# ─── Tier 4: granted-scan accumulation ────────────────────────

def scan_n_granted(api, pass_id, resort_id, token, n, base_iso,
                   step_minutes=10, headers=OPS):
    """Perform n GRANTED scans spaced step_minutes apart (>5 min) starting at
    base_iso, so each clears the anti-passback window. Advances the clock before
    each scan. Returns the list of LiftScan dicts.

    base_iso must be an ISO instant like "2026-01-10T08:00:00Z".
    """
    base = datetime.strptime(base_iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    scans = []
    for i in range(n):
        when = base + timedelta(minutes=step_minutes * i)
        set_clock(api, _iso(when))
        scan = get_success_data(
            api.scan_pass(pass_id, f.scan_payload(resort_id, token), headers)
        )
        scans.append(scan)
    return scans


def setup_pass_with_granted_scans(api, scan_count, price_cents=10000,
                                  base_iso="2026-01-10T08:00:00Z",
                                  tier="FULL_EPIC", holder_name="Scan Holder",
                                  product_overrides=None):
    """ACTIVE FULL_EPIC pass scanned exactly scan_count times GRANTED.

    FULL_EPIC + EPIC resort means no blackout and no interchange interfere, so
    every spaced scan is GRANTED. Returns (product, resort, pass_data, token).
    The returned pass_data is a fresh GET reflecting the final scan_count/version.
    """
    overrides = {"tier": tier, "price_cents": price_cents,
                 "ikon_interchange_enabled": False}
    overrides.update(product_overrides or {})
    product, resort, active, token = setup_active_pass(
        api, clock_iso=base_iso, product_overrides=overrides,
        resort_overrides={"home_network": "EPIC"}, holder_name=holder_name,
    )
    if scan_count > 0:
        scan_n_granted(api, active["id"], resort["id"], token, scan_count, base_iso)
    fresh = get_pass(api, active["id"])
    return product, resort, fresh, token


# ─── Buddy-ticket helpers ─────────────────────────────────────

def reserve_buddy(api, pass_id, resort_id, valid_date, guest_name="Guest",
                  headers=OPS):
    return get_success_data(
        api.create_buddy_ticket(
            f.create_buddy_ticket_payload(pass_id, resort_id, valid_date,
                                          guest_name=guest_name),
            headers,
        )
    )


def setup_active_pass_with_buddies(api, num_buddies, allotment=2,
                                   buddy_price_cents=2000,
                                   clock_iso="2026-01-06T08:00:00Z",
                                   base_date="2026-01-07"):
    """ACTIVE LOCAL pass (given allotment) with num_buddies RESERVED tickets at
    distinct valid_dates and distinct guests. Returns (product, resort, pass_data,
    list_of_buddy_dicts).
    """
    product, resort, active, _token = setup_active_pass(
        api, clock_iso=clock_iso,
        product_overrides={
            "tier": "LOCAL", "price_cents": 5000,
            "buddy_ticket_allotment": allotment,
            "buddy_ticket_price_cents": buddy_price_cents,
            "ikon_interchange_enabled": False,
        },
        resort_overrides={"home_network": "EPIC"},
        holder_name="Buddy Host",
    )
    base = datetime.strptime(base_date, "%Y-%m-%d")
    buddies = []
    for i in range(num_buddies):
        vd = (base + timedelta(days=i)).strftime("%Y-%m-%d")
        buddies.append(
            reserve_buddy(api, active["id"], resort["id"], vd, guest_name=f"G{i + 1}")
        )
    return product, resort, active, buddies


# ─── Refund helpers ───────────────────────────────────────────

def open_refund(api, pass_id, reason="INJURY", headers=REFUND):
    return get_success_data(
        api.create_refund_request(
            f.create_refund_request_payload(pass_id, reason), headers
        )
    )


def setup_pending_refund(api, scan_count, reason, price_cents,
                         base_iso="2026-01-10T08:00:00Z"):
    """ACTIVE FULL_EPIC pass scanned scan_count times, with a PENDING
    RefundRequest of the given reason (snapshot == scan_count). Returns
    (pass_data, refund_request, pass_version). pass_version is the current version
    suitable for an OCC approve.
    """
    _product, _resort, fresh, _token = setup_pass_with_granted_scans(
        api, scan_count, price_cents=price_cents, base_iso=base_iso,
        holder_name="Refund Holder",
    )
    rr = open_refund(api, fresh["id"], reason=reason)
    pass_now = get_pass(api, fresh["id"], headers=REFUND)
    return pass_now, rr, pass_now["version"]


def approve_refund(api, rr_id, expected_version, headers=REFUND):
    return api.approve_refund_request(
        rr_id, f.approve_refund_payload(expected_version), headers
    )


def reject_refund(api, rr_id, headers=REFUND):
    return api.reject_refund_request(rr_id, headers)
