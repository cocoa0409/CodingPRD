"""Locator endpoints."""

from flask import Blueprint, request

import clock
from db import db
from errors import err_invalid_state, err_not_found
from middleware import require_roles
from serializers import locator_out
from util import (get_pagination, new_id, paginate, parse_body,
                  require_string, success_envelope)

bp = Blueprint("locators", __name__)

ALL_ROLES = ("IntakeCoordinator", "DamageInvestigator", "ClaimsAdjuster",
             "RecoveryManager", "Excavator", "Locator")


@bp.route("/damage-recovery/locators", methods=["POST"])
def create_locator():
    require_roles("RecoveryManager")
    body = parse_body(required_fields=["company_name", "contact_email", "contract_region"])
    now = clock.get_current_utc()
    lid = new_id()
    loc = {
        "id": lid,
        "company_name": require_string(body["company_name"], "company_name"),
        "contact_email": require_string(body["contact_email"], "contact_email"),
        "contract_region": require_string(body["contract_region"], "contract_region"),
        "contract_status": "ACTIVE",
        "performance_score_bp": 10000,
        "total_responses": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_insert_seq(),
    }
    db.locators[lid] = loc
    return success_envelope(locator_out(loc), "object", 201)


@bp.route("/damage-recovery/locators", methods=["GET"])
def list_locators():
    require_roles(*ALL_ROLES)
    limit, offset = get_pagination()
    items = list(db.locators.values())
    status = request.args.get("contract_status")
    if status is not None:
        items = [e for e in items if e["contract_status"] == status]
    items.sort(key=lambda e: (e["created_at"], e["_seq"]))
    page, meta = paginate(items, limit, offset)
    return success_envelope([locator_out(e) for e in page], "array", 200, meta)


@bp.route("/damage-recovery/locators/<lid>/suspend", methods=["POST"])
def suspend_locator(lid):
    require_roles("RecoveryManager")
    loc = db.locators.get(lid)
    if loc is None:
        raise err_not_found("locator not found")
    if loc["contract_status"] != "ACTIVE":
        raise err_invalid_state("locator contract is not ACTIVE")
    loc["contract_status"] = "SUSPENDED"
    loc["updated_at"] = clock.get_current_utc()
    loc["version"] += 1
    return success_envelope(locator_out(loc), "object", 200)
