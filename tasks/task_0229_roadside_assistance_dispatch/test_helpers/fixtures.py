"""Composite setup helpers for Roadside Assistance Dispatch tests.

Every helper builds its preconditions from scratch using only PRD-declared endpoints,
because the test harness restarts the server (empty DB) before each test. Helpers use
get_success_data() (lenient) internally so setup failures surface as clear
"Setup failed" errors rather than confusing assertion failures.

Identity threading: ServiceCall create/cancel and claim file/resubmit are Member-owned;
offer accept/decline and call start/complete are Provider-owned. The fixtures thread the
owning entity's id through make_member_headers / make_provider_headers — never the shared
TEST_USERS constant — so ownership checks pass.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS, make_member_headers, make_provider_headers
from . import factories as F
from .constants import DEFAULT_CLOCK

OP = TEST_USERS["dispatch_operator_headers"]


# ---------------------------------------------------------------------------
# Tier 0: clock + atomic creators
# ---------------------------------------------------------------------------
def set_clock(instant=DEFAULT_CLOCK):
    """Pin the server clock (PRD §2.10). Returns None (endpoint returns null data)."""
    return get_success_data(api_client.set_clock(instant, OP))


def create_plan(**overrides) -> dict:
    return get_success_data(api_client.create_membership_plan(F.create_membership_plan_payload(**overrides), OP))


def create_member(plan_id=None, **overrides) -> dict:
    if plan_id is None:
        plan_id = create_plan()["id"]
    return get_success_data(api_client.create_member(F.create_member_payload(plan_id, **overrides), OP))


def create_provider(**overrides) -> dict:
    return get_success_data(api_client.create_service_provider(F.create_service_provider_payload(**overrides), OP))


def create_depot(**overrides) -> dict:
    return get_success_data(api_client.create_depot(F.create_depot_payload(**overrides), OP))


def create_shift(provider_id, shift_start, shift_end, **overrides) -> dict:
    return get_success_data(
        api_client.create_shift(provider_id, F.create_shift_payload(shift_start, shift_end, **overrides), OP)
    )


def create_call(member_id, service_type="TOW", **overrides) -> dict:
    """Open a service call as the owning Member (ownership-threaded)."""
    return get_success_data(
        api_client.create_service_call(
            F.create_service_call_payload(member_id, service_type, **overrides),
            make_member_headers(member_id),
        )
    )


def create_offer(call_id, provider_id, expected_version) -> dict:
    """Dispatch an offer (operator-only)."""
    return get_success_data(
        api_client.create_offer(call_id, F.create_offer_payload(provider_id, expected_version), OP)
    )


# ---------------------------------------------------------------------------
# Tier 1: standard plan + member + provider triad
# ---------------------------------------------------------------------------
def setup_plan_member_provider(plan_overrides=None, member_overrides=None, provider_overrides=None,
                               clock=DEFAULT_CLOCK):
    """Pin clock, create a PLUS plan, an ACTIVE member, and an AVAILABLE TOW provider.

    Returns dict {plan, member, provider}.
    """
    if clock is not None:
        set_clock(clock)
    plan = create_plan(**(plan_overrides or {}))
    member = create_member(plan["id"], **(member_overrides or {}))
    provider = create_provider(**(provider_overrides or {}))
    return {"plan": plan, "member": member, "provider": provider}


# ---------------------------------------------------------------------------
# Tier 2: service-call lifecycle shortcuts
# ---------------------------------------------------------------------------
def setup_dispatching_call(plan_overrides=None, member_overrides=None, provider_overrides=None,
                           call_overrides=None, clock=DEFAULT_CLOCK):
    """A DISPATCHING TOW call with a member + an AVAILABLE TOW provider (no offer yet).

    Returns dict {plan, member, provider, call}.
    """
    ctx = setup_plan_member_provider(plan_overrides, member_overrides, provider_overrides, clock)
    ctx["call"] = create_call(ctx["member"]["id"], **(call_overrides or {}))
    return ctx


def setup_call_with_live_offer(plan_overrides=None, provider_overrides=None, call_overrides=None,
                               clock=DEFAULT_CLOCK):
    """A DISPATCHING call with one live OFFERED offer from an AVAILABLE TOW provider.

    Returns dict {plan, member, provider, call, offer}.
    """
    ctx = setup_dispatching_call(plan_overrides, None, provider_overrides, call_overrides, clock)
    ctx["offer"] = create_offer(ctx["call"]["id"], ctx["provider"]["id"], ctx["call"]["version"])
    return ctx


def setup_assigned_call(plan_overrides=None, provider_overrides=None, call_overrides=None,
                        clock=DEFAULT_CLOCK):
    """A call driven to ASSIGNED (offer ACCEPTED, provider ON_JOB).

    Returns dict {plan, member, provider, call, offer}.
    """
    ctx = setup_call_with_live_offer(plan_overrides, provider_overrides, call_overrides, clock)
    pid = ctx["provider"]["id"]
    get_success_data(api_client.accept_offer(ctx["call"]["id"], ctx["offer"]["id"], make_provider_headers(pid)))
    return ctx


def setup_en_route_call(plan_overrides=None, provider_overrides=None, call_overrides=None,
                        clock=DEFAULT_CLOCK):
    """A call driven to EN_ROUTE (assigned provider has started travel).

    Returns dict {plan, member, provider, call, offer}.
    """
    ctx = setup_assigned_call(plan_overrides, provider_overrides, call_overrides, clock)
    pid = ctx["provider"]["id"]
    get_success_data(api_client.start_call(ctx["call"]["id"], make_provider_headers(pid)))
    return ctx


def complete_call(call_id, provider_id, final_towed_miles=None):
    """Complete an EN_ROUTE call as its assigned provider; returns the completed call data."""
    return get_success_data(
        api_client.complete_call(call_id, F.complete_payload(final_towed_miles), make_provider_headers(provider_id))
    )


def setup_completed_call(plan_overrides=None, provider_overrides=None, call_overrides=None,
                         final_towed_miles=20, clock=DEFAULT_CLOCK):
    """A COMPLETED TOW call with cost reconciled.

    Returns dict {plan, member, provider, call, offer, completed} where `completed` is the
    completed-call response data (carries final_cost_cents / member_out_of_pocket_cents).
    """
    ctx = setup_en_route_call(plan_overrides, provider_overrides, call_overrides, clock)
    ctx["completed"] = complete_call(ctx["call"]["id"], ctx["provider"]["id"], final_towed_miles)
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: reimbursement-claim lifecycle shortcuts
# ---------------------------------------------------------------------------
def file_claim(member_id, service_call_id, claimed_amount_cents) -> dict:
    """File a claim as the owning Member (ownership-threaded)."""
    return get_success_data(
        api_client.create_claim(
            F.create_claim_payload(member_id, service_call_id, claimed_amount_cents),
            make_member_headers(member_id),
        )
    )


def setup_claim_under_review(claimed_amount_cents=3000, final_towed_miles=20,
                             plan_overrides=None, clock=DEFAULT_CLOCK):
    """A COMPLETED call + a claim driven to UNDER_REVIEW.

    Returns dict {plan, member, provider, call, completed, claim}.
    """
    ctx = setup_completed_call(plan_overrides=plan_overrides, final_towed_miles=final_towed_miles, clock=clock)
    claim = file_claim(ctx["member"]["id"], ctx["call"]["id"], claimed_amount_cents)
    get_success_data(api_client.begin_review_claim(claim["id"], OP))
    ctx["claim"] = claim
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: dispatch-candidate (eligibility / ranking) setups
# ---------------------------------------------------------------------------
def make_call_for_candidates(service_type="TOW", clock=DEFAULT_CLOCK, plan_overrides=None,
                             call_overrides=None):
    """Pin clock, build plan + member, and open a call at breakdown (0,0) for candidate ranking.

    Returns dict {plan, member, call}.
    """
    if clock is not None:
        set_clock(clock)
    plan = create_plan(**(plan_overrides or {}))
    member = create_member(plan["id"])
    call = create_call(member["id"], service_type, **(call_overrides or {}))
    return {"plan": plan, "member": member, "call": call}


def add_provider_with_shift(current_lat, current_lng, capabilities, rating, company_name,
                            shift_start="2026-06-01T08:00:00Z", shift_end="2026-06-01T20:00:00Z") -> dict:
    """Create an AVAILABLE provider at a location with a SCHEDULED shift covering noon.

    Returns the provider data.
    """
    prov = create_provider(company_name=company_name, current_lat=current_lat, current_lng=current_lng,
                           capabilities=capabilities, rating=rating)
    create_shift(prov["id"], shift_start, shift_end)
    return prov


# ---------------------------------------------------------------------------
# Tier 5: depot / bay-reservation setups
# ---------------------------------------------------------------------------
def setup_depot_with_reservation(bay_count=1, cleanup_buffer_minutes=0,
                                 reserved_from="2026-06-01T10:00:00Z",
                                 reserved_until="2026-06-01T11:00:00Z",
                                 clock="2026-06-01T09:00:00Z", depot_overrides=None):
    """A depot with one ACTIVE bay reservation for a TOW call.

    Returns dict {plan, member, depot, call, reservation}.
    """
    if clock is not None:
        set_clock(clock)
    plan = create_plan()
    member = create_member(plan["id"])
    depot = create_depot(bay_count=bay_count, cleanup_buffer_minutes=cleanup_buffer_minutes,
                         **(depot_overrides or {}))
    call = create_call(member["id"], "TOW")
    reservation = get_success_data(
        api_client.create_bay_reservation(
            depot["id"], F.create_bay_reservation_payload(call["id"], reserved_from, reserved_until), OP
        )
    )
    return {"plan": plan, "member": member, "depot": depot, "call": call, "reservation": reservation}
