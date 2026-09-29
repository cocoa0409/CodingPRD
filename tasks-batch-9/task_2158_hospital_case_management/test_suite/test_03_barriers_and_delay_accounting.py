"""Barriers: the cyclic lifecycle, the escalation posture that runs in parallel with
the case status, and the merged avoidable-delay union."""
from test_helpers import (
    CASE_MANAGER,
    SECOND_UR_NURSE,
    UR_NURSE,
    ApiErrorId,
    assert_barrier,
    assert_throughput_report,
    move_barrier,
    open_barrier,
    read_barriers,
    read_episode,
    record_bundle,
    set_logical_clock,
    setup_planning_episode,
    setup_screened_episode,
    validate_error,
    validate_success,
)

LAKESIDE = {
    "name": "Lakeside Choice", "coinsurance_pct": 0.200,
    "snf_auth_required": False, "hh_auth_required": False, "auth_expiry_days": 30,
}
OBSERVATION_EPISODE = {
    "admission_type": "OBSERVATION", "drg_code": "DRG-871", "drg_gmlos_days": 5.0,
    "attending_unit": "2S", "admitted_at": "2026-08-01T00:00:00Z",
}


def test_critical_barrier_escalates_the_posture_without_moving_the_case_status(api):
    """PRD §3.2: "Running in parallel and entirely independently is the
    `barrier_posture` axis, which takes the values `CLEAR`, `ACTIVE` and `ESCALATED` and
    is described in §3.3. Neither axis constrains the other's vocabulary; both constrain
    what operations are legal."
    PRD §3.3: "When the set is non-empty and contains at least one barrier whose
    `severity` is `CRITICAL`, or at least one whose age — the logical clock now less its
    `clock_start_at`, measured in whole hours — has reached 72 hours or more,
    `barrier_posture` is `ESCALATED`; the age comparison is inclusive, so a barrier that
    has been open for exactly 72 hours escalates."
    PRD §3.3: "The `avoidable` flag is derived, not supplied: it is true exactly when
    `delay_reason_code` is one of the six codes beginning "awaiting" — `AWAITING_BED`,
    `AWAITING_AUTH`, `AWAITING_DME`, `AWAITING_TRANSPORT`, `AWAITING_FAMILY`,
    `AWAITING_PHYSICIAN` — and false for the two clinical codes, `CLINICAL_INSTABILITY`
    and `PATIENT_REFUSAL`."

    Design: Difficulty/non_linear_state_machine/episode_parallel_axes_posture_moves_while_case_status_holds
    """
    env = setup_planning_episode(
        payer=dict(LAKESIDE),
        patient={
            "mrn": "MRN-3001", "full_name": "Eve Nakamura", "date_of_birth": "1960-05-30",
            "prior_admissions_180d": 2, "lives_alone": False, "has_pcp": True,
        },
        episode=dict(OBSERVATION_EPISODE),
    )
    episode_id = env["episode"]["id"]
    assert env["episode"]["case_status"] == "PLANNING"
    assert env["episode"]["barrier_posture"] == "CLEAR"

    critical = validate_success(
        api.create_barrier(
            episode_id,
            {"barrier_code": "BEHAVIORAL", "severity": "CRITICAL",
             "delay_reason_code": "PATIENT_REFUSAL"},
            CASE_MANAGER,
        ),
        201,
    )
    assert_barrier(critical)
    assert critical["avoidable"] is False, "PATIENT_REFUSAL is not an avoidable delay code"

    episode = read_episode(episode_id)
    assert episode["barrier_posture"] == "ESCALATED"
    assert episode["case_status"] == "PLANNING", (
        "recording a barrier never touches the case_status axis, got "
        f"{episode['case_status']}"
    )
    assert episode["avoidable_delay_hours"] == 0.0, (
        "a non-avoidable barrier contributes nothing to the delay union"
    )


