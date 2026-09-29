"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints only, because each test starts against an empty database.

Setup calls use the lenient ``get_success_data`` validator so a broken
precondition surfaces as a clear setup failure rather than a confusing
assertion further down.

Identity threading: an ``Employee`` caller's ``X-User-ID`` is the acting
employee's ``id`` and a ``Restaurant`` caller's ``X-User-ID`` is the acting
restaurant's ``id``, so every ownership-gated call below goes through
``make_employee_headers(employee["id"])`` / ``make_restaurant_headers(
restaurant["id"])`` — never a shared constant.
"""

from types import SimpleNamespace

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    DEFAULT_CLOCK,
    MONDAY_NOON,
    TEST_DEFAULTS,
)
from .factories import (
    create_benefit_period_payload,
    create_budget_rule_payload,
    create_credit_claim_payload,
    create_delivery_location_payload,
    create_employee_group_payload,
    create_employee_payload,
    create_expense_export_payload,
    create_group_order_payload,
    create_meal_program_payload,
    create_order_payload,
    create_restaurant_payload,
    order_line,
)
from .test_users import (
    CONTROLLER_APPROVER_ID,
    CONTROLLER_DRAFTER_ID,
    CONTROLLER_RESOLVER_ID,
    CONTROLLER_SETTLER_ID,
    TEST_USERS,
    make_controller_headers,
    make_employee_headers,
    make_restaurant_headers,
)

PLATFORM = TEST_USERS["platform_admin_headers"]
PROGRAM = TEST_USERS["program_admin_headers"]
DRAFTER = TEST_USERS["controller_drafter_headers"]
APPROVER = TEST_USERS["controller_approver_headers"]
RESOLVER = TEST_USERS["controller_resolver_headers"]
SETTLER = TEST_USERS["controller_settler_headers"]


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
def set_clock(now: str) -> dict:
    """Set the logical UTC clock every temporal rule reads."""
    return get_success_data(api_client.set_clock({"now": now}, PLATFORM))


def reset_clock() -> dict:
    return set_clock(DEFAULT_CLOCK)


# ---------------------------------------------------------------------------
# Tier 1 / Tier 2 — single-row creation and reads
# ---------------------------------------------------------------------------
def create_program(**overrides) -> dict:
    return get_success_data(
        api_client.create_meal_program(create_meal_program_payload(**overrides), PLATFORM)
    )


def read_program(program_id: str) -> dict:
    return get_success_data(api_client.get_meal_program(program_id, PLATFORM))


def create_group(program_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_employee_group(
            program_id, create_employee_group_payload(**overrides), PROGRAM
        )
    )


def read_group(group_id: str) -> dict:
    return get_success_data(api_client.get_employee_group(group_id, PROGRAM))


def draft_rule(group_id: str, drafter_id: str = CONTROLLER_DRAFTER_ID, **overrides) -> dict:
    return get_success_data(
        api_client.create_budget_rule(
            group_id,
            create_budget_rule_payload(**overrides),
            make_controller_headers(drafter_id),
        )
    )


def activate_rule(
    rule_id: str,
    group_id: str,
    activator_id: str = CONTROLLER_APPROVER_ID,
    expected_employee_group_version: int = None,
) -> dict:
    """Activate a drafted rule, reading the owning group's current version
    unless the caller pins one explicitly."""
    if expected_employee_group_version is None:
        expected_employee_group_version = read_group(group_id)["version"]
    return get_success_data(
        api_client.activate_budget_rule(
            rule_id,
            {"expected_employee_group_version": expected_employee_group_version},
            make_controller_headers(activator_id),
        )
    )


def create_active_rule(
    group_id: str,
    drafter_id: str = CONTROLLER_DRAFTER_ID,
    activator_id: str = CONTROLLER_APPROVER_ID,
    **rule_overrides,
) -> dict:
    """Draft then four-eyes activate a budget rule. Returns the ACTIVE rule."""
    rule = draft_rule(group_id, drafter_id=drafter_id, **rule_overrides)
    return activate_rule(rule["id"], group_id, activator_id=activator_id)


def create_location(program_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_delivery_location(
            program_id, create_delivery_location_payload(**overrides), PROGRAM
        )
    )


def create_restaurant(**overrides) -> dict:
    return get_success_data(
        api_client.create_restaurant(create_restaurant_payload(**overrides), PLATFORM)
    )


def suspend_restaurant(restaurant_id: str) -> dict:
    return get_success_data(
        api_client.patch_restaurant(restaurant_id, {"status": "SUSPENDED"}, PLATFORM)
    )


def reinstate_restaurant(restaurant_id: str) -> dict:
    return get_success_data(
        api_client.patch_restaurant(restaurant_id, {"status": "ELIGIBLE"}, PLATFORM)
    )


def create_employee(program_id: str, group_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_employee(
            create_employee_payload(program_id, group_id, **overrides), PROGRAM
        )
    )


def read_employee(employee_id: str) -> dict:
    return get_success_data(api_client.get_employee(employee_id, PROGRAM))


def open_period(employee_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_benefit_period(
            create_benefit_period_payload(employee_id, **overrides), PROGRAM
        )
    )


def read_period(period_id: str) -> dict:
    return get_success_data(api_client.get_benefit_period(period_id, PROGRAM))


def read_order(order_id: str) -> dict:
    return get_success_data(api_client.get_order(order_id, PROGRAM))


def read_claim(claim_id: str) -> dict:
    return get_success_data(api_client.get_credit_claim(claim_id, PROGRAM))


def read_group_order(group_order_id: str) -> dict:
    return get_success_data(api_client.get_group_order(group_order_id, PROGRAM))


def read_imputed_records(employee_id: str, **params) -> list:
    resp = api_client.list_imputed_income_records(
        employee_id, PROGRAM, params=params or None
    )
    body = resp.json()
    return body["data"]


def read_order_refund_entries(order_id: str, **params) -> list:
    resp = api_client.list_order_refund_entries(order_id, PROGRAM, params=params or None)
    return resp.json()["data"]


def read_claim_refund_entries(claim_id: str, **params) -> list:
    resp = api_client.list_claim_refund_entries(claim_id, PROGRAM, params=params or None)
    return resp.json()["data"]


# ---------------------------------------------------------------------------
# Tier 3 — order lifecycle shortcuts
# ---------------------------------------------------------------------------
def draft_order(
    employee: dict,
    period: dict,
    restaurant: dict,
    location: dict,
    **overrides,
) -> dict:
    payload = create_order_payload(
        employee["id"], period["id"], restaurant["id"], location["id"], **overrides
    )
    return get_success_data(
        api_client.create_order(payload, make_employee_headers(employee["id"]))
    )


def place_order_raw(order: dict, employee: dict, expected_version: int = None):
    """Place an order, reading the period's live version unless one is pinned.
    Returns the raw response so a test can assert a rejection."""
    if expected_version is None:
        expected_version = read_period(order["benefit_period_id"])["version"]
    return api_client.place_order(
        order["id"],
        {"expected_benefit_period_version": expected_version},
        make_employee_headers(employee["id"]),
    )


def place_order(order: dict, employee: dict, expected_version: int = None) -> dict:
    return get_success_data(place_order_raw(order, employee, expected_version))


def confirm_order(order: dict, restaurant: dict) -> dict:
    return get_success_data(
        api_client.confirm_order(order["id"], make_restaurant_headers(restaurant["id"]))
    )


def deliver_order(order: dict, restaurant: dict) -> dict:
    return get_success_data(
        api_client.deliver_order(order["id"], make_restaurant_headers(restaurant["id"]))
    )


def cancel_order_as_employee(order: dict, employee: dict) -> dict:
    return get_success_data(
        api_client.cancel_order(order["id"], make_employee_headers(employee["id"]))
    )


def final_close(period_id: str) -> dict:
    return get_success_data(
        api_client.close_benefit_period(period_id, {"mode": "FINAL"}, PROGRAM)
    )


def grace_close(period_id: str) -> dict:
    return get_success_data(
        api_client.close_benefit_period(period_id, {"mode": "GRACE"}, PROGRAM)
    )


# ---------------------------------------------------------------------------
# Tier 2 — the shared program backbone
# ---------------------------------------------------------------------------
def setup_program_base(
    clock: str = DEFAULT_CLOCK,
    program_overrides: dict = None,
    group_overrides: dict = None,
    rule_overrides: dict = None,
    location_overrides: dict = None,
    restaurant_overrides: dict = None,
) -> SimpleNamespace:
    """Clock + program + employee group + ACTIVE budget rule + dock + restaurant.

    The dock sits at the grid origin and the restaurant at (3, 4), i.e. exactly
    5 km away, comfortably inside both the program's 8 km default ceiling and
    the restaurant's own 10 km radius.
    """
    set_clock(clock)
    program = create_program(**(program_overrides or {}))
    group = create_group(program["id"], **(group_overrides or {}))
    rule = create_active_rule(group["id"], **(rule_overrides or {}))
    location = create_location(program["id"], **(location_overrides or {}))
    restaurant = create_restaurant(**(restaurant_overrides or {}))
    return SimpleNamespace(
        program=program,
        group=group,
        rule=rule,
        location=location,
        restaurant=restaurant,
    )


def add_employee_with_period(
    ns: SimpleNamespace,
    employee_overrides: dict = None,
    period_overrides: dict = None,
):
    """Enrol one employee under ``ns.group`` and open them a benefit period."""
    employee = create_employee(
        ns.program["id"], ns.group["id"], **(employee_overrides or {})
    )
    period = open_period(employee["id"], **(period_overrides or {}))
    return employee, period


def setup_scenario(
    clock: str = DEFAULT_CLOCK,
    program_overrides: dict = None,
    group_overrides: dict = None,
    rule_overrides: dict = None,
    location_overrides: dict = None,
    restaurant_overrides: dict = None,
    employee_overrides: dict = None,
    period_overrides: dict = None,
) -> SimpleNamespace:
    """The most common setup: program backbone plus one enrolled employee with
    an OPEN benefit period. Returns a namespace with ``program``, ``group``,
    ``rule``, ``location``, ``restaurant``, ``employee`` and ``period``."""
    ns = setup_program_base(
        clock=clock,
        program_overrides=program_overrides,
        group_overrides=group_overrides,
        rule_overrides=rule_overrides,
        location_overrides=location_overrides,
        restaurant_overrides=restaurant_overrides,
    )
    ns.employee, ns.period = add_employee_with_period(
        ns, employee_overrides, period_overrides
    )
    return ns


# ---------------------------------------------------------------------------
# Tier 3 — full-lifecycle order shortcuts
# ---------------------------------------------------------------------------
def setup_drafted_order(order_overrides: dict = None, **scenario_kwargs) -> SimpleNamespace:
    ns = setup_scenario(**scenario_kwargs)
    ns.order = draft_order(
        ns.employee, ns.period, ns.restaurant, ns.location, **(order_overrides or {})
    )
    return ns


def setup_placed_order(order_overrides: dict = None, **scenario_kwargs) -> SimpleNamespace:
    """Draft + place. The default single 1,000-cent line prices to a covered
    base of 1,787 cents, fully inside the 2,500-cent per-meal cap."""
    ns = setup_drafted_order(order_overrides=order_overrides, **scenario_kwargs)
    ns.order = place_order(ns.order, ns.employee)
    return ns


def setup_confirmed_order(
    order_overrides: dict = None, **scenario_kwargs
) -> SimpleNamespace:
    ns = setup_placed_order(order_overrides=order_overrides, **scenario_kwargs)
    ns.order = confirm_order(ns.order, ns.restaurant)
    return ns


def setup_delivered_order(
    order_overrides: dict = None, **scenario_kwargs
) -> SimpleNamespace:
    ns = setup_confirmed_order(order_overrides=order_overrides, **scenario_kwargs)
    ns.order = deliver_order(ns.order, ns.restaurant)
    return ns


# Pre-priced line sets used by the money-pipeline tests.
LINES_1000 = [order_line("Pad Thai", 1000, 1)]
LINES_THREE_1000 = [
    order_line("Pad Thai", 1000, 1),
    order_line("Green Curry", 1000, 1),
    order_line("Massaman", 1000, 1),
]
LINES_TWO_2000 = [
    order_line("Bento Deluxe", 2000, 1),
    order_line("Bento Classic", 2000, 1),
]
LINES_FOUR_1500 = [
    order_line("Bowl A", 1500, 1),
    order_line("Bowl B", 1500, 1),
    order_line("Bowl C", 1500, 1),
    order_line("Bowl D", 1500, 1),
]


def setup_overage_order(**scenario_kwargs) -> SimpleNamespace:
    """A delivered-ready order that overruns the 2,500-cent cap: three
    1,000-cent lines plus a 200-cent tip price to a covered base of 4,163, an
    employer share of 2,500, an employee card share of 1,863 and a gross total
    of 4,363."""
    kwargs = dict(scenario_kwargs)
    kwargs.setdefault(
        "order_overrides", {"lines": LINES_THREE_1000, "tip_cents": 200}
    )
    return setup_placed_order(**kwargs)


# ---------------------------------------------------------------------------
# Tier 4 — accumulation / threshold targeting
# ---------------------------------------------------------------------------
def setup_program_at_admin_tier_boundary() -> SimpleNamespace:
    """Drive the program's month-to-date captured figure to exactly 100,000
    cents by delivering one order whose covered base is exactly 100,000.

    A single 91,609-cent line taxes to 8,016, earns free delivery and a
    service fee of 375 after the 25 percent volume discount, so the covered
    base is 91,609 + 8,016 + 0 + 375 = 100,000. Returns the namespace with
    ``big_order`` delivered.
    """
    ns = setup_scenario(
        rule_overrides={
            "per_meal_cap_cents": 200_000,
            "monthly_allocation_cents": 500_000,
            "daily_meal_limit": 5,
        },
    )
    ns.big_order = draft_order(
        ns.employee,
        ns.period,
        ns.restaurant,
        ns.location,
        lines=[order_line("Banquet Platter", 91_609, 1)],
    )
    ns.big_order = place_order(ns.big_order, ns.employee)
    ns.big_order = confirm_order(ns.big_order, ns.restaurant)
    ns.big_order = deliver_order(ns.big_order, ns.restaurant)
    return ns


def setup_forecast_scenario(clock: str = DEFAULT_CLOCK) -> SimpleNamespace:
    """One participating group of two planned heads with a daily limit of 1, a
    2,500-cent cap, weekdays Monday to Friday and a 50,000-cent allocation,
    with the program's spend driven to exactly 2,500 cents by one delivered
    order (two 2,000-cent lines price to a covered base of 4,750, capped to an
    employer share of 2,500)."""
    ns = setup_scenario(clock=clock, group_overrides={"headcount_planned": 2})
    ns.order = draft_order(
        ns.employee, ns.period, ns.restaurant, ns.location, lines=LINES_TWO_2000
    )
    ns.order = place_order(ns.order, ns.employee)
    ns.order = confirm_order(ns.order, ns.restaurant)
    ns.order = deliver_order(ns.order, ns.restaurant)
    return ns


def setup_locked_tax_month(**scenario_kwargs) -> SimpleNamespace:
    """Deliver an order and then finally close its period, which cascades the
    month's imputed-income record ACCRUING -> LOCKED."""
    ns = setup_delivered_order(**scenario_kwargs)
    ns.period = final_close(ns.period["id"])
    return ns


