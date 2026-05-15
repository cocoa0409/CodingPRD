"""Client CRUD, response envelope conformance, and optimistic concurrency
on Client (PRD §2.2, §2.4, §3.1)."""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    assert_client,
    assert_version_incremented,
    create_client,
    create_client_payload,
    update_client_payload,
    validate_error,
    validate_success,
)


class TestClientCRUD:
    def test_create_client_returns_201_and_correct_shape(
        self, api, lab_manager_headers,
    ):
        """PRD §3.1: 'a LabManager, who registers a Client by providing
        a name and a contact_email.'

        Claim: POST /clients returns 201 with the full Client envelope.
        """
        payload = create_client_payload()
        resp = api.create_client(payload, lab_manager_headers)
        data = validate_success(resp, expected_status=201)
        assert_client(data)
        assert data["name"] == payload["name"]
        assert data["contact_email"] == payload["contact_email"]

    def test_new_client_has_zero_balances(self, api, lab_manager_headers):
        """PRD §3.1: 'Each Client carries two server-maintained money
        fields ... Both default to zero on registration.'

        Claim: a freshly-created client has deposit_balance_cents=0 and
        outstanding_balance_cents=0.
        """
        resp = api.create_client(create_client_payload(), lab_manager_headers)
        data = validate_success(resp, expected_status=201)
        assert data["deposit_balance_cents"] == 0
        assert data["outstanding_balance_cents"] == 0

    def test_new_client_version_is_one(self, api, lab_manager_headers):
        """PRD §2.4: 'an integer version that starts at 1 and is
        incremented by 1 on every mutation that changes a stored field.'

        Claim: a newly created Client has version == 1.
        """
        resp = api.create_client(create_client_payload(), lab_manager_headers)
        data = validate_success(resp, expected_status=201)
        assert data["version"] == 1

    def test_get_client_returns_persisted_row(self, api, lab_manager_headers):
        """PRD §3.12: 'Read endpoints on individual resources return the
        full current row.'

        Claim: GET /clients/{id} returns the row matching what POST
        returned.
        """
        created = create_client()
        resp = api.get_client(created["id"], lab_manager_headers)
        data = validate_success(resp)
        assert data["id"] == created["id"]
        assert data["name"] == created["name"]

    def test_get_unknown_client_returns_not_found(
        self, api, lab_manager_headers,
    ):
        """PRD §2.6: 'the first segment whose id does not match an
        existing resource yields ERR_NOT_FOUND (HTTP 404).'

        Claim: GET /clients/{non-existent} yields ERR_NOT_FOUND.
        """
        resp = api.get_client(NON_EXISTENT_UUID, lab_manager_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


class TestClientUpdateOCC:
    """PRD §2.4 optimistic concurrency on PATCH endpoints."""

    def test_update_with_current_version_succeeds(
        self, api, lab_manager_headers,
    ):
        """PRD §2.4: 'Successful PATCH operations bump version by one
        and refresh updated_at.'

        Claim: PATCH /clients/{id} with the current version succeeds
        and bumps version to 2.
        """
        created = create_client()
        payload = update_client_payload(
            version=created["version"],
            contact_email="new@example.test",
        )
        resp = api.update_client(created["id"], payload, lab_manager_headers)
        data = validate_success(resp)
        assert_version_incremented(data["version"], created["version"])
        assert data["contact_email"] == "new@example.test"

    def test_update_with_stale_version_returns_version_conflict(
        self, api, lab_manager_headers,
    ):
        """PRD §2.4: 'If the supplied version does not equal the current
        row version, the request is rejected with ERR_VERSION_CONFLICT
        (HTTP 409).'

        Claim: PATCH with a stale version yields ERR_VERSION_CONFLICT.
        """
        created = create_client()
        # First PATCH succeeds and moves version → 2.
        api.update_client(
            created["id"],
            update_client_payload(version=created["version"],
                                  contact_email="first@example.test"),
            lab_manager_headers,
        )
        # Second PATCH using the original version is now stale.
        resp = api.update_client(
            created["id"],
            update_client_payload(version=created["version"],
                                  contact_email="second@example.test"),
            lab_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_VERSION_CONFLICT.value)

    def test_update_omitting_version_is_validation_error(
        self, api, lab_manager_headers,
    ):
        """PRD §2.4: 'omitting the field on those endpoints is itself a
        malformed request rejected with ERR_VALIDATION.'

        Claim: PATCH /clients/{id} without a version field is
        ERR_VALIDATION.
        """
        created = create_client()
        resp = api.update_client(
            created["id"], {"contact_email": "x@example.test"},
            lab_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


class TestPaginationBounds:
    """PRD §2.3 pagination contract."""

    @pytest.mark.parametrize("limit,offset,expected", [
        (0, 0, ApiErrorId.ERR_INVALID_PAGINATION),
        (101, 0, ApiErrorId.ERR_INVALID_PAGINATION),
        (10, -1, ApiErrorId.ERR_INVALID_PAGINATION),
    ])
    def test_out_of_range_pagination_rejected(
        self, api, lab_manager_headers, limit, offset, expected,
    ):
        """PRD §2.3: 'The default limit is 10; the minimum is 1 and the
        maximum is 100. The default offset is 0 and the minimum is 0.
        If a caller supplies a value outside these bounds, the request
        is rejected with ERR_INVALID_PAGINATION (HTTP 400).'

        Claim: out-of-bounds limit/offset returns ERR_INVALID_PAGINATION.
        """
        resp = api.list_testers(
            lab_manager_headers, params={"limit": limit, "offset": offset},
        )
        validate_error(resp, expected.value)

    def test_list_testers_with_valid_pagination_returns_envelope(
        self, api, lab_manager_headers,
    ):
        """PRD §2.3: 'Each list response surfaces four pagination fields
        in the meta envelope: limit, offset, total_count, and has_more.'

        Claim: GET /testers returns the four meta fields.
        """
        from test_helpers import validate_paginated
        resp = api.list_testers(
            lab_manager_headers, params={"limit": 1, "offset": 0},
        )
        data_list, meta = validate_paginated(resp)
        assert isinstance(data_list, list)
        for k in ("limit", "offset", "total_count", "has_more"):
            assert k in meta, f"meta missing key {k}"
