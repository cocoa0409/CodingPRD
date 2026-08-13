"""Client account endpoints."""
from flask import Blueprint

import errors
from db import DB
from middleware import auth, json_body
from response import ok
from services import CURRENCIES, base_record, client_json, lazy_read_tick

bp = Blueprint("clients", __name__)


@bp.post("/clients")
def create_client():
    auth(["CastingDirector"])
    body = json_body()
    # priority 10: uniqueness (before shape, priority 11)
    email = body.get("contact_email")
    if isinstance(email, str) and any(c["contact_email"] == email for c in DB["clients"].values()):
        raise errors.duplicate("Client contact_email already registered")
    # priority 11: shape
    for field in ("company_name", "contact_email", "billing_email"):
        if body.get(field) is None or not isinstance(body[field], str):
            raise errors.invalid_request(f"Missing or invalid required field: {field}")
    currency = body.get("default_currency", "USD")
    if currency not in CURRENCIES:
        raise errors.invalid_request("Invalid default_currency")
    rec = base_record()
    rec.update({
        "company_name": body["company_name"],
        "contact_email": body["contact_email"],
        "billing_email": body["billing_email"],
        "default_currency": currency,
        "account_status": "ACTIVE",
    })
    DB["clients"][rec["id"]] = rec
    return ok(client_json(rec), 201)


@bp.get("/clients/<cid>")
def get_client(cid):
    auth(["CastingDirector", "Client", "Agent"])
    lazy_read_tick()
    rec = DB["clients"].get(cid)
    if rec is None:
        raise errors.not_found("Client not found")
    return ok(client_json(rec))
