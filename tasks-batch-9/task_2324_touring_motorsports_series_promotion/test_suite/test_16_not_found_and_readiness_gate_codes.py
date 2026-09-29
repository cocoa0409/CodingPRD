"""Error codes for missing rows, the on-sale gate and the settlement gate.

Four families live in this module: the 404 that belongs to each entity, the four
codes the on-sale gate reports in rule order, the shortfall codes that a safety
plan meets at submission time, and the preconditions that guard the preparation
of a settlement.

Every scenario is built inside its own test, because each test runs against a
freshly launched server with an empty database, and all time-dependent behaviour
is driven from the logical clock rather than the host's wall clock.
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from test_helpers import (
    ApiClient,
    ApiErrorId,
    NON_EXISTENT_UUID,
    factories,
    fixtures as helpers,
    get_success_data,
    test_users as users,
    validate_error,
    validate_success,
)

# Header builders keyed by the role each read is addressed as. Parametrized cases
# cannot take fixtures, so the builder is resolved inside the test body.
_HEADER_BUILDERS = {
    "SeriesPromoter": users.make_series_promoter_headers,
    "TicketingManager": users.make_ticketing_manager_headers,
    "SafetyOfficial": users.make_safety_official_headers,
    "FinanceController": users.make_finance_controller_headers,
}

# One single-row read per entity, each addressed as a role the endpoint permits so
# that no authorization rule can answer ahead of the resolution rule.
_ENTITY_READS = [
    ("get_season", "SeriesPromoter", ApiErrorId.ERR_SEASON_NOT_FOUND),
    ("get_venue", "SeriesPromoter", ApiErrorId.ERR_VENUE_NOT_FOUND),
    ("get_venue_booking", "SeriesPromoter", ApiErrorId.ERR_VENUE_BOOKING_NOT_FOUND),
    ("get_tour_stop", "SeriesPromoter", ApiErrorId.ERR_TOUR_STOP_NOT_FOUND),
    ("get_competitor", "SeriesPromoter", ApiErrorId.ERR_COMPETITOR_NOT_FOUND),
    ("get_vehicle_entry", "SeriesPromoter", ApiErrorId.ERR_VEHICLE_ENTRY_NOT_FOUND),
    ("get_tech_inspection", "SafetyOfficial", ApiErrorId.ERR_TECH_INSPECTION_NOT_FOUND),
    ("get_show_segment", "SeriesPromoter", ApiErrorId.ERR_SHOW_SEGMENT_NOT_FOUND),
    ("get_ticket_tier", "TicketingManager", ApiErrorId.ERR_TICKET_TIER_NOT_FOUND),
    ("get_ticket_order", "TicketingManager", ApiErrorId.ERR_TICKET_ORDER_NOT_FOUND),
    ("get_sponsor", "SeriesPromoter", ApiErrorId.ERR_SPONSOR_NOT_FOUND),
    (
        "get_sponsorship_activation",
        "SeriesPromoter",
        ApiErrorId.ERR_SPONSORSHIP_ACTIVATION_NOT_FOUND,
    ),
    ("get_safety_plan", "SafetyOfficial", ApiErrorId.ERR_SAFETY_PLAN_NOT_FOUND),
    (
        "get_marketing_allocation",
        "SeriesPromoter",
        ApiErrorId.ERR_MARKETING_ALLOCATION_NOT_FOUND,
    ),
    ("get_settlement", "FinanceController", ApiErrorId.ERR_SETTLEMENT_NOT_FOUND),
]

# Reads addressed under a parent, where the identifier in the path is the parent's,
# so the code reported is the parent's rather than the child's.
_NESTED_READS = [
    (
        "list_tech_inspections",
        "SafetyOfficial",
        ApiErrorId.ERR_VEHICLE_ENTRY_NOT_FOUND,
    ),
    ("get_tour_stop_settlement", "FinanceController", ApiErrorId.ERR_TOUR_STOP_NOT_FOUND),
    ("get_season_market_report", "FinanceController", ApiErrorId.ERR_SEASON_NOT_FOUND),
]

# Provisioning that exactly meets the floors of a stop with no tiers and no live
# entries: one ALS medic, two BLS medics, one ambulance, 1200 feet of barrier, a
# six-foot fence and one access lane.
_BARE_STOP_PROVISIONING = {
    "barrier_linear_feet": 1200,
    "catch_fence_height_ft": 6,
    "medical_als_staff_count": 1,
    "medical_bls_staff_count": 2,
    "ambulance_count": 1,
    "emergency_access_lanes": 1,
}

# The price card the readiness ladder is walked with: one tier of 500 seats whose
# selling window closes five hours before the show starts.
_GA_TIER = {
    "tier_code": "GA",
    "price_cents": 3200,
    "allotment": 500,
    "on_sale_start_utc": "2026-08-01T00:00:00Z",
    "on_sale_end_utc": "2026-11-14T18:00:00Z",
}

# Provisioning that is short on medics, short on ambulances and short on barrier
# all at once, so the submission ladder has three failures to choose between.
_SHORT_PROVISIONING = {
    "barrier_linear_feet": 800,
    "catch_fence_height_ft": 6,
    "medical_als_staff_count": 0,
    "medical_bls_staff_count": 2,
    "ambulance_count": 0,
    "emergency_access_lanes": 1,
}


def _bare_stop(api: ApiClient) -> Dict[str, Any]:
    """A confirmed Atlanta stop with its show timing set and nothing else on it."""
    return helpers.stop_with_show_timing(api)


def _certify_bare_plan(api: ApiClient, stop_id: str) -> Dict[str, Any]:
    """Certify a plan that exactly meets the floors of a stop with no tiers."""
    return helpers.certified_safety_plan(api, stop_id, **_BARE_STOP_PROVISIONING)


def _revise_plan(
    api: ApiClient, plan_id: str, **provisioning: Any
) -> Dict[str, Any]:
    """Revise the draft plan's provisioning as its author."""
    return get_success_data(
        api.update_safety_plan(
            plan_id,
            factories.make_safety_plan_update_payload(**provisioning),
            headers=users.make_safety_author_headers(),
        )
    )