def test_resolving_the_critical_barrier_returns_the_posture_to_clear(api):
    """PRD §3.3: "Consider the set of that episode's barriers whose `status` is `OPEN` or
    `MITIGATING`; `RESOLVED` and `WAIVED` rows never participate. When that set is empty,
    `barrier_posture` is `CLEAR`."
    PRD §3.2: "Running in parallel and entirely independently is the `barrier_posture`
    axis, which takes the values `CLEAR`, `ACTIVE` and `ESCALATED` and is described in
    §3.3. Neither axis constrains the other's vocabulary; both constrain what operations
    are legal."
    PRD §3.3: "From either `OPEN` or `MITIGATING` it may go to `RESOLVED`, which sets
    `clock_stop_at` to the logical clock instant and closes out `accrued_delay_minutes`,
    the per-barrier running total of all its closed intervals plus its currently open
    interval up to the logical clock."

    Design: Difficulty/non_linear_state_machine/episode_parallel_axes_posture_moves_while_case_status_holds
    """
    env = setup_planning_episode(
        payer=dict(LAKESIDE),
        patient={
            "mrn": "MRN-3002", "full_name": "Eve Nakamura", "date_of_birth": "1960-05-30",
            "prior_admissions_180d": 2, "lives_alone": False, "has_pcp": True,
        },
        episode=dict(OBSERVATION_EPISODE),
    )
    episode_id = env["episode"]["id"]
    critical = open_barrier(
        episode_id, barrier_code="BEHAVIORAL", severity="CRITICAL",
        delay_reason_code="PATIENT_REFUSAL",
    )
    assert read_episode(episode_id)["barrier_posture"] == "ESCALATED"

    resolved = validate_success(
        api.change_barrier_status(critical["id"], {"to_status": "RESOLVED"}, CASE_MANAGER)
    )

    assert resolved["status"] == "RESOLVED"
    assert resolved["clock_stop_at"] == "2026-08-01T00:00:00.000Z"
    episode = read_episode(episode_id)
    assert episode["barrier_posture"] == "CLEAR"
    assert episode["case_status"] == "PLANNING", (
        "the posture axis travelled CLEAR -> ESCALATED -> CLEAR while case_status held"
    )
    assert episode["avoidable_delay_hours"] == 0.0


def test_a_waived_barrier_admits_no_further_transition(api):
    """PRD §3.3: "And from either `OPEN` or `MITIGATING` it may be waived, which sets
    `clock_stop_at` and moves it to the terminal `WAIVED` status."
    PRD §3.3: "Any `to_status` not reachable from the barrier's current status is refused
    with `ERR_INVALID_BARRIER_STATE`: `WAIVED` is terminal and admits no exit, and the
    step from `RESOLVED` directly to `MITIGATING` is not a declared transition."

    Design: Corner/state_machines/barrier_status_change_from_waived_returns_invalid_barrier_state
    """
    env = setup_screened_episode(
        payer={"name": "Lakeside Choice", "coinsurance_pct": 0.200},
        patient={
            "mrn": "MRN-C201", "full_name": "Cal Ito", "date_of_birth": "1949-03-03",
            "prior_admissions_180d": 2, "lives_alone": False, "has_pcp": True,
        },
    )
    barrier = open_barrier(
        env["episode"]["id"], barrier_code="TRANSPORT", severity="MEDIUM",
        delay_reason_code="AWAITING_TRANSPORT",
    )
    waived = move_barrier(barrier["id"], "WAIVED", UR_NURSE)
    assert waived["status"] == "WAIVED"

    response = api.change_barrier_status(barrier["id"], {"to_status": "RESOLVED"}, UR_NURSE)

    validate_error(response, ApiErrorId.ERR_INVALID_BARRIER_STATE, 409)
    after = read_barriers(env["episode"]["id"])[0]
    assert after["status"] == "WAIVED"
    assert after["clock_stop_at"] == "2026-08-01T00:00:00.000Z", (
        "the refused transition must not move clock_stop_at"
    )
    assert read_episode(env["episode"]["id"])["barrier_posture"] == "CLEAR"


