"""Comparisons that must land on the inclusive side of their own boundary."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import fixtures as fx
from test_helpers import (
    assert_instant,
    campaign_manager_headers,
    fulfillment_ops_headers,
    moderator_a_headers,
)
from test_helpers.api_errors import ERR_CAMPAIGN_KIT_EMPTY, ERR_REVIEW_TOO_SHORT
from test_helpers.fixtures import KitSpec


SINGLE_HERO_KIT = (KitSpec("HERO-1", "HERO_PRODUCT", 1417, 1, 0.8, 10),)

TEN_WORD_BODY = "This sample kit arrived quickly and worked very well overall"
NINE_WORD_BODY = "This sample kit arrived quickly and worked very well"


class TestReviewWordCountAtTheCampaignFloor:
    """Exactly the floor passes; one word under it does not."""

    @staticmethod
    def _two_drafts_astride_the_floor(api):
        """Two delivered samples, one draft of ten words and one of nine.

        The campaign floor is ten words, so the two drafts sit on either side of
        an inclusive comparison and differ in nothing else.
        """
        world = fx.delivered_sample_world(
            api,
            panelist_count=2,
            surcharges=[0, 0],
            kit_specs=SINGLE_HERO_KIT,
            center_overrides={"freight_cents_per_kit": 300},
            wave_overrides={"planned_capacity_units": 50},
            objective_type="REVIEW_ACQUISITION",
            min_review_word_count=10,
            name="Word Boundary",
        )
        at_floor = fx.create_review(
            api,
            world.enrollment_id(0),
            world.panelist_id(0),
            headline="Exactly ten",
            body_text=TEN_WORD_BODY,
            star_rating=4,
            disclosure_statement="Sample provided by the brand.",
        )
        under_floor = fx.create_review(
            api,
            world.enrollment_id(1),
            world.panelist_id(1),
            headline="One word short",
            body_text=NINE_WORD_BODY,
            star_rating=4,
            disclosure_statement="Sample provided by the brand.",
        )
        return world, at_floor, under_floor

    def test_a_review_exactly_at_the_floor_is_accepted(self, api):
        """PRD §3.7: "`word_count` is at least the campaign's
        `min_review_word_count`, otherwise `ERR_REVIEW_TOO_SHORT`. The comparison
        is inclusive: a review whose word count exactly equals the campaign floor
        passes."

        Design: Difficulty/boundary_precision_check/review_word_count_inclusive_at_min_review_word_count
        """
        world, at_floor, _ = self._two_drafts_astride_the_floor(api)

        submitted = validate_success(
            api.submit_review(world.panelist_headers(0), at_floor["id"])
        )

        assert submitted["word_count"] == 10
        assert submitted["status"] == "SUBMITTED"
        assert_instant(submitted["first_submitted_at"], "2026-08-01T00:00:00Z", "first_submitted_at")

    def test_a_review_one_word_under_the_floor_is_refused(self, api):
        """PRD §3.7: "The review's `word_count` is at least the campaign's
        `min_review_word_count` — otherwise `ERR_REVIEW_TOO_SHORT` (422). Applies
        to review submission and review revision."

        Design: Difficulty/boundary_precision_check/review_word_count_inclusive_at_min_review_word_count
        """
        world, _, under_floor = self._two_drafts_astride_the_floor(api)

        assert under_floor["word_count"] == 9

        validate_error(
            api.submit_review(world.panelist_headers(1), under_floor["id"]),
            ERR_REVIEW_TOO_SHORT,
            422,
        )

    def test_the_refused_submission_leaves_the_draft_unstamped(self, api):
        """PRD §3.7: "A first submission stamps `first_submitted_at` with the
        logical clock's current instant, and only a first submission does so —
        every later submission of the same review leaves that timestamp exactly
        as it was, which is what makes it a stable anchor for the audit variant's
        review-velocity window in §3.3."

        Design: Difficulty/boundary_precision_check/review_word_count_inclusive_at_min_review_word_count
        """
        world, _, under_floor = self._two_drafts_astride_the_floor(api)

        validate_error(
            api.submit_review(world.panelist_headers(1), under_floor["id"]),
            ERR_REVIEW_TOO_SHORT,
        )

        stored = validate_success(
            api.get_review_submission(moderator_a_headers(), under_floor["id"])
        )
        assert stored["status"] == "DRAFT"
        assert stored["first_submitted_at"] is None


class TestActiveKitPoolCollapsingToZero:
    """The reservation candidate set falling from one line to none."""

    @staticmethod
    def _campaign_whose_only_line_is_retired(api):
        """A sampling-active campaign left with an empty active kit pool.

        The single line was stocked and costed before retirement, so the only
        thing that changed is the cardinality of the active candidate set.
        """
        world = fx.sampling_active_campaign(
            api,
            panelist_count=1,
            kit_specs=SINGLE_HERO_KIT,
            center_overrides={"freight_cents_per_kit": 300},
            wave_overrides={"planned_capacity_units": 50},
            name="Empty Pool",
        )
        fx.retire_kit_line(api, world.kit_line_id(0))
        return world

    def test_an_empty_active_pool_refuses_the_allocation(self, api):
        """PRD §3.6: "The candidate set is every kit line of the enrollment's
        campaign whose `status` is `ACTIVE`; `RETIRED` lines are never debited.
        If that set is empty the allocation is refused with
        `ERR_CAMPAIGN_KIT_EMPTY`."

        Design: Difficulty/boundary_precision_check/retired_last_kit_line_empties_the_active_pool_at_zero
        """
        world = self._campaign_whose_only_line_is_retired(api)
        enrollment = fx.get_enrollment(api, world.enrollment_id(0))

        validate_error(
            api.create_sample_shipment(
                fulfillment_ops_headers(),
                enrollment_id=world.enrollment_id(0),
                fulfillment_wave_id=world.wave_id,
                expected_enrollment_version=enrollment["version"],
                surcharge_cents=0,
            ),
            ERR_CAMPAIGN_KIT_EMPTY,
            422,
        )

    def test_the_retired_line_keeps_its_own_extended_cost_and_its_stock(self, api):
        """PRD §3.1: "It deliberately leaves `units_reserved` on the retired line
        untouched: those units are still owed back to `units_available` by the
        shipment that reserved them, and they are released by that shipment's own
        cancellation or by its wave's release, so the four-bucket balance of §2.7
        continues to hold on a retired row."

        Design: Difficulty/boundary_precision_check/retired_last_kit_line_empties_the_active_pool_at_zero
        """
        world = self._campaign_whose_only_line_is_retired(api)

        line = validate_success(
            api.get_kit_line(campaign_manager_headers(), world.kit_line_id(0))
        )
        assert line["status"] == "RETIRED"
        assert line["units_available"] == 10
        assert line["units_reserved"] == 0
        assert line["extended_cost_cents"] == 283

    def test_the_campaign_level_sum_drops_to_zero(self, api):
        """PRD §3.1: "The campaign's `kit_assembly_unit_cost_cents` is then the
        plain sum of those already-rounded line values, taken over the campaign's
        `ACTIVE` lines only and evaluated in order of `created_at` ascending with
        `component_sku` ascending as the tie-break. A `RETIRED` line contributes
        neither cost nor reservation."

        Design: Difficulty/boundary_precision_check/retired_last_kit_line_empties_the_active_pool_at_zero
        """
        world = self._campaign_whose_only_line_is_retired(api)
        enrollment = fx.get_enrollment(api, world.enrollment_id(0))

        validate_error(
            api.create_sample_shipment(
                fulfillment_ops_headers(),
                enrollment_id=world.enrollment_id(0),
                fulfillment_wave_id=world.wave_id,
                expected_enrollment_version=enrollment["version"],
                surcharge_cents=0,
            ),
            ERR_CAMPAIGN_KIT_EMPTY,
        )

        campaign = validate_success(
            api.get_campaign(campaign_manager_headers(), world.campaign_id)
        )
        assert campaign["kit_assembly_unit_cost_cents"] == 0
        assert campaign["allocated_sample_count"] == 0
        assert campaign["budget_committed_cents"] == 0

        wave = validate_success(
            api.get_fulfillment_wave(fulfillment_ops_headers(), world.wave_id)
        )
        assert wave["planned_unit_count"] == 0
