"""Ordering, scoring and re-ordering sleep studies."""

from test_helpers import (
    ApiErrorId,
    approx_index,
    assert_calendar_date,
    assert_is_null,
    assert_sleep_study,
    build_scenario,
    create_referral_payload,
    create_sleep_study_payload,
    order_and_result_study,
    sleep_study_results_payload,
    validate_error,
    validate_success,
)


def test_hsat_severity_index_divides_by_recording_time(api):
    """PRD §3.2: "For an `HSAT`, the denominator is `recording_minutes` divided by 60 — a home
    test cannot score sleep, so every monitored minute counts, and `sleep_minutes` is ignored
    even when it is supplied."
    PRD §3.2: "In both branches `severity_index` is `respiratory_events` divided by that
    denominator in hours, rounded half up to 1 decimal place, and a denominator of zero or less
    is refused with `ERR_VALIDATION`."

    Design: Difficulty/dual_variant_calc/hsat_recording_time_vs_psg_sleep_time_severity_index
    """
    scenario = build_scenario("cast")
    study = order_and_result_study(
        scenario,
        results={
            "performed_on": "2026-04-10",
            "respiratory_events": 120,
            "recording_minutes": 480,
            "sleep_minutes": 240,
            "artifact_pct": 0,
            "attended": True,
        },
        study_overrides={"modality": "HSAT", "study_purpose": "DIAGNOSTIC"},
    )
    data = validate_success(api.get_sleep_study(study["id"], scenario["phys_headers"]))
    assert_sleep_study(data)
    assert data["severity_index"] == approx_index(15.0), (
        "120 events over 480 recording minutes is 15.0 on the HSAT denominator"
    )
    assert data["severity_band"] == "MODERATE"
    assert data["status"] == "DIAGNOSTIC_VALID"


def test_psg_severity_index_divides_by_scored_sleep_time(api):
    """PRD §3.2: "For a `PSG`, the denominator is `sleep_minutes` divided by 60, because an
    attended study scores true sleep time."
    PRD §3.2: "Because scored sleep time is always the smaller number, the PSG arm produces the
    higher index from the same event count, and can land the same patient in a stricter severity
    band."

    Design: Difficulty/dual_variant_calc/hsat_recording_time_vs_psg_sleep_time_severity_index
    """
    scenario = build_scenario("cast")
    posted = {
        "performed_on": "2026-04-10",
        "respiratory_events": 120,
        "recording_minutes": 480,
        "sleep_minutes": 240,
        "artifact_pct": 0,
        "attended": True,
    }
    hsat = order_and_result_study(
        scenario, results=posted,
        study_overrides={"modality": "HSAT", "study_purpose": "DIAGNOSTIC"},
    )
    psg = order_and_result_study(
        scenario, results=posted,
        study_overrides={"modality": "PSG", "study_purpose": "DIAGNOSTIC"},
    )
    psg_data = validate_success(api.get_sleep_study(psg["id"], scenario["phys_headers"]))
    hsat_data = validate_success(api.get_sleep_study(hsat["id"], scenario["phys_headers"]))
    assert psg_data["severity_index"] == approx_index(30.0)
    assert psg_data["severity_band"] == "SEVERE"
    assert psg_data["status"] == "DIAGNOSTIC_VALID"
    assert psg_data["severity_index"] != hsat_data["severity_index"], (
        "identical postings must diverge because the denominator differs by modality"
    )


def test_severity_band_is_severe_at_exactly_thirty(api):
    """PRD §3.2: "On the passing branch the study moves `ORDERED → DIAGNOSTIC_VALID`,
    `severity_index` is stored, and `severity_band` is derived from it: at least 30.0 is
    `SEVERE`, at least 15.0 but below 30.0 is `MODERATE`, at least 5.0 but below 15.0 is `MILD`,
    and anything below 5.0 is `NONE`."
    PRD §3.2: "Every band boundary is inclusive on its lower edge."

    Design: Difficulty/boundary_precision_check/severity_band_at_exact_ahi_thirty
    """
    scenario = build_scenario("cast")
    study = order_and_result_study(
        scenario,
        results={"performed_on": "2026-04-10", "respiratory_events": 240,
                 "recording_minutes": 480, "artifact_pct": 0},
    )
    data = validate_success(api.get_sleep_study(study["id"], scenario["phys_headers"]))
    assert data["severity_index"] == approx_index(30.0)
    assert data["severity_band"] == "SEVERE", "30.0 is on the inclusive lower edge of SEVERE"
    assert data["status"] == "DIAGNOSTIC_VALID"


