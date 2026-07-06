"""Difficulty rule: combinatorial_formula.

Multi-input arithmetic with pinned rounding/clamping order:
  (A) citation fine = clamp(round(base * tier) + zone_surcharge, MIN, MAX);
  (B) boot release total = subtotal + flat fee + round(subtotal * 8.5%),
      with the admin percentage rounded once on the subtotal alone.
"""
from test_helpers import (
    validate_success,
    TEST_USERS,
    setup_issuing_context,
    issue_in_context,
    setup_boot_eligible_vehicle,
)

SUPERVISOR = TEST_USERS["supervisor_headers"]


class TestCitationFineTieredZoneClamp:
    def test_first_offense_downtown_fine(self, api):
        """PRD §3.3: "The base fine is then multiplied by that tier multiplier and
        rounded half-up to whole cents — this rounding happens *before* the surcharge
        is added, not after. Next a flat zone surcharge is added according to the
        citation's beat zone: 2,000 cents for a `DOWNTOWN` beat, 0 cents for a
        `RESIDENTIAL` beat, and 5,000 cents for a `SCHOOL` beat."

        Design: Difficulty/combinatorial_formula/citation_fine_tiered_zone_clamp
        """
        # DOWNTOWN, base 5000, first offense (n=0): round(5000*1.0)=5000 + 2000 = 7000.
        ctx = setup_issuing_context(patrol_zone="DOWNTOWN", base_fine_cents=5000,
                                    code="EXP_METER")
        cit = issue_in_context(ctx, evidence_photo_url="https://ev/m1.jpg")
        assert cit["fine_amount_cents"] == 7000, \
            f"first offense DOWNTOWN fine must be 7000, got {cit['fine_amount_cents']}"

    def test_second_offense_applies_repeat_tier(self, api):
        """PRD §3.3: "If there are no such prior citations the tier multiplier is 1.0;
        with exactly one prior it is 1.5; with two or more priors it is 2.0."

        Design: Difficulty/combinatorial_formula/citation_fine_tiered_zone_clamp
        """
        # Second EXP_METER on same vehicle (n=1): round(5000*1.5)=7500 + 2000 = 9500.
        ctx = setup_issuing_context(patrol_zone="DOWNTOWN", base_fine_cents=5000,
                                    code="EXP_METER")
        first = issue_in_context(ctx, evidence_photo_url="https://ev/m1.jpg")
        assert first["fine_amount_cents"] == 7000
        second = issue_in_context(ctx, evidence_photo_url="https://ev/m2.jpg")
        assert second["fine_amount_cents"] == 9500, \
            f"second offense DOWNTOWN fine must be 9500, got {second['fine_amount_cents']}"


class TestBootReleaseTotalRoundingOrder:
    def test_admin_fee_rounded_half_up_on_subtotal_only(self, api):
        """PRD §3.8: "It then computes the administrative fee as 8.5 percent of that
        subtotal — the fraction is applied to the citations subtotal alone, rounded
        half-up to whole cents, and is *not* charged on the boot or tow fee."

        Design: Difficulty/combinatorial_formula/boot_release_total_rounding_order
        """
        # subtotal = 15000+22500+25000 = 62500; round_half_up(62500*0.085)=round(5312.5)=5313.
        ctx = setup_boot_eligible_vehicle()
        order = ctx["boot_order"]
        released = validate_success(api.release_boot_tow_order(order["id"], SUPERVISOR))
        subtotal = 62500
        admin_component = released["release_total_cents"] - subtotal - released["fee_cents"]
        assert admin_component == 5313, \
            f"admin fee on subtotal alone must round to 5313, got {admin_component}"

    def test_release_total_is_subtotal_plus_fee_plus_admin(self, api):
        """PRD §3.8: "The `release_total_cents` is the citations subtotal plus the
        flat enforcement fee (`fee_cents`) plus that rounded administrative fee. The
        `release_total_cents` is null until the order reaches `RELEASED`."

        Design: Difficulty/combinatorial_formula/boot_release_total_rounding_order
        """
        ctx = setup_boot_eligible_vehicle()
        order = ctx["boot_order"]
        released = validate_success(api.release_boot_tow_order(order["id"], SUPERVISOR))
        subtotal = 62500
        assert released["status"] == "RELEASED"
        assert released["release_total_cents"] == subtotal + released["fee_cents"] + 5313, \
            f"release_total mismatch, got {released['release_total_cents']}"
