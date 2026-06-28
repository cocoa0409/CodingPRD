"""Composite setup helpers.

Each test runs against a freshly-restarted, empty server. These helpers build the
multi-step preconditions that the design indices require (plan -> clock -> register
-> screen -> approve -> activate -> set preferences -> suggest -> respond -> ...),
so individual tests focus on the assertion under test.

All setup calls use get_success_data() (lenient) so a setup failure surfaces a clear
"Setup step failed" message rather than a confusing downstream assertion error.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS, make_member_headers
from . import factories as f
from .constants import DEFAULT_CLOCK


# Convenience header accessors
def _admin():
    return TEST_USERS["billing_admin_headers"]


def _screening():
    return TEST_USERS["screening_officer_headers"]


def _matchmaker():
    return TEST_USERS["matchmaker_headers"]


# ---------------------------------------------------------------------------
# Primitive: clock
# ---------------------------------------------------------------------------
def set_clock(instant=DEFAULT_CLOCK):
    """Set the logical clock and return the resulting now."""
    return get_success_data(api_client.set_clock(instant, _admin()))


# ---------------------------------------------------------------------------
# Tier 1: plan + member state progression
# ---------------------------------------------------------------------------
def create_plan(**overrides) -> dict:
    """Create a MembershipPlan as BillingAdmin. Returns the plan."""
    return get_success_data(api_client.create_plan(f.create_plan_payload(**overrides), _admin()))


def register_prospect(email, gender="MALE", **overrides) -> dict:
    """Register a PROSPECT member. Returns the member."""
    payload = f.create_member_payload(email=email, gender=gender, **overrides)
    return get_success_data(api_client.create_member(payload, _screening()))


def open_and_decide_screening(member_id, decision="APPROVED", **scr_overrides) -> dict:
    """Open a screening for a member and decide it. Returns the decided screening."""
    scr = get_success_data(
        api_client.create_screening(member_id, f.create_screening_payload(**scr_overrides), _screening())
    )
    decided = get_success_data(
        api_client.decide_screening(
            member_id, scr["id"], f.decide_screening_payload(decision=decision), _screening()
        )
    )
    return decided


def set_preferences(member_id, **overrides) -> dict:
    """Upsert a member's preferences using the member's own (ownership) headers."""
    return get_success_data(
        api_client.put_preferences(
            member_id, f.create_preference_payload(**overrides), make_member_headers(member_id)
        )
    )


def activate_membership(member_id, plan_id) -> dict:
    """Activate a membership for an APPROVED member. Returns the membership."""
    return get_success_data(
        api_client.activate_membership(member_id, f.activate_membership_payload(plan_id), _admin())
    )


def create_active_member(plan_id, email, gender="MALE", with_preferences=True,
                         pref_overrides=None, **member_overrides):
    """Full chain to an ACTIVE member on the given plan:
    register -> screen+approve -> activate membership -> (optionally) set preferences.

    Extra keyword arguments (e.g. ``city``) are forwarded to member registration
    so callers can place members in different cities for proximity scoring.

    Returns (member_dict_after_activation, membership_dict).
    """
    member = register_prospect(email, gender=gender, **member_overrides)
    open_and_decide_screening(member["id"], decision="APPROVED")
    membership = activate_membership(member["id"], plan_id)
    if with_preferences:
        set_preferences(member["id"], **(pref_overrides or {}))
    member = get_success_data(api_client.get_member(member["id"], _matchmaker()))
    return member, membership


# ---------------------------------------------------------------------------
# Tier 2: standard plan + one active pair ready to be introduced
# ---------------------------------------------------------------------------
def setup_eligible_pair(plan_overrides=None, a_pref=None, b_pref=None,
                        a_gender="MALE", b_gender="FEMALE",
                        a_email="pair_a@x.com", b_email="pair_b@x.com",
                        clock=DEFAULT_CLOCK):
    """Active, screening-approved, preference-compatible pair on a shared plan.

    member_a seeks FEMALE, member_b seeks MALE by default, both 25..45, same city,
    identical attribute vectors -> compatibility well above threshold.

    Returns dict: {plan, member_a, member_b, membership_a, membership_b}.
    """
    set_clock(clock)
    plan = create_plan(**(plan_overrides or {}))
    member_a, membership_a = create_active_member(
        plan["id"], a_email, gender=a_gender,
        pref_overrides=(a_pref or {"seeking_gender": "FEMALE"}),
    )
    member_b, membership_b = create_active_member(
        plan["id"], b_email, gender=b_gender,
        pref_overrides=(b_pref or {"seeking_gender": "MALE"}),
    )
    return {
        "plan": plan,
        "member_a": member_a,
        "member_b": member_b,
        "membership_a": membership_a,
        "membership_b": membership_b,
    }


def current_version(member_id) -> int:
    """Read a member's current version (needed for the OCC check on suggest)."""
    m = get_success_data(api_client.get_member(member_id, _matchmaker()))
    return m["version"]


