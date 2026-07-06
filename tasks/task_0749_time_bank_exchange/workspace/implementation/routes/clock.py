"""POST /_clock/set_current_utc, POST /_ledger/admin-adjust."""
from flask import Blueprint, request
import db
from auth import require_role, ROLE_ADMIN
from errors import raise_err, ERR_INVALID_REQUEST, ERR_RESOURCE_NOT_FOUND
from response import envelope_object
from services import validators, balance, ledger, clock_sweep
from services.serializers import ledger_entry_dto

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    # PlatformAdmin only (per §1.4 priority 1 note: this endpoint DOES require
    # PlatformAdmin — the note in §1.4 exempts it from "authenticated" gate
    # semantically only when Anonymous, but scaffold pins roles=[PlatformAdmin].
    # We treat this as requiring the admin role like every other admin endpoint.
    require_role({ROLE_ADMIN})
    payload = request.get_json(silent=True) or {}
    validators.require_fields(payload, ["to_iso8601"])
    validators.require_datetime(payload, "to_iso8601")
    db.set_clock_iso(payload["to_iso8601"])
    clock_sweep.sweep()
    return envelope_object({}, status=200)


@bp.route("/_ledger/admin-adjust", methods=["POST"])
def admin_adjust():
    require_role({ROLE_ADMIN})
    payload = request.get_json(silent=True) or {}
    validators.require_fields(payload, ["member_id", "delta_minutes", "memo"])
    member_id = validators.require_str(payload, "member_id")
    memo = validators.require_str(payload, "memo")
    delta = validators.require_minute_multiple(
        payload, "delta_minutes", lo=15, hi=4800, allow_negative=True
    )
    m = db.members.get(member_id)
    if m is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "Member not found")

    entry = ledger.post_entry(
        member_id=member_id,
        entry_kind="ADMIN_ADJUSTMENT",
        delta_minutes=delta,
        memo=memo,
    )
    balance.recompute_member_snapshot(member_id, bump_version=True)
    return envelope_object(ledger_entry_dto(entry), status=201)
