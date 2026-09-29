"""In-memory data store. Every collection starts EMPTY on every boot: the
implementation encodes the system, never the data."""
from util import next_seq, new_id, now

sponsors = {}
permittees = {}
irt_members = {}
banks = {}
prospectuses = {}
prospectus_votes = {}
work_plans = {}
performance_standards = {}
milestones = {}
monitoring_reports = {}
remedial_actions = {}
credit_sales = {}
ledger_by_bank = {}          # bank_id -> [entry dict, ...] in append order


def new_row(fields, common=True):
    """Create a row with server-minted id and the common bookkeeping properties."""
    row = {"id": new_id(), "_seq": next_seq()}
    row.update(fields)
    stamp = now()
    row["created_at"] = stamp
    if common:
        row["updated_at"] = stamp
        row["version"] = 1
    return row


def touch(row):
    """Refresh updated_at and increment version by exactly 1 (PRD 2.4)."""
    row["updated_at"] = now()
    row["version"] = row.get("version", 0) + 1
    return row


def ordered(rows):
    """Default ordering: created_at ascending, stable on insertion order."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def bank_ledger(bank_id):
    return ledger_by_bank.setdefault(bank_id, [])
