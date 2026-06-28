"""Imaging orders and modality scheduling (PRD §3.9)."""

from datetime import timedelta

from flask import Blueprint, request

import db
import errors
import middleware as mw
import response as resp
import validate as v

bp = Blueprint("imaging_orders", __name__)

ALL_ROLES = {"PracticeAdmin", "Podiatrist", "BillingSpecialist", "FrontDesk", "PayerAgent"}


@bp.route("/podiatry/imaging-orders", methods=["POST"])
def create_imaging_order():
    _, role = mw.authenticate()
    mw.require_role(role, {"Podiatrist"})
    body = mw.get_body()
    with db.lock():
        encounter_id = v.as_str(body, "encounter_id", required=True)
        modality_id = v.as_str(body, "modality_id", required=True)
        encounter = db.encounters.get(encounter_id)
        if encounter is None:
            raise errors.fk_not_found("encounter_id references a non-existent encounter.")
        modality = db.modalities.get(modality_id)
        if modality is None:
            raise errors.fk_not_found("modality_id references a non-existent modality.")

        start = v.as_datetime(body, "study_start", required=True)
        end = v.as_datetime(body, "study_end", required=True)
        if end <= start:
            raise errors.invalid_request("study_end must be after study_start.")
        expected_version = v.as_int(body, "expected_modality_version", required=True)

        # OCC check (priority 6) — before booking logic (PRD §2.10).
        if expected_version != modality["version"]:
            raise errors.ApiError(errors.ERR_MODALITY_VERSION_STALE, 412,
                                  "expected_modality_version is stale.")

        # Buffered overlap (priority 13, PRD §3.9): each study's interval is
        # expanded by cleanup_buffer_minutes after its end; buffered intervals on
        # the same modality must not overlap (non-CANCELLED studies only).
        buffer = timedelta(minutes=modality["cleanup_buffer_minutes"])
        new_start = start
        new_end = end + buffer
        for io in db.imaging_orders.values():
            if io["modality_id"] != modality_id:
                continue
            if io["status"] == "CANCELLED":
                continue
            other_start = v.parse_datetime(io["study_start"])
            other_end = v.parse_datetime(io["study_end"]) + buffer
            if new_start < other_end and other_start < new_end:
                raise errors.ApiError(errors.ERR_MODALITY_DOUBLE_BOOKED, 409,
                                      "New study overlaps a buffered study on this "
                                      "modality.")

        entity = {
            "encounter_id": encounter_id,
            "patient_id": encounter["patient_id"],
            "modality_id": modality_id,
            "study_start": body["study_start"],
            "study_end": body["study_end"],
            "status": "SCHEDULED",
        }
        db.stamp_common(entity)
        db.imaging_orders[entity["id"]] = entity
        # Successful booking bumps the modality version (PRD §3.9).
        db.touch(modality)
        return resp.success(entity, 201)


@bp.route("/podiatry/imaging-orders", methods=["GET"])
def list_imaging_orders():
    _, role = mw.authenticate()
    mw.require_role(role, ALL_ROLES)
    encounter_id = request.args.get("encounter_id")
    modality_id = request.args.get("modality_id")
    items = []
    for io in db.imaging_orders.values():
        if encounter_id is not None and io["encounter_id"] != encounter_id:
            continue
        if modality_id is not None and io["modality_id"] != modality_id:
            continue
        items.append(io)
    page, meta = mw.paginate(items)
    return resp.success(page, 200, pagination=meta)


@bp.route("/podiatry/imaging-orders/<imaging_order_id>", methods=["GET"])
def get_imaging_order(imaging_order_id):
    _, role = mw.authenticate()
    mw.require_role(role, ALL_ROLES)
    entity = db.imaging_orders.get(imaging_order_id)
    if entity is None:
        raise errors.not_found("Imaging order not found.")
    return resp.success(entity, 200)


def _load(imaging_order_id):
    entity = db.imaging_orders.get(imaging_order_id)
    if entity is None:
        raise errors.not_found("Imaging order not found.")
    return entity


@bp.route("/podiatry/imaging-orders/<imaging_order_id>/complete", methods=["POST"])
def complete_imaging_order(imaging_order_id):
    _, role = mw.authenticate()
    mw.require_role(role, {"Podiatrist"})
    with db.lock():
        io = _load(imaging_order_id)
        if io["status"] != "SCHEDULED":
            raise errors.ApiError(errors.ERR_IMAGING_BAD_STATE, 409,
                                  "complete requires status SCHEDULED.")
        io["status"] = "COMPLETED"
        db.touch(io)
        return resp.success(io, 200)


@bp.route("/podiatry/imaging-orders/<imaging_order_id>/cancel", methods=["POST"])
def cancel_imaging_order(imaging_order_id):
    _, role = mw.authenticate()
    mw.require_role(role, {"FrontDesk"})
    with db.lock():
        io = _load(imaging_order_id)
        if io["status"] != "SCHEDULED":
            raise errors.ApiError(errors.ERR_IMAGING_BAD_STATE, 409,
                                  "cancel requires status SCHEDULED.")
        io["status"] = "CANCELLED"
        db.touch(io)
        return resp.success(io, 200)