def suggest_introduction(member_a_id, member_b_id, **overrides) -> dict:
    """Suggest an introduction as Matchmaker, threading member_a's live version.
    Returns the created introduction."""
    a_ver = current_version(member_a_id)
    payload = f.create_introduction_payload(member_a_id, member_b_id, a_ver, **overrides)
    return get_success_data(api_client.create_introduction(payload, _matchmaker()))


def respond(introduction_id, member_id, response, expected_version) -> dict:
    """A party member responds to an introduction. Returns the updated introduction."""
    payload = f.respond_introduction_payload(response, expected_version)
    return get_success_data(
        api_client.respond_introduction(introduction_id, payload, make_member_headers(member_id))
    )


def setup_mutual_introduction(plan_overrides=None, clock=DEFAULT_CLOCK,
                              a_email="mut_a@x.com", b_email="mut_b@x.com"):
    """Eligible pair + a MUTUAL introduction (both accepted).

    Returns dict: {plan, member_a, member_b, membership_a, membership_b, introduction}.
    The introduction dict is the state after the second accept (MUTUAL).
    """
    ctx = setup_eligible_pair(plan_overrides=plan_overrides, clock=clock,
                              a_email=a_email, b_email=b_email)
    a_id, b_id = ctx["member_a"]["id"], ctx["member_b"]["id"]
    intro = suggest_introduction(a_id, b_id)
    intro = respond(intro["id"], a_id, "ACCEPTED", intro["version"])
    intro = respond(intro["id"], b_id, "ACCEPTED", intro["version"])
    ctx["introduction"] = intro
    return ctx


def setup_suggested_introduction(plan_overrides=None, clock=DEFAULT_CLOCK,
                                 a_email="sug_a@x.com", b_email="sug_b@x.com"):
    """Eligible pair + one SUGGESTED introduction (no responses yet).

    Returns dict: {plan, member_a, member_b, membership_a, membership_b, introduction}.
    """
    ctx = setup_eligible_pair(plan_overrides=plan_overrides, clock=clock,
                              a_email=a_email, b_email=b_email)
    a_id, b_id = ctx["member_a"]["id"], ctx["member_b"]["id"]
    ctx["introduction"] = suggest_introduction(a_id, b_id)
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: dates and coaching
# ---------------------------------------------------------------------------
def schedule_date(introduction_id, scheduler_id, start_at, end_at) -> dict:
    """Schedule a DateEvent on a MUTUAL introduction as the scheduling member."""
    payload = f.create_date_event_payload(scheduler_id, start_at, end_at)
    return get_success_data(
        api_client.create_date_event(introduction_id, payload, make_member_headers(scheduler_id))
    )


