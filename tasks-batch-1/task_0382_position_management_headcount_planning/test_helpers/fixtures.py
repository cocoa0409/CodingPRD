"""Composite setup helpers for the Position Management & Headcount Planning API.

These encapsulate the multi-step sequences needed to drive positions, cost
centers, freezes, requisitions, reclass requests, and forecast periods into the
states the tests assert against, so test functions can focus on assertions.

Every helper builds its preconditions from scratch — the server DB is empty at
the start of each test. Setup calls use get_success_data() so a setup failure
produces a clear "Setup failed" error rather than a confusing assertion failure.

All four roles are opaque (no entity-backed ownership), so headers are the
shared role constants from TEST_USERS.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS
from . import factories
from . import constants


# ---------------------------------------------------------------------------
# Header shortcuts
# ---------------------------------------------------------------------------
def hrbp():
    return TEST_USERS["hrbp_headers"]


def finance():
    return TEST_USERS["finance_headers"]


def comp():
    return TEST_USERS["comp_headers"]


def director():
    return TEST_USERS["director_headers"]


# ---------------------------------------------------------------------------
# Tier 0: clock + master data primitives
# ---------------------------------------------------------------------------
def set_clock(to_iso8601: str) -> None:
    """Set the server's current UTC instant (FinanceController)."""
    get_success_data(api_client.set_current_utc(factories.set_clock_payload(to_iso8601), finance()))


def create_grade(**overrides) -> dict:
    """Create a Grade (CompensationAnalyst). Pass band_* / rank / code overrides."""
    return get_success_data(api_client.create_grade(factories.create_grade_payload(**overrides), comp()))


def create_grade_g05() -> dict:
    return create_grade(**constants.GRADE_G05)


def create_grade_g07() -> dict:
    return create_grade(**constants.GRADE_G07)


def create_grade_g09() -> dict:
    return create_grade(**constants.GRADE_G09)


def create_grade_gh() -> dict:
    return create_grade(**constants.GRADE_GH)


def create_cost_center(**overrides) -> dict:
    """Create a CostCenter (FinanceController)."""
    return get_success_data(api_client.create_cost_center(factories.create_cost_center_payload(**overrides), finance()))


def create_employee(**overrides) -> dict:
    """Create an Employee (HRBP)."""
    return get_success_data(api_client.create_employee(factories.create_employee_payload(**overrides), hrbp()))


def create_position(cost_center_id, grade_id, **overrides) -> dict:
    """Create a Position in DRAFT/VACANT (HRBP)."""
    return get_success_data(
        api_client.create_position(
            factories.create_position_payload(cost_center_id, grade_id, **overrides), hrbp()
        )
    )


def get_cost_center(cost_center_id) -> dict:
    return get_success_data(api_client.get_cost_center(cost_center_id, finance()))


def get_position(position_id) -> dict:
    return get_success_data(api_client.get_position(position_id, hrbp()))


def cost_center_version(cost_center_id) -> int:
    """Read the cost center's current version (the OCC token for fund/snapshot)."""
    return get_cost_center(cost_center_id)["version"]


# ---------------------------------------------------------------------------
# Tier 1: Position lifecycle progression
# ---------------------------------------------------------------------------
def requisition_position(position_id) -> dict:
    """DRAFT -> REQUISITIONED (HRBP action=REQUISITION)."""
    return get_success_data(
        api_client.position_lifecycle(position_id, factories.lifecycle_payload("REQUISITION"), hrbp())
    )


def fund_position(position_id, cost_center_id, override=None) -> dict:
    """REQUISITIONED -> FUNDED (FinanceController action=FUND).

    Reads the cost center's live version immediately before funding so the OCC
    token is fresh.
    """
    v = cost_center_version(cost_center_id)
    extra = {"override": override} if override is not None else {}
    return get_success_data(
        api_client.position_lifecycle(
            position_id, factories.lifecycle_payload("FUND", expected_cost_center_version=v, **extra), finance()
        )
    )


