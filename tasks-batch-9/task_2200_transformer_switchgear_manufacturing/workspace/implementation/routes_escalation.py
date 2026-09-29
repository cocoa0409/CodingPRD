"""Escalation clauses, commodity index points and escalation adjustments (PRD 3.3)."""
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

bp = Blueprint("escalation", __name__)

COMMODITIES = ["COPPER", "ALUMINUM", "CORE_STEEL"]
VARIANTS = ["PROVISIONAL", "FINAL"]
IN_FLIGHT = ("SUBMITTED_TO_CUSTOMER", "RECALCULATING")


def _check_month(value, field):
    if len(value) != 7 or value[4] != "-" or not value[0:4].isdigit() or not value[5:7].isdigit():
        raise ApiError("ERR_FIELD_TYPE_INVALID", "%s must be in YYYY-MM form" % field)
    if not (1 <= int(value[5:7]) <= 12):
        raise ApiError("ERR_FIELD_VALUE_OUT_OF_RANGE", "%s names an impossible month" % field)


def _recompute(adjustment, clause):
    values = calc.escalation_components(clause, adjustment.get("variant"))
    adjustment.update(values)
    return adjustment


# --------------------------------------------------------------------------- #
# escalation clauses
# --------------------------------------------------------------------------- #

@bp.route("/engineered-orders/<oid>/escalation-clauses", methods=["POST"])
def create_clause(oid):
    rbac.authenticate("POST /engineered-orders/{id}/escalation-clauses")
    order = common.resolve("order", oid)
    payload = validation.body()
    data = validation.validate(payload, [
        f("copper_weight_bp", INTEGER, required=True, minimum=0, maximum=10000),
        f("aluminum_weight_bp", INTEGER, required=True, minimum=0, maximum=10000),
        f("core_steel_weight_bp", INTEGER, required=True, minimum=0, maximum=10000),
        f("escalatable_base_cents", INTEGER, required=True, minimum=0),
        f("base_index_month", STRING, required=True),
        f("cap_bp", INTEGER, required=True, minimum=0, maximum=5000),
        f("collar_bp", INTEGER, required=True, minimum=0, maximum=1000),
        f("de_escalation_enabled", BOOLEAN, default=True),
        f("final_window_end_month", STRING, required=True),
    ])
    _check_month(data["base_index_month"], "base_index_month")
    _check_month(data["final_window_end_month"], "final_window_end_month")
    weights = data["copper_weight_bp"] + data["aluminum_weight_bp"] + data["core_steel_weight_bp"]
    if weights != 10000:
        raise ApiError("ERR_FIELD_VALUE_OUT_OF_RANGE",
                       "the three commodity weightings must sum to exactly 10000")
    if data["escalatable_base_cents"] > (order.get("contract_value_cents") or 0):
        raise ApiError("ERR_FIELD_VALUE_OUT_OF_RANGE",
                       "escalatable_base_cents may not exceed the order's contract_value_cents")
    common.check_order_not_cancelled(order)
    if store.where("clause", engineered_order_id=oid):
        raise ApiError("ERR_CLAUSE_ALREADY_EXISTS", "the order already carries an escalation clause")
    if data["base_index_month"] >= data["final_window_end_month"]:
        raise ApiError("ERR_INDEX_WINDOW_INVALID",
                       "base_index_month must be strictly earlier than final_window_end_month")
    clause = dict(data)
    clause["engineered_order_id"] = oid
    clause["status"] = "ACTIVE"
    store.insert("clause", clause)
    store.touch("order", order)
    posture.refresh(order)
    return envelope.created(store.public(clause))


@bp.route("/engineered-orders/<oid>/escalation-clauses", methods=["GET"])
def list_order_clauses(oid):
    rbac.authenticate("GET /engineered-orders/{id}/escalation-clauses")
    common.resolve("order", oid)
    limit, offset = envelope.pagination()
    rows = store.where("clause", engineered_order_id=oid)
    return envelope.listing(store.public_list(rows), limit, offset)


