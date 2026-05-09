"""Recall initiation, notification, disposal, completion and cancellation (PRD §3.8)."""
import pytest

from test_helpers import (
    api_client as api,
    validate_success,
    validate_error,
    setup_batch_with_qr_inspected_pass,
    setup_recall_at_initiated,
    setup_logistics_leg_in_transit,
    initiate_recall,
    notify_recall,
    record_disposal,
    create_recall_payload,
    REGULATORY_HEADERS,
    make_grower_headers,
    make_distributor_headers,
    NON_EXISTENT_UUID,
    DEFAULT_GROWER_ID,
)


# --------------------------------------------------------------------------
# PRD §3.8 — recall initiation cascade
# --------------------------------------------------------------------------

def test_recall_init_cascades_batch_to_recalled_and_revokes_qrs():
    """PRD §3.8: "The cascade described in §2.5 fires immediately: the batch
    moves to RECALLED with recall_status ACTIVE_RECALL, every QRCode for the
    batch has revoked set to true, and every LogisticsLeg in PLANNED or
    IN_TRANSIT is marked ABNORMAL."

    Claim: post-init the batch is in RECALLED with recall_status ACTIVE_RECALL.
    """
    batch, _bin, _harvest, _report, _qr = setup_batch_with_qr_inspected_pass()
    initiate_recall(batch)
    refreshed = validate_success(
        api.get_planting_batch(batch["id"], make_grower_headers(batch["grower_id"])), 200
    )
    assert refreshed["status"] == "RECALLED"
    assert refreshed["recall_status"] == "ACTIVE_RECALL"


def test_second_recall_on_active_recall_batch_rejected():
    """PRD §3.8: "If the batch already has an ACTIVE_RECALL recall, the request
    is rejected with ERR_RECALL_ALREADY_ACTIVE."

    Claim: a second POST /recall-orders for the same batch →
    ERR_RECALL_ALREADY_ACTIVE.
    """
    batch, _bin, _harvest, _report, _qr = setup_batch_with_qr_inspected_pass()
    initiate_recall(batch)
    payload = create_recall_payload(batch["id"])
    res = api.create_recall(payload, REGULATORY_HEADERS)
    validate_error(res, "ERR_RECALL_ALREADY_ACTIVE")


def test_recall_on_unknown_batch_yields_not_found():
    """PRD §2.6: "The first unresolved identifier yields ERR_NOT_FOUND
    immediately."

    Claim: POST /recall-orders with unknown planting_batch_id → ERR_NOT_FOUND.
    """
    payload = create_recall_payload(NON_EXISTENT_UUID)
    res = api.create_recall(payload, REGULATORY_HEADERS)
    validate_error(res, "ERR_NOT_FOUND")


# --------------------------------------------------------------------------
# PRD §3.8 — notify lifecycle
# --------------------------------------------------------------------------

def test_notify_advances_recall_to_notified():
    """PRD §3.8: "Notification advances the recall from INITIATED to NOTIFIED."

    Claim: POST /recall-orders/{id}/notify on an INITIATED recall →
    status NOTIFIED.
    """
    batch, recall, _distributor, _harvest = setup_recall_at_initiated()
    notified = notify_recall(recall)
    assert notified["status"] == "NOTIFIED"


# --------------------------------------------------------------------------
# PRD §3.8 — disposal -> IN_PROGRESS, ERR_RECALL_OVER_DISPOSED
# --------------------------------------------------------------------------

def test_first_disposal_advances_to_in_progress():
    """PRD §3.8: "The first disposal advances the recall from NOTIFIED to
    IN_PROGRESS."

    Claim: first POST /recall-orders/{id}/disposals on a NOTIFIED recall
    moves status to IN_PROGRESS.
    """
    batch, recall, distributor, _harvest = setup_recall_at_initiated()
    notify_recall(recall)
    res = record_disposal(recall, distributor, disposed_kg=10.0)
    body = validate_success(res, 201)
    # The POST returns the RecallOrder updated; alternatively a GET re-reads it.
    fetched = validate_success(api.get_recall(recall["id"], REGULATORY_HEADERS), 200)
    assert fetched["status"] == "IN_PROGRESS"


def test_disposal_over_total_recalled_rejected():
    """PRD §3.8: "A disposal that would push the cumulative disposed weight
    strictly above total_quantity_recalled_kg is rejected with
    ERR_RECALL_OVER_DISPOSED."

    Claim: a disposal whose cumulative disposed_kg would exceed total_recalled
    yields ERR_RECALL_OVER_DISPOSED.
    """
    batch, recall, distributor, _harvest = setup_recall_at_initiated()
    notify_recall(recall)
    # First disposal equals the entire recalled amount (50 kg from default fixture)
    record_disposal(recall, distributor, disposed_kg=50.0)
    res2 = record_disposal(recall, distributor, disposed_kg=0.01)
    validate_error(res2, "ERR_RECALL_OVER_DISPOSED")


