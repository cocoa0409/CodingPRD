"""Credited-minute arithmetic and the therapy-week verdict cycle."""

from test_helpers import (
    api_client,
    assert_week_counters,
    deliver_session,
    evaluate_week,
    open_therapy_week,
    read_admission,
    read_therapy_session,
    read_therapy_week,
    schedule_session,
    set_clock,
    setup_admitted_cohort,
    setup_facility_with_staff,
    setup_stay_with_week,
    sign_plan_of_care,
    validate_success,
    void_session,
)

PLAN_DAILY_PT = {"three_hour_rule_mode": "DAILY_3HR", "disciplines": ["PT"]}


def test_group_sessions_are_floored_per_session_before_being_summed():
    """Three 50-minute group sessions of three credit 16 minutes each, not 50.

    PRD §3.6: "Three 50-minute `GROUP` sessions with a `group_size` of 3
    therefore credit 16 minutes each for a total of 48 credited minutes — not
    the 50 that would result from adding the raw minutes first and dividing
    once."

    Design: Difficulty/combinatorial_formula/credited_minutes_group_floor_per_session_then_sum
    """
    env = setup_facility_with_staff(staff=("nurse", "physician", "pt"))
    stay = setup_stay_with_week(env, plan_overrides=PLAN_DAILY_PT)
    admission_id = stay["admission"]["id"]

    sessions = [
        schedule_session(env, admission_id, start_at, end_at,
                         modality="GROUP", group_size=3)
        for start_at, end_at in (
            ("2026-08-05T09:00:00Z", "2026-08-05T09:50:00Z"),
            ("2026-08-05T10:00:00Z", "2026-08-05T10:50:00Z"),
            ("2026-08-05T11:00:00Z", "2026-08-05T11:50:00Z"),
        )
    ]

    set_clock("2026-08-05T18:00:00Z")
    for session in sessions:
        deliver_session(env, session["id"])

    for session in sessions:
        delivered = read_therapy_session(session["id"])
        assert delivered["status"] == "DELIVERED"
        assert delivered["raw_minutes"] == 50
        assert delivered["credited_minutes"] == 16

    week = read_therapy_week(stay["week"]["id"])
    assert week["delivered_credited_minutes"] == 48


def test_group_session_day_never_reaches_a_qualifying_three_hour_total():
    """48 credited minutes on one date leave the day short of 180 minutes.

    PRD §3.6: "It first refreshes the week's counters from the window's seven
    inclusive dates: for each date, the credited minutes of that week's
    `DELIVERED` sessions bearing that `session_date` are totalled;
    `delivered_credited_minutes` is the sum of those seven daily totals, and
    `qualifying_days_count` is the number of those dates whose daily total is
    at least 180 credited minutes — three hours of therapy in one day."

    Design: Difficulty/combinatorial_formula/credited_minutes_group_floor_per_session_then_sum
    """
    env = setup_facility_with_staff(staff=("nurse", "physician", "pt"))
    stay = setup_stay_with_week(env, plan_overrides=PLAN_DAILY_PT)
    admission_id = stay["admission"]["id"]

    sessions = [
        schedule_session(env, admission_id, start_at, end_at,
                         modality="GROUP", group_size=3)
        for start_at, end_at in (
            ("2026-08-05T09:00:00Z", "2026-08-05T09:50:00Z"),
            ("2026-08-05T10:00:00Z", "2026-08-05T10:50:00Z"),
            ("2026-08-05T11:00:00Z", "2026-08-05T11:50:00Z"),
        )
    ]

    set_clock("2026-08-05T18:00:00Z")
    for session in sessions:
        deliver_session(env, session["id"])

    for session in sessions:
        assert read_therapy_session(session["id"])["session_date"] == "2026-08-05"

    week = read_therapy_week(stay["week"]["id"])
    assert_week_counters(week, delivered_credited_minutes=48,
                         qualifying_days_count=0)
    assert read_admission(admission_id)["total_credited_minutes"] == 48


