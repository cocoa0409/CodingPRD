"""Refund authorizations: authorize, release, void."""
from flask import Blueprint, g

from db import base_record, db, now, ordered, paginate, touch
from errors import api_error
from middleware import require, require_customer_owner
from response import collection, single
from serialize import REFUND_AUTHORIZATION, dump, dump_many
from services import entities, pricing
from validate import Fields, Query

bp = Blueprint("refunds", __name__)

REFUND_STATUSES = ("AUTHORIZED", "RELEASED", "VOIDED")


def _refunds_of_case(case_id):
    return ordered([r for r in db.refund_authorizations.values()
                    if r["return_case_id"] == case_id])


@bp.route("/refund-authorizations", methods=["POST"])
@require("FinanceController")
def create_refund_authorization():
    fields = Fields("return_case_id", "expected_return_case_version",
                    "supersedes_refund_id")
    return_case_id = fields.reference("return_case_id")
    expected_version = fields.integer("expected_return_case_version")
    supersedes_refund_id = fields.reference("supersedes_refund_id",
                                           required=False, default=None)
    case = entities.get_return_case(return_case_id)
    superseded = None
    if supersedes_refund_id is not None:
        superseded = entities.get_refund(supersedes_refund_id)

    if case["logistics_status"] != "DISPOSITIONED":
        raise api_error("ERR_INVALID_RETURN_STATE",
                        "A refund can only be authorized on a DISPOSITIONED "
                        "return case")
    delivered_intake = any(
        a["return_case_id"] == case["id"] and a["status"] == "DELIVERED"
        for a in db.disposition_assignments.values())
    if not delivered_intake:
        raise api_error("ERR_DISPOSITION_NOT_CONFIRMED",
                        "The disposition partner has not confirmed intake")
    if expected_version != case["version"]:
        raise api_error("ERR_STALE_RETURN_CASE_VERSION",
                        "expected_return_case_version does not match the "
                        "return case's current version")
    if entities.open_quality_claims(case["order_id"]):
        raise api_error("ERR_OPEN_QUALITY_CLAIM",
                        "An unresolved quality claim is open on this order")

    existing = _refunds_of_case(case["id"])
    if superseded is not None:
        if (superseded["return_case_id"] != case["id"]
                or superseded["status"] != "VOIDED"):
            raise api_error("ERR_REFUND_SUPERSEDE_INVALID",
                            "supersedes_refund_id must name a voided "
                            "authorization on this return case")
    elif any(r["status"] != "VOIDED" for r in existing):
        raise api_error("ERR_REFUND_SUPERSEDE_INVALID",
                        "This return case already carries a live refund "
                        "authorization")

    order, model, bundle = pricing.priced_context(case)
    priced = pricing.price_return_case(case, order, model, bundle)
    net = priced["final_refund_cents"]
    if net <= 0:
        raise api_error("ERR_NO_REFUNDABLE_BALANCE",
                        "There is no refundable balance on this return")

    record = base_record()
    record.update({
        "return_case_id": case["id"],
        "order_id": case["order_id"],
        "supersedes_refund_id": supersedes_refund_id,
        "gross_refundable_cents": priced["gross_refundable_cents"],
        "proration_deduction_cents": priced["final_proration_cents"],
        "bundle_unwind_cents": priced["bundle_unwind_cents"],
        "damage_offset_cents": priced["damage_offset_cents"],
        "net_refund_cents": net,
        "authorized_by_user_id": g.user_id,
        "released_by_user_id": None,
        "released_at": None,
        "voided_at": None,
        "void_reason": None,
        "status": "AUTHORIZED",
    })
    db.refund_authorizations[record["id"]] = record

    case["proration_deduction_cents"] = priced["final_proration_cents"]
    case["bundle_unwind_cents"] = priced["bundle_unwind_cents"]
    case["damage_offset_cents"] = priced["damage_offset_cents"]
    case["final_refund_cents"] = net
    case["financial_status"] = "AUTHORIZED"
    touch(case)
    return single(dump(record, REFUND_AUTHORIZATION), 201)


