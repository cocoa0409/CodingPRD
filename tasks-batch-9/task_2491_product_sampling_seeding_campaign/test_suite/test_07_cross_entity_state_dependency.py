"""Writes gated by the state of a different row than the one being written."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import fixtures as fx
from test_helpers import (
    campaign_manager_headers,
    fulfillment_ops_headers,
    moderator_a_headers,
)
from test_helpers.api_errors import (
    ERR_ENROLLMENT_NOT_ELIGIBLE_FOR_REVIEW,
    ERR_INVALID_WAVE_STATE,
)
from test_helpers.fixtures import KitSpec


SINGLE_HERO_KIT = (KitSpec("HERO-1", "HERO_PRODUCT", 1417, 1, 0.8, 10),)


class TestAllocationGatedByTheWaveState:
    """A brand-new shipment refused by the wave's status alone."""

    @staticmethod
    def _locked_wave_with_a_second_candidate(api):
        """One allocated shipment in a locked wave and a spare screened enrollment.

        Wave capacity is fifty units and the center allows a hundred a day, so
        the second candidate clears both ceilings, and it holds fresh stock,
        budget and a current enrollment version too.
        """
        world = fx.sampling_active_campaign(
            api,
            panelist_count=2,
            center_overrides={"freight_cents_per_kit": 300},
            wave_overrides={"planned_capacity_units": 50},
            name="Locked Wave",
        )
        world.shipments.append(
            fx.allocate_shipment(
                api, world.enrollment_id(0), world.wave_id, surcharge_cents=0
            )
        )
        fx.lock_wave(api, world.wave_id)
        return world

    def test_a_locked_wave_refuses_a_further_allocation(self, api):
        """PRD §3.5: "`FulfillmentOps` locks a `PLANNED` wave to `LOCKED`, closing
        it to further allocation; a wave that is not `PLANNED`, or one whose
        `planned_unit_count` is still zero because nothing was ever allocated
        into it, is refused with `ERR_INVALID_WAVE_STATE`."

        Design: Difficulty/cross_entity_state_dependency/shipment_allocation_requires_planned_wave
        """
        world = self._locked_wave_with_a_second_candidate(api)
        candidate = fx.get_enrollment(api, world.enrollment_id(1))

        validate_error(
            api.create_sample_shipment(
                fulfillment_ops_headers(),
                enrollment_id=world.enrollment_id(1),
                fulfillment_wave_id=world.wave_id,
                expected_enrollment_version=candidate["version"],
                surcharge_cents=0,
            ),
            ERR_INVALID_WAVE_STATE,
            409,
        )

        wave = validate_success(
            api.get_fulfillment_wave(fulfillment_ops_headers(), world.wave_id)
        )
        assert wave["status"] == "LOCKED"
        assert wave["planned_unit_count"] == 4

    def test_the_first_allocation_alone_holds_the_ledger_and_the_units(self, api):
        """PRD §3.6: "The wave's `planned_unit_count` then grows by
        `kit_unit_total` and its `version` by 1; the campaign's
        `allocated_sample_count` grows by 1, its
        `cost_per_sample_provisional_cents` is refreshed and its `version` grows
        by 1; and the enrollment's `version` grows by 1, which is what makes a
        second allocation attempt with the same `expected_enrollment_version`
        fail as stale."

        Design: Difficulty/cross_entity_state_dependency/shipment_allocation_requires_planned_wave
        """
        world = self._locked_wave_with_a_second_candidate(api)
        candidate = fx.get_enrollment(api, world.enrollment_id(1))

        validate_error(
            api.create_sample_shipment(
                fulfillment_ops_headers(),
                enrollment_id=world.enrollment_id(1),
                fulfillment_wave_id=world.wave_id,
                expected_enrollment_version=candidate["version"],
                surcharge_cents=0,
            ),
            ERR_INVALID_WAVE_STATE,
        )

        campaign = validate_success(
            api.get_campaign(campaign_manager_headers(), world.campaign_id)
        )
        assert campaign["allocated_sample_count"] == 1
        assert campaign["budget_committed_cents"] == 754

        accessory = validate_success(
            api.get_kit_line(campaign_manager_headers(), world.kit_line_id(1))
        )
        assert accessory["units_reserved"] == 2
        assert accessory["units_available"] == 18

    def test_the_refused_candidate_keeps_an_untouched_obligation_axis(self, api):
        """PRD §3.4: "The obligation axis records what the panelist owes the
        programme: `NONE`, `SAMPLE_SENT`, `REVIEW_DUE`, and the terminal
        `REVIEW_FULFILLED` and `FORFEITED`."

        Design: Difficulty/cross_entity_state_dependency/shipment_allocation_requires_planned_wave
        """
        world = self._locked_wave_with_a_second_candidate(api)
        candidate = fx.get_enrollment(api, world.enrollment_id(1))

        validate_error(
            api.create_sample_shipment(
                fulfillment_ops_headers(),
                enrollment_id=world.enrollment_id(1),
                fulfillment_wave_id=world.wave_id,
                expected_enrollment_version=candidate["version"],
                surcharge_cents=0,
            ),
            ERR_INVALID_WAVE_STATE,
        )

        refreshed = validate_success(
            api.get_enrollment(campaign_manager_headers(), world.enrollment_id(1))
        )
        assert refreshed["obligation_status"] == "NONE"


