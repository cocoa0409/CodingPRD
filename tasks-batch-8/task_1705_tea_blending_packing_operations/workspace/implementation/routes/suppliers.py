"""Supplier registry (PRD 3.1)."""
from flask import Blueprint

import store
from auth import ALL_ROLES, authenticate, authorize
from errors import ERR_INVALID_STATE, raise_err
from services import (
    hold_batches_for_lot,
    supplier_out,
)
from util import (
    body_json, bump, get_or_404, new_record, req_str, success_object,
)

bp = Blueprint("suppliers", __name__)


@bp.route("/tea-ops/suppliers", methods=["POST"])
def create_supplier():
    _, role = authenticate()
    authorize(role, ["ProcurementLead"])
    body = body_json()
    name = req_str(body, "name")
    origin_region = req_str(body, "origin_region")

    rec = new_record()
    rec.update({"name": name, "origin_region": origin_region, "status": "ACTIVE"})
    store.suppliers[rec["id"]] = rec
    return success_object(supplier_out(rec), 201)


@bp.route("/tea-ops/suppliers/<sid>", methods=["GET"])
def get_supplier(sid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    rec = get_or_404(store.suppliers, sid, "Supplier")
    return success_object(supplier_out(rec))


@bp.route("/tea-ops/suppliers/<sid>/suspend", methods=["POST"])
def suspend_supplier(sid):
    _, role = authenticate()
    authorize(role, ["ProcurementLead"])
    rec = get_or_404(store.suppliers, sid, "Supplier")
    # Suppliers have no terminal state; suspend requires ACTIVE.
    if rec["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "Supplier is not ACTIVE")
    rec["status"] = "SUSPENDED"
    bump(rec)

    # Cascade link 1: lots in GRADED / LAB_SUBMITTED / RELEASED -> ON_HOLD
    # (REGISTERED, REJECTED, DEPLETED lots untouched).
    for lot in sorted(
        (l for l in store.leaf_lots.values() if l["supplier_id"] == rec["id"]),
        key=lambda l: l["_seq"],
    ):
        if lot["status"] in ("GRADED", "LAB_SUBMITTED", "RELEASED"):
            lot["status"] = "ON_HOLD"
            bump(lot)
            # Cascade links 2 and 3 fire from each lot that just went ON_HOLD.
            hold_batches_for_lot(lot)
    return success_object(supplier_out(rec))


@bp.route("/tea-ops/suppliers/<sid>/reinstate", methods=["POST"])
def reinstate_supplier(sid):
    _, role = authenticate()
    authorize(role, ["ProcurementLead"])
    rec = get_or_404(store.suppliers, sid, "Supplier")
    if rec["status"] != "SUSPENDED":
        raise_err(ERR_INVALID_STATE, "Supplier is not SUSPENDED")
    rec["status"] = "ACTIVE"
    bump(rec)
    # No automatic lot un-hold (PRD 2.8).
    return success_object(supplier_out(rec))
