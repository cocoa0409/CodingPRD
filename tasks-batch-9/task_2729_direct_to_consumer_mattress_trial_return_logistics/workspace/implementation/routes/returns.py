"""Return cases: request, cancel, inspect, disposition, refund summary."""
from flask import Blueprint

from db import base_record, db, now, ordered, paginate, touch
from errors import api_error
from middleware import require, require_customer_owner
from response import collection, single
from serialize import (DISPOSITION_ASSIGNMENT, RETURN_CASE, dump, dump_many)
from services import calc, entities, pricing, selection
from validate import Fields, Query

bp = Blueprint("returns", __name__)

REASON_CODES = ("COMFORT", "DAMAGE", "PRICE", "OTHER")
LOGISTICS_STATUSES = ("REQUESTED", "PICKUP_SCHEDULED", "PICKED_UP",
                      "INSPECTED", "DISPOSITIONED", "CANCELLED")
FINANCIAL_STATUSES = ("PENDING", "AUTHORIZED", "RELEASED", "VOID")
DISPOSITIONS = ("PENDING", "DONATION", "RECYCLE")
REQUESTED_DISPOSITIONS = ("DONATION", "RECYCLE")
PRICING_FIELDS = ("proration_deduction_cents", "bundle_unwind_cents",
                  "damage_offset_cents", "provisional_refund_cents",
                  "final_refund_cents")


def _damage_bypass(order, reason_code):
    """The only break-in bypass: a damage return backed by a live shipping
    damage claim."""
    if reason_code != "DAMAGE":
        return False
    return any(c["order_id"] == order["id"]
               and c["claim_type"] == "SHIPPING_DAMAGE"
               and c["status"] in ("SUBMITTED", "EVIDENCE_REQUESTED",
                                   "APPROVED")
               for c in db.quality_claims.values())


@bp.route("/return-cases", methods=["POST"])
@require("Customer", "TrialSupportAgent")
def create_return_case():
    fields = Fields("order_id", "reason_code")
    order_id = fields.reference("order_id")
    reason_code = fields.enum("reason_code", REASON_CODES)
    order = entities.get_order(order_id)
    require_customer_owner(order["customer_id"], "trial order")

    active = entities.active_return_cases(order["id"])
    if not active:
        if (order["fulfillment_status"] not in ("DELIVERED",
                                                "DAMAGED_REPORTED")
                or order["trial_status"] not in ("BREAK_IN", "TRIAL_ACTIVE",
                                                 "TRIAL_EXPIRED")):
            raise api_error("ERR_INVALID_ORDER_STATE",
                            "A return cannot be opened on this order from its "
                            "current state")
    elif order["delivered_at"] is None:
        raise api_error("ERR_INVALID_ORDER_STATE",
                        "A return cannot be opened on an order that was never "
                        "delivered")

    clock = now()
    if not _damage_bypass(order, reason_code):
        if (order["break_in_ends_at"] is None
                or clock < order["break_in_ends_at"]):
            raise api_error("ERR_BREAK_IN_NOT_ELAPSED",
                            "The break-in period has not elapsed yet")
    if order["trial_ends_at"] is None or clock >= order["trial_ends_at"]:
        raise api_error("ERR_TRIAL_WINDOW_EXPIRED",
                        "The trial window has closed")
    if active:
        raise api_error("ERR_DUPLICATE_ACTIVE_RETURN",
                        "A live return case already exists on this order")

    case = base_record()
    case.update({
        "order_id": order["id"],
        "reason_code": reason_code,
        "requested_at": clock,
        "logistics_status": "REQUESTED",
        "financial_status": "PENDING",
        "picked_up_at": None,
        "nights_used": None,
        "condition_grade": None,
        "soil_flag": False,
        "accessory_returned": False,
        "disposition": "PENDING",
        "proration_deduction_cents": None,
        "bundle_unwind_cents": None,
        "damage_offset_cents": None,
        "provisional_refund_cents": None,
        "final_refund_cents": None,
    })
    db.return_cases[case["id"]] = case
    order["trial_status"] = "RETURN_REQUESTED"
    touch(order)
    return single(dump(case, RETURN_CASE), 201)


@bp.route("/return-cases/<case_id>", methods=["GET"])
@require("Customer", "TrialSupportAgent", "LogisticsCoordinator",
         "FinanceController", "PlatformAdmin")
def read_return_case(case_id):
    case = entities.get_return_case(case_id)
    order = entities.get_order(case["order_id"])
    require_customer_owner(order["customer_id"], "return case")
    return single(dump(case, RETURN_CASE), 200)


@bp.route("/return-cases", methods=["GET"])
@require("Customer", "TrialSupportAgent", "LogisticsCoordinator",
         "FinanceController", "PlatformAdmin")
def list_return_cases():
    query = Query("order_id", "logistics_status", "financial_status",
                  "disposition")
    limit, offset = query.page()
    order_id = query.string("order_id")
    logistics_status = query.enum("logistics_status", LOGISTICS_STATUSES)
    financial_status = query.enum("financial_status", FINANCIAL_STATUSES)
    disposition = query.enum("disposition", DISPOSITIONS)
    matches = ordered([
        c for c in db.return_cases.values()
        if (order_id is None or c["order_id"] == order_id)
        and (logistics_status is None
             or c["logistics_status"] == logistics_status)
        and (financial_status is None
             or c["financial_status"] == financial_status)
        and (disposition is None or c["disposition"] == disposition)
    ])
    page, total = paginate(matches, limit, offset)
    return collection(dump_many(page, RETURN_CASE), limit, offset, total)


