"""Requests that break two rules at once, and which refusal must be returned."""

from test_helpers import (
    ApiErrorId,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)


def _grass_field_with_a_scheduled_practice(client, roster):
    """A field carrying one never-confirmed practice on the evening of 5 August."""
    field = fixtures.register_grass_main_1(client, roster)
    booking = fixtures.request_booking(
        client,
        roster,
        field["id"],
        activity_type="PRACTICE",
        window_start_utc="2026-08-05T19:00:00Z",
        window_end_utc="2026-08-05T21:00:00Z",
        expected_participant_count=30,
    )
    assert booking["status"] == "SCHEDULED"
    return field, booking


def _overlapping_request(roster, field_id):
    """A window that starts an hour into the existing one."""
    return factories.make_usage_booking_payload(
        field_id=field_id,
        requested_by_staff_member_id=roster.id_of("coordinator"),
        activity_type="PRACTICE",
        window_start_utc="2026-08-05T20:00:00Z",
        window_end_utc="2026-08-05T22:00:00Z",
        expected_participant_count=30,
    )


class TestPostureOutranksWindowConflict:
    def test_a_closed_field_reports_its_posture_not_the_live_window_clash(
        self, client, roster
    ):
        """Both rules are broken; the posture gate is the one that answers.

        "State preconditions on the target resource come next, then posture and
        safety gates, then referential business rules, then the two
        interval-conflict rules and the staff-capacity rule, and finally the fiscal
        and scoring thresholds — completeness, condition index, priority score and
        budget availability."

        "A field whose `play_status` is `CLOSED_ADMIN`, `CLOSED_UNSAFE` or
        `RETIRED` accepts no allocation and the request is refused with
        `ERR_FIELD_NOT_PLAYABLE`"

        "An administrative closure **does not cancel anything**. Bookings already
        sitting in `SCHEDULED` or `CONFIRMED` on the field are left exactly as they
        are; they simply cannot be created or confirmed while the closure is in
        force, and if the closure is lifted before their windows arrive they proceed
        normally."

        Design: Difficulty/priority_pair_validation_conflict/field_posture_outranks_booking_window_conflict_on_create
        """
        field, booking = _grass_field_with_a_scheduled_practice(client, roster)
        closed = fixtures.close_field_administratively(
            client, roster, field["id"], reason_code="IRRIGATION_MAIN_BREAK"
        )
        assert closed["play_status"] == "CLOSED_ADMIN"
        assert closed["admin_closure_reason_code"] == "IRRIGATION_MAIN_BREAK"

        # The closure left the earlier booking occupying its window, so the
        # requested 20:00-22:00 slot really does clash inside the changeover buffer.
        untouched = fixtures.read_booking(client, roster, booking["id"])
        assert untouched["status"] == "SCHEDULED"

        error = validate_error(
            client.create_usage_booking(
                _overlapping_request(roster, field["id"]), roster.coordinator_headers
            ),
            ApiErrorId.FIELD_NOT_PLAYABLE,
            422,
        )
        assert error["error_id"] != ApiErrorId.BOOKING_WINDOW_CONFLICT

        _items, meta = validate_paginated(
            client.list_usage_bookings(
                roster.coordinator_headers,
                params={"limit": 100, "field_id": field["id"]},
            )
        )
        assert meta["total_count"] == 1, "the refused request minted no row"

    def test_the_window_clash_surfaces_once_the_posture_gate_is_satisfied(
        self, client, roster
    ):
        """The lower-priority rule was real all along, and says so when reached.

        "Considering only bookings on the same field whose `status` is `SCHEDULED`
        or `CONFIRMED` — terminal-status bookings are excluded from the candidate
        set entirely — the requested window conflicts with an existing one when the
        requested `window_start_utc` falls strictly before the existing
        `window_end_utc` extended forward by thirty minutes **and** the existing
        `window_start_utc` falls strictly before the requested `window_end_utc`
        extended forward by thirty minutes."

        "A conflict is refused with `ERR_BOOKING_WINDOW_CONFLICT`."

        "The practical consequence is worth stating plainly: two back-to-back
        bookings with a gap of zero **do** conflict, because the trailing edge of
        the earlier one, widened by the buffer, still covers the leading edge of
        the later; a gap of exactly thirty minutes is accepted."

        Design: Difficulty/priority_pair_validation_conflict/field_posture_outranks_booking_window_conflict_on_create
        """
        field, _booking = _grass_field_with_a_scheduled_practice(client, roster)
        fixtures.close_field_administratively(client, roster, field["id"])
        reopened = fixtures.reopen_field_administratively(client, roster, field["id"])
        assert reopened["play_status"] == "OPEN"

        # Same request, same clash, no posture obstacle left in front of it.
        error = validate_error(
            client.create_usage_booking(
                _overlapping_request(roster, field["id"]), roster.coordinator_headers
            ),
            ApiErrorId.BOOKING_WINDOW_CONFLICT,
            409,
        )
        assert error["error_id"] != ApiErrorId.FIELD_NOT_PLAYABLE

        # Zero gap still collides once the buffer is applied to the trailing edge.
        validate_error(
            client.create_usage_booking(
                factories.make_usage_booking_payload(
                    field_id=field["id"],
                    requested_by_staff_member_id=roster.id_of("coordinator"),
                    activity_type="PRACTICE",
                    window_start_utc="2026-08-05T21:00:00Z",
                    window_end_utc="2026-08-05T22:00:00Z",
                    expected_participant_count=30,
                ),
                roster.coordinator_headers,
            ),
            ApiErrorId.BOOKING_WINDOW_CONFLICT,
            409,
        )

        # A gap of exactly thirty minutes is accepted.
        accepted = validate_success(
            client.create_usage_booking(
                factories.make_usage_booking_payload(
                    field_id=field["id"],
                    requested_by_staff_member_id=roster.id_of("coordinator"),
                    activity_type="PRACTICE",
                    window_start_utc="2026-08-05T21:30:00Z",
                    window_end_utc="2026-08-05T23:00:00Z",
                    expected_participant_count=30,
                ),
                roster.coordinator_headers,
            ),
            201,
        )
        assert accepted["status"] == "SCHEDULED"

        _items, meta = validate_paginated(
            client.list_usage_bookings(
                roster.coordinator_headers,
                params={"limit": 100, "field_id": field["id"]},
            )
        )
        assert meta["total_count"] == 2


