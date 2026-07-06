from flask import request

from db import db
from errors import (
    ERR_CLIENT_NOT_FOUND,
    ERR_INTAKE_NOT_DRAFT,
    ERR_INTAKE_NOT_FOUND,
    ERR_INTAKE_NOT_SCREENED,
    ERR_INVALID_REQUEST,
    ERR_REFERRAL_INVALID_STATE,
    raise_error,
)
from middleware import require_roles
from response import paginate, success
from services import (
    _touch,
    make_intake,
    serialise_intake,
)
from validate import (
    CATEGORY_ENUM,
    URGENCY_ENUM,
    parse_pagination,
    require_body,
    require_bool,
    require_enum,
    require_enum_subset,
    require_int,
)


def _intake_or_404(iid: str):
    i = db.intakes.get(iid)
    if not i:
        raise_error(ERR_INTAKE_NOT_FOUND, f"intake {iid} not found")
    return i


def register(app):
    @app.post("/clients/<cid>/intakes")
    @require_roles("Caseworker", "PlatformAdmin")
    def create_intake(cid):
        if cid not in db.clients:
            raise_error(ERR_CLIENT_NOT_FOUND, f"client {cid} not found")
        body = require_body(request.get_json(silent=True))
        needs = require_enum_subset(body, "presenting_needs", CATEGORY_ENUM, non_empty=True)
        urgency = require_enum(body, "urgency", URGENCY_ENUM)
        hh = require_int(body, "household_size")
        if hh < 1:
            raise_error(ERR_INVALID_REQUEST, "household_size must be >= 1")
        disability = require_bool(body, "disability_flag")
        entity = make_intake(cid, needs, urgency, hh, disability)
        return success(serialise_intake(entity), 201)

    @app.get("/intakes/<iid>")
    @require_roles("Caseworker", "PlatformAdmin")
    def get_intake(iid):
        return success(serialise_intake(_intake_or_404(iid)), 200)

    @app.get("/intakes")
    @require_roles("Caseworker", "PlatformAdmin")
    def list_intakes():
        limit, offset = parse_pagination(request.args)
        client_id = request.args.get("client_id")
        status = request.args.get("status")
        items = list(db.intakes.values())
        if client_id is not None:
            items = [i for i in items if i["client_id"] == client_id]
        if status is not None:
            items = [i for i in items if i["status"] == status]
        items.sort(key=lambda x: x["created_at"])
        window, pg = paginate(items, limit, offset)
        return success([serialise_intake(i) for i in window], 200, "array", pg)

    @app.post("/intakes/<iid>/screen")
    @require_roles("Caseworker", "PlatformAdmin")
    def screen_intake(iid):
        i = _intake_or_404(iid)
        if i["status"] != "DRAFT":
            raise_error(ERR_INTAKE_NOT_DRAFT, "intake is not in DRAFT")
        i["status"] = "SCREENED"
        _touch(i)
        return success(serialise_intake(i), 200)

    @app.post("/intakes/<iid>/reopen")
    @require_roles("Caseworker", "PlatformAdmin")
    def reopen_intake(iid):
        i = _intake_or_404(iid)
        if i["status"] != "SCREENED":
            raise_error(ERR_INTAKE_NOT_SCREENED, "intake is not in SCREENED")
        # Precondition: no Referral in {ACCEPTED, SERVICE_IN_PROGRESS} for this intake.
        for r in db.referrals.values():
            if r["intake_id"] == iid and r["status"] in ("ACCEPTED", "SERVICE_IN_PROGRESS"):
                raise_error(
                    ERR_REFERRAL_INVALID_STATE,
                    "cannot reopen: a referral is ACCEPTED or SERVICE_IN_PROGRESS",
                )
        i["status"] = "DRAFT"
        _touch(i)
        return success(serialise_intake(i), 200)
