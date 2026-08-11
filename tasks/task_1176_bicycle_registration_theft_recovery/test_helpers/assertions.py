"""Entity assertions and domain invariant checkers (PRD §2.5, §2.8, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict, entity: str):
    """Standard system-managed fields present on every primary resource (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be an ISO 8601 timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be an ISO 8601 timestamp"
    )
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"


def assert_owner(data: dict):
    _assert_common_fields(data, "Owner")
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert "password" not in data, "password must never be returned (PRD §3.1)"
    assert isinstance(data["bikes_registered_count"], int)


def assert_partner_org(data: dict):
    _assert_common_fields(data, "PartnerOrg")
    assert data["org_type"] in ["LAW_ENFORCEMENT", "BIKE_SHOP", "CAMPUS"]
    assert data["status"] in ["PENDING", "ACTIVE", "SUSPENDED", "REVOKED"]


def assert_bicycle(data: dict):
    _assert_common_fields(data, "Bicycle")
    assert isinstance(data["serial_number"], str) and data["serial_number"]
    assert isinstance(data["serial_normalized"], str) and data["serial_normalized"]
    assert isinstance(data["declared_value_cents"], int)
    assert data["declared_value_cents"] >= 0
    assert isinstance(data["registration_fee_cents"], int)
    assert data["registration_fee_cents"] >= 0
    assert data["registry_status"] in ["REGISTERED", "STOLEN", "RECOVERED", "RETURNED"]
    assert data["integrity_status"] in ["CLEAR", "DUPLICATE_SUSPECT", "MERGED"]
    assert is_valid_uuid(data.get("current_owner_id", ""))


def assert_transfer(data: dict):
    _assert_common_fields(data, "OwnershipTransfer")
    assert is_valid_uuid(data.get("bicycle_id", ""))
    assert isinstance(data["sale_price_cents"], int)
    assert data["sale_price_cents"] >= 0
    assert data["status"] in [
        "PENDING_ACCEPTANCE", "COMPLETED", "REJECTED", "CANCELLED", "EXPIRED",
    ]


def assert_theft_report(data: dict):
    _assert_common_fields(data, "TheftReport")
    assert is_valid_uuid(data.get("bicycle_id", ""))
    assert is_valid_uuid(data.get("owner_id", ""))
    assert data["status"] in [
        "UNDER_REVIEW", "NEEDS_INFO", "FLAGGED", "REJECTED", "WITHDRAWN",
        "CLOSED_RECOVERED",
    ]


def assert_recovery_intake(data: dict):
    _assert_common_fields(data, "RecoveryIntake")
    assert is_valid_uuid(data.get("partner_org_id", ""))
    assert isinstance(data["appraised_value_cents"], int)
    assert data["appraised_value_cents"] >= 0
    assert data["status"] in [
        "INTAKE", "CLAIM_PENDING", "RETURNED", "UNCLAIMED",
        "DISPOSITION_SCHEDULED", "DISPOSED",
    ]


def assert_match_candidate(data: dict):
    _assert_common_fields(data, "MatchCandidate")
    assert is_valid_uuid(data.get("recovery_intake_id", ""))
    assert is_valid_uuid(data.get("theft_report_id", ""))
    assert is_valid_uuid(data.get("bicycle_id", ""))
    assert isinstance(data["screening_score"], int)
    assert 0 <= data["screening_score"] <= 10000
    assert isinstance(data["forensic_score"], int)
    assert 0 <= data["forensic_score"] <= 10000
    assert data["status"] in ["PROPOSED", "NOTIFIED", "CONFIRMED", "DISMISSED", "EXPIRED"]


def assert_claim(data: dict):
    _assert_common_fields(data, "OwnerClaim")
    assert is_valid_uuid(data.get("recovery_intake_id", ""))
    assert is_valid_uuid(data.get("match_id", ""))
    assert is_valid_uuid(data.get("owner_id", ""))
    assert data["status"] in ["UNDER_REVIEW", "APPROVED", "REJECTED", "WITHDRAWN"]


def assert_auction(data: dict):
    _assert_common_fields(data, "Auction")
    assert is_valid_uuid(data.get("recovery_intake_id", ""))
    assert isinstance(data["reserve_price_cents"], int)
    assert data["reserve_price_cents"] >= 1000
    assert isinstance(data["estimated_storage_fee_cents"], int)
    assert isinstance(data["estimated_program_commission_cents"], int)
    assert isinstance(data["estimated_partner_payout_cents"], int)
    assert data["status"] in [
        "SCHEDULED", "OPEN", "CLOSED", "SETTLED", "VOIDED", "CANCELLED",
    ]


