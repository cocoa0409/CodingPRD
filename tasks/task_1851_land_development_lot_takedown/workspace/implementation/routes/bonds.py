"""InfrastructureBond endpoints (PRD 3.3): bonding and work acceptance."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_BOND_INVALID_STATE,
    ERR_INSUFFICIENT_BOND_POSTED,
    ERR_BOND_REDUCTION_NOT_ELIGIBLE,
    ERR_NO_ACTIVE_LOAN,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response, public
from services import calculations as calc
from services.core import active_loan_for, new_record, touch
from validate import check_body_fk_exists, get_body, req_int, req_str, require_path

bp = Blueprint("bonds", __name__)


@bp.post("/infrastructure-bonds")
def create_bond():
    authorized(["DeveloperOperator"])
    body = get_body()
    # Priority 3: body FK existence
    check_body_fk_exists("phases", body, "phase_id")
    # Priority 4: shape
    phase_id = req_str(body, "phase_id")
    estimate = req_int(body, "engineer_estimate_cents", minimum=1)
    rec = new_record("bonds", {
        "phase_id": phase_id,
        "engineer_estimate_cents": estimate,
        "awarded_bid_cents": None,
        "required_bond_cents": calc.required_bond_cents(estimate),  # PROVISIONAL basis
        "posted_bond_cents": 0,
        "work_accepted": False,
        "status": "ESTIMATED",
    })
    return success_object(public(rec), status=201)


@bp.get("/infrastructure-bonds")
def list_bonds():
    return list_response("bonds", {
        "phase_id": request.args.get("phase_id"),
        "status": request.args.get("status"),
    })


@bp.get("/infrastructure-bonds/<rid>")
def get_bond(rid):
    return get_one("bonds", rid)


@bp.post("/infrastructure-bonds/<rid>/award-bid")
def award_bid(rid):
    authorized(["DeveloperOperator"])
    bond = require_path("bonds", rid)
    body = get_body()
    awarded = req_int(body, "awarded_bid_cents", minimum=1)
    if bond["status"] != "ESTIMATED":
        raise_error(ERR_BOND_INVALID_STATE, "award-bid requires ESTIMATED")
    bond["awarded_bid_cents"] = awarded
    bond["required_bond_cents"] = calc.required_bond_cents(awarded)  # FINAL basis
    bond["status"] = "BID_FINAL"
    touch(bond)
    return success_object(public(bond))


@bp.post("/infrastructure-bonds/<rid>/post-bond")
def post_bond(rid):
    authorized(["DeveloperOperator"])
    bond = require_path("bonds", rid)
    body = get_body()
    posted = req_int(body, "posted_amount_cents")
    if bond["status"] != "BID_FINAL":
        raise_error(ERR_BOND_INVALID_STATE, "post-bond requires BID_FINAL")
    # Priority 11 (fiscal): posted must cover the requirement, boundary inclusive
    if posted < bond["required_bond_cents"]:
        raise_error(ERR_INSUFFICIENT_BOND_POSTED,
                    "posted_amount_cents is below required_bond_cents")
    bond["posted_bond_cents"] = posted
    bond["status"] = "POSTED"
    touch(bond)
    return success_object(public(bond))


@bp.post("/infrastructure-bonds/<rid>/reduce")
def reduce_bond(rid):
    authorized(["DeveloperOperator"])
    bond = require_path("bonds", rid)
    body = get_body()
    reduction = req_int(body, "reduction_amount_cents")
    if bond["status"] != "POSTED":
        raise_error(ERR_BOND_INVALID_STATE, "reduce requires POSTED")
    # Priority 10 (referential): the parcel's single ACTIVE loan must exist
    phase = db["phases"].get(bond["phase_id"])
    parcel_id = phase["parcel_id"] if phase else None
    loan = active_loan_for(parcel_id) if parcel_id else None
    if loan is None:
        raise_error(ERR_NO_ACTIVE_LOAN, "no ACTIVE development loan for the parcel")
    # Priority 11 (fiscal): all three step-down thresholds; boundary inclusive.
    # Loan leg: outstanding <= commitment * 5000/10000 (exact integer form:
    # 2 * outstanding <= commitment).
    loan_leg_ok = 2 * loan["outstanding_balance_cents"] <= loan["commitment_amount_cents"]
    floor_cents = calc.half_of_required_bond(bond["required_bond_cents"])
    bond_leg_ok = (bond["posted_bond_cents"] - reduction) >= floor_cents
    amount_ok = reduction >= 1
    if not (loan_leg_ok and bond_leg_ok and amount_ok):
        raise_error(ERR_BOND_REDUCTION_NOT_ELIGIBLE,
                    "bond reduction fails the step-down thresholds")
    bond["posted_bond_cents"] -= reduction
    bond["status"] = "PARTIALLY_REDUCED"
    touch(bond)
    return success_object(public(bond))


@bp.post("/infrastructure-bonds/<rid>/accept-work")
def accept_work(rid):
    # Segregation of duties: the clerk certifies; only the developer posts/reduces/releases
    authorized(["MunicipalClerk"])
    bond = require_path("bonds", rid)
    if bond["status"] not in ("POSTED", "PARTIALLY_REDUCED"):
        raise_error(ERR_BOND_INVALID_STATE, "accept-work requires POSTED or PARTIALLY_REDUCED")
    bond["work_accepted"] = True
    bond["status"] = "WORK_ACCEPTED"
    touch(bond)
    return success_object(public(bond))


@bp.post("/infrastructure-bonds/<rid>/release")
def release_bond(rid):
    authorized(["DeveloperOperator"])
    bond = require_path("bonds", rid)
    if bond["status"] != "WORK_ACCEPTED":
        raise_error(ERR_BOND_INVALID_STATE, "release requires WORK_ACCEPTED")
    bond["posted_bond_cents"] = 0
    bond["status"] = "RELEASED"
    touch(bond)
    return success_object(public(bond))
