"""Auth header validation, body enum validation, 404, pagination envelope."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_artist,
    create_label,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.fixtures import ADMIN, ANR


class TestMissingAuthHeader:
    def test_create_artist_without_headers_rejected(self):
        """PRD §2.1: "A request whose headers are missing, or whose role value is
        not one of the five declared roles, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/errors/artist_create_missing_auth_header_returns_400
        """
        r = api_client.create_artist({
            "label_id": NON_EXISTENT_UUID,
            "stage_name": "NoAuth",
            "genre": "POP",
            "birth_date": "1995-04-12",
            "monthly_streams": 1,
            "social_followers": 1,
            "engagement_rate": 0.1,
            "live_draw_avg": 1,
        }, headers={})
        validate_error(r, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestInvalidEnum:
    def test_invalid_genre_rejected(self):
        """PRD §2.9: "Fifth, the request body itself is validated — required fields
        present, types correct, enum membership, and numeric ranges ...
        (`ERR_INVALID_REQUEST`)."
        PRD §3.1: "a `genre` of `POP`, `HIPHOP`, `ROCK`, `ELECTRONIC`, or `OTHER`".

        Design: Corner/errors/artist_create_invalid_enum_returns_invalid_request
        """
        label = create_label("Label X9")
        r = api_client.create_artist({
            "label_id": label["id"],
            "stage_name": "Jazz Act",
            "genre": "JAZZ",
            "birth_date": "1995-04-12",
            "monthly_streams": 1,
            "social_followers": 1,
            "engagement_rate": 0.1,
            "live_draw_avg": 1,
        }, ANR)
        validate_error(r, ApiErrorId.ERR_INVALID_REQUEST)


class TestContractNotFound:
    def test_get_nonexistent_contract_returns_404(self):
        """PRD §2.11: "Requests that target nested resources validate path
        identifiers sequentially from left to right, and the request is rejected
        with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not
        correspond to an existing resource."

        Design: Corner/entities/contract_get_not_found_returns_404
        """
        r = api_client.get_contract(NON_EXISTENT_UUID, ADMIN)
        validate_error(r, ApiErrorId.ERR_NOT_FOUND)


class TestListPagination:
    def test_limit_offset_has_more(self):
        """PRD §2.3: "The `limit` parameter sets the maximum number of items
        returned: it defaults to 10 when omitted ... The `offset` parameter sets
        the number of items to skip and defaults to 0. ... The `meta` object of a
        list response carries four pagination fields: `limit`, `offset`,
        `total_count`, and `has_more`."

        Design: Corner/endpoints/list_pagination_defaults_and_has_more
        """
        label = create_label("Label P1")
        for name in ("A1", "A2", "A3"):
            create_artist(label["id"], name, monthly_streams=100,
                          social_followers=100, engagement_rate=0.1, live_draw_avg=10)
        page1, meta1 = validate_paginated(api_client.list_artists(
            ANR, params={"label_id": label["id"], "limit": 2}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(api_client.list_artists(
            ANR, params={"label_id": label["id"], "limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False
