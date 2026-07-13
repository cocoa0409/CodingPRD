"""VI-SPDAT scoring depth tests: provisional vs verified variant, the acuity boundary at 8,
and the four-part prioritization rank_score formula.

Every test translates exactly one instance from the difficulty design index (queue A).
"""
from test_helpers import (
    api_client, validate_success, get_success_data,
    create_client_payload, create_assessment_payload,
    create_prioritization_entry_payload,
    new_client, new_assessment, new_active_consent, new_pool_entry,
    TEST_USERS,
)

INTAKE = TEST_USERS["intake_headers"]
ADMIN = TEST_USERS["hmis_admin_headers"]


# ─── dual_variant_calc / dv_assessment_provisional_vs_verified_tier ────────────
def test_provisional_score_ignores_verification_delta_while_draft(api):
    """PRD §3.1: "While it is `DRAFT`, its `provisional_score` is simply the
    `self_report_points`, ignoring the delta."

    Design: Difficulty/dual_variant_calc/dv_assessment_provisional_vs_verified_tier
    """
    client = new_client(full_name="Ada Vuln", dob="1990-01-01")
    res = api.create_assessment(
        create_assessment_payload(client["id"], self_report_points=7, verification_delta=1),
        INTAKE)
    asm = validate_success(res, 201)
    assert asm["provisional_score"] == 7, "provisional score must equal self_report_points"


def test_verified_score_and_high_tier_on_completion(api):
    """PRD §3.1: "Completing the assessment computes the `verified_score` as the
    `self_report_points` plus the `verification_delta`, clamped to the range 0 through 17
    (values below 0 become 0, values above 17 become 17)."
    PRD §3.1: "the subject client's `vulnerability_score` is set to that verified score with
    `acuity_tier` recomputed."
    PRD §3.1: "If the score is at least 8, the tier is `HIGH`, which recommends the `PSH` track."

    Design: Difficulty/dual_variant_calc/dv_assessment_provisional_vs_verified_tier
    """
    client = new_client(full_name="Ada Vuln", dob="1990-01-01")
    asm = get_success_data(api.create_assessment(
        create_assessment_payload(client["id"], self_report_points=7, verification_delta=1),
        INTAKE))
    completed = validate_success(api.complete_assessment(asm["id"], INTAKE), 200)
    assert completed["verified_score"] == 8
    assert completed["recommended_track"] == "PSH"

    client_after = validate_success(api.get_client(client["id"], INTAKE), 200)
    assert client_after["vulnerability_score"] == 8
    assert client_after["acuity_tier"] == "HIGH"


# ─── boundary_precision_check / bnd_acuity_tier_threshold_eight ────────────────
def test_acuity_tier_high_at_score_exactly_eight(api):
    """PRD §3.1: "If the score is at least 8, the tier is `HIGH`, which recommends the
    `PSH` track."

    Design: Difficulty/boundary_precision_check/bnd_acuity_tier_threshold_eight
    """
    client = new_client(full_name="Hi Eight", dob="1990-01-08")
    asm = get_success_data(api.create_assessment(
        create_assessment_payload(client["id"], self_report_points=8), INTAKE))
    api.complete_assessment(asm["id"], INTAKE)
    client_after = validate_success(api.get_client(client["id"], INTAKE), 200)
    assert client_after["vulnerability_score"] == 8
    assert client_after["acuity_tier"] == "HIGH"


def test_acuity_tier_moderate_just_below_eight(api):
    """PRD §3.1: "Otherwise, if the score is at least 4, the tier is `MODERATE`, which
    recommends the `RRH` track."

    Design: Difficulty/boundary_precision_check/bnd_acuity_tier_threshold_eight
    """
    client = new_client(full_name="Lo Seven", dob="1990-01-07")
    asm = get_success_data(api.create_assessment(
        create_assessment_payload(client["id"], self_report_points=7), INTAKE))
    api.complete_assessment(asm["id"], INTAKE)
    client_after = validate_success(api.get_client(client["id"], INTAKE), 200)
    assert client_after["vulnerability_score"] == 7
    assert client_after["acuity_tier"] == "MODERATE"


# ─── combinatorial_formula / comb_prioritization_rank_tiered ───────────────────
def test_prioritization_rank_score_four_part_composition(api):
    """PRD §3.6: "The first is a tier weight from the client's `acuity_tier`: 1000 for
    `HIGH`, 500 for `MODERATE`, 100 for `LOW`, and 0 for an unscored client whose tier is null."
    PRD §3.6: "The second is a chronic bonus of 300 if the client's `chronic_homeless` flag
    is set, and 0 otherwise."
    PRD §3.6: "The third is a time-homeless contribution: if the client's `months_homeless`
    is at least 12, it contributes 200; otherwise, if `months_homeless` is at least 6, it
    contributes 100; otherwise it contributes the `months_homeless` multiplied by 10."
    PRD §3.6: "The fourth is a household factor equal to the smaller of the client's
    `household_size` and 5, multiplied by 20 (so household size is capped at 5 for this purpose)."
    PRD §3.6: "The `rank_score` is the sum of these four contributions."

    Design: Difficulty/combinatorial_formula/comb_prioritization_rank_tiered
    """
    # HIGH tier (1000) + chronic (300) + months>=12 (200) + min(2,5)*20 (40) = 1540
    client = new_client(full_name="Ravi Rank", dob="1979-03-03",
                        household_size=2, months_homeless=12, chronic_homeless=True)
    asm = new_assessment(client["id"], self_report_points=10)
    api.complete_assessment(asm["id"], INTAKE)
    new_active_consent(client["id"])

    pe = validate_success(api.create_prioritization_entry(
        create_prioritization_entry_payload(client["id"]), ADMIN), 201)
    assert pe["rank_score"] == 1540, f"expected 1540, got {pe['rank_score']}"


def test_prioritization_client_scored_high_before_pooling(api):
    """PRD §3.1: "If the score is at least 8, the tier is `HIGH`, which recommends the
    `PSH` track."

    Design: Difficulty/combinatorial_formula/comb_prioritization_rank_tiered
    """
    client = new_client(full_name="Ravi Rank", dob="1979-03-03",
                        household_size=2, months_homeless=12, chronic_homeless=True)
    asm = new_assessment(client["id"], self_report_points=10)
    api.complete_assessment(asm["id"], INTAKE)
    client_after = validate_success(api.get_client(client["id"], INTAKE), 200)
    assert client_after["acuity_tier"] == "HIGH"
