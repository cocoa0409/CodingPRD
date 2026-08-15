"""Hood sessions, compounding batches, preparations (PRD Section 3.5)."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

import db
import validate as V
import calc
import ops
from auth import authenticate, ALL_ROLES
from errors import (
    err_not_found, err_stale_version, err_invalid_state, err_invalid_request,
    err_invalid_quantity, err_hood_overlap, err_hd_cert, err_hood_not_hd,
    err_hood_session_not_active, err_outside_window, err_sod,
    err_waste_tolerance, err_order_not_verified,
)
from response import ok, ok_list, serialize, paginate

bp = Blueprint("compounding", __name__)

TECH = ["PharmacyTechnician"]
PHARMACIST = ["Pharmacist"]
RISK_LEVELS = {"LOW", "MEDIUM", "HIGH"}
STORAGE_CONDITIONS = {"ROOM", "REFRIGERATED", "FROZEN"}


# ---------------------------------------------------------------------------
# Hood sessions
# ---------------------------------------------------------------------------

@bp.post("/pharmacy/hood-sessions")
def create_session():
    authenticate(TECH)
    d = V.body()
    hood_id = V.req_str(d, "hood_id")
    start_at = V.req_datetime(d, "start_at")
    end_at = V.req_datetime(d, "end_at")
    if hood_id not in db.hoods:
        raise err_not_found("Hood not found")
    if not (end_at > start_at):
        raise err_invalid_quantity("end_at must be strictly after start_at")
    # Half-open overlap against non-cancelled sessions on the same hood;
    # adjacency (start == other end) is allowed.
    for s in db.sessions.values():
        if s["hood_id"] != hood_id or s["status"] not in ("SCHEDULED", "IN_USE"):
            continue
        if start_at < s["end_at"] and s["start_at"] < end_at:
            raise err_hood_overlap()
    session = db.base_fields()
    session.update({
        "hood_id": hood_id,
        "start_at": start_at,
        "end_at": end_at,
        "status": "SCHEDULED",
    })
    db.sessions[session["id"]] = session
    return ok(serialize(session), 201)


@bp.get("/pharmacy/hood-sessions/<sid>")
def get_session(sid):
    authenticate(ALL_ROLES)
    s = db.sessions.get(sid)
    if s is None:
        raise err_not_found("Hood session not found")
    return ok(serialize(s))


@bp.get("/pharmacy/hood-sessions")
def list_sessions():
    authenticate(ALL_ROLES)
    items = list(db.sessions.values())
    hood_id = request.args.get("hood_id")
    if hood_id is not None:
        items = [s for s in items if s["hood_id"] == hood_id]
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    page, meta = paginate(items, request.args)
    return ok_list(page, meta)


def _get_session(sid):
    s = db.sessions.get(sid)
    if s is None:
        raise err_not_found("Hood session not found")
    return s


@bp.post("/pharmacy/hood-sessions/<sid>/start")
def start_session(sid):
    authenticate(TECH)
    V.body()
    s = _get_session(sid)
    if s["status"] != "SCHEDULED":
        raise err_invalid_state("Hood session is not SCHEDULED")
    if not (s["start_at"] <= db.now() < s["end_at"]):
        raise err_outside_window()
    s["status"] = "IN_USE"
    db.touch(s)
    return ok(serialize(s))


@bp.post("/pharmacy/hood-sessions/<sid>/complete")
def complete_session(sid):
    authenticate(TECH)
    V.body()
    s = _get_session(sid)
    if s["status"] != "IN_USE":
        raise err_invalid_state("Hood session is not IN_USE")
    s["status"] = "COMPLETED"
    db.touch(s)
    return ok(serialize(s))


@bp.post("/pharmacy/hood-sessions/<sid>/cancel")
def cancel_session(sid):
    authenticate(TECH)
    V.body()
    s = _get_session(sid)
    if s["status"] not in ("SCHEDULED", "IN_USE"):
        raise err_invalid_state("Hood session cannot be cancelled from its current state")
    s["status"] = "CANCELLED"
    db.touch(s)
    return ok(serialize(s))


# ---------------------------------------------------------------------------
# Batches
# ---------------------------------------------------------------------------

def _get_batch(bid):
    b = db.batches.get(bid)
    if b is None:
        raise err_not_found("Batch not found")
    return b


@bp.post("/pharmacy/batches")
def create_batch():
    uid, _, _ = authenticate(TECH)
    d = V.body()
    hood_session_id = V.req_str(d, "hood_session_id")
    order_ids = V.req_str_list(d, "order_ids", non_empty=True)
    usp_risk_level = V.req_enum(d, "usp_risk_level", RISK_LEVELS)
    documents_stability_source = V.opt_bool(d, "documents_stability_source", False)

    if hood_session_id not in db.sessions:
        raise err_not_found("Hood session not found")
    orders = []
    for oid in order_ids:
        order = db.orders.get(oid)
        if order is None:
            raise err_not_found("Medication order not found")
        orders.append(order)
    # Atomic preconditions: every order VERIFIED, IV, and awaiting compounding.
    for order in orders:
        if order["verification_status"] != "VERIFIED":
            raise err_order_not_verified()
    for order in orders:
        if order["route"] != "IV" or order["fulfillment_status"] != "QUEUED":
            raise err_invalid_state("Order is not an IV order awaiting compounding")

    batch = db.base_fields()
    batch.update({
        "hood_session_id": hood_session_id,
        "compounder_staff_id": uid,
        "qa_pharmacist_staff_id": None,
        "usp_risk_level": usp_risk_level,
        "documents_stability_source": documents_stability_source,
        "status": "DRAFT",
        "rework_count": 0,
        "demand_ml": Decimal("0"),
        "vials_used": 0,
        "total_drawn_ml": Decimal("0"),
        "delivered_ml": Decimal("0"),
        "waste_ml": Decimal("0"),
        "overage_pct": Decimal("0"),
        "_first_drug_id": None,
        "_last_run_drawn": Decimal("0"),
    })
    db.batches[batch["id"]] = batch

    for order in orders:
        prep = db.base_fields()
        prep.update({
            "batch_id": batch["id"],
            "order_id": order["id"],
            "drug_product_id": order["drug_product_id"],
            "status": "PLANNED",
            "prepared_volume_ml": None,
            "storage_condition": None,
            "bud_expiry": None,
        })
        db.preparations[prep["id"]] = prep
        if batch["_first_drug_id"] is None:
            batch["_first_drug_id"] = order["drug_product_id"]
        order["fulfillment_status"] = "COMPOUNDING"
        db.touch(order)

    ops.recompute_batch_derived(batch)
    return ok(serialize(batch), 201)


@bp.get("/pharmacy/batches/<bid>")
def get_batch(bid):
    authenticate(ALL_ROLES)
    return ok(serialize(_get_batch(bid)))


@bp.get("/pharmacy/batches")
def list_batches():
    authenticate(ALL_ROLES)
    items = list(db.batches.values())
    for param in ("status", "compounder_staff_id", "qa_pharmacist_staff_id",
                  "hood_session_id"):
        v = request.args.get(param)
        if v is not None:
            items = [b for b in items if b[param] == v]
    page, meta = paginate(items, request.args)
    return ok_list(page, meta)


@bp.post("/pharmacy/batches/<bid>/start")
def start_batch(bid):
    authenticate(TECH)
    V.body()
    batch = _get_batch(bid)
    if batch["status"] != "DRAFT":
        raise err_invalid_state("Batch is not DRAFT")
    planned = [p for p in calc.batch_preparations(bid) if p["status"] == "PLANNED"]
    any_hazardous = any(db.drugs[p["drug_product_id"]]["is_hazardous"] for p in planned)
    if any_hazardous:
        # Safety tier order: certification (11) before hood rating (12).
        compounder = db.staff.get(batch["compounder_staff_id"])
        certified = (
            compounder is not None
            and compounder["hd_compounding_certified"]
            and compounder["hd_cert_expires_at"] is not None
            and compounder["hd_cert_expires_at"] > db.now()
        )
        if not certified:
            raise err_hd_cert()
        hood = db.hoods[db.sessions[batch["hood_session_id"]]["hood_id"]]
        if not hood["is_hd_rated"]:
            raise err_hood_not_hd()
    session = db.sessions[batch["hood_session_id"]]
    if session["status"] != "IN_USE":
        raise err_hood_session_not_active()
    if not planned:
        raise err_invalid_state("No preparation remains in PLANNED")
    batch["status"] = "IN_PROGRESS"
    db.touch(batch)
    return ok(serialize(batch))


@bp.post("/pharmacy/batches/<bid>/complete")
def complete_batch(bid):
    uid, _, _ = authenticate(TECH)
    d = V.body()
    prepared_volumes = V.req_number_list(d, "prepared_volumes_ml")
    waste_ml = V.req_number(d, "waste_ml")
    storage_condition = V.req_enum(d, "storage_condition", STORAGE_CONDITIONS)
    V.occ_field(d, "expected_batch_version", required=False)
    batch = _get_batch(bid)
    expected = d.get("expected_batch_version")
    if expected is not None and expected != batch["version"]:
        raise err_stale_version("expected_batch_version does not match the batch version")
    if batch["status"] != "IN_PROGRESS":
        raise err_invalid_state("Batch is not IN_PROGRESS")
    planned = [p for p in calc.batch_preparations(bid) if p["status"] == "PLANNED"]
    if len(prepared_volumes) != len(planned):
        raise err_invalid_request(
            "prepared_volumes_ml must carry one entry per PLANNED preparation"
        )
    if waste_ml < 0:
        raise err_invalid_quantity("waste_ml must be non-negative")

    completed_at = db.now()
    # Move every PLANNED preparation to COMPOUNDED with its BUD.
    for prep, volume in zip(planned, prepared_volumes):
        prep["status"] = "COMPOUNDED"
        prep["prepared_volume_ml"] = volume
        prep["storage_condition"] = storage_condition
        drug = db.drugs[prep["drug_product_id"]]
        hours = calc.beyond_use_hours(batch, drug, storage_condition)
        prep["bud_expiry"] = completed_at + timedelta(hours=hours)
        db.touch(prep)

    # Pinned evaluation order: demand -> vials -> drawn -> waste -> overage.
    demand, vials = calc.compute_demand_and_vials(batch)
    first_drug = db.drugs[batch["_first_drug_id"]]
    run_drawn = Decimal(vials) * Decimal(str(first_drug["vial_size_ml"]))
    run_waste = waste_ml
    batch["demand_ml"] = demand
    batch["vials_used"] = vials
    if run_drawn > 0:
        batch["overage_pct"] = calc.round2(run_waste / run_drawn * Decimal("100"))
    else:
        batch["overage_pct"] = Decimal("0")
    batch["total_drawn_ml"] = Decimal(str(batch["total_drawn_ml"])) + run_drawn
    batch["waste_ml"] = Decimal(str(batch["waste_ml"])) + run_waste
    batch["delivered_ml"] = calc.compute_delivered(bid)
    batch["_last_run_drawn"] = run_drawn

    ops.append_waste_record(
        recorded_by=uid, reason="PARTIAL_VIAL",
        batch_id=batch["id"], volume_ml=run_waste,
    )
    batch["status"] = "QA_REVIEW"
    db.touch(batch)
    return ok(serialize(batch))


@bp.post("/pharmacy/batches/<bid>/qa-release")
def qa_release_batch(bid):
    uid, _, _ = authenticate(PHARMACIST)
    V.body()
    batch = _get_batch(bid)
    if batch["status"] != "QA_REVIEW":
        raise err_invalid_state("Batch is not QA_REVIEW")
    if uid == batch["compounder_staff_id"]:
        raise err_sod()
    # Size tier is read off the latest completion's drawn volume.
    tier = calc.size_tier(batch.get("_last_run_drawn", Decimal("0")))
    if batch["overage_pct"] > calc.TOLERANCE_PCT[tier]:
        raise err_waste_tolerance()
    for prep in calc.batch_preparations(bid):
        if prep["status"] == "COMPOUNDED":
            prep["status"] = "QA_PASSED"
            db.touch(prep)
            order = db.orders[prep["order_id"]]
            if order["fulfillment_status"] == "COMPOUNDING":
                order["fulfillment_status"] = "READY"
                db.touch(order)
    batch["qa_pharmacist_staff_id"] = uid
    batch["status"] = "RELEASED"
    batch["delivered_ml"] = calc.compute_delivered(bid)
    db.touch(batch)
    return ok(serialize(batch))


@bp.post("/pharmacy/batches/<bid>/qa-reject")
def qa_reject_batch(bid):
    uid, _, _ = authenticate(PHARMACIST)
    d = V.body()
    V.req_str(d, "reason")
    batch = _get_batch(bid)
    if batch["status"] != "QA_REVIEW":
        raise err_invalid_state("Batch is not QA_REVIEW")
    if uid == batch["compounder_staff_id"]:
        raise err_sod()
    wasted_volume = Decimal("0")
    for prep in calc.batch_preparations(bid):
        if prep["status"] == "COMPOUNDED":
            prep["status"] = "WASTED"
            if prep["prepared_volume_ml"] is not None:
                wasted_volume += Decimal(str(prep["prepared_volume_ml"]))
            db.touch(prep)
    batch["waste_ml"] = Decimal(str(batch["waste_ml"])) + wasted_volume
    ops.append_waste_record(
        recorded_by=uid, reason="QA_REJECT",
        batch_id=batch["id"], volume_ml=wasted_volume,
    )
    batch["status"] = "REJECTED"
    batch["delivered_ml"] = calc.compute_delivered(bid)
    db.touch(batch)
    return ok(serialize(batch))


@bp.post("/pharmacy/batches/<bid>/rework")
def rework_batch(bid):
    authenticate(TECH)
    V.body()
    batch = _get_batch(bid)
    if batch["status"] != "REJECTED":
        raise err_invalid_state("Batch is not REJECTED")
    if batch["rework_count"] >= calc.MAX_REWORK:
        # Rework cap reached: the same call transitions to terminal FAILED.
        batch["status"] = "FAILED"
        db.touch(batch)
        return ok(serialize(batch))
    batch["rework_count"] += 1
    # Fresh PLANNED preparations for linked orders still VERIFIED.
    linked_order_ids = []
    for prep in calc.batch_preparations(bid):
        if prep["order_id"] not in linked_order_ids:
            linked_order_ids.append(prep["order_id"])
    for oid in linked_order_ids:
        order = db.orders[oid]
        if order["verification_status"] == "VERIFIED" and not ops.order_is_terminal(order):
            prep = db.base_fields()
            prep.update({
                "batch_id": batch["id"],
                "order_id": order["id"],
                "drug_product_id": order["drug_product_id"],
                "status": "PLANNED",
                "prepared_volume_ml": None,
                "storage_condition": None,
                "bud_expiry": None,
            })
            db.preparations[prep["id"]] = prep
    batch["status"] = "DRAFT"
    ops.recompute_batch_derived(batch)
    db.touch(batch)
    return ok(serialize(batch))


# ---------------------------------------------------------------------------
# Preparations
# ---------------------------------------------------------------------------

@bp.get("/pharmacy/batches/<bid>/preparations")
def list_batch_preparations(bid):
    authenticate(ALL_ROLES)
    batch = _get_batch(bid)
    items = calc.batch_preparations(batch["id"])
    page, meta = paginate(items, request.args)
    return ok_list(page, meta)


@bp.get("/pharmacy/batches/<bid>/waste-records")
def list_batch_waste_records(bid):
    authenticate(ALL_ROLES)
    batch = _get_batch(bid)
    items = [w for w in db.waste_records.values() if w["batch_id"] == batch["id"]]
    page, meta = paginate(items, request.args)
    return ok_list(page, meta)


@bp.get("/pharmacy/preparations/<pid>")
def get_preparation(pid):
    authenticate(ALL_ROLES)
    prep = db.preparations.get(pid)
    if prep is None:
        raise err_not_found("Preparation not found")
    return ok(serialize(prep))


@bp.get("/pharmacy/preparations")
def list_preparations():
    authenticate(ALL_ROLES)
    items = list(db.preparations.values())
    for param in ("batch_id", "order_id", "drug_product_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [p for p in items if p[param] == v]
    page, meta = paginate(items, request.args)
    return ok_list(page, meta)
