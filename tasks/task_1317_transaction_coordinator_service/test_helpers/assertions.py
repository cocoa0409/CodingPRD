"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, f"{entity}.version must be an integer >= 1"


def assert_coordinator(data: dict):
    _assert_common(data, "Coordinator")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data["license_number"], str) and data["license_number"]
    assert data["status"] in ["ACTIVE", "SUSPENDED"]


def assert_agent(data: dict):
    _assert_common(data, "Agent")
    assert is_valid_uuid(data.get("coordinator_id", "")), "Agent.coordinator_id must be a UUID"
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["brokerage"], str) and data["brokerage"]
    assert data["status"] in ["ACTIVE", "INACTIVE"]


def assert_template(data: dict):
    _assert_common(data, "ChecklistTemplate")
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert data["contract_type"] in ["PURCHASE_SALE", "LISTING_ONLY"]
    assert isinstance(data["milestone_defs"], list)
    for entry in data["milestone_defs"]:
        assert set(["name", "offset_days", "mandatory"]).issubset(entry.keys())
    assert isinstance(data["required_doc_types"], list)
    assert data["status"] in ["DRAFT", "ACTIVE", "RETIRED"]
    assert isinstance(data["template_version"], int) and data["template_version"] >= 1


def assert_subscription(data: dict):
    _assert_common(data, "Subscription")
    assert is_valid_uuid(data.get("coordinator_id", "")), "Subscription.coordinator_id must be a UUID"
    assert isinstance(data["monthly_fee_cents"], int)
    assert isinstance(data["included_files_quota"], int) and data["included_files_quota"] >= 0
    assert isinstance(data["overage_fee_cents"], int)
    assert isinstance(data["included_files_used"], int) and data["included_files_used"] >= 0
    assert data["status"] in ["ACTIVE", "CANCELLED"]


def assert_file(data: dict):
    _assert_common(data, "TransactionFile")
    assert is_valid_uuid(data.get("coordinator_id", "")), "TransactionFile.coordinator_id must be a UUID"
    assert data["billing_model"] in ["PER_FILE", "SUBSCRIPTION"]
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert data["contract_type"] in ["PURCHASE_SALE", "LISTING_ONLY"]
    assert isinstance(data["property_address"], str)
    assert isinstance(data["effective_date"], str)
    assert isinstance(data["closing_date"], str)
    assert isinstance(data["list_price_cents"], int)
    assert data["last_audit_status"] in ["NONE", "PASS", "FAIL"]
    assert isinstance(data["open_escalation_count"], int) and data["open_escalation_count"] >= 0
    assert data["status"] in ["DRAFT", "ACTIVE", "PENDING_CLOSE", "CLOSED", "ARCHIVED", "TERMINATED"]


def assert_milestone(data: dict):
    _assert_common(data, "Milestone")
    assert is_valid_uuid(data.get("file_id", "")), "Milestone.file_id must be a UUID"
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["offset_days"], int)
    assert isinstance(data["mandatory"], bool)
    assert isinstance(data["due_date"], str)
    assert data["status"] in ["PENDING", "IN_PROGRESS", "COMPLETED", "WAIVED", "CANCELLED", "OVERDUE"]
    assert isinstance(data["late_completion"], bool)


def assert_deadline(data: dict):
    _assert_common(data, "Deadline")
    assert is_valid_uuid(data.get("file_id", "")), "Deadline.file_id must be a UUID"
    assert data["kind"] in ["INSPECTION", "APPRAISAL", "FINANCING"]
    assert isinstance(data["offset_days"], int)
    assert data["day_convention"] in ["CALENDAR", "BUSINESS"]
    assert isinstance(data["due_date"], str)
    assert data["status"] in ["PENDING", "MET", "WAIVED", "EXPIRED", "CANCELLED"]
    assert isinstance(data["escalated"], bool)


def assert_reminder(data: dict):
    _assert_common(data, "Reminder")
    assert is_valid_uuid(data.get("deadline_id", "")), "Reminder.deadline_id must be a UUID"
    assert isinstance(data["sequence_no"], int) and data["sequence_no"] >= 1
    assert is_iso8601_timestamp(data.get("scheduled_at", "")), "Reminder.scheduled_at must be ISO 8601"
    assert data["status"] in ["QUEUED", "SENT", "CANCELLED"]


