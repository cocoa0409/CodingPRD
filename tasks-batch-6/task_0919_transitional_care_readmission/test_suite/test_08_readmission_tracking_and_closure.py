"""Thirty-day readmission tracking, the record-freeze cascade, retraction and
administrative closure."""
from test_helpers import (
    ADMIN,
    CLINICIAN,
    ApiErrorId,
    assert_episode_readmission_conservation,
    assert_readmission_event,
    connect_contact,
    add_navigator,
    open_medrec,
    complete_medrec,
    propose_handoff,
    raise_barrier,
    raise_red_flag,
    read_barrier,
    read_claim,
    read_episode,
    read_handoff,
    read_medrec,
    read_navigator,
    read_patient,
    read_readmission,
    read_red_flag,
    record_readmission,
    set_clock,
    setup_program_with_episode,
    setup_submitted_claim,
    validate_error,
    validate_success,
)


def test_unplanned_readmission_closes_the_episode_and_voids_the_claim(api):
    """PRD §3.9: "`UNPLANNED_INPATIENT` is the one that counts toward the
    readmission rate and the only one with teeth: it sets the episode's
    `billing_eligible` to false; if the episode's `status` is `ACTIVE` or
    `SERVICE_PERIOD_CLOSED` it stores that value in `pre_readmission_status` and
    drives the episode to `CLOSED_READMITTED`, which also decrements the
    navigator's `active_episode_count` and the patient's `open_episode_count` by
    1 each and recomputes the navigator's `workload_score` and
    `availability_status`; if the episode has a claim sitting in `PREPARED`,
    `SUBMITTED`, `DENIED` or `APPEALED`, that claim is voided with
    `net_payable_cents` zeroed; and if the claim has already reached `PAID`, the
    claim is **not** voided — instead the episode's `recoupment_required` is set
    to true, because money that has already moved must be clawed back rather
    than cancelled."

    Design: Difficulty/transitive_cascade/unplanned_readmission_five_hop_cascade
    """
    ctx, ep, _visit, claim = setup_submitted_claim()
    event = record_readmission(ctx, ep, "2026-05-20", "UNPLANNED_INPATIENT")
    assert_readmission_event(event)
    assert event["status"] == "RECORDED"
    assert event["day_index"] == 19
    assert event["counts_toward_rate"] is True

    episode = read_episode(ctx, ep["episode_id"])
    assert episode["status"] == "CLOSED_READMITTED"
    assert episode["pre_readmission_status"] == "SERVICE_PERIOD_CLOSED"
    assert episode["billing_eligible"] is False
    assert episode["readmission_event_count"] == 1
    assert episode["counted_readmission_count"] == 1
    assert episode["excluded_readmission_count"] == 0
    assert episode["retracted_readmission_count"] == 0
    assert_episode_readmission_conservation(episode)

    voided = read_claim(ctx, claim["id"])
    assert voided["status"] == "VOIDED"
    assert voided["net_payable_cents"] == 0

    assert read_navigator(ctx, ctx["navigator_id"])["active_episode_count"] == 0
    assert read_patient(ctx, ep["patient_id"])["open_episode_count"] == 0


def test_freeze_cascade_supersedes_handoffs_and_closes_children(api):
    """PRD §3.9: "the claim reaching a terminal status makes the episode
    eligible for the freeze evaluation, which flips `record_posture` from `OPEN`
    to `FROZEN`; and the freeze in turn supersedes every proposed handoff,
    closes every open or acknowledged red flag administratively and closes every
    open or escalated barrier administratively."
    PRD §2.7: "Freezing is not merely a flag; it runs a three-branch cascade
    over the episode's children. Every handoff request still in `PROPOSED` moves
    to `SUPERSEDED` with `superseded_by_id` left null, because no newer proposal
    caused it. Every red flag in `RAISED` or `ACKNOWLEDGED` moves to
    `CLOSED_ADMINISTRATIVE`, which drives the episode's `open_red_flag_count`
    down to 0 and its `escalation_state` back to `NONE`. Every barrier in `OPEN`
    or `ESCALATED` moves to `CLOSED_ADMINISTRATIVE` with `closed_at` stamped at
    the current instant."

    Design: Difficulty/transitive_cascade/unplanned_readmission_five_hop_cascade
    """
    ctx, ep, _visit, _claim = setup_submitted_claim()
    nav2, _nav2_headers = add_navigator(ctx, full_name="Owen Park")
    barrier = raise_barrier(ctx, ep, "TRANSPORTATION", "no ride to clinic")
    flag = raise_red_flag(ctx, ep, category="CLINICAL_SYMPTOM", initial_tier="TIER_3")
    handoff = propose_handoff(ctx, ep, nav2["id"])

    record_readmission(ctx, ep, "2026-05-20", "UNPLANNED_INPATIENT")

    episode = read_episode(ctx, ep["episode_id"])
    assert episode["record_posture"] == "FROZEN"
    assert episode["open_red_flag_count"] == 0
    assert episode["escalation_state"] == "NONE"

    after_handoff = read_handoff(ctx, handoff["id"])
    assert after_handoff["status"] == "SUPERSEDED"
    assert after_handoff["superseded_by_id"] is None
    assert read_red_flag(ctx, flag["id"])["status"] == "CLOSED_ADMINISTRATIVE"

    after_barrier = read_barrier(ctx, barrier["id"])
    assert after_barrier["status"] == "CLOSED_ADMINISTRATIVE"
    assert after_barrier["closed_at"] is not None


