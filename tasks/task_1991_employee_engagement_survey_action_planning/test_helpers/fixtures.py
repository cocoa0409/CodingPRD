"""Composite setup helpers.

Multi-step preconditions (instrument -> roster -> cycle -> field period ->
scoring -> publication -> action plans) are encapsulated here so tests focus
on assertions. Every helper builds state from scratch via PRD-declared
endpoints and validates setup calls with get_success_data() so failures
surface as clear setup errors.

Identity threading: UnitManager calls use make_unit_manager_headers() with the
unit's manager_user_id; EmployeeRole calls use make_employee_headers() with the
employee's id. Opaque roles use the shared TEST_USERS constants.
"""
from typing import Any, Dict, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import (
    DEFAULT_CLOSES_AT,
    DEFAULT_ITEM_TARGET_AT,
    DEFAULT_OPENS_AT,
    DEFAULT_PLAN_DUE_AT,
    HIRED_LONG_AGO,
)
from .factories import (
    build_answers,
    create_action_item_payload,
    create_action_plan_payload,
    create_employee_payload,
    create_org_unit_payload,
    create_survey_cycle_payload,
)
from .test_users import (
    TEST_USERS,
    make_employee_headers,
    make_unit_manager_headers,
)

HR_ADMIN = TEST_USERS["hr_admin_headers"]
PEOPLE_ANALYST = TEST_USERS["people_analyst_headers"]
EXECUTIVE = TEST_USERS["executive_headers"]


# ---------------------------------------------------------------------------
# Tier 1: instrument (item bank + items)
# ---------------------------------------------------------------------------

def make_active_bank(
    name: str = "Bank",
    framework: str = "CUSTOM",
    item_specs: Optional[Sequence[Dict[str, Any]]] = None,
) -> Tuple[dict, List[dict]]:
    """Create a bank, add items, activate it. Returns (bank, items).

    item_specs entries: {item_code, dimension, weight, has_free_text?}.
    Defaults to three PURPOSE items of weight 1.0 (the activation floor).
    """
    if item_specs is None:
        item_specs = [
            {"item_code": f"{name[:2].upper()}-{i:02d}", "dimension": "PURPOSE", "weight": 1.0}
            for i in range(1, 4)
        ]
    bank = get_success_data(
        api_client.create_item_bank({"name": name, "framework": framework}, HR_ADMIN)
    )
    items: List[dict] = []
    for spec in item_specs:
        payload = {
            "item_code": spec["item_code"],
            "dimension": spec["dimension"],
            "weight": spec["weight"],
        }
        if "has_free_text" in spec:
            payload["has_free_text"] = spec["has_free_text"]
        items.append(get_success_data(api_client.add_survey_item(bank["id"], payload, HR_ADMIN)))
    bank = get_success_data(api_client.activate_item_bank(bank["id"], HR_ADMIN))
    return bank, items


# ---------------------------------------------------------------------------
# Tier 1: roster (org units + employees)
# ---------------------------------------------------------------------------

def make_unit(
    name: str = "Unit",
    manager_user_id: str = "mgr-1",
    min_n_threshold: Optional[int] = None,
    verbatim_n_threshold: Optional[int] = None,
    parent_unit_id: Optional[str] = None,
) -> dict:
    payload = create_org_unit_payload(name=name, manager_user_id=manager_user_id)
    if min_n_threshold is not None:
        payload["min_n_threshold"] = min_n_threshold
    if verbatim_n_threshold is not None:
        payload["verbatim_n_threshold"] = verbatim_n_threshold
    if parent_unit_id is not None:
        payload["parent_unit_id"] = parent_unit_id
    return get_success_data(api_client.create_org_unit(payload, HR_ADMIN))


def make_employee(
    unit_id: str,
    external_ref: str,
    hired_at: str = HIRED_LONG_AGO,
    employment_status: str = "ACTIVE",
) -> dict:
    payload = create_employee_payload(
        external_ref=external_ref,
        unit_id=unit_id,
        employment_status=employment_status,
        hired_at=hired_at,
    )
    return get_success_data(api_client.create_employee(payload, HR_ADMIN))


def make_employees(
    unit_id: str,
    count: int,
    prefix: str = "E",
    hired_at: str = HIRED_LONG_AGO,
) -> List[dict]:
    return [
        make_employee(unit_id, f"{prefix}{i:03d}", hired_at=hired_at)
        for i in range(1, count + 1)
    ]