def assert_document(data: dict):
    _assert_common(data, "Document")
    assert is_valid_uuid(data.get("file_id", "")), "Document.file_id must be a UUID"
    assert data["doc_type"] in [
        "EXECUTED_CONTRACT", "INSPECTION_REPORT", "APPRAISAL_REPORT", "LOAN_COMMITMENT",
        "TITLE_COMMITMENT", "T47_DISCLOSURE", "NHD_REPORT", "TDS_DISCLOSURE",
        "HOA_ADDENDUM", "CLOSING_DISCLOSURE", "AMENDMENT_EXECUTED", "OTHER",
    ]
    assert data["status"] in ["REQUESTED", "RECEIVED", "ACCEPTED", "REJECTED", "CANCELLED"]
    assert isinstance(data["review_round"], int) and data["review_round"] >= 1


def assert_communication(data: dict):
    """Append-only event entity: id + created_at only; updated_at/version must be absent."""
    assert is_valid_uuid(data.get("id", "")), "CommunicationEntry.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "CommunicationEntry.created_at must be ISO 8601"
    assert "version" not in data, "CommunicationEntry must not expose version (append-only)"
    assert "updated_at" not in data, "CommunicationEntry must not expose updated_at (append-only)"
    assert is_valid_uuid(data.get("file_id", "")), "CommunicationEntry.file_id must be a UUID"
    assert data["entry_kind"] in ["LOG", "ESCALATION", "SYSTEM"]
    assert isinstance(data["author_role"], str) and data["author_role"]
    assert data["party"] in ["BUYER_AGENT", "SELLER_AGENT", "LENDER", "TITLE", "COORDINATOR", "SYSTEM"]
    assert data["direction"] in ["INBOUND", "OUTBOUND", "SYSTEM"]
    assert isinstance(data["body"], str)
    assert data["status"] in ["OPEN", "ANSWERED", "ESCALATED", "RESOLVED"]


def assert_amendment(data: dict):
    _assert_common(data, "Amendment")
    assert is_valid_uuid(data.get("file_id", "")), "Amendment.file_id must be a UUID"
    assert isinstance(data["round_number"], int) and data["round_number"] >= 1
    assert isinstance(data["effective_from"], str)
    assert isinstance(data["effective_to"], str)
    assert data["status"] in ["DRAFT", "ROUTED", "PARTIALLY_SIGNED", "FULLY_SIGNED", "EFFECTIVE", "REJECTED", "VOIDED"]


def assert_signature_request(data: dict):
    _assert_common(data, "SignatureRequest")
    assert is_valid_uuid(data.get("amendment_id", "")), "SignatureRequest.amendment_id must be a UUID"
    assert is_valid_uuid(data.get("agent_id", "")), "SignatureRequest.agent_id must be a UUID"
    assert data["signer_party"] in ["BUYER_AGENT", "SELLER_AGENT"]
    assert isinstance(data["round_number"], int) and data["round_number"] >= 1
    assert data["status"] in ["PENDING", "SIGNED", "DECLINED", "VOIDED"]


def assert_closing_verification(data: dict):
    _assert_common(data, "ClosingVerification")
    assert is_valid_uuid(data.get("file_id", "")), "ClosingVerification.file_id must be a UUID"
    assert data["title_status"] in ["PENDING", "CLEARED"]
    assert data["lender_status"] in ["PENDING", "CLEAR_TO_CLOSE", "NOT_REQUIRED"]
    assert data["overall_status"] in ["PENDING", "CLEAR_TO_CLOSE"]


def assert_invoice(data: dict):
    _assert_common(data, "Invoice")
    assert is_valid_uuid(data.get("file_id", "")), "Invoice.file_id must be a UUID"
    assert isinstance(data["line_items"], list)
    for line in data["line_items"]:
        assert line["label"] in [
            "BASE_FEE", "RUSH_SURCHARGE", "SUBSCRIPTION_OVERAGE",
            "SUBSCRIPTION_INCLUDED", "AMENDMENT_FEE", "TERMINATION_CREDIT",
        ]
        assert isinstance(line["amount_cents"], int), "line amounts are integer cents"
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["discount_cents"], int)
    assert isinstance(data["total_cents"], int)
    assert data["status"] in ["DRAFT", "ISSUED", "PAID", "VOIDED"]


def assert_invoice_invariants(data: dict):
    """Domain invariants that must hold on any invoice: totals reconcile exactly."""
    assert_invoice(data)
    assert data["subtotal_cents"] == sum(l["amount_cents"] for l in data["line_items"]), \
        "subtotal_cents must equal the sum of per-line amounts"
    assert data["total_cents"] == data["subtotal_cents"] - data["discount_cents"], \
        "total_cents must equal subtotal_cents minus discount_cents"
