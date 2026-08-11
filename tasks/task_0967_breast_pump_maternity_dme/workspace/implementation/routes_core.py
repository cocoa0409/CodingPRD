"""Members, policies, prescriptions, catalog items, logical clock."""
from datetime import datetime, timezone

from flask import Blueprint, request

from db import store, now_iso, today, fmt_dt
from errors import ApiError
from response import ok
from middleware import (
    authorize, check_ownership, body, get_or_404, req_str, opt_str, req_int,
    opt_int, opt_bool, opt_num, req_date, parse_date, req_enum, opt_enum,
    paginate, filter_query, scope_member_list, public, ALL_ROLES,
)
from services import create_entity, bump, recompute_member_aggregates

bp = Blueprint("core", __name__, url_prefix="/dme")

PLAN_TYPES = ["COMMERCIAL_PPO", "MEDICAID", "MEDICARE_ADVANTAGE"]
PUMP_TYPES = ["SINGLE_ELECTRIC", "DOUBLE_ELECTRIC", "HOSPITAL_GRADE"]
ITEM_TYPES = ["PUMP", "PART", "COMPRESSION_GARMENT"]
TIERS = ["STANDARD", "UPGRADE"]
SCHEDULE_MODES = ["ROLLING", "CALENDAR_ANCHORED"]


# ---------------------------------------------------------------- members ----

@bp.route("/members", methods=["POST"])
def create_member():
    authorize(["CareCoordinator", "PlatformAdmin"])
    b = body()
    full_name = req_str(b, "full_name")
    email = req_str(b, "email")
    req_date(b, "date_of_birth")
    addr = req_str(b, "shipping_address")
    if any(m["email"] == email for m in store.members.values()):
        raise ApiError("ERR_VALIDATION", "email must be unique across members", 400)
    m = create_entity(store.members, {
        "full_name": full_name,
        "email": email,
        "date_of_birth": b["date_of_birth"],
        "shipping_address": addr,
        "out_of_pocket_balance_cents": 0,
        "oop_accumulated_cents": 0,
        "next_resupply_date": None,
        "active_schedule_count": 0,
    })
    return ok(public(m), 201)


@bp.route("/members/<mid>", methods=["GET"])
def get_member(mid):
    uid, role = authorize(ALL_ROLES)
    if role == "Member" and mid != uid:
        raise ApiError("ERR_OWNERSHIP_VIOLATION", "Members may only read themselves", 403)
    m = get_or_404(store.members, mid, "ERR_MEMBER_NOT_FOUND")
    return ok(public(m))


@bp.route("/members", methods=["GET"])
def list_members():
    authorize(["CareCoordinator", "InsuranceSpecialist", "BillingSpecialist", "PlatformAdmin"])
    return paginate(list(store.members.values()))


# --------------------------------------------------------------- policies ----

@bp.route("/policies", methods=["POST"])
def create_policy():
    authorize(["PlatformAdmin", "InsuranceSpecialist"])
    b = body()
    if isinstance(b.get("member_id"), str):
        get_or_404(store.members, b["member_id"], "ERR_MEMBER_NOT_FOUND")
    member_id = req_str(b, "member_id")
    get_or_404(store.members, member_id, "ERR_MEMBER_NOT_FOUND")
    payer_name = req_str(b, "payer_name")
    plan_type = req_enum(b, "plan_type", PLAN_TYPES)
    start = req_date(b, "benefit_period_start")
    end = req_date(b, "benefit_period_end")
    if end <= start:
        raise ApiError("ERR_VALIDATION", "benefit_period_end must be after benefit_period_start", 400)
    requires_prior_auth = opt_bool(b, "requires_prior_auth", False)
    threshold = opt_int(b, "prior_auth_threshold_cents", 50000)
    pump_allow = opt_int(b, "pump_allowance_per_period", 1)
    garment_allow = opt_int(b, "garment_allowance_per_period", 0)
    freq = opt_int(b, "resupply_frequency_days", 90)
    mode = opt_enum(b, "schedule_mode", SCHEDULE_MODES, "ROLLING")
    ded = opt_int(b, "deductible_cents", 0)
    coins = opt_num(b, "coinsurance_pct", 0)
    if coins < 0 or coins > 1:
        raise ApiError("ERR_VALIDATION", "coinsurance_pct must be in [0, 1]", 400)
    oop = opt_int(b, "oop_max_cents", 0)
    upgrade = opt_bool(b, "upgrade_coverage", False)
    # half-open interval overlap among the member's ACTIVE policies; adjacency allowed
    for p in store.policies.values():
        if p["member_id"] == member_id and p["status"] == "ACTIVE":
            ps = parse_date(p["benefit_period_start"])
            pe = parse_date(p["benefit_period_end"])
            if start < pe and ps < end:
                raise ApiError(
                    "ERR_POLICY_PERIOD_OVERLAP",
                    "Benefit period overlaps an existing ACTIVE policy",
                    409,
                )
    p = create_entity(store.policies, {
        "member_id": member_id,
        "payer_name": payer_name,
        "plan_type": plan_type,
        "benefit_period_start": b["benefit_period_start"],
        "benefit_period_end": b["benefit_period_end"],
        "requires_prior_auth": requires_prior_auth,
        "prior_auth_threshold_cents": threshold,
        "pump_allowance_per_period": pump_allow,
        "pumps_consumed_count": 0,
        "garment_allowance_per_period": garment_allow,
        "garments_consumed_count": 0,
        "resupply_frequency_days": freq,
        "schedule_mode": mode,
        "deductible_cents": ded,
        "deductible_met_cents": 0,
        "coinsurance_pct": coins,
        "oop_max_cents": oop,
        "upgrade_coverage": upgrade,
        "status": "ACTIVE",
    })
    return ok(public(p), 201)


