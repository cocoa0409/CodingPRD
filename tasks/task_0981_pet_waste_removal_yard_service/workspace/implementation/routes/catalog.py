from flask import Blueprint, request

import services as svc
from errors import err_invalid_request
from middleware import (
    auth,
    get_body,
    require,
    optional,
    require_enum,
    lookup,
    parse_pagination,
    paginate,
)
from response import ok_object, ok_list

bp = Blueprint("catalog", __name__)

VISIT_FREQUENCIES = {"WEEKLY", "BIWEEKLY", "TWICE_WEEKLY", "DAILY"}


def _require_int_list(data, field):
    v = require(data, field, list)
    for item in v:
        if not isinstance(item, int) or isinstance(item, bool):
            raise err_invalid_request(f"Field {field} must be a list of integers")
    return v


def _check_tiers(thresholds, surcharges, label):
    if any(thresholds[i] >= thresholds[i + 1] for i in range(len(thresholds) - 1)):
        raise err_invalid_request(f"{label}_thresholds must be ascending")
    if len(surcharges) != len(thresholds) + 1:
        raise err_invalid_request(
            f"{label}_surcharges_cents must have exactly one more entry than "
            f"{label}_thresholds (implicit top tier)"
        )


@bp.post("/api/subscription-plans")
def create_plan():
    auth("OperationsManager")
    data = get_body()
    plan_code = require(data, "plan_code", str)
    display_name = require(data, "display_name", str)
    frequency = require_enum(data, "visit_frequency", VISIT_FREQUENCIES)
    applies_multi = require(data, "applies_to_multifamily", bool)
    base_fee = require(data, "base_monthly_fee_cents", int)
    yard_thresholds = _require_int_list(data, "yard_tier_thresholds")
    yard_surcharges = _require_int_list(data, "yard_tier_surcharges_cents")
    pet_thresholds = _require_int_list(data, "pet_tier_thresholds")
    pet_surcharges = _require_int_list(data, "pet_tier_surcharges_cents")
    multiplier = optional(data, "multifamily_multiplier_bp", int, 10000)
    if base_fee < 0:
        raise err_invalid_request("base_monthly_fee_cents must be >= 0")
    _check_tiers(yard_thresholds, yard_surcharges, "yard_tier")
    _check_tiers(pet_thresholds, pet_surcharges, "pet_tier")
    for p in svc.plans.values():
        if p["plan_code"] == plan_code:
            raise err_invalid_request("plan_code must be unique")
    rec = svc.new_record()
    rec.update(
        {
            "plan_code": plan_code,
            "display_name": display_name,
            "visit_frequency": frequency,
            "applies_to_multifamily": applies_multi,
            "base_monthly_fee_cents": base_fee,
            "yard_tier_thresholds": yard_thresholds,
            "yard_tier_surcharges_cents": yard_surcharges,
            "pet_tier_thresholds": pet_thresholds,
            "pet_tier_surcharges_cents": pet_surcharges,
            "multifamily_multiplier_bp": multiplier,
            "plan_status": "ACTIVE",
        }
    )
    svc.plans[rec["id"]] = rec
    return ok_object(svc.ser_plan(rec), status=201)


@bp.get("/api/subscription-plans")
def list_plans():
    auth("OperationsManager", "Customer", "BillingAdmin")
    limit, offset = parse_pagination()
    records = list(svc.plans.values())
    status = request.args.get("plan_status")
    if status is not None:
        records = [p for p in records if p["plan_status"] == status]
    page, total = paginate(records, limit, offset)
    return ok_list([svc.ser_plan(p) for p in page], total, limit, offset)


@bp.get("/api/subscription-plans/<pid>")
def get_plan(pid):
    auth("OperationsManager", "Customer", "BillingAdmin")
    rec = lookup(svc.plans, pid, "SubscriptionPlan")
    return ok_object(svc.ser_plan(rec))


@bp.post("/api/service-addons")
def create_addon():
    auth("OperationsManager")
    data = get_body()
    addon_code = require(data, "addon_code", str)
    display_name = require(data, "display_name", str)
    price = require(data, "price_cents_per_visit", int)
    if price < 0:
        raise err_invalid_request("price_cents_per_visit must be >= 0")
    for a in svc.addons.values():
        if a["addon_code"] == addon_code:
            raise err_invalid_request("addon_code must be unique")
    rec = svc.new_record()
    rec.update(
        {
            "addon_code": addon_code,
            "display_name": display_name,
            "price_cents_per_visit": price,
            "addon_status": "ACTIVE",
        }
    )
    svc.addons[rec["id"]] = rec
    return ok_object(svc.ser_addon(rec), status=201)


@bp.get("/api/service-addons")
def list_addons():
    auth("OperationsManager", "Customer", "BillingAdmin", "Technician")
    limit, offset = parse_pagination()
    records = list(svc.addons.values())
    page, total = paginate(records, limit, offset)
    return ok_list([svc.ser_addon(a) for a in page], total, limit, offset)
