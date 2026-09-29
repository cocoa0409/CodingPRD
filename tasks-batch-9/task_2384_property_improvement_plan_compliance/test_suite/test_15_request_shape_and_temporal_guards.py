"""Internally inconsistent bodies, the cure-period bound, and the three temporal envelopes."""

from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    acknowledged_plan,
    assert_field_equals,
    assert_item_state,
    assert_plan_dimensions,
    capital_budget_payload,
    contractor_booking_payload,
    current_plan_version,
    default_notice_payload,
    extension_request_payload,
    issued_plan,
    item_payload,
    list_rows,
    read_franchisee,
    read_item,
    read_plan,
    register_contractor,
    renovation_phase_payload,
    schedule_phase,
    set_clock,
    validate_error,
)


@pytest.fixture
def acknowledged_plan_open_to_probes(api):
    """An acknowledged plan carrying one guest-facing item, so every shape probe is reachable."""
    scenario = acknowledged_plan(
        api,
        [
            {
                "key": "casegoods",
                "category": "GUEST_FACING",
                "standards_reference": "GF-17.1.1",
                "brand_estimated_cost_cents": 1000000,
            }
        ],
        legal_name="Kingsmere Hotels LLC",
        contact_email="ops@kingsmereh.example",
    )
    return scenario, current_plan_version(api, scenario.plan_id)


class TestRequestShapeGuardsRejectInconsistentBodies:
    def test_the_room_fields_must_agree_with_each_other(
        self, api, brand_manager, acknowledged_plan_open_to_probes
    ):
        """"The room fields must agree — `rooms_affected_count` must be 0 when `room_impacting` is
        false and at least 1 when `room_impacting` is true, and a mismatch is
        `ERR_ROOM_IMPACT_MISMATCH` (422)." The shape band runs before the state band, so this answers
        ahead of `ERR_PLAN_NOT_DRAFT`: "Required fields present and non-null, enum-typed inputs drawn
        from their declared sets, numeric bounds respected ... followed by the shape rules that carry
        their own codes: `ERR_INVALID_DATE_RANGE`, `ERR_ROOM_IMPACT_MISMATCH`".

        Design: Corner/validations/request_shape_guards_reject_internally_inconsistent_bodies
        """
        scenario, plan_version = acknowledged_plan_open_to_probes

        response = api.create_item(
            item_payload(
                scenario.plan_id,
                category="GUEST_FACING",
                standards_reference="GF-17.1.2",
                brand_estimated_cost_cents=200000,
                room_impacting=True,
                rooms_affected_count=0,
            ),
            brand_manager,
        )

        validate_error(response, ApiErrorId.ERR_ROOM_IMPACT_MISMATCH, 422)
        plan = read_plan(api, scenario.plan_id)
        assert_field_equals(plan, "scope_item_count", 1, "plan")
        assert_field_equals(plan, "version", plan_version, "plan")

    def test_a_contingency_past_the_ceiling_and_a_thin_justification_are_each_refused(
        self, api, acknowledged_plan_open_to_probes
    ):
        """"a `contingency_pct` between 0 and 0.50 inclusive carrying at most 4 decimal places ... A
        contingency outside that range, or one carrying more than four decimal places, is refused with
        `ERR_CONTINGENCY_OUT_OF_RANGE` (422)." "The justification must be at least 40 characters after
        trimming, or the request is refused with `ERR_JUSTIFICATION_INSUFFICIENT` (422)."

        Design: Corner/validations/request_shape_guards_reject_internally_inconsistent_bodies
        """
        scenario, plan_version = acknowledged_plan_open_to_probes

        validate_error(
            api.create_capital_budget(
                capital_budget_payload(
                    scenario.plan_id,
                    1182500,
                    plan_version,
                    contingency_pct=0.51,
                    financing_source="OWNER_EQUITY",
                ),
                scenario.owner_headers,
            ),
            ApiErrorId.ERR_CONTINGENCY_OUT_OF_RANGE,
            422,
        )
        validate_error(
            api.create_extension_request(
                extension_request_payload(
                    scenario.item_id("casegoods"),
                    30,
                    business_justification="too short xx",
                ),
                scenario.owner_headers,
            ),
            ApiErrorId.ERR_JUSTIFICATION_INSUFFICIENT,
            422,
        )

        _budgets, budget_meta = list_rows(api, "list_capital_budgets", plan_id=scenario.plan_id)
        assert budget_meta["total_count"] == 0, (
            f"the refused authorisation must leave no budget row, got {budget_meta}"
        )
        assert_item_state(read_item(api, scenario.item_id("casegoods")), status="SCOPED")

    def test_a_closure_window_that_ends_before_it_starts_is_refused(
        self, api, acknowledged_plan_open_to_probes
    ):
        """"The dates must parse and `end_date` must be no earlier than `start_date`, or the request
        fails with `ERR_INVALID_DATE_RANGE` (422)."

        Design: Corner/validations/request_shape_guards_reject_internally_inconsistent_bodies
        """
        scenario, plan_version = acknowledged_plan_open_to_probes

        response = api.create_renovation_phase(
            renovation_phase_payload(
                scenario.plan_id,
                phase_number=1,
                start_date="2026-09-10",
                end_date="2026-09-01",
                rooms_out_of_service=10,
            ),
            scenario.owner_headers,
        )

        validate_error(response, ApiErrorId.ERR_INVALID_DATE_RANGE, 422)
        _phases, phase_meta = list_rows(api, "list_renovation_phases", plan_id=scenario.plan_id)
        assert phase_meta["total_count"] == 0, (
            f"the refused window must leave no phase row, got {phase_meta}"
        )
        assert_field_equals(read_plan(api, scenario.plan_id), "version", plan_version, "plan")


