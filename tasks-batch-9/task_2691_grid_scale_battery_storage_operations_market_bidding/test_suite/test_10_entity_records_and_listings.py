"""Record-level behaviour: created envelopes, read-backs, listings and shape refusals.

These probes stay at the surface of each entity — what a create returns, what a
read exposes, which pages a filtered listing yields, and which bodies the
platform refuses before any business rule runs.
"""
import pytest
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_client import api_client
from test_helpers.factories import (
    ASSET_DEFAULTS,
    create_market_bid_payload,
    create_soc_reservation_payload,
    create_storage_asset_payload,
    create_telemetry_sample_payload,
)
from test_helpers.fixtures import (
    ADMIN,
    MARKET_OPERATOR,
    TRADER,
    append_sample,
    draft_bid,
    executing_position,
    hold_reservation,
    make_site_controller_headers,
    provision_asset,
    refresh_asset,
    register_asset,
    commission_asset,
    set_clock,
)


class TestStorageAssetRecord:
    """Registration output, read-back fidelity and the shape gate."""

    def test_registration_returns_the_whole_derived_envelope(self):
        """The 201 body carries the seeded ledgers and both parallel state axes.

        PRD: "`safety_state` starts at `NORMAL`, `market_state` at `OFFLINE`, `suspension_reason` and `suspended_at` at null, and `version` at 1."

        Design: Corner/entities/storage_asset_creation_returns_full_computed_envelope
        """
        set_clock("2026-08-01T00:00:00Z")

        response = api_client.create_storage_asset(
            create_storage_asset_payload(), ADMIN
        )

        asset = validate_success(response, 201)
        assert asset["soc_mwh"] == pytest.approx(80.0, abs=0.01)
        assert asset["rated_energy_mwh"] == pytest.approx(100.0, abs=0.01)
        assert asset["available_energy_mwh"] == pytest.approx(100.0, abs=0.01)
        assert asset["free_dispatchable_mwh"] == pytest.approx(70.0, abs=0.01)
        assert asset["soh_pct"] == pytest.approx(100.00, abs=0.01)
        assert asset["reserved_mwh_total"] == pytest.approx(0.0, abs=0.01)
        assert asset["cumulative_throughput_mwh"] == pytest.approx(0.0, abs=0.01)
        assert asset["equivalent_full_cycles_ytd"] == pytest.approx(0.0, abs=0.01)
        assert asset["safety_state"] == "NORMAL"
        assert asset["market_state"] == "OFFLINE"
        assert asset["version"] == 1

    def test_a_read_back_shows_the_commissioned_state_at_the_same_version(self):
        """Commissioning advances the version once; the read does not advance it again.

        PRD: "On success `suspension_reason` and `suspended_at` are set to null, `updated_at` is refreshed and `version` increases by one, and the response is HTTP 200 carrying the asset."

        Design: Corner/entities/storage_asset_retrieval_returns_stored_state
        """
        set_clock("2026-08-01T00:00:00Z")
        registered = register_asset()
        commissioned = commission_asset(registered["id"])

        read_back = refresh_asset(registered["id"])

        assert read_back["id"] == registered["id"]
        assert read_back["market_state"] == commissioned["market_state"] == "AVAILABLE"
        assert read_back["version"] == commissioned["version"]
        assert read_back["soc_mwh"] == pytest.approx(80.0, abs=0.01)

    def test_registration_without_a_nameplate_is_malformed(self):
        """A missing required input fails the shape gate rather than defaulting to zero.

        PRD: "The body is a JSON object, every required input field is present with its declared type, every enum field carries a declared member, every numeric field is finite and — unless that field's own rule says otherwise — non-negative, and `limit` and `offset` are integers inside their bounds."

        Design: Corner/entities/storage_asset_missing_nameplate_returns_invalid_request
        """
        payload = dict(ASSET_DEFAULTS)
        payload["name"] = "No Nameplate BESS"
        payload.pop("nameplate_energy_mwh")

        response = api_client.create_storage_asset(payload, ADMIN)

        validate_error(response, "ERR_INVALID_REQUEST")
        _, meta = validate_paginated(api_client.list_storage_assets(ADMIN))
        assert meta["total_count"] == 0

    def test_all_six_optional_inputs_apply_their_declared_defaults(self):
        """Omitting every optional input still yields a fully specified plant.

        PRD: "Six inputs are optional and each has a default."

        Design: Corner/entities/storage_asset_omitted_optionals_apply_declared_defaults
        """
        asset = register_asset(name="Defaults BESS")

        assert asset["soc_floor_pct"] == pytest.approx(10.0, abs=0.01)
        assert asset["soc_ceiling_pct"] == pytest.approx(95.0, abs=0.01)
        assert asset["warranty_guaranteed_soh_pct"] == pytest.approx(80.0, abs=0.01)
        assert asset["warranty_annual_fade_pct"] == pytest.approx(2.5, abs=0.01)
        assert asset["cumulative_throughput_mwh"] == pytest.approx(0.0, abs=0.01)

    def test_the_defaulted_floor_reaches_the_reservation_pool_formula(self):
        """A defaulted efficiency and a defaulted floor both materialise on the record.

        PRD: "`round_trip_efficiency_pct` is the AC round-trip efficiency, defaulting to 88.0, and must be at least 50.0 and at most 100.0; it is used both to gross up the cost of charge energy inside the offer price and to derate charge energy booked into stored energy."

        Design: Corner/entities/storage_asset_omitted_optionals_apply_declared_defaults
        """
        asset = register_asset(name="Defaults BESS")

        assert asset["round_trip_efficiency_pct"] == pytest.approx(88.0, abs=0.01)
        assert asset["free_dispatchable_mwh"] == pytest.approx(70.0, abs=0.01)

    def test_posted_identifiers_and_counters_are_discarded(self):
        """A client cannot pre-set its own id, creation stamp or version.

        PRD: "Every resource is identified by `id`, a server-minted UUID with no type prefix; clients never supply an `id`."

        Design: Corner/entities/storage_asset_system_fields_client_input_ignored
        """
        set_clock("2026-08-01T00:00:00Z")
        payload = create_storage_asset_payload(
            name="System Fields BESS",
            id="11111111-1111-4111-8111-111111111111",
            created_at="1999-01-01T00:00:00Z",
            version=99,
        )

        asset = validate_success(api_client.create_storage_asset(payload, ADMIN), 201)

        assert asset["id"] != "11111111-1111-4111-8111-111111111111"
        assert asset["created_at"] != "1999-01-01T00:00:00Z"
        assert asset["version"] == 1


