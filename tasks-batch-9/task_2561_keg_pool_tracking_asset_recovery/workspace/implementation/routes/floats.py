"""Float agreements and the issuance-order pipeline."""
from flask import Blueprint

import clock
import db
import middleware
import response
import util
from errors import fail
from services import calc, recompute, view

bp = Blueprint("floats", __name__)

AGREEMENT_STATUSES = ("DRAFT", "ACTIVE", "TERMINATED")
FLOAT_POSTURES = ("HEALTHY", "TIGHT", "SUSPENDED")
ORDER_STATUSES = ("REQUESTED", "ALLOCATED", "PARTIALLY_ALLOCATED",
                  "DISPATCHED", "CANCELLED")
ORDER_TERMINAL = ("CANCELLED", "DISPATCHED")
ORDER_LIVE = ("REQUESTED", "ALLOCATED", "PARTIALLY_ALLOCATED")


# ------------------------------------------------- shared gate helpers -------


def _pool_gates(pool, requested_keg_count):
    """Ladder steps 13 and 14, shared by order creation and allocation."""
    if pool["posture"] == "FROZEN":
        fail("ERR_POOL_FROZEN", "The pool's posture is FROZEN.")
    if pool["posture"] == "RESTRICTED" and \
            requested_keg_count > pool["restricted_max_kegs_per_order"]:
        fail("ERR_POOL_RESTRICTED",
             "A RESTRICTED pool allows at most %d kegs per order."
             % pool["restricted_max_kegs_per_order"])


def _brewer_not_suspended(brewer):
    if brewer is not None and brewer["status"] == "SUSPENDED":
        fail("ERR_BREWER_SUSPENDED", "The brewer's status is SUSPENDED.")


# -------------------------------------------------------- float agreements ---


@bp.post("/float-agreements")
def create_agreement():
    middleware.authenticate("PoolOperator")
    payload = util.body()
    util.forbid_version_fields(payload)
    brewer_id = util.req_string(payload, "brewer_id")
    pool_id = util.req_string(payload, "pool_id")
    float_size = util.req_int(payload, "float_size_kegs", minimum=1,
                              maximum=500)
    per_fill_rate = util.req_int(payload, "per_fill_rate_cents", minimum=1)
    threshold = util.opt_int(payload, "replenishment_threshold_pct", minimum=0,
                             maximum=100, default=20)
    min_fills = util.opt_int(payload, "min_fills_per_month", minimum=0,
                             default=0)
    if brewer_id not in db.brewers:
        fail("ERR_BREWER_NOT_FOUND")
    if pool_id not in db.pools:
        fail("ERR_POOL_NOT_FOUND")
    agreement = util.common_fields()
    agreement.update({
        "brewer_id": brewer_id,
        "pool_id": pool_id,
        "float_size_kegs": float_size,
        "per_fill_rate_cents": per_fill_rate,
        "replenishment_threshold_pct": threshold,
        "min_fills_per_month": min_fills,
        "effective_date": None,
        "status": "DRAFT",
        "float_posture": "HEALTHY",
        "kegs_issued_count": 0,
        "kegs_at_brewer_count": 0,
        "pending_replenishment_kegs": 0,
        "billed_fills_count": 0,
        "billed_amount_cents": 0,
        "terminated_reason": None,
    })
    db.agreements[agreement["id"]] = agreement
    return response.created(agreement)


@bp.post("/float-agreements/<agreement_id>/activate")
def activate_agreement(agreement_id):
    middleware.authenticate("PoolOperator")
    payload = util.body()
    util.forbid_version_fields(payload)
    effective_date = util.parse_date(
        util.req_present(payload, "effective_date"), "effective_date")
    agreement = db.agreements.get(agreement_id)
    if agreement is None:
        fail("ERR_AGREEMENT_NOT_FOUND")
    if agreement["status"] == "TERMINATED":
        fail("ERR_ALREADY_TERMINAL", "The agreement is TERMINATED.")
    if agreement["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", "Only a DRAFT agreement may be activated.")
    brewer = db.brewers.get(agreement["brewer_id"])
    _brewer_not_suspended(brewer)
    util.not_future_date(effective_date, "effective_date")
    existing = recompute.active_agreement(agreement["brewer_id"],
                                          agreement["pool_id"])
    if existing is not None and existing["id"] != agreement["id"]:
        fail("ERR_AGREEMENT_ALREADY_ACTIVE",
             "That brewer already holds an ACTIVE agreement on this pool.")
    agreement["status"] = "ACTIVE"
    agreement["effective_date"] = effective_date
    util.bump(agreement)
    recompute.recompute_agreement(agreement)
    return response.ok(agreement)


