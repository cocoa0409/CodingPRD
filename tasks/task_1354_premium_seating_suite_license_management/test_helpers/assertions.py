"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AccountStatus, AccountType, AgreementStatus, AssessmentStatus, AllocationMethod,
    CateringOrderStatus, CredentialStatus, CredentialType, CreditStanding, EventStatus,
    EventType, InvoiceStatus, InvoiceType, PackageTier, PaymentMethod, PaymentStatus,
    RentalStatus, RenewalOfferStatus, SeasonStatus, SuiteStatus, SuiteTier,
    SuspensionReason, TransferStatus, TransferType, WaitlistStatus,
)


def _assert_common(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"{entity}.version must be a positive integer"


def assert_venue(data: dict):
    _assert_common(data, "Venue")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["address"], str) and data["address"]
    assert isinstance(data["default_catering_cutoff_hours"], int)


def assert_suite(data: dict):
    _assert_common(data, "Suite")
    assert is_valid_uuid(data.get("venue_id", ""))
    assert isinstance(data["suite_code"], str) and data["suite_code"]
    assert data["tier"] in [t.value for t in SuiteTier]
    assert isinstance(data["capacity_seats"], int) and data["capacity_seats"] > 0
    assert isinstance(data["base_annual_fee_cents"], int) and data["base_annual_fee_cents"] >= 0
    assert isinstance(data["f_b_minimum_cents"], int) and data["f_b_minimum_cents"] >= 0
    assert data["status"] in [s.value for s in SuiteStatus]


def assert_season(data: dict):
    _assert_common(data, "Season")
    assert is_valid_uuid(data.get("venue_id", ""))
    assert isinstance(data["label"], str) and data["label"]
    assert is_iso8601_timestamp(data.get("starts_on", ""))
    assert is_iso8601_timestamp(data.get("ends_on", ""))
    assert is_iso8601_timestamp(data.get("renewal_window_opens_on", ""))
    assert is_iso8601_timestamp(data.get("renewal_window_closes_on", ""))
    assert data["status"] in [s.value for s in SeasonStatus]


def assert_event(data: dict):
    _assert_common(data, "Event")
    assert is_valid_uuid(data.get("season_id", ""))
    assert isinstance(data["name"], str) and data["name"]
    assert data["event_type"] in [t.value for t in EventType]
    assert is_iso8601_timestamp(data.get("starts_at", ""))
    assert isinstance(data["duration_hours"], int) and data["duration_hours"] > 0
    assert isinstance(data["rental_base_price_cents"], int) and data["rental_base_price_cents"] >= 0
    assert data["status"] in [s.value for s in EventStatus]


def assert_account(data: dict):
    _assert_common(data, "Account")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["account_type"] in [t.value for t in AccountType]
    assert isinstance(data["tax_id"], str) and data["tax_id"]
    assert isinstance(data["billing_email"], str) and data["billing_email"]
    assert data["status"] in [s.value for s in AccountStatus]
    assert data["credit_standing"] in [c.value for c in CreditStanding]
    assert isinstance(data["balance_due_cents"], int) and data["balance_due_cents"] >= 0
    assert isinstance(data["lifetime_spend_cents"], int) and data["lifetime_spend_cents"] >= 0


def assert_agreement(data: dict):
    _assert_common(data, "LicenseAgreement")
    assert is_valid_uuid(data.get("suite_id", ""))
    assert is_valid_uuid(data.get("account_id", ""))
    assert is_valid_uuid(data.get("start_season_id", ""))
    assert 1 <= data["term_seasons"] <= 10
    assert isinstance(data["base_annual_fee_cents"], int) and data["base_annual_fee_cents"] >= 0
    assert 0 <= data["escalator_bp"] <= 2000
    assert isinstance(data["f_b_minimum_cents"], int) and data["f_b_minimum_cents"] >= 0
    assert data["status"] in [s.value for s in AgreementStatus]
    assert isinstance(data["suspension_count"], int) and data["suspension_count"] >= 0
    if data.get("suspension_reason") is not None:
        assert data["suspension_reason"] in [r.value for r in SuspensionReason]
    if data.get("executed_on") is not None:
        assert is_iso8601_timestamp(data["executed_on"])
    if data.get("fee_schedule_cents") is not None:
        assert isinstance(data["fee_schedule_cents"], list)
        assert all(isinstance(x, int) for x in data["fee_schedule_cents"])


def assert_invoice(data: dict):
    _assert_common(data, "Invoice")
    assert is_valid_uuid(data.get("account_id", ""))
    assert data["invoice_type"] in [t.value for t in InvoiceType]
    assert isinstance(data["lines"], list) and len(data["lines"]) >= 1
    for line in data["lines"]:
        assert isinstance(line["quantity"], int) and line["quantity"] > 0
        assert isinstance(line["unit_price_cents"], int) and line["unit_price_cents"] >= 0
    assert isinstance(data["subtotal_cents"], int) and data["subtotal_cents"] >= 0
    assert isinstance(data["late_fee_cents"], int) and data["late_fee_cents"] >= 0
    assert isinstance(data["amount_paid_cents"], int) and data["amount_paid_cents"] >= 0
    assert isinstance(data["amount_due_cents"], int) and data["amount_due_cents"] >= 0
    assert is_iso8601_timestamp(data.get("due_on", ""))
    assert data["status"] in [s.value for s in InvoiceStatus]


