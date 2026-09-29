"""Business-rule validation: aggregates, conditionals, windows and budgets.

The rules here are the ones a request body cannot show on its face — they
depend on sibling rows, on the plant's posture, or on cumulative counters, so
every test builds the surrounding world before it makes the one call under test.
"""
import pytest
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_client import api_client
from test_helpers.factories import (
    create_capacity_obligation_payload,
    create_dispatch_instruction_payload,
    create_market_bid_payload,
    create_soc_reservation_payload,
    create_warranty_claim_payload,
)
from test_helpers.fixtures import (
    ASSET_MANAGER,
    CLAIM_FILER,
    DISPATCH_DAY_CLOCK,
    MARKET_OPERATOR,
    TRADER,
    cleared_bid,
    commission_asset,
    completed_test,
    draft_bid,
    elevate_asset,
    enrol_obligation,
    file_claim,
    hold_reservation,
    issue_dispatch,
    lightly_cycled_plant,
    provision_asset,
    refresh_asset,
    refresh_bid,
    register_asset,
    set_clock,
    submit_bid,
)


class TestSiblingInstructionsShareOneHold:
    """The reservation is charged for every live sibling, not just the new row."""

    def _cleared_offer_with_two_orders(self):
        set_clock(DISPATCH_DAY_CLOCK)
        asset = provision_asset()
        reservation = hold_reservation(
            asset["id"],
            reserved_mwh=40.0,
            window_start="2026-08-10T12:00:00Z",
            window_end="2026-08-10T20:00:00Z",
        )
        bid = cleared_bid(
            asset["id"],
            reservation["id"],
            cleared_price_usd_per_mwh=45.00,
            cleared_mw=20.0,
            offer_mw=20.0,
            delivery_start="2026-08-10T12:00:00Z",
            delivery_end="2026-08-10T18:00:00Z",
        )
        first = issue_dispatch(
            bid["id"],
            asset["id"],
            instructed_mw=20.0,
            setpoint_start="2026-08-10T13:00:00Z",
            setpoint_end="2026-08-10T14:00:00Z",
        )
        second = issue_dispatch(
            bid["id"],
            asset["id"],
            instructed_mw=20.0,
            setpoint_start="2026-08-10T15:00:00Z",
            setpoint_end="2026-08-10T16:00:00Z",
        )
        return asset, bid, first, second

    def test_two_orders_may_fill_the_hold_exactly(self):
        """Twenty plus twenty megawatt-hours lands on the hold and is admitted.

        PRD: "Summing this instruction's `expected_energy_mwh` with the `expected_energy_mwh` of every sibling instruction on the same reservation whose `execution_status` is `PENDING`, `ACCEPTED`, `EXECUTING` or `COMPLETED`, and rounding the total half up to 3 decimal places, that total must be at most the reservation's `reserved_mwh`; otherwise the creation is refused with `ERR_DISPATCH_EXCEEDS_RESERVATION` (HTTP 422)."

        Design: Corner/validations/sibling_instructions_collectively_exceed_the_reservation
        """
        asset, bid, first, second = self._cleared_offer_with_two_orders()

        assert first["expected_energy_mwh"] == pytest.approx(20.0, abs=0.01)
        assert second["expected_energy_mwh"] == pytest.approx(20.0, abs=0.01)

    def test_a_third_order_breaches_the_aggregated_hold(self):
        """Ten more megawatt-hours would take the running total to fifty.

        PRD: "That energy is charged against what the reservation still holds."

        Design: Corner/validations/sibling_instructions_collectively_exceed_the_reservation
        """
        asset, bid, first, second = self._cleared_offer_with_two_orders()

        response = api_client.create_dispatch_instruction(
            create_dispatch_instruction_payload(
                bid["id"],
                asset["id"],
                instructed_mw=20.0,
                setpoint_start="2026-08-10T17:00:00Z",
                setpoint_end="2026-08-10T17:30:00Z",
            ),
            MARKET_OPERATOR,
        )

        validate_error(response, "ERR_DISPATCH_EXCEEDS_RESERVATION", expected_status=422)

    def test_the_refused_order_is_never_written(self):
        """Only the two admitted orders exist on the offer afterwards.

        PRD: "Failed siblings release their claim and are not counted."

        Design: Corner/validations/sibling_instructions_collectively_exceed_the_reservation
        """
        asset, bid, first, second = self._cleared_offer_with_two_orders()

        api_client.create_dispatch_instruction(
            create_dispatch_instruction_payload(
                bid["id"],
                asset["id"],
                instructed_mw=20.0,
                setpoint_start="2026-08-10T17:00:00Z",
                setpoint_end="2026-08-10T17:30:00Z",
            ),
            MARKET_OPERATOR,
        )

        data, meta = validate_paginated(
            api_client.list_dispatch_instructions(
                MARKET_OPERATOR, params={"bid_id": bid["id"]}
            )
        )
        assert meta["total_count"] == 2
        assert sorted(row["id"] for row in data) == sorted([first["id"], second["id"]])


