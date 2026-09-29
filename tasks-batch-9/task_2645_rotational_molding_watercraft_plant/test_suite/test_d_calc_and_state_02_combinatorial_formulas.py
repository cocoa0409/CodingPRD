"""Formulas whose answer depends on the order their steps are evaluated in.

Three rules of PRD.md are only well defined because the order of their steps is
pinned: the wall-thickness distribution rounds the mean before the standard
deviation is taken about it and before the coefficient of variation divides the
two rounded values; zone selection resolves anchor existence, then the candidate
footprint, then the remaining cube, then the ranking; and warranty pricing picks
the administrative-fee tier from the gross before any deduction reduces it.

Each test below is written so that an implementation which reorders the steps —
dividing unrounded values, ranking on fit before affinity, or re-selecting the
fee band after the storage deduction — fails it.
"""

from test_helpers import (
    ADMIN_HEADERS,
    AGENT_HEADERS,
    PLANNER_HEADERS,
    Q_CUBE,
    Q_MASS,
    Q_PERCENT,
    Q_WARPAGE,
    advance_unit_to_outfitted,
    api_client,
    approve_claim_payload,
    assert_claim_payout_arithmetic,
    assert_decimal_equals,
    assert_money_equals,
    assert_warranty_reserve_conserved,
    inspect_payload,
    product_model_version,
    release_storage_payload,
    set_clock,
    setup_delivered_unit_with_customer,
    setup_demolded_units,
    setup_sellable_units,
    storage_review_payload,
    store_unit,
    validate_success,
    waive_storage_finding_payload,
    warranty_claim_payload,
    zone,
)

# Six readings whose arithmetic mean is 6.151666..., which rounds to 6.152. The
# population standard deviation about that rounded mean is 0.107, so the
# coefficient of variation is 1.74 percent. Dividing the unrounded deviation by
# the unrounded mean instead gives 1.75 percent — a different answer for the
# very same hull.
_P1_NESTED_ROUNDING_POINTS = [6.14, 6.0, 6.19, 6.34, 6.18, 6.06]

# The ceiling is set to exactly the coefficient of variation the readings above
# produce under PRD.md's rounding order, so the two orders give two verdicts.
_P1_CV_CEILING_PCT = 1.74


def _p1_outfitted_hull_at_cv_ceiling():
    """One OUTFITTED hull whose model tolerates exactly 1.74 percent variation."""
    ctx = setup_demolded_units(model_overrides={"wall_cv_max_pct": _P1_CV_CEILING_PCT})
    unit = ctx["finished_units"][0]
    advance_unit_to_outfitted(ctx, unit)
    ctx["unit_under_test"] = unit
    return ctx


def _p1_inspect_with_nested_rounding_points(ctx):
    """Inspect the hull under test with the readings that pin the rounding order."""
    return validate_success(
        api_client.inspect_finished_unit(
            ctx["unit_under_test"]["id"],
            inspect_payload(wall_thickness_points=list(_P1_NESTED_ROUNDING_POINTS)),
            ctx["inspector_headers"],
        ),
        200,
    )


