"""FFEProject endpoints and project-scoped sublists (PRD 3.1)."""
from flask import Blueprint, request

import db
import services as svc
from errors import ApiError
from middleware import auth, require_role, body, req_str, req_int, opt_int, req_enum
from response import ok, paginate

bp = Blueprint("projects", __name__)

S = db.STORE
BRAND_PROGRAMS = ("MARQUEE_SELECT", "MARQUEE_LUXE", "INDIE_SOFT")
PROJECT_STATUSES = ("PLANNING", "PROCUREMENT", "INSTALLATION", "COMPLETED", "CANCELLED")
ANY = ("PurchasingAgent", "BrandApprover", "Vendor",
       "WarehouseReceiver", "InstallationManager", "OwnerRep")


@bp.route("/api/projects", methods=["POST"])
def create_project():
    auth_user, role = auth()
    require_role(role, ("PurchasingAgent",))
    b = body()
    name = req_str(b, "name")
    hotel_name = req_str(b, "hotel_name")
    brand_program = req_enum(b, "brand_program", BRAND_PROGRAMS)
    total_budget = req_int(b, "total_budget_cents")
    if total_budget <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "total_budget_cents must be > 0")
    unallocated = opt_int(b, "unallocated_contingency_cents", 0)
    if unallocated < 0 or unallocated > total_budget:
        raise ApiError("ERR_INVALID_REQUEST",
                       "unallocated_contingency_cents must be >= 0 and <= total_budget_cents")
    capacity = opt_int(b, "default_crew_capacity_per_floor_day", 8)
    if capacity < 1:
        raise ApiError("ERR_INVALID_REQUEST",
                       "default_crew_capacity_per_floor_day must be >= 1")
    p = db.create("projects", {
        "name": name,
        "hotel_name": hotel_name,
        "brand_program": brand_program,
        "total_budget_cents": total_budget,
        "unallocated_contingency_cents": unallocated,
        "default_crew_capacity_per_floor_day": capacity,
        "committed_cents": 0,
        "actual_spend_cents": 0,
        "sunk_fees_cents": 0,
        "procurement_posture": "OPEN",
        "status": "PLANNING",
    })
    return ok(db.pub(p), 201)


@bp.route("/api/projects", methods=["GET"])
def list_projects():
    auth_user, role = auth()
    require_role(role, ANY)
    rows = db.sorted_items(S["projects"].values())
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, meta = paginate(rows)
    return ok([db.pub(r) for r in page], 200, meta)


@bp.route("/api/projects/<projectId>", methods=["GET"])
def get_project(projectId):
    auth_user, role = auth()
    require_role(role, ANY)
    return ok(db.pub(svc.get_project(projectId)))


@bp.route("/api/projects/<id>/lifecycle-transitions", methods=["POST"])
def lifecycle(id):
    auth_user, role = auth()
    require_role(role, ("PurchasingAgent",))
    p = svc.get_project(id)
    b = body()
    to_status = req_enum(b, "to_status", PROJECT_STATUSES)
    cur = p["status"]
    legal = {
        ("PLANNING", "PROCUREMENT"),
        ("PROCUREMENT", "INSTALLATION"),
        ("INSTALLATION", "COMPLETED"),
        ("PLANNING", "CANCELLED"),
        ("PROCUREMENT", "CANCELLED"),
    }
    if (cur, to_status) not in legal:
        raise ApiError("ERR_INVALID_LIFECYCLE_TRANSITION",
                       f"{cur} -> {to_status} is not a legal lifecycle transition")
    if to_status == "PROCUREMENT":
        if not any(bl["project_id"] == p["id"] for bl in S["budget_lines"].values()):
            raise ApiError("ERR_NO_BUDGET_LINES",
                           "PLANNING -> PROCUREMENT requires at least one budget line")
    elif to_status == "COMPLETED":
        if any(w["project_id"] == p["id"] and w["status"] in ("PLANNED", "RELEASED", "IN_PROGRESS")
               for w in S["installation_windows"].values()):
            raise ApiError("ERR_WINDOWS_OUTSTANDING",
                           "An installation window is still PLANNED, RELEASED, or IN_PROGRESS")
        if any(c["po_line_id"] in S["po_lines"]
               and svc.project_of_line(S["po_lines"][c["po_line_id"]])["id"] == p["id"]
               and c["status"] in ("OPEN", "SUBMITTED", "DISPUTED")
               for c in S["damage_claims"].values()):
            raise ApiError("ERR_OPEN_CLAIMS_REMAIN",
                           "A damage claim is still OPEN, SUBMITTED, or DISPUTED")
    elif to_status == "CANCELLED":
        if any(po["project_id"] == p["id"] and po["fulfillment_status"]
               in ("READY_TO_SHIP", "CONSOLIDATED", "DELIVERED", "CLOSED")
               for po in S["purchase_orders"].values()):
            raise ApiError("ERR_ACTIVE_POS_EXIST",
                           "A purchase order is READY_TO_SHIP, CONSOLIDATED, DELIVERED, or CLOSED")
    # --- apply ---
    if to_status == "CANCELLED":
        for po in db.sorted_items([po for po in S["purchase_orders"].values()
                                   if po["project_id"] == p["id"]]):
            if po["fulfillment_status"] in ("ISSUED", "ACKNOWLEDGED"):
                po["fulfillment_status"] = "CANCELLED"
                db.touch(po)
                for line in svc.lines_of_po(po["id"]):
                    line["status"] = "CANCELLED"
                    db.touch(line)
        svc.recompute_project_financials(p["id"])
    elif to_status == "COMPLETED":
        for spec in db.sorted_items([s for s in S["spec_items"].values()
                                     if s["project_id"] == p["id"]]):
            if spec["status"] == "BRAND_APPROVED":
                spec["status"] = "LOCKED"
                db.touch(spec)
    p["status"] = to_status
    db.touch(p)
    svc.recompute_project(p)
    return ok(db.pub(p))


