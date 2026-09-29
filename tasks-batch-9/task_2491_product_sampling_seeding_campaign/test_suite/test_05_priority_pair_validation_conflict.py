"""Requests that break two ladder rules at once, where only the earlier speaks."""

import pytest

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import fixtures as fx
from test_helpers import (
    campaign_manager_headers,
    fulfillment_ops_headers,
    moderator_a_headers,
)
from test_helpers.api_errors import (
    ERR_CAMPAIGN_BUDGET_EXHAUSTED,
    ERR_CAMPAIGN_NOT_ACCEPTING_ENROLLMENTS,
    ERR_PANELIST_INTEGRITY_HOLD,
    ERR_RETAILER_NOT_IN_CAMPAIGN,
)
from test_helpers.fixtures import KitSpec


SINGLE_HERO_KIT = (KitSpec("HERO-1", "HERO_PRODUCT", 1417, 1, 0.8, 10),)


class TestSuspendedStateBeatsExhaustedBudget:
    """Rung 11 on the campaign status against rung 33 on the budget."""

    @staticmethod
    def _suspended_campaign_that_cannot_afford_a_kit(api):
        """A suspended campaign holding 100 cents against a 754-cent shipment.

        The kit assembles at 454 cents and the center charges 300 of freight, so
        the allocation would need 754 cents from a 100-cent balance while the
        campaign is also out of its sampling status.
        """
        world = fx.sampling_active_campaign(
            api,
            panelist_count=1,
            center_overrides={"freight_cents_per_kit": 300},
            wave_overrides={"planned_capacity_units": 50},
            budget_total_cents=100,
            name="Broke Campaign",
        )
        world.campaign = fx.suspend_campaign(api, world.campaign_id)
        return world

    def test_the_campaign_status_rung_answers_before_the_budget_rung(self, api):
        """PRD §2.5: "Because the campaign-status gate sits at rung 11 and the
        posture gate at rung 16, a request against a campaign in the wrong
        lifecycle status reports `ERR_CAMPAIGN_NOT_ACCEPTING_ENROLLMENTS` even
        when the posture is also unacceptable."

        Design: Difficulty/priority_pair_validation_conflict/suspended_campaign_state_beats_exhausted_budget_on_allocation
        """
        world = self._suspended_campaign_that_cannot_afford_a_kit(api)
        enrollment = fx.get_enrollment(api, world.enrollment_id(0))

        response = api.create_sample_shipment(
            fulfillment_ops_headers(),
            enrollment_id=world.enrollment_id(0),
            fulfillment_wave_id=world.wave_id,
            expected_enrollment_version=enrollment["version"],
            surcharge_cents=0,
        )

        body = validate_error(response, ERR_CAMPAIGN_NOT_ACCEPTING_ENROLLMENTS, 409)
        assert body["error_id"] != ERR_CAMPAIGN_BUDGET_EXHAUSTED

    def test_the_refused_allocation_moves_no_ledger_and_no_units(self, api):
        """PRD §2.5: "Every request is validated against one global, strictly
        ordered ladder of rules, and **the first rule that fails determines the
        response**: no later rule is evaluated, and no later rule's error code
        can appear once an earlier rule has rejected the request."

        Design: Difficulty/priority_pair_validation_conflict/suspended_campaign_state_beats_exhausted_budget_on_allocation
        """
        world = self._suspended_campaign_that_cannot_afford_a_kit(api)
        enrollment = fx.get_enrollment(api, world.enrollment_id(0))

        validate_error(
            api.create_sample_shipment(
                fulfillment_ops_headers(),
                enrollment_id=world.enrollment_id(0),
                fulfillment_wave_id=world.wave_id,
                expected_enrollment_version=enrollment["version"],
                surcharge_cents=0,
            ),
            ERR_CAMPAIGN_NOT_ACCEPTING_ENROLLMENTS,
        )

        campaign = validate_success(
            api.get_campaign(campaign_manager_headers(), world.campaign_id)
        )
        assert campaign["status"] == "SUSPENDED"
        assert campaign["allocated_sample_count"] == 0
        assert campaign["budget_committed_cents"] == 0
        assert campaign["budget_available_cents"] == 100

    def test_no_kit_units_are_reserved_and_the_wave_stays_empty(self, api):
        """PRD §3.6: "The reservation is **all-or-nothing**: the lines are walked
        in that order and the first line whose `units_available` is below its
        `quantity_per_kit` refuses the whole allocation with
        `ERR_KIT_STOCK_INSUFFICIENT`, leaving every kit line untouched. No
        partial reservation is ever written, so a failed allocation is
        indistinguishable from one that never happened."

        Design: Difficulty/priority_pair_validation_conflict/suspended_campaign_state_beats_exhausted_budget_on_allocation
        """
        world = self._suspended_campaign_that_cannot_afford_a_kit(api)
        enrollment = fx.get_enrollment(api, world.enrollment_id(0))

        validate_error(
            api.create_sample_shipment(
                fulfillment_ops_headers(),
                enrollment_id=world.enrollment_id(0),
                fulfillment_wave_id=world.wave_id,
                expected_enrollment_version=enrollment["version"],
                surcharge_cents=0,
            ),
            ERR_CAMPAIGN_NOT_ACCEPTING_ENROLLMENTS,
        )

        hero = validate_success(
            api.get_kit_line(campaign_manager_headers(), world.kit_line_id(0))
        )
        assert hero["units_reserved"] == 0

        wave = validate_success(
            api.get_fulfillment_wave(fulfillment_ops_headers(), world.wave_id)
        )
        assert wave["planned_unit_count"] == 0