class TestWallDistributionNestedRounding:
    """The mean is rounded first, and everything downstream reads that value."""

    def test_mean_then_sd_then_cv_each_read_the_previous_rounded_value(self):
        """Each distribution step consumes the already-rounded step before it.

        PRD.md section 3.6: "With `n` the number of supplied points:
        `mean_wall_thickness_mm` is the sum of the points divided by `n`, rounded
        to three decimals and stored."

        PRD.md section 3.6: "`wall_sd_mm` is then the population standard
        deviation taken **about that already-rounded mean** — the sum over the
        points of the squared difference from `mean_wall_thickness_mm`, divided by
        `n` (the population divisor, never `n` minus 1), square-rooted, and
        rounded to three decimals."

        PRD.md section 3.6: "Using the unrounded arithmetic mean here produces a
        different standard deviation and is wrong."

        PRD.md section 3.6: "`wall_cv_pct` is then `wall_sd_mm` divided by
        `mean_wall_thickness_mm` times 100, rounded to two decimals, computed from
        the two already-rounded values, and is 0.00 when the mean is 0.000."

        PRD.md section 3.6: "`min_wall_thickness_mm` is the smallest supplied
        point rounded to three decimals."

        The six readings sum to 36.91, so the mean is 6.152; the squared
        deviations about 6.152 sum to 0.069284, so the population deviation is
        0.107; and 0.107 over 6.152 is 1.74 percent. Dividing the unrounded
        0.1074547 by the unrounded 6.1516666 gives 1.75 instead.

        Design: Difficulty/combinatorial_formula/wall_distribution_nested_rounding_mean_then_sd_then_cv
        """
        ctx = _p1_outfitted_hull_at_cv_ceiling()
        unit = _p1_inspect_with_nested_rounding_points(ctx)

        assert_decimal_equals(
            unit["mean_wall_thickness_mm"], "6.152", Q_MASS, "mean_wall_thickness_mm"
        )
        assert_decimal_equals(unit["wall_sd_mm"], "0.107", Q_MASS, "wall_sd_mm")
        assert_decimal_equals(unit["wall_cv_pct"], "1.74", Q_PERCENT, "wall_cv_pct")
        assert_decimal_equals(
            unit["min_wall_thickness_mm"], "6.000", Q_MASS, "min_wall_thickness_mm"
        )

    def test_variation_exactly_at_the_model_ceiling_passes_instead_of_reworking(self):
        """1.74 against a 1.74 ceiling is not "strictly greater", so it passes.

        PRD.md section 3.6: "(5) `wall_cv_pct` strictly greater than the model's
        `wall_cv_max_pct` gives `REWORK`; exactly equal passes."

        PRD.md section 3.6: "Term 4, distribution penalty: `wall_cv_pct` minus the
        model's `wall_cv_max_pct`, floored at zero, divided by 10, rounded to
        three decimals."

        PRD.md section 3.6: "(8) Otherwise the verdict is `PASS`."

        PRD.md section 3.6: "The verdict writes `inspection_verdict` and moves
        `build_status`: a `PASS` moves `OUTFITTED` to `SELLABLE`; a `REWORK` moves
        `OUTFITTED` to `REWORK` and increments `rework_count`; a `SCRAP` moves
        `OUTFITTED` to `SCRAPPED`."

        This is the falsifying half of the rounding order: a coefficient of
        variation of 1.75 would exceed the 1.74 ceiling, raise the distribution
        term off zero and rework the hull. Under PRD.md's order it is 1.74, the
        distribution term is 0.000 and the hull is sellable.

        Design: Difficulty/combinatorial_formula/wall_distribution_nested_rounding_mean_then_sd_then_cv
        """
        ctx = _p1_outfitted_hull_at_cv_ceiling()
        unit = _p1_inspect_with_nested_rounding_points(ctx)

        assert_decimal_equals(unit["wall_cv_pct"], "1.74", Q_PERCENT, "wall_cv_pct")
        assert_decimal_equals(
            unit["final_warpage_index"], "0.000", Q_WARPAGE, "final_warpage_index"
        )
        assert unit["inspection_verdict"] == "PASS", (
            "a coefficient of variation exactly at the ceiling passes clause 5, so "
            f"the verdict must be PASS, got {unit['inspection_verdict']}"
        )
        assert unit["build_status"] == "SELLABLE", (
            f"a PASS moves the hull to SELLABLE, got {unit['build_status']}"
        )
        assert unit["rework_count"] == 0, (
            f"no rework may be recorded on a passing hull, got {unit['rework_count']}"
        )


