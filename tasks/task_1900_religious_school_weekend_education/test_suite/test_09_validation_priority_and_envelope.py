"""Validation priority pairs, invalid from-state transitions, entity creation
defaults, not-found, response envelope, pagination, and auth."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, is_iso8601_timestamp,
    ApiErrorId, TEST_USERS, make_parent_headers, NON_EXISTENT_UUID,
    setup_open_year_with_section, setup_family_with_invoice,
    setup_family_with_enrollment, create_year, create_family,
    create_student, enroll_student_fresh, post_payment,
    create_application_payload, create_hired_teacher,
    get_family, get_milestone_for_student,
)

ADMIN = TEST_USERS["admin_headers"]


class TestValidationPriorityPairs:
    def test_state_outranks_fiscal_on_invoice_reissue(self):
        """PRD §2.8: "The server evaluates request checks in a fixed priority
        order, so that earlier failures mask later ones deterministically", with
        step 7 "State preconditions... (`ERR_SCHOOL_YEAR_NOT_OPEN`)" listed before
        step 12 "Fiscal rules. Re-issue only against an unpaid invoice
        (`ERR_INVOICE_HAS_PAYMENTS`)".

        Design: Difficulty/priority_pair_validation_conflict/state_outranks_fiscal_on_invoice_reissue
        """
        ctx = setup_open_year_with_section()
        year = ctx["year"]
        bundle = setup_family_with_invoice(year, ctx["section"], 1)
        family, inv = bundle["family"], bundle["invoice"]
        post_payment(family["id"], 20000, method="CHECK")  # invoice now has payments
        get_success_data(api_client.close_school_year(year["id"], ADMIN))
        fresh = get_family(family["id"])
        # Both violations hold (year CLOSED; paid_cents > 0) — state must win.
        resp = api_client.issue_invoice(
            family["id"],
            {"school_year_id": year["id"],
             "expected_family_version": fresh["version"]},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_SCHOOL_YEAR_NOT_OPEN)
        assert resp.status_code == 409

    def test_safety_outranks_temporal_on_session_hold(self):
        """PRD §2.8: step 8 "Safety and compliance. An `ACTIVE` security plan
        where required (`ERR_SECURITY_PLAN_NOT_ACTIVE`)" is listed before step 9
        "Calendar and temporal rules... holding a future-dated session
        (`ERR_SESSION_DATE_IN_FUTURE`)", and §2.8 opens with "The server evaluates
        request checks in a fixed priority order, so that earlier failures mask
        later ones deterministically".

        Design: Difficulty/priority_pair_validation_conflict/safety_outranks_temporal_on_session_hold
        """
        ctx = setup_open_year_with_section()
        year, section, plan = ctx["year"], ctx["section"], ctx["plan"]
        session = get_success_data(
            api_client.create_session(section["id"], {"session_date": "2026-09-13"}, ADMIN),
            201,
        )
        # Retire the only ACTIVE plan -> no ACTIVE plan remains; clock untouched at
        # the 2026-08-01 default, so 2026-09-13 is also in the future.
        get_success_data(api_client.retire_security_plan(plan["id"], ADMIN))
        resp = api_client.hold_session(session["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_SECURITY_PLAN_NOT_ACTIVE)
        s_now = get_success_data(api_client.get_session(session["id"], ADMIN))
        assert s_now["status"] == "SCHEDULED"

    def test_year_closed_alone_blocks_invoice_issue(self):
        """PRD §3.1: "Only an `OPEN` year accepts enrollments, invoice issues,
        session scheduling, and assistance applications — each of those operations
        rejects with `ERR_SCHOOL_YEAR_NOT_OPEN` against a year in any other
        status."

        Design: Difficulty/priority_pair_validation_conflict/state_outranks_fiscal_on_invoice_reissue
        """
        ctx = setup_open_year_with_section()
        year = ctx["year"]
        bundle = setup_family_with_invoice(year, ctx["section"], 1)
        family = bundle["family"]
        # No payment posted: only the year-state violation exists on re-issue.
        get_success_data(api_client.close_school_year(year["id"], ADMIN))
        fresh = get_family(family["id"])
        resp = api_client.issue_invoice(
            family["id"],
            {"school_year_id": year["id"],
             "expected_family_version": fresh["version"]},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_SCHOOL_YEAR_NOT_OPEN)

    def test_hold_allowed_once_plan_active_and_date_reached(self):
        """PRD §3.4: "The transition `SCHEDULED` → `HELD` is allowed only when the
        year has an `ACTIVE` security plan (`ERR_SECURITY_PLAN_NOT_ACTIVE`) and the
        `session_date` is on or before the logical clock's current date"."

        Design: Difficulty/priority_pair_validation_conflict/safety_outranks_temporal_on_session_hold
        """
        ctx = setup_open_year_with_section()
        section = ctx["section"]
        session = get_success_data(
            api_client.create_session(section["id"], {"session_date": "2026-09-13"}, ADMIN),
            201,
        )
        # Plan still ACTIVE; advance the clock to the session date so neither rule
        # is violated — the hold succeeds.
        get_success_data(
            api_client.set_clock({"to_iso8601": "2026-09-13T00:00:00Z"}, ADMIN)
        )
        held = get_success_data(api_client.hold_session(session["id"], ADMIN))
        assert held["status"] == "HELD"


class TestInvalidFromStates:
    def test_decide_from_submitted_rejected(self):
        """PRD §3.5: "A `SchoolAdmin` decides an `UNDER_REVIEW` application" — a
        SUBMITTED application is not in the decide transition's from-state, and
        §2.8 step 7: "The requested transition's from-state holds
        (`ERR_INVALID_STATE`)".

        Design: Corner/state_machines/invalid_from_state_transitions_rejected
        """
        from test_helpers import setup_open_year
        year, _plan = setup_open_year()
        family = create_family()
        app = get_success_data(
            api_client.create_application(
                family["id"], create_application_payload(year["id"]), ADMIN
            ),
            201,
        )
        assert app["status"] == "SUBMITTED"
        from test_helpers import make_admin_headers
        resp = api_client.decide_application(
            app["id"], {"decision": "DENIED"}, make_admin_headers("admin-9")
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_complete_tracking_milestone_rejected(self):
        """PRD §3.4: "completing the milestone moves it `SCHEDULED` → `COMPLETED`"
        — TRACKING is not a from-state for complete; §2.8 step 7: "The requested
        transition's from-state holds (`ERR_INVALID_STATE`)".

        Design: Corner/state_machines/invalid_from_state_transitions_rejected
        """
        ctx = setup_open_year_with_section()
        bundle = setup_family_with_enrollment(ctx["section"], 1)
        milestone = get_milestone_for_student(bundle["students"][0]["id"])
        assert milestone["status"] == "TRACKING"
        resp = api_client.complete_milestone(milestone["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_double_withdraw_rejected(self):
        """PRD §3.7: "withdrawal moves an enrollment from `REGISTERED` or `ACTIVE`
        — the only two states from which withdrawal is permitted, anything else
        failing with `ERR_INVALID_STATE`".

        Design: Corner/state_machines/invalid_from_state_transitions_rejected
        """
        ctx = setup_open_year_with_section()
        bundle = setup_family_with_enrollment(ctx["section"], 1)
        enr = bundle["enrollments"][0]
        get_success_data(api_client.withdraw_enrollment(enr["id"], ADMIN))
        resp = api_client.withdraw_enrollment(enr["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_double_cancel_rejected(self):
        """PRD §3.4: "A session may instead be cancelled: an administrator cancels
        manually" for a `SCHEDULED` session ("The transition `SCHEDULED` → `HELD`
        ... A session may instead be cancelled") — an already-CANCELLED session has
        no cancel from-state; §2.8 step 7: "The requested transition's from-state
        holds (`ERR_INVALID_STATE`)".

        Design: Corner/state_machines/invalid_from_state_transitions_rejected
        """
        ctx = setup_open_year_with_section()
        session = get_success_data(
            api_client.create_session(
                ctx["section"]["id"], {"session_date": "2026-09-13"}, ADMIN
            ),
            201,
        )
        get_success_data(api_client.cancel_session(session["id"], ADMIN))
        resp = api_client.cancel_session(session["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestFamilyCreation:
    def test_family_creation_defaults_and_missing_field(self):
        """PRD §3.3: "A new family starts with `outstanding_balance_cents` and
        `credit_balance_cents` at 0 and `version` 1." PRD §2.8 step 5: "Required
        fields are present... otherwise `ERR_INVALID_REQUEST`" — and §3.3 lists
        `membership_status` as part of the registration payload.

        Design: Corner/entities/family_creation_defaults_and_system_fields
        """
        fam = get_success_data(
            api_client.create_family(
                {"family_name": "Fam Zero", "primary_email": "z@x.org",
                 "membership_status": "MEMBER"},
                ADMIN,
            ),
            201,
        )
        assert fam["outstanding_balance_cents"] == 0
        assert fam["credit_balance_cents"] == 0
        assert fam["version"] == 1
        assert is_iso8601_timestamp(fam["created_at"])
        resp = api_client.create_family(
            {"family_name": "Fam Bad", "primary_email": "bad@x.org"}, ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestNotFound:
    def test_get_nonexistent_family_returns_not_found(self):
        """PRD §2.8 step 4: "Existence. Path resources are validated left to
        right — a request naming a school year and then a closure is rejected with
        `ERR_NOT_FOUND` for the year before the closure is ever examined." — a
        well-formed but absent family id fails the same existence check.

        Design: Corner/entities/get_nonexistent_family_returns_not_found
        """
        resp = api_client.get_family(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestEnvelope:
    def test_response_envelope_shape(self):
        """PRD §2.2: "The `response_type` is either "object" for a single resource
        or "array" for a list of resources." and for errors "The `meta` object for
        error responses contains only `api_request_id` and
        `api_request_timestamp`... The `error_id` is a unique, machine-readable
        string that identifies the specific error. The `message` provides a
        human-readable explanation".

        Design: Corner/endpoints/response_envelope_shape
        """
        fam = create_family(family_name="Fam Env")
        create_student(fam["id"], full_name="E1")
        single = api_client.get_family(fam["id"], ADMIN).json()
        assert single["response_type"] == "object"
        assert single["meta"]["api_request_id"]
        assert is_iso8601_timestamp(single["meta"]["api_request_timestamp"])
        assert single["data"]["id"] == fam["id"]
        listing = api_client.list_students(fam["id"], ADMIN).json()
        assert listing["response_type"] == "array"
        err = api_client.get_family(NON_EXISTENT_UUID, ADMIN).json()
        assert err["response_type"] == "error"
        assert err["data"]["error_id"] == "ERR_NOT_FOUND"
        assert err["data"]["message"]


class TestPaginationAndFilters:
    def test_enrollment_list_pagination_and_family_filter(self):
        """PRD §2.3: "The `limit` parameter caps the number of items returned...
        The `offset` parameter skips that many items before returning the page...
        List responses carry `limit`, `offset`, `total_count`, and `has_more` in
        the `meta` object of the envelope." PRD §3.3: "The enrollments listing
        accepts optional `family_id`, `student_id`, `section_id`, `school_year_id`,
        and `status` filters."

        Design: Corner/endpoints/enrollment_list_pagination_and_filter
        """
        ctx = setup_open_year_with_section(capacity=10)
        section = ctx["section"]
        fam_a = create_family()
        a_kids = [create_student(fam_a["id"]) for _ in range(3)]
        for k in a_kids:
            enroll_student_fresh(section["id"], k["id"])
        fam_b = create_family()
        b_kid = create_student(fam_b["id"])
        enroll_student_fresh(section["id"], b_kid["id"])

        page1 = api_client.list_enrollments(
            ADMIN, params={"family_id": fam_a["id"], "limit": 2, "offset": 0}
        )
        data1, meta1 = validate_paginated(page1)
        assert len(data1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2 = api_client.list_enrollments(
            ADMIN, params={"family_id": fam_a["id"], "limit": 2, "offset": 2}
        )
        data2, meta2 = validate_paginated(page2)
        assert len(data2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False


class TestAuth:
    def test_missing_auth_headers_return_unauthenticated(self):
        """PRD §2.1: "A request with missing headers or an unrecognized role is
        rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/missing_auth_headers_return_unauthenticated
        """
        family = create_family()
        resp = api_client.get_family(family["id"], headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_parent_reading_other_family_forbidden(self):
        """PRD §2.1: "a parent touching another family's subtree is rejected with
        `ERR_OWNERSHIP_MISMATCH` (HTTP 403)". PRD §4: "Get a family (Parent: own
        family only)".

        Design: Corner/rbac/parent_reading_other_family_forbidden
        """
        fam_a = create_family(family_name="Fam A")
        fam_b = create_family(family_name="Fam B")
        resp = api_client.get_family(fam_b["id"], make_parent_headers(fam_a["id"]))
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH)
        ok = api_client.get_family(fam_a["id"], make_parent_headers(fam_a["id"]))
        ok_data = validate_success(ok, 200)
        assert ok_data["id"] == fam_a["id"]
