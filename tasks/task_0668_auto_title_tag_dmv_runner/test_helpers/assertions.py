"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_account(data: dict):
    _common(data)
    assert data["account_type"] in ("RETAIL", "FLEET")
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert isinstance(data["state_code"], str)
    assert isinstance(data["credit_terms"], bool)
    assert isinstance(data["ytd_completed_count"], int) and data["ytd_completed_count"] >= 0
    assert isinstance(data["outstanding_balance_cents"], int)
    assert data["outstanding_balance_cents"] >= 0, "outstanding_balance_cents is clamped at >= 0"
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_fee_schedule(data: dict):
    _common(data)
    assert isinstance(data["state_code"], str)
    for fee in ("title_fee_cents", "registration_fee_cents", "transfer_fee_cents",
                "lien_recording_fee_cents", "use_tax_rate_bps"):
        assert isinstance(data[fee], int)
    assert data["use_tax_rate_bps"] >= 0
    assert isinstance(data["trade_in_credit_allowed"], bool)
    assert data["status"] in ("ACTIVE", "SUPERSEDED")


def assert_transaction(data: dict):
    _common(data)
    assert data["transaction_type"] in ("TITLE", "REGISTRATION", "TRANSFER", "LIEN")
    assert isinstance(data["vin"], str)
    assert data["lifecycle_status"] in (
        "DRAFT", "QUOTED", "SUBMITTED", "REJECTED", "APPROVED", "COMPLETED", "CANCELLED")
    assert data["document_status"] in ("COLLECTING", "VERIFIED", "INCOMPLETE")
    assert isinstance(data["rejection_round"], int) and data["rejection_round"] >= 0


def assert_document_item(data: dict):
    _common(data)
    assert data["checklist_code"] in (
        "TITLE_CERT", "BILL_OF_SALE", "ODOMETER", "ID_PROOF",
        "INSURANCE", "LIEN_RELEASE", "LIEN_INSTRUMENT", "POWER_OF_ATTORNEY")
    assert data["doc_status"] in ("PENDING", "VERIFIED", "REJECTED")


def assert_fee_quote(data: dict):
    _common(data)
    assert data["variant"] in ("ESTIMATE", "FINAL")
    assert data["status"] in ("ACTIVE", "SUPERSEDED", "SETTLED")
    for fee in ("tax_cents", "state_fees_cents", "service_fee_cents", "total_cents"):
        assert isinstance(data[fee], int) and data[fee] >= 0
    # total is the integer sum of the three whole-cent lines (PRD §3.5).
    assert data["total_cents"] == data["tax_cents"] + data["state_fees_cents"] + data["service_fee_cents"], \
        "total_cents must equal tax_cents + state_fees_cents + service_fee_cents"


def assert_submission(data: dict):
    _common(data)
    assert data["submission_status"] in (
        "QUEUED", "ASSIGNED", "ACCEPTED", "DMV_REJECTED", "SUPERSEDED")
    assert data["priority_class"] in ("EXPEDITE", "STANDARD")


def assert_runner_trip(data: dict):
    _common(data)
    assert data["trip_status"] in ("PLANNED", "DISPATCHED", "RETURNED", "CLOSED")
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["assigned_leg_count"], int) and data["assigned_leg_count"] >= 0


def assert_runner_leg(data: dict):
    _common(data)
    assert data["leg_status"] in ("ATTACHED", "FILED", "RESOLVED")
    assert isinstance(data["sequence_index"], int)


def assert_lien_packet(data: dict):
    _common(data)
    assert data["packet_status"] in ("DRAFT", "PERFECTED", "VOIDED")


def assert_payment(data: dict):
    """Payment is immutable: id + created_at only — no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "Payment must not carry updated_at"
    assert "version" not in data, "Payment must not carry version"
    assert data["kind"] in ("CHARGE", "REFUND")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1
