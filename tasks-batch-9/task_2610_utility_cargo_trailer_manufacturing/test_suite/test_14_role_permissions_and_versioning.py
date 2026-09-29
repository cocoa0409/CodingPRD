"""Role lanes, the shared-asset version fields and immediate visibility.

PRD 2.1 separates the seven roles by lane while PRD 2.11 separates the two
halves of certification by identity, and PRD 2.8 guards the two shared
aggregates with explicit version fields. The last tests here read a write
response and the rows it touched in the same breath.
"""

import pytest

import test_helpers as H
from test_helpers import (
    ALL_ROLE_HEADERS,
    CERT_OFFICER_2,
    PLANT_ENGINEER,
    SALES_ADMIN,
    WELD_SUPERVISOR,
    validate_error,
    validate_paginated,
    validate_success,
)


JIG_WINDOW_TWO_HOURS = ("2026-08-03T12:00:00Z", "2026-08-03T14:00:00Z")
JIG_WINDOW_TWO_HOURS_OCCUPANCY_END = "2026-08-03T14:45:00Z"


class TestPlantEngineerAssetRegistry:
    def test_the_engineer_registers_configures_and_commissions_but_never_signs(self, api):
        """All four engineering writes land, and the decision is still refused.

        PRD 2.1: "A `PlantEngineer` is the plant engineering administrator: it owns
        model configurations and the weld-jig and test-lane asset registry, but it
        may never certify a model it submitted, because the certification decision
        belongs exclusively to `CertificationOfficer`."
        PRD 2.1: "When the role named in `X-User-Role` does not appear in the
        authorized-role list of the endpoint being called (see §4), the request is
        rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

        Design: Corner/rbac/rbac_plant_engineer_performs_all_four_of_its_exclusive_operations
        """
        H.set_clock(api, H.CLOCK_DEFAULT_UTC)

        model = validate_success(
            api.create_model(H.model_payload(), headers=PLANT_ENGINEER), expected_status=201
        )
        submitted = validate_success(
            api.submit_model(model["id"], H.submission_payload(), headers=PLANT_ENGINEER)
        )
        jig = validate_success(
            api.create_jig(H.jig_payload(), headers=PLANT_ENGINEER), expected_status=201
        )
        lane = validate_success(
            api.create_lane(H.lane_payload(), headers=PLANT_ENGINEER), expected_status=201
        )

        assert submitted["certification_status"] == H.CertificationStatus.IN_ENGINEERING_REVIEW
        assert submitted["provisional_gvwr_lbs"] == H.TA_PROVISIONAL_GVWR_LBS
        assert submitted["certified_gvwr_lbs"] is None
        assert jig["changeover_buffer_min"] == H.DEFAULT_CHANGEOVER_BUFFER_MIN
        assert jig["reserved_minutes_total"] == 0
        assert lane["max_concurrent_tests"] == H.DEFAULT_LANE_CAPACITY
        assert lane["surface_type"] == "ASPHALT"
        refused = api.decide_model(
            model["id"],
            H.decision_payload(H.CertificationDecision.CERTIFIED),
            headers=PLANT_ENGINEER,
        )
        validate_error(refused, H.ERR_ROLE_NOT_PERMITTED)
        after = H.read_model(api, model["id"])
        assert after["certification_status"] == H.CertificationStatus.IN_ENGINEERING_REVIEW
        assert after["certified_by_user_id"] is None


class TestTheClockIsOpenToEveryRole:
    def test_all_seven_roles_move_the_clock_and_the_seventh_setting_stands(self, api):
        """The dealer identity moves the clock too, though no dealer row exists.

        PRD 2.4: "Any of the seven roles may move it by supplying a `to_iso8601`
        instant, and the response reports the new setting as `current_utc`."

        Design: Corner/rbac/rbac_every_one_of_the_seven_roles_may_move_the_logical_clock
        """
        H.set_clock(api, H.CLOCK_DEFAULT_UTC)
        assert len(ALL_ROLE_HEADERS) == 7

        reported = [
            validate_success(api.set_clock(instant, headers=headers))
            for headers, instant in zip(ALL_ROLE_HEADERS, H.CLOCK_ROLE_SWEEP)
        ]

        assert len(reported) == 7
        for setting, instant in zip(reported, H.CLOCK_ROLE_SWEEP):
            H.assert_instant(setting["current_utc"], instant)
        H.assert_instant(reported[-1]["current_utc"], H.CLOCK_ROLE_SWEEP[-1])


