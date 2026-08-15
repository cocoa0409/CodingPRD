"""Business logic (PRD §3): matching cascade, payee scoring, decision
deadlines, exception lifecycle, settlement ledger, fees, sweeps, billing,
liability, adoption metrics — plus serializers for every entity."""
import hashlib
import json
import re
from datetime import datetime, timedelta

import clock
import store
from util import bump, new_record, period_of, round_half_up_int, serialize

UTC = clock.UTC

# ---------------------------------------------------------------------------
# constants (PRD §3 / scaffold calculations)
# ---------------------------------------------------------------------------
TIERS = ["POSITIVE_PAY", "PAYEE_POSITIVE_PAY", "REVERSE_POSITIVE_PAY"]
DEFAULT_DECISIONS = ["PAY", "RETURN"]
DEADLINE_MODES = ["SAME_DAY_CUTOFF", "ROLLING_HOURS"]
USER_ROLES = ["ADMIN", "MANAGER", "DECISION_MAKER", "VIEWER"]
CHANNELS = ["TELLER", "REMOTE_DEPOSIT", "CLEARING"]
RULE_TYPES = ["BLOCK", "FILTER"]
SEC_CODES = ["CCD", "PPD", "WEB", "TEL"]
CLAIM_REASONS = ["FORGED_SIGNATURE", "ALTERED_AMOUNT", "COUNTERFEIT", "UNAUTHORIZED_PAYEE"]
RESOLUTIONS = ["BANK_LIABLE", "CUSTOMER_LIABLE", "SHARED"]
OPS_KINDS = ["DAILY_SWEEP", "MONTHLY_BILLING"]

PROVISIONAL_EXCEPTION_FEE_CENTS = 200
RETURN_FEE_CENTS = 500
MONTHLY_MINIMUM_CENTS = 5000
TIER1_LIMIT = 10
TIER1_FEE_CENTS = 200
TIER2_LIMIT = 40
TIER2_FEE_CENTS = 150
TIER3_FEE_CENTS = 100
CLAIM_WINDOW_DAYS = 30
PROVISIONAL_CREDIT_CAP_CENTS = 25000
SOD_CASE_THRESHOLD_CENTS = 25000
WAIVER_AUTHORITY_CAP_CENTS = 1000
REVERSE_VOLUME_MAX_90D = 75
REVERSE_WINDOW_DAYS = 90
CUTOFF_HOUR = 14
SAME_DAY_DEADLINE_HOUR = 20
TRAINING_BUFFER_MINUTES = 30
EXTEND_WINDOW_HOURS = 24

RESOLVED_CASE_STATUSES = ["RESOLVED_BANK_LIABLE", "RESOLVED_CUSTOMER_LIABLE", "RESOLVED_SHARED"]


# ---------------------------------------------------------------------------
# enrollment helpers / computed counters (PRD §2.4: computed counters do NOT
# bump version)
# ---------------------------------------------------------------------------
def open_exception_count(enrollment_id):
    return sum(
        1
        for e in store.exceptions.values()
        if e["enrollment_id"] == enrollment_id and e["status"] == "OPEN"
    )


def provisional_credit_outstanding(enrollment_id):
    return sum(
        c["provisional_credit_cents"]
        for c in store.cases.values()
        if c["enrollment_id"] == enrollment_id and c["status"] == "UNDER_REVIEW"
    )


def ytd_bank_loss(enrollment_id):
    year = clock.now().year
    total = 0
    for c in store.cases.values():
        if (
            c["enrollment_id"] == enrollment_id
            and c["status"] in RESOLVED_CASE_STATUSES
            and c.get("resolved_at") is not None
            and c["resolved_at"].year == year
        ):
            total += c["bank_liability_cents"] or 0
    return total


def account_enrollment_id(account):
    return account["enrollment_id"]


def check_enrollment_id(check):
    return store.accounts[check["account_id"]]["enrollment_id"]


def item_enrollment_id(item):
    return store.accounts[item["account_id"]]["enrollment_id"]


def rule_enrollment_id(rule):
    return store.accounts[rule["account_id"]]["enrollment_id"]


