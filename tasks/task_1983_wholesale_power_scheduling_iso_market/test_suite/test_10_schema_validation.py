"""Schema-level request validation: required fields and enum membership."""
import pytest
from test_helpers import (
    validate_error, get_success_data, ApiErrorId, make_trader_headers,
)
from test_helpers.fixtures import (
    ISO, create_participant, create_generator, create_operating_day,
    setup_participant_generator, set_clock,
)


class TestOfferRequiredFields:
    def test_offer_create_missing_required_field_rejected(self, api):
        """PRD §2.11 item 3: "Request shape: the body parses, every required
        input field is present, enum fields are within their declared value
        sets, numeric ranges are sane ... and unknown fields are rejected —
        `ERR_INVALID_REQUEST`." PRD §3.2: "Creating an offer names the
        `generator_asset_id`, an `offered_mw` block greater than zero, and an
        `offer_price_cents_per_mwh` floor".

        Design: Corner/entities/offer_create_missing_required_field_rejected
        """
        p_id, g_id, _ = setup_participant_generator(company="Req Co")
        _, d_id, d_v = create_operating_day()
        resp = api.create_offer(d_id, {
            "generator_asset_id": g_id,
            "offer_price_cents_per_mwh": 5000,
            "expected_operating_day_version": d_v,
        }, make_trader_headers(p_id))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestParticipantEnum:
    def test_participant_invalid_enum_rejected(self, api):
        """PRD §2.11 item 3: "enum fields are within their declared value sets
        ... — `ERR_INVALID_REQUEST`." PRD §3.1: "a `credit_rating_tier` of
        `INVESTMENT_GRADE` or `BELOW_INVESTMENT_GRADE`".

        Design: Corner/entities/participant_invalid_enum_rejected
        """
        set_clock("2026-08-01T00:00:00Z")
        resp = api.create_participant(
            {"company_name": "Enum Co", "credit_rating_tier": "AAA"}, ISO)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
