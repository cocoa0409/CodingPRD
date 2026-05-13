"""Transfer endpoints (PRD §3.8)."""
from __future__ import annotations

from flask import Blueprint

from db import (
    LOCK,
    bikes,
    new_id,
    record_bike_in_region_history,
    regions,
    transfer_orders,
)
from errors import (
    ERR_BIKE_NOT_AVAILABLE_FOR_TRANSFER,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_QUOTA_EXCEEDED,
    ERR_REFERENCE_NOT_FOUND,
    ERR_TRANSFER_KIND_MISMATCH,
    ERR_TRANSFER_NOT_IN_TRANSIT,
    ERR_TRANSFER_NOT_PLANNED,
    ERR_VALIDATION,
    raise_err,
)
from middleware import require_role
from response import success_object
from services.audit import write_audit
from services.regions import recompute_region_counts
from services.validators import (
    bump_version,
    get_json_body,
)
from time_utils import now_iso


bp = Blueprint("transfers", __name__)


def serialize_transfer(t: dict) -> dict:
    return dict(t)


@bp.post("/transfers")
def create_transfer():
    require_role("Operator", "Admin")
    body = get_json_body()
    if "from_region_id" not in body or "to_region_id" not in body:
        raise_err(ERR_VALIDATION, "from_region_id and to_region_id are required")
    if "bike_ids" not in body:
        raise_err(ERR_VALIDATION, "bike_ids is required")
    bike_ids = body["bike_ids"]
    if not isinstance(bike_ids, list) or not bike_ids:
        raise_err(ERR_VALIDATION, "bike_ids must be a non-empty array")
    for bid in bike_ids:
        if not isinstance(bid, str) or not bid:
            raise_err(ERR_VALIDATION, "bike_ids must be strings")

    with LOCK:
        from_region = regions.get(body["from_region_id"])
        if from_region is None:
            raise_err(ERR_REFERENCE_NOT_FOUND, "from_region_id not found")
        to_region = regions.get(body["to_region_id"])
        if to_region is None:
            raise_err(ERR_REFERENCE_NOT_FOUND, "to_region_id not found")
        if from_region["id"] == to_region["id"]:
            raise_err(ERR_VALIDATION, "from_region_id and to_region_id must differ")
        for bid in bike_ids:
            if bid not in bikes:
                raise_err(ERR_REFERENCE_NOT_FOUND, "bike_id not found")

        # Determine kind from current postures at plan time.
        if to_region["density_posture"] == "LOW":
            kind = "REPLENISH"
        elif from_region["density_posture"] == "HIGH":
            kind = "CLEARANCE"
        else:
            raise_err(
                ERR_INVALID_STATE,
                "Neither destination is LOW nor source is HIGH; transfer cannot be planned",
            )

        tid = new_id()
        ts = now_iso()
        transfer = {
            "id": tid,
            "from_region_id": from_region["id"],
            "to_region_id": to_region["id"],
            "bike_ids": list(bike_ids),
            "status": "PLANNED",
            "kind": kind,
            "dispatched_minute": None,
            "completed_minute": None,
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
        }
        transfer_orders[tid] = transfer
    return success_object(serialize_transfer(transfer), status=201)


@bp.get("/transfers/<transfer_id>")
def get_transfer(transfer_id):
    require_role("Operator", "Admin")
    t = transfer_orders.get(transfer_id)
    if t is None:
        raise_err(ERR_NOT_FOUND, "TransferOrder not found")
    return success_object(serialize_transfer(t))


@bp.post("/transfers/<transfer_id>/dispatch")
def dispatch_transfer(transfer_id):
    require_role("Operator")
    t = transfer_orders.get(transfer_id)
    if t is None:
        raise_err(ERR_NOT_FOUND, "TransferOrder not found")
    with LOCK:
        t = transfer_orders[transfer_id]
        if t["status"] != "PLANNED":
            raise_err(ERR_TRANSFER_NOT_PLANNED, "TransferOrder is not PLANNED")
        from_region = regions[t["from_region_id"]]
        to_region = regions[t["to_region_id"]]

        # Check every bike's eligibility.
        for bid in t["bike_ids"]:
            bike = bikes.get(bid)
            if bike is None:
                raise_err(ERR_BIKE_NOT_AVAILABLE_FOR_TRANSFER, f"Bike {bid} not eligible")
            if bike.get("region_id") != t["from_region_id"]:
                raise_err(ERR_BIKE_NOT_AVAILABLE_FOR_TRANSFER, f"Bike {bid} not in source region")
            if bike.get("status") != "AVAILABLE":
                raise_err(ERR_BIKE_NOT_AVAILABLE_FOR_TRANSFER, f"Bike {bid} not AVAILABLE")
            if bike.get("shelf_state") != "ON_SHELF":
                raise_err(ERR_BIKE_NOT_AVAILABLE_FOR_TRANSFER, f"Bike {bid} not ON_SHELF")

        # Kind ↔ current-posture match at dispatch.
        if t["kind"] == "REPLENISH" and to_region["density_posture"] != "LOW":
            raise_err(ERR_TRANSFER_KIND_MISMATCH, "REPLENISH requires destination LOW")
        if t["kind"] == "CLEARANCE" and from_region["density_posture"] != "HIGH":
            raise_err(ERR_TRANSFER_KIND_MISMATCH, "CLEARANCE requires source HIGH")

        # Quota guard at destination (will be checked again at complete, but pre-checked).
        if to_region["deployed_count"] + len(t["bike_ids"]) > to_region["deployment_quota"]:
            raise_err(ERR_QUOTA_EXCEEDED, "Destination deployment_quota would be exceeded")

        # Side effects: detach bikes from source.
        for bid in t["bike_ids"]:
            bike = bikes[bid]
            bike["shelf_state"] = "OFF_SHELF"
            bike["region_id"] = None
            bump_version(bike)
        recompute_region_counts(t["from_region_id"])
        t["status"] = "IN_TRANSIT"
        t["dispatched_minute"] = int(from_region.get("clock_minutes", 0))
        bump_version(t)
        write_audit(
            event_kind="OPS_ACTION",
            action="TRANSFER_DISPATCH",
            subject_type="TransferOrder",
            subject_id=transfer_id,
            before={"status": "PLANNED"},
            after={"status": "IN_TRANSIT"},
            region_id=t["from_region_id"],
        )
    return success_object(serialize_transfer(t))


