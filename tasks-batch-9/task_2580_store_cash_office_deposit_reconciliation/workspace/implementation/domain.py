"""Lookups, derived aggregates, the safe ledger and the journal compound derivation."""
import calc
import clock
import db
from errors import err

OPEN_CASE_STATUSES = ("OPEN", "RESEARCHING", "ESCALATED")
TERMINAL_CASE_STATUSES = ("EXPLAINED", "CLOSED_SUBSTANTIATED", "CLOSED_UNSUBSTANTIATED")
DEPOSIT_PRESENT_STATUSES = ("SEALED", "SCHEDULED", "IN_TRANSIT", "RECONCILED")
DROP_TXN_TYPES = ("MID_SHIFT_DROP", "CLOSING_DROP")


# --------------------------------------------------------------------------
# existence resolution
# --------------------------------------------------------------------------
def _lookup(collection, record_id, error_id):
    if not isinstance(record_id, str):
        raise err(error_id, "record %r does not exist" % (record_id,))
    record = collection.get(record_id)
    if record is None:
        raise err(error_id, "record %s does not exist" % record_id)
    return record


def get_store(store_id):
    return _lookup(db.stores, store_id, "ERR_STORE_NOT_FOUND")


def get_cashier(cashier_id):
    return _lookup(db.cashiers, cashier_id, "ERR_CASHIER_NOT_FOUND")


def get_safe(safe_id):
    return _lookup(db.safes, safe_id, "ERR_SAFE_NOT_FOUND")


def get_journal(journal_id):
    return _lookup(db.sales_journals, journal_id, "ERR_SALES_JOURNAL_NOT_FOUND")


def get_session(session_id):
    return _lookup(db.till_sessions, session_id, "ERR_TILL_SESSION_NOT_FOUND")


def get_txn(txn_id):
    return _lookup(db.safe_transactions, txn_id, "ERR_SAFE_TRANSACTION_NOT_FOUND")


def get_deposit(deposit_id):
    return _lookup(db.deposits, deposit_id, "ERR_DEPOSIT_NOT_FOUND")


def get_credit_record(record_id):
    return _lookup(db.bank_credit_records, record_id, "ERR_BANK_CREDIT_RECORD_NOT_FOUND")


def get_settlement(settlement_id):
    return _lookup(db.card_settlements, settlement_id, "ERR_CARD_SETTLEMENT_NOT_FOUND")


def get_case(case_id):
    return _lookup(db.variance_cases, case_id, "ERR_VARIANCE_CASE_NOT_FOUND")


def get_change_order(order_id):
    return _lookup(db.change_orders, order_id, "ERR_CHANGE_ORDER_NOT_FOUND")


def store_of_safe(safe):
    return db.stores.get(safe["store_id"])


def store_of_journal(journal):
    return db.stores.get(journal["store_id"])


def store_of_case(case):
    journal = db.sales_journals.get(case["sales_journal_id"])
    if journal is None:
        return None
    return db.stores.get(journal["store_id"])


def earliest_safe(store_id):
    candidates = [s for s in db.ordered(db.safes) if s["store_id"] == store_id]
    return candidates[0] if candidates else None


# --------------------------------------------------------------------------
# safe ledger
# --------------------------------------------------------------------------
def safe_rows(safe_id):
    return [r for r in db.ordered(db.safe_transactions) if r["safe_id"] == safe_id]


def safe_balance(safe_id):
    """Full recompute over every ledger row of the safe; no status filter."""
    return sum(calc.effective_amount(row) for row in safe_rows(safe_id))


def safe_provisional_credit_balance(safe_id):
    total = 0
    for deposit in db.ordered(db.deposits):
        if deposit["safe_id"] != safe_id:
            continue
        if deposit["status"] in ("RECONCILED", "VOIDED"):
            continue
        for record in db.ordered(db.bank_credit_records):
            if record["deposit_id"] == deposit["id"] and record["credit_type"] == "PROVISIONAL":
                total += record["amount_cents"]
    return total


