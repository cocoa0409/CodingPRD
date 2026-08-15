"""Cross-border transfers with adequacy, contract, and 30-day buffer gates."""
from datetime import timedelta

from flask import Blueprint, request

import db
from errors import ApiError
from middleware import STAFF_ROLES, get_body, require_roles
from response import list_response, success
from serialize import ser_transfer
from services.core import base_entity, created_asc, touch
from services.risk import MECHANISMS, REGIONS
from utils import parse_ts

bp = Blueprint("transfers", __name__)

BUFFER_DAYS = 30


def _buffer_conflict(transfer):
    for other in db.transfers.values():
        if other["id"] == transfer["id"]:
            continue
        if (other["source_system_id"] != transfer["source_system_id"]
                or other["vendor_id"] != transfer["vendor_id"]):
            continue
        if other["status"] not in ("APPROVED", "SUSPENDED"):
            continue
        separated = (
            transfer["effective_from"] >= other["effective_to"] + timedelta(days=BUFFER_DAYS)
            or transfer["effective_to"] <= other["effective_from"] - timedelta(days=BUFFER_DAYS)
        )
        if not separated:
            return True
    return False


@bp.post("/privacy/transfers")
def create_transfer():
    require_roles("PrivacyAdmin")
    body = get_body()
    source_system_id = body.get("source_system_id")
    vendor_id = body.get("vendor_id")
    vendor_contract_id = body.get("vendor_contract_id")
    activity_id = body.get("activity_id")
    for value, store, label in (
            (source_system_id, db.data_systems, "source_system_id"),
            (vendor_id, db.vendors, "vendor_id"),
            (vendor_contract_id, db.contracts, "vendor_contract_id"),
            (activity_id, db.activities, "activity_id")):
        if isinstance(value, str) and value not in store:
            raise ApiError("ERR_NOT_FOUND", "%s not found" % label)
    source = db.data_systems.get(source_system_id)
    if source is not None and source["status"] != "ACTIVE":
        raise ApiError("ERR_SYSTEM_DECOMMISSIONED",
                       "source system is not ACTIVE")
    vendor = db.vendors.get(vendor_id)
    if vendor is not None and vendor["status"] != "APPROVED":
        raise ApiError("ERR_VENDOR_NOT_APPROVED",
                       "vendor is not APPROVED")
    effective_from = None
    effective_to = None
    try:
        if isinstance(body.get("effective_from"), str):
            effective_from = parse_ts(body.get("effective_from"))
        if isinstance(body.get("effective_to"), str):
            effective_to = parse_ts(body.get("effective_to"))
    except (ValueError, TypeError):
        pass
    if (effective_from is not None and effective_to is not None
            and effective_to <= effective_from):
        raise ApiError("ERR_INVALID_WINDOW",
                       "effective_to must be strictly after effective_from")
    dest_region = body.get("dest_region")
    mechanism = body.get("mechanism")
    if not isinstance(source_system_id, str):
        raise ApiError("ERR_INVALID_REQUEST", "source_system_id is required")
    if not isinstance(vendor_id, str):
        raise ApiError("ERR_INVALID_REQUEST", "vendor_id is required")
    if not isinstance(vendor_contract_id, str):
        raise ApiError("ERR_INVALID_REQUEST", "vendor_contract_id is required")
    if not isinstance(activity_id, str):
        raise ApiError("ERR_INVALID_REQUEST", "activity_id is required")
    if dest_region not in REGIONS:
        raise ApiError("ERR_INVALID_REQUEST", "invalid dest_region")
    if mechanism not in MECHANISMS:
        raise ApiError("ERR_INVALID_REQUEST", "invalid mechanism")
    if effective_from is None or effective_to is None:
        raise ApiError("ERR_INVALID_REQUEST",
                       "effective_from and effective_to must be ISO 8601 timestamps")
    transfer = base_entity()
    transfer.update({
        "source_system_id": source_system_id,
        "vendor_id": vendor_id,
        "vendor_contract_id": vendor_contract_id,
        "activity_id": activity_id,
        "dest_region": dest_region,
        "mechanism": mechanism,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "suspension_reason": None,
        "status": "PROPOSED",
    })
    db.transfers[transfer["id"]] = transfer
    return success(ser_transfer(transfer), 201)


