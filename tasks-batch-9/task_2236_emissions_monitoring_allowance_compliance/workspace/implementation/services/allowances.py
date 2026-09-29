"""Allowance ledger: settlement, the true-up cascade, the compensation
(reversal) cascade and facility compliance posture (PRD 3.9).

Tonnage is a conserved quantity. Every settled movement stores the exact
per-bucket debits it applied (``debited_prior_tons`` / ``debited_current_tons``
/ ``debited_next_tons``) so that a reversal can credit back precisely those
amounts rather than re-deriving them.
"""

from decimal import Decimal

from constants import PENALTY_MULTIPLIER, PROGRAM_POLLUTANT
from db import base_record, db, touch
from lookup import accounts_of_facility, units_of_facility
from util import D, ceil_int, rhu

PRIOR = "holdings_prior_vintage_tons"
CURRENT = "holdings_current_vintage_tons"
NEXT = "holdings_next_vintage_tons"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def transactions_of(account_id):
    rows = [t for t in db.allowance_transactions.values() if t["allowance_account_id"] == account_id]
    rows.sort(key=lambda t: (t["created_at"], t["_seq"]))
    return rows


def bucket_for_vintage(account, vintage_year):
    if vintage_year < account["compliance_year"]:
        return PRIOR
    if vintage_year == account["compliance_year"]:
        return CURRENT
    return NEXT


def add_to_bucket(account, bucket, amount):
    account[bucket] = rhu(D(account[bucket]) + D(amount), 3)


def new_transaction(account, transaction_type, quantity, vintage_year, status, origin,
                    counterparty_id=None, debited_prior=0.0, debited_current=0.0,
                    debited_next=0.0):
    txn = base_record()
    txn.update(
        {
            "allowance_account_id": account["id"],
            "counterparty_account_id": counterparty_id,
            "transaction_type": transaction_type,
            "quantity_tons": rhu(quantity, 3),
            "vintage_year": vintage_year,
            "status": status,
            "origin": origin,
            "debited_current_tons": rhu(debited_current, 3),
            "debited_prior_tons": rhu(debited_prior, 3),
            "debited_next_tons": rhu(debited_next, 3),
            "allowance_account_version_after": account["version"],
            "reversal_reason": None,
        }
    )
    db.allowance_transactions[txn["id"]] = txn
    return txn


def refresh_account_figures(account):
    """``surrendered_tons`` / ``penalty_deducted_tons`` are re-derived from the
    account's SETTLED rows; ``shortfall_tons`` is the obligation shortfall,
    floored at zero.
    """
    surrendered = Decimal(0)
    penalty = Decimal(0)
    for txn in transactions_of(account["id"]):
        if txn["status"] != "SETTLED":
            continue
        if txn["transaction_type"] == "SURRENDER":
            surrendered += D(txn["quantity_tons"])
        elif txn["transaction_type"] == "PENALTY_DEDUCTION":
            penalty += D(txn["quantity_tons"])
    account["surrendered_tons"] = rhu(surrendered, 3)
    account["penalty_deducted_tons"] = rhu(penalty, 3)
    shortfall = rhu(D(account["obligation_tons"]) - D(account["surrendered_tons"]), 3)
    account["shortfall_tons"] = 0.0 if D(shortfall) < 0 else shortfall


# ---------------------------------------------------------------------------
# facility compliance posture
# ---------------------------------------------------------------------------

def _facility_reports(facility_id):
    unit_ids = {u["id"] for u in units_of_facility(facility_id)}
    return [r for r in db.quarterly_reports.values() if r["unit_id"] in unit_ids]


def recompute_facility_posture(facility):
    """Returns ``(changed, previous, current)``. DEFICIT dominates; otherwise the
    first account whose banked+current holdings fall strictly short of the
    projected obligation settles WATCH. Equality is COMPLIANT.
    """
    previous = facility["compliance_posture"]
    accounts = accounts_of_facility(facility["id"])
    accounts.sort(key=lambda a: (a["created_at"], a["_seq"]))
    posture = "COMPLIANT"
    if any(D(a["shortfall_tons"]) > 0 for a in accounts):
        posture = "DEFICIT"
    else:
        reports = _facility_reports(facility["id"])
        for account in accounts:
            total = Decimal(0)
            for report in reports:
                if report["status"] not in ("SUBMITTED", "CERTIFIED", "ACCEPTED"):
                    continue
                if report["year"] != account["compliance_year"]:
                    continue
                total += D(report["total_so2_tons"] if report["total_so2_tons"] is not None else 0)
            projected = ceil_int(rhu(total, 3))
            covered = D(account[CURRENT]) + D(account[PRIOR])
            if covered < D(projected):
                posture = "WATCH"
                break
    changed = posture != previous
    if changed:
        facility["compliance_posture"] = posture
        touch(facility)
    return changed, previous, posture


