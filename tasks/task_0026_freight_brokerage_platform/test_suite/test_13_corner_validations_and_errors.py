"""Corner-design sections: validations & errors.

Single-violation tests for the named error_ids — each rooted in a verbatim
PRD sentence pinning the rejection condition.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    create_carrier,
    create_shipper,
    get_success_data,
    set_clock,
    setup_invoiced_load,
    validate_error,
)
from test_helpers.api_client import api_client
from test_helpers.factories import (
    create_contract_rate_payload,
    create_dispute_claim_payload,
    create_quote_request_payload,
    create_smartway_audit_payload,
    payment_payload,
)
from test_helpers import make_shipper_headers


# ─── Validations section ──────────────────────────────────────────


def test_quote_request_time_window_invalid_when_start_after_end(api):
    """PRD §3.3: "The pickup window must satisfy two conditions:
    `pickup_window_start_utc` must be strictly earlier than
    `pickup_window_end_utc`, and `pickup_window_start_utc` must be strictly
    later than the current server time. Violations are rejected with
    `ERR_TIME_WINDOW_INVALID`."

    Design: Corner/validations/quote_request_time_window_invalid_start_after_end
    """
    set_clock("2026-06-01T00:00:00Z")
    shipper = create_shipper(credit_limit_cents=100_000_000)
    res = api.create_quote_request(
        create_quote_request_payload(
            shipper["id"], lane_origin="10001", lane_destination="30303",
            distance_miles=400,
            # start > end → invalid.
            pickup_window_start_utc="2026-06-15T18:00:00Z",
            pickup_window_end_utc="2026-06-15T08:00:00Z",
            requested_equipment="DRY_VAN",
        ),
        TEST_USERS["broker_ops_headers"],
    )
    validate_error(res, "ERR_TIME_WINDOW_INVALID")


def test_credit_limit_exceeded_on_quote_create(api):
    """PRD §3.3: "The server first computes an estimated quote total using
    a conservative SPOT-mode pricing path (SPOT distance tier with no
    equipment uplift) and then verifies that `Shipper.open_ar_cents` plus
    that estimate does not exceed `Shipper.credit_limit_cents`. A breach
    is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`."

    Design: Corner/validations/credit_limit_exceeded_on_quote_create
    """
    set_clock("2026-06-01T00:00:00Z")
    # 400-mile SPOT estimate is 235*400 + 65*400 = 120000 cents. Set credit
    # limit far below.
    shipper = create_shipper(credit_limit_cents=10_000)
    res = api.create_quote_request(
        create_quote_request_payload(
            shipper["id"], lane_origin="10001", lane_destination="30303",
            distance_miles=400,
            pickup_window_start_utc="2026-06-15T08:00:00Z",
            pickup_window_end_utc="2026-06-15T18:00:00Z",
            requested_equipment="DRY_VAN",
        ),
        TEST_USERS["broker_ops_headers"],
    )
    validate_error(res, "ERR_CREDIT_LIMIT_EXCEEDED")


def test_payment_overage_rejected(api):
    """PRD §3.6: "if it would exceed the total, the request is rejected
    with `ERR_PAYMENT_OVERAGE` and no state change occurs."

    Design: Corner/validations/payment_overage_rejected
    """
    # Invoice total = 200 c/mi + 50 c/mi fuel × 400 mi = 100000.
    _shipper, _carrier, _quote, _load, invoice, _contract = setup_invoiced_load(
        contract_overrides={
            "rate_per_mile_cents": 200,
            "fuel_surcharge_per_mile_cents": 50,
        },
    )
    assert invoice["total_cents"] == 100000
    res = api.record_payment(
        invoice["id"], payment_payload(amount_cents=200_000),
        TEST_USERS["broker_ops_headers"],
    )
    validate_error(res, "ERR_PAYMENT_OVERAGE")


def test_contract_window_invalid_when_from_after_until(api):
    """PRD §3.2: "On creation the window must satisfy `effective_from_utc`
    strictly less than `effective_until_utc`; otherwise the request is
    rejected with `ERR_CONTRACT_WINDOW_INVALID`."

    Design: Corner/validations/contract_window_invalid_from_after_until
    """
    set_clock("2026-06-01T00:00:00Z")
    shipper = create_shipper(credit_limit_cents=100_000_000)
    res = api.create_contract_rate(
        create_contract_rate_payload(
            shipper["id"],
            effective_from_utc="2027-01-01T00:00:00Z",
            effective_until_utc="2026-01-01T00:00:00Z",
        ),
        TEST_USERS["broker_ops_headers"],
    )
    validate_error(res, "ERR_CONTRACT_WINDOW_INVALID")


# ─── Errors section ───────────────────────────────────────────────


def test_safety_score_too_high_on_qualify(api):
    """PRD §3.1: "To advance a carrier from `PENDING` to `QUALIFIED`, the
    operator confirms (in this order) that `mc_number` still matches the
    6-or-7-digit pattern, that `usdot_number` still matches the
    5-to-8-digit pattern, that `insurance_expiry_utc` is strictly after
    the current server time, and that `safety_score` is strictly below
    75.0. The safety check, when it fails, surfaces as
    `ERR_SAFETY_SCORE_TOO_HIGH`; the insurance check, when it fails,
    surfaces as `ERR_INSURANCE_EXPIRED`."

    Design: Corner/errors/err_safety_score_too_high_triggered
    """
    set_clock("2026-06-01T00:00:00Z")
    carrier = create_carrier(
        smartway_tier="NONE",
        insurance_expiry_utc="2027-01-01T00:00:00Z",
        safety_score=80.0,  # >= 75.0 → must fail the safety check.
    )
    res = api.qualify_carrier(carrier["id"], TEST_USERS["broker_ops_headers"])
    validate_error(res, "ERR_SAFETY_SCORE_TOO_HIGH")


def test_dispute_amount_exceeds_open_rejected(api):
    """PRD §3.7: "The contested amount is capped: `claimed_amount_cents`
    must be no greater than `Invoice.total_cents` minus
    `Invoice.amount_paid_cents`, i.e., the still-open balance on the
    invoice. A breach is rejected with `ERR_DISPUTE_AMOUNT_EXCEEDS_OPEN`."

    Design: Corner/errors/err_dispute_amount_exceeds_open
    """
    # Invoice total = 100000, no payments, open balance = 100000.
    shipper, _carrier, _quote, _load, invoice, _contract = setup_invoiced_load(
        contract_overrides={
            "rate_per_mile_cents": 200,
            "fuel_surcharge_per_mile_cents": 50,
        },
    )
    assert invoice["total_cents"] == 100000
    headers = make_shipper_headers(shipper["id"])
    res = api.create_dispute_claim(
        create_dispute_claim_payload(
            invoice["id"], claim_type="OVERCHARGE",
            claimed_amount_cents=200_000,
        ),
        headers,
    )
    validate_error(res, "ERR_DISPUTE_AMOUNT_EXCEEDS_OPEN")


def test_audit_quarter_invalid_when_quarter_not_complete(api):
    """PRD §3.8: "The label must match that pattern, the quarter must
    already be complete (i.e., the quarter's end UTC moment must be
    strictly earlier than the server's current time), and the pair
    `(shipper_id, quarter_label)` must be unique across the audit table —
    duplicates are rejected with `ERR_AUDIT_QUARTER_INVALID`. The same
    error covers all three audit-input failures."

    Design: Corner/errors/err_audit_quarter_invalid_future_quarter
    """
    # Clock pinned mid-Q2 → 2026Q2 (ends 2026-07-01) is NOT yet complete.
    set_clock("2026-04-15T00:00:00Z")
    shipper = create_shipper(credit_limit_cents=1_000_000)
    res = api.create_smartway_audit(
        create_smartway_audit_payload(shipper["id"], "2026Q2"),
        TEST_USERS["broker_ops_headers"],
    )
    validate_error(res, "ERR_AUDIT_QUARTER_INVALID")
