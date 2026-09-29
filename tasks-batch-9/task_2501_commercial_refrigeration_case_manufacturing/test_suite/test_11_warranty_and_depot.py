"""Warranty coverage, depot reservations and the reserve ledger (PRD §3.9).

Coverage is measured from the handoff instant, reservations withhold depot stock
without consuming it, and a denial compensates a reservation exactly.
"""

import pytest

from test_helpers import *  # noqa: F401,F403

GASKET_PART = {
    "part_number": "GSK-8-OH",
    "description": "Door gasket, 8 ft MT case",
    "region_code": "OH",
    "on_hand_qty": 5,
    "unit_cost_cents": 41000,
    "min_stock_qty": 2,
}

COMPRESSOR_PART = {
    "part_number": "CMP-4200",
    "description": "Scroll compressor, 4200 g charge platform",
    "region_code": "OH",
    "on_hand_qty": 3,
    "unit_cost_cents": 148000,
    "min_stock_qty": 1,
}

SIX_FOOT_MODEL = {
    "model_code": "MDL-MT-6",
    "application": "GRAB_AND_GO",
    "temperature_class": "MT",
    "system_type": "REMOTE",
    "nominal_length_ft": 6,
    "tda_sqft": 19.8,
    "charge_grams": 3600,
    "line_set_length_ft": 110,
    "door_type": "OPEN",
    "glass_door_count": 0,
    "curtain_layers": 2,
    "discharge_velocity_mps": 0.50,
    "case_air_temp_c": 3.0,
    "ambient_dew_point_c": 15.5,
    "lighting_w_per_ft": 11.0,
    "fan_w_per_ft": 9.0,
    "defrost_cycles_per_day": 4,
}


class TestCoverageWindow:
    """PRD §3.9 — the coverage end is inclusive and measured from the handoff."""

    def test_01_coverage_includes_the_twelfth_month_anniversary_but_not_the_day_after(
        self, api
    ):
        """A gasket reported on 2027-09-17 is covered; 2027-09-18 is not.

        PRD §3.9: "The end boundary is inclusive, so a failure reported exactly at
        the coverage end is in warranty; and because `warranty_start_date` is only
        ever stamped by a shipment handoff, a unit that has never been handed off
        yields `in_warranty` false."

        Design: Corner/calculations/warranty_coverage_end_boundary_includes_twelfth_month_anniversary
        """
        ctx = setup_handed_off_shipment()
        unit = refresh_work_orders(ctx)[0]
        assert_instant_equals(
            unit["warranty_start_date"], "2026-09-17T14:00:00Z", "warranty_start_date"
        )
        ctx["part_inventory"] = seed_part_inventory(
            ctx["case_model"]["id"], **GASKET_PART
        )

        on_anniversary = validate_success(
            open_claim(
                ctx,
                claim_type="DOOR_GASKET",
                reported_date="2027-09-17",
                estimated_cost_cents=60000,
            ),
            expected_status=201,
        )
        assert_warranty_claim(on_anniversary)
        assert on_anniversary["warranty_term_months"] == 12
        assert on_anniversary["in_warranty"] is True
        assert on_anniversary["status"] == "OPEN"
        assert on_anniversary.get("parts_cost_cents") is None
        assert on_anniversary.get("total_cost_cents") is None

        day_after = validate_success(
            open_claim(
                ctx,
                claim_type="DOOR_GASKET",
                reported_date="2027-09-18",
                estimated_cost_cents=60000,
            ),
            expected_status=201,
        )
        assert day_after["warranty_term_months"] == 12
        assert day_after["in_warranty"] is False, (
            "one day past the twelfth-month anniversary falls outside coverage"
        )
        assert day_after.get("parts_cost_cents") is None
        assert day_after.get("total_cost_cents") is None


