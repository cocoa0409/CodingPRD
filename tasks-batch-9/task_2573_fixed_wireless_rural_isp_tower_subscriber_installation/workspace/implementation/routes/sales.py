"""Service plans, premise qualification, reservations and accounts."""
from decimal import Decimal

from flask import Blueprint, g

import calc
import db
import domain
import flows
import middleware as mw
import resolve
import response
from errors import ApiError
from util import add_days, dec, q1

bp = Blueprint("sales", __name__)

SLA_CREDIT_METHODS = ("SLA_SHORTFALL", "PER_INCIDENT")
EQUIPMENT_POLICIES = ("RENTAL_ONLY", "PURCHASE_ONLY", "RENTAL_OR_PURCHASE")
EQUIPMENT_MODES = ("RENTAL", "PURCHASE")
OBSTRUCTION_CLASSES = ("CLEAR", "PARTIAL", "BLOCKED")
SERVICE_STATUSES = ("PENDING_INSTALL", "ACTIVE", "SUSPENDED", "CANCELLED")

SUBSCRIBER_TRANSITIONS = {
    ("ACTIVE", "SUSPENDED"),
    ("SUSPENDED", "ACTIVE"),
    ("PENDING_INSTALL", "CANCELLED"),
    ("ACTIVE", "CANCELLED"),
    ("SUSPENDED", "CANCELLED"),
}

OCCUPYING_STATUSES = ("PENDING_INSTALL", "ACTIVE", "SUSPENDED")


