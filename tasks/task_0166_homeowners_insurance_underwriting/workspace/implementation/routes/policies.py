"""Policy routes (PRD §3.7) — read, lapse (CASCADE B), cancel."""
from flask import Blueprint, g, request

from db import db
from errors import err
from middleware import require_roles
from response import success
from services.calc import to_money
from services.common import (
    get_json_body, require_field, as_int, get_or_404, parse_pagination, paginate,
)
from services.ledger import post
from services.models import serialize, touch

bp = Blueprint("policies", __name__)


@bp.get("/policies")
@require_roles("Admin", "Agent", "Underwriter")
def list_policies():
    limit, offset = parse_pagination()
    application_id = request.args.get("application_id")
    property_id = request.args.get("property_id")
    with db.lock:
        items = list(db.policies.values())
        if application_id is not None:
            items = [p for p in items if p["application_id"] == application_id]
        if property_id is not None:
            items = [p for p in items if p["property_id"] == property_id]
        window, meta = paginate(items, limit, offset)
        data = [serialize(p) for p in window]
    return success(data, status=200, list_meta=meta)


@bp.get("/policies/<rid>")
@require_roles("Admin", "Agent", "Underwriter")
def get_policy(rid):
    with db.lock:
        rec = get_or_404("policy", rid)
        return success(serialize(rec), status=200)


@bp.post("/policies/<rid>/lapse")
@require_roles("Underwriter")
def lapse_policy(rid):
    body = get_json_body()
    with db.lock:
        pol = get_or_404("policy", rid)
        if pol["status"] not in ("ACTIVE", "REINSTATED"):
            raise err("ERR_POLICY_NOT_ACTIVE", "lapse requires Policy in ACTIVE or REINSTATED.")
        # input integrity (lowest priority) after the state gate
        expected_version = as_int(require_field(body, "expected_policy_version"),
                                  "expected_policy_version")
        if expected_version != pol["version"]:
            raise err("ERR_STALE_POLICY_VERSION",
                      "expected_policy_version does not match the policy's version.")
        pol["status"] = "LAPSED"
        pol["lapse_count"] = pol["lapse_count"] + 1
        touch(pol)  # increments Policy.version by 1
        # CASCADE B: CREDIT the entire current premium_balance so it returns to 0
        writeoff = to_money(pol["premium_balance"])
        post(pol, "CREDIT", writeoff, "LAPSE_WRITEOFF")
        return success(serialize(pol), status=200)


@bp.post("/policies/<rid>/cancel")
@require_roles("Underwriter")
def cancel_policy(rid):
    with db.lock:
        pol = get_or_404("policy", rid)
        if pol["status"] not in ("ACTIVE", "REINSTATED", "LAPSED"):
            raise err("ERR_POLICY_NOT_CANCELLABLE", "cancel requires Policy in ACTIVE/REINSTATED/LAPSED.")
        pol["status"] = "CANCELLED"
        touch(pol)
        return success(serialize(pol), status=200)