class TestDerateGateAppliesOnlyWhileElevated:
    """The half-rating ceiling exists only while the plant is derated."""

    def _plant_with_three_drafts(self):
        set_clock(DISPATCH_DAY_CLOCK)
        asset = provision_asset()
        reservation = hold_reservation(
            asset["id"],
            reserved_mwh=40.0,
            window_start="2026-08-10T12:00:00Z",
            window_end="2026-08-10T20:00:00Z",
        )
        full_power = draft_bid(
            asset["id"],
            reservation["id"],
            offer_mw=20.0,
            delivery_start="2026-08-10T12:00:00Z",
            delivery_end="2026-08-10T13:00:00Z",
        )
        repeat = draft_bid(
            asset["id"],
            reservation["id"],
            offer_mw=20.0,
            delivery_start="2026-08-10T14:00:00Z",
            delivery_end="2026-08-10T15:00:00Z",
        )
        half_power = draft_bid(
            asset["id"],
            reservation["id"],
            offer_mw=12.5,
            delivery_start="2026-08-10T16:00:00Z",
            delivery_end="2026-08-10T17:00:00Z",
        )
        return asset, full_power, repeat, half_power

    def test_full_power_submits_while_the_plant_is_normal(self):
        """Twenty megawatts on a twenty-five megawatt plant is ordinary business.

        PRD: "The derate gate — `ERR_ASSET_DERATED` (HTTP 409) — guards exactly two operations, offer submission and dispatch acceptance, and in both it compares the request's power (`offer_mw` or `instructed_mw`) against 50.0 percent of `power_rating_mw`."

        Design: Corner/validations/derate_rule_applies_only_while_safety_state_is_elevated
        """
        asset, full_power, repeat, half_power = self._plant_with_three_drafts()

        submitted = submit_bid(full_power["id"])

        assert submitted["status"] == "SUBMITTED"

    def test_a_warning_event_derates_without_suspending(self):
        """The elevated posture leaves the market axis and the live offer alone.

        PRD: "On the `NORMAL → ELEVATED` transition — a `WARNING`-severity non-runaway event, or a telemetry sample crossing 65.0 degrees Celsius — `market_state` is untouched: an elevated posture derates the plant, it does not suspend it."

        Design: Corner/validations/derate_rule_applies_only_while_safety_state_is_elevated
        """
        asset, full_power, repeat, half_power = self._plant_with_three_drafts()
        submit_bid(full_power["id"])

        event = elevate_asset(asset["id"])

        assert event["imposed_safety_state"] == "ELEVATED"
        plant = refresh_asset(asset["id"])
        assert plant["safety_state"] == "ELEVATED"
        assert plant["market_state"] == "AVAILABLE"
        assert refresh_bid(full_power["id"])["status"] == "SUBMITTED"

    def test_the_identical_offer_is_refused_once_the_plant_is_derated(self):
        """The same twenty megawatts now exceeds half of the rating.

        PRD: "The derate gate — `ERR_ASSET_DERATED` (HTTP 409) — guards exactly two operations, offer submission and dispatch acceptance, and in both it compares the request's power (`offer_mw` or `instructed_mw`) against 50.0 percent of `power_rating_mw`."

        Design: Corner/validations/derate_rule_applies_only_while_safety_state_is_elevated
        """
        asset, full_power, repeat, half_power = self._plant_with_three_drafts()
        submit_bid(full_power["id"])
        elevate_asset(asset["id"])

        response = api_client.submit_market_bid(repeat["id"], TRADER)

        validate_error(response, "ERR_ASSET_DERATED", expected_status=409)
        assert refresh_bid(repeat["id"])["status"] == "DRAFT"

    def test_exactly_half_the_rating_still_submits_while_derated(self):
        """Twelve and a half megawatts sits on the ceiling, which is inclusive.

        PRD: "While the asset's `safety_state` is `ELEVATED` the plant is derated and `offer_mw` must not exceed 50.0 percent of `power_rating_mw`, or the submission is refused with `ERR_ASSET_DERATED` (HTTP 409) — an open warning-severity thermal event does not suspend the market, it shrinks the sellable power."

        Design: Corner/validations/derate_rule_applies_only_while_safety_state_is_elevated
        """
        asset, full_power, repeat, half_power = self._plant_with_three_drafts()
        elevate_asset(asset["id"])

        submitted = submit_bid(half_power["id"])

        assert submitted["status"] == "SUBMITTED"


