"""Corner-design section: calculations.

Numeric formula claims pinned by a single PRD sentence — invoice-total
aggregation, SPOT-tier inclusive-250 boundary, and the credit-risk
zero-baseline.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    attach_accessorial,
    create_shipper,
    deliver_load,
    get_success_data,
    set_clock,
    setup_awarded_load,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.factories import create_quote_request_payload


def test_invoice_total_sums_agreed_detention_and_accessorial(api):
    """PRD §3.6: "`Invoice.total_cents` is computed at issue time as the sum
    of the load's `agreed_rate_cents`, the load's `detention_charge_cents`,
    and the running sum of `Accessorial.amount_cents` over every
    accessorial whose `load_id` matches the load, minus the running sum of
    `resolution_amount_cents` over every `RESOLVED` dispute claim on this
    invoice whose `resolution_kind` is `PARTIAL`. The calculation sums
    first and subtracts second; the partial-resolution credits are not
    netted per-line. At issue time, before any disputes have been raised,
    the subtractive term is zero and the formula reduces to the additive
    sum."

    Design: Corner/calculations/invoice_total_sums_agreed_detention_and_accessorial
    """
    # Contract 250 c/mi + 60 c/mi fuel, free=110 → quote total 124000.
    # Pickup 3hr late → detention 15000 (180 - 110 = 70 → ceil(70/60)=2hr × 7500).
    # LUMPER accessorial 8000.
    # Invoice.total_cents = 124000 + 15000 + 8000 = 147000.
    shipper, carrier, _quote, load, _contract = setup_awarded_load(
        pickup_window_start_utc="2026-06-10T08:00:00Z",
        pickup_window_end_utc="2026-06-10T18:00:00Z",
        distance_miles=400, requested_equipment="DRY_VAN",
        contract_overrides={
            "rate_per_mile_cents": 250,
            "fuel_surcharge_per_mile_cents": 60,
            "detention_free_minutes": 110,
            "detention_rate_per_hour_cents": 7500,
        },
    )
    delivered = deliver_load(
        load, carrier,
        actual_pickup_at_utc="2026-06-10T11:00:00Z",
        actual_delivery_at_utc="2026-06-11T11:00:00Z",
    )
    assert delivered["detention_charge_cents"] == 15000
    attach_accessorial(load["id"], code="LUMPER", amount_cents=8000,
                       note="Lumper service")
    invoice = get_success_data(api.invoice_load(
        load["id"], TEST_USERS["broker_ops_headers"],
    ))
    assert invoice["total_cents"] == 147000


def test_spot_tier_boundary_at_250_miles_inclusive(api):
    """PRD §3.3: "SPOT pricing applies a distance-tiered per-mile rate:
    for `distance_miles` of at most 250, the per-mile rate is 320 cents;
    for `distance_miles` of 251 through 750 inclusive, the per-mile rate
    is 235 cents; for `distance_miles` of 751 or more, the per-mile rate
    is 195 cents."
    PRD §3.3: "The linehaul term is the chosen per-mile rate multiplied
    by `distance_miles`, and the fuel term is a flat 65 cents per mile
    multiplied by `distance_miles`."
    PRD §3.3: "SPOT pricing further adds an equipment uplift expressed
    as a percentage of linehaul: `DRY_VAN` adds 0 percent, `REEFER`
    adds 18 percent, and `FLATBED` adds 10 percent."

    Design: Corner/calculations/spot_tier_boundary_at_250_miles_inclusive
    """
    set_clock("2026-06-01T00:00:00Z")
    shipper = create_shipper(credit_limit_cents=100_000_000)
    quote = get_success_data(api.create_quote_request(
        create_quote_request_payload(
            shipper["id"],
            lane_origin="10001", lane_destination="30303",
            distance_miles=250,
            pickup_window_start_utc="2026-06-15T08:00:00Z",
            pickup_window_end_utc="2026-06-15T18:00:00Z",
            requested_equipment="DRY_VAN",
        ),
        TEST_USERS["broker_ops_headers"],
    ))
    # At exactly 250 mi the tier is tier1 (320 c/mi): linehaul=80000;
    # fuel=65 × 250 = 16250; DRY_VAN uplift=0. Total=96250.
    assert quote["rate_mode"] == "SPOT"
    assert quote["quoted_total_cents"] == 96250


def test_credit_risk_baseline_zero_for_brand_new_shipper(api):
    """PRD §3.9: "Shipper credit risk is exposed as a read-only computation
    rather than a stored attribute."
    PRD §3.9: "First, the `utilization_ratio` is `Shipper.open_ar_cents`
    divided by the maximum of `Shipper.credit_limit_cents` and one (the
    `max(·, 1)` guard prevents a divide-by-zero on a zero-credit-limit
    shipper)."
    PRD §3.9: "The composite credit-risk `score` is then computed as 0.6
    multiplied by the minimum of `utilization_ratio` and 1.0 multiplied
    by 100 (no intermediate rounding on the utilization term), plus 5
    multiplied by `late_count`, plus 8 multiplied by `dispute_count`. The
    result is rounded half-up to a whole integer."

    Design: Corner/calculations/shipper_credit_risk_score_baseline_low_utilization
    """
    set_clock("2026-06-01T00:00:00Z")
    shipper = create_shipper(
        legal_name="Alpha Two Shippers",
        billing_email="ap@alpha2.test",
        credit_limit_cents=200_000,
    )
    res = api.get_credit_risk(shipper["id"], TEST_USERS["broker_ops_headers"])
    body = validate_success(res, 200)
    # Brand new shipper: open_ar=0, no invoices, no disputes.
    # score = round(0.6 × 0 × 100 + 5×0 + 8×0) = 0.
    # utilization_ratio = 0 / max(200000, 1) = 0.0.
    assert body["score"] == 0
    assert body["utilization_ratio"] == 0 or body["utilization_ratio"] == 0.0
    assert body["late_count"] == 0
    assert body["dispute_count"] == 0
