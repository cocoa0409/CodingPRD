"""Queue B — complexity_layers section corner tests (non-stub only)."""
from test_helpers import (
    api_client, validate_error, validate_success, get_success_data,
    create_program, create_charter_payload, create_baseline_payload,
    create_active_program, create_and_execute_contract,
    create_owner_report, submit_owner_report, return_owner_report,
    create_change_order, submit_change_order, recommend_change_order,
    decide_change_order,
    pm_headers, owner_headers,
    ApiErrorId,
)


def test_charter_approve_stale_program_version_rejected(api):
    """PRD §2.6: "The charter decision requires a non-optional
    expected_program_version field in the request body, carrying the client's
    last observed version of the program. If that value does not match the
    program's current version, the decision is rejected with
    ERR_STALE_PROGRAM_VERSION (HTTP 412)." And §3.1: "any previously APPROVED
    charter of the same program is automatically moved to SUPERSEDED by the
    system".

    Design: Corner/complexity_layers/charter_approve_stale_program_version_rejected
    """
    prog = create_program(name="P-OCC1")
    pid = prog["id"]
    c1 = get_success_data(api_client.create_charter(
        create_charter_payload(pid, objectives="c1", scope_statement="c1"), pm_headers()))
    api_client.submit_charter(c1["id"], pm_headers())
    c2 = get_success_data(api_client.create_charter(
        create_charter_payload(pid, objectives="c2", scope_statement="c2"), pm_headers()))
    api_client.submit_charter(c2["id"], pm_headers())
    pv = get_success_data(api_client.get_program(pid, pm_headers()))["version"]
    # Approve c1 (this advances Program.version)
    r1 = get_success_data(api_client.decide_charter(
        c1["id"], {"decision": "APPROVE", "expected_program_version": pv},
        owner_headers()))
    assert r1["status"] == "APPROVED"
    # Now decide c2 with the STALE pv
    resp = api_client.decide_charter(
        c2["id"], {"decision": "APPROVE", "expected_program_version": pv},
        owner_headers())
    validate_error(resp, ApiErrorId.ERR_STALE_PROGRAM_VERSION)
    # Re-read and retry
    pv2 = get_success_data(api_client.get_program(pid, pm_headers()))["version"]
    r2 = get_success_data(api_client.decide_charter(
        c2["id"], {"decision": "APPROVE", "expected_program_version": pv2},
        owner_headers()))
    assert r2["status"] == "APPROVED"
    c1_final = get_success_data(api_client.get_charter(c1["id"], pm_headers()))
    assert c1_final["status"] == "SUPERSEDED"


def test_baseline_approve_stale_program_version_rejected(api):
    """PRD §2.6: "The baseline decision likewise requires a non-optional
    expected_program_version, and a mismatch with the program's current
    version is rejected with ERR_STALE_PROGRAM_VERSION (HTTP 412)."

    Design: Corner/complexity_layers/baseline_approve_stale_program_version_rejected
    """
    prog = create_program(name="P-OCC2")
    pid = prog["id"]
    b1 = get_success_data(api_client.create_baseline(
        create_baseline_payload(pid, total_budget_cents=1_000_000,
                                 contingency_total_cents=100_000,
                                 lines=[{"cost_code": "CC-100", "amount_cents": 1_000_000}]),
        pm_headers()))
    api_client.submit_baseline(b1["id"], pm_headers())
    b2 = get_success_data(api_client.create_baseline(
        create_baseline_payload(pid, total_budget_cents=2_000_000,
                                 contingency_total_cents=200_000,
                                 target_finish_date="2027-06-30",
                                 lines=[{"cost_code": "CC-100", "amount_cents": 2_000_000}]),
        pm_headers()))
    api_client.submit_baseline(b2["id"], pm_headers())
    pv = get_success_data(api_client.get_program(pid, pm_headers()))["version"]
    r1 = get_success_data(api_client.decide_baseline(
        b1["id"], {"decision": "APPROVE", "expected_program_version": pv},
        owner_headers()))
    assert r1["status"] == "APPROVED"
    # Stale version on b2
    resp = api_client.decide_baseline(
        b2["id"], {"decision": "APPROVE", "expected_program_version": pv},
        owner_headers())
    validate_error(resp, ApiErrorId.ERR_STALE_PROGRAM_VERSION)
    # B1's values still in effect
    p = get_success_data(api_client.get_program(pid, pm_headers()))
    assert p["current_budget_cents"] == 1_000_000
    assert p["contingency_total_cents"] == 100_000
    assert p["baseline_version_no"] == 1


def test_program_version_increments_on_governance_events(api):
    """PRD §2.4: "version (integer): A system-managed integer that starts at
    1 at creation and increments by exactly 1 on every mutation of the
    resource." PRD §3.1: "Each charter receives a version_no..." and charter
    creation/submission "increments the parent Program.version by 1".

    Design: Corner/complexity_layers/program_version_increments_on_governance_events
    """
    prog = create_program(name="P-VER")
    pid = prog["id"]
    assert prog["version"] == 1
    ch = get_success_data(api_client.create_charter(
        create_charter_payload(pid), pm_headers()))
    p = get_success_data(api_client.get_program(pid, pm_headers()))
    assert p["version"] == 2
    api_client.submit_charter(ch["id"], pm_headers())
    p = get_success_data(api_client.get_program(pid, pm_headers()))
    assert p["version"] == 3


def test_returned_report_not_refreshed_until_resubmit(api):
    """PRD §3.6: "Reports in RETURNED are deliberately not refreshed by these
    cascades." And §3.3 cascade link 4: "the forecast fields of every
    OwnerReport in DRAFT for this program are recomputed (reports in RETURNED
    are not refreshed)". And §3.6: "Submission — moving DRAFT → SUBMITTED, or
    RETURNED → SUBMITTED on resubmission — first recomputes every forecast
    field from current program state, then freezes them while the report is
    SUBMITTED".

    Design: Corner/complexity_layers/returned_report_not_refreshed_until_resubmit
    """
    prog = create_active_program(
        total_budget_cents=10_000_000, contingency_total_cents=1_000_000,
        lines=[{"cost_code": "CC-100", "amount_cents": 10_000_000}], name="P-RECON",
    )
    pid = prog["id"]
    ct1 = create_and_execute_contract(pid, 4_500_000,
                                       solicitation_estimate_cents=4_500_000,
                                       vendor_name="V1", contract_type="CONTRACTOR")
    rep = create_owner_report(pid, period="2026-08")
    submit_owner_report(rep["id"], pm_id="pm-1")
    return_owner_report(rep["id"], return_note="revise", owner_id="owner-1")
    # CO approval cascade fires while the report is RETURNED
    co = create_change_order(ct1["id"], amount_cents=100_000, title="CO", reason="r")
    submit_change_order(co["id"])
    recommend_change_order(co["id"], recommendation="APPROVE", analysis_note="ok")
    decide_change_order(co["id"], decision="APPROVE")
    # RETURNED report is untouched
    ret = get_success_data(api_client.get_owner_report(rep["id"], pm_headers()))
    assert ret["status"] == "RETURNED"
    assert ret["eac_commitment_based_cents"] == 4_500_000
    # Resubmission recomputes from current state
    sub = submit_owner_report(rep["id"], pm_id="pm-1")
    assert sub["status"] == "SUBMITTED"
    assert sub["eac_commitment_based_cents"] == 4_600_000
