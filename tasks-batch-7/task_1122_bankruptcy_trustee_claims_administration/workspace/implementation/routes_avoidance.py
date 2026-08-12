"""Avoidance action endpoints (preference / fraudulent transfer) and the
recovery-deposit ledger listings."""
from datetime import timedelta

from flask import Blueprint, request

import db
from errors import (
    ApiError, ERR_INVALID_STATE, ERR_REFERENTIAL_INTEGRITY,
    ERR_TRANSFER_NOT_AVOIDABLE, ERR_INVALID_DEMAND_AMOUNT,
    ERR_PLAN_RELIES_ON_RECOVERY, ERR_INSUFFICIENT_ESTATE_FUNDS,
    ERR_INVALID_REQUEST,
)
from logical_clock import CLOCK
from middleware import auth_context, require_roles, json_body, ALL_ROLES
from response import ok_object, paginate
from services_calc import register_claim_number
from services_common import (
    new_entity, touch, bump_case, get_case, get_or_404, ensure_case_open,
    ensure_trustee_binding, ser_action, ser_deposit, sorted_rows,
)
from util import parse_datetime, require_str, require_int, require_enum

bp = Blueprint("avoidance", __name__)

ACTION_TYPES = ("PREFERENCE_547", "FRAUDULENT_548")


def _get_action_and_case(action_id):
    action = get_or_404(db.actions, action_id, "avoidance action")
    return action, db.cases[action["case_id"]]


def _lookback_days(action_type, creditor):
    if action_type == "PREFERENCE_547":
        return 365 if creditor["insider"] else 90
    return 730  # FRAUDULENT_548


def _compute_avoidable(case, transfer_date, window_days):
    # Whole-day granularity (PRD §2.8/§3.5): on/after the earliest boundary is
    # avoidable; a transfer dated on the petition date itself is not.
    earliest = (case["filed_on"] - timedelta(days=window_days)).date()
    transfer_day = transfer_date.date()
    return earliest <= transfer_day < case["filed_on"].date()


@bp.route("/trustee/cases/<id>/avoidance_actions", methods=["POST"])
def create_action(id):
    uid, role = auth_context()
    require_roles(role, ("Trustee",))
    case = get_case(id)
    ensure_case_open(case)
    ensure_trustee_binding(case, uid)
    body = json_body()

    raw_creditor = body.get("transferee_creditor_id")
    creditor = None
    if isinstance(raw_creditor, str):
        creditor = db.creditors.get(raw_creditor)
        if creditor is None:
            raise ApiError(ERR_REFERENTIAL_INTEGRITY, 422,
                           "transferee_creditor_id does not reference an existing creditor.")

    transferee_id = require_str(body, "transferee_creditor_id")
    transfer_date = parse_datetime(body.get("transfer_date"), "transfer_date")
    transfer_amount = require_int(body, "transfer_amount_cents", minimum=0)
    action_type = require_enum(body, "action_type", ACTION_TYPES)
    demand_amount = require_int(body, "demand_amount_cents", minimum=0)

    window = _lookback_days(action_type, creditor)
    avoidable = _compute_avoidable(case, transfer_date, window)

    action = new_entity({
        "case_id": id,
        "transferee_creditor_id": transferee_id,
        "transfer_date": transfer_date,
        "transfer_amount_cents": transfer_amount,
        "action_type": action_type,
        "lookback_window_days": window,
        "avoidable": avoidable,
        "demand_amount_cents": demand_amount,
        "recovered_amount_cents": 0,
        "status": "IDENTIFIED",
    })
    db.actions[action["id"]] = action
    return ok_object(ser_action(action), status=201)


@bp.route("/trustee/cases/<id>/avoidance_actions", methods=["GET"])
def list_case_actions(id):
    auth_context()
    require_roles(request.headers.get("X-User-Role"), ALL_ROLES)
    get_case(id)
    status = request.args.get("status")
    transferee = request.args.get("transferee_creditor_id")
    rows = [a for a in db.actions.values() if a["case_id"] == id]
    if status is not None:
        rows = [a for a in rows if a["status"] == status]
    if transferee is not None:
        rows = [a for a in rows if a["transferee_creditor_id"] == transferee]
    return paginate([ser_action(a) for a in sorted_rows(rows)])


