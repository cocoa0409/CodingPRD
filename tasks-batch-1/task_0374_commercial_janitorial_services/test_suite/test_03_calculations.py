"""Labor estimation, actual-labor accumulation, periodic charge, callback credit.

Translates SCAFFOLD_CORNER_DESIGN.yaml §1.9 `calculations` non-stub instances.
"""
from test_helpers import (
    validate_success, ApiErrorId, fixtures,
)
from test_helpers.test_users import TEST_USERS
from test_helpers.api_client import api_client

AM = TEST_USERS["account_manager_headers"]
FS = TEST_USERS["field_supervisor_headers"]


def test_estimate_labor_callback_factor_applied(api):
    """PRD §3.3: "For a `CALLBACK` visit, the remediation pass is lighter:
    `estimated_labor_min` is the base figure multiplied by a callback factor of
    0.40, rounded up to the next whole minute." PRD §3.3: "The estimate begins
    with a base figure equal to the site's `cleanable_sqft` divided by a
    productivity rate of 50 cleanable square feet per crew-minute, rounded up to
    the next whole minute."

    Design: Corner/calculations/estimate_labor_callback_factor_applied
    """
    bundle = fixtures.setup_billing_scenario(site_overrides={"cleanable_sqft": 8000})
    complaint, cb_visit_id = fixtures.setup_callback_scheduled_complaint(
        bundle["site"]["id"], bundle["crew"]["id"], severity="MAJOR")
    visit = validate_success(api.get_visit(cb_visit_id, FS), 200)
    assert visit["visit_kind"] == "CALLBACK"
    # base_min = ceil(8000/50) = 160; ceil(160 * 0.40) = 64
    assert visit["estimated_labor_min"] == 64


def test_estimate_labor_routine_sqft_ceil(api):
    """PRD §3.3: "For a `ROUTINE` visit, `estimated_labor_min` is exactly that
    base figure." PRD §3.3: "the site's `cleanable_sqft` divided by a productivity
    rate of 50 cleanable square feet per crew-minute, rounded up to the next whole
    minute."

    Design: Corner/calculations/estimate_labor_routine_sqft_ceil
    """
    _, site, crew = fixtures.setup_account_site_crew(site_overrides={"cleanable_sqft": 8005})
    visit = fixtures.create_visit(
        site["id"], crew["id"], planned_start_min=540, planned_end_min=700, visit_kind="ROUTINE")
    # ceil(8005/50) = ceil(160.1) = 161
    assert visit["estimated_labor_min"] == 161


def test_actual_labor_excludes_voided_entries(api):
    """PRD §3.5: "It walks the visit's time entries whose `status` is `COMPLETED`,
    in `created_at` ascending order ... and accumulates each entry's `clocked_min`
    into a running sum that becomes `actual_labor_min`; `VOIDED` and `OPEN`
    entries are excluded."

    Design: Corner/calculations/actual_labor_excludes_voided_entries
    """
    _, site, crew = fixtures.setup_account_site_crew()
    visit = fixtures.create_started_visit(site["id"], crew["id"])
    fixtures.clock_full_entry(visit["id"], crew["id"], 480, 540)  # 60 min COMPLETED
    te2 = validate_success(api.create_time_entry(
        {"visit_id": visit["id"], "crew_id": crew["id"], "clock_in_min": 600}, FS), 201)
    validate_success(api.void_time_entry(te2["id"], FS), 200)
    completed = validate_success(api.complete_visit(visit["id"], FS), 200)
    assert completed["actual_labor_min"] == 60


def test_periodic_charge_no_overage_straight_rate_only(api):
    """PRD §3.6: "the overage minutes are the actual minutes minus the quoted
    minutes, but never less than 0; and the straight minutes are the billable
    minutes minus the overage minutes. The per-minute rate is the contract's
    `hourly_rate_cents` divided by 60. The straight portion is the straight
    minutes multiplied by the per-minute rate, rounded half-up to whole cents".

    Design: Corner/calculations/periodic_charge_no_overage_straight_rate_only
    """
    bundle = fixtures.setup_billing_scenario(
        site_overrides={"floor_type": "VCT"},
        contract_overrides={"hourly_rate_cents": 6000})
    # quoted 2h = 120 min, clocked exactly 120 min -> no overage
    _job, _visit = fixtures.setup_completed_periodic_visit(
        bundle["site"]["id"], bundle["crew"]["id"], 480, 600,
        job_overrides={"quoted_hours": 2})
    period = validate_success(api.get_billing_period(bundle["period"]["id"], AM), 200)
    # round(120 * 6000/60) = 12000, no 1.5x surcharge
    assert period["periodic_cents"] == 12000


def test_callback_credit_minor_uses_bare_pct(api):
    """PRD §3.7: "The credit starts from the contract's `monthly_base_cents`
    multiplied by the contract's `callback_credit_pct`; if the complaint's
    `severity` is `MAJOR`, the fraction is increased by a major-severity bonus of
    0.05 (five percentage points) before multiplying — a `MINOR` complaint uses
    the bare contract percentage."

    Design: Corner/calculations/callback_credit_minor_uses_bare_pct
    """
    bundle = fixtures.setup_billing_scenario(
        contract_overrides={"monthly_base_cents": 300000, "callback_credit_pct": 0.10})
    complaint = fixtures.setup_resolved_complaint(
        bundle["site"]["id"], bundle["crew"]["id"], severity="MINOR")
    # round(300000 * 0.10) = 30000 (MINOR, bare pct)
    assert complaint["credit_applied_cents"] == 30000