def _p1_two_zone_site_with_three_stored_hulls():
    """A four-cavity cycle and a two-zone site with three hulls already stored.

    The site holds 14.0000 cube over a tight Z-A of 4.0000 and a roomy Z-B of
    10.0000. The three stored hulls go in at 13:00, 13:05 and 13:10, so the
    promotion tie-break on ``stored_at`` is unambiguous, and the fourth hull is
    left SELLABLE and UNALLOCATED.
    """
    ctx = setup_sellable_units(
        model_overrides={"nominal_charge_kg": 6.0},
        mold_overrides={"cavity_count": 4, "nominal_charge_kg": 24.0},
        warehouse_overrides={
            "footprint_capacity_cube_m3": 14.0,
            "zones": [zone("Z-A", 4.0), zone("Z-B", 10.0)],
        },
        order_overrides={"ordered_qty": 4},
    )
    hulls = ctx["sellable_units"]
    assert len(hulls) == 4, f"expected four sellable hulls, got {len(hulls)}"
    instants = (
        "2026-08-01T13:00:00Z",
        "2026-08-01T13:05:00Z",
        "2026-08-01T13:10:00Z",
    )
    stored = []
    for unit, instant in zip(hulls[:3], instants):
        set_clock(instant)
        stored.append(store_unit(ctx, unit))
    ctx["stored_three"] = stored
    ctx["fourth_hull"] = hulls[3]
    return ctx


def _p1_read_unit(unit_id):
    return api_client.read_entity("get_finished_unit", unit_id, PLANNER_HEADERS)


def _p1_read_site(ctx):
    return api_client.read_entity("get_warehouse", ctx["warehouse_id"], PLANNER_HEADERS)


