"""Composite setup helpers.

Every test runs against an empty database with the logical clock at its
startup default (PRD 2.4), so each helper builds its preconditions from
scratch using only endpoints the PRD declares. Setup calls use the lenient
get_success_data validator so a broken precondition surfaces as a clear
"Setup step failed" rather than a confusing assertion later.
"""
from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CLOCK_START,
    CONFIG_A_DEPARTMENTS,
    DEFAULT_ASSOCIATION,
    DEFAULT_STATUTE,
    ESTOPPEL_FEE_QUOTED,
    ESTOPPEL_PAYOFF,
    FINDINGS_CODE_ACCRUAL_11500,
    FINDINGS_EMPTY,
    FINDINGS_UTILITY_300K,
)
from .factories import (
    create_association_payload,
    create_department_payload,
    create_discrepancy_payload,
    create_jurisdiction_payload,
    create_search_order_payload,
    create_statute_payload,
    record_findings_payload,
    resolve_discrepancy_payload,
)
from .test_users import (
    make_provider_admin_headers,
    make_qa_reviewer_headers,
    make_research_analyst_headers,
    make_title_agent_headers,
)

ADMIN = make_provider_admin_headers()
AGENT = make_title_agent_headers("agent_1")
ANALYST = make_research_analyst_headers("analyst_1")
QA = make_qa_reviewer_headers("qa_1")
QA2 = make_qa_reviewer_headers("qa_2")


# ---------------------------------------------------------------------------
# Tier 0 — primitive steps
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str = CLOCK_START) -> dict:
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN)
    )


def create_jurisdiction(
    code: str = "FL-DADE",
    name: str = "Miami-Dade",
    state_code: str = "FL",
    rush_daily_capacity: Optional[int] = 5,
) -> dict:
    payload = create_jurisdiction_payload(
        code=code, name=name, state_code=state_code,
        rush_daily_capacity=rush_daily_capacity,
    )
    return get_success_data(api_client.create_jurisdiction(payload, ADMIN))


def create_statute(jurisdiction_id: str, **overrides) -> dict:
    payload = create_statute_payload(jurisdiction_id, **overrides)
    return get_success_data(api_client.create_statute(payload, ADMIN))


def create_department(jurisdiction_id: str, **overrides) -> dict:
    payload = create_department_payload(jurisdiction_id, **overrides)
    return get_success_data(api_client.create_department(payload, ADMIN))


def create_association(jurisdiction_id: str, **overrides) -> dict:
    payload = create_association_payload(jurisdiction_id, **overrides)
    return get_success_data(api_client.create_association(payload, ADMIN))


def create_search_order(parcel_number: str, agent_headers=None, **overrides) -> dict:
    payload = create_search_order_payload(parcel_number, **overrides)
    return get_success_data(
        api_client.create_search_order(payload, agent_headers or AGENT)
    )


def get_order(order_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_search_order(order_id, headers or QA))


def get_task(task_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_research_task(task_id, headers or QA))


def get_estoppel(estoppel_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_estoppel_order(estoppel_id, headers or QA))


def get_discrepancy(discrepancy_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_discrepancy(discrepancy_id, headers or QA))


def get_delivery(delivery_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_delivery(delivery_id, headers or QA))


def list_order_tasks(order_id: str, headers=None) -> List[dict]:
    data = get_success_data(
        api_client.list_order_research_tasks(order_id, headers or ANALYST)
    )
    assert isinstance(data, list), "research-tasks list must return an array payload"
    return data


def list_order_estoppels(order_id: str, headers=None) -> List[dict]:
    data = get_success_data(
        api_client.list_order_estoppel_orders(order_id, headers or ANALYST)
    )
    assert isinstance(data, list), "estoppel-orders list must return an array payload"
    return data


def identify_order(order_id: str, jurisdiction_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.identify_jurisdiction(
            order_id, {"jurisdiction_id": jurisdiction_id}, headers or ANALYST
        )
    )


def record_findings(task: dict, findings: List[dict], headers=None) -> dict:
    """Record findings on a task dict, threading its current version (PRD 2.7)."""
    return get_success_data(
        api_client.record_findings(
            task["id"],
            record_findings_payload(task["version"], findings),
            headers or ANALYST,
        )
    )


def complete_task(task_id: str, headers=None) -> dict:
    return get_success_data(api_client.complete_task(task_id, headers or ANALYST))


def place_estoppel(
    estoppel_id: str, fee_quoted_cents: int = ESTOPPEL_FEE_QUOTED, headers=None
) -> dict:
    return get_success_data(
        api_client.place_estoppel(
            estoppel_id, {"fee_quoted_cents": fee_quoted_cents}, headers or ANALYST
        )
    )


