"""A second upheld complaint suspends the carrier and requeues its pending risk."""
from test_helpers import (
    ATLAS,
    BEACON,
    accept_assignment,
    api_client,
    assignment_for_application,
    bootstrap_plan,
    bring_application_to_certified,
    create_resolution_payload,
    docket_complaint,
    issue_policy,
    make_compliance_examiner_headers,
    read_application,
    read_assignment,
    read_carrier,
    read_complaint,
    read_policy,
    record_findings,
    run_cycle,
    schedule_cycle,
    set_clock,
    uphold_one_complaint,
    validate_success,
)

SECOND_EXAMINER = "EX-2"

# Atlas holds nine tenths of the voluntary market, so largest-remainder
# apportionment gives it every assignable unit and Beacon none.
ATLAS_DOMINANT = dict(ATLAS, voluntary_market_share_bps=9000)
BEACON_MINOR = dict(BEACON, voluntary_market_share_bps=1000)


def _atlas_restricted_with_one_policy_and_one_pending_designation():
    """Atlas services one policy, holds one pending designation and sits at 80.

    The first risk is placed in the September cycle, accepted and written. The
    second risk is certified in October and placed by the October cycle, so it is
    still awaiting acceptance. One upheld complaint against the written policy
    then costs Atlas twenty points, and a second complaint is worked up to
    findings without being resolved.
    """
    env = bootstrap_plan(carriers=[ATLAS_DOMINANT, BEACON_MINOR])
    atlas, beacon = env["carriers"]
    first = bring_application_to_certified(
        env,
        applicant_overrides={"full_name": "Owen Pike", "driver_license_number": "D-99011"},
        vehicle_overrides={"vin": "1HGCM82633A004360"},
        document_prefix="DEC-16",
    )
    september = schedule_cycle(env["plan_period"]["id"])
    run_cycle(september["id"])
    first_assignment = assignment_for_application(first["application"]["id"])
    accept_assignment(first_assignment["id"], atlas["id"])
    set_clock("2026-09-15T00:00:00Z")
    policy = issue_policy(first_assignment["id"], atlas["id"], policy_number="AR-100004")

    set_clock("2026-10-05T00:00:00Z")
    second = bring_application_to_certified(
        env,
        applicant_overrides={"full_name": "Nadia Frost", "driver_license_number": "D-99012"},
        vehicle_overrides={"vin": "1HGCM82633A004361"},
        application_overrides={"requested_effective_date": "2026-10-20T00:00:00Z"},
        document_prefix="DEC-17",
    )
    october = schedule_cycle(env["plan_period"]["id"],
                             window_start="2026-10-02T00:00:00Z",
                             window_end="2026-10-31T00:00:00Z")
    run_cycle(october["id"])
    second_assignment = assignment_for_application(second["application"]["id"])
    assert second_assignment["carrier_id"] == atlas["id"]
    assert second_assignment["status"] == "PENDING_ACCEPTANCE"

    uphold_one_complaint(policy["id"], atlas["id"], complaint_type="CLAIM_HANDLING_DELAY",
                         narrative="Acknowledgement and contact standards not met.")
    assert read_carrier(atlas["id"])["posture"] == "RESTRICTED"
    second_complaint = docket_complaint(policy["id"], atlas["id"],
                                       complaint_type="SERVICE_STANDARD",
                                       narrative="Second substantiated servicing failure.")
    record_findings(second_complaint["id"])
    return {
        "atlas": atlas, "beacon": beacon, "policy": policy,
        "first_assignment": first_assignment,
        "second_application": second["application"],
        "second_assignment": second_assignment,
        "second_complaint": second_complaint,
    }


def _uphold(complaint_id: str):
    return validate_success(api_client.resolve_complaint(
        complaint_id, create_resolution_payload("UPHELD"),
        make_compliance_examiner_headers(SECOND_EXAMINER)))


