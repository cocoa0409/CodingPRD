"""Position endpoints: create / get / list / patch / lifecycle / reports
(PRD §3.2, §3.3, §3.8)."""
from flask import Blueprint, request

from db import db
from errors import err
from middleware import require_auth
from response import success, list_success
from services import serialize, calc
from services.common import (
    get_body, require_string, validate_fte, base_common_fields, fetch,
    paginate, bump,
)

bp = Blueprint("positions", __name__)

ALL_ROLES = ["HRBP", "HRDirector", "FinanceController", "CompensationAnalyst"]


def _span_gate(manager_id, exclude_position_id=None):
    """Reject if adding/repointing a report would push manager's non-ABOLISHED
    direct-report count to 9. Reaching exactly 8 is allowed (PRD §3.2)."""
    count = 0
    for p in db.positions.values():
        if p["id"] == exclude_position_id:
            continue
        if p["manager_position_id"] == manager_id and p["lifecycle_status"] != "ABOLISHED":
            count += 1
    if count + 1 > calc.MAX_SPAN_OF_CONTROL:
        raise err("ERR_SPAN_LIMIT_EXCEEDED", "manager would exceed MAX_SPAN_OF_CONTROL")


@bp.post("/positions")
def create_position():
    require_auth(["HRBP"])
    body = get_body()
    cost_center_id = require_string(body, "cost_center_id")
    grade_id = require_string(body, "grade_id")
    title = require_string(body, "title")
    if body.get("fte") is None:
        raise err("ERR_INVALID_REQUEST", "missing required field: fte")
    fte = validate_fte(body.get("fte"))
    manager_position_id = body.get("manager_position_id")
    if manager_position_id is not None and not isinstance(manager_position_id, str):
        raise err("ERR_INVALID_REQUEST", "manager_position_id must be a string or null")

    # Existence (priority 3): path has none; resolve body FKs left-to-right.
    cc = fetch(db.cost_centers, cost_center_id)
    fetch(db.grades, grade_id)
    if manager_position_id is not None:
        fetch(db.positions, manager_position_id)

    # Span gate on the prospective manager (priority 8).
    if manager_position_id is not None:
        _span_gate(manager_position_id)

    rec = base_common_fields()
    rec.update({
        "cost_center_id": cost_center_id,
        "grade_id": grade_id,
        "manager_position_id": manager_position_id,
        "title": title,
        "fte": fte,
        "lifecycle_status": "DRAFT",
        "occupancy_status": "VACANT",
    })
    db.positions[rec["id"]] = rec
    return success(serialize.position_out(rec), status=201)


@bp.get("/positions/<position_id>")
def get_position(position_id):
    require_auth(ALL_ROLES)
    rec = fetch(db.positions, position_id)
    return success(serialize.position_out(rec))


@bp.get("/positions")
def list_positions():
    require_auth(ALL_ROLES)
    records = list(db.positions.values())
    for field in ("cost_center_id", "grade_id", "manager_position_id",
                  "lifecycle_status", "occupancy_status"):
        val = request.args.get(field)
        if val is not None:
            records = [r for r in records if r[field] == val]
    page, limit, offset, total = paginate(records)
    return list_success([serialize.position_out(r) for r in page], limit, offset, total)