@bp.post("/float-agreements/<agreement_id>/terminate")
def terminate_agreement(agreement_id):
    middleware.authenticate("PoolOperator")
    payload = util.body()
    util.forbid_version_fields(payload)
    reason = util.req_string(payload, "terminated_reason", 1, 500)
    agreement = db.agreements.get(agreement_id)
    if agreement is None:
        fail("ERR_AGREEMENT_NOT_FOUND")
    if agreement["status"] == "TERMINATED":
        fail("ERR_ALREADY_TERMINAL", "The agreement is already TERMINATED.")
    if agreement["status"] == "ACTIVE":
        at_brewer, _issued = recompute.agreement_counters(agreement)
        outstanding = at_brewer > 0 or any(
            order["status"] in ORDER_LIVE
            for order in recompute.orders_of_agreement(agreement["id"]))
        if outstanding:
            fail("ERR_AGREEMENT_FLOAT_OUTSTANDING",
                 "Float is still outstanding against this agreement.")
    agreement["status"] = "TERMINATED"
    agreement["terminated_reason"] = reason
    util.bump(agreement)
    return response.ok(agreement)


@bp.get("/float-agreements/<agreement_id>")
def read_agreement(agreement_id):
    actor = middleware.authenticate("PoolOperator", "Brewer",
                                    "AssetRecoveryAnalyst")
    agreement = db.agreements.get(agreement_id)
    if agreement is None:
        fail("ERR_AGREEMENT_NOT_FOUND")
    # PRD 2.8 step 8: entity-backed ownership of the now-known target resource,
    # on every operation whose authorised roles include Brewer or Distributor
    # and that names an existing resource.
    middleware.owner_check(actor, agreement["brewer_id"])
    return response.ok(agreement)


@bp.get("/float-agreements")
def list_agreements():
    middleware.authenticate("PoolOperator", "Brewer", "AssetRecoveryAnalyst")
    limit, offset = middleware.pagination()
    filters = {field: middleware.qparam(field)
               for field in ("brewer_id", "pool_id", "status",
                             "float_posture")}
    rows = [row for row in db.agreements.values()
            if all(view.match(row, field, value)
                   for field, value in filters.items())]
    page, total = view.paginate(view.ordered(rows), limit, offset)
    return response.listing(page, limit, offset, total)


# -------------------------------------------------------- issuance orders ----


@bp.post("/issuance-orders")
def create_order():
    middleware.authenticate("PoolOperator")
    payload = util.body()
    util.forbid_version_fields(payload)
    agreement_id = util.req_string(payload, "agreement_id")
    requested = util.req_int(payload, "requested_keg_count", minimum=1)
    allow_partial = util.opt_bool(payload, "allow_partial", default=False)
    agreement = db.agreements.get(agreement_id)
    if agreement is None:
        fail("ERR_AGREEMENT_NOT_FOUND")
    if agreement["status"] != "ACTIVE":
        fail("ERR_AGREEMENT_NOT_ACTIVE", "The agreement is not ACTIVE.")
    pool = db.pools.get(agreement["pool_id"])
    brewer = db.brewers.get(agreement["brewer_id"])
    _pool_gates(pool, requested)
    _brewer_not_suspended(brewer)
    if requested + agreement["kegs_at_brewer_count"] \
            > agreement["float_size_kegs"]:
        fail("ERR_FLOAT_SIZE_EXCEEDED",
             "The request does not fit the contracted float size.")
    exposure = brewer["chargeback_balance_cents"] \
        + requested * agreement["per_fill_rate_cents"]
    if exposure > brewer["credit_limit_cents"]:
        fail("ERR_CREDIT_LIMIT_EXCEEDED",
             "Projected exposure of %d cents exceeds the brewer's credit "
             "limit." % exposure)
    order = util.common_fields()
    order.update({
        "agreement_id": agreement["id"],
        "brewer_id": agreement["brewer_id"],
        "requested_keg_count": requested,
        "allow_partial": allow_partial,
        "status": "REQUESTED",
        "allocated_keg_count": 0,
        "allocation_shortfall": 0,
        "per_fill_price_cents_pinned": None,
        "allocated_keg_ids": [],
        "dispatched_at": None,
        "cancel_reason": None,
    })
    db.orders[order["id"]] = order
    return response.created(order)


