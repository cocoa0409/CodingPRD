"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures produce
clear "Setup failed" errors rather than confusing assertion failures.

Identity threading: Client and Chef are entity_backed roles. Every ownership-gated
call routes through make_client_headers(client_id) / make_chef_headers(chef_id) with
the real entity id — never the shared TEST_USERS fallback.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_client_payload, create_chef_payload, create_dietary_plan_payload,
    create_weekly_menu_payload, create_menu_meal_payload, create_cook_session_payload,
    ingredient,
)
from .test_users import TEST_USERS, make_client_headers, make_chef_headers
from .constants import TEST_DEFAULTS

ADMIN = TEST_USERS["admin_headers"]
WEEK_START = TEST_DEFAULTS["WEEK_START_DATE"]


# ─── Primitive creators ───────────────────────────────────────────────

def create_client(**overrides) -> dict:
    """Create a Client (PlatformAdmin action). Returns the client resource."""
    res = api_client.create_client(create_client_payload(**overrides), ADMIN)
    return get_success_data(res)


def create_chef(**overrides) -> dict:
    """Create a Chef (PlatformAdmin action). Returns the chef resource."""
    res = api_client.create_chef(create_chef_payload(**overrides), ADMIN)
    return get_success_data(res)


def create_active_plan(client, expected_client_version=None, **overrides) -> dict:
    """Create a dietary plan owned by `client`. Defaults the OCC version to the
    client's current version."""
    version = client["version"] if expected_client_version is None else expected_client_version
    res = api_client.create_dietary_plan(
        create_dietary_plan_payload(client["id"], version, **overrides),
        make_client_headers(client["id"]),
    )
    return get_success_data(res)


def create_draft_menu(client, chef, plan, week_start_date=WEEK_START, **overrides) -> dict:
    """Chef drafts a weekly menu for `client` against `plan`."""
    res = api_client.create_weekly_menu(
        create_weekly_menu_payload(
            client["id"], plan["id"], chef["id"], week_start_date=week_start_date, **overrides
        ),
        make_chef_headers(chef["id"]),
    )
    return get_success_data(res)


def add_meal(menu, chef, meal_name="Test Meal", meal_slot="DINNER", servings=2,
             ingredients=None, is_perishable=None, required_equipment=None) -> dict:
    """Chef adds a meal to a DRAFT menu."""
    extra = {}
    if is_perishable is not None:
        extra["is_perishable"] = is_perishable
    if required_equipment is not None:
        extra["required_equipment"] = required_equipment
    payload = create_menu_meal_payload(
        menu["id"], meal_name=meal_name, meal_slot=meal_slot,
        servings=servings, ingredients=ingredients, **extra,
    )
    res = api_client.create_menu_meal(payload, make_chef_headers(chef["id"]))
    return get_success_data(res)


def propose(menu, chef) -> dict:
    return get_success_data(api_client.propose_menu(menu["id"], make_chef_headers(chef["id"])))


def approve(menu, client) -> dict:
    return get_success_data(api_client.approve_menu(menu["id"], make_client_headers(client["id"])))


def reject(menu, client) -> dict:
    return get_success_data(api_client.reject_menu(menu["id"], make_client_headers(client["id"])))


def skip(menu, client) -> dict:
    return get_success_data(api_client.skip_menu(menu["id"], make_client_headers(client["id"])))


def resume(menu, client) -> dict:
    return get_success_data(api_client.resume_menu(menu["id"], make_client_headers(client["id"])))


def schedule_session(menu, chef, scheduled_start, scheduled_end) -> dict:
    res = api_client.create_cook_session(
        create_cook_session_payload(menu["id"], chef["id"], scheduled_start, scheduled_end),
        make_chef_headers(chef["id"]),
    )
    return get_success_data(res)


def start_session(session, chef) -> dict:
    return get_success_data(api_client.start_session(session["id"], make_chef_headers(chef["id"])))


def complete_session(session, chef) -> dict:
    return get_success_data(api_client.complete_session(session["id"], make_chef_headers(chef["id"])))


def set_clock(iso: str) -> None:
    get_success_data(api_client.set_clock(iso, ADMIN))


def get_client(client_id) -> dict:
    return get_success_data(api_client.get_client(client_id, ADMIN))


def get_menu(menu_id) -> dict:
    return get_success_data(api_client.get_weekly_menu(menu_id, ADMIN))


def get_meal(meal_id) -> dict:
    return get_success_data(api_client.get_menu_meal(meal_id, ADMIN))


def get_session(session_id) -> dict:
    return get_success_data(api_client.get_cook_session(session_id, ADMIN))