class TestNotFoundCodeIsPinnedToItsOwnEntity:
    """Each entity answers a read of a missing row with its own 404 code."""

    @pytest.mark.parametrize(
        "method_name, role, expected_error",
        _ENTITY_READS,
        ids=[case[2].value for case in _ENTITY_READS],
    )
    def test_read_of_a_missing_row_reports_that_entity_s_own_code(
        self,
        api: ApiClient,
        method_name: str,
        role: str,
        expected_error: ApiErrorId,
    ) -> None:
        """PRD §2.6: "The first identifier that does not resolve determines the error, and the response is the 404 belonging to that entity — `ERR_SEASON_NOT_FOUND`, `ERR_VENUE_NOT_FOUND`, `ERR_VENUE_BOOKING_NOT_FOUND`, `ERR_TOUR_STOP_NOT_FOUND`, `ERR_COMPETITOR_NOT_FOUND`, `ERR_VEHICLE_ENTRY_NOT_FOUND`, `ERR_TECH_INSPECTION_NOT_FOUND`, `ERR_SHOW_SEGMENT_NOT_FOUND`, `ERR_TICKET_TIER_NOT_FOUND`, `ERR_TICKET_ORDER_NOT_FOUND`, `ERR_SPONSOR_NOT_FOUND`, `ERR_SPONSORSHIP_ACTIVATION_NOT_FOUND`, `ERR_SAFETY_PLAN_NOT_FOUND`, `ERR_MARKETING_ALLOCATION_NOT_FOUND` or `ERR_SETTLEMENT_NOT_FOUND`."

        Design: Corner/errors/corner_error_every_not_found_code_is_pinned_to_its_own_entity
        """
        response = getattr(api, method_name)(
            NON_EXISTENT_UUID, headers=_HEADER_BUILDERS[role]()
        )

        # The validator also cross-checks the documented HTTP status, which is 404
        # for every member of this family, and that the body carries both the
        # error_id and a non-empty message.
        validate_error(response, expected_error)

    @pytest.mark.parametrize(
        "method_name, role, expected_error",
        _NESTED_READS,
        ids=["tech_inspections_of_entry", "settlement_of_stop", "market_report_of_season"],
    )
    def test_read_under_a_missing_parent_reports_the_parent_s_code(
        self,
        api: ApiClient,
        method_name: str,
        role: str,
        expected_error: ApiErrorId,
    ) -> None:
        """PRD §2.6: "Many creations and reads are addressed under a parent: a stop's ticket tiers, a stop's safety plan, an entry's inspections. When a path contains an identifier, the server resolves it before doing anything else, and when a path contains more than one identifier they are resolved strictly left to right."

        Design: Corner/errors/corner_error_every_not_found_code_is_pinned_to_its_own_entity
        """
        response = getattr(api, method_name)(
            NON_EXISTENT_UUID, headers=_HEADER_BUILDERS[role]()
        )

        # The child collection is never reached, so the code names the parent.
        validate_error(response, expected_error)


