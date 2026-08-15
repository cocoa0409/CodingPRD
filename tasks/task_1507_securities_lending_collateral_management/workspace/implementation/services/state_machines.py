"""State machine transitions and cascade side effects."""

import db
import errors
from services import calculations as calc
from datetime import datetime, timedelta


def _touch(entity):
    entity["updated_at"] = db.now_iso()
    entity["version"] = entity.get("version", 0) + 1


def _post_ledger(loan_id, owner_id, entry_type, amount_cents, accrual_date, note=""):
    period = accrual_date[:7]  # YYYY-MM
    entry = {
        "id": db.new_id(),
        "created_at": db.now_iso(),
        "loan_id": loan_id,
        "owner_id": owner_id,
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "accrual_date": accrual_date,
        "period": period,
        "note": note,
    }
    db.ledger_entries[entry["id"]] = entry
    return entry


# ---------------------------------------------------------------------------
# Loan booking (accept / confirm share the same logic)
# ---------------------------------------------------------------------------

def book_loan(loan):
    """Shared booking logic for accept and confirm."""
    position = db.lendable_positions[loan["position_id"]]
    borrower = db.borrowers[loan["borrower_id"]]
    owner = db.beneficial_owners[loan["owner_id"]]
    security = db.securities[loan["security_id"]]

    # Preconditions (priority order from scaffold §1.4)
    if borrower["status"] != "ACTIVE":
        raise errors.make_error(errors.ERR_BORROWER_SUSPENDED, "Borrower is not ACTIVE")
    if owner["status"] != "ACTIVE":
        raise errors.make_error(errors.ERR_OWNER_SUSPENDED, "Owner is not ACTIVE")
    if security["status"] != "LENDABLE":
        raise errors.make_error(errors.ERR_SECURITY_HALTED, "Security is HALTED")
    if position["status"] != "OPEN":
        raise errors.make_error(errors.ERR_POSITION_SUSPENDED, "Position is not OPEN")

    # Forward capacity (exclude own reservation — booking is bucket-neutral)
    if not calc.check_forward_capacity(position, 0, loan.get("term_days"), exclude_loan_id=loan["id"]):
        raise errors.make_error(errors.ERR_FORWARD_CAPACITY_EXCEEDED, "Forward capacity exceeded")

    # Utilization gate
    calc.recompute_borrower_derived(borrower)
    new_value = loan["quantity"] * security["price_cents"]
    prospective_bps = calc.compute_utilization_bps(
        borrower["id"], borrower["effective_limit_cents"], additional_value=new_value
    )
    if prospective_bps >= 9000:
        raise errors.make_error(errors.ERR_CREDIT_LIMIT_EXCEEDED, "Prospective utilization >= 9000 bps")

    # Side effects
    loan["status"] = "BOOKED"
    loan["original_price_cents"] = security["price_cents"]
    loan["_window_start_date"] = db.clock.now().date()
    _touch(loan)

    # Position: reserved -> on_loan
    position["quantity_reserved"] -= loan["quantity"]
    position["quantity_on_loan"] += loan["quantity"]
    position["quantity_available"] = position["quantity_total"] - position["quantity_reserved"] - position["quantity_on_loan"]
    _touch(position)

    # Linked borrow request
    if loan.get("borrow_request_id"):
        req = db.borrow_requests.get(loan["borrow_request_id"])
        if req and req["status"] == "MATCHED":
            req["status"] = "LOANED"
            _touch(req)

    calc.recompute_loan_derived(loan)
    calc.recompute_borrower_derived(borrower)


# ---------------------------------------------------------------------------
# Loan cancel
# ---------------------------------------------------------------------------

