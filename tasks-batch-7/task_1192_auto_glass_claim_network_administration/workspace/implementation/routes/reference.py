"""Reference data: Policyholder, StateRegulation, Policy, GlassShop, PartCatalogEntry."""

from flask import Blueprint, request

from db import store, base_fields, touch, parse_date
from errors import (
    ApiError,
    ERR_POLICYHOLDER_NOT_FOUND,
    ERR_SHOP_NOT_FOUND,
    ERR_PART_NOT_FOUND,
    ERR_DUPLICATE_STATE_REGULATION,
    ERR_INVALID_REQUEST,
)
from middleware import (
    get_context,
    body_json,
    req_str,
    req_int,
    opt_int,
    req_bool,
    opt_bool,
    req_enum,
    opt_enum,
    req_str_list,
    pagination_params,
    paginate,
    ALL_ROLES,
    ROLE_NETWORK_ADMIN,
)
from response import success_object, success_list
from db import sorted_created
from serialize import (
    policyholder_view,
    regulation_view,
    policy_view,
    shop_view,
    part_view,
    work_order_view,
    line_item_view,
)
from services.capacity import bay_minutes_booked

bp = Blueprint("reference", __name__)

ADMIN = [ROLE_NETWORK_ADMIN]

COVERAGE_TYPES = {"COMPREHENSIVE", "LIABILITY"}
AGREEMENT_TIERS = {"PLATINUM", "PREFERRED", "STANDARD"}
PART_CATEGORIES = {"WINDSHIELD", "SIDE_GLASS", "REAR_GLASS", "MOLDING_KIT", "CALIBRATION"}
PART_ORIGINS = {"OEM", "AFTERMARKET"}
NETWORK_STATUSES = {"ACTIVE", "SUSPENDED"}
PART_STATUSES = {"AVAILABLE", "DISCONTINUED"}


# ---------------------------------------------------------------- Policyholder

@bp.route("/policyholders", methods=["POST"])
def create_policyholder():
    get_context(ADMIN)
    data = body_json(required=True)
    ph = base_fields()
    ph.update(
        {
            "full_name": req_str(data, "full_name"),
            "email": req_str(data, "email"),
            "phone": req_str(data, "phone"),
            "state_code": req_str(data, "state_code"),
            "fraud_score": 0,
            "no_show_count": 0,
            "status": "ACTIVE",
        }
    )
    store.policyholders[ph["id"]] = ph
    return success_object(policyholder_view(ph), status=201)


@bp.route("/policyholders/<pid>", methods=["GET"])
def get_policyholder(pid):
    get_context(ALL_ROLES)
    ph = store.policyholders.get(pid)
    if ph is None:
        raise ApiError(ERR_POLICYHOLDER_NOT_FOUND, 404, "Policyholder does not exist")
    return success_object(policyholder_view(ph))


# ------------------------------------------------------------ StateRegulation

@bp.route("/state-regulations", methods=["POST"])
def create_state_regulation():
    get_context(ADMIN)
    data = body_json(required=True)
    state_code = req_str(data, "state_code")
    zero_deductible = req_bool(data, "zero_deductible_windshield")
    max_deductible = opt_int(data, "max_deductible_cents", None)
    tax_rate = req_int(data, "glass_sales_tax_rate_bp")
    if state_code in store.state_reg_by_code:
        raise ApiError(
            ERR_DUPLICATE_STATE_REGULATION,
            409,
            "A StateRegulation already exists for this state_code",
        )
    reg = base_fields()
    reg.update(
        {
            "state_code": state_code,
            "zero_deductible_windshield": zero_deductible,
            "max_deductible_cents": max_deductible,
            "glass_sales_tax_rate_bp": tax_rate,
        }
    )
    store.state_regulations[reg["id"]] = reg
    store.state_reg_by_code[state_code] = reg["id"]
    return success_object(regulation_view(reg), status=201)


@bp.route("/state-regulations", methods=["GET"])
def list_state_regulations():
    get_context(ALL_ROLES)
    limit, offset = pagination_params()
    items = sorted_created(store.state_regulations.values())
    state_code = request.args.get("state_code")
    if state_code is not None:
        items = [r for r in items if r["state_code"] == state_code]
    page, total = paginate(items, limit, offset)
    return success_list([regulation_view(r) for r in page], limit, offset, total)


# -------------------------------------------------------------------- Policy

