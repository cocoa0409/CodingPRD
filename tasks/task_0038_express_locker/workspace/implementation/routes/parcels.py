"""Parcel routes — deposit, pickup, recall, return, dispose, waive-fee, fees, disputes."""

from flask import Blueprint, g, request

from db import LOCK
from middleware import require_roles
from response import success_array, success_object, parse_pagination
from services.dispute import open_dispute, serialize_dispute
from services.fee import all_parcel_fees, serialize_fee
from services.parcel import (
    begin_deposit,
    cancel_deposit,
    cancel_pickup,
    confirm_deposit,
    correct_wrong_deposit,
    dispose_parcel,
    get_parcel,
    initiate_pickup,
    list_parcels,
    pickup_confirm,
    recall_parcel,
    retry_open,
    return_to_sender,
    serialize_parcel,
    waive_fee,
)


bp = Blueprint("parcels", __name__)


# --- Deposit ---


@bp.route("/parcels", methods=["POST"])
@require_roles("Courier")
def post_parcel():
    with LOCK:
        p = begin_deposit(request.get_json(silent=True) or {}, g.user_id)
        return success_object(serialize_parcel(p), 201)


@bp.route("/parcels/<parcel_id>/confirm-deposit", methods=["POST"])
@require_roles("Courier")
def post_confirm_deposit(parcel_id):
    with LOCK:
        p = confirm_deposit(parcel_id, request.get_json(silent=True) or {}, g.user_id)
        return success_object(serialize_parcel(p))


@bp.route("/parcels/<parcel_id>/cancel-deposit", methods=["POST"])
@require_roles("Courier")
def post_cancel_deposit(parcel_id):
    with LOCK:
        p = cancel_deposit(parcel_id, request.get_json(silent=True) or {}, g.user_id)
        return success_object(serialize_parcel(p))


@bp.route("/parcels/<parcel_id>/retry-open", methods=["POST"])
@require_roles("Courier")
def post_retry_open(parcel_id):
    with LOCK:
        p = retry_open(parcel_id, request.get_json(silent=True) or {}, g.user_id)
        return success_object(serialize_parcel(p))


@bp.route("/parcels/<parcel_id>/correct-wrong-deposit", methods=["POST"])
@require_roles("Courier")
def post_correct(parcel_id):
    with LOCK:
        p = correct_wrong_deposit(parcel_id, request.get_json(silent=True) or {}, g.user_id)
        return success_object(serialize_parcel(p))


# --- Pickup ---


@bp.route("/parcels/<parcel_id>/initiate-pickup", methods=["POST"])
@require_roles("Recipient")
def post_initiate_pickup(parcel_id):
    with LOCK:
        p = initiate_pickup(parcel_id, request.get_json(silent=True) or {}, g.user_id)
        return success_object(serialize_parcel(p))


@bp.route("/parcels/<parcel_id>/pickup-confirm", methods=["POST"])
@require_roles("Recipient")
def post_pickup_confirm(parcel_id):
    with LOCK:
        p = pickup_confirm(parcel_id, request.get_json(silent=True) or {}, g.user_id)
        return success_object(serialize_parcel(p))


@bp.route("/parcels/<parcel_id>/cancel-pickup", methods=["POST"])
@require_roles("Recipient")
def post_cancel_pickup(parcel_id):
    with LOCK:
        p = cancel_pickup(parcel_id, request.get_json(silent=True) or {}, g.user_id)
        return success_object(serialize_parcel(p))


# --- Long-stay paths ---


@bp.route("/parcels/<parcel_id>/recall", methods=["POST"])
@require_roles("Courier")
def post_recall(parcel_id):
    with LOCK:
        p = recall_parcel(parcel_id, request.get_json(silent=True) or {}, g.user_id)
        return success_object(serialize_parcel(p))


@bp.route("/parcels/<parcel_id>/return-to-sender", methods=["POST"])
@require_roles("OperationsAdmin")
def post_return(parcel_id):
    with LOCK:
        p = return_to_sender(parcel_id, request.get_json(silent=True) or {}, g.user_id)
        return success_object(serialize_parcel(p))


@bp.route("/parcels/<parcel_id>/dispose", methods=["POST"])
@require_roles("OperationsAdmin")
def post_dispose(parcel_id):
    with LOCK:
        p = dispose_parcel(parcel_id, request.get_json(silent=True) or {}, g.user_id)
        return success_object(serialize_parcel(p))


@bp.route("/parcels/<parcel_id>/waive-fee", methods=["POST"])
@require_roles("OperationsAdmin")
def post_waive_fee(parcel_id):
    with LOCK:
        fee = waive_fee(parcel_id, request.get_json(silent=True) or {}, g.user_id)
        return success_object(serialize_fee(fee))


# --- Reads ---


@bp.route("/parcels", methods=["GET"])
@require_roles("OperationsAdmin", "Courier", "Recipient", "Any")
def get_parcels():
    with LOCK:
        limit, offset = parse_pagination(request.args)
        all_records = list_parcels(request.args)
        sliced = all_records[offset: offset + limit]
        return success_array(
            [serialize_parcel(p) for p in sliced],
            limit=limit, offset=offset, total_count=len(all_records),
        )


@bp.route("/parcels/<parcel_id>", methods=["GET"])
@require_roles("OperationsAdmin", "Courier", "Recipient", "Any")
def get_one_parcel(parcel_id):
    with LOCK:
        p = get_parcel(parcel_id)
        return success_object(serialize_parcel(p))


@bp.route("/parcels/<parcel_id>/fees", methods=["GET"])
@require_roles("OperationsAdmin", "Courier", "Recipient", "Any")
def get_fees(parcel_id):
    with LOCK:
        get_parcel(parcel_id)
        limit, offset = parse_pagination(request.args)
        fees = all_parcel_fees(parcel_id)
        sliced = fees[offset: offset + limit]
        return success_array(
            [serialize_fee(f) for f in sliced],
            limit=limit, offset=offset, total_count=len(fees),
        )


# --- Disputes (open) ---


@bp.route("/parcels/<parcel_id>/disputes", methods=["POST"])
@require_roles("Recipient", "Courier")
def post_open_dispute(parcel_id):
    with LOCK:
        d = open_dispute(parcel_id, request.get_json(silent=True) or {}, g.role, g.user_id)
        return success_object(serialize_dispute(d), 201)
