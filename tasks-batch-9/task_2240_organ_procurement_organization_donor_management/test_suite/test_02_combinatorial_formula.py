"""Multi-term formulas whose rounding order, nesting and single pass are pinned."""

from test_helpers import (
    CIT_LIMIT_MINUTES,
    RISK_TIER_STANDARD,
    VARIANT_INTERVIEW_BASED,
    accepted_organ,
    assert_instant_equals,
    assert_two_decimal_value,
    book_operation,
    chart_observation,
    converted_case,
    create_asset,
    create_hospital,
    create_referral,
    create_team,
    cross_clamp,
    dispatch_transport,
    observation_payload,
    open_screening,
    read_case,
    read_organ,
    submit_assessment,
)


# ---------------------------------------------------------------------------
# Risk score: round each contribution, then sum
# ---------------------------------------------------------------------------
def _pending_screening(env, mrn="MRN-7101"):
    hospital = create_hospital(env, timely_referral_window_minutes=60)
    referral = create_referral(
        env, hospital["id"], "2026-08-10T10:30:00Z", patient_mrn=mrn
    )
    return open_screening(env, referral["id"])


def test_each_contribution_is_rounded_before_the_contributions_are_added(env):
    """Two factors under a 1.15 multiplier land on 9.21, not on the 9.20 of a late round.

    PRD 3.2: "each contribution is rounded to two decimal places first, and
    only then are the rounded contributions added together."
    PRD 3.2: "Summing the unrounded products and rounding once at the end is
    wrong and differs by whole cents."

    Design: Difficulty/combinatorial_formula/risk_score_rounds_each_contribution_before_summing
    """
    env.set_clock("2026-08-10T11:00:00Z")
    screening = _pending_screening(env)

    scored = submit_assessment(
        env,
        screening["id"],
        screening["version"],
        risk_factors=["IV_DRUG_USE_12MO", "TATTOO_UNREGULATED_12MO"],
        informant_reliability="SECONDARY_CONTACT",
    )

    # 6.50 * 1.15 rounds to 7.48 and 1.50 * 1.15 rounds to 1.73.
    assert_two_decimal_value(scored["risk_score"], 9.21)
    assert float(scored["risk_score"]) != 9.20


def test_contribution_order_and_tier_are_stable_under_client_ordering(env):
    """The canonical weight order governs, whatever order the client sent.

    PRD 3.2: "That listing order is the **canonical order** in which factors are
    scored, and it is used regardless of the order the client sent them in".
    PRD 3.2: "Submitting the assessment also records the submitting operator in
    `risk_assessed_by_user_id`".

    Design: Difficulty/combinatorial_formula/risk_score_rounds_each_contribution_before_summing
    """
    env.set_clock("2026-08-10T11:00:00Z")
    screening = _pending_screening(env)

    scored = submit_assessment(
        env,
        screening["id"],
        screening["version"],
        risk_factors=["TATTOO_UNREGULATED_12MO", "IV_DRUG_USE_12MO"],
        informant_reliability="SECONDARY_CONTACT",
    )

    assert_two_decimal_value(scored["risk_score"], 9.21)
    assert scored["risk_tier"] == RISK_TIER_STANDARD
    assert scored["risk_variant_applied"] == VARIANT_INTERVIEW_BASED
    assert scored["version"] == 2


# ---------------------------------------------------------------------------
# Viability index: nested minimum, maximum and the pressor cap
# ---------------------------------------------------------------------------
def _case_for_observations(env):
    return converted_case(env, "2026-08-10T11:00:00Z", patient_mrn="MRN-7201")


