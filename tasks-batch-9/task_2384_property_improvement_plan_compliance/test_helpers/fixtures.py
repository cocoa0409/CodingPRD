"""Composite setup helpers.

The harness restarts the API server before every individual test, so every test
starts against an empty database and must build all of its preconditions from
scratch through the documented endpoints. These helpers are the shared vocabulary
for doing that: they drive real requests, use the lenient ``get_success_data``
validator so a broken precondition fails loudly with the server's own error id,
and return the resource bodies the tests then assert against.

The helpers are layered:

1. atomic single-endpoint calls and reads,
2. portfolio and plan scaffolding,
3. capital authorisation,
4. closure phases, crews and item execution,
5. inspections, defects, disputes, extensions, draws and notices, plus a few
   whole-lifecycle composites built from the layers above.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .factories import (
    capital_budget_payload,
    contractor_booking_payload,
    contractor_payload,
    default_notice_payload,
    dispute_payload,
    dispute_resolution_payload,
    draw_decision_payload,
    extension_decision_payload,
    extension_request_payload,
    extension_resubmit_payload,
    franchisee_payload,
    inspection_payload,
    item_payload,
    plan_payload,
    property_payload,
    punch_list_item_payload,
    punch_verify_payload,
    renovation_phase_payload,
    reserve_contribution_payload,
    reserve_draw_payload,
)
from .test_users import (
    BRAND_MANAGER_HEADERS,
    INSPECTOR_HEADERS,
    INSPECTOR_USER_ID,
    make_brand_inspector_headers,
    make_franchisee_owner_headers,
)

JsonDict = Dict[str, Any]


# ---------------------------------------------------------------------------
# Scenario containers
# ---------------------------------------------------------------------------


@dataclass
class Portfolio:
    """A franchisee account and one property registered under it."""

    franchisee: JsonDict
    prop: JsonDict
    owner_headers: JsonDict

    @property
    def franchisee_id(self) -> str:
        return self.franchisee["id"]

    @property
    def property_id(self) -> str:
        return self.prop["id"]


@dataclass
class PlanScenario:
    """A plan scoped against a portfolio, with the items created on it."""

    portfolio: Portfolio
    plan: JsonDict
    items: List[JsonDict] = field(default_factory=list)
    items_by_key: Dict[str, JsonDict] = field(default_factory=dict)

    @property
    def plan_id(self) -> str:
        return self.plan["id"]

    @property
    def property_id(self) -> str:
        return self.portfolio.property_id

    @property
    def franchisee_id(self) -> str:
        return self.portfolio.franchisee_id

    @property
    def owner_headers(self) -> JsonDict:
        return self.portfolio.owner_headers

    def item(self, key: str) -> JsonDict:
        return self.items_by_key[key]

    def item_id(self, key: str) -> str:
        return self.items_by_key[key]["id"]


# ---------------------------------------------------------------------------
# Tier 1 — atomic calls and reads
# ---------------------------------------------------------------------------


def set_clock(api, current_utc: str, headers: Optional[JsonDict] = None) -> JsonDict:
    return get_success_data(api.set_clock(current_utc, headers or BRAND_MANAGER_HEADERS))


def register_franchisee(
    api,
    legal_name: str = "Harborline Lodging LLC",
    contact_email: str = "ops@harborline.example",
) -> JsonDict:
    return get_success_data(
        api.create_franchisee_account(
            franchisee_payload(legal_name=legal_name, contact_email=contact_email),
            BRAND_MANAGER_HEADERS,
        )
    )


def register_property(api, franchisee_id: str, **overrides: Any) -> JsonDict:
    return get_success_data(
        api.create_property(property_payload(franchisee_id, **overrides), BRAND_MANAGER_HEADERS)
    )


def register_contractor(api, **overrides: Any) -> JsonDict:
    return get_success_data(
        api.create_contractor(contractor_payload(**overrides), BRAND_MANAGER_HEADERS)
    )


def read_plan(api, plan_id: str, headers: Optional[JsonDict] = None) -> JsonDict:
    return get_success_data(api.get_plan(plan_id, headers or BRAND_MANAGER_HEADERS))


def read_item(api, item_id: str, headers: Optional[JsonDict] = None) -> JsonDict:
    return get_success_data(api.get_item(item_id, headers or BRAND_MANAGER_HEADERS))


def read_property(api, property_id: str, headers: Optional[JsonDict] = None) -> JsonDict:
    return get_success_data(api.get_property(property_id, headers or BRAND_MANAGER_HEADERS))


def read_franchisee(api, franchisee_id: str, headers: Optional[JsonDict] = None) -> JsonDict:
    return get_success_data(
        api.get_franchisee_account(franchisee_id, headers or BRAND_MANAGER_HEADERS)
    )


def read_budget(api, budget_id: str, headers: Optional[JsonDict] = None) -> JsonDict:
    return get_success_data(api.get_capital_budget(budget_id, headers or BRAND_MANAGER_HEADERS))


def read_draw(api, draw_id: str, headers: Optional[JsonDict] = None) -> JsonDict:
    return get_success_data(api.get_reserve_draw(draw_id, headers or BRAND_MANAGER_HEADERS))


def read_phase(api, phase_id: str, headers: Optional[JsonDict] = None) -> JsonDict:
    return get_success_data(api.get_renovation_phase(phase_id, headers or BRAND_MANAGER_HEADERS))


def read_booking(api, booking_id: str, headers: Optional[JsonDict] = None) -> JsonDict:
    return get_success_data(api.get_contractor_booking(booking_id, headers or BRAND_MANAGER_HEADERS))


def read_inspection(api, inspection_id: str, headers: Optional[JsonDict] = None) -> JsonDict:
    return get_success_data(api.get_inspection(inspection_id, headers or BRAND_MANAGER_HEADERS))


def read_punch_item(api, punch_id: str, headers: Optional[JsonDict] = None) -> JsonDict:
    return get_success_data(api.get_punch_list_item(punch_id, headers or BRAND_MANAGER_HEADERS))


def read_dispute(api, dispute_id: str, headers: Optional[JsonDict] = None) -> JsonDict:
    return get_success_data(api.get_dispute(dispute_id, headers or BRAND_MANAGER_HEADERS))


def read_notice(api, notice_id: str, headers: Optional[JsonDict] = None) -> JsonDict:
    return get_success_data(api.get_default_notice(notice_id, headers or BRAND_MANAGER_HEADERS))


def read_extension(api, request_id: str, headers: Optional[JsonDict] = None) -> JsonDict:
    return get_success_data(api.get_extension_request(request_id, headers or BRAND_MANAGER_HEADERS))


def read_cost_summary(api, plan_id: str, headers: Optional[JsonDict] = None) -> JsonDict:
    return get_success_data(api.get_plan_cost_summary(plan_id, headers or BRAND_MANAGER_HEADERS))


def read_risk_summary(api, property_id: str, headers: Optional[JsonDict] = None) -> JsonDict:
    return get_success_data(
        api.get_property_risk_summary(property_id, headers or BRAND_MANAGER_HEADERS)
    )


def current_plan_version(api, plan_id: str, headers: Optional[JsonDict] = None) -> int:
    return read_plan(api, plan_id, headers)["version"]


def current_property_version(api, property_id: str, headers: Optional[JsonDict] = None) -> int:
    return read_property(api, property_id, headers)["version"]


def ledger_entries(
    api, headers: Optional[JsonDict] = None, **filters: Any
) -> List[JsonDict]:
    """The filtered ledger list is the only channel through which cascade-appended
    entries can be observed."""
    params = {"limit": 100}
    params.update(filters)
    rows, _meta = validate_paginated(
        api.list_compliance_ledger_entries(headers or BRAND_MANAGER_HEADERS, params)
    )
    return rows


def list_rows(api, list_method_name: str, headers: Optional[JsonDict] = None, **filters: Any):
    """Call any list endpoint by client-method name and return ``(rows, meta)``."""
    params = {"limit": 100}
    params.update(filters)
    method = getattr(api, list_method_name)
    return validate_paginated(method(headers or BRAND_MANAGER_HEADERS, params))


def run_compliance_sweep(api, plan_id: str, headers: Optional[JsonDict] = None) -> JsonDict:
    return get_success_data(api.run_compliance_sweep(plan_id, headers or BRAND_MANAGER_HEADERS))


def credit_reserve_contribution(
    api, portfolio: Portfolio, amount_cents: int = 1000000
) -> JsonDict:
    return get_success_data(
        api.create_reserve_contribution(
            portfolio.property_id,
            reserve_contribution_payload(amount_cents),
            portfolio.owner_headers,
        )
    )


# ---------------------------------------------------------------------------
# Tier 2 — portfolio and plan scaffolding
# ---------------------------------------------------------------------------


def bootstrap_portfolio(
    api,
    legal_name: str = "Harborline Lodging LLC",
    contact_email: str = "ops@harborline.example",
    **property_overrides: Any,
) -> Portfolio:
    """Register a franchisee and a 200-key property under it.

    The property defaults mirror the values every scenario in this suite uses:
    200 keys, an 18000-cent ADR baseline, a 0.70 occupancy baseline, a
    50000000-cent reserve balance and a 5000000-cent retention floor.
    """
    franchisee = register_franchisee(api, legal_name, contact_email)
    prop = register_property(api, franchisee["id"], **property_overrides)
    return Portfolio(
        franchisee=franchisee,
        prop=prop,
        owner_headers=make_franchisee_owner_headers(franchisee["id"]),
    )


def scope_plan(
    api,
    portfolio: Portfolio,
    item_specs: Sequence[JsonDict] = (),
    trigger_type: str = "POST_INSPECTION",
    standards_edition: str = "2026.1",
) -> PlanScenario:
    """Scope a draft plan and add its items in the order supplied.

    Each spec is passed through to the item factory. Two extra keys are
    understood: ``key`` names the item for later lookup, and ``predecessor_key``
    resolves to the id of an item created earlier in the same call.
    """
    plan = get_success_data(
        api.create_plan(
            plan_payload(portfolio.property_id, trigger_type, standards_edition),
            BRAND_MANAGER_HEADERS,
        )
    )
    scenario = PlanScenario(portfolio=portfolio, plan=plan)
    for index, spec in enumerate(item_specs):
        spec = dict(spec)
        key = spec.pop("key", f"item{index + 1}")
        predecessor_key = spec.pop("predecessor_key", None)
        if predecessor_key is not None:
            spec["predecessor_item_id"] = scenario.item_id(predecessor_key)
        item = get_success_data(
            api.create_item(item_payload(plan["id"], **spec), BRAND_MANAGER_HEADERS)
        )
        scenario.items.append(item)
        scenario.items_by_key[key] = item
    scenario.plan = read_plan(api, plan["id"])
    return scenario


def issue_plan(api, scenario: PlanScenario) -> PlanScenario:
    scenario.plan = get_success_data(api.issue_plan(scenario.plan_id, BRAND_MANAGER_HEADERS))
    _refresh_items(api, scenario)
    return scenario


def acknowledge_plan(api, scenario: PlanScenario) -> PlanScenario:
    scenario.plan = get_success_data(
        api.acknowledge_plan(scenario.plan_id, scenario.owner_headers)
    )
    return scenario


def _refresh_items(api, scenario: PlanScenario) -> None:
    refreshed = [read_item(api, item["id"]) for item in scenario.items]
    scenario.items = refreshed
    scenario.items_by_key = {
        key: next(item for item in refreshed if item["id"] == stored["id"])
        for key, stored in scenario.items_by_key.items()
    }


def refresh(api, scenario: PlanScenario) -> PlanScenario:
    """Re-read the plan, its items and the property after a cascade."""
    scenario.plan = read_plan(api, scenario.plan_id)
    scenario.portfolio.prop = read_property(api, scenario.property_id)
    _refresh_items(api, scenario)
    return scenario


def issued_plan(
    api,
    item_specs: Sequence[JsonDict],
    legal_name: str = "Harborline Lodging LLC",
    contact_email: str = "ops@harborline.example",
    trigger_type: str = "POST_INSPECTION",
    property_overrides: Optional[JsonDict] = None,
) -> PlanScenario:
    """A plan issued at whatever the logical clock currently reads."""
    portfolio = bootstrap_portfolio(
        api, legal_name, contact_email, **(property_overrides or {})
    )
    scenario = scope_plan(api, portfolio, item_specs, trigger_type)
    return issue_plan(api, scenario)


def acknowledged_plan(api, item_specs: Sequence[JsonDict], **kwargs: Any) -> PlanScenario:
    """A plan issued and then acknowledged by its owner, opening the execution window."""
    scenario = issued_plan(api, item_specs, **kwargs)
    return acknowledge_plan(api, scenario)


# ---------------------------------------------------------------------------
# Tier 3 — capital authorisation
# ---------------------------------------------------------------------------


def authorize_budget(
    api,
    scenario: PlanScenario,
    total_authorized_cents: int,
    contingency_pct: float = 0.10,
    financing_source: str = "OWNER_EQUITY",
    expected_plan_version: Optional[int] = None,
) -> JsonDict:
    """Create a capital budget, reading the plan's current version unless one is given."""
    version = (
        expected_plan_version
        if expected_plan_version is not None
        else current_plan_version(api, scenario.plan_id, scenario.owner_headers)
    )
    return get_success_data(
        api.create_capital_budget(
            capital_budget_payload(
                scenario.plan_id,
                total_authorized_cents,
                version,
                contingency_pct=contingency_pct,
                financing_source=financing_source,
            ),
            scenario.owner_headers,
        )
    )


