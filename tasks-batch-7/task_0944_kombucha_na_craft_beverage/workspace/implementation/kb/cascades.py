"""The three named cascades plus the shared system-driven side effects."""

from decimal import Decimal

from . import constants as C
from .calc import (
    recompute_shipment_totals,
    recompute_outstanding_balance,
)
from .store import base_record, collection_sorted, db, touch
from .util import add_hours, dec, round2


# --------------------------------------------------------------- helpers


def deplete_lot_if_empty(lot):
    """FinishedLot.deplete_lot -- evaluated after any decrease of on_hand_units."""
    if lot["status"] == "RELEASED" and int(lot["on_hand_units"]) == 0:
        lot["status"] = "DEPLETED"
    return lot


def batches_of_run(run):
    seen = []
    for draw in run["source_draws"]:
        batch = db.batches.get(draw["batch_id"])
        if batch is not None and batch not in seen:
            seen.append(batch)
    return seen


def abort_packaging_run(run):
    """Compensation: every drawn liter goes back to its source batch."""
    for draw in run["source_draws"]:
        batch = db.batches.get(draw["batch_id"])
        if batch is None:
            continue
        liters = dec(draw["liters_drawn"])
        batch["drawn_liters"] = round2(dec(batch["drawn_liters"]) - liters)
        batch["remaining_liters"] = round2(dec(batch["remaining_liters"]) + liters)
        touch(batch)
    run["status"] = "ABORTED"
    touch(run)
    return run


def recompute_open_recall_notice_count(account):
    account["open_recall_notice_count"] = sum(
        1
        for n in db.recall_notices.values()
        if n["account_id"] == account["id"] and n["status"] in ("PENDING", "OVERDUE")
    )
    return account["open_recall_notice_count"]


# --------------------------------------------- recall cascade, hops 5 - 7


def hop5_unwind_lot(lot):
    """Draft/confirmed lines pulled, allocations reversed, filled kegs emptied."""
    # (a) shipment lines
    lines = collection_sorted(
        db.shipment_lines,
        lambda l: l["finished_lot_id"] == lot["id"] and l["line_status"] == "ACTIVE",
    )
    touched_shipments = []
    for line in lines:
        shipment = db.shipments.get(line["shipment_id"])
        if shipment is None or shipment["status"] not in ("DRAFT", "CONFIRMED"):
            continue
        line["line_status"] = "RECALLED"
        touch(line)
        lot["reserved_units"] = int(lot["reserved_units"]) - int(line["units"])
        if shipment["status"] == "CONFIRMED":
            shipment["status"] = "RECALL_HOLD"
        if shipment not in touched_shipments:
            touched_shipments.append(shipment)
    for shipment in touched_shipments:
        recompute_shipment_totals(shipment)
        if shipment["status"] == "RECALL_HOLD":
            shipment["late_fee"] = Decimal("0.00")
            shipment["aging_bucket"] = "CURRENT"
            shipment["days_past_due"] = 0
        touch(shipment)

    # (b) subscription allocations
    allocations = collection_sorted(
        db.subscription_allocations,
        lambda a: a["finished_lot_id"] == lot["id"] and a["status"] == "ALLOCATED",
    )
    for allocation in allocations:
        allocation["status"] = "REVERSED"
        allocation["reversal_reason"] = "LOT_QUARANTINED"
        touch(allocation)
        lot["reserved_units"] = int(lot["reserved_units"]) - int(allocation["units"])
        subscription = db.subscriptions.get(allocation["subscription_id"])
        if subscription is not None:
            subscription["credit_balance"] = round2(
                dec(subscription["credit_balance"]) + dec(allocation["charge_amount"])
            )
            touch(subscription)

    # (c) filled kegs from this lot
    kegs = collection_sorted(
        db.kegs,
        lambda k: k["finished_lot_id"] == lot["id"] and k["status"] == "FILLED",
    )
    for keg in kegs:
        keg["status"] = "EMPTY"
        keg["remaining_liters"] = Decimal("0.00")
        touch(keg)
        lot["destroyed_units"] = int(lot["destroyed_units"]) + 1

    if int(lot["reserved_units"]) < 0:
        lot["reserved_units"] = 0
    return lot


