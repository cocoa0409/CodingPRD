"""Rejection precedence and inclusive-bound behaviour.

Covers the fixed check order of PRD §2.10 where two refusals compete on one
call — own state against the transport stabilization gate, and milk expiry
against the milk volume ledger — and the worked boundary examples of PRD §3.6
(the stabilization score and departure), §3.7 (the developmental bundle),
§3.8 (back-transfer readiness) and §3.9 (the surveillance rate variants).
"""

from typing import Any, Dict

from test_helpers import (
    ApiErrorId,
    assert_close,
    assert_decimal_places,
    factories,
    fixtures,
    make_bedside_nurse_headers,
    validate_error,
    validate_success,
)


def _ground_run_on_scene(env: Dict[str, Any], case_reference: str) -> Dict[str, Any]:
    """Refer a 30.0-week, 1250 g HFOV case, hold a bed for it, then activate,
    dispatch and bring a GROUND run to ON_SCENE with no vitals recorded."""
    _, accepted = fixtures.hold_bed(
        env,
        case_reference=case_reference,
        gestational_age_weeks=30.0,
        birth_weight_grams=1250,
        support_modality="HFOV",
    )
    run = fixtures.create_run(
        env,
        accepted["reservation_id"],
        mode="GROUND",
        crew_composition=["TRANSPORT_RN", "NNP"],
        depart_at="2026-08-02T08:00:00Z",
        planned_return_at="2026-08-02T12:00:00Z",
        weather_minimums_met=False,
    )
    fixtures.dispatch_run(env, run["id"])
    return fixtures.run_on_scene(env, run["id"])


def _stabilized_admission(env: Dict[str, Any], case_reference: str) -> Dict[str, Any]:
    """Admit a 1200 g case and post one day of care in room air at 1900 g, which
    carries the admission from ADMITTED to STABILIZED."""
    admission = fixtures.admit_case(env, case_reference=case_reference)
    return fixtures.care_update(
        env,
        admission["id"],
        current_weight_grams=1900,
        support_modality="ROOM_AIR",
        central_line_present=False,
        ventilated=False,
    )


# ---------------------------------------------------------------------------
# Own state against the transport safety gate
# ---------------------------------------------------------------------------


def test_depart_from_on_scene_answers_invalid_state_not_the_bundle_gate(api):
    """PRD §2.10: "When a request violates more than one rule, exactly one error is returned, and which one is not a matter of implementation convenience."

    PRD §2.10: "Own state: the entity's own status must permit the trigger, including terminal-state lockdown and rejection of a repeated trigger, else `ERR_INVALID_STATE` (409)."

    PRD §3.6: "Departure moves the run `STABILIZING → EN_ROUTE` and carries no body fields."

    Design: Difficulty/priority_pair_validation_conflict/own_state_precedes_stabilization_safety_gate
    """
    env = fixtures.setup_network(with_isolette=True)
    run = _ground_run_on_scene(env, "CASE-V1")

    refused = api.depart_transport_run(run["id"], {}, env["coord"])
    validate_error(refused, ApiErrorId.INVALID_STATE)

    unchanged = validate_success(api.get_transport_run(run["id"], env["coord"]))
    assert unchanged["status"] == "ON_SCENE"
    assert unchanged["stabilization_bundle_complete"] is False