def safe_suspect_note_cents(safe_id):
    total = 0
    for deposit in db.ordered(db.deposits):
        if deposit["safe_id"] != safe_id:
            continue
        if deposit["deposit_type"] != "SMART_SAFE":
            continue
        if deposit["status"] in ("RECONCILED", "VOIDED"):
            continue
        total += deposit["suspect_note_cents"] or 0
    return total


def write_txn(safe_id, txn_type, declared_amount_cents, actor_user_id, memo,
              till_session_id=None, deposit_id=None, change_order_id=None,
              verified_amount_cents=None):
    row = db.base_record(with_version=False)
    row.update(
        {
            "safe_id": safe_id,
            "till_session_id": till_session_id,
            "deposit_id": deposit_id,
            "change_order_id": change_order_id,
            "txn_type": txn_type,
            "declared_amount_cents": declared_amount_cents,
            "verified_amount_cents": verified_amount_cents,
            "actor_user_id": actor_user_id,
            "occurred_at": clock.now(),
            "memo": memo,
        }
    )
    db.safe_transactions[row["id"]] = row
    return row


# --------------------------------------------------------------------------
# till session drop aggregates
# --------------------------------------------------------------------------
def session_drop_rows(session_id):
    return [
        r
        for r in db.ordered(db.safe_transactions)
        if r["till_session_id"] == session_id and r["txn_type"] in DROP_TXN_TYPES
    ]


def dropped_declared_cents(session_id):
    return sum(r["declared_amount_cents"] for r in session_drop_rows(session_id))


def dropped_verified_cents(session_id):
    """Null while any drop row of the session is still unverified, and null when
    the session has no drop rows at all (nothing has been re-counted)."""
    rows = session_drop_rows(session_id)
    if not rows:
        return None
    total = 0
    for row in rows:
        if row["verified_amount_cents"] is None:
            return None
        total += row["verified_amount_cents"]
    return total


# --------------------------------------------------------------------------
# variance case aggregates
# --------------------------------------------------------------------------
def bucket_total(case, bucket):
    return sum(
        entry["amount_cents"] for entry in case["attributions"] if entry["bucket"] == bucket
    )


def unexplained_cents(case):
    attributed = sum(bucket_total(case, bucket) for bucket in calc.ATTRIBUTION_BUCKETS)
    return case["total_variance_cents"] - attributed


def journal_open_cases(journal_id):
    return [
        c
        for c in db.ordered(db.variance_cases)
        if c["sales_journal_id"] == journal_id and c["status"] in OPEN_CASE_STATUSES
    ]


def journal_open_case_count(journal_id):
    return len(journal_open_cases(journal_id))


def journal_net_unexplained_cents(journal_id):
    return sum(unexplained_cents(c) for c in journal_open_cases(journal_id))


def cashier_open_case_count(cashier_id):
    return len(
        [
            c
            for c in db.variance_cases.values()
            if c["cashier_id"] == cashier_id and c["status"] in OPEN_CASE_STATUSES
        ]
    )


# --------------------------------------------------------------------------
# sales journal derived figures and the compound derivation
# --------------------------------------------------------------------------
def journal_sessions(journal_id):
    return [s for s in db.ordered(db.till_sessions) if s["sales_journal_id"] == journal_id]


def journal_session_count(journal_id):
    return len(journal_sessions(journal_id))


def journal_reconciled_sessions(journal_id):
    return [s for s in journal_sessions(journal_id) if s["status"] == "RECONCILED"]


def journal_settlements(journal_id):
    return [s for s in db.ordered(db.card_settlements) if s["sales_journal_id"] == journal_id]


def journal_deposits(journal_id):
    return [d for d in db.ordered(db.deposits) if d["sales_journal_id"] == journal_id]


def journal_register_cash_tieout_cents(journal):
    posted = journal["journal_cash_sales_cents"] or 0
    total = sum(
        (s["pos_cash_sales_cents"] or 0) for s in journal_reconciled_sessions(journal["id"])
    )
    return total - posted


