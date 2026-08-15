"""Coaching assignments: lifecycle, overdue sweep, escalation, OCC-guarded
create-with-supersede, and the risk-score completion credit."""
from test_helpers import (
    ApiErrorId,
    assert_timestamp_at,
    create_coaching_payload,
    get_coaching,
    get_driver,
    make_carrier,
    make_carrier_with_driver,
    make_category,
    make_coaching,
    make_driver,
    make_inspection,
    make_violation,
    setup_overdue_coaching_case,
    validate_error,
    validate_success,
)


class TestCoachingStateMachine:
    def test_coaching_overdue_sweep_then_escalate_suspends_driver(
        self, api, manager_headers
    ):
        """PRD §3.5: "When a measurement cycle finds an assignment in
        `ASSIGNED` or `IN_PROGRESS` whose `due_date` lies before the current
        logical clock, it marks the assignment `OVERDUE`." and "escalation
        requires the assignment to be `OVERDUE` (`ERR_COACHING_NOT_OVERDUE` from
        any other state) and the driver still `ACTIVE` (`ERR_DRIVER_NOT_ACTIVE`),
        and it moves the assignment to `ESCALATED`, suspends the driver
        (`ACTIVE` → `SUSPENDED`), adds one to the driver's `coaching_strikes`,
        and increments the driver's `version`."

        Design: Corner/state_machines/coaching_overdue_sweep_then_escalate_suspends_driver
        """
        env = setup_overdue_coaching_case()
        assert env["cycle"]["overdue_coaching_marked"] == 1
        assert get_coaching(env["coaching"]["id"])["status"] == "OVERDUE"

        escalated = validate_success(
            api.escalate_coaching(env["coaching"]["id"], manager_headers), 200
        )
        assert escalated["status"] == "ESCALATED"

        driver = get_driver(env["driver"]["id"])
        assert driver["employment_status"] == "SUSPENDED"
        assert driver["coaching_strikes"] == 1

    def test_coaching_complete_after_escalation_auto_reinstates(
        self, api, manager_headers
    ):
        """PRD §3.5: "Completion stamps `completed_at` with the clock,
        recomputes the driver's `risk_score` (the two-point completion credit
        described in §3.2), and, when the completed assignment was previously
        `ESCALATED`, re-evaluates the driver's suspension holds and
        automatically moves a `SUSPENDED` driver back to `ACTIVE` if and only if
        zero holds remain."

        Design: Corner/state_machines/coaching_complete_after_escalation_auto_reinstates
        """
        env = setup_overdue_coaching_case(coaching_type="PROBATION")
        validate_success(api.escalate_coaching(env["coaching"]["id"], manager_headers), 200)
        assert get_driver(env["driver"]["id"])["employment_status"] == "SUSPENDED"

        completed = validate_success(
            api.complete_coaching(
                env["coaching"]["id"],
                {"completion_note": "Course finished late"},
                manager_headers,
            ),
            200,
        )
        assert completed["status"] == "COMPLETED"
        assert_timestamp_at(completed["completed_at"], "2026-08-11T00:00:00")
        assert get_driver(env["driver"]["id"])["employment_status"] == "ACTIVE"

    def test_coaching_start_complete_twice_rejected(self, api, manager_headers):
        """PRD §3.5: "Starting work moves `ASSIGNED` → `IN_PROGRESS`.
        Completion, submitted with a `completion_note`, moves an assignment from
        `ASSIGNED`, `IN_PROGRESS`, `OVERDUE`, or `ESCALATED` to `COMPLETED`;
        either action attempted from an ineligible state — including the
        terminal states `COMPLETED`, `SUPERSEDED`, and `CANCELLED` — is rejected
        with `ERR_COACHING_NOT_OPEN`."

        Design: Corner/validations/coaching_start_complete_twice_rejected
        """
        carrier, driver = make_carrier_with_driver(
            carrier_overrides={"dot_number": "DOT-2324"}
        )
        coaching = make_coaching(
            driver["id"], coaching_type="VERBAL_WARNING", due_date="2026-12-01T00:00:00Z"
        )

        validate_success(api.start_coaching(coaching["id"], manager_headers), 200)
        start_again = api.start_coaching(coaching["id"], manager_headers)
        validate_error(start_again, ApiErrorId.ERR_COACHING_NOT_OPEN)

        validate_success(
            api.complete_coaching(coaching["id"], {"completion_note": "done"}, manager_headers),
            200,
        )
        complete_again = api.complete_coaching(
            coaching["id"], {"completion_note": "again"}, manager_headers
        )
        validate_error(complete_again, ApiErrorId.ERR_COACHING_NOT_OPEN)

    def test_coaching_escalate_before_overdue_rejected(self, api, manager_headers):
        """PRD §3.5: "escalation requires the assignment to be `OVERDUE`
        (`ERR_COACHING_NOT_OVERDUE` from any other state) and the driver still
        `ACTIVE` (`ERR_DRIVER_NOT_ACTIVE`)".

        Design: Corner/validations/coaching_escalate_before_overdue_rejected
        """
        carrier, driver = make_carrier_with_driver(
            carrier_overrides={"dot_number": "DOT-2325"}
        )
        coaching = make_coaching(
            driver["id"], coaching_type="PROBATION", due_date="2026-12-01T00:00:00Z"
        )
        assert coaching["status"] == "ASSIGNED"

        resp = api.escalate_coaching(coaching["id"], manager_headers)
        validate_error(resp, ApiErrorId.ERR_COACHING_NOT_OVERDUE)
        assert get_driver(driver["id"])["employment_status"] == "ACTIVE"


