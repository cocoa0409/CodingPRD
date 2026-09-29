"""An unlicensed market is recorded as a deferral, not raised as a failure."""
from test_helpers import (
    ATLAS,
    BEACON,
    api_client,
    bootstrap_plan,
    bring_application_to_certified,
    make_plan_administrator_headers,
    read_application,
    read_assignment_cycle,
    read_carrier,
    read_plan_period,
    schedule_cycle,
    validate_paginated,
    validate_success,
)

ADMIN_HEADERS = make_plan_administrator_headers()

# Neither carrier writes T02, and the single risk is garaged there, so the
# candidate pool for that risk is empty however healthy the carriers look.
ATLAS_T01_ONLY = dict(ATLAS, licensed_territories=["T01"])
BEACON_T01_ONLY = dict(BEACON, licensed_territories=["T01"])


def _certified_risk_no_carrier_can_write():
    """Certify one T02 risk into a period served only by T01 writers."""
    env = bootstrap_plan(carriers=[ATLAS_T01_ONLY, BEACON_T01_ONLY])
    risk = bring_application_to_certified(env, document_prefix="DEC-22")
    assert risk["vehicle"]["garaging_territory_code"] == "T02"
    assert read_plan_period(env["plan_period"]["id"])["total_assignable_units"] == 1
    cycle = schedule_cycle(env["plan_period"]["id"])
    return env, risk, cycle


def test_a_run_with_no_licensed_candidate_completes_and_defers_the_risk():
    """The run succeeds, counts the deferral and writes no assignment row.

    No carrier is licensed where the vehicle is garaged, so the pool is empty. The
    run still completes and stamps its clock, the deferred count rises to one while
    the assigned count stays at zero, the application lands on DEFERRED_NO_CARRIER,
    and no assignment exists to be listed.

    PRD: "If the candidate pool is empty, the application moves to
    `DEFERRED_NO_CARRIER`, the cycle's `deferred_count` rises by 1, no assignment
    row is created, no error is raised, and the run proceeds to the next
    application — an empty market is a fact to be recorded, not a request failure."
    Design: Difficulty/boundary_precision_check/empty_candidate_pool_defers_the_risk_without_raising_an_error
    """
    _, risk, cycle = _certified_risk_no_carrier_can_write()

    run = validate_success(api_client.run_assignment_cycle(cycle["id"], ADMIN_HEADERS))

    assert "error_id" not in run
    completed = read_assignment_cycle(cycle["id"])
    assert completed["status"] == "COMPLETED"
    assert completed["assigned_count"] == 0
    assert completed["deferred_count"] == 1
    assert completed["run_at"].startswith("2026-09-01T00:00:00")
    assert read_application(risk["application"]["id"])["status"] == "DEFERRED_NO_CARRIER"
    _, meta = validate_paginated(api_client.list_assignments(
        ADMIN_HEADERS, params={"application_id": risk["application"]["id"]}))
    assert meta["total_count"] == 0


def test_the_deferral_leaves_the_apportionment_standing_and_both_carriers_open():
    """The unit stays apportioned even though nobody could write it.

    Certification put one assignable unit into the period, and the apportionment
    still hands that unit to Atlas on its larger share. Neither carrier services
    anything, so Atlas sits a whole unit below its target without being
    overallocated, and both carriers remain open for future business.

    PRD: "`quota_variance_units` is the carrier's `assigned_risk_count` plus its
    `voluntary_credit_units`, less its `quota_target_units`, carried to 1 decimal
    place; a positive variance means the carrier is over-served."
    Design: Difficulty/boundary_precision_check/empty_candidate_pool_defers_the_risk_without_raising_an_error
    """
    env, _, cycle = _certified_risk_no_carrier_can_write()

    validate_success(api_client.run_assignment_cycle(cycle["id"], ADMIN_HEADERS))

    atlas = read_carrier(env["carriers"][0]["id"])
    beacon = read_carrier(env["carriers"][1]["id"])
    assert atlas["assigned_risk_count"] == 0
    assert beacon["assigned_risk_count"] == 0
    assert atlas["quota_target_units"] == 1
    assert atlas["quota_variance_units"] == -1.0
    assert atlas["overallocated"] is False
    assert atlas["posture"] == "OPEN"
    assert beacon["posture"] == "OPEN"