def test_pressor_penalty_below_the_cap_is_subtracted_in_full(env):
    """Two pressors cost ten points off a base of twenty-five.

    PRD 3.4: "A pressor penalty is then computed as five points per infusing
    agent, capped at 15 — the smaller of 15 and five times `pressor_count` — and
    subtracted from the base".
    PRD 3.4: "sodium contributes 15 points when it lies at or between 135 and
    155 inclusive and 5 points otherwise; urine output contributes 10 points at
    1.0 or above, 5 points at 0.5 or above, and 0 below that".

    Design: Difficulty/combinatorial_formula/viability_index_nested_min_max_with_pressor_penalty_cap
    """
    bundle = _case_for_observations(env)

    observation = chart_observation(
        env,
        bundle.case_id,
        observation_payload(
            "2026-08-10T10:40:00Z",
            map_mmhg=65,
            pao2_fio2_ratio=320,
            sodium=148,
            urine_output_ml_per_kg_hr=0.7,
            pressor_count=2,
        ),
    )

    # Oxygenation 40, haemodynamics 25 - 10, metabolic 15 + 5.
    assert observation["viability_index_snapshot"] == 75
    assert observation["dmg_bundle_met"] is False


def test_pressor_penalty_is_capped_and_haemodynamics_floors_at_zero(env):
    """Three pressors cap the penalty at fifteen, which floors a base of ten at zero.

    PRD 3.4: "with the result floored at zero so haemodynamics never
    contributes a negative amount".
    PRD 3.4: "The three components are added and clamped into the range 0
    through 100 to give the observation's `viability_index_snapshot`".

    Design: Difficulty/combinatorial_formula/viability_index_nested_min_max_with_pressor_penalty_cap
    """
    bundle = _case_for_observations(env)

    observation = chart_observation(
        env,
        bundle.case_id,
        observation_payload(
            "2026-08-10T10:50:00Z",
            map_mmhg=55,
            pao2_fio2_ratio=180,
            sodium=160,
            urine_output_ml_per_kg_hr=0.3,
            pressor_count=3,
        ),
    )

    # Oxygenation 15, haemodynamics max(0, 10 - 15), metabolic 5 + 0.
    assert observation["viability_index_snapshot"] == 20
    assert observation["dmg_bundle_met"] is False


def test_case_takes_the_latest_snapshot_and_aggregates_over_all_observations(env):
    """Two charted observations leave the case on the later, lower snapshot.

    PRD 3.4: "The case always takes the index of its **latest** observation,
    where latest means the greatest `recorded_at`, breaking a tie by the
    greatest `created_at`."
    PRD 3.4: "The case's `dmg_bundle_met_count` is refreshed to the number of
    its observations whose `dmg_bundle_met` is true, and `observation_count` to
    the total number of its observations".

    Design: Difficulty/combinatorial_formula/viability_index_nested_min_max_with_pressor_penalty_cap
    """
    bundle = _case_for_observations(env)

    chart_observation(
        env,
        bundle.case_id,
        observation_payload(
            "2026-08-10T10:40:00Z",
            map_mmhg=65,
            pao2_fio2_ratio=320,
            sodium=148,
            urine_output_ml_per_kg_hr=0.7,
            pressor_count=2,
        ),
    )
    chart_observation(
        env,
        bundle.case_id,
        observation_payload(
            "2026-08-10T10:50:00Z",
            map_mmhg=55,
            pao2_fio2_ratio=180,
            sodium=160,
            urine_output_ml_per_kg_hr=0.3,
            pressor_count=3,
        ),
    )

    case = read_case(env, bundle.case_id)
    assert case["viability_index"] == 20
    assert case["physiologic_status"] == "DECOMPENSATING"
    assert case["case_posture"] == "RESTRICTED"
    assert case["observation_count"] == 2
    assert case["dmg_bundle_met_count"] == 0
    assert case["allocation_status"] == "NOT_STARTED"


