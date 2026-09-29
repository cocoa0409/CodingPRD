"""Logical clock and engineered-order endpoints (PRD 3.1)."""
from flask import Blueprint

import calc
import clock
import common
import envelope
import posture
import rbac
import store
import validation
from errors import ApiError
from validation import BOOLEAN, DATETIME, INTEGER, NUMBER, STRING, f

bp = Blueprint("orders", __name__)

PRODUCT_FAMILIES = ["POWER_TRANSFORMER", "PAD_MOUNT_TRANSFORMER", "MV_SWITCHGEAR", "LV_SWITCHGEAR"]

CREATE_SPEC = [
    f("order_number", STRING, required=True),
    f("customer_name", STRING, required=True),
    f("product_family", STRING, required=True, enum=PRODUCT_FAMILIES),
    f("rated_kv", NUMBER, required=True),
    f("contract_value_cents", INTEGER, required=True, minimum=100000),
    f("sold_at", DATETIME, required=True),
    f("promised_ship_at", DATETIME, required=True),
    f("owning_sales_user_id", STRING, required=True),
]

PATCH_SPEC = [
    f("customer_name", STRING),
    f("contract_value_cents", INTEGER, minimum=100000),
    f("promised_ship_at", DATETIME),
    f("owning_sales_user_id", STRING),
]


def order_state(order, allowed_fulfillment=None, allowed_engineering=None):
    """Rungs 34/35/37 for a transition whose target row is the order itself."""
    if allowed_engineering is not None:
        eng = order.get("engineering_status")
        if eng not in allowed_engineering:
            if eng == "ENG_CLOSED":
                raise ApiError("ERR_TERMINAL_STATE", "engineering_status is ENG_CLOSED")
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "engineering_status %s is not a legal source" % eng)
    if allowed_fulfillment is not None:
        ful = order.get("fulfillment_status")
        if ful not in allowed_fulfillment:
            if ful in ("CLOSED", "CANCELLED"):
                raise ApiError("ERR_TERMINAL_STATE", "fulfillment_status is %s" % ful)
            raise ApiError("ERR_ORDER_FULFILLMENT_STATE_INVALID",
                           "fulfillment_status %s is not a legal source" % ful)


# --------------------------------------------------------------------------- #
# logical clock
# --------------------------------------------------------------------------- #

@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    rbac.authenticate("POST /_clock/set_current_utc")
    payload = validation.body()
    data = validation.validate(payload, [f("current_utc", DATETIME, required=True)])
    clock.set_now(clock.parse(data["current_utc"]))
    return envelope.ok({"current_utc": clock.now_str()})


# --------------------------------------------------------------------------- #
# orders
# --------------------------------------------------------------------------- #

@bp.route("/engineered-orders", methods=["POST"])
def create_order():
    actor = rbac.authenticate("POST /engineered-orders")
    payload = validation.body()
    # Rung 4 sits above payload validation: on a creation the order in scope is the
    # one being created, and its owner is the owning_sales_user_id in the body.
    owner = payload.get("owning_sales_user_id") if isinstance(payload, dict) else None
    if isinstance(owner, str):
        rbac.check_order_ownership(actor, {"owning_sales_user_id": owner})
    data = validation.validate(payload, CREATE_SPEC)
    if not (6 <= len(data["order_number"]) <= 24):
        raise ApiError("ERR_FIELD_VALUE_OUT_OF_RANGE", "order_number must be 6-24 characters")
    if not (0 < data["rated_kv"] <= 800):
        raise ApiError("ERR_FIELD_VALUE_OUT_OF_RANGE", "rated_kv must be > 0 and <= 800")
    for existing in store.all_rows("order"):
        if existing.get("order_number") == data["order_number"]:
            raise ApiError("ERR_DUPLICATE_ORDER_NUMBER", "order_number already exists")
    order = dict(data)
    order.update({
        "engineering_status": "ENG_OPEN",
        "fulfillment_status": "PLANNING",
        "production_posture": "OPEN",
        "posture_reason_codes": [],
        "escalation_accepted_total_cents": 0,
        "warranty_credit_total_cents": 0,
        "net_contract_value_cents": data["contract_value_cents"],
        "billed_to_date_cents": 0,
        "released_drawing_revision": None,
        "cancelled_reason": None,
    })
    store.insert("order", order)
    return envelope.created(store.public(order))


