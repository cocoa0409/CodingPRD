"""Composite setup helpers for the Pharma E-Commerce Compliance API.

Design principles
-----------------
* Every fixture uses get_success_data() so setup failures yield clear
  "Setup failed" errors, not assertion noise.
* Identity threading is mandatory: every ownership-gated call uses
  make_<role>_headers(actual_entity_id) — never a shared TEST_USERS
  constant — because PRD §2.1 compares X-User-ID byte-equal to the
  resource's foreign-key field for entity-backed roles. Concretely:
    - Customer order operations: X-User-ID == order.customer_id
    - VendorAdmin resubmit-qualification: X-User-ID == vendor.id
    - PrescriptionReviewer approve: prescription.reviewer_pharmacist_id = X-User-ID
    - PharmacistReReviewer review actions: X-User-ID == review.assigned_pharmacist_id
    - Segregation of duties: PR Pharmacist.id != RR Pharmacist.id
* The platform clock is the system clock for every time-driven check.
  The autouse conftest fixture resets the clock to a baseline before
  every test; helpers that need a different clock advance from there.
"""
from __future__ import annotations
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client, ApiClient
from .factories import (
    create_platform_payload,
    create_vendor_payload,
    create_pharmacist_payload,
    create_customer_payload,
    create_drug_payload,
    create_prescription_payload,
    create_purchase_limit_rule_payload,
    create_order_payload,
    open_pharmacist_review_payload,
    approve_review_payload,
    reject_review_payload,
    request_change_payload,
    create_shipment_payload,
    create_adr_payload,
    order_item,
    prescription_item,
    reading_payload,
    denylist_entry_payload,
    unique_ndc,
)
from .test_users import (
    TEST_USERS,
    make_admin_headers,
    make_regulatory_headers,
    make_vendor_admin_headers,
    make_prescription_reviewer_headers,
    make_pharmacist_re_reviewer_headers,
    make_pharmacist_headers,
    make_customer_headers,
)
from .constants import FAR_FUTURE_ISO


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def iso_z(dt: datetime) -> str:
    """Serialize a datetime as ISO 8601 UTC with millisecond precision."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"


def parse_iso(iso: str) -> datetime:
    """Parse ISO 8601 UTC string with millisecond precision into a datetime."""
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(timezone.utc)


def add_seconds(iso: str, seconds: float) -> str:
    return iso_z(parse_iso(iso) + timedelta(seconds=seconds))


def add_days(iso: str, days: float) -> str:
    return iso_z(parse_iso(iso) + timedelta(days=days))


def add_hours(iso: str, hours: float) -> str:
    return iso_z(parse_iso(iso) + timedelta(hours=hours))


def add_milliseconds(iso: str, millis: int) -> str:
    return iso_z(parse_iso(iso) + timedelta(milliseconds=millis))


# ---------------------------------------------------------------------------
# Tier 1: Platform + Clock
# ---------------------------------------------------------------------------

def create_platform(api: ApiClient = api_client, **overrides) -> Dict[str, Any]:
    """Create a PharmaPlatform via PlatformAdmin (PRD §3.0/§4)."""
    payload = create_platform_payload(**overrides)
    resp = api.create_platform(payload, TEST_USERS["admin_headers"])
    return get_success_data(resp)


def advance_clock(api: ApiClient, pid: str, to_iso: str,
                    headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Advance the platform clock (PRD §2.4 / §2.11)."""
    h = headers or TEST_USERS["admin_headers"]
    resp = api.advance_clock(pid, to_iso, h)
    return get_success_data(resp)


def setup_platform_at_clock(api: ApiClient,
                              clock_iso: str = "2025-01-01T00:00:00.000Z",
                              **overrides) -> Dict[str, Any]:
    """Create a platform and advance its clock to a known baseline.

    The fresh platform initialises current_clock_iso to 1970-01-01 per PRD §2.4;
    advancing to a known baseline gives every test a deterministic 'now'.
    Returns the platform dict at the new clock.
    """
    pf = create_platform(api, **overrides)
    return advance_clock(api, pf["id"], clock_iso)


# ---------------------------------------------------------------------------
# Tier 1: Vendor / Pharmacist / Customer
# ---------------------------------------------------------------------------

def create_vendor(api: ApiClient, pid: str, **overrides) -> Dict[str, Any]:
    """Create a Vendor (PRD §3.1). Defaults: far-future expiries (no auto sweep)."""
    payload = create_vendor_payload(**overrides)
    resp = api.create_vendor(pid, payload, TEST_USERS["admin_headers"])
    return get_success_data(resp)


