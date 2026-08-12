"""Partner companies, co-production share capacity, and settlement variants."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_partner_company,
    create_production,
    create_rental_offer_payload,
    create_share,
    setup_copro_settlement_scenario,
    transition_share,
    validate_error,
    validate_success,
)

PM = TEST_USERS["production_manager_headers"]
ANY = TEST_USERS["any_headers"]


class TestPartnerCompanies:
    def test_partner_company_invalid_enum_rejected(self, api):
        """PRD §3.1: "A `PlatformAdmin` registers each external company the house does business with, supplying its legal `name` and a `partner_kind` of either `CO_PRODUCER` or `RENTER`."
        PRD §2.9: "Required fields must be present, enums must be in range, integers that must be positive must be positive, and a share percentage must be greater than zero and at most one hundred — else `ERR_VALIDATION` (400)."

        Design: Corner/entities/partner_company_invalid_enum_rejected
        """
        resp = api.create_partner_company({"name": "BadKindCo", "partner_kind": "BOTH"},
                                          TEST_USERS["platform_admin_headers"])
        validate_error(resp, ApiErrorId.ERR_VALIDATION)


class TestShareCapacity:
    def test_share_percent_overflow_rejected(self, api):
        """PRD §3.3: "Ratifying — `PROPOSED` → `RATIFIED` — enforces the house's one-hundred-percent cap: the sum of `share_percentage` over the production's already-`RATIFIED` shares plus the candidate's percentage must not exceed one hundred, else the ratification is rejected with `ERR_SHARE_PERCENT_OVERFLOW` (HTTP 422)."

        Design: Corner/validations/share_percent_overflow_rejected
        """
        gross_co = create_partner_company(name="GrossCo", partner_kind="CO_PRODUCER")
        net_co = create_partner_company(name="NetCo", partner_kind="CO_PRODUCER")
        production = create_production(title="Swan Lake", build_budget_cents=100_000_000)
        share1 = create_share(production["id"], gross_co["id"], 60, "GROSS_COST")
        transition_share(share1["id"], "RATIFIED")
        share2 = create_share(production["id"], net_co["id"], 60, "NET_REVENUE_SHARE")

        resp = api.transition_co_production_share(share2["id"], "RATIFIED", PM)
        validate_error(resp, ApiErrorId.ERR_SHARE_PERCENT_OVERFLOW)
        after = validate_success(api.get_co_production_share(share2["id"], ANY), 200)
        assert after["status"] == "PROPOSED", "rejected ratification leaves the share PROPOSED"


class TestPartnerKindEnforcement:
    def test_rental_offer_to_co_producer_kind_rejected(self, api):
        """PRD §3.9: "Renting a production out begins when a `ProductionManager` creates a rental offer with the `production_id`, the `renter_company_id` of the prospective renter — which must be a `RENTER`-kind partner company, else `ERR_PARTNER_KIND_MISMATCH` —"

        Design: Corner/validations/rental_offer_to_co_producer_kind_rejected
        """
        co_producer = create_partner_company(name="GrossCo", partner_kind="CO_PRODUCER")
        production = create_production(title="Swan Lake", build_budget_cents=100_000_000)
        payload = create_rental_offer_payload(
            production["id"], co_producer["id"],
            expected_production_version=production["version"],
        )
        resp = api.create_rental_offer(payload, PM)
        validate_error(resp, ApiErrorId.ERR_PARTNER_KIND_MISMATCH)


class TestCoproSettlementVariants:
    def test_copro_settlement_gross_and_net_literal_values(self, api):
        """PRD §3.3: "Under `GROSS_COST` the partner simply pays its share of the build cost with no revenue offset, so `settlement_cents` is the cost share."
        PRD §3.3: "Under `NET_REVENUE_SHARE` the build-cost share is offset by the partner's accrued share of season revenue: `settlement_cents` is the cost share minus the `accrued_revenue_share_cents`, with the accrual evaluated at settle time as the share's percentage of the production's `season_revenue_cents`, rounded half up."

        Total build cost 25,000,000; season revenue 100,000; both shares 40%.

        Design: Difficulty/dual_variant_calc/copro_settlement_gross_vs_net
        """
        scenario = setup_copro_settlement_scenario()
        share_g = scenario["share_g"]
        share_n = scenario["share_n"]

        settled_g = transition_share(share_g["id"], "SETTLED")
        settled_n = transition_share(share_n["id"], "SETTLED")

        assert settled_g["settlement_cents"] == 10_000_000, (
            "GROSS_COST: round_half_up(0.40 * 25,000,000)"
        )
        assert settled_n["settlement_cents"] == 9_960_000, (
            "NET_REVENUE_SHARE: 10,000,000 - round_half_up(0.40 * 100,000)"
        )
        assert settled_n["accrued_revenue_share_cents"] == 40_000, (
            "accrued = round_half_up(0.40 * season_revenue 100,000)"
        )
        assert settled_g["settlement_cents"] != settled_n["settlement_cents"], (
            "identical production data, different settlement variants"
        )

    def test_copro_settlement_net_strictly_smaller_and_gross_accrual_zero(self, api):
        """PRD §3.3: "The net variant therefore yields a strictly smaller settlement than the gross variant on identical inputs, and it may legitimately go negative when the partner's revenue share exceeds its cost share."
        PRD §3.3: "A new share is `PROPOSED`; its `settlement_cents` stays null until the share is `SETTLED`, and its `accrued_revenue_share_cents` is zero unless and until a ratified net-revenue share begins accruing."

        Design: Difficulty/dual_variant_calc/copro_settlement_gross_vs_net
        """
        scenario = setup_copro_settlement_scenario()
        share_g = scenario["share_g"]
        share_n = scenario["share_n"]

        # The GROSS_COST share never accrues a revenue share, even after sales.
        gross_before = validate_success(api.get_co_production_share(share_g["id"], ANY), 200)
        net_before = validate_success(api.get_co_production_share(share_n["id"], ANY), 200)
        assert gross_before["accrued_revenue_share_cents"] == 0, (
            "accrual only begins for a ratified net-revenue share"
        )
        assert net_before["accrued_revenue_share_cents"] == 40_000, (
            "net share accrual tracks season revenue (100,000 * 0.40)"
        )

        settled_g = transition_share(share_g["id"], "SETTLED")
        settled_n = transition_share(share_n["id"], "SETTLED")
        assert settled_n["settlement_cents"] < settled_g["settlement_cents"], (
            "net variant yields a strictly smaller settlement on identical inputs"
        )
        assert settled_g["settlement_cents"] == 10_000_000
        assert settled_n["settlement_cents"] == 9_960_000