@bp.route("/policies", methods=["POST"])
def create_policy():
    get_context(ADMIN)
    data = body_json(required=True)
    policyholder_id = req_str(data, "policyholder_id")
    if policyholder_id not in store.policyholders:
        raise ApiError(ERR_POLICYHOLDER_NOT_FOUND, 404, "Referenced policyholder does not exist")
    policy = base_fields()
    policy.update(
        {
            "policyholder_id": policyholder_id,
            "policy_number": req_str(data, "policy_number"),
            "state_code": req_str(data, "state_code"),
            "coverage_type": req_enum(data, "coverage_type", COVERAGE_TYPES),
            "deductible_cents": req_int(data, "deductible_cents"),
            "oem_endorsement": opt_bool(data, "oem_endorsement", False),
            "effective_start_date": req_str(data, "effective_start_date"),
            "effective_end_date": req_str(data, "effective_end_date"),
            "status": "ACTIVE",
        }
    )
    store.policies[policy["id"]] = policy
    return success_object(policy_view(policy), status=201)


@bp.route("/policies/<pid>", methods=["GET"])
def get_policy(pid):
    get_context(ALL_ROLES)
    policy = store.policies.get(pid)
    if policy is None:
        from errors import ERR_POLICY_NOT_FOUND

        raise ApiError(ERR_POLICY_NOT_FOUND, 404, "Policy does not exist")
    return success_object(policy_view(policy))


