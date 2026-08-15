"""Magazines, product batches, inventory movements, quarantine."""

from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

from auth import require_roles
from db import store, new_record, bump
from errors import err
from response import ok, ok_list, serialize, serialize_list, sort_created
from services import (
    EVENT_PERMIT_APPROVED, batches_at_show, check_operator_active,
    check_operator_exists, current_site_plan, evaluate_auto_close,
    magazine_of_batch, magazine_posture, operator_of_batch,
    recompute_batch_status, recompute_magazine_mass, rsd_for_diameter,
)
from validation import validate_schema, parse_pagination, paginate

bp = Blueprint("inventory", __name__)

MOVEMENT_TYPES = {"CHECK_OUT", "RETURN", "EXPEND"}
MAGAZINE_TYPES = {"INDOOR", "OUTDOOR"}


def _get_magazine(mag_id):
    mag = store.magazines.get(mag_id)
    if mag is None:
        err("ERR_NOT_FOUND", f"magazine {mag_id} not found")
    return mag


def _get_batch(batch_id):
    batch = store.batches.get(batch_id)
    if batch is None:
        err("ERR_NOT_FOUND", f"batch {batch_id} not found")
    return batch


def _serialize_magazine(mag):
    out = serialize(mag)
    out["posture"] = magazine_posture(mag)
    return out


def _check_mag_ownership(mag, uid):
    if mag["operator_id"] != uid:
        err("ERR_FORBIDDEN_OWNERSHIP", "magazine belongs to another operator")


def _check_batch_ownership(batch, uid):
    if operator_of_batch(batch) != uid:
        err("ERR_FORBIDDEN_OWNERSHIP", "batch belongs to another operator")


# ---- Magazines ---------------------------------------------------------------

@bp.post("/pyro/magazines")
def create_magazine():
    uid, _ = require_roles("Operator")
    vals = validate_schema(request.get_json(silent=True), [
        ("name", "str", True, None),
        ("atf_magazine_permit", "str", True, None),
        ("magazine_type", "enum", True, MAGAZINE_TYPES),
        ("capacity_new_lbs", "num", True, None),
        ("inspection_due_at", "dt", True, None),
    ])
    if vals["capacity_new_lbs"] <= 0:
        err("ERR_VALIDATION", "capacity_new_lbs must be > 0")
    check_operator_exists(uid)
    check_operator_active(uid)
    rec = new_record()
    rec.update({
        "operator_id": uid,
        "name": vals["name"],
        "atf_magazine_permit": vals["atf_magazine_permit"],
        "magazine_type": vals["magazine_type"],
        "capacity_new_lbs": vals["capacity_new_lbs"].quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP),
        "current_new_lbs": Decimal("0.00"),
        "inspection_due_at": vals["inspection_due_at"],
    })
    store.magazines[rec["id"]] = rec
    return ok(_serialize_magazine(rec), 201)


@bp.get("/pyro/magazines/<mag_id>")
def get_magazine(mag_id):
    uid, _ = require_roles("Operator")
    mag = _get_magazine(mag_id)
    _check_mag_ownership(mag, uid)
    return ok(_serialize_magazine(mag))


@bp.get("/pyro/magazines")
def list_magazines():
    uid, _ = require_roles("Operator")
    limit, offset = parse_pagination(request.args)
    op_filter = request.args.get("operator_id")
    if op_filter is not None and op_filter != uid:
        err("ERR_FORBIDDEN_OWNERSHIP", "operator may only list its own magazines")
    recs = sort_created([m for m in store.magazines.values()
                         if m["operator_id"] == uid])
    return ok_list([_serialize_magazine(m) for m in paginate(recs, limit, offset)],
                   len(recs), limit, offset)


# ---- Batches -----------------------------------------------------------------

