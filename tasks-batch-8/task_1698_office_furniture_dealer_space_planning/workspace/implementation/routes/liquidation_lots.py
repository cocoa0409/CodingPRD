"""LiquidationLot routes: offer, OCC-guarded appraisal, SoD-gated credit
issuance, manual redemption with remainder forfeiture, decline."""
from flask import Blueprint

from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_STALE_VERSION,
    ERR_SOD_VIOLATION,
)
from middleware import ALL_ROLES
from response import success_object
from routes.helpers import authorize, list_response, get_response
from serialize import public
from services.core import get_or_404, new_entity, touch, recompute_customer_balance
from services.pricing import liquidation_estimate, liquidation_final_credit
from util import CLOCK
from validate import body_dict, req_str, req_enum, req_int, is_int

bp = Blueprint("liquidation_lots", __name__)

GRADES = {"A", "B", "C"}


@bp.route("/api/liquidation-lots", methods=["POST"])
def create_lot():
    authorize(["AccountExecutive"])
    body = body_dict()
    customer_id = req_str(body, "customer_id")
    description = req_str(body, "description")
    item_count = req_int(body, "item_count", minv=1)
    get_or_404("customers", customer_id)
    lot = new_entity("liquidation_lots", {
        "customer_id": customer_id,
        "description": description,
        "item_count": item_count,
        "condition_grade": None,
        "estimated_credit_cents": liquidation_estimate(item_count),
        "appraised_value_cents": None,
        "appraised_at": None,
        "appraised_by_user_id": None,
        "issued_by_user_id": None,
        "final_credit_cents": None,
        "redeemed_cents": 0,
        "status": "OFFERED",
        "_manual_redeem": False,
    })
    return success_object(public(lot), status=201)


@bp.route("/api/liquidation-lots", methods=["GET"])
def list_lots():
    authorize(ALL_ROLES)
    return list_response("liquidation_lots", ["customer_id", "status"])


@bp.route("/api/liquidation-lots/<lot_id>", methods=["GET"])
def get_lot(lot_id):
    authorize(ALL_ROLES)
    return get_response("liquidation_lots", lot_id)


@bp.route("/api/liquidation-lots/<lot_id>/appraise", methods=["POST"])
def appraise_lot(lot_id):
    caller = authorize(["LiquidationAppraiser"])
    lot = get_or_404("liquidation_lots", lot_id)
    # priority 4: appraisal (or re-appraisal) exists from OFFERED and APPRAISED
    if lot["status"] not in ("OFFERED", "APPRAISED"):
        raise_error(ERR_INVALID_STATE, f"cannot appraise a lot in status {lot['status']}")
    body = body_dict()
    # OCC (concurrency rule lot-appraisal-stale-version)
    expected = body.get("expected_lot_version")
    if not is_int(expected):
        raise_error(ERR_INVALID_REQUEST, "field 'expected_lot_version' is required and must be an integer")
    if expected != lot["version"]:
        raise_error(ERR_STALE_VERSION,
                    f"expected_lot_version {expected} does not match current version {lot['version']}")
    # priority 8a
    condition_grade = req_enum(body, "condition_grade", GRADES)
    appraised_value_cents = req_int(body, "appraised_value_cents", minv=0)
    lot["condition_grade"] = condition_grade
    lot["appraised_value_cents"] = appraised_value_cents
    lot["appraised_at"] = CLOCK.today().isoformat()
    lot["appraised_by_user_id"] = caller.user_id
    lot["status"] = "APPRAISED"
    touch(lot)
    return success_object(public(lot))


@bp.route("/api/liquidation-lots/<lot_id>/issue_credit", methods=["POST"])
def issue_credit(lot_id):
    caller = authorize(["FinanceManager"])
    lot = get_or_404("liquidation_lots", lot_id)
    if lot["status"] != "APPRAISED":
        raise_error(ERR_INVALID_STATE, f"cannot issue credit for a lot in status {lot['status']}")
    # priority 5a: segregation of duties — issuer must differ from appraiser
    if caller.user_id == lot.get("appraised_by_user_id"):
        raise_error(ERR_SOD_VIOLATION, "the credit issuer must differ from the lot appraiser")
    lot["final_credit_cents"] = liquidation_final_credit(
        lot["condition_grade"], lot["appraised_value_cents"], lot["item_count"])
    lot["issued_by_user_id"] = caller.user_id
    lot["status"] = "CREDIT_ISSUED"
    touch(lot)
    customer = get_or_404("customers", lot["customer_id"])
    recompute_customer_balance(customer)
    return success_object(public(lot))


@bp.route("/api/liquidation-lots/<lot_id>/redeem", methods=["POST"])
def redeem_lot(lot_id):
    authorize(["FinanceManager"])
    lot = get_or_404("liquidation_lots", lot_id)
    if lot["status"] != "CREDIT_ISSUED":
        raise_error(ERR_INVALID_STATE, f"cannot redeem a lot in status {lot['status']}")
    lot["status"] = "REDEEMED"
    lot["_manual_redeem"] = True
    touch(lot)
    # the unredeemed remainder is forfeited: debited from the customer's ledger
    # via the REDEEMED-lot remainder term of the balance derivation
    customer = get_or_404("customers", lot["customer_id"])
    recompute_customer_balance(customer)
    return success_object(public(lot))


@bp.route("/api/liquidation-lots/<lot_id>/decline", methods=["POST"])
def decline_lot(lot_id):
    authorize(["AccountExecutive"])
    lot = get_or_404("liquidation_lots", lot_id)
    if lot["status"] not in ("OFFERED", "APPRAISED"):
        raise_error(ERR_INVALID_STATE, f"cannot decline a lot in status {lot['status']}")
    lot["status"] = "DECLINED"
    touch(lot)
    return success_object(public(lot))