def test_week_without_delivered_sessions_evaluates_to_not_met():
    """An empty week evaluates to NOT_MET at zero minutes rather than erroring.

    PRD §3.6: "A week with no delivered sessions at all yields
    `delivered_credited_minutes` of 0 and `qualifying_days_count` of 0 and is
    `NOT_MET` under either mode; no division is performed, so an empty week is
    not an error."

    Design: Difficulty/boundary_precision_check/therapy_week_evaluate_with_zero_delivered_sessions
    """
    env = setup_facility_with_staff(staff=("nurse", "physician", "pt"))
    stay = setup_stay_with_week(env, plan_overrides=PLAN_DAILY_PT)
    schedule_session(env, stay["admission"]["id"],
                     "2026-08-05T09:00:00Z", "2026-08-05T12:00:00Z")

    response = api_client.evaluate_therapy_week(stay["week"]["id"],
                                                env["pt_headers"])

    week = validate_success(response, expected_status=200)
    assert_week_counters(week, delivered_credited_minutes=0,
                         qualifying_days_count=0, status="NOT_MET")


def test_scheduled_minutes_are_carried_but_never_credited_to_the_ledger():
    """A scheduled session holds its credited minutes without contributing them.

    PRD §3.6: "`therapy_weeks_satisfied` — false by default — is true only when
    the admission has at least one therapy week and every one of them is either
    `MET` or `EXCEPTION_GRANTED`."

    Design: Difficulty/boundary_precision_check/therapy_week_evaluate_with_zero_delivered_sessions
    """
    env = setup_facility_with_staff(staff=("nurse", "physician", "pt"))
    stay = setup_stay_with_week(env, plan_overrides=PLAN_DAILY_PT)
    admission_id = stay["admission"]["id"]
    session = schedule_session(env, admission_id,
                               "2026-08-05T09:00:00Z", "2026-08-05T12:00:00Z")

    validate_success(
        api_client.evaluate_therapy_week(stay["week"]["id"], env["pt_headers"])
    )

    untouched = read_therapy_session(session["id"])
    assert untouched["status"] == "SCHEDULED"
    assert untouched["credited_minutes"] == 180

    admission = read_admission(admission_id)
    assert admission["total_credited_minutes"] == 0
    assert admission["therapy_weeks_satisfied"] is False


def test_daily_three_hour_mode_fails_a_week_of_three_long_therapy_days():
    """900 minutes spread over three days is NOT_MET under DAILY_3HR.

    PRD §3.6: "Under `DAILY_3HR`, the week is `MET` when
    `qualifying_days_count` is at least 5 — five of the seven dates each
    reaching 180 credited minutes — and `NOT_MET` otherwise."

    Design: Difficulty/dual_variant_calc/three_hour_rule_daily_vs_weekly_variant_divergence
    """
    env = setup_facility_with_staff(staff=("nurse", "physician", "pt", "pt2"))
    stays = setup_admitted_cohort(env, [{"mrn": "MRN-A"}, {"mrn": "MRN-B"}])
    admission_a = stays[0]["admission"]["id"]
    admission_b = stays[1]["admission"]["id"]
    sign_plan_of_care(env, admission_a, three_hour_rule_mode="DAILY_3HR",
                      disciplines=["PT"])
    sign_plan_of_care(env, admission_b, three_hour_rule_mode="WEEKLY_15HR",
                      disciplines=["PT"])
    week_a = open_therapy_week(env, admission_a, week_start_date="2026-08-04",
                               lead_key="pt")
    week_b = open_therapy_week(env, admission_b, week_start_date="2026-08-04",
                               lead_key="pt2")
    scheduled = []
    for day in ("2026-08-04", "2026-08-05", "2026-08-06"):
        scheduled.append(("pt", schedule_session(
            env, admission_a, f"{day}T09:00:00Z", f"{day}T14:00:00Z",
            clinician_key="pt")))
        scheduled.append(("pt2", schedule_session(
            env, admission_b, f"{day}T09:00:00Z", f"{day}T14:00:00Z",
            clinician_key="pt2")))
    set_clock("2026-08-06T18:00:00Z")
    for clinician_key, session in scheduled:
        deliver_session(env, session["id"], lead_key=clinician_key)

    evaluated_a = evaluate_week(env, week_a["id"], lead_key="pt")
    evaluate_week(env, week_b["id"], lead_key="pt2")

    assert evaluated_a["evaluation_mode"] == "DAILY_3HR"
    assert_week_counters(evaluated_a, delivered_credited_minutes=900,
                         qualifying_days_count=3, status="NOT_MET")
    admission = read_admission(admission_a)
    assert admission["total_credited_minutes"] == 900
    assert admission["therapy_weeks_satisfied"] is False


