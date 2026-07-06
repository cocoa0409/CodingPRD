from flask import Blueprint, request
from db import db
from middleware import require_user_context, require_role
from response import object_response, array_response
from services.common import (stamp_new, public, get_json_body, require_str,
                             require_int, require_enum, paginate, sorted_by_creation)
from services.lookup import get_or_404
from services.calc import recompute_grant, round_half_up
from errors import err

bp = Blueprint("sponsors", __name__)

SPONSOR_TYPES = {"EMPLOYER", "GRANT"}


def _sponsor_view_guard(sponsor, user_id, role):
    """SponsorViewer may only access if X-User-ID == sponsor.viewer_user_id."""
    if role == "SponsorViewer" and user_id != sponsor.get("viewer_user_id"):
        raise err("ERR_INSUFFICIENT_PERMISSIONS", "Not the sponsor's viewer")


# ---------------- Sponsors ----------------

@bp.route("/sponsors", methods=["POST"])
def create_sponsor():
    _, role = require_user_context()
    require_role(role, {"ProgramManager"})
    body = get_json_body()
    name = require_str(body, "name")
    sponsor_type = require_enum(body, "sponsor_type", SPONSOR_TYPES)
    viewer_user_id = require_str(body, "viewer_user_id")
    sponsor = stamp_new({
        "name": name, "sponsor_type": sponsor_type,
        "viewer_user_id": viewer_user_id,
    })
    db.sponsors[sponsor["id"]] = sponsor
    return object_response(public(sponsor), 201)


@bp.route("/sponsors", methods=["GET"])
def list_sponsors():
    _, role = require_user_context()
    require_role(role, {"ProgramManager", "BillingClerk"})
    items = list(db.sponsors.values())
    st = request.args.get("sponsor_type")
    if st is not None:
        items = [s for s in items if s["sponsor_type"] == st]
    items = sorted_by_creation(items)
    page, limit, offset, total = paginate(items)
    return array_response([public(s) for s in page], limit, offset, total)


@bp.route("/sponsors/<rid>", methods=["GET"])
def get_sponsor(rid):
    user_id, role = require_user_context()
    require_role(role, {"ProgramManager", "BillingClerk", "SponsorViewer"})
    sponsor = get_or_404("sponsors", rid)
    _sponsor_view_guard(sponsor, user_id, role)
    return object_response(public(sponsor), 200)


@bp.route("/sponsors/<rid>/report", methods=["GET"])
def sponsor_report(rid):
    user_id, role = require_user_context()
    require_role(role, {"ProgramManager", "SponsorViewer"})
    sponsor = get_or_404("sponsors", rid)
    _sponsor_view_guard(sponsor, user_id, role)
    return object_response(_compute_report(sponsor), 200)


def _compute_report(sponsor):
    sponsor_id = sponsor["id"]
    event_ids = {e["id"] for e in db.events.values() if e["sponsor_id"] == sponsor_id}
    events = [e for e in db.events.values() if e["id"] in event_ids]
    appts = [a for a in db.appointments.values() if a["event_id"] in event_ids]

    events_published = sum(1 for e in events if e["status"] in ("PUBLISHED", "CLOSED"))
    total_screened = sum(1 for a in appts if a["status"] in ("SCREENED", "RESULT_READY", "CLOSED"))
    abnormal_count = sum(1 for a in appts
                         if a["status"] in ("RESULT_READY", "CLOSED") and a.get("result") == "ABNORMAL")
    abnormal_rate_pct = round_half_up((abnormal_count / total_screened) * 100) if total_screened > 0 else 0

    appt_ids = {a["id"] for a in appts}
    charges = [c for c in db.charges.values() if c["appointment_id"] in appt_ids]
    grant_settled_cents = sum(c.get("grant_covered_cents") or 0
                              for c in charges if c["status"] == "SETTLED" and c.get("grant_id"))
    patient_paid_cents = sum(c.get("final_patient_responsibility_cents") or 0
                             for c in charges if c["status"] == "SETTLED" and not c.get("grant_id"))
    realized_cost_cents = grant_settled_cents + patient_paid_cents

    referrals = [r for r in db.referrals.values() if r["appointment_id"] in appt_ids]
    referrals_total = len(referrals)
    referrals_resolved = sum(1 for r in referrals if r["status"] == "RESOLVED")
    resolution_rate_pct = round_half_up((referrals_resolved / referrals_total) * 100) if referrals_total > 0 else 0

    return {
        "events_published": events_published,
        "total_screened": total_screened,
        "abnormal_count": abnormal_count,
        "abnormal_rate_pct": abnormal_rate_pct,
        "grant_settled_cents": grant_settled_cents,
        "patient_paid_cents": patient_paid_cents,
        "realized_cost_cents": realized_cost_cents,
        "referrals_total": referrals_total,
        "referrals_resolved": referrals_resolved,
        "resolution_rate_pct": resolution_rate_pct,
    }


# ---------------- Grants ----------------

@bp.route("/grants", methods=["POST"])
def create_grant():
    _, role = require_user_context()
    require_role(role, {"ProgramManager"})
    body = get_json_body()
    sponsor_id = require_str(body, "sponsor_id")
    name = require_str(body, "name")
    total_budget_cents = require_int(body, "total_budget_cents", minimum=0)
    # FK existence (priority 4)
    get_or_404("sponsors", sponsor_id)
    grant = stamp_new({
        "sponsor_id": sponsor_id, "name": name,
        "total_budget_cents": total_budget_cents,
        "committed_cents": 0, "settled_cents": 0,
        "remaining_cents": total_budget_cents, "is_depleted": False,
    })
    db.grants[grant["id"]] = grant
    return object_response(public(grant), 201)


@bp.route("/grants", methods=["GET"])
def list_grants():
    _, role = require_user_context()
    require_role(role, {"ProgramManager", "BillingClerk"})
    items = list(db.grants.values())
    sid = request.args.get("sponsor_id")
    if sid is not None:
        items = [g for g in items if g["sponsor_id"] == sid]
    items = sorted_by_creation(items)
    page, limit, offset, total = paginate(items)
    return array_response([public(recompute_grant(g)) for g in page], limit, offset, total)


@bp.route("/grants/<rid>", methods=["GET"])
def get_grant(rid):
    user_id, role = require_user_context()
    require_role(role, {"ProgramManager", "BillingClerk", "SponsorViewer"})
    grant = get_or_404("grants", rid)
    if role == "SponsorViewer":
        sponsor = db.sponsors.get(grant["sponsor_id"])
        if not sponsor or user_id != sponsor.get("viewer_user_id"):
            raise err("ERR_INSUFFICIENT_PERMISSIONS", "Not the sponsor's viewer")
    recompute_grant(grant)
    return object_response(public(grant), 200)