def create_pharmacist(api: ApiClient, pid: str, **overrides) -> Dict[str, Any]:
    """Create a Pharmacist (PRD §3.3). Defaults: ACTIVE with far-future cert expiry."""
    payload = create_pharmacist_payload(**overrides)
    resp = api.create_pharmacist(pid, payload, TEST_USERS["admin_headers"])
    return get_success_data(resp)


def create_customer(api: ApiClient, pid: str, **overrides) -> Dict[str, Any]:
    """Create a Customer (PRD §2.10). Defaults: real_name_verified=True."""
    payload = create_customer_payload(**overrides)
    resp = api.create_customer(pid, payload, TEST_USERS["admin_headers"])
    return get_success_data(resp)


def create_two_pharmacists(api: ApiClient, pid: str,
                            **overrides) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Create two distinct Pharmacists for segregation-of-duties scenarios.

    PRD §3.6 requires the prescription's reviewer_pharmacist_id to differ
    from the second-line pharmacist's X-User-ID. Returns (PR, RR).
    """
    pr = create_pharmacist(api, pid, full_name="Pharmacist Reviewer 1", **overrides)
    rr = create_pharmacist(api, pid, full_name="Pharmacist ReReviewer 1", **overrides)
    assert pr["id"] != rr["id"], "Setup failed: PR and RR pharmacists must be distinct ids"
    return pr, rr


# ---------------------------------------------------------------------------
# Tier 2: Drug lifecycle (create + shelve)
# ---------------------------------------------------------------------------

def create_drug(api: ApiClient, pid: str, vendor_id: str, **overrides) -> Dict[str, Any]:
    """Create a Drug in PENDING_REVIEW (PRD §3.2)."""
    payload = create_drug_payload(vendor_id, **overrides)
    resp = api.create_drug(pid, payload, TEST_USERS["admin_headers"])
    return get_success_data(resp)


def shelve_drug(api: ApiClient, pid: str, drug_id: str,
                 headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Move a Drug to ON_SHELF (PRD §3.2)."""
    resp = api.shelve_drug(pid, drug_id, headers or TEST_USERS["admin_headers"])
    return get_success_data(resp)


def create_and_shelve_drug(api: ApiClient, pid: str, vendor_id: str,
                             **overrides) -> Dict[str, Any]:
    """Create a Drug and shelve it (PRD §3.2)."""
    drug = create_drug(api, pid, vendor_id, **overrides)
    return shelve_drug(api, pid, drug["id"])


def create_otc_drug_on_shelf(api: ApiClient, pid: str, vendor_id: str,
                               **overrides) -> Dict[str, Any]:
    """OTC drug, ON_SHELF, control_category=NONE."""
    return create_and_shelve_drug(api, pid, vendor_id,
                                    classification="OTC",
                                    control_category="NONE",
                                    **overrides)


def create_prescription_drug_on_shelf(api: ApiClient, pid: str, vendor_id: str,
                                        **overrides) -> Dict[str, Any]:
    """PRESCRIPTION drug, ON_SHELF."""
    return create_and_shelve_drug(api, pid, vendor_id,
                                    classification="PRESCRIPTION",
                                    control_category="NONE",
                                    **overrides)


def create_cold_chain_drug_on_shelf(api: ApiClient, pid: str, vendor_id: str,
                                      **overrides) -> Dict[str, Any]:
    """Cold-chain OTC drug, ON_SHELF (cold_chain_required=True).

    Default classification is OTC so we don't need a prescription path
    when only the cold-chain flag matters. Override classification to
    PRESCRIPTION for prescription cold-chain orders.
    """
    return create_and_shelve_drug(api, pid, vendor_id,
                                    classification="OTC",
                                    control_category="NONE",
                                    cold_chain_required=True,
                                    **overrides)


# ---------------------------------------------------------------------------
# Tier 2: Prescription lifecycle
# ---------------------------------------------------------------------------

def upload_prescription(api: ApiClient, pid: str,
                          customer: Dict[str, Any],
                          drug_items: List[Dict[str, Any]],
                          **overrides) -> Dict[str, Any]:
    """Upload a prescription via the Customer (PRD §3.4).

    Identity threading: Customer X-User-ID must equal customer.id per PRD §2.1.
    """
    payload = create_prescription_payload(customer["id"], drug_items, **overrides)
    resp = api.create_prescription(pid, payload, make_customer_headers(customer["id"]))
    return get_success_data(resp)