class TestSubmissionGatedByTheObligationAxis:
    """A review refused by its enrollment's obligation, not by its own state."""

    @staticmethod
    def _draft_behind_a_forfeited_obligation(api):
        """A lost kit leaves a screen-passed enrollment with nothing owed back.

        The draft satisfies attestation, disclosure and the word-count floor, so
        the obligation axis is the only gate left that can refuse it.
        """
        world = fx.allocated_sample_world(
            api,
            panelist_count=1,
            kit_specs=SINGLE_HERO_KIT,
            center_overrides={"freight_cents_per_kit": 300},
            wave_overrides={"planned_capacity_units": 50},
            objective_type="REVIEW_ACQUISITION",
            name="Lost Kit Review",
        )
        fx.lock_wave(api, world.wave_id)
        fx.release_wave(api, world.wave_id)
        fx.report_shipment_lost(api, world.shipment_id(0))

        review = fx.create_review(
            api,
            world.enrollment_id(0),
            world.panelist_id(0),
            headline="Never arrived",
            body_text=(
                "The courier lost my sampling kit so this text only describes "
                "what I expected to receive."
            ),
            star_rating=3,
            disclosure_statement="Sample provided by the brand at no cost.",
        )
        return world, review

    def test_a_forfeited_obligation_refuses_the_submission(self, api):
        """PRD §3.7: "the enrollment's `obligation_status` is `REVIEW_DUE`,
        otherwise `ERR_ENROLLMENT_NOT_ELIGIBLE_FOR_REVIEW`, which is what stops a
        panelist reviewing a sample that was never delivered;"

        Design: Difficulty/cross_entity_state_dependency/review_submission_requires_enrollment_in_review_due
        """
        world, review = self._draft_behind_a_forfeited_obligation(api)

        validate_error(
            api.submit_review(world.panelist_headers(0), review["id"]),
            ERR_ENROLLMENT_NOT_ELIGIBLE_FOR_REVIEW,
            422,
        )

    def test_the_loss_moved_only_the_obligation_axis(self, api):
        """PRD §3.6: "Reporting a loss moves the shipment `SHIPPED → LOST` and
        refreshes `cost_per_sample_final_cents`; it advances the enrollment's
        obligation axis `SAMPLE_SENT → FORFEITED` **only when no other shipment of
        that enrollment is still in `ALLOCATED`, `SHIPPED` or `DELIVERED`** — a
        panelist with a live parallel shipment still owes their review, so the
        obligation stays where it is."

        Design: Difficulty/cross_entity_state_dependency/review_submission_requires_enrollment_in_review_due
        """
        world, _ = self._draft_behind_a_forfeited_obligation(api)

        enrollment = validate_success(
            api.get_enrollment(campaign_manager_headers(), world.enrollment_id(0))
        )
        assert enrollment["screening_status"] == "SCREEN_PASSED"
        assert enrollment["obligation_status"] == "FORFEITED"
        assert enrollment["review_due_at"] is None

        shipment = validate_success(
            api.get_sample_shipment(fulfillment_ops_headers(), world.shipment_id(0))
        )
        assert shipment["status"] == "LOST"

    def test_the_draft_itself_was_accepted_and_stays_a_draft(self, api):
        """PRD §3.7: "Drafting deliberately enforces almost nothing beyond field
        validity, ownership and the campaign being in `SAMPLING_ACTIVE` or
        `REVIEW_WINDOW` — **obligation eligibility is checked at submission, not
        at drafting**, so a panelist may compose a review before their sample is
        confirmed delivered."

        Design: Difficulty/cross_entity_state_dependency/review_submission_requires_enrollment_in_review_due
        """
        world, review = self._draft_behind_a_forfeited_obligation(api)

        validate_error(
            api.submit_review(world.panelist_headers(0), review["id"]),
            ERR_ENROLLMENT_NOT_ELIGIBLE_FOR_REVIEW,
        )

        stored = validate_success(
            api.get_review_submission(moderator_a_headers(), review["id"])
        )
        assert stored["status"] == "DRAFT"
        assert stored["first_submitted_at"] is None

        campaign = validate_success(
            api.get_campaign(campaign_manager_headers(), world.campaign_id)
        )
        assert campaign["delivered_sample_count"] == 0
        assert campaign["approved_review_count"] == 0
