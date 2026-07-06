"""RetainerCycle endpoints (PRD §3.8)."""
import copy

from flask import Blueprint, request

import errors
import middleware as mw
from clock import clock
from db import db
from response import array_response, object_response
from routes.common import assert_show_owner, get_or_404
from serialize import serialize, serialize_list
from services import calc, retainer, show_state
from timeutil import parse_iso8601

bp = Blueprint("retainer_cycles", __name__)


def _overlaps(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


@bp.post("/retainer-cycles")
def create_cycle():
    auth = mw.authenticate()
    mw.require_role(auth, {"PlatformAdmin"})
    body = mw.get_json_body()
    contract_id = mw.require_string(body, "contract_id")
    contract = get_or_404(db.contracts, contract_id)
    start_raw = mw.require_string(body, "cycle_start_utc")
    end_raw = mw.require_string(body, "cycle_end_utc")
    try:
        start = parse_iso8601(start_raw)
        end = parse_iso8601(end_raw)
    except ValueError:
        raise errors.err(errors.ERR_INVALID_REQUEST, "Invalid datetime")
    # window well-formedness (priority 27)
    if not (end > start):
        raise errors.err(errors.ERR_INVALID_WINDOW, "cycle_end_utc must be strictly after start")
    # overlap with any existing cycle of SAME contract, any status (priority 28)
    for c in db.retainer_cycles.all():
        if c["contract_id"] != contract_id:
            continue
        if _overlaps(start, end, c["cycle_start_utc"], c["cycle_end_utc"]):
            raise errors.err(errors.ERR_CYCLE_OVERLAP, "Cycle window overlaps an existing cycle")
    rec = db.retainer_cycles.create({
        "contract_id": contract_id,
        "cycle_start_utc": start,
        "cycle_end_utc": end,
        "status": "OPEN",
        "included_consumed": 0,
        "overage_episode_count": 0,
        "closed_at": None,
    })
    return object_response(serialize(rec), status=201)


@bp.get("/retainer-cycles")
def list_cycles():
    auth = mw.authenticate()
    mw.require_role(auth, {"PlatformAdmin", "ShowOwner"})
    limit, offset = mw.parse_pagination()
    records = db.retainer_cycles.all()
    contract_id = request.args.get("contract_id")
    status = request.args.get("status")
    if contract_id is not None:
        records = [r for r in records if r["contract_id"] == contract_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    if auth.role == "ShowOwner":
        records = [r for r in records if _show_of_cycle(r) == auth.user_id]
    page, meta = mw.paginate(records, limit, offset)
    return array_response(serialize_list(page), meta)


def _show_of_cycle(cycle):
    contract = db.contracts.get(cycle["contract_id"])
    return contract["show_id"] if contract else None


@bp.get("/retainer-cycles/<rid>")
def get_cycle(rid):
    auth = mw.authenticate()
    mw.require_role(auth, {"PlatformAdmin", "ShowOwner"})
    rec = get_or_404(db.retainer_cycles, rid)
    if auth.role == "ShowOwner":
        assert_show_owner(auth, _show_of_cycle(rec))
    return object_response(serialize(rec))


@bp.get("/retainer-cycles/<rid>/projection")
def projection(rid):
    auth = mw.authenticate()
    mw.require_role(auth, {"PlatformAdmin", "ShowOwner"})
    rec = get_or_404(db.retainer_cycles, rid)
    if auth.role == "ShowOwner":
        assert_show_owner(auth, _show_of_cycle(rec))
    contract = db.contracts.get(rec["contract_id"])
    included, overage, _ = retainer.reconcile(contract, rec, "provisional")
    # Projection does NOT persist; return a copy with projected fields.
    projected = copy.deepcopy(rec)
    projected["included_consumed"] = included
    projected["overage_episode_count"] = overage
    return object_response(serialize(projected))


@bp.post("/retainer-cycles/<rid>/close")
def close_cycle(rid):
    auth = mw.authenticate()
    mw.require_role(auth, {"PlatformAdmin"})
    rec = get_or_404(db.retainer_cycles, rid)
    contract = db.contracts.get(rec["contract_id"])
    # state legality first (PRD §2.8), then engagement_type business gate
    if rec["status"] != "OPEN":
        raise errors.err(errors.ERR_INVALID_STATE, "Cycle is not OPEN")
    if contract is None or contract["engagement_type"] != "RETAINER":
        raise errors.err(errors.ERR_NOT_RETAINER, "Owning contract is not RETAINER")
    included, overage, overage_subtotal = retainer.reconcile(contract, rec, "final")
    rec["included_consumed"] = included
    rec["overage_episode_count"] = overage
    rec["closed_at"] = clock.now()
    rec["status"] = "CLOSED"
    db.retainer_cycles.touch(rec)
    show = db.shows.get(contract["show_id"])
    if overage > 0:
        # RETAINER_OVERAGE invoice; subtotal = overage subtotal; discount/late/total
        # as for any invoice. Retainer overage is not flagged delivered_late.
        snapshot = show["lifetime_billed_cents"]
        subtotal, discount, late_fee, total = calc.overage_invoice_amounts(
            contract["tier"], overage, contract["loyalty_discount_pct"], False, snapshot)
        # subtotal is recomputed inside calc; align with reconciliation subtotal
        # (same arithmetic: overage * rate).
        db.invoices.create({
            "show_id": show["id"],
            "episode_id": None,
            "retainer_cycle_id": rec["id"],
            "kind": "RETAINER_OVERAGE",
            "subtotal_cents": subtotal,
            "discount_cents": discount,
            "late_fee_cents": late_fee,
            "total_cents": total,
            "status": "ISSUED",
        })
        show["lifetime_billed_cents"] = snapshot + total
        db.shows.touch(show)
    if show is not None:
        show_state.recompute_posture(show)
    return object_response(serialize(rec))