def exposed_account_ids(lot):
    """An ACTIVE or RECALLED line on any shipment of the account referencing the
    lot, or a keg from the lot held by the account with deposit_state CHARGED."""
    account_ids = []
    for line in collection_sorted(
        db.shipment_lines,
        lambda l: l["finished_lot_id"] == lot["id"]
        and l["line_status"] in ("ACTIVE", "RECALLED"),
    ):
        shipment = db.shipments.get(line["shipment_id"])
        if shipment is None:
            continue
        if shipment["account_id"] not in account_ids:
            account_ids.append(shipment["account_id"])
    for keg in collection_sorted(
        db.kegs,
        lambda k: k["finished_lot_id"] == lot["id"]
        and k["deposit_state"] == "CHARGED"
        and k.get("account_id"),
    ):
        if keg["account_id"] not in account_ids:
            account_ids.append(keg["account_id"])
    return account_ids


def hop6_7_notices(lot, trigger_source):
    account_ids = exposed_account_ids(lot)
    for account_id in account_ids:
        account = db.accounts.get(account_id)
        if account is None:
            continue
        already = any(
            n["account_id"] == account_id
            and n["finished_lot_id"] == lot["id"]
            and n["status"] == "PENDING"
            for n in db.recall_notices.values()
        )
        if not already:
            notice = base_record()
            notice.update(
                {
                    "account_id": account_id,
                    "finished_lot_id": lot["id"],
                    "trigger_source": trigger_source,
                    "status": "PENDING",
                    "issued_at": db.clock,
                    "ack_deadline_at": add_hours(db.clock, C.RECALL_ACK_DEADLINE_HOURS),
                    "acknowledged_at": None,
                    "acknowledged_by_user_id": None,
                }
            )
            db.recall_notices[notice["id"]] = notice
        recompute_open_recall_notice_count(account)
        touch(account)
    return account_ids


def quarantine_finished_lot(lot, trigger_source):
    """Hop 4 plus hops 5, 6 and 7 for a single lot already known eligible."""
    lot["pre_quarantine_status"] = lot["status"]
    lot["status"] = "QUARANTINED"
    hop5_unwind_lot(lot)
    touch(lot)
    hop6_7_notices(lot, trigger_source)
    return lot


# ------------------------------------------- ingredient recall cascade 2-7


def ingredient_quarantine_cascade(ingredient_lot):
    # hop 2 -- batches reached through a non-voided consumption record
    reached_batch_ids = []
    for use in collection_sorted(
        db.batch_ingredient_uses,
        lambda u: u["ingredient_lot_id"] == ingredient_lot["id"] and not u["voided"],
    ):
        batch = db.batches.get(use["batch_id"])
        if batch is None:
            continue
        if batch["ferment_stage"] not in ("F1_ACTIVE", "F2_ACTIVE", "READY_TO_PACKAGE"):
            continue
        if batch["id"] not in reached_batch_ids:
            reached_batch_ids.append(batch["id"])
        if batch["qa_disposition"] != "NONCONFORMING":
            batch["qa_disposition"] = "NONCONFORMING"
            touch(batch)

    if not reached_batch_ids:
        return

    # hop 3 -- COMPLETED runs naming one of those batches
    flagged_runs = []
    for run in collection_sorted(db.packaging_runs, lambda r: r["status"] == "COMPLETED"):
        if any(d["batch_id"] in reached_batch_ids for d in run["source_draws"]):
            run["status"] = "RECALL_FLAGGED"
            touch(run)
            flagged_runs.append(run)

    # hop 4 -- their finished lots
    for run in flagged_runs:
        lot = db.finished_lots.get(run.get("finished_lot_id"))
        if lot is None or lot["status"] not in ("HELD", "RELEASED"):
            continue
        quarantine_finished_lot(lot, "INGREDIENT_LOT_QUARANTINE")


