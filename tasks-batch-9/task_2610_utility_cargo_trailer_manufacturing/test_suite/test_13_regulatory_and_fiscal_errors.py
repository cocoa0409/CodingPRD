"""Regulatory, identity and fiscal refusals from PRD 3.2 through 3.9.

These are the rules that reject a request whose shape and whose state are both
fine: a segregation-of-duties identity clash, an unmet lamp conjunction, a
tooling mismatch, an overshot weight budget and the dealer's fiscal gates.
"""

import test_helpers as H
from test_helpers import (
    ASSEMBLY_TECH,
    CERT_OFFICER,
    SALES_ADMIN,
    WELD_SUPERVISOR,
    validate_error,
    validate_paginated,
)


class TestRegulatoryAndToolingRefusals:
    def test_the_officer_who_certified_the_model_may_not_mint_its_vin(self, api):
        """An identity clash, not a role clash: co-1 holds the right role.

        PRD 3.7: "And the acting officer's `X-User-ID` must differ from the
        `certified_by_user_id` recorded on the trailer's model, per the
        segregation-of-duties rule of §2.11, with a match refused as
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/errors/error_certifying_officer_cannot_issue_the_label_for_that_model
        """
        plant = H.setup_plant(api)
        assert plant["model"]["certified_by_user_id"] == H.CERT_OFFICER_1_ID
        staged = H.unit_at_road_test_passed(plant, api)

        response = api.issue_label(staged["unit"]["id"], H.label_payload(), headers=CERT_OFFICER)

        validate_error(response, H.ERR_SEGREGATION_OF_DUTIES)
        labels, meta = validate_paginated(
            api.list_labels(staged["unit"]["id"], headers=SALES_ADMIN)
        )
        assert labels == []
        assert meta["total_count"] == 0
        unit = H.read_unit(api, staged["unit"]["id"])
        assert unit["vin"] is None
        assert unit["build_status"] == H.BuildStatus.ROAD_TEST_PASSED

    def test_three_reflex_reflectors_fail_the_lamp_conjunction(self, api):
        """Four of the five terms holding is still a failure of the whole set.

        PRD 3.4: "There must be at least 4 reflex reflectors."

        Design: Corner/errors/error_lighting_stage_with_three_reflex_reflectors_is_rejected
        """
        plant = H.setup_plant(api)
        staged = H.unit_at_frame_welded(plant, api)

        response = api.install_systems(
            staged["unit"]["id"],
            H.lighting_payload(reflex_reflector_count=3),
            headers=ASSEMBLY_TECH,
        )

        validate_error(response, H.ERR_LIGHTING_NOT_COMPLIANT)
        unit = H.read_unit(api, staged["unit"]["id"])
        H.assert_unit_dimensions(
            unit, H.BuildStatus.FRAME_WELDED, H.ComplianceStatus.NOT_VERIFIED
        )
        assert unit["clearance_lamp_count"] is None

    def test_a_second_trailer_cannot_reuse_a_serial_number(self, api):
        """Serial uniqueness is plant-wide and leaves active_unit_count alone.

        PRD 2.7: "`model_code`, `dealer_code`, `jig_code`, `lane_code`,
        `serial_number` and `claim_ref` are each unique across their collection, on
        model creation, dealer enrollment, jig commissioning, lane commissioning,
        unit creation and claim filing."

        Design: Corner/errors/error_duplicate_serial_number_is_rejected
        """
        H.set_clock(api, H.CLOCK_DEFAULT_UTC)
        model = H.create_certified_model(api)
        H.open_unit(api, model["id"], "SN-000101")

        response = api.create_unit(
            H.unit_payload(model["id"], "SN-000101", planned_start_date="2026-08-04T07:00:00Z"),
            headers=WELD_SUPERVISOR,
        )

        validate_error(response, H.ERR_DUPLICATE_CODE)
        assert H.read_model(api, model["id"])["active_unit_count"] == 1
        units, meta = validate_paginated(api.list_units(headers=WELD_SUPERVISOR))
        assert len(units) == 1
        assert meta["total_count"] == 1

    def test_a_jig_tooled_for_another_frame_family_cannot_take_the_trailer(self, api):
        """An empty calendar and a fresh version still cannot save the request.

        PRD 3.2: "The jig's `frame_design_code` must equal the model's
        `frame_design_code`; a jig tooled for a different frame family produces
        `ERR_JIG_DESIGN_MISMATCH`."

        Design: Corner/errors/error_jig_design_mismatch_is_rejected
        """
        H.set_clock(api, H.CLOCK_DEFAULT_UTC)
        model = H.create_certified_model(api)
        wrong_jig = H.commission_jig(api, **H.JIG_SC)
        unit = H.open_unit(api, model["id"])

        response = api.reserve_jig(
            wrong_jig["id"],
            H.reservation_payload(unit["id"], wrong_jig["version"]),
            headers=WELD_SUPERVISOR,
        )

        validate_error(response, H.ERR_JIG_DESIGN_MISMATCH)
        after_jig = H.read_jig(api, wrong_jig["id"])
        assert after_jig["reserved_minutes_total"] == 0
        assert after_jig["version"] == wrong_jig["version"]
        after_unit = H.read_unit(api, unit["id"])
        assert after_unit["build_status"] == H.BuildStatus.PLANNED
        assert after_unit["gvwr_lbs"] is None

    def test_one_pound_past_the_budget_is_refused(self, api):
        """4321 lb against 4320 lb of payload would leave minus one.

        PRD 3.5: "The admission rule follows directly: an install is refused when
        charging it would drive `payload_capacity_lbs` below zero, and a
        `payload_capacity_lbs` of exactly zero is admissible — a trailer may be
        loaded to precisely its rating and no further."

        Design: Corner/errors/error_option_that_overshoots_the_payload_budget_is_rejected
        """
        plant = H.setup_plant(api)
        staged = H.unit_at_frame_welded(plant, api)

        response = api.create_option_install(
            staged["unit"]["id"],
            H.option_payload(
                option_code="SPECIALTY_FLOORING",
                quantity=1,
                unit_weight_lbs=H.TA_PAYLOAD_CAPACITY_LBS + 1,
                unit_price_cents=199900,
                labor_hours=4.0,
            ),
            headers=ASSEMBLY_TECH,
        )

        validate_error(response, H.ERR_PAYLOAD_CAPACITY_EXCEEDED)
        options, meta = validate_paginated(
            api.list_option_installs(
                staged["unit"]["id"], params={"include_removed": "true"}, headers=ASSEMBLY_TECH
            )
        )
        assert options == []
        assert meta["total_count"] == 0
        unit = H.read_unit(api, staged["unit"]["id"])
        assert unit["curb_weight_lbs"] == H.TA_BASE_CURB_WEIGHT_LBS
        assert unit["payload_capacity_lbs"] == H.TA_PAYLOAD_CAPACITY_LBS


