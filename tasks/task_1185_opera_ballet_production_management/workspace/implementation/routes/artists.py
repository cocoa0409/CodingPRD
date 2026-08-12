"""Artist routes (PRD 3.4)."""

from flask import Blueprint

from db import store
from middleware import require_roles
from response import ok_object
from routes.common import get_or_404, list_response
from util import json_body, new_record, req_enum, req_str, to_public

bp = Blueprint("artists", __name__)

DISCIPLINES = ("PRINCIPAL_DANCER", "CORPS_DANCER", "SOPRANO", "TENOR", "CHORUS",
               "ORCHESTRA")
UNION_CODES = ("AGMA", "AFM", "EQUITY")


@bp.post("/opera/artists")
def create_artist():
    require_roles("ContractsOfficer")
    body = json_body()
    rec = new_record(
        full_name=req_str(body, "full_name"),
        discipline=req_enum(body, "discipline", DISCIPLINES),
        union_code=req_enum(body, "union_code", UNION_CODES),
    )
    store.artists[rec["id"]] = rec
    return ok_object(to_public(rec), 201)


@bp.get("/opera/artists")
def list_artists():
    require_roles("Any")
    return list_response(store.artists.values(), [("discipline", "discipline")])


@bp.get("/opera/artists/<aid>")
def get_artist(aid):
    require_roles("Any")
    return ok_object(to_public(get_or_404(store.artists, aid, "Artist")))
