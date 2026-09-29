"""Program-year budgets (PRD sec 3.2)."""

from flask import Blueprint

import db
import middleware as mw
import response
from errors import ApiError
from routes.common import require_owner, require_state
from services import calculations as calc
from services import lookup
from services import serializers as ser

bp = Blueprint("budgets", __name__)

REVIEWER = mw.ROLE_STATE_AGENCY_REVIEWER
SPONSOR_ADMIN = mw.ROLE_SPONSOR_ADMIN

BUDGET_STATUSES = (
    "DRAFT",
    "SUBMITTED",
    "APPROVED",
    "REVISION_REQUESTED",
    "AMENDMENT_PENDING",
    "WITHDRAWN",
)


@bp.post("/sfsp/sponsor-budgets")
@mw.endpoint([SPONSOR_ADMIN])
def create_budget():
    body = mw.json_body()
    sponsor_id = mw.field_str(body, "sponsor_id")
    program_year = mw.field_int(body, "program_year", minimum=2020)
    operating_cents = mw.field_int(body, "operating_cost_budget_cents", minimum=1)
    admin_cents = mw.field_int(body, "admin_cost_budget_cents", minimum=0)
    projected_meals = mw.field_int(body, "projected_total_meals", minimum=1)

    sponsor = lookup.require_sponsor(sponsor_id)
    require_owner(sponsor["id"])
    if program_year != sponsor["program_year"]:
        mw.bad_request("Field 'program_year' must equal the sponsor's program year.")

    budget = db.new_row(
        {
            "sponsor_id": sponsor["id"],
            "program_year": program_year,
            "operating_cost_budget_cents": operating_cents,
            "admin_cost_budget_cents": admin_cents,
            "projected_total_meals": projected_meals,
            "admin_cost_ratio": calc.admin_cost_ratio(operating_cents, admin_cents),
            "approved_operating_cost_cents": None,
            "approved_admin_cost_cents": None,
            "status": "DRAFT",
            "revision_round": 0,
            "decision_reason": None,
            "submitted_at": None,
            "decided_at": None,
        }
    )
    db.store.budgets[budget["id"]] = budget
    return response.created_response(ser.budget(budget))


@bp.get("/sfsp/sponsor-budgets/<budget_id>")
@mw.endpoint([SPONSOR_ADMIN, REVIEWER])
def get_budget(budget_id):
    budget = lookup.require_budget(budget_id)
    return response.object_response(ser.budget(budget))


@bp.get("/sfsp/sponsor-budgets")
@mw.endpoint([SPONSOR_ADMIN, REVIEWER])
def list_budgets():
    limit, offset = mw.pagination()
    sponsor_id = mw.query_value("sponsor_id")
    program_year = mw.query_int("program_year")
    status = mw.query_enum("status", BUDGET_STATUSES)

    rows = []
    for budget in db.store.budgets.values():
        if sponsor_id is not None and budget["sponsor_id"] != sponsor_id:
            continue
        if program_year is not None and budget["program_year"] != program_year:
            continue
        if status is not None and budget["status"] != status:
            continue
        rows.append(budget)
    return response.paginate(rows, limit, offset, ser.budget)


@bp.post("/sfsp/sponsor-budgets/<budget_id>/submit")
@mw.endpoint([SPONSOR_ADMIN])
def submit_budget(budget_id):
    budget = lookup.require_budget(budget_id)
    require_owner(budget["sponsor_id"])
    require_state(
        budget["status"] in ("DRAFT", "REVISION_REQUESTED", "APPROVED"),
        "ERR_BUDGET_STATE_INVALID",
    )
    sponsor = lookup.require_sponsor(budget["sponsor_id"])
    require_state(
        sponsor["application_status"] == "APPROVED", "ERR_SPONSOR_NOT_APPROVED"
    )
    if budget["admin_cost_ratio"] > calc.ADMIN_RATIO_LIMIT:
        raise ApiError("ERR_ADMIN_RATIO_EXCEEDED")

    previous = budget["status"]
    if previous == "DRAFT":
        budget["status"] = "SUBMITTED"
    elif previous == "REVISION_REQUESTED":
        budget["status"] = "SUBMITTED"
        budget["revision_round"] = (budget["revision_round"] or 0) + 1
        budget["decision_reason"] = None
    else:  # APPROVED -> AMENDMENT_PENDING, leaving the ceilings in force
        budget["status"] = "AMENDMENT_PENDING"
    budget["submitted_at"] = db.clock.now_iso()
    db.touch(budget)
    return response.object_response(ser.budget(budget))


@bp.post("/sfsp/sponsor-budgets/<budget_id>/decision")
@mw.endpoint([REVIEWER])
def decide_budget(budget_id):
    body = mw.json_body()
    decision = mw.field_enum(
        body, "decision", ("APPROVED", "REVISION_REQUESTED", "WITHDRAWN")
    )
    reason = mw.field_str(body, "reason", required=False)
    approved_operating = mw.field_int(
        body, "approved_operating_cost_cents", required=False, minimum=0
    )
    approved_admin = mw.field_int(
        body, "approved_admin_cost_cents", required=False, minimum=0
    )
    if decision == "APPROVED":
        if approved_operating is None or approved_admin is None:
            mw.bad_request(
                "Both approved ceiling fields are required for an APPROVED decision."
            )
    elif reason is None:
        mw.bad_request("Field 'reason' is required for a %s decision." % decision)

    budget = lookup.require_budget(budget_id)
    if decision == "APPROVED":
        require_state(
            budget["status"] in ("SUBMITTED", "AMENDMENT_PENDING"),
            "ERR_BUDGET_STATE_INVALID",
        )
    elif decision == "REVISION_REQUESTED":
        require_state(
            budget["status"] in ("SUBMITTED", "AMENDMENT_PENDING"),
            "ERR_BUDGET_STATE_INVALID",
        )
    else:
        require_state(
            budget["status"] in ("SUBMITTED", "REVISION_REQUESTED"),
            "ERR_BUDGET_STATE_INVALID",
        )

    if decision == "APPROVED":
        if (
            approved_operating > budget["operating_cost_budget_cents"]
            or approved_admin > budget["admin_cost_budget_cents"]
        ):
            raise ApiError("ERR_APPROVED_CEILING_EXCEEDS_REQUEST")

    previous = budget["status"]
    if decision == "APPROVED":
        budget["approved_operating_cost_cents"] = approved_operating
        budget["approved_admin_cost_cents"] = approved_admin
        budget["status"] = "APPROVED"
        if previous == "AMENDMENT_PENDING":
            budget["revision_round"] = (budget["revision_round"] or 0) + 1
    elif decision == "REVISION_REQUESTED":
        budget["decision_reason"] = reason
        budget["status"] = "REVISION_REQUESTED"
        if previous == "AMENDMENT_PENDING":
            budget["approved_operating_cost_cents"] = None
            budget["approved_admin_cost_cents"] = None
    else:
        budget["decision_reason"] = reason
        budget["status"] = "WITHDRAWN"
    budget["decided_at"] = db.clock.now_iso()
    db.touch(budget)
    return response.object_response(ser.budget(budget))