def approve_budget(api, budget_id: str) -> JsonDict:
    return get_success_data(api.approve_capital_budget(budget_id, BRAND_MANAGER_HEADERS))


def lock_budget(api, scenario: PlanScenario, budget_id: str) -> JsonDict:
    return get_success_data(api.lock_capital_budget(budget_id, scenario.owner_headers))


def locked_budget(
    api,
    scenario: PlanScenario,
    total_authorized_cents: int,
    contingency_pct: float = 0.10,
    financing_source: str = "OWNER_EQUITY",
) -> JsonDict:
    """Authorise, approve and lock a budget in one step: the item-start gate."""
    budget = authorize_budget(
        api, scenario, total_authorized_cents, contingency_pct, financing_source
    )
    approve_budget(api, budget["id"])
    return lock_budget(api, scenario, budget["id"])


# ---------------------------------------------------------------------------
# Tier 4 — closure phases, crews and item execution
# ---------------------------------------------------------------------------


def schedule_phase(api, scenario: PlanScenario, **overrides: Any) -> JsonDict:
    return get_success_data(
        api.create_renovation_phase(
            renovation_phase_payload(scenario.plan_id, **overrides), scenario.owner_headers
        )
    )


def activate_phase(api, scenario: PlanScenario, phase_id: str) -> JsonDict:
    return get_success_data(
        api.activate_renovation_phase(phase_id, scenario.owner_headers)
    )