class TestAllocationSelectorRefusals:
    def test_a_named_trailer_of_the_wrong_model_reports_the_mismatch_first(self, api):
        """The model comparison runs before the eligibility predicate.

        PRD 3.8: "A named trailer that belongs to a different model than the
        order's is refused earlier, with `ERR_UNIT_MODEL_MISMATCH`."

        Design: Corner/errors/error_unit_model_mismatch_on_an_explicit_allocation_is_rejected
        """
        plant = H.setup_plant(api)
        other_model = H.create_model(api, **H.MODEL_SC)
        other_unit = H.open_unit(api, other_model["id"], "SN-000201")
        order = H.place_order(api, plant["dealer"]["id"], plant["model"]["id"])
        dealer_version = H.read_dealer(api, plant["dealer"]["id"])["version"]

        response = api.allocate_order(
            order["id"],
            H.allocation_payload(dealer_version, unit_id=other_unit["id"]),
            headers=SALES_ADMIN,
        )

        validate_error(response, H.ERR_UNIT_MODEL_MISMATCH)
        pending = H.read_order(api, order["id"])
        assert pending["status"] == H.OrderStatus.PENDING
        assert pending["allocated_unit_id"] is None
        after_unit = H.read_unit(api, other_unit["id"])
        assert after_unit["build_status"] == H.BuildStatus.PLANNED
        assert after_unit["dealer_order_id"] is None
        dealer = H.read_dealer(api, plant["dealer"]["id"])
        H.assert_floor_plan_conserved(dealer, 0)
        assert dealer["version"] == dealer_version

    def test_an_empty_candidate_set_is_its_own_error(self, api):
        """With no unit in stock the ranked selector has nothing to rank.

        PRD 3.8: "The first candidate after that sort is the allocated trailer, and
        an empty candidate set is refused with `ERR_NO_ALLOCATABLE_UNIT`."

        Design: Corner/errors/error_allocation_with_no_stocked_unit_is_rejected
        """
        plant = H.setup_plant(api)
        order = H.place_order(api, plant["dealer"]["id"], plant["model"]["id"])
        dealer_version = H.read_dealer(api, plant["dealer"]["id"])["version"]

        response = api.allocate_order(
            order["id"], H.allocation_payload(dealer_version), headers=SALES_ADMIN
        )

        validate_error(response, H.ERR_NO_ALLOCATABLE_UNIT)
        pending = H.read_order(api, order["id"])
        assert pending["status"] == H.OrderStatus.PENDING
        assert pending["floor_plan_status"] == H.FloorPlanStatus.NONE
        dealer = H.read_dealer(api, plant["dealer"]["id"])
        assert dealer["allocations_ytd_count"] == 0
        assert dealer["version"] == dealer_version


