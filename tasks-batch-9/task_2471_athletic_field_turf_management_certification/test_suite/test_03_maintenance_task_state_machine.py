"""The maintenance-task lifecycle: initial state, refused transitions, side effects."""

from test_helpers import (
    ApiErrorId,
    assert_instant_equals,
    assert_maintenance_task,
    assert_two_decimals,
    assert_usage_ledger_entry,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestMaintenanceTaskInitialState:
    def test_task_is_created_in_the_scheduled_initial_state(self, client, roster):
        """Scheduling work commits the department to nothing yet.

        "`status` initialises to `SCHEDULED`, with `started_at_utc`,
        `completed_at_utc` and `cancellation_reason` all null."

        "If the field has no `PLAY_WEAR` entry at all, `rest_debt_hours` is 0.00
        and there is nothing further to do."

        "On creation, `committed_amount_cents` is 0, `available_amount_cents`
        equals `total_authorized_amount_cents`, `status` is `OPEN`, and
        `lock_threshold_amount_cents` is set to ninety percent of the
        authorisation"

        "A new plan starts with `funding_status` `DRAFT`. Its second,
        **independent** axis, `disposal_status`, starts at `PENDING` when the
        *existing* `Field.surface_type` is `SYNTHETIC_TURF` — synthetic infill and
        carpet must be manifested to a licensed receiver — and at
        `NOT_APPLICABLE` otherwise."

        Design: Corner/state_machines/maintenance_task_is_created_in_the_scheduled_initial_state
        """
        field = fixtures.register_grass_practice_3(client, roster)
        task = fixtures.schedule_task(
            client,
            roster,
            field["id"],
            task_type="AERATION",
            scheduled_start_utc="2026-08-10T08:00:00Z",
            scheduled_end_utc="2026-08-10T10:00:00Z",
        )
        assert_maintenance_task(task)
        assert task["status"] == "SCHEDULED"
        assert task.get("started_at_utc") is None
        assert task.get("completed_at_utc") is None
        assert task.get("cancellation_reason") is None

        current = fixtures.read_field(client, roster, field["id"])
        assert_two_decimals(
            current["rest_debt_hours"], 0.00, "Field.rest_debt_hours"
        )

        budget = fixtures.authorize_budget(client, roster, fiscal_year=2027)
        assert budget["status"] == "OPEN"
        assert budget["committed_amount_cents"] == 0
        assert (
            budget["available_amount_cents"] == budget["total_authorized_amount_cents"]
        )

        plan = fixtures.draft_plan(
            client,
            roster,
            field["id"],
            budget["id"],
            current["version"],
            target_surface_type="NATURAL_GRASS",
            area_sq_ft=60000,
        )
        assert plan["funding_status"] == "DRAFT"
        # The existing surface is grass, which is not a waste stream.
        assert plan["disposal_status"] == "NOT_APPLICABLE"


class TestMaintenanceTaskRefusedTransitions:
    def test_complete_without_start_is_rejected(self, client, roster):
        """COMPLETE has exactly one legal source state.

        "`COMPLETE` is permitted only from `IN_PROGRESS` and takes the task
        `IN_PROGRESS → COMPLETED`; it requires a `completed_at_utc` in the body
        which must be at or after the task's `started_at_utc` and at or before the
        current logical instant."

        "Requesting an action the current status does not permit is refused with
        `ERR_TASK_NOT_TRANSITIONABLE`."

        Design: Corner/state_machines/maintenance_task_complete_without_start_is_rejected
        """
        field = fixtures.register_grass_practice_3(client, roster)
        task = fixtures.schedule_task(
            client,
            roster,
            field["id"],
            task_type="AERATION",
            scheduled_start_utc="2026-08-10T08:00:00Z",
            scheduled_end_utc="2026-08-10T10:00:00Z",
        )
        # Advancing the clock past the window rules out any complaint about a
        # completion instant that lies in the future.
        fixtures.set_clock(client, roster, "2026-08-10T10:00:00Z")

        validate_error(
            client.transition_maintenance_task(
                task["id"],
                factories.make_task_complete_payload("2026-08-10T10:00:00Z"),
                roster.agronomist_headers,
            ),
            ApiErrorId.TASK_NOT_TRANSITIONABLE,
            409,
        )

        unchanged = fixtures.read_task(client, roster, task["id"])
        assert unchanged["status"] == "SCHEDULED"
        assert unchanged.get("completed_at_utc") is None

        _entries, meta = validate_paginated(
            client.list_usage_ledger_entries(
                roster.agronomist_headers,
                params={"limit": 100, "field_id": field["id"]},
            )
        )
        assert meta["total_count"] == 0

        # The refusal was about the source state, not about the action itself.
        fixtures.start_task(client, roster, task["id"])
        completed = fixtures.complete_task(
            client, roster, task["id"], "2026-08-10T10:00:00Z"
        )
        assert completed["status"] == "COMPLETED"

    def test_cancel_after_completion_is_rejected(self, client, roster):
        """COMPLETED is terminal and admits no further action.

        "`CANCEL` is permitted from either `SCHEDULED` or `IN_PROGRESS`, takes the
        task to `CANCELLED`, and requires a `cancellation_reason` in the body.
        Requesting an action the current status does not permit is refused with
        `ERR_TASK_NOT_TRANSITIONABLE`."

        "`START` is permitted only from `SCHEDULED` and takes the task
        `SCHEDULED → IN_PROGRESS`, stamping `started_at_utc` from the logical
        clock"

        Design: Corner/state_machines/maintenance_task_cancel_after_completion_is_rejected
        """
        field = fixtures.register_grass_practice_3(client, roster)
        task = fixtures.schedule_task(
            client,
            roster,
            field["id"],
            task_type="AERATION",
            scheduled_start_utc="2026-08-10T08:00:00Z",
            scheduled_end_utc="2026-08-10T10:00:00Z",
        )
        fixtures.set_clock(client, roster, "2026-08-10T10:00:00Z")
        fixtures.start_task(client, roster, task["id"])
        fixtures.complete_task(client, roster, task["id"], "2026-08-10T10:00:00Z")

        validate_error(
            client.transition_maintenance_task(
                task["id"],
                factories.make_task_cancel_payload("WEATHER"),
                roster.agronomist_headers,
            ),
            ApiErrorId.TASK_NOT_TRANSITIONABLE,
            409,
        )

        after = fixtures.read_task(client, roster, task["id"])
        assert after["status"] == "COMPLETED"
        assert_instant_equals(
            after["completed_at_utc"],
            "2026-08-10T10:00:00Z",
            "MaintenanceTask.completed_at_utc",
        )
        assert after.get("cancellation_reason") is None

        validate_error(
            client.transition_maintenance_task(
                task["id"],
                factories.make_task_complete_payload("2026-08-10T10:00:00Z"),
                roster.agronomist_headers,
            ),
            ApiErrorId.TASK_NOT_TRANSITIONABLE,
            409,
        )
        validate_error(
            client.transition_maintenance_task(
                task["id"],
                factories.make_task_start_payload(),
                roster.agronomist_headers,
            ),
            ApiErrorId.TASK_NOT_TRANSITIONABLE,
            409,
        )

        field_after = fixtures.read_field(client, roster, field["id"])
        assert_two_decimals(
            field_after["rest_debt_hours"], 0.00, "Field.rest_debt_hours"
        )


class TestMaintenanceTaskCompletionSideEffect:
    def test_completion_credits_outstanding_rest_debt_as_ledger_side_effect(
        self, client, roster
    ):
        """The credit a task delivers is the credit the outstanding window admits.

        "Against that, credit is taken: the sum of `recovery_credit_hours` over
        the field's maintenance tasks whose `status` is `COMPLETED` and whose
        `completed_at_utc` is at or after the governing entry's
        `effective_at_utc`, but capped so it can never exceed the outstanding
        obligation itself."

        "Otherwise the outstanding obligation is the number of hours from the
        current logical instant to that governing entry's `rest_window_end_utc`,
        floored at 0.00 so an elapsed window contributes nothing, rounded half up
        to two decimal places."

        "if the credit that recomputation is actually able to absorb is strictly
        greater than 0.00 a ledger entry with `entry_type` `RECOVERY_CREDIT` is
        appended carrying `wear_units_delta` of 0.00 and `rest_credit_hours` equal
        to that absorbed credit"

        "The posture is then recomputed — a field whose only reason for being
        `RESTRICTED` was rest debt can go `RESTRICTED → OPEN` here"

        "a field that is `OPEN` or `RESTRICTED` but will not take the requested
        intensity — that is, a `RESTRICTED` field asked for a `GAME` or a
        `TOURNAMENT` — is refused with `ERR_FIELD_RESTRICTED_FOR_ACTIVITY`."

        Design: Corner/state_machines/task_completion_credits_outstanding_rest_debt_as_ledger_side_effect
        """
        field = fixtures.register_grass_practice_3(client, roster)
        booking = fixtures.request_booking(
            client,
            roster,
            field["id"],
            activity_type="GAME",
            window_start_utc="2026-08-02T19:00:00Z",
            window_end_utc="2026-08-02T20:30:00Z",
            expected_participant_count=40,
        )
        fixtures.confirm_booking(client, roster, booking["id"])
        # The task window sits clear of the booking window, so the
        # task-versus-booking guard cannot fire.
        task = fixtures.schedule_task(
            client,
            roster,
            field["id"],
            task_type="AERATION",
            scheduled_start_utc="2026-08-02T21:00:00Z",
            scheduled_end_utc="2026-08-02T22:00:00Z",
        )
        assert_two_decimals(
            task["recovery_credit_hours"], 12.00, "AERATION recovery_credit_hours"
        )

        fixtures.set_clock(client, roster, "2026-08-02T20:30:00Z")
        fixtures.close_out_booking(
            client,
            roster,
            booking["id"],
            outcome="PLAYED",
            actual_duration_hours=1.50,
            actual_participant_count=40,
            weather_condition="WET",
        )
        restricted = fixtures.read_field(client, roster, field["id"])
        assert restricted["play_status"] == "RESTRICTED"
        assert_two_decimals(
            restricted["rest_debt_hours"], 3.83, "Field.rest_debt_hours"
        )

        fixtures.set_clock(client, roster, "2026-08-02T22:00:00Z")
        # While the rest window is still running the surface takes no game.
        validate_error(
            client.create_usage_booking(
                factories.make_usage_booking_payload(
                    field_id=field["id"],
                    requested_by_staff_member_id=roster.id_of("coordinator"),
                    activity_type="GAME",
                    window_start_utc="2026-08-05T19:00:00Z",
                    window_end_utc="2026-08-05T21:00:00Z",
                    expected_participant_count=40,
                ),
                roster.coordinator_headers,
            ),
            ApiErrorId.FIELD_RESTRICTED_FOR_ACTIVITY,
            422,
        )

        fixtures.start_task(client, roster, task["id"])
        completed = fixtures.complete_task(
            client, roster, task["id"], "2026-08-02T22:00:00Z"
        )
        assert completed["status"] == "COMPLETED"
        assert_instant_equals(
            completed["completed_at_utc"],
            "2026-08-02T22:00:00Z",
            "MaintenanceTask.completed_at_utc",
        )
        assert_two_decimals(
            completed["recovery_credit_hours"],
            12.00,
            "the nominal AERATION credit is untouched by capping",
        )

        entries, meta = validate_paginated(
            client.list_usage_ledger_entries(
                roster.agronomist_headers,
                params={"limit": 100, "maintenance_task_id": task["id"]},
            )
        )
        assert meta["total_count"] == 1
        credit = entries[0]
        assert_usage_ledger_entry(credit)
        assert credit["entry_type"] == "RECOVERY_CREDIT"
        # The governing window ends at 2026-08-03T00:19:48Z, so at 22:00 the
        # outstanding obligation is 2h 19m 48s, and the nominal 12.00 is capped
        # down to that figure rather than delivered in full.
        assert_two_decimals(
            credit["rest_credit_hours"], 2.33, "RECOVERY_CREDIT rest_credit_hours"
        )
        assert_two_decimals(credit["wear_units_delta"], 0.00, "wear_units_delta")
        assert_two_decimals(
            credit["running_balance_after"], 3.65, "running_balance_after"
        )

        after = fixtures.read_field(client, roster, field["id"])
        assert_two_decimals(after["rest_debt_hours"], 0.00, "Field.rest_debt_hours")
        assert after["play_status"] == "OPEN"
        # A recovery credit never repays wear.
        assert_two_decimals(
            after["cumulative_wear_units"], 3.65, "Field.cumulative_wear_units"
        )

        allowed = validate_success(
            client.create_usage_booking(
                factories.make_usage_booking_payload(
                    field_id=field["id"],
                    requested_by_staff_member_id=roster.id_of("coordinator"),
                    activity_type="GAME",
                    window_start_utc="2026-08-05T19:00:00Z",
                    window_end_utc="2026-08-05T21:00:00Z",
                    expected_participant_count=40,
                ),
                roster.coordinator_headers,
            ),
            201,
        )
        assert allowed["status"] == "SCHEDULED"
