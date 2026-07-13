"""Statements of work and the rate pin (PRD 3.2)."""
from flask import Blueprint, request

import db
import response
import services
import validate
from auth import ALL_ROLES, endpoint
from errors import ApiError

bp = Blueprint("sows", __name__)


@bp.post("/sows")
@endpoint(["AccountManager"])
def create_sow():
    b = validate.body()
    client_id = validate.req_str(b, "client_id")
    rate_card_id = validate.req_str(b, "rate_card_id")
    title = validate.req_str(b, "title")
    labor_cap = validate.req_int(b, "labor_cap_cents", minimum=0)
    markup_pct = validate.req_num(b, "markup_pct", minimum=0, maximum=1)
    effective_start = validate.req_datetime(b, "effective_start")
    effective_end = validate.req_datetime(b, "effective_end")
    if effective_end <= effective_start:
        validate.bad("effective_end must be strictly after effective_start.")

    services.must("client", client_id)
    services.must("rate_card", rate_card_id)

    obj = db.base_entity()
    obj.update(
        {
            "client_id": client_id,
            "rate_card_id": rate_card_id,
            "title": title,
            "labor_cap_cents": labor_cap,
            "markup_pct": markup_pct,
            "effective_start": b["effective_start"],
            "effective_end": b["effective_end"],
            "status": "DRAFT",
            "pinned_rate_card_version": None,
            "pinned_rate_junior_cents_per_hour": None,
            "pinned_rate_senior_cents_per_hour": None,
            "pinned_rate_director_cents_per_hour": None,
            "consumed_labor_cents": 0,
            "_effective_start_dt": effective_start,
            "_effective_end_dt": effective_end,
        }
    )
    db.SOWS[obj["id"]] = obj
    return response.created(db.public(obj))


@bp.get("/sows/<sid>")
@endpoint(ALL_ROLES)
def get_sow(sid):
    return response.ok(db.public(services.must("sow", sid)))


@bp.get("/sows")
@endpoint(["AgencyAdmin", "AccountManager", "ClientReviewer"])
def list_sows():
    limit, offset = validate.pagination()
    client_id = request.args.get("client_id")
    rate_card_id = request.args.get("rate_card_id")
    status = request.args.get("status")
    rows = db.ordered(db.SOWS)
    if client_id:
        rows = [s for s in rows if s["client_id"] == client_id]
    if rate_card_id:
        rows = [s for s in rows if s["rate_card_id"] == rate_card_id]
    if status:
        rows = [s for s in rows if s["status"] == status]
    return response.listing(rows, limit, offset)


@bp.post("/sows/<sid>/countersign")
@endpoint(["ClientReviewer"])
def countersign_sow(sid):
    sow = services.must("sow", sid)
    services.must_own_client(sow["client_id"])

    if sow["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE")
    if db.clock_now() >= sow["_effective_end_dt"]:
        raise ApiError("ERR_SOW_EXPIRED")

    card = db.RATE_CARDS.get(sow["rate_card_id"])
    if card is None:
        raise ApiError("ERR_RATE_CARD_NOT_FOUND")

    sow["status"] = "COUNTERSIGNED"
    sow["pinned_rate_card_version"] = card["version"]
    sow["pinned_rate_junior_cents_per_hour"] = card["rate_junior_cents_per_hour"]
    sow["pinned_rate_senior_cents_per_hour"] = card["rate_senior_cents_per_hour"]
    sow["pinned_rate_director_cents_per_hour"] = card["rate_director_cents_per_hour"]
    services.touch(sow)
    return response.ok(db.public(sow))