class TestDealerScopedListing:
    def test_a_dealer_listing_orders_sees_only_its_own_purchase_orders(self, api):
        """The same endpoint is confined for the dealer and open for the administrator.

        PRD 2.1: "Concretely, a `Dealer` caller must supply its own `id` as the body
        `dealer_id` when placing a dealer order or filing a warranty claim; when
        cancelling a dealer order, the order's own `dealer_id` must equal
        `X-User-ID`; when answering an information request on a claim, the claim's
        `dealer_id` must equal `X-User-ID`; when reading a single dealer record, the
        dealer identifier in the path must equal `X-User-ID`; and when listing dealer
        orders or warranty claims, the `dealer_id` filter must be supplied and must
        equal `X-User-ID`."
        PRD 2.1: "A `SalesAdmin` is deliberately unscoped across dealers and is never
        subject to this check."

        Design: Corner/rbac/rbac_dealer_scoped_list_returns_only_its_own_orders
        """
        plant = H.setup_plant(api)
        other_dealer = H.enroll_dealer(api, **H.DEALER_002)
        mine = H.place_order(
            api, plant["dealer"]["id"], plant["model"]["id"], po_ref="PO-10001"
        )
        theirs = H.place_order(
            api, other_dealer["id"], plant["model"]["id"], po_ref="PO-20001"
        )

        scoped, scoped_meta = validate_paginated(
            api.list_orders(
                params={"dealer_id": plant["dealer"]["id"]},
                headers=H.make_dealer_headers(plant["dealer"]["id"]),
            )
        )
        unscoped, unscoped_meta = validate_paginated(api.list_orders(headers=SALES_ADMIN))

        assert [row["id"] for row in scoped] == [mine["id"]]
        assert scoped[0]["po_ref"] == "PO-10001"
        assert theirs["id"] not in [row["id"] for row in scoped]
        assert scoped_meta["total_count"] == 1
        assert {row["id"] for row in unscoped} == {mine["id"], theirs["id"]}
        assert unscoped_meta["total_count"] == 2
        for row in unscoped:
            assert row["status"] == H.OrderStatus.PENDING
            assert row["floor_plan_status"] == H.FloorPlanStatus.NONE


class TestSegregationIsByIdentityNotByRole:
    def test_a_second_officer_holding_the_same_role_completes_the_build(self, api):
        """co-2 needs no extra grant; it simply is not the officer on the model row.

        PRD 2.11: "Both halves of certification belong to `CertificationOfficer`:
        signing a model's GVWR, and minting the VIN and certification label for a
        trailer built to that model."
        PRD 2.11: "Completing a build therefore always requires at least two distinct
        certification-officer identities."

        Design: Corner/rbac/rbac_a_second_certification_officer_completes_the_build
        """
        plant = H.setup_plant(api)
        staged = H.unit_at_road_test_passed(plant, api)
        assert plant["model"]["certified_by_user_id"] == H.CERT_OFFICER_1_ID

        label = validate_success(
            api.issue_label(staged["unit"]["id"], H.label_payload(), headers=CERT_OFFICER_2),
            expected_status=201,
        )

        assert label["issued_by_user_id"] == H.CERT_OFFICER_2_ID
        assert label["status"] == H.LabelStatus.ISSUED
        assert label["vin"] == H.VIN_FIRST
        assert H.read_model(api, plant["model"]["id"])["certified_by_user_id"] == (
            H.CERT_OFFICER_1_ID
        )
        unit = H.read_unit(api, staged["unit"]["id"])
        assert unit["build_status"] == H.BuildStatus.RELEASED_TO_STOCK
        assert unit["vin"] == H.VIN_FIRST


class TestDealerNeverWritesProduction:
    def test_a_dealer_cannot_open_a_build_record(self, api):
        """A dealer that could open build records would inflate the active count.

        PRD 2.1: "A `Dealer` never writes a production record of any kind — no unit,
        reservation, inspection, systems stage, option install, road test or
        certification label."

        Design: Corner/rbac/rbac_dealer_cannot_open_a_production_record
        """
        plant = H.setup_plant(api)

        response = api.create_unit(
            H.unit_payload(plant["model"]["id"]),
            headers=H.make_dealer_headers(plant["dealer"]["id"]),
        )

        validate_error(response, H.ERR_ROLE_NOT_PERMITTED)
        units, meta = validate_paginated(api.list_units(headers=WELD_SUPERVISOR))
        assert units == []
        assert meta["total_count"] == 0
        assert H.read_model(api, plant["model"]["id"])["active_unit_count"] == 0


