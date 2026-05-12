"""Authentication headers, role permission, response envelope, pagination.

PRD §2.1 (headers and roles), §2.2 (envelope), §2.3 (pagination),
§2.5 (left-to-right path resolution), §2.9 (validation ordering).
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ADMIN,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    build_user_headers,
    create_lab_payload,
    create_lab_with_owner,
    create_user_payload,
    create_verified_user,
    make_lab_owner_headers,
    make_platform_admin_headers,
    make_user_headers,
    register_equipment,
    setup_basic_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# Header presence  (PRD §2.1 / §2.9 priority 1)
# ===========================================================================
class TestAuthHeadersRequired:
    """PRD §2.1: 'Every request must carry two mandatory headers:
    X-User-ID identifies the acting principal, and X-User-Role declares
    the operational capacity in which the request is made. When either
    header is missing or unparseable the request is rejected with
    ERR_MISSING_AUTH and a 401 status'.
    """

    def test_missing_both_headers_rejected(self, api):
        """PRD §2.1: 'When either header is missing or unparseable the
        request is rejected with ERR_MISSING_AUTH and a 401 status'."""
        res = api.create_lab(
            create_lab_payload(contact_user_id="any"), {},
        )
        validate_error(res, ApiErrorId.ERR_MISSING_AUTH.value)

    def test_missing_user_id_header_rejected(self, api):
        """PRD §2.1: 'When either header is missing or unparseable the
        request is rejected with ERR_MISSING_AUTH and a 401 status'."""
        res = api.create_lab(
            create_lab_payload(contact_user_id="any"),
            {"X-User-Role": "PlatformAdmin"},
        )
        validate_error(res, ApiErrorId.ERR_MISSING_AUTH.value)

    def test_missing_role_header_rejected(self, api):
        """PRD §2.1: 'When either header is missing or unparseable the
        request is rejected with ERR_MISSING_AUTH and a 401 status'."""
        res = api.create_lab(
            create_lab_payload(contact_user_id="any"),
            {"X-User-ID": "some-id"},
        )
        validate_error(res, ApiErrorId.ERR_MISSING_AUTH.value)

    def test_empty_user_id_header_rejected(self, api):
        """PRD §2.1: 'When either header is missing or unparseable the
        request is rejected with ERR_MISSING_AUTH and a 401 status'."""
        res = api.create_lab(
            create_lab_payload(contact_user_id="any"),
            {"X-User-ID": "", "X-User-Role": "PlatformAdmin"},
        )
        validate_error(res, ApiErrorId.ERR_MISSING_AUTH.value)


# ===========================================================================
# Role permission  (PRD §2.1 / §2.9 priority 2)
# ===========================================================================
class TestRoleAuthorization:
    """PRD §2.1: 'when both are present but the declared role is not
    permitted to perform the requested operation under the role matrix
    below, the request is rejected with ERR_FORBIDDEN at 403'.
    """

    def test_user_role_cannot_create_lab(self, api):
        """PRD §2.1: 'when both are present but the declared role is not
        permitted to perform the requested operation under the role
        matrix below, the request is rejected with ERR_FORBIDDEN at 403'.
        """
        res = api.create_lab(
            create_lab_payload(contact_user_id="any"),
            TEST_USERS["user_headers"],
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)

    def test_lab_owner_cannot_create_user(self, api):
        """PRD §2.1: 'when both are present but the declared role is not
        permitted to perform the requested operation under the role
        matrix below, the request is rejected with ERR_FORBIDDEN at 403'.
        """
        res = api.create_user(
            create_user_payload(),
            TEST_USERS["lab_owner_headers"],
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)

    def test_user_role_cannot_advance_clock(self, api):
        """PRD §4: 'POST /_clock/advance ... Authorized Role(s): PlatformAdmin'."""
        res = api.advance_clock(
            {"target_time": "2026-05-12T00:00:00.000Z"},
            TEST_USERS["user_headers"],
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)

    def test_user_role_cannot_settle_lab(self, api):
        """PRD §4: 'POST /labs/{lab_id}/settle ... Authorized Role(s):
        PlatformAdmin'."""
        res = api.settle_lab(
            NON_EXISTENT_UUID, TEST_USERS["user_headers"],
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)

    def test_user_role_cannot_register_equipment(self, api):
        """PRD §4: 'POST /equipment ... Authorized Role(s): LabOwner'."""
        from test_helpers import create_equipment_payload
        res = api.create_equipment(
            create_equipment_payload(lab_id=NON_EXISTENT_UUID),
            TEST_USERS["user_headers"],
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# Path-segment NOT_FOUND  (PRD §2.5 / §2.9 priority 3)
# ===========================================================================
class TestPathSegmentNotFound:
    """PRD §2.5: 'Path segments are resolved strictly left to right ...
    The first segment that fails to resolve yields ERR_NOT_FOUND (404)
    without further checks'.
    """

    def test_get_nonexistent_lab(self, api, admin_headers):
        res = api.get_lab(NON_EXISTENT_UUID, admin_headers)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)

    def test_get_nonexistent_equipment(self, api, admin_headers):
        res = api.get_equipment(NON_EXISTENT_UUID, admin_headers)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)

    def test_get_nonexistent_user(self, api, admin_headers):
        res = api.get_user(NON_EXISTENT_UUID, admin_headers)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)

    def test_get_nonexistent_reservation(self, api, admin_headers):
        res = api.get_reservation(NON_EXISTENT_UUID, admin_headers)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)

    def test_check_in_nonexistent_reservation(self, api):
        """PRD §2.5: path id must resolve before further checks."""
        headers = make_user_headers(NON_EXISTENT_UUID)
        res = api.check_in_reservation(NON_EXISTENT_UUID, headers)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)


