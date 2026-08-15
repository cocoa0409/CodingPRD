"""Supplier and SupplierAgreement endpoints."""
from flask import Blueprint, request

import db
from common import (caller, require_role, body_json, v_str, v_int, v_num,
                    v_enum, v_bool, v_date, v_list, ok, view, stamp_new, touch,
                    paginate, sorted_items, get_or_404, fail)
from logic import (posture_gate, supplier_suspend_cascade,
                   supplier_terminate_cascade, agreement_stop_cascade)

bp = Blueprint("supply", __name__)

SUPPLIER_TYPES = {"FARM", "SLAUGHTERHOUSE", "BUTCHER_SHOP", "GROCERY"}
SPECIES_ALL = {"BOVINE", "PORCINE", "POULTRY", "OVINE", "MIXED"}
POLICIES = {"ZERO_TOLERANCE", "SORT_AND_RETURN"}


# ---------------- suppliers ----------------

@bp.post("/rendering/suppliers")
def create_supplier():
    uid, role = caller()
    b = body_json()
    plant_id = v_str(b, "plant_id")
    name = v_str(b, "supplier_name")
    stype = v_enum(b, "supplier_type", SUPPLIER_TYPES)
    require_role(role, "ProcurementManager")
    plant = get_or_404("plants", plant_id, "ERR_PLANT_NOT_FOUND")
    posture_gate(plant, "admin")
    s = {
        "plant_id": plant_id,
        "supplier_name": name,
        "supplier_type": stype,
        "contamination_strikes": 0,
        "outstanding_service_fees_cents": 0,
        "status": "ACTIVE",
    }
    stamp_new(s)
    db.STORES["suppliers"][s["id"]] = s
    return ok(view(s), 201)


@bp.get("/rendering/suppliers")
def list_suppliers():
    caller()
    items = sorted_items("suppliers", {
        "plant_id": request.args.get("plant_id"),
        "status": request.args.get("status"),
        "supplier_type": request.args.get("supplier_type"),
    })
    return paginate(items)


@bp.get("/rendering/suppliers/<sid>")
def get_supplier(sid):
    caller()
    return ok(view(get_or_404("suppliers", sid, "ERR_SUPPLIER_NOT_FOUND")), 200)


@bp.post("/rendering/suppliers/<sid>/reinstate")
def reinstate_supplier(sid):
    uid, role = caller()
    require_role(role, "ProcurementManager")
    s = get_or_404("suppliers", sid, "ERR_SUPPLIER_NOT_FOUND")
    plant = get_or_404("plants", s["plant_id"], "ERR_PLANT_NOT_FOUND")
    posture_gate(plant, "admin")
    if s["status"] != "SUSPENDED":
        fail("ERR_SUPPLIER_INVALID_STATE", 409, "Supplier must be SUSPENDED to reinstate")
    s["status"] = "ACTIVE"
    s["contamination_strikes"] = 0
    touch(s)
    return ok(view(s), 200)


@bp.post("/rendering/suppliers/<sid>/terminate")
def terminate_supplier(sid):
    uid, role = caller()
    require_role(role, "ProcurementManager")
    s = get_or_404("suppliers", sid, "ERR_SUPPLIER_NOT_FOUND")
    plant = get_or_404("plants", s["plant_id"], "ERR_PLANT_NOT_FOUND")
    posture_gate(plant, "admin")
    if s["status"] not in ("ACTIVE", "SUSPENDED"):
        fail("ERR_SUPPLIER_INVALID_STATE", 409, "Supplier must be ACTIVE or SUSPENDED to terminate")
    supplier_terminate_cascade(s)
    return ok(view(s), 200)


# ---------------- supplier agreements ----------------