def cancel_loan(loan):
    """Cancel a PROPOSED or COUNTERED loan."""
    position = db.lendable_positions[loan["position_id"]]
    loan["status"] = "CANCELLED"
    _touch(loan)

    position["quantity_reserved"] -= loan["quantity"]
    position["quantity_available"] = position["quantity_total"] - position["quantity_reserved"] - position["quantity_on_loan"]
    _touch(position)

    # If linked to a borrow request, return it to SUBMITTED
    if loan.get("borrow_request_id"):
        req = db.borrow_requests.get(loan["borrow_request_id"])
        if req and req["status"] == "MATCHED":
            req["status"] = "SUBMITTED"
            _touch(req)


# ---------------------------------------------------------------------------
# Loan return (settlement cascade)
# ---------------------------------------------------------------------------

def return_shares(loan, return_qty):
    """Process a return of shares against a BOOKED or RECALLED loan."""
    if return_qty > loan["outstanding_quantity"]:
        raise errors.make_error(errors.ERR_RETURN_EXCEEDS_LOAN, "Return quantity exceeds outstanding")

    loan["outstanding_quantity"] -= return_qty
    _touch(loan)

    # Absorb into open recall first
    open_recall = _find_open_recall(loan["id"])
    if open_recall:
        remaining = open_recall["quantity"] - open_recall["delivered_quantity"]
        absorbed = min(return_qty, remaining)
        open_recall["delivered_quantity"] += absorbed
        # Track the delivery tranche (date + shares). Fail fees are computed
        # per tranche using the recall's fail_price_cents once known — either
        # immediately (if recall already FAILED) or at failure/completion.
        tranche = {"date": db.current_date_str(), "shares": absorbed}
        open_recall.setdefault("_delivery_tranches", []).append(tranche)
        # If fail_price_cents is already known (recall already FAILED),
        # accrue the fee for this tranche immediately.
        if open_recall.get("fail_price_cents") is not None:
            deadline = datetime.strptime(open_recall["deadline_date"], "%Y-%m-%d").date()
            delivery_date = db.clock.now().date()
            fee_days = max(0, (delivery_date - deadline).days)
            fee = calc.compute_fail_fee_for_tranche(absorbed, open_recall["fail_price_cents"], fee_days)
            open_recall["fail_fee_cents"] += fee
            tranche["_fee_accrued"] = True
        _touch(open_recall)

        if open_recall["delivered_quantity"] >= open_recall["quantity"]:
            _accrue_pending_fail_fees(open_recall)
            _complete_recall(open_recall)

    if loan["outstanding_quantity"] == 0:
        _settle_loan(loan)
    else:
        calc.recompute_loan_derived(loan)


def _settle_loan(loan):
    """Settlement cascade: pledges RELEASED, tranches UNWOUND, calls CURED.

    Caller is responsible for bumping the loan's version (each settlement is
    part of a single mutation — a return that settles, or a buy-in that
    settles, increments version exactly once at the entry point).
    """
    position = db.lendable_positions[loan["position_id"]]
    loan["status"] = "SETTLED"
    loan["updated_at"] = db.now_iso()

    # Position
    position["quantity_on_loan"] -= loan["quantity"]
    position["quantity_available"] = position["quantity_total"] - position["quantity_reserved"] - position["quantity_on_loan"]
    _touch(position)

    # Release all ACTIVE pledges
    for p in db.pledges.values():
        if p["loan_id"] == loan["id"] and p["status"] == "ACTIVE":
            p["status"] = "RELEASED"
            _touch(p)

    # Unwind all INVESTED tranches
    for t in db.reinvestments.values():
        if t["loan_id"] == loan["id"] and t["status"] == "INVESTED":
            _unwind_tranche(t, loan)

    # Cure all open margin calls
    for mc in db.margin_calls.values():
        if mc["loan_id"] == loan["id"] and mc["status"] in ("OPEN", "ESCALATED"):
            mc["status"] = "CURED"
            mc["note"] = "settled"
            _touch(mc)

    calc.recompute_loan_derived(loan)
    calc.recompute_borrower_derived(db.borrowers[loan["borrower_id"]])