@bp.post("/pyro/magazines/<mag_id>/batches")
def create_batch(mag_id):
    uid, _ = require_roles("Operator")
    vals = validate_schema(request.get_json(silent=True), [
        ("product_name", "str", True, None),
        ("un_number", "str", True, None),
        ("shell_diameter_in", "num", True, None),
        ("quantity_units", "int", True, None),
        ("new_per_unit_lbs", "num", True, None),
        ("lot_number", "str", True, None),
    ])
    if vals["shell_diameter_in"] <= 0:
        err("ERR_VALIDATION", "shell_diameter_in must be > 0")
    if vals["new_per_unit_lbs"] <= 0:
        err("ERR_VALIDATION", "new_per_unit_lbs must be > 0")
    if vals["quantity_units"] <= 0:
        err("ERR_INVALID_QUANTITY", "quantity_units must be > 0")
    mag = _get_magazine(mag_id)
    _check_mag_ownership(mag, uid)
    check_operator_active(uid)
    if magazine_posture(mag) != "ACTIVE":
        err("ERR_MAGAZINE_LAPSED", "magazine inspection is overdue; intake blocked")
    new_per_unit = vals["new_per_unit_lbs"].quantize(Decimal("0.01"),
                                                     rounding=ROUND_HALF_UP)
    incoming = Decimal(vals["quantity_units"]) * new_per_unit
    if mag["current_new_lbs"] + incoming > mag["capacity_new_lbs"]:
        err("ERR_MAGAZINE_CAPACITY_EXCEEDED",
            "intake would exceed magazine net-explosive-weight capacity")
    rec = new_record()
    rec.update({
        "magazine_id": mag["id"],
        "product_name": vals["product_name"],
        "un_number": vals["un_number"],
        "shell_diameter_in": vals["shell_diameter_in"],
        "quantity_units": vals["quantity_units"],
        "new_per_unit_lbs": new_per_unit,
        "lot_number": vals["lot_number"],
        "quantity_remaining": vals["quantity_units"],
        "qty_at_magazine": vals["quantity_units"],
        "qty_at_show": 0,
        "qty_expended": 0,
        "status": "IN_MAGAZINE",
        "_at_show": {},
    })
    store.batches[rec["id"]] = rec
    recompute_magazine_mass(mag)
    bump(mag)
    return ok(serialize(rec), 201)


@bp.get("/pyro/magazines/<mag_id>/batches")
def list_batches_of_magazine(mag_id):
    uid, _ = require_roles("Operator")
    mag = _get_magazine(mag_id)
    _check_mag_ownership(mag, uid)
    limit, offset = parse_pagination(request.args)
    recs = [b for b in store.batches.values() if b["magazine_id"] == mag_id]
    status = request.args.get("status")
    if status is not None:
        recs = [b for b in recs if b["status"] == status]
    recs = sort_created(recs)
    return ok_list(serialize_list(paginate(recs, limit, offset)), len(recs),
                   limit, offset)


@bp.get("/pyro/batches/<batch_id>")
def get_batch(batch_id):
    uid, _ = require_roles("Operator")
    batch = _get_batch(batch_id)
    _check_batch_ownership(batch, uid)
    return ok(serialize(batch))


@bp.post("/pyro/batches/<batch_id>/quarantine")
def quarantine_batch(batch_id):
    uid, role = require_roles("Operator", "FireMarshal")
    vals = validate_schema(request.get_json(silent=True),
                           [("reason", "str", True, None)])
    batch = _get_batch(batch_id)
    if role == "Operator":
        _check_batch_ownership(batch, uid)
    if batch["status"] not in ("IN_MAGAZINE", "CHECKED_OUT"):
        err("ERR_INVALID_STATE", "batch cannot be quarantined from its current state")
    if role == "Operator":
        check_operator_active(uid)
    batch["status"] = "QUARANTINED"
    bump(batch)
    return ok(serialize(batch))


# ---- Movements ---------------------------------------------------------------

