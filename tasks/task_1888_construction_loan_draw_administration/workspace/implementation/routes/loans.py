from decimal import Decimal
from flask import Blueprint, g, request

import db
from auth import ALL_ROLES, require_role
from db import pub, touch
from errors import ApiError
from respond import success, success_list
from services import (
    ACTIVE_DRAW_STATES,
    cascade_close_budget_lines,
    entries_of_loan,
    get_or_404,
    make_entry,
    recompute_loan_money,
    sweep_reserve,
)
from util import (
    day_count,
    dec_num,
    get_body,
    opt_enum,
    opt_num,
    paginate,
    parse_date_str,
    req_date,
    req_int,
    req_str,
    sort_created,
    to_date,
    round_half_up,
)

bp = Blueprint("loans", __name__)

DAY_COUNT_CONVENTIONS = ["ACTUAL_360", "THIRTY_360"]


def _loan_or_404(rid):
    return get_or_404(db.loans, rid, "Loan")


@bp.post("/loans")
def create_loan():
    require_role(g.role, {"LenderAdmin"})
    body = get_body()
    # Existence (priority 4) before structural field validation (priority 9).
    borrower_id = body.get("borrower_id")
    if borrower_id is not None and borrower_id not in db.borrowers:
        raise ApiError("ERR_NOT_FOUND", "Borrower not found")
    borrower_id = req_str(body, "borrower_id")
    commitment = req_int(body, "commitment_amount_cents", min_value=1)
    rate_bps = req_int(body, "interest_rate_annual_bps", min_value=0)
    reserve_initial = req_int(body, "interest_reserve_initial_cents", min_value=0)
    maturity = req_date(body, "maturity_date")
    dcc = opt_enum(body, "day_count_convention", DAY_COUNT_CONVENTIONS, "ACTUAL_360")
    retainage_pct = opt_num(body, "retainage_pct", 10.00)
    reduced_pct = opt_num(body, "reduced_retainage_pct", 5.00)
    milestone_pct = opt_num(body, "retainage_milestone_pct", 50.00)
    sm_max_pct = opt_num(body, "stored_materials_max_pct", 75.00)

    rec = db.base_record()
    rec.update(
        {
            "borrower_id": borrower_id,
            "commitment_amount_cents": commitment,
            "interest_rate_annual_bps": rate_bps,
            "day_count_convention": dcc,
            "interest_reserve_initial_cents": reserve_initial,
            "maturity_date": maturity,
            "retainage_pct": retainage_pct,
            "reduced_retainage_pct": reduced_pct,
            "retainage_milestone_pct": milestone_pct,
            "stored_materials_max_pct": sm_max_pct,
            "status": "OPEN",
            "total_original_budget_cents": 0,
            "principal_disbursed_cents": 0,
            "retained_cents": 0,
            "interest_reserve_balance_cents": reserve_initial,
            "interest_reserve_depleted": False,
            "interest_reserve_swept_cents": 0,
            "interest_capitalized_cents": 0,
            "inspection_percent_complete": 0.0,
            "cost_percent_complete": 0.0,
            "milestone_reached": False,
            "retainage_fully_released": False,
            "permanent_interest_rate_annual_bps": None,
            "permanent_term_months": None,
            "_retained_positive": False,
        }
    )
    db.loans[rec["id"]] = rec
    # Seed the interest reserve ledger with INITIAL_DEPOSIT (entry_index 1).
    make_entry(
        rec,
        "INITIAL_DEPOSIT",
        reserve_initial,
        None,
        None,
        None,
        None,
        None,
        0,
        reserve_initial,
    )
    return success(pub(rec), 201)


@bp.get("/loans/<rid>")
def get_loan(rid):
    require_role(g.role, ALL_ROLES)
    return success(pub(_loan_or_404(rid)))


