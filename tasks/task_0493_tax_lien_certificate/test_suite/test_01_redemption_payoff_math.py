"""Redemption / payoff-quote calculation tests.

Covers the dual-variant payoff (bid-down vs premium), the per-component
rounding of subsequent-tax interest, the floor-day boundary on accrual, and the
non-mutating payoff quote.
"""
import pytest

from test_helpers import (
    validate_success,
    api_client,
    TEST_USERS,
    make_investor_headers,
    assert_redemption,
)
from test_helpers import fixtures as fx

TREASURER = TEST_USERS["treasurer_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def test_redemption_payoff_bid_down_no_premium(api):
    """PRD §3.9: "The `face_interest_cents` is simple interest on the face: the
    face amount multiplied by the certificate's `rate_bps`, multiplied by the
    whole elapsed days from `issued_at` to `redeemed_at`, divided by 10,000 times
    the county's `day_count_basis`, rounded half-up to whole cents."
    PRD §3.9: "The `penalty_cents` is the flat penalty: the face amount
    multiplied by the county's `penalty_rate_bps`, divided by 10,000, rounded
    half-up"
    PRD §3.9: "when `premium_earns_interest` is false it is 0."

    Design: Difficulty/dual_variant_calc/redemption_payoff_vs_premium_refund_on_certificate
    """
    ctx = fx.setup_active_certificate(
        county_overrides={
            "name": "CA County", "state_code": "CA", "penalty_rate_bps": 500,
            "premium_bidding_enabled": False, "premium_earns_interest": False,
            "day_count_basis": 365,
        },
        parcel_overrides={"apn": "A-1", "base_tax_due_cents": 100_000},
        investor_escrow=200_000, winning_rate_bps=1200,
        issue_clock="2026-03-01T00:00:00Z",
    )
    county, cert, investor = ctx["county"], ctx["certificate"], ctx["investor"]

    fx.set_clock("2026-06-01T00:00:00Z")
    fx.add_sub_tax(county["id"], cert["id"], investor["id"], 2026, 50_000)

    fx.set_clock("2026-09-01T00:00:00Z")
    resp = api.redeem_certificate(county["id"], cert["id"], TREASURER)
    redemption = validate_success(resp, expected_status=201)
    assert_redemption(redemption)

    assert redemption["face_interest_cents"] == 6049
    assert redemption["penalty_cents"] == 5000
    assert redemption["sub_tax_interest_cents"] == 2016
    assert redemption["premium_refund_cents"] == 0
    assert redemption["total_payoff_cents"] == 163065

    cert_after = validate_success(
        api.get_certificate(county["id"], cert["id"], AUDITOR)
    )
    assert cert_after["status"] == "REDEEMED"


def test_redemption_payoff_premium_county_earns_interest(api):
    """PRD §3.9: "when `premium_earns_interest` is true it is the certificate's
    `premium_cents` plus simple interest on that premium (premium times `rate_bps`
    times the same face elapsed days, over 10,000 times `day_count_basis`, rounded
    half-up)"
    PRD §3.6: "its `rate_bps` is the awarded rate (the winning bid's rate for a
    rate-bid-down sale, or the county ceiling for a premium sale), and its
    `premium_cents` is the overbid paid (0 for rate-bid-down)."

    Design: Difficulty/dual_variant_calc/premium_refund_with_interest_on_premium_county
    """
    fx.set_clock("2026-03-01T00:00:00Z")
    county = fx.create_county(
        name="FL County", state_code="FL", max_interest_rate_bps=1600,
        penalty_rate_bps=0, premium_bidding_enabled=True,
        premium_earns_interest=True, day_count_basis=365,
    )
    parcel = fx.create_parcel(county["id"], apn="B-1", base_tax_due_cents=100_000)
    investor = fx.create_funded_investor(200_000, legal_name="HolderB", tax_id="TIN-B1")
    sale = fx.create_sale(county["id"], scheduled_at="2026-03-01T00:00:00Z",
                          sale_name="Premium Sale")
    listing = fx.create_listing(county["id"], sale["id"], parcel["id"])
    validate_success(api.open_sale(county["id"], sale["id"], TREASURER))
    listing = validate_success(
        api.get_listing(county["id"], sale["id"], listing["id"], AUDITOR)
    )
    fx.place_premium_bid(county["id"], sale["id"], listing["id"], investor["id"],
                         25_000, listing["version"])
    validate_success(api.close_sale(county["id"], sale["id"], TREASURER))
    cert = fx.get_certificate_for_parcel(county["id"], parcel["id"])

    assert cert["rate_bps"] == 1600
    assert cert["premium_cents"] == 25000

    fx.set_clock("2026-09-01T00:00:00Z")
    redemption = validate_success(
        api.redeem_certificate(county["id"], cert["id"], TREASURER),
        expected_status=201,
    )
    assert_redemption(redemption)
    assert redemption["face_interest_cents"] == 8066
    assert redemption["premium_refund_cents"] == 27016
    assert redemption["penalty_cents"] == 0
    assert redemption["total_payoff_cents"] == 135082


def test_subtax_interest_rounded_per_subtax_then_summed(api):
    """PRD §2.6: "it rounds each component — the face-interest component, each
    individual subsequent-tax interest amount, and the premium interest — to whole
    cents first, and only then adds the rounded components together."
    PRD §3.9: "and then summing those already-rounded per-sub-tax amounts in their
    posting order."

    Design: Difficulty/combinatorial_formula/subtax_interest_round_per_subtax_then_sum
    """
    ctx = fx.setup_active_certificate(
        county_overrides={
            "name": "GA County", "state_code": "GA", "penalty_rate_bps": 0,
            "day_count_basis": 365,
        },
        parcel_overrides={"apn": "G-1", "base_tax_due_cents": 100_000},
        investor_escrow=300_000, winning_rate_bps=1200,
        issue_clock="2026-03-01T00:00:00Z",
    )
    county, cert, investor = ctx["county"], ctx["certificate"], ctx["investor"]

    fx.set_clock("2026-08-31T00:00:00Z")
    fx.add_sub_tax(county["id"], cert["id"], investor["id"], 2025, 33_333)
    fx.add_sub_tax(county["id"], cert["id"], investor["id"], 2026, 33_333)

    fx.set_clock("2026-09-30T00:00:00Z")
    redemption = validate_success(
        api.redeem_certificate(county["id"], cert["id"], TREASURER),
        expected_status=201,
    )
    assert_redemption(redemption)
    assert redemption["sub_tax_payoff_cents"] == 66666
    # round-per-subtax-then-sum = 876, not sum-then-round 877
    assert redemption["sub_tax_interest_cents"] == 876
    assert redemption["face_interest_cents"] == 7003
    assert redemption["total_payoff_cents"] == 174545


def test_payoff_quote_returns_total_without_mutating(api):
    """PRD §3.9: "A non-mutating payoff quote is also available at the current
    logical-clock instant, returning `face_payoff_cents`, `face_interest_cents`,
    `penalty_cents`, `sub_tax_payoff_cents`, `sub_tax_interest_cents`,
    `premium_refund_cents`, `total_payoff_cents`, and the `as_of` instant it was
    computed at."

    Design: Corner/calculations/payoff_quote_does_not_mutate
    """
    ctx = fx.setup_active_certificate(
        county_overrides={
            "name": "QC County", "state_code": "CA", "penalty_rate_bps": 500,
        },
        parcel_overrides={"apn": "QC-1", "base_tax_due_cents": 100_000},
        investor_escrow=300_000, winning_rate_bps=1200,
        issue_clock="2026-03-01T00:00:00Z",
    )
    county, cert, investor = ctx["county"], ctx["certificate"], ctx["investor"]

    fx.set_clock("2026-06-01T00:00:00Z")
    fx.add_sub_tax(county["id"], cert["id"], investor["id"], 2026, 50_000)

    fx.set_clock("2026-09-01T00:00:00Z")
    quote = validate_success(
        api.get_payoff_quote(county["id"], cert["id"], make_investor_headers(investor["id"]))
    )
    assert quote["total_payoff_cents"] == 163065
    assert quote["sub_tax_interest_cents"] == 2016

    # The quote must not have created a redemption / changed the certificate.
    cert_after = validate_success(
        api.get_certificate(county["id"], cert["id"], AUDITOR)
    )
    assert cert_after["status"] == "ACTIVE"


def test_payoff_quote_full_day_boundary_accrual(api):
    """PRD §2.6: "redeeming exactly a whole number of days after issuance — at the
    issuance instant plus that many multiples of 86,400 seconds — yields that many
    accrual days, and redeeming one second earlier yields one fewer day."

    Design: Difficulty/boundary_precision_check/interest_accrual_full_day_boundary
    """
    ctx = fx.setup_active_certificate(
        county_overrides={
            "name": "Bnd County", "penalty_rate_bps": 0, "day_count_basis": 365,
        },
        parcel_overrides={"apn": "BND-1", "base_tax_due_cents": 100_000},
        investor_escrow=200_000, winning_rate_bps=1200,
        issue_clock="2026-03-01T00:00:00Z",
    )
    county, cert, investor = ctx["county"], ctx["certificate"], ctx["investor"]
    inv_headers = make_investor_headers(investor["id"])

    # Exactly 30 * 86400 seconds after 2026-03-01 -> 30 accrual days.
    fx.set_clock("2026-03-31T00:00:00Z")
    quote = validate_success(api.get_payoff_quote(county["id"], cert["id"], inv_headers))
    assert quote["face_interest_cents"] == 986
    assert quote["penalty_cents"] == 0
    assert quote["total_payoff_cents"] == 100986


def test_payoff_quote_one_second_before_boundary_loses_a_day(api):
    """PRD §2.6: "any partial day is discarded entirely, so day zero accrues
    nothing and accrual begins only once a full day has elapsed. Concretely,
    redeeming exactly a whole number of days after issuance — at the issuance
    instant plus that many multiples of 86,400 seconds — yields that many accrual
    days, and redeeming one second earlier yields one fewer day."

    Design: Difficulty/boundary_precision_check/interest_accrual_full_day_boundary
    """
    ctx = fx.setup_active_certificate(
        county_overrides={
            "name": "Bnd2 County", "penalty_rate_bps": 0, "day_count_basis": 365,
        },
        parcel_overrides={"apn": "BND2-1", "base_tax_due_cents": 100_000},
        investor_escrow=200_000, winning_rate_bps=1200,
        issue_clock="2026-03-01T00:00:00Z",
    )
    county, cert, investor = ctx["county"], ctx["certificate"], ctx["investor"]
    inv_headers = make_investor_headers(investor["id"])

    # One second before the 30-day mark -> 29 accrual days.
    fx.set_clock("2026-03-30T23:59:59Z")
    quote = validate_success(api.get_payoff_quote(county["id"], cert["id"], inv_headers))
    # 29 days: round(100000 * 1200 * 29 / (10000 * 365)) = round(953.42) = 953
    assert quote["face_interest_cents"] == 953
    assert quote["total_payoff_cents"] == 100953
