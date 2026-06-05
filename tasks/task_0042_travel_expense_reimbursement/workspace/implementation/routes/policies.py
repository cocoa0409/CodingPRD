"""TravelPolicy and PerDiemRate routes."""
from flask import Blueprint, request

from common import (get_json_body, require_fields, require_string,
                    require_nonneg_int, paginate, list_response)
from db import store, base_fields, touch
from errors import err
from middleware import require_roles
from response import success
from services import get_or_404, active_policy

bp = Blueprint("policies", __name__)

POLICY_INT_FIELDS = [
    "max_economy_fare_cents", "business_class_min_hours", "advance_purchase_days",
    "cdw_daily_cap_cents", "mileage_rate_milli_cents", "receipt_required_threshold_cents",
]


# ---- TravelPolicy ----

@bp.route("/travel-policies", methods=["POST"])
@require_roles("FinanceAdmin")
def create_policy():
    body = get_json_body()
    require_fields(body, ["name"] + POLICY_INT_FIELDS)
    name = require_string(body, "name")
    vals = {f: require_nonneg_int(body, f) for f in POLICY_INT_FIELDS}
    p = base_fields()
    p.update({"name": name, "status": "DRAFT"})
    p.update(vals)
    store.travel_policies[p["id"]] = p
    return success(dict(p), status=201)


@bp.route("/travel-policies/<policy_id>", methods=["GET"])
@require_roles("FinanceAdmin", "Traveler", "Approver")
def get_policy(policy_id):
    p = get_or_404(store.travel_policies, policy_id)
    return success(dict(p))


@bp.route("/travel-policies/<policy_id>/activate", methods=["POST"])
@require_roles("FinanceAdmin")
def activate_policy(policy_id):
    p = get_or_404(store.travel_policies, policy_id)
    # state legality
    if p["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Policy is not DRAFT")
    # business: no other ACTIVE policy
    other = active_policy()
    if other is not None and other["id"] != p["id"]:
        raise err("ERR_POLICY_ALREADY_ACTIVE", "Another policy is already ACTIVE")
    p["status"] = "ACTIVE"
    touch(p)
    return success(dict(p))


@bp.route("/travel-policies/<policy_id>/retire", methods=["POST"])
@require_roles("FinanceAdmin")
def retire_policy(policy_id):
    p = get_or_404(store.travel_policies, policy_id)
    if p["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Policy is not ACTIVE")
    # business: no PENDING / PENDING_OOP_APPROVAL trip references this policy
    for t in store.trip_requests.values():
        if t["policy_id"] == p["id"] and t["status"] in ("PENDING", "PENDING_OOP_APPROVAL"):
            raise err("ERR_POLICY_IN_USE", "Policy is referenced by a live trip request")
    p["status"] = "RETIRED"
    touch(p)
    return success(dict(p))


# ---- PerDiemRate ----

@bp.route("/per-diem-rates", methods=["POST"])
@require_roles("FinanceAdmin")
def create_per_diem_rate():
    body = get_json_body()
    require_fields(body, ["state_code", "lodging_cap_cents", "mie_cents"])
    state_code = require_string(body, "state_code")
    lodging = require_nonneg_int(body, "lodging_cap_cents")
    mie = require_nonneg_int(body, "mie_cents")
    # immutable reference data: id + created_at only
    r = base_fields(common=False)
    r.update({
        "state_code": state_code,
        "lodging_cap_cents": lodging,
        "mie_cents": mie,
    })
    store.per_diem_rates[r["id"]] = r
    return success(dict(r), status=201)


@bp.route("/per-diem-rates/<rate_id>", methods=["GET"])
@require_roles("FinanceAdmin", "Traveler", "Approver")
def get_per_diem_rate(rate_id):
    r = get_or_404(store.per_diem_rates, rate_id)
    return success(dict(r))


@bp.route("/per-diem-rates", methods=["GET"])
@require_roles("FinanceAdmin", "Traveler", "Approver")
def list_per_diem_rates():
    limit, offset = paginate()
    items = list(store.per_diem_rates.values())
    state_code = request.args.get("state_code")
    if state_code is not None:
        items = [r for r in items if r["state_code"] == state_code]
    page, pagination = list_response(items, limit, offset)
    return success([dict(r) for r in page], pagination=pagination)