def _sublist(project_id, kind, key="project_id"):
    svc.get_project(project_id)
    rows = db.sorted_items(r for r in S[kind].values() if r.get(key) == project_id)
    page, meta = paginate(rows)
    return ok([db.pub(r) for r in page], 200, meta)


@bp.route("/api/projects/<id>/budget-lines", methods=["GET"])
def project_budget_lines(id):
    auth_user, role = auth()
    require_role(role, ANY)
    return _sublist(id, "budget_lines")


@bp.route("/api/projects/<id>/spec-items", methods=["GET"])
def project_spec_items(id):
    auth_user, role = auth()
    require_role(role, ANY)
    return _sublist(id, "spec_items")


@bp.route("/api/projects/<id>/purchase-orders", methods=["GET"])
def project_purchase_orders(id):
    auth_user, role = auth()
    require_role(role, ANY)
    return _sublist(id, "purchase_orders")


@bp.route("/api/projects/<id>/shipments", methods=["GET"])
def project_shipments(id):
    auth_user, role = auth()
    require_role(role, ANY)
    return _sublist(id, "shipments")


@bp.route("/api/projects/<id>/rooms", methods=["GET"])
def project_rooms(id):
    auth_user, role = auth()
    require_role(role, ANY)
    return _sublist(id, "rooms")


@bp.route("/api/projects/<id>/installation-windows", methods=["GET"])
def project_installation_windows(id):
    auth_user, role = auth()
    require_role(role, ANY)
    return _sublist(id, "installation_windows")


@bp.route("/api/projects/<id>/change-orders", methods=["GET"])
def project_change_orders(id):
    auth_user, role = auth()
    require_role(role, ANY)
    return _sublist(id, "change_orders")


# --- BudgetLine (PRD 3.1) ----------------------------------------------------

CATEGORIES = ("FURNITURE", "LIGHTING", "TEXTILES", "DECOR",
              "APPLIANCES", "FREIGHT", "INSTALLATION")


@bp.route("/api/budget-lines", methods=["POST"])
def create_budget_line():
    auth_user, role = auth()
    require_role(role, ("PurchasingAgent",))
    b = body()
    project_id = b.get("project_id")
    if not isinstance(project_id, str):
        raise ApiError("ERR_INVALID_REQUEST", "Missing or invalid field: project_id")
    category = req_enum(b, "category", CATEGORIES)
    budgeted = req_int(b, "budgeted_cents", 0)
    svc.get_project(project_id)
    if any(bl["project_id"] == project_id and bl["category"] == category
           for bl in S["budget_lines"].values()):
        raise ApiError("ERR_DUPLICATE_BUDGET_CATEGORY",
                       "A budget line with this category already exists for the project")
    bl = db.create("budget_lines", {
        "project_id": project_id,
        "category": category,
        "budgeted_cents": budgeted,
        "committed_cents": 0,
        "actual_cents": 0,
        "variance_commitment_cents": budgeted,
        "variance_final_cents": budgeted,
    })
    return ok(db.pub(bl), 201)


@bp.route("/api/budget-lines/<budgetLineId>", methods=["GET"])
def get_budget_line(budgetLineId):
    auth_user, role = auth()
    require_role(role, ANY)
    return ok(db.pub(svc.get_budget_line(budgetLineId)))