def receive_estoppel(
    estoppel_id: str, payoff_amount_cents: int = ESTOPPEL_PAYOFF, headers=None
) -> dict:
    return get_success_data(
        api_client.receive_estoppel(
            estoppel_id, {"payoff_amount_cents": payoff_amount_cents},
            headers or ANALYST,
        )
    )


def submit_order(order_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.submit_for_verification(order_id, headers or ANALYST)
    )


def verify_order(order_id: str, verified_total: int, headers=None) -> dict:
    return get_success_data(
        api_client.verify_payoff(
            order_id, {"verified_payoff_total_cents": verified_total}, headers or QA
        )
    )


def create_ready_delivery(order_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.create_delivery({"search_order_id": order_id}, headers or QA)
    )


def deliver(delivery_id: str, headers=None) -> dict:
    return get_success_data(api_client.deliver_delivery(delivery_id, headers or QA))


def file_discrepancy(
    search_order_id: str,
    subject_type: str,
    subject_id: str,
    discrepancy_type: str,
    claimed_amount_cents: int,
    description: str = "test discrepancy",
    headers=None,
) -> dict:
    payload = create_discrepancy_payload(
        search_order_id, subject_type, subject_id,
        discrepancy_type, claimed_amount_cents, description,
    )
    return get_success_data(api_client.create_discrepancy(payload, headers or AGENT))


def start_review(discrepancy_id: str, headers=None) -> dict:
    return get_success_data(api_client.start_review(discrepancy_id, headers or QA2))


def resolve_discrepancy(
    discrepancy_id: str,
    resolution_outcome: str,
    confirmed_amount_cents: Optional[int] = None,
    headers=None,
) -> dict:
    payload = resolve_discrepancy_payload(resolution_outcome, confirmed_amount_cents)
    return get_success_data(
        api_client.resolve_discrepancy(discrepancy_id, payload, headers or QA2)
    )


# ---------------------------------------------------------------------------
# Tier 1 — reference book
# ---------------------------------------------------------------------------

def setup_config_a(
    *,
    departments: Sequence[Dict[str, Any]] = CONFIG_A_DEPARTMENTS,
    with_association: bool = True,
    rush_daily_capacity: Optional[int] = 5,
    clock: Optional[str] = CLOCK_START,
    jurisdiction_code: str = "FL-DADE",
    statute_overrides: Optional[dict] = None,
    association_overrides: Optional[dict] = None,
) -> Dict[str, Any]:
    """Clock + jurisdiction + in-force statute + departments (+ association).

    Returns {"jurisdiction", "statute", "departments", "association"}.
    """
    if clock is not None:
        set_clock(clock)
    jurisdiction = create_jurisdiction(
        code=jurisdiction_code, rush_daily_capacity=rush_daily_capacity
    )
    statute = create_statute(
        jurisdiction["id"], **(dict(DEFAULT_STATUTE, **(statute_overrides or {})))
    )
    deps = [create_department(jurisdiction["id"], **d) for d in departments]
    association = (
        create_association(
            jurisdiction["id"],
            **(dict(DEFAULT_ASSOCIATION, **(association_overrides or {}))),
        )
        if with_association
        else None
    )
    return {
        "jurisdiction": jurisdiction,
        "statute": statute,
        "departments": deps,
        "association": association,
    }


# ---------------------------------------------------------------------------
# Tier 2 — identified order (INTAKE -> RESEARCH_IN_PROGRESS fan-out)
# ---------------------------------------------------------------------------

