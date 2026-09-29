"""Session transitions, the consent terminal states and the retention sweep.

Every test in this module builds its own preconditions: the server is relaunched
with an empty database before each one, and the logical clock starts at exactly
2026-08-01T00:00:00Z.
"""

import pytest

from test_helpers import (
    PRIVACY_OFFICER_HEADERS,
    RESEARCHER_HEADERS,
    ApiErrorId,
    assert_retention_sweep,
    complete_session,
    create_finding,
    create_theme,
    grant_consent,
    invite,
    link_evidence,
    read_artifact,
    read_consent,
    read_finding,
    read_pool,
    read_recruitment,
    read_study,
    register_artifact,
    schedule,
    screen,
    screening_answers,
    screening_criteria,
    set_clock,
    setup_fielding_study,
    setup_invited_recruitments,
    setup_planned_study,
    setup_scheduled_sessions,
    setup_screened_in_recruitments,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK_START = "2026-08-01T00:00:00.000Z"
BIG_POOL = {"incentive_budget_cents": 100000}


# ===========================================================================
# Unlisted transitions and terminal states
# ===========================================================================
def test_completing_an_invited_recruitment_is_refused(api):
    """COMPLETED and SCHEDULED are both reachable only from a later state than INVITED.

    PRD 3.5: "**Completion** carries `SCHEDULED → COMPLETED` and records
    `actual_duration_min`, the duration the moderator reports."

    PRD 3.5: "Booking a session carries a screened-in candidate `SCREENED_IN →
    SCHEDULED`."

    PRD 2.6: "**State legality** — `ERR_INVALID_STATE` (409) when the requested
    transition does not exist out of the resource's current state."

    Design: Corner/state_machines/completing_an_invited_recruitment_is_rejected
    """
    ctx = setup_invited_recruitments(api, participant_count=1, pool_overrides=BIG_POOL)
    recruitment_id = ctx["recruitments"][0]["id"]

    early_completion = api.complete_recruitment(
        recruitment_id, {"actual_duration_min": 45}, RESEARCHER_HEADERS
    )
    validate_error(early_completion, ApiErrorId.INVALID_STATE.value)

    early_schedule = api.schedule_recruitment(
        recruitment_id,
        {
            "scheduled_start": "2026-08-05T10:00:00Z",
            "scheduled_end": "2026-08-05T11:00:00Z",
            "moderator_user_id": "u_res_1",
        },
        RESEARCHER_HEADERS,
    )
    validate_error(early_schedule, ApiErrorId.INVALID_STATE.value)

    recruitment = read_recruitment(recruitment_id, api)
    assert recruitment["status"] == "INVITED", (
        f"Expected the recruitment to stay INVITED after two refused transitions, "
        f"got {recruitment['status']}"
    )
    assert recruitment["actual_duration_min"] is None, (
        f"Expected actual_duration_min to stay null, "
        f"got {recruitment['actual_duration_min']}"
    )
    assert recruitment["incentive_state"] == "RESERVED", (
        f"Expected a refused transition to move no money, "
        f"got incentive_state {recruitment['incentive_state']}"
    )

    study = read_study(ctx["study"]["id"], api)
    assert study["completed_count"] == 0, (
        f"Expected completed_count 0, got {study['completed_count']}"
    )
    assert study["recruitment_status"] == "RECRUITING", (
        f"Expected recruitment_status RECRUITING after the invitation, "
        f"got {study['recruitment_status']}"
    )


def test_revoking_an_already_revoked_consent_is_refused(api):
    """REVOKED is terminal, so the cascade cannot be replayed by a second revocation.

    PRD 3.6: "A `PrivacyOfficer` — and only a `PrivacyOfficer` — may revoke a
    `GRANTED` record with a supplied `reason`, carrying it `GRANTED → REVOKED`,
    setting `revoked_at` to the clock instant and storing the `reason` as
    `revocation_reason`."

    PRD 3.6: "`REVOKED` and `EXPIRED` are both terminal."

    PRD 3.6: "Take the smallest maximum across every scope the record grants, take
    the smaller of that figure and the requested `retention_days`, and add that
    many whole days to `granted_at` to obtain `retention_until`, preserving the
    millisecond component of the instant exactly."

    Design: Corner/state_machines/revoking_an_already_revoked_consent_is_rejected
    """
    ctx = setup_planned_study(api, participant_count=1)
    consent = grant_consent(
        ctx["participants"][0]["id"],
        ctx["study"]["id"],
        api,
        scopes=["TRANSCRIPT"],
        retention_days=120,
    )
    first_reason = "Participant asked to withdraw"

    first_revoke = validate_success(
        api.revoke_consent_record(
            consent["id"], {"reason": first_reason}, PRIVACY_OFFICER_HEADERS
        )
    )
    assert first_revoke["status"] == "REVOKED", (
        f"Expected the first revoke to reach REVOKED, got {first_revoke['status']}"
    )
    assert first_revoke["revoked_at"] == CLOCK_START, (
        f"Expected revoked_at stamped from the clock at {CLOCK_START}, "
        f"got {first_revoke['revoked_at']}"
    )
    assert first_revoke["revocation_reason"] == first_reason, (
        f"Expected the supplied reason to be stored, "
        f"got {first_revoke['revocation_reason']}"
    )
    assert first_revoke["retention_until"] == "2026-11-29T00:00:00.000Z", (
        f"Expected 120 requested days inside the TRANSCRIPT cap of 365 to land on "
        f"2026-11-29T00:00:00.000Z, got {first_revoke['retention_until']}"
    )

    second_revoke = api.revoke_consent_record(
        consent["id"],
        {"reason": "Duplicate request from the same participant"},
        PRIVACY_OFFICER_HEADERS,
    )
    validate_error(second_revoke, ApiErrorId.INVALID_STATE.value)

    after = read_consent(consent["id"], api)
    assert after["status"] == "REVOKED", (
        f"Expected the record to stay REVOKED, got {after['status']}"
    )
    assert after["revocation_reason"] == first_reason, (
        f"Expected the refused call to overwrite nothing, "
        f"got revocation_reason {after['revocation_reason']}"
    )
    assert after["retention_until"] == "2026-11-29T00:00:00.000Z", (
        f"Expected retention_until unchanged by either revoke, "
        f"got {after['retention_until']}"
    )


def test_scheduling_the_last_session_bubbles_the_study_to_quota_met(api):
    """A held slot counts toward the quota before any session has been completed.

    PRD 3.5: "On success the two instants and the `moderator_user_id` are stored,
    the recruitment keeps the `guide_version_pinned` it received at invitation, and
    the study's `recruitment_status` is recomputed — which may take it `RECRUITING
    → QUOTA_MET`."

    PRD 3.5: "The study's `completed_count` is recomputed as the number of its
    recruitments standing in `COMPLETED`, and its `recruitment_status` re-derived:
    once the number of the study's recruitments sitting in `SCHEDULED` or
    `COMPLETED` reaches `target_participant_count`, the study moves `RECRUITING →
    QUOTA_MET` and further invitations are refused with `ERR_RECRUITMENT_CLOSED`."

    Design: Corner/state_machines/scheduling_the_last_session_bubbles_the_study_to_quota_met
    """
    ctx = setup_screened_in_recruitments(
        api,
        participant_count=3,
        invite_count=2,
        target_participant_count=2,
        pool_overrides=BIG_POOL,
    )
    study_id = ctx["study"]["id"]
    first, second = ctx["recruitments"][0], ctx["recruitments"][1]
    spare_participant = ctx["participants"][2]

    schedule(first["id"], "2026-08-05T10:00:00Z", "2026-08-05T11:00:00Z", api)
    after_first = read_study(study_id, api)
    assert after_first["recruitment_status"] == "RECRUITING", (
        f"Expected RECRUITING with 1 of 2 slots held, "
        f"got {after_first['recruitment_status']}"
    )
    assert after_first["screened_in_count"] == 2, (
        f"Expected screened_in_count 2 for the two admitted candidates, "
        f"got {after_first['screened_in_count']}"
    )

    schedule(second["id"], "2026-08-05T12:00:00Z", "2026-08-05T13:00:00Z", api)
    after_second = read_study(study_id, api)
    assert after_second["recruitment_status"] == "QUOTA_MET", (
        f"Expected QUOTA_MET once both slots are held, "
        f"got {after_second['recruitment_status']}"
    )
    assert after_second["completed_count"] == 0, (
        f"Expected the quota to be met with completed_count still 0, "
        f"got {after_second['completed_count']}"
    )

    refused = api.create_recruitment(
        study_id,
        {
            "participant_id": spare_participant["id"],
            "screening_answers": screening_answers(),
        },
        RESEARCHER_HEADERS,
    )
    validate_error(refused, ApiErrorId.RECRUITMENT_CLOSED.value)

    rows, meta = validate_paginated(
        api.list_recruitments(
            RESEARCHER_HEADERS, {"participant_id": spare_participant["id"]}
        )
    )
    assert meta["total_count"] == 0, (
        f"Expected no recruitment row for the refused participant, "
        f"got {meta['total_count']}"
    )
    assert rows == [], f"Expected an empty recruitment list, got {len(rows)} rows"

    final_study = read_study(study_id, api)
    assert final_study["invited_count"] == 2, (
        f"Expected invited_count to stay 2, got {final_study['invited_count']}"
    )
    pool = read_pool(ctx["pool"]["id"], api)
    assert pool["incentive_reserved_cents"] == 10000, (
        f"Expected the refused invitation to reserve nothing, leaving 10000 cents "
        f"reserved, got {pool['incentive_reserved_cents']}"
    )


def test_withdrawing_a_scheduled_session_reopens_recruiting(api):
    """The recruitment dimension is a loop: a released slot takes QUOTA_MET back to RECRUITING.

    PRD 3.5: "**A withdrawal** is available from `INVITED`, from `SCREENED_IN` and
    from `SCHEDULED` — three separate transitions into the terminal `WITHDRAWN`
    state, all available to a `Researcher`, `ResearchLead` or `ResearchOpsAdmin`,
    and all behaving identically: the supplied `reason` is stored as
    `closure_reason`, and the recruitment's `incentive_state` moves `RESERVED →
    RELEASED` with `paid_cents` left at 0, returning **exactly** the recruitment's
    stored `reserved_cents` — never a recomputed figure — out of the pool's
    `incentive_reserved_cents` and therefore back into `incentive_available_cents`."

    PRD 3.5: "Withdrawing from `SCREENED_IN` or from `SCHEDULED` additionally
    re-derives the study's `recruitment_status`, and from `SCHEDULED` that can take
    the study `QUOTA_MET → RECRUITING`."

    PRD 3.4: "From that pre-call utilization read a scarcity surcharge percentage:
    below 0.50 the surcharge is zero; from 0.50 up to but not including 0.80 it is
    five percent; at 0.80 or above it is ten percent."

    Design: Corner/state_machines/withdrawing_a_scheduled_session_reopens_recruiting
    """
    ctx = setup_scheduled_sessions(
        api,
        scheduled_start="2026-08-05T10:00:00Z",
        scheduled_end="2026-08-05T11:00:00Z",
        participant_count=3,
        invite_count=2,
        target_participant_count=2,
        pool_overrides=BIG_POOL,
    )
    study_id = ctx["study"]["id"]
    pool_id = ctx["pool"]["id"]
    spare_participant = ctx["participants"][2]
    reason = "Participant took a new role"

    assert read_study(study_id, api)["recruitment_status"] == "QUOTA_MET", (
        "Both slots are held before the withdrawal, so the study starts at QUOTA_MET"
    )

    withdrawn = validate_success(
        api.withdraw_recruitment(
            ctx["recruitments"][1]["id"], {"reason": reason}, RESEARCHER_HEADERS
        )
    )
    assert withdrawn["status"] == "WITHDRAWN", (
        f"Expected the recruitment to reach WITHDRAWN, got {withdrawn['status']}"
    )
    assert withdrawn["incentive_state"] == "RELEASED", (
        f"Expected incentive_state RELEASED, got {withdrawn['incentive_state']}"
    )
    assert withdrawn["paid_cents"] == 0, (
        f"Expected paid_cents left at 0, got {withdrawn['paid_cents']}"
    )
    assert withdrawn["closure_reason"] == reason, (
        f"Expected the supplied reason stored as closure_reason, "
        f"got {withdrawn['closure_reason']}"
    )

    reopened = read_study(study_id, api)
    assert reopened["recruitment_status"] == "RECRUITING", (
        f"Expected QUOTA_MET to revert to RECRUITING once the slot fell through, "
        f"got {reopened['recruitment_status']}"
    )
    assert reopened["invited_count"] == 2, (
        f"Expected invited_count to count the withdrawn row too, "
        f"got {reopened['invited_count']}"
    )
    assert reopened["completed_count"] == 0, (
        f"Expected completed_count 0, got {reopened['completed_count']}"
    )

    pool_after_release = read_pool(pool_id, api)
    assert pool_after_release["incentive_reserved_cents"] == 5000, (
        f"Expected exactly the withdrawn 5000 cents to leave the reservation, "
        f"got {pool_after_release['incentive_reserved_cents']}"
    )
    assert pool_after_release["incentive_available_cents"] == 95000, (
        f"Expected the released cents back in available money, "
        f"got {pool_after_release['incentive_available_cents']}"
    )

    replacement = validate_success(
        api.create_recruitment(
            study_id,
            {
                "participant_id": spare_participant["id"],
                "screening_answers": screening_answers(),
            },
            RESEARCHER_HEADERS,
        ),
        expected_status=201,
    )
    assert replacement["reserved_cents"] == 5000, (
        f"Expected an unsurcharged 5000-cent reservation at a pre-call utilization "
        f"of 0.05, got {replacement['reserved_cents']}"
    )

    pool_final = read_pool(pool_id, api)
    assert pool_final["incentive_reserved_cents"] == 10000, (
        f"Expected the reservation back at 10000 cents, "
        f"got {pool_final['incentive_reserved_cents']}"
    )
    assert pool_final["status"] == "OPEN", (
        f"Expected the pool to stay OPEN, got {pool_final['status']}"
    )


def test_retention_sweep_purges_only_artifacts_past_their_horizon(api):
    """One sweep at one clock instant expires the due consent and leaves the other alone.

    PRD 3.6: "Alternatively the retention sweep carries a `GRANTED` record whose
    `retention_until` is at or before the current clock instant to `GRANTED →
    EXPIRED`; on that path `revoked_at` and `revocation_reason` both stay null."

    PRD 3.6: "Its `purged_at` is set to the clock instant and its `purge_reason` is
    set to `CONSENT_REVOKED` on the revocation path or `RETENTION_EXPIRED` on the
    expiry path."

    PRD 3.6: "For each artifact that just became `PURGED`, every evidence link
    citing it whose `is_admissible` is still true is flipped to false with
    `inadmissible_reason` set to `ARTIFACT_PURGED`."

    PRD 3.6: "It answers with six counters describing what it did:
    `expired_consent_count`, `purged_artifact_count`, `inadmissible_link_count`,
    `retracted_finding_count`, `overdue_follow_up_count` and
    `unlocked_decision_count`."

    Design: Corner/state_machines/retention_sweep_purges_only_artifacts_past_their_horizon
    """
    ctx = setup_fielding_study(api, participant_count=2, target_participant_count=2)
    study_id = ctx["study"]["id"]
    near_participant, far_participant = ctx["participants"][0], ctx["participants"][1]

    near_consent = grant_consent(
        near_participant["id"], study_id, api, scopes=["PII_QUOTE"], retention_days=20
    )
    far_consent = grant_consent(
        far_participant["id"], study_id, api, scopes=["RECORDING"], retention_days=180
    )
    assert near_consent["retention_until"] == "2026-08-21T00:00:00.000Z", (
        f"Expected 20 requested days inside the PII_QUOTE cap of 90 to land on "
        f"2026-08-21T00:00:00.000Z, got {near_consent['retention_until']}"
    )
    assert far_consent["retention_until"] == "2027-01-28T00:00:00.000Z", (
        f"Expected 180 requested days at exactly the RECORDING cap to land on "
        f"2027-01-28T00:00:00.000Z, got {far_consent['retention_until']}"
    )

    near_recruitment = invite(study_id, near_participant["id"], api)
    screen(near_recruitment["id"], api)
    schedule(
        near_recruitment["id"], "2026-08-05T10:00:00Z", "2026-08-05T11:00:00Z", api
    )
    complete_session(near_recruitment["id"], api)

    far_recruitment = invite(study_id, far_participant["id"], api)
    screen(far_recruitment["id"], api)
    schedule(far_recruitment["id"], "2026-08-05T12:00:00Z", "2026-08-05T13:00:00Z", api)
    complete_session(far_recruitment["id"], api)

    near_artifact = register_artifact(
        near_recruitment["id"], api, artifact_type="PII_NOTE", contains_pii=True
    )
    far_artifact = register_artifact(
        far_recruitment["id"], api, artifact_type="RECORDING", contains_pii=True
    )
    assert near_artifact["retention_until"] == "2026-08-21T00:00:00.000Z", (
        f"Expected the PII_NOTE to inherit its consent horizon verbatim, "
        f"got {near_artifact['retention_until']}"
    )
    assert far_artifact["retention_until"] == "2027-01-28T00:00:00.000Z", (
        f"Expected the RECORDING to inherit its consent horizon verbatim, "
        f"got {far_artifact['retention_until']}"
    )

    theme = create_theme(api)
    finding = create_finding(study_id, theme["id"], api)
    near_link = link_evidence(
        finding["id"], near_artifact["id"], api, weight_class="DIRECT_QUOTE"
    )
    far_link = link_evidence(
        finding["id"], far_artifact["id"], api, weight_class="DIRECT_QUOTE"
    )

    before = read_finding(finding["id"], api)
    assert before["evidence_strength"] == pytest.approx(0.50, abs=0.01), (
        f"Expected two 1.00 contributions over the provisional divisor of 4.00 to "
        f"give 0.50, got {before['evidence_strength']}"
    )
    assert before["admissible_link_count"] == 2, (
        f"Expected both links admissible before the sweep, "
        f"got {before['admissible_link_count']}"
    )
    assert before["distinct_participant_count"] == 2, (
        f"Expected two distinct participants before the sweep, "
        f"got {before['distinct_participant_count']}"
    )

    set_clock("2026-09-01T00:00:00Z", api)
    sweep = validate_success(api.run_retention_sweep(PRIVACY_OFFICER_HEADERS))
    assert_retention_sweep(sweep)
    assert sweep["expired_consent_count"] == 1, (
        f"Expected only the due consent to expire, "
        f"got expired_consent_count {sweep['expired_consent_count']}"
    )
    assert sweep["purged_artifact_count"] == 1, (
        f"Expected only the artifact past its horizon to purge, "
        f"got purged_artifact_count {sweep['purged_artifact_count']}"
    )
    assert sweep["inadmissible_link_count"] == 1, (
        f"Expected the one link citing the purged artifact to flip, "
        f"got inadmissible_link_count {sweep['inadmissible_link_count']}"
    )
    assert sweep["retracted_finding_count"] == 0, (
        f"Expected a DRAFT finding never to retract, "
        f"got retracted_finding_count {sweep['retracted_finding_count']}"
    )
    assert sweep["overdue_follow_up_count"] == 0, (
        f"Expected no follow-ups to exist, "
        f"got overdue_follow_up_count {sweep['overdue_follow_up_count']}"
    )
    assert sweep["unlocked_decision_count"] == 0, (
        f"Expected no decision to unlock, "
        f"got unlocked_decision_count {sweep['unlocked_decision_count']}"
    )

    expired = read_consent(near_consent["id"], api)
    assert expired["status"] == "EXPIRED", (
        f"Expected the due consent to reach EXPIRED, got {expired['status']}"
    )
    assert expired["revoked_at"] is None, (
        f"Expected revoked_at to stay null on the expiry path, "
        f"got {expired['revoked_at']}"
    )
    assert expired["revocation_reason"] is None, (
        f"Expected revocation_reason to stay null on the expiry path, "
        f"got {expired['revocation_reason']}"
    )
    still_granted = read_consent(far_consent["id"], api)
    assert still_granted["status"] == "GRANTED", (
        f"Expected the consent whose horizon is months away to stay GRANTED, "
        f"got {still_granted['status']}"
    )

    purged = read_artifact(near_artifact["id"], api)
    assert purged["lifecycle_state"] == "PURGED", (
        f"Expected the covered artifact to reach PURGED, "
        f"got {purged['lifecycle_state']}"
    )
    assert purged["purge_reason"] == "RETENTION_EXPIRED", (
        f"Expected the expiry-path purge reason, got {purged['purge_reason']}"
    )
    assert purged["purged_at"] == "2026-09-01T00:00:00.000Z", (
        f"Expected purged_at stamped from the swept clock instant, "
        f"got {purged['purged_at']}"
    )
    retained = read_artifact(far_artifact["id"], api)
    assert retained["lifecycle_state"] == "RETAINED", (
        f"Expected the untouched artifact to stay RETAINED, "
        f"got {retained['lifecycle_state']}"
    )
    assert retained["purged_at"] is None, (
        f"Expected purged_at null on the retained artifact, got {retained['purged_at']}"
    )

    links, _ = validate_paginated(
        api.list_finding_evidence_links(finding["id"], RESEARCHER_HEADERS)
    )
    by_id = {link["id"]: link for link in links}
    flipped = by_id[near_link["id"]]
    assert flipped["is_admissible"] is False, (
        f"Expected the link citing the purged artifact to go inadmissible, "
        f"got is_admissible {flipped['is_admissible']}"
    )
    assert flipped["inadmissible_reason"] == "ARTIFACT_PURGED", (
        f"Expected inadmissible_reason ARTIFACT_PURGED, "
        f"got {flipped['inadmissible_reason']}"
    )
    surviving = by_id[far_link["id"]]
    assert surviving["is_admissible"] is True, (
        f"Expected the other link to stay admissible, "
        f"got is_admissible {surviving['is_admissible']}"
    )

    after = read_finding(finding["id"], api)
    assert after["status"] == "DRAFT", (
        f"Expected the finding to stay DRAFT, got {after['status']}"
    )
    assert after["admissible_link_count"] == 1, (
        f"Expected one surviving admissible link, "
        f"got {after['admissible_link_count']}"
    )
    assert after["distinct_participant_count"] == 1, (
        f"Expected the participant reachable only through the purged link to drop "
        f"out, got distinct_participant_count {after['distinct_participant_count']}"
    )
    assert after["evidence_strength"] == pytest.approx(0.25, abs=0.01), (
        f"Expected a single 1.00 contribution over 4.00 to give 0.25, "
        f"got {after['evidence_strength']}"
    )


# ===========================================================================
# Arithmetic that has to land on the exact number
# ===========================================================================
@pytest.mark.parametrize(
    "target_answers,submitted_segment,submitted_locale,submitted_answers,"
    "expected_score,expected_status",
    [
        (["A1", "A2"], "POWER_USER", "en-US", ["A1", "X9"], 0.00, "SCREENED_OUT"),
        (["A1", "A2"], "POWER_USER", "de-DE", ["A1"], 55.00, "SCREENED_OUT"),
        (["A1", "A2"], "POWER_USER", "en-US", ["A1", "A2", "A7"], 90.00, "SCREENED_IN"),
        (
            ["A1", "A2", "A3", "A4"],
            "CASUAL_USER",
            "en-US",
            ["A1", "A2", "A3", "A4"],
            60.00,
            "SCREENED_IN",
        ),
        (["A1", "A2", "A3", "A4"], "CASUAL_USER", "en-US", ["A1"], 35.00, "SCREENED_OUT"),
    ],
    ids=[
        "disqualifying_answer_short_circuits_to_zero",
        "wrong_locale_lands_one_band_under_the_threshold",
        "third_answer_hits_the_forty_point_cap",
        "wrong_segment_with_four_hits_lands_exactly_on_the_threshold",
        "wrong_segment_with_one_hit_lands_at_thirty_five",
    ],
)
def test_screen_score_applies_the_hard_gate_then_partial_credit(
    api,
    target_answers,
    submitted_segment,
    submitted_locale,
    submitted_answers,
    expected_score,
    expected_status,
):
    """The gate short-circuits, the two exact-match terms are all-or-nothing and the hit term caps at 40.

    PRD 3.5: "Evaluation begins with a hard gate that short-circuits everything
    else: if any element of the submitted `answers` array appears in the rubric's
    `disqualifying_answers`, the score is exactly 0.00 and no further term is
    computed."

    PRD 3.5: "A submitted `segment` exactly equal to the rubric's
    `required_segment` earns 40.0 points, and nothing otherwise. A submitted
    `locale` exactly equal to `required_locale` earns 20.0 points, and nothing
    otherwise. Each element of the submitted `answers` array that appears in the
    rubric's `target_answers` counts as one hit; multiply the number of hits by
    15.0 and hold the result at a ceiling of 40.0 points — so one hit earns 15.0,
    two earn 30.0, and three or more all earn the capped 40.0."

    PRD 3.5: "A score of at least 60.00 carries the recruitment `INVITED →
    SCREENED_IN`; anything below — including the 0.00 produced by the
    disqualifying-answer gate — carries it `INVITED → SCREENED_OUT`, which is
    terminal."

    Design: Corner/calculations/screen_score_hard_gate_and_partial_credit
    """
    ctx = setup_fielding_study(
        api,
        participant_count=1,
        pool_overrides=BIG_POOL,
        screening_criteria=screening_criteria(target_answers=list(target_answers)),
    )
    recruitment = invite(
        ctx["study"]["id"],
        ctx["participants"][0]["id"],
        api,
        screening_answers=screening_answers(
            segment=submitted_segment,
            locale=submitted_locale,
            answers=list(submitted_answers),
        ),
    )

    screened = validate_success(
        api.screen_recruitment(recruitment["id"], RESEARCHER_HEADERS)
    )
    assert screened["screen_score"] == pytest.approx(expected_score, abs=0.01), (
        f"Expected screen_score {expected_score:.2f} for segment "
        f"{submitted_segment}, locale {submitted_locale} and answers "
        f"{list(submitted_answers)} against targets {list(target_answers)}, "
        f"got {screened['screen_score']}"
    )
    assert screened["status"] == expected_status, (
        f"Expected {expected_status} at a score of {expected_score:.2f} against the "
        f"inclusive 60.00 threshold, got {screened['status']}"
    )


def test_screening_three_answer_sheets_moves_no_money(api):
    """Three sheets score 0.00, 55.00 and 90.00, and every reservation survives untouched.

    PRD 3.5: "Either way `screen_score` is stored, and admission recomputes the
    study's `screened_in_count`, which counts every recruitment of the study whose
    `status` is `SCREENED_IN`, `SCHEDULED`, `COMPLETED` or `NO_SHOW`."

    PRD 3.5: "On **both** outcomes the money is left alone: `incentive_state` stays
    `RESERVED` and `reserved_cents` is untouched, because a screened-out candidate
    still gave up their time and keeps their reservation until settlement converts
    it into the screen-out stipend of 200 cents."

    Design: Corner/calculations/screen_score_hard_gate_and_partial_credit
    """
    ctx = setup_fielding_study(
        api,
        participant_count=3,
        pool_overrides=BIG_POOL,
        screening_criteria=screening_criteria(target_answers=["A1", "A2"]),
    )
    study_id = ctx["study"]["id"]
    sheets = [
        ({"segment": "POWER_USER", "locale": "en-US", "answers": ["A1", "X9"]}, 0.00),
        ({"segment": "POWER_USER", "locale": "de-DE", "answers": ["A1"]}, 55.00),
        (
            {"segment": "POWER_USER", "locale": "en-US", "answers": ["A1", "A2", "A7"]},
            90.00,
        ),
    ]

    screened_rows = []
    for participant, (sheet, expected_score) in zip(ctx["participants"], sheets):
        recruitment = invite(
            study_id, participant["id"], api, screening_answers=sheet
        )
        row = validate_success(
            api.screen_recruitment(recruitment["id"], RESEARCHER_HEADERS)
        )
        assert row["screen_score"] == pytest.approx(expected_score, abs=0.01), (
            f"Expected screen_score {expected_score:.2f} for answer sheet {sheet}, "
            f"got {row['screen_score']}"
        )
        screened_rows.append(row)

    study = read_study(study_id, api)
    assert study["screened_in_count"] == 1, (
        f"Expected only the 90.00 sheet to be admitted, "
        f"got screened_in_count {study['screened_in_count']}"
    )
    assert study["invited_count"] == 3, (
        f"Expected invited_count 3, got {study['invited_count']}"
    )
    assert study["recruitment_status"] == "RECRUITING", (
        f"Expected RECRUITING with 1 of 3 admitted, "
        f"got {study['recruitment_status']}"
    )

    for row in screened_rows:
        current = read_recruitment(row["id"], api)
        assert current["incentive_state"] == "RESERVED", (
            f"Expected incentive_state RESERVED after screening, "
            f"got {current['incentive_state']} on {current['status']}"
        )
        assert current["reserved_cents"] == 5000, (
            f"Expected reserved_cents untouched at 5000, "
            f"got {current['reserved_cents']} on {current['status']}"
        )


def test_artifact_horizon_inherits_the_clamped_consent_window(api):
    """A RECORDING under a consent that also covers PII_QUOTE dies after 90 days, not 180.

    PRD 3.6: "Take the smallest maximum across every scope the record grants, take
    the smaller of that figure and the requested `retention_days`, and add that
    many whole days to `granted_at` to obtain `retention_until`, preserving the
    millisecond component of the instant exactly."

    PRD 3.6: "A consent record granting `TRANSCRIPT` alone with a requested 300
    days therefore expires 300 days after grant; the same request granting
    `TRANSCRIPT` and `PII_QUOTE` together expires after 90, because the tightest
    scope governs the whole record."

    PRD 3.6: "When one is found, the artifact inherits that record's
    `retention_until` verbatim and opens in `lifecycle_state` `RETAINED` with
    `purged_at` and `purge_reason` null."

    Design: Corner/calculations/artifact_horizon_inherits_the_clamped_consent_window
    """
    ctx = setup_fielding_study(
        api, participant_count=1, target_participant_count=1, pool_overrides=BIG_POOL
    )
    study_id = ctx["study"]["id"]
    participant_id = ctx["participants"][0]["id"]

    recruitment = invite(study_id, participant_id, api)
    screen(recruitment["id"], api)

    clamped_consent = grant_consent(
        participant_id,
        study_id,
        api,
        scopes=["RECORDING", "PII_QUOTE"],
        retention_days=300,
    )
    roomy_consent = grant_consent(
        participant_id, study_id, api, scopes=["TRANSCRIPT"], retention_days=300
    )
    assert clamped_consent["retention_until"] == "2026-10-30T00:00:00.000Z", (
        f"Expected 300 requested days clamped to the PII_QUOTE cap of 90, "
        f"got {clamped_consent['retention_until']}"
    )
    assert roomy_consent["retention_until"] == "2027-05-28T00:00:00.000Z", (
        f"Expected 300 requested days inside the TRANSCRIPT cap of 365 to stand "
        f"unclamped, got {roomy_consent['retention_until']}"
    )

    schedule(recruitment["id"], "2026-08-05T10:00:00Z", "2026-08-05T11:00:00Z", api)
    complete_session(recruitment["id"], api, actual_duration_min=60)

    recording = register_artifact(
        recruitment["id"], api, artifact_type="RECORDING", contains_pii=True
    )
    transcript = register_artifact(
        recruitment["id"], api, artifact_type="TRANSCRIPT", contains_pii=False
    )
    pii_note = register_artifact(
        recruitment["id"], api, artifact_type="PII_NOTE", contains_pii=True
    )

    assert recording["retention_until"] == "2026-10-30T00:00:00.000Z", (
        f"Expected the RECORDING to inherit the clamped 90-day horizon rather than "
        f"its own 180-day cap, got {recording['retention_until']}"
    )
    assert pii_note["retention_until"] == "2026-10-30T00:00:00.000Z", (
        f"Expected the PII_NOTE to inherit the same clamped horizon, "
        f"got {pii_note['retention_until']}"
    )
    assert transcript["retention_until"] == "2027-05-28T00:00:00.000Z", (
        f"Expected the TRANSCRIPT to resolve through the only record granting that "
        f"scope, got {transcript['retention_until']}"
    )

    for artifact in (recording, transcript, pii_note):
        assert artifact["lifecycle_state"] == "RETAINED", (
            f"Expected a fresh artifact to open RETAINED, "
            f"got {artifact['lifecycle_state']} on {artifact['artifact_type']}"
        )
        assert artifact["purged_at"] is None, (
            f"Expected purged_at null on {artifact['artifact_type']}, "
            f"got {artifact['purged_at']}"
        )
        assert artifact["purge_reason"] is None, (
            f"Expected purge_reason null on {artifact['artifact_type']}, "
            f"got {artifact['purge_reason']}"
        )


# ===========================================================================
# The fielding-window boundary
# ===========================================================================
def test_session_on_the_final_fielding_day_is_accepted(api):
    """The window runs to one day past fielding_end, so the last day is bookable to the small hours.

    PRD 3.5: "Second, the session must sit inside the study's fielding window,
    treated as running from `fielding_start` inclusive up to one day past
    `fielding_end` exclusive — so a session may start on the final fielding day and
    run into the small hours, but nothing may begin before `fielding_start` or
    extend beyond that one-day grace boundary; a violation is
    `ERR_SESSION_WINDOW_OUTSIDE_FIELDING`."

    PRD 3.5: "On success the two instants and the `moderator_user_id` are stored,
    the recruitment keeps the `guide_version_pinned` it received at invitation, and
    the study's `recruitment_status` is recomputed — which may take it `RECRUITING →
    QUOTA_MET`."

    Design: Corner/validations/session_on_the_final_fielding_day_is_accepted
    """
    ctx = setup_screened_in_recruitments(api, participant_count=3, pool_overrides=BIG_POOL)
    recruitment_id = ctx["recruitments"][0]["id"]

    booked = validate_success(
        api.schedule_recruitment(
            recruitment_id,
            {
                "scheduled_start": "2026-08-21T23:00:00Z",
                "scheduled_end": "2026-08-21T23:30:00Z",
                "moderator_user_id": "u_res_1",
            },
            RESEARCHER_HEADERS,
        )
    )
    assert booked["status"] == "SCHEDULED", (
        f"Expected a session on the final fielding day to be booked, "
        f"got {booked['status']}"
    )
    assert booked["scheduled_start"] == "2026-08-21T23:00:00.000Z", (
        f"Expected the supplied start instant stored verbatim, "
        f"got {booked['scheduled_start']}"
    )
    assert booked["scheduled_end"] == "2026-08-21T23:30:00.000Z", (
        f"Expected the supplied end instant stored verbatim, "
        f"got {booked['scheduled_end']}"
    )
    assert booked["moderator_user_id"] == "u_res_1", (
        f"Expected the moderator recorded, got {booked['moderator_user_id']}"
    )

    study = read_study(ctx["study"]["id"], api)
    assert study["recruitment_status"] == "RECRUITING", (
        f"Expected RECRUITING with 1 of 3 slots held, "
        f"got {study['recruitment_status']}"
    )


def test_session_outside_the_fielding_window_is_rejected(api):
    """Both boundaries bite: the grace instant itself is out, and so is anything before the start.

    PRD 3.5: "Second, the session must sit inside the study's fielding window,
    treated as running from `fielding_start` inclusive up to one day past
    `fielding_end` exclusive — so a session may start on the final fielding day and
    run into the small hours, but nothing may begin before `fielding_start` or
    extend beyond that one-day grace boundary; a violation is
    `ERR_SESSION_WINDOW_OUTSIDE_FIELDING`."

    Design: Corner/validations/session_outside_the_fielding_window_is_rejected
    """
    ctx = setup_screened_in_recruitments(api, participant_count=3, pool_overrides=BIG_POOL)
    study_version_before = read_study(ctx["study"]["id"], api)["version"]
    past_the_grace_boundary = ctx["recruitments"][0]["id"]
    before_the_start = ctx["recruitments"][1]["id"]

    too_late = api.schedule_recruitment(
        past_the_grace_boundary,
        {
            "scheduled_start": "2026-08-22T00:00:00Z",
            "scheduled_end": "2026-08-22T01:00:00Z",
            "moderator_user_id": "u_res_1",
        },
        RESEARCHER_HEADERS,
    )
    validate_error(too_late, ApiErrorId.SESSION_WINDOW_OUTSIDE_FIELDING.value)

    too_early = api.schedule_recruitment(
        before_the_start,
        {
            "scheduled_start": "2026-08-02T22:00:00Z",
            "scheduled_end": "2026-08-02T23:00:00Z",
            "moderator_user_id": "u_res_1",
        },
        RESEARCHER_HEADERS,
    )
    validate_error(too_early, ApiErrorId.SESSION_WINDOW_OUTSIDE_FIELDING.value)

    for recruitment_id in (past_the_grace_boundary, before_the_start):
        recruitment = read_recruitment(recruitment_id, api)
        assert recruitment["status"] == "SCREENED_IN", (
            f"Expected the candidate to stay SCREENED_IN after a refused booking, "
            f"got {recruitment['status']}"
        )
        assert recruitment["scheduled_start"] is None, (
            f"Expected scheduled_start to stay null, "
            f"got {recruitment['scheduled_start']}"
        )
        assert recruitment["scheduled_end"] is None, (
            f"Expected scheduled_end to stay null, got {recruitment['scheduled_end']}"
        )
        assert recruitment["reschedule_count"] == 0, (
            f"Expected reschedule_count to stay 0, "
            f"got {recruitment['reschedule_count']}"
        )

    study = read_study(ctx["study"]["id"], api)
    assert study["recruitment_status"] == "RECRUITING", (
        f"Expected the study to stay RECRUITING with no slot held, "
        f"got {study['recruitment_status']}"
    )
    assert study["version"] == study_version_before, (
        f"Expected the study version to stand at {study_version_before} after two "
        f"refused bookings, got {study['version']}"
    )
