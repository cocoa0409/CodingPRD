"""Artist endpoints (PRD 3.1)."""
from flask import Blueprint

from db import db
from errors import raise_error, ERR_INVALID_STATE
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response, public, scoped_mutation_auth
from services.core import new_record, touch
from validate import get_body, opt_str, req_str, require_path_resource

bp = Blueprint("artists", __name__)

ARTIST_STATUSES = {"ACTIVE", "ON_HIATUS", "ARCHIVED"}


@bp.post("/artists")
def create_artist():
    caller = authorized(["FirmAdmin"])  # unscoped: no target artist yet
    body = get_body()
    stage_name = req_str(body, "stage_name")
    legal_name = req_str(body, "legal_name")
    primary_genre = req_str(body, "primary_genre")
    home_currency = opt_str(body, "home_currency", "USD")
    rec = new_record("artists", {
        "stage_name": stage_name,
        "legal_name": legal_name,
        "primary_genre": primary_genre,
        "home_currency": home_currency,
        "status": "ACTIVE",
        "current_agreement_id": None,
        "unrecouped_advance_balance_cents": 0,
        "lifetime_gross_cents": 0,
        "lifetime_commission_cents": 0,
        "lifetime_disbursed_cents": 0,
    })
    return success_object(public(rec), status=201)


@bp.get("/artists/<rid>")
def get_artist(rid):
    return get_one("artists", rid)


@bp.get("/artists")
def list_artists():
    filters = {
        "status": __import__("flask").request.args.get("status"),
        "current_agreement_id": __import__("flask").request.args.get("current_agreement_id"),
    }
    return list_response("artists", filters)


@bp.patch("/artists/<rid>")
def patch_artist(rid):
    caller = scoped_mutation_auth(["FirmAdmin"], "artists", rid)
    body = get_body()
    artist = require_path_resource("artists", rid)

    new_status = body.get("status")
    if new_status is not None:
        if not isinstance(new_status, str) or new_status not in ARTIST_STATUSES:
            raise_error(ERR_INVALID_STATE, f"invalid artist status: {new_status}")
        cur = artist["status"]
        if new_status == cur:
            pass  # no-op same-status write is treated as a field update below
        elif cur == "ACTIVE" and new_status in ("ON_HIATUS", "ARCHIVED"):
            artist["status"] = new_status
            touch(artist)
            if new_status == "ARCHIVED":
                _archive_cascade(artist)
        elif cur == "ON_HIATUS" and new_status in ("ACTIVE", "ARCHIVED"):
            artist["status"] = new_status
            touch(artist)
            if new_status == "ARCHIVED":
                _archive_cascade(artist)
        else:
            raise_error(ERR_INVALID_STATE, f"cannot transition artist from {cur} to {new_status}")

    changed = False
    if "stage_name" in body and body["stage_name"] is not None:
        v = body["stage_name"]
        if not isinstance(v, str) or not v.strip():
            from errors import ERR_INVALID_REQUEST
            raise_error(ERR_INVALID_REQUEST, "stage_name must be a non-empty string")
        if artist["stage_name"] != v:
            artist["stage_name"] = v
            changed = True
    if "home_currency" in body and body["home_currency"] is not None:
        v = body["home_currency"]
        if not isinstance(v, str) or not v.strip():
            from errors import ERR_INVALID_REQUEST
            raise_error(ERR_INVALID_REQUEST, "home_currency must be a non-empty string")
        if artist["home_currency"] != v:
            artist["home_currency"] = v
            changed = True
    if changed:
        touch(artist)
    return success_object(public(artist))


def _archive_cascade(artist):
    """Archiving cascades: TeamMembers ACTIVE/SUSPENDED -> ENDED (PRD 3.1)."""
    for tm in db["team_members"].values():
        if tm["artist_id"] == artist["id"] and tm["status"] in ("ACTIVE", "SUSPENDED"):
            tm["status"] = "ENDED"
            touch(tm)
