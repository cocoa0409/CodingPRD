"""DepositAccount core service: posture, ledger postings, closures (PRD §2.7,
§2.8, §3.1, §3.9) and the closure cascade shared by all four closure paths.
"""

import db
from errors import ApiError, ERR_NOT_FOUND

# Transaction direction (PRD §2.7): amount_cents is always positive;
# direction derives from txn_type.
CREDIT_TYPES = {"DEPOSIT", "FEDERAL_BENEFIT_DEPOSIT", "INTEREST_CREDIT"}
DEBIT_TYPES = {
    "WITHDRAWAL",
    "INACTIVITY_FEE",
    "LEGAL_REMITTANCE",
    "CLOSURE_PAYOUT",
    "ESTATE_RELEASE",
}
CLIENT_TXN_TYPES = {"DEPOSIT", "WITHDRAWAL", "FEDERAL_BENEFIT_DEPOSIT"}

OWNERSHIP_TYPES = {"INDIVIDUAL", "JOINT", "POD", "TRUST", "BUSINESS"}
PRODUCT_CODES = {"BASIC_CHECKING", "PREMIUM_CHECKING", "SAVINGS", "MONEY_MARKET"}

DEST_OWNER = "OWNER"
DEST_ESTATE = "ESTATE"
DEST_STATE_ESCHEAT = "STATE_ESCHEAT"


def get_account_or_404(account_id: str):
    acct = db.accounts.get(account_id)
    if acct is None:
        raise ApiError(ERR_NOT_FOUND, f"Account {account_id} does not exist")
    return acct


def compute_suppression(lifecycle_status: str, restriction_status: str) -> str:
    """statement_suppression derivation, strict precedence (PRD §2.8)."""
    if lifecycle_status == "CLOSED":
        return "CLOSED"
    if restriction_status == "DECEASED_HOLD":
        return "DECEASED"
    if lifecycle_status in ("DORMANT", "ESCHEAT_PENDING"):
        return "DORMANT"
    return "NONE"


def touch_account(acct) -> None:
    """Every account mutation increments version by exactly one (PRD §2.8)."""
    acct["version"] += 1
    acct["updated_at"] = db.now_timestamp()
    acct["statement_suppression"] = compute_suppression(
        acct["lifecycle_status"], acct["restriction_status"]
    )


def touch_resource(rec) -> None:
    rec["version"] += 1
    rec["updated_at"] = db.now_timestamp()


def derived_totals(account_id: str):
    """available_balance_reconciliation (SCAFFOLD §1.3): total held is the sum
    over orders in FUNDS_HELD only; available = balance - total_held."""
    total_held = sum(
        g["held_amount_cents"]
        for g in db.garnishments.values()
        if g["account_id"] == account_id and g["status"] == "FUNDS_HELD"
    )
    acct = db.accounts[account_id]
    return total_held, acct["balance_cents"] - total_held


def refresh_restriction(account_id: str) -> None:
    """LEGAL_HOLD holds while any order is FUNDS_HELD; a DECEASED_HOLD is only
    cleared as part of the estate-release closure (PRD §3.4)."""
    acct = db.accounts[account_id]
    if acct["restriction_status"] == "LEGAL_HOLD":
        any_held = any(
            g["account_id"] == account_id and g["status"] == "FUNDS_HELD"
            for g in db.garnishments.values()
        )
        if not any_held:
            acct["restriction_status"] = "NONE"


def post_transaction(acct, txn_type: str, amount_cents: int, customer_initiated: bool,
                     posted_date: str):
    """Append a posting to the ledger and move the balance (PRD §2.7)."""
    if txn_type in CREDIT_TYPES:
        acct["balance_cents"] += amount_cents
    else:
        acct["balance_cents"] -= amount_cents
    txn = {
        "id": db.new_uuid(),
        "account_id": acct["id"],
        "txn_type": txn_type,
        "amount_cents": amount_cents,
        "customer_initiated": bool(customer_initiated),
        "posted_date": posted_date,
        "balance_after_cents": acct["balance_cents"],
        "created_at": db.now_timestamp(),
        "_seq": db.next_creation_seq(),
    }
    db.transactions[txn["id"]] = txn
    return txn


def closure_cascade(acct, closed_date: str, signer_reason: str) -> None:
    """The cascade shared by every closure path (PRD §3.9): signers removed,
    in-flight title changes rejected, scheduled conversions cancelled,
    scheduled statement cycles suppressed."""
    for s in db.signers.values():
        if s["account_id"] == acct["id"] and s["status"] in ("ACTIVE", "SUSPENDED"):
            s["status"] = "REMOVED"
            s["removed_reason"] = signer_reason
            touch_resource(s)
    for r in db.title_changes.values():
        if r["account_id"] == acct["id"] and r["status"] == "SUBMITTED":
            r["status"] = "REJECTED"
            r["decision_reason"] = "ACCOUNT_CLOSED"
            r["decided_by_user_id"] = None
            touch_resource(r)
    for c in db.conversions.values():
        if c["account_id"] == acct["id"] and c["status"] == "SCHEDULED":
            c["status"] = "CANCELLED"
            touch_resource(c)
    for c in db.statement_cycles.values():
        if c["account_id"] == acct["id"] and c["status"] == "SCHEDULED":
            c["status"] = "SUPPRESSED"
            c["suppression_reason"] = "CLOSED"
            c["produced_date"] = closed_date
            touch_resource(c)


def settle_interest_txn(acct, settlement_date: str, variant: str):
    """Post the INTEREST_CREDIT for [accrual_start_date, settlement_date).
    Returns the settled amount (0 posts no transaction)."""
    from services.interest import accrued_interest

    amount = accrued_interest(
        acct["id"], acct["accrual_start_date"], settlement_date,
        acct["rate_bps"], variant,
    )
    if amount > 0:
        post_transaction(acct, "INTEREST_CREDIT", amount, False, settlement_date)
    acct["accrued_interest_cents"] = 0
    return amount


def finalize_closure(acct, close_date: str, payout_cents: int, destination: str,
                     signer_reason: str) -> None:
    """Common terminal step for every closure path."""
    acct["lifecycle_status"] = "CLOSED"
    acct["closure_payout_cents"] = payout_cents
    acct["closure_payout_destination"] = destination
    closure_cascade(acct, close_date, signer_reason)
    touch_account(acct)