def test_reopening_and_reresolving_at_one_instant_leaves_the_union_unchanged(api):
    """PRD §3.3: "From `RESOLVED` it may return to `OPEN` — this is the revision loop, and it
    may repeat without bound — incrementing `reopen_count` by one, setting
    `clock_start_at` to the logical clock instant and `clock_stop_at` back to null."
    PRD §3.3: "An interval whose end is at or before its start contributes nothing and is
    dropped, which is exactly what happens to a barrier reopened and re-resolved at the
    same logical instant."
    PRD §3.3: "Only the barrier's **current** interval is modelled, since `clock_start_at`
    is reset on every reopen; a reopened barrier therefore contributes only its newest
    interval, and a freshly reopened barrier contributes a zero-length interval that
    leaves the union unchanged."

    Design: Corner/state_machines/barrier_reopen_cycle_increments_reopen_count_without_delay_drift
    """
    env = setup_screened_episode(
        payer={"name": "Lakeside Choice", "coinsurance_pct": 0.200},
        patient={
            "mrn": "MRN-C204", "full_name": "Fin Gopal", "date_of_birth": "1948-06-06",
            "prior_admissions_180d": 2, "lives_alone": False, "has_pcp": True,
        },
    )
    episode_id = env["episode"]["id"]
    barrier = open_barrier(
        episode_id, barrier_code="BED_AVAILABILITY", severity="MEDIUM",
        delay_reason_code="AWAITING_BED",
    )
    set_logical_clock("2026-08-03T00:00:00Z")
    move_barrier(barrier["id"], "RESOLVED")

    reopened = validate_success(
        api.change_barrier_status(barrier["id"], {"to_status": "OPEN"}, CASE_MANAGER)
    )
    assert reopened["reopen_count"] == 1
    assert reopened["clock_start_at"] == "2026-08-03T00:00:00.000Z"
    assert reopened["clock_stop_at"] is None

    final = validate_success(
        api.change_barrier_status(barrier["id"], {"to_status": "RESOLVED"}, CASE_MANAGER)
    )
    assert final["status"] == "RESOLVED"
    assert final["reopen_count"] == 1
    assert final["clock_start_at"] == "2026-08-03T00:00:00.000Z"
    assert final["clock_stop_at"] == "2026-08-03T00:00:00.000Z"

    episode = read_episode(episode_id)
    assert episode["avoidable_delay_hours"] == 0.0, (
        "only the newest, zero-length interval survives, got "
        f"{episode['avoidable_delay_hours']}"
    )
    assert episode["barrier_posture"] == "CLEAR"


def test_posture_escalates_the_moment_a_barrier_reaches_seventy_two_hours(api):
    """PRD §3.3: "When the set is non-empty and contains at least one barrier whose
    `severity` is `CRITICAL`, or at least one whose age — the logical clock now less its
    `clock_start_at`, measured in whole hours — has reached 72 hours or more,
    `barrier_posture` is `ESCALATED`; the age comparison is inclusive, so a barrier that
    has been open for exactly 72 hours escalates. Otherwise `barrier_posture` is
    `ACTIVE`."
    PRD §3.8: "Second, `barrier_posture` must not be `ESCALATED`, or the refusal is
    `ERR_ESCALATED_POSTURE` — so a critical or long-aged barrier surfaces as an escalation
    rather than being masked by the generic unresolved-barrier check that follows."

    Design: Corner/state_machines/barrier_posture_escalates_at_exactly_seventy_two_hours
    """
    env = setup_planning_episode(
        payer={"name": "Lakeside Choice", "coinsurance_pct": 0.200, "snf_auth_required": False},
        patient={
            "mrn": "MRN-C209", "full_name": "Kim Lorca", "date_of_birth": "1941-11-11",
            "prior_admissions_180d": 2, "lives_alone": False, "has_pcp": True,
        },
    )
    episode_id = env["episode"]["id"]
    open_barrier(
        episode_id, barrier_code="FAMILY_DECISION", severity="MEDIUM",
        delay_reason_code="AWAITING_FAMILY",
    )

    set_logical_clock("2026-08-03T23:00:00Z")
    assert read_episode(episode_id)["barrier_posture"] == "ACTIVE", (
        "at 71 hours the barrier has not yet aged into escalation"
    )

    set_logical_clock("2026-08-04T00:00:00Z")
    assert read_episode(episode_id)["barrier_posture"] == "ESCALATED", (
        "at exactly 72 hours the inclusive comparison escalates"
    )

    response = api.mark_ready(
        episode_id, {"discharge_disposition": "HOME_SELF_CARE"}, CASE_MANAGER
    )
    validate_error(response, ApiErrorId.ERR_ESCALATED_POSTURE, 409)
    assert read_episode(episode_id)["case_status"] == "PLANNING"