def setup_closed_period_with_rollover(**scenario_kwargs) -> SimpleNamespace:
    """An untouched 50,000-cent allocation closed FINAL under the default
    25 percent cap: rollover_out_cents 12,500 and forfeited_cents 37,500."""
    ns = setup_scenario(**scenario_kwargs)
    ns.closed_period = final_close(ns.period["id"])
    return ns


# ---------------------------------------------------------------------------
# Tier 5 — claims, settlement and terminal states
# ---------------------------------------------------------------------------
def raise_claim(order: dict, employee: dict, **overrides) -> dict:
    return get_success_data(
        api_client.create_credit_claim(
            create_credit_claim_payload(order["id"], **overrides),
            make_employee_headers(employee["id"]),
        )
    )


def resolve_claim(
    claim: dict,
    order_id: str,
    resolver_id: str = CONTROLLER_RESOLVER_ID,
    expected_order_version: int = None,
    **overrides,
) -> dict:
    if expected_order_version is None:
        expected_order_version = read_order(order_id)["version"]
    payload = {
        "decision": "APPROVE",
        "expected_order_version": expected_order_version,
        "approved_cents": claim["claimed_cents"],
        "routing_basis": "EMPLOYEE_FIRST",
    }
    payload.update(overrides)
    if payload["decision"] == "DENY":
        payload.pop("approved_cents", None)
        payload.pop("routing_basis", None)
    return get_success_data(
        api_client.resolve_credit_claim(
            claim["id"], payload, make_controller_headers(resolver_id)
        )
    )


