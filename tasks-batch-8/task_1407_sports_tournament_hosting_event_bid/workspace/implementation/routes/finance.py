"""ImpactReport and Settlement endpoints (PRD §3.9)."""

from flask import Blueprint, request

import services as svc
from db import STORE, base_entity, touch
from errors import (ERR_BLOCK_NOT_RECONCILABLE, ERR_IMPACT_REPORT_NOT_ACCEPTED,
                    ERR_SETTLEMENT_EXISTS, ERR_SOD_VIOLATION, already_terminal,
                    invalid_state, posture_forbids, raise_err)
from listing import list_response
from middleware import (get_body, opt_str, req_enum, req_int, req_str,
                        require_any_authenticated, require_roles)
from response import ok

bp = Blueprint("finance", __name__, url_prefix="/api/v1")


# ---------------------------------------------------------------------------
# Impact reports
# ---------------------------------------------------------------------------

@bp.post("/events/<id>/impact-reports")
def create_report(id):
    uid, _role = require_roles("CommissionAdmin")
    e = svc.get_or_404(STORE.events, id, "event")
    data = get_body()
    projected_attendance = req_int(data, "projected_attendance", lo=0)
    notes = opt_str(data, "notes")
    if e["posture"] != "COMPLETED":
        posture_forbids("Impact reports may be created only once the event is COMPLETED.")
    r = base_entity()
    r.update({
        "event_id": e["id"],
        "status": "DRAFT",
        "projected_attendance": projected_attendance,
        "notes": notes,
        "projected_room_nights": None,
        "projected_direct_spend_cents": None,
        "actual_attendance": None,
        "actual_room_nights": None,
        "audited_direct_spend_cents": None,
        "created_by_user_id": uid,
        "audited_by_user_id": None,
        "revision_count": 0,
    })
    STORE.reports[r["id"]] = r
    return ok(svc.ser_report(r), status=201)


@bp.get("/events/<id>/impact-reports")
def list_reports(id):
    require_any_authenticated()
    e = svc.get_or_404(STORE.events, id, "event")
    items = svc.reports_of_event(e["id"])
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return list_response(items, svc.ser_report)


@bp.get("/impact-reports/<id>")
def get_report(id):
    require_any_authenticated()
    r = svc.get_or_404(STORE.reports, id, "impact report")
    return ok(svc.ser_report(r))


@bp.post("/impact-reports/<id>/submit")
def submit_report(id):
    require_roles("CommissionAdmin")
    r = svc.get_or_404(STORE.reports, id, "impact report")
    if r["status"] in svc.REPORT_TERMINAL:
        already_terminal("impact report")
    if r["status"] != "DRAFT":
        invalid_state("Only a DRAFT impact report can be submitted.")
    nights, spend = svc.impact_figures(r["event_id"], svc.PICKUP_FORWARD,
                                       r["projected_attendance"])
    r["projected_room_nights"] = nights
    r["projected_direct_spend_cents"] = spend
    r["status"] = "SUBMITTED"
    touch(r)
    return ok(svc.ser_report(r))


@bp.post("/impact-reports/<id>/audit")
def audit_report(id):
    uid, _role = require_roles("CvbAuditor")
    r = svc.get_or_404(STORE.reports, id, "impact report")
    data = get_body()
    actual_attendance = req_int(data, "actual_attendance", lo=0)
    if r["status"] in svc.REPORT_TERMINAL:
        already_terminal("impact report")
    if r["status"] != "SUBMITTED":
        invalid_state("Only a SUBMITTED impact report can be audited.")
    if uid == r["created_by_user_id"]:
        raise_err(ERR_SOD_VIOLATION, "An auditor may not audit a report they created.")
    nights, spend = svc.impact_figures(r["event_id"], svc.PICKUP_FINAL,
                                       actual_attendance)
    r["actual_attendance"] = actual_attendance
    r["actual_room_nights"] = nights
    r["audited_direct_spend_cents"] = spend
    r["audited_by_user_id"] = uid
    r["status"] = "UNDER_AUDIT"
    touch(r)
    return ok(svc.ser_report(r))


