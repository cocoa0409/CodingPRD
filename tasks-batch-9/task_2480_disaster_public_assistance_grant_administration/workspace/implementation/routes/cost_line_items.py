"""CostLineItem endpoints: claim creation and eligibility review."""
from datetime import timedelta

from flask import Blueprint

from db import db, new_row, now_iso, parse_instant, setf, touch
from errors import fail
from middleware import ALL_ROLES, authenticate, check_scope
from routes.common import PREFIX, find, render_list, require, respond
from services.calc import cost_line_item_eligible_cost, dec, equipment_cap_exceeded
from services.constants import (
    COST_LINE_OPEN_PROJECT_STATUSES,
    COST_TYPES,
    LABOR_REST_BUFFER_MINUTES,
)
from services.ledger import (
    applicant_of_project,
    disaster_of_project,
)
from validate import body, present, v_id, v_enum, v_instant, v_int, v_num

bp = Blueprint("cost_line_items", __name__)


def _days_touched(start, end):
    days = set()
    cursor = start.date()
    last = end.date()
    while cursor <= last:
        days.add(cursor)
        cursor = cursor + timedelta(days=1)
    return days


@bp.route(PREFIX + "/cost-line-items", methods=["POST"])
def create_line():
    actor = authenticate(("ApplicantAgent",))
    payload = body()

    raw_project = payload.get("project_id")
    if isinstance(raw_project, str):
        project = find("projects", raw_project)
        if project is not None:
            check_scope(actor, project["applicant_id"])

    project_id = v_id(payload, "project_id")
    cost_type = v_enum(payload, "cost_type", COST_TYPES)
    claimed_cents = v_int(payload, "claimed_cents", minimum=0)
    work_start_at = v_instant(payload, "work_start_at")
    work_end_at = v_instant(payload, "work_end_at")
    resource_id = v_id(payload, "force_account_resource_id", required=False, default=None)
    contract_id = v_id(payload, "contract_id", required=False, default=None)
    straight_time_hours = v_num(payload, "straight_time_hours", required=False,
                                default=0, minimum=0)
    overtime_hours = v_num(payload, "overtime_hours", required=False, default=0,
                           minimum=0)
    equipment_hours = v_num(payload, "equipment_hours", required=False, default=0,
                            minimum=0)

    start = parse_instant(work_start_at)
    end = parse_instant(work_end_at)
    if end <= start:
        fail("ERR_INVALID_REQUEST", "work_end_at must be after work_start_at")

    if cost_type in ("FORCE_ACCOUNT_LABOR", "FORCE_ACCOUNT_EQUIPMENT"):
        if resource_id is None:
            fail("ERR_INVALID_REQUEST",
                 "force_account_resource_id is required for %s" % cost_type)
        if contract_id is not None:
            fail("ERR_INVALID_REQUEST", "contract_id must be null for %s" % cost_type)
    elif cost_type == "CONTRACT":
        if contract_id is None:
            fail("ERR_INVALID_REQUEST", "contract_id is required for CONTRACT")
        if resource_id is not None:
            fail("ERR_INVALID_REQUEST",
                 "force_account_resource_id must be null for CONTRACT")
    else:  # MATERIALS
        if resource_id is not None or contract_id is not None:
            fail("ERR_INVALID_REQUEST",
                 "MATERIALS lines carry neither a resource nor a contract")

    project = require("projects", project_id)
    resource = require("force_account_resources", resource_id) if resource_id else None
    contract = require("contracts", contract_id) if contract_id else None

    if project["status"] not in COST_LINE_OPEN_PROJECT_STATUSES:
        fail("ERR_COST_LINE_ITEM_LOCKED",
             "cost line items are locked in project status %s" % project["status"])

    disaster = disaster_of_project(project)
    if disaster is not None:
        low = parse_instant(disaster["incident_start_at"])
        high = parse_instant(disaster["incident_end_at"])
        if not (low <= start and end <= high):
            fail("ERR_OUTSIDE_INCIDENT_PERIOD",
                 "the charged work interval falls outside the incident period")

    if cost_type == "CONTRACT" and contract["procurement_status"] == "NONCOMPLIANT":
        fail("ERR_PROCUREMENT_NONCOMPLIANT",
             "the contract failed procurement compliance review")

    applicant = applicant_of_project(project)
    if applicant is None or applicant["eligibility_status"] != "ELIGIBLE":
        fail("ERR_APPLICANT_NOT_ELIGIBLE", "the applicant is not ELIGIBLE")

    if resource is not None and resource["applicant_id"] != project["applicant_id"]:
        fail("ERR_CROSS_APPLICANT_REFERENCE",
             "the resource belongs to another applicant")
    if contract is not None and contract["applicant_id"] != project["applicant_id"]:
        fail("ERR_CROSS_APPLICANT_REFERENCE",
             "the contract belongs to another applicant")

    if cost_type == "FORCE_ACCOUNT_LABOR":
        buffer = timedelta(minutes=LABOR_REST_BUFFER_MINUTES)
        low = start - buffer
        high = end + buffer
        for other in db.cost_line_items.values():
            if other["force_account_resource_id"] != resource_id:
                continue
            if other["cost_type"] != "FORCE_ACCOUNT_LABOR":
                continue
            other_start = parse_instant(other["work_start_at"])
            other_end = parse_instant(other["work_end_at"])
            if other_start is None or other_end is None:
                continue
            if low <= other_end and other_start <= high:
                fail("ERR_LABOR_ENTRY_OVERLAP",
                     "this labor interval collides with an existing entry")

    if cost_type == "FORCE_ACCOUNT_EQUIPMENT":
        existing = []
        for other in db.cost_line_items.values():
            if other["force_account_resource_id"] != resource_id:
                continue
            if other["cost_type"] != "FORCE_ACCOUNT_EQUIPMENT":
                continue
            other_start = parse_instant(other["work_start_at"])
            other_end = parse_instant(other["work_end_at"])
            if other_start is None or other_end is None:
                continue
            existing.append((_days_touched(other_start, other_end),
                             other["equipment_hours"]))
        if equipment_cap_exceeded(_days_touched(start, end), equipment_hours, existing):
            fail("ERR_EQUIPMENT_DAILY_HOURS_EXCEEDED",
                 "the daily equipment hours cap would be exceeded")

    row = new_row("cost_line_items", {
        "project_id": project_id,
        "cost_type": cost_type,
        "force_account_resource_id": resource_id,
        "contract_id": contract_id,
        "claimed_cents": claimed_cents,
        "work_start_at": work_start_at,
        "work_end_at": work_end_at,
        "straight_time_hours": straight_time_hours,
        "overtime_hours": overtime_hours,
        "equipment_hours": equipment_hours,
        "eligible_cents": 0,
        "review_status": "SUBMITTED",
        "disallowance_reason": None,
        "reviewed_at": None,
    })
    return respond(row, 201)