def invoice_for_menu(menu_id) -> dict:
    """Return the single invoice synthesized for `menu_id` (cook cascade)."""
    data, _meta = _list(api_client.list_invoices, ADMIN, {"weekly_menu_id": menu_id})
    assert data, f"Setup failed: no invoice found for menu {menu_id}"
    return data[0]


def containers_for_meal(meal_id) -> list:
    data, _meta = _list(api_client.list_containers, ADMIN, {"menu_meal_id": meal_id})
    return data


def _list(list_fn, headers, params):
    res = list_fn(headers, params=params)
    body = res.json()
    return body.get("data", []), body.get("meta", {})


# ─── Tier 2/3: Composite lifecycle shortcuts ──────────────────────────

def setup_proposed_single_meal(client_kwargs=None, plan_kwargs=None, meal_kwargs=None,
                               week_start_date=WEEK_START):
    """Client + Chef + active plan + DRAFT menu with one meal, then PROPOSE.

    Returns dict(client, chef, plan, menu, meal).
    """
    client = create_client(**(client_kwargs or {}))
    chef = create_chef()
    plan = create_active_plan(client, **(plan_kwargs or {}))
    menu = create_draft_menu(client, chef, plan, week_start_date=week_start_date)
    meal = add_meal(menu, chef, **(meal_kwargs or {}))
    propose(menu, chef)
    menu = get_menu(menu["id"])
    return {"client": client, "chef": chef, "plan": plan, "menu": menu, "meal": meal}


def setup_approved_single_meal(client_kwargs=None, plan_kwargs=None, meal_kwargs=None,
                               week_start_date=WEEK_START):
    """As setup_proposed_single_meal, then APPROVE. Returns dict(...) with the
    approved menu snapshot."""
    ctx = setup_proposed_single_meal(client_kwargs, plan_kwargs, meal_kwargs, week_start_date)
    approve(ctx["menu"], ctx["client"])
    ctx["menu"] = get_menu(ctx["menu"]["id"])
    return ctx


def setup_cooked_single_meal(client_kwargs=None, plan_kwargs=None, meal_kwargs=None,
                             week_start_date=WEEK_START,
                             scheduled_start="2026-03-03T09:00:00Z",
                             scheduled_end="2026-03-03T12:00:00Z",
                             clock_at_start=None, clock_at_complete=None):
    """Full lifecycle through COMPLETED: create -> approve -> schedule -> start ->
    complete, driving the production cascade (menu COOKED, containers, invoice).

    Optional clock_at_start / clock_at_complete advance the logical clock before
    the start / complete calls (used by container use-by and payout tests).

    Returns dict(client, chef, plan, menu, meal, session, invoice).
    """
    ctx = setup_approved_single_meal(client_kwargs, plan_kwargs, meal_kwargs, week_start_date)
    session = schedule_session(ctx["menu"], ctx["chef"], scheduled_start, scheduled_end)
    if clock_at_start is not None:
        set_clock(clock_at_start)
    session = start_session(session, ctx["chef"])
    if clock_at_complete is not None:
        set_clock(clock_at_complete)
    session = complete_session(session, ctx["chef"])
    ctx["session"] = session
    ctx["menu"] = get_menu(ctx["menu"]["id"])
    ctx["invoice"] = invoice_for_menu(ctx["menu"]["id"])
    return ctx


def cook_menu_with_meals(billing_mode, meals, household_size=2, week_start_date=WEEK_START,
                         scheduled_start="2026-03-03T09:00:00Z",
                         scheduled_end="2026-03-03T10:00:00Z", **client_kwargs):
    """Create a client of `billing_mode`, an active plan, a menu with the given
    list of meal specs, approve, and cook it. `meals` is a list of dicts accepted
    by add_meal(). Returns dict(client, chef, plan, menu, meals, session, invoice).
    """
    client = create_client(billing_mode=billing_mode, household_size=household_size,
                           **client_kwargs)
    chef = create_chef()
    plan = create_active_plan(client)
    menu = create_draft_menu(client, chef, plan, week_start_date=week_start_date)
    created = [add_meal(menu, chef, **spec) for spec in meals]
    propose(menu, chef)
    approve(menu, client)
    session = schedule_session(menu, chef, scheduled_start, scheduled_end)
    session = start_session(session, chef)
    session = complete_session(session, chef)
    menu = get_menu(menu["id"])
    return {
        "client": client, "chef": chef, "plan": plan, "menu": menu,
        "meals": created, "session": session, "invoice": invoice_for_menu(menu["id"]),
    }
