"""Quality claims: shipping damage, compression recovery, warranty indentation."""
from flask import Blueprint, g

from db import base_record, db, now, ordered, paginate, touch
from errors import api_error, invalid
from middleware import require, require_customer_owner
from response import collection, single
from serialize import QUALITY_CLAIM, TRIAL_ORDER, dump, dump_many
from services import calc, entities, orders as order_service
from util import whole_days
from validate import Fields, Query

bp = Blueprint("claims", __name__)

CLAIM_TYPES = ("SHIPPING_DAMAGE", "COMPRESSION_RECOVERY",
               "WARRANTY_INDENTATION")
DELIVERY_CLAIM_TYPES = ("SHIPPING_DAMAGE", "COMPRESSION_RECOVERY")
MEASUREMENT_METHODS = ("STRAIGHTEDGE_PHOTO", "LASER_SCAN")
RESOLUTIONS = ("REPLACEMENT", "CREDIT", "DENIED")
CLAIM_STATUSES = ("SUBMITTED", "EVIDENCE_REQUESTED", "APPROVED", "DENIED",
                  "SETTLED", "WITHDRAWN")
CLAIM_RESOLUTIONS = ("PENDING", "REPLACEMENT", "CREDIT", "DENIED")


def _check_evidence_floor(claim):
    needed = calc.required_photos(claim["claim_type"],
                                 claim["measurement_method"])
    if claim["photo_evidence_count"] < needed:
        raise api_error("ERR_INSUFFICIENT_EVIDENCE",
                        "At least %d photographs are required" % needed)


def _check_indentation(claim, order, model):
    if claim["claim_type"] != "WARRANTY_INDENTATION":
        return
    if (order["trial_status"] != "KEPT"
            or claim["measured_indentation_mm"] is None
            or claim["measured_indentation_mm"]
            < model["indentation_warranty_threshold_mm"]):
        raise api_error(
            "ERR_INDENTATION_BELOW_THRESHOLD",
            "Warranty indentation claims require a kept mattress measuring at "
            "least the model's warranty threshold")


def _revert_fulfillment_if_quiet(order, claim):
    """A CREDIT or DENIED outcome releases the damage flag only when no other
    complaint on the order is still open; a CLOSED or REPLACED order is left
    exactly as it is."""
    if order["fulfillment_status"] != "DAMAGED_REPORTED":
        return
    if entities.open_quality_claims(order["id"], exclude_claim_id=claim["id"]):
        return
    order["fulfillment_status"] = "DELIVERED"
    touch(order)


@bp.route("/quality-claims", methods=["POST"])
@require("Customer", "TrialSupportAgent")
def create_quality_claim():
    fields = Fields("order_id", "claim_type", "photo_evidence_count",
                    "measurement_method", "measured_indentation_mm")
    order_id = fields.reference("order_id")
    claim_type = fields.enum("claim_type", CLAIM_TYPES)
    photo_evidence_count = fields.integer("photo_evidence_count", minimum=0)
    measurement_method = fields.enum("measurement_method",
                                     MEASUREMENT_METHODS, required=False,
                                     default=None)
    measured_indentation_mm = fields.number("measured_indentation_mm",
                                            required=False, default=None,
                                            minimum=0)
    if claim_type == "WARRANTY_INDENTATION":
        if measurement_method is None:
            raise invalid("measurement_method is required for "
                          "WARRANTY_INDENTATION claims")
        if measured_indentation_mm is None:
            raise invalid("measured_indentation_mm is required for "
                          "WARRANTY_INDENTATION claims")
    else:
        measurement_method = None
        measured_indentation_mm = None

    order = entities.get_order(order_id)
    require_customer_owner(order["customer_id"], "trial order")

    if order["delivered_at"] is None:
        raise api_error("ERR_INVALID_ORDER_STATE",
                        "A claim cannot be filed on an order that was never "
                        "delivered")
    if (claim_type in DELIVERY_CLAIM_TYPES
            and order["fulfillment_status"] not in ("DELIVERED",
                                                    "DAMAGED_REPORTED")):
        raise api_error("ERR_INVALID_ORDER_STATE",
                        "This order is no longer accepting delivery claims")

    nights_since_delivery = whole_days(order["delivered_at"], now())
    if (claim_type == "COMPRESSION_RECOVERY"
            and nights_since_delivery < calc.COMPRESSION_RECOVERY_WAIT_NIGHTS):
        raise api_error("ERR_RECOVERY_WINDOW_NOT_ELAPSED",
                        "The mattress must be given %d nights to recover"
                        % calc.COMPRESSION_RECOVERY_WAIT_NIGHTS)
    if (claim_type == "SHIPPING_DAMAGE"
            and nights_since_delivery > calc.DAMAGE_REPORT_WINDOW_NIGHTS):
        raise api_error("ERR_DAMAGE_REPORT_WINDOW_CLOSED",
                        "Shipping damage must be reported within %d nights"
                        % calc.DAMAGE_REPORT_WINDOW_NIGHTS)

    model = entities.model_of_order(order)
    claim = base_record()
    claim.update({
        "order_id": order["id"],
        "claim_type": claim_type,
        "photo_evidence_count": photo_evidence_count,
        "measurement_method": measurement_method,
        "measured_indentation_mm": measured_indentation_mm,
        "reported_at": now(),
        "evidence_round_count": 0,
        "ownership_years": None,
        "coverage_bps": None,
        "credit_cents": 0,
        "resolution": "PENDING",
        "status": "SUBMITTED",
        "approved_by_user_id": None,
        "settled_by_user_id": None,
    })
    _check_evidence_floor(claim)
    _check_indentation(claim, order, model)

    if claim_type == "WARRANTY_INDENTATION":
        years, coverage = calc.warranty_coverage(order["delivered_at"],
                                                 claim["reported_at"])
        claim["ownership_years"] = years
        claim["coverage_bps"] = coverage

    db.quality_claims[claim["id"]] = claim
    if (claim_type in DELIVERY_CLAIM_TYPES
            and order["fulfillment_status"] == "DELIVERED"):
        order["fulfillment_status"] = "DAMAGED_REPORTED"
        touch(order)
    return single(dump(claim, QUALITY_CLAIM), 201)


