"""Risk-management-plan submission, due-date computation, and resubmission."""
from test_helpers import (
    validate_success,
    make_facility_operator_headers,
    register_facility,
    submit_rmp,
)


# ---------------------------------------------------------------------------
# Corner: calculations / rmp_next_due_date_five_years
# ---------------------------------------------------------------------------
def test_rmp_next_due_date_is_five_years_out(api):
    """PRD §3.7: "The plan is created in `ACTIVE` status, and its `next_due_date` is
    computed as the `submitted_date` advanced by five years."

    Design: Corner/calculations/rmp_next_due_date_five_years
    """
    facility = register_facility()
    rmp = submit_rmp(facility["id"], program_level=2, submitted_date="2025-06-01T00:00:00Z")
    assert rmp["status"] == "ACTIVE"
    # 2025-06-01 + 5 years = 2030-06-01.
    assert rmp["next_due_date"].startswith("2030-06-01")


# ---------------------------------------------------------------------------
# Corner: endpoints / rmp_resubmit_from_overdue_returns_active
# ---------------------------------------------------------------------------
def test_resubmit_overdue_rmp_returns_active_with_new_due_date(api):
    """PRD §3.7: "Once the clock passes the `next_due_date` outright, the plan
    becomes `OVERDUE`. A `FacilityOperator` resubmits its own facility's plan — from
    either `DUE` or `OVERDUE` — by supplying a fresh `submitted_date`; resubmission
    returns the plan to `ACTIVE`, records the new `submitted_date`, and recomputes
    `next_due_date` as that new date plus five years."

    Design: Corner/endpoints/rmp_resubmit_from_overdue_returns_active
    """
    facility = register_facility()
    fac_id = facility["id"]
    # submitted 2020-01-01 -> next_due 2025-01-01, which is past the default clock 2026-03-01.
    rmp = submit_rmp(fac_id, program_level=3, submitted_date="2020-01-01T00:00:00Z")
    resp = api.resubmit_risk_management_plan(
        rmp["id"], {"submitted_date": "2026-03-01T00:00:00Z"}, make_facility_operator_headers(fac_id)
    )
    data = validate_success(resp, expected_status=200)
    assert data["status"] == "ACTIVE"
    # 2026-03-01 + 5 years = 2031-03-01.
    assert data["next_due_date"].startswith("2031-03-01")
