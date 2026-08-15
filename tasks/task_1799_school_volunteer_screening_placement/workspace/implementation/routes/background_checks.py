"""Background check endpoints."""

from flask import request

import db
import clock
import services
from errors import (
    APIError, not_found, invalid_request,
    ERR_VOLUNTEER_INVALID_STATE, ERR_CHECK_INVALID_STATE,
    ERR_CHECK_ALREADY_PENDING, ERR_STALE_VERSION,
)
from middleware import require_roles
from pagination import parse_pagination, paginate
from response import success_object, success_list

LEVELS = ("BASIC", "ENHANCED")
FINDINGS = ("NONE", "MINOR", "DISQUALIFYING")


def register(app):
    @app.route("/background-checks", methods=["POST"])
    def create_check():
        require_roles("DistrictCoordinator")
        body = request.get_json(silent=True) or {}

        # p3 existence (body FK in payload field order): volunteer_id
        vid = body.get("volunteer_id")
        if vid is not None:
            vol = db.volunteers.get(vid)
            if vol is None:
                raise not_found("volunteer_id does not resolve")
        else:
            vol = None

        # p4 state: volunteer must be in {APPLIED, ACTIVE, RESCREEN_REQUIRED}
        if vol is not None and vol["status"] not in ("APPLIED", "ACTIVE", "RESCREEN_REQUIRED"):
            raise APIError(ERR_VOLUNTEER_INVALID_STATE,
                           "check creation requires volunteer in {APPLIED, ACTIVE, RESCREEN_REQUIRED}", 409)

        # p8: no PENDING check for volunteer
        if vol is not None:
            for c in db.background_checks.values():
                if c["volunteer_id"] == vol["id"] and c["status"] == "PENDING":
                    raise APIError(ERR_CHECK_ALREADY_PENDING,
                                   "A BackgroundCheck in PENDING already exists for the volunteer", 409)

        # p9 OCC: expected_volunteer_version
        if vol is not None and "expected_volunteer_version" in body and body["expected_volunteer_version"] is not None:
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
        level = body.get("level")
        if level not in LEVELS:
            raise invalid_request("level must be BASIC or ENHANCED")
        if "expected_volunteer_version" not in body or body.get("expected_volunteer_version") is None:
            raise invalid_request("expected_volunteer_version is required")

        check = {
            "id": db.new_id(),
            "created_at": clock.now_iso(),
            "updated_at": clock.now_iso(),
            "version": 1,
            "volunteer_id": vid,
            "level": level,
            "status": "PENDING",
            "findings": None,
            "decided_at": None,
            "expires_at": None,
        }
        db.background_checks[check["id"]] = check

        # first check: APPLIED -> UNDER_SCREENING; always bump volunteer version
        if vol["status"] == "APPLIED":
            vol["status"] = "UNDER_SCREENING"
        services.touch(vol)

        return success_object(check, 201)

    @app.route("/background-checks", methods=["GET"])
    def list_checks():
        require_roles("DistrictCoordinator")
        limit, offset = parse_pagination()
        items = list(db.background_checks.values())
        vid = request.args.get("volunteer_id")
        status = request.args.get("status")
        if vid is not None:
            items = [c for c in items if c["volunteer_id"] == vid]
        if status is not None:
            items = [c for c in items if c["status"] == status]
        page, total = paginate(items, limit, offset)
        return success_list(page, limit, offset, total)

    @app.route("/background-checks/<cid>", methods=["GET"])
    def get_check(cid):
        require_roles("DistrictCoordinator")
        check = db.background_checks.get(cid)
        if check is None:
            raise not_found()
        return success_object(check, 200)

    @app.route("/background-checks/<cid>/adjudicate", methods=["POST"])
    def adjudicate(cid):
        require_roles("DistrictCoordinator")
        check = db.background_checks.get(cid)
        if check is None:
            raise not_found()

        # p4 state
        if check["status"] != "PENDING":
            raise APIError(ERR_CHECK_INVALID_STATE,
                           "Adjudication attempted on a BackgroundCheck not in PENDING", 409)

        # p10 shape
        body = request.get_json(silent=True) or {}
        findings = body.get("findings")
        if findings not in FINDINGS:
            raise invalid_request("findings must be NONE, MINOR, or DISQUALIFYING")

        services.adjudicate_check(check, findings)
        return success_object(check, 200)
