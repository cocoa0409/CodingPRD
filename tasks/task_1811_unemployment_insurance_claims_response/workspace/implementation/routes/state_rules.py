"""StateRule endpoints: per-state deadline policy records."""
import re

from flask import Blueprint

from db import STORE
from errors import err, ERR_DUPLICATE_ACTIVE_RECORD, ERR_INVALID_REQUEST
from middleware import require_roles
from response import paginate, success
from services.core import find_or_404, list_view, new_record, serialize
from util import as_int, as_str, body_json, check_enum, req

bp = Blueprint("state_rules", __name__)

ALL_ROLES = (
    "PlatformAdmin", "ClaimsAnalyst", "TpaAgent", "ChargeAuditor",
    "AgencyLiaison", "RatingAnalyst", "TpaManager",
)

WINDOW_BASIS = ("CALENDAR", "BUSINESS")
WEEKEND_SHIFT = ("NEXT_BUSINESS_DAY", "NONE")


def find_rule_by_code(state_code):
    """Claims and charge statements reference the state by code, never id."""
    for r in STORE.state_rules.values():
        if r["state_code"] == state_code:
            return r
    return None


@bp.post("/ui/state-rules")
def create_state_rule():
    require_roles("PlatformAdmin")
    body = body_json()
    state_code = as_str(req(body, "state_code"), "state_code")
    if not re.fullmatch(r"[A-Z]{2}", state_code):
        raise err(ERR_INVALID_REQUEST, 400, "state_code must be a 2-letter USPS code")
    response_window_days = as_int(req(body, "response_window_days"), "response_window_days")
    window_basis = check_enum(as_str(req(body, "window_basis"), "window_basis"), WINDOW_BASIS, "window_basis")
    appeal_window_days = as_int(req(body, "appeal_window_days"), "appeal_window_days")
    protest_window_days = as_int(req(body, "protest_window_days"), "protest_window_days")
    weekend_shift = check_enum(as_str(req(body, "weekend_shift"), "weekend_shift"), WEEKEND_SHIFT, "weekend_shift")
    if find_rule_by_code(state_code) is not None:
        raise err(ERR_DUPLICATE_ACTIVE_RECORD, 409, "a rule for this state_code already exists")
    rec = new_record({
        "state_code": state_code,
        "response_window_days": response_window_days,
        "window_basis": window_basis,
        "appeal_window_days": appeal_window_days,
        "protest_window_days": protest_window_days,
        "weekend_shift": weekend_shift,
    })
    STORE.state_rules[rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.get("/ui/state-rules")
def list_state_rules():
    require_roles(*ALL_ROLES)
    return paginate(list_view(STORE.state_rules))


@bp.get("/ui/state-rules/<rid>")
def get_state_rule(rid):
    require_roles(*ALL_ROLES)
    rec = find_or_404(STORE.state_rules, rid, "state rule")
    return success(serialize(rec))
