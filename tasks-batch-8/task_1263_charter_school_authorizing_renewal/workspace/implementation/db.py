"""In-memory data store (PRD §2.4).

Purely in-memory Python dicts keyed by id. No persistence, no seeding —
the store starts empty on every boot and every entity any test needs is
constructed via the declared API surface.
"""
import uuid

from clock import now_iso


# One dict per entity type. Keys are the entity id (server-minted UUID).
DB = {
    "applications": {},        # CharterApplication
    "interviews": {},          # CapacityInterview
    "schools": {},             # School
    "contracts": {},           # CharterContract
    "targets": {},             # PerformanceTarget
    "monitoring_reports": {},  # MonitoringReport
    "lotteries": {},           # Lottery
    "lottery_entries": {},     # LotteryEntry
    "interventions": {},       # InterventionNotice
    "corrective_plans": {},    # CorrectiveActionPlan
    "renewal_decisions": {},   # RenewalDecision
    "closure_plans": {},       # ClosurePlan
    "student_transitions": {}, # StudentTransition
    "fee_invoices": {},        # FeeInvoice
    "appeals": {},             # Appeal
}


def new_id() -> str:
    """Server-minted UUID with no type prefix (PRD §2.4)."""
    return str(uuid.uuid4())


def insert(collection: str, record: dict) -> dict:
    DB[collection][record["id"]] = record
    return record


def get(collection: str, record_id: str):
    return DB[collection].get(record_id)


def all_records(collection: str):
    return list(DB[collection].values())


def stamp_new(record: dict) -> dict:
    """Set the four server-managed properties on a fresh record (§2.4)."""
    ts = now_iso()
    record["id"] = new_id()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    return record


def touch(record: dict) -> dict:
    """Bump version and refresh updated_at on a mutation (§2.4)."""
    record["version"] = record.get("version", 1) + 1
    record["updated_at"] = now_iso()
    return record