@bp.get("/loans")
def list_loans():
    require_role(g.role, ALL_ROLES)
    items = list(db.loans.values())
    f_borrower = request.args.get("borrower_id")
    f_status = request.args.get("status")
    if f_borrower is not None:
        items = [l for l in items if l["borrower_id"] == f_borrower]
    if f_status is not None:
        items = [l for l in items if l["status"] == f_status]
    page, total, limit, offset = paginate(sort_created(items))
    return success_list([pub(r) for r in page], total, limit, offset)


@bp.post("/loans/<rid>/terminate")
def terminate_loan(rid):
    require_role(g.role, {"LenderAdmin"})
    loan = _loan_or_404(rid)
    if loan["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "Only an OPEN loan can be terminated")
    has_active_draw = any(
        d["loan_id"] == rid and d["status"] in ACTIVE_DRAW_STATES
        for d in db.draws.values()
    )
    has_active_realloc = any(
        r["loan_id"] == rid and r["status"] in ("PENDING", "APPROVED")
        for r in db.reallocation_requests.values()
    )
    has_active_release = any(
        r["loan_id"] == rid and r["status"] in ("REQUESTED", "APPROVED")
        for r in db.retainage_releases.values()
    )
    has_active_conversion = any(
        c["loan_id"] == rid and c["status"] in ("REQUESTED", "APPROVED")
        for c in db.conversion_reviews.values()
    )
    if (
        loan["principal_disbursed_cents"] != 0
        or loan["retained_cents"] != 0
        or has_active_draw
        or has_active_realloc
        or has_active_release
        or has_active_conversion
    ):
        raise ApiError(
            "ERR_LOAN_HAS_ACTIVITY",
            "Terminate blocked by disbursed/retained balances or non-terminal child workflows",
        )
    loan["status"] = "TERMINATED"
    cascade_close_budget_lines(loan)
    sweep_reserve(loan)
    touch(loan)
    return success(pub(loan))


@bp.post("/loans/<rid>/interest-accruals")
def run_interest_accrual(rid):
    require_role(g.role, {"LoanServicer"})
    loan = _loan_or_404(rid)
    if loan["status"] != "OPEN":
        raise ApiError("ERR_LOAN_NOT_OPEN", "Interest accruals require an OPEN loan")
    body = get_body()
    ps = req_date(body, "period_start_date")
    pe = req_date(body, "period_end_date")
    d1, d2 = to_date(ps), to_date(pe)

    # Pinned evaluation order (PRD §3.8).
    base = loan["principal_disbursed_cents"] + loan["interest_capitalized_cents"]
    days = day_count(loan["day_count_convention"], d1, d2)
    interest_due = round_half_up(
        Decimal(base)
        * Decimal(loan["interest_rate_annual_bps"])
        * Decimal(days)
        / (Decimal(10000) * Decimal(360))
    )
    paid_from_reserve = min(interest_due, loan["interest_reserve_balance_cents"])
    loan["interest_reserve_balance_cents"] -= paid_from_reserve
    shortfall = interest_due - paid_from_reserve
    if shortfall > 0:
        loan["interest_capitalized_cents"] += shortfall
    if loan["interest_reserve_balance_cents"] == 0:
        loan["interest_reserve_depleted"] = True
    balance_after = loan["interest_reserve_balance_cents"]

    ip = make_entry(
        loan,
        "INTEREST_PAYMENT",
        -paid_from_reserve,
        ps,
        pe,
        days,
        interest_due,
        paid_from_reserve,
        shortfall,
        balance_after,
    )
    if shortfall > 0:
        make_entry(
            loan,
            "CAPITALIZATION",
            0,
            ps,
            pe,
            days,
            interest_due,
            paid_from_reserve,
            shortfall,
            balance_after,
        )
    touch(loan)
    return success(pub(ip), 201)


@bp.get("/loans/<rid>/interest-ledger")
def interest_ledger(rid):
    require_role(g.role, ALL_ROLES)
    _loan_or_404(rid)
    entries = entries_of_loan(rid)  # ordered by entry_index ASC
    page, total, limit, offset = paginate(entries)
    return success_list([pub(e) for e in page], total, limit, offset)