def guard_enrollment_mutable(enr):
    """Outermost state precondition: mutations against a TERMINATED enrollment."""
    if enr["status"] == "TERMINATED":
        from errors import ERR_ENROLLMENT_TERMINATED, raise_err

        raise_err(ERR_ENROLLMENT_TERMINATED, "Enrollment is TERMINATED")


def guard_enrollment_active(enr):
    """Enrollment-state precedence: TERMINATED beats not-active (PRD §2.10 p7)."""
    from errors import ERR_ENROLLMENT_NOT_ACTIVE, raise_err

    guard_enrollment_mutable(enr)
    if enr["status"] != "ACTIVE":
        raise_err(ERR_ENROLLMENT_NOT_ACTIVE, "Enrollment is not ACTIVE")


# ---------------------------------------------------------------------------
# serializers
# ---------------------------------------------------------------------------
ENROLLMENT_FIELDS = [
    "business_name", "tier", "default_decision", "deadline_mode",
    "decision_window_hours", "amount_tolerance_cents", "payee_score_threshold",
    "stale_days", "loss_suspension_threshold_cents", "status",
]


def enrollment_out(e):
    data = serialize(e, ["id"] + ENROLLMENT_FIELDS + ["created_at", "updated_at", "version"])
    data["open_exception_count"] = open_exception_count(e["id"])
    data["provisional_credit_outstanding_cents"] = provisional_credit_outstanding(e["id"])
    data["ytd_bank_loss_cents"] = ytd_bank_loss(e["id"])
    return data


def user_out(u):
    return serialize(u, ["id", "enrollment_id", "display_name", "user_role",
                         "created_at", "updated_at", "version"])


def account_out(a):
    return serialize(a, ["id", "enrollment_id", "account_number",
                         "payment_review_threshold_cents", "status",
                         "cumulative_paid_cents", "cumulative_reversed_cents",
                         "net_settled_cents", "created_at", "updated_at", "version"])


def upload_out(f):
    return serialize(f, ["id", "enrollment_id", "account_id", "uploaded_by_user_id",
                         "file_reference", "payload_hash", "row_count",
                         "accepted_row_count", "rejected_row_count", "row_errors",
                         "status", "created_at", "updated_at", "version"])


def check_out(c):
    return serialize(c, ["id", "account_id", "issue_file_id", "check_number",
                         "amount_cents", "payee_name", "issue_date", "status",
                         "consumed_by_item_id", "created_at", "updated_at", "version"])


def item_out(i):
    return serialize(i, ["id", "account_id", "check_number", "amount_cents",
                         "payee_name_raw", "channel", "presented_at",
                         "idempotency_key", "status", "match_result", "match_score",
                         "exception_id", "paid_at", "created_at", "updated_at",
                         "version"])


def exception_out(e):
    return serialize(e, ["id", "enrollment_id", "account_id", "presented_item_id",
                         "issued_check_id", "reason", "status",
                         "default_decision_snapshot", "decision_deadline_at",
                         "extended_once", "decided_by_user_id", "decided_at",
                         "liability_party", "fee_entry_id",
                         "created_at", "updated_at", "version"])


def rule_out(r):
    return serialize(r, ["id", "account_id", "rule_type", "originator_company_id",
                         "sec_code", "max_amount_cents", "effective_start_date",
                         "effective_end_date", "status",
                         "created_at", "updated_at", "version"])


def fee_out(f):
    return serialize(f, ["id", "enrollment_id", "exception_id", "period",
                         "fee_type", "amount_cents", "status", "waived_from_status",
                         "waived_by", "waiver_reason",
                         "created_at", "updated_at", "version"])


def case_out(c):
    return serialize(c, ["id", "enrollment_id", "presented_item_id",
                         "filed_by_user_id", "claim_reason", "claim_amount_cents",
                         "status", "assigned_bank_user_id",
                         "provisional_credit_cents", "bank_liability_cents",
                         "customer_liability_cents", "resolved_by_bank_user_id",
                         "created_at", "updated_at", "version"])