class TestPlanStateOutranksBudgetInsufficiency:
    def _underfunded_draft_plan(self, client, full_roster):
        """A plan costing 5243000 against a budget authorised for only 1000000."""
        field = fixtures.register_synthetic_stadium_1(client, full_roster)
        budget = fixtures.authorize_budget(
            client, full_roster, total_authorized_amount_cents=1000000
        )
        plan = fixtures.draft_plan(
            client,
            full_roster,
            field["id"],
            budget["id"],
            field["version"],
            target_surface_type="SYNTHETIC_TURF",
            area_sq_ft=70000,
            priority_basis="CONDITION_RISK",
            planned_install_year=2028,
        )
        assert plan["plan_funding_amount_cents"] == 5243000
        assert budget["available_amount_cents"] == 1000000
        return budget, plan

    def test_a_draft_plan_reports_its_state_not_the_shortfall(
        self, client, full_roster
    ):
        """The money is nowhere near enough, and that is still not the answer.

        "`APPROVE` and `REJECT` both require `funding_status` to be `SUBMITTED` and
        are otherwise refused with `ERR_PLAN_NOT_SUBMITTED`."

        "`APPROVE` additionally requires the budget to be `OPEN`, refusing with
        `ERR_BUDGET_LOCKED`; then that `replacement_priority_score` is at least
        20.00, refusing with `ERR_PLAN_PRIORITY_BELOW_THRESHOLD`; then that
        `plan_funding_amount_cents` does not exceed the budget's
        `available_amount_cents`, refusing with `ERR_BUDGET_INSUFFICIENT`."

        "Within that final group the ordering is: certification completeness before
        certification condition index; plan priority score before budget
        availability."

        Design: Difficulty/priority_pair_validation_conflict/plan_state_check_outranks_budget_insufficiency_on_decide
        """
        budget, plan = self._underfunded_draft_plan(client, full_roster)
        assert plan["funding_status"] == "DRAFT"

        error = validate_error(
            client.decide_replacement_plan(
                plan["id"],
                factories.make_plan_decide_payload(
                    decision="APPROVE",
                    decided_by_staff_member_id=full_roster.id_of("director_two"),
                ),
                full_roster.headers_of("director_two"),
            ),
            ApiErrorId.PLAN_NOT_SUBMITTED,
            409,
        )
        assert error["error_id"] != ApiErrorId.BUDGET_INSUFFICIENT

        held = fixtures.read_plan(client, full_roster, plan["id"])
        assert held["funding_status"] == "DRAFT"
        assert held.get("decided_by_staff_member_id") is None
        assert held.get("decided_at_utc") is None

        after_budget = fixtures.read_budget(client, full_roster, budget["id"])
        assert after_budget["committed_amount_cents"] == 0
        assert after_budget["available_amount_cents"] == 1000000
        assert after_budget["status"] == "OPEN"

    def test_the_shortfall_surfaces_once_the_plan_is_actually_submitted(
        self, client, full_roster
    ):
        """With the state precondition met the fiscal gate is the next to fire.

        "then that `plan_funding_amount_cents` does not exceed the budget's
        `available_amount_cents`, refusing with `ERR_BUDGET_INSUFFICIENT`."

        "Submitting a plan records the `submitted_by_staff_member_id`, stamps
        `submitted_at_utc`, and takes the funding axis `DRAFT → SUBMITTED`."

        "`REJECT` takes the plan `SUBMITTED → REJECTED`, moves no capital at all
        and leaves the budget entirely untouched, decrements
        `Field.open_replacement_plan_count` by 1 and increments `Field.version` by
        1."

        Design: Difficulty/priority_pair_validation_conflict/plan_state_check_outranks_budget_insufficiency_on_decide
        """
        budget, plan = self._underfunded_draft_plan(client, full_roster)
        submitted = fixtures.submit_plan(client, full_roster, plan["id"])
        assert submitted["funding_status"] == "SUBMITTED"
        # The priority gate sits ahead of the fiscal one and this plan clears it.
        assert float(submitted["replacement_priority_score"]) >= 20.00

        error = validate_error(
            client.decide_replacement_plan(
                plan["id"],
                factories.make_plan_decide_payload(
                    decision="APPROVE",
                    decided_by_staff_member_id=full_roster.id_of("director_two"),
                ),
                full_roster.headers_of("director_two"),
            ),
            ApiErrorId.BUDGET_INSUFFICIENT,
            422,
        )
        assert error["error_id"] != ApiErrorId.PLAN_NOT_SUBMITTED

        still_submitted = fixtures.read_plan(client, full_roster, plan["id"])
        assert still_submitted["funding_status"] == "SUBMITTED"

        # Rejecting the same plan is permitted from `SUBMITTED` and costs nothing.
        rejected = fixtures.decide_plan(
            client, full_roster, plan["id"], decision="REJECT"
        )
        assert rejected["funding_status"] == "REJECTED"

        after_budget = fixtures.read_budget(client, full_roster, budget["id"])
        assert after_budget["committed_amount_cents"] == 0
        assert after_budget["available_amount_cents"] == 1000000
        assert after_budget["status"] == "OPEN"
