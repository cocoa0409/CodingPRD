"""Writes whose legality depends on the live state of a *different* record.

Each pair here keeps the target record perfectly valid and moves only the
parent it points at: an offer whose reservation has lapsed, an instruction whose
offer has not cleared, and a claim whose capacity test proves nothing.
"""
import pytest
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_client import api_client
from test_helpers.factories import (
    create_dispatch_instruction_payload,
    create_warranty_claim_payload,
)
from test_helpers.fixtures import (
    ASSET_MANAGER,
    CLAIM_FILER,
    MARKET_OPERATOR,
    TRADER,
    clear_bid,
    completed_test,
    draft_bid,
    hold_reservation,
    lightly_cycled_plant,
    reference_plant,
    refresh_bid,
    refresh_reservation,
    schedule_test,
    set_clock,
    short_warranty_plant,
    submit_bid,
    submitted_bid,
)


class TestOfferSubmissionFollowsItsReservation:
    """A valid DRAFT offer whose reservation was lapsed by another request's sweep."""

    def _world_with_one_lapsed_reservation(self):
        set_clock("2026-08-01T00:00:00Z")
        asset = reference_plant()
        near = hold_reservation(
            asset["id"],
            reserved_mwh=20.0,
            window_start="2026-08-05T00:00:00Z",
            window_end="2026-08-05T08:00:00Z",
        )
        near_offer = draft_bid(
            asset["id"],
            near["id"],
            delivery_start="2026-08-05T01:00:00Z",
            delivery_end="2026-08-05T05:00:00Z",
            offer_mw=20.0,
        )
        far = hold_reservation(
            asset["id"],
            purpose="ANCILLARY",
            reserved_mwh=20.0,
            window_start="2026-08-20T00:00:00Z",
            window_end="2026-08-20T08:00:00Z",
        )
        far_offer = draft_bid(
            asset["id"],
            far["id"],
            market_type="REAL_TIME",
            product="REG_UP",
            delivery_start="2026-08-20T01:00:00Z",
            delivery_end="2026-08-20T05:00:00Z",
            offer_mw=5.0,
        )
        set_clock("2026-08-10T00:00:00Z")
        sweeper = hold_reservation(
            asset["id"],
            reserved_mwh=10.0,
            window_start="2026-09-01T00:00:00Z",
            window_end="2026-09-01T08:00:00Z",
        )
        return {
            "asset": asset,
            "near": near,
            "near_offer": near_offer,
            "far": far,
            "far_offer": far_offer,
            "sweeper": sweeper,
        }

    def test_the_sweep_lapses_only_the_reservation_whose_window_has_passed(self):
        """Creating a third reservation expires the stale one and leaves the future one held.

        PRD: "Every reservation of this asset whose `status` is `HELD` and whose `window_end` is at or before the current logical instant moves to `EXPIRED` with `released_reason` of `WINDOW_EXPIRED`, taken in ascending `window_end` order and, among ties, ascending `created_at`."

        Design: Difficulty/cross_entity_state_dependency/bid_submit_blocked_by_expired_reservation_state
        """
        world = self._world_with_one_lapsed_reservation()

        lapsed = refresh_reservation(world["near"]["id"])
        assert lapsed["status"] == "EXPIRED"
        assert lapsed["released_reason"] == "WINDOW_EXPIRED"
        assert refresh_reservation(world["far"]["id"])["status"] == "HELD"
        assert refresh_reservation(world["sweeper"]["id"])["status"] == "HELD"

    def test_a_draft_offer_on_the_lapsed_reservation_cannot_be_submitted(self):
        """The offer's own state is fine; its backing reservation is what refuses it.

        PRD: "The backing reservation must still be `HELD` and must belong to the same asset."

        Design: Difficulty/cross_entity_state_dependency/bid_submit_blocked_by_expired_reservation_state
        """
        world = self._world_with_one_lapsed_reservation()
        assert world["near_offer"]["status"] == "DRAFT"

        response = api_client.submit_market_bid(world["near_offer"]["id"], TRADER)

        validate_error(response, "ERR_RESERVATION_NOT_HELD")
        assert refresh_bid(world["near_offer"]["id"])["status"] == "DRAFT"

    def test_the_sibling_offer_on_a_still_held_reservation_submits(self):
        """Under the identical asset state the control path succeeds.

        PRD: "On success `submitted_by_user_id` records the acting `X-User-ID` for audit — it is never an ownership gate — and `offer_price_usd_per_mwh` is frozen at its current value and stops tracking the asset's recomputes."

        Design: Difficulty/cross_entity_state_dependency/bid_submit_blocked_by_expired_reservation_state
        """
        world = self._world_with_one_lapsed_reservation()

        submitted = submit_bid(world["far_offer"]["id"])

        assert submitted["status"] == "SUBMITTED"
        assert submitted["submitted_by_user_id"] is not None


