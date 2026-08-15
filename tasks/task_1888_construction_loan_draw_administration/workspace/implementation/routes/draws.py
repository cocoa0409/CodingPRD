from decimal import Decimal

from flask import Blueprint, g, request

import db
from auth import ALL_ROLES, require_borrower_ownership, require_role
from db import pub, touch
from errors import ApiError
from respond import success, success_list
from services import (
    OVERLAP_BLOCKING_STATES,
    docs_of_draw,
    draws_of_loan,
    get_or_404,
    items_of_draw,
    latest_accepted_inspection,
    recompute_loan_money,
    approved_unfunded_for_line,
)
from util import (
    dec_num,
    floor_int,
    get_body,
    paginate,
    req_date,
    req_str,
    round_half_up,
    sort_created,
    to_date,
)

bp = Blueprint("draws", __name__)


def _draw_or_404(rid):
    return get_or_404(db.draws, rid, "DrawRequest")


@bp.post("/draws")
def create_draw():
    require_role(g.role, {"Borrower"})
    body = get_body()
    loan_id = body.get("loan_id")
    if loan_id is not None and loan_id not in db.loans:
        raise ApiError("ERR_NOT_FOUND", "Loan not found")
    loan = db.loans.get(loan_id) if isinstance(loan_id, str) else None
    if loan is not None:
        # Borrower ownership (priority 3).
        require_borrower_ownership(g.uid, loan)
        # Loan-open gating (priority 6).
        if loan["status"] != "OPEN":
            raise ApiError("ERR_LOAN_NOT_OPEN", "Draws can only be created on an OPEN loan")
    # Temporal rule (priority 8): end strictly after start.
    ps_raw, pe_raw = body.get("period_start_date"), body.get("period_end_date")
    if isinstance(ps_raw, str) and isinstance(pe_raw, str):
        try:
            if not (to_date(pe_raw) > to_date(ps_raw)):
                raise ApiError(
                    "ERR_DRAW_PERIOD_INVALID",
                    "period_end_date must be strictly after period_start_date",
                )
        except ValueError:
            pass  # malformed dates are handled by structural validation below
    # Structural field validation (priority 9).
    ps = req_date(body, "period_start_date")
    pe = req_date(body, "period_end_date")
    loan_id = req_str(body, "loan_id")

    draw_number = max(
        (d["draw_number"] for d in draws_of_loan(loan_id)), default=0
    ) + 1
    rec = db.base_record()
    rec.update(
        {
            "loan_id": loan_id,
            "draw_number": draw_number,
            "period_start_date": ps,
            "period_end_date": pe,
            "status": "DRAFT",
            "revision_notes": None,
            "rejection_reason": None,
            "requested_total_cents": 0,
            "approved_total_cents": 0,
            "retainage_total_cents": 0,
            "funded_total_cents": 0,
            "effective_retainage_pct": None,
            "milestone_applied": False,
        }
    )
    db.draws[rec["id"]] = rec
    return success(pub(rec), 201)


@bp.get("/draws/<rid>")
def get_draw(rid):
    require_role(g.role, ALL_ROLES)
    return success(pub(_draw_or_404(rid)))


@bp.get("/draws")
def list_draws():
    require_role(g.role, ALL_ROLES)
    items = list(db.draws.values())
    f_loan = request.args.get("loan_id")
    f_status = request.args.get("status")
    if f_loan is not None:
        items = [d for d in items if d["loan_id"] == f_loan]
    if f_status is not None:
        items = [d for d in items if d["status"] == f_status]
    page, total, limit, offset = paginate(sort_created(items))
    return success_list([pub(r) for r in page], total, limit, offset)


@bp.post("/draws/<rid>/submit")
def submit_draw(rid):
    require_role(g.role, {"Borrower"})
    draw = _draw_or_404(rid)
    loan = db.loans[draw["loan_id"]]
    require_borrower_ownership(g.uid, loan)
    if draw["status"] not in ("DRAFT", "REVISION_REQUESTED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            "Only a DRAFT or REVISION_REQUESTED draw can be submitted",
        )
    # Temporal rule (priority 8): half-open period overlap vs sibling draws.
    for sib in draws_of_loan(draw["loan_id"]):
        if sib["id"] == draw["id"] or sib["status"] not in OVERLAP_BLOCKING_STATES:
            continue
        if (
            draw["period_start_date"] < sib["period_end_date"]
            and sib["period_start_date"] < draw["period_end_date"]
        ):
            raise ApiError(
                "ERR_DRAW_PERIOD_OVERLAP",
                "Billing period overlaps a sibling draw in an active or funded state",
            )
    # Structural rule (priority 9): at least one line item.
    if not items_of_draw(draw["id"]):
        raise ApiError("ERR_DRAW_HAS_NO_LINES", "Submit requires at least one line item")
    draw["status"] = "SUBMITTED"
    touch(draw)
    return success(pub(draw))


