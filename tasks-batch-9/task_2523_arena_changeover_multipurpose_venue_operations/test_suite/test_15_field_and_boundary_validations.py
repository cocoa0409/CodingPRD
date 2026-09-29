"""Boundary values on every guarded write: the inclusive edges that must pass,
the one-past edges that must fail, and the error each failure has to name."""
import pytest

from test_helpers import (
    ApiErrorId,
    CLOCK_STARTUP_UTC,
    accumulate_changeover_debt,
    confirm_booking,
    create_equipment_pool,
    draft_booking,
    issue_equipment,
    make_anchor_tenant_rep_headers,
    open_challenge,
    place_hold,
    progress_order,
    read_asset,
    read_booking,
    read_challenge,
    read_ice_sheet,
    read_order,
    read_tenant,
    read_venue,
    register_tenant,
    setup_arena,
    setup_arena_with_ice_sheet,
    setup_ice_to_concert_bookings,
    setup_ice_to_concert_turnaround,
    setup_open_challenge,
    validate_error,
    validate_paginated,
    validate_success,
    venue_version,
    TEST_USERS,
)

DIRECTOR = TEST_USERS["director_headers"]
MANAGER = TEST_USERS["booking_manager_headers"]
SUPERVISOR = TEST_USERS["changeover_supervisor_headers"]
COORDINATOR = TEST_USERS["labor_coordinator_headers"]

HOCKEY_WINDOW = ("2026-09-10T00:00:00Z", "2026-09-10T03:00:00Z")


class TestForecastAttendanceAgainstTheHouseCeiling:
    def test_a_forecast_exactly_on_the_sellable_ceiling_is_accepted(self, api):
        """PRD §3.3: "`expected_attendance` is a forecast of at least zero that must not exceed
        the `nominal_seats` of the named configuration profile; a forecast above that ceiling is a
        malformed request."
        PRD §3.1: "`nominal_seats`, greater than zero, is the number of seats sellable in this
        configuration and is the ceiling every booking's forecast attendance is measured against."

        Design: Corner/validations/expected_attendance_equal_to_the_profile_nominal_seats_is_accepted
        """
        arena = setup_arena(profiles=("ICE",), clock=CLOCK_STARTUP_UTC)
        assert arena["profiles"]["ICE"]["nominal_seats"] == 17_000

        booking = validate_success(
            api.create_event_booking(
                {
                    "venue_id": arena["venue_id"],
                    "config_profile_id": arena["profiles"]["ICE"]["id"],
                    "title": "Sold out hockey",
                    "promoter_name": "Lakeside Hockey Club",
                    "event_start_utc": HOCKEY_WINDOW[0],
                    "event_end_utc": HOCKEY_WINDOW[1],
                    "expected_attendance": 17_000,
                    "rigging_load_kg": 3_000,
                },
                MANAGER,
            ),
            201,
        )

        assert booking["expected_attendance"] == 17_000
        assert booking["status"] == "DRAFT"

    def test_one_seat_above_the_ceiling_is_a_malformed_request(self, api):
        """PRD §3.3: "`expected_attendance` is a forecast of at least zero that must not exceed
        the `nominal_seats` of the named configuration profile; a forecast above that ceiling is a
        malformed request."
        PRD §2.10: "Every required input field present, every enum value a member of its declared
        set, every numeric field inside its declared bounds, `event_end_utc` strictly after
        `event_start_utc`, `window_end_utc` strictly after `window_start_utc`, `call_end_utc`
        strictly after `call_start_utc`, `expected_attendance` no greater than the configuration
        profile's `nominal_seats`, `promoter_name` present whenever `tenant_id` is absent,
        `damaged_units` no greater than the issue's `units_issued`, and `sheet_thickness_mm`
        between 18 and 45 inclusive."
        PRD §2.10: "Any breach is `ERR_INVALID_REQUEST`."

        Design: Corner/validations/expected_attendance_above_the_profile_nominal_seats_is_rejected
        """
        arena = setup_arena(profiles=("ICE",), clock=CLOCK_STARTUP_UTC)

        response = api.create_event_booking(
            {
                "venue_id": arena["venue_id"],
                "config_profile_id": arena["profiles"]["ICE"]["id"],
                "title": "Oversold hockey",
                "promoter_name": "Lakeside Hockey Club",
                "event_start_utc": HOCKEY_WINDOW[0],
                "event_end_utc": HOCKEY_WINDOW[1],
                "expected_attendance": 17_001,
                "rigging_load_kg": 3_000,
            },
            MANAGER,
        )
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

        _rows, meta = validate_paginated(
            api.list_event_bookings(MANAGER, {"venue_id": arena["venue_id"]})
        )
        assert meta["total_count"] == 0