def test_mark_ready_reports_the_unresolved_barrier_before_the_bundle_gap(api):
    """PRD §3.8: "Third, no barrier on the episode may be in `OPEN` or `MITIGATING`
    status at all, failing which the refusal is `ERR_BARRIER_UNRESOLVED` (HTTP 422).
    Fourth, `readmission_bundle_complete` must be true, evaluated against the
    `current_risk_band` **in effect before** this transition's predischarge rescore, or
    the refusal is `ERR_READMISSION_BUNDLE_INCOMPLETE` (HTTP 422)."
    PRD §3.8: "Five preconditions guard the `PLANNING → READY_FOR_DISCHARGE` transition,
    and they are evaluated in this order, which matters because several of them can be
    false at once."

    Design: Corner/validations/mark_ready_with_open_barrier_returns_barrier_unresolved
    """
    env = setup_screened_episode(
        payer={"name": "Lakeside Choice", "coinsurance_pct": 0.200, "snf_auth_required": False},
        patient={
            "mrn": "MRN-D008", "full_name": "Wil Xu", "date_of_birth": "1953-12-12",
            "prior_admissions_180d": 2, "lives_alone": False, "has_pcp": True,
        },
    )
    episode_id = env["episode"]["id"]
    record_bundle(episode_id, pcp_followup_booked=False)
    barrier = open_barrier(
        episode_id, barrier_code="TRANSPORT", severity="MEDIUM",
        delay_reason_code="AWAITING_TRANSPORT",
    )

    response = api.mark_ready(
        episode_id, {"discharge_disposition": "HOME_SELF_CARE"}, CASE_MANAGER
    )

    validate_error(response, ApiErrorId.ERR_BARRIER_UNRESOLVED, 422)
    assert response.json()["data"]["error_id"] != "ERR_READMISSION_BUNDLE_INCOMPLETE"
    episode = read_episode(episode_id)
    assert episode["barrier_posture"] == "ACTIVE"
    assert episode["case_status"] == "PLANNING"
    assert episode["readmission_bundle_complete"] is False
    assert read_barriers(episode_id, params={"status": "OPEN"})[0]["id"] == barrier["id"]