@bp.route("/policies/<pid>", methods=["GET"])
def get_policy(pid):
    uid, role = authorize(["Member", "CareCoordinator", "InsuranceSpecialist", "BillingSpecialist", "PlatformAdmin"])
    p = get_or_404(store.policies, pid, "ERR_POLICY_NOT_FOUND")
    check_ownership(role, uid, p["member_id"])
    return ok(public(p))


@bp.route("/policies", methods=["GET"])
def list_policies():
    uid, role = authorize(["Member", "CareCoordinator", "InsuranceSpecialist", "BillingSpecialist", "PlatformAdmin"])
    items = scope_member_list(store.policies.values(), role, uid)
    items = filter_query(items, {"member_id": "member_id", "plan_type": "plan_type"})
    return paginate(items)


@bp.route("/policies/<pid>/terminate", methods=["POST"])
def terminate_policy(pid):
    authorize(["PlatformAdmin", "InsuranceSpecialist"])
    p = get_or_404(store.policies, pid, "ERR_POLICY_NOT_FOUND")
    if p["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Policy is not ACTIVE", 409)
    p["status"] = "TERMINATED"
    bump(p)
    affected_members = set()
    for s in store.schedules.values():
        if s["status"] in ("ACTIVE", "SUSPENDED"):
            order = store.pump_orders.get(s["pump_order_id"])
            if order is not None and order["policy_id"] == p["id"]:
                s["status"] = "ENDED"
                bump(s)
                affected_members.add(s["member_id"])
    for mid in affected_members:
        recompute_member_aggregates(store.members[mid])
    return ok(public(p))


# ---------------------------------------------------------- prescriptions ----

@bp.route("/prescriptions", methods=["POST"])
def create_prescription():
    authorize(["CareCoordinator", "PlatformAdmin"])
    b = body()
    if isinstance(b.get("member_id"), str):
        get_or_404(store.members, b["member_id"], "ERR_MEMBER_NOT_FOUND")
    member_id = req_str(b, "member_id")
    get_or_404(store.members, member_id, "ERR_MEMBER_NOT_FOUND")
    diagnosis_code = req_str(b, "diagnosis_code")
    pump_type = req_enum(b, "pump_type", PUMP_TYPES)
    req_date(b, "issued_date")
    req_date(b, "expiration_date")
    rx = create_entity(store.prescriptions, {
        "member_id": member_id,
        "diagnosis_code": diagnosis_code,
        "pump_type": pump_type,
        "issued_date": b["issued_date"],
        "expiration_date": b["expiration_date"],
        "status": "PENDING_VERIFICATION",
        "rejection_reason": None,
        "verified_by_user_id": None,
        "consumed_by_order_id": None,
    })
    return ok(public(rx), 201)


@bp.route("/prescriptions/<rid>", methods=["GET"])
def get_prescription(rid):
    uid, role = authorize(["Member", "CareCoordinator", "InsuranceSpecialist", "PlatformAdmin"])
    rx = get_or_404(store.prescriptions, rid, "ERR_PRESCRIPTION_NOT_FOUND")
    check_ownership(role, uid, rx["member_id"])
    return ok(public(rx))


@bp.route("/prescriptions", methods=["GET"])
def list_prescriptions():
    uid, role = authorize(["Member", "CareCoordinator", "InsuranceSpecialist", "PlatformAdmin"])
    items = scope_member_list(store.prescriptions.values(), role, uid)
    items = filter_query(items, {
        "member_id": "member_id",
        "status": "status",
        "consumed_by_order_id": "consumed_by_order_id",
    })
    return paginate(items)


def _lazy_rx_expiry(rx):
    """Lazy expiry: flips the prescription to EXPIRED and raises."""
    rx["status"] = "EXPIRED"
    bump(rx)
    raise ApiError("ERR_PRESCRIPTION_EXPIRED", "Prescription has expired", 422)