class TestClaimReferentialRules:
    """PRD §3.9 — the depot row must match the unit's model and the store's region."""

    def test_02_claim_naming_a_part_for_another_model_is_rejected(self, api):
        """A 6 ft grab-and-go compressor cannot be sent to fix an 8 ft multideck.

        PRD §3.9: "At rank 35 the depot stock row's `case_model_id` must equal the
        claimed unit's `case_model_id`, else `ERR_PART_MODEL_MISMATCH` (HTTP 422)"

        Design: Corner/validations/warranty_claim_with_part_for_other_model_rejected
        """
        ctx = setup_handed_off_shipment()
        other_model = validate_success(
            api.create_case_model(
                create_case_model_payload(ctx["refrigerant"]["id"], **SIX_FOOT_MODEL),
                TEST_USERS["design_engineer_headers"],
            ),
            expected_status=201,
        )
        ctx["part_inventory"] = seed_part_inventory(
            other_model["id"], part_number="CMP-6-OH", description="Compressor for MDL-MT-6"
        )

        response = open_claim(ctx, claim_type="COMPRESSOR_FAILURE")
        validate_error(response, ApiErrorId.ERR_PART_MODEL_MISMATCH.value)

        _rows, meta = validate_paginated(
            api.list_warranty_claims(TEST_USERS["service_manager_headers"])
        )
        assert meta["total_count"] == 0

    def test_03_claim_naming_a_part_in_another_region_is_rejected(self, api):
        """An Indiana depot row cannot serve an Ohio store.

        PRD §3.9: "At rank 36 the depot stock row's `region_code` must equal the
        `region_code` of the store plan behind the claimed unit, else
        `ERR_PART_REGION_MISMATCH` (HTTP 422), because a part must come out of the
        depot serving that store."

        Design: Corner/validations/warranty_claim_with_part_in_other_region_rejected
        """
        ctx = setup_handed_off_shipment()
        ctx["part_inventory"] = seed_part_inventory(
            ctx["case_model"]["id"], part_number="CMP-8-IN", region_code="IN"
        )
        assert ctx["store_plan"]["region_code"] == "OH"

        response = open_claim(ctx, claim_type="COMPRESSOR_FAILURE")
        validate_error(response, ApiErrorId.ERR_PART_REGION_MISMATCH.value)

        _rows, meta = validate_paginated(
            api.list_warranty_claims(TEST_USERS["service_manager_headers"])
        )
        assert meta["total_count"] == 0


class TestPartsReservation:
    """PRD §3.9 — reservation needs coverage first, then available stock."""

    def test_04_reserving_parts_on_a_never_handed_off_unit_is_rejected(self, api):
        """No handoff means no warranty start, so nothing may be reserved.

        PRD §3.9: "at rank 37 the claim's `in_warranty` must be true, else
        `ERR_CLAIM_OUT_OF_WARRANTY` (HTTP 422)"

        Design: Corner/validations/parts_reservation_on_never_handed_off_unit_rejected
        """
        ctx = setup_plan_with_completed_units()
        assert ctx["work_orders"][0]["status"] == "COMPLETE"
        assert ctx["work_orders"][0].get("warranty_start_date") is None
        ctx["install_crew"] = seed_install_crew()
        ctx["part_inventory"] = seed_part_inventory(ctx["case_model"]["id"])

        claim = validate_success(
            open_claim(
                ctx,
                claim_type="COMPRESSOR_FAILURE",
                reported_date="2026-09-20",
                requested_qty=1,
                estimated_cost_cents=200000,
            ),
            expected_status=201,
        )
        assert claim["warranty_term_months"] == 60
        assert claim["in_warranty"] is False

        response = api.reserve_claim_parts(
            claim["id"], TEST_USERS["service_manager_headers"]
        )
        validate_error(response, ApiErrorId.ERR_CLAIM_OUT_OF_WARRANTY.value)

        part = refresh_part_inventory(ctx)
        assert_depot_stock_invariants(part)
        assert part["on_hand_qty"] == 5
        assert part["reserved_qty"] == 0
        assert part["available_qty"] == 5

    def test_05_reserving_more_parts_than_the_depot_has_available_is_rejected(
        self, api
    ):
        """Two units requested against one on hand is refused at HTTP 409.

        PRD §3.9: "at rank 38 the depot row's `available_qty` must be at or above
        the claim's `requested_qty`, else `ERR_PARTS_UNAVAILABLE` (HTTP 409)."

        Design: Corner/validations/parts_reservation_beyond_available_stock_rejected
        """
        ctx = setup_open_claim(
            part_overrides={"on_hand_qty": 1, "unit_cost_cents": 45000, "min_stock_qty": 2},
            claim_overrides={
                "claim_type": "COMPRESSOR_FAILURE",
                "requested_qty": 2,
                "estimated_cost_cents": 200000,
            },
        )
        assert ctx["warranty_claim"]["in_warranty"] is True
        assert ctx["warranty_claim"]["warranty_term_months"] == 60

        response = api.reserve_claim_parts(
            ctx["warranty_claim"]["id"], TEST_USERS["service_manager_headers"]
        )
        validate_error(response, ApiErrorId.ERR_PARTS_UNAVAILABLE.value)

        claim = refresh_warranty_claim(ctx)
        assert claim["status"] == "OPEN"
        assert claim.get("parts_cost_cents") is None
        assert_version_is(claim, 1, "warranty claim")

        part = refresh_part_inventory(ctx)
        assert part["reserved_qty"] == 0
        assert part["available_qty"] == 1


