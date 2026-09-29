"""State machines that branch, run on parallel axes or revisit a state."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import fixtures as fx
from test_helpers import (
    assert_instant,
    campaign_manager_headers,
    fulfillment_ops_headers,
    moderator_a_headers,
    MODERATOR_A_USER_ID,
)
from test_helpers.fixtures import KitSpec


class TestEnrollmentParallelAxes:
    """One enrollment row carrying two state fields that move independently."""

    @staticmethod
    def _allocated_in_a_locked_wave(api):
        world = fx.allocated_sample_world(
            api,
            panelist_count=1,
            surcharges=[0],
            center_overrides={"freight_cents_per_kit": 300},
            wave_overrides={"planned_capacity_units": 50},
            name="Axes Campaign",
        )
        fx.lock_wave(api, world.wave_id)
        return world

    def test_the_obligation_axis_advances_while_screening_stays_pinned(self, api):
        """PRD §3.4: "A shipment that ships, is delivered, is lost and is then
        reshipped drives the obligation axis around a full loop while the
        screening axis sits unchanged at `SCREEN_PASSED` throughout."

        Design: Difficulty/non_linear_state_machine/enrollment_parallel_axes_screening_frozen_while_obligation_advances
        """
        world = self._allocated_in_a_locked_wave(api)
        ops = fulfillment_ops_headers()

        validate_success(api.release_fulfillment_wave(ops, world.wave_id))
        validate_success(api.deliver_sample_shipment(ops, world.shipment_id(0)))

        enrollment = validate_success(
            api.get_enrollment(campaign_manager_headers(), world.enrollment_id(0))
        )
        assert enrollment["screening_status"] == "SCREEN_PASSED"
        assert enrollment["screen_attempt_count"] == 1
        assert enrollment["holdout_flag"] is False
        assert enrollment["obligation_status"] == "REVIEW_DUE"

    def test_delivery_stamps_the_review_due_date_from_the_delivery_instant(self, api):
        """PRD §3.6: "Confirming delivery moves the shipment `SHIPPED →
        DELIVERED`, stamps `delivered_at` from the logical clock, increases the
        campaign's `delivered_sample_count` by 1, refreshes
        `cost_per_sample_final_cents`, re-evaluates `compliance_posture`, and
        advances the enrollment's obligation axis `SAMPLE_SENT → REVIEW_DUE`
        while stamping `review_due_at` as the delivery instant plus the
        campaign's `review_due_days` days."

        Design: Difficulty/non_linear_state_machine/enrollment_parallel_axes_screening_frozen_while_obligation_advances
        """
        world = self._allocated_in_a_locked_wave(api)
        ops = fulfillment_ops_headers()

        validate_success(api.release_fulfillment_wave(ops, world.wave_id))
        shipment = validate_success(
            api.deliver_sample_shipment(ops, world.shipment_id(0))
        )

        assert shipment["status"] == "DELIVERED"
        assert_instant(shipment["shipped_at"], "2026-08-01T00:00:00Z", "shipped_at")
        assert_instant(shipment["delivered_at"], "2026-08-01T00:00:00Z", "delivered_at")

        enrollment = validate_success(
            api.get_enrollment(campaign_manager_headers(), world.enrollment_id(0))
        )
        assert_instant(enrollment["review_due_at"], "2026-08-22T00:00:00Z", "review_due_at")

    def test_release_moves_reserved_units_into_the_shipped_bucket(self, api):
        """PRD §3.6: "Every shipment of the released wave still in `ALLOCATED`
        moves to `SHIPPED` with `shipped_at` stamped from the logical clock; each
        such shipment's mapped units move from `units_reserved` to
        `units_shipped` on every kit line named in its `reserved_line_units`,
        with each line's `version` increased by 1; the wave's
        `shipped_unit_count` takes on the units that just shipped while its
        `planned_unit_count` returns to zero; and each affected enrollment's
        obligation axis advances `NONE → SAMPLE_SENT`."

        Design: Difficulty/non_linear_state_machine/enrollment_parallel_axes_screening_frozen_while_obligation_advances
        """
        world = self._allocated_in_a_locked_wave(api)
        ops = fulfillment_ops_headers()

        wave = validate_success(api.release_fulfillment_wave(ops, world.wave_id))
        validate_success(api.deliver_sample_shipment(ops, world.shipment_id(0)))

        assert wave["status"] == "RELEASED"
        assert wave["planned_unit_count"] == 0
        assert wave["shipped_unit_count"] == 4

        accessory = validate_success(
            api.get_kit_line(campaign_manager_headers(), world.kit_line_id(1))
        )
        assert accessory["units_shipped"] == 2
        assert accessory["units_reserved"] == 0


class TestReviewChangesRequestedCycle:
    """A review re-entering SUBMITTED, a state it already occupied."""

    @staticmethod
    def _review_awaiting_revision(api):
        """A submitted review sent back for changes, with the clock moved on.

        The clock is repositioned to 2026-08-03 before the revision so that a
        reset of the first-submission stamp would be visible.
        """
        world = fx.delivered_sample_world(
            api,
            panelist_count=1,
            kit_specs=(KitSpec("HERO-1", "HERO_PRODUCT", 1417, 1, 0.8, 10),),
            center_overrides={"freight_cents_per_kit": 300},
            wave_overrides={"planned_capacity_units": 50},
            objective_type="REVIEW_ACQUISITION",
            name="Cycle Campaign",
        )
        review = fx.create_review(
            api,
            world.enrollment_id(0),
            world.panelist_id(0),
            headline="Worked well",
            body_text=(
                "This sampling kit arrived quickly and the hero product "
                "performed very well overall"
            ),
            star_rating=5,
        )
        fx.submit_review(api, review["id"], world.panelist_id(0))
        fx.moderate_review(
            api,
            review["id"],
            "REQUEST_CHANGES",
            headers=moderator_a_headers(),
            moderator_note="please name the product explicitly",
        )
        fx.advance_clock(api, "2026-08-03T00:00:00Z")
        return world, review

    def test_revision_returns_the_review_to_submitted_and_counts_the_loop(self, api):
        """PRD §3.7: "the supplied content replaces the stored content wholesale,
        `word_count` is recomputed from the new `body_text`, `revision_count`
        increases by 1, `first_submitted_at` is left untouched, and the review
        returns to `SUBMITTED` with its `version` increased by 1."

        Design: Difficulty/non_linear_state_machine/review_changes_requested_cycle_preserves_first_submitted_at
        """
        world, review = self._review_awaiting_revision(api)

        revised = validate_success(
            api.revise_review(
                world.panelist_headers(0),
                review["id"],
                headline="Worked well, revised",
                body_text=(
                    "The revised sampling kit arrived quickly and the hero "
                    "product performed very well overall today"
                ),
                star_rating=5,
                disclosure_statement="Sample provided by the brand for testing.",
                honest_opinion_attested=True,
            )
        )

        assert revised["status"] == "SUBMITTED"
        assert revised["revision_count"] == 1
        assert revised["word_count"] == 15
        assert revised["headline"] == "Worked well, revised"

    def test_the_first_submission_stamp_survives_the_cycle(self, api):
        """PRD §3.7: "A first submission stamps `first_submitted_at` with the
        logical clock's current instant, and only a first submission does so —
        every later submission of the same review leaves that timestamp exactly
        as it was, which is what makes it a stable anchor for the audit variant's
        review-velocity window in §3.3."

        Design: Difficulty/non_linear_state_machine/review_changes_requested_cycle_preserves_first_submitted_at
        """
        world, review = self._review_awaiting_revision(api)

        revised = validate_success(
            api.revise_review(
                world.panelist_headers(0),
                review["id"],
                headline="Worked well, revised",
                body_text=(
                    "The revised sampling kit arrived quickly and the hero "
                    "product performed very well overall today"
                ),
                star_rating=5,
                disclosure_statement="Sample provided by the brand for testing.",
                honest_opinion_attested=True,
            )
        )

        assert_instant(revised["first_submitted_at"], "2026-08-01T00:00:00Z", "first_submitted_at")
        assert revised["changes_requested_by_user_id"] == MODERATOR_A_USER_ID

    def test_requesting_changes_moves_no_obligation_and_no_counter(self, api):
        """PRD §3.7: "`REQUEST_CHANGES` moves the review `SUBMITTED →
        CHANGES_REQUESTED` and records `changes_requested_by_user_id` from the
        acting moderator. It touches no campaign counter, no posture and no
        obligation axis."

        Design: Difficulty/non_linear_state_machine/review_changes_requested_cycle_preserves_first_submitted_at
        """
        world, review = self._review_awaiting_revision(api)

        validate_success(
            api.revise_review(
                world.panelist_headers(0),
                review["id"],
                headline="Worked well, revised",
                body_text=(
                    "The revised sampling kit arrived quickly and the hero "
                    "product performed very well overall today"
                ),
                star_rating=5,
                disclosure_statement="Sample provided by the brand for testing.",
                honest_opinion_attested=True,
            )
        )

        enrollment = validate_success(
            api.get_enrollment(campaign_manager_headers(), world.enrollment_id(0))
        )
        assert enrollment["obligation_status"] == "REVIEW_DUE"

        campaign = validate_success(
            api.get_campaign(campaign_manager_headers(), world.campaign_id)
        )
        assert campaign["approved_review_count"] == 0