def _accrue_pending_fail_fees(recall):
    """Accrue fail fees for delivery tranches that landed before the recall
    had a fail_price_cents snapshot (i.e., before the run moved it to FAILED).

    PRD §3.7: "Fail fees then accrue per delivery tranche: for shares
    delivered — or bought in — on a given date, the chargeable days are the
    calendar days from the `deadline_date` to that date, floored at zero."
    """
    if recall.get("fail_price_cents") is None:
        return
    deadline = datetime.strptime(recall["deadline_date"], "%Y-%m-%d").date()
    for tranche in recall.get("_delivery_tranches", []):
        if tranche.get("_fee_accrued"):
            continue
        delivery_date = datetime.strptime(tranche["date"], "%Y-%m-%d").date()
        fee_days = max(0, (delivery_date - deadline).days)
        fee = calc.compute_fail_fee_for_tranche(
            tranche["shares"], recall["fail_price_cents"], fee_days)
        recall["fail_fee_cents"] += fee
        tranche["_fee_accrued"] = True


def _complete_recall(recall):
    """Recall COMPLETED — finalize fail fees."""
    recall["status"] = "COMPLETED"
    _touch(recall)
    if recall["fail_fee_cents"] > 0:
        loan = db.loans[recall["loan_id"]]
        _post_ledger(
            loan_id=loan["id"],
            owner_id=loan["owner_id"],
            entry_type="FAIL_FEE",
            amount_cents=-recall["fail_fee_cents"],  # charged to borrower = negative
            accrual_date=db.current_date_str(),
            note="recall_completed",
        )


def _find_open_recall(loan_id):
    for r in db.recalls.values():
        if r["loan_id"] == loan_id and r["status"] in ("ISSUED", "EXTENDED", "FAILED"):
            return r
    return None


# ---------------------------------------------------------------------------
# Default cascade
# ---------------------------------------------------------------------------

def default_loan(loan):
    """Fire the full default cascade for a single loan."""
    position = db.lendable_positions[loan["position_id"]]
    owner = db.beneficial_owners[loan["owner_id"]]

    loan["status"] = "DEFAULTED"
    _touch(loan)

    # Seize all ACTIVE pledges
    seized_values = []
    for p in db.pledges.values():
        if p["loan_id"] == loan["id"] and p["status"] == "ACTIVE":
            p["status"] = "SEIZED"
            p["marked_value_cents"] = calc.compute_pledge_marked_value(p)
            seized_values.append(p["marked_value_cents"])
            _touch(p)
            _post_ledger(
                loan_id=loan["id"],
                owner_id=loan["owner_id"],
                entry_type="COLLATERAL_SEIZURE",
                amount_cents=p["marked_value_cents"],
                accrual_date=db.current_date_str(),
                note="default_seizure",
            )

    # Unwind all INVESTED tranches
    for t in db.reinvestments.values():
        if t["loan_id"] == loan["id"] and t["status"] == "INVESTED":
            _unwind_tranche(t, loan)

    # Indemnity credit
    if owner["indemnification_opt_in"]:
        shortfall = calc.compute_indemnity_shortfall(loan, seized_values)
        if shortfall > 0:
            _post_ledger(
                loan_id=loan["id"],
                owner_id=loan["owner_id"],
                entry_type="INDEMNITY_CREDIT",
                amount_cents=shortfall,
                accrual_date=db.current_date_str(),
                note="indemnity_shortfall",
            )

    # Position: release on-loan quantity
    position["quantity_on_loan"] -= loan["outstanding_quantity"]
    position["quantity_available"] = position["quantity_total"] - position["quantity_reserved"] - position["quantity_on_loan"]
    _touch(position)

    # Cancel open recall
    open_recall = _find_open_recall(loan["id"])
    if open_recall:
        open_recall["status"] = "CANCELLED"
        _touch(open_recall)

    # Cure open margin calls
    for mc in db.margin_calls.values():
        if mc["loan_id"] == loan["id"] and mc["status"] in ("OPEN", "ESCALATED"):
            mc["status"] = "DEFAULTED"
            _touch(mc)

    calc.recompute_loan_derived(loan)
    calc.recompute_borrower_derived(db.borrowers[loan["borrower_id"]])