# ------------------------------------------------- recipe revision cascade


def recipe_revision_cascade(recipe):
    """Hops 2 - 4; hop 1 (the version bump) is done by the caller."""
    staled_ids = []
    for approval in collection_sorted(
        db.label_approvals,
        lambda a: a["recipe_id"] == recipe["id"] and a["status"] == "APPROVED",
    ):
        approval["status"] = "STALE"
        approval["stale_reason"] = "RECIPE_REVISED"
        touch(approval)
        staled_ids.append(approval["id"])
    recipe["active_label_approval_id"] = None

    if not staled_ids:
        return
    for run in collection_sorted(
        db.packaging_runs,
        lambda r: r["status"] in ("DRAFT", "SOURCED")
        and r["label_approval_id"] in staled_ids,
    ):
        abort_packaging_run(run)


# --------------------------------------------- lot re-allocation cascade


def lot_reallocation_cascade(lot):
    """Hops 2 and 3 of the clearance cascade."""
    for allocation in collection_sorted(
        db.subscription_allocations,
        lambda a: a["finished_lot_id"] == lot["id"]
        and a["status"] == "REVERSED"
        and a["reversal_reason"] == "LOT_QUARANTINED"
        and int(a["reallocation_attempt_count"]) < C.SUBSCRIPTION_REALLOCATION_ATTEMPT_CAP,
    ):
        allocation["status"] = "ALLOCATED"
        allocation["reversal_reason"] = None
        allocation["reallocation_attempt_count"] = (
            int(allocation["reallocation_attempt_count"]) + 1
        )
        touch(allocation)
        lot["reserved_units"] = int(lot["reserved_units"]) + int(allocation["units"])
        subscription = db.subscriptions.get(allocation["subscription_id"])
        if subscription is not None:
            subscription["credit_balance"] = round2(
                dec(subscription["credit_balance"]) - dec(allocation["charge_amount"])
            )
            touch(subscription)


# ------------------------------------- culture reverification-fail cascade


def culture_failure_cascade(culture):
    reached_batch_ids = []
    for batch in collection_sorted(
        db.batches,
        lambda b: b["scoby_culture_id"] == culture["id"]
        and b["ferment_stage"] in ("F1_ACTIVE", "F2_ACTIVE", "READY_TO_PACKAGE"),
    ):
        if batch["qa_disposition"] != "NONCONFORMING":
            batch["qa_disposition"] = "NONCONFORMING"
            touch(batch)
        reached_batch_ids.append(batch["id"])

    if not reached_batch_ids:
        return
    for run in collection_sorted(
        db.packaging_runs,
        lambda r: r["status"] in ("DRAFT", "SOURCED", "IN_PROGRESS"),
    ):
        if any(d["batch_id"] in reached_batch_ids for d in run["source_draws"]):
            abort_packaging_run(run)


# ------------------------------------------------------------ recall


def recall_finished_lot(lot):
    lot["destroyed_units"] = int(lot["destroyed_units"]) + int(lot["on_hand_units"])
    lot["on_hand_units"] = 0
    lot["reserved_units"] = 0
    lot["status"] = "RECALLED"
    for allocation in collection_sorted(
        db.subscription_allocations,
        lambda a: a["finished_lot_id"] == lot["id"] and a["status"] == "ALLOCATED",
    ):
        allocation["status"] = "REVERSED"
        allocation["reversal_reason"] = "LOT_RECALLED"
        touch(allocation)
    touch(lot)
    hop6_7_notices(lot, "LOT_RECALL")
    return lot


def refresh_account_ledgers(account):
    recompute_outstanding_balance(account)
    return account
