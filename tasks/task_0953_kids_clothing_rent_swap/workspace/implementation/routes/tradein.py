"""Pipeline T: from outgrown garment to account credit (PRD 3.9)."""

from flask import Blueprint

import auth
import calc
import constants as K
import envelope
import ledger
import listing
import lookup
import serialize
import shape
import store
import timeutil
import tradein_ops
from errors import ApiError

bp = Blueprint("tradein", __name__)


@bp.post("/kidswear/trade-in-submissions")
def create_submission():
    caller = auth.gate("Member")
    body = shape.body_json()
    member_id = shape.id_string(body, "member_id")
    declared_item_count = shape.integer(body, "declared_item_count")
    auth.own(caller, member_id)
    member = lookup.member(member_id)
    lookup.standing(member, block_pending=True)
    lookup.pause_gate_t(member)
    if (declared_item_count < K.TRADEIN_MIN_ITEMS_PER_SUBMISSION
            or declared_item_count > K.TRADEIN_MAX_ITEMS_PER_SUBMISSION):
        raise ApiError("ERR_TRADE_IN_ITEM_COUNT_INVALID")
    row = store.insert("submissions", {
        "member_id": member_id,
        "inbound_shipment_id": None,
        "status": "DRAFT",
        "declared_item_count": declared_item_count,
        "credited_total_cents": 0,
        "uncapped_total_cents": 0,
        "election_deadline_at": None,
    })
    return envelope.created(serialize.submission(row))


@bp.get("/kidswear/trade-in-submissions")
def list_submissions():
    caller = auth.gate("Member", "PlatformAdmin", "WarehouseOperator", "BillingAgent",
                       "GradingTechnician", "MerchandisePlanner", "LogisticsCoordinator")
    rows = store.all_rows("submissions")
    rows = listing.scope_to_member(caller, rows, lambda r: r["member_id"])
    rows = listing.eq(rows, "member_id", shape.query_str("member_id"))
    rows = listing.eq(rows, "inbound_shipment_id", shape.query_str("inbound_shipment_id"))
    rows = listing.eq(rows, "status", shape.query_member("status", K.TRADE_IN_SUBMISSION_STATUSES))
    return envelope.listing(rows, serialize.submission)


@bp.get("/kidswear/trade-in-submissions/<submission_id>")
def read_submission(submission_id):
    caller = auth.gate("Member", "PlatformAdmin", "WarehouseOperator", "BillingAgent",
                       "GradingTechnician", "MerchandisePlanner")
    row = lookup.submission(submission_id)
    auth.own(caller, row["member_id"])
    return envelope.ok(serialize.submission(row))


@bp.post("/kidswear/trade-in-submissions/<submission_id>/items")
def add_item(submission_id):
    caller = auth.gate("Member")
    body = shape.body_json()
    declared_brand_tier = shape.enum_in(body, "declared_brand_tier", K.BRAND_TIERS)
    declared_size_code = shape.enum_in(body, "declared_size_code", K.SIZE_LADDER)
    submission = lookup.submission(submission_id)
    auth.own(caller, submission["member_id"])
    member = lookup.member(submission["member_id"])
    lookup.standing(member, block_pending=True)
    lookup.pause_gate_t(member)
    if submission["status"] != "DRAFT":
        raise ApiError("ERR_TRADE_IN_INVALID_STATE")
    if len(tradein_ops.submission_items(submission_id)) >= submission["declared_item_count"]:
        raise ApiError("ERR_TRADE_IN_ITEM_COUNT_INVALID")
    row = store.insert("trade_in_items", {
        "submission_id": submission_id,
        "absorbed_unit_id": None,
        "declared_brand_tier": declared_brand_tier,
        "declared_size_code": declared_size_code,
        "grading_status": "PENDING",
        "disposition_status": "NONE",
        "assessed_grade": None,
        "demand_band": "MEDIUM",
        "credit_cents": 0,
        "granted_credit_cents": 0,
    })
    return envelope.created(serialize.trade_in_item(row))


