"""Calculations whose variant is chosen by the data rather than by the caller.

Two of them exist on this line: advance sizing branches on `funding_type`, and
covenant profitability branches on how many prior quarters the facility holds.
"""

import pytest

from test_helpers import assertions as asserts
from test_helpers import fixtures as fx


def _book_dry_and_wet_pair_on_one_line():
    """The same 50,000,000 note funded twice, once dry and once wet."""
    scenario = fx.setup_facility_panel()
    dry = fx.book_advance(
        scenario.facility["id"],
        scenario.custodian["id"],
        investor_commitment_id=scenario.commitment["id"],
        expected_facility_version=scenario.facility_version_before_booking,
        loan_amount_cents=50_000_000,
    )
    fx.file_receipt(dry["id"], scenario.custodian["id"])
    fx.verify_wire(fx.wire_for_advance(dry["id"])["id"], "CB-301")
    scenario.dry_advance = fx.fund_advance(dry["id"])

    wet = fx.book_advance(
        scenario.facility["id"],
        scenario.custodian["id"],
        investor_commitment_id=scenario.commitment["id"],
        loan_amount_cents=50_000_000,
        funding_type="WET",
    )
    fx.verify_wire(fx.wire_for_advance(wet["id"])["id"], "CB-302")
    scenario.wet_advance = fx.fund_advance(wet["id"])

    scenario.facility = fx.read_facility(scenario.facility["id"])
    scenario.commitment = fx.read_commitment(scenario.commitment["id"])
    return scenario


class TestWetVersusDryAdvanceSizing:
    def test_wet_funding_advances_strictly_less_than_dry_on_the_same_note(self):
        """The wet haircut is the whole difference between the two variants.

        PRD 3.4: "Under wet funding — permitted only when the product's
        `wet_funding_allowed` is true, and otherwise refused with
        `ERR_WET_FUNDING_NOT_ALLOWED` — stage one subtracts the `wet_haircut`
        from the base `advance_rate` and stage four adds the facility's
        wet-bucket headroom to the cap list, so the same `loan_amount_cents`
        yields a strictly smaller `advance_amount_cents` than dry funding
        would."

        Design: Difficulty/dual_variant_calc/dual_variant_wet_versus_dry_advance_sizing
        """
        scenario = _book_dry_and_wet_pair_on_one_line()
        dry, wet = scenario.dry_advance, scenario.wet_advance

        asserts.assert_advance(dry)
        asserts.assert_advance(wet)

        # A 0.98 base rate on a 50,000,000 note, floored to whole cents.
        assert dry["provisional_advance_amount_cents"] == 49_000_000
        assert dry["advance_amount_cents"] == 49_000_000
        assert dry["effective_advance_rate"] == pytest.approx(0.98, abs=1e-6)

        # The 0.02 wet haircut takes the same note to 0.96.
        assert wet["provisional_advance_amount_cents"] == 48_000_000
        assert wet["advance_amount_cents"] == 48_000_000
        assert wet["effective_advance_rate"] == pytest.approx(0.96, abs=1e-6)

        assert dry["loan_amount_cents"] == wet["loan_amount_cents"] == 50_000_000
        assert dry["advance_amount_cents"] - wet["advance_amount_cents"] == 1_000_000
        assert wet["advance_amount_cents"] < dry["advance_amount_cents"]

        # Neither advance is anywhere near the de-minimis concentration floor.
        assert dry["concentration_capped"] is False
        assert wet["concentration_capped"] is False

    def test_both_variants_roll_up_into_one_line_and_one_allocation(self):
        """Whichever variant produced them, the funded amounts aggregate alike.

        PRD 2.6: "`availability_cents` is the committed line size less the
        outstanding principal, and is never negative — a computed shortfall is
        reported as zero."

        Design: Difficulty/dual_variant_calc/dual_variant_wet_versus_dry_advance_sizing
        """
        scenario = _book_dry_and_wet_pair_on_one_line()

        assert scenario.facility["outstanding_principal_cents"] == 97_000_000
        assert scenario.facility["availability_cents"] == 19_903_000_000
        asserts.assert_availability_projection(scenario.facility)

        # Only the wet advance sits in the wet bucket.
        assert scenario.facility["wet_outstanding_cents"] == 48_000_000

        assert scenario.commitment["allocated_amount_cents"] == 97_000_000
        assert scenario.commitment["settled_amount_cents"] == 0
        assert scenario.commitment["status"] == "PARTIALLY_ALLOCATED"
        asserts.assert_commitment_capacity_conserved(scenario.commitment)

        summary = fx.read_exposure_summary(scenario.facility["id"])
        asserts.assert_both_conservation_invariants(summary)