class TestDealerVersionAdvancesOnEveryWrite:
    def test_the_retry_on_a_fresh_dealer_version_succeeds_and_prices_one_tier_up(self, api):
        """Re-reading the row the first allocation bumped lets the second one through.

        PRD 3.8: "The dealer's `allocations_current_month_count`,
        `allocations_ytd_count` and `floor_plan_available_cents` are all recomputed
        and the dealer's `version` increments — which is precisely what makes a
        second allocation request holding the old `expected_dealer_version` stale."
        PRD 2.8: "Such a request is rejected with `ERR_STALE_DEALER_VERSION` (HTTP
        412) so that the client can re-read and re-decide; the same allocation
        retried with the fresh `version` succeeds."

        Design: Corner/cross_cutting_complexity_layers/layer_dealer_version_increments_on_every_write_and_the_retry_succeeds
        """
        plant = H.setup_plant(api)
        enrollment_version = plant["dealer"]["version"]
        H.unit_in_stock(plant, api, "SN-000101", H.JIG_WINDOW_1, H.LANE_WINDOW_1)
        second = H.unit_in_stock(plant, api, "SN-000102", H.JIG_WINDOW_2, H.LANE_WINDOW_2)
        first_order = H.place_order(
            api, plant["dealer"]["id"], plant["model"]["id"], po_ref="PO-10001"
        )
        H.allocate_order(api, first_order["id"], plant["dealer"]["id"])
        after_first = H.read_dealer(api, plant["dealer"]["id"])
        assert after_first["version"] > enrollment_version
        second_order = H.place_order(
            api, plant["dealer"]["id"], plant["model"]["id"], po_ref="PO-10002"
        )

        allocated = validate_success(
            api.allocate_order(
                second_order["id"],
                H.allocation_payload(after_first["version"]),
                headers=SALES_ADMIN,
            )
        )

        assert allocated["status"] == H.OrderStatus.ALLOCATED
        assert allocated["allocated_unit_id"] == second["unit"]["id"]
        assert allocated["volume_discount_pct"] == pytest.approx(
            H.ORDER2_DISCOUNT_PCT, abs=0.001
        )
        H.assert_money(allocated["freight_cents"], H.ORDER2_FREIGHT_CENTS)
        H.assert_money(allocated["invoice_total_cents"], H.ORDER2_TOTAL_CENTS)
        H.assert_money(allocated["floor_plan_draw_cents"], H.ORDER2_DRAW_CENTS)
        dealer = H.read_dealer(api, plant["dealer"]["id"])
        H.assert_floor_plan_conserved(dealer, H.TWO_ORDER_OUTSTANDING_CENTS)
        assert dealer["version"] > after_first["version"]
        assert dealer["allocations_ytd_count"] == 2


class TestJigVersionAdvancesOnEveryReservation:
    def test_two_units_on_one_jig_accumulate_minutes_under_a_re_read_version(self, api):
        """The minutes add to 240 rather than being overwritten by the second booking.

        PRD 3.2: "An accepted reservation is created against that jig with `jig_id`
        set, `status` `RESERVED`, and two computed quantities: `duration_minutes`,
        the whole minutes between `window_start_at` and `window_end_at` with the
        changeover buffer **excluded**, and `occupancy_end_at` as described above."
        PRD 2.8: "A caller whose `expected_weld_jig_version` is lower than the jig's
        current `version` booked its window against a superseded calendar — another
        reservation has been added, or a model revision released one and gave the
        minutes back — so the request is rejected with `ERR_STALE_JIG_VERSION` (HTTP
        412) rather than being silently squeezed into a calendar the caller never
        saw."

        Design: Corner/cross_cutting_complexity_layers/layer_weld_jig_version_increments_on_each_reservation
        """
        plant = H.setup_plant(api)
        jig_v0 = plant["jig"]["version"]
        first_unit = H.open_unit(api, plant["model"]["id"], "SN-000101")
        second_unit = H.open_unit(api, plant["model"]["id"], "SN-000102")
        H.reserve_jig_window(api, plant["jig"]["id"], first_unit["id"], window=H.JIG_WINDOW_1)
        jig_v1 = H.read_jig(api, plant["jig"]["id"])["version"]
        assert jig_v1 > jig_v0

        reservation = validate_success(
            api.reserve_jig(
                plant["jig"]["id"],
                H.reservation_payload(second_unit["id"], jig_v1, window=JIG_WINDOW_TWO_HOURS),
                headers=WELD_SUPERVISOR,
            ),
            expected_status=201,
        )

        assert reservation["status"] == H.ReservationStatus.RESERVED
        assert reservation["duration_minutes"] == 120
        H.assert_instant(
            reservation["occupancy_end_at"], JIG_WINDOW_TWO_HOURS_OCCUPANCY_END
        )
        jig = H.read_jig(api, plant["jig"]["id"])
        assert jig["reserved_minutes_total"] == 240
        assert jig["version"] > jig_v1
        unit = H.read_unit(api, second_unit["id"])
        assert unit["build_status"] == H.BuildStatus.JIG_RESERVED
        assert unit["gvwr_lbs"] == H.TA_CERTIFIED_GVWR_LBS


