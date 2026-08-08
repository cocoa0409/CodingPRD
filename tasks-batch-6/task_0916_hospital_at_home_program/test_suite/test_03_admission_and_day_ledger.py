"""Admission itself: what the five-part write produces and what it re-checks."""

from test_helpers import (
    ApiErrorId,
    assert_day_ledger,
    assert_episode,
    assert_same_instant,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    ADMITTING_PHYSICIAN,
    BILLING_ANALYST,
    PROGRAM_ADMIN,
)


def test_admission_mints_the_first_pending_compliance_day(api):
    """PRD §3.2: "A successful admission is a five-part write. The new episode
    opens in `ACTIVE`; `admitted_at` is stamped from the logical clock;
    `physician_eval_at` is copied from the latest-created assessment's
    `in_person_eval_at`; the episode's own `acuity` is copied verbatim from the
    referral's `acuity`, which is what later halves or does not halve the
    escalation deadlines; the referral advances `ELIGIBLE → ADMITTED` with its
    `version` incremented by 1; the patient's `status` moves `REGISTERED →
    IN_PROGRAM`; and exactly one compliance record is minted in `PENDING` for the
    UTC calendar date of `admitted_at`."

    Design: Corner/entities/episode_creation_mints_first_pending_compliance_day_and_computed_counters
    """
    parts = fx.setup_eligible_referral(
        clock="2026-06-01T08:00:00Z",
        eval_at="2026-06-01T06:00:00Z",
        acuity="HIGH",
        mrn="MRN-CF",
        full_name="Cyd Computed",
    )
    patient, referral = parts["patient"], parts["referral"]

    episode = validate_success(
        api.create_episode(
            {
                "patient_id": patient["id"],
                "referral_id": referral["id"],
                "program_track": "CMS_WAIVER",
            },
            ADMITTING_PHYSICIAN,
        ),
        201,
    )
    assert_episode(episode)
    assert episode["status"] == "ACTIVE"
    assert episode["acuity"] == "HIGH", "the episode copies the referral's acuity"
    assert_same_instant(episode["admitted_at"], "2026-06-01T08:00:00Z", "admitted_at")
    assert_same_instant(
        episode["physician_eval_at"], "2026-06-01T06:00:00Z", "physician_eval_at"
    )
    assert_day_ledger(episode, service=1, billable=0, carved_out=0, pending=1)

    assert (
        validate_success(api.get_referral(referral["id"], ADMITTING_PHYSICIAN))["status"]
        == "ADMITTED"
    )
    assert (
        validate_success(api.get_patient(patient["id"], PROGRAM_ADMIN))["status"]
        == "IN_PROGRAM"
    )

    days, meta = validate_paginated(
        api.list_compliance_days(episode["id"], PROGRAM_ADMIN)
    )
    assert meta["total_count"] == 1, (
        f"admission mints exactly one compliance record, got {meta['total_count']}"
    )
    assert days[0]["service_date"] == "2026-06-01"
    assert days[0]["status"] == "PENDING"


def test_physician_evaluation_window_is_inclusive_at_twenty_four_hours(api):
    """PRD §3.2: "That window rule reads the latest-created assessment's
    `in_person_eval_at` and requires it to fall at or after the admission instant
    minus twenty-four hours *and* at or before the admission instant itself; both
    bounds are inclusive, so an evaluation performed exactly twenty-four hours
    before admission passes, an evaluation twenty-four hours and one minute
    before admission fails, and an evaluation dated after the admission instant
    also fails. Either failure yields `ERR_EVAL_WINDOW_EXPIRED`."

    Design: Corner/validations/physician_eval_exactly_24_hours_before_admission_passes_and_one_minute_earlier_fails
    """
    edge = fx.setup_eligible_referral(
        clock="2026-06-01T08:00:00Z",
        eval_at="2026-06-01T08:00:00Z",
        mrn="MRN-EG",
        full_name="Eve Edge",
    )
    stale = fx.setup_eligible_referral(
        set_the_clock=False,
        eval_at="2026-06-01T07:59:00Z",
        mrn="MRN-SA",
        full_name="Sal Stale",
    )

    fx.set_clock("2026-06-02T08:00:00Z")

    admitted = validate_success(
        api.create_episode(
            {
                "patient_id": edge["patient"]["id"],
                "referral_id": edge["referral"]["id"],
                "program_track": "CMS_WAIVER",
            },
            ADMITTING_PHYSICIAN,
        ),
        201,
    )
    assert_same_instant(
        admitted["physician_eval_at"], "2026-06-01T08:00:00Z", "physician_eval_at"
    )

    validate_error(
        api.create_episode(
            {
                "patient_id": stale["patient"]["id"],
                "referral_id": stale["referral"]["id"],
                "program_track": "CMS_WAIVER",
            },
            ADMITTING_PHYSICIAN,
        ),
        ApiErrorId.ERR_EVAL_WINDOW_EXPIRED.value,
    )
    assert (
        validate_success(
            api.get_referral(stale["referral"]["id"], ADMITTING_PHYSICIAN)
        )["status"]
        == "ELIGIBLE"
    ), "the rejected admission must not consume the referral"


