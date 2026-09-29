"""Difficulty rule: compensating_invariant.

Both conserved counters are driven up and then brought back down by their
compensating action, and each must land on exactly its pre-change value with
zero drift.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prd_bench_local_runner.testing import (  # noqa: E402
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import ERR_TRANSITION_NOT_ALLOWED  # noqa: E402
from test_helpers.assertions import (  # noqa: E402
    assert_contractor_posture,
    assert_grant_state,
    assert_instant_equals,
    assert_prequalification_state,
    assert_site_posture,
    reconcile_granted_worker_count,
    reconcile_open_deficiency_count,
)
from test_helpers.constants import INITIAL_CLOCK  # noqa: E402
from test_helpers.factories import (  # noqa: E402
    improvement_plan_decision_payload,
    improvement_plan_payload,
    improvement_plan_submit_payload,
    revoke_payload,
)


def _two_badged_workers(build):
    """Dana and Marco both badged onto PLANT-7 through the same standing."""
    build.set_clock(INITIAL_CLOCK)
    scenario = build.graded_standing()
    second_worker = build.worker_with_qualifications(
        scenario["contractor_id"],
        ("OSHA10",),
        full_name="Marco Vela",
        employee_ref="EMP-1002",
    )
    scenario["second_worker"] = second_worker
    return scenario


def test_granted_worker_count_climbs_to_two_and_returns_to_zero(build, api):
    """0 to 1 to 2, then back to 1 and 0, reconciled at every step.

    PRD Section 2.10: "A grant followed by its compensating revocation must
    return the field to its exact pre-grant value, and a revocation never drives
    the field below 0."

    Design: Difficulty/compensating_invariant/site_granted_worker_count_returns_to_zero_after_two_grants_and_two_revokes_and_never_goes_negative
    """
    scenario = _two_badged_workers(build)
    site_id = scenario["site_id"]
    manager = scenario["manager_headers"]

    assert reconcile_granted_worker_count(api, manager, site_id) == 0

    first = build.grant_badge(
        scenario["worker_id"], site_id, scenario["prequalification_id"], scenario["contractor_id"]
    )
    assert reconcile_granted_worker_count(api, manager, site_id) == 1

    second = build.grant_badge(
        scenario["second_worker"]["id"],
        site_id,
        scenario["prequalification_id"],
        scenario["contractor_id"],
    )
    assert reconcile_granted_worker_count(api, manager, site_id) == 2

    build.revoke_badge(first["id"], scenario["client_id"])
    assert reconcile_granted_worker_count(api, manager, site_id) == 1

    build.revoke_badge(second["id"], scenario["client_id"])
    assert reconcile_granted_worker_count(api, manager, site_id) == 0

    site = validate_success(api.get_site(site_id, manager))
    assert_site_posture(site, granted_worker_count=0, access_gate_status="OPEN")


def test_redundant_revocation_is_refused_and_never_drives_the_count_negative(build, api):
    """A third revoke on an already revoked badge cannot move the counter.

    PRD Section 3.8: "Revocation is the client manager's lever. It requires the
    grant to be in `GRANTED`, else `ERR_TRANSITION_NOT_ALLOWED`, and it accepts
    an optional `revocation_reason` which defaults to `CLIENT_REVOKED` when
    omitted."

    Design: Difficulty/compensating_invariant/site_granted_worker_count_returns_to_zero_after_two_grants_and_two_revokes_and_never_goes_negative
    """
    scenario = _two_badged_workers(build)
    site_id = scenario["site_id"]
    manager = scenario["manager_headers"]

    first = build.grant_badge(
        scenario["worker_id"], site_id, scenario["prequalification_id"], scenario["contractor_id"]
    )
    second = build.grant_badge(
        scenario["second_worker"]["id"],
        site_id,
        scenario["prequalification_id"],
        scenario["contractor_id"],
    )
    build.revoke_badge(first["id"], scenario["client_id"])
    build.revoke_badge(second["id"], scenario["client_id"])

    response = api.revoke_grant(second["id"], revoke_payload("CLIENT_REVOKED"), manager)
    validate_error(response, ERR_TRANSITION_NOT_ALLOWED, 409)

    site = validate_success(api.get_site(site_id, manager))
    assert_site_posture(site, granted_worker_count=0)
    assert reconcile_granted_worker_count(api, manager, site_id) == 0

    granted_rows, granted_meta = validate_paginated(
        api.list_grants(manager, {"site_id": site_id, "status": "GRANTED"})
    )
    assert granted_meta["total_count"] == 0
    assert granted_rows == []

    all_rows, all_meta = validate_paginated(
        api.list_grants(manager, {"site_id": site_id})
    )
    assert all_meta["total_count"] == 2, (
        f"expected two historical grant rows, got {all_meta['total_count']}"
    )
    for row in all_rows:
        assert_grant_state(row, status="REVOKED")


def test_conditional_grading_raises_the_deficiency_count_and_the_plan_snapshots_it(build, api):
    """The counter goes 0 to 1, and the plan freezes the code list.

    PRD Section 3.7: "Creating a plan snapshots the row's current
    `deficiency_codes` into the plan's own `deficiency_codes` array, so the plan
    permanently records what it was meant to fix even after the row's list is
    cleared."

    Design: Difficulty/compensating_invariant/contractor_open_deficiency_count_returns_to_its_pre_grading_value_after_an_accepted_improvement_plan
    """
    build.set_clock(INITIAL_CLOCK)
    scenario = build.graded_standing(statistic_overrides={"emr": 1.01}, grade=False)

    # The pre-grading value of the conserved counter.
    assert (
        reconcile_open_deficiency_count(
            api, scenario["admin_headers"], scenario["contractor_id"]
        )
        == 0
    )

    graded = build.grade_prequalification(
        scenario["prequalification_id"], scenario["client_id"]
    )
    assert_prequalification_state(
        graded, status="CONDITIONAL", grade="B", deficiency_codes=["EMR"]
    )
    assert (
        reconcile_open_deficiency_count(
            api, scenario["admin_headers"], scenario["contractor_id"]
        )
        == 1
    )

    plan = validate_success(
        api.create_improvement_plan(
            scenario["prequalification_id"],
            improvement_plan_payload(
                expected_prequalification_version=graded["version"],
                due_date="2026-10-01T00:00:00Z",
                milestone_count=3,
            ),
            scenario["manager_headers"],
        ),
        201,
    )
    assert plan["status"] == "OPEN"
    assert plan["deficiency_codes"] == ["EMR"], (
        f"expected the plan to snapshot ['EMR'], got {plan['deficiency_codes']}"
    )
    assert plan["evidence_ref"] is None

    # Creating a plan advances the prequalification's own version by exactly 1.
    after_plan = build.read_prequalification(scenario["prequalification_id"])
    assert after_plan["version"] == graded["version"] + 1, (
        f"expected version {graded['version'] + 1}, got {after_plan['version']}"
    )


def test_accepted_plan_returns_the_deficiency_count_to_its_pre_grading_value(build, api):
    """Acceptance is the compensating action and lands back on exactly 0.

    PRD Section 3.7: "It then recomputes the contractor's
    `open_deficiency_count`, which by the conservation rule of Section 2.10 must
    land back on exactly the value it held before the conditional grading, with
    zero drift."

    Design: Difficulty/compensating_invariant/contractor_open_deficiency_count_returns_to_its_pre_grading_value_after_an_accepted_improvement_plan
    """
    build.set_clock(INITIAL_CLOCK)
    scenario = build.graded_standing(statistic_overrides={"emr": 1.01})
    pq_id = scenario["prequalification_id"]

    graded = scenario["prequalification"]
    plan = validate_success(
        api.create_improvement_plan(
            pq_id,
            improvement_plan_payload(
                expected_prequalification_version=graded["version"],
                due_date="2026-10-01T00:00:00Z",
                milestone_count=3,
            ),
            scenario["manager_headers"],
        ),
        201,
    )
    validate_success(
        api.submit_improvement_plan(
            plan["id"],
            improvement_plan_submit_payload("EMR-REMEDIATION-PACKET-1"),
            scenario["contractor_headers"],
        )
    )
    accepted = validate_success(
        api.decide_improvement_plan(
            plan["id"],
            improvement_plan_decision_payload("ACCEPT"),
            scenario["manager_headers"],
        )
    )
    assert accepted["status"] == "ACCEPTED"
    assert_instant_equals(accepted["closed_at"], INITIAL_CLOCK)

    row = build.read_prequalification(pq_id)
    assert_prequalification_state(
        row,
        status="UNDER_REVIEW",
        grade=None,
        deficiency_codes=[],
        final_composite_score=None,
    )
    assert row["effective_thresholds"] is None
    assert row["conditional_expires_at"] is None
    assert_instant_equals(row["expires_at"], "2027-08-01T00:00:00Z")

    assert_contractor_posture(
        build.read_contractor(scenario["contractor_id"]), open_deficiency_count=0
    )
    assert (
        reconcile_open_deficiency_count(
            api, scenario["admin_headers"], scenario["contractor_id"]
        )
        == 0
    )

    _rows, meta = validate_paginated(
        api.list_prequalifications(
            scenario["admin_headers"],
            {"contractor_id": scenario["contractor_id"], "status": "CONDITIONAL"},
        )
    )
    assert meta["total_count"] == 0, (
        f"expected no CONDITIONAL rows after the cure, got {meta['total_count']}"
    )
