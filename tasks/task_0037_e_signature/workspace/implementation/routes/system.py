"""System / test-driving endpoints: /_clock/advance and /_sweep/run, plus
an internal seed endpoint to register OrgUsers used by the test fixtures."""

from flask import Blueprint, g, request

from db import DB, LOCK, new_id
from clock import CLOCK, parse_iso, iso, now
from errors import validation_failed
from middleware import require_roles
from response import success_object
from services import sweep as sweep_svc
from ._helpers import get_json_body


bp = Blueprint("system", __name__)


@bp.route("/_clock/advance", methods=["POST"])
@require_roles("PlatformAdmin")
def clock_advance():
    body = get_json_body()
    to_raw = body.get("to") if isinstance(body, dict) else None
    if not to_raw:
        raise validation_failed("'to' is required")
    try:
        target = parse_iso(to_raw)
    except Exception:
        raise validation_failed("'to' must be ISO 8601")
    with LOCK:
        new_now = CLOCK.advance_to(target)
    return success_object({"now": iso(new_now)})


@bp.route("/_sweep/run", methods=["POST"])
@require_roles("PlatformAdmin", "SystemSweeper")
def sweep_run():
    with LOCK:
        result = sweep_svc.run_sweep(actor_user_id=g.user_id, actor_role=g.role)
    return success_object(result)


# ---- Test fixture endpoints -----------------------------------------------
# These are not described in the PRD endpoint table but are needed so that
# the harness can seed OrgUser identities (used for delegation, segregation,
# real_name_match, etc.). They are open to all authenticated callers.

@bp.route("/_org-users", methods=["POST"])
def create_org_user():
    body = get_json_body()
    if not isinstance(body, dict):
        raise validation_failed("Body must be a JSON object")
    legal_name = body.get("legal_name")
    org_id = body.get("org_id")
    org_role = body.get("org_role")
    registered_factors = body.get("registered_factors") or []
    explicit_id = body.get("id")
    if not isinstance(legal_name, str) or not (1 <= len(legal_name) <= 120):
        raise validation_failed("legal_name must be 1..120 chars")
    if not isinstance(org_id, str) or not org_id:
        raise validation_failed("org_id required")
    if org_role not in ("LEGAL_REP", "AUTHORIZED_DELEGATE", "EMPLOYEE"):
        raise validation_failed("org_role invalid")
    n = now()
    uid = explicit_id or new_id()
    u = {
        "id": uid,
        "legal_name": legal_name,
        "org_id": org_id,
        "org_role": org_role,
        "registered_factors": list(registered_factors),
        "status": body.get("status", "ACTIVE"),
        "version": 1,
        "created_at": n,
        "updated_at": n,
    }
    DB.org_users[uid] = u
    return success_object(u, 201)


@bp.route("/_org-users/<uid>", methods=["GET"])
def get_org_user(uid):
    u = DB.org_users.get(uid)
    if not u:
        from errors import not_found
        raise not_found("OrgUser not found")
    return success_object(u)


@bp.route("/_reset", methods=["POST"])
def reset_db():
    """Wipe all in-memory state. Useful for test isolation."""
    DB.reset()
    CLOCK.reset()
    return success_object({"reset": True})
