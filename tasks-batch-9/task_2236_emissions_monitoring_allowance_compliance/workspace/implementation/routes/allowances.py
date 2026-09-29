"""Allowance accounts, the compliance-deadline true-up, and the allowance
transaction ledger (PRD 3.9).
"""

from flask import Blueprint

from constants import (
    ACCOUNT_STATUSES,
    API_PREFIX,
    MIN_COMPLIANCE_YEAR,
    PROGRAMS,
    ROLE_ALLOWANCE_TRADER,
    ROLE_DESIGNATED_REP,
    ROLE_REGULATORY_REVIEWER,
    TRANSACTION_ACTIONS,
    TRANSACTION_ORIGINS,
    TRANSACTION_STATUSES,
    TRANSACTION_TYPES,
    TRANSFER_TYPES,
)
from db import base_record, db, public, public_list, sort_rows, touch
from errors import fail
from lookup import accounts_of_facility, get, units_of_facility
from middleware import ANY_ROLE, authenticate
from response import array_response, object_response
from services import allowances
from validation import (
    apply_pagination,
    body_dict,
    check_range,
    enum_field,
    id_field,
    int_field,
    match_filters,
    num_field,
    pagination,
    query_filters,
    str_field,
)
from util import D

bp = Blueprint("allowances", __name__)


def _facility_of_account(account):
    return db.facilities.get(account["facility_id"])


# ---------------------------------------------------------------------------
# accounts
# ---------------------------------------------------------------------------

@bp.route(API_PREFIX + "/facilities/<facility_id>/allowance-accounts", methods=["POST"])
def open_account(facility_id):
    authenticate((ROLE_REGULATORY_REVIEWER,))
    body = body_dict()

    program = enum_field(body, "program", PROGRAMS, required=True)
    compliance_year = int_field(body, "compliance_year", required=True)
    current = num_field(body, "holdings_current_vintage_tons", required=True)
    prior = num_field(body, "holdings_prior_vintage_tons", required=True)
    nxt = num_field(body, "holdings_next_vintage_tons", required=True)

    facility = get("facility", facility_id)

    if program not in (facility.get("programs") or []):
        fail("ERR_INVALID_REQUEST", "The program is not held by this facility.")

    for existing in accounts_of_facility(facility["id"]):
        if existing["program"] == program and existing["compliance_year"] == compliance_year:
            fail(
                "ERR_DUPLICATE_ALLOWANCE_ACCOUNT",
                "This facility already holds that program for that compliance year.",
            )

    check_range("compliance_year", compliance_year, minimum=MIN_COMPLIANCE_YEAR)
    check_range("holdings_current_vintage_tons", current, minimum=0)
    check_range("holdings_prior_vintage_tons", prior, minimum=0)
    check_range("holdings_next_vintage_tons", nxt, minimum=0)

    account = base_record()
    account.update(
        {
            "facility_id": facility["id"],
            "program": program,
            "compliance_year": compliance_year,
            "holdings_current_vintage_tons": float(current),
            "holdings_prior_vintage_tons": float(prior),
            "holdings_next_vintage_tons": float(nxt),
            "obligation_tons": 0,
            "surrendered_tons": 0.0,
            "penalty_deducted_tons": 0.0,
            "shortfall_tons": 0.0,
            "status": "OPEN",
            "true_up_utc": None,
        }
    )
    db.allowance_accounts[account["id"]] = account
    return object_response(public(account), 201)


@bp.route(API_PREFIX + "/allowance-accounts", methods=["GET"])
def list_accounts():
    authenticate(ANY_ROLE)
    filters = query_filters(
        {
            "facility_id": "str",
            "program": PROGRAMS,
            "compliance_year": "int",
            "status": ACCOUNT_STATUSES,
        }
    )
    limit, offset = pagination()
    rows = match_filters(list(db.allowance_accounts.values()), filters)
    rows = sort_rows(rows)
    return array_response(
        public_list(apply_pagination(rows, limit, offset)), limit, offset, len(rows)
    )


@bp.route(API_PREFIX + "/allowance-accounts/<account_id>", methods=["GET"])
def read_account(account_id):
    authenticate(ANY_ROLE)
    return object_response(public(get("allowance_account", account_id)))


@bp.route(API_PREFIX + "/allowance-accounts/<account_id>/true-up", methods=["POST"])
def true_up(account_id):
    authenticate((ROLE_REGULATORY_REVIEWER,))
    body_dict()

    account = get("allowance_account", account_id)
    if account["status"] != "OPEN":
        fail("ERR_INVALID_STATE_TRANSITION", "Only an OPEN account may be trued up.")

    facility = _facility_of_account(account)
    deadline = facility.get("_true_up_deadline") if facility else None
    if deadline is not None and db.now() < deadline:
        fail("ERR_TRUE_UP_BEFORE_DEADLINE", "The compliance deadline has not been reached.")

    unit_ids = {u["id"] for u in units_of_facility(account["facility_id"])}
    for report in db.quarterly_reports.values():
        if report["unit_id"] not in unit_ids:
            continue
        if report["year"] != account["compliance_year"]:
            continue
        if report["status"] != "ACCEPTED":
            fail(
                "ERR_REPORTS_NOT_ALL_ACCEPTED",
                "Every quarterly report of the compliance year must be ACCEPTED.",
            )

    allowances.run_true_up(account, facility)
    return object_response(public(account))


# ---------------------------------------------------------------------------
# transactions
# ---------------------------------------------------------------------------

