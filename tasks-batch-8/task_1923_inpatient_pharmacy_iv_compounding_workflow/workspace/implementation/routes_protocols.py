"""Substitution protocols, waste records, and the logical clock."""

from flask import Blueprint, request

import db
import validate as V
import ops
from auth import authenticate, ALL_ROLES
from errors import (
    err_not_found, err_invalid_state, err_protocol_expired,
    err_drug_not_in_shortage, err_no_eligible_substitute,
)
from response import ok, ok_list, serialize, paginate
from timeutil import fmt

bp = Blueprint("protocols", __name__)

ADMIN = ["PharmacyAdmin"]


def _get_protocol(pid):
    p = db.protocols.get(pid)
    if p is None:
        raise err_not_found("Substitution protocol not found")
    return p


@bp.post("/pharmacy/substitution-protocols")
def create_protocol():
    authenticate(ADMIN)
    d = V.body()
    shortage_id = V.req_str(d, "shortage_drug_product_id")
    substitute_id = V.req_str(d, "substitute_drug_product_id")
    conversion_factor = V.req_number(d, "conversion_factor")
    max_dose_mg = V.req_number(d, "max_dose_mg")
    min_dose_mg = V.opt_number(d, "min_dose_mg", 0)
    expires_at = V.req_datetime(d, "expires_at")
    if shortage_id not in db.drugs:
        raise err_not_found("Shortage drug product not found")
    if substitute_id not in db.drugs:
        raise err_not_found("Substitute drug product not found")
    protocol = db.base_fields()
    protocol.update({
        "shortage_drug_product_id": shortage_id,
        "substitute_drug_product_id": substitute_id,
        "conversion_factor": conversion_factor,
        "min_dose_mg": min_dose_mg,
        "max_dose_mg": max_dose_mg,
        "expires_at": expires_at,
        "status": "DRAFT",
    })
    db.protocols[protocol["id"]] = protocol
    return ok(serialize(protocol), 201)


@bp.get("/pharmacy/substitution-protocols/<pid>")
def get_protocol(pid):
    authenticate(ALL_ROLES)
    return ok(serialize(_get_protocol(pid)))


@bp.get("/pharmacy/substitution-protocols")
def list_protocols():
    authenticate(ALL_ROLES)
    items = list(db.protocols.values())
    sub = request.args.get("substitute_drug_product_id")
    if sub is not None:
        items = [p for p in items if p["substitute_drug_product_id"] == sub]
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    page, meta = paginate(items, request.args)
    return ok_list(page, meta)


@bp.post("/pharmacy/substitution-protocols/<pid>/activate")
def activate_protocol(pid):
    authenticate(ADMIN)
    V.body()
    protocol = _get_protocol(pid)
    if protocol["status"] != "DRAFT":
        raise err_invalid_state("Protocol is not DRAFT")
    # Temporal tier (27) masks referential tiers (34, 35).
    if not (db.now() < protocol["expires_at"]):
        raise err_protocol_expired()
    substitute = db.drugs[protocol["substitute_drug_product_id"]]
    if substitute["status"] != "ACTIVE":
        raise err_no_eligible_substitute()
    shortage = db.drugs[protocol["shortage_drug_product_id"]]
    if not shortage["in_shortage"]:
        raise err_drug_not_in_shortage()
    protocol["status"] = "ACTIVE"
    db.touch(protocol)
    ops.protocol_flagging_cascade(protocol)
    return ok(serialize(protocol))


@bp.post("/pharmacy/substitution-protocols/<pid>/revoke")
def revoke_protocol(pid):
    authenticate(ADMIN)
    V.body()
    protocol = _get_protocol(pid)
    if protocol["status"] != "ACTIVE":
        raise err_invalid_state("Protocol is not ACTIVE")
    protocol["status"] = "REVOKED"
    db.touch(protocol)
    ops.protocol_compensation_cascade(protocol)
    return ok(serialize(protocol))


# ---------------------------------------------------------------------------
# Waste records (shared read model)
# ---------------------------------------------------------------------------

@bp.get("/pharmacy/waste-records/<wid>")
def get_waste_record(wid):
    authenticate(ALL_ROLES)
    wr = db.waste_records.get(wid)
    if wr is None:
        raise err_not_found("Waste record not found")
    return ok(serialize(wr))


@bp.get("/pharmacy/waste-records")
def list_waste_records():
    authenticate(ALL_ROLES)
    items = list(db.waste_records.values())
    for param in ("pocket_id", "recorded_by_staff_id", "witness_staff_id"):
        v = request.args.get(param)
        if v is not None:
            items = [w for w in items if w[param] == v]
    page, meta = paginate(items, request.args)
    return ok_list(page, meta)


# ---------------------------------------------------------------------------
# Logical clock (test-driving capability)
# ---------------------------------------------------------------------------

@bp.post("/pharmacy/_clock/set_current_utc")
def set_clock():
    uid, _, _ = authenticate(ADMIN)
    d = V.body()
    to = V.req_datetime(d, "to_iso8601")
    db.set_clock(to)
    ops.run_expiry_sweeps(uid)
    return ok({"now": fmt(db.now())})
