"""Tests for PRD §3.7 — Ownership transfer at the DMV: document checklist,
appointment booking with 60-day window, transfer_succeeded → ownership change,
transfer_failed → rollback full compensation cascade.
"""

from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    advance_clock_payload,
    api_client,
    book_appointment_payload,
    emit_event_payload,
    make_buyer_headers,
    server_now_plus,
    setup_completed_purchase_order,
    setup_paid_purchase_order,
    setup_transfer_in_failed_state,
    submit_all_transfer_documents,
    upload_doc_payload,
    validate_error,
    validate_success,
)


# ──────────────────────────────────────────────────────────
# §3.7 Document upload prerequisites
# ──────────────────────────────────────────────────────────


def test_book_appointment_with_missing_documents_rejected(api):
    """PRD §3.7: "Once every item has submitted true, the buyer may book a
    DMV appointment ... Document or plate-rule violations are rejected with
    ERR_TRANSFER_DOCS_INCOMPLETE."

    Without uploading any documents, booking must be rejected.
    """
    state = setup_paid_purchase_order(ask_price_cents=2_000_000)
    transfer = state["transfer"]
    buyer = state["buyer"]
    appointment_iso = server_now_plus(timedelta(days=5))
    res = api.book_appointment(
        transfer["id"],
        book_appointment_payload(appointment_at=appointment_iso),
        make_buyer_headers(buyer["id"]),
    )
    validate_error(res, "ERR_TRANSFER_DOCS_INCOMPLETE")


def test_new_number_plate_action_requires_new_plate_number(api):
    """PRD §3.7: "when the action is NEW_NUMBER, the new_plate_number must be
    a non-empty string, and when the action is anything else,
    new_plate_number must remain null. Document or plate-rule violations are
    rejected with ERR_TRANSFER_DOCS_INCOMPLETE."
    """
    state = setup_paid_purchase_order(ask_price_cents=2_000_000)
    transfer = state["transfer"]
    buyer = state["buyer"]
    submit_all_transfer_documents(buyer, transfer["id"])
    appointment_iso = server_now_plus(timedelta(days=5))
    # Action NEW_NUMBER but new_plate_number = null → must reject.
    res = api.book_appointment(
        transfer["id"],
        book_appointment_payload(
            appointment_at=appointment_iso,
            license_plate_action="NEW_NUMBER",
            new_plate_number=None,
        ),
        make_buyer_headers(buyer["id"]),
    )
    validate_error(res, "ERR_TRANSFER_DOCS_INCOMPLETE")


def test_keep_old_action_with_set_new_plate_number_rejected(api):
    """PRD §3.7: "when the action is anything else, new_plate_number must
    remain null." Setting new_plate_number with KEEP_OLD must be rejected
    with ERR_TRANSFER_DOCS_INCOMPLETE.
    """
    state = setup_paid_purchase_order(ask_price_cents=2_000_000)
    transfer = state["transfer"]
    buyer = state["buyer"]
    submit_all_transfer_documents(buyer, transfer["id"])
    appointment_iso = server_now_plus(timedelta(days=5))
    res = api.book_appointment(
        transfer["id"],
        book_appointment_payload(
            appointment_at=appointment_iso,
            license_plate_action="KEEP_OLD",
            new_plate_number="ABC123",
        ),
        make_buyer_headers(buyer["id"]),
    )
    validate_error(res, "ERR_TRANSFER_DOCS_INCOMPLETE")


# ──────────────────────────────────────────────────────────
# §3.7 Appointment window
# ──────────────────────────────────────────────────────────


def test_appointment_in_past_rejected(api):
    """PRD §3.7: "The appointment_at must be strictly later than the current
    instant ... otherwise the booking is rejected with
    ERR_APPOINTMENT_OUT_OF_WINDOW."
    """
    state = setup_paid_purchase_order(ask_price_cents=2_000_000)
    transfer = state["transfer"]
    buyer = state["buyer"]
    submit_all_transfer_documents(buyer, transfer["id"])
    past = server_now_plus(timedelta(days=-1))
    res = api.book_appointment(
        transfer["id"],
        book_appointment_payload(appointment_at=past),
        make_buyer_headers(buyer["id"]),
    )
    validate_error(res, "ERR_APPOINTMENT_OUT_OF_WINDOW")


def test_appointment_more_than_sixty_days_in_future_rejected(api):
    """PRD §3.7: "the gap from now to appointment_at must be at most sixty
    days; otherwise the booking is rejected with ERR_APPOINTMENT_OUT_OF_WINDOW."
    """
    state = setup_paid_purchase_order(ask_price_cents=2_000_000)
    transfer = state["transfer"]
    buyer = state["buyer"]
    submit_all_transfer_documents(buyer, transfer["id"])
    far_future = server_now_plus(timedelta(days=91))
    res = api.book_appointment(
        transfer["id"],
        book_appointment_payload(appointment_at=far_future),
        make_buyer_headers(buyer["id"]),
    )
    validate_error(res, "ERR_APPOINTMENT_OUT_OF_WINDOW")