class TestDenialCompensation:
    """PRD §3.9 — a denial after reservation restores the depot row exactly."""

    def test_06_denying_a_reserved_claim_fully_restores_the_depot_row(self, api):
        """Stock, reservation, cost and the incurred ledger all return to zero.

        PRD §3.9: "denying a claim that had already reserved parts decreases the
        depot row's `reserved_qty` by `requested_qty` while leaving `on_hand_qty`
        untouched, recomputes `available_qty` and `below_min`, and clears the
        claim's `parts_cost_cents` back to absent."

        Design: Difficulty/compensating_invariant/depot_part_stock_fully_restored_on_claim_denial
        """
        ctx = setup_reserved_claim(
            part_overrides=COMPRESSOR_PART,
            claim_clock="2026-10-05T09:00:00Z",
            claim_overrides={
                "claim_type": "COMPRESSOR_FAILURE",
                "reported_date": "2026-10-05",
                "requested_qty": 1,
                "estimated_cost_cents": 200000,
            },
        )
        reserved = ctx["warranty_claim"]
        assert reserved["status"] == "PARTS_RESERVED"
        assert reserved["parts_cost_cents"] == 148000
        assert reserved["in_warranty"] is True

        held = ctx["part_inventory"]
        assert held["reserved_qty"] == 1
        assert held["available_qty"] == 2
        assert_depot_stock_invariants(held)

        denied = validate_success(
            api.deny_warranty_claim(
                reserved["id"],
                {
                    "denial_reason": (
                        "Failure traced to store-side power quality, not the case"
                    )
                },
                TEST_USERS["service_manager_headers"],
            )
        )
        assert denied["status"] == "DENIED"
        assert denied.get("parts_cost_cents") is None
        assert denied["warranty_term_months"] == 60
        assert denied["in_warranty"] is True

        part = refresh_part_inventory(ctx)
        assert_depot_stock_invariants(part)
        assert part["on_hand_qty"] == 3
        assert part["reserved_qty"] == 0
        assert part["available_qty"] == 3
        assert part["below_min"] is False

        plan = refresh_store_plan(ctx)
        assert plan["warranty_reserve_incurred_cents"] == 0, (
            "a denied claim contributes exactly zero to the incurred half"
        )
        assert plan["warranty_reserve_accrual_cents"] == 28696

        assert refresh_install_crew(ctx)["committed_case_days"] == 0

    def test_07_denying_an_open_claim_touches_no_depot_row(self, api):
        """The unreserved path books the denial without moving any quantity.

        PRD §3.9: "Denying a claim still in `OPEN` touches no depot row, because
        nothing was ever reserved."

        Design: Difficulty/compensating_invariant/depot_part_stock_fully_restored_on_claim_denial
        """
        ctx = setup_open_claim(
            part_overrides=COMPRESSOR_PART,
            claim_clock="2026-10-05T09:00:00Z",
            claim_overrides={
                "claim_type": "COMPRESSOR_FAILURE",
                "reported_date": "2026-10-05",
                "requested_qty": 1,
                "estimated_cost_cents": 200000,
            },
        )
        assert ctx["warranty_claim"]["status"] == "OPEN"
        assert refresh_store_plan(ctx)["warranty_reserve_incurred_cents"] == 120000, (
            "an open claim is recognised at sixty hundredths of its estimate"
        )

        denied = validate_success(
            api.deny_warranty_claim(
                ctx["warranty_claim"]["id"],
                {"denial_reason": "Damage caused during store-side remodel work"},
                TEST_USERS["service_manager_headers"],
            )
        )
        assert denied["status"] == "DENIED"
        assert denied.get("parts_cost_cents") is None

        part = refresh_part_inventory(ctx)
        assert part["on_hand_qty"] == 3
        assert part["reserved_qty"] == 0
        assert part["available_qty"] == 3
        assert part["below_min"] is False

        assert refresh_store_plan(ctx)["warranty_reserve_incurred_cents"] == 0
