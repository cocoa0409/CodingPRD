"""In-memory data store.

Every collection starts EMPTY on every boot.  Nothing is ever seeded, preloaded
or hardcoded here: tests build all preconditions through the declared API.
"""

import itertools
import uuid
from contextlib import contextmanager

import clock

plan_years = {}
vendors = {}
contracts = {}
amendments = {}
disclosures = {}
mrfs = {}
refresh_cycles = {}
tools = {}
rx_submissions = {}
packages = {}
attestations = {}
ledger_entries = {}
remediation_plans = {}

_seq = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq)


def common_fields():
    """id / created_at / updated_at / version for a fresh record."""
    stamp = clock.now_iso()
    return {
        "id": new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": next_seq(),
    }


def ledger_common_fields():
    """A PenaltyLedgerEntry carries only id and created_at (PRD 2.4)."""
    return {
        "id": new_id(),
        "created_at": clock.now_iso(),
        "_seq": next_seq(),
    }


def ordered(collection):
    """Rows ordered by created_at ascending; insertion order breaks ties."""
    return sorted(collection.values(), key=lambda r: (r["created_at"], r["_seq"]))


def _snapshot(record):
    return {
        k: (list(v) if isinstance(v, list) else v)
        for k, v in record.items()
        if not k.startswith("_") and k not in ("version", "updated_at")
    }


def bump(record):
    """Record one mutation: version += 1 and updated_at refreshed."""
    record["version"] = record.get("version", 0) + 1
    record["updated_at"] = clock.now_iso()
    return record


@contextmanager
def txn(record):
    """Collapse every stored-field change made inside the block into ONE
    version increment (PRD 2.4: a resource's version increments by exactly 1
    per mutation that changes at least one stored field; a recomputation that
    changes nothing is not a mutation)."""
    depth = record.get("_txn_depth", 0)
    if depth == 0:
        record["_txn_snapshot"] = _snapshot(record)
    record["_txn_depth"] = depth + 1
    try:
        yield record
    finally:
        record["_txn_depth"] -= 1
        if record["_txn_depth"] == 0:
            before = record.pop("_txn_snapshot", None)
            if before != _snapshot(record):
                bump(record)


def children(collection, field, value):
    return [r for r in ordered(collection) if r.get(field) == value]


def contracts_of_plan_year(plan_year_id):
    return children(contracts, "plan_year_id", plan_year_id)


def amendments_of_contract(contract_id):
    return children(amendments, "contract_id", contract_id)


def disclosures_of_plan_year(plan_year_id):
    ids = {c["id"] for c in contracts.values() if c["plan_year_id"] == plan_year_id}
    return [d for d in ordered(disclosures) if d["contract_id"] in ids]


def refresh_cycles_of_plan_year(plan_year_id):
    return children(refresh_cycles, "plan_year_id", plan_year_id)


def tools_of_plan_year(plan_year_id):
    return children(tools, "plan_year_id", plan_year_id)


def rx_submissions_of_plan_year(plan_year_id):
    return children(rx_submissions, "plan_year_id", plan_year_id)


def packages_of_submission(rx_submission_id):
    return children(packages, "rx_submission_id", rx_submission_id)


def attestations_of_plan_year(plan_year_id):
    return children(attestations, "plan_year_id", plan_year_id)


def ledger_of_plan_year(plan_year_id):
    return children(ledger_entries, "plan_year_id", plan_year_id)


def plan_year_of_contract(contract):
    return plan_years.get(contract["plan_year_id"])


def plan_year_of_amendment(amendment):
    contract = contracts.get(amendment["contract_id"])
    return plan_years.get(contract["plan_year_id"]) if contract else None


def plan_year_of_disclosure(disclosure):
    contract = contracts.get(disclosure["contract_id"])
    return plan_years.get(contract["plan_year_id"]) if contract else None


def plan_year_of_package(package):
    submission = rx_submissions.get(package["rx_submission_id"])
    return plan_years.get(submission["plan_year_id"]) if submission else None


def plan_year_of_attestation(attestation):
    return plan_years.get(attestation["plan_year_id"])
