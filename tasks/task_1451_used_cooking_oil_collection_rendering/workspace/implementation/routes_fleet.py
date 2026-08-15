"""Routes: trucks, route manifests, pickup visits, quality samples
(PRD 3.4, 3.5, 3.6)."""

from flask import Blueprint, g

import calc
import serialize
from db import parse_date, store
from errors import err
from helpers import (
    cc_check,
    forbid_role,
    fk_exists,
    get_container,
    get_manifest,
    get_sample,
    get_truck,
    get_visit,
    get_body,
    paginate,
    req_date,
    req_enum,
    req_int,
    req_num,
    req_str,
    req_str_list,
    require_roles,
    sorted_items,
)
from response import success

bp = Blueprint("fleet", __name__)

TRUCK_STATUSES = {"IN_SERVICE", "OUT_OF_SERVICE"}
VISIT_TERMINAL_FOR_ROUTE = {"COMPLETED", "SKIPPED", "VOID"}


# ---------------------------------------------------------------------------
# Trucks (PRD 3.4)
# ---------------------------------------------------------------------------
@bp.route("/api/trucks", methods=["POST"])
@require_roles("SystemAdmin", "RouteDispatcher")
def create_truck():
    body = get_body()
    plate = req_str(body, "plate")
    tank_capacity = req_num(body, "tank_capacity_gallons")
    if any(t["plate"] == plate for t in store.trucks.values()):
        raise err("ERR_VALIDATION", "plate '%s' is already registered" % plate)
    rec = {
        "id": store.new_id(),
        "plate": plate,
        "tank_capacity_gallons": tank_capacity,
        "status": "IN_SERVICE",
    }
    store.stamp(rec)
    store.trucks[rec["id"]] = rec
    return success(serialize.truck(rec), code=201)


@bp.route("/api/trucks/<tid>", methods=["GET"])
@require_roles("SystemAdmin", "FieldOpsManager", "RouteDispatcher", "Driver")
def get_one_truck(tid):
    return success(serialize.truck(get_truck(tid)))


@bp.route("/api/trucks/<tid>/service-status", methods=["POST"])
@require_roles("RouteDispatcher")
def set_truck_status(tid):
    rec = get_truck(tid)
    body = get_body()
    status = req_enum(body, "status", TRUCK_STATUSES)
    rec["status"] = status
    store.bump(rec)
    return success(serialize.truck(rec))


@bp.route("/api/trucks/<tid>/manifests", methods=["GET"])
@require_roles("SystemAdmin", "RouteDispatcher", "Driver")
def list_truck_manifests(tid):
    get_truck(tid)
    items = [m for m in sorted_items(store.manifests.values()) if m["truck_id"] == tid]
    page, meta = paginate(items)
    return success([serialize.manifest(m) for m in page], response_type="array", pagination=meta)


# ---------------------------------------------------------------------------
# Route manifests (PRD 3.4)
# ---------------------------------------------------------------------------
def _create_visits(manifest):
    for cid in manifest["container_ids"]:
        v = {
            "id": store.new_id(),
            "manifest_id": manifest["id"],
            "container_id": cid,
            "scheduled_date": manifest["service_date"],
            "status": "SCHEDULED",
            "pump_gallons": None,
            "field_moisture_pct": None,
            "net_gallons_provisional": None,
            "retry_count": 0,
            "failure_reason": None,
            "void_reason": None,
            "skipped_at": None,
            "completed_at": None,
        }
        store.stamp(v)
        store.visits[v["id"]] = v


@bp.route("/api/route-manifests", methods=["POST"])
@require_roles("RouteDispatcher")
def create_manifest():
    body = get_body()
    truck_id = req_str(body, "truck_id")
    driver_ref = req_str(body, "driver_ref")
    service_date = req_date(body, "service_date")
    container_ids = req_str_list(body, "container_ids")
    fk_exists(store.trucks, truck_id, "truck_id")
    for cid in container_ids:
        fk_exists(store.containers, cid, "container_ids")
    if any(
        m["truck_id"] == truck_id and m["service_date"] == service_date
        for m in store.manifests.values()
    ):
        raise err(
            "ERR_MANIFEST_DATE_CONFLICT",
            "Truck %s already has a manifest on %s" % (truck_id, service_date),
        )
    rec = {
        "id": store.new_id(),
        "truck_id": truck_id,
        "driver_ref": driver_ref,
        "service_date": service_date,
        "status": "DRAFT",
        "projected_fill_gallons": calc.projected_fill(container_ids),
        "start_level_gallons": None,
        "end_level_gallons": None,
        "spill_loss_gallons": 0,
        "container_ids": list(container_ids),
    }
    store.stamp(rec)
    store.manifests[rec["id"]] = rec
    _create_visits(rec)
    return success(serialize.manifest(rec), code=201)


