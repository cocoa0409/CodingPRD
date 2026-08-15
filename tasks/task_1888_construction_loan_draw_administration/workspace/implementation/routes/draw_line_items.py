from flask import Blueprint, g, request

import db
from auth import ALL_ROLES, require_borrower_ownership, require_role
from db import pub, touch
from errors import ApiError
from respond import success, success_list
from services import get_or_404, items_of_draw
from util import (
    get_body,
    opt_date,
    paginate,
    req_date,
    req_enum,
    req_int,
    req_str,
    sort_created,
)

bp = Blueprint("draw_line_items", __name__)

LINE_TYPES = ["WORK_COMPLETED", "STORED_MATERIALS"]
STORED_EVIDENCE_FIELDS = (
    "stored_material_invoice_cents",
    "insurance_certificate_ref",
    "stored_location",
)


@bp.post("/draw-line-items")
def create_draw_line_item():
    require_role(g.role, {"Borrower"})
    body = get_body()
    # Existence (4): draw first (needed for ownership), then budget line.
    draw_id = body.get("draw_id")
    if draw_id is not None and draw_id not in db.draws:
        raise ApiError("ERR_NOT_FOUND", "DrawRequest not found")
    draw = db.draws.get(draw_id) if isinstance(draw_id, str) else None
    if draw is not None:
        loan = db.loans[draw["loan_id"]]
        # Borrower ownership (3).
        require_borrower_ownership(g.uid, loan)
    line_id = body.get("budget_line_id")
    if line_id is not None and line_id not in db.budget_lines:
        raise ApiError("ERR_NOT_FOUND", "BudgetLine not found")
    if draw is not None:
        loan = db.loans[draw["loan_id"]]
        # Loan-open gating (6).
        if loan["status"] != "OPEN":
            raise ApiError(
                "ERR_LOAN_NOT_OPEN", "Line items can only be added under an OPEN loan"
            )
        # Draw from-state (6).
        if draw["status"] not in ("DRAFT", "REVISION_REQUESTED"):
            raise ApiError(
                "ERR_INVALID_STATE",
                "Line items can only be added to a DRAFT or REVISION_REQUESTED draw",
            )
    # Structural rules (9).
    line_type = req_enum(body, "line_type", LINE_TYPES)
    requested = req_int(body, "requested_cents", min_value=1)
    if line_type == "STORED_MATERIALS":
        missing = [
            f
            for f in STORED_EVIDENCE_FIELDS
            if body.get(f) is None or (isinstance(body.get(f), str) and body.get(f) == "")
        ]
        if missing:
            raise ApiError(
                "ERR_STORED_MATERIALS_EVIDENCE_MISSING",
                "STORED_MATERIALS line missing: " + ", ".join(missing),
            )
        sm_invoice = req_int(body, "stored_material_invoice_cents", min_value=1)
        insurance_ref = req_str(body, "insurance_certificate_ref")
        stored_location = req_str(body, "stored_location")
    else:
        for f in STORED_EVIDENCE_FIELDS:
            if body.get(f) is not None:
                raise ApiError(
                    "ERR_INVALID_REQUEST",
                    f"Field '{f}' is forbidden on a WORK_COMPLETED line",
                )
        sm_invoice = None
        insurance_ref = None
        stored_location = None
    installed_by = opt_date(body, "installed_by_date")
    draw_id = req_str(body, "draw_id")
    line_id = req_str(body, "budget_line_id")
    # Cross-entity linkage (10): budget line belongs to the draw's loan.
    line = db.budget_lines[line_id]
    if line["loan_id"] != draw["loan_id"]:
        raise ApiError(
            "ERR_BUDGET_LINE_LOAN_MISMATCH",
            "Budget line belongs to a different loan than the draw",
        )
    rec = db.base_record()
    rec.update(
        {
            "draw_id": draw_id,
            "budget_line_id": line_id,
            "line_type": line_type,
            "requested_cents": requested,
            "stored_material_invoice_cents": sm_invoice,
            "insurance_certificate_ref": insurance_ref,
            "stored_location": stored_location,
            "installed_by_date": installed_by,
            "is_installed": False,
            "installed_date": None,
            "approved_cents": 0,
            "retainage_cents": 0,
            "net_fundable_cents": 0,
            "funded_cents": 0,
        }
    )
    db.draw_line_items[rec["id"]] = rec
    # Recompute the draw's requested total (a draw mutation -> version bump).
    draw["requested_total_cents"] = sum(
        i["requested_cents"] for i in items_of_draw(draw_id)
    )
    touch(draw)
    return success(pub(rec), 201)


@bp.get("/draw-line-items/<rid>")
def get_draw_line_item(rid):
    require_role(g.role, ALL_ROLES)
    return success(pub(get_or_404(db.draw_line_items, rid, "DrawLineItem")))


@bp.get("/draw-line-items")
def list_draw_line_items():
    require_role(g.role, ALL_ROLES)
    items = list(db.draw_line_items.values())
    f_draw = request.args.get("draw_id")
    f_line = request.args.get("budget_line_id")
    f_type = request.args.get("line_type")
    if f_draw is not None:
        items = [i for i in items if i["draw_id"] == f_draw]
    if f_line is not None:
        items = [i for i in items if i["budget_line_id"] == f_line]
    if f_type is not None:
        items = [i for i in items if i["line_type"] == f_type]
    page, total, limit, offset = paginate(sort_created(items))
    return success_list([pub(r) for r in page], total, limit, offset)


@bp.post("/draw-line-items/<rid>/mark-installed")
def mark_installed(rid):
    require_role(g.role, {"DrawProcessor"})
    item = get_or_404(db.draw_line_items, rid, "DrawLineItem")
    draw = db.draws[item["draw_id"]]
    # State validity (6): draw APPROVED or FUNDED, and not already installed.
    if draw["status"] not in ("APPROVED", "FUNDED") or item["is_installed"]:
        raise ApiError(
            "ERR_INVALID_STATE",
            "mark-installed requires the draw to be APPROVED or FUNDED and the line not already installed",
        )
    # Structural rule (9): STORED_MATERIALS lines only.
    if item["line_type"] != "STORED_MATERIALS":
        raise ApiError(
            "ERR_LINE_NOT_STORED_MATERIALS",
            "mark-installed called on a WORK_COMPLETED line item",
        )
    body = get_body()
    item["installed_date"] = req_date(body, "installed_date")
    item["is_installed"] = True
    touch(item)
    return success(pub(item))