@pytest.fixture
def issued_plan_with_nothing_overdue(api):
    """A plan issued at the default clock, so no item of it has yet slipped."""
    return issued_plan(
        api,
        [
            {
                "key": "corridor",
                "category": "GUEST_FACING",
                "standards_reference": "GF-18.1.1",
                "brand_estimated_cost_cents": 900000,
            }
        ],
        legal_name="Lowfield Hotels LLC",
        contact_email="ops@lowfieldh.example",
    )


class TestCurePeriodBoundOutranksTheBreachCheck:
    def test_an_out_of_range_cure_period_answers_before_the_breach_precondition(
        self, api, brand_manager, issued_plan_with_nothing_overdue
    ):
        """"That count must be between 1 and 60 days inclusive, or the request fails with
        `ERR_CURE_PERIOD_OUT_OF_RANGE` (422)." The shape band precedes the state band: "3. **Request
        shape.** ... 4. **State preconditions.**"

        Design: Corner/validations/cure_period_bound_outranks_the_breach_precondition
        """
        scenario = issued_plan_with_nothing_overdue

        response = api.create_default_notice(
            default_notice_payload(scenario.plan_id, 61), brand_manager
        )

        validate_error(response, ApiErrorId.ERR_CURE_PERIOD_OUT_OF_RANGE, 422)
        assert_plan_dimensions(read_plan(api, scenario.plan_id), status="ISSUED")

    def test_a_legal_cure_period_then_surfaces_the_missing_breach(
        self, api, brand_manager, issued_plan_with_nothing_overdue
    ):
        """"At least one item of the plan must be overdue at the instant of issuance, or the request
        fails with `ERR_NO_BREACH_TO_NOTICE` (409)."

        Design: Corner/validations/cure_period_bound_outranks_the_breach_precondition
        """
        scenario = issued_plan_with_nothing_overdue

        response = api.create_default_notice(
            default_notice_payload(scenario.plan_id, 30), brand_manager
        )

        validate_error(response, ApiErrorId.ERR_NO_BREACH_TO_NOTICE, 409)
        _notices, meta = list_rows(api, "list_default_notices", plan_id=scenario.plan_id)
        assert meta["total_count"] == 0, f"no notice row may survive either refusal, got {meta}"
        assert_field_equals(
            read_franchisee(api, scenario.franchisee_id), "standing", "GOOD", "franchisee"
        )


@pytest.fixture
def acknowledged_plan_with_a_phase_and_a_crew(api):
    """An acknowledged plan, one closure window in September, and one general contractor."""
    scenario = acknowledged_plan(
        api,
        [
            {
                "key": "case_goods",
                "category": "GUEST_FACING",
                "standards_reference": "GF-19.1.1",
                "brand_estimated_cost_cents": 900000,
            }
        ],
        legal_name="Marchmont Hotels LLC",
        contact_email="ops@marchmonth.example",
    )
    phase = schedule_phase(
        api,
        scenario,
        phase_number=1,
        start_date="2026-09-01",
        end_date="2026-09-10",
        rooms_out_of_service=10,
    )
    contractor = register_contractor(
        api,
        name="Northrop Building Group",
        trade="GENERAL",
        brand_approved=False,
        max_concurrent_bookings=2,
    )
    return scenario, phase, contractor