def test_avoidable_delay_union_merges_overlaps_and_drops_waived_and_clinical_rows(api):
    """PRD §3.3: "Each barrier on the episode contributes a candidate half-open interval,
    except that a barrier whose `delay_reason_code` is `CLINICAL_INSTABILITY` or
    `PATIENT_REFUSAL` is skipped — non-avoidable delay never counts — and a barrier whose
    `status` is `WAIVED` is skipped entirely, its whole history erased."
    PRD §3.3: "Walking the sorted list, two intervals merge into one whenever the next
    interval's start is at or before the current interval's end; intervals that merely
    touch, with a gap of zero, do merge. The lengths of the merged intervals are summed in
    whole minutes, and only at that very end is the total divided by 60 and rounded half up
    to one decimal place to yield `avoidable_delay_hours`."
    PRD §3.9: "**Step four** computes `adjusted_los_hours` as `los_hours` less
    `avoidable_delay_hours`, rounded half up to one decimal place and floored at 0.0, so an
    episode whose avoidable delay exceeds its stay reports zero rather than a negative
    figure. **Step five** computes `expected_los_hours` as `drg_gmlos_days` multiplied by 24
    to convert days into hours and then multiplied by an acuity multiplier keyed on the band
    from step one — 0.90 for `LOW`, 1.00 for `MODERATE`, 1.15 for `HIGH`, and 1.30 for
    `VERY_HIGH` — with the product rounded half up to one decimal place. **Step six**
    computes `observed_expected_ratio` as `adjusted_los_hours` divided by
    `expected_los_hours`, rounded half up to three decimal places."
    PRD §3.9: "A ratio of 0.900 or below is `EXEMPLARY`."

    Design: Corner/calculations/avoidable_delay_union_merges_overlap_and_adjacency_and_drops_waived
    """
    env = setup_screened_episode(
        payer={"name": "Lakeside Choice", "coinsurance_pct": 0.200, "snf_auth_required": False},
        patient={
            "mrn": "MRN-C301", "full_name": "Lou Meyers", "date_of_birth": "1950-01-15",
            "prior_admissions_180d": 2, "lives_alone": False, "has_pcp": True,
        },
    )
    episode_id = env["episode"]["id"]

    set_logical_clock("2026-08-02T00:00:00Z")
    bar_a = open_barrier(episode_id, barrier_code="BED_AVAILABILITY", severity="MEDIUM",
                         delay_reason_code="AWAITING_BED")
    set_logical_clock("2026-08-03T00:00:00Z")
    bar_b = open_barrier(episode_id, barrier_code="INSURANCE_AUTH", severity="MEDIUM",
                         delay_reason_code="AWAITING_AUTH")
    set_logical_clock("2026-08-04T00:00:00Z")
    move_barrier(bar_a["id"], "RESOLVED")
    set_logical_clock("2026-08-05T00:00:00Z")
    move_barrier(bar_b["id"], "RESOLVED")
    bar_c = open_barrier(episode_id, barrier_code="DME_DELIVERY", severity="LOW",
                         delay_reason_code="AWAITING_DME")
    set_logical_clock("2026-08-05T06:00:00Z")
    move_barrier(bar_c["id"], "RESOLVED")
    set_logical_clock("2026-08-06T00:00:00Z")
    bar_d = open_barrier(episode_id, barrier_code="BEHAVIORAL", severity="MEDIUM",
                         delay_reason_code="CLINICAL_INSTABILITY")
    bar_e = open_barrier(episode_id, barrier_code="FAMILY_DECISION", severity="MEDIUM",
                         delay_reason_code="AWAITING_FAMILY")
    set_logical_clock("2026-08-07T00:00:00Z")
    move_barrier(bar_e["id"], "WAIVED", UR_NURSE)
    set_logical_clock("2026-08-08T00:00:00Z")
    move_barrier(bar_d["id"], "RESOLVED")

    report = validate_success(api.get_throughput(episode_id, SECOND_UR_NURSE))

    assert_throughput_report(report)
    assert report["avoidable_delay_hours"] == 78.0, (
        "[08-02,08-04) and [08-03,08-05) merge into 72 hours and the adjacent "
        f"[08-05,08-05T06) adds 6 more, got {report['avoidable_delay_hours']}"
    )
    assert report["los_hours"] == 168.0
    assert report["adjusted_los_hours"] == 90.0
    assert report["expected_los_hours"] == 108.0
    assert report["observed_expected_ratio"] == 0.833
    assert report["throughput_grade"] == "EXEMPLARY"
    assert report["current_risk_score"] == 45
    assert report["current_risk_band"] == "MODERATE"
    assert report["barriers_ever_opened_count"] == 5

    rows = {row["id"]: row for row in read_barriers(episode_id)}
    assert rows[bar_d["id"]]["avoidable"] is False
    assert rows[bar_e["id"]]["status"] == "WAIVED"