class TestCoachingOptimisticConcurrency:
    def test_occ_coaching_create_stale_driver_version(self, api, manager_headers):
        """PRD §2.7: "Creating a coaching assignment
        (`POST /safety/coaching-assignments`) requires
        `expected_driver_version`, carrying the client's last observed `version`
        of the coached driver." and "When the supplied value does not equal the
        parent entity's current `version` — because the driver or carrier has
        advanced through changes the client has not observed — the request is
        rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.5: "it legitimately supersedes an existing open assignment of the
        same driver and `coaching_type`: when one in `ASSIGNED`, `IN_PROGRESS`,
        `OVERDUE`, or `ESCALATED` exists, the prior assignment moves to
        `SUPERSEDED`" and "Creation increments the driver's `version`".

        Design: Corner/complexity_layers/occ_coaching_create_stale_driver_version
        """
        carrier, driver = make_carrier_with_driver(
            carrier_overrides={"dot_number": "DOT-2601"}
        )
        assert driver["version"] == 1

        first = validate_success(
            api.create_coaching(
                create_coaching_payload(
                    driver["id"], 1,
                    coaching_type="TRAINING_COURSE", due_date="2026-12-01T00:00:00Z",
                ),
                manager_headers,
            ),
            201,
        )
        assert get_driver(driver["id"])["version"] == 2

        stale = api.create_coaching(
            create_coaching_payload(
                driver["id"], 1,
                coaching_type="TRAINING_COURSE", due_date="2026-12-15T00:00:00Z",
            ),
            manager_headers,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        second = validate_success(
            api.create_coaching(
                create_coaching_payload(
                    driver["id"], 2,
                    coaching_type="TRAINING_COURSE", due_date="2026-12-15T00:00:00Z",
                ),
                manager_headers,
            ),
            201,
        )
        assert second["status"] == "ASSIGNED"
        assert get_coaching(first["id"])["status"] == "SUPERSEDED"


class TestRiskScoreCoachingCredit:
    def test_driver_risk_coaching_credit_and_floor(self, api, manager_headers):
        """PRD §3.2: "minus a coaching credit of two points for each coaching
        assignment the driver has `COMPLETED` whose `completed_at` falls within
        the trailing twenty-four months. The score is floored at zero — it never
        goes negative. The `risk_tier` derives from it: `LOW` below 10,
        `MEDIUM` from 10 through 19, and `HIGH` at 20 or above."

        Design: Corner/calculations/driver_risk_coaching_credit_and_floor
        """
        carrier = make_carrier(dot_number="DOT-2203")
        category = make_category(
            category_code="VEHICLE_MAINTENANCE", display_name="VM"
        )
        driver = make_driver(
            carrier["id"], cdl_number="CDL-2203", hire_date="2024-01-01T00:00:00Z"
        )
        inspection = make_inspection(
            carrier["id"], driver["id"], report_number="R-2203",
            inspection_level=2, state_code="IA",
        )
        # 3 severity x time-weight 3 = 9 points against the driver.
        make_violation(
            inspection["id"], category["id"], violation_code="396.3", severity_weight=3
        )
        assert get_driver(driver["id"])["risk_score"] == 9

        for round_no in range(1, 6):
            coaching = make_coaching(
                driver["id"], coaching_type="TRAINING_COURSE",
                due_date="2027-01-01T00:00:00Z",
            )
            validate_success(
                api.complete_coaching(
                    coaching["id"],
                    {"completion_note": f"done {round_no}"},
                    manager_headers,
                ),
                200,
            )
            after = get_driver(driver["id"])
            if round_no == 3:
                assert after["risk_score"] == 3, "9 - 3 x 2 completion credit"

        final = get_driver(driver["id"])
        assert final["risk_score"] == 0, "raw 9 - 10 = -1 is floored at zero"
        assert final["risk_tier"] == "LOW"
