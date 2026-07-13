"""Retainers: the advertiser's prepaid balance (PRD 3.1)."""
from flask import Blueprint, request

import db
import response
import services
import validate
from auth import endpoint

bp = Blueprint("retainers", __name__)

READ_ROLES = ["AgencyAdmin", "AccountManager", "ClientReviewer"]


@bp.post("/retainers")
@endpoint(["AgencyAdmin"])
def create_retainer():
    b = validate.body()
    client_id = validate.req_str(b, "client_id")
    initial = validate.req_int(b, "initial_funding_cents", minimum=0)
    period_start = validate.req_datetime(b, "period_start")
    period_end = validate.req_datetime(b, "period_end")
    if period_end <= period_start:
        validate.bad("period_end must be strictly after period_start.")

    services.must("client", client_id)

    obj = db.base_entity()
    obj.update(
        {
            "client_id": client_id,
            "period_start": b["period_start"],
            "period_end": b["period_end"],
            "funded_cents": initial,
            "balance_cents": initial,
            "status": "ACTIVE",
            "_period_start": period_start.date(),
            "_period_end": period_end.date(),
        }
    )
    db.RETAINERS[obj["id"]] = obj
    return response.created(db.public(obj))


@bp.get("/retainers/<rid>")
@endpoint(READ_ROLES)
def get_retainer(rid):
    return response.ok(db.public(services.must("retainer", rid)))


@bp.get("/retainers")
@endpoint(READ_ROLES)
def list_retainers():
    limit, offset = validate.pagination()
    client_id = request.args.get("client_id")
    status = request.args.get("status")
    rows = db.ordered(db.RETAINERS)
    if client_id:
        rows = [r for r in rows if r["client_id"] == client_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    return response.listing(rows, limit, offset)


@bp.post("/retainers/<rid>/fund")
@endpoint(["AgencyAdmin"])
def fund_retainer(rid):
    b = validate.body()
    amount = validate.req_int(b, "amount_cents", minimum=1)
    retainer = services.must("retainer", rid)

    retainer["funded_cents"] += amount
    retainer["balance_cents"] += amount
    services.touch(retainer)
    services.retainer_status_recompute(retainer)
    return response.ok(db.public(retainer))
