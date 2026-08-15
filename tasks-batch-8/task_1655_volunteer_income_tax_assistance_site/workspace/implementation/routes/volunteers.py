"""Volunteer registration, testing, activation (PRD §3.2)."""
from flask import Blueprint

import db
from db import store
from errors import ApiError
from middleware import get_context, require_roles
from response import created, ok, paginate
from services import cascades, certs
from services.serialize import certification_json, volunteer_json
from validation import get_body, parse_body, require_entity

bp = Blueprint("volunteers", __name__)

VOLUNTEER_STATUSES = ["REGISTERED", "ACTIVE", "INACTIVE"]

CREATE_SCHEMA = {
    "site_id": {"kind": "string", "required": True},
    "full_name": {"kind": "string", "required": True},
    "email": {"kind": "string", "required": True},
    "is_coordinator": {"kind": "boolean"},
}

STATE_SCHEMA = {
    "to_status": {"kind": "enum", "required": True, "values": VOLUNTEER_STATUSES},
}

CERT_SCHEMA = {
    "test_type": {"kind": "enum", "required": True, "values": certs.TEST_TYPES},
    "score": {"kind": "integer", "required": True, "min": 0, "max": 100},
    "tax_season": {"kind": "integer", "required": True},
    "expected_volunteer_version": {"kind": "integer", "required": True},
}


@bp.post("/volunteers")
def create_volunteer():
    get_context()
    require_roles(["SiteCoordinator", "SponsorAdmin"])
    raw = get_body()
    # Existence (tier 3) precedes schema (tier 4): check a referenced site id
    # that is present and well-typed before the rest of the schema runs.
    site_id = raw.get("site_id")
    if isinstance(site_id, str) and site_id not in store.sites:
        raise ApiError("ERR_NOT_FOUND", 404, "Referenced site does not exist")
    body = parse_body(CREATE_SCHEMA)
    site = store.sites.get(body["site_id"])
    if site is None:
        # site_id present but not a string -> type error; unreachable otherwise.
        raise ApiError("ERR_INVALID_REQUEST", 400, "site_id has a wrong type")
    # Uniqueness (tier 7): email unique across all volunteers -> ERR_INVALID_REQUEST.
    if any(v["email"] == body["email"] for v in store.volunteers.values()):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "email is already registered to another volunteer")
    vol = db.new_common({
        "site_id": body["site_id"],
        "full_name": body["full_name"],
        "email": body["email"],
        "is_coordinator": body.get("is_coordinator", False),
        "status": "REGISTERED",
    })
    store.volunteers[vol["id"]] = vol
    return created(volunteer_json(vol))


@bp.get("/volunteers/<volunteer_id>")
def get_volunteer(volunteer_id):
    get_context()
    vol = require_entity(store.volunteers, volunteer_id)
    return ok(volunteer_json(vol))


@bp.post("/volunteers/<volunteer_id>/state")
def transition_volunteer(volunteer_id):
    get_context()
    require_roles(["SiteCoordinator", "SponsorAdmin"])
    vol = require_entity(store.volunteers, volunteer_id)
    body = parse_body(STATE_SCHEMA)
    current = vol["status"]
    target = body["to_status"]

    if target == "ACTIVE" and current in ("REGISTERED", "INACTIVE"):
        # Activation requires a CURRENT passed ETHICS certification for 2026,
        # and is barred once the volunteer's site is CLOSED.
        if not certs.has_current_passed(volunteer_id, "ETHICS"):
            raise ApiError("ERR_VOLUNTEER_NOT_CERTIFIED", 403,
                           "Volunteer lacks a CURRENT passed ETHICS certification "
                           "for season 2026")
        site = store.sites.get(vol["site_id"])
        if site is not None and site["status"] == "CLOSED":
            raise ApiError("ERR_INVALID_TRANSITION", 409,
                           "Volunteer's site is CLOSED")
    elif target == "INACTIVE" and current == "ACTIVE":
        cascades.volunteer_inactivation_cascade(volunteer_id)
    else:
        raise ApiError("ERR_INVALID_TRANSITION", 409,
                       "Cannot move volunteer from %s to %s" % (current, target))

    vol["status"] = target
    db.touch(vol)
    return ok(volunteer_json(vol))


@bp.post("/volunteers/<volunteer_id>/certifications")
def record_certification(volunteer_id):
    get_context()
    require_roles(["SiteCoordinator", "SponsorAdmin"])
    vol = require_entity(store.volunteers, volunteer_id)
    body = parse_body(CERT_SCHEMA)
    # OCC (PRD §2.7): the recording mutates the volunteer.
    if body["expected_volunteer_version"] != vol["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_volunteer_version does not match the volunteer's "
                       "current version")

    test_type = body["test_type"]
    tax_season = body["tax_season"]
    earlier = [c for c in store.certifications.values()
               if c["volunteer_id"] == volunteer_id and c["test_type"] == test_type
               and c["tax_season"] == tax_season]
    prior_current = next((c for c in earlier if c["status"] == "CURRENT"), None)

    cert = db.new_common({
        "volunteer_id": volunteer_id,
        "test_type": test_type,
        "score": body["score"],
        "tax_season": tax_season,
        "passed": body["score"] >= certs.PASS_SCORE,
        "status": "CURRENT",
        "attempt_number": 1 + len(earlier),
    })
    store.certifications[cert["id"]] = cert
    for c in earlier:
        if c["status"] == "CURRENT":
            c["status"] = "SUPERSEDED"
            db.touch(c)

    # Recording an attempt mutates the volunteer (PRD §3.2): bump its version.
    db.touch(vol)

    # Supersession teeth: a failed ETHICS 2026 attempt that superseded the
    # volunteer's CURRENT passed ETHICS 2026 row demotes ACTIVE -> INACTIVE
    # with the full appointment-cancel cascade.
    if (test_type == "ETHICS" and tax_season == certs.CURRENT_SEASON
            and not cert["passed"] and prior_current is not None
            and prior_current["passed"] and vol["status"] == "ACTIVE"):
        cascades.volunteer_inactivation_cascade(volunteer_id)
        vol["status"] = "INACTIVE"
        db.touch(vol)

    return created(certification_json(cert))


@bp.get("/volunteers/<volunteer_id>/certifications")
def list_certifications(volunteer_id):
    get_context()
    require_entity(store.volunteers, volunteer_id)
    rows = [c for c in store.certifications.values()
            if c["volunteer_id"] == volunteer_id]
    page = paginate(rows)
    return ok([certification_json(c) for c in page], rtype="array",
              pagination=paginate)
