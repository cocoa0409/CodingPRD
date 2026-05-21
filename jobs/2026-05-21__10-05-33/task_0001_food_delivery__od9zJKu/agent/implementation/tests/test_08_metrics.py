"""Rider metric computations (§3.3 end)."""
from __future__ import annotations

from app.metrics import compute_bonus_tier, recompute_all

from ._harness import test


@test("bonus_tier boundaries: 0.700 -> SILVER, 0.800 -> GOLD, 0.900 -> PLATINUM")
def t():
    # We need scores that round-half-up to exactly the boundary
    # Score = 0.6*on_time + 0.3*acc + 0.1*(rating/5)
    # Pick on_time=0.7, acc=0.7, rating=5*0.7=3.5 -> score = 0.42 + 0.21 + 0.07 = 0.70 -> SILVER
    assert compute_bonus_tier(0.7, 0.7, 3.5) == "SILVER"
    # 0.8 -> GOLD
    assert compute_bonus_tier(0.8, 0.8, 4.0) == "GOLD"
    # 0.9 -> PLATINUM
    assert compute_bonus_tier(0.9, 0.9, 4.5) == "PLATINUM"
    # Just below 0.7 -> BRONZE
    assert compute_bonus_tier(0.69, 0.69, 3.45) == "BRONZE"


@test("bonus_tier half-up rounding at 3dp")
def t():
    # Compute a score that lands at exactly 0.8995 -> rounds to 0.900 -> PLATINUM
    # 0.6*0.9 + 0.3*0.9 + 0.1*(x/5) = 0.54 + 0.27 + 0.02*x = 0.81 + 0.02x = 0.8995
    # 0.02x = 0.0895 -> x = 4.475
    assert compute_bonus_tier(0.9, 0.9, 4.475) == "PLATINUM"


@test("on_time_rate initializes to 1.0 when fewer than 10 deliveries")
def t():
    rider = {
        "_offer_history": [],
        "_delivery_history": [True] * 5,
        "_rating_history": [],
    }
    recompute_all(rider)
    assert rider["on_time_rate"] == 1.0


@test("on_time_rate window of last 30 once threshold reached")
def t():
    rider = {
        "_offer_history": [],
        "_delivery_history": [True] * 5 + [False] * 5,  # 10 entries, 50% on-time
        "_rating_history": [],
    }
    recompute_all(rider)
    assert abs(rider["on_time_rate"] - 0.5) < 1e-9


@test("acceptance_rate over last 30 offers")
def t():
    rider = {
        "_offer_history": ["ACCEPTED", "REJECTED", "ACCEPTED"],
        "_delivery_history": [],
        "_rating_history": [],
    }
    recompute_all(rider)
    assert abs(rider["acceptance_rate"] - 2/3) < 1e-9