class TestRampBufferWindowExclusivity:
    """A live offer occupies its delivery window widened by a quarter of an hour."""

    def _incumbent_and_two_challengers(self):
        set_clock(DISPATCH_DAY_CLOCK)
        asset = provision_asset()
        reservation = hold_reservation(
            asset["id"],
            reserved_mwh=40.0,
            window_start="2026-08-10T12:00:00Z",
            window_end="2026-08-10T20:00:00Z",
        )
        incumbent = draft_bid(
            asset["id"],
            reservation["id"],
            offer_mw=20.0,
            delivery_start="2026-08-10T12:00:00Z",
            delivery_end="2026-08-10T13:00:00Z",
        )
        touching = draft_bid(
            asset["id"],
            reservation["id"],
            offer_mw=20.0,
            delivery_start="2026-08-10T13:15:00Z",
            delivery_end="2026-08-10T14:15:00Z",
        )
        clear_of_it = draft_bid(
            asset["id"],
            reservation["id"],
            offer_mw=20.0,
            delivery_start="2026-08-10T13:45:00Z",
            delivery_end="2026-08-10T14:45:00Z",
        )
        submitted = submit_bid(incumbent["id"])
        return asset, submitted, touching, clear_of_it

    def test_the_incumbent_holds_its_buffered_window(self):
        """The submitted offer is the one whose occupancy the others must dodge.

        PRD: "No other offer of the same asset and the same `market_type` whose `status` is `SUBMITTED` or `CLEARED` may occupy the requested delivery window, where occupancy is the closed interval running from 15 minutes before `delivery_start` to 15 minutes after `delivery_end`."

        Design: Corner/validations/bid_window_ramp_buffer_conflicts_at_fifteen_minutes_and_clears_at_sixteen
        """
        asset, incumbent, touching, clear_of_it = self._incumbent_and_two_challengers()

        assert incumbent["status"] == "SUBMITTED"

    def test_an_offer_touching_the_buffer_endpoint_conflicts(self):
        """Starting exactly fifteen minutes after the incumbent still collides.

        PRD: "Because the buffered interval is closed on both sides, two offers that merely touch at an endpoint do conflict, and so do two offers separated by a 15-minute gap; a conflict is refused with `ERR_BID_WINDOW_CONFLICT` (HTTP 409)."

        Design: Corner/validations/bid_window_ramp_buffer_conflicts_at_fifteen_minutes_and_clears_at_sixteen
        """
        asset, incumbent, touching, clear_of_it = self._incumbent_and_two_challengers()

        response = api_client.submit_market_bid(touching["id"], TRADER)

        validate_error(response, "ERR_BID_WINDOW_CONFLICT", expected_status=409)

    def test_a_refused_submission_leaves_the_draft_alive(self):
        """A rejected submission is not a withdrawal.

        PRD: "Submitting an offer whose `status` is not `DRAFT` is refused with `ERR_BID_NOT_DRAFT`."

        Design: Corner/validations/bid_window_ramp_buffer_conflicts_at_fifteen_minutes_and_clears_at_sixteen
        """
        asset, incumbent, touching, clear_of_it = self._incumbent_and_two_challengers()

        api_client.submit_market_bid(touching["id"], TRADER)

        assert refresh_bid(touching["id"])["status"] == "DRAFT"

    def test_an_offer_clear_of_the_ramp_allowance_submits(self):
        """Once the buffered intervals no longer touch, the second offer is free.

        PRD: "Fifteen minutes is the plant's ramp allowance between two market commitments."

        Design: Corner/validations/bid_window_ramp_buffer_conflicts_at_fifteen_minutes_and_clears_at_sixteen
        """
        asset, incumbent, touching, clear_of_it = self._incumbent_and_two_challengers()

        submitted = submit_bid(clear_of_it["id"])

        assert submitted["status"] == "SUBMITTED"