class TestZoneSelectorAffinityThenFitThenPromotion:
    """Anchor affinity, then tightest fit, then the anchor promotion on release."""

    def test_anchor_affinity_outranks_a_looser_fitting_empty_zone(self):
        """A nested follower is forced into the anchoring zone, not the empty one.

        PRD.md section 3.7: "Eligible zones are ranked with anchor affinity first
        (zones already anchoring this hull model win), then tightest fit by
        ascending remaining cube, then ascending `zone_code`, which is unique
        within the site and therefore makes the order total; neither the hull's
        identifier nor the zone's array position is ever consulted."

        PRD.md section 3.7: "**Joining an existing nest group** charges
        `gross_cube_m3` multiplied by `nest_factor` and leaves `is_zone_anchor`
        false, and the affinity term forces that zone even when a wholly empty
        zone would give a looser fit."

        PRD.md section 3.7: "A zone is eligible when that remainder is at or
        above 0.0000, so a zone that fills to exactly capacity is eligible."

        The first hull opens the group in the tighter Z-A. The second and third
        then follow it there at 1.0000 each even though Z-B is wholly empty, and
        the third fills Z-A to exactly its 4.0000 capacity.

        Design: Difficulty/combinatorial_formula/zone_selector_anchor_affinity_then_remaining_then_promotion
        """
        ctx = _p1_two_zone_site_with_three_stored_hulls()
        first, second, third = ctx["stored_three"]

        assert first["storage_zone_code"] == "Z-A", (
            "with no anchor anywhere the tighter Z-A wins on fit, got "
            f"{first['storage_zone_code']}"
        )
        assert first["is_zone_anchor"] is True, (
            "the first hull of a nest group is its anchor"
        )
        assert_decimal_equals(
            first["stored_footprint_cube_m3"], "2.0000", Q_CUBE, "anchor footprint"
        )

        for label, unit in (("second", second), ("third", third)):
            assert unit["storage_zone_code"] == "Z-A", (
                f"anchor affinity must keep the {label} hull in Z-A, got "
                f"{unit['storage_zone_code']}"
            )
            assert unit["is_zone_anchor"] is False, (
                f"the {label} hull joins an existing group, so it is not an anchor"
            )
            assert_decimal_equals(
                unit["stored_footprint_cube_m3"],
                "1.0000",
                Q_CUBE,
                f"{label} nested footprint",
            )

        site = _p1_read_site(ctx)
        assert_decimal_equals(
            site["committed_cube_m3"], "4.0000", Q_CUBE, "committed_cube_m3"
        )
        assert_decimal_equals(
            site["utilization_pct"], "28.57", Q_PERCENT, "utilization_pct"
        )
        assert site["posture"] == "NORMAL", (
            f"28.57 percent is below the restricted threshold, got {site['posture']}"
        )

    def test_a_zone_that_cannot_fit_the_nested_follower_opens_a_second_group(self):
        """Once the anchoring zone is exactly full the affinity term stops winning.

        PRD.md section 3.7: "the remaining cube after admission is the zone's
        `capacity_cube_m3` minus that committed sum minus the candidate footprint,
        rounded to four decimals. A zone is eligible when that remainder is at or
        above 0.0000, so a zone that fills to exactly capacity is eligible."

        PRD.md section 3.7: "Opening a **new nest group** — no eligible zone
        anchors this model — charges the full `gross_cube_m3` and sets
        `is_zone_anchor` true."

        Z-A is committed to exactly 4.0000, so admitting a fourth nested hull
        there would leave -1.0000 and the affinity-ranked zone drops out of the
        eligible set entirely. Z-B then opens a second group at full cube, which
        raises the site's committed cube by 2.0000 rather than 1.0000.

        Design: Difficulty/combinatorial_formula/zone_selector_anchor_affinity_then_remaining_then_promotion
        """
        ctx = _p1_two_zone_site_with_three_stored_hulls()

        set_clock("2026-08-01T13:15:00Z")
        fourth = store_unit(ctx, ctx["fourth_hull"])

        assert fourth["storage_zone_code"] == "Z-B", (
            "Z-A is full to capacity, so only Z-B remains eligible, got "
            f"{fourth['storage_zone_code']}"
        )
        assert fourth["is_zone_anchor"] is True, (
            "no eligible zone anchors this model any more, so the hull opens a group"
        )
        assert_decimal_equals(
            fourth["stored_footprint_cube_m3"],
            "2.0000",
            Q_CUBE,
            "new-group footprint",
        )
        assert fourth["logistics_status"] == "STORED", (
            f"storing writes STORED, got {fourth['logistics_status']}"
        )

        site = _p1_read_site(ctx)
        assert_decimal_equals(
            site["committed_cube_m3"], "6.0000", Q_CUBE, "committed_cube_m3"
        )
        assert_decimal_equals(
            site["utilization_pct"], "42.86", Q_PERCENT, "utilization_pct"
        )

    def test_releasing_the_anchor_promotes_the_earliest_follower_upward(self):
        """The promotion re-charge makes the site more utilised, not less.

        PRD.md section 3.7: "when the released hull *was* its nest group's anchor
        and followers remain, the earliest surviving occupant of the same
        site-zone-model group — ordered by ascending `stored_at` with ascending
        `hull_serial` as the total tie-break — is promoted: its `is_zone_anchor`
        becomes true and its `stored_footprint_cube_m3` is re-charged to the full
        `gross_cube_m3` rounded to four decimals."

        PRD.md section 3.7: "Promotion **raises** the group's total footprint by
        `gross_cube_m3` multiplied by one minus `nest_factor`, so releasing one
        hull can leave the site more utilised than a naive subtraction predicts."

        PRD.md section 3.7: "the hull moves `STORED` to `UNALLOCATED`, its
        `warehouse_id`, `storage_zone_code`, `stored_at` and `demand_bucket_id`
        are cleared, its `stored_footprint_cube_m3` is set to 0.0000 and
        `is_zone_anchor` to false."

        Releasing the 13:00 anchor gives up 2.0000 and promotes the 13:05 hull
        from 1.0000 to 2.0000, so the site falls only from 6.0000 to 5.0000. The
        13:10 hull is untouched and the Z-B group is unaffected.

        Design: Difficulty/combinatorial_formula/zone_selector_anchor_affinity_then_remaining_then_promotion
        """
        ctx = _p1_two_zone_site_with_three_stored_hulls()
        set_clock("2026-08-01T13:15:00Z")
        fourth = store_unit(ctx, ctx["fourth_hull"])
        anchor, follower, laggard = ctx["stored_three"]

        set_clock("2026-08-01T13:20:00Z")
        released = validate_success(
            api_client.release_storage(
                anchor["id"], release_storage_payload(), PLANNER_HEADERS
            ),
            200,
        )

        assert released["logistics_status"] == "UNALLOCATED", (
            f"the released hull leaves storage, got {released['logistics_status']}"
        )
        assert released["storage_zone_code"] is None, "the zone code is cleared"
        assert released["stored_at"] is None, "stored_at is cleared on release"
        assert released["is_zone_anchor"] is False, "the released hull is no anchor"
        assert_decimal_equals(
            released["stored_footprint_cube_m3"],
            "0.0000",
            Q_CUBE,
            "released footprint",
        )

        promoted = _p1_read_unit(follower["id"])
        assert promoted["is_zone_anchor"] is True, (
            "the 13:05 hull is the earliest surviving occupant and must be promoted"
        )
        assert_decimal_equals(
            promoted["stored_footprint_cube_m3"],
            "2.0000",
            Q_CUBE,
            "promoted footprint re-charged to full gross cube",
        )
        assert promoted["storage_zone_code"] == "Z-A", "promotion does not move a hull"

        untouched = _p1_read_unit(laggard["id"])
        assert untouched["is_zone_anchor"] is False, (
            "only one follower is promoted, and it is the earliest by stored_at"
        )
        assert_decimal_equals(
            untouched["stored_footprint_cube_m3"],
            "1.0000",
            Q_CUBE,
            "later follower stays nested",
        )

        other_group = _p1_read_unit(fourth["id"])
        assert other_group["is_zone_anchor"] is True, (
            "the Z-B group is a different site-zone-model triple and is untouched"
        )
        assert_decimal_equals(
            other_group["stored_footprint_cube_m3"],
            "2.0000",
            Q_CUBE,
            "Z-B anchor footprint",
        )

        site = _p1_read_site(ctx)
        assert_decimal_equals(
            site["committed_cube_m3"], "5.0000", Q_CUBE, "committed_cube_m3"
        )
        assert_decimal_equals(
            site["utilization_pct"], "35.71", Q_PERCENT, "utilization_pct"
        )
        assert site["posture"] == "NORMAL", (
            f"35.71 percent stays in the normal band, got {site['posture']}"
        )


