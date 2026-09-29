"""The reserve journal: authorisation, disbursement and reversal (PRD 3.8)."""

from flask import Blueprint

import db
import listing
import response
import store
import validators as v
from errors import err
from middleware import (ROLE_ADJUSTER, ROLE_COMPLIANCE, ROLE_UNDERWRITER, endpoint)

bp = Blueprint("ledger", __name__)

CARRIER_READERS = (ROLE_UNDERWRITER, ROLE_COMPLIANCE, ROLE_ADJUSTER)
AUTHORIZING_TYPES = ("INITIAL", "ADJUSTMENT")


@bp.post("/claims/<claim_id>/reserve-entries")
@endpoint(ROLE_ADJUSTER)
def authorize_reserve(claim_id, user_id, role):
    claim = store.get_claim(claim_id)
    body = v.body()
    entry_type = v.req_enum(body, "entry_type", AUTHORIZING_TYPES)
    amount = v.req_int(body, "amount_cents", 1)
    memo = v.opt_str(body, "memo", non_blank=False)
    expected = v.req_int(body, "expected_claim_version")
    if expected != claim["version"]:
        raise err("ERR_STALE_CLAIM_VERSION",
                  "expected_claim_version %d does not match version %d"
                  % (expected, claim["version"]))
    existing = store.entries_of_claim(claim["id"])
    if entry_type == "INITIAL":
        if any(e["entry_type"] in AUTHORIZING_TYPES for e in existing):
            raise err("ERR_INITIAL_RESERVE_ALREADY_SET",
                      "the reserve is already set; re-authorise with ADJUSTMENT")
    elif amount < claim["paid_cents"]:
        raise err("ERR_AUTHORIZATION_BELOW_DISBURSED",
                  "the authorised reserve may not fall below paid_cents")
    store.authorize_amount(claim, amount)
    row = store.append_entry(claim, entry_type, amount, user_id, memo=memo)
    store.recompute_builder(store.builder_of_claim(claim))
    db.mark(claim)
    return response.object_response(db.public(row), 201)


@bp.post("/claims/<claim_id>/payments")
@endpoint(ROLE_ADJUSTER)
def pay_claim(claim_id, user_id, role):
    claim = store.get_claim(claim_id)
    if claim["adjudicated_by_user_id"] == user_id:
        raise err("ERR_SEGREGATION_OF_DUTIES",
                  "the adjuster who adjudicated this claim may not disburse on it")
    body = v.body()
    amount = v.req_int(body, "amount_cents", 1)
    memo = v.opt_str(body, "memo", non_blank=False)
    term = store.term_of_claim(claim)
    if term is None or term["status"] != "OPEN":
        raise err("ERR_COVERAGE_LIMIT_EXHAUSTED",
                  "the claim's coverage term is not OPEN")
    if amount > claim["reserve_cents"]:
        raise err("ERR_PAYMENT_EXCEEDS_RESERVE",
                  "the payment exceeds the claim's reserve")
    if amount > term["remaining_limit_cents"]:
        raise err("ERR_COVERAGE_LIMIT_EXCEEDED",
                  "the payment exceeds the term's remaining limit")

    claim["paid_cents"] += amount
    claim["reserve_cents"] -= amount
    store.append_entry(claim, "PAYMENT", amount, user_id, memo=memo)
    term["consumed_limit_cents"] += amount
    term["remaining_limit_cents"] -= amount
    db.mark(term)
    if claim["status"] == "APPROVED" and claim["paid_cents"] == claim["net_payable_cents"]:
        claim["status"] = "CLOSED_PAID"
    builder = store.builder_of_claim(claim)
    if term["remaining_limit_cents"] == 0 and term["status"] == "OPEN":
        term["status"] = "LIMIT_EXHAUSTED"
        store.limit_exhaustion_cascade(term, claim, builder, user_id)
    else:
        store.recompute_builder(builder)
    db.mark(claim)
    return response.object_response(db.public(claim))


@bp.post("/claims/<claim_id>/payment-reversals")
@endpoint(ROLE_COMPLIANCE)
def reverse_payment(claim_id, user_id, role):
    claim = store.get_claim(claim_id)
    body = v.body()
    raw_entry_id = body.get("reserve_entry_id")
    entry = None
    if isinstance(raw_entry_id, str):
        entry = store.get_reserve_entry(raw_entry_id)
    entry_id = v.req_str(body, "reserve_entry_id")
    memo = v.opt_str(body, "memo", non_blank=False)
    if entry is None:
        entry = store.get_reserve_entry(entry_id)
    reversed_already = any(e["reversed_entry_id"] == entry["id"]
                           for e in store.entries_of_claim(claim["id"]))
    if (entry["claim_id"] != claim["id"] or entry["entry_type"] != "PAYMENT"
            or reversed_already):
        raise err("ERR_ENTRY_NOT_REVERSIBLE",
                  "the named entry is not a reversible payment of this claim")

    amount = entry["amount_cents"]
    claim["paid_cents"] -= amount
    claim["reserve_cents"] += amount
    store.append_entry(claim, "PAYMENT_REVERSAL", amount, user_id, memo=memo,
                       reversed_entry_id=entry["id"])
    term = store.term_of_claim(claim)
    if term is not None:
        term["consumed_limit_cents"] -= amount
        term["remaining_limit_cents"] += amount
        if term["status"] == "LIMIT_EXHAUSTED" and term["remaining_limit_cents"] > 0:
            term["status"] = "OPEN"
        db.mark(term)
    store.recompute_builder(store.builder_of_claim(claim))
    db.mark(claim)
    return response.object_response(db.public(claim))


@bp.get("/reserve-entries/<entry_id>")
@endpoint(*CARRIER_READERS)
def read_entry(entry_id, user_id, role):
    return response.object_response(db.public(store.get_reserve_entry(entry_id)))


@bp.get("/reserve-entries")
@endpoint(*CARRIER_READERS)
def list_entries(user_id, role):
    rows = store.all_rows(db.reserve_entries)
    rows = listing.eq_filter(rows, "claim_id")
    rows = listing.eq_filter(rows, "reversed_entry_id")
    rows = listing.eq_filter(rows, "entry_type")
    return response.paginate(rows)