@bp.post("/kidswear/trade-in-submissions/<submission_id>/issue-label")
def issue_label(submission_id):
    auth.gate("LogisticsCoordinator")
    body = shape.body_json()
    label_id = shape.id_string(body, "label_id")
    submission = lookup.submission(submission_id)
    label = lookup.label(label_id)
    member = lookup.member(submission["member_id"])
    lookup.standing(member, block_pending=True, block_delinquent=True)
    lookup.pause_gate_t(member)
    if submission["status"] != "DRAFT":
        raise ApiError("ERR_TRADE_IN_INVALID_STATE")
    if label["direction"] != "TRADE_IN_INBOUND":
        raise ApiError("ERR_LABEL_DIRECTION_MISMATCH")
    if label["status"] != "ISSUED":
        raise ApiError("ERR_LABEL_INVALID_STATE")
    if len(tradein_ops.submission_items(submission_id)) != submission["declared_item_count"]:
        raise ApiError("ERR_TRADE_IN_ITEM_COUNT_INVALID")
    shipment = store.insert("shipments", {
        "member_id": member["id"],
        "label_id": label_id,
        "direction": "TRADE_IN_INBOUND",
        "status": "CREATED",
        "item_count": submission["declared_item_count"],
        "shipped_at": None,
        "delivered_at": None,
        "ever_scanned": False,
    })
    submission["inbound_shipment_id"] = shipment["id"]
    submission["status"] = "LABEL_ISSUED"
    store.touch(submission)
    return envelope.ok(serialize.submission(submission))


@bp.post("/kidswear/trade-in-submissions/<submission_id>/finalize")
def finalize(submission_id):
    auth.gate("BillingAgent")
    submission = lookup.submission(submission_id)
    member = lookup.member(submission["member_id"])
    lookup.standing(member, block_pending=True)
    if submission["status"] != "GRADING":
        raise ApiError("ERR_TRADE_IN_INVALID_STATE")
    items = tradein_ops.submission_items(submission_id)
    for item in items:
        if item["grading_status"] not in ("GRADED", "REJECTED"):
            raise ApiError("ERR_TRADE_IN_INVALID_STATE",
                           "Every garment must be graded or rejected first.")
    plan = lookup.plan(member["plan_id"])
    graded = [i for i in items if i["grading_status"] == "GRADED"]
    graded.sort(key=lambda i: (-i["credit_cents"], store.order_key(i)))
    uncapped, grants, credited_total = calc.tradein_cap_waterfall(graded, plan["tier"])
    for item in graded:
        item["granted_credit_cents"] = grants[item["id"]]
        item["grading_status"] = "CREDITED"
        store.touch(item)
    submission["uncapped_total_cents"] = uncapped
    submission["credited_total_cents"] = credited_total
    submission["election_deadline_at"] = timeutil.add_days(
        timeutil.now(), K.TRADEIN_DISPOSITION_ELECTION_DAYS)
    submission["status"] = "CREDITED"
    store.touch(submission)
    if credited_total > 0:
        ledger.new_credit(member, credited_total, submission_id)
        if member["auto_apply_credit"]:
            ledger.apply_credit_waterfall(member)
    tradein_ops.maybe_close_submission(submission)
    return envelope.ok(serialize.submission(submission))


@bp.get("/kidswear/trade-in-items")
def list_items():
    caller = auth.gate("Member", "PlatformAdmin", "GradingTechnician",
                       "MerchandisePlanner", "BillingAgent", "WarehouseOperator")
    rows = store.all_rows("trade_in_items")
    rows = listing.scope_to_member(
        caller, rows,
        lambda r: (store.get("submissions", r["submission_id"]) or {}).get("member_id"))
    rows = listing.eq(rows, "submission_id", shape.query_str("submission_id"))
    rows = listing.eq(rows, "absorbed_unit_id", shape.query_str("absorbed_unit_id"))
    rows = listing.eq(rows, "grading_status",
                      shape.query_member("grading_status", K.TRADE_IN_GRADING_STATUSES))
    rows = listing.eq(rows, "disposition_status",
                      shape.query_member("disposition_status", K.TRADE_IN_DISPOSITION_STATUSES))
    return envelope.listing(rows, serialize.trade_in_item)


