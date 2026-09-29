"""Deliverables: scope lines, lead assignment and execution (PRD 3.3, 3.6)."""

from decimal import Decimal

from flask import Blueprint, g

from calc import (
    GRADES,
    MAX_CONCURRENT_LEAD_DELIVERABLES,
    has_dependency_cycle,
    windows_overlap,
)
from db import db, new_row, rows, touch
from errors import fail
from middleware import (
    READ_ROLES,
    ROLE_CLIENT,
    ROLE_MANAGER,
    client_scope,
    require_roles,
)
from response import ok
from routes.common import fetch, filtered, fk, paged
from serializers import deliverable_out
from services import economics
from services.cascade import engagement_for_opportunity
from validators import (
    filter_arg,
    get_date,
    get_decimal,
    get_enum,
    get_id,
    get_str,
    json_body,
    parse_date,
)

bp = Blueprint("deliverables", __name__)

STATUSES = ("PLANNED", "IN_PROGRESS", "SUBMITTED", "ACCEPTED", "REWORK", "SUSPENDED")
LEGAL_TRANSITIONS = {
    ("PLANNED", "IN_PROGRESS"),
    ("IN_PROGRESS", "SUBMITTED"),
    ("SUBMITTED", "ACCEPTED"),
    ("SUBMITTED", "REWORK"),
    ("REWORK", "IN_PROGRESS"),
}
MANAGER_TARGETS = ("IN_PROGRESS", "SUBMITTED")
CLIENT_TARGETS = ("ACCEPTED", "REWORK")


def opportunity_deliverables(opportunity_id):
    return [d for d in rows("deliverables") if d["opportunity_id"] == opportunity_id]


def scope_state_guard(opportunity):
    status = opportunity["status"]
    if status in ("SCREENING", "QUALIFIED", "DISQUALIFIED"):
        fail("ERR_OPPORTUNITY_STATE_INVALID", "The pursuit is not open for scope editing.")
    if status != "SCOPING":
        fail("ERR_SCOPE_FROZEN", "The scope has been baselined and is frozen.")


def manager_binding(opportunity):
    if g.user_id != opportunity["scoping_manager_consultant_id"]:
        fail(
            "ERR_NOT_ASSIGNED_TO_ENGAGEMENT",
            "Only the pursuit's scoping manager may perform this operation.",
        )


def check_dependency(opportunity_id, deliverable_id, predecessor_id, current_rows):
    """PRD 3.3: same pursuit, not itself, no cycle -- all ERR_DEPENDENCY_CYCLE."""
    if predecessor_id is None:
        return
    predecessor = db.deliverables.get(predecessor_id)
    if predecessor["opportunity_id"] != opportunity_id:
        fail("ERR_DEPENDENCY_CYCLE", "The predecessor belongs to another pursuit.")
    if deliverable_id is not None and predecessor_id == deliverable_id:
        fail("ERR_DEPENDENCY_CYCLE", "A deliverable may not depend on itself.")
    graph = []
    for d in current_rows:
        edge = d.get("depends_on_deliverable_id")
        if deliverable_id is not None and d["id"] == deliverable_id:
            edge = predecessor_id
        graph.append({"id": d["id"], "depends_on_deliverable_id": edge})
    if deliverable_id is None:
        graph.append({"id": "__new__", "depends_on_deliverable_id": predecessor_id})
    if has_dependency_cycle(graph):
        fail("ERR_DEPENDENCY_CYCLE", "The dependency graph would contain a cycle.")


def quality_gate_failed(engagement_id):
    for review in rows("quality_reviews"):
        if review["engagement_id"] != engagement_id or review["status"] != "FAILED":
            continue
        for esc in rows("risk_escalations"):
            if esc["source_quality_review_id"] == review["id"] and esc["status"] != "RESOLVED":
                return True
    return False


# ------------------------------------------------------------------ create / read / list