class TestInstructionFollowsItsOffer:
    """The same instruction body against a SUBMITTED and then a CLEARED offer."""

    def _submitted_offer(self):
        set_clock("2026-08-10T00:00:00Z")
        asset = reference_plant()
        reservation = hold_reservation(
            asset["id"],
            reserved_mwh=40.0,
            window_start="2026-08-10T12:00:00Z",
            window_end="2026-08-10T20:00:00Z",
        )
        offer = submitted_bid(
            asset["id"],
            reservation["id"],
            delivery_start="2026-08-10T12:00:00Z",
            delivery_end="2026-08-10T16:00:00Z",
            offer_mw=20.0,
        )
        return asset, offer

    def _instruction_body(self, asset, offer):
        return create_dispatch_instruction_payload(
            offer["id"],
            asset["id"],
            instructed_mw=20.0,
            setpoint_start="2026-08-10T14:00:00Z",
            setpoint_end="2026-08-10T15:00:00Z",
        )

    def test_an_instruction_under_a_merely_submitted_offer_is_refused(self):
        """Nothing has cleared yet, so there is no physical order to give.

        PRD: "The referenced offer must be `CLEARED`, or the creation is refused with `ERR_BID_NOT_CLEARED`, and the instruction's `asset_id` must equal that offer's asset, which the scope agreement of §2.6 step 6 enforces."

        Design: Difficulty/cross_entity_state_dependency/dispatch_create_requires_cleared_parent_bid
        """
        asset, offer = self._submitted_offer()
        assert offer["status"] == "SUBMITTED"

        response = api_client.create_dispatch_instruction(
            self._instruction_body(asset, offer), MARKET_OPERATOR
        )

        validate_error(response, "ERR_BID_NOT_CLEARED")
        rows, meta = validate_paginated(
            api_client.list_dispatch_instructions(
                MARKET_OPERATOR, {"bid_id": offer["id"]}
            )
        )
        assert meta["total_count"] == 0
        assert rows == []

    def test_an_award_at_exactly_the_offer_floor_clears_the_offer(self):
        """The offer price is the floor, so a 37.00 award on a 37.00 offer is accepted.

        PRD: "The supplied `cleared_price_usd_per_mwh` must be at least the offer's `offer_price_usd_per_mwh`: the offer price *is* the floor, so an award at exactly the offer price is accepted and one a cent below it is refused with `ERR_CLEARING_PRICE_BELOW_FLOOR` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/dispatch_create_requires_cleared_parent_bid
        """
        asset, offer = self._submitted_offer()

        cleared = clear_bid(
            offer["id"],
            cleared_price_usd_per_mwh=offer["offer_price_usd_per_mwh"],
            cleared_mw=20.0,
        )

        assert offer["offer_price_usd_per_mwh"] == pytest.approx(37.00, abs=0.01)
        assert cleared["status"] == "CLEARED"
        assert cleared["cleared_price_usd_per_mwh"] == pytest.approx(37.00, abs=0.01)

    def test_the_identical_body_succeeds_once_the_offer_has_cleared(self):
        """The check reads live parent state, so clearing unblocks the same request.

        PRD: "A new instruction inherits `direction` from the offer it executes — `DISCHARGE` or `CHARGE` — and starts with `execution_status` of `PENDING`, `scoring_status` of `NOT_SCORED`, `delivered_mwh` of 0.0, `soc_delta_mwh` of 0.0, `telemetry_sample_count` of 0, `non_performance_charge_usd` of 0.0, and `accuracy_score`, `deadband_pct`, `composite_score`, `failure_reason` and `accepted_by_user_id` all null."

        Design: Difficulty/cross_entity_state_dependency/dispatch_create_requires_cleared_parent_bid
        """
        asset, offer = self._submitted_offer()
        api_client.create_dispatch_instruction(
            self._instruction_body(asset, offer), MARKET_OPERATOR
        )
        clear_bid(offer["id"], cleared_price_usd_per_mwh=37.00, cleared_mw=20.0)

        response = api_client.create_dispatch_instruction(
            self._instruction_body(asset, offer), MARKET_OPERATOR
        )

        instruction = validate_success(response, 201)
        assert instruction["execution_status"] == "PENDING"
        assert instruction["direction"] == "DISCHARGE"
        assert instruction["expected_energy_mwh"] == pytest.approx(20.0, abs=0.01)


