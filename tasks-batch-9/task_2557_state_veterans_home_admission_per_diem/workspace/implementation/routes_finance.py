"""Income records, cost-share determinations and the resident trust fund."""
from flask import Blueprint

import calc
import services
from calc import (
    COUNTABLE_RATE_BPS,
    INCOME_TYPES,
    determination_out,
    income_out,
    round_half_up,
    txn_out,
)
from common import (
    f_date,
    f_enum,
    f_int,
    f_month,
    f_str,
    fail,
    guard,
    json_body,
    object_response,
    pagination,
    paginate,
    q_bool,
    q_month,
    q_str,
)
from routes_residents import find_resident, own_resident
from store import clock_date, new_record, parse_date, store, touch_once

bp = Blueprint("finance", __name__)

TXN_TYPES = ("DEPOSIT", "WITHDRAWAL", "PNA_CREDIT", "COST_SHARE_DEBIT")
VARIANTS = ("PROVISIONAL", "FINAL")
VERIFICATION_DECISIONS = ("VERIFIED", "REJECTED")


def find_income(record_id):
    record = store.income_records.get(record_id)
    if record is None:
        fail("ERR_INCOME_RECORD_NOT_FOUND", "No income record with id %s." % record_id)
    return record


def find_txn(txn_id):
    txn = store.transactions.get(txn_id)
    if txn is None:
        fail("ERR_TRANSACTION_NOT_FOUND", "No trust fund transaction with id %s." % txn_id)
    return txn


# ------------------------------------------------------------------ reads ----
@bp.get("/residents/<resident_id>/income-records")
def list_income(resident_id):
    user_id, role = guard(
        "StateProgramAdmin",
        "BusinessOfficeManager",
        "FederalPerDiemAuditor",
        "ResidentRepresentative",
    )
    limit, offset = pagination()
    resident = find_resident(resident_id)
    own_resident(user_id, role, resident["id"])
    effective_month = q_month("effective_month")
    verification_status = q_str("verification_status")
    rows = [r for r in store.income_records.values() if r["resident_id"] == resident["id"]]
    if effective_month is not None:
        rows = [r for r in rows if r["effective_month"] == effective_month]
    if verification_status is not None:
        rows = [r for r in rows if r["verification_status"] == verification_status]
    rows = sorted(
        rows,
        key=lambda r: (r["effective_month"], r["income_type"], r["created_at"], r["_seq"]),
    )
    return paginate(rows, limit, offset, income_out)


@bp.get("/residents/<resident_id>/cost-share-determinations")
def list_determinations(resident_id):
    user_id, role = guard(
        "StateProgramAdmin",
        "BusinessOfficeManager",
        "FederalPerDiemAuditor",
        "ResidentRepresentative",
    )
    limit, offset = pagination()
    resident = find_resident(resident_id)
    own_resident(user_id, role, resident["id"])
    effective_month = q_month("effective_month")
    variant = q_str("variant")
    rows = calc.resident_determinations(resident["id"])
    if effective_month is not None:
        rows = [d for d in rows if d["effective_month"] == effective_month]
    if variant is not None:
        rows = [d for d in rows if d["variant"] == variant]
    rows = sorted(rows, key=lambda d: (d["effective_month"], d["created_at"], d["_seq"]))
    return paginate(rows, limit, offset, determination_out)


@bp.get("/trust-fund-transactions/<txn_id>")
def get_txn(txn_id):
    user_id, role = guard(
        "StateProgramAdmin",
        "BusinessOfficeManager",
        "FederalPerDiemAuditor",
        "ResidentRepresentative",
    )
    txn = find_txn(txn_id)
    own_resident(user_id, role, txn["resident_id"])
    return object_response(txn_out(txn))


@bp.get("/trust-fund-transactions")
def list_txns():
    user_id, role = guard(
        "StateProgramAdmin",
        "BusinessOfficeManager",
        "FederalPerDiemAuditor",
        "ResidentRepresentative",
    )
    limit, offset = pagination()
    resident_id = q_str("resident_id")
    if role == "ResidentRepresentative" and resident_id != user_id:
        fail(
            "ERR_NOT_RESOURCE_OWNER",
            "A ResidentRepresentative must scope this read to its own resident_id.",
        )
    reverses_transaction_id = q_str("reverses_transaction_id")
    txn_type = q_str("txn_type")
    reversed_flag = q_bool("reversed")
    rows = list(store.transactions.values())
    if resident_id is not None:
        rows = [t for t in rows if t["resident_id"] == resident_id]
    if reverses_transaction_id is not None:
        rows = [t for t in rows if t["reverses_transaction_id"] == reverses_transaction_id]
    if txn_type is not None:
        rows = [t for t in rows if t["txn_type"] == txn_type]
    if reversed_flag is not None:
        rows = [t for t in rows if calc.is_reversed(t) == reversed_flag]
    rows = sorted(rows, key=lambda t: (t["effective_date"], t["created_at"], t["_seq"]))
    return paginate(rows, limit, offset, txn_out)


# ------------------------------------------------------------ income records ----
@bp.post("/residents/<resident_id>/income-records")
def declare_income(resident_id):
    guard("BusinessOfficeManager")
    body = json_body()
    income_type = f_enum(body, "income_type", INCOME_TYPES)
    monthly_amount_cents = f_int(body, "monthly_amount_cents", minimum=0)
    effective_month = f_month(body, "effective_month")

    resident = find_resident(resident_id)
    if resident["occupancy_status"] == "DISCHARGED":
        fail("ERR_RESIDENT_STATE_INVALID", "A discharged resident accepts no income record.")

    rate = COUNTABLE_RATE_BPS[income_type]
    record = new_record()
    record.update(
        {
            "resident_id": resident["id"],
            "income_type": income_type,
            "monthly_amount_cents": monthly_amount_cents,
            "effective_month": effective_month,
            "countable_rate_bps": rate,
            "countable_amount_cents": round_half_up(monthly_amount_cents * rate, 10000),
            "verification_status": "UNVERIFIED",
            "verified_by_user_id": None,
        }
    )
    store.income_records[record["id"]] = record
    touch_once(resident)
    return object_response(income_out(record), 201)


