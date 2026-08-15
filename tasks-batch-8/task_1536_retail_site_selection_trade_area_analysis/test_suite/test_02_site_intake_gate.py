"""Candidate site intake and the screening gate (PRD §3.2): request shape,
existence, state gates, terminal lockdown, and the two screening fences."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_market,
    create_qualified_market,
    create_site,
    create_site_payload,
    create_draft_model,
    create_sales_forecast_payload,
    get_success_data,
    lock_model,
    add_site_visit,
    validate_error,
    validate_success,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
ANALYST = TEST_USERS["analyst_headers"]
MANAGER = TEST_USERS["manager_headers"]


class TestSiteScreeningMarketGate:
    def _disqualified_market_with_site(self, api):
        market = create_market(
            name="Metro DQ", state_code="WV", population=100000,
            median_household_income_cents=4500000, population_growth_bp=100,
            psychographic_index=60,
        )
        evaluated = validate_success(api.evaluate_market(market["id"], ADMIN))
        site = create_site(market["id"], address="3 Coal Rd")
        return evaluated, site

    def test_disqualified_market_evaluation_scores(self, api):
        """PRD §3.1: "A market whose final score is at least 60.00 becomes
        `QUALIFIED`; below that bar it becomes `DISQUALIFIED`."

        Design: Difficulty/cross_entity_state_dependency/site_screening_requires_market_qualified
        """
        evaluated, _site = self._disqualified_market_with_site(api)
        # 0.30*40 + 0.30*60 + 0.20*20 + 0.20*50 = 44.00
        assert evaluated["final_score"] == pytest.approx(44.00, abs=0.001)
        assert evaluated["market_status"] == "DISQUALIFIED"

    def test_run_screening_rejected_when_market_not_qualified(self, api):
        """PRD §3.2: "the site's market must be `QUALIFIED` — screening against
        a market in any other posture is rejected with
        `ERR_MARKET_NOT_QUALIFIED`"

        Design: Difficulty/cross_entity_state_dependency/site_screening_requires_market_qualified
        """
        _evaluated, site = self._disqualified_market_with_site(api)
        resp = api.run_site_screening(site["id"], ANALYST)
        validate_error(resp, ApiErrorId.ERR_MARKET_NOT_QUALIFIED)
        after = validate_success(api.get_site(site["id"], ANALYST))
        assert after["site_status"] == "DRAFT"


class TestSiteRequestShapeAndExistence:
    def test_site_create_invalid_enum_returns_invalid_request(self, api):
        """PRD §2.7: "Then the request body itself is checked — required fields
        present, types correct, enum membership, date ordering (an exclusivity
        end date must be strictly after its start date; a build end date
        strictly after its start date), and numeric ranges per the entity
        constraints of §3; violations yield `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/site_create_invalid_enum_returns_invalid_request
        """
        market = create_qualified_market(name="Metro E")
        payload = create_site_payload(market_id=market["id"],
                                      address="9 Bad Enum Ln",
                                      format_type="MEGA")
        resp = api.create_site(payload, ANALYST)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_get_nonexistent_site_returns_not_found(self, api):
        """PRD §2.7: "Path-template identifiers are resolved left to right, and
        every body-referenced foreign key (`market_id`, `site_id`,
        `trade_area_model_id`, `sales_forecast_id`, `sponsor_member_id`,
        `loi_id`, `crew_id`, and each store id inside `store_drive_times`) must
        resolve to an existing resource; a dangling reference yields
        `ERR_NOT_FOUND` (404)."

        Design: Corner/entities/get_nonexistent_site_returns_not_found
        """
        resp_get = api.get_site(NON_EXISTENT_UUID, ANALYST)
        validate_error(resp_get, ApiErrorId.ERR_NOT_FOUND)
        resp_fk = api.create_trade_area_model(
            {
                "site_id": NON_EXISTENT_UUID,
                "drive_time_minutes": 15,
                "trade_area_population": 50000,
                "per_capita_spend_cents": 300000,
                "cannibalization_variant": "FLAT_BAND",
            },
            ANALYST,
        )
        validate_error(resp_fk, ApiErrorId.ERR_NOT_FOUND)


class TestSiteStateGateAndLockdown:
    def test_site_open_from_draft_rejected_invalid_state(self, api):
        """PRD §3.8: "A successful opening moves the site from `BUILD_OUT` to
        `OPEN`, increments the market's `open_store_count`, and triggers the
        saturation check of §2.9 — a `QUALIFIED` market at or above target
        becomes `SATURATED`."
        PRD §2.7: "a live resource in the wrong state yields
        `ERR_INVALID_STATE` (409)"

        Design: Corner/state_machines/site_open_from_draft_rejected_invalid_state
        """
        market = create_qualified_market(name="Metro S1")
        site = create_site(market["id"])
        resp = api.open_site(site["id"], MANAGER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api.get_site(site["id"], ANALYST))
        assert after["site_status"] == "DRAFT"

    def test_withdraw_twice_returns_already_terminal(self, api):
        """PRD §2.10: "No mutation endpoint accepts a resource that has reached
        a terminal state; the attempt is rejected with `ERR_ALREADY_TERMINAL`
        (HTTP 409)."
        PRD §3.2: "Withdrawal is reachable from `DRAFT`, `SCREENED`, `MODELED`,
        `SCORED`, `FORECAST_LOCKED`, `IN_COMMITTEE`, `APPROVED`, `REJECTED`,
        `LOI_ACTIVE`, `LEASE_EXECUTED`, or `BUILD_OUT`, and lands the site in
        the terminal `WITHDRAWN` state."

        Design: Corner/state_machines/withdraw_twice_returns_already_terminal
        """
        market = create_qualified_market(name="Metro S2")
        site = create_site(market["id"])
        first = validate_success(api.withdraw_site(site["id"], MANAGER))
        assert first["site_status"] == "WITHDRAWN"
        second = api.withdraw_site(site["id"], MANAGER)
        validate_error(second, ApiErrorId.ERR_ALREADY_TERMINAL)

    def test_run_screening_twice_second_rejected(self, api):
        """PRD §3.2: "A passing screening moves the site from `DRAFT` to
        `SCREENED` and advances its `version`."
        PRD §2.7: "a live resource in the wrong state yields
        `ERR_INVALID_STATE` (409)"

        Design: Corner/state_machines/run_screening_twice_second_rejected
        """
        market = create_qualified_market(name="Metro S3")
        site = create_site(market["id"])
        first = validate_success(api.run_site_screening(site["id"], ANALYST))
        assert first["site_status"] == "SCREENED"
        second = api.run_site_screening(site["id"], ANALYST)
        validate_error(second, ApiErrorId.ERR_INVALID_STATE)


class TestInitialStates:
    def test_initial_states_on_creation(self, api):
        """PRD §3.2: "The site begins in `DRAFT` with `consecutive_miss_count`
        at zero."
        PRD §3.3: "A new model is `DRAFT` with its `cannibalized_sales_cents`
        unset."
        PRD §3.4: "Only one visit stands per site at a time: recording a new
        visit supersedes the site's prior `SUBMITTED` visit, which moves to
        `SUPERSEDED`, while the new visit begins `SUBMITTED`."
        PRD §3.5: "A new forecast is `DRAFT`, with `cannibalized_sales_cents`,
        `net_annual_sales_cents`, `occupancy_ratio_bp`, and `occupancy_band`
        unset until lock."

        Design: Corner/state_machines/initial_states_on_creation
        """
        market = create_qualified_market(name="Metro S5")
        site = create_site(market["id"])
        assert site["site_status"] == "DRAFT"
        assert site["consecutive_miss_count"] == 0
        get_success_data(api.run_site_screening(site["id"], ANALYST))
        model = create_draft_model(site["id"])
        assert model["model_status"] == "DRAFT"
        assert model.get("cannibalized_sales_cents") is None
        lock_model(model["id"], site["id"])
        visit = add_site_visit(site["id"])
        assert visit["visit_status"] == "SUBMITTED"
        forecast = validate_success(
            api.create_sales_forecast(
                create_sales_forecast_payload(
                    site_id=site["id"], trade_area_model_id=model["id"],
                    model_variant="ANALOG",
                ),
                ANALYST,
            ),
            expected_status=201,
        )
        assert forecast["forecast_status"] == "DRAFT"
        assert isinstance(forecast["gross_annual_sales_cents"], int)
        assert forecast.get("net_annual_sales_cents") is None
        assert forecast.get("cannibalized_sales_cents") is None
        assert forecast.get("occupancy_ratio_bp") is None
        assert forecast.get("occupancy_band") is None


class TestScreeningFences:
    def test_error_format_sqft_mismatch(self, api):
        """PRD §3.2: "the `square_footage` must fall inside the format band —
        2,000 to 4,000 square feet inclusive for `EXPRESS`, 8,000 to 15,000
        inclusive for `STANDARD`, and 20,000 to 45,000 inclusive for `FLAGSHIP`,
        with an out-of-band parcel rejected as `ERR_FORMAT_SQFT_MISMATCH`"

        Design: Corner/errors/error_format_sqft_mismatch
        """
        market = create_qualified_market(name="Metro E1")
        site = create_site(market["id"], address="6 Small St",
                           square_footage=5000)
        resp = api.run_site_screening(site["id"], ANALYST)
        validate_error(resp, ApiErrorId.ERR_FORMAT_SQFT_MISMATCH)
        after = validate_success(api.get_site(site["id"], ANALYST))
        assert after["site_status"] == "DRAFT"

    def test_error_asking_rent_above_market_cap(self, api):
        """PRD §3.2: "the `asking_rent_psf_cents` must not exceed the market's
        `max_rent_psf_cents`, else `ERR_ASKING_RENT_ABOVE_MARKET_CAP`"

        Design: Corner/errors/error_asking_rent_above_market_cap
        """
        market = create_qualified_market(name="Metro E2")
        site = create_site(market["id"], address="7 Pricey St",
                           asking_rent_psf_cents=45000)
        resp = api.run_site_screening(site["id"], ANALYST)
        validate_error(resp, ApiErrorId.ERR_ASKING_RENT_ABOVE_MARKET_CAP)
        after = validate_success(api.get_site(site["id"], ANALYST))
        assert after["site_status"] == "DRAFT"