def test_the_second_upheld_complaint_drops_the_score_to_sixty_and_suspends_the_carrier():
    """Two upheld complaints cost forty points, and sixty is the suspension rung.

    Atlas starts at 100, loses twenty on the first upheld complaint and twenty more
    on the second, landing on exactly 60. That is the score rung of the posture
    ladder, so its posture reports SUSPENDED even though its enrolment status is
    still ACTIVE — suspension is a posture, not a withdrawal.

    PRD: "Because two upheld complaints cost 40 points in total and the clamp is
    applied after each adjustment, a fresh carrier's first upheld complaint leaves
    it `RESTRICTED` at 80 and its second leaves it `SUSPENDED` at 60."
    Design: Difficulty/transitive_cascade/second_upheld_complaint_cascades_into_suspension_rescission_and_requeue
    """
    world = _atlas_restricted_with_one_policy_and_one_pending_designation()

    _uphold(world["second_complaint"]["id"])

    assert read_complaint(world["second_complaint"]["id"])["status"] == "RESOLVED_UPHELD"
    atlas = read_carrier(world["atlas"]["id"])
    assert atlas["upheld_complaint_count"] == 2
    assert atlas["performance_score"] == 60
    assert atlas["posture"] == "SUSPENDED"
    assert atlas["status"] == "ACTIVE"


def test_suspension_rescinds_the_pending_designation_and_returns_the_risk_to_the_queue():
    """The pending risk is pulled back, and the headcount drops with it.

    The cascade rides on the same request as the resolution. Atlas's untaken
    designation is rescinded as carrier-ineligible and its application goes back to
    awaiting assignment, so Atlas services one risk against a target of two — a
    variance of -1.0 and no overallocation. Beacon, which was entitled to nothing,
    is not handed the risk by this cascade.

    PRD: "If that recomputation lands the carrier in `SUSPENDED`, a cascade follows
    in the same request — every assignment of that carrier still in
    `PENDING_ACCEPTANCE` is moved to `RESCINDED` with a `rescission_reason_code` of
    `CARRIER_INELIGIBLE`, and each of those assignments' applications returns from
    `ASSIGNED` to `CERTIFIED_AWAITING_ASSIGNMENT` so the risks re-enter the queue"
    Design: Difficulty/transitive_cascade/second_upheld_complaint_cascades_into_suspension_rescission_and_requeue
    """
    world = _atlas_restricted_with_one_policy_and_one_pending_designation()

    _uphold(world["second_complaint"]["id"])

    rescinded = read_assignment(world["second_assignment"]["id"])
    assert rescinded["status"] == "RESCINDED"
    assert rescinded["rescission_reason_code"] == "CARRIER_INELIGIBLE"
    assert read_application(world["second_application"]["id"])["status"] == \
        "CERTIFIED_AWAITING_ASSIGNMENT"
    atlas = read_carrier(world["atlas"]["id"])
    assert atlas["assigned_risk_count"] == 1
    assert atlas["quota_variance_units"] == -1.0
    assert atlas["overallocated"] is False
    beacon = read_carrier(world["beacon"]["id"])
    assert beacon["assigned_risk_count"] == 0
    assert beacon["posture"] == "OPEN"


def test_resolving_the_complaint_lifts_the_freeze_and_leaves_the_written_policy_in_force():
    """The complaint that caused the suspension is no longer open against the policy.

    Both complaints are resolved, so the policy's open count falls back to zero and
    the freeze derived from it is off. The suspension reaches only untaken
    designations: the assignment that already produced a policy stays at
    POLICY_ISSUED and the policy itself remains in force.

    PRD: "Finally, the policy's `open_complaint_count` falls by 1 and
    `complaint_freeze_active` is re-derived from it."
    Design: Difficulty/transitive_cascade/second_upheld_complaint_cascades_into_suspension_rescission_and_requeue
    """
    world = _atlas_restricted_with_one_policy_and_one_pending_designation()

    _uphold(world["second_complaint"]["id"])

    policy = read_policy(world["policy"]["id"])
    assert policy["open_complaint_count"] == 0
    assert policy["complaint_freeze_active"] is False
    assert policy["policy_status"] == "IN_FORCE"
    assert read_assignment(world["first_assignment"]["id"])["status"] == "POLICY_ISSUED"
