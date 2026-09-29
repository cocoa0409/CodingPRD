"""Role authorization, entity-backed ownership and separation of duties.

Every test builds its own state from an empty database, moves time only through
the logical clock, and threads the real row id of a venue, competitor or sponsor
into the header of the role that is backed by that row.
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from test_helpers import (
    ApiClient,
    ApiErrorId,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as helpers
from test_helpers import test_users as users


# ---------------------------------------------------------------------------
# Module-local setup helpers
# ---------------------------------------------------------------------------


def _peer_competitor(api: ApiClient) -> Dict[str, Any]:
    """Register a second competing team, distinct from the canonical one."""
    return helpers.create_competitor(
        api,
        team_name="Bravo Racing",
        driver_name="L. Ortiz",
        home_market_code="PHX",
    )


def _peer_sponsor(api: ApiClient) -> Dict[str, Any]:
    """Register a second sponsor, distinct from the canonical one."""
    return helpers.create_sponsor(
        api,
        company_name="Apex Tire",
        sponsor_category="TIRE",
        contact_email="rep@apextire.example",
    )


def _cross_role_baseline(api: ApiClient) -> Dict[str, Any]:
    """A stop carrying one of every child an exclusive endpoint addresses."""
    state = helpers.stop_with_show_timing(api)
    stop_id = state["stop_id"]
    state.update(helpers.create_vehicle_entry(api, stop_id))
    state.update(helpers.create_ticket_tier(api, stop_id))
    state.update(helpers.certified_safety_plan(api, stop_id))
    state.update(helpers.create_sponsorship_activation(api, stop_id))
    state["tier"] = helpers.fetch_tier(api, state["tier_id"])
    return state


#: The exclusive endpoints, each addressed by a role that does not hold it.
_CROSS_ROLE_CALLS = (
    "promoter_adds_a_pricing_tier",
    "safety_official_places_a_ticket_order",
    "finance_controller_revises_the_safety_plan",
    "venue_manager_proposes_a_booking",
    "competitor_team_files_a_tech_inspection",
    "sponsor_rep_activates_the_package",
    "ticketing_manager_reads_the_safety_plan",
)


def _make_cross_role_call(api: ApiClient, state: Dict[str, Any], call: str):
    """Issue one exclusive-endpoint request under a role that does not hold it."""
    if call == "promoter_adds_a_pricing_tier":
        return api.create_ticket_tier(
            state["stop_id"],
            F.make_ticket_tier_payload(tier_code="CLUB", price_cents=5000, allotment=100),
            headers=users.make_series_promoter_headers(),
        )
    if call == "safety_official_places_a_ticket_order":
        return api.create_ticket_order(
            F.make_ticket_order_payload(
                state["stop_id"], state["tier_id"], state["tier"]["version"], qty=2
            ),
            headers=users.make_safety_author_headers(),
        )
    if call == "finance_controller_revises_the_safety_plan":
        return api.update_safety_plan(
            state["plan_id"],
            F.make_safety_plan_update_payload(barrier_linear_feet=2000),
            headers=users.make_finance_preparer_headers(),
        )
    if call == "venue_manager_proposes_a_booking":
        return api.create_venue_booking(
            F.make_venue_booking_payload(
                state["season_id"],
                state["venue_id"],
                tour_date=C.SECOND_TOUR_DATE,
                load_in_start_utc=C.SECOND_LOAD_IN_START_UTC,
                tear_down_end_utc=C.SECOND_TEAR_DOWN_END_UTC,
            ),
            headers=users.make_venue_manager_headers(state["venue_id"]),
        )
    if call == "competitor_team_files_a_tech_inspection":
        return api.create_tech_inspection(
            state["entry_id"],
            F.make_tech_inspection_payload(),
            headers=users.make_competitor_team_headers(state["competitor_id"]),
        )
    if call == "sponsor_rep_activates_the_package":
        return api.activate_sponsorship_activation(
            state["activation_id"],
            headers=users.make_sponsor_rep_headers(state["sponsor_id"]),
        )
    if call == "ticketing_manager_reads_the_safety_plan":
        return api.get_safety_plan(
            state["plan_id"], headers=users.make_ticketing_manager_headers()
        )
    raise AssertionError(f"unknown cross-role call: {call}")


# ---------------------------------------------------------------------------
# Each role reaching its own exclusive operation
# ---------------------------------------------------------------------------


class TestExclusiveOperationPerRole:
    """The seven roles each reach the operation that only they may perform."""

    def test_promoter_sets_the_show_timing_on_a_stop(self, api: ApiClient) -> None:
        """PRD §3.2: "The promoter fills that in with a logistics update, which
        accepts any subset of `doors_open_utc`, `show_start_utc`,
        `show_window_minutes`, `pit_party_price_cents`, `pit_party_capacity`,
        `preceding_stop_id` and `haul_distance_miles`."

        Design: Corner/rbac/corner_rbac_each_role_can_perform_its_own_exclusive_operation
        """
        state = helpers.confirmed_booking(api)

        stop = validate_success(
            api.update_tour_stop_logistics(
                state["stop_id"],
                F.make_logistics_payload(),
                headers=users.make_series_promoter_headers(),
            )
        )

        assert stop["doors_open_utc"] == C.DEFAULT_DOORS_OPEN_UTC
        assert stop["show_start_utc"] == C.DEFAULT_SHOW_START_UTC

    def test_venue_manager_counters_the_terms_of_its_own_booking(
        self, api: ApiClient
    ) -> None:
        """PRD §3.1: "A `VenueManager` for the booked building counters the terms,
        which moves the booking from `TERMS_PROPOSED` to `COUNTERED`: the counter
        supplies its own `rental_base_cents`, `revenue_share_pct` and
        `per_ticket_facility_fee_cents` plus an optional `note`, and those values
        overwrite the terms on the row; if the counter also supplies
        `load_in_start_utc` or `tear_down_end_utc`, those overwrite the occupancy
        bounds as well." "Countering sets `terms_source` to `VENUE`, records the
        caller in `last_counter_by_user_id`, increments `negotiation_round` by one
        and increments the booking's `version` by one."

        Design: Corner/rbac/corner_rbac_each_role_can_perform_its_own_exclusive_operation
        """
        state = helpers.proposed_booking(api)

        booking = validate_success(
            api.counter_venue_booking(
                state["booking_id"],
                F.make_counter_terms_payload(),
                headers=users.make_venue_manager_headers(state["venue_id"]),
            )
        )

        assert booking["state"] == "COUNTERED"
        assert booking["terms_source"] == "VENUE"
        assert booking["negotiation_round"] == 2

    def test_competitor_team_enters_its_own_vehicle(self, api: ApiClient) -> None:
        """PRD §3.3: "A `CompetitorTeam` may only enter its own vehicles; the
        promoter may enter on any team's behalf."

        Design: Corner/rbac/corner_rbac_each_role_can_perform_its_own_exclusive_operation
        """
        state = helpers.stop_with_show_timing(api)
        team = helpers.create_competitor(api)

        entry = validate_success(
            api.create_vehicle_entry(
                F.make_vehicle_entry_payload(team["competitor_id"], state["stop_id"]),
                headers=users.make_competitor_team_headers(team["competitor_id"]),
            ),
            201,
        )

        assert entry["competitor_id"] == team["competitor_id"]
        assert entry["logistics_state"] == "ENTERED"

    def test_safety_official_authors_the_stop_safety_plan(self, api: ApiClient) -> None:
        """PRD §3.5: "Each stop has at most one safety plan, and a `SafetyOfficial`
        authors it." "Creation records the caller in `authored_by_user_id`, opens
        the plan in `state` `DRAFT`, and immediately computes the requirement
        floors."

        Design: Corner/rbac/corner_rbac_each_role_can_perform_its_own_exclusive_operation
        """
        state = helpers.stop_with_show_timing(api)

        plan = validate_success(
            api.create_safety_plan(
                state["stop_id"],
                F.make_safety_plan_payload(),
                headers=users.make_safety_author_headers(),
            ),
            201,
        )

        assert plan["state"] == "DRAFT"
        assert plan["authored_by_user_id"] == users.SAFETY_AUTHOR_USER_ID

    def test_ticketing_manager_adds_a_pricing_tier(self, api: ApiClient) -> None:
        """PRD §3.6: "A `TicketingManager` builds the price card for a stop one
        tier at a time."

        Design: Corner/rbac/corner_rbac_each_role_can_perform_its_own_exclusive_operation
        """
        state = helpers.stop_with_show_timing(api)

        tier = validate_success(
            api.create_ticket_tier(
                state["stop_id"],
                F.make_ticket_tier_payload(),
                headers=users.make_ticketing_manager_headers(),
            ),
            201,
        )

        assert tier["tier_code"] == C.DEFAULT_TIER_CODE
        assert tier["allotment"] == C.DEFAULT_TIER_ALLOTMENT

    def test_sponsor_rep_proposes_its_own_sponsors_package(self, api: ApiClient) -> None:
        """PRD §3.8: "A `SponsorRep` may propose only its own sponsor's packages;
        the promoter may propose on any sponsor's behalf." "A proposed activation
        opens in `state` `PROPOSED` with `recognized_fee_cents` at 0 and
        `obligations_fulfilled_at` null."

        Design: Corner/rbac/corner_rbac_each_role_can_perform_its_own_exclusive_operation
        """
        state = helpers.stop_with_show_timing(api)
        sponsor = helpers.create_sponsor(api)

        activation = validate_success(
            api.create_sponsorship_activation(
                F.make_sponsorship_activation_payload(
                    sponsor["sponsor_id"], state["stop_id"]
                ),
                headers=users.make_sponsor_rep_headers(sponsor["sponsor_id"]),
            ),
            201,
        )

        assert activation["state"] == "PROPOSED"
        assert activation["sponsor_id"] == sponsor["sponsor_id"]

    def test_finance_controller_reaches_the_settlement_business_gate(
        self, api: ApiClient
    ) -> None:
        """PRD §3.9: "Settlement is prepared by a `FinanceController`." PRD §2.10:
        "`ERR_SAFETY_PLAN_MISSING` (409) — the stop has no safety-plan row when a
        settlement is prepared. Settlement preparation only."

        Design: Corner/rbac/corner_rbac_each_role_can_perform_its_own_exclusive_operation
        """
        state = helpers.stop_with_show_timing(api)

        resp = api.create_settlement(
            state["stop_id"], headers=users.make_finance_preparer_headers()
        )

        validate_error(resp, ApiErrorId.ERR_SAFETY_PLAN_MISSING)


# ---------------------------------------------------------------------------
# Cross-role calls on exclusive endpoints
# ---------------------------------------------------------------------------


class TestCrossRoleRefusals:
    """A role that does not hold an endpoint is refused, whatever the state."""

    @pytest.mark.parametrize("call", _CROSS_ROLE_CALLS)
    def test_cross_role_call_on_an_exclusive_endpoint_is_refused(
        self, api: ApiClient, call: str
    ) -> None:
        """PRD §2.1: "A request whose `X-User-Role` is not among the roles
        authorized for the addressed endpoint is rejected with `ERR_UNAUTHORIZED`
        (403)."

        Design: Corner/rbac/corner_rbac_cross_role_calls_on_exclusive_endpoints_are_refused
        """
        state = _cross_role_baseline(api)

        resp = _make_cross_role_call(api, state, call)

        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    def test_role_refusal_outranks_the_path_lookup(self, api: ApiClient) -> None:
        """PRD §2.10: "Where several rules could reject the same request, they are
        evaluated in a fixed order and the first failure determines the response."
        "`ERR_UNAUTHORIZED` (403) — the caller's role is not authorized for the
        endpoint. Every endpoint." "The entity-specific 404 — the `{id}` in the
        path does not resolve to a row of the addressed entity. Every endpoint
        with a path parameter."

        Design: Corner/rbac/corner_rbac_cross_role_calls_on_exclusive_endpoints_are_refused
        """
        unknown_settlement_id = "00000000-0000-0000-0000-0000000000ff"

        resp = api.approve_settlement(
            unknown_settlement_id,
            F.make_approve_settlement_payload(),
            headers=users.make_series_promoter_headers(),
        )

        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    def test_missing_or_empty_identity_is_refused_before_the_role_is_read(
        self, api: ApiClient
    ) -> None:
        """PRD §2.1: "A request with a missing or empty `X-User-ID` is rejected
        with `ERR_UNAUTHENTICATED` (401)."

        Design: Corner/rbac/corner_rbac_cross_role_calls_on_exclusive_endpoints_are_refused
        """
        state = _cross_role_baseline(api)
        empty_identity = dict(users.make_ticketing_manager_headers())
        empty_identity["X-User-ID"] = ""

        validate_error(
            api.open_tour_stop_sales(state["stop_id"], headers=empty_identity),
            ApiErrorId.ERR_UNAUTHENTICATED,
        )
        validate_error(
            api.open_tour_stop_sales(
                state["stop_id"], headers=users.make_headers_without_identity()
            ),
            ApiErrorId.ERR_UNAUTHENTICATED,
        )

    def test_refused_cross_role_calls_leave_every_row_untouched(
        self, api: ApiClient
    ) -> None:
        """PRD §2.1: "A request whose `X-User-Role` is not among the roles
        authorized for the addressed endpoint is rejected with `ERR_UNAUTHORIZED`
        (403)."

        Design: Corner/rbac/corner_rbac_cross_role_calls_on_exclusive_endpoints_are_refused
        """
        state = _cross_role_baseline(api)
        tier_version_before = state["tier"]["version"]

        for call in _CROSS_ROLE_CALLS:
            validate_error(
                _make_cross_role_call(api, state, call), ApiErrorId.ERR_UNAUTHORIZED
            )

        plan = helpers.fetch_safety_plan(api, state["plan_id"])
        assert plan["state"] == "CERTIFIED"
        assert plan["barrier_linear_feet"] == C.DEFAULT_BARRIER_LINEAR_FEET

        tier = helpers.fetch_tier(api, state["tier_id"])
        assert tier["version"] == tier_version_before
        assert tier["reserved_seat_count"] == 0

        activation = validate_success(
            api.get_sponsorship_activation(
                state["activation_id"], headers=users.make_series_promoter_headers()
            )
        )
        assert activation["state"] == "PROPOSED"

        tiers, _meta = validate_paginated(
            api.list_ticket_tiers(
                state["stop_id"], headers=users.make_ticketing_manager_headers()
            )
        )
        assert len(tiers) == 1

        stop = helpers.fetch_stop(api, state["stop_id"])
        assert stop["sales_state"] == "SALES_PENDING"


# ---------------------------------------------------------------------------
# Entity-backed identities and their peers
# ---------------------------------------------------------------------------


class TestEntityBackedOwnership:
    """An entity-backed caller reaches its own rows and no peer's rows."""

    def test_venue_manager_cannot_counter_a_peer_buildings_booking(
        self, api: ApiClient
    ) -> None:
        """PRD §2.1: "A `VenueManager` may therefore counter only bookings whose
        `venue_id` equals their own `X-User-ID`, and may dispute only the
        settlement of a stop whose booking names their venue." "Any entity-backed
        caller acting outside their own resource is rejected with
        `ERR_OWNERSHIP_MISMATCH` (403)."

        Design: Corner/rbac/corner_rbac_entity_backed_identities_cannot_reach_a_peer_s_rows
        """
        state = helpers.proposed_booking(api)
        peer = helpers.create_venue(
            api,
            venue_name=C.SECOND_VENUE_NAME,
            market_code=C.SECOND_VENUE_MARKET_CODE,
            city=C.SECOND_VENUE_CITY,
            state_code=C.SECOND_VENUE_STATE_CODE,
        )

        refused = api.counter_venue_booking(
            state["booking_id"],
            F.make_counter_terms_payload(),
            headers=users.make_venue_manager_headers(peer["venue_id"]),
        )
        validate_error(refused, ApiErrorId.ERR_OWNERSHIP_MISMATCH)

        untouched = validate_success(
            api.get_venue_booking(
                state["booking_id"], headers=users.make_series_promoter_headers()
            )
        )
        assert untouched["state"] == "TERMS_PROPOSED"
        assert untouched["negotiation_round"] == 1

        countered = validate_success(
            api.counter_venue_booking(
                state["booking_id"],
                F.make_counter_terms_payload(),
                headers=users.make_venue_manager_headers(state["venue_id"]),
            )
        )
        assert countered["state"] == "COUNTERED"
        assert countered["negotiation_round"] == 2

    def test_competitor_team_cannot_enter_a_vehicle_for_a_peer_team(
        self, api: ApiClient
    ) -> None:
        """PRD §2.1: "When `X-User-Role` is `CompetitorTeam`, `X-User-ID` is the
        `id` of the acting `Competitor`; entries may be created only with a
        `competitor_id` equal to `X-User-ID`, and only that team's own entries may
        be checked in."

        Design: Corner/rbac/corner_rbac_entity_backed_identities_cannot_reach_a_peer_s_rows
        """
        state = helpers.stop_with_show_timing(api)
        owner = helpers.create_competitor(api)
        peer = _peer_competitor(api)
        payload = F.make_vehicle_entry_payload(
            owner["competitor_id"], state["stop_id"], vehicle_number="21"
        )

        refused = api.create_vehicle_entry(
            payload, headers=users.make_competitor_team_headers(peer["competitor_id"])
        )
        validate_error(refused, ApiErrorId.ERR_OWNERSHIP_MISMATCH)

        rows, _meta = validate_paginated(
            api.list_vehicle_entries(
                {"tour_stop_id": state["stop_id"]},
                headers=users.make_series_promoter_headers(),
            )
        )
        assert [row for row in rows if row["vehicle_number"] == "21"] == []

        entry = validate_success(
            api.create_vehicle_entry(
                payload,
                headers=users.make_competitor_team_headers(owner["competitor_id"]),
            ),
            201,
        )
        assert entry["competitor_id"] == owner["competitor_id"]

    def test_competitor_team_cannot_check_in_a_peer_teams_entry(
        self, api: ApiClient
    ) -> None:
        """PRD §3.3: "It may be called by the owning `CompetitorTeam` or by the
        promoter, carries an optional `arrival_note`, and requires three things of
        the stop: its `safety_state` must be `SAFETY_CERTIFIED`, its posture must
        not be `FROZEN`, and the current logical clock must sit inside the staging
        window, which opens 8 hours before `show_start_utc` and closes 2 hours
        before `show_start_utc`, with both bounds inclusive." PRD §2.1: "Any
        entity-backed caller acting outside their own resource is rejected with
        `ERR_OWNERSHIP_MISMATCH` (403)."

        Design: Corner/rbac/corner_rbac_entity_backed_identities_cannot_reach_a_peer_s_rows
        """
        state = helpers.stop_with_show_timing(api)
        owner = helpers.create_competitor(api)
        peer = _peer_competitor(api)
        entry = helpers.create_vehicle_entry(
            api,
            state["stop_id"],
            competitor_id=owner["competitor_id"],
            headers=users.make_competitor_team_headers(owner["competitor_id"]),
        )
        helpers.certified_safety_plan(api, state["stop_id"])
        helpers.set_clock(api, C.DEFAULT_CHECK_IN_CLOCK_UTC)

        refused = api.check_in_vehicle_entry(
            entry["entry_id"],
            F.make_check_in_payload(),
            headers=users.make_competitor_team_headers(peer["competitor_id"]),
        )
        validate_error(refused, ApiErrorId.ERR_OWNERSHIP_MISMATCH)
        assert helpers.fetch_entry(api, entry["entry_id"])["logistics_state"] == "ENTERED"

        staged = validate_success(
            api.check_in_vehicle_entry(
                entry["entry_id"],
                F.make_check_in_payload(),
                headers=users.make_competitor_team_headers(owner["competitor_id"]),
            )
        )
        assert staged["logistics_state"] == "STAGED"

    def test_sponsor_rep_cannot_propose_under_a_peer_sponsor(
        self, api: ApiClient
    ) -> None:
        """PRD §2.1: "When `X-User-Role` is `SponsorRep`, `X-User-ID` is the `id`
        of the acting `Sponsor`; an activation may be proposed only with a
        `sponsor_id` equal to `X-User-ID`, and only that sponsor's own activations
        may be signed off as fulfilled."

        Design: Corner/rbac/corner_rbac_entity_backed_identities_cannot_reach_a_peer_s_rows
        """
        state = helpers.stop_with_show_timing(api)
        owner = helpers.create_sponsor(api)
        peer = _peer_sponsor(api)
        payload = F.make_sponsorship_activation_payload(
            owner["sponsor_id"], state["stop_id"]
        )

        refused = api.create_sponsorship_activation(
            payload, headers=users.make_sponsor_rep_headers(peer["sponsor_id"])
        )
        validate_error(refused, ApiErrorId.ERR_OWNERSHIP_MISMATCH)

        activation = validate_success(
            api.create_sponsorship_activation(
                payload, headers=users.make_sponsor_rep_headers(owner["sponsor_id"])
            ),
            201,
        )
        assert activation["state"] == "PROPOSED"

    def test_sponsor_rep_ownership_outranks_the_activation_state_gate(
        self, api: ApiClient
    ) -> None:
        """PRD §2.10: "`ERR_OWNERSHIP_MISMATCH` (403) — an entity-backed caller
        acting on somebody else's resource. Applies to exactly five operations:
        booking counter, vehicle-entry creation, vehicle-entry check-in,
        activation creation and activation fulfilment." "Where several rules could
        reject the same request, they are evaluated in a fixed order and the first
        failure determines the response."

        Design: Corner/rbac/corner_rbac_entity_backed_identities_cannot_reach_a_peer_s_rows
        """
        state = helpers.stop_with_show_timing(api)
        owner = helpers.create_sponsor(api)
        peer = _peer_sponsor(api)
        activation = helpers.create_sponsorship_activation(
            api, state["stop_id"], sponsor_id=owner["sponsor_id"]
        )

        refused = api.fulfill_sponsorship_activation(
            activation["activation_id"],
            F.make_fulfill_payload(),
            headers=users.make_sponsor_rep_headers(peer["sponsor_id"]),
        )

        validate_error(refused, ApiErrorId.ERR_OWNERSHIP_MISMATCH)
        untouched = validate_success(
            api.get_sponsorship_activation(
                activation["activation_id"], headers=users.make_series_promoter_headers()
            )
        )
        assert untouched["state"] == "PROPOSED"