def session_out(s):
    return serialize(s, ["id", "enrollment_id", "trainer_id", "scheduled_start",
                         "scheduled_end", "attendee_user_ids", "status",
                         "created_at", "updated_at", "version"])


OPS_RUN_FIELDS = [
    "kind", "enrollment_id", "period", "status", "exceptions_defaulted",
    "checks_staled", "ach_rules_expired", "sessions_marked_no_show",
    "fees_billed", "adjustment_cents", "minimum_topup_cents",
]


def ops_run_out(r):
    """OpsRun is an immutable checkpoint receipt: id + created_at only (no
    updated_at / version — PRD §2.4)."""
    return serialize(r, ["id", "created_at"] + OPS_RUN_FIELDS)


# ---------------------------------------------------------------------------
# payee match score (PRD §3.4): per-token floor BEFORE summing
# ---------------------------------------------------------------------------
_TOKEN_SPLIT = re.compile(r"[^A-Z0-9]+")


def _tokens(s):
    return [t for t in _TOKEN_SPLIT.split(s.upper()) if t]


def payee_match_score(issued_name, presented_raw):
    issued = _tokens(issued_name or "")
    presented = _tokens(presented_raw or "")
    if not issued or not presented:
        return 0
    total_len = sum(len(t) for t in issued)
    score = 0
    for t in issued:
        if t in presented:
            sim = 100
        elif any(
            (p.startswith(t) or t.startswith(p)) and min(len(p), len(t)) >= 3
            for p in presented
        ):
            sim = 50
        else:
            sim = 0
        score += (len(t) * sim) // total_len  # floor per token, then plain sum
    return score


