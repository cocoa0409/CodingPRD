"""The retention floor at its exact edge, and the displacement recapture at its lowest tier."""

from __future__ import annotations

from decimal import Decimal

import pytest

from test_helpers import (
    ApiErrorId,
    acknowledged_plan,
    assert_field_equals,
    assert_ledger_contains,
    assert_plan_dimensions,
    consent_draw,
    current_property_version,
    disburse_draw,
    ledger_entries,
    locked_budget,
    read_budget,
    read_draw,
    read_plan,
    read_property,
    request_draw,
    reserve_draw_payload,
    schedule_phase,
    start_item,
    validate_error,
    validate_success,
)


@pytest.fixture
def locked_plan_with_a_full_reserve(api):
    """A locked budget over a 500,000-dollar item, against a reserve holding exactly 45,000,000 free."""
    scenario = acknowledged_plan(
        api,
        [
            {
                "key": "tower_rooms",
                "category": "GUEST_FACING",
                "standards_reference": "GF-13.1.1",
                "brand_estimated_cost_cents": 50000000,
            }
        ],
        legal_name="Fallowmere Hotels LLC",
        contact_email="finance@fallowmerehotels.example",
    )
    budget = locked_budget(api, scenario, 59125000, financing_source="RESERVE_DRAW")
    start_item(api, scenario, scenario.item_id("tower_rooms"))
    return scenario, budget


class TestReserveFloorIsInclusive:
    def test_one_cent_past_the_availability_is_refused(self, api, locked_plan_with_a_full_reserve):
        """"The amount available for a new draw is the property's `reserve_balance_cents` less its
        `minimum_retention_cents` less that encumbered total, floored at 0. The new `amount_cents`
        must be no greater than that available figure; a draw that consumes the availability exactly
        is admitted, and one that exceeds it is refused with `ERR_INSUFFICIENT_RESERVE` (409)."

        Design: Corner/calculations/reserve_floor_permits_exact_consumption_but_not_one_cent_more
        """
        scenario, budget = locked_plan_with_a_full_reserve
        version = current_property_version(api, scenario.property_id, scenario.owner_headers)

        response = api.create_reserve_draw(
            reserve_draw_payload(
                scenario.property_id,
                budget["id"],
                scenario.item_id("tower_rooms"),
                45000001,
                version,
            ),
            scenario.owner_headers,
        )

        validate_error(response, ApiErrorId.ERR_INSUFFICIENT_RESERVE, 409)
        prop = read_property(api, scenario.property_id)
        assert_field_equals(prop, "reserve_balance_cents", 50000000, "property")
        assert_field_equals(prop, "version", version, "property")

    def test_a_draw_that_consumes_the_availability_exactly_is_admitted(
        self, api, locked_plan_with_a_full_reserve
    ):
        """"A requested or consented draw *encumbers* its amount: it is earmarked but not yet paid."
        "Creating a reserve draw — `POST /pip/reserve-draws` — requires a non-optional
        `expected_property_version` field carrying the client's last observed `version` of the target
        `Property`."

        Design: Corner/calculations/reserve_floor_permits_exact_consumption_but_not_one_cent_more
        """
        scenario, budget = locked_plan_with_a_full_reserve
        version = current_property_version(api, scenario.property_id, scenario.owner_headers)

        draw = validate_success(
            api.create_reserve_draw(
                reserve_draw_payload(
                    scenario.property_id,
                    budget["id"],
                    scenario.item_id("tower_rooms"),
                    45000000,
                    version,
                ),
                scenario.owner_headers,
            ),
            201,
        )

        assert_field_equals(draw, "status", "REQUESTED", "draw")
        assert_field_equals(draw, "amount_cents", 45000000, "draw")
        assert_field_equals(
            read_property(api, scenario.property_id), "version", version + 1, "property"
        )

    def test_consent_earmarks_the_cash_without_moving_it(self, api, locked_plan_with_a_full_reserve):
        """"A decision of `CONSENT` moves it `REQUESTED → BRAND_CONSENTED` and stamps
        `consented_by_user_id` with the acting `X-User-ID`; the amount stays encumbered against the
        reserve."

        Design: Corner/calculations/reserve_floor_permits_exact_consumption_but_not_one_cent_more
        """
        scenario, budget = locked_plan_with_a_full_reserve
        draw = request_draw(
            api, scenario, budget["id"], scenario.item_id("tower_rooms"), 45000000
        )

        consented = consent_draw(api, draw["id"])

        assert_field_equals(consented, "status", "BRAND_CONSENTED", "draw")
        assert_field_equals(consented, "consented_by_user_id", "bm-001", "draw")
        assert_field_equals(
            read_property(api, scenario.property_id), "reserve_balance_cents", 50000000, "property"
        )
        assert_field_equals(read_budget(api, budget["id"]), "committed_cents", 0, "budget")

    def test_disbursement_leaves_the_balance_sitting_on_the_floor(
        self, api, locked_plan_with_a_full_reserve
    ):
        """"On success the draw's `amount_cents` is subtracted from `reserve_balance_cents` and the
        property's `version` increments; `disbursed_at` is stamped with the logical clock; the funding
        budget's `committed_cents` increases by the same amount; and a ledger entry of type
        `DRAW_DISBURSED` is appended, carrying the draw's `purpose_item_id` as its item reference and
        the draw amount as a positive `delta_cents`."

        Design: Corner/calculations/reserve_floor_permits_exact_consumption_but_not_one_cent_more
        """
        scenario, budget = locked_plan_with_a_full_reserve
        draw = request_draw(
            api, scenario, budget["id"], scenario.item_id("tower_rooms"), 45000000
        )
        consent_draw(api, draw["id"])

        disburse_draw(api, scenario, draw["id"])

        prop = read_property(api, scenario.property_id)
        assert_field_equals(read_draw(api, draw["id"]), "status", "DISBURSED", "draw")
        assert_field_equals(prop, "reserve_balance_cents", 5000000, "property")
        assert_field_equals(prop, "minimum_retention_cents", 5000000, "property")
        settled_budget = read_budget(api, budget["id"])
        assert_field_equals(settled_budget, "committed_cents", 45000000, "budget")
        assert_field_equals(settled_budget, "status", "LOCKED", "budget")
        assert_ledger_contains(
            ledger_entries(api, plan_id=scenario.plan_id),
            "DRAW_DISBURSED",
            delta_cents=45000000,
            item_id=scenario.item_id("tower_rooms"),
            count=1,
        )


