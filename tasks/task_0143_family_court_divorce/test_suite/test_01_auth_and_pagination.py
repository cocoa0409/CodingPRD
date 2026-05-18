"""Auth, RBAC, nested-resource resolution, and pagination.

PRD §2.1 (auth + roles), §2.2 (envelopes), §2.3 (pagination), §2.4
(nested resource resolution).
"""
from __future__ import annotations

from typing import Dict

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    api_client,
    create_case_payload,
    setup_case_with_both_disclosures_accepted,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# Missing / malformed headers — PRD §2.1
# ===========================================================================
class TestMissingHeaders:
    """PRD §2.1: 'Every request must carry two HTTP headers: X-User-ID
    identifies the acting user, and X-User-Role declares the
    operational capacity in which the request is being made. Missing
    or malformed headers cause the request to be rejected with
    ERR_AUTH_MISSING (HTTP 401).'"""

    def test_no_headers_at_all_rejected(self, api):
        """PRD §2.1: 'Missing or malformed headers cause the request
        to be rejected with ERR_AUTH_MISSING (HTTP 401).'

        Claim: a request with NO X-User-ID and NO X-User-Role headers
        is rejected ERR_AUTH_MISSING with HTTP 401.
        """
        res = api.get_clock(headers={})
        validate_error(res, "ERR_AUTH_MISSING", expected_status=401)

    def test_only_user_id_present_rejected(self, api):
        """PRD §2.1: 'Every request must carry two HTTP headers'.

        Claim: omitting X-User-Role (but supplying X-User-ID) is
        ERR_AUTH_MISSING.
        """
        res = api.get_clock(headers={"X-User-ID": "anyone"})
        validate_error(res, "ERR_AUTH_MISSING", expected_status=401)

    def test_only_user_role_present_rejected(self, api):
        """PRD §2.1: 'Every request must carry two HTTP headers:
        X-User-ID identifies the acting user, and X-User-Role declares
        the operational capacity'.

        Claim: omitting X-User-ID (but supplying X-User-Role) is
        ERR_AUTH_MISSING.
        """
        res = api.get_clock(headers={"X-User-Role": "Judge"})
        validate_error(res, "ERR_AUTH_MISSING", expected_status=401)

    def test_empty_string_headers_rejected(self, api):
        """PRD §2.1: 'Missing or malformed headers cause the request
        to be rejected with ERR_AUTH_MISSING (HTTP 401).'

        Claim: empty-string header values count as malformed.
        """
        res = api.get_clock(
            headers={"X-User-ID": "", "X-User-Role": ""},
        )
        validate_error(res, "ERR_AUTH_MISSING", expected_status=401)


# ===========================================================================
# RBAC forbidden — PRD §2.1
# ===========================================================================
class TestForbidden:

    def test_petitioner_cannot_advance_clock(
        self, api, petitioner_fallback_headers,
    ):
        """PRD §2.1: 'A request whose role is recognized but is not
        permitted for the targeted endpoint (per the §4 endpoint
        table) is rejected with ERR_FORBIDDEN (HTTP 403).'
        PRD §4: POST /_clock/advance is authorised for PlatformAdmin
        only.

        Claim: Petitioner cannot advance the server clock.
        """
        res = api.advance_clock(
            {"to_timestamp": "2030-01-01T00:00:00.000Z"},
            petitioner_fallback_headers,
        )
        validate_error(res, "ERR_FORBIDDEN", expected_status=403)

    def test_judge_cannot_file_petition(self, api, judge_headers):
        """PRD §4: POST /cases is authorised for AttorneyOfRecord,
        Petitioner only.

        Claim: Judge filing a petition is ERR_FORBIDDEN.
        """
        res = api.create_case(create_case_payload(), judge_headers)
        validate_error(res, "ERR_FORBIDDEN", expected_status=403)

    def test_mediator_cannot_issue_temp_order(
        self, api, mediator_headers,
    ):
        """PRD §4: POST /cases/{caseId}/issue-temp-order is Judge-only.

        Claim: Mediator attempting to issue a temp order is
        ERR_FORBIDDEN.
        """
        res = api.issue_temp_order(
            NON_EXISTENT_UUID,
            {"temporary_order_id": NON_EXISTENT_UUID},
            mediator_headers,
        )
        # Auth priority: ERR_FORBIDDEN fires before ERR_NOT_FOUND
        # (PRD §2.11 fixes auth headers > role permission > resource
        # existence).
        validate_error(res, "ERR_FORBIDDEN", expected_status=403)

    def test_admin_cannot_create_case(self, api, admin_headers):
        """PRD §4: POST /cases roles list is AttorneyOfRecord,
        Petitioner. PlatformAdmin is not listed.

        Claim: PlatformAdmin filing a petition is ERR_FORBIDDEN.
        """
        res = api.create_case(create_case_payload(), admin_headers)
        validate_error(res, "ERR_FORBIDDEN", expected_status=403)