def _allocation_candidates(agreement):
    """IN_FLOAT, certified enough to leave, unencumbered by theft or loss."""
    candidates = [keg for keg in db.kegs.values()
                  if keg["pool_id"] == agreement["pool_id"]
                  and keg["custody_state"] == "IN_FLOAT"
                  and keg["service_state"] in ("SERVICE_OK", "SERVICE_DUE")
                  and keg["theft_investigation_id"] is None
                  and not keg["assessment_open"]]
    candidates.sort(key=lambda keg: (keg["fill_count"],
                                     keg["last_pressure_test_at"],
                                     keg["created_at"]))
    return candidates


@bp.post("/issuance-orders/<order_id>/allocate")
def allocate_order(order_id):
    middleware.authenticate("PoolOperator")
    payload = util.body()
    util.forbid_version_fields(payload, allowed="expected_agreement_version")
    expected_version = util.req_int(payload, "expected_agreement_version")
    order = db.orders.get(order_id)
    if order is None:
        fail("ERR_ORDER_NOT_FOUND")
    agreement = db.agreements.get(order["agreement_id"])
    if agreement is not None and expected_version != agreement["version"]:
        fail("ERR_STALE_AGREEMENT_VERSION",
             "The agreement has moved on since version %d." % expected_version)
    if order["status"] in ORDER_TERMINAL:
        fail("ERR_ALREADY_TERMINAL", "The order is %s." % order["status"])
    if order["status"] != "REQUESTED":
        fail("ERR_INVALID_STATE",
             "Only a REQUESTED order may be allocated.")
    if agreement["status"] != "ACTIVE":
        fail("ERR_AGREEMENT_NOT_ACTIVE", "The agreement is not ACTIVE.")
    pool = db.pools.get(agreement["pool_id"])
    brewer = db.brewers.get(agreement["brewer_id"])
    _pool_gates(pool, order["requested_keg_count"])
    if agreement["float_posture"] == "SUSPENDED":
        fail("ERR_FLOAT_SUSPENDED", "The agreement's float is SUSPENDED.")
    _brewer_not_suspended(brewer)
    candidates = _allocation_candidates(agreement)
    if not candidates:
        fail("ERR_NO_ELIGIBLE_KEGS", "No keg of the pool is allocatable.")
    take = min(order["requested_keg_count"], len(candidates))
    if take < order["requested_keg_count"] and not order["allow_partial"]:
        fail("ERR_INSUFFICIENT_FLOAT",
             "Only %d of %d kegs are allocatable and allow_partial is false."
             % (take, order["requested_keg_count"]))
    if brewer["chargeback_balance_cents"] >= brewer["credit_limit_cents"]:
        fail("ERR_CREDIT_LIMIT_EXCEEDED",
             "The brewer's chargeback balance has reached its credit limit.")
    selected = candidates[:take]
    stamp = clock.now()
    for keg in selected:
        keg["custody_state"] = "ISSUED_TO_BREWER"
        keg["current_brewer_id"] = agreement["brewer_id"]
        keg["issuance_order_id"] = order["id"]
        keg["dwell_started_at"] = stamp
        keg["dwell_flag"] = "WITHIN_LIMIT"
        util.bump(keg)
    order["allocated_keg_ids"] = [keg["id"] for keg in selected]
    order["allocated_keg_count"] = take
    order["allocation_shortfall"] = order["requested_keg_count"] - take
    order["per_fill_price_cents_pinned"] = agreement["per_fill_rate_cents"]
    order["status"] = "ALLOCATED" if order["allocation_shortfall"] == 0 \
        else "PARTIALLY_ALLOCATED"
    util.bump(order)
    recompute.cascade_pool(pool)
    recompute.recompute_agreement(agreement)
    return response.ok(order)


