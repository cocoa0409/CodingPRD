"""Dual-variant readings and multi-factor formulas of the Neonatal Network API.

Covers the two level variants and the triage weighting of PRD §3.3, the crude
versus device-adjusted infection rates of PRD §3.9, the committed versus forecast
capacity projection and the per-acuity-band nursing requirement of PRD §2.8, the
surge tier, waiver and bed arithmetic of PRD §3.5, and the weighted designation
compliance score with its transport capability cap of PRD §3.2.
"""

from test_helpers import (
    ApiErrorId,
    assertions,
    factories,
    fixtures,
    validate_error,
    validate_success,
)

# ---------------------------------------------------------------------------
# Shared preconditions, all built through documented endpoints
# ---------------------------------------------------------------------------

MATERNAL_CASE = {
    "referral_kind": "MATERNAL_ANTENATAL",
    "gestational_age_weeks": 30.0,
    "birth_weight_grams": 1300,
    "support_modality": "ROOM_AIR",
}

INBOUND_LEVEL_III_CASE = {
    "referral_kind": "INBOUND_NEONATAL",
    "gestational_age_weeks": 29.0,
    "birth_weight_grams": 1200,
    "support_modality": "ROOM_AIR",
}

INBOUND_LEVEL_I_CASE = {
    "referral_kind": "INBOUND_NEONATAL",
    "gestational_age_weeks": 34.0,
    "birth_weight_grams": 2000,
    "support_modality": "ROOM_AIR",
}


def _clabsi_cohort(env):
    """Admit a 900 gram infant, give it a central-line day and drive its
    infection dimension to CONFIRMED_CLABSI, then admit a 2000 gram infant with
    no infection, so the period holds a cohort of two and one infection."""
    small = fixtures.admit_case(
        env,
        case_reference="CASE-S1",
        gestational_age_weeks=29.0,
        birth_weight_grams=900,
        support_modality="ROOM_AIR",
    )
    fixtures.care_update(
        env,
        small["id"],
        current_weight_grams=950,
        support_modality="CPAP",
        central_line_present=True,
        ventilated=False,
    )
    fixtures.infection_event(env, small["id"], "SUSPECT")
    fixtures.infection_event(env, small["id"], "CONFIRM_CLABSI")
    large = fixtures.admit_case(
        env,
        case_reference="CASE-S2",
        gestational_age_weeks=34.0,
        birth_weight_grams=2000,
        support_modality="ROOM_AIR",
    )
    return small, large


def _report_for_the_august_period(api, env):
    return validate_success(
        api.create_surveillance_report(
            factories.surveillance_report_payload(
                env["unit_a_id"],
                period_start="2026-08-01T00:00:00Z",
                period_end="2026-08-31T23:59:59Z",
                reported_patient_days=500,
                reported_central_line_days=120,
            ),
            env["dir_a"],
        ),
        201,
    )


def _committed_and_forecast_picture(env):
    """Fill the four staffed beds of the regional unit with two admissions — one
    of them attested back-transfer ready — and two live holds, one antenatal and
    one inbound, then move the clock to 55 minutes before the inbound hold ends."""
    fixtures.set_clock("2026-08-02T00:00:00Z")

    fixtures.admit_case(env, case_reference="CASE-C1", **INBOUND_LEVEL_I_CASE)

    ready = fixtures.admit_case(env, case_reference="CASE-C2", **INBOUND_LEVEL_I_CASE)
    fixtures.care_update(
        env,
        ready["id"],
        current_weight_grams=2050,
        support_modality="ROOM_AIR",
        central_line_present=False,
        ventilated=False,
    )
    fixtures.developmental_rounds(
        env,
        ready["id"],
        count=2,
        kangaroo_care_minutes=60,
        family_presence_minutes=240,
        cluster_care_compliant=True,
        light_cycling_compliant=False,
    )
    fixtures.attest_back_transfer_ready(
        env,
        ready["id"],
        back_transfer_attestation_note="Growing, room air, feeding",
    )

    maternal = fixtures.create_referral(env, case_reference="CASE-C3", **MATERNAL_CASE)
    maternal_accepted = fixtures.accept_referral(env, maternal["id"])

    inbound = fixtures.create_referral(env, case_reference="CASE-C4", **INBOUND_LEVEL_I_CASE)
    inbound_accepted = fixtures.accept_referral(env, inbound["id"])

    fixtures.set_clock("2026-08-02T03:05:00Z")
    return maternal_accepted, inbound_accepted


