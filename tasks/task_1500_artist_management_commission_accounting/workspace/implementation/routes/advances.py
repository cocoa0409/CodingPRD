"""Advance endpoints (PRD 3.6)."""
from flask import Blueprint, request

from db import db
from errors import raise_error, ERR_INVALID_STATE, ERR_ARTIST_ARCHIVED
from response import success_object
from routes.helpers import get_one, list_response, public, scoped_mutation_auth
from services.core import new_record, touch, recompute_artist
from validate import (
    get_body, opt_int, opt_str_list_of_enums, req_date, req_int, req_str,
    require_path_resource, require_ref,
)

bp = Blueprint("advances", __name__)

INCOME_TYPES = {"TOURING", "RECORDING", "PUBLISHING", "ENDORSEMENT"}


@bp.post("/advances")
def create_advance():
    body = get_body()
    artist_id = req_str(body, "artist_id")
    caller = scoped_mutation_auth(["BusinessManager", "FirmAdmin"], body_artist_id=artist_id)
    principal = req_int(body, "principal_cents", positive=True)
    issued_date = req_date(body, "issued_date")
    recoup_pct_bps = opt_int(body, "recoup_pct_bps", default=10000, minimum=1, maximum=10000)
    applies_to = opt_str_list_of_enums(body, "applies_to_income_types", INCOME_TYPES, default=[])

    artist = require_ref("artists", artist_id, "artist_id")
    if artist["status"] == "ARCHIVED":
        raise_error(ERR_ARTIST_ARCHIVED, "artist is ARCHIVED")

    rec = new_record("advances", {
        "artist_id": artist_id,
        "principal_cents": principal,
        "issued_date": issued_date,
        "recoup_pct_bps": recoup_pct_bps,
        "applies_to_income_types": applies_to,
        "recouped_cents": 0,
        "written_off_cents": 0,
        "outstanding_cents": principal,
        "status": "ACTIVE",
    })
    recompute_artist(artist_id, bump=True)
    return success_object(public(rec), status=201)


@bp.get("/advances/<rid>")
def get_advance(rid):
    return get_one("advances", rid)


@bp.get("/advances")
def list_advances():
    filters = {
        "artist_id": request.args.get("artist_id"),
        "status": request.args.get("status"),
    }
    return list_response("advances", filters)


@bp.post("/advances/<rid>/write-off")
def write_off_advance(rid):
    caller = scoped_mutation_auth(["FirmAdmin"], "advances", rid)
    adv = require_path_resource("advances", rid)
    if adv["status"] != "ACTIVE" or adv["outstanding_cents"] <= 0:
        raise_error(ERR_INVALID_STATE,
                    "write-off requires ACTIVE status with a positive outstanding balance")
    adv["written_off_cents"] = adv["outstanding_cents"]
    adv["outstanding_cents"] = 0
    adv["status"] = "WRITTEN_OFF"
    touch(adv)
    recompute_artist(adv["artist_id"], bump=True)
    return success_object(public(adv))