@pytest.fixture
def phase_closing_a_twentieth_of_the_house(api):
    """A ten-night closure of 10 keys out of 200 — a ratio of 0.05, the lowest recapture band."""
    scenario = acknowledged_plan(
        api,
        [
            {
                "key": "north_wing",
                "category": "GUEST_FACING",
                "standards_reference": "GF-15.1.1",
                "brand_estimated_cost_cents": 700000,
            }
        ],
        legal_name="Hazelbrook Hotels LLC",
        contact_email="pm@hazelbrookhotels.example",
    )
    phase = schedule_phase(
        api,
        scenario,
        phase_number=1,
        start_date="2026-09-01",
        end_date="2026-09-10",
        rooms_out_of_service=10,
    )
    return scenario, phase


class TestDisplacementLowestRecaptureTier:
    def test_a_ratio_below_a_tenth_recaptures_thirty_percent(
        self, api, phase_closing_a_twentieth_of_the_house
    ):
        """"the recapture is 30 percent, that is 0.30, when the ratio is below 0.10". "The gross
        displacement is the displaced room nights multiplied by the property's `adr_baseline_cents`
        and by its `occupancy_baseline_pct`, rounded half up to whole cents — that is the first
        rounding. The phase's `displacement_revenue_impact_cents` is that rounded gross figure
        multiplied by one minus the recapture fraction, rounded half up to whole cents again — the
        second rounding."

        Design: Corner/calculations/displacement_impact_uses_the_lowest_recapture_tier
        """
        _scenario, phase = phase_closing_a_twentieth_of_the_house

        assert_field_equals(phase, "displacement_revenue_impact_cents", 882000, "phase")
        assert_field_equals(phase, "status", "PLANNED", "phase")
        assert phase["ooo_pct_at_activation"] is None, (
            f"only activation writes the activation ratio, got {phase!r}"
        )

    def test_the_projection_reads_the_baselines_as_they_stand_at_creation(
        self, api, phase_closing_a_twentieth_of_the_house
    ):
        """"Every phase carries a projection of the revenue its closure displaces, computed at
        creation against the property's baselines as they then stand and recomputed at activation
        against the baselines as they stand at that moment." "The number of closed nights is the count
        of days from `start_date` to `end_date` inclusive — the difference between the two dates plus
        one."

        Design: Corner/calculations/displacement_impact_uses_the_lowest_recapture_tier
        """
        scenario, phase = phase_closing_a_twentieth_of_the_house

        prop = read_property(api, scenario.property_id)

        assert_field_equals(prop, "room_count", 200, "property")
        assert_field_equals(prop, "adr_baseline_cents", 18000, "property")
        assert Decimal(str(prop["occupancy_baseline_pct"])) == Decimal("0.70"), (
            f"the baseline occupancy feeding the gross figure is 0.70, got {prop!r}"
        )
        assert_field_equals(prop, "rooms_out_of_service_current", 0, "property")
        assert_field_equals(phase, "rooms_out_of_service", 10, "phase")
        assert_plan_dimensions(read_plan(api, scenario.plan_id), status="OWNER_ACKNOWLEDGED")
