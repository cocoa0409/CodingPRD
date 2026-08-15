"""Alerts: list/fetch, triage, dismiss, reopen, link-to-case."""
from flask import Blueprint, request

import db
import response
from errors import ApiError
from middleware import ALL_ROLES, authn, authz, get_body, pagination_params
from util import req_str, serialize, sort_created, touch

bp = Blueprint("alerts", __name__)


def _get(store, rid, label):
    entity = store.get(rid)
    if entity is None:
        raise ApiError("ERR_NOT_FOUND", f"{label} '{rid}' does not exist", 404)
    return entity


@bp.route("/alerts", methods=["GET"])
def list_alerts():
    _, role = authn()
    authz(role, ALL_ROLES)
    limit, offset = pagination_params()
    items = list(db.alerts.values())
    for field in ("scenario_id", "scenario_threshold_id", "account_id",
                  "customer_id", "case_id", "status"):
        value = request.args.get(field)
        if value is not None:
            items = [a for a in items if a.get(field) == value]
    items = sort_created(items)
    return response.paginated([serialize(a) for a in items], limit, offset)


@bp.route("/alerts/<rid>", methods=["GET"])
def get_alert(rid):
    _, role = authn()
    authz(role, ALL_ROLES)
    alert = _get(db.alerts, rid, "Alert")
    return response.success(serialize(alert), status=200)


@bp.route("/alerts/<rid>/triage", methods=["POST"])
def triage_alert(rid):
    user_id, role = authn()
    authz(role, ["BSAAnalyst"])
    alert = _get(db.alerts, rid, "Alert")
    if alert["status"] != "NEW":
        raise ApiError("ERR_INVALID_STATE",
                       f"Alert in status {alert['status']} cannot be triaged", 409)
    alert["status"] = "UNDER_TRIAGE"
    alert["triaged_by_analyst_id"] = user_id
    touch(alert)
    return response.success(serialize(alert), status=200)


@bp.route("/alerts/<rid>/dismiss", methods=["POST"])
def dismiss_alert(rid):
    body = get_body()
    rationale = req_str(body, "dismissal_rationale")
    user_id, role = authn()
    authz(role, ["BSAAnalyst"])
    alert = _get(db.alerts, rid, "Alert")
    if alert["status"] != "UNDER_TRIAGE":
        raise ApiError("ERR_INVALID_STATE",
                       f"Alert in status {alert['status']} cannot be dismissed", 409)
    alert["status"] = "DISMISSED"
    alert["dismissal_rationale"] = rationale
    alert["dismissed_at"] = db.now()
    touch(alert)
    return response.success(serialize(alert), status=200)


@bp.route("/alerts/<rid>/reopen", methods=["POST"])
def reopen_alert(rid):
    _, role = authn()
    authz(role, ["BSAAnalyst"])
    alert = _get(db.alerts, rid, "Alert")
    if alert["status"] != "DISMISSED":
        raise ApiError("ERR_INVALID_STATE",
                       f"Alert in status {alert['status']} cannot be reopened", 409)
    alert["status"] = "UNDER_TRIAGE"
    alert["dismissed_at"] = None
    alert["dismissal_rationale"] = None
    touch(alert)
    return response.success(serialize(alert), status=200)


@bp.route("/alerts/<rid>/link-to-case", methods=["POST"])
def link_alert_to_case(rid):
    body = get_body()
    case_id = req_str(body, "case_id")
    _, role = authn()
    authz(role, ["BSAAnalyst"])
    alert = _get(db.alerts, rid, "Alert")
    case = _get(db.cases, case_id, "Case")
    if alert["status"] != "UNDER_TRIAGE":
        raise ApiError("ERR_INVALID_STATE",
                       f"Alert in status {alert['status']} cannot be linked", 409)
    if case["status"] not in {"OPEN", "ASSIGNED", "INVESTIGATING"}:
        raise ApiError("ERR_INVALID_STATE",
                       f"Case in status {case['status']} cannot accept linked alerts", 409)
    if alert["customer_id"] != case["customer_id"]:
        raise ApiError("ERR_SUBJECT_MISMATCH",
                       "Alert and case belong to different customers", 422)
    alert["case_id"] = case["id"]
    alert["status"] = "LINKED"
    touch(alert)
    # Per scaffold: the case's updated_at is refreshed (no version increment).
    touch(case, bump_version=False)
    return response.success(serialize(alert), status=200)
