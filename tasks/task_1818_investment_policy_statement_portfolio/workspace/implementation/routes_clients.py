from flask import Blueprint, request

import store as db
from auth import authorize
from envelope import obj, page
from errors import ApiError
from logic import (new_common, touch, get_or_404, pin_expiry_cascade)
from serialize import client_out
from validate import body, no_unknown, req_str, req_int, pagination
import logical_clock as clock

bp = Blueprint("clients", __name__)


@bp.post("/advisory/clients")
def create_client():
    authorize("Advisor")
    b = body()
    no_unknown(b, {"full_name", "risk_tolerance_score"})
    full_name = req_str(b, "full_name")
    risk = req_int(b, "risk_tolerance_score", 1, 100)
    c = new_common()
    c.update({"full_name": full_name, "risk_tolerance_score": risk,
              "status": "PROSPECT"})
    db.clients[c["id"]] = c
    return obj(client_out(c), 201)


@bp.get("/advisory/clients")
def list_clients():
    authorize("Advisor", "ComplianceOfficer")
    limit, offset = pagination()
    status = request.args.get("status")
    rows = sorted(db.clients.values(), key=lambda e: (e["created_dt"], e["_seq"]))
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    total = len(rows)
    return page([client_out(c) for c in rows[offset:offset + limit]],
                limit, offset, total)


@bp.get("/advisory/clients/<cid>")
def get_client(cid):
    uid, role = authorize("Advisor", "ComplianceOfficer", "Client")
    # Ownership (priority 3) precedes existence (priority 5) for the self-read:
    # the client record's owning key is its own id.
    if role == "Client" and cid != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Clients may read only themselves")
    c = get_or_404(db.clients, cid)
    return obj(client_out(c))


@bp.post("/advisory/clients/<cid>/activate")
def activate_client(cid):
    authorize("Advisor")
    if request.data:
        b = body()
        no_unknown(b, set())
    c = get_or_404(db.clients, cid)
    if c["status"] != "PROSPECT":
        raise ApiError("ERR_CLIENT_INVALID_STATE", 409,
                       "Client activation requires PROSPECT")
    c["status"] = "ACTIVE"
    touch(c)
    return obj(client_out(c))


@bp.post("/advisory/clients/<cid>/terminate")
def terminate_client(cid):
    authorize("Advisor")
    if request.data:
        b = body()
        no_unknown(b, set())
    c = get_or_404(db.clients, cid)
    if c["status"] != "ACTIVE":
        raise ApiError("ERR_CLIENT_INVALID_STATE", 409,
                       "Client termination requires ACTIVE")
    for pf in db.portfolios.values():
        if pf["client_id"] == cid and pf["lifecycle_status"] != "CLOSED":
            raise ApiError("ERR_CLIENT_INVALID_STATE", 409,
                           "All portfolios must be CLOSED before termination")
    # Cascade: non-terminal IPS -> ARCHIVED; pinned proposals -> EXPIRED;
    # their PENDING/BLOCKED trades -> CANCELLED.
    archived = []
    for ips in db.ips_policies.values():
        if (ips["client_id"] == cid
                and ips["status"] in ("DRAFT", "PENDING_COMPLIANCE",
                                      "PENDING_CLIENT", "ACTIVE")):
            ips["status"] = "ARCHIVED"
            touch(ips)
            archived.append(ips["id"])
    for ips_id in archived:
        pin_expiry_cascade(ips_id)
    c["status"] = "TERMINATED"
    touch(c)
    return obj(client_out(c))
