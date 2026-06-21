"""Test-driving endpoints: /_clock/set_current_utc and /_jobs/sweep-deadlines."""

from flask import Blueprint

from db import db
from errors import raise_api
from middleware import require_roles
from response import success
from services.body import get_json_body, require_string
from services.dateutil import add_months
from services.application_svc import (
    bump_application,
    bump_office_action,
    bump_maintenance_fee,
)


bp = Blueprint("system", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@require_roles("USPTOAdmin")
def set_clock(**_):
    body = get_json_body()
    to_iso = require_string(body, "to_iso8601")
    try:
        db.set_clock(to_iso)
    except ValueError as e:
        raise_api("ERR_INVALID_REQUEST", str(e))
    return success(None)


@bp.route("/_jobs/sweep-deadlines", methods=["POST"])
@require_roles("USPTOAdmin")
def sweep_deadlines(**_):
    now = db.current_utc_dt()

    counters = {
        "applications_abandoned": 0,
        "applications_expired": 0,
        "provisionals_expired": 0,
        "maintenance_fees_lapsed": 0,
        "office_actions_expired": 0,
    }

    # ---- Cascade 1: OUTSTANDING OAs past maximum_due_date -> Application ABANDONED
    # Group OUTSTANDING OAs by application_id.
    apps_to_abandon = {}
    for oa in db.office_actions.values():
        if oa["status"] != "OUTSTANDING":
            continue
        if now <= oa["maximum_due_date"]:
            continue
        app = db.applications.get(oa["application_id"])
        if app is None:
            continue
        if app["status"] != "OFFICE_ACTION_OUTSTANDING":
            continue
        apps_to_abandon.setdefault(app["id"], []).append(oa)

    for app_id in apps_to_abandon:
        app = db.applications[app_id]
        # Expire ALL outstanding OAs on this application (not just the triggering one).
        for oa in db.office_actions.values():
            if oa["application_id"] == app_id and oa["status"] == "OUTSTANDING":
                oa["status"] = "EXPIRED"
                bump_office_action(oa)
                counters["office_actions_expired"] += 1
        app["status"] = "ABANDONED"
        bump_application(app)
        counters["applications_abandoned"] += 1

    # ---- Cascade 2: PROVISIONAL filing_date + 12mo elapsed (status=FILED) -> EXPIRED
    for app in db.applications.values():
        if app["application_type"] != "PROVISIONAL":
            continue
        if app["status"] != "FILED":
            continue
        deadline = add_months(app["filing_date"], 12)
        if now > deadline:
            app["status"] = "EXPIRED"
            bump_application(app)
            counters["provisionals_expired"] += 1

    # ---- Cascade 3: MaintenanceFee window_grace_date passed (PENDING) -> LAPSED + EXPIRED parent
    for mf in db.maintenance_fees.values():
        if mf["fee_status"] != "PENDING":
            continue
        if now <= mf["window_grace_date"]:
            continue
        app = db.applications.get(mf["application_id"])
        if app is None:
            continue
        # Only lapse if parent still ISSUED
        if app["status"] != "ISSUED":
            continue
        mf["fee_status"] = "LAPSED"
        bump_maintenance_fee(mf)
        counters["maintenance_fees_lapsed"] += 1

        app["status"] = "EXPIRED"
        bump_application(app)
        counters["applications_expired"] += 1

    return success(counters)