def test_depart_with_an_incomplete_bundle_answers_stabilization_incomplete(api):
    """PRD §3.6: "It requires `stabilization_bundle_complete` to be true — otherwise `ERR_STABILIZATION_INCOMPLETE` — and it requires the referral behind the reservation still to be in `ACCEPTED`, otherwise `ERR_DEPENDENT_STATE_INVALID`; a crew must not set off toward a bed that has since been given away."

    PRD §3.6: "At 30.0 weeks gestation, values of 36.5, 45, 30 and 90 — every one of them exactly on its boundary — score 100 and the bundle is complete; 36.4, 44, 26 and 89 score 68 and it is not; 36.8, 60, 28 and 92 score 92 and the bundle is complete with only the mean pressure failing; and 37.6, 60, 31 and 96 score 84 and the bundle is incomplete, because temperature and saturation both overshoot."

    Design: Difficulty/priority_pair_validation_conflict/own_state_precedes_stabilization_safety_gate
    """
    env = fixtures.setup_network(with_isolette=True)
    run = _ground_run_on_scene(env, "CASE-V1")

    stabilized = validate_success(
        api.stabilize_transport_run(
            run["id"],
            factories.stabilize_payload(
                temp_c=36.4, glucose_mg_dl=44, mean_bp_mmhg=26, spo2_pct=89
            ),
            env["coord"],
        )
    )
    assert stabilized["status"] == "STABILIZING"
    assert_close(stabilized["stabilization_score"], 68)
    assert stabilized["stabilization_bundle_complete"] is False

    refused = api.depart_transport_run(run["id"], {}, env["coord"])
    validate_error(refused, ApiErrorId.STABILIZATION_INCOMPLETE)

    unchanged = validate_success(api.get_transport_run(run["id"], env["coord"]))
    assert unchanged["status"] == "STABILIZING"


# ---------------------------------------------------------------------------
# Milk expiry against the milk volume ledger
# ---------------------------------------------------------------------------


def test_over_volume_administration_answers_volume_exceeded_while_batch_is_live(api):
    """PRD §3.7: "The posted volume must not exceed `remaining_ml`, and a reversal's posted volume must not exceed `administered_ml`; either overrun is refused with `ERR_MILK_VOLUME_EXCEEDED`."

    PRD §3.7: "`administered_ml` is the sum of volumes administered less the sum of volumes reversed; `discarded_ml` is the sum of volumes discarded; and `remaining_ml` is `volume_ml` less `administered_ml` less `discarded_ml`, at one decimal place."

    Design: Difficulty/priority_pair_validation_conflict/milk_expiry_safety_precedes_volume_capacity
    """
    env = fixtures.setup_network()
    admission = fixtures.admit_case(env, case_reference="CASE-M2")
    batch = fixtures.verified_milk_batch(
        env,
        admission["id"],
        donor_type="MOTHERS_OWN",
        volume_ml=120.0,
        expressed_at="2026-08-01T00:00:00Z",
    )

    fixtures.set_clock("2026-08-02T00:00:00Z", env["admin"])

    refused = api.administer_milk(
        batch["id"], factories.milk_volume_payload(200.0), make_bedside_nurse_headers("nurse-3")
    )
    validate_error(refused, ApiErrorId.MILK_VOLUME_EXCEEDED)

    untouched = validate_success(api.get_milk_batch(batch["id"], env["nurse"]))
    assert untouched["status"] == "VERIFIED"
    assert_close(untouched["administered_ml"], 0.0)
    assert_close(untouched["remaining_ml"], 120.0)
    assert_decimal_places(untouched["remaining_ml"], 1)

    admission_after = fixtures.read_admission(env, admission["id"])
    assert_close(admission_after["milk_administered_ml"], 0.0)


def test_expiry_at_the_expires_at_instant_replaces_the_volume_refusal(api):
    """PRD §3.7: "The batch must not have expired: an `expires_at` at or before the current clock instant is refused with `ERR_MILK_EXPIRED`, and at exactly `expires_at` the batch is already expired."

    PRD §3.7: "The caller's `X-User-ID` is stored as `received_by_user_id`, the batch opens at status `RECEIVED` with `verified_by_user_id` null, and `expires_at` is derived from the donor type: 96 hours — four days — after `expressed_at` for `MOTHERS_OWN`, and 24 hours after `expressed_at` for `DONOR_PASTEURIZED`."

    PRD §2.10: "Checks are evaluated in the following fixed order, and the first failure is returned immediately."

    Design: Difficulty/priority_pair_validation_conflict/milk_expiry_safety_precedes_volume_capacity
    """
    env = fixtures.setup_network()
    admission = fixtures.admit_case(env, case_reference="CASE-M2")
    batch = fixtures.verified_milk_batch(
        env,
        admission["id"],
        donor_type="MOTHERS_OWN",
        volume_ml=120.0,
        expressed_at="2026-08-01T00:00:00Z",
    )
    assert batch["expires_at"].startswith("2026-08-05T00:00:00")

    fixtures.set_clock("2026-08-05T00:00:00Z", env["admin"])

    refused = api.administer_milk(
        batch["id"], factories.milk_volume_payload(200.0), make_bedside_nurse_headers("nurse-3")
    )
    validate_error(refused, ApiErrorId.MILK_EXPIRED)

    untouched = validate_success(api.get_milk_batch(batch["id"], env["nurse"]))
    assert untouched["status"] == "VERIFIED"
    assert_close(untouched["administered_ml"], 0.0)
    assert_close(untouched["remaining_ml"], 120.0)

    admission_after = fixtures.read_admission(env, admission["id"])
    assert_close(admission_after["milk_administered_ml"], 0.0)


