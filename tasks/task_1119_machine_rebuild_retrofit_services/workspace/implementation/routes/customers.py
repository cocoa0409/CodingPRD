"""Customer endpoints."""

from flask import Blueprint

from db import new_record, store
from middleware import require_roles
from response import success
from serializers import serialize
from util import get_body, opt_str, req_int, req_str
from routes.common import check_customer_ownership, get_or_404

bp = Blueprint("customers", __name__)


@bp.post("/api/customers")
@require_roles("PlatformAdmin")
def create_customer(user_id, role):
    body = get_body()
    name = req_str(body, "name")
    credit_limit_cents = req_int(body, "credit_limit_cents", minimum=0)
    region = opt_str(body, "region")
    rec = new_record(
        {"name": name, "credit_limit_cents": credit_limit_cents, "region": region}
    )
    store.customers[rec["id"]] = rec
    return success(serialize(rec), status=201)


@bp.get("/api/customers/<cid>")
@require_roles("PlatformAdmin", "ProjectManager", "Customer")
def get_customer(user_id, role, cid):
    rec = get_or_404(store.customers, cid, "customer")
    check_customer_ownership(user_id, role, "customer", rec)
    return success(serialize(rec))