class TestOnSaleGateReportsItsCodesInRuleOrder:
    """The four on-sale conditions are repaired one at a time, in declared order."""

    def test_bare_stop_reports_safety_not_certified_first(
        self, api: ApiClient, ticketing_headers: Dict[str, str]
    ) -> None:
        """PRD §3.7: "Each failure has its own error, and they are reported in the precedence order of §2.10: `ERR_SAFETY_NOT_CERTIFIED`, then `ERR_RUN_ORDER_INCOMPLETE`, then `ERR_NO_TICKET_TIERS`, and finally `ERR_STOP_NOT_READY` for a stop that passes all three specific checks but still fails the derived posture — which happens, for instance, when a live entry is `TECH_HELD` or when no marketing money has been committed to the market yet."

        Design: Corner/errors/corner_error_on_sale_gate_reveals_its_readiness_codes_in_rule_order
        """
        state = _bare_stop(api)
        stop = helpers.fetch_stop(api, state["stop_id"])
        assert stop["safety_state"] == "SAFETY_DRAFT"
        assert stop["competition_segment_count"] == 0

        rejected = api.open_tour_stop_sales(state["stop_id"], headers=ticketing_headers)

        # The run order is empty and there is no price card either, but the
        # lowest-order rule of the four is the one that answers.
        validate_error(rejected, ApiErrorId.ERR_SAFETY_NOT_CERTIFIED)
        assert helpers.fetch_stop(api, state["stop_id"])["sales_state"] == "SALES_PENDING"

    def test_certified_stop_with_an_empty_run_order_reports_run_order_incomplete(
        self, api: ApiClient, ticketing_headers: Dict[str, str]
    ) -> None:
        """PRD §3.7: "Each failure has its own error, and they are reported in the precedence order of §2.10: `ERR_SAFETY_NOT_CERTIFIED`, then `ERR_RUN_ORDER_INCOMPLETE`, then `ERR_NO_TICKET_TIERS`, and finally `ERR_STOP_NOT_READY` for a stop that passes all three specific checks but still fails the derived posture — which happens, for instance, when a live entry is `TECH_HELD` or when no marketing money has been committed to the market yet."

        Design: Corner/errors/corner_error_on_sale_gate_reveals_its_readiness_codes_in_rule_order
        """
        state = _bare_stop(api)
        _certify_bare_plan(api, state["stop_id"])
        assert (
            helpers.fetch_stop(api, state["stop_id"])["safety_state"]
            == "SAFETY_CERTIFIED"
        )

        rejected = api.open_tour_stop_sales(state["stop_id"], headers=ticketing_headers)

        validate_error(rejected, ApiErrorId.ERR_RUN_ORDER_INCOMPLETE)

    def test_intermission_only_run_order_still_reports_run_order_incomplete(
        self, api: ApiClient, ticketing_headers: Dict[str, str]
    ) -> None:
        """PRD §3.4: "Each insert also refreshes the stop's `competition_segment_count`, which is the number of the stop's segments whose `segment_type` is `COMPETITION`, and recomputes the posture — which matters because a stop with zero competition segments is held at `RESTRICTED` and cannot open sales."

        Design: Corner/errors/corner_error_on_sale_gate_reveals_its_readiness_codes_in_rule_order
        """
        state = _bare_stop(api)
        _certify_bare_plan(api, state["stop_id"])
        helpers.create_show_segment(
            api,
            state["stop_id"],
            segment_type="INTERMISSION",
            segment_title="Freestyle Exhibition",
            run_order_position=1,
            duration_minutes=20,
        )
        assert helpers.fetch_stop(api, state["stop_id"])["competition_segment_count"] == 0

        rejected = api.open_tour_stop_sales(state["stop_id"], headers=ticketing_headers)

        # The stop now has a segment, but not a competition one.
        validate_error(rejected, ApiErrorId.ERR_RUN_ORDER_INCOMPLETE)

    def test_stop_without_a_price_card_reports_no_ticket_tiers(
        self, api: ApiClient, ticketing_headers: Dict[str, str]
    ) -> None:
        """PRD §3.7: "Each failure has its own error, and they are reported in the precedence order of §2.10: `ERR_SAFETY_NOT_CERTIFIED`, then `ERR_RUN_ORDER_INCOMPLETE`, then `ERR_NO_TICKET_TIERS`, and finally `ERR_STOP_NOT_READY` for a stop that passes all three specific checks but still fails the derived posture — which happens, for instance, when a live entry is `TECH_HELD` or when no marketing money has been committed to the market yet."

        Design: Corner/errors/corner_error_on_sale_gate_reveals_its_readiness_codes_in_rule_order
        """
        state = _bare_stop(api)
        _certify_bare_plan(api, state["stop_id"])
        helpers.create_show_segment(
            api,
            state["stop_id"],
            segment_type="INTERMISSION",
            segment_title="Freestyle Exhibition",
            run_order_position=1,
            duration_minutes=20,
        )
        helpers.create_show_segment(
            api,
            state["stop_id"],
            segment_type="COMPETITION",
            segment_title="Feature",
            run_order_position=2,
            duration_minutes=40,
        )
        assert helpers.fetch_stop(api, state["stop_id"])["competition_segment_count"] == 1

        rejected = api.open_tour_stop_sales(state["stop_id"], headers=ticketing_headers)

        validate_error(rejected, ApiErrorId.ERR_NO_TICKET_TIERS)

    def test_stop_without_committed_marketing_money_reports_stop_not_ready(
        self, api: ApiClient, ticketing_headers: Dict[str, str]
    ) -> None:
        """PRD §3.7: "Each failure has its own error, and they are reported in the precedence order of §2.10: `ERR_SAFETY_NOT_CERTIFIED`, then `ERR_RUN_ORDER_INCOMPLETE`, then `ERR_NO_TICKET_TIERS`, and finally `ERR_STOP_NOT_READY` for a stop that passes all three specific checks but still fails the derived posture — which happens, for instance, when a live entry is `TECH_HELD` or when no marketing money has been committed to the market yet."

        Design: Corner/errors/corner_error_on_sale_gate_reveals_its_readiness_codes_in_rule_order
        """
        state = _bare_stop(api)
        _certify_bare_plan(api, state["stop_id"])
        helpers.create_show_segment(
            api,
            state["stop_id"],
            segment_type="COMPETITION",
            segment_title="Feature",
            run_order_position=1,
            duration_minutes=40,
        )
        helpers.create_ticket_tier(api, state["stop_id"], **_GA_TIER)

        stop = helpers.fetch_stop(api, state["stop_id"])
        assert stop["safety_state"] == "SAFETY_CERTIFIED"
        assert stop["competition_segment_count"] == 1
        assert stop["marketing_spend_committed_cents"] == 0
        assert stop["readiness_posture"] == "RESTRICTED"

        rejected = api.open_tour_stop_sales(state["stop_id"], headers=ticketing_headers)

        # Every specific check passes now, so only the derived posture is left.
        validate_error(rejected, ApiErrorId.ERR_STOP_NOT_READY)

    def test_gate_opens_once_marketing_money_is_committed(
        self, api: ApiClient, ticketing_headers: Dict[str, str]
    ) -> None:
        """PRD §3.7: "A `TicketingManager` takes it on sale, moving `sales_state` from `SALES_PENDING` to `ON_SALE`, and four conditions must hold: the stop's `safety_state` must be `SAFETY_CERTIFIED`, its `competition_segment_count` must be at least 1, it must have at least one ticket tier, and its `readiness_posture` must be `OPEN`."

        Design: Corner/errors/corner_error_on_sale_gate_reveals_its_readiness_codes_in_rule_order
        """
        state = _bare_stop(api)
        _certify_bare_plan(api, state["stop_id"])
        helpers.create_show_segment(
            api,
            state["stop_id"],
            segment_type="COMPETITION",
            segment_title="Feature",
            run_order_position=1,
            duration_minutes=40,
        )
        helpers.create_ticket_tier(api, state["stop_id"], **_GA_TIER)
        # The commit reads the season's current version as its concurrency token.
        helpers.commit_marketing_allocation(
            api,
            state["stop_id"],
            state["season_id"],
            channel="GRASSROOTS",
            amount_cents=25000,
        )

        opened = api.open_tour_stop_sales(state["stop_id"], headers=ticketing_headers)

        stop = validate_success(opened)
        assert stop["readiness_posture"] == "OPEN"
        assert stop["sales_state"] == "ON_SALE"

    def test_adding_the_price_card_does_not_decertify_the_plan(
        self, api: ApiClient
    ) -> None:
        """PRD §3.5: "The floors and the cost are recomputed at five distinct moments: when the plan is created, when a draft is revised, when the plan is submitted, when it is certified, and whenever a ticket tier is added to the stop — because a new tier can raise `expected_attendance`."

        Design: Corner/errors/corner_error_on_sale_gate_reveals_its_readiness_codes_in_rule_order
        """
        state = _bare_stop(api)
        plan_state = _certify_bare_plan(api, state["stop_id"])
        helpers.create_ticket_tier(api, state["stop_id"], **_GA_TIER)

        plan = helpers.fetch_safety_plan(api, plan_state["plan_id"])
        stop = helpers.fetch_stop(api, state["stop_id"])

        # 500 seats raise expected_attendance from 0 to 500, but MAX(2, CEIL(500 /
        # 2500)) is still two BLS medics, so the certified plan is left standing.
        assert stop["expected_attendance"] == 500
        assert plan["required_bls_staff_count"] == 2
        assert plan["medical_bls_staff_count"] == 2
        assert plan["state"] == "CERTIFIED"
        assert stop["safety_state"] == "SAFETY_CERTIFIED"


