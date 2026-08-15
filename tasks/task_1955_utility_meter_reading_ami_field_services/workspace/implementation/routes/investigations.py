"""Investigation endpoints: tamper/theft workflow with back-bill computation."""
from decimal import Decimal

from flask import Blueprint, request

from db import db, stamp_new, touch
from errors import (
    ApiError, ERR_NOT_FOUND, ERR_REFERENCED_ENTITY_NOT_FOUND, ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION, ERR_INVESTIGATION_ALREADY_OPEN,
    ERR_BACKBILL_INPUT_MISMATCH, ERR_SEGREGATION_OF_DUTIES,
    ERR_EXCHANGE_NOT_VERIFIED,
)
from middleware import require_roles, ALL_ROLES, body, req_str, req_enum
from response import success, list_response, created_sorted
from serializers import ser_investigation
from services.cascades import (
    suspect_meter, non_terminal_investigation_for_meter,
    cancel_pending_stops_for_account,
)
from util import round_half_up_decimal

bp = Blueprint("investigations", __name__)

RATE_CENTS_PER_KWH = Decimal("11.25")
PENALTY_PCT = Decimal("0.25")


def get_investigation(iid):
    i = db.investigations.get(iid)
    if not i:
        raise ApiError(ERR_NOT_FOUND, "Investigation not found", 404)
    return i


def _transition(inv, from_states, to_state):
    if inv["investigation_status"] not in from_states:
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            f"Investigation cannot move to {to_state} from {inv['investigation_status']}",
            409,
        )
    inv["investigation_status"] = to_state
    touch(inv)


@bp.route("/investigations", methods=["POST"])
def create():
    uid, _role = require_roles("Investigator")
    data = body()
    account_id = req_str(data, "service_account_id")
    meter_id = req_str(data, "meter_id")
    indication_type = req_enum(
        data, "indication_type", ("TAMPER_FLAG", "THEFT_REPORT", "USAGE_ANOMALY")
    )
    if account_id not in db.accounts:
        raise ApiError(ERR_REFERENCED_ENTITY_NOT_FOUND, "ServiceAccount not found", 404)
    if meter_id not in db.meters:
        raise ApiError(ERR_REFERENCED_ENTITY_NOT_FOUND, "Meter not found", 404)
    if non_terminal_investigation_for_meter(meter_id) is not None:
        raise ApiError(
            ERR_INVESTIGATION_ALREADY_OPEN,
            "A non-terminal investigation already exists for this meter",
            409,
        )
    rec = {
        "service_account_id": account_id,
        "meter_id": meter_id,
        "indication_type": indication_type,
        "investigation_status": "OPEN",
        "opened_by_user_id": uid,
        "closed_by_user_id": None,
        "triggering_read_id": None,
        "exchange_work_order_id": None,
        "theft_window_months": None,
        "monthly_estimated_kwh": None,
        "backbill_cents": None,
        "evidence_notes": [],
    }
    stamp_new(rec)
    db.investigations[rec["id"]] = rec
    suspect_meter(db.meters[meter_id])
    return success(ser_investigation(rec), code=201)


@bp.route("/investigations", methods=["GET"])
def list_all():
    require_roles(*ALL_ROLES)
    items = list(db.investigations.values())
    for param in ("service_account_id", "meter_id", "investigation_status",
                  "triggering_read_id", "exchange_work_order_id"):
        val = request.args.get(param)
        if val is not None:
            items = [i for i in items if i[param] == val]
    return list_response([ser_investigation(i) for i in created_sorted(items)])


@bp.route("/investigations/<iid>", methods=["GET"])
def get_one(iid):
    require_roles(*ALL_ROLES)
    return success(ser_investigation(get_investigation(iid)), code=200)


@bp.route("/investigations/<iid>/begin-evidence", methods=["POST"])
def begin_evidence(iid):
    require_roles("Investigator")
    inv = get_investigation(iid)
    _transition(inv, ("OPEN",), "EVIDENCE_GATHERING")
    return success(ser_investigation(inv), code=200)


@bp.route("/investigations/<iid>/submit-disposition", methods=["POST"])
def submit_disposition(iid):
    require_roles("Investigator")
    inv = get_investigation(iid)
    _transition(inv, ("EVIDENCE_GATHERING",), "PENDING_DISPOSITION")
    return success(ser_investigation(inv), code=200)


@bp.route("/investigations/<iid>/request-more-evidence", methods=["POST"])
def request_more_evidence(iid):
    require_roles("Investigator")
    inv = get_investigation(iid)
    _transition(inv, ("PENDING_DISPOSITION",), "EVIDENCE_GATHERING")
    return success(ser_investigation(inv), code=200)


