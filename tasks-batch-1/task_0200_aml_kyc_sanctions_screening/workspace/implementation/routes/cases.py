"""Case investigation and fork-join disposition (PRD §3.8)."""

from decimal import Decimal

from flask import Blueprint, request

import db
import calculations as calc
import services
from errors import (
    err,
    ERR_INVALID_STATE,
    ERR_STALE_VERSION,
    ERR_INVALID_DECISION,
    ERR_NO_CTR_ALERT,
    ERR_ALERT_ALREADY_LINKED,
    ERR_ALERT_CUSTOMER_MISMATCH,
    ERR_ACCOUNT_BLOCKED_FOR_CASE,
)
from middleware import authenticate, require_role
from response import object_response, array_response
from validation import (
    get_body,
    require_found,
    require_field,
    parse_pagination,
    sort_and_paginate,
)

bp = Blueprint("cases", __name__)

READ_ROLES = {"Analyst", "ComplianceOfficer", "QualityReviewer", "PlatformAdmin"}


def _linked_alerts(case_id):
    return [
        al
        for al in db.alerts.values()
        if al["case_id"] == case_id and al["status"] == "LINKED"
    ]


def _recompute_case(case):
    linked = _linked_alerts(case["id"])
    case["linked_alert_count"] = len(linked)
    if linked:
        max_sev = max(Decimal(str(al["severity_score"])) for al in linked)
    else:
        max_sev = None
    case["priority"] = calc.case_priority(max_sev)


# ---------------------------------------------------------------------------
# POST /cases  (Analyst)
# ---------------------------------------------------------------------------
@bp.route("/cases", methods=["POST"])
def open_case():
    user_id, role = authenticate()
    require_role(role, {"Analyst"})
    body = get_body()
    customer_id = require_field(body, "customer_id")
    require_found(db.customers.get(customer_id))

    base = db.common_create_fields()
    case = {
        **base,
        "customer_id": customer_id,
        "opened_by_user_id": user_id,
        "priority": "LOW",
        "disposition": "TRIAGE",
        "linked_alert_count": 0,
    }
    db.cases[case["id"]] = case
    services.audit("Case", case["id"], "CASE_OPENED", user_id, role)
    return object_response(db.public(case), 201)


@bp.route("/cases/<cid>", methods=["GET"])
def get_case(cid):
    user_id, role = authenticate()
    require_role(role, READ_ROLES)
    case = require_found(db.cases.get(cid))
    return object_response(db.public(case))


@bp.route("/cases", methods=["GET"])
def list_cases():
    user_id, role = authenticate()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination(request.args)
    rows = list(db.cases.values())
    cust = request.args.get("customer_id")
    if cust is not None:
        rows = [c for c in rows if c["customer_id"] == cust]
    disp = request.args.get("disposition")
    if disp is not None:
        rows = [c for c in rows if c["disposition"] == disp]
    page, total = sort_and_paginate(rows, limit, offset)
    return array_response([db.public(c) for c in page], limit, offset, total)


# ---------------------------------------------------------------------------
# POST /cases/{id}/alerts  (Analyst; OCC-guarded)
# ---------------------------------------------------------------------------
@bp.route("/cases/<cid>/alerts", methods=["POST"])
def link_alert(cid):
    user_id, role = authenticate()
    require_role(role, {"Analyst"})
    case = require_found(db.cases.get(cid))
    body = get_body()

    alert_id = require_field(body, "alert_id")
    expected_version = require_field(body, "expected_case_version")

    # existence of FK alert (priority 3)
    alert = require_found(db.alerts.get(alert_id))

    # state legality (priority 7): linkable only from TRIAGE or INVESTIGATING
    if case["disposition"] not in ("TRIAGE", "INVESTIGATING"):
        raise err(ERR_INVALID_STATE, "Case is not in a linkable state.")

    # OCC (priority 8): after state check (PRD §2.7, §2.11)
    if expected_version != case["version"]:
        raise err(ERR_STALE_VERSION, "expected_case_version mismatch.")

    # priority 14: already linked
    if alert["status"] == "LINKED":
        raise err(ERR_ALERT_ALREADY_LINKED, "Alert is already linked to a case.")

    # priority 15: alert.customer_id must equal case.customer_id
    if alert["customer_id"] != case["customer_id"]:
        raise err(ERR_ALERT_CUSTOMER_MISMATCH, "Alert customer does not match case customer.")

    # priority 20: originating account FROZEN -> blocked (checked after the above)
    account = db.accounts.get(alert["account_id"])
    if account is not None and account["monitoring_status"] == "FROZEN":
        raise err(ERR_ACCOUNT_BLOCKED_FOR_CASE, "Alert's account is FROZEN.")

    # Link
    alert["status"] = "LINKED"
    alert["case_id"] = cid
    db.touch(alert)

    if case["disposition"] == "TRIAGE":
        case["disposition"] = "INVESTIGATING"
    _recompute_case(case)
    db.touch(case)
    services.audit("Case", cid, "ALERT_LINKED", user_id, role)

    # cross-entity cascade: account ACTIVE -> UNDER_INVESTIGATION (PRD §3.8)
    if account is not None and account["monitoring_status"] == "ACTIVE":
        account["monitoring_status"] = "UNDER_INVESTIGATION"
        db.touch(account)

    return object_response(db.public(case))


