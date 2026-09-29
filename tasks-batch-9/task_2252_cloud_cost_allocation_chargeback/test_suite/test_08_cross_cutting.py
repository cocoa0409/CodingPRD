"""Cross-cutting layers: the three optimistic-concurrency legs and a rate threshold."""

from test_helpers import (
    ANALYST_HEADERS,
    CONTROLLER_HEADERS,
    OWNER_1,
    OWNER_2,
    ApiErrorId,
    assert_cents,
    assert_pct,
    assert_ratio,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import (
    APRIL_END,
    APRIL_START,
    JULY_END,
    JULY_START,
    JUNE_END,
    JUNE_START,
    MAY_END,
    MAY_START,
)


def test_replaying_a_manual_adjustment_at_the_old_run_version_is_refused(api):
    """The client's own first append invalidates the version it still holds.

    PRD §2.8: "**Appending a manual adjustment line to an allocation run**
    requires `expected_allocation_run_version`, carrying the client's last
    observed `version` of the target `AllocationRun`."

    Design: Corner/cross-cutting complexity layers/stale_run_version_on_a_manual_adjustment_returns_412
    """
    fixtures.set_clock(api)
    unit = fixtures.create_business_unit(api)
    record = fixtures.create_untagged_record(api, 4000)
    built = fixtures.shared_pool_run(
        api, [unit["id"]], [record["id"]], mode="SHOWBACK", do_seal=False
    )
    run_id = built["run"]["id"]
    run_version = built["run"]["version"]

    first = validate_success(
        api.create_manual_adjustment(
            run_id,
            factories.manual_adjustment_payload(
                run_version, unit["id"], 100, memo="first true-up"
            ),
            CONTROLLER_HEADERS,
        ),
        201,
    )
    assert_cents(first["allocated_cents"], 100, "allocated_cents")

    replay = api.create_manual_adjustment(
        run_id,
        factories.manual_adjustment_payload(
            run_version, unit["id"], 200, memo="replayed true-up"
        ),
        CONTROLLER_HEADERS,
    )
    validate_error(replay, ApiErrorId.STALE_VERSION.value, 412)

    _, after_replay = validate_paginated(
        api.list_allocation_lines(CONTROLLER_HEADERS, {"allocation_run_id": run_id})
    )
    assert after_replay["total_count"] == 2

    reread = validate_success(api.get_allocation_run(run_id, CONTROLLER_HEADERS))
    assert reread["version"] == run_version + 1

    retried = validate_success(
        api.create_manual_adjustment(
            run_id,
            factories.manual_adjustment_payload(
                reread["version"], unit["id"], 200, memo="retried true-up"
            ),
            CONTROLLER_HEADERS,
        ),
        201,
    )
    assert_cents(retried["allocated_cents"], 200, "allocated_cents")
    assert retried["memo"] == "retried true-up"

    _, final_lines = validate_paginated(
        api.list_allocation_lines(CONTROLLER_HEADERS, {"allocation_run_id": run_id})
    )
    assert final_lines["total_count"] == 3

    final_run = validate_success(api.get_allocation_run(run_id, CONTROLLER_HEADERS))
    assert final_run["version"] == run_version + 2


def test_replaying_a_budget_revision_at_the_old_budget_version_is_refused(api):
    """The forecast trail advanced, so the stale revision cannot be applied.

    PRD §2.8: "**Revising a budget's forecast** requires
    `expected_budget_version`, carrying the client's last observed `version` of
    the target `Budget`."

    Design: Corner/cross-cutting complexity layers/stale_budget_version_on_revise_returns_412
    """
    fixtures.set_clock(api)
    unit = fixtures.create_business_unit(api)
    budget = fixtures.create_budget(api, unit["id"], amount_cents=10000, forecast_cents=9000)
    budget_version = budget["version"]

    revised = validate_success(
        api.revise_budget(
            budget["id"],
            {"expected_budget_version": budget_version, "forecast_cents": 9500},
            CONTROLLER_HEADERS,
        )
    )
    assert_cents(revised["forecast_cents"], 9500, "forecast_cents")
    assert revised["forecast_history"] == [9000]
    assert revised["revision_count"] == 1
    assert revised["version"] == budget_version + 1

    replay = api.revise_budget(
        budget["id"],
        {"expected_budget_version": budget_version, "forecast_cents": 9800},
        CONTROLLER_HEADERS,
    )
    validate_error(replay, ApiErrorId.STALE_VERSION.value, 412)

    reread = validate_success(api.get_budget(budget["id"], CONTROLLER_HEADERS))
    assert_cents(reread["forecast_cents"], 9500, "forecast_cents")
    assert reread["revision_count"] == 1
    assert reread["version"] == budget_version + 1

    retried = validate_success(
        api.revise_budget(
            budget["id"],
            {"expected_budget_version": reread["version"], "forecast_cents": 9800},
            CONTROLLER_HEADERS,
        )
    )
    assert_cents(retried["forecast_cents"], 9800, "forecast_cents")
    assert retried["forecast_history"] == [9000, 9500]
    assert retried["revision_count"] == 2


def test_a_policy_amendment_authored_before_activation_is_refused_as_stale(api):
    """Activation bumped the version, so the draft-time amendment is stale.

    The refusal is the concurrency one rather than the lifecycle one because the
    PRD orders the two checks: "**Optimistic concurrency**, per §2.8, yielding
    `ERR_STALE_VERSION` (412) on the three protected operations" is rung 8 of
    §2.10, while "**State admissibility.** The target must currently be in a
    state from which the requested transition is declared" is rung 9.  Once the
    client presents the live version, that later rung refuses the amendment
    instead, because PRD §3.2 says "amending a policy that is no longer `DRAFT`,
    for instance — is rejected with `ERR_POLICY_STATE_INVALID`".

    Design: Corner/cross-cutting complexity layers/stale_policy_version_on_amend_returns_412
    """
    drafted = validate_success(
        api.create_tagging_policy(factories.tagging_policy_payload(), ANALYST_HEADERS), 201
    )
    draft_version = drafted["version"]

    activated = validate_success(
        api.activate_tagging_policy(drafted["id"], CONTROLLER_HEADERS)
    )
    assert activated["version"] == draft_version + 1

    amendment = {
        "expected_tagging_policy_version": draft_version,
        "mandatory_dimensions": ["team", "environment"],
        "enforcement_mode": "BLOCKING",
    }
    stale = api.amend_tagging_policy(drafted["id"], amendment, CONTROLLER_HEADERS)
    validate_error(stale, ApiErrorId.STALE_VERSION.value, 412)

    untouched = validate_success(api.get_tagging_policy(drafted["id"], CONTROLLER_HEADERS))
    assert untouched["mandatory_dimensions"] == ["team", "environment", "application"]
    assert untouched["enforcement_mode"] == "ADVISORY"

    amendment["expected_tagging_policy_version"] = activated["version"]
    fresh = api.amend_tagging_policy(drafted["id"], amendment, CONTROLLER_HEADERS)
    validate_error(fresh, ApiErrorId.POLICY_STATE_INVALID.value, 409)

    final = validate_success(api.get_tagging_policy(drafted["id"], CONTROLLER_HEADERS))
    assert final["status"] == "ACTIVE"
    assert final["mandatory_dimensions"] == ["team", "environment", "application"]
    assert final["version"] == activated["version"]


def test_a_spike_one_cent_short_of_the_delta_gate_raises_no_alert(api):
    """Two units on identical baselines: 300000 alerts, 299999 does not.

    PRD §3.9: "An alert is emitted only when **both** gates clear, each
    inclusive at its boundary: `spike_ratio` must be at least 1.20 **and**
    `delta_cents` must be at least 50,000 cents. Anything else is skipped
    silently."

    Design: Corner/cross-cutting complexity layers/spend_spike_needs_both_the_ratio_and_the_delta_gate
    """
    fixtures.set_clock(api)
    policy = fixtures.create_active_policy(api)

    spiking = fixtures.create_business_unit(api, "Unit X", "CC-700", headcount=10)
    steady = fixtures.create_business_unit(api, "Unit Y", "CC-701", headcount=10)

    for unit, owner, newest in ((spiking, OWNER_1, 300000), (steady, OWNER_2, 299999)):
        resource = fixtures.provision_resource(
            api, policy["id"], unit["id"], owner, monthly_run_rate_cents=250000
        )
        for amount, start, end in (
            (250000, APRIL_START, APRIL_END),
            (250000, MAY_START, MAY_END),
            (250000, JUNE_START, JUNE_END),
            (newest, JULY_START, JULY_END),
        ):
            fixtures.create_cost_record(
                api,
                amount,
                resource_kind="COMPUTE",
                billing_period_start=start,
                billing_period_end=end,
                cloud_resource_id=resource["id"],
            )

    alerts = validate_success(api.run_anomaly_scan({}, ANALYST_HEADERS))
    assert len(alerts) == 1

    alert = alerts[0]
    assert alert["business_unit_id"] == spiking["id"]
    assert_cents(alert["baseline_cents"], 250000, "baseline_cents")
    assert_cents(alert["observed_cents"], 300000, "observed_cents")
    assert_cents(alert["delta_cents"], 50000, "delta_cents")
    assert_ratio(alert["spike_ratio"], 1.2000, "spike_ratio")
    assert alert["status"] == "ROUTED"
    assert_pct(alert["severity_score"], 0.50, "severity_score")
    assert alert["severity"] == "LOW"
    assert alert["routed_queue"] == "WEEKLY_DIGEST"

    _, steady_meta = validate_paginated(
        api.list_anomaly_alerts(ANALYST_HEADERS, {"business_unit_id": steady["id"]})
    )
    assert steady_meta["total_count"] == 0
