"""Routes: applications, screening reports, decisions, resubmit."""
from decimal import Decimal

from flask import Blueprint, g

import helpers as h
import domain as d
from state import S

bp = Blueprint("applications", __name__)

_CYCLES = {"WEEKLY", "MONTHLY"}
_BG = {"CLEAR", "FLAGGED", "FAILED"}


def _reports_for(app_id):
    return [r for r in S.screening_reports.values() if r["application_id"] == app_id]


def _latest_report(app_id):
    rows = _reports_for(app_id)
    if not rows:
        return None
    return max(rows, key=lambda r: (r["created_at"], r["sequence_number"]))


def _recompute_income(application):
    room = S.rooms[application["room_id"]]
    if application["billing_cycle"] == "MONTHLY":
        monthly_equiv = room["monthly_rate_cents"]
    else:
        monthly_equiv = h.round_half_up(Decimal(room["weekly_rate_cents"]) * 52 / 12)
    application["monthly_equivalent_cents"] = monthly_equiv
    application["required_income_cents"] = h.round_half_up(Decimal(monthly_equiv) * d.INCOME_MULTIPLE)


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------
@bp.post("/co-living/applications")
def create_application():
    h.authorize("Member", "CommunityManager")
    b = h.body()
    # Priority 4: ownership for Member
    if g.role == "Member" and b.get("member_id") != g.user_id:
        raise h.ApiError("ERR_NOT_RESOURCE_OWNER", "member_id must equal caller")
    # Priority 5: shape
    member_id = h.req_str(b, "member_id")
    room_id = h.req_str(b, "room_id")
    move_in = h.req_date(b, "requested_move_in_date")
    billing_cycle = h.req_enum(b, "billing_cycle", _CYCLES)
    # Priority 6: FK
    h.find_or_404(S.members, member_id, "ERR_MEMBER_NOT_FOUND")
    h.find_or_404(S.rooms, room_id, "ERR_ROOM_NOT_FOUND")
    app = h.new_common()
    app.update({
        "member_id": member_id,
        "room_id": room_id,
        "requested_move_in_date": b["requested_move_in_date"],
        "billing_cycle": billing_cycle,
        "status": "SUBMITTED",
        "cosigner_monthly_income_cents": None,
        "screening_round": 0,
        "monthly_equivalent_cents": 0,
        "required_income_cents": 0,
        "required_deposit_cents": 0,
        "decision_note": None,
    })
    S.applications[app["id"]] = app
    return h.ok(d.serialize(app), 201)


@bp.get("/co-living/applications/<aid>")
def get_application(aid):
    h.authorize(*h.ROLES)
    app = h.find_or_404(S.applications, aid, "ERR_APPLICATION_NOT_FOUND")
    return h.ok(d.serialize(app), 200)


@bp.get("/co-living/applications")
def list_applications():
    h.authorize(*h.ROLES)
    limit, offset = h.parse_pagination()
    member_id = h.query_val("member_id")
    room_id = h.query_val("room_id")
    status = h.query_val("status")
    rows = []
    for a in S.applications.values():
        if member_id is not None and a["member_id"] != member_id:
            continue
        if room_id is not None and a["room_id"] != room_id:
            continue
        if status is not None and a["status"] != status:
            continue
        rows.append(a)
    rows = h.sort_created(rows)
    page, pag = h.paginate(rows, limit, offset)
    return h.ok([d.serialize(x) for x in page], 200, "array", pag)


# ---------------------------------------------------------------------------
# Screening reports
# ---------------------------------------------------------------------------
@bp.post("/co-living/applications/<aid>/screening-reports")
def create_screening_report(aid):
    h.authorize("ComplianceOfficer")
    app = h.find_or_404(S.applications, aid, "ERR_APPLICATION_NOT_FOUND")
    b = h.body()
    background = h.req_enum(b, "background_result", _BG)
    verified = h.req_int_nonneg(b, "verified_monthly_income_cents")
    report_reference = h.req_str(b, "report_reference")
    # Priority 10: state
    if app["status"] != "SUBMITTED":
        raise h.ApiError("ERR_APPLICATION_NOT_PENDING", "application is not SUBMITTED")
    # Priority 29: round ceiling
    if app["screening_round"] >= d.MAX_APPLICATION_ROUNDS:
        raise h.ApiError("ERR_APPLICATION_ROUND_LIMIT", "screening round limit reached")
    report = h.new_ledger()
    report.update({
        "application_id": aid,
        "sequence_number": app["screening_round"] + 1,
        "background_result": background,
        "verified_monthly_income_cents": verified,
        "report_reference": report_reference,
        "submitted_by_user_id": g.user_id,
    })
    S.screening_reports[report["id"]] = report
    app["screening_round"] = len(_reports_for(aid))
    app["status"] = "SCREENED"
    _recompute_income(app)
    h.touch(app)
    return h.ok(d.serialize(report), 201)