def approve_prescription(api: ApiClient, pid: str, rx_id: str,
                           pr_pharmacist: Dict[str, Any]) -> Dict[str, Any]:
    """Approve a prescription as the named PrescriptionReviewer pharmacist.

    PRD §3.4: 'sets reviewer_pharmacist_id to the reviewer's X-User-ID'.
    Identity threading is critical for the segregation-of-duties check
    that fires later at re-review time.
    """
    headers = make_prescription_reviewer_headers(pr_pharmacist["id"])
    resp = api.approve_prescription(pid, rx_id, headers)
    return get_success_data(resp)


def upload_and_approve_prescription(api: ApiClient, pid: str,
                                      customer: Dict[str, Any],
                                      pr_pharmacist: Dict[str, Any],
                                      drug_items: List[Dict[str, Any]],
                                      **overrides) -> Dict[str, Any]:
    """Upload a prescription and approve it. Returns the approved Prescription."""
    rx = upload_prescription(api, pid, customer, drug_items, **overrides)
    return approve_prescription(api, pid, rx["id"], pr_pharmacist)


# ---------------------------------------------------------------------------
# Tier 2: Order lifecycle
# ---------------------------------------------------------------------------

def place_order(api: ApiClient, pid: str,
                 customer: Dict[str, Any],
                 items: List[Dict[str, Any]],
                 prescription_id: Optional[str] = None,
                 **overrides) -> Dict[str, Any]:
    """Place an order as the Customer (PRD §3.5).

    Identity threading: X-User-ID == customer_id (PRD §2.1).
    """
    payload = create_order_payload(customer["id"], items, prescription_id, **overrides)
    resp = api.create_order(pid, payload, make_customer_headers(customer["id"]))
    return get_success_data(resp)


def pay_order(api: ApiClient, pid: str, order: Dict[str, Any]) -> Dict[str, Any]:
    """Pay an order as the placing customer (PRD §2.1, §3.5)."""
    headers = make_customer_headers(order["customer_id"])
    resp = api.pay_order(pid, order["id"], headers)
    return get_success_data(resp)


def open_pharmacist_review(api: ApiClient, pid: str, order: Dict[str, Any],
                             rr_pharmacist: Dict[str, Any]) -> Dict[str, Any]:
    """Open second-line review (PRD §3.6).

    Identity threading: assigned_pharmacist_id = rr.id and X-User-ID = rr.id.
    """
    payload = open_pharmacist_review_payload(rr_pharmacist["id"])
    headers = make_pharmacist_re_reviewer_headers(rr_pharmacist["id"])
    resp = api.open_pharmacist_review(pid, order["id"], payload, headers)
    return get_success_data(resp)


def approve_review(api: ApiClient, pid: str,
                    order_id: str, review_id: str,
                    rr_pharmacist: Dict[str, Any],
                    **overrides) -> Dict[str, Any]:
    """Approve a pharmacist review (PRD §3.6).

    Identity threading: X-User-ID = rr.id == review.assigned_pharmacist_id.
    """
    payload = approve_review_payload(**overrides)
    headers = make_pharmacist_re_reviewer_headers(rr_pharmacist["id"])
    resp = api.approve_pharmacist_review(pid, order_id, review_id, payload, headers)
    return get_success_data(resp)


def reject_review(api: ApiClient, pid: str, order_id: str, review_id: str,
                   rr_pharmacist: Dict[str, Any],
                   decision_notes: str = "Insufficient justification provided",
                   **overrides) -> Dict[str, Any]:
    """Reject a pharmacist review (PRD §3.6)."""
    payload = reject_review_payload(decision_notes=decision_notes, **overrides)
    headers = make_pharmacist_re_reviewer_headers(rr_pharmacist["id"])
    resp = api.reject_pharmacist_review(pid, order_id, review_id, payload, headers)
    return get_success_data(resp)


def request_change(api: ApiClient, pid: str, order_id: str, review_id: str,
                    rr_pharmacist: Dict[str, Any],
                    decision_notes: str = "Need clarification on dose schedule",
                    **overrides) -> Dict[str, Any]:
    """Request changes on a pharmacist review (PRD §3.6)."""
    payload = request_change_payload(decision_notes=decision_notes, **overrides)
    headers = make_pharmacist_re_reviewer_headers(rr_pharmacist["id"])
    resp = api.request_change_pharmacist_review(pid, order_id, review_id, payload, headers)
    return get_success_data(resp)