@bp.post("/deliverables")
def create_deliverable():
    require_roles(ROLE_MANAGER)
    body = json_body()
    opportunity_id = get_id(body, "opportunity_id")
    name = get_str(body, "name", min_len=1, max_len=160)
    primary_grade = get_enum(body, "primary_grade", GRADES)
    effort = get_decimal(body, "effort_hours_estimate", gt=0, le=5000)
    weight = get_decimal(body, "completion_weight_pct", gt=0, le=100)
    # PRD 3.3 states no length bound on acceptance_criteria; PRD 3.4 checks it is
    # non-empty at baselining (ERR_ACCEPTANCE_CRITERIA_MISSING), so an empty
    # string is accepted here.
    acceptance_criteria = get_str(body, "acceptance_criteria", min_len=0, max_len=None)
    start = get_date(body, "planned_start_date")
    end = get_date(body, "planned_end_date")
    predecessor_id = get_id(body, "depends_on_deliverable_id", required=False)

    if not end > start:
        fail("ERR_INVALID_DATE_RANGE", "planned_end_date must be after planned_start_date.")

    opportunity = fk("opportunities", opportunity_id)
    fk("deliverables", predecessor_id) if predecessor_id else None
    manager_binding(opportunity)
    scope_state_guard(opportunity)
    check_dependency(
        opportunity_id, None, predecessor_id, opportunity_deliverables(opportunity_id)
    )

    row = new_row(
        {
            "opportunity_id": opportunity_id,
            "lead_consultant_id": None,
            "depends_on_deliverable_id": predecessor_id,
            "name": name,
            "primary_grade": primary_grade,
            "effort_hours_estimate": effort,
            "completion_weight_pct": weight,
            "acceptance_criteria": acceptance_criteria,
            "planned_start_date": start.isoformat(),
            "planned_end_date": end.isoformat(),
            "status": "PLANNED",
            "prior_status": None,
            "line_cost_cents": None,
            "hours_consumed": Decimal("0.00"),
        }
    )
    db.deliverables[row["id"]] = row
    return ok(deliverable_out(row), 201)


@bp.get("/deliverables/<deliverable_id>")
def read_deliverable(deliverable_id):
    require_roles(*READ_ROLES)
    row = fetch("deliverables", deliverable_id)
    opportunity = db.opportunities.get(row["opportunity_id"])
    if opportunity is not None:
        client_scope(opportunity["client_id"])
    return ok(deliverable_out(row))


@bp.get("/deliverables")
def list_deliverables():
    require_roles(*READ_ROLES)
    opportunity_id = filter_arg("opportunity_id")
    lead = filter_arg("lead_consultant_id")
    predecessor = filter_arg("depends_on_deliverable_id")
    status = filter_arg("status")
    own_client = g.user_id if g.role == ROLE_CLIENT else None

    def keep(row):
        if opportunity_id is not None and row["opportunity_id"] != opportunity_id:
            return False
        if lead is not None and row["lead_consultant_id"] != lead:
            return False
        if predecessor is not None and row["depends_on_deliverable_id"] != predecessor:
            return False
        if status is not None and row["status"] != status:
            return False
        if own_client is not None:
            opportunity = db.opportunities.get(row["opportunity_id"])
            if opportunity is None or opportunity["client_id"] != own_client:
                return False
        return True

    return paged(filtered("deliverables", keep), deliverable_out)


# ------------------------------------------------------------------ edit


@bp.patch("/deliverables/<deliverable_id>")
def patch_deliverable(deliverable_id):
    require_roles(ROLE_MANAGER)
    row = fetch("deliverables", deliverable_id)
    opportunity = db.opportunities.get(row["opportunity_id"])
    if opportunity is not None:
        manager_binding(opportunity)

    body = json_body()
    name = get_str(body, "name", required=False, min_len=1, max_len=160)
    primary_grade = get_enum(body, "primary_grade", GRADES, required=False)
    effort = get_decimal(body, "effort_hours_estimate", required=False, gt=0, le=5000)
    weight = get_decimal(body, "completion_weight_pct", required=False, gt=0, le=100)
    acceptance_criteria = get_str(
        body, "acceptance_criteria", required=False, min_len=0, max_len=None
    )
    start = get_date(body, "planned_start_date", required=False)
    end = get_date(body, "planned_end_date", required=False)
    predecessor_supplied = "depends_on_deliverable_id" in body
    predecessor_id = get_id(body, "depends_on_deliverable_id", required=False)

    effective_start = start if start is not None else parse_date(row["planned_start_date"])
    effective_end = end if end is not None else parse_date(row["planned_end_date"])
    if not effective_end > effective_start:
        fail("ERR_INVALID_DATE_RANGE", "planned_end_date must be after planned_start_date.")

    if predecessor_id is not None:
        fk("deliverables", predecessor_id)
    scope_state_guard(opportunity)
    if predecessor_supplied and predecessor_id is not None:
        check_dependency(
            row["opportunity_id"],
            row["id"],
            predecessor_id,
            opportunity_deliverables(row["opportunity_id"]),
        )

    if name is not None:
        row["name"] = name
    if primary_grade is not None:
        row["primary_grade"] = primary_grade
    if effort is not None:
        row["effort_hours_estimate"] = effort
    if weight is not None:
        row["completion_weight_pct"] = weight
    if acceptance_criteria is not None:
        row["acceptance_criteria"] = acceptance_criteria
    if start is not None:
        row["planned_start_date"] = start.isoformat()
    if end is not None:
        row["planned_end_date"] = end.isoformat()
    if predecessor_supplied:
        row["depends_on_deliverable_id"] = predecessor_id
    touch(row)
    return ok(deliverable_out(row))


