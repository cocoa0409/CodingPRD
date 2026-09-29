"""Lifecycle entry states, declared transitions and refused transitions."""

from test_helpers import (
    ANALYST_HEADERS,
    CONTROLLER_HEADERS,
    OWNER_4,
    ApiErrorId,
    assert_cents,
    assert_commitment_figures,
    assert_freshly_created,
    assert_invoice_dimensions,
    assert_invoice_ledger,
    assert_nulls,
    assert_pct,
    assert_remediation_task,
    factories,
    fixtures,
    make_resource_owner_headers,
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


def test_a_new_budget_is_born_in_draft_with_an_empty_forecast_trail(api):
    """Every derived budget figure starts at zero and the trail starts empty.

    PRD §3.9: "The budget starts in `DRAFT` with an empty `forecast_history`,
    `revision_count` at 0, `variance_explanation_text` null,
    `accuracy_basis_applied` null, `warning_flag` false, and
    `actual_spend_cents`, `variance_cents`, `variance_pct` and
    `forecast_accuracy_pct` all at zero."

    Design: Corner/state_machines/budget_is_born_in_draft_with_empty_forecast_history
    """
    fixtures.set_clock(api)
    unit = fixtures.create_business_unit(api)

    budget = validate_success(
        api.create_budget(
            factories.budget_payload(unit["id"], amount_cents=10000, forecast_cents=9000),
            CONTROLLER_HEADERS,
        ),
        201,
    )

    assert budget["status"] == "DRAFT"
    assert budget["forecast_history"] == []
    assert budget["revision_count"] == 0
    assert budget["accuracy_basis"] == "MAPE_BASIS"
    assert_nulls(budget, "accuracy_basis_applied", "variance_explanation_text")
    assert_cents(budget["actual_spend_cents"], 0, "actual_spend_cents")
    assert_cents(budget["variance_cents"], 0, "variance_cents")
    assert_pct(budget["variance_pct"], 0.0, "variance_pct")
    assert_pct(budget["forecast_accuracy_pct"], 0.0, "forecast_accuracy_pct")
    assert budget["warning_flag"] is False
    assert_freshly_created(budget)


def test_activating_a_commitment_sets_its_capacity_and_discounts_the_covered_record(api):
    """Activation runs the waterfall and rewrites the record it covers.

    PRD §3.4: "A new commitment lands in `PENDING` with
    `committed_capacity_cents` already set to `hourly_commit_cents` multiplied
    by the 720 hours in a standard 30-day commitment period."

    Design: Corner/state_machines/commitment_activation_sets_capacity_and_discounts_the_covered_record
    """
    fixtures.set_clock(api)
    unit = fixtures.create_business_unit(api)
    policy = fixtures.create_active_policy(api)
    resource = fixtures.provision_resource(
        api, policy["id"], unit["id"], OWNER_4, monthly_run_rate_cents=10000
    )
    record = fixtures.create_cost_record(
        api, 10000, resource_kind="COMPUTE", cloud_resource_id=resource["id"]
    )

    commitment = fixtures.create_commitment(
        api,
        commitment_type="RESERVED_INSTANCE",
        region="us-east-1",
        covered_resource_kind="COMPUTE",
        term_start=JULY_START,
        term_end=JULY_END,
        hourly_commit_cents=50,
    )
    activated = validate_success(
        api.activate_commitment(commitment["id"], CONTROLLER_HEADERS)
    )

    assert activated["status"] == "ACTIVE"
    assert_commitment_figures(
        activated,
        committed_capacity_cents=36000,
        covered_spend_cents=10000,
        total_discount_cents=4000,
        waste_cents=26000,
        coverage_pct=100.00,
        utilization_pct=27.78,
    )
    assert activated["version"] == 2

    covered = validate_success(api.get_cost_record(record["id"], ANALYST_HEADERS))
    assert covered["applied_commitment_id"] == commitment["id"]
    assert_cents(covered["effective_cost_cents"], 6000, "effective_cost_cents")
    assert_cents(covered["list_cost_cents"], 10000, "list_cost_cents")
    assert covered["allocation_state"] == "UNALLOCATED"


def test_a_submitted_request_cannot_skip_approval_and_be_provisioned(api):
    """Provisioning is only declared from `APPROVED`, so `SUBMITTED` conflicts.

    PRD §3.3: "Retag, approval or provisioning attempted from a status that
    does not declare that transition is rejected with
    `ERR_REQUEST_STATE_INVALID`."

    Design: Corner/state_machines/provisioning_request_cannot_be_provisioned_while_still_submitted
    """
    fixtures.set_clock(api)
    unit = fixtures.create_business_unit(api)
    policy = fixtures.create_active_policy(api)
    request = fixtures.create_provisioning_request(api, policy["id"], unit["id"], OWNER_4)

    response = api.provision_provisioning_request(request["id"], ANALYST_HEADERS)
    validate_error(response, ApiErrorId.REQUEST_STATE_INVALID.value, 409)

    unchanged = validate_success(api.get_provisioning_request(request["id"], ANALYST_HEADERS))
    assert unchanged["status"] == "SUBMITTED"
    assert_pct(unchanged["compliance_score"], 100.00, "compliance_score")

    _, meta = validate_paginated(
        api.list_cloud_resources(ANALYST_HEADERS, {"provisioning_request_id": request["id"]})
    )
    assert meta["total_count"] == 0


def test_starting_review_on_a_dispute_advances_the_review_round_only(api):
    """The declared side effect of `OPEN → UNDER_REVIEW` is one round increment.

    PRD §3.7: "A `FinOpsController` moves it `OPEN → UNDER_REVIEW`, which
    requires `review_round` to be strictly below 3 and increments
    `review_round` by 1."

    Design: Corner/state_machines/dispute_start_review_applies_its_declared_side_effect_on_review_round
    """
    fixtures.set_clock(api, "2026-08-05T00:00:00Z")
    unit = fixtures.create_chargeback_unit(api)
    policy = fixtures.create_active_policy(api)
    resource = fixtures.provision_resource(
        api, policy["id"], unit["id"], OWNER_4, monthly_run_rate_cents=10000
    )
    fixtures.create_cost_record(
        api, 10000, resource_kind="COMPUTE", cloud_resource_id=resource["id"]
    )

    run = fixtures.create_run(api, mode="CHARGEBACK")
    fixtures.compute(api, run["id"], "FINAL")
    published = fixtures.publish(api, run["id"])
    invoice = fixtures.issue_invoice(api, fixtures.invoices_of_run(api, published["id"])[0]["id"])

    dispute = fixtures.file_dispute(
        api,
        invoice,
        reason_code="WRONG_OWNER",
        claimed_credit_cents=4000,
        narrative="resource belongs to another unit",
    )

    reviewed = validate_success(api.start_review_dispute(dispute["id"], CONTROLLER_HEADERS))
    assert reviewed["status"] == "UNDER_REVIEW"
    assert reviewed["review_round"] == 1
    assert reviewed["version"] == 2
    assert reviewed["filed_by_business_unit_id"] == unit["id"]
    assert_cents(reviewed["granted_credit_cents"], 0, "granted_credit_cents")

    current = validate_success(api.get_chargeback_invoice(invoice["id"], CONTROLLER_HEADERS))
    assert_invoice_dimensions(current, settlement_status="ISSUED", dispute_status="DISPUTED")
    assert_invoice_ledger(current, 10000, 0, 0, 10000)


def test_a_routed_anomaly_alert_cannot_be_attributed_before_acknowledgement(api):
    """Attribution is declared only from `ACKNOWLEDGED`, so `ROUTED` conflicts.

    PRD §3.9: "Acknowledging, attributing or closing from a status that does
    not declare that transition — closing as explained before attribution, for
    instance — is `ERR_ALERT_STATE_INVALID`."

    Design: Corner/state_machines/anomaly_alert_cannot_be_attributed_straight_from_routed
    """
    fixtures.set_clock(api)
    unit = fixtures.create_business_unit(api)
    policy = fixtures.create_active_policy(api)
    resource = fixtures.provision_resource(
        api, policy["id"], unit["id"], OWNER_4, monthly_run_rate_cents=250000
    )
    for amount, start, end in (
        (250000, APRIL_START, APRIL_END),
        (250000, MAY_START, MAY_END),
        (250000, JUNE_START, JUNE_END),
        (300000, JULY_START, JULY_END),
    ):
        fixtures.create_cost_record(
            api,
            amount,
            resource_kind="COMPUTE",
            billing_period_start=start,
            billing_period_end=end,
            cloud_resource_id=resource["id"],
        )

    alerts = validate_success(
        api.run_anomaly_scan({"business_unit_id": unit["id"]}, ANALYST_HEADERS)
    )
    alert_id = alerts[0]["id"]

    response = api.attribute_anomaly_alert(
        alert_id,
        {
            "root_cause_cloud_resource_id": resource["id"],
            "root_cause_kind": "UTILIZATION_SPIKE",
        },
        ANALYST_HEADERS,
    )
    validate_error(response, ApiErrorId.ALERT_STATE_INVALID.value, 409)

    alert = validate_success(api.get_anomaly_alert(alert_id, ANALYST_HEADERS))
    assert alert["status"] == "ROUTED"
    assert_nulls(
        alert,
        "root_cause_cloud_resource_id",
        "root_cause_kind",
        "acknowledged_by_user_id",
    )
    assert alert["version"] == 1


def test_a_closed_budget_refuses_revision_evaluation_and_a_second_closure(api):
    """`CLOSED` is terminal, so all three later moves are state conflicts.

    PRD §3.9: "Every budget mutation increments its `version` by 1, and
    activation, revision, evaluation, explanation or closure attempted from a
    status that does not declare that transition is `ERR_BUDGET_STATE_INVALID`."

    Design: Corner/state_machines/closed_budget_refuses_revise_evaluate_and_close
    """
    fixtures.set_clock(api)
    unit = fixtures.create_business_unit(api)
    budget = fixtures.create_active_budget(
        api, unit["id"], amount_cents=10000, forecast_cents=9000
    )
    closed = validate_success(api.close_budget(budget["id"], CONTROLLER_HEADERS))
    closed_version = closed["version"]

    revise = api.revise_budget(
        budget["id"],
        {"expected_budget_version": closed_version, "forecast_cents": 9500},
        CONTROLLER_HEADERS,
    )
    validate_error(revise, ApiErrorId.BUDGET_STATE_INVALID.value, 409)

    evaluate = api.evaluate_budget(budget["id"], CONTROLLER_HEADERS)
    validate_error(evaluate, ApiErrorId.BUDGET_STATE_INVALID.value, 409)

    close_again = api.close_budget(budget["id"], CONTROLLER_HEADERS)
    validate_error(close_again, ApiErrorId.BUDGET_STATE_INVALID.value, 409)

    final = validate_success(api.get_budget(budget["id"], CONTROLLER_HEADERS))
    assert final["status"] == "CLOSED"
    assert_cents(final["forecast_cents"], 9000, "forecast_cents")
    assert final["revision_count"] == 0
    assert final["version"] == closed_version


def test_sealing_an_already_sealed_pool_is_a_state_conflict(api):
    """Sealing is declared only from `OPEN`, so the second seal conflicts.

    PRD §3.5: "Sealing moves a pool `OPEN → SEALED`, after which no further
    record may be absorbed, and increments the pool's `version`; absorbing into
    or re-sealing an already-`SEALED` pool is `ERR_POOL_STATE_INVALID`."

    Design: Corner/state_machines/sealing_a_shared_cost_pool_twice_is_rejected
    """
    fixtures.set_clock(api)
    unit = fixtures.create_business_unit(api, headcount=10)
    run = fixtures.create_run(api, mode="SHOWBACK")
    pool = fixtures.create_pool(api, run["id"], [unit["id"]])

    sealed = validate_success(api.seal_shared_cost_pool(pool["id"], ANALYST_HEADERS))
    assert sealed["status"] == "SEALED"
    assert sealed["version"] == 2

    again = api.seal_shared_cost_pool(pool["id"], ANALYST_HEADERS)
    validate_error(again, ApiErrorId.POOL_STATE_INVALID.value, 409)

    final = validate_success(api.get_shared_cost_pool(pool["id"], ANALYST_HEADERS))
    assert final["status"] == "SEALED"
    assert final["version"] == 2


def test_notification_and_snoozing_alternate_up_to_the_two_snooze_cap(api):
    """The third snooze is refused while the task stays inside its window.

    PRD §3.8: "Notification and snoozing therefore alternate while the window
    is open, up to the two-snooze cap."

    Design: Corner/state_machines/remediation_snooze_cycle_is_capped_at_two_extensions
    """
    fixtures.set_clock(api, "2026-08-05T00:00:00Z")
    unit = fixtures.create_business_unit(api)
    policy = fixtures.create_active_policy(api)
    built = fixtures.flag_idle_resource(
        api,
        unit["id"],
        policy["id"],
        OWNER_4,
        utilization_pct=2.00,
        monthly_run_rate_cents=1000000,
        requested_tags={"team": "ops", "environment": "dev", "application": "batch"},
    )
    task_id = built["task"]["id"]
    owner = make_resource_owner_headers(OWNER_4)

    assert_remediation_task(
        built["task"],
        kind="IDLE_TERMINATE",
        status="PROPOSED",
        observed_utilization_pct=2.00,
        projected_savings_cents=1000000,
        waste_score=98.80,
        auto_remediation_eligible=True,
    )

    notified = validate_success(api.notify_owner(task_id, ANALYST_HEADERS))
    assert notified["status"] == "OWNER_NOTIFIED"
    assert notified["snooze_count"] == 0
    assert notified["remediation_window_starts_at"].startswith("2026-08-05T00:00:00")
    assert notified["remediation_window_ends_at"].startswith("2026-08-08T00:00:00")

    first_snooze = validate_success(api.snooze_remediation_task(task_id, owner))
    assert first_snooze["status"] == "OWNER_SNOOZED"
    assert first_snooze["snooze_count"] == 1
    assert first_snooze["remediation_window_ends_at"].startswith("2026-08-11T00:00:00")

    renotified = validate_success(api.notify_owner(task_id, ANALYST_HEADERS))
    assert renotified["status"] == "OWNER_NOTIFIED"
    assert renotified["snooze_count"] == 1

    second_snooze = validate_success(api.snooze_remediation_task(task_id, owner))
    assert second_snooze["status"] == "OWNER_SNOOZED"
    assert second_snooze["snooze_count"] == 2

    renotified_again = validate_success(api.notify_owner(task_id, ANALYST_HEADERS))
    assert renotified_again["status"] == "OWNER_NOTIFIED"
    assert renotified_again["snooze_count"] == 2

    third_snooze = api.snooze_remediation_task(task_id, owner)
    validate_error(third_snooze, ApiErrorId.SNOOZE_LIMIT.value, 409)

    final = validate_success(api.get_remediation_task(task_id, ANALYST_HEADERS))
    assert final["status"] == "OWNER_NOTIFIED"
    assert final["snooze_count"] == 2

    resource = validate_success(
        api.get_cloud_resource(built["resource"]["id"], ANALYST_HEADERS)
    )
    assert resource["lifecycle_state"] == "FLAGGED_IDLE"
