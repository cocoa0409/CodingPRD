"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be a positive integer"


def assert_gala_event(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["status"] in [
        "DRAFT", "SOLICITING", "CATALOGING", "BIDDING_OPEN",
        "BIDDING_CLOSED", "SETTLEMENT", "RECONCILED",
    ]
    assert isinstance(data["min_bid_pct_bps"], int)
    assert isinstance(data["min_bid_increment_cents"], int)
    assert isinstance(data["min_bid_floor_cents"], int)
    assert isinstance(data["bid_increment_tiers"], list)
    assert isinstance(data["ack_threshold_cents"], int)
    assert isinstance(data["solicitation_cooldown_days"], int)
    assert isinstance(data["cert_validity_months"], int)
    assert isinstance(data["cert_grace_days"], int)


def assert_donor(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["donor_type"] in ["INDIVIDUAL", "BUSINESS"]


def assert_bidder(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("gala_event_id", ""))
    assert isinstance(data["paddle_no"], int)
    assert isinstance(data["payment_method_on_file"], bool)
    assert data["status"] in ["REGISTERED", "SUSPENDED"]


def assert_solicitation(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("donor_id", ""))
    assert is_valid_uuid(data.get("gala_event_id", ""))
    assert data["status"] in [
        "DRAFT", "SENT", "REVISED", "PLEDGED", "STALLED", "DECLINED",
        "WITHDRAWN", "FULFILLED",
    ]
    if data.get("last_sent_at") is not None:
        assert is_iso8601_timestamp(data["last_sent_at"])


def assert_item(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("solicitation_id", ""))
    assert is_valid_uuid(data.get("donor_id", ""))
    assert is_valid_uuid(data.get("gala_event_id", ""))
    assert data["kind"] in ["PHYSICAL", "EXPERIENCE"]
    assert data["status"] in [
        "RECEIVED", "VALUED", "BUNDLED", "CATALOGED", "SOLD", "UNSOLD",
        "RETURNED_TO_DONOR", "DISCARDED",
    ]


def assert_valuation(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("item_id", ""))
    assert isinstance(data["fmv_cents"], int) and data["fmv_cents"] >= 1
    assert data["fmv_source"] in [
        "DONOR_DECLARED", "APPRAISAL", "COMPARABLE_SALE",
    ]
    assert data["status"] in ["SUBMITTED", "APPROVED", "REJECTED", "SUPERSEDED"]


def assert_bundle(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("gala_event_id", ""))
    assert data["status"] in [
        "DRAFT", "PUBLISHED", "SOLD", "UNSOLD", "SETTLED", "DISPOSITIONED",
    ]
    assert isinstance(data["bundle_fmv_cents"], int)
    assert isinstance(data["min_bid_overridden"], bool)


def assert_bid(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("bundle_id", ""))
    assert is_valid_uuid(data.get("bidder_id", ""))
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in ["ACTIVE", "OUTBID", "WINNER", "VOID"]


def assert_invoice(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("gala_event_id", ""))
    assert is_valid_uuid(data.get("bundle_id", ""))
    assert is_valid_uuid(data.get("bidder_id", ""))
    assert isinstance(data["winning_bid_cents"], int)
    assert isinstance(data["pinned_bundle_fmv_cents"], int)
    assert isinstance(data["revenue_portion_cents"], int)
    assert isinstance(data["contribution_portion_cents"], int)
    assert isinstance(data["contribution_prorata_cents"], int)
    assert isinstance(data["amount_paid_cents"], int)
    assert data["payment_status"] in [
        "UNPAID", "PARTIALLY_PAID", "PAID", "REFUNDED", "WRITTEN_OFF",
    ]
    assert data["fulfillment_status"] in [
        "PENDING", "READY", "FULFILLED", "EXPIRED", "VOIDED",
    ]


def assert_payment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("invoice_id", ""))
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1
    assert data["method"] in ["CARD", "CHECK"]
    assert data["status"] in ["INITIATED", "SUCCEEDED", "FAILED", "REFUNDED"]


def assert_certificate(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("invoice_id", ""))
    assert data["status"] in [
        "PENDING_ISSUE", "ISSUED", "REDEEMED", "EXPIRED", "VOIDED",
    ]


def assert_blackout_window(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("item_id", ""))
    assert is_iso8601_timestamp(data.get("starts_at", ""))
    assert is_iso8601_timestamp(data.get("ends_at", ""))


def assert_disposition(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("item_id", ""))
    assert is_valid_uuid(data.get("gala_event_id", ""))
    assert is_valid_uuid(data.get("donor_id", ""))
    assert data["status"] in ["PROPOSED", "DONOR_NOTIFIED", "EXECUTED"]


def assert_acknowledgment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("donor_id", ""))
    assert is_valid_uuid(data.get("gala_event_id", ""))
    assert is_valid_uuid(data.get("item_id", ""))
    assert data["kind"] == "DONATION_RECEIPT"
    assert isinstance(data["fmv_cents"], int)
    assert data["disclosure_tier"] in ["LOW", "MEDIUM", "HIGH"]
    assert data["status"] in ["PENDING", "ISSUED", "VOIDED"]


def assert_invoice_money_invariants(data: dict):
    """The aggregate revenue/contribution split must partition the winning
    bid, and paid amount can never be negative."""
    assert data["revenue_portion_cents"] + data["contribution_portion_cents"] \
        == data["winning_bid_cents"]
    assert data["revenue_portion_cents"] <= data["pinned_bundle_fmv_cents"]
    assert data["contribution_portion_cents"] >= 0
    assert data["amount_paid_cents"] >= 0
