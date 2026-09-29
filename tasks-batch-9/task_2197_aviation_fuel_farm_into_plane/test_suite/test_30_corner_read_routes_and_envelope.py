"""Corner behaviour of the read surface and the response envelope: every foreign key is traversable
backwards, detail reads carry the derived figures, creates and actions use distinct status codes, and every
response — success or failure — carries the same meta block."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    fixtures as fx, factories as F,
)

BIG_CREDIT = 100_000_000_000
PIPELINE_PARCEL = dict(delivery_mode="PIPELINE", supplier_name="Refinery One",
                       meter_ticket_gross_liters=29800.0, tank_opening_gauge_liters=0.0,
                       tank_closing_gauge_liters=29700.0, temperature_c=15.0,
                       certificate_density_kg_per_m3=795.0, measured_water_liters=0.0)


class TestReverseReachabilityOfEveryForeignKey:
    def test_every_parent_can_enumerate_its_children(self, api):
        """PRD §4: "Lists the farm's tanks with derived ledger figures."
        PRD §4: "Lists hydrant pits, filterable by farm and source tank."
        PRD §4: "Lists samples, filterable by receipt, tank, asset and status."
        PRD §4: "Lists authorizations, filterable by account, flight and status."
        PRD §4: "Lists orders, filterable by flight, authorization, tank, asset, pit and status."

        Design: Corner/endpoints/every_fk_has_a_listing_or_nested_route
        """
        env = fx.setup_hydrant_order(target_state="FUELING", requested_uplift_liters=20_000.0,
                                     max_authorized_liters=20_000.0,
                                     account_overrides={"credit_limit_cents": BIG_CREDIT})
        farm_id, tank_id, cart_id = env["farm"]["id"], env["tank"]["id"], env["cart"]["id"]
        account_id, flight_id = env["account"]["id"], env["flight"]["id"]
        order_id = env["order"]["id"]
        ticket = fx.post_uplift(order_id, fx.current_order_version(order_id),
                                meter_start_liters=0.0, meter_end_liters=20_000.0,
                                temperature_c=15.0)
        receipt = fx.record_receipt(tank_id, **PIPELINE_PARCEL)
        sample = fx.draw_receipt_sample(receipt["id"])
        spill = fx.report_spill(farm_id)

        def ids(response):
            rows, _meta = validate_paginated(response)
            return [row["id"] for row in rows]

        # the farm's four nested collections
        assert ids(api.list_storage_tanks(farm_id, fx.OPERATOR)) == [tank_id]
        assert len(ids(api.list_environmental_permits(farm_id, fx.OPERATOR))) == 1
        assert ids(api.list_farm_hydrant_pits(farm_id, fx.OPERATOR)) == [env["pit"]["id"]]
        assert ids(api.list_reconciliation_runs(farm_id, fx.OPERATOR)) == []

        # every remaining foreign key is reachable through a filter or a nested route
        assert ids(api.list_fuel_receipts(fx.OPERATOR, {"storage_tank_id": tank_id})) == \
            [receipt["id"]]
        assert ids(api.list_quality_samples(fx.INSPECTOR_A,
                                            {"fuel_receipt_id": receipt["id"]})) == \
            [sample["id"]]
        assert ids(api.list_quality_samples(fx.INSPECTOR_A,
                                            {"storage_tank_id": tank_id})) != []
        assert ids(api.list_fueling_assets(fx.OPERATOR, {"fuel_farm_id": farm_id})) == [cart_id]
        assert ids(api.list_filter_changes(cart_id, fx.OPERATOR)) == []
        assert ids(api.list_hydrant_pits(fx.OPERATOR,
                                         {"source_storage_tank_id": tank_id})) == \
            [env["pit"]["id"]]
        assert ids(api.list_flights(fx.AGENT, {"airline_account_id": account_id})) == [flight_id]
        assert ids(api.list_fuel_authorizations(fx.AGENT, {"flight_id": flight_id})) == \
            [env["auth"]["id"]]
        assert ids(api.list_fueling_orders(fx.AGENT, {"flight_id": flight_id})) == [order_id]
        assert ids(api.list_fueling_orders(fx.AGENT, {"fueling_asset_id": cart_id})) == [order_id]
        assert ids(api.list_uplift_records(fx.AGENT, {"fueling_order_id": order_id})) == \
            [ticket["id"]]
        assert ids(api.list_spill_incidents(fx.ENVIRO, {"fuel_farm_id": farm_id})) == \
            [spill["id"]]
        assert ids(api.list_invoices(fx.BILLING, {"airline_account_id": account_id})) == []


class TestDetailReadsCarryTheDerivedFigures:
    def test_the_tank_ledger_is_already_settled_when_the_release_returns(self, api):
        """PRD §4: "Reads a tank with book, reserved and available volumes."
        PRD §3.4: "The `available_volume_liters` is the book volume less the reserved volume less the farm's
        `unpumpable_bottom_liters`, rounded half up to two decimals and then floored at 0.0 so it can never
        go negative."
        PRD §2.4: "Derived figures are also refreshed on read, so a client never sees a stale computed
        value."

        Design: Corner/endpoints/derived_fields_appear_on_the_detail_read
        """
        env = fx.setup_fuel_farm()
        tank = fx.make_released_tank(env["farm"]["id"], capacity_liters=5_000_000.0,
                                     safe_fill_liters=4_000_000.0, density_kg_per_m3=795.0,
                                     opening_volume_liters=0.0)
        fx.make_released_receipt(tank["id"], **PIPELINE_PARCEL)

        detail = validate_success(api.get_storage_tank(tank["id"], fx.OPERATOR))

        assert detail["book_volume_liters"] == pytest.approx(29700.00, abs=0.005)
        assert detail["reserved_volume_liters"] == pytest.approx(0.00, abs=0.005)
        assert detail["available_volume_liters"] == pytest.approx(29200.00, abs=0.005), \
            "29700 book, nothing reserved, 500 unpumpable — settled by the time the read returns"

    def test_the_farm_read_shows_the_utilisation_that_drives_its_posture(self, api):
        """PRD §4: "Reads a farm with its derived posture, permit utilisation, in-service asset count and
        open spill count."
        PRD §2.7: "Third, the farm is **restricted** if any of four conditions holds: at least one storage
        tank at the farm has `quality_status` `QUARANTINED`; at least one spill incident at the farm has
        `status` `REPORTED`; the farm's `active_permit_throughput_used_liters` has reached or exceeded 90
        percent of the governing permit's `max_daily_throughput_liters`; or the farm's
        `in_service_asset_count` is zero."
        PRD §2.11: "**Permit throughput conservation**: a rejected parcel never touched the ledger, so
        rejecting a quarantined receipt leaves the farm's `active_permit_throughput_used_liters` exactly as
        it was — only receipts that reach `RELEASED` and uplift tickets that are `POSTED` or `BILLED` count
        toward the permit day."

        Design: Corner/endpoints/farm_detail_exposes_posture_and_permit_utilisation
        """
        env = fx.setup_fueling_order_with_uplift(
            meter_end_liters=20_000.0, requested_uplift_liters=20_000.0,
            max_authorized_liters=20_000.0,
            account_overrides={"credit_limit_cents": BIG_CREDIT},
            permit_overrides={"max_daily_throughput_liters": 5_000_000.0})

        farm = validate_success(api.get_fuel_farm(env["farm"]["id"], fx.OPERATOR))

        assert farm["active_permit_throughput_used_liters"] == pytest.approx(20_000.00,
                                                                            abs=0.005)
        assert farm["in_service_asset_count"] == 1
        assert farm["open_spill_count"] == 0
        assert farm["posture"] == "OPEN", \
            "20,000 of 5,000,000 permitted liters is 0.4 percent, far below the 90 percent line"

    def test_the_issued_invoice_and_its_swept_tickets_are_readable_together(self, api):
        """PRD §4: "Reads an invoice with its rebate, admin fee and payable total."
        PRD §3.9: "Issuance flips every swept ticket from `POSTED` to `BILLED` and freezes its
        `billed_line_cents`, recomputing the invoice totals one final time in the same four steps; stamps
        `issued_by_user_id` from the acting identifier; and recomputes both of the account's exposure
        figures, where the uncollected-ticket term is replaced by the invoiced-invoice term, which
        additionally carries the admin fee and the rebate."
        PRD §4: "Lists uplift tickets, filterable by order, tank, invoice and status."

        Design: Corner/endpoints/invoice_detail_lists_its_swept_tickets
        """
        # The pinned money constants below are the PRD §3.6/§3.9 arithmetic for an account
        # priced at 62.00 cents per liter, so the account has to be opened at that price.
        env = fx.setup_issued_invoice(
            meter_end_liters=20_000.0,
            account_overrides={"credit_limit_cents": BIG_CREDIT,
                               "base_price_cents_per_liter": 62.00})
        invoice_id, ticket_id = env["invoice"]["id"], env["uplift"]["id"]

        detail = validate_success(api.get_invoice(invoice_id, fx.BILLING))
        assert detail["status"] == "ISSUED"
        assert detail["subtotal_cents"] == 1433393
        assert detail["volume_rebate_cents"] == 0
        assert detail["admin_fee_cents"] == 5734
        assert detail["total_cents"] == 1439127

        billed, meta = validate_paginated(api.list_uplift_records(fx.BILLING,
                                                                 {"invoice_id": invoice_id}))
        assert [t["id"] for t in billed] == [ticket_id]
        assert meta["total_count"] == 1
        assert billed[0]["status"] == "BILLED"


class TestStatusCodesAndActionPayloads:
    def test_creates_answer_201_while_transitions_answer_200(self, api):
        """PRD §4: "Endpoints that create a new resource respond with HTTP 201 and return the created
        resource in the `data` field; endpoints that modify an existing resource, drive a state transition,
        or read a resource respond with HTTP 200."
        PRD §3.6: "A new order opens in `REQUESTED` with `fueling_asset_id` and `hydrant_pit_id` null,
        `reserved_amount_cents` zero, `posted_net_liters` 0.0, `unassign_count` zero and `abort_reason` null,
        and — importantly — **no reservation is taken against the tank yet.**"
        PRD §3.4: "On the quality dimension, a fresh tank starts `ON_TEST` and cannot yet source an order."

        Design: Corner/endpoints/creates_are_201_and_actions_are_200
        """
        env = fx.setup_farm_with_released_tank()
        truck = fx.register_truck(env["farm"]["id"], tank_capacity_liters=40_000.0)
        airline = fx.setup_airline({"credit_limit_cents": BIG_CREDIT}, None, 20_000.0)
        payload = F.create_fueling_order_payload(
            airline["flight"]["id"], airline["auth"]["id"], env["tank"]["id"],
            airline["auth"]["authorization_code"], delivery_mode="TRUCK",
            requested_uplift_liters=20_000.0, window_start_utc=fx.WINDOW_START,
            window_end_utc=fx.WINDOW_END)

        order = validate_success(api.create_fueling_order(payload, fx.AGENT), 201)
        order_id = order["id"]
        validate_success(api.authorize_order(order_id, fx.AGENT), 200)
        validate_success(api.assign_order(order_id, {"fueling_asset_id": truck["id"]},
                                          fx.AGENT), 200)
        validate_success(api.unassign_order(order_id, fx.AGENT), 200)
        validate_success(api.assign_order(order_id, {"fueling_asset_id": truck["id"]},
                                          fx.AGENT), 200)
        started = validate_success(api.start_order(order_id, fx.AGENT), 200)
        validate_success(api.create_uplift_record(
            order_id, F.create_uplift_record_payload(started["version"],
                                                     meter_start_liters=0.0,
                                                     meter_end_liters=20_000.0,
                                                     temperature_c=15.0), fx.AGENT), 201)
        validate_success(api.complete_order(order_id, fx.AGENT), 200)

        # the two sub-resource creates mint a QualitySample row, so they are 201 as well
        receipt = fx.record_receipt(env["tank"]["id"], **PIPELINE_PARCEL)
        validate_success(api.create_receipt_sample(receipt["id"], fx.INSPECTOR_A), 201)
        fresh_tank = fx.register_tank(env["farm"]["id"], capacity_liters=5_000_000.0,
                                      safe_fill_liters=4_000_000.0,
                                      density_kg_per_m3=795.0, opening_volume_liters=0.0)
        validate_success(api.create_tank_sample(fresh_tank["id"], fx.INSPECTOR_A,
                                                {"sample_purpose": "PERIODIC_TANK_QA"}), 201)

    def test_an_action_hands_back_the_whole_mutated_parent(self, api):
        """PRD §2.2: "The `data` field contains the resource object or an array of resource objects. For 2xx
        responses with no data, it contains an empty object. Unless otherwise noted, operations that create
        or modify a resource will return the created or updated resource object in the data field."
        PRD §2.2: "The `response_type` is either "object" for a single resource or "array" for a list of
        resources."
        PRD §3.6: "Authorising an order, `REQUESTED → AUTHORIZED`, is an `IntoPlaneAgent` action and the
        single densest gate in the system."

        Design: Corner/endpoints/action_endpoints_return_the_mutated_parent
        """
        env = fx.setup_truck_order(target_state="REQUESTED",
                                   account_overrides={"credit_limit_cents": BIG_CREDIT})
        before = env["order"]
        assert before["status"] == "REQUESTED"

        response = api.authorize_order(before["id"], fx.AGENT)
        authorized = validate_success(response, 200)

        assert response.json()["response_type"] == "object"
        assert authorized["id"] == before["id"]
        assert authorized["status"] == "AUTHORIZED"
        assert authorized["version"] == before["version"] + 1
        assert authorized["requested_uplift_liters"] == pytest.approx(20_000.0, abs=0.005), \
            "the action returns the order itself, not a bare acknowledgement"
        assert authorized["reserved_amount_cents"] == fx.read_order(
            before["id"])["reserved_amount_cents"]

    def test_replaying_an_action_is_a_state_error_rather_than_a_silent_success(self, api):
        """PRD §2.10: "Only then are the per-machine from-state guards evaluated:
        `ERR_INVALID_RECEIPT_STATE` on receipt sampling, verdict and rejection; `ERR_INVALID_ORDER_STATE` on
        order authorize, assign, unassign, start, uplift posting, complete, abort and cancel;
        `ERR_INVALID_TANK_STATE` on tank service-status changes, quality release, quarantine and tank
        sampling; `ERR_INVALID_ASSET_STATE` on asset status changes and filter changes;
        `ERR_INVALID_SPILL_STATE` on spill escalate, contain, remediate and close;
        `ERR_INVALID_INVOICE_STATE` on invoice issue, dispute, dispute resolution, void and payment; and
        `ERR_INVALID_RUN_STATE` on reconciliation measure and post."
        PRD §3.6: "Authorising an order, `REQUESTED → AUTHORIZED`, is an `IntoPlaneAgent` action and the
        single densest gate in the system."

        Design: Corner/endpoints/no_endpoint_is_idempotent_by_replay
        """
        env = fx.setup_truck_order(target_state="AUTHORIZED",
                                   account_overrides={"credit_limit_cents": BIG_CREDIT})
        order_id = env["order"]["id"]
        version_after_first = fx.read_order(order_id)["version"]

        validate_error(api.authorize_order(order_id, fx.AGENT),
                       ApiErrorId.ERR_INVALID_ORDER_STATE, 409)

        again = fx.read_order(order_id)
        assert again["status"] == "AUTHORIZED"
        assert again["version"] == version_after_first, \
            "the refused replay committed nothing, so no second reservation was taken"

    def test_the_meta_block_is_identical_in_shape_across_success_and_failure(self, api):
        """PRD §4: "Every response, successful or otherwise, uses the envelope defined in §2.2."
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the request that starts
        with `req_`."
        PRD §2.2: "The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three
        fractional digits."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."
        PRD §2.2: "The `meta` object for error responses contains only `api_request_id` and
        `api_request_timestamp`."

        Design: Corner/endpoints/every_response_carries_the_meta_block
        """
        env = fx.setup_farm_with_released_tank()

        created = api.create_fuel_farm(F.create_fuel_farm_payload(), fx.ADMIN)
        validate_success(created, 201)
        read = api.get_storage_tank(env["tank"]["id"], fx.OPERATOR)
        validate_success(read, 200)
        conflict = api.release_tank_quality(env["tank"]["id"], fx.INSPECTOR_B)
        validate_error(conflict, ApiErrorId.ERR_INVALID_TANK_STATE, 409)

        for response, expected_type in ((created, "object"), (read, "object"),
                                        (conflict, "error")):
            body = response.json()
            assert set(body.keys()) == {"data", "meta", "response_type"}
            assert body["response_type"] == expected_type
            assert body["meta"]["api_request_id"].startswith("req_")
            assert isinstance(body["meta"]["api_request_timestamp"], str)

        assert set(conflict.json()["meta"].keys()) == {"api_request_id",
                                                       "api_request_timestamp"}
        assert set(conflict.json()["data"].keys()) == {"error_id", "message"}
