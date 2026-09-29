"""Settlement batches, clearing-record intake, finalization and reversals
(PRD 3.5, 3.6 and 3.7)."""

from flask import Blueprint

import calc
import listing
import resolve
import validate as v
from auth import ALL_ROLES, authenticate, require_scope
from envelope import array_response, object_response, paginate
from errors import (
    ERR_ACQUIRER_NON_COMPLIANT,
    ERR_BATCH_NOT_OPEN,
    ERR_CLEARING_BEFORE_AUTH,
    ERR_DUPLICATE_RESOURCE,
    ERR_INVALID_STATE,
    ERR_MERCHANT_MISREPRESENTED,
    ERR_STALE_VERSION,
    fail,
)
from store import (
    DATA_ELEMENT_VOCAB,
    new_row,
    serialize,
    serialize_many,
    sorted_rows,
    store,
    touch,
)

bp = Blueprint("clearing", __name__)

MAX_AMOUNT_CENTS = 100000000000


# ---------------------------------------------------------------------------
# Settlement batches
# ---------------------------------------------------------------------------

@bp.post("/settlement-batches")
def open_batch():
    caller = authenticate(["AcquirerOps", "NetworkAdmin"])
    data = v.body()

    acquirer_id = v.raw_id(data, "acquirer_id")
    if acquirer_id is not None:
        resolve.acquirer(acquirer_id)

    fields = {
        "acquirer_id": v.req_str(data, "acquirer_id"),
        "batch_date": v.req_date(data, "batch_date"),
        "currency_code": v.req_currency(data, "currency_code"),
        "status": "OPEN",
        "record_count": 0,
        "total_assessed_cents": 0,
        "finalized_at": None,
    }
    require_scope(caller, fields["acquirer_id"])

    for existing in store.batches.values():
        if (existing["acquirer_id"] == fields["acquirer_id"]
                and existing["batch_date"] == fields["batch_date"]
                and existing["currency_code"] == fields["currency_code"]):
            fail(ERR_DUPLICATE_RESOURCE,
                 "That acquirer already has a batch for that date and currency.")

    row = new_row(fields)
    store.batches[row["id"]] = row
    return object_response(serialize("SettlementBatch", row), 201)


@bp.get("/settlement-batches/<row_id>")
def get_batch(row_id):
    caller = authenticate(ALL_ROLES)
    row = resolve.batch(row_id)
    require_scope(caller, row["acquirer_id"])
    return object_response(serialize("SettlementBatch", row))


@bp.get("/settlement-batches")
def list_batches():
    authenticate(ALL_ROLES)
    rows = sorted_rows(list(store.batches.values()))
    rows = listing.apply_string_filters(rows, [
        ("acquirer_id", "acquirer_id"),
        ("status", "status"),
        ("batch_date", "batch_date"),
    ])
    page, meta = paginate(rows)
    return array_response(serialize_many("SettlementBatch", page), meta)


@bp.post("/settlement-batches/<row_id>/submit")
def submit_batch(row_id):
    caller = authenticate(["AcquirerOps", "NetworkAdmin"])
    batch = resolve.batch(row_id)
    require_scope(caller, batch["acquirer_id"])
    if batch["status"] != "OPEN":
        fail(ERR_INVALID_STATE, "Only an OPEN batch may be submitted.")
    batch["status"] = "SUBMITTED"
    touch(batch)
    return object_response(serialize("SettlementBatch", batch))


# ---------------------------------------------------------------------------
# Clearing-record intake
# ---------------------------------------------------------------------------

@bp.post("/settlement-batches/<batch_id>/transaction-records")
def add_record(batch_id):
    caller = authenticate(["AcquirerOps", "NetworkAdmin"])
    batch = resolve.batch(batch_id)
    data = v.body()

    merchant_id = v.raw_id(data, "merchant_id")
    if merchant_id is not None:
        resolve.merchant(merchant_id)

    fields = {
        "settlement_batch_id": batch["id"],
        "merchant_id": v.req_str(data, "merchant_id"),
        "amount_cents": v.req_int(data, "amount_cents", 1, MAX_AMOUNT_CENTS),
        "transaction_currency": v.req_currency(data, "transaction_currency"),
        "auth_code": v.req_str(data, "auth_code", 6, 6),
        "auth_timestamp": v.req_ts(data, "auth_timestamp"),
        "clearing_timestamp": v.req_ts(data, "clearing_timestamp"),
        "data_elements": v.req_code_list(
            data, "data_elements", DATA_ELEMENT_VOCAB, required=False, default=[],
        ),
    }
    expected = v.req_int(data, "expected_batch_version")

    require_scope(caller, batch["acquirer_id"])

    if batch["status"] != "OPEN":
        fail(ERR_BATCH_NOT_OPEN)
    if expected != int(batch["version"]):
        fail(ERR_STALE_VERSION)

    merchant = store.merchants[fields["merchant_id"]]
    if merchant["mcc_status"] == "MISREPRESENTED":
        fail(ERR_MERCHANT_MISREPRESENTED)

    if fields["clearing_timestamp"] < fields["auth_timestamp"]:
        fail(ERR_CLEARING_BEFORE_AUTH)

    for existing in calc.records_of_batch(batch["id"]):
        if existing["auth_code"] == fields["auth_code"]:
            fail(ERR_DUPLICATE_RESOURCE, "auth_code is already present in this batch.")

    acquirer = store.acquirers.get(batch["acquirer_id"])
    fields.update({
        "authorization_status": "AUTH_APPROVED",
        "qualification_status": "PENDING",
        "clearing_delay_hours": calc.clearing_delay_hours(
            fields["auth_timestamp"], fields["clearing_timestamp"]),
        "cross_border": bool(
            acquirer is not None
            and merchant["home_country_code"] != acquirer["country_code"]),
        "provisional_rate_program_id": None,
        "qualified_rate_program_id": None,
        "provisional_assessed_cents": 0,
        "assessed_interchange_cents": 0,
        "cross_border_surcharge_cents": 0,
        "fx_markup_cents": 0,
        "downgrade_reason": None,
        "mcc_at_qualification": None,
        "reversal_type": None,
        "reversal_reason": None,
    })

    program, provisional = calc.provisional_pass(fields, batch, merchant)
    fields["provisional_rate_program_id"] = program["id"]
    fields["provisional_assessed_cents"] = provisional

    row = new_row(fields)
    store.records[row["id"]] = row
    calc.recompute_batch_totals(batch)
    return object_response(serialize("TransactionRecord", row), 201)


