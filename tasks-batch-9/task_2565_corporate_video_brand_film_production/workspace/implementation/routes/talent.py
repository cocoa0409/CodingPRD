"""Talent engagements: buyout loads and union session-and-reuse fees (PRD 3.3)."""

from flask import Blueprint

import derive
import workflow
from auth import authenticate
from envelope import respond_created, respond_object
from errors import ApiError
from lookups import find_engagement, find_project
from store import db, new_row, touch
from validation import field_enum, field_identifier, field_integer, field_string, json_body

bp = Blueprint("talent", __name__)

UNION_AFFILIATIONS = ("UNION", "NON_UNION")
COMPENSATION_MODELS = ("USAGE_BUYOUT", "UNION_SESSION_REUSE")
REQUIRED_MODEL = {"UNION": "UNION_SESSION_REUSE", "NON_UNION": "USAGE_BUYOUT"}


@bp.post("/talent-engagements")
def create_engagement():
    authenticate(("LineProducer",))
    body = json_body()
    project_id = field_identifier(body, "project_id")
    talent_name = field_string(body, "talent_name", 1, 120)
    union_affiliation = field_enum(body, "union_affiliation", UNION_AFFILIATIONS)
    compensation_model = field_enum(body, "compensation_model", COMPENSATION_MODELS)
    session_fee_cents = field_integer(body, "session_fee_cents", minimum=1)
    session_days = field_integer(body, "session_days", 1, 30)

    project = find_project(project_id)
    if project["status"] not in ("DRAFT", "SCOPED", "IN_PRODUCTION"):
        raise ApiError("ERR_PROJECT_STATE_INVALID",
                       "Casting is not permitted while the project is %s." % project["status"])
    # A UNION performer may never be bought out (PRD 3.3).
    if REQUIRED_MODEL[union_affiliation] != compensation_model:
        raise ApiError("ERR_TALENT_COMP_MODEL_INVALID",
                       "A %s performer must use %s."
                       % (union_affiliation, REQUIRED_MODEL[union_affiliation]))

    row = new_row(
        project_id=project["id"],
        talent_name=talent_name,
        union_affiliation=union_affiliation,
        compensation_model=compensation_model,
        session_fee_cents=session_fee_cents,
        session_days=session_days,
        channel_basis_count=0,
        term_basis_months=0,
        reuse_cycles=0,
        base_fee_cents=0,
        usage_load_cents=0,
        reuse_fee_cents=0,
        pension_health_cents=0,
        agent_fee_cents=0,
        total_comp_cents=0,
        comp_basis="PROVISIONAL",
        status="DRAFT",
    )
    money = workflow.price_engagement(row, project, "PROVISIONAL")
    workflow.enforce_allowance(project, money["total_comp_cents"])

    watch = workflow.LedgerWatch(project)
    db["talent_engagements"][row["id"]] = row
    watch.finish()
    return respond_created(derive.talent_engagement_out(row))


@bp.post("/talent-engagements/<engagement_id>/confirm")
def confirm_engagement(engagement_id):
    authenticate(("LineProducer",))
    json_body(required=False)
    engagement = find_engagement(engagement_id)
    if engagement["status"] != "DRAFT":
        raise ApiError("ERR_TALENT_ENGAGEMENT_STATE_INVALID",
                       "Countersigning requires the engagement to be DRAFT.")
    project = db["projects"].get(engagement["project_id"])
    if project["status"] not in ("SCOPED", "IN_PRODUCTION", "IN_POST"):
        raise ApiError("ERR_PROJECT_STATE_INVALID",
                       "Countersigning is not permitted while the project is %s."
                       % project["status"])
    if not derive.project_deliverables(project["id"]):
        raise ApiError("ERR_SCOPE_INCOMPLETE",
                       "The project carries no deliverable to price a FINAL basis against.")

    watch = workflow.LedgerWatch(project)
    workflow.price_engagement(engagement, project, "FINAL")
    engagement["status"] = "CONFIRMED"
    touch(engagement)
    watch.finish()
    return respond_object(derive.talent_engagement_out(engagement))