# ---------------------------------------------------------------------------
# Safety plan authorship
# ---------------------------------------------------------------------------


class TestSafetyPlanAuthorship:
    """Authorship follows the last revision, and the author may never certify."""

    def test_plan_author_cannot_certify_their_own_plan(self, api: ApiClient) -> None:
        """PRD §2.11: "A safety plan's author is recorded in `authored_by_user_id`
        — written when the plan is created and re-stamped on every revision of a
        draft." "The `X-User-ID` certifying that plan must differ from
        `authored_by_user_id`; if it does not, the request is rejected with
        `ERR_SAFETY_SELF_CERTIFICATION` (403)."

        Design: Corner/rbac/corner_rbac_safety_plan_authorship_moves_with_the_last_patch
        """
        state = helpers.stop_with_show_timing(api)
        plan = helpers.submitted_safety_plan(api, state["stop_id"])

        refused = api.certify_safety_plan(
            plan["plan_id"],
            F.make_certify_payload(),
            headers=users.make_safety_author_headers(),
        )

        validate_error(refused, ApiErrorId.ERR_SAFETY_SELF_CERTIFICATION)
        assert helpers.fetch_safety_plan(api, plan["plan_id"])["state"] == "SUBMITTED"
        assert helpers.fetch_stop(api, state["stop_id"])["safety_state"] == "SAFETY_REVIEW"

    def test_authorship_moves_to_the_official_who_last_revised_the_plan(
        self, api: ApiClient
    ) -> None:
        """PRD §3.5: "Revising a plan overwrites whichever of the six provisioning
        fields the request supplies, re-stamps `authored_by_user_id` with the
        caller, and recomputes the floors and the cost." PRD §2.11: "The
        `X-User-ID` certifying that plan must differ from `authored_by_user_id`;
        if it does not, the request is rejected with
        `ERR_SAFETY_SELF_CERTIFICATION` (403)."

        Design: Corner/rbac/corner_rbac_safety_plan_authorship_moves_with_the_last_patch
        """
        state = helpers.stop_with_show_timing(api)
        plan_id = helpers.submitted_safety_plan(api, state["stop_id"])["plan_id"]
        first_official = users.make_safety_author_headers()
        second_official = users.make_safety_certifier_headers()

        validate_error(
            api.certify_safety_plan(
                plan_id, F.make_certify_payload(), headers=first_official
            ),
            ApiErrorId.ERR_SAFETY_SELF_CERTIFICATION,
        )

        returned = validate_success(
            api.return_safety_plan(
                plan_id, F.make_return_plan_payload(), headers=second_official
            )
        )
        assert returned["state"] == "RETURNED"
        assert helpers.fetch_stop(api, state["stop_id"])["safety_state"] == "SAFETY_DRAFT"

        revised = validate_success(
            api.update_safety_plan(
                plan_id,
                F.make_safety_plan_update_payload(catch_fence_height_ft=9),
                headers=second_official,
            )
        )
        assert revised["state"] == "DRAFT"
        assert revised["catch_fence_height_ft"] == 9
        assert revised["authored_by_user_id"] == users.SAFETY_CERTIFIER_USER_ID

        validate_success(api.submit_safety_plan(plan_id, headers=second_official))
        validate_error(
            api.certify_safety_plan(
                plan_id, F.make_certify_payload(), headers=second_official
            ),
            ApiErrorId.ERR_SAFETY_SELF_CERTIFICATION,
        )

        certified = validate_success(
            api.certify_safety_plan(
                plan_id, F.make_certify_payload(), headers=first_official
            )
        )
        assert certified["state"] == "CERTIFIED"
        assert certified["authored_by_user_id"] == users.SAFETY_CERTIFIER_USER_ID
        assert certified["certified_by_user_id"] == users.SAFETY_AUTHOR_USER_ID
        assert (
            helpers.fetch_stop(api, state["stop_id"])["safety_state"]
            == "SAFETY_CERTIFIED"
        )