# ---------------------------------------------------------------------------
# Finalization
# ---------------------------------------------------------------------------

@bp.post("/settlement-batches/<row_id>/finalize")
def finalize_batch(row_id):
    authenticate(["NetworkAdmin"])
    batch = resolve.batch(row_id)
    if batch["status"] != "SUBMITTED":
        fail(ERR_INVALID_STATE, "Only a SUBMITTED batch may be finalized.")
    acquirer = store.acquirers.get(batch["acquirer_id"])
    if acquirer is not None and acquirer["compliance_status"] != "COMPLIANT":
        fail(ERR_ACQUIRER_NON_COMPLIANT)

    # Nothing is committed until every record has produced a result.
    results = calc.definitive_pass(batch)

    batch["status"] = "FINALIZED"
    batch["finalized_at"] = store.now_ms()
    touch(batch)

    merchants = []
    for result in results:
        record = result["record"]
        record["qualification_status"] = result["status"]
        record["qualified_rate_program_id"] = result["program"]["id"]
        record["mcc_at_qualification"] = result["mcc_code"]
        record["assessed_interchange_cents"] = result["total"]
        record["cross_border_surcharge_cents"] = result["surcharge"]
        record["fx_markup_cents"] = result["markup"]
        record["downgrade_reason"] = result["reason"]
        touch(record)
        merchant = result["merchant"]
        if merchant is not None and all(m["id"] != merchant["id"] for m in merchants):
            merchants.append(merchant)

    calc.recompute_batch_totals(batch)

    merchants = sorted_rows(merchants)
    for merchant in merchants:
        calc.recompute_merchant_ledger(merchant)
    calc.run_downgrade_tripwire(merchants)

    return object_response(serialize("SettlementBatch", batch))


# ---------------------------------------------------------------------------
# Reversals across the two independent dimensions
# ---------------------------------------------------------------------------

@bp.post("/transaction-records/<row_id>/reverse")
def reverse_record(row_id):
    caller = authenticate(["AcquirerOps", "NetworkAdmin"])
    record = resolve.record(row_id)
    data = v.body()
    reversal_type = v.req_enum(data, "reversal_type", ("AUTH_REVERSAL", "CLEARING_REVERSAL"))
    reason = v.req_str(data, "reversal_reason", 1, 1000)

    batch = store.batches.get(record["settlement_batch_id"])
    require_scope(caller, batch["acquirer_id"] if batch else None)

    if reversal_type == "AUTH_REVERSAL":
        if record["authorization_status"] != "AUTH_APPROVED":
            fail(ERR_INVALID_STATE, "Only an AUTH_APPROVED record may be authorization-reversed.")
        record["authorization_status"] = "AUTH_REVERSED"
        record["reversal_type"] = reversal_type
        record["reversal_reason"] = reason
        touch(record)
        return object_response(serialize("TransactionRecord", record))

    if record["qualification_status"] not in ("QUALIFIED", "DOWNGRADED"):
        fail(ERR_INVALID_STATE,
             "Only a QUALIFIED or DOWNGRADED record may be clearing-reversed.")
    record["qualification_status"] = "REVERSED"
    record["assessed_interchange_cents"] = 0
    record["cross_border_surcharge_cents"] = 0
    record["fx_markup_cents"] = 0
    record["reversal_type"] = reversal_type
    record["reversal_reason"] = reason
    touch(record)
    if batch is not None:
        calc.recompute_batch_totals(batch)
    merchant = store.merchants.get(record["merchant_id"])
    if merchant is not None:
        calc.recompute_merchant_ledger(merchant)
    return object_response(serialize("TransactionRecord", record))


@bp.get("/transaction-records/<row_id>")
def get_record(row_id):
    caller = authenticate(ALL_ROLES)
    record = resolve.record(row_id)
    batch = store.batches.get(record["settlement_batch_id"])
    require_scope(caller, batch["acquirer_id"] if batch else None)
    return object_response(serialize("TransactionRecord", record))


@bp.get("/transaction-records")
def list_records():
    authenticate(ALL_ROLES)
    rows = sorted_rows(list(store.records.values()))
    rows = listing.apply_string_filters(rows, [
        ("settlement_batch_id", "settlement_batch_id"),
        ("merchant_id", "merchant_id"),
        ("provisional_rate_program_id", "provisional_rate_program_id"),
        ("qualified_rate_program_id", "qualified_rate_program_id"),
        ("qualification_status", "qualification_status"),
        ("authorization_status", "authorization_status"),
    ])
    page, meta = paginate(rows)
    return array_response(serialize_many("TransactionRecord", page), meta)
