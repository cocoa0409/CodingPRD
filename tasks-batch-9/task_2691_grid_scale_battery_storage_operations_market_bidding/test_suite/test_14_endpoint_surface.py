"""The endpoint surface: CRUD round trips, action endpoints and nested reads.

These tests exercise the endpoints as endpoints — what a create returns, what a
read returns afterwards, what a filtered collection contains, and what an action
endpoint with no request body changes on the row it acts on.
"""
import pytest
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_client import api_client
from test_helpers.factories import (
    create_capacity_obligation_payload,
    create_warranty_claim_payload,
)
from test_helpers.fixtures import (
    ADMIN,
    ASSET_MANAGER,
    CLAIM_FILER,
    DISPATCH_DAY_CLOCK,
    MARKET_OPERATOR,
    append_sample,
    cleared_bid,
    commission_asset,
    completed_test,
    executing_dispatch,
    file_claim,
    hold_reservation,
    lightly_cycled_plant,
    provision_asset,
    refresh_asset,
    refresh_dispatch,
    register_asset,
    set_clock,
)


class TestCapacityObligationRoundTrip:
    """Enrolment writes a row whose assessed fields are all still empty."""

    def _enrolment_response(self, asset_id):
        return api_client.create_capacity_obligation(
            create_capacity_obligation_payload(
                asset_id,
                program_name="ISO-NE FCM",
                program_year=2026,
                committed_mw=20.0,
                availability_hours_required=8000.0,
                penalty_rate_usd_per_mw_hour=150.0,
                obligation_duration_hours=4.0,
            ),
            ASSET_MANAGER,
        )

    def test_enrolment_returns_the_unassessed_shape(self):
        """Nothing is assessed at enrolment, so every assessed field is empty.

        PRD: "A new obligation is created with `status` `ACTIVE`, `unavailable_hours` 0.0, `accrual_started_at` null, `measured_available_hours` 0.0, `availability_pct` null, `shortfall_hours` 0.0, `penalty_exposure_usd` 0.0, `assessment_mode` null and `derated_committed_mw` null, and returns HTTP 201."

        Design: Corner/endpoints/capacity_obligation_create_read_list_round_trip
        """
        set_clock(DISPATCH_DAY_CLOCK)
        asset = provision_asset()

        obligation = validate_success(self._enrolment_response(asset["id"]), expected_status=201)

        assert obligation["status"] == "ACTIVE"
        assert obligation["unavailable_hours"] == pytest.approx(0.0, abs=0.01)
        assert obligation["penalty_exposure_usd"] == pytest.approx(0.0, abs=0.01)
        assert obligation["availability_pct"] is None
        assert obligation["assessment_mode"] is None
        assert obligation["derated_committed_mw"] is None
        assert obligation["accrual_started_at"] is None

    def test_the_read_returns_the_stored_commitment(self):
        """Reading the obligation back returns the inputs it was created with.

        PRD: "`obligation_duration_hours` is optional, defaults to 4.0, must be greater than 0, and is the number of hours of continuous discharge at `committed_mw` the programme requires the plant to be able to sustain."

        Design: Corner/endpoints/capacity_obligation_create_read_list_round_trip
        """
        set_clock(DISPATCH_DAY_CLOCK)
        asset = provision_asset()
        obligation = get_success_data(self._enrolment_response(asset["id"]))

        stored = get_success_data(
            api_client.get_capacity_obligation(obligation["id"], MARKET_OPERATOR)
        )

        assert stored["id"] == obligation["id"]
        assert stored["committed_mw"] == pytest.approx(20.0, abs=0.01)
        assert stored["obligation_duration_hours"] == pytest.approx(4.0, abs=0.01)

    def test_the_collection_filters_on_the_programme_year(self):
        """A read filtered by asset and programme year finds the one enrolment.

        PRD: "Capacity obligations filter on `asset_id`, `program_year` and `status`."

        Design: Corner/endpoints/capacity_obligation_create_read_list_round_trip
        """
        set_clock(DISPATCH_DAY_CLOCK)
        asset = provision_asset()
        obligation = get_success_data(self._enrolment_response(asset["id"]))

        data, meta = validate_paginated(
            api_client.list_capacity_obligations(
                MARKET_OPERATOR,
                params={"asset_id": asset["id"], "program_year": 2026},
            )
        )

        assert meta["total_count"] == 1
        assert [row["id"] for row in data] == [obligation["id"]]


