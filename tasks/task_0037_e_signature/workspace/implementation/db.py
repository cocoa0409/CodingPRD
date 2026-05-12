"""In-memory data store with global lock for serialization."""

import threading
import uuid


# A single coarse-grained lock keeps every mutating endpoint serialized,
# which is sufficient for the concurrency guarantees in PRD §2.10.
LOCK = threading.RLock()


class Store:
    def __init__(self):
        self.templates = {}                    # id -> Template
        self.template_versions = {}            # id -> TemplateVersion
        self.contracts = {}                    # id -> Contract
        self.signing_steps = {}                # id -> SigningStep
        self.signing_parties = {}              # id -> SigningParty
        self.identity_verifications = {}       # id -> IdentityVerification
        self.timestamp_tokens = {}             # id -> TimestampToken
        self.evidence_packages = {}            # id -> EvidencePackage
        self.reminder_rules = {}               # id -> ReminderRule
        self.reminder_events = {}              # id -> ReminderEvent
        self.audit_logs = []                   # ordered list of AuditLog dicts
        self.org_users = {}                    # id -> OrgUser
        # Auxiliary indexes
        self.evidence_by_contract = {}         # contract_id -> evidence_package_id
        # Track which user PUBLISHED a TemplateVersion (for SoD on activation)
        self.template_version_publisher = {}   # template_version_id -> actor_user_id
        # Track reminder idempotency: (rule_id, idempotency_key) -> event_id
        self.reminder_idem = {}
        # Track re-initiation chain: source_contract_id -> new_contract_id
        self.reinit_index = {}

    def reset(self):
        self.__init__()


DB = Store()


def new_id() -> str:
    return str(uuid.uuid4())