def setup_identified_order(
    parcel_number: str = "P-BASE-1",
    *,
    departments: Sequence[Dict[str, Any]] = CONFIG_A_DEPARTMENTS,
    with_association: bool = True,
    order_overrides: Optional[dict] = None,
    agent_headers=None,
    config_overrides: Optional[dict] = None,
) -> Dict[str, Any]:
    """Config A plus one order driven through identify-jurisdiction.

    Returns config keys plus "order", "tasks", "estoppels".
    """
    ctx = setup_config_a(
        departments=departments,
        with_association=with_association,
        **(config_overrides or {}),
    )
    overrides = dict(order_overrides or {})
    if ctx["association"] is not None and "association_id" not in overrides:
        overrides["association_id"] = ctx["association"]["id"]
    order = create_search_order(
        parcel_number, agent_headers=agent_headers, **overrides
    )
    identify_order(order["id"], ctx["jurisdiction"]["id"])
    ctx["order"] = get_order(order["id"])
    ctx["tasks"] = list_order_tasks(order["id"])
    ctx["estoppels"] = list_order_estoppels(order["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 3 — research-complete order (tasks COMPLETED, estoppel RECEIVED)
# ---------------------------------------------------------------------------

def complete_all_tasks(
    ctx: Dict[str, Any],
    findings_per_task: Optional[Sequence[List[dict]]] = None,
    headers=None,
) -> List[dict]:
    """Complete every spawned task. Default findings: 300000 utility on the
    first task, an accruing code violation on the second, empty on the rest."""
    tasks = ctx["tasks"]
    if findings_per_task is None:
        defaults = [FINDINGS_UTILITY_300K, FINDINGS_CODE_ACCRUAL_11500]
        findings_per_task = [
            defaults[i] if i < len(defaults) else FINDINGS_EMPTY
            for i in range(len(tasks))
        ]
    completed = []
    for task, findings in zip(tasks, findings_per_task):
        record_findings(task, findings, headers=headers)
        completed.append(complete_task(task["id"], headers=headers))
    ctx["tasks"] = [get_task(t["id"]) for t in tasks]
    ctx["order"] = get_order(ctx["order"]["id"])
    return completed


def place_and_receive_estoppel(
    ctx: Dict[str, Any],
    fee_quoted_cents: int = ESTOPPEL_FEE_QUOTED,
    payoff_amount_cents: int = ESTOPPEL_PAYOFF,
    headers=None,
) -> dict:
    estoppel = ctx["estoppels"][0]
    place_estoppel(estoppel["id"], fee_quoted_cents, headers=headers)
    received = receive_estoppel(estoppel["id"], payoff_amount_cents, headers=headers)
    ctx["estoppels"] = list_order_estoppels(ctx["order"]["id"])
    ctx["order"] = get_order(ctx["order"]["id"])
    return received


def setup_research_complete(
    parcel_number: str = "P-BASE-2",
    *,
    departments: Sequence[Dict[str, Any]] = CONFIG_A_DEPARTMENTS,
    with_association: bool = True,
    findings_per_task: Optional[Sequence[List[dict]]] = None,
    estoppel_fee: int = ESTOPPEL_FEE_QUOTED,
    estoppel_payoff: int = ESTOPPEL_PAYOFF,
    order_overrides: Optional[dict] = None,
    config_overrides: Optional[dict] = None,
    agent_headers=None,
) -> Dict[str, Any]:
    """Identified order with every task COMPLETED and (when an association is
    attached) its estoppel RECEIVED."""
    ctx = setup_identified_order(
        parcel_number,
        departments=departments,
        with_association=with_association,
        order_overrides=order_overrides,
        agent_headers=agent_headers,
        config_overrides=config_overrides,
    )
    complete_all_tasks(ctx, findings_per_task)
    if ctx["estoppels"]:
        place_and_receive_estoppel(ctx, estoppel_fee, estoppel_payoff)
    return ctx


# ---------------------------------------------------------------------------
# Tier 4 — verification / delivery lifecycle
# ---------------------------------------------------------------------------

def setup_in_verification(parcel_number: str = "P-BASE-3", **kwargs) -> Dict[str, Any]:
    """Research-complete order submitted for verification (VERIFICATION)."""
    ctx = setup_research_complete(parcel_number, **kwargs)
    submit_order(ctx["order"]["id"])
    ctx["order"] = get_order(ctx["order"]["id"])
    return ctx


def setup_ready_for_delivery(
    parcel_number: str = "P-BASE-4", **kwargs
) -> Dict[str, Any]:
    """Order in READY_FOR_DELIVERY. The verifier's total is read back from the
    server so the independent verification always matches the computed payoff."""
    ctx = setup_in_verification(parcel_number, **kwargs)
    computed_total = get_order(ctx["order"]["id"])["total_payoff_cents"]
    verify_order(ctx["order"]["id"], computed_total)
    ctx["order"] = get_order(ctx["order"]["id"])
    return ctx


def setup_with_ready_delivery(
    parcel_number: str = "P-BASE-5", **kwargs
) -> Dict[str, Any]:
    """READY_FOR_DELIVERY order holding one READY delivery."""
    ctx = setup_ready_for_delivery(parcel_number, **kwargs)
    ctx["delivery"] = create_ready_delivery(ctx["order"]["id"])
    return ctx


def setup_delivered(parcel_number: str = "P-BASE-6", **kwargs) -> Dict[str, Any]:
    """Full lifecycle through DELIVERED, with the delivery snapshot frozen."""
    ctx = setup_with_ready_delivery(parcel_number, **kwargs)
    ctx["delivery"] = deliver(ctx["delivery"]["id"])
    ctx["order"] = get_order(ctx["order"]["id"])
    return ctx