def setup_mutual_with_date(start_at="2026-06-05T18:00:00Z", end_at="2026-06-05T20:00:00Z",
                           plan_overrides=None, clock=DEFAULT_CLOCK,
                           a_email="dt_a@x.com", b_email="dt_b@x.com"):
    """MUTUAL introduction with a SCHEDULED DateEvent owned by member_a.

    Returns dict from setup_mutual_introduction plus key 'date_event'.
    """
    ctx = setup_mutual_introduction(plan_overrides=plan_overrides, clock=clock,
                                    a_email=a_email, b_email=b_email)
    a_id = ctx["member_a"]["id"]
    ctx["date_event"] = schedule_date(ctx["introduction"]["id"], a_id, start_at, end_at)
    return ctx


def book_coaching(member_id, start_at, end_at, **overrides) -> dict:
    """Book a coaching session for a member as the member."""
    payload = f.create_coaching_session_payload(start_at, end_at, **overrides)
    return get_success_data(
        api_client.create_coaching_session(member_id, payload, make_member_headers(member_id))
    )


def mark_coaching_outcome(session_id, outcome) -> dict:
    """Record a coaching outcome as Matchmaker."""
    return get_success_data(
        api_client.coaching_session_outcome(session_id, {"outcome": outcome}, _matchmaker())
    )


def setup_member_with_no_shows(num_no_shows, plan_overrides=None,
                               first_session="2026-06-02T10:00:00Z",
                               outcome_clock="2026-06-02T16:00:00Z",
                               email="ns@x.com"):
    """Active member with `num_no_shows` coaching NO_SHOW sessions recorded.

    Sessions are booked at 2h apart starting from first_session, clock advanced to
    outcome_clock, then each marked NO_SHOW. Plan defaults to 5 included sessions so
    bookings are not gated. Returns (member_id, [session_ids]).
    """
    overrides = {"included_coaching_sessions": 5}
    overrides.update(plan_overrides or {})
    set_clock(DEFAULT_CLOCK)
    plan = create_plan(**overrides)
    member, _ = create_active_member(plan["id"], email, with_preferences=False)
    member_id = member["id"]

    # Book the sessions before advancing the clock (start_at must be >= now).
    base_hour = int(first_session[11:13])
    session_ids = []
    for i in range(num_no_shows):
        start_h = base_hour + 2 * i
        start = f"2026-06-02T{start_h:02d}:00:00Z"
        end = f"2026-06-02T{start_h + 1:02d}:00:00Z"
        s = book_coaching(member_id, start, end)
        session_ids.append(s["id"])

    set_clock(outcome_clock)
    for sid in session_ids:
        mark_coaching_outcome(sid, "NO_SHOW")
    return member_id, session_ids


# ---------------------------------------------------------------------------
# Tier 4: freeze windows
# ---------------------------------------------------------------------------
def schedule_freeze(membership_id, start_at, end_at) -> dict:
    """Schedule a freeze on a membership as BillingAdmin. Returns the freeze."""
    return get_success_data(
        api_client.create_freeze(membership_id, f.create_freeze_payload(start_at, end_at), _admin())
    )


def setup_membership_with_scheduled_freeze(freeze_start="2026-07-01T00:00:00Z",
                                           freeze_end="2026-07-10T00:00:00Z",
                                           clock=DEFAULT_CLOCK, email="frz@x.com"):
    """Active membership with a future SCHEDULED freeze (not yet activated).

    Returns (member_id, membership_id, freeze_id).
    """
    set_clock(clock)
    plan = create_plan()
    member, membership = create_active_member(plan["id"], email, with_preferences=False)
    frz = schedule_freeze(membership["id"], freeze_start, freeze_end)
    return member["id"], membership["id"], frz["id"]


# ---------------------------------------------------------------------------
# Tier 5: background checks
# ---------------------------------------------------------------------------
def order_background_check(member_id, **overrides) -> dict:
    """Order a background check for a member as ScreeningOfficer. Returns the check."""
    return get_success_data(
        api_client.order_background_check(
            member_id, f.order_background_check_payload(**overrides), _screening()
        )
    )