class TestSafetyShortfallCodesSurfaceAtSubmit:
    """A plan short on three fronts is repaired one front at a time."""

    def test_creation_writes_the_requirement_floors(self, api: ApiClient) -> None:
        """PRD §3.5: "The six floors are computed as follows, and every threshold is inclusive:" — "`required_als_staff_count` is 1, plus one more when `expected_attendance` is 6000 or greater, plus one more when the live entry count is 12 or greater." "`required_bls_staff_count` is the larger of 2 and the attendance divided by 2500 rounded **up** to a whole number, plus one further medic when the booked venue's `floor_type` is `CONCRETE`." "`required_ambulance_count` is the larger of 1 and the live entry count divided by 10 rounded **up** to a whole number." "`required_catch_fence_height_ft` is 8 feet when a heavy rig is present among the live entries and 6 feet otherwise." "`required_emergency_access_lanes` is 1, plus one more when `expected_attendance` is 6000 or greater." "`required_barrier_linear_feet` is the larger of 1200 feet and 900 feet plus 75 feet for each live entry."

        Design: Corner/errors/corner_error_safety_shortfall_codes_surface_at_submit_in_rule_order
        """
        booking = helpers.confirmed_booking(api)
        plan_state = helpers.draft_safety_plan(
            api, booking["stop_id"], **_SHORT_PROVISIONING
        )

        plan = plan_state["plan"]
        # No tiers and no live entries, so attendance is 0 and every floor sits at
        # its own minimum on a DIRT floor with no heavy rig.
        assert plan["required_als_staff_count"] == 1
        assert plan["required_bls_staff_count"] == 2
        assert plan["required_ambulance_count"] == 1
        assert plan["required_barrier_linear_feet"] == 1200
        assert plan["required_catch_fence_height_ft"] == 6
        assert plan["required_emergency_access_lanes"] == 1
        assert plan["state"] == "DRAFT"

    def test_medical_staffing_shortfall_answers_first(self, api: ApiClient) -> None:
        """PRD §3.5: "Submission first recomputes all six floors and `safety_cost_cents`, then requires four things to hold against the fresh figures: `medical_als_staff_count` must be at least `required_als_staff_count` and `medical_bls_staff_count` at least `required_bls_staff_count`, or the request is rejected with `ERR_MEDICAL_STAFFING_SHORTFALL`; `ambulance_count` must be at least `required_ambulance_count`, or `ERR_AMBULANCE_SHORTFALL`; `catch_fence_height_ft` must be at least `required_catch_fence_height_ft` and at the same time no greater than the booked venue's `catch_fence_max_height_ft`, or `ERR_CATCH_FENCE_INSUFFICIENT`; `emergency_access_lanes` must be at least `required_emergency_access_lanes`, or `ERR_EMERGENCY_ACCESS_INSUFFICIENT`; and `barrier_linear_feet` must be at least `required_barrier_linear_feet`, or `ERR_BARRIER_INSUFFICIENT`."

        Design: Corner/errors/corner_error_safety_shortfall_codes_surface_at_submit_in_rule_order
        """
        booking = helpers.confirmed_booking(api)
        plan_state = helpers.draft_safety_plan(
            api, booking["stop_id"], **_SHORT_PROVISIONING
        )

        rejected = api.submit_safety_plan(
            plan_state["plan_id"], headers=users.make_safety_author_headers()
        )

        # The ambulance and barrier shortfalls are equally true, yet the medics are
        # checked first.
        validate_error(rejected, ApiErrorId.ERR_MEDICAL_STAFFING_SHORTFALL)
        assert helpers.fetch_safety_plan(api, plan_state["plan_id"])["state"] == "DRAFT"
        assert helpers.fetch_stop(api, booking["stop_id"])["safety_state"] == "SAFETY_DRAFT"

    def test_ambulance_shortfall_answers_once_the_medics_are_there(
        self, api: ApiClient
    ) -> None:
        """PRD §3.5: "Submission first recomputes all six floors and `safety_cost_cents`, then requires four things to hold against the fresh figures: `medical_als_staff_count` must be at least `required_als_staff_count` and `medical_bls_staff_count` at least `required_bls_staff_count`, or the request is rejected with `ERR_MEDICAL_STAFFING_SHORTFALL`; `ambulance_count` must be at least `required_ambulance_count`, or `ERR_AMBULANCE_SHORTFALL`; `catch_fence_height_ft` must be at least `required_catch_fence_height_ft` and at the same time no greater than the booked venue's `catch_fence_max_height_ft`, or `ERR_CATCH_FENCE_INSUFFICIENT`; `emergency_access_lanes` must be at least `required_emergency_access_lanes`, or `ERR_EMERGENCY_ACCESS_INSUFFICIENT`; and `barrier_linear_feet` must be at least `required_barrier_linear_feet`, or `ERR_BARRIER_INSUFFICIENT`."

        Design: Corner/errors/corner_error_safety_shortfall_codes_surface_at_submit_in_rule_order
        """
        booking = helpers.confirmed_booking(api)
        plan_state = helpers.draft_safety_plan(
            api, booking["stop_id"], **_SHORT_PROVISIONING
        )
        _revise_plan(api, plan_state["plan_id"], medical_als_staff_count=1)

        rejected = api.submit_safety_plan(
            plan_state["plan_id"], headers=users.make_safety_author_headers()
        )

        validate_error(rejected, ApiErrorId.ERR_AMBULANCE_SHORTFALL)
        assert helpers.fetch_safety_plan(api, plan_state["plan_id"])["state"] == "DRAFT"
        assert helpers.fetch_stop(api, booking["stop_id"])["safety_state"] == "SAFETY_DRAFT"

    def test_barrier_insufficient_answers_last(self, api: ApiClient) -> None:
        """PRD §3.5: "Submission first recomputes all six floors and `safety_cost_cents`, then requires four things to hold against the fresh figures: `medical_als_staff_count` must be at least `required_als_staff_count` and `medical_bls_staff_count` at least `required_bls_staff_count`, or the request is rejected with `ERR_MEDICAL_STAFFING_SHORTFALL`; `ambulance_count` must be at least `required_ambulance_count`, or `ERR_AMBULANCE_SHORTFALL`; `catch_fence_height_ft` must be at least `required_catch_fence_height_ft` and at the same time no greater than the booked venue's `catch_fence_max_height_ft`, or `ERR_CATCH_FENCE_INSUFFICIENT`; `emergency_access_lanes` must be at least `required_emergency_access_lanes`, or `ERR_EMERGENCY_ACCESS_INSUFFICIENT`; and `barrier_linear_feet` must be at least `required_barrier_linear_feet`, or `ERR_BARRIER_INSUFFICIENT`."

        Design: Corner/errors/corner_error_safety_shortfall_codes_surface_at_submit_in_rule_order
        """
        booking = helpers.confirmed_booking(api)
        plan_state = helpers.draft_safety_plan(
            api, booking["stop_id"], **_SHORT_PROVISIONING
        )
        _revise_plan(
            api, plan_state["plan_id"], medical_als_staff_count=1, ambulance_count=1
        )

        rejected = api.submit_safety_plan(
            plan_state["plan_id"], headers=users.make_safety_author_headers()
        )

        # 800 feet is short of the 1200-foot floor even with an empty floor.
        validate_error(rejected, ApiErrorId.ERR_BARRIER_INSUFFICIENT)
        assert helpers.fetch_safety_plan(api, plan_state["plan_id"])["state"] == "DRAFT"
        assert helpers.fetch_stop(api, booking["stop_id"])["safety_state"] == "SAFETY_DRAFT"

    def test_fully_provisioned_plan_submits_and_carries_its_bill(
        self, api: ApiClient
    ) -> None:
        """PRD §3.5: "The plan's `safety_cost_cents` is the provisioning bill that later flows into settlement: each ALS medic costs 45,000 cents, each BLS medic 28,000 cents, each ambulance 120,000 cents, and each linear foot of barrier 350 cents, and the cost is the sum of `medical_als_staff_count`, `medical_bls_staff_count`, `ambulance_count` and `barrier_linear_feet` each multiplied by its own rate."

        Design: Corner/errors/corner_error_safety_shortfall_codes_surface_at_submit_in_rule_order
        """
        booking = helpers.confirmed_booking(api)
        plan_state = helpers.draft_safety_plan(
            api, booking["stop_id"], **_SHORT_PROVISIONING
        )
        _revise_plan(
            api,
            plan_state["plan_id"],
            medical_als_staff_count=1,
            ambulance_count=1,
            barrier_linear_feet=1200,
        )

        submitted = api.submit_safety_plan(
            plan_state["plan_id"], headers=users.make_safety_author_headers()
        )

        plan = validate_success(submitted)
        assert plan["state"] == "SUBMITTED"
        assert plan["safety_cost_cents"] == 641000
        assert plan["safety_cost_cents"] == (
            1 * 45000 + 2 * 28000 + 1 * 120000 + 1200 * 350
        )
        assert helpers.fetch_stop(api, booking["stop_id"])["safety_state"] == "SAFETY_REVIEW"