# ---------------------------------------------------------------------------
# The stabilization bundle exactly on its inclusive bounds
# ---------------------------------------------------------------------------


def test_stabilization_targets_on_their_inclusive_bounds_score_one_hundred(api):
    """PRD §3.6: "**The stabilization score** begins at 100 and loses 8 points for each of four targets the infant misses."

    PRD §3.6: "At 30.0 weeks gestation, values of 36.5, 45, 30 and 90 — every one of them exactly on its boundary — score 100 and the bundle is complete; 36.4, 44, 26 and 89 score 68 and it is not; 36.8, 60, 28 and 92 score 92 and the bundle is complete with only the mean pressure failing; and 37.6, 60, 31 and 96 score 84 and the bundle is incomplete, because temperature and saturation both overshoot."

    PRD §3.6: "`stabilization_bundle_complete` is true when `stabilization_score` reaches at least 85, which means at most one failed target may be carried into transport."

    Design: Difficulty/boundary_precision_check/stabilization_targets_met_exactly_at_every_bound
    """
    env = fixtures.setup_network(with_isolette=True)
    run = _ground_run_on_scene(env, "CASE-B1")

    stabilized = validate_success(
        api.stabilize_transport_run(
            run["id"],
            factories.stabilize_payload(
                temp_c=36.5, glucose_mg_dl=45, mean_bp_mmhg=30, spo2_pct=90
            ),
            env["coord"],
        )
    )
    assert_close(stabilized["stabilization_score"], 100)
    assert stabilized["stabilization_bundle_complete"] is True
    assert stabilized["status"] == "STABILIZING"
    assert_close(stabilized["mean_bp_mmhg"], 30)


def test_departure_is_permitted_once_the_boundary_bundle_is_complete(api):
    """PRD §3.6: "Departure moves the run `STABILIZING → EN_ROUTE` and carries no body fields."

    PRD §3.6: "It requires `stabilization_bundle_complete` to be true — otherwise `ERR_STABILIZATION_INCOMPLETE` — and it requires the referral behind the reservation still to be in `ACCEPTED`, otherwise `ERR_DEPENDENT_STATE_INVALID`; a crew must not set off toward a bed that has since been given away."

    Design: Difficulty/boundary_precision_check/stabilization_targets_met_exactly_at_every_bound
    """
    env = fixtures.setup_network(with_isolette=True)
    run = _ground_run_on_scene(env, "CASE-B1")

    fixtures.stabilize_run(
        env, run["id"], temp_c=36.5, glucose_mg_dl=45, mean_bp_mmhg=30, spo2_pct=90
    )

    departed = validate_success(api.depart_transport_run(run["id"], {}, env["coord"]))
    assert departed["status"] == "EN_ROUTE"
    assert departed["stabilization_bundle_complete"] is True
    assert_close(departed["stabilization_score"], 100)


# ---------------------------------------------------------------------------
# Surveillance denominators at zero and an empty cohort
# ---------------------------------------------------------------------------


def _confirmed_clabsi_unit(env: Dict[str, Any]) -> Dict[str, Any]:
    """Admit a 900 g infant, record one central-line day, then carry the
    infection dimension through SUSPECT to CONFIRMED_CLABSI."""
    admission = fixtures.admit_case(env, case_reference="CASE-Z1", birth_weight_grams=900)
    fixtures.care_update(
        env,
        admission["id"],
        current_weight_grams=950,
        support_modality="CPAP",
        central_line_present=True,
        ventilated=False,
    )
    fixtures.infection_event(env, admission["id"], "SUSPECT")
    return fixtures.infection_event(env, admission["id"], "CONFIRM_CLABSI")