_P1_TWELVE_MONTHS_ON = "2027-08-02T00:00:00Z"


def _p1_hull_delivered_twelve_months_ago():
    """A delivered hull on a 300000-cent model with a 500000-cent reserve.

    The clock is moved to exactly twelve calendar months after ``delivered_at``,
    so the frozen ``months_in_service`` is 12 and the PRO_RATA_AGE coverage share
    is (60 - 12) / 60 * 100 = 80.00 percent.
    """
    ctx = setup_delivered_unit_with_customer(
        model_overrides={
            "msrp_cents": 300000,
            "initial_warranty_reserve_cents": 500000,
        }
    )
    set_clock(_P1_TWELVE_MONTHS_ON)
    return ctx


def _p1_claim_under_review(ctx, **claim_overrides):
    claim = validate_success(
        api_client.create_warranty_claim(
            warranty_claim_payload(ctx["unit_id"], ctx["customer_id"], **claim_overrides),
            AGENT_HEADERS,
        ),
        201,
    )
    reviewing = validate_success(
        api_client.start_claim_review(claim["id"], AGENT_HEADERS), 200
    )
    assert reviewing["months_in_service"] == 12, (
        "the claim must freeze twelve complete calendar months of service, got "
        f"{reviewing['months_in_service']}"
    )
    return reviewing