class TestReferenceResolutionPrecedesTheScopeCheck:
    """A scope comparison is impossible until the referenced row is resolved."""

    def test_an_unknown_reservation_reports_the_missing_reference(self):
        """The unresolvable sibling reference decides the code, not the scope rule.

        PRD: "The failing reference decides which of `ERR_ASSET_NOT_FOUND`, `ERR_RESERVATION_NOT_FOUND`, `ERR_BID_NOT_FOUND`, `ERR_DISPATCH_NOT_FOUND` or `ERR_TEST_NOT_FOUND` is returned."

        Design: Corner/validations/body_fk_existence_runs_before_the_scope_check
        """
        set_clock(DISPATCH_DAY_CLOCK)
        asset = provision_asset()

        response = api_client.create_market_bid(
            create_market_bid_payload(asset["id"], NON_EXISTENT_UUID), TRADER
        )

        validate_error(response, "ERR_RESERVATION_NOT_FOUND", expected_status=404)

    def test_the_same_body_succeeds_once_the_reference_resolves(self):
        """The asset in the body was never the problem.

        PRD: "References are resolved in a fixed field order: `asset_id` first, then whichever of `reservation_id`, `bid_id`, `capacity_test_id`, `baseline_test_id` or `source_dispatch_id` the body carries, then `dispatch_id`."

        Design: Corner/validations/body_fk_existence_runs_before_the_scope_check
        """
        set_clock(DISPATCH_DAY_CLOCK)
        asset = provision_asset()
        reservation = hold_reservation(
            asset["id"],
            reserved_mwh=40.0,
            window_start="2026-08-10T12:00:00Z",
            window_end="2026-08-10T20:00:00Z",
        )

        response = api_client.create_market_bid(
            create_market_bid_payload(asset["id"], reservation["id"]), TRADER
        )

        bid = validate_success(response, expected_status=201)
        assert bid["reservation_id"] == reservation["id"]
        assert bid["asset_id"] == asset["id"]


