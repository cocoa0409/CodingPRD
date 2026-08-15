"""Composite setup helpers for multi-step test prerequisites.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (the runner restarts the server before every test, so each test
starts against an empty database). Setup calls use the lenient
get_success_data() validator so a setup failure surfaces as a clear error
naming the step, not as a confusing assertion failure.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_VISIT_DATE, F1_COMPONENTS
from .factories import (
    create_association_payload,
    create_component_payload,
    create_expenditure_payload,
    create_funding_plan_payload,
    create_site_visit_payload,
    create_state_rule_payload,
    create_study_payload,
)
from .test_users import TEST_USERS

ADMIN = TEST_USERS["platform_admin_headers"]
SPECIALIST = TEST_USERS["reserve_specialist_headers"]
BOARD = TEST_USERS["board_member_headers"]
MANAGER = TEST_USERS["association_manager_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-entity primitives
# ---------------------------------------------------------------------------

def seed_state_rule(state_code="CA", **overrides) -> dict:
    """Create a state reserve rule. Returns the rule."""
    payload = create_state_rule_payload(state_code=state_code, **overrides)
    return get_success_data(api_client.create_state_rule(payload, ADMIN))


def onboard_association(state_code="CA", seed_rule=True, **overrides) -> dict:
    """Create an association (seeding its state rule first by default)."""
    if seed_rule:
        seed_state_rule(state_code)
    payload = create_association_payload(state_code=state_code, **overrides)
    return get_success_data(api_client.create_association(payload, SPECIALIST))


def schedule_visit(association_id, visit_date=DEFAULT_VISIT_DATE) -> dict:
    """Schedule a site visit (status SCHEDULED)."""
    payload = create_site_visit_payload(association_id, visit_date)
    return get_success_data(api_client.create_site_visit(payload, MANAGER))


def complete_visit(visit_id) -> dict:
    """Mark a SCHEDULED visit COMPLETED."""
    return get_success_data(api_client.complete_site_visit(visit_id, MANAGER))


def schedule_and_complete_visit(association_id,
                                visit_date=DEFAULT_VISIT_DATE) -> dict:
    """Schedule + complete a site visit. Returns the COMPLETED visit."""
    visit = schedule_visit(association_id, visit_date)
    return complete_visit(visit["id"])


def create_draft_study(association_id, **overrides) -> dict:
    """Create a reserve study (status DRAFT)."""
    payload = create_study_payload(association_id, **overrides)
    return get_success_data(api_client.create_study(payload, SPECIALIST))


def add_component(study_id, **overrides) -> dict:
    """Add a component (status ACTIVE) to a DRAFT study."""
    payload = create_component_payload(study_id, **overrides)
    return get_success_data(api_client.create_component(payload, SPECIALIST))


def add_components(study_id, specs) -> list:
    """Add several components in order. Returns the component list."""
    return [add_component(study_id, **spec) for spec in specs]


def get_study(study_id) -> dict:
    return get_success_data(api_client.get_study(study_id, SPECIALIST))


def get_association(association_id) -> dict:
    return get_success_data(api_client.get_association(association_id, SPECIALIST))


def study_version(study_id) -> int:
    """Current version of a study — the OCC token for plan creation."""
    return get_study(study_id)["version"]


# ---------------------------------------------------------------------------
# Tier 2: funding plans
# ---------------------------------------------------------------------------

def create_plan(study_id, plan_type="BASELINE") -> dict:
    """Create a funding plan, reading the study's fresh version for the OCC
    token (plan creation itself advances the study version, PRD §3.4)."""
    payload = create_funding_plan_payload(plan_type, study_version(study_id))
    return get_success_data(api_client.create_funding_plan(study_id, payload,
                                                           SPECIALIST))


def recommend_plan(plan_id) -> dict:
    return get_success_data(api_client.recommend_plan(plan_id, SPECIALIST))


def select_plan(plan_id) -> dict:
    return get_success_data(api_client.select_plan(plan_id, BOARD))


# ---------------------------------------------------------------------------
# Tier 3: study lifecycle composites
# ---------------------------------------------------------------------------

def setup_draft_study(state_code="CA", cash=500000, components=None,
                      with_visit=False, visit_date=DEFAULT_VISIT_DATE,
                      association_name="Test HOA", association_overrides=None,
                      **study_overrides) -> dict:
    """Rule + association + DRAFT study + components (+ optional completed
    visit). Returns a dict with the created entities."""
    assoc_kwargs = {"name": association_name,
                    "reserve_cash_balance_cents": cash}
    assoc_kwargs.update(association_overrides or {})
    association = onboard_association(state_code=state_code, seed_rule=True,
                                      **assoc_kwargs)
    visit = None
    if with_visit:
        visit = schedule_and_complete_visit(association["id"], visit_date)
    study = create_draft_study(association["id"], **study_overrides)
    specs = F1_COMPONENTS if components is None else components
    comps = add_components(study["id"], specs) if specs else []
    return {
        "association": association,
        "study": get_study(study["id"]),
        "components": comps,
        "visit": visit,
    }


def setup_submitted_study(state_code="CA", cash=500000, components=None,
                          plan_type="BASELINE", visit_date=DEFAULT_VISIT_DATE,
                          association_name="Test HOA", association_overrides=None,
                          **study_overrides) -> dict:
    """DRAFT study + components + one plan + completed visit, then SUBMITTED.
    Returns association / study (SUBMITTED) / components / plan / visit."""
    ctx = setup_draft_study(state_code=state_code, cash=cash,
                            components=components, with_visit=True,
                            visit_date=visit_date,
                            association_name=association_name,
                            association_overrides=association_overrides,
                            **study_overrides)
    plan = create_plan(ctx["study"]["id"], plan_type)
    submitted = get_success_data(api_client.submit_study(ctx["study"]["id"],
                                                         SPECIALIST))
    ctx["study"] = submitted
    ctx["plan"] = plan
    return ctx


def setup_adopted_study(state_code="CA", cash=500000, components=None,
                        plan_type="BASELINE", visit_date=DEFAULT_VISIT_DATE,
                        association_name="Test HOA", association_overrides=None,
                        **study_overrides) -> dict:
    """Full lifecycle: SUBMITTED study + plan SELECTED + study ADOPTED.
    Returns association / study (ADOPTED) / components / plan / visit."""
    ctx = setup_submitted_study(state_code=state_code, cash=cash,
                                components=components, plan_type=plan_type,
                                visit_date=visit_date,
                                association_name=association_name,
                                association_overrides=association_overrides,
                                **study_overrides)
    select_plan(ctx["plan"]["id"])
    adopted = get_success_data(api_client.adopt_study(ctx["study"]["id"], BOARD))
    ctx["study"] = adopted
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: expenditures
# ---------------------------------------------------------------------------

def create_expenditure(association_id, component_id, **overrides) -> dict:
    """Submit an expenditure (SUBMITTED / UNRECONCILED)."""
    payload = create_expenditure_payload(association_id, component_id, **overrides)
    return get_success_data(api_client.create_expenditure(payload, MANAGER))


def get_expenditure(expenditure_id) -> dict:
    return get_success_data(api_client.get_expenditure(expenditure_id, SPECIALIST))


def list_components(study_id, params=None) -> list:
    return get_success_data(api_client.list_components(study_id, SPECIALIST,
                                                       params=params))


def list_plans(study_id, params=None) -> list:
    return get_success_data(api_client.list_funding_plans(study_id, SPECIALIST,
                                                          params=params))


def list_disclosures(study_id, params=None) -> list:
    return get_success_data(api_client.list_disclosures(study_id, SPECIALIST,
                                                        params=params))