@bp.route("/escalation-clauses/<cid>", methods=["GET"])
def get_clause(cid):
    rbac.authenticate("GET /escalation-clauses/{id}")
    return envelope.ok(store.public(common.resolve("clause", cid)))


# --------------------------------------------------------------------------- #
# commodity index points
# --------------------------------------------------------------------------- #

@bp.route("/commodity-index-points", methods=["POST"])
def create_index_point():
    rbac.authenticate("POST /commodity-index-points")
    payload = validation.body()
    data = validation.validate(payload, [
        f("commodity", STRING, required=True, enum=COMMODITIES),
        f("index_month", STRING, required=True),
        f("index_value", NUMBER, required=True),
        f("published_at", DATETIME, required=True),
        f("is_provisional", BOOLEAN, default=False),
    ])
    _check_month(data["index_month"], "index_month")
    if data["index_value"] <= 0:
        raise ApiError("ERR_FIELD_VALUE_OUT_OF_RANGE", "index_value must be above zero")
    for p in store.all_rows("index_point"):
        if p.get("commodity") == data["commodity"] and p.get("index_month") == data["index_month"]:
            raise ApiError("ERR_DUPLICATE_INDEX_POINT",
                           "an index point already exists for that commodity and month")
    point = dict(data)
    store.insert("index_point", point)
    return envelope.created(store.public(point))


@bp.route("/commodity-index-points", methods=["GET"])
def list_index_points():
    rbac.authenticate("GET /commodity-index-points")
    limit, offset = envelope.pagination()
    rows = common.apply_filters(store.all_rows("index_point"), {
        "commodity": common.qstr("commodity"),
        "index_month": common.qstr("index_month"),
        "is_provisional": common.qbool("is_provisional"),
    })
    return envelope.listing(store.public_list(rows), limit, offset)


@bp.route("/commodity-index-points/<pid>", methods=["GET"])
def get_index_point(pid):
    rbac.authenticate("GET /commodity-index-points/{id}")
    return envelope.ok(store.public(common.resolve("index_point", pid)))


@bp.route("/commodity-index-points/<pid>", methods=["PATCH"])
def patch_index_point(pid):
    rbac.authenticate("PATCH /commodity-index-points/{id}")
    point = common.resolve("index_point", pid)
    payload = validation.body()
    data = validation.validate(payload, [
        f("index_value", NUMBER),
        f("published_at", DATETIME),
        f("is_provisional", BOOLEAN),
    ])
    if "index_value" in data and data["index_value"] <= 0:
        raise ApiError("ERR_FIELD_VALUE_OUT_OF_RANGE", "index_value must be above zero")
    for key in ("index_value", "published_at", "is_provisional"):
        if key in data:
            point[key] = data[key]
    return envelope.ok(store.public(point))


# --------------------------------------------------------------------------- #
# escalation adjustments
# --------------------------------------------------------------------------- #

