"""The RFI cycle: creation, routing, answers, reopens, due dates, OCC (PRD §2.9, §3.5)."""
from test_helpers import (
    ApiErrorId,
    add_reviewer,
    answer_rfi,
    assert_rfi,
    create_active_project,
    create_rfi,
    create_rfi_answer_payload,
    create_rfi_payload,
    current_project_version,
    make_reviewer_headers,
    route_rfi,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

PM = TEST_USERS["project_manager_headers"]
PE = TEST_USERS["project_engineer_headers"]


def _active_project_with_reviewer(api, **project_overrides):
    project = create_active_project("P", **project_overrides)
    reviewer = add_reviewer(project["id"], display_name="Arch One", discipline="ARCH")
    return project, reviewer


class TestRfiStateMachine:
    def test_close_rfi_in_open_state_rejected(self, api):
        """PRD §3.5: "Closing an RFI, also by a `ProjectEngineer`, requires `ANSWERED`
        (otherwise `ERR_RFI_INVALID_STATE`)"

        Design: Corner/state_machines/close_rfi_in_open_state_rejected
        """
        project, _reviewer = _active_project_with_reviewer(api)
        rfi = create_rfi(project["id"], subject="S", question_text="Q")
        assert rfi["status"] == "OPEN"

        resp = api.close_rfi(rfi["id"], PE)
        validate_error(resp, ApiErrorId.ERR_RFI_INVALID_STATE, 409)

    def test_answer_twice_rejected(self, api):
        """PRD §3.5: "the RFI must be `ROUTED` (otherwise `ERR_RFI_INVALID_STATE`)"
        A second answer on an already ANSWERED RFI (no reopen in between) is rejected.

        Design: Corner/state_machines/answer_twice_rejected
        """
        project, reviewer = _active_project_with_reviewer(api)
        rfi = create_rfi(project["id"], subject="S", question_text="Q")
        route_rfi(rfi["id"], reviewer["id"])
        answer_rfi(rfi["id"], reviewer["id"], answer_text="a1")

        resp = api.answer_rfi(
            rfi["id"],
            create_rfi_answer_payload("a2"),
            make_reviewer_headers(reviewer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_RFI_INVALID_STATE, 409)

    def test_answer_with_cost_flag_but_no_estimate_returns_invalid_request(self, api):
        """PRD §3.5: "A true cost flag requires `estimated_cost_cents` to be present, and
        a true schedule flag requires `estimated_schedule_days` — the calendar days of
        slip being claimed — to be present; a missing conditionally-required estimate
        fails with `ERR_INVALID_REQUEST`."

        Design: Corner/validations/answer_with_cost_flag_but_no_estimate_returns_invalid_request
        """
        project, reviewer = _active_project_with_reviewer(api)
        rfi = create_rfi(project["id"], subject="S", question_text="Q")
        route_rfi(rfi["id"], reviewer["id"])

        resp = api.answer_rfi(
            rfi["id"],
            {
                "answer_text": "premium",
                "cost_impact_flag": True,
                "schedule_impact_flag": False,
            },
            make_reviewer_headers(reviewer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


class TestRfiDueDate:
    def test_rfi_due_date_skips_project_holidays(self, api):
        """PRD §2.6: "A business day is a Monday through Friday whose `YYYY-MM-DD` date
        does not appear in the project's `holiday_dates` array; holidays and weekends are
        simply skipped when counting."
        PRD §3.5: "computes `due_date` by advancing `rfi_response_days` business days
        from the opened date with the opened day itself counted as day zero"
        Opened Monday 2026-08-03 with the default ten business days and Friday
        2026-08-14 a holiday lands on 2026-08-18, one day later than the no-holiday
        2026-08-17.

        Design: Corner/calculations/rfi_due_date_skips_project_holidays
        """
        project, _reviewer = _active_project_with_reviewer(
            api, holiday_dates=["2026-08-14"]
        )
        set_clock("2026-08-03T09:00:00Z")
        rfi = create_rfi(project["id"], subject="S", question_text="Q")
        assert rfi["opened_date"] == "2026-08-03"
        assert rfi["due_date"] == "2026-08-18", (
            "the holiday 2026-08-14 is skipped in the forward business-day pass"
        )

    def test_create_then_read_reflects_all_computed_fields_immediately(self, api):
        """PRD §3.5: "Creation stamps the RFI `OPEN`, assigns `rfi_number` as `RFI-`
        followed by a one-based per-project sequence zero-padded to four digits
        (`RFI-0001`, `RFI-0002`, …), records `opened_date` from the clock, computes
        `due_date` by advancing `rfi_response_days` business days from the opened date
        with the opened day itself counted as day zero, initializes `cycle_count` to zero
        and `is_overdue` to false, and bumps the Project's `version`."
        The create response and a following GET agree exactly on these computed fields.

        Design: Corner/consistency_model/create_then_read_reflects_all_computed_fields_immediately
        """
        project, _reviewer = _active_project_with_reviewer(api)
        set_clock("2026-08-03T09:00:00Z")
        resp = api.create_rfi(
            project["id"],
            create_rfi_payload("S", "Q", current_project_version(project["id"])),
            PE,
        )
        created = validate_success(resp, 201)
        assert_rfi(created)
        assert created["rfi_number"] == "RFI-0001"
        assert created["due_date"] == "2026-08-17"
        assert created["is_overdue"] is False

        fetched = validate_success(api.get_rfi(created["id"], PE), 200)
        assert fetched["due_date"] == created["due_date"] == "2026-08-17"
        assert fetched["is_overdue"] is False
        assert fetched["cycle_count"] == 0


class TestRfiCreateOcc:
    def test_occ_stale_project_version_on_rfi_create(self, api):
        """PRD §2.9: "Creating an RFI (`POST /v1/projects/{projectId}/rfis`) requires
        `expected_project_version`. Creating a second RFI legitimately mints the next
        `rfi_number` and advances the project's `version`; a create carrying a previously
        observed version is therefore stale and is rejected with
        `ERR_STALE_PROJECT_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_project_version_on_rfi_create
        """
        project, _reviewer = _active_project_with_reviewer(api)
        observed = current_project_version(project["id"])
        first = create_rfi(project["id"], expected_project_version=observed, subject="R1")
        assert first["rfi_number"] == "RFI-0001"

        resp = api.create_rfi(
            project["id"], create_rfi_payload("R2", "Q", observed), PE
        )
        validate_error(resp, ApiErrorId.ERR_STALE_PROJECT_VERSION, 412)


class TestRfiPagination:
    def test_pagination_limit_offset_interaction(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned; it
        defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter
        skips a number of items and defaults to 0. Unless otherwise specified, list
        endpoints return resources sorted by `created_at` in ascending order"
        PRD §2.3: "Paginated list responses include the following fields in the `meta`
        object of the response envelope: `limit`, `offset`, `total_count`, and
        `has_more`."
        Three RFIs paged 2 + 1 partition the creation order without overlap.

        Design: Corner/cross_cutting_layers/pagination_limit_offset_interaction
        """
        project, _reviewer = _active_project_with_reviewer(api)
        rfi1 = create_rfi(project["id"], subject="R1")
        rfi2 = create_rfi(project["id"], subject="R2")
        rfi3 = create_rfi(project["id"], subject="R3")

        page1, meta1 = validate_paginated(
            api.list_project_rfis(project["id"], PE, params={"limit": 2, "offset": 0})
        )
        assert [r["id"] for r in page1] == [rfi1["id"], rfi2["id"]]
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api.list_project_rfis(project["id"], PE, params={"limit": 2, "offset": 2})
        )
        assert [r["id"] for r in page2] == [rfi3["id"]]
        assert meta2["has_more"] is False


class TestRfiDueDateBoundary:
    def _two_routed_rfis(self, api):
        project, reviewer = _active_project_with_reviewer(api)
        set_clock("2026-08-03T09:00:00Z")
        rfi1 = create_rfi(project["id"], subject="R1")
        route_rfi(rfi1["id"], reviewer["id"])
        rfi2 = create_rfi(project["id"], subject="R2")
        route_rfi(rfi2["id"], reviewer["id"])
        return project, reviewer, rfi1, rfi2

    def test_answer_on_due_date_is_on_time(self, api):
        """PRD §3.5: "an answer recorded on or before the `due_date` is on time — the
        boundary is inclusive — and a later answer is late."
        Opened Monday 2026-08-03 with ten response days, due 2026-08-17; answering on
        2026-08-17 itself is on time.

        Design: Difficulty/boundary_precision_check/rfi_due_date_inclusive_boundary
        """
        _project, reviewer, rfi1, _rfi2 = self._two_routed_rfis(api)
        assert rfi1["due_date"] == "2026-08-17"

        set_clock("2026-08-17T23:59:00Z")
        answered = answer_rfi(rfi1["id"], reviewer["id"], answer_text="on time")
        assert answered["answered_date"] == "2026-08-17"
        assert answered["is_late_answer"] is False, (
            "answered_date == due_date is on time at the exact boundary"
        )

    def test_answer_one_day_after_due_date_is_late(self, api):
        """PRD §3.5: "an answer recorded on or before the `due_date` is on time — the
        boundary is inclusive — and a later answer is late."
        The same RFI answered on 2026-08-18, one day past its 2026-08-17 due date, is
        late.

        Design: Difficulty/boundary_precision_check/rfi_due_date_inclusive_boundary
        """
        _project, reviewer, _rfi1, rfi2 = self._two_routed_rfis(api)
        assert rfi2["due_date"] == "2026-08-17"

        set_clock("2026-08-18T00:01:00Z")
        answered = answer_rfi(rfi2["id"], reviewer["id"], answer_text="late")
        assert answered["answered_date"] == "2026-08-18"
        assert answered["is_late_answer"] is True


class TestRfiReopenCycle:
    def _answered_rfi(self, api):
        project, reviewer = _active_project_with_reviewer(api)
        set_clock("2026-08-03T09:00:00Z")
        rfi = create_rfi(project["id"], subject="Grid line", question_text="Offset?")
        route_rfi(rfi["id"], reviewer["id"])
        answer_rfi(rfi["id"], reviewer["id"], answer_text="Offset 300mm")
        return project, reviewer, rfi

    def test_reopen_clears_answer_and_recomputes_due_date(self, api):
        """PRD §3.5: "Reopening increments `cycle_count`, clears the answer fields
        (`answer_text`, `answered_date`, `answered_by_reviewer_id`, both impact flags,
        and `estimated_schedule_days` return to null or false), clears `is_overdue`,
        recomputes `due_date` from the current clock date over another
        `rfi_response_days` business days, and bumps the RFI's `version`."
        Opened 2026-08-03 -> due 2026-08-17; reopened 2026-08-05 -> due 2026-08-19.

        Design: Difficulty/non_linear_state_machine/rfi_reopen_cycle_recomputes_due_date
        """
        _project, _reviewer, rfi = self._answered_rfi(api)
        assert rfi["due_date"] == "2026-08-17", "opened Monday + 10 business days"

        set_clock("2026-08-05T09:00:00Z")
        resp = api.reopen_rfi(rfi["id"], PE)
        reopened = validate_success(resp, 200)
        assert reopened["status"] == "ROUTED"
        assert reopened["cycle_count"] == 1
        assert reopened["answer_text"] is None, "the answer fields are cleared"
        assert reopened["due_date"] == "2026-08-19", (
            "due_date recomputes from the reopen clock date over 10 business days"
        )

    def test_reopened_rfi_completes_second_answer_cycle(self, api):
        """PRD §3.5: "An answered RFI may be reopened for clarification by a
        `ProjectEngineer`, returning it to `ROUTED`" and reopening preserves the routed
        reviewer, so the same reviewer answers the second cycle; the answer stamps
        `answered_date` and moves the RFI back to `ANSWERED` ("The answer stamps
        `answered_date` and `answered_by_reviewer_id`...").

        Design: Difficulty/non_linear_state_machine/rfi_reopen_cycle_recomputes_due_date
        """
        _project, reviewer, rfi = self._answered_rfi(api)
        set_clock("2026-08-05T09:00:00Z")
        validate_success(api.reopen_rfi(rfi["id"], PE), 200)

        answered = answer_rfi(
            rfi["id"], reviewer["id"], answer_text="Offset 300mm confirmed"
        )
        assert answered["status"] == "ANSWERED"
        assert answered["answered_date"] == "2026-08-05"
        assert answered["cycle_count"] == 1


