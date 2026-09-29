"""Business-rule refusals: boundaries, aggregates and cross-entity gates."""

from test_helpers import (
    ADMIN_HEADERS,
    ANALYST_HEADERS,
    CONTROLLER_HEADERS,
    OWNER_4,
    OWNER_9,
    ApiErrorId,
    assert_allocation_line,
    assert_cents,
    assert_nulls,
    assert_pagination_meta,
    assert_pct,
    assert_tag_compliance,
    factories,
    fixtures,
    make_business_unit_owner_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import JULY_END, JULY_START, JUNE_END, JUNE_START


def test_absorbing_an_allocated_record_beside_a_fresh_one_refuses_the_whole_batch(api):
    """The already-allocated record decides the outcome, and nothing is applied.

    PRD §3.5: "If a named record's `allocation_state` is already `ALLOCATED` or
    `REVERSED`, it can neither be absorbed nor re-allocated and the request
    fails with `ERR_COST_RECORD_ALREADY_ALLOCATED` at HTTP 409."

    Design: Corner/validations/absorbing_an_already_allocated_record_alongside_a_fresh_one_is_rejected
    """
    unit = fixtures.create_chargeback_unit(api)
    first = fixtures.create_untagged_record(api, 1000)
    second = fixtures.create_untagged_record(api, 2000)

    published = fixtures.shared_pool_run(
        api,
        [unit["id"]],
        [first["id"]],
        mode="CHARGEBACK",
        methodology="PROPORTIONAL",
        proportional_basis="HEADCOUNT",
    )
    run_a = fixtures.publish(api, published["run"]["id"])

    run_b = fixtures.create_run(api, mode="SHOWBACK")
    pool_b = fixtures.create_pool(api, run_b["id"], [unit["id"]], name="Pool B")

    response = api.absorb_untagged(
        pool_b["id"], [first["id"], second["id"]], ANALYST_HEADERS
    )
    validate_error(response, ApiErrorId.COST_RECORD_ALREADY_ALLOCATED.value, 409)

    untouched_pool = validate_success(api.get_shared_cost_pool(pool_b["id"], ANALYST_HEADERS))
    assert_cents(untouched_pool["pooled_cost_cents"], 0, "pooled_cost_cents")
    assert untouched_pool["absorbed_record_count"] == 0
    assert untouched_pool["version"] == 1

    legal = validate_success(api.get_cost_record(second["id"], ANALYST_HEADERS))
    assert legal["allocation_state"] == "UNALLOCATED"
    assert_nulls(legal, "shared_cost_pool_id")

    already = validate_success(api.get_cost_record(first["id"], ANALYST_HEADERS))
    assert already["allocation_state"] == "ALLOCATED"
    assert already["allocated_by_run_id"] == run_a["id"]


def test_a_headcount_pool_over_a_zero_headcount_unit_cannot_be_computed(api):
    """A zero basis total is refused, and raising the headcount makes it compute.

    PRD §3.5: "The basis total is the sum of those bases across eligible
    participants, and if that total is zero the run fails with
    `ERR_PROPORTIONAL_BASIS_ZERO` at HTTP 422 — division would otherwise be
    undefined."

    Design: Corner/validations/proportional_pool_with_a_zero_basis_total_is_rejected_at_compute
    """
    unit = fixtures.create_business_unit(api)
    record = fixtures.create_untagged_record(api, 3000)

    run = fixtures.create_run(api, mode="SHOWBACK")
    pool = fixtures.create_pool(
        api,
        run["id"],
        [unit["id"]],
        name="Untagged",
        methodology="PROPORTIONAL",
        proportional_basis="HEADCOUNT",
    )
    fixtures.absorb(api, pool["id"], [record["id"]])

    refused = api.compute_allocation_run(run["id"], "FINAL", ANALYST_HEADERS)
    validate_error(refused, ApiErrorId.PROPORTIONAL_BASIS_ZERO.value, 422)

    still_draft = validate_success(api.get_allocation_run(run["id"], ANALYST_HEADERS))
    assert still_draft["status"] == "DRAFT"
    assert still_draft["line_count"] == 0
    assert_nulls(still_draft, "variant_applied")

    validate_success(api.patch_business_unit(unit["id"], {"headcount": 3}, ADMIN_HEADERS))

    computed = fixtures.compute(api, run["id"], "FINAL")
    assert computed["status"] == "COMPUTED_FINAL"
    assert_cents(computed["total_allocated_cents"], 3000, "total_allocated_cents")
    assert computed["line_count"] == 1

    lines, _ = validate_paginated(
        api.list_allocation_lines(ANALYST_HEADERS, {"allocation_run_id": run["id"]})
    )
    assert len(lines) == 1
    assert_allocation_line(
        lines[0],
        line_kind="SHARED",
        method_applied="PROPORTIONAL",
        allocated_cents=3000,
        basis_value=3.00,
    )


def test_an_overlapping_budget_period_becomes_legal_once_the_sibling_closes(api):
    """The duplicate-period filter counts only non-`CLOSED` siblings.

    PRD §3.9: "A business unit may not hold two non-`CLOSED` budgets whose
    periods overlap; an attempt is rejected with `ERR_BUDGET_PERIOD_DUPLICATE`
    at HTTP 409."

    Design: Corner/validations/overlapping_budget_periods_for_one_unit_are_rejected_until_the_first_closes
    """
    unit = fixtures.create_business_unit(api)
    first = fixtures.create_active_budget(
        api, unit["id"], amount_cents=10000, forecast_cents=10000
    )

    overlapping = factories.budget_payload(
        unit["id"],
        amount_cents=20000,
        forecast_cents=20000,
        period_start="2026-07-15T00:00:00Z",
        period_end="2026-08-15T00:00:00Z",
    )

    blocked = api.create_budget(overlapping, CONTROLLER_HEADERS)
    validate_error(blocked, ApiErrorId.BUDGET_PERIOD_DUPLICATE.value, 409)

    closed = validate_success(api.close_budget(first["id"], CONTROLLER_HEADERS))
    assert closed["status"] == "CLOSED"

    accepted = validate_success(api.create_budget(overlapping, CONTROLLER_HEADERS), 201)
    assert accepted["status"] == "DRAFT"

    _, meta = validate_paginated(
        api.list_budgets(CONTROLLER_HEADERS, {"business_unit_id": unit["id"]})
    )
    assert meta["total_count"] == 2


def test_a_dispute_filed_at_the_window_end_lands_and_one_second_later_does_not(api):
    """The 168-hour deadline is inclusive on the instant it names.

    PRD §2.5: "A dispute may be filed while the logical clock is at or before
    the invoice's `dispute_window_ends_at`; later filings are rejected with
    `ERR_DISPUTE_WINDOW_CLOSED`."

    Design: Corner/validations/dispute_filing_is_inclusive_at_the_window_end_and_rejected_one_second_later
    """
    fixtures.set_clock(api, "2026-08-05T00:00:00Z")
    unit = fixtures.create_chargeback_unit(api)
    built = fixtures.issued_chargeback_invoice(
        api, unit["id"], 5000, methodology="PROPORTIONAL", proportional_basis="HEADCOUNT"
    )
    invoice = built["invoice"]
    assert_cents(invoice["gross_amount_cents"], 5000, "gross_amount_cents")
    assert invoice["dispute_window_ends_at"].startswith("2026-08-12T00:00:00")

    owner = make_business_unit_owner_headers(unit["id"])
    payload = factories.dispute_payload(
        invoice["id"],
        reason_code="UNTAGGED_ABSORPTION",
        claimed_credit_cents=1000,
        narrative="not our storage",
    )

    fixtures.set_clock(api, "2026-08-12T00:00:01Z")
    too_late = api.create_dispute(payload, owner)
    validate_error(too_late, ApiErrorId.DISPUTE_WINDOW_CLOSED.value, 422)

    undisputed = validate_success(api.get_chargeback_invoice(invoice["id"], CONTROLLER_HEADERS))
    assert undisputed["dispute_status"] == "NONE"

    fixtures.set_clock(api, "2026-08-12T00:00:00Z")
    dispute = validate_success(api.create_dispute(payload, owner), 201)
    assert dispute["status"] == "OPEN"
    assert dispute["filed_by_business_unit_id"] == unit["id"]
    assert dispute["review_round"] == 0

    disputed = validate_success(api.get_chargeback_invoice(invoice["id"], CONTROLLER_HEADERS))
    assert disputed["dispute_status"] == "DISPUTED"

    record = validate_success(api.get_cost_record(built["record"]["id"], ANALYST_HEADERS))
    assert record["allocation_state"] == "DISPUTED_HOLD"


def test_publication_waits_for_the_billed_unit_to_be_chargeback_enabled(api):
    """The same publish call flips from refusal to success when the flag is set.

    PRD §3.6: "and, when the run's `mode` is `CHARGEBACK`, every business unit
    appearing on a line must have `chargeback_enabled` set to true, or the
    request fails with `ERR_BU_NOT_CHARGEBACK_ENABLED` at HTTP 422."

    Design: Corner/validations/publishing_a_chargeback_run_to_a_showback_only_unit_is_rejected
    """
    unit = fixtures.create_business_unit(api, headcount=10)
    record = fixtures.create_untagged_record(api, 4000)
    built = fixtures.shared_pool_run(
        api,
        [unit["id"]],
        [record["id"]],
        mode="CHARGEBACK",
        methodology="EVEN_SPLIT",
    )
    run_id = built["run"]["id"]

    refused = api.publish_allocation_run(run_id, CONTROLLER_HEADERS)
    validate_error(refused, ApiErrorId.BU_NOT_CHARGEBACK_ENABLED.value, 422)

    unpublished = validate_success(api.get_allocation_run(run_id, ANALYST_HEADERS))
    assert unpublished["status"] == "COMPUTED_FINAL"
    _, empty_meta = validate_paginated(
        api.list_chargeback_invoices(CONTROLLER_HEADERS, {"allocation_run_id": run_id})
    )
    assert empty_meta["total_count"] == 0

    validate_success(
        api.patch_business_unit(unit["id"], {"chargeback_enabled": True}, ADMIN_HEADERS)
    )

    published = validate_success(api.publish_allocation_run(run_id, CONTROLLER_HEADERS))
    assert published["status"] == "PUBLISHED"
    assert published["published_by_user_id"] == "controller-1"

    invoices, meta = validate_paginated(
        api.list_chargeback_invoices(CONTROLLER_HEADERS, {"allocation_run_id": run_id})
    )
    assert meta["total_count"] == 1
    assert invoices[0]["settlement_status"] == "UNBILLED"
    assert invoices[0]["dispute_status"] == "NONE"
    assert_cents(invoices[0]["gross_amount_cents"], 4000, "gross_amount_cents")


def test_a_credit_that_exactly_zeroes_a_unit_is_allowed_but_one_cent_more_is_not(api):
    """The gate is the unit's line total on the run, not the adjustment's sign.

    PRD §3.5: "An adjustment that would drive the affected business unit's line
    total on the run below zero is rejected with
    `ERR_ADJUSTMENT_WOULD_GO_NEGATIVE` at HTTP 422."

    Design: Corner/validations/manual_adjustment_that_would_drive_a_unit_negative_is_rejected
    """
    unit = fixtures.create_business_unit(api, headcount=10)
    record = fixtures.create_untagged_record(api, 1000)
    built = fixtures.shared_pool_run(
        api,
        [unit["id"]],
        [record["id"]],
        mode="SHOWBACK",
        methodology="EVEN_SPLIT",
        do_seal=False,
    )
    run = built["run"]
    run_version = run["version"]

    over_credit = api.create_manual_adjustment(
        run["id"],
        factories.manual_adjustment_payload(
            run_version, unit["id"], -1001, memo="over-credit"
        ),
        CONTROLLER_HEADERS,
    )
    validate_error(over_credit, ApiErrorId.ADJUSTMENT_WOULD_GO_NEGATIVE.value, 422)

    zeroed = validate_success(
        api.create_manual_adjustment(
            run["id"],
            factories.manual_adjustment_payload(
                run_version, unit["id"], -1000, memo="zero-out"
            ),
            CONTROLLER_HEADERS,
        ),
        201,
    )
    assert zeroed["line_kind"] == "MANUAL_ADJUSTMENT"
    assert_cents(zeroed["allocated_cents"], -1000, "allocated_cents")

    final = validate_success(api.get_allocation_run(run["id"], CONTROLLER_HEADERS))
    assert final["line_count"] == 2
    assert_cents(final["total_allocated_cents"], 1000, "total_allocated_cents")


def test_a_pool_participant_must_sit_inside_the_runs_scope_subtree(api):
    """A descendant of the scope root is in scope; a sibling of it is not.

    PRD §3.5: "Every participant id must resolve to an existing business unit,
    and when the run carries a `scope_business_unit_id` every participant must
    sit inside that unit's subtree; a participant outside the scope subtree is
    rejected with `ERR_PARTICIPANT_OUT_OF_SCOPE` at HTTP 422."

    Design: Corner/validations/pool_participant_outside_the_scoped_subtree_is_rejected
    """
    engineering = fixtures.create_business_unit(api, "Engineering", "CC-500", headcount=30)
    data = fixtures.create_business_unit(
        api,
        "Engineering / Data",
        "CC-501",
        headcount=10,
        parent_business_unit_id=engineering["id"],
    )
    marketing = fixtures.create_business_unit(api, "Marketing", "CC-600", headcount=5)

    run = fixtures.create_run(
        api, mode="SHOWBACK", scope_business_unit_id=engineering["id"]
    )

    bad = api.create_shared_cost_pool(
        run["id"],
        factories.shared_cost_pool_payload(
            [data["id"], marketing["id"]], name="Bad Pool", methodology="EVEN_SPLIT"
        ),
        ANALYST_HEADERS,
    )
    validate_error(bad, ApiErrorId.PARTICIPANT_OUT_OF_SCOPE.value, 422)

    good = validate_success(
        api.create_shared_cost_pool(
            run["id"],
            factories.shared_cost_pool_payload(
                [engineering["id"], data["id"]], name="Good Pool", methodology="EVEN_SPLIT"
            ),
            ANALYST_HEADERS,
        ),
        201,
    )
    assert good["participant_business_unit_ids"] == [engineering["id"], data["id"]]

    pools, meta = validate_paginated(api.list_shared_cost_pools(run["id"], ANALYST_HEADERS))
    assert meta["total_count"] == 1
    assert pools[0]["name"] == "Good Pool"


def test_a_provisioning_request_may_not_name_a_policy_still_in_draft(api):
    """The policy resolves, so the refusal is about its state, not its absence.

    PRD §3.2: "Only an `ACTIVE` policy may be referenced by a provisioning
    request, and only an `ACTIVE` policy may be consulted during retag or
    approval — referencing a policy still in `DRAFT` or already in `RETIRED`
    yields `ERR_POLICY_NOT_ACTIVE`."

    Design: Corner/validations/provisioning_against_a_draft_policy_is_rejected
    """
    unit = fixtures.create_business_unit(api)
    policy = fixtures.create_policy(api)
    payload = factories.provisioning_request_payload(policy["id"], unit["id"], OWNER_4)

    refused = api.create_provisioning_request(payload, ANALYST_HEADERS)
    validate_error(refused, ApiErrorId.POLICY_NOT_ACTIVE.value, 409)

    activated = validate_success(
        api.activate_tagging_policy(policy["id"], CONTROLLER_HEADERS)
    )
    assert activated["status"] == "ACTIVE"
    assert activated["activated_by_user_id"] == "controller-1"

    accepted = validate_success(api.create_provisioning_request(payload, ANALYST_HEADERS), 201)
    assert accepted["status"] == "SUBMITTED"
    assert_pct(accepted["compliance_score"], 100.00, "compliance_score")


def test_absorbing_a_record_from_outside_the_run_period_finds_no_candidate(api):
    """A June record is no candidate for a July run, so the batch is empty.

    PRD §3.5: "If the submitted set is empty, or if it matches no `UNALLOCATED`
    cost record with a null `business_unit_id` inside the run's period, the
    request fails with `ERR_UNTAGGED_ABSORB_EMPTY` at HTTP 422."

    Design: Corner/validations/absorbing_untagged_spend_with_no_in_period_candidate_is_rejected
    """
    unit = fixtures.create_business_unit(api, headcount=10)
    june = fixtures.create_untagged_record(
        api, 2500, billing_period_start=JUNE_START, billing_period_end=JUNE_END
    )

    run = fixtures.create_run(
        api, mode="SHOWBACK", period_start=JULY_START, period_end=JULY_END
    )
    pool = fixtures.create_pool(api, run["id"], [unit["id"]], name="Untagged")

    response = api.absorb_untagged(pool["id"], [june["id"]], ANALYST_HEADERS)
    validate_error(response, ApiErrorId.UNTAGGED_ABSORB_EMPTY.value, 422)

    record = validate_success(api.get_cost_record(june["id"], ANALYST_HEADERS))
    assert record["allocation_state"] == "UNALLOCATED"
    assert_nulls(record, "shared_cost_pool_id")

    unchanged = validate_success(api.get_shared_cost_pool(pool["id"], ANALYST_HEADERS))
    assert_cents(unchanged["pooled_cost_cents"], 0, "pooled_cost_cents")
    assert unchanged["absorbed_record_count"] == 0


def test_the_regional_hourly_ceiling_admits_exactly_five_hundred_cents(api):
    """500 passes, 501 does not, and a second region is unaffected.

    PRD §3.4: "Regional capacity is an aggregate: summing `hourly_commit_cents`
    across every commitment in the same `region` whose status is `PENDING`,
    `ACTIVE` or `UNDER_UTILIZED`, and including the new purchase in that sum,
    the total may not exceed 500 cents per hour."

    Design: Corner/validations/regional_hourly_commit_ceiling_is_inclusive_at_five_hundred
    """
    fixtures.create_commitment(
        api,
        commitment_type="RESERVED_INSTANCE",
        region="us-east-1",
        covered_resource_kind="COMPUTE",
        hourly_commit_cents=300,
    )

    over = api.create_commitment(
        factories.commitment_payload(
            commitment_type="SAVINGS_PLAN",
            region="us-east-1",
            covered_resource_kind=None,
            hourly_commit_cents=201,
        ),
        CONTROLLER_HEADERS,
    )
    validate_error(over, ApiErrorId.COMMITMENT_CAPACITY_EXCEEDED.value, 422)

    at_ceiling = validate_success(
        api.create_commitment(
            factories.commitment_payload(
                commitment_type="SAVINGS_PLAN",
                region="us-east-1",
                covered_resource_kind=None,
                hourly_commit_cents=200,
            ),
            CONTROLLER_HEADERS,
        ),
        201,
    )
    assert at_ceiling["status"] == "PENDING"
    assert_cents(
        at_ceiling["committed_capacity_cents"], 144000, "committed_capacity_cents"
    )

    other_region = validate_success(
        api.create_commitment(
            factories.commitment_payload(
                commitment_type="SAVINGS_PLAN",
                region="eu-west-1",
                covered_resource_kind=None,
                hourly_commit_cents=300,
            ),
            CONTROLLER_HEADERS,
        ),
        201,
    )
    assert other_region["region"] == "eu-west-1"

    rows, meta = validate_paginated(
        api.list_commitments(CONTROLLER_HEADERS, {"region": "us-east-1"})
    )
    assert meta["total_count"] == 2
    assert all(row["status"] == "PENDING" for row in rows)


def test_a_second_window_on_one_resource_cannot_touch_the_first(api):
    """Two identical windows on one resource are the harshest overlap there is.

    PRD §3.8: "No two windows on the same cloud resource may share an instant,
    so a new notification whose window would touch or overlap an existing open
    window on that resource is rejected with `ERR_REMEDIATION_WINDOW_OVERLAP`."

    Design: Corner/validations/second_remediation_window_on_the_same_resource_is_rejected
    """
    fixtures.set_clock(api, "2026-08-05T00:00:00Z")
    unit = fixtures.create_business_unit(api, headcount=10)
    policy = fixtures.create_active_policy(api)
    built = fixtures.flag_idle_resource(
        api,
        unit["id"],
        policy["id"],
        OWNER_4,
        utilization_pct=3.00,
        monthly_run_rate_cents=500000,
        requested_tags={"team": "ops", "environment": "dev", "application": "batch"},
    )
    resource_id = built["resource"]["id"]
    first_task = fixtures.notified_remediation_task(api, built["task"]["id"])
    assert first_task["status"] == "OWNER_NOTIFIED"

    second_task = validate_success(
        api.create_remediation_task(
            factories.remediation_task_payload(resource_id, kind="RIGHTSIZE"),
            ANALYST_HEADERS,
        ),
        201,
    )
    assert second_task["status"] == "PROPOSED"
    assert second_task["cloud_resource_id"] == resource_id

    clash = api.notify_owner(second_task["id"], ANALYST_HEADERS)
    validate_error(clash, ApiErrorId.REMEDIATION_WINDOW_OVERLAP.value, 409)

    unopened = validate_success(api.get_remediation_task(second_task["id"], ANALYST_HEADERS))
    assert unopened["status"] == "PROPOSED"
    assert_nulls(unopened, "remediation_window_starts_at", "remediation_window_ends_at")

    untouched = validate_success(
        api.get_remediation_task(built["task"]["id"], ANALYST_HEADERS)
    )
    assert untouched["status"] == "OWNER_NOTIFIED"
    assert untouched["remediation_window_starts_at"].startswith("2026-08-05T00:00:00")
    assert untouched["remediation_window_ends_at"].startswith("2026-08-08T00:00:00")


def test_remediation_cannot_be_opened_on_a_fully_utilised_resource(api):
    """A resource the scan left `ACTIVE` is not remediable by hand either.

    PRD §3.8: "Manual creation, owner notification and owner approval all
    require the underlying resource to be in `lifecycle_state` `FLAGGED_IDLE`
    or `RIGHTSIZE_PENDING`; a resource in any other lifecycle state is refused
    with `ERR_RESOURCE_NOT_REMEDIABLE` at HTTP 409."

    Design: Corner/validations/raising_a_remediation_task_on_an_unflagged_resource_is_rejected
    """
    unit = fixtures.create_business_unit(api, headcount=10)
    policy = fixtures.create_active_policy(api)
    resource = fixtures.provision_resource(
        api, policy["id"], unit["id"], OWNER_4, monthly_run_rate_cents=500000
    )

    flagged = validate_success(
        api.run_idle_detection_scan({"business_unit_id": unit["id"]}, ANALYST_HEADERS)
    )
    assert flagged == []

    refused = api.create_remediation_task(
        factories.remediation_task_payload(resource["id"], kind="IDLE_TERMINATE"),
        ANALYST_HEADERS,
    )
    validate_error(refused, ApiErrorId.RESOURCE_NOT_REMEDIABLE.value, 409)

    current = validate_success(api.get_cloud_resource(resource["id"], ANALYST_HEADERS))
    assert current["lifecycle_state"] == "ACTIVE"
    assert_pct(current["utilization_pct"], 100.00, "utilization_pct")

    _, meta = validate_paginated(
        api.list_remediation_tasks(ANALYST_HEADERS, {"cloud_resource_id": resource["id"]})
    )
    assert meta["total_count"] == 0


def test_approval_is_judged_against_the_units_status_at_approval_time(api):
    """A suspension filed after the request still blocks the approval.

    PRD §3.3: "A `FinOpsAnalyst` moves a request `SUBMITTED → APPROVED` only
    when four conditions hold together: the referenced policy is `ACTIVE`, or
    the request fails with `ERR_POLICY_NOT_ACTIVE`; the owning business unit is
    `ACTIVE`, or the request fails with `ERR_BU_SUSPENDED`; under `BLOCKING`
    enforcement `missing_dimensions` is empty, or the request fails with
    `ERR_MANDATORY_TAG_MISSING` at HTTP 422; and, if the owning business unit
    has a budget in `BREACHED` status whose period covers the current logical
    clock, that budget's `variance_explanation_text` is non-null, or the request
    fails with `ERR_VARIANCE_EXPLANATION_REQUIRED` at HTTP 422."

    Design: Corner/validations/approving_provisioning_for_a_suspended_unit_is_rejected
    """
    unit = fixtures.create_business_unit(api)
    policy = fixtures.create_active_policy(api)
    request = fixtures.create_provisioning_request(api, policy["id"], unit["id"], OWNER_4)

    validate_success(
        api.patch_business_unit(unit["id"], {"status": "SUSPENDED"}, ADMIN_HEADERS)
    )

    refused = api.approve_provisioning_request(request["id"], ANALYST_HEADERS)
    validate_error(refused, ApiErrorId.BU_SUSPENDED.value, 409)

    held = validate_success(api.get_provisioning_request(request["id"], ANALYST_HEADERS))
    assert held["status"] == "SUBMITTED"

    validate_success(
        api.patch_business_unit(unit["id"], {"status": "ACTIVE"}, ADMIN_HEADERS)
    )

    approved = validate_success(
        api.approve_provisioning_request(request["id"], ANALYST_HEADERS)
    )
    assert approved["status"] == "APPROVED"


def test_a_fully_tagged_request_clears_every_approval_gate_under_blocking(api):
    """All four approval conditions hold, so the request provisions.

    PRD §3.3: "The `APPROVED → PROVISIONED` transition creates a resource in
    `lifecycle_state` `ACTIVE` that freezes the request's tag data:
    `applied_tags` is a snapshot of `requested_tags` at provision time,
    `tag_state` is copied from `projected_tag_state`, and `environment` takes
    the value of the request's `environment` tag or, when that tag is absent,
    the literal string `untagged`."

    Design: Corner/validations/fully_compliant_request_under_blocking_enforcement_passes_every_gate
    """
    unit = fixtures.create_business_unit(api, headcount=10)
    policy = fixtures.create_active_policy(api, enforcement_mode="BLOCKING")

    request = validate_success(
        api.create_provisioning_request(
            factories.provisioning_request_payload(
                policy["id"],
                unit["id"],
                OWNER_9,
                resource_kind="DATABASE",
                requested_tags={"team": "ops", "environment": "prod", "application": "ledger"},
                monthly_run_rate_cents=30000,
            ),
            ANALYST_HEADERS,
        ),
        201,
    )
    assert_tag_compliance(
        request,
        missing_dimensions=[],
        compliance_score=100.00,
        projected_tag_state="TAGGED",
        status="SUBMITTED",
    )

    approved = validate_success(
        api.approve_provisioning_request(request["id"], ANALYST_HEADERS)
    )
    assert approved["status"] == "APPROVED"

    provisioned = validate_success(
        api.provision_provisioning_request(request["id"], ANALYST_HEADERS)
    )
    assert provisioned["status"] == "PROVISIONED"

    resources, meta = validate_paginated(
        api.list_cloud_resources(
            ANALYST_HEADERS, {"provisioning_request_id": request["id"]}
        )
    )
    assert_pagination_meta(meta, total_count=1, has_more=False)
    resource = resources[0]
    assert resource["lifecycle_state"] == "ACTIVE"
    assert resource["tag_state"] == "TAGGED"
    assert resource["environment"] == "prod"
    assert resource["owner_user_id"] == OWNER_9
    assert_cents(
        resource["monthly_run_rate_cents"], 30000, "monthly_run_rate_cents"
    )
    assert_pct(resource["utilization_pct"], 100.00, "utilization_pct")

    owning = validate_success(api.get_business_unit(unit["id"], ADMIN_HEADERS))
    assert owning["resource_count"] == 1
    assert_cents(owning["tracked_run_rate_cents"], 30000, "tracked_run_rate_cents")
