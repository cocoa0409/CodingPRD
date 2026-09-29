"""The assigned-risk headcount is a derived count, and rescission gives it back."""
from test_helpers import (
    api_client,
    assignment_for_application,
    bootstrap_plan,
    bring_application_to_certified,
    create_rescission_payload,
    make_plan_administrator_headers,
    read_application,
    read_assignment,
    read_assignment_cycle,
    read_carrier,
    read_plan_period,
    run_cycle,
    schedule_cycle,
    validate_paginated,
    validate_success,
)

ADMIN_HEADERS = make_plan_administrator_headers()

LIVE_ASSIGNMENT_STATUSES = {"PENDING_ACCEPTANCE", "ACCEPTED", "POLICY_ISSUED"}


def _one_risk_designated_to_atlas_and_not_yet_accepted():
    """Certify one risk, run the cycle, and leave the designation untaken."""
    env = bootstrap_plan()
    atlas, beacon = env["carriers"]
    risk = bring_application_to_certified(env, document_prefix="DEC-28")
    period = read_plan_period(env["plan_period"]["id"])
    assert period["total_assignable_units"] == 1
    assert read_carrier(atlas["id"])["quota_target_units"] == 1
    assert read_carrier(beacon["id"])["quota_target_units"] == 0
    cycle = schedule_cycle(env["plan_period"]["id"])
    run_cycle(cycle["id"])
    assignment = assignment_for_application(risk["application"]["id"])
    assert assignment["carrier_id"] == atlas["id"]
    assert assignment["status"] == "PENDING_ACCEPTANCE"
    atlas_holding = read_carrier(atlas["id"])
    assert atlas_holding["assigned_risk_count"] == 1
    assert atlas_holding["quota_variance_units"] == 0.0
    assert atlas_holding["posture"] == "OPEN"
    return env, atlas, beacon, risk, cycle, assignment


def _rescind(assignment_id: str):
    return validate_success(api_client.rescind_assignment(
        assignment_id, create_rescission_payload("ASSIGNMENT_ERROR"), ADMIN_HEADERS))


def test_rescinding_the_designation_gives_the_headcount_back_and_requeues_the_risk():
    """The carrier is made whole and the application returns to the queue.

    An administrative rescission for plan error moves the assignment out of the live
    set, so Atlas's headcount drops back to zero and it once again sits a whole unit
    below its target of one — a variance of -1.0 with no overallocation. The risk
    goes back to awaiting assignment, and because the reason was plan error rather
    than a missed deadline the carrier keeps its full score of 100 and stays open.

    PRD: "A rescission moves the assignment to `RESCINDED`, returns its application
    to `CERTIFIED_AWAITING_ASSIGNMENT` so the risk re-enters the queue and can be
    placed by the next cycle run, lowers the designated carrier's
    `assigned_risk_count` by 1, and recomputes that carrier's `quota_variance_units`,
    `overallocated` and `posture`."
    Design: Difficulty/compensating_invariant/assigned_risk_headcount_conserved_across_placement_and_rescission
    """
    _, atlas, beacon, risk, _, assignment = _one_risk_designated_to_atlas_and_not_yet_accepted()

    _rescind(assignment["id"])

    rescinded = read_assignment(assignment["id"])
    assert rescinded["status"] == "RESCINDED"
    assert rescinded["rescission_reason_code"] == "ASSIGNMENT_ERROR"
    atlas_after = read_carrier(atlas["id"])
    assert atlas_after["assigned_risk_count"] == 0
    assert read_carrier(beacon["id"])["assigned_risk_count"] == 0
    assert atlas_after["quota_variance_units"] == -1.0
    assert atlas_after["overallocated"] is False
    assert atlas_after["posture"] == "OPEN"
    assert atlas_after["performance_score"] == 100
    assert read_application(risk["application"]["id"])["status"] == \
        "CERTIFIED_AWAITING_ASSIGNMENT"


def test_the_headcount_still_equals_the_live_assignment_count_and_the_cycle_is_not_rewound():
    """The invariant holds on both sides of the rescission, and history is preserved.

    The headcount is not an independent counter but a count of the carrier's live
    assignments, so after the rescission the sum of both carriers' headcounts equals
    the number of assignments still in one of the three live statuses — zero. The
    audit record is not edited to match: the cycle still reports the one placement
    it made, and the period still has its one assignable unit to apportion.

    PRD: "`assigned_risk_count` is the number of the carrier's assignments whose
    status is `PENDING_ACCEPTANCE`, `ACCEPTED` or `POLICY_ISSUED`."
    Design: Difficulty/compensating_invariant/assigned_risk_headcount_conserved_across_placement_and_rescission
    """
    env, atlas, beacon, _, cycle, assignment = \
        _one_risk_designated_to_atlas_and_not_yet_accepted()
    before_rows, _ = validate_paginated(api_client.list_assignments(ADMIN_HEADERS))
    assert (read_carrier(atlas["id"])["assigned_risk_count"]
            + read_carrier(beacon["id"])["assigned_risk_count"]
            == len([r for r in before_rows if r["status"] in LIVE_ASSIGNMENT_STATUSES]))

    _rescind(assignment["id"])

    after_rows, _ = validate_paginated(api_client.list_assignments(ADMIN_HEADERS))
    live = [row for row in after_rows if row["status"] in LIVE_ASSIGNMENT_STATUSES]
    headcount_total = (read_carrier(atlas["id"])["assigned_risk_count"]
                       + read_carrier(beacon["id"])["assigned_risk_count"])
    assert headcount_total == len(live)
    assert headcount_total == 0
    completed = read_assignment_cycle(cycle["id"])
    assert completed["status"] == "COMPLETED"
    assert completed["assigned_count"] == 1
    assert read_plan_period(env["plan_period"]["id"])["total_assignable_units"] == 1
