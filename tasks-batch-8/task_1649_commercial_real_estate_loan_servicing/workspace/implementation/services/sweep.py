"""The deterministic 7-step clock sweep (calculations.collection_cadence, PRD §3.7)."""
from datetime import timedelta

import db
from services import posture
from services.common import add_months_clamped, quarter_of, quarter_label, touch

RENT_ROLL_DUE_OFFSET_DAYS = 15
OP_STMT_DUE_OFFSET_DAYS = 45
MATURITY_RISK_WINDOW_DAYS = 180


def run_sweep():
    clock = db.get_clock()
    _step1_insurance_expiry(clock)
    _step2_estoppel_expiry(clock)
    _step3_option_expiry(clock)
    _step4_reporting_delinquency(clock)
    _step5_maturity_risk(clock)
    _step6_maturity_default(clock)
    # 7. risk re-eval for all loans, then servicing re-eval for all loans
    for loan in list(db.loans.values()):
        posture.reevaluate_risk(loan)
    for loan in list(db.loans.values()):
        posture.reevaluate_servicing(loan)


def _coverage_active_at(prop_id, coverage_type, moment):
    for p in db.insurance_policies.values():
        if (
            p["property_id"] == prop_id
            and p["coverage_type"] == coverage_type
            and p["status"] == "ACTIVE"
            and p["start_date_dt"] <= moment <= p["end_date_dt"]
        ):
            return True
    return False


def _has_active_entry(loan_id, criterion, source_ref=None):
    for e in db.watchlist_entries.values():
        if e["loan_id"] != loan_id or e["criterion"] != criterion or e["status"] != "ACTIVE":
            continue
        if source_ref is None or e["source_ref"] == source_ref:
            return True
    return False


def _step1_insurance_expiry(clock):
    for pol in list(db.insurance_policies.values()):
        if pol["status"] == "ACTIVE" and clock > pol["end_date_dt"]:
            pol["status"] = "EXPIRED"
            touch(pol)
            prop = db.properties.get(pol["property_id"])
            if not prop:
                continue
            if not _coverage_active_at(prop["id"], pol["coverage_type"], clock):
                loan = db.loans.get(prop["loan_id"])
                if loan and not _has_active_entry(loan["id"], "INSURANCE_LAPSE"):
                    posture.create_watchlist_entry(
                        loan, "INSURANCE_LAPSE",
                        source_ref=f"insurance policy {pol['id']}",
                    )


def _step2_estoppel_expiry(clock):
    for e in list(db.estoppels.values()):
        if e["status"] == "PENDING" and clock > e["due_date_dt"]:
            e["status"] = "EXPIRED"
            touch(e)
        elif e["status"] == "EXECUTED" and e.get("expires_at_dt") and clock > e["expires_at_dt"]:
            e["status"] = "EXPIRED"
            touch(e)


def _step3_option_expiry(clock):
    for o in list(db.extension_options.values()):
        if o["status"] == "AVAILABLE" and clock > o["exercise_window_end_dt"]:
            o["status"] = "EXPIRED"
            touch(o)


def _statement_due_date(stmt_type, period_end):
    offset = RENT_ROLL_DUE_OFFSET_DAYS if stmt_type == "RENT_ROLL" else OP_STMT_DUE_OFFSET_DAYS
    return period_end + timedelta(days=offset)


def _step4_reporting_delinquency(clock):
    for loan in list(db.loans.values()):
        orig = loan["origination_date_dt"]
        # Enumerate quarters from origination's quarter forward; expected when due_date < clock.
        qs, _ = quarter_of(orig)
        year, q = qs.year, (qs.month - 1) // 3
        # Guard against infinite loops: cap at 400 quarters.
        for _ in range(400):
            qstart = type(orig)(year, q * 3 + 1, 1, tzinfo=orig.tzinfo)
            _, qend = quarter_of(qstart)
            if qstart < orig:
                # Quarters whose period_start precedes origination_date are ignored.
                pass
            else:
                for stmt_type in ("RENT_ROLL", "OPERATING_STATEMENT"):
                    due = _statement_due_date(stmt_type, qend)
                    if due < clock:
                        _maybe_create_reporting_entry(loan, qstart, stmt_type)
            # advance quarter
            q += 1
            if q > 3:
                q = 0
                year += 1
            # Stop once the quarter's latest due date is still in the future.
            _, last_qend = quarter_of(qstart)
            if _statement_due_date("OPERATING_STATEMENT", last_qend) >= clock:
                break


def _maybe_create_reporting_entry(loan, qstart, stmt_type):
    label = f"period {quarter_label(qstart)} {stmt_type}"
    if _has_active_entry(loan["id"], "REPORTING_DELINQUENCY", source_ref=label):
        return
    qs, qe = quarter_of(qstart)
    for s in db.financial_statements.values():
        if (
            s["loan_id"] == loan["id"]
            and s["statement_type"] == stmt_type
            and s["status"] == "ACCEPTED"
            and s["period_start_dt"].date() == qs.date()
        ):
            return  # accepted statement exists for this quarter+type
    posture.create_watchlist_entry(loan, "REPORTING_DELINQUENCY", source_ref=label)


def _step5_maturity_risk(clock):
    for loan in list(db.loans.values()):
        delta_days = (loan["maturity_date_dt"] - clock).total_seconds() / 86400.0
        if not (0 <= delta_days <= MATURITY_RISK_WINDOW_DAYS):
            continue
        if loan["current_balance_cents"] <= 0:
            continue
        has_exercised = any(
            o["loan_id"] == loan["id"] and o["status"] == "EXERCISED"
            for o in db.extension_options.values()
        )
        if has_exercised:
            continue
        if _has_active_entry(loan["id"], "MATURITY_RISK"):
            continue
        posture.create_watchlist_entry(loan, "MATURITY_RISK", source_ref=None)


def _step6_maturity_default(clock):
    for loan in list(db.loans.values()):
        if (
            clock >= loan["maturity_date_dt"]
            and loan["current_balance_cents"] > 0
            and loan["payment_status"] in ("CURRENT", "DELINQUENT")
        ):
            loan["payment_status"] = "MATURITY_DEFAULT"
            touch(loan)