def test_weekly_fifteen_hour_mode_meets_on_the_same_volume_of_therapy():
    """The same 900 minutes over three days is MET under WEEKLY_15HR.

    PRD §3.6: "Under `WEEKLY_15HR`, the week is `MET` when
    `delivered_credited_minutes` is at least 900 — fifteen hours anywhere
    inside the window — and `NOT_MET` otherwise."

    Design: Difficulty/dual_variant_calc/three_hour_rule_daily_vs_weekly_variant_divergence
    """
    env = setup_facility_with_staff(staff=("nurse", "physician", "pt", "pt2"))
    stays = setup_admitted_cohort(env, [{"mrn": "MRN-A"}, {"mrn": "MRN-B"}])
    admission_a = stays[0]["admission"]["id"]
    admission_b = stays[1]["admission"]["id"]
    sign_plan_of_care(env, admission_a, three_hour_rule_mode="DAILY_3HR",
                      disciplines=["PT"])
    sign_plan_of_care(env, admission_b, three_hour_rule_mode="WEEKLY_15HR",
                      disciplines=["PT"])
    week_a = open_therapy_week(env, admission_a, week_start_date="2026-08-04",
                               lead_key="pt")
    week_b = open_therapy_week(env, admission_b, week_start_date="2026-08-04",
                               lead_key="pt2")
    scheduled = []
    for day in ("2026-08-04", "2026-08-05", "2026-08-06"):
        scheduled.append(("pt", schedule_session(
            env, admission_a, f"{day}T09:00:00Z", f"{day}T14:00:00Z",
            clinician_key="pt")))
        scheduled.append(("pt2", schedule_session(
            env, admission_b, f"{day}T09:00:00Z", f"{day}T14:00:00Z",
            clinician_key="pt2")))
    set_clock("2026-08-06T18:00:00Z")
    for clinician_key, session in scheduled:
        deliver_session(env, session["id"], lead_key=clinician_key)

    evaluate_week(env, week_a["id"], lead_key="pt")
    evaluated_b = evaluate_week(env, week_b["id"], lead_key="pt2")

    assert evaluated_b["evaluation_mode"] == "WEEKLY_15HR"
    assert_week_counters(evaluated_b, delivered_credited_minutes=900,
                         qualifying_days_count=3, status="MET")
    admission = read_admission(admission_b)
    assert admission["total_credited_minutes"] == 900
    assert admission["therapy_weeks_satisfied"] is True


def test_met_week_reverts_to_not_met_when_a_delivered_session_is_voided():
    """Voiding the fifth qualifying day carries the week back out of MET.

    PRD §3.6: "`MET` and `NOT_MET` are thus a genuine cycle driven by delivery
    and voiding, and neither is terminal."

    Design: Difficulty/non_linear_state_machine/therapy_week_met_reverts_to_not_met_after_void
    """
    env = setup_facility_with_staff(staff=("nurse", "physician", "pt"))
    stay = setup_stay_with_week(env, plan_overrides=PLAN_DAILY_PT)
    admission_id = stay["admission"]["id"]
    sessions = [
        schedule_session(env, admission_id, f"{day}T09:00:00Z", f"{day}T12:00:00Z")
        for day in ("2026-08-04", "2026-08-05", "2026-08-06",
                    "2026-08-07", "2026-08-08")
    ]
    set_clock("2026-08-08T18:00:00Z")
    for session in sessions:
        deliver_session(env, session["id"])
    assert evaluate_week(env, stay["week"]["id"])["status"] == "MET"

    void_session(env, sessions[-1]["id"],
                 void_reason="Documented in error — patient refused")

    assert_week_counters(read_therapy_week(stay["week"]["id"]),
                         delivered_credited_minutes=720,
                         qualifying_days_count=4, status="NOT_MET")