def test_severity_band_is_moderate_one_tenth_below_thirty(api):
    """PRD §3.2: "On the passing branch the study moves `ORDERED → DIAGNOSTIC_VALID`,
    `severity_index` is stored, and `severity_band` is derived from it: at least 30.0 is
    `SEVERE`, at least 15.0 but below 30.0 is `MODERATE`, at least 5.0 but below 15.0 is `MILD`,
    and anything below 5.0 is `NONE`."
    PRD §2.10: "Every rounding in this specification is **round half up**: at the stated
    precision, a discarded remainder of exactly one half raises the retained digit."

    Design: Difficulty/boundary_precision_check/severity_band_at_exact_ahi_thirty
    """
    scenario = build_scenario("cast")
    study = order_and_result_study(
        scenario,
        results={"performed_on": "2026-04-10", "respiratory_events": 239,
                 "recording_minutes": 480, "artifact_pct": 0},
    )
    data = validate_success(api.get_sleep_study(study["id"], scenario["phys_headers"]))
    assert data["severity_index"] == approx_index(29.9), "239 over 8.0 hours is 29.875 → 29.9"
    assert data["severity_band"] == "MODERATE"
    assert data["status"] == "DIAGNOSTIC_VALID"


def test_non_diagnostic_hsat_reorder_clears_the_recording_and_repeats(api):
    """PRD §3.2: "An `HSAT` is diagnostic when `recording_minutes` is at least 240 and
    `artifact_pct` is at most 20; attendance is irrelevant to it."
    PRD §3.2: "A non-diagnostic recording does not require a new study row. The physician
    re-orders on the same row, which moves it `NON_DIAGNOSTIC → ORDERED`, raises `repeat_count`
    by 1, and clears `performed_on`, `respiratory_events`, `recording_minutes`, `sleep_minutes`,
    `artifact_pct`, `attended`, `severity_index` and `severity_band` all back to null."

    Design: Corner/state_machines/non_diagnostic_hsat_reorder_cycle_clears_results
    """
    scenario = build_scenario("cast")
    study = order_and_result_study(
        scenario,
        results={"performed_on": "2026-04-10", "respiratory_events": 240,
                 "recording_minutes": 239, "artifact_pct": 0},
    )
    assert study["status"] == "NON_DIAGNOSTIC", "239 monitored minutes is one short of 240"
    assert_is_null(study["severity_band"], "SleepStudy.severity_band")

    reordered = validate_success(
        api.reorder_sleep_study(study["id"], {"modality": "HSAT"}, scenario["phys_headers"])
    )
    assert reordered["status"] == "ORDERED"
    assert reordered["repeat_count"] == 1
    assert_is_null(reordered["recording_minutes"], "SleepStudy.recording_minutes")

    retried = validate_success(
        api.post_sleep_study_results(
            study["id"],
            sleep_study_results_payload(
                performed_on="2026-04-20", respiratory_events=240,
                recording_minutes=240, artifact_pct=0,
            ),
            scenario["phys_headers"],
        )
    )
    assert retried["status"] == "DIAGNOSTIC_VALID"
    assert retried["severity_index"] == approx_index(60.0)
    assert retried["severity_band"] == "SEVERE"


