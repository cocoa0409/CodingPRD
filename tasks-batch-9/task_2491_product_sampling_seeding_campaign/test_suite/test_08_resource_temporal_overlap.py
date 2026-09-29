"""Interval arithmetic over a contended resource, at the touching instant."""

import pytest

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import fixtures as fx
from test_helpers import (
    campaign_manager_headers,
    fulfillment_ops_headers,
    moderator_a_headers,
)
from test_helpers.api_errors import (
    ERR_CENTER_CAPACITY_EXCEEDED,
    ERR_WAVE_CAPACITY_EXCEEDED,
)
from test_helpers.fixtures import KitSpec


COOLDOWN_KIT = (KitSpec("HERO-C", "HERO_PRODUCT", 1000, 1, 0.0, 10),)
FOUR_UNIT_KIT = (KitSpec("HERO-4", "HERO_PRODUCT", 1417, 4, 0.8, 20),)


class TestPanelistCooldownClosedInterval:
    """The prior campaign's window plus its fourteen-day trailing buffer."""

    @staticmethod
    def _one_panelist_across_three_windows(api):
        """A panelist passed into a June campaign and pending in two July ones.

        The June campaign runs to 2026-06-30, so with the two-week buffer it
        occupies through 2026-07-14T00:00:00Z inclusive. The touching candidate
        starts on exactly that instant and the clear candidate one second later,
        which is the only difference between them.
        """
        panelist = fx.create_panelist(api)

        prior = fx.screening_open_campaign(
            api,
            kit_specs=COOLDOWN_KIT,
            name="Cooldown Prior",
            sampling_window_start="2026-06-01T00:00:00Z",
            sampling_window_end="2026-06-30T00:00:00Z",
        )
        occupying = fx.create_enrollment(api, prior.campaign_id, panelist["id"])
        occupying = fx.screen_enrollment(api, occupying["id"])

        touching = fx.screening_open_campaign(
            api,
            kit_specs=COOLDOWN_KIT,
            name="Cooldown Touching",
            sampling_window_start="2026-07-14T00:00:00Z",
            sampling_window_end="2026-08-31T00:00:00Z",
        )
        touching_enrollment = fx.create_enrollment(
            api, touching.campaign_id, panelist["id"]
        )

        clear = fx.screening_open_campaign(
            api,
            kit_specs=COOLDOWN_KIT,
            name="Cooldown Clear",
            sampling_window_start="2026-07-14T00:00:01Z",
            sampling_window_end="2026-08-31T00:00:00Z",
        )
        clear_enrollment = fx.create_enrollment(api, clear.campaign_id, panelist["id"])

        return {
            "panelist": panelist,
            "occupying": occupying,
            "touching": touching,
            "touching_enrollment": touching_enrollment,
            "clear": clear,
            "clear_enrollment": clear_enrollment,
        }

    def test_a_candidate_touching_the_buffer_end_collides(self, api):
        """PRD §3.4: "Because both intervals are closed, touching at a single
        instant counts as a collision: a candidate starting at exactly the prior
        campaign's window end plus 14 days conflicts, while a candidate starting
        one second later does not."

        Design: Difficulty/resource_temporal_overlap/panelist_cooldown_closed_interval_with_trailing_buffer
        """
        setup = self._one_panelist_across_three_windows(api)

        screened = validate_success(
            api.screen_enrollment(
                campaign_manager_headers(), setup["touching_enrollment"]["id"]
            )
        )

        assert screened["screening_status"] == "SCREEN_FAILED"
        assert screened["screening_failure_reason"] == "COOLDOWN_CONFLICT"
        assert screened["screen_attempt_count"] == 1

    def test_a_candidate_one_second_past_the_buffer_passes(self, api):
        """PRD §3.4: "Every other enrollment of the same panelist whose
        `screening_status` is `SCREEN_PASSED` occupies its own campaign's sampling
        window extended by a two-week trailing exclusivity buffer — that is, from
        that campaign's `sampling_window_start` through its `sampling_window_end`
        plus 14 days, inclusive at both ends."

        Design: Difficulty/resource_temporal_overlap/panelist_cooldown_closed_interval_with_trailing_buffer
        """
        setup = self._one_panelist_across_three_windows(api)

        validate_success(
            api.screen_enrollment(
                campaign_manager_headers(), setup["touching_enrollment"]["id"]
            )
        )
        screened = validate_success(
            api.screen_enrollment(
                campaign_manager_headers(), setup["clear_enrollment"]["id"]
            )
        )

        assert screened["screening_status"] == "SCREEN_PASSED"
        assert screened["screening_failure_reason"] is None

    def test_neither_outcome_is_explained_by_the_fraud_threshold(self, api):
        """PRD §3.4: "Past those gates the operation always succeeds as an HTTP
        200 — **a failed screen is not an error response.** It is a 200 whose
        returned enrollment carries `screening_status` `SCREEN_FAILED` and a
        `screening_failure_reason`."

        Design: Difficulty/resource_temporal_overlap/panelist_cooldown_closed_interval_with_trailing_buffer
        """
        setup = self._one_panelist_across_three_windows(api)

        validate_success(
            api.screen_enrollment(
                campaign_manager_headers(), setup["touching_enrollment"]["id"]
            )
        )
        validate_success(
            api.screen_enrollment(
                campaign_manager_headers(), setup["clear_enrollment"]["id"]
            )
        )

        panelist = validate_success(
            api.get_panelist(moderator_a_headers(), setup["panelist"]["id"])
        )
        assert panelist["fraud_risk_score_screening"] == pytest.approx(0.0, abs=0.01)

        occupying = validate_success(
            api.get_enrollment(campaign_manager_headers(), setup["occupying"]["id"])
        )
        assert occupying["screening_status"] == "SCREEN_PASSED"

        touching_campaign = validate_success(
            api.get_campaign(campaign_manager_headers(), setup["touching"].campaign_id)
        )
        clear_campaign = validate_success(
            api.get_campaign(campaign_manager_headers(), setup["clear"].campaign_id)
        )
        assert touching_campaign["enrollment_count"] == 1
        assert clear_campaign["enrollment_count"] == 1