@bp.route("/trustee/avoidance_actions/<id>", methods=["GET"])
def get_action(id):
    auth_context()
    require_roles(request.headers.get("X-User-Role"), ALL_ROLES)
    return ok_object(ser_action(get_or_404(db.actions, id, "avoidance action")))


@bp.route("/trustee/avoidance_actions/<id>/recovery_deposits", methods=["GET"])
def action_deposits(id):
    auth_context()
    require_roles(request.headers.get("X-User-Role"), ALL_ROLES)
    get_or_404(db.actions, id, "avoidance action")
    rows = [d for d in db.deposits.values() if d["avoidance_action_id"] == id]
    return paginate([ser_deposit(d) for d in sorted_rows(rows)])


@bp.route("/trustee/cases/<id>/recovery_deposits", methods=["GET"])
def list_case_deposits(id):
    auth_context()
    require_roles(request.headers.get("X-User-Role"), ALL_ROLES)
    get_case(id)
    status = request.args.get("status")
    action_id = request.args.get("avoidance_action_id")
    rows = [d for d in db.deposits.values() if d["case_id"] == id]
    if status is not None:
        rows = [d for d in rows if d["status"] == status]
    if action_id is not None:
        rows = [d for d in rows if d["avoidance_action_id"] == action_id]
    return paginate([ser_deposit(d) for d in sorted_rows(rows)])


@bp.route("/trustee/recovery_deposits/<id>", methods=["GET"])
def get_deposit(id):
    auth_context()
    require_roles(request.headers.get("X-User-Role"), ALL_ROLES)
    return ok_object(ser_deposit(get_or_404(db.deposits, id, "recovery deposit")))


@bp.route("/trustee/avoidance_actions/<id>/analyze", methods=["POST"])
def analyze_action(id):
    uid, role = auth_context()
    require_roles(role, ("Trustee",))
    action, case = _get_action_and_case(id)
    ensure_case_open(case)
    if action["status"] != "IDENTIFIED":
        raise ApiError(ERR_INVALID_STATE, 409, "Action must be IDENTIFIED to analyze.")
    ensure_trustee_binding(case, uid)
    if not action["avoidable"]:
        raise ApiError(ERR_TRANSFER_NOT_AVOIDABLE, 409,
                       "The transfer falls outside the lookback window.")
    action["status"] = "ANALYZED"
    touch(action)
    return ok_object(ser_action(action))


@bp.route("/trustee/avoidance_actions/<id>/demand", methods=["POST"])
def demand_action(id):
    uid, role = auth_context()
    require_roles(role, ("Trustee",))
    action, case = _get_action_and_case(id)
    ensure_case_open(case)
    if action["status"] != "ANALYZED":
        raise ApiError(ERR_INVALID_STATE, 409, "Action must be ANALYZED to demand.")
    ensure_trustee_binding(case, uid)
    if not (0 < action["demand_amount_cents"] <= action["transfer_amount_cents"]):
        raise ApiError(ERR_INVALID_DEMAND_AMOUNT, 422,
                       "demand_amount_cents must be in (0, transfer_amount_cents].")
    action["status"] = "DEMANDED"
    touch(action)
    return ok_object(ser_action(action))


