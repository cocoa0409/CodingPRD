"""Cyclic state machines and transitive cascade chains (difficulty rules 3 & 4).

Translates SCAFFOLD_DIFFICULTY_DESIGN.yaml §1.8 non_linear_state_machine and
transitive_cascade instances. Each instance carries >=2 tests.
"""
from test_helpers import (
    validate_success, validate_paginated, ApiErrorId, fixtures,
)
from test_helpers.test_users import TEST_USERS
from test_helpers.api_client import api_client

AM = TEST_USERS["account_manager_headers"]
FS = TEST_USERS["field_supervisor_headers"]
CC = TEST_USERS["client_contact_headers"]


# ===========================================================================
# Rule 3 instance A: complaint_cyclic_resolved_reopen_to_open
# ===========================================================================
def test_major_complaint_reopen_cycles_back_to_open(api):
    """PRD §3.7: "Reopening advances the complaint `RESOLVED → OPEN`, clears its
    `callback_visit_id`, leaves the previously posted credit in place (it is not
    clawed back), and recomputes the owning account's `open_complaint_count`."

    Design: Difficulty/non_linear_state_machine/complaint_cyclic_resolved_reopen_to_open
    """
    bundle = fixtures.setup_billing_scenario(
        contract_overrides={"monthly_base_cents": 300000, "callback_credit_pct": 0.10})
    complaint = fixtures.setup_resolved_complaint(
        bundle["site"]["id"], bundle["crew"]["id"], severity="MAJOR")
    reopened = validate_success(api.reopen_complaint(complaint["id"], CC), 200)
    assert reopened["status"] == "OPEN"
    assert reopened["callback_visit_id"] is None


def test_major_complaint_reopen_keeps_posted_credit(api):
    """PRD §3.7: "Reopening advances the complaint `RESOLVED → OPEN`, clears its
    `callback_visit_id`, leaves the previously posted credit in place (it is not
    clawed back)". The MAJOR credit is round(300000 * (0.10 + 0.05)) = 45000.

    Design: Difficulty/non_linear_state_machine/complaint_cyclic_resolved_reopen_to_open
    """
    bundle = fixtures.setup_billing_scenario(
        contract_overrides={"monthly_base_cents": 300000, "callback_credit_pct": 0.10})
    complaint = fixtures.setup_resolved_complaint(
        bundle["site"]["id"], bundle["crew"]["id"], severity="MAJOR")
    assert complaint["credit_applied_cents"] == 45000
    validate_success(api.reopen_complaint(complaint["id"], CC), 200)
    after = validate_success(api.get_complaint(complaint["id"], FS), 200)
    assert after["credit_applied_cents"] == 45000


# ===========================================================================
# Rule 3 instance B: billing_period_cyclic_closed_reopened_closed
# ===========================================================================
def test_billing_period_close_reopen_close_returns_to_closed(api):
    """PRD §3.9: "A `REOPENED` period can be closed again, which requires
    `expected_account_version` to match, re-checks that no captured visit is
    `IN_PROGRESS` ... recomputes the final totals, re-emits the four invoice-line
    rows, advances the period back to `CLOSED`".

    Design: Difficulty/non_linear_state_machine/billing_period_cyclic_closed_reopened_closed
    """
    bundle = fixtures.setup_billing_scenario(crew=False)
    period, acct = bundle["period"], bundle["account"]
    fixtures.close_period(period["id"], acct["id"])
    fixtures.reopen_period(period["id"], acct["id"])
    reclosed = fixtures.close_period(period["id"], acct["id"])
    assert reclosed["status"] == "CLOSED"


def test_billing_period_reclose_reemits_base_invoice_line(api):
    """PRD §3.9: "Reopening deletes the invoice lines previously emitted for the
    period as a compensating action". PRD §3.9: "A `REOPENED` period can be closed
    again ... re-emits the four invoice-line rows".

    Design: Difficulty/non_linear_state_machine/billing_period_cyclic_closed_reopened_closed
    """
    bundle = fixtures.setup_billing_scenario(crew=False)
    period, acct = bundle["period"], bundle["account"]
    fixtures.close_period(period["id"], acct["id"])
    fixtures.reopen_period(period["id"], acct["id"])
    fixtures.close_period(period["id"], acct["id"])
    data, _meta = validate_paginated(api.list_invoice_lines(period["id"], AM))
    base_lines = [ln for ln in data if ln["line_type"] == "BASE"]
    assert len(base_lines) == 1
    assert base_lines[0]["amount_cents"] == 300000


