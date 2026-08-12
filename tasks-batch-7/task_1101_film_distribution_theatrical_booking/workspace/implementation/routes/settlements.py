"""Settlement endpoints."""
from flask import Blueprint, request

from db import db
from middleware import require_roles
from response import success_object
from errors import (
    err_invalid_state, err_sod,
)
from services.core import (
    serialize_settlement, get_settlement, get_booking, get_distributor,
    touch, compute_distributor_posture,
)
from services.cascade import check_film_holdover_phase
from ._helpers import paginate_list

bp = Blueprint("settlements", __name__)


@bp.route("/distributors/<did>/booking-agreements/<baid>/settlements/<sid>", methods=["GET"])
@require_roles("PlatformAdmin", "Booker", "Exhibitor", "SettlementClerk", "Auditor")
def read_settlement(did, baid, sid, _user_id, _role):
    return success_object(serialize_settlement(get_settlement(did, baid, sid)))


@bp.route("/distributors/<did>/booking-agreements/<baid>/settlements", methods=["GET"])
@require_roles("PlatformAdmin", "Booker", "Exhibitor", "SettlementClerk", "Auditor")
def list_settlements(did, baid, _user_id, _role):
    get_booking(did, baid)
    items = [s for s in db.settlements.values() if s["booking_agreement_id"] == baid]
    filters = {}
    for k in ("status", "week_index", "variant", "booking_agreement_id"):
        if k in request.args:
            filters[k] = request.args.get(k)
    return paginate_list(items, serialize_settlement, filters)


@bp.route("/distributors/<did>/booking-agreements/<baid>/settlements/<sid>/mark_settled", methods=["POST"])
@require_roles("SettlementClerk")
def mark_settled(did, baid, sid, _user_id, _role):
    b = get_booking(did, baid)
    s = get_settlement(did, baid, sid)
    # SoD: clerk cannot be the agreement's creator (priority 17 — after state at 5)
    if s["status"] != "FINALIZED":
        raise err_invalid_state("Settlement must be FINALIZED")
    if b.get("created_by_user_id") == _user_id:
        raise err_sod()
    s["status"] = "SETTLED"
    touch(s)
    b["weeks_played"] += 1
    touch(b)
    check_film_holdover_phase(b["film_id"])
    return success_object(serialize_settlement(s))


@bp.route("/distributors/<did>/booking-agreements/<baid>/settlements/<sid>/dispute", methods=["POST"])
@require_roles("Exhibitor")
def dispute_settlement(did, baid, sid, _user_id, _role):
    s = get_settlement(did, baid, sid)
    if s["status"] != "FINALIZED":
        raise err_invalid_state("Settlement must be FINALIZED")
    s["status"] = "DISPUTED"
    touch(s)
    # Cascade distributor FROZEN is computed on the fly; nothing to store.
    return success_object(serialize_settlement(s))


@bp.route("/distributors/<did>/booking-agreements/<baid>/settlements/<sid>/resolve_dispute", methods=["POST"])
@require_roles("SettlementClerk")
def resolve_dispute(did, baid, sid, _user_id, _role):
    b = get_booking(did, baid)
    s = get_settlement(did, baid, sid)
    if s["status"] != "DISPUTED":
        raise err_invalid_state("Settlement must be DISPUTED")
    if b.get("created_by_user_id") == _user_id:
        raise err_sod()
    s["status"] = "FINALIZED"
    touch(s)
    return success_object(serialize_settlement(s))


@bp.route("/distributors/<did>/booking-agreements/<baid>/settlements/<sid>/write_off", methods=["POST"])
@require_roles("SettlementClerk")
def write_off(did, baid, sid, _user_id, _role):
    d = get_distributor(did)
    b = get_booking(did, baid)
    s = get_settlement(did, baid, sid)
    if s["status"] != "FINALIZED":
        raise err_invalid_state("Settlement must be FINALIZED")
    # Must be older than 2 week_epochs
    if d["week_epoch"] - s["week_index"] < 2:
        raise err_invalid_state("Settlement must be older than 2 week_epochs")
    s["status"] = "WRITTEN_OFF"
    touch(s)
    b["weeks_played"] += 1
    touch(b)
    check_film_holdover_phase(b["film_id"])
    return success_object(serialize_settlement(s))
