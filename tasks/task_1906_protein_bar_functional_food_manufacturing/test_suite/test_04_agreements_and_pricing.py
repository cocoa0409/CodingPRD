"""Co-manufacturing agreements: tiered pricing variants, lifecycle terminal
lockdown, and the quarterly rollup window (PRD §3.3)."""
from test_helpers import (
    ApiErrorId,
    fixtures,
    validate_error,
    validate_success,
)
from test_helpers import api_client as client
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["plant_admin_headers"]
PP = TEST_USERS["production_planner_headers"]

TIERS = [
    {"upto_cases": 1000, "rate_cents_per_case": 500},
    {"upto_cases": 5000, "rate_cents_per_case": 450},
    {"upto_cases": 999999999, "rate_cents_per_case": 400},
]


def _pricing_agreements():
    cust = fixtures.create_customer("C1")
    agm = fixtures.create_agreement(
        cust["id"], pricing_mode="MARGINAL", moq=100, committed=1000,
        tier_breaks=[dict(t) for t in TIERS],
    )
    aga = fixtures.create_agreement(
        cust["id"], pricing_mode="AVERAGE", moq=100, committed=1000,
        tier_breaks=[dict(t) for t in TIERS],
    )
    return agm, aga


class TestTieredPricingVariants:
    def test_marginal_pricing_charges_each_tier_inside_its_bracket(self, api):
        """PRD §3.3: "Under `MARGINAL` pricing, the quote walks the tier table
        in ascending order and charges each tier's `rate_cents_per_case` only
        to the cases falling inside that tier's bracket — for each tier, the
        cases charged are the smaller of the requested count and the tier's
        `upto_cases`, minus the cases already charged to lower tiers, never
        less than zero — and the total is the sum of those per-tier charges."
        PRD §3.3: "In both modes `total_cents` is an exact integer of cents,
        and `per_case_cents` is the total divided by the case count, rounded
        half-up to a whole cent."

        Design: Difficulty/dual_variant_calc/marginal_vs_average_tier_pricing
        """
        agm, _ = _pricing_agreements()
        quote = validate_success(client.get_agreement_quote(agm["id"], 2000, PP), 200)
        assert quote["cases"] == 2000
        # 1000*500 + 1000*450 = 950000; per-case 950000/2000 = 475
        assert quote["total_cents"] == 950000
        assert quote["per_case_cents"] == 475

    def test_average_pricing_applies_reached_tier_to_all_cases(self, api):
        """PRD §3.3: "Under `AVERAGE` pricing, the quote finds the first tier
        whose `upto_cases` reaches the requested count and applies that single
        tier's rate to every case; when tier rates descend, this yields a
        strictly lower total than `MARGINAL` for any request above the first
        tier."

        Design: Difficulty/dual_variant_calc/marginal_vs_average_tier_pricing
        """
        agm, aga = _pricing_agreements()
        marginal = validate_success(client.get_agreement_quote(agm["id"], 2000, PP), 200)
        average = validate_success(client.get_agreement_quote(aga["id"], 2000, PP), 200)
        # first tier reaching 2000 is upto 5000 @ 450 -> 2000*450 = 900000
        assert average["total_cents"] == 900000
        assert average["per_case_cents"] == 450
        assert marginal["total_cents"] - average["total_cents"] == 50000


class TestAgreementLifecycle:
    def test_terminated_agreement_cannot_be_reactivated(self, api):
        """PRD §3.3: "Termination from either `ACTIVE` or `SUSPENDED` moves the
        agreement to `TERMINATED`, which is terminal."
        PRD §2.6: "8. **Terminal-state lock** — the addressed resource must not
        sit in a terminal state: a `TERMINATED` agreement, a `SUPERSEDED`
        revision, a `REJECTED` or `DEPLETED` lot, a `CANCELLED` run or
        changeover, a lot release whose decision is `RELEASED` or `SCRAPPED`,
        or a `COMPLETED`, `FAILED`, or `TERMINATED` study all reject further
        action with `ERR_TERMINAL_STATE_LOCKED` (409)."

        Design: Corner/state_machines/c_agreement_terminal_lockdown
        """
        cust = fixtures.create_customer("C1")
        agreement = fixtures.create_agreement(cust["id"])
        validate_success(client.activate_agreement(agreement["id"], ADMIN), 200)
        terminated = validate_success(
            client.terminate_agreement(agreement["id"], ADMIN), 200
        )
        assert terminated["status"] == "TERMINATED"
        resp = client.activate_agreement(agreement["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_TERMINAL_STATE_LOCKED, 409)


class TestQuarterRollupWindow:
    def test_rollup_honors_half_open_quarter_window(self, api):
        """PRD §3.3: "The `produced_cases_current_quarter` is the sum of
        `produced_cases` over the agreement's runs whose `release_status` is
        `RELEASED` and whose `completed_utc` falls inside the quarter window —
        a completion exactly at `quarter_start` counts, one exactly at the
        window's end does not."
        PRD §3.3: "The `shortfall_cases` is the committed volume minus that
        produced volume, floored at zero, so it can never report a negative
        shortfall."

        Design: Corner/calculations/c_quarter_rollup_window_filtering
        """
        ns = fixtures.setup_quarter_window_pair()
        after_x = validate_success(client.get_agreement(ns.plant.ag["id"], PP), 200)
        assert after_x["produced_cases_current_quarter"] == 130

        # run Y completed exactly at the exclusive end 2026-09-30T00:00Z.
        validate_success(
            client.decide_lot_release(ns.rel_y["id"], {"decision": "RELEASED"},
                                      TEST_USERS["quality_manager_headers"]),
            200,
        )
        after_y = validate_success(client.get_agreement(ns.plant.ag["id"], PP), 200)
        assert after_y["produced_cases_current_quarter"] == 130
        assert after_y["shortfall_cases"] == 870
