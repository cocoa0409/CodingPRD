"""Core record lifecycle helpers (PRD §2.4).

Every top-level resource carries id / created_at / updated_at / version;
version starts at 1 and increments by one on every mutation. Filing line items
are the single exception — they carry only id and created_at.
"""
from db import db
from util import new_id, wall_ts, next_seq


def new_record(collection, fields, with_version=True):
    rec = dict(fields)
    rec["id"] = new_id()
    ts = wall_ts()
    rec["created_at"] = ts
    if with_version:
        rec["updated_at"] = ts
        rec["version"] = 1
    rec["_seq"] = next_seq()
    db[collection][rec["id"]] = rec
    return rec


def touch(rec):
    """Refresh updated_at and increment version by one (a mutation)."""
    rec["updated_at"] = wall_ts()
    rec["version"] = rec.get("version", 1) + 1


def public(rec):
    """Serialization: internal underscore-prefixed fields are never exposed."""
    if rec is None:
        return None
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def get_plan(plan_id):
    return db["plans"].get(plan_id)


def get_contract(contract_id):
    return db["contracts"].get(contract_id)


def get_member(member_id):
    return db["members"].get(member_id)


def get_claim(claim_id):
    return db["claims"].get(claim_id)


def get_filing(filing_id):
    return db["filings"].get(filing_id)


def find_specific_row(contract_id, member_id):
    for row in db["accumulations"].values():
        if (row["contract_id"] == contract_id and row["scope"] == "SPECIFIC"
                and row["member_id"] == member_id):
            return row
    return None


def find_aggregate_row(contract_id):
    for row in db["accumulations"].values():
        if (row["contract_id"] == contract_id and row["scope"] == "AGGREGATE"
                and row["member_id"] is None):
            return row
    return None


def in_force_contracts_for_plan(plan_id):
    return [c for c in db["contracts"].values()
            if c["plan_id"] == plan_id and c["status"] == "IN_FORCE"]