def _one_infant_in_each_acuity_band(env):
    """Admit three infants whose weights place one in each of the LEVEL_III,
    LEVEL_II and LEVEL_I acuity bands."""
    level_three = fixtures.admit_case(
        env,
        case_reference="CASE-N3",
        gestational_age_weeks=29.0,
        birth_weight_grams=1200,
        support_modality="ROOM_AIR",
    )
    level_two = fixtures.admit_case(
        env,
        case_reference="CASE-N2",
        gestational_age_weeks=34.0,
        birth_weight_grams=1600,
        support_modality="ROOM_AIR",
    )
    level_one = fixtures.admit_case(
        env,
        case_reference="CASE-N1B",
        gestational_age_weeks=38.0,
        birth_weight_grams=2600,
        support_modality="ROOM_AIR",
    )
    return level_three, level_two, level_one


def _full_census_with_two_surge_requests(env):
    """Shrink the staffed bed target to 2, occupy both beds, and open two surge
    requests over windows that do not touch each other."""
    fixtures.patch_unit(env, headers=env["dir_a"], staffed_bed_target=2)
    fixtures.admit_case(env, case_reference="CASE-G1", **INBOUND_LEVEL_I_CASE)
    fixtures.admit_case(env, case_reference="CASE-G2", **INBOUND_LEVEL_I_CASE)
    first = fixtures.request_surge(
        env,
        requested_beds=6,
        effective_from="2026-08-02T00:00:00Z",
        effective_to="2026-08-03T00:00:00Z",
    )
    second = fixtures.request_surge(
        env,
        requested_beds=6,
        effective_from="2026-08-05T00:00:00Z",
        effective_to="2026-08-06T00:00:00Z",
    )
    return first, second


def _level_four_candidate():
    """A transport-capable regional centre holding three of the four LEVEL_IV
    credential codes and all three of its equipment codes, with the LEVEL_IV
    standard declared alongside the other three."""
    return fixtures.setup_network(
        standard_levels=("LEVEL_I", "LEVEL_II", "LEVEL_III", "LEVEL_IV"),
        credentials=(
            ("NEO_BOARD", "neo-1", 1.0),
            ("RN_NICU_CORE", "rn-pool", 3.0),
            ("NNP", "nnp-1", 1.0),
        ),
        equipment=(
            ("CONVENTIONAL_VENT", "VENT-1"),
            ("HFOV", "HFOV-1"),
            ("INHALED_NO", "INO-1"),
        ),
    )


# ---------------------------------------------------------------------------
# Referral: current support versus anticipated need
# ---------------------------------------------------------------------------


def test_antenatal_referral_keeps_its_estimated_weight_out_of_the_current_variant(api, network):
    """PRD §3.3: "`current_support_level` — the level demanded by findings that already exist — is the higher-ranking of the support term and the weight term, except that for a `MATERNAL_ANTENATAL` referral the weight contribution is forced to `LEVEL_I`, because an unborn infant has no current weight-driven support need and its estimated fetal weight belongs to the anticipated variant only."
    PRD §3.3: "`maternal_transfer_preferred` is true exactly when `referral_kind` is `MATERNAL_ANTENATAL` and `required_level` ranks at `LEVEL_III` or above."
    PRD §3.3: "An antenatal `LEVEL_III` case at 30.0 weeks and 1300 grams scores 78.75; an inbound `LEVEL_III` case at 29.0 weeks and 1200 grams scores 71.25, as does an inbound `LEVEL_III` case at 30.0 weeks and 1250 grams — ties are real and are broken by the rules in §3.4."

    Design: Difficulty/dual_variant_calc/referral_current_support_vs_anticipated_need_level
    """
    response = api.create_referral(
        factories.referral_payload(
            network["unit_b_id"],
            network["unit_a_id"],
            case_reference="CASE-M1",
            **MATERNAL_CASE,
        ),
        network["ref_b"],
    )
    referral = validate_success(response, 201)
    assertions.assert_referral(referral)

    assert referral["current_support_level"] == "LEVEL_I"
    assert referral["anticipated_need_level"] == "LEVEL_III"
    assert referral["level_basis"] == "ANTICIPATED_NEED"
    assert referral["required_level"] == "LEVEL_III"
    assert referral["maternal_transfer_preferred"] is True
    assertions.assert_close(referral["triage_priority"], 78.75)


