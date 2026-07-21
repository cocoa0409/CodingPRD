from flask import Blueprint

import errors
import serializers
from errors import fail
from auth import require_auth, ANY_ROLE
from store import db, new_id, stamp_new
from envelope import ok, created
from validation import get_body, require_str, require_bool, optional_ratio

bp = Blueprint("providers", __name__)


@bp.post("/providers")
def create_provider():
    require_auth({"TPAAdmin"})
    body = get_body()
    p = {
        "id": new_id(),
        "name": require_str(body, "name"),
        "tax_id": require_str(body, "tax_id"),
        "npi": require_str(body, "npi"),
        "in_network": require_bool(body, "in_network"),
        "ppo_discount_pct": optional_ratio(body, "ppo_discount_pct", 0),
        "ytd_paid_cents": 0,
    }
    stamp_new(p)
    db.providers[p["id"]] = p
    return created(serializers.provider(p))


@bp.get("/providers/<pid>")
def get_provider(pid):
    require_auth(ANY_ROLE)
    p = db.providers.get(pid)
    if not p:
        fail(errors.ERR_PROVIDER_NOT_FOUND, "Provider not found")
    return ok(serializers.provider(p))
