"""Routes: work orders (intake, dispatch, field execution, QA) and photo evidence."""

from flask import Blueprint, request

from auth import get_auth, require_role, ANY_ROLE
from db import store, new_entity, bump, public
from errors import raise_err
from response import ok, ok_list
from services import (
    select_allowable, winterization_quote, evidence_complete,
    recompute_evidence_complete, has_unresolved_flags, crew_day_load,
    cancel_work_order,
)
from util import (
    get_body, req_str, opt_str, req_amount, req_enum, req_date, get_or_404,
    parse_pagination, paginate, sort_created, req_datetime,
    ORDER_TYPES, ORDER_ITEM_MAP, OCCUPANCY_GATED_ORDER_TYPES, PHOTO_CATEGORIES,
)

bp = Blueprint("work", __name__)


def _occupancy_gate(prop, order_type):
    if order_type in OCCUPANCY_GATED_ORDER_TYPES and prop["occupancy_status"] == "OCCUPIED":
        raise_err("ERR_PROPERTY_OCCUPIED", "Operation gated on verified vacancy; property is OCCUPIED")


def _check_capacity(crew, scheduled_date, exclude_wo_id=None):
    if crew_day_load(crew["id"], scheduled_date, exclude_wo_id=exclude_wo_id) >= crew["daily_capacity_jobs"]:
        raise_err("ERR_CREW_DAY_CAPACITY", "Crew daily capacity reached for that scheduled_date")


# ---- WorkOrder creation --------------------------------------------------------

@bp.post("/preservation/work-orders")
def create_work_order():
    user_id, role = get_auth()
    require_role(role, ["Servicer"])
    b = get_body()

    property_id = b.get("property_id")
    if property_id is None:
        raise_err("ERR_INVALID_REQUEST", "Missing required field: property_id")
    if not isinstance(property_id, str):
        raise_err("ERR_INVALID_REQUEST", "property_id must be a string")
    prop = get_or_404(store.properties, property_id, "Property")

    # Entity-backed ownership: a Servicer issues orders only for its own properties.
    if prop["servicer_id"] != user_id:
        raise_err("ERR_FORBIDDEN_FOR_ROLE", "Servicer may issue work orders only for its own properties")

    # Body-referenced ids, left to right.
    code_violation_id = b.get("code_violation_id")
    if code_violation_id is not None:
        if not isinstance(code_violation_id, str):
            raise_err("ERR_INVALID_REQUEST", "code_violation_id must be a string")
        get_or_404(store.violations, code_violation_id, "CodeViolation")
    damage_report_id = b.get("damage_report_id")
    if damage_report_id is not None:
        if not isinstance(damage_report_id, str):
            raise_err("ERR_INVALID_REQUEST", "damage_report_id must be a string")
        get_or_404(store.damage_reports, damage_report_id, "DamageReport")

    order_type = req_enum(b, "order_type", ORDER_TYPES)
    due_date = req_date(b, "due_date")

    # State gates (tier 5).
    if prop["status"] != "ACTIVE":
        raise_err("ERR_PROPERTY_NOT_ACTIVE", "Property is not ACTIVE")
    if order_type in ("GRASS_CUT", "SNOW_REMOVAL") and prop["compliance_posture"] == "NON_COMPLIANT":
        raise_err("ERR_POSTURE_BLOCKS_ORDER", "Property compliance posture blocks exterior recurring orders")

    # Referential gate (tier 7): allowable schedule selection + pinning.
    item_code = ORDER_ITEM_MAP[order_type]
    row = select_allowable(prop["investor_type"], item_code)
    if row is None:
        raise_err("ERR_ALLOWABLE_NOT_FOUND", "No InvestorAllowable row is effective for this investor/item")

    estimated = 0
    if order_type in ("WINTERIZATION", "DEWINTERIZATION"):
        estimated = winterization_quote(prop, order_type)

    wo = new_entity({
        "property_id": prop["id"],
        "servicer_id": prop["servicer_id"],
        "order_type": order_type,
        "item_code": item_code,
        "source": "DIRECT",
        "status": "ISSUED",
        "due_date": due_date,
        "scheduled_date": None,
        "assigned_crew_id": None,
        "bid_id": None,
        "damage_report_id": damage_report_id,
        "code_violation_id": code_violation_id,
        "recurring_plan_id": None,
        "investor_allowable_id": row["id"],
        "investor_allowable_version": row["version"],
        "allowable_cap_cents": row["max_per_occurrence_cents"],
        "requires_bid_over_cents": row["requires_bid_over_cents"],
        "estimated_cost_cents": estimated,
        "submitted_cost_cents": None,
        "approved_cost_cents": None,
        "rework_count": 0,
        "evidence_complete": False,
    })
    store.work_orders[wo["id"]] = wo
    return ok(public(wo), status=201)


