"""Writes whose admissibility is decided by the state of a different aggregate.

Two gates live here. Taking a stop on sale is a write on the stop's ticketing
dimension, but it is refused or admitted according to the state of the stop's
safety plan — a sibling row the request never names. And a vehicle entry parked
at ``TECH_HELD`` refuses two structurally unrelated writes on other entities: a
run-order segment that would headline it and a sponsorship package that would
brand it.
"""

from __future__ import annotations

from typing import Any, Callable, Dict

import pytest

from test_helpers import (
    ApiClient,
    ApiErrorId,
    assert_seat_pool_conserved,
    certified_safety_plan,
    commit_marketing_allocation,
    create_show_segment,
    create_sponsor,
    create_ticket_tier,
    create_vehicle_entry,
    fetch_entry,
    fetch_safety_plan,
    fetch_stop,
    fetch_tier,
    file_tech_inspection,
    get_success_data,
    make_certify_payload,
    make_check_in_payload,
    make_series_promoter_headers,
    make_show_segment_payload,
    make_sponsorship_activation_payload,
    set_clock,
    stop_with_show_timing,
    submitted_safety_plan,
    validate_error,
    validate_success,
)

#: Provisioning that exactly meets the requirement floors of a stop whose
#: expected attendance is small and whose live entries are all light rigs.
_LEAN_PROVISIONING: Dict[str, int] = {
    "barrier_linear_feet": 1200,
    "catch_fence_height_ft": 6,
    "medical_als_staff_count": 1,
    "medical_bls_staff_count": 2,
    "ambulance_count": 1,
    "emergency_access_lanes": 1,
}


def _featuring_segment_payload(entry_id: str) -> Dict[str, Any]:
    """The one run-order slot both tech-status branches of this module ask for."""
    return make_show_segment_payload(
        segment_type="COMPETITION",
        title="Grudge Match",
        run_order_position=1,
        duration_minutes=20,
        featured_vehicle_entry_id=entry_id,
    )


def _branding_activation_payload(
    sponsor_id: str, stop_id: str, entry_id: str
) -> Dict[str, Any]:
    """The one sponsorship package both tech-status branches of this module ask for."""
    return make_sponsorship_activation_payload(
        sponsor_id,
        stop_id,
        branded_vehicle_entry_id=entry_id,
        fee_cents=400000,
        vehicle_branding_slots=2,
        signage_units=4,
    )


@pytest.fixture
def stop_awaiting_certification(api: ApiClient) -> Dict[str, Any]:
    """A stop whose sales preconditions are all met except the safety plan's state.

    Show timing is set, one ``COMPETITION`` segment is in the run order, a tier is
    on the price card and radio money is committed in the market — so nothing the
    ticketing dimension itself needs is missing. The safety plan is authored and
    submitted but deliberately left uncertified.
    """
    state = stop_with_show_timing(api)
    stop_id = state["stop_id"]
    state.update(create_show_segment(api, stop_id))
    state.update(
        create_ticket_tier(
            api, stop_id, tier_code="GA", price_cents=3200, allotment=1000
        )
    )
    state.update(
        commit_marketing_allocation(
            api, stop_id, state["season_id"], channel="RADIO", amount_cents=500000
        )
    )
    state.update(submitted_safety_plan(api, stop_id, **_LEAN_PROVISIONING))
    state["stop"] = fetch_stop(api, stop_id)
    return state