def test_appointment_within_window_succeeds(api):
    """PRD §3.7: "A successful booking transitions the case from DOCS_PENDING
    to APPOINTMENT_BOOKED."
    """
    state = setup_paid_purchase_order(ask_price_cents=2_000_000)
    transfer = state["transfer"]
    buyer = state["buyer"]
    submit_all_transfer_documents(buyer, transfer["id"])
    soon = server_now_plus(timedelta(days=5))
    res = api.book_appointment(
        transfer["id"],
        book_appointment_payload(appointment_at=soon),
        make_buyer_headers(buyer["id"]),
    )
    booked = validate_success(res, 200)
    assert booked["status"] == "APPOINTMENT_BOOKED"


# ──────────────────────────────────────────────────────────
# §3.7 Successful transfer cascade
# ──────────────────────────────────────────────────────────


def test_transfer_succeeded_event_completes_order_and_archives_vehicle(api, admin_headers):
    """PRD §3.7: "A transfer_succeeded event advances the case from
    IN_PROGRESS to SUCCEEDED, advances the order from AWAITING_TRANSFER to
    COMPLETED, advances the vehicle from SOLD to ARCHIVED, and rewrites
    Vehicle.ownership_seller_id to the buyer's principal id."
    """
    state = setup_completed_purchase_order(ask_price_cents=2_000_000)
    transfer = state["transfer"]
    po = state["purchase_order"]
    vehicle_after = validate_success(api.get_vehicle(state["vehicle"]["id"], admin_headers), 200)
    assert transfer["status"] == "SUCCEEDED"
    assert po["status"] == "COMPLETED"
    assert vehicle_after["vehicle_status"] == "ARCHIVED"
    # PRD §3.7: ownership transferred to the buyer's principal id.
    assert vehicle_after["ownership_seller_id"] == state["buyer"]["id"]


# ──────────────────────────────────────────────────────────
# §3.7 Transfer failed → rollback full cascade (depth-4)
# ──────────────────────────────────────────────────────────


def test_rollback_only_admissible_on_failed(api, admin_headers):
    """PRD §3.7: "Rollback is admissible only on FAILED cases; attempting it
    on any other status is rejected with ERR_INVALID_STATE."

    Tested by attempting rollback on a DOCS_PENDING transfer (newly created,
    untouched).
    """
    state = setup_paid_purchase_order(ask_price_cents=2_000_000)
    transfer = state["transfer"]
    res = api.rollback_transfer(transfer["id"], admin_headers)
    validate_error(res, "ERR_INVALID_STATE")


def test_rollback_failed_transfer_cascades_full_compensation(api, admin_headers):
    """PRD §3.7: "A platform admin then explicitly invokes rollback on a
    failed case, advancing the case from FAILED to ROLLED_BACK with
    rolled_back_at set to the rollback instant; this triggers the full
    compensation cascade described in §2.6 — the order is moved from
    AWAITING_TRANSFER to REFUNDED, the listing is restored from SOLD to
    ACTIVE, the vehicle from SOLD to LISTED, the warranty from ACTIVE to
    VOIDED, any disbursed loan from DISBURSED to CANCELLED, and
    Vehicle.ownership_seller_id reverts to the original seller's id."
    """
    state = setup_transfer_in_failed_state(ask_price_cents=2_000_000)
    transfer = state["transfer"]
    assert transfer["status"] == "FAILED"
    rolled_back = validate_success(api.rollback_transfer(transfer["id"], admin_headers), 200)
    assert rolled_back["status"] == "ROLLED_BACK"
    assert rolled_back.get("rolled_back_at") is not None

    po_after = validate_success(
        api.get_purchase_order(state["purchase_order"]["id"], admin_headers), 200
    )
    assert po_after["status"] == "REFUNDED"

    listing_after = validate_success(api.get_listing(state["listing"]["id"], admin_headers), 200)
    assert listing_after["status"] == "ACTIVE"

    vehicle_after = validate_success(api.get_vehicle(state["vehicle"]["id"], admin_headers), 200)
    assert vehicle_after["vehicle_status"] == "LISTED"
    # PRD §3.7: ownership reverts to the original seller's id.
    assert vehicle_after["ownership_seller_id"] == state["seller"]["id"]

    # Warranty must be VOIDED.
    if state.get("warranty"):
        warranty_after = validate_success(
            api.get_warranty(state["warranty"]["id"], admin_headers), 200
        )
        assert warranty_after["status"] == "VOIDED"


def test_failed_transfer_writes_failure_reason_from_event_payload(api, admin_headers):
    """PRD §3.7: "A transfer_failed event advances the case from IN_PROGRESS
    to FAILED and writes the event payload's reason to failure_reason."
    """
    state = setup_transfer_in_failed_state(ask_price_cents=2_000_000)
    transfer = state["transfer"]
    assert transfer["failure_reason"] == "Title mismatch"
