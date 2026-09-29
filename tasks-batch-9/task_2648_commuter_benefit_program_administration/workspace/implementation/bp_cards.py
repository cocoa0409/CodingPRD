"""Card transactions, their substantiation posture and the documentation claims."""

from flask import Blueprint

import serialize
from auth import (
    authenticate,
    require_employee_scope,
    resolve_claim,
    resolve_election,
    resolve_transaction,
)
from calc import (
    MAX_SUBSTANTIATION_REOPENS,
    post_entry,
    substantiation_posture,
)
from cascades import deny_cascade, reopen_from_ineligible
from errors import fail
from guards import (
    TERMINAL_CLAIM,
    owner_of_claim,
    owner_of_transaction,
    require_balance,
    require_distinct_operator,
    require_not_terminal,
    require_transition,
)
from responses import array_response, created_response, object_response, paginate
from store import bump, sorted_rows, stamp_new, store
from validate import (
    CLAIM_STATUSES,
    DOC_TYPES,
    REJECTION_REASONS,
    SUBSTANTIATION_STATUSES,
    enum_filter,
    field,
    pagination,
    parse_body,
    str_filter,
)

bp = Blueprint("cards", __name__)

REOPENABLE_STATUSES = ("AUTO_SUBSTANTIATED", "SUBSTANTIATED", "INELIGIBLE")
APPROVED_POSTURES = ("AUTO_SUBSTANTIATED", "SUBSTANTIATED")


# ------------------------------------------------------------- CardTransaction
@bp.post("/benefits/card-transactions")
def create_transaction():
    authenticate(["ProgramAdmin"])
    specs = [
        field("election_id", "id", required=True),
        field("amount_cents", "integer", required=True, minimum=1),
        field("merchant_category_code", "integer", required=True,
              minimum=1000, maximum=9999),
        field("merchant_name", "string", required=True, min_len=1, max_len=120),
        field("transaction_at", "datetime", required=True),
    ]
    body, values = parse_body(specs)
    election = resolve_election(values["election_id"])
    category = store.benefit_categories.get(election["benefit_category_id"])
    account = store.benefit_accounts.get(election["benefit_account_id"])
    if account is None:
        fail("ERR_BENEFIT_ACCOUNT_NOT_FOUND",
             "The election does not reference a resolvable benefit account.")

    status, posted = substantiation_posture(category, values["amount_cents"],
                                           values["merchant_category_code"])

    # ladder 33 - the balance gate applies only to an eligible swipe
    if status != "INELIGIBLE":
        require_balance(account, values["amount_cents"])

    row = {
        "election_id": election["id"],
        "benefit_account_id": account["id"],
        "amount_cents": values["amount_cents"],
        "merchant_category_code": values["merchant_category_code"],
        "merchant_name": values["merchant_name"],
        "transaction_at": body["transaction_at"],
        "_transaction_at": values["transaction_at"],
        "substantiation_status": status,
        "posted_spend_cents": posted,
        "reopen_count": 0,
        "approved_by_user_id": None,
        "denied_by_user_id": None,
    }
    stamp_new(row)
    store.card_transactions[row["id"]] = row

    if posted > 0:
        account["spent_cents"] += posted
        post_entry(account, "SPEND", -posted, "CardTransaction", row["id"],
                   "Commuter debit card swipe posted against the benefit account.")
        bump(account)
    return created_response(serialize.card_transaction(row))


@bp.get("/benefits/card-transactions/<transaction_id>")
def read_transaction(transaction_id):
    authenticate(["ProgramAdmin", "Employee", "ComplianceReviewer"])
    row = resolve_transaction(transaction_id)
    return object_response(serialize.card_transaction(row))


@bp.get("/benefits/card-transactions")
def list_transactions():
    authenticate(["ProgramAdmin", "Employee", "ComplianceReviewer"])
    election_id = str_filter("election_id")
    account_id = str_filter("benefit_account_id")
    status = enum_filter("substantiation_status", SUBSTANTIATION_STATUSES)
    limit, offset = pagination()
    rows = []
    for row in store.card_transactions.values():
        if election_id is not None and row["election_id"] != election_id:
            continue
        if account_id is not None and row["benefit_account_id"] != account_id:
            continue
        if status is not None and row["substantiation_status"] != status:
            continue
        rows.append(row)
    rows = sorted_rows(rows)
    page, total = paginate(rows, limit, offset)
    return array_response([serialize.card_transaction(r) for r in page],
                         limit, offset, total)


@bp.post("/benefits/card-transactions/<transaction_id>/deny-substantiation")
def deny_substantiation(transaction_id):
    principal = authenticate(["ComplianceReviewer"])
    row = resolve_transaction(transaction_id)
    _body, _values = parse_body([field("reason", "string", required=True,
                                       min_len=1)])
    require_transition(row["substantiation_status"] == "PENDING_DOCS",
                       "CardTransaction %s cannot be denied from substantiation "
                       "status %s." % (row["id"], row["substantiation_status"]))
    deny_cascade(row, principal.user_id)
    return object_response(serialize.card_transaction(row))