@bp.route("/quality-claims/<claim_id>", methods=["GET"])
@require("Customer", "TrialSupportAgent", "FinanceController", "PlatformAdmin")
def read_quality_claim(claim_id):
    claim = entities.get_claim(claim_id)
    order = entities.get_order(claim["order_id"])
    require_customer_owner(order["customer_id"], "quality claim")
    return single(dump(claim, QUALITY_CLAIM), 200)


@bp.route("/quality-claims", methods=["GET"])
@require("Customer", "TrialSupportAgent", "FinanceController", "PlatformAdmin")
def list_quality_claims():
    query = Query("order_id", "claim_type", "status")
    limit, offset = query.page()
    order_id = query.string("order_id")
    claim_type = query.enum("claim_type", CLAIM_TYPES)
    status = query.enum("status", CLAIM_STATUSES)
    matches = ordered([
        c for c in db.quality_claims.values()
        if (order_id is None or c["order_id"] == order_id)
        and (claim_type is None or c["claim_type"] == claim_type)
        and (status is None or c["status"] == status)
    ])
    page, total = paginate(matches, limit, offset)
    return collection(dump_many(page, QUALITY_CLAIM), limit, offset, total)


@bp.route("/quality-claims/<claim_id>/request-evidence", methods=["POST"])
@require("TrialSupportAgent")
def request_evidence(claim_id):
    Fields()
    claim = entities.get_claim(claim_id)
    if claim["status"] != "SUBMITTED":
        raise api_error("ERR_INVALID_CLAIM_STATE",
                        "Only a SUBMITTED claim can be asked for evidence")
    claim["status"] = "EVIDENCE_REQUESTED"
    touch(claim)
    return single(dump(claim, QUALITY_CLAIM), 200)


@bp.route("/quality-claims/<claim_id>/submit-evidence", methods=["POST"])
@require("Customer", "TrialSupportAgent")
def submit_evidence(claim_id):
    fields = Fields("photo_evidence_count", "measured_indentation_mm")
    photo_evidence_count = fields.integer("photo_evidence_count", minimum=0)
    measured_indentation_mm = fields.number("measured_indentation_mm",
                                            required=False, default=None,
                                            minimum=0)
    claim = entities.get_claim(claim_id)
    order = entities.get_order(claim["order_id"])
    require_customer_owner(order["customer_id"], "quality claim")
    if claim["status"] != "EVIDENCE_REQUESTED":
        raise api_error("ERR_INVALID_CLAIM_STATE",
                        "Evidence can only be supplied while the claim is "
                        "EVIDENCE_REQUESTED")
    probe = dict(claim)
    probe["photo_evidence_count"] = photo_evidence_count
    _check_evidence_floor(probe)
    if claim["evidence_round_count"] >= calc.MAX_EVIDENCE_ROUNDS:
        raise api_error("ERR_ROUND_LIMIT_REACHED",
                        "At most %d evidence rounds are allowed"
                        % calc.MAX_EVIDENCE_ROUNDS)
    claim["photo_evidence_count"] = photo_evidence_count
    if (claim["claim_type"] == "WARRANTY_INDENTATION"
            and measured_indentation_mm is not None):
        claim["measured_indentation_mm"] = measured_indentation_mm
    claim["evidence_round_count"] = claim["evidence_round_count"] + 1
    claim["status"] = "SUBMITTED"
    touch(claim)
    return single(dump(claim, QUALITY_CLAIM), 200)