# ===========================================================================
# Body foreign-key NOT_FOUND  (PRD §2.5 / §2.9 priority 4)
# ===========================================================================
class TestBodyForeignKeyNotFound:
    """PRD §2.5: 'Body-referenced foreign keys — authorization_id on a
    reservation create, lab_id on equipment create — are resolved after
    path resolution; an unknown body foreign key likewise yields
    ERR_NOT_FOUND'.
    """

    def test_register_equipment_with_unknown_lab(self, api):
        """PRD §2.5: 'an unknown body foreign key likewise yields
        ERR_NOT_FOUND'."""
        from test_helpers import create_equipment_payload
        # Caller is a real LabOwner of SOME lab — but the body lab_id
        # references a non-existent row. Build a real owner so role check
        # passes, then point lab_id elsewhere.
        owner = create_verified_user()
        headers = make_lab_owner_headers(owner["id"])
        res = api.create_equipment(
            create_equipment_payload(lab_id=NON_EXISTENT_UUID),
            headers,
        )
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)


# ===========================================================================
# Success envelope  (PRD §2.2)
# ===========================================================================
class TestSuccessEnvelope:
    """PRD §2.2: 'All successful API responses (those with 2xx status
    codes) follow this standard envelope format' (meta + response_type +
    data, with api_request_id and api_request_timestamp in meta).
    """

    def test_envelope_has_meta_and_data(self, api, admin_headers):
        """PRD §2.2: meta.api_request_id starts with 'req_'; data carries
        the resource; api_request_timestamp is ISO 8601 UTC."""
        lab, _ = create_lab_with_owner()
        body = api.get_lab(lab["id"], admin_headers).json()
        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"].startswith("req_")
        assert "api_request_timestamp" in body["meta"]
        assert body["data"]["id"] == lab["id"]


# ===========================================================================
# Pagination  (PRD §2.3)
# ===========================================================================
class TestPagination:
    """PRD §2.3: 'The limit parameter defaults to 10, with a minimum of 1
    and a maximum of 100; values outside that range yield ERR_BAD_REQUEST.
    The offset parameter defaults to 0 ... Every list response includes
    limit, offset, total_count, and has_more in the meta envelope. The
    has_more flag is true if and only if offset + limit < total_count'.
    """

    def test_default_limit_meta_present(self, api):
        """PRD §2.3: 'Every list response includes limit, offset,
        total_count, and has_more in the meta envelope'."""
        s = setup_basic_scenario()
        data, meta = validate_paginated(api.list_equipment(
            make_lab_owner_headers(s["owner_user"]["id"]),
        ))
        assert "limit" in meta and "offset" in meta
        assert "total_count" in meta and "has_more" in meta
        assert meta["limit"] == 10

    def test_limit_above_max_rejected(self, api):
        """PRD §2.3: 'maximum of 100; values outside that range yield
        ERR_BAD_REQUEST'."""
        res = api.list_equipment(ADMIN, params={"limit": 101})
        validate_error(res, ApiErrorId.ERR_BAD_REQUEST.value)

    def test_limit_below_min_rejected(self, api):
        """PRD §2.3: 'minimum of 1 ... yield ERR_BAD_REQUEST'."""
        res = api.list_equipment(ADMIN, params={"limit": 0})
        validate_error(res, ApiErrorId.ERR_BAD_REQUEST.value)

    def test_has_more_iff_offset_plus_limit_less_than_total(self, api):
        """PRD §2.3: 'The has_more flag is true if and only if
        offset + limit < total_count'."""
        s = setup_basic_scenario()
        # Add two more equipments so we exceed limit=1.
        register_equipment(lab=s["lab"], owner_user=s["owner_user"])
        register_equipment(lab=s["lab"], owner_user=s["owner_user"])
        owner_h = make_lab_owner_headers(s["owner_user"]["id"])
        data, meta = validate_paginated(api.list_equipment(
            owner_h, params={"limit": 1, "offset": 0},
        ))
        assert meta["limit"] == 1
        assert meta["offset"] == 0
        assert meta["has_more"] == (meta["offset"] + meta["limit"]
                                    < meta["total_count"])