@bp.post("/draws/<rid>/start-review")
def start_review(rid):
    require_role(g.role, {"DrawProcessor"})
    draw = _draw_or_404(rid)
    if draw["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "Only a SUBMITTED draw can move to UNDER_REVIEW")
    draw["status"] = "UNDER_REVIEW"
    touch(draw)
    return success(pub(draw))


@bp.post("/draws/<rid>/request-revision")
def request_revision(rid):
    require_role(g.role, {"DrawProcessor"})
    draw = _draw_or_404(rid)
    if draw["status"] != "UNDER_REVIEW":
        raise ApiError(
            "ERR_INVALID_STATE", "Only an UNDER_REVIEW draw can be sent back for revision"
        )
    body = get_body()
    draw["revision_notes"] = req_str(body, "revision_notes")
    draw["status"] = "REVISION_REQUESTED"
    touch(draw)
    return success(pub(draw))


@bp.post("/draws/<rid>/reject")
def reject_draw(rid):
    require_role(g.role, {"DrawProcessor"})
    draw = _draw_or_404(rid)
    if draw["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", "Only an UNDER_REVIEW draw can be rejected")
    body = get_body()
    draw["rejection_reason"] = req_str(body, "reason")
    draw["status"] = "REJECTED"
    touch(draw)
    return success(pub(draw))


@bp.post("/draws/<rid>/withdraw")
def withdraw_draw(rid):
    require_role(g.role, {"Borrower"})
    draw = _draw_or_404(rid)
    loan = db.loans[draw["loan_id"]]
    require_borrower_ownership(g.uid, loan)
    if draw["status"] not in ("DRAFT", "SUBMITTED", "REVISION_REQUESTED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            "Only a DRAFT, SUBMITTED, or REVISION_REQUESTED draw can be withdrawn",
        )
    draw["status"] = "WITHDRAWN"
    touch(draw)
    return success(pub(draw))


@bp.post("/draws/<rid>/approve")
def approve_draw(rid):
    require_role(g.role, {"CreditOfficer"})
    draw = _draw_or_404(rid)
    if draw["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", "Only an UNDER_REVIEW draw can be approved")
    loan = db.loans[draw["loan_id"]]
    items = items_of_draw(draw["id"])
    docs = docs_of_draw(draw["id"])
    verified = [d for d in docs if d["status"] == "VERIFIED"]

    # Gate 1 (priority 7): lien-waiver coverage.
    funded_siblings = [
        d for d in draws_of_loan(draw["loan_id"]) if d["status"] == "FUNDED"
    ]
    prior = max(funded_siblings, key=lambda d: d["draw_number"], default=None)
    required_unconditional = prior["approved_total_cents"] if prior else 0
    required_conditional = draw["requested_total_cents"]
    verified_unconditional = sum(
        d["amount_cents"]
        for d in verified
        if d["doc_type"] == "LIEN_WAIVER_UNCONDITIONAL"
    )
    verified_conditional = sum(
        d["amount_cents"] for d in verified if d["doc_type"] == "LIEN_WAIVER_CONDITIONAL"
    )
    if (
        verified_unconditional < required_unconditional
        or verified_conditional < required_conditional
    ):
        raise ApiError(
            "ERR_LIEN_WAIVER_UNVERIFIED",
            "Verified lien-waiver coverage below required unconditional/conditional amounts",
        )

    # Gate 2 (priority 8): accepted-inspection staleness vs the draw period
    # (closed interval [period_start_date, period_end_date]).
    insp = latest_accepted_inspection(draw["loan_id"], draw_id=draw["id"])
    if insp is not None and not (
        draw["period_start_date"] <= insp["completed_date"] <= draw["period_end_date"]
    ):
        raise ApiError(
            "ERR_INSPECTION_STALE",
            "ACCEPTED inspection's completed_date lies outside the draw's billing period",
        )

    # Gate 3 (priority 10): an ACCEPTED inspection linked to this draw must exist.
    if insp is None:
        raise ApiError(
            "ERR_INSPECTION_REQUIRED", "No ACCEPTED inspection linked to the draw"
        )

    # Gate 4 (priority 11): invoice coverage over WORK_COMPLETED lines.
    required_invoice = sum(
        i["requested_cents"] for i in items if i["line_type"] == "WORK_COMPLETED"
    )
    covered_invoice = sum(d["amount_cents"] for d in verified if d["doc_type"] == "INVOICE")
    if covered_invoice < required_invoice:
        raise ApiError(
            "ERR_INVOICE_COVERAGE_INSUFFICIENT",
            "Verified INVOICE total below requested WORK_COMPLETED total",
        )

    # Compute per-line approval amounts (no mutation until all gates pass).
    eff_pct = (
        loan["reduced_retainage_pct"]
        if loan["milestone_reached"]
        else loan["retainage_pct"]
    )
    insp_pct = dec_num(insp["percent_complete_reported"])
    computed = []
    for item in items:
        line = db.budget_lines[item["budget_line_id"]]
        consumed = (
            line["disbursed_cents"]
            + line["retained_cents"]
            + line["approved_unfunded_cents"]
        )
        cost_headroom = line["revised_amount_cents"] - consumed
        inspection_cap = (
            floor_int(Decimal(line["revised_amount_cents"]) * insp_pct / Decimal(100))
            - consumed
        )
        inspection_cap = max(inspection_cap, 0)
        approved = min(item["requested_cents"], cost_headroom, inspection_cap)
        if item["line_type"] == "STORED_MATERIALS":
            if item["is_installed"]:
                sm_cap = item["stored_material_invoice_cents"]
            else:
                sm_cap = floor_int(
                    Decimal(item["stored_material_invoice_cents"])
                    * dec_num(loan["stored_materials_max_pct"])
                    / Decimal(100)
                )
            approved = min(approved, sm_cap)
        approved = max(approved, 0)
        retainage = round_half_up(Decimal(approved) * dec_num(eff_pct) / Decimal(100))
        computed.append((item, approved, retainage))

    approved_total = sum(c[1] for c in computed)
    # Gate 5 (priority 11): something must be approvable.
    if approved_total <= 0:
        raise ApiError("ERR_NOTHING_APPROVABLE", "Computed approved_total_cents is zero")

    # Commit: line items, then the draw, then touched budget lines.
    for item, approved, retainage in computed:
        item["approved_cents"] = approved
        item["retainage_cents"] = retainage
        item["net_fundable_cents"] = approved - retainage
        touch(item)
    draw["approved_total_cents"] = approved_total
    draw["retainage_total_cents"] = sum(c[2] for c in computed)
    draw["effective_retainage_pct"] = eff_pct
    draw["milestone_applied"] = bool(loan["milestone_reached"])
    draw["status"] = "APPROVED"
    touch(draw)
    touched_lines = {db.budget_lines[i["budget_line_id"]]["id"] for i in items}
    for line_id in touched_lines:
        line = db.budget_lines[line_id]
        line["approved_unfunded_cents"] = approved_unfunded_for_line(line_id)
        touch(line)
    return success(pub(draw))


@bp.post("/draws/<rid>/fund")
def fund_draw(rid):
    require_role(g.role, {"LoanServicer"})
    draw = _draw_or_404(rid)
    if draw["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", "Only an APPROVED draw can be funded")
    loan = db.loans[draw["loan_id"]]
    if loan["status"] != "OPEN":
        raise ApiError("ERR_LOAN_NOT_OPEN", "Funding requires an OPEN loan")
    items = items_of_draw(draw["id"])
    for item in items:
        item["funded_cents"] = item["net_fundable_cents"]
        touch(item)
    per_line = {}
    for item in items:
        agg = per_line.setdefault(
            item["budget_line_id"], {"net": 0, "ret": 0, "appr": 0}
        )
        agg["net"] += item["net_fundable_cents"]
        agg["ret"] += item["retainage_cents"]
        agg["appr"] += item["approved_cents"]
    for line_id, agg in per_line.items():
        line = db.budget_lines[line_id]
        line["disbursed_cents"] += agg["net"]
        line["retained_cents"] += agg["ret"]
        line["approved_unfunded_cents"] -= agg["appr"]
        touch(line)
    draw["funded_total_cents"] = sum(i["funded_cents"] for i in items)
    draw["status"] = "FUNDED"
    touch(draw)
    recompute_loan_money(loan)
    touch(loan)
    return success(pub(draw))