@bp.route("/engineered-orders", methods=["GET"])
def list_orders():
    rbac.authenticate("GET /engineered-orders")
    limit, offset = envelope.pagination()
    rows = common.apply_filters(store.all_rows("order"), {
        "engineering_status": common.qstr("engineering_status"),
        "fulfillment_status": common.qstr("fulfillment_status"),
        "production_posture": common.qstr("production_posture"),
        "product_family": common.qstr("product_family"),
        "owning_sales_user_id": common.qstr("owning_sales_user_id"),
    })
    return envelope.listing(store.public_list(rows), limit, offset)


@bp.route("/engineered-orders/<oid>", methods=["GET"])
def get_order(oid):
    rbac.authenticate("GET /engineered-orders/{id}")
    order = common.resolve("order", oid)
    return envelope.ok(store.public(order))


@bp.route("/engineered-orders/<oid>", methods=["PATCH"])
def patch_order(oid):
    rbac.authenticate("PATCH /engineered-orders/{id}")
    order = common.resolve("order", oid)
    payload = validation.body()
    data = validation.validate(payload, PATCH_SPEC)
    order_state(order, allowed_fulfillment=("PLANNING",))
    for key in ("customer_name", "contract_value_cents", "promised_ship_at", "owning_sales_user_id"):
        if key in data:
            order[key] = data[key]
    store.touch("order", order)
    posture.refresh(order)
    common.rebill_stages(order)
    return envelope.ok(store.public(order))


@bp.route("/engineered-orders/<oid>/start-production", methods=["POST"])
def start_production(oid):
    actor = rbac.authenticate("POST /engineered-orders/{id}/start-production")
    order = common.resolve("order", oid)
    rbac.check_order_ownership(actor, order)
    order_state(order, allowed_fulfillment=("MATERIAL_ALLOCATED",))
    common.check_design_released(order)
    posture.refresh(order)
    if order.get("production_posture") != "OPEN":
        raise ApiError("ERR_POSTURE_BLOCKED",
                       "posture is %s: %s" % (order.get("production_posture"),
                                              ", ".join(order.get("posture_reason_codes") or [])))
    now = clock.sec(clock.now())
    for a in store.where("allocation", engineered_order_id=oid):
        if a.get("status") != "COMMITTED":
            continue
        need_by = clock.sec(clock.parse(a.get("need_by_date")))
        if need_by is not None and need_by < now:
            raise ApiError("ERR_NEED_BY_DATE_PASSED",
                           "allocation %s need_by_date has passed" % a["id"])
    order["fulfillment_status"] = "IN_PRODUCTION"
    store.touch("order", order)
    posture.refresh(order)
    return envelope.ok(store.public(order))


@bp.route("/engineered-orders/<oid>/close-engineering", methods=["POST"])
def close_engineering(oid):
    actor = rbac.authenticate("POST /engineered-orders/{id}/close-engineering")
    order = common.resolve("order", oid)
    rbac.check_order_ownership(actor, order)
    order_state(order, allowed_engineering=("DESIGN_RELEASED",))
    if order.get("fulfillment_status") != "CLOSED":
        raise ApiError("ERR_ORDER_FULFILLMENT_STATE_INVALID",
                       "fulfillment_status must be CLOSED to close engineering")
    for d in store.where("drawing", engineered_order_id=oid):
        if d.get("status") in ("DRAFT", "SUBMITTED", "UNDER_REVIEW", "REVISE_AND_RESUBMIT"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "submittal drawing %s is still in review" % d["id"])
    for a in store.where("adjustment", engineered_order_id=oid):
        if a.get("status") in ("CALCULATED", "SUBMITTED_TO_CUSTOMER", "DISPUTED", "RECALCULATING"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "escalation adjustment %s is still in flight" % a["id"])
    order["engineering_status"] = "ENG_CLOSED"
    store.touch("order", order)
    for c in store.where("clause", engineered_order_id=oid):
        c["status"] = "SUPERSEDED"
        store.touch("clause", c)
    posture.refresh(order)
    return envelope.ok(store.public(order))


