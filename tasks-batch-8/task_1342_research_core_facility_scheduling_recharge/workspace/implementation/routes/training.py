"""Training records (PRD §3.3)."""

from flask import Blueprint, request

from auth import authenticate, require_roles, is_entity_role, auth_id
from errors import fail
from helpers import (
    Body, validate_body, training_effective_status, ser_training, find_training,
    CERT_VALIDITY_MONTHS,
)
from routes.instruments import get_instrument_or_404
from store import store, now
from util import new_entity, ok_object, parse_pagination, paginate, sort_default, touch, add_months, fmt_ts

bp = Blueprint("training", __name__)


def get_training_or_404(tid):
    rec = store.training_records.get(tid)
    if rec is None:
        fail("ERR_NOT_FOUND", "Training record not found")
    return rec


@bp.route("/training-records", methods=["POST"])
def create_training():
    authenticate()
    require_roles("CoreStaff", "FacilityAdmin")
    body = Body(request.get_json(silent=True))
    # Priority 4 — body FK existence (left-to-right: user_id, instrument_id)
    user_id = body.get("user_id")
    instrument_id = body.get("instrument_id")
    if user_id is not None and user_id not in store.users:
        fail("ERR_NOT_FOUND", "user_id does not reference an existing user")
    if instrument_id is not None and instrument_id not in store.instruments:
        fail("ERR_NOT_FOUND", "instrument_id does not reference an existing instrument")
    # Priority 21 — formats
    validate_body(
        body,
        allowed={"user_id", "instrument_id"},
        required={"user_id", "instrument_id"},
        checkers={
            "user_id": lambda v: isinstance(v, str),
            "instrument_id": lambda v: isinstance(v, str),
        },
    )
    # Priority 22 — one non-REVOKED record per (user, instrument)
    if find_training(user_id, instrument_id) is not None:
        fail("ERR_UNIQUE_CONSTRAINT", "A non-revoked training record already exists for this pair")
    rec = new_entity({
        "user_id": user_id,
        "instrument_id": instrument_id,
        "status": "ENROLLED",
        "certified_at": None,
        "expires_at": None,
        "expires_at_dt": None,
    })
    store.training_records[rec["id"]] = rec
    return ok_object(ser_training(rec), status=201)


@bp.route("/training-records", methods=["GET"])
def list_training():
    authenticate()
    require_roles("CoreStaff", "FacilityAdmin", "Researcher", "ExternalClient")
    limit, offset = parse_pagination(request.args)
    items = list(store.training_records.values())
    if is_entity_role():
        items = [r for r in items if r["user_id"] == auth_id()]
    else:
        user_id = request.args.get("user_id")
        if user_id is not None:
            items = [r for r in items if r["user_id"] == user_id]
    instrument_id = request.args.get("instrument_id")
    if instrument_id is not None:
        items = [r for r in items if r["instrument_id"] == instrument_id]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if training_effective_status(r) == status]
    return paginate(sort_default(items), limit, offset, ser_training)


@bp.route("/training-records/<tid>", methods=["GET"])
def get_training(tid):
    authenticate()
    require_roles("CoreStaff", "FacilityAdmin", "Researcher", "ExternalClient")
    rec = get_training_or_404(tid)
    if is_entity_role() and rec["user_id"] != auth_id():
        fail("ERR_FORBIDDEN", "Entity-backed callers may only access their own resources")
    return ok_object(ser_training(rec))


@bp.route("/training-records/<tid>/certify", methods=["POST"])
def certify_training(tid):
    authenticate()
    require_roles("CoreStaff")
    rec = get_training_or_404(tid)
    # Priority 6 — state legality (effective status must be ENROLLED)
    if training_effective_status(rec) != "ENROLLED":
        fail("ERR_INVALID_STATE", "Only an ENROLLED record can be certified")
    # Priority 11 — user must be ACTIVE
    user = store.users.get(rec["user_id"])
    if user is not None and user["status"] != "ACTIVE":
        fail("ERR_USER_SUSPENDED", "Suspended users cannot be certified")
    # Instrument must not be RETIRED
    inst = store.instruments.get(rec["instrument_id"])
    if inst is not None and inst["status"] == "RETIRED":
        fail("ERR_INVALID_STATE", "Cannot certify training for a RETIRED instrument")
    ts = now()
    rec["status"] = "CERTIFIED"
    rec["certified_at"] = fmt_ts(ts)
    rec["expires_at_dt"] = add_months(ts, CERT_VALIDITY_MONTHS)
    rec["expires_at"] = fmt_ts(rec["expires_at_dt"])
    touch(rec)
    return ok_object(ser_training(rec))


@bp.route("/training-records/<tid>/re-enroll", methods=["POST"])
def reenroll_training(tid):
    authenticate()
    require_roles("CoreStaff")
    rec = get_training_or_404(tid)
    if training_effective_status(rec) != "EXPIRED":
        fail("ERR_INVALID_STATE", "Only an EXPIRED record can be re-enrolled")
    rec["status"] = "ENROLLED"
    rec["certified_at"] = None
    rec["expires_at"] = None
    rec["expires_at_dt"] = None
    touch(rec)
    return ok_object(ser_training(rec))


@bp.route("/training-records/<tid>/revoke", methods=["POST"])
def revoke_training(tid):
    authenticate()
    require_roles("CoreStaff")
    rec = get_training_or_404(tid)
    if rec["status"] == "REVOKED":
        fail("ERR_INVALID_STATE", "Training record is already REVOKED")
    rec["status"] = "REVOKED"
    touch(rec)
    return ok_object(ser_training(rec))
