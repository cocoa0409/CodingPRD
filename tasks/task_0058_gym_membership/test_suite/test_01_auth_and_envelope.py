"""Auth headers, role enforcement, response envelope, pagination,
path-parameter resolution.

PRD §2.1, §2.2, §2.3, §2.6.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    PA,
    SO,
    build_user_headers,
    create_card_type_payload,
    create_member,
    create_member_payload,
    create_funded_member,
    setup_member_with_active_card,
    make_member_headers,
    make_trainer_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# Auth header presence (PRD §2.1)
# ===========================================================================
class TestAuthHeadersRequired:
    """PRD §2.1: 'Every request must carry an X-User-ID header and an
    X-User-Role header. When either is absent or the role name is
    unknown, the request is rejected with ERR_AUTH_REQUIRED.'"""

    def test_missing_both_headers_rejected(self, api):
        """PRD §2.1: 'When either is absent or the role name is unknown,
        the request is rejected with ERR_AUTH_REQUIRED.'"""
        res = api.create_card_type(create_card_type_payload(), {})
        validate_error(res, ApiErrorId.ERR_AUTH_REQUIRED.value)

    def test_missing_user_id_header_rejected(self, api):
        """PRD §2.1: 'When either is absent or the role name is unknown,
        the request is rejected with ERR_AUTH_REQUIRED.'"""
        res = api.create_card_type(
            create_card_type_payload(),
            {"X-User-Role": "PlatformAdmin"},
        )
        validate_error(res, ApiErrorId.ERR_AUTH_REQUIRED.value)

    def test_missing_role_header_rejected(self, api):
        """PRD §2.1: 'When either is absent or the role name is unknown,
        the request is rejected with ERR_AUTH_REQUIRED.'"""
        res = api.create_card_type(
            create_card_type_payload(),
            {"X-User-ID": "some-id"},
        )
        validate_error(res, ApiErrorId.ERR_AUTH_REQUIRED.value)

    def test_unknown_role_rejected(self, api):
        """PRD §2.1: 'When either is absent or the role name is unknown,
        the request is rejected with ERR_AUTH_REQUIRED.'"""
        headers = build_user_headers("some-id", "GodModeAdmin")
        res = api.create_card_type(create_card_type_payload(), headers)
        validate_error(res, ApiErrorId.ERR_AUTH_REQUIRED.value)


