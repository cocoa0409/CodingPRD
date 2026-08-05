"""The efficacy report, its dual criterion, the physician's signature and the recall cadence."""

from test_helpers import (
    ApiErrorId,
    approx_index,
    approx_rate,
    assert_calendar_date,
    assert_efficacy_report,
    build_scenario,
    create_efficacy_report_payload,
    make_sleep_physician_headers,
    read_referral_version,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_efficacy_outcome_is_complete_when_both_criteria_hold(api):
    """PRD §3.7: "`pct_reduction` is `baseline_index` minus `residual_index`, divided by
    `baseline_index`, rounded half up to 4 decimal places."
    PRD §3.7: "When both criteria hold the `outcome` is `COMPLETE`; when exactly one holds it is
    `PARTIAL`; when neither holds it is `FAILED`."
    PRD §3.7: "A baseline of 30.0 falling to 4.0 gives 0.8667 and satisfies both, so it is
    `COMPLETE`."

    Design: Difficulty/transitive_cascade/efficacy_signoff_cascade_depth_four
    """
    scenario = build_scenario("efficacy_submitted", efficacy_events=32)
    report = validate_success(
        api.get_efficacy_report(scenario["rep_id"], scenario["dent_headers"])
    )
    assert_efficacy_report(report)
    assert report["baseline_index"] == approx_index(30.0)
    assert report["residual_index"] == approx_index(4.0)
    assert report["pct_reduction"] == approx_rate(0.8667)
    assert report["outcome"] == "COMPLETE"


def test_physician_signature_closes_the_cross_provider_loop(api):
    """PRD §3.7: "The report moves `SUBMITTED → SIGNED`, `physician_decision_on` is stamped from
    the clock date, and a three-level cascade runs: the referral moves `ACCEPTED → CLOSED` and
    its `loop_status` becomes `CLOSED`; the appliance moves `EFFICACY_PENDING → ACTIVE_THERAPY`;
    and the patient-recall cadence starts, with `recall_status` moving `NOT_SCHEDULED → NOT_DUE`
    and `next_recall_due_on` set to the clock date plus 90 days while `recall_cycle_index` stays
    at 0."

    Design: Difficulty/transitive_cascade/efficacy_signoff_cascade_depth_four
    """
    scenario = build_scenario("efficacy_submitted", efficacy_events=32)
    set_clock("2026-07-07T00:00:00Z")
    signed = validate_success(
        api.physician_respond_to_efficacy_report(
            scenario["rep_id"], {"decision": "SIGNED"}, scenario["phys_headers"]
        )
    )
    assert signed["outcome"] == "COMPLETE"
    assert signed["status"] == "SIGNED"
    referral = validate_success(
        api.get_referral(scenario["ref_id"], scenario["phys_headers"])
    )
    assert referral["status"] == "CLOSED"
    assert referral["loop_status"] == "CLOSED"


def test_physician_signature_starts_the_patient_recall_cadence(api):
    """PRD §3.7: "The report moves `SUBMITTED → SIGNED`, `physician_decision_on` is stamped from
    the clock date, and a three-level cascade runs: the referral moves `ACCEPTED → CLOSED` and
    its `loop_status` becomes `CLOSED`; the appliance moves `EFFICACY_PENDING → ACTIVE_THERAPY`;
    and the patient-recall cadence starts, with `recall_status` moving `NOT_SCHEDULED → NOT_DUE`
    and `next_recall_due_on` set to the clock date plus 90 days while `recall_cycle_index` stays
    at 0."
    PRD §3.7: "Activation sets `next_recall_due_on` to 90 days after the date therapy became
    active — measured from activation, not from delivery."

    Design: Difficulty/transitive_cascade/efficacy_signoff_cascade_depth_four
    """
    scenario = build_scenario("active_therapy", efficacy_events=32)
    appliance = validate_success(
        api.get_appliance(scenario["app_id"], scenario["dent_headers"])
    )
    assert appliance["lifecycle_status"] == "ACTIVE_THERAPY"
    assert appliance["recall_status"] == "NOT_DUE"
    assert_calendar_date(
        appliance["next_recall_due_on"], "2026-10-05", "Appliance.next_recall_due_on"
    )
    assert appliance["recall_cycle_index"] == 0


def test_efficacy_outcome_is_failed_when_neither_criterion_holds(api):
    """PRD §3.7: "The absolute criterion, `meets_absolute_target`, is true when `residual_index`
    is at most the payer's `residual_ahi_target` — 5.0 by default — regardless of how far the
    patient came."
    PRD §3.7: "The relative criterion, `meets_relative_target`, is true when `pct_reduction` is
    at least the payer's `pct_reduction_target` — 0.50 by default — **and** `residual_index` is
    below 10.0; the second clause stops a spectacular percentage drop from certifying a patient
    who is still frankly apnoeic."
    PRD §3.7: "When both criteria hold the `outcome` is `COMPLETE`; when exactly one holds it is
    `PARTIAL`; when neither holds it is `FAILED`."

    Design: Corner/calculations/efficacy_outcome_failed_when_neither_criterion_is_met
    """
    scenario = build_scenario("efficacy_drafted", efficacy_events=160)
    report = validate_success(
        api.get_efficacy_report(scenario["rep_id"], scenario["dent_headers"])
    )
    assert report["baseline_index"] == approx_index(30.0)
    assert report["residual_index"] == approx_index(20.0)
    assert report["pct_reduction"] == approx_rate(0.3333)
    assert report["meets_absolute_target"] is False
    assert report["meets_relative_target"] is False
    assert report["outcome"] == "FAILED"


def test_efficacy_outcome_is_partial_at_exactly_half_the_reduction_target(api):
    """PRD §3.7: "The relative criterion, `meets_relative_target`, is true when `pct_reduction`
    is at least the payer's `pct_reduction_target` — 0.50 by default — **and** `residual_index`
    is below 10.0; the second clause stops a spectacular percentage drop from certifying a
    patient who is still frankly apnoeic."
    PRD §3.3: "For a `MODERATE` band, oral appliance therapy is first-line and **no**
    positive-airway-pressure documentation is required at all: `eligibility_basis` is set to
    `FIRST_LINE_MILD_MODERATE` and no further test runs."

    Design: Corner/calculations/efficacy_outcome_partial_at_exact_fifty_percent_reduction
    """
    scenario = build_scenario(
        "efficacy_drafted",
        study_results={"respiratory_events": 144},
        referral_overrides={
            "cpap_history": "NONE", "cpap_nights_used": 0, "cpap_documented_on": None,
        },
        efficacy_events=72,
    )
    referral = validate_success(
        api.get_referral(scenario["ref_id"], scenario["dent_headers"])
    )
    assert referral["severity_band_at_referral"] == "MODERATE"
    assert referral["eligibility_basis"] == "FIRST_LINE_MILD_MODERATE"

    report = validate_success(
        api.get_efficacy_report(scenario["rep_id"], scenario["dent_headers"])
    )
    assert report["baseline_index"] == approx_index(18.0)
    assert report["residual_index"] == approx_index(9.0)
    assert report["pct_reduction"] == approx_rate(0.5000)
    assert report["meets_relative_target"] is True
    assert report["meets_absolute_target"] is False
    assert report["outcome"] == "PARTIAL"


def test_treating_dentist_may_not_sign_off_his_own_efficacy_report(api):
    """PRD §2.6 rung 14: "On a physician response to an efficacy report, the acting `X-User-ID`
    must be the referral's `referring_physician_id`; if it is instead the referral's
    `treating_dentist_id` — exactly what happens when a treating dentist presents the
    `SleepPhysician` role header to sign off his own titration — the answer is
    `ERR_SELF_REFERRAL` (422), not `ERR_NOT_CARE_TEAM`, because the treating dentist genuinely
    passes the rung-6 care-team test."

    Design: Corner/rbac/treating_dentist_cannot_sign_off_his_own_efficacy_report
    """
    scenario = build_scenario("efficacy_submitted", efficacy_events=32)
    dentist_wearing_physician_hat = make_sleep_physician_headers(scenario["dent_id"])
    validate_error(
        api.physician_respond_to_efficacy_report(
            scenario["rep_id"], {"decision": "SIGNED"}, dentist_wearing_physician_hat
        ),
        ApiErrorId.ERR_SELF_REFERRAL.value,
    )
    report = validate_success(
        api.get_efficacy_report(scenario["rep_id"], scenario["dent_headers"])
    )
    assert report["status"] == "SUBMITTED"
    referral = validate_success(
        api.get_referral(scenario["ref_id"], scenario["dent_headers"])
    )
    assert referral["loop_status"] == "OPEN"
    appliance = validate_success(
        api.get_appliance(scenario["app_id"], scenario["dent_headers"])
    )
    assert appliance["lifecycle_status"] == "EFFICACY_PENDING"


def test_stale_referral_version_blocks_efficacy_report_creation(api):
    """PRD §2.7: "**Creating an `EfficacyReport`** requires `expected_referral_version` carrying
    the client's last observed `version` of the target `Referral`. A mismatch with the referral's
    current `version` is rejected with `ERR_STALE_VERSION` (412). A new report supersedes a
    `DISPUTED` report on the same referral, so a stale writer would replace a revision the
    physician has already acted on."

    Design: Corner/cross_cutting_complexity_layers/stale_referral_version_blocks_efficacy_report_creation
    """
    scenario = build_scenario("plateau")
    eff_study = validate_success(
        api.create_sleep_study(
            {
                "patient_id": scenario["pat_id"],
                "ordering_physician_id": scenario["phys_id"],
                "modality": "HSAT",
                "study_purpose": "EFFICACY",
                "appliance_id": scenario["app_id"],
            },
            scenario["phys_headers"],
        ),
        201,
    )
    validate_success(
        api.post_sleep_study_results(
            eff_study["id"],
            {
                "performed_on": "2026-07-05", "respiratory_events": 32,
                "recording_minutes": 480, "artifact_pct": 0,
            },
            scenario["phys_headers"],
        )
    )
    set_clock("2026-07-06T00:00:00Z")
    stale_version = read_referral_version(scenario["ref_id"], scenario["dent_headers"])
    first = validate_success(
        api.create_efficacy_report(
            create_efficacy_report_payload(
                scenario["ref_id"], scenario["app_id"], eff_study["id"], stale_version
            ),
            scenario["dent_headers"],
        ),
        201,
    )
    validate_error(
        api.create_efficacy_report(
            create_efficacy_report_payload(
                scenario["ref_id"], scenario["app_id"], eff_study["id"], stale_version
            ),
            scenario["dent_headers"],
        ),
        ApiErrorId.ERR_STALE_VERSION.value,
    )
    reread = validate_success(
        api.get_efficacy_report(first["id"], scenario["dent_headers"])
    )
    assert reread["status"] == "DRAFT"
    assert reread["outcome"] == "COMPLETE"
    rows, meta = validate_paginated(
        api.list_efficacy_reports(
            scenario["dent_headers"], {"referral_id": scenario["ref_id"]}
        )
    )
    assert meta["total_count"] == 1 and len(rows) == 1


def test_signature_cascade_bumps_the_version_of_every_row_it_touches(api):
    """PRD §2.5: "When a request cascades into other rows, each *distinct row* that is actually
    written is likewise raised by exactly 1 — never once per affected field and never once per
    cascade level."
    PRD §2.11: "Wherever a cascade writes to a row, that row's `updated_at` is refreshed and its
    `version` rises by exactly 1 — once for the whole request, as §2.5 requires — and the cascade
    is atomic with the operation that triggered it: either every level lands or the request fails
    and none does."

    Design: Corner/cross_cutting_complexity_layers/cascaded_side_effects_bump_version_on_every_touched_row
    """
    scenario = build_scenario("efficacy_submitted", efficacy_events=32)
    referral_before = validate_success(
        api.get_referral(scenario["ref_id"], scenario["dent_headers"])
    )
    appliance_before = validate_success(
        api.get_appliance(scenario["app_id"], scenario["dent_headers"])
    )
    set_clock("2026-07-07T00:00:00Z")
    validate_success(
        api.physician_respond_to_efficacy_report(
            scenario["rep_id"], {"decision": "SIGNED"}, scenario["phys_headers"]
        )
    )
    referral_after = validate_success(
        api.get_referral(scenario["ref_id"], scenario["dent_headers"])
    )
    appliance_after = validate_success(
        api.get_appliance(scenario["app_id"], scenario["dent_headers"])
    )
    assert referral_after["version"] > referral_before["version"]
    assert appliance_after["version"] > appliance_before["version"]
    assert referral_after["status"] == "CLOSED"
    assert appliance_after["lifecycle_status"] == "ACTIVE_THERAPY"
    assert appliance_after["recall_status"] == "NOT_DUE"


def test_recall_axis_walks_due_then_lapsed_then_resets_from_the_check_date(api):
    """PRD §3.7: "Every time a `PlatformAdmin` sets the logical clock, the posture of every
    appliance in `ACTIVE_THERAPY` is re-evaluated, and the lapse test is applied **first**: when
    the clock date has reached or passed `next_recall_due_on` plus 30 grace days, `recall_status`
    becomes `LAPSED`; otherwise, when the clock date has reached or passed `next_recall_due_on`,
    it becomes `DUE`. Both boundaries are inclusive."
    PRD §3.7: "From either `DUE` or `LAPSED` the check returns `recall_status` to `NOT_DUE` and
    raises `recall_cycle_index` by 1, and the next check falls 365 days later. On the lapsed arm
    the specification is explicit that the next due date is recomputed **from the date the check
    was actually performed, not from the missed due date**, so a late check pushes the whole
    cadence out rather than compressing it — and the calculation that governs both arms, together
    with its stated rationale, measures every subsequent cycle from the date the previous check
    was performed."

    Design: Corner/state_machines/clock_sweep_moves_recall_axis_not_due_then_due_then_lapsed
    """
    scenario = build_scenario("active_therapy", efficacy_events=32)
    set_clock("2026-10-05T00:00:00Z")
    on_due_date = validate_success(
        api.get_appliance(scenario["app_id"], scenario["dent_headers"])
    )
    assert on_due_date["recall_status"] == "DUE", "the due date itself is inclusive"

    set_clock("2026-11-04T00:00:00Z")
    lapsed = validate_success(
        api.get_appliance(scenario["app_id"], scenario["dent_headers"])
    )
    assert lapsed["recall_status"] == "LAPSED", "30 grace days after the due date"

    set_clock("2026-11-10T00:00:00Z")
    checked = validate_success(
        api.perform_recall_check(
            scenario["app_id"],
            {"notes": "Appliance intact, retention good"},
            scenario["dent_headers"],
        )
    )
    assert checked["recall_status"] == "NOT_DUE"
    assert checked["recall_cycle_index"] == 1
    assert_calendar_date(
        checked["next_recall_due_on"], "2027-11-10", "Appliance.next_recall_due_on"
    )
    assert checked["lifecycle_status"] == "ACTIVE_THERAPY"
