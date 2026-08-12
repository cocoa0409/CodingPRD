"""Routes: logical clock, donors, categories."""
from flask import Blueprint, request

import db
from errors import ApiError, err_invalid_request
from response import success_obj, success_list
from services import serialize_donor
from util import (
    authenticate,
    require_role,
    get_body,
    req_str,
    opt_str,
    req_enum,
    opt_enum,
    req_int,
    opt_int,
    req_num,
    opt_num,
    req_bool,
    opt_bool,
    parse_dt,
    lookup,
    paginate,
    serialize,
)

bp = Blueprint("core", __name__)

DONOR_TYPES = {"INDIVIDUAL", "BUSINESS", "CONTRACTOR"}
PRICING_MODELS = {"PER_UNIT", "PER_SQFT", "PER_LINEAR_FT", "FLAT"}
DISPOSITIONS = {"DONATE", "RECYCLE", "DISPOSE"}
CATEGORY_STATES = {"ACCEPTING", "PAUSED", "RETIRED"}

# Category acceptance_status transitions per state_machines.Category
CATEGORY_TRANSITIONS = {
    ("ACCEPTING", "PAUSED"),
    ("PAUSED", "ACCEPTING"),
    ("ACCEPTING", "RETIRED"),
    ("PAUSED", "RETIRED"),
}


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------


@bp.post("/reuse/_clock/set_current_utc")
def set_clock():
    data = get_body()
    raw = req_str(data, "to_iso8601")
    dt = parse_dt(raw, "to_iso8601")
    ctx = authenticate()
    require_role(ctx, ["WarehouseAdmin"])
    db.CLOCK.set(dt, raw)
    return success_obj({"current_utc": raw})


# ---------------------------------------------------------------------------
# Donors
# ---------------------------------------------------------------------------


@bp.post("/reuse/donors")
def create_donor():
    data = get_body()
    full_name = req_str(data, "full_name")
    donor_type = req_enum(data, "donor_type", DONOR_TYPES)
    email = req_str(data, "email")
    address_text = req_str(data, "address_text")
    phone = opt_str(data, "phone", "")
    ctx = authenticate()
    require_role(ctx, ["IntakeStaff", "WarehouseAdmin"])
    donor = {
        **db.base_fields(),
        "full_name": full_name,
        "donor_type": donor_type,
        "email": email,
        "phone": phone,
        "address_text": address_text,
        "status": "ACTIVE",
        "trailing_receipt_value_cents": 0,
        "recognition_tier": "NONE",
    }
    db.donors[donor["id"]] = donor
    return success_obj(serialize_donor(donor), 201)


@bp.get("/reuse/donors")
def list_donors():
    ctx = authenticate()
    require_role(ctx, ["IntakeStaff", "WarehouseAdmin", "StoreManager", "CrewCoordinator"])
    records = list(db.donors.values())
    status = request.args.get("status")
    tier = request.args.get("recognition_tier")
    if status is not None:
        records = [d for d in records if d["status"] == status]
    if tier is not None:
        records = [d for d in records if d["recognition_tier"] == tier]
    page, meta = paginate(records)
    return success_list([serialize_donor(d) for d in page], meta)


@bp.get("/reuse/donors/<donorId>")
def get_donor(donorId):
    ctx = authenticate()
    require_role(ctx, ["IntakeStaff", "WarehouseAdmin", "Donor"])
    # Ownership (priority 3) is checked before path existence (priority 4):
    # a Donor may only ever touch their own record.
    if ctx.role == "Donor" and donorId != ctx.user_id:
        from errors import err_not_owner

        raise err_not_owner("Donor may only read own record")
    donor = lookup(db.donors, "donor", donorId)
    return success_obj(serialize_donor(donor))


@bp.patch("/reuse/donors/<donorId>")
def patch_donor(donorId):
    data = get_body()
    status = opt_enum(data, "status", {"ACTIVE", "INACTIVE"})
    full_name = opt_str(data, "full_name")
    email = opt_str(data, "email")
    phone = opt_str(data, "phone")
    address_text = opt_str(data, "address_text")
    ctx = authenticate()
    require_role(ctx, ["IntakeStaff", "WarehouseAdmin"])
    donor = lookup(db.donors, "donor", donorId)
    if status is not None and status != donor["status"]:
        if donor["status"] == "ACTIVE" and status == "INACTIVE":
            open_states = {"OFFERED", "UNDER_REVIEW", "NEEDS_INFO", "ACCEPTED"}
            for offer in db.offers.values():
                if offer["donor_id"] == donor["id"] and offer["status"] in open_states:
                    raise ApiError(
                        "ERR_INVALID_OFFER_STATE",
                        409,
                        "Donor has offers in an open pipeline state",
                    )
            donor["status"] = "INACTIVE"
        elif donor["status"] == "INACTIVE" and status == "ACTIVE":
            donor["status"] = "ACTIVE"
    if full_name is not None:
        donor["full_name"] = full_name
    if email is not None:
        donor["email"] = email
    if phone is not None:
        donor["phone"] = phone
    if address_text is not None:
        donor["address_text"] = address_text
    db.touch(donor)
    return success_obj(serialize_donor(donor))


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------