def test_inbound_referral_agrees_across_both_variants_at_the_same_required_level(api, network):
    """PRD §3.3: "`level_basis` records which variant drove the answer: it is `ANTICIPATED_NEED` when `anticipated_need_level` outranks `current_support_level`, and `CURRENT_SUPPORT` otherwise — including when the two are equal."
    PRD §3.3: "`required_level` is always `anticipated_need_level`."
    PRD §3.3: "An antenatal `LEVEL_III` case at 30.0 weeks and 1300 grams scores 78.75; an inbound `LEVEL_III` case at 29.0 weeks and 1200 grams scores 71.25, as does an inbound `LEVEL_III` case at 30.0 weeks and 1250 grams — ties are real and are broken by the rules in §3.4."

    Design: Difficulty/dual_variant_calc/referral_current_support_vs_anticipated_need_level
    """
    antenatal = fixtures.create_referral(network, case_reference="CASE-M1", **MATERNAL_CASE)

    response = api.create_referral(
        factories.referral_payload(
            network["unit_b_id"],
            network["unit_a_id"],
            case_reference="CASE-N1",
            **INBOUND_LEVEL_III_CASE,
        ),
        network["ref_b"],
    )
    inbound = validate_success(response, 201)
    assertions.assert_referral(inbound)

    assert inbound["current_support_level"] == "LEVEL_III"
    assert inbound["anticipated_need_level"] == "LEVEL_III"
    assert inbound["level_basis"] == "CURRENT_SUPPORT"
    assert inbound["required_level"] == "LEVEL_III"
    assertions.assert_close(inbound["triage_priority"], 71.25)

    # The birth weight is counted by the anticipated variant of both cases but by
    # the current variant of the postnatal case only.
    assert antenatal["current_support_level"] != inbound["current_support_level"]
    assert antenatal["required_level"] == inbound["required_level"] == "LEVEL_III"


# ---------------------------------------------------------------------------
# Surveillance: crude versus device-adjusted infection rate
# ---------------------------------------------------------------------------


def test_surveillance_report_computes_both_infection_rate_variants(api, network):
    """PRD §3.9: "One infection over 500 patient-days and 120 central-line-days, with a cohort of two infants weighing 900 and 2000 grams, yields a risk weight of 1.1500, a crude rate of 2.00, a device-adjusted rate of 9.58, a variant of `DEVICE_ADJUSTED`, a completeness of `COMPLETE` and a flag of `ABOVE_BENCHMARK`."

    Design: Difficulty/dual_variant_calc/clabsi_crude_versus_device_adjusted_rate
    """
    _clabsi_cohort(network)
    report = _report_for_the_august_period(api, network)
    assertions.assert_surveillance_report(report)

    assert report["cohort_size"] == 2
    assert report["clabsi_count"] == 1
    assertions.assert_close(report["birth_weight_risk_weight"], 1.1500)
    assertions.assert_close(report["crude_clabsi_rate"], 2.00)
    assertions.assert_close(report["device_adjusted_clabsi_rate"], 9.58)


def test_network_benchmark_flag_is_decided_by_the_device_adjusted_variant(api, network):
    """PRD §3.9: "`variant_applied` records which of the two the network will judge: `DEVICE_ADJUSTED` when `reported_central_line_days` is above zero, and `CRUDE` otherwise."
    PRD §3.9: "`data_completeness_flag` is `COMPLETE` when both `reported_patient_days` and `reported_central_line_days` are above zero, and `DENOMINATOR_MISSING` otherwise."
    PRD §3.9: "`network_benchmark_flag` is `ABOVE_BENCHMARK` when the rate of the applied variant is strictly greater than the network benchmark of 1.50 infections per 1000 days, and `WITHIN_BENCHMARK` otherwise."

    Design: Difficulty/dual_variant_calc/clabsi_crude_versus_device_adjusted_rate
    """
    _clabsi_cohort(network)
    report = _report_for_the_august_period(api, network)
    assertions.assert_surveillance_report(report)

    assert report["variant_applied"] == "DEVICE_ADJUSTED"
    assert report["data_completeness_flag"] == "COMPLETE"
    assert report["network_benchmark_flag"] == "ABOVE_BENCHMARK"

    # The same source data yields two different rates, and the applied one is the
    # higher of the pair here.
    assertions.assert_close(
        float(report["device_adjusted_clabsi_rate"]) - float(report["crude_clabsi_rate"]), 7.58
    )