# ---------------------------------------------------------------------------
# Tier 1: logical clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    return get_success_data(
        api_client.set_current_utc({"to_iso8601": to_iso8601}, HR_ADMIN)
    )


# ---------------------------------------------------------------------------
# Tier 2: cycle composition and lifecycle progression
# ---------------------------------------------------------------------------

def make_cycle(
    bank_id: str,
    label: str = "Cycle",
    cycle_kind: str = "CENSUS",
    opens_at: str = DEFAULT_OPENS_AT,
    closes_at: str = DEFAULT_CLOSES_AT,
    min_n_default: Optional[int] = None,
    sampling_ratio: Optional[float] = None,
) -> dict:
    payload = create_survey_cycle_payload(
        label=label,
        cycle_kind=cycle_kind,
        bank_id=bank_id,
        opens_at=opens_at,
        closes_at=closes_at,
    )
    if min_n_default is not None:
        payload["min_n_default"] = min_n_default
    if sampling_ratio is not None:
        payload["sampling_ratio"] = sampling_ratio
    return get_success_data(api_client.create_survey_cycle(payload, HR_ADMIN))


def pin_items(
    cycle_id: str,
    items: Sequence[dict],
    pinned_weights: Optional[Sequence[float]] = None,
    start_order: int = 1,
) -> List[dict]:
    """Pin each survey item into the cycle at display_order start_order..start_order+N-1.
    Returns the created CycleItem rows (answer payloads key on CycleItem.id).
    `start_order` continues the sequence when pinning a second batch into a
    cycle that already holds pins (display_order is unique within a cycle)."""
    cycle_items: List[dict] = []
    for idx, item in enumerate(items):
        weight = (
            pinned_weights[idx] if pinned_weights is not None else item["weight"]
        )
        payload = {
            "item_id": item["id"],
            "pinned_weight": weight,
            "display_order": start_order + idx,
        }
        cycle_items.append(
            get_success_data(api_client.pin_cycle_item(cycle_id, payload, HR_ADMIN))
        )
    return cycle_items


def configure_cycle(cycle_id: str) -> dict:
    """DRAFT -> CONFIGURED with a fresh OCC read of the cycle version."""
    current = get_success_data(api_client.get_survey_cycle(cycle_id, HR_ADMIN))
    return get_success_data(
        api_client.configure_cycle(
            cycle_id, {"expected_cycle_version": current["version"]}, HR_ADMIN
        )
    )


def open_cycle(cycle_id: str) -> dict:
    return get_success_data(api_client.open_cycle(cycle_id, HR_ADMIN))


def close_cycle(cycle_id: str) -> dict:
    return get_success_data(api_client.close_cycle(cycle_id, HR_ADMIN))


def score_cycle(cycle_id: str) -> dict:
    return get_success_data(api_client.score_cycle(cycle_id, PEOPLE_ANALYST))


def publish_cycle(cycle_id: str) -> dict:
    return get_success_data(api_client.publish_cycle(cycle_id, HR_ADMIN))


def archive_cycle(cycle_id: str) -> dict:
    return get_success_data(api_client.archive_cycle(cycle_id, HR_ADMIN))


# ---------------------------------------------------------------------------
# Tier 2: invites and responses
# ---------------------------------------------------------------------------

def list_cycle_invites(cycle_id: str) -> List[dict]:
    data, _meta = validate_paginated(
        api_client.list_survey_invites(PEOPLE_ANALYST, params={"cycle_id": cycle_id, "limit": 100})
    )
    return data


def get_invite_for(cycle_id: str, employee_id: str) -> dict:
    data, _meta = validate_paginated(
        api_client.list_survey_invites(
            PEOPLE_ANALYST,
            params={"cycle_id": cycle_id, "employee_id": employee_id},
        )
    )
    assert len(data) == 1, f"expected exactly one invite for employee {employee_id}, got {len(data)}"
    return data[0]


def get_invite(invite_id: str) -> dict:
    return get_success_data(api_client.get_survey_invite(invite_id, PEOPLE_ANALYST))


def get_cycle(cycle_id: str) -> dict:
    return get_success_data(api_client.get_survey_cycle(cycle_id, PEOPLE_ANALYST))


def submit_full(invite: dict, cycle_items: Sequence[dict],
                scores: Sequence[int],
                comments: Optional[Sequence[Optional[str]]] = None):
    """Complete submission by the invite's owning employee (raw Response)."""
    answers = build_answers([ci["id"] for ci in cycle_items], list(scores),
                            list(comments) if comments else None)
    return api_client.submit_invite(
        invite["id"], {"answers": answers}, make_employee_headers(invite["employee_id"])
    )


