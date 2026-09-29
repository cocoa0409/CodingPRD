"""Tax filing lines and the filing calendar (PRD 3.9)."""

from flask import Blueprint

import auth
import clock
import ledger
import licensing
import serialize
import store
import validation
from calc import filing
from envelope import created, ok
from errors import ApiError
from routes.common import arg, filtered, list_response
from store import db, touch

bp = Blueprint("filing", __name__)


# --- tax filing lines -----------------------------------------------------

@bp.get("/tax-filing-lines/<rec_id>")
def get_line(rec_id):
    auth.require(auth.ANY)
    rec = auth.path_entity("tax_filing_lines", "tax_filing_line", rec_id)
    return ok(serialize.public(rec))


@bp.get("/tax-filing-lines")
def list_lines():
    auth.require(auth.ANY)
    rows = filtered(db.all("tax_filing_lines"),
                    policy_id=arg("policy_id"),
                    state_program_id=arg("state_program_id"),
                    filing_batch_id=arg("filing_batch_id"),
                    source_endorsement_id=arg("source_endorsement_id"),
                    source_cancellation_id=arg("source_cancellation_id"),
                    status=arg("status"),
                    period_key=arg("period_key"),
                    line_type=arg("line_type"))
    return list_response(rows)


# --- filing batches -------------------------------------------------------

@bp.post("/filing-batches")
def create_batch():
    auth.require("TaxFiler")
    data = validation.body()
    # Rung 5: state_program_id is declared before broker_id.
    program = auth.body_fk(data, "state_program_id", "state_programs",
                           "state_program")
    broker = auth.body_fk(data, "broker_id", "brokers", "broker")
    validation.req_str(data, "state_program_id")
    validation.req_str(data, "broker_id")
    period_key = validation.req_str(data, "period_key")

    rec = db.insert("filing_batches", {
        "state_program_id": program["id"],
        "broker_id": broker["id"],
        "period_key": period_key,
        "status": "OPEN",
        "prepared_by_user_id": None,
        "remitted_by_user_id": None,
        "line_count": 0,
        "total_tax_cents": 0,
        "total_stamping_fee_cents": 0,
        "penalty_cents": 0,
        "total_due_cents": 0,
        "due_date": None,
        "late": False,
    })
    return created(serialize.public(rec))


@bp.get("/filing-batches/<rec_id>")
def get_batch(rec_id):
    auth.require(auth.ANY)
    rec = auth.path_entity("filing_batches", "filing_batch", rec_id)
    return ok(serialize.public(rec))


@bp.get("/filing-batches")
def list_batches():
    auth.require(auth.ANY)
    rows = filtered(db.all("filing_batches"),
                    state_program_id=arg("state_program_id"),
                    broker_id=arg("broker_id"), status=arg("status"),
                    period_key=arg("period_key"))
    return list_response(rows)


@bp.post("/filing-batches/<rec_id>/prepare")
def prepare_batch(rec_id):
    auth.require("TaxFiler")
    batch = auth.path_entity("filing_batches", "filing_batch", rec_id)
    if batch.get("status") != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "Only an OPEN batch may be prepared.")

    program = db.get("state_programs", batch.get("state_program_id"))
    frequency = (program or {}).get("filing_frequency")
    if not filing.period_key_valid(batch.get("period_key"), frequency):
        raise ApiError("ERR_PERIOD_KEY_MALFORMED",
                       "period_key %r does not match the %s filing calendar."
                       % (batch.get("period_key"), frequency))

    lines = filing.sweepable_lines(batch)
    for line in lines:
        line["filing_batch_id"] = batch["id"]
        line["status"] = "BATCHED"
        touch(line)

    count, total_tax, total_fee = filing.totals(lines)
    due = filing.due_date(batch.get("period_key"), program)
    late = clock.now() > due
    penalty = filing.penalty_for(total_tax, late)

    batch["line_count"] = count
    batch["total_tax_cents"] = total_tax
    batch["total_stamping_fee_cents"] = total_fee
    batch["due_date"] = clock.fmt(due)
    batch["late"] = late
    batch["penalty_cents"] = penalty
    batch["total_due_cents"] = total_tax + total_fee + penalty
    batch["prepared_by_user_id"] = auth.user_id()
    batch["status"] = "PREPARED"
    touch(batch)
    return ok(serialize.public(batch))


@bp.post("/filing-batches/<rec_id>/submit")
def submit_batch(rec_id):
    auth.require("TaxFiler")
    batch = auth.path_entity("filing_batches", "filing_batch", rec_id)
    if batch.get("status") != "PREPARED":
        raise ApiError("ERR_INVALID_STATE", "Only a PREPARED batch may be filed.")
    if int(batch.get("line_count") or 0) <= 0:
        raise ApiError("ERR_BATCH_EMPTY", "The batch holds no filing lines.")

    program = db.get("state_programs", batch.get("state_program_id"))
    state_code = (program or {}).get("state_code")
    if not licensing.has_active_surplus_lines(batch.get("broker_id"), state_code):
        raise ApiError("ERR_BROKER_LICENSE_NOT_ACTIVE",
                       "The brokerage holds no ACTIVE surplus lines licence in %s."
                       % state_code)

    lines = store.lines_of_batch(batch["id"])
    filed = []
    for line in lines:
        if line.get("status") == "BATCHED":
            line["status"] = "FILED"
            touch(line)
            filed.append(line)

    batch["status"] = "SUBMITTED"
    touch(batch)
    ledger.advance_policies_after_filing(filed)
    return ok(serialize.public(batch))


@bp.post("/filing-batches/<rec_id>/remit")
def remit_batch(rec_id):
    auth.require("TaxFiler")
    batch = auth.path_entity("filing_batches", "filing_batch", rec_id)
    data = validation.body()
    amount = validation.req_int(data, "remitted_amount_cents")

    if batch.get("status") != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "Only a SUBMITTED batch may be remitted.")
    if auth.user_id() == batch.get("prepared_by_user_id"):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The remitter must differ from the preparer of the batch.")
    if amount != int(batch.get("total_due_cents") or 0):
        raise ApiError("ERR_REMITTANCE_AMOUNT_MISMATCH",
                       "remitted_amount_cents must equal the batch total of %d."
                       % int(batch.get("total_due_cents") or 0))

    remitted = []
    for line in store.lines_of_batch(batch["id"]):
        if line.get("status") == "FILED":
            line["status"] = "REMITTED"
            touch(line)
            remitted.append(line)

    batch["remitted_by_user_id"] = auth.user_id()
    batch["status"] = "REMITTED"
    touch(batch)
    ledger.advance_policies_after_remittance(remitted)
    return ok(serialize.public(batch))