def create_funded_position(cost_center_id, grade_id, override=None, **pos_overrides) -> dict:
    """Create a position and drive it DRAFT -> REQUISITIONED -> FUNDED.

    Returns the funded Position resource (after a fresh GET).
    """
    pos = create_position(cost_center_id, grade_id, **pos_overrides)
    requisition_position(pos["id"])
    fund_position(pos["id"], cost_center_id, override=override)
    return get_position(pos["id"])


def create_requisitioned_position(cost_center_id, grade_id, **pos_overrides) -> dict:
    """Create a position and drive it DRAFT -> REQUISITIONED. Returns the position."""
    pos = create_position(cost_center_id, grade_id, **pos_overrides)
    requisition_position(pos["id"])
    return get_position(pos["id"])


# ---------------------------------------------------------------------------
# Tier 2: standard scenario builders
# ---------------------------------------------------------------------------
def setup_grade_and_cost_center(grade_overrides=None, cc_overrides=None):
    """A G07 grade + a default cost center. Returns (grade, cost_center)."""
    grade = create_grade(**(grade_overrides or constants.GRADE_G07))
    cc = create_cost_center(**(cc_overrides or {}))
    return grade, cc


def setup_funded_vacant_position(grade_overrides=None, cc_overrides=None, pos_overrides=None):
    """G07 + cost center + one FUNDED, VACANT position.

    Returns (grade, cost_center, position).
    """
    grade, cc = setup_grade_and_cost_center(grade_overrides, cc_overrides)
    pos = create_funded_position(cc["id"], grade["id"], **(pos_overrides or {}))
    return grade, cc, pos


def fill_position(position_id, employee_id, start_date="2026-01-01") -> dict:
    """Fill a FUNDED/VACANT position with an employee (HRBP). Returns the Incumbent."""
    return get_success_data(
        api_client.create_incumbent(
            position_id, factories.create_incumbent_payload(employee_id, start_date=start_date), hrbp()
        )
    )


def setup_filled_position(employee_salary_cents=13000000, grade_overrides=None,
                          cc_overrides=None, pos_overrides=None, start_date="2026-01-01"):
    """G07 + cost center + FUNDED position + AVAILABLE employee + ACTIVE incumbent (FILLED).

    Returns (grade, cost_center, position, employee, incumbent).
    """
    grade, cc, pos = setup_funded_vacant_position(grade_overrides, cc_overrides, pos_overrides)
    emp = create_employee(annual_salary_cents=employee_salary_cents)
    inc = fill_position(pos["id"], emp["id"], start_date=start_date)
    return grade, cc, pos, emp, inc


# ---------------------------------------------------------------------------
# Tier 3: freeze / cascade builders
# ---------------------------------------------------------------------------
def open_freeze_order(cost_center_id, effective_from, effective_to, reason="freeze") -> dict:
    """Open a hiring freeze window (FinanceController). Returns the FreezeOrder."""
    return get_success_data(
        api_client.create_freeze_order(
            cost_center_id, factories.create_freeze_order_payload(effective_from, effective_to, reason), finance()
        )
    )


def lift_freeze_order(freeze_order_id) -> dict:
    """Lift an ACTIVE freeze order (FinanceController). Returns the FreezeOrder."""
    return get_success_data(api_client.lift_freeze_order(freeze_order_id, finance()))


def setup_frozen_cost_center_with_funded_position(
    clock="2026-02-01T00:00:00Z",
    window_from="2026-01-01T00:00:00Z",
    window_to="2026-04-01T00:00:00Z",
):
    """Clock set; G07 + CC + one FUNDED position; then a freeze covering now ->
    cost center FROZEN, position FROZEN.

    Returns (grade, cost_center, position, freeze_order).
    """
    set_clock(clock)
    grade, cc, pos = setup_funded_vacant_position()
    f = open_freeze_order(cc["id"], window_from, window_to)
    return grade, cc, pos, f


# ---------------------------------------------------------------------------
# Tier 4: requisition builders
# ---------------------------------------------------------------------------
def open_requisition(position_id, req_type="NEW_HIRE", justification="hire") -> dict:
    """Open a requisition on a position (HRBP). Returns the Requisition."""
    return get_success_data(
        api_client.create_requisition(
            position_id, factories.create_requisition_payload(req_type, justification), hrbp()
        )
    )