@bp.post("/impact-reports/<id>/audit-decision")
def audit_decision(id):
    require_roles("CvbAuditor")
    r = svc.get_or_404(STORE.reports, id, "impact report")
    data = get_body()
    decision = req_enum(data, "decision", {"ACCEPTED", "DISPUTED"})
    if r["status"] in svc.REPORT_TERMINAL:
        already_terminal("impact report")
    if r["status"] != "UNDER_AUDIT":
        invalid_state("Only an UNDER_AUDIT impact report can be decided.")
    r["status"] = decision
    touch(r)
    return ok(svc.ser_report(r))


@bp.post("/impact-reports/<id>/revise")
def revise_report(id):
    require_roles("CommissionAdmin")
    r = svc.get_or_404(STORE.reports, id, "impact report")
    if r["status"] in svc.REPORT_TERMINAL:
        already_terminal("impact report")
    if r["status"] != "DISPUTED":
        invalid_state("Only a DISPUTED impact report can be revised back to DRAFT.")
    r["status"] = "DRAFT"
    r["revision_count"] += 1
    touch(r)
    return ok(svc.ser_report(r))


# ---------------------------------------------------------------------------
# Settlements
# ---------------------------------------------------------------------------

@bp.post("/events/<id>/settlements")
def create_settlement(id):
    require_roles("CommissionAdmin")
    e = svc.get_or_404(STORE.events, id, "event")
    data = get_body()
    sponsor = req_int(data, "sponsor_contributions_cents", lo=0)
    if e["posture"] != "COMPLETED":
        posture_forbids("A settlement may be created only once the event is COMPLETED.")
    if svc.settlements_of_event(e["id"]):
        raise_err(ERR_SETTLEMENT_EXISTS, "The event already has a settlement.")
    s = base_entity()
    s.update({
        "event_id": e["id"],
        "status": "OPEN",
        "sponsor_contributions_cents": sponsor,
        "expense_lines": [],
        "registration_revenue_cents": None,
        "rebate_total_cents": None,
        "sanction_fee_cents": None,
        "venue_rental_total_cents": None,
        "officials_stipend_total_cents": None,
        "expense_total_cents": 0,
        "gross_revenue_cents": None,
        "net_to_commission_cents": None,
        "certified_by_user_id": None,
        "approved_by_user_id": None,
    })
    STORE.settlements[s["id"]] = s
    return ok(svc.ser_settlement(s), status=201)


@bp.get("/events/<id>/settlements")
def list_settlements(id):
    require_any_authenticated()
    e = svc.get_or_404(STORE.events, id, "event")
    items = svc.settlements_of_event(e["id"])
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    items.sort(key=lambda s: (s["created_at"], s["_seq"]))
    return list_response(items, svc.ser_settlement)


@bp.get("/settlements/<id>")
def get_settlement(id):
    require_any_authenticated()
    s = svc.get_or_404(STORE.settlements, id, "settlement")
    return ok(svc.ser_settlement(s))


@bp.post("/settlements/<id>/expense-lines")
def add_expense_line(id):
    require_roles("CommissionAdmin")
    s = svc.get_or_404(STORE.settlements, id, "settlement")
    data = get_body()
    category = req_str(data, "category")
    amount = req_int(data, "amount_cents", lo=0)
    description = req_str(data, "description")
    if s["status"] in svc.SETTLEMENT_TERMINAL:
        already_terminal("settlement")
    if s["status"] != "OPEN":
        invalid_state("Expense lines are editable only while the settlement is OPEN.")
    s["expense_lines"].append({
        "category": category,
        "amount_cents": amount,
        "description": description,
    })
    s["expense_total_cents"] = sum(l["amount_cents"] for l in s["expense_lines"])
    touch(s)
    return ok(svc.ser_settlement(s))


