"""Till session lifecycle: assignment, drops, close, blind count, recount, reconcile."""
from flask import Blueprint, request

import calc
import clock
import db
import domain
import response
import serializers
import validation
from auth import endpoint, is_cashier, user_id
from errors import bad_request, err
from routes.common import list_collection

bp = Blueprint("sessions", __name__)

SESSION_READ_ROLES = ["Cashier", "CashOfficeClerk", "StoreManager", "LossPreventionInvestigator"]
DROP_TYPES = ("MID_SHIFT_DROP", "CLOSING_DROP")


def _ownership_guard(session_id):
    """PRD section 2.1/2.12 step 2: a Cashier may only act on their own session."""
    if is_cashier():
        session = db.till_sessions.get(session_id)
        if session is not None and session["cashier_id"] != user_id():
            raise err("ERR_UNAUTHORIZED", "a Cashier may only act on their own till session")


def _overlaps(start_a, end_a, start_b, end_b):
    """Half-open [start, end) overlap; windows that merely touch do not conflict."""
    return start_a < end_b and start_b < end_a


@bp.post("/cash-ops/till-sessions")
@endpoint(["StoreManager", "CashOfficeClerk"])
def create_session():
    data = validation.body()
    journal_id = validation.req_str(data, "sales_journal_id")
    cashier_id = validation.req_str(data, "cashier_id")
    safe_id = validation.req_str(data, "safe_id")
    register_number = validation.req_int(data, "register_number", minimum=1, maximum=99)
    shift_start_at = validation.req_datetime(data, "shift_start_at")
    shift_end_at = validation.req_datetime(data, "shift_end_at")
    if shift_end_at <= shift_start_at:
        raise bad_request("shift_end_at must be strictly after shift_start_at")
    starting_bank_cents = validation.req_int(data, "starting_bank_cents", minimum=0)

    journal = domain.get_journal(journal_id)
    cashier = domain.get_cashier(cashier_id)
    if cashier["store_id"] != journal["store_id"]:
        raise err("ERR_CASHIER_NOT_FOUND", "the cashier does not belong to the journal's store")
    safe = domain.get_safe(safe_id)
    if safe["store_id"] != journal["store_id"]:
        raise err("ERR_SAFE_NOT_FOUND", "the safe does not belong to the journal's store")

    if journal["status"] not in ("OPEN", "TENDERS_POSTED"):
        raise err(
            "ERR_TILL_SESSION_INVALID_STATE",
            "the sales journal no longer accepts new till sessions",
        )
    if safe["posture"] == "FROZEN":
        raise err("ERR_SAFE_FROZEN", "the safe is frozen by an investigation")
    if cashier["till_eligibility"] == "BARRED":
        raise err("ERR_CASHIER_BARRED", "a barred cashier may never be assigned a till")
    if cashier["till_eligibility"] == "RESTRICTED":
        if cashier["coaching_state"] != "COACHING_ACKNOWLEDGED":
            raise err(
                "ERR_CASHIER_RESTRICTED",
                "a restricted cashier must acknowledge coaching before taking a till",
            )
    elif cashier["till_eligibility"] == "ELIGIBLE" and cashier["coaching_state"] == "COACHING_DUE":
        due = cashier["coaching_due_at"]
        if due is not None and clock.now() > due:
            raise err(
                "ERR_COACHING_NOT_ACKNOWLEDGED",
                "the coaching grace period has expired",
            )

    for other in db.ordered(db.till_sessions):
        if other["cashier_id"] != cashier["id"]:
            continue
        if other["status"] == "RECONCILED":
            continue
        if _overlaps(shift_start_at, shift_end_at, other["shift_start_at"], other["shift_end_at"]):
            raise err("ERR_CASHIER_SHIFT_OVERLAP", "the cashier already works an overlapping shift")
    for other in db.ordered(db.till_sessions):
        if other["sales_journal_id"] != journal["id"]:
            continue
        if other["register_number"] != register_number:
            continue
        if other["status"] not in ("ACTIVE", "PENDING_COUNT"):
            continue
        if _overlaps(shift_start_at, shift_end_at, other["shift_start_at"], other["shift_end_at"]):
            raise err("ERR_REGISTER_OCCUPIED", "the register is already occupied on this journal")

    if domain.safe_balance(safe["id"]) < starting_bank_cents:
        raise err(
            "ERR_INSUFFICIENT_SAFE_BALANCE",
            "the starting bank would drive the safe balance below zero",
        )

    record = db.base_record()
    record.update(
        {
            "sales_journal_id": journal["id"],
            "cashier_id": cashier["id"],
            "safe_id": safe["id"],
            "register_number": register_number,
            "shift_start_at": shift_start_at,
            "shift_end_at": shift_end_at,
            "status": "ACTIVE",
            "starting_bank_cents": starting_bank_cents,
            "pos_cash_sales_cents": None,
            "pos_card_sales_cents": None,
            "pos_paid_out_cents": None,
            "counted_lines": [],
            "counted_cash_cents": None,
            "expected_cash_cents": None,
            "variance_cents": None,
            "variance_basis": None,
            "recount_count": 0,
            "counted_by_user_id": None,
            "forced_close": False,
        }
    )
    db.till_sessions[record["id"]] = record
    domain.write_txn(
        safe_id=safe["id"],
        txn_type="STARTING_BANK_ISSUE",
        declared_amount_cents=starting_bank_cents,
        actor_user_id=user_id(),
        memo="starting bank issue for session %s" % record["id"],
        till_session_id=record["id"],
    )
    db.touch(safe)
    return response.object_response(serializers.till_session(record), 201)


