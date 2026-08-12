"""Visit pricing: provisional vs final variants, tiered composition, overtime
block rounding, seasonal wrap windows."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    create_household, create_coop, create_visit, create_window,
    assign_visit, check_in_visit, complete_visit,
    setup_household_with_installed_coop, create_seasonal_window_payload,
)

ADMIN = TEST_USERS["platform_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]

_BASE_SENTENCE = (
    "The base component takes the visit type's list rate — 8000 cents for a "
    "cleaning, 6000 for a health check, 12000 for predator proofing, 25000 for "
    "a setup install — multiplies it by the household zone's multiplier (1.0 "
    "for `URBAN`, 1.15 for `SUBURBAN`, 1.30 for `RURAL`), then multiplies by "
    "one plus the `visit_surcharge_pct` of the seasonal window covering the "
    "scheduled date in that zone (one plus zero when no window covers it), and "
    "rounds the result half up to whole cents, once."
)
_FLOCK_SENTENCE = (
    "The flock-tier fee looks at the coop's declared `coop_capacity_hens`: "
    "nothing for a flock of six or fewer, 1500 cents for seven to twelve hens, "
    "3000 cents for thirteen to twenty, and for larger flocks 3000 cents plus a "
    "further 250 cents for every hen beyond twenty."
)


class TestProvisionalVsFinalPrice:
    def test_provisional_price_uses_declared_capacity(self, api):
        """PRD §3.5: "The provisional quote is built from a base component plus
        a flock-tier fee. The base component takes the visit type's list rate —
        8000 cents for a cleaning, 6000 for a health check, 12000 for predator
        proofing, 25000 for a setup install — multiplies it by the household
        zone's multiplier (1.0 for `URBAN`, 1.15 for `SUBURBAN`, 1.30 for
        `RURAL`), then multiplies by one plus the `visit_surcharge_pct` of the
        seasonal window covering the scheduled date in that zone (one plus zero
        when no window covers it), and rounds the result half up to whole
        cents, once. The flock-tier fee looks at the coop's declared
        `coop_capacity_hens`: nothing for a flock of six or fewer, 1500 cents
        for seven to twelve hens, 3000 cents for thirteen to twenty, and for
        larger flocks 3000 cents plus a further 250 cents for every hen beyond
        twenty. The provisional price is the sum of the two parts."

        Design: Difficulty/dual_variant_calc/visit_provisional_vs_final_price_divergence
        """
        household = create_household(name="H Prov", address="1 Hen Ln")
        coop = create_coop(household, 8, site_label="north")
        visit = create_visit(household, coop, "SETUP_INSTALL",
                             "2026-06-10T09:00:00Z", "2026-06-10T11:00:00Z")

        # 25000 * 1.0 (URBAN) * 1.0 (no window) + tier(8) = 1500
        assert visit["provisional_price_cents"] == 26500
        assert visit["final_price_cents"] is None, "final price stays null until completion"

    def test_final_price_retiers_on_observed_flock_and_diverges(self, api):
        """PRD §3.5: "Completion stamps `completed_at` with the logical clock
        and computes `final_price_cents`: the same base-component formula as the
        provisional quote, but evaluated against the seasonal window covering
        the **completion** date; a flock-tier fee computed from the **observed**
        flock size rather than declared capacity, using the same tier
        boundaries; and an overtime charge of 700 cents for every started
        15-minute block by which `actual_duration_minutes` exceeds the type's
        standard duration — 60 minutes for a cleaning, 45 for a health check,
        90 for predator proofing, 180 for a setup install — with any partial
        block counting as a full started block."
        PRD §3.5: "The final price is the sum of base, flock fee, and overtime,
        and identical scheduled inputs can legitimately yield a final price
        different from the provisional one whenever completion lands in a
        different seasonal window or the observed flock falls in a different
        tier."
        PRD §3.4: "When a `SETUP_INSTALL` visit completes, the coop moves from
        `PLANNED` to `INSTALLED`."

        Design: Difficulty/dual_variant_calc/visit_provisional_vs_final_price_divergence
        """
        household = create_household(name="H Prov", address="1 Hen Ln")
        coop = create_coop(household, 8, site_label="north")
        visit = create_visit(household, coop, "SETUP_INSTALL",
                             "2026-06-10T09:00:00Z", "2026-06-10T11:00:00Z")
        assign_visit(visit["id"], "tech-1")
        check_in_visit(visit["id"], "tech-1")
        completed = complete_visit(visit["id"], "tech-1",
                                   observed_flock_size=21, actual_duration_minutes=180)

        # base 25000 + tier(21) = 3000 + 250*(21-20) = 3250, 180 min == standard -> 0 overtime
        assert completed["final_price_cents"] == 28250
        assert completed["final_price_cents"] != completed["provisional_price_cents"] == 26500

        coop_after = validate_success(api.get_coop_site(coop["id"], DISPATCHER), 200)
        assert coop_after["status"] == "INSTALLED"


class TestTieredMultiInputPricing:
    def test_zone_window_and_tier_compose_on_covered_date(self, api):
        """PRD §3.5 (base): "The base component takes the visit type's list
        rate — 8000 cents for a cleaning, 6000 for a health check, 12000 for
        predator proofing, 25000 for a setup install — multiplies it by the
        household zone's multiplier (1.0 for `URBAN`, 1.15 for `SUBURBAN`, 1.30
        for `RURAL`), then multiplies by one plus the `visit_surcharge_pct` of
        the seasonal window covering the scheduled date in that zone (one plus
        zero when no window covers it), and rounds the result half up to whole
        cents, once."
        PRD §3.5 (tier): "The flock-tier fee looks at the coop's declared
        `coop_capacity_hens`: nothing for a flock of six or fewer, 1500 cents
        for seven to twelve hens, 3000 cents for thirteen to twenty, and for
        larger flocks 3000 cents plus a further 250 cents for every hen beyond
        twenty."
        PRD §3.2: "Coverage is wrap-aware and inclusive at both bounds: a
        non-wrapping window covers a date when the date's MM-DD string falls
        between the two bounds inclusively; a wrapping window covers it when
        the MM-DD is at or after `start_md` or at or before `end_md`."

        Design: Difficulty/combinatorial_formula/visit_price_tiered_multi_input
        """
        create_window(window_code="WINTER_PEAK", zone_code="RURAL",
                      start_md="11-15", end_md="02-15",
                      visit_surcharge_pct=0.25, sitting_surcharge_pct=0.20)
        household = create_household(zone_code="RURAL", name="H Rural", address="9 Range Rd")
        coop = create_coop(household, 25, site_label="big")
        install_coop_visit = create_visit(household, coop, "SETUP_INSTALL",
                                          "2026-06-01T09:00:00Z", "2026-06-01T12:00:00Z")
        assign_visit(install_coop_visit["id"], "tech-1")
        check_in_visit(install_coop_visit["id"], "tech-1")
        complete_visit(install_coop_visit["id"], "tech-1",
                       observed_flock_size=25, actual_duration_minutes=180)

        visit = create_visit(household, coop, "COOP_CLEANING",
                             "2026-12-20T09:00:00Z", "2026-12-20T10:00:00Z")
        # 12-20 is inside the wrap window (>= 11-15): round_half_up(8000*1.30*1.25) = 13000
        # flock tier for 25 hens: 3000 + 250*5 = 4250
        assert visit["provisional_price_cents"] == 17250
        assert visit["coverage"] == "BILLABLE", "no subscription -> never covered"
        assert visit["status"] == "REQUESTED"

    def test_same_inputs_outside_window_drop_the_surcharge(self, api):
        """PRD §3.5: "The base component takes the visit type's list rate —
        8000 cents for a cleaning, 6000 for a health check, 12000 for predator
        proofing, 25000 for a setup install — multiplies it by the household
        zone's multiplier (1.0 for `URBAN`, 1.15 for `SUBURBAN`, 1.30 for
        `RURAL`), then multiplies by one plus the `visit_surcharge_pct` of the
        seasonal window covering the scheduled date in that zone (one plus zero
        when no window covers it), and rounds the result half up to whole
        cents, once."
        PRD §3.3: "Visits of type `PREDATOR_PROOFING` or `SETUP_INSTALL` are
        never covered, and neither is any visit scheduled outside the current
        period."

        Design: Difficulty/combinatorial_formula/visit_price_tiered_multi_input
        """
        create_window(window_code="WINTER_PEAK", zone_code="RURAL",
                      start_md="11-15", end_md="02-15",
                      visit_surcharge_pct=0.25, sitting_surcharge_pct=0.20)
        household = create_household(zone_code="RURAL", name="H Rural", address="9 Range Rd")
        coop = create_coop(household, 25, site_label="big")
        install = create_visit(household, coop, "SETUP_INSTALL",
                               "2026-06-01T09:00:00Z", "2026-06-01T12:00:00Z")
        assign_visit(install["id"], "tech-1")
        check_in_visit(install["id"], "tech-1")
        complete_visit(install["id"], "tech-1",
                       observed_flock_size=25, actual_duration_minutes=180)

        visit = create_visit(household, coop, "COOP_CLEANING",
                             "2026-06-05T09:00:00Z", "2026-06-05T10:00:00Z")
        # 06-05 outside the wrap window: round_half_up(8000*1.30*1.0) = 10400 + 4250
        assert visit["provisional_price_cents"] == 14650
        assert visit["coverage"] == "BILLABLE"


class TestOvertimeBlocks:
    def test_overtime_bills_every_started_fifteen_minute_block(self, api):
        """PRD §3.5: "Completion stamps `completed_at` with the logical clock
        and computes `final_price_cents`: the same base-component formula as
        the provisional quote, but evaluated against the seasonal window
        covering the **completion** date; a flock-tier fee computed from the
        **observed** flock size rather than declared capacity, using the same
        tier boundaries; and an overtime charge of 700 cents for every started
        15-minute block by which `actual_duration_minutes` exceeds the type's
        standard duration — 60 minutes for a cleaning, 45 for a health check,
        90 for predator proofing, 180 for a setup install — with any partial
        block counting as a full started block."

        Design: Corner/calculations/visit_overtime_started_block_rounding
        """
        household = create_household(name="H OT", address="34 Hen Ln")
        coop = create_coop(household, 4)
        install = create_visit(household, coop, "SETUP_INSTALL",
                               "2026-06-01T09:00:00Z", "2026-06-01T12:00:00Z")
        assign_visit(install["id"], "tech-1")
        check_in_visit(install["id"], "tech-1")
        install_done = complete_visit(install["id"], "tech-1",
                                      observed_flock_size=4, actual_duration_minutes=195)
        # 15 over 180 -> exactly 1 block: 25000 + 0 + 700
        assert install_done["final_price_cents"] == 25700

        cleaning = create_visit(household, coop, "COOP_CLEANING",
                                "2026-06-02T09:00:00Z", "2026-06-02T10:00:00Z")
        assign_visit(cleaning["id"], "tech-1")
        check_in_visit(cleaning["id"], "tech-1")
        cleaning_done = complete_visit(cleaning["id"], "tech-1",
                                       observed_flock_size=4, actual_duration_minutes=76)
        # 16 over 60 -> 2 started blocks: 8000 + 0 + 1400
        assert cleaning_done["final_price_cents"] == 9400


class TestSeasonalWindows:
    def test_wrap_window_covers_january_date(self, api):
        """PRD §3.2: "Coverage is wrap-aware and inclusive at both bounds: a
        non-wrapping window covers a date when the date's MM-DD string falls
        between the two bounds inclusively; a wrapping window covers it when
        the MM-DD is at or after `start_md` or at or before `end_md`."
        PRD §3.5: "The base component takes the visit type's list rate — 8000
        cents for a cleaning, 6000 for a health check, 12000 for predator
        proofing, 25000 for a setup install — multiplies it by the household
        zone's multiplier (1.0 for `URBAN`, 1.15 for `SUBURBAN`, 1.30 for
        `RURAL`), then multiplies by one plus the `visit_surcharge_pct` of the
        seasonal window covering the scheduled date in that zone (one plus zero
        when no window covers it), and rounds the result half up to whole
        cents, once."

        Design: Corner/calculations/seasonal_wrap_window_january_membership
        """
        create_window(window_code="WINTER_PEAK", zone_code="RURAL",
                      start_md="11-15", end_md="02-15",
                      visit_surcharge_pct=0.25, sitting_surcharge_pct=0.20)
        household = create_household(zone_code="RURAL", name="H Wrap", address="35 Range Rd")
        coop = create_coop(household, 4)
        install = create_visit(household, coop, "SETUP_INSTALL",
                               "2026-06-01T09:00:00Z", "2026-06-01T12:00:00Z")
        assign_visit(install["id"], "tech-1")
        check_in_visit(install["id"], "tech-1")
        complete_visit(install["id"], "tech-1", observed_flock_size=4,
                       actual_duration_minutes=180)

        visit = create_visit(household, coop, "COOP_CLEANING",
                             "2027-01-10T09:00:00Z", "2027-01-10T10:00:00Z")
        # 01-10 <= 02-15 satisfies wrap membership: round_half_up(8000*1.30*1.25) = 13000
        assert visit["provisional_price_cents"] == 13000

    def test_overlapping_window_for_same_zone_rejected(self, api):
        """PRD §3.2: "Creating a window that would cover a calendar day already
        covered by another window in the same zone is rejected with
        `ERR_SEASONAL_WINDOW_OVERLAP`, which is precisely the guarantee that
        lets pricing treat the covering-window set for any zone and date as
        having size zero or one: the lookup returns either the single covering
        window or nothing."

        Design: Corner/validations/seasonal_window_day_overlap_rejected
        """
        create_window(window_code="WINTER_PEAK", zone_code="RURAL",
                      start_md="11-15", end_md="02-15",
                      visit_surcharge_pct=0.25, sitting_surcharge_pct=0.20)
        res = api.create_seasonal_window(
            create_seasonal_window_payload(
                window_code="JAN_PROMO", zone_code="RURAL",
                start_md="01-01", end_md="01-31",
                visit_surcharge_pct=0.10, sitting_surcharge_pct=0.10),
            ADMIN,
        )
        validate_error(res, ApiErrorId.ERR_SEASONAL_WINDOW_OVERLAP)