# ---------------------------------------------------------------------------
# Capacity: committed versus forecast beds
# ---------------------------------------------------------------------------


def test_capacity_projection_publishes_committed_and_forecast_bed_variants(api, network):
    """PRD §2.8: "The committed variant, `committed_available`, is simply `available_bed_count`."
    PRD §2.8: "The forecast variant, `forecast_available`, is `committed_available` plus `back_transfer_ready_count` — the number of the unit's admissions whose `care_status` is `BACK_TRANSFER_READY` — plus `expiring_hold_count` — the number of `HELD` reservations whose `expires_at` is at or before the current clock instant advanced by 60 minutes."
    PRD §2.8: "When `available_bed_count` is at or below zero, the posture is `CLOSED`."

    Design: Difficulty/dual_variant_calc/capacity_committed_versus_forecast_beds
    """
    _committed_and_forecast_picture(network)

    projection = validate_success(
        api.get_capacity_projection(network["unit_a_id"], network["dir_a"])
    )

    assert projection["committed_available"] == 0
    assert projection["forecast_available"] == 2
    assert projection["back_transfer_ready_count"] == 1
    assert projection["expiring_hold_count"] == 1
    assert projection["census_posture"] == "CLOSED"


def test_only_the_hold_inside_the_sixty_minute_window_counts_as_expiring(api, network):
    """PRD §3.4: "A permitted acceptance moves the referral `PENDING → ACCEPTED` and creates a bed reservation for it, carrying the receiving unit as `unit_id` and the referral as `referral_id`, starting at status `HELD`, taking its `bed_class` from the waterfall rule of §2.8, stamping `held_at` with the current clock instant, and computing `expires_at` from the referral's kind: an antenatal hold lasts 720 minutes — twelve hours — from `held_at`, because a mother in labour needs a bed that will still be there tomorrow morning, while every other kind of hold lasts 240 minutes, four hours."
    PRD §2.8: "The forecast variant, `forecast_available`, is `committed_available` plus `back_transfer_ready_count` — the number of the unit's admissions whose `care_status` is `BACK_TRANSFER_READY` — plus `expiring_hold_count` — the number of `HELD` reservations whose `expires_at` is at or before the current clock instant advanced by 60 minutes."

    Design: Difficulty/dual_variant_calc/capacity_committed_versus_forecast_beds
    """
    maternal, inbound = _committed_and_forecast_picture(network)

    antenatal_hold = fixtures.read_reservation(network, maternal["reservation_id"])
    inbound_hold = fixtures.read_reservation(network, inbound["reservation_id"])
    assert antenatal_hold["status"] == "HELD"
    assert inbound_hold["status"] == "HELD"
    assert antenatal_hold["expires_at"].startswith("2026-08-02T12:00:00")
    assert inbound_hold["expires_at"].startswith("2026-08-02T04:00:00")

    unit = validate_success(api.get_nicu_unit(network["unit_a_id"], network["dir_a"]))
    assertions.assert_unit_counts(unit, occupied=2, held=2, available=0, posture="CLOSED")

    projection = validate_success(
        api.get_capacity_projection(network["unit_a_id"], network["dir_a"])
    )
    assert projection["expiring_hold_count"] == 1
    assert projection["forecast_available"] == (
        projection["committed_available"]
        + projection["back_transfer_ready_count"]
        + projection["expiring_hold_count"]
    )


# ---------------------------------------------------------------------------
# Nursing requirement: rounding up per acuity band before summing
# ---------------------------------------------------------------------------


def test_each_admitted_infant_lands_in_its_own_acuity_band(api, network):
    """PRD §3.7: "`current_care_level` is re-derived from the bedside record as the higher-ranking of the weight term applied to `current_weight_grams` and the support term applied to `support_modality`, using exactly the weight and support mappings of §3.3."

    Design: Difficulty/combinatorial_formula/required_nurse_count_per_band_ceiling_order
    """
    level_three, level_two, level_one = _one_infant_in_each_acuity_band(network)

    heaviest_support = validate_success(api.get_admission(level_three["id"], network["dir_a"]))
    middle = validate_success(api.get_admission(level_two["id"], network["dir_a"]))
    lightest_support = validate_success(api.get_admission(level_one["id"], network["dir_a"]))

    assertions.assert_admission(heaviest_support)
    assertions.assert_admission(middle)
    assertions.assert_admission(lightest_support)

    assert heaviest_support["current_care_level"] == "LEVEL_III"
    assert middle["current_care_level"] == "LEVEL_II"
    assert lightest_support["current_care_level"] == "LEVEL_I"