@bp.route("/api/route-manifests/<mid>", methods=["GET"])
@require_roles("SystemAdmin", "FieldOpsManager", "RouteDispatcher", "Driver", "PlantOperator")
def get_one_manifest(mid):
    return success(serialize.manifest(get_manifest(mid)))


@bp.route("/api/route-manifests/<mid>", methods=["PATCH"])
@require_roles("RouteDispatcher")
def patch_manifest(mid):
    rec = get_manifest(mid)
    body = get_body()
    expected = req_int(body, "expected_manifest_version")
    container_ids = req_str_list(body, "container_ids")
    for cid in container_ids:
        fk_exists(store.containers, cid, "container_ids")
    if rec["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Manifest %s is %s; only DRAFT can be re-planned" % (mid, rec["status"]))
    if expected != rec["version"]:
        raise err("ERR_STALE_VERSION", "expected_manifest_version %s != current %s" % (expected, rec["version"]))
    stale = [
        vid for vid, v in store.visits.items()
        if v["manifest_id"] == mid and v["status"] == "SCHEDULED"
    ]
    for vid in stale:
        del store.visits[vid]
    rec["container_ids"] = list(container_ids)
    rec["projected_fill_gallons"] = calc.projected_fill(container_ids)
    _create_visits(rec)
    store.bump(rec)
    return success(serialize.manifest(rec))


@bp.route("/api/route-manifests/<mid>/dispatch", methods=["POST"])
@require_roles("RouteDispatcher")
def dispatch_manifest(mid):
    rec = get_manifest(mid)
    body = get_body()
    start_level = req_num(body, "start_level_gallons")
    if rec["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Manifest %s is %s; only DRAFT can dispatch" % (mid, rec["status"]))
    containers = [store.containers[cid] for cid in rec["container_ids"]]
    for cont in containers:
        if cont["status"] not in ("PLACED", "ACTIVE"):
            raise err(
                "ERR_INVALID_STATE",
                "Stop container %s is %s; dispatch requires PLACED or ACTIVE" % (cont["id"], cont["status"]),
            )
    for cont in containers:
        customer = store.customers[cont["customer_id"]]
        if customer["status"] == "SUSPENDED":
            raise err("ERR_CUSTOMER_SUSPENDED", "Stop customer %s is SUSPENDED" % customer["id"])
    truck = store.trucks[rec["truck_id"]]
    if truck["status"] != "IN_SERVICE":
        raise err("ERR_TRUCK_UNAVAILABLE", "Truck %s is %s" % (truck["id"], truck["status"]))
    if calc.D(rec["projected_fill_gallons"]) > calc.D(truck["tank_capacity_gallons"]):
        raise err(
            "ERR_TANK_CAPACITY_EXCEEDED",
            "Projected fill %s exceeds tank capacity %s"
            % (rec["projected_fill_gallons"], truck["tank_capacity_gallons"]),
        )
    rec["start_level_gallons"] = start_level
    rec["status"] = "DISPATCHED"
    for cont in containers:
        if cont["status"] == "PLACED":
            cont["status"] = "ACTIVE"
            store.bump(cont)
    store.bump(rec)
    return success(serialize.manifest(rec))


@bp.route("/api/route-manifests/<mid>/complete", methods=["POST"])
@require_roles("Driver")
def complete_manifest(mid):
    rec = get_manifest(mid)
    if g.user_id != rec["driver_ref"]:
        raise forbid_role("Only the assigned driver may close this route")
    if rec["status"] not in ("DISPATCHED", "IN_PROGRESS"):
        raise err("ERR_INVALID_STATE", "Manifest %s is %s; complete requires DISPATCHED or IN_PROGRESS" % (mid, rec["status"]))
    open_visits = [
        v for v in store.visits.values()
        if v["manifest_id"] == mid and v["status"] not in VISIT_TERMINAL_FOR_ROUTE
    ]
    if open_visits:
        raise err("ERR_INVALID_STATE", "Manifest %s still has non-terminal visits" % mid)
    rec["status"] = "COMPLETED"
    store.bump(rec)
    return success(serialize.manifest(rec))


