"""StatePolicy routes (PRD §3.1)."""

from flask import Blueprint, request

from core.auth import require_roles
from core.envelope import success_object
from core.errors import raise_error
from core.store import STORE, gen_id, lock
from core.validation import require_body, require_field, require_enum, optional_enum
from services.mutations import stamp_create
from services.projections import project_state_policy


bp = Blueprint("state_policies", __name__)


_ASSET_TYPES = {
    "PRIMARY_RESIDENCE", "VEHICLE", "CHECKING", "SAVINGS",
    "RETIREMENT", "INVESTMENT", "LIFE_INSURANCE", "OTHER",
}


def _validate_state_code(s, field="state_code"):
    # PRD §3.1 does not pin a format on state_code; only require a
    # non-empty string. Uniqueness is enforced separately below.
    if not isinstance(s, str) or not s.strip():
        raise_error("ERR_INVALID_REQUEST", f"Field '{field}' must be a non-empty string")
    return s


@bp.route("/state-policies", methods=["POST"])
@require_roles("PolicyAdmin")
def create_state_policy():
    body = require_body(request)
    state_code = _validate_state_code(require_field(body, "state_code", kind="string"))
    fpl_year = require_field(body, "fpl_year", kind="int")
    fpl_base = require_field(body, "fpl_base_amount", kind="number")
    fpl_per = require_field(body, "fpl_per_member_amount", kind="number")
    magi_pct = require_field(body, "magi_income_limit_pct", kind="number")
    asset_test_applies = body.get("asset_test_applies", False)
    if not isinstance(asset_test_applies, bool):
        raise_error("ERR_INVALID_REQUEST", "asset_test_applies must be boolean")
    asset_limit = body.get("asset_limit_per_member", 0)
    if not isinstance(asset_limit, (int, float)) or isinstance(asset_limit, bool) or asset_limit < 0:
        raise_error("ERR_INVALID_REQUEST", "asset_limit_per_member must be a non-negative number")
    state_disregard = body.get("state_disregard_amount", 0)
    if not isinstance(state_disregard, (int, float)) or isinstance(state_disregard, bool) or state_disregard < 0:
        raise_error("ERR_INVALID_REQUEST", "state_disregard_amount must be a non-negative number")
    state_exempt = body.get("state_exempt_asset_types", []) or []
    if not isinstance(state_exempt, list) or not all(isinstance(x, str) for x in state_exempt):
        raise_error("ERR_INVALID_REQUEST", "state_exempt_asset_types must be a list of strings")
    for x in state_exempt:
        if x not in _ASSET_TYPES:
            raise_error("ERR_INVALID_REQUEST", f"Invalid asset_type '{x}' in state_exempt_asset_types")

    with lock():
        if state_code in STORE.state_policies_by_code:
            raise_error("ERR_INVALID_REQUEST", f"StatePolicy already exists for state_code '{state_code}'")
        pid = gen_id()
        row = {
            "id": pid,
            "state_code": state_code,
            "fpl_year": int(fpl_year),
            "fpl_base_amount": float(fpl_base),
            "fpl_per_member_amount": float(fpl_per),
            "magi_income_limit_pct": float(magi_pct),
            "asset_limit_per_member": float(asset_limit),
            "asset_test_applies": bool(asset_test_applies),
            "state_disregard_amount": float(state_disregard),
            "state_exempt_asset_types": list(state_exempt),
        }
        stamp_create(row)
        STORE.state_policies[pid] = row
        STORE.state_policies_by_code[state_code] = pid

    return success_object(project_state_policy(row), status=201)


@bp.route("/state-policies/<state_code>", methods=["GET"])
@require_roles("PolicyAdmin", "IntakeWorker", "EligibilityCaseworker", "AppealsOfficer")
def get_state_policy(state_code):
    pid = STORE.state_policies_by_code.get(state_code)
    if pid is None:
        raise_error("ERR_NOT_FOUND", f"StatePolicy '{state_code}' not found")
    row = STORE.state_policies[pid]
    return success_object(project_state_policy(row))