def test_required_nurse_count_rounds_up_each_band_before_summing_the_bands(api, network):
    """PRD §2.8: "For each level, divide that level's census band by the product of the `nurse_patient_ratio_denominator` declared by the standard for that level and the waiver in force, then round the quotient **up** to a whole nurse; `required_nurse_count` is the sum of those per-band whole numbers."
    PRD §2.8: "The order is pinned: the rounding up happens per acuity band and only then are the bands summed."

    Design: Difficulty/combinatorial_formula/required_nurse_count_per_band_ceiling_order
    """
    _one_infant_in_each_acuity_band(network)

    unit = validate_success(api.get_nicu_unit(network["unit_a_id"], network["dir_a"]))
    assertions.assert_nicu_unit(unit)

    # One nurse per occupied band: 1/2.0, 1/3.0 and 1/4.0 each round up to 1.
    assert unit["required_nurse_count"] == 3
    # Summing the three fractions first and rounding once would give 2.
    assert unit["required_nurse_count"] != 2

    assertions.assert_unit_counts(unit, occupied=3, held=0, available=1, posture="OPEN")


# ---------------------------------------------------------------------------
# Surge authorization: the ratio excludes the escalation's own beds
# ---------------------------------------------------------------------------


def test_surge_authorization_at_a_full_census_reaches_the_top_tier(api, network):
    """PRD §3.5: "First, `census_ratio_at_request` — the unit's `occupied_bed_count` divided by the sum of its `staffed_bed_target` and the `authorized_beds` of every *other* `ACTIVE` escalation at that unit, rounded half up to four decimals."
    PRD §3.5: "The tier fixes `staffing_waiver_ratio` — 1.10 at `TIER_1`, 1.25 at `TIER_2`, 1.50 at `TIER_3` — which is the multiplier applied to the acuity-band denominators in the nurse calculation of §2.8, and it also fixes a bed cap of 2 beds at `TIER_1`, 4 beds at `TIER_2` and 6 beds at `TIER_3`."
    PRD §3.5: "`authorized_beds` is then the lowest of three quantities: the `requested_beds` asked for, that staffing headroom, and the tier's bed cap — floored at zero so it is never negative."

    Design: Difficulty/combinatorial_formula/surge_authorization_excludes_its_own_beds_from_the_ratio
    """
    first, _second = _full_census_with_two_surge_requests(network)

    escalation = validate_success(
        api.authorize_surge_escalation(first["id"], {}, network["admin"])
    )
    assertions.assert_surge_escalation(escalation)

    assertions.assert_close(escalation["census_ratio_at_request"], 1.0000)
    assert escalation["escalation_tier"] == "TIER_3"
    assertions.assert_close(escalation["staffing_waiver_ratio"], 1.50)
    assert escalation["authorized_beds"] == 6
    assert escalation["status"] == "ACTIVE"

    unit = validate_success(api.get_nicu_unit(network["unit_a_id"], network["dir_a"]))
    assertions.assert_unit_counts(unit, occupied=2, held=0, available=6, escalation=6)


def test_second_surge_authorization_is_refused_once_the_active_beds_enter_the_denominator(
    api, network
):
    """PRD §3.5: "First, `census_ratio_at_request` — the unit's `occupied_bed_count` divided by the sum of its `staffed_bed_target` and the `authorized_beds` of every *other* `ACTIVE` escalation at that unit, rounded half up to four decimals."
    PRD §3.5: "Second, the tier: a ratio at or above 1.00 is `TIER_3`, a ratio at or above 0.90 is `TIER_2`, a ratio at or above 0.80 is `TIER_1`, and a ratio strictly below 0.80 refuses the authorization with `ERR_SURGE_THRESHOLD_NOT_MET`."
    PRD §3.5: "The request opens at status `REQUESTED` and grants nothing until the network authorizes it."

    Design: Difficulty/combinatorial_formula/surge_authorization_excludes_its_own_beds_from_the_ratio
    """
    first, second = _full_census_with_two_surge_requests(network)
    fixtures.authorize_surge(network, first["id"])

    # Two occupied beds over a target of 2 plus the 6 beds the first escalation
    # already holds is 0.2500, well below the 0.80 authorization threshold.
    response = api.authorize_surge_escalation(second["id"], {}, network["admin"])
    validate_error(response, ApiErrorId.SURGE_THRESHOLD_NOT_MET)

    unchanged = validate_success(api.get_surge_escalation(second["id"], network["admin"]))
    assertions.assert_surge_escalation(unchanged)
    assert unchanged["status"] == "REQUESTED"
    assert unchanged["authorized_beds"] is None
    assert unchanged["escalation_tier"] is None
    assert unchanged["staffing_waiver_ratio"] is None


