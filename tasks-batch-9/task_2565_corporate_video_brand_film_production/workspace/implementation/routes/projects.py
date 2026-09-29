"""Projects and budget lines (PRD 3.1, 3.2, 3.10)."""

from flask import Blueprint, request

import calc
import derive
import workflow
from auth import authenticate
from envelope import respond_created, respond_list, respond_object
from errors import ApiError
from lookups import find_project
from store import db, new_row, touch
from validation import (field_enum, field_enum_array, field_integer, field_number,
                        field_string, json_body, paginate, pagination)

bp = Blueprint("projects", __name__)

CHANNELS = ("BROADCAST", "OLV", "SOCIAL", "INTERNAL", "OOH")
BUDGET_CATEGORIES = ("CREW", "EQUIPMENT", "LOCATION", "TALENT", "POST")

READ_ROLES = ("ProductionCoordinator", "LineProducer", "PostSupervisor",
              "ClientApprover", "ComplianceOfficer")


@bp.get("/projects/<project_id>")
def read_project(project_id):
    authenticate(READ_ROLES)
    project = find_project(project_id)
    return respond_object(derive.project_out(project))


@bp.get("/projects/<project_id>/budget-lines")
def list_project_budget_lines(project_id):
    authenticate(("ProductionCoordinator", "LineProducer", "ClientApprover"))
    limit, offset = pagination()
    project = find_project(project_id)
    rows = derive.project_budget_lines(project["id"])
    category = request.args.get("category")
    if category is not None:
        rows = [r for r in rows if r["category"] == category]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
    page, total = paginate(rows, limit, offset)
    return respond_list([derive.budget_line_out(r) for r in page], limit, offset, total)


@bp.get("/projects/<project_id>/deliverables")
def list_project_deliverables(project_id):
    authenticate(("ProductionCoordinator", "LineProducer", "PostSupervisor", "ClientApprover"))
    limit, offset = pagination()
    project = find_project(project_id)
    rows = derive.project_deliverables(project["id"])
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    channel = request.args.get("channel")
    if channel is not None:
        rows = [r for r in rows if r["channel"] == channel]
    rows = sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
    page, total = paginate(rows, limit, offset)
    return respond_list([derive.deliverable_out(r) for r in page], limit, offset, total)


@bp.get("/projects/<project_id>/talent-engagements")
def list_project_engagements(project_id):
    authenticate(("ProductionCoordinator", "LineProducer"))
    limit, offset = pagination()
    project = find_project(project_id)
    rows = derive.project_engagements(project["id"])
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    model = request.args.get("compensation_model")
    if model is not None:
        rows = [r for r in rows if r["compensation_model"] == model]
    rows = sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
    page, total = paginate(rows, limit, offset)
    return respond_list([derive.talent_engagement_out(r) for r in page], limit, offset, total)


@bp.post("/projects")
def create_project():
    authenticate(("LineProducer",))
    body = json_body()
    client_name = field_string(body, "client_name", 1, 120)
    campaign_title = field_string(body, "campaign_title", 1, 120)
    creative_brief_summary = field_string(body, "creative_brief_summary", 10, 2000)
    channel_scope = field_enum_array(body, "channel_scope", CHANNELS)
    usage_term_months = field_integer(body, "usage_term_months", 1, 60)
    budget_ceiling_cents = field_integer(body, "budget_ceiling_cents", minimum=1)
    contracted_revision_rounds = field_integer(
        body, "contracted_revision_rounds", 0, 10, required=False, default=2)
    raw_footage_retention_months = field_integer(
        body, "raw_footage_retention_months", 0, 120, required=False, default=12)
    raw_footage_terabytes = field_number(
        body, "raw_footage_terabytes", minimum=0, required=False, default=0)

    row = new_row(
        client_name=client_name,
        campaign_title=campaign_title,
        creative_brief_summary=creative_brief_summary,
        channel_scope=channel_scope,
        usage_term_months=usage_term_months,
        contracted_revision_rounds=contracted_revision_rounds,
        budget_ceiling_cents=budget_ceiling_cents,
        raw_footage_retention_months=raw_footage_retention_months,
        raw_footage_terabytes=raw_footage_terabytes,
        status="DRAFT",
        approved_budget_cents=None,
        handover_at=None,
        handover_recipient=None,
    )
    db["projects"][row["id"]] = row
    return respond_created(derive.project_out(row))


