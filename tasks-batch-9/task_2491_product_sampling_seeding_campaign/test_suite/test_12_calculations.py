"""Derived figures: staircases, input-set filters, selectors, thresholds and variants."""

import pytest

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import fixtures as fx
from test_helpers import (
    assert_instant,
    campaign_manager_headers,
    fulfillment_ops_headers,
    moderator_a_headers,
    platform_admin_headers,
)
from test_helpers.api_errors import ERR_KIT_STOCK_INSUFFICIENT
from test_helpers.fixtures import KitSpec


SINGLE_HERO_KIT = (KitSpec("HERO-1", "HERO_PRODUCT", 1417, 1, 0.8, 10),)
SHORT_ACCESSORY_KIT = (
    KitSpec("HERO-1", "HERO_PRODUCT", 1417, 1, 0.8, 10),
    KitSpec("ACC-2", "ACCESSORY", 388, 2, 0.85, 1),
    KitSpec("INS-3", "INSERT_CARD", 554, 1, 0.9, 10),
)
FOUR_LINE_KIT = (
    KitSpec("HERO-1", "HERO_PRODUCT", 1417, 1, 0.8, 10),
    KitSpec("ACC-2", "ACCESSORY", 388, 2, 0.85, 20),
    KitSpec("INS-3", "INSERT_CARD", 554, 1, 0.9, 10),
    KitSpec("ACC-4", "ACCESSORY", 100, 1, 0.5, 5),
)


class TestHoldoutStaircase:
    """A deterministic staircase over the enrollment ordinal."""

    def test_only_the_fifth_of_five_enrollments_is_withheld(self, api):
        """PRD §3.4: "An enrollment is placed in the holdout group when the
        whole-number part of its `enrollment_seq` multiplied by the campaign's
        `holdout_pct` is strictly greater than the whole-number part of one less
        than its `enrollment_seq` multiplied by that same `holdout_pct`."

        PRD §3.4: "When the flag comes out true, the campaign's
        `holdout_enrollment_count` increases by 1 and its `version` by 1."

        Design: Corner/calculations/holdout_staircase_flags_exactly_the_fifth_of_five_enrollments
        """
        world = fx.screening_open_campaign(
            api, kit_specs=SINGLE_HERO_KIT, holdout_pct=0.2, name="Staircase"
        )
        enrollments = []
        for _ in range(5):
            panelist = fx.create_panelist(api)
            enrollments.append(
                fx.create_enrollment(api, world.campaign_id, panelist["id"])
            )
        for enrollment in enrollments[:4]:
            fx.screen_enrollment(api, enrollment["id"])

        fifth = validate_success(
            api.screen_enrollment(campaign_manager_headers(), enrollments[4]["id"])
        )

        assert fifth["enrollment_seq"] == 5
        assert fifth["screening_status"] == "SCREEN_PASSED"
        assert fifth["holdout_flag"] is True

        for enrollment in enrollments[:4]:
            stored = fx.get_enrollment(api, enrollment["id"])
            assert stored["holdout_flag"] is False

        campaign = fx.get_campaign(api, world.campaign_id)
        assert campaign["enrollment_count"] == 5
        assert campaign["holdout_enrollment_count"] == 1


class TestProvisionalCostPopulation:
    """The input set behind the provisional cost per sample."""

    def test_a_cancelled_shipment_leaves_both_sides_of_the_division(self, api):
        """PRD §3.6: "Its population is every shipment of the campaign — that is,
        every shipment whose enrollment belongs to the campaign — whose `status` is
        `ALLOCATED`, `SHIPPED`, `DELIVERED` or `LOST`; `CANCELLED` shipments are
        excluded entirely."

        PRD §3.6: "The result is that sum divided by the count of shipments in the
        population, rounded half-up to a whole cent in a **single** division at
        the end."

        Design: Corner/calculations/provisional_cost_per_sample_drops_a_cancelled_shipment_from_both_sides
        """
        world = fx.allocated_sample_world(
            api, panelist_count=2, surcharges=[0, 0], name="Cancelled Population"
        )

        cancelled = validate_success(
            api.cancel_sample_shipment(fulfillment_ops_headers(), world.shipment_id(1))
        )
        assert cancelled["status"] == "CANCELLED"

        survivor = fx.get_shipment(api, world.shipment_id(0))
        assert survivor["status"] == "ALLOCATED"

        campaign = fx.get_campaign(api, world.campaign_id)
        assert campaign["cost_per_sample_provisional_cents"] == 754
        assert campaign["cost_per_sample_final_cents"] == 0
        assert campaign["allocated_sample_count"] == 1
        assert campaign["budget_committed_cents"] == 754
        assert campaign["budget_available_cents"] == 999246

        wave = fx.get_wave(api, world.wave_id)
        assert wave["planned_unit_count"] == 4
        assert wave["status"] == "PLANNED"

        hero = fx.get_kit_line(api, world.kit_line_id(0))
        accessory = fx.get_kit_line(api, world.kit_line_id(1))
        insert = fx.get_kit_line(api, world.kit_line_id(2))
        assert (hero["units_available"], hero["units_reserved"]) == (9, 1)
        assert (accessory["units_available"], accessory["units_reserved"]) == (18, 2)
        assert (insert["units_available"], insert["units_reserved"]) == (9, 1)


