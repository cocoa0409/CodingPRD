"""Third-party registration fields, defaults, existence checks, and listing."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_country_risk_profile,
    assert_third_party,
    country_profile_payload,
    create_country,
    is_iso8601_timestamp,
    is_valid_uuid,
    sponsor_headers,
    third_party_payload,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import (
    admin_headers,
    officer_headers,
)


class TestRegistrationFields:
    def test_third_party_create_missing_country_code_rejected(self, api, sponsor_headers):
        """PRD §3.2: "A `BusinessSponsor` begins onboarding by registering the
        counterparty with its `legal_name`, `country_code`, `industry`, and
        `government_touchpoint`."
        PRD §2.9: "Eighth, business constraints: `ERR_SOD_VIOLATION`,
        `ERR_NOT_RESOURCE_OWNER`, `ERR_CLAUSE_SET_INCOMPLETE`,
        `ERR_DUPLICATE_ACTIVE_CYCLE`, `ERR_FINDINGS_PENDING`, and the
        malformed-request catch-all `ERR_VALIDATION` (HTTP 400)."

        Design: Corner/entities/third_party_create_missing_required_country_code_rejected
        """
        payload = {
            "legal_name": "No Country Co",
            "industry": "TECHNOLOGY",
            "government_touchpoint": "NONE",
        }
        resp = api.create_third_party(payload, sponsor_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

        list_resp = api.list_third_parties(officer_headers())
        _, meta = validate_paginated(list_resp)
        assert meta["total_count"] == 0, "no ThirdParty may be persisted on a 400"

    def test_country_profile_sanctioned_defaults_false(self, api, admin_headers):
        """PRD §3.1: "Each country risk profile records a `country_code` (an ISO
        3166-1 alpha-2 code, unique across profiles — the server refuses
        duplicates), a `cpi_score` (the Corruption Perceptions Index from 0 to
        100, where higher means cleaner), and a `sanctioned` flag that defaults
        to false."

        Design: Corner/entities/country_profile_sanctioned_defaults_false
        """
        resp = api.create_country_profile(
            country_profile_payload(country_code="CH", cpi_score=80), admin_headers
        )
        data = validate_success(resp, 201)
        assert_country_risk_profile(data)
        assert data["sanctioned"] is False, "sanctioned default must be false"

    def test_third_party_created_in_draft_with_null_scores(self, api, admin_headers, sponsor_headers):
        """PRD §3.2: "The server stamps `sponsor_user_id` from the caller's header,
        sets `onboarding_status` to `DRAFT`, initializes
        `gov_gift_rolling_12m_cents` to 0, and leaves `risk_score_provisional`,
        `risk_score_final`, `risk_tier`, `approval_tier_snapshot`,
        `approved_policy_id`, and `diligence_expires_at` empty until the
        workflows below produce them."
        PRD §2.4: "The `version` field is an integer optimistic-concurrency
        counter, incremented by one at each mutation point called out in §3."
        PRD §2.5: "At startup, before any operator intervention, the clock reads
        exactly 2026-05-01T00:00:00Z."

        Design: Corner/entities/third_party_created_in_draft_with_null_scores_and_system_fields
        """
        create_country("CH", 80)
        resp = api.create_third_party(
            third_party_payload(legal_name="CH Tech GmbH", country_code="CH",
                                industry="TECHNOLOGY", government_touchpoint="NONE"),
            sponsor_headers,
        )
        data = validate_success(resp, 201)
        assert_third_party(data)
        assert data["onboarding_status"] == "DRAFT"
        assert data["risk_score_provisional"] is None
        assert data["risk_score_final"] is None
        assert data["risk_tier"] is None
        assert data["version"] == 1
        assert is_valid_uuid(data["id"])
        assert is_iso8601_timestamp(data["created_at"])
        assert data["created_at"].startswith("2026-05-01T00:00:00"), (
            "created_at is pinned to the logical clock startup default"
        )
        assert data["sponsor_user_id"] == "u_sp1"
        assert data["gov_gift_rolling_12m_cents"] == 0

    def test_third_party_invalid_industry_rejected(self, api, admin_headers, sponsor_headers):
        """PRD §3.2: "The `industry` is one of `TECHNOLOGY` (industry score 20),
        `LOGISTICS` (40), `CONSULTING` (60), `CONSTRUCTION` (70), or
        `GOVERNMENT_RELATIONS` (90), and the `government_touchpoint` is one of
        `NONE` (touchpoint score 0), `INDIRECT` (50), or `DIRECT` (100) — the
        parenthesized values are the scores the weighted formula consumes."
        PRD §2.9: "Eighth, business constraints: `ERR_SOD_VIOLATION`,
        `ERR_NOT_RESOURCE_OWNER`, `ERR_CLAUSE_SET_INCOMPLETE`,
        `ERR_DUPLICATE_ACTIVE_CYCLE`, `ERR_FINDINGS_PENDING`, and the
        malformed-request catch-all `ERR_VALIDATION` (HTTP 400)."

        Design: Corner/entities/third_party_invalid_enum_industry_rejected
        """
        create_country("CH", 80)
        resp = api.create_third_party(
            third_party_payload(legal_name="Bad Industry Co", country_code="CH",
                                industry="FINANCE", government_touchpoint="NONE"),
            sponsor_headers,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_third_party_create_unknown_country_code_not_found(self, api, sponsor_headers):
        """PRD §3.2: "The `country_code` must resolve to an existing country risk
        profile, else the create fails with `ERR_NOT_FOUND`."

        Design: Corner/entities/third_party_create_unknown_country_code_not_found
        """
        resp = api.create_third_party(
            third_party_payload(legal_name="Nowhere Co", country_code="ZZ",
                                industry="TECHNOLOGY", government_touchpoint="NONE"),
            sponsor_headers,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_get_nonexistent_third_party_returns_not_found(self, api, officer_headers):
        """PRD §2.4: "Routes that address a sub-resource through its parent
        validate path parameters left to right: each identifier must resolve to
        an existing record before the next segment is examined, and the first
        unresolved identifier yields `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/get_nonexistent_third_party_returns_not_found
        """
        resp = api.get_third_party(NON_EXISTENT_UUID, officer_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestListing:
    def test_third_parties_list_filter_and_pagination(self, api, admin_headers,
                                                      sponsor_headers, officer_headers):
        """PRD §2.3: "List endpoints accept two query parameters: `limit`,
        defaulting to 10 with a minimum of 1 and a maximum of 100, and `offset`,
        defaulting to 0. Every list response carries `limit`, `offset`,
        `total_count`, and `has_more` in its `meta` object. All list results are
        ordered by `created_at` ascending, so the oldest record appears first."
        PRD §3.2: "The third-party collection can be listed with the filters
        `onboarding_status`, `risk_tier`, `country_code`, and `sponsor_user_id`."

        Design: Corner/entities/third_parties_list_filter_and_pagination
        """
        create_country("CH", 80)
        names = ["TP One", "TP Two", "TP Three"]
        variants = [("TECHNOLOGY", "NONE"), ("LOGISTICS", "INDIRECT"), ("CONSULTING", "DIRECT")]
        for name, (industry, touchpoint) in zip(names, variants):
            resp = api.create_third_party(
                third_party_payload(legal_name=name, country_code="CH",
                                    industry=industry, government_touchpoint=touchpoint),
                sponsor_headers,
            )
            validate_success(resp, 201)

        page1_resp = api.list_third_parties(
            officer_headers, params={"onboarding_status": "DRAFT", "limit": 2, "offset": 0}
        )
        rows1, meta1 = validate_paginated(page1_resp)
        assert len(rows1) == 2, f"page 1 must carry exactly 2 rows, got {len(rows1)}"
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2
        assert meta1["offset"] == 0

        page2_resp = api.list_third_parties(
            officer_headers, params={"onboarding_status": "DRAFT", "limit": 2, "offset": 2}
        )
        rows2, meta2 = validate_paginated(page2_resp)
        assert len(rows2) == 1, f"page 2 must carry exactly 1 row, got {len(rows2)}"
        assert meta2["has_more"] is False

        ordered_names = [r["legal_name"] for r in rows1 + rows2]
        assert ordered_names == names, (
            f"created_at ASC ordering must read TP One, TP Two, TP Three; got {ordered_names}"
        )