@bp.route("/api/route-manifests/<mid>/reconcile", methods=["POST"])
@require_roles("RouteDispatcher")
def reconcile_manifest(mid):
    rec = get_manifest(mid)
    body = get_body()
    end_level = req_num(body, "end_level_gallons")
    spill = req_num(body, "spill_loss_gallons") if body.get("spill_loss_gallons") is not None else 0
    if rec["status"] != "COMPLETED":
        raise err("ERR_INVALID_STATE", "Manifest %s is %s; reconcile requires COMPLETED" % (mid, rec["status"]))
    if not calc.tank_conservation_ok(rec, end_level, spill):
        raise err(
            "ERR_TANK_IMBALANCE",
            "End level %s deviates from expected tank conservation by more than 0.5 gal" % end_level,
        )
    rec["end_level_gallons"] = end_level
    rec["spill_loss_gallons"] = spill
    rec["status"] = "RECONCILED"
    store.bump(rec)
    return success(serialize.manifest(rec))


@bp.route("/api/route-manifests/<mid>/pickup-visits", methods=["GET"])
@require_roles("SystemAdmin", "FieldOpsManager", "RouteDispatcher", "Driver")
def list_manifest_visits(mid):
    get_manifest(mid)
    items = [v for v in sorted_items(store.visits.values()) if v["manifest_id"] == mid]
    page, meta = paginate(items)
    return success([serialize.visit(v) for v in page], response_type="array", pagination=meta)


@bp.route("/api/route-manifests/<mid>/processing-batches", methods=["GET"])
@require_roles("SystemAdmin", "RouteDispatcher", "PlantOperator")
def list_manifest_batches(mid):
    get_manifest(mid)
    items = [b for b in sorted_items(store.batches.values()) if b["manifest_id"] == mid]
    page, meta = paginate(items)
    return success([serialize.batch(b) for b in page], response_type="array", pagination=meta)


# ---------------------------------------------------------------------------
# Pickup visits (PRD 3.5)
# ---------------------------------------------------------------------------
def _visit_and_manifest(vid):
    visit = get_visit(vid)
    return visit, store.manifests[visit["manifest_id"]]


def _driver_owns(manifest):
    if g.user_id != manifest["driver_ref"]:
        raise forbid_role("Driver %s is not the assigned driver of this route" % g.user_id)


@bp.route("/api/pickup-visits/<vid>", methods=["GET"])
@require_roles("SystemAdmin", "FieldOpsManager", "RouteDispatcher", "Driver", "BillingAnalyst", "CustomerContact")
def get_one_visit(vid):
    rec = get_visit(vid)
    if g.role == "CustomerContact":
        cc_check(store.containers[rec["container_id"]]["customer_id"])
    return success(serialize.visit(rec))


@bp.route("/api/pickup-visits/<vid>/start", methods=["POST"])
@require_roles("Driver")
def start_visit(vid):
    rec, manifest = _visit_and_manifest(vid)
    _driver_owns(manifest)
    if rec["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Visit %s is %s; only SCHEDULED can start" % (vid, rec["status"]))
    if manifest["status"] not in ("DISPATCHED", "IN_PROGRESS"):
        raise err("ERR_INVALID_STATE", "Manifest is %s; visits start only once DISPATCHED" % manifest["status"])
    rec["status"] = "EN_ROUTE"
    store.bump(rec)
    if manifest["status"] == "DISPATCHED":
        manifest["status"] = "IN_PROGRESS"
        store.bump(manifest)
    return success(serialize.visit(rec))