@bp.route("/refund-authorizations/<refund_id>", methods=["GET"])
@require("Customer", "FinanceController", "PlatformAdmin")
def read_refund_authorization(refund_id):
    refund = entities.get_refund(refund_id)
    order = entities.get_order(refund["order_id"])
    require_customer_owner(order["customer_id"], "refund authorization")
    return single(dump(refund, REFUND_AUTHORIZATION), 200)


@bp.route("/refund-authorizations", methods=["GET"])
@require("Customer", "FinanceController", "PlatformAdmin")
def list_refund_authorizations():
    query = Query("order_id", "return_case_id", "supersedes_refund_id",
                  "status")
    limit, offset = query.page()
    order_id = query.string("order_id")
    return_case_id = query.string("return_case_id")
    supersedes_refund_id = query.string("supersedes_refund_id")
    status = query.enum("status", REFUND_STATUSES)
    matches = ordered([
        r for r in db.refund_authorizations.values()
        if (order_id is None or r["order_id"] == order_id)
        and (return_case_id is None or r["return_case_id"] == return_case_id)
        and (supersedes_refund_id is None
             or r["supersedes_refund_id"] == supersedes_refund_id)
        and (status is None or r["status"] == status)
    ])
    page, total = paginate(matches, limit, offset)
    return collection(dump_many(page, REFUND_AUTHORIZATION), limit, offset,
                      total)


@bp.route("/refund-authorizations/<refund_id>/release", methods=["POST"])
@require("FinanceController")
def release_refund_authorization(refund_id):
    Fields()
    refund = entities.get_refund(refund_id)
    if refund["status"] != "AUTHORIZED":
        raise api_error("ERR_INVALID_REFUND_STATE",
                        "Only an AUTHORIZED refund can be released")
    if g.user_id == refund["authorized_by_user_id"]:
        raise api_error("ERR_SEGREGATION_OF_DUTIES",
                        "The authorizing controller may not also release the "
                        "refund")
    order = entities.get_order(refund["order_id"])
    case = entities.get_return_case(refund["return_case_id"])
    refund["status"] = "RELEASED"
    refund["released_by_user_id"] = g.user_id
    refund["released_at"] = now()
    touch(refund)

    order["refunded_total_cents"] = (order["refunded_total_cents"]
                                     + refund["net_refund_cents"])
    order["outstanding_refundable_cents"] = 0
    order["retained_amount_cents"] = (order["paid_amount_cents"]
                                      - order["refunded_total_cents"])
    touch(order)
    case["financial_status"] = "RELEASED"
    touch(case)
    return single(dump(refund, REFUND_AUTHORIZATION), 200)


@bp.route("/refund-authorizations/<refund_id>/void", methods=["POST"])
@require("FinanceController")
def void_refund_authorization(refund_id):
    fields = Fields("void_reason")
    void_reason = fields.string("void_reason")
    refund = entities.get_refund(refund_id)
    if refund["status"] not in ("AUTHORIZED", "RELEASED"):
        raise api_error("ERR_INVALID_REFUND_STATE",
                        "A voided refund cannot be voided again")
    was_released = refund["status"] == "RELEASED"
    case = entities.get_return_case(refund["return_case_id"])
    refund["status"] = "VOIDED"
    refund["voided_at"] = now()
    refund["void_reason"] = void_reason
    touch(refund)

    if was_released:
        order = entities.get_order(refund["order_id"])
        order["refunded_total_cents"] = (order["refunded_total_cents"]
                                        - refund["net_refund_cents"])
        order["outstanding_refundable_cents"] = (
            order["paid_amount_cents"] - order["refunded_total_cents"])
        order["retained_amount_cents"] = 0
        touch(order)
    case["financial_status"] = "VOID"
    touch(case)
    return single(dump(refund, REFUND_AUTHORIZATION), 200)
