from flask import Blueprint

import store
import calc
from common import (ApiError, authorize, ok_object, ok_array, serialize, paginate,
                    sorted_list, get_body, require_str, optional_str,
                    require_tenant_owner)

bp = Blueprint("tenants", __name__)


@bp.post("/api/tenants")
def create_tenant():
    uid, role = authorize(["PlatformAdmin"])
    body = get_body()
    full_name = require_str(body, "full_name")
    email = require_str(body, "email")
    phone = optional_str(body, "phone")
    # email unique per tenant
    for t in store.tenants.values():
        if t["email"] == email:
            raise ApiError("ERR_INVALID_REQUEST", "email already in use")
    t = store.base_fields()
    t.update({
        "full_name": full_name,
        "email": email,
        "phone": phone,
        "reported_on_time_rate_pct": None,
        "effective_reported_items": 0,
    })
    store.tenants[t["id"]] = t
    return ok_object(serialize(t), 201)


def _load_tenant(tenant_id):
    t = store.tenants.get(tenant_id)
    if t is None:
        raise ApiError("ERR_TENANT_NOT_FOUND", "tenant not found")
    return t


@bp.get("/api/tenants/<tenant_id>")
def get_tenant(tenant_id):
    uid, role = authorize(["PlatformAdmin", "Tenant"])
    t = _load_tenant(tenant_id)
    require_tenant_owner(role, uid, t["id"])
    return ok_object(serialize(t))


@bp.get("/api/tenants/<tenant_id>/credit-summary")
def credit_summary(tenant_id):
    uid, role = authorize(["PlatformAdmin", "Tenant"])
    t = _load_tenant(tenant_id)
    require_tenant_owner(role, uid, t["id"])
    rates = calc.compute_rates(tenant_id)
    data = {
        "tenant_id": tenant_id,
        "on_time_rate_as_paid_pct": rates["as_paid"],
        "on_time_rate_as_reported_pct": rates["as_reported"],
        "total_payments": rates["total_payments"],
        "effective_reported_items": rates["effective_reported_items"],
        "latest_scores": calc.latest_scores(tenant_id),
    }
    return ok_object(data)


@bp.get("/api/tenants/<tenant_id>/score-snapshots")
def list_score_snapshots(tenant_id):
    uid, role = authorize(["PlatformAdmin", "Tenant"])
    t = _load_tenant(tenant_id)
    require_tenant_owner(role, uid, t["id"])
    from flask import request
    bureau = request.args.get("bureau")

    def pred(s):
        if s["tenant_id"] != tenant_id:
            return False
        if bureau is not None and s["bureau"] != bureau:
            return False
        return True

    items = sorted_list(store.score_snapshots, pred)
    page, pagination = paginate(items)
    return ok_array([serialize(x) for x in page], pagination)
