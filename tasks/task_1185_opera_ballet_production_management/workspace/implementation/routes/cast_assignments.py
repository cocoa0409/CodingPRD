"""CastAssignment routes (PRD 3.5) — cover chains and promotion cascade."""

from flask import Blueprint

from db import store
from errors import (ApiError, ERR_CONTRACT_NOT_ACTIVE, ERR_COVER_LINK,
                    ERR_CROSS_PRODUCTION, ERR_INVALID_STATE,
                    ERR_PRINCIPAL_TAKEN, conflict)
from middleware import require_roles
from response import ok_object
from routes.common import get_or_404, list_response
from services import recompute_casting_status
from util import json_body, new_record, req_enum, req_str, to_public, touch

bp = Blueprint("cast_assignments", __name__)

SLOTS = ("PRINCIPAL", "COVER_1", "COVER_2")
_SLOT_RANK = {"COVER_1": 0, "COVER_2": 1}


def _cover_link_error(message):
    return ApiError(ERR_COVER_LINK, 422, message)


@bp.post("/opera/cast-assignments")
def create_assignment():
    require_roles("CastingDirector")
    body = json_body()
    role_id = req_str(body, "role_id")
    contract_id = req_str(body, "contract_id")
    slot = req_enum(body, "slot", SLOTS)
    role = get_or_404(store.roles, role_id, "Role")
    contract = get_or_404(store.contracts, contract_id, "Contract")

    covers_id = None
    if slot != "PRINCIPAL":
        # Required exactly when slot != PRINCIPAL; must reference a
        # PRINCIPAL-slot assignment on the same role.
        raw = body.get("covers_assignment_id")
        if not isinstance(raw, str):
            raise _cover_link_error(
                "covers_assignment_id is required for cover slots")
        target = store.cast_assignments.get(raw)
        if target is None:
            raise _cover_link_error("covers_assignment_id does not exist")
        if target["role_id"] != role["id"] or target["slot"] != "PRINCIPAL":
            raise _cover_link_error(
                "covers_assignment_id must reference a PRINCIPAL assignment "
                "on the same role")
        covers_id = raw

    if contract["production_id"] != role["production_id"]:
        raise ApiError(ERR_CROSS_PRODUCTION, 422,
                       "Contract and role belong to different productions")

    rec = new_record(
        production_id=role["production_id"],
        role_id=role["id"],
        contract_id=contract["id"],
        slot=slot,
        covers_assignment_id=covers_id,
        status="PROPOSED",
    )
    store.cast_assignments[rec["id"]] = rec
    return ok_object(to_public(rec), 201)


@bp.get("/opera/cast-assignments")
def list_assignments():
    require_roles("Any")
    return list_response(
        store.cast_assignments.values(),
        [("production_id", "production_id"), ("role_id", "role_id"),
         ("contract_id", "contract_id"),
         ("covers_assignment_id", "covers_assignment_id"),
         ("slot", "slot"), ("status", "status")],
    )


@bp.get("/opera/cast-assignments/<aid>")
def get_assignment(aid):
    require_roles("Any")
    return ok_object(to_public(get_or_404(store.cast_assignments, aid,
                                          "CastAssignment")))


@bp.post("/opera/cast-assignments/<aid>/confirm")
def confirm_assignment(aid):
    require_roles("CastingDirector")
    asn = get_or_404(store.cast_assignments, aid, "CastAssignment")
    if asn["status"] != "PROPOSED":
        raise conflict(ERR_INVALID_STATE,
                       f"CastAssignment in {asn['status']} cannot be confirmed")
    # Guards in pipeline order: contract state, cover link, principal quota.
    contract = store.contracts[asn["contract_id"]]
    if contract["status"] != "ACTIVE":
        raise conflict(ERR_CONTRACT_NOT_ACTIVE,
                       "Contract must be ACTIVE to confirm an assignment")
    if asn["slot"] != "PRINCIPAL":
        target = store.cast_assignments.get(asn["covers_assignment_id"] or "")
        if target is None or target["status"] != "CONFIRMED":
            raise _cover_link_error(
                "The referenced principal assignment must be CONFIRMED")
    else:
        for other in store.cast_assignments.values():
            if (other["id"] != asn["id"] and other["role_id"] == asn["role_id"]
                    and other["slot"] == "PRINCIPAL"
                    and other["status"] == "CONFIRMED"):
                raise conflict(ERR_PRINCIPAL_TAKEN,
                               "Role already has a CONFIRMED principal")
    asn["status"] = "CONFIRMED"
    touch(asn)
    role = store.roles[asn["role_id"]]
    recompute_casting_status(role)
    return ok_object(to_public(asn))


@bp.post("/opera/cast-assignments/<aid>/release")
def release_assignment(aid):
    require_roles("CastingDirector")
    asn = get_or_404(store.cast_assignments, aid, "CastAssignment")
    if asn["status"] == "PROPOSED":
        asn["status"] = "WITHDRAWN"
        touch(asn)
    elif asn["status"] == "CONFIRMED":
        was_principal = asn["slot"] == "PRINCIPAL"
        asn["status"] = "RELEASED"
        touch(asn)
        if was_principal:
            _promote_cover(asn)
    else:
        raise conflict(ERR_INVALID_STATE,
                       f"CastAssignment in {asn['status']} cannot be released")
    role = store.roles[asn["role_id"]]
    recompute_casting_status(role)
    return ok_object(to_public(asn))


def _promote_cover(released):
    """Cover-promotion cascade (PRD 3.5): lowest slot rank, created_at ASC;
    promoted cover becomes PRINCIPAL; other CONFIRMED covers re-point."""
    covers = [a for a in store.cast_assignments.values()
              if a["covers_assignment_id"] == released["id"]
              and a["status"] == "CONFIRMED"]
    if not covers:
        return
    covers.sort(key=lambda a: (_SLOT_RANK.get(a["slot"], 9), a["created_at"],
                               a["_seq"]))
    promoted = covers[0]
    promoted["slot"] = "PRINCIPAL"
    promoted["covers_assignment_id"] = None
    touch(promoted)
    for other in covers[1:]:
        other["covers_assignment_id"] = promoted["id"]
        touch(other)