@bp.post("/benefits/card-transactions/<transaction_id>/reopen")
def reopen_transaction(transaction_id):
    principal = authenticate(["ComplianceReviewer"])
    row = resolve_transaction(transaction_id)
    _body, _values = parse_body([field("reason", "string", required=True,
                                       min_len=1)])
    require_transition(row["substantiation_status"] in REOPENABLE_STATUSES,
                       "CardTransaction %s cannot be reopened from substantiation "
                       "status %s." % (row["id"], row["substantiation_status"]))

    # ladder 16 - segregation of duties, only from an approved posture
    if row["substantiation_status"] in APPROVED_POSTURES:
        require_distinct_operator(
            principal.user_id, row["approved_by_user_id"],
            "The reviewer that approved the substantiation of CardTransaction %s "
            "may not also reopen it." % row["id"])

    # ladder 30
    if row["reopen_count"] >= MAX_SUBSTANTIATION_REOPENS:
        fail("ERR_REOPEN_LIMIT_EXCEEDED",
             "CardTransaction %s has already been reopened the maximum number of "
             "times." % row["id"])

    if row["substantiation_status"] == "INELIGIBLE":
        reopen_from_ineligible(row)
    else:
        row["substantiation_status"] = "PENDING_DOCS"
        row["reopen_count"] += 1
        bump(row)
    return object_response(serialize.card_transaction(row))


# --------------------------------------------------------- SubstantiationClaim
@bp.post("/benefits/substantiation-claims")
def create_claim():
    principal = authenticate(["Employee", "ProgramAdmin"])
    specs = [
        field("card_transaction_id", "id", required=True),
        field("claimed_amount_cents", "integer", required=True, minimum=1),
        field("doc_type", "enum", required=True, choices=DOC_TYPES),
    ]
    _body, values = parse_body(specs)
    transaction = resolve_transaction(values["card_transaction_id"])
    require_employee_scope(principal, owner_of_transaction(transaction))
    row = {
        "card_transaction_id": transaction["id"],
        "claimed_amount_cents": values["claimed_amount_cents"],
        "doc_type": values["doc_type"],
        "status": "SUBMITTED",
        "reviewed_by_user_id": None,
        "rejection_reason": None,
    }
    stamp_new(row)
    store.substantiation_claims[row["id"]] = row
    return created_response(serialize.substantiation_claim(row))


@bp.get("/benefits/substantiation-claims/<claim_id>")
def read_claim(claim_id):
    authenticate(["Employee", "ProgramAdmin", "ComplianceReviewer"])
    row = resolve_claim(claim_id)
    return object_response(serialize.substantiation_claim(row))


@bp.get("/benefits/substantiation-claims")
def list_claims():
    authenticate(["Employee", "ProgramAdmin", "ComplianceReviewer"])
    transaction_id = str_filter("card_transaction_id")
    status = enum_filter("status", CLAIM_STATUSES)
    limit, offset = pagination()
    rows = []
    for row in store.substantiation_claims.values():
        if transaction_id is not None and row["card_transaction_id"] != transaction_id:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    rows = sorted_rows(rows)
    page, total = paginate(rows, limit, offset)
    return array_response([serialize.substantiation_claim(r) for r in page],
                         limit, offset, total)


@bp.post("/benefits/substantiation-claims/<claim_id>/approve")
def approve_claim(claim_id):
    principal = authenticate(["ComplianceReviewer"])
    row = resolve_claim(claim_id)
    transaction = store.card_transactions.get(row["card_transaction_id"])
    require_not_terminal(row, "status", TERMINAL_CLAIM, "SubstantiationClaim")
    require_transition(row["status"] == "SUBMITTED",
                       "SubstantiationClaim %s cannot be approved from status %s."
                       % (row["id"], row["status"]))
    require_transition(transaction is not None and
                       transaction["substantiation_status"] == "PENDING_DOCS",
                       "SubstantiationClaim %s cannot be approved because its card "
                       "transaction is not awaiting documents." % row["id"])

    # ladder 34
    if row["claimed_amount_cents"] != transaction["amount_cents"]:
        fail("ERR_CLAIM_AMOUNT_MISMATCH",
             "The claimed amount does not equal the settled transaction amount; "
             "the claim must be rejected instead.")

    row["status"] = "APPROVED"
    row["reviewed_by_user_id"] = principal.user_id
    bump(row)
    transaction["substantiation_status"] = "SUBSTANTIATED"
    transaction["approved_by_user_id"] = principal.user_id
    bump(transaction)
    return object_response(serialize.substantiation_claim(row))


@bp.post("/benefits/substantiation-claims/<claim_id>/reject")
def reject_claim(claim_id):
    principal = authenticate(["ComplianceReviewer"])
    row = resolve_claim(claim_id)
    _body, values = parse_body([field("rejection_reason", "enum", required=True,
                                      choices=REJECTION_REASONS)])
    transaction = store.card_transactions.get(row["card_transaction_id"])
    require_not_terminal(row, "status", TERMINAL_CLAIM, "SubstantiationClaim")
    require_transition(row["status"] == "SUBMITTED",
                       "SubstantiationClaim %s cannot be rejected from status %s."
                       % (row["id"], row["status"]))
    require_transition(transaction is not None and
                       transaction["substantiation_status"] == "PENDING_DOCS",
                       "SubstantiationClaim %s cannot be rejected because its card "
                       "transaction is not awaiting documents." % row["id"])

    row["status"] = "REJECTED"
    row["rejection_reason"] = values["rejection_reason"]
    row["reviewed_by_user_id"] = principal.user_id
    bump(row)
    deny_cascade(transaction, principal.user_id)
    return object_response(serialize.substantiation_claim(row))
