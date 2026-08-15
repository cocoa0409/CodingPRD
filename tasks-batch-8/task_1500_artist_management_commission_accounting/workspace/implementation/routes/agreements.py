"""Agreement endpoints (PRD 3.2)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_STALE_ARTIST_VERSION,
    ERR_STALE_AGREEMENT_VERSION,
    ERR_ARTIST_ARCHIVED,
    ERR_NO_RATE_SCHEDULE,
)
from response import success_object
from routes.helpers import get_one, list_response, public, scoped_mutation_auth
from services.core import new_record, touch, set_sunset_window
from util import CLOCK, parse_date
from validate import (
    get_body, opt_enum, opt_int, req_date, req_str, require_path_resource, require_ref,
)

bp = Blueprint("agreements", __name__)

TOURING_BASES = {"GROSS", "NET_OF_EXPENSES"}
RECOUP_POLICIES = {"FIFO", "PRO_RATA"}


@bp.post("/agreements")
def create_agreement():
    body = get_body()
    artist_id = req_str(body, "artist_id")
    caller = scoped_mutation_auth(["FirmAdmin"], body_artist_id=artist_id)
    term_start = req_date(body, "term_start_date")
    term_end = req_date(body, "term_end_date")
    if parse_date(term_end) < parse_date(term_start):
        raise_error(ERR_INVALID_REQUEST, "term_end_date must be on or after term_start_date")
    tcb = opt_enum(body, "touring_commission_base", TOURING_BASES, "GROSS")
    rp = opt_enum(body, "recoupment_policy", RECOUP_POLICIES, "FIFO")
    expected_artist_version = opt_int(body, "expected_artist_version")

    artist = require_ref("artists", artist_id, "artist_id")
    # Priority 9: OCC on artist version
    if expected_artist_version is not None and expected_artist_version != artist["version"]:
        raise_error(ERR_STALE_ARTIST_VERSION,
                    "expected_artist_version does not match the artist's current version")

    rec = new_record("agreements", {
        "artist_id": artist_id,
        "prior_agreement_id": None,
        "term_start_date": term_start,
        "term_end_date": term_end,
        "termination_date": None,
        "touring_commission_base": tcb,
        "recoupment_policy": rp,
        "status": "DRAFT",
        "sunset_start_date": None,
        "sunset_end_date": None,
    })
    # Creation itself increments the artist's version (PRD 3.2)
    touch(artist)
    return success_object(public(rec), status=201)


@bp.get("/agreements/<rid>")
def get_agreement(rid):
    return get_one("agreements", rid)


@bp.get("/agreements")
def list_agreements():
    filters = {
        "artist_id": request.args.get("artist_id"),
        "prior_agreement_id": request.args.get("prior_agreement_id"),
        "status": request.args.get("status"),
    }
    return list_response("agreements", filters)


@bp.patch("/agreements/<rid>")
def patch_agreement(rid):
    caller = scoped_mutation_auth(["FirmAdmin"], "agreements", rid)
    body = get_body()
    ag = require_path_resource("agreements", rid)

    expected = opt_int(body, "expected_agreement_version")
    # Priority 9: OCC (state check happens first per priority 8)
    if ag["status"] == "DRAFT":
        pass
    elif ag["status"] == "ACTIVE":
        # only term_end_date extension allowed; check fields below
        pass
    else:
        raise_error(ERR_INVALID_STATE,
                    f"agreement in {ag['status']} may not be edited")

    if expected is not None and expected != ag["version"]:
        raise_error(ERR_STALE_AGREEMENT_VERSION,
                    "expected_agreement_version does not match the agreement's current version")

    changed = False
    if ag["status"] == "DRAFT":
        if "term_start_date" in body and body["term_start_date"] is not None:
            v = req_date(body, "term_start_date")
            if parse_date(v) > parse_date(body.get("term_end_date") or ag["term_end_date"]):
                raise_error(ERR_INVALID_REQUEST, "term_start_date must be on or before term_end_date")
            ag["term_start_date"] = v
            changed = True
        if "term_end_date" in body and body["term_end_date"] is not None:
            v = req_date(body, "term_end_date")
            if parse_date(v) < parse_date(ag["term_start_date"]):
                raise_error(ERR_INVALID_REQUEST, "term_end_date must be on or after term_start_date")
            ag["term_end_date"] = v
            changed = True
        if "touring_commission_base" in body and body["touring_commission_base"] is not None:
            ag["touring_commission_base"] = opt_enum(body, "touring_commission_base", TOURING_BASES)
            changed = True
        if "recoupment_policy" in body and body["recoupment_policy"] is not None:
            ag["recoupment_policy"] = opt_enum(body, "recoupment_policy", RECOUP_POLICIES)
            changed = True
    else:  # ACTIVE: only term_end_date extension
        if "term_end_date" in body and body["term_end_date"] is not None:
            v = req_date(body, "term_end_date")
            if parse_date(v) <= parse_date(ag["term_end_date"]):
                raise_error(ERR_INVALID_REQUEST,
                            "ACTIVE agreement edit may only extend term_end_date to a later date")
            ag["term_end_date"] = v
            changed = True
        else:
            raise_error(ERR_INVALID_STATE,
                        "ACTIVE agreement edit may only extend term_end_date")

    if changed:
        touch(ag)
    return success_object(public(ag))


@bp.post("/agreements/<rid>/activate")
def activate_agreement(rid):
    caller = scoped_mutation_auth(["FirmAdmin"], "agreements", rid)
    ag = require_path_resource("agreements", rid)
    if ag["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, "only a DRAFT agreement can be activated")
    artist = db["artists"].get(ag["artist_id"])
    if artist is not None and artist["status"] == "ARCHIVED":
        raise_error(ERR_ARTIST_ARCHIVED, "artist is ARCHIVED")
    has_schedule = any(
        s["agreement_id"] == ag["id"] for s in db["rate_schedules"].values()
    )
    if not has_schedule:
        raise_error(ERR_NO_RATE_SCHEDULE,
                    "at least one CommissionRateSchedule must exist before activation")

    # Supersede the artist's currently ACTIVE agreement, if any
    prior = None
    for other in db["agreements"].values():
        if other["artist_id"] == ag["artist_id"] and other["status"] == "ACTIVE" and other["id"] != ag["id"]:
            prior = other
            break
    if prior is not None:
        prior["status"] = "SUPERSEDED"
        set_sunset_window(prior, CLOCK.today())
        touch(prior)

    ag["prior_agreement_id"] = prior["id"] if prior else None
    ag["status"] = "ACTIVE"
    touch(ag)
    if artist is not None:
        artist["current_agreement_id"] = ag["id"]
        touch(artist)
    return success_object(public(ag))


@bp.post("/agreements/<rid>/terminate")
def terminate_agreement(rid):
    caller = scoped_mutation_auth(["FirmAdmin"], "agreements", rid)
    body = get_body()
    ag = require_path_resource("agreements", rid)
    termination_date = req_date(body, "termination_date")
    if ag["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE, "only an ACTIVE agreement can be terminated")
    from datetime import timedelta
    ag["status"] = "TERMINATED"
    ag["termination_date"] = termination_date
    set_sunset_window(ag, parse_date(termination_date) + timedelta(days=1))
    touch(ag)
    artist = db["artists"].get(ag["artist_id"])
    if artist is not None:
        artist["current_agreement_id"] = None
        touch(artist)
    return success_object(public(ag))