@bp.route("/trustee/avoidance_actions/<id>/settle", methods=["POST"])
def settle_action(id):
    uid, role = auth_context()
    require_roles(role, ("Trustee",))
    action, case = _get_action_and_case(id)
    ensure_case_open(case)
    if action["status"] != "DEMANDED":
        raise ApiError(ERR_INVALID_STATE, 409, "Action must be DEMANDED to settle.")
    ensure_trustee_binding(case, uid)
    body = json_body()
    settled = body.get("settled_amount_cents")
    if isinstance(settled, bool) or not isinstance(settled, int):
        raise ApiError(ERR_INVALID_REQUEST, 400, "settled_amount_cents is required and must be an integer.")
    if settled < 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "settled_amount_cents must be non-negative.")
    if settled > action["demand_amount_cents"]:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "settled_amount_cents may not exceed demand_amount_cents.")

    deposit = new_entity({
        "case_id": case["id"],
        "avoidance_action_id": id,
        "amount_cents": settled,
        "status": "POSTED",
    })
    db.deposits[deposit["id"]] = deposit
    action["recovered_amount_cents"] = settled
    action["status"] = "SETTLED"
    case["estate_cash_on_hand_cents"] += settled

    # Claim-swap: the unrecovered shortfall becomes a GENERAL_UNSECURED claim
    # of the transferee, received at the current logical time.
    shortfall = action["transfer_amount_cents"] - settled
    if shortfall > 0:
        swap = new_entity({
            "case_id": case["id"],
            "creditor_id": action["transferee_creditor_id"],
            "claim_number": 0,
            "received_at": CLOCK.now(),
            "filed_amount_cents": shortfall,
            "allowed_amount_cents": 0,
            "priority_class": "GENERAL_UNSECURED",
            "secured_by_asset_id": None,
            "reclassified_from_claim_id": None,
            "status": "FILED",
            "objection_id": None,
        })
        db.claims[swap["id"]] = swap
        register_claim_number(swap)

    touch(action)
    bump_case(case)
    return ok_object(ser_action(action))


@bp.route("/trustee/avoidance_actions/<id>/enter_judgment", methods=["POST"])
def enter_judgment(id):
    _, role = auth_context()
    require_roles(role, ("Court",))
    action, case = _get_action_and_case(id)
    ensure_case_open(case)
    if action["status"] != "DEMANDED":
        raise ApiError(ERR_INVALID_STATE, 409, "Action must be DEMANDED to enter judgment.")
    deposit = new_entity({
        "case_id": case["id"],
        "avoidance_action_id": id,
        "amount_cents": action["demand_amount_cents"],
        "status": "POSTED",
    })
    db.deposits[deposit["id"]] = deposit
    action["recovered_amount_cents"] = action["demand_amount_cents"]
    action["status"] = "JUDGMENT"
    case["estate_cash_on_hand_cents"] += action["demand_amount_cents"]
    touch(action)
    bump_case(case)
    return ok_object(ser_action(action))


@bp.route("/trustee/avoidance_actions/<id>/rescind", methods=["POST"])
def rescind_action(id):
    _, role = auth_context()
    require_roles(role, ("Court",))
    action, case = _get_action_and_case(id)
    ensure_case_open(case)
    if action["status"] != "JUDGMENT":
        raise ApiError(ERR_INVALID_STATE, 409, "Action must be JUDGMENT to rescind.")
    if case["status"] == "DISTRIBUTION" or any(
            p["case_id"] == case["id"] and p["status"] in ("CONFIRMED", "EXECUTING")
            for p in db.plans.values()):
        raise ApiError(ERR_PLAN_RELIES_ON_RECOVERY, 409,
                       "A distribution plan relies on this recovery.")
    if case["estate_cash_on_hand_cents"] < action["demand_amount_cents"]:
        raise ApiError(ERR_INSUFFICIENT_ESTATE_FUNDS, 409,
                       "Rescission would drive estate cash negative.")
    for deposit in db.deposits.values():
        if deposit["avoidance_action_id"] == id and deposit["status"] == "POSTED":
            deposit["status"] = "VOIDED"
            touch(deposit)
    action["recovered_amount_cents"] = 0
    action["status"] = "RESCINDED"
    case["estate_cash_on_hand_cents"] -= action["demand_amount_cents"]
    touch(action)
    bump_case(case)
    return ok_object(ser_action(action))


@bp.route("/trustee/avoidance_actions/<id>/abandon", methods=["POST"])
def abandon_action(id):
    uid, role = auth_context()
    require_roles(role, ("Trustee",))
    action, case = _get_action_and_case(id)
    ensure_case_open(case)
    if action["status"] not in ("IDENTIFIED", "ANALYZED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only an IDENTIFIED or ANALYZED action may be abandoned.")
    ensure_trustee_binding(case, uid)
    action["status"] = "ABANDONED"
    touch(action)
    return ok_object(ser_action(action))
