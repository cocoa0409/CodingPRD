"""Markets, Subcontractors, Coverages, Customers, Properties."""
from flask import Blueprint, request
import db
from errors import err
from middleware import require_role, get_body, require_fields, check_enum, paginate_args
from response import success_obj, success_list
from services.common import (
    base_record, touch, get_or_404, serialize_market, serialize_subcontractor,
    serialize_coverage, serialize_customer, serialize_property,
    find_accepted_or_arrived_assignment,
)
from services import dispatch as dispatch_svc

bp = Blueprint("network", __name__)


# ---------------- Markets ----------------

@bp.route("/markets", methods=["POST"])
def create_market():
    require_role("PlatformAdmin")
    body = get_body()
    require_fields(body, [
        "name", "code", "sla_minutes_p1", "sla_minutes_p2", "sla_minutes_p3",
        "permit_required", "notification_required", "notification_deadline_hours",
        "late_notification_fee_cents", "board_rate_per_sheet_cents",
        "tarp_rate_per_sqft_cents", "fence_rate_per_linear_ft_cents",
        "patrol_visit_fee_cents", "temp_power_daily_rate_cents",
        "temp_lighting_daily_rate_cents", "generator_pool_units",
        "removal_flat_fee_cents",
    ])
    # unique code
    for m in db.markets.values():
        if m["code"] == body["code"]:
            raise err("ERR_INVALID_REQUEST", "Market code already exists: %s" % body["code"])
    rec = base_record()
    rec.update({k: body[k] for k in [
        "name", "code", "sla_minutes_p1", "sla_minutes_p2", "sla_minutes_p3",
        "permit_required", "notification_required", "notification_deadline_hours",
        "late_notification_fee_cents", "board_rate_per_sheet_cents",
        "tarp_rate_per_sqft_cents", "fence_rate_per_linear_ft_cents",
        "patrol_visit_fee_cents", "temp_power_daily_rate_cents",
        "temp_lighting_daily_rate_cents", "generator_pool_units",
        "removal_flat_fee_cents",
    ]})
    db.markets[rec["id"]] = rec
    return success_obj(serialize_market(rec), 201)


@bp.route("/markets/<mid>", methods=["GET"])
def get_market(mid):
    require_role("PlatformAdmin", "Dispatcher", "Customer", "Subcontractor")
    rec = get_or_404(db.markets, mid, "Market")
    return success_obj(serialize_market(rec))


# ---------------- Subcontractors ----------------

@bp.route("/subcontractors", methods=["POST"])
def create_subcontractor():
    require_role("PlatformAdmin")
    body = get_body()
    require_fields(body, ["legal_name"])
    rec = base_record()
    rec.update({
        "legal_name": body["legal_name"],
        "status": "ACTIVE",
        "completed_job_count": 0,
        "breached_job_count": 0,
        "expired_offer_count": 0,
        "active_assignment_count": 0,
    })
    db.subcontractors[rec["id"]] = rec
    return success_obj(serialize_subcontractor(rec), 201)


@bp.route("/subcontractors/<sid>", methods=["GET"])
def get_subcontractor(sid):
    require_role("PlatformAdmin", "Dispatcher", "Customer", "Subcontractor")
    rec = get_or_404(db.subcontractors, sid, "Subcontractor")
    return success_obj(serialize_subcontractor(rec))


@bp.route("/subcontractors/<sid>", methods=["PATCH"])
def patch_subcontractor(sid):
    require_role("PlatformAdmin")
    rec = get_or_404(db.subcontractors, sid, "Subcontractor")
    body = get_body()
    new_status = body.get("status")
    if new_status is not None:
        check_enum(new_status, {"ACTIVE", "SUSPENDED"}, "status")
        if new_status != rec["status"]:
            rec["status"] = new_status
            touch(rec)
            if new_status == "SUSPENDED":
                # cascade: cancel own assignments in OFFERED/ACCEPTED/ARRIVED
                affected_jobs = set()
                for a in list(db.assignments.values()):
                    if a["subcontractor_id"] == sid and a["status"] in ("OFFERED", "ACCEPTED", "ARRIVED"):
                        was_accepted = a["status"] in ("ACCEPTED", "ARRIVED")
                        a["status"] = "CANCELLED"
                        touch(a)
                        affected_jobs.add(a["job_id"])
                        if was_accepted:
                            # active count recomputed
                            pass
                # coverage rows -> SUSPENDED
                for cov in db.coverages.values():
                    if cov["subcontractor_id"] == sid:
                        if cov["status"] != "SUSPENDED":
                            cov["status"] = "SUSPENDED"
                            touch(cov)
                # recompute active count once
                from services.common import recompute_active_assignment_count
                recompute_active_assignment_count(sid)
                # each cancellation cascades to its job
                for jid in affected_jobs:
                    job = db.jobs.get(jid)
                    if job is not None:
                        dispatch_svc.run_reoffer_cascade(job)
            else:
                # ACTIVE: coverage rows -> ACTIVE
                for cov in db.coverages.values():
                    if cov["subcontractor_id"] == sid:
                        if cov["status"] != "ACTIVE":
                            cov["status"] = "ACTIVE"
                            touch(cov)
    return success_obj(serialize_subcontractor(rec))


