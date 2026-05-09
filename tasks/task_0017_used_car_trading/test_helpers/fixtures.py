"""Composite setup helpers for multi-step test prerequisites.

Most interesting test claims require the system to be in a specific state that
takes 5–15 API calls to reach. These helpers encapsulate the preambles so tests
focus on assertions, not plumbing.

Identity threading (mandatory): after a fixture creates a Seller or Buyer, any
ownership-gated call in the same fixture (or in a downstream fixture) MUST use
``make_seller_headers(seller["id"])`` / ``make_buyer_headers(buyer["id"])`` —
never fall back to the shared constant. Otherwise every ownership check on the
server rejects every request, cascading "Setup failed" into dozens of tests.

Setup helpers use ``get_success_data()`` (lenient — accepts any 2xx) so a
broken implementation surfaces as "setup failed" rather than confusing
mid-test assertions.
"""

import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    advance_clock_payload,
    book_appointment_payload,
    create_assessment_payload,
    create_bid_payload,
    create_buyer_payload,
    create_listing_payload,
    create_loan_payload,
    create_purchase_order_payload,
    create_reservation_payload,
    create_seller_payload,
    create_vehicle_payload,
    dispute_payload,
    emit_event_payload,
    finalize_payload,
    onsite_findings_payload,
    upload_doc_payload,
    vin_history,
    warranty_claim_payload,
)
from .test_users import (
    TEST_USERS,
    make_admin_headers,
    make_buyer_headers,
    make_inspector_headers,
    make_seller_headers,
)
from .constants import TRANSFER_DOC_TYPES


ADMIN_HEADERS = TEST_USERS["admin_headers"]
INSPECTOR_HEADERS = TEST_USERS["inspector_headers"]


# ──────────────────────────────────────────────────────────
# Server-clock helpers — tests share a single backend across the session, and
# any prior test that called /_clock/advance leaves the server's virtual clock
# pinned at that future instant. Tests must compute appointment / expiry
# offsets relative to the SERVER's current clock, not the local wall clock.
# ──────────────────────────────────────────────────────────


def server_now() -> datetime:
    """Return the server's current virtual clock as a UTC datetime.

    Reads from the response envelope's ``meta.api_request_timestamp`` of a
    no-op admin GET — every response stamps that field with the server clock.
    """
    res = api_client.list_audit_logs(ADMIN_HEADERS, params={"limit": 1})
    body = res.json()
    ts = body.get("meta", {}).get("api_request_timestamp")
    if not ts:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def server_now_plus(delta: timedelta) -> str:
    """Return ISO 8601 UTC string for server_now() + delta."""
    return (server_now() + delta).strftime("%Y-%m-%dT%H:%M:%S.000Z")


# ──────────────────────────────────────────────────────────
# Tier 1 — Single-actor creation helpers
# ──────────────────────────────────────────────────────────


def register_seller(**overrides: Any) -> Dict[str, Any]:
    """Create a Seller and return the persisted entity."""
    res = api_client.create_seller(create_seller_payload(**overrides), ADMIN_HEADERS)
    return get_success_data(res)


def register_buyer(**overrides: Any) -> Dict[str, Any]:
    """Create a Buyer and return the persisted entity."""
    res = api_client.create_buyer(create_buyer_payload(**overrides), ADMIN_HEADERS)
    return get_success_data(res)


def register_vehicle(seller: Dict[str, Any], **overrides: Any) -> Dict[str, Any]:
    """Create a Vehicle owned by the given seller. Acts as the owning seller
    so PRD §2.1 ownership checks resolve."""
    payload = create_vehicle_payload(**overrides)
    res = api_client.create_vehicle(payload, make_seller_headers(seller["id"]))
    return get_success_data(res)


# ──────────────────────────────────────────────────────────
# Tier 2 — Assessment progression (DRAFT → ONSITE_PENDING → FINALIZED)
# ──────────────────────────────────────────────────────────


