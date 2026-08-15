"""CardHolder endpoints (PRD 3.1, 3.2)."""

from flask import Blueprint, g, request

from db import store
from errors import (
    err, ERR_VALIDATION, ERR_NOT_FOUND, ERR_NOT_RESOURCE_OWNER,
    ERR_DUPLICATE_NATURAL_KEY, ERR_INVALID_STATE_TRANSITION, ERR_FRAUD_HOLD,
)
from middleware import (
    authenticate, require_roles, get_body, v_str, v_enum, find_or_404, pub,
    paginate, HOLDER_TYPES, HOUSING_STATUSES,
)
from response import success
from services.core import new_row, touch
from services.cascades import (
    suspension_cascade, unfreeze_holder_suspended_accounts,
    offboard_holder_cascade,
)

bp = Blueprint("holders", __name__)

HOLDER_STATUSES = {"ACTIVE", "SUSPENDED", "WITHDRAWN", "GRADUATED"}


@bp.route("/api/card-holders", methods=["POST"])
def create_holder():
    authenticate()
    require_roles("CardOfficeAdmin")
    body = get_body()
    university_id = v_str(body, "university_id")
    full_name = v_str(body, "full_name")
    email = v_str(body, "email")
    holder_type = v_enum(body, "holder_type", HOLDER_TYPES)
    housing_status = v_enum(body, "housing_status", HOUSING_STATUSES)
    for h in store.holders.values():
        if h["university_id"] == university_id:
            err(ERR_DUPLICATE_NATURAL_KEY, "university_id already exists")
    holder = new_row()
    holder.update({
        "university_id": university_id,
        "full_name": full_name,
        "email": email,
        "holder_type": holder_type,
        "housing_status": housing_status,
        "status": "ACTIVE",
        "fraud_strike_count": 0,
        "fraud_flag": False,
    })
    store.holders[holder["id"]] = holder
    return success(pub(holder), 201)


@bp.route("/api/card-holders", methods=["GET"])
def list_holders():
    authenticate()
    require_roles("PlatformAdmin", "CardOfficeAdmin", "DiningServicesManager",
                  "BursarOffice", "FraudAnalyst", "SecurityOfficer")
    rows = list(store.holders.values())
    holder_type = request.args.get("holder_type")
    status = request.args.get("status")
    housing = request.args.get("housing_status")
    uid = request.args.get("university_id")
    if holder_type is not None:
        rows = [h for h in rows if h["holder_type"] == holder_type]
    if status is not None:
        rows = [h for h in rows if h["status"] == status]
    if housing is not None:
        rows = [h for h in rows if h["housing_status"] == housing]
    if uid is not None:
        rows = [h for h in rows if h["university_id"] == uid]
    data, page = paginate(rows)
    return success(data, 200, page)


@bp.route("/api/card-holders/<hid>", methods=["GET"])
def get_holder(hid):
    authenticate()
    require_roles("PlatformAdmin", "CardOfficeAdmin", "DiningServicesManager",
                  "BursarOffice", "FraudAnalyst", "SecurityOfficer", "CardHolder")
    holder = store.holders.get(hid)
    if holder is not None and g.role == "CardHolder" and g.user_id != holder["id"]:
        err(ERR_NOT_RESOURCE_OWNER, "CardHolder may read only its own record")
    if holder is None:
        err(ERR_NOT_FOUND, "Card holder not found")
    return success(pub(holder), 200)


def _get_holder_path(hid):
    return find_or_404(store.holders, hid)


@bp.route("/api/card-holders/<hid>/suspend", methods=["POST"])
def suspend_holder(hid):
    authenticate()
    require_roles("CardOfficeAdmin", "FraudAnalyst")
    holder = _get_holder_path(hid)
    if holder["status"] != "ACTIVE":
        err(ERR_INVALID_STATE_TRANSITION, "Only an ACTIVE holder can be suspended")
    holder["status"] = "SUSPENDED"
    suspension_cascade(holder)
    touch(holder)
    return success(pub(holder), 200)


@bp.route("/api/card-holders/<hid>/reinstate", methods=["POST"])
def reinstate_holder(hid):
    authenticate()
    require_roles("CardOfficeAdmin")
    holder = _get_holder_path(hid)
    if holder["status"] not in ("SUSPENDED", "WITHDRAWN"):
        err(ERR_INVALID_STATE_TRANSITION,
            "Only a SUSPENDED or WITHDRAWN holder can be reinstated")
    if holder["status"] == "SUSPENDED" and holder["fraud_flag"]:
        err(ERR_FRAUD_HOLD, "fraud_flag is set; fraud review must run first")
    was_suspended = holder["status"] == "SUSPENDED"
    holder["status"] = "ACTIVE"
    if was_suspended:
        unfreeze_holder_suspended_accounts(holder)
    touch(holder)
    return success(pub(holder), 200)


@bp.route("/api/card-holders/<hid>/withdraw", methods=["POST"])
def withdraw_holder(hid):
    authenticate()
    require_roles("CardOfficeAdmin")
    holder = _get_holder_path(hid)
    if holder["status"] != "ACTIVE":
        err(ERR_INVALID_STATE_TRANSITION, "Only an ACTIVE holder can be withdrawn")
    offboard_holder_cascade(holder)
    holder["status"] = "WITHDRAWN"
    touch(holder)
    return success(pub(holder), 200)


@bp.route("/api/card-holders/<hid>/graduate", methods=["POST"])
def graduate_holder(hid):
    authenticate()
    require_roles("CardOfficeAdmin")
    holder = _get_holder_path(hid)
    if holder["status"] != "ACTIVE":
        err(ERR_INVALID_STATE_TRANSITION, "Only an ACTIVE holder can be graduated")
    offboard_holder_cascade(holder)
    holder["status"] = "GRADUATED"
    touch(holder)
    return success(pub(holder), 200)


@bp.route("/api/card-holders/<hid>/fraud-review", methods=["POST"])
def fraud_review(hid):
    authenticate()
    require_roles("FraudAnalyst")
    holder = _get_holder_path(hid)
    holder["fraud_strike_count"] = 0
    holder["fraud_flag"] = False
    unfreeze_holder_suspended_accounts(holder)
    touch(holder)
    return success(pub(holder), 200)
