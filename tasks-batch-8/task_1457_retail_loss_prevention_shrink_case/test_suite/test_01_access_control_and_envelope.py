"""Access control (roles, auth headers), response envelope, pagination, and
simple reverse-filter reads."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_instants_equal,
    draft_demand,
    hold_interview,
    document_interview,
    make_admin_headers,
    make_analyst_headers,
    make_auditor_headers,
    make_hr_partner_headers,
    make_manager_headers,
    make_pos_feed_headers,
    make_employee,
    make_orc_group,
    make_period,
    make_store,
    post_event,
    schedule_interview,
    setup_case_adjudicating,
    setup_case_interviewed,
    setup_case_ready_for_interview,
    the_only_alert,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import ADMIN_1, ANALYST_1, AUDITOR_1, HR_PARTNER_1, MANAGER_1


class TestAuthHeaders:
    def test_missing_user_headers_unauthenticated(self, api):
        """PRD §2.1: "A request with either header missing or malformed, or
        whose role value is not one of these six, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_user_headers_unauthenticated
        """
        resp = api.list_stores(headers={})
        body = resp.json()
        assert body.get("response_type") == "error"
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_wrong_role_forbidden_precedes_not_found(self, api):
        """PRD §2.7: "Every request passes through a single ordered validation
        pipeline, and the first failing check produces the response — later
        checks are not evaluated."
        PRD §2.7: "2. Role permission for the endpoint, including subject-type
        routing on adjudication (`ERR_FORBIDDEN_FOR_ROLE`)."
        PRD §2.7: "5. Existence of every referenced resource (`ERR_NOT_FOUND`)."

        An LPAnalyst calling store-close on a nonexistent store id fails the
        role check (step 2) before existence (step 5) is examined.

        Design: Corner/validations/wrong_role_forbidden_precedes_not_found
        """
        resp = api.close_store(NON_EXISTENT_UUID, make_analyst_headers(ANALYST_1))
        err = validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        assert err["error_id"] != ApiErrorId.ERR_NOT_FOUND


class TestRoleDenials:
    def test_posfeed_cannot_create_case(self, api):
        """PRD §2.1: "`PosFeed` (the machine account that ingests POS exception
        events)"
        PRD §4: "| POST | `/cases` | Create a manual case | LPAnalyst |"
        PRD §2.1: "A request whose role is recognized but not permitted for the
        target endpoint — including the subject-type routing on adjudication,
        where an `EMPLOYEE`-subject case may be adjudicated only by `HRPartner`
        and an `EXTERNAL`-subject case only by `LPManager` — is rejected with
        `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

        Design: Corner/rbac/rbac_posfeed_cannot_create_case_forbidden
        """
        store = make_store()
        resp = api.create_case(
            {"store_id": store["id"], "subject_type": "EXTERNAL",
             "manual_loss_cents": 1000},
            make_pos_feed_headers("feed-1"),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_auditor_cannot_write_but_can_read(self, api):
        """PRD §2.1: "`Auditor` (read-only oversight)"
        PRD §4: "| POST | `/orc-groups` | Create an ORC group | LPManager |"
        PRD §4: "| GET | `/orc-groups` | List ORC groups | All six roles |"
        PRD §2.1: "A request whose role is recognized but not permitted for the
        target endpoint — including the subject-type routing on adjudication,
        where an `EMPLOYEE`-subject case may be adjudicated only by `HRPartner`
        and an `EXTERNAL`-subject case only by `LPManager` — is rejected with
        `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

        Design: Corner/rbac/rbac_auditor_cannot_write_forbidden
        """
        resp = api.create_orc_group(
            {"name": "Ring Iota"}, make_auditor_headers(AUDITOR_1)
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        data, meta = validate_paginated(
            api.list_orc_groups(make_auditor_headers(AUDITOR_1))
        )
        assert data == [] and meta["total_count"] == 0

    def test_hrpartner_cannot_issue_demand(self, api):
        """PRD §4: "| POST | `/civil-demands/{demand_id}/issue` | Issue a DRAFT
        demand (issuer must differ from drafter) | LPManager |"
        PRD §2.1: "A request whose role is recognized but not permitted for the
        target endpoint — including the subject-type routing on adjudication,
        where an `EMPLOYEE`-subject case may be adjudicated only by `HRPartner`
        and an `EXTERNAL`-subject case only by `LPManager` — is rejected with
        `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

        Design: Corner/rbac/rbac_hrpartner_cannot_issue_demand_forbidden
        """
        store = make_store()
        ctx = setup_case_interviewed(store["id"], manual_loss_cents=10000)
        demand = draft_demand(ctx["case"]["id"], ANALYST_1, basis="ACTUAL_LOSS")
        resp = api.issue_civil_demand(
            demand["id"], make_hr_partner_headers(HR_PARTNER_1)
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        after = validate_success(
            api.get_civil_demand(demand["id"], make_manager_headers(MANAGER_1))
        )
        assert after["status"] == "DRAFT", "demand must be unchanged after role denial"

    def test_lpadmin_cannot_convert_alert(self, api):
        """PRD §4: "| POST | `/alerts/{alert_id}/convert` | Convert an alert
        (optionally bundling same-store alerts) into a new case | LPAnalyst |"
        PRD §2.1: "A request whose role is recognized but not permitted for the
        target endpoint — including the subject-type routing on adjudication,
        where an `EMPLOYEE`-subject case may be adjudicated only by `HRPartner`
        and an `EXTERNAL`-subject case only by `LPManager` — is rejected with
        `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

        Design: Corner/rbac/rbac_lpadmin_cannot_convert_alert_forbidden
        """
        store = make_store()
        post_event(store["id"], "HIGH_VALUE_VOID", 40000, "2026-07-12T10:00:00Z")
        post_event(store["id"], "HIGH_VALUE_VOID", 35000, "2026-07-12T11:00:00Z")
        alert = the_only_alert(store["id"], viewer_id=ADMIN_1)
        resp = api.convert_alert(
            alert["id"], {"subject_type": "EXTERNAL"}, make_admin_headers(ADMIN_1)
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_lpanalyst_cannot_adjudicate(self, api):
        """PRD §4: "| POST | `/cases/{case_id}/adjudicate` | Adjudicate an
        ADJUDICATING case (HRPartner for EMPLOYEE subjects, LPManager for
        EXTERNAL) | LPManager, HRPartner |"
        PRD §2.1: "A request whose role is recognized but not permitted for the
        target endpoint — including the subject-type routing on adjudication,
        where an `EMPLOYEE`-subject case may be adjudicated only by `HRPartner`
        and an `EXTERNAL`-subject case only by `LPManager` — is rejected with
        `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

        Design: Corner/rbac/rbac_lpanalyst_cannot_adjudicate_forbidden
        """
        store = make_store()
        ctx = setup_case_adjudicating(store["id"], manual_loss_cents=10000)
        resp = api.adjudicate_case(
            ctx["case"]["id"],
            {"decision": "SUBSTANTIATED", "restitution_waived": True},
            make_analyst_headers(ANALYST_1),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_lpmanager_cannot_register_employee(self, api):
        """PRD §4: "| POST | `/employees` | Register an employee | HRPartner |"
        PRD §2.1: "A request whose role is recognized but not permitted for the
        target endpoint — including the subject-type routing on adjudication,
        where an `EMPLOYEE`-subject case may be adjudicated only by `HRPartner`
        and an `EXTERNAL`-subject case only by `LPManager` — is rejected with
        `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

        Design: Corner/rbac/rbac_lpmanager_cannot_register_employee_forbidden
        """
        store = make_store()
        resp = api.create_employee(
            {"store_id": store["id"], "employee_ref": "E-304",
             "full_name": "Emp 304"},
            make_manager_headers(MANAGER_1),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_adjudicate_subject_type_routing(self, api):
        """PRD §3.5: "An `EMPLOYEE`-subject case can be adjudicated only by an
        `HRPartner`; an `EXTERNAL`-subject case only by an `LPManager`; the
        wrong role draws `ERR_FORBIDDEN_FOR_ROLE`."

        Design: Corner/rbac/rbac_adjudicate_subject_type_routing
        """
        store = make_store()
        make_period(store["id"])
        emp = make_employee(store["id"])
        ctx_emp = setup_case_adjudicating(
            store["id"], subject_type="EMPLOYEE", employee_id=emp["id"],
            manual_loss_cents=10000,
        )
        ctx_ext = setup_case_adjudicating(
            store["id"], subject_type="EXTERNAL", manual_loss_cents=10000,
            scheduled_start="2026-08-02T11:00:00Z",
            scheduled_end="2026-08-02T12:00:00Z",
        )
        # Wrong-role attempts.
        resp1 = api.adjudicate_case(
            ctx_emp["case"]["id"], {"decision": "UNSUBSTANTIATED"},
            make_manager_headers(MANAGER_1),
        )
        validate_error(resp1, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        resp2 = api.adjudicate_case(
            ctx_ext["case"]["id"], {"decision": "UNSUBSTANTIATED"},
            make_hr_partner_headers(HR_PARTNER_1),
        )
        validate_error(resp2, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        # Correct-role counterparts succeed.
        ce = api.adjudicate_case(
            ctx_emp["case"]["id"], {"decision": "UNSUBSTANTIATED"},
            make_hr_partner_headers(HR_PARTNER_1),
        )
        assert validate_success(ce)["status"] == "CLOSED_UNSUBSTANTIATED"
        cx = api.adjudicate_case(
            ctx_ext["case"]["id"], {"decision": "UNSUBSTANTIATED"},
            make_manager_headers(MANAGER_1),
        )
        assert validate_success(cx)["status"] == "CLOSED_UNSUBSTANTIATED"


class TestResponseEnvelope:
    def test_envelope_success_object_shape(self, api):
        """PRD §2.2: "The `response_type` is either "object" for a single
        resource or "array" for a list of resources."
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`."
        PRD §2.2: "The `api_request_timestamp` is a server-generated ISO 8601
        UTC timestamp with three fractional digits."

        Design: Corner/endpoints/envelope_success_object_shape
        """
        store = make_store(store_number="S100x", name="Envelope Store")
        resp = api.get_store(store["id"], make_auditor_headers(AUDITOR_1))
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert isinstance(body["meta"]["api_request_timestamp"], str)
        assert body["response_type"] == "object"
        assert body["data"]["id"] == store["id"]
        assert body["data"]["store_number"] == "S100x"

    def test_envelope_error_shape_on_not_found(self, api):
        """PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."
        PRD §2.2: "The `message` provides a human-readable explanation of what
        went wrong."

        Design: Corner/endpoints/envelope_error_shape_on_not_found
        """
        resp = api.get_case(NON_EXISTENT_UUID, make_analyst_headers(ANALYST_1))
        body = resp.json()
        assert body["response_type"] == "error"
        assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}
        err = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        assert err["message"].strip()
        assert "total_count" not in body["meta"]

    def test_pagination_defaults_bounds_and_last_page(self, api):
        """PRD §2.3: "`limit` sets the maximum number of items returned; it
        defaults to 10 when omitted, and any value below 1 or above 100 is
        rejected with `ERR_INVALID_REQUEST`. `offset` sets the number of items
        skipped; it defaults to 0 and must be at least 0."
        PRD §2.3: "The `meta` object of a list response carries four pagination
        fields: `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/pagination_defaults_bounds_and_last_page
        """
        for i in range(12):
            make_store(store_number=f"S2{i:02d}")
        headers = make_analyst_headers(ANALYST_1)

        data, meta = validate_paginated(api.list_stores(headers))
        assert len(data) == 10, "default limit is 10"
        assert meta["total_count"] == 12
        assert meta["has_more"] is True
        assert meta["offset"] == 0

        data, meta = validate_paginated(
            api.list_stores(headers, params={"limit": 5, "offset": 10})
        )
        assert len(data) == 2, "last page holds the remainder"
        assert meta["total_count"] == 12
        assert meta["has_more"] is False

        validate_error(
            api.list_stores(headers, params={"limit": 0}),
            ApiErrorId.ERR_INVALID_REQUEST,
        )
        validate_error(
            api.list_stores(headers, params={"limit": 101}),
            ApiErrorId.ERR_INVALID_REQUEST,
        )
        validate_error(
            api.list_stores(headers, params={"offset": -1}),
            ApiErrorId.ERR_INVALID_REQUEST,
        )


class TestReverseFilters:
    def test_employees_listed_by_store_filter(self, api):
        """PRD §3.1: "Employees can be listed with `store_id` and `status`
        filters, or read individually by `employee_id`."

        Design: Corner/endpoints/fk_reverse_employees_by_store_filter
        """
        s1 = make_store()
        s2 = make_store()
        make_employee(s1["id"])
        make_employee(s1["id"])
        make_employee(s2["id"])
        headers = make_analyst_headers(ANALYST_1)
        d1, m1 = validate_paginated(
            api.list_employees(headers, params={"store_id": s1["id"]})
        )
        d2, m2 = validate_paginated(
            api.list_employees(headers, params={"store_id": s2["id"]})
        )
        assert m1["total_count"] == 2 and len(d1) == 2
        assert all(e["store_id"] == s1["id"] for e in d1)
        assert m2["total_count"] == 1 and len(d2) == 1
        assert d2[0]["store_id"] == s2["id"]