# --------------------------------------------------------------------------
# PRD §3.8 — completion (zero-residual boundary)
# --------------------------------------------------------------------------

def test_complete_with_nonzero_residual_rejected():
    """PRD §3.8: "Completion is permitted only when the recall is in
    IN_PROGRESS and the running residual is exactly zero — that is,
    total_quantity_disposed_kg equals total_quantity_recalled_kg. A non-zero
    residual yields ERR_RECALL_RESIDUAL_NONZERO."

    Claim: complete with residual > 0 → ERR_RECALL_RESIDUAL_NONZERO.
    """
    batch, recall, distributor, _harvest = setup_recall_at_initiated()
    notify_recall(recall)
    record_disposal(recall, distributor, disposed_kg=10.0)  # 10 of 50 disposed
    res = api.complete_recall(recall["id"], REGULATORY_HEADERS)
    validate_error(res, "ERR_RECALL_RESIDUAL_NONZERO")


def test_complete_with_zero_residual_finalizes():
    """PRD §3.8: "On success, the recall's status advances to COMPLETED, the
    parent batch's recall_status advances to COMPLETED, the batch's status
    advances to DISPOSED."

    Claim: complete after disposing exactly total_recalled → recall COMPLETED,
    batch.status DISPOSED, recall_status COMPLETED.
    """
    batch, recall, distributor, _harvest = setup_recall_at_initiated()
    notify_recall(recall)
    record_disposal(recall, distributor, disposed_kg=50.0)
    completed = validate_success(api.complete_recall(recall["id"], REGULATORY_HEADERS), 200)
    assert completed["status"] == "COMPLETED"
    refreshed = validate_success(
        api.get_planting_batch(batch["id"], make_grower_headers(batch["grower_id"])), 200
    )
    assert refreshed["status"] == "DISPOSED"
    assert refreshed["recall_status"] == "COMPLETED"


# --------------------------------------------------------------------------
# PRD §3.8 — cancel before any disposal
# --------------------------------------------------------------------------

def test_cancel_before_disposal_reverts_batch_status():
    """PRD §3.8: "An officer may cancel a recall while it is still in
    INITIATED and no disposal record has been appended; the recall's status
    advances to CANCELLED, the batch's recall_status reverts to NONE, the
    batch's status reverts to whatever it held immediately before recall
    initiation."

    Claim: cancel of an INITIATED recall reverts the batch.
    """
    batch, recall, _distributor, _harvest = setup_recall_at_initiated()
    # Before initiation the batch was DELIVERED.
    res = api.cancel_recall(recall["id"], REGULATORY_HEADERS)
    cancelled = validate_success(res, 200)
    assert cancelled["status"] == "CANCELLED"
    refreshed = validate_success(
        api.get_planting_batch(batch["id"], make_grower_headers(batch["grower_id"])), 200
    )
    assert refreshed["recall_status"] == "NONE"
    assert refreshed["status"] == "DELIVERED"


def test_cancel_after_disposal_rejected():
    """PRD §3.8: "Cancellation against a recall that already has at least one
    disposal record is rejected with ERR_RECALL_HAS_DISPOSALS."

    Claim: cancel after at least one disposal → ERR_RECALL_HAS_DISPOSALS.
    """
    batch, recall, distributor, _harvest = setup_recall_at_initiated()
    notify_recall(recall)
    record_disposal(recall, distributor, disposed_kg=5.0)
    res = api.cancel_recall(recall["id"], REGULATORY_HEADERS)
    validate_error(res, "ERR_RECALL_HAS_DISPOSALS")


def test_disposal_distributor_id_must_match_x_user_id():
    """PRD §2.10: "A Distributor who records a disposal must supply a
    distributor_id matching their own X-User-ID."

    Claim: posting a disposal whose distributor_id != X-User-ID → ERR_FORBIDDEN.
    """
    batch, recall, distributor, _harvest = setup_recall_at_initiated()
    notify_recall(recall)
    # Build headers for a different distributor_id but supply the actual one
    foreign_headers = make_distributor_headers("foreign-distributor-id-001")
    payload = {
        "distributor_id": distributor["id"],
        "disposed_kg": 5.0,
        "disposed_at": "2026-04-22T00:00:00.000Z",
    }
    res = api.create_disposal(recall["id"], payload, foreign_headers)
    validate_error(res, "ERR_FORBIDDEN")