@bp.post("/projects/<project_id>/lock-scope")
def lock_scope(project_id):
    authenticate(("LineProducer",))
    project = find_project(project_id)
    if project["status"] != "DRAFT":
        raise ApiError("ERR_PROJECT_STATE_INVALID",
                       "Scope lock requires project status DRAFT.")
    deliverables = derive.project_deliverables(project["id"])
    budget_lines = derive.project_budget_lines(project["id"])
    if not deliverables or not budget_lines:
        raise ApiError("ERR_SCOPE_INCOMPLETE",
                       "Scope lock requires at least one deliverable and one budget line.")
    for deliverable in deliverables:
        if deliverable["usage_rights_months"] > project["usage_term_months"]:
            raise ApiError("ERR_USAGE_RIGHTS_EXCEED_TERM",
                           "A deliverable's usage_rights_months exceeds the project term.")
    project["status"] = "SCOPED"
    touch(project)
    return respond_object(derive.project_out(project))


@bp.post("/projects/<project_id>/approve-budget")
def approve_budget(project_id):
    authenticate(("ClientApprover",))
    body = json_body()
    field_integer(body, "approved_budget_cents", minimum=0)
    project = find_project(project_id)
    if project["status"] != "SCOPED":
        raise ApiError("ERR_PROJECT_STATE_INVALID",
                       "Budget approval requires project status SCOPED.")
    budget_lines = derive.project_budget_lines(project["id"])
    if not budget_lines:
        raise ApiError("ERR_SCOPE_INCOMPLETE",
                       "Budget approval requires at least one budget line.")
    provisional = derive.provisional_cost_cents(project)
    if provisional > project["budget_ceiling_cents"]:
        raise ApiError("ERR_BUDGET_CEILING_EXCEEDED",
                       "Provisional cost %d exceeds the contracted ceiling %d."
                       % (provisional, project["budget_ceiling_cents"]))
    # The stored baseline is the provisional figure evaluated at this instant.
    project["approved_budget_cents"] = provisional
    project["status"] = "IN_PRODUCTION"
    touch(project)
    for line in budget_lines:
        if line["status"] == "PLANNED":
            line["status"] = "COMMITTED"
            touch(line)
    return respond_object(derive.project_out(project))


@bp.post("/projects/<project_id>/handover")
def handover(project_id):
    authenticate(("LineProducer",))
    body = json_body()
    recipient = field_string(body, "handover_recipient", 1, 200)
    project = find_project(project_id)
    if project["status"] != "DELIVERED":
        raise ApiError("ERR_PROJECT_STATE_INVALID",
                       "Handover requires project status DELIVERED.")
    if derive.archive_status(project) != "NOT_PACKAGED":
        raise ApiError("ERR_ARCHIVE_ALREADY_HANDED_OVER",
                       "This project has already been handed over.")
    workflow.perform_handover(project, recipient)
    return respond_object(derive.project_out(project))


@bp.post("/budget-lines")
def create_budget_line():
    authenticate(("LineProducer",))
    body = json_body()
    project_id = field_string(body, "project_id", 1, None)
    category = field_enum(body, "category", BUDGET_CATEGORIES)
    description = field_string(body, "description", 1, 200)
    quantity = field_number(body, "quantity", exclusive_min=0)
    unit_rate_cents = field_integer(body, "unit_rate_cents", minimum=0)
    markup_pct = field_number(body, "markup_pct", minimum=0, maximum=float(calc.MAX_MARKUP_PCT),
                              required=False, default=0)

    project = find_project(project_id)
    if project["status"] not in ("DRAFT", "SCOPED", "IN_PRODUCTION", "IN_POST"):
        raise ApiError("ERR_PROJECT_STATE_INVALID",
                       "Budget lines may not be added while the project is %s."
                       % project["status"])
    extended_cents = calc.budget_line_extended_cents(quantity, unit_rate_cents, markup_pct)
    workflow.enforce_allowance(project, extended_cents)

    status = "COMMITTED" if project["status"] in ("IN_PRODUCTION", "IN_POST") else "PLANNED"
    watch = workflow.LedgerWatch(project)
    row = new_row(
        project_id=project["id"],
        category=category,
        description=description,
        quantity=quantity,
        unit_rate_cents=unit_rate_cents,
        markup_pct=markup_pct,
        extended_cents=extended_cents,
        status=status,
    )
    db["budget_lines"][row["id"]] = row
    watch.finish()
    return respond_created(derive.budget_line_out(row))