class TestDealerFiscalGates:
    def test_a_dealer_on_credit_hold_cannot_take_stock_however_much_headroom_it_has(self, api):
        """The hold bites before the quota and the limit are consulted.

        PRD 3.8: "The dealer's `status` must be `ACTIVE`; a dealer on credit hold is
        refused with `ERR_DEALER_CREDIT_HOLD`."

        Design: Corner/errors/error_allocation_for_a_dealer_on_credit_hold_is_rejected
        """
        plant = H.setup_plant(api)
        staged = H.unit_in_stock(plant, api)
        order = H.place_order(api, plant["dealer"]["id"], plant["model"]["id"])
        held = H.adjust_floor_plan(
            api, plant["dealer"]["id"], "CREDIT_HOLD", 0, note="lender placed the account on hold"
        )
        assert held["status"] == H.DealerStatus.CREDIT_HOLD

        response = api.allocate_order(
            order["id"], H.allocation_payload(held["version"]), headers=SALES_ADMIN
        )

        validate_error(response, H.ERR_DEALER_CREDIT_HOLD)
        pending = H.read_order(api, order["id"])
        assert pending["status"] == H.OrderStatus.PENDING
        assert pending["allocated_unit_id"] is None
        assert H.read_unit(api, staged["unit"]["id"])["build_status"] == (
            H.BuildStatus.RELEASED_TO_STOCK
        )
        dealer = H.read_dealer(api, plant["dealer"]["id"])
        assert dealer["status"] == H.DealerStatus.CREDIT_HOLD
        H.assert_floor_plan_conserved(dealer, 0)

    def test_a_second_august_allocation_against_a_quota_of_one_is_refused(self, api):
        """The quota gate answers before the floor-plan limit is consulted.

        PRD 3.8: "The dealer's `allocations_current_month_count` plus one must be no
        greater than its `allocation_quota_per_month`, so an allocation that lands
        exactly on the quota is accepted and the next one is refused with
        `ERR_ALLOCATION_QUOTA_EXCEEDED`."

        Design: Corner/errors/error_second_allocation_in_a_month_with_quota_one_is_rejected
        """
        plant = H.setup_plant(api, dealer_overrides={"allocation_quota_per_month": 1})
        H.unit_in_stock(plant, api, "SN-000101", H.JIG_WINDOW_1, H.LANE_WINDOW_1)
        second = H.unit_in_stock(plant, api, "SN-000102", H.JIG_WINDOW_2, H.LANE_WINDOW_2)
        first_order = H.place_order(
            api, plant["dealer"]["id"], plant["model"]["id"], po_ref="PO-10001"
        )
        second_order = H.place_order(
            api, plant["dealer"]["id"], plant["model"]["id"], po_ref="PO-10002"
        )
        H.allocate_order(api, first_order["id"], plant["dealer"]["id"])
        dealer_version = H.read_dealer(api, plant["dealer"]["id"])["version"]

        response = api.allocate_order(
            second_order["id"], H.allocation_payload(dealer_version), headers=SALES_ADMIN
        )

        validate_error(response, H.ERR_ALLOCATION_QUOTA_EXCEEDED)
        pending = H.read_order(api, second_order["id"])
        assert pending["status"] == H.OrderStatus.PENDING
        assert pending["allocated_unit_id"] is None
        unit = H.read_unit(api, second["unit"]["id"])
        assert unit["build_status"] == H.BuildStatus.RELEASED_TO_STOCK
        assert unit["dealer_order_id"] is None
        dealer = H.read_dealer(api, plant["dealer"]["id"])
        assert dealer["allocations_current_month_count"] == 1
        assert dealer["allocations_ytd_count"] == 1
        H.assert_floor_plan_conserved(dealer, H.ORDER1_DRAW_CENTS)