class TestDuplicateProgrammeEnrolment:
    """Uniqueness binds the asset, the programme and the programme year together."""

    def _enrolled_plant(self):
        set_clock(DISPATCH_DAY_CLOCK)
        asset = provision_asset()
        obligation = enrol_obligation(
            asset["id"],
            program_name="PJM RPM",
            program_year=2026,
            committed_mw=20.0,
            availability_hours_required=8000.0,
            penalty_rate_usd_per_mw_hour=150.00,
        )
        return asset, obligation

    def test_the_same_triple_is_refused_rather_than_merged(self):
        """A second enrolment for the same programme year keeps the first intact.

        PRD: "At most one obligation may exist for a given combination of `asset_id`, `program_name` and `program_year`, whatever its status, and a second enrolment for the same triple is refused with `ERR_DUPLICATE_OBLIGATION` (HTTP 409) rather than merged into the first."

        Design: Corner/validations/duplicate_capacity_program_enrolment_rejected
        """
        asset, obligation = self._enrolled_plant()

        response = api_client.create_capacity_obligation(
            create_capacity_obligation_payload(
                asset["id"],
                program_name="PJM RPM",
                program_year=2026,
                committed_mw=15.0,
                availability_hours_required=7000.0,
                penalty_rate_usd_per_mw_hour=120.0,
            ),
            MARKET_OPERATOR,
        )

        validate_error(response, "ERR_DUPLICATE_OBLIGATION", expected_status=409)
        stored = get_success_data(
            api_client.get_capacity_obligation(obligation["id"], ASSET_MANAGER)
        )
        assert stored["committed_mw"] == pytest.approx(20.0, abs=0.01)

    def test_the_next_programme_year_is_still_enrollable(self):
        """The year is part of the key, so 2027 is a different enrolment.

        PRD: "A new obligation is created with `status` `ACTIVE`, `unavailable_hours` 0.0, `accrual_started_at` null, `measured_available_hours` 0.0, `availability_pct` null, `shortfall_hours` 0.0, `penalty_exposure_usd` 0.0, `assessment_mode` null and `derated_committed_mw` null, and returns HTTP 201."

        Design: Corner/validations/duplicate_capacity_program_enrolment_rejected
        """
        asset, obligation = self._enrolled_plant()

        response = api_client.create_capacity_obligation(
            create_capacity_obligation_payload(
                asset["id"],
                program_name="PJM RPM",
                program_year=2027,
                committed_mw=15.0,
                availability_hours_required=7000.0,
                penalty_rate_usd_per_mw_hour=120.0,
            ),
            MARKET_OPERATOR,
        )

        second = validate_success(response, expected_status=201)
        assert second["program_year"] == 2027
        assert second["status"] == "ACTIVE"

    def test_the_plant_ends_up_with_two_enrolments(self):
        """One refusal and one acceptance leave exactly two programme rows.

        PRD: "At most one obligation may exist for a given combination of `asset_id`, `program_name` and `program_year`, whatever its status, and a second enrolment for the same triple is refused with `ERR_DUPLICATE_OBLIGATION` (HTTP 409) rather than merged into the first."

        Design: Corner/validations/duplicate_capacity_program_enrolment_rejected
        """
        asset, obligation = self._enrolled_plant()

        api_client.create_capacity_obligation(
            create_capacity_obligation_payload(
                asset["id"], program_name="PJM RPM", program_year=2026
            ),
            MARKET_OPERATOR,
        )
        enrol_obligation(asset["id"], program_name="PJM RPM", program_year=2027)

        data, meta = validate_paginated(
            api_client.list_capacity_obligations(
                ASSET_MANAGER, params={"asset_id": asset["id"]}
            )
        )
        assert meta["total_count"] == 2
        assert sorted(row["program_year"] for row in data) == [2026, 2027]


