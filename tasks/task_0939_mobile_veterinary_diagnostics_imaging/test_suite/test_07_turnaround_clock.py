"""The turnaround clock: business minutes, wall minutes, holds and STAT escalation."""
from test_helpers import (
    TEST_USERS,
    accepted_referral_with_appointment,
    assert_same_instant,
    assert_tat_partition,
    make_clinic_user_headers,
    make_specialist_headers,
    new_clinic,
    new_specialist,
    new_study,
    offer_and_accept_read,
    set_clock,
    setup_telerad_scene,
    upload_study,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
SCHED = TEST_USERS["scheduler_headers"]


# --------------------------------------------------------------------------
# The breach comparator — difficulty instance
# --------------------------------------------------------------------------
def _routine_telerad_study_created_monday_at_nine(api):
    set_clock("2026-05-04T09:00:00Z")
    scene = setup_telerad_scene(
        clinic_name="Clockwatch Vet", address_zone="Z12",
        requested_modality="RADIOGRAPHY", study_modality="RADIOGRAPHY",
        body_regions=("STIFLE",), upload=False,
    )
    return scene["clinic"], scene["studies"][0]


def test_a_routine_study_at_exactly_two_hundred_and_forty_minutes_is_still_accruing(api):
    """PRD §3.8: "A routine study is given **240 minutes measured only inside the
    referring clinic's business windows** — four working hours, which across a default
    Monday-to-Friday 08:00-to-17:00 UTC calendar means the clock stops every evening
    and does not run at all at weekends."
    PRD §3.8: "The comparison is strict: a routine study sitting at exactly 240
    accrued business minutes is still `ACCRUING`, and one at 241 is `BREACHED`."

    Derivation: the study is created on Monday 2026-05-04 at 09:00 UTC, inside the
    clinic's default 08:00-17:00 window, so at 13:00 UTC exactly 240 business minutes
    have accrued.

    Design: Difficulty/boundary_precision_check/tat_breach_is_strictly_greater_than_at_240_business_minutes
    """
    clinic, study = _routine_telerad_study_created_monday_at_nine(api)

    set_clock("2026-05-04T13:00:00Z")
    fetched = validate_success(api.get_study(study["id"], make_clinic_user_headers(clinic["id"])))

    assert fetched["tat_target_minutes"] == 240
    assert fetched["tat_accrued_minutes"] == 240
    assert fetched["tat_status"] == "ACCRUING"
    assert_tat_partition(fetched)


def test_one_further_business_minute_flips_the_routine_study_to_breached(api):
    """PRD §3.8: "Otherwise, if `tat_accrued_minutes` is **strictly greater than**
    `tat_target_minutes`, the study moves `ACCRUING → BREACHED`."
    PRD §3.8: "The first time a study enters `BREACHED`, one notification of kind
    `TAT_BREACHED` is appended for its clinic."
    PRD §2.11: "Reading a study additionally evaluates the turnaround breach test
    described in §3.8, which can move a study into `BREACHED` with no client having
    written anything."

    Derivation: 09:00 to 13:01 UTC on a Monday inside the 08:00-17:00 window is 241
    business minutes, one past the 240-minute target.

    Design: Difficulty/boundary_precision_check/tat_breach_is_strictly_greater_than_at_240_business_minutes
    """
    clinic, study = _routine_telerad_study_created_monday_at_nine(api)
    clinic_headers = make_clinic_user_headers(clinic["id"])
    set_clock("2026-05-04T13:00:00Z")
    validate_success(api.get_study(study["id"], clinic_headers))

    set_clock("2026-05-04T13:01:00Z")
    fetched = validate_success(api.get_study(study["id"], clinic_headers))

    assert fetched["tat_accrued_minutes"] == 241
    assert fetched["tat_status"] == "BREACHED"
    rows, _meta = validate_paginated(
        api.list_notifications(SCHED, params={"study_id": study["id"], "kind": "TAT_BREACHED"})
    )
    assert len(rows) == 1


# --------------------------------------------------------------------------
# Business minutes versus wall minutes
# --------------------------------------------------------------------------
def test_a_routine_clock_skips_the_weekend_while_a_stat_clock_does_not(api):
    """PRD §2.5: "**Wall minutes between two instants.** Given a start instant and an
    end instant, the wall-minute count is the number of whole minutes from the start
    to the end: take the difference in seconds, divide by 60 and truncate toward zero,
    and treat any negative result as zero. The calendar is ignored entirely — nights,
    weekends and holidays all count."
    PRD §3.8: "`tat_elapsed_minutes` is the number of minutes between the anchor and
    the logical clock's current value, counted in the study's **accrual mode**: wall
    minutes when the study's `priority` is `STAT`, business minutes against the
    referring clinic's calendar when it is `ROUTINE`."

    Derivation: both studies are created Friday 2026-05-01 at 16:00 UTC and read on
    Monday 2026-05-04 at 09:00 UTC.  In business mode that is 16:00-17:00 on Friday
    (60 minutes) plus 08:00-09:00 on Monday (60 minutes), the weekend contributing
    nothing, so 120 minutes against a 240-minute target.  In wall mode it is 65 hours,
    that is 3900 minutes, against a 60-minute target.

    Design: Corner/calculations/routine_turnaround_skips_the_weekend_while_stat_does_not
    """
    set_clock("2026-05-01T16:00:00Z")
    clinic = new_clinic("Weekend Vet", "ZW")
    _routine_referral, routine_appointment = accepted_referral_with_appointment(
        clinic["id"], patient_name="Sol", study_kind="TELERAD",
        requested_modality="RADIOGRAPHY", priority="ROUTINE", clinical_history="chronic",
    )
    routine_study = new_study(routine_appointment["id"], clinic["id"],
                              modality="RADIOGRAPHY", body_region="SPINE")
    _stat_referral, stat_appointment = accepted_referral_with_appointment(
        clinic["id"], patient_name="Luna", study_kind="TELERAD",
        requested_modality="RADIOGRAPHY", priority="STAT", clinical_history="acute abdomen",
    )
    stat_study = new_study(stat_appointment["id"], clinic["id"],
                           modality="RADIOGRAPHY", body_region="ABDOMEN")

    set_clock("2026-05-04T09:00:00Z")
    routine = validate_success(api.get_study(routine_study["id"], SCHED))
    stat = validate_success(api.get_study(stat_study["id"], SCHED))

    assert routine["tat_accrued_minutes"] == 120
    assert routine["tat_target_minutes"] == 240
    assert routine["tat_status"] == "ACCRUING"
    assert routine["tat_paused_minutes"] == 0
    assert stat["tat_accrued_minutes"] == 3900
    assert stat["tat_target_minutes"] == 60
    assert stat["tat_status"] == "BREACHED"
    assert stat["tat_paused_minutes"] == 0


# --------------------------------------------------------------------------
# Escalation is not monotone in elapsed time
# --------------------------------------------------------------------------
def test_escalating_an_acquired_study_breaches_it_the_instant_it_is_upgraded(api):
    """PRD §3.8: "The clock is measured from the study's `tat_anchor_at`, and which
    instant that is depends on `priority_source`. For a `NATIVE` study — one whose
    priority was fixed at order time — the anchor is the study's `created_at`, so the
    whole order-to-report span is measured. For an `UPGRADED` study — one raised to
    `STAT` after the fact — the anchor is the study's `acquired_at`, or, when the
    study has not been acquired yet, its `escalated_at`."
    PRD §3.8: "Escalation sets `priority` to `STAT`, sets `priority_source` to
    `UPGRADED`, stamps `escalated_at` with the logical clock, re-anchors
    `tat_anchor_at` to the study's `acquired_at`, re-targets `tat_target_minutes` to
    60 wall minutes, adds the 4500-cent STAT surcharge to the study's price, and
    appends a notification of kind `STAT_UPGRADED`."
    PRD §3.8: "Such a study is `BREACHED` the instant it is upgraded, with no time
    having passed at all: the clock jumps `ACCRUING → BREACHED` as a direct
    consequence of the escalation."

    Derivation: the study is created at 08:20 and uploaded at 09:30 on Monday
    2026-05-04; at 11:00 it has accrued 160 business minutes of its 240-minute routine
    budget.  Escalation re-anchors to 09:30 and re-targets to 60 wall minutes, and
    09:30 to 11:00 is 90 wall minutes — already past the new target.

    Design: Corner/calculations/stat_escalation_after_acquisition_breaches_the_study_instantly
    """
    set_clock("2026-05-04T08:20:00Z")
    clinic = new_clinic("Escalate Vet", "ZX")
    _referral, appointment = accepted_referral_with_appointment(
        clinic["id"], patient_name="Ivy", study_kind="TELERAD",
        requested_modality="ULTRASOUND", priority="ROUTINE", clinical_history="vomiting",
    )
    study = new_study(appointment["id"], clinic["id"])
    set_clock("2026-05-04T09:30:00Z")
    upload_study(study["id"], clinic["id"], image_count=12)
    set_clock("2026-05-04T11:00:00Z")

    before = validate_success(api.get_study(study["id"], SCHED))
    assert before["tat_accrued_minutes"] == 160
    assert before["tat_status"] == "ACCRUING"
    assert_same_instant(before["tat_anchor_at"], "2026-05-04T08:20:00Z")

    after = validate_success(
        api.escalate_stat(study["id"], make_clinic_user_headers(clinic["id"]))
    )

    assert_same_instant(after["tat_anchor_at"], "2026-05-04T09:30:00Z")
    assert after["tat_target_minutes"] == 60
    assert after["tat_accrued_minutes"] == 90
    assert after["tat_status"] == "BREACHED"
    assert after["priority_source"] == "UPGRADED"
    assert_same_instant(after["escalated_at"], "2026-05-04T11:00:00Z")
    upgraded_rows, _m1 = validate_paginated(
        api.list_notifications(SCHED, params={"study_id": study["id"], "kind": "STAT_UPGRADED"})
    )
    assert len(upgraded_rows) == 1
    breach_rows, _m2 = validate_paginated(
        api.list_notifications(SCHED, params={"study_id": study["id"], "kind": "TAT_BREACHED"})
    )
    assert len(breach_rows) == 1


# --------------------------------------------------------------------------
# Hold and resume conserve the elapsed partition — difficulty instance
# --------------------------------------------------------------------------
def _study_read_in_progress_at_ten(api):
    """A routine telerad study created at 09:00 Monday, read-ready, with an ACCEPTED
    read assignment — so the reading specialist may hold its clock under both the
    workflow precondition and the ownership rule."""
    set_clock("2026-05-04T09:00:00Z")
    scene = setup_telerad_scene(
        clinic_name="Pause Vet", address_zone="Z19", technician_name="Hub QC Two",
        technician_modalities=("RADIOGRAPHY",), species="FELINE",
        requested_modality="RADIOGRAPHY", study_modality="RADIOGRAPHY",
        body_regions=("THORAX",), image_count=3,
    )
    specialist = new_specialist("Dr Sato", ("RADIOGRAPHY",), ("FELINE",), stat_eligible=False)
    study = scene["studies"][0]
    offer_and_accept_read(study["id"], specialist["id"])
    return scene["clinic"], specialist, study


def test_holding_the_clock_pauses_it_and_resuming_clears_the_hold(api):
    """PRD §3.8: "**Holding the clock.** A reading `Specialist` may pause the clock
    pending input from the clinic, supplying a `hold_reason` of either
    `MISSING_HISTORY` or `ADDENDUM_QUESTION`. A hold requires the study's `tat_status`
    to be `ACCRUING` and its `workflow_status` to be one of `ACQUIRED`, `ASSIGNED`,
    `READ_IN_PROGRESS` or `PRELIM_REPORTED`; it moves the clock `ACCRUING → PAUSED`
    and stamps `pause_started_at` with the logical clock."
    PRD §3.8: "It requires `tat_status` to be `PAUSED`, moves the clock `PAUSED →
    ACCRUING`, adds the minutes of the now-closed pause window — counted in the
    study's accrual mode — to `tat_paused_minutes`, and clears both `pause_started_at`
    and `hold_reason` back to null."

    Design: Difficulty/compensating_invariant/turnaround_hold_and_resume_conserve_the_elapsed_partition
    """
    clinic, specialist, study = _study_read_in_progress_at_ten(api)

    set_clock("2026-05-04T10:00:00Z")
    held = validate_success(
        api.hold_study(study["id"], {"hold_reason": "MISSING_HISTORY"},
                       make_specialist_headers(specialist["id"]))
    )
    assert held["tat_status"] == "PAUSED"

    set_clock("2026-05-04T11:00:00Z")
    resumed = validate_success(
        api.resume_study(study["id"], {"clinical_history": "aspiration two days ago"},
                         make_clinic_user_headers(clinic["id"]))
    )

    assert resumed["tat_status"] == "ACCRUING"
    assert resumed["pause_started_at"] is None
    assert resumed["hold_reason"] is None


def test_the_elapsed_partition_survives_a_hold_and_resume_exactly(api):
    """PRD §2.10: "**Turnaround partition.** A study's `tat_elapsed_minutes` equals its
    `tat_accrued_minutes` plus its `tat_paused_minutes`, exactly."
    PRD §3.8: "`tat_paused_minutes` is the number of minutes the clock spent stopped,
    counted in the **same** mode so the partition invariant cannot drift: it is the
    sum, over every closed hold-and-resume window on the study, of the minutes that
    window contains, plus — when the study is currently `PAUSED` — the minutes between
    `pause_started_at` and the logical clock's current value."
    PRD §3.8: "`tat_accrued_minutes` is `tat_elapsed_minutes` less
    `tat_paused_minutes`, and §2.10 requires the three to reconcile exactly."

    Derivation: the study is created at 09:00 on Monday and read at 12:00, so 180
    business minutes have elapsed; the hold ran 10:00 to 11:00, which is 60 business
    minutes paused, leaving 120 accrued.

    Design: Difficulty/compensating_invariant/turnaround_hold_and_resume_conserve_the_elapsed_partition
    """
    clinic, specialist, study = _study_read_in_progress_at_ten(api)
    set_clock("2026-05-04T10:00:00Z")
    validate_success(
        api.hold_study(study["id"], {"hold_reason": "MISSING_HISTORY"},
                       make_specialist_headers(specialist["id"]))
    )
    set_clock("2026-05-04T11:00:00Z")
    validate_success(
        api.resume_study(study["id"], {"clinical_history": "aspiration two days ago"},
                         make_clinic_user_headers(clinic["id"]))
    )

    set_clock("2026-05-04T12:00:00Z")
    fetched = validate_success(api.get_study(study["id"], SCHED))

    assert fetched["tat_elapsed_minutes"] == 180
    assert fetched["tat_paused_minutes"] == 60
    assert fetched["tat_accrued_minutes"] == 120
    assert_tat_partition(fetched)
    assert fetched["tat_status"] == "ACCRUING"