@bp.route("/quality-claims/<claim_id>/adjudicate", methods=["POST"])
@require("TrialSupportAgent")
def adjudicate_quality_claim(claim_id):
    fields = Fields("resolution")
    resolution = fields.enum("resolution", RESOLUTIONS)
    claim = entities.get_claim(claim_id)
    if claim["status"] != "SUBMITTED":
        raise api_error("ERR_INVALID_CLAIM_STATE",
                        "Only a SUBMITTED claim can be adjudicated")
    if (resolution == "REPLACEMENT"
            and claim["claim_type"] not in DELIVERY_CLAIM_TYPES):
        raise api_error("ERR_INVALID_CLAIM_STATE",
                        "A replacement is only available on delivery-related "
                        "claims")
    order = entities.get_order(claim["order_id"])
    model = entities.model_of_order(order)
    _check_evidence_floor(claim)
    _check_indentation(claim, order, model)

    if resolution == "REPLACEMENT":
        if order["fulfillment_status"] != "DAMAGED_REPORTED":
            raise api_error("ERR_INVALID_ORDER_STATE",
                            "A replacement requires the order to be in "
                            "DAMAGED_REPORTED")
        if order["trial_status"] not in ("BREAK_IN", "TRIAL_ACTIVE"):
            raise api_error("ERR_INVALID_ORDER_STATE",
                            "The trial is no longer live on this order")
        if entities.active_return_cases(order["id"]):
            raise api_error("ERR_INVALID_ORDER_STATE",
                            "A live return case exists on this order")
        customer = entities.get_customer(order["customer_id"])
        order_service.new_order(
            customer, model, None, order["channel"],
            order["retail_partner_id"], order["gross_price_cents"],
            exchanged_from_order_id=order["id"],
            exchange_chain_depth=order["exchange_chain_depth"] + 1)
        order["fulfillment_status"] = "REPLACED"
        order["trial_status"] = "EXCHANGED"
        touch(order)
        claim["credit_cents"] = 0
        claim["resolution"] = "REPLACEMENT"
        claim["status"] = "APPROVED"
        claim["approved_by_user_id"] = g.user_id
    elif resolution == "CREDIT":
        claim["credit_cents"] = calc.quality_claim_credit(
            claim, order["paid_amount_cents"])
        claim["resolution"] = "CREDIT"
        claim["status"] = "APPROVED"
        claim["approved_by_user_id"] = g.user_id
        _revert_fulfillment_if_quiet(order, claim)
    else:
        claim["credit_cents"] = 0
        claim["resolution"] = "DENIED"
        claim["status"] = "DENIED"
        _revert_fulfillment_if_quiet(order, claim)
    touch(claim)
    return single(dump(claim, QUALITY_CLAIM), 200)


@bp.route("/quality-claims/<claim_id>/settle", methods=["POST"])
@require("FinanceController")
def settle_quality_claim(claim_id):
    Fields()
    claim = entities.get_claim(claim_id)
    if claim["status"] != "APPROVED" or claim["resolution"] != "CREDIT":
        raise api_error("ERR_INVALID_CLAIM_STATE",
                        "Only an APPROVED claim resolved to CREDIT can be "
                        "settled")
    if g.user_id == claim["approved_by_user_id"]:
        raise api_error("ERR_SEGREGATION_OF_DUTIES",
                        "The adjudicating agent may not also settle the claim")
    order = entities.get_order(claim["order_id"])
    claim["status"] = "SETTLED"
    claim["settled_by_user_id"] = g.user_id
    touch(claim)
    order["goodwill_credit_cents"] = (order["goodwill_credit_cents"]
                                      + claim["credit_cents"])
    touch(order)
    return single(dump(claim, QUALITY_CLAIM), 200)
