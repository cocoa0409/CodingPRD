"""In-memory data store.

All state lives in module-level dicts keyed by id. Nothing is seeded — the
store starts empty on every process boot (per-test-server isolation wipes
state by re-launching the process). Tests build all preconditions via the
declared API surface.

Common fields per PRD §2.4 (every entity carries the full quartet):
  - id: UUID, no type prefix
  - created_at: ISO8601 UTC, 3 fractional digits
  - updated_at: refreshed on every mutation
  - version: starts at 1, +1 on each modification

NOTE on Claim.version: the entity-wide `version` field is the OCC token AND
the §2.4 mutation counter. PRD §2.4 says version advances ONLY on the four
workflow-named claim transitions (assign, decide, the two settles). A pure
ledger refresh (rental approve / subrogation resolve / void touching
total_disbursed_cents) refreshes updated_at WITHOUT bumping version. So Claim
uses `touch_no_version` for ledger refreshes and explicit version increments
inside the four guarded transitions.
"""
from datetime import datetime, timezone

from util import new_uuid

# Collections (entity name -> {id: record dict}).
policies = {}
coverages = {}
adjusters = {}
claims = {}
claim_parties = {}
coverage_verifications = {}
repair_estimates = {}
total_loss_evaluations = {}
rental_reimbursements = {}
subrogation_cases = {}
disbursements = {}

COLLECTIONS = {
    "Policy": policies,
    "Coverage": coverages,
    "Adjuster": adjusters,
    "Claim": claims,
    "ClaimParty": claim_parties,
    "CoverageVerification": coverage_verifications,
    "RepairEstimate": repair_estimates,
    "TotalLossEvaluation": total_loss_evaluations,
    "RentalReimbursement": rental_reimbursements,
    "SubrogationCase": subrogation_cases,
    "Disbursement": disbursements,
}

# Monotonic sequence so created_at ties (same clock instant) still sort
# deterministically in insertion order for list endpoints and ledger replay.
_seq = 0


def next_seq():
    global _seq
    _seq += 1
    return _seq


def _now():
    return datetime.now(timezone.utc)


def insert(collection, record):
    """Insert a new record, stamping the full common-field quartet."""
    rid = new_uuid()
    now = _now()
    record["id"] = rid
    record["created_at"] = now
    record["updated_at"] = now
    record["version"] = 1
    record["_seq"] = next_seq()
    collection[rid] = record
    return record


def touch_no_version(record):
    """Refresh updated_at without bumping version (derived-field recompute)."""
    record["updated_at"] = _now()
    return record


def touch(record):
    """Bump version and refresh updated_at (a real modification)."""
    record["version"] = record.get("version", 1) + 1
    record["updated_at"] = _now()
    return record
