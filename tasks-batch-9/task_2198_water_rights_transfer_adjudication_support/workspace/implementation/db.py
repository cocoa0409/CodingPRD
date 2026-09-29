"""In-memory data store.

Every collection starts empty on every boot. Nothing is seeded, preloaded or
hardcoded -- all rows are created by callers through the declared endpoints.
"""
import itertools
import uuid

import clock

claimants = {}
water_rights = {}
points_of_diversion = {}
beneficial_use_records = {}
hcu_studies = {}
transfer_applications = {}
injury_analyses = {}
protests = {}
approval_conditions = {}
water_bank_accounts = {}
lease_assignments = {}
decree_dockets = {}
adjudication_claims = {}

# Internal ledger of accepted bank deposits (not an exposed entity; rows are
# created only by POST /water-bank-accounts/{id}/deposits).
bank_deposits = []

_seq = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq)


def base_row(with_version=True):
    """Common system fields shared by every versioned entity."""
    stamp = clock.now_iso()
    row = {
        "id": new_id(),
        "created_at": stamp,
        "_seq": next_seq(),
    }
    if with_version:
        row["updated_at"] = stamp
        row["version"] = 1
    return row


def touch(row):
    """Refresh updated_at and increment version by 1."""
    row["updated_at"] = clock.now_iso()
    row["version"] = int(row.get("version", 1)) + 1
    return row


def values(store):
    return list(store.values())
