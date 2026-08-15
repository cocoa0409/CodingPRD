"""Master data creation, computed fields, defaults, and request-shape validation."""

from test_helpers import (
    ApiErrorId, NON_EXISTENT_UUID, assert_campaign, assert_playlog,
    assert_reel, assert_showtime, constants, create_advertiser,
    make_network_ops_headers, make_sales_manager_headers, make_theater_ops_headers, setup_confirmed_slot,
    setup_showtime_with_reel, validate_error, validate_success,
)
from test_helpers.factories import (
    create_campaign_payload, create_playlog_payload,
)
from test_helpers.fixtures import set_clock


class TestShowtimeCreation:
    def test_showtime_create_computes_daypart_forecast_and_reel(self, api):
        """PRD §3.1: "Its `daypart` is `MATINEE` when the UTC hour component of
        `starts_at` is less than 17, and `EVENING` otherwise."
        PRD §3.1: "Every showtime is born with exactly one pre-show reel, created
        automatically alongside it."

        Design: Corner/entities/showtime_create_computes_daypart_forecast_and_reel
        """
        theater, screen, feature, showtime, reel = setup_showtime_with_reel(
            starts_at=constants.OPENING_EVENING_START)
        assert_showtime(showtime)
        assert showtime["daypart"] == "EVENING"
        assert showtime["forecast_attendance"] == constants.FORECAST_OPENING_EVENING
        assert_reel(reel)
        assert reel["reel_status"] == "ASSEMBLING"
        assert reel["version"] == 1
        assert reel["capacity_seconds"] == 1200
        assert reel["national_pool_seconds"] == 720
        assert reel["local_pool_seconds"] == 480
        assert reel["showtime_id"] == showtime["id"]

    def test_showtime_create_matinee_daypart(self, api):
        """PRD §3.1: "Its `daypart` is `MATINEE` when the UTC hour component of
        `starts_at` is less than 17, and `EVENING` otherwise."

        Design: Corner/entities/showtime_create_computes_daypart_forecast_and_reel
        """
        _, _, _, showtime, _ = setup_showtime_with_reel(
            starts_at=constants.OPENING_MATINEE_START)
        assert showtime["daypart"] == "MATINEE"
        assert showtime["forecast_attendance"] == constants.FORECAST_OPENING_MATINEE


class TestCampaignCreationDefaults:
    def test_campaign_create_applies_strict_default(self, api):
        """PRD §3.2: "an optional `partial_credit_mode` of `STRICT` or `LENIENT`
        that defaults to `STRICT`."
        PRD §3.2: "Both computed counters, `reserved_estimated_cents` and
        `delivered_impressions`, begin at zero."

        Design: Corner/entities/campaign_create_applies_strict_default
        """
        advertiser = create_advertiser()
        resp = api.create_campaign(create_campaign_payload(advertiser["id"]),
                                   make_sales_manager_headers("sm-1"))
        campaign = validate_success(resp, expected_status=201)
        assert_campaign(campaign)
        assert campaign["partial_credit_mode"] == "STRICT"
        assert campaign["campaign_status"] == "DRAFT"
        assert campaign["reserved_estimated_cents"] == 0
        assert campaign["delivered_impressions"] == 0
        assert campaign["version"] == 1
        assert campaign["created_by_user_id"] == "sm-1"
        assert campaign["approved_by_user_id"] is None


class TestPlayLogRecordShape:
    def test_playlog_record_is_immutable_without_version(self, api):
        """PRD §2.4: "The PlayLog is an append-only verification record: it
        carries `id` and `created_at` only, and both `updated_at` and `version`
        are absent from it."

        Design: Corner/entities/playlog_record_is_immutable_without_version
        """
        ctx = setup_confirmed_slot()
        set_clock(constants.AFTER_SHOW_CLOCK)
        resp = api.create_playlog(ctx["slot"]["id"], create_playlog_payload(),
                                  make_theater_ops_headers(ctx["theater"]["id"]))
        playlog = validate_success(resp, expected_status=201)
        assert_playlog(playlog)
        assert playlog["slot_id"] == ctx["slot"]["id"]
        assert playlog["played_at"] == constants.AFTER_SHOW_CLOCK
        assert playlog["reported_by_user_id"] == ctx["theater"]["id"]
        assert playlog["reported_by_theater_id"] == ctx["theater"]["id"]


class TestNotFoundAndRequestShape:
    def test_campaign_get_unknown_id_not_found(self, api):
        """PRD §2.6: "**Existence** — every referenced resource must exist,
        failing as `ERR_NOT_FOUND`."

        Design: Corner/entities/campaign_get_unknown_id_not_found
        """
        resp = api.get_campaign(NON_EXISTENT_UUID, make_sales_manager_headers("sm-1"))
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_theater_create_missing_required_field_returns_invalid_request(self, api):
        """PRD §2.6: "**Request shape** — required fields present, types valid,
        enum values in-domain, date fields in ISO form, `period_end_date` not
        earlier than `period_start_date`, and `flight_end_date` not earlier than
        `flight_start_date`, failing as `ERR_INVALID_REQUEST`."

        Design: Corner/entities/theater_create_missing_required_field_returns_invalid_request
        """
        resp = api.create_theater({"name": "NoTier"}, make_network_ops_headers())
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_feature_create_invalid_enum_returns_invalid_request(self, api):
        """PRD §2.6: "**Request shape** — required fields present, types valid,
        enum values in-domain, date fields in ISO form, `period_end_date` not
        earlier than `period_start_date`, and `flight_end_date` not earlier than
        `flight_start_date`, failing as `ERR_INVALID_REQUEST`."

        Design: Corner/entities/feature_create_invalid_enum_returns_invalid_request
        """
        resp = api.create_feature(
            {"title": "Bad", "content_rating": "PG-13", "runtime_minutes": 100,
             "release_date": "2026-08-01"},
            make_network_ops_headers())
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_campaign_create_with_unknown_advertiser_not_found(self, api):
        """PRD §2.6: "only after the path resolves are body-referenced foreign
        keys such as `campaign_id` and `feature_id` checked."

        Design: Corner/entities/campaign_create_with_unknown_advertiser_not_found
        """
        resp = api.create_campaign(
            create_campaign_payload(NON_EXISTENT_UUID),
            make_sales_manager_headers("sm-1"))
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