def submit_partial(invite: dict, cycle_items: Sequence[dict],
                   scores: Sequence[int]):
    """Partial submission by the invite's owning employee (raw Response)."""
    answers = build_answers([ci["id"] for ci in cycle_items], list(scores))
    return api_client.submit_invite_partial(
        invite["id"], {"answers": answers}, make_employee_headers(invite["employee_id"])
    )


# ---------------------------------------------------------------------------
# Tier 2: report snapshots
# ---------------------------------------------------------------------------

def get_direct_snapshot(cycle_id: str, unit_id: str) -> dict:
    data, _meta = validate_paginated(
        api_client.list_report_snapshots(
            PEOPLE_ANALYST,
            params={"cycle_id": cycle_id, "unit_id": unit_id, "scope": "DIRECT"},
        )
    )
    assert len(data) == 1, f"expected exactly one DIRECT snapshot, got {len(data)}"
    return data[0]


# ---------------------------------------------------------------------------
# Tier 3/4/5: full lifecycle composite
# ---------------------------------------------------------------------------

def setup_cycle_with_field_results(
    *,
    bank_name: str = "Bank",
    framework: str = "CUSTOM",
    item_specs: Optional[Sequence[Dict[str, Any]]] = None,
    unit_name: str = "Unit",
    manager_user_id: str = "mgr-1",
    min_n_threshold: int = 3,
    verbatim_n_threshold: int = 5,
    num_employees: int = 3,
    hired_at: str = HIRED_LONG_AGO,
    cycle_label: str = "Census",
    cycle_kind: str = "CENSUS",
    sampling_ratio: Optional[float] = None,
    min_n_default: Optional[int] = None,
    opens_at: str = DEFAULT_OPENS_AT,
    closes_at: str = DEFAULT_CLOSES_AT,
    clock_at_open: str = DEFAULT_OPENS_AT,
    submitters: int = 0,
    submit_scores: Optional[Sequence[Sequence[int]]] = None,
    submit_comments: Optional[Sequence[Optional[Sequence[Optional[str]]]]] = None,
    partial_submitters: int = 0,
    partial_answers: Optional[Sequence[Sequence[int]]] = None,
    target_state: str = "SCORING",
) -> Dict[str, Any]:
    """Build instrument + roster + cycle, walk it to `target_state`.

    Returns a dict with bank, items, cycle_items, unit, employees, invites,
    cycle (latest read after reaching target_state). `submitters` employees
    (from the front of the roster) submit complete responses while the cycle
    is OPEN; `submit_scores[i]` cycles through answer score triples.
    `partial_submitters` following them submit partials answering only the
    first cycle item unless partial_answers gives per-submitter scores.
    """
    bank, items = make_active_bank(bank_name, framework, item_specs)
    unit = make_unit(
        unit_name,
        manager_user_id,
        min_n_threshold=min_n_threshold,
        verbatim_n_threshold=verbatim_n_threshold,
    )
    employees = make_employees(unit["id"], num_employees, prefix=f"{unit_name[:1].upper()}", hired_at=hired_at)

    set_clock(clock_at_open)
    cycle = make_cycle(
        bank["id"],
        label=cycle_label,
        cycle_kind=cycle_kind,
        opens_at=opens_at,
        closes_at=closes_at,
        min_n_default=min_n_default,
        sampling_ratio=sampling_ratio,
    )
    cycle_items = pin_items(cycle["id"], items)
    cycle = configure_cycle(cycle["id"])
    cycle = open_cycle(cycle["id"])

    invites_by_employee: Dict[str, dict] = {}
    for inv in list_cycle_invites(cycle["id"]):
        invites_by_employee[inv["employee_id"]] = inv
    invites = [invites_by_employee.get(emp["id"]) for emp in employees]

    for i in range(submitters):
        scores = submit_scores[i] if submit_scores else [4] * len(cycle_items)
        comments = submit_comments[i] if submit_comments else None
        resp = submit_full(invites[i], cycle_items, scores, comments)
        assert resp.status_code == 201, f"setup submit failed: {resp.text}"
    for j in range(partial_submitters):
        idx = submitters + j
        scores = partial_answers[j] if partial_answers else [5]
        resp = submit_partial(invites[idx], cycle_items[: len(scores)], scores)
        assert resp.status_code == 201, f"setup partial submit failed: {resp.text}"

    if target_state in ("CLOSED", "SCORING", "REPORTED", "ARCHIVED"):
        cycle = close_cycle(cycle["id"])
    if target_state in ("SCORING", "REPORTED", "ARCHIVED"):
        cycle = score_cycle(cycle["id"])
    if target_state in ("REPORTED", "ARCHIVED"):
        cycle = publish_cycle(cycle["id"])
    if target_state == "ARCHIVED":
        cycle = archive_cycle(cycle["id"])

    return {
        "bank": bank,
        "items": items,
        "cycle_items": cycle_items,
        "unit": unit,
        "employees": employees,
        "invites": invites,
        "cycle": cycle,
        "manager_user_id": manager_user_id,
    }


