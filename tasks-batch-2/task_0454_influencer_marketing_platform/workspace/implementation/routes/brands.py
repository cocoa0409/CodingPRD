from flask import Blueprint

from db import db, base_fields
from middleware import get_auth, require_role
from validators import get_body, req_str, opt_str, req_int
from response import success
from pagination import paginate
import serializers as S
import services as svc
import derive

bp = Blueprint("brands", __name__)


@bp.route("/brands", methods=["POST"])
def create_brand():
    _, role = get_auth()
    require_role(role, {"PlatformAdmin"})
    body = get_body()
    legal_name = req_str(body, "legal_name", allow_empty=False)
    contact_email = opt_str(body, "contact_email", default="")
    if "contact_email" in body and body["contact_email"] is not None:
        contact_email = body["contact_email"]
        if not isinstance(contact_email, str):
            from errors import err
            raise err("ERR_INVALID_REQUEST", "contact_email must be a string")
    budget_cents = req_int(body, "budget_cents", minimum=0)

    rec = base_fields()
    rec.update({
        "legal_name": legal_name,
        "contact_email": contact_email,
        "budget_cents": budget_cents,
        "committed_cents": 0,
        "available_budget_cents": budget_cents,
    })
    db.brands[rec["id"]] = rec
    return success(S.brand_view(rec), status=201)


@bp.route("/brands/<brand_id>", methods=["GET"])
def get_brand(brand_id):
    _, role = get_auth()
    require_role(role, {"PlatformAdmin", "Brand", "ComplianceOfficer"})
    b = svc.get_brand(brand_id)
    derive.recompute_brand_budget(b)
    return success(S.brand_view(b), status=200)


@bp.route("/brands/<brand_id>/campaigns", methods=["GET"])
def list_brand_campaigns(brand_id):
    _, role = get_auth()
    require_role(role, {"PlatformAdmin", "Brand", "ComplianceOfficer"})
    svc.get_brand(brand_id)
    rows = [c for c in db.campaigns.values() if c["brand_id"] == brand_id]
    for c in rows:
        derive.recompute_campaign_committed(c)
    page, meta = paginate(rows)
    return success([S.campaign_view(c) for c in page], status=200, pagination=meta)