def journal_settlement_variance_total_cents(journal_id):
    return sum(abs(s["settlement_variance_cents"]) for s in journal_settlements(journal_id))


def journal_structurally_complete(journal):
    if journal["status"] not in ("TENDERS_POSTED", "OUT_OF_BALANCE"):
        return False
    session_count = journal_session_count(journal["id"])
    if session_count < 1:
        return False
    if len(journal_reconciled_sessions(journal["id"])) != session_count:
        return False
    if len(journal_settlements(journal["id"])) < 1:
        return False
    for deposit in journal_deposits(journal["id"]):
        if deposit["status"] in DEPOSIT_PRESENT_STATUSES:
            return True
    return False


def journal_balanced(journal):
    return (
        journal_register_cash_tieout_cents(journal) == 0
        and journal_settlement_variance_total_cents(journal["id"]) == 0
        and journal_open_case_count(journal["id"]) == 0
    )


def reevaluate_journal(journal):
    """Compound derivation of PRD section 3.1. BALANCED is terminal."""
    if journal is None:
        return
    if journal["status"] not in ("TENDERS_POSTED", "OUT_OF_BALANCE"):
        return
    if not journal_structurally_complete(journal):
        return
    target = "BALANCED" if journal_balanced(journal) else "OUT_OF_BALANCE"
    if journal["status"] != target:
        journal["status"] = target


# --------------------------------------------------------------------------
# safe posture fan-out
# --------------------------------------------------------------------------
def store_has_escalated_case(store_id):
    for case in db.variance_cases.values():
        if case["status"] != "ESCALATED":
            continue
        journal = db.sales_journals.get(case["sales_journal_id"])
        if journal is not None and journal["store_id"] == store_id:
            return True
    return False


def freeze_store_safes(store_id):
    for safe in db.ordered(db.safes):
        if safe["store_id"] != store_id:
            continue
        if safe["posture"] != "FROZEN":
            safe["posture"] = "FROZEN"
            db.touch(safe)


def restore_store_safes(store_id):
    for safe in db.ordered(db.safes):
        if safe["store_id"] != store_id:
            continue
        if safe["posture"] != "OPEN":
            safe["posture"] = "OPEN"
            db.touch(safe)


# --------------------------------------------------------------------------
# cashier rolling window (calculations.cashier_rolling_variance)
# --------------------------------------------------------------------------
def recompute_rolling(cashier, store):
    window_end = clock.now()
    window_start = clock.plus_days(window_end, -store["rolling_window_days"])
    selected = []
    for session in db.ordered(db.till_sessions):
        if session["cashier_id"] != cashier["id"]:
            continue
        if session["status"] != "RECONCILED":
            continue
        stamp = session["updated_at"]
        if stamp is None or stamp < window_start or stamp > window_end:
            continue
        selected.append(session)
    cashier["reconciled_session_count"] = len(selected)
    cashier["rolling_absolute_variance_cents"] = sum(
        abs(s["variance_cents"] or 0) for s in selected
    )
    cashier["rolling_net_variance_cents"] = sum((s["variance_cents"] or 0) for s in selected)
    return selected


# --------------------------------------------------------------------------
# variance case opening (calculations.variance_case_opening)
# --------------------------------------------------------------------------
def open_variance_case(case_type, sales_journal_id, total_variance_cents, store,
                       cashier_id=None, deposit_id=None):
    case = db.base_record()
    case.update(
        {
            "sales_journal_id": sales_journal_id,
            "cashier_id": cashier_id,
            "deposit_id": deposit_id,
            "case_type": case_type,
            "status": "OPEN",
            "total_variance_cents": total_variance_cents,
            "attributions": [],
            "suspected_theft": total_variance_cents >= store["theft_escalation_threshold_cents"],
            "escalated_by_user_id": None,
            "disposition": None,
            "closing_note": None,
        }
    )
    db.variance_cases[case["id"]] = case
    return case
