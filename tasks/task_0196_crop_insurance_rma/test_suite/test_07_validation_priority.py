"""Deterministic validation ordering when two checks both apply (PRD §2.9).

Each test arranges a request that violates two rules at once and asserts the
higher-priority error is the one returned.
"""
import pytest
from test_helpers import (
    validate_error, get_success_data,
    setup_reported_unit,
    file_loss_claim, make_lossadjuster_headers,
)


def test_invalid_state_beats_segregation_on_loss_approve(api):
    """PRD §2.9: "Only after those four gates does the optimistic concurrency check run
    (ERR_STALE_VERSION), followed by the state-machine check that the target resource is
    in a state from which the requested transition is defined (ERR_INVALID_STATE).
    Domain-specific business rules — segregation of duties, adjuster assignment,
    harvest-price availability, program openness, deadline gating, and acreage arithmetic
    — are evaluated after those structural gates."

    Design: Difficulty/priority_pair_validation_conflict/priority_state_invalid_beats_segregation
    """
    # Claim is DRAFT (never submitted) -> wrong state for approve. The acting adjuster's
    # id equals the selling agent's id, which would also trip segregation. State (p6)
    # precedes business_safety (p7), so ERR_INVALID_STATE is returned.
    ctx = setup_reported_unit(plan_type="YP", acres=100, share=1, publish_harvest=5.20)
    sa_id = ctx["sa"]["id"]
    # assigned_adjuster_id is the selling agent; claim left in DRAFT.
    claim = file_loss_claim(ctx["unit"]["id"], sa_id, ctx["sa_headers"],
                            production_to_count_bu=10000)
    res = api.approve_loss_claim(claim["id"], make_lossadjuster_headers(sa_id))
    validate_error(res, "ERR_INVALID_STATE")
    after = get_success_data(api.get_loss_claim(claim["id"], ctx["sa_headers"]))
    assert after["status"] == "DRAFT", after["status"]


def test_segregation_fires_when_state_is_valid(api):
    """PRD §3.6: "the segregation-of-duties guarantee — the acting adjuster must not be the
    selling agent_id of the unit's policy (else ERR_SEGREGATION_OF_DUTIES); for these two
    checks the assigned-adjuster check is evaluated before the segregation check."

    Design: Difficulty/priority_pair_validation_conflict/priority_state_invalid_beats_segregation
    """
    # When the state is valid (UNDER_REVIEW) the lower-priority segregation check is
    # reachable: a claim assigned to the selling agent, submitted to UNDER_REVIEW, then
    # approved by that same selling agent trips segregation (assigned check passes first).
    ctx = setup_reported_unit(plan_type="YP", acres=100, share=1, publish_harvest=5.20,
                              clock="2026-06-01T00:00:00Z")
    sa_id = ctx["sa"]["id"]
    claim = file_loss_claim(ctx["unit"]["id"], sa_id, ctx["sa_headers"],
                            production_to_count_bu=10000)
    api.submit_loss_claim(claim["id"], ctx["sa_headers"])
    res = api.approve_loss_claim(claim["id"], make_lossadjuster_headers(sa_id))
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES")


def test_program_not_open_beats_acreage_over_report(api):
    """PRD §3.3: "The referenced commodity program must be in OPEN status at creation time
    — electing against a program that is not open is rejected with ERR_PROGRAM_NOT_OPEN."

    Design: Difficulty/priority_pair_validation_conflict/priority_program_not_open_beats_acreage_over_report
    """
    # Program OPENed then CLOSED; creating an election against it fails at the openness
    # gate before any downstream over-report constraint could apply.
    from test_helpers import (
        register_selling_agent, register_producer, create_program, create_policy,
        make_agent_headers,
    )
    sa = register_selling_agent(license_number="SA-CLOSED")
    producer = register_producer(tax_id="TX-CLOSED")
    program = create_program(status="CLOSED")  # opened then closed; no open elections
    sa_headers = make_agent_headers(sa["id"])
    policy = create_policy(producer["id"], sa["id"], sa_headers)
    res = api.create_coverage_election(
        {"policy_id": policy["id"], "commodity_program_id": program["id"],
         "plan_type": "YP", "aph_yield": 180, "coverage_level": 0.75},
        sa_headers)
    validate_error(res, "ERR_PROGRAM_NOT_OPEN")


def test_over_report_constraint_reachable_against_open_program(api):
    """PRD §3.5: "the sum of planted_acres and prevented_acres may not exceed the unit's
    acres, and a sum that exceeds the insured acreage is rejected with
    ERR_ACREAGE_OVER_REPORTED."

    Design: Difficulty/priority_pair_validation_conflict/priority_program_not_open_beats_acreage_over_report
    """
    # Against an OPEN program the election is created and a unit added, so the downstream
    # over-report constraint is reachable: it fires only once the openness gate has passed.
    from test_helpers import setup_election_with_unit
    ctx = setup_election_with_unit(plan_type="YP", acres=100, share=1,
                                   clock="2026-06-01T00:00:00Z")
    res = api.create_acreage_report(
        {"unit_id": ctx["unit"]["id"], "planted_acres": 70, "prevented_acres": 40,
         "planting_date": "2026-05-10T00:00:00Z",
         "expected_unit_version": ctx["unit"]["version"]},
        ctx["sa_headers"])
    validate_error(res, "ERR_ACREAGE_OVER_REPORTED")
