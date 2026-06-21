"""System clock and ops-run endpoints."""

from flask import Blueprint

import db
from helpers import (
    append_audit_event,
    get_json_body,
    parse_iso_datetime,
    recompute_rmd_posture,
    require_int,
    require_str,
)
from middleware import parse_auth_headers, require_roles
from response import success_object
from serializers import system_clock_to_json


bp = Blueprint("system", __name__, url_prefix="/ira")


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    parse_auth_headers()
    require_roles("PlanAdministrator")
    body = get_json_body()
    to_iso = require_str(body, "to_iso8601")
    dt = parse_iso_datetime(to_iso, "to_iso8601")
    db.system_clock["current_utc"] = dt
    db.system_clock["current_tax_year"] = dt.year
    return success_object(system_clock_to_json(db.system_clock))


@bp.route("/_clock", methods=["GET"])
def get_clock():
    parse_auth_headers()
    require_roles("PlanAdministrator", "AccountOwner", "IRSAuditor")
    return success_object(system_clock_to_json(db.system_clock))


@bp.route("/_ops/advance-year-rollover", methods=["POST"])
def advance_year_rollover():
    parse_auth_headers()
    require_roles("PlanAdministrator")
    body = get_json_body()
    new_tax_year = require_int(body, "new_tax_year")

    now = db.now_utc()
    rolled = 0
    for acct in db.accounts.values():
        if acct["tax_year_marker"] != new_tax_year:
            acct["tax_year_marker"] = new_tax_year
            acct["ytd_contribution_cents"] = 0
            acct["updated_at"] = now
            acct["version"] += 1
            rolled += 1
        else:
            # Still reset ytd_contribution_cents per PRD wording — capability
            # resets every account's ytd to 0 and advances the marker. If the
            # marker already matches the new year, we still ensure ytd is 0.
            if acct["ytd_contribution_cents"] != 0:
                acct["ytd_contribution_cents"] = 0
                acct["updated_at"] = now
                acct["version"] += 1
                rolled += 1

    delinquent_count = 0
    affected_owners = set()
    clock_now = db.system_clock["current_utc"]
    for s in db.rmd_schedules.values():
        if s["status"] == "OPEN" and clock_now > s["deadline_at"] and s["satisfied_amount_cents"] < s["required_amount_cents"]:
            shortfall = s["required_amount_cents"] - s["satisfied_amount_cents"]
            s["status"] = "DELINQUENT"
            s["updated_at"] = now
            s["version"] += 1
            delinquent_count += 1
            append_audit_event(
                owner_id=s["owner_id"],
                account_id=None,
                event_kind="RMD_DEADLINE_BREACHED",
                tax_year=s["tax_year"],
                amount_cents=shortfall,
            )
            affected_owners.add(s["owner_id"])
            # Set rmd_posture to REQUIRED_DELINQUENT on the owner.
            owner = db.owners.get(s["owner_id"])
            if owner is not None and owner["rmd_posture"] != "REQUIRED_DELINQUENT":
                owner["rmd_posture"] = "REQUIRED_DELINQUENT"
                owner["updated_at"] = now
                owner["version"] += 1

    # YEAR_ROLLED_OVER audit events for each owner with accounts that rolled.
    rolled_owner_ids = set()
    for acct in db.accounts.values():
        if acct["tax_year_marker"] == new_tax_year:
            rolled_owner_ids.add(acct["owner_id"])
    for oid in rolled_owner_ids:
        append_audit_event(
            owner_id=oid,
            account_id=None,
            event_kind="YEAR_ROLLED_OVER",
            tax_year=new_tax_year,
            amount_cents=0,
        )

    return success_object({
        "rolled_account_count": rolled,
        "delinquent_schedule_count": delinquent_count,
    })