def close_out_phase(api, scenario: PlanScenario, phase_id: str) -> JsonDict:
    return get_success_data(
        api.close_out_renovation_phase(phase_id, scenario.owner_headers)
    )


def book_crew(
    api, scenario: PlanScenario, contractor_id: str, phase_id: str, **overrides: Any
) -> JsonDict:
    return get_success_data(
        api.create_contractor_booking(
            contractor_booking_payload(contractor_id, phase_id, **overrides),
            scenario.owner_headers,
        )
    )


def start_item(api, scenario: PlanScenario, item_id: str) -> JsonDict:
    return get_success_data(api.start_item(item_id, scenario.owner_headers))


def complete_item_work(api, scenario: PlanScenario, item_id: str) -> JsonDict:
    return get_success_data(api.complete_item_work(item_id, scenario.owner_headers))


# ---------------------------------------------------------------------------
# Tier 5 — inspections, defects, disputes, extensions, draws and notices
# ---------------------------------------------------------------------------


def schedule_inspection(
    api,
    scenario: PlanScenario,
    inspector_user_id: str = INSPECTOR_USER_ID,
    scheduled_date: str = "2026-08-05",
    inspection_type: str = "COMPLETION",
) -> JsonDict:
    return get_success_data(
        api.create_inspection(
            inspection_payload(
                scenario.plan_id,
                inspector_user_id,
                scheduled_date=scheduled_date,
                inspection_type=inspection_type,
            ),
            BRAND_MANAGER_HEADERS,
        )
    )


