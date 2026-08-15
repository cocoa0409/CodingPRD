"""Campaign setup, defaults, uniqueness, pagination, and lifecycle gating."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    create_campaign_payload, assert_campaign,
    reset_clock, create_campaign, set_clock,
    ApiErrorId, CLOCK,
)

ADMIN = None  # bound per-test via fixture


class TestCampaignDefaults:
    def test_campaign_create_applies_defaults(self, api, admin_headers):
        """PRD §3.1: "an optional `privacy_mode` that defaults to `STRICT` and may
        be either `STRICT` or `STANDARD`. The campaign begins in `DRAFT`, with
        `backfill_spent_cents` at 0 and `version` at 1."

        Design: Corner/entities/campaign_create_applies_defaults
        """
        reset_clock()
        payload = create_campaign_payload()
        payload.pop("privacy_mode", None)  # omit the optional field
        campaign = validate_success(api.create_campaign(payload, admin_headers), 201)
        assert_campaign(campaign)
        assert campaign["status"] == "DRAFT"
        assert campaign["privacy_mode"] == "STRICT"
        assert campaign["version"] == 1
        assert campaign["backfill_spent_cents"] == 0

    def test_campaign_missing_season_year_returns_invalid_request(
            self, api, admin_headers):
        """PRD §2.8: "A required field that is missing, of the wrong type, or an
        enum value outside its declared set yields `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD §3.1: "The create payload carries `season_year` (a four-digit year, at
        least 2020 and at most 2100, unique across all campaigns)".

        Design: Corner/entities/campaign_missing_required_field_returns_invalid_request
        """
        reset_clock()
        payload = create_campaign_payload()
        del payload["season_year"]
        res = api.create_campaign(payload, admin_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


class TestCampaignUniquenessAndListing:
    def test_duplicate_season_year_rejected(self, api, admin_headers):
        """PRD §3.4: "Violating the per-child uniqueness of `priority_rank`, the
        campaign's `season_year` uniqueness, an agency's `agency_code` uniqueness,
        or a donor's `email` uniqueness all yield `ERR_DUPLICATE` (HTTP 409)."

        Design: Corner/validations/duplicate_season_year_rejected
        """
        reset_clock()
        first = create_campaign_payload(season_year=2026)
        validate_success(api.create_campaign(first, admin_headers), 201)
        second = create_campaign_payload(season_year=2026)
        res = api.create_campaign(second, admin_headers)
        validate_error(res, ApiErrorId.ERR_DUPLICATE, expected_status=409)

    def test_list_campaigns_pagination_defaults(self, api, admin_headers):
        """PRD §2.3: "The default `limit` is 10, the minimum permitted `limit` is
        1, and the maximum permitted `limit` is 100. The default `offset` is 0."
        PRD §2.3: "the response `meta` block carries the four pagination fields
        `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/list_endpoint_pagination_defaults
        """
        reset_clock()
        validate_success(api.create_campaign(create_campaign_payload(),
                                             admin_headers), 201)
        res = api.list_campaigns(admin_headers)
        data, meta = validate_paginated(res)
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert len(data) == 1


class TestCampaignLifecycleGating:
    def test_advance_from_draft_rejected(self, api, admin_headers):
        """PRD §3.1: "From `MATCHING`, advancing the campaign moves it to
        `DISTRIBUTION_PREP`." — no advance transition is defined from `DRAFT`, and
        the error catalogue maps an undefined transition to `ERR_INVALID_STATE`
        (HTTP 409).

        Design: Corner/state_machines/campaign_cannot_skip_from_draft_to_distribution
        """
        reset_clock()
        campaign = validate_success(
            api.create_campaign(create_campaign_payload(), admin_headers), 201)
        res = api.advance_campaign(campaign["id"], campaign["version"],
                                   admin_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        after = validate_success(api.get_campaign(campaign["id"], admin_headers))
        assert after["status"] == "DRAFT"

    def test_event_with_inverted_window_rejected(self, api, admin_headers):
        """PRD §3.9: "Window sanity is enforced: `end_at` must be strictly greater
        than `start_at`, else the create is rejected with `ERR_INVALID_WINDOW`
        (HTTP 422)."

        Design: Corner/errors/error_invalid_window_on_event
        """
        reset_clock()
        campaign = validate_success(
            api.create_campaign(create_campaign_payload(), admin_headers), 201)
        res = api.create_distribution_event(
            {"campaign_id": campaign["id"], "site_name": "Bad Hall",
             "start_at": "2026-12-18T17:00:00Z", "end_at": "2026-12-18T09:00:00Z",
             "capacity_slots": 10}, admin_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_WINDOW, expected_status=422)

    def test_thank_you_generate_before_reconciliation_rejected(
            self, api, admin_headers):
        """PRD §3.11: "Attempting generation while the campaign is not yet in
        `RECONCILIATION` or `CLOSED` is rejected with `ERR_CAMPAIGN_NOT_CLOSED`
        (HTTP 409)."

        Design: Corner/errors/error_campaign_not_closed_on_thankyou_send
        """
        reset_clock()
        campaign = validate_success(
            api.create_campaign(create_campaign_payload(), admin_headers), 201)
        res = api.generate_thank_you_notes(campaign["id"], admin_headers)
        validate_error(res, ApiErrorId.ERR_CAMPAIGN_NOT_CLOSED, expected_status=409)