class TestClaimFilingWindowBoundary:
    """The thirty-day filing window includes its final day."""

    TEST_DATE = "2026-08-01T00:00:00Z"
    DAY_THIRTY = "2026-08-31T00:00:00Z"
    DAY_THIRTY_ONE = "2026-09-01T00:00:00Z"

    def _plant_with_a_triggered_test(self):
        set_clock(self.TEST_DATE)
        asset = lightly_cycled_plant()
        test = completed_test(
            asset["id"], scheduled_date=self.TEST_DATE, measured_capacity_mwh=90.0
        )
        return asset, test

    def test_filing_on_the_thirtieth_day_passes(self):
        """Thirty elapsed days is inside the window, so the claim is drafted.

        PRD: "Filing is also time-boxed: the current logical instant must be within 30 days of the cited test's `scheduled_date`, inclusive of the final day, so 30 elapsed days passes and 31 fails, and a late filing is refused with `ERR_CLAIM_FILING_WINDOW_EXPIRED` (HTTP 422)."

        Design: Corner/validations/claim_filed_on_day_thirty_passes_and_day_thirty_one_expires
        """
        asset, test = self._plant_with_a_triggered_test()
        assert test["soh_deficit_pct"] == pytest.approx(2.1, abs=0.01)
        assert test["warranty_claim_triggered"] is True

        set_clock(self.DAY_THIRTY)
        claim = file_claim(asset["id"], test["id"])

        assert claim["status"] == "DRAFT"
        assert claim["claimed_shortfall_pct"] == pytest.approx(2.1, abs=0.01)

    def test_filing_on_the_thirty_first_day_expires(self):
        """One day later the same evidence is out of time.

        PRD: "Filing is also time-boxed: the current logical instant must be within 30 days of the cited test's `scheduled_date`, inclusive of the final day, so 30 elapsed days passes and 31 fails, and a late filing is refused with `ERR_CLAIM_FILING_WINDOW_EXPIRED` (HTTP 422)."

        Design: Corner/validations/claim_filed_on_day_thirty_passes_and_day_thirty_one_expires
        """
        asset, test = self._plant_with_a_triggered_test()

        set_clock(self.DAY_THIRTY_ONE)
        response = api_client.create_warranty_claim(
            create_warranty_claim_payload(asset["id"], test["id"]), CLAIM_FILER
        )

        validate_error(
            response, "ERR_CLAIM_FILING_WINDOW_EXPIRED", expected_status=422
        )

    def test_only_the_timely_claim_is_ever_written(self):
        """The expired attempt leaves no row behind for the cited test.

        PRD: "A drafted claim copies `claimed_shortfall_pct` from the cited test's `soh_deficit_pct`, starts with `status` `DRAFT`, records `created_by_user_id` as the acting identifier, leaves `submitted_by_user_id`, `adjudicated_by_user_id`, `remedy_energy_add_mwh`, `remedy_install_date`, `remedy_outage_days` and `denial_reason` null, and returns HTTP 201."

        Design: Corner/validations/claim_filed_on_day_thirty_passes_and_day_thirty_one_expires
        """
        asset, test = self._plant_with_a_triggered_test()

        set_clock(self.DAY_THIRTY_ONE)
        api_client.create_warranty_claim(
            create_warranty_claim_payload(asset["id"], test["id"]), CLAIM_FILER
        )
        set_clock(self.DAY_THIRTY)
        timely = file_claim(asset["id"], test["id"])

        data, meta = validate_paginated(
            api_client.list_warranty_claims(
                ASSET_MANAGER, params={"capacity_test_id": test["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in data] == [timely["id"]]


class TestStaleAssetVersionGuard:
    """A reservation writer must present the asset version it actually read."""

    WINDOW = ("2026-08-10T12:00:00Z", "2026-08-10T20:00:00Z")

    def _commissioned_plant(self):
        set_clock(DISPATCH_DAY_CLOCK)
        registered = register_asset()
        commissioned = commission_asset(registered["id"])
        return registered, commissioned

    def _reservation_request(self, asset_id, version, purpose, reserved_mwh):
        return create_soc_reservation_payload(
            asset_id,
            version,
            purpose=purpose,
            reserved_mwh=reserved_mwh,
            window_start=self.WINDOW[0],
            window_end=self.WINDOW[1],
        )

    def test_an_accepted_hold_bumps_the_version_it_quoted(self):
        """The first write succeeds and invalidates the version it was given.

        PRD: "The request body must carry `expected_asset_version`, a non-optional integer holding the `version` the client last observed on the target storage asset."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_asset_version_on_reservation_create_is_rejected
        """
        registered, commissioned = self._commissioned_plant()
        assert commissioned["version"] > registered["version"]

        response = api_client.create_soc_reservation(
            self._reservation_request(
                commissioned["id"], commissioned["version"], "ENERGY_ARBITRAGE", 40.0
            ),
            TRADER,
        )

        validate_success(response, expected_status=201)
        plant = refresh_asset(commissioned["id"])
        assert plant["version"] == commissioned["version"] + 1
        assert plant["reserved_mwh_total"] == pytest.approx(40.0, abs=0.01)

    def test_replaying_the_cached_version_is_refused_with_a_precondition_failure(self):
        """The second request quoting the stale version writes nothing.

        PRD: "If that value does not equal the asset's current `version`, the creation is rejected with `ERR_STALE_ASSET_VERSION` (HTTP 412) and nothing is written."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_asset_version_on_reservation_create_is_rejected
        """
        registered, commissioned = self._commissioned_plant()
        cached_version = commissioned["version"]
        api_client.create_soc_reservation(
            self._reservation_request(
                commissioned["id"], cached_version, "ENERGY_ARBITRAGE", 40.0
            ),
            TRADER,
        )

        response = api_client.create_soc_reservation(
            self._reservation_request(
                commissioned["id"], cached_version, "ANCILLARY", 20.0
            ),
            TRADER,
        )

        validate_error(response, "ERR_STALE_ASSET_VERSION", expected_status=412)
        data, meta = validate_paginated(
            api_client.list_soc_reservations(
                TRADER, params={"asset_id": commissioned["id"]}
            )
        )
        assert meta["total_count"] == 1

    def test_the_retry_with_the_re_read_version_succeeds(self):
        """Re-reading the asset makes the same request legal.

        PRD: "The asset's `reserved_mwh_total` and `free_dispatchable_mwh` are recomputed and its `version` increases by one."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_asset_version_on_reservation_create_is_rejected
        """
        registered, commissioned = self._commissioned_plant()
        api_client.create_soc_reservation(
            self._reservation_request(
                commissioned["id"], commissioned["version"], "ENERGY_ARBITRAGE", 40.0
            ),
            TRADER,
        )
        after_one = refresh_asset(commissioned["id"])

        response = api_client.create_soc_reservation(
            self._reservation_request(
                commissioned["id"], after_one["version"], "ANCILLARY", 20.0
            ),
            TRADER,
        )

        validate_success(response, expected_status=201)
        after_two = refresh_asset(commissioned["id"])
        assert after_two["version"] == after_one["version"] + 1
        assert after_two["reserved_mwh_total"] == pytest.approx(60.0, abs=0.01)
        assert after_two["free_dispatchable_mwh"] == pytest.approx(10.0, abs=0.01)


class TestSubmissionBudgetBoundaries:
    """Two cumulative budgets bind at submission, each inclusive at its ceiling."""

    def _plant_with_two_offers(self, name, warranty_limit, cycle_limit):
        asset = provision_asset(
            name=name,
            initial_cumulative_throughput_mwh=190.0,
            warranty_throughput_limit_mwh=warranty_limit,
            cycle_limit_per_year=cycle_limit,
        )
        reservation = hold_reservation(
            asset["id"],
            reserved_mwh=40.0,
            window_start="2026-08-10T12:00:00Z",
            window_end="2026-08-10T20:00:00Z",
        )
        on_the_ceiling = draft_bid(
            asset["id"],
            reservation["id"],
            offer_mw=10.0,
            delivery_start="2026-08-10T12:00:00Z",
            delivery_end="2026-08-10T13:00:00Z",
        )
        just_over = draft_bid(
            asset["id"],
            reservation["id"],
            offer_mw=10.01,
            delivery_start="2026-08-10T14:00:00Z",
            delivery_end="2026-08-10T15:00:00Z",
        )
        return asset, on_the_ceiling, just_over

    def _cycle_constrained_plant(self):
        set_clock(DISPATCH_DAY_CLOCK)
        return self._plant_with_two_offers("Mesa Verde Cycle Bound", 400.0, 1)

    def _throughput_constrained_plant(self):
        set_clock(DISPATCH_DAY_CLOCK)
        return self._plant_with_two_offers("Mesa Verde Throughput Bound", 200.0, 5)

    def test_the_cycle_budget_admits_its_exact_ceiling(self):
        """A debit that lands on one full cycle a year is inside the budget.

        PRD: "The cycle budget: the asset's `equivalent_full_cycles_ytd` plus this offer's cycle debit — `expected_energy_mwh` divided by twice `available_energy_mwh`, the sum rounded half up to 4 decimal places — must be at most `cycle_limit_per_year`, or the submission is refused with `ERR_CYCLE_LIMIT_EXCEEDED` (HTTP 409)."

        Design: Corner/cross_cutting_complexity_layers/cumulative_cycle_and_throughput_thresholds_bind_at_their_exact_boundary
        """
        asset, on_the_ceiling, just_over = self._cycle_constrained_plant()
        assert asset["equivalent_full_cycles_ytd"] == pytest.approx(0.95, abs=0.0001)
        assert on_the_ceiling["cycle_debit_efc"] == pytest.approx(0.05, abs=0.0001)

        submitted = submit_bid(on_the_ceiling["id"])

        assert submitted["status"] == "SUBMITTED"

    def test_the_cycle_budget_refuses_one_hundredth_past_its_ceiling(self):
        """A hundredth of a megawatt more takes the year past one full cycle.

        PRD: "The cycle budget: the asset's `equivalent_full_cycles_ytd` plus this offer's cycle debit — `expected_energy_mwh` divided by twice `available_energy_mwh`, the sum rounded half up to 4 decimal places — must be at most `cycle_limit_per_year`, or the submission is refused with `ERR_CYCLE_LIMIT_EXCEEDED` (HTTP 409)."

        Design: Corner/cross_cutting_complexity_layers/cumulative_cycle_and_throughput_thresholds_bind_at_their_exact_boundary
        """
        asset, on_the_ceiling, just_over = self._cycle_constrained_plant()

        response = api_client.submit_market_bid(just_over["id"], TRADER)

        validate_error(response, "ERR_CYCLE_LIMIT_EXCEEDED", expected_status=409)

    def test_the_warranty_budget_admits_its_exact_ceiling(self):
        """Ten megawatt-hours on top of one hundred and ninety reaches the limit.

        PRD: "The warranty budget: the asset's `cumulative_throughput_mwh` plus this offer's `expected_energy_mwh`, rounded half up to 3 decimal places, must be at most `warranty_throughput_limit_mwh`, or the submission is refused with `ERR_THROUGHPUT_LIMIT_EXCEEDED` (HTTP 409), because trading past the guaranteed throughput would void the capacity-maintenance obligation."

        Design: Corner/cross_cutting_complexity_layers/cumulative_cycle_and_throughput_thresholds_bind_at_their_exact_boundary
        """
        asset, on_the_ceiling, just_over = self._throughput_constrained_plant()
        assert on_the_ceiling["expected_energy_mwh"] == pytest.approx(10.0, abs=0.01)

        submitted = submit_bid(on_the_ceiling["id"])

        assert submitted["status"] == "SUBMITTED"

    def test_the_warranty_budget_reports_its_own_code(self):
        """With cycle room to spare, only the throughput code can be returned.

        PRD: "The warranty budget: the asset's `cumulative_throughput_mwh` plus this offer's `expected_energy_mwh`, rounded half up to 3 decimal places, must be at most `warranty_throughput_limit_mwh`, or the submission is refused with `ERR_THROUGHPUT_LIMIT_EXCEEDED` (HTTP 409), because trading past the guaranteed throughput would void the capacity-maintenance obligation."

        Design: Corner/cross_cutting_complexity_layers/cumulative_cycle_and_throughput_thresholds_bind_at_their_exact_boundary
        """
        asset, on_the_ceiling, just_over = self._throughput_constrained_plant()

        response = api_client.submit_market_bid(just_over["id"], TRADER)

        validate_error(response, "ERR_THROUGHPUT_LIMIT_EXCEEDED", expected_status=409)

    def test_offering_energy_moves_neither_budget(self):
        """The counters advance on delivery, not on offering.

        PRD: "Two budgets are checked at submission and nowhere else."

        Design: Corner/cross_cutting_complexity_layers/cumulative_cycle_and_throughput_thresholds_bind_at_their_exact_boundary
        """
        asset, on_the_ceiling, just_over = self._throughput_constrained_plant()

        submit_bid(on_the_ceiling["id"])

        plant = refresh_asset(asset["id"])
        assert plant["cumulative_throughput_mwh"] == pytest.approx(190.0, abs=0.01)
        assert plant["equivalent_full_cycles_ytd"] == pytest.approx(0.95, abs=0.0001)
