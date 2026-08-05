"""Routes: logical clock, vendors, contracts, services, recommendations."""
from flask import Blueprint, g

import core
from core import (db, ApiError, ok, ok_list, guard, get_body, require,
                  check_enum, as_int_nonneg, as_bool, base_common, touch,
                  serialize, ordered, paginate, find, parse_dt,
                  recompute_contract_committed, compute_utilization,
                  compute_expected_amount, compute_projected_savings,
                  compute_realized_savings, add_months, format_dt_like,
                  UTILIZATION_THRESHOLD_PCT)
from decimal import Decimal
from datetime import timedelta
from flask import request

bp = Blueprint("inventory", __name__)

VENDOR_TYPES = {"TELECOM", "SAAS"}
SERVICE_TYPES = {"TELECOM_LINE", "SAAS_SUBSCRIPTION"}
LICENSE_TYPES = {"PER_SEAT", "FLAT", "USAGE_BASED"}
DISCOVERY_SOURCES = {"SANCTIONED", "SHADOW_IT"}
REC_TYPES = {"DOWNGRADE_SEATS", "TERMINATE", "SANCTION"}


def validate_dt(body, field):
    raw = body[field]
    try:
        parse_dt(raw)
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", 422, f"{field} must be an ISO 8601 datetime.")
    return raw


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
@bp.route("/_clock/set_current_utc", methods=["POST"])
@guard(["SystemAdmin"])
def set_clock():
    body = get_body()
    require(body, ["to_iso8601"])
    raw = validate_dt(body, "to_iso8601")
    db.clock_raw = raw
    db.clock_dt = parse_dt(raw)
    return ok({"current_utc": raw}, status=200)


# ---------------------------------------------------------------------------
# Vendors
# ---------------------------------------------------------------------------
@bp.route("/vendors", methods=["POST"])
@guard(["Sourcing"])
def create_vendor():
    body = get_body()
    require(body, ["name", "vendor_type"])
    check_enum(body["vendor_type"], VENDOR_TYPES, "vendor_type")
    v = base_common({
        "name": body["name"],
        "vendor_type": body["vendor_type"],
        "status": "ACTIVE",
    })
    db.vendors[v["id"]] = v
    return ok(serialize(v), status=201)


@bp.route("/vendors/<vid>", methods=["GET"])
@guard(core.ALL_ROLES)
def get_vendor(vid):
    v = find(db.vendors, vid, "ERR_VENDOR_NOT_FOUND")
    return ok(serialize(v))


@bp.route("/vendors/<vid>/suspend", methods=["POST"])
@guard(["Sourcing"])
def suspend_vendor(vid):
    v = find(db.vendors, vid, "ERR_VENDOR_NOT_FOUND")
    if v["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Vendor is not ACTIVE.")
    v["status"] = "SUSPENDED"
    touch(v)
    return ok(serialize(v))


@bp.route("/vendors/<vid>/contracts", methods=["GET"])
@guard(core.ALL_ROLES)
def list_vendor_contracts(vid):
    find(db.vendors, vid, "ERR_VENDOR_NOT_FOUND")
    items = ordered([c for c in db.contracts.values() if c["vendor_id"] == vid])
    page, meta = paginate(items)
    return ok_list([serialize(c) for c in page], meta)


# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------
@bp.route("/contracts", methods=["POST"])
@guard(["Sourcing"])
def create_contract():
    body = get_body()
    require(body, ["vendor_id", "term_start", "term_end", "renewal_notice_days"])
    validate_dt(body, "term_start")
    validate_dt(body, "term_end")
    renewal_notice_days = as_int_nonneg(body, "renewal_notice_days")
    renewal_term_months = as_int_nonneg(body, "renewal_term_months",
                                        required=False, default=12)
    auto_renew = as_bool(body, "auto_renew", False)
    volume_tier_enabled = as_bool(body, "volume_tier_enabled", True)
    # existence
    find(db.vendors, body["vendor_id"], "ERR_VENDOR_NOT_FOUND")
    c = base_common({
        "vendor_id": body["vendor_id"],
        "term_start": body["term_start"],
        "term_end": body["term_end"],
        "renewal_notice_days": renewal_notice_days,
        "renewal_term_months": renewal_term_months,
        "auto_renew": auto_renew,
        "volume_tier_enabled": volume_tier_enabled,
        "status": "DRAFT",
        "monthly_committed_cost_cents": 0,
        "total_recovered_cents": 0,
        "renewal_count": 0,
    })
    db.contracts[c["id"]] = c
    return ok(serialize(c), status=201)


@bp.route("/contracts/<cid>", methods=["GET"])
@guard(core.ALL_ROLES)
def get_contract(cid):
    c = find(db.contracts, cid, "ERR_CONTRACT_NOT_FOUND")
    return ok(serialize(c))


