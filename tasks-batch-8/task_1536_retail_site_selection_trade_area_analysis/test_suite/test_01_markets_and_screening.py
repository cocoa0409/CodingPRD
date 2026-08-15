"""Market onboarding, screening evaluation, saturation posture, and store roster.

PRD §3.1 (screening chain), §2.9 (portfolio ledgers and saturation posture).
"""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_market,
    assert_store,
    create_market,
    create_market_payload,
    create_open_site,
    create_qualified_market,
    create_site,
    create_stores,
    create_store_payload,
    get_success_data,
    validate_error,
    validate_success,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
ANALYST = TEST_USERS["analyst_headers"]


class TestMarketCreation:
    def test_market_create_applies_defaults_and_null_computed(self, api):
        """PRD §3.1: "A new market begins with `market_status` of `SCREENING`,
        with `open_store_count` and `committed_capex_cents` at zero and all
        score fields unset."
        PRD §2.4: "Every resource carries an `id`, which is a server-minted
        UUID with no type prefix."

        Design: Corner/entities/market_create_applies_defaults_and_null_computed
        """
        data = validate_success(
            api.create_market(create_market_payload(name="Metro D"), ADMIN),
            expected_status=201,
        )
        assert_market(data)
        assert data["market_status"] == "SCREENING"
        assert data["open_store_count"] == 0
        assert data["committed_capex_cents"] == 0
        assert data["version"] == 1
        for field in ("raw_score", "screening_tier", "target_store_count",
                      "penetration_index", "final_score"):
            assert data.get(field) is None, (
                f"{field} must be unset before the first evaluation"
            )

    def test_market_create_missing_required_returns_invalid_request(self, api):
        """PRD §2.7: "Then the request body itself is checked — required fields
        present, types correct, enum membership, date ordering (an exclusivity
        end date must be strictly after its start date; a build end date
        strictly after its start date), and numeric ranges per the entity
        constraints of §3; violations yield `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/market_create_missing_required_returns_invalid_request
        """
        payload = create_market_payload(name="Metro D")
        del payload["population"]
        resp = api.create_market(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestMarketScreeningCircularOrder:
    """Pinned five-step chain: raw -> tier -> target -> penetration -> final."""

    def _evaluate_circular_market(self, api):
        market = create_market(
            name="Metro Circ", state_code="OH", population=400000,
            median_household_income_cents=8000000, population_growth_bp=250,
            psychographic_index=110, base_target_stores=4,
        )
        create_stores(market["id"], (
            ("P1", "STANDARD", 900000000),
            ("P2", "STANDARD", 900000000),
            ("P3", "STANDARD", 900000000),
        ))
        return validate_success(api.evaluate_market(market["id"], ADMIN))

    def test_raw_score_tier_and_target_follow_pinned_order(self, api):
        """PRD §3.1: "a raw score of at least 75.00 earns tier `A` with a bonus
        of four stores, a raw score of at least 50.00 earns tier `B` with a
        bonus of two, and anything lower is tier `C` with no bonus;
        `target_store_count` is then `base_target_stores` plus the tier bonus."

        Design: Difficulty/combinatorial_formula/market_screening_circular_order
        """
        data = self._evaluate_circular_market(api)
        assert_market(data)
        # 0.30*100 + 0.30*100 + 0.20*50 + 0.20*91.6667 -> 88.33
        assert data["raw_score"] == pytest.approx(88.33, abs=0.001)
        assert data["screening_tier"] == "A"
        assert data["target_store_count"] == 8, (
            "base 4 + tier-A bonus 4 (tier read off raw_score before target)"
        )

    def test_penetration_and_final_score_use_post_bonus_target(self, api):
        """PRD §3.1: "Fourth, `penetration_index` is the market's current
        `open_store_count` divided by the freshly computed `target_store_count`,
        rounded half-up to six decimal places — zero when the market has no open
        stores — and the penetration penalty is the lesser of that index and
        1.0, multiplied by 20."
        PRD §3.1: "Fifth, `final_score` is `raw_score` minus the penetration
        penalty, rounded half-up to two decimal places. A market whose final
        score is at least 60.00 becomes `QUALIFIED`; below that bar it becomes
        `DISQUALIFIED`."

        Design: Difficulty/combinatorial_formula/market_screening_circular_order
        """
        data = self._evaluate_circular_market(api)
        assert data["penetration_index"] == pytest.approx(0.375, abs=1e-6), (
            "3 open stores / 8 target (target already includes the tier bonus)"
        )
        # 88.33 - min(0.375, 1.0)*20 = 80.83
        assert data["final_score"] == pytest.approx(80.83, abs=0.001)
        assert data["market_status"] == "QUALIFIED"


class TestMarketSaturationCycle:
    """Full posture loop driven by child transitions: open saturates at the
    inclusive boundary, a store close de-saturates."""

    def _setup_boundary_market_with_open_site(self, api):
        market = create_qualified_market(
            name="Metro Sat", state_code="NM", population=250000,
            median_household_income_cents=7500000, population_growth_bp=0,
            psychographic_index=0, base_target_stores=1,
        )
        stores = create_stores(market["id"], (
            ("K1", "STANDARD", 900000000),
            ("K2", "STANDARD", 1100000000),
        ))
        # stores=None: the K1/K2 roster above is the market's only roster.
        ctx = create_open_site(market_id=market["id"], stores=None,
                               num_voters=3, crew_code="CREW-SAT")
        return market, stores, ctx

    def test_open_reaching_target_saturates_market(self, api):
        """PRD §2.9: "After every recomputation of `open_store_count`, the
        market's saturation posture is re-evaluated: a `QUALIFIED` market whose
        `open_store_count` has risen to at least its `target_store_count`
        becomes `SATURATED`, and a `SATURATED` market whose count has fallen
        below its target returns to `QUALIFIED`."
        PRD §2.9: "The boundary is inclusive — a count exactly equal to the
        target is saturated."

        Design: Difficulty/non_linear_state_machine/market_saturation_cycle
        """
        market, _stores, ctx = self._setup_boundary_market_with_open_site(api)
        evaluated = get_success_data(api.get_market(market["id"], ADMIN))
        # Boundary market: raw 60.00 -> tier B -> target 1 + 2 = 3.
        assert evaluated["final_score"] == pytest.approx(60.00, abs=0.001)
        assert evaluated["target_store_count"] == 3
        assert ctx["site"]["site_status"] == "OPEN"
        # 2 OPERATING stores + 1 OPEN site == target 3 -> SATURATED.
        assert evaluated["open_store_count"] == 3
        assert evaluated["market_status"] == "SATURATED"

    def test_store_close_cycles_market_back_to_qualified(self, api):
        """PRD §3.1: "Closing a store moves it to `CLOSED`, decrements the
        count, and triggers the de-saturation check — a `SATURATED` market
        whose count has dropped below target re-opens to `QUALIFIED`."

        Design: Difficulty/non_linear_state_machine/market_saturation_cycle
        """
        market, stores, _ctx = self._setup_boundary_market_with_open_site(api)
        saturated = get_success_data(api.get_market(market["id"], ADMIN))
        assert saturated["market_status"] == "SATURATED"
        closed = validate_success(api.close_store(stores[0]["id"], ADMIN))
        assert_store(closed)
        assert closed["store_status"] == "CLOSED"
        restored = get_success_data(api.get_market(market["id"], ADMIN))
        assert restored["open_store_count"] == 2
        assert restored["market_status"] == "QUALIFIED"


class TestStoreRosterLedger:
    def test_store_close_decrements_open_store_count(self, api):
        """PRD §3.1: "Closing a store moves it to `CLOSED`, decrements the
        count, and triggers the de-saturation check — a `SATURATED` market
        whose count has dropped below target re-opens to `QUALIFIED`."
        PRD §2.9: "`open_store_count` is the number of the market's existing
        stores in `OPERATING` status plus the number of the market's sites in
        `OPEN`, `MEASURING`, or `UNDERPERFORMING` status."

        Design: Corner/state_machines/store_close_decrements_open_store_count
        """
        market = create_qualified_market(
            name="Metro S9", state_code="NM", population=250000,
            median_household_income_cents=7500000, population_growth_bp=0,
            psychographic_index=0, base_target_stores=1,
        )
        stores = create_stores(market["id"], (
            ("K1", "STANDARD", 900000000),
            ("K2", "STANDARD", 1100000000),
        ))
        before = get_success_data(api.get_market(market["id"], ADMIN))
        assert before["open_store_count"] == 2
        closed = validate_success(api.close_store(stores[0]["id"], ADMIN))
        assert closed["store_status"] == "CLOSED"
        after = get_success_data(api.get_market(market["id"], ADMIN))
        assert after["open_store_count"] == 1, "close decrements the ledger"
        assert after["market_status"] == "QUALIFIED", (
            "1 < target 3: no posture change away from QUALIFIED"
        )

    def test_duplicate_store_code_scoped_per_market(self, api):
        """PRD §3.1: "a `store_code` that must be unique within its market
        (case-sensitive; a collision is rejected with
        `ERR_DUPLICATE_STORE_CODE`)"

        Design: Corner/errors/error_duplicate_store_code_scoped_per_market
        """
        mkt1 = create_market(name="Metro E3a")
        mkt2 = create_market(name="Metro E3b", state_code="OK")
        create_stores(mkt1["id"], (("DUP", "STANDARD", 900000000),))
        resp_dup = api.create_store(
            create_store_payload(
                market_id=mkt1["id"], store_code="DUP",
                format_type="EXPRESS", annual_sales_cents=500000000,
            ), ADMIN,
        )
        validate_error(resp_dup, ApiErrorId.ERR_DUPLICATE_STORE_CODE)
        resp_ok = api.create_store(
            create_store_payload(
                market_id=mkt2["id"], store_code="DUP",
                format_type="STANDARD", annual_sales_cents=500000000,
            ), ADMIN,
        )
        store = validate_success(resp_ok, expected_status=201)
        assert_store(store)
        assert store["market_id"] == mkt2["id"]


class TestImmediateConsistency:
    def test_immediate_visibility_and_version_increments(self, api):
        """PRD §2.4: "Resources other than votes also carry `updated_at`,
        refreshed to the mutation time whenever the resource changes, and
        `version`, an integer that begins at 1 at creation and increments by
        one on every mutation of the resource — including automatic mutations
        such as the increment applied to a site's `version` when one of its
        trade-area models is locked."
        PRD §3.2: "A passing screening moves the site from `DRAFT` to
        `SCREENED` and advances its `version`."

        Design: Corner/consistency_model/immediate_visibility_and_version_increments
        """
        market = create_qualified_market(name="Metro IM")
        site = create_site(market["id"])
        assert site["version"] == 1
        read_back = validate_success(api.get_site(site["id"], ANALYST))
        assert read_back["version"] == 1
        assert read_back["site_status"] == "DRAFT"
        screened = validate_success(api.run_site_screening(site["id"], ANALYST))
        assert screened["site_status"] == "SCREENED"
        after = validate_success(api.get_site(site["id"], ANALYST))
        assert after["site_status"] == "SCREENED"
        assert after["version"] == 2, "screening increments version by exactly 1"
        assert after["updated_at"] >= read_back["updated_at"]