@bp.route("/api/pickup-visits/<vid>/complete", methods=["POST"])
@require_roles("Driver")
def complete_visit(vid):
    rec, manifest = _visit_and_manifest(vid)
    _driver_owns(manifest)
    body = get_body()
    pump = req_num(body, "pump_gallons", strict_gt=0)
    moisture = req_num(body, "field_moisture_pct", min_v=0, max_v=100)
    if rec["status"] != "EN_ROUTE":
        raise err("ERR_INVALID_STATE", "Visit %s is %s; only EN_ROUTE can complete" % (vid, rec["status"]))
    cont = store.containers[rec["container_id"]]
    if cont["status"] == "LOCKED":
        raise err("ERR_CONTAINER_LOCKED", "Container %s is LOCKED" % cont["id"])
    if cont["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Container %s is %s; complete requires ACTIVE" % (cont["id"], cont["status"]))
    if calc.D(pump) > calc.D(cont["capacity_gallons"]):
        raise err(
            "ERR_CONTAINER_CAPACITY_EXCEEDED",
            "pump_gallons %s exceeds container capacity %s" % (pump, cont["capacity_gallons"]),
        )
    if store.clock_date() < parse_date(rec["scheduled_date"]):
        raise err(
            "ERR_PICKUP_WINDOW_FUTURE",
            "Visit %s is scheduled for %s" % (vid, rec["scheduled_date"]),
        )
    rec["pump_gallons"] = pump
    rec["field_moisture_pct"] = moisture
    rec["net_gallons_provisional"] = calc.net_provisional(pump, moisture)
    rec["completed_at"] = store.now_iso()
    rec["status"] = "COMPLETED"
    cont["last_completed_pickup_date"] = rec["scheduled_date"]
    store.bump(cont)
    store.bump(rec)
    return success(serialize.visit(rec))


@bp.route("/api/pickup-visits/<vid>/fail", methods=["POST"])
@require_roles("Driver")
def fail_visit(vid):
    rec, manifest = _visit_and_manifest(vid)
    _driver_owns(manifest)
    body = get_body()
    reason = req_str(body, "reason")
    if rec["status"] != "EN_ROUTE":
        raise err("ERR_INVALID_STATE", "Visit %s is %s; only EN_ROUTE can fail" % (vid, rec["status"]))
    # EN_ROUTE -> FAILED -> SCHEDULED is a single atomic fail-and-retry (PRD 3.5).
    rec["failure_reason"] = reason
    rec["retry_count"] += 1
    rec["status"] = "SCHEDULED"
    store.bump(rec)
    return success(serialize.visit(rec))


@bp.route("/api/pickup-visits/<vid>/void", methods=["POST"])
@require_roles("RouteDispatcher")
def void_visit(vid):
    rec, manifest = _visit_and_manifest(vid)
    body = get_body()
    reason = req_str(body, "reason")
    if rec["status"] != "COMPLETED":
        raise err("ERR_INVALID_STATE", "Visit %s is %s; only COMPLETED can be voided" % (vid, rec["status"]))
    if manifest["status"] not in ("DISPATCHED", "IN_PROGRESS", "COMPLETED"):
        raise err("ERR_INVALID_STATE", "Manifest is %s; void is no longer possible" % manifest["status"])
    rec["void_reason"] = reason
    rec["status"] = "VOID"
    store.bump(rec)
    # Compensating side effects: drop PROVISIONAL settlement lines for the visit.
    affected = {
        line["settlement_id"]
        for line in store.lines.values()
        if line["pickup_visit_id"] == vid
    }
    for sid in sorted(affected):
        settlement = store.settlements[sid]
        if settlement["status"] != "PROVISIONAL":
            continue
        doomed = [
            lid for lid, line in store.lines.items()
            if line["settlement_id"] == sid and line["pickup_visit_id"] == vid
        ]
        for lid in doomed:
            del store.lines[lid]
        settlement["provisional_total_cents"] = sum(
            line["line_amount_cents"]
            for line in store.lines.values()
            if line["settlement_id"] == sid
        )
        store.bump(settlement)
    # Recompute the container's last completed pickup date from what remains.
    cont = store.containers[rec["container_id"]]
    remaining = [
        v["scheduled_date"]
        for v in store.visits.values()
        if v["container_id"] == cont["id"] and v["status"] == "COMPLETED"
    ]
    new_last = max(remaining) if remaining else None
    if cont["last_completed_pickup_date"] != new_last:
        cont["last_completed_pickup_date"] = new_last
        store.bump(cont)
    return success(serialize.visit(rec))