# ---------------------------------------------------------------------------
# Tranche unwind
# ---------------------------------------------------------------------------

def _unwind_tranche(tranche, loan):
    """Unwind a reinvestment tranche."""
    tranche["status"] = "UNWOUND"
    tranche["realized_income_cents"] = tranche["current_nav_cents"] - tranche["principal_cents"]
    _touch(tranche)

    _post_ledger(
        loan_id=loan["id"],
        owner_id=loan["owner_id"],
        entry_type="REINVEST_INCOME_FINAL",
        amount_cents=tranche["realized_income_cents"],
        accrual_date=db.current_date_str(),
        note="tranche_unwind",
    )

    # Return principal to uninvested cash
    loan["cash_uninvested_cents"] = loan.get("cash_uninvested_cents", 0) + tranche["principal_cents"]


# ---------------------------------------------------------------------------
# Borrower default cascade
# ---------------------------------------------------------------------------

def default_borrower(borrower):
    """Four-link cascade for borrower default."""
    borrower["status"] = "DEFAULTED"
    _touch(borrower)

    # Link 1: Default all BOOKED/RECALLED loans
    for loan in db.loans.values():
        if loan["borrower_id"] == borrower["id"] and loan["status"] in ("BOOKED", "RECALLED"):
            default_loan(loan)

    # Cancel SUBMITTED and MATCHED borrow requests
    for req in db.borrow_requests.values():
        if req["borrower_id"] != borrower["id"]:
            continue
        if req["status"] == "SUBMITTED":
            req["status"] = "CANCELLED"
            _touch(req)
        elif req["status"] == "MATCHED":
            # Cancel the linked proposal and release reservation
            linked = _find_linked_proposal(req["id"])
            if linked:
                cancel_loan(linked)
            req["status"] = "CANCELLED"
            _touch(req)

    calc.recompute_borrower_derived(borrower)


def _find_linked_proposal(request_id):
    for loan in db.loans.values():
        if loan.get("borrow_request_id") == request_id and loan["status"] in ("PROPOSED", "COUNTERED"):
            return loan
    return None


# ---------------------------------------------------------------------------
# Security halt cascade
# ---------------------------------------------------------------------------

def halt_security(security):
    """Three-link halt cascade."""
    security["status"] = "HALTED"
    _touch(security)

    # Cancel SUBMITTED/MATCHED borrow requests for this security
    for req in db.borrow_requests.values():
        if req["security_id"] == security["id"] and req["status"] in ("SUBMITTED", "MATCHED"):
            if req["status"] == "MATCHED":
                linked = _find_linked_proposal(req["id"])
                if linked:
                    cancel_loan(linked)
            req["status"] = "CANCELLED"
            _touch(req)

    # Cancel PROPOSED/COUNTERED loans for this security (including direct ones)
    for loan in db.loans.values():
        if loan["security_id"] == security["id"] and loan["status"] in ("PROPOSED", "COUNTERED"):
            cancel_loan(loan)


# ---------------------------------------------------------------------------
# Owner offboard
# ---------------------------------------------------------------------------

def offboard_owner(owner):
    """Offboard owner, suspending all OPEN positions."""
    owner["status"] = "OFFBOARDED"
    _touch(owner)
    for pos in db.lendable_positions.values():
        if pos["owner_id"] == owner["id"] and pos["status"] == "OPEN":
            pos["status"] = "SUSPENDED"
            _touch(pos)


# ---------------------------------------------------------------------------
# Borrower suspend
# ---------------------------------------------------------------------------

def suspend_borrower(borrower):
    borrower["status"] = "SUSPENDED"
    _touch(borrower)
    for req in db.borrow_requests.values():
        if req["borrower_id"] == borrower["id"] and req["status"] == "SUBMITTED":
            req["status"] = "CANCELLED"
            _touch(req)
