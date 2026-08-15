"""School year opening gate, security-plan revision loop, closure intervals."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data,
    ApiErrorId, TEST_USERS, make_parent_headers, NON_EXISTENT_UUID,
    create_year, create_year_with_plan, setup_open_year,
    create_school_year_payload, create_security_plan_payload,
    create_hired_teacher, create_staffed_section, create_section_payload,
    create_family, create_student,
    setup_open_year_with_section,
)

ADMIN = TEST_USERS["admin_headers"]


class TestYearOpenRequiresActivePlan:
    def test_open_blocked_while_plan_draft(self):
        """PRD §3.1: "With an `ACTIVE` plan in place, opening the year moves it
        `SETUP` → `OPEN`; without one the attempt fails with
        `ERR_SECURITY_PLAN_NOT_ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/school_year_open_requires_active_security_plan
        """
        year, plan = create_year_with_plan()
        resp = api_client.open_school_year(year["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_SECURITY_PLAN_NOT_ACTIVE)
        # Plan still DRAFT; year must remain SETUP.
        year_now = get_success_data(api_client.get_school_year(year["id"], ADMIN))
        assert year_now["status"] == "SETUP"

    def test_open_succeeds_after_plan_approved(self):
        """PRD §3.1: "Submission moves it `DRAFT` → `SUBMITTED`, approval moves it
        `SUBMITTED` → `ACTIVE` and stamps `approved_at` from the logical clock
        (`approved_at` is null in every other status)" and "With an `ACTIVE` plan in
        place, opening the year moves it `SETUP` → `OPEN`".

        Design: Difficulty/cross_entity_state_dependency/school_year_open_requires_active_security_plan
        """
        year, plan = create_year_with_plan()
        get_success_data(api_client.submit_security_plan(plan["id"], ADMIN))
        plan = get_success_data(api_client.approve_security_plan(plan["id"], ADMIN))
        assert plan["status"] == "ACTIVE"
        assert plan["approved_at"] is not None
        year = get_success_data(api_client.open_school_year(year["id"], ADMIN))
        assert year["status"] == "OPEN"


class TestSecurityPlanLifecycle:
    def test_approve_from_draft_rejected(self):
        """PRD §3.1: "approval moves it `SUBMITTED` → `ACTIVE`" — a plan still in
        DRAFT has no declared transition into ACTIVE, so the attempt is an invalid
        from-state under §2.8 step 7 ("The requested transition's from-state holds
        (`ERR_INVALID_STATE`)").

        Design: Corner/state_machines/invalid_from_state_transitions_rejected
        """
        year, plan = create_year_with_plan()
        resp = api_client.approve_security_plan(plan["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        # Confirm the plan is still DRAFT via the year-scoped listing.
        data, _ = validate_paginated(api_client.list_security_plans(year["id"], ADMIN))
        target = [p for p in data if p["id"] == plan["id"]][0]
        assert target["status"] == "DRAFT"


class TestClosureOverlap:
    def test_closed_interval_shared_endpoint_rejected_adjacent_allowed(self):
        """PRD §2.9: "Calendar closures use **closed-interval** semantics: a closure
        covers every day from `start_date` through `end_date`, both inclusive, and two
        closures overlap whenever those closed intervals intersect — a new closure
        whose first day is exactly one day after an existing closure's last day is
        adjacent, not overlapping, and is allowed."
        PRD §3.1: "A new closure that overlaps an existing one under the
        closed-interval semantics of §2.9 is rejected with `ERR_CLOSURE_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/closure_closed_interval_inclusive_overlap
        """
        year, _plan = create_year_with_plan()
        get_success_data(
            api_client.create_closure(
                year["id"],
                {"start_date": "2026-09-07", "end_date": "2026-09-08", "reason": "Rosh Hashanah"},
                ADMIN,
            ),
            201,
        )
        # [09-08..09-09] shares inclusive endpoint day 09-08 -> overlap.
        resp = api_client.create_closure(
            year["id"],
            {"start_date": "2026-09-08", "end_date": "2026-09-09", "reason": "Overlap attempt"},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_CLOSURE_OVERLAP)
        # [09-09..09-10] starts one day after the prior end -> adjacent, allowed.
        adj = api_client.create_closure(
            year["id"],
            {"start_date": "2026-09-09", "end_date": "2026-09-10", "reason": "Adjacent break"},
            ADMIN,
        )
        adj_data = validate_success(adj, 201)
        assert adj_data["start_date"] == "2026-09-09"

    def test_closure_rejects_inverted_dates(self):
        """PRD §2.8 step 5: "a closure's `start_date` on or before its `end_date`...
        otherwise `ERR_INVALID_REQUEST`."
        PRD §3.1: "each with a `start_date`, an `end_date` on or after it, and a
        `reason` label".

        Design: Difficulty/resource_temporal_overlap/closure_closed_interval_inclusive_overlap
        """
        year, _plan = create_year_with_plan()
        resp = api_client.create_closure(
            year["id"],
            {"start_date": "2026-09-10", "end_date": "2026-09-09", "reason": "Inverted"},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestClosureCascade:
    def test_closure_cancels_covered_sessions(self):
        """PRD §3.1: "Creating a closure also cancels class: every `SCHEDULED`
        session of every section in the year whose `session_date` falls inside the
        closure interval moves to `CANCELLED` with `cancel_reason` `CLOSURE`".

        Design: Corner/state_machines/closure_cancels_covered_sessions
        """
        ctx = setup_open_year_with_section()
        year, section = ctx["year"], ctx["section"]
        s_in = get_success_data(
            api_client.create_session(section["id"], {"session_date": "2026-09-13"}, ADMIN), 201
        )
        s_out = get_success_data(
            api_client.create_session(section["id"], {"session_date": "2026-09-20"}, ADMIN), 201
        )
        get_success_data(
            api_client.create_closure(
                year["id"],
                {"start_date": "2026-09-12", "end_date": "2026-09-14", "reason": "Yom Kippur"},
                ADMIN,
            ),
            201,
        )
        s_in_now = get_success_data(api_client.get_session(s_in["id"], ADMIN))
        s_out_now = get_success_data(api_client.get_session(s_out["id"], ADMIN))
        assert s_in_now["status"] == "CANCELLED"
        assert s_in_now["cancel_reason"] == "CLOSURE"
        assert s_out_now["status"] == "SCHEDULED"


class TestYearOpenRbac:
    def test_parent_cannot_open_school_year(self):
        """PRD §4: the open endpoint's Authorized Role(s) list contains only
        "SchoolAdmin". PRD §2.1: "a caller whose role is not on that list is rejected
        with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/rbac/parent_cannot_open_school_year
        """
        year = create_year()
        family = create_family()
        resp = api_client.open_school_year(year["id"], make_parent_headers(family["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        year_now = get_success_data(api_client.get_school_year(year["id"], ADMIN))
        assert year_now["status"] == "SETUP"

    def test_role_denial_precedes_not_found(self):
        """PRD §2.8: "The server evaluates request checks in a fixed priority order,
        so that earlier failures mask later ones deterministically: 1. Authentication...
        2. Role authorization. The caller's role appears in the endpoint's role list;
        otherwise `ERR_UNAUTHORIZED_ROLE`... 4. Existence. Path resources are
        validated left to right".

        Design: Corner/validations/role_denial_precedes_not_found
        """
        family = create_family()
        resp = api_client.open_school_year(
            NON_EXISTENT_UUID, make_parent_headers(family["id"])
        )
        # Authorization (step 2) masks existence (step 4): not ERR_NOT_FOUND.
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