class TestTheDehumidificationInstallFloor:
    def test_one_litre_below_a_quarter_of_demand_fails_and_exactly_a_quarter_passes(
        self, api
    ):
        """PRD §3.6: "And the applied dehumidification must be at least one quarter of the
        profile's `dehumidification_required_lph` — evaluated inclusively, so exactly a quarter of
        the demand passes — otherwise `ERR_DEHUMIDIFICATION_INSUFFICIENT`."
        PRD §3.6: "The install snapshots the profile's moisture demand onto the sheet as
        `required_dehumidification_lph`."
        PRD §3.6: "Those three are combined with weights of 0.45 for the dehumidification deficit,
        0.30 for the cover load and 0.25 for the thickness deficit; the weighted sum is multiplied
        by 100 and rounded half up to two decimal places to give `condensation_risk_score`."
        PRD §3.6: "The arena's `ice_deck_status` becomes `BUILDING` and its `version` advances by
        one."

        Design: Corner/validations/ice_install_below_a_quarter_of_the_required_dehumidification_is_rejected
        """
        arena = setup_arena(profiles=("ICE",), clock=CLOCK_STARTUP_UTC)
        version_before = venue_version(arena["venue_id"])

        refused = api.create_ice_sheet(
            arena["venue_id"],
            {
                "config_profile_id": arena["profiles"]["ICE"]["id"],
                "dehumidification_lph_applied": 29,
                "sheet_thickness_mm": 32,
            },
            SUPERVISOR,
        )
        validate_error(
            refused, ApiErrorId.ERR_DEHUMIDIFICATION_INSUFFICIENT.value, 422
        )
        venue = read_venue(arena["venue_id"])
        assert venue["ice_deck_status"] == "NONE"
        assert venue["version"] == version_before

        accepted = validate_success(
            api.create_ice_sheet(
                arena["venue_id"],
                {
                    "config_profile_id": arena["profiles"]["ICE"]["id"],
                    "dehumidification_lph_applied": 30,
                    "sheet_thickness_mm": 32,
                },
                SUPERVISOR,
            ),
            201,
        )
        assert accepted["status"] == "BUILDING"
        assert float(accepted["condensation_risk_score"]) == pytest.approx(
            33.75, abs=0.005
        ), "three quarters of the demand missing, weighted at 0.45"

        venue = read_venue(arena["venue_id"])
        assert venue["ice_deck_status"] == "BUILDING"
        assert venue["version"] == version_before + 1


class TestTheFloorProtectionGate:
    def test_laying_needs_the_full_set_count_while_striking_is_never_gated(self, api):
        """PRD §3.8: "The system sums `units_issued` across every equipment issue on this order
        whose `status` is `ISSUED` and whose pool has an `asset_class` of `FLOOR_PANEL_SET`, and
        requires that sum to be at least the incoming configuration's
        `floor_protection_panels_required` divided by 40 panels per set and rounded up to a whole
        number of sets."
        PRD §3.8: "The comparison is inclusive, so exactly the required set count passes; anything
        less is refused with `ERR_FLOOR_PROTECTION_SHORTFALL`."
        PRD §3.8: "The first progress call accepted on an order stamps `started_at_utc` with the
        logical clock instant and moves the compound `status` from `PLANNED` to `IN_PROGRESS`."
        PRD §3.8: "Each progress call names exactly one `dimension` — `FLOOR`, `SEATING` or
        `INFRA` — and the `to_stage` it should advance to, and it advances exactly one stage on
        exactly that dimension, leaving the other two untouched."

        Design: Corner/validations/floor_advance_to_laying_without_the_required_panel_sets_is_rejected
        """
        arena = setup_ice_to_concert_turnaround(
            crew_headcount=40, confirm_incoming=True, floor_panel_units_total=10
        )
        order_id = arena["order"]["id"]
        assert arena["profiles"]["CONCERT"]["floor_protection_panels_required"] == 120
        issue_equipment(arena["floor_pool"]["id"], order_id, 2)

        striking = progress_order(order_id, "FLOOR", "STRIKING")
        assert striking["floor_stage"] == "STRIKING"
        assert striking["status"] == "IN_PROGRESS"

        refused = api.progress_changeover_order(
            order_id, {"dimension": "FLOOR", "to_stage": "LAYING"}, SUPERVISOR
        )
        validate_error(
            refused, ApiErrorId.ERR_FLOOR_PROTECTION_SHORTFALL.value, 422
        )
        assert read_order(order_id)["floor_stage"] == "STRIKING", (
            "two sets fall short of the three the concert needs"
        )

        issue_equipment(arena["floor_pool"]["id"], order_id, 1)
        laying = progress_order(order_id, "FLOOR", "LAYING")
        assert laying["floor_stage"] == "LAYING", "exactly three sets passes"

        assert read_asset(arena["floor_pool"]["id"])["units_available"] == 7
        final = read_order(order_id)
        assert final["seating_stage"] == "NOT_STARTED"
        assert final["infra_stage"] == "NOT_STARTED"


