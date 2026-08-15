"""RateIndication routes: creation with both calculation variants, and the
cyclic actuarial review workflow (submit-review / approve / return / lock).
"""
from flask import Blueprint, request

from auth import ALL_ROLES, authenticate
from calc import compute_indication
from envelope import list_response, serialize, success
from errors import err, ERR_INVALID_STATE, ERR_SOD_VIOLATION, ERR_STALE_VERSION
from fields import RATE_INDICATION
from store import db, touch
from validate import (
    apply_filters, get_json_body, paginate, v_enum, v_int, v_number,
    v_optional, v_pos_int, v_state_code, v_string, validate_body,
)
from workflows import base_entity, get_or_404

bp = Blueprint("indications", __name__)

VARIANTS = {"INCURRED_CREDIBILITY", "PAID_PURE"}


@bp.route("/rate-indications", methods=["POST"])
def create_indication():
    user_id, _ = authenticate({"ProductActuary"})
    body = get_json_body(required=True)
    data = validate_body(body, {
        "product_id": (True, v_string),
        "scope_state_code": (False, v_optional(v_state_code)),
        "variant": (True, v_enum(VARIANTS)),
        "earned_premium_cents": (True, v_pos_int),
        "incurred_loss_cents": (True, v_pos_int),
        "paid_loss_cents": (True, v_pos_int),
        "exposure_units": (True, v_pos_int),
        "trend_factor": (True, v_number),
        "countrywide_change_pct": (True, v_number),
        "expected_product_version": (True, v_int),
    })
    with db.lock:
        product = get_or_404(db.products, data["product_id"])
        # OCC: expected_product_version must match the product's current version
        if data["expected_product_version"] != product["version"]:
            raise err(ERR_STALE_VERSION)
        credibility_z, indicated, alternate = compute_indication(
            data["variant"],
            data["earned_premium_cents"],
            data["incurred_loss_cents"],
            data["paid_loss_cents"],
            data["exposure_units"],
            data["trend_factor"],
            data["countrywide_change_pct"],
        )
        indication = base_entity()
        indication.update({
            "product_id": data["product_id"],
            "scope_state_code": data["scope_state_code"],
            "variant": data["variant"],
            "earned_premium_cents": data["earned_premium_cents"],
            "incurred_loss_cents": data["incurred_loss_cents"],
            "paid_loss_cents": data["paid_loss_cents"],
            "exposure_units": data["exposure_units"],
            "trend_factor": data["trend_factor"],
            "countrywide_change_pct": data["countrywide_change_pct"],
            "credibility_z": credibility_z,
            "indicated_change_pct": indicated,
            "alternate_change_pct": alternate,
            "status": "DRAFT",
            "prepared_by_user_id": user_id,
            "approved_by_user_id": None,
            "review_round": 1,
        })
        db.rate_indications[indication["id"]] = indication
        # Creating an indication advances the parent product's book of record
        touch(product)
    return success(serialize(indication, RATE_INDICATION), code=201)


@bp.route("/rate-indications/<indicationId>", methods=["GET"])
def get_indication(indicationId):
    authenticate(ALL_ROLES)
    indication = get_or_404(db.rate_indications, indicationId)
    return success(serialize(indication, RATE_INDICATION), code=200)


@bp.route("/rate-indications", methods=["GET"])
def list_indications():
    authenticate(ALL_ROLES)
    filters = {
        "product_id": request.args.get("product_id"),
        "status": request.args.get("status"),
    }
    items = apply_filters(list(db.rate_indications.values()), filters)
    page, total, limit, offset = paginate(items)
    return list_response([serialize(i, RATE_INDICATION) for i in page], total, limit, offset)


@bp.route("/rate-indications/<indicationId>/submit-review", methods=["POST"])
def submit_review(indicationId):
    authenticate({"ProductActuary"})
    with db.lock:
        indication = get_or_404(db.rate_indications, indicationId)
        if indication["status"] != "DRAFT":
            raise err(ERR_INVALID_STATE)
        indication["status"] = "IN_ACTUARIAL_REVIEW"
        touch(indication)
    return success(serialize(indication, RATE_INDICATION), code=200)


@bp.route("/rate-indications/<indicationId>/approve", methods=["POST"])
def approve_indication(indicationId):
    user_id, _ = authenticate({"ProductActuary"})
    with db.lock:
        indication = get_or_404(db.rate_indications, indicationId)
        if indication["status"] != "IN_ACTUARIAL_REVIEW":
            raise err(ERR_INVALID_STATE)
        # Segregation of duties: approver must differ from preparer
        if user_id == indication["prepared_by_user_id"]:
            raise err(ERR_SOD_VIOLATION)
        indication["status"] = "APPROVED"
        indication["approved_by_user_id"] = user_id
        touch(indication)
    return success(serialize(indication, RATE_INDICATION), code=200)


@bp.route("/rate-indications/<indicationId>/return", methods=["POST"])
def return_indication(indicationId):
    authenticate({"ProductActuary"})
    with db.lock:
        indication = get_or_404(db.rate_indications, indicationId)
        if indication["status"] != "IN_ACTUARIAL_REVIEW":
            raise err(ERR_INVALID_STATE)
        indication["status"] = "DRAFT"
        indication["review_round"] += 1
        touch(indication)
    return success(serialize(indication, RATE_INDICATION), code=200)


@bp.route("/rate-indications/<indicationId>/lock", methods=["POST"])
def lock_indication(indicationId):
    authenticate({"ProductActuary"})
    with db.lock:
        indication = get_or_404(db.rate_indications, indicationId)
        if indication["status"] != "APPROVED":
            raise err(ERR_INVALID_STATE)
        # Supersede any other LOCKED indication of the same (product, scope)
        for other in db.rate_indications.values():
            if (
                other["id"] != indication["id"]
                and other["status"] == "LOCKED"
                and other["product_id"] == indication["product_id"]
                and other["scope_state_code"] == indication["scope_state_code"]
            ):
                other["status"] = "SUPERSEDED"
                touch(other)
        indication["status"] = "LOCKED"
        touch(indication)
        if indication["scope_state_code"] is None:
            product = db.products.get(indication["product_id"])
            if product is not None:
                product["current_locked_indication_id"] = indication["id"]
                touch(product)
    return success(serialize(indication, RATE_INDICATION), code=200)