@bp.route(API_PREFIX + "/allowance-transactions", methods=["POST"])
def propose_transaction():
    authenticate((ROLE_ALLOWANCE_TRADER,))
    body = body_dict()

    expected_version = int_field(body, "expected_allowance_account_version", required=True)
    account_id = id_field(body, "allowance_account_id", required=True)
    transaction_type = enum_field(body, "transaction_type", TRANSACTION_TYPES, required=True)
    quantity = num_field(body, "quantity_tons", required=True)
    vintage_year = int_field(body, "vintage_year", required=True)
    counterparty_id = id_field(body, "counterparty_account_id")

    account = get("allowance_account", account_id)
    counterparty = None
    if counterparty_id is not None:
        counterparty = get("allowance_account", counterparty_id)

    if expected_version != account["version"]:
        fail(
            "ERR_STALE_ACCOUNT_VERSION",
            "expected_allowance_account_version does not match the stored version.",
        )

    if account["status"] in ("TRUE_UP_LOCKED", "CLOSED"):
        fail("ERR_ACCOUNT_TRUE_UP_LOCKED", "The account is locked to client proposals.")

    if D(quantity) <= 0:
        fail("ERR_INVALID_QUANTITY", "quantity_tons must be strictly greater than zero.")

    if transaction_type == "PENALTY_DEDUCTION":
        fail(
            "ERR_PENALTY_TRANSACTION_NOT_CLIENT_CREATABLE",
            "Only the true-up cascade may create a penalty deduction.",
        )

    if transaction_type in TRANSFER_TYPES:
        if counterparty is None:
            fail("ERR_INVALID_COUNTERPARTY", "A transfer requires a counterparty_account_id.")
        if counterparty["id"] == account["id"]:
            fail("ERR_INVALID_COUNTERPARTY", "The counterparty must be a different account.")
        if counterparty["program"] != account["program"]:
            fail("ERR_INVALID_COUNTERPARTY", "Allowances never cross program boundaries.")
    elif counterparty is not None:
        fail("ERR_INVALID_COUNTERPARTY", "This transaction type may not carry a counterparty.")

    year = account["compliance_year"]
    if vintage_year < year - 1 or vintage_year > year + 1:
        fail(
            "ERR_VINTAGE_YEAR_INVALID",
            "vintage_year must lie within one year of the account's compliance year.",
        )

    txn = allowances.new_transaction(
        account,
        transaction_type,
        quantity,
        vintage_year,
        "PROPOSED",
        "MANUAL",
        counterparty_id=counterparty["id"] if counterparty else None,
    )
    return object_response(public(txn), 201)


@bp.route(API_PREFIX + "/allowance-transactions", methods=["GET"])
def list_transactions():
    authenticate(ANY_ROLE)
    filters = query_filters(
        {
            "allowance_account_id": "str",
            "counterparty_account_id": "str",
            "transaction_type": TRANSACTION_TYPES,
            "status": TRANSACTION_STATUSES,
            "origin": TRANSACTION_ORIGINS,
            "vintage_year": "int",
        }
    )
    limit, offset = pagination()
    rows = match_filters(list(db.allowance_transactions.values()), filters)
    rows = sort_rows(rows)
    return array_response(
        public_list(apply_pagination(rows, limit, offset)), limit, offset, len(rows)
    )


@bp.route(API_PREFIX + "/allowance-transactions/<transaction_id>", methods=["GET"])
def read_transaction(transaction_id):
    authenticate(ANY_ROLE)
    return object_response(public(get("allowance_transaction", transaction_id)))


@bp.route(API_PREFIX + "/allowance-transactions/<transaction_id>/transition", methods=["POST"])
def transition_transaction(transaction_id):
    authenticate((ROLE_DESIGNATED_REP,))
    body = body_dict()

    action = enum_field(body, "action", TRANSACTION_ACTIONS, required=True)
    reason = str_field(body, "reason")

    txn = get("allowance_transaction", transaction_id)
    account = get("allowance_account", txn["allowance_account_id"])
    facility = _facility_of_account(account)
    counterparty = (
        db.allowance_accounts.get(txn["counterparty_account_id"])
        if txn.get("counterparty_account_id")
        else None
    )

    if action == "RECORD":
        if txn["status"] != "PROPOSED":
            fail("ERR_INVALID_STATE_TRANSITION", "Only a PROPOSED transaction may be recorded.")
        txn["status"] = "RECORDED"
        touch(txn)
        return object_response(public(txn))

    if action == "SETTLE":
        if txn["status"] != "RECORDED":
            fail("ERR_INVALID_STATE_TRANSITION", "Only a RECORDED transaction may be settled.")
        if account["status"] in ("TRUE_UP_LOCKED", "CLOSED"):
            fail("ERR_ACCOUNT_TRUE_UP_LOCKED", "The account is locked to settlement.")
        if txn["transaction_type"] in ("SURRENDER", "TRANSFER_OUT"):
            available = D(account["holdings_prior_vintage_tons"]) + D(
                account["holdings_current_vintage_tons"]
            )
            if D(txn["quantity_tons"]) > available:
                fail(
                    "ERR_INSUFFICIENT_ALLOWANCES",
                    "The banked and current buckets do not cover this quantity.",
                )
        allowances.settle_transaction(txn, account, counterparty, facility)
        return object_response(public(txn))

    # REVERSE
    if txn["status"] not in ("RECORDED", "SETTLED"):
        fail(
            "ERR_INVALID_STATE_TRANSITION",
            "Only a RECORDED or SETTLED transaction may be reversed.",
        )
    if reason is None or not reason.strip():
        fail("ERR_REASON_REQUIRED", "reason is required to reverse a transaction.")

    if txn["status"] == "RECORDED":
        # nothing was ever debited, so no holdings move
        txn["reversal_reason"] = reason
        txn["status"] = "REVERSED"
        touch(txn)
        return object_response(public(txn))

    allowances.reverse_settled_transaction(txn, account, facility, reason)
    return object_response(public(txn))