# ---------------------------------------------------------------------------
# Cold ischemic projection: one pass selects the prep tier
# ---------------------------------------------------------------------------
def _liver_dispatched_on_a_long_leg(env):
    clock = "2026-08-05T05:00:00Z"
    bundle = accepted_organ(
        env, "LIVER", clock, candidate_count=1, primary_offer_slots=2
    )
    bundle.team = create_team(
        env, specialty="ABDOMINAL", turnaround_buffer_minutes=90
    )
    bundle.operation = book_operation(
        env,
        bundle.case_id,
        bundle.team["id"],
        "2026-08-05T05:30:00Z",
        "2026-08-05T09:30:00Z",
    )
    env.set_clock("2026-08-05T06:00:00Z")
    bundle.operation = cross_clamp(env, bundle.operation["id"])
    bundle.asset = create_asset(
        env, mode="FIXED_WING", concurrent_leg_capacity=2
    )
    bundle.organs["LIVER"] = dispatch_transport(
        env,
        bundle.only_organ_id,
        bundle.asset["id"],
        "2026-08-05T07:56:00Z",
        "2026-08-05T16:16:00Z",
        transport_mode="FIXED_WING",
    )
    return bundle


def test_provisional_margin_selects_crash_prep_and_is_not_reselected(env):
    """A provisional margin of 59 picks crash prep, and the final figure keeps it.

    PRD 3.7: "the prep tier is selected from that **provisional** margin — a
    margin of at least 120 minutes selects standard prep at 45 minutes,
    otherwise a margin of at least 60 minutes selects expedited prep at 30
    minutes, otherwise crash prep at 20 minutes".
    PRD 3.7: "the tier is **not** re-selected from this final figure, exactly
    one pass is performed, and no fixed point is sought".

    Design: Difficulty/combinatorial_formula/cold_ischemic_projection_single_pass_prep_tier
    """
    bundle = _liver_dispatched_on_a_long_leg(env)
    organ = bundle.organ("LIVER")

    assert organ["cit_limit_minutes"] == CIT_LIMIT_MINUTES["LIVER"] == 720
    assert organ["transit_minutes"] == 500
    assert organ["implant_prep_minutes"] == 20
    # 116 elapsed + 500 transit + 20 crash prep; a re-selected tier would give 646.
    assert organ["projected_cold_ischemic_minutes"] == 636
    assert organ["projected_cold_ischemic_minutes"] != 646


def test_projected_margin_is_the_ceiling_less_the_projection(env):
    """The stored margin closes the arithmetic against the organ's own ceiling.

    PRD 3.7: "Fourth, `projected_cit_margin_minutes` is the organ's
    `cit_limit_minutes` less `projected_cold_ischemic_minutes`."
    PRD 3.7: "the elapsed cold time so far is the whole minutes from the
    organ's `cross_clamp_at` to `transport_depart_at`".

    Design: Difficulty/combinatorial_formula/cold_ischemic_projection_single_pass_prep_tier
    """
    bundle = _liver_dispatched_on_a_long_leg(env)
    organ = read_organ(env, bundle.only_organ_id)

    assert_instant_equals(organ["cross_clamp_at"], "2026-08-05T06:00:00Z")
    assert organ["status"] == "RECOVERED"
    assert organ["projected_cit_margin_minutes"] == 84
    assert (
        organ["projected_cold_ischemic_minutes"]
        + organ["projected_cit_margin_minutes"]
        == organ["cit_limit_minutes"]
    )


def test_dispatch_is_accepted_when_the_projection_stays_inside_the_ceiling(env):
    """A 636-minute projection under a 720-minute ceiling is dispatched, not refused.

    PRD 3.7: "The gate then rejects the dispatch only when
    `projected_cold_ischemic_minutes` **strictly exceeds** `cit_limit_minutes`".
    PRD 3.5: "twelve hours each for a `LIVER` and a `PANCREAS`".

    Design: Difficulty/combinatorial_formula/cold_ischemic_projection_single_pass_prep_tier
    """
    bundle = _liver_dispatched_on_a_long_leg(env)
    organ = bundle.organ("LIVER")

    assert organ["transport_asset_id"] == bundle.asset["id"]
    assert organ["transport_mode"] == "FIXED_WING"
    assert_instant_equals(organ["transport_depart_at"], "2026-08-05T07:56:00Z")
    assert_instant_equals(organ["transport_arrive_at"], "2026-08-05T16:16:00Z")
    assert organ["projected_cold_ischemic_minutes"] <= organ["cit_limit_minutes"]
