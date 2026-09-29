"""Armored and smart-safe deposits: prepare, seal, void, book, pickup, bank tie-out."""
from flask import Blueprint

import calc
import clock
import db
import domain
import response
import serializers
import validation
from auth import endpoint, user_id
from errors import bad_request, err
from routes.common import list_collection

bp = Blueprint("deposits", __name__)

DEPOSIT_READ_ROLES = [
    "CashOfficeClerk",
    "StoreManager",
    "TreasuryAnalyst",
    "ArmoredCarrier",
    "LossPreventionInvestigator",
]
PICKUP_BLOCKING_STATUSES = ("SCHEDULED", "IN_TRANSIT")


def _new_deposit(safe, journal, business_date, counted_lines, declared_total):
    record = db.base_record()
    record.update(
        {
            "safe_id": safe["id"],
            "sales_journal_id": journal["id"],
            "deposit_type": None,
            "status": None,
            "business_date": business_date,
            "counted_lines": counted_lines,
            "declared_total_cents": declared_total,
            "suspect_note_cents": 0,
            "credit_basis": None,
            "provisional_credit_cents": 0,
            "carrier_fee_cents": calc.carrier_fee_cents(declared_total),
            "expected_credit_cents": calc.expected_credit_cents(declared_total),
            "credited_total_cents": 0,
            "credit_variance_cents": None,
            "pickup_window_start": None,
            "pickup_window_end": None,
            "prepared_by_user_id": None,
            "sealed_by_user_id": None,
            "seal_number": None,
            "carrier_reference": None,
        }
    )
    return record


def _write_provisional_credit(deposit, store):
    row = db.base_record()
    row.update(
        {
            "store_id": store["id"],
            "deposit_id": deposit["id"],
            "credit_type": "PROVISIONAL",
            "amount_cents": deposit["provisional_credit_cents"],
            "value_date": deposit["business_date"],
            "bank_reference": "PROVISIONAL-%s" % deposit["id"],
            "match_state": "UNMATCHED",
        }
    )
    db.bank_credit_records[row["id"]] = row
    return row


def _apply_verification(deposit, sessions):
    """PRD section 3.6: apportion the re-count across the listed sessions and write
    verified_amount_cents onto their drop ledger rows."""
    if not sessions:
        return
    declared_total = deposit["declared_total_cents"]
    if len(sessions) == 1:
        shares = {sessions[0]["id"]: declared_total}
    else:
        basis = {s["id"]: domain.dropped_declared_cents(s["id"]) for s in sessions}
        pool = sum(basis.values())
        shares = {}
        for session in sessions:
            if pool <= 0:
                shares[session["id"]] = 0
            else:
                shares[session["id"]] = calc.round_half_up(
                    calc.Decimal(declared_total) * calc.Decimal(basis[session["id"]])
                    / calc.Decimal(pool)
                )
    for session in sessions:
        rows = domain.session_drop_rows(session["id"])
        if not rows:
            continue
        closing = [r for r in rows if r["txn_type"] == "CLOSING_DROP"]
        remainder_row = closing[-1] if closing else None
        running = 0
        for row in rows:
            if row is remainder_row:
                continue
            row["verified_amount_cents"] = row["declared_amount_cents"]
            running += row["verified_amount_cents"]
        if remainder_row is not None:
            remainder_row["verified_amount_cents"] = shares[session["id"]] - running