class TestCenterAggregateCapacityHalfOpenWindows:
    """One center's daily picker pool shared by every overlapping wave."""

    @staticmethod
    def _three_waves_at_one_tight_center(api):
        """A six-unit center holding one four-unit allocation in its first wave.

        The second wave starts exactly where the first ends, so half-open
        intervals leave them independent. The third wave sits strictly inside the
        first, so it inherits those four occupied units even though its own
        ceiling is ten.
        """
        world = fx.sampling_active_campaign(
            api,
            panelist_count=3,
            kit_specs=FOUR_UNIT_KIT,
            center_overrides={"daily_pick_capacity_units": 6, "freight_cents_per_kit": 100},
            wave_overrides={
                "window_start": "2026-08-01T00:00:00Z",
                "window_end": "2026-08-02T00:00:00Z",
                "planned_capacity_units": 4,
            },
            name="Center Capacity",
        )
        adjacent = fx.create_wave(
            api,
            world.center_id,
            window_start="2026-08-02T00:00:00Z",
            window_end="2026-08-03T00:00:00Z",
            planned_capacity_units=4,
        )
        nested = fx.create_wave(
            api,
            world.center_id,
            window_start="2026-08-01T12:00:00Z",
            window_end="2026-08-01T18:00:00Z",
            planned_capacity_units=10,
        )
        world.waves.extend([adjacent, nested])
        world.shipments.append(
            fx.allocate_shipment(
                api, world.enrollment_id(0), world.wave_id, surcharge_cents=0
            )
        )
        return world

    def test_an_adjacent_wave_inherits_no_occupied_units(self, api):
        """PRD §3.5: "As §2.6 sets out, a wave's interval is half-open — the start
        instant belongs to the wave and the end instant does not — so two waves
        that meet exactly, where one's `window_end` equals the next one's
        `window_start`, do not overlap and never compete for the same capacity."

        Design: Difficulty/resource_temporal_overlap/center_aggregate_capacity_half_open_windows
        """
        world = self._three_waves_at_one_tight_center(api)
        candidate = fx.get_enrollment(api, world.enrollment_id(1))

        adjacent = validate_success(
            api.create_sample_shipment(
                fulfillment_ops_headers(),
                enrollment_id=world.enrollment_id(1),
                fulfillment_wave_id=world.waves[1]["id"],
                expected_enrollment_version=candidate["version"],
                surcharge_cents=0,
            ),
            201,
        )

        assert adjacent["status"] == "ALLOCATED"
        assert adjacent["kit_unit_total"] == 4
        assert adjacent["committed_cost_cents"] == 1234

        campaign = validate_success(
            api.get_campaign(campaign_manager_headers(), world.campaign_id)
        )
        assert campaign["kit_assembly_unit_cost_cents"] == 1134

    def test_a_nested_wave_is_refused_by_the_center_pool_not_its_own(self, api):
        """PRD §3.5: "The system collects every wave of the same
        `fulfillment_center_id` whose `status` is `PLANNED` or `LOCKED` and whose
        half-open interval overlaps the target wave's — that is, whose
        `window_start` is strictly before the target's `window_end` and whose
        `window_end` is strictly after the target's `window_start`, a set that
        always includes the target wave itself — sums their `planned_unit_count`
        values, adds the kit units the new shipment would consume, and compares
        the total against the center's `daily_pick_capacity_units`."

        Design: Difficulty/resource_temporal_overlap/center_aggregate_capacity_half_open_windows
        """
        world = self._three_waves_at_one_tight_center(api)
        second = fx.get_enrollment(api, world.enrollment_id(1))
        validate_success(
            api.create_sample_shipment(
                fulfillment_ops_headers(),
                enrollment_id=world.enrollment_id(1),
                fulfillment_wave_id=world.waves[1]["id"],
                expected_enrollment_version=second["version"],
                surcharge_cents=0,
            ),
            201,
        )

        third = fx.get_enrollment(api, world.enrollment_id(2))
        body = validate_error(
            api.create_sample_shipment(
                fulfillment_ops_headers(),
                enrollment_id=world.enrollment_id(2),
                fulfillment_wave_id=world.waves[2]["id"],
                expected_enrollment_version=third["version"],
                surcharge_cents=0,
            ),
            ERR_CENTER_CAPACITY_EXCEEDED,
            422,
        )
        assert body["error_id"] != ERR_WAVE_CAPACITY_EXCEEDED

    def test_the_two_accepted_allocations_are_all_that_the_ledger_holds(self, api):
        """PRD §3.5: "Two sibling waves at the same center that overlap in time
        therefore share one pool of picker capacity: each may be individually
        under its own `planned_capacity_units` and still be jointly refused."

        Design: Difficulty/resource_temporal_overlap/center_aggregate_capacity_half_open_windows
        """
        world = self._three_waves_at_one_tight_center(api)
        second = fx.get_enrollment(api, world.enrollment_id(1))
        validate_success(
            api.create_sample_shipment(
                fulfillment_ops_headers(),
                enrollment_id=world.enrollment_id(1),
                fulfillment_wave_id=world.waves[1]["id"],
                expected_enrollment_version=second["version"],
                surcharge_cents=0,
            ),
            201,
        )
        third = fx.get_enrollment(api, world.enrollment_id(2))
        validate_error(
            api.create_sample_shipment(
                fulfillment_ops_headers(),
                enrollment_id=world.enrollment_id(2),
                fulfillment_wave_id=world.waves[2]["id"],
                expected_enrollment_version=third["version"],
                surcharge_cents=0,
            ),
            ERR_CENTER_CAPACITY_EXCEEDED,
        )

        ops = fulfillment_ops_headers()
        first_wave = validate_success(api.get_fulfillment_wave(ops, world.waves[0]["id"]))
        adjacent_wave = validate_success(
            api.get_fulfillment_wave(ops, world.waves[1]["id"])
        )
        nested_wave = validate_success(
            api.get_fulfillment_wave(ops, world.waves[2]["id"])
        )
        assert first_wave["planned_unit_count"] == 4
        assert adjacent_wave["planned_unit_count"] == 4
        assert nested_wave["planned_unit_count"] == 0

        campaign = validate_success(
            api.get_campaign(campaign_manager_headers(), world.campaign_id)
        )
        assert campaign["allocated_sample_count"] == 2
        assert campaign["budget_committed_cents"] == 2468

        line = validate_success(
            api.get_kit_line(campaign_manager_headers(), world.kit_line_id(0))
        )
        assert line["units_reserved"] == 8
        assert line["units_available"] == 12

        refused = validate_success(
            api.get_enrollment(campaign_manager_headers(), world.enrollment_id(2))
        )
        assert refused["obligation_status"] == "NONE"
