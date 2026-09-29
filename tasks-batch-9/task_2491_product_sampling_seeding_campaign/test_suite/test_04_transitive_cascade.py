"""Server-run propagation chains whose later hops depend on earlier hops."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import fixtures as fx
from test_helpers import (
    assert_instant,
    campaign_manager_headers,
    fulfillment_ops_headers,
    moderator_a_headers,
    moderator_b_headers,
)
from test_helpers.fixtures import KitSpec


SINGLE_HERO_KIT = (KitSpec("HERO-1", "HERO_PRODUCT", 1417, 1, 0.8, 10),)


class TestSubstantiationCascade:
    """Four hops out from one compliance decision to live retailer content."""

    @staticmethod
    def _live_content_under_investigation(api):
        """A delivered sample whose review is live at a retailer, case pending.

        The panelist's only live case scores the audit variant at 15.0, well
        under the flagging threshold, so their standing is still CLEAR when the
        case is substantiated and every standing change observed afterwards is
        the cascade's own work.
        """
        return fx.investigating_case_world(
            api,
            kit_specs=SINGLE_HERO_KIT,
            center_overrides={"freight_cents_per_kit": 300},
            wave_overrides={"planned_capacity_units": 50},
            objective_type="REVIEW_ACQUISITION",
            name="Cascade Campaign",
            evidence_note="kit listed for resale two days after delivery",
        )

    def test_the_ban_hop_revokes_screening_but_spares_a_fulfilled_obligation(self, api):
        """PRD §3.9: "The cascade then runs: the panelist's `diversion_strikes`
        increases by 1 and their `integrity_status` becomes `BANNED`; because
        they are banned, every enrollment of theirs whose `screening_status` is
        `PENDING_SCREEN` or `SCREEN_PASSED` moves to the terminal
        `SCREEN_REVOKED` and its `obligation_status` becomes `FORFEITED` unless
        it is already `REVIEW_FULFILLED`;"

        Design: Difficulty/transitive_cascade/substantiation_bans_panelist_revokes_enrollment_retracts_review_requests_takedown
        """
        bundle = self._live_content_under_investigation(api)
        world = bundle["world"]

        case = validate_success(
            api.substantiate_diversion_case(moderator_b_headers(), bundle["case"]["id"])
        )
        assert case["status"] == "SUBSTANTIATED"
        assert_instant(case["substantiated_at"], "2026-08-01T00:00:00Z", "substantiated_at")

        panelist = validate_success(
            api.get_panelist(moderator_a_headers(), world.panelist_id(0))
        )
        assert panelist["integrity_status"] == "BANNED"
        assert panelist["diversion_strikes"] == 1

        enrollment = validate_success(
            api.get_enrollment(campaign_manager_headers(), world.enrollment_id(0))
        )
        assert enrollment["screening_status"] == "SCREEN_REVOKED"
        assert enrollment["obligation_status"] == "REVIEW_FULFILLED"

    def test_the_retraction_hop_reaches_the_already_dispatched_record(self, api):
        """PRD §3.9: "because those enrollments are revoked, every review of
        theirs in `SUBMITTED` or `APPROVED` moves to the terminal `RETRACTED`,
        with the campaign's `approved_review_count` decreasing by 1 for each
        review that was `APPROVED`; and because those reviews are retracted,
        every `SYNDICATED` syndication record of theirs moves to
        `TAKEDOWN_REQUESTED`, with the campaign's `syndicated_review_count`
        decreasing by 1 for each."

        Design: Difficulty/transitive_cascade/substantiation_bans_panelist_revokes_enrollment_retracts_review_requests_takedown
        """
        bundle = self._live_content_under_investigation(api)
        world = bundle["world"]

        validate_success(
            api.substantiate_diversion_case(moderator_b_headers(), bundle["case"]["id"])
        )

        review = validate_success(
            api.get_review_submission(moderator_a_headers(), bundle["review"]["id"])
        )
        assert review["status"] == "RETRACTED"

        record = validate_success(
            api.get_syndication_record(
                campaign_manager_headers(), bundle["syndication"]["id"]
            )
        )
        assert record["status"] == "TAKEDOWN_REQUESTED"
        assert_instant(record["takedown_requested_at"], "2026-08-01T00:00:00Z", "takedown_requested_at")

        campaign = validate_success(
            api.get_campaign(campaign_manager_headers(), world.campaign_id)
        )
        assert campaign["approved_review_count"] == 0
        assert campaign["syndicated_review_count"] == 0

    def test_the_direct_effect_freezes_the_campaign_posture(self, api):
        """PRD §2.9: "the posture is `FROZEN` when the diversion rate is at least
        0.2, or when `substantiated_diversion_count` is at least 5;"

        Design: Difficulty/transitive_cascade/substantiation_bans_panelist_revokes_enrollment_retracts_review_requests_takedown
        """
        bundle = self._live_content_under_investigation(api)
        world = bundle["world"]

        validate_success(
            api.substantiate_diversion_case(moderator_b_headers(), bundle["case"]["id"])
        )

        campaign = validate_success(
            api.get_campaign(campaign_manager_headers(), world.campaign_id)
        )
        assert campaign["substantiated_diversion_count"] == 1
        assert campaign["delivered_sample_count"] == 1
        assert campaign["compliance_posture"] == "FROZEN"


class TestCancellationCompensatingChain:
    """Three hops back from a cancelled shipment to the campaign ledger."""

    @staticmethod
    def _locked_wave_holding_one_allocation(api):
        """One allocated shipment inside a wave that has just been locked.

        The three-line kit reserves four units and the shipment commits
        454 + 300 = 754 cents, so the wave's planned count is exactly the kit's
        unit total and cancelling it must drive that count to zero.
        """
        world = fx.allocated_sample_world(
            api,
            panelist_count=1,
            surcharges=[0],
            center_overrides={"freight_cents_per_kit": 300},
            wave_overrides={"planned_capacity_units": 20},
            name="Compensating Campaign",
        )
        fx.lock_wave(api, world.wave_id)
        return world

    def test_cancellation_returns_every_reserved_unit_to_available(self, api):
        """PRD §3.6: "the mapped units in `reserved_line_units` go back from
        `units_reserved` to `units_available` on each kit line; because those
        units are no longer reserved, the wave's `planned_unit_count` falls by
        `kit_unit_total`, and a `LOCKED` wave whose count thereby reaches zero
        returns to `PLANNED`;"

        Design: Difficulty/transitive_cascade/cancel_releases_kit_units_unlocks_wave_and_uncommits_budget
        """
        world = self._locked_wave_holding_one_allocation(api)
        manager = campaign_manager_headers()

        cancelled = validate_success(
            api.cancel_sample_shipment(fulfillment_ops_headers(), world.shipment_id(0))
        )
        assert cancelled["status"] == "CANCELLED"

        hero = validate_success(api.get_kit_line(manager, world.kit_line_id(0)))
        accessory = validate_success(api.get_kit_line(manager, world.kit_line_id(1)))
        insert = validate_success(api.get_kit_line(manager, world.kit_line_id(2)))

        assert hero["units_available"] == 10
        assert hero["units_reserved"] == 0
        assert accessory["units_available"] == 20
        assert accessory["units_reserved"] == 0
        assert insert["units_available"] == 10
        assert insert["units_reserved"] == 0

    def test_the_wave_unlocks_itself_once_its_planned_count_reaches_zero(self, api):
        """PRD §2.11: "A state change the server performs as part of a chain is
        not a client-visible transition endpoint: the wave unlock that returns a
        wave from `LOCKED` to `PLANNED`, the enrollment revocation to
        `SCREEN_REVOKED`, the review retraction to `RETRACTED` and the
        syndication takedown to `TAKEDOWN_REQUESTED` all happen only as cascade
        hops and can never be requested directly."

        Design: Difficulty/transitive_cascade/cancel_releases_kit_units_unlocks_wave_and_uncommits_budget
        """
        world = self._locked_wave_holding_one_allocation(api)

        validate_success(
            api.cancel_sample_shipment(fulfillment_ops_headers(), world.shipment_id(0))
        )

        wave = validate_success(
            api.get_fulfillment_wave(fulfillment_ops_headers(), world.wave_id)
        )
        assert wave["planned_unit_count"] == 0
        assert wave["status"] == "PLANNED"
        assert wave["shipped_unit_count"] == 0

    def test_the_snapshotted_commitment_moves_back_to_the_available_balance(self, api):
        """PRD §3.6: "because the wave's planned units changed, the campaign's
        `allocated_sample_count` falls by 1, exactly the shipment's snapshotted
        `committed_cost_cents` moves back from `budget_committed_cents` to
        `budget_available_cents`, and `cost_per_sample_provisional_cents` is
        refreshed."

        Design: Difficulty/transitive_cascade/cancel_releases_kit_units_unlocks_wave_and_uncommits_budget
        """
        world = self._locked_wave_holding_one_allocation(api)

        validate_success(
            api.cancel_sample_shipment(fulfillment_ops_headers(), world.shipment_id(0))
        )

        campaign = validate_success(
            api.get_campaign(campaign_manager_headers(), world.campaign_id)
        )
        assert campaign["allocated_sample_count"] == 0
        assert campaign["budget_committed_cents"] == 0
        assert campaign["budget_available_cents"] == 1000000
        assert campaign["cost_per_sample_provisional_cents"] == 0