def assert_payment(data: dict):
    _assert_common(data, "Payment")
    assert is_valid_uuid(data.get("account_id", ""))
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["method"] in [m.value for m in PaymentMethod]
    assert isinstance(data["allocations"], list) and len(data["allocations"]) >= 1
    assert data["status"] in [s.value for s in PaymentStatus]


def assert_catering_order(data: dict):
    _assert_common(data, "CateringOrder")
    assert is_valid_uuid(data.get("event_id", ""))
    assert is_valid_uuid(data.get("suite_id", ""))
    # Exactly one of agreement_id / rental_id (PRD §3.6).
    assert (data.get("agreement_id") is None) != (data.get("rental_id") is None)
    assert data["package_tier"] in [t.value for t in PackageTier]
    assert isinstance(data["guest_count"], int) and data["guest_count"] > 0
    assert isinstance(data["subtotal_cents"], int) and data["subtotal_cents"] >= 0
    assert isinstance(data["service_fee_cents"], int) and data["service_fee_cents"] >= 0
    assert isinstance(data["total_cents"], int)
    assert data["total_cents"] == data["subtotal_cents"] + data["service_fee_cents"]
    assert isinstance(data["accrual_cents"], int) and data["accrual_cents"] >= 0
    assert isinstance(data["cancel_fee_cents"], int) and data["cancel_fee_cents"] >= 0
    assert data["status"] in [s.value for s in CateringOrderStatus]


def assert_credential(data: dict):
    _assert_common(data, "AccessCredential")
    assert is_valid_uuid(data.get("event_id", ""))
    assert is_valid_uuid(data.get("suite_id", ""))
    assert (data.get("agreement_id") is None) != (data.get("rental_id") is None)
    assert isinstance(data["guest_name"], str) and data["guest_name"]
    assert isinstance(data["guest_email"], str) and data["guest_email"]
    assert data["credential_type"] in [t.value for t in CredentialType]
    assert isinstance(data["barcode"], str) and data["barcode"]
    assert data["status"] in [s.value for s in CredentialStatus]


def assert_rental(data: dict):
    _assert_common(data, "SingleEventRental")
    assert is_valid_uuid(data.get("event_id", ""))
    assert is_valid_uuid(data.get("suite_id", ""))
    assert is_valid_uuid(data.get("account_id", ""))
    assert isinstance(data["guest_count"], int) and data["guest_count"] > 0
    assert isinstance(data["quoted_price_cents"], int) and data["quoted_price_cents"] >= 0
    assert isinstance(data["deposit_cents"], int) and data["deposit_cents"] >= 0
    assert isinstance(data["cancel_fee_cents"], int) and data["cancel_fee_cents"] >= 0
    assert data["status"] in [s.value for s in RentalStatus]


def assert_transfer_request(data: dict):
    _assert_common(data, "TransferRequest")
    assert is_valid_uuid(data.get("agreement_id", ""))
    assert is_valid_uuid(data.get("from_account_id", ""))
    assert is_valid_uuid(data.get("to_account_id", ""))
    assert data["from_account_id"] != data["to_account_id"]
    assert data["transfer_type"] in [t.value for t in TransferType]
    assert isinstance(data["asking_price_cents"], int) and data["asking_price_cents"] >= 0
    assert data["status"] in [s.value for s in TransferStatus]


def assert_renewal_offer(data: dict):
    _assert_common(data, "RenewalOffer")
    assert is_valid_uuid(data.get("agreement_id", ""))
    assert is_valid_uuid(data.get("season_id", ""))
    assert isinstance(data["proposed_fee_cents"], int) and data["proposed_fee_cents"] >= 0
    assert 0 <= data["proposed_escalator_bp"] <= 2000
    assert 1 <= data["proposed_term_seasons"] <= 10
    assert is_iso8601_timestamp(data.get("response_due_on", ""))
    assert isinstance(data["round_index"], int) and data["round_index"] >= 1
    assert data["status"] in [s.value for s in RenewalOfferStatus]


def assert_waitlist_entry(data: dict):
    _assert_common(data, "WaitlistEntry")
    assert is_valid_uuid(data.get("account_id", ""))
    assert data["desired_tier"] in [t.value for t in SuiteTier]
    assert isinstance(data["priority_score"], (int, float))
    assert data["status"] in [s.value for s in WaitlistStatus]


def assert_assessment(data: dict):
    _assert_common(data, "Assessment")
    assert is_valid_uuid(data.get("venue_id", ""))
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["total_cost_cents"], int) and data["total_cost_cents"] > 0
    assert data["allocation_method"] in [m.value for m in AllocationMethod]
    assert data["status"] in [s.value for s in AssessmentStatus]


def assert_invoice_amounts(data: dict):
    """PRD §3.4 invariant: amount_due = subtotal + late_fee - amount_paid, floored at 0."""
    expected = data["subtotal_cents"] + data["late_fee_cents"] - data["amount_paid_cents"]
    assert data["amount_due_cents"] == max(0, expected), (
        f"amount_due_cents {data['amount_due_cents']} != max(0, {expected})"
    )