class TestCommissioningActionEndpoint:
    """Commissioning carries no body: its whole effect is the transition.

    The version it leaves behind is the one the reservation writers then quote.
    """

    def test_a_registered_plant_starts_offline_at_version_one(self):
        """Registration leaves the market axis closed.

        PRD: "`safety_state` starts at `NORMAL`, `market_state` at `OFFLINE`, `suspension_reason` and `suspended_at` at null, and `version` at 1."

        Design: Corner/endpoints/commission_action_endpoint_flips_the_market_axis
        """
        set_clock(DISPATCH_DAY_CLOCK)

        registered = register_asset()

        assert registered["market_state"] == "OFFLINE"
        assert registered["version"] == 1

    def test_commissioning_opens_the_market_axis_only(self):
        """The safety axis is untouched and the version advances.

        PRD: "On success `suspension_reason` and `suspended_at` are set to null, `updated_at` is refreshed and `version` increases by one, and the response is HTTP 200 carrying the asset."

        Design: Corner/endpoints/commission_action_endpoint_flips_the_market_axis
        """
        set_clock(DISPATCH_DAY_CLOCK)
        registered = register_asset()

        response = api_client.commission_storage_asset(registered["id"], ASSET_MANAGER)

        commissioned = validate_success(response, expected_status=200)
        assert commissioned["market_state"] == "AVAILABLE"
        assert commissioned["safety_state"] == "NORMAL"
        assert commissioned["suspension_reason"] is None
        assert commissioned["version"] == registered["version"] + 1


class TestSecondCommissioningIsRefused:
    """Commissioning is only meaningful from `OFFLINE`."""

    def test_commissioning_an_available_plant_is_refused(self):
        """A plant that already trades cannot be commissioned again.

        PRD: "Commissioning an asset whose `market_state` is not `OFFLINE` — one already `AVAILABLE`, or one `SUSPENDED` by a safety cascade — is refused with `ERR_ASSET_NOT_OFFLINE`."

        Design: Corner/endpoints/second_commission_conditional_action_rejected
        """
        set_clock(DISPATCH_DAY_CLOCK)
        asset = provision_asset()

        response = api_client.commission_storage_asset(asset["id"], ADMIN)

        validate_error(response, "ERR_ASSET_NOT_OFFLINE", expected_status=409)

    def test_the_refused_call_does_not_advance_the_version(self):
        """A rejected action is not a mutation.

        PRD: "The asset's `version` advances by one on commissioning, on every reservation creation, on every reservation release, on dispatch completion, on dispatch failure, on the creation of a safety event, on the closure of a safety event, on capacity-test completion, and on augmentation installation."

        Design: Corner/endpoints/second_commission_conditional_action_rejected
        """
        set_clock(DISPATCH_DAY_CLOCK)
        registered = register_asset()
        commissioned = commission_asset(registered["id"])

        api_client.commission_storage_asset(registered["id"], ADMIN)

        plant = refresh_asset(registered["id"])
        assert plant["market_state"] == "AVAILABLE"
        assert plant["version"] == commissioned["version"]