class TestDisclosureRejectionConstant:
    """The absolute disclosure-rejection count in the posture branch test."""

    def test_the_third_rejection_restricts_the_campaign_and_the_second_does_not(
        self, api
    ):
        """PRD §2.9: "otherwise the posture is `RESTRICTED` when the diversion rate
        is at least 0.05, or when `disclosure_rejected_review_count` is at least 3;"

        PRD §3.7: "`REJECT_DISCLOSURE` moves the review `SUBMITTED →
        DISCLOSURE_REJECTED`, which is terminal, increases the campaign's
        `disclosure_rejected_review_count` by 1 and re-evaluates
        `compliance_posture`."

        Design: Corner/calculations/third_disclosure_rejection_applies_the_restricted_disclosure_constant
        """
        world = fx.delivered_sample_world(
            api,
            panelist_count=1,
            surcharges=[0],
            kit_specs=SINGLE_HERO_KIT,
            min_review_word_count=10,
            name="Disclosure Constant",
        )
        reviews = []
        for index in range(3):
            review = fx.create_review(
                api,
                world.enrollment_id(0),
                world.panelist_id(0),
                headline=f"Draft number {index + 1}",
            )
            reviews.append(fx.submit_review(api, review["id"], world.panelist_id(0)))
        for review in reviews[:2]:
            fx.moderate_review(
                api,
                review["id"],
                "REJECT_DISCLOSURE",
                headers=moderator_a_headers(),
                moderator_note="the disclosure is inadequate in substance",
            )
        after_two = fx.get_campaign(api, world.campaign_id)
        assert after_two["disclosure_rejected_review_count"] == 2
        assert after_two["compliance_posture"] == "OPEN"

        third = validate_success(
            api.moderate_review(
                moderator_a_headers(),
                reviews[2]["id"],
                decision="REJECT_DISCLOSURE",
                moderator_note="the disclosure is inadequate in substance",
            )
        )
        assert third["status"] == "DISCLOSURE_REJECTED"

        campaign = fx.get_campaign(api, world.campaign_id)
        assert campaign["disclosure_rejected_review_count"] == 3
        assert campaign["compliance_posture"] == "RESTRICTED"
        assert campaign["substantiated_diversion_count"] == 0
        assert campaign["delivered_sample_count"] == 1
        assert campaign["approved_review_count"] == 0
        assert campaign["status"] == "SAMPLING_ACTIVE"

        enrollment = fx.get_enrollment(api, world.enrollment_id(0))
        assert enrollment["obligation_status"] == "REVIEW_DUE"

        for review in reviews[:2]:
            stored = fx.get_review(api, review["id"])
            assert stored["status"] == "DISCLOSURE_REJECTED"


