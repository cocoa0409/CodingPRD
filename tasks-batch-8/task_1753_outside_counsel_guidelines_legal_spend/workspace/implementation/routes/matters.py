"""Matter endpoints including engage/close/reopen and staffing-ratio advisory."""

from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

import db
import errors
import helpers
import response as resp
from middleware import require_auth, ROLE_LEGAL_OPS, ROLE_FIRM_USER
from services import invoice_service

bp = Blueprint("matters", __name__)


@bp.route("/legal-departments/<deptId>/matters", methods=["POST"])
def create_matter(deptId):
    require_auth([ROLE_LEGAL_OPS])
    helpers.resolve_department(deptId)
    body = helpers.get_body()
    helpers.require_fields(body, ["panel_firm_id", "title", "budget_cents"])
    firm = db.panel_firms.get(body["panel_firm_id"])
    if firm is None or firm.get("legal_department_id") != deptId:
        raise errors.referential_integrity("panel_firm_id does not resolve within this department")
    rec = db.base_resource({
        "legal_department_id": deptId,
        "panel_firm_id": body["panel_firm_id"],
        "title": body["title"],
        "engagement_status": "PENDING",
        "budget_cents": int(body["budget_cents"]),
        "billed_to_date_cents": 0,
        "accrual_outstanding_cents": 0,
    })
    db.matters[rec["id"]] = rec
    return resp.success_object(resp.public(rec), 201)


@bp.route("/legal-departments/<deptId>/matters/<matterId>", methods=["GET"])
def get_matter(deptId, matterId):
    require_auth([ROLE_LEGAL_OPS, ROLE_FIRM_USER])
    _, matter = helpers.resolve_matter(deptId, matterId)
    return resp.success_object(resp.public(matter))


@bp.route("/legal-departments/<deptId>/matters", methods=["GET"])
def list_matters(deptId):
    require_auth([ROLE_LEGAL_OPS, ROLE_FIRM_USER])
    helpers.resolve_department(deptId)
    limit, offset = resp.parse_pagination(request.args)
    records = [m for m in db.matters.values() if m.get("legal_department_id") == deptId]
    records = helpers.apply_filters(records, request.args, ["engagement_status", "panel_firm_id"])
    items, total = resp.paginate(records, limit, offset)
    return resp.success_list(items, limit, offset, total)


@bp.route("/legal-departments/<deptId>/matters/<matterId>/engage", methods=["POST"])
def engage_matter(deptId, matterId):
    user_id, _ = require_auth([ROLE_FIRM_USER])
    dept, matter = helpers.resolve_matter(deptId, matterId)
    if matter.get("engagement_status") != "PENDING":
        raise errors.invalid_state()
    if user_id != matter.get("panel_firm_id"):
        raise errors.firm_mismatch()
    firm = db.panel_firms.get(matter.get("panel_firm_id"))
    if firm is None or firm.get("status") != "ACTIVE":
        raise errors.firm_not_active()
    # If a PUBLISHED guideline version exists for this department, the firm
    # must hold an ACKNOWLEDGED acknowledgment for it.
    published = [
        g for g in db.guideline_versions.values()
        if g.get("legal_department_id") == deptId and g.get("status") == "PUBLISHED"
    ]
    if published:
        current = max(published, key=lambda g: db.parse_iso(g.get("effective_date")) or db.get_clock())
        acked = any(
            a for a in db.guideline_acknowledgments.values()
            if a.get("panel_firm_id") == firm["id"]
            and a.get("guideline_version_id") == current["id"]
            and a.get("status") == "ACKNOWLEDGED"
        )
        if not acked:
            raise errors.ack_outstanding()
    matter["engagement_status"] = "ENGAGED"
    db.touch(matter)
    return resp.success_object(resp.public(matter))


def _matter_open_invoices(matter_id):
    return [
        inv for inv in db.invoices.values()
        if inv.get("matter_id") == matter_id and inv.get("status") in ("SUBMITTED", "UNDER_REVIEW")
    ]


def _matter_open_appeals(matter_id):
    inv_ids = {inv["id"] for inv in db.invoices.values() if inv.get("matter_id") == matter_id}
    line_ids = {l["id"] for l in db.invoice_line_items.values() if l.get("invoice_id") in inv_ids}
    return [
        a for a in db.appeals.values()
        if a.get("invoice_line_item_id") in line_ids and a.get("status") in ("SUBMITTED", "UNDER_REVIEW")
    ]


@bp.route("/legal-departments/<deptId>/matters/<matterId>/close", methods=["POST"])
def close_matter(deptId, matterId):
    require_auth([ROLE_LEGAL_OPS])
    _, matter = helpers.resolve_matter(deptId, matterId)
    if matter.get("engagement_status") != "ENGAGED":
        raise errors.invalid_state()
    if _matter_open_invoices(matterId):
        raise errors.matter_has_open_invoices()
    if _matter_open_appeals(matterId):
        raise errors.matter_has_open_appeals()
    matter["engagement_status"] = "CLOSED"
    db.touch(matter)
    return resp.success_object(resp.public(matter))


@bp.route("/legal-departments/<deptId>/matters/<matterId>/reopen", methods=["POST"])
def reopen_matter(deptId, matterId):
    require_auth([ROLE_LEGAL_OPS])
    _, matter = helpers.resolve_matter(deptId, matterId)
    if matter.get("engagement_status") != "CLOSED":
        raise errors.invalid_state()
    firm = db.panel_firms.get(matter.get("panel_firm_id"))
    if firm is None or firm.get("status") != "ACTIVE":
        raise errors.firm_not_active()
    matter["engagement_status"] = "ENGAGED"
    db.touch(matter)
    return resp.success_object(resp.public(matter))


@bp.route("/legal-departments/<deptId>/matters/<matterId>/staffing-ratio", methods=["GET"])
def staffing_ratio(deptId, matterId):
    require_auth([ROLE_LEGAL_OPS, ROLE_FIRM_USER])
    dept, matter = helpers.resolve_matter(deptId, matterId)
    basis = (request.args.get("basis") or "BILLED_HOURS").upper()

    if basis == "HEADCOUNT":
        firm_tks = [
            t for t in db.timekeepers.values()
            if t.get("panel_firm_id") == matter.get("panel_firm_id")
            and t.get("qualification_status") == "QUALIFIED"
        ]
        total = len(firm_tks)
        partners = sum(1 for t in firm_tks if t.get("tk_class") == "PARTNER")
        if total == 0:
            ratio = None
        else:
            ratio = (Decimal(partners) / Decimal(total) * Decimal("100")).quantize(
                Decimal("0.0001"), rounding=ROUND_HALF_UP
            )
    else:
        ratio = invoice_service.billed_hours_ratio(matterId)

    if ratio is None:
        compliant = True
        pct_out = None
    else:
        pct_out = float(ratio)
        min_pct = Decimal(str(dept.get("partner_ratio_min_pct", 0)))
        max_pct = Decimal(str(dept.get("partner_ratio_max_pct", 0)))
        # Strict violation outside the band; exactly at min or max is compliant.
        compliant = not (ratio < min_pct or ratio > max_pct)

    return resp.success_object({
        "partner_share_pct": pct_out,
        "basis": basis,
        "compliant": compliant,
    })