def apply_dispatch_restriction(facility, restricted):
    """Link four of the true-up / compensation cascades."""
    affected = []
    units = units_of_facility(facility["id"])
    units.sort(key=lambda u: (u["created_at"], u["_seq"]))
    for unit in units:
        changed = False
        if unit["dispatch_restricted"] != restricted:
            unit["dispatch_restricted"] = restricted
            changed = True
        if restricted and unit["dispatch_state"] == "ONLINE":
            unit["dispatch_state"] = "RESERVE_SHUTDOWN"
            changed = True
        if changed:
            touch(unit)
            affected.append(unit)
    return affected


def posture_and_dispatch(facility):
    """Recompute posture; entering DEFICIT restricts dispatch, leaving it lifts
    the restriction.
    """
    changed, previous, current = recompute_facility_posture(facility)
    if current == "DEFICIT" and previous != "DEFICIT":
        apply_dispatch_restriction(facility, True)
    elif previous == "DEFICIT" and current != "DEFICIT":
        apply_dispatch_restriction(facility, False)
    return changed, previous, current


# ---------------------------------------------------------------------------
# settlement
# ---------------------------------------------------------------------------

def settle_transaction(txn, account, counterparty, facility=None):
    """Apply a RECORDED transaction's holdings movement.

    Callers have already run the state and sufficiency guards.
    """
    quantity = D(txn["quantity_tons"])
    bucket = bucket_for_vintage(account, txn["vintage_year"])
    ttype = txn["transaction_type"]

    if ttype in ("PURCHASE", "TRANSFER_IN"):
        add_to_bucket(account, bucket, quantity)
        txn["debited_prior_tons"] = 0.0
        txn["debited_current_tons"] = 0.0
        txn["debited_next_tons"] = 0.0
    elif ttype in ("SURRENDER", "TRANSFER_OUT"):
        remaining = quantity
        prior_balance = D(account[PRIOR])
        debited_prior = prior_balance if prior_balance < remaining else remaining
        if debited_prior < 0:
            debited_prior = Decimal(0)
        remaining -= debited_prior
        current_balance = D(account[CURRENT])
        debited_current = current_balance if current_balance < remaining else remaining
        if debited_current < 0:
            debited_current = Decimal(0)
        remaining -= debited_current
        account[PRIOR] = rhu(prior_balance - debited_prior, 3)
        account[CURRENT] = rhu(current_balance - debited_current, 3)
        txn["debited_prior_tons"] = rhu(debited_prior, 3)
        txn["debited_current_tons"] = rhu(debited_current, 3)
        txn["debited_next_tons"] = 0.0
        if ttype == "TRANSFER_OUT" and counterparty is not None:
            other_bucket = bucket_for_vintage(counterparty, txn["vintage_year"])
            add_to_bucket(counterparty, other_bucket, quantity)
            touch(counterparty)
    else:  # PENALTY_DEDUCTION -- cascade only; the next-vintage bucket may go negative
        account[NEXT] = rhu(D(account[NEXT]) - quantity, 3)
        txn["debited_prior_tons"] = 0.0
        txn["debited_current_tons"] = 0.0
        txn["debited_next_tons"] = rhu(quantity, 3)

    txn["status"] = "SETTLED"
    refresh_account_figures(account)
    touch(account)
    if facility is not None:
        posture_and_dispatch(facility)
    txn["allowance_account_version_after"] = account["version"]
    touch(txn)


# ---------------------------------------------------------------------------
# the true-up cascade
# ---------------------------------------------------------------------------

def enforceable_event_debit(facility_id, compliance_year, program):
    """Event tonnage that this account absorbs: ENFORCEABLE events on the
    facility's units, detected in the compliance year, whose parent limit's
    pollutant is regulated by the account's program.
    """
    pollutant = PROGRAM_POLLUTANT.get(program)
    if pollutant is None:
        return 0
    unit_ids = {u["id"] for u in units_of_facility(facility_id)}
    total = 0
    for event in db.excess_events.values():
        if event["status"] != "ENFORCEABLE":
            continue
        if event["unit_id"] not in unit_ids:
            continue
        detected = event.get("_detected")
        if detected is None or detected.year != compliance_year:
            continue
        limit = db.permit_limits.get(event["permit_limit_id"])
        if limit is None or limit["pollutant"] != pollutant:
            continue
        total += int(event["penalty_allowance_debit_tons"])
    return total


def accepted_emitted_tons(facility_id, compliance_year):
    unit_ids = {u["id"] for u in units_of_facility(facility_id)}
    total = Decimal(0)
    for report in db.quarterly_reports.values():
        if report["unit_id"] not in unit_ids:
            continue
        if report["status"] != "ACCEPTED":
            continue
        if report["year"] != compliance_year:
            continue
        total += D(report["total_so2_tons"] if report["total_so2_tons"] is not None else 0)
    return rhu(total, 3)