class TestTemporalEnvelopes:
    def test_a_booking_may_not_run_past_the_end_of_its_phase(
        self, api, acknowledged_plan_with_a_phase_and_a_crew
    ):
        """"The interval must sit inside its phase's closure window: `start_datetime` must be at or
        after the phase's `start_date` at `00:00:00Z`, and `end_datetime` must be at or before the day
        after the phase's `end_date` at `00:00:00Z`; otherwise the booking fails with
        `ERR_BOOKING_OUTSIDE_PHASE_WINDOW` (422)."

        Design: Corner/validations/temporal_gates_bound_bookings_phases_and_extensions
        """
        scenario, phase, contractor = acknowledged_plan_with_a_phase_and_a_crew

        response = api.create_contractor_booking(
            contractor_booking_payload(
                contractor["id"],
                phase["id"],
                start_datetime="2026-09-10T08:00:00Z",
                end_datetime="2026-09-11T17:00:00Z",
                crew_size=6,
            ),
            scenario.owner_headers,
        )

        validate_error(response, ApiErrorId.ERR_BOOKING_OUTSIDE_PHASE_WINDOW, 422)
        _rows, meta = list_rows(api, "list_contractor_bookings", phase_id=phase["id"])
        assert meta["total_count"] == 0, f"the refused engagement must leave no row, got {meta}"

    def test_a_phase_may_not_end_after_the_plan_horizon(
        self, api, acknowledged_plan_with_a_phase_and_a_crew
    ):
        """"For a plan that has already been issued, the new phase's `end_date` may not fall after the
        plan's `back_of_house_deadline_date`, or the request fails with
        `ERR_PHASE_OUTSIDE_PLAN_HORIZON` (422); for a plan still in `DRAFT`, which has no deadlines
        yet, this check is skipped entirely."

        Design: Corner/validations/temporal_gates_bound_bookings_phases_and_extensions
        """
        scenario, _phase, _contractor = acknowledged_plan_with_a_phase_and_a_crew

        response = api.create_renovation_phase(
            renovation_phase_payload(
                scenario.plan_id,
                phase_number=2,
                start_date="2027-10-20",
                end_date="2027-10-26",
                rooms_out_of_service=10,
            ),
            scenario.owner_headers,
        )

        validate_error(response, ApiErrorId.ERR_PHASE_OUTSIDE_PLAN_HORIZON, 422)
        assert_field_equals(
            read_plan(api, scenario.plan_id), "back_of_house_deadline_date", "2027-10-25", "plan"
        )
        _rows, meta = list_rows(api, "list_renovation_phases", plan_id=scenario.plan_id)
        assert meta["total_count"] == 1, (
            f"only the September window may remain on the plan, got {meta}"
        )

    def test_an_extension_may_not_be_asked_for_after_the_deadline(
        self, api, acknowledged_plan_with_a_phase_and_a_crew
    ):
        """"Timing matters: an extension may be requested only while the clock date is at or before
        the item's `deadline_date`; once the item is already overdue its deadline can no longer be
        moved, and the request is refused with `ERR_EXTENSION_AFTER_DEADLINE` (409)."

        Design: Corner/validations/temporal_gates_bound_bookings_phases_and_extensions
        """
        scenario, _phase, _contractor = acknowledged_plan_with_a_phase_and_a_crew
        set_clock(api, "2027-04-29T00:00:00Z")

        response = api.create_extension_request(
            extension_request_payload(
                scenario.item_id("case_goods"),
                30,
                business_justification=(
                    "The specified case goods vendor entered receivership and a replacement package "
                    "needs re-bidding."
                ),
            ),
            scenario.owner_headers,
        )

        validate_error(response, ApiErrorId.ERR_EXTENSION_AFTER_DEADLINE, 409)
        item = read_item(api, scenario.item_id("case_goods"))
        assert_item_state(item, status="SCOPED", deadline_date="2027-04-28")
        assert_field_equals(item, "extension_days_granted", 0, "item")
        _rows, meta = list_rows(
            api, "list_extension_requests", item_id=scenario.item_id("case_goods")
        )
        assert meta["total_count"] == 0, f"the refused request must leave no row, got {meta}"
