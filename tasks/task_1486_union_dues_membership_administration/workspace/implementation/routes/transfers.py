"""MemberTransfer lifecycle: list/get, certify, accept, reject, complete,
cancel."""
from flask import Blueprint, request

import db
import errors
import serializers
import utils
from middleware import require_roles, check_member_ownership, ALL_ROLES
from response import ok, ok_list
from services import ledger as ledger_svc

bp = Blueprint("transfers", __name__, url_prefix="/api/transfers")


def get_transfer_or_404(transfer_id):
    t = db.store.transfers.get(transfer_id)
    if t is None:
        raise errors.transfer_not_found()
    return t


@bp.route("", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_transfers(user_id, role):
    rows = list(db.store.transfers.values())
    for f in ("member_id", "from_local_id", "to_local_id", "status"):
        v = request.args.get(f)
        if v is not None:
            rows = [t for t in rows if t.get(f) == v]
    rows.sort(key=lambda t: t["_seq"])
    page, meta = utils.paginate(rows)
    return ok_list([serializers.transfer(t) for t in page], meta)


@bp.route("/<transfer_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_transfer(user_id, role, transfer_id):
    return ok(serializers.transfer(get_transfer_or_404(transfer_id)), 200)


@bp.route("/<transfer_id>/certify", methods=["POST"])
@require_roles("OfficeClerk")
def certify(user_id, role, transfer_id):
    t = get_transfer_or_404(transfer_id)
    if t["status"] != "INITIATED":
        raise errors.transfer_state_forbidden()
    member = db.store.members[t["member_id"]]
    arrears, _ = ledger_svc.balances(member["id"])
    if member["status"] != "ACTIVE" or arrears != 0:
        raise errors.not_good_standing()
    t["status"] = "PENDING_TARGET"
    db.touch(t)
    return ok(serializers.transfer(t), 200)


@bp.route("/<transfer_id>/accept", methods=["POST"])
@require_roles("OfficeClerk")
def accept(user_id, role, transfer_id):
    t = get_transfer_or_404(transfer_id)
    if t["status"] != "PENDING_TARGET":
        raise errors.transfer_state_forbidden()
    target = db.store.locals.get(t["to_local_id"])
    if target is None or target["status"] != "ACTIVE":
        raise errors.target_local_unavailable()
    t["status"] = "ACCEPTED_BY_TARGET"
    db.touch(t)
    return ok(serializers.transfer(t), 200)


@bp.route("/<transfer_id>/reject", methods=["POST"])
@require_roles("OfficeClerk")
def reject(user_id, role, transfer_id):
    t = get_transfer_or_404(transfer_id)
    if t["status"] != "PENDING_TARGET":
        raise errors.transfer_state_forbidden()
    body = request.get_json(silent=True) or {}
    t["reject_reason"] = body.get("reason")
    t["status"] = "REJECTED_BY_TARGET"
    db.touch(t)
    return ok(serializers.transfer(t), 200)


@bp.route("/<transfer_id>/complete", methods=["POST"])
@require_roles("SecretaryTreasurer")
def complete(user_id, role, transfer_id):
    t = get_transfer_or_404(transfer_id)
    if t["status"] != "ACCEPTED_BY_TARGET":
        raise errors.transfer_state_forbidden()
    member = db.store.members[t["member_id"]]
    if member["status"] != "ACTIVE":
        raise errors.not_good_standing()
    if utils.period_key(db.current_period()) < utils.period_key(t["effective_period"]):
        raise errors.transfer_not_ready()
    arrears, _ = ledger_svc.balances(member["id"])
    if arrears != 0:
        raise errors.arrears_outstanding()
    member["local_id"] = t["to_local_id"]
    db.touch(member)
    t["status"] = "COMPLETED"
    db.touch(t)
    return ok(serializers.transfer(t), 200)


@bp.route("/<transfer_id>/cancel", methods=["POST"])
@require_roles("Member", "OfficeClerk")
def cancel(user_id, role, transfer_id):
    t = get_transfer_or_404(transfer_id)
    check_member_ownership(user_id, role, t["member_id"])
    if t["status"] not in ("INITIATED", "PENDING_TARGET"):
        raise errors.transfer_state_forbidden()
    t["status"] = "CANCELLED"
    db.touch(t)
    return ok(serializers.transfer(t), 200)
