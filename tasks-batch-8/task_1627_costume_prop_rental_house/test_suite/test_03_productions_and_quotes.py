"""Production confirmation gates and reservation pricing (rate variants, tiers)."""
from test_helpers import (
    ApiErrorId,
    acquire_unit,
    create_active_renter,
    create_catalog_item,
    create_confirmed_production,
    create_production_draft,
    get_production,
    make_renter_contact_headers,
    place_reservation,
    publish_rate_card,
    register_renter,
    decide_certificate,
    submit_certificate,
    validate_error,
    validate_success,
)


def _quote(api, production_id, renter, item_id, start="2026-09-01", end="2026-09-10"):
    """Place a qty-1 reservation and return it (reads rate_variant + quoted_charge_cents)."""
    return place_reservation(
        api, production_id, renter, item_id, quantity=1,
        window_start_date=start, window_end_date=end,
    )


class TestProductionConfirmGates:
    def test_error_rate_card_required_at_confirm(self, api, house_admin_headers):
        """PRD §3.3: "It enforces, in validation order: the renter is `ACTIVE"
        (`ERR_RENTER_SUSPENDED`); ... a rate card in `PUBLISHED` status exists
        (`ERR_RATE_CARD_REQUIRED`)".

        Design: Corner/errors/error_rate_card_required_at_confirm
        """
        renter = create_active_renter(api, name="R")["renter"]
        production = create_production_draft(api, renter, title="P", closing_date="2026-09-20")
        # No rate card has ever been published in this fresh database.
        resp = api.confirm_production(
            production["id"], make_renter_contact_headers(renter["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_RATE_CARD_REQUIRED, 409)
        assert get_production(api, production["id"])["status"] == "DRAFT"

    def test_error_insurance_not_verified_at_confirm(self, api):
        """PRD §3.3: "the renter holds a certificate in `VERIFIED` status whose `expiry_date`
        is on or after the production's `return_by_date` (`ERR_INSURANCE_NOT_VERIFIED`)" and
        "The `return_by_date` is the `closing_date` plus a three-day strike allowance."

        Design: Corner/errors/error_insurance_not_verified_at_confirm
        """
        publish_rate_card(api)
        renter = register_renter(api, name="R")
        # Cert expires 2026-09-01; production return_by_date is 2026-09-23 (closing +3).
        cert = submit_certificate(
            api, renter["id"], coverage_cents=100000, expiry_date="2026-09-01",
        )
        decide_certificate(api, cert["id"], decision="VERIFIED")
        production = create_production_draft(api, renter, title="P", closing_date="2026-09-20")

        resp = api.confirm_production(
            production["id"], make_renter_contact_headers(renter["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INSURANCE_NOT_VERIFIED, 422)
        assert get_production(api, production["id"])["status"] == "DRAFT"


class TestRateVariants:
    def test_daily_variant_quote_five_day_window(self, api):
        """PRD §3.4: "If the production's pinned `long_run` flag is true, the variant is
        `LONG_RUN`; otherwise, if the window spans at least seven days the variant is
        `WEEKLY`, else `DAILY`." and "`DAILY`: the charge is the `quantity` times the item's
        `base_daily_rate_cents` times the number of window days."

        Design: Corner/calculations/daily_variant_quote_five_day_window
        """
        publish_rate_card(api)
        item = create_catalog_item(api, name="I1")
        acquire_unit(api, item["id"], barcode="BC-Q1")
        renter = create_active_renter(api, name="R")["renter"]
        production = create_confirmed_production(api, renter, closing_date="2026-09-20")

        reservation = _quote(api, production["id"], renter, item["id"],
                             start="2026-09-01", end="2026-09-05")
        assert reservation["rate_variant"] == "DAILY"
        assert reservation["quoted_charge_cents"] == 5000  # 1 * 1000 * 5 days

    def test_weekly_variant_for_short_run_production(self, api):
        """PRD §3.4: "otherwise, if the window spans at least seven days the variant is
        `WEEKLY`" and "`WEEKLY`: the charge is the `quantity` times the item's
        `base_weekly_rate_cents` times the number of whole weeks the window spans, rounding
        the day count up to a whole week — a window of eight days bills two weeks."
        PRD §3.3: "The `long_run` flag is true when `run_weeks` is at least the pinned card's
        `long_run_threshold_weeks`".

        Design: Difficulty/dual_variant_calc/rental_rate_long_run_vs_weekly
        """
        publish_rate_card(api)
        item = create_catalog_item(api, name="Flapper dress", period="TWENTIES",
                                   size_class="S", alteration_policy="REVERSIBLE_ONLY",
                                   replacement_value_cents=80000)
        acquire_unit(api, item["id"], barcode="BC-101")
        acquire_unit(api, item["id"], barcode="BC-102")
        renter = create_active_renter(api, name="Renter R")["renter"]
        # 20-day run -> run_weeks 2 < 8 -> long_run false.
        production = create_confirmed_production(api, renter, title="Short Run",
                                                 closing_date="2026-09-20")
        assert production["long_run"] is False

        reservation = _quote(api, production["id"], renter, item["id"])
        assert reservation["rate_variant"] == "WEEKLY"
        # 10 days -> ceil(10/7) = 2 weeks -> 1 * 5000 * 2.
        assert reservation["quoted_charge_cents"] == 10000

    def test_long_run_variant_for_long_run_production(self, api):
        """PRD §3.4: "If the production's pinned `long_run` flag is true, the variant is
        `LONG_RUN`" and "`LONG_RUN`: weekly pricing as above, then discounted: the discount
        fraction is the pinned card's `deep_run_discount_pct` when the production's
        `run_weeks` is at least the card's `deep_run_threshold_weeks`, and the card's
        `long_run_discount_pct` otherwise".

        Design: Difficulty/dual_variant_calc/rental_rate_long_run_vs_weekly
        """
        publish_rate_card(api)
        item = create_catalog_item(api, name="Flapper dress", period="TWENTIES",
                                   size_class="S", alteration_policy="REVERSIBLE_ONLY",
                                   replacement_value_cents=80000)
        acquire_unit(api, item["id"], barcode="BC-101")
        acquire_unit(api, item["id"], barcode="BC-102")
        renter = create_active_renter(api, name="Renter R")["renter"]
        # 56-day run (Sep 1 .. Oct 26) -> run_weeks 8 >= threshold 8 -> long_run true.
        production = create_confirmed_production(api, renter, title="Long Run",
                                                 closing_date="2026-10-26")
        assert production["long_run"] is True

        reservation = _quote(api, production["id"], renter, item["id"])
        assert reservation["rate_variant"] == "LONG_RUN"
        # 2 weeks * 5000 * (1 - 0.20) = 8000 — same window prices lower than WEEKLY.
        assert reservation["quoted_charge_cents"] == 8000


class TestThreeTierStacking:
    def _setup(self, api):
        publish_rate_card(api)
        item = create_catalog_item(api, name="Tailcoat")
        for bc in ("BC-201", "BC-202", "BC-203"):
            acquire_unit(api, item["id"], barcode=bc)
        renter = create_active_renter(api, name="Renter R")["renter"]
        return item, renter

    def test_weekly_vs_long_run_tiers(self, api):
        """PRD §3.4: "`WEEKLY`: the charge is the `quantity` times the item's
        `base_weekly_rate_cents` times the number of whole weeks the window spans" and
        "`LONG_RUN`: weekly pricing as above, then discounted ... the weekly charge is
        multiplied by one minus the discount."

        Design: Difficulty/combinatorial_formula/rental_quote_three_tier_stacking
        """
        item, renter = self._setup(api)
        p2 = create_confirmed_production(api, renter, title="P2", closing_date="2026-09-20")
        p8 = create_confirmed_production(api, renter, title="P8", closing_date="2026-10-26")

        r2 = _quote(api, p2["id"], renter, item["id"])
        r8 = _quote(api, p8["id"], renter, item["id"])
        assert (r2["rate_variant"], r2["quoted_charge_cents"]) == ("WEEKLY", 10000)
        assert (r8["rate_variant"], r8["quoted_charge_cents"]) == ("LONG_RUN", 8000)

    def test_deep_run_tier(self, api):
        """PRD §3.4: "the discount fraction is the pinned card's `deep_run_discount_pct` when
        the production's `run_weeks` is at least the card's `deep_run_threshold_weeks`, and
        the card's `long_run_discount_pct` otherwise".

        Design: Difficulty/combinatorial_formula/rental_quote_three_tier_stacking
        """
        item, renter = self._setup(api)
        # 112-day run (Sep 1 .. Dec 21) -> run_weeks 16 >= deep threshold 16.
        p16 = create_confirmed_production(api, renter, title="P16", closing_date="2026-12-21")
        assert p16["run_weeks"] == 16

        r16 = _quote(api, p16["id"], renter, item["id"])
        assert r16["rate_variant"] == "LONG_RUN"
        # 2 weeks * 5000 * (1 - 0.30) = 7000 — the deep tier undercuts plain long-run.
        assert r16["quoted_charge_cents"] == 7000


class TestLongRunThresholdBoundary:
    def _setup(self, api, closing_date, title):
        publish_rate_card(api)
        item = create_catalog_item(api, name="Tailcoat")
        acquire_unit(api, item["id"], barcode=f"BC-{title}-1")
        acquire_unit(api, item["id"], barcode=f"BC-{title}-2")
        renter = create_active_renter(api, name="Renter R")["renter"]
        production = create_confirmed_production(api, renter, title=title,
                                                 closing_date=closing_date)
        return item, renter, production

    def test_55_day_run_not_long_run(self, api):
        """PRD §3.3: "The `run_weeks` is the whole number of weeks in the run: the count of
        calendar days from `performance_start_date` through `closing_date` inclusive, divided
        by seven, rounded down — so a 55-day run yields 7 and a 56-day run yields 8. The
        `long_run` flag is true when `run_weeks` is at least the pinned card's
        `long_run_threshold_weeks` — a run exactly at the threshold qualifies."

        Design: Difficulty/boundary_precision_check/long_run_threshold_exact_weeks
        """
        item, renter, production = self._setup(api, "2026-10-25", "P55")
        assert production["run_weeks"] == 7
        assert production["long_run"] is False

        reservation = _quote(api, production["id"], renter, item["id"])
        assert reservation["rate_variant"] == "WEEKLY"
        assert reservation["quoted_charge_cents"] == 10000

    def test_56_day_run_is_long_run(self, api):
        """PRD §3.3: "The `run_weeks` is the whole number of weeks in the run: the count of
        calendar days from `performance_start_date` through `closing_date` inclusive, divided
        by seven, rounded down — so a 55-day run yields 7 and a 56-day run yields 8. The
        `long_run` flag is true when `run_weeks` is at least the pinned card's
        `long_run_threshold_weeks` — a run exactly at the threshold qualifies."

        Design: Difficulty/boundary_precision_check/long_run_threshold_exact_weeks
        """
        item, renter, production = self._setup(api, "2026-10-26", "P56")
        assert production["run_weeks"] == 8
        assert production["long_run"] is True

        reservation = _quote(api, production["id"], renter, item["id"])
        assert reservation["rate_variant"] == "LONG_RUN"
        # One closing day later flips the tier: 2 * 5000 * (1 - 0.20).
        assert reservation["quoted_charge_cents"] == 8000


class TestRateCardSupersession:
    def test_rate_card_supersession_keeps_pinned_quote(self, api, house_admin_headers):
        """PRD §3.3: "A new card is born `PUBLISHED`; publishing it automatically moves the
        previously `PUBLISHED` card to `SUPERSEDED`. Productions already confirmed keep their
        pinned card and are never re-priced — supersession affects only future confirmations."
        and "every downstream charge for the production reads thresholds, discounts, and the
        late-fee percentage from that pinned card, never from whatever card is currently
        published."

        Design: Corner/calculations/rate_card_supersession_keeps_pinned_quote
        """
        rc1 = publish_rate_card(api, name="RC-1")
        item = create_catalog_item(api, name="I1")
        acquire_unit(api, item["id"], barcode="BC-RC1")
        renter = create_active_renter(api, name="R")["renter"]
        production = create_confirmed_production(api, renter, closing_date="2026-10-26")
        assert production["rate_card_id"] == rc1["id"]
        assert production["rate_card_version"] == rc1["version"]
        assert production["long_run"] is True

        # Supersede with a card whose threshold (99) would make this run short.
        rc2 = publish_rate_card(
            api, name="RC-2", long_run_threshold_weeks=99, long_run_discount_pct=0.05,
            deep_run_threshold_weeks=199, deep_run_discount_pct=0.10, late_fee_daily_pct=0.50,
        )
        rc1_after = validate_success(api.get_rate_card(rc1["id"], house_admin_headers))
        assert rc1_after["status"] == "SUPERSEDED"
        rc2_after = validate_success(api.get_rate_card(rc2["id"], house_admin_headers))
        assert rc2_after["status"] == "PUBLISHED"

        # The confirmed production still prices from the pinned RC1.
        reservation = _quote(api, production["id"], renter, item["id"],
                             start="2026-09-11", end="2026-09-20")
        assert reservation["rate_variant"] == "LONG_RUN"
        assert reservation["quoted_charge_cents"] == 8000
