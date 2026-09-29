"""Projects, the lifecycle, the contract position and photo documentation."""
from decimal import Decimal

from flask import Blueprint

from errors import AppError
from store import db, base_row, now, bump, ordered
from util import (
    ALL_ROLES, authorize, check_staff_identity, parse_body, ok, ok_list, paginate,
    qfilter, req_str, opt_id, req_enum, req_money, opt_money, req_dt, req_int,
    add_days, q2,
)
from routes.common import fetch, own_project
from services.constants import (
    CONTRACT_TYPES, WARRANTY_BASE_DAYS, BLOCKING_DEFECT_STATUSES,
    OPEN_CHANGE_ORDER_STATUSES, PENDING_DRAW_STATUSES, VISIBILITIES,
)
from services.ledger import (
    recompute_project, contract_position, project_allowance_items,
    project_schedule_tasks, project_change_orders, project_draw_requests,
    project_defect_tickets,
)

bp = Blueprint("projects", __name__)

READ_ROLES = ALL_ROLES
POSITION_ROLES = ["PlatformAdmin", "ProjectManager", "Controller", "Client", "Lender"]
PHOTO_LIST_ROLES = ["PlatformAdmin", "ProjectManager", "Controller", "Client"]

PROJECT_ACTIONS = ("START_CONSTRUCTION", "DECLARE_SUBSTANTIAL_COMPLETION")


def new_project_row():
    row = base_row()
    row.update({
        "client_id": None,
        "lender_id": None,
        "address": None,
        "contract_type": None,
        "base_contract_amount": None,
        "builder_fee_pct": None,
        "gmp_cap": None,
        "target_substantial_completion_date": None,
        "status": "PLANNING",
        "budget_posture": "WITHIN_BUDGET",
        "approved_change_order_total": Decimal("0.00"),
        "allowance_variance_total": Decimal("0.00"),
        "contract_sum_current": Decimal("0.00"),
        "cost_to_date": Decimal("0.00"),
        "eligible_cost_pool": Decimal("0.00"),
        "pending_draw_amount": Decimal("0.00"),
        "funded_to_date": Decimal("0.00"),
        "retainage_held": Decimal("0.00"),
        "construction_started_at": None,
        "substantial_completion_at": None,
        "final_accepted_at": None,
        "warranty_starts_at": None,
        "warranty_expires_at": None,
    })
    return row


@bp.post("/projects")
def create_project():
    authorize(["PlatformAdmin"])
    body = parse_body()

    client_id = req_str(body, "client_id")
    lender_id = opt_id(body, "lender_id")
    address = req_str(body, "address")
    contract_type = req_enum(body, "contract_type", CONTRACT_TYPES)
    base_contract_amount = req_money(body, "base_contract_amount",
                                     minimum=Decimal("0"), exclusive_min=True)
    builder_fee_pct = opt_money(body, "builder_fee_pct", None, minimum=Decimal("0"),
                                maximum=Decimal("0.50"), max_dp=4)
    gmp_cap = opt_money(body, "gmp_cap", None, minimum=Decimal("0"))
    target = req_dt(body, "target_substantial_completion_date")

    # ladder step 6 - body references resolve
    if client_id not in db.clients:
        raise AppError("ERR_CLIENT_NOT_FOUND")
    if lender_id is not None and lender_id not in db.lenders:
        raise AppError("ERR_LENDER_NOT_FOUND")

    # ladder step 9 - contract terms coherent
    if contract_type == "COST_PLUS" and builder_fee_pct is None:
        raise AppError("ERR_CONTRACT_TERMS_INVALID",
                       "A COST_PLUS project requires builder_fee_pct.")
    if gmp_cap is not None and gmp_cap < base_contract_amount:
        raise AppError("ERR_CONTRACT_TERMS_INVALID",
                       "gmp_cap must not sit below base_contract_amount.")

    row = new_project_row()
    row.update({
        "client_id": client_id,
        "lender_id": lender_id,
        "address": address,
        "contract_type": contract_type,
        "base_contract_amount": q2(base_contract_amount),
        "builder_fee_pct": builder_fee_pct,
        "gmp_cap": None if gmp_cap is None else q2(gmp_cap),
        "target_substantial_completion_date": target,
        "contract_sum_current": q2(base_contract_amount),
    })
    db.projects[row["id"]] = row
    return ok(row, 201)


@bp.get("/projects/<project_id>")
def get_project(project_id):
    user_id, role = authorize(READ_ROLES)
    project = fetch("projects", project_id)
    check_staff_identity(user_id, role)
    return ok(project, 200)