def test_psg_quality_gate_reads_attendance_and_ignores_artifact(api):
    """PRD §3.2: "A `PSG` is diagnostic when `sleep_minutes` is at least 180 and `attended` is
    true; artifact is irrelevant to it, so a polysomnogram with an `artifact_pct` of 90 is still
    diagnostic if it scored enough sleep with a technologist present."
    PRD §3.2: "On the failing branch the study moves `ORDERED → NON_DIAGNOSTIC`, and
    `severity_index` is **still computed and stored** — the arithmetic is not conditional on
    quality — but `severity_band` is set to null, and a study in this state may never ground a
    referral or an efficacy report."

    Design: Corner/calculations/unattended_psg_is_non_diagnostic_regardless_of_artifact
    """
    scenario = build_scenario("cast")
    unattended = order_and_result_study(
        scenario,
        results={"performed_on": "2026-04-10", "respiratory_events": 120,
                 "recording_minutes": 480, "sleep_minutes": 240,
                 "artifact_pct": 0, "attended": False},
        study_overrides={"modality": "PSG", "study_purpose": "DIAGNOSTIC"},
    )
    noisy = order_and_result_study(
        scenario,
        results={"performed_on": "2026-04-10", "respiratory_events": 120,
                 "recording_minutes": 480, "sleep_minutes": 240,
                 "artifact_pct": 90, "attended": True},
        study_overrides={"modality": "PSG", "study_purpose": "DIAGNOSTIC"},
    )
    assert unattended["status"] == "NON_DIAGNOSTIC"
    assert noisy["status"] == "DIAGNOSTIC_VALID"
    assert noisy["severity_index"] == approx_index(30.0)
    assert unattended["severity_index"] == approx_index(30.0), (
        "the index is computed even on the failing branch"
    )
    assert_is_null(unattended["severity_band"], "SleepStudy.severity_band")


def test_diagnosis_currency_window_differs_by_modality(api):
    """PRD §3.3: "A referral grounded on an `HSAT` carries a `diagnosis_valid_until` of the
    study's `performed_on` plus 365 days; grounded on a `PSG`, it is `performed_on` plus 1095
    days."
    PRD §3.3: "Creation snapshots `severity_band_at_referral` from the grounding study — a later
    re-read of that study can never change what the referral was admitted on — and initialises
    `loop_status` to `OPEN` and `status` to `ISSUED`."

    Design: Corner/calculations/psg_diagnosis_stays_current_three_years_where_hsat_expires_in_one
    """
    scenario = build_scenario("cast", extra_dentist=True)
    hsat = order_and_result_study(
        scenario,
        results={"performed_on": "2026-04-10", "respiratory_events": 240,
                 "recording_minutes": 480, "artifact_pct": 0},
        study_overrides={"modality": "HSAT", "study_purpose": "DIAGNOSTIC"},
    )
    psg = order_and_result_study(
        scenario,
        results={"performed_on": "2026-04-10", "respiratory_events": 120,
                 "recording_minutes": 480, "sleep_minutes": 240,
                 "artifact_pct": 0, "attended": True},
        study_overrides={"modality": "PSG", "study_purpose": "DIAGNOSTIC"},
    )
    ref_hsat = validate_success(
        api.create_referral(
            create_referral_payload(
                scenario["pat_id"], scenario["phys_id"], scenario["dent_id"], hsat["id"],
                cpap_history="REFUSAL", cpap_nights_used=0,
                cpap_documented_on="2026-03-01",
            ),
            scenario["phys_headers"],
        ),
        201,
    )
    ref_psg = validate_success(
        api.create_referral(
            create_referral_payload(
                scenario["pat_id"], scenario["phys_id"], scenario["dent2_id"], psg["id"],
                cpap_history="REFUSAL", cpap_nights_used=0,
                cpap_documented_on="2026-03-01",
            ),
            scenario["phys_headers"],
        ),
        201,
    )
    assert_calendar_date(
        ref_hsat["diagnosis_valid_until"], "2027-04-10", "Referral.diagnosis_valid_until"
    )
    assert_calendar_date(
        ref_psg["diagnosis_valid_until"], "2029-04-09", "Referral.diagnosis_valid_until"
    )
    assert ref_hsat["eligibility_basis"] == "CPAP_INTOLERANT_SEVERE"
    assert ref_psg["severity_band_at_referral"] == "SEVERE"


