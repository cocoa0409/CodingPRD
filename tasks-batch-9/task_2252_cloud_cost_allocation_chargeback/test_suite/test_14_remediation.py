"""Waste control: the auto-execution cascade and the two idle-detection boundaries."""

from test_helpers import (
    ADMIN_HEADERS,
    ANALYST_HEADERS,
    CONTROLLER_HEADERS,
    OWNER_5,
    assert_cents,
    assert_pct,
    assert_remediation_task,
    fixtures,
    find_by,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import AUGUST_FIFTH_UTC

WINDOW_EXPIRED_UTC = "2026-08-08T00:00:01Z"


def _auto_executable_task(api):
    """One idle 1000000-cent dev resource on Platform BU, notified and then stale.

    The savings plan is `ACTIVE` over all three July records, the scan is narrowed
    to Platform BU so only the idle resource is proposed, and the clock is pushed
    one second past the 72-hour window so the next sweep must act on it.
    """
    built = fixtures.discounted_compute_model(api, utilizations=[5.00, 80.00, 80.00])

    tasks = validate_success(
        api.run_idle_detection_scan({"business_unit_id": built["platform"]["id"]}, ANALYST_HEADERS)
    )
    assert len(tasks) == 1
    task = tasks[0]
    assert task["cloud_resource_id"] == built["resources"][0]["id"]
    assert_remediation_task(
        task,
        kind="IDLE_TERMINATE",
        status="PROPOSED",
        observed_utilization_pct=5.00,
        projected_savings_cents=1000000,
        waste_score=97.00,
        auto_remediation_eligible=True,
    )

    notified = fixtures.notified_remediation_task(api, task["id"])
    assert notified["status"] == "OWNER_NOTIFIED"
    assert notified["remediation_window_starts_at"].startswith("2026-08-05T00:00:00")
    assert notified["remediation_window_ends_at"].startswith("2026-08-08T00:00:00")

    fixtures.set_clock(api, WINDOW_EXPIRED_UTC)
    built["task"] = notified
    return built


def test_an_expired_window_on_an_eligible_task_terminates_the_whole_resource_chain(api):
    """The sweep books the savings and drives resource, request and record together.

    PRD §3.8: "An `IDLE_TERMINATE` task moves the resource `FLAGGED_IDLE →
    TERMINATED`, which is the deepest cascade in the system:
    `monthly_run_rate_cents` is set to 0; every cost record whose
    `cloud_resource_id` is this resource and whose `allocation_state` is
    `UNALLOCATED` or `ALLOCATED` is set to `REVERSED`; each reversed record that
    carries an `applied_commitment_id` drops out of that commitment's
    `covered_spend_cents`, which recomputes that commitment's `utilization_pct`
    and `waste_cents` and may move it to `UNDER_UTILIZED`; the owning
    provisioning request bubbles `PROVISIONED → TERMINATED`; and the owning
    business unit's `resource_count`, `tracked_run_rate_cents` and
    `direct_spend_cents` are all recomputed."

    Design: Difficulty/transitive_cascade/auto_remediation_sweep_cascades_task_to_resource_to_records_to_commitment
    """
    built = _auto_executable_task(api)
    idle_resource = built["resources"][0]

    swept = validate_success(api.run_remediation_window_sweep(ANALYST_HEADERS))
    assert len(swept) == 1
    assert swept[0]["id"] == built["task"]["id"]
    assert swept[0]["status"] == "AUTO_EXECUTED"
    assert_cents(swept[0]["realized_savings_cents"], 1000000, "realized_savings_cents")

    terminated = validate_success(api.get_cloud_resource(idle_resource["id"], ANALYST_HEADERS))
    assert terminated["lifecycle_state"] == "TERMINATED"
    assert_cents(terminated["monthly_run_rate_cents"], 0, "monthly_run_rate_cents")

    request = validate_success(
        api.get_provisioning_request(idle_resource["provisioning_request_id"], ANALYST_HEADERS)
    )
    assert request["status"] == "TERMINATED"

    reversed_record = validate_success(
        api.get_cost_record(built["records"][0]["id"], CONTROLLER_HEADERS)
    )
    assert reversed_record["allocation_state"] == "REVERSED"

    for record in built["records"][1:]:
        survivor = validate_success(api.get_cost_record(record["id"], CONTROLLER_HEADERS))
        assert survivor["allocation_state"] == "UNALLOCATED"
        assert_cents(survivor["effective_cost_cents"], 7322, "effective_cost_cents")

    for resource in built["resources"][1:]:
        untouched = validate_success(api.get_cloud_resource(resource["id"], ANALYST_HEADERS))
        assert untouched["lifecycle_state"] == "ACTIVE"


def test_the_reversal_drops_the_record_out_of_the_commitments_coverage(api):
    """Losing 10100 cents of covered spend takes utilization from 84.17 to 56.11.

    PRD §3.4: "The `ACTIVE → UNDER_UTILIZED` move can also arrive as a system
    cascade rather than an explicit evaluation: when a covered cost record is
    reversed it drops out of `covered_spend_cents`, and if that pushes
    `utilization_pct` below the target the commitment slides into
    `UNDER_UTILIZED` on its own."

    Design: Difficulty/transitive_cascade/auto_remediation_sweep_cascades_task_to_resource_to_records_to_commitment
    """
    built = _auto_executable_task(api)
    commitment_id = built["commitment"]["id"]

    before = validate_success(api.get_commitment(commitment_id, CONTROLLER_HEADERS))
    assert before["status"] == "ACTIVE"
    assert_pct(before["utilization_pct"], 84.17, "utilization_pct")

    validate_success(api.run_remediation_window_sweep(ANALYST_HEADERS))

    after = validate_success(api.get_commitment(commitment_id, CONTROLLER_HEADERS))
    assert after["status"] == "UNDER_UTILIZED"
    assert_cents(after["covered_spend_cents"], 20200, "covered_spend_cents")
    assert_cents(after["waste_cents"], 15800, "waste_cents")
    assert_pct(after["utilization_pct"], 56.11, "utilization_pct")

    platform = validate_success(api.get_business_unit(built["platform"]["id"], ADMIN_HEADERS))
    assert platform["resource_count"] == 1
    assert_cents(platform["tracked_run_rate_cents"], 30000, "tracked_run_rate_cents")


def _lab_unit_with_four_resources(api):
    """Four dev resources at the edges of the run-rate floor and the idle threshold.

    They are created in descending run-rate order — 1000000, 1000000, 20000 and
    19999 cents — and their reported utilizations are 5.00, 5.01, 5.00 and 5.00,
    so only the second one sits above the idle line.
    """
    fixtures.set_clock(api, AUGUST_FIFTH_UTC)
    unit = fixtures.create_chargeback_unit(api, "Lab BU", "CC-500", headcount=8)
    policy = fixtures.create_active_policy(api, "core-tags")

    specs = (
        ("sandbox-a", 1000000, 5.00),
        ("sandbox-b", 1000000, 5.01),
        ("sandbox-c", 20000, 5.00),
        ("sandbox-d", 19999, 5.00),
    )
    resources = {}
    for application, run_rate, utilization_pct in specs:
        resource = fixtures.provision_resource(
            api,
            policy["id"],
            unit["id"],
            OWNER_5,
            resource_kind="COMPUTE",
            requested_tags={"team": "lab", "environment": "dev", "application": application},
            monthly_run_rate_cents=run_rate,
        )
        fixtures.set_utilization(api, resource["id"], utilization_pct)
        resources[application] = resource
    return {"unit": unit, "resources": resources}


def test_utilization_of_exactly_five_percent_is_idle_and_five_point_zero_one_is_oversized(api):
    """One hundredth of a percent turns a termination proposal into a rightsizing one.

    PRD §3.8: "Above that floor, utilization decides the verdict: a resource
    whose `utilization_pct` is at or below 5.00 is idle and draws an
    `IDLE_TERMINATE` proposal whose `projected_savings_cents` is the full
    `monthly_run_rate_cents`, rounded half up to whole cents; a resource whose
    `utilization_pct` is above 5.00 but at or below 30.00 is oversized and draws
    a `RIGHTSIZE` proposal whose `projected_savings_cents` is half of
    `monthly_run_rate_cents`, rounded half up to whole cents; a resource above
    30.00 is left alone."

    Design: Difficulty/boundary_precision_check/idle_threshold_exact_five_percent_versus_five_point_zero_one
    """
    built = _lab_unit_with_four_resources(api)
    resources = built["resources"]

    tasks = validate_success(
        api.run_idle_detection_scan({"business_unit_id": built["unit"]["id"]}, ANALYST_HEADERS)
    )
    assert len(tasks) == 3
    assert [task["cloud_resource_id"] for task in tasks] == [
        resources["sandbox-a"]["id"],
        resources["sandbox-b"]["id"],
        resources["sandbox-c"]["id"],
    ]

    assert_remediation_task(
        tasks[0],
        kind="IDLE_TERMINATE",
        status="PROPOSED",
        observed_utilization_pct=5.00,
        projected_savings_cents=1000000,
        waste_score=97.00,
        auto_remediation_eligible=True,
    )
    assert_remediation_task(
        tasks[1],
        kind="RIGHTSIZE",
        status="PROPOSED",
        observed_utilization_pct=5.01,
        projected_savings_cents=500000,
        waste_score=96.99,
        auto_remediation_eligible=True,
    )

    idle = validate_success(api.get_cloud_resource(resources["sandbox-a"]["id"], ANALYST_HEADERS))
    assert idle["lifecycle_state"] == "FLAGGED_IDLE"
    oversized = validate_success(
        api.get_cloud_resource(resources["sandbox-b"]["id"], ANALYST_HEADERS)
    )
    assert oversized["lifecycle_state"] == "RIGHTSIZE_PENDING"


def test_a_waste_score_below_sixty_is_proposed_but_never_auto_remediable(api):
    """The 20000-cent resource scores 57.80 and so is refused unattended execution.

    PRD §3.8: "The task also records `observed_utilization_pct`, the
    `utilization_pct` read from the resource at scan time, and sets
    `auto_remediation_eligible` to true only when both conditions hold: the
    `waste_score` is at or above 60.00 **and** the resource's `environment` is
    not the literal string `prod`."

    Design: Difficulty/boundary_precision_check/idle_threshold_exact_five_percent_versus_five_point_zero_one
    """
    built = _lab_unit_with_four_resources(api)
    resources = built["resources"]

    tasks = validate_success(
        api.run_idle_detection_scan({"business_unit_id": built["unit"]["id"]}, ANALYST_HEADERS)
    )
    assert len(tasks) == 3

    small = find_by(tasks, cloud_resource_id=resources["sandbox-c"]["id"])
    assert_remediation_task(
        small,
        kind="IDLE_TERMINATE",
        status="PROPOSED",
        observed_utilization_pct=5.00,
        projected_savings_cents=20000,
        waste_score=57.80,
        auto_remediation_eligible=False,
    )
    assert small["waste_score"] < 60.00

    for application in ("sandbox-a", "sandbox-b"):
        eligible = find_by(tasks, cloud_resource_id=resources[application]["id"])
        assert eligible["auto_remediation_eligible"] is True
        assert eligible["waste_score"] >= 60.00

    flagged = validate_success(api.get_cloud_resource(resources["sandbox-c"]["id"], ANALYST_HEADERS))
    assert flagged["lifecycle_state"] == "FLAGGED_IDLE"


def test_a_resource_one_cent_under_the_run_rate_floor_draws_no_proposal(api):
    """19999 cents is too small to bother with, so the fourth resource is skipped.

    PRD §3.8: "A resource whose `monthly_run_rate_cents` is below 20,000 cents is
    skipped as too small to bother with."

    Design: Difficulty/boundary_precision_check/idle_threshold_exact_five_percent_versus_five_point_zero_one
    """
    built = _lab_unit_with_four_resources(api)
    resources = built["resources"]

    validate_success(
        api.run_idle_detection_scan({"business_unit_id": built["unit"]["id"]}, ANALYST_HEADERS)
    )

    _, skipped = validate_paginated(
        api.list_remediation_tasks(
            ANALYST_HEADERS, {"cloud_resource_id": resources["sandbox-d"]["id"]}
        )
    )
    assert skipped["total_count"] == 0

    untouched = validate_success(
        api.get_cloud_resource(resources["sandbox-d"]["id"], ANALYST_HEADERS)
    )
    assert untouched["lifecycle_state"] == "ACTIVE"
    assert_cents(untouched["monthly_run_rate_cents"], 19999, "monthly_run_rate_cents")
    assert_pct(untouched["utilization_pct"], 5.00, "utilization_pct")

    _, at_the_floor = validate_paginated(
        api.list_remediation_tasks(
            ANALYST_HEADERS, {"cloud_resource_id": resources["sandbox-c"]["id"]}
        )
    )
    assert at_the_floor["total_count"] == 1

    _, all_tasks = validate_paginated(api.list_remediation_tasks(ANALYST_HEADERS))
    assert all_tasks["total_count"] == 3
