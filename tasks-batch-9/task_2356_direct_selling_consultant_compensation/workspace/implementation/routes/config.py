"""Logical clock, compensation plans, tax jurisdictions and products."""

from flask import Blueprint

from common import (
    bad,
    is_int,
    new_row,
    opt_bool,
    opt_enum,
    opt_int,
    opt_str,
    pagination,
    paginate,
    q_bool,
    q_enum,
    q_str,
    raw_body,
    req_bool,
    req_dt_str,
    req_int,
    req_str,
    touch,
)
from db import db
from errors import ApiError
from middleware import ALL_ROLES, auth
from response import created, ok, ok_list
from services import planlib
from services.genealogy import by_created
from services.lookup import fetch

bp = Blueprint("config", __name__)


# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------

@bp.get("/_clock")
def read_clock():
    auth(ALL_ROLES)
    return ok({"current_utc": db.clock})


@bp.post("/_clock/set_current_utc")
def set_clock():
    auth(["PlatformAdmin"])
    body = raw_body()
    value = req_dt_str(body, "current_utc")
    db.clock = value
    return ok({"current_utc": db.clock})


# --------------------------------------------------------------------------
# Compensation plans
# --------------------------------------------------------------------------

def _validate_bands(bands):
    if not isinstance(bands, list) or len(bands) < 1:
        bad()
    for index, band in enumerate(bands):
        if not isinstance(band, dict):
            bad()
        upper = band.get("upper_points", None)
        if upper is not None:
            if not is_int(upper) or upper < 0:
                bad()
        rate = band.get("rate_bp")
        if not is_int(rate) or rate < 0 or rate > 10000:
            bad()
        if index == len(bands) - 1 and upper is not None:
            bad()
    return [
        {"upper_points": band.get("upper_points", None), "rate_bp": int(band["rate_bp"])}
        for band in bands
    ]


def _validate_ladder(ladder):
    if not isinstance(ladder, list) or len(ladder) < 1:
        bad()
    cleaned = []
    codes = set()
    orders = set()
    for rung in ladder:
        if not isinstance(rung, dict):
            bad()
        code = rung.get("rank_code")
        if not isinstance(code, str) or not code:
            bad()
        order = rung.get("rank_order")
        if not is_int(order) or order < 1:
            bad()
        levels = rung.get("override_levels")
        if not is_int(levels) or levels < 0:
            bad()
        rates = rung.get("override_bp_by_level")
        if rates is None:
            rates = []
        if not isinstance(rates, list):
            bad()
        for rate in rates:
            if not is_int(rate) or rate < 0 or rate > 10000:
                bad()
        if len(rates) != levels:
            bad()
        thresholds = {}
        for name in ("required_pv_points", "required_gv_points", "required_active_legs"):
            value = rung.get(name)
            if not is_int(value) or value < 0:
                bad()
            thresholds[name] = int(value)
        if code in codes or order in orders:
            bad()
        codes.add(code)
        orders.add(order)
        cleaned.append(
            {
                "rank_code": code,
                "rank_order": int(order),
                "required_pv_points": thresholds["required_pv_points"],
                "required_gv_points": thresholds["required_gv_points"],
                "required_active_legs": thresholds["required_active_legs"],
                "override_levels": int(levels),
                "override_bp_by_level": [int(r) for r in rates],
            }
        )
    if orders != set(range(1, len(cleaned) + 1)):
        bad()
    cleaned.sort(key=lambda r: r["rank_order"])
    return cleaned


@bp.post("/compensation-plans")
def create_plan():
    auth(["PlatformAdmin"])
    body = raw_body()

    plan_code = req_str(body, "plan_code", min_len=1, max_len=32)
    name = req_str(body, "name", min_len=1)
    compression_mode = opt_enum(body, "compression_mode", planlib.COMPRESSION_MODES, "DYNAMIC")

    numbers = {}
    for field, (default, minimum, maximum) in planlib.NUMERIC_PLAN_FIELDS.items():
        numbers[field] = opt_int(body, field, default, minimum=minimum, maximum=maximum)

    bands = planlib.DEFAULT_PV_BONUS_BANDS
    if body.get("pv_bonus_bands") is not None:
        bands = _validate_bands(body["pv_bonus_bands"])
    else:
        bands = [dict(band) for band in planlib.DEFAULT_PV_BONUS_BANDS]

    ladder = None
    if body.get("rank_ladder") is not None:
        ladder = _validate_ladder(body["rank_ladder"])
    else:
        ladder = [dict(rung, override_bp_by_level=list(rung["override_bp_by_level"]))
                  for rung in planlib.DEFAULT_RANK_LADDER]

    for existing in db.plans.values():
        if existing["plan_code"] == plan_code:
            raise ApiError("ERR_DUPLICATE_PLAN_CODE")

    row = new_row()
    row["plan_code"] = plan_code
    row["name"] = name
    row["compression_mode"] = compression_mode
    for field in planlib.PLAN_FIELD_ORDER:
        if field in numbers:
            row[field] = numbers[field]
    row["pv_bonus_bands"] = bands
    row["rank_ladder"] = ladder
    row["consultant_count"] = 0
    db.plans[row["id"]] = row
    return created(row)