@bp.route("/prescriptions/<rid>/verify", methods=["POST"])
def verify_prescription(rid):
    uid, role = authorize(["InsuranceSpecialist"])
    rx = get_or_404(store.prescriptions, rid, "ERR_PRESCRIPTION_NOT_FOUND")
    if rx["status"] != "PENDING_VERIFICATION":
        raise ApiError("ERR_INVALID_STATE", "Prescription is not PENDING_VERIFICATION", 409)
    if today() > parse_date(rx["expiration_date"]):
        _lazy_rx_expiry(rx)
    rx["status"] = "VERIFIED"
    rx["verified_by_user_id"] = uid
    bump(rx)
    return ok(public(rx))


@bp.route("/prescriptions/<rid>/reject", methods=["POST"])
def reject_prescription(rid):
    authorize(["InsuranceSpecialist"])
    rx = get_or_404(store.prescriptions, rid, "ERR_PRESCRIPTION_NOT_FOUND")
    b = body()
    reason = req_str(b, "rejection_reason")
    if rx["status"] != "PENDING_VERIFICATION":
        raise ApiError("ERR_INVALID_STATE", "Prescription is not PENDING_VERIFICATION", 409)
    rx["status"] = "REJECTED"
    rx["rejection_reason"] = reason
    bump(rx)
    return ok(public(rx))


@bp.route("/prescriptions/<rid>/resubmit", methods=["POST"])
def resubmit_prescription(rid):
    authorize(["CareCoordinator", "InsuranceSpecialist"])
    rx = get_or_404(store.prescriptions, rid, "ERR_PRESCRIPTION_NOT_FOUND")
    if rx["status"] != "REJECTED":
        raise ApiError("ERR_INVALID_STATE", "Prescription is not REJECTED", 409)
    if today() > parse_date(rx["expiration_date"]):
        _lazy_rx_expiry(rx)
    rx["status"] = "PENDING_VERIFICATION"
    rx["rejection_reason"] = None
    bump(rx)
    return ok(public(rx))


# ---------------------------------------------------------------- catalog ----

@bp.route("/catalog-items", methods=["POST"])
def create_catalog_item():
    authorize(["PlatformAdmin"])
    b = body()
    item_type = req_enum(b, "item_type", ITEM_TYPES)
    name = req_str(b, "name")
    sku = req_str(b, "sku")
    price = req_int(b, "unit_price_cents")
    tier = opt_enum(b, "insurance_tier", TIERS, "STANDARD")
    upgrade_fee = opt_int(b, "upgrade_fee_cents", 0)
    covered = opt_bool(b, "covered_under_resupply", False)
    max_qty = opt_int(b, "max_qty_per_frequency", 0)
    warranty_months = opt_int(b, "warranty_months", 0)
    pump_type = opt_enum(b, "pump_type", PUMP_TYPES, None)
    if any(c["sku"] == sku for c in store.catalog_items.values()):
        raise ApiError("ERR_VALIDATION", "sku must be unique", 400)
    c = create_entity(store.catalog_items, {
        "item_type": item_type,
        "name": name,
        "sku": sku,
        "unit_price_cents": price,
        "insurance_tier": tier,
        "upgrade_fee_cents": upgrade_fee,
        "covered_under_resupply": covered,
        "max_qty_per_frequency": max_qty,
        "warranty_months": warranty_months,
        "pump_type": pump_type,
    })
    return ok(public(c), 201)


@bp.route("/catalog-items/<cid>", methods=["GET"])
def get_catalog_item(cid):
    authorize(ALL_ROLES)
    c = get_or_404(store.catalog_items, cid, "ERR_CATALOG_ITEM_NOT_FOUND")
    return ok(public(c))


@bp.route("/catalog-items", methods=["GET"])
def list_catalog_items():
    authorize(ALL_ROLES)
    items = filter_query(store.catalog_items.values(), {"item_type": "item_type"})
    v = request.args.get("covered_under_resupply")
    if v is not None:
        if v == "true":
            items = [e for e in items if e["covered_under_resupply"]]
        elif v == "false":
            items = [e for e in items if not e["covered_under_resupply"]]
        else:
            raise ApiError("ERR_VALIDATION", "covered_under_resupply must be true or false", 400)
    return paginate(items)


@bp.route("/catalog-items/<cid>/order-lines", methods=["GET"])
def list_catalog_item_order_lines(cid):
    authorize(["CareCoordinator", "InsuranceSpecialist", "BillingSpecialist", "PlatformAdmin"])
    c = get_or_404(store.catalog_items, cid, "ERR_CATALOG_ITEM_NOT_FOUND")
    items = [l for l in store.order_lines.values() if l["catalog_item_id"] == c["id"]]
    return paginate(items)


# ------------------------------------------------------------------ clock ----

@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authorize(["PlatformAdmin"])
    b = body()
    iso = req_str(b, "to_iso8601")
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        raise ApiError("ERR_VALIDATION", "to_iso8601 must be ISO 8601", 400)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    store.clock = dt.astimezone(timezone.utc)
    return ok({"current_utc": fmt_dt(store.clock)})
