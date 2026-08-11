"""RenewalApplication endpoints."""

from datetime import timedelta

import db
import services as S
from db import store
from errors import (
    err_invalid_state,
    err_renewal_lapsed,
    err_renewal_not_open,
    err_validation,
)
from middleware import ALL_READ_ROLES, actor, body, check_funder_scope, require_roles
from response import ok, paginate


def create_renewal(grant_id):
    _, role = actor()
    require_roles(role, {"GrantsOfficer"})
    grant = S.get_grant(grant_id)
    if S.grant_renewals(grant_id):
        raise err_invalid_state("A grant admits at most one RenewalApplication")
    end = grant["end_date"]
    window_open = end - timedelta(days=grant["renewal_window_days"])  # 00:00:00Z
    window_close = end.replace(hour=23, minute=59, second=59)
    r = S.stamp({
        "grant_id": grant_id,
        "window_open": window_open,
        "window_close": window_close,
        "status": "NOT_OPEN",
        "submitted_at": None,
    })
    store["renewal_applications"][r["id"]] = r
    return ok(S.ser_renewal(r), code=201)


def list_renewals(grant_id):
    _, role = actor()
    require_roles(role, ALL_READ_ROLES)
    S.get_grant(grant_id)
    items = S.grant_renewals(grant_id)
    page, meta = paginate(items)
    return ok([S.ser_renewal(r) for r in page], pagination=meta)


def submit_renewal(renewal_id):
    _, role = actor()
    require_roles(role, {"ProgramDirector"})
    r = S.get_renewal(renewal_id)
    if r["status"] == "NOT_OPEN":
        raise err_renewal_not_open()
    if r["status"] == "LAPSED":
        raise err_renewal_lapsed()
    if r["status"] != "ELIGIBLE":
        raise err_invalid_state("Only an ELIGIBLE renewal application can be submitted")
    r["status"] = "SUBMITTED"
    r["submitted_at"] = db.now()
    S.touch(r)
    return ok(S.ser_renewal(r))


def decide_renewal(renewal_id):
    uid, role = actor()
    require_roles(role, {"Funder"})
    r = S.get_renewal(renewal_id)
    grant = S.get_grant(r["grant_id"])
    check_funder_scope(uid, grant)
    data = body()
    decision = data.get("decision")
    if decision not in ("RENEWED", "DECLINED"):
        raise err_validation("decision must be RENEWED or DECLINED")
    if r["status"] != "SUBMITTED":
        raise err_invalid_state("Only a SUBMITTED renewal application can be decided")
    r["status"] = decision
    S.touch(r)
    return ok(S.ser_renewal(r))


def register(app):
    app.add_url_rule("/grants/<grant_id>/renewal-applications", "renew_create", create_renewal, methods=["POST"])
    app.add_url_rule("/grants/<grant_id>/renewal-applications", "renew_list", list_renewals, methods=["GET"])
    app.add_url_rule("/renewal-applications/<renewal_id>/submit", "renew_submit", submit_renewal, methods=["POST"])
    app.add_url_rule("/renewal-applications/<renewal_id>/decide", "renew_decide", decide_renewal, methods=["POST"])
