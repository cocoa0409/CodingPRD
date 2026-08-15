"""Client registration and updates (PRD section 3.1)."""
from flask import Blueprint, g

from db import db, new_id
from middleware import ALL_ROLES, require_roles
from response import ok_object
from services.common import (delete_waitlist_entry_for, get_or_404,
                             list_response, stamp_new, touch)
from services.serialize import client_json
from validators import (body, check_allowed, opt_enum, opt_int, opt_list,
                        opt_str, req_bool, req_int, req_str)

bp = Blueprint("clients", __name__)

VULNERABILITY_FACTORS = ["ELDERLY", "DISABLED", "DV_SURVIVOR",
                         "LIMITED_ENGLISH", "HOMELESS", "VETERAN"]

CLIENT_STATUSES = ["ACTIVE", "ARCHIVED"]

FINANCIAL_FIELDS = ("household_size", "annual_gross_income_cents",
                    "annual_countable_income_cents",
                    "receives_means_tested_benefits", "residence_county")


@bp.route("/clients", methods=["POST"])
@require_roles(["IntakeSpecialist"])
def create_client():
    b = body()
    check_allowed(b, ["full_name", "residence_county", "household_size",
                      "annual_gross_income_cents",
                      "annual_countable_income_cents",
                      "receives_means_tested_benefits", "vulnerability_factors"])
    rec = {
        "id": new_id(),
        "full_name": req_str(b, "full_name"),
        "residence_county": req_str(b, "residence_county"),
        "household_size": req_int(b, "household_size", min_v=1),
        "annual_gross_income_cents": req_int(b, "annual_gross_income_cents",
                                             min_v=0),
        "annual_countable_income_cents": req_int(
            b, "annual_countable_income_cents", min_v=0),
        "receives_means_tested_benefits": req_bool(
            b, "receives_means_tested_benefits"),
        "vulnerability_factors": opt_list(b, "vulnerability_factors",
                                          default=[],
                                          enum_values=VULNERABILITY_FACTORS),
        "status": "ACTIVE",
    }
    stamp_new(rec)
    db.clients[rec["id"]] = rec
    return ok_object(client_json(rec), 201)


@bp.route("/clients/<cid>", methods=["GET"])
@require_roles(ALL_ROLES)
def get_client(cid):
    return ok_object(client_json(get_or_404(db.clients, cid)))


@bp.route("/clients", methods=["GET"])
@require_roles(ALL_ROLES)
def list_clients():
    from flask import request
    records = list(db.clients.values())
    county = request.args.get("residence_county")
    if county is not None:
        records = [c for c in records if c["residence_county"] == county]
    status = request.args.get("status")
    if status is not None:
        records = [c for c in records if c["status"] == status]
    return list_response(records, client_json)


@bp.route("/clients/<cid>", methods=["PATCH"])
@require_roles(["IntakeSpecialist"])
def update_client(cid):
    rec = get_or_404(db.clients, cid)
    b = body()
    check_allowed(b, ["full_name", "residence_county", "household_size",
                      "annual_gross_income_cents",
                      "annual_countable_income_cents",
                      "receives_means_tested_benefits", "vulnerability_factors",
                      "status"])
    updates = {}
    if "full_name" in b and b["full_name"] is not None:
        updates["full_name"] = req_str(b, "full_name")
    if "residence_county" in b and b["residence_county"] is not None:
        updates["residence_county"] = req_str(b, "residence_county")
    if "household_size" in b and b["household_size"] is not None:
        updates["household_size"] = req_int(b, "household_size", min_v=1)
    if ("annual_gross_income_cents" in b
            and b["annual_gross_income_cents"] is not None):
        updates["annual_gross_income_cents"] = req_int(
            b, "annual_gross_income_cents", min_v=0)
    if ("annual_countable_income_cents" in b
            and b["annual_countable_income_cents"] is not None):
        updates["annual_countable_income_cents"] = req_int(
            b, "annual_countable_income_cents", min_v=0)
    if ("receives_means_tested_benefits" in b
            and b["receives_means_tested_benefits"] is not None):
        updates["receives_means_tested_benefits"] = req_bool(
            b, "receives_means_tested_benefits")
    if ("vulnerability_factors" in b
            and b["vulnerability_factors"] is not None):
        updates["vulnerability_factors"] = opt_list(
            b, "vulnerability_factors", enum_values=VULNERABILITY_FACTORS)
    if "status" in b and b["status"] is not None:
        updates["status"] = opt_enum(b, "status", CLIENT_STATUSES)

    financial_changed = any(
        f in updates and updates[f] != rec[f] for f in FINANCIAL_FIELDS)

    rec.update(updates)
    touch(rec)

    if financial_changed:
        # Invalidate every pending determination for this client.
        for app in db.applications.values():
            if app["client_id"] != rec["id"]:
                continue
            if app["status"] in ("SCREENED", "ELIGIBLE", "INELIGIBLE"):
                app["status"] = "SUBMITTED"
                touch(app)
            elif app["status"] == "WAITLISTED":
                delete_waitlist_entry_for(app["id"])
                app["status"] = "SUBMITTED"
                touch(app)

    return ok_object(client_json(rec))
