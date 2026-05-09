"""Tests for PRD §3.5 — Purchase order creation, payment cascade, and PRD
§2.10 idempotent external event processing.
"""

import pytest

from test_helpers import (
    api_client,
    assert_purchase_order,
    create_purchase_order_payload,
    emit_event_payload,
    emit_payment_received,
    make_buyer_headers,
    setup_holding_reservation,
    setup_paid_purchase_order,
    validate_error,
    validate_success,
)


# ──────────────────────────────────────────────────────────
# §3.5 PO creation snapshots
# ──────────────────────────────────────────────────────────


def test_purchase_order_snapshots_listing_fields(api):
    """PRD §3.5: "On creation the system snapshots the listing's vehicle_id
    and seller_id onto the order's vehicle_id and seller_id, sets the
    agreed_price_cents to the winning Bid.amount_cents (for auctions) or to
    the ask_price_cents (for fixed-price reservations), sets the buyer_id to
    the acting buyer, and persists the order in status PENDING_PAYMENT."
    """
    seller, vehicle, listing, buyer, _ = setup_holding_reservation(
        ask_price_cents=2_000_000
    )
    payload = create_purchase_order_payload(listing["id"])
    payload["package_code"] = "STANDARD"
    res = api.create_purchase_order(payload, make_buyer_headers(buyer["id"]))
    po = validate_success(res, 201)
    assert_purchase_order(po)
    assert po["status"] == "PENDING_PAYMENT"
    assert po["vehicle_id"] == vehicle["id"]
    assert po["seller_id"] == seller["id"]
    assert po["buyer_id"] == buyer["id"]
    assert po["agreed_price_cents"] == 2_000_000
    assert po["payment_method"] == "FULL_PAYMENT"


def test_full_payment_down_payment_equals_agreed_price(api):
    """PRD §3.5: "For FULL_PAYMENT, down_payment_cents equals
    agreed_price_cents and loan_id remains null."
    """
    seller, vehicle, listing, buyer, _ = setup_holding_reservation(
        ask_price_cents=2_000_000
    )
    payload = create_purchase_order_payload(listing["id"], payment_method="FULL_PAYMENT")
    payload["package_code"] = "STANDARD"
    res = api.create_purchase_order(payload, make_buyer_headers(buyer["id"]))
    po = validate_success(res, 201)
    assert po["down_payment_cents"] == po["agreed_price_cents"]
    assert po.get("loan_id") is None


# ──────────────────────────────────────────────────────────
# §3.5 PO cancel (PENDING_PAYMENT → CANCELLED)
# ──────────────────────────────────────────────────────────


def test_cancel_pending_payment_releases_deposit_and_reactivates_listing(api, admin_headers):
    """PRD §3.5: "A buyer may cancel an order before payment by transitioning
    the order from PENDING_PAYMENT to CANCELLED. Cancellation releases any
    held bid or reservation deposit, restores the listing from RESERVED back
    to ACTIVE, and cascades any associated loan to CANCELLED."
    """
    seller, vehicle, listing, buyer, reservation = setup_holding_reservation()
    payload = create_purchase_order_payload(listing["id"])
    payload["package_code"] = "STANDARD"
    po = validate_success(api.create_purchase_order(payload, make_buyer_headers(buyer["id"])), 201)

    cancelled = validate_success(
        api.cancel_purchase_order(po["id"], make_buyer_headers(buyer["id"])), 200
    )
    assert cancelled["status"] == "CANCELLED"
    refreshed_buyer = validate_success(api.get_buyer(buyer["id"], make_buyer_headers(buyer["id"])), 200)
    assert refreshed_buyer["deposit_held_cents"] == 0
    listing_after = validate_success(api.get_listing(listing["id"], admin_headers), 200)
    assert listing_after["status"] == "ACTIVE"


# ──────────────────────────────────────────────────────────
# §3.5 PAID cascade
# ──────────────────────────────────────────────────────────


def test_paid_event_advances_po_through_paid_to_awaiting_transfer(api, admin_headers):
    """PRD §3.5: "Once these side-effects have completed, the order
    auto-transitions from PAID to AWAITING_TRANSFER."
    """
    state = setup_paid_purchase_order(ask_price_cents=2_000_000)
    po_after = validate_success(
        api.get_purchase_order(
            state["purchase_order"]["id"], make_buyer_headers(state["buyer"]["id"])
        ),
        200,
    )
    # PRD §3.5: "PAID is set first, then AWAITING_TRANSFER is auto-set ..."
    assert po_after["status"] == "AWAITING_TRANSFER"
    assert po_after.get("paid_at") is not None