@bp.post("/rendering/supplier-agreements")
def create_agreement():
    uid, role = caller()
    b = body_json()
    supplier_id = v_str(b, "supplier_id")
    plant_id = v_str(b, "plant_id")
    ref = v_str(b, "agreement_ref")
    scope = v_list(b, "species_scope", non_empty=True)
    for sp in scope:
        if not isinstance(sp, str) or sp not in SPECIES_ALL:
            fail("ERR_INVALID_REQUEST", 400, "species_scope entries must be declared species")
    policy = v_enum(b, "prohibited_material_policy", POLICIES)
    accepts_ds = v_bool(b, "accepts_dead_stock")
    base_fee = v_int(b, "pickup_base_fee_cents", minv=0)
    per_lb = v_int(b, "per_lb_fee_cents", minv=0)
    mileage = v_int(b, "mileage_rate_cents", minv=0)
    ds_surcharge = v_int(b, "dead_stock_surcharge_cents", minv=0, required=False, default=0)
    min_vol = v_int(b, "minimum_volume_lbs", minv=0, required=False, default=0)
    vol_disc = v_num(b, "volume_discount_pct", required=False, default=0)
    eff_from = v_date(b, "effective_from")
    eff_to = v_date(b, "effective_to")
    if eff_to < eff_from:
        fail("ERR_INVALID_REQUEST", 400, "effective_to must be >= effective_from")
    require_role(role, "ProcurementManager")
    supplier = get_or_404("suppliers", supplier_id, "ERR_SUPPLIER_NOT_FOUND")
    plant = get_or_404("plants", plant_id, "ERR_PLANT_NOT_FOUND")
    if supplier["plant_id"] != plant_id:
        fail("ERR_INVALID_REQUEST", 400, "plant_id must equal the supplier's owning plant")
    posture_gate(plant, "admin")
    ag = {
        "supplier_id": supplier_id,
        "plant_id": plant_id,
        "agreement_ref": ref,
        "species_scope": scope,
        "prohibited_material_policy": policy,
        "accepts_dead_stock": accepts_ds,
        "pickup_base_fee_cents": base_fee,
        "per_lb_fee_cents": per_lb,
        "mileage_rate_cents": mileage,
        "dead_stock_surcharge_cents": ds_surcharge,
        "minimum_volume_lbs": min_vol,
        "volume_discount_pct": vol_disc,
        "effective_from": eff_from,
        "effective_to": eff_to,
        "created_by": uid,
        "status": "DRAFT",
    }
    stamp_new(ag)
    db.STORES["agreements"][ag["id"]] = ag
    return ok(view(ag), 201)


@bp.get("/rendering/supplier-agreements")
def list_agreements():
    caller()
    items = sorted_items("agreements", {
        "plant_id": request.args.get("plant_id"),
        "supplier_id": request.args.get("supplier_id"),
        "status": request.args.get("status"),
    })
    return paginate(items)


@bp.get("/rendering/supplier-agreements/<aid>")
def get_agreement(aid):
    caller()
    return ok(view(get_or_404("agreements", aid, "ERR_AGREEMENT_NOT_FOUND")), 200)


def _get_agreement_and_plant(aid):
    ag = get_or_404("agreements", aid, "ERR_AGREEMENT_NOT_FOUND")
    plant = get_or_404("plants", ag["plant_id"], "ERR_PLANT_NOT_FOUND")
    return ag, plant


@bp.post("/rendering/supplier-agreements/<aid>/submit")
def submit_agreement(aid):
    uid, role = caller()
    require_role(role, "ProcurementManager")
    ag, plant = _get_agreement_and_plant(aid)
    posture_gate(plant, "admin")
    if ag["status"] != "DRAFT":
        fail("ERR_AGREEMENT_INVALID_STATE", 409, "Agreement must be DRAFT to submit")
    ag["status"] = "SUBMITTED"
    touch(ag)
    return ok(view(ag), 200)


@bp.post("/rendering/supplier-agreements/<aid>/approve")
def approve_agreement(aid):
    uid, role = caller()
    require_role(role, "PlantManager")
    ag, plant = _get_agreement_and_plant(aid)
    posture_gate(plant, "admin")
    if ag["status"] != "SUBMITTED":
        fail("ERR_AGREEMENT_INVALID_STATE", 409, "Agreement must be SUBMITTED to approve")
    if ag["created_by"] == uid:
        fail("ERR_SOD_VIOLATION", 403, "Approver must differ from creator")
    for other in db.STORES["agreements"].values():
        if (other["id"] != ag["id"] and other["supplier_id"] == ag["supplier_id"]
                and other["status"] in ("ACTIVE", "SUSPENDED")
                and other["effective_from"] <= ag["effective_to"]
                and ag["effective_from"] <= other["effective_to"]):
            fail("ERR_AGREEMENT_WINDOW_OVERLAP", 409,
                 "Overlapping ACTIVE/SUSPENDED agreement window for this supplier")
    ag["status"] = "ACTIVE"
    touch(ag)
    return ok(view(ag), 200)