@bp.get("/preservation/work-orders/<workOrderId>")
def get_work_order(workOrderId):
    user_id, role = get_auth()
    require_role(role, ANY_ROLE)
    wo = get_or_404(store.work_orders, workOrderId, "WorkOrder")
    return ok(public(wo))


@bp.get("/preservation/work-orders")
def list_work_orders():
    user_id, role = get_auth()
    require_role(role, ANY_ROLE)
    limit, offset = parse_pagination()
    items = list(store.work_orders.values())
    for field in (
        "property_id", "assigned_crew_id", "servicer_id", "bid_id",
        "investor_allowable_id", "recurring_plan_id", "code_violation_id",
        "damage_report_id", "status",
    ):
        v = request.args.get(field)
        if v is not None:
            items = [w for w in items if w.get(field) == v]
    items = sort_created(items)
    page, total = paginate(items, public, limit, offset)
    return ok_list(page, total, limit, offset)


# ---- Dispatch ------------------------------------------------------------------

@bp.post("/preservation/work-orders/<workOrderId>/assign")
def assign_work_order(workOrderId):
    user_id, role = get_auth()
    require_role(role, ["Dispatcher"])
    wo = get_or_404(store.work_orders, workOrderId, "WorkOrder")
    b = get_body()
    crew_id = b.get("crew_id")
    crew = None
    if crew_id is not None:
        if not isinstance(crew_id, str):
            raise_err("ERR_INVALID_REQUEST", "crew_id must be a string")
        crew = get_or_404(store.crews, crew_id, "Crew")
    if crew_id is None:
        raise_err("ERR_INVALID_REQUEST", "Missing required field: crew_id")
    scheduled_date = req_date(b, "scheduled_date")

    if wo["status"] != "ISSUED":
        raise_err("ERR_INVALID_STATE", "Work order is not ISSUED")
    prop = store.properties.get(wo["property_id"])
    if prop is not None and prop["status"] != "ACTIVE":
        raise_err("ERR_PROPERTY_NOT_ACTIVE", "Property is not ACTIVE")
    if prop is not None:
        _occupancy_gate(prop, wo["order_type"])
    _check_capacity(crew, scheduled_date)

    wo["assigned_crew_id"] = crew_id
    wo["scheduled_date"] = scheduled_date
    wo["status"] = "ASSIGNED"
    bump(wo)
    return ok(public(wo))