@bp.route("/engineered-orders/<oid>/cancel", methods=["POST"])
def cancel_order(oid):
    actor = rbac.authenticate("POST /engineered-orders/{id}/cancel")
    order = common.resolve("order", oid)
    rbac.check_order_ownership(actor, order)
    payload = validation.body()
    data = validation.validate(payload, [f("cancelled_reason", STRING, required=True)])
    order_state(order, allowed_fulfillment=("PLANNING", "MATERIAL_ALLOCATED"),
                allowed_engineering=("ENG_OPEN", "SUBMITTAL_IN_REVIEW", "DESIGN_RELEASED"))
    for r in store.where("release", engineered_order_id=oid):
        if r.get("status") in ("IN_TRANSIT", "DELIVERED"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "freight has already left the plant")
    order["fulfillment_status"] = "CANCELLED"
    order["cancelled_reason"] = data["cancelled_reason"]
    store.touch("order", order)

    components = set()
    for a in store.where("allocation", engineered_order_id=oid):
        if a.get("status") not in ("RESERVED", "COMMITTED"):
            continue
        was_committed = a.get("status") == "COMMITTED"
        comp = store.get("component", a.get("long_lead_component_id"))
        a["status"] = "RELEASED"
        a["released_at"] = clock.now_str()
        if was_committed and comp is not None:
            a["release_penalty_cents"] = calc.release_penalty_cents(a, comp, order)
        store.touch("allocation", a)
        if comp is not None:
            components.add(comp["id"])
    for cid in components:
        comp = store.get("component", cid)
        calc.refresh_component_buckets(comp)
        store.touch("component", comp)

    for r in store.where("release", engineered_order_id=oid):
        if r.get("status") in ("HELD", "CLEARED", "STAGED", "SITE_STORAGE"):
            r["status"] = "CANCELLED"
            r["stage_billing_cents"] = 0
            store.touch("release", r)
            for sa in store.where("storage", shipment_release_id=r["id"]):
                if sa.get("status") == "OPEN":
                    sa["status"] = "WAIVED"
                    sa["billable_days"] = 0
                    sa["storage_subtotal_cents"] = 0
                    sa["insurance_surcharge_cents"] = 0
                    sa["long_stay_discount_cents"] = 0
                    sa["total_fee_cents"] = 0
                    store.touch("storage", sa)

    for j in store.where("job", engineered_order_id=oid):
        if j.get("status") in ("COMPLETE", "CANCELLED"):
            continue
        j["status"] = "CANCELLED"
        for item in store.where("punch", commissioning_job_id=j["id"]):
            if item.get("status") in ("OPEN", "ASSIGNED", "RESOLVED"):
                item["status"] = "REJECTED"
                store.touch("punch", item)
        calc.refresh_job_aggregates(j)
        store.touch("job", j)

    posture.refresh(order)
    return envelope.ok(store.public(order))


@bp.route("/engineered-orders/<oid>/posture", methods=["GET"])
def get_posture(oid):
    rbac.authenticate("GET /engineered-orders/{id}/posture")
    order = common.resolve("order", oid)
    posture.refresh(order)
    return envelope.ok(store.public(order))


@bp.route("/engineered-orders/<oid>/financial-summary", methods=["GET"])
def get_financial_summary(oid):
    actor = rbac.authenticate("GET /engineered-orders/{id}/financial-summary")
    order = common.resolve("order", oid)
    posture.refresh(order)
    return envelope.ok(store.public(order))
