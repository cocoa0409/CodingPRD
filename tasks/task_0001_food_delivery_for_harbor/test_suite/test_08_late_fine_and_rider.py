"""Late-delivery fine tiers and rider cascade (PRD §3.3, §3.7).

Covers:
- On-time delivery → minutes_late == 0 and no Fine
- Tier 1 (1 ≤ minutes_late ≤ 10) → flat 200 cents
- Tier 2 (11 ≤ minutes_late ≤ 30) → 500 + 50*(m-10)
- Tier 3 (minutes_late > 30) → min(final_delivery_fee_cents, 1500) + 500
- Late fine debits rider wallet and recomputes bonus_tier (cascade chain)
"""

import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    advance_clock_seconds,
    get_success_data,
    make_rider_headers,
    run_order_deliver_with_lateness,
    run_order_to_delivered,
    validate_error,
    validate_success,
)


class TestOnTimeDelivery:
    def test_on_time_delivery_no_fine(self, api):
        """PRD §3.7: "minutes_late is computed as the non-negative floor of the seconds
        between actual_delivery_time and promised_delivery_time, divided by 60. Early or
        on-time deliveries produce a minutes_late of zero."

        Claim: delivery within promised window → minutes_late == 0 and no fine created.
        """
        ctx = run_order_to_delivered(distance_km=2.0)
        assert ctx["order"]["minutes_late"] == 0
        # Look up fines filtered by this rider; PRD §3.11 guarantees a list endpoint.
        rider_id = ctx["rider"]["id"]
        admin = TEST_USERS["admin_headers"]
        data, _ = _list_fines(api, admin, {"subject_type": "RIDER", "subject_id": rider_id})
        late_fines = [f for f in data if f.get("reason") == "LATE_DELIVERY"]
        assert late_fines == [], "no LATE_DELIVERY fine expected on on-time delivery"


class TestLateFineTier1:
    def test_five_minutes_late_flat_200_cents(self, api):
        """PRD §3.7: "when minutes_late is from 1 through 10 inclusive, amount_cents is a
        flat 200 cents (a two-dollar penalty)."

        Claim: minutes_late=5 → Fine amount_cents == 200.
        """
        ctx = run_order_deliver_with_lateness(minutes_late=5, distance_km=2.0)
        order = ctx["order"]
        assert order["minutes_late"] == 5
        fine = _find_late_fine(api, ctx["rider"]["id"])
        assert fine is not None
        assert fine["amount_cents"] == 200

    def test_ten_minutes_late_still_flat_200_cents(self, api):
        """PRD §3.7: "when minutes_late is from 1 through 10 inclusive, amount_cents is a
        flat 200 cents."

        Claim: minutes_late=10 (inclusive boundary) → amount_cents == 200.
        """
        ctx = run_order_deliver_with_lateness(minutes_late=10, distance_km=2.0)
        assert ctx["order"]["minutes_late"] == 10
        fine = _find_late_fine(api, ctx["rider"]["id"])
        assert fine is not None
        assert fine["amount_cents"] == 200


class TestLateFineTier2:
    def test_eleven_minutes_is_tier2_boundary(self, api):
        """PRD §3.7: "when minutes_late is from 11 through 30 inclusive, amount_cents is
        500 plus 50 per minute over 10."

        Claim: minutes_late=11 → 500 + 50*1 = 550 cents.
        """
        ctx = run_order_deliver_with_lateness(minutes_late=11, distance_km=2.0)
        assert ctx["order"]["minutes_late"] == 11
        fine = _find_late_fine(api, ctx["rider"]["id"])
        assert fine is not None
        assert fine["amount_cents"] == 550

    def test_twenty_minutes_yields_1000_cents(self, api):
        """PRD §3.7: "so a 20-minute lateness yields 500 plus 50 times 10, which is 1 000
        cents."

        Claim: minutes_late=20 → amount_cents == 1000.

        # difficulty: combinatorial_formula/late_fine_conditional_formula_with_three_inputs
        """
        ctx = run_order_deliver_with_lateness(minutes_late=20, distance_km=2.0)
        assert ctx["order"]["minutes_late"] == 20
        fine = _find_late_fine(api, ctx["rider"]["id"])
        assert fine is not None
        assert fine["amount_cents"] == 1000