@bp.patch("/compensation-plans/<plan_id>")
def patch_plan(plan_id):
    auth(["PlatformAdmin"])
    body = raw_body()

    updates = {}
    if "compression_mode" in body and body["compression_mode"] is not None:
        updates["compression_mode"] = opt_enum(
            body, "compression_mode", planlib.COMPRESSION_MODES
        )
    for field in planlib.MUTABLE_PLAN_FIELDS:
        if field == "compression_mode":
            continue
        if field in body and body[field] is not None:
            default, minimum, maximum = planlib.NUMERIC_PLAN_FIELDS[field]
            updates[field] = req_int(body, field, minimum=minimum, maximum=maximum)

    plan = fetch("plan", plan_id)

    if not updates:
        raise ApiError("ERR_NO_MUTABLE_FIELDS")

    plan.update(updates)
    touch(plan)
    return ok(plan)


@bp.get("/compensation-plans")
def list_plans():
    auth(ALL_ROLES)
    limit, offset = pagination()
    plan_code = q_str("plan_code")
    compression_mode = q_enum("compression_mode", planlib.COMPRESSION_MODES)

    rows = by_created(list(db.plans.values()))
    if plan_code is not None:
        rows = [r for r in rows if r["plan_code"] == plan_code]
    if compression_mode is not None:
        rows = [r for r in rows if r["compression_mode"] == compression_mode]
    page, total = paginate(rows, limit, offset)
    return ok_list(page, total, limit, offset)


@bp.get("/compensation-plans/<plan_id>")
def read_plan(plan_id):
    auth(ALL_ROLES)
    return ok(fetch("plan", plan_id))


# --------------------------------------------------------------------------
# Tax jurisdictions
# --------------------------------------------------------------------------

@bp.post("/tax-jurisdictions")
def create_jurisdiction():
    auth(["PlatformAdmin"])
    body = raw_body()
    state_code = req_str(body, "state_code", min_len=2, max_len=2)
    if not state_code.isupper() or not state_code.isalpha():
        bad()
    tax_rate_bp = req_int(body, "tax_rate_bp", minimum=0, maximum=2000)
    # PRD §3.1 names no default for this flag, so it is a required member of the
    # creation payload and its absence is a shape error (PRD §2.8 rule 4).
    facilitator = req_bool(body, "facilitator_agreement_active")

    for existing in db.jurisdictions.values():
        if existing["state_code"] == state_code:
            raise ApiError("ERR_DUPLICATE_JURISDICTION")

    row = new_row(with_version=False)
    row["state_code"] = state_code
    row["tax_rate_bp"] = tax_rate_bp
    row["facilitator_agreement_active"] = facilitator
    row["tax_basis_mode"] = "SRP" if facilitator else "NET_PRICE"
    row["remitter"] = "COMPANY" if facilitator else "CONSULTANT"
    db.jurisdictions[row["id"]] = row
    return created(row)


@bp.get("/tax-jurisdictions")
def list_jurisdictions():
    auth(ALL_ROLES)
    limit, offset = pagination()
    state_code = q_str("state_code")
    facilitator = q_bool("facilitator_agreement_active")

    rows = by_created(list(db.jurisdictions.values()))
    if state_code is not None:
        rows = [r for r in rows if r["state_code"] == state_code]
    if facilitator is not None:
        rows = [r for r in rows if r["facilitator_agreement_active"] is facilitator]
    page, total = paginate(rows, limit, offset)
    return ok_list(page, total, limit, offset)


@bp.get("/tax-jurisdictions/<jurisdiction_id>")
def read_jurisdiction(jurisdiction_id):
    auth(ALL_ROLES)
    return ok(fetch("jurisdiction", jurisdiction_id))


# --------------------------------------------------------------------------
# Products
# --------------------------------------------------------------------------

@bp.post("/products")
def create_product():
    auth(["PlatformAdmin"])
    body = raw_body()
    sku = req_str(body, "sku", min_len=1)
    name = req_str(body, "name", min_len=1)
    wholesale = req_int(body, "wholesale_price_cents", minimum=0)
    srp = req_int(body, "srp_cents", minimum=0)
    if srp < wholesale:
        bad()
    volume_points = opt_int(body, "volume_points_per_unit", 0, minimum=0)
    commissionable = opt_bool(body, "commissionable", True)
    buyback_eligible = opt_bool(body, "buyback_eligible", True)
    is_starter_kit = opt_bool(body, "is_starter_kit", False)

    for existing in db.products.values():
        if existing["sku"] == sku:
            raise ApiError("ERR_DUPLICATE_SKU")

    row = new_row()
    row.update(
        {
            "sku": sku,
            "name": name,
            "wholesale_price_cents": wholesale,
            "srp_cents": srp,
            "volume_points_per_unit": volume_points,
            "commissionable": commissionable,
            "buyback_eligible": buyback_eligible,
            "is_starter_kit": is_starter_kit,
        }
    )
    db.products[row["id"]] = row
    return created(row)


@bp.get("/products")
def list_products():
    auth(ALL_ROLES)
    limit, offset = pagination()
    sku = q_str("sku")
    is_starter_kit = q_bool("is_starter_kit")
    buyback_eligible = q_bool("buyback_eligible")

    rows = by_created(list(db.products.values()))
    if sku is not None:
        rows = [r for r in rows if r["sku"] == sku]
    if is_starter_kit is not None:
        rows = [r for r in rows if r["is_starter_kit"] is is_starter_kit]
    if buyback_eligible is not None:
        rows = [r for r in rows if r["buyback_eligible"] is buyback_eligible]
    page, total = paginate(rows, limit, offset)
    return ok_list(page, total, limit, offset)


@bp.get("/products/<product_id>")
def read_product(product_id):
    auth(ALL_ROLES)
    return ok(fetch("product", product_id))
