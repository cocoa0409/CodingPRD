"""Component allocations, preemption and release penalties (PRD 3.4)."""
from flask import Blueprint

import calc
import clock
import common
import envelope
import posture
import rbac
import routes_suppliers as sup
import store
import validation
from errors import ApiError
from validation import DATETIME, INTEGER, STRING, f

bp = Blueprint("allocations", __name__)


def _victim_ranking(candidates):
    """priority_class DESC, then need_by_date DESC, then created_at ASC."""
    def key(a):
        need_by = clock.parse(a.get("need_by_date"))
        return (-(a.get("priority_class") or 0),
                -(need_by.timestamp() if need_by else 0),
                a.get("created_at"), a.get("_seq", 0))
    return sorted(candidates, key=key)


@bp.route("/component-allocations", methods=["POST"])
def create_allocation():
    rbac.authenticate("POST /component-allocations")
    payload = validation.body()
    order = common.resolve_body_ref("order", payload, "engineered_order_id")
    component = common.resolve_body_ref("component", payload, "long_lead_component_id")
    data = validation.validate(payload, [
        f("long_lead_component_id", STRING, required=True),
        f("engineered_order_id", STRING, required=True),
        f("quantity", INTEGER, required=True, minimum=1),
        f("priority_class", INTEGER, required=True, minimum=1, maximum=5),
        f("need_by_date", DATETIME, required=True),
        f("expected_component_version", INTEGER, required=True),
    ])
    validation.check_component_version(data, component)
    common.check_order_not_cancelled(order)
    sup.check_component_usable(component, as_target=False)
    sup.check_supplier_active(store.get("supplier", component.get("supplier_id")))
    need_by = clock.sec(clock.parse(data["need_by_date"]))
    if need_by is not None and need_by < clock.sec(clock.now()):
        raise ApiError("ERR_NEED_BY_DATE_PASSED", "need_by_date is already in the past")

    available = component.get("quantity_available") or 0
    victims = []
    if data["quantity"] > available:
        shortfall = data["quantity"] - available
        pool = [a for a in store.where("allocation", long_lead_component_id=component["id"])
                if a.get("status") == "RESERVED"
                and (a.get("priority_class") or 0) > data["priority_class"]
                and a.get("engineered_order_id") != order["id"]]
        same_order_lower = [a for a in store.where("allocation", long_lead_component_id=component["id"])
                            if a.get("status") == "RESERVED"
                            and (a.get("priority_class") or 0) > data["priority_class"]
                            and a.get("engineered_order_id") == order["id"]]
        if component.get("allocation_policy") == "PROTECTED" and (pool or same_order_lower):
            raise ApiError("ERR_PREEMPTION_NOT_PERMITTED",
                           "the component is PROTECTED and may not be preempted")
        if not pool:
            if same_order_lower:
                raise ApiError("ERR_PREEMPTION_NOT_PERMITTED",
                               "the only lower-priority holders belong to this order")
            raise ApiError("ERR_COMPONENT_INSUFFICIENT",
                           "quantity exceeds quantity_available")
        running = 0
        for candidate in _victim_ranking(pool):
            victims.append(candidate)
            running += candidate.get("quantity") or 0
            if running >= shortfall:
                break
        if running < shortfall:
            raise ApiError("ERR_COMPONENT_INSUFFICIENT",
                           "preemption cannot cover the shortfall")

    allocation = {
        "long_lead_component_id": component["id"],
        "engineered_order_id": order["id"],
        "quantity": data["quantity"],
        "priority_class": data["priority_class"],
        "need_by_date": data["need_by_date"],
        "status": "RESERVED",
        "release_penalty_cents": 0,
        "preempted_for_allocation_id": None,
        "committed_at": None,
        "released_at": None,
    }
    store.insert("allocation", allocation)
    victim_orders = set()
    for victim in victims:
        victim["status"] = "PREEMPTED"
        victim["preempted_for_allocation_id"] = allocation["id"]
        victim["released_at"] = clock.now_str()
        store.touch("allocation", victim)
        victim_orders.add(victim.get("engineered_order_id"))
    calc.refresh_component_buckets(component)
    store.touch("component", component)
    for oid in victim_orders:
        common.auto_material_edges(store.get("order", oid))
    common.auto_material_edges(order)
    return envelope.created(store.public(allocation))


