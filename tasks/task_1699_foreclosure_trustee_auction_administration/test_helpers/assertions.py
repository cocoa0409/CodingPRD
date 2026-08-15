"""Entity assertions and date/instant comparison helpers.

Field checks follow PRD §2.4: every primary resource carries id, created_at,
updated_at and version; a Postponement and a Bid carry only id and created_at.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"


def _assert_ledger(data: dict, entity: str):
    """Immutable ledger entries (Postponement, Bid): only id + created_at."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601"
    )
    assert "updated_at" not in data, f"{entity} must not carry updated_at"
    assert "version" not in data, f"{entity} must not carry version"


def assert_date_equals(actual, expected_yyyy_mm_dd: str, label: str = "date"):
    """Compare a date/datetime field by its calendar day (YYYY-MM-DD prefix)."""
    assert str(actual)[:10] == expected_yyyy_mm_dd, (
        f"Expected {label} day {expected_yyyy_mm_dd}, got {actual}"
    )


def assert_instant_equals(actual, expected_iso_prefix: str, label: str = "instant"):
    """Compare a timestamp field down to the second (first 19 chars)."""
    assert str(actual).replace("+00:00", "Z")[:19] == expected_iso_prefix[:19], (
        f"Expected {label} {expected_iso_prefix}, got {actual}"
    )


def assert_beneficiary(data: dict):
    _assert_common(data, "Beneficiary")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["reference_code"], str) and data["reference_code"]
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["total_outstanding_advances_cents"], int)


def assert_foreclosure_case(data: dict):
    _assert_common(data, "ForeclosureCase")
    assert is_valid_uuid(data.get("beneficiary_id", ""))
    assert isinstance(data["loan_reference"], str) and data["loan_reference"]
    assert isinstance(data["unpaid_principal_balance_cents"], int)
    assert data["unpaid_principal_balance_cents"] > 0
    assert isinstance(data["monthly_payment_cents"], int)
    assert isinstance(data["months_in_arrears"], int)
    assert isinstance(data["late_fee_per_month_cents"], int)
    assert data["lifecycle_status"] in (
        "REFERRED", "NOD_RECORDED", "NOTS_RECORDED", "SALE_SCHEDULED", "SOLD",
        "DEED_RECORDED", "CLOSED", "REINSTATED", "PAID_OFF", "CANCELLED",
    )
    assert data["hold_status"] in ("CLEAR", "BANKRUPTCY_STAY", "LITIGATION_HOLD")
    assert data["distribution_method"] in ("STATUTORY_PRIORITY", "PRO_RATA")
    assert isinstance(data["undistributed_surplus_cents"], int)


def assert_notice_of_default(data: dict):
    _assert_common(data, "NoticeOfDefault")
    assert data["status"] in ("RECORDED", "RESCINDED")
    assert isinstance(data["instrument_number"], str) and data["instrument_number"]


def assert_notice_of_trustee_sale(data: dict):
    _assert_common(data, "NoticeOfTrusteeSale")
    assert data["status"] in (
        "RECORDED", "PUBLICATION_COMPLETE", "SALE_SCHEDULED", "CONCLUDED", "VOIDED",
    )
    assert isinstance(data["postponement_count"], int)


def assert_publication(data: dict):
    _assert_common(data, "Publication")
    assert data["status"] in ("RUN", "AFFIDAVIT_FILED")
    assert isinstance(data["run_index"], int) and data["run_index"] >= 1


def assert_auction_sale(data: dict):
    _assert_common(data, "AuctionSale")
    assert data["status"] in ("SCHEDULED", "CONDUCTED", "CLOSED", "VOIDED")
    assert isinstance(data["venue_name"], str) and data["venue_name"]
    assert is_iso8601_timestamp(data.get("scheduled_sale_start_at", ""))


def assert_postponement(data: dict):
    _assert_ledger(data, "Postponement")
    assert data["reason"] in (
        "BENEFICIARY_REQUEST", "TRUSTEE_DISCRETION", "MUTUAL_AGREEMENT",
        "OPERATION_OF_LAW", "BANKRUPTCY_STAY",
    )
    assert data["announced_via"] in ("ADVANCE", "AT_SALE")


def assert_bidder_registration(data: dict):
    _assert_common(data, "BidderRegistration")
    assert data["status"] in (
        "PENDING", "QUALIFIED", "DISQUALIFIED", "DEPOSIT_APPLIED",
        "REFUND_PENDING", "REFUNDED",
    )
    assert isinstance(data["deposit_cents"], int) and data["deposit_cents"] > 0


def assert_bid(data: dict):
    _assert_ledger(data, "Bid")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0


def assert_bidding_instruction(data: dict):
    _assert_common(data, "BiddingInstruction")
    assert data["status"] in (
        "ACTIVE", "SUPERSEDED", "WITHDRAWN", "EXECUTED", "EXPIRED",
    )
    assert isinstance(data["opening_bid_cents"], int)
    assert isinstance(data["max_bid_cents"], int)
    assert data["strategy"] in ("OPENING_ONLY", "UP_TO_MAX")


def assert_quote(data: dict):
    _assert_common(data, "Quote")
    assert data["quote_type"] in ("REINSTATEMENT", "PAYOFF")
    assert data["status"] in (
        "ISSUED", "ACCEPTED", "SUPERSEDED", "EXPIRED", "VOIDED",
    )
    for line in (
        "arrears_cents", "late_fees_cents", "costs_cents", "interest_cents",
        "trustee_fee_cents", "prepayment_penalty_cents", "total_cents",
    ):
        assert isinstance(data[line], int), f"Quote.{line} must be integer cents"


def assert_cost_advance(data: dict):
    _assert_common(data, "CostAdvance")
    assert data["category"] in (
        "PUBLICATION", "RECORDING", "POSTING", "LEGAL",
        "PROPERTY_PRESERVATION", "OTHER",
    )
    assert data["status"] in ("SUBMITTED", "APPROVED", "DENIED", "REIMBURSED")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0


def assert_stay_order(data: dict):
    _assert_common(data, "StayOrder")
    assert data["stay_type"] in (
        "BANKRUPTCY_CHAPTER_7", "BANKRUPTCY_CHAPTER_11",
        "BANKRUPTCY_CHAPTER_13", "LITIGATION_HOLD",
    )
    assert data["status"] in ("ACTIVE", "RELEASED")


def assert_trustees_deed(data: dict):
    _assert_common(data, "TrusteesDeed")
    assert data["status"] in ("DRAFTED", "RECORDED", "VOIDED")


def assert_surplus_claim(data: dict):
    _assert_common(data, "SurplusClaim")
    assert data["claimant_type"] in (
        "JUNIOR_LIENHOLDER", "BORROWER", "JUDGMENT_CREDITOR",
    )
    assert data["status"] in ("FILED", "APPROVED", "DENIED", "PAID", "EXPIRED")
    assert isinstance(data["claimed_amount_cents"], int)
    assert isinstance(data["paid_cents"], int)


def assert_disbursement(data: dict):
    _assert_common(data, "Disbursement")
    assert data["recipient_type"] in (
        "TRUSTEE_FEE", "BENEFICIARY_COST_REIMBURSEMENT",
        "BENEFICIARY_DEBT_PAYOFF", "CLAIMANT", "BORROWER_RESIDUE",
    )
    assert data["status"] in ("CLEARED", "REVERSED")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["distribution_run_index"], int)