@bp.post("/cash-ops/till-sessions/<session_id>/drops")
@endpoint(["Cashier"])
def record_drop(session_id):
    _ownership_guard(session_id)
    data = validation.body()
    txn_type = validation.req_enum(data, "txn_type", DROP_TYPES)
    declared_amount_cents = validation.req_int(data, "declared_amount_cents", minimum=0)
    memo = validation.opt_str(data, "memo")
    session = domain.get_session(session_id)
    if session["status"] != "ACTIVE":
        raise err("ERR_TILL_SESSION_INVALID_STATE", "drops are only accepted on an ACTIVE session")
    safe = domain.get_safe(session["safe_id"])
    if safe["safe_type"] == "MANUAL" and safe["open_state"] != "UNLOCKED":
        raise err("ERR_SAFE_NOT_UNLOCKED", "the safe must be UNLOCKED to accept a drop")
    if safe["posture"] == "FROZEN":
        raise err("ERR_SAFE_FROZEN", "the safe is frozen by an investigation")
    if memo is None or memo.strip() == "":
        memo = "%s for session %s" % (
            "closing drop" if txn_type == "CLOSING_DROP" else "mid-shift drop",
            session["id"],
        )
    row = domain.write_txn(
        safe_id=safe["id"],
        txn_type=txn_type,
        declared_amount_cents=declared_amount_cents,
        actor_user_id=user_id(),
        memo=memo,
        till_session_id=session["id"],
    )
    db.touch(session)
    return response.object_response(serializers.safe_transaction(row), 201)


@bp.post("/cash-ops/till-sessions/<session_id>/close")
@endpoint(["Cashier", "StoreManager"])
def close_session(session_id):
    _ownership_guard(session_id)
    data = validation.body()
    forced_close = validation.opt_bool(data, "forced_close", False)
    if forced_close and is_cashier():
        raise err("ERR_UNAUTHORIZED", "forced_close is reserved to a StoreManager")
    if forced_close:
        validation.opt_int(data, "pos_cash_sales_cents", minimum=0)
        validation.opt_int(data, "pos_card_sales_cents", minimum=0)
        validation.opt_int(data, "pos_paid_out_cents", minimum=0)
        pos_cash = pos_card = pos_paid_out = None
    else:
        pos_cash = validation.req_int(data, "pos_cash_sales_cents", minimum=0)
        pos_card = validation.req_int(data, "pos_card_sales_cents", minimum=0)
        pos_paid_out = validation.opt_int(data, "pos_paid_out_cents", minimum=0)
        if pos_paid_out is None:
            pos_paid_out = 0
    session = domain.get_session(session_id)
    if session["status"] != "ACTIVE":
        raise err("ERR_TILL_SESSION_INVALID_STATE", "only an ACTIVE session may be closed")
    session["status"] = "PENDING_COUNT"
    session["forced_close"] = bool(forced_close)
    session["pos_cash_sales_cents"] = pos_cash
    session["pos_card_sales_cents"] = pos_card
    session["pos_paid_out_cents"] = pos_paid_out
    db.touch(session)
    return response.object_response(serializers.close_projection(session))


