"""Shared domain helpers: ledger journalling, follow-up tasks, cascades."""

import db
from services import calc


# ------------------------------------------------------------------ ledger
def append_entry(entry_type, direction, amount_cents, memo,
                 donation_id=None, remittance_batch_id=None):
    """Ledger lines are immutable: id and created_at only, no version."""
    entry = db.new_record(with_common=False)
    entry["donation_id"] = donation_id
    entry["remittance_batch_id"] = remittance_batch_id
    entry["entry_type"] = entry_type
    entry["direction"] = direction
    entry["amount_cents"] = amount_cents
    entry["memo"] = memo
    db.ledger_entries[entry["id"]] = entry
    return entry


def donation_entries(donation_id):
    return db.ordered(
        [e for e in db.ledger_entries.values() if e["donation_id"] == donation_id]
    )


def batch_entries(batch_id):
    return db.ordered(
        [
            e
            for e in db.ledger_entries.values()
            if e["remittance_batch_id"] == batch_id
        ]
    )


# ------------------------------------------------------- follow-up tasks
def create_task(donation_id, task_type, assigned_role, due_utc):
    task = db.new_record()
    task["donation_id"] = donation_id
    task["task_type"] = task_type
    task["status"] = "OPEN"
    task["due_utc"] = due_utc
    task["assigned_role"] = assigned_role
    task["resolution_note"] = None
    db.follow_up_tasks[task["id"]] = task
    return task


def complete_tasks(donation_id, task_type, note):
    """Sweep both OPEN and ESCALATED tasks of one type to DONE."""
    for task in db.ordered(list(db.follow_up_tasks.values())):
        if task["donation_id"] != donation_id or task["task_type"] != task_type:
            continue
        if task["status"] not in ("OPEN", "ESCALATED"):
            continue
        task["status"] = "DONE"
        task["resolution_note"] = note
        db.touch(task)


def donation_tasks(donation_id):
    return db.ordered(
        [t for t in db.follow_up_tasks.values() if t["donation_id"] == donation_id]
    )


# ----------------------------------------------------------- lookups
def vehicle_for_donation(donation_id):
    for veh in db.vehicles.values():
        if veh["donation_id"] == donation_id:
            return veh
    return None


def title_for_donation(donation_id):
    for rec in db.title_records.values():
        if rec["donation_id"] == donation_id:
            return rec
    return None


def completed_pickup(donation_id):
    for order in db.ordered(list(db.pickup_orders.values())):
        if order["donation_id"] == donation_id and order["status"] == "COMPLETED":
            return order
    return None


def sold_lot_for_donation(donation_id):
    for lot in db.ordered(list(db.auction_lots.values())):
        if lot["donation_id"] == donation_id and lot["status"] == "SOLD":
            return lot
    return None


def active_receipt(donation_id):
    for rec in db.tax_receipts.values():
        if rec["donation_id"] == donation_id and rec["status"] in ("DRAFT", "ISSUED"):
            return rec
    return None


def is_settled(donation_id, exclude_batch_id=None):
    """True when a CLOSED or PAID batch holds a settlement entry for this donation."""
    for entry in db.ledger_entries.values():
        if entry["donation_id"] != donation_id:
            continue
        if entry["entry_type"] != "REMITTANCE_SETTLEMENT":
            continue
        batch_id = entry["remittance_batch_id"]
        if batch_id is None or batch_id == exclude_batch_id:
            continue
        batch = db.remittance_batches.get(batch_id)
        if batch and batch["status"] in ("CLOSED", "PAID"):
            return True
    return False


