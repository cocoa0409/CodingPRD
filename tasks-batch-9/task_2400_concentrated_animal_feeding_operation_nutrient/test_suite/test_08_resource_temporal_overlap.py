"""Two contended timelines: a field's 21-day reapplication buffer and an
operation's half-open coverage intervals.
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
    assert_null,
    assert_quantity,
    assert_state,
)
from test_helpers.factories import application_event_payload
from test_helpers.fixtures import (
    cover_permit,
    draft_permit,
    record_application,
    register_operation,
    setup_ready_operation,
)
from test_helpers.test_users import REVIEWER_HEADERS, make_operator_headers


def _field_applied_on_the_fifth_of_july():
    """A ready operation whose North 40 already carries a 300,000-gallon record
    dated 5 July 2026."""
    ctx = setup_ready_operation()
    ctx["first_event"] = record_application(
        ctx["operation"]["id"],
        ctx["plan"]["id"],
        ctx["budget"]["id"],
        ctx["storage"]["id"],
        ctx["operator_headers"],
        applied_on="2026-07-05T00:00:00Z",
    )
    return ctx


def _application(ctx, **overrides):
    return api_client.create_application_event(
        application_event_payload(
            ctx["plan"]["id"], ctx["budget"]["id"], ctx["storage"]["id"], **overrides
        ),
        ctx["operator_headers"],
    )


def _three_coverage_intervals():
    """One operation with coverage in force from 2026-01-01, plus two further
    draft applications: one starting inside that interval and one starting
    exactly at its closing instant."""
    operation = register_operation()
    operation_id = operation["id"]
    operator_headers = make_operator_headers(operation_id)
    permit_a = cover_permit(operation_id, operator_headers, REVIEWER_HEADERS)
    permit_b = draft_permit(
        operation_id, operator_headers, effective_on="2030-06-01T00:00:00Z"
    )
    permit_c = draft_permit(
        operation_id, operator_headers, effective_on="2031-01-01T00:00:00Z"
    )
    return {
        "operation": operation,
        "operator_headers": operator_headers,
        "permit_a": permit_a,
        "permit_b": permit_b,
        "permit_c": permit_c,
    }


def test_the_buffer_rejects_both_a_later_and_an_earlier_record_within_twenty_one_days():
    """Twenty days after the existing record and fifteen days before it are both
    refused by the same rule, which is what makes the buffer symmetric.

    PRD: "The gap between `applied_on` and the field's `last_application_on` must be at least 21 days in absolute terms; the buffer is symmetric, so a back-dated record that lands inside the window of a later existing record is rejected exactly as a too-soon forward record is, while a gap of exactly 21 days is accepted."
    PRD: "A violation is refused with `ERR_REAPPLICATION_INTERVAL_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/field_reapplication_symmetric_twenty_one_day_buffer
    """
    ctx = _field_applied_on_the_fifth_of_july()

    too_soon = _application(
        ctx, applied_on="2026-07-25T00:00:00Z", gallons_applied=50000, acres_treated=10
    )
    validate_error(too_soon, ApiErrorId.ERR_REAPPLICATION_INTERVAL_CONFLICT)
    assert too_soon.status_code == 409, (
        f"a record 20 days later expects HTTP 409, got {too_soon.status_code}"
    )

    back_dated = _application(
        ctx, applied_on="2026-06-20T00:00:00Z", gallons_applied=50000, acres_treated=10
    )
    validate_error(back_dated, ApiErrorId.ERR_REAPPLICATION_INTERVAL_CONFLICT)
    assert back_dated.status_code == 409, (
        f"a record 15 days earlier expects HTTP 409, got {back_dated.status_code}"
    )

    field = validate_success(
        api_client.get_field(ctx["field"]["id"], ctx["operator_headers"]), 200
    )
    assert field["last_application_on"].startswith("2026-07-05"), (
        f"last_application_on: expected 5 July 2026, got {field['last_application_on']}"
    )


def test_a_gap_of_exactly_twenty_one_days_is_accepted_and_moves_the_ledger():
    """Twenty-six July is exactly 21 days after the existing record, so the
    second application stands and both records count against the allowance.

    PRD: "The per-acre rate, `rate_gal_per_acre`, computed as `gallons_applied` divided by `acres_treated` and rounded half up to 2 decimal places, may not exceed the budget's `allowable_rate_gal_per_acre`, or the record is refused with `ERR_RATE_EXCEEDS_LIMIT`."
    PRD: "The field's `last_application_on` is stamped with `applied_on` when that instant is later than the value already stored."
    PRD: "`applied_gallons_to_date` accumulates the volume of every non-voided land application recorded against the budget, and `remaining_gallons` is what is left."

    Design: Difficulty/resource_temporal_overlap/field_reapplication_symmetric_twenty_one_day_buffer
    """
    ctx = _field_applied_on_the_fifth_of_july()
    headers = ctx["operator_headers"]

    accepted = validate_success(
        _application(
            ctx,
            applied_on="2026-07-26T00:00:00Z",
            gallons_applied=50000,
            acres_treated=10,
        ),
        201,
    )
    assert_state(accepted, "event_status", "RECORDED")
    assert_quantity(accepted["rate_gal_per_acre"], 5000.00, "rate_gal_per_acre")
    assert_quantity(accepted["n_applied_lbs"], 780.00, "n_applied_lbs")
    assert_quantity(accepted["p2o5_applied_lbs"], 500.00, "p2o5_applied_lbs")

    field = validate_success(api_client.get_field(ctx["field"]["id"], headers), 200)
    assert field["last_application_on"].startswith("2026-07-26"), (
        f"last_application_on: expected 26 July 2026, got {field['last_application_on']}"
    )

    budget = validate_success(
        api_client.get_field_budget(ctx["budget"]["id"], headers), 200
    )
    assert_budget_ledger(budget, applied=350000.00, remaining=64396, total=414396)

    events, _ = validate_paginated(
        api_client.list_application_events(headers, {"budget_id": ctx["budget"]["id"]})
    )
    assert len(events) == 2, f"expected exactly two records, got {len(events)}"
    assert {event["id"] for event in events} == {
        ctx["first_event"]["id"],
        accepted["id"],
    }, "the two surviving records are the July 5th and July 26th applications"


def test_a_coverage_interval_starting_inside_the_incumbent_is_refused():
    """A second application whose term opens in the middle of the existing
    coverage genuinely intersects it, so submission is refused.

    PRD: "Submission additionally enforces non-overlap: no other permit of the same operation whose `coverage_status` is `SUBMITTED`, `COVERED` or `RENEWAL_PENDING` may have a coverage interval that intersects the interval this application is requesting."
    PRD: "A genuine intersection is refused with `ERR_PERMIT_COVERAGE_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/permit_coverage_intervals_touch_without_overlapping
    """
    ctx = _three_coverage_intervals()
    headers = ctx["operator_headers"]

    incumbent = validate_success(
        api_client.get_permit(ctx["permit_a"]["id"], headers), 200
    )
    assert_state(incumbent, "coverage_status", "COVERED")
    assert incumbent["effective_on"].startswith("2026-01-01"), (
        f"effective_on: expected 1 January 2026, got {incumbent['effective_on']}"
    )
    assert incumbent["expiration_on"].startswith("2031-01-01"), (
        f"expiration_on: expected 1 January 2031, got {incumbent['expiration_on']}"
    )

    response = api_client.submit_permit(ctx["permit_b"]["id"], headers)
    validate_error(response, ApiErrorId.ERR_PERMIT_COVERAGE_OVERLAP)
    assert response.status_code == 409, (
        f"expected HTTP 409, got {response.status_code}"
    )

    permit_b = validate_success(
        api_client.get_permit(ctx["permit_b"]["id"], headers), 200
    )
    assert_state(permit_b, "coverage_status", "DRAFT_APPLICATION")


def test_a_coverage_interval_starting_at_the_closing_instant_is_accepted():
    """The half-open interval excludes its own endpoint, so an application
    effective exactly at the incumbent's expiration merely touches it.

    PRD: "Coverage intervals are half-open — they run from `effective_on` up to but not including `expiration_on` — so two intervals that merely touch at an endpoint do not intersect and both may stand."
    PRD: "Issuance is what stamps the term: `expiration_on` becomes `effective_on` plus a coverage term of 5 years; `renewal_window_opens_on` becomes `expiration_on` minus 180 days; and `renewal_due_on` becomes `expiration_on` minus 90 days."

    Design: Difficulty/resource_temporal_overlap/permit_coverage_intervals_touch_without_overlapping
    """
    ctx = _three_coverage_intervals()
    headers = ctx["operator_headers"]

    submitted = validate_success(
        api_client.submit_permit(ctx["permit_c"]["id"], headers), 200
    )
    assert_state(submitted, "coverage_status", "SUBMITTED")
    assert_null(submitted, "expiration_on")

    incumbent = validate_success(
        api_client.get_permit(ctx["permit_a"]["id"], headers), 200
    )
    assert_state(incumbent, "coverage_status", "COVERED")
    assert incumbent["expiration_on"].startswith("2031-01-01"), (
        f"expiration_on: expected 1 January 2031, got {incumbent['expiration_on']}"
    )