class TestWarrantyFilingGates:
    def test_labor_hours_a_hundredth_past_the_ceiling_are_refused(self, api):
        """4.376 hours is the first refused value for an AXLE claim.

        PRD 3.9: "The published allowances are 3.5 hours for `AXLE`, 2.5 for
        `BRAKE`, 1.5 for `LIGHTING`, 6.0 for `FRAME`, 4.0 for `FLOORING` and 2.0
        for `COUPLER`, and the ceiling is that allowance multiplied by one and a
        quarter — so a brake claim may be filed for up to 3.125 hours and a frame
        claim for up to 7.5 hours."
        PRD 3.9: "The comparison is inclusive: hours landing exactly on the ceiling
        are accepted, and hours above it are refused with
        `ERR_LABOR_HOURS_EXCEED_FLAT_RATE`."

        Design: Corner/errors/error_labor_hours_above_the_flat_rate_ceiling_are_rejected
        """
        plant = H.setup_plant(api)
        staged = H.unit_shipped(plant, api)
        H.set_clock(api, H.CLOCK_SEP_01)
        assert (
            H.FLAT_RATE_HOURS["AXLE"] * H.FLAT_RATE_CEILING_MULTIPLIER
            == H.CLAIM_AXLE_HOURS_CEILING
        )

        response = api.create_claim(
            H.claim_payload(
                staged["unit"]["id"],
                plant["dealer"]["id"],
                complaint_code="AXLE",
                labor_hours=H.CLAIM_AXLE_HOURS_OVER_CEILING,
            ),
            headers=SALES_ADMIN,
        )

        validate_error(response, H.ERR_LABOR_HOURS_EXCEED_FLAT_RATE)
        claims, meta = validate_paginated(api.list_claims(headers=SALES_ADMIN))
        assert claims == []
        assert meta["total_count"] == 0
        H.assert_money(H.read_dealer(api, plant["dealer"]["id"])["warranty_receivable_cents"], 0)

    def test_a_failure_months_past_the_goodwill_tail_is_refused_at_filing(self, api):
        """Beyond expiry plus 90 days there is no prorated band left to apply.

        PRD 3.9: "Separately, the `failure_date` must fall no more than 90 days
        past the trailer's warranty expiry, where expiry is the trailer's
        `warranty_start_date` plus 730 days; a failure later than that closes the
        goodwill window and is refused with `ERR_WARRANTY_WINDOW_EXPIRED`."

        Design: Corner/errors/error_claim_far_past_the_warranty_expiry_is_rejected
        """
        plant = H.setup_plant(api)
        staged = H.unit_shipped(plant, api)
        H.set_clock(api, H.CLOCK_2029_JAN_02)

        response = api.create_claim(
            H.claim_payload(
                staged["unit"]["id"],
                plant["dealer"]["id"],
                failure_date=H.FAILURE_FAR_PAST_GOODWILL,
            ),
            headers=SALES_ADMIN,
        )

        validate_error(response, H.ERR_WARRANTY_WINDOW_EXPIRED)
        claims, meta = validate_paginated(api.list_claims(headers=SALES_ADMIN))
        assert claims == []
        assert meta["total_count"] == 0
        H.assert_instant(
            H.read_unit(api, staged["unit"]["id"])["warranty_start_date"],
            H.WARRANTY_START_AUG_05,
        )
        H.assert_money(H.read_dealer(api, plant["dealer"]["id"])["warranty_receivable_cents"], 0)
