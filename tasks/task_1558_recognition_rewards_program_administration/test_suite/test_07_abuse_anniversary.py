"""Abuse-flag adjudication cascades, employee suspension/reinstatement, and
service-anniversary scan behavior."""
from test_helpers import (
    ApiErrorId,
    create_abuse_flag_payload,
    create_employee,
    create_redemption_order_payload,
    get_success_data,
    make_employee_headers,
    setup_catalog,
    setup_employee_with_grant,
    setup_program_with_budget,
    submit_and_approve_nomination,
    suspend_employee,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestAbuseConfirmCascade:
    def test_confirm_suspends_revokes_cancels_and_demotes(
        self, api, hr_admin_headers, finance_admin_headers
    ):
        """PRD §3.8: "First, every one of the employee's redemption orders
        still in `PENDING_SUBMISSION` is cancelled with a full `REFUND` of its
        held points and its inventory restored. Second, every `ACTIVE` award
        of the employee is revoked in `granted_at` ascending order, ties
        broken by `created_at` ascending, each revocation firing its own
        clawback side effects per §3.4 — the `CLAWBACK` ledger entries
        reference the flag through `reference_type` `ABUSE_FLAG`, the
        employee's `available_points` may go negative, and the originating
        budgets release committed points when not `CLOSED`. Third, the
        employee's `recognition_tier` is recomputed against the reduced
        `lifetime_granted_points`."

        Design: Difficulty/transitive_cascade/abuse_confirm_suspension_clawback_chain
        """
        ctx = setup_program_with_budget(allocated_points=100000)
        program_id = ctx["program"]["id"]
        employee, manager = ctx["employee"], ctx["manager"]
        _, award1 = submit_and_approve_nomination(
            program_id, employee["id"], manager, 2000,
            type="MANAGER", reason_code="TEAMWORK", idempotency_key="tc2-n1",
        )
        # Pin a strict grant order for the cascade's granted_at-asc walk.
        get_success_data(api.set_clock("2026-08-01T01:00:00Z", hr_admin_headers))
        _, award2 = submit_and_approve_nomination(
            program_id, employee["id"], manager, 500,
            type="MANAGER", reason_code="INNOVATION", idempotency_key="tc2-n2",
        )
        _, item = setup_catalog(item_overrides={
            "sku": "MUG", "name": "Mug", "point_cost": 500, "cash_value_cents": 2500,
        })
        order = validate_success(api.create_redemption_order(
            create_redemption_order_payload(item["id"], idempotency_key="tc2-r1"),
            make_employee_headers(employee["id"]),
        ), 201)

        flag = validate_success(api.create_abuse_flag(
            create_abuse_flag_payload(employee["id"], program_id,
                                      details={"note": "audit hit"}),
            hr_admin_headers,
        ), 201)
        get_success_data(api.confirm_abuse_flag(flag["id"], hr_admin_headers))

        employee_after = validate_success(
            api.get_employee(employee["id"], hr_admin_headers), 200
        )
        assert employee_after["program_status"] == "SUSPENDED"
        assert employee_after["available_points"] == 0
        assert employee_after["held_points"] == 0
        assert employee_after["recognition_tier"] == "BRONZE"

        a1 = validate_success(api.get_award(award1, hr_admin_headers), 200)
        a2 = validate_success(api.get_award(award2, hr_admin_headers), 200)
        assert a1["status"] == "REVOKED"
        assert a2["status"] == "REVOKED"
        assert a1["revoked_by_flag_id"] == flag["id"]

        order_after = validate_success(
            api.get_redemption_order(order["id"], hr_admin_headers), 200
        )
        assert order_after["fulfillment_status"] == "CANCELLED"
        assert order_after["escrow_status"] == "REFUNDED"

        budget = validate_success(
            api.get_budget(ctx["budget"]["id"], finance_admin_headers), 200
        )
        assert budget["committed_points"] == 0

    def test_confirm_writes_clawbacks_in_grant_order_and_one_refund(
        self, api, hr_admin_headers
    ):
        """PRD §3.8: "every `ACTIVE` award of the employee is revoked in
        `granted_at` ascending order, ties broken by `created_at` ascending,
        each revocation firing its own clawback side effects per §3.4 — the
        `CLAWBACK` ledger entries reference the flag through `reference_type`
        `ABUSE_FLAG`".
        PRD §2.9: "An employee's ledger is readable as a chronological list,
        filterable by `entry_type`."

        Design: Difficulty/transitive_cascade/abuse_confirm_suspension_clawback_chain
        """
        ctx = setup_program_with_budget(allocated_points=100000)
        program_id = ctx["program"]["id"]
        employee, manager = ctx["employee"], ctx["manager"]
        submit_and_approve_nomination(
            program_id, employee["id"], manager, 2000,
            type="MANAGER", reason_code="TEAMWORK", idempotency_key="tc2b-n1",
        )
        get_success_data(api.set_clock("2026-08-01T01:00:00Z", hr_admin_headers))
        submit_and_approve_nomination(
            program_id, employee["id"], manager, 500,
            type="MANAGER", reason_code="INNOVATION", idempotency_key="tc2b-n2",
        )
        _, item = setup_catalog(item_overrides={
            "sku": "MUG2", "name": "Mug", "point_cost": 500, "cash_value_cents": 2500,
        })
        validate_success(api.create_redemption_order(
            create_redemption_order_payload(item["id"], idempotency_key="tc2b-r1"),
            make_employee_headers(employee["id"]),
        ), 201)

        flag = validate_success(api.create_abuse_flag(
            create_abuse_flag_payload(employee["id"], program_id), hr_admin_headers,
        ), 201)
        get_success_data(api.confirm_abuse_flag(flag["id"], hr_admin_headers))

        clawbacks, _ = validate_paginated(api.list_ledger_entries(
            employee["id"], hr_admin_headers, params={"entry_type": "CLAWBACK"},
        ))
        assert [entry["points"] for entry in clawbacks] == [-2000, -500]
        assert all(entry["reference_type"] == "ABUSE_FLAG" for entry in clawbacks)
        assert all(entry["reference_id"] == flag["id"] for entry in clawbacks)

        refunds, _ = validate_paginated(api.list_ledger_entries(
            employee["id"], hr_admin_headers, params={"entry_type": "REFUND"},
        ))
        assert len(refunds) == 1
        assert refunds[0]["points"] == 500


class TestAbuseFlagTerminalStates:
    def test_dismissed_flag_rejects_confirm_and_leaves_employee_eligible(
        self, api, hr_admin_headers
    ):
        """PRD §3.8: "Reviewing moves a flag from `OPEN` to `UNDER_REVIEW`;
        anything else is `ERR_INVALID_STATE_TRANSITION`. Confirming works from
        either `OPEN` or `UNDER_REVIEW` and lands the flag in `CONFIRMED`;
        disclosing the same states, dismissing lands it in `DISMISSED`. Both
        decisions stamp `resolved_by` with the acting administrator's
        identifier and increment the flag's `version`, and both `CONFIRMED`
        and `DISMISSED` are terminal."

        Design: Corner/state_machines/dismissed_flag_terminal_lockdown
        """
        ctx = setup_program_with_budget(
            program_overrides={"max_points_per_nomination": 1000},
            allocated_points=10000, num_extra_employees=0,
        )
        employee = ctx["employee"]
        flag = validate_success(api.create_abuse_flag(
            create_abuse_flag_payload(employee["id"], ctx["program"]["id"],
                                      details={"note": "x"}),
            hr_admin_headers,
        ), 201)
        get_success_data(api.dismiss_abuse_flag(flag["id"], hr_admin_headers))

        res = api.confirm_abuse_flag(flag["id"], hr_admin_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

        employee_after = validate_success(
            api.get_employee(employee["id"], hr_admin_headers), 200
        )
        assert employee_after["program_status"] == "ELIGIBLE"


class TestSuspensionGatesRedemption:
    def test_redemption_blocked_while_suspended_allowed_after_reinstate(
        self, api, hr_admin_headers
    ):
        """PRD §3.8: "a `SUSPENDED` employee cannot nominate or redeem
        (`ERR_EMPLOYEE_SUSPENDED`), and suspension never restores the revoked
        awards."
        PRD §3.8: "An `HRAdmin` may reinstate an employee only from
        `SUSPENDED`, and only while no abuse flag for that employee remains in
        `OPEN` or `UNDER_REVIEW`; either violation is `ERR_INVALID_STATE_TRANSITION`."

        Design: Difficulty/cross_entity_state_dependency/redemption_gated_by_employee_suspension
        """
        ctx = setup_employee_with_grant(5000)
        program_id = ctx["program"]["id"]
        employee = ctx["employee"]
        _, item = setup_catalog()
        flag = validate_success(api.create_abuse_flag(
            create_abuse_flag_payload(employee["id"], program_id,
                                      details={"note": "audit"}),
            hr_admin_headers,
        ), 201)
        get_success_data(api.confirm_abuse_flag(flag["id"], hr_admin_headers))

        # Suspended: redemption refused even though a balance check would also
        # fail (suspension is stage 8, points balance stage 17).
        res = api.create_redemption_order(
            create_redemption_order_payload(item["id"], idempotency_key="ce2-r1"),
            make_employee_headers(employee["id"]),
        )
        validate_error(res, ApiErrorId.ERR_EMPLOYEE_SUSPENDED)

        # The confirmed flag is resolved, so reinstate is unblocked.
        get_success_data(api.reinstate_employee(employee["id"], hr_admin_headers))
        validate_success(api.create_points_adjustment(
            employee["id"],
            {"program_id": program_id, "points": 1000,
             "reason": "restore after investigation"},
            hr_admin_headers,
        ), 201)

        order = validate_success(api.create_redemption_order(
            create_redemption_order_payload(item["id"], idempotency_key="ce2-r2"),
            make_employee_headers(employee["id"]),
        ), 201)
        assert order["fulfillment_status"] == "PENDING_SUBMISSION"

        refreshed = validate_success(api.get_employee(employee["id"], hr_admin_headers), 200)
        assert refreshed["available_points"] == 900
        assert refreshed["program_status"] == "ELIGIBLE"

    def test_reinstate_rejected_while_flag_open_and_dismiss_of_confirmed_fails(
        self, api, hr_admin_headers
    ):
        """PRD §3.8: "An `HRAdmin` may reinstate an employee only from
        `SUSPENDED`, and only while no abuse flag for that employee remains in
        `OPEN` or `UNDER_REVIEW`; either violation is
        `ERR_INVALID_STATE_TRANSITION`."
        PRD §3.8: "both `CONFIRMED` and `DISMISSED` are terminal."

        Design: Difficulty/cross_entity_state_dependency/redemption_gated_by_employee_suspension
        """
        ctx = setup_program_with_budget(allocated_points=100000)
        program_id = ctx["program"]["id"]
        employee = ctx["employee"]

        # An OPEN flag blocks the (not-yet-suspended) reinstate path.
        open_flag = validate_success(api.create_abuse_flag(
            create_abuse_flag_payload(employee["id"], program_id), hr_admin_headers,
        ), 201)
        early = api.reinstate_employee(employee["id"], hr_admin_headers)
        validate_error(early, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

        get_success_data(api.confirm_abuse_flag(open_flag["id"], hr_admin_headers))
        # Confirming is terminal: dismissing a CONFIRMED flag fails.
        res = api.dismiss_abuse_flag(open_flag["id"], hr_admin_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

        # With no OPEN/UNDER_REVIEW flag left, reinstate succeeds.
        reinstated = validate_success(
            api.reinstate_employee(employee["id"], hr_admin_headers), 200
        )
        assert reinstated["program_status"] == "ELIGIBLE"


class TestAnniversaryScan:
    def _program_with_milestones(self, milestones):
        return setup_program_with_budget(
            program_overrides={"anniversary_milestones": milestones},
            allocated_points=10000,
        )

    def test_milestone_processed_once_then_duplicate_skipped(
        self, api, hr_admin_headers, finance_admin_headers
    ):
        """PRD §3.4: "Because duplicates resolve to `SKIPPED_DUPLICATE`, a
        scan is idempotent per employee and milestone".
        PRD §3.4: "otherwise it records `PROCESSED`, creating an `Award` with
        `source` `ANNIVERSARY` and the milestone's points, writing a
        `GRANT_ANNIVERSARY` ledger entry, raising the budget's
        `committed_points` by the milestone points, and recomputing the
        employee's tier."

        Design: Corner/calculations/anniversary_scan_milestone_and_duplicate
        """
        get_success_data(api.set_clock("2026-08-20T00:00:00Z", hr_admin_headers))
        ctx = self._program_with_milestones([{"years": 5, "points": 500}])
        program_id = ctx["program"]["id"]
        employee = ctx["employee"]  # hired 2021-06-15 by default; re-register below
        # Register the veteran whose (month, day) matches the scan date.
        veteran = create_employee(ctx["dept"]["id"], employee_ref="VET-5",
                                  full_name="Veteran", hire_date="2021-08-20")

        first = validate_success(api.run_anniversary_scan(program_id, hr_admin_headers), 200)
        mine = [e for e in first if e["employee_id"] == veteran["id"]]
        assert len(mine) == 1
        assert mine[0]["status"] == "PROCESSED"
        assert mine[0]["award_id"]

        second = validate_success(api.run_anniversary_scan(program_id, hr_admin_headers), 200)
        mine2 = [e for e in second if e["employee_id"] == veteran["id"]]
        assert len(mine2) == 1
        assert mine2[0]["status"] == "SKIPPED_DUPLICATE"

        refreshed = validate_success(api.get_employee(veteran["id"], hr_admin_headers), 200)
        assert refreshed["available_points"] == 500
        budget = validate_success(
            api.get_budget(ctx["budget"]["id"], finance_admin_headers), 200
        )
        assert budget["committed_points"] == 500

        events, meta = validate_paginated(api.list_anniversary_events(
            hr_admin_headers,
            params={"program_id": program_id, "employee_id": veteran["id"]},
        ))
        assert meta["total_count"] == 2

    def test_leap_day_hire_observed_on_feb_28_in_non_leap_year(
        self, api, hr_admin_headers
    ):
        """PRD §3.4: "The scan considers every employee whose department holds
        any budget in the program, any window and any posture, and matches
        anniversaries by the month and day of `hire_date` against the scan
        date, with February 29 hires observed on February 28 in non-leap
        years; the service years reached are the scan year minus the hire
        year."

        Design: Corner/calculations/anniversary_leap_day_observed_feb28
        """
        # The logical clock boots at 2026-08-01 and never moves backward, so
        # the next non-leap-year February observance of a 2024-02-29 hire is
        # 2027-02-28, when the service years reached are 2027 - 2024 = 3.
        ctx = setup_program_with_budget(
            program_overrides={"anniversary_milestones": [{"years": 3, "points": 300}]},
            allocated_points=10000,
            budget_overrides={"period_start_date": "2026-01-01",
                              "period_end_date": "2028-01-01"},
        )
        program_id = ctx["program"]["id"]
        leapling = create_employee(ctx["dept"]["id"], employee_ref="LEAP-1",
                                   full_name="Leapling", hire_date="2024-02-29")

        get_success_data(api.set_clock("2027-02-27T00:00:00Z", hr_admin_headers))
        day_before = validate_success(
            api.run_anniversary_scan(program_id, hr_admin_headers), 200
        )
        assert [e for e in day_before if e["employee_id"] == leapling["id"]] == []

        get_success_data(api.set_clock("2027-02-28T00:00:00Z", hr_admin_headers))
        on_day = validate_success(
            api.run_anniversary_scan(program_id, hr_admin_headers), 200
        )
        mine = [e for e in on_day if e["employee_id"] == leapling["id"]]
        assert len(mine) == 1
        assert mine[0]["status"] == "PROCESSED"
        assert mine[0]["milestone_years"] == 3
        refreshed = validate_success(api.get_employee(leapling["id"], hr_admin_headers), 200)
        assert refreshed["available_points"] == 300

    def test_suspended_employee_anniversary_skipped_ineligible(
        self, api, hr_admin_headers
    ):
        """PRD §3.4: "otherwise, if the employee is `SUSPENDED`, it records
        `SKIPPED_INELIGIBLE`".

        Design: Corner/cross_cutting_layers/anniversary_skipped_for_suspended_employee
        """
        ctx = setup_program_with_budget(
            program_overrides={"anniversary_milestones": [{"years": 5, "points": 500}]},
            allocated_points=10000,
        )
        program_id = ctx["program"]["id"]
        veteran = create_employee(ctx["dept"]["id"], employee_ref="VET-S",
                                  full_name="Vet", hire_date="2021-08-20")
        suspend_employee(veteran["id"], program_id)
        get_success_data(api.set_clock("2026-08-20T00:00:00Z", hr_admin_headers))

        events = validate_success(api.run_anniversary_scan(program_id, hr_admin_headers), 200)
        mine = [e for e in events if e["employee_id"] == veteran["id"]]
        assert len(mine) == 1
        assert mine[0]["status"] == "SKIPPED_INELIGIBLE"

        refreshed = validate_success(api.get_employee(veteran["id"], hr_admin_headers), 200)
        assert refreshed["available_points"] == 0
        _, meta = validate_paginated(api.list_awards(
            hr_admin_headers,
            params={"employee_id": veteran["id"], "source": "ANNIVERSARY"},
        ))
        assert meta["total_count"] == 0
