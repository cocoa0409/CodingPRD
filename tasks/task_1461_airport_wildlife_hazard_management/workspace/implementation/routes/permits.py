"""Take permits: issue, list, take-preview, annual report, revoke."""
from flask import Blueprint, request

import errors as E
from auth import authenticate, require_roles
from constants import PERMIT_STATUSES
from db import store
from services import projected_take
from util import (body, validate_payload, check_fk, get_or_404, list_response,
                  ok_object, new_entity, serialize, touch)

bp = Blueprint("permits", __name__, url_prefix="/wildlife")

READ_ROLES = ("WildlifeBiologist", "AirportAdmin", "RegulatorAgent")


def _get_permit(rid):
    return get_or_404(store.take_permits, rid, "take permit")


@bp.post("/take-permits")
def create_permit():
    uid, role = authenticate()
    require_roles(role, ("RegulatorAgent",))
    data = validate_payload(body(), [
        ("airport_id", "str", True),
        ("species_id", "str", True),
        ("issued_by_regulator_id", "str", True),
        ("permit_number", "str", True),
        ("authorized_take_total", "int", True, {"min": 1}),
        ("valid_from", "date", True),
        ("valid_to", "date", True),
    ])
    check_fk("airport_id", data["airport_id"], store.airports, "airport")
    check_fk("species_id", data["species_id"], store.species, "species")
    check_fk("issued_by_regulator_id", data["issued_by_regulator_id"], store.regulators, "regulator agent")
    for p in store.take_permits.values():
        if p["permit_number"] == data["permit_number"]:
            raise E.invalid_request("permit_number must be unique")
    rec = new_entity(store.take_permits, {
        "airport_id": data["airport_id"],
        "species_id": data["species_id"],
        "issued_by_regulator_id": data["issued_by_regulator_id"],
        "permit_number": data["permit_number"],
        "authorized_take_total": data["authorized_take_total"],
        "take_consumed": 0,
        "valid_from": data["valid_from"],
        "valid_to": data["valid_to"],
        "status": "ISSUED",
        "annual_report_submitted": False,
    })
    return ok_object(serialize(rec), 201)


@bp.get("/take-permits")
def list_permits():
    uid, role = authenticate()
    require_roles(role, READ_ROLES)
    args = request.args
    status = args.get("status")
    if status is not None and status not in PERMIT_STATUSES:
        raise E.invalid_enum("status", status)
    rows = [p for p in store.take_permits.values()
            if (args.get("airport_id") is None or p["airport_id"] == args.get("airport_id"))
            and (args.get("species_id") is None or p["species_id"] == args.get("species_id"))
            and (status is None or p["status"] == status)
            and (args.get("issued_by_regulator_id") is None or p["issued_by_regulator_id"] == args.get("issued_by_regulator_id"))]
    return list_response(rows)


@bp.get("/take-permits/<rid>")
def get_permit(rid):
    uid, role = authenticate()
    require_roles(role, READ_ROLES)
    return ok_object(serialize(_get_permit(rid)))


@bp.get("/take-permits/<rid>/take-preview")
def take_preview(rid):
    uid, role = authenticate()
    require_roles(role, READ_ROLES)
    p = _get_permit(rid)
    projected = projected_take(p["id"])
    return ok_object({
        "projected_take_consumed": projected,
        "projected_remaining": p["authorized_take_total"] - projected,
    })


@bp.post("/take-permits/<rid>/submit-annual-report")
def submit_annual_report(rid):
    uid, role = authenticate()
    require_roles(role, ("RegulatorAgent",))
    p = _get_permit(rid)
    report_body = body().get("report_body")
    if report_body is None:
        raise E.invalid_request("missing required field: 'report_body'")
    if p["status"] not in ("ACTIVE", "EXHAUSTED"):
        raise E.invalid_state("take permit must be in ACTIVE or EXHAUSTED to submit the annual report")
    # reconciliation invariant: take_consumed == sum over CLOSED dispersals
    closed_sum = sum(
        d["animals_taken_lethal"]
        for d in store.dispersal_activities.values()
        if d.get("take_permit_id") == p["id"] and d["status"] == "CLOSED"
    )
    if p["take_consumed"] != closed_sum:
        raise E.ApiError(E.ERR_TAKE_PERMIT_REQUIRED,
                         "annual depredation report does not reconcile with closed dispersal take", 422)
    p["annual_report_submitted"] = True
    p["status"] = "CLOSED"
    touch(p)
    return ok_object(serialize(p))


@bp.post("/take-permits/<rid>/revoke")
def revoke_permit(rid):
    uid, role = authenticate()
    require_roles(role, ("RegulatorAgent",))
    p = _get_permit(rid)
    if p["status"] != "ACTIVE":
        raise E.invalid_state("take permit must be in ACTIVE to revoke")
    issuer = store.regulators.get(p["issued_by_regulator_id"])
    actor = store.regulators.get(uid)
    if actor is None or issuer is None or actor["agency"] != issuer["agency"]:
        raise E.ApiError(E.ERR_UNAUTHORIZED,
                         "only a regulator of the issuing agency may revoke this permit", 403)
    p["status"] = "REVOKED"
    touch(p)
    # cascade: still-LOGGED dispersals referencing this permit -> FLAGGED
    for d in store.dispersal_activities.values():
        if d.get("take_permit_id") == p["id"] and d["status"] == "LOGGED":
            d["status"] = "FLAGGED"
            touch(d)
    return ok_object(serialize(p))
