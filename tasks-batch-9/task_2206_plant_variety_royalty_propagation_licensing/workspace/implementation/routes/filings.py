"""Protection filings and the maintenance calendar."""

import math

from flask import Blueprint

from calculations import annuity_amounts
from common import filtered, resolve, terminal, transition
from derive import (FILING_LIVE, apply, children, grace_deadline, lapse_filing,
                    recompute_protection)
from errors import ApiError
from middleware import ALL_ROLES, BREEDER_ADMIN, endpoint
from response import collection, created, ok
from store import new_id, parse_dt, store
from validation import ID, DateTime, Enum, Int, UPPER_2_4

bp = Blueprint("filings", __name__)

FILING_TERMINAL = ("LAPSED", "ABANDONED")

CREATE_SCHEMA = [
    ("variety_id", ID, True),
    ("instrument_type", Enum(["PLANT_PATENT", "PLANT_VARIETY_CERTIFICATE"]), True),
    ("jurisdiction_code", UPPER_2_4, True),
    ("term_years", Int(5, 25), False),
    ("annuity_base_cents", Int(1000), True),
]

SCHEDULE_SCHEMA = [
    ("annuity_due_date", DateTime(), True),
    ("annuity_grace_days", Int(0, 90), False),
]

PAY_SCHEMA = [
    ("paid_amount_cents", Int(0), True),
]


@endpoint(bp, "POST", "/protection-filings", [BREEDER_ADMIN], CREATE_SCHEMA)
def create_filing(actor, body):
    variety = resolve("variety_id", body["variety_id"])
    for other in children("filings", "variety_id", variety["id"]):
        if (other["instrument_type"] == body["instrument_type"]
                and other["jurisdiction_code"] == body["jurisdiction_code"]
                and other["status"] in FILING_LIVE):
            raise ApiError("ERR_DUPLICATE_FILING_JURISDICTION")
    record = {
        "id": new_id(),
        "variety_id": variety["id"],
        "instrument_type": body["instrument_type"],
        "jurisdiction_code": body["jurisdiction_code"],
        "status": "DRAFT",
        "filed_on": None,
        "granted_on": None,
        "term_years": body["term_years"] if body["term_years"] is not None else 20,
        "annuity_base_cents": body["annuity_base_cents"],
        "annuity_sequence_no": 0,
        "annuity_due_date": None,
        "annuity_grace_days": 90,
        "annuity_days_late": 0,
        "annuity_surcharge_cents": 0,
        "annuity_volume_credit_cents": 0,
        "annuity_total_due_cents": 0,
        "installments_paid_count": 0,
        "lapse_reason": None,
    }
    store.stamp_new(record)
    store.filings[record["id"]] = record
    recompute_protection(variety)
    return created(record)


@endpoint(bp, "GET", "/protection-filings", ALL_ROLES)
def list_filings(actor):
    records, limit, offset, total = filtered(
        "filings", "variety_id", "status", "jurisdiction_code")
    return collection(records, limit, offset, total)


@endpoint(bp, "GET", "/protection-filings/<filing_id>", ALL_ROLES)
def get_filing(actor, filing_id):
    return ok(resolve("filing_id", filing_id))


@endpoint(bp, "POST", "/protection-filings/<filing_id>/file", [BREEDER_ADMIN], [])
def file_filing(actor, body, filing_id):
    filing = resolve("filing_id", filing_id)
    terminal(filing["status"] in FILING_TERMINAL)
    transition(filing["status"] == "DRAFT")
    apply(filing, {"status": "FILED", "filed_on": store.now_iso()}, force=True)
    variety = store.varieties.get(filing["variety_id"])
    if variety is not None:
        recompute_protection(variety, force=True)
    return ok(filing)


