"""Waiver endpoints (PRD §3.1). POST /farm/waivers is the public kiosk."""

from flask import Blueprint, request

import db
import domain
from errors import raise_err, ERR_INVALID_STATE, ERR_NOT_FOUND
from helpers import (
    check_no_undeclared,
    get_body,
    ok_object,
    paginate,
    req_str,
    req_str_list,
    require,
)

bp = Blueprint("waivers", __name__)

FM = ("FarmManager",)
READERS = ("FarmManager", "GateStaff")


@bp.post("/farm/waivers")
def create_waiver():
    # The one endpoint exempt from the authentication gate; authorization
    # still applies: any presented role other than Anonymous is forbidden.
    require(("Anonymous",), public_endpoint=True)
    body = get_body()
    check_no_undeclared(
        body, {"season_id", "signer_name", "signer_email", "party_member_names"}
    )
    season_id = req_str(body, "season_id")
    signer_name = req_str(body, "signer_name")
    signer_email = req_str(body, "signer_email")
    party_member_names = req_str_list(body, "party_member_names")
    season = db.seasons.get(season_id)
    if season is None:
        raise_err(ERR_NOT_FOUND, "season_id does not resolve")
    waiver = domain.new_entity()
    waiver.update(
        {
            "season_id": season_id,
            "signer_name": signer_name,
            "signer_email": signer_email,
            "party_member_names": list(party_member_names),
            "waiver_version_signed": season["current_waiver_version"],
            "status": "SIGNED",
        }
    )
    db.waivers[waiver["id"]] = waiver
    return ok_object(domain.serialize_waiver(waiver), 201)


@bp.get("/farm/waivers/<wid>")
def get_waiver(wid):
    require(READERS)
    waiver = db.waivers.get(wid)
    if waiver is None:
        raise_err(ERR_NOT_FOUND, "Waiver not found")
    return ok_object(domain.serialize_waiver(waiver))


@bp.get("/farm/waivers")
def list_waivers():
    require(READERS)
    items = list(db.waivers.values())
    season_id = request.args.get("season_id")
    if season_id is not None:
        items = [w for w in items if w["season_id"] == season_id]
    signer_email = request.args.get("signer_email")
    if signer_email is not None:
        items = [w for w in items if w["signer_email"] == signer_email]
    return paginate(items, domain.serialize_waiver)


@bp.post("/farm/waivers/<wid>/void")
def void_waiver(wid):
    require(FM)
    waiver = db.waivers.get(wid)
    if waiver is None:
        raise_err(ERR_NOT_FOUND, "Waiver not found")
    if waiver["status"] != "SIGNED":
        raise_err(ERR_INVALID_STATE, "Only a SIGNED waiver can be voided")
    waiver["status"] = "VOIDED"
    domain.touch(waiver)
    return ok_object(domain.serialize_waiver(waiver))