def assert_bid(data: dict):
    _assert_common_fields(data, "Bid")
    assert is_valid_uuid(data.get("auction_id", ""))
    assert is_valid_uuid(data.get("bidder_owner_id", ""))
    assert isinstance(data["amount_cents"], int)
    assert data["amount_cents"] >= 1
    assert data["status"] in [
        "ACTIVE", "OUTBID", "WINNING", "WON", "LOST", "RETRACTED",
    ]


def assert_event(data: dict):
    _assert_common_fields(data, "RegistryEvent")
    assert is_valid_uuid(data.get("host_org_id", ""))
    assert isinstance(data["capacity"], int)
    assert data["capacity"] >= 1
    assert isinstance(data["registered_count"], int)
    assert data["status"] in ["DRAFT", "PUBLISHED", "COMPLETED", "CANCELLED"]


def assert_event_registration(data: dict):
    _assert_common_fields(data, "EventRegistration")
    assert is_valid_uuid(data.get("event_id", ""))
    assert is_valid_uuid(data.get("owner_id", ""))
    assert data["status"] in ["BOOKED", "CANCELLED"]
    assert isinstance(data["waiver_code"], str) and data["waiver_code"]
    assert isinstance(data["waiver_used"], bool)


def assert_duplicate_flag(data: dict):
    _assert_common_fields(data, "DuplicateFlag")
    assert is_valid_uuid(data.get("bicycle_a_id", ""))
    assert is_valid_uuid(data.get("bicycle_b_id", ""))
    assert isinstance(data["confidence_score"], int)
    assert 0 <= data["confidence_score"] <= 10000
    assert data["status"] in ["OPEN", "CONFIRMED", "DISMISSED"]


def assert_ledger_entry(data: dict):
    """LedgerEntry is append-only: id + created_at only from the common set (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), "LedgerEntry.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "LedgerEntry.created_at must be an ISO 8601 timestamp"
    )
    assert "updated_at" not in data, "LedgerEntry must not expose updated_at (PRD §2.5)"
    assert "version" not in data, "LedgerEntry must not expose version (PRD §2.5)"
    assert data["entry_type"] in [
        "REGISTRATION_FEE", "FEE_WAIVER", "TRANSFER_FEE", "STORAGE_FEE",
        "AUCTION_COMMISSION", "AUCTION_PARTNER_PAYOUT", "AUCTION_ESCROW", "REVERSAL",
    ]
    assert data["direction"] in ["DEBIT", "CREDIT"]
    assert data["account"] in ["OWNER", "PARTNER_ORG", "PROGRAM", "ESCROW"]
    assert isinstance(data["amount_cents"], int)
    assert data["amount_cents"] >= 0


def assert_notification(data: dict):
    _assert_common_fields(data, "Notification")
    assert is_valid_uuid(data.get("owner_id", ""))
    assert data["kind"] in [
        "MATCH_FOUND", "CLAIM_APPROVED", "CLAIM_REJECTED", "TRANSFER_COMPLETED",
        "TRANSFER_CANCELLED_STOLEN", "REPORT_FLAGGED", "BID_OUTBID", "AUCTION_WON",
    ]
    assert isinstance(data["read"], bool)


def assert_ledger_balance(entries: list):
    """Double-entry invariant: SUM(CREDIT) - SUM(DEBIT) == 0 over all rows (PRD §2.8)."""
    credits = sum(e["amount_cents"] for e in entries if e["direction"] == "CREDIT")
    debits = sum(e["amount_cents"] for e in entries if e["direction"] == "DEBIT")
    assert credits == debits, (
        f"Ledger out of balance: CREDIT total {credits} != DEBIT total {debits}"
    )
    return credits, debits


def assert_seat_invariant(event: dict, booked_count: int):
    """registered_count == COUNT(BOOKED registrations) and 0 <= count <= capacity (PRD §3.9)."""
    assert event["registered_count"] == booked_count, (
        f"registered_count {event['registered_count']} != BOOKED count {booked_count}"
    )
    assert 0 <= event["registered_count"] <= event["capacity"]