class TestActiveUnitCountIsACountNotACounter:
    def test_a_shipment_drops_the_active_count_while_the_row_stays_intact(self, api):
        """Three trailers built, one shipped, and the count settles at two.

        PRD 2.10: "A model's `active_unit_count` equals the count of units built to
        that model whose `build_status` is neither `SHIPPED` nor `SCRAPPED`, and it is
        recomputed on every change to any of its units' `build_status`."
        PRD 3.8: "Critically, the order's `floor_plan_status` stays `DRAWN`:
        delivering a trailer does not repay the dealer's floor plan, and only a payoff
        adjustment does that."

        Design: Corner/cross_cutting_complexity_layers/layer_active_unit_count_reconciles_after_a_shipment
        """
        plant = H.setup_plant(api)
        staged = H.unit_in_stock(plant, api, "SN-000101", H.JIG_WINDOW_1, H.LANE_WINDOW_1)
        H.unit_at_road_test_passed(plant, api, "SN-000102", H.JIG_WINDOW_2, H.LANE_WINDOW_2)
        H.open_unit(api, plant["model"]["id"], "SN-000103")
        assert H.read_model(api, plant["model"]["id"])["active_unit_count"] == 3
        staged = H.order_allocated(plant, api, staged=staged)

        delivered = H.deliver_order(api, staged["order"]["id"])

        assert delivered["status"] == H.OrderStatus.DELIVERED
        assert delivered["floor_plan_status"] == H.FloorPlanStatus.DRAWN
        unit = H.read_unit(api, staged["unit"]["id"])
        assert unit["build_status"] == H.BuildStatus.SHIPPED
        H.assert_instant(unit["warranty_start_date"], H.CLOCK_DEFAULT_UTC)
        assert unit["model_id"] == plant["model"]["id"]
        assert unit["gvwr_lbs"] == H.TA_CERTIFIED_GVWR_LBS
        assert H.read_model(api, plant["model"]["id"])["active_unit_count"] == 2
        H.assert_floor_plan_conserved(
            H.read_dealer(api, plant["dealer"]["id"]), H.ORDER1_DRAW_CENTS
        )


class TestAllocationResponseIsAlreadyAuthoritative:
    def test_the_allocation_response_matches_three_immediate_reads_field_for_field(self, api):
        """No settling: the write body and the reads taken straight after agree.

        PRD 2.2: "Unless otherwise noted, operations that create or modify a resource
        will return the created or updated resource object in the data field."
        PRD 3.8: "A successful allocation moves the order `PENDING` → `ALLOCATED`,
        sets `allocated_unit_id` to the chosen trailer and `allocated_at` to the
        logical clock's current instant, and writes all six invoice fields."

        Design: Corner/consistency_model/consistency_allocation_response_already_carries_every_derived_field
        """
        plant = H.setup_plant(api)
        staged = H.unit_in_stock(plant, api)
        order = H.place_order(api, plant["dealer"]["id"], plant["model"]["id"])

        written = validate_success(
            api.allocate_order(
                order["id"],
                H.allocation_payload(plant["dealer"]["version"]),
                headers=SALES_ADMIN,
            )
        )

        assert written["status"] == H.OrderStatus.ALLOCATED
        assert written["allocated_unit_id"] == staged["unit"]["id"]
        H.assert_money(written["invoice_subtotal_cents"], H.ORDER1_SUBTOTAL_CENTS)
        H.assert_money(written["volume_discount_cents"], H.ORDER1_DISCOUNT_CENTS)
        H.assert_money(written["freight_cents"], H.ORDER1_FREIGHT_CENTS)
        H.assert_money(written["invoice_total_cents"], H.ORDER1_TOTAL_CENTS)
        H.assert_money(written["floor_plan_draw_cents"], H.ORDER1_DRAW_CENTS)
        read_back = H.read_order(api, order["id"])
        for field in (
            "status",
            "allocated_unit_id",
            "invoice_subtotal_cents",
            "volume_discount_cents",
            "freight_cents",
            "invoice_total_cents",
            "floor_plan_draw_cents",
        ):
            assert read_back[field] == written[field]
        dealer = H.read_dealer(api, plant["dealer"]["id"])
        H.assert_floor_plan_conserved(dealer, H.ORDER1_DRAW_CENTS)
        H.assert_money(dealer["floor_plan_available_cents"], H.ORDER1_AVAILABLE_CENTS)
        assert dealer["allocations_current_month_count"] == 1
        unit = H.read_unit(api, staged["unit"]["id"])
        assert unit["build_status"] == H.BuildStatus.ALLOCATED
        assert unit["dealer_order_id"] == order["id"]