def _compute_backbill(monthly_kwh):
    # pinned nested rounding: per-month rounding BEFORE summation
    charges = [
        int(round_half_up_decimal(Decimal(kwh) * RATE_CENTS_PER_KWH))
        for kwh in monthly_kwh
    ]
    subtotal = sum(charges)
    penalty = int(round_half_up_decimal(Decimal(subtotal) * PENALTY_PCT))
    return subtotal + penalty


@bp.route("/investigations/<iid>/confirm-theft", methods=["POST"])
def confirm_theft(iid):
    require_roles("Investigator")
    data = body()
    months = data.get("theft_window_months")
    if months is None or not isinstance(months, int) or isinstance(months, bool) or months < 1:
        raise ApiError(
            ERR_INVALID_REQUEST, "theft_window_months must be a positive integer", 400
        )
    monthly = data.get("monthly_estimated_kwh")
    if (
        not isinstance(monthly, list)
        or any(not isinstance(v, int) or isinstance(v, bool) or v < 0 for v in monthly)
    ):
        raise ApiError(
            ERR_INVALID_REQUEST,
            "monthly_estimated_kwh must be an array of non-negative integers",
            400,
        )
    if len(monthly) != months:
        raise ApiError(
            ERR_BACKBILL_INPUT_MISMATCH,
            "monthly_estimated_kwh length must equal theft_window_months",
            422,
        )
    inv = get_investigation(iid)
    if inv["investigation_status"] != "PENDING_DISPOSITION":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "Investigation is not PENDING_DISPOSITION",
            409,
        )
    inv["theft_window_months"] = months
    inv["monthly_estimated_kwh"] = list(monthly)
    inv["backbill_cents"] = _compute_backbill(monthly)
    inv["investigation_status"] = "CONFIRMED_THEFT"
    touch(inv)
    # auto-create the EXCHANGE work order (system cascade; bypasses the hold)
    wo = {
        "work_order_type": "EXCHANGE",
        "service_account_id": inv["service_account_id"],
        "meter_id": inv["meter_id"],
        "route_stop_id": None,
        "investigation_id": inv["id"],
        "campaign_enrollment_id": None,
        "scheduled_date": None,
        "work_shift": None,
        "notes": None,
        "technician_id": None,
        "work_order_status": "OPEN",
        "new_meter_id": None,
        "old_final_read_value": None,
        "new_initial_read_value": None,
        "reread_value": None,
        "reread_at": None,
        "evidence_note": None,
        "completed_at": None,
    }
    stamp_new(wo)
    db.work_orders[wo["id"]] = wo
    inv["exchange_work_order_id"] = wo["id"]
    touch(inv)
    meter = db.meters.get(inv["meter_id"])
    if meter and meter["tamper_status"] == "SUSPECTED":
        meter["tamper_status"] = "CONFIRMED"
        touch(meter)
    account = db.accounts.get(inv["service_account_id"])
    if account and account["account_status"] == "ACTIVE":
        account["account_status"] = "SUSPENDED"
        touch(account)
        cancel_pending_stops_for_account(account["id"])
    return success(ser_investigation(inv), code=200)


@bp.route("/investigations/<iid>/clear", methods=["POST"])
def clear(iid):
    require_roles("Investigator")
    inv = get_investigation(iid)
    _transition(inv, ("PENDING_DISPOSITION",), "CLEARED")
    meter = db.meters.get(inv["meter_id"])
    if meter and meter["tamper_status"] == "SUSPECTED":
        meter["tamper_status"] = "NONE"
        touch(meter)
    return success(ser_investigation(inv), code=200)


@bp.route("/investigations/<iid>/close", methods=["POST"])
def close(iid):
    uid, _role = require_roles("Investigator")
    inv = get_investigation(iid)
    if inv["investigation_status"] not in ("CONFIRMED_THEFT", "CLEARED"):
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "Investigation can be closed only from CONFIRMED_THEFT or CLEARED",
            409,
        )
    if uid == inv["opened_by_user_id"]:
        raise ApiError(
            ERR_SEGREGATION_OF_DUTIES,
            "The opener of an investigation cannot close it",
            403,
        )
    if inv["investigation_status"] == "CONFIRMED_THEFT":
        wo = db.work_orders.get(inv["exchange_work_order_id"] or "")
        if not wo or wo["work_order_status"] != "VERIFIED":
            raise ApiError(
                ERR_EXCHANGE_NOT_VERIFIED,
                "The auto-created exchange work order is not VERIFIED",
                409,
            )
    inv["investigation_status"] = "CLOSED"
    inv["closed_by_user_id"] = uid
    touch(inv)
    return success(ser_investigation(inv), code=200)
