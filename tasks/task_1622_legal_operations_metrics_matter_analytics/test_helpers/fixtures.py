"""Composite setup helpers for multi-step test prerequisites.

Most claims require the system to be in a state that takes 5-15 API calls to
reach (department -> fiscal period -> taxonomy -> roster -> matter ->
assignment -> activation -> invoices ...). These helpers encapsulate those
chains so tests can focus on assertions. Setup calls use get_success_data()
so a setup failure reports a clear "Setup step failed" message.

The runner restarts the server before every test, so every helper builds its
preconditions from scratch using only PRD-declared endpoints.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_department_payload,
    create_fiscal_period_payload,
    create_practice_area_payload,
    create_matter_type_payload,
    create_firm_payload,
    create_counsel_payload,
    create_matter_payload,
    create_assignment_payload,
    create_budget_payload,
    create_accrual_payload,
    create_invoice_payload,
    create_dashboard_payload,
)
from .test_users import TEST_USERS

MANAGER = TEST_USERS["manager_headers"]
ANALYST = TEST_USERS["analyst_headers"]
# Default approver is a DIFFERENT operator id than the default invoice creator,
# so invoices at or above the SOD threshold are never accidentally self-approved.
APPROVER = TEST_USERS["analyst_2_headers"]
EXECUTIVE = TEST_USERS["executive_headers"]


# ---------------------------------------------------------------------------
# Single-resource creators (thin wrappers returning validated data)
# ---------------------------------------------------------------------------

def create_department(**overrides) -> dict:
    res = api_client.create_department(create_department_payload(**overrides), MANAGER)
    return get_success_data(res)


def create_fiscal_period(**overrides) -> dict:
    res = api_client.create_fiscal_period(create_fiscal_period_payload(**overrides), MANAGER)
    return get_success_data(res)


def create_practice_area(**overrides) -> dict:
    res = api_client.create_practice_area(create_practice_area_payload(**overrides), MANAGER)
    return get_success_data(res)


def create_matter_type(practice_area_id: str, **overrides) -> dict:
    res = api_client.create_matter_type(
        practice_area_id, create_matter_type_payload(**overrides), MANAGER
    )
    return get_success_data(res)


def create_firm(**overrides) -> dict:
    res = api_client.create_firm(create_firm_payload(**overrides), MANAGER)
    return get_success_data(res)


def create_counsel(**overrides) -> dict:
    res = api_client.create_counsel(create_counsel_payload(**overrides), MANAGER)
    return get_success_data(res)


def create_matter(
    practice_area_id: str,
    matter_type_id: str,
    fiscal_period_id: str,
    lead_counsel_id: str,
    **overrides,
) -> dict:
    payload = create_matter_payload(
        practice_area_id, matter_type_id, fiscal_period_id, lead_counsel_id, **overrides
    )
    res = api_client.create_matter(payload, ANALYST)
    return get_success_data(res)


def create_assignment(matter_id: str, counsel_id: str, allocated_hours: int = 5) -> dict:
    res = api_client.create_assignment(
        matter_id, create_assignment_payload(counsel_id, allocated_hours), ANALYST
    )
    return get_success_data(res)


def create_budget(
    fiscal_period_id: str,
    practice_area_id: str,
    allocated_cents: int,
    matter_type_id=None,
) -> dict:
    res = api_client.create_budget(
        create_budget_payload(fiscal_period_id, practice_area_id, allocated_cents, matter_type_id),
        MANAGER,
    )
    return get_success_data(res)


def create_accrual(matter_id: str, fiscal_period_id: str, firm_id: str, amount_cents: int) -> dict:
    res = api_client.create_accrual(
        create_accrual_payload(matter_id, fiscal_period_id, firm_id, amount_cents), ANALYST
    )
    return get_success_data(res)


def create_invoice(
    matter_id: str,
    firm_id: str,
    fiscal_period_id: str,
    amount_cents: int,
    invoice_number: str = None,
    creator_headers=None,
) -> dict:
    res = api_client.create_invoice(
        create_invoice_payload(matter_id, firm_id, fiscal_period_id, amount_cents, invoice_number),
        creator_headers or ANALYST,
    )
    return get_success_data(res)


def create_dashboard(fiscal_period_id: str, snapshot_label: str = None) -> dict:
    res = api_client.create_dashboard(
        create_dashboard_payload(fiscal_period_id, snapshot_label), ANALYST
    )
    return get_success_data(res)


# ---------------------------------------------------------------------------
# Tier 1: State progression shortcuts
# ---------------------------------------------------------------------------

def soft_close_period(fiscal_period_id: str) -> dict:
    """OPEN/REOPENED -> SOFT_CLOSED (analyst action; runs the accrual sweep)."""
    return get_success_data(api_client.soft_close_fiscal_period(fiscal_period_id, ANALYST))


def hard_close_period(fiscal_period_id: str) -> dict:
    """SOFT_CLOSED -> HARD_CLOSED (manager action)."""
    return get_success_data(api_client.hard_close_fiscal_period(fiscal_period_id, MANAGER))


def reopen_period(fiscal_period_id: str) -> dict:
    """HARD_CLOSED -> REOPENED (manager action; increments reopen_count)."""
    return get_success_data(api_client.reopen_fiscal_period(fiscal_period_id, MANAGER))


def activate_matter(matter_id: str) -> dict:
    return get_success_data(api_client.activate_matter(matter_id, ANALYST))


def close_matter(matter_id: str) -> dict:
    """Close a matter using its currently observed version (OCC field)."""
    current = get_success_data(api_client.get_matter(matter_id, ANALYST))
    return get_success_data(
        api_client.close_matter(
            matter_id, {"expected_matter_version": current["version"]}, ANALYST
        )
    )


def approve_invoice(invoice_id: str, approver_headers=None) -> dict:
    """Approve with a distinct operator id by default (SOD-safe)."""
    return get_success_data(
        api_client.approve_invoice(invoice_id, approver_headers or APPROVER)
    )


def pay_invoice(invoice_id: str) -> dict:
    return get_success_data(api_client.pay_invoice(invoice_id, MANAGER))


def create_paid_invoice(
    matter_id: str,
    firm_id: str,
    fiscal_period_id: str,
    amount_cents: int,
    invoice_number: str = None,
) -> dict:
    """Submit -> approve -> pay an invoice. Returns the PAID invoice."""
    inv = create_invoice(matter_id, firm_id, fiscal_period_id, amount_cents, invoice_number)
    approve_invoice(inv["id"])
    return pay_invoice(inv["id"])


def publish_dashboard(dashboard_id: str) -> dict:
    """Publish a dashboard using its currently observed version (OCC field)."""
    current = get_success_data(api_client.get_dashboard(dashboard_id, MANAGER))
    return get_success_data(
        api_client.publish_dashboard(
            dashboard_id, {"expected_dashboard_version": current["version"]}, MANAGER
        )
    )


# ---------------------------------------------------------------------------
# Tier 2: Entity hierarchy — the standard matter graph
# ---------------------------------------------------------------------------

def setup_taxonomy(
    dept_overrides=None,
    period_overrides=None,
    pa_overrides=None,
    mt_overrides=None,
) -> dict:
    """Department + fiscal period (OPEN) + practice area + matter type."""
    graph = {
        "department": create_department(**(dept_overrides or {})),
        "fiscal_period": create_fiscal_period(**(period_overrides or {})),
    }
    graph["practice_area"] = create_practice_area(**(pa_overrides or {}))
    graph["matter_type"] = create_matter_type(
        graph["practice_area"]["id"], **(mt_overrides or {})
    )
    return graph


def setup_matter_graph(
    dept_overrides=None,
    period_overrides=None,
    pa_overrides=None,
    mt_overrides=None,
    firm_overrides=None,
    counsel_overrides=None,
    matter_overrides=None,
    with_firm: bool = True,
    assignment_hours: int = 5,
    activate: bool = True,
) -> dict:
    """Full standard graph: taxonomy + firm + counsel + matter (+ assignment, + ACTIVE).

    Returns a dict with keys: department, fiscal_period, practice_area,
    matter_type, firm (or None), counsel, matter, assignment (or None).
    """
    graph = setup_taxonomy(dept_overrides, period_overrides, pa_overrides, mt_overrides)
    graph["firm"] = create_firm(**(firm_overrides or {})) if with_firm else None
    graph["counsel"] = create_counsel(**(counsel_overrides or {}))

    mo = dict(matter_overrides or {})
    if with_firm and "primary_firm_id" not in mo:
        mo["primary_firm_id"] = graph["firm"]["id"]
    graph["matter"] = create_matter(
        graph["practice_area"]["id"],
        graph["matter_type"]["id"],
        graph["fiscal_period"]["id"],
        graph["counsel"]["id"],
        **mo,
    )
    graph["assignment"] = None
    if assignment_hours is not None:
        graph["assignment"] = create_assignment(
            graph["matter"]["id"], graph["counsel"]["id"], assignment_hours
        )
    if activate:
        graph["matter"] = activate_matter(graph["matter"]["id"])
    return graph


def create_active_matter(graph: dict, allocated_hours: int = 5, **matter_overrides) -> dict:
    """Add another ACTIVE matter to an existing graph (fresh matter_number)."""
    mo = dict(matter_overrides)
    if graph.get("firm") and "primary_firm_id" not in mo:
        mo["primary_firm_id"] = graph["firm"]["id"]
    matter = create_matter(
        graph["practice_area"]["id"],
        graph["matter_type"]["id"],
        graph["fiscal_period"]["id"],
        graph["counsel"]["id"],
        **mo,
    )
    if allocated_hours is not None:
        create_assignment(matter["id"], graph["counsel"]["id"], allocated_hours)
    return activate_matter(matter["id"])


# ---------------------------------------------------------------------------
# Tier 3: Period lifecycle composites
# ---------------------------------------------------------------------------

def setup_soft_closed_period(**taxonomy_kwargs) -> dict:
    """Taxonomy graph whose fiscal period has been soft-closed (OPEN -> SOFT_CLOSED)."""
    graph = setup_taxonomy(**taxonomy_kwargs)
    graph["fiscal_period"] = soft_close_period(graph["fiscal_period"]["id"])
    return graph


def setup_hard_closed_period(**taxonomy_kwargs) -> dict:
    """Taxonomy graph whose fiscal period is HARD_CLOSED (no invoices/dashboards)."""
    graph = setup_soft_closed_period(**taxonomy_kwargs)
    graph["fiscal_period"] = hard_close_period(graph["fiscal_period"]["id"])
    return graph


def setup_reopened_period(**taxonomy_kwargs) -> dict:
    """Taxonomy graph whose fiscal period went OPEN -> SOFT -> HARD -> REOPENED once."""
    graph = setup_hard_closed_period(**taxonomy_kwargs)
    graph["fiscal_period"] = reopen_period(graph["fiscal_period"]["id"])
    return graph


# ---------------------------------------------------------------------------
# Tier 4: Accumulation / threshold targeting
# ---------------------------------------------------------------------------

def setup_budget_with_consumed(
    consumed_cents: int,
    allocated_cents: int,
    dept_overrides=None,
) -> dict:
    """Graph + budget + ACTIVE matter with exactly `consumed_cents` PAID spend.

    Pays a single invoice of `consumed_cents` (must be > 0 and within the
    fixed overrun allowance of ten percent past `allocated_cents`).
    Returns the graph dict extended with keys: budget, invoice.
    """
    graph = setup_matter_graph(dept_overrides=dept_overrides)
    graph["budget"] = create_budget(
        graph["fiscal_period"]["id"],
        graph["practice_area"]["id"],
        allocated_cents,
        matter_type_id=graph["matter_type"]["id"],
    )
    graph["invoice"] = None
    if consumed_cents > 0:
        graph["invoice"] = create_paid_invoice(
            graph["matter"]["id"],
            graph["firm"]["id"],
            graph["fiscal_period"]["id"],
            consumed_cents,
        )
    return graph


def pay_invoice_amounts(graph: dict, amounts: list) -> list:
    """Pay a sequence of invoice amounts against the graph's matter/firm/period.

    Returns the list of PAID invoices in pay order.
    """
    paid = []
    for amount in amounts:
        paid.append(
            create_paid_invoice(
                graph["matter"]["id"],
                graph["firm"]["id"],
                graph["fiscal_period"]["id"],
                amount,
            )
        )
    return paid


# ---------------------------------------------------------------------------
# Tier 5: Terminal state composites
# ---------------------------------------------------------------------------

def setup_archived_matter() -> dict:
    """Full lifecycle: matter ACTIVE -> CLOSED, period HARD_CLOSED, matter ARCHIVED."""
    graph = setup_matter_graph()
    graph["matter"] = close_matter(graph["matter"]["id"])
    graph["fiscal_period"] = soft_close_period(graph["fiscal_period"]["id"])
    graph["fiscal_period"] = hard_close_period(graph["fiscal_period"]["id"])
    get_success_data(api_client.archive_matter(graph["matter"]["id"], MANAGER))
    graph["matter"] = get_success_data(api_client.get_matter(graph["matter"]["id"], ANALYST))
    return graph