# ===========================================================================
# Rule 4 instance A: periodic_visit_complete_cascade_depth3
# ===========================================================================
def test_periodic_complete_cascade_bills_job_and_captures_period(api):
    """PRD §3.5: "for a `PERIODIC` visit the period's `periodic_cents` grows by the
    visit's periodic charge (see §3.6), and the period's `total_cents` is
    recomputed by the provisional total formula of §3.8. Finally, if the visit's
    `visit_kind` is `PERIODIC`, the linked periodic job is advanced `DISPATCHED →
    BILLED` as a cascade."

    Design: Difficulty/transitive_cascade/periodic_visit_complete_cascade_depth3
    """
    bundle = fixtures.setup_billing_scenario(
        site_overrides={"floor_type": "VCT"},
        contract_overrides={"monthly_base_cents": 300000, "hourly_rate_cents": 6000})
    # quoted 2h, clocked 120 min -> no overage, periodic 12000
    job, visit = fixtures.setup_completed_periodic_visit(
        bundle["site"]["id"], bundle["crew"]["id"], 480, 600,
        job_overrides={"quoted_hours": 2},
        dispatch_overrides={"planned_start_min": 480, "planned_end_min": 600})
    assert visit["status"] == "COMPLETED"
    assert job["status"] == "BILLED"
    period = validate_success(api.get_billing_period(bundle["period"]["id"], AM), 200)
    assert period["periodic_cents"] == 12000
    assert period["total_cents"] == 312000  # 300000 + 12000 provisional


def test_periodic_job_billed_only_after_visit_completes(api):
    """PRD §3.5: "Finally, if the visit's `visit_kind` is `PERIODIC`, the linked
    periodic job is advanced `DISPATCHED → BILLED` as a cascade."

    Design: Difficulty/transitive_cascade/periodic_visit_complete_cascade_depth3
    """
    bundle = fixtures.setup_billing_scenario(
        site_overrides={"floor_type": "VCT"},
        contract_overrides={"monthly_base_cents": 300000, "hourly_rate_cents": 6000})
    job, pvisit_id = fixtures.setup_dispatched_periodic_visit(
        bundle["site"]["id"], bundle["crew"]["id"],
        job_overrides={"quoted_hours": 2},
        dispatch_overrides={"planned_start_min": 480, "planned_end_min": 600})
    # before completion: still DISPATCHED
    before = validate_success(api.get_periodic_job(job["id"], AM), 200)
    assert before["status"] == "DISPATCHED"
    fixtures.start_visit(pvisit_id)
    fixtures.clock_full_entry(pvisit_id, bundle["crew"]["id"], 480, 600)
    validate_success(api.complete_visit(pvisit_id, FS), 200)
    after = validate_success(api.get_periodic_job(job["id"], AM), 200)
    assert after["status"] == "BILLED"


# ===========================================================================
# Rule 4 instance B: complaint_resolve_credit_cascade_depth2
# ===========================================================================
def test_complaint_resolve_posts_credit_into_period(api):
    """PRD §3.7: "The credit is posted into the `OPEN` billing period of the site's
    contract for the month of the callback visit's `service_date`: the period's
    `callback_credit_cents` grows by the credit and `total_cents` is recomputed
    via the provisional formula."

    Design: Difficulty/transitive_cascade/complaint_resolve_credit_cascade_depth2
    """
    bundle = fixtures.setup_billing_scenario(
        contract_overrides={"monthly_base_cents": 300000, "callback_credit_pct": 0.10})
    complaint = fixtures.setup_resolved_complaint(
        bundle["site"]["id"], bundle["crew"]["id"], severity="MAJOR")
    assert complaint["credit_applied_cents"] == 45000  # round(300000 * 0.15)
    period = validate_success(api.get_billing_period(bundle["period"]["id"], AM), 200)
    assert period["callback_credit_cents"] == 45000
    assert period["total_cents"] == 255000  # 300000 - 45000 provisional


def test_complaint_resolve_credit_computed_before_posting(api):
    """PRD §3.7: "On resolution, the system computes the callback credit and posts
    it." PRD §3.7: "if the complaint's `severity` is `MAJOR`, the fraction is
    increased by a major-severity bonus of 0.05 (five percentage points) before
    multiplying".

    Design: Difficulty/transitive_cascade/complaint_resolve_credit_cascade_depth2
    """
    bundle = fixtures.setup_billing_scenario(
        contract_overrides={"monthly_base_cents": 300000, "callback_credit_pct": 0.10})
    # before resolution the period has no credit
    period_before = validate_success(api.get_billing_period(bundle["period"]["id"], AM), 200)
    assert period_before["callback_credit_cents"] == 0
    complaint = fixtures.setup_resolved_complaint(
        bundle["site"]["id"], bundle["crew"]["id"], severity="MAJOR")
    assert complaint["credit_applied_cents"] == 45000
    period_after = validate_success(api.get_billing_period(bundle["period"]["id"], AM), 200)
    assert period_after["callback_credit_cents"] == 45000