def approve_requisition(requisition_id) -> dict:
    """OPEN -> APPROVED (FinanceController)."""
    return get_success_data(api_client.approve_requisition(requisition_id, finance()))


# ---------------------------------------------------------------------------
# Tier 5: reclass builders
# ---------------------------------------------------------------------------
def submit_reclass(position_id, target_grade_id, justification="promo") -> dict:
    """Submit a reclass request (CompensationAnalyst). Returns the ReclassRequest."""
    return get_success_data(
        api_client.create_reclass_request(
            position_id, factories.create_reclass_request_payload(target_grade_id, justification), comp()
        )
    )


def review_reclass(reclass_id) -> dict:
    """SUBMITTED -> UNDER_REVIEW (CompensationAnalyst)."""
    return get_success_data(api_client.review_reclass_request(reclass_id, comp()))


def return_reclass(reclass_id) -> dict:
    """UNDER_REVIEW -> SUBMITTED (CompensationAnalyst)."""
    return get_success_data(api_client.return_reclass_request(reclass_id, comp()))


def setup_reclass_under_review(from_grade=None, to_grade=None, fund=True):
    """Funded (or just-created) position on a G05->target reclass moved to UNDER_REVIEW.

    Returns (cost_center, position, from_grade, target_grade, reclass).
    """
    g_from = create_grade(**(from_grade or constants.GRADE_G05))
    g_to = create_grade(**(to_grade or constants.GRADE_G07))
    cc = create_cost_center()
    if fund:
        pos = create_funded_position(cc["id"], g_from["id"])
    else:
        pos = create_position(cc["id"], g_from["id"])
    rr = submit_reclass(pos["id"], g_to["id"])
    review_reclass(rr["id"])
    return cc, pos, g_from, g_to, rr


# ---------------------------------------------------------------------------
# Tier 6: forecast builders
# ---------------------------------------------------------------------------
def create_forecast_period(cost_center_id, fiscal_label="FY26-Q1", planned_fte=2.0) -> dict:
    """Create a DRAFT forecast period (FinanceController). Returns the ForecastPeriod."""
    return get_success_data(
        api_client.create_forecast_period(
            cost_center_id, factories.create_forecast_period_payload(fiscal_label, planned_fte), finance()
        )
    )


def snapshot_forecast_period(forecast_period_id, cost_center_id) -> dict:
    """Snapshot a DRAFT forecast period with the live cost-center version (OCC token)."""
    v = cost_center_version(cost_center_id)
    return get_success_data(
        api_client.snapshot_forecast_period(forecast_period_id, factories.snapshot_payload(v), finance())
    )


# ---------------------------------------------------------------------------
# Tier 7: budget adjustment builder
# ---------------------------------------------------------------------------
def apply_budget_adjustment(cost_center_id, amount_cents, memo="adjustment") -> dict:
    """Apply a signed budget adjustment (FinanceController). Returns the BudgetAdjustment."""
    return get_success_data(
        api_client.create_budget_adjustment(
            cost_center_id, factories.create_budget_adjustment_payload(amount_cents, memo), finance()
        )
    )


# ---------------------------------------------------------------------------
# Tier 8: span-of-control builder
# ---------------------------------------------------------------------------
def setup_manager_with_reports(num_reports, cc_overrides=None):
    """A manager position with `num_reports` non-abolished DRAFT direct reports.

    Returns (cost_center, grade, manager, [report_ids]).
    """
    grade = create_grade(**constants.GRADE_G07)
    cc = create_cost_center(**(cc_overrides or {"fte_cap": 50.0}))
    mgr = create_position(cc["id"], grade["id"], title="Mgr")
    report_ids = []
    for i in range(num_reports):
        r = create_position(cc["id"], grade["id"], title=f"r{i + 1}", manager_position_id=mgr["id"])
        report_ids.append(r["id"])
    return cc, grade, mgr, report_ids