# ---------------------------------------------------------------------------
# Designation score: four factors and the transport capability cap
# ---------------------------------------------------------------------------


def test_designation_submission_freezes_the_three_weighted_subscores(api):
    """PRD §3.2: "`staffing_subscore` is 100 multiplied by the credential coverage and again by the ratio factor, rounded half up to two decimals."
    PRD §3.2: "`equipment_subscore` is 100 multiplied by the count of the standard's `required_equipment_codes` held with derived `status` `IN_SERVICE` and divided by the number of codes listed, rounded half up to two decimals, and is 100.00 when the list is empty."
    PRD §3.2: "For volume, the effective minimum is the standard's `min_annual_volume` for a unit whose `hospital_type` is `REGIONAL_CENTER`, and half of that figure for a `COMMUNITY` unit; `volume_subscore` is 100 multiplied by the lower of 1.0 and the unit's `annual_admission_volume` divided by that effective minimum, rounded half up to two decimals."

    Design: Difficulty/combinatorial_formula/designation_score_multi_factor_with_transport_cap
    """
    env = _level_four_candidate()
    review = fixtures.open_review(env, requested_level="LEVEL_IV", assigned_nurse_count=0)

    submitted = validate_success(
        api.submit_designation_review(review["id"], {}, env["dir_a"])
    )
    assertions.assert_designation_review(submitted)

    # Three of the four required credential codes are held, all three required
    # assets are in service, and 400 admissions sit against a minimum of 500.
    assertions.assert_close(submitted["staffing_subscore"], 75.00)
    assertions.assert_close(submitted["equipment_subscore"], 100.00)
    assertions.assert_close(submitted["volume_subscore"], 80.00)
    assert submitted["submission_round"] == 1


def test_transport_capability_cap_moves_only_the_weighted_total(api):
    """PRD §3.2: "`compliance_score` is then 0.45 of the staffing subscore plus 0.35 of the equipment subscore plus 0.20 of the volume subscore, rounded half up to two decimals."
    PRD §3.2: "Finally, and only after that total has been computed, one cap applies: when the standard sets `transport_capability_required` to true and the unit's `transport_capable` is false, `compliance_score` becomes the lower of its computed value and 69.99."
    PRD §3.2: "Verification moves it `SUBMITTED → VERIFIED` and records the caller as `verified_by_user_id`; it requires that `compliance_score` be at or above the `conditional_floor_score` of the standard for `requested_level`, and again that the caller differ from `submitted_by_user_id`."

    Design: Difficulty/combinatorial_formula/designation_score_multi_factor_with_transport_cap
    """
    env = _level_four_candidate()
    review = fixtures.open_review(env, requested_level="LEVEL_IV", assigned_nurse_count=0)

    first_round = fixtures.submit_review(env, review["id"], headers=env["dir_a"])
    assertions.assert_close(first_round["compliance_score"], 84.75)
    assert first_round["submission_round"] == 1

    fixtures.return_review(
        env,
        review["id"],
        return_reason="RT_NEO coverage missing - resubmit with the transport attestation corrected",
    )
    fixtures.patch_unit(env, headers=env["dir_a"], transport_capable=False)

    second_round = validate_success(
        api.submit_designation_review(review["id"], {}, env["dir_a"])
    )
    assertions.assert_designation_review(second_round)

    # The four factors are untouched by the transport flag.
    assertions.assert_close(second_round["staffing_subscore"], 75.00)
    assertions.assert_close(second_round["equipment_subscore"], 100.00)
    assertions.assert_close(second_round["volume_subscore"], 80.00)

    assertions.assert_close(second_round["compliance_score"], 69.99)
    assert second_round["submission_round"] == 2
    assert second_round["status"] == "SUBMITTED"

    conditional_floor = env["standards"]["LEVEL_IV"]["conditional_floor_score"]
    assertions.assert_close(conditional_floor, 75.00)
    assert float(second_round["compliance_score"]) < float(conditional_floor)
