"""Corner-design sections: cross_cutting_complexity_layers, consistency_model.

Cascade and immediate-visibility claims — pinned to verbatim PRD sentences.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    award_quote_payload,
    create_qualified_carrier,
    create_quote,
    create_shipper,
    get_success_data,
    pay_invoice,
    set_clock,
    setup_invoiced_load,
    validate_success,
)
from test_helpers.api_client import api_client


# ─── Cross-cutting / cascades ─────────────────────────────────────


def test_full_payment_cascades_load_to_closed(api):
    """PRD §3.6: "Whenever a payment lands, `Shipper.open_ar_cents` is
    recomputed in the same transaction so the AR conservation invariant
    in §2.9 continues to hold. When a payment carries the invoice to
    `PAID`, the cascade additionally moves the parent load `INVOICED →
    CLOSED`, advancing the load's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/cascading_side_effects_payment_closes_load
    """
    shipper, _carrier, _quote, load, invoice, _contract = setup_invoiced_load(
        contract_overrides={
            "rate_per_mile_cents": 200,
            "fuel_surcharge_per_mile_cents": 50,
        },
    )
    assert invoice["total_cents"] == 100000
    pay_invoice(invoice["id"], amount_cents=100_000)

    invoice_after = get_success_data(
        api_client.get_invoice(invoice["id"], TEST_USERS["broker_ops_headers"])
    )
    load_after = get_success_data(
        api_client.get_load(load["id"], TEST_USERS["broker_ops_headers"])
    )
    assert invoice_after["status"] == "PAID"
    assert invoice_after["amount_paid_cents"] == 100000
    assert load_after["status"] == "CLOSED"


def test_open_ar_reconciles_after_partial_payment(api):
    """PRD §2.9: "`Shipper.open_ar_cents` is, at every observable moment,
    the sum of `Invoice.total_cents - Invoice.amount_paid_cents` taken
    over every `Invoice` that reaches the shipper through its load chain
    (an invoice belongs to a shipper when its `load_id` resolves to a
    `Load` whose `quote_request_id` resolves to a `QuoteRequest` whose
    `shipper_id` equals the shipper) and whose `status` is one of
    `ISSUED`, `PARTIALLY_PAID`, or `DISPUTED`."

    Design: Corner/cross_cutting_complexity_layers/derived_field_open_ar_reconciliation
    """
    shipper, _carrier, _quote, _load, invoice, _contract = setup_invoiced_load(
        contract_overrides={
            "rate_per_mile_cents": 200,
            "fuel_surcharge_per_mile_cents": 50,
        },
    )
    assert invoice["total_cents"] == 100000

    # Partial payment of 40000.
    pay_invoice(invoice["id"], amount_cents=40_000)
    invoice_after = get_success_data(
        api_client.get_invoice(invoice["id"], TEST_USERS["broker_ops_headers"])
    )
    shipper_after = get_success_data(
        api_client.get_shipper(shipper["id"], TEST_USERS["broker_ops_headers"])
    )
    assert invoice_after["status"] == "PARTIALLY_PAID"
    assert invoice_after["amount_paid_cents"] == 40_000
    # open_ar = total - amount_paid = 100000 - 40000 = 60000.
    assert shipper_after["open_ar_cents"] == 60_000


# ─── Consistency model ────────────────────────────────────────────


def test_award_response_carries_freshly_created_load_atomically(api):
    """PRD §3.4: "When all checks pass, the server performs the award as
    a single transaction: the quote moves `OPEN → AWARDED` and its
    `version` advances by one; a new `Load` row is created with
    `quote_request_id` set to the quote's `id`, `carrier_id` set to the
    supplied carrier, `agreed_rate_cents` set to the quote's
    `quoted_total_cents`, `detention_charge_cents` initialized to zero,
    `accessorial_total_cents` initialized to zero, `pod_received_at_utc`
    initialized to null, `actual_pickup_at_utc` and
    `actual_delivery_at_utc` initialized to null, and `status` set to
    `AWARDED`. The award endpoint returns the newly created `Load`, not
    the quote, because the load is the entity the operator will reference
    for every subsequent step."

    Design: Corner/consistency_model/immediate_consistency_load_visible_in_award_response
    """
    set_clock("2026-06-01T00:00:00Z")
    shipper = create_shipper(credit_limit_cents=100_000_000)
    carrier = create_qualified_carrier(
        smartway_tier="NONE",
        insurance_expiry_utc="2027-01-01T00:00:00Z",
        safety_score=30.0,
    )
    quote = create_quote(
        shipper["id"], lane_origin="10001", lane_destination="30303",
        distance_miles=250, requested_equipment="DRY_VAN",
        pickup_window_start_utc="2026-06-15T08:00:00Z",
        pickup_window_end_utc="2026-06-15T18:00:00Z",
    )
    # SPOT @ 250 mi: tier1 (320 c/mi) × 250 + fuel 65 × 250 + 0% uplift =
    # 80000 + 16250 = 96250.
    assert quote["rate_mode"] == "SPOT"
    assert quote["quoted_total_cents"] == 96250

    res = api.award_quote(
        quote["id"], award_quote_payload(carrier["id"], quote["version"]),
        TEST_USERS["broker_ops_headers"],
    )
    body = validate_success(res, 200)
    # The response body is the freshly created Load (not the quote).
    assert body["status"] == "AWARDED"
    assert body["agreed_rate_cents"] == 96250
    assert body["quote_request_id"] == quote["id"]
    assert body["carrier_id"] == carrier["id"]

    # Sanity: the parent quote is now AWARDED too.
    quote_after = get_success_data(api_client.get_quote_request(
        quote["id"], TEST_USERS["broker_ops_headers"],
    ))
    assert quote_after["status"] == "AWARDED"
