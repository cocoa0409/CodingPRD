"""In-memory data store. Starts empty on every boot; no seeding."""
import uuid
from datetime import datetime, timezone

UTC = timezone.utc


def fmt_dt(dt):
    """ISO 8601 UTC with three fractional digits, e.g. 2026-08-01T00:00:00.000Z"""
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class Store:
    def __init__(self):
        # Logical clock: startup default exactly 2026-08-01T00:00:00Z, never wall-clock.
        self.now = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)
        self.seq = 0
        self.coordinators = {}
        self.agents = {}
        self.templates = {}
        self.subscriptions = {}
        self.files = {}
        self.milestones = {}
        self.deadlines = {}
        self.reminders = {}
        self.documents = {}
        self.communications = {}
        self.amendments = {}
        self.signature_requests = {}
        self.closing_verifications = {}
        self.invoices = {}

    def next_seq(self):
        self.seq += 1
        return self.seq


store = Store()


def mint(rec, common=True):
    rec["id"] = str(uuid.uuid4())
    rec["created_at"] = fmt_dt(store.now)
    if common:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    rec["_seq"] = store.next_seq()
    return rec


def touch(rec):
    """Every mutation refreshes updated_at and bumps version by exactly 1."""
    rec["updated_at"] = fmt_dt(store.now)
    rec["version"] += 1


# Serialized field order per entity (internal "_" prefixed keys never leak).
FIELDS = {
    "coordinator": ["id", "full_name", "email", "license_number", "status",
                    "created_at", "updated_at", "version"],
    "agent": ["id", "coordinator_id", "full_name", "email", "brokerage", "status",
              "created_at", "updated_at", "version"],
    "template": ["id", "state_code", "contract_type", "milestone_defs", "required_doc_types",
                 "status", "template_version", "created_at", "updated_at", "version"],
    "subscription": ["id", "coordinator_id", "monthly_fee_cents", "included_files_quota",
                     "overage_fee_cents", "included_files_used", "status",
                     "created_at", "updated_at", "version"],
    "file": ["id", "coordinator_id", "buyer_agent_id", "seller_agent_id", "subscription_id",
             "billing_model", "state_code", "contract_type", "property_address",
             "effective_date", "closing_date", "inspection_offset_days",
             "appraisal_offset_days", "financing_offset_days", "list_price_cents",
             "template_id", "template_version", "fee_estimate_cents", "fee_final_cents",
             "last_audit_status", "open_escalation_count", "status", "terminated_reason",
             "archived_at", "created_at", "updated_at", "version"],
    "milestone": ["id", "file_id", "name", "offset_days", "mandatory", "due_date", "status",
                  "completed_at", "late_completion", "created_at", "updated_at", "version"],
    "deadline": ["id", "file_id", "kind", "offset_days", "day_convention", "due_date",
                 "status", "met_at", "escalated", "created_at", "updated_at", "version"],
    "reminder": ["id", "deadline_id", "sequence_no", "scheduled_at", "sent_at", "status",
                 "created_at", "updated_at", "version"],
    "document": ["id", "file_id", "doc_type", "status", "submitted_by_agent_id",
                 "review_round", "reject_reason", "created_at", "updated_at", "version"],
    # CommunicationEntry carries only id + created_at; no updated_at / version.
    "communication": ["id", "file_id", "entry_kind", "author_role", "party", "direction",
                      "body", "requires_response", "response_due_at", "in_reply_to_id",
                      "status", "created_at"],
    "amendment": ["id", "file_id", "round_number", "new_effective_date", "new_closing_date",
                  "new_list_price_cents", "effective_from", "effective_to", "status",
                  "created_at", "updated_at", "version"],
    "signature_request": ["id", "amendment_id", "agent_id", "signer_party", "round_number",
                          "status", "signed_at", "created_at", "updated_at", "version"],
    "closing_verification": ["id", "file_id", "title_status", "lender_status",
                             "overall_status", "created_at", "updated_at", "version"],
    "invoice": ["id", "file_id", "subscription_id", "line_items", "subtotal_cents",
                "discount_cents", "total_cents", "status", "issued_at",
                "created_at", "updated_at", "version"],
}


def pub(kind, rec):
    return {k: rec.get(k) for k in FIELDS[kind]}


def pub_list(kind, recs):
    return [pub(kind, r) for r in recs]
