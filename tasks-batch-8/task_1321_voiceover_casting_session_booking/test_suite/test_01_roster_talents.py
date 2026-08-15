"""Talent roster: creation, shape rules, uniqueness, pagination, OCC updates."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_talent,
    create_talent,
    create_talent_payload,
    is_valid_uuid,
    make_client_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import AGENT, CD
from test_helpers.test_users import TEST_USERS


class TestTalentCreation:
    def test_talent_creation_required_fields(self, api):
        """PRD §3.1: "The new roster entry begins with `roster_status` set to
        `ACTIVE`". PRD §2.4: "a `version`, an integer beginning at 1 on creation
        and incrementing by one on every mutation of the resource."

        Design: Corner/entities/talent_creation_required_fields
        """
        resp = api.create_talent(create_talent_payload(), CD)
        assert resp.status_code == 201, f"talent creation must return 201: {resp.text}"
        data = validate_success(resp, expected_status=201)
        assert_talent(data)
        assert is_valid_uuid(data["id"])
        assert data["version"] == 1, f"version must begin at 1, got {data['version']}"
        assert data["roster_status"] == "ACTIVE"

    def test_talent_missing_required_email_returns_invalid_request(self, api):
        """PRD §2.10: "then enum and shape validity (`ERR_INVALID_REQUEST`)".
        PRD §3.1: "Registering a talent captures the artist's `stage_name`, a
        contact `email`, the `voice_profile` classification ..., the `languages`
        the artist records in ..., the artist's `union_status` ..., and
        `base_session_fee_cents`".

        Design: Corner/entities/talent_missing_required_email_returns_invalid_request
        """
        payload = create_talent_payload()
        del payload["email"]
        resp = api.create_talent(payload, CD)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_talent_default_roster_status_applied(self, api):
        """PRD §3.1: "The new roster entry begins with `roster_status` set to
        `ACTIVE`; the other two roster states, `SUSPENDED` and `OFFBOARDED`, are
        reached only through later roster updates."

        Design: Corner/entities/talent_default_roster_status_applied
        """
        resp = api.create_talent(create_talent_payload(), CD)
        data = validate_success(resp, expected_status=201)
        assert data["roster_status"] == "ACTIVE"

    def test_talent_invalid_enum_returns_invalid_request(self, api):
        """PRD §3.2: "A payload violating these shape rules — an unrecognized
        enum member, a missing `term_months` on a `TERM` project, a
        `spots_count` below 1 — is rejected with `ERR_INVALID_REQUEST`
        (HTTP 400)." PRD §2.10 lists "enum and shape validity
        (`ERR_INVALID_REQUEST`)" as a check applied to every request.

        Design: Corner/entities/talent_invalid_enum_returns_invalid_request
        """
        resp = api.create_talent(create_talent_payload(voice_profile="SUPER_DEEP"), CD)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_get_nonexistent_talent_returns_not_found(self, api):
        """PRD §2.8: "Any identifier that does not resolve to an existing
        resource produces `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/get_nonexistent_talent_returns_not_found
        """
        resp = api.get_talent(NON_EXISTENT_UUID, CD)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_duplicate_talent_email_returns_duplicate(self, api):
        """PRD §3.1: "Each talent's `email` must be unique across the roster,
        and a duplicate registration is rejected with `ERR_DUPLICATE`
        (HTTP 409)."

        Design: Corner/validations/duplicate_talent_email_returns_duplicate
        """
        first = create_talent(email="dup@example.com")
        assert first["email"] == "dup@example.com"
        resp = api.create_talent(create_talent_payload(email="dup@example.com"), CD)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE)


class TestTalentListing:
    def test_list_talents_pagination_shape(self, api):
        """PRD §2.3: "The `meta` block of a list response carries four
        pagination fields: `limit`, `offset`, `total_count`, and `has_more`,
        the last indicating whether additional results exist beyond the
        returned page."

        Design: Corner/entities/list_talents_pagination_shape
        """
        create_talent()
        create_talent()
        create_talent()
        resp = api.list_talents(CD)
        data, meta = validate_paginated(resp)
        assert len(data) == 3
        assert meta["total_count"] == 3
        assert meta["limit"] == 10, "default limit is 10"
        assert meta["offset"] == 0
        assert meta["has_more"] is False

    def test_pagination_limit_offset_interaction(self, api):
        """PRD §2.3: "List endpoints accept two query parameters: `limit`,
        defaulting to 10, with a minimum of 1 and a maximum of 100; and
        `offset`, defaulting to 0. Results are always sorted by `created_at`
        in ascending order."

        Design: Corner/cross_cutting_complexity_layers/pagination_limit_offset_interaction
        """
        create_talent()
        create_talent()
        create_talent()
        resp = api.list_talents(CD, params={"limit": 2, "offset": 1})
        data, meta = validate_paginated(resp)
        assert len(data) == 2, f"limit=2&offset=1 on 3 rows must return 2, got {len(data)}"
        assert meta["total_count"] == 3
        assert meta["has_more"] is False


class TestTalentOccUpdate:
    def test_occ_put_talent_with_correct_version_succeeds(self, api):
        """PRD §3.1: "the update is concurrency-guarded: it must carry
        `expected_talent_version` matching the talent's current `version` ...
        A successful update increments the talent's `version` by one."

        Design: Corner/cross_cutting_complexity_layers/occ_put_talent_with_correct_version_succeeds
        """
        talent = create_talent()
        assert talent["version"] == 1
        resp = api.update_talent(
            talent["id"],
            {"stage_name": "Vox2", "expected_talent_version": talent["version"]},
            CD,
        )
        data = validate_success(resp, expected_status=200)
        assert data["stage_name"] == "Vox2"
        assert data["version"] == talent["version"] + 1

    def test_put_talent_occ_version_conflict(self, api):
        """PRD §2.7: "If another writer has advanced the talent's version since
        that read, the update is rejected with `ERR_STALE_VERSION` (HTTP 412),
        preventing the client from overwriting a roster entry it has not
        observed — for example, a concurrent fee change."

        Design: Corner/endpoints/put_talent_occ_version_conflict
        """
        talent = create_talent()
        stale_version = talent["version"]
        first = api.update_talent(
            talent["id"],
            {"stage_name": "Vox2", "expected_talent_version": stale_version},
            CD,
        )
        validate_success(first, expected_status=200)
        resp = api.update_talent(
            talent["id"],
            {"stage_name": "Vox3", "expected_talent_version": stale_version},
            CD,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