@bp.post("/settlements/<id>/certify")
def certify_settlement(id):
    uid, _role = require_roles("CommissionAdmin")
    s = svc.get_or_404(STORE.settlements, id, "settlement")
    if s["status"] in svc.SETTLEMENT_TERMINAL:
        already_terminal("settlement")
    if s["status"] != "OPEN":
        invalid_state("Only an OPEN settlement can be certified.")
    for b in svc.blocks_of_event(s["event_id"]):
        if b["status"] not in ("RECONCILED", "SETTLED", "RELEASED"):
            raise_err(ERR_BLOCK_NOT_RECONCILABLE,
                  "All hotel blocks must be RECONCILED, SETTLED, or RELEASED before certification.")
    eid = s["event_id"]
    reg_rev = svc.registration_revenue_cents(eid)
    rebate_total = sum(b["final_rebate_cents"] or 0
                       for b in svc.blocks_of_event(eid)
                       if b["status"] in ("RECONCILED", "SETTLED"))
    fee = svc.sanction_fee_cents(reg_rev)
    rental = sum(v["rental_fee_cents"] for v in svc.venues_of_event(eid)
                 if v["status"] in ("CONTRACTED", "RELEASED"))
    stipends = svc.officials_stipend_total_cents(eid)
    expenses = sum(l["amount_cents"] for l in s["expense_lines"])
    gross = reg_rev + rebate_total + s["sponsor_contributions_cents"]
    net = gross - fee - rental - stipends - expenses
    s["registration_revenue_cents"] = reg_rev
    s["rebate_total_cents"] = rebate_total
    s["sanction_fee_cents"] = fee
    s["venue_rental_total_cents"] = rental
    s["officials_stipend_total_cents"] = stipends
    s["expense_total_cents"] = expenses
    s["gross_revenue_cents"] = gross
    s["net_to_commission_cents"] = net
    s["certified_by_user_id"] = uid
    s["status"] = "EXPENSES_CERTIFIED"
    touch(s)
    return ok(svc.ser_settlement(s))


@bp.post("/settlements/<id>/approve")
def approve_settlement(id):
    uid, _role = require_roles("CommissionAdmin")
    s = svc.get_or_404(STORE.settlements, id, "settlement")
    if s["status"] in svc.SETTLEMENT_TERMINAL:
        already_terminal("settlement")
    if s["status"] != "EXPENSES_CERTIFIED":
        invalid_state("Only an EXPENSES_CERTIFIED settlement can be approved.")
    if uid == s["certified_by_user_id"]:
        raise_err(ERR_SOD_VIOLATION, "The approver must differ from the certifier.")
    if not any(r["status"] == "ACCEPTED" for r in svc.reports_of_event(s["event_id"])):
        raise_err(ERR_IMPACT_REPORT_NOT_ACCEPTED,
                  "An ACCEPTED impact report is required before approval.")
    s["approved_by_user_id"] = uid
    s["status"] = "APPROVED"
    touch(s)
    return ok(svc.ser_settlement(s))


@bp.post("/settlements/<id>/pay")
def pay_settlement(id):
    require_roles("CommissionAdmin")
    s = svc.get_or_404(STORE.settlements, id, "settlement")
    if s["status"] in svc.SETTLEMENT_TERMINAL:
        already_terminal("settlement")
    if s["status"] != "APPROVED":
        invalid_state("Only an APPROVED settlement can be paid.")
    s["status"] = "PAID"
    touch(s)
    # Cascade: event COMPLETED -> SETTLED; RECONCILED blocks -> SETTLED.
    e = STORE.events.get(s["event_id"])
    if e is not None and e["posture"] == "COMPLETED":
        for b in svc.blocks_of_event(e["id"]):
            if b["status"] == "RECONCILED":
                b["status"] = "SETTLED"
                touch(b)
        e["posture"] = "SETTLED"
        touch(e)
    return ok(svc.ser_settlement(s))


@bp.post("/settlements/<id>/dispute")
def dispute_settlement(id):
    require_roles("CommissionAdmin", "CvbAuditor")
    s = svc.get_or_404(STORE.settlements, id, "settlement")
    data = get_body()
    req_str(data, "dispute_reason")
    if s["status"] in svc.SETTLEMENT_TERMINAL:
        already_terminal("settlement")
    if s["status"] != "EXPENSES_CERTIFIED":
        invalid_state("Only an EXPENSES_CERTIFIED settlement can be disputed.")
    s["status"] = "DISPUTED"
    touch(s)
    return ok(svc.ser_settlement(s))


@bp.post("/settlements/<id>/reopen")
def reopen_settlement(id):
    require_roles("CommissionAdmin")
    s = svc.get_or_404(STORE.settlements, id, "settlement")
    if s["status"] in svc.SETTLEMENT_TERMINAL:
        already_terminal("settlement")
    if s["status"] != "DISPUTED":
        invalid_state("Only a DISPUTED settlement can be reopened.")
    s["status"] = "OPEN"
    s["certified_by_user_id"] = None
    touch(s)
    return ok(svc.ser_settlement(s))