def test_ordered_study_that_was_never_resulted_cannot_ground_a_referral(api):
    """PRD §2.6 rung 16: "A referenced `SleepStudy` must be in status `DIAGNOSTIC_VALID` — an
    `ORDERED` study that was never resulted, or a `NON_DIAGNOSTIC` one that failed its modality
    quality gate, may neither ground a referral nor ground an efficacy report. A violation is
    `ERR_STUDY_NON_DIAGNOSTIC` (422). Applies to referral creation and efficacy-report creation."
    PRD §2.6: "Rung 16 sits above rung 17 because a `NON_DIAGNOSTIC` study also has a null
    `severity_band`: were the band checked first, `ERR_STUDY_NON_DIAGNOSTIC` would be
    unreachable."

    Design: Corner/validations/non_diagnostic_study_is_refused_before_the_band_is_examined
    """
    scenario = build_scenario("cast")
    bad_study = order_and_result_study(
        scenario,
        results={"performed_on": "2026-04-10", "respiratory_events": 240,
                 "recording_minutes": 200, "artifact_pct": 0},
    )
    ordered_study = validate_success(
        api.create_sleep_study(
            create_sleep_study_payload(scenario["pat_id"], scenario["phys_id"]),
            scenario["phys_headers"],
        ),
        201,
    )
    assert bad_study["status"] == "NON_DIAGNOSTIC"

    for study_id in (bad_study["id"], ordered_study["id"]):
        error = validate_error(
            api.create_referral(
                create_referral_payload(
                    scenario["pat_id"], scenario["phys_id"], scenario["dent_id"], study_id,
                ),
                scenario["phys_headers"],
            ),
            ApiErrorId.ERR_STUDY_NON_DIAGNOSTIC.value,
        )
        assert error["error_id"] != ApiErrorId.ERR_DIAGNOSIS_REQUIRED.value


def test_valid_recording_below_the_mild_edge_is_not_a_diagnosis(api):
    """PRD §2.6 rung 17: "The study grounding a referral must carry an actual diagnosis: its
    `study_purpose` is `DIAGNOSTIC` and its `severity_band` is `MILD`, `MODERATE` or `SEVERE`. A
    violation is `ERR_DIAGNOSIS_REQUIRED` (422). Applies to referral creation."
    PRD §3.3: "A band of `NONE`, or a null band, means there is nothing to treat and the request
    is refused with `ERR_DIAGNOSIS_REQUIRED`."

    Design: Corner/validations/study_with_severity_band_none_is_not_a_diagnosis
    """
    scenario = build_scenario("cast")
    study = order_and_result_study(
        scenario,
        results={"performed_on": "2026-04-10", "respiratory_events": 24,
                 "recording_minutes": 480, "artifact_pct": 0},
    )
    assert study["severity_index"] == approx_index(3.0)
    assert study["severity_band"] == "NONE"
    assert study["status"] == "DIAGNOSTIC_VALID"

    validate_error(
        api.create_referral(
            create_referral_payload(
                scenario["pat_id"], scenario["phys_id"], scenario["dent_id"], study["id"],
            ),
            scenario["phys_headers"],
        ),
        ApiErrorId.ERR_DIAGNOSIS_REQUIRED.value,
    )


def test_logical_clock_reads_the_declared_epoch_before_it_is_ever_set(api):
    """PRD §2.4: "It maintains a logical clock which, before the first time anyone sets it, reads
    exactly `2026-05-01T00:00:00Z` and which never falls back to wall-clock time thereafter."
    PRD §3.4: "The row is created already in `SUBMITTED`, with `submitted_on` stamped from the
    clock date and `appeal_attempts` at 0."

    Design: Corner/endpoints/logical_clock_defaults_to_2026_05_01_before_any_set
    """
    scenario = build_scenario(
        "referral_accepted",
        touch_clock=False,
        payer_overrides={"prior_auth_required": True},
    )
    prior_auth = validate_success(
        api.create_prior_auth(
            {
                "patient_id": scenario["pat_id"],
                "payer_id": scenario["payer_med_id"],
                "referral_id": scenario["ref_id"],
                "requested_hcpcs": "E0486",
            },
            scenario["billing_headers"],
        ),
        201,
    )
    assert_calendar_date(prior_auth["submitted_on"], "2026-05-01", "PriorAuth.submitted_on")
    assert prior_auth["status"] == "SUBMITTED"
    assert prior_auth["appeal_attempts"] == 0
    referral = validate_success(
        api.get_referral(scenario["ref_id"], scenario["phys_headers"])
    )
    assert_calendar_date(
        referral["diagnosis_valid_until"], "2027-04-10", "Referral.diagnosis_valid_until"
    )
