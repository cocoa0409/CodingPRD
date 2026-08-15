"""Operational advisories: draft, activate (with supersession + airport OCC), cancel."""
from flask import Blueprint, request

import errors as E
from auth import authenticate, require_roles, biologist_is_senior
from constants import HAZARD_LEVELS, REASON_CODES, ADVISORY_STATUSES
from db import store
from services import recompute_airport
from util import (body, validate_payload, check_fk, get_or_404, list_response,
                  ok_object, new_entity, serialize, touch)

bp = Blueprint("advisories", __name__, url_prefix="/wildlife")

READ_ROLES = ("WildlifeBiologist", "AirportAdmin", "RegulatorAgent", "ATCController")


def _get_advisory(rid):
    return get_or_404(store.operational_advisories, rid, "operational advisory")


@bp.post("/operational-advisories")
def create_advisory():
    uid, role = authenticate()
    require_roles(role, ("WildlifeBiologist",))
    data = validate_payload(body(), [
        ("airport_id", "str", True),
        ("issued_by_biologist_id", "str", True),
        ("issued_at", "datetime", True),
        ("effective_from", "datetime", True),
        ("effective_to", "datetime", True),
        ("hazard_level", "enum", True, {"values": HAZARD_LEVELS}),
        ("reason_code", "enum", True, {"values": REASON_CODES}),
        ("supersedes_advisory_id", "str", False),
    ])
    check_fk("airport_id", data["airport_id"], store.airports, "airport")
    check_fk("issued_by_biologist_id", data["issued_by_biologist_id"], store.biologists, "biologist")
    if data.get("supersedes_advisory_id") is not None:
        check_fk("supersedes_advisory_id", data["supersedes_advisory_id"],
                 store.operational_advisories, "operational advisory")
    if not data["effective_from"] < data["effective_to"]:
        raise E.ApiError(E.ERR_INVALID_WINDOW,
                         "effective_to must be strictly after effective_from", 422)
    rec = new_entity(store.operational_advisories, {
        "airport_id": data["airport_id"],
        "issued_by_biologist_id": data["issued_by_biologist_id"],
        "issued_at": data["issued_at"],
        "effective_from": data["effective_from"],
        "effective_to": data["effective_to"],
        "hazard_level": data["hazard_level"],
        "status": "DRAFT",
        "reason_code": data["reason_code"],
        "supersedes_advisory_id": data.get("supersedes_advisory_id"),
    })
    return ok_object(serialize(rec), 201)


@bp.get("/operational-advisories")
def list_advisories():
    uid, role = authenticate()
    require_roles(role, READ_ROLES)
    args = request.args
    status = args.get("status")
    hazard = args.get("hazard_level")
    reason = args.get("reason_code")
    if status is not None and status not in ADVISORY_STATUSES:
        raise E.invalid_enum("status", status)
    if hazard is not None and hazard not in HAZARD_LEVELS:
        raise E.invalid_enum("hazard_level", hazard)
    if reason is not None and reason not in REASON_CODES:
        raise E.invalid_enum("reason_code", reason)
    rows = [a for a in store.operational_advisories.values()
            if (args.get("airport_id") is None or a["airport_id"] == args.get("airport_id"))
            and (status is None or a["status"] == status)
            and (hazard is None or a["hazard_level"] == hazard)
            and (reason is None or a["reason_code"] == reason)
            and (args.get("issued_by_biologist_id") is None or a["issued_by_biologist_id"] == args.get("issued_by_biologist_id"))
            and (args.get("supersedes_advisory_id") is None or a.get("supersedes_advisory_id") == args.get("supersedes_advisory_id"))]
    return list_response(rows)


@bp.get("/operational-advisories/<rid>")
def get_advisory(rid):
    uid, role = authenticate()
    require_roles(role, READ_ROLES)
    return ok_object(serialize(_get_advisory(rid)))


@bp.post("/operational-advisories/<rid>/activate")
def activate_advisory(rid):
    uid, role = authenticate()
    require_roles(role, ("WildlifeBiologist",))
    adv = _get_advisory(rid)
    data = body()
    if "expected_airport_version" not in data or data["expected_airport_version"] is None:
        raise E.invalid_request("missing required field: 'expected_airport_version'")
    expected = data["expected_airport_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise E.invalid_request("expected_airport_version must be an integer")
    if adv["status"] != "DRAFT":
        raise E.invalid_state("operational advisory must be in DRAFT to activate")
    if not biologist_is_senior(uid):
        raise E.ApiError(E.ERR_SENIOR_REQUIRED,
                         "activating an operational advisory requires a senior biologist", 403)
    if not adv["effective_from"] < adv["effective_to"]:
        raise E.ApiError(E.ERR_INVALID_WINDOW,
                         "effective_to must be strictly after effective_from", 422)
    prior = None
    if adv.get("supersedes_advisory_id"):
        prior = store.operational_advisories.get(adv["supersedes_advisory_id"])
        if prior is None or prior["status"] != "ACTIVE" or prior["airport_id"] != adv["airport_id"]:
            raise E.invalid_state(
                "supersedes_advisory_id must reference an ACTIVE advisory on the same airport")
    # OCC (priority 20): expected airport version must match
    ap = store.airports.get(adv["airport_id"])
    if ap is not None and expected != ap["version"]:
        raise E.ApiError(E.ERR_STALE_VERSION,
                         "expected_airport_version does not match the airport's current version", 412)
    adv["status"] = "ACTIVE"
    touch(adv)
    if prior is not None:
        prior["status"] = "SUPERSEDED"
        touch(prior)
    if ap is not None:
        recompute_airport(ap)
    return ok_object(serialize(adv))


@bp.post("/operational-advisories/<rid>/cancel")
def cancel_advisory(rid):
    uid, role = authenticate()
    require_roles(role, ("WildlifeBiologist",))
    adv = _get_advisory(rid)
    if adv["status"] != "DRAFT":
        raise E.invalid_state("operational advisory must be in DRAFT to cancel")
    if uid != adv["issued_by_biologist_id"]:
        raise E.ApiError(E.ERR_UNAUTHORIZED,
                         "only the issuing biologist may cancel this advisory", 403)
    adv["status"] = "CANCELLED"
    touch(adv)
    return ok_object(serialize(adv))