def _p1_settle_storage_axis(ctx, claim_id, *, waived):
    """Drive the storage axis to WAIVED (via VIOLATED) or to GUIDANCE_VERIFIED."""
    outcome = "VIOLATED" if waived else "VERIFIED"
    decided = validate_success(
        api_client.submit_storage_review(
            claim_id, storage_review_payload(outcome=outcome), AGENT_HEADERS
        ),
        200,
    )
    if not waived:
        return decided
    return validate_success(
        api_client.waive_storage_finding(
            claim_id, waive_storage_finding_payload(), ADMIN_HEADERS
        ),
        200,
    )


def _p1_approve(ctx, claim_id):
    return validate_success(
        api_client.approve_warranty_claim(
            claim_id,
            approve_claim_payload(product_model_version(ctx["product_model_id"])),
            AGENT_HEADERS,
        ),
        200,
    )


class TestWarrantyPayoutGrossThenFeeTierThenDeduction:
    """Coverage, then gross, then the fee tier, then the deduction, then the net."""

    def test_the_fee_tier_is_chosen_from_the_gross_not_from_the_reduced_amount(self):
        """A waived claim pays the expensive band's fee on the full gross.

        PRD.md section 3.9: "Under the `PRO_RATA_AGE` variant the coverage
        percentage is 60 minus `months_in_service`, divided by 60, times 100,
        rounded to two decimals."

        PRD.md section 3.9: "`admin_fee_cents` is the gross multiplied by the rate
        of the **first** tier whose maximum gross is at or above
        `pre_fee_gross_cents`, from an ordered ladder of 50000 cents at 12.00
        percent and 200000 cents at 8.00 percent, falling through to a top rate of
        5.00 percent, rounded half-up. That tier is chosen **once, from the gross,
        before any deduction**, and is never re-selected against the reduced
        amount: a claim whose post-deduction value would have fallen into a
        cheaper band still pays the expensive band's fee."

        PRD.md section 3.9: "A waiver unblocks approval but does **not** restore
        full value: the 35.00 percent storage deduction still applies to a claim
        approved from `WAIVED`."

        PRD.md section 3.9: "`net_payout_cents` is the gross minus the deduction
        minus the fee, floored at 0 so it can never go negative."

        The gross of 240000 clears both tier maxima and so pays the 5.00 percent
        top rate, 12000 cents. The 35.00 percent waived deduction of 84000 would
        have dropped the remainder to 156000, inside the 8.00 percent band, but
        the tier is never re-selected.

        Design: Difficulty/combinatorial_formula/warranty_payout_gross_then_fee_tier_then_storage_deduction
        """
        ctx = _p1_hull_delivered_twelve_months_ago()
        claim = _p1_claim_under_review(ctx)
        waived = _p1_settle_storage_axis(ctx, claim["id"], waived=True)
        assert waived["storage_review_status"] == "WAIVED", (
            f"the axis must read WAIVED before approval, got {waived['storage_review_status']}"
        )

        approved = _p1_approve(ctx, claim["id"])

        assert approved["claim_status"] == "APPROVED", (
            f"approval moves the claim to APPROVED, got {approved['claim_status']}"
        )
        assert approved["payout_basis"] == "PRO_RATA_AGE", (
            "payout_basis is copied from the model's warranty_basis, got "
            f"{approved['payout_basis']}"
        )
        assert_money_equals(approved["pre_fee_gross_cents"], 240000, "pre_fee_gross_cents")
        assert_money_equals(approved["admin_fee_cents"], 12000, "admin_fee_cents")
        assert_money_equals(
            approved["storage_deduction_cents"], 84000, "storage_deduction_cents"
        )
        assert_money_equals(approved["net_payout_cents"], 144000, "net_payout_cents")
        assert_claim_payout_arithmetic(approved)

    def test_the_claim_type_factor_lands_the_same_hull_in_a_cheaper_fee_band(self):
        """The 0.30 cosmetic factor shrinks the gross into the 8.00 percent tier.

        PRD.md section 3.9: "`pre_fee_gross_cents` is the model's `msrp_cents`
        multiplied by the coverage percentage divided by 100, multiplied by the
        claim-type factor — 1.00 for `HULL_DEFORMATION`, 0.60 for `HARDWARE`, 0.30
        for `COSMETIC` — and rounded half-up to whole cents."

        PRD.md section 3.9: "`storage_deduction_cents` is the gross multiplied by
        35.00 percent, rounded half-up, when `storage_review_status` is `WAIVED`,
        and exactly 0 when it is `GUIDANCE_VERIFIED`."

        The same model, hull and age priced as COSMETIC give a gross of 72000,
        which the 200000-cent tier still covers, so the fee is 8.00 percent rather
        than the top 5.00 percent. A verified storage axis contributes no
        deduction, so the net is the gross less the fee alone.

        Design: Difficulty/combinatorial_formula/warranty_payout_gross_then_fee_tier_then_storage_deduction
        """
        ctx = _p1_hull_delivered_twelve_months_ago()
        claim = _p1_claim_under_review(ctx, claim_type="COSMETIC")
        verified = _p1_settle_storage_axis(ctx, claim["id"], waived=False)
        assert verified["storage_review_status"] == "GUIDANCE_VERIFIED", (
            "a verified review guarantees a zero deduction, got "
            f"{verified['storage_review_status']}"
        )

        approved = _p1_approve(ctx, claim["id"])

        assert_money_equals(approved["pre_fee_gross_cents"], 72000, "pre_fee_gross_cents")
        assert_money_equals(approved["admin_fee_cents"], 5760, "admin_fee_cents")
        assert_money_equals(
            approved["storage_deduction_cents"], 0, "storage_deduction_cents"
        )
        assert_money_equals(approved["net_payout_cents"], 66240, "net_payout_cents")
        assert_claim_payout_arithmetic(approved)

    def test_two_payouts_move_the_reserve_ledger_by_exactly_their_nets(self):
        """Both approvals draw down the one shared reserve and it stays conserved.

        PRD.md section 3.9: "the model's `warranty_reserve_cents` decreases by
        `net_payout_cents` and its `warranty_paid_cents` increases by the identical
        integer. No rounding happens in the ledger itself, because the amount was
        already rounded during pricing."

        PRD.md section 3.9: "The invariant `warranty_reserve_cents` plus
        `warranty_paid_cents` equals `initial_warranty_reserve_cents` holds after
        every ledger move, without exception."

        A waived deformation claim at 144000 and a verified cosmetic claim at
        66240 draw 210240 in total from a 500000-cent reserve, leaving 289760.

        Design: Difficulty/combinatorial_formula/warranty_payout_gross_then_fee_tier_then_storage_deduction
        """
        ctx = _p1_hull_delivered_twelve_months_ago()

        deformation = _p1_claim_under_review(ctx)
        _p1_settle_storage_axis(ctx, deformation["id"], waived=True)
        first = _p1_approve(ctx, deformation["id"])
        assert_money_equals(first["net_payout_cents"], 144000, "first net_payout_cents")

        cosmetic = _p1_claim_under_review(ctx, claim_type="COSMETIC")
        _p1_settle_storage_axis(ctx, cosmetic["id"], waived=False)
        second = _p1_approve(ctx, cosmetic["id"])
        assert_money_equals(second["net_payout_cents"], 66240, "second net_payout_cents")

        model = api_client.read_entity(
            "get_product_model", ctx["product_model_id"], ADMIN_HEADERS
        )
        assert_money_equals(
            model["warranty_reserve_cents"], 289760, "warranty_reserve_cents"
        )
        assert_money_equals(model["warranty_paid_cents"], 210240, "warranty_paid_cents")
        assert_warranty_reserve_conserved(model)
