"""ACH originations, legs, settle, reverse — PRD §3.12-§3.14."""
from flask import Blueprint, request

from db import db
from middleware import require_roles
from response import object_response
from models import stamp_new, touch, public
from services.validate import (
    get_body, require_fields, require_enum, require_positive_int_amount,
)
from services.resolve import get_ach_origination, get_ach_leg, get_account
from services import ach as ach_svc
from routes.common import paged_list
import errors
from errors import ApiError

bp = Blueprint("ach", __name__)

POSTING_ORDERS = {"CHRONOLOGICAL", "HIGH_TO_LOW"}
LEG_ROLES = {"DEBIT", "CREDIT"}


def serialize_origination(o):
    return public(o)


def serialize_leg(l):
    return public(l)


@bp.route("/ach-originations", methods=["POST"])
@require_roles("ComplianceOfficer", "Teller")
def create_origination():
    body = get_body()
    require_fields(body, "debtor_account_id", "creditor_account_id")
    # Referenced accounts must resolve (specialized not-found).
    get_account(body["debtor_account_id"], specialized=True)
    get_account(body["creditor_account_id"], specialized=True)

    posting_order = body.get("posting_order", "CHRONOLOGICAL")
    if posting_order is None:
        posting_order = "CHRONOLOGICAL"
    if posting_order not in POSTING_ORDERS:
        raise ApiError(errors.ERR_INVALID_REQUEST, 422,
                       "posting_order must be CHRONOLOGICAL or HIGH_TO_LOW")

    orig = {
        "debtor_account_id": body["debtor_account_id"],
        "creditor_account_id": body["creditor_account_id"],
        "posting_order": posting_order,
        "status": "STAGED",
        "total_debit_cents": 0,
        "total_credit_cents": 0,
    }
    stamp_new(orig)
    db.ach_originations[orig["id"]] = orig
    return object_response(serialize_origination(orig), status=201)


@bp.route("/ach-originations/<orig_id>", methods=["GET"])
@require_roles("ComplianceOfficer", "Teller")
def get_origination(orig_id):
    o = get_ach_origination(orig_id)
    return object_response(serialize_origination(o))


@bp.route("/ach-originations", methods=["GET"])
@require_roles("ComplianceOfficer", "Teller")
def list_originations():
    debtor = request.args.get("debtor_account_id")
    creditor = request.args.get("creditor_account_id")
    status = request.args.get("status")
    rows = list(db.ach_originations.values())
    if debtor is not None:
        rows = [o for o in rows if o["debtor_account_id"] == debtor]
    if creditor is not None:
        rows = [o for o in rows if o["creditor_account_id"] == creditor]
    if status is not None:
        rows = [o for o in rows if o["status"] == status]
    return paged_list(rows, serializer=serialize_origination)


@bp.route("/ach-originations/<orig_id>/legs", methods=["POST"])
@require_roles("ComplianceOfficer", "Teller")
def add_leg(orig_id):
    o = get_ach_origination(orig_id)
    body = get_body()
    require_fields(body, "leg_role", "amount_cents", "expected_ach_origination_version")
    leg_role = require_enum(body, "leg_role", LEG_ROLES)
    amount = require_positive_int_amount(body["amount_cents"])

    # State gate: legs are added only to a STAGED batch.
    if o["status"] != "STAGED":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Origination is not STAGED")
    # OCC guard (PRD §2.6): expected version must match current version.
    _check_version(o, body["expected_ach_origination_version"])

    leg = {
        "ach_origination_id": orig_id,
        "leg_role": leg_role,
        "amount_cents": amount,
        "produced_transaction_id": None,
        "settlement_outcome": None,
    }
    stamp_new(leg)
    db.ach_legs[leg["id"]] = leg
    # Adding a leg advances the origination's version by one (PRD §2.6).
    touch(o)
    return object_response(serialize_leg(leg), status=201)


@bp.route("/ach-originations/<orig_id>/legs", methods=["GET"])
@require_roles("ComplianceOfficer", "Teller")
def list_legs(orig_id):
    get_ach_origination(orig_id)
    rows = [l for l in db.ach_legs.values() if l["ach_origination_id"] == orig_id]
    return paged_list(rows, serializer=serialize_leg)


@bp.route("/ach-legs/<leg_id>", methods=["GET"])
@require_roles("ComplianceOfficer", "Teller")
def get_leg(leg_id):
    l = get_ach_leg(leg_id)
    return object_response(serialize_leg(l))


@bp.route("/ach-legs", methods=["GET"])
@require_roles("ComplianceOfficer", "Teller")
def list_all_legs():
    produced = request.args.get("produced_transaction_id")
    orig_id = request.args.get("ach_origination_id")
    rows = list(db.ach_legs.values())
    if produced is not None:
        rows = [l for l in rows if l["produced_transaction_id"] == produced]
    if orig_id is not None:
        rows = [l for l in rows if l["ach_origination_id"] == orig_id]
    return paged_list(rows, serializer=serialize_leg)


@bp.route("/ach-originations/<orig_id>/settle", methods=["POST"])
@require_roles("ComplianceOfficer")
def settle(orig_id):
    o = get_ach_origination(orig_id)
    body = get_body()
    require_fields(body, "expected_ach_origination_version")
    # State gate (priority 5) precedes OCC (priority 8).
    if o["status"] != "STAGED":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Origination is not STAGED")
    _check_version(o, body["expected_ach_origination_version"])
    # Both accounts must exist and not be CLOSED.
    debtor = db.accounts.get(o["debtor_account_id"])
    creditor = db.accounts.get(o["creditor_account_id"])
    if debtor is None or creditor is None or debtor["status"] == "CLOSED" or creditor["status"] == "CLOSED":
        raise ApiError(errors.ERR_ACCOUNT_NOT_FOUND, 404,
                       "Debtor or creditor account missing or CLOSED")

    ach_svc.settle(o)
    return object_response(serialize_origination(o))


@bp.route("/ach-originations/<orig_id>/reverse", methods=["POST"])
@require_roles("ComplianceOfficer")
def reverse(orig_id):
    o = get_ach_origination(orig_id)
    body = get_body()
    require_fields(body, "expected_ach_origination_version")
    # State gate (priority 5) precedes OCC (priority 8).
    if o["status"] != "SETTLED":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Origination is not SETTLED")
    _check_version(o, body["expected_ach_origination_version"])

    ach_svc.reverse(o)
    return object_response(serialize_origination(o))


def _check_version(origination, expected):
    """OCC: expected_ach_origination_version must equal current version."""
    if expected != origination.get("version"):
        raise ApiError(errors.ERR_STALE_VERSION, 412,
                       "expected_ach_origination_version does not match current version")