# ---------------------------------------------------------------------------
# Quality samples (PRD 3.6)
# ---------------------------------------------------------------------------
@bp.route("/api/pickup-visits/<vid>/samples", methods=["POST"])
@require_roles("Driver")
def draw_sample(vid):
    get_visit(vid)
    rec = {
        "id": store.new_id(),
        "pickup_visit_id": vid,
        "status": "COLLECTED",
        "lab_moisture_pct": None,
        "lab_impurity_pct": None,
        "grade": None,
        "dispute_note": None,
    }
    store.stamp(rec)
    store.samples[rec["id"]] = rec
    return success(serialize.sample(rec), code=201)


@bp.route("/api/pickup-visits/<vid>/samples", methods=["GET"])
@require_roles("SystemAdmin", "FieldOpsManager", "Driver", "PlantOperator", "BillingAnalyst")
def list_visit_samples(vid):
    get_visit(vid)
    items = [s for s in sorted_items(store.samples.values()) if s["pickup_visit_id"] == vid]
    page, meta = paginate(items)
    return success([serialize.sample(s) for s in page], response_type="array", pagination=meta)


@bp.route("/api/pickup-visits/<vid>/settlement-lines", methods=["GET"])
@require_roles("SystemAdmin", "BillingAnalyst", "CustomerContact")
def list_visit_lines(vid):
    rec = get_visit(vid)
    if g.role == "CustomerContact":
        cc_check(store.containers[rec["container_id"]]["customer_id"])
    items = [l for l in sorted_items(store.lines.values()) if l["pickup_visit_id"] == vid]
    page, meta = paginate(items)
    return success([serialize.line(l) for l in page], response_type="array", pagination=meta)


@bp.route("/api/pickup-visits/<vid>/complaints", methods=["GET"])
@require_roles("SystemAdmin", "FieldOpsManager", "CustomerContact")
def list_visit_complaints(vid):
    from helpers import fresh_complaint

    rec = get_visit(vid)
    if g.role == "CustomerContact":
        cc_check(store.containers[rec["container_id"]]["customer_id"])
    items = [fresh_complaint(c) for c in sorted_items(store.complaints.values()) if c["pickup_visit_id"] == vid]
    page, meta = paginate(items)
    return success([serialize.complaint(c) for c in page], response_type="array", pagination=meta)


@bp.route("/api/quality-samples/<sid>/submit", methods=["POST"])
@require_roles("Driver")
def submit_sample(sid):
    rec = get_sample(sid)
    if rec["status"] != "COLLECTED":
        raise err("ERR_INVALID_STATE", "Sample %s is %s; only COLLECTED can be submitted" % (sid, rec["status"]))
    rec["status"] = "SUBMITTED"
    store.bump(rec)
    return success(serialize.sample(rec))


@bp.route("/api/quality-samples/<sid>/grade", methods=["POST"])
@require_roles("PlantOperator")
def grade_sample(sid):
    rec = get_sample(sid)
    body = get_body()
    moisture = req_num(body, "lab_moisture_pct", min_v=0, max_v=100)
    impurity = req_num(body, "lab_impurity_pct", min_v=0, max_v=100)
    if rec["status"] == "GRADED":
        raise err("ERR_SAMPLE_ALREADY_GRADED", "Sample %s is already GRADED; dispute it first" % sid)
    if rec["status"] not in ("SUBMITTED", "DISPUTED"):
        raise err("ERR_INVALID_STATE", "Sample %s is %s; grade requires SUBMITTED or DISPUTED" % (sid, rec["status"]))
    rec["lab_moisture_pct"] = moisture
    rec["lab_impurity_pct"] = impurity
    rec["grade"] = calc.assign_grade(moisture, impurity)
    rec["status"] = "GRADED"
    store.bump(rec)
    return success(serialize.sample(rec))


@bp.route("/api/quality-samples/<sid>/dispute", methods=["POST"])
@require_roles("FieldOpsManager")
def dispute_sample(sid):
    rec = get_sample(sid)
    body = get_body()
    note = req_str(body, "note")
    if rec["status"] != "GRADED":
        raise err("ERR_INVALID_STATE", "Sample %s is %s; only GRADED can be disputed" % (sid, rec["status"]))
    rec["dispute_note"] = note
    rec["status"] = "DISPUTED"
    store.bump(rec)
    return success(serialize.sample(rec))
