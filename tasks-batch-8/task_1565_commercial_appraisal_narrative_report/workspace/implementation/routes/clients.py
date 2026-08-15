from flask import Blueprint

import response
from db import store, new_rec, serialize
from middleware import auth, require_role, get_body, req_str, req_enum
from services import domain

bp = Blueprint("clients", __name__)

CLIENT_TYPES = ("LENDER", "LAW_FIRM", "INVESTOR", "GOVERNMENT_AGENCY")


@bp.post("/clients")
def create_client():
    _, role = auth()
    require_role(role, {"EngagementManager"})
    body = get_body()
    name = req_str(body, "name")
    client_type = req_enum(body, "client_type", CLIENT_TYPES)
    rec = new_rec(
        {
            "name": name,
            "client_type": client_type,
            "total_billed_cents": 0,
            "volume_discount_tier": "NONE",
        }
    )
    store.clients[rec["id"]] = rec
    return response.success(serialize(rec), status=201)


@bp.get("/clients/<clientId>")
def get_client(clientId):
    auth()
    rec = domain.get_client(clientId)
    return response.success(serialize(rec))