@bp.patch("/positions/<position_id>")
def patch_position(position_id):
    require_auth(["HRBP"])
    pos = fetch(db.positions, position_id)
    body = get_body()

    new_title = body.get("title")
    new_fte = body.get("fte")
    has_manager_key = "manager_position_id" in body
    new_manager = body.get("manager_position_id")

    # Well-formedness (priority 4).
    if new_title is not None and (not isinstance(new_title, str) or new_title == ""):
        raise err("ERR_INVALID_REQUEST", "title must be a non-empty string")
    if new_fte is not None:
        new_fte = validate_fte(new_fte)
    if has_manager_key and new_manager is not None and not isinstance(new_manager, str):
        raise err("ERR_INVALID_REQUEST", "manager_position_id must be a string or null")

    # Existence of a new manager (priority 3).
    if has_manager_key and new_manager is not None:
        fetch(db.positions, new_manager)

    # fte/title editable only while DRAFT or REQUISITIONED (PRD §3.2).
    # (manager repoint follows the same editable window.)
    editable = pos["lifecycle_status"] in ("DRAFT", "REQUISITIONED")
    if (new_fte is not None or new_title is not None or has_manager_key) and not editable:
        raise err("ERR_INVALID_STATE", "position not editable in its current lifecycle state")

    # Span gate on the prospective new manager (priority 8).
    if has_manager_key and new_manager is not None and new_manager != pos["manager_position_id"]:
        _span_gate(new_manager, exclude_position_id=pos["id"])

    changed = False
    if new_title is not None:
        pos["title"] = new_title
        changed = True
    if new_fte is not None:
        pos["fte"] = new_fte
        changed = True
    if has_manager_key:
        pos["manager_position_id"] = new_manager
        changed = True

    if changed:
        bump(pos)
    return success(serialize.position_out(pos))


@bp.get("/cost-centers/<cost_center_id>/positions")
def list_cc_positions(cost_center_id):
    require_auth(ALL_ROLES)
    fetch(db.cost_centers, cost_center_id)
    records = [p for p in db.positions.values() if p["cost_center_id"] == cost_center_id]
    lifecycle = request.args.get("lifecycle_status")
    if lifecycle is not None:
        records = [r for r in records if r["lifecycle_status"] == lifecycle]
    page, limit, offset, total = paginate(records)
    return list_success([serialize.position_out(r) for r in page], limit, offset, total)


@bp.get("/positions/<position_id>/reports")
def list_position_reports(position_id):
    require_auth(ALL_ROLES)
    fetch(db.positions, position_id)
    records = [p for p in db.positions.values() if p["manager_position_id"] == position_id]
    page, limit, offset, total = paginate(records)
    return list_success([serialize.position_out(r) for r in page], limit, offset, total)


# --- Lifecycle: REQUISITION | FUND | ABOLISH --------------------------------
@bp.post("/positions/<position_id>/lifecycle")
def position_lifecycle(position_id):
    # All three actors share this endpoint; per-action role is enforced below
    # after the action is known. Auth (priority 1/2) requires a recognised role
    # that could perform some action here.
    require_auth(["HRBP", "FinanceController", "HRDirector"])
    pos = fetch(db.positions, position_id)
    body = get_body()
    action = body.get("action")
    if action not in ("REQUISITION", "FUND", "ABOLISH"):
        raise err("ERR_INVALID_REQUEST", "action must be REQUISITION, FUND or ABOLISH")

    if action == "REQUISITION":
        return _requisition(pos, body)
    if action == "FUND":
        return _fund(pos, body)
    return _abolish(pos, body)


def _require_role(role, allowed):
    if role not in allowed:
        raise err("ERR_FORBIDDEN", "role not permitted for this action")