@bp.post("/income-records/<record_id>/verify")
def verify_income(record_id):
    user_id, _role = guard("BusinessOfficeManager")
    body = json_body()
    decision = f_enum(body, "decision", VERIFICATION_DECISIONS)
    record = find_income(record_id)
    if record["verification_status"] != "UNVERIFIED":
        fail("ERR_INCOME_RECORD_STATE_INVALID", "This income record has already been decided.")

    record["verification_status"] = decision
    record["verified_by_user_id"] = user_id
    touch_once(record)
    resident = store.residents.get(record["resident_id"])
    if resident is not None:
        touch_once(resident)
    return object_response(income_out(record))


# ------------------------------------------------- cost share determinations ----
@bp.post("/residents/<resident_id>/cost-share-determinations")
def create_determination(resident_id):
    user_id, _role = guard("BusinessOfficeManager")
    body = json_body()
    variant = f_enum(body, "variant", VARIANTS)
    effective_month = f_month(body, "effective_month")
    expected_version = f_int(body, "expected_resident_version", minimum=0)
    declared_medical = f_int(
        body, "declared_medical_expense_cents", minimum=0, required=False, default=0
    )

    resident = find_resident(resident_id)
    if expected_version != resident["version"]:
        fail("ERR_RESIDENT_VERSION_STALE", "expected_resident_version does not match the resident.")
    if resident["occupancy_status"] == "DISCHARGED":
        fail("ERR_RESIDENT_STATE_INVALID", "A discharged resident accepts no determination.")
    if variant == "FINAL":
        verified = services.resident_income_records(
            resident["id"], effective_month, ("VERIFIED",)
        )
        if not verified:
            fail(
                "ERR_INCOME_NOT_VERIFIED",
                "A FINAL determination requires at least one VERIFIED income record for the month.",
            )

    prior = calc.governing_determination(resident["id"], effective_month)
    computed = services.compute_cost_share(resident, variant, effective_month, declared_medical)

    det = new_record(versioned=False)
    det.update(
        {
            "resident_id": resident["id"],
            "variant": variant,
            "effective_month": effective_month,
            "declared_medical_expense_cents": declared_medical,
            "determined_by_user_id": user_id,
        }
    )
    det.update(computed)
    det["delta_from_prior_cents"] = (
        0
        if prior is None
        else computed["monthly_cost_share_cents"] - prior["monthly_cost_share_cents"]
    )
    store.determinations[det["id"]] = det

    if variant == "FINAL":
        resident["billing_status"] = "FINAL_COST_SHARE"
    touch_once(resident)
    return object_response(determination_out(det), 201)


# --------------------------------------------------------------- trust fund ----
@bp.post("/residents/<resident_id>/trust-fund-transactions")
def post_txn(resident_id):
    user_id, _role = guard("BusinessOfficeManager")
    body = json_body()
    txn_type = f_enum(body, "txn_type", TXN_TYPES)
    amount_cents = f_int(body, "amount_cents", minimum=1)
    effective_date = f_date(body, "effective_date")
    memo = f_str(body, "memo", required=False)

    resident = find_resident(resident_id)
    if resident["occupancy_status"] == "DISCHARGED":
        fail("ERR_RESIDENT_STATE_INVALID", "A discharged resident accepts no trust fund posting.")
    if parse_date(effective_date) > clock_date():
        fail("ERR_DATE_OUT_OF_RANGE", "effective_date may not lie in the future.")

    signed = services.signed_amount(txn_type, amount_cents)
    projected = calc.trust_fund_balance(resident["id"]) + signed
    if txn_type == "WITHDRAWAL" and projected < 0:
        fail("ERR_TRUST_FUND_INSUFFICIENT", "The withdrawal would overdraw the trust fund.")
    if txn_type == "COST_SHARE_DEBIT":
        home = calc.home_of_resident(resident)
        reserve = home["personal_needs_allowance_monthly_cents"] if home else 0
        if projected < reserve:
            fail(
                "ERR_PNA_RESERVE_BREACH",
                "The debit would breach the personal needs allowance reserve.",
            )

    txn = services.post_transaction(
        resident, txn_type, amount_cents, effective_date, memo, user_id
    )
    return object_response(txn_out(txn), 201)


@bp.post("/trust-fund-transactions/<txn_id>/reverse")
def reverse_txn(txn_id):
    user_id, _role = guard("BusinessOfficeManager")
    body = json_body()
    memo = f_str(body, "memo", required=False)
    original = find_txn(txn_id)
    if original["txn_type"] == "REVERSAL" or calc.is_reversed(original):
        fail(
            "ERR_TRANSACTION_ALREADY_REVERSED",
            "This transaction is already reversed or is itself a reversal.",
        )
    if user_id == original["recorded_by_user_id"]:
        fail(
            "ERR_SEGREGATION_OF_DUTIES",
            "The reversing operator may not be the operator who recorded the original.",
        )

    resident = store.residents.get(original["resident_id"])
    if resident is None:
        fail("ERR_RESIDENT_NOT_FOUND", "The transaction's resident no longer exists.")
    txn = services.post_transaction(
        resident,
        "REVERSAL",
        original["amount_cents"],
        original["effective_date"],
        memo,
        user_id,
        reverses_transaction_id=original["id"],
        signed=-original["signed_amount_cents"],
    )
    return object_response(txn_out(txn), 201)