def test_voided_session_keeps_its_minutes_while_the_admission_ledger_drops():
    """The voided row retains credited_minutes; the stay's totals do not.

    PRD §3.6: "A verdict of `NOT_MET` forces `therapy_weeks_satisfied` to false
    and, when the admission is already `DISCHARGED`, forces its
    `compliance_class` to `NON_QUALIFYING`, which in turn drags the facility's
    provisional percentage and `posture` with it."

    Design: Difficulty/non_linear_state_machine/therapy_week_met_reverts_to_not_met_after_void
    """
    env = setup_facility_with_staff(staff=("nurse", "physician", "pt"))
    stay = setup_stay_with_week(env, plan_overrides=PLAN_DAILY_PT)
    admission_id = stay["admission"]["id"]
    sessions = [
        schedule_session(env, admission_id, f"{day}T09:00:00Z", f"{day}T12:00:00Z")
        for day in ("2026-08-04", "2026-08-05", "2026-08-06",
                    "2026-08-07", "2026-08-08")
    ]
    set_clock("2026-08-08T18:00:00Z")
    for session in sessions:
        deliver_session(env, session["id"])
    evaluate_week(env, stay["week"]["id"])

    voided = void_session(env, sessions[-1]["id"],
                          void_reason="Documented in error — patient refused")

    assert voided["status"] == "VOIDED"
    assert voided["credited_minutes"] == 180
    admission = read_admission(admission_id)
    assert admission["total_credited_minutes"] == 720
    assert admission["therapy_weeks_satisfied"] is False


def test_voiding_a_delivered_session_subtracts_exactly_its_credited_minutes():
    """Voiding one of two delivered sessions removes only its own minutes.

    PRD §3.6: "Voiding a `DELIVERED` session moves it to `VOIDED`, subtracts
    exactly that session's `credited_minutes` from its week's
    `delivered_credited_minutes`, refreshes `qualifying_days_count`,
    re-evaluates the week when it is `MET` or `NOT_MET` — which can carry a
    week from `MET` back to `NOT_MET` — and recomputes the admission's
    `total_credited_minutes`."

    Design: Difficulty/compensating_invariant/void_after_deliver_restores_week_and_admission_minute_ledgers
    """
    env = setup_facility_with_staff(staff=("nurse", "physician", "pt"))
    stay = setup_stay_with_week(env, plan_overrides=PLAN_DAILY_PT)
    admission_id = stay["admission"]["id"]
    kept = schedule_session(env, admission_id,
                            "2026-08-04T13:00:00Z", "2026-08-04T16:00:00Z")
    voidable = schedule_session(env, admission_id,
                                "2026-08-05T09:00:00Z", "2026-08-05T10:00:00Z")
    set_clock("2026-08-05T17:00:00Z")
    deliver_session(env, kept["id"])
    deliver_session(env, voidable["id"])

    voided = void_session(
        env, voidable["id"],
        void_reason="Documented in error; minutes belong to another patient",
    )

    assert voided["status"] == "VOIDED"
    assert voided["credited_minutes"] == 60
    week = read_therapy_week(stay["week"]["id"])
    assert week["delivered_credited_minutes"] == 180
    assert read_admission(admission_id)["total_credited_minutes"] == 180


def test_void_leaves_the_surviving_qualifying_day_and_an_open_week():
    """The untouched session keeps its minutes and the week stays OPEN.

    PRD §3.6: "The session's `credited_minutes` are added to its week's
    `delivered_credited_minutes` and the week's `qualifying_days_count` is
    refreshed; if the week is already `MET` or `NOT_MET` it is re-evaluated on
    the spot, which can carry a week from `NOT_MET` to `MET`."

    Design: Difficulty/compensating_invariant/void_after_deliver_restores_week_and_admission_minute_ledgers
    """
    env = setup_facility_with_staff(staff=("nurse", "physician", "pt"))
    stay = setup_stay_with_week(env, plan_overrides=PLAN_DAILY_PT)
    admission_id = stay["admission"]["id"]
    kept = schedule_session(env, admission_id,
                            "2026-08-04T13:00:00Z", "2026-08-04T16:00:00Z")
    voidable = schedule_session(env, admission_id,
                                "2026-08-05T09:00:00Z", "2026-08-05T10:00:00Z")
    set_clock("2026-08-05T17:00:00Z")
    deliver_session(env, kept["id"])
    deliver_session(env, voidable["id"])

    void_session(
        env, voidable["id"],
        void_reason="Documented in error; minutes belong to another patient",
    )

    survivor = read_therapy_session(kept["id"])
    assert survivor["status"] == "DELIVERED"
    assert survivor["credited_minutes"] == 180
    assert_week_counters(read_therapy_week(stay["week"]["id"]),
                         delivered_credited_minutes=180,
                         qualifying_days_count=1, status="OPEN")