class TestSettlementPreparationPreconditions:
    """Preparation needs a plan and no pending order, and only ever runs once."""

    def test_stop_without_a_safety_plan_cannot_be_prepared(
        self, api: ApiClient, finance_preparer_headers: Dict[str, str]
    ) -> None:
        """PRD §3.9: "Preparation deliberately does **not** require sales to be closed — a promoter may cut a provisional settlement mid-window — but it does require that the stop already have a safety plan, or the request is rejected with `ERR_SAFETY_PLAN_MISSING`, and that no order of the stop is still in `PENDING`, or the request is rejected with `ERR_PENDING_ORDERS_OUTSTANDING`."

        Design: Corner/errors/corner_error_settlement_preparation_preconditions_and_duplicate_children
        """
        booking = helpers.confirmed_booking(api)

        rejected = api.create_settlement(
            booking["stop_id"], headers=finance_preparer_headers
        )

        validate_error(rejected, ApiErrorId.ERR_SAFETY_PLAN_MISSING)
        rows = get_success_data(
            api.get_tour_stop_settlement(
                booking["stop_id"], headers=finance_preparer_headers
            )
        )
        assert rows == []

    def test_stop_with_a_pending_order_cannot_be_prepared(
        self, api: ApiClient, finance_preparer_headers: Dict[str, str]
    ) -> None:
        """PRD §3.9: "Preparation deliberately does **not** require sales to be closed — a promoter may cut a provisional settlement mid-window — but it does require that the stop already have a safety plan, or the request is rejected with `ERR_SAFETY_PLAN_MISSING`, and that no order of the stop is still in `PENDING`, or the request is rejected with `ERR_PENDING_ORDERS_OUTSTANDING`."

        Design: Corner/errors/corner_error_settlement_preparation_preconditions_and_duplicate_children
        """
        state = helpers.stop_with_pending_order(api)
        assert state["order"]["status"] == "PENDING"

        rejected = api.create_settlement(
            state["stop_id"], headers=finance_preparer_headers
        )

        # The stop has a certified plan, so the outstanding order is what answers.
        validate_error(rejected, ApiErrorId.ERR_PENDING_ORDERS_OUTSTANDING)
        rows = get_success_data(
            api.get_tour_stop_settlement(
                state["stop_id"], headers=finance_preparer_headers
            )
        )
        assert rows == []

    def test_second_safety_plan_on_the_stop_is_a_duplicate_child(
        self, api: ApiClient, stop_on_sale: Dict[str, Any]
    ) -> None:
        """PRD §3.5: "Each stop has at most one safety plan, and a `SafetyOfficial` authors it. Creating a second plan for the same stop is rejected with `ERR_DUPLICATE_CHILD`."

        Design: Corner/errors/corner_error_settlement_preparation_preconditions_and_duplicate_children
        """
        first = helpers.fetch_safety_plan(api, stop_on_sale["plan_id"])

        rejected = api.create_safety_plan(
            stop_on_sale["stop_id"],
            factories.make_safety_plan_payload(
                barrier_linear_feet=1500,
                catch_fence_height_ft=7,
                medical_als_staff_count=2,
                medical_bls_staff_count=3,
                ambulance_count=2,
                emergency_access_lanes=2,
            ),
            headers=users.make_safety_author_headers(),
        )

        validate_error(rejected, ApiErrorId.ERR_DUPLICATE_CHILD)
        surviving = helpers.fetch_safety_plan(api, stop_on_sale["plan_id"])
        assert surviving["state"] == "CERTIFIED"
        assert surviving["barrier_linear_feet"] == first["barrier_linear_feet"]
        assert surviving["version"] == first["version"]
        rows = get_success_data(
            api.get_tour_stop_safety_plan(
                stop_on_sale["stop_id"], headers=users.make_safety_author_headers()
            )
        )
        assert len(rows) == 1

    def test_second_settlement_on_the_stop_is_a_duplicate_child(
        self, api: ApiClient, finance_preparer_headers: Dict[str, str]
    ) -> None:
        """PRD §3.9: "A stop that already has a settlement row that is not `DISPUTED` cannot have a second one: that is rejected with `ERR_DUPLICATE_CHILD`."

        Design: Corner/errors/corner_error_settlement_preparation_preconditions_and_duplicate_children
        """
        state = helpers.settlement_ready_stop(api)

        prepared = api.create_settlement(
            state["stop_id"], headers=finance_preparer_headers
        )
        settlement = validate_success(prepared, 201)
        assert settlement["state"] == "PREPARED"
        assert settlement["variant"] == "PROVISIONAL"
        assert settlement["prepared_by_user_id"] == users.FINANCE_PREPARER_USER_ID

        rejected = api.create_settlement(
            state["stop_id"], headers=finance_preparer_headers
        )

        validate_error(rejected, ApiErrorId.ERR_DUPLICATE_CHILD)
        rows = get_success_data(
            api.get_tour_stop_settlement(
                state["stop_id"], headers=finance_preparer_headers
            )
        )
        assert len(rows) == 1
        assert rows[0]["id"] == settlement["id"]