def _requisition(pos, body):
    from middleware import get_principal
    _, role = get_principal()
    _require_role(role, ["HRBP"])
    # State (priority 6).
    if pos["lifecycle_status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "position must be DRAFT to requisition")
    # Frozen gate (priority 7).
    cc = db.cost_centers[pos["cost_center_id"]]
    if calc.cost_center_posture(cc["id"]) == "FROZEN":
        raise err("ERR_COST_CENTER_FROZEN", "owning cost center is frozen")
    pos["lifecycle_status"] = "REQUISITIONED"
    bump(pos)
    return success(serialize.position_out(pos))


def _fund(pos, body):
    from middleware import get_principal
    _, role = get_principal()
    _require_role(role, ["FinanceController"])
    cc = db.cost_centers[pos["cost_center_id"]]

    # OCC (priority 5) — expected_cost_center_version required for FUND.
    expected = body.get("expected_cost_center_version")
    if expected is not None:
        if isinstance(expected, bool) or not isinstance(expected, int):
            raise err("ERR_INVALID_REQUEST", "expected_cost_center_version must be an integer")
        if expected != cc["version"]:
            raise err("ERR_STALE_VERSION", "cost center version is stale")

    # State (priority 6).
    if pos["lifecycle_status"] != "REQUISITIONED":
        raise err("ERR_INVALID_STATE", "position must be REQUISITIONED to fund")

    # Frozen gate (priority 7).
    if calc.cost_center_posture(cc["id"]) == "FROZEN":
        raise err("ERR_COST_CENTER_FROZEN", "owning cost center is frozen")

    override = body.get("override") is True

    # FTE cap (priority 12) then budget (priority 13).
    headroom_fte = float(cc["fte_cap"]) - calc.committed_fte(cc["id"])
    delta_fte = pos["fte"]
    # Compare with a tiny epsilon tolerance for float aggregation noise; equality
    # is admitted (PRD §3.3).
    if delta_fte > headroom_fte + 1e-9:
        raise err("ERR_FTE_CAP_EXCEEDED", "funding would exceed fte_cap")

    headroom_cents = calc.adjusted_budget_cents(cc) - calc.committed_cost_cents(cc["id"])
    delta_cost = calc.planned_cost_cents(pos)
    if delta_cost > headroom_cents and not override:
        raise err("ERR_BUDGET_EXCEEDED", "funding would exceed budget")

    pos["lifecycle_status"] = "FUNDED"
    bump(pos)
    # Funding consumes the shared pool: bump the cost center's version (PRD §3.3).
    bump(cc)
    return success(serialize.position_out(pos))


def _abolish(pos, body):
    from middleware import get_principal
    _, role = get_principal()
    _require_role(role, ["HRDirector"])
    cc = db.cost_centers[pos["cost_center_id"]]

    # State (priority 6): abolishable from REQUISITIONED or FUNDED.
    if pos["lifecycle_status"] not in ("REQUISITIONED", "FUNDED"):
        raise err("ERR_INVALID_STATE", "position must be REQUISITIONED or FUNDED to abolish")

    # Has-direct-reports guard (priority 9).
    for child in db.positions.values():
        if child["manager_position_id"] == pos["id"] and child["lifecycle_status"] != "ABOLISHED":
            raise err("ERR_HAS_DIRECT_REPORTS", "position has non-ABOLISHED direct reports")

    was_funded = pos["lifecycle_status"] == "FUNDED"
    pos["lifecycle_status"] = "ABOLISHED"

    if was_funded:
        # Vacate active incumbent if FILLED (cascade hop 2).
        if pos["occupancy_status"] == "FILLED":
            for inc in db.incumbents.values():
                if inc["position_id"] == pos["id"] and inc["status"] == "ACTIVE":
                    inc["status"] = "VACATED"
                    inc["end_date"] = inc["start_date"]
                    bump(inc)
                    emp = db.employees.get(inc["employee_id"])
                    if emp is not None:
                        emp["status"] = "AVAILABLE"
                        bump(emp)
            pos["occupancy_status"] = "VACANT"
        # OPEN/SUSPENDED requisitions -> CANCELLED (cascade hop 2).
        for r in db.requisitions.values():
            if r["position_id"] == pos["id"] and r["status"] in ("OPEN", "SUSPENDED"):
                r["status"] = "CANCELLED"
                bump(r)
        # SUBMITTED/UNDER_REVIEW reclass requests -> REJECTED (cascade hop 2).
        for rc in db.reclass_requests.values():
            if rc["position_id"] == pos["id"] and rc["status"] in ("SUBMITTED", "UNDER_REVIEW"):
                rc["status"] = "REJECTED"
                bump(rc)

    bump(pos)
    return success(serialize.position_out(pos))