@bp.route("/component-allocations", methods=["GET"])
def list_allocations():
    rbac.authenticate("GET /component-allocations")
    limit, offset = envelope.pagination()
    rows = common.apply_filters(store.all_rows("allocation"), {
        "long_lead_component_id": common.qstr("long_lead_component_id"),
        "engineered_order_id": common.qstr("engineered_order_id"),
        "preempted_for_allocation_id": common.qstr("preempted_for_allocation_id"),
        "status": common.qstr("status"),
        "priority_class": common.qint("priority_class"),
    })
    return envelope.listing(store.public_list(rows), limit, offset)


@bp.route("/component-allocations/<aid>", methods=["GET"])
def get_allocation(aid):
    rbac.authenticate("GET /component-allocations/{id}")
    return envelope.ok(store.public(common.resolve("allocation", aid)))


@bp.route("/component-allocations/<aid>/commit", methods=["POST"])
def commit_allocation(aid):
    rbac.authenticate("POST /component-allocations/{id}/commit")
    allocation = common.resolve("allocation", aid)
    component = common.resolve("component", allocation.get("long_lead_component_id"))
    order = common.resolve("order", allocation.get("engineered_order_id"))
    common.check_state("allocation", allocation, ("RESERVED",))
    common.check_order_not_cancelled(order)
    common.check_design_released(order)
    posture.check_posture_blocked(order)
    sup.check_component_usable(component)
    headroom = (component.get("quantity_on_hand") or 0) - (component.get("quantity_committed") or 0)
    if (allocation.get("quantity") or 0) > headroom:
        raise ApiError("ERR_COMPONENT_INSUFFICIENT",
                       "quantity exceeds quantity_on_hand less quantity_committed")
    allocation["status"] = "COMMITTED"
    allocation["committed_at"] = clock.now_str()
    store.touch("allocation", allocation)
    calc.refresh_component_buckets(component)
    store.touch("component", component)
    store.touch("order", order)
    common.auto_material_edges(order)
    return envelope.ok(store.public(allocation))


@bp.route("/component-allocations/<aid>/release", methods=["POST"])
def release_allocation(aid):
    rbac.authenticate("POST /component-allocations/{id}/release")
    allocation = common.resolve("allocation", aid)
    component = common.resolve("component", allocation.get("long_lead_component_id"))
    order = common.resolve("order", allocation.get("engineered_order_id"))
    payload = validation.body()
    validation.validate(payload, [f("reason", STRING)])
    was_committed = allocation.get("status") == "COMMITTED"
    common.check_state("allocation", allocation, ("RESERVED", "COMMITTED"))
    if was_committed:
        if order.get("fulfillment_status") == "FAT_COMPLETE":
            raise ApiError("ERR_ORDER_FULFILLMENT_STATE_INVALID",
                           "a committed allocation may not be released once the FAT is complete")
        if order.get("fulfillment_status") == "CLOSED":
            raise ApiError("ERR_RELEASE_PENALTY_UNBILLABLE",
                           "the order has closed and the restocking penalty could never be billed")
    allocation["status"] = "RELEASED"
    allocation["released_at"] = clock.now_str()
    if isinstance(payload.get("reason"), str):
        allocation["release_reason"] = payload["reason"]
    allocation["release_penalty_cents"] = \
        calc.release_penalty_cents(allocation, component, order) if was_committed else 0
    store.touch("allocation", allocation)
    calc.refresh_component_buckets(component)
    store.touch("component", component)
    store.touch("order", order)
    common.auto_material_edges(order)
    return envelope.ok(store.public(allocation))
