"""A carrier withdrawal cascades into reassignment and overloads the receiver."""
from test_helpers import (
    ATLAS,
    BEACON,
    accept_assignment,
    api_client,
    assignment_for_application,
    assignments_for_application,
    bootstrap_plan,
    bring_application_to_certified,
    create_exit_notice_payload,
    issue_policy,
    make_plan_administrator_headers,
    read_assignment,
    read_carrier,
    read_policy,
    run_cycle,
    schedule_cycle,
    set_clock,
    validate_paginated,
    validate_success,
)

ADMIN_HEADERS = make_plan_administrator_headers()

# Atlas takes both units on an 8000-bps share. Beacon is the only other T02
# writer, so it is the whole candidate pool once Atlas withdraws, even though
# its 500-bps share entitles it to nothing. Cedar writes T01 only, so it can
# never receive a T02 risk however deficient it looks.
ATLAS_MAJORITY = dict(ATLAS, voluntary_market_share_bps=8000)
BEACON_SLIVER = dict(BEACON, voluntary_market_share_bps=500)
CEDAR_T01 = {"name": "Cedar Indemnity", "naic_code": "33333",
             "voluntary_market_share_bps": 1500, "licensed_territories": ["T01"]}

EXIT_EFFECTIVE_DATE = "2026-12-20T00:00:00Z"


def _atlas_holds_one_policy_and_one_accepted_assignment():
    """Place two T02 risks with Atlas, issue a policy on the first, accept both."""
    env = bootstrap_plan(carriers=[ATLAS_MAJORITY, BEACON_SLIVER, CEDAR_T01])
    atlas, beacon, cedar = env["carriers"]
    first = bring_application_to_certified(
        env,
        applicant_overrides={"full_name": "Owen Pike", "driver_license_number": "D-99011"},
        vehicle_overrides={"vin": "1HGCM82633A004360"},
        document_prefix="DEC-14",
    )
    second = bring_application_to_certified(
        env,
        applicant_overrides={"full_name": "Nadia Frost", "driver_license_number": "D-99012"},
        vehicle_overrides={"vin": "1HGCM82633A004361"},
        document_prefix="DEC-15",
    )
    cycle = schedule_cycle(env["plan_period"]["id"])
    run_cycle(cycle["id"])
    first_assignment = assignment_for_application(first["application"]["id"])
    second_assignment = assignment_for_application(second["application"]["id"])
    assert first_assignment["carrier_id"] == atlas["id"]
    assert second_assignment["carrier_id"] == atlas["id"]
    accept_assignment(first_assignment["id"], atlas["id"])
    accept_assignment(second_assignment["id"], atlas["id"])
    set_clock("2026-09-15T00:00:00Z")
    policy = issue_policy(first_assignment["id"], atlas["id"], policy_number="AR-100003")
    return {
        "env": env, "atlas": atlas, "beacon": beacon, "cedar": cedar,
        "first_application": first["application"], "first_assignment": first_assignment,
        "second_assignment": second_assignment, "policy": policy,
    }


def _file_exit_notice(carrier_id: str):
    return validate_success(api_client.file_carrier_exit_notice(
        carrier_id, create_exit_notice_payload(EXIT_EFFECTIVE_DATE), ADMIN_HEADERS))


def test_the_withdrawal_creates_a_successor_assignment_pointing_at_the_old_one():
    """The notice suspends the carrier, flags the policy and spawns a reassignment.

    Filing the notice moves Atlas out of ACTIVE, which is the top rung of the
    posture ladder and so reports SUSPENDED. Its in-force policy is flagged for
    transfer, and a successor assignment appears for the same application with no
    originating cycle, a REASSIGNMENT kind, the first batch position and a pointer
    back to the assignment the policy currently sits on.

    PRD: "Third, for each such policy — processed in ascending policy `created_at`
    order and stamped with `batch_sequence` running from 1 upward across the
    cascade — the plan creates a successor assignment whose `assignment_kind` is
    `REASSIGNMENT`, whose `assignment_cycle_id` is null because no cycle produced
    it, and whose `predecessor_assignment_id` points at the assignment the policy
    currently sits on."
    Design: Difficulty/transitive_cascade/carrier_exit_cascades_through_policy_reassignment_into_receiver_overallocation
    """
    world = _atlas_holds_one_policy_and_one_accepted_assignment()

    _file_exit_notice(world["atlas"]["id"])

    atlas = read_carrier(world["atlas"]["id"])
    assert atlas["status"] == "EXIT_NOTICED"
    assert atlas["posture"] == "SUSPENDED"
    policy = read_policy(world["policy"]["id"])
    assert policy["policy_status"] == "REASSIGNMENT_PENDING"
    assert policy["reassignment_required"] is True
    assert policy["carrier_id"] == world["atlas"]["id"]

    rows, meta = validate_paginated(api_client.list_assignments(
        ADMIN_HEADERS, params={"application_id": world["first_application"]["id"]}))
    assert meta["total_count"] == 2
    successor = [row for row in rows if row["assignment_kind"] == "REASSIGNMENT"][0]
    assert successor["carrier_id"] == world["beacon"]["id"]
    assert successor["predecessor_assignment_id"] == world["first_assignment"]["id"]
    assert successor["status"] == "PENDING_ACCEPTANCE"
    assert successor["assignment_cycle_id"] is None
    assert successor["batch_sequence"] == 1
    assert successor["deficit_score_at_selection"] == 0.0