@pytest.fixture
def stop_with_held_and_cleared_entries(api: ApiClient) -> Dict[str, Any]:
    """Two staged entries of one team, one held on tech and one cleared.

    Both vehicles are light rigs, so they take the two lowest staging bays of the
    building's four. The stop's safety plan is certified because check-in demands
    a certified safety envelope.
    """
    state = stop_with_show_timing(api)
    stop_id = state["stop_id"]
    state.update(certified_safety_plan(api, stop_id, **_LEAN_PROVISIONING))

    held = create_vehicle_entry(
        api,
        stop_id,
        vehicle_number="11",
        vehicle_weight_lbs=7200,
        entry_haul_distance_miles=600,
        scheduled_arrival_utc="2026-11-14T16:00:00Z",
    )
    cleared = create_vehicle_entry(
        api,
        stop_id,
        competitor_id=held["competitor_id"],
        vehicle_number="22",
        vehicle_weight_lbs=6800,
        entry_haul_distance_miles=600,
        scheduled_arrival_utc="2026-11-14T16:00:00Z",
    )
    state["competitor_id"] = held["competitor_id"]
    state["entry_held_id"] = held["entry_id"]
    state["entry_cleared_id"] = cleared["entry_id"]

    set_clock(api, "2026-11-14T17:00:00Z")
    for entry_id in (state["entry_held_id"], state["entry_cleared_id"]):
        get_success_data(
            api.check_in_vehicle_entry(
                entry_id,
                make_check_in_payload(),
                headers=make_series_promoter_headers(),
            )
        )

    file_tech_inspection(
        api,
        state["entry_held_id"],
        result="FAILED",
        defect_severity="CRITICAL",
        notes="roll cage weld",
    )
    file_tech_inspection(
        api,
        state["entry_cleared_id"],
        result="PASSED",
        defect_severity="NONE",
        notes="clean",
    )

    state.update(
        create_sponsor(
            api,
            company_name="Apex Tire",
            sponsor_category="TIRE",
            contact_email="rep@apextire.example",
            exclusive_category=False,
        )
    )
    state["stop"] = fetch_stop(api, stop_id)
    return state


class TestOpeningSalesReadsTheSafetyPlan:
    """The on-sale gate is decided by a row the on-sale request never names."""

    def test_on_sale_is_refused_while_the_sibling_plan_is_only_submitted(
        self,
        api: ApiClient,
        stop_awaiting_certification: Dict[str, Any],
        ticketing_headers: Dict[str, str],
    ) -> None:
        """PRD §3.5: "On success the plan becomes `SUBMITTED` and the stop's `safety_state` moves from `SAFETY_DRAFT` to `SAFETY_REVIEW`, with the posture recomputed."

        PRD §2.10: "`ERR_SAFETY_NOT_CERTIFIED` (409) — the stop's `safety_state` is not `SAFETY_CERTIFIED` when sales are opened or resumed. Applies to both going on sale and resuming sales."

        PRD §2.10: "`ERR_STOP_NOT_READY` (409) — the stop's posture is not `OPEN` when sales are opened or resumed. This is the final composite gate on both operations, and it is reached only after every specific safety and referential check above it has already passed; a stop that is uncertified reports `ERR_SAFETY_NOT_CERTIFIED`, a stop with no competition segment reports `ERR_RUN_ORDER_INCOMPLETE`, and only a stop that survives all of those but still fails the derived posture reports `ERR_STOP_NOT_READY`."

        Design: Difficulty/cross_entity_state_dependency/opening_sales_reads_the_safety_plan_state_of_a_different_aggregate
        """
        state = stop_awaiting_certification
        assert fetch_safety_plan(api, state["plan_id"])["state"] == "SUBMITTED"
        assert state["stop"]["safety_state"] == "SAFETY_REVIEW"
        assert state["stop"]["readiness_posture"] == "RESTRICTED"

        response = api.open_tour_stop_sales(state["stop_id"], headers=ticketing_headers)
        error = validate_error(response, ApiErrorId.ERR_SAFETY_NOT_CERTIFIED)

        # The run order, the price card and the market money are all in place, so
        # no later gate on the ladder may claim this rejection.
        assert error["error_id"] not in {
            "ERR_RUN_ORDER_INCOMPLETE",
            "ERR_NO_TICKET_TIERS",
            "ERR_STOP_NOT_READY",
        }
        assert fetch_stop(api, state["stop_id"])["sales_state"] == "SALES_PENDING"

    def test_certifying_the_plan_alone_flips_the_identical_on_sale_request(
        self,
        api: ApiClient,
        stop_awaiting_certification: Dict[str, Any],
        ticketing_headers: Dict[str, str],
        safety_certifier_headers: Dict[str, str],
    ) -> None:
        """PRD §3.5: "On success `certified_by_user_id` is set to the caller, and the stop's `safety_state` moves from `SAFETY_REVIEW` to `SAFETY_CERTIFIED`, with the posture recomputed — which is the moment a stop can first become `OPEN`."

        PRD §3.7: "A `TicketingManager` takes it on sale, moving `sales_state` from `SALES_PENDING` to `ON_SALE`, and four conditions must hold: the stop's `safety_state` must be `SAFETY_CERTIFIED`, its `competition_segment_count` must be at least 1, it must have at least one ticket tier, and its `readiness_posture` must be `OPEN`."

        Design: Difficulty/cross_entity_state_dependency/opening_sales_reads_the_safety_plan_state_of_a_different_aggregate
        """
        state = stop_awaiting_certification

        plan = validate_success(
            api.certify_safety_plan(
                state["plan_id"],
                make_certify_payload(note="provisioning verified against required_* fields"),
                headers=safety_certifier_headers,
            )
        )
        assert plan["state"] == "CERTIFIED"
        assert plan["certified_by_user_id"] == "so-certifier-2"

        # Nothing addressed the stop, yet both its safety dimension and its
        # derived posture moved.
        stop = fetch_stop(api, state["stop_id"])
        assert stop["safety_state"] == "SAFETY_CERTIFIED"
        assert stop["readiness_posture"] == "OPEN"

        opened = validate_success(
            api.open_tour_stop_sales(state["stop_id"], headers=ticketing_headers)
        )
        assert opened["sales_state"] == "ON_SALE"

    def test_the_certification_detour_never_touches_tier_inventory(
        self,
        api: ApiClient,
        stop_awaiting_certification: Dict[str, Any],
        ticketing_headers: Dict[str, str],
        safety_certifier_headers: Dict[str, str],
    ) -> None:
        """PRD §2.5: "For any `TicketTier`, its `allotment` always equals `available_seat_count` plus `reserved_seat_count` plus `sold_seat_count` plus `held_seat_count`."

        PRD §3.6: "`reserved_seat_count` is the sum of `qty` over the tier's orders in `PENDING`; `sold_seat_count` the same sum over orders in `PAID`; `held_seat_count` the sum of `hospitality_seat_count` over sponsorship activations that name this tier for hospitality and sit in `ACTIVATED` or `FULFILLED`; and `available_seat_count` is the `allotment` minus all three of those, as the conservation rule in §2.5 requires."

        Design: Difficulty/cross_entity_state_dependency/opening_sales_reads_the_safety_plan_state_of_a_different_aggregate
        """
        state = stop_awaiting_certification
        seats = []

        seats.append(fetch_tier(api, state["tier_id"]))
        api.open_tour_stop_sales(state["stop_id"], headers=ticketing_headers)
        seats.append(fetch_tier(api, state["tier_id"]))
        api.certify_safety_plan(
            state["plan_id"],
            make_certify_payload(),
            headers=safety_certifier_headers,
        )
        seats.append(fetch_tier(api, state["tier_id"]))
        api.open_tour_stop_sales(state["stop_id"], headers=ticketing_headers)
        seats.append(fetch_tier(api, state["tier_id"]))

        for tier in seats:
            assert tier["allotment"] == 1000
            assert tier["available_seat_count"] == 1000
            assert tier["reserved_seat_count"] == 0
            assert tier["sold_seat_count"] == 0
            assert tier["held_seat_count"] == 0
            assert_seat_pool_conserved(tier)