def test_readmission_on_day_thirty_is_inside_the_window(api):
    """PRD §3.9: "The window is open at the left and closed at the right: a
    `day_index` of 1 through 30 inclusive is inside the window, while a
    `day_index` of 0 — a same-day return — is outside it, a `day_index` of 31 is
    outside it, and any negative value is outside it."
    PRD §3.9: "An accepted event opens in `status` `RECORDED`, records
    `recorded_by_user_id` from the acting `X-User-ID`, leaves
    `retraction_reason` and `source_red_flag_id` null, and sets
    `counts_toward_rate` true only when the `classification` is
    `UNPLANNED_INPATIENT`."

    Design: Difficulty/boundary_precision_check/readmission_day_30_accepted_day_31_and_day_0_rejected
    """
    ctx, ep = setup_program_with_episode()
    connect_contact(ctx, ep)
    set_clock("2026-06-05T10:00:00Z")

    event = validate_success(
        api.record_readmission(
            ep["episode_id"],
            {"readmission_date": "2026-05-31", "classification": "OBSERVATION_ONLY"},
            ADMIN,
        ),
        201,
    )
    assert event["day_index"] == 30
    assert event["classification"] == "OBSERVATION_ONLY"
    assert event["counts_toward_rate"] is False
    assert event["status"] == "RECORDED"
    assert event["source_red_flag_id"] is None
    assert event["retraction_reason"] is None

    episode = read_episode(ctx, ep["episode_id"])
    assert episode["readmission_event_count"] == 1
    assert episode["excluded_readmission_count"] == 1
    assert episode["counted_readmission_count"] == 0
    assert episode["status"] == "ACTIVE"
    assert episode["billing_eligible"] is True


def test_readmission_on_day_thirty_one_and_day_zero_fall_outside_the_window(api):
    """PRD §3.9: "Anything outside is refused with
    `ERR_READMISSION_OUT_OF_WINDOW`."
    PRD §3.9: "The event's `day_index` is the whole number of calendar days from
    the episode's `discharge_date` to the `readmission_date`. The window is open
    at the left and closed at the right: a `day_index` of 1 through 30 inclusive
    is inside the window, while a `day_index` of 0 — a same-day return — is
    outside it, a `day_index` of 31 is outside it, and any negative value is
    outside it."

    Design: Difficulty/boundary_precision_check/readmission_day_30_accepted_day_31_and_day_0_rejected
    """
    ctx, ep = setup_program_with_episode()
    connect_contact(ctx, ep)
    set_clock("2026-06-05T10:00:00Z")

    validate_error(
        api.record_readmission(
            ep["episode_id"],
            {"readmission_date": "2026-06-01", "classification": "OBSERVATION_ONLY"},
            ADMIN,
        ),
        ApiErrorId.ERR_READMISSION_OUT_OF_WINDOW.value,
    )
    validate_error(
        api.record_readmission(
            ep["episode_id"],
            {"readmission_date": "2026-05-01", "classification": "OBSERVATION_ONLY"},
            ADMIN,
        ),
        ApiErrorId.ERR_READMISSION_OUT_OF_WINDOW.value,
    )
    episode = read_episode(ctx, ep["episode_id"])
    assert episode["readmission_event_count"] == 0
    assert episode["status"] == "ACTIVE"