def test_service_radius_is_rechecked_at_admission_time(api):
    """PRD §3.2: "Two eligibility rules are then re-run at this later moment, in
    this order: first the service-radius rule, because a patient's
    `home_distance_km` may have been revised since screening (failure:
    `ERR_OUTSIDE_SERVICE_RADIUS`), and then the physician-evaluation window rule,
    which is checked **only here and nowhere else**."
    PRD §3.1: "Because home circumstances change between the first phone call and
    the eligibility visit, a `ProgramAdmin` or `AdmittingPhysician` may later
    revise `home_distance_km`, `diet_restriction`, `broadband_verified` and
    `caregiver_present` on an existing patient — each such revision advances that
    patient's `version` by 1 and refreshes `updated_at`."

    Design: Corner/validations/patient_moved_outside_the_radius_after_eligibility_blocks_admission
    """
    parts = fx.setup_eligible_referral(
        home_distance_km=12.5, mrn="MRN-MV", full_name="Mo Moved"
    )
    patient, referral, assessment = (
        parts["patient"],
        parts["referral"],
        parts["assessment"],
    )

    eligible = validate_success(api.get_referral(referral["id"], ADMITTING_PHYSICIAN))
    assert eligible["status"] == "ELIGIBLE"
    assert eligible["first_failed_gauntlet_rung"] is None

    rows, meta = validate_paginated(
        api.list_referral_assessments(referral["id"], ADMITTING_PHYSICIAN)
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == assessment["id"]

    validate_success(
        api.update_patient(patient["id"], {"home_distance_km": 55.0}, ADMITTING_PHYSICIAN)
    )

    validate_error(
        api.create_episode(
            {
                "patient_id": patient["id"],
                "referral_id": referral["id"],
                "program_track": "CMS_WAIVER",
            },
            ADMITTING_PHYSICIAN,
        ),
        ApiErrorId.ERR_OUTSIDE_SERVICE_RADIUS.value,
    )
    assert (
        validate_success(api.get_referral(referral["id"], ADMITTING_PHYSICIAN))["status"]
        == "ELIGIBLE"
    )

    validate_success(
        api.update_patient(patient["id"], {"home_distance_km": 12.5}, ADMITTING_PHYSICIAN)
    )
    episode = validate_success(
        api.create_episode(
            {
                "patient_id": patient["id"],
                "referral_id": referral["id"],
                "program_track": "CMS_WAIVER",
            },
            ADMITTING_PHYSICIAN,
        ),
        201,
    )
    assert episode["status"] == "ACTIVE"
    assert (
        validate_success(api.get_referral(referral["id"], ADMITTING_PHYSICIAN))["status"]
        == "ADMITTED"
    )


def test_episode_version_increments_on_direct_and_cascaded_mutations(api):
    """PRD §2.4: "`version` is an integer that begins at 1 when the row is
    created and increases by exactly 1 on every mutation of that row — including
    mutations the caller did not directly request, such as a bed census shifting
    because a sibling reservation expired, or an episode's day-ledger counters
    being recomputed after a compliance day flips."
    PRD §3.2: "Signing it sets `med_rec_signed` to true, records the signing
    physician's opaque identifier in `med_rec_signed_by_user_id`, and advances
    the episode's `version` by 1."

    Design: Corner/cross_cutting_complexity_layers/episode_version_increments_on_every_mutation_including_cascades
    """
    parts = fx.setup_active_episode(
        program_track="FEE_FOR_SERVICE", mrn="MRN-VR", full_name="Vera Version"
    )
    episode = parts["episode"]
    version_at_admission = episode["version"]
    assert version_at_admission == 1, (
        f"an episode's version begins at 1, got {version_at_admission}"
    )

    fx.perform_and_attest_visit(
        episode["id"], "2026-06-01T09:00:00Z", "2026-06-01T09:45:00Z"
    )
    day = fx.compliance_day_for(episode["id"], "2026-06-01")

    after_sign = validate_success(
        api.sign_med_rec(episode["id"], ADMITTING_PHYSICIAN)
    )
    assert after_sign["version"] > version_at_admission, (
        "signing medication reconciliation is a direct mutation of the episode"
    )

    validate_success(api.finalize_compliance_day(day["id"], PROGRAM_ADMIN))
    after_finalize = validate_success(api.get_episode(episode["id"], BILLING_ANALYST))
    assert after_finalize["version"] > after_sign["version"], (
        "the day-ledger recompute is a cascaded mutation of the episode"
    )
    assert after_finalize["med_rec_signed"] is True
    assert after_finalize["billable_day_count"] == 1

    finalized_day = fx.compliance_day_for(episode["id"], "2026-06-01")
    assert finalized_day["status"] == "COMPLIANT"


def test_episode_list_narrows_by_patient_referral_and_status(api):
    """PRD §3.2: "Episodes are readable individually and as a filterable list
    narrowed by `patient_id`, `referral_id` and `status`."
    PRD §2.3: "Filter parameters supported by an individual list (for example
    `status`, `service_date`, `scheduling_status`, `reconciliation_status`,
    `patient_id`, `referral_id`, `episode_id` or `unit_id`) are applied before
    the sort and before the page window, so `total_count` always reflects the
    filtered set rather than the whole table."

    Design: Corner/endpoints/episodes_filtered_list_narrows_by_patient_and_status
    """
    first = fx.setup_active_episode(mrn="MRN-FL1", full_name="Fay Filter")
    second = fx.setup_active_episode(
        set_the_clock=False, mrn="MRN-FL2", full_name="Fred Filter"
    )

    by_patient, by_patient_meta = validate_paginated(
        api.list_episodes(
            BILLING_ANALYST,
            params={"patient_id": first["patient"]["id"], "status": "ACTIVE"},
        )
    )
    assert by_patient_meta["total_count"] == 1
    assert len(by_patient) == 1
    assert by_patient[0]["id"] == first["episode"]["id"]

    by_referral, by_referral_meta = validate_paginated(
        api.list_episodes(
            BILLING_ANALYST, params={"referral_id": second["referral"]["id"]}
        )
    )
    assert by_referral_meta["total_count"] == 1
    assert by_referral[0]["id"] == second["episode"]["id"]

    _, unfiltered_meta = validate_paginated(api.list_episodes(BILLING_ANALYST))
    assert unfiltered_meta["total_count"] == 2
