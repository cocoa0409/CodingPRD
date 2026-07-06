"""Composite setup helpers.

Every test runs against a freshly restarted, empty database. These helpers build
all preconditions from scratch using only PRD-declared endpoints, and use the
lenient get_success_data() validator so setup failures surface as clear
"Setup failed" errors rather than confusing assertion failures.

Identity threading: AccountOwner and Receptionist are entity-backed roles. After
a fixture creates such an entity, ownership-gated calls in the same chain use the
per-instance header builder (make_account_owner_headers / make_receptionist_headers)
with the real entity id — never the shared TEST_USERS constant.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    make_platform_admin_headers,
    make_account_owner_headers,
    make_receptionist_headers,
)
from . import factories as f

ADMIN = make_platform_admin_headers()


# --- clock -------------------------------------------------------------------
def set_clock(iso: str):
    """Advance the logical clock to an absolute UTC instant."""
    return get_success_data(api_client.set_clock(iso, ADMIN))


# --- plans / accounts --------------------------------------------------------
def create_per_minute_plan(**overrides) -> dict:
    resp = api_client.create_service_plan(f.create_per_minute_plan_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_per_call_plan(**overrides) -> dict:
    resp = api_client.create_service_plan(f.create_per_call_plan_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_account(plan_id, **overrides) -> dict:
    resp = api_client.create_account(f.create_account_payload(plan_id, **overrides), ADMIN)
    return get_success_data(resp)


def create_account_on_per_minute_plan(plan_overrides=None, account_overrides=None):
    """Returns (plan, account). Account opens its first OPEN BillingPeriod."""
    plan = create_per_minute_plan(**(plan_overrides or {}))
    account = create_account(plan["id"], **(account_overrides or {}))
    return plan, account


def create_account_on_per_call_plan(plan_overrides=None, account_overrides=None):
    plan = create_per_call_plan(**(plan_overrides or {}))
    account = create_account(plan["id"], **(account_overrides or {}))
    return plan, account


# --- scripts -----------------------------------------------------------------
def create_published_script(account_id, **overrides) -> dict:
    """Create a DRAFT script then publish it; returns the PUBLISHED script."""
    owner = make_account_owner_headers(account_id)
    draft = get_success_data(
        api_client.create_call_script(f.create_call_script_payload(account_id, **overrides), owner)
    )
    published = get_success_data(api_client.publish_call_script(draft["id"], owner))
    return published


# --- receptionists -----------------------------------------------------------
def create_online_receptionist(languages=None, max_concurrent_calls=5,
                               start_minute=0, end_minute=1440) -> dict:
    """Create a receptionist, give them an ACTIVE window, bring them online.
    Returns the AVAILABLE receptionist resource."""
    payload = f.create_receptionist_payload(
        languages=languages or ["EN"], max_concurrent_calls=max_concurrent_calls,
    )
    rec = get_success_data(api_client.create_receptionist(payload, ADMIN))
    rec_headers = make_receptionist_headers(rec["id"])
    get_success_data(api_client.create_availability_window(
        rec["id"], f.create_availability_window_payload(
            start_minute=start_minute, end_minute=end_minute), rec_headers))
    rec = get_success_data(api_client.go_online(rec["id"], rec_headers))
    return rec


# --- full live-answer environment -------------------------------------------
def setup_answer_environment(plan_kind="PER_CALL", plan_overrides=None,
                             script_overrides=None, rec_languages=None,
                             rec_max_concurrent=5, clock="2026-03-01T09:00:00Z"):
    """Active account + PUBLISHED script + one AVAILABLE receptionist.

    Returns dict: plan, account, script, receptionist, owner_headers, rec_headers.
    This is the most common base for any call-lifecycle test.
    """
    set_clock(clock)
    if plan_kind == "PER_MINUTE":
        plan = create_per_minute_plan(**(plan_overrides or {}))
    else:
        plan = create_per_call_plan(**(plan_overrides or {}))
    account = create_account(plan["id"])
    script = create_published_script(account["id"], **(script_overrides or {}))
    rec = create_online_receptionist(
        languages=rec_languages or ["EN"], max_concurrent_calls=rec_max_concurrent)
    return {
        "plan": plan,
        "account": account,
        "script": script,
        "receptionist": rec,
        "owner_headers": make_account_owner_headers(account["id"]),
        "rec_headers": make_receptionist_headers(rec["id"]),
    }


# --- call lifecycle ----------------------------------------------------------
def intake_call(account_id, rec_id, **call_overrides) -> dict:
    """Submit an inbound call as the given receptionist. Returns the Call."""
    rec_headers = make_receptionist_headers(rec_id)
    return get_success_data(api_client.create_call(
        f.create_call_payload(account_id, **call_overrides), rec_headers))


def answer_call(call_id, rec_id) -> dict:
    rec_headers = make_receptionist_headers(rec_id)
    return get_success_data(api_client.answer_call(call_id, rec_headers))


def run_call_segment(call_id, rec_id, start_iso, end_iso) -> dict:
    """Start the live segment at start_iso, then wrap at end_iso. Returns the
    wrapped Call (handling_status WRAP_UP)."""
    rec_headers = make_receptionist_headers(rec_id)
    set_clock(start_iso)
    get_success_data(api_client.start_call(call_id, rec_headers))
    set_clock(end_iso)
    return get_success_data(api_client.wrap_call(call_id, rec_headers))


def complete_call(call_id, rec_id) -> dict:
    rec_headers = make_receptionist_headers(rec_id)
    return get_success_data(api_client.complete_call(call_id, rec_headers))


def answer_start_wrap_complete(call_id, account_id, rec_id, start_iso, end_iso) -> dict:
    """Drive a RINGING call all the way to COMPLETED/BILLED. Returns the call
    after completion."""
    answer_call(call_id, rec_id)
    run_call_segment(call_id, rec_id, start_iso, end_iso)
    return complete_call(call_id, rec_id)


def create_completed_call(env, start_iso, end_iso, **call_overrides) -> dict:
    """From a setup_answer_environment() env, intake + drive one call to COMPLETED.
    Returns the completed Call."""
    call = intake_call(env["account"]["id"], env["receptionist"]["id"], **call_overrides)
    return answer_start_wrap_complete(
        call["id"], env["account"]["id"], env["receptionist"]["id"], start_iso, end_iso)


# --- account-posture targeting (Tier 4) -------------------------------------
def setup_suspended_account(clock="2026-03-01T10:00:00Z", hard_cap=300, r1=100):
    """Create a PER_MINUTE plan with included_minutes=0 and a low hard_cap, then
    complete one 121s call (3 billed minutes) so overage_charge reaches/exceeds
    the cap and the account is SUSPENDED.

    Returns the env dict from setup_answer_environment plus 'period_id'.
    """
    env = setup_answer_environment(
        plan_kind="PER_MINUTE",
        plan_overrides={
            "included_minutes": 0, "overage_rate_cents": r1,
            "overage_tier2_rate_cents": r1, "hard_cap_overage_cents": hard_cap,
            "overage_tier2_threshold": 100,
        },
        clock=clock,
    )
    account = get_success_data(api_client.get_account(env["account"]["id"], ADMIN))
    env["period_id"] = account["current_period_id"]
    # 121s -> ceil(121/60)=3 billed minutes -> overage 3 -> charge 3*r1.
    create_completed_call(env, "2026-03-01T10:00:00Z", "2026-03-01T10:02:01Z")
    return env


# --- slots / appointments (Tier 2/3) ----------------------------------------
def create_slot(account_id, capacity=1, buffer_minutes=0,
                window_start="2026-03-02T09:00:00Z", window_end="2026-03-02T17:00:00Z"):
    """Create an OPEN CalendarSlot. Returns the slot."""
    owner = make_account_owner_headers(account_id)
    return get_success_data(api_client.create_calendar_slot(
        f.create_calendar_slot_payload(
            account_id, capacity=capacity, buffer_minutes=buffer_minutes,
            window_start=window_start, window_end=window_end),
        owner))


def book_appointment(account_id, slot_id, expected_slot_version,
                     start_at="2026-03-02T10:00:00Z", end_at="2026-03-02T10:30:00Z",
                     **overrides) -> dict:
    """Book one appointment into a slot (REQUESTED). Returns the Appointment."""
    owner = make_account_owner_headers(account_id)
    return get_success_data(api_client.create_appointment(
        f.create_appointment_payload(
            account_id, slot_id, expected_slot_version,
            start_at=start_at, end_at=end_at, **overrides),
        owner))


def confirm_appointment(account_id, appointment_id) -> dict:
    owner = make_account_owner_headers(account_id)
    return get_success_data(api_client.confirm_appointment(appointment_id, owner))


def setup_slot_with_confirmed_appointment(plan_kind="PER_CALL", capacity=1,
                                          buffer_minutes=0,
                                          start_at="2026-03-02T10:00:00Z",
                                          end_at="2026-03-02T10:30:00Z",
                                          clock="2026-03-01T00:00:00Z"):
    """Active account + OPEN slot + one CONFIRMED appointment.

    Returns dict: account, slot, appointment, owner_headers. The returned slot
    reflects booked_count after the booking (re-fetched).
    """
    set_clock(clock)
    if plan_kind == "PER_MINUTE":
        plan, account = create_account_on_per_minute_plan()
    else:
        plan, account = create_account_on_per_call_plan()
    slot = create_slot(account["id"], capacity=capacity, buffer_minutes=buffer_minutes)
    appt = book_appointment(
        account["id"], slot["id"], slot["version"], start_at=start_at, end_at=end_at)
    appt = confirm_appointment(account["id"], appt["id"])
    owner = make_account_owner_headers(account["id"])
    slot = get_success_data(api_client.get_calendar_slot(slot["id"], owner))
    return {
        "plan": plan,
        "account": account,
        "slot": slot,
        "appointment": appt,
        "owner_headers": owner,
    }


# --- dispute / adjust (billing axis) ----------------------------------------
def setup_disputed_call(plan_overrides=None, clock="2026-03-01T09:00:00Z",
                        start_iso="2026-03-01T09:05:00Z", end_iso="2026-03-01T09:07:01Z"):
    """PER_MINUTE account, one completed+BILLED call, then DISPUTED by the owner.

    Returns dict: env keys plus 'call' (the disputed call, fields incl version),
    'period_id'. Call duration is 121s -> 3 billed minutes by default.
    """
    env = setup_answer_environment(
        plan_kind="PER_MINUTE",
        plan_overrides=plan_overrides or {
            "included_minutes": 100, "overage_rate_cents": 100,
            "overage_tier2_rate_cents": 100, "hard_cap_overage_cents": 100_000,
            "overage_tier2_threshold": 100,
        },
        clock=clock,
    )
    account = get_success_data(api_client.get_account(env["account"]["id"], ADMIN))
    env["period_id"] = account["current_period_id"]
    call = create_completed_call(env, start_iso, end_iso)
    owner = env["owner_headers"]
    call = get_success_data(api_client.dispute_call(call["id"], owner))
    env["call"] = call
    return env