# ---------------------------------------------------------------------------
# Settlement separation of duties
# ---------------------------------------------------------------------------


class TestSettlementSeparationOfDuties:
    """The preparer of a settlement is locked out of approving it."""

    def test_settlement_preparer_cannot_approve_its_own_settlement(
        self, api: ApiClient, prepared_settlement: Dict[str, Any]
    ) -> None:
        """PRD §2.11: "A settlement's preparer is recorded in
        `prepared_by_user_id` — written on the initial preparation and re-stamped
        on every re-preparation out of dispute." "The `X-User-ID` approving that
        settlement must differ from `prepared_by_user_id`; if it does not, the
        request is rejected with `ERR_SETTLEMENT_SELF_APPROVAL` (403)."

        Design: Corner/rbac/corner_rbac_settlement_preparer_is_locked_out_of_its_own_approval
        """
        refused = api.approve_settlement(
            prepared_settlement["settlement_id"],
            F.make_approve_settlement_payload(),
            headers=users.make_finance_preparer_headers(),
        )

        validate_error(refused, ApiErrorId.ERR_SETTLEMENT_SELF_APPROVAL)
        row = helpers.fetch_settlement(api, prepared_settlement["settlement_id"])
        assert row["state"] == "PREPARED"
        assert row["variant"] == "PROVISIONAL"
        assert row["approved_by_user_id"] is None
        assert (
            helpers.fetch_stop(api, prepared_settlement["stop_id"])["sales_state"]
            == "SALES_CLOSED"
        )

    def test_a_second_finance_controller_may_approve_what_the_preparer_cannot(
        self, api: ApiClient, prepared_settlement: Dict[str, Any]
    ) -> None:
        """PRD §3.9: "Approval is the terminal act, performed by a
        `FinanceController` who is not the preparer and carrying an optional
        `note`." PRD §2.9: "Approving a settlement recomputes every money field
        under the final variant, sets `variant` to `FINAL`, `state` to `APPROVED`
        and `approved_by_user_id` from the caller." "Because the settlement became
        `APPROVED`, the stop moves `sales_state` from `SALES_CLOSED` to
        `SETTLED`." "Because the stop became `SETTLED`, the season's
        `settled_stop_count` increments by one, the settlement's
        `net_to_promoter_cents` is added to the season's `season_net_cents`, and
        the season's `version` increments by one." "If, after that, the season has
        at least one tour stop, every tour stop of the season has `sales_state` in
        `SETTLED` or `CANCELLED`, and at least one of them is `SETTLED`, the
        season's `status` moves from `PLANNING` to `CLOSED` and the season's
        `version` increments again."

        Design: Corner/rbac/corner_rbac_settlement_preparer_is_locked_out_of_its_own_approval
        """
        settlement_id = prepared_settlement["settlement_id"]

        validate_error(
            api.approve_settlement(
                settlement_id,
                F.make_approve_settlement_payload(),
                headers=users.make_finance_preparer_headers(),
            ),
            ApiErrorId.ERR_SETTLEMENT_SELF_APPROVAL,
        )

        approved = validate_success(
            api.approve_settlement(
                settlement_id,
                F.make_approve_settlement_payload(),
                headers=users.make_finance_approver_headers(),
            )
        )

        assert approved["state"] == "APPROVED"
        assert approved["variant"] == "FINAL"
        assert approved["approved_by_user_id"] == users.FINANCE_APPROVER_USER_ID

        stop = helpers.fetch_stop(api, prepared_settlement["stop_id"])
        assert stop["sales_state"] == "SETTLED"

        season = helpers.fetch_season(api, prepared_settlement["season_id"])
        assert season["settled_stop_count"] == 1
        assert season["season_net_cents"] == approved["net_to_promoter_cents"]
        assert season["status"] == "CLOSED"

    def test_an_approved_settlement_cannot_be_approved_a_second_time(
        self, api: ApiClient, approved_settlement: Dict[str, Any]
    ) -> None:
        """PRD §3.9: "It requires the settlement to be `PREPARED` and the stop's
        `sales_state` to be `SALES_CLOSED`." PRD §2.10:
        "`ERR_INVALID_STATE_TRANSITION` (409) — the addressed row is not in a
        state from which the requested transition is declared."

        Design: Corner/rbac/corner_rbac_settlement_preparer_is_locked_out_of_its_own_approval
        """
        third_controller = users.make_finance_controller_headers("fc-third-3")

        resp = api.approve_settlement(
            approved_settlement["settlement_id"],
            F.make_approve_settlement_payload(),
            headers=third_controller,
        )

        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