def test_paid_cascades_listing_to_sold_and_vehicle_to_sold(api, admin_headers):
    """PRD §3.5: "the listing transitions from RESERVED to SOLD; the vehicle
    transitions from LISTED to SOLD".
    """
    state = setup_paid_purchase_order(ask_price_cents=2_000_000)
    listing_after = validate_success(api.get_listing(state["listing"]["id"], admin_headers), 200)
    vehicle_after = validate_success(api.get_vehicle(state["vehicle"]["id"], admin_headers), 200)
    assert listing_after["status"] == "SOLD"
    assert vehicle_after["vehicle_status"] == "SOLD"


def test_paid_creates_transfer_case_in_docs_pending(api, admin_headers):
    """PRD §3.5: "a new TransferCase is created in DOCS_PENDING with the
    required-document checklist seeded."
    PRD §3.7: "with a seeded required_documents checklist. Each item in the
    checklist is {doc_type, submitted, doc_url} with doc_type drawn from
    ID_BUYER, ID_SELLER, TITLE, REGISTRATION, RELEASE_OF_LIEN, and
    EMISSIONS_CERT; every item starts with submitted false and doc_url null."
    """
    from test_helpers import assert_required_documents_seeded

    state = setup_paid_purchase_order(ask_price_cents=2_000_000)
    transfer = state["transfer"]
    assert transfer is not None, (
        "PRD §3.5: a TransferCase must be created on PAID; none found"
    )
    assert transfer["status"] == "DOCS_PENDING"
    assert_required_documents_seeded(transfer)
    # Every item starts unsubmitted with null URL.
    for item in transfer["required_documents"]:
        assert item.get("submitted") is False
        assert item.get("doc_url") is None


def test_paid_activates_warranty(api, admin_headers):
    """PRD §3.5: "the matching Warranty is activated by moving from
    PENDING_ACTIVATION to ACTIVE, with effective_at set to the order's
    paid_at and expires_at computed per §3.8."
    """
    state = setup_paid_purchase_order(package_code="STANDARD", ask_price_cents=2_000_000)
    warranty = state["warranty"]
    assert warranty is not None, "PRD §3.5: matching Warranty must be activated on PAID"
    assert warranty["status"] == "ACTIVE"
    assert warranty["effective_at"] is not None


# ──────────────────────────────────────────────────────────
# §2.10 Idempotent External Event Processing
# ──────────────────────────────────────────────────────────


def test_duplicate_event_idempotency_key_replays_marker(api, admin_headers):
    """PRD §2.10: "any later arrival with the same idempotency_key is silently
    absorbed — the original ExternalEvent row is returned, no downstream
    side-effects fire, the response carries HTTP 200, and the response body's
    error_id is ERR_IDEMPOTENCY_REPLAY to mark it as a replay rather than a
    fresh action."
    """
    seller, vehicle, listing, buyer, _ = setup_holding_reservation(ask_price_cents=2_000_000)
    payload = create_purchase_order_payload(listing["id"])
    payload["package_code"] = "STANDARD"
    po = validate_success(api.create_purchase_order(payload, make_buyer_headers(buyer["id"])), 201)

    key = "idem-test-" + po["id"]
    body = emit_event_payload(
        source="PAYMENT",
        event_type="payment_received",
        payload={"purchase_order_id": po["id"]},
        idempotency_key=key,
    )
    first = api.emit_event(body, admin_headers)
    assert first.status_code in (200, 201)

    # Replay: same key → 200 with ERR_IDEMPOTENCY_REPLAY in body.
    replay = api.emit_event(body, admin_headers)
    assert replay.status_code == 200, (
        f"PRD §2.10 says replay returns HTTP 200; got {replay.status_code}"
    )
    body_json = replay.json()
    error_id = body_json.get("data", {}).get("error_id")
    assert error_id == "ERR_IDEMPOTENCY_REPLAY", (
        f"PRD §2.10: replay must carry error_id ERR_IDEMPOTENCY_REPLAY; got {error_id!r}"
    )
