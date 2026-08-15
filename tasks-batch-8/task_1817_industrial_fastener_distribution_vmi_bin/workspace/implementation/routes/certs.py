"""LotCertificate endpoints."""

from flask import Blueprint, request

import errors
from db import store, new_id, now_iso
from middleware import (
    authenticate, require_roles, json_body, need, as_str, as_dt,
    pagination_params, paginate,
)
from response import success, success_list

bp = Blueprint("certs", __name__)

READ_ROLES = ["DistributorAdmin", "RouteDriver", "WarehouseOperator"]


def serialize(c):
    return {
        "id": c["id"],
        "part_id": c["part_id"],
        "lot_number": c["lot_number"],
        "cert_expires_at": c["cert_expires_at"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


@bp.post("/vmi/lot-certificates")
def create_cert():
    role = authenticate()
    body = json_body()
    part_id = as_str(need(body, "part_id"), "part_id")
    lot_number = as_str(need(body, "lot_number"), "lot_number")
    cert_expires_at = as_dt(need(body, "cert_expires_at"), "cert_expires_at")
    require_roles(role, ["DistributorAdmin"])
    with store.lock:
        if part_id not in store.parts:
            raise errors.not_found("part not found")
        if any(
            c["part_id"] == part_id and c["lot_number"] == lot_number
            for c in store.certs.values()
        ):
            raise errors.duplicate("(part_id, lot_number) pair already registered")
        ts = now_iso()
        cert = {
            "id": new_id(),
            "part_id": part_id,
            "lot_number": lot_number,
            "cert_expires_at": cert_expires_at,
            "status": "VALID",
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
            "_seq": store.next_seq(),
        }
        store.certs[cert["id"]] = cert
        return success(serialize(cert), 201)


@bp.get("/vmi/lot-certificates/<cid>")
def get_cert(cid):
    role = authenticate()
    require_roles(role, READ_ROLES)
    cert = store.certs.get(cid)
    if cert is None:
        raise errors.not_found("lot certificate not found")
    return success(serialize(cert), 200)


@bp.get("/vmi/lot-certificates")
def list_certs():
    role = authenticate()
    require_roles(role, READ_ROLES)
    limit, offset = pagination_params()
    part_id = request.args.get("part_id")
    status = request.args.get("status")
    items = sorted(store.certs.values(), key=lambda c: c["_seq"])
    if part_id is not None:
        items = [c for c in items if c["part_id"] == part_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, total = paginate(items, limit, offset)
    return success_list([serialize(c) for c in page], total, limit, offset)
