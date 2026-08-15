"""Plan creation defaults, required fields, and the plan lifecycle (PRD §3.1)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_plan,
    validate_error,
    validate_success,
    create_draft_plan_with_building,
    create_plan,
)

ADMIN = TEST_USERS["admin_headers"]
COORD = TEST_USERS["coordinator_headers"]
ANY = TEST_USERS["any_headers"]


def test_plan_creation_applies_documented_defaults(api):
    """PRD §3.1: "benefit_threshold_minutes` defaults to 1800 — thirty hours of scheduled work in a week, at or above which a paraprofessional becomes benefit-eligible; `benefit_surcharge_pct` defaults to 0.20, the wage multiplier applied to newly costed assignments while the para is benefit-eligible; and `travel_buffer_minutes` defaults to 30, the required gap between same-day assignments in different buildings."
    PRD §3.1: "A new plan starts in `DRAFT` with `committed_cost_cents` and `settled_cost_cents` at zero and `cost_balance_cents` equal to the full budget."

    Design: Corner/entities/plan_creation_applies_defaults
    """
    resp = api.create_plan(
        {"plan_name": "Defaults", "school_year": "2026-27", "total_budget_cents": 1_000_000},
        ADMIN,
    )
    plan = validate_success(resp, 201)
    assert_plan(plan)
    assert plan["benefit_threshold_minutes"] == 1800
    assert plan["benefit_surcharge_pct"] == pytest.approx(0.20)
    assert plan["travel_buffer_minutes"] == 30
    assert plan["status"] == "DRAFT"
    assert plan["committed_cost_cents"] == 0
    assert plan["settled_cost_cents"] == 0
    assert plan["cost_balance_cents"] == 1_000_000
    assert plan["version"] == 1


@pytest.mark.parametrize("missing_field", ["plan_name", "school_year", "total_budget_cents"])
def test_plan_creation_missing_required_field_returns_invalid_request(api, missing_field):
    """PRD §2.10: "Malformed payloads — a missing required field, a type mismatch, an invalid enum value — are rejected with `ERR_INVALID_REQUEST` (HTTP 400), which also covers violations of the per-plan uniqueness of `building_code`, `student_ref`, and paraprofessional `email`."

    Design: Corner/entities/plan_creation_missing_required_returns_invalid_request
    """
    payload = {"plan_name": "No Budget", "school_year": "2026-27", "total_budget_cents": 1000}
    payload.pop(missing_field)
    resp = api.create_plan(payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_plan_activate_requires_at_least_one_building(api):
    """PRD §3.1: "A plan with no buildings cannot go live: activation moves the plan from `DRAFT` to `ACTIVE`, requires at least one building (else `ERR_PLAN_HAS_NO_BUILDINGS`), and increments the plan’s `version` by one."

    Design: Corner/state_machines/plan_activate_requires_building
    """
    plan = create_plan()
    resp = api.activate_plan(plan["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_PLAN_HAS_NO_BUILDINGS)
    after = validate_success(api.get_plan(plan["id"], ANY))
    assert after["status"] == "DRAFT"


def test_plan_reopen_revision_cycle_and_wrong_state_rejection(api):
    """PRD §3.1: "Later, when the year winds down, beginning reconciliation moves the plan from `ACTIVE` to `RECONCILING`, and reopening moves it from `RECONCILING` back to `ACTIVE` — a revision loop for correcting reconciliation findings, requiring `RECONCILING` (else `ERR_PLAN_NOT_RECONCILING`) — with each transition incrementing the plan’s `version` by one."

    Design: Corner/state_machines/plan_reopen_cycle_and_wrong_state_rejection
    """
    plan, _building = create_draft_plan_with_building()
    activated = validate_success(api.activate_plan(plan["id"], ADMIN), 200)
    assert activated["status"] == "ACTIVE"

    # reopen from ACTIVE is not RECONCILING -> rejected
    resp = api.reopen_plan(plan["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_PLAN_NOT_RECONCILING)

    # ACTIVE -> RECONCILING -> ACTIVE revision loop works
    reconciling = validate_success(api.begin_reconciliation(plan["id"], ADMIN), 200)
    assert reconciling["status"] == "RECONCILING"
    reopened = validate_success(api.reopen_plan(plan["id"], ADMIN), 200)
    assert reopened["status"] == "ACTIVE"


def test_plan_closed_is_terminal_and_rejects_activate(api):
    """PRD §3.9: "When the year’s books are ready, a `DistrictStaffingAdmin` closes the plan, moving it from `RECONCILING` to the terminal `CLOSED`."
    PRD §3.1: "Attempting activation from any state other than `DRAFT` is rejected with `ERR_PLAN_NOT_DRAFT`."

    Design: Corner/state_machines/plan_terminal_lockdown_closed_rejects_activate
    """
    plan, _building = create_draft_plan_with_building()
    validate_success(api.activate_plan(plan["id"], ADMIN), 200)
    validate_success(api.begin_reconciliation(plan["id"], ADMIN), 200)
    closed = validate_success(api.close_plan(plan["id"], ADMIN), 200)
    assert closed["status"] == "CLOSED"

    resp = api.activate_plan(plan["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_PLAN_NOT_DRAFT)
    after = validate_success(api.get_plan(plan["id"], ANY))
    assert after["status"] == "CLOSED"
