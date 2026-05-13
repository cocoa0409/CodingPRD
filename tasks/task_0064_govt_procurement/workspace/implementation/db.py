"""In-memory data store and common-field helpers."""

import threading
import uuid

from clock import clock


class DB:
    def __init__(self):
        self.lock = threading.RLock()
        self.suppliers = {}              # id -> Supplier
        self.plans = {}                  # id -> ProcurementPlan
        self.plan_items = {}             # id -> PlanItem
        self.projects = {}               # id -> Project
        self.tender_documents = {}       # id -> TenderDocument
        # auxiliary index: project_id -> tender_document_id
        self.tender_by_project = {}
        # auxiliary index: project_id -> award_id
        self.award_by_project = {}
        # auxiliary index: project_id -> contract_id
        self.contract_by_project = {}
        # auxiliary index: project_id -> committee_id
        self.committee_by_project = {}
        # Snapshot of tender version at award time, keyed by award_id
        self.award_tender_version = {}
        self.bids = {}                   # id -> Bid
        self.committees = {}             # id -> EvaluationCommittee
        self.awards = {}                 # id -> Award
        self.contracts = {}              # id -> Contract
        self.contract_amendments = {}    # id -> ContractAmendment
        self.queries = {}                # id -> Query
        self.complaints = {}             # id -> Complaint
        self.audit_logs = []             # list of AuditLog dicts (ordered)
        # External: stable mock pool of EvaluationExperts available to be selected.
        # Caller provides expert ids via the eligible_pool when forming a committee.
        # We just rely on the pool provided in the request body for flexibility.

    def new_id(self) -> str:
        return str(uuid.uuid4())


db = DB()


def now_iso() -> str:
    return clock.now_iso()


def common_fields_create() -> dict:
    """Return the {created_at, updated_at, version} subset for a brand-new entity."""
    ts = now_iso()
    return {"created_at": ts, "updated_at": ts, "version": 1}


def light_fields_create() -> dict:
    """Return the {created_at} subset for lighter entities (no version / updated_at)."""
    return {"created_at": now_iso()}


def bump_version(entity: dict) -> None:
    """Mutate an entity to refresh updated_at and bump version (in place)."""
    if "version" in entity:
        entity["version"] = int(entity.get("version", 0)) + 1
    if "updated_at" in entity:
        entity["updated_at"] = now_iso()


def touch(entity: dict) -> None:
    """Refresh updated_at without bumping version (for entities with domain-version)."""
    if "updated_at" in entity:
        entity["updated_at"] = now_iso()