class TestTelemetryCollectionRead:
    """The nested collection is the only way to see stored sample-level fields."""

    def _instruction_with_two_samples(self):
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
        )
        dispatch = executing_dispatch(
            bid["id"],
            asset["id"],
            instructed_mw=20.0,
            setpoint_start="2026-08-10T14:00:00Z",
            setpoint_end="2026-08-10T15:00:00Z",
        )
        append_sample(
            dispatch["id"], asset["id"], 1, "2026-08-10T14:15:00Z", measured_mw=19.6,
            soc_mwh_reading=75.1,
        )
        append_sample(
            dispatch["id"], asset["id"], 2, "2026-08-10T14:30:00Z", measured_mw=20.4,
            soc_mwh_reading=70.0,
        )
        return asset, dispatch

    def test_the_stream_is_returned_in_sampling_order(self):
        """Both samples come back oldest first, as the delivery happened.

        PRD: "The one exception is the telemetry of a single dispatch instruction, which is returned in ascending `sampled_at` order so that a reader sees the delivery as it happened."

        Design: Corner/endpoints/telemetry_computed_read_returns_derived_sample_fields
        """
        asset, dispatch = self._instruction_with_two_samples()

        data, meta = validate_paginated(
            api_client.list_telemetry_samples(
                dispatch["id"], ASSET_MANAGER, params={"limit": 10, "offset": 0}
            )
        )

        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        assert [row["sample_index"] for row in data] == [1, 2]

    def test_each_element_carries_its_stored_arithmetic(self):
        """The two readings deviate symmetrically around the instructed power.

        PRD: "Because telemetry samples are append-only and have no single-resource read of their own, listing the telemetry of one instruction is the only channel through which a client can observe the sample-level fields the platform computes."

        Design: Corner/endpoints/telemetry_computed_read_returns_derived_sample_fields
        """
        asset, dispatch = self._instruction_with_two_samples()

        data, meta = validate_paginated(
            api_client.list_telemetry_samples(
                dispatch["id"], ASSET_MANAGER, params={"limit": 10, "offset": 0}
            )
        )

        first, second = data
        assert first["apparent_mva"] == pytest.approx(19.6, abs=0.01)
        assert second["apparent_mva"] == pytest.approx(20.4, abs=0.01)
        assert first["deviation_mw"] == pytest.approx(0.4, abs=0.01)
        assert second["deviation_mw"] == pytest.approx(0.4, abs=0.01)
        assert first["error_ratio"] == pytest.approx(0.02, abs=0.0001)
        assert second["error_ratio"] == pytest.approx(0.02, abs=0.0001)
        assert first["within_deadband"] is True
        assert second["within_deadband"] is True
        assert first["thermal_escalation"] == "NONE"
        assert second["thermal_escalation"] == "NONE"

    def test_the_parent_counter_agrees_with_the_collection(self):
        """The instruction's own counter matches the stream it owns.

        PRD: "Appending a sample also increases the instruction's `telemetry_sample_count` by one, and that counter includes late-arriving samples."

        Design: Corner/endpoints/telemetry_computed_read_returns_derived_sample_fields
        """
        asset, dispatch = self._instruction_with_two_samples()

        stored = refresh_dispatch(dispatch["id"], headers=ASSET_MANAGER)

        assert stored["telemetry_sample_count"] == 2


class TestWarrantyClaimCrossReference:
    """A claim links one asset to one of that same asset's capacity tests."""

    TEST_DATE = "2026-08-01T00:00:00Z"

    def _two_plants_and_one_triggered_test(self):
        set_clock(self.TEST_DATE)
        tested = lightly_cycled_plant()
        test = completed_test(
            tested["id"], scheduled_date=self.TEST_DATE, measured_capacity_mwh=90.0
        )
        untested = provision_asset(name="Mesa Verde BESS 5")
        return tested, test, untested

    def test_a_claim_citing_another_plants_test_is_refused(self):
        """Both references exist; they simply disagree about the asset.

        PRD: "Every reference in the body that transitively belongs to a storage asset resolves to the same asset as the body's `asset_id` — the referenced offer's asset, the referenced reservation's asset, the referenced instruction's asset, the referenced capacity test's asset, the originating instruction's asset and the baseline test's asset must all agree."

        Design: Corner/endpoints/warranty_claim_cross_reference_must_cite_the_same_asset
        """
        tested, test, untested = self._two_plants_and_one_triggered_test()
        assert test["warranty_claim_triggered"] is True

        response = api_client.create_warranty_claim(
            create_warranty_claim_payload(untested["id"], test["id"]), CLAIM_FILER
        )

        validate_error(response, "ERR_ASSET_SCOPE_MISMATCH", expected_status=409)

    def test_the_same_plants_test_is_claimable(self):
        """The association is created only when both references agree.

        PRD: "A drafted claim copies `claimed_shortfall_pct` from the cited test's `soh_deficit_pct`, starts with `status` `DRAFT`, records `created_by_user_id` as the acting identifier, leaves `submitted_by_user_id`, `adjudicated_by_user_id`, `remedy_energy_add_mwh`, `remedy_install_date`, `remedy_outage_days` and `denial_reason` null, and returns HTTP 201."

        Design: Corner/endpoints/warranty_claim_cross_reference_must_cite_the_same_asset
        """
        tested, test, untested = self._two_plants_and_one_triggered_test()

        claim = file_claim(tested["id"], test["id"])

        assert claim["status"] == "DRAFT"
        assert claim["claimed_shortfall_pct"] == pytest.approx(2.1, abs=0.01)