@bp.route("/contracts/<cid>/activate", methods=["POST"])
@guard(["Sourcing"])
def activate_contract(cid):
    c = find(db.contracts, cid, "ERR_CONTRACT_NOT_FOUND")
    if c["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Contract is not DRAFT.")
    vendor = db.vendors[c["vendor_id"]]
    if vendor["status"] != "ACTIVE":
        raise ApiError("ERR_VENDOR_SUSPENDED", 409, "Vendor is SUSPENDED.")
    # closed-interval term overlap with other ACTIVE contracts of same vendor
    a_start = parse_dt(c["term_start"])
    a_end = parse_dt(c["term_end"])
    for other in db.contracts.values():
        if other["id"] == c["id"]:
            continue
        if other["vendor_id"] != c["vendor_id"] or other["status"] != "ACTIVE":
            continue
        b_start = parse_dt(other["term_start"])
        b_end = parse_dt(other["term_end"])
        if a_start <= b_end and b_start <= a_end:  # closed interval, adjacency overlaps
            raise ApiError("ERR_CONTRACT_TERM_OVERLAP", 409, "Contract term overlaps.")
    c["status"] = "ACTIVE"
    touch(c)
    return ok(serialize(c))


@bp.route("/contracts/<cid>/renew", methods=["POST"])
@guard(["Sourcing"])
def renew_contract(cid):
    c = find(db.contracts, cid, "ERR_CONTRACT_NOT_FOUND")
    if c["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Contract is not ACTIVE.")
    vendor = db.vendors[c["vendor_id"]]
    if vendor["status"] != "ACTIVE":
        raise ApiError("ERR_VENDOR_SUSPENDED", 409, "Vendor is SUSPENDED.")
    term_end = parse_dt(c["term_end"])
    window_start = term_end - timedelta(days=c["renewal_notice_days"])
    now = db.clock_dt
    if not (window_start <= now <= term_end):
        raise ApiError("ERR_OUTSIDE_RENEWAL_WINDOW", 422, "Outside renewal window.")
    new_end = add_months(term_end, c["renewal_term_months"])
    c["term_end"] = format_dt_like(c["term_end"], new_end)
    c["renewal_count"] += 1
    touch(c)
    return ok(serialize(c))


@bp.route("/contracts/<cid>/terminate", methods=["POST"])
@guard(["Sourcing"])
def terminate_contract(cid):
    c = find(db.contracts, cid, "ERR_CONTRACT_NOT_FOUND")
    if c["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Contract is not ACTIVE.")
    c["status"] = "TERMINATED"
    for s in db.services.values():
        if s["contract_id"] == c["id"] and s["status"] != "RETIRED":
            s["status"] = "RETIRED"
            touch(s)
    recompute_contract_committed(c)
    touch(c)
    return ok(serialize(c))


@bp.route("/contracts/<cid>/services", methods=["GET"])
@guard(core.ALL_ROLES)
def list_contract_services(cid):
    find(db.contracts, cid, "ERR_CONTRACT_NOT_FOUND")
    items = ordered([s for s in db.services.values() if s["contract_id"] == cid])
    page, meta = paginate(items)
    return ok_list([serialize(s) for s in page], meta)


@bp.route("/contracts/<cid>/invoices", methods=["GET"])
@guard(core.ALL_ROLES)
def list_contract_invoices(cid):
    find(db.contracts, cid, "ERR_CONTRACT_NOT_FOUND")
    items = ordered([i for i in db.invoices.values() if i["contract_id"] == cid])
    page, meta = paginate(items)
    return ok_list([serialize(i) for i in page], meta)


@bp.route("/contracts/<cid>/savings-summary", methods=["GET"])
@guard(core.ALL_ROLES)
def savings_summary(cid):
    c = find(db.contracts, cid, "ERR_CONTRACT_NOT_FOUND")
    service_ids = {s["id"] for s in db.services.values() if s["contract_id"] == cid}
    total_projected = 0
    total_realized = 0
    for r in db.recommendations.values():
        if r["service_id"] in service_ids:
            total_projected += r["projected_savings_cents"]
            total_realized += r["realized_savings_cents"]
    data = {
        "contract_id": cid,
        "total_projected_savings_cents": total_projected,
        "total_realized_savings_cents": total_realized,
        "total_recovered_cents": c["total_recovered_cents"],
        "monthly_committed_cost_cents": c["monthly_committed_cost_cents"],
    }
    return ok(data)


# ---------------------------------------------------------------------------
# Services
# ---------------------------------------------------------------------------
@bp.route("/services", methods=["POST"])
@guard(["Sourcing"])
def create_service():
    body = get_body()
    require(body, ["contract_id", "service_type", "license_type",
                   "unit_rate_cents", "contracted_quantity"])
    check_enum(body["service_type"], SERVICE_TYPES, "service_type")
    check_enum(body["license_type"], LICENSE_TYPES, "license_type")
    unit_rate = as_int_nonneg(body, "unit_rate_cents")
    contracted = as_int_nonneg(body, "contracted_quantity")
    active = as_int_nonneg(body, "active_quantity", required=False, default=0)
    discovery = body.get("discovery_source", "SANCTIONED")
    if discovery is None:
        discovery = "SANCTIONED"
    check_enum(discovery, DISCOVERY_SOURCES, "discovery_source")
    sanctioned = as_bool(body, "sanctioned", True)
    find(db.contracts, body["contract_id"], "ERR_CONTRACT_NOT_FOUND")
    s = base_common({
        "contract_id": body["contract_id"],
        "service_type": body["service_type"],
        "license_type": body["license_type"],
        "unit_rate_cents": unit_rate,
        "contracted_quantity": contracted,
        "active_quantity": active,
        "discovery_source": discovery,
        "sanctioned": sanctioned,
        "utilization_pct": compute_utilization(active, contracted),
        "status": "ACTIVE",
    })
    db.services[s["id"]] = s
    recompute_contract_committed(db.contracts[s["contract_id"]])
    return ok(serialize(s), status=201)


