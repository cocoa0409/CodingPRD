"""ReimbursementForm endpoints (form, items, submit, approve, reject)."""

from __future__ import annotations

from decimal import Decimal

from flask import Blueprint, g, request

from db import STORE
from errors import (
    APIError, ERR_FORBIDDEN, ERR_INVALID_STATE, ERR_NOT_CURRENT_APPROVER, ERR_NOT_FOUND,
    ERR_REFERENCE_INVALID, ERR_VALIDATION,
    ERR_INVOICE_NOT_VERIFIED, ERR_INVOICE_NOT_MATCHED, ERR_INVOICE_ALREADY_ATTACHED,
    ERR_GM_APPROVAL_REQUIRED,
)
from middleware import require_auth
from response import success, empty_204
from serializers import (
    reimbursement_form as ser_form,
    reimbursement_item as ser_item,
)
from services.audit import write_approval_record
from services.reimbursement import recompute_totals, recompute_totals_simple_sum
from services.travel_application import bump
from services.validate import (
    require_body, get_str, get_enum, get_bool, get_money, get_int,
)
from utils import CLOCK, new_uuid, parse_ts


bp = Blueprint("reimbursement_forms", __name__)


ITEM_CATEGORIES = {"LODGING", "PER_DIEM", "TRANSPORTATION", "OTHER"}


def _load_form_or_404(fid):
    row = STORE.reimbursement_forms.get(fid)
    if not row:
        raise APIError(ERR_NOT_FOUND, f"ReimbursementForm {fid} not found", 404)
    return row


def _ownership_or_forbid(form):
    if g.role == "Applicant" and form["applicant_id"] != g.user_id:
        raise APIError(ERR_FORBIDDEN, "Applicant is not the owner of this form", 403)


