"""The transitive cascades of PRD 2.12: each hop is caused by the hop above it.

Cascade A  window lock -> election re-funding -> account credit -> employer
           commitment / auto-suspension.
Cascade B  substantiation denial -> spend reversal -> employee receivable ->
           held elections.
Plus the exact compensation of cascade B on a reopen from INELIGIBLE, the
election cancellation cascade shared by cancel / supersede / termination, and
the media-order supersede cancellation.
"""

from calc import (
    exclusion_split,
    maybe_reconcile_batch,
    post_entry,
    recompute_commitment,
    recompute_line_count,
    rederive_fulfillment,
)
from store import bump, sorted_rows, store

CANCELLABLE_MEDIA_STATUSES = ("PENDING", "SUBMITTED")


# ------------------------------------------------------ media order cancellation
def cancel_media_orders(election):
    """Drive every PENDING or SUBMITTED line of the election to CANCELLED."""
    touched_batches = {}
    rows = [o for o in store.media_orders.values()
            if o["election_id"] == election["id"]
            and o["status"] in CANCELLABLE_MEDIA_STATUSES]
    for order in sorted_rows(rows):
        order["status"] = "CANCELLED"
        bump(order)
        batch = store.order_batches.get(order["order_batch_id"])
        if batch is not None:
            touched_batches[batch["id"]] = batch
    for batch in touched_batches.values():
        recompute_line_count(batch)
        if maybe_reconcile_batch(batch):
            bump(batch)
    return rows


def cancel_election(election):
    """The shared cancellation effect set: identical for cancel, supersede and
    the termination cascade."""
    election["funding_status"] = "CANCELLED"
    election["excluded_amount_cents"] = 0
    election["posttax_spill_cents"] = 0
    election["posttax_effective_cents"] = 0
    election["total_amount_cents"] = 0
    cancel_media_orders(election)
    rederive_fulfillment(election)
    bump(election)
    return election


# --------------------------------------------------------------- cascade A
LOCK_ORDER_TIE_BREAK = "created_at asc, category_type asc, pretax_amount_cents desc"


def _lock_sort_key(election):
    category = store.benefit_categories.get(election["benefit_category_id"])
    category_type = "" if category is None else category["category_type"]
    return (election["created_at"], category_type,
            -election["pretax_amount_cents"], election["_seq"])


def lock_window_cascade(window, employer):
    """Cascade A hops 1 through 4."""
    # hop 1 - the window itself
    window["status"] = "LOCKED"
    window["locked_at"] = store.clock_iso()
    bump(window)

    # hop 2 - caused by the window change
    pending = [e for e in store.elections.values()
               if e["election_window_id"] == window["id"]
               and e["funding_status"] == "PENDING"]
    employer_touched = False
    for election in sorted(pending, key=_lock_sort_key):
        category = store.benefit_categories.get(election["benefit_category_id"])
        employee = store.employees.get(election["employee_id"])
        if category is None or employee is None:
            continue
        split = exclusion_split(
            employer, category, election["employee_id"], window["id"],
            election["pretax_amount_cents"], election["posttax_amount_cents"],
            "FUNDED_BASIS", enforce_spill_policy=False,
            exclude_election_id=election["id"])
        election["total_amount_cents"] = split["total_amount_cents"]
        election["excluded_amount_cents"] = split["excluded_amount_cents"]
        election["posttax_spill_cents"] = split["posttax_spill_cents"]
        election["posttax_effective_cents"] = split["posttax_effective_cents"]
        election["exclusion_basis"] = "FUNDED_BASIS"

        funded = False
        if employee["substantiation_hold"]:
            election["funding_status"] = "HELD"
        elif employer["program_status"] == "ACTIVE":
            election["funding_status"] = "FUNDED"
            funded = True
        bump(election)

        if not funded:
            continue

        # hop 3 - caused by the move into FUNDED
        account = store.benefit_accounts.get(election["benefit_account_id"])
        if account is not None:
            account["contributed_cents"] += election["total_amount_cents"]
            post_entry(account, "CONTRIBUTION", election["total_amount_cents"],
                       "Election", election["id"],
                       "Election funding contribution credited at window lock.")
            bump(account)

            # hop 4 - caused by the account credit
            if recompute_commitment(employer):
                employer_touched = True

    if employer_touched:
        bump(employer)
    return window


# --------------------------------------------------------------- cascade B
def deny_cascade(transaction, acting_user_id):
    """Cascade B hops 1 through 4 (PENDING_DOCS -> INELIGIBLE)."""
    amount = transaction["amount_cents"]

    # hop 1 - the transaction
    transaction["substantiation_status"] = "INELIGIBLE"
    transaction["denied_by_user_id"] = acting_user_id
    transaction["posted_spend_cents"] = 0
    bump(transaction)

    # hop 2 - caused by the transaction change
    account = store.benefit_accounts.get(transaction["benefit_account_id"])
    if account is not None:
        account["spent_cents"] -= amount
        post_entry(account, "SPEND_REVERSAL", amount, "CardTransaction",
                   transaction["id"],
                   "Spend reversed after substantiation was denied.")
        bump(account)

    # hop 3 - caused by the ledger credit
    election = store.elections.get(transaction["election_id"])
    employee = None if election is None else store.employees.get(election["employee_id"])
    if employee is not None:
        employee["repayment_due_cents"] += amount
        employee["substantiation_hold"] = employee["repayment_due_cents"] > 0
        bump(employee)

        # hop 4 - caused by the hold flag
        held = [e for e in store.elections.values()
                if e["employee_id"] == employee["id"] and e["funding_status"] == "PENDING"]
        for row in sorted_rows(held):
            row["funding_status"] = "HELD"
            bump(row)
    return transaction


def reopen_from_ineligible(transaction):
    """The exact compensation of cascade B, hop for hop."""
    amount = transaction["amount_cents"]

    # hop 1
    transaction["substantiation_status"] = "PENDING_DOCS"
    transaction["posted_spend_cents"] = amount
    transaction["reopen_count"] += 1
    bump(transaction)

    # hop 2 - caused by the transaction change
    account = store.benefit_accounts.get(transaction["benefit_account_id"])
    if account is not None:
        account["spent_cents"] += amount
        post_entry(account, "SPEND", -amount, "CardTransaction", transaction["id"],
                   "Spend re-posted after the substantiation posture was reopened "
                   "for audit.")
        bump(account)

    # hop 3 - caused by the ledger debit
    election = store.elections.get(transaction["election_id"])
    employee = None if election is None else store.employees.get(election["employee_id"])
    if employee is not None:
        employee["repayment_due_cents"] -= amount
        employee["substantiation_hold"] = employee["repayment_due_cents"] > 0
        bump(employee)

        # hop 4 - caused by the flag clearing
        if not employee["substantiation_hold"]:
            held = [e for e in store.elections.values()
                    if e["employee_id"] == employee["id"]
                    and e["funding_status"] == "HELD"]
            for row in sorted_rows(held):
                window = store.election_windows.get(row["election_window_id"])
                if window is None or window["status"] not in ("OPEN", "LOCKED"):
                    continue
                row["funding_status"] = "PENDING"
                bump(row)
    return transaction


# --------------------------------------------------------- employee termination
def terminate_cascade(employee, employer):
    live = [e for e in store.elections.values()
            if e["employee_id"] == employee["id"]
            and e["funding_status"] in ("PENDING", "HELD")]
    for election in sorted_rows(live):
        cancel_election(election)
    bump(employee)
    return employee
