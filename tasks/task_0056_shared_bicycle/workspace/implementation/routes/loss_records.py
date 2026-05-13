"""LossRecord endpoints (PRD §3.11)."""
from __future__ import annotations

from flask import Blueprint, request

from db import LOCK, bikes, loss_records, new_id, riders
from errors import (
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_REFERENCE_NOT_FOUND,
    ERR_VALIDATION,
    raise_err,
)
from middleware import require_role
from response import success_list, success_object
from services.audit import write_audit
from services.validators import (
    ensure_enum,
    ensure_positive_int,
    get_json_body,
    parse_pagination,
)
from time_utils import now_iso


bp = Blueprint("loss_records", __name__)

LOSS_CAUSES = {"THEFT", "DAMAGE", "ABANDONED"}
RESPONSIBILITIES = {"RIDER", "OPERATOR", "UNKNOWN"}


def _serialize(lr: dict) -> dict:
    return dict(lr)


@bp.post("/loss-records")
def create_loss_record():
    require_role("Admin")
    body = get_json_body()
    if "bike_id" not in body:
        raise_err(ERR_VALIDATION, "bike_id is required")
    bike_id = body["bike_id"]
    if "cause" not in body:
        raise_err(ERR_VALIDATION, "cause is required")
    cause = ensure_enum(body["cause"], "cause", LOSS_CAUSES)
    if "responsibility" not in body:
        raise_err(ERR_VALIDATION, "responsibility is required")
    responsibility = ensure_enum(body["responsibility"], "responsibility", RESPONSIBILITIES)
    if "financial_impact_cents" not in body:
        raise_err(ERR_VALIDATION, "financial_impact_cents is required")
    impact = ensure_positive_int(body["financial_impact_cents"], "financial_impact_cents")
    responsible_party_id = body.get("responsible_party_id")

    with LOCK:
        bike = bikes.get(bike_id)
        if bike is None:
            raise_err(ERR_REFERENCE_NOT_FOUND, "bike_id not found")
        if bike["shelf_state"] == "SCRAPPED":
            raise_err(ERR_INVALID_STATE, "Bike is SCRAPPED")
        if responsibility == "RIDER":
            if not isinstance(responsible_party_id, str) or responsible_party_id not in riders:
                raise_err(ERR_REFERENCE_NOT_FOUND, "responsible_party_id (rider) not found")
        elif responsibility == "OPERATOR":
            if not isinstance(responsible_party_id, str) or not responsible_party_id:
                raise_err(ERR_VALIDATION, "responsible_party_id required for OPERATOR responsibility")
        else:
            responsible_party_id = None

        lr_id = new_id()
        ts = now_iso()
        lr = {
            "id": lr_id,
            "bike_id": bike_id,
            "region_id": bike.get("region_id"),
            "cause": cause,
            "responsibility": responsibility,
            "responsible_party_id": responsible_party_id,
            "financial_impact_cents": impact,
            "scrapped": False,
            "created_at": ts,
        }
        loss_records[lr_id] = lr
        write_audit(
            event_kind="OPS_ACTION",
            action="LOSS_RECORD_CREATE",
            subject_type="LossRecord",
            subject_id=lr_id,
            before={},
            after={"bike_id": bike_id, "cause": cause, "responsibility": responsibility},
            region_id=bike.get("region_id"),
        )
    return success_object(_serialize(lr), status=201)


@bp.get("/loss-records")
def list_loss_records():
    require_role("Admin")
    region_filter = request.args.get("region_id")
    cause_filter = request.args.get("cause")
    if cause_filter is not None and cause_filter not in LOSS_CAUSES:
        raise_err(ERR_VALIDATION, "cause filter invalid")

    items = list(loss_records.values())
    if region_filter is not None:
        items = [lr for lr in items if lr.get("region_id") == region_filter]
    if cause_filter is not None:
        items = [lr for lr in items if lr.get("cause") == cause_filter]
    items.sort(key=lambda lr: lr["created_at"])

    limit, offset = parse_pagination()
    total = len(items)
    window = items[offset:offset + limit]
    return success_list([_serialize(lr) for lr in window], limit=limit, offset=offset, total_count=total)
