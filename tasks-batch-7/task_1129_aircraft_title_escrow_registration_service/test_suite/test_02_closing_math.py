"""Closing math: dual-variant proration, tiered escrow fee with floor /
surcharge / cap, pinned evaluation order, and the closing-statement read."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_escrow_file,
    assert_statement,
    create_aircraft,
    create_buyer_seller,
    create_escrow_file_payload,
    get_statement,
    validate_success,
)

OFFICER = TEST_USERS["officer_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def _create_file(api, *, purchase_price_cents, annual_fee, method, close_date,
                 requires_trust=None, n_number):
    aircraft = validate_success(
        api.create_aircraft(
            {
                "n_number": n_number,
                "serial_number": f"SN-{n_number}",
                "make_model": "Cessna 560XL",
                "year": 2015,
            },
            OFFICER,
        ),
        201,
    )
    buyer, seller = create_buyer_seller()
    payload = create_escrow_file_payload(
        aircraft_id=aircraft["id"],
        buyer_party_id=buyer["id"],
        seller_party_id=seller["id"],
        purchase_price_cents=purchase_price_cents,
        annual_registration_fee_cents=annual_fee,
        proration_method=method,
        expected_close_date=close_date,
    )
    if requires_trust is not None:
        payload["requires_trust"] = requires_trust
    return validate_success(api.create_escrow_file(payload, OFFICER), 201)


class TestProrationDualVariant:
    def test_daily_variant_whole_days_fraction(self, api):
        """PRD §3.2.1: "Under the `DAILY` variant, count the whole days strictly
        after `expected_close_date` through December 31 of the same calendar year,
        inclusive of December 31."
        PRD §3.2.1: "The proration is the annual fee multiplied by that day count
        and divided by 365, rounded half-up to the nearest cent in a single final
        rounding."

        184 days follow 2026-06-30 through Dec 31; 100001 * 184 / 365 = 50411.46...
        rounds to 50411 in the single final rounding.

        Design: Difficulty/dual_variant_calc/d1_proration_daily_vs_monthly
        """
        escrow_file = _create_file(
            api, purchase_price_cents=1_000_000, annual_fee=100_001,
            method="DAILY", close_date="2026-06-30", n_number="N100DA",
        )
        assert_escrow_file(escrow_file)
        assert escrow_file["proration_amount_cents"] == 50_411

    def test_monthly_variant_per_month_rounding_then_sum(self, api):
        """PRD §3.2.1: "Under the `MONTHLY` variant, count the calendar months
        strictly after the month containing `expected_close_date` through
        December — call that count the full months."
        PRD §3.2.1: "Each full month contributes the annual fee divided by 12,
        rounded half-up to the nearest cent."
        PRD §3.2.1: "The proration is the sum of those per-month and half-month
        roundings — never the other way around."

        6 full months x round_half_up(100001/12)=8333 -> 49998; close day 30 is
        after the 15th, so no half-month credit. Diverges from the DAILY value
        on identical inputs.

        Design: Difficulty/dual_variant_calc/d1_proration_daily_vs_monthly
        """
        monthly = _create_file(
            api, purchase_price_cents=1_000_000, annual_fee=100_001,
            method="MONTHLY", close_date="2026-06-30", n_number="N100MA",
        )
        assert monthly["proration_amount_cents"] == 49_998

        daily = _create_file(
            api, purchase_price_cents=1_000_000, annual_fee=100_001,
            method="DAILY", close_date="2026-06-30", n_number="N100DB",
        )
        assert daily["proration_amount_cents"] != monthly["proration_amount_cents"]


class TestEscrowFeeSchedule:
    def test_tiered_fee_three_tiers_summed(self, api):
        """PRD §3.2.2: "The first tier covers the portion of the base up to and
        including $500,000 (that is, 50,000,000 cents) and is charged at 30 basis
        points."
        PRD §3.2.2: "The second tier covers the portion of the base strictly above
        $500,000 and up to and including $2,000,000 (that is, 200,000,000 cents)
        and is charged at 20 basis points."
        PRD §3.2.2: "The third tier covers any portion of the base strictly above
        $2,000,000 and is charged at 10 basis points."
        PRD §3.2.2: "Each tier's amount is rounded half-up to the nearest cent
        independently, and the three rounded tier amounts are then summed."

        Base 250,000,000 -> 150,000 + 300,000 + 50,000 = 500,000.

        Design: Difficulty/combinatorial_formula/c1_escrow_fee_tiered_with_trust_surcharge
        """
        escrow_file = _create_file(
            api, purchase_price_cents=250_000_000, annual_fee=0,
            method="DAILY", close_date="2026-06-30", n_number="N310FA",
        )
        statement = get_statement(escrow_file["id"])
        assert_statement(statement)
        assert statement["escrow_fee_cents"] == 500_000

    def test_trust_surcharge_added_inside_cap(self, api):
        """PRD §3.2.2: "If the file's `requires_trust` is `true`, a flat trust
        surcharge of $750 (75,000 cents) is added."
        PRD §3.2: "a file whose `requires_trust` is `true` and for which no
        `ACCEPTED` trust covers the aircraft on the open date will be born
        `TRUST_BLOCKED`, and the converse for lien discovery."

        500,000 + 75,000 surcharge = 575,000 (below the cap); the trust leg of
        posture still applies even though the fee is computed and frozen.

        Design: Difficulty/combinatorial_formula/c1_escrow_fee_tiered_with_trust_surcharge
        """
        escrow_file = _create_file(
            api, purchase_price_cents=250_000_000, annual_fee=0,
            method="DAILY", close_date="2026-06-30", requires_trust=True,
            n_number="N310FB",
        )
        statement = get_statement(escrow_file["id"])
        assert statement["escrow_fee_cents"] == 575_000
        assert escrow_file["posture"] == "TRUST_BLOCKED"

    def test_fee_base_includes_proration_pinned_order(self, api):
        """PRD §2.8: "The evaluation order is pinned — proration first, then the
        fee computed against the sum of `purchase_price_cents` and the just-frozen
        proration — so that the fee base itself never includes the fee."

        Base 250,060,493 -> tier3 round_half_up(50,060,493 x 0.001) = 50,060, so
        fee = 150,000 + 300,000 + 50,060 = 500,060 — not the 500,000 that a
        price-only base would yield.

        Design: Difficulty/combinatorial_formula/c2_statement_evaluation_order_pin
        """
        escrow_file = _create_file(
            api, purchase_price_cents=250_000_000, annual_fee=120_000,
            method="DAILY", close_date="2026-06-30", n_number="N320EO",
        )
        statement = get_statement(escrow_file["id"])
        assert statement["proration_amount_cents"] == 60_493
        assert statement["escrow_fee_cents"] == 500_060
        assert statement["escrow_fee_cents"] != 500_000

    def test_buyer_amount_due_is_sum_of_frozen_components(self, api):
        """PRD §2.8: "The buyer's `buyer_amount_due_cents` is frozen alongside
        them as `purchase_price_cents + proration_amount_cents +
        escrow_fee_cents`."

        250,000,000 + 60,493 + 500,060 = 250,560,553.

        Design: Difficulty/combinatorial_formula/c2_statement_evaluation_order_pin
        """
        escrow_file = _create_file(
            api, purchase_price_cents=250_000_000, annual_fee=120_000,
            method="DAILY", close_date="2026-06-30", n_number="N320EP",
        )
        statement = get_statement(escrow_file["id"])
        assert statement["buyer_amount_due_cents"] == 250_560_553
        assert (
            statement["buyer_amount_due_cents"]
            == statement["purchase_price_cents"]
            + statement["proration_amount_cents"]
            + statement["escrow_fee_cents"]
        )

    def test_minimum_fee_floor_applies(self, api):
        """PRD §3.2.2: "The summed figure is then floored at a minimum fee of
        $1,500 (150,000 cents)."

        Base 1,000,000 -> raw tier1 = 3,000, lifted to the 150,000 floor;
        due = 1,000,000 + 0 + 150,000 = 1,150,000.

        Design: Corner/calculations/c_fee_minimum_floor_applies
        """
        escrow_file = _create_file(
            api, purchase_price_cents=1_000_000, annual_fee=0,
            method="DAILY", close_date="2026-06-30", n_number="N130MF",
        )
        statement = get_statement(escrow_file["id"])
        assert statement["escrow_fee_cents"] == 150_000
        assert statement["buyer_amount_due_cents"] == 1_150_000

    def test_fee_cap_applies(self, api):
        """PRD §3.2.2: "The result is capped at a maximum fee of $25,000
        (2,500,000 cents)."

        Base 3,000,000,000 -> tier sum 150,000 + 300,000 + 2,800,000 = 3,250,000,
        clamped to the 2,500,000 cap.

        Design: Corner/calculations/c_fee_cap_applies
        """
        escrow_file = _create_file(
            api, purchase_price_cents=3_000_000_000, annual_fee=0,
            method="DAILY", close_date="2026-06-30", n_number="N131FC",
        )
        statement = get_statement(escrow_file["id"])
        assert statement["escrow_fee_cents"] == 2_500_000

    def test_monthly_partial_month_day15_boundary(self, api):
        """PRD §3.2.1: "If the day of the month of `expected_close_date` is on or
        before the 15th, the closing month also contributes a half-month credit of
        the annual fee divided by 24, rounded half-up to the nearest cent."

        Close on the 15th: 6 x 10,000 + 5,000 half month = 65,000.
        Close on the 16th: 6 x 10,000 = 60,000, no half month.

        Design: Corner/calculations/c_proration_partial_month_boundary
        """
        on_15th = _create_file(
            api, purchase_price_cents=2_000_000, annual_fee=120_000,
            method="MONTHLY", close_date="2026-06-15", n_number="N132P1",
        )
        on_16th = _create_file(
            api, purchase_price_cents=2_000_000, annual_fee=120_000,
            method="MONTHLY", close_date="2026-06-16", n_number="N132P2",
        )
        assert on_15th["proration_amount_cents"] == 65_000
        assert on_16th["proration_amount_cents"] == 60_000


class TestClosingStatementRead:
    def test_statement_field_set_and_values_on_fresh_file(self, api, auditor_headers):
        """PRD §3.6: "The closing-statement read returns this live figure
        alongside the frozen components."
        PRD §2.8: "Three further figures — `total_funded_cents`,
        `escrow_balance_cents`, and `seller_net_proceeds_cents` — remain live for
        the life of the file and are recomputed on every deposit create or return
        and on every disbursement release or void."
        PRD §3.6: "The seller's net figure is `purchase_price_cents +
        proration_amount_cents - escrow_fee_cents`, minus the sum of `RELEASED`
        disbursements whose purpose is `LIEN_PAYOFF`, minus the sum of `RELEASED`
        disbursements whose purpose is `TAX_REMITTANCE`."

        Fresh file, price 10,000,000 / annual 0: fee floored at 150,000, due
        10,150,000, funded 0, balance 0, seller net 9,850,000.

        Design: Corner/endpoints/ep_statement_read_fields
        """
        escrow_file = _create_file(
            api, purchase_price_cents=10_000_000, annual_fee=0,
            method="DAILY", close_date="2026-06-30", n_number="N150ST",
        )
        res = api.get_escrow_file_statement(escrow_file["id"], auditor_headers)
        statement = validate_success(res, 200)
        assert_statement(statement)
        assert statement["purchase_price_cents"] == 10_000_000
        assert statement["proration_amount_cents"] == 0
        assert statement["escrow_fee_cents"] == 150_000
        assert statement["buyer_amount_due_cents"] == 10_150_000
        assert statement["total_funded_cents"] == 0
        assert statement["escrow_balance_cents"] == 0
        assert statement["seller_net_proceeds_cents"] == 9_850_000