# ---------------------------------------------------------------------------
# decision deadline (PRD §3.5)
# ---------------------------------------------------------------------------
def compute_decision_deadline(presented_at, enrollment):
    if enrollment["deadline_mode"] == "ROLLING_HOURS":
        return presented_at + timedelta(hours=enrollment["decision_window_hours"])
    # SAME_DAY_CUTOFF: before 14:00:00Z -> same day 20:00Z; at/after -> next day
    cutoff = presented_at.replace(hour=CUTOFF_HOUR, minute=0, second=0, microsecond=0)
    day = presented_at.date() if presented_at < cutoff else presented_at.date() + timedelta(days=1)
    return datetime(day.year, day.month, day.day, SAME_DAY_DEADLINE_HOUR, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# fee ledger helpers
# ---------------------------------------------------------------------------
def create_fee(enrollment_id, exception_id, fee_type, amount_cents, status,
               period=None):
    rec = new_record()
    rec.update({
        "enrollment_id": enrollment_id,
        "exception_id": exception_id,
        "period": period if period is not None else period_of(rec["created_at"]),
        "fee_type": fee_type,
        "amount_cents": amount_cents,
        "status": status,
        "waived_from_status": None,
        "waived_by": None,
        "waiver_reason": None,
    })
    store.fees[rec["id"]] = rec
    return rec


def create_return_fee(exc):
    return create_fee(exc["enrollment_id"], exc["id"], "RETURN_FEE",
                      RETURN_FEE_CENTS, "ACCRUED")


# ---------------------------------------------------------------------------
# account settlement ledger + review threshold (PRD §3.2)
# ---------------------------------------------------------------------------
def apply_pay_event(account, amount_cents):
    """Pay-side ledger update, then the review-threshold evaluation. A single
    logical mutation -> one version bump even when the hold also flips."""
    account["cumulative_paid_cents"] += amount_cents
    account["net_settled_cents"] = (
        account["cumulative_paid_cents"] - account["cumulative_reversed_cents"]
    )
    threshold = account.get("payment_review_threshold_cents")
    if (
        threshold is not None
        and account["status"] == "ACTIVE"
        and account["cumulative_paid_cents"] >= threshold
    ):
        account["status"] = "REVIEW_HOLD"
    bump(account)


def apply_reversal(account, amount_cents):
    account["cumulative_reversed_cents"] += amount_cents
    account["net_settled_cents"] = (
        account["cumulative_paid_cents"] - account["cumulative_reversed_cents"]
    )
    bump(account)


def consume_check(check, item):
    if check is not None and check["status"] == "REGISTERED":
        check["status"] = "CONSUMED"
        check["consumed_by_item_id"] = item["id"]
        bump(check)


def pay_item(item, check):
    """Shared pay-side cascade for CLEAN auto-match, DECISIONED_PAY and
    DEFAULTED_PAY: paid_at, ledger, threshold evaluation, check consumption."""
    item["paid_at"] = clock.now()
    apply_pay_event(store.accounts[item["account_id"]], item["amount_cents"])
    consume_check(check, item)


# ---------------------------------------------------------------------------
# matching cascade (PRD §3.4) — strict ordered rule chain
# ---------------------------------------------------------------------------
def find_issued_check(account_id, check_number):
    """Latest-created IssuedCheck on the account with this check_number (a
    STALE_DATED number may have been re-issued; the live record wins)."""
    cands = [
        c for c in store.checks.values()
        if c["account_id"] == account_id and c["check_number"] == check_number
    ]
    if not cands:
        return None
    cands.sort(key=lambda c: (c["created_at"], c["_seq"]))
    return cands[-1]


def match_item(item, account, enrollment):
    """Returns (match_result, matched_check_or_None, match_score_or_None)."""
    if enrollment["tier"] == "REVERSE_POSITIVE_PAY":
        return "REVERSE_REVIEW", None, None
    if account["status"] == "REVIEW_HOLD":
        return "ACCOUNT_HOLD_REVIEW", find_issued_check(account["id"], item["check_number"]), None
    check = find_issued_check(account["id"], item["check_number"])
    if check is None:
        return "NO_ISSUE_RECORD", None, None
    if check["status"] == "VOIDED":
        return "VOIDED_ITEM", check, None
    if check["status"] == "STALE_DATED":
        return "STALE_DATED_ITEM", check, None
    if check["status"] == "CONSUMED":
        return "DUPLICATE_PRESENTMENT", check, None
    if abs(item["amount_cents"] - check["amount_cents"]) > enrollment["amount_tolerance_cents"]:
        return "AMOUNT_MISMATCH", check, None
    if enrollment["tier"] == "PAYEE_POSITIVE_PAY":
        score = payee_match_score(check["payee_name"], item["payee_name_raw"])
        if score < enrollment["payee_score_threshold"]:
            return "PAYEE_MISMATCH", check, score
        return "CLEAN", check, score
    return "CLEAN", check, None


# ---------------------------------------------------------------------------
# exception lifecycle (PRD §3.5)
# ---------------------------------------------------------------------------
def create_exception(item, account, enrollment, reason, check):
    exc = new_record()
    exc.update({
        "enrollment_id": enrollment["id"],
        "account_id": account["id"],
        "presented_item_id": item["id"],
        "issued_check_id": check["id"] if check is not None else None,
        "reason": reason,
        "status": "OPEN",
        "default_decision_snapshot": enrollment["default_decision"],
        "decision_deadline_at": compute_decision_deadline(item["presented_at"], enrollment),
        "extended_once": False,
        "decided_by_user_id": None,
        "decided_at": None,
        "liability_party": None,
        "fee_entry_id": None,
    })
    fee = create_fee(enrollment["id"], exc["id"], "EXCEPTION_FEE",
                     PROVISIONAL_EXCEPTION_FEE_CENTS, "ACCRUED")
    exc["fee_entry_id"] = fee["id"]
    store.exceptions[exc["id"]] = exc
    item["exception_id"] = exc["id"]
    return exc


def resolve_exception_decision(exc, decision, decided_by):
    """Customer decision on an OPEN exception (PRD §3.5)."""
    item = store.items[exc["presented_item_id"]]
    exc["decided_by_user_id"] = decided_by
    exc["decided_at"] = clock.now()
    if decision == "PAY":
        exc["status"] = "DECISIONED_PAY"
        exc["liability_party"] = "CUSTOMER"
        item["status"] = "PAID"
        check = store.checks.get(exc["issued_check_id"]) if exc["issued_check_id"] else None
        pay_item(item, check)
    else:
        exc["status"] = "DECISIONED_RETURN"
        exc["liability_party"] = "NONE"
        item["status"] = "RETURNED"
        create_return_fee(exc)
    bump(exc)
    bump(item)


def default_exception(exc):
    """DAILY_SWEEP defaulting per the pinned default_decision_snapshot."""
    item = store.items[exc["presented_item_id"]]
    exc["liability_party"] = "CUSTOMER"
    if exc["default_decision_snapshot"] == "PAY":
        exc["status"] = "DEFAULTED_PAY"
        item["status"] = "DEFAULT_PAID"
        check = store.checks.get(exc["issued_check_id"]) if exc["issued_check_id"] else None
        pay_item(item, check)
    else:
        exc["status"] = "DEFAULTED_RETURN"
        item["status"] = "DEFAULT_RETURNED"
        create_return_fee(exc)
    bump(exc)
    bump(item)


# ---------------------------------------------------------------------------
# presented-item ingestion (PRD §3.4)
# ---------------------------------------------------------------------------
def ingest_presented_item(account, enrollment, fields):
    item = new_record()
    item.update(fields)
    item.update({
        "account_id": account["id"],
        "status": "RECEIVED",
        "match_result": None,
        "match_score": None,
        "exception_id": None,
        "paid_at": None,
    })
    result, check, score = match_item(item, account, enrollment)
    item["match_result"] = result
    item["match_score"] = score
    if result == "CLEAN":
        item["status"] = "PAID"
        pay_item(item, check)
    else:
        item["status"] = "EXCEPTION_HELD"
        create_exception(item, account, enrollment, result, check)
    store.items[item["id"]] = item
    return item


# ---------------------------------------------------------------------------
# ACH debit rules (PRD §3.6): half-open [start, end) window overlap
# ---------------------------------------------------------------------------
def ach_window_overlaps(a_start, a_end, b_start, b_end):
    from datetime import date as _date

    far = _date.max
    a_e = a_end if a_end is not None else far
    b_e = b_end if b_end is not None else far
    return a_start < b_e and b_start < a_e


def ach_has_overlap(account_id, originator_company_id, sec_code, start, end,
                    exclude_id=None):
    for r in store.ach_rules.values():
        if r["id"] == exclude_id:
            continue
        if r["status"] not in ("ACTIVE", "SUSPENDED"):
            continue
        if (
            r["account_id"] == account_id
            and r["originator_company_id"] == originator_company_id
            and r["sec_code"] == sec_code
            and ach_window_overlaps(start, end, r["effective_start_date"],
                                    r["effective_end_date"])
        ):
            return True
    return False


# ---------------------------------------------------------------------------
# issue-file intake (PRD §3.3)
# ---------------------------------------------------------------------------
def canonical_rows_hash(rows):
    canon = json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def validate_issue_row(row, account_id, seen_in_file):
    """Returns None when the row is valid, else a human-readable reason."""
    if not isinstance(row, dict):
        return "row must be an object"
    check_number = row.get("check_number")
    if not isinstance(check_number, str) or not (1 <= len(check_number) <= 12) \
            or not check_number.isdigit():
        return "check_number must be 1-12 digits"
    amount = row.get("amount_cents")
    if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
        return "amount_cents must be a positive integer"
    payee = row.get("payee_name")
    if not isinstance(payee, str) or not (1 <= len(payee) <= 80):
        return "payee_name must be 1-80 characters"
    issue_date_raw = row.get("issue_date")
    issue_date = None
    if isinstance(issue_date_raw, str):
        try:
            issue_date = datetime.strptime(issue_date_raw.strip(), "%Y-%m-%d").date()
        except ValueError:
            issue_date = None
    if issue_date is None:
        return "issue_date must be a valid ISO date (YYYY-MM-DD)"
    if issue_date > clock.today():
        return "issue_date must not be after the current date"
    if check_number in seen_in_file:
        return "duplicate check_number within the file"
    # any non-STALE_DATED live record blocks re-issue (STALE_DATED may re-issue)
    blocking = [
        c for c in store.checks.values()
        if c["account_id"] == account_id
        and c["check_number"] == check_number
        and c["status"] in ("REGISTERED", "CONSUMED", "VOIDED")
    ]
    if blocking:
        return "check_number already exists on this account"
    return None


# ---------------------------------------------------------------------------
# ops runs (PRD §3.9)
# ---------------------------------------------------------------------------
def run_daily_sweep(enrollment_id):
    now = clock.now()
    today = now.date()
    exceptions_defaulted = 0
    checks_staled = 0
    ach_rules_expired = 0
    sessions_no_show = 0

    open_excs = [
        e for e in store.exceptions.values()
        if e["status"] == "OPEN"
        and (enrollment_id is None or e["enrollment_id"] == enrollment_id)
    ]
    open_excs.sort(key=lambda e: (e["created_at"], e["_seq"]))
    for exc in open_excs:
        if exc["decision_deadline_at"] < now:  # strictly before the clock
            default_exception(exc)
            exceptions_defaulted += 1

    for chk in store.checks.values():
        if chk["status"] != "REGISTERED":
            continue
        account = store.accounts[chk["account_id"]]
        if enrollment_id is not None and account["enrollment_id"] != enrollment_id:
            continue
        enr = store.enrollments[account["enrollment_id"]]
        if today >= chk["issue_date"] + timedelta(days=enr["stale_days"]):
            chk["status"] = "STALE_DATED"
            bump(chk)
            checks_staled += 1

    for rule in store.ach_rules.values():
        if rule["status"] not in ("ACTIVE", "SUSPENDED"):
            continue
        account = store.accounts[rule["account_id"]]
        if enrollment_id is not None and account["enrollment_id"] != enrollment_id:
            continue
        if rule["effective_end_date"] is not None and rule["effective_end_date"] < today:
            rule["status"] = "EXPIRED"
            bump(rule)
            ach_rules_expired += 1

    for sess in store.sessions.values():
        if sess["status"] != "SCHEDULED":
            continue
        if enrollment_id is not None and sess["enrollment_id"] != enrollment_id:
            continue
        if sess["scheduled_end"] < now:
            sess["status"] = "NO_SHOW"
            bump(sess)
            sessions_no_show += 1

    return {
        "exceptions_defaulted": exceptions_defaulted,
        "checks_staled": checks_staled,
        "ach_rules_expired": ach_rules_expired,
        "sessions_marked_no_show": sessions_no_show,
    }


def _exception_fee_tier_price(position):
    if position <= TIER1_LIMIT:
        return TIER1_FEE_CENTS
    if position <= TIER2_LIMIT:
        return TIER2_FEE_CENTS
    return TIER3_FEE_CENTS


def run_monthly_billing(enrollment_id, period):
    """Pinned evaluation order (PRD §3.7): tier re-rate -> adjustment ->
    waiver-adjusted pre-minimum -> minimum top-up -> ACCRUED flip."""
    entries = [
        f for f in store.fees.values()
        if f["enrollment_id"] == enrollment_id and f["period"] == period
    ]

    exc_entries = [f for f in entries if f["fee_type"] == "EXCEPTION_FEE"]

    def _exc_order(fee):
        exc = store.exceptions.get(fee["exception_id"])
        if exc is None:
            return (datetime.min.replace(tzinfo=UTC), "", 0)
        item = store.items.get(exc["presented_item_id"])
        check_number = item["check_number"] if item is not None else ""
        return (exc["created_at"], check_number, exc["_seq"])

    exc_entries.sort(key=_exc_order)
    tiered_total = sum(
        _exception_fee_tier_price(i) for i in range(1, len(exc_entries) + 1)
    )
    provisional_total = sum(f["amount_cents"] for f in exc_entries)
    adjustment = tiered_total - provisional_total
    adjustment_posted = 0
    if adjustment != 0:
        create_fee(enrollment_id, None, "ADJUSTMENT", adjustment, "BILLED",
                   period=period)
        adjustment_posted = adjustment

    return_total = sum(
        f["amount_cents"] for f in entries if f["fee_type"] == "RETURN_FEE"
    )
    waived_return = sum(
        f["amount_cents"] for f in entries
        if f["fee_type"] == "RETURN_FEE" and f["status"] == "WAIVED"
    )
    waived_exception = sum(
        f["amount_cents"] for f in entries
        if f["fee_type"] == "EXCEPTION_FEE" and f["status"] == "WAIVED"
    )
    pre_minimum = (provisional_total + adjustment) + (return_total - waived_return) - waived_exception
    net_due = max(MONTHLY_MINIMUM_CENTS, pre_minimum)
    topup_posted = 0
    if net_due > pre_minimum:
        topup = net_due - pre_minimum
        create_fee(enrollment_id, None, "MINIMUM_TOPUP", topup, "BILLED",
                   period=period)
        topup_posted = topup

    fees_billed = 0
    for f in entries:
        if f["status"] == "ACCRUED":
            f["status"] = "BILLED"
            bump(f)
            fees_billed += 1

    return {
        "fees_billed": fees_billed,
        "adjustment_cents": adjustment_posted,
        "minimum_topup_cents": topup_posted,
    }


def fee_statement(enrollment_id, period):
    """Statement read derivation (PRD §3.7): net_due is the BILLED sum;
    waived amounts surface separately."""
    entries = [
        f for f in store.fees.values()
        if f["enrollment_id"] == enrollment_id and f["period"] == period
    ]
    by_type = lambda t: sum(f["amount_cents"] for f in entries if f["fee_type"] == t)
    return {
        "period": period,
        "exception_fees_cents": by_type("EXCEPTION_FEE"),
        "return_fees_cents": by_type("RETURN_FEE"),
        "adjustment_cents": by_type("ADJUSTMENT"),
        "waived_cents": sum(f["amount_cents"] for f in entries if f["status"] == "WAIVED"),
        "minimum_topup_cents": by_type("MINIMUM_TOPUP"),
        "net_due_cents": sum(f["amount_cents"] for f in entries if f["status"] == "BILLED"),
        "entry_count": len(entries),
    }


# ---------------------------------------------------------------------------
# adoption report (PRD §3.9)
# ---------------------------------------------------------------------------
def adoption_report(enrollment):
    enr_id = enrollment["id"]
    account_ids = {
        a["id"] for a in store.accounts.values() if a["enrollment_id"] == enr_id
    }
    items = [i for i in store.items.values() if i["account_id"] in account_ids]
    excs = [e for e in store.exceptions.values() if e["enrollment_id"] == enr_id]
    decisioned = sum(1 for e in excs if e["status"] in ("DECISIONED_PAY", "DECISIONED_RETURN"))
    defaulted = sum(1 for e in excs if e["status"] in ("DEFAULTED_PAY", "DEFAULTED_RETURN"))
    resolved = decisioned + defaulted
    on_time_bp = 0 if resolved == 0 else round_half_up_int(10000 * decisioned, resolved)
    if enrollment["tier"] == "REVERSE_POSITIVE_PAY" or len(items) == 0:
        compliance_bp = None
    else:
        clean = sum(1 for i in items if i["match_result"] == "CLEAN")
        compliance_bp = round_half_up_int(10000 * clean, len(items))
    training_done = sum(
        1 for s in store.sessions.values()
        if s["enrollment_id"] == enr_id and s["status"] == "COMPLETED"
    )
    return {
        "presented_total": len(items),
        "clean_paid_total": sum(1 for i in items if i["match_result"] == "CLEAN"),
        "exceptions_total": len(excs),
        "decisioned_total": decisioned,
        "defaulted_total": defaulted,
        "on_time_decision_bp": on_time_bp,
        "issue_file_compliance_bp": compliance_bp,
        "training_completed_count": training_done,
    }


# ---------------------------------------------------------------------------
# tier change volume gate (PRD §3.1): trailing 90 days, both ends inclusive
# ---------------------------------------------------------------------------
def trailing_90d_issued_volume(enrollment_id):
    now = clock.now()
    lo = now - timedelta(days=REVERSE_WINDOW_DAYS)
    account_ids = {
        a["id"] for a in store.accounts.values() if a["enrollment_id"] == enrollment_id
    }
    return sum(
        1 for c in store.checks.values()
        if c["account_id"] in account_ids and lo <= c["created_at"] <= now
    )