@bp.post("/cash-ops/till-sessions/<session_id>/blind-count")
@endpoint(["CashOfficeClerk"])
def blind_count(session_id):
    data = validation.body()
    counted_lines = validation.req_counted_lines(data, "counted_lines")
    session = domain.get_session(session_id)
    if session["status"] != "PENDING_COUNT":
        raise err(
            "ERR_TILL_SESSION_INVALID_STATE",
            "a blind count is only accepted on a PENDING_COUNT session",
        )
    session["counted_lines"] = counted_lines
    session["counted_cash_cents"] = validation.lines_value(counted_lines)
    session["counted_by_user_id"] = user_id()
    session["status"] = "COUNTED"
    db.touch(session)
    return response.object_response(serializers.blind_count_projection(session))


@bp.post("/cash-ops/till-sessions/<session_id>/recount")
@endpoint(["CashOfficeClerk"])
def recount(session_id):
    data = validation.body()
    validation.req_str(data, "recount_reason")
    session = domain.get_session(session_id)
    if session["status"] != "COUNTED":
        raise err(
            "ERR_TILL_SESSION_INVALID_STATE",
            "a recount is only ordered from a COUNTED session",
        )
    session["status"] = "PENDING_COUNT"
    session["recount_count"] = session["recount_count"] + 1
    session["counted_lines"] = []
    session["counted_cash_cents"] = None
    session["counted_by_user_id"] = None
    db.touch(session)
    return response.object_response(serializers.till_session(session))


@bp.post("/cash-ops/till-sessions/<session_id>/reconcile")
@endpoint(["CashOfficeClerk"])
def reconcile_session(session_id):
    validation.body()
    session = domain.get_session(session_id)
    if session["forced_close"] and session["pos_cash_sales_cents"] is None:
        raise bad_request("a forced-closed session has no cash-sales figure to reconcile")
    if session["status"] != "COUNTED":
        raise err(
            "ERR_TILL_SESSION_INVALID_STATE",
            "a session may only be reconciled from COUNTED",
        )
    journal = domain.get_journal(session["sales_journal_id"])
    store = domain.get_store(journal["store_id"])
    if store["dual_control_required"] and session["counted_by_user_id"] == user_id():
        raise err(
            "ERR_DUAL_CONTROL_VIOLATION",
            "the reconciling user must differ from the counting user",
        )

    verified = domain.dropped_verified_cents(session["id"])
    if verified is None:
        basis = "DECLARED_DROPS"
        drop_total = domain.dropped_declared_cents(session["id"])
    else:
        basis = "VERIFIED_DROPS"
        drop_total = verified
    expected = calc.till_expected_cash(
        session["starting_bank_cents"],
        session["pos_cash_sales_cents"],
        session["pos_paid_out_cents"],
        drop_total,
    )
    variance = session["counted_cash_cents"] - expected
    session["variance_basis"] = basis
    session["expected_cash_cents"] = expected
    session["variance_cents"] = variance
    session["status"] = "RECONCILED"
    db.touch(session)

    cashier = domain.get_cashier(session["cashier_id"])
    domain.recompute_rolling(cashier, store)
    if abs(variance) >= store["single_event_variance_threshold_cents"]:
        cashier["coaching_state"] = "COACHING_DUE"
        cashier["coaching_due_at"] = clock.plus_hours(clock.now(), calc.COACHING_GRACE_HOURS)
        domain.open_variance_case(
            case_type="SESSION_VARIANCE",
            sales_journal_id=journal["id"],
            total_variance_cents=abs(variance),
            store=store,
            cashier_id=cashier["id"],
        )
    if cashier["rolling_absolute_variance_cents"] >= store["rolling_variance_threshold_cents"]:
        if cashier["till_eligibility"] == "ELIGIBLE":
            cashier["till_eligibility"] = "RESTRICTED"
        domain.open_variance_case(
            case_type="ROLLING_PATTERN",
            sales_journal_id=journal["id"],
            total_variance_cents=cashier["rolling_absolute_variance_cents"],
            store=store,
            cashier_id=cashier["id"],
        )
    db.touch(cashier)

    domain.reevaluate_journal(journal)
    db.touch(journal)
    return response.object_response(serializers.till_session(session))


@bp.get("/cash-ops/till-sessions/<session_id>")
@endpoint(SESSION_READ_ROLES)
def read_session(session_id):
    _ownership_guard(session_id)
    session = domain.get_session(session_id)
    return response.object_response(serializers.till_session(session))


@bp.get("/cash-ops/till-sessions")
@endpoint(SESSION_READ_ROLES)
def list_sessions():
    return list_collection(
        db.till_sessions,
        [
            ("sales_journal_id", "sales_journal_id"),
            ("cashier_id", "cashier_id"),
            ("safe_id", "safe_id"),
            ("status", "status"),
        ],
        serializers.till_session,
    )
