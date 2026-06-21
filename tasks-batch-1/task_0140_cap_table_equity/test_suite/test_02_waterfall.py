"""Liquidation-preference waterfall: non-participating vs participating-capped
preferred allocations. Expected totals are derived literally from PRD §3.12.
"""
from test_helpers import (
    TEST_USERS,
    setup_computed_waterfall,
    get_distribution_for_class,
)

AUDITOR = TEST_USERS["auditor_headers"]


# ============================================================================
# Difficulty/dual_variant_calc/waterfall_non_participating_vs_participating_capped
# ============================================================================

def test_waterfall_non_participating_preferred_takes_pref_only(api):
    """PRD §3.12: "A non-participating preferred class has already taken its
    preference and does not share in the residual at all; instead its economics
    are the *greater* of its preference or its as-converted pro-rata share, and
    it never takes both."

    Series A 1x non-part, 100000 sh oip=500c → pref = 50,000,000c. Its pro-rata
    (40M) is less than its pref, so it takes 50M only and does not join Pass 2.

    Design: Difficulty/dual_variant_calc/waterfall_non_participating_vs_participating_capped
    """
    env = setup_computed_waterfall(
        classes=[
            {"key": "A", "name": "Series A", "class_type": "PREFERRED", "oip": 500,
             "pref_multiple": 1.0, "participating": False, "senior_to": None, "shares": 100000},
            {"key": "C", "name": "Common", "class_type": "COMMON", "oip": 0,
             "pref_multiple": 0, "senior_to": "A", "shares": 400000},
        ],
        proceeds_cents=200_000_000, email_suffix="np",
    )
    dist_a = get_distribution_for_class(env["event"]["id"], env["classes"]["A"]["id"])
    assert dist_a["total_paid_cents"] == 50_000_000, (
        f"expected 50,000,000 (pref only), got {dist_a['total_paid_cents']}"
    )


def test_waterfall_non_participating_common_takes_full_residual(api):
    """PRD §3.12: "The participating set — every `COMMON` class plus every
    participating preferred class — shares the residual in proportion to
    `shares_outstanding`: each such class's raw participation is the remaining
    proceeds multiplied by its `shares_outstanding` divided by the total
    participating shares (the summed `shares_outstanding` of all common and
    participating-preferred classes), rounded half-up."

    With non-participating preferred excluded from Pass 2, Common (400000 sh) is
    the only participating class and takes the full residual 150,000,000c.

    Design: Difficulty/dual_variant_calc/waterfall_non_participating_vs_participating_capped
    """
    env = setup_computed_waterfall(
        classes=[
            {"key": "A", "name": "Series A", "class_type": "PREFERRED", "oip": 500,
             "pref_multiple": 1.0, "participating": False, "senior_to": None, "shares": 100000},
            {"key": "C", "name": "Common", "class_type": "COMMON", "oip": 0,
             "pref_multiple": 0, "senior_to": "A", "shares": 400000},
        ],
        proceeds_cents=200_000_000, email_suffix="np2",
    )
    dist_c = get_distribution_for_class(env["event"]["id"], env["classes"]["C"]["id"])
    assert dist_c["total_paid_cents"] == 150_000_000, (
        f"expected 150,000,000 (full residual), got {dist_c['total_paid_cents']}"
    )


def test_waterfall_participating_capped_preferred_takes_pref_plus_capped_participation(api):
    """PRD §3.12: "For a participating preferred class that carries a positive
    `participation_cap_multiple`, the total it may receive is capped: the cap
    total is its `participation_cap_multiple` times its invested capital (rounded
    half-up), the allowed participation is that cap total minus what it already
    received as `preference_paid_cents` (never below zero), and its
    `participation_paid_cents` is the lesser of its raw participation and that
    allowed amount."

    Series A 1x pref, cap 2x, 100000 sh oip=500c: pref 50M; raw participation
    30M; cap_total 100M; allowed = 100M-50M = 50M; participation = min(30M,50M)
    = 30M; total = 80,000,000c.

    Design: Difficulty/dual_variant_calc/waterfall_non_participating_vs_participating_capped
    """
    env = setup_computed_waterfall(
        classes=[
            {"key": "A", "name": "Series A", "class_type": "PREFERRED", "oip": 500,
             "pref_multiple": 1.0, "participating": True, "cap_multiple": 2.0,
             "senior_to": None, "shares": 100000},
            {"key": "C", "name": "Common", "class_type": "COMMON", "oip": 0,
             "pref_multiple": 0, "senior_to": "A", "shares": 400000},
        ],
        proceeds_cents=200_000_000, email_suffix="pc",
    )
    dist_a = get_distribution_for_class(env["event"]["id"], env["classes"]["A"]["id"])
    assert dist_a["preference_paid_cents"] == 50_000_000, (
        f"expected pref 50,000,000, got {dist_a['preference_paid_cents']}"
    )
    assert dist_a["total_paid_cents"] == 80_000_000, (
        f"expected total 80,000,000 (50M pref + 30M participation), got {dist_a['total_paid_cents']}"
    )


def test_waterfall_participating_common_takes_pro_rata_residual(api):
    """PRD §3.12: "Every other participating class records its raw share as
    `participation_paid_cents`. Each class's `total_paid_cents` is its
    `preference_paid_cents` plus its `participation_paid_cents`."

    Common (400000 sh) raw participation = 150,000,000 * 400000/500000 =
    120,000,000c; it carries no preference, so total = 120,000,000c.

    Design: Difficulty/dual_variant_calc/waterfall_non_participating_vs_participating_capped
    """
    env = setup_computed_waterfall(
        classes=[
            {"key": "A", "name": "Series A", "class_type": "PREFERRED", "oip": 500,
             "pref_multiple": 1.0, "participating": True, "cap_multiple": 2.0,
             "senior_to": None, "shares": 100000},
            {"key": "C", "name": "Common", "class_type": "COMMON", "oip": 0,
             "pref_multiple": 0, "senior_to": "A", "shares": 400000},
        ],
        proceeds_cents=200_000_000, email_suffix="pc2",
    )
    dist_c = get_distribution_for_class(env["event"]["id"], env["classes"]["C"]["id"])
    assert dist_c["total_paid_cents"] == 120_000_000, (
        f"expected 120,000,000, got {dist_c['total_paid_cents']}"
    )