@bp.post("/preservation/work-orders/<workOrderId>/reassign")
def reassign_work_order(workOrderId):
    user_id, role = get_auth()
    require_role(role, ["Dispatcher"])
    wo = get_or_404(store.work_orders, workOrderId, "WorkOrder")
    b = get_body()
    crew_id = b.get("crew_id")
    crew = None
    if crew_id is not None:
        if not isinstance(crew_id, str):
            raise_err("ERR_INVALID_REQUEST", "crew_id must be a string")
        crew = get_or_404(store.crews, crew_id, "Crew")
    if crew_id is None:
        raise_err("ERR_INVALID_REQUEST", "Missing required field: crew_id")
    scheduled_date = req_date(b, "scheduled_date")
    if "expected_work_order_version" not in b or b.get("expected_work_order_version") is None:
        raise_err("ERR_INVALID_REQUEST", "Missing required field: expected_work_order_version")
    expected = b["expected_work_order_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise_err("ERR_INVALID_REQUEST", "expected_work_order_version must be an integer")

    # OCC guard (section 2.8).
    if expected != wo["version"]:
        raise_err("ERR_STALE_VERSION", "Work order version has advanced since last read")

    if wo["status"] != "ASSIGNED":
        raise_err("ERR_INVALID_STATE", "Work order is not ASSIGNED")
    _check_capacity(crew, scheduled_date, exclude_wo_id=wo["id"])

    wo["assigned_crew_id"] = crew_id
    wo["scheduled_date"] = scheduled_date
    bump(wo)
    return ok(public(wo))


# ---- Field execution -------------------------------------------------------------

@bp.post("/preservation/work-orders/<workOrderId>/start")
def start_work_order(workOrderId):
    user_id, role = get_auth()
    require_role(role, ["FieldCrew"])
    wo = get_or_404(store.work_orders, workOrderId, "WorkOrder")
    get_body()
    if wo["status"] != "ASSIGNED":
        raise_err("ERR_INVALID_STATE", "Work order is not ASSIGNED")
    prop = store.properties.get(wo["property_id"])
    if prop is not None and prop["status"] != "ACTIVE":
        raise_err("ERR_PROPERTY_NOT_ACTIVE", "Property is not ACTIVE")
    if prop is not None:
        _occupancy_gate(prop, wo["order_type"])
    if user_id != wo.get("assigned_crew_id"):
        raise_err("ERR_NOT_ASSIGNED_CREW", "Only the assigned crew may start this work order")
    wo["status"] = "IN_PROGRESS"
    bump(wo)
    return ok(public(wo))


@bp.post("/preservation/work-orders/<workOrderId>/submit")
def submit_work_order(workOrderId):
    user_id, role = get_auth()
    require_role(role, ["FieldCrew"])
    wo = get_or_404(store.work_orders, workOrderId, "WorkOrder")
    b = get_body()
    submitted_cost_cents = req_amount(b, "submitted_cost_cents")

    if wo["status"] != "IN_PROGRESS":
        raise_err("ERR_INVALID_STATE", "Work order is not IN_PROGRESS")
    if user_id != wo.get("assigned_crew_id"):
        raise_err("ERR_NOT_ASSIGNED_CREW", "Only the assigned crew may submit this work order")
    if not evidence_complete(wo):
        raise_err("ERR_PHOTO_INCOMPLETE", "Photo evidence minimums for this order type are not met")
    if has_unresolved_flags(wo["id"]):
        raise_err("ERR_PHOTO_FLAGGED_OPEN", "Flagged photo evidence remains uncleared on this work order")
    threshold = wo.get("requires_bid_over_cents")
    if threshold is not None and submitted_cost_cents > threshold:
        bid_ok = False
        bid_id = wo.get("bid_id")
        if bid_id:
            bid = store.bids.get(bid_id)
            bid_ok = bid is not None and bid["status"] == "APPROVED"
        if not bid_ok:
            raise_err("ERR_BID_REQUIRED_OVER_CAP", "Submitted cost exceeds the bid threshold without an APPROVED bid")

    wo["submitted_cost_cents"] = submitted_cost_cents
    wo["status"] = "SUBMITTED"
    bump(wo)
    return ok(public(wo))


# ---- Quality review ---------------------------------------------------------------

@bp.post("/preservation/work-orders/<workOrderId>/approve")
def approve_work_order(workOrderId):
    user_id, role = get_auth()
    require_role(role, ["QualityReviewer"])
    wo = get_or_404(store.work_orders, workOrderId, "WorkOrder")
    get_body()
    if wo["status"] != "SUBMITTED":
        raise_err("ERR_INVALID_STATE", "Work order is not SUBMITTED")
    if has_unresolved_flags(wo["id"]):
        raise_err("ERR_PHOTO_FLAGGED_OPEN", "Flagged photo evidence remains uncleared on this work order")
    approved = wo["submitted_cost_cents"]
    bid_id = wo.get("bid_id")
    if bid_id:
        bid = store.bids.get(bid_id)
        if bid is not None and bid["status"] == "APPROVED" and bid["amount_cents"] < approved:
            approved = bid["amount_cents"]
    wo["approved_cost_cents"] = approved
    wo["status"] = "APPROVED"
    bump(wo)
    return ok(public(wo))


@bp.post("/preservation/work-orders/<workOrderId>/reject")
def reject_work_order(workOrderId):
    user_id, role = get_auth()
    require_role(role, ["QualityReviewer"])
    wo = get_or_404(store.work_orders, workOrderId, "WorkOrder")
    b = get_body()
    req_str(b, "reason")
    if wo["status"] != "SUBMITTED":
        raise_err("ERR_INVALID_STATE", "Work order is not SUBMITTED")
    wo["status"] = "IN_PROGRESS"
    wo["rework_count"] += 1
    wo["submitted_cost_cents"] = None
    bump(wo)
    return ok(public(wo))


@bp.post("/preservation/work-orders/<workOrderId>/cancel")
def cancel_work_order_endpoint(workOrderId):
    user_id, role = get_auth()
    require_role(role, ["Servicer"])
    wo = get_or_404(store.work_orders, workOrderId, "WorkOrder")
    b = get_body()
    opt_str(b, "reason")
    if wo["servicer_id"] != user_id:
        raise_err("ERR_FORBIDDEN_FOR_ROLE", "Servicer may cancel only its own work orders")
    if wo["status"] not in ("ISSUED", "ASSIGNED", "IN_PROGRESS"):
        raise_err("ERR_INVALID_STATE", "Work order is not in a cancellable status")
    cancel_work_order(wo)
    return ok(public(wo))


@bp.post("/preservation/work-orders/<workOrderId>/complete")
def complete_work_order(workOrderId):
    user_id, role = get_auth()
    require_role(role, ["QualityReviewer"])
    wo = get_or_404(store.work_orders, workOrderId, "WorkOrder")
    get_body()
    if wo["status"] != "APPROVED":
        raise_err("ERR_INVALID_STATE", "Work order is not APPROVED")
    wo["status"] = "COMPLETED"
    bump(wo)

    # Cascade: auto-create the DRAFT invoice.
    prop = store.properties.get(wo["property_id"])
    inv = new_entity({
        "work_order_id": wo["id"],
        "property_id": wo["property_id"],
        "investor_type": prop["investor_type"] if prop else None,
        "status": "DRAFT",
        "claimed_total_cents": 0,
        "provisional_allowed_cents": None,
        "approved_amount_cents": None,
        "prompt_pay_discount_cents": 0,
        "payable_amount_cents": None,
        "appeal_round": 0,
        "submitted_at": None,
        "approved_at": None,
    })
    store.invoices[inv["id"]] = inv
    return ok(public(wo))


# ---- PhotoEvidence ------------------------------------------------------------------

def _recompute_subject_evidence(photo):
    wo_id = photo.get("work_order_id")
    if wo_id:
        wo = store.work_orders.get(wo_id)
        if wo is not None:
            recompute_evidence_complete(wo)


@bp.post("/preservation/photo-evidence")
def upload_photo():
    user_id, role = get_auth()
    require_role(role, ["FieldCrew"])
    b = get_body()

    # Existence of any referenced subject ids, left to right (tier 3).
    subjects = {}
    for field, table, label in (
        ("work_order_id", store.work_orders, "WorkOrder"),
        ("inspection_id", store.inspections, "Inspection"),
        ("bid_id", store.bids, "Bid"),
        ("damage_report_id", store.damage_reports, "DamageReport"),
    ):
        v = b.get(field)
        if v is not None:
            if not isinstance(v, str):
                raise_err("ERR_INVALID_REQUEST", f"{field} must be a string")
            get_or_404(table, v, label)
            subjects[field] = v

    # Body shape (tier 4): exactly one subject FK.
    if len(subjects) != 1:
        raise_err("ERR_INVALID_REQUEST", "Exactly one subject FK is required on photo evidence")
    category = req_enum(b, "category", PHOTO_CATEGORIES)
    taken_at = req_datetime(b, "taken_at")
    content_hash = req_str(b, "content_hash")

    photo = new_entity({
        "work_order_id": subjects.get("work_order_id"),
        "inspection_id": subjects.get("inspection_id"),
        "bid_id": subjects.get("bid_id"),
        "damage_report_id": subjects.get("damage_report_id"),
        "category": category,
        "taken_at": taken_at.strftime("%Y-%m-%dT%H:%M:%S.") + f"{taken_at.microsecond // 1000:03d}Z",
        "content_hash": content_hash,
        "captured_by_crew_id": user_id,
        "flagged": False,
        "flagged_by_user_id": None,
        "flag_reason": None,
    })
    store.photos[photo["id"]] = photo
    _recompute_subject_evidence(photo)
    return ok(public(photo), status=201)


@bp.get("/preservation/photo-evidence/<photoId>")
def get_photo(photoId):
    user_id, role = get_auth()
    require_role(role, ANY_ROLE)
    photo = get_or_404(store.photos, photoId, "PhotoEvidence")
    return ok(public(photo))


@bp.get("/preservation/photo-evidence")
def list_photos():
    user_id, role = get_auth()
    require_role(role, ANY_ROLE)
    limit, offset = parse_pagination()
    items = list(store.photos.values())
    for field in ("work_order_id", "inspection_id", "bid_id", "damage_report_id", "captured_by_crew_id"):
        v = request.args.get(field)
        if v is not None:
            items = [p for p in items if p.get(field) == v]
    items = sort_created(items)
    page, total = paginate(items, public, limit, offset)
    return ok_list(page, total, limit, offset)


@bp.post("/preservation/photo-evidence/<photoId>/flag")
def flag_photo(photoId):
    user_id, role = get_auth()
    require_role(role, ["QualityReviewer"])
    photo = get_or_404(store.photos, photoId, "PhotoEvidence")
    b = get_body()
    reason = req_str(b, "reason")
    if photo["flagged"]:
        raise_err("ERR_INVALID_STATE", "Photo evidence is already flagged")
    photo["flagged"] = True
    photo["flagged_by_user_id"] = user_id
    photo["flag_reason"] = reason
    bump(photo)
    _recompute_subject_evidence(photo)
    return ok(public(photo))


@bp.post("/preservation/photo-evidence/<photoId>/clear-flag")
def clear_flag_photo(photoId):
    user_id, role = get_auth()
    require_role(role, ["QualityReviewer"])
    photo = get_or_404(store.photos, photoId, "PhotoEvidence")
    get_body()
    if not photo["flagged"]:
        raise_err("ERR_INVALID_STATE", "Photo evidence is not flagged")
    if photo.get("flagged_by_user_id") == user_id:
        raise_err("ERR_SOD_FLAG_CLEAR", "A reviewer may not clear a flag they set themselves")
    photo["flagged"] = False
    bump(photo)
    _recompute_subject_evidence(photo)
    return ok(public(photo))