# ===========================================================================
# RBAC: role not permitted for endpoint (PRD §2.1)
# ===========================================================================
class TestRoleForbidden:
    """PRD §2.1: 'When the role is known but is not permitted to invoke
    the targeted endpoint, the request is rejected with ERR_FORBIDDEN.'
    """

    def test_member_cannot_create_card_type(self, api):
        """PRD §2.1: 'When the role is known but is not permitted to
        invoke the targeted endpoint, the request is rejected with
        ERR_FORBIDDEN.' Per PRD §4, POST /card-types is PlatformAdmin
        only."""
        member = create_member()
        res = api.create_card_type(
            create_card_type_payload(),
            make_member_headers(member["id"]),
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)

    def test_staff_ops_cannot_create_card_type(self, api):
        """PRD §4: POST /card-types is authorized for PlatformAdmin
        only; PRD §2.1: 'When the role is known but is not permitted to
        invoke the targeted endpoint, the request is rejected with
        ERR_FORBIDDEN.'"""
        res = api.create_card_type(create_card_type_payload(), SO)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)

    def test_member_cannot_open_payout(self, api):
        """PRD §4: POST /payouts is PlatformAdmin only."""
        member = create_member()
        res = api.open_payout(
            {"cycle_start": "2026-01-01T00:00:00.000Z",
             "cycle_end": "2026-04-01T00:00:00.000Z"},
            make_member_headers(member["id"]),
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# Member ownership (PRD §2.1)
# ===========================================================================
class TestMemberOwnership:
    """PRD §2.1: 'ownership checks on any resource that references a
    Member compare the resource's foreign-key field ... to X-User-ID,
    and a mismatch is rejected with ERR_FORBIDDEN.'"""

    def test_member_cannot_read_other_members_card(self, api):
        """PRD §2.1: 'ownership checks on any resource that references
        a Member compare the resource's foreign-key field ... to
        X-User-ID, and a mismatch is rejected with ERR_FORBIDDEN.'"""
        _, holder, card = setup_member_with_active_card()
        # Another member calls GET /cards/{holder's card}.
        intruder = create_member()
        res = api.get_card(card["id"], make_member_headers(intruder["id"]))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)

    def test_member_cannot_recharge_other_members_wallet(self, api):
        """PRD §2.1: 'a mismatch is rejected with ERR_FORBIDDEN.'"""
        target = create_member()
        intruder = create_member()
        res = api.recharge_wallet(
            target["id"], {"amount_cents": 30_000},
            make_member_headers(intruder["id"]),
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# Response envelope (PRD §2.2)
# ===========================================================================
class TestSuccessEnvelope:
    """PRD §2.2: 'All successful API responses (those with 2xx status
    codes) follow this standard envelope format in their JSON body.'"""

    def test_create_card_type_returns_envelope(self, api):
        """PRD §2.2: standard envelope with meta + response_type +
        data."""
        res = api.create_card_type(
            create_card_type_payload(code="CT_ENV01"),
            PA,
        )
        data = validate_success(res, expected_status=201)
        assert "id" in data and "code" in data, (
            f"data must carry the created CardType; got {data!r}"
        )


# ===========================================================================
# Path-parameter resolution (PRD §2.6)
# ===========================================================================
class TestNotFound:
    """PRD §2.6: 'If any path-parameter id along the chain does not
    resolve, the response is ERR_NOT_FOUND with HTTP 404.'"""

    def test_get_member_nonexistent_id_returns_404(self, api):
        """PRD §2.6: 'If any path-parameter id along the chain does not
        resolve, the response is ERR_NOT_FOUND with HTTP 404.'"""
        res = api.get_member(NON_EXISTENT_UUID, PA)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)

    def test_get_card_nonexistent_id_returns_404(self, api):
        """PRD §2.6: 'If any path-parameter id along the chain does not
        resolve, the response is ERR_NOT_FOUND with HTTP 404.'"""
        res = api.get_card(NON_EXISTENT_UUID, PA)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)

    def test_body_fk_nonexistent_returns_404(self, api):
        """PRD §2.6: 'Foreign-key body fields — including card_type_id,
        holder_member_id, member_id, trainer_id, slot_id, package_id,
        class_id, card_id, and to_member_id — are likewise checked for
        existence, and unresolved references return ERR_NOT_FOUND.'"""
        member = create_member()
        res = api.issue_card(
            {"card_type_id": NON_EXISTENT_UUID,
             "holder_member_id": member["id"]},
            SO,
        )
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)


# ===========================================================================
# Pagination (PRD §2.3)
# ===========================================================================
class TestPagination:
    """PRD §2.3: 'List endpoints accept two query parameters, limit and
    offset.'"""

    def test_default_pagination_limit_is_10(self, api):
        """PRD §2.3: 'limit defaults to 10.'"""
        res = api.list_card_types(PA)
        data, meta = validate_paginated(res)
        assert meta.get("limit") == 10, (
            f"PRD §2.3 'limit defaults to 10'; got {meta.get('limit')!r}"
        )

    def test_limit_above_max_rejected(self, api):
        """PRD §2.3: 'limit defaults to 10, has a minimum of 1, and a
        maximum of 100; values outside this band are rejected with
        ERR_VALIDATION.'"""
        res = api.list_card_types(PA, params={"limit": 200})
        validate_error(res, ApiErrorId.ERR_VALIDATION.value)

    def test_limit_below_min_rejected(self, api):
        """PRD §2.3: 'values outside this band are rejected with
        ERR_VALIDATION.'"""
        res = api.list_card_types(PA, params={"limit": 0})
        validate_error(res, ApiErrorId.ERR_VALIDATION.value)