# ------------------------------------------------------------------ lead assignment


@bp.post("/deliverables/<deliverable_id>/assign-lead")
def assign_lead(deliverable_id):
    require_roles(ROLE_MANAGER)
    row = fetch("deliverables", deliverable_id)
    opportunity = db.opportunities.get(row["opportunity_id"])
    engagement = engagement_for_opportunity(row["opportunity_id"])
    allowed = set()
    if opportunity is not None:
        allowed.add(opportunity["scoping_manager_consultant_id"])
    if engagement is not None and engagement["engagement_manager_consultant_id"]:
        allowed.add(engagement["engagement_manager_consultant_id"])
    if g.user_id not in allowed:
        fail(
            "ERR_NOT_ASSIGNED_TO_ENGAGEMENT",
            "Only the pursuit's scoping manager may assign a deliverable lead.",
        )

    body = json_body()
    lead_id = get_id(body, "lead_consultant_id")
    consultant = fk("consultants", lead_id)

    if opportunity is not None and consultant["practice_code"] != opportunity[
        "requested_practice_code"
    ]:
        fail(
            "ERR_CONSULTANT_PRACTICE_MISMATCH",
            "The consultant's practice does not match the pursuit's requested practice.",
        )

    start = parse_date(row["planned_start_date"])
    end = parse_date(row["planned_end_date"])
    overlapping = 0
    for other in rows("deliverables"):
        if other["id"] == row["id"]:
            continue
        if other["lead_consultant_id"] != lead_id or other["status"] == "ACCEPTED":
            continue
        if windows_overlap(
            start, end, parse_date(other["planned_start_date"]), parse_date(other["planned_end_date"])
        ):
            overlapping += 1
    if overlapping >= MAX_CONCURRENT_LEAD_DELIVERABLES:
        fail(
            "ERR_CONSULTANT_CAPACITY_CONFLICT",
            "The consultant already leads two overlapping deliverables.",
        )

    row["lead_consultant_id"] = lead_id
    touch(row)
    touch(consultant)
    return ok(deliverable_out(row))


# ------------------------------------------------------------------ execution


@bp.post("/deliverables/<deliverable_id>/status")
def change_status(deliverable_id):
    require_roles(ROLE_MANAGER, ROLE_CLIENT)
    row = fetch("deliverables", deliverable_id)
    opportunity = db.opportunities.get(row["opportunity_id"])
    engagement = engagement_for_opportunity(row["opportunity_id"])

    if g.role == ROLE_CLIENT:
        if opportunity is not None:
            client_scope(opportunity["client_id"])
    else:
        if engagement is None or g.user_id != engagement["engagement_manager_consultant_id"]:
            fail(
                "ERR_NOT_ASSIGNED_TO_ENGAGEMENT",
                "Only the engagement manager may drive this deliverable.",
            )

    body = json_body()
    target = get_enum(body, "target_status", STATUSES)

    if (row["status"], target) not in LEGAL_TRANSITIONS:
        fail(
            "ERR_DELIVERABLE_STATE_INVALID",
            "%s is not reachable from %s." % (target, row["status"]),
        )
    if g.role == ROLE_CLIENT and target not in CLIENT_TARGETS:
        fail("ERR_FORBIDDEN_ROLE", "A client contact may not request %s." % target)
    if g.role == ROLE_MANAGER and target not in MANAGER_TARGETS:
        fail("ERR_FORBIDDEN_ROLE", "An engagement manager may not request %s." % target)

    if engagement is None or engagement["delivery_state"] != "ACTIVE":
        fail("ERR_ENGAGEMENT_STATE_INVALID", "The engagement's delivery is not ACTIVE.")
    if quality_gate_failed(engagement["id"]):
        fail("ERR_QUALITY_GATE_FAILED", "A failed quality checkpoint is still unresolved.")

    if row["status"] == "PLANNED" and target == "IN_PROGRESS":
        predecessor_id = row["depends_on_deliverable_id"]
        if predecessor_id is not None:
            predecessor = db.deliverables.get(predecessor_id)
            if predecessor is None or predecessor["status"] != "ACCEPTED":
                fail("ERR_DEPENDENCY_NOT_ACCEPTED", "The predecessor has not been accepted.")
        if row["lead_consultant_id"] is None:
            fail("ERR_DELIVERABLE_LEAD_UNASSIGNED", "No lead consultant has been assigned.")

    row["status"] = target
    touch(row)
    if target == "ACCEPTED":
        economics.recompute(engagement)
    return ok(deliverable_out(row))