@bp.route(PREFIX + "/cost-line-items", methods=["GET"])
def list_lines():
    authenticate(ALL_ROLES)
    return render_list("cost_line_items", {
        "project_id": "project_id",
        "force_account_resource_id": "force_account_resource_id",
        "contract_id": "contract_id",
        "review_status": "review_status",
        "cost_type": "cost_type",
    })


@bp.route(PREFIX + "/cost-line-items/<cost_line_item_id>", methods=["GET"])
def get_line(cost_line_item_id):
    actor = authenticate(ALL_ROLES)
    line = find("cost_line_items", cost_line_item_id)
    if line is not None:
        project = find("projects", line["project_id"])
        if project is not None:
            check_scope(actor, project["applicant_id"])
    line = require("cost_line_items", cost_line_item_id)
    return respond(line)


@bp.route(PREFIX + "/cost-line-items/<cost_line_item_id>/review", methods=["POST"])
def review_line(cost_line_item_id):
    authenticate(("ProgramSpecialist",))
    line = require("cost_line_items", cost_line_item_id)

    project = find("projects", line["project_id"])
    if project is None or project["status"] not in COST_LINE_OPEN_PROJECT_STATUSES:
        fail("ERR_COST_LINE_ITEM_LOCKED",
             "cost line item review is locked in this project status")

    resource = find("force_account_resources", line["force_account_resource_id"]) \
        if line["force_account_resource_id"] else None
    contract = find("contracts", line["contract_id"]) if line["contract_id"] else None

    if line["cost_type"] == "CONTRACT" and contract is not None \
            and contract["procurement_status"] == "PENDING_REVIEW":
        fail("ERR_PROCUREMENT_REVIEW_PENDING",
             "the contract has not been through procurement review")

    # PRD 3.5: the ceiling counts only siblings whose created_at is *strictly*
    # earlier than this line's; the row identifier is never an ordering key, and
    # lines sharing an instant therefore do not consume each other's headroom.
    siblings = []
    if contract is not None:
        for other in db.cost_line_items.values():
            if other["id"] == line["id"]:
                continue
            if other["contract_id"] != contract["id"]:
                continue
            if other["created_at"] < line["created_at"]:
                siblings.append(other)

    eligible, status, reason = cost_line_item_eligible_cost(
        line, project, resource, contract, siblings
    )
    setf(line, "eligible_cents", eligible)
    setf(line, "review_status", status)
    setf(line, "disallowance_reason", reason)
    setf(line, "reviewed_at", now_iso())
    touch(line)

    if resource is not None:
        total = dec(0)
        for other in db.cost_line_items.values():
            if other["force_account_resource_id"] != resource["id"]:
                continue
            total += (dec(other["straight_time_hours"])
                      + dec(other["overtime_hours"])
                      + dec(other["equipment_hours"]))
        setf(resource, "charged_hours_total", float(total))

    if contract is not None:
        allowed = sum(other["eligible_cents"] for other in db.cost_line_items.values()
                      if other["contract_id"] == contract["id"]
                      and other["review_status"] in ("ALLOWED", "PARTIALLY_ALLOWED"))
        setf(contract, "allowed_cost_total_cents", allowed)

    return respond(line)