class TestTechHeldEntryBlocksOtherEntities:
    """One entry's tech status gates writes on two structurally unrelated children."""

    def test_a_held_entry_cannot_headline_a_run_order_segment(
        self,
        api: ApiClient,
        stop_with_held_and_cleared_entries: Dict[str, Any],
        promoter_headers: Dict[str, str],
    ) -> None:
        """PRD §3.3: "A `FAILED` result moves the entry to `TECH_HELD`, increments both `tech_attempt_count` and `failed_attempt_count`, re-scores readiness with the 25-point-per-failure penalty, and — uniquely among the three branches — reaches across to the stop: the stop's posture is recomputed and becomes `RESTRICTED` while any live entry of the stop sits at `TECH_HELD`, which in turn drives a stop that was `ON_SALE` to `SALES_HALTED`."

        PRD §3.3: "While an entry is `TECH_HELD` it may neither headline a run-order segment nor carry sponsor branding; both attempts are rejected with `ERR_ENTRY_TECH_HELD`."

        PRD §3.4: "Each insert also refreshes the stop's `competition_segment_count`, which is the number of the stop's segments whose `segment_type` is `COMPETITION`, and recomputes the posture — which matters because a stop with zero competition segments is held at `RESTRICTED` and cannot open sales."

        Design: Difficulty/cross_entity_state_dependency/a_tech_held_vehicle_entry_blocks_run_order_and_branding_writes_on_other_entities
        """
        state = stop_with_held_and_cleared_entries
        held = fetch_entry(api, state["entry_held_id"])
        assert held["tech_status"] == "TECH_HELD"
        assert held["failed_attempt_count"] == 1
        assert held["staging_bay_index"] == 1
        assert state["stop"]["readiness_posture"] == "RESTRICTED"

        response = api.create_show_segment(
            state["stop_id"],
            _featuring_segment_payload(state["entry_held_id"]),
            headers=promoter_headers,
        )
        validate_error(response, ApiErrorId.ERR_ENTRY_TECH_HELD)
        assert fetch_stop(api, state["stop_id"])["competition_segment_count"] == 0

    def test_a_held_entry_cannot_carry_sponsor_branding(
        self,
        api: ApiClient,
        stop_with_held_and_cleared_entries: Dict[str, Any],
        sponsor_rep_headers: Callable[[str], Dict[str, str]],
    ) -> None:
        """PRD §3.8: "Both the named tier and the named entry must belong to the addressed stop, or the proposal is rejected with `ERR_CHILD_STOP_MISMATCH`, and a branded entry sitting at `TECH_HELD` is rejected with `ERR_ENTRY_TECH_HELD`."

        PRD §2.10: "`ERR_ENTRY_TECH_HELD` (409) — a vehicle entry whose `tech_status` is `TECH_HELD` is being featured in a run-order segment or branded by an activation. Applies to exactly two operations: run-order segment creation and activation creation."

        PRD §3.8: "The `vehicle_branding_slots` are added to the branded entry's `branding_slots_committed`, which is the sum of slots over activations naming that entry in `ACTIVATED` or `FULFILLED`."

        Design: Difficulty/cross_entity_state_dependency/a_tech_held_vehicle_entry_blocks_run_order_and_branding_writes_on_other_entities
        """
        state = stop_with_held_and_cleared_entries

        response = api.create_sponsorship_activation(
            _branding_activation_payload(
                state["sponsor_id"], state["stop_id"], state["entry_held_id"]
            ),
            headers=sponsor_rep_headers(state["sponsor_id"]),
        )
        validate_error(response, ApiErrorId.ERR_ENTRY_TECH_HELD)
        assert fetch_entry(api, state["entry_held_id"])["branding_slots_committed"] == 0

    def test_the_cleared_sibling_entry_accepts_both_writes(
        self,
        api: ApiClient,
        stop_with_held_and_cleared_entries: Dict[str, Any],
        promoter_headers: Dict[str, str],
        sponsor_rep_headers: Callable[[str], Dict[str, str]],
    ) -> None:
        """PRD §3.3: "A `PASSED` result moves the entry to `TECH_CLEARED`, increments `tech_attempt_count` and re-scores readiness under `POST_STAGING`."

        PRD §3.3: "The choice within the candidate set depends on weight: an entry whose `vehicle_weight_lbs` is at least 9000 pounds is a heavy rig and takes the **highest** free bay index, staging nearest the ramp, while a lighter rig takes the **lowest** free index, staging from the far wall."

        PRD §3.4: "For each segment in turn, `reset_gap_minutes` is set to 8 minutes when the immediately preceding position's segment is also of type `COMPETITION` and this segment is of type `COMPETITION`, and to 0 in every other case, including the very first segment; that reset gap accounts for clearing and re-preparing the floor between heats."

        PRD §3.8: "A proposed activation opens in `state` `PROPOSED` with `recognized_fee_cents` at 0 and `obligations_fulfilled_at` null."

        Design: Difficulty/cross_entity_state_dependency/a_tech_held_vehicle_entry_blocks_run_order_and_branding_writes_on_other_entities
        """
        state = stop_with_held_and_cleared_entries
        cleared = fetch_entry(api, state["entry_cleared_id"])
        assert cleared["tech_status"] == "TECH_CLEARED"
        assert cleared["staging_bay_index"] == 2

        segment = validate_success(
            api.create_show_segment(
                state["stop_id"],
                _featuring_segment_payload(state["entry_cleared_id"]),
                headers=promoter_headers,
            ),
            expected_status=201,
        )
        assert segment["start_offset_minutes"] == 0
        assert segment["end_offset_minutes"] == 20

        activation = validate_success(
            api.create_sponsorship_activation(
                _branding_activation_payload(
                    state["sponsor_id"], state["stop_id"], state["entry_cleared_id"]
                ),
                headers=sponsor_rep_headers(state["sponsor_id"]),
            ),
            expected_status=201,
        )
        assert activation["state"] == "PROPOSED"