@bp.get("/privacy/transfers")
def list_transfers():
    require_roles(*STAFF_ROLES)
    items = created_asc(list(db.transfers.values()))
    vendor_id = request.args.get("vendor_id")
    source_system_id = request.args.get("source_system_id")
    activity_id = request.args.get("activity_id")
    vendor_contract_id = request.args.get("vendor_contract_id")
    if vendor_id is not None:
        items = [t for t in items if t["vendor_id"] == vendor_id]
    if source_system_id is not None:
        items = [t for t in items if t["source_system_id"] == source_system_id]
    if activity_id is not None:
        items = [t for t in items if t["activity_id"] == activity_id]
    if vendor_contract_id is not None:
        items = [t for t in items if t["vendor_contract_id"] == vendor_contract_id]
    return list_response(items, ser_transfer)


@bp.get("/privacy/transfers/<transfer_id>")
def get_transfer(transfer_id):
    require_roles(*STAFF_ROLES)
    transfer = db.transfers.get(transfer_id)
    if transfer is None:
        raise ApiError("ERR_NOT_FOUND", "transfer not found")
    return success(ser_transfer(transfer), 200)


@bp.post("/privacy/transfers/<transfer_id>/assess")
def assess_transfer(transfer_id):
    require_roles("LegalCounsel")
    transfer = db.transfers.get(transfer_id)
    if transfer is None:
        raise ApiError("ERR_NOT_FOUND", "transfer not found")
    if transfer["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "only a PROPOSED transfer can move to UNDER_ASSESSMENT")
    transfer["status"] = "UNDER_ASSESSMENT"
    touch(transfer)
    return success(ser_transfer(transfer), 200)


@bp.post("/privacy/transfers/<transfer_id>/approve")
def approve_transfer(transfer_id):
    require_roles("LegalCounsel")
    transfer = db.transfers.get(transfer_id)
    if transfer is None:
        raise ApiError("ERR_NOT_FOUND", "transfer not found")
    if transfer["status"] != "UNDER_ASSESSMENT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "only an UNDER_ASSESSMENT transfer can be approved")
    source = db.data_systems.get(transfer["source_system_id"])
    if (source is not None and source["hosting_region"] in ("EU", "UK")
            and transfer["dest_region"] == "US"
            and transfer["mechanism"] not in ("SCC_2021", "BCR")):
        raise ApiError("ERR_MECHANISM_NOT_ADEQUATE",
                       "EU/UK source to US requires SCC_2021 or BCR")
    contract = db.contracts.get(transfer["vendor_contract_id"])
    if contract is None or contract["status"] != "EXECUTED":
        raise ApiError("ERR_CONTRACT_NOT_EXECUTED",
                       "vendor contract is not EXECUTED")
    if _buffer_conflict(transfer):
        raise ApiError("ERR_TRANSFER_WINDOW_CONFLICT",
                       "window is within the 30-day buffer of an APPROVED/SUSPENDED transfer")
    transfer["status"] = "APPROVED"
    touch(transfer)
    return success(ser_transfer(transfer), 200)


@bp.post("/privacy/transfers/<transfer_id>/reject")
def reject_transfer(transfer_id):
    require_roles("LegalCounsel")
    transfer = db.transfers.get(transfer_id)
    if transfer is None:
        raise ApiError("ERR_NOT_FOUND", "transfer not found")
    if transfer["status"] != "UNDER_ASSESSMENT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "only an UNDER_ASSESSMENT transfer can be rejected")
    transfer["status"] = "REJECTED"
    touch(transfer)
    return success(ser_transfer(transfer), 200)