@bp.post("/issuance-orders/<order_id>/dispatch")
def dispatch_order(order_id):
    middleware.authenticate("PoolOperator")
    payload = util.body()
    util.forbid_version_fields(payload)
    dispatched_at = util.parse_instant(
        util.req_present(payload, "dispatched_at"), "dispatched_at")
    order = db.orders.get(order_id)
    if order is None:
        fail("ERR_ORDER_NOT_FOUND")
    if order["status"] in ORDER_TERMINAL:
        fail("ERR_ALREADY_TERMINAL", "The order is %s." % order["status"])
    if order["status"] not in ("ALLOCATED", "PARTIALLY_ALLOCATED"):
        fail("ERR_INVALID_STATE",
             "Only an allocated order may be dispatched.")
    agreement = db.agreements.get(order["agreement_id"])
    if agreement["status"] != "ACTIVE":
        fail("ERR_AGREEMENT_NOT_ACTIVE", "The agreement is not ACTIVE.")
    util.not_future_instant(dispatched_at, "dispatched_at")
    order["status"] = "DISPATCHED"
    order["dispatched_at"] = dispatched_at
    util.bump(order)
    for keg_id in order["allocated_keg_ids"]:
        keg = db.kegs.get(keg_id)
        if keg is None:
            continue
        keg["dwell_started_at"] = dispatched_at
        util.bump(keg)
    recompute.recompute_agreement(agreement)
    return response.ok(order)


@bp.post("/issuance-orders/<order_id>/cancel")
def cancel_order(order_id):
    middleware.authenticate("PoolOperator")
    payload = util.body()
    util.forbid_version_fields(payload)
    reason = util.req_string(payload, "cancel_reason", 1, 500)
    order = db.orders.get(order_id)
    if order is None:
        fail("ERR_ORDER_NOT_FOUND")
    if order["status"] in ORDER_TERMINAL:
        fail("ERR_ALREADY_TERMINAL", "The order is %s." % order["status"])
    if order["status"] not in ORDER_LIVE:
        fail("ERR_INVALID_STATE", "The order cannot be cancelled.")
    for keg_id in order["allocated_keg_ids"]:
        keg = db.kegs.get(keg_id)
        if keg is None or keg["custody_state"] != "ISSUED_TO_BREWER":
            continue
        keg["custody_state"] = "IN_FLOAT"
        keg["current_brewer_id"] = None
        keg["issuance_order_id"] = None
        keg["dwell_started_at"] = None
        keg["dwell_flag"] = "WITHIN_LIMIT"
        util.bump(keg)
    order["status"] = "CANCELLED"
    order["cancel_reason"] = reason
    util.bump(order)
    agreement = db.agreements.get(order["agreement_id"])
    if agreement is not None:
        recompute.cascade_pool_id(agreement["pool_id"])
        recompute.recompute_agreement(agreement)
    return response.ok(order)


@bp.get("/issuance-orders/<order_id>")
def read_order(order_id):
    middleware.authenticate("PoolOperator", "Brewer", "AssetRecoveryAnalyst")
    order = db.orders.get(order_id)
    if order is None:
        fail("ERR_ORDER_NOT_FOUND")
    return response.ok(order)


@bp.get("/issuance-orders")
def list_orders():
    middleware.authenticate("PoolOperator", "Brewer", "AssetRecoveryAnalyst")
    limit, offset = middleware.pagination()
    filters = {field: middleware.qparam(field)
               for field in ("agreement_id", "brewer_id", "status")}
    rows = [row for row in db.orders.values()
            if all(view.match(row, field, value)
                   for field, value in filters.items())]
    page, total = view.paginate(view.ordered(rows), limit, offset)
    return response.listing(page, limit, offset, total)
