from flask import Blueprint, g, request

from db import store
from errors import (invalid_request, stale_version, integrity_error,
                    conflict_error)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_array, paginate
from services.common import get_or_404
from services.ledger import post_ledger
from services.serializers import ledger_json
from validate import Body, get_body

bp = Blueprint("ledger", __name__)

READ = ALL_ROLES


@bp.route("/api/clubs/<clubId>/ledger-entries", methods=["POST"])
@require_roles("Treasurer")
def post_adjustment(clubId):
    data = get_body()
    club = get_or_404(store.clubs, clubId, "club")
    # OCC (rung 6) when present; absence is caught as a shape error below
    if "expected_club_version" in data and data["expected_club_version"] is not None:
        ev = data["expected_club_version"]
        if not isinstance(ev, int) or isinstance(ev, bool):
            raise invalid_request("expected_club_version must be an integer")
        if ev != club["version"]:
            raise stale_version()
    body = Body(data, {"entry_type", "amount_cents", "memo",
                       "expected_club_version"})
    entry_type = body.req_str("entry_type")
    if entry_type != "ADJUSTMENT":
        raise invalid_request("Manual posts must use entry_type ADJUSTMENT")
    amount = body.req_int("amount_cents")
    if amount == 0:
        raise invalid_request("amount_cents must be non-zero")
    memo = body.opt_str("memo")
    body.req_int("expected_club_version")
    le = post_ledger(club["id"], "ADJUSTMENT", amount, g.user_id, memo=memo)
    return success_object(ledger_json(le), 201)


@bp.route("/api/clubs/<clubId>/ledger-entries", methods=["GET"])
@require_roles(*READ)
def list_club_ledger(clubId):
    club = get_or_404(store.clubs, clubId, "club")
    items = [le for le in store.ledger_entries.values()
             if le["club_id"] == club["id"]]
    page, limit, offset, total = paginate(items, request.args)
    return success_array([ledger_json(le) for le in page], 200, paginated=True,
                         limit=limit, offset=offset, total_count=total)


@bp.route("/api/ledger-entries", methods=["GET"])
@require_roles(*READ)
def list_ledger():
    items = list(store.ledger_entries.values())
    cid = request.args.get("club_id")
    if cid is not None:
        items = [le for le in items if le["club_id"] == cid]
    mid = request.args.get("membership_id")
    if mid is not None:
        items = [le for le in items if le.get("membership_id") == mid]
    eid = request.args.get("entry_id")
    if eid is not None:
        items = [le for le in items if le.get("entry_id") == eid]
    rid = request.args.get("reversal_of_id")
    if rid is not None:
        items = [le for le in items if le.get("reversal_of_id") == rid]
    etype = request.args.get("entry_type")
    if etype is not None:
        items = [le for le in items if le["entry_type"] == etype]
    page, limit, offset, total = paginate(items, request.args)
    return success_array([ledger_json(le) for le in page], 200, paginated=True,
                         limit=limit, offset=offset, total_count=total)


@bp.route("/api/ledger-entries/<ledgerEntryId>", methods=["GET"])
@require_roles(*READ)
def get_ledger_entry(ledgerEntryId):
    le = get_or_404(store.ledger_entries, ledgerEntryId, "ledger entry")
    return success_object(ledger_json(le), 200)


@bp.route("/api/ledger-entries/<ledgerEntryId>/reverse", methods=["POST"])
@require_roles("Auditor")
def reverse_entry(ledgerEntryId):
    data = get_body()
    le = get_or_404(store.ledger_entries, ledgerEntryId, "ledger entry")
    body = Body(data, {"memo"})
    memo = body.opt_str("memo")
    # segregation of duties (rung 9) precedes already-reversed (rung 11)
    if le["posted_by_user_id"] == g.user_id:
        raise integrity_error("ERR_SEGREGATION_OF_DUTIES",
                              "Reverser must differ from the original poster")
    if le["entry_type"] == "REVERSAL" or le.get("reversed_by_id"):
        raise conflict_error("ERR_ALREADY_REVERSED",
                             "Entry is already reversed or is a reversal")
    rev = post_ledger(le["club_id"], "REVERSAL", -le["amount_cents"], g.user_id,
                      memo=memo, reversal_of_id=le["id"])
    le["reversed_by_id"] = rev["id"]  # only post-creation mutation allowed
    return success_object(ledger_json(rev), 201)