@bp.route("/return-cases/<case_id>/refund-summary", methods=["GET"])
@require("Customer", "TrialSupportAgent", "FinanceController", "PlatformAdmin")
def refund_summary(case_id):
    case = entities.get_return_case(case_id)
    order = entities.get_order(case["order_id"])
    require_customer_owner(order["customer_id"], "return case")
    model = entities.model_of_order(order)
    bundle = entities.bundle_of_order(order)

    provisional = case["provisional_refund_cents"]
    final = case["final_refund_cents"]
    if case["condition_grade"] is not None and case["nights_used"] is not None:
        priced = pricing.price_return_case(case, order, model, bundle)
        if provisional is None:
            provisional = priced["provisional_refund_cents"]
        if final is None:
            final = priced["final_refund_cents"]
    variant = "FINAL" if case["final_refund_cents"] is not None \
        else "PROVISIONAL"
    delta = None
    if provisional is not None and final is not None:
        delta = provisional - final
    return single({
        "variant_in_effect": variant,
        "gross_refundable_cents": order["paid_amount_cents"],
        "proration_deduction_cents": case["proration_deduction_cents"],
        "bundle_unwind_cents": case["bundle_unwind_cents"],
        "damage_offset_cents": case["damage_offset_cents"],
        "provisional_refund_cents": provisional,
        "final_refund_cents": final,
        "variant_delta_cents": delta,
    }, 200)


@bp.route("/return-cases/<case_id>/cancel", methods=["POST"])
@require("Customer", "TrialSupportAgent")
def cancel_return_case(case_id):
    Fields()
    case = entities.get_return_case(case_id)
    order = entities.get_order(case["order_id"])
    require_customer_owner(order["customer_id"], "return case")
    if (case["logistics_status"] not in ("REQUESTED", "PICKUP_SCHEDULED")
            or case["financial_status"] != "PENDING"):
        raise api_error("ERR_INVALID_RETURN_STATE",
                        "This return case can no longer be cancelled")
    clock = now()
    case["logistics_status"] = "CANCELLED"
    case["financial_status"] = "VOID"
    for field in PRICING_FIELDS:
        case[field] = None
    touch(case)

    for appointment in entities.appointments_of_case(case["id"]):
        if appointment["status"] != "BOOKED":
            continue
        appointment["status"] = "CANCELLED"
        touch(appointment)
        route = db.pickup_routes.get(appointment["route_id"])
        if route is not None:
            entities.refresh_route_capacity(route)
            touch(route)

    if order["trial_ends_at"] is not None and clock >= order["trial_ends_at"]:
        order["trial_status"] = "TRIAL_EXPIRED"
    else:
        order["trial_status"] = "TRIAL_ACTIVE"
    touch(order)
    return single(dump(case, RETURN_CASE), 200)


@bp.route("/return-cases/<case_id>/inspect", methods=["POST"])
@require("LogisticsCoordinator")
def inspect_return_case(case_id):
    fields = Fields("condition_grade", "soil_flag", "accessory_returned")
    condition_grade = fields.enum("condition_grade", calc.CONDITION_GRADES)
    soil_flag = fields.boolean("soil_flag", required=False, default=False)
    accessory_returned = fields.boolean("accessory_returned", required=False,
                                        default=False)
    case = entities.get_return_case(case_id)
    if case["logistics_status"] != "PICKED_UP":
        raise api_error("ERR_INVALID_RETURN_STATE",
                        "Only a PICKED_UP return case can be inspected")
    case["condition_grade"] = condition_grade
    case["soil_flag"] = soil_flag
    case["accessory_returned"] = accessory_returned
    order, model, bundle = pricing.priced_context(case)
    priced = pricing.price_return_case(case, order, model, bundle)
    case["bundle_unwind_cents"] = priced["bundle_unwind_cents"]
    case["damage_offset_cents"] = priced["damage_offset_cents"]
    case["proration_deduction_cents"] = priced["provisional_proration_cents"]
    case["provisional_refund_cents"] = priced["provisional_refund_cents"]
    case["logistics_status"] = "INSPECTED"
    touch(case)
    return single(dump(case, RETURN_CASE), 200)


@bp.route("/return-cases/<case_id>/disposition", methods=["POST"])
@require("LogisticsCoordinator")
def disposition_return_case(case_id):
    fields = Fields("disposition", "intake_date")
    requested = fields.enum("disposition", REQUESTED_DISPOSITIONS)
    intake_date = fields.date("intake_date")
    case = entities.get_return_case(case_id)
    if (case["logistics_status"] != "INSPECTED"
            or case["disposition"] != "PENDING"):
        raise api_error("ERR_INVALID_RETURN_STATE",
                        "Only an INSPECTED, undispositioned return case can be "
                        "dispositioned")
    order = entities.get_order(case["order_id"])
    model = entities.model_of_order(order)
    units = calc.units_for_size(model["size"])
    partner, fallback = selection.select_partner(
        case, order, model, requested, intake_date, units)

    disposition_type = ("DONATION" if partner["partner_type"] == "CHARITY"
                        else "RECYCLE")
    assignment = base_record()
    assignment.update({
        "return_case_id": case["id"],
        "partner_id": partner["id"],
        "intake_date": intake_date,
        "disposition_type": disposition_type,
        "units": units,
        "fee_cents": units * partner["recycle_fee_cents_per_unit"],
        "fallback_applied": fallback,
        "status": "ASSIGNED",
    })
    db.disposition_assignments[assignment["id"]] = assignment
    case["disposition"] = disposition_type
    case["logistics_status"] = "DISPOSITIONED"
    touch(case)
    return single(dump(assignment, DISPOSITION_ASSIGNMENT), 201)
