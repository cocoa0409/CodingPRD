"""Daily mark-to-market run and month-end close."""

import db
import errors
from services import calculations as calc
from services.state_machines import (
    _post_ledger, _touch, _find_open_recall, _complete_recall,
    _settle_loan, cancel_loan, _accrue_pending_fail_fees,
)
from decimal import Decimal
from datetime import datetime, timedelta


def run_mark_to_market():
    """Daily batch for the current clock date. Returns summary dict."""
    today = db.current_date_str()
    result = {
        "as_of_date": today,
        "loans_accrued": 0,
        "margin_calls_issued": 0,
        "margin_calls_cured": 0,
        "margin_calls_escalated": 0,
        "requests_expired": 0,
        "recalls_failed": 0,
        "overrides_expired": 0,
    }

    # --- Provisional accruals ---
    for loan in list(db.loans.values()):
        if loan["status"] not in ("BOOKED", "RECALLED"):
            continue

        # Check if already accrued today
        already = any(
            e.get("loan_id") == loan["id"]
            and e.get("accrual_date") == today
            and e["entry_type"] in ("FEE_ACCRUAL_PROVISIONAL", "REBATE_ACCRUAL")
            for e in db.ledger_entries.values()
        )
        if already:
            continue

        sec = db.securities[loan["security_id"]]

        if loan["collateral_type"] == "SECURITIES":
            fee = calc.compute_daily_fee(loan["outstanding_quantity"], sec["price_cents"], loan["rate_bps"])
            # Track day inputs for exact month-end computation
            period = today[:7]
            if "_accrual_inputs" not in loan:
                loan["_accrual_inputs"] = {}
            if period not in loan["_accrual_inputs"]:
                loan["_accrual_inputs"][period] = []
            loan["_accrual_inputs"][period].append(
                (loan["outstanding_quantity"], sec["price_cents"], loan["rate_bps"])
            )
            if fee > 0:
                _post_ledger(
                    loan_id=loan["id"],
                    owner_id=loan["owner_id"],
                    entry_type="FEE_ACCRUAL_PROVISIONAL",
                    amount_cents=fee,
                    accrual_date=today,
                    note="daily_provisional",
                )
                result["loans_accrued"] += 1
        else:
            # CASH collateral -> rebate
            active_cash = sum(
                p["amount_cents"]
                for p in db.pledges.values()
                if p["loan_id"] == loan["id"] and p["status"] == "ACTIVE" and p["pledge_type"] == "CASH"
            )
            rebate = calc.compute_daily_rebate(active_cash, loan["rate_bps"])
            if rebate > 0:
                _post_ledger(
                    loan_id=loan["id"],
                    owner_id=loan["owner_id"],
                    entry_type="REBATE_ACCRUAL",
                    amount_cents=-rebate,  # negative = income owed to borrower
                    accrual_date=today,
                    note="daily_rebate",
                )
                result["loans_accrued"] += 1

    # --- Reinvestment income provisional ---
    for tranche in list(db.reinvestments.values()):
        if tranche["status"] != "INVESTED":
            continue
        already = any(
            e.get("loan_id") == tranche["loan_id"]
            and e.get("accrual_date") == today
            and e["entry_type"] == "REINVEST_INCOME_PROVISIONAL"
            for e in db.ledger_entries.values()
        )
        if already:
            continue
        loan = db.loans.get(tranche["loan_id"])
        if not loan:
            continue
        income = calc.compute_daily_reinvest_income(tranche["principal_cents"], tranche["stated_yield_bps"])
        if income > 0:
            _post_ledger(
                loan_id=loan["id"],
                owner_id=loan["owner_id"],
                entry_type="REINVEST_INCOME_PROVISIONAL",
                amount_cents=income,
                accrual_date=today,
                note="daily_reinvest_provisional",
            )

    # --- Margin call issue / refresh / cure / escalate ---
    for loan in list(db.loans.values()):
        if loan["status"] not in ("BOOKED", "RECALLED"):
            continue
        calc.recompute_loan_derived(loan)
        deficit = loan["required_collateral_cents"] - loan["posted_collateral_cents"]

        open_calls = [
            mc for mc in db.margin_calls.values()
            if mc["loan_id"] == loan["id"] and mc["status"] in ("OPEN", "ESCALATED")
        ]

        if deficit > 0:
            if not open_calls:
                # Issue new call
                mc = {
                    "id": db.new_id(),
                    "created_at": db.now_iso(),
                    "updated_at": db.now_iso(),
                    "version": 1,
                    "loan_id": loan["id"],
                    "amount_due_cents": deficit,
                    "issued_date": today,
                    "due_date": (db.clock.now().date() + timedelta(days=1)).strftime("%Y-%m-%d"),
                    "status": "OPEN",
                }
                db.margin_calls[mc["id"]] = mc
                result["margin_calls_issued"] += 1
                calc._recompute_margin_status(loan)
            else:
                for mc in open_calls:
                    if mc["status"] == "OPEN":
                        # Check escalation: past due_date with deficit persisting
                        if today > mc["due_date"]:
                            mc["status"] = "ESCALATED"
                            _touch(mc)
                            result["margin_calls_escalated"] += 1
                        else:
                            # Refresh amount
                            mc["amount_due_cents"] = deficit
                            _touch(mc)
        else:
            # Cure all open calls
            for mc in open_calls:
                mc["status"] = "CURED"
                _touch(mc)
                result["margin_calls_cured"] += 1
            calc._recompute_margin_status(loan)

    # --- Expire borrow requests ---
    for req in list(db.borrow_requests.values()):
        if req["status"] in ("SUBMITTED", "MATCHED") and req["needed_by_date"] < today:
            if req["status"] == "MATCHED":
                linked = None
                for loan in db.loans.values():
                    if loan.get("borrow_request_id") == req["id"] and loan["status"] in ("PROPOSED", "COUNTERED"):
                        linked = loan
                        break
                if linked:
                    cancel_loan(linked)
            req["status"] = "EXPIRED"
            _touch(req)
            result["requests_expired"] += 1

    # --- Fail recalls past deadline ---
    for recall in list(db.recalls.values()):
        if recall["status"] in ("ISSUED", "EXTENDED"):
            if today > recall["deadline_date"] and recall["delivered_quantity"] < recall["quantity"]:
                recall["status"] = "FAILED"
                loan = db.loans[recall["loan_id"]]
                sec = db.securities[loan["security_id"]]
                recall["fail_price_cents"] = sec["price_cents"]
                recall["_failed_date"] = today
                # Accrue fail fees for any late-delivery tranches that
                # landed before the snapshot existed.
                _accrue_pending_fail_fees(recall)
                _touch(recall)
                result["recalls_failed"] += 1

    # --- Expire limit overrides ---
    for ov in list(db.limit_overrides.values()):
        if ov["status"] == "APPROVED" and today >= ov["expires_at"]:
            ov["status"] = "EXPIRED"
            _touch(ov)
            borrower = db.borrowers[ov["borrower_id"]]
            calc.recompute_borrower_derived(borrower)
            result["overrides_expired"] += 1

    return result