def resume_review(api: ApiClient, pid: str, order_id: str, review_id: str,
                   rr_pharmacist: Dict[str, Any]) -> Dict[str, Any]:
    """Resume a pharmacist review from REQUEST_CHANGE → IN_REVIEW (PRD §3.6)."""
    headers = make_pharmacist_re_reviewer_headers(rr_pharmacist["id"])
    resp = api.resume_pharmacist_review(pid, order_id, review_id, headers)
    return get_success_data(resp)


def dispense_order(api: ApiClient, pid: str, order_id: str,
                    pharmacist: Dict[str, Any]) -> Dict[str, Any]:
    """Dispense an order as a Pharmacist (PRD §3.6)."""
    headers = make_pharmacist_headers(pharmacist["id"])
    resp = api.dispense_order(pid, order_id, headers)
    return get_success_data(resp)


def ship_order(api: ApiClient, pid: str, order_id: str) -> Dict[str, Any]:
    resp = api.ship_order(pid, order_id, TEST_USERS["admin_headers"])
    return get_success_data(resp)


def deliver_order(api: ApiClient, pid: str, order_id: str) -> Dict[str, Any]:
    resp = api.deliver_order(pid, order_id, TEST_USERS["admin_headers"])
    return get_success_data(resp)


def cancel_order(api: ApiClient, pid: str, order: Dict[str, Any]) -> Dict[str, Any]:
    headers = make_customer_headers(order["customer_id"])
    resp = api.cancel_order(pid, order["id"], headers)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 3: Composite scenarios
# ---------------------------------------------------------------------------