class TestClaimFollowsItsCapacityTest:
    """Three probes: a completed-but-untriggered test, a scheduled test, a triggered one."""

    def _two_tested_plants(self):
        set_clock("2026-08-01T00:00:00Z")
        healthy = short_warranty_plant()
        healthy_test = completed_test(
            healthy["id"],
            scheduled_date="2026-08-01T00:00:00Z",
            measured_capacity_mwh=90.0,
        )
        degraded = lightly_cycled_plant()
        degraded_test = completed_test(
            degraded["id"],
            scheduled_date="2026-08-01T00:00:00Z",
            measured_capacity_mwh=90.0,
        )
        future_test = schedule_test(
            degraded["id"], scheduled_date="2026-08-15T00:00:00Z"
        )
        return {
            "healthy": healthy,
            "healthy_test": healthy_test,
            "degraded": degraded,
            "degraded_test": degraded_test,
            "future_test": future_test,
        }

    def test_a_completed_test_that_met_its_expectation_triggers_nothing(self):
        """Measured health above the expectation leaves the trigger flag false.

        PRD: "`warranty_claim_triggered` is true when `soh_deficit_pct` is at least 1.00 percentage point, inclusive at the boundary."

        Design: Difficulty/cross_entity_state_dependency/warranty_claim_requires_completed_and_triggered_capacity_test
        """
        world = self._two_tested_plants()

        healthy_test = world["healthy_test"]
        assert healthy_test["status"] == "COMPLETED"
        assert healthy_test["expected_soh_pct"] == pytest.approx(80.00, abs=0.01)
        assert healthy_test["measured_soh_pct"] == pytest.approx(90.00, abs=0.01)
        assert healthy_test["soh_deficit_pct"] == pytest.approx(0.00, abs=0.01)
        assert healthy_test["warranty_claim_triggered"] is False

    def test_a_claim_citing_an_untriggered_test_is_refused(self):
        """The test is COMPLETED, but it evidences no shortfall.

        PRD: "The cited test must have `status` `COMPLETED` and `warranty_claim_triggered` true, and no other claim in `DRAFT`, `SUBMITTED`, `APPROVED` or `REMEDIED` may already cite it; any of those failures is refused with `ERR_NO_WARRANTY_TRIGGER` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/warranty_claim_requires_completed_and_triggered_capacity_test
        """
        world = self._two_tested_plants()

        response = api_client.create_warranty_claim(
            create_warranty_claim_payload(
                world["healthy"]["id"], world["healthy_test"]["id"]
            ),
            CLAIM_FILER,
        )

        validate_error(response, "ERR_NO_WARRANTY_TRIGGER")

    def test_a_claim_citing_a_merely_scheduled_test_is_refused(self):
        """A test that has not run cannot be a claim's evidence either.

        PRD: "The cited test must have `status` `COMPLETED` and `warranty_claim_triggered` true, and no other claim in `DRAFT`, `SUBMITTED`, `APPROVED` or `REMEDIED` may already cite it; any of those failures is refused with `ERR_NO_WARRANTY_TRIGGER` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/warranty_claim_requires_completed_and_triggered_capacity_test
        """
        world = self._two_tested_plants()
        assert world["future_test"]["status"] == "SCHEDULED"

        response = api_client.create_warranty_claim(
            create_warranty_claim_payload(
                world["degraded"]["id"], world["future_test"]["id"]
            ),
            CLAIM_FILER,
        )

        validate_error(response, "ERR_NO_WARRANTY_TRIGGER")

    def test_a_claim_citing_the_triggered_test_is_drafted_with_its_deficit(self):
        """The one test that satisfies both halves of the condition supports a claim.

        PRD: "A drafted claim copies `claimed_shortfall_pct` from the cited test's `soh_deficit_pct`, starts with `status` `DRAFT`, records `created_by_user_id` as the acting identifier, leaves `submitted_by_user_id`, `adjudicated_by_user_id`, `remedy_energy_add_mwh`, `remedy_install_date`, `remedy_outage_days` and `denial_reason` null, and returns HTTP 201."

        Design: Difficulty/cross_entity_state_dependency/warranty_claim_requires_completed_and_triggered_capacity_test
        """
        world = self._two_tested_plants()
        degraded_test = world["degraded_test"]
        assert degraded_test["warranty_claim_triggered"] is True
        assert degraded_test["soh_deficit_pct"] == pytest.approx(2.10, abs=0.01)

        response = api_client.create_warranty_claim(
            create_warranty_claim_payload(
                world["degraded"]["id"], degraded_test["id"]
            ),
            CLAIM_FILER,
        )

        claim = validate_success(response, 201)
        assert claim["status"] == "DRAFT"
        assert claim["claimed_shortfall_pct"] == pytest.approx(2.10, abs=0.01)
        assert claim["submitted_by_user_id"] is None
        assert claim["adjudicated_by_user_id"] is None

    def test_only_the_triggered_plant_carries_a_claim(self):
        """Two refused filings leave the healthy plant's claim list empty.

        PRD: "Checks run in a fixed order, and the first failing check decides the response; no later check runs, and no partial write survives a rejection."

        Design: Difficulty/cross_entity_state_dependency/warranty_claim_requires_completed_and_triggered_capacity_test
        """
        world = self._two_tested_plants()
        api_client.create_warranty_claim(
            create_warranty_claim_payload(
                world["healthy"]["id"], world["healthy_test"]["id"]
            ),
            CLAIM_FILER,
        )
        api_client.create_warranty_claim(
            create_warranty_claim_payload(
                world["degraded"]["id"], world["future_test"]["id"]
            ),
            CLAIM_FILER,
        )
        api_client.create_warranty_claim(
            create_warranty_claim_payload(
                world["degraded"]["id"], world["degraded_test"]["id"]
            ),
            CLAIM_FILER,
        )

        _, healthy_meta = validate_paginated(
            api_client.list_warranty_claims(
                ASSET_MANAGER, {"asset_id": world["healthy"]["id"]}
            )
        )
        _, degraded_meta = validate_paginated(
            api_client.list_warranty_claims(
                ASSET_MANAGER, {"asset_id": world["degraded"]["id"]}
            )
        )
        assert healthy_meta["total_count"] == 0
        assert degraded_meta["total_count"] == 1