class TestTheChangeoverDebtFreeze:
    def test_a_ledger_sitting_exactly_on_three_hours_freezes_new_work(self, api):
        """PRD §3.7: "Then the arena's `changeover_debt_minutes` must be strictly below three
        hours of accumulated overrun, otherwise `ERR_CHANGEOVER_DEBT_FREEZE` — a building that has
        already blown its turnaround targets by three hours in aggregate may not open new work
        until a director clears the backlog."
        PRD §3.8: "`overrun_minutes` is then the amount by which the actual measurement exceeds
        `window_minutes`, floored at zero: an order that finished inside its window records an
        overrun of 0."
        PRD §3.8: "The arena's `changeover_debt_minutes` rises by exactly this order's
        `overrun_minutes`."
        PRD §3.8: "That ledger is monotonic — it is never decremented by any operation in this
        system — and once it reaches or passes three hours it freezes the opening of new
        turnarounds, as §3.7 describes and as the readiness projection reports."
        PRD §3.8: "`actual_turnaround_minutes` is the span from `started_at_utc` to
        `completed_at_utc`, expressed in whole minutes with any fractional minute discarded —
        rounded down."

        Design: Corner/validations/changeover_order_at_exactly_the_debt_freeze_threshold_is_rejected
        """
        arena = accumulate_changeover_debt(180)
        signed = arena["signed_order"]
        assert signed["window_minutes"] == 735
        assert signed["planned_turnaround_minutes"] == 708
        assert signed["actual_turnaround_minutes"] == 915
        assert signed["overrun_minutes"] == 180
        assert read_venue(arena["venue_id"])["changeover_debt_minutes"] == 180

        next_show = draft_booking(
            arena["venue_id"], arena["profiles"]["ICE"]["id"], "Hockey Sep 12",
            "2026-09-12T00:00:00Z", "2026-09-12T03:00:00Z",
            expected_attendance=15_000, rigging_load_kg=3_000,
            promoter_name="Lakeside Hockey Club",
        )
        place_hold(next_show["id"])
        version_frozen = venue_version(arena["venue_id"])

        response = api.create_changeover_order(
            {
                "from_booking_id": arena["to_booking"]["id"],
                "to_booking_id": next_show["id"],
                "crew_headcount": 30,
                "expected_venue_version": version_frozen,
            },
            SUPERVISOR,
        )
        validate_error(response, ApiErrorId.ERR_CHANGEOVER_DEBT_FREEZE.value, 409)

        _rows, meta = validate_paginated(
            api.list_changeover_orders(SUPERVISOR, {"venue_id": arena["venue_id"]})
        )
        assert meta["total_count"] == 1, "only the signed-off turnaround exists"
        assert venue_version(arena["venue_id"]) == version_frozen

        readiness = validate_success(
            api.get_changeover_readiness(signed["id"], DIRECTOR), 200
        )
        assert readiness["blocking_reasons"] == ["CHANGEOVER_DEBT_FREEZE"], (
            "every dimension is terminal, so the frozen ledger is the only blocker"
        )


class TestTheUpheldRulingGuards:
    def test_two_equal_tiers_cannot_displace_each_other_but_can_be_denied(self, api):
        """PRD §3.4: "Then the stored `priority_delta` must be at least 1; a delta of exactly zero,
        meaning equal tiers, is insufficient, while a delta of exactly 1 suffices, and anything
        below 1 is `ERR_HOLD_PRIORITY_INSUFFICIENT`."
        PRD §3.4: "The delta is the ordinal of the incumbent booking's **pinned** `hold_tier` minus
        the ordinal of the challenging tenant's current `hold_priority_tier`, so it lands somewhere
        between negative three and positive three."
        PRD §3.4: "A `DENIED` ruling has no further preconditions: `ruled_at` is stamped with the
        logical clock instant, the `ruling_note` is stored when supplied, and — provided the
        incumbent booking is still `CHALLENGED` and no other challenge against it remains `OPEN`
        — the incumbent moves `CHALLENGED → HELD` with `hold_tier`, `hold_placed_at` and
        `hold_expires_at` left exactly as they were before the contest."
        PRD §3.4: "A denial does not refund the credit; a spent challenge that was actually
        adjudicated stays spent."
        PRD §3.3: "A fresh draft has `status` reading `DRAFT`; `hold_tier`, `hold_placed_at`,
        `hold_expires_at`, `release_reason` and `displaced_by_booking_id` all unset; and
        `displacement_penalty_cents` at 0."

        Design: Corner/validations/equal_tier_challenge_cannot_be_upheld_for_insufficient_priority
        """
        arena = setup_open_challenge(
            incumbent_tier="TIER_2", challenger_tier="TIER_2"
        )
        challenge_id = arena["challenge"]["id"]
        incumbent_id = arena["incumbent_booking"]["id"]
        assert arena["challenge"]["priority_delta"] == 0, "tier two against tier two"

        refused = api.rule_hold_challenge(
            challenge_id,
            {"decision": "UPHELD", "ruling_note": "challenger claims the slot"},
            MANAGER,
        )
        validate_error(
            refused, ApiErrorId.ERR_HOLD_PRIORITY_INSUFFICIENT.value, 409
        )
        pending = read_challenge(challenge_id)
        assert pending["status"] == "OPEN"
        assert pending["ruled_at"] is None
        assert read_booking(incumbent_id)["status"] == "CHALLENGED"

        denied = validate_success(
            api.rule_hold_challenge(
                challenge_id,
                {
                    "decision": "DENIED",
                    "ruling_note": "equal tier, incumbent keeps the hold",
                },
                MANAGER,
            ),
            200,
        )
        assert denied["status"] == "DENIED"

        incumbent = read_booking(incumbent_id)
        assert incumbent["status"] == "HELD"
        assert incumbent["hold_expires_at"] == "2026-08-08T00:00:00.000Z"
        assert incumbent["displaced_by_booking_id"] is None
        assert incumbent["displacement_penalty_cents"] == 0
        assert read_tenant(
            arena["venue_id"], arena["challenger_tenant"]["id"]
        )["challenge_credits"] == 1, "an adjudicated challenge stays spent"

    def test_a_top_tier_hold_reports_protection_rather_than_thin_priority(self, api):
        """PRD §3.4: "An `UPHELD` ruling is guarded by two further checks, evaluated in this
        order."
        PRD §3.4: "The incumbent booking's pinned `hold_tier` must not be `TIER_1`, because a
        top-tier anchor hold can never be displaced; an attempt is `ERR_ANCHOR_HOLD_PROTECTED`."
        PRD §3.4: "Each tier maps to an ordinal in which a *smaller* number is a *stronger*
        contractual claim: `TIER_1` maps to 1, `TIER_2` to 2, `TIER_3` to 3, and `OPEN` to 4."
        PRD §3.4: "The challenge must be `OPEN`, otherwise `ERR_INVALID_CHALLENGE_STATE`."

        Design: Corner/validations/tier_one_incumbent_hold_cannot_be_displaced_by_any_challenger
        """
        arena = setup_open_challenge(
            incumbent_tier="TIER_1", challenger_tier="TIER_1"
        )
        assert arena["challenge"]["priority_delta"] == 0
        assert read_booking(arena["incumbent_booking"]["id"])["hold_tier"] == "TIER_1"
        version_before = venue_version(arena["venue_id"])

        response = api.rule_hold_challenge(
            arena["challenge"]["id"],
            {
                "decision": "UPHELD",
                "ruling_note": "attempt against a protected anchor hold",
            },
            MANAGER,
        )
        validate_error(response, ApiErrorId.ERR_ANCHOR_HOLD_PROTECTED.value, 409)

        stored = read_challenge(arena["challenge"]["id"])
        assert stored["status"] == "OPEN"
        assert stored["ruled_at"] is None
        incumbent = read_booking(arena["incumbent_booking"]["id"])
        assert incumbent["status"] == "CHALLENGED"
        assert incumbent["displaced_by_booking_id"] is None
        assert venue_version(arena["venue_id"]) == version_before