@bp.get("/projects")
def list_projects():
    user_id, role = authorize(READ_ROLES)
    check_staff_identity(user_id, role)
    rows = ordered(db.projects.values())
    client_id = qfilter("client_id")
    lender_id = qfilter("lender_id")
    status = qfilter("status")
    if client_id:
        rows = [r for r in rows if r["client_id"] == client_id]
    if lender_id:
        rows = [r for r in rows if r["lender_id"] == lender_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    page, meta = paginate(rows)
    return ok_list(page, meta)


@bp.get("/projects/<project_id>/contract-position")
def get_contract_position(project_id):
    user_id, role = authorize(POSITION_ROLES)
    project = fetch("projects", project_id)
    check_staff_identity(user_id, role)
    return ok(contract_position(project), 200)


@bp.post("/projects/<project_id>/advance")
def advance_project(project_id):
    user_id, role = authorize(["ProjectManager"])
    project = fetch("projects", project_id)
    body = parse_body()
    action = req_enum(body, "action", PROJECT_ACTIONS)
    check_staff_identity(user_id, role)

    if action == "START_CONSTRUCTION":
        # ladder step 10
        if project["status"] != "PLANNING":
            raise AppError("ERR_PROJECT_INVALID_STATE")
        # ladder step 14
        items = project_allowance_items(project["id"])
        tasks = project_schedule_tasks(project["id"])
        if not items or not any(t["status"] == "PLANNED" for t in tasks):
            raise AppError("ERR_PROJECT_NOT_READY_TO_START")

        project["status"] = "UNDER_CONSTRUCTION"
        project["construction_started_at"] = now()
        recompute_project(project)
        bump(project)
        return ok(project, 200)

    # DECLARE_SUBSTANTIAL_COMPLETION
    if project["status"] != "UNDER_CONSTRUCTION":
        raise AppError("ERR_PROJECT_INVALID_STATE")
    # ladder step 15 - the task check runs first
    tasks = project_schedule_tasks(project["id"])
    if any(t["status"] != "COMPLETE" for t in tasks):
        raise AppError("ERR_PROJECT_TASKS_INCOMPLETE")
    orders = project_change_orders(project["id"])
    if any(c["status"] in OPEN_CHANGE_ORDER_STATUSES for c in orders):
        raise AppError("ERR_CHANGE_ORDER_PENDING")

    project["status"] = "SUBSTANTIAL_COMPLETION"
    project["substantial_completion_at"] = now()
    project["warranty_starts_at"] = project["substantial_completion_at"]
    project["warranty_expires_at"] = add_days(project["warranty_starts_at"], WARRANTY_BASE_DAYS)
    recompute_project(project)
    bump(project)
    return ok(project, 200)


@bp.post("/projects/<project_id>/final-walkthrough")
def final_walkthrough(project_id):
    user_id, role = authorize(["Client"])
    project = fetch("projects", project_id)
    body = parse_body()
    acknowledged = req_int(body, "acknowledged_open_cosmetic_count", minimum=0)
    own_project(project, user_id, role)

    # ladder step 10
    if project["status"] != "SUBSTANTIAL_COMPLETION":
        raise AppError("ERR_PROJECT_INVALID_STATE")

    tickets = project_defect_tickets(project["id"])
    # ladder step 16
    blocking = [t for t in tickets
                if t["phase"] == "PUNCH"
                and t["severity"] in ("FUNCTIONAL", "LIFE_SAFETY")
                and t["status"] in BLOCKING_DEFECT_STATUSES]
    if blocking:
        raise AppError("ERR_BLOCKING_PUNCH_ITEMS")

    # ladder step 17
    cosmetic = [t for t in tickets
                if t["phase"] == "PUNCH" and t["severity"] == "COSMETIC"
                and t["status"] in BLOCKING_DEFECT_STATUSES]
    if acknowledged != len(cosmetic):
        raise AppError("ERR_PUNCH_ACK_COUNT_MISMATCH")

    # money still in flight blocks the close-out (PRD 3.9)
    for draw in project_draw_requests(project["id"]):
        if draw["status"] in PENDING_DRAW_STATUSES:
            raise AppError("ERR_PROJECT_INVALID_STATE",
                           "A draw request is still with the lender.")

    project["status"] = "FINAL_ACCEPTED"
    project["final_accepted_at"] = now()

    # narrowly-scoped cascade: only OPEN cosmetic punch items are waived
    for ticket in tickets:
        if (ticket["phase"] == "PUNCH" and ticket["severity"] == "COSMETIC"
                and ticket["status"] == "OPEN"):
            ticket["status"] = "WAIVED"
            ticket["resolved_at"] = now()
            bump(ticket)

    bump(project)
    return ok(project, 200)


# ------------------------------------------------------------------ photos
@bp.post("/projects/<project_id>/photo-documents")
def create_photo_document(project_id):
    user_id, role = authorize(["ProjectManager"])
    project = fetch("projects", project_id)
    body = parse_body()
    captured_at = req_dt(body, "captured_at")
    caption = req_str(body, "caption")
    check_staff_identity(user_id, role)

    row = base_row()
    row.update({
        "project_id": project["id"],
        "captured_at": captured_at,
        "caption": caption,
        "visibility": "INTERNAL",
        "published_at": None,
    })
    db.photo_documents[row["id"]] = row
    return ok(row, 201)


@bp.get("/projects/<project_id>/photo-documents")
def list_photo_documents(project_id):
    user_id, role = authorize(PHOTO_LIST_ROLES)
    project = fetch("projects", project_id)
    check_staff_identity(user_id, role)

    rows = ordered([p for p in db.photo_documents.values()
                    if p["project_id"] == project["id"]])
    visibility = qfilter("visibility")
    if visibility:
        rows = [r for r in rows if r["visibility"] == visibility]

    if role == "Client":
        rows = [r for r in rows if r["visibility"] == "CLIENT_PORTAL"]
        client = db.clients.get(user_id)
        if client is not None and client.get("portal_enabled") is False:
            rows = []

    page, meta = paginate(rows)
    return ok_list(page, meta)


@bp.post("/photo-documents/<photo_id>/publish")
def publish_photo_document(photo_id):
    user_id, role = authorize(["ProjectManager"])
    photo = fetch("photo_documents", photo_id)
    check_staff_identity(user_id, role)

    # ladder step 10
    if photo["visibility"] == "CLIENT_PORTAL":
        raise AppError("ERR_PHOTO_ALREADY_PUBLISHED")
    # ladder step 11
    project = db.projects.get(photo["project_id"])
    if project is None or project["status"] == "PLANNING":
        raise AppError("ERR_PROJECT_NOT_ACCEPTING_PHOTOS")

    photo["visibility"] = "CLIENT_PORTAL"
    photo["published_at"] = now()
    bump(photo)
    return ok(photo, 200)