def settle_claim(claim: dict, settler_id: str = CONTROLLER_SETTLER_ID) -> dict:
    return get_success_data(
        api_client.settle_credit_claim(claim["id"], make_controller_headers(settler_id))
    )


def setup_submitted_claim(
    claim_overrides: dict = None, order_overrides: dict = None, **scenario_kwargs
) -> SimpleNamespace:
    """Delivered order plus one SUBMITTED credit claim against it."""
    ns = setup_delivered_order(order_overrides=order_overrides, **scenario_kwargs)
    ns.claim = raise_claim(ns.order, ns.employee, **(claim_overrides or {}))
    return ns


def setup_resolved_claim(
    routing_basis: str = "EMPLOYEE_FIRST",
    approved_cents: int = None,
    claim_overrides: dict = None,
    order_overrides: dict = None,
    **scenario_kwargs,
) -> SimpleNamespace:
    ns = setup_submitted_claim(
        claim_overrides=claim_overrides, order_overrides=order_overrides, **scenario_kwargs
    )
    ns.claim = resolve_claim(
        ns.claim,
        ns.order["id"],
        routing_basis=routing_basis,
        approved_cents=approved_cents or ns.claim["claimed_cents"],
    )
    return ns


def setup_settled_claim(
    routing_basis: str = "EMPLOYEE_FIRST",
    approved_cents: int = None,
    claim_overrides: dict = None,
    order_overrides: dict = None,
    **scenario_kwargs,
) -> SimpleNamespace:
    ns = setup_resolved_claim(
        routing_basis=routing_basis,
        approved_cents=approved_cents,
        claim_overrides=claim_overrides,
        order_overrides=order_overrides,
        **scenario_kwargs,
    )
    ns.claim = settle_claim(ns.claim)
    ns.order = read_order(ns.order["id"])
    return ns


