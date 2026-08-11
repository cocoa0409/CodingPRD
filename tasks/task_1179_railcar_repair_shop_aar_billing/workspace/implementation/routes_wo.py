"""Work orders and repair lines (PRD 3.3, 3.4, 3.5)."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, g, request

import db
from errors import ApiError
from common import (
    auth, ok, get_body, req_str, req_int, invalid_request,
    base_fields, touch, get_or_404, ref_or_404, public, sort_items,
    list_response, now, now_iso, parse_dt, hours_between,
    resolve_price_entry, estimate_line, final_line_pricing,
    determine_line_responsibility, compute_wo_responsibility,
    dwell_projected, shop_posture, part_available,
    ROUTINGS,
)
import billing_ops

bp = Blueprint("wo", __name__)


def wo_out(w):
    return public(w)


def line_out(l):
    return public(l)


def wo_lines(wo_id):
    return [l for l in db.STORE["repair_lines"].values()
            if l["work_order_id"] == wo_id]


def live_lines(wo_id):
    return [l for l in wo_lines(wo_id) if l["status"] != "CANCELLED"]


def recompute_wo_estimate_total(wo):
    wo["estimate_total_cents"] = sum(
        l["estimate_total_cents"] for l in wo_lines(wo["id"])
        if l["status"] != "CANCELLED")


def cancel_lines_and_findings(wo):
    """Compensation: lines ESTIMATED/AUTHORIZED -> CANCELLED; referenced
    findings return ESTIMATED/AUTHORIZED -> OPEN."""
    for line in wo_lines(wo["id"]):
        if line["status"] in ("ESTIMATED", "AUTHORIZED"):
            line["status"] = "CANCELLED"
            touch(line)
            defect = db.STORE["defects"].get(line["defect_finding_id"])
            if defect is not None and defect["status"] in ("ESTIMATED", "AUTHORIZED"):
                defect["status"] = "OPEN"
                touch(defect)


def release_reservations(wo):
    for line in wo_lines(wo["id"]):
        for p in (line["planned_parts"] or []):
            part = db.STORE["parts"].get(p["part_item_id"])
            if part is not None:
                part["reserved_qty"] -= p["quantity"]
                touch(part)


def release_slot(wo):
    if wo.get("assigned_slot_id"):
        slot = db.STORE["shop_slots"].get(wo["assigned_slot_id"])
        if slot is not None and slot["status"] in ("RESERVED", "OCCUPIED"):
            slot["status"] = "RELEASED"
            slot["reserved_work_order_id"] = None
            touch(slot)


# ---------------------------------------------------------------------------
# Work order CRUD and lines
# ---------------------------------------------------------------------------

@bp.post("/work-orders")
@auth("RepairForeman")
def create_work_order():
    body = get_body()
    railcar = ref_or_404("railcars", req_str(body, "railcar_id"), "Railcar")
    inspection = ref_or_404("inspections", req_str(body, "inspection_id"), "Inspection")
    if inspection["railcar_id"] != railcar["id"]:
        raise ApiError("ERR_REFERENCE_NOT_FOUND", 404,
                       "inspection_id does not belong to this railcar")
    if "routing" not in body or body["routing"] not in ROUTINGS:
        raise invalid_request("routing must be SHOP or MOBILE")
    expected = req_int(body, "expected_railcar_version")
    if expected != railcar["version"]:
        raise ApiError("ERR_STALE_RAILCAR_VERSION", 412,
                       "expected_railcar_version does not match the railcar's current version")
    if inspection["status"] != "COMPLETED":
        raise ApiError("ERR_INSPECTION_NOT_COMPLETED", 409,
                       "Work order requires a COMPLETED inspection")
    shop = db.STORE["shops"].get(railcar["shop_id"])
    if shop is not None and shop_posture(shop) == "FULL":
        raise ApiError("ERR_SHOP_AT_CAPACITY", 409,
                       "Shop is at capacity for the current day")

    # Supersede an existing DRAFT work order on this railcar.
    for w in db.STORE["work_orders"].values():
        if w["railcar_id"] == railcar["id"] and w["auth_status"] == "DRAFT":
            w["auth_status"] = "CANCELLED"
            w["exec_status"] = "CANCELLED"
            cancel_lines_and_findings(w)
            touch(w)

    wo = base_fields()
    wo.update({
        "railcar_id": railcar["id"],
        "inspection_id": inspection["id"],
        "routing": body["routing"],
        "auth_status": "DRAFT",
        "exec_status": "NOT_STARTED",
        "responsible_party": None,
        "owner_share_pct": None,
        "estimate_total_cents": 0,
        "final_total_cents": None,
        "assigned_slot_id": None,
        "mobile_crew_id": None,
        "created_by_user_id": g.user_id,
        "authorized_at": None,
        "completed_at": None,
        "qa_review_entered_at": None,
        "rework_count": 0,
    })
    db.STORE["work_orders"][wo["id"]] = wo
    touch(railcar)
    return ok(wo_out(wo), code=201)


@bp.get("/work-orders")
@auth("Any")
def list_work_orders():
    items = list(db.STORE["work_orders"].values())
    for name in ("railcar_id", "inspection_id", "assigned_slot_id",
                 "auth_status", "exec_status"):
        v = request.args.get(name)
        if v is not None:
            items = [w for w in items if w[name] == v]
    return list_response([wo_out(w) for w in sort_items(items)])


@bp.get("/work-orders/<wid>")
@auth("Any")
def get_work_order(wid):
    return ok(wo_out(get_or_404("work_orders", wid, "WorkOrder")))


@bp.post("/work-orders/<wid>/lines")
@auth("RepairForeman")
def add_line(wid):
    wo = get_or_404("work_orders", wid, "WorkOrder")
    body = get_body()
    defect = ref_or_404("defects", req_str(body, "defect_finding_id"), "DefectFinding")
    if defect["inspection_id"] != wo["inspection_id"]:
        raise ApiError("ERR_REFERENCE_NOT_FOUND", 404,
                       "defect_finding_id does not belong to the work order's inspection")
    job_code = req_str(body, "job_code")
    planned_parts = body.get("planned_parts") or []
    if not isinstance(planned_parts, list):
        raise invalid_request("planned_parts must be a list")
    norm_parts = []
    for p in planned_parts:
        if not isinstance(p, dict):
            raise invalid_request("planned_parts entries must be objects")
        part = ref_or_404("parts", p.get("part_item_id"), "PartItem")
        qty = p.get("quantity")
        if not isinstance(qty, int) or isinstance(qty, bool) or qty <= 0:
            raise invalid_request("planned_parts quantity must be a positive integer")
        norm_parts.append({"part_item_id": part["id"], "quantity": qty})
    if wo["auth_status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Repair lines can only be added while the work order is DRAFT")
    if defect["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Only an OPEN finding can be referenced by a new line")
    railcar = db.STORE["railcars"][wo["railcar_id"]]
    entry = resolve_price_entry(railcar["shop_id"], job_code, now().date())
    if entry is None:
        raise ApiError("ERR_PRICE_MASTER_GAP", 422,
                       "No price master entry effective for job_code %s" % job_code)
    labor, material, total = estimate_line(norm_parts, entry)
    line = base_fields()
    line.update({
        "work_order_id": wo["id"],
        "defect_finding_id": defect["id"],
        "job_code": job_code,
        "price_master_entry_id": entry["id"],
        "planned_parts": norm_parts,
        "actual_labor_hours": None,
        "actual_parts": None,
        "estimate_labor_cents": labor,
        "estimate_material_cents": material,
        "estimate_total_cents": total,
        "final_labor_cents": None,
        "final_material_cents": None,
        "final_total_cents": None,
        "responsible_party": None,
        "owner_pct": None,
        "status": "ESTIMATED",
    })
    db.STORE["repair_lines"][line["id"]] = line
    defect["status"] = "ESTIMATED"
    touch(defect)
    recompute_wo_estimate_total(wo)
    touch(wo)
    return ok(line_out(line), code=201)


@bp.get("/work-orders/<wid>/lines")
@auth("Any")
def list_wo_lines(wid):
    wo = get_or_404("work_orders", wid, "WorkOrder")
    return list_response([line_out(l) for l in sort_items(wo_lines(wo["id"]))])


@bp.get("/repair-lines/<lid>")
@auth("Any")
def get_repair_line(lid):
    return ok(line_out(get_or_404("repair_lines", lid, "RepairLine")))


@bp.get("/repair-lines")
@auth("Any")
def list_repair_lines():
    items = list(db.STORE["repair_lines"].values())
    for name in ("price_master_entry_id", "defect_finding_id", "status"):
        v = request.args.get(name)
        if v is not None:
            items = [l for l in items if l[name] == v]
    return list_response([line_out(l) for l in sort_items(items)])


# ---------------------------------------------------------------------------
# Submission and authorization (PRD 3.3, 3.4)
# ---------------------------------------------------------------------------

@bp.post("/work-orders/<wid>/submit")
@auth("RepairForeman")
def submit_work_order(wid):
    wo = get_or_404("work_orders", wid, "WorkOrder")
    get_body(required=False)
    if wo["auth_status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Only a DRAFT work order can be submitted")
    inspection = db.STORE["inspections"][wo["inspection_id"]]
    if inspection["status"] != "COMPLETED":
        raise ApiError("ERR_INSPECTION_NOT_COMPLETED", 409,
                       "Source inspection is no longer COMPLETED")
    lines = wo_lines(wo["id"])
    if not lines:
        raise ApiError("ERR_WORK_ORDER_NO_LINES", 409,
                       "Submit requires at least one repair line")
    railcar = db.STORE["railcars"][wo["railcar_id"]]
    if wo["routing"] == "MOBILE":
        for line in lines:
            entry = db.STORE["price_entries"][line["price_master_entry_id"]]
            if not entry["mobile_eligible"]:
                raise ApiError("ERR_MOBILE_ROUTE_NOT_ELIGIBLE", 409,
                               "A line's price entry is not mobile_eligible")
    for line in lines:
        entry = db.STORE["price_entries"][line["price_master_entry_id"]]
        defect = db.STORE["defects"][line["defect_finding_id"]]
        party, pct = determine_line_responsibility(defect, entry, railcar, inspection)
        line["responsible_party"] = party
        line["owner_pct"] = pct
        touch(line)
    party, share = compute_wo_responsibility(wo)
    wo["responsible_party"] = party
    wo["owner_share_pct"] = share
    wo["auth_status"] = "PENDING_AUTHORIZATION"
    touch(wo)
    return ok(wo_out(wo))


@bp.post("/work-orders/<wid>/authorize")
@auth("CarOwnerRep", "HandlingLineRep")
def authorize_work_order(wid):
    wo = get_or_404("work_orders", wid, "WorkOrder")
    body = get_body()
    billing_ops.party_match_or_403(wo)
    expected = req_int(body, "expected_work_order_version")
    if expected != wo["version"]:
        raise ApiError("ERR_STALE_WORK_ORDER_VERSION", 412,
                       "expected_work_order_version does not match the work order's current version")
    if wo["auth_status"] != "PENDING_AUTHORIZATION":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Only a PENDING_AUTHORIZATION work order can be authorized")
    # Parts availability is checked for every planned part before any
    # reservation is made (atomic).
    planned = []
    for line in live_lines(wo["id"]):
        for p in (line["planned_parts"] or []):
            part = db.STORE["parts"].get(p["part_item_id"])
            if part is None:
                raise ApiError("ERR_REFERENCE_NOT_FOUND", 404,
                               "PartItem %s does not exist" % p["part_item_id"])
            planned.append((part, p["quantity"]))
    for part, qty in planned:
        if part_available(part) < qty:
            raise ApiError("ERR_PART_STOCK_INSUFFICIENT", 409,
                           "available_qty is below the planned quantity for part %s"
                           % part["id"])
    for part, qty in planned:
        part["reserved_qty"] += qty
        touch(part)
    for line in live_lines(wo["id"]):
        if line["status"] == "ESTIMATED":
            line["status"] = "AUTHORIZED"
            touch(line)
        defect = db.STORE["defects"].get(line["defect_finding_id"])
        if defect is not None and defect["status"] == "ESTIMATED":
            defect["status"] = "AUTHORIZED"
            touch(defect)
    wo["auth_status"] = "AUTHORIZED"
    wo["authorized_at"] = now_iso()
    touch(wo)
    return ok(wo_out(wo))


@bp.post("/work-orders/<wid>/reject")
@auth("CarOwnerRep", "HandlingLineRep")
def reject_work_order(wid):
    wo = get_or_404("work_orders", wid, "WorkOrder")
    get_body(required=False)
    billing_ops.party_match_or_403(wo)
    if wo["auth_status"] != "PENDING_AUTHORIZATION":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Only a PENDING_AUTHORIZATION work order can be rejected")
    cancel_lines_and_findings(wo)
    wo["auth_status"] = "REJECTED"
    wo["exec_status"] = "CANCELLED"
    touch(wo)
    return ok(wo_out(wo))


@bp.post("/work-orders/<wid>/revise-estimate")
@auth("RepairForeman")
def revise_estimate(wid):
    wo = get_or_404("work_orders", wid, "WorkOrder")
    body = get_body()
    expected = req_int(body, "expected_work_order_version")
    if expected != wo["version"]:
        raise ApiError("ERR_STALE_WORK_ORDER_VERSION", 412,
                       "expected_work_order_version does not match the work order's current version")
    if wo["auth_status"] != "PENDING_AUTHORIZATION":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Only a PENDING_AUTHORIZATION work order can be re-estimated")
    railcar = db.STORE["railcars"][wo["railcar_id"]]
    today = now().date()
    # Resolve every line first so a gap fails the whole operation.
    resolutions = []
    for line in live_lines(wo["id"]):
        entry = resolve_price_entry(railcar["shop_id"], line["job_code"], today)
        if entry is None:
            raise ApiError("ERR_PRICE_MASTER_GAP", 422,
                           "No price master entry effective for job_code %s"
                           % line["job_code"])
        resolutions.append((line, entry))
    for line, entry in resolutions:
        labor, material, total = estimate_line(line["planned_parts"] or [], entry)
        line["price_master_entry_id"] = entry["id"]
        line["estimate_labor_cents"] = labor
        line["estimate_material_cents"] = material
        line["estimate_total_cents"] = total
        touch(line)
    recompute_wo_estimate_total(wo)
    touch(wo)
    return ok(wo_out(wo))


# ---------------------------------------------------------------------------
# Routing, execution, quality gate (PRD 3.5)
# ---------------------------------------------------------------------------

@bp.post("/work-orders/<wid>/assign-slot")
@auth("RepairForeman")
def assign_slot(wid):
    wo = get_or_404("work_orders", wid, "WorkOrder")
    body = get_body()
    slot = ref_or_404("shop_slots", req_str(body, "slot_id"), "ShopSlot")
    if wo["auth_status"] != "AUTHORIZED" or wo["routing"] != "SHOP" \
            or wo["exec_status"] != "NOT_STARTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "assign-slot requires an AUTHORIZED SHOP work order that is NOT_STARTED")
    if slot["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Slot must be OPEN to be reserved")
    s_start = parse_dt(slot["starts_at"])
    s_end = parse_dt(slot["ends_at"])
    for other in db.STORE["shop_slots"].values():
        if (other["id"] != slot["id"] and other["stall_id"] == slot["stall_id"]
                and other["status"] in ("RESERVED", "OCCUPIED")):
            o_start = parse_dt(other["starts_at"])
            o_end = parse_dt(other["ends_at"])
            if s_start < o_end and o_start < s_end:
                raise ApiError("ERR_SLOT_OVERLAP", 409,
                               "Slot window overlaps a reserved or occupied slot on the same stall")
    std_hours = Decimal(0)
    for line in live_lines(wo["id"]):
        entry = db.STORE["price_entries"][line["price_master_entry_id"]]
        std_hours += Decimal(str(entry["standard_labor_hours"]))
    window_hours = Decimal(str((s_end - s_start).total_seconds())) / Decimal(3600)
    if window_hours < std_hours:
        raise ApiError("ERR_SLOT_WINDOW_TOO_SHORT", 409,
                       "Slot window hours are below the sum of standard labor hours")
    slot["status"] = "RESERVED"
    slot["reserved_work_order_id"] = wo["id"]
    touch(slot)
    wo["assigned_slot_id"] = slot["id"]
    wo["exec_status"] = "SHOP_QUEUED"
    railcar = db.STORE["railcars"][wo["railcar_id"]]
    shop = db.STORE["shops"].get(railcar["shop_id"])
    railcar["projected_dwell_charge_cents"] = dwell_projected(railcar, shop, s_end)
    touch(railcar)
    touch(wo)
    return ok(wo_out(wo))


@bp.post("/work-orders/<wid>/dispatch")
@auth("RepairForeman")
def dispatch_work_order(wid):
    wo = get_or_404("work_orders", wid, "WorkOrder")
    body = get_body()
    crew = req_str(body, "mobile_crew_id")
    if wo["auth_status"] != "AUTHORIZED" or wo["routing"] != "MOBILE" \
            or wo["exec_status"] != "NOT_STARTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "dispatch requires an AUTHORIZED MOBILE work order that is NOT_STARTED")
    wo["mobile_crew_id"] = crew
    wo["exec_status"] = "MOBILE_DISPATCHED"
    railcar = db.STORE["railcars"][wo["railcar_id"]]
    shop = db.STORE["shops"].get(railcar["shop_id"])
    std_hours = Decimal(0)
    for line in live_lines(wo["id"]):
        entry = db.STORE["price_entries"][line["price_master_entry_id"]]
        std_hours += Decimal(str(entry["standard_labor_hours"]))
    release = now() + timedelta(seconds=float(std_hours * Decimal(3600)))
    railcar["projected_dwell_charge_cents"] = dwell_projected(railcar, shop, release)
    touch(railcar)
    touch(wo)
    return ok(wo_out(wo))


@bp.post("/work-orders/<wid>/start")
@auth("RepairForeman")
def start_work_order(wid):
    wo = get_or_404("work_orders", wid, "WorkOrder")
    get_body(required=False)
    if wo["exec_status"] not in ("SHOP_QUEUED", "MOBILE_DISPATCHED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Only SHOP_QUEUED or MOBILE_DISPATCHED work can be started")
    if wo["exec_status"] == "SHOP_QUEUED":
        slot = db.STORE["shop_slots"].get(wo["assigned_slot_id"])
        if slot is not None and slot["status"] == "RESERVED":
            slot["status"] = "OCCUPIED"
            touch(slot)
        railcar = db.STORE["railcars"][wo["railcar_id"]]
        if railcar["status"] == "ARRIVED":
            railcar["status"] = "IN_SHOP"
            touch(railcar)
    wo["exec_status"] = "IN_PROGRESS"
    touch(wo)
    return ok(wo_out(wo))


@bp.post("/work-orders/<wid>/complete")
@auth("RepairForeman")
def complete_work_order(wid):
    wo = get_or_404("work_orders", wid, "WorkOrder")
    body = get_body()
    actuals = req_field_list(body, "line_actuals")
    if wo["exec_status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Only IN_PROGRESS work can be reported complete")
    target_lines = {l["id"]: l for l in live_lines(wo["id"])}
    seen = set()
    for entry in actuals:
        if not isinstance(entry, dict):
            raise invalid_request("line_actuals entries must be objects")
        line_id = entry.get("repair_line_id") or entry.get("line_id")
        if not isinstance(line_id, str):
            raise invalid_request("line_actuals entries require repair_line_id")
        if line_id not in db.STORE["repair_lines"] or \
                db.STORE["repair_lines"][line_id]["work_order_id"] != wo["id"]:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", 404,
                           "Repair line %s does not exist on this work order" % line_id)
        if line_id not in target_lines:
            raise invalid_request("line_actuals references a cancelled line")
        if line_id in seen:
            raise invalid_request("line_actuals contains a duplicate line")
        seen.add(line_id)
        hours = entry.get("actual_labor_hours")
        if not isinstance(hours, (int, float)) or isinstance(hours, bool) or hours < 0:
            raise invalid_request("actual_labor_hours must be a non-negative number")
        parts = entry.get("actual_parts") or []
        if not isinstance(parts, list):
            raise invalid_request("actual_parts must be a list")
        norm_parts = []
        for p in parts:
            if not isinstance(p, dict):
                raise invalid_request("actual_parts entries must be objects")
            part = ref_or_404("parts", p.get("part_item_id"), "PartItem")
            qty = p.get("quantity")
            if not isinstance(qty, int) or isinstance(qty, bool) or qty <= 0:
                raise invalid_request("actual_parts quantity must be a positive integer")
            norm_parts.append({"part_item_id": part["id"], "quantity": qty})
        entry["_norm_parts"] = norm_parts
    if seen != set(target_lines.keys()):
        raise invalid_request("line_actuals must cover every non-cancelled line")
    for entry in actuals:
        line_id = entry.get("repair_line_id") or entry.get("line_id")
        line = target_lines[line_id]
        line["actual_labor_hours"] = entry["actual_labor_hours"]
        line["actual_parts"] = entry["_norm_parts"]
        touch(line)
    wo["qa_review_entered_at"] = now_iso()
    wo["exec_status"] = "QA_REVIEW"
    touch(wo)
    return ok(wo_out(wo))


def req_field_list(body, name):
    v = body.get(name)
    if not isinstance(v, list) or not v:
        raise invalid_request("Field %s must be a non-empty list" % name)
    return v


@bp.post("/work-orders/<wid>/qa-review")
@auth("QualityInspector")
def qa_review(wid):
    wo = get_or_404("work_orders", wid, "WorkOrder")
    body = get_body()
    if g.user_id == wo["created_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403,
                       "The reviewer must differ from the work order's creator")
    if wo["exec_status"] != "QA_REVIEW":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Only a work order in QA_REVIEW can be reviewed")
    result = body.get("result")
    if not isinstance(result, str) or result.upper() not in ("PASS", "FAIL"):
        raise invalid_request("result must be PASS or FAIL")
    result = result.upper()
    railcar = db.STORE["railcars"][wo["railcar_id"]]
    delay = hours_between(parse_dt(wo["qa_review_entered_at"]), now(), 2)
    railcar["shop_delay_hours"] = float(
        Decimal(str(railcar["shop_delay_hours"])) + delay)
    touch(railcar)

    if result == "FAIL":
        wo["rework_count"] += 1
        wo["exec_status"] = "IN_PROGRESS"
        touch(wo)
        return ok(wo_out(wo))

    # PASS
    wo["completed_at"] = now_iso()
    wo["exec_status"] = "COMPLETED"
    completion_date = now().date()
    final_total = 0
    for line in live_lines(wo["id"]):
        if line["status"] == "AUTHORIZED":
            labor, material, total = final_line_pricing(line, wo, completion_date)
            line["final_labor_cents"] = labor
            line["final_material_cents"] = material
            line["final_total_cents"] = total
            line["status"] = "FINALIZED"
            touch(line)
            final_total += total
            defect = db.STORE["defects"].get(line["defect_finding_id"])
            if defect is not None and defect["status"] == "AUTHORIZED":
                defect["status"] = "REPAIRED"
                touch(defect)
    wo["final_total_cents"] = final_total
    # Consume parts: on_hand -= consumed, reserved -= planned.
    for line in live_lines(wo["id"]):
        for a in (line["actual_parts"] or []):
            part = db.STORE["parts"].get(a["part_item_id"])
            if part is not None:
                part["on_hand_qty"] -= a["quantity"]
                touch(part)
        for p in (line["planned_parts"] or []):
            part = db.STORE["parts"].get(p["part_item_id"])
            if part is not None:
                part["reserved_qty"] -= p["quantity"]
                touch(part)
    if wo["routing"] == "SHOP":
        release_slot(wo)
    siblings_open = any(
        w["id"] != wo["id"] and w["railcar_id"] == railcar["id"]
        and w["exec_status"] not in ("COMPLETED", "CANCELLED")
        for w in db.STORE["work_orders"].values())
    if not siblings_open and railcar["status"] == "IN_SHOP":
        railcar["status"] = "READY_FOR_DEPARTURE"
        touch(railcar)
    touch(wo)
    return ok(wo_out(wo))


@bp.post("/work-orders/<wid>/cancel")
@auth("RepairForeman")
def cancel_work_order(wid):
    wo = get_or_404("work_orders", wid, "WorkOrder")
    get_body(required=False)
    if wo["exec_status"] not in ("NOT_STARTED", "SHOP_QUEUED", "MOBILE_DISPATCHED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Only work that has not started can be cancelled")
    was_authorized = wo["auth_status"] == "AUTHORIZED"
    cancel_lines_and_findings(wo)
    if was_authorized:
        release_reservations(wo)
    release_slot(wo)
    wo["auth_status"] = "CANCELLED"
    wo["exec_status"] = "CANCELLED"
    touch(wo)
    return ok(wo_out(wo))