class TestIntegrityHoldBeatsUnregisteredRetailer:
    """Rung 14 on the panelist's standing against rung 20 on the retailer."""

    @staticmethod
    def _flagged_panelist_with_live_content(api):
        """An approved review whose author has been flagged by an audit rescore.

        Three siblings share the target's address hash, so the address term
        reaches its full 18 points, and the target's account is seven whole days
        old, so the account-age term adds 22: screening scores 40.0 and passes.
        Moving the target's only diversion case into investigation re-weights the
        address term and adds the live-case term, taking the audit score to 64.0
        and flagging the panelist.
        """
        in_campaign = fx.create_retailer(api, name="BigBox")
        outside_campaign = fx.create_retailer(api, name="SideMart")

        campaign = fx.create_campaign(
            api,
            name="Cluster Campaign",
            objective_type="REVIEW_ACQUISITION",
            syndication_retailer_ids=[in_campaign["id"]],
        )
        kit_lines = fx.build_kit(api, campaign["id"], SINGLE_HERO_KIT)
        fx.open_screening(api, campaign["id"])

        fx.address_cluster_panelists(api, 3, account_opened_at="2026-01-01T00:00:00Z")
        target = fx.create_panelist(
            api, address_hash="H-CLUSTER", account_opened_at="2026-07-25T00:00:00Z"
        )

        enrollment = fx.create_enrollment(api, campaign["id"], target["id"])
        enrollment = fx.screen_enrollment(api, enrollment["id"])
        fx.activate_sampling(api, campaign["id"])

        center = fx.create_center(api, freight_cents_per_kit=300)
        wave = fx.create_wave(api, center["id"], planned_capacity_units=50)
        shipment = fx.allocate_shipment(
            api, enrollment["id"], wave["id"], surcharge_cents=0
        )
        fx.ship_and_deliver(api, wave["id"], shipment["id"])

        review = fx.create_review(api, enrollment["id"], target["id"], headline="Nice kit")
        fx.submit_review(api, review["id"], target["id"])
        review = fx.moderate_review(
            api,
            review["id"],
            "APPROVE",
            headers=moderator_a_headers(),
            moderator_note="disclosure present",
        )

        case = fx.open_diversion_case(
            api,
            target["id"],
            shipment["id"],
            signal_type="ADDRESS_CLUSTER",
            evidence_note="four accounts share one shipping address",
        )
        fx.investigate_case(api, case["id"])

        return {
            "campaign": campaign,
            "kit_lines": kit_lines,
            "target": target,
            "enrollment": enrollment,
            "review": review,
            "in_campaign": in_campaign,
            "outside_campaign": outside_campaign,
        }

    def test_the_safety_rung_answers_before_the_referential_rung(self, api):
        """PRD §2.5: "When the operation publishes panelist content outside the
        platform, that panelist does not have `integrity_status` equal to
        `FLAGGED` — otherwise `ERR_PANELIST_INTEGRITY_HOLD` (403). Applies to
        syndication queueing and syndication dispatch."

        Design: Difficulty/priority_pair_validation_conflict/flagged_panelist_safety_beats_unregistered_retailer_referential_on_syndication
        """
        setup = self._flagged_panelist_with_live_content(api)

        response = api.create_syndication_record(
            campaign_manager_headers(),
            setup["review"]["id"],
            setup["outside_campaign"]["id"],
        )

        body = validate_error(response, ERR_PANELIST_INTEGRITY_HOLD, 403)
        assert body["error_id"] != ERR_RETAILER_NOT_IN_CAMPAIGN

    def test_the_two_fraud_variants_that_produced_the_flag(self, api):
        """PRD §3.3: "The audit total is the 1.5-weighted address term plus the
        account-age term plus the strike term plus the referral term plus the
        velocity term plus the resale term, capped at 100.0, rounded half-up to
        one decimal place, and written to `fraud_risk_score_audit`."

        Design: Difficulty/priority_pair_validation_conflict/flagged_panelist_safety_beats_unregistered_retailer_referential_on_syndication
        """
        setup = self._flagged_panelist_with_live_content(api)

        panelist = validate_success(
            api.get_panelist(moderator_a_headers(), setup["target"]["id"])
        )
        assert panelist["fraud_risk_score_screening"] == pytest.approx(40.0, abs=0.01)
        assert panelist["fraud_risk_score_audit"] == pytest.approx(64.0, abs=0.01)
        assert panelist["integrity_status"] == "FLAGGED"

        enrollment = validate_success(
            api.get_enrollment(campaign_manager_headers(), setup["enrollment"]["id"])
        )
        assert enrollment["screening_status"] == "SCREEN_PASSED"

    def test_the_refused_queue_leaves_no_record_and_no_counter(self, api):
        """PRD §2.10: "`FLAGGED` marks a panelist whose audited fraud score has
        crossed the flagging threshold or who is under live investigation; a
        flagged panelist's content is held out of every outbound retailer feed,
        and any attempt to queue or dispatch it is refused with
        `ERR_PANELIST_INTEGRITY_HOLD`."

        Design: Difficulty/priority_pair_validation_conflict/flagged_panelist_safety_beats_unregistered_retailer_referential_on_syndication
        """
        setup = self._flagged_panelist_with_live_content(api)

        validate_error(
            api.create_syndication_record(
                campaign_manager_headers(),
                setup["review"]["id"],
                setup["outside_campaign"]["id"],
            ),
            ERR_PANELIST_INTEGRITY_HOLD,
        )

        review = validate_success(
            api.get_review_submission(moderator_a_headers(), setup["review"]["id"])
        )
        assert review["status"] == "APPROVED"

        campaign = validate_success(
            api.get_campaign(campaign_manager_headers(), setup["campaign"]["id"])
        )
        assert campaign["syndicated_review_count"] == 0

        _, meta = validate_paginated(
            api.list_syndication_records(
                campaign_manager_headers(), review_submission_id=setup["review"]["id"]
            )
        )
        assert meta["total_count"] == 0