@bp.get("/co-living/applications/<aid>/screening-reports")
def list_screening_reports(aid):
    h.authorize(*h.ROLES)
    h.find_or_404(S.applications, aid, "ERR_APPLICATION_NOT_FOUND")
    limit, offset = h.parse_pagination()
    rows = _reports_for(aid)
    rows = sorted(rows, key=lambda r: (r["created_at"], r["sequence_number"]))
    page, pag = h.paginate(rows, limit, offset)
    return h.ok([d.serialize(x) for x in page], 200, "array", pag)


# ---------------------------------------------------------------------------
# Decision
# ---------------------------------------------------------------------------
@bp.post("/co-living/applications/<aid>/decision")
def decide_application(aid):
    h.authorize("ComplianceOfficer")
    app = h.find_or_404(S.applications, aid, "ERR_APPLICATION_NOT_FOUND")
    b = h.body()
    decision = h.req_enum(b, "decision", {"APPROVE", "DENY"})
    note = h.opt_str(b, "decision_note")
    # Priority 10: state
    if app["status"] != "SCREENED":
        raise h.ApiError("ERR_APPLICATION_NOT_PENDING", "application is not SCREENED")
    # Priority 11: room availability
    room = S.rooms[app["room_id"]]
    if room["occupancy_state"] != "VACANT":
        raise h.ApiError("ERR_ROOM_NOT_AVAILABLE", "room is not VACANT")

    if decision == "DENY":
        app["status"] = "DENIED"
        app["required_deposit_cents"] = 0
        app["decision_note"] = note
        h.touch(app)
        return h.ok(d.serialize(app), 200)

    # decision == APPROVE
    latest = _latest_report(aid)
    # Priority 14: background safety
    if latest is not None and latest["background_result"] == "FAILED":
        raise h.ApiError("ERR_BACKGROUND_FAILED", "latest background result is FAILED")
    verified = latest["verified_monthly_income_cents"] if latest else 0
    cosigner = app["cosigner_monthly_income_cents"]
    qualifying = verified + (cosigner or 0)
    required = app["required_income_cents"]
    # Priority 31: income sufficiency once cosigner round consumed
    if qualifying < required and cosigner is not None:
        raise h.ApiError("ERR_INCOME_INSUFFICIENT", "income below the bar after cosigner round")

    weekly = Decimal(room["weekly_rate_cents"])
    if latest is not None and latest["background_result"] == "CLEAR" and qualifying >= required:
        app["status"] = "APPROVED"
        app["required_deposit_cents"] = h.round_half_up(weekly * d.DEPOSIT_MULTIPLE)
    else:
        app["status"] = "CONDITIONAL"
        app["required_deposit_cents"] = h.round_half_up(weekly * d.CONDITIONAL_DEPOSIT_MULTIPLE)
    app["decision_note"] = note
    h.touch(app)
    return h.ok(d.serialize(app), 200)


# ---------------------------------------------------------------------------
# Resubmit
# ---------------------------------------------------------------------------
@bp.post("/co-living/applications/<aid>/resubmit")
def resubmit_application(aid):
    h.authorize("Member")
    app = h.find_or_404(S.applications, aid, "ERR_APPLICATION_NOT_FOUND")
    # Priority 4: ownership
    if app["member_id"] != g.user_id:
        raise h.ApiError("ERR_NOT_RESOURCE_OWNER", "caller does not own the application")
    b = h.body()
    cosigner = h.opt_int_nonneg(b, "cosigner_monthly_income_cents")
    # Priority 10: state
    if app["status"] != "CONDITIONAL":
        raise h.ApiError("ERR_APPLICATION_NOT_PENDING", "application is not CONDITIONAL")
    # Priority 29: round ceiling
    if app["screening_round"] >= d.MAX_APPLICATION_ROUNDS:
        raise h.ApiError("ERR_APPLICATION_ROUND_LIMIT", "screening round limit reached")
    app["status"] = "SUBMITTED"
    if cosigner is not None:
        app["cosigner_monthly_income_cents"] = cosigner
    app["required_deposit_cents"] = 0
    h.touch(app)
    return h.ok(d.serialize(app), 200)