def test_zero_central_line_days_falls_back_to_the_crude_variant(api):
    """PRD §3.9: "`device_adjusted_clabsi_rate` is `clabsi_count` multiplied by `birth_weight_risk_weight`, multiplied by 1000, divided by `reported_central_line_days`, rounded half up to two decimals, and is likewise 0.00 when that denominator is zero."

    PRD §3.9: "`variant_applied` records which of the two the network will judge: `DEVICE_ADJUSTED` when `reported_central_line_days` is above zero, and `CRUDE` otherwise."

    PRD §3.9: "The same data with zero central-line-days yields a device-adjusted rate of 0.00, a variant of `CRUDE`, a completeness of `DENOMINATOR_MISSING`, and still `ABOVE_BENCHMARK`, because the crude 2.00 exceeds 1.50."

    Design: Difficulty/boundary_precision_check/surveillance_denominators_at_zero_and_empty_cohort
    """
    env = fixtures.setup_network()
    _confirmed_clabsi_unit(env)

    report = validate_success(
        api.create_surveillance_report(
            factories.surveillance_report_payload(
                env["unit_a_id"],
                period_start="2026-08-01T00:00:00Z",
                period_end="2026-08-31T23:59:59Z",
                reported_patient_days=500,
                reported_central_line_days=0,
            ),
            env["dir_a"],
        ),
        201,
    )

    assert report["cohort_size"] == 1
    assert_close(report["birth_weight_risk_weight"], 1.3000)
    assert_decimal_places(report["birth_weight_risk_weight"], 4)
    assert report["clabsi_count"] == 1
    assert_close(report["crude_clabsi_rate"], 2.00)
    assert_close(report["device_adjusted_clabsi_rate"], 0.00)
    assert_decimal_places(report["crude_clabsi_rate"], 2)
    assert_decimal_places(report["device_adjusted_clabsi_rate"], 2)
    assert report["variant_applied"] == "CRUDE"
    assert report["data_completeness_flag"] == "DENOMINATOR_MISSING"
    assert report["network_benchmark_flag"] == "ABOVE_BENCHMARK"


def test_an_empty_cohort_reports_the_neutral_risk_weight(api):
    """PRD §3.9: "`birth_weight_risk_weight` is the mean, over the cohort, of a band weight applied to each admission's `birth_weight_grams`: 1.30 below 1000 grams, 1.15 from 1000 up to but not including 1500, 1.00 from 1500 up to but not including 2500, and 0.85 at 2500 grams or above — rounded half up to four decimals, and reported as 1.0000 for an empty cohort."

    PRD §3.9: "`clabsi_count` is deliberately not cohort-scoped: it is the count of the unit's admissions whose `infection_confirmed_at` falls inside the period, inclusive at both ends, whenever they were admitted."

    PRD §3.9: "`network_benchmark_flag` is `ABOVE_BENCHMARK` when the rate of the applied variant is strictly greater than the network benchmark of 1.50 infections per 1000 days, and `WITHIN_BENCHMARK` otherwise."

    Design: Difficulty/boundary_precision_check/surveillance_denominators_at_zero_and_empty_cohort
    """
    env = fixtures.setup_network()
    _confirmed_clabsi_unit(env)

    report = validate_success(
        api.create_surveillance_report(
            factories.surveillance_report_payload(
                env["unit_a_id"],
                period_start="2026-09-01T00:00:00Z",
                period_end="2026-09-30T23:59:59Z",
                reported_patient_days=0,
                reported_central_line_days=0,
            ),
            env["dir_a"],
        ),
        201,
    )

    assert report["cohort_size"] == 0
    assert_close(report["birth_weight_risk_weight"], 1.0000)
    assert_decimal_places(report["birth_weight_risk_weight"], 4)
    assert report["clabsi_count"] == 0
    assert_close(report["crude_clabsi_rate"], 0.00)
    assert_close(report["device_adjusted_clabsi_rate"], 0.00)
    assert report["variant_applied"] == "CRUDE"
    assert report["data_completeness_flag"] == "DENOMINATOR_MISSING"
    assert report["network_benchmark_flag"] == "WITHIN_BENCHMARK"