@bp.post("/pyro/batches/<batch_id>/movements")
def create_movement(batch_id):
    uid, _ = require_roles("Operator")
    body = request.get_json(silent=True)
    vals = validate_schema(body, [
        ("movement_type", "enum", True, MOVEMENT_TYPES),
        ("quantity", "int", True, None),
        ("display_event_id", "str", True, None),
        ("driver_name", "str", False, None),
        ("vehicle_placard", "str", False, None),
        ("cdl_hazmat_endorsed", "bool", False, None),
    ])
    if vals["quantity"] <= 0:
        err("ERR_INVALID_QUANTITY", "movement quantity must be > 0")
    mtype = vals["movement_type"]
    if mtype == "CHECK_OUT":
        # Transport-manifest fields are required exactly on checkout.
        for f in ("driver_name", "vehicle_placard", "cdl_hazmat_endorsed"):
            if vals[f] is None:
                err("ERR_VALIDATION", f"{f} is required for CHECK_OUT movements")
    batch = _get_batch(batch_id)
    ev = store.displays.get(vals["display_event_id"])
    if ev is None:
        err("ERR_NOT_FOUND", f"display {vals['display_event_id']} not found")
    _check_batch_ownership(batch, uid)
    check_operator_active(uid)
    if ev["status"] not in EVENT_PERMIT_APPROVED:
        err("ERR_PERMIT_NOT_APPROVED", "the event's permit is not approved")
    if batch["status"] == "QUARANTINED":
        err("ERR_BATCH_QUARANTINED", "movements on a QUARANTINED batch are blocked")
    if mtype == "CHECK_OUT":
        # c_allocation_rsd_gate: evaluation order pinned — the candidate batch
        # joins the at-show set for the max-diameter computation BEFORE gating.
        plan = current_site_plan(ev)
        if plan is not None:
            current_max = max((b["shell_diameter_in"] for b in batches_at_show(ev["id"])),
                              default=Decimal("0"))
            candidate_max = max(current_max, batch["shell_diameter_in"])
            if rsd_for_diameter(candidate_max) > plan["spectator_boundary_ft"]:
                err("ERR_FALLOUT_EXCEEDS_BOUNDARY",
                    "allocation would push the required fallout distance past the boundary")
    if operator_of_batch(batch) != ev["operator_id"]:
        err("ERR_SCOPE_MISMATCH", "batch's operator does not match the event's operator")
    at_show_here = batch["_at_show"].get(ev["id"], 0)
    if mtype == "CHECK_OUT":
        if vals["quantity"] > batch["qty_at_magazine"]:
            err("ERR_INSUFFICIENT_PRODUCT", "quantity exceeds units at the magazine")
    else:
        if vals["quantity"] > at_show_here:
            err("ERR_INSUFFICIENT_PRODUCT",
                "quantity exceeds units at the show for this event")
    if mtype == "CHECK_OUT" and vals["cdl_hazmat_endorsed"] is not True:
        err("ERR_MANIFEST_NOT_COMPLIANT", "driver must hold a CDL hazmat endorsement")
    q = vals["quantity"]
    if mtype == "CHECK_OUT":
        batch["qty_at_magazine"] -= q
        batch["qty_at_show"] += q
        batch["_at_show"][ev["id"]] = at_show_here + q
    elif mtype == "RETURN":
        batch["qty_at_show"] -= q
        batch["qty_at_magazine"] += q
        batch["_at_show"][ev["id"]] = at_show_here - q
    else:  # EXPEND
        batch["qty_at_show"] -= q
        batch["qty_expended"] += q
        batch["_at_show"][ev["id"]] = at_show_here - q
        ev["fired_count"] += q
    recompute_batch_status(batch)
    bump(batch)
    mv = new_record(with_version=False)
    mv.update({
        "product_batch_id": batch["id"],
        "display_event_id": ev["id"],
        "movement_type": mtype,
        "quantity": q,
        "driver_name": vals["driver_name"] if mtype == "CHECK_OUT" else None,
        "vehicle_placard": vals["vehicle_placard"] if mtype == "CHECK_OUT" else None,
        "cdl_hazmat_endorsed": vals["cdl_hazmat_endorsed"] if mtype == "CHECK_OUT" else None,
        "auto_generated": False,
        "recorded_by_user_id": uid,
    })
    store.movements[mv["id"]] = mv
    mag = magazine_of_batch(batch)
    if mag:
        recompute_magazine_mass(mag)
        bump(mag)
    if mtype == "RETURN":
        evaluate_auto_close(ev)
    return ok(serialize(mv), 201)


@bp.get("/pyro/batches/<batch_id>/movements")
def list_movements_of_batch(batch_id):
    uid, _ = require_roles("Operator")
    batch = _get_batch(batch_id)
    _check_batch_ownership(batch, uid)
    limit, offset = parse_pagination(request.args)
    recs = sort_created([m for m in store.movements.values()
                         if m["product_batch_id"] == batch_id])
    return ok_list(serialize_list(paginate(recs, limit, offset)), len(recs),
                   limit, offset)


@bp.get("/pyro/displays/<display_id>/movements")
def list_movements_of_display(display_id):
    uid, role = require_roles("Operator", "FireMarshal")
    ev = store.displays.get(display_id)
    if ev is None:
        err("ERR_NOT_FOUND", f"display {display_id} not found")
    if role == "Operator" and ev["operator_id"] != uid:
        err("ERR_FORBIDDEN_OWNERSHIP", "display belongs to another operator")
    limit, offset = parse_pagination(request.args)
    recs = [m for m in store.movements.values() if m["display_event_id"] == display_id]
    mtype = request.args.get("movement_type")
    if mtype is not None:
        recs = [m for m in recs if m["movement_type"] == mtype]
    recs = sort_created(recs)
    return ok_list(serialize_list(paginate(recs, limit, offset)), len(recs),
                   limit, offset)