@bp.route("/services/<sid>", methods=["GET"])
@guard(core.ALL_ROLES)
def get_service(sid):
    s = find(db.services, sid, "ERR_SERVICE_NOT_FOUND")
    return ok(serialize(s))


@bp.route("/services/<sid>/recommendations", methods=["POST"])
@guard(["Analyst"])
def create_recommendation(sid):
    body = get_body()
    require(body, ["rec_type", "target_quantity", "expected_service_version"])
    check_enum(body["rec_type"], REC_TYPES, "rec_type")
    target_quantity = as_int_nonneg(body, "target_quantity")
    expected_version = as_int_nonneg(body, "expected_service_version")
    s = find(db.services, sid, "ERR_SERVICE_NOT_FOUND")
    contract = db.contracts[s["contract_id"]]
    # band 8: utilization gate for DOWNGRADE_SEATS
    if body["rec_type"] == "DOWNGRADE_SEATS":
        util = Decimal(str(compute_utilization(s["active_quantity"],
                                               s["contracted_quantity"])))
        if util > UTILIZATION_THRESHOLD_PCT:
            raise ApiError("ERR_UTILIZATION_ABOVE_THRESHOLD", 422,
                           "Utilization above threshold.")
    # band 10: optimistic concurrency on Service.version
    if expected_version != s["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "Stale service version.")
    projected = compute_projected_savings(s, target_quantity)
    r = base_common({
        "service_id": sid,
        "rec_type": body["rec_type"],
        "target_quantity": target_quantity,
        "projected_savings_cents": projected,
        "realized_savings_cents": 0,
        "status": "PROPOSED",
    })
    db.recommendations[r["id"]] = r
    # supersede prior PROPOSED recommendations on this service
    for other in db.recommendations.values():
        if (other["id"] != r["id"] and other["service_id"] == sid
                and other["status"] == "PROPOSED"):
            other["status"] = "SUPERSEDED"
            touch(other)
    s["utilization_pct"] = compute_utilization(s["active_quantity"],
                                               s["contracted_quantity"])
    touch(s)
    return ok(serialize(r), status=201)


@bp.route("/services/<sid>/recommendations", methods=["GET"])
@guard(core.ALL_ROLES)
def list_service_recommendations(sid):
    find(db.services, sid, "ERR_SERVICE_NOT_FOUND")
    status_filter = request.args.get("status")
    items = [r for r in db.recommendations.values() if r["service_id"] == sid]
    if status_filter:
        items = [r for r in items if r["status"] == status_filter]
    items = ordered(items)
    page, meta = paginate(items)
    return ok_list([serialize(r) for r in page], meta)


# ---------------------------------------------------------------------------
# Recommendation actions
# ---------------------------------------------------------------------------
@bp.route("/recommendations/<rid>/implement", methods=["POST"])
@guard(["FinanceApprover"])
def implement_recommendation(rid):
    r = find(db.recommendations, rid, "ERR_RECOMMENDATION_NOT_FOUND")
    s = db.services.get(r["service_id"])
    if r["status"] != "PROPOSED" or s is None or s["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Recommendation not PROPOSED or service not ACTIVE.")
    contract = db.contracts[s["contract_id"]]
    # 1) compute realized savings (chronological)
    realized = compute_realized_savings(s, contract, r["target_quantity"], db.clock_dt)
    r["realized_savings_cents"] = realized
    # 2) apply change to service
    if r["rec_type"] == "DOWNGRADE_SEATS":
        s["contracted_quantity"] = r["target_quantity"]
        s["status"] = "RIGHTSIZED"
    elif r["rec_type"] == "TERMINATE":
        s["contracted_quantity"] = 0
        s["status"] = "RETIRED"
    # SANCTION: no quantity/status change
    s["utilization_pct"] = compute_utilization(s["active_quantity"],
                                               s["contracted_quantity"])
    touch(s)
    # 3) recompute parent contract committed cost (cascade -> version bump)
    recompute_contract_committed(contract)
    touch(contract)
    r["status"] = "IMPLEMENTED"
    touch(r)
    return ok(serialize(r))


@bp.route("/recommendations/<rid>/reject", methods=["POST"])
@guard(["FinanceApprover"])
def reject_recommendation(rid):
    r = find(db.recommendations, rid, "ERR_RECOMMENDATION_NOT_FOUND")
    if r["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE", 409, "Recommendation not PROPOSED.")
    r["status"] = "REJECTED"
    touch(r)
    return ok(serialize(r))