# ---------------------------------------------------------------------------
# Group order coordination
# ---------------------------------------------------------------------------
def create_group_order(ns: SimpleNamespace, organizer: dict, **overrides) -> dict:
    payload = create_group_order_payload(
        ns.program["id"],
        organizer["id"],
        ns.restaurant["id"],
        ns.location["id"],
        **overrides,
    )
    return get_success_data(
        api_client.create_group_order(payload, make_employee_headers(organizer["id"]))
    )


def add_member_order(
    ns: SimpleNamespace,
    employee: dict,
    period: dict,
    group_order: dict,
    place: bool = True,
    **order_overrides,
) -> dict:
    overrides = dict(order_overrides)
    overrides.setdefault("group_order_id", group_order["id"])
    order = draft_order(employee, period, ns.restaurant, ns.location, **overrides)
    if place:
        order = place_order(order, employee)
    return order


def setup_group_order_with_members(
    member_count: int = 3,
    place_members: bool = True,
    group_order_overrides: dict = None,
    member_line_sets: list = None,
    **scenario_kwargs,
) -> SimpleNamespace:
    """One group order plus ``member_count`` distinct employees, each with
    their own benefit period and one attached member order.

    The logical clock is nudged forward one minute between member creations so
    the member rows have strictly increasing ``created_at`` values — the
    primary key of the group delivery fee remainder waterfall — while staying
    strictly before the 11:30 cutoff.
    """
    ns = setup_scenario(**scenario_kwargs)
    ns.group_order = create_group_order(
        ns, ns.employee, **(group_order_overrides or {})
    )
    ns.members = []
    ns.member_orders = []
    ns.member_periods = []

    names = [
        ("Ada Lovelace", "ada@acme.test"),
        ("Ben Barnes", "ben@acme.test"),
        ("Cleo Chen", "cleo@acme.test"),
        ("Dan Diaz", "dan@acme.test"),
        ("Eve Evans", "eve@acme.test"),
    ]
    for index in range(member_count):
        set_clock(f"2026-08-01T00:0{index}:00Z")
        if index == 0:
            employee, period = ns.employee, ns.period
        else:
            full_name, email = names[index]
            employee, period = add_employee_with_period(
                ns, employee_overrides={"full_name": full_name, "email": email}
            )
        lines = (member_line_sets or [None] * member_count)[index]
        extra = {"lines": lines} if lines else {}
        order = add_member_order(
            ns, employee, period, ns.group_order, place=place_members, **extra
        )
        ns.members.append(employee)
        ns.member_periods.append(period)
        ns.member_orders.append(order)

    ns.group_order = read_group_order(ns.group_order["id"])
    return ns


