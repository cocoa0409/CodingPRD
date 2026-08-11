"""Queue B — calculations section corner tests."""
import pytest

from test_helpers import (
    api_client, validate_success, get_success_data,
    create_active_program, create_drawdown, create_risk_entry, assess_risk,
    close_risk, create_owner_report, submit_owner_report, accept_owner_report,
    create_and_execute_contract, create_change_order, submit_change_order,
    recommend_change_order, decide_change_order,
    pm_headers, owner_headers,
)


def test_posture_floor_boundary_sweep(api):
    """PRD §2.7: "the ratio of contingency_available_cents to
    contingency_total_cents is compared against two inclusive floors: a ratio
    of at least 30 percent yields NORMAL; a ratio below 30 percent but at
    least 10 percent yields WATCH; anything below 10 percent yields CRITICAL.
    The floors are inclusive — a ratio of exactly 0.30 is NORMAL, and a ratio
    of exactly 0.10 is WATCH."

    Design: Corner/calculations/posture_floor_boundary_sweep
    """
    prog = create_active_program(
        total_budget_cents=10_000_000, contingency_total_cents=1_000_000,
        lines=[{"cost_code": "CC-100", "amount_cents": 10_000_000}], name="P-SWEEP",
    )
    pid = prog["id"]
    # available 300_000 / 1_000_000 = 0.30 -> NORMAL (inclusive)
    create_drawdown(pid, 700_000, purpose="r1")
    p = get_success_data(api_client.get_program(pid, pm_headers()))
    assert p["contingency_posture"] == "NORMAL"
    # available 299_999 -> WATCH
    create_drawdown(pid, 1, purpose="r2")
    p = get_success_data(api_client.get_program(pid, pm_headers()))
    assert p["contingency_posture"] == "WATCH"
    # available 100_000 -> WATCH (0.10 inclusive)
    create_drawdown(pid, 199_999, purpose="r3")
    p = get_success_data(api_client.get_program(pid, pm_headers()))
    assert p["contingency_posture"] == "WATCH"
    # available 99_999 -> CRITICAL
    create_drawdown(pid, 1, purpose="r4")
    p = get_success_data(api_client.get_program(pid, pm_headers()))
    assert p["contingency_posture"] == "CRITICAL"
    assert p["contingency_available_cents"] == 99_999


def test_risk_exposure_rounding_precision(api):
    """PRD §2.8: "Wherever a computation produces a fractional cent, the
    result is rounded half-up to a whole cent." Applied to PRD §3.4's
    exposure formula probability_pct * impact_cents / 100.

    Design: Corner/calculations/risk_exposure_rounding_precision
    """
    prog = create_active_program(
        total_budget_cents=1_000_000, contingency_total_cents=100_000,
        lines=[{"cost_code": "CC-100", "amount_cents": 1_000_000}], name="P-PREC",
    )
    pid = prog["id"]
    # 33 * 100_001 / 100 = 33_000.33 -> round_half_up -> 33_000
    ra = create_risk_entry(pid, probability_pct=33, impact_cents=100_001,
                            title="RA", category="COST")
    assert ra["exposure_cents"] == 33_000
    # 25 * 2 / 100 = 0.5 -> round_half_up -> 1 (not banker's rounding)
    rb = create_risk_entry(pid, probability_pct=25, impact_cents=2,
                            title="RB", category="COST")
    assert rb["exposure_cents"] == 1


def test_owner_report_snapshot_frozen_after_accept(api):
    """PRD §3.6: "The Owner accepts, moving SUBMITTED → ACCEPTED, subject to
    the segregation check that the accepter's X-User-ID differs from
    submitted_by_user_id (else ERR_SEGREGATION_OF_DUTIES, 403); acceptance
    records accepted_by_user_id and the accepted_at timestamp and permanently
    freezes the snapshot." And §3.3 link 4: "reports in RETURNED are not
    refreshed, and SUBMITTED or ACCEPTED reports remain frozen per §3.6".

    Design: Corner/calculations/owner_report_snapshot_frozen_after_accept
    """
    prog = create_active_program(
        total_budget_cents=10_000_000, contingency_total_cents=1_000_000,
        lines=[{"cost_code": "CC-100", "amount_cents": 10_000_000}], name="P-FRZ",
    )
    pid = prog["id"]
    ct1 = create_and_execute_contract(pid, 4_500_000,
                                       solicitation_estimate_cents=4_500_000,
                                       vendor_name="V1", contract_type="CONTRACTOR")
    rep = create_owner_report(pid, period="2026-08")
    submit_owner_report(rep["id"], pm_id="pm-1")
    accepted = accept_owner_report(rep["id"], owner_id="owner-1")
    assert accepted["status"] == "ACCEPTED"
    # Later CO approval cascade must NOT rewrite the ACCEPTED snapshot
    co = create_change_order(ct1["id"], amount_cents=100_000, title="CO", reason="r")
    submit_change_order(co["id"])
    recommend_change_order(co["id"], recommendation="APPROVE", analysis_note="ok")
    decide_change_order(co["id"], decision="APPROVE")
    final = get_success_data(api_client.get_owner_report(rep["id"], pm_headers()))
    assert final["status"] == "ACCEPTED"
    assert final["accepted_at"] is not None
    # Frozen at the pre-CO commitment 4_500_000, even though commitment is now 4_600_000
    assert final["eac_commitment_based_cents"] == 4_500_000


def test_forecast_input_set_excludes_terminal_risks(api):
    """PRD §3.6: "The risk set: entries in ASSESSED, MITIGATING, MONITORING,
    or ESCALATED. IDENTIFIED entries are excluded as unassessed; REALIZED and
    CLOSED entries are excluded as resolved."

    Design: Corner/calculations/forecast_input_set_excludes_terminal_risks
    """
    prog = create_active_program(
        total_budget_cents=10_000_000, contingency_total_cents=1_000_000,
        lines=[{"cost_code": "CC-100", "amount_cents": 10_000_000}], name="P-FILT",
    )
    pid = prog["id"]
    r1 = create_risk_entry(pid, probability_pct=50, impact_cents=400_000,
                            title="R1", category="COST")
    assess_risk(r1["id"], 50, 400_000)  # exposure 200_000
    rep_aug = create_owner_report(pid, period="2026-08")
    assert rep_aug["eac_commitment_based_cents"] == 200_000  # ASSESSED risk included
    # Closing the risk excludes it from the input set
    close_risk(r1["id"])
    rep_sep = create_owner_report(pid, period="2026-09")
    assert rep_sep["eac_commitment_based_cents"] == 0  # CLOSED excluded
    # Risk close is not a fiscal-cascade refresh trigger for the pre-existing DRAFT
    # (the cascade trigger is pool/posture/commitment change per §3.6).
    # The existing report retains its value unless refreshed by a fiscal cascade.
    rep_aug_now = get_success_data(api_client.get_owner_report(rep_aug["id"], pm_headers()))
    assert rep_aug_now["eac_commitment_based_cents"] == 200_000