@bp.post("/cash-ops/deposits")
@endpoint(["CashOfficeClerk"])
def prepare_deposit():
    data = validation.body()
    safe_id = validation.req_str(data, "safe_id")
    journal_id = validation.req_str(data, "sales_journal_id")
    business_date = validation.req_date(data, "business_date")
    counted_lines = validation.req_counted_lines(data, "counted_lines")
    expected_safe_version = validation.opt_int(data, "expected_safe_version", minimum=0)
    verify_ids = data.get("verify_till_session_ids")
    if verify_ids is None:
        verify_ids = []
    else:
        verify_ids = validation.req_id_list(data, "verify_till_session_ids")
    validation.opt_int(data, "suspect_note_cents", minimum=0)

    safe = domain.get_safe(safe_id)
    journal = domain.get_journal(journal_id)
    if journal["store_id"] != safe["store_id"]:
        raise err("ERR_SAFE_NOT_FOUND", "the safe does not belong to the journal's store")
    sessions = [domain.get_session(sid) for sid in verify_ids]

    if safe["open_state"] != "UNLOCKED":
        raise err("ERR_SAFE_NOT_UNLOCKED", "the safe must be UNLOCKED to prepare a deposit")
    if safe["posture"] == "FROZEN":
        raise err("ERR_SAFE_FROZEN", "the safe is frozen by an investigation")

    declared_total = validation.lines_value(counted_lines)
    if domain.safe_balance(safe["id"]) < declared_total:
        raise err(
            "ERR_INSUFFICIENT_SAFE_BALANCE",
            "the safe does not hold the value of the submitted lines",
        )
    if expected_safe_version is not None and expected_safe_version != safe["version"]:
        raise err("ERR_SAFE_VERSION_STALE", "expected_safe_version does not match the safe")

    store = domain.get_store(safe["store_id"])
    record = _new_deposit(safe, journal, business_date, counted_lines, declared_total)
    record.update(
        {
            "deposit_type": "MANUAL_ARMORED",
            "status": "PREPARING",
            "credit_basis": "CARRIER_PROVISIONAL",
            "prepared_by_user_id": user_id(),
            "suspect_note_cents": 0,
        }
    )
    db.deposits[record["id"]] = record
    _apply_verification(record, sessions)
    domain.write_txn(
        safe_id=safe["id"],
        txn_type="DEPOSIT_REMOVAL",
        declared_amount_cents=declared_total,
        actor_user_id=user_id(),
        memo="deposit removal for deposit %s" % record["id"],
        deposit_id=record["id"],
    )
    db.touch(safe)
    return response.object_response(serializers.deposit(record), 201)


@bp.post("/cash-ops/safes/<safe_id>/smart-deposits")
@endpoint(["CashOfficeClerk", "Cashier"])
def smart_deposit(safe_id):
    data = validation.body()
    journal_id = validation.req_str(data, "sales_journal_id")
    business_date = validation.req_date(data, "business_date")
    counted_lines = validation.req_counted_lines(data, "counted_lines")
    suspect_note_cents = validation.opt_int(data, "suspect_note_cents", minimum=0)
    if suspect_note_cents is None:
        suspect_note_cents = 0
    till_session_id = validation.opt_str(data, "till_session_id")
    declared_total = validation.lines_value(counted_lines)
    if suspect_note_cents > declared_total:
        raise bad_request("suspect_note_cents may not exceed the value of counted_lines")

    safe = domain.get_safe(safe_id)
    journal = domain.get_journal(journal_id)
    if journal["store_id"] != safe["store_id"]:
        raise err("ERR_SAFE_NOT_FOUND", "the safe does not belong to the journal's store")
    session = None
    if till_session_id is not None:
        session = domain.get_session(till_session_id)

    if safe["safe_type"] != "SMART":
        raise err("ERR_SMART_SAFE_REQUIRED", "only a smart safe accepts a validator insertion")
    if safe["posture"] == "FROZEN":
        raise err("ERR_SAFE_FROZEN", "the safe is frozen by an investigation")

    store = domain.get_store(safe["store_id"])
    record = _new_deposit(safe, journal, business_date, counted_lines, declared_total)
    record.update(
        {
            "deposit_type": "SMART_SAFE",
            "status": "SEALED",
            "credit_basis": "SMART_PROVISIONAL",
            "suspect_note_cents": suspect_note_cents,
            "seal_number": "SMART-%s" % safe["safe_code"],
            "provisional_credit_cents": calc.smart_provisional_credit(
                counted_lines, suspect_note_cents, store["provisional_credit_cap_cents"]
            ),
        }
    )
    db.deposits[record["id"]] = record
    domain.write_txn(
        safe_id=safe["id"],
        txn_type="SMART_DEPOSIT",
        declared_amount_cents=declared_total,
        actor_user_id=user_id(),
        memo="smart safe insertion for deposit %s" % record["id"],
        deposit_id=record["id"],
        till_session_id=session["id"] if session is not None else None,
    )
    _write_provisional_credit(record, store)
    db.touch(safe)
    domain.reevaluate_journal(journal)
    return response.object_response(serializers.deposit(record), 201)


def _store_deposits(store_id):
    out = []
    for deposit in db.ordered(db.deposits):
        safe = db.safes.get(deposit["safe_id"])
        if safe is not None and safe["store_id"] == store_id:
            out.append(deposit)
    return out