def perform_inspection(
    api, inspection_id: str, inspector_user_id: str = INSPECTOR_USER_ID
) -> JsonDict:
    return get_success_data(
        api.perform_inspection(inspection_id, make_brand_inspector_headers(inspector_user_id))
    )


def sign_off_inspection(
    api, inspection_id: str, inspector_user_id: str = INSPECTOR_USER_ID
) -> JsonDict:
    return get_success_data(
        api.sign_off_inspection(inspection_id, make_brand_inspector_headers(inspector_user_id))
    )


def raise_defect(
    api,
    inspection_id: str,
    pip_item_id: str,
    severity: str = "MAJOR",
    inspector_user_id: str = INSPECTOR_USER_ID,
    **overrides: Any,
) -> JsonDict:
    return get_success_data(
        api.create_punch_list_item(
            punch_list_item_payload(inspection_id, pip_item_id, severity=severity, **overrides),
            make_brand_inspector_headers(inspector_user_id),
        )
    )


def remediate_defect(api, scenario: PlanScenario, punch_id: str) -> JsonDict:
    return get_success_data(
        api.remediate_punch_list_item(punch_id, scenario.owner_headers)
    )


def verify_defect(
    api,
    punch_id: str,
    outcome: str,
    inspector_user_id: str = INSPECTOR_USER_ID,
    **overrides: Any,
) -> JsonDict:
    return get_success_data(
        api.verify_punch_list_item(
            punch_id,
            punch_verify_payload(outcome, **overrides),
            make_brand_inspector_headers(inspector_user_id),
        )
    )