@endpoint(bp, "POST", "/protection-filings/<filing_id>/grant", [BREEDER_ADMIN], [])
def grant_filing(actor, body, filing_id):
    filing = resolve("filing_id", filing_id)
    terminal(filing["status"] in FILING_TERMINAL)
    transition(filing["status"] == "FILED")
    apply(filing, {"status": "GRANTED", "granted_on": store.now_iso()}, force=True)
    variety = store.varieties.get(filing["variety_id"])
    if variety is not None:
        recompute_protection(variety, force=True)
    return ok(filing)


@endpoint(bp, "POST", "/protection-filings/<filing_id>/abandon", [BREEDER_ADMIN], [])
def abandon_filing(actor, body, filing_id):
    filing = resolve("filing_id", filing_id)
    terminal(filing["status"] in FILING_TERMINAL)
    transition(filing["status"] in ("DRAFT", "FILED"))
    apply(filing, {"status": "ABANDONED"}, force=True)
    variety = store.varieties.get(filing["variety_id"])
    if variety is not None:
        recompute_protection(variety, force=True)
    return ok(filing)


@endpoint(bp, "POST", "/protection-filings/<filing_id>/schedule-annuity",
          [BREEDER_ADMIN], SCHEDULE_SCHEMA)
def schedule_annuity(actor, body, filing_id):
    filing = resolve("filing_id", filing_id)
    terminal(filing["status"] in FILING_TERMINAL)
    transition(filing["status"] == "GRANTED")
    due = parse_dt(body["annuity_due_date"])
    if due <= store.now:
        raise ApiError("ERR_INVALID_INTERVAL")
    grace = body["annuity_grace_days"]
    apply(filing, {
        "status": "MAINTENANCE_DUE",
        "annuity_sequence_no": int(filing["annuity_sequence_no"]) + 1,
        "annuity_due_date": body["annuity_due_date"],
        "annuity_grace_days": 90 if grace is None else grace,
        "annuity_days_late": 0,
        "annuity_surcharge_cents": 0,
        "annuity_volume_credit_cents": 0,
        "annuity_total_due_cents": 0,
    }, force=True)
    variety = store.varieties.get(filing["variety_id"])
    if variety is not None:
        recompute_protection(variety)
    return ok(filing)


@endpoint(bp, "POST", "/protection-filings/<filing_id>/pay-annuity",
          [BREEDER_ADMIN], PAY_SCHEMA)
def pay_annuity(actor, body, filing_id):
    filing = resolve("filing_id", filing_id)
    terminal(filing["status"] in FILING_TERMINAL)
    transition(filing["status"] == "MAINTENANCE_DUE")
    deadline = grace_deadline(filing)
    if deadline is not None and store.now > deadline:
        raise ApiError("ERR_GRACE_PERIOD_EXPIRED")
    due = parse_dt(filing["annuity_due_date"])
    days_late = 0
    if due is not None:
        elapsed = (store.now - due).total_seconds()
        days_late = max(0, int(math.floor(elapsed / 86400.0)))
    surcharge, credit, total = annuity_amounts(filing["annuity_base_cents"], days_late)
    if int(body["paid_amount_cents"]) != total:
        raise ApiError("ERR_ANNUITY_AMOUNT_MISMATCH")
    apply(filing, {
        "status": "GRANTED",
        "annuity_days_late": days_late,
        "annuity_surcharge_cents": surcharge,
        "annuity_volume_credit_cents": credit,
        "annuity_total_due_cents": total,
        "installments_paid_count": int(filing["installments_paid_count"]) + 1,
        "granted_on": store.now_iso(),
    }, force=True)
    variety = store.varieties.get(filing["variety_id"])
    if variety is not None:
        recompute_protection(variety)
    return ok(filing)


@endpoint(bp, "POST", "/protection-filings/<filing_id>/lapse", [BREEDER_ADMIN], [])
def lapse(actor, body, filing_id):
    filing = resolve("filing_id", filing_id)
    terminal(filing["status"] in FILING_TERMINAL)
    transition(filing["status"] in ("GRANTED", "MAINTENANCE_DUE"))
    lapse_filing(filing, "VOLUNTARY_LAPSE")
    return ok(filing)
