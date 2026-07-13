"""Composite setup helpers.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints, because the harness restarts the server (empty DB) before each test.
All setup calls use get_success_data() (lenient) so a broken precondition surfaces
as a clear "Setup failed" rather than a confusing assertion error.

Identity threading: after creating a Client/Coach, ownership-gated calls use
make_client_headers(client_id) / make_coach_headers(coach_id) with the real id.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS, make_client_headers, make_coach_headers
from .factories import (
    create_package_plan_payload,
    create_client_payload,
    create_coach_payload,
    create_order_payload,
    create_session_payload,
    create_revision_payload,
    create_draft_payload,
)

ADMIN = TEST_USERS["admin_headers"]

# A far-future default session window (well past the 2026-03-01 logical clock).
DEFAULT_SESSION_START = "2026-04-01T10:00:00Z"
DEFAULT_SESSION_END = "2026-04-01T11:00:00Z"


# --------------------------------------------------------------------------
# Low-level entity creation
# --------------------------------------------------------------------------
def create_plan(**overrides) -> dict:
    return get_success_data(api_client.create_package_plan(create_package_plan_payload(**overrides), ADMIN))


def create_client_entity(**overrides) -> dict:
    return get_success_data(api_client.create_client(create_client_payload(**overrides), ADMIN))


def create_coach_entity(**overrides) -> dict:
    return get_success_data(api_client.create_coach(create_coach_payload(**overrides), ADMIN))


def create_order_entity(plan_id, client_id, **overrides) -> dict:
    headers = make_client_headers(client_id)
    return get_success_data(api_client.create_order(create_order_payload(plan_id, **overrides), headers))


def order_version(order_id) -> int:
    return get_success_data(api_client.get_order(order_id, ADMIN))["version"]


def get_order_now(order_id) -> dict:
    return get_success_data(api_client.get_order(order_id, ADMIN))


def first_deliverable_id(order_id) -> str:
    deliverables = get_success_data(api_client.list_order_deliverables(order_id, ADMIN))
    return deliverables[0]["id"]


def order_addons(order_id) -> list:
    return get_success_data(api_client.list_order_addons(order_id, ADMIN))


def order_payments(order_id) -> list:
    return get_success_data(api_client.list_order_payments(order_id, ADMIN))


# --------------------------------------------------------------------------
# Order lifecycle
# --------------------------------------------------------------------------
def setup_confirmed_order(plan_overrides=None, order_overrides=None, coach_overrides=None,
                          with_coach=True):
    """Plan + client (+coach) + order, then confirm the order (now IN_PRODUCTION).

    Returns a context dict with entities, ownership-correct headers, and ids.
    """
    plan = create_plan(**(plan_overrides or {}))
    client = create_client_entity(**{"email": "conf-client@example.com"})
    coach = create_coach_entity(**(coach_overrides or {})) if with_coach else None
    client_headers = make_client_headers(client["id"])
    order = create_order_entity(plan["id"], client["id"], **(order_overrides or {}))
    confirmed = get_success_data(api_client.confirm_order(order["id"], client_headers))
    return {
        "plan": plan,
        "client": client,
        "client_id": client["id"],
        "coach": coach,
        "coach_id": coach["id"] if coach else None,
        "order": confirmed,
        "order_id": order["id"],
        "client_headers": client_headers,
        "coach_headers": make_coach_headers(coach["id"]) if coach else None,
    }


def draft(deliverable_id, coach_headers) -> dict:
    return get_success_data(api_client.create_draft(deliverable_id, create_draft_payload(), coach_headers))


def open_revision(deliverable_id, client_headers, reason="Please revise") -> dict:
    return get_success_data(
        api_client.create_revision(deliverable_id, create_revision_payload(reason=reason), client_headers)
    )


def approve(deliverable_id, client_headers) -> dict:
    return get_success_data(api_client.approve_deliverable(deliverable_id, client_headers))


def setup_drafted_deliverable(plan_overrides=None, order_overrides=None):
    """Confirmed order whose first deliverable has been drafted (status DRAFTED).

    Adds keys 'deliverable_id' and 'deliverable' to the confirmed-order context.
    """
    ctx = setup_confirmed_order(plan_overrides=plan_overrides, order_overrides=order_overrides)
    deliv_id = first_deliverable_id(ctx["order_id"])
    drafted = draft(deliv_id, ctx["coach_headers"])
    ctx["deliverable_id"] = deliv_id
    ctx["deliverable"] = drafted
    return ctx


def setup_delivered_order(plan_overrides=None, order_overrides=None):
    """Full lifecycle through DELIVERED for a single-RESUME plan.

    Drafts + approves the one deliverable (order bubbles to READY), then delivers
    it (admin). Returns the confirmed-order context plus 'deliverable_id' and the
    delivered 'order'. delivered_at is stamped at the default logical clock.
    """
    ctx = setup_drafted_deliverable(plan_overrides=plan_overrides, order_overrides=order_overrides)
    approve(ctx["deliverable_id"], ctx["client_headers"])
    delivered = get_success_data(api_client.deliver_order(ctx["order_id"], ADMIN))
    ctx["order"] = delivered
    return ctx


# --------------------------------------------------------------------------
# Sessions
# --------------------------------------------------------------------------
def book_session(order_id, coach_id, client_headers, scheduled_start=DEFAULT_SESSION_START,
                 scheduled_end=DEFAULT_SESSION_END, session_type="COACHING",
                 expected_order_version=None) -> dict:
    """Book one session on a confirmed order, reading the current version if not given."""
    if expected_order_version is None:
        expected_order_version = order_version(order_id)
    payload = create_session_payload(
        coach_id=coach_id,
        scheduled_start=scheduled_start,
        scheduled_end=scheduled_end,
        expected_order_version=expected_order_version,
        session_type=session_type,
    )
    return get_success_data(api_client.create_session(order_id, payload, client_headers))


def setup_order_with_billable_session(plan_overrides=None):
    """Confirmed BASIC order with zero included sessions and one booked billable
    COACHING session (fee 12000). Returns the context plus 'session'."""
    overrides = {
        "tier": "BASIC",
        "base_price_cents": 20000,
        "included_deliverables": ["RESUME"],
        "included_revision_rounds": 1,
        "included_coaching_sessions": 0,
        "guarantee_type": "NONE",
    }
    if plan_overrides:
        overrides.update(plan_overrides)
    ctx = setup_confirmed_order(plan_overrides=overrides)
    ctx["session"] = book_session(ctx["order_id"], ctx["coach_id"], ctx["client_headers"])
    return ctx


def setup_delivered_satisfaction_with_session(session_start="2026-05-01T10:00:00Z",
                                              session_end="2026-05-01T11:00:00Z"):
    """SATISFACTION plan (base 30000) with one included coaching session.

    Confirms (charge 30000), drafts, books one included (free) COACHING session
    for a future slot, approves (order READY), delivers (DELIVERED at default
    clock 2026-03-01), and submits a SATISFACTION claim. Returns context plus
    'session', 'deliverable_id', and 'claim'.
    """
    ctx = setup_drafted_deliverable(plan_overrides={
        "tier": "PRO",
        "base_price_cents": 30000,
        "included_deliverables": ["RESUME"],
        "included_revision_rounds": 1,
        "included_coaching_sessions": 1,
        "guarantee_type": "SATISFACTION",
    })
    ctx["session"] = book_session(
        ctx["order_id"], ctx["coach_id"], ctx["client_headers"],
        scheduled_start=session_start, scheduled_end=session_end,
    )
    approve(ctx["deliverable_id"], ctx["client_headers"])
    get_success_data(api_client.deliver_order(ctx["order_id"], ADMIN))
    claim = get_success_data(api_client.create_guarantee_claim(
        ctx["order_id"], {"claim_type": "SATISFACTION", "evidence": "not satisfied with results"},
        ctx["client_headers"],
    ))
    ctx["claim"] = claim
    ctx["claim_id"] = claim["id"]
    return ctx
