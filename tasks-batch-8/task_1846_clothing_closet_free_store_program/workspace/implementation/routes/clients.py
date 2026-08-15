"""Client registration, profile updates, discipline (PRD 3.1)."""
from flask import Blueprint, g

import services as svc
from db import stamp_new, store, touch
from errors import ApiError, bad_request, forbidden, invalid_state, not_found
from middleware import require_roles
from response import ok, ok_list
from util import (
    get_body, opt_enum_filter, page_params, paginate, v_enum, v_int, v_str,
)

bp = Blueprint("clients", __name__)

TIERS = {"STANDARD", "HARDSHIP"}
CLIENT_STATUSES = {"ACTIVE", "SUSPENDED"}


def get_client_or_404(client_id):
    c = store.clients.get(client_id)
    if c is None:
        raise not_found("Client not found")
    return c


@bp.post("/closet/clients")
@require_roles("ProgramAdmin", "VolunteerLead", "Volunteer")
def create_client():
    data = get_body()
    full_name = v_str(data, "full_name")
    household_size = v_int(data, "household_size", lo=1)
    tier = v_enum(data, "eligibility_tier", TIERS, required=False, default="STANDARD")
    c = stamp_new({
        "full_name": full_name,
        "household_size": household_size,
        "eligibility_tier": tier,
        "status": "ACTIVE",
        "last_checkout_at": None,
    })
    store.clients[c["id"]] = c
    return ok(svc.serialize_client(c), 201)


@bp.get("/closet/clients")
@require_roles("ProgramAdmin", "VolunteerLead", "Volunteer")
def list_clients():
    status = opt_enum_filter("status", CLIENT_STATUSES)
    limit, offset = page_params()
    rows = list(store.clients.values())
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list([svc.serialize_client(c) for c in page], total, limit, offset)


@bp.get("/closet/clients/<cid>")
@require_roles("ProgramAdmin", "VolunteerLead", "Volunteer", "Client")
def get_client(cid):
    # Ownership scope: a Client may read only their own record.
    if g.user_role == "Client" and g.user_id != cid:
        raise forbidden("Clients may only read their own record")
    c = get_client_or_404(cid)
    return ok(svc.serialize_client(c))


@bp.patch("/closet/clients/<cid>")
@require_roles("ProgramAdmin", "VolunteerLead")
def update_client(cid):
    c = get_client_or_404(cid)
    data = get_body()
    household_size = v_int(data, "household_size", required=False, lo=1)
    tier = v_enum(data, "eligibility_tier", TIERS, required=False)
    expected = v_int(data, "expected_client_version")
    if expected != c["version"]:
        raise ApiError(
            "ERR_STALE_VERSION", 412,
            "expected_client_version does not match the client's current version",
        )
    if household_size is not None:
        c["household_size"] = household_size
    if tier is not None:
        c["eligibility_tier"] = tier
    touch(c)
    return ok(svc.serialize_client(c))


@bp.post("/closet/clients/<cid>/suspend")
@require_roles("ProgramAdmin", "VolunteerLead")
def suspend_client(cid):
    c = get_client_or_404(cid)
    if c["status"] != "ACTIVE":
        raise invalid_state("Only an ACTIVE client can be suspended")
    c["status"] = "SUSPENDED"
    touch(c)
    return ok(svc.serialize_client(c))


@bp.post("/closet/clients/<cid>/reinstate")
@require_roles("ProgramAdmin", "VolunteerLead")
def reinstate_client(cid):
    c = get_client_or_404(cid)
    if c["status"] != "SUSPENDED":
        raise invalid_state("Only a SUSPENDED client can be reinstated")
    c["status"] = "ACTIVE"
    touch(c)
    return ok(svc.serialize_client(c))
