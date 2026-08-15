"""Routes: logical clock, complaints, theft incidents, processing batches
(PRD 2.4, 3.8, 3.9, 3.3)."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, g

import calc
import serialize
from db import parse_dt, store
from errors import err
from helpers import (
    cc_check,
    fk_exists,
    fresh_complaint,
    get_batch,
    get_complaint,
    get_manifest,
    get_theft,
    get_body,
    opt_str,
    req_dt,
    req_enum,
    req_num,
    req_str,
    require_roles,
)
from response import success

bp = Blueprint("ops", __name__)

COMPLAINT_CATEGORIES = {"SPILL", "ODOR", "NUISANCE", "THEFT_ATTEMPT"}
COMPLAINT_SEVERITIES = {"LOW", "MEDIUM", "HIGH"}
SPILL_BLOCKING = {"OPEN", "INVESTIGATING", "ESCALATED", "REOPENED"}


# ---------------------------------------------------------------------------
# Logical clock (PRD 2.4) — SystemAdmin-exclusive test-driving capability.
# ---------------------------------------------------------------------------
@bp.route("/api/_clock/set_current_utc", methods=["POST"])
@require_roles("SystemAdmin")
def set_clock():
    body = get_body()
    store.clock = req_dt(body, "to_iso8601")
    return success({})


# ---------------------------------------------------------------------------
# Complaints (PRD 3.8)
# ---------------------------------------------------------------------------
@bp.route("/api/complaints", methods=["POST"])
@require_roles("CustomerContact", "FieldOpsManager")
def create_complaint():
    body = get_body()
    # Ownership (priority 2) evaluates before full schema validation: a
    # CustomerContact filing for another customer is forbidden outright.
    raw_customer = body.get("customer_id")
    if g.role == "CustomerContact" and isinstance(raw_customer, str):
        cc_check(raw_customer)
    customer_id = req_str(body, "customer_id")
    fk_exists(store.customers, customer_id, "customer_id")
    category = req_enum(body, "category", COMPLAINT_CATEGORIES)
    severity = req_enum(body, "severity", COMPLAINT_SEVERITIES)
    note = req_str(body, "note")
    visit_id = opt_str(body, "pickup_visit_id")
    if category == "SPILL" and visit_id is None:
        raise err("ERR_VALIDATION", "pickup_visit_id is required for category SPILL")
    if visit_id is not None:
        fk_exists(store.visits, visit_id, "pickup_visit_id")
    rec = {
        "id": store.new_id(),
        "customer_id": customer_id,
        "pickup_visit_id": visit_id,
        "category": category,
        "severity": severity,
        "note": note,
        "status": "OPEN",
        "resolved_at": None,
        "reopen_count": 0,
        "resolution_note": None,
    }
    store.stamp(rec)
    store.complaints[rec["id"]] = rec
    return success(serialize.complaint(rec), code=201)


@bp.route("/api/complaints/<cid>/investigate", methods=["POST"])
@require_roles("FieldOpsManager")
def investigate_complaint(cid):
    rec = get_complaint(cid)
    if rec["status"] not in ("OPEN", "REOPENED"):
        raise err("ERR_INVALID_STATE", "Complaint %s is %s; investigate requires OPEN or REOPENED" % (cid, rec["status"]))
    rec["status"] = "INVESTIGATING"
    store.bump(rec)
    return success(serialize.complaint(rec))


@bp.route("/api/complaints/<cid>/escalate", methods=["POST"])
@require_roles("FieldOpsManager")
def escalate_complaint(cid):
    rec = get_complaint(cid)
    body = get_body()
    opt_str(body, "note")
    if rec["status"] != "INVESTIGATING":
        raise err("ERR_INVALID_STATE", "Complaint %s is %s; escalate requires INVESTIGATING" % (cid, rec["status"]))
    rec["status"] = "ESCALATED"
    store.bump(rec)
    return success(serialize.complaint(rec))


@bp.route("/api/complaints/<cid>/resolve", methods=["POST"])
@require_roles("FieldOpsManager")
def resolve_complaint(cid):
    rec = get_complaint(cid)
    body = get_body()
    resolution_note = req_str(body, "resolution_note")
    if rec["status"] not in ("INVESTIGATING", "ESCALATED"):
        raise err("ERR_INVALID_STATE", "Complaint %s is %s; resolve requires INVESTIGATING or ESCALATED" % (cid, rec["status"]))
    rec["resolution_note"] = resolution_note
    rec["resolved_at"] = store.now_iso()
    rec["status"] = "RESOLVED"
    store.bump(rec)
    return success(serialize.complaint(rec))


@bp.route("/api/complaints/<cid>/reopen", methods=["POST"])
@require_roles("CustomerContact")
def reopen_complaint(cid):
    # Loaded WITHOUT lazy auto-close: the reopen-window check (priority 22)
    # must see the stored RESOLVED state to reject past-window attempts with
    # ERR_COMPLAINT_REOPEN_WINDOW_EXPIRED rather than ERR_INVALID_STATE.
    rec = store.complaints.get(cid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Complaint %s not found" % cid)
    cc_check(rec["customer_id"])
    body = get_body()
    req_str(body, "note")
    if rec["status"] != "RESOLVED":
        raise err("ERR_INVALID_STATE", "Complaint %s is %s; only RESOLVED can be reopened" % (cid, rec["status"]))
    deadline = parse_dt(rec["resolved_at"]) + timedelta(days=calc.COMPLAINT_REOPEN_WINDOW_DAYS)
    if store.clock > deadline:
        fresh_complaint(rec)  # the write access lands the lazy auto-close
        raise err("ERR_COMPLAINT_REOPEN_WINDOW_EXPIRED", "Complaint %s resolved more than 7 days ago" % cid)
    rec["reopen_count"] += 1
    rec["status"] = "REOPENED"
    store.bump(rec)
    return success(serialize.complaint(rec))


# ---------------------------------------------------------------------------
# Theft incidents (PRD 3.3)
# ---------------------------------------------------------------------------
@bp.route("/api/theft-incidents", methods=["POST"])
@require_roles("Driver", "CustomerContact", "FieldOpsManager")
def create_theft():
    body = get_body()
    container_id = req_str(body, "container_id")
    evidence_note = req_str(body, "evidence_note")
    container = fk_exists(store.containers, container_id, "container_id")
    if g.role == "CustomerContact":
        cc_check(container["customer_id"])
    rec = {
        "id": store.new_id(),
        "container_id": container_id,
        "evidence_note": evidence_note,
        "status": "REPORTED",
        "resolution_note": None,
    }
    store.stamp(rec)
    store.thefts[rec["id"]] = rec
    return success(serialize.theft(rec), code=201)


@bp.route("/api/theft-incidents/<tid>/confirm", methods=["POST"])
@require_roles("FieldOpsManager")
def confirm_theft(tid):
    rec = get_theft(tid)
    if rec["status"] != "REPORTED":
        raise err("ERR_INVALID_STATE", "Theft incident %s is %s; only REPORTED can be confirmed" % (tid, rec["status"]))
    rec["status"] = "CONFIRMED"
    store.bump(rec)
    # Cascade (PRD 3.3): lock the container, skip its SCHEDULED visits, and
    # recompute the owning customer's missed-pickup suspension threshold.
    container = store.containers[rec["container_id"]]
    if container["status"] == "ACTIVE":
        container["status"] = "LOCKED"
        store.bump(container)
    for visit in store.visits.values():
        if visit["container_id"] == container["id"] and visit["status"] == "SCHEDULED":
            visit["status"] = "SKIPPED"
            visit["skipped_at"] = store.now_iso()
            store.bump(visit)
    customer = store.customers[container["customer_id"]]
    if (
        customer["status"] == "ACTIVE"
        and calc.missed_pickup_count(customer["id"]) >= calc.MISSED_PICKUP_SUSPEND_THRESHOLD
    ):
        customer["status"] = "SUSPENDED"
        store.bump(customer)
    return success(serialize.theft(rec))


@bp.route("/api/theft-incidents/<tid>/dismiss", methods=["POST"])
@require_roles("FieldOpsManager")
def dismiss_theft(tid):
    rec = get_theft(tid)
    body = get_body()
    req_str(body, "note")
    if rec["status"] != "REPORTED":
        raise err("ERR_INVALID_STATE", "Theft incident %s is %s; only REPORTED can be dismissed" % (tid, rec["status"]))
    rec["status"] = "DISMISSED"
    store.bump(rec)
    return success(serialize.theft(rec))


@bp.route("/api/theft-incidents/<tid>/resolve", methods=["POST"])
@require_roles("FieldOpsManager")
def resolve_theft(tid):
    rec = get_theft(tid)
    body = get_body()
    resolution_note = req_str(body, "resolution_note")
    if rec["status"] != "CONFIRMED":
        raise err("ERR_INVALID_STATE", "Theft incident %s is %s; only CONFIRMED can be resolved" % (tid, rec["status"]))
    rec["resolution_note"] = resolution_note
    rec["status"] = "RESOLVED"
    store.bump(rec)
    return success(serialize.theft(rec))


# ---------------------------------------------------------------------------
# Processing batches (PRD 3.9)
# ---------------------------------------------------------------------------
@bp.route("/api/processing-batches", methods=["POST"])
@require_roles("PlantOperator")
def create_batch():
    body = get_body()
    manifest_id = req_str(body, "manifest_id")
    input_gallons = req_num(body, "input_gallons")
    manifest = fk_exists(store.manifests, manifest_id, "manifest_id")
    if manifest["status"] != "RECONCILED":
        raise err("ERR_INVALID_STATE", "Manifest %s is %s; intake requires RECONCILED" % (manifest_id, manifest["status"]))
    if any(b["manifest_id"] == manifest_id for b in store.batches.values()):
        raise err("ERR_INVALID_STATE", "Manifest %s already feeds a processing batch" % manifest_id)
    visit_ids = {v["id"] for v in store.visits.values() if v["manifest_id"] == manifest_id}
    for complaint in store.complaints.values():
        fresh_complaint(complaint)
        if (
            complaint["category"] == "SPILL"
            and complaint["pickup_visit_id"] in visit_ids
            and complaint["status"] in SPILL_BLOCKING
        ):
            raise err("ERR_SPILL_COMPLAINT_OPEN", "An unresolved SPILL complaint blocks intake")
    collected = calc.collected_gallons(manifest_id)
    if Decimal(str(input_gallons)) != Decimal(str(collected)):
        raise err(
            "ERR_BATCH_INPUT_MISMATCH",
            "input_gallons %s must equal the manifest's collected_gallons %s" % (input_gallons, collected),
        )
    weighted = calc.weighted_moisture_pct(manifest_id)
    rec = {
        "id": store.new_id(),
        "manifest_id": manifest_id,
        "input_gallons": input_gallons,
        "weighted_moisture_pct": weighted,
        "est_yield_gallons": calc.est_yield_gallons(input_gallons, weighted),
        "actual_output_gallons": None,
        "yield_rate": None,
        "sale_price_cents_per_gal": None,
        "sale_revenue_cents": None,
        "status": "INTAKE",
    }
    store.stamp(rec)
    store.batches[rec["id"]] = rec
    return success(serialize.batch(rec), code=201)


@bp.route("/api/processing-batches/<bid>/process", methods=["POST"])
@require_roles("PlantOperator")
def process_batch(bid):
    rec = get_batch(bid)
    body = get_body()
    actual_output = req_num(body, "actual_output_gallons")
    if rec["status"] != "INTAKE":
        raise err("ERR_INVALID_STATE", "Batch %s is %s; only INTAKE can be processed" % (bid, rec["status"]))
    rec["actual_output_gallons"] = actual_output
    rec["yield_rate"] = calc.yield_rate(actual_output, rec["input_gallons"])
    rec["status"] = "PROCESSED"
    store.bump(rec)
    return success(serialize.batch(rec))


@bp.route("/api/processing-batches/<bid>/sell", methods=["POST"])
@require_roles("PlantOperator")
def sell_batch(bid):
    rec = get_batch(bid)
    body = get_body()
    sale_price = req_num(body, "sale_price_cents_per_gal")
    if rec["status"] != "PROCESSED":
        raise err("ERR_INVALID_STATE", "Batch %s is %s; only PROCESSED can be sold" % (bid, rec["status"]))
    rec["sale_price_cents_per_gal"] = sale_price
    rec["sale_revenue_cents"] = calc.sale_revenue_cents(rec["actual_output_gallons"], sale_price)
    rec["status"] = "SOLD"
    store.bump(rec)
    return success(serialize.batch(rec))
