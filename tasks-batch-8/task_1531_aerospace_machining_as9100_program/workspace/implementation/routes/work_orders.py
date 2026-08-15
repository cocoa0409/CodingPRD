"""Work order endpoints (plus serial batch creation, SPC, ship-all)."""

from flask import Blueprint, request

from db import db, base_record, public, touch
from errors import (
    ApiError,
    ERR_CHARACTERISTIC_NOT_FOUND,
    ERR_DELEGATION_REQUIRED,
    ERR_FAI_REQUIRED,
    ERR_INSUFFICIENT_MATERIAL_QUANTITY,
    ERR_INVALID_REQUEST,
    ERR_MATERIAL_CERT_NOT_ACCEPTED,
    ERR_MATERIAL_CERT_NOT_FOUND,
    ERR_MATERIAL_CERT_REVOKED,
    ERR_PO_NOT_FOUND,
    ERR_PO_NOT_RELEASED,
    ERR_PROCESS_NOT_APPROVED,
    ERR_QUANTITY_EXCEEDS_UNRELEASED,
    ERR_SERIAL_BATCH_EXCEEDS_QUANTITY,
    ERR_SERIALS_INCOMPLETE,
    ERR_WO_NOT_ACCEPTABLE,
    ERR_WO_NOT_ACCEPTING_SERIALS,
    ERR_WO_NOT_CANCELLABLE,
    ERR_WO_NOT_FOUND,
    ERR_WO_NOT_IN_PRODUCTION,
    ERR_WO_NOT_ON_HOLD,
    ERR_WO_NOT_RELEASABLE,
    ERR_WO_OPEN_NCR,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from services import (
    create_ncr,
    evaluate_characteristic,
    num_out,
    recompute_wo_counters,
    recompute_wo_spc_status,
    ship_serial,
    check_serial_shippable,
    wo_has_open_ncr,
    MIN_MEASUREMENTS,
)
from validate import (
    json_body,
    no_unknown,
    opt_enum_list,
    paginate,
    req_int,
    req_num,
    req_str,
)

bp = Blueprint("work_orders", __name__)

MP = "ManufacturingPlanner"
QI = "QualityInspector"
QM = "QualityManager"
CQR = "CustomerQualityRep"

SPECIAL_PROCESSES = {"HEAT_TREAT", "NDT", "PLATING", "WELDING", "SHOT_PEEN"}


def get_wo(wo_id):
    wo = db.work_orders.get(wo_id)
    if wo is None:
        raise ApiError(ERR_WO_NOT_FOUND, 404, "Work order %s not found" % wo_id)
    return wo


@bp.route("/api/work-orders", methods=["POST"])
def create_wo():
    require_roles(MP)
    data = json_body()
    no_unknown(data, {"po_id", "quantity", "special_processes_required"})
    po_id = req_str(data, "po_id")
    quantity = req_int(data, "quantity", min_val=1)
    processes = opt_enum_list(data, "special_processes_required", SPECIAL_PROCESSES, default=[])

    po = db.purchase_orders.get(po_id)
    if po is None:
        raise ApiError(ERR_PO_NOT_FOUND, 404, "Purchase order %s not found" % po_id)
    if quantity > po["unreleased_quantity"]:
        raise ApiError(
            ERR_QUANTITY_EXCEEDS_UNRELEASED, 422, "quantity exceeds PO unreleased_quantity"
        )

    rec = base_record(db.new_id())
    rec.update(
        {
            "po_id": po["id"],
            "quantity": quantity,
            "special_processes_required": processes,
            "status": "PLANNED",
            "serials_created_count": 0,
            "good_quantity": 0,
            "scrapped_quantity": 0,
            "spc_status": "MONITORING",
            "requires_100pct_inspection": False,
            "completed_at": None,
            "_completed_dt": None,
        }
    )
    db.work_orders[rec["id"]] = rec
    po["unreleased_quantity"] -= quantity
    touch(po)
    return success_object(public(rec), 201)


@bp.route("/api/work-orders", methods=["GET"])
def list_wos():
    require_roles(*ALL_ROLES)
    items = list(db.work_orders.values())
    po_id = request.args.get("po_id")
    status = request.args.get("status")
    if po_id is not None:
        items = [w for w in items if w["po_id"] == po_id]
    if status is not None:
        items = [w for w in items if w["status"] == status]
    items.sort(key=lambda r: (r["_created_dt"], r["_seq"]))
    page, pagination = paginate(items, request.args)
    return success_list(page, pagination)


@bp.route("/api/work-orders/<woId>", methods=["GET"])
def get_one_wo(woId):
    require_roles(*ALL_ROLES)
    return success_object(public(get_wo(woId)))


@bp.route("/api/work-orders/<woId>/release", methods=["POST"])
def release_wo(woId):
    require_roles(MP)
    data = json_body()
    no_unknown(data, set())
    wo = get_wo(woId)
    if wo["status"] != "PLANNED":
        raise ApiError(ERR_WO_NOT_RELEASABLE, 409, "WO release requires PLANNED")
    po = db.purchase_orders.get(wo["po_id"])
    if po is None or po["status"] != "RELEASED":
        raise ApiError(ERR_PO_NOT_RELEASED, 409, "Parent PO is not RELEASED")

    # Airworthiness gates
    if "AS9102_FAI" in po["flowdown_clauses"]:
        approved = any(
            f["status"] == "APPROVED"
            and f["part_number"] == po["part_number"]
            and f["part_revision"] == po["part_revision"]
            for f in db.fais.values()
        )
        if not approved:
            raise ApiError(
                ERR_FAI_REQUIRED,
                422,
                "An APPROVED FAI is required for this part number and revision",
            )
    today = db.today()
    for p in wo["special_processes_required"]:
        covered = False
        for pa in db.process_approvals.values():
            if (
                pa["process_code"] == p
                and pa["status"] == "ACTIVE"
                and pa["_from_d"] <= today < pa["_to_d"]
            ):
                src = db.sources.get(pa["source_id"])
                if src is not None and src["status"] == "APPROVED":
                    covered = True
                    break
        if not covered:
            raise ApiError(
                ERR_PROCESS_NOT_APPROVED,
                422,
                "No in-window ACTIVE approval from an APPROVED source for %s" % p,
            )

    wo["status"] = "RELEASED"
    touch(wo)
    return success_object(public(wo))


@bp.route("/api/work-orders/<woId>/serials", methods=["POST"])
def create_serials(woId):
    require_roles(MP)
    wo = get_wo(woId)
    data = json_body()
    no_unknown(data, {"material_cert_id", "count"})
    cert_id = req_str(data, "material_cert_id")
    count = req_int(data, "count", min_val=1)

    cert = db.material_certs.get(cert_id)
    if cert is None:
        raise ApiError(ERR_MATERIAL_CERT_NOT_FOUND, 404, "Material cert %s not found" % cert_id)
    if wo["status"] not in ("RELEASED", "IN_PRODUCTION"):
        raise ApiError(
            ERR_WO_NOT_ACCEPTING_SERIALS, 409, "WO is not accepting serials"
        )
    if cert["status"] == "REVOKED":
        raise ApiError(ERR_MATERIAL_CERT_REVOKED, 422, "Material cert is REVOKED")
    if cert["status"] != "ACCEPTED":
        raise ApiError(ERR_MATERIAL_CERT_NOT_ACCEPTED, 422, "Material cert is not ACCEPTED")
    if count > cert["quantity_available"]:
        raise ApiError(
            ERR_INSUFFICIENT_MATERIAL_QUANTITY, 422, "Batch exceeds material cert availability"
        )
    if wo["serials_created_count"] + count > wo["quantity"]:
        raise ApiError(
            ERR_SERIAL_BATCH_EXCEEDS_QUANTITY, 422, "Batch exceeds work order quantity"
        )

    created = []
    for i in range(count):
        seq = wo["serials_created_count"] + i + 1
        rec = base_record(db.new_id())
        rec.update(
            {
                "wo_id": wo["id"],
                "material_cert_id": cert["id"],
                "serial_number": "SN-%04d" % seq,
                "status": "CREATED",
                "shipped_at": None,
                "_shipped_dt": None,
            }
        )
        db.serials[rec["id"]] = rec
        created.append(rec)

    cert["quantity_available"] -= count
    touch(cert)
    first_batch = wo["status"] == "RELEASED"
    recompute_wo_counters(wo)
    if first_batch:
        wo["status"] = "IN_PRODUCTION"
    return success_list(
        [public(r) for r in created],
        {"limit": len(created), "offset": 0, "total_count": len(created), "has_more": False},
        201,
    )


@bp.route("/api/work-orders/<woId>/serials", methods=["GET"])
def list_wo_serials(woId):
    require_roles(*ALL_ROLES)
    wo = get_wo(woId)
    items = [s for s in db.serials.values() if s["wo_id"] == wo["id"]]
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    items.sort(key=lambda r: (r["_created_dt"], r["_seq"]))
    page, pagination = paginate(items, request.args)
    return success_list(page, pagination)


@bp.route("/api/work-orders/<woId>/spc-measurements", methods=["POST"])
def create_spc_measurement(woId):
    uid = require_roles(QI)
    wo = get_wo(woId)
    data = json_body()
    no_unknown(data, {"characteristic_id", "measured_value"})
    char_id = req_str(data, "characteristic_id")
    measured = req_num(data, "measured_value")

    char = db.characteristics.get(char_id)
    if char is None:
        raise ApiError(ERR_CHARACTERISTIC_NOT_FOUND, 404, "Characteristic %s not found" % char_id)
    if wo["status"] != "IN_PRODUCTION":
        raise ApiError(ERR_WO_NOT_IN_PRODUCTION, 409, "WO is not IN_PRODUCTION")
    if not char["is_key_characteristic"]:
        raise ApiError(ERR_INVALID_REQUEST, 400, "characteristic is not a key characteristic")

    rec = base_record(db.new_id())
    rec.update(
        {
            "wo_id": wo["id"],
            "characteristic_id": char["id"],
            "measured_value": measured,
            "recorded_by_user_id": uid,
        }
    )
    # SpcMeasurement carries only id + created_at as system fields
    rec.pop("updated_at", None)
    rec.pop("version", None)
    db.spc_measurements[rec["id"]] = rec

    new_status, cpk = evaluate_characteristic(char, wo["id"], final=False)
    if new_status is None:
        if char["spc_eval_status"] != "MONITORING":
            char["spc_eval_status"] = "MONITORING"
            touch(char)
    else:
        char["cpk_provisional"] = float(cpk)
        became_incapable = (
            new_status == "INCAPABLE" and char["spc_eval_status"] != "INCAPABLE"
        )
        char["spc_eval_status"] = new_status
        touch(char)
        if became_incapable:
            wo["requires_100pct_inspection"] = True
            create_ncr(
                wo_id=wo["id"],
                defect_code="SPC_CAPABILITY_LOSS",
                description="Automatic SPC capability-loss report for key characteristic",
                quantity_affected=1,
                affected_serial_ids=[],
                detected_post_shipment=False,
                origin="AUTO_SPC",
                discovered_by_user_id=None,
            )
    recompute_wo_spc_status(wo)
    touch(wo)
    return success_object(public(rec), 201)


@bp.route("/api/work-orders/<woId>/spc-measurements", methods=["GET"])
def list_wo_spc(woId):
    require_roles(*ALL_ROLES)
    wo = get_wo(woId)
    items = [m for m in db.spc_measurements.values() if m["wo_id"] == wo["id"]]
    char_id = request.args.get("characteristic_id")
    if char_id is not None:
        items = [m for m in items if m["characteristic_id"] == char_id]
    items.sort(key=lambda r: (r["_created_dt"], r["_seq"]))
    page, pagination = paginate(items, request.args)
    return success_list(page, pagination)


@bp.route("/api/work-orders/<woId>/complete", methods=["POST"])
def complete_wo(woId):
    require_roles(MP)
    data = json_body()
    no_unknown(data, set())
    wo = get_wo(woId)
    if wo["status"] != "IN_PRODUCTION":
        raise ApiError(ERR_WO_NOT_IN_PRODUCTION, 409, "WO complete requires IN_PRODUCTION")
    if wo["serials_created_count"] != wo["quantity"]:
        raise ApiError(ERR_SERIALS_INCOMPLETE, 422, "Serial count is incomplete")
    if wo_has_open_ncr(wo["id"]):
        raise ApiError(ERR_WO_OPEN_NCR, 409, "WO has an open NCR")

    # Freeze final (population-stddev) capability per key characteristic
    char_ids = []
    for m in db.spc_measurements.values():
        if m["wo_id"] == wo["id"] and m["characteristic_id"] not in char_ids:
            char_ids.append(m["characteristic_id"])
    for cid in char_ids:
        char = db.characteristics.get(cid)
        if char is None:
            continue
        new_status, cpk = evaluate_characteristic(char, wo["id"], final=True)
        if cpk is not None:
            char["cpk_final"] = float(cpk)
            touch(char)

    wo["status"] = "FINAL_INSPECTION"
    touch(wo)
    return success_object(public(wo))


@bp.route("/api/work-orders/<woId>/accept", methods=["POST"])
def accept_wo(woId):
    uid = require_roles(CQR, QI)
    data = json_body()
    no_unknown(data, set())
    wo = get_wo(woId)
    if wo["status"] != "FINAL_INSPECTION":
        raise ApiError(ERR_WO_NOT_ACCEPTABLE, 409, "WO accept requires FINAL_INSPECTION")
    role = request.headers.get("X-User-Role")
    if role == QI:
        today = db.today()
        delegated = any(
            d["po_id"] == wo["po_id"]
            and d["inspector_user_id"] == uid
            and d["status"] == "ACTIVE"
            and d["_from_d"] <= today <= d["_to_d"]
            for d in db.delegations.values()
        )
        if not delegated:
            raise ApiError(
                ERR_DELEGATION_REQUIRED,
                403,
                "Inspector lacks an ACTIVE in-window delegation for this PO",
            )
    wo["status"] = "COMPLETED"
    wo["completed_at"] = db.now_iso()
    wo["_completed_dt"] = db.now()
    touch(wo)
    return success_object(public(wo))


@bp.route("/api/work-orders/<woId>/cancel", methods=["POST"])
def cancel_wo(woId):
    require_roles(MP)
    data = json_body()
    no_unknown(data, set())
    wo = get_wo(woId)
    if wo["status"] not in ("PLANNED", "RELEASED"):
        raise ApiError(ERR_WO_NOT_CANCELLABLE, 409, "WO cancel requires PLANNED or RELEASED")
    wo["status"] = "CANCELLED"
    touch(wo)
    po = db.purchase_orders.get(wo["po_id"])
    if po is not None:
        po["unreleased_quantity"] += wo["quantity"]
        touch(po)
    return success_object(public(wo))


@bp.route("/api/work-orders/<woId>/release-hold", methods=["POST"])
def release_hold(woId):
    require_roles(QM)
    data = json_body()
    no_unknown(data, set())
    wo = get_wo(woId)
    if wo["status"] != "QUALITY_HOLD":
        raise ApiError(ERR_WO_NOT_ON_HOLD, 409, "WO is not on QUALITY_HOLD")
    if any(s["wo_id"] == wo["id"] and s["status"] == "QUARANTINED" for s in db.serials.values()):
        raise ApiError(ERR_WO_OPEN_NCR, 409, "WO has quarantined serials")
    if wo_has_open_ncr(wo["id"]):
        raise ApiError(ERR_WO_OPEN_NCR, 409, "WO has an open NCR")
    wo["status"] = "IN_PRODUCTION"
    touch(wo)
    return success_object(public(wo))


@bp.route("/api/work-orders/<woId>/ship-all", methods=["POST"])
def ship_all(woId):
    require_roles(MP)
    data = json_body()
    no_unknown(data, set())
    wo = get_wo(woId)
    if wo["status"] != "COMPLETED":
        raise ApiError(ERR_WO_NOT_ACCEPTABLE, 409, "ship-all requires a COMPLETED work order")
    created = [
        s
        for s in db.serials.values()
        if s["wo_id"] == wo["id"] and s["status"] == "CREATED"
    ]
    created.sort(key=lambda r: (r["_created_dt"], r["_seq"]))
    # Atomic: every CREATED serial must pass ship preconditions before any ships
    for s in created:
        check_serial_shippable(s)
    po = db.purchase_orders.get(wo["po_id"])
    for s in created:
        s["status"] = "SHIPPED"
        s["shipped_at"] = db.now_iso()
        s["_shipped_dt"] = db.now()
        touch(s)
        if po is not None:
            po["delivered_quantity"] += 1
    if po is not None and created:
        if po["delivered_quantity"] == po["quantity"] and po["status"] == "RELEASED":
            po["status"] = "CLOSED"
            po["_closed_dt"] = db.now()
        touch(po)
    return success_list(
        [public(s) for s in created],
        {"limit": len(created), "offset": 0, "total_count": len(created), "has_more": False},
    )