# ---------------------------------------------------------------------------
# The developmental bundle exactly at sixty
# ---------------------------------------------------------------------------


def test_two_rounds_reach_exactly_sixty_and_open_back_transfer_readiness(api):
    """PRD §3.7: "Two rounds each of 60 kangaroo minutes, 240 family minutes, cluster compliance true and light cycling false produce exactly 60.00 — the boundary at which back-transfer readiness passes."

    PRD §3.7: "Posting a round increments `developmental_round_count` by one; it increments `kangaroo_care_sessions` by one only when the round's `kangaroo_care_minutes` is at least 60 — a session that short of an hour does not count as skin-to-skin care; it adds the round's `family_presence_minutes` to the admission's running total of the same name; it increments `cluster_care_compliant_count` by one when `cluster_care_compliant` was true; and it increments `light_cycling_compliant_count` by one when `light_cycling_compliant` was true."

    PRD §3.8: "The receiving unit's `IntakeNeonatologist` attests that readiness, moving the admission `STABILIZED → BACK_TRANSFER_READY`."

    Design: Difficulty/boundary_precision_check/developmental_bundle_at_exactly_sixty
    """
    env = fixtures.setup_network()
    admission = _stabilized_admission(env, "CASE-D1")

    rounded = fixtures.developmental_rounds(
        env,
        admission["id"],
        count=2,
        kangaroo_care_minutes=60,
        family_presence_minutes=240,
        cluster_care_compliant=True,
        light_cycling_compliant=False,
    )
    assert rounded["developmental_round_count"] == 2
    assert rounded["kangaroo_care_sessions"] == 2
    assert rounded["family_presence_minutes"] == 480
    assert_close(rounded["developmental_bundle_score"], 60.00)
    assert_decimal_places(rounded["developmental_bundle_score"], 2)

    attested = validate_success(
        api.attest_back_transfer_ready(
            admission["id"],
            factories.back_transfer_ready_payload("Bundle met at threshold"),
            env["intake_a"],
        )
    )
    assert attested["care_status"] == "BACK_TRANSFER_READY"
    assert attested["back_transfer_attestation_note"] == "Bundle met at threshold"


def test_a_single_round_scores_forty_and_readiness_is_refused(api):
    """PRD §3.7: "A single such round produces 40.00 and readiness is refused."

    PRD §3.8: "Four conditions must all hold: `developmental_bundle_score` must be at least 60, and a lower score is refused with `ERR_DEVELOPMENTAL_BUNDLE_INCOMPLETE`; `support_modality` must be `ROOM_AIR` or `CPAP`; `infection_status` must not be `CONFIRMED_CLABSI`, because an active central-line infection is not something to hand to a community nursery; and a `back_transfer_attestation_note` must be present in the request, which is then recorded on the admission as the risk-appropriateness attestation."

    Design: Difficulty/boundary_precision_check/developmental_bundle_at_exactly_sixty
    """
    env = fixtures.setup_network()
    admission = _stabilized_admission(env, "CASE-D2")

    rounded = fixtures.developmental_round(
        env,
        admission["id"],
        kangaroo_care_minutes=60,
        family_presence_minutes=240,
        cluster_care_compliant=True,
        light_cycling_compliant=False,
    )
    assert rounded["developmental_round_count"] == 1
    assert rounded["kangaroo_care_sessions"] == 1
    assert rounded["family_presence_minutes"] == 240
    assert_close(rounded["developmental_bundle_score"], 40.00)
    assert_decimal_places(rounded["developmental_bundle_score"], 2)

    refused = api.attest_back_transfer_ready(
        admission["id"],
        factories.back_transfer_ready_payload("One round only"),
        env["intake_a"],
    )
    validate_error(refused, ApiErrorId.DEVELOPMENTAL_BUNDLE_INCOMPLETE)

    unchanged = fixtures.read_admission(env, admission["id"])
    assert unchanged["care_status"] == "STABILIZED"
