"""Dual-variant reconciliation against the core deposit platform."""

from db import db
from timeutils import date_str
from services import lookup
from services.constants import VARIANCE_TOLERANCE_CENTS


def _credit_side(participant_id, business_date):
    total = 0
    count = 0
    for row in db.credit_transfers.values():
        if row["originator_participant_id"] != participant_id:
            continue
        if row["direction"] != "INBOUND":
            continue
        if row["clearing_status"] != "SETTLED":
            continue
        if row["settlement_business_date"] != business_date:
            continue
        total += row["amount_cents"]
        count += 1
    return total, count


def _provisional_debit_side(participant_id, business_date):
    total = 0
    count = 0
    for row in db.credit_transfers.values():
        if row["originator_participant_id"] != participant_id:
            continue
        if row["direction"] != "OUTBOUND":
            continue
        status = row["clearing_status"]
        if status == "SETTLED":
            if row["settlement_business_date"] != business_date:
                continue
        elif status == "ACCEPTED":
            if row["accepted_at"] is None or date_str(row["accepted_at"]) != business_date:
                continue
        else:
            continue
        total += row["amount_cents"]
        count += 1
    return total, count


def _final_debit_side(participant_id, business_date):
    total = 0
    count = 0
    for row in db.credit_transfers.values():
        if row["originator_participant_id"] != participant_id:
            continue
        if row["direction"] != "OUTBOUND":
            continue
        if row["clearing_status"] != "SETTLED":
            continue
        if row["settlement_business_date"] != business_date:
            continue
        if row["exception_status"] == "RETURN_HONORED":
            continue
        total += row["amount_cents"]
        count += 1
    return total, count


def _fee_component(account_id, business_date):
    total = 0
    for entry in db.ledger_entries.values():
        if entry["account_id"] != account_id:
            continue
        if entry["entry_type"] != "FEE_DEBIT":
            continue
        if entry["business_date"] != business_date:
            continue
        total += entry["amount_cents"]
    return total


def compute(participant, cycle, variant, core_deposit_total_cents, account):
    business_date = cycle["business_date"]
    credit_total, credit_count = _credit_side(participant["id"], business_date)
    if variant == "PROVISIONAL":
        debit_total, debit_count = _provisional_debit_side(participant["id"], business_date)
        fee_component = 0
    else:
        debit_total, debit_count = _final_debit_side(participant["id"], business_date)
        fee_component = _fee_component(account["id"], business_date)
    rail_net = credit_total - debit_total + fee_component
    variance = core_deposit_total_cents - rail_net
    outcome = "BALANCED" if abs(variance) <= VARIANCE_TOLERANCE_CENTS else "OUT_OF_BALANCE"
    return {
        "rail_net_position_cents": rail_net,
        "variance_cents": variance,
        "outcome": outcome,
        "included_transfer_count": debit_count + credit_count,
        "fee_component_cents": fee_component,
    }


def next_revision(cycle_id, participant_id, variant):
    existing = 0
    for run in db.reconciliation_runs.values():
        if (run["settlement_cycle_id"] == cycle_id
                and run["participant_id"] == participant_id
                and run["variant"] == variant):
            existing += 1
    return existing + 1


def highest_final_run(cycle_id, participant_id):
    best = None
    for run in db.reconciliation_runs.values():
        if run["settlement_cycle_id"] != cycle_id:
            continue
        if run["participant_id"] != participant_id:
            continue
        if run["variant"] != "FINAL":
            continue
        if best is None or run["revision"] > best["revision"]:
            best = run
    return best


def any_live_out_of_balance(cycle_id):
    for participant in lookup.live_participants():
        run = highest_final_run(cycle_id, participant["id"])
        if run is not None and run["outcome"] == "OUT_OF_BALANCE":
            return True
    return False


def all_live_balanced(cycle_id):
    for participant in lookup.live_participants():
        run = highest_final_run(cycle_id, participant["id"])
        if run is None or run["outcome"] != "BALANCED":
            return False
    return True