def _certify_two_facilities_on_identical_numbers():
    """One facility with three waived priors, one with none, same certificate."""
    seasoned = fx.create_active_facility()
    fresh = fx.create_active_facility(
        facility_overrides={
            "borrower_legal_name": "Keystone Home Loans Inc",
            "settlement_account_last4": "8802",
        }
    )

    priors = []
    for period_end in ("2025-09-30", "2025-12-31", "2026-03-31"):
        prior = fx.certify_covenants(
            seasoned["id"], period_end, net_income_cents=15_000_000
        )
        priors.append(prior)
        fx.waive_covenant_test(
            prior["id"], reason="Sponsor equity injection documented"
        )

    seasoned_test = fx.certify_covenants(
        seasoned["id"], "2026-06-30", net_income_cents=30_000_000
    )
    fresh_test = fx.certify_covenants(
        fresh["id"], "2026-06-30", net_income_cents=30_000_000
    )
    return fx.Scenario(
        seasoned_facility=fx.read_facility(seasoned["id"]),
        fresh_facility=fx.read_facility(fresh["id"]),
        priors=priors,
        seasoned_test=seasoned_test,
        fresh_test=fresh_test,
    )


class TestProfitabilityVariantSelection:
    def test_three_priors_switch_the_metric_from_annualized_to_rolling(self):
        """Identical certified numbers pass on one line and breach on the other.

        PRD 3.8: "When the facility holds at least three such priors,
        `profitability_variant` is `TTM_ROLLING` and
        `profitability_metric_cents` is the certified `net_income_cents` plus
        the `net_income_cents` of the three most recent priors — a
        trailing-four-quarter sum, so weak earlier quarters can breach the
        covenant even when the quarter just certified is strong."

        Design: Difficulty/dual_variant_calc/dual_variant_ttm_rolling_versus_annualized_quarter_profitability
        """
        scenario = _certify_two_facilities_on_identical_numbers()

        # The very first prior had no history of its own to lean on.
        first_prior = scenario.priors[0]
        assert first_prior["profitability_variant"] == "ANNUALIZED_QUARTER"
        assert first_prior["profitability_metric_cents"] == 60_000_000

        seasoned = scenario.seasoned_test
        asserts.assert_covenant_test(seasoned)
        assert seasoned["profitability_variant"] == "TTM_ROLLING"
        # 30,000,000 certified plus three waived priors of 15,000,000 each.
        assert seasoned["profitability_metric_cents"] == 75_000_000
        assert seasoned["breach_codes"] == ["PROFITABILITY"]
        assert seasoned["status"] == "BREACH"

        fresh = scenario.fresh_test
        asserts.assert_covenant_test(fresh)
        assert fresh["profitability_variant"] == "ANNUALIZED_QUARTER"
        # The same 30,000,000, multiplied by four instead.
        assert fresh["profitability_metric_cents"] == 120_000_000
        assert fresh["breach_codes"] == []
        assert fresh["status"] == "PASS"

    def test_only_the_breaching_line_is_restricted_and_counted(self):
        """A breach on one facility leaves its twin entirely untouched.

        PRD 3.8: "A breaching test increases it, moves an `ACTIVE` facility to
        `RESTRICTED`, and issues a facility-level margin call with
        `trigger_reason` of `COVENANT_BREACH` sized at one tenth of
        `outstanding_principal_cents` — skipped silently when that amount works
        out to zero."

        Design: Difficulty/dual_variant_calc/dual_variant_ttm_rolling_versus_annualized_quarter_profitability
        """
        scenario = _certify_two_facilities_on_identical_numbers()

        seasoned = scenario.seasoned_facility
        assert seasoned["status"] == "RESTRICTED"
        assert seasoned["last_covenant_status"] == "BREACH"
        # Each waived prior reset the counter, so this breach is the first.
        assert seasoned["consecutive_breach_count"] == 1

        fresh = scenario.fresh_facility
        assert fresh["status"] == "ACTIVE"
        assert fresh["last_covenant_status"] == "PASS"
        assert fresh["consecutive_breach_count"] == 0

        # Nothing is drawn on either line, so the covenant call sizes to zero
        # and is skipped rather than created.
        assert seasoned["outstanding_principal_cents"] == 0
        assert seasoned["open_margin_call_count"] == 0
        assert fx.facility_margin_calls(seasoned["id"]) == []
