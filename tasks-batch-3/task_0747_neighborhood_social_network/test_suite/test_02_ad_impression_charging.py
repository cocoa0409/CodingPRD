"""LocalAd impression-charging tests — waterfall allocation, EXHAUSTED transition."""
import pytest

from test_helpers import (
    get_success_data, validate_success,
    make_business_owner_headers,
    setup_business_owner_scaffold, create_running_local_ad,
    set_clock, api_client, ADMIN,
)


# PRD §3.8 / §4 endpoint table: `POST /neighborhood/local-ads/{id}/serve-impression`
# is authorized only for `PlatformAdmin`. Impression-serving must use ADMIN headers.


class TestAdImpressionUnderbidVariant:
    """Difficulty rule 1 dual-variant on LocalAd — last impression caps at
    remaining, not the full bid."""

    def test_second_impression_caps_at_remaining_and_transitions_exhausted(self, api):
        """PRD §3.8: "the impression `charge` is set to the smaller of
        `bid_cents_per_impression` and `remaining` — meaning the ordinary
        charge is exactly `bid_cents_per_impression`, but on the last
        impression before exhaustion the charge is capped at the exact
        remaining budget, so `spend_cents` never exceeds `budget_cents` even
        at the boundary."
        PRD §3.8: "the ad's `spend_cents` is incremented by that charge and,
        if the new `spend_cents` is at least `budget_cents`, the same response
        transitions the ad from `RUNNING` to the terminal `EXHAUSTED` state as
        the last step; the cap and the state transition happen in the same
        impression response."

        Design: Difficulty/dual_variant_calc/ad_impression_charge_last_impression_underbid_variant_caps_charge_at_remaining
        """
        set_clock("2026-06-01T00:00:00Z")
        n, mod, r, biz = setup_business_owner_scaffold()
        ad = create_running_local_ad(
            biz["id"], [n["id"]],
            budget_cents=1200, bid_cents_per_impression=1000,
        )
        # First impression: full bid 1000 -> spend 1000, remaining 200, RUNNING.
        r1 = get_success_data(api_client.serve_impression(
            ad["id"], {"neighborhood_id": n["id"]},
            ADMIN,
        ))
        assert r1["spend_cents"] == 1000
        assert r1["state"] == "RUNNING"
        # Second impression: charge = min(1000, 200) = 200, EXHAUSTED.
        r2 = get_success_data(api_client.serve_impression(
            ad["id"], {"neighborhood_id": n["id"]},
            ADMIN,
        ))
        assert r2["spend_cents"] == 1200, \
            f"Expected spend_cents=1200 (capped at budget), got {r2['spend_cents']}"
        assert r2["state"] == "EXHAUSTED", \
            f"Expected state=EXHAUSTED after last impression, got {r2['state']}"

    def test_spend_cents_never_exceeds_budget_cents(self, api):
        """PRD §3.8: "on the last impression before exhaustion the charge is
        capped at the exact remaining budget, so `spend_cents` never exceeds
        `budget_cents` even at the boundary."

        Design: Difficulty/dual_variant_calc/ad_impression_charge_last_impression_underbid_variant_caps_charge_at_remaining
        """
        set_clock("2026-06-01T00:00:00Z")
        n, mod, r, biz = setup_business_owner_scaffold()
        ad = create_running_local_ad(
            biz["id"], [n["id"]],
            budget_cents=1200, bid_cents_per_impression=1000,
        )
        get_success_data(api_client.serve_impression(
            ad["id"], {"neighborhood_id": n["id"]},
            ADMIN,
        ))
        r2 = get_success_data(api_client.serve_impression(
            ad["id"], {"neighborhood_id": n["id"]},
            ADMIN,
        ))
        assert r2["spend_cents"] <= ad["budget_cents"], \
            "spend_cents must never exceed budget_cents"


class TestAdImpressionChargeCombinatorialMode:
    """Difficulty rule 2 combinatorial formula (mode a — three-input min)."""

    def test_charge_is_smaller_of_bid_and_remaining(self, api):
        """PRD §3.8: "the impression `charge` is set to the smaller of
        `bid_cents_per_impression` and `remaining` — meaning the ordinary
        charge is exactly `bid_cents_per_impression`, but on the last
        impression before exhaustion the charge is capped at the exact
        remaining budget, so `spend_cents` never exceeds `budget_cents` even
        at the boundary."

        With budget=500, bid=1000, spend=0: remaining=500 -> charge=min(1000,500)=500.
        The three-input min collapses to remaining and the ad exhausts on the
        first impression.

        Design: Difficulty/combinatorial_formula/ad_impression_charge_mode_a_nested_min_over_three_inputs
        """
        set_clock("2026-06-01T00:00:00Z")
        n, mod, r, biz = setup_business_owner_scaffold()
        ad = create_running_local_ad(
            biz["id"], [n["id"]],
            budget_cents=1000, bid_cents_per_impression=2000,  # bid > budget
        )
        r1 = get_success_data(api_client.serve_impression(
            ad["id"], {"neighborhood_id": n["id"]},
            ADMIN,
        ))
        # remaining = 1000, charge = min(2000, 1000) = 1000; spend = 1000.
        assert r1["spend_cents"] == 1000, \
            f"Expected charge collapsed to remaining=1000, got spend={r1['spend_cents']}"
        assert r1["state"] == "EXHAUSTED", \
            f"Expected EXHAUSTED after single impression saturating budget, got {r1['state']}"

    def test_first_impression_bid_wins_when_bid_lt_remaining(self, api):
        """PRD §3.8: "the impression `charge` is set to the smaller of
        `bid_cents_per_impression` and `remaining` — meaning the ordinary
        charge is exactly `bid_cents_per_impression`, but on the last
        impression before exhaustion the charge is capped at the exact
        remaining budget, so `spend_cents` never exceeds `budget_cents` even
        at the boundary."

        With budget=5000, bid=100: remaining=5000 -> charge=100, spend=100,
        state RUNNING (still 4900 remaining).

        Design: Difficulty/combinatorial_formula/ad_impression_charge_mode_a_nested_min_over_three_inputs
        """
        set_clock("2026-06-01T00:00:00Z")
        n, mod, r, biz = setup_business_owner_scaffold()
        ad = create_running_local_ad(
            biz["id"], [n["id"]],
            budget_cents=5000, bid_cents_per_impression=100,
        )
        r1 = get_success_data(api_client.serve_impression(
            ad["id"], {"neighborhood_id": n["id"]},
            ADMIN,
        ))
        assert r1["spend_cents"] == 100, \
            f"Expected charge=bid=100 when bid<remaining, got {r1['spend_cents']}"
        assert r1["state"] == "RUNNING", \
            f"Expected RUNNING after non-exhausting impression, got {r1['state']}"