@bp.route("/engineered-orders/<oid>/escalation-adjustments", methods=["POST"])
def create_adjustment(oid):
    rbac.authenticate("POST /engineered-orders/{id}/escalation-adjustments")
    order = common.resolve("order", oid)
    payload = validation.body()
    clause = None
    if payload.get("escalation_clause_id") is not None:
        if not isinstance(payload["escalation_clause_id"], str):
            raise ApiError("ERR_FIELD_TYPE_INVALID", "escalation_clause_id must be of type string")
        clause = common.resolve("clause", payload["escalation_clause_id"],
                                "engineered_order_id", oid)
    data = validation.validate(payload, [
        f("escalation_clause_id", STRING, required=True),
        f("variant", STRING, required=True, enum=VARIANTS),
        f("prepared_by_user_id", STRING, required=True),
        f("expected_engineered_order_version", INTEGER, required=True),
    ])
    validation.check_order_version(data, order)
    common.check_order_not_cancelled(order)
    if clause.get("status") not in ("ACTIVE", "LOCKED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "the escalation clause is %s" % clause.get("status"))
    adjustment = {
        "engineered_order_id": oid,
        "escalation_clause_id": clause["id"],
        "variant": data["variant"],
        "status": "CALCULATED",
        "recalculation_round": 0,
        "prepared_by_user_id": data["prepared_by_user_id"],
        "accepted_by_user_id": None,
        "dispute_reason": None,
    }
    _recompute(adjustment, clause)
    store.insert("adjustment", adjustment)
    store.touch("order", order)
    posture.refresh(order)
    return envelope.created(store.public(adjustment))


@bp.route("/escalation-adjustments", methods=["GET"])
def list_adjustments():
    rbac.authenticate("GET /escalation-adjustments")
    limit, offset = envelope.pagination()
    rows = common.apply_filters(store.all_rows("adjustment"), {
        "engineered_order_id": common.qstr("engineered_order_id"),
        "escalation_clause_id": common.qstr("escalation_clause_id"),
        "variant": common.qstr("variant"),
        "status": common.qstr("status"),
    })
    return envelope.listing(store.public_list(rows), limit, offset)


@bp.route("/escalation-adjustments/<aid>", methods=["GET"])
def get_adjustment(aid):
    rbac.authenticate("GET /escalation-adjustments/{id}")
    return envelope.ok(store.public(common.resolve("adjustment", aid)))


@bp.route("/escalation-adjustments/<aid>/submit", methods=["POST"])
def submit_adjustment(aid):
    rbac.authenticate("POST /escalation-adjustments/{id}/submit")
    adjustment = common.resolve("adjustment", aid)
    order = common.resolve("order", adjustment.get("engineered_order_id"))
    common.check_state("adjustment", adjustment, ("CALCULATED", "RECALCULATING"))
    common.check_order_not_cancelled(order)
    for other in store.where("adjustment", engineered_order_id=order["id"]):
        if other["id"] != aid and other.get("status") in IN_FLIGHT:
            raise ApiError("ERR_ESCALATION_ADJUSTMENT_IN_FLIGHT",
                           "adjustment %s is already with the customer" % other["id"])
    adjustment["status"] = "SUBMITTED_TO_CUSTOMER"
    store.touch("adjustment", adjustment)
    store.touch("order", order)
    posture.refresh(order)
    return envelope.ok(store.public(adjustment))


@bp.route("/escalation-adjustments/<aid>/accept", methods=["POST"])
def accept_adjustment(aid):
    actor = rbac.authenticate("POST /escalation-adjustments/{id}/accept")
    adjustment = common.resolve("adjustment", aid)
    order = common.resolve("order", adjustment.get("engineered_order_id"))
    rbac.check_sod(actor, adjustment.get("prepared_by_user_id"))
    payload = validation.body()
    data = validation.validate(payload, [f("accepted_by_user_id", STRING, required=True)])
    if data["accepted_by_user_id"] == adjustment.get("prepared_by_user_id"):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "accepted_by_user_id must differ from prepared_by_user_id")
    common.check_state("adjustment", adjustment, ("SUBMITTED_TO_CUSTOMER",))
    common.check_order_not_cancelled(order)
    if adjustment.get("variant") == "FINAL":
        common.check_design_released(order)
    for other in store.where("adjustment", escalation_clause_id=adjustment.get("escalation_clause_id")):
        if other["id"] != aid and other.get("status") in ("SUBMITTED_TO_CUSTOMER", "DISPUTED", "RECALCULATING"):
            raise ApiError("ERR_ESCALATION_ADJUSTMENT_IN_FLIGHT",
                           "adjustment %s is still in flight on this clause" % other["id"])
    adjustment["status"] = "ACCEPTED"
    adjustment["accepted_by_user_id"] = data["accepted_by_user_id"]
    store.touch("adjustment", adjustment)
    store.touch("order", order)
    posture.refresh(order)
    common.rebill_stages(order)
    return envelope.ok(store.public(adjustment))