@bp.post("/cash-ops/deposits/<deposit_id>/seal")
@endpoint(["CashOfficeClerk", "StoreManager"])
def seal_deposit(deposit_id):
    data = validation.body()
    seal_number = validation.req_str(data, "seal_number")
    deposit = domain.get_deposit(deposit_id)
    if deposit["status"] != "PREPARING":
        raise err("ERR_DEPOSIT_INVALID_STATE", "only a PREPARING deposit may be sealed")
    safe = domain.get_safe(deposit["safe_id"])
    store = domain.get_store(safe["store_id"])
    if store["dual_control_required"] and deposit["prepared_by_user_id"] == user_id():
        raise err(
            "ERR_DUAL_CONTROL_VIOLATION",
            "the sealing user must differ from the preparing user",
        )
    deposit["seal_number"] = seal_number
    deposit["sealed_by_user_id"] = user_id()
    deposit["status"] = "SEALED"
    db.touch(deposit)
    safe["open_state"] = "LOCKED"
    safe["open_requested_at"] = None
    safe["open_requested_by_user_id"] = None
    safe["unlocked_at"] = None
    db.touch(safe)
    domain.reevaluate_journal(db.sales_journals.get(deposit["sales_journal_id"]))
    return response.object_response(serializers.deposit(deposit))


@bp.post("/cash-ops/deposits/<deposit_id>/void")
@endpoint(["StoreManager"])
def void_deposit(deposit_id):
    data = validation.body()
    validation.req_str(data, "void_reason")
    deposit = domain.get_deposit(deposit_id)
    if deposit["status"] not in ("PREPARING", "SEALED") or deposit["deposit_type"] != "MANUAL_ARMORED":
        raise err(
            "ERR_DEPOSIT_INVALID_STATE",
            "only a PREPARING or SEALED armored deposit may be voided",
        )
    safe = domain.get_safe(deposit["safe_id"])
    domain.write_txn(
        safe_id=safe["id"],
        txn_type="DEPOSIT_RETURN",
        declared_amount_cents=deposit["declared_total_cents"],
        actor_user_id=user_id(),
        memo="deposit return for voided deposit %s" % deposit["id"],
        deposit_id=deposit["id"],
    )
    deposit["status"] = "VOIDED"
    db.touch(deposit)
    db.touch(safe)
    return response.object_response(serializers.deposit(deposit))


@bp.post("/cash-ops/deposits/<deposit_id>/schedule-pickup")
@endpoint(["CashOfficeClerk"])
def schedule_pickup(deposit_id):
    data = validation.body()
    window_start = validation.req_datetime(data, "pickup_window_start")
    window_end = validation.req_datetime(data, "pickup_window_end")
    if window_end <= window_start:
        raise bad_request("pickup_window_end must be strictly after pickup_window_start")
    carrier_reference = validation.req_str(data, "carrier_reference")
    deposit = domain.get_deposit(deposit_id)
    if deposit["status"] != "SEALED":
        raise err("ERR_DEPOSIT_INVALID_STATE", "only a SEALED deposit may be booked for pickup")
    safe = domain.get_safe(deposit["safe_id"])
    store = domain.get_store(safe["store_id"])
    buffer_minutes = store["pickup_buffer_minutes"]
    new_start = clock.plus_minutes(window_start, -buffer_minutes)
    new_end = clock.plus_minutes(window_end, buffer_minutes)
    siblings = [
        d
        for d in _store_deposits(store["id"])
        if d["id"] != deposit["id"] and d["status"] in PICKUP_BLOCKING_STATUSES
    ]
    for other in siblings:
        if other["pickup_window_start"] is None or other["pickup_window_end"] is None:
            continue
        other_start = clock.plus_minutes(other["pickup_window_start"], -buffer_minutes)
        other_end = clock.plus_minutes(other["pickup_window_end"], buffer_minutes)
        if new_start <= other_end and other_start <= new_end:
            raise err(
                "ERR_PICKUP_WINDOW_CONFLICT",
                "the buffered pickup window intersects another booked deposit",
            )
    same_day = [d for d in siblings if d["business_date"] == deposit["business_date"]]
    if len(same_day) >= store["max_daily_pickups"]:
        raise err(
            "ERR_PICKUP_CAPACITY_EXCEEDED",
            "the store's daily pickup capacity is already committed",
        )
    deposit["pickup_window_start"] = window_start
    deposit["pickup_window_end"] = window_end
    deposit["carrier_reference"] = carrier_reference
    deposit["status"] = "SCHEDULED"
    db.touch(deposit)
    return response.object_response(serializers.deposit(deposit))


