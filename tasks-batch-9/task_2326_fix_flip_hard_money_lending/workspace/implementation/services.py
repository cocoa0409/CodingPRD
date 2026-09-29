"""Shared side-effect services: ledger writes, cascades and compensating reversals."""

import calc
import serialize as ser
from core import clock_date, clock_instant, conflict, db, new_record, touch


# ---------------------------------------------------------------------------
# Ledger (PRD 2.5)
# ---------------------------------------------------------------------------
def write_ledger(loan, entry_type, amount_cents, effective_date, memo, source_ref):
    entry = new_record(full=False)
    entry.update({
        "loan_id": loan["id"],
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "effective_date": effective_date if effective_date is not None else clock_date(),
        "memo": memo,
        "source_ref": source_ref,
    })
    db.ledger_entries[entry["id"]] = entry
    return entry


# ---------------------------------------------------------------------------
# Application / scope-line cascades (PRD 2.10, 3.1, 3.2)
# ---------------------------------------------------------------------------
def recompute_application_total(app):
    total = ser.approved_rehab_total(app["id"])
    if app["approved_rehab_total_cents"] != total:
        app["approved_rehab_total_cents"] = total
        return True
    return False


def mark_sizing_stale(app):
    if app["status"] == "SIZED":
        app["_sizing_stale"] = True


def void_live_lines(app):
    for line in ser.application_lines(app["id"]):
        if line["status"] in calc.VOIDABLE_SCOPE_STATUSES:
            line["status"] = "VOID"
            line["approved_cost_cents"] = None
            touch(line)
    recompute_application_total(app)


SIZING_FIELDS = (
    "cap_purchase_advance_cents", "cap_ltc_cents", "cap_ltarv_cents",
    "max_total_loan_cents", "sized_committed_amount_cents",
    "sized_initial_funding_cents", "sized_interest_reserve_cents",
    "sizing_arv_cents", "sizing_rate_bps",
)


def clear_sizing_fields(app):
    for name in SIZING_FIELDS:
        app[name] = None
    app["_sizing_rehab_total_cents"] = None
    app["_sizing_stale"] = False


def withdraw_application(app):
    was_sized = app["status"] == "SIZED"
    app["status"] = "WITHDRAWN"
    if was_sized:
        clear_sizing_fields(app)
    void_live_lines(app)
    touch(app)


def suspend_borrower(borrower, reason, skip_application_id=None):
    """APPROVED_SPONSOR -> SUSPENDED plus the two-level WITHDRAWN / VOID cascade."""
    if borrower["status"] == "APPROVED_SPONSOR":
        borrower["status"] = "SUSPENDED"
        borrower["suspension_reason"] = reason
        for app in ser.borrower_applications(borrower["id"]):
            if app["id"] == skip_application_id:
                continue
            if app["status"] in ("DRAFT", "SIZED"):
                withdraw_application(app)
    touch(borrower)


# ---------------------------------------------------------------------------
# Draw request cascades (PRD 2.10, 3.5, 3.9)
# ---------------------------------------------------------------------------
def cancel_scheduled_visits(request):
    for visit in ser.request_visits(request["id"]):
        if visit["status"] == "SCHEDULED":
            visit["status"] = "CANCELLED"
            touch(visit)


def reverse_approval(loan, request):
    """Return earmarked cash to the holdback and clear the approved figures."""
    amount = request["approved_release_cents"]
    if amount:
        loan["reserved_release_cents"] -= amount
        loan["undisbursed_holdback_cents"] += amount
    request["approved_release_cents"] = None
    for alloc in ser.request_allocations(request["id"]):
        if alloc["approved_amount_cents"] is not None:
            alloc["approved_amount_cents"] = None
            touch(alloc)


def close_open_request(loan, request, new_status, superseded_by=None):
    previous = request["status"]
    request["status"] = new_status
    if superseded_by is not None:
        request["superseded_by_draw_request_id"] = superseded_by
    if previous == "INSPECTION_ORDERED":
        cancel_scheduled_visits(request)
    if previous == "APPROVED":
        reverse_approval(loan, request)
    touch(request)


def supersede_open_requests(loan, new_request_id):
    for request in ser.loan_draw_requests(loan["id"]):
        if request["id"] == new_request_id:
            continue
        if request["status"] in calc.OPEN_DRAW_STATUSES:
            close_open_request(loan, request, "SUPERSEDED", superseded_by=new_request_id)


def suspend_open_requests(loan):
    for request in ser.loan_draw_requests(loan["id"]):
        if request["status"] in calc.SUSPENDABLE_DRAW_STATUSES:
            close_open_request(loan, request, "SUSPENDED")


# ---------------------------------------------------------------------------
# Exit axis (PRD 3.8)
# ---------------------------------------------------------------------------
FROZEN_EXIT_STATUSES = ("REFI_IN_PROCESS", "EXITED", "FORECLOSED")


def set_exit_status(loan, new_status):
    previous = loan["exit_status"]
    loan["exit_status"] = new_status
    if new_status in FROZEN_EXIT_STATUSES:
        if previous not in FROZEN_EXIT_STATUSES or loan.get("_days_on_market_frozen") is None:
            loan["_days_on_market_frozen"] = calc.live_days_on_market(loan)
    else:
        loan["_days_on_market_frozen"] = None


def refresh_exit_status(loan):
    latest = calc.latest_milestone(loan["id"])
    if latest is None:
        return
    set_exit_status(loan, calc.MILESTONE_EXIT_MAP[latest["milestone_type"]])


# ---------------------------------------------------------------------------
# Property cascade (PRD 3.2)
# ---------------------------------------------------------------------------
def move_property(loan, new_status, allowed_from):
    prop = property_of_loan(loan)
    if prop is None:
        return
    if prop["status"] in allowed_from:
        prop["status"] = new_status
        touch(prop)


def property_of_loan(loan):
    app = db.applications.get(loan["application_id"])
    if app is None:
        return None
    return db.properties.get(app["property_id"])


# ---------------------------------------------------------------------------
# Loan settlement shared by payoff and REO disposition (PRD 3.7, 3.9)
# ---------------------------------------------------------------------------
def settle_principal_and_revenue(loan):
    loan["repaid_principal_cents"] += loan["funded_principal_cents"]
    loan["funded_principal_cents"] = 0
    loan["accrued_interest_unpaid_cents"] = 0
    loan["fee_balance_cents"] = 0


def stamp_funded(request, user_id):
    request["funded_by_user_id"] = user_id
    request["funded_at"] = clock_instant()


# ---------------------------------------------------------------------------
# Guards (PRD 2.12 steps 9 and 10)
# ---------------------------------------------------------------------------
def require_loan_writable(loan):
    if loan["payment_status"] in calc.TERMINAL_PAYMENT_STATUSES:
        raise conflict("ERR_LOAN_STATE_INVALID",
                       "The loan's payment_status is terminal and accepts no further writes.")


def require_serviceable(loan):
    if loan["payment_status"] == "DEFAULT":
        raise conflict("ERR_LOAN_NOT_SERVICEABLE",
                       "The loan is in DEFAULT and is no longer serviceable for this operation.")
