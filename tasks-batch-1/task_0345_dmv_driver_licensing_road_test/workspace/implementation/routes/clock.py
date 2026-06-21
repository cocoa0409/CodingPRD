"""Logical clock endpoints (PRD section 2.5)."""
from flask import Blueprint

from db import db as store
from errors import err
from middleware import get_user_context, require_role
from response import success
from services.common import get_json_body
from services.sweep import run_sweep

bp = Blueprint("clock", __name__)


@bp.post("/_clock/advance")
def advance_clock():
    _, role = get_user_context()
    require_role(role, {"AdjudicationOfficer", "LicenseClerk"})
    body = get_json_body()
    if "by_periods" not in body or body["by_periods"] is None:
        raise err("ERR_INVALID_REQUEST", "by_periods is required")
    by_periods = body["by_periods"]
    if not isinstance(by_periods, int) or isinstance(by_periods, bool) or by_periods <= 0:
        raise err("ERR_INVALID_REQUEST", "by_periods must be a positive integer")
    store.current_period += by_periods
    run_sweep(store)
    return success({"current_period": store.current_period}, 200, "object")


@bp.get("/_clock")
def get_clock():
    _, role = get_user_context()
    require_role(role, {"AdjudicationOfficer", "LicenseClerk", "Examiner", "KnowledgeProctor"})
    return success({"current_period": store.current_period}, 200, "object")