class TestOfferAndReservationRecords:
    """Derived reservation fields, offer listing pages and the two reference gates."""

    def test_posted_reservation_computed_fields_are_discarded(self):
        """Rank, status and consumption are the platform's to write, not the caller's.

        PRD: "`purpose` is one of `ENERGY_ARBITRAGE`, `ANCILLARY` or `CAPACITY`, and it also fixes the reservation's standing in the pool: `priority_rank` is set to 1 for `CAPACITY`, 2 for `ANCILLARY` and 3 for `ENERGY_ARBITRAGE`, and a lower rank preempts a higher one."

        Design: Corner/entities/soc_reservation_computed_fields_client_input_ignored
        """
        set_clock("2026-08-01T00:00:00Z")
        asset = provision_asset()
        payload = create_soc_reservation_payload(
            asset["id"],
            asset["version"],
            purpose="ENERGY_ARBITRAGE",
            reserved_mwh=20.0,
            window_start="2026-08-05T00:00:00Z",
            window_end="2026-08-05T08:00:00Z",
            priority_rank=1,
            status="CONSUMED",
            consumed_mwh=20.0,
        )

        reservation = validate_success(
            api_client.create_soc_reservation(payload, TRADER), 201
        )

        assert reservation["priority_rank"] == 3
        assert reservation["status"] == "HELD"
        assert reservation["consumed_mwh"] == pytest.approx(0.0, abs=0.01)
        assert reservation["released_reason"] is None

    def test_offer_listing_paginates_inside_the_filtered_set(self):
        """Two offers on one plant, read one per page, with total_count and has_more.

        PRD: "List responses carry `limit` and `offset` as applied, `total_count` — the number of rows matching the request's filters before pagination — and `has_more`, a boolean stating whether any matching row remains beyond the returned page, all four inside `meta`."

        Design: Corner/entities/market_bid_listing_paginates_with_total_count_and_has_more
        """
        set_clock("2026-08-01T00:00:00Z")
        asset = provision_asset()
        near = hold_reservation(
            asset["id"],
            reserved_mwh=20.0,
            window_start="2026-08-05T00:00:00Z",
            window_end="2026-08-05T08:00:00Z",
        )
        first_offer = draft_bid(
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
        second_offer = draft_bid(
            asset["id"],
            far["id"],
            market_type="REAL_TIME",
            product="REG_UP",
            delivery_start="2026-08-20T01:00:00Z",
            delivery_end="2026-08-20T05:00:00Z",
            offer_mw=5.0,
        )

        page_one, meta_one = validate_paginated(
            api_client.list_market_bids(
                MARKET_OPERATOR, {"asset_id": asset["id"], "limit": 1, "offset": 0}
            )
        )
        page_two, meta_two = validate_paginated(
            api_client.list_market_bids(
                MARKET_OPERATOR, {"asset_id": asset["id"], "limit": 1, "offset": 1}
            )
        )

        assert len(page_one) == 1
        assert meta_one["total_count"] == 2
        assert meta_one["has_more"] is True
        assert meta_one["limit"] == 1
        assert meta_one["offset"] == 0
        assert len(page_two) == 1
        assert meta_two["total_count"] == 2
        assert meta_two["has_more"] is False
        assert meta_two["offset"] == 1
        assert {page_one[0]["id"], page_two[0]["id"]} == {
            first_offer["id"],
            second_offer["id"],
        }

    def test_an_unknown_product_is_refused_at_the_shape_gate(self):
        """No product factor exists for an undeclared enum member.

        PRD: "The body is a JSON object, every required input field is present with its declared type, every enum field carries a declared member, every numeric field is finite and — unless that field's own rule says otherwise — non-negative, and `limit` and `offset` are integers inside their bounds."

        Design: Corner/entities/market_bid_unknown_product_returns_invalid_request
        """
        set_clock("2026-08-01T00:00:00Z")
        asset = provision_asset()
        reservation = hold_reservation(
            asset["id"],
            reserved_mwh=20.0,
            window_start="2026-08-05T00:00:00Z",
            window_end="2026-08-05T08:00:00Z",
        )

        response = api_client.create_market_bid(
            create_market_bid_payload(
                asset["id"],
                reservation["id"],
                product="FREQUENCY_TRIM",
                delivery_start="2026-08-05T01:00:00Z",
                delivery_end="2026-08-05T05:00:00Z",
            ),
            TRADER,
        )

        validate_error(response, "ERR_INVALID_REQUEST")
        _, meta = validate_paginated(
            api_client.list_market_bids(TRADER, {"asset_id": asset["id"]})
        )
        assert meta["total_count"] == 0

    def test_an_offer_may_not_pair_one_plant_with_another_s_reservation(self):
        """Both references resolve, and then the scope agreement refuses the pairing.

        PRD: "A disagreement is `ERR_ASSET_SCOPE_MISMATCH` (HTTP 409)."

        Design: Corner/entities/flat_topology_cross_asset_reservation_reference_rejected
        """
        set_clock("2026-08-01T00:00:00Z")
        owner = provision_asset(name="Scope BESS A")
        stranger = provision_asset(name="Scope BESS B")
        reservation = hold_reservation(
            owner["id"],
            reserved_mwh=40.0,
            window_start="2026-08-10T12:00:00Z",
            window_end="2026-08-10T20:00:00Z",
        )

        response = api_client.create_market_bid(
            create_market_bid_payload(stranger["id"], reservation["id"]),
            TRADER,
        )

        validate_error(response, "ERR_ASSET_SCOPE_MISMATCH")
        assert refresh_asset(stranger["id"])["reserved_mwh_total"] == pytest.approx(
            0.0, abs=0.01
        )


class TestInstructionAndTelemetryRecords:
    """The one entity with no version, and the two not-found surfaces around it."""

    def test_an_unknown_instruction_id_answers_with_the_dispatch_not_found_code(self):
        """A well-formed but unknown path identifier is an entity-specific 404.

        PRD: "A miss yields the not-found code of the entity that failed to resolve: `ERR_ASSET_NOT_FOUND`, `ERR_RESERVATION_NOT_FOUND`, `ERR_BID_NOT_FOUND`, `ERR_DISPATCH_NOT_FOUND`, `ERR_SAFETY_EVENT_NOT_FOUND`, `ERR_OBLIGATION_NOT_FOUND`, `ERR_TEST_NOT_FOUND` or `ERR_CLAIM_NOT_FOUND`, each HTTP 404."

        Design: Corner/entities/dispatch_instruction_unknown_id_not_found
        """
        response = api_client.get_dispatch_instruction(
            NON_EXISTENT_UUID, MARKET_OPERATOR
        )

        validate_error(response, "ERR_DISPATCH_NOT_FOUND")

    def test_a_telemetry_sample_carries_no_version_and_no_updated_at(self):
        """The one immutable entity exposes only its identity and creation stamp.

        PRD: "Telemetry samples are the exception: a sample is an immutable measurement, so it carries only `id` and `created_at` — it has neither `updated_at` nor `version`."

        Design: Corner/entities/telemetry_sample_is_immutable_with_no_version_and_no_mutating_endpoint
        """
        set_clock("2026-08-10T00:00:00Z")
        position = executing_position()

        sample = append_sample(
            position["dispatch"]["id"],
            position["asset"]["id"],
            1,
            "2026-08-10T14:15:00Z",
            measured_mw=20.0,
            soc_mwh_reading=75.0,
        )

        assert sample["sample_index"] == 1
        assert sample["apparent_mva"] == pytest.approx(20.0, abs=0.01)
        assert sample["deviation_mw"] == pytest.approx(0.0, abs=0.01)
        assert sample["thermal_escalation"] == "NONE"
        assert "version" not in sample
        assert "updated_at" not in sample
        assert "created_at" in sample

    def test_a_sample_naming_an_unknown_instruction_is_a_dispatch_not_found(self):
        """A body reference is resolved before any instruction state is examined.

        PRD: "The failing reference decides which of `ERR_ASSET_NOT_FOUND`, `ERR_RESERVATION_NOT_FOUND`, `ERR_BID_NOT_FOUND`, `ERR_DISPATCH_NOT_FOUND` or `ERR_TEST_NOT_FOUND` is returned."

        Design: Corner/entities/telemetry_sample_unknown_parent_dispatch_not_found
        """
        response = api_client.create_telemetry_sample(
            create_telemetry_sample_payload(
                NON_EXISTENT_UUID,
                1,
                "2026-08-10T14:15:00Z",
                measured_mw=20.0,
                soc_mwh_reading=75.0,
                max_cell_temp_c=30.0,
            ),
            make_site_controller_headers(NON_EXISTENT_UUID),
        )

        validate_error(response, "ERR_DISPATCH_NOT_FOUND")
