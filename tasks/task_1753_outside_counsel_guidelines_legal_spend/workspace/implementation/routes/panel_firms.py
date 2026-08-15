"""PanelFirm endpoints including suspend/reinstate/offboard cascades."""

from flask import Blueprint, request

import db
import errors
import helpers
import response as resp
from middleware import require_auth, ROLE_LEGAL_OPS, ROLE_FIRM_USER
from services import invoice_service

bp = Blueprint("panel_firms", __name__)


@bp.route("/legal-departments/<deptId>/panel-firms", methods=["POST"])
def create_firm(deptId):
    require_auth([ROLE_LEGAL_OPS])
    dept = helpers.resolve_department(deptId)
    body = helpers.get_body()
    helpers.require_fields(body, ["firm_name"])
    rec = db.base_resource({
        "legal_department_id": deptId,
        "firm_name": body["firm_name"],
        "status": "ACTIVE",
        "scorecard_overall_pct": None,
    })
    db.panel_firms[rec["id"]] = rec
    return resp.success_object(resp.public(rec), 201)


@bp.route("/legal-departments/<deptId>/panel-firms/<firmId>", methods=["GET"])
def get_firm(deptId, firmId):
    require_auth([ROLE_LEGAL_OPS, ROLE_FIRM_USER])
    _, firm = helpers.resolve_firm(deptId, firmId)
    return resp.success_object(resp.public(firm))


@bp.route("/legal-departments/<deptId>/panel-firms", methods=["GET"])
def list_firms(deptId):
    require_auth([ROLE_LEGAL_OPS, ROLE_FIRM_USER])
    helpers.resolve_department(deptId)
    limit, offset = resp.parse_pagination(request.args)
    records = [f for f in db.panel_firms.values() if f.get("legal_department_id") == deptId]
    records = helpers.apply_filters(records, request.args, ["status"])
    items, total = resp.paginate(records, limit, offset)
    return resp.success_list(items, limit, offset, total)


def _open_appeals_of_firm(firm_id):
    """All appeals on line items of invoices belonging to this firm that are
    SUBMITTED or UNDER_REVIEW."""
    firm_invoice_ids = {
        inv["id"] for inv in db.invoices.values() if inv.get("panel_firm_id") == firm_id
    }
    firm_line_ids = {
        l["id"] for l in db.invoice_line_items.values() if l.get("invoice_id") in firm_invoice_ids
    }
    return [
        a for a in db.appeals.values()
        if a.get("invoice_line_item_id") in firm_line_ids
        and a.get("status") in ("SUBMITTED", "UNDER_REVIEW")
    ]


def _deny_appeal_cascade(appeal, resolution_note):
    """Standard DENIED cascade: appeal -> line REJECTED->UPHELD -> invoice recompute."""
    appeal["status"] = "DENIED"
    appeal["resolution_note"] = resolution_note
    db.touch(appeal)
    line = db.invoice_line_items.get(appeal.get("invoice_line_item_id"))
    if line is not None and line.get("review_status") == "REJECTED":
        line["review_status"] = "UPHELD"
        db.touch(line)
        inv = db.invoices.get(line.get("invoice_id"))
        if inv is not None:
            matter = db.matters.get(inv.get("matter_id"))
            if matter is not None:
                invoice_service.finalize_invoice_state(inv, matter, inv.get("status"))
            db.touch(inv)


@bp.route("/legal-departments/<deptId>/panel-firms/<firmId>/suspend", methods=["POST"])
def suspend_firm(deptId, firmId):
    require_auth([ROLE_LEGAL_OPS])
    _, firm = helpers.resolve_firm(deptId, firmId)
    if firm.get("status") != "ACTIVE":
        raise errors.invalid_state()
    # Cascade hop 1: auto-deny open appeals of this firm.
    for appeal in _open_appeals_of_firm(firmId):
        _deny_appeal_cascade(appeal, "AUTO_DENIED_FIRM_SUSPENDED")
    firm["status"] = "SUSPENDED"
    db.touch(firm)
    return resp.success_object(resp.public(firm))


@bp.route("/legal-departments/<deptId>/panel-firms/<firmId>/reinstate", methods=["POST"])
def reinstate_firm(deptId, firmId):
    require_auth([ROLE_LEGAL_OPS])
    _, firm = helpers.resolve_firm(deptId, firmId)
    if firm.get("status") != "SUSPENDED":
        raise errors.invalid_state()
    firm["status"] = "ACTIVE"
    db.touch(firm)
    return resp.success_object(resp.public(firm))


@bp.route("/legal-departments/<deptId>/panel-firms/<firmId>/offboard", methods=["POST"])
def offboard_firm(deptId, firmId):
    require_auth([ROLE_LEGAL_OPS])
    _, firm = helpers.resolve_firm(deptId, firmId)
    if firm.get("status") != "SUSPENDED":
        raise errors.invalid_state()
    # Precondition: no invoice under any matter engaged to this firm in
    # SUBMITTED or UNDER_REVIEW.
    firm_matter_ids = {
        m["id"] for m in db.matters.values() if m.get("panel_firm_id") == firmId
    }
    for inv in db.invoices.values():
        if inv.get("matter_id") in firm_matter_ids and inv.get("status") in ("SUBMITTED", "UNDER_REVIEW"):
            raise errors.firm_has_open_invoices()
    # Cascade: close ENGAGED matters, disqualify PENDING timekeepers,
    # reject DRAFT/SUBMITTED rate cards.
    for m in db.matters.values():
        if m.get("panel_firm_id") == firmId and m.get("engagement_status") == "ENGAGED":
            m["engagement_status"] = "CLOSED"
            db.touch(m)
    for tk in db.timekeepers.values():
        if tk.get("panel_firm_id") == firmId and tk.get("qualification_status") == "PENDING":
            tk["qualification_status"] = "DISQUALIFIED"
            db.touch(tk)
    for card in db.rate_cards.values():
        if card.get("panel_firm_id") == firmId and card.get("status") in ("DRAFT", "SUBMITTED"):
            card["status"] = "REJECTED"
            db.touch(card)
    firm["status"] = "OFFBOARDED"
    db.touch(firm)
    return resp.success_object(resp.public(firm))