# --------------------------------------------------------- proceeds cascade
def accrue_proceeds(donation, charity):
    """Cascade links two through four following a recorded sale."""
    append_entry(
        "PROCEEDS_CREDIT",
        "CREDIT",
        donation["gross_proceeds_cents"],
        "gross sale proceeds",
        donation_id=donation["id"],
    )
    append_entry(
        "PROGRAM_FEE_DEBIT",
        "DEBIT",
        donation["program_fee_cents"],
        "tiered program fee",
        donation_id=donation["id"],
    )
    if donation["tow_allowance_cents"] != 0:
        append_entry(
            "TOW_COST_DEBIT",
            "DEBIT",
            donation["tow_allowance_cents"],
            "reimbursable tow allowance",
            donation_id=donation["id"],
        )
    append_entry(
        "ADMIN_FEE_DEBIT",
        "DEBIT",
        db.ADMIN_FLAT_FEE_CENTS,
        "flat administrative fee",
        donation_id=donation["id"],
    )

    charity["pledged_balance_cents"] += donation["net_to_charity_cents"]
    db.touch(charity)

    if charity["pledged_balance_cents"] >= db.AUTO_BATCH_THRESHOLD_CENTS:
        has_open = any(
            b["charity_id"] == charity["id"]
            and b["status"] in ("OPEN", "CLOSED", "DISPUTED")
            for b in db.remittance_batches.values()
        )
        if not has_open:
            batch = create_batch(
                charity["id"], db.now(), db.now() + db.days(db.AUTO_BATCH_PERIOD_DAYS)
            )
            create_task(
                donation["id"],
                "REMITTANCE_PENDING",
                "FinanceOfficer",
                db.now() + db.days(db.REMITTANCE_FOLLOWUP_DAYS),
            )
            return batch
    return None


def reverse_accrual(donation, charity, memo):
    """Compensating reversal of a prior accrual, used by void-sale and withholding."""
    amount = donation["net_to_charity_cents"]
    append_entry(
        "REVERSAL", "DEBIT", amount, memo, donation_id=donation["id"]
    )
    charity["pledged_balance_cents"] -= amount
    db.touch(charity)


# --------------------------------------------------------- remittance batches
def create_batch(charity_id, period_start, period_end):
    batch = db.new_record()
    batch["charity_id"] = charity_id
    batch["period_start_utc"] = period_start
    batch["period_end_utc"] = period_end
    batch["status"] = "OPEN"
    batch["donation_count"] = 0
    batch["gross_cents"] = 0
    batch["provisional_fee_cents"] = 0
    batch["fee_cents"] = 0
    batch["net_cents"] = 0
    batch["closed_by_user_id"] = None
    batch["paid_by_user_id"] = None
    batch["payment_reference"] = None
    batch["dispute_reason"] = None
    batch["_member_ids"] = []
    batch["_member_fees"] = {}
    db.remittance_batches[batch["id"]] = batch
    # A batch opens with donation_count, gross_cents, fee_cents and net_cents all 0,
    # but with its provisional fee computed immediately (PRD 3.9).
    refresh_provisional(batch)
    batch["gross_cents"] = 0
    return batch


def eligible_members(batch):
    """Live eligibility filter (PRD section 3.9), ordered by donation created_at."""
    members = []
    for donation in db.donations.values():
        if donation["charity_id"] != batch["charity_id"]:
            continue
        if donation["payout_status"] != "ACCRUED":
            continue
        if donation["net_to_charity_cents"] <= 0:
            continue
        lot = sold_lot_for_donation(donation["id"])
        if lot is None or lot.get("sold_at_utc") is None:
            continue
        if not (
            batch["period_start_utc"] <= lot["sold_at_utc"] < batch["period_end_utc"]
        ):
            continue
        if is_settled(donation["id"], exclude_batch_id=batch["id"]):
            continue
        members.append(donation)
    return db.ordered(members)


def refresh_provisional(batch):
    """Recompute the live gross and the batch-rounded provisional fee."""
    charity = db.charities.get(batch["charity_id"])
    pct = charity["remittance_fee_pct"] if charity else 0
    members = eligible_members(batch)
    gross = sum(d["net_to_charity_cents"] for d in members)
    batch["gross_cents"] = gross
    batch["provisional_fee_cents"] = calc.batch_rounded_fee(gross, pct)
    return members
