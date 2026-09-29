"""Entity shape, persistence and read-surface behaviour."""

from test_helpers import (
    ADMIN_HEADERS,
    ANALYST_ALT_HEADERS,
    ANALYST_HEADERS,
    CONTROLLER_HEADERS,
    OWNER_4,
    ApiErrorId,
    assert_cents,
    assert_freshly_created,
    assert_no_version_surface,
    assert_nulls,
    assert_pagination_meta,
    assert_pct,
    assert_tag_compliance,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import (
    JULY_END,
    JULY_START,
    JUNE_END,
    JUNE_START,
    MAY_END,
    MAY_START,
)


def test_business_unit_creation_stores_its_inputs_and_zeroes_every_derived_ledger(api):
    """A newly registered unit echoes its inputs and starts every ledger at zero.

    PRD §3.1: "Five derived figures hang off each unit and are all initialised
    to 0 at creation."

    Design: Corner/entities/business_unit_creation_persists_inputs_and_zeroes_derived_fields
    """
    response = api.create_business_unit(
        {
            "name": "Platform",
            "cost_center_code": "CC-100",
            "chargeback_enabled": True,
            "headcount": 40,
            "revenue_cents": 5000000,
            "status": "ACTIVE",
        },
        ADMIN_HEADERS,
    )
    unit = validate_success(response, 201)

    assert unit["name"] == "Platform"
    assert unit["cost_center_code"] == "CC-100"
    assert unit["chargeback_enabled"] is True
    assert unit["headcount"] == 40
    assert_cents(unit["revenue_cents"], 5000000, "revenue_cents")
    assert unit["status"] == "ACTIVE"

    assert unit["resource_count"] == 0
    assert_cents(unit["tracked_run_rate_cents"], 0, "tracked_run_rate_cents")
    assert_cents(unit["direct_spend_cents"], 0, "direct_spend_cents")
    assert_cents(unit["showback_total_cents"], 0, "showback_total_cents")
    assert_cents(unit["chargeback_balance_cents"], 0, "chargeback_balance_cents")

    assert_nulls(unit, "parent_business_unit_id")
    assert_freshly_created(unit)


def test_tagging_policy_read_returns_its_dimension_list_in_the_declared_order(api):
    """A policy read back preserves dimension order and its two defaults.

    PRD §3.2: "Either a `FinOpsAnalyst` or a `FinOpsController` drafts one by
    supplying a `name` and the ordered `mandatory_dimensions` list, which must
    be non-empty and must draw only from the three recognised dimensions
    `team`, `environment` and `application`."

    Design: Corner/entities/tagging_policy_retrieval_returns_stored_dimension_list
    """
    created = validate_success(
        api.create_tagging_policy(
            {
                "name": "Two Dimension Policy",
                "mandatory_dimensions": ["team", "environment"],
            },
            ANALYST_HEADERS,
        ),
        201,
    )

    policy = validate_success(api.get_tagging_policy(created["id"], CONTROLLER_HEADERS))

    assert policy["name"] == "Two Dimension Policy"
    assert policy["mandatory_dimensions"] == ["team", "environment"]
    assert policy["enforcement_mode"] == "ADVISORY"
    assert policy["status"] == "DRAFT"


def test_cost_record_listing_filters_by_resource_inside_the_pagination_envelope(api):
    """The record list narrows to one resource and reports a truthful envelope.

    PRD §2.3: "`limit` caps the number of items returned; it defaults to 10,
    may not be lower than 1, and may not be higher than 100."

    Design: Corner/entities/cost_record_listing_filters_by_resource_with_pagination_envelope
    """
    fixtures.set_clock(api)
    unit = fixtures.create_chargeback_unit(api, "Ops", "CC-400", headcount=10)
    policy = fixtures.create_active_policy(api)
    resource = fixtures.provision_resource(
        api,
        policy["id"],
        unit["id"],
        OWNER_4,
        monthly_run_rate_cents=10000,
    )

    for amount, start, end in (
        (1000, MAY_START, MAY_END),
        (2000, JUNE_START, JUNE_END),
        (3000, JULY_START, JULY_END),
    ):
        fixtures.create_cost_record(
            api,
            amount,
            resource_kind="COMPUTE",
            billing_period_start=start,
            billing_period_end=end,
            cloud_resource_id=resource["id"],
        )
    fixtures.create_cost_record(api, 900, resource_kind="STORAGE")

    rows, meta = validate_paginated(
        api.list_cost_records(ANALYST_HEADERS, {"cloud_resource_id": resource["id"]})
    )
    assert len(rows) == 3
    assert_pagination_meta(meta, total_count=3, has_more=False, limit=10, offset=0)
    assert all(row["cloud_resource_id"] == resource["id"] for row in rows)

    page, page_meta = validate_paginated(
        api.list_cost_records(
            ANALYST_HEADERS,
            {"cloud_resource_id": resource["id"], "limit": 2, "offset": 0},
        )
    )
    assert len(page) == 2
    assert_pagination_meta(page_meta, total_count=3, has_more=True, limit=2, offset=0)

    _, all_meta = validate_paginated(api.list_cost_records(ANALYST_HEADERS))
    assert all_meta["total_count"] == 4


def test_fetching_a_commitment_that_does_not_exist_names_the_commitment_entity(api):
    """An unresolvable commitment id yields the commitment's own 404.

    PRD §2.10: "The first identifier segment in the URL that does not resolve
    determines the 404, and the server does not attempt to resolve any later
    segment."

    Design: Corner/entities/commitment_fetch_with_unknown_id_returns_commitment_not_found
    """
    response = api.get_commitment("00000000-0000-4000-8000-000000000999", CONTROLLER_HEADERS)

    validate_error(response, ApiErrorId.COMMITMENT_NOT_FOUND.value, 404)
    body = response.json()
    assert body["response_type"] == "error"
    assert isinstance(body["meta"]["api_request_id"], str) and body["meta"]["api_request_id"]


def test_a_provisioning_request_without_an_owner_user_id_is_a_shape_error(api):
    """The remediation owner is a required input, and its absence persists nothing.

    PRD §3.3: "The payload names the `tagging_policy_id` to be evaluated
    against, the `business_unit_id` that will own the resource, the
    `resource_kind` — one of `COMPUTE`, `DATABASE` or `STORAGE` — the
    `requested_tags` map whose keys are dimension names and whose values are
    non-empty strings, the projected `monthly_run_rate_cents` as a non-negative
    integer, and the `owner_user_id` of the engineering owner who will be
    notified when the resource later needs remediation."

    Design: Corner/entities/provisioning_request_without_owner_user_id_is_rejected
    """
    fixtures.set_clock(api)
    unit = fixtures.create_business_unit(api)
    policy = fixtures.create_active_policy(api)

    response = api.create_provisioning_request(
        {
            "tagging_policy_id": policy["id"],
            "business_unit_id": unit["id"],
            "resource_kind": "COMPUTE",
            "requested_tags": {"team": "ops", "environment": "dev", "application": "api"},
            "monthly_run_rate_cents": 10000,
        },
        ANALYST_HEADERS,
    )
    validate_error(response, ApiErrorId.INVALID_REQUEST.value, 400)

    _, meta = validate_paginated(
        api.list_provisioning_requests(ANALYST_HEADERS, {"tagging_policy_id": policy["id"]})
    )
    assert meta["total_count"] == 0


def test_a_new_shared_cost_pool_opens_on_the_spend_basis_with_nothing_absorbed(api):
    """A pool's two defaults and its four zeroed fields at creation.

    PRD §3.5: "A new pool is created in `OPEN` status with `pooled_cost_cents`
    at 0, `absorbed_record_count` at 0, and its `allocation_run_id` set to the
    run it hangs from."

    Design: Corner/entities/shared_cost_pool_defaults_to_spend_basis_and_open_status
    """
    fixtures.set_clock(api)
    unit = fixtures.create_business_unit(api)
    run = fixtures.create_run(api, mode="SHOWBACK")

    pool = validate_success(
        api.create_shared_cost_pool(
            run["id"],
            {
                "name": "Network",
                "methodology": "PROPORTIONAL",
                "participant_business_unit_ids": [unit["id"]],
            },
            ANALYST_HEADERS,
        ),
        201,
    )

    assert pool["proportional_basis"] == "SPEND"
    assert pool["status"] == "OPEN"
    assert pool["absorbed_record_count"] == 0
    assert_cents(pool["pooled_cost_cents"], 0, "pooled_cost_cents")
    assert pool["allocation_run_id"] == run["id"]


def test_tag_compliance_is_evaluated_from_dimension_weights_at_creation(api):
    """A request missing one dimension records the gap and scores it by weight.

    PRD §3.3: "Each dimension carries a fixed weight: `team` is worth 40,
    `environment` 35 and `application` 25."

    Design: Corner/entities/provisioning_request_compliance_fields_are_computed_from_dimension_weights
    """
    fixtures.set_clock(api)
    unit = fixtures.create_business_unit(api)
    policy = fixtures.create_active_policy(
        api, mandatory_dimensions=["team", "environment", "application"]
    )

    request = validate_success(
        api.create_provisioning_request(
            factories.provisioning_request_payload(
                policy["id"],
                unit["id"],
                OWNER_4,
                requested_tags={"team": "ops", "environment": "dev"},
            ),
            ANALYST_HEADERS,
        ),
        201,
    )

    assert_tag_compliance(
        request,
        missing_dimensions=["application"],
        compliance_score=75.00,
        projected_tag_state="PARTIAL",
        status="SUBMITTED",
    )
    assert request["retag_count"] == 0


def test_a_drafted_policys_status_and_actor_fields_are_assigned_by_the_system(api):
    """The drafter is recorded, the activator is not, and the audit counter is zero.

    PRD §3.2: "A freshly drafted policy is in `DRAFT` status, its
    `created_by_user_id` set to the drafter's `X-User-ID`, its
    `activated_by_user_id` null, and its `rejection_count` at 0."

    Design: Corner/entities/tagging_policy_status_and_actor_fields_are_system_assigned
    """
    policy = validate_success(
        api.create_tagging_policy(
            {"name": "Std", "mandatory_dimensions": ["team"]},
            ANALYST_ALT_HEADERS,
        ),
        201,
    )

    assert policy["status"] == "DRAFT"
    assert policy["created_by_user_id"] == "analyst-7"
    assert_nulls(policy, "activated_by_user_id")
    assert policy["rejection_count"] == 0
    assert_freshly_created(policy)


def test_a_budget_with_an_inverted_period_or_a_zero_amount_is_refused(api):
    """Both the interval rule and the strict-positivity rule are shape errors.

    PRD §2.5: "Wherever a resource declares an interval, the end instant must
    be strictly after the start instant: `period_end` strictly after
    `period_start` for allocation runs and budgets, and `term_end` strictly
    after `term_start` for commitments."

    Design: Corner/entities/budget_with_inverted_period_and_zero_amount_is_rejected
    """
    fixtures.set_clock(api)
    unit = fixtures.create_business_unit(api)

    inverted = api.create_budget(
        factories.budget_payload(
            unit["id"], period_start=JULY_END, period_end=JULY_START
        ),
        CONTROLLER_HEADERS,
    )
    validate_error(inverted, ApiErrorId.INVALID_REQUEST.value, 400)

    zero_amount = api.create_budget(
        factories.budget_payload(unit["id"], amount_cents=0),
        CONTROLLER_HEADERS,
    )
    validate_error(zero_amount, ApiErrorId.INVALID_REQUEST.value, 400)

    _, meta = validate_paginated(
        api.list_budgets(CONTROLLER_HEADERS, {"business_unit_id": unit["id"]})
    )
    assert meta["total_count"] == 0


def test_an_allocation_line_exposes_no_version_and_no_updated_at(api):
    """A line is a write-once artifact with only the two common fields.

    PRD §2.4: "Allocation lines are write-once artifacts of a compute or
    adjustment operation, never edited in place, so a line carries only `id`
    and `created_at`; it has no `updated_at` and no `version` field at all."

    Design: Corner/entities/allocation_line_is_immutable_with_no_write_or_version_surface
    """
    fixtures.set_clock(api)
    unit = fixtures.create_chargeback_unit(api)
    run = fixtures.create_run(api, mode="CHARGEBACK")
    computed = fixtures.compute(api, run["id"], "FINAL")

    created = validate_success(
        api.create_manual_adjustment(
            run["id"],
            factories.manual_adjustment_payload(
                computed["version"], unit["id"], 500, memo="true-up"
            ),
            CONTROLLER_HEADERS,
        ),
        201,
    )

    line = validate_success(api.get_allocation_line(created["id"], CONTROLLER_HEADERS))

    assert_no_version_surface(line)
    assert line["line_kind"] == "MANUAL_ADJUSTMENT"
    assert line["method_applied"] == "MANUAL"
    assert_cents(line["allocated_cents"], 500, "allocated_cents")
    assert line["memo"] == "true-up"
    assert_pct(line["basis_value"], 0.0, "basis_value")
    assert_cents(line["rounding_remainder_cents"], 0, "rounding_remainder_cents")


def test_attaching_a_pool_to_a_run_that_does_not_exist_names_the_run(api):
    """The unresolvable path segment decides the failure, not the participant check.

    PRD §2.10: "**Path identifier existence**, validated strictly left to
    right."

    Design: Corner/entities/shared_cost_pool_creation_requires_an_existing_parent_run
    """
    fixtures.set_clock(api)
    unit = fixtures.create_business_unit(api)

    response = api.create_shared_cost_pool(
        "00000000-0000-4000-8000-0000000000aa",
        {
            "name": "Network",
            "methodology": "EVEN_SPLIT",
            "participant_business_unit_ids": [unit["id"]],
        },
        ANALYST_HEADERS,
    )

    validate_error(response, ApiErrorId.ALLOCATION_RUN_NOT_FOUND.value, 404)


def test_the_unit_tree_and_pool_membership_are_both_navigable(api):
    """A child points at its parent and both units can share one pool.

    PRD §3.1: "A `PlatformAdmin` registers one by supplying its display `name`
    and the finance `cost_center_code` that will appear on its chargeback
    invoices, and may optionally place it beneath an existing unit by supplying
    `parent_business_unit_id` — a self-reference into the same collection that
    builds the rollup tree."

    Design: Corner/entities/business_unit_self_referential_tree_and_many_to_many_pool_membership
    """
    fixtures.set_clock(api)
    parent = fixtures.create_business_unit(api, "Engineering", "CC-500", headcount=30)
    child = fixtures.create_business_unit(
        api,
        "Engineering / Data",
        "CC-501",
        headcount=10,
        parent_business_unit_id=parent["id"],
    )

    run = fixtures.create_run(api, mode="SHOWBACK", scope_business_unit_id=parent["id"])
    pool = validate_success(
        api.create_shared_cost_pool(
            run["id"],
            {
                "name": "Shared Platform",
                "methodology": "EVEN_SPLIT",
                "participant_business_unit_ids": [parent["id"], child["id"]],
            },
            ANALYST_HEADERS,
        ),
        201,
    )
    assert parent["id"] in pool["participant_business_unit_ids"]
    assert child["id"] in pool["participant_business_unit_ids"]

    rows, meta = validate_paginated(
        api.list_business_units(ADMIN_HEADERS, {"parent_business_unit_id": parent["id"]})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == child["id"]
    assert rows[0]["parent_business_unit_id"] == parent["id"]
