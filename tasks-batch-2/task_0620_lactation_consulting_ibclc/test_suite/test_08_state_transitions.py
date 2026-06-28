"""State-machine preconditions, invalid transitions, and terminal-state lockdown
across consults, superbills, follow-up plans, and referrals (state_machines
section breadth from queue B).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    setup_practice_with_consultant_and_client, create_consult,
    create_completed_consult, create_in_progress_consult,
    create_submitted_superbill, create_open_follow_up_plan,
    create_referral, close_follow_up_plan,
    create_feeding_assessment_payload, create_weighted_feed_payload,
    make_consultant_headers,
    TEST_USERS,
)

FRONT_DESK = TEST_USERS["front_desk_headers"]
BILLING = TEST_USERS["billing_specialist_headers"]


# ─── state_machines / complete_consult_without_assessment_returns_error ─────

def test_complete_without_feeding_assessment_rejected(api):
    """PRD §3.5: "Completing a consult is a `Consultant` action that advances
    `IN_PROGRESS → COMPLETED`. ... requires that a feeding assessment already exists
    for this consult; completing a consult with no recorded assessment is rejected
    with `ERR_NO_FEEDING_ASSESSMENT`."

    Design: Corner/state_machines/complete_consult_without_assessment_returns_error
    """
    ctx = setup_practice_with_consultant_and_client(clock_utc="2026-06-10T15:00:00Z")
    prac, cons, client = ctx["practice"], ctx["consultant"], ctx["client"]
    consult = create_consult(prac["id"], client["id"], cons["id"],
                             "2026-06-10T15:00:00Z", "2026-06-10T16:00:00Z")
    get_success_data(api.start_consult(consult["id"], make_consultant_headers(cons["id"])))

    resp = api.complete_consult(consult["id"], make_consultant_headers(cons["id"]))
    validate_error(resp, ApiErrorId.ERR_NO_FEEDING_ASSESSMENT.value)


# ─── state_machines / start_consult_before_start_time_returns_not_startable ─

def test_start_before_clock_reaches_start_returns_not_startable(api):
    """PRD §3.5: "requires the practice clock `now_utc` to have reached the
    appointment start — that is, `now_utc` is at or after `scheduled_start_utc`; if
    the clock is still before the start the request is rejected with
    `ERR_CONSULT_NOT_STARTABLE`."

    With the clock left at its default 2026-01-01, a 2026-06-10 consult cannot start.

    Design: Corner/state_machines/start_consult_before_start_time_returns_not_startable
    """
    ctx = setup_practice_with_consultant_and_client()  # clock left at default
    prac, cons, client = ctx["practice"], ctx["consultant"], ctx["client"]
    consult = create_consult(prac["id"], client["id"], cons["id"],
                             "2026-06-10T15:00:00Z", "2026-06-10T16:00:00Z")
    resp = api.start_consult(consult["id"], make_consultant_headers(cons["id"]))
    validate_error(resp, ApiErrorId.ERR_CONSULT_NOT_STARTABLE.value)


# ─── state_machines / complete_consult_from_scheduled_invalid_transition ────

def test_complete_scheduled_consult_returns_not_in_progress(api):
    """PRD §3.5: "Completing a consult is a `Consultant` action that advances
    `IN_PROGRESS → COMPLETED`. It requires the consult to be `IN_PROGRESS`
    (`ERR_CONSULT_NOT_IN_PROGRESS` otherwise)".

    Completing a SCHEDULED (never started) consult is rejected
    ERR_CONSULT_NOT_IN_PROGRESS.

    Design: Corner/state_machines/complete_consult_from_scheduled_invalid_transition
    """
    ctx = setup_practice_with_consultant_and_client()
    prac, cons, client = ctx["practice"], ctx["consultant"], ctx["client"]
    consult = create_consult(prac["id"], client["id"], cons["id"],
                             "2026-06-10T15:00:00Z", "2026-06-10T16:00:00Z")
    resp = api.complete_consult(consult["id"], make_consultant_headers(cons["id"]))
    validate_error(resp, ApiErrorId.ERR_CONSULT_NOT_IN_PROGRESS.value)


# ─── state_machines / cancel_already_cancelled_consult_returns_not_cancellable

def test_cancel_already_cancelled_consult_rejected(api):
    """PRD §3.6: "Cancellation is permitted only on a consult that is `SCHEDULED`; an
    attempt to cancel a consult in any other state is rejected with
    `ERR_CONSULT_NOT_CANCELLABLE`."

    A second cancel on an already-CANCELLED consult is rejected
    ERR_CONSULT_NOT_CANCELLABLE.

    Design: Corner/state_machines/cancel_already_cancelled_consult_returns_not_cancellable
    """
    ctx = setup_practice_with_consultant_and_client()
    prac, cons, client = ctx["practice"], ctx["consultant"], ctx["client"]
    consult = create_consult(prac["id"], client["id"], cons["id"],
                             "2026-06-10T15:00:00Z", "2026-06-10T16:00:00Z")
    validate_success(api.cancel_consult(consult["id"], FRONT_DESK), 200)
    resp = api.cancel_consult(consult["id"], FRONT_DESK)
    validate_error(resp, ApiErrorId.ERR_CONSULT_NOT_CANCELLABLE.value)


# ─── state_machines / adjudicate_superbill_not_submitted_returns_error ──────

def test_adjudicate_draft_superbill_returns_not_submitted(api):
    """PRD §3.9: "Adjudication is the decisive step and is driven by an `outcome`
    supplied in the request. The superbill must be `SUBMITTED`, otherwise
    `ERR_SUPERBILL_NOT_SUBMITTED`."

    Adjudicating a DRAFT (never submitted) superbill is rejected
    ERR_SUPERBILL_NOT_SUBMITTED.

    Design: Corner/state_machines/adjudicate_superbill_not_submitted_returns_error
    """
    ctx = create_completed_consult()
    from test_helpers import draft_superbill
    sb = draft_superbill(ctx["consult"]["id"], 25000, 15000, is_aca_preventive=True)
    resp = api.adjudicate_superbill(sb["id"], {"outcome": "PAID"}, BILLING)
    validate_error(resp, ApiErrorId.ERR_SUPERBILL_NOT_SUBMITTED.value)


# ─── state_machines / void_unpaid_superbill_returns_not_voidable ────────────

def test_void_submitted_superbill_returns_not_voidable(api):
    """PRD §3.9: "The superbill must be `PAID`, otherwise `ERR_SUPERBILL_NOT_VOIDABLE`."

    Voiding a SUBMITTED (not PAID) superbill is rejected ERR_SUPERBILL_NOT_VOIDABLE.

    Design: Corner/state_machines/void_unpaid_superbill_returns_not_voidable
    """
    ctx = create_submitted_superbill(
        billed_amount_cents=25000, allowed_amount_cents=15000, is_aca_preventive=True)
    client_ver = get_success_data(api.get_client(ctx["client"]["id"], BILLING))["version"]
    resp = api.void_superbill(
        ctx["superbill"]["id"], {"expected_client_version": client_ver}, BILLING)
    validate_error(resp, ApiErrorId.ERR_SUPERBILL_NOT_VOIDABLE.value)


# ─── state_machines / weighted_feed_on_closed_plan_returns_plan_closed ──────

def test_weighted_feed_on_closed_plan_rejected(api):
    """PRD §3.8: "A weighted feed may be recorded only while its plan is `OPEN`; once
    the plan is closed, further feed entry is rejected with `ERR_PLAN_CLOSED`."

    Design: Corner/state_machines/weighted_feed_on_closed_plan_returns_plan_closed
    """
    ctx = create_open_follow_up_plan(target_daily_transfer_grams=100)
    plan, cons = ctx["plan"], ctx["consultant"]
    close_follow_up_plan(plan["id"], cons["id"])

    resp = api.create_weighted_feed(
        create_weighted_feed_payload(plan["id"], 4000, 4050),
        make_consultant_headers(cons["id"]))
    validate_error(resp, ApiErrorId.ERR_PLAN_CLOSED.value)


# ─── state_machines / acknowledge_already_acknowledged_referral_returns_error

def test_acknowledge_already_acknowledged_referral_rejected(api):
    """PRD §3.11: "A referral has two terminal resolutions, both `Consultant` actions
    on an `OPEN` referral (otherwise `ERR_REFERRAL_NOT_OPEN` in either case).
    Acknowledging it advances `OPEN → ACKNOWLEDGED`".

    A second acknowledge on an ACKNOWLEDGED referral is rejected ERR_REFERRAL_NOT_OPEN.

    Design: Corner/state_machines/acknowledge_already_acknowledged_referral_returns_error
    """
    ctx = create_completed_consult()
    ref = create_referral(ctx["consult"]["id"], ctx["consultant"]["id"])
    validate_success(api.acknowledge_pediatrician_referral(
        ref["id"], make_consultant_headers(ctx["consultant"]["id"])), 200)
    resp = api.acknowledge_pediatrician_referral(
        ref["id"], make_consultant_headers(ctx["consultant"]["id"]))
    validate_error(resp, ApiErrorId.ERR_REFERRAL_NOT_OPEN.value)


# ─── state_machines / reschedule_completed_consult_invalid ──────────────────

def test_reschedule_completed_consult_rejected(api):
    """PRD §3.5: "Rescheduling is permitted only on a consult in `SCHEDULED` status,
    otherwise it is rejected with `ERR_CONSULT_NOT_SCHEDULED`".

    Rescheduling a COMPLETED consult is rejected ERR_CONSULT_NOT_SCHEDULED.

    Design: Corner/state_machines/reschedule_completed_consult_invalid
    """
    ctx = create_completed_consult()
    resp = api.reschedule_consult(ctx["consult"]["id"], {
        "scheduled_start_utc": "2026-06-12T15:00:00Z",
        "scheduled_end_utc": "2026-06-12T16:00:00Z"}, FRONT_DESK)
    validate_error(resp, ApiErrorId.ERR_CONSULT_NOT_SCHEDULED.value)
