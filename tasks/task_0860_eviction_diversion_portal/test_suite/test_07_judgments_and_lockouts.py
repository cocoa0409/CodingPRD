"""Judgment fork, money judgment, lockout scheduling gates, officer buffer, stay
precedence, and execution gating (PRD §3.7, §3.8, §2.8)."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    make_judge_headers, make_sheriff_headers, TEST_USERS,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx

CLERK = TEST_USERS["clerk_headers"]


# --------------------------------------------------------------------------- #
# Queue A: non_linear_state_machine / judgment_fork_dismissal                   #
# --------------------------------------------------------------------------- #
def test_dismissal_judgment_routes_case_to_dismissed(api):
    """PRD §3.7: "A DISMISSAL judgment carries money_amount_cents of 0 and moves the
    case from IN_LITIGATION to DISMISSED, stamping closed_at and setting the outcome to
    DISMISSED."

    Design: Difficulty/non_linear_state_machine/judgment_fork_dismissal_routes_case_dismissed
    """
    ctx = fx.setup_in_litigation_case(api, claimed_arrears_cents=600000)
    judgment = get_success_data(api.create_judgment(
        f.create_judgment_payload(ctx["case"]["id"], "DISMISSAL"),
        make_judge_headers("judge-1")))
    case = get_success_data(api.get_case(ctx["case"]["id"], CLERK))
    assert judgment["judgment_type"] == "DISMISSAL"
    assert case["status"] == "DISMISSED"
    assert case["outcome"] == "DISMISSED"


def test_dismissal_judgment_carries_zero_money_and_closes_case(api):
    """PRD §3.7: "A DISMISSAL judgment carries money_amount_cents of 0 and moves the
    case from IN_LITIGATION to DISMISSED, stamping closed_at". PRD §2.5: closed_at is
    captured as the logical-clock instant of the triggering event.

    Design: Difficulty/non_linear_state_machine/judgment_fork_dismissal_routes_case_dismissed
    """
    ctx = fx.setup_in_litigation_case(api, claimed_arrears_cents=600000)
    judgment = get_success_data(api.create_judgment(
        f.create_judgment_payload(ctx["case"]["id"], "DISMISSAL"),
        make_judge_headers("judge-1")))
    case = get_success_data(api.get_case(ctx["case"]["id"], CLERK))
    assert judgment["money_amount_cents"] == 0
    assert case["closed_at"] is not None


# --------------------------------------------------------------------------- #
# Queue A: cross_entity_state_dependency / lockout_schedule_requires_possession #
# --------------------------------------------------------------------------- #
def test_lockout_schedule_succeeds_and_assigns_officer(api):
    """PRD §3.8: "The referenced judgment must be of type POSSESSION and in status
    ENTERED or STAYED ... On success the officer_id and scheduled_at are recorded".

    Design: Difficulty/cross_entity_state_dependency/lockout_schedule_requires_possession_judgment_entered
    """
    ctx = fx.setup_requested_lockout(api, claimed_arrears_cents=600000)
    scheduled = get_success_data(api.transition_lockout_order(
        ctx["lockout"]["id"],
        {"to_status": "SCHEDULED", "officer_id": ctx["officer"]["id"],
         "scheduled_at": "2026-06-01T10:00:00Z"},
        make_sheriff_headers()))
    assert scheduled["status"] == "SCHEDULED"
    assert scheduled["officer_id"] == ctx["officer"]["id"]


def test_lockout_schedule_moves_case_to_enforcement(api):
    """PRD §3.8: "On success the officer_id and scheduled_at are recorded and the case
    advances from JUDGMENT_ENTERED to ENFORCEMENT."

    Design: Difficulty/cross_entity_state_dependency/lockout_schedule_requires_possession_judgment_entered
    """
    ctx = fx.setup_requested_lockout(api, claimed_arrears_cents=600000)
    scheduled = get_success_data(api.transition_lockout_order(
        ctx["lockout"]["id"],
        {"to_status": "SCHEDULED", "officer_id": ctx["officer"]["id"],
         "scheduled_at": "2026-06-01T10:00:00Z"},
        make_sheriff_headers()))
    case = get_success_data(api.get_case(ctx["case"]["id"], CLERK))
    assert scheduled["scheduled_at"] == "2026-06-01T10:00:00.000Z"
    assert case["status"] == "ENFORCEMENT"


# --------------------------------------------------------------------------- #
# Two-lockout / one-officer scenarios (buffer + stay precedence)               #
# --------------------------------------------------------------------------- #
def _two_possession_lockouts(api):
    """Case A: POSSESSION judgment, lockout SCHEDULED at 2026-06-01T10:00.
    Case B: POSSESSION judgment ENTERED, lockout REQUESTED. Same officer.
    Returns (ctx, officer, judg_b, lock_b)."""
    ctx = fx.seed_parties(api)
    officer = fx.seed_officer(api)
    # Case A
    case_a = fx.file_case(api, ctx, claimed_arrears_cents=600000)
    fx.serve_case(api, case_a["id"])
    fx.answer_case(api, ctx, case_a["id"])
    fx.case_to_in_litigation(api, case_a["id"])
    ctx["case"] = fx.fetch_case(api, case_a["id"])
    judg_a = fx.enter_judgment(api, ctx, "POSSESSION")
    lock_a = fx.request_lockout(api, ctx, judg_a["id"])
    fx.schedule_lockout(api, lock_a["id"], officer["id"], "2026-06-01T10:00:00Z")
    # Case B
    case_b = fx.file_case(api, ctx, claimed_arrears_cents=300000)
    fx.serve_case(api, case_b["id"])
    fx.answer_case(api, ctx, case_b["id"])
    fx.case_to_in_litigation(api, case_b["id"])
    ctx["case"] = fx.fetch_case(api, case_b["id"])
    judg_b = fx.enter_judgment(api, ctx, "POSSESSION")
    lock_b = fx.request_lockout(api, ctx, judg_b["id"])
    return ctx, officer, judg_b, lock_b


# --------------------------------------------------------------------------- #
# Queue A: resource_temporal_overlap / lockout_officer_buffer_overlap           #
# --------------------------------------------------------------------------- #
def test_officer_buffer_overlap_rejected(api):
    """PRD §3.8: "Two lockouts for the same officer must be at least forty-eight hours
    apart (LOCKOUT_BUFFER_HOURS of 48) — exactly forty-eight hours apart is allowed, and
    a gap strictly less than that is refused with ERR_OFFICER_UNAVAILABLE."

    Design: Difficulty/resource_temporal_overlap/lockout_officer_buffer_overlap_rejected
    """
    ctx, officer, judg_b, lock_b = _two_possession_lockouts(api)
    # Second lockout at 2026-06-02T10:00 is 24h from the existing 2026-06-01T10:00 (< 48h).
    resp = api.transition_lockout_order(
        lock_b["id"],
        {"to_status": "SCHEDULED", "officer_id": officer["id"],
         "scheduled_at": "2026-06-02T10:00:00Z"},
        make_sheriff_headers())
    validate_error(resp, ApiErrorId.ERR_OFFICER_UNAVAILABLE.value, expected_status=409)


def test_officer_buffer_overlap_leaves_lockout_requested(api):
    """PRD §3.8: a gap strictly less than forty-eight hours "is refused with
    ERR_OFFICER_UNAVAILABLE." The rejected lockout stays REQUESTED (no officer/time set).

    Design: Difficulty/resource_temporal_overlap/lockout_officer_buffer_overlap_rejected
    """
    ctx, officer, judg_b, lock_b = _two_possession_lockouts(api)
    api.transition_lockout_order(
        lock_b["id"],
        {"to_status": "SCHEDULED", "officer_id": officer["id"],
         "scheduled_at": "2026-06-02T10:00:00Z"},
        make_sheriff_headers())
    fetched = get_success_data(api.get_lockout_order(lock_b["id"], CLERK))
    assert fetched["status"] == "REQUESTED"


# --------------------------------------------------------------------------- #
# Queue A: priority_pair_validation_conflict / temporal_beats_constraint         #
# --------------------------------------------------------------------------- #
def test_lockout_stay_active_beats_officer_buffer(api):
    """PRD §2.8: "the first failing check determines the error returned. The order is:
    ... (9) temporal gates ... (10) resource capacity and overlap ... Lower-numbered
    categories always take precedence over higher-numbered ones." PRD §3.8: "If the
    judgment is STAYED, the scheduled_at must be at or after the judgment's stay_until;
    scheduling inside an active stay yields ERR_LOCKOUT_STAY_ACTIVE."

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_constraint_on_lockout_schedule_returns_stay_active
    """
    ctx, officer, judg_b, lock_b = _two_possession_lockouts(api)
    get_success_data(api.transition_judgment(
        judg_b["id"], {"to_status": "STAYED", "stay_until": "2026-07-01T00:00:00Z"},
        make_judge_headers("judge-1")))
    # scheduled_at 09:00 is before stay_until (temporal) AND 1h from case-A's 10:00 (buffer).
    resp = api.transition_lockout_order(
        lock_b["id"],
        {"to_status": "SCHEDULED", "officer_id": officer["id"],
         "scheduled_at": "2026-06-01T09:00:00Z"},
        make_sheriff_headers())
    validate_error(resp, ApiErrorId.ERR_LOCKOUT_STAY_ACTIVE.value, expected_status=409)


def test_lockout_stay_active_leaves_lockout_requested(api):
    """PRD §3.8: "scheduling inside an active stay yields ERR_LOCKOUT_STAY_ACTIVE." The
    rejected schedule leaves the lockout REQUESTED.

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_constraint_on_lockout_schedule_returns_stay_active
    """
    ctx, officer, judg_b, lock_b = _two_possession_lockouts(api)
    get_success_data(api.transition_judgment(
        judg_b["id"], {"to_status": "STAYED", "stay_until": "2026-07-01T00:00:00Z"},
        make_judge_headers("judge-1")))
    api.transition_lockout_order(
        lock_b["id"],
        {"to_status": "SCHEDULED", "officer_id": officer["id"],
         "scheduled_at": "2026-06-01T09:00:00Z"},
        make_sheriff_headers())
    fetched = get_success_data(api.get_lockout_order(lock_b["id"], CLERK))
    assert fetched["status"] == "REQUESTED"


# --------------------------------------------------------------------------- #
# Queue B: money judgment, lockout FK gate, invalid interval, execute gate       #
# --------------------------------------------------------------------------- #
def test_money_judgment_possession_adds_filing_fee(api):
    """PRD §3.7: "A POSSESSION judgment computes money_amount_cents as the case's final
    outstanding arrears plus a filing fee of forty-five dollars (JUDGMENT_FILING_FEE_CENTS
    of 4500)".

    Design: Corner/calculations/money_judgment_amount_possession_adds_filing_fee
    """
    ctx = fx.setup_in_litigation_case(api, claimed_arrears_cents=600000)
    judgment = get_success_data(api.create_judgment(
        f.create_judgment_payload(ctx["case"]["id"], "POSSESSION"),
        make_judge_headers("judge-1")))
    assert judgment["money_amount_cents"] == 604500


def test_lockout_create_on_dismissal_judgment_returns_no_possession(api):
    """PRD §3.8: "a vacated, satisfied, or non-possession judgment yields
    ERR_NO_POSSESSION_JUDGMENT."

    Design: Corner/validations/lockout_create_on_dismissal_judgment_returns_no_possession
    """
    ctx = fx.setup_dismissed_case(api, claimed_arrears_cents=600000)
    resp = api.create_lockout_order(
        f.create_lockout_order_payload(ctx["case"]["id"], ctx["judgment"]["id"]),
        fx.ll_headers(ctx))
    validate_error(resp, ApiErrorId.ERR_NO_POSSESSION_JUDGMENT.value, expected_status=409)


def test_judgment_stay_until_in_past_returns_invalid_interval(api):
    """PRD §3.7: "the stay instant must be strictly in the future relative to the current
    clock (otherwise ERR_INVALID_INTERVAL)."

    Design: Corner/validations/judgment_stay_until_in_past_returns_invalid_interval
    """
    ctx = fx.setup_possession_judgment(api, claimed_arrears_cents=600000)
    resp = api.transition_judgment(
        ctx["judgment"]["id"], {"to_status": "STAYED", "stay_until": "2026-04-01T00:00:00Z"},
        make_judge_headers("judge-1"))
    validate_error(resp, ApiErrorId.ERR_INVALID_INTERVAL.value, expected_status=422)


def test_lockout_execute_before_scheduled_returns_not_due(api):
    """PRD §3.8: "Execution requires that the current logical-clock instant be at or
    after scheduled_at (otherwise ERR_LOCKOUT_NOT_DUE)".

    Design: Corner/validations/lockout_execute_before_scheduled_returns_not_due
    """
    ctx = fx.setup_scheduled_lockout(api, claimed_arrears_cents=600000,
                                     scheduled_at="2026-06-01T10:00:00Z")
    # Clock still at default 2026-05-01, before scheduled_at.
    resp = api.transition_lockout_order(
        ctx["lockout"]["id"], {"to_status": "EXECUTED"}, make_sheriff_headers())
    validate_error(resp, ApiErrorId.ERR_LOCKOUT_NOT_DUE.value, expected_status=409)
