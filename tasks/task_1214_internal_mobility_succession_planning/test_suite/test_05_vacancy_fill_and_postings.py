"""Vacancy fill selector policy, fill window, and posting channel wind-down."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS,
    setup_employee, setup_hrbp, setup_manager, setup_report,
    setup_active_role, add_active_successor, setup_vacancy_scenario,
    setup_open_posting, setup_application, consent_application,
    advance_application, terminate_and_get_vacancy, set_clock,
    create_posting_payload, assert_instant_equals,
)

ADMIN = TEST_USERS["admin_headers"]


class TestFillSelectorPolicy:
    def test_selector_skips_suspended_entry(self, api):
        """PRD §3.4: "Eligibility requires an entry on the vacancy's role in
        `ACTIVE` status, rated `READY_NOW` or `READY_1_2`, whose employee's
        `employment_status` is `ACTIVE`."

        Design: Corner/complexity_layers/selector_skips_suspended_entry
        """
        hrbp, hrbp_headers = setup_hrbp(employee_code="HRPC132")
        incumbent = setup_employee(employee_code="INC132", job_level=8,
                                   performance_rating="STRONG", hire_date="2019-03-01")
        sue_a = setup_employee(employee_code="S132A", job_level=6,
                               performance_rating="STRONG", hire_date="2022-07-01")
        sue_b = setup_employee(employee_code="S132B", job_level=6,
                               performance_rating="STRONG", hire_date="2022-07-01")
        role = setup_active_role(hrbp_headers, incumbent["id"], role_title="Role 132")
        entry_b = add_active_successor(role["id"], sue_b["id"], hrbp_headers,
                                       readiness_rating="READY_NOW", slate_position=1)
        suspended = validate_success(api.patch_successor(entry_b["id"], {
            "status": "SUSPENDED", "suspension_reason": "PERFORMANCE_CONCERN",
        }, hrbp_headers), 200)
        assert suspended["status"] == "SUSPENDED"
        add_active_successor(role["id"], sue_a["id"], hrbp_headers,
                             readiness_rating="READY_1_2", slate_position=2)
        vacancy = terminate_and_get_vacancy(role["id"], incumbent["id"], hrbp_headers)

        filled = validate_success(
            api.fill_vacancy_from_slate(vacancy["id"], hrbp_headers), 200,
        )
        assert filled["filled_by_employee_id"] == sue_a["id"], (
            "the SUSPENDED READY_NOW entry at position 1 must be excluded; "
            "the ACTIVE READY_1_2 entry at position 2 is selected"
        )

    def test_selector_tie_break_by_slate_position(self, api):
        """PRD §3.4: "Ranking proceeds through four tie-breaking levels:
        `READY_NOW` entries rank before `READY_1_2` entries; within the same
        band, the higher `readiness_score` — compared at its stored
        2-decimal-place precision — ranks first; then the lower
        `slate_position`; and finally the earlier `created_at` as the last
        resort, never the resource id."

        Design: Corner/complexity_layers/selector_tie_break_by_slate_position
        """
        hrbp, hrbp_headers = setup_hrbp(employee_code="HRPC133")
        incumbent = setup_employee(employee_code="INC133", job_level=8,
                                   performance_rating="STRONG", hire_date="2019-03-01")
        sue_a = setup_employee(employee_code="S133A", job_level=6,
                               performance_rating="STRONG", hire_date="2022-07-01")
        sue_b = setup_employee(employee_code="S133B", job_level=6,
                               performance_rating="STRONG", hire_date="2022-07-01")
        role = setup_active_role(hrbp_headers, incumbent["id"], role_title="Role 133")
        entry_a = add_active_successor(role["id"], sue_a["id"], hrbp_headers,
                                       readiness_rating="READY_NOW", slate_position=2)
        entry_b = add_active_successor(role["id"], sue_b["id"], hrbp_headers,
                                       readiness_rating="READY_NOW", slate_position=1)
        score_a = get_success_data(api.get_successor(entry_a["id"], hrbp_headers))
        score_b = get_success_data(api.get_successor(entry_b["id"], hrbp_headers))
        assert score_a["readiness_score"] == pytest.approx(40.00, abs=0.001)
        assert score_b["readiness_score"] == pytest.approx(40.00, abs=0.001)
        vacancy = terminate_and_get_vacancy(role["id"], incumbent["id"], hrbp_headers)

        filled = validate_success(
            api.fill_vacancy_from_slate(vacancy["id"], hrbp_headers), 200,
        )
        assert filled["filled_by_employee_id"] == sue_b["id"], (
            "identical readiness band and score: the lower slate_position (1) wins"
        )

    def test_selector_empty_pool_returns_no_eligible_successor(self, api):
        """PRD §3.4: "the eligible successor pool must be non-empty (otherwise
        `ERR_NO_ELIGIBLE_SUCCESSOR`)"
        PRD §3.4: "Eligibility requires an entry on the vacancy's role in
        `ACTIVE` status, rated `READY_NOW` or `READY_1_2`, whose employee's
        `employment_status` is `ACTIVE`."

        Design: Corner/complexity_layers/selector_empty_pool_returns_no_eligible_successor
        """
        ctx = setup_vacancy_scenario(with_ready_successor=True,
                                     successor_readiness="READY_3_PLUS")
        resp = api.fill_vacancy_from_slate(ctx["vacancy"]["id"], ctx["hrbp_headers"])
        validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_SUCCESSOR, 409)
        vacancy = get_success_data(
            api.get_vacancy(ctx["vacancy"]["id"], ctx["hrbp_headers"])
        )
        assert vacancy["status"] == "OPEN"


class TestFillWindow:
    def _setup_fillable_vacancy(self, api, code_suffix):
        hrbp, hrbp_headers = setup_hrbp(employee_code=f"HRPC{code_suffix}")
        incumbent = setup_employee(employee_code=f"INC{code_suffix}", job_level=8,
                                   performance_rating="STRONG", hire_date="2019-03-01")
        successor = setup_employee(employee_code=f"S{code_suffix}", job_level=6,
                                   performance_rating="STRONG", hire_date="2022-07-01")
        role = setup_active_role(hrbp_headers, incumbent["id"],
                                 role_title=f"Role {code_suffix}")
        entry = add_active_successor(role["id"], successor["id"], hrbp_headers,
                                     readiness_rating="READY_NOW", slate_position=1)
        vacancy = terminate_and_get_vacancy(role["id"], incumbent["id"], hrbp_headers)
        return hrbp_headers, role, successor, entry, vacancy

    def test_fill_after_deadline_returns_fill_window_expired(self, api):
        """PRD §3.4: "the current instant must be on or before the vacancy's
        `fill_deadline`, the window being inclusive (otherwise
        `ERR_FILL_WINDOW_EXPIRED`)"
        PRD §2.4: "A vacancy's `fill_deadline` is the vacancy's `created_at`
        plus 60 days, and a slate fill is accepted while the current instant is
        on or before that deadline — the fill window is inclusive, in contrast
        to the strict consent window — after which fills are rejected with
        `ERR_FILL_WINDOW_EXPIRED`."

        Design: Corner/validations/fill_after_deadline_returns_fill_window_expired
        """
        hrbp_headers, role, successor, entry, vacancy = (
            self._setup_fillable_vacancy(api, "102")
        )
        assert_instant_equals(vacancy["fill_deadline"], "2026-06-30T00:00:00Z")
        set_clock("2026-07-01T00:00:00Z")

        resp = api.fill_vacancy_from_slate(vacancy["id"], hrbp_headers)
        validate_error(resp, ApiErrorId.ERR_FILL_WINDOW_EXPIRED, 409)

        vacancy = get_success_data(api.get_vacancy(vacancy["id"], hrbp_headers))
        assert vacancy["status"] == "OPEN"
        entry = get_success_data(api.get_successor(entry["id"], hrbp_headers))
        assert entry["status"] == "ACTIVE"

    def test_fill_at_exact_deadline_succeeds(self, api):
        """PRD §2.4: "A vacancy's `fill_deadline` is the vacancy's `created_at`
        plus 60 days, and a slate fill is accepted while the current instant is
        on or before that deadline — the fill window is inclusive, in contrast
        to the strict consent window — after which fills are rejected with
        `ERR_FILL_WINDOW_EXPIRED`."

        Design: Corner/validations/fill_at_exact_deadline_succeeds
        """
        hrbp_headers, role, successor, entry, vacancy = (
            self._setup_fillable_vacancy(api, "103")
        )
        set_clock("2026-06-30T00:00:00Z")

        filled = validate_success(
            api.fill_vacancy_from_slate(vacancy["id"], hrbp_headers), 200,
        )
        assert filled["status"] == "FILLED"
        assert filled["filled_by_employee_id"] == successor["id"]


class TestFillTerminalAndConsistency:
    def test_fill_on_filled_vacancy_returns_vacancy_not_open(self, api):
        """PRD §3.4: "The request is validated in order: the vacancy must be
        `OPEN` (otherwise `ERR_VACANCY_NOT_OPEN`)"

        Design: Corner/state_machines/fill_on_filled_vacancy_returns_vacancy_not_open
        """
        ctx = setup_vacancy_scenario(with_ready_successor=True)
        first = validate_success(
            api.fill_vacancy_from_slate(ctx["vacancy"]["id"], ctx["hrbp_headers"]), 200,
        )
        assert first["status"] == "FILLED"

        resp = api.fill_vacancy_from_slate(ctx["vacancy"]["id"], ctx["hrbp_headers"])
        validate_error(resp, ApiErrorId.ERR_VACANCY_NOT_OPEN, 409)

        vacancy = get_success_data(
            api.get_vacancy(ctx["vacancy"]["id"], ctx["hrbp_headers"])
        )
        assert vacancy["status"] == "FILLED"
        assert vacancy["filled_by_employee_id"] == ctx["successor"]["id"]

    def test_immediate_visibility_after_slate_fill(self, api):
        """PRD §2.9: "Every mutation together with all of its cascades and
        recomputations commits atomically within the same request; the platform
        never persists a partial cascade."
        PRD §3.4: "A successful slate fill does four things at once: the
        selected entry becomes `PROMOTED`; the vacancy becomes `FILLED` with
        `fill_source` `SUCCESSION_SLATE` and `filled_by_employee_id` set to the
        selected employee; the role transitions from `VACANT` back to `ACTIVE`
        with the selected employee as `incumbent_employee_id`, its `version`
        incrementing; and the role's bench recomputes because the promoted
        entry left the `ACTIVE` slate."

        Design: Corner/consistency_model/immediate_visibility_after_slate_fill
        """
        ctx = setup_vacancy_scenario(with_ready_successor=True)

        filled = validate_success(
            api.fill_vacancy_from_slate(ctx["vacancy"]["id"], ctx["hrbp_headers"]), 200,
        )
        assert filled["status"] == "FILLED"
        assert filled["filled_by_employee_id"] == ctx["successor"]["id"]

        role = get_success_data(
            api.get_critical_role(ctx["role"]["id"], ctx["hrbp_headers"])
        )
        assert role["status"] == "ACTIVE"
        assert role["incumbent_employee_id"] == ctx["successor"]["id"]

        entry = get_success_data(
            api.get_successor(ctx["entry"]["id"], ctx["hrbp_headers"])
        )
        assert entry["status"] == "PROMOTED"


class TestVacancyAndPostingClose:
    def test_vacancy_close_cascades_to_posting_and_applications(self, api):
        """PRD §3.4: "Closing moves the vacancy to `CLOSED_UNFILLED`,
        transitions any `OPEN` posting of the vacancy to `CLOSED`, and rejects
        that posting's non-terminal applications."

        Design: Corner/state_machines/vacancy_close_cascades_to_posting_and_applications
        """
        hrbp, hrbp_headers = setup_hrbp(employee_code="HRPB65")
        manager, _ = setup_manager(employee_code="MGR65")
        applicant = setup_report(manager["id"], employee_code="E65", job_level=5,
                                 hire_date="2024-05-01", performance_rating="SOLID")
        incumbent = setup_employee(employee_code="INC65", job_level=8,
                                   performance_rating="STRONG", hire_date="2019-03-01")
        role = setup_active_role(hrbp_headers, incumbent["id"], role_title="Role 65")
        vacancy = terminate_and_get_vacancy(role["id"], incumbent["id"], hrbp_headers)
        posting = setup_open_posting(vacancy["id"], hrbp_headers, title="Role 65")
        application = setup_application(posting["id"], applicant)
        consent_application(application["id"], manager["id"])

        closed = validate_success(api.close_vacancy(
            vacancy["id"], {"closed_reason": "ORG_CHANGE"}, hrbp_headers,
        ), 200)
        assert closed["status"] == "CLOSED_UNFILLED"
        assert closed["closed_reason"] == "ORG_CHANGE"

        posting = get_success_data(api.get_posting(posting["id"], hrbp_headers))
        assert posting["status"] == "CLOSED"
        application = get_success_data(api.get_application(application["id"], hrbp_headers))
        assert application["status"] == "REJECTED"

    def test_posting_close_rejects_open_applications(self, api):
        """PRD §3.5: "closing an `OPEN` posting moves it to `CLOSED` and
        rejects all of its non-terminal applications, freeing any hold those
        applications carried; closing a `DRAFT` posting moves it to `CANCELLED`
        with no application effects."

        Design: Corner/state_machines/posting_close_rejects_open_applications
        """
        hrbp, hrbp_headers = setup_hrbp(employee_code="HRPB66")
        manager, _ = setup_manager(employee_code="MGR66")
        applicant = setup_report(manager["id"], employee_code="E66", job_level=5,
                                 hire_date="2024-05-01", performance_rating="SOLID")
        incumbent = setup_employee(employee_code="INC66", job_level=8,
                                   performance_rating="STRONG", hire_date="2019-03-01")
        role = setup_active_role(hrbp_headers, incumbent["id"], role_title="Role 66")
        vacancy = terminate_and_get_vacancy(role["id"], incumbent["id"], hrbp_headers)
        posting = setup_open_posting(vacancy["id"], hrbp_headers, title="Role 66")
        application = setup_application(posting["id"], applicant)
        consent_application(application["id"], manager["id"])
        advance_application(application["id"], "INTERVIEWING", hrbp_headers)

        closed = validate_success(api.close_posting(posting["id"], hrbp_headers), 200)
        assert closed["status"] == "CLOSED"

        application = get_success_data(api.get_application(application["id"], hrbp_headers))
        assert application["status"] == "REJECTED"
        vacancy = get_success_data(api.get_vacancy(vacancy["id"], hrbp_headers))
        assert vacancy["status"] == "OPEN", "closing a posting must not close the vacancy"


class TestPostingWindowOverlap:
    def _setup_vacancy_with_open_posting(self, api):
        hrbp, hrbp_headers = setup_hrbp(employee_code="HRPB16")
        incumbent = setup_employee(employee_code="INC16", job_level=8,
                                   performance_rating="STRONG", hire_date="2019-03-01")
        role = setup_active_role(hrbp_headers, incumbent["id"], role_title="Cloud Lead")
        vacancy = terminate_and_get_vacancy(role["id"], incumbent["id"], hrbp_headers)
        posting_a = setup_open_posting(
            vacancy["id"], hrbp_headers, title="Cloud Lead A",
            planned_open_date="2026-05-04", planned_close_date="2026-05-15",
        )
        return hrbp_headers, vacancy, posting_a

    def test_shared_boundary_date_conflicts(self, api):
        """PRD §2.11: "Because the interval is closed at day granularity, a
        posting whose `planned_open_date` equals the other's
        `planned_close_date` conflicts — in contrast to the half-open session
        calendar, where adjacency is allowed."
        PRD §3.5: "the new window must not overlap any other `OPEN` posting of
        the same vacancy under the closed-interval semantics of §2.11
        (otherwise `ERR_POSTING_WINDOW_CONFLICT` — note that a shared boundary
        date conflicts here, unlike the session calendar)."

        Design: Difficulty/resource_temporal_overlap/posting_window_closed_interval_adjacency_conflicts
        """
        hrbp_headers, vacancy, posting_a = self._setup_vacancy_with_open_posting(api)

        posting_b = validate_success(api.create_posting(vacancy["id"], {
            "title": "Cloud Lead B",
            "planned_open_date": "2026-05-15",
            "planned_close_date": "2026-05-29",
        }, hrbp_headers), 201)
        assert posting_b["status"] == "DRAFT"

        resp = api.publish_posting(posting_b["id"], hrbp_headers)
        validate_error(resp, ApiErrorId.ERR_POSTING_WINDOW_CONFLICT, 409)

        posting_b = get_success_data(api.get_posting(posting_b["id"], hrbp_headers))
        assert posting_b["status"] == "DRAFT", "rejected publish leaves the posting DRAFT"

    def test_next_day_window_is_allowed(self, api):
        """PRD §2.11: "At publish time, the new posting conflicts with any
        other posting of the same vacancy whose status is `OPEN` exactly when
        the new open date is on or before the existing close date and the
        existing open date is on or before the new close date."

        Design: Difficulty/resource_temporal_overlap/posting_window_closed_interval_adjacency_conflicts
        """
        hrbp_headers, vacancy, posting_a = self._setup_vacancy_with_open_posting(api)

        posting_c = validate_success(api.create_posting(vacancy["id"], {
            "title": "Cloud Lead C",
            "planned_open_date": "2026-05-16",
            "planned_close_date": "2026-05-29",
        }, hrbp_headers), 201)
        published = validate_success(api.publish_posting(posting_c["id"], hrbp_headers), 200)
        assert published["status"] == "OPEN", (
            "2026-05-16 is fully disjoint from [2026-05-04, 2026-05-15] and must publish"
        )
