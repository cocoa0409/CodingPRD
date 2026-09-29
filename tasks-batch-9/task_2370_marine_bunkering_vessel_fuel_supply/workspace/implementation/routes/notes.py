"""MARPOL bunker delivery notes and retained samples (PRD 3.7)."""

from datetime import timedelta

from flask import Blueprint, g

import db
import serializers
from db import store, touch
from errors import ApiError
from lookup import body_ref, path_ref
from middleware import roles
from response import success, success_list
from services import calc
from validation import apply_page, body, pagination, q_enum, q_str, v_decimal, v_string

bp = Blueprint("notes", __name__)

NOTE_READERS = ("OpsCoordinator", "Surveyor", "CustomerRep", "LabTechnician")
NOTE_STATUSES = ("ISSUED", "SUPERSEDED")


@bp.post("/bunker-delivery-notes")
@roles("OpsCoordinator")
def create_note():
    data = body()
    order = body_ref(
        data, "delivery_order_id", store.delivery_orders, "ERR_DELIVERY_ORDER_NOT_FOUND"
    )
    v_string(data, "delivery_order_id", min_len=1)
    bdn_number = v_string(data, "bdn_number", min_len=1)
    declared_sulfur_pct = v_decimal(data, "declared_sulfur_pct", 3, positive=True)
    sample_seal_number = v_string(data, "sample_seal_number", min_len=1)
    if order is None:
        raise ApiError("ERR_DELIVERY_ORDER_NOT_FOUND")

    nomination = calc.order_nomination(order)
    if order["logistics_status"] != "DELIVERED":
        raise ApiError("ERR_INVALID_ORDER_STATE")
    if order["measurement_status"] != "AGREED" or order["agreed_quantity_mt"] is None:
        raise ApiError("ERR_MEASUREMENT_NOT_AGREED")

    reviewer = nomination["compliance_reviewer_user_id"] if nomination else None
    if reviewer is not None and reviewer == g.user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    for existing in store.bunker_delivery_notes.values():
        if existing["bdn_number"] == bdn_number:
            raise ApiError("ERR_DUPLICATE_BDN_NUMBER")
    for existing in store.bunker_delivery_notes.values():
        if existing["sample_seal_number"] == sample_seal_number:
            raise ApiError("ERR_DUPLICATE_SAMPLE_SEAL")

    note = db.new_record()
    retention_until = note["created_at"] + timedelta(days=calc.SAMPLE_RETENTION_DAYS)
    note.update(
        {
            "delivery_order_id": order["id"],
            "bdn_number": bdn_number,
            "declared_sulfur_pct": declared_sulfur_pct,
            "delivered_quantity_mt": order["agreed_quantity_mt"],
            "sample_seal_number": sample_seal_number,
            "sample_retention_until": retention_until,
            "sample_released_at": None,
            "status": "ISSUED",
            "issued_by_user_id": g.user_id,
        }
    )

    # A corrected note supersedes the previous one unless a claim references it.
    for prior in db.sorted_rows(store.bunker_delivery_notes):
        if prior["delivery_order_id"] != order["id"]:
            continue
        if prior["status"] != "ISSUED":
            continue
        claimed = any(
            claim["bdn_id"] == prior["id"] for claim in store.quality_claims.values()
        )
        if claimed:
            continue
        prior["status"] = "SUPERSEDED"
        touch(prior)

    store.bunker_delivery_notes[note["id"]] = note
    return success(serializers.bunker_delivery_note(note), 201)


@bp.get("/bunker-delivery-notes/<rec_id>")
@roles(*NOTE_READERS)
def get_note(rec_id):
    note = path_ref(store.bunker_delivery_notes, rec_id, "ERR_BDN_NOT_FOUND")
    return success(serializers.bunker_delivery_note(note))


@bp.get("/bunker-delivery-notes")
@roles(*NOTE_READERS)
def list_notes():
    delivery_order_id = q_str("delivery_order_id")
    status = q_enum("status", NOTE_STATUSES)
    limit, offset = pagination()

    def match(row):
        if delivery_order_id is not None and row["delivery_order_id"] != delivery_order_id:
            return False
        if status is not None and row["status"] != status:
            return False
        return True

    rows = db.sorted_rows(store.bunker_delivery_notes, match)
    page = apply_page(rows, limit, offset)
    return success_list(
        [serializers.bunker_delivery_note(r) for r in page], limit, offset, len(rows)
    )


@bp.post("/bunker-delivery-notes/<rec_id>/release-sample")
@roles("OpsCoordinator")
def release_sample(rec_id):
    note = path_ref(store.bunker_delivery_notes, rec_id, "ERR_BDN_NOT_FOUND")
    if db.now() > note["sample_retention_until"]:
        raise ApiError("ERR_SAMPLE_RETENTION_EXPIRED")
    note["sample_released_at"] = db.now()
    touch(note)
    return success(serializers.bunker_delivery_note(note))
