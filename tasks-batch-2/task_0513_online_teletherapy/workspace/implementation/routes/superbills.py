"""Superbill routes: draft, fetch, issue, void; reimbursable aggregation."""
from flask import Blueprint, request

from db import db, common_create_fields, touch
from clock import parse_iso
from errors import err, ERR_INVALID_STATE
from middleware import get_auth, require_role
from lookup import get_or_404, check_client_owner
from validate import require_body, require_datetime
import serialize
from response import success

bp = Blueprint("superbills", __name__)


def _compute_superbill(client_id, period_start_iso, period_end_iso):
    """Chronological aggregation of COMPLETED sessions in [period_start, period_end)."""
    period_start = parse_iso(period_start_iso)
    period_end = parse_iso(period_end_iso)
    # client's match ids
    client_match_ids = {m["id"] for m in db.matches.values() if m["client_id"] == client_id}
    sessions = []
    for s in db.live_sessions.values():
        if s["match_id"] not in client_match_ids:
            continue
        if s["status"] != "COMPLETED":
            continue
        s_start = parse_iso(s["starts_at"])
        if period_start <= s_start < period_end:
            sessions.append(s)
    sessions.sort(key=lambda s: (parse_iso(s["starts_at"]), s["created_at"], s["_seq"]))
    session_count = len(sessions)
    total = 0
    for s in sessions:
        s_start = parse_iso(s["starts_at"])
        cycle = _containing_paid_cycle(s_start)
        if cycle is None:
            continue
        credits = cycle["credits_granted"]
        if credits < 1:
            credits = 1
        per_session = cycle["list_amount_cents"] // credits  # floor
        total += per_session
    return session_count, total


def _containing_paid_cycle(instant):
    for b in db.billing_cycles.values():
        if b["status"] != "PAID":
            continue
        ps = parse_iso(b["period_start"])
        pe = parse_iso(b["period_end"])
        if ps <= instant < pe:
            return b
    return None


@bp.route("/clients/<cid>/superbills", methods=["POST"])
def draft_superbill(cid):
    user_id, role = get_auth()
    require_role(role, {"BillingAdmin"})
    client = get_or_404(db.clients, cid)
    data = require_body(request.get_json(silent=True))
    period_start = require_datetime(data, "period_start")
    period_end = require_datetime(data, "period_end")
    if period_end <= period_start:
        from errors import ERR_INVALID_REQUEST
        raise err(ERR_INVALID_REQUEST, "period_end must be after period_start")
    session_count, reimbursable = _compute_superbill(cid, data["period_start"], data["period_end"])
    superbill = {
        **common_create_fields(),
        "client_id": cid,
        "period_start": data["period_start"],
        "period_end": data["period_end"],
        "status": "DRAFT",
        "session_count": session_count,
        "reimbursable_amount_cents": reimbursable,
    }
    db.superbills[superbill["id"]] = superbill
    return success(serialize.superbill_out(superbill), status=201)


@bp.route("/superbills/<sid>", methods=["GET"])
def get_superbill(sid):
    user_id, role = get_auth()
    require_role(role, {"Client", "BillingAdmin"})
    superbill = get_or_404(db.superbills, sid)
    check_client_owner(role, user_id, superbill["client_id"])
    return success(serialize.superbill_out(superbill))


@bp.route("/superbills/<sid>/issue", methods=["POST"])
def issue_superbill(sid):
    user_id, role = get_auth()
    require_role(role, {"BillingAdmin"})
    superbill = get_or_404(db.superbills, sid)
    if superbill["status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "Superbill not in DRAFT")
    session_count, reimbursable = _compute_superbill(
        superbill["client_id"], superbill["period_start"], superbill["period_end"],
    )
    if session_count < 1:
        raise err(ERR_INVALID_STATE, "No completed session in window")
    superbill["session_count"] = session_count
    superbill["reimbursable_amount_cents"] = reimbursable
    superbill["status"] = "ISSUED"
    touch(superbill)
    return success(serialize.superbill_out(superbill))


@bp.route("/superbills/<sid>/void", methods=["POST"])
def void_superbill(sid):
    user_id, role = get_auth()
    require_role(role, {"BillingAdmin"})
    superbill = get_or_404(db.superbills, sid)
    if superbill["status"] != "ISSUED":
        raise err(ERR_INVALID_STATE, "Superbill not in ISSUED")
    superbill["status"] = "VOID"
    touch(superbill)
    return success(serialize.superbill_out(superbill))