class TestReservationSelector:
    """The fixed selector that decides what a kit allocation debits."""

    def test_every_active_line_is_debited_and_the_retired_one_is_skipped(self, api):
        """PRD §3.6: "The candidate set is every kit line of the enrollment's
        campaign whose `status` is `ACTIVE`; `RETIRED` lines are never debited."

        PRD §3.6: "The candidates are ordered by `created_at` ascending with
        `component_sku` ascending as the tie-break, and each contributes its own
        `quantity_per_kit` units — one kit needs one line's worth of every active
        component."

        PRD §3.6: "On success the per-line debits are recorded on the shipment as
        `reserved_line_units`, a mapping from kit line to units taken, and their
        sum is recorded as `kit_unit_total` — the figure both capacity ceilings
        were tested against."

        Design: Corner/calculations/reservation_selector_debits_every_active_line_and_skips_the_retired_one
        """
        campaign = fx.create_campaign(api, name="Selector Sweep")
        lines = fx.build_kit(api, campaign["id"], FOUR_LINE_KIT)
        fx.retire_kit_line(api, lines[3]["id"])
        fx.open_screening(api, campaign["id"])
        panelist = fx.create_panelist(api)
        enrollment = fx.create_enrollment(api, campaign["id"], panelist["id"])
        enrollment = fx.screen_enrollment(api, enrollment["id"])
        fx.activate_sampling(api, campaign["id"])
        center = fx.create_center(api)
        wave = fx.create_wave(api, center["id"])

        shipment = validate_success(
            api.create_sample_shipment(
                fulfillment_ops_headers(),
                enrollment_id=enrollment["id"],
                fulfillment_wave_id=wave["id"],
                expected_enrollment_version=enrollment["version"],
                surcharge_cents=0,
            ),
            201,
        )

        assert shipment["kit_unit_total"] == 4
        assert shipment["reserved_line_units"] == {
            lines[0]["id"]: 1,
            lines[1]["id"]: 2,
            lines[2]["id"]: 1,
        }
        assert lines[3]["id"] not in shipment["reserved_line_units"]
        assert shipment["committed_cost_cents"] == 754

        hero = fx.get_kit_line(api, lines[0]["id"])
        accessory = fx.get_kit_line(api, lines[1]["id"])
        insert = fx.get_kit_line(api, lines[2]["id"])
        retired = fx.get_kit_line(api, lines[3]["id"])
        assert (hero["units_reserved"], hero["units_available"]) == (1, 9)
        assert (accessory["units_reserved"], accessory["units_available"]) == (2, 18)
        assert (insert["units_reserved"], insert["units_available"]) == (1, 9)
        assert retired["status"] == "RETIRED"
        assert retired["units_reserved"] == 0
        assert retired["units_available"] == 5

        stored = fx.get_campaign(api, campaign["id"])
        assert stored["kit_assembly_unit_cost_cents"] == 454
        assert stored["budget_committed_cents"] == 754

    def test_one_short_line_leaves_every_earlier_line_undebited(self, api):
        """PRD §3.6: "The reservation is **all-or-nothing**: the lines are walked
        in that order and the first line whose `units_available` is below its
        `quantity_per_kit` refuses the whole allocation with
        `ERR_KIT_STOCK_INSUFFICIENT`, leaving every kit line untouched. No partial
        reservation is ever written, so a failed allocation is indistinguishable
        from one that never happened."

        Design: Corner/calculations/short_stock_on_one_line_leaves_every_kit_line_untouched
        """
        world = fx.sampling_active_campaign(
            api, panelist_count=1, kit_specs=SHORT_ACCESSORY_KIT, name="Short Stock"
        )
        enrollment = fx.get_enrollment(api, world.enrollment_id(0))

        validate_error(
            api.create_sample_shipment(
                fulfillment_ops_headers(),
                enrollment_id=world.enrollment_id(0),
                fulfillment_wave_id=world.wave_id,
                expected_enrollment_version=enrollment["version"],
                surcharge_cents=0,
            ),
            ERR_KIT_STOCK_INSUFFICIENT,
            422,
        )

        hero = fx.get_kit_line(api, world.kit_line_id(0))
        accessory = fx.get_kit_line(api, world.kit_line_id(1))
        insert = fx.get_kit_line(api, world.kit_line_id(2))
        assert (hero["units_reserved"], hero["units_available"]) == (0, 10)
        assert (accessory["units_reserved"], accessory["units_available"]) == (0, 1)
        assert (insert["units_reserved"], insert["units_available"]) == (0, 10)

        campaign = fx.get_campaign(api, world.campaign_id)
        assert campaign["allocated_sample_count"] == 0
        assert campaign["budget_committed_cents"] == 0
        assert campaign["cost_per_sample_provisional_cents"] == 0

        wave = fx.get_wave(api, world.wave_id)
        assert wave["planned_unit_count"] == 0


