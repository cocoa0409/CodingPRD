"""Onboarding defaults, computed fields, envelope shape, and pagination."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    is_valid_uuid, is_iso8601_timestamp,
    ApiErrorId, TEST_USERS, make_iso_headers, make_trader_headers,
    assert_market_participant, assert_generator_asset, assert_participant_credit_invariants,
)
from test_helpers.fixtures import (
    ISO, create_participant, create_generator, create_operating_day,
    setup_participant_generator, set_clock,
)

NON_EXISTENT = "00000000-0000-0000-0000-000000000000"


class TestParticipantDefaults:
    def test_participant_create_applies_defaults_investment_grade(self, api):
        """PRD §3.1: "A new participant starts `ACTIVE`, with
        `posted_collateral_cents` zero and `collateral_requirement_cents` zero,
        and its `unsecured_allowance_cents` fixed by tier per §2.8."

        Design: Corner/entities/participant_create_applies_defaults
        """
        resp = api.create_participant(
            {"company_name": "Defaults Co", "credit_rating_tier": "INVESTMENT_GRADE"}, ISO)
        data = validate_success(resp, expected_status=201)
        assert_market_participant(data)
        assert data["status"] == "ACTIVE"
        assert data["posted_collateral_cents"] == 0
        assert data["collateral_requirement_cents"] == 0
        assert data["version"] == 1
        assert data["unsecured_allowance_cents"] == 100000
        assert is_valid_uuid(data["id"])
        assert is_iso8601_timestamp(data["created_at"])
        assert is_iso8601_timestamp(data["updated_at"])
        assert_participant_credit_invariants(data)
        # re-read
        reread = validate_success(api.get_participant(data["id"], ISO))
        assert reread["status"] == "ACTIVE"

    def test_participant_create_applies_defaults_below_investment_grade(self, api):
        """PRD §2.8: "The tier also fixes `unsecured_allowance_cents`: 100000
        cents (one thousand dollars) for `INVESTMENT_GRADE`, zero for
        `BELOW_INVESTMENT_GRADE`."

        Design: Corner/entities/participant_create_applies_defaults
        """
        resp = api.create_participant(
            {"company_name": "Defaults BIG", "credit_rating_tier": "BELOW_INVESTMENT_GRADE"}, ISO)
        data = validate_success(resp, expected_status=201)
        assert data["unsecured_allowance_cents"] == 0
        assert data["status"] == "ACTIVE"
        assert_participant_credit_invariants(data)


class TestGeneratorComputedOnCreate:
    def test_generator_availability_computed_on_create(self, api):
        """PRD §3.1: "A new generator starts `AVAILABLE` with `availability_mw`
        equal to its `capacity_mw`."

        Design: Corner/entities/generator_availability_computed_on_create
        """
        _, p_id = create_participant(company_name="Gen Co")
        resp = api.create_generator(
            {"market_participant_id": p_id, "unit_name": "U1",
             "pricing_node": "WEST_HUB", "capacity_mw": 12.5}, ISO)
        data = validate_success(resp, expected_status=201)
        assert_generator_asset(data)
        assert data["availability_mw"] == 12.5
        assert data["status"] == "AVAILABLE"


class TestOperatingDayUniqueDate:
    def test_operating_day_duplicate_date_rejected(self, api):
        """PRD §3.2: "The market date is unique across all operating days — a
        duplicate is rejected with `ERR_OPERATING_DAY_EXISTS`."

        Design: Corner/entities/operating_day_duplicate_date_rejected
        """
        create_operating_day(market_date="2026-08-03", gate_close="2026-08-02T10:30:00Z")
        resp = api.create_operating_day(
            {"market_date": "2026-08-03", "da_gate_close_at": "2026-08-02T11:30:00Z"}, ISO)
        validate_error(resp, ApiErrorId.ERR_OPERATING_DAY_EXISTS)


class TestNotFound:
    def test_get_offer_not_found_returns_404(self, api):
        """PRD §2.11 item 4: "Existence: path identifiers are validated left to
        right ... `ERR_NOT_FOUND`."

        Design: Corner/entities/get_offer_not_found_returns_404
        """
        create_participant(company_name="NF Co")
        resp = api.get_offer(NON_EXISTENT, make_trader_headers("t"))
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        body = resp.json()
        assert body["response_type"] == "error"


class TestResponseEnvelope:
    def test_response_envelope_success_and_error_shape(self, api):
        """PRD §2.2 success format: "The `api_request_id` is a server-generated
        unique identifier for the request that starts with `req_`." and error
        format: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."

        Design: Corner/endpoints/response_envelope_success_and_error_shape
        """
        _, p_id = create_participant(company_name="Env Co")
        ok = api.get_participant(p_id, ISO)
        body = ok.json()
        assert body["meta"]["api_request_id"]
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert body["response_type"] == "object"
        assert body["data"]["id"] == p_id

        err = api.get_participant(NON_EXISTENT, ISO)
        ebody = err.json()
        assert ebody["response_type"] == "error"
        assert ebody["data"]["error_id"] == "ERR_NOT_FOUND"
        assert ebody["data"]["message"]


class TestOutagesPagination:
    def test_outages_list_pagination_limit_offset(self, api):
        """PRD §2.3: "Unless otherwise specified, every list endpoint returns
        rows ordered by `created_at` ascending — a stable order in which ties
        are broken by insertion sequence." and "The `limit` parameter caps the
        number of items returned: if not provided it defaults to 10".

        Design: Corner/endpoints/outages_list_pagination_limit_offset
        """
        p_id, g_id, _ = setup_participant_generator(company="Pg Co")
        th = make_trader_headers(p_id)
        ids = []
        for i, day in enumerate(["2026-08-05", "2026-08-06", "2026-08-07"]):
            resp = api.create_outage(g_id, {
                "outage_type": "PARTIAL", "derate_pct": 20,
                "start_at": f"{day}T00:00:00Z", "end_at": f"{day}T06:00:00Z",
                "reason": f"r{i+1}",
            }, th)
            ids.append(get_success_data(resp)["id"])

        page1, meta1 = validate_paginated(api.list_outages(ISO, params={
            "generator_asset_id": g_id, "limit": 2, "offset": 0}))
        assert [r["id"] for r in page1] == ids[:2]
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(api.list_outages(ISO, params={
            "generator_asset_id": g_id, "limit": 2, "offset": 2}))
        assert [r["id"] for r in page2] == ids[2:]
        assert meta2["has_more"] is False