def file_dispute(
    api,
    scenario: PlanScenario,
    item_id: str,
    claimed_cost_cents: int,
    dispute_basis: str = "COST_ESTIMATE",
) -> JsonDict:
    return get_success_data(
        api.create_dispute(
            dispute_payload(scenario.plan_id, item_id, claimed_cost_cents, dispute_basis),
            scenario.owner_headers,
        )
    )


def resolve_dispute(
    api, dispute_id: str, resolution: str, **overrides: Any
) -> JsonDict:
    return get_success_data(
        api.resolve_dispute(
            dispute_id, dispute_resolution_payload(resolution, **overrides), BRAND_MANAGER_HEADERS
        )
    )


def request_extension(
    api, scenario: PlanScenario, item_id: str, requested_days: int, **overrides: Any
) -> JsonDict:
    return get_success_data(
        api.create_extension_request(
            extension_request_payload(item_id, requested_days, **overrides),
            scenario.owner_headers,
        )
    )


def decide_extension(
    api,
    request_id: str,
    decision: str,
    headers: Optional[JsonDict] = None,
    **overrides: Any,
) -> JsonDict:
    return get_success_data(
        api.decide_extension_request(
            request_id,
            extension_decision_payload(decision, **overrides),
            headers or BRAND_MANAGER_HEADERS,
        )
    )


def resubmit_extension(
    api, scenario: PlanScenario, request_id: str, **overrides: Any
) -> JsonDict:
    return get_success_data(
        api.resubmit_extension_request(
            request_id, extension_resubmit_payload(**overrides), scenario.owner_headers
        )
    )


def request_draw(
    api,
    scenario: PlanScenario,
    budget_id: str,
    purpose_item_id: str,
    amount_cents: int,
    expected_property_version: Optional[int] = None,
) -> JsonDict:
    version = (
        expected_property_version
        if expected_property_version is not None
        else current_property_version(api, scenario.property_id, scenario.owner_headers)
    )
    return get_success_data(
        api.create_reserve_draw(
            reserve_draw_payload(
                scenario.property_id, budget_id, purpose_item_id, amount_cents, version
            ),
            scenario.owner_headers,
        )
    )


def consent_draw(api, draw_id: str, decision: str = "CONSENT") -> JsonDict:
    return get_success_data(
        api.consent_reserve_draw(draw_id, draw_decision_payload(decision), BRAND_MANAGER_HEADERS)
    )


def disburse_draw(api, scenario: PlanScenario, draw_id: str) -> JsonDict:
    return get_success_data(api.disburse_reserve_draw(draw_id, scenario.owner_headers))


def reverse_draw(api, scenario: PlanScenario, draw_id: str) -> JsonDict:
    return get_success_data(api.reverse_reserve_draw(draw_id, scenario.owner_headers))


