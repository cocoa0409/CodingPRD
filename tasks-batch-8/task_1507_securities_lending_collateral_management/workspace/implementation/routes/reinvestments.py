"""Cash collateral reinvestment endpoints."""

from flask import Blueprint, request
import db
import errors
from middleware import get_auth, require_roles
from response import success_object, success_list
from services import calculations as calc
from services.state_machines import _touch, _unwind_tranche
from routes.helpers import (
    get_json_body, require_fields, validate_positive_int, validate_enum,
    get_or_404, paginate, serialize_common,
)

bp = Blueprint("reinvestments", __name__)

ALL_ROLES = ["DeskAdmin", "DeskTrader", "BorrowerRep", "OwnerRep", "RiskOfficer", "OpsSettler"]
INSTRUMENT_TYPES = ["MMF", "REPO", "TIME_DEPOSIT"]


@bp.route("/api/loans/<loan_id>/reinvestments", methods=["POST"])
def create_tranche(loan_id):
    user_id, role = get_auth()
    require_roles(role, ["DeskTrader"])
    loan = get_or_404(db.loans, loan_id, "Loan")

    if loan["status"] not in ("BOOKED", "RECALLED"):
        raise errors.make_error(errors.ERR_INVALID_STATE, "Loan is not BOOKED or RECALLED")
    if loan["collateral_type"] != "CASH":
        raise errors.make_error(errors.ERR_LOAN_NOT_CASH_COLLATERAL, "Reinvestment requires CASH-collateral loan")

    body = get_json_body()
    require_fields(body, ["instrument_type", "principal_cents", "stated_yield_bps"])
    validate_enum(body["instrument_type"], INSTRUMENT_TYPES, "instrument_type")
    validate_positive_int(body["principal_cents"], "principal_cents")
    if not isinstance(body["stated_yield_bps"], int) or isinstance(body["stated_yield_bps"], bool) or body["stated_yield_bps"] < 0:
        raise errors.make_error(errors.ERR_VALIDATION, "stated_yield_bps must be a non-negative integer")

    calc.recompute_loan_derived(loan)
    if body["principal_cents"] > loan["cash_uninvested_cents"]:
        raise errors.make_error(errors.ERR_REINVEST_EXCEEDS_CASH, "Principal exceeds uninvested cash")

    tranche = {
        "id": db.new_id(),
        "created_at": db.now_iso(),
        "updated_at": db.now_iso(),
        "version": 1,
        "loan_id": loan_id,
        "instrument_type": body["instrument_type"],
        "principal_cents": body["principal_cents"],
        "stated_yield_bps": body["stated_yield_bps"],
        "current_nav_cents": body["principal_cents"],
        "realized_income_cents": None,
        "status": "INVESTED",
    }
    db.reinvestments[tranche["id"]] = tranche

    loan["cash_uninvested_cents"] -= body["principal_cents"]
    _touch(loan)

    return success_object(serialize_common(tranche), 201)


@bp.route("/api/reinvestments/<tranche_id>", methods=["GET"])
def get_tranche(tranche_id):
    user_id, role = get_auth()
    require_roles(role, ALL_ROLES)
    tranche = get_or_404(db.reinvestments, tranche_id, "ReinvestmentTranche")
    return success_object(serialize_common(tranche))


@bp.route("/api/reinvestments", methods=["GET"])
def list_tranches():
    user_id, role = get_auth()
    require_roles(role, ALL_ROLES)
    filters = {
        "loan_id": request.args.get("loan_id"),
        "status": request.args.get("status"),
    }
    items = list(db.reinvestments.values())
    if filters["loan_id"]:
        items = [t for t in items if t["loan_id"] == filters["loan_id"]]
    if filters["status"]:
        items = [t for t in items if t["status"] == filters["status"]]
    page, limit, offset, total = paginate(items, request.args)
    return success_list([serialize_common(t) for t in page], limit, offset, total)


@bp.route("/api/reinvestments/<tranche_id>/mark", methods=["POST"])
def mark_tranche(tranche_id):
    user_id, role = get_auth()
    require_roles(role, ["OpsSettler"])
    tranche = get_or_404(db.reinvestments, tranche_id, "ReinvestmentTranche")
    if tranche["status"] != "INVESTED":
        raise errors.make_error(errors.ERR_INVALID_STATE, "Tranche is not INVESTED")

    body = get_json_body()
    require_fields(body, ["current_nav_cents"])
    if not isinstance(body["current_nav_cents"], int) or isinstance(body["current_nav_cents"], bool):
        raise errors.make_error(errors.ERR_VALIDATION, "current_nav_cents must be an integer")

    tranche["current_nav_cents"] = body["current_nav_cents"]
    _touch(tranche)
    return success_object(serialize_common(tranche))


@bp.route("/api/reinvestments/<tranche_id>/unwind", methods=["POST"])
def unwind_tranche(tranche_id):
    user_id, role = get_auth()
    require_roles(role, ["DeskTrader"])
    tranche = get_or_404(db.reinvestments, tranche_id, "ReinvestmentTranche")
    if tranche["status"] != "INVESTED":
        raise errors.make_error(errors.ERR_INVALID_STATE, "Tranche is not INVESTED")

    loan = db.loans[tranche["loan_id"]]
    if loan["status"] not in ("BOOKED", "RECALLED"):
        raise errors.make_error(errors.ERR_INVALID_STATE, "Loan is not BOOKED or RECALLED")

    _unwind_tranche(tranche, loan)
    calc.recompute_loan_derived(loan)
    return success_object(serialize_common(tranche))