def test_the_only_licensed_receiver_takes_the_risk_and_becomes_overallocated():
    """Beacon absorbs a risk it is entitled to none of, and the ladder demotes it.

    A deficit of zero does not disqualify Beacon, because it is the only licensed
    candidate left in T02 once Atlas is excluded. Withdrawal then removes Atlas
    from the denominator, so the two assignable units reapportion to Cedar on its
    larger share. Beacon ends up servicing one risk against a target of none — a
    variance of 1.0 — which makes it overallocated and therefore RESTRICTED even
    though its performance score is untouched at 100.

    PRD: "A deficit of zero or below does not disqualify a carrier: when it is the
    only licensed candidate it takes the risk and duly becomes overallocated."
    PRD: "with a total of 2 units and two active carriers holding 500 and 1500 basis
    points, the exact entitlements are 0.5 and 1.5, the floors are 0 and 1, one
    leftover unit remains, and the remainders tie at 0.5 each — so the tie is broken
    by market share and the 1500-basis-point carrier takes the leftover, giving
    targets of 0 and 2."
    Design: Difficulty/transitive_cascade/carrier_exit_cascades_through_policy_reassignment_into_receiver_overallocation
    """
    world = _atlas_holds_one_policy_and_one_accepted_assignment()

    _file_exit_notice(world["atlas"]["id"])

    beacon = read_carrier(world["beacon"]["id"])
    cedar = read_carrier(world["cedar"]["id"])
    assert beacon["assigned_risk_count"] == 1
    assert beacon["quota_target_units"] == 0
    assert cedar["quota_target_units"] == 2
    assert beacon["quota_variance_units"] == 1.0
    assert beacon["overallocated"] is True
    assert beacon["performance_score"] == 100
    assert beacon["posture"] == "RESTRICTED"
    assert cedar["quota_variance_units"] == -2.0
    assert cedar["posture"] == "OPEN"


def test_an_already_accepted_assignment_survives_the_withdrawal_cascade():
    """Only pending designations are rescinded, so the accepted one is left alone.

    Atlas's second assignment was accepted before the notice, so it is outside the
    fourth cascade step and keeps its ACCEPTED status with no rescission reason.
    Atlas therefore still counts both risks in its headcount, and only one
    successor assignment was ever created.

    PRD: "Fourth, every assignment of the withdrawing carrier still in
    `PENDING_ACCEPTANCE` is moved to `RESCINDED` with a `rescission_reason_code` of
    `CARRIER_INELIGIBLE`, and each of those applications returns to
    `CERTIFIED_AWAITING_ASSIGNMENT`."
    Design: Difficulty/transitive_cascade/carrier_exit_cascades_through_policy_reassignment_into_receiver_overallocation
    """
    world = _atlas_holds_one_policy_and_one_accepted_assignment()

    _file_exit_notice(world["atlas"]["id"])

    surviving = read_assignment(world["second_assignment"]["id"])
    assert surviving["status"] == "ACCEPTED"
    assert surviving["rescission_reason_code"] is None
    assert read_carrier(world["atlas"]["id"])["assigned_risk_count"] == 2
    successors = [row for row in assignments_for_application(
        world["first_application"]["id"]) if row["assignment_kind"] == "REASSIGNMENT"]
    assert len(successors) == 1