@bp.route("/cases/<cid>/alerts", methods=["GET"])
def list_case_alerts(cid):
    user_id, role = authenticate()
    require_role(role, READ_ROLES)
    require_found(db.cases.get(cid))
    limit, offset = parse_pagination(request.args)
    rows = [al for al in db.alerts.values() if al["case_id"] == cid]
    page, total = sort_and_paginate(rows, limit, offset)
    return array_response([db.public(al) for al in page], limit, offset, total)


# ---------------------------------------------------------------------------
# POST /cases/{id}/disposition  (Analyst, ComplianceOfficer)
# ---------------------------------------------------------------------------
@bp.route("/cases/<cid>/disposition", methods=["POST"])
def disposition_case(cid):
    user_id, role = authenticate()
    require_role(role, {"Analyst", "ComplianceOfficer"})
    case = require_found(db.cases.get(cid))
    body = get_body()

    # priority 21: decision must be in allowed set
    decision = require_field(body, "decision")
    if decision not in {"RECOMMEND_SAR", "REQUIRE_CTR", "CLOSE_NO_ACTION"}:
        raise err(ERR_INVALID_DECISION, "decision must be RECOMMEND_SAR, REQUIRE_CTR, or CLOSE_NO_ACTION.")

    # state legality (priority 7): fork only from INVESTIGATING
    if case["disposition"] != "INVESTIGATING":
        raise err(ERR_INVALID_STATE, "Case disposition requires INVESTIGATING.")

    if decision == "RECOMMEND_SAR":
        # requires at least one linked alert (PRD §3.8)
        if case["linked_alert_count"] < 1:
            raise err(ERR_INVALID_STATE, "RECOMMEND_SAR requires at least one linked alert.")
        case["disposition"] = "SAR_RECOMMENDED"
        db.touch(case)
        services.audit("Case", cid, "CASE_DISPOSITIONED", user_id, role)
        return object_response(db.public(case))

    if decision == "REQUIRE_CTR":
        # priority 13: requires a LINKED CTR_THRESHOLD alert
        has_ctr = any(al["rule_code"] == "CTR_THRESHOLD" for al in _linked_alerts(cid))
        if not has_ctr:
            raise err(ERR_NO_CTR_ALERT, "REQUIRE_CTR requires a LINKED CTR_THRESHOLD alert.")
        case["disposition"] = "CTR_REQUIRED"
        db.touch(case)
        services.audit("Case", cid, "CASE_DISPOSITIONED", user_id, role)
        return object_response(db.public(case))

    # CLOSE_NO_ACTION: ComplianceOfficer only (deliberate override) (PRD §3.8)
    if role != "ComplianceOfficer":
        from errors import ERR_FORBIDDEN

        raise err(ERR_FORBIDDEN, "CLOSE_NO_ACTION requires ComplianceOfficer.")

    case["disposition"] = "CLOSED_NO_ACTION"
    db.touch(case)
    # dismiss every linked alert; revert affected accounts (PRD §3.8)
    affected_accounts = set()
    for al in list(db.alerts.values()):
        if al["case_id"] == cid and al["status"] == "LINKED":
            al["status"] = "DISMISSED"
            al["case_id"] = None
            db.touch(al)
            affected_accounts.add(al["account_id"])
    for acc_id in affected_accounts:
        acc = db.accounts.get(acc_id)
        if acc is not None:
            services.maybe_revert_account_monitoring(acc)
    services.audit("Case", cid, "CASE_DISPOSITIONED", user_id, role)
    return object_response(db.public(case))
