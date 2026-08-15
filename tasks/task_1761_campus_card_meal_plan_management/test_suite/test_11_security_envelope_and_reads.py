"""Cross-cutting security: auth context, role gating, ownership, not-found, and
the pagination envelope."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_card_holder_payload,
    create_holder,
    issue_card,
    make_cardholder_headers,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["card_office_admin_headers"]
DINING = TEST_USERS["dining_manager_headers"]


class TestAuthContext:
    def test_missing_auth_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role string
        the system does not declare, is rejected with `ERR_MISSING_AUTH_CONTEXT`
        (HTTP 401)."

        Design: Corner/validations/missing_auth_headers_returns_unauthenticated
        """
        resp = api.list_terms(None)
        validate_error(resp, ApiErrorId.ERR_MISSING_AUTH_CONTEXT)

    def test_role_not_permitted_returns_forbidden(self, api):
        """PRD §2.1: "If the headers are well-formed but the named role is not in
        the calling endpoint's authorized role list, the request is rejected with
        `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

        Design: Corner/validations/role_not_permitted_returns_forbidden
        """
        holder = create_holder(university_id="U92001", full_name="Lou Role",
                               email="lou@x.edu")
        resp = api.create_term(
            {"term_code": "T-ROLE", "name": "X",
             "start_date": "2026-08-24T00:00:00Z",
             "end_date": "2026-12-13T23:59:59Z",
             "add_drop_deadline": "2026-09-20T23:59:59Z",
             "total_weeks": 16, "proration_mode": "WEEKLY"},
            make_cardholder_headers(holder["id"]))
        validate_error(resp, ApiErrorId.ERR_ROLE_NOT_PERMITTED)

    def test_role_check_beats_existence_check_rejected(self, api):
        """PRD §2.10: "When a request violates several rules at once, the error
        that surfaces is determined by a fixed priority order, evaluated from first
        to last" — item 2 "**Role permission** — the caller's role is in the
        endpoint's authorized list, else `ERR_ROLE_NOT_PERMITTED` (403)" precedes
        item 5 "**Path existence** — path identifiers resolve to existing
        resources, validated left to right, else `ERR_NOT_FOUND` (404)".

        Design: Corner/validations/role_check_beats_existence_check_rejected
        """
        holder = create_holder(university_id="U92002", full_name="Max Prio",
                               email="max@x.edu")
        resp = api.open_term(str(NON_EXISTENT_UUID),
                             make_cardholder_headers(holder["id"]))
        validate_error(resp, ApiErrorId.ERR_ROLE_NOT_PERMITTED)


class TestBodyValidation:
    def test_missing_required_field_returns_validation_error(self, api):
        """PRD §2.10: "**Body well-formedness** — required fields present, types
        correct, enum values in range, `amount_cents` positive (exactly zero for
        a meal swipe), end after start, dates parseable, and `rejection_reason` or
        `denial_reason` present where the action requires one, else
        `ERR_VALIDATION` (400)."

        Design: Corner/validations/missing_required_field_returns_validation_error
        """
        resp = api.create_card_holder(
            {"university_id": "U92003", "full_name": "No Email",
             "holder_type": "STAFF", "housing_status": "OFF_CAMPUS"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)
        holders, _ = validate_paginated(
            api.list_card_holders(ADMIN, {"university_id": "U92003"}))
        assert holders == []


class TestNotFound:
    def test_nonexistent_resource_returns_not_found(self, api):
        """PRD §2.10: "**Path existence** — path identifiers resolve to existing
        resources, validated left to right, else `ERR_NOT_FOUND` (404)."

        Design: Corner/entities/nonexistent_resource_returns_not_found
        """
        missing_card = api.get_card(str(NON_EXISTENT_UUID), ADMIN)
        validate_error(missing_card, ApiErrorId.ERR_NOT_FOUND)
        missing_nested = api.list_enrollment_change_requests(
            str(NON_EXISTENT_UUID), DINING)
        validate_error(missing_nested, ApiErrorId.ERR_NOT_FOUND)


class TestOwnership:
    def test_entity_backed_ownership_enforced(self, api):
        """PRD §2.1: "A holder calling an owner-scoped endpoint against another
        holder's resource — including list filters that name another holder's id —
        is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."
        PRD §3.1: "a holder record can be read by administrative roles, and a
        `CardHolder` caller may read only their own record."

        Design: Corner/rbac/entity_backed_ownership_enforced
        """
        set_clock("2026-08-25T09:00:00Z")
        ha = create_holder(university_id="U94002", full_name="Ann A",
                           email="ann@x.edu", holder_type="STUDENT_RESIDENT",
                           housing_status="ON_CAMPUS")
        hb = create_holder(university_id="U94003", full_name="Ben B",
                           email="ben@x.edu", holder_type="STUDENT_COMMUTER",
                           housing_status="COMMUTER")
        card_a = issue_card(ha["id"])

        card_read = api.get_card(card_a["id"], make_cardholder_headers(hb["id"]))
        validate_error(card_read, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
        holder_read = api.get_card_holder(ha["id"],
                                          make_cardholder_headers(hb["id"]))
        validate_error(holder_read, ApiErrorId.ERR_NOT_RESOURCE_OWNER)


class TestCrossEntityGuards:
    def test_activate_card_for_withdrawn_holder_rejected(self, api):
        """PRD §3.1: "Three preconditions guard it: the holder's `status` must be
        `ACTIVE` (otherwise `ERR_HOLDER_NOT_ACTIVE`)"

        Design: Corner/validations/activate_card_for_withdrawn_holder_rejected
        """
        set_clock("2026-08-25T09:00:00Z")
        holder = create_holder(university_id="U92019", full_name="Cy Withdrawn",
                               email="cy@x.edu", holder_type="STUDENT_RESIDENT",
                               housing_status="ON_CAMPUS")
        card = issue_card(holder["id"])
        validate_success(api.withdraw_card_holder(holder["id"], ADMIN), 200)

        resp = api.activate_card(card["id"], {"allow_provisional": True}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_HOLDER_NOT_ACTIVE)
        still = get_card(api, card["id"])
        assert still["lifecycle_status"] == "PENDING_PHOTO"


class TestPaginationEnvelope:
    def test_list_pagination_limit_offset_has_more(self, api):
        """PRD §2.3: "The `meta` object of every list response carries the
        pagination fields `limit`, `offset`, `total_count`, and `has_more`."
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`." and "The `response_type` is
        either "object" for a single resource or "array" for a list of resources."

        Design: Corner/endpoints/list_pagination_limit_offset_has_more
        """
        for i in range(1, 4):
            api.create_card_holder(
                create_card_holder_payload(
                    university_id=f"U9300{i}", full_name=f"P {i}",
                    email=f"p{i}@x.edu", holder_type="STAFF",
                    housing_status="OFF_CAMPUS"), ADMIN)

        page1_resp = api.list_card_holders(ADMIN, {"limit": 2, "offset": 0})
        page1, meta1 = validate_paginated(page1_resp)
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2 and meta1["offset"] == 0
        body = page1_resp.json()
        assert body["response_type"] == "array"
        assert body["meta"]["api_request_id"].startswith("req_")

        page2, meta2 = validate_paginated(
            api.list_card_holders(ADMIN, {"limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False


def get_card(api, card_id):
    from test_helpers import get_success_data
    return get_success_data(api.get_card(card_id, ADMIN))