@bp.post("/cash-ops/deposits/<deposit_id>/pickup")
@endpoint(["ArmoredCarrier"])
def pickup_deposit(deposit_id):
    data = validation.body()
    validation.req_datetime(data, "picked_up_at")
    validation.req_str(data, "carrier_signature")
    deposit = domain.get_deposit(deposit_id)
    if deposit["status"] != "SCHEDULED":
        raise err("ERR_DEPOSIT_INVALID_STATE", "only a SCHEDULED deposit may be picked up")
    safe = domain.get_safe(deposit["safe_id"])
    store = domain.get_store(safe["store_id"])
    deposit["provisional_credit_cents"] = calc.carrier_provisional_credit(
        deposit["declared_total_cents"], store["provisional_credit_cap_cents"]
    )
    deposit["status"] = "IN_TRANSIT"
    _write_provisional_credit(deposit, store)
    db.touch(deposit)
    db.touch(safe)
    return response.object_response(serializers.deposit(deposit))


@bp.post("/cash-ops/deposits/<deposit_id>/reconcile-bank")
@endpoint(["TreasuryAnalyst"])
def reconcile_bank(deposit_id):
    data = validation.body()
    record_ids = validation.req_id_list(data, "bank_credit_record_ids")
    deposit = domain.get_deposit(deposit_id)
    records = [domain.get_credit_record(rid) for rid in record_ids]
    if deposit["status"] not in ("IN_TRANSIT", "SEALED", "DISCREPANT"):
        raise err(
            "ERR_DEPOSIT_INVALID_STATE",
            "the deposit is not awaiting a bank tie-out",
        )
    safe = domain.get_safe(deposit["safe_id"])
    store = domain.get_store(safe["store_id"])
    journal = domain.get_journal(deposit["sales_journal_id"])
    if deposit["status"] == "DISCREPANT":
        for case in db.ordered(db.variance_cases):
            if case["deposit_id"] != deposit["id"]:
                continue
            if case["status"] in domain.OPEN_CASE_STATUSES:
                raise err(
                    "ERR_VARIANCE_CASE_INVALID_STATE",
                    "the deposit's variance case must be resolved before recovery",
                )
    for record in records:
        if record["match_state"] == "MATCHED":
            raise err(
                "ERR_BANK_CREDIT_ALREADY_MATCHED",
                "bank credit record %s is already matched" % record["id"],
            )
    for record in records:
        if record["credit_type"] == "PROVISIONAL" or record["store_id"] != store["id"]:
            raise err(
                "ERR_CREDIT_TYPE_INVALID",
                "only FINAL or ADJUSTMENT records of this store may be consumed",
            )
    for record in records:
        record["match_state"] = "MATCHED"
        record["deposit_id"] = deposit["id"]
        db.touch(record)

    linked = [
        r
        for r in db.ordered(db.bank_credit_records)
        if r["deposit_id"] == deposit["id"] and r["credit_type"] in ("FINAL", "ADJUSTMENT")
    ]
    if not linked:
        raise bad_request("no FINAL or ADJUSTMENT bank credit record exists for the deposit")
    credited_total = sum(r["amount_cents"] for r in linked)
    variance = credited_total - deposit["expected_credit_cents"]
    was_discrepant = deposit["status"] == "DISCREPANT"
    deposit["credited_total_cents"] = credited_total
    deposit["credit_variance_cents"] = variance
    if variance == 0:
        deposit["status"] = "RECONCILED"
    else:
        deposit["status"] = "DISCREPANT"
        if not was_discrepant:
            domain.open_variance_case(
                case_type="DEPOSIT_CREDIT",
                sales_journal_id=journal["id"],
                total_variance_cents=abs(variance),
                store=store,
                cashier_id=None,
                deposit_id=deposit["id"],
            )
    db.touch(deposit)
    db.touch(safe)
    domain.reevaluate_journal(journal)
    db.touch(journal)
    return response.object_response(serializers.deposit(deposit))


@bp.get("/cash-ops/deposits/<deposit_id>")
@endpoint(DEPOSIT_READ_ROLES)
def read_deposit(deposit_id):
    deposit = domain.get_deposit(deposit_id)
    return response.object_response(serializers.deposit(deposit))


@bp.get("/cash-ops/deposits")
@endpoint(DEPOSIT_READ_ROLES)
def list_deposits():
    return list_collection(
        db.deposits,
        [
            ("safe_id", "safe_id"),
            ("sales_journal_id", "sales_journal_id"),
            ("status", "status"),
            ("business_date", "business_date"),
        ],
        serializers.deposit,
    )
