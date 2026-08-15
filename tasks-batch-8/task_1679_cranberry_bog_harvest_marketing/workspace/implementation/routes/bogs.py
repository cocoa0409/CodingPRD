"""Bog endpoints: register, get, list, renovation-cycle transitions.

Transition role split: plan (ACTIVE->RENOVATION_PLANNED) and cancel
(RENOVATION_PLANNED->ACTIVE) are GrowerMember-owner or FieldOfficer;
UNDER_RENOVATION, REPLANTED and certify (REPLANTED->ACTIVE) are FieldOfficer-only.
"""
from decimal import Decimal

from flask import Blueprint

from db import store, new_common, touch
from errors import ApiError
from middleware import authenticate, require_roles, forbidden, ANY_ROLE
from response import ok, created, paginate
from services import quota as quota_service
from validation import (get_body, req_string, req_number, req_int, req_enum,
                        opt_number, require_positive)

bp = Blueprint("bogs", __name__)

VARIETIES = {"STEVENS", "BEN_LEAR", "MULICA_QUEEN", "EARLY_BLACK"}
BOG_STATUSES = {"ACTIVE", "RENOVATION_PLANNED", "UNDER_RENOVATION", "REPLANTED"}

# (from, to, grower_owner_allowed, field_officer_allowed)
BOG_TRANSITIONS = [
    ("ACTIVE", "RENOVATION_PLANNED", True, True),
    ("RENOVATION_PLANNED", "ACTIVE", True, True),
    ("RENOVATION_PLANNED", "UNDER_RENOVATION", False, True),
    ("UNDER_RENOVATION", "REPLANTED", False, True),
    ("REPLANTED", "ACTIVE", False, True),
]


def get_bog_or_404(bog_id):
    bog = store.bogs.get(bog_id)
    if bog is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Bog not found")
    return bog


@bp.post("/coop/bogs")
def create_bog():
    body = get_body()
    name = req_string(body, "name")
    acres = require_positive(req_number(body, "acres"), "acres")
    variety = req_enum(body, "variety", VARIETIES)
    gpm = require_positive(req_int(body, "sprinkler_demand_gpm"), "sprinkler_demand_gpm")
    threshold = opt_number(body, "frost_damage_threshold_c")
    member_id_input = body.get("member_id")
    if member_id_input is not None and not isinstance(member_id_input, str):
        raise ApiError("ERR_VALIDATION", 400, "Field 'member_id' must be a string")

    uid, role = authenticate()
    require_roles(role, {"GrowerMember", "CoopAdmin"})

    if role == "GrowerMember":
        member_id = uid
    else:
        if not member_id_input:
            raise ApiError("ERR_VALIDATION", 400,
                           "CoopAdmin must supply member_id when registering a bog")
        if member_id_input not in store.members:
            raise ApiError("ERR_NOT_FOUND", 404, "Member not found")
        member_id = member_id_input

    bog = new_common({
        "member_id": member_id,
        "name": name,
        "acres": acres,
        "variety": variety,
        "sprinkler_demand_gpm": gpm,
        "frost_damage_threshold_c": threshold if threshold is not None else Decimal("-2.0"),
        "status": "ACTIVE",
    })
    store.bogs[bog["id"]] = bog
    return created(bog)


@bp.get("/coop/bogs/<bog_id>")
def get_bog(bog_id):
    _, role = authenticate()
    require_roles(role, ANY_ROLE)
    return ok(get_bog_or_404(bog_id))


@bp.get("/coop/bogs")
def list_bogs():
    _, role = authenticate()
    require_roles(role, ANY_ROLE)
    rows = list(store.bogs.values())
    rows = paginate.filter(rows, "member_id")
    rows = paginate.filter(rows, "status")
    return ok(paginate(rows), rtype="array", pagination=paginate)


@bp.post("/coop/bogs/<bog_id>/transition")
def transition_bog(bog_id):
    body = get_body()
    to = req_enum(body, "to", BOG_STATUSES)

    uid, role = authenticate()
    require_roles(role, {"GrowerMember", "FieldOfficer"})

    # Band-3 transition-target role split (before existence): a target whose
    # transitions never permit the caller's role is forbidden outright.
    target_rows = [t for t in BOG_TRANSITIONS if t[1] == to]
    if target_rows:
        if role == "GrowerMember" and not any(t[2] for t in target_rows):
            forbidden("Transition to %s is FieldOfficer-only" % to)
        if role == "FieldOfficer" and not any(t[3] for t in target_rows):
            forbidden("Transition to %s is not permitted for FieldOfficer" % to)

    bog = get_bog_or_404(bog_id)

    if role == "GrowerMember" and bog["member_id"] != uid:
        forbidden("GrowerMember may only act on their own bogs")

    row = next((t for t in BOG_TRANSITIONS
                if t[0] == bog["status"] and t[1] == to), None)
    if row is None:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Bog transition %s -> %s is not defined" % (bog["status"], to))
    if role == "GrowerMember" and not row[2]:
        forbidden("Transition to %s is FieldOfficer-only" % to)
    if role == "FieldOfficer" and not row[3]:
        forbidden("Transition to %s is not permitted for FieldOfficer" % to)

    bog["status"] = to
    touch(bog)

    # Quota ripples: entering UNDER_RENOVATION drops the bog from the quota
    # input set; certification back to ACTIVE re-adds it.
    if to == "UNDER_RENOVATION":
        quota_service.recompute_member_quotas(bog["member_id"])
    elif to == "ACTIVE" and row[0] == "REPLANTED":
        quota_service.recompute_member_quotas(bog["member_id"])

    return ok(bog)
