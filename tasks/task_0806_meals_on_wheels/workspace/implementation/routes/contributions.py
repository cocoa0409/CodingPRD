from flask import Blueprint

import db
import core
import ser
import find
from core import ApiError

bp = Blueprint("contributions", __name__)


@bp.post("/clients/<cid>/contributions")
@core.require_auth(["ContributionClerk"])
def create_contribution(cid):
    body = core.get_body()
    amount_cents = core.require_field(body, "amount_cents", "int")
    period_month = core.require_field(body, "period_month", "str")

    if amount_cents <= 0:
        core.invalid_value("amount_cents must be > 0")

    client = find.client(cid)

    rec = db.base_record()
    rec.update({
        "client_id": cid,
        "amount_cents": amount_cents,
        "period_month": period_month,
        "status": "RECORDED",
    })
    db.contributions[rec["id"]] = rec
    db.touch(client)
    return core.ok_object(ser.contribution(rec), 201)


@bp.get("/contributions/<cid>")
@core.require_auth(core.ALL_ROLES)
def get_contribution(cid):
    c = find.contribution(cid)
    return core.ok_object(ser.contribution(c))


@bp.get("/contributions")
@core.require_auth(core.ALL_ROLES)
def list_contributions():
    args = core.request.args
    items = list(db.contributions.values())
    for key in ("client_id", "status", "period_month"):
        val = args.get(key)
        if val is not None:
            items = [c for c in items if c[key] == val]
    items = ser.sorted_by_seq(items)
    limit, offset = core.get_pagination()
    page, total = core.paginate(items, limit, offset)
    return core.ok_array([ser.contribution(c) for c in page], limit, offset, total)


@bp.post("/contributions/<cid>/void")
@core.require_auth(["ContributionClerk"])
def void_contribution(cid):
    c = find.contribution(cid)
    if c["status"] != "RECORDED":
        raise ApiError("ERR_INVALID_STATE", 409, "contribution must be RECORDED to void")
    c["status"] = "VOIDED"
    db.touch(c)
    client = db.clients.get(c["client_id"])
    if client is not None:
        db.touch(client)
    return core.ok_object(ser.contribution(c))
