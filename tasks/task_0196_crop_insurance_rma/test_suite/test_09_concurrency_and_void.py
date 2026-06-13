"""Optimistic concurrency on guarded writes, and the election-void preconditions.

Covers the two OCC-guarded writes (acreage-report on Unit, election-void on Policy,
PRD §2.7), the unit version increment on a successful filing, and the cross-entity rule
that an election cannot be voided once any unit has an ACCEPTED report (PRD §3.3).
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    setup_election_with_unit, setup_policy_with_election,
    file_acreage_report, add_unit, create_election,
)


def test_acreage_report_with_stale_unit_version_rejected(api):
    """PRD §2.7: "a request to file an acreage report must carry expected_unit_version,
    holding the client's last observed version of the target Unit. If that value does not
    equal the unit's current version, the request is rejected with ERR_STALE_VERSION
    (HTTP 412)."

    Design: Corner/errors/acreage_report_stale_unit_version_returns_stale
    """
    ctx = setup_election_with_unit(plan_type="YP", acres=100, share=1,
                                   clock="2026-06-01T00:00:00Z")
    v0 = ctx["unit"]["version"]
    # First report A succeeds and advances the unit's version.
    file_acreage_report(ctx["unit"]["id"], ctx["sa_headers"], v0,
                        planted_acres=100, prevented_acres=0)
    # Report B carries the stale pre-A version v0.
    res = api.create_acreage_report(
        {"unit_id": ctx["unit"]["id"], "planted_acres": 80, "prevented_acres": 0,
         "planting_date": "2026-05-11T00:00:00Z", "expected_unit_version": v0},
        ctx["sa_headers"])
    validate_error(res, "ERR_STALE_VERSION")
    unit = get_success_data(api.get_unit(ctx["unit"]["id"], ctx["sa_headers"]))
    assert unit["planted_acres"] == 100, unit["planted_acres"]


def test_unit_version_increments_on_successful_acreage_report(api):
    """PRD §2.5: "Whenever the server mutates a resource ... that resource's updated_at is
    refreshed and its version is incremented, exactly as if the client had mutated it
    directly."
    PRD §3.5: "the owning policy's total_insured_acres is recomputed ... and the unit's
    version increments by one."

    Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_unit_acreage_report
    """
    ctx = setup_election_with_unit(plan_type="YP", acres=100, share=1,
                                   clock="2026-06-01T00:00:00Z")
    assert ctx["unit"]["version"] == 1, ctx["unit"]["version"]
    file_acreage_report(ctx["unit"]["id"], ctx["sa_headers"], ctx["unit"]["version"],
                        planted_acres=100, prevented_acres=0)
    unit = get_success_data(api.get_unit(ctx["unit"]["id"], ctx["sa_headers"]))
    assert unit["version"] == 2, unit["version"]
    assert unit["status"] == "REPORTED", unit["status"]


def test_void_election_with_stale_policy_version_rejected(api):
    """PRD §2.7: "The second guarded write is the voiding of a coverage election: that
    request must carry expected_policy_version, holding the client's last observed version
    of the owning Policy. If the policy's version has advanced since the client read it —
    because another election was voided ... the void is rejected with ERR_STALE_VERSION
    (HTTP 412)"

    Design: Corner/errors/void_election_with_stale_policy_version_returns_stale
    """
    ctx = setup_policy_with_election(plan_type="YP", aph_yield=180, coverage_level=0.75)
    elec_a = ctx["election"]
    elec_b = create_election(ctx["policy"]["id"], ctx["program"]["id"], ctx["sa_headers"],
                             plan_type="RP", aph_yield=180, coverage_level=0.75)
    policy = get_success_data(api.get_policy(ctx["policy"]["id"], ctx["sa_headers"]))
    pv = policy["version"]
    # Void A with the fresh version (bumps the policy version).
    validate_success(api.void_coverage_election(
        elec_a["id"], {"expected_policy_version": pv}, ctx["sa_headers"]), 200)
    # Void B with the now-stale pre-void version.
    res = api.void_coverage_election(
        elec_b["id"], {"expected_policy_version": pv}, ctx["sa_headers"])
    validate_error(res, "ERR_STALE_VERSION")
    after = get_success_data(api.get_coverage_election(elec_b["id"], ctx["sa_headers"]))
    assert after["status"] == "ELECTED", after["status"]


def test_election_void_blocked_by_reported_unit(api):
    """PRD §3.3: "A direct void is permitted only when no unit under the election has an
    ACCEPTED acreage report; if any unit is already reported, the void is rejected with
    ERR_ELECTION_ALREADY_REPORTED."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_election_void_blocked_by_reported_unit
    """
    # Two-unit election; unit 1 has an ACCEPTED report (REPORTED), unit 2 still PENDING.
    # The election is therefore still ELECTED (not all units reported), policy still DRAFT.
    ctx = setup_policy_with_election(plan_type="YP", aph_yield=180, coverage_level=0.75,
                                     clock="2026-06-01T00:00:00Z")
    unit1 = add_unit(ctx["election"]["id"], ctx["sa_headers"], unit_number="0001-0001",
                     acres=60, share=1)
    add_unit(ctx["election"]["id"], ctx["sa_headers"], unit_number="0001-0002",
             acres=40, share=1)
    file_acreage_report(unit1["id"], ctx["sa_headers"], unit1["version"],
                        planted_acres=60, prevented_acres=0)
    # Read the policy version AFTER adding the units (each add recomputes the policy
    # premium ledger and bumps the policy version, PRD §3.4). Voiding is OCC-guarded on
    # the owning policy's current version (PRD §2.7), which is checked before the
    # already-reported gate; passing a fresh version isolates the ERR_ELECTION_ALREADY_
    # REPORTED rule this test targets.
    policy = get_success_data(api.get_policy(ctx["policy"]["id"], ctx["sa_headers"]))
    pv = policy["version"]
    res = api.void_coverage_election(
        ctx["election"]["id"], {"expected_policy_version": pv}, ctx["sa_headers"])
    validate_error(res, "ERR_ELECTION_ALREADY_REPORTED")
    elec = get_success_data(api.get_coverage_election(ctx["election"]["id"], ctx["sa_headers"]))
    assert elec["status"] == "ELECTED", elec["status"]


def test_election_void_succeeds_when_no_unit_reported(api):
    """PRD §3.3: "An election that has not yet accumulated any reported acreage can be
    voided directly by an Agent, moving it from ELECTED to VOID. A direct void is permitted
    only when no unit under the election has an ACCEPTED acreage report"

    Design: Difficulty/cross_entity_state_dependency/cross_entity_election_void_blocked_by_reported_unit
    """
    # Same cross-entity gate, positive side: with a PENDING unit and no accepted report,
    # the void proceeds and the election becomes VOID.
    ctx = setup_election_with_unit(plan_type="YP", aph_yield=180, coverage_level=0.75,
                                   acres=100, share=1)
    policy = get_success_data(api.get_policy(ctx["policy"]["id"], ctx["sa_headers"]))
    res = validate_success(api.void_coverage_election(
        ctx["election"]["id"], {"expected_policy_version": policy["version"]},
        ctx["sa_headers"]), 200)
    assert res["status"] == "VOID", res["status"]