@bp.route("/escalation-adjustments/<aid>/dispute", methods=["POST"])
def dispute_adjustment(aid):
    rbac.authenticate("POST /escalation-adjustments/{id}/dispute")
    adjustment = common.resolve("adjustment", aid)
    order = common.resolve("order", adjustment.get("engineered_order_id"))
    payload = validation.body()
    data = validation.validate(payload, [f("dispute_reason", STRING, required=True)])
    if not data["dispute_reason"].strip():
        raise ApiError("ERR_MISSING_REQUIRED_FIELD", "dispute_reason must be non-empty")
    common.check_state("adjustment", adjustment, ("SUBMITTED_TO_CUSTOMER",))
    common.check_order_not_cancelled(order)
    adjustment["status"] = "DISPUTED"
    adjustment["dispute_reason"] = data["dispute_reason"]
    store.touch("adjustment", adjustment)
    store.touch("order", order)
    posture.refresh(order)
    return envelope.ok(store.public(adjustment))


@bp.route("/escalation-adjustments/<aid>/recalculate", methods=["POST"])
def recalculate_adjustment(aid):
    rbac.authenticate("POST /escalation-adjustments/{id}/recalculate")
    adjustment = common.resolve("adjustment", aid)
    order = common.resolve("order", adjustment.get("engineered_order_id"))
    payload = validation.body()
    data = validation.validate(payload, [f("variant", STRING, enum=VARIANTS)])
    common.check_state("adjustment", adjustment, ("DISPUTED",))
    common.check_order_not_cancelled(order)
    clause = store.get("clause", adjustment.get("escalation_clause_id"))
    if clause is None or clause.get("status") not in ("ACTIVE", "LOCKED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "the escalation clause is not amendable")
    variant = data.get("variant", adjustment.get("variant"))
    for commodity, weight_field, _ in calc.COMMODITY_FIELDS:
        if (clause.get(weight_field) or 0) == 0:
            continue
        if not calc.usable_index_points(commodity, variant):
            raise ApiError("ERR_INDEX_POINT_MISSING",
                           "no usable %s index point at the current clock" % commodity)
    adjustment["variant"] = variant
    adjustment["status"] = "RECALCULATING"
    adjustment["recalculation_round"] = (adjustment.get("recalculation_round") or 0) + 1
    _recompute(adjustment, clause)
    store.touch("adjustment", adjustment)
    posture.refresh(order)
    return envelope.ok(store.public(adjustment))


@bp.route("/escalation-adjustments/<aid>/withdraw", methods=["POST"])
def withdraw_adjustment(aid):
    rbac.authenticate("POST /escalation-adjustments/{id}/withdraw")
    adjustment = common.resolve("adjustment", aid)
    order = common.resolve("order", adjustment.get("engineered_order_id"))
    was_accepted = adjustment.get("status") == "ACCEPTED"
    common.check_state("adjustment", adjustment,
                       ("CALCULATED", "SUBMITTED_TO_CUSTOMER", "DISPUTED", "RECALCULATING", "ACCEPTED"))
    if was_accepted:
        if order.get("engineering_status") == "ENG_CLOSED":
            raise ApiError("ERR_ENGINEERING_CLOSED", "engineering is closed on this order")
        for r in store.where("release", engineered_order_id=order["id"]):
            if r.get("status") == "DELIVERED":
                raise ApiError("ERR_INVALID_STATE_TRANSITION",
                               "a shipment release has already been delivered")
    adjustment["status"] = "WITHDRAWN"
    store.touch("adjustment", adjustment)
    store.touch("order", order)
    posture.refresh(order)
    if was_accepted:
        common.rebill_stages(order)
    return envelope.ok(store.public(adjustment))
