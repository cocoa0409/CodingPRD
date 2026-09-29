"""Requests that break two rules at once: only the earlier check in the pinned
ordering may be reported.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_budget_ledger,
    assert_quantity,
    assert_state,
)
from test_helpers.factories import application_event_payload
from test_helpers.fixtures import (
    record_application,
    setup_ready_operation,
    setup_scenario,
)


def _application(ctx, **overrides):
    return api_client.create_application_event(
        application_event_payload(
            ctx["plan"]["id"], ctx["budget"]["id"], ctx["storage"]["id"], **overrides
        ),
        ctx["operator_headers"],
    )


def test_unapproved_plan_is_reported_before_the_rate_ceiling():
    """A 30,000 gallon-per-acre rate on a plan that is only SUBMITTED must be
    refused for the plan state, because that check sits far earlier.

    PRD: "When a single request could fail several checks, the outcome must be the error belonging to the **earliest** applicable check in the ordering below."
    PRD: "The named plan's `plan_status` must be `APPROVED`, or the record is refused with `ERR_PLAN_NOT_APPROVED`."

    Design: Difficulty/priority_pair_validation_conflict/plan_not_approved_outranks_rate_exceeds_limit
    """
    ctx = setup_scenario("SUBMITTED", intake_gallons=1000000)

    response = _application(
        ctx, applied_on="2026-07-20T00:00:00Z", gallons_applied=900000, acres_treated=30
    )
    validate_error(response, ApiErrorId.ERR_PLAN_NOT_APPROVED)
    assert response.status_code == 409, (
        f"expected HTTP 409, got {response.status_code}"
    )


def test_unapproved_plan_rejection_writes_nothing_at_all():
    """The rejected request leaves no application record and touches neither the
    field allowance ledger nor the structure's volume balance.

    PRD: "The **field allowance ledger** lives on each field nutrient budget. Its total, `allowable_total_gallons`, is fixed when the budget is created; `applied_gallons_to_date` accumulates the volume of every non-voided land application recorded against the budget, and `remaining_gallons` is what is left."
    PRD: "The named budget's `budget_status` must be `ACTIVE`, or the record is refused with `ERR_BUDGET_NOT_ACTIVE`; this is the gate that catches a budget filed after its plan was approved and therefore still born `LOCKED`."

    Design: Difficulty/priority_pair_validation_conflict/plan_not_approved_outranks_rate_exceeds_limit
    """
    ctx = setup_scenario("SUBMITTED", intake_gallons=1000000)
    headers = ctx["operator_headers"]

    _application(
        ctx, applied_on="2026-07-20T00:00:00Z", gallons_applied=900000, acres_treated=30
    )

    events, _ = validate_paginated(
        api_client.list_application_events(headers, {"budget_id": ctx["budget"]["id"]})
    )
    assert events == [], f"no application record may exist, got {len(events)}"

    budget = validate_success(
        api_client.get_field_budget(ctx["budget"]["id"], headers), 200
    )
    assert_budget_ledger(budget, applied=0.00, remaining=414396, total=414396)

    storage = validate_success(
        api_client.get_manure_storage(ctx["storage"]["id"], headers), 200
    )
    assert_quantity(storage["current_volume_gallons"], 1000000.00, "current_volume_gallons")


def test_frozen_ground_is_reported_before_the_remaining_allowance():
    """A frozen-ground application that also overdraws the field's remaining
    allowance must be refused for the ground condition.

    PRD: "Ground condition is checked first: a `soil_condition` of `FROZEN` is refused with `ERR_FROZEN_GROUND_APPLICATION`, and then a `soil_condition` of `SATURATED` with `ERR_SATURATED_SOIL_APPLICATION`."
    PRD: "`gallons_applied` may not exceed the budget's `remaining_gallons`, or the record is refused with `ERR_FIELD_ALLOWANCE_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/frozen_ground_outranks_field_allowance_exceeded
    """
    ctx = setup_ready_operation()
    record_application(
        ctx["operation"]["id"],
        ctx["plan"]["id"],
        ctx["budget"]["id"],
        ctx["storage"]["id"],
        ctx["operator_headers"],
        applied_on="2026-04-01T00:00:00Z",
    )

    # 200,000 gallons is more than the 114,396 gallons the budget has left.
    response = _application(
        ctx,
        applied_on="2026-07-20T00:00:00Z",
        gallons_applied=200000,
        acres_treated=30,
        soil_condition="FROZEN",
    )
    validate_error(response, ApiErrorId.ERR_FROZEN_GROUND_APPLICATION)
    assert response.status_code == 422, (
        f"expected HTTP 422, got {response.status_code}"
    )


def test_frozen_ground_rejection_leaves_the_earlier_record_and_both_ledgers_alone():
    """The refused winter record changes nothing: the April record stands, the
    ledger still shows only its volume and the field's last application date is
    unmoved.

    PRD: "A field's `last_application_on` starts null and thereafter tracks the `applied_on` of the most recent non-voided land application recorded on that field — that is, the latest among records whose `event_status` is `RECORDED` or `VERIFIED` — reverting to null when no such record remains."
    PRD: "At all times `applied_gallons_to_date` plus `remaining_gallons` equals `allowable_total_gallons`."

    Design: Difficulty/priority_pair_validation_conflict/frozen_ground_outranks_field_allowance_exceeded
    """
    ctx = setup_ready_operation()
    headers = ctx["operator_headers"]
    first = record_application(
        ctx["operation"]["id"],
        ctx["plan"]["id"],
        ctx["budget"]["id"],
        ctx["storage"]["id"],
        headers,
        applied_on="2026-04-01T00:00:00Z",
    )

    _application(
        ctx,
        applied_on="2026-07-20T00:00:00Z",
        gallons_applied=200000,
        acres_treated=30,
        soil_condition="FROZEN",
    )

    budget = validate_success(
        api_client.get_field_budget(ctx["budget"]["id"], headers), 200
    )
    assert_budget_ledger(budget, applied=300000.00, remaining=114396, total=414396)

    kept = validate_success(api_client.get_application_event(first["id"], headers), 200)
    assert_state(kept, "event_status", "RECORDED")

    storage = validate_success(
        api_client.get_manure_storage(ctx["storage"]["id"], headers), 200
    )
    assert_quantity(storage["current_volume_gallons"], 700000.00, "current_volume_gallons")

    field = validate_success(api_client.get_field(ctx["field"]["id"], headers), 200)
    assert field["last_application_on"].startswith("2026-04-01"), (
        f"last_application_on: expected 1 April 2026, got {field['last_application_on']}"
    )


def test_reapplication_buffer_is_reported_before_the_method_membership():
    """A record filed 12 days after the last one, using a method the plan never
    authorised, must be refused for the interval rather than the method.

    PRD: "The gap between `applied_on` and the field's `last_application_on` must be at least 21 days in absolute terms; the buffer is symmetric, so a back-dated record that lands inside the window of a later existing record is rejected exactly as a too-soon forward record is, while a gap of exactly 21 days is accepted."
    PRD: "And the `application_method` must be a member of the owning plan's `allowed_application_methods`, or the record is refused with `ERR_APPLICATION_METHOD_NOT_IN_PLAN`."

    Design: Difficulty/priority_pair_validation_conflict/reapplication_interval_outranks_method_not_in_plan
    """
    ctx = setup_ready_operation()
    record_application(
        ctx["operation"]["id"],
        ctx["plan"]["id"],
        ctx["budget"]["id"],
        ctx["storage"]["id"],
        ctx["operator_headers"],
        applied_on="2026-07-20T00:00:00Z",
    )

    response = _application(
        ctx,
        applied_on="2026-08-01T00:00:00Z",
        gallons_applied=100000,
        acres_treated=10,
        application_method="SURFACE_BROADCAST",
        setback_maintained_ft=250,
    )
    validate_error(response, ApiErrorId.ERR_REAPPLICATION_INTERVAL_CONFLICT)
    assert response.status_code == 409, (
        f"expected HTTP 409, got {response.status_code}"
    )


def test_reapplication_rejection_does_not_move_the_field_or_the_ledger():
    """The refused record leaves the field's last application date and the
    budget's remaining allowance exactly as the accepted July record left them.

    PRD: "The budget's `applied_gallons_to_date` increases by `gallons_applied` and its `remaining_gallons` decreases by the same amount."
    PRD: "The field's `last_application_on` is stamped with `applied_on` when that instant is later than the value already stored."

    Design: Difficulty/priority_pair_validation_conflict/reapplication_interval_outranks_method_not_in_plan
    """
    ctx = setup_ready_operation()
    headers = ctx["operator_headers"]
    record_application(
        ctx["operation"]["id"],
        ctx["plan"]["id"],
        ctx["budget"]["id"],
        ctx["storage"]["id"],
        headers,
        applied_on="2026-07-20T00:00:00Z",
    )

    _application(
        ctx,
        applied_on="2026-08-01T00:00:00Z",
        gallons_applied=100000,
        acres_treated=10,
        application_method="SURFACE_BROADCAST",
        setback_maintained_ft=250,
    )

    field = validate_success(api_client.get_field(ctx["field"]["id"], headers), 200)
    assert field["last_application_on"].startswith("2026-07-20"), (
        f"last_application_on: expected 20 July 2026, got {field['last_application_on']}"
    )

    budget = validate_success(
        api_client.get_field_budget(ctx["budget"]["id"], headers), 200
    )
    assert_budget_ledger(budget, applied=300000.00, remaining=114396, total=414396)