@bp.post("/transfers/<transfer_id>/complete")
def complete_transfer(transfer_id):
    require_role("Operator")
    t = transfer_orders.get(transfer_id)
    if t is None:
        raise_err(ERR_NOT_FOUND, "TransferOrder not found")
    with LOCK:
        t = transfer_orders[transfer_id]
        if t["status"] != "IN_TRANSIT":
            raise_err(ERR_TRANSFER_NOT_IN_TRANSIT, "TransferOrder is not IN_TRANSIT")
        to_region = regions[t["to_region_id"]]
        prior_posture = to_region["density_posture"]

        # Final quota guard (defensive).
        if to_region["deployed_count"] + len(t["bike_ids"]) > to_region["deployment_quota"]:
            raise_err(ERR_QUOTA_EXCEEDED, "Destination deployment_quota would be exceeded")

        # Drop bikes at destination.
        for bid in t["bike_ids"]:
            bike = bikes[bid]
            bike["region_id"] = t["to_region_id"]
            bike["shelf_state"] = "ON_SHELF"
            bike["status"] = "AVAILABLE"
            record_bike_in_region_history(t["to_region_id"], bid)
            bump_version(bike)

        recompute_region_counts(t["to_region_id"])
        new_posture = to_region["density_posture"]

        t["status"] = "COMPLETED"
        t["completed_minute"] = int(to_region.get("clock_minutes", 0))
        bump_version(t)

        # Cascade hop 3: if destination flipped LOW→NORMAL or LOW→HIGH,
        # cancel any other PLANNED REPLENISH transfers targeting this region.
        if prior_posture == "LOW" and new_posture != "LOW":
            for other in list(transfer_orders.values()):
                if other["id"] == transfer_id:
                    continue
                if (
                    other["to_region_id"] == t["to_region_id"]
                    and other["status"] == "PLANNED"
                    and other["kind"] == "REPLENISH"
                ):
                    other["status"] = "CANCELLED"
                    bump_version(other)

        write_audit(
            event_kind="OPS_ACTION",
            action="TRANSFER_COMPLETE",
            subject_type="TransferOrder",
            subject_id=transfer_id,
            before={"status": "IN_TRANSIT"},
            after={"status": "COMPLETED", "to_density_posture": new_posture},
            region_id=t["to_region_id"],
        )
    return success_object(serialize_transfer(t))


@bp.post("/transfers/<transfer_id>/cancel")
def cancel_transfer(transfer_id):
    require_role("Operator", "Admin")
    t = transfer_orders.get(transfer_id)
    if t is None:
        raise_err(ERR_NOT_FOUND, "TransferOrder not found")
    with LOCK:
        t = transfer_orders[transfer_id]
        if t["status"] == "PLANNED":
            t["status"] = "CANCELLED"
            bump_version(t)
        elif t["status"] == "IN_TRANSIT":
            for bid in t["bike_ids"]:
                bike = bikes[bid]
                bike["region_id"] = t["from_region_id"]
                bike["shelf_state"] = "ON_SHELF"
                bike["status"] = "AVAILABLE"
                record_bike_in_region_history(t["from_region_id"], bid)
                bump_version(bike)
            recompute_region_counts(t["from_region_id"])
            t["status"] = "CANCELLED"
            bump_version(t)
        else:
            raise_err(
                ERR_TRANSFER_NOT_PLANNED if t["status"] == "COMPLETED" else ERR_TRANSFER_NOT_IN_TRANSIT,
                f"TransferOrder cannot be cancelled from {t['status']}",
            )
    return success_object(serialize_transfer(t))