def _validate_category_payload(data):
    return {
        "code": req_str(data, "code"),
        "display_name": req_str(data, "display_name"),
        "pricing_model": req_enum(data, "pricing_model", PRICING_MODELS),
        "base_rate_cents": req_int(data, "base_rate_cents", min_value=0),
        "hazmat_risk_flag": req_bool(data, "hazmat_risk_flag"),
        "requires_appraisal_review": opt_bool(data, "requires_appraisal_review", False),
        "markdown_after_days": req_int(data, "markdown_after_days", min_value=0),
        "markdown_step_pct": req_num(data, "markdown_step_pct", ge=0),
        "markdown_interval_days": req_int(data, "markdown_interval_days", min_value=0),
        "max_markdown_steps": req_int(data, "max_markdown_steps", min_value=0),
        "floor_price_pct": req_num(data, "floor_price_pct", ge=0),
        "divertible": opt_bool(data, "divertible", True),
        "target_turn_days": req_int(data, "target_turn_days", min_value=0),
        "slow_item_disposition": opt_enum(
            data, "slow_item_disposition", DISPOSITIONS, "DONATE"
        ),
    }


@bp.post("/reuse/categories")
def create_category():
    data = get_body()
    vals = _validate_category_payload(data)
    ctx = authenticate()
    require_role(ctx, ["StoreManager", "WarehouseAdmin"])
    for c in db.categories.values():
        if c["code"] == vals["code"]:
            raise ApiError("ERR_DUPLICATE_CODE", 409, "Category code already exists")
    category = {**db.base_fields(), **vals, "acceptance_status": "ACCEPTING"}
    db.categories[category["id"]] = category
    return success_obj(serialize(category), 201)


@bp.get("/reuse/categories")
def list_categories():
    ctx = authenticate()
    require_role(
        ctx,
        ["StoreManager", "WarehouseAdmin", "IntakeStaff", "Cashier", "Contractor", "CrewCoordinator"],
    )
    records = list(db.categories.values())
    status = request.args.get("acceptance_status")
    if status is not None:
        records = [c for c in records if c["acceptance_status"] == status]
    page, meta = paginate(records)
    return success_list([serialize(c) for c in page], meta)


@bp.get("/reuse/categories/<categoryId>")
def get_category(categoryId):
    ctx = authenticate()
    require_role(
        ctx,
        ["StoreManager", "WarehouseAdmin", "IntakeStaff", "Cashier", "Contractor", "CrewCoordinator"],
    )
    category = lookup(db.categories, "category", categoryId)
    return success_obj(serialize(category))


@bp.patch("/reuse/categories/<categoryId>")
def patch_category(categoryId):
    data = get_body()
    new_status = opt_enum(data, "acceptance_status", CATEGORY_STATES)
    base_rate_cents = opt_int(data, "base_rate_cents", min_value=0)
    markdown_after_days = opt_int(data, "markdown_after_days", min_value=0)
    markdown_step_pct = opt_num(data, "markdown_step_pct", ge=0)
    markdown_interval_days = opt_int(data, "markdown_interval_days", min_value=0)
    max_markdown_steps = opt_int(data, "max_markdown_steps", min_value=0)
    floor_price_pct = opt_num(data, "floor_price_pct", ge=0)
    target_turn_days = opt_int(data, "target_turn_days", min_value=0)
    slow_item_disposition = opt_enum(data, "slow_item_disposition", DISPOSITIONS)
    hazmat_risk_flag = opt_bool(data, "hazmat_risk_flag")
    ctx = authenticate()
    require_role(ctx, ["StoreManager", "WarehouseAdmin"])
    category = lookup(db.categories, "category", categoryId)
    if new_status is not None and new_status != category["acceptance_status"]:
        if (category["acceptance_status"], new_status) not in CATEGORY_TRANSITIONS:
            raise err_invalid_request(
                "Invalid acceptance_status transition %s -> %s"
                % (category["acceptance_status"], new_status)
            )
        category["acceptance_status"] = new_status
    for field, value in (
        ("base_rate_cents", base_rate_cents),
        ("markdown_after_days", markdown_after_days),
        ("markdown_step_pct", markdown_step_pct),
        ("markdown_interval_days", markdown_interval_days),
        ("max_markdown_steps", max_markdown_steps),
        ("floor_price_pct", floor_price_pct),
        ("target_turn_days", target_turn_days),
        ("slow_item_disposition", slow_item_disposition),
        ("hazmat_risk_flag", hazmat_risk_flag),
    ):
        if value is not None:
            category[field] = value
    db.touch(category)
    return success_obj(serialize(category))
