"""Recognition award endpoints."""

from flask import request

import db
import clock
import services
from errors import (
    APIError, not_found, invalid_request,
    ERR_VOLUNTEER_INVALID_STATE, ERR_DUPLICATE_AWARD, ERR_STALE_VERSION,
)
from middleware import require_roles
from pagination import parse_pagination, paginate
from response import success_object, success_list

TIERS = ("BRONZE", "SILVER", "GOLD")


def register(app):
    @app.route("/recognition-awards", methods=["POST"])
    def create_award():
        require_roles("DistrictCoordinator")
        body = request.get_json(silent=True) or {}

        # p3 existence
        vid = body.get("volunteer_id")
        if vid is not None and vid not in db.volunteers:
            raise not_found("volunteer_id does not resolve")

        # p4 state: volunteer not in {DENIED, REMOVED}
        if vid is not None:
            vol = db.volunteers[vid]
            if vol["status"] in ("DENIED", "REMOVED"):
                raise APIError(ERR_VOLUNTEER_INVALID_STATE,
                               "award grant requires volunteer not in {DENIED, REMOVED}", 409)

        # p8: no existing award of same tier for volunteer
        tier = body.get("tier")
        if vid is not None and tier is not None:
            for a in db.recognition_awards.values():
                if a["volunteer_id"] == vid and a["tier"] == tier:
                    raise APIError(ERR_DUPLICATE_AWARD,
                                   "A RecognitionAward of the same tier already exists for the volunteer", 409)

        # p9 OCC
        if vid is not None and "expected_volunteer_version" in body and body["expected_volunteer_version"] is not None:
            vol = db.volunteers[vid]
            evv = body["expected_volunteer_version"]
            try:
                evv_int = int(evv)
            except (TypeError, ValueError):
                evv_int = None
            if evv_int is not None and evv_int != vol["version"]:
                raise APIError(ERR_STALE_VERSION,
                               "expected_volunteer_version does not match Volunteer.version", 412)

        # p10 shape
        if vid is None:
            raise invalid_request("volunteer_id is required")
        if tier not in TIERS:
            raise invalid_request("tier must be BRONZE, SILVER, or GOLD")
        if "expected_volunteer_version" not in body or body.get("expected_volunteer_version") is None:
            raise invalid_request("expected_volunteer_version is required")
        note = body.get("note", "")
        if not isinstance(note, str):
            raise invalid_request("note must be a string")

        award = {
            "id": db.new_id(),
            "created_at": clock.now_iso(),
            "volunteer_id": vid,
            "tier": tier,
            "source": "MANUAL",
            "note": note,
        }
        db.recognition_awards[award["id"]] = award

        # award attaches to the volunteer aggregate: bump volunteer version
        vol = db.volunteers[vid]
        services.touch(vol)

        return success_object(award, 201)

    @app.route("/recognition-awards", methods=["GET"])
    def list_awards():
        require_roles("DistrictCoordinator", "CampusAdmin")
        limit, offset = parse_pagination()
        items = list(db.recognition_awards.values())
        vid = request.args.get("volunteer_id")
        tier = request.args.get("tier")
        if vid is not None:
            items = [a for a in items if a["volunteer_id"] == vid]
        if tier is not None:
            items = [a for a in items if a["tier"] == tier]
        page, total = paginate(items, limit, offset)
        return success_list(page, limit, offset, total)

    @app.route("/recognition-awards/<aid>", methods=["GET"])
    def get_award(aid):
        require_roles("DistrictCoordinator", "CampusAdmin")
        award = db.recognition_awards.get(aid)
        if award is None:
            raise not_found()
        return success_object(award, 200)
