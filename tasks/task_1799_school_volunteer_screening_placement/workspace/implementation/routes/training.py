"""Training module and training record endpoints."""

from flask import request

import db
import clock
import services
from errors import APIError, not_found, invalid_request, ERR_MODULE_CODE_TAKEN
from middleware import require_roles
from pagination import parse_pagination, paginate
from response import success_object, success_list

CONTACT_TYPES = ("SUPERVISED", "UNSUPERVISED")


def register(app):
    @app.route("/training-modules", methods=["POST"])
    def create_module():
        require_roles("DistrictCoordinator")
        body = request.get_json(silent=True) or {}

        # p8 uniqueness
        code = body.get("module_code")
        if code is not None:
            for m in db.training_modules.values():
                if m["module_code"] == code:
                    raise APIError(ERR_MODULE_CODE_TAKEN, "module_code already in use", 409)

        # p10 shape
        title = body.get("title")
        rct = body.get("required_contact_types")
        validity_days = body.get("validity_days", None)
        if not code or not isinstance(code, str):
            raise invalid_request("module_code is required")
        if not title or not isinstance(title, str):
            raise invalid_request("title is required")
        if not isinstance(rct, list) or len(rct) == 0:
            raise invalid_request("required_contact_types must be a non-empty array")
        for v in rct:
            if v not in CONTACT_TYPES:
                raise invalid_request("required_contact_types entries must be SUPERVISED or UNSUPERVISED")
        if validity_days is not None:
            if isinstance(validity_days, bool) or not isinstance(validity_days, int) or validity_days < 1:
                raise invalid_request("validity_days must be null or integer >= 1")

        module = {
            "id": db.new_id(),
            "created_at": clock.now_iso(),
            "module_code": code,
            "title": title,
            "required_contact_types": list(rct),
            "validity_days": validity_days,
        }
        db.training_modules[module["id"]] = module
        return success_object(module, 201)

    @app.route("/training-modules", methods=["GET"])
    def list_modules():
        require_roles("DistrictCoordinator", "CampusAdmin", "Volunteer")
        limit, offset = parse_pagination()
        items = list(db.training_modules.values())
        page, total = paginate(items, limit, offset)
        return success_list(page, limit, offset, total)

    @app.route("/training-records", methods=["POST"])
    def create_record():
        require_roles("DistrictCoordinator", "CampusAdmin")
        body = request.get_json(silent=True) or {}

        # p3 existence in payload field order: volunteer_id, module_id
        vid = body.get("volunteer_id")
        if vid is not None and vid not in db.volunteers:
            raise not_found("volunteer_id does not resolve")
        mid = body.get("module_id")
        if mid is not None and mid not in db.training_modules:
            raise not_found("module_id does not resolve")

        # p10 shape
        if vid is None:
            raise invalid_request("volunteer_id is required")
        if mid is None:
            raise invalid_request("module_id is required")
        completed_at_raw = body.get("completed_at")
        if not completed_at_raw:
            raise invalid_request("completed_at is required")
        try:
            completed_dt = clock.parse_iso(completed_at_raw)
        except (ValueError, TypeError):
            raise invalid_request("completed_at must be a valid ISO8601 datetime")

        module = db.training_modules[mid]
        vd = module["validity_days"]
        if vd is None:
            expires_at = None
        else:
            from datetime import timedelta
            expires_at = clock.to_iso(completed_dt + timedelta(days=vd))

        record = {
            "id": db.new_id(),
            "created_at": clock.now_iso(),
            "volunteer_id": vid,
            "module_id": mid,
            "completed_at": clock.to_iso(completed_dt),
            "expires_at": expires_at,
        }
        db.training_records[record["id"]] = record

        # auto-activate CLEARANCE_GRANTED -> ACTIVE when compliance becomes complete
        vol = db.volunteers[vid]
        if vol["status"] == "CLEARANCE_GRANTED" and services.training_compliance(vol):
            vol["status"] = "ACTIVE"
            services.touch(vol)

        return success_object(record, 201)

    @app.route("/training-records", methods=["GET"])
    def list_records():
        require_roles("DistrictCoordinator", "CampusAdmin")
        limit, offset = parse_pagination()
        items = list(db.training_records.values())
        vid = request.args.get("volunteer_id")
        mid = request.args.get("module_id")
        if vid is not None:
            items = [r for r in items if r["volunteer_id"] == vid]
        if mid is not None:
            items = [r for r in items if r["module_id"] == mid]
        page, total = paginate(items, limit, offset)
        return success_list(page, limit, offset, total)

    @app.route("/training-records/<rid>", methods=["GET"])
    def get_record(rid):
        require_roles("DistrictCoordinator", "CampusAdmin")
        record = db.training_records.get(rid)
        if record is None:
            raise not_found()
        return success_object(record, 200)
