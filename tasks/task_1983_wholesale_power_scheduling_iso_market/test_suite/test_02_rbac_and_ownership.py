"""RBAC segregation of duties and ownership scoping."""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, make_iso_headers, make_trader_headers, make_analyst_headers,
    make_credit_headers,
)
from test_helpers.fixtures import (
    ISO, create_participant, create_generator, create_operating_day,
    create_offer, setup_participant_generator, set_clock,
)


class TestMissingAuthHeaders:
    def test_missing_auth_headers_rejected(self, api):
        """PRD §2.1: "A request whose headers are missing, malformed, or whose
        role is not one of these declared names is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/rbac/missing_auth_headers_rejected
        """
        set_clock("2026-08-01T00:00:00Z")
        # Send the trigger with both auth headers stripped.
        resp = api._request("POST", "/market/participants",
                            {"company_name": "NoHdr Co", "credit_rating_tier": "INVESTMENT_GRADE"},
                            {"Content-Type": "application/json"})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestSegregationOfDuties:
    def test_trader_cannot_run_market_forbidden(self, api):
        """PRD §2.1: "A request whose role is not on the endpoint's authorized
        list is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

        Design: Corner/rbac/trader_cannot_run_market_forbidden
        """
        _, p_id = create_participant(company_name="Sod Co")
        _, d_id, _ = create_operating_day()
        resp = api.run_day_ahead_market(d_id, {"node_prices": []}, make_trader_headers(p_id))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        day = get_success_data(api.get_operating_day(d_id, ISO))
        assert day["status"] == "DA_OPEN"

    def test_iso_operator_cannot_submit_offer_forbidden(self, api):
        """PRD §2.1: "A request whose role is not on the endpoint's authorized
        list is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

        Design: Corner/rbac/iso_operator_cannot_submit_offer_forbidden
        """
        set_clock("2026-08-01T00:00:00Z")
        p_id, g_id, _ = setup_participant_generator(company="Sod2 Co")
        _, d_id, d_v = create_operating_day()
        _, o_id = create_offer(d_id, g_id, offered_mw=5, day_version=d_v, participant_id=p_id)
        resp = api.submit_offer(o_id, ISO)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        offer = get_success_data(api.get_offer(o_id, make_trader_headers(p_id)))
        assert offer["status"] == "DRAFT"

    def test_settlement_analyst_cannot_post_collateral_forbidden(self, api):
        """PRD §2.1: "The `SettlementAnalyst` validates statements and files or
        withdraws disputes, and may not trade or move collateral."

        Design: Corner/rbac/settlement_analyst_cannot_post_collateral_forbidden
        """
        _, p_id = create_participant(company_name="Sod3 Co")
        resp = api.create_posting(p_id, {"amount_cents": 1000, "instrument_type": "CASH"},
                                  make_analyst_headers(p_id))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)


class TestOwnershipScoping:
    def test_trader_ownership_violation_on_foreign_generator(self, api):
        """PRD §2.1: "ownership checks on any resource that references a
        MarketParticipant ... compare the resource's owning participant `id`
        against `X-User-ID`, and a mismatch is rejected with
        `ERR_OWNERSHIP_VIOLATION` (HTTP 403)."

        Design: Corner/rbac/trader_ownership_violation_on_foreign_generator
        """
        _, p1 = create_participant(company_name="Own1 Co")
        _, p2 = create_participant(company_name="Own2 Co")
        _, g2, _ = create_generator(p2, unit_name="U2")
        _, d_id, d_v = create_operating_day()
        resp = api.create_offer(d_id, {
            "generator_asset_id": g2, "offered_mw": 5,
            "offer_price_cents_per_mwh": 5000, "expected_operating_day_version": d_v,
        }, make_trader_headers(p1))
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_VIOLATION)