# ---------------- Coverages ----------------

@bp.route("/coverages", methods=["POST"])
def create_coverage():
    require_role("PlatformAdmin")
    body = get_body()
    require_fields(body, ["subcontractor_id", "market_id", "max_concurrent_jobs", "rank"])
    sub = db.subcontractors.get(body["subcontractor_id"])
    if sub is None:
        raise err("ERR_NOT_FOUND", "Subcontractor not found")
    market = db.markets.get(body["market_id"])
    if market is None:
        raise err("ERR_NOT_FOUND", "Market not found")
    for c in db.coverages.values():
        if c["subcontractor_id"] == body["subcontractor_id"] and c["market_id"] == body["market_id"]:
            raise err("ERR_DUPLICATE_COVERAGE", "Coverage already exists for this pair")
    rec = base_record()
    rec.update({
        "subcontractor_id": body["subcontractor_id"],
        "market_id": body["market_id"],
        "max_concurrent_jobs": body["max_concurrent_jobs"],
        "rank": body["rank"],
        "status": sub["status"],
    })
    db.coverages[rec["id"]] = rec
    return success_obj(serialize_coverage(rec), 201)


@bp.route("/coverages/<cid>", methods=["GET"])
def get_coverage(cid):
    require_role("PlatformAdmin", "Dispatcher", "Customer", "Subcontractor")
    rec = get_or_404(db.coverages, cid, "Coverage")
    return success_obj(serialize_coverage(rec))


@bp.route("/coverages", methods=["GET"])
def list_coverages():
    require_role("PlatformAdmin", "Dispatcher", "Customer", "Subcontractor")
    limit, offset = paginate_args()
    items = list(db.coverages.values())
    sid = request.args.get("subcontractor_id")
    mid = request.args.get("market_id")
    if sid:
        items = [c for c in items if c["subcontractor_id"] == sid]
    if mid:
        items = [c for c in items if c["market_id"] == mid]
    items.sort(key=lambda c: c["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_coverage(c) for c in page], total, limit, offset)


# ---------------- Customers ----------------

@bp.route("/customers", methods=["POST"])
def create_customer():
    require_role("PlatformAdmin")
    body = get_body()
    require_fields(body, ["full_name", "email", "kind"])
    check_enum(body["kind"], {"OWNER", "ADJUSTER"}, "kind")
    rec = base_record()
    rec.update({
        "full_name": body["full_name"],
        "email": body["email"],
        "kind": body["kind"],
    })
    db.customers[rec["id"]] = rec
    return success_obj(serialize_customer(rec), 201)


@bp.route("/customers/<cid>", methods=["GET"])
def get_customer(cid):
    require_role("PlatformAdmin", "Dispatcher", "Customer", "Subcontractor")
    rec = get_or_404(db.customers, cid, "Customer")
    return success_obj(serialize_customer(rec))


# ---------------- Properties ----------------

@bp.route("/properties", methods=["POST"])
def create_property():
    require_role("PlatformAdmin")
    body = get_body()
    require_fields(body, ["customer_id", "market_id", "address_line", "wind_zone"])
    check_enum(body["wind_zone"], {"LOW", "HIGH"}, "wind_zone")
    if body["customer_id"] not in db.customers:
        raise err("ERR_NOT_FOUND", "Customer not found")
    if body["market_id"] not in db.markets:
        raise err("ERR_NOT_FOUND", "Market not found")
    rec = base_record()
    rec.update({
        "customer_id": body["customer_id"],
        "market_id": body["market_id"],
        "address_line": body["address_line"],
        "wind_zone": body["wind_zone"],
    })
    db.properties[rec["id"]] = rec
    return success_obj(serialize_property(rec), 201)


@bp.route("/properties/<pid>", methods=["GET"])
def get_property(pid):
    require_role("PlatformAdmin", "Dispatcher", "Customer", "Subcontractor")
    rec = get_or_404(db.properties, pid, "Property")
    return success_obj(serialize_property(rec))


@bp.route("/properties", methods=["GET"])
def list_properties():
    require_role("PlatformAdmin", "Dispatcher", "Customer", "Subcontractor")
    limit, offset = paginate_args()
    items = list(db.properties.values())
    cid = request.args.get("customer_id")
    mid = request.args.get("market_id")
    if cid:
        items = [p for p in items if p["customer_id"] == cid]
    if mid:
        items = [p for p in items if p["market_id"] == mid]
    items.sort(key=lambda p: p["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_property(p) for p in page], total, limit, offset)
