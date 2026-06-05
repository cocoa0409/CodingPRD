"""RMDSchedule endpoints."""

from flask import Blueprint, request

import db
from calculations import (
    rmd_deadline,
    rmd_required_amount,
    secure_inherited_required_amount,
)
from errors import ERR_INVALID_REQUEST, raise_api
from helpers import (
    get_json_body,
    get_owner_or_404,
    get_pagination_params,
    get_rmd_schedule_or_404,
    paginate,
    recompute_rmd_posture,
    require_int,
    require_str,
)
from middleware import g, parse_auth_headers, require_owner_match, require_roles
from response import success_array, success_object
from serializers import rmd_schedule_to_json


bp = Blueprint("rmd_schedules", __name__, url_prefix="/ira/rmd-schedules")


RMD_STATUSES = {"OPEN", "SATISFIED", "DELINQUENT"}


@bp.route("", methods=["POST"])
def create_rmd_schedule():
    parse_auth_headers()
    require_roles("PlanAdministrator")
    body = get_json_body()
    owner_id = require_str(body, "owner_id")
    tax_year = require_int(body, "tax_year")

    owner = get_owner_or_404(owner_id)

    # Compute required_amount_cents
    if owner["deceased_at"] is not None:
        # SECURE inherited path: aggregate inherited Traditional accounts and
        # find a NON_ELIGIBLE_INDIVIDUAL beneficiary with secure_deadline_at.
        inherited_accounts = [
            a for a in db.accounts.values()
            if a["owner_id"] == owner_id and a["account_type"] == "TRADITIONAL" and a["status"] == "INHERITED"
        ]
        total_inherited = sum(a["cash_balance_cents"] for a in inherited_accounts)
        # Find any NEI beneficiary with a secure deadline.
        secure_deadline = None
        for b in db.beneficiary_designations.values():
            if (
                b["status"] == "INHERITED"
                and b["relationship"] == "NON_ELIGIBLE_INDIVIDUAL"
                and b["secure_deadline_at"] is not None
            ):
                acct = db.accounts.get(b["account_id"])
                if acct is not None and acct["owner_id"] == owner_id:
                    secure_deadline = b["secure_deadline_at"]
                    break
        if secure_deadline is not None:
            required = secure_inherited_required_amount(
                total_inherited, secure_deadline, db.system_clock["current_utc"]
            )
        else:
            required = 0
    else:
        traditional_accounts = [
            a for a in db.accounts.values()
            if a["owner_id"] == owner_id and a["account_type"] == "TRADITIONAL" and a["status"] in ("ACTIVE", "FROZEN")
        ]
        required = rmd_required_amount(owner, tax_year, traditional_accounts, db.system_clock["current_utc"])

    deadline, is_first = rmd_deadline(owner, tax_year)

    now = db.now_utc()
    s = {
        "id": db.new_id(),
        "owner_id": owner_id,
        "tax_year": tax_year,
        "required_amount_cents": required,
        "satisfied_amount_cents": 0,
        "deadline_at": deadline,
        "status": "OPEN",
        "is_first_rmd_year": is_first,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.rmd_schedules[s["id"]] = s

    # If required > 0, set owner.rmd_posture to REQUIRED_PENDING.
    if required > 0:
        if owner["rmd_posture"] != "REQUIRED_PENDING":
            owner["rmd_posture"] = "REQUIRED_PENDING"
            owner["updated_at"] = now
            owner["version"] += 1

    return success_object(rmd_schedule_to_json(s), status_code=201)


@bp.route("/<s_id>", methods=["GET"])
def get_rmd_schedule(s_id):
    parse_auth_headers()
    require_roles("PlanAdministrator", "AccountOwner", "IRSAuditor")
    s = get_rmd_schedule_or_404(s_id)
    if g.role == "AccountOwner":
        require_owner_match(s["owner_id"])
    return success_object(rmd_schedule_to_json(s))


@bp.route("", methods=["GET"])
def list_rmd_schedules():
    parse_auth_headers()
    require_roles("PlanAdministrator", "AccountOwner", "IRSAuditor")
    limit, offset = get_pagination_params()
    owner_id = request.args.get("owner_id")
    tax_year_str = request.args.get("tax_year")
    status = request.args.get("status")
    rows = list(db.rmd_schedules.values())
    if owner_id is not None:
        rows = [s for s in rows if s["owner_id"] == owner_id]
    if tax_year_str is not None:
        try:
            ty = int(tax_year_str)
        except ValueError:
            raise_api(ERR_INVALID_REQUEST, "tax_year filter must be an integer.")
        rows = [s for s in rows if s["tax_year"] == ty]
    if status is not None:
        if status not in RMD_STATUSES:
            raise_api(ERR_INVALID_REQUEST, "status filter is not a recognized value.")
        rows = [s for s in rows if s["status"] == status]
    if g.role == "AccountOwner":
        rows = [s for s in rows if s["owner_id"] == g.user_id]
    page, total = paginate(rows, limit, offset)
    return success_array([rmd_schedule_to_json(s) for s in page], limit, offset, total)