# ---------------------------------------------------------------------------
# Tier 3: action plans
# ---------------------------------------------------------------------------

def make_plan(
    cycle_id: str,
    unit_id: str,
    manager_user_id: str,
    title: str = "Improvement plan",
    focus_dimension: str = "PURPOSE",
    due_at: str = DEFAULT_PLAN_DUE_AT,
) -> dict:
    payload = create_action_plan_payload(
        cycle_id=cycle_id,
        unit_id=unit_id,
        title=title,
        focus_dimension=focus_dimension,
        due_at=due_at,
    )
    return get_success_data(
        api_client.create_action_plan(payload, make_unit_manager_headers(manager_user_id))
    )


def add_plan_item(
    plan_id: str,
    manager_user_id: str,
    description: str = "Milestone",
    owner_user_id: Optional[str] = None,
    target_at: str = DEFAULT_ITEM_TARGET_AT,
) -> dict:
    payload = create_action_item_payload(
        description=description,
        owner_user_id=owner_user_id or manager_user_id,
        target_at=target_at,
    )
    return get_success_data(
        api_client.add_action_item(
            plan_id, payload, make_unit_manager_headers(manager_user_id)
        )
    )


def get_plan(plan_id: str) -> dict:
    return get_success_data(api_client.get_action_plan(plan_id, PEOPLE_ANALYST))


def submit_plan(plan_id: str, manager_user_id: str) -> dict:
    """DRAFT -> SUBMITTED with a fresh OCC read of the plan version."""
    current = get_plan(plan_id)
    return get_success_data(
        api_client.submit_action_plan(
            plan_id,
            {"expected_plan_version": current["version"]},
            make_unit_manager_headers(manager_user_id),
        )
    )


def setup_submitted_plan(
    scenario: Optional[Dict[str, Any]] = None,
    *,
    num_items: int = 1,
    title: str = "Improvement plan",
    focus_dimension: str = "PURPOSE",
    due_at: str = DEFAULT_PLAN_DUE_AT,
    **scenario_kwargs,
) -> Dict[str, Any]:
    """REPORTED cycle scenario plus a SUBMITTED plan with `num_items` OPEN items."""
    if scenario is None:
        scenario_kwargs.setdefault("target_state", "REPORTED")
        scenario_kwargs.setdefault("submitters", scenario_kwargs.get("num_employees", 3))
        scenario = setup_cycle_with_field_results(**scenario_kwargs)
    mgr = scenario["manager_user_id"]
    plan = make_plan(
        scenario["cycle"]["id"], scenario["unit"]["id"], mgr,
        title=title, focus_dimension=focus_dimension, due_at=due_at,
    )
    items = [
        add_plan_item(plan["id"], mgr, description=f"Milestone {i + 1}")
        for i in range(num_items)
    ]
    plan = submit_plan(plan["id"], mgr)
    scenario.update({"plan": plan, "plan_items": items})
    return scenario


def setup_in_progress_plan(
    scenario: Optional[Dict[str, Any]] = None,
    *,
    num_items: int = 1,
    **scenario_kwargs,
) -> Dict[str, Any]:
    """SUBMITTED plan driven APPROVED then IN_PROGRESS."""
    scenario = setup_submitted_plan(scenario, num_items=num_items, **scenario_kwargs)
    mgr = scenario["manager_user_id"]
    plan = get_success_data(api_client.approve_action_plan(scenario["plan"]["id"], PEOPLE_ANALYST))
    plan = get_success_data(
        api_client.start_action_plan(plan["id"], make_unit_manager_headers(mgr))
    )
    scenario["plan"] = plan
    return scenario