class TestLateFineTier3:
    def test_above_thirty_minutes_uses_cap_and_compensation(self, api):
        """PRD §3.7: "when minutes_late exceeds 30, amount_cents is the smaller of
        final_delivery_fee_cents and 1 500 (the rider's earnings clawback is capped at
        $15 regardless of the fee) plus an additional 500 cents of customer compensation."

        Claim: minutes_late=35 with solo off-peak 540-cent fee → min(540, 1500) + 500 = 1040.

        # difficulty: transitive_cascade/deliver_order_cascade_to_rider_tier_via_fine
        """
        ctx = run_order_deliver_with_lateness(minutes_late=35, distance_km=2.0)
        order = ctx["order"]
        if not order["is_peak"]:
            # Off-peak: solo_fee = 300 + 2*120 = 540 cents.
            expected_fine = min(order["final_delivery_fee_cents"], 1500) + 500
            assert order["minutes_late"] == 35
            assert expected_fine == 1040
            fine = _find_late_fine(api, ctx["rider"]["id"])
            assert fine is not None
            assert fine["amount_cents"] == 1040
        else:
            # Peak: solo_fee = 740. fine = min(740, 1500) + 500 = 1240.
            fine = _find_late_fine(api, ctx["rider"]["id"])
            assert fine is not None
            assert fine["amount_cents"] == min(order["final_delivery_fee_cents"], 1500) + 500


class TestRiderCascadeFromLateDelivery:
    def test_rider_wallet_net_credit_minus_late_fine(self, api):
        """PRD §3.7: "This fine creation itself triggers a follow-on debit of the rider's
        wallet_balance_cents by amount_cents and a recomputation of the rider's
        bonus_tier."
        PRD §3.7: "the rider's wallet_balance_cents is credited with the reconciled
        Assignment.final_delivery_fee_cents".

        Claim: Rider.wallet_balance_cents after late delivery == +delivery_fee - fine_amount.

        # difficulty: combinatorial_formula/late_fine_conditional_formula_with_three_inputs
        """
        ctx = run_order_deliver_with_lateness(minutes_late=20, distance_km=2.0)
        order = ctx["order"]
        rider = ctx["rider"]
        fine = _find_late_fine(api, rider["id"])
        assert fine is not None
        expected = order["final_delivery_fee_cents"] - fine["amount_cents"]
        assert rider["wallet_balance_cents"] == expected


class TestRiderBonusTierRecompute:
    def test_on_time_delivery_recomputes_tier(self, api):
        """PRD §3.3: "On every completed delivery (PICKED_UP → DELIVERED on an
        Assignment) … the system recomputes the tier."

        Claim: after an on-time delivery, the rider's bonus_tier is present and legal.
        """
        ctx = run_order_to_delivered(distance_km=2.0)
        tier = ctx["rider"]["bonus_tier"]
        assert tier in ("BRONZE", "SILVER", "GOLD", "PLATINUM")

    def test_new_rider_completing_on_time_remains_platinum(self, api):
        """PRD §3.3: "on_time_rate … is initialized to 1.0 for riders with fewer than 10
        completed deliveries"; "acceptance_rate is the fraction of the rider's last 30
        dispatch offers … likewise initialized to 1.0"; "rating … initialized at 5.0";
        "a score of 0.90 or more is PLATINUM."

        Claim: a fresh rider completing one on-time delivery — with initial metrics
        (1.0, 1.0, 5.0) — yields score = 0.6 + 0.3 + 0.1 = 1.000 → PLATINUM.

        # difficulty: boundary_precision_check/rider_bonus_tier_platinum_boundary_exact_0_90
        """
        ctx = run_order_to_delivered(distance_km=2.0)
        assert ctx["order"]["minutes_late"] == 0
        assert ctx["rider"]["bonus_tier"] == "PLATINUM"


# ──────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────

def _list_fines(api, headers, params):
    res = api.list_fines(headers, params=params)
    body = res.json()
    assert body.get("response_type") == "array", f"expected array envelope, got {body!r}"
    return body["data"], body.get("meta", {})


def _find_late_fine(api, rider_id: str):
    """Return the most recent LATE_DELIVERY fine for *rider_id*, or None."""
    admin = TEST_USERS["admin_headers"]
    data, _ = _list_fines(api, admin, {"subject_type": "RIDER", "subject_id": rider_id,
                                        "settlement_status": "PENDING"})
    late_fines = [f for f in data if f.get("reason") == "LATE_DELIVERY"]
    return late_fines[-1] if late_fines else None