@bp.route("/policies", methods=["GET"])
def list_policies():
    get_context(ALL_ROLES)
    limit, offset = pagination_params()
    items = sorted_created(store.policies.values())
    policyholder_id = request.args.get("policyholder_id")
    status = request.args.get("status")
    if policyholder_id is not None:
        items = [p for p in items if p["policyholder_id"] == policyholder_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    page, total = paginate(items, limit, offset)
    return success_list([policy_view(p) for p in page], limit, offset, total)


# ------------------------------------------------------------------ GlassShop

@bp.route("/glass-shops", methods=["POST"])
def create_glass_shop():
    get_context(ADMIN)
    data = body_json(required=True)
    shop = base_fields()
    shop.update(
        {
            "shop_name": req_str(data, "shop_name"),
            "state_code": req_str(data, "state_code"),
            "service_zip_prefixes": req_str_list(data, "service_zip_prefixes"),
            "mobile_capable": req_bool(data, "mobile_capable"),
            "adas_certified": req_bool(data, "adas_certified"),
            "oem_certified": req_bool(data, "oem_certified"),
            "agreement_tier": req_enum(data, "agreement_tier", AGREEMENT_TIERS),
            "bay_count": req_int(data, "bay_count"),
            "mobile_unit_count": req_int(data, "mobile_unit_count"),
            "operating_minutes_per_day": opt_int(data, "operating_minutes_per_day", 480),
            "network_status": "ACTIVE",
            "warranty_strike_count": 0,
            "rolling_audit_score": 100,
            "_audit_events": [],
        }
    )
    store.shops[shop["id"]] = shop
    return success_object(shop_view(shop), status=201)


@bp.route("/glass-shops/<sid>", methods=["GET"])
def get_glass_shop(sid):
    get_context(ALL_ROLES)
    shop = store.shops.get(sid)
    if shop is None:
        raise ApiError(ERR_SHOP_NOT_FOUND, 404, "Glass shop does not exist")
    return success_object(shop_view(shop))


@bp.route("/glass-shops/<sid>", methods=["PATCH"])
def patch_glass_shop(sid):
    get_context(ADMIN)
    shop = store.shops.get(sid)
    if shop is None:
        raise ApiError(ERR_SHOP_NOT_FOUND, 404, "Glass shop does not exist")
    data = body_json(required=False)
    network_status = opt_enum(data, "network_status", NETWORK_STATUSES)
    agreement_tier = opt_enum(data, "agreement_tier", AGREEMENT_TIERS)
    adas_certified = opt_bool(data, "adas_certified")
    mobile_capable = opt_bool(data, "mobile_capable")
    if network_status is not None:
        shop["network_status"] = network_status
    if agreement_tier is not None:
        shop["agreement_tier"] = agreement_tier
    if adas_certified is not None:
        shop["adas_certified"] = adas_certified
    if mobile_capable is not None:
        shop["mobile_capable"] = mobile_capable
    touch(shop)
    return success_object(shop_view(shop))


@bp.route("/glass-shops/<sid>/work-orders", methods=["GET"])
def list_shop_work_orders(sid):
    get_context(ALL_ROLES)
    shop = store.shops.get(sid)
    if shop is None:
        raise ApiError(ERR_SHOP_NOT_FOUND, 404, "Glass shop does not exist")
    limit, offset = pagination_params()
    items = sorted_created([w for w in store.work_orders.values() if w["shop_id"] == sid])
    status = request.args.get("status")
    if status is not None:
        items = [w for w in items if w["status"] == status]
    page, total = paginate(items, limit, offset)
    return success_list([work_order_view(w) for w in page], limit, offset, total)


@bp.route("/glass-shops/<sid>/capacity", methods=["GET"])
def get_shop_capacity(sid):
    get_context(ALL_ROLES)
    shop = store.shops.get(sid)
    if shop is None:
        raise ApiError(ERR_SHOP_NOT_FOUND, 404, "Glass shop does not exist")
    date_str = request.args.get("date")
    if date_str is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Query parameter 'date' is required")
    try:
        date_val = parse_date(date_str)
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Query parameter 'date' must be YYYY-MM-DD")
    bay_total = shop["bay_count"] * shop["operating_minutes_per_day"]
    booked = bay_minutes_booked(sid, date_val.isoformat())
    return success_object(
        {
            "bay_minutes_total": bay_total,
            "bay_minutes_booked": booked,
            "bay_minutes_available": bay_total - booked,
            "mobile_units_total": shop["mobile_unit_count"],
        }
    )


# ----------------------------------------------------------- PartCatalogEntry

@bp.route("/part-catalog-entries", methods=["POST"])
def create_part():
    get_context(ADMIN)
    data = body_json(required=True)
    part = base_fields()
    part.update(
        {
            "part_number": req_str(data, "part_number"),
            "part_description": req_str(data, "part_description"),
            "part_category": req_enum(data, "part_category", PART_CATEGORIES),
            "part_origin": req_enum(data, "part_origin", PART_ORIGINS),
            "nags_list_price_cents": req_int(data, "nags_list_price_cents"),
            "status": "AVAILABLE",
        }
    )
    store.parts[part["id"]] = part
    return success_object(part_view(part), status=201)


@bp.route("/part-catalog-entries/<pid>", methods=["GET"])
def get_part(pid):
    get_context(ALL_ROLES)
    part = store.parts.get(pid)
    if part is None:
        raise ApiError(ERR_PART_NOT_FOUND, 404, "Part catalog entry does not exist")
    return success_object(part_view(part))


@bp.route("/part-catalog-entries", methods=["GET"])
def list_parts():
    get_context(ALL_ROLES)
    limit, offset = pagination_params()
    items = sorted_created(store.parts.values())
    part_number = request.args.get("part_number")
    part_category = request.args.get("part_category")
    status = request.args.get("status")
    if part_number is not None:
        items = [p for p in items if p["part_number"] == part_number]
    if part_category is not None:
        items = [p for p in items if p["part_category"] == part_category]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    page, total = paginate(items, limit, offset)
    return success_list([part_view(p) for p in page], limit, offset, total)


@bp.route("/part-catalog-entries/<pid>", methods=["PATCH"])
def patch_part(pid):
    get_context(ADMIN)
    part = store.parts.get(pid)
    if part is None:
        raise ApiError(ERR_PART_NOT_FOUND, 404, "Part catalog entry does not exist")
    data = body_json(required=False)
    status = opt_enum(data, "status", PART_STATUSES)
    nags = opt_int(data, "nags_list_price_cents")
    if status is not None:
        part["status"] = status
    if nags is not None:
        part["nags_list_price_cents"] = nags
    touch(part)
    return success_object(part_view(part))


@bp.route("/part-catalog-entries/<pid>/line-items", methods=["GET"])
def list_part_line_items(pid):
    get_context(ALL_ROLES)
    part = store.parts.get(pid)
    if part is None:
        raise ApiError(ERR_PART_NOT_FOUND, 404, "Part catalog entry does not exist")
    limit, offset = pagination_params()
    items = sorted_created(
        [l for l in store.invoice_lines.values() if l.get("part_catalog_entry_id") == pid]
    )
    page, total = paginate(items, limit, offset)
    return success_list([line_item_view(l) for l in page], limit, offset, total)
