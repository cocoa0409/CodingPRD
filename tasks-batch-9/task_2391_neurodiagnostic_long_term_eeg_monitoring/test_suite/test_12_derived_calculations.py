"""
Derived calculations: the frozen marking weight, the clamped nurse-response
deadline, export package volume and the conference vote tally.

Every literal in this file is recomputed from the contract's own arithmetic and
its precision discipline — capture figures to 3 decimal places rounded half up,
storage volumes and percentages to 2, the response deadline an integer after a
nested clamp, and vote tallies plain integer counts.
"""

from test_helpers import (
    assert_alert_dimensions,
    assert_capture_value,
    assert_case_tallies,
    assert_fields_null,
    assert_ids_equal,
    assert_instant_equals,
    assert_storage_value,
    assert_unit_storage,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_errors as errors
from test_helpers import constants as const
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users

SEGMENT_CLOSE = "2026-08-02T02:00:00Z"
PRELIM_AT = "2026-08-02T12:00:00Z"
CONFERENCE_AT = "2026-08-06T00:00:00Z"
PRESENTER = "epi-p"


def _delivered_case(api, *, target_event_count, presenter_user_id=PRESENTER):
    """Walk one stay through acquisition, final interpretation, delivery and presentation.

    Returns the stay, the delivered package and the presented conference case.
    """
    baseline = fx.build_admitted_stay(
        api,
        bed_count=1,
        storage_quota_gb=500.00,
        requested_days=5,
        authorized_days=5,
        planned_days=2,
        target_event_count=target_event_count,
        admitted_at=const.T_ADMIT,
        channel_count=32,
    )
    fx.acquire_and_complete(
        api,
        baseline.study_id,
        baseline.shift_id,
        from_iso=const.T_ADMIT,
        to_iso=SEGMENT_CLOSE,
    )
    fx.finalized_report(api, baseline.study_id, prelim_at=PRELIM_AT)
    package = fx.delivered_export(
        api,
        baseline.study_id,
        include_video=True,
        recipient_center="Metro Surgical Center",
    )
    fx.set_clock(api, CONFERENCE_AT)
    case = fx.presented_case(
        api,
        admission_id=baseline.admission_id,
        export_id=package["id"],
        presenter_user_id=presenter_user_id,
    )
    return baseline, package, case


def test_marking_weight_discounted_at_taper_step_two(api):
    """A clinical seizure marked at taper step 2 freezes the discounted weight 0.750.

    PRD §3.7: "And `weight` is computed as the class weight of the `event_class` — 1.0
    for `CLINICAL_SEIZURE`, 0.5 for `SUBCLINICAL_SEIZURE`, and 0 for both `SPIKE_BURST`
    and `ARTIFACT` — multiplied by a provoked-event discount of 0.75 when
    `taper_step_at_onset` is 2 or greater, or by 1.0 when it is below 2, with the
    product rounded half up to 3 decimal places."
    PRD §3.7: "From that set: `weighted_event_count` is the sum of the members' `weight`
    values, rounded half up to 3 decimal places."
    PRD §3.7: "The retrospective figure stored on `capture_adequacy_index` is the lesser
    of 1.000 and `weighted_event_count` divided by `target_event_count`, rounded half up
    to 3 decimal places; it counts only weight already banked by adjudicated markings,
    it is clamped at 1.000, and it is **the only figure the `ADMITTED` to
    `CAPTURE_TARGET_MET` transition reads** — the transition fires when it reaches 1.000
    or more, and the reverse transition fires when it falls below 1.000."

    Design: Corner/calculations/marking_weight_discounted_at_taper_step_two
    """
    baseline = fx.build_admitted_stay(
        api,
        bed_count=1,
        storage_quota_gb=500.00,
        risk_tier=const.RISK_MODERATE,
        setting=const.SETTING_INPATIENT,
        requested_days=5,
        authorized_days=5,
        planned_days=2,
        target_event_count=4,
        admitted_at=const.T_ADMIT,
        channel_count=32,
    )
    # Two reduction steps taken, so the marking is provoked at step 2.
    plan = fx.create_taper_plan(
        api, baseline.admission_id, total_steps=3, steps_advanced=2
    )
    assert plan["current_step"] == 2, "setup should leave the taper plan at step 2"
    # One closed segment [00:00, 02:00) so the onset falls inside the recording.
    fx.acquire_segment(
        api,
        baseline.study_id,
        from_iso=const.T_ADMIT,
        to_iso=SEGMENT_CLOSE,
        shift_id=baseline.shift_id,
    )
    fx.set_clock(api, const.T_ADMIT_PLUS_1D)

    marking = fx.create_marking(
        api,
        baseline.study_id,
        "2026-08-02T01:30:00Z",
        event_class=const.EVENT_CLINICAL_SEIZURE,
        duration_seconds=70,
    )
    assert marking["taper_step_at_onset"] == 2, (
        f"taper_step_at_onset should be 2, got {marking['taper_step_at_onset']!r}"
    )
    # 1.0 class weight * 0.75 provoked discount = 0.750
    assert_capture_value(marking["weight"], 0.750, "marking weight")

    adjudicated = validate_success(
        api.adjudicate_marking(marking["id"], users.EPILEPTOLOGIST), 200
    )
    assert adjudicated["status"] == const.MARKING_ADJUDICATED, (
        f"marking status should be ADJUDICATED, got {adjudicated['status']!r}"
    )
    assert_instant_equals(
        adjudicated["adjudicated_at"], const.T_ADMIT_PLUS_1D, "adjudicated_at"
    )

    admission = validate_success(
        api.get_admission(baseline.admission_id, users.EPILEPTOLOGIST)
    )
    assert_capture_value(
        admission["weighted_event_count"], 0.750, "weighted_event_count"
    )
    # 0.750 / 4 = 0.1875, rounded half up to 3 places
    assert_capture_value(
        admission["capture_adequacy_index"], 0.188, "capture_adequacy_index"
    )
    # PRD §3.7: deficit is target minus banked weight, elapsed is one full day,
    # yield is 0.750 / 1.000 and the prospective figure adds 3 remaining days.
    assert_capture_value(admission["deficit_weighted"], 3.250, "deficit_weighted")
    assert_capture_value(
        admission["elapsed_monitored_days"], 1.000, "elapsed_monitored_days"
    )
    assert_capture_value(
        admission["projected_daily_yield"], 0.750, "projected_daily_yield"
    )
    assert_capture_value(
        admission["capture_adequacy_index_prospective"],
        0.750,
        "capture_adequacy_index_prospective",
    )
    assert admission["clinical_state"] == const.CLINICAL_ADMITTED, (
        "0.188 is far below the 1.000 target-met threshold, so the stay stays ADMITTED"
    )

    plan_after = validate_success(api.get_taper_plan(plan["id"], users.EPILEPTOLOGIST))
    assert plan_after["current_step"] == 2, "the marking must not move the taper plan"
    assert plan_after["status"] == const.TAPER_ACTIVE


def test_alert_deadline_clamps_up_to_floor_at_night(api):
    """A HIGH-tier overnight alert at taper step 3 sums to 1 minute and the floor lifts it to 2.

    PRD §3.6: "Start from the base allowance for the patient's `risk_tier`: 10 minutes
    for `LOW`, 6 minutes for `MODERATE`, 3 minutes for `HIGH` — the higher the clinical
    risk, the tighter the base."
    PRD §3.6: "Subtract one minute for each reduction step already taken, that is,
    subtract the `current_step` of the admission's taper plan, since deeper medication
    reduction demands a faster bedside response; a taper plan in `ACTIVE`, `HELD` or
    `COMPLETED` supplies that step, `ABORTED` plans are ignored, and when the admission
    has no taper plan at all the step reads 0."
    PRD §3.6: "Add 1 minute when the UTC hour of `detected_at` is 22 or later, or 5 or
    earlier — the overnight allowance."
    PRD §3.6: "Then clamp the sum: take the lesser of the sum and a ceiling of 15
    minutes, and then take the greater of that result and a floor of 2 minutes."

    Design: Corner/calculations/alert_deadline_clamps_up_to_floor_at_night
    """
    baseline = fx.build_admitted_stay(
        api,
        bed_count=1,
        storage_quota_gb=500.00,
        risk_tier=const.RISK_HIGH,
        setting=const.SETTING_INPATIENT,
        requested_days=5,
        authorized_days=5,
        planned_days=2,
        target_event_count=4,
        admitted_at=const.T_ADMIT,
        max_concurrent_studies=2,
        channel_count=32,
    )
    plan = fx.create_taper_plan(
        api, baseline.admission_id, total_steps=3, steps_advanced=3
    )
    assert plan["current_step"] == 3, "setup should leave the taper plan at step 3"
    assert plan["status"] == const.TAPER_COMPLETED, (
        "reaching total_steps completes the plan, and a COMPLETED plan still supplies "
        "its step to the deadline"
    )
    # One acquiring study against a window of capacity 2 keeps the unit OPEN,
    # so no coverage-constrained allowance is added.
    fx.start_study(api, baseline.study_id, baseline.shift_id, at=const.T_ADMIT)
    fx.set_clock(api, "2026-08-02T23:00:00Z")

    alert = validate_success(
        api.raise_alert(
            baseline.study_id,
            f.alert_payload(const.ALERT_SOURCE_PATIENT_PUSH_BUTTON),
            users.TECHNOLOGIST,
        ),
        201,
    )
    assert_instant_equals(alert["detected_at"], "2026-08-02T23:00:00Z", "detected_at")
    # base 3 - taper 3 + posture 0 + night 1 = 1, raised to the floor of 2
    assert alert["response_deadline_minutes"] == 2, (
        "response_deadline_minutes should be the floor 2, got "
        f"{alert['response_deadline_minutes']!r}"
    )
    assert_alert_dimensions(alert, const.TRIAGE_DETECTED, const.RESPONSE_AWAITING)
    assert_fields_null(alert, "responded_at", "latency_minutes")

    unit = validate_success(api.get_unit(baseline.unit_id, users.COORDINATOR))
    assert unit["posture"] == const.POSTURE_OPEN, (
        f"unit posture should be OPEN, got {unit['posture']!r}"
    )


def test_export_package_gb_without_video_divides_by_modality_factor(api):
    """Building without video divides the study volume by the inpatient modality factor.

    PRD §3.9: "The volume itself is a two-branch figure: when `include_video` is true,
    `package_gb` equals the study's `stored_gb` at build time exactly; when it is false,
    `package_gb` is the study's `stored_gb` divided by the study's modality factor — 2.5
    for `INPATIENT_VEEG`, 1.0 for `AMBULATORY_VEEG` — rounded half up to 2 decimal
    places, since stripping video from an inpatient recording strips most of its bulk
    while an ambulatory recording carries no video premium to strip."
    PRD §3.9: "On success the cascade runs in four links: first, `package_gb` is set from
    that computation, `built_at` is stamped from the clock, and `retention_expires_at` is
    set to 30 days after `built_at`, that being the first instant from which a sweep may
    purge the package; second, the package volume is added to the unit's
    `storage_used_gb`, which re-derives `storage_pressure_pct`; third, if that pressure
    has reached 90.00 percent or more the unit's `posture` becomes `STORAGE_LOCKED`; and
    fourth, because the posture is now locked, every *other* export package of that unit
    standing in `QUEUED` moves to `BLOCKED` with `blocked_reason` set to
    `UNIT_STORAGE_LOCKED`."
    PRD §2.11: "From that figure, `storage_pressure_pct` is the used volume divided by
    the unit's `storage_quota_gb`, multiplied by 100, rounded half up to 2 decimal
    places."

    Design: Corner/calculations/export_package_gb_without_video_divides_by_modality_factor
    """
    baseline = fx.build_admitted_stay(
        api,
        bed_count=1,
        storage_quota_gb=500.00,
        requested_days=5,
        authorized_days=5,
        planned_days=2,
        target_event_count=3,
        admitted_at=const.T_ADMIT,
        channel_count=32,
    )
    # One 120-minute segment at 0.0004 * 32 * 2.5 = 0.032 GB per minute
    study = fx.acquire_and_complete(
        api,
        baseline.study_id,
        baseline.shift_id,
        from_iso=const.T_ADMIT,
        to_iso=SEGMENT_CLOSE,
    )
    assert_storage_value(study["stored_gb"], 3.84, "stored_gb")
    fx.finalized_report(api, baseline.study_id, prelim_at=PRELIM_AT)
    package = fx.queue_export(api, baseline.study_id, include_video=False)
    fx.set_clock(api, "2026-08-05T00:00:00Z")

    built = validate_success(api.build_export(package["id"], users.COORDINATOR), 200)
    assert built["status"] == const.EXPORT_BUILT, (
        f"package status should be BUILT, got {built['status']!r}"
    )
    # 3.84 / 2.5 = 1.536, rounded half up to 2 places
    assert_storage_value(built["package_gb"], 1.54, "package_gb")
    assert_instant_equals(built["built_at"], "2026-08-05T00:00:00Z", "built_at")
    assert_instant_equals(
        built["retention_expires_at"], "2026-09-04T00:00:00Z", "retention_expires_at"
    )

    unit = validate_success(api.get_unit(baseline.unit_id, users.COORDINATOR))
    # 3.84 online study volume + 1.54 built package = 5.38; 5.38 / 500.00 * 100 = 1.076
    assert_unit_storage(
        unit,
        storage_used_gb=5.38,
        storage_pressure_pct=1.08,
        posture=const.POSTURE_OPEN,
    )

    study_after = validate_success(api.get_study(baseline.study_id, users.COORDINATOR))
    assert_storage_value(study_after["stored_gb"], 3.84, "stored_gb after the build")


def test_conference_vote_tally_defer_ties_win_at_t2(api):
    """One ballot each way plus one deferral resolves as a deferral, not as candidacy.

    PRD §3.9: "Second, if `defer_votes` is greater than or equal to `candidate_votes`
    **and** greater than or equal to `non_candidate_votes`, the outcome is a deferral — a
    deferral plurality wins ties against both other options."
    PRD §3.9: "A deferral outcome moves `status` to `DEFERRED`, increments `defer_round`
    by 1, and leaves `decision_at` null."
    PRD §3.9: "Critically, a deferral **retains the tallies of the round just closed** —
    `eligible_vote_count`, `candidate_votes`, `non_candidate_votes`, `defer_votes`,
    `distinct_specialty_count` and `quorum_met` all keep the values that decided the
    deferral, so the record of why the case was deferred survives."

    Design: Corner/calculations/conference_vote_tally_defer_ties_win_at_t2
    """
    _baseline, package, case = _delivered_case(api, target_event_count=3)
    fx.cast_ballots(
        api,
        case["id"],
        [
            {
                "voter_user_id": "epi-a",
                "specialty": const.SPECIALTY_EPILEPTOLOGY,
                "vote": const.VOTE_CANDIDATE,
                "rationale": "clear focal onset",
            },
            {
                "voter_user_id": "epi-b",
                "specialty": const.SPECIALTY_NEUROSURGERY,
                "vote": const.VOTE_NON_CANDIDATE,
                "rationale": "eloquent cortex",
            },
            {
                "voter_user_id": "epi-c",
                "specialty": const.SPECIALTY_NEURORADIOLOGY,
                "vote": const.VOTE_DEFER,
                "rationale": "await MRI re-read",
            },
        ],
    )

    closed = validate_success(
        api.close_vote(case["id"], users.as_epileptologist(PRESENTER)), 200
    )
    assert closed["status"] == const.CASE_DEFERRED, (
        f"a defer tie should resolve to DEFERRED, got {closed['status']!r}"
    )
    assert closed["decision_at"] is None, "a deferral leaves decision_at null"
    assert closed["defer_round"] == 1, (
        f"defer_round should be 1 after the deferral, got {closed['defer_round']!r}"
    )
    assert_case_tallies(
        closed,
        eligible_vote_count=3,
        candidate_votes=1,
        non_candidate_votes=1,
        defer_votes=1,
        distinct_specialty_count=3,
        quorum_met=True,
    )
    assert_ids_equal(closed["presenter_user_id"], PRESENTER, "presenter_user_id")

    package_after = validate_success(api.get_export(package["id"], users.COORDINATOR))
    assert package_after["status"] == const.EXPORT_DELIVERED
    # include_video true, so the package took the study's stored volume exactly
    assert_storage_value(package_after["package_gb"], 3.84, "package_gb")


def test_presenter_ballot_excluded_from_tally_blocks_quorum(api):
    """Three ballots are stored but the presenter's is uncounted, so quorum fails.

    PRD §3.9: "The server stamps `voter_user_id` from the acting `X-User-ID`,
    `round_index` from the case's `defer_round` at the instant the ballot was cast, and
    `counted` — which is false when the voter is the case's own `presenter_user_id` and
    true otherwise, so that the presenter may speak but not decide."
    PRD §3.9: "The tally is drawn only from ballots on this case whose `counted` is true
    and whose `round_index` equals the case's current `defer_round`; the presenter's
    uncounted ballot and every ballot from an earlier round are excluded."
    PRD §3.9: "`quorum_met` is true if and only if `eligible_vote_count` is at least 3
    **and** `distinct_specialty_count` is at least 2 — three voices spanning at least two
    disciplines."
    PRD §3.9: "First, if `quorum_met` is false the close is refused with
    `ERR_QUORUM_NOT_MET`."

    Design: Corner/calculations/presenter_ballot_excluded_from_tally_blocks_quorum
    """
    _baseline, _package, case = _delivered_case(api, target_event_count=3)
    presenter_ballot = fx.cast_ballot(
        api,
        case["id"],
        voter_user_id=PRESENTER,
        specialty=const.SPECIALTY_EPILEPTOLOGY,
        vote=const.VOTE_CANDIDATE,
        rationale="presenter opinion",
    )
    ballot_a = fx.cast_ballot(
        api,
        case["id"],
        voter_user_id="epi-a",
        specialty=const.SPECIALTY_EPILEPTOLOGY,
        vote=const.VOTE_CANDIDATE,
        rationale="focal onset",
    )
    ballot_b = fx.cast_ballot(
        api,
        case["id"],
        voter_user_id="epi-b",
        specialty=const.SPECIALTY_NEUROSURGERY,
        vote=const.VOTE_CANDIDATE,
        rationale="resectable",
    )

    validate_error(
        api.close_vote(case["id"], users.as_epileptologist(PRESENTER)),
        errors.ERR_QUORUM_NOT_MET,
        409,
    )

    ballots, meta = validate_paginated(
        api.list_case_votes(
            case["id"], users.EPILEPTOLOGIST, {"limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 3, (
        f"all three ballots should be stored, got total_count {meta['total_count']!r}"
    )
    by_id = {ballot["id"]: ballot for ballot in ballots}
    stored_presenter = by_id[presenter_ballot["id"]]
    assert stored_presenter["counted"] is False, (
        "the presenter's own ballot should carry counted false"
    )
    assert_ids_equal(stored_presenter["voter_user_id"], PRESENTER, "voter_user_id")
    assert stored_presenter["round_index"] == 0, (
        f"round_index should be 0, got {stored_presenter['round_index']!r}"
    )
    assert by_id[ballot_a["id"]]["counted"] is True
    assert by_id[ballot_b["id"]]["counted"] is True

    case_after = validate_success(
        api.get_conference_case(case["id"], users.EPILEPTOLOGIST)
    )
    assert_case_tallies(
        case_after,
        eligible_vote_count=2,
        candidate_votes=2,
        distinct_specialty_count=2,
        quorum_met=False,
    )
    assert case_after["status"] == const.CASE_PRESENTED, (
        "the refused close must leave the case PRESENTED"
    )
    assert case_after["decision_at"] is None
    assert case_after["defer_round"] == 0
