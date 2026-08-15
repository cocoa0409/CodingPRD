"""Composite setup helpers.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints: the test harness restarts the API server before every test, so each
test begins against an empty database. Setup calls use the lenient
get_success_data() validator so failures surface as clear setup errors.

All helpers run as ProgramAdmin (the unrestricted operational superset) unless
a test deliberately exercises another role.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_coach_payload,
    create_coaching_case_payload,
    create_curriculum_module_payload,
    create_deposit_payload,
    create_goal_plan_payload,
    create_match_enrollment_payload,
    create_match_pool_payload,
    create_outcome_snapshot_payload,
    create_participant_payload,
    create_referral_payload,
    create_registration_payload,
    create_workshop_payload,
)
from .test_users import make_admin_headers

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"


def _admin(user_id: str = "test-admin-1") -> dict:
    return make_admin_headers(user_id)


# ---------------------------------------------------------------------------
# Tier 1: single-entity creation and state progression
# ---------------------------------------------------------------------------

def create_module(admin_headers=None, **overrides) -> dict:
    """Create an ACTIVE curriculum module."""
    headers = admin_headers or _admin()
    resp = api_client.create_curriculum_module(
        create_curriculum_module_payload(**overrides), headers
    )
    return get_success_data(resp)


def create_candidate_coach(admin_headers=None, **overrides) -> dict:
    """Create a coach (starts CANDIDATE)."""
    headers = admin_headers or _admin()
    resp = api_client.create_coach(create_coach_payload(**overrides), headers)
    return get_success_data(resp)


def create_certified_coach(admin_headers=None, **overrides) -> dict:
    """Create a coach and certify them. Returns the CERTIFIED coach."""
    headers = admin_headers or _admin()
    coach = create_candidate_coach(headers, **overrides)
    resp = api_client.certify_coach(coach["id"], headers)
    return get_success_data(resp)


def create_participant(admin_headers=None, **overrides) -> dict:
    """Create an ACTIVE participant with no_show_count 0."""
    headers = admin_headers or _admin()
    resp = api_client.create_participant(create_participant_payload(**overrides), headers)
    return get_success_data(resp)


def create_workshop(module_id, coach_id, admin_headers=None, **overrides) -> dict:
    """Schedule a SCHEDULED workshop with confirmed_count 0."""
    headers = admin_headers or _admin()
    resp = api_client.create_workshop(
        create_workshop_payload(module_id, coach_id, **overrides), headers
    )
    return get_success_data(resp)


def create_registration(workshop_id, participant_id, admin_headers=None, **overrides) -> dict:
    """Register a participant for a workshop (REGISTERED or WAITLISTED)."""
    headers = admin_headers or _admin()
    resp = api_client.create_registration(
        create_registration_payload(workshop_id, participant_id, **overrides), headers
    )
    return get_success_data(resp)


def set_clock(to_iso8601: str, admin_headers=None) -> dict:
    """Advance the logical clock; applies due lazy sweeps."""
    headers = admin_headers or _admin()
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, headers)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: coaching-case progression (INTAKE -> PLAN_DRAFT -> PLAN_ACTIVE ...)
# ---------------------------------------------------------------------------

def create_case(participant_id, coach_id, admin_headers=None, **overrides) -> dict:
    """Open a coaching case in INTAKE."""
    headers = admin_headers or _admin()
    resp = api_client.create_coaching_case(
        create_coaching_case_payload(participant_id, coach_id, **overrides), headers
    )
    return get_success_data(resp)


def transition_case(case_id, target_state, admin_headers=None, **extra) -> dict:
    """Drive the case state machine. Extra body fields (e.g. new_coach_id) via **extra."""
    headers = admin_headers or _admin()
    payload = {"target_state": target_state}
    payload.update(extra)
    resp = api_client.transition_coaching_case(case_id, payload, headers)
    return get_success_data(resp)


def create_goal_plan_for_case(case_id, expected_case_version, admin_headers=None, **overrides) -> dict:
    """Create a DRAFT goal plan against a PLAN_DRAFT case (OCC-guarded)."""
    headers = admin_headers or _admin()
    resp = api_client.create_goal_plan(
        create_goal_plan_payload(case_id, expected_case_version, **overrides), headers
    )
    return get_success_data(resp)


def create_snapshot(participant_id, recorded_at, admin_headers=None, **overrides) -> dict:
    """Append an outcome snapshot."""
    headers = admin_headers or _admin()
    resp = api_client.create_outcome_snapshot(
        create_outcome_snapshot_payload(participant_id, recorded_at, **overrides), headers
    )
    return get_success_data(resp)


def setup_case_with_draft_plan(participant_id=None, coach_id=None, admin_headers=None,
                               case_overrides=None, plan_overrides=None):
    """Coach + participant + case walked INTAKE -> PLAN_DRAFT, with one DRAFT plan.

    Returns dict(case, plan, participant, coach). The case's current version is
    reflected in case["version"] (after plan creation, which bumps it by 1).
    """
    headers = admin_headers or _admin()
    coach = coach_id and {"id": coach_id} or create_certified_coach(headers)
    participant = participant_id and {"id": participant_id} or create_participant(headers)
    case = create_case(participant["id"], coach["id"], headers, **(case_overrides or {}))
    case = transition_case(case["id"], "PLAN_DRAFT", headers)
    plan = create_goal_plan_for_case(
        case["id"], case["version"], headers, **(plan_overrides or {})
    )
    # Refresh case after plan creation (version bumped).
    case = get_success_data(api_client.get_coaching_case(case["id"], headers))
    return {"case": case, "plan": plan, "participant": participant, "coach": coach}


def setup_case_with_active_plan(participant_id=None, coach_id=None, admin_headers=None,
                                case_overrides=None, plan_overrides=None):
    """Case walked to PLAN_ACTIVE with its plan ACTIVE.

    Returns dict(case, plan, participant, coach).
    """
    headers = admin_headers or _admin()
    ctx = setup_case_with_draft_plan(participant_id, coach_id, headers,
                                     case_overrides=case_overrides,
                                     plan_overrides=plan_overrides)
    case = transition_case(ctx["case"]["id"], "PLAN_ACTIVE", headers)
    plan = get_success_data(api_client.get_goal_plan(ctx["plan"]["id"], headers))
    ctx.update({"case": case, "plan": plan})
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: matched-savings composites
# ---------------------------------------------------------------------------

def create_pool(admin_headers=None, **overrides) -> dict:
    """Create an ACTIVE match pool."""
    headers = admin_headers or _admin()
    resp = api_client.create_match_pool(create_match_pool_payload(**overrides), headers)
    return get_success_data(resp)


def create_enrollment(participant_id, pool_id, goal_plan_id, admin_headers=None, **overrides) -> dict:
    """Enroll a participant against an ACTIVE goal plan."""
    headers = admin_headers or _admin()
    resp = api_client.create_match_enrollment(
        create_match_enrollment_payload(participant_id, pool_id, goal_plan_id, **overrides),
        headers,
    )
    return get_success_data(resp)


def setup_active_enrollment(admin_headers=None, participant_income_cents=2000000,
                            pool_overrides=None, savings_goal_cents=500000,
                            plan_overrides=None):
    """Full chain: certified coach + participant + case at PLAN_ACTIVE with an
    ACTIVE plan + pool + ACTIVE enrollment.

    Returns dict(case, plan, participant, coach, pool, enrollment).
    """
    headers = admin_headers or _admin()
    participant = create_participant(headers, annual_income_cents=participant_income_cents)
    ctx = setup_case_with_active_plan(participant_id=participant["id"],
                                      admin_headers=headers,
                                      plan_overrides=plan_overrides)
    pool = create_pool(headers, **(pool_overrides or {}))
    enrollment = create_enrollment(
        participant["id"], pool["id"], ctx["plan"]["id"], headers,
        savings_goal_cents=savings_goal_cents,
    )
    ctx.update({"pool": pool, "enrollment": enrollment})
    return ctx


def create_deposit_on(enrollment_id, amount_cents, admin_headers=None) -> dict:
    """Record an accepted deposit; returns the refreshed enrollment."""
    headers = admin_headers or _admin()
    resp = api_client.create_deposit(
        enrollment_id, create_deposit_payload(amount_cents), headers
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 4: workshop / registration composites
# ---------------------------------------------------------------------------

def setup_workshop_scenario(admin_headers=None, capacity=10,
                            start_at="2026-08-10T10:00:00Z",
                            end_at="2026-08-10T11:00:00Z",
                            module_overrides=None, coach_overrides=None):
    """Module + certified coach + one SCHEDULED workshop.

    Returns dict(module, coach, workshop).
    """
    headers = admin_headers or _admin()
    module = create_module(headers, **(module_overrides or {}))
    coach = create_certified_coach(headers, **(coach_overrides or {}))
    workshop = create_workshop(
        module["id"], coach["id"], headers,
        start_at=start_at, end_at=end_at, capacity=capacity,
    )
    return {"module": module, "coach": coach, "workshop": workshop}


def setup_full_waitlist_workshop(admin_headers=None, capacity=1, num_waitlisted=1,
                                 start_at="2026-08-10T10:00:00Z",
                                 end_at="2026-08-10T11:00:00Z",
                                 module_overrides=None):
    """Workshop at capacity: `capacity` REGISTERED participants followed by
    `num_waitlisted` WAITLISTED participants.

    Returns dict(module, coach, workshop, registered=[(participant, registration), ...],
                 waitlisted=[(participant, registration), ...]).
    """
    headers = admin_headers or _admin()
    ctx = setup_workshop_scenario(headers, capacity=capacity, start_at=start_at,
                                  end_at=end_at, module_overrides=module_overrides)
    registered = []
    for _ in range(capacity):
        p = create_participant(headers)
        r = create_registration(ctx["workshop"]["id"], p["id"], headers)
        registered.append((p, r))
    waitlisted = []
    for _ in range(num_waitlisted):
        p = create_participant(headers)
        r = create_registration(ctx["workshop"]["id"], p["id"], headers)
        waitlisted.append((p, r))
    ctx.update({"registered": registered, "waitlisted": waitlisted})
    return ctx


# ---------------------------------------------------------------------------
# Tier 5: referrals and misc
# ---------------------------------------------------------------------------

def create_referral_for(participant_id, coach_id, admin_headers=None, **overrides) -> dict:
    """Create a SENT referral."""
    headers = admin_headers or _admin()
    resp = api_client.create_referral(
        create_referral_payload(participant_id, coach_id, **overrides), headers
    )
    return get_success_data(resp)
