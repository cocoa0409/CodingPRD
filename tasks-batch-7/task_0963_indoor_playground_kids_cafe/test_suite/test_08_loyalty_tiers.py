"""Loyalty tier assignment thresholds (PRD §3.9)."""
import pytest

from test_helpers import (
    validate_success, ApiErrorId,
    setup_staff_trio, register_guardian, seed_points, run_ops_as_admin,
    get_guardian_fresh, guardian_headers,
)
from test_helpers import api_client  # noqa: F401


class TestLoyaltyTierBoundaries:
    def test_loyalty_tier_exactly_1000_promotes(self, api):
        """PRD §3.9: "a guardian whose `lifetime_points` reaches at least
        5,000 is `GOLD`, at least 1,000 is `SILVER` (the boundary is inclusive
        — exactly 1,000 is `SILVER`, exactly 5,000 is `GOLD`), and otherwise
        `BRONZE`." and the operations sweep "recomputes loyalty tiers from
        `lifetime_points`".

        Exactly 1,000 promotes to SILVER; 999 stays BRONZE.

        Design: Difficulty/boundary_precision_check/loyalty_tier_exactly_1000_promotes
        """
        staff = setup_staff_trio()
        ga = register_guardian("G A", "ga3@x.com", "201")
        gb = register_guardian("G B", "gb3@x.com", "202")
        seed_points(ga, staff["mgr_headers"], 1000, note="promo")
        seed_points(gb, staff["mgr_headers"], 999, note="promo")

        run_ops_as_admin()

        a = get_guardian_fresh(ga["id"], guardian_headers(ga))
        b = get_guardian_fresh(gb["id"], guardian_headers(gb))
        assert a["lifetime_points"] == 1000
        assert a["loyalty_tier"] == "SILVER", "inclusive >= threshold at 1000"
        assert b["lifetime_points"] == 999
        assert b["loyalty_tier"] == "BRONZE", "one below the threshold stays BRONZE"

    def test_loyalty_tier_exactly_5000_promotes_to_gold(self, api):
        """PRD §3.9: "a guardian whose `lifetime_points` reaches at least
        5,000 is `GOLD`, at least 1,000 is `SILVER` (the boundary is inclusive
        — exactly 1,000 is `SILVER`, exactly 5,000 is `GOLD`), and otherwise
        `BRONZE`."

        Exactly 5,000 promotes to GOLD; 4,999 is SILVER.

        Design: Difficulty/boundary_precision_check/loyalty_tier_exactly_1000_promotes
        """
        staff = setup_staff_trio()
        ga = register_guardian("G C", "gc4@x.com", "203")
        gb = register_guardian("G D", "gd4@x.com", "204")
        seed_points(ga, staff["mgr_headers"], 5000, note="promo")
        seed_points(gb, staff["mgr_headers"], 4999, note="promo")

        run_ops_as_admin()

        a = get_guardian_fresh(ga["id"], guardian_headers(ga))
        b = get_guardian_fresh(gb["id"], guardian_headers(gb))
        assert a["loyalty_tier"] == "GOLD"
        assert b["loyalty_tier"] == "SILVER"