def run_month_end_close(period):
    """Close a period: finalize accruals, post true-ups, run revenue split."""
    if period in db.period_closes:
        raise errors.make_error(errors.ERR_PERIOD_ALREADY_CLOSED, f"Period {period} already closed")

    # --- Finalize accruals per loan ---
    loans_finalized = 0
    loans_with_provisionals = set()
    for entry in db.ledger_entries.values():
        if entry.get("period") == period and entry["entry_type"] == "FEE_ACCRUAL_PROVISIONAL" and entry.get("loan_id"):
            loans_with_provisionals.add(entry["loan_id"])

    for loan_id in loans_with_provisionals:
        loan = db.loans.get(loan_id)
        if not loan:
            continue
        # Collect all provisional entries for this loan/period
        prov_entries = [
            e for e in db.ledger_entries.values()
            if e.get("loan_id") == loan_id
            and e.get("period") == period
            and e["entry_type"] == "FEE_ACCRUAL_PROVISIONAL"
        ]
        if not prov_entries:
            continue

        # Reconstruct day entries for exact total
        # Each provisional was: round_half_up(qty * price * rate / 10000 / 360)
        # We need the unrounded exact total. We stored the amount; we need to recompute.
        # We track the original inputs at time of accrual via stored fields.
        # For exactness, we store _day_inputs on the loan dict during accrual.
        day_inputs = loan.get("_accrual_inputs", {}).get(period, [])
        if day_inputs:
            exact_total = calc.compute_period_fee_exact(day_inputs)
        else:
            # Fallback: sum provisionals (shouldn't happen in normal flow)
            exact_total = Decimal(sum(e["amount_cents"] for e in prov_entries))

        final_fee = calc.round_half_up_cents(exact_total)
        prov_sum = sum(e["amount_cents"] for e in prov_entries)
        true_up = final_fee - prov_sum

        _post_ledger(
            loan_id=loan_id,
            owner_id=loan["owner_id"],
            entry_type="FEE_ACCRUAL_FINAL",
            amount_cents=final_fee,
            accrual_date=db.current_date_str(),
            note="month_end_final",
        )
        _post_ledger(
            loan_id=loan_id,
            owner_id=loan["owner_id"],
            entry_type="FEE_TRUE_UP",
            amount_cents=true_up,
            accrual_date=db.current_date_str(),
            note="true_up",
        )
        loans_finalized += 1

    # --- Revenue split per owner ---
    for owner in db.beneficial_owners.values():
        owner_share, agent_share, net_pool = calc.compute_revenue_split(owner, period)
        if net_pool != 0 or owner_share != 0 or agent_share != 0:
            _post_ledger(
                loan_id=None,
                owner_id=owner["id"],
                entry_type="REVENUE_SPLIT_OWNER",
                amount_cents=owner_share,
                accrual_date=db.current_date_str(),
                note=f"revenue_split_{period}",
            )
            _post_ledger(
                loan_id=None,
                owner_id=owner["id"],
                entry_type="REVENUE_SPLIT_AGENT",
                amount_cents=agent_share,
                accrual_date=db.current_date_str(),
                note=f"revenue_split_{period}",
            )

    # --- Record the close ---
    close = {
        "id": period,
        "created_at": db.now_iso(),
        "period": period,
        "loans_finalized_count": loans_finalized,
        "status": "CLOSED",
    }
    db.period_closes[period] = close
    return close
