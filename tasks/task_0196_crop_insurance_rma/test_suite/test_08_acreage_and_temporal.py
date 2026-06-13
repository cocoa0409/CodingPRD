"""Acreage reporting: deadline window, late-planting flag, arithmetic, conservation.

Covers the inclusive deadline boundary and the strict late-planting boundary (PRD §3.5),
the over-report arithmetic gate, the prevented-planting acres gate (PRD §3.8), and the
conserved total_insured_acres under report supersession (PRD §3.5).
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    setup_election_with_unit, setup_reported_unit, setup_submitted_pp_claim,
    setup_policy_with_election, add_unit,
    file_acreage_report, set_clock, file_pp_claim,
)


# ─── Deadline window (inclusive at the deadline) ──────────────────────────

def test_acreage_report_at_exactly_deadline_succeeds(api):
    """PRD §3.5: "it is rejected with ERR_ACREAGE_DEADLINE_PASSED if the server's current
    clock is strictly after the program's acreage_reporting_deadline — that is, filing is
    allowed only while now is at or before the deadline."

    Design: Difficulty/resource_temporal_overlap/temporal_acreage_deadline_inclusive_boundary
    """
    ctx = setup_election_with_unit(plan_type="YP", acres=100, share=1,
                                   acreage_reporting_deadline="2026-07-15T00:00:00Z",
                                   clock=None)
    set_clock("2026-07-15T00:00:00Z")  # exactly at the deadline
    res = api.create_acreage_report(
        {"unit_id": ctx["unit"]["id"], "planted_acres": 100, "prevented_acres": 0,
         "planting_date": "2026-05-10T00:00:00Z",
         "expected_unit_version": ctx["unit"]["version"]},
        ctx["sa_headers"])
    report = validate_success(res, 201)
    assert report["status"] == "ACCEPTED", report["status"]
    unit = get_success_data(api.get_unit(ctx["unit"]["id"], ctx["sa_headers"]))
    assert unit["status"] == "REPORTED", unit["status"]


def test_acreage_report_one_second_past_deadline_rejected(api):
    """PRD §3.5: "it is rejected with ERR_ACREAGE_DEADLINE_PASSED if the server's current
    clock is strictly after the program's acreage_reporting_deadline — that is, filing is
    allowed only while now is at or before the deadline."

    Design: Difficulty/resource_temporal_overlap/temporal_acreage_deadline_inclusive_boundary
    """
    ctx = setup_election_with_unit(plan_type="YP", acres=100, share=1,
                                   acreage_reporting_deadline="2026-07-15T00:00:00Z",
                                   clock=None)
    set_clock("2026-07-15T00:00:01Z")  # one second past the deadline
    res = api.create_acreage_report(
        {"unit_id": ctx["unit"]["id"], "planted_acres": 100, "prevented_acres": 0,
         "planting_date": "2026-05-10T00:00:00Z",
         "expected_unit_version": ctx["unit"]["version"]},
        ctx["sa_headers"])
    validate_error(res, "ERR_ACREAGE_DEADLINE_PASSED")
    unit = get_success_data(api.get_unit(ctx["unit"]["id"], ctx["sa_headers"]))
    assert unit["status"] == "PENDING", unit["status"]


# ─── Late-planting flag (strict upper bound) ──────────────────────────────

def test_late_planted_true_when_planting_after_final_date(api):
    """PRD §3.5: "The report's late_planted flag is computed as true when the planting_date
    is strictly after the program's final_planting_date, and false otherwise."

    Design: Difficulty/resource_temporal_overlap/temporal_late_planting_flag_after_final_planting_date
    """
    ctx = setup_election_with_unit(plan_type="YP", acres=100, share=1,
                                   final_planting_date="2026-05-31T00:00:00Z",
                                   acreage_reporting_deadline="2026-07-15T00:00:00Z",
                                   clock="2026-06-20T00:00:00Z")
    report = file_acreage_report(ctx["unit"]["id"], ctx["sa_headers"], ctx["unit"]["version"],
                                 planted_acres=100, prevented_acres=0,
                                 planting_date="2026-06-10T00:00:00Z")
    assert report["late_planted"] is True, report["late_planted"]
    assert report["status"] == "ACCEPTED", report["status"]
    unit = get_success_data(api.get_unit(ctx["unit"]["id"], ctx["sa_headers"]))
    assert unit["status"] == "REPORTED", unit["status"]


def test_late_planted_false_on_final_planting_date_boundary(api):
    """PRD §3.5: "The report's late_planted flag is computed as true when the planting_date
    is strictly after the program's final_planting_date, and false otherwise."

    Design: Difficulty/resource_temporal_overlap/temporal_late_planting_flag_after_final_planting_date
    """
    ctx = setup_election_with_unit(plan_type="YP", acres=100, share=1,
                                   final_planting_date="2026-05-31T00:00:00Z",
                                   acreage_reporting_deadline="2026-07-15T00:00:00Z",
                                   clock="2026-06-20T00:00:00Z")
    # planting exactly on the final planting date is NOT strictly after -> not late.
    report = file_acreage_report(ctx["unit"]["id"], ctx["sa_headers"], ctx["unit"]["version"],
                                 planted_acres=100, prevented_acres=0,
                                 planting_date="2026-05-31T00:00:00Z")
    assert report["late_planted"] is False, report["late_planted"]
    assert report["status"] == "ACCEPTED", report["status"]


# ─── Conserved insured acres under supersession ───────────────────────────

def test_insured_acres_conserved_after_report_supersede(api):
    """PRD §3.5: "Any prior ACCEPTED report on the same unit transitions to SUPERSEDED so
    that only one report is ever ACCEPTED per unit, and the new report becomes ACCEPTED"
    PRD §3.5: "the owning policy's total_insured_acres is recomputed — it is the sum of
    acres across the policy's units that are in REPORTED or ACTIVE status"

    Design: Difficulty/compensating_invariant/invariant_insured_acres_amend_then_revert_conserved
    """
    # Two-unit election so reporting unit1 does NOT bubble the election to REPORTED
    # (unit2 stays PENDING). The owning election therefore remains ELECTED, which is the
    # precondition PRD §3.5 requires for a report to be accepted on the unit — so unit1's
    # report can be superseded by a second report.
    ctx = setup_policy_with_election(plan_type="YP", aph_yield=180, coverage_level=0.75,
                                     clock="2026-06-01T00:00:00Z")
    unit1 = add_unit(ctx["election"]["id"], ctx["sa_headers"], unit_number="0001-0001",
                     acres=100, share=1)
    add_unit(ctx["election"]["id"], ctx["sa_headers"], unit_number="0001-0002",
             acres=40, share=1)
    # Report A on unit1 (100 ac) -> REPORTED; total_insured_acres = 100.
    file_acreage_report(unit1["id"], ctx["sa_headers"], unit1["version"],
                        planted_acres=100, prevented_acres=0)
    unit = get_success_data(api.get_unit(unit1["id"], ctx["sa_headers"]))
    # File report B re-reporting the same 100 acres -> supersedes A.
    file_acreage_report(unit1["id"], ctx["sa_headers"], unit["version"],
                        planted_acres=100, prevented_acres=0,
                        planting_date="2026-05-12T00:00:00Z")
    policy = get_success_data(api.get_policy(ctx["policy"]["id"], ctx["sa_headers"]))
    assert policy["total_insured_acres"] == 100, policy["total_insured_acres"]


def test_unit_planted_acres_reflect_latest_accepted_report(api):
    """PRD §3.5: "The unit's planted_acres and prevented_acres are set from the accepted
    report, and the unit transitions from PENDING to REPORTED."

    Design: Difficulty/compensating_invariant/invariant_insured_acres_amend_then_revert_conserved
    """
    # Two-unit election keeps the owning election ELECTED after unit1 reports (unit2 stays
    # PENDING), which is the precondition PRD §3.5 requires for a report — including the
    # superseding report B — to be accepted on unit1.
    ctx = setup_policy_with_election(plan_type="YP", aph_yield=180, coverage_level=0.75,
                                     clock="2026-06-01T00:00:00Z")
    unit1 = add_unit(ctx["election"]["id"], ctx["sa_headers"], unit_number="0001-0001",
                     acres=100, share=1)
    add_unit(ctx["election"]["id"], ctx["sa_headers"], unit_number="0001-0002",
             acres=40, share=1)
    file_acreage_report(unit1["id"], ctx["sa_headers"], unit1["version"],
                        planted_acres=100, prevented_acres=0)
    unit = get_success_data(api.get_unit(unit1["id"], ctx["sa_headers"]))
    file_acreage_report(unit1["id"], ctx["sa_headers"], unit["version"],
                        planted_acres=100, prevented_acres=0,
                        planting_date="2026-05-12T00:00:00Z")
    unit_after = get_success_data(api.get_unit(unit1["id"], ctx["sa_headers"]))
    assert unit_after["planted_acres"] == 100, unit_after["planted_acres"]


# ─── Acreage arithmetic gates ─────────────────────────────────────────────

def test_acreage_over_report_rejected(api):
    """PRD §3.5: "the sum of planted_acres and prevented_acres may not exceed the unit's
    acres, and a sum that exceeds the insured acreage is rejected with
    ERR_ACREAGE_OVER_REPORTED."

    Design: Corner/validations/acreage_over_report_returns_over_reported
    """
    ctx = setup_election_with_unit(plan_type="YP", acres=100, share=1,
                                   clock="2026-06-01T00:00:00Z")
    res = api.create_acreage_report(
        {"unit_id": ctx["unit"]["id"], "planted_acres": 70, "prevented_acres": 40,
         "planting_date": "2026-05-10T00:00:00Z",
         "expected_unit_version": ctx["unit"]["version"]},
        ctx["sa_headers"])
    validate_error(res, "ERR_ACREAGE_OVER_REPORTED")
    unit = get_success_data(api.get_unit(ctx["unit"]["id"], ctx["sa_headers"]))
    assert unit["status"] == "PENDING", unit["status"]


def test_pp_claim_acres_exceed_reported_rejected(api):
    """PRD §3.8: "The agent submits it ... which requires both that the
    claimed_prevented_acres not exceed the unit's reported prevented_acres (else
    ERR_PP_ACRES_EXCEED_REPORTED)"

    Design: Corner/validations/pp_claim_acres_exceed_reported_returns_exceed
    """
    # Unit reported 60 planted + 40 prevented; PP claim claims 50 prevented.
    ctx = setup_reported_unit(plan_type="YP", acres=100, share=1, planted_acres=60,
                              prevented_acres=40, clock="2026-06-01T00:00:00Z")
    pp = file_pp_claim(ctx["unit"]["id"], ctx["sa_headers"], 50, cause="DROUGHT")
    res = api.submit_pp_claim(pp["id"], ctx["sa_headers"])
    validate_error(res, "ERR_PP_ACRES_EXCEED_REPORTED")
    after = get_success_data(api.get_pp_claim(pp["id"], ctx["sa_headers"]))
    assert after["status"] == "DRAFT", after["status"]
