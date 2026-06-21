"""ContainerType endpoints (PRD section 3.1)."""
from flask import Blueprint, request

from db import db
from errors import err
from helpers import get_container_type, paginate
from middleware import require_auth, require_role
from response import success
from serialize import container_type as ser
import validate

bp = Blueprint("container_types", __name__)

SIZE_CODES = {"YD10", "YD20", "YD30", "YD40"}
READ_ROLES = ["YardAdmin", "Dispatcher", "Contractor", "BillingClerk",
              "ScaleOperator", "PermitOfficer"]


@bp.post("/container-types")
def create_container_type():
    _, role = require_auth()
    require_role(role, ["YardAdmin"])
    body = validate.get_json_body()
    validate.require_fields(body, [
        "size_code", "base_rate_cents", "included_days",
        "overage_day_cents", "included_tonnage_lbs", "overage_rate_cents_per_lb",
    ])
    size_code = validate.require_enum(body, "size_code", SIZE_CODES)
    base_rate_cents = validate.require_non_negative_int(body, "base_rate_cents")
    included_days = validate.require_int_at_least(body, "included_days", 1)
    overage_day_cents = validate.require_non_negative_int(body, "overage_day_cents")
    included_tonnage_lbs = validate.require_non_negative_int(body, "included_tonnage_lbs")
    overage_rate_cents_per_lb = validate.require_non_negative_int(body, "overage_rate_cents_per_lb")

    # size_code unique across active types (priority 15).
    for t in db.container_types.values():
        if t["active"] and t["size_code"] == size_code:
            raise err("ERR_DUPLICATE_RESOURCE", "Active container type with this size_code exists")

    rec = db.insert_with_common(db.container_types, {
        "size_code": size_code,
        "base_rate_cents": base_rate_cents,
        "included_days": included_days,
        "overage_day_cents": overage_day_cents,
        "included_tonnage_lbs": included_tonnage_lbs,
        "overage_rate_cents_per_lb": overage_rate_cents_per_lb,
        "active": True,
    })
    return success(ser(rec), status=201)


@bp.get("/container-types")
def list_container_types():
    _, role = require_auth()
    require_role(role, READ_ROLES)
    limit, offset = validate.get_pagination()
    active = request.args.get("active")
    records = list(db.container_types.values())
    if active is not None:
        want = active.lower() == "true"
        records = [r for r in records if r["active"] == want]
    return paginate(records, ser, limit, offset)


@bp.get("/container-types/<type_id>")
def get_container_type_ep(type_id):
    _, role = require_auth()
    require_role(role, READ_ROLES)
    rec = get_container_type(type_id)
    return success(ser(rec), status=200)


@bp.post("/container-types/<type_id>/retire")
def retire_container_type(type_id):
    _, role = require_auth()
    require_role(role, ["YardAdmin"])
    rec = get_container_type(type_id)
    rec["active"] = False
    db.touch(rec)
    return success(ser(rec), status=200)