def setup_basic_platform(api: ApiClient = api_client,
                           clock_iso: str = "2025-01-01T00:00:00.000Z"
                           ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Active platform + active vendor, ready for further setup. Returns (platform, vendor)."""
    pf = setup_platform_at_clock(api, clock_iso)
    vendor = create_vendor(api, pf["id"])
    return pf, vendor


def setup_otc_purchase_scenario(api: ApiClient = api_client,
                                  clock_iso: str = "2025-01-01T00:00:00.000Z",
                                  customer_overrides: Optional[Dict[str, Any]] = None,
                                  ) -> Dict[str, Any]:
    """Build an OTC purchase scenario.

    Returns dict with: platform, vendor, drug (OTC, ON_SHELF), customer.
    """
    pf, vendor = setup_basic_platform(api, clock_iso)
    drug = create_otc_drug_on_shelf(api, pf["id"], vendor["id"])
    customer = create_customer(api, pf["id"], **(customer_overrides or {}))
    return {
        "platform": pf,
        "vendor": vendor,
        "drug": drug,
        "customer": customer,
    }


def setup_prescription_scenario(api: ApiClient = api_client,
                                  clock_iso: str = "2025-01-01T00:00:00.000Z",
                                  drug_overrides: Optional[Dict[str, Any]] = None,
                                  customer_overrides: Optional[Dict[str, Any]] = None,
                                  ) -> Dict[str, Any]:
    """Build a full prescription scenario with two pharmacists (PR + RR).

    Returns: platform, vendor, drug (PRESCRIPTION ON_SHELF), customer
    (real_name_verified=True), pr_pharmacist, rr_pharmacist. Pharmacists are
    distinct ids per PRD §3.6 segregation-of-duties.
    """
    pf, vendor = setup_basic_platform(api, clock_iso)
    drug = create_prescription_drug_on_shelf(api, pf["id"], vendor["id"],
                                                **(drug_overrides or {}))
    cust_kw = {"real_name_verified": True}
    cust_kw.update(customer_overrides or {})
    customer = create_customer(api, pf["id"], **cust_kw)
    pr, rr = create_two_pharmacists(api, pf["id"])
    return {
        "platform": pf,
        "vendor": vendor,
        "drug": drug,
        "customer": customer,
        "pr_pharmacist": pr,
        "rr_pharmacist": rr,
    }


def setup_approved_prescription_with_order(api: ApiClient = api_client,
                                              clock_iso: str = "2025-01-01T00:00:00.000Z",
                                              issued_at: Optional[str] = None,
                                              validity_days: int = 30,
                                              qty: int = 1,
                                              unit_price_cents: int = 12_999,
                                              drug_overrides: Optional[Dict[str, Any]] = None,
                                              customer_overrides: Optional[Dict[str, Any]] = None,
                                              ) -> Dict[str, Any]:
    """Approved Prescription + UNPAID/PENDING_REVIEW Order referencing it.

    Useful starting point for tests of pay, open-pharmacist-review,
    cancel, reject cascades, refund cascades, etc. Returns the full bag.
    """
    s = setup_prescription_scenario(api, clock_iso,
                                       drug_overrides=drug_overrides,
                                       customer_overrides=customer_overrides)
    pf, drug, customer = s["platform"], s["drug"], s["customer"]
    pr, rr = s["pr_pharmacist"], s["rr_pharmacist"]
    rx = upload_and_approve_prescription(
        api, pf["id"], customer, pr,
        drug_items=[prescription_item(drug["id"], qty=qty)],
        issued_at=issued_at or clock_iso,
        validity_days=validity_days,
    )
    order = place_order(api, pf["id"], customer,
                          items=[order_item(drug["id"], qty=qty,
                                             unit_price_cents=unit_price_cents)],
                          prescription_id=rx["id"])
    return {**s, "prescription": rx, "order": order}


def setup_order_in_review(api: ApiClient = api_client,
                            clock_iso: str = "2025-01-01T00:00:00.000Z",
                            paid: bool = False,
                            **overrides) -> Dict[str, Any]:
    """Order in PHARMACIST_REVIEWING state with an open IN_REVIEW PharmacistReview.

    If paid=True, the order is PAID before opening the review (PRD §3.5
    permits payment while dispensing_status is PENDING_REVIEW).
    Returns scenario dict with 'review' key.
    """
    s = setup_approved_prescription_with_order(api, clock_iso=clock_iso, **overrides)
    pf, order, rr = s["platform"], s["order"], s["rr_pharmacist"]
    if paid:
        s["order"] = pay_order(api, pf["id"], order)
        order = s["order"]
    review = open_pharmacist_review(api, pf["id"], order, rr)
    s["review"] = review
    return s


def setup_otc_order_in_review(api: ApiClient = api_client,
                                clock_iso: str = "2025-01-01T00:00:00.000Z",
                                paid: bool = False,
                                qty: int = 1,
                                unit_price_cents: int = 1000,
                                ) -> Dict[str, Any]:
    """OTC order in PHARMACIST_REVIEWING (no prescription required).

    PRD §3.6: opening a re-review on an OTC order does not require a
    prescription, but the order must be PENDING_REVIEW and the second-line
    pharmacist must be ACTIVE. Returns dict including 'review' key.
    """
    pf = setup_platform_at_clock(api, clock_iso)
    vendor = create_vendor(api, pf["id"])
    drug = create_otc_drug_on_shelf(api, pf["id"], vendor["id"])
    customer = create_customer(api, pf["id"], real_name_verified=True)
    rr = create_pharmacist(api, pf["id"])
    order = place_order(api, pf["id"], customer,
                          items=[order_item(drug["id"], qty=qty,
                                             unit_price_cents=unit_price_cents)])
    if paid:
        order = pay_order(api, pf["id"], order)
    review = open_pharmacist_review(api, pf["id"], order, rr)
    return {
        "platform": pf,
        "vendor": vendor,
        "drug": drug,
        "customer": customer,
        "rr_pharmacist": rr,
        "order": order,
        "review": review,
    }


# ---------------------------------------------------------------------------
# Tier 4: Cold chain
# ---------------------------------------------------------------------------

def setup_cold_chain_dispatched(api: ApiClient = api_client,
                                  clock_iso: str = "2025-01-01T00:00:00.000Z",
                                  **drug_overrides
                                  ) -> Dict[str, Any]:
    """Set up an APPROVED order requiring cold chain, with a DISPATCHED ColdChainShipment.

    Walks: platform → vendor → cold-chain OTC drug ON_SHELF → courier-qualified
    pharmacist + RR pharmacist (so we can re-review and approve) →
    customer (verified) → order → pay → open-review → approve-review (so
    dispensing_status reaches APPROVED) → dispatch shipment.
    Returns full bag with 'order' and 'shipment'.
    """
    pf = setup_platform_at_clock(api, clock_iso)
    vendor = create_vendor(api, pf["id"])
    drug = create_cold_chain_drug_on_shelf(api, pf["id"], vendor["id"], **drug_overrides)
    customer = create_customer(api, pf["id"], real_name_verified=True)
    courier_ph = create_pharmacist(api, pf["id"], courier_qualified=True,
                                     full_name="Courier 1")
    rr = create_pharmacist(api, pf["id"], full_name="Cold-chain RR")

    order = place_order(api, pf["id"], customer,
                          items=[order_item(drug["id"], qty=1, unit_price_cents=5000)])
    order = pay_order(api, pf["id"], order)
    review = open_pharmacist_review(api, pf["id"], order, rr)
    review = approve_review(api, pf["id"], order["id"], review["id"], rr)
    # Now order.dispensing_status is APPROVED — dispatch a cold-chain shipment.
    shipment_payload = create_shipment_payload(order["id"], courier_ph["id"])
    resp = api.create_cold_chain_shipment(pf["id"], shipment_payload,
                                            TEST_USERS["admin_headers"])
    shipment = get_success_data(resp)
    # Refresh order so we have cold_chain_shipment_id and updated version.
    order_resp = api.get_order(pf["id"], order["id"], TEST_USERS["admin_headers"])
    order = get_success_data(order_resp)
    return {
        "platform": pf,
        "vendor": vendor,
        "drug": drug,
        "customer": customer,
        "courier_pharmacist": courier_ph,
        "rr_pharmacist": rr,
        "order": order,
        "review": review,
        "shipment": shipment,
    }


def append_readings(api: ApiClient, pid: str, shipment_id: str,
                     readings: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Append a list of readings; returns the final shipment after the last append."""
    final = None
    for r in readings:
        resp = api.append_cold_chain_reading(pid, shipment_id, r,
                                                TEST_USERS["admin_headers"])
        final = get_success_data(resp)
    return final


def setup_cold_chain_with_score(api: ApiClient = api_client,
                                  target_score: int = 0,
                                  clock_iso: str = "2025-01-01T00:00:00.000Z",
                                  ) -> Dict[str, Any]:
    """Build a cold-chain shipment whose excursion_score equals target_score exactly.

    Construction strategy: critical readings (severity 5) carry 5 points
    per minute window; we use ceil(seconds/60)=1-min windows by spacing
    the next reading exactly 60 seconds after the previous critical
    reading, then drop to the safe band.

    For target_score = 5*k (k integer >= 0): emit k critical readings
    each 60 seconds apart, then a final safe-band reading (severity 0,
    last-window=1). Per PRD §3.7 the last reading carries a per-reading
    score of 0, so excursion_score = 5*k.

    For other targets, generic recipes are not encoded — caller should
    pass target_score that is a multiple of 5, or use append_readings
    directly for custom shapes.
    """
    if target_score % 5 != 0 or target_score < 0:
        raise ValueError("target_score must be a non-negative multiple of 5 in this helper")

    s = setup_cold_chain_dispatched(api, clock_iso=clock_iso)
    pf = s["platform"]
    shipment = s["shipment"]
    base = clock_iso  # readings are placed within this trace
    readings: List[Dict[str, Any]] = []
    k = target_score // 5
    for i in range(k):
        readings.append(reading_payload(add_seconds(base, 60 * i), 200))   # 20.0°C critical
    # Final safe-band reading; window for last reading is 1 by §3.7.
    readings.append(reading_payload(add_seconds(base, 60 * k), 27))  # 2.7°C safe
    final_shipment = append_readings(api, pf["id"], shipment["id"], readings)
    s["shipment"] = final_shipment
    return s


# ---------------------------------------------------------------------------
# Tier 4: Purchase limits — cumulative state
# ---------------------------------------------------------------------------

def setup_psychotropic_window_scenario(api: ApiClient = api_client,
                                         clock_iso: str = "2025-01-31T00:00:00.000Z",
                                         window_days: int = 30,
                                         max_units_per_window: int = 10,
                                         existing_paid_units_in_window: int = 8,
                                         existing_paid_units_outside_window: int = 1,
                                         ) -> Dict[str, Any]:
    """Build a customer with prior PAID orders for a psychotropic-II drug.

    PRD §3.5 rolling window: closed at left, open at right; window_start
    = current_clock_iso - window_days days. We build:
      - One historical PAID order with paid_at strictly inside the window
        (existing_paid_units_in_window units).
      - Optionally one historical PAID order with paid_at strictly before
        the window's left edge (existing_paid_units_outside_window units),
        which MUST be excluded from the aggregation.

    We seed the historical orders by advancing the clock to the desired
    paid_at (PRD §3.5 sets paid_at = current_clock_iso), placing/paying
    the order, and then advancing the clock to the test's 'now'.

    Returns the scenario bag with platform, vendor, drug, customer,
    pr_pharmacist, rr_pharmacist, rule, prior_orders.
    """
    # Anchor the test 'now' clock_iso. Wall back two windows so we can
    # seed historical orders without going backwards in time.
    far_past = add_days(clock_iso, -2 * window_days)
    pf = setup_platform_at_clock(api, far_past)
    vendor = create_vendor(api, pf["id"])

    drug = create_and_shelve_drug(
        api, pf["id"], vendor["id"],
        classification="PRESCRIPTION",
        control_category="PSYCHOTROPIC_II",
        per_order_qty_cap=10,
        per_period_qty_cap=100,
    )
    customer = create_customer(api, pf["id"], real_name_verified=True)
    pr, rr = create_two_pharmacists(api, pf["id"])
    rule_resp = api.create_purchase_limit_rule(
        pf["id"],
        create_purchase_limit_rule_payload(
            control_category="PSYCHOTROPIC_II",
            window_days=window_days,
            max_units_per_window=max_units_per_window,
            blocks_special_populations=[],
        ),
        TEST_USERS["admin_headers"],
    )
    rule = get_success_data(rule_resp)

    prior_orders: List[Dict[str, Any]] = []
    # --- Outside-window historical order (paid_at strictly before window left edge) ---
    if existing_paid_units_outside_window > 0:
        outside_paid_at = add_days(clock_iso, -(window_days + 1))
        advance_clock(api, pf["id"], outside_paid_at)
        rx_outside = upload_and_approve_prescription(
            api, pf["id"], customer, pr,
            drug_items=[prescription_item(drug["id"],
                                            qty=existing_paid_units_outside_window)],
            issued_at=outside_paid_at,
            validity_days=999,
        )
        order_outside = place_order(
            api, pf["id"], customer,
            items=[order_item(drug["id"],
                                qty=existing_paid_units_outside_window,
                                unit_price_cents=10_000)],
            prescription_id=rx_outside["id"],
        )
        order_outside = pay_order(api, pf["id"], order_outside)
        prior_orders.append(order_outside)

    # --- Inside-window historical order ---
    if existing_paid_units_in_window > 0:
        inside_paid_at = add_days(clock_iso, -(window_days // 2))
        advance_clock(api, pf["id"], inside_paid_at)
        rx_inside = upload_and_approve_prescription(
            api, pf["id"], customer, pr,
            drug_items=[prescription_item(drug["id"],
                                            qty=existing_paid_units_in_window)],
            issued_at=inside_paid_at,
            validity_days=999,
        )
        order_inside = place_order(
            api, pf["id"], customer,
            items=[order_item(drug["id"],
                                qty=existing_paid_units_in_window,
                                unit_price_cents=10_000)],
            prescription_id=rx_inside["id"],
        )
        order_inside = pay_order(api, pf["id"], order_inside)
        prior_orders.append(order_inside)

    # Move clock to test's 'now'.
    advance_clock(api, pf["id"], clock_iso)

    return {
        "platform": pf,
        "vendor": vendor,
        "drug": drug,
        "customer": customer,
        "pr_pharmacist": pr,
        "rr_pharmacist": rr,
        "rule": rule,
        "prior_orders": prior_orders,
    }


# ---------------------------------------------------------------------------
# Tier 5: ADR scenarios
# ---------------------------------------------------------------------------

def setup_adr(api: ApiClient = api_client,
                clock_iso: str = "2025-01-01T00:00:00.000Z",
                severity: str = "NON_SERIOUS",
                ) -> Dict[str, Any]:
    """Create an ADR in REPORTED state.

    Customer reports an ADR for an OTC drug (most concise path). Returns
    bag including 'report'.
    """
    pf = setup_platform_at_clock(api, clock_iso)
    vendor = create_vendor(api, pf["id"])
    drug = create_otc_drug_on_shelf(api, pf["id"], vendor["id"])
    customer = create_customer(api, pf["id"], real_name_verified=True)
    rr = create_pharmacist(api, pf["id"], full_name="ADR-RR")
    payload = create_adr_payload(drug["id"], customer["id"],
                                   reporter_kind="PATIENT",
                                   severity=severity)
    resp = api.create_adr(pf["id"], payload, make_customer_headers(customer["id"]))
    report = get_success_data(resp)
    return {
        "platform": pf,
        "vendor": vendor,
        "drug": drug,
        "customer": customer,
        "rr_pharmacist": rr,
        "report": report,
    }


# ---------------------------------------------------------------------------
# Tier 5: Vendor qualification scoring
# ---------------------------------------------------------------------------

def setup_vendor_with_expiries(api: ApiClient = api_client,
                                 clock_iso: str = "2025-01-15T00:00:00.000Z",
                                 license_expires_at: Optional[str] = None,
                                 permit_expires_at: Optional[str] = None,
                                 ) -> Dict[str, Any]:
    """Create platform + vendor with explicit expiry dates and clock.

    Useful for vendor-qualification scoring tests that need to control
    L_days and P_days exactly.
    """
    pf = setup_platform_at_clock(api, clock_iso)
    vendor = create_vendor(api, pf["id"],
                              business_license_expires_at=license_expires_at or FAR_FUTURE_ISO,
                              drug_operation_permit_expires_at=permit_expires_at or FAR_FUTURE_ISO)
    return {"platform": pf, "vendor": vendor}


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------

def get_audit_logs(api: ApiClient, pid: str, **params) -> List[Dict[str, Any]]:
    """List audit logs (PRD §2.8). Returns the data array of entries."""
    resp = api.list_audit_logs(pid, TEST_USERS["admin_headers"], params=params or None)
    payload = resp.json() if hasattr(resp, "json") else resp.get("body", {})
    # Be tolerant: some envelope formats return data as either list or {data: list}.
    data = payload.get("data") if isinstance(payload, dict) else payload
    if isinstance(data, dict) and "items" in data:
        return data["items"]
    if isinstance(data, list):
        return data
    return []


def get_external_events(api: ApiClient, pid: str, **params) -> List[Dict[str, Any]]:
    """List external events (PRD §2.8). Returns the data array."""
    resp = api.list_external_events(pid, TEST_USERS["admin_headers"], params=params or None)
    payload = resp.json() if hasattr(resp, "json") else resp.get("body", {})
    data = payload.get("data") if isinstance(payload, dict) else payload
    if isinstance(data, dict) and "items" in data:
        return data["items"]
    if isinstance(data, list):
        return data
    return []


def get_order(api: ApiClient, pid: str, order_id: str) -> Dict[str, Any]:
    resp = api.get_order(pid, order_id, TEST_USERS["admin_headers"])
    return get_success_data(resp)


def get_prescription(api: ApiClient, pid: str, rx_id: str) -> Dict[str, Any]:
    resp = api.get_prescription(pid, rx_id, TEST_USERS["admin_headers"])
    return get_success_data(resp)


def get_drug(api: ApiClient, pid: str, drug_id: str) -> Dict[str, Any]:
    resp = api.get_drug(pid, drug_id, TEST_USERS["admin_headers"])
    return get_success_data(resp)


def get_vendor(api: ApiClient, pid: str, vendor_id: str) -> Dict[str, Any]:
    resp = api.get_vendor(pid, vendor_id, TEST_USERS["admin_headers"])
    return get_success_data(resp)


def get_pharmacist(api: ApiClient, pid: str, pharmacist_id: str) -> Dict[str, Any]:
    resp = api.get_pharmacist(pid, pharmacist_id, TEST_USERS["admin_headers"])
    return get_success_data(resp)


def get_shipment(api: ApiClient, pid: str, shipment_id: str) -> Dict[str, Any]:
    resp = api.get_cold_chain_shipment(pid, shipment_id, TEST_USERS["admin_headers"])
    return get_success_data(resp)


def get_review(api: ApiClient, pid: str, order_id: str, review_id: str) -> Dict[str, Any]:
    resp = api.get_pharmacist_review(pid, order_id, review_id, TEST_USERS["admin_headers"])
    return get_success_data(resp)


def get_adr_report(api: ApiClient, pid: str, report_id: str) -> Dict[str, Any]:
    resp = api.get_adr(pid, report_id, TEST_USERS["admin_headers"])
    return get_success_data(resp)


def add_to_denylist(api: ApiClient, pid: str, prescriber_license_no: str,
                      reason: str = "Test reason") -> Dict[str, Any]:
    resp = api.add_prescriber_to_denylist(
        pid, denylist_entry_payload(prescriber_license_no, reason),
        TEST_USERS["admin_headers"],
    )
    return get_success_data(resp)