def test_retraction_moves_one_unit_into_the_retracted_bucket(api):
    """PRD §2.9: "Second, on a care episode, `readmission_event_count` always
    equals `counted_readmission_count` plus `excluded_readmission_count` plus
    `retracted_readmission_count`. Retracting an event moves one unit out of
    whichever of the first two buckets held it and into the retracted bucket,
    leaving the grand total untouched."
    PRD §3.9: "One unit leaves `counted_readmission_count` when the event
    counted toward the rate, or `excluded_readmission_count` when it did not,
    and lands in `retracted_readmission_count`; `readmission_event_count` does
    not change."

    Design: Difficulty/compensating_invariant/readmission_retract_conserves_event_totals_and_restores_episode
    """
    ctx, ep = setup_program_with_episode()
    connect_contact(ctx, ep)
    set_clock("2026-05-20T09:00:00Z")
    event = record_readmission(ctx, ep, "2026-05-15", "UNPLANNED_INPATIENT")
    assert event["day_index"] == 14

    before = read_episode(ctx, ep["episode_id"])
    assert before["readmission_event_count"] == 1
    assert before["counted_readmission_count"] == 1
    assert before["excluded_readmission_count"] == 0
    assert before["retracted_readmission_count"] == 0
    assert_episode_readmission_conservation(before)

    retracted = validate_success(
        api.retract_readmission(
            event["id"],
            {"retraction_reason": "coding error - admission belonged to a different index stay"},
            ADMIN,
        )
    )
    assert retracted["status"] == "RETRACTED"

    after = read_episode(ctx, ep["episode_id"])
    assert after["readmission_event_count"] == 1
    assert after["counted_readmission_count"] == 0
    assert after["excluded_readmission_count"] == 0
    assert after["retracted_readmission_count"] == 1
    assert_episode_readmission_conservation(after)
    assert read_patient(ctx, ep["patient_id"])["lifetime_readmission_count"] == 0


def test_retraction_restores_the_episode_status_and_thaws_the_records(api):
    """PRD §2.7: "Thawing is possible in exactly one direction. Retracting the
    unplanned-inpatient readmission that closed an episode restores the
    episode's `status` from `pre_readmission_status`, which takes it back out of
    the frozen status set, and the freeze evaluation then returns
    `record_posture` to `OPEN`."
    PRD §3.9: "For an `UNPLANNED_INPATIENT` event, the episode's `status` is
    restored from `pre_readmission_status`, `pre_readmission_status` is cleared
    back to null, `billing_eligible` returns to true, and the navigator's
    `active_episode_count` and the patient's `open_episode_count` each rise by 1
    again — restoring `ACTIVE` if that was the stored value, or
    `SERVICE_PERIOD_CLOSED` if that was."

    Design: Difficulty/compensating_invariant/readmission_retract_conserves_event_totals_and_restores_episode
    """
    ctx, ep = setup_program_with_episode()
    connect_contact(ctx, ep)
    set_clock("2026-05-20T09:00:00Z")
    event = record_readmission(ctx, ep, "2026-05-15", "UNPLANNED_INPATIENT")

    closed = read_episode(ctx, ep["episode_id"])
    assert closed["status"] == "CLOSED_READMITTED"
    assert closed["record_posture"] == "FROZEN"
    assert closed["billing_eligible"] is False

    validate_success(
        api.retract_readmission(
            event["id"], {"retraction_reason": "coding error"}, ADMIN
        )
    )
    after = read_episode(ctx, ep["episode_id"])
    assert after["status"] == "ACTIVE"
    assert after["pre_readmission_status"] is None
    assert after["billing_eligible"] is True
    assert after["record_posture"] == "OPEN"
    assert read_patient(ctx, ep["patient_id"])["open_episode_count"] == 1
    assert read_navigator(ctx, ctx["navigator_id"])["active_episode_count"] == 1
    assert read_readmission(ctx, event["id"])["status"] == "RETRACTED"


def test_planned_inpatient_readmission_flags_the_claim_without_closing_the_episode(api):
    """PRD §3.9: "`PLANNED_INPATIENT` and `OBSERVATION_ONLY` are excluded from
    the rate and behave as a matched pair: the episode's `status` is untouched,
    `billing_eligible` stays true, the episode's `excluded_readmission_count`
    rises by 1, and if a claim exists its `readmission_flagged` is set to true so
    that the payer-facing record notes the return."

    Design: Corner/state_machines/planned_inpatient_readmission_flags_claim_without_closing_episode
    """
    ctx, ep, _visit, claim = setup_submitted_claim()
    event = record_readmission(ctx, ep, "2026-05-25", "PLANNED_INPATIENT")
    assert event["day_index"] == 24
    assert event["counts_toward_rate"] is False
    assert event["status"] == "RECORDED"

    after_claim = read_claim(ctx, claim["id"])
    assert after_claim["status"] == "SUBMITTED"
    assert after_claim["readmission_flagged"] is True
    assert after_claim["net_payable_cents"] == 21480

    episode = read_episode(ctx, ep["episode_id"])
    assert episode["status"] == "SERVICE_PERIOD_CLOSED"
    assert episode["record_posture"] == "OPEN"
    assert episode["billing_eligible"] is True
    assert episode["recoupment_required"] is False
    assert episode["readmission_event_count"] == 1
    assert episode["excluded_readmission_count"] == 1
    assert episode["counted_readmission_count"] == 0


