"""Routes: customers, contracts, containers (PRD 3.1, 3.2, 3.3)."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

import calc
import serialize
from db import parse_date, parse_dt, store
from errors import err
from helpers import (
    CONTRACT_ACTIVE_ERA,
    CONTRACT_TERMINAL,
    cc_check,
    fresh_complaint,
    fresh_contract,
    get_complaint,
    get_container,
    get_contract,
    get_customer,
    get_body,
    opt_num,
    opt_int,
    opt_str,
    paginate,
    req_bool,
    req_date,
    req_enum,
    req_int,
    req_num,
    req_str,
    require_roles,
    sorted_items,
)
from response import success

bp = Blueprint("customers", __name__)

CUSTOMER_STATUSES = {"PROSPECT", "ACTIVE", "SUSPENDED", "TERMINATED"}
PRICING_MODES = {"REBATE", "SERVICE_FEE"}


def _overlaps(s1, e1, s2, e2):
    """Half-open [s, e) interval overlap; adjacency is allowed (PRD 3.2)."""
    return s1 < e2 and s2 < e1


def _sibling_contracts(customer_id, exclude_id=None):
    out = []
    for c in store.contracts.values():
        if c["customer_id"] != customer_id or c["id"] == exclude_id:
            continue
        fresh_contract(c)  # lazy expiry evaluated on access (PRD 2.4)
        out.append(c)
    return out


def _check_term_overlap(customer_id, term_start, term_end, exclude_id=None):
    for other in _sibling_contracts(customer_id, exclude_id=exclude_id):
        if other["status"] in CONTRACT_TERMINAL:
            continue
        if _overlaps(term_start, term_end, other["term_start"], other["term_end"]):
            raise err(
                "ERR_CONTRACT_TERM_OVERLAP",
                "Term window overlaps contract %s" % other["id"],
            )


# ---------------------------------------------------------------------------
# Customers (PRD 3.1)
# ---------------------------------------------------------------------------
@bp.route("/api/customers", methods=["POST"])
@require_roles("SystemAdmin", "FieldOpsManager")
def create_customer():
    body = get_body()
    rec = {
        "id": store.new_id(),
        "name": req_str(body, "name"),
        "site_address": req_str(body, "site_address"),
        "site_max_container_gal": req_int(body, "site_max_container_gal"),
        "status": "PROSPECT",
    }
    store.stamp(rec)
    store.customers[rec["id"]] = rec
    return success(serialize.customer(rec), code=201)


@bp.route("/api/customers", methods=["GET"])
@require_roles("SystemAdmin", "FieldOpsManager", "RouteDispatcher", "BillingAnalyst", "PlantOperator")
def list_customers():
    items = sorted_items(store.customers.values())
    status = request.args.get("status")
    if status is not None:
        if status not in CUSTOMER_STATUSES:
            raise err("ERR_VALIDATION", "Query parameter 'status' must be one of %s" % sorted(CUSTOMER_STATUSES))
        items = [c for c in items if c["status"] == status]
    page, meta = paginate(items)
    return success([serialize.customer(c) for c in page], response_type="array", pagination=meta)


@bp.route("/api/customers/<cid>", methods=["GET"])
@require_roles("SystemAdmin", "FieldOpsManager", "RouteDispatcher", "BillingAnalyst", "PlantOperator", "CustomerContact")
def get_one_customer(cid):
    cc_check(cid)  # CustomerContact restricted to its own id (PRD 2.1)
    return success(serialize.customer(get_customer(cid)))


@bp.route("/api/customers/<cid>/suspend", methods=["POST"])
@require_roles("SystemAdmin", "FieldOpsManager")
def suspend_customer(cid):
    rec = get_customer(cid)
    body = get_body()
    opt_str(body, "reason")
    if rec["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Customer %s is %s; only ACTIVE can be suspended" % (cid, rec["status"]))
    rec["status"] = "SUSPENDED"
    store.bump(rec)
    return success(serialize.customer(rec))


@bp.route("/api/customers/<cid>/reinstate", methods=["POST"])
@require_roles("SystemAdmin", "FieldOpsManager")
def reinstate_customer(cid):
    rec = get_customer(cid)
    if rec["status"] != "SUSPENDED":
        raise err("ERR_INVALID_STATE", "Customer %s is %s; only SUSPENDED can be reinstated" % (cid, rec["status"]))
    rec["status"] = "ACTIVE"
    # missed_pickup_count is recomputed from visit history, never reset (PRD 3.1)
    store.bump(rec)
    return success(serialize.customer(rec))


@bp.route("/api/customers/<cid>/terminate", methods=["POST"])
@require_roles("SystemAdmin", "FieldOpsManager")
def terminate_customer(cid):
    rec = get_customer(cid)
    body = get_body()
    req_str(body, "reason")
    if rec["status"] not in ("ACTIVE", "SUSPENDED"):
        raise err("ERR_INVALID_STATE", "Customer %s is %s; terminate requires ACTIVE or SUSPENDED" % (cid, rec["status"]))
    for c in _sibling_contracts(cid):
        if c["status"] not in CONTRACT_TERMINAL:
            raise err("ERR_INVALID_STATE", "Customer %s still has non-terminal contract %s" % (cid, c["id"]))
    for cont in store.containers.values():
        if cont["customer_id"] == cid and cont["status"] in ("PLACED", "ACTIVE", "LOCKED"):
            cont["status"] = "REMOVED"
            store.bump(cont)
    rec["status"] = "TERMINATED"
    store.bump(rec)
    return success(serialize.customer(rec))


# ---------------------------------------------------------------------------
# Contracts (PRD 3.2)
# ---------------------------------------------------------------------------
@bp.route("/api/customers/<cid>/contracts", methods=["POST"])
@require_roles("SystemAdmin", "FieldOpsManager")
def create_contract(cid):
    get_customer(cid)
    body = get_body()
    pricing_mode = req_enum(body, "pricing_mode", PRICING_MODES)
    index_code = req_str(body, "index_code")
    term_start = req_date(body, "term_start")
    term_end = req_date(body, "term_end")
    rec = {
        "id": store.new_id(),
        "customer_id": cid,
        "pricing_mode": pricing_mode,
        "index_code": index_code,
        "floor_cents_per_gal": opt_num(body, "floor_cents_per_gal", 0),
        "cap_cents_per_gal": opt_num(body, "cap_cents_per_gal", 1000000),
        "service_fee_cents": opt_int(body, "service_fee_cents", 0),
        "overage_threshold_gal": opt_num(body, "overage_threshold_gal", 0),
        "overage_rate_cents_per_gal": opt_num(body, "overage_rate_cents_per_gal", 0),
        "term_start": term_start,
        "term_end": term_end,
        "status": "DRAFT",
        "status_before_renewal": None,
        "offered_term_start": None,
        "offered_term_end": None,
        "activated_at": None,
        "competitor_name": None,
        "poach_offer_cents_per_gal": None,
        "termination_reason": None,
    }
    _check_term_overlap(cid, term_start, term_end)
    store.stamp(rec)
    store.contracts[rec["id"]] = rec
    return success(serialize.contract(rec), code=201)


@bp.route("/api/customers/<cid>/contracts", methods=["GET"])
@require_roles("SystemAdmin", "FieldOpsManager", "BillingAnalyst", "CustomerContact")
def list_customer_contracts(cid):
    cc_check(cid)
    get_customer(cid)
    items = [fresh_contract(c) for c in sorted_items(store.contracts.values()) if c["customer_id"] == cid]
    page, meta = paginate(items)
    return success([serialize.contract(c) for c in page], response_type="array", pagination=meta)


@bp.route("/api/customers/<cid>/containers", methods=["GET"])
@require_roles("SystemAdmin", "FieldOpsManager", "RouteDispatcher", "CustomerContact")
def list_customer_containers(cid):
    cc_check(cid)
    get_customer(cid)
    items = [c for c in sorted_items(store.containers.values()) if c["customer_id"] == cid]
    page, meta = paginate(items)
    return success([serialize.container(c) for c in page], response_type="array", pagination=meta)


@bp.route("/api/customers/<cid>/settlements", methods=["GET"])
@require_roles("SystemAdmin", "FieldOpsManager", "BillingAnalyst", "CustomerContact")
def list_customer_settlements(cid):
    cc_check(cid)
    get_customer(cid)
    items = [s for s in sorted_items(store.settlements.values()) if s["customer_id"] == cid]
    page, meta = paginate(items)
    return success([serialize.settlement(s) for s in page], response_type="array", pagination=meta)


@bp.route("/api/customers/<cid>/complaints", methods=["GET"])
@require_roles("SystemAdmin", "FieldOpsManager", "CustomerContact")
def list_customer_complaints(cid):
    cc_check(cid)
    get_customer(cid)
    items = [fresh_complaint(c) for c in sorted_items(store.complaints.values()) if c["customer_id"] == cid]
    page, meta = paginate(items)
    return success([serialize.complaint(c) for c in page], response_type="array", pagination=meta)


@bp.route("/api/contracts/<cid>", methods=["GET"])
@require_roles("SystemAdmin", "FieldOpsManager", "BillingAnalyst", "CustomerContact")
def get_one_contract(cid):
    rec = get_contract(cid)
    cc_check(rec["customer_id"])
    return success(serialize.contract(rec))


@bp.route("/api/contracts/<cid>/activate", methods=["POST"])
@require_roles("SystemAdmin", "FieldOpsManager")
def activate_contract(cid):
    rec = get_contract(cid)
    if rec["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Contract %s is %s; only DRAFT can activate" % (cid, rec["status"]))
    today = store.clock_date()
    if not (today >= parse_date(rec["term_start"]) and today < parse_date(rec["term_end"])):
        raise err(
            "ERR_INVALID_STATE",
            "Contract term [%s, %s) does not cover the logical clock date %s"
            % (rec["term_start"], rec["term_end"], today.isoformat()),
        )
    _check_term_overlap(rec["customer_id"], rec["term_start"], rec["term_end"], exclude_id=rec["id"])
    rec["activated_at"] = store.now_iso()
    rec["status"] = "ACTIVE"
    store.bump(rec)
    customer = store.customers[rec["customer_id"]]
    if customer["status"] == "PROSPECT":
        customer["status"] = "ACTIVE"
        store.bump(customer)
    return success(serialize.contract(rec))


AMENDABLE_FIELDS = (
    ("floor_cents_per_gal", "num"),
    ("cap_cents_per_gal", "num"),
    ("service_fee_cents", "int"),
    ("overage_threshold_gal", "num"),
    ("overage_rate_cents_per_gal", "num"),
)


@bp.route("/api/contracts/<cid>/amend", methods=["POST"])
@require_roles("FieldOpsManager")
def amend_contract(cid):
    rec = get_contract(cid)
    body = get_body()
    expected = req_int(body, "expected_contract_version")
    updates = {}
    for field, kind in AMENDABLE_FIELDS:
        if field in body and body[field] is not None:
            updates[field] = opt_int(body, field) if kind == "int" else opt_num(body, field)
    if rec["status"] not in ("ACTIVE", "AT_RISK"):
        raise err("ERR_INVALID_STATE", "Contract %s is %s; amend requires ACTIVE or AT_RISK" % (cid, rec["status"]))
    if expected != rec["version"]:
        raise err("ERR_STALE_VERSION", "expected_contract_version %s != current %s" % (expected, rec["version"]))
    for field, value in updates.items():
        rec[field] = value
    if rec["status"] == "AT_RISK":
        rec["competitor_name"] = None
        rec["poach_offer_cents_per_gal"] = None
        rec["status"] = "ACTIVE"
    store.bump(rec)
    return success(serialize.contract(rec))


@bp.route("/api/contracts/<cid>/offer-renewal", methods=["POST"])
@require_roles("FieldOpsManager")
def offer_renewal(cid):
    rec = get_contract(cid)
    body = get_body()
    new_start = req_date(body, "new_term_start")
    new_end = req_date(body, "new_term_end")
    if rec["status"] not in ("ACTIVE", "AT_RISK"):
        raise err("ERR_INVALID_STATE", "Contract %s is %s; offer-renewal requires ACTIVE or AT_RISK" % (cid, rec["status"]))
    _check_term_overlap(rec["customer_id"], new_start, new_end, exclude_id=rec["id"])
    rec["offered_term_start"] = new_start
    rec["offered_term_end"] = new_end
    rec["status_before_renewal"] = rec["status"]
    rec["status"] = "RENEWAL_OFFERED"
    store.bump(rec)
    return success(serialize.contract(rec))


@bp.route("/api/contracts/<cid>/respond-renewal", methods=["POST"])
@require_roles("CustomerContact", "FieldOpsManager")
def respond_renewal(cid):
    rec = get_contract(cid)
    cc_check(rec["customer_id"])
    body = get_body()
    accept = req_bool(body, "accept")
    if rec["status"] != "RENEWAL_OFFERED":
        raise err("ERR_INVALID_STATE", "Contract %s is %s; respond-renewal requires RENEWAL_OFFERED" % (cid, rec["status"]))
    if accept:
        rec["term_start"] = rec["offered_term_start"]
        rec["term_end"] = rec["offered_term_end"]
        rec["offered_term_start"] = None
        rec["offered_term_end"] = None
        rec["status_before_renewal"] = None
        rec["status"] = "ACTIVE"
    else:
        prior = rec["status_before_renewal"]
        rec["offered_term_start"] = None
        rec["offered_term_end"] = None
        rec["status_before_renewal"] = None
        rec["status"] = prior
    store.bump(rec)
    return success(serialize.contract(rec))


@bp.route("/api/contracts/<cid>/flag-poach", methods=["POST"])
@require_roles("CustomerContact", "FieldOpsManager")
def flag_poach(cid):
    rec = get_contract(cid)
    cc_check(rec["customer_id"])
    body = get_body()
    competitor_name = req_str(body, "competitor_name")
    offer = req_num(body, "offer_cents_per_gal")
    if rec["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Contract %s is %s; flag-poach requires ACTIVE" % (cid, rec["status"]))
    rec["competitor_name"] = competitor_name
    rec["poach_offer_cents_per_gal"] = offer
    rec["status"] = "AT_RISK"
    store.bump(rec)
    return success(serialize.contract(rec))


@bp.route("/api/contracts/<cid>/terminate", methods=["POST"])
@require_roles("FieldOpsManager")
def terminate_contract(cid):
    rec = get_contract(cid)
    body = get_body()
    reason = req_enum(body, "reason", {"VOLUNTARY", "POACHED"})
    allowed = (rec["status"] == "ACTIVE" and reason == "VOLUNTARY") or (
        rec["status"] == "AT_RISK" and reason == "POACHED"
    )
    if not allowed:
        raise err(
            "ERR_INVALID_STATE",
            "Contract %s is %s; terminate with reason %s has no transition" % (cid, rec["status"], reason),
        )
    if store.clock < parse_dt(rec["activated_at"]) + timedelta(days=calc.COOLING_OFF_DAYS):
        raise err("ERR_CONTRACT_IN_COOLING_OFF", "Contract %s is within the 14-day cooling-off window" % cid)
    open_settlements = [
        s for s in store.settlements.values()
        if s["customer_id"] == rec["customer_id"] and s["status"] in ("PROVISIONAL", "FINALIZED")
    ]
    if open_settlements:
        raise err("ERR_OPEN_SETTLEMENTS", "Customer has settlements in PROVISIONAL or FINALIZED")
    rec["termination_reason"] = reason
    rec["status"] = "TERMINATED_VOLUNTARY" if reason == "VOLUNTARY" else "TERMINATED_POACHED"
    store.bump(rec)
    return success(serialize.contract(rec))


# ---------------------------------------------------------------------------
# Containers (PRD 3.3)
# ---------------------------------------------------------------------------
@bp.route("/api/customers/<cid>/containers", methods=["POST"])
@require_roles("FieldOpsManager")
def place_container(cid):
    customer = get_customer(cid)
    body = get_body()
    capacity = req_num(body, "capacity_gallons")
    if calc.D(capacity) < calc.D(30) or calc.D(capacity) > calc.D(2000):
        raise err("ERR_VALIDATION", "capacity_gallons must be within [30, 2000]")
    est_fill = req_num(body, "est_fill_rate_gal_per_week")
    lock_code = req_str(body, "lock_code")
    # Domain state guards in priority order: contract engagement (7), then
    # customer suspension (9).
    active_era = [c for c in _sibling_contracts(cid) if c["status"] in CONTRACT_ACTIVE_ERA]
    if not active_era:
        raise err("ERR_CONTRACT_NOT_ACTIVE", "Customer %s has no active-era contract" % cid)
    if customer["status"] == "SUSPENDED":
        raise err("ERR_CUSTOMER_SUSPENDED", "Customer %s is SUSPENDED" % cid)
    aggregate = sum(
        calc.D(c["capacity_gallons"])
        for c in store.containers.values()
        if c["customer_id"] == cid and c["status"] != "REMOVED"
    )
    if aggregate + calc.D(capacity) > calc.D(customer["site_max_container_gal"]):
        raise err(
            "ERR_VALIDATION",
            "Aggregate container capacity would exceed site_max_container_gal %s"
            % customer["site_max_container_gal"],
        )
    rec = {
        "id": store.new_id(),
        "customer_id": cid,
        "capacity_gallons": capacity,
        "est_fill_rate_gal_per_week": est_fill,
        "lock_code": lock_code,
        "status": "PLACED",
        "last_completed_pickup_date": None,
    }
    store.stamp(rec)
    store.containers[rec["id"]] = rec
    return success(serialize.container(rec), code=201)


@bp.route("/api/containers/<cid>", methods=["GET"])
@require_roles("SystemAdmin", "FieldOpsManager", "RouteDispatcher", "Driver", "CustomerContact")
def get_one_container(cid):
    rec = get_container(cid)
    cc_check(rec["customer_id"])
    return success(serialize.container(rec))


@bp.route("/api/containers/<cid>/unlock", methods=["POST"])
@require_roles("FieldOpsManager")
def unlock_container(cid):
    rec = get_container(cid)
    if rec["status"] != "LOCKED":
        raise err("ERR_INVALID_STATE", "Container %s is %s; only LOCKED can unlock" % (cid, rec["status"]))
    if _has_confirmed_theft(cid):
        raise err("ERR_THEFT_UNRESOLVED", "Container %s has a CONFIRMED theft incident" % cid)
    rec["status"] = "ACTIVE"
    store.bump(rec)
    return success(serialize.container(rec))


@bp.route("/api/containers/<cid>/remove", methods=["POST"])
@require_roles("FieldOpsManager")
def remove_container(cid):
    rec = get_container(cid)
    if rec["status"] not in ("PLACED", "ACTIVE", "LOCKED"):
        raise err("ERR_INVALID_STATE", "Container %s is %s; remove requires PLACED, ACTIVE or LOCKED" % (cid, rec["status"]))
    busy = any(
        v["container_id"] == cid and v["status"] in ("SCHEDULED", "EN_ROUTE")
        for v in store.visits.values()
    )
    if busy:
        raise err("ERR_INVALID_STATE", "Container %s has visits in SCHEDULED or EN_ROUTE" % cid)
    if rec["status"] == "LOCKED" and _has_confirmed_theft(cid):
        raise err("ERR_THEFT_UNRESOLVED", "Container %s has a CONFIRMED theft incident" % cid)
    rec["status"] = "REMOVED"
    store.bump(rec)
    return success(serialize.container(rec))


def _has_confirmed_theft(container_id):
    return any(
        t["container_id"] == container_id and t["status"] == "CONFIRMED"
        for t in store.thefts.values()
    )


@bp.route("/api/containers/<cid>/pickup-visits", methods=["GET"])
@require_roles("SystemAdmin", "FieldOpsManager", "RouteDispatcher", "Driver", "CustomerContact")
def list_container_visits(cid):
    rec = get_container(cid)
    cc_check(rec["customer_id"])
    items = [v for v in sorted_items(store.visits.values()) if v["container_id"] == cid]
    page, meta = paginate(items)
    return success([serialize.visit(v) for v in page], response_type="array", pagination=meta)


@bp.route("/api/containers/<cid>/theft-incidents", methods=["GET"])
@require_roles("SystemAdmin", "FieldOpsManager", "RouteDispatcher", "CustomerContact")
def list_container_thefts(cid):
    rec = get_container(cid)
    cc_check(rec["customer_id"])
    items = [t for t in sorted_items(store.thefts.values()) if t["container_id"] == cid]
    page, meta = paginate(items)
    return success([serialize.theft(t) for t in page], response_type="array", pagination=meta)
