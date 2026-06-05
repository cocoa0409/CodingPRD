"""Experience modification factor (EMR) and its premium re-rating cascade:
debit vs credit mods, the current_emr update, and modified_premium recomputation.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    setup_lost_time_claim,
    setup_employer,
    read_employer,
    read_policy,
    TEST_USERS,
    ApiErrorId,
)
from test_helpers import factories as f

ADMIN = TEST_USERS["platform_admin_headers"]


def test_experience_mod_debit_surcharges_premium(api):
    """PRD §3.12: "A factor above 1.00 means actual losses exceeded expected and the
    employer pays a surcharge (modified premium above manual)."
    PRD §3.12: "Posting the entry cascades: the employer's current_emr is set to the new
    mod_factor, and the modified_premium_cents is recomputed on every one of that employer's
    policies as the manual premium times the new factor, rounded half-up to whole cents."

    Design: Difficulty/dual_variant_calc/experience_mod_debit_vs_credit_on_premium
    """
    ctx = setup_lost_time_claim(disability_days=10, projected_weeks=12, average_weekly_wage_cents=150_000)
    # claim total_incurred 2700060; low expected inputs -> debit mod
    mod = validate_success(
        api.create_experience_mod(
            f.create_experience_mod_payload(
                ctx["employer"]["id"], 2026, weighting_factor=0.30, ballast_cents=300_000,
                expected_primary_cents=800_000, expected_excess_cents=400_000,
            ),
            ADMIN,
        ),
        201,
    )
    assert mod["mod_factor"] == 1.72, "debit mod: actual losses far exceed low expected"

    employer = read_employer(ctx["employer"]["id"])
    assert employer["current_emr"] == 1.72

    policy = read_policy(ctx["policy"]["id"])
    assert policy["modified_premium_cents"] == 8600000, "5000000 * 1.72"


def test_experience_mod_credit_discounts_premium(api):
    """PRD §3.12: "a factor below 1.00 means losses ran under expected and the employer
    earns a credit (modified premium below manual)."
    PRD §3.12: "the modified_premium_cents is recomputed on every one of that employer's
    policies as the manual premium times the new factor, rounded half-up to whole cents."

    Design: Difficulty/dual_variant_calc/experience_mod_debit_vs_credit_on_premium
    """
    ctx = setup_lost_time_claim(disability_days=10, projected_weeks=12, average_weekly_wage_cents=150_000)
    # same losses, higher expected inputs -> credit mod 0.96
    mod = validate_success(
        api.create_experience_mod(
            f.create_experience_mod_payload(
                ctx["employer"]["id"], 2026, weighting_factor=0.30, ballast_cents=1_000_000,
                expected_primary_cents=1_800_000, expected_excess_cents=1_200_000,
            ),
            ADMIN,
        ),
        201,
    )
    assert mod["mod_factor"] == 0.96

    employer = read_employer(ctx["employer"]["id"])
    assert employer["current_emr"] == 0.96

    policy = read_policy(ctx["policy"]["id"])
    assert policy["modified_premium_cents"] == 4800000, "5000000 * 0.96 < 5000000"


def test_emr_recompute_reprices_existing_policy_premium(api):
    """PRD §3.12: "Posting the entry cascades: the employer's current_emr is set to the new
    mod_factor, and the modified_premium_cents is recomputed on every one of that employer's
    policies as the manual premium times the new factor, rounded half-up to whole cents."

    Design: Corner/cross_cutting_complexity_layers/emr_recompute_repricies_policy_premium
    """
    ctx = setup_lost_time_claim(disability_days=10, projected_weeks=12, average_weekly_wage_cents=150_000)
    get_success_data(
        api.create_experience_mod(
            f.create_experience_mod_payload(
                ctx["employer"]["id"], 2026, weighting_factor=0.30, ballast_cents=300_000,
                expected_primary_cents=800_000, expected_excess_cents=400_000,
            ),
            ADMIN,
        )
    )
    employer = read_employer(ctx["employer"]["id"])
    assert employer["current_emr"] == 1.72
    policy = read_policy(ctx["policy"]["id"])
    assert policy["modified_premium_cents"] == 8600000, "5000000 * 1.72 on a re-read"


def test_experience_mod_duplicate_year_rejected(api):
    """PRD §3.12: "at most one entry may exist per employer per rating year; a duplicate is
    rejected with ERR_DUPLICATE_RESOURCE."

    Design: Corner/errors/experience_mod_duplicate_year_returns_409
    """
    employer = setup_employer()
    get_success_data(
        api.create_experience_mod(
            f.create_experience_mod_payload(
                employer["id"], 2026, weighting_factor=0.30, ballast_cents=1_000_000,
                expected_primary_cents=1_800_000, expected_excess_cents=1_200_000,
            ),
            ADMIN,
        )
    )
    resp = api.create_experience_mod(
        f.create_experience_mod_payload(
            employer["id"], 2026, weighting_factor=0.30, ballast_cents=1_000_000,
            expected_primary_cents=1_800_000, expected_excess_cents=1_200_000,
        ),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_RESOURCE.value)