def test_frozen_records_preempt_the_invalid_state_error(api):
    """PRD §2.10: "**The global write gate.** The care episode that owns the
    target resource has `record_posture` equal to `OPEN` — otherwise
    `ERR_EPISODE_RECORDS_FROZEN` (409). Exempt: recording a readmission,
    retracting a readmission, setting the logical clock, and every read."
    PRD §2.10: "When a single request would fail more than one rule, the rule
    with the **lowest rung number** below decides the response. This ordering is
    normative: an implementation that reports a later rung's error where an
    earlier rung also failed is wrong, even if both conditions genuinely hold."

    Design: Difficulty/priority_pair_validation_conflict/frozen_gate_preempts_invalid_state
    """
    ctx, ep = setup_program_with_episode()
    medrec = open_medrec(ctx, ep)
    complete_medrec(ctx, medrec["id"])
    validate_success(
        api.admin_close_episode(
            ep["episode_id"], {"reason": "patient moved out of service area"}, ADMIN
        )
    )
    episode = read_episode(ctx, ep["episode_id"])
    assert episode["status"] == "ADMIN_CLOSED"
    assert episode["record_posture"] == "FROZEN"

    validate_error(
        api.complete_med_reconciliation(medrec["id"], CLINICIAN),
        ApiErrorId.ERR_EPISODE_RECORDS_FROZEN.value,
    )


def test_frozen_episode_leaves_the_completed_reconciliation_untouched(api):
    """PRD §3.9: "Administrative closure drives the episode to `ADMIN_CLOSED`,
    voids any claim sitting in `PREPARED`, `SUBMITTED`, `DENIED` or `APPEALED`
    with `net_payable_cents` zeroed, decrements the navigator's
    `active_episode_count` and the patient's `open_episode_count` by 1 each with
    the navigator's workload figures recomputed, and triggers the freeze
    evaluation together with its three-branch cascade."
    PRD §3.5: "A completed reconciliation may be reopened by a `Clinician`,
    moving it `COMPLETED → IN_REVIEW`, incrementing `reopen_count` by 1,
    clearing `completed_at` and setting the episode's `medrec_complete` back to
    false — which re-blocks attestation until the reconciliation is completed
    again."

    Design: Difficulty/priority_pair_validation_conflict/frozen_gate_preempts_invalid_state
    """
    ctx, ep = setup_program_with_episode()
    medrec = open_medrec(ctx, ep)
    complete_medrec(ctx, medrec["id"])
    validate_success(
        api.admin_close_episode(
            ep["episode_id"], {"reason": "patient moved out of service area"}, ADMIN
        )
    )
    validate_error(
        api.complete_med_reconciliation(medrec["id"], CLINICIAN),
        ApiErrorId.ERR_EPISODE_RECORDS_FROZEN.value,
    )
    after = read_medrec(ctx, medrec["id"])
    assert after["status"] == "COMPLETED"
    assert after["reopen_count"] == 0
    assert read_navigator(ctx, ctx["navigator_id"])["active_episode_count"] == 0
    assert read_patient(ctx, ep["patient_id"])["open_episode_count"] == 0


def test_invalid_state_preempts_the_service_period_open_error(api):
    """PRD §3.8: "Closing the service period is a `ProgramAdmin` action
    available only from `ACTIVE`, and only once the current instant is strictly
    after the end of `service_period_end_date`. The earliest legal moment is
    therefore `discharge_date` plus 30 days at `00:00:00.000Z`; an attempt
    before that is refused with `ERR_SERVICE_PERIOD_OPEN`, and an attempt on an
    episode not in `ACTIVE` is refused with `ERR_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_preempts_service_period_open
    """
    ctx, ep = setup_program_with_episode()
    set_clock("2026-05-03T09:00:00Z")
    validate_error(
        api.close_service_period(ep["episode_id"], ADMIN),
        ApiErrorId.ERR_INVALID_STATE.value,
    )
    episode = read_episode(ctx, ep["episode_id"])
    assert episode["status"] == "INTAKE"
    assert episode["record_posture"] == "OPEN"


def test_service_period_bounds_are_derived_at_intake(api):
    """PRD §3.8: "Day 0 is `discharge_date` itself, which is also
    `service_period_start_date`, so `service_period_end_date` is
    `discharge_date` plus 29 days. The readmission tracking window is one day
    longer: `readmission_window_end_date` is `discharge_date` plus 30 days."
    PRD §3.8: "an attempt before that is refused with `ERR_SERVICE_PERIOD_OPEN`,
    and an attempt on an episode not in `ACTIVE` is refused with
    `ERR_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_preempts_service_period_open
    """
    ctx, ep = setup_program_with_episode()
    set_clock("2026-05-03T09:00:00Z")
    validate_error(
        api.close_service_period(ep["episode_id"], ADMIN),
        ApiErrorId.ERR_INVALID_STATE.value,
    )
    episode = read_episode(ctx, ep["episode_id"])
    assert episode["service_period_end_date"] == "2026-05-30"
    assert episode["readmission_window_end_date"] == "2026-05-31"
