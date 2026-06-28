"""Standalone resource GET endpoints: billing-cycles, session-credits."""
from flask import Blueprint, request

from db import db
from middleware import get_auth, require_role
from lookup import get_or_404, check_client_owner, check_therapist_owner, paginate
import serialize
from response import success, list_success

bp = Blueprint("resources", __name__)


@bp.route("/billing-cycles/<bid>", methods=["GET"])
def get_billing_cycle(bid):
    user_id, role = get_auth()
    require_role(role, {"Client", "BillingAdmin"})
    cycle = get_or_404(db.billing_cycles, bid)
    sub = db.subscriptions.get(cycle["subscription_id"])
    if sub:
        check_client_owner(role, user_id, sub["client_id"])
    return success(serialize.billing_cycle_out(cycle))


@bp.route("/billing-cycles/<bid>/session-credits", methods=["GET"])
def list_cycle_credits(bid):
    user_id, role = get_auth()
    require_role(role, {"Client", "BillingAdmin"})
    cycle = get_or_404(db.billing_cycles, bid)
    sub = db.subscriptions.get(cycle["subscription_id"])
    if sub:
        check_client_owner(role, user_id, sub["client_id"])
    items = [c for c in db.session_credits.values() if c["billing_cycle_id"] == bid]
    items.sort(key=lambda c: (c["created_at"], c["_seq"]))
    page, lim, off, total = paginate(items, request.args)
    return list_success([serialize.session_credit_out(c) for c in page], lim, off, total)


@bp.route("/session-credits/<scid>", methods=["GET"])
def get_session_credit(scid):
    user_id, role = get_auth()
    require_role(role, {"Client", "ClinicalAdmin", "BillingAdmin"})
    credit = get_or_404(db.session_credits, scid)
    check_client_owner(role, user_id, credit["client_id"])
    return success(serialize.session_credit_out(credit))


@bp.route("/session-credits/<scid>/live-sessions", methods=["GET"])
def list_credit_session(scid):
    user_id, role = get_auth()
    require_role(role, {"Client", "Therapist", "ClinicalAdmin", "BillingAdmin"})
    credit = get_or_404(db.session_credits, scid)
    check_client_owner(role, user_id, credit["client_id"])
    items = []
    lsid = credit.get("live_session_id")
    if lsid and lsid in db.live_sessions:
        session = db.live_sessions[lsid]
        match = db.matches.get(session["match_id"])
        if match:
            check_therapist_owner(role, user_id, match["therapist_id"])
        items = [session]
    page, lim, off, total = paginate(items, request.args)
    return list_success([serialize.live_session_out(s) for s in page], lim, off, total)