def run_true_up(account, facility):
    """Link one of the true-up cascade, then links two to four when short."""
    emitted = accepted_emitted_tons(facility["id"], account["compliance_year"])
    event_debit = enforceable_event_debit(
        facility["id"], account["compliance_year"], account["program"]
    )
    obligation = ceil_int(emitted) + event_debit
    account["obligation_tons"] = obligation

    # banked-first waterfall
    remaining = D(obligation)
    prior_balance = D(account[PRIOR])
    take_prior = prior_balance if prior_balance < remaining else remaining
    if take_prior < 0:
        take_prior = Decimal(0)
    remaining -= take_prior
    current_balance = D(account[CURRENT])
    take_current = current_balance if current_balance < remaining else remaining
    if take_current < 0:
        take_current = Decimal(0)
    remaining -= take_current

    account[PRIOR] = rhu(prior_balance - take_prior, 3)
    account[CURRENT] = rhu(current_balance - take_current, 3)
    surrendered = rhu(take_prior + take_current, 3)
    shortfall = rhu(remaining, 3)
    account["surrendered_tons"] = surrendered
    account["shortfall_tons"] = shortfall
    account["penalty_deducted_tons"] = 0.0
    account["true_up_utc"] = db.now_str()

    surrender_txn = new_transaction(
        account,
        "SURRENDER",
        surrendered,
        account["compliance_year"],
        "SETTLED",
        "TRUE_UP_SURRENDER",
        debited_prior=take_prior,
        debited_current=take_current,
    )

    if D(shortfall) <= 0:
        account["status"] = "CLOSED"
        touch(account)
        surrender_txn["allowance_account_version_after"] = account["version"]
        posture_and_dispatch(facility)
        return {"surrender_transaction": surrender_txn, "penalty_transaction": None}

    account["status"] = "TRUE_UP_LOCKED"
    touch(account)

    # ---- link two: the punitive penalty deduction -------------------------
    penalty_quantity = rhu(D(shortfall) * PENALTY_MULTIPLIER, 3)
    penalty_txn = new_transaction(
        account,
        "PENALTY_DEDUCTION",
        penalty_quantity,
        account["compliance_year"],
        "SETTLED",
        "TRUE_UP_PENALTY",
        debited_next=penalty_quantity,
    )
    account[NEXT] = rhu(D(account[NEXT]) - D(penalty_quantity), 3)
    refresh_account_figures(account)
    touch(account)
    surrender_txn["allowance_account_version_after"] = account["version"]
    penalty_txn["allowance_account_version_after"] = account["version"]

    # ---- links three and four: posture and dispatch ----------------------
    posture_and_dispatch(facility)
    return {"surrender_transaction": surrender_txn, "penalty_transaction": penalty_txn}


# ---------------------------------------------------------------------------
# the compensation (reversal) cascade
# ---------------------------------------------------------------------------

def reverse_settled_transaction(txn, account, facility, reason):
    """Link one credits back the exact stored debits; link two voids a true-up
    when the reversed row is the true-up surrender; links three and four
    recompute posture and lift the dispatch restriction.
    """
    # ---- link one ---------------------------------------------------------
    add_to_bucket(account, PRIOR, D(txn["debited_prior_tons"]))
    add_to_bucket(account, CURRENT, D(txn["debited_current_tons"]))
    add_to_bucket(account, NEXT, D(txn["debited_next_tons"]))
    if txn["transaction_type"] == "TRANSFER_OUT" and txn.get("counterparty_account_id"):
        counterparty = db.allowance_accounts.get(txn["counterparty_account_id"])
        if counterparty is not None:
            bucket = bucket_for_vintage(counterparty, txn["vintage_year"])
            counterparty[bucket] = rhu(D(counterparty[bucket]) - D(txn["quantity_tons"]), 3)
            touch(counterparty)
    txn["reversal_reason"] = reason
    txn["status"] = "REVERSED"
    touch(txn)

    # link one's own account bump
    touch(account)

    if txn["origin"] == "TRUE_UP_SURRENDER":
        # ---- link two: the true-up is voided outright, never re-derived ----
        for other in transactions_of(account["id"]):
            if other["status"] == "SETTLED" and other["origin"] == "TRUE_UP_PENALTY":
                add_to_bucket(account, NEXT, D(other["debited_next_tons"]))
                other["reversal_reason"] = reason
                other["status"] = "REVERSED"
                touch(other)
        if account["status"] == "TRUE_UP_LOCKED":
            account["status"] = "OPEN"
        account["obligation_tons"] = 0
        account["surrendered_tons"] = 0.0
        account["penalty_deducted_tons"] = 0.0
        account["shortfall_tons"] = 0.0
        account["true_up_utc"] = None
        touch(account)
    else:
        # Reversing any other row leaves the lock alone and only refreshes the
        # three derived figures.
        refresh_account_figures(account)

    txn["allowance_account_version_after"] = account["version"]

    # ---- links three and four --------------------------------------------
    posture_and_dispatch(facility)
    return txn
