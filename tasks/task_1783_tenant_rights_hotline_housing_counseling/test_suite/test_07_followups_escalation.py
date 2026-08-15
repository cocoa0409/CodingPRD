"""Follow-up cadence, escalation, de-escalation compensation, and case closure
gates (PRD §3.7)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_instant_equal,
    complete_follow_up,
    escalate_case,
    get_case,
    get_case_follow_ups,
    get_case_notes,
    move_case_in_progress,
    open_case,
    run_time_sweep,
    schedule_follow_up,
    set_clock,
    setup_hotline,
    setup_verified_case,
    start_active_session,
    transition_case_ok,
    validate_error,
    validate_success,
)

# Verified base score 65 (ELEVATED): eviction d=9 -> +30, habitability h=29 -> +25,
# deposit over cap -> +10.
BASE_65_FACTS = {
    "eviction_notice_date": "2026-08-10",
    "habitability_reported_at": "2026-07-03T00:00:00Z",
    "deposit_amount_cents": 200000,
    "monthly_rent_cents": 150000,
}


def _completed_cycle_to_in_progress(api, bundle):
    """Schedule FU1 for 08-02, sweep it to DUE at 08-02, complete it."""
    fu1 = schedule_follow_up(bundle, bundle["case"]["id"], "2026-08-02T00:00:00Z")
    set_clock("2026-08-02T00:00:00Z")
    sweep = run_time_sweep()
    completed = complete_follow_up(bundle, fu1["id"])
    return fu1, sweep, completed


def test_follow_up_lifecycle_bubble_up(api):
    """PRD §3.7: "A new follow-up starts `SCHEDULED`, pins
    `required_count_at_schedule` to the case's then-current
    `required_follow_up_count`, and — when the case was `IN_PROGRESS` —
    auto-transitions the case to `PENDING_FOLLOW_UP`."
    PRD §3.7: "The sweep advances follow-ups through their deadlines: a `SCHEDULED`
    follow-up becomes `DUE` when the logical time is on or after `scheduled_for`
    (the boundary is inclusive), and a `DUE` follow-up becomes `MISSED` when the
    logical time is strictly more than 48 hours past `scheduled_for` — exactly at
    the 48-hour edge it stays `DUE`."
    PRD §3.7: "Two cascade links follow: a system-generated `CaseNote` —
    `system_generated` true, `counselor_id` null — is appended to the parent case,
    bumping the case's `version`; and if the case was `PENDING_FOLLOW_UP` and no
    other non-terminal follow-ups remain, it bubbles back to `IN_PROGRESS`."

    Design: Difficulty/non_linear_state_machine/case_escalation_cycle
    """
    bundle = setup_verified_case()  # VERIFIED CRITICAL, IN_PROGRESS
    fu1 = schedule_follow_up(bundle, bundle["case"]["id"], "2026-08-02T00:00:00Z")
    assert fu1["status"] == "SCHEDULED"
    waiting = get_case(bundle, bundle["case"]["id"])
    assert waiting["status"] == "PENDING_FOLLOW_UP"

    set_clock("2026-08-02T00:00:00Z")
    sweep = run_time_sweep()
    assert sweep["follow_ups_due"] == 1, "inclusive DUE boundary at scheduled_for"

    completed = complete_follow_up(bundle, fu1["id"])
    assert completed["status"] == "COMPLETED"
    assert completed.get("completed_at") is not None

    case = get_case(bundle, bundle["case"]["id"])
    assert case["status"] == "IN_PROGRESS", "bubble-up after the last open item"
    notes = get_case_notes(bundle, bundle["case"]["id"])
    system_notes = [
        n for n in notes
        if n.get("system_generated") is True and n.get("counselor_id") is None
    ]
    assert len(system_notes) >= 1, "completion appends a system-generated note"


def test_escalation_and_deescalation_compensation(api):
    """PRD §3.7: "Escalation increments `escalation_level` by one, stamps
    `last_escalated_at`, auto-creates a follow-up scheduled 24 hours out with
    `auto_created` true and `required_count_at_schedule` pinned from the case, and
    appends a system-generated case note recording the event (which bumps the
    case's `version`)."
    PRD §3.7: "De-escalation back to `IN_PROGRESS` is a `HotlineSupervisor`-only act
    and carries the compensating half: every `SCHEDULED` follow-up with
    `auto_created` true is cancelled."

    Design: Difficulty/non_linear_state_machine/case_escalation_cycle
    """
    bundle = setup_verified_case()  # VERIFIED CRITICAL (75), IN_PROGRESS
    fu1, sweep, completed = _completed_cycle_to_in_progress(api, bundle)
    assert get_case(bundle, bundle["case"]["id"])["status"] == "IN_PROGRESS"

    escalated = escalate_case(bundle, bundle["case"])
    assert escalated["status"] == "ESCALATED"
    assert escalated["escalation_level"] == 1
    assert escalated.get("last_escalated_at") is not None

    follow_ups = get_case_follow_ups(bundle, bundle["case"]["id"])
    auto = [f for f in follow_ups if f["auto_created"]]
    assert len(auto) == 1
    assert auto[0]["status"] == "SCHEDULED"
    assert_instant_equal(auto[0]["scheduled_for"], "2026-08-03T00:00:00Z",
                         "auto follow-up scheduled 24h out")
    assert auto[0]["required_count_at_schedule"] == 3, "pinned from CRITICAL tier"

    resolved_back = transition_case_ok(
        bundle, bundle["case"]["id"], "IN_PROGRESS",
        headers=TEST_USERS["supervisor_headers"],
    )
    assert resolved_back["status"] == "IN_PROGRESS"
    follow_ups_after = {f["id"]: f for f in get_case_follow_ups(bundle, bundle["case"]["id"])}
    assert follow_ups_after[auto[0]["id"]]["status"] == "CANCELLED", (
        "de-escalation compensation cancels the auto-created follow-up"
    )
    assert follow_ups_after[fu1["id"]]["status"] == "COMPLETED"


def test_missed_followups_recompute_and_auto_escalate(api):
    """PRD §3.7: "A miss is the serious event. The case's `missed_follow_up_count`
    increases by one, and the priority score is recomputed with the
    five-points-per-miss history component. If the recompute crosses into
    `CRITICAL`, `required_follow_up_count` updates for future scheduling only —
    existing follow-ups keep their `required_count_at_schedule`."
    PRD §3.7: "And when the case is `VERIFIED`, the new tier is `CRITICAL`, and the
    case sits in `IN_PROGRESS` or `PENDING_FOLLOW_UP`, the system auto-escalates it
    with exactly the same side effects as a manual escalation; a case already
    `ESCALATED` does not re-escalate, and an unverified case recomputes its score
    but does not auto-escalate."

    Design: Difficulty/combinatorial_formula/follow_up_cadence_circular_break
    """
    bundle = setup_verified_case(case_facts=BASE_65_FACTS)
    case = bundle["case"]
    assert case["priority_score"] == 65 and case["urgency_tier"] == "ELEVATED"
    assert case["required_follow_up_count"] == 2

    schedule_follow_up(bundle, case["id"], "2026-08-02T00:00:00Z")
    schedule_follow_up(bundle, case["id"], "2026-08-03T00:00:00Z")
    set_clock("2026-08-05T00:00:01Z")
    sweep = run_time_sweep()
    assert sweep["follow_ups_missed"] == 2, (
        "FU1 missed strictly after 08-04T00:00Z; FU2 strictly after 08-05T00:00Z"
    )

    current = get_case(bundle, case["id"])
    assert current["missed_follow_up_count"] == 2
    # 65 + 2*5 = 75; the first miss recomputed to 70 -> CRITICAL -> one
    # auto-escalation from PENDING_FOLLOW_UP; the second did not re-escalate.
    assert current["priority_score"] == 75
    assert current["urgency_tier"] == "CRITICAL"
    assert current["status"] == "ESCALATED"
    assert current["escalation_level"] == 1


def test_no_retroactive_reclassification_after_tier_change(api):
    """PRD §3.6: "The evaluation order score → tier → required count is pinned,
    which is what breaks the otherwise-circular dependency: missed follow-ups raise
    the next score recompute, a higher tier raises the required count, but each
    existing follow-up is always classified against the
    `required_count_at_schedule` captured when it was scheduled — a tier change
    never retroactively reclassifies an existing follow-up."

    Design: Difficulty/combinatorial_formula/follow_up_cadence_circular_break
    """
    bundle = setup_verified_case(case_facts=BASE_65_FACTS)
    case = bundle["case"]
    fu1 = schedule_follow_up(bundle, case["id"], "2026-08-02T00:00:00Z")
    fu2 = schedule_follow_up(bundle, case["id"], "2026-08-03T00:00:00Z")
    set_clock("2026-08-05T00:00:01Z")
    run_time_sweep()

    current = get_case(bundle, case["id"])
    assert current["required_follow_up_count"] == 3, (
        "the CRITICAL tier raises the cadence for future scheduling only"
    )
    follow_ups = {f["id"]: f for f in get_case_follow_ups(bundle, case["id"])}
    for fu in (fu1, fu2):
        assert follow_ups[fu["id"]]["status"] == "MISSED"
        assert follow_ups[fu["id"]]["required_count_at_schedule"] == 2, (
            "existing follow-ups keep their required_count_at_schedule"
        )
    auto = [f for f in follow_ups.values() if f["auto_created"]]
    assert len(auto) == 1
    assert auto[0]["status"] == "SCHEDULED"
    assert_instant_equal(auto[0]["scheduled_for"], "2026-08-06T00:00:01Z",
                         "auto follow-up 24h after the auto-escalation")
    assert auto[0]["required_count_at_schedule"] == 3


def test_escalate_provisional_rejected(api):
    """PRD §3.7: "Manual escalation moves `IN_PROGRESS` → `ESCALATED` and is
    reserved for the worst cases: `score_variant` must be `VERIFIED`
    (`ERR_CASE_NOT_VERIFIED`) and `urgency_tier` must be `CRITICAL`
    (`ERR_INVALID_STATE` — only imminent-eviction-grade cases escalate manually)."

    Design: Corner/endpoints/escalate_provisional_rejected
    """
    bundle = setup_hotline()
    caller, session = start_active_session(bundle)
    case = open_case(bundle, caller, session,
                     eviction_notice_date="2026-08-05",
                     habitability_reported_at="2026-07-15T00:00:00Z",
                     deposit_amount_cents=200000, monthly_rent_cents=150000)
    assert case["priority_score"] == 75 and case["urgency_tier"] == "CRITICAL"
    move_case_in_progress(bundle, case)

    resp = api.transition_case(
        case["id"], {"to_status": "ESCALATED"}, bundle["worker_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_CASE_NOT_VERIFIED)
    current = get_case(bundle, case["id"])
    assert current["status"] == "IN_PROGRESS"
    assert current["escalation_level"] == 0


def test_followup_complete_from_scheduled_rejected(api):
    """PRD §3.7: "Completion is a human act: a `Counselor` or `HotlineSupervisor`
    moves a `DUE` follow-up to `COMPLETED` with a mandatory `outcome` text
    (`ERR_INVALID_REQUEST` if absent), stamping `completed_at`."
    PRD §2.10: "The requested transition must be listed for the resource's current
    state, terminal states reject everything, a session cannot go active while an
    interpreter request is pending, a case can only be opened from a session that
    is active or wrapped up, notes and referrals attach only to cases in an open
    counseling state, and manual escalation is reserved for critical cases —
    otherwise `ERR_INVALID_STATE`."

    Design: Corner/state_machines/followup_complete_from_scheduled_rejected
    """
    bundle = setup_verified_case()
    fu1 = schedule_follow_up(bundle, bundle["case"]["id"], "2026-08-02T00:00:00Z")
    # Clock is still 2026-08-01: the follow-up is SCHEDULED, not DUE.
    resp = api.transition_follow_up(
        fu1["id"], {"to_status": "COMPLETED", "outcome": "too early"},
        bundle["worker_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_case_resolve_with_open_items_rejected(api):
    """PRD §3.7: "From `IN_PROGRESS`, `PENDING_FOLLOW_UP`, or `ESCALATED`, a case
    may move to `RESOLVED` only when no follow-up stands in `SCHEDULED` or `DUE` and
    no referral stands in `PROPOSED` or `DISPATCHED` — otherwise
    `ERR_CASE_HAS_OPEN_ITEMS`."

    Design: Corner/state_machines/case_resolve_with_open_items_rejected
    """
    bundle = setup_hotline()
    caller, session = start_active_session(bundle)
    case = open_case(bundle, caller, session)
    move_case_in_progress(bundle, case)
    fu1 = schedule_follow_up(bundle, case["id"], "2026-08-02T00:00:00Z")
    assert get_case(bundle, case["id"])["status"] == "PENDING_FOLLOW_UP"

    resp = api.transition_case(
        case["id"], {"to_status": "RESOLVED"}, bundle["worker_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_CASE_HAS_OPEN_ITEMS)
    assert get_case(bundle, case["id"])["status"] == "PENDING_FOLLOW_UP"
    remaining = {f["id"]: f for f in get_case_follow_ups(bundle, case["id"])}
    assert remaining[fu1["id"]]["status"] == "SCHEDULED"


def test_cancel_scheduled_followup(api):
    """PRD §3.7: "Cancellation of a `SCHEDULED` follow-up, whether manual or by
    cascade (consent revocation or expiry, or de-escalation), performs the same
    bubble-up."

    Design: Corner/cross_cutting_complexity_layers/cancel_scheduled_followup
    """
    bundle = setup_hotline()
    caller, session = start_active_session(bundle)
    case = open_case(bundle, caller, session)
    move_case_in_progress(bundle, case)
    fu1 = schedule_follow_up(bundle, case["id"], "2026-08-02T10:00:00Z")
    assert get_case(bundle, case["id"])["status"] == "PENDING_FOLLOW_UP"

    cancelled = validate_success(api.transition_follow_up(
        fu1["id"], {"to_status": "CANCELLED"}, bundle["worker_headers"]
    ))
    assert cancelled["status"] == "CANCELLED"
    assert get_case(bundle, case["id"])["status"] == "IN_PROGRESS", (
        "no remaining non-terminal follow-ups — the case bubbles back"
    )


def test_followup_spacing_rejected(api):
    """PRD §3.7: "A follow-up is scheduled on a case in `IN_PROGRESS`,
    `PENDING_FOLLOW_UP`, or `ESCALATED` — other states reject with
    `ERR_INVALID_STATE` — with a `scheduled_for` instant that must lie strictly
    after the current logical time (a past instant is `ERR_INVALID_REQUEST`) and
    must stand at least 24 hours away from every other non-terminal follow-up on
    the same case: a gap of strictly less than 24 hours is rejected with
    `ERR_FOLLOW_UP_TOO_SOON`, while exactly 24 hours passes."

    Design: Corner/validations/followup_spacing_rejected
    """
    bundle = setup_hotline()
    caller, session = start_active_session(bundle)
    case = open_case(bundle, caller, session)
    move_case_in_progress(bundle, case)
    schedule_follow_up(bundle, case["id"], "2026-08-02T10:00:00Z")

    resp = api.create_follow_up(
        case["id"], {"scheduled_for": "2026-08-02T20:00:00Z"},
        bundle["worker_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_FOLLOW_UP_TOO_SOON)


def test_anonymous_followup_schedule_rejected(api):
    """PRD §3.7: "Scheduling for a case whose caller is anonymous is refused with
    `ERR_ANONYMOUS_FOLLOW_UP_FORBIDDEN`."

    Design: Corner/validations/anonymous_followup_schedule_rejected
    """
    bundle = setup_hotline()
    caller, session = start_active_session(
        bundle, alias="anon-1", channel="CHAT", is_anonymous=True
    )
    case = open_case(bundle, caller, session)
    move_case_in_progress(bundle, case)

    resp = api.create_follow_up(
        case["id"], {"scheduled_for": "2026-08-02T10:00:00Z"},
        bundle["worker_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_ANONYMOUS_FOLLOW_UP_FORBIDDEN)
    assert get_case(bundle, case["id"])["status"] == "IN_PROGRESS", (
        "no follow-up was created, so no auto-transition to PENDING_FOLLOW_UP"
    )


def test_deescalate_counselor_forbidden(api):
    """PRD §2.1: "Certain transitions are narrower than their endpoint's role list —
    case de-escalation, every transition to `CLOSED`, script retirement from
    `PUBLISHED`, and resource retirement are `HotlineSupervisor`-only even where the
    endpoint itself also admits counselors."
    PRD §3.7: "De-escalation back to `IN_PROGRESS` is a `HotlineSupervisor`-only act
    and carries the compensating half: every `SCHEDULED` follow-up with
    `auto_created` true is cancelled."

    Design: Corner/rbac/deescalate_counselor_forbidden
    """
    bundle = setup_verified_case()
    escalated = escalate_case(bundle, bundle["case"])
    assert escalated["status"] == "ESCALATED"

    forbidden = api.transition_case(
        bundle["case"]["id"], {"to_status": "IN_PROGRESS"},
        bundle["worker_headers"],
    )
    validate_error(forbidden, ApiErrorId.ERR_FORBIDDEN)
    assert get_case(bundle, bundle["case"]["id"])["status"] == "ESCALATED"

    resolved_back = transition_case_ok(
        bundle, bundle["case"]["id"], "IN_PROGRESS",
        headers=TEST_USERS["supervisor_headers"],
    )
    assert resolved_back["status"] == "IN_PROGRESS"
    follow_ups = get_case_follow_ups(bundle, bundle["case"]["id"])
    auto = [f for f in follow_ups if f["auto_created"]]
    assert len(auto) == 1 and auto[0]["status"] == "CANCELLED", (
        "supervisor de-escalation runs the compensation"
    )
