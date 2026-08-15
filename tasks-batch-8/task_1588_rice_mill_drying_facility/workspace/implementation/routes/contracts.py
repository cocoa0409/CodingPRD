"""DeliveryContract endpoints (PRD §3.2, §2.8 OCC)."""
from flask import Blueprint

from db import db
from errors import (
    raise_error, ERR_GROWER_NOT_FOUND, ERR_CONTRACT_HAS_DELIVERIES,
    ERR_CONTRACT_NOT_OPEN, ERR_STALE_CONTRACT_VERSION,
)
from middleware import authorized
from response import success_object
from routes.helpers import list_endpoint, get_endpoint, public, require_resource
from services import core
from util import new_id, next_seq, q2
from validate import (
    get_body, req_str, req_enum, req_num, req_int, opt_num, opt_int,
    req_grade_adjustments, opt_grade_adjustments,
)

bp = Blueprint("contracts", __name__)


@bp.route("/mill/contracts", methods=["POST"])
def create_contract():
    authorized(["Merchandiser"])
    body = get_body()
    season_id = req_str(body, "season_id")
    grower_id = req_str(body, "grower_id")
    variety = req_enum(body, "variety", core.VARIETIES)
    contracted = req_num(body, "contracted_cwt", positive=True)
    base_price = req_int(body, "base_price_cents_per_cwt")
    adjustments = req_grade_adjustments(body, "grade_adjustments")
    require_resource("seasons", season_id)
    grower = db["growers"].get(grower_id)
    if grower is None or grower["season_id"] != season_id:
        raise_error(ERR_GROWER_NOT_FOUND, "grower not found in this season")
    rec = {
        "id": new_id(),
        "_seq": next_seq(),
        "season_id": season_id,
        "grower_id": grower_id,
        "variety": variety,
        "contracted_cwt": q2(contracted),
        "base_price_cents_per_cwt": base_price,
        "grade_adjustments": adjustments,
        "delivery_count": 0,
        "fulfilled_cwt": q2(0),
        "status": "OPEN",
    }
    core.touch_new(rec)
    db["contracts"][rec["id"]] = rec
    return success_object(public(rec), 201)


@bp.route("/mill/contracts", methods=["GET"])
def list_contracts():
    return list_endpoint("contracts", ["season_id", "grower_id", "variety", "status"])


@bp.route("/mill/contracts/<rid>", methods=["GET"])
def get_contract(rid):
    return get_endpoint("contracts", rid)


@bp.route("/mill/contracts/<rid>", methods=["PUT"])
def amend_contract(rid):
    authorized(["Merchandiser"])
    body = get_body()
    expected = req_int(body, "expected_contract_version")
    new_contracted = opt_num(body, "contracted_cwt", positive=True)
    new_price = opt_int(body, "base_price_cents_per_cwt")
    new_adj = opt_grade_adjustments(body, "grade_adjustments")
    contract = require_resource("contracts", rid)
    if D_nonzero_fulfilled(contract):
        raise_error(ERR_CONTRACT_HAS_DELIVERIES,
                    "contract has fulfilled volume; terms are locked")
    if int(contract["version"]) != expected:
        raise_error(ERR_STALE_CONTRACT_VERSION,
                    "expected_contract_version does not match the contract's current version")
    if new_contracted is not None:
        contract["contracted_cwt"] = q2(new_contracted)
    if new_price is not None:
        contract["base_price_cents_per_cwt"] = new_price
    if new_adj is not None:
        contract["grade_adjustments"] = new_adj
    core.bump(contract)
    return success_object(public(contract))


def D_nonzero_fulfilled(contract):
    from util import D
    return D(contract["fulfilled_cwt"]) != 0


@bp.route("/mill/contracts/<rid>/cancel", methods=["POST"])
def cancel_contract(rid):
    authorized(["Merchandiser"])
    contract = require_resource("contracts", rid)
    if contract["status"] not in ("OPEN", "PARTIALLY_FULFILLED"):
        raise_error(ERR_CONTRACT_NOT_OPEN,
                    f"contract status {contract['status']} cannot be cancelled")
    if D_nonzero_fulfilled(contract):
        raise_error(ERR_CONTRACT_HAS_DELIVERIES,
                    "contract has fulfilled volume; it cannot be cancelled")
    contract["status"] = "CANCELLED"
    core.bump(contract)
    return success_object(public(contract))