def lock_group_order(group_order: dict, organizer: dict) -> dict:
    return get_success_data(
        api_client.lock_group_order(
            group_order["id"], make_employee_headers(organizer["id"])
        )
    )


def reopen_group_order(group_order: dict, organizer: dict) -> dict:
    return get_success_data(
        api_client.reopen_group_order(
            group_order["id"], make_employee_headers(organizer["id"])
        )
    )


def submit_group_order(group_order: dict, organizer: dict) -> dict:
    return get_success_data(
        api_client.submit_group_order(
            group_order["id"], make_employee_headers(organizer["id"])
        )
    )


def setup_submitted_group_order(
    member_count: int = 1, group_order_overrides: dict = None, **scenario_kwargs
) -> SimpleNamespace:
    """A group order taken all the way to SUBMITTED, with the consolidated
    1,250-cent delivery fee allocated across its member orders."""
    ns = setup_group_order_with_members(
        member_count=member_count,
        group_order_overrides=group_order_overrides,
        **scenario_kwargs,
    )
    ns.group_order = lock_group_order(ns.group_order, ns.employee)
    ns.group_order = submit_group_order(ns.group_order, ns.employee)
    ns.member_orders = [read_order(o["id"]) for o in ns.member_orders]
    return ns


def occupy_dock(
    ns: SimpleNamespace,
    window_start: str,
    window_end: str,
    cutoff_at: str = "2026-08-03T10:00:00Z",
    organizer: dict = None,
    period: dict = None,
) -> dict:
    """Submit one group order (with one member) so its dock window and
    restaurant capacity are already occupied. Returns the SUBMITTED row."""
    organizer = organizer or ns.employee
    period = period or ns.period
    group_order = create_group_order(
        ns,
        organizer,
        cutoff_at=cutoff_at,
        window_start=window_start,
        window_end=window_end,
    )
    add_member_order(ns, organizer, period, group_order, place=True)
    lock_group_order(group_order, organizer)
    return submit_group_order(group_order, organizer)


# ---------------------------------------------------------------------------
# Expense exports
# ---------------------------------------------------------------------------
def generate_export(program_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_expense_export(
            program_id, create_expense_export_payload(**overrides), DRAFTER
        )
    )


def acknowledge_export(export_id: str) -> dict:
    return get_success_data(api_client.acknowledge_expense_export(export_id, DRAFTER))