def own(subscriber):
    """Rung 7 -- a Subscriber caller addresses only their own account."""
    if mw.is_subscriber_caller() and g.user_id != subscriber["id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    return subscriber


def policy_permits(policy, mode):
    if policy == "RENTAL_OR_PURCHASE":
        return True
    if policy == "RENTAL_ONLY":
        return mode == "RENTAL"
    if policy == "PURCHASE_ONLY":
        return mode == "PURCHASE"
    return False


# ---------------------------------------------------------------------------
# service plans
# ---------------------------------------------------------------------------
@bp.post("/service-plans")
def create_plan():
    mw.require(mw.ROLE_CAPACITY_PLANNER)
    payload = mw.body()
    tier_code = mw.v_str(payload, "tier_code")
    downstream = mw.v_int(payload, "downstream_mbps", minimum=1)
    upstream = mw.v_int(payload, "upstream_mbps", minimum=1)
    price = mw.v_int(payload, "monthly_price_cents", minimum=0)
    soft_cap = mw.v_num(payload, "soft_cap_gb", exclusive_minimum="0", places=1)
    factor = mw.v_num(payload, "deprioritization_factor", minimum="0.05",
                      maximum="1.0", places=2)
    uptime = mw.v_num(payload, "sla_uptime_pct", minimum="90.0", maximum="100.0", places=3)
    method = mw.v_enum(payload, "sla_credit_method", SLA_CREDIT_METHODS)
    policy = mw.v_enum(payload, "equipment_policy", EQUIPMENT_POLICIES)

    for plan in db.service_plans.values():
        if plan["tier_code"] == tier_code:
            raise ApiError("ERR_DUPLICATE_TIER_CODE")

    plan = db.base_record(
        tier_code=tier_code,
        downstream_mbps=downstream,
        upstream_mbps=upstream,
        monthly_price_cents=price,
        soft_cap_gb=soft_cap,
        deprioritization_factor=factor,
        sla_uptime_pct=uptime,
        sla_credit_method=method,
        equipment_policy=policy,
    )
    db.service_plans[plan["id"]] = plan
    return response.created(domain.plan_view(plan))


@bp.get("/service-plans/<plan_id>")
def read_plan(plan_id):
    mw.require(mw.ROLE_NETWORK_ENGINEER, mw.ROLE_CAPACITY_PLANNER, mw.ROLE_SALES_AGENT,
               mw.ROLE_BILLING_ADMIN, mw.ROLE_FINANCE_APPROVER)
    plan = resolve.plan(plan_id)
    return response.object_response(domain.plan_view(plan))


# ---------------------------------------------------------------------------
# serviceability requests
# ---------------------------------------------------------------------------
@bp.post("/serviceability-requests")
def create_request():
    mw.require(mw.ROLE_SALES_AGENT)
    payload = mw.body()
    tower_id = mw.v_ref(payload, "candidate_tower_id")
    plan_id = mw.v_ref(payload, "requested_plan_id")
    contact_name = mw.v_str(payload, "contact_name")
    latitude = mw.v_num(payload, "premise_latitude", minimum="-90.0", maximum="90.0", places=4)
    longitude = mw.v_num(payload, "premise_longitude", minimum="-180.0", maximum="180.0",
                         places=4)
    ground = mw.v_num(payload, "premise_ground_elevation_m", minimum="0.0",
                      maximum="4500.0", places=1)
    roof = mw.v_num(payload, "roof_height_m", minimum="0.0", maximum="20.0", places=1)
    trees = mw.v_num(payload, "declared_tree_line_height_m", minimum="0.0",
                     maximum="60.0", places=1)
    obstruction = mw.v_enum(payload, "obstruction_class", OBSTRUCTION_CLASSES)
    distance = mw.v_num(payload, "path_distance_km", exclusive_minimum="0", places=1)

    tower = resolve.tower(tower_id)
    plan = resolve.plan(plan_id)

    record = db.base_record(
        candidate_tower_id=tower["id"],
        requested_plan_id=plan["id"],
        contact_name=contact_name,
        premise_latitude=latitude,
        premise_longitude=longitude,
        premise_ground_elevation_m=ground,
        roof_height_m=roof,
        declared_tree_line_height_m=trees,
        obstruction_class=obstruction,
        path_distance_km=distance,
        intake_sequence=db.next_intake_sequence(),
        qualified_sector_id=None,
        desktop_los_margin_m=None,
        desktop_required_mast_height_m=None,
        desktop_mounting_type=None,
        status="EVALUATING",
        denial_reason=None,
        qualification_expires_at=None,
    )
    db.serviceability_requests[record["id"]] = record

    def deny(reason):
        record["status"] = "DENIED"
        record["denial_reason"] = reason
        record["qualified_sector_id"] = None
        record["qualification_expires_at"] = None
        return response.created(domain.request_view(record))

    # PRD 3.5 -- the five refusals, in pinned order; the first that holds wins
    if distance > calc.MAX_LINK_DISTANCE_KM:
        return deny("LINK_DISTANCE_EXCEEDED")
    if obstruction == "BLOCKED":
        return deny("OBSTRUCTION_BLOCKED")

    geometry = calc.los_geometry(
        tower["ground_elevation_m"], tower["antenna_agl_m"], ground, trees, roof,
        obstruction, distance,
    )
    record["desktop_los_margin_m"] = geometry["los_margin_m"]
    if geometry["los_margin_m"] < 0:
        return deny("NO_LINE_OF_SIGHT")

    record["desktop_required_mast_height_m"] = geometry["required_mast_height_m"]
    if geometry["required_mast_height_m"] > calc.MAX_MAST_HEIGHT_M:
        return deny("MAST_LIMIT_EXCEEDED")

    record["desktop_mounting_type"] = geometry["mounting_type"]
    if not [s for s in domain.tower_sectors(tower["id"]) if s["status"] == "ACTIVE"]:
        return deny("NO_ACTIVE_SECTOR")

    sector, outcome = flows.select_sector(tower, plan)
    if outcome == "QUALIFIED":
        record["status"] = "QUALIFIED"
        record["qualified_sector_id"] = sector["id"]
        record["qualification_expires_at"] = add_days(db.now(),
                                                      calc.QUALIFICATION_VALID_DAYS)
    elif outcome == "CAPACITY_DEFERRED":
        record["status"] = "CAPACITY_DEFERRED"
        record["qualification_expires_at"] = add_days(db.now(),
                                                      calc.QUALIFICATION_VALID_DAYS)
    else:
        return deny("NO_ACTIVE_SECTOR")
    return response.created(domain.request_view(record))


@bp.get("/serviceability-requests/<request_id>")
def read_request(request_id):
    mw.require(mw.ROLE_NETWORK_ENGINEER, mw.ROLE_CAPACITY_PLANNER, mw.ROLE_SALES_AGENT,
               mw.ROLE_FIELD_TECH)
    record = resolve.request_(request_id)
    return response.object_response(domain.request_view(record))


@bp.get("/serviceability-requests")
def list_requests():
    mw.require(mw.ROLE_NETWORK_ENGINEER, mw.ROLE_CAPACITY_PLANNER, mw.ROLE_SALES_AGENT)
    limit, offset = mw.pagination()
    spec = mw.filters("candidate_tower_id", "qualified_sector_id", "requested_plan_id",
                      "status")
    records = mw.apply_filters(db.ordered(list(db.serviceability_requests.values())), spec)
    page, total = mw.paginate(records, limit, offset)
    return response.list_response([domain.request_view(r) for r in page],
                                  limit, offset, total)


# ---------------------------------------------------------------------------
# capacity holds
# ---------------------------------------------------------------------------
def _guard_qualified(record):
    if record["status"] != "QUALIFIED":
        raise ApiError("ERR_REQUEST_NOT_QUALIFIED")
    expires = record.get("qualification_expires_at")
    if expires is None or db.now() >= expires:
        raise ApiError("ERR_QUALIFICATION_EXPIRED")


def _guard_capacity(sector, needed):
    ledger = domain.sector_ledger(sector)
    if ledger["capacity_posture"] == calc.POSTURE_HOLD:
        raise ApiError("ERR_SECTOR_CAPACITY_HOLD")
    if ledger["capacity_posture"] == calc.POSTURE_FROZEN:
        raise ApiError("ERR_SECTOR_FROZEN")
    if ledger["remaining_allowance_mbps"] < int(needed):
        raise ApiError("ERR_INSUFFICIENT_SECTOR_CAPACITY")
    return ledger


@bp.post("/capacity-holds")
def create_hold():
    mw.require(mw.ROLE_SALES_AGENT, mw.ROLE_CAPACITY_PLANNER)
    payload = mw.body()
    request_id = mw.v_ref(payload, "serviceability_request_id")
    expected_version = mw.v_int(payload, "expected_sector_version")
    hold_days = mw.v_int(payload, "hold_days", required=False,
                         default=calc.DEFAULT_HOLD_DAYS,
                         minimum=calc.MIN_HOLD_DAYS, maximum=calc.MAX_HOLD_DAYS)

    record = resolve.request_(request_id)
    _guard_qualified(record)

    sector = db.sectors.get(record["qualified_sector_id"])
    if sector is None:
        raise ApiError("ERR_SECTOR_NOT_FOUND")
    if int(expected_version) != int(sector["version"]):
        raise ApiError("ERR_STALE_SECTOR_VERSION")

    plan = db.service_plans.get(record["requested_plan_id"])
    if plan is None:
        raise ApiError("ERR_PLAN_NOT_FOUND")
    _guard_capacity(sector, plan["downstream_mbps"])

    tracker = flows.SectorTracker()
    tracker.watch(sector)
    hold = flows.mint_hold(record, sector, plan, hold_days, "DIRECT")
    tracker.settle()
    return response.created(domain.hold_view(hold))


@bp.get("/capacity-holds/<hold_id>")
def read_hold(hold_id):
    mw.require(mw.ROLE_NETWORK_ENGINEER, mw.ROLE_CAPACITY_PLANNER, mw.ROLE_SALES_AGENT)
    hold = resolve.hold(hold_id)
    return response.object_response(domain.hold_view(hold))


@bp.get("/capacity-holds")
def list_holds():
    mw.require(mw.ROLE_NETWORK_ENGINEER, mw.ROLE_CAPACITY_PLANNER, mw.ROLE_SALES_AGENT)
    limit, offset = mw.pagination()
    spec = mw.filters("sector_id", "serviceability_request_id", "status", "origin")
    records = mw.apply_filters(db.ordered(list(db.capacity_holds.values())), spec)
    page, total = mw.paginate(records, limit, offset)
    return response.list_response([domain.hold_view(h) for h in page],
                                  limit, offset, total)


@bp.post("/capacity-holds/<hold_id>/release")
def release_hold_endpoint(hold_id):
    mw.require(mw.ROLE_CAPACITY_PLANNER)
    payload = mw.body()
    mw.v_str(payload, "note", required=False)
    hold = resolve.hold(hold_id)
    if hold["status"] != "HELD":
        raise ApiError("ERR_HOLD_NOT_HELD")

    tracker = flows.SectorTracker()
    sector = db.sectors.get(hold["sector_id"])
    tracker.watch(sector)
    flows.release_hold(hold, "MANUAL", tracker)
    flows.promote_deferred(sector, tracker)
    tracker.settle()
    return response.object_response(domain.hold_view(hold))


# ---------------------------------------------------------------------------
# subscribers
# ---------------------------------------------------------------------------
@bp.post("/subscribers")
def create_subscriber():
    mw.require(mw.ROLE_SALES_AGENT)
    payload = mw.body()
    request_id = mw.v_ref(payload, "serviceability_request_id")
    plan_id = mw.v_ref(payload, "service_plan_id")
    billing_email = mw.v_str(payload, "billing_email")
    equipment_mode = mw.v_enum(payload, "equipment_mode", EQUIPMENT_MODES)

    record = resolve.request_(request_id)
    plan = resolve.plan(plan_id)

    _guard_qualified(record)
    hold = None
    for candidate in db.ordered(list(db.capacity_holds.values())):
        if candidate["serviceability_request_id"] == record["id"] \
                and candidate["status"] == "HELD":
            hold = candidate
            break
    if hold is None:
        raise ApiError("ERR_HOLD_NOT_HELD")

    if plan["id"] != record["requested_plan_id"]:
        raise ApiError("ERR_PLAN_MISMATCH")
    if not policy_permits(plan["equipment_policy"], equipment_mode):
        raise ApiError("ERR_PLAN_MISMATCH")

    sector = db.sectors.get(record["qualified_sector_id"])
    tracker = flows.SectorTracker()
    tracker.watch(sector)

    subscriber = db.base_record(
        serviceability_request_id=record["id"],
        service_plan_id=plan["id"],
        sector_id=record["qualified_sector_id"],
        account_number=db.next_account_number(),
        billing_email=billing_email,
        equipment_mode=equipment_mode,
        service_status="PENDING_INSTALL",
        usage_priority="STANDARD",
        cycle_start_date=None,
        consecutive_breach_cycles=0,
        sticky_deprioritization_active=False,
        deprioritized_at=None,
        service_start_date=None,
        cancelled_at=None,
    )
    db.subscribers[subscriber["id"]] = subscriber

    record["status"] = "CONSUMED"
    db.touch(record)
    hold["status"] = "CONSUMED"
    db.touch(hold)

    assignment = db.base_record(
        subscriber_id=subscriber["id"],
        acquisition_mode=equipment_mode,
        radio_serial=None,
        status="ASSIGNED",
        monthly_rental_cents=(calc.RENTAL_MONTHLY_CENTS if equipment_mode == "RENTAL" else 0),
        purchase_price_cents=(calc.PURCHASE_PRICE_CENTS if equipment_mode == "PURCHASE" else 0),
        replacement_cost_cents=calc.REPLACEMENT_COST_CENTS,
        deployed_at=None,
        return_due_at=None,
        returned_at=None,
        return_condition=None,
        months_in_service=0,
        settlement_cents=0,
        settlement_basis=None,
    )
    db.equipment_assignments[assignment["id"]] = assignment

    tracker.mark(sector)
    tracker.settle()
    return response.created(domain.subscriber_view(subscriber))


@bp.get("/subscribers/<subscriber_id>")
def read_subscriber(subscriber_id):
    mw.require(*mw.ALL_ROLES)
    subscriber = own(resolve.subscriber(subscriber_id))
    return response.object_response(domain.subscriber_view(subscriber))


@bp.get("/subscribers")
def list_subscribers():
    mw.require(mw.ROLE_NETWORK_ENGINEER, mw.ROLE_CAPACITY_PLANNER, mw.ROLE_SALES_AGENT,
               mw.ROLE_BILLING_ADMIN, mw.ROLE_FINANCE_APPROVER)
    limit, offset = mw.pagination()
    spec = mw.filters("sector_id", "serviceability_request_id", "service_plan_id",
                      "service_status", "usage_priority")
    records = mw.apply_filters(db.ordered(list(db.subscribers.values())), spec)
    page, total = mw.paginate(records, limit, offset)
    return response.list_response([domain.subscriber_view(s) for s in page],
                                  limit, offset, total)


@bp.post("/subscribers/<subscriber_id>/plan-changes")
def change_plan(subscriber_id):
    mw.require(mw.ROLE_SALES_AGENT, mw.ROLE_BILLING_ADMIN)
    payload = mw.body()
    plan_id = mw.v_ref(payload, "service_plan_id")
    expected_version = mw.v_int(payload, "expected_subscriber_version")

    subscriber = resolve.subscriber(subscriber_id)
    plan = resolve.plan(plan_id)

    if int(expected_version) != int(subscriber["version"]):
        raise ApiError("ERR_STALE_SUBSCRIBER_VERSION")
    if not policy_permits(plan["equipment_policy"], subscriber["equipment_mode"]):
        raise ApiError("ERR_PLAN_MISMATCH")

    previous = db.service_plans.get(subscriber["service_plan_id"]) or {}
    old_downstream = int(previous.get("downstream_mbps", 0))
    delta = int(plan["downstream_mbps"]) - old_downstream

    sector = db.sectors.get(subscriber["sector_id"])
    if sector is not None and delta > 0 \
            and subscriber["service_status"] in OCCUPYING_STATUSES:
        ledger = domain.sector_ledger(sector)
        if delta > ledger["remaining_allowance_mbps"]:
            raise ApiError("ERR_INSUFFICIENT_SECTOR_CAPACITY")

    tracker = flows.SectorTracker()
    tracker.watch(sector)
    subscriber["service_plan_id"] = plan["id"]
    flows.refresh_usage_posture(subscriber, plan)
    db.touch(subscriber)
    tracker.settle()
    return response.object_response(domain.subscriber_view(subscriber))


@bp.post("/subscribers/<subscriber_id>/status-changes")
def change_subscriber_status(subscriber_id):
    mw.require(mw.ROLE_BILLING_ADMIN)
    payload = mw.body()
    to_status = mw.v_enum(payload, "to_status", SERVICE_STATUSES)
    mw.v_str(payload, "reason")

    subscriber = resolve.subscriber(subscriber_id)
    previous = subscriber["service_status"]
    if (previous, to_status) not in SUBSCRIBER_TRANSITIONS:
        raise ApiError("ERR_SUBSCRIBER_NOT_ACTIVE")

    tracker = flows.SectorTracker()
    tracker.watch(db.sectors.get(subscriber["sector_id"]))
    subscriber["service_status"] = to_status
    if to_status == "CANCELLED":
        flows.cascade_subscriber_cancelled(subscriber, previous, tracker)
    db.touch(subscriber)
    tracker.settle()
    return response.object_response(domain.subscriber_view(subscriber))


# ---------------------------------------------------------------------------
# metered usage and cycle close
# ---------------------------------------------------------------------------
@bp.post("/subscribers/<subscriber_id>/usage-records")
def ingest_usage(subscriber_id):
    mw.require(mw.ROLE_BILLING_ADMIN)
    payload = mw.body()
    usage_date = mw.v_date(payload, "usage_date")
    downstream = mw.v_num(payload, "downstream_gb", minimum="0.0", places=1)
    upstream = mw.v_num(payload, "upstream_gb", minimum="0.0", places=1)

    subscriber = resolve.subscriber(subscriber_id)

    for existing in domain.subscriber_usage_records(subscriber["id"]):
        if existing["usage_date"] == usage_date:
            raise ApiError("ERR_DUPLICATE_USAGE_RECORD")

    if not calc.in_window(usage_date, subscriber.get("cycle_start_date")):
        raise ApiError("ERR_USAGE_DATE_OUT_OF_CYCLE")

    record = {
        "id": db.new_id(),
        "created_at": db.now(),
        "_seq": db.next_seq(),
        "subscriber_id": subscriber["id"],
        "usage_date": usage_date,
        "downstream_gb": downstream,
        "upstream_gb": upstream,
        "total_gb": q1(downstream + upstream),
        "ingest_sequence": db.next_ingest_sequence(),
    }
    db.usage_records[record["id"]] = record

    plan = db.service_plans.get(subscriber["service_plan_id"])
    if plan is not None:
        flows.refresh_usage_posture(subscriber, plan)
    db.touch(subscriber)
    return response.created(domain.usage_record_view(record))


@bp.get("/subscribers/<subscriber_id>/usage-records")
def list_usage(subscriber_id):
    mw.require(mw.ROLE_BILLING_ADMIN, mw.ROLE_FINANCE_APPROVER, mw.ROLE_CAPACITY_PLANNER,
               mw.ROLE_SUBSCRIBER)
    limit, offset = mw.pagination()
    subscriber = own(resolve.subscriber(subscriber_id))
    records = db.ordered(domain.subscriber_usage_records(subscriber["id"]))
    page, total = mw.paginate(records, limit, offset)
    return response.list_response([domain.usage_record_view(r) for r in page],
                                  limit, offset, total)


@bp.post("/subscribers/<subscriber_id>/cycle-close")
def close_cycle(subscriber_id):
    mw.require(mw.ROLE_BILLING_ADMIN)
    mw.body()
    subscriber = resolve.subscriber(subscriber_id)
    plan = db.service_plans.get(subscriber["service_plan_id"])
    if plan is None:
        raise ApiError("ERR_PLAN_NOT_FOUND")

    # judge the closing cycle, then roll the window, then re-derive the posture
    closing_usage = domain.subscriber_cycle_usage_gb(subscriber)
    breached = closing_usage > dec(plan["soft_cap_gb"])
    if breached:
        subscriber["consecutive_breach_cycles"] = \
            int(subscriber["consecutive_breach_cycles"]) + 1
    else:
        subscriber["consecutive_breach_cycles"] = 0
    subscriber["sticky_deprioritization_active"] = (
        int(subscriber["consecutive_breach_cycles"]) >= calc.STICKY_BREACH_CYCLES)
    if subscriber.get("cycle_start_date") is not None:
        subscriber["cycle_start_date"] = add_days(subscriber["cycle_start_date"],
                                                 calc.CYCLE_DAYS)
    flows.refresh_usage_posture(subscriber, plan)
    db.touch(subscriber)
    return response.object_response(domain.subscriber_view(subscriber))


@bp.get("/subscribers/<subscriber_id>/install-work-orders")
def list_subscriber_work_orders(subscriber_id):
    mw.require(mw.ROLE_NETWORK_ENGINEER, mw.ROLE_SALES_AGENT, mw.ROLE_FIELD_TECH,
               mw.ROLE_BILLING_ADMIN, mw.ROLE_SUBSCRIBER)
    limit, offset = mw.pagination()
    subscriber = own(resolve.subscriber(subscriber_id))
    records = mw.apply_filters(domain.subscriber_work_orders(subscriber["id"]),
                               mw.filters("status"))
    page, total = mw.paginate(records, limit, offset)
    return response.list_response([domain.work_order_view(w) for w in page],
                                  limit, offset, total)


@bp.get("/subscribers/<subscriber_id>/equipment-assignments")
def list_subscriber_assignments(subscriber_id):
    mw.require(mw.ROLE_NETWORK_ENGINEER, mw.ROLE_FIELD_TECH, mw.ROLE_BILLING_ADMIN,
               mw.ROLE_FINANCE_APPROVER, mw.ROLE_SUBSCRIBER)
    limit, offset = mw.pagination()
    subscriber = own(resolve.subscriber(subscriber_id))
    records = mw.apply_filters(domain.subscriber_assignments(subscriber["id"]),
                               mw.filters("status"))
    page, total = mw.paginate(records, limit, offset)
    return response.list_response([domain.assignment_view(a) for a in page],
                                  limit, offset, total)