class TestChallengeCreationGuards:
    def test_the_same_tenant_may_not_contest_one_hold_twice_at_once(self, api):
        """PRD §3.4: "And no challenge may already exist with the same `booking_id` and the same
        `challenger_tenant_id` in `OPEN` status, otherwise `ERR_DUPLICATE_CHALLENGE`."
        PRD §3.4: "On acceptance the challenge is created `OPEN`, its `priority_delta` is computed
        and frozen, the challenging tenant's `challenge_credits` drops by one, and the arena's
        `version` advances by one."
        PRD §3.2: "`challenge_credits` is the tenant's remaining budget of hold challenges; a
        freshly registered tenant is granted exactly two credits."

        Design: Corner/validations/second_open_challenge_from_the_same_tenant_is_rejected_as_duplicate
        """
        arena = setup_open_challenge(
            incumbent_tier="TIER_2", challenger_tier="TIER_1"
        )
        challenger_tenant_id = arena["challenger_tenant"]["id"]
        incumbent_id = arena["incumbent_booking"]["id"]

        second_draft = draft_booking(
            arena["venue_id"], arena["profiles"]["ICE"]["id"],
            "Challenger second draft",
            "2026-09-11T00:00:00Z", "2026-09-11T03:00:00Z",
            expected_attendance=15_000, rigging_load_kg=3_000,
            tenant_id=challenger_tenant_id,
        )

        response = api.create_hold_challenge(
            {
                "booking_id": incumbent_id,
                "challenger_tenant_id": challenger_tenant_id,
                "challenger_booking_id": second_draft["id"],
            },
            make_anchor_tenant_rep_headers(challenger_tenant_id),
        )
        validate_error(response, ApiErrorId.ERR_DUPLICATE_CHALLENGE.value, 409)

        rows, meta = validate_paginated(
            api.list_hold_challenges(MANAGER, {"booking_id": incumbent_id})
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == arena["challenge"]["id"]
        assert read_tenant(
            arena["venue_id"], challenger_tenant_id
        )["challenge_credits"] == 1, "charged once and not twice"
        assert read_booking(incumbent_id)["status"] == "CHALLENGED"
        assert read_booking(second_draft["id"])["status"] == "DRAFT"

    def test_the_third_challenge_on_a_two_credit_grant_is_refused(self, api):
        """PRD §3.4: "The challenging tenant must have at least one remaining `challenge_credits`,
        otherwise `ERR_CHALLENGE_CREDITS_EXHAUSTED`."
        PRD §3.2: "`challenge_credits` is the tenant's remaining budget of hold challenges; a
        freshly registered tenant is granted exactly two credits."
        PRD §3.2: "A credit is spent when the tenant opens a challenge and is restored only when
        the tenant itself withdraws that challenge — a challenge that is ruled on, in either
        direction, consumes the credit permanently."
        PRD §3.4: "The incumbent booking must be `HELD` or `CHALLENGED` — a second anchor tenant is
        expressly permitted to open its own challenge against a hold that is already contested —
        and the challenger's own booking must be `DRAFT`; either violation is
        `ERR_INVALID_BOOKING_STATE`."

        Design: Corner/validations/third_challenge_from_a_tenant_granted_two_credits_is_rejected
        """
        arena = setup_arena(profiles=("ICE",), clock=CLOCK_STARTUP_UTC)
        venue_id = arena["venue_id"]
        profile_id = arena["profiles"]["ICE"]["id"]
        incumbent = register_tenant(venue_id, "Lakeside Hockey Club", "TIER_2", 5)
        challenger = register_tenant(venue_id, "Riverton Athletics", "TIER_1", 5)
        challenger_headers = make_anchor_tenant_rep_headers(challenger["id"])

        incumbent_bookings = []
        challenger_bookings = []
        for day in ("10", "11", "12"):
            held = draft_booking(
                venue_id, profile_id, f"Incumbent hold Sep {day}",
                f"2026-09-{day}T00:00:00Z", f"2026-09-{day}T03:00:00Z",
                expected_attendance=15_000, rigging_load_kg=3_000,
                tenant_id=incumbent["id"],
            )
            place_hold(held["id"], make_anchor_tenant_rep_headers(incumbent["id"]))
            incumbent_bookings.append(held)
            challenger_bookings.append(
                draft_booking(
                    venue_id, profile_id, f"Challenger draft Sep {day}",
                    f"2026-09-{day}T00:00:00Z", f"2026-09-{day}T03:00:00Z",
                    expected_attendance=15_000, rigging_load_kg=3_000,
                    tenant_id=challenger["id"],
                )
            )

        filed = [
            open_challenge(
                incumbent_bookings[index]["id"], challenger["id"],
                challenger_bookings[index]["id"], challenger_headers,
            )
            for index in range(2)
        ]
        assert read_tenant(venue_id, challenger["id"])["challenge_credits"] == 0

        response = api.create_hold_challenge(
            {
                "booking_id": incumbent_bookings[2]["id"],
                "challenger_tenant_id": challenger["id"],
                "challenger_booking_id": challenger_bookings[2]["id"],
            },
            challenger_headers,
        )
        validate_error(
            response, ApiErrorId.ERR_CHALLENGE_CREDITS_EXHAUSTED.value, 409
        )

        rows, meta = validate_paginated(
            api.list_hold_challenges(
                MANAGER, {"challenger_tenant_id": challenger["id"]}
            )
        )
        assert meta["total_count"] == 2
        assert {row["id"] for row in rows} == {filed[0]["id"], filed[1]["id"]}
        assert read_booking(incumbent_bookings[2]["id"])["status"] == "HELD", (
            "the refused challenge never pushed the third hold into contest"
        )
        assert read_booking(challenger_bookings[2]["id"])["status"] == "DRAFT"


class TestTheExclusiveLaborCallScope:
    def test_naming_both_scopes_and_naming_neither_are_both_refused(self, api):
        """PRD §3.9: "Scope is exclusive: exactly one of `changeover_order_id` and `booking_id`
        must be supplied and non-null, so that a call is unambiguously either changeover-crew work
        or a show's load-in and load-out labor."
        PRD §3.9: "Supplying both or neither is `ERR_LABOR_CALL_SCOPE_INVALID`."
        PRD §3.9: "A call is created `CALLED` with `actual_hours` and `settled_cost_cents` unset
        and `cancellation_fee_cents` at 0, and finishes as either `WORKED` or `CANCELLED`, both
        terminal."

        Design: Corner/validations/labor_call_with_both_scopes_or_with_neither_scope_is_rejected
        """
        arena = setup_ice_to_concert_turnaround(
            crew_headcount=40, confirm_incoming=True
        )
        order_id = arena["order"]["id"]
        booking_id = arena["to_booking"]["id"]
        version_after_open = venue_version(arena["venue_id"])
        shift = {
            "craft": "STAGEHAND",
            "headcount": 10,
            "call_start_utc": "2026-09-10T04:00:00Z",
            "call_end_utc": "2026-09-10T12:00:00Z",
            "guaranteed_hours": 8,
        }

        both = api.create_labor_call(
            dict(shift, changeover_order_id=order_id, booking_id=booking_id),
            COORDINATOR,
        )
        validate_error(both, ApiErrorId.ERR_LABOR_CALL_SCOPE_INVALID.value, 400)

        neither = api.create_labor_call(dict(shift), COORDINATOR)
        validate_error(neither, ApiErrorId.ERR_LABOR_CALL_SCOPE_INVALID.value, 400)

        _order_rows, order_meta = validate_paginated(
            api.list_labor_calls(COORDINATOR, {"changeover_order_id": order_id})
        )
        assert order_meta["total_count"] == 0
        _booking_rows, booking_meta = validate_paginated(
            api.list_labor_calls(COORDINATOR, {"booking_id": booking_id})
        )
        assert booking_meta["total_count"] == 0

        assert read_order(order_id)["status"] == "PLANNED"
        assert venue_version(arena["venue_id"]) == version_after_open, (
            "neither refusal touched the arena row"
        )


class TestTheDockNumberRange:
    def test_the_dock_above_the_count_is_refused_while_the_last_dock_is_taken(self, api):
        """PRD §3.9: "Only then is `dock_number` checked to lie between 1 and the arena's
        `dock_count` inclusive, with `ERR_DOCK_NUMBER_INVALID` otherwise."
        PRD §3.9: "A reservation is created `RESERVED`; the only other state is `RELEASED`, which
        is terminal."
        PRD §3.9: "The booking must be `HELD`, `CHALLENGED` or `CONFIRMED`, otherwise
        `ERR_INVALID_BOOKING_STATE`."
        PRD §3.9: "A booking's reservations are listed through a reverse-reachability read that can
        be narrowed by `purpose` and by `status`."

        Design: Corner/validations/dock_number_above_the_venue_dock_count_is_rejected
        """
        arena = setup_arena(profiles=("CONCERT",), clock=CLOCK_STARTUP_UTC)
        assert read_venue(arena["venue_id"])["dock_count"] == 4
        draft = draft_booking(
            arena["venue_id"], arena["profiles"]["CONCERT"]["id"], "Concert Sep 10",
            "2026-09-10T16:00:00Z", "2026-09-10T19:00:00Z",
            expected_attendance=8_000, rigging_load_kg=5_000,
            promoter_name="Northline Live",
        )
        place_hold(draft["id"])
        confirm_booking(draft["id"], arena["venue_id"])
        window = {
            "purpose": "LOAD_IN",
            "window_start_utc": "2026-09-10T06:00:00Z",
            "window_end_utc": "2026-09-10T10:00:00Z",
            "truck_count": 12,
        }

        refused = api.create_dock_slot_reservation(
            draft["id"], dict(window, dock_number=5), SUPERVISOR
        )
        validate_error(refused, ApiErrorId.ERR_DOCK_NUMBER_INVALID.value, 422)

        accepted = validate_success(
            api.create_dock_slot_reservation(
                draft["id"], dict(window, dock_number=4), SUPERVISOR
            ),
            201,
        )
        assert accepted["dock_number"] == 4, "the last legal dock is inside the bound"
        assert accepted["status"] == "RESERVED"

        rows, meta = validate_paginated(
            api.list_dock_slot_reservations(draft["id"], SUPERVISOR)
        )
        assert meta["total_count"] == 1
        assert rows[0]["dock_number"] == 4


class TestTheOrderSequencingCheck:
    def test_an_inverted_pair_of_dates_reports_sequencing_and_not_a_short_window(
        self, api
    ):
        """PRD §3.7: "Then the structural ordering check: the incoming event's `event_start_utc`
        must be strictly after the outgoing event's `event_end_utc`, otherwise
        `ERR_ORDER_BOOKING_SEQUENCE_INVALID`."
        PRD §3.7: "That check deliberately runs before any window arithmetic so that an inverted
        pair of dates reports the sequencing fault rather than a nonsensical negative window."
        PRD §3.7: "Then the window must be long enough for the frozen plan, otherwise
        `ERR_TURNAROUND_WINDOW_INSUFFICIENT`."
        PRD §3.3: "First, no other booking on the same arena whose `status` is `CONFIRMED` may
        overlap this booking's event interval under the unbuffered half-open convention of §2.7; an
        overlap is `ERR_BOOKING_TIME_CONFLICT`."

        Design: Corner/validations/order_whose_incoming_event_starts_before_the_outgoing_event_ends_is_rejected
        """
        arena = setup_arena(clock=CLOCK_STARTUP_UTC)
        setup_ice_to_concert_bookings(
            arena,
            ice_event=("2026-09-10T00:00:00Z", "2026-09-10T03:00:00Z"),
            concert_event=("2026-09-10T02:00:00Z", "2026-09-10T05:00:00Z"),
            confirm_incoming=True,
        )
        assert read_booking(arena["from_booking"]["id"])["status"] == "HELD", (
            "the outgoing show is never confirmed, so the overlap itself is legal"
        )
        version_before = venue_version(arena["venue_id"])

        response = api.create_changeover_order(
            {
                "from_booking_id": arena["from_booking"]["id"],
                "to_booking_id": arena["to_booking"]["id"],
                "crew_headcount": 40,
                "expected_venue_version": version_before,
            },
            SUPERVISOR,
        )
        validate_error(
            response, ApiErrorId.ERR_ORDER_BOOKING_SEQUENCE_INVALID.value, 422
        )

        _rows, meta = validate_paginated(
            api.list_changeover_orders(SUPERVISOR, {"venue_id": arena["venue_id"]})
        )
        assert meta["total_count"] == 0
        assert venue_version(arena["venue_id"]) == version_before


class TestTheConfirmedBookingConflictInterval:
    def test_an_overlapping_show_is_refused_while_a_touching_show_confirms(self, api):
        """PRD §3.3: "First, no other booking on the same arena whose `status` is `CONFIRMED` may
        overlap this booking's event interval under the unbuffered half-open convention of §2.7; an
        overlap is `ERR_BOOKING_TIME_CONFLICT`."
        PRD §2.7: "Two intervals collide when the first starts strictly before the second ends *and*
        the second starts strictly before the first ends."
        PRD §2.7: "Intervals that merely touch at an endpoint — one ending at exactly the instant
        the next begins — do not collide."
        PRD §3.3: "On success the booking moves `HELD → CONFIRMED`, the arena's `open_hold_count`
        drops by one, `rigging_committed_load_kg` is recomputed, and the arena's `version` advances
        by one."
        PRD §3.3: "The stored arena field `rigging_committed_load_kg` uses exactly the same
        closed-interval arithmetic with the logical clock instant standing in as a zero-length
        candidate window: it is the sum of `rigging_load_kg` over confirmed bookings whose closed
        event interval contains the current instant."

        Design: Corner/validations/confirming_a_time_overlapping_booking_is_rejected_while_a_touching_booking_is_accepted
        """
        arena = setup_arena(profiles=("ICE",), clock=CLOCK_STARTUP_UTC)
        venue_id = arena["venue_id"]
        profile_id = arena["profiles"]["ICE"]["id"]

        windows = [
            ("Anchor game", "2026-09-10T00:00:00Z", "2026-09-10T03:00:00Z"),
            ("Overlapping game", "2026-09-10T02:00:00Z", "2026-09-10T05:00:00Z"),
            ("Touching game", "2026-09-10T03:00:00Z", "2026-09-10T06:00:00Z"),
        ]
        bookings = []
        for title, start, end in windows:
            draft = draft_booking(
                venue_id, profile_id, title, start, end,
                expected_attendance=15_000, rigging_load_kg=0,
                promoter_name="Lakeside Hockey Club",
            )
            place_hold(draft["id"])
            bookings.append(draft)
        confirm_booking(bookings[0]["id"], venue_id)
        version_before = venue_version(venue_id)

        refused = api.confirm_event_booking(
            bookings[1]["id"], {"expected_venue_version": version_before}, MANAGER
        )
        validate_error(refused, ApiErrorId.ERR_BOOKING_TIME_CONFLICT.value, 409)
        assert read_booking(bookings[1]["id"])["status"] == "HELD"
        assert venue_version(venue_id) == version_before, (
            "the refusal leaves the same expected version usable"
        )

        accepted = validate_success(
            api.confirm_event_booking(
                bookings[2]["id"], {"expected_venue_version": version_before}, MANAGER
            ),
            200,
        )
        assert accepted["status"] == "CONFIRMED", (
            "a show that starts exactly when the previous one ends does not collide"
        )

        assert float(read_venue(venue_id)["rigging_committed_load_kg"]) == pytest.approx(
            0.00, abs=0.005
        ), "neither September window contains the August clock instant"
        rows, meta = validate_paginated(
            api.list_event_bookings(
                MANAGER, {"venue_id": venue_id, "status": "CONFIRMED"}
            )
        )
        assert meta["total_count"] == 2
        assert {row["id"] for row in rows} == {bookings[0]["id"], bookings[2]["id"]}


class TestTheEquipmentAvailabilityCheck:
    def test_the_last_unit_goes_out_and_the_unit_after_it_does_not(self, api):
        """PRD §3.9: "Four conditions guard it, in this order: the order's `status` must be neither
        `SIGNED_OFF` nor `ABANDONED`, otherwise `ERR_INVALID_ORDER_STATE`; the pool's `status` must
        be `IN_SERVICE`, otherwise `ERR_ASSET_OUT_OF_SERVICE`; `units_issued` must not exceed the
        pool's `units_available`, evaluated inclusively so that taking the last available unit
        succeeds, otherwise `ERR_EQUIPMENT_UNITS_UNAVAILABLE`; and the pool's arena must be the same
        arena as the order's, otherwise `ERR_VENUE_SCOPE_MISMATCH`."
        PRD §3.9: "The issue is created `ISSUED` — the only other state is `RETURNED`, which is
        terminal — and the pool's `units_available` falls by `units_issued`."
        PRD §3.9: "Availability is always derived, never written directly: `units_available` is
        `units_total` less `units_out_of_service` less the sum of `units_issued` across every
        equipment issue on that pool whose `status` is `ISSUED`."
        PRD §3.9: "The pool's `cycles_since_service` rises by one and `service_due` is re-evaluated
        against `service_interval_cycles`."

        Design: Corner/validations/issuing_one_unit_more_than_the_pool_holds_is_rejected_after_the_last_unit_is_taken
        """
        arena = setup_ice_to_concert_turnaround(crew_headcount=40)
        pool = create_equipment_pool(arena["venue_id"], "STAGE_DECK", 3)
        order_id = arena["order"]["id"]

        issue = validate_success(
            api.create_equipment_issue(
                {
                    "asset_id": pool["id"],
                    "changeover_order_id": order_id,
                    "units_issued": 3,
                },
                SUPERVISOR,
            ),
            201,
        )
        assert issue["units_issued"] == 3
        assert issue["status"] == "ISSUED"

        emptied = read_asset(pool["id"])
        assert emptied["units_available"] == 0
        assert emptied["units_total"] == 3
        assert emptied["units_out_of_service"] == 0

        response = api.create_equipment_issue(
            {
                "asset_id": pool["id"],
                "changeover_order_id": order_id,
                "units_issued": 1,
            },
            SUPERVISOR,
        )
        validate_error(
            response, ApiErrorId.ERR_EQUIPMENT_UNITS_UNAVAILABLE.value, 409
        )

        rows, meta = validate_paginated(
            api.list_equipment_issues(SUPERVISOR, {"asset_id": pool["id"]})
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == issue["id"]
        still_empty = read_asset(pool["id"])
        assert still_empty["units_available"] == 0
        assert still_empty["cycles_since_service"] == 0, (
            "a refused issue is not a cycle"
        )


class TestTheSingleLiveIceSheetRule:
    def test_a_second_flood_over_a_building_sheet_is_refused(self, api):
        """PRD §3.6: "The arena must have no existing sheet outside `REMOVED`, otherwise
        `ERR_ICE_SHEET_ALREADY_PRESENT`."
        PRD §3.6: "An arena carries at most one live ice sheet."
        PRD §3.6: "The new sheet starts with `status` reading `BUILDING`, `cover_cycles` at 0,
        `cover_hours_accumulated` at 0, an initial `condensation_risk_score`, and
        `cover_installed_at_utc` unset."
        PRD §3.6: "The arena's sheet list includes retired sheets so that cover history is
        auditable, and can be narrowed by `status`."

        Design: Corner/validations/installing_a_second_ice_sheet_while_one_is_present_is_rejected
        """
        arena = setup_arena_with_ice_sheet(
            dehumidification_lph_applied=120,
            sheet_thickness_mm=32,
            to_status="BUILDING",
            profiles=("ICE",),
        )
        first_sheet = arena["ice_sheet"]

        response = api.create_ice_sheet(
            arena["venue_id"],
            {
                "config_profile_id": arena["profiles"]["ICE"]["id"],
                "dehumidification_lph_applied": 120,
                "sheet_thickness_mm": 32,
            },
            SUPERVISOR,
        )
        validate_error(response, ApiErrorId.ERR_ICE_SHEET_ALREADY_PRESENT.value, 409)

        rows, meta = validate_paginated(
            api.list_ice_sheets(arena["venue_id"], SUPERVISOR)
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == first_sheet["id"]
        stored = read_ice_sheet(arena["venue_id"], first_sheet["id"])
        assert stored["status"] == "BUILDING"
        assert stored["cover_cycles"] == 0
        assert float(stored["dehumidification_lph_applied"]) == pytest.approx(
            120, abs=0.005
        ), "the refused install did not overwrite the running sheet"
        assert read_venue(arena["venue_id"])["ice_deck_status"] == "BUILDING"


class TestTheCrewHeadcountCap:
    def test_one_head_above_the_cap_is_refused_while_the_cap_itself_plans_a_turnaround(
        self, api
    ):
        """PRD §3.7: "Then `crew_headcount` must not exceed the arena's `crew_headcount_cap`,
        otherwise `ERR_CREW_CAP_EXCEEDED`."
        PRD §3.7: "The **crew-productivity factor** is the order's `crew_headcount` divided by the
        incoming configuration's `crew_size_required`, then clamped to lie between 0.5 and 2.0: a
        factor computed below 0.5 is raised to 0.5, and one computed above 2.0 is lowered to 2.0."
        PRD §3.7: "The raw minute figure is divided by the factor and the quotient is rounded **up**
        to a whole minute; this is the first ceiling."
        PRD §3.7: "When and only when `overnight_shift` is true, that already-ceiled figure is then
        multiplied by 1.15 to reflect the overnight slowdown and the product is rounded **up** to a
        whole minute again; this is the second ceiling."
        PRD §3.7: "Then the window must be long enough for the frozen plan, otherwise
        `ERR_TURNAROUND_WINDOW_INSUFFICIENT`."

        Design: Corner/validations/crew_headcount_one_above_the_venue_cap_is_rejected_while_the_cap_itself_is_accepted
        """
        arena = setup_arena(clock=CLOCK_STARTUP_UTC)
        setup_ice_to_concert_bookings(arena, confirm_incoming=True)
        assert read_venue(arena["venue_id"])["crew_headcount_cap"] == 60
        version_before = venue_version(arena["venue_id"])
        request = {
            "from_booking_id": arena["from_booking"]["id"],
            "to_booking_id": arena["to_booking"]["id"],
            "expected_venue_version": version_before,
        }

        refused = api.create_changeover_order(
            dict(request, crew_headcount=61), SUPERVISOR
        )
        validate_error(refused, ApiErrorId.ERR_CREW_CAP_EXCEEDED.value, 422)
        assert venue_version(arena["venue_id"]) == version_before

        order = validate_success(
            api.create_changeover_order(dict(request, crew_headcount=60), SUPERVISOR),
            201,
        )
        assert order["crew_headcount"] == 60
        assert order["planned_turnaround_minutes"] == 472, (
            "six hundred and fifteen raw minutes at a factor of one and a half, then "
            "the overnight slowdown"
        )
        assert order["window_minutes"] == 735

        _rows, meta = validate_paginated(
            api.list_changeover_orders(SUPERVISOR, {"venue_id": arena["venue_id"]})
        )
        assert meta["total_count"] == 1


class TestTheSeasonalHoldQuota:
    def test_a_one_hold_grant_is_spent_by_the_first_hold(self, api):
        """PRD §3.3: "It requires the booking to be `DRAFT` — any other state is
        `ERR_INVALID_BOOKING_STATE` — and, for an anchor booking, that the tenant's
        `holds_consumed` is strictly below its `guaranteed_holds_per_season`, otherwise
        `ERR_TENANT_HOLD_QUOTA_EXCEEDED`."
        PRD §3.2: "`holds_consumed` counts the tenant's bookings that are currently `HELD`,
        `CHALLENGED` or `CONFIRMED`, and is the figure measured against
        `guaranteed_holds_per_season` when a new hold is placed."
        PRD §3.3: "A fresh draft has `status` reading `DRAFT`; `hold_tier`, `hold_placed_at`,
        `hold_expires_at`, `release_reason` and `displaced_by_booking_id` all unset; and
        `displacement_penalty_cents` at 0."
        PRD §2.11: "`open_hold_count` is the number of bookings on the arena whose `status` is
        either `HELD` or `CHALLENGED`."

        Design: Corner/validations/tenant_hold_quota_is_exhausted_and_the_second_hold_is_rejected
        """
        arena = setup_arena(profiles=("ICE",), clock=CLOCK_STARTUP_UTC)
        venue_id = arena["venue_id"]
        tenant = register_tenant(venue_id, "Lakeside Hockey Club", "TIER_2", 1)
        tenant_headers = make_anchor_tenant_rep_headers(tenant["id"])

        drafts = [
            draft_booking(
                venue_id, arena["profiles"]["ICE"]["id"], f"Anchor game Sep {day}",
                f"2026-09-{day}T00:00:00Z", f"2026-09-{day}T03:00:00Z",
                expected_attendance=15_000, rigging_load_kg=3_000,
                tenant_id=tenant["id"],
            )
            for day in ("10", "11")
        ]
        first = place_hold(drafts[0]["id"], tenant_headers)
        assert first["hold_expires_at"] == "2026-08-08T00:00:00.000Z"

        response = api.hold_event_booking(drafts[1]["id"], tenant_headers)
        validate_error(
            response, ApiErrorId.ERR_TENANT_HOLD_QUOTA_EXCEEDED.value, 422
        )

        assert read_tenant(venue_id, tenant["id"])["holds_consumed"] == 1
        refused_booking = read_booking(drafts[1]["id"])
        assert refused_booking["status"] == "DRAFT"
        assert refused_booking["hold_placed_at"] is None
        assert refused_booking["hold_expires_at"] is None
        assert read_venue(venue_id)["open_hold_count"] == 1
