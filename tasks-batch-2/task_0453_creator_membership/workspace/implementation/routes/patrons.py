"""Patron endpoints (PRD §3.2)."""
from flask import Blueprint

import response
from db import db
from middleware import require_auth, require_role
from services import serialize
from services.common import init_common, get_body, require_string
from services.lookups import get_patron

bp = Blueprint("patrons", __name__)


@bp.post("/patrons")
def create_patron():
    ctx = require_auth()
    require_role(ctx, {"Patron"})
    body = get_body()
    display_name = require_string(body, "display_name")
    email = require_string(body, "email")
    rec = init_common({
        "display_name": display_name,
        "email": email,
        "wallet_credit_cents": 0,
        "status": "ACTIVE",
    })
    db.patrons[rec["id"]] = rec
    return response.success(serialize.patron(rec), status=201)


@bp.get("/patrons/<patron_id>")
def get_one_patron(patron_id):
    ctx = require_auth()
    require_role(ctx, {"Creator", "Patron", "PlatformAdmin"})
    rec = get_patron(patron_id)
    return response.success(serialize.patron(rec))
