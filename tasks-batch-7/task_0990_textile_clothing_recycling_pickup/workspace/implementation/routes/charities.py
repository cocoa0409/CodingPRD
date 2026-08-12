"""Charity endpoints."""
from flask import Blueprint

from db import store, new_record
from errors import fail
from middleware import endpoint
from response import success
from services import domain
from util import check_fields, get_body

bp = Blueprint("charities", __name__)


@bp.route("/charities", methods=["POST"])
@endpoint(["ZoneOperator"])
def create_charity(user_id, role):
    body = get_body()
    check_fields(body, {"name": ("str", True)})
    rec = new_record()
    rec.update({"name": body["name"]})
    store.charities[rec["id"]] = rec
    return success(domain.charity_view(rec), code=201)


@bp.route("/charities/<cid>", methods=["GET"])
@endpoint(["ZoneOperator", "CharityAdmin"])
def get_charity(user_id, role, cid):
    if role == "CharityAdmin" and user_id != cid:
        fail("ERR_UNAUTHORIZED", "CharityAdmins may only read their own charity")
    charity = domain.get_or_404(store.charities, cid, "Charity")
    return success(domain.charity_view(charity))


@bp.route("/charities/<cid>/allocations", methods=["GET"])
@endpoint(["ZoneOperator", "CharityAdmin"])
def get_charity_allocations(user_id, role, cid):
    if role == "CharityAdmin" and user_id != cid:
        fail("ERR_UNAUTHORIZED", "CharityAdmins may only read their own allocations")
    charity = domain.get_or_404(store.charities, cid, "Charity")
    allocations = []
    settled = [c for c in store.credits.values() if c["status"] == "SETTLED"]
    settled.sort(key=lambda c: (c["created_at"], c["_seq"]))
    for c in settled:
        for line in c.get("charity_allocations") or []:
            if line["charity_id"] == cid:
                allocations.append({
                    "credit_id": c["id"],
                    "ticket_id": c["ticket_id"],
                    "pct": line["pct"],
                    "amount_cents": line["amount_cents"],
                })
    return success({
        "charity_id": cid,
        "total_received_cents": domain.charity_total(cid),
        "allocations": allocations,
    })
