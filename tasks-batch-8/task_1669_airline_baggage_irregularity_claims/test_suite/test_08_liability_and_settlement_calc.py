"""Liability-cap variants and settlement-offer arithmetic (PRD §3.3, §3.8)."""
from test_helpers import (
    validate_success, get_success_data,
    ApiErrorId,
    setup_declared_lost_report,
    TEST_USERS, make_passenger_headers,
)

ADMIN = TEST_USERS["admin_headers"]
AGENT = TEST_USERS["agent_headers"]
ADJUSTER = TEST_USERS["adjuster_headers"]


def _offer(api, ctx, root_cause="MISCONNECT"):
    return api.offer_settlement(
        ctx["report"]["id"],
        {"root_cause": root_cause,
         "root_cause_station_id": ctx["station"]["id"]}, ADJUSTER)


class TestLiabilityCapVariants:

    def _setup_lost_pair(self, api):
        """Two DELAYED reports (international + domestic, both 20kg declared 0),
        both swept to DECLARED_LOST and assessed with contents_loss 100000."""
        ctx_intl = setup_declared_lost_report(is_international=True, weight_kg=20,
                                              declared_value_cents=0)
        ctx_dom = setup_declared_lost_report(is_international=False, weight_kg=20,
                                             declared_value_cents=0)
        for ctx in (ctx_intl, ctx_dom):
            get_success_data(api.assess_loss(ctx["report"]["id"],
                                             {"contents_loss_cents": 100000},
                                             ADJUSTER))
            get_success_data(_offer(api, ctx))
        return ctx_intl, ctx_dom

    def test_identical_loss_divergent_caps(self, api):
        """PRD §3.3: "The `effective_cap_cents` is the greater of a regime base cap
        and the bag's `declared_value_cents`: under the Montreal regime the base cap
        is a flat 170016 cents regardless of weight, while under the domestic regime
        the base cap scales linearly at 2500 cents per checked kilogram of
        `weight_kg` — so the same twenty-kilogram bag carries a base cap of 50000
        cents domestically against 170016 cents internationally."
        PRD §3.8: "The offer is then the lesser of the report's `effective_cap_cents`
        and that loss basis."

        Design: Difficulty/dual_variant_calc/liability_cap_montreal_vs_domestic_weight
        """
        ctx_intl, ctx_dom = self._setup_lost_pair(api)
        rpt_intl = get_success_data(api.get_report(ctx_intl["report"]["id"], ADJUSTER))
        rpt_dom = get_success_data(api.get_report(ctx_dom["report"]["id"], ADJUSTER))
        assert rpt_intl["liability_regime"] == "MONTREAL"
        assert rpt_intl["effective_cap_cents"] == 170016
        assert rpt_intl["settlement_offer_cents"] == 100000
        assert rpt_dom["liability_regime"] == "DOMESTIC"
        assert rpt_dom["effective_cap_cents"] == 50000
        assert rpt_dom["settlement_offer_cents"] == 50000

    def test_domestic_cap_scales_with_weight(self, api):
        """PRD §3.3: "under the domestic regime the base cap scales linearly at 2500
        cents per checked kilogram of `weight_kg` — so the same twenty-kilogram bag
        carries a base cap of 50000 cents domestically against 170016 cents
        internationally."

        Design: Difficulty/dual_variant_calc/liability_cap_montreal_vs_domestic_weight
        """
        # 10kg domestic bag: base cap = 10 * 2500 = 25000.
        ctx = setup_declared_lost_report(is_international=False, weight_kg=10,
                                         declared_value_cents=0)
        get_success_data(api.assess_loss(ctx["report"]["id"],
                                         {"contents_loss_cents": 100000}, ADJUSTER))
        offered = validate_success(_offer(api, ctx), 200)
        assert offered["effective_cap_cents"] == 25000
        assert offered["settlement_offer_cents"] == 25000


class TestDeclaredValueRaisesCap:

    def test_declared_value_raises_effective_cap(self, api):
        """PRD §3.3: "The `effective_cap_cents` is the greater of a regime base cap
        and the bag's `declared_value_cents`"
        PRD §3.8: "The offer is then the lesser of the report's `effective_cap_cents`
        and that loss basis."

        Design: Corner/calculations/declared_value_raises_effective_cap
        """
        ctx = setup_declared_lost_report(is_international=False, weight_kg=20,
                                         declared_value_cents=200000)
        get_success_data(api.assess_loss(ctx["report"]["id"],
                                         {"contents_loss_cents": 150000}, ADJUSTER))
        offered = validate_success(_offer(api, ctx), 200)
        assert offered["effective_cap_cents"] == 200000
        assert offered["settlement_offer_cents"] == 150000

    def test_declared_value_below_base_cap_does_not_lower_cap(self, api):
        """PRD §3.3: "The `effective_cap_cents` is the greater of a regime base cap
        and the bag's `declared_value_cents`"
        PRD §3.3: "under the Montreal regime the base cap is a flat 170016 cents
        regardless of weight"

        Design: Corner/calculations/declared_value_raises_effective_cap
        """
        # Montreal base cap 170016 > declared 50000: cap stays at the base.
        ctx = setup_declared_lost_report(is_international=True, weight_kg=20,
                                         declared_value_cents=50000)
        get_success_data(api.assess_loss(ctx["report"]["id"],
                                         {"contents_loss_cents": 150000}, ADJUSTER))
        offered = validate_success(_offer(api, ctx), 200)
        assert offered["effective_cap_cents"] == 170016
        assert offered["settlement_offer_cents"] == 150000