# ===========================================================================
# Nested resource resolution — PRD §2.4
# ===========================================================================
class TestNestedResolution:

    def test_unknown_case_id_is_not_found(self, api, judge_headers):
        """PRD §2.4: 'the caseId is resolved first, and only after the
        case is found does the server attempt to resolve the child
        identifier ... The first identifier in the path that does not
        name a real resource within its parent scope causes the
        request to fail with ERR_NOT_FOUND (HTTP 404)'.

        Claim: GET on /cases/{bogus} → ERR_NOT_FOUND.
        """
        res = api.get_case(NON_EXISTENT_UUID, judge_headers)
        validate_error(res, "ERR_NOT_FOUND", expected_status=404)

    def test_unknown_disclosure_id_under_real_case_is_not_found(
        self, api, judge_headers,
    ):
        """PRD §2.4: nested resolution returns ERR_NOT_FOUND for the
        first id that does not exist.

        Claim: real caseId + bogus disclosureId → ERR_NOT_FOUND.
        """
        ctx = setup_case_with_both_disclosures_accepted()
        case_id = ctx["case"]["id"]
        res = api.accept_disclosure(
            case_id, NON_EXISTENT_UUID, judge_headers,
        )
        validate_error(res, "ERR_NOT_FOUND", expected_status=404)


# ===========================================================================
# Pagination — PRD §2.3
# ===========================================================================
class TestPagination:
    """PRD §2.3: 'The limit parameter specifies the maximum number of
    items returned; it defaults to 10, has a minimum of 1, and a
    maximum of 100. The offset parameter specifies how many items to
    skip and defaults to 0.'"""

    def test_pagination_meta_present_and_filled(
        self, api, judge_headers,
    ):
        """PRD §2.3: 'The meta object on every list response carries
        the four pagination fields limit, offset, total_count, and
        has_more.'

        Claim: list-cases response carries meta with all four fields.
        """
        # Create at least one case so the list is non-empty.
        setup_case_with_both_disclosures_accepted()
        res = api.list_cases(judge_headers)
        data, meta = validate_paginated(res)
        assert isinstance(data, list)
        for k in ("limit", "offset", "total_count", "has_more"):
            assert k in meta, f"meta missing {k!r}; got {list(meta)}"

    def test_limit_one_returns_at_most_one(self, api, judge_headers):
        """PRD §2.3: 'The limit parameter specifies the maximum number
        of items returned'.

        Claim: with limit=1, len(data) <= 1.
        """
        for _ in range(2):
            setup_case_with_both_disclosures_accepted()
        res = api.list_cases(judge_headers, params={"limit": 1})
        data, meta = validate_paginated(res)
        assert len(data) <= 1
        assert meta["limit"] == 1

    def test_offset_past_end_returns_empty(self, api, judge_headers):
        """PRD §2.3: 'The offset parameter specifies how many items to
        skip'.

        Claim: an offset past the total returns an empty data list
        and has_more=false.
        """
        res = api.list_cases(judge_headers, params={"offset": 999999})
        data, meta = validate_paginated(res)
        assert data == []
        assert meta["has_more"] is False