@bp.post("/rendering/supplier-agreements/<aid>/return-to-draft")
def return_agreement(aid):
    uid, role = caller()
    require_role(role, "PlantManager")
    ag, plant = _get_agreement_and_plant(aid)
    posture_gate(plant, "admin")
    if ag["status"] != "SUBMITTED":
        fail("ERR_AGREEMENT_INVALID_STATE", 409, "Agreement must be SUBMITTED to return to draft")
    ag["status"] = "DRAFT"
    touch(ag)
    return ok(view(ag), 200)


@bp.post("/rendering/supplier-agreements/<aid>/suspend")
def suspend_agreement(aid):
    uid, role = caller()
    require_role(role, "PlantManager")
    ag, plant = _get_agreement_and_plant(aid)
    posture_gate(plant, "admin")
    if ag["status"] != "ACTIVE":
        fail("ERR_AGREEMENT_INVALID_STATE", 409, "Agreement must be ACTIVE to suspend")
    ag["status"] = "SUSPENDED"
    touch(ag)
    agreement_stop_cascade(ag)
    return ok(view(ag), 200)


@bp.post("/rendering/supplier-agreements/<aid>/reinstate")
def reinstate_agreement(aid):
    uid, role = caller()
    require_role(role, "PlantManager")
    ag, plant = _get_agreement_and_plant(aid)
    posture_gate(plant, "admin")
    if ag["status"] != "SUSPENDED":
        fail("ERR_AGREEMENT_INVALID_STATE", 409, "Agreement must be SUSPENDED to reinstate")
    supplier = get_or_404("suppliers", ag["supplier_id"], "ERR_SUPPLIER_NOT_FOUND")
    if supplier["status"] != "ACTIVE":
        fail("ERR_SUPPLIER_NOT_ACTIVE", 409, "Supplier must be ACTIVE to reinstate an agreement")
    ag["status"] = "ACTIVE"
    touch(ag)
    return ok(view(ag), 200)


@bp.post("/rendering/supplier-agreements/<aid>/terminate")
def terminate_agreement(aid):
    uid, role = caller()
    require_role(role, "PlantManager")
    ag, plant = _get_agreement_and_plant(aid)
    posture_gate(plant, "admin")
    if ag["status"] not in ("ACTIVE", "SUSPENDED", "DRAFT", "SUBMITTED"):
        fail("ERR_AGREEMENT_INVALID_STATE", 409, "Agreement cannot be terminated from its state")
    had_stops = ag["status"] in ("ACTIVE", "SUSPENDED")
    ag["status"] = "TERMINATED"
    touch(ag)
    if had_stops:
        agreement_stop_cascade(ag)
    return ok(view(ag), 200)


@bp.post("/rendering/supplier-agreements/<aid>/amend")
def amend_agreement(aid):
    uid, role = caller()
    b = body_json()
    expected = v_int(b, "expected_agreement_version")
    new_base = v_int(b, "pickup_base_fee_cents", minv=0, required=False)
    new_per_lb = v_int(b, "per_lb_fee_cents", minv=0, required=False)
    new_mileage = v_int(b, "mileage_rate_cents", minv=0, required=False)
    new_surcharge = v_int(b, "dead_stock_surcharge_cents", minv=0, required=False)
    new_minvol = v_int(b, "minimum_volume_lbs", minv=0, required=False)
    new_disc = v_num(b, "volume_discount_pct", required=False)
    new_to = v_date(b, "effective_to", required=False)
    require_role(role, "ProcurementManager")
    ag, plant = _get_agreement_and_plant(aid)
    posture_gate(plant, "admin")
    if ag["status"] != "ACTIVE":
        fail("ERR_AGREEMENT_INVALID_STATE", 409, "Only an ACTIVE agreement may be amended")
    if ag["version"] != expected:
        fail("ERR_STALE_VERSION", 412, "expected_agreement_version does not match current version")
    if new_base is not None:
        ag["pickup_base_fee_cents"] = new_base
    if new_per_lb is not None:
        ag["per_lb_fee_cents"] = new_per_lb
    if new_mileage is not None:
        ag["mileage_rate_cents"] = new_mileage
    if new_surcharge is not None:
        ag["dead_stock_surcharge_cents"] = new_surcharge
    if new_minvol is not None:
        ag["minimum_volume_lbs"] = new_minvol
    if new_disc is not None:
        ag["volume_discount_pct"] = new_disc
    if new_to is not None:
        if new_to < ag["effective_from"]:
            fail("ERR_INVALID_REQUEST", 400, "effective_to must be >= effective_from")
        ag["effective_to"] = new_to
    touch(ag)
    return ok(view(ag), 200)
