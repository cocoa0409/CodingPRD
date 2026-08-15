from flask import Blueprint

from constants import ALL_ROLES
from db import store, stamp_new, bump, pub
from errors import raise_err
from middleware import authenticate
from response import success
from services.domain import get_or_404, list_response
from services.pipeline import revert_distributions_using_exception, _exception_exit_posture
from util import new_id, parse_body, req_str, req_int

bp = Blueprint("exceptions", __name__)

NON_TERMINAL_EXCEPTION_STATES = ("REQUESTED", "ENDORSED", "APPROVED")


def _terminated_gate(fund):
    pool = store.pools.get(fund["pool_id"]) if fund else None
    if pool is not None and pool["pool_status"] == "TERMINATED":
        raise_err(
            "ERR_POOL_SUSPENDED",
            "Pool is TERMINATED and read-only; all mutations are rejected",
        )


@bp.route("/endowment/exceptions", methods=["POST"])
def create_exception():
    user_id, _ = authenticate(["DevelopmentOfficer"])
    body = parse_body(required=True)
    fund_id = req_str(body, "fund_id")
    fiscal_year = req_int(body, "fiscal_year")
    requested = req_int(body, "requested_amount_cents", minv=1)
    justification = req_str(body, "justification")

    fund = get_or_404(store.funds, fund_id, "Fund")
    if fund["fund_status"] != "ACTIVE":
        raise_err(
            "ERR_INVALID_STATE_TRANSITION",
            "Exception requests require an ACTIVE fund",
        )
    _terminated_gate(fund)
    if not fund["is_underwater"]:
        raise_err(
            "ERR_FUND_NOT_UNDERWATER",
            "An exception may be requested only for a fund that is underwater",
        )
    duplicate = any(
        e["fund_id"] == fund_id
        and e["fiscal_year"] == fiscal_year
        and e["exception_status"] in NON_TERMINAL_EXCEPTION_STATES
        for e in store.exceptions.values()
    )
    if duplicate:
        raise_err(
            "ERR_DUPLICATE_RECORD",
            f"A non-terminal exception already exists for this fund and fiscal "
            f"year {fiscal_year}",
        )

    rec = {
        "id": new_id(),
        "fund_id": fund_id,
        "fiscal_year": fiscal_year,
        "requested_amount_cents": requested,
        "justification": justification,
        "exception_status": "REQUESTED",
        "approved_amount_cents": None,
        "requested_by_user_id": user_id,
        "endorsed_by_user_id": None,
        "approved_by_user_id": None,
        "version": 1,
    }
    stamp_new(rec)
    store.exceptions[rec["id"]] = rec
    return success(pub(rec), status=201)


@bp.route("/endowment/exceptions", methods=["GET"])
def list_exceptions():
    authenticate(ALL_ROLES)
    return list_response(
        store.exceptions,
        [
            ("fund_id", "fund_id", "str"),
            ("exception_status", "exception_status", "str"),
            ("fiscal_year", "fiscal_year", "int"),
        ],
    )


@bp.route("/endowment/exceptions/<exception_id>", methods=["GET"])
def get_exception(exception_id):
    authenticate(ALL_ROLES)
    return success(pub(get_or_404(store.exceptions, exception_id, "PolicyException")))


@bp.route("/endowment/exceptions/<exception_id>/endorse", methods=["POST"])
def endorse_exception(exception_id):
    user_id, _ = authenticate(["InvestmentOfficer"])
    exc = store.exceptions.get(exception_id)
    if exc is not None and user_id == exc["requested_by_user_id"]:
        raise_err(
            "ERR_SEGREGATION_OF_DUTIES_VIOLATION",
            "The endorser must differ from the exception's requester",
        )
    if exc is None:
        raise_err("ERR_NOT_FOUND", f"PolicyException not found: {exception_id}")
    if exc["exception_status"] != "REQUESTED":
        raise_err(
            "ERR_INVALID_STATE_TRANSITION",
            f"Cannot endorse an exception in state {exc['exception_status']}",
        )
    _terminated_gate(store.funds.get(exc["fund_id"]))
    exc["exception_status"] = "ENDORSED"
    exc["endorsed_by_user_id"] = user_id
    bump(exc)
    return success(pub(exc))


@bp.route("/endowment/exceptions/<exception_id>/approve", methods=["POST"])
def approve_exception(exception_id):
    user_id, _ = authenticate(["BoardMember"])
    exc = store.exceptions.get(exception_id)
    if exc is not None and (
        user_id == exc["requested_by_user_id"]
        or user_id == exc.get("endorsed_by_user_id")
    ):
        raise_err(
            "ERR_SEGREGATION_OF_DUTIES_VIOLATION",
            "The approver must differ from both the requester and the endorser",
        )
    body = parse_body(required=True)
    approved_amount = req_int(body, "approved_amount_cents", minv=1)
    if exc is None:
        raise_err("ERR_NOT_FOUND", f"PolicyException not found: {exception_id}")
    if exc["exception_status"] != "ENDORSED":
        raise_err(
            "ERR_INVALID_STATE_TRANSITION",
            f"Cannot approve an exception in state {exc['exception_status']}",
        )
    fund = store.funds.get(exc["fund_id"])
    _terminated_gate(fund)
    if fund is None or not fund["is_underwater"]:
        raise_err(
            "ERR_FUND_NOT_UNDERWATER",
            "An exception may be approved only while the fund remains underwater",
        )
    if approved_amount > exc["requested_amount_cents"]:
        raise_err(
            "ERR_EXCEPTION_AMOUNT_EXCEEDS_REQUESTED",
            "approved_amount_cents must not exceed requested_amount_cents",
        )
    exc["exception_status"] = "APPROVED"
    exc["approved_amount_cents"] = approved_amount
    exc["approved_by_user_id"] = user_id
    bump(exc)
    if fund["spending_posture"] == "SPENDING_SUSPENDED":
        fund["spending_posture"] = "EXCEPTION_ACTIVE"
        bump(fund)
    return success(pub(exc))


@bp.route("/endowment/exceptions/<exception_id>/reject", methods=["POST"])
def reject_exception(exception_id):
    authenticate(["BoardMember"])
    exc = get_or_404(store.exceptions, exception_id, "PolicyException")
    if exc["exception_status"] not in ("REQUESTED", "ENDORSED"):
        raise_err(
            "ERR_INVALID_STATE_TRANSITION",
            f"Cannot reject an exception in state {exc['exception_status']}",
        )
    _terminated_gate(store.funds.get(exc["fund_id"]))
    exc["exception_status"] = "REJECTED"
    bump(exc)
    return success(pub(exc))


@bp.route("/endowment/exceptions/<exception_id>/rescind", methods=["POST"])
def rescind_exception(exception_id):
    authenticate(["BoardMember"])
    exc = get_or_404(store.exceptions, exception_id, "PolicyException")
    if exc["exception_status"] != "APPROVED":
        raise_err(
            "ERR_INVALID_STATE_TRANSITION",
            f"Cannot rescind an exception in state {exc['exception_status']}",
        )
    _terminated_gate(store.funds.get(exc["fund_id"]))
    exc["exception_status"] = "RESCINDED"
    bump(exc)
    revert_distributions_using_exception(exc)
    _exception_exit_posture(exc)
    return success(pub(exc))