# ===================== Create draft =====================
@bp.route("/reimbursement-forms", methods=["POST"])
@require_auth(["Applicant"])
def create_form():
    body = require_body(request.get_json(silent=True))
    app_id = get_str(body, "application_id")
    app = STORE.travel_applications.get(app_id)
    if not app:
        raise APIError(ERR_REFERENCE_INVALID, "application_id not found", 422)
    if app["applicant_id"] != g.user_id:
        raise APIError(ERR_FORBIDDEN, "Applicant must own the parent application", 403)

    now = CLOCK.now_iso()
    fid = new_uuid()
    row = {
        "id": fid,
        "application_id": app_id,
        "applicant_id": app["applicant_id"],
        "status": "DRAFT",
        "total_claimed": Decimal("0.00"),
        "total_reimbursable": Decimal("0.00"),
        "total_self_paid": Decimal("0.00"),
        "requires_special_approval": False,
        "special_approval_granted": False,
        "correction_round": 0,
        "rejection_reason": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    STORE.reimbursement_forms[fid] = row
    return success(ser_form(row), status=201)


@bp.route("/reimbursement-forms/<fid>", methods=["GET"])
@require_auth(["Applicant", "Supervisor", "DeptHead", "Finance", "GeneralManager", "Admin"])
def get_form(fid):
    form = _load_form_or_404(fid)
    return success(ser_form(form))


# ===================== Add item =====================
@bp.route("/reimbursement-forms/<fid>/items", methods=["POST"])
@require_auth(["Applicant"])
def add_item(fid):
    form = _load_form_or_404(fid)
    _ownership_or_forbid(form)
    if form["status"] != "DRAFT":
        raise APIError(ERR_INVALID_STATE, "Form is not in DRAFT", 409)
    body = require_body(request.get_json(silent=True))
    invoice_id = get_str(body, "invoice_id")
    category = get_enum(body, "category", ITEM_CATEGORIES)
    covered_days = get_int(body, "covered_days", min_value=0)
    claimed_amount = get_money(body, "claimed_amount", non_negative=True)
    matched_segment_id = body.get("matched_segment_id")
    if matched_segment_id is not None and not isinstance(matched_segment_id, str):
        raise APIError(ERR_VALIDATION, "matched_segment_id must be a string", 422)

    # FK: invoice exists
    inv = STORE.invoices.get(invoice_id)
    if not inv:
        raise APIError(ERR_REFERENCE_INVALID, "invoice_id not found", 422)
    # Ownership: invoice must belong to the form's applicant
    if inv["applicant_id"] != form["applicant_id"]:
        raise APIError(ERR_REFERENCE_INVALID,
                        "invoice does not belong to the form's applicant", 422)

    # matched_segment_id reference (if provided): must belong to same application
    app = STORE.travel_applications.get(form["application_id"])
    seg = None
    if matched_segment_id is not None:
        seg = STORE.itinerary_segments.get(matched_segment_id)
        if seg is None or seg["application_id"] != form["application_id"]:
            raise APIError(ERR_REFERENCE_INVALID,
                            "matched_segment_id not under same application", 422)

    # Priority 12: invoice <-> segment matching for LODGING/TRANSPORTATION
    if category in {"LODGING", "TRANSPORTATION"}:
        if not matched_segment_id:
            raise APIError(ERR_INVOICE_NOT_MATCHED,
                            "matched_segment_id required for LODGING/TRANSPORTATION", 422)
        if seg["status"] != "ACTIVE":
            raise APIError(ERR_INVOICE_NOT_MATCHED, "Matched segment must be ACTIVE", 422)
        # category <-> segment_type compatibility
        if category == "LODGING" and seg["segment_type"] != "HOTEL":
            raise APIError(ERR_INVOICE_NOT_MATCHED,
                            "LODGING item must match a HOTEL segment", 422)
        if category == "TRANSPORTATION" and seg["segment_type"] not in {"FLIGHT", "TRAIN", "CAR"}:
            raise APIError(ERR_INVOICE_NOT_MATCHED,
                            "TRANSPORTATION item must match a FLIGHT/TRAIN/CAR segment", 422)
        # invoice_date within [start_at, end_at]
        inv_date = parse_ts(inv.get("invoice_date"))
        if inv_date is None or inv_date is False:
            raise APIError(ERR_INVOICE_NOT_MATCHED, "Invoice has no usable invoice_date", 422)
        s_at = parse_ts(seg["start_at"])
        e_at = parse_ts(seg["end_at"])
        if inv_date < s_at or inv_date > e_at:
            raise APIError(ERR_INVOICE_NOT_MATCHED,
                            "invoice_date not within segment window", 422)

    # Priority 13: invoice must be in TAX_VERIFIED
    if inv["ocr_status"] == "ATTACHED":
        raise APIError(ERR_INVOICE_ALREADY_ATTACHED,
                        "Invoice is already attached elsewhere", 409)
    if inv["ocr_status"] != "TAX_VERIFIED":
        raise APIError(ERR_INVOICE_NOT_VERIFIED,
                        "Invoice must be in TAX_VERIFIED to attach", 422)

    # Insert item
    now = CLOCK.now_iso()
    item_id = new_uuid()
    item = {
        "id": item_id,
        "form_id": form["id"],
        "invoice_id": invoice_id,
        "category": category,
        "covered_days": covered_days,
        "claimed_amount": claimed_amount,
        "reimbursable_amount": Decimal("0.00"),
        "self_paid_amount": Decimal("0.00"),
        "standard_cap_applied": Decimal("0.00"),
        "matched_segment_id": matched_segment_id,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    STORE.reimbursement_items[item_id] = item

    # Cascade: Invoice TAX_VERIFIED -> ATTACHED (refresh inv version)
    inv["ocr_status"] = "ATTACHED"
    inv["updated_at"] = now
    inv["version"] = inv.get("version", 0) + 1

    # Recompute totals (DRAFT-time simple sum)
    recompute_totals_simple_sum(form)
    bump(form)
    return success(ser_item(item), status=201)


# ===================== Remove item =====================
@bp.route("/reimbursement-forms/<fid>/items/<item_id>", methods=["DELETE"])
@require_auth(["Applicant"])
def remove_item(fid, item_id):
    form = _load_form_or_404(fid)
    _ownership_or_forbid(form)
    if form["status"] != "DRAFT":
        raise APIError(ERR_INVALID_STATE, "Form is not in DRAFT", 409)
    item = STORE.reimbursement_items.get(item_id)
    if not item or item["form_id"] != form["id"]:
        raise APIError(ERR_NOT_FOUND, f"Item {item_id} not found", 404)

    inv = STORE.invoices.get(item["invoice_id"])
    # Revert invoice ATTACHED -> TAX_VERIFIED
    if inv is not None and inv["ocr_status"] == "ATTACHED":
        inv["ocr_status"] = "TAX_VERIFIED"
        inv["updated_at"] = CLOCK.now_iso()
        inv["version"] = inv.get("version", 0) + 1
    del STORE.reimbursement_items[item_id]
    recompute_totals_simple_sum(form)
    bump(form)
    return empty_204()


# ===================== Submit =====================
@bp.route("/reimbursement-forms/<fid>/submit", methods=["POST"])
@require_auth(["Applicant"])
def submit_form(fid):
    form = _load_form_or_404(fid)
    _ownership_or_forbid(form)
    if form["status"] != "DRAFT":
        raise APIError(ERR_INVALID_STATE, "Form is not in DRAFT", 409)
    app = STORE.travel_applications.get(form["application_id"])
    if not app:
        raise APIError(ERR_REFERENCE_INVALID, "Parent application not found", 422)
    if app["status"] not in {"BOOKING_LOCKED", "COMPLETED"}:
        raise APIError(ERR_INVALID_STATE,
                        "Parent application must be BOOKING_LOCKED or COMPLETED", 409)
    items = [i for i in STORE.reimbursement_items.values() if i["form_id"] == form["id"]]
    if not items:
        raise APIError(ERR_INVALID_STATE,
                        "Form must have at least one item to submit", 409)
    # Every attached invoice must be ATTACHED
    for it in items:
        inv = STORE.invoices.get(it["invoice_id"])
        if not inv or inv["ocr_status"] != "ATTACHED":
            raise APIError(ERR_INVALID_STATE,
                            "All attached invoices must be in ATTACHED state", 409)

    # Final settlement recompute
    recompute_totals(form)
    form["status"] = "SUBMITTED"
    bump(form)
    return success(ser_form(form))


# ===================== Approve =====================
FORM_STATUS_ORDER = ["SUBMITTED", "SUPERVISOR_APPROVED", "DEPT_APPROVED",
                     "FINANCE_APPROVED", "GM_APPROVED", "APPROVED"]


ROLE_TO_FORM_STEP = {
    "Supervisor": "SUPERVISOR",
    "DeptHead": "DEPT_HEAD",
    "Finance": "FINANCE",
    "GeneralManager": "GM",
}


def _expected_form_step(status: str) -> str | None:
    if status == "SUBMITTED":
        return "SUPERVISOR"
    if status == "SUPERVISOR_APPROVED":
        return "DEPT_HEAD"
    if status == "DEPT_APPROVED":
        return "FINANCE"
    if status == "FINANCE_APPROVED":
        # Either FINANCE moves directly to APPROVED (if no special) or GM (if special)
        return "FINANCE_OR_GM"
    return None


@bp.route("/reimbursement-forms/<fid>/approve", methods=["POST"])
@require_auth(["Supervisor", "DeptHead", "Finance", "GeneralManager"])
def approve_form(fid):
    form = _load_form_or_404(fid)
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        raise APIError(ERR_VALIDATION, "Request body must be a JSON object", 422)
    comment = body.get("comment")
    if comment is not None and not isinstance(comment, str):
        raise APIError(ERR_VALIDATION, "comment must be a string", 422)

    # State legality
    advanceable = {"SUBMITTED", "SUPERVISOR_APPROVED", "DEPT_APPROVED", "FINANCE_APPROVED"}
    if form["status"] not in advanceable:
        raise APIError(ERR_INVALID_STATE, "Form is not awaiting approval", 409)

    # Chain-step check
    expected = _expected_form_step(form["status"])
    role_step = ROLE_TO_FORM_STEP.get(g.role)

    if expected == "SUPERVISOR":
        if g.role != "Supervisor":
            raise APIError(ERR_NOT_CURRENT_APPROVER, "Expected SUPERVISOR step", 403)
        applicant = STORE.employees.get(form["applicant_id"])
        if not applicant or applicant.get("supervisor_id") != g.user_id:
            raise APIError(ERR_NOT_CURRENT_APPROVER,
                            "Acting Supervisor is not the applicant's supervisor", 403)
        from_status = form["status"]
        form["status"] = "SUPERVISOR_APPROVED"
        actor_role_label = "SUPERVISOR"
    elif expected == "DEPT_HEAD":
        if g.role != "DeptHead":
            raise APIError(ERR_NOT_CURRENT_APPROVER, "Expected DEPT_HEAD step", 403)
        from_status = form["status"]
        form["status"] = "DEPT_APPROVED"
        actor_role_label = "DEPT_HEAD"
    elif expected == "FINANCE":
        if g.role != "Finance":
            raise APIError(ERR_NOT_CURRENT_APPROVER, "Expected FINANCE step", 403)
        from_status = form["status"]
        form["status"] = "FINANCE_APPROVED"
        actor_role_label = "FINANCE"
    elif expected == "FINANCE_OR_GM":
        # Recompute requires_special_approval flag based on current totals
        form["requires_special_approval"] = (
            (form.get("total_self_paid") or Decimal("0.00")) > 0
            and not form.get("special_approval_granted", False)
        )
        if g.role == "Finance":
            # Finance approving from FINANCE_APPROVED
            if form["requires_special_approval"]:
                raise APIError(ERR_GM_APPROVAL_REQUIRED,
                                "Form requires GM approval before final approval", 422)
            from_status = form["status"]
            form["status"] = "APPROVED"
            actor_role_label = "FINANCE"
        elif g.role == "GeneralManager":
            if not form["requires_special_approval"]:
                # GM acting when not required — wrong approver
                raise APIError(ERR_NOT_CURRENT_APPROVER,
                                "GM approval is not required for this form", 403)
            from_status = form["status"]
            form["status"] = "APPROVED"  # auto-transition through GM_APPROVED
            form["special_approval_granted"] = True
            form["requires_special_approval"] = False
            actor_role_label = "GM"
        else:
            raise APIError(ERR_NOT_CURRENT_APPROVER,
                            "Expected FINANCE or GM at this step", 403)
    else:
        raise APIError(ERR_INVALID_STATE, "Form is not in an approvable state", 409)

    bump(form)
    write_approval_record(
        subject_type="REIMBURSEMENT_FORM",
        subject_id=form["id"],
        actor_id=g.user_id,
        actor_role=actor_role_label,
        action="APPROVE",
        comment=comment,
        from_status=from_status,
        to_status=form["status"],
    )
    return success(ser_form(form))


# ===================== Reject =====================
@bp.route("/reimbursement-forms/<fid>/reject", methods=["POST"])
@require_auth(["Supervisor", "DeptHead", "Finance", "GeneralManager"])
def reject_form(fid):
    form = _load_form_or_404(fid)
    body = require_body(request.get_json(silent=True))
    reason = get_str(body, "rejection_reason")
    correction = get_bool(body, "correction", required=True)

    rejectable = {"SUBMITTED", "SUPERVISOR_APPROVED", "DEPT_APPROVED", "FINANCE_APPROVED"}
    if form["status"] not in rejectable:
        raise APIError(ERR_INVALID_STATE, "Form is not in a rejectable state", 409)

    # Role at this step
    expected = _expected_form_step(form["status"])
    # We allow the *current* chain-step approver to reject. Map expected->required role(s).
    allowed_roles = set()
    if expected == "SUPERVISOR":
        allowed_roles = {"Supervisor"}
    elif expected == "DEPT_HEAD":
        allowed_roles = {"DeptHead"}
    elif expected == "FINANCE":
        allowed_roles = {"Finance"}
    elif expected == "FINANCE_OR_GM":
        # Both finance and GM may reject from FINANCE_APPROVED
        allowed_roles = {"Finance", "GeneralManager"}

    if g.role not in allowed_roles:
        raise APIError(ERR_NOT_CURRENT_APPROVER,
                        "Acting role is not the current chain step's approver", 403)
    if g.role == "Supervisor":
        applicant = STORE.employees.get(form["applicant_id"])
        if not applicant or applicant.get("supervisor_id") != g.user_id:
            raise APIError(ERR_NOT_CURRENT_APPROVER,
                            "Acting Supervisor is not the applicant's supervisor", 403)

    actor_role_label = ROLE_TO_FORM_STEP[g.role]

    # correction=false is only allowed from SUBMITTED per state machine?
    # The SCAFFOLD only defines SUBMITTED -> REJECTED for correction=false.
    if not correction:
        if form["status"] != "SUBMITTED":
            raise APIError(ERR_INVALID_STATE,
                            "Terminal reject is only valid from SUBMITTED", 409)
        from_status = form["status"]
        form["status"] = "REJECTED"
        form["rejection_reason"] = reason
        bump(form)
        write_approval_record(
            subject_type="REIMBURSEMENT_FORM",
            subject_id=form["id"],
            actor_id=g.user_id,
            actor_role=actor_role_label,
            action="REJECT",
            comment=reason,
            from_status=from_status,
            to_status="REJECTED",
        )
        return success(ser_form(form))

    # correction=true: revert to DRAFT, increment correction_round, revert invoices
    from_status = form["status"]
    form["status"] = "DRAFT"
    form["correction_round"] = form.get("correction_round", 0) + 1
    form["rejection_reason"] = reason
    # Revert invoices ATTACHED -> TAX_VERIFIED
    for it in STORE.reimbursement_items.values():
        if it["form_id"] != form["id"]:
            continue
        inv = STORE.invoices.get(it["invoice_id"])
        if inv and inv["ocr_status"] == "ATTACHED":
            inv["ocr_status"] = "TAX_VERIFIED"
            inv["updated_at"] = CLOCK.now_iso()
            inv["version"] = inv.get("version", 0) + 1
    # Reset settlement totals (back to simple draft sum)
    recompute_totals_simple_sum(form)
    bump(form)
    write_approval_record(
        subject_type="REIMBURSEMENT_FORM",
        subject_id=form["id"],
        actor_id=g.user_id,
        actor_role=actor_role_label,
        action="REJECT",
        comment=reason,
        from_status=from_status,
        to_status="DRAFT",
    )
    return success(ser_form(form))