def issue_default_notice(api, scenario: PlanScenario, cure_period_days: int) -> JsonDict:
    return get_success_data(
        api.create_default_notice(
            default_notice_payload(scenario.plan_id, cure_period_days), BRAND_MANAGER_HEADERS
        )
    )


def cure_default_notice(api, notice_id: str) -> JsonDict:
    return get_success_data(api.cure_default_notice(notice_id, BRAND_MANAGER_HEADERS))


def escalate_default_notice(api, notice_id: str) -> JsonDict:
    return get_success_data(api.escalate_default_notice(notice_id, BRAND_MANAGER_HEADERS))


# ---------------------------------------------------------------------------
# Whole-lifecycle composites
# ---------------------------------------------------------------------------


def executing_plan(
    api,
    item_specs: Sequence[JsonDict],
    total_authorized_cents: int,
    contingency_pct: float = 0.10,
    financing_source: str = "OWNER_EQUITY",
    **kwargs: Any,
) -> Dict[str, Any]:
    """Acknowledged plan plus an approved and locked budget: the item-start gate is open."""
    scenario = acknowledged_plan(api, item_specs, **kwargs)
    budget = locked_budget(
        api, scenario, total_authorized_cents, contingency_pct, financing_source
    )
    return {"scenario": scenario, "budget": budget}


def plan_ready_for_completion(
    api,
    item_specs: Sequence[JsonDict],
    total_authorized_cents: int,
    contingency_pct: float = 0.10,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Every item started and reported finished, so the plan has risen to readiness."""
    built = executing_plan(
        api, item_specs, total_authorized_cents, contingency_pct, **kwargs
    )
    scenario = built["scenario"]
    for item in list(scenario.items):
        start_item(api, scenario, item["id"])
        complete_item_work(api, scenario, item["id"])
    refresh(api, scenario)
    return built


def performed_completion_inspection(
    api,
    item_specs: Sequence[JsonDict],
    total_authorized_cents: int,
    scheduled_date: str = "2026-08-05",
    perform_at_utc: str = "2026-08-05T00:00:00Z",
    inspector_user_id: str = INSPECTOR_USER_ID,
    **kwargs: Any,
) -> Dict[str, Any]:
    """A ready plan with a COMPLETION inspection already recorded as performed."""
    built = plan_ready_for_completion(api, item_specs, total_authorized_cents, **kwargs)
    scenario = built["scenario"]
    inspection = schedule_inspection(
        api, scenario, inspector_user_id=inspector_user_id, scheduled_date=scheduled_date
    )
    set_clock(api, perform_at_utc)
    inspection = perform_inspection(api, inspection["id"], inspector_user_id)
    built["inspection"] = inspection
    return built


__all__ = [
    "Portfolio",
    "PlanScenario",
    "set_clock",
    "register_franchisee",
    "register_property",
    "register_contractor",
    "read_plan",
    "read_item",
    "read_property",
    "read_franchisee",
    "read_budget",
    "read_draw",
    "read_phase",
    "read_booking",
    "read_inspection",
    "read_punch_item",
    "read_dispute",
    "read_notice",
    "read_extension",
    "read_cost_summary",
    "read_risk_summary",
    "current_plan_version",
    "current_property_version",
    "ledger_entries",
    "list_rows",
    "run_compliance_sweep",
    "credit_reserve_contribution",
    "bootstrap_portfolio",
    "scope_plan",
    "issue_plan",
    "acknowledge_plan",
    "refresh",
    "issued_plan",
    "acknowledged_plan",
    "authorize_budget",
    "approve_budget",
    "lock_budget",
    "locked_budget",
    "schedule_phase",
    "activate_phase",
    "close_out_phase",
    "book_crew",
    "start_item",
    "complete_item_work",
    "schedule_inspection",
    "perform_inspection",
    "sign_off_inspection",
    "raise_defect",
    "remediate_defect",
    "verify_defect",
    "file_dispute",
    "resolve_dispute",
    "request_extension",
    "decide_extension",
    "resubmit_extension",
    "request_draw",
    "consent_draw",
    "disburse_draw",
    "reverse_draw",
    "issue_default_notice",
    "cure_default_notice",
    "escalate_default_notice",
    "executing_plan",
    "plan_ready_for_completion",
    "performed_completion_inspection",
    "INSPECTOR_HEADERS",
]