def create_draft_assessment(
    vehicle: Dict[str, Any], **overrides: Any
) -> Dict[str, Any]:
    """Create AssessmentReport in DRAFT for the given vehicle."""
    payload = create_assessment_payload(**overrides)
    res = api_client.create_assessment(vehicle["id"], payload, INSPECTOR_HEADERS)
    return get_success_data(res)


def advance_assessment_to_onsite(assessment: Dict[str, Any]) -> Dict[str, Any]:
    """DRAFT → ONSITE_PENDING. Computes provisional_valuation_cents."""
    res = api_client.request_onsite(assessment["id"], INSPECTOR_HEADERS)
    return get_success_data(res)


def finalize_assessment(
    assessment: Dict[str, Any],
    onsite: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """ONSITE_PENDING → FINALIZED. Computes mileage discrepancy, final
    valuation, assessment score."""
    body = finalize_payload(onsite=onsite)
    res = api_client.finalize_assessment(assessment["id"], body, INSPECTOR_HEADERS)
    return get_success_data(res)


def setup_finalized_assessment(
    seller: Optional[Dict[str, Any]] = None,
    vehicle_overrides: Optional[Dict[str, Any]] = None,
    history: Optional[List[Dict[str, Any]]] = None,
    onsite: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Walk a vehicle through to a FINALIZED assessment.

    Returns ``(seller, vehicle, finalized_assessment)``. If ``seller`` is None
    a fresh seller is registered. ``onsite`` defaults to A/A/B grades with
    mileage_km_observed equal to the vehicle's declared mileage (no
    discrepancy).
    """
    seller = seller or register_seller()
    vehicle = register_vehicle(seller, **(vehicle_overrides or {}))
    if history is None:
        history = vin_history(maintenance=1)
    draft = create_draft_assessment(vehicle, vin_history_records=history)
    onsite_pending = advance_assessment_to_onsite(draft)
    if onsite is None:
        onsite = onsite_findings_payload(
            mileage_km_observed=vehicle["declared_mileage_km"]
        )
    finalized = finalize_assessment(onsite_pending, onsite=onsite)
    return seller, vehicle, finalized


# ──────────────────────────────────────────────────────────
# Tier 3 — Listing lifecycle (DRAFT → UNDER_REVIEW → ACTIVE)
# ──────────────────────────────────────────────────────────


def create_draft_listing(
    seller: Dict[str, Any],
    vehicle: Dict[str, Any],
    assessment: Dict[str, Any],
    sale_mode: str = "FIXED_PRICE",
    **overrides: Any,
) -> Dict[str, Any]:
    """Create a Listing in DRAFT pinned to the given assessment."""
    payload = create_listing_payload(
        vehicle["id"], assessment["id"], sale_mode=sale_mode, **overrides
    )
    res = api_client.create_listing(payload, make_seller_headers(seller["id"]))
    return get_success_data(res)


def submit_listing(seller: Dict[str, Any], listing: Dict[str, Any]) -> Dict[str, Any]:
    """DRAFT → UNDER_REVIEW."""
    res = api_client.submit_listing(listing["id"], make_seller_headers(seller["id"]))
    return get_success_data(res)


def approve_listing(listing: Dict[str, Any]) -> Dict[str, Any]:
    """UNDER_REVIEW → ACTIVE."""
    res = api_client.approve_listing(listing["id"], ADMIN_HEADERS)
    return get_success_data(res)


def setup_active_listing(
    sale_mode: str = "FIXED_PRICE",
    ask_price_cents: int = 2_000_000,
    reserve_price_cents: Optional[int] = None,
    seller: Optional[Dict[str, Any]] = None,
    vehicle_overrides: Optional[Dict[str, Any]] = None,
    history: Optional[List[Dict[str, Any]]] = None,
    onsite: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Walk a listing through to ACTIVE. Returns
    ``(seller, vehicle, assessment, listing)``."""
    seller, vehicle, assessment = setup_finalized_assessment(
        seller=seller,
        vehicle_overrides=vehicle_overrides,
        history=history,
        onsite=onsite,
    )
    listing_kwargs: Dict[str, Any] = {"ask_price_cents": ask_price_cents}
    if sale_mode == "AUCTION":
        listing_kwargs["reserve_price_cents"] = (
            reserve_price_cents if reserve_price_cents is not None else ask_price_cents
        )
    listing = create_draft_listing(
        seller, vehicle, assessment, sale_mode=sale_mode, **listing_kwargs
    )
    listing = submit_listing(seller, listing)
    listing = approve_listing(listing)
    return seller, vehicle, assessment, listing


def setup_listing_under_review(
    sale_mode: str = "FIXED_PRICE",
    ask_price_cents: int = 2_000_000,
    photo_urls: Optional[List[str]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Build a listing that has been submitted (UNDER_REVIEW) but not yet
    approved. Returns ``(seller, vehicle, assessment, listing)``."""
    seller, vehicle, assessment = setup_finalized_assessment()
    extras: Dict[str, Any] = {"ask_price_cents": ask_price_cents}
    if sale_mode == "AUCTION":
        extras["reserve_price_cents"] = ask_price_cents
    if photo_urls is not None:
        extras["photo_urls"] = photo_urls
    listing = create_draft_listing(
        seller, vehicle, assessment, sale_mode=sale_mode, **extras
    )
    listing = submit_listing(seller, listing)
    return seller, vehicle, assessment, listing


# ──────────────────────────────────────────────────────────
# Tier 4 — Bidding / Reservation flows
# ──────────────────────────────────────────────────────────


def place_bid(
    buyer: Dict[str, Any], listing: Dict[str, Any], amount_cents: int
) -> Dict[str, Any]:
    res = api_client.place_bid(
        listing["id"],
        create_bid_payload(amount_cents),
        make_buyer_headers(buyer["id"]),
    )
    return get_success_data(res)


def create_reservation(buyer: Dict[str, Any], listing: Dict[str, Any]) -> Dict[str, Any]:
    res = api_client.create_reservation(
        listing["id"],
        make_buyer_headers(buyer["id"]),
        create_reservation_payload(),
    )
    return get_success_data(res)


def setup_auction_with_two_bidders(
    ask_price_cents: int = 1_000_000,
    reserve_price_cents: int = 1_000_000,
) -> Tuple[
    Dict[str, Any],
    Dict[str, Any],
    Dict[str, Any],
    Dict[str, Any],
    Dict[str, Any],
]:
    """Build an ACTIVE AUCTION listing with two registered buyers ready to
    bid. Returns ``(seller, listing, vehicle, buyer_a, buyer_b)``."""
    seller, vehicle, _, listing = setup_active_listing(
        sale_mode="AUCTION",
        ask_price_cents=ask_price_cents,
        reserve_price_cents=reserve_price_cents,
    )
    buyer_a = register_buyer()
    buyer_b = register_buyer()
    return seller, listing, vehicle, buyer_a, buyer_b


def setup_holding_reservation(
    ask_price_cents: int = 2_000_000,
) -> Tuple[
    Dict[str, Any],
    Dict[str, Any],
    Dict[str, Any],
    Dict[str, Any],
    Dict[str, Any],
]:
    """Build a FIXED_PRICE listing with one buyer holding a HOLDING reservation
    at queue_position 1. Returns ``(seller, vehicle, listing, buyer, reservation)``."""
    seller, vehicle, _, listing = setup_active_listing(
        sale_mode="FIXED_PRICE", ask_price_cents=ask_price_cents
    )
    buyer = register_buyer()
    reservation = create_reservation(buyer, listing)
    return seller, vehicle, listing, buyer, reservation


# ──────────────────────────────────────────────────────────
# Tier 5 — Purchase order / payment / transfer
# ──────────────────────────────────────────────────────────


def create_purchase_order(
    buyer: Dict[str, Any],
    listing: Dict[str, Any],
    payment_method: str = "FULL_PAYMENT",
) -> Dict[str, Any]:
    res = api_client.create_purchase_order(
        create_purchase_order_payload(listing["id"], payment_method=payment_method),
        make_buyer_headers(buyer["id"]),
    )
    return get_success_data(res)


def emit_payment_received(
    purchase_order_id: str, idempotency_key: Optional[str] = None
) -> Dict[str, Any]:
    """Emit a PAYMENT system payment_received event. Triggers PO
    PENDING_PAYMENT → PAID per PRD §3.5."""
    body = emit_event_payload(
        source="PAYMENT",
        event_type="payment_received",
        payload={"purchase_order_id": purchase_order_id},
        idempotency_key=idempotency_key,
    )
    res = api_client.emit_event(body, ADMIN_HEADERS)
    return get_success_data(res)


def submit_all_transfer_documents(
    buyer: Dict[str, Any], transfer_id: str
) -> Dict[str, Any]:
    """Mark every required_documents item submitted (PRD §3.7 prerequisite for
    book-appointment)."""
    last: Dict[str, Any] = {}
    for doc_type in TRANSFER_DOC_TYPES:
        res = api_client.upload_transfer_doc(
            transfer_id,
            upload_doc_payload(doc_type),
            make_buyer_headers(buyer["id"]),
        )
        last = get_success_data(res)
    return last


def setup_paid_purchase_order(
    package_code: str = "STANDARD",
    ask_price_cents: int = 2_000_000,
) -> Dict[str, Any]:
    """Run the full happy path: ACTIVE FIXED_PRICE listing → reservation →
    PO created with the chosen warranty package → payment_received event →
    PO reaches PAID/AWAITING_TRANSFER, Warranty ACTIVE, TransferCase
    DOCS_PENDING.

    Returns a dict with keys: seller, buyer, vehicle, listing, reservation,
    purchase_order, warranty, transfer, paid_at.
    """
    seller, vehicle, listing, buyer, reservation = setup_holding_reservation(
        ask_price_cents=ask_price_cents
    )
    # Some implementations require the warranty package on PO creation; PRD §3.8
    # says "package_code is supplied by the buyer at order time", so include it.
    po_payload = create_purchase_order_payload(
        listing["id"], payment_method="FULL_PAYMENT"
    )
    po_payload["package_code"] = package_code
    po_res = api_client.create_purchase_order(po_payload, make_buyer_headers(buyer["id"]))
    po = get_success_data(po_res)

    emit_payment_received(po["id"])

    po_after = get_success_data(
        api_client.get_purchase_order(po["id"], make_buyer_headers(buyer["id"]))
    )

    # Read warranty + transfer by listing the relevant rows. The PO carries
    # neither id directly per PRD §1.5; we discover them via the audit log
    # filter by target_entity. Simplification: try to fetch by querying the
    # buyer-readable nested-list endpoints if available; fall back to nothing.
    warranty = _find_warranty_for_po(po_after["id"])
    transfer = _find_transfer_for_po(po_after["id"])
    return {
        "seller": seller,
        "buyer": buyer,
        "vehicle": vehicle,
        "listing": listing,
        "reservation": reservation,
        "purchase_order": po_after,
        "warranty": warranty,
        "transfer": transfer,
    }


def _iter_audit_logs(target_entity: str):
    """Yield every audit row for the given target_entity by paginating.
    PRD §2.4 caps `limit` at 100; tests share a single backend across the
    session, so warranty / transfer rows accumulate and a single page is
    insufficient — we must walk every page."""
    seen: set = set()
    offset = 0
    page_size = 100
    while True:
        res = api_client.list_audit_logs(
            ADMIN_HEADERS,
            params={"target_entity": target_entity, "limit": page_size, "offset": offset},
        )
        data = get_success_data(res)
        rows = data if isinstance(data, list) else data.get("items") or data.get("data") or []
        if not isinstance(rows, list) or not rows:
            return
        for entry in rows:
            tid = entry.get("target_id")
            if not tid or tid in seen:
                continue
            seen.add(tid)
            yield tid
        if len(rows) < page_size:
            return
        offset += page_size


def _find_warranty_for_po(po_id: str) -> Optional[Dict[str, Any]]:
    """Find the Warranty corresponding to a PurchaseOrder via the audit log
    (PRD §2.12 says state transitions land in audit_logs)."""
    for wid in _iter_audit_logs("Warranty"):
        warranty_res = api_client.get_warranty(wid, ADMIN_HEADERS)
        if warranty_res.status_code != 200:
            continue
        warranty = get_success_data(warranty_res)
        if warranty.get("purchase_order_id") == po_id:
            return warranty
    return None


def _find_transfer_for_po(po_id: str) -> Optional[Dict[str, Any]]:
    """Find the TransferCase corresponding to a PurchaseOrder via the audit log."""
    for tid in _iter_audit_logs("TransferCase"):
        transfer_res = api_client.get_transfer(tid, ADMIN_HEADERS)
        if transfer_res.status_code != 200:
            continue
        transfer = get_success_data(transfer_res)
        if transfer.get("purchase_order_id") == po_id:
            return transfer
    return None


# ──────────────────────────────────────────────────────────
# Tier 6 — Transfer-rollback and dispute scenarios
# ──────────────────────────────────────────────────────────


def setup_transfer_in_failed_state(
    package_code: str = "STANDARD",
    ask_price_cents: int = 2_000_000,
) -> Dict[str, Any]:
    """Run paid → docs uploaded → appointment booked → clock advanced past
    appointment → transfer_failed event delivered. Returns the same dict as
    ``setup_paid_purchase_order`` plus refreshed transfer in FAILED state.
    """
    state = setup_paid_purchase_order(
        package_code=package_code, ask_price_cents=ask_price_cents
    )
    buyer = state["buyer"]
    transfer = state["transfer"]
    if transfer is None:
        raise RuntimeError("setup failed: TransferCase not found after PAID cascade")

    submit_all_transfer_documents(buyer, transfer["id"])

    # Book appointment 7 days from server-now (within PRD §3.7's 60-day window).
    now = server_now()
    appointment_iso = (now + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    book_res = api_client.book_appointment(
        transfer["id"],
        book_appointment_payload(appointment_at=appointment_iso),
        make_buyer_headers(buyer["id"]),
    )
    get_success_data(book_res)

    # Advance clock past appointment_at → IN_PROGRESS.
    after_appt = (now + timedelta(days=7, hours=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    get_success_data(
        api_client.advance_clock(advance_clock_payload(after_appt), ADMIN_HEADERS)
    )

    # Emit transfer_failed → IN_PROGRESS → FAILED.
    fail_evt = emit_event_payload(
        source="DMV",
        event_type="transfer_failed",
        payload={"transfer_case_id": transfer["id"], "reason": "Title mismatch"},
    )
    get_success_data(api_client.emit_event(fail_evt, ADMIN_HEADERS))

    state["transfer"] = get_success_data(
        api_client.get_transfer(transfer["id"], ADMIN_HEADERS)
    )
    state["purchase_order"] = get_success_data(
        api_client.get_purchase_order(
            state["purchase_order"]["id"], make_buyer_headers(buyer["id"])
        )
    )
    return state


def setup_completed_purchase_order(
    package_code: str = "STANDARD",
    ask_price_cents: int = 2_000_000,
) -> Dict[str, Any]:
    """Run all the way through to TransferCase SUCCEEDED + PO COMPLETED."""
    state = setup_paid_purchase_order(
        package_code=package_code, ask_price_cents=ask_price_cents
    )
    buyer = state["buyer"]
    transfer = state["transfer"]
    if transfer is None:
        raise RuntimeError("setup failed: TransferCase not found after PAID cascade")

    submit_all_transfer_documents(buyer, transfer["id"])

    now = server_now()
    appointment_iso = (now + timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    get_success_data(
        api_client.book_appointment(
            transfer["id"],
            book_appointment_payload(appointment_at=appointment_iso),
            make_buyer_headers(buyer["id"]),
        )
    )
    after_appt = (now + timedelta(days=5, hours=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    get_success_data(
        api_client.advance_clock(advance_clock_payload(after_appt), ADMIN_HEADERS)
    )
    get_success_data(
        api_client.emit_event(
            emit_event_payload(
                source="DMV",
                event_type="transfer_succeeded",
                payload={"transfer_case_id": transfer["id"]},
            ),
            ADMIN_HEADERS,
        )
    )
    state["transfer"] = get_success_data(
        api_client.get_transfer(transfer["id"], ADMIN_HEADERS)
    )
    state["purchase_order"] = get_success_data(
        api_client.get_purchase_order(
            state["purchase_order"]["id"], make_buyer_headers(buyer["id"])
        )
    )
    return state


def file_dispute(
    state: Dict[str, Any], complainant_role: str = "BUYER"
) -> Dict[str, Any]:
    """File a DisputeCase against the state's purchase_order."""
    actor = state["buyer"] if complainant_role == "BUYER" else state["seller"]
    headers = (
        make_buyer_headers(actor["id"])
        if complainant_role == "BUYER"
        else make_seller_headers(actor["id"])
    )
    res = api_client.create_dispute(
        state["purchase_order"]["id"],
        dispute_payload(complainant_role=complainant_role),
        headers,
    )
    return get_success_data(res)


def setup_dispute_at_round(
    state: Dict[str, Any], round_count: int
) -> Dict[str, Any]:
    """Cycle a fresh DisputeCase through start-review / request-more-evidence
    until ``round_count`` is reached. Returns the dispute resource at
    EVIDENCE_REVIEW (or SUBMITTED if round_count == 0). Pre: state must have
    a PO in COMPLETED or AWAITING_TRANSFER (PRD §3.9 dispute eligibility).
    """
    dispute = file_dispute(state)
    for r in range(round_count):
        # SUBMITTED → EVIDENCE_REVIEW (round_count++)
        dispute = get_success_data(
            api_client.start_review_dispute(dispute["id"], ADMIN_HEADERS)
        )
        if r == round_count - 1:
            break
        # EVIDENCE_REVIEW → SUBMITTED (cycle)
        dispute = get_success_data(
            api_client.request_more_evidence(dispute["id"], ADMIN_HEADERS)
        )
    return dispute


# ──────────────────────────────────────────────────────────
# Tier 7 — Loan-flow shortcut for boundary tests
# ──────────────────────────────────────────────────────────


def setup_loan_in_credit_checking(
    lender_code: str = "LENDER_A",
    requested_principal_cents: int = 4_000_000,
    down_payment_ratio_bp: int = 2_000,
    term_months: int = 36,
    ask_price_cents: int = 5_000_000,
) -> Dict[str, Any]:
    """Drive a Loan to CREDIT_CHECKING ready for a credit_check_returned event.

    Returns dict with: seller, buyer, listing, purchase_order, loan.
    """
    seller, vehicle, listing, buyer, reservation = setup_holding_reservation(
        ask_price_cents=ask_price_cents
    )
    po_payload = create_purchase_order_payload(listing["id"], payment_method="LOAN")
    po_payload["package_code"] = "STANDARD"
    po = get_success_data(
        api_client.create_purchase_order(po_payload, make_buyer_headers(buyer["id"]))
    )
    loan = get_success_data(
        api_client.apply_loan(
            po["id"],
            create_loan_payload(
                lender_code=lender_code,
                requested_principal_cents=requested_principal_cents,
                down_payment_ratio_bp=down_payment_ratio_bp,
                term_months=term_months,
            ),
            make_buyer_headers(buyer["id"]),
        )
    )
    loan = get_success_data(api_client.run_credit_check(loan["id"], ADMIN_HEADERS))
    return {
        "seller": seller,
        "buyer": buyer,
        "vehicle": vehicle,
        "listing": listing,
        "purchase_order": po,
        "loan": loan,
    }


def emit_credit_check_returned(loan_id: str, credit_score: int) -> Dict[str, Any]:
    """Emit a BANK credit_check_returned event with the requested credit_score."""
    body = emit_event_payload(
        source="BANK",
        event_type="credit_check_returned",
        payload={"loan_id": loan_id, "credit_score": credit_score},
    )
    res = api_client.emit_event(body, ADMIN_HEADERS)
    return get_success_data(res)