@bp.get("/kidswear/trade-in-items/<trade_in_item_id>")
def read_item(trade_in_item_id):
    caller = auth.gate("Member", "PlatformAdmin", "GradingTechnician",
                       "MerchandisePlanner", "BillingAgent")
    item = lookup.trade_in_item(trade_in_item_id)
    submission = lookup.submission(item["submission_id"])
    auth.own(caller, submission["member_id"])
    return envelope.ok(serialize.trade_in_item(item))


@bp.post("/kidswear/trade-in-items/<trade_in_item_id>/absorb")
def absorb(trade_in_item_id):
    auth.gate("MerchandisePlanner")
    body = shape.body_json()
    style_id = shape.id_string(body, "style_id")
    item = lookup.trade_in_item(trade_in_item_id)
    style = lookup.style(style_id)
    submission = lookup.submission(item["submission_id"])
    if item["disposition_status"] != "NONE" or item["grading_status"] != "CREDITED":
        raise ApiError("ERR_TRADE_IN_INVALID_STATE")
    if style["status"] != "ACTIVE" or style["size_code"] != item["declared_size_code"]:
        raise ApiError("ERR_ABSORB_STYLE_MISMATCH")
    unit = store.insert("units", {
        "style_id": style_id,
        "capsule_id": None,
        "state": "IN_STOCK",
        "acquisition_source": "TRADE_IN_ABSORBED",
        "acquired_at": timeutil.now(),
        "cycles_completed": 0,
        "cumulative_cleaning_cost_cents": 0,
        "current_grade": item["assessed_grade"],
        "retired_reason": None,
        "retirement_eligible": False,
    })
    style["units_ever_acquired"] += 1
    store.touch(style)
    item["absorbed_unit_id"] = unit["id"]
    item["disposition_status"] = "ABSORBED"
    store.touch(item)
    tradein_ops.maybe_close_submission(submission)
    return envelope.created(serialize.unit(unit))


@bp.post("/kidswear/trade-in-items/<trade_in_item_id>/elect-disposition")
def elect_disposition(trade_in_item_id):
    caller = auth.gate("Member")
    body = shape.body_json()
    disposition = shape.enum_in(body, "disposition", K.TRADE_IN_ELECTIONS)
    item = lookup.trade_in_item(trade_in_item_id)
    submission = lookup.submission(item["submission_id"])
    auth.own(caller, submission["member_id"])
    member = lookup.member(submission["member_id"])
    lookup.standing(member, block_pending=True)
    if item["disposition_status"] != "AWAITING_ELECTION":
        raise ApiError("ERR_TRADE_IN_ITEM_NOT_REJECTED")
    deadline = submission["election_deadline_at"]
    if deadline is not None and timeutil.now() > deadline:
        raise ApiError("ERR_ELECTION_DEADLINE_PASSED")
    item["disposition_status"] = disposition
    store.touch(item)
    if disposition == "RETURN_TO_MEMBER":
        ledger.new_charge(member, "SHIPPING_FEE", K.TRADEIN_RETURN_SHIP_FEE_CENTS, None)
    tradein_ops.maybe_close_submission(submission)
    return envelope.ok(serialize.trade_in_item(item))


@bp.post("/kidswear/trade-in-items/<trade_in_item_id>/apply-default-disposition")
def apply_default_disposition(trade_in_item_id):
    auth.gate("PlatformAdmin")
    item = lookup.trade_in_item(trade_in_item_id)
    submission = lookup.submission(item["submission_id"])
    if item["disposition_status"] != "AWAITING_ELECTION":
        raise ApiError("ERR_TRADE_IN_INVALID_STATE")
    deadline = submission["election_deadline_at"]
    if deadline is None or timeutil.now() <= deadline:
        raise ApiError("ERR_ELECTION_NOT_DUE")
    item["disposition_status"] = K.TRADEIN_DEFAULT_DISPOSITION
    store.touch(item)
    tradein_ops.maybe_close_submission(submission)
    return envelope.ok(serialize.trade_in_item(item))
