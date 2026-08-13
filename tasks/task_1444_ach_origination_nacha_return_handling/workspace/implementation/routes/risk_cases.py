"""RiskCase resolution (drives the Originator risk-state transitions)."""

from __future__ import annotations

from flask import Blueprint

import db
from db import touch
from errors import (
    raise_err,
    ERR_NOT_FOUND,
    ERR_RISK_CASE_ALREADY_RESOLVED,
    ERR_RESOLUTION_NOT_APPLICABLE,
)
from middleware import require_roles
from response import success_object
from services.domain import RESOLUTION_ACTIONS, cascade_reject_warehoused_files
from util import get_json_body, require_enum

bp = Blueprint("risk_cases", __name__)

# Action applicability per scaffold §1.2 RiskCase machine.
_APPLICABLE_FROM = {
    "SUSPEND": {"ACTIVE", "WATCH"},
    "WATCH": {"ACTIVE"},
    "REINSTATE": {"SUSPENDED", "WATCH"},
    "TERMINATE": {"ACTIVE", "WATCH", "SUSPENDED"},
    "DISMISS": {"PENDING_UNDERWRITING", "ACTIVE", "WATCH", "SUSPENDED", "TERMINATED"},
}


@bp.route("/ach/risk-cases/<case_id>/resolve", methods=["POST"])
@require_roles("OdfiRiskOfficer")
def resolve_risk_case(case_id: str, _user_id: str, _role: str):
    # Existence (p4)
    case = db.risk_cases.get(case_id)
    if case is None:
        raise_err(ERR_NOT_FOUND, "RiskCase not found")
    # Schema (p5)
    body = get_json_body()
    action = require_enum(body, "action", RESOLUTION_ACTIONS)
    # State (p6)
    if case["status"] != "OPEN":
        raise_err(ERR_RISK_CASE_ALREADY_RESOLVED, "RiskCase is already RESOLVED")
    originator = db.originators[case["originator_id"]]
    if originator["status"] not in _APPLICABLE_FROM[action]:
        raise_err(
            ERR_RESOLUTION_NOT_APPLICABLE,
            f"action {action} is not applicable to originator status {originator['status']}",
        )

    # Divergent per-action originator transition.
    if action == "SUSPEND":
        originator["status"] = "SUSPENDED"
        touch(originator)
        cascade_reject_warehoused_files(originator["id"])
    elif action == "WATCH":
        originator["status"] = "WATCH"
        touch(originator)
    elif action == "REINSTATE":
        # SUSPENDED -> WATCH; WATCH -> ACTIVE (one step toward good standing).
        originator["status"] = "WATCH" if originator["status"] == "SUSPENDED" else "ACTIVE"
        touch(originator)
    elif action == "TERMINATE":
        originator["status"] = "TERMINATED"
        touch(originator)
        cascade_reject_warehoused_files(originator["id"])
    # DISMISS: no originator change.

    case["status"] = "RESOLVED"
    case["resolution_action"] = action
    case["resolved_by_user_id"] = _user_id
    touch(case)
    return success_object(case)