class TestLiftVariantDivergence:
    """One conversion data set measured under both treated-group definitions."""

    def test_the_denominator_alone_moves_the_lift_between_variants(self, api):
        """PRD §3.9: "Under `ITT` — intent-to-treat — the treated group is every
        enrollment of the campaign whose `holdout_flag` is false and whose
        `screening_status` is `SCREEN_PASSED`, whether or not a sample ever
        reached them."

        PRD §3.9: "Under `PER_PROTOCOL` the treated group is restricted further to
        those enrollments that have at least one shipment in `DELIVERED`."

        PRD §3.9: "every existing analysis of the same campaign whose `superseded`
        is false has it set to true before the new row is stored with `superseded`
        false and `computed_at` stamped from the logical clock."

        Design: Corner/calculations/itt_and_per_protocol_lift_diverge_on_the_same_conversion_data
        """
        world = fx.delivered_sample_world(
            api, panelist_count=1, surcharges=[0], name="Variant Divergence"
        )
        untreated_panelist = fx.create_panelist(api)
        untreated = fx.create_enrollment(
            api, world.campaign_id, untreated_panelist["id"]
        )
        fx.screen_enrollment(api, untreated["id"])
        fx.create_purchase_match(
            api,
            world.enrollment_id(0),
            purchased_at="2026-08-10T00:00:00Z",
            match_confidence=0.9,
        )
        fx.open_review_window(api, world.campaign_id)

        before_itt = fx.get_campaign(api, world.campaign_id)
        itt = validate_success(
            api.create_lift_analysis(
                campaign_manager_headers(),
                campaign_id=world.campaign_id,
                variant="ITT",
                expected_campaign_version=before_itt["version"],
            ),
            201,
        )
        assert itt["variant"] == "ITT"
        assert itt["treated_count"] == 2
        assert itt["treated_converted_count"] == 1
        assert itt["treated_conversion_rate"] == pytest.approx(0.5, abs=0.0001)
        assert itt["lift_pct"] == pytest.approx(50.00, abs=0.01)

        before_pp = fx.get_campaign(api, world.campaign_id)
        per_protocol = validate_success(
            api.create_lift_analysis(
                campaign_manager_headers(),
                campaign_id=world.campaign_id,
                variant="PER_PROTOCOL",
                expected_campaign_version=before_pp["version"],
            ),
            201,
        )
        assert per_protocol["variant"] == "PER_PROTOCOL"
        assert per_protocol["treated_count"] == 1
        assert per_protocol["treated_converted_count"] == 1
        assert per_protocol["treated_conversion_rate"] == pytest.approx(1.0, abs=0.0001)
        assert per_protocol["lift_pct"] == pytest.approx(100.00, abs=0.01)

        for analysis in (itt, per_protocol):
            assert analysis["holdout_count"] == 0
            assert analysis["holdout_conversion_rate"] == pytest.approx(0.0, abs=0.0001)
            assert analysis["power_status"] == "INSUFFICIENT_POWER"

        assert per_protocol["effective_sample_count"] == 1
        assert per_protocol["diverted_unit_count"] == 0
        assert per_protocol["base_cost_per_sample_cents"] == 754
        assert per_protocol["penalty_rate_pct"] == 20
        assert per_protocol["diversion_penalty_cents"] == 0
        assert per_protocol["adjusted_cost_per_sample_cents"] == 754
        assert per_protocol["superseded"] is False
        assert_instant(per_protocol["computed_at"], "2026-08-01T00:00:00Z", "computed_at")

        superseded = validate_success(
            api.get_lift_analysis(campaign_manager_headers(), itt["id"])
        )
        assert superseded["superseded"] is True


class TestPurchaseMatchQualification:
    """The confidence floor, read at the last legal instant of the window."""

    def test_exactly_the_floor_qualifies_and_a_hair_under_it_does_not(self, api):
        """PRD §3.9: "The purchase must fall inside the campaign's conversion
        window — from the campaign's `sampling_window_start` through its
        `sampling_window_end` plus 30 days, inclusive at both ends — and one
        outside it is refused with `ERR_PURCHASE_MATCH_OUT_OF_WINDOW`."

        PRD §3.9: "The stored `qualified` flag is derived, not supplied: it is
        true when the `match_confidence` is at least 0.8 and the `purchased_at`
        instant lies inside that same conversion window. The 0.8 floor is
        inclusive, so a match at exactly 0.8 qualifies."

        Design: Corner/calculations/purchase_match_qualified_needs_the_confidence_floor_at_the_window_tail
        """
        world = fx.screening_open_campaign(
            api, kit_specs=SINGLE_HERO_KIT, name="Window Tail"
        )
        panelist = fx.create_panelist(api)
        enrollment = fx.create_enrollment(api, world.campaign_id, panelist["id"])
        fx.screen_enrollment(api, enrollment["id"])

        at_floor = validate_success(
            api.create_purchase_match(
                platform_admin_headers(),
                enrollment_id=enrollment["id"],
                retailer_channel_code="CH-ONLINE",
                purchase_amount_cents=2599,
                purchased_at="2026-10-30T00:00:00Z",
                match_confidence=0.8,
            ),
            201,
        )
        below_floor = validate_success(
            api.create_purchase_match(
                platform_admin_headers(),
                enrollment_id=enrollment["id"],
                retailer_channel_code="CH-ONLINE",
                purchase_amount_cents=2599,
                purchased_at="2026-10-30T00:00:00Z",
                match_confidence=0.7999,
            ),
            201,
        )

        assert at_floor["qualified"] is True
        assert_instant(at_floor["purchased_at"], "2026-10-30T00:00:00Z", "purchased_at")
        assert below_floor["qualified"] is False

        _, meta = validate_paginated(
            api.list_enrollment_purchase_matches(
                platform_admin_headers(), enrollment["id"]
            )
        )
        assert meta["total_count"] == 2
