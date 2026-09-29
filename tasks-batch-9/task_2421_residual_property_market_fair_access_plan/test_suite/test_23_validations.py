"""Validation rules at their exact boundaries and in their exact order.

Two tests sit on the satisfied side of a limit — a dwelling limit equal to the
replacement cost, and a bind at the very instant of the deadline — and the third
proves that the declination count rule is only reachable once the reviewable
state rule has already been satisfied.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_errors import ERR_INSUFFICIENT_DECLINATIONS
from test_helpers.assertions import (
    assert_cents,
    assert_date_equals,
    assert_field_equals,
    assert_field_null,
    assert_instant_equals,
)
from test_helpers.constants import (
    APP_STATUS_BOUND,
    APP_STATUS_DECLINED,
    APP_STATUS_DRAFT,
    APP_STATUS_ELIGIBILITY_HELD,
    COVERAGE_STATUS_IN_FORCE,
    CLOCK_BASE,
    ELIGIBILITY_DECISION_ADVANCE,
    ELIGIBILITY_DECISION_DECLINE,
    PACKAGE_BASIC_FIRE_EO,
    REASON_APPETITE,
    REASON_CAT_EXPOSURE,
)
from test_helpers.fixtures import (
    DEFAULT_MEMBER_SPECS,
    Foundations,
    add_declination,
    build_bindable_application,
    build_foundations,
    create_applicant,
    create_appointed_producer,
    create_draft_application,
    create_property,
    create_zone,
    pin_clock,
    read_application,
    submit,
)
from test_helpers.test_users import admin_headers, binder_headers, reviewer_headers


def test_dwelling_limit_exactly_equal_to_replacement_cost_is_accepted(client):
    """A limit equal to the replacement cost is inside the cap, so the draft opens.

    PRD: "And the requested dwelling limit must be no greater than the plan's statutory
    ceiling of one and a half million dollars — 150,000,000 cents — **and** no
    greater than the property's own `replacement_cost_cents`; breaching either
    bound yields `ERR_COVERAGE_LIMIT_EXCEEDED`."

    PRD: "A fresh application sits in `status` `DRAFT` with `declination_count` at 0;
    `quoted_annual_premium_cents` and `voluntary_equivalent_premium_cents` at 0;
    `voluntary_market_comparison_pct` at 0.0; and `quote_rate_filing_id`,
    `submitted_at`, `eligibility_hold_reason`, `decline_reason`,
    `eligibility_reviewer_user_id`, `approved_to_bind_at` and `bind_deadline_at`
    all null."

    Design: Corner/validations/dwelling_limit_exactly_equal_to_replacement_cost_is_accepted
    """
    pin_clock(client, CLOCK_BASE)
    zone = create_zone(client, exposure_cap_cents=900_000_000)
    producer = create_appointed_producer(client)
    foundations = Foundations(client=client, zone=zone, producer=producer)
    applicant = create_applicant(client, foundations)
    prop = create_property(client, foundations, replacement_cost_cents=54_000_000)

    response = client.create_application(
        f.application_payload(
            property_id=prop["id"],
            applicant_id=applicant["id"],
            requested_dwelling_limit_cents=54_000_000,
            requested_peril_package=PACKAGE_BASIC_FIRE_EO,
        ),
        foundations.producer_headers,
    )

    application = validate_success(response, 201)
    assert_field_equals(application, "status", APP_STATUS_DRAFT)
    assert_cents(
        application["requested_dwelling_limit_cents"],
        54_000_000,
        "requested_dwelling_limit_cents",
    )
    assert_field_equals(application, "producer_id", foundations.producer_id)
    assert_field_equals(application, "declination_count", 0)


def test_bind_at_exactly_the_bind_deadline_instant_is_accepted(roomy_foundations):
    """Binding at the very deadline instant is inside the window and succeeds.

    PRD: "`PENDING → PASS` is available when the request supplies no requirements. It
    cascades the application `INSPECTION_PENDING → APPROVED_TO_BIND`, writing
    `approved_to_bind_at` to the current logical clock and `bind_deadline_at` to
    thirty days after that instant."

    PRD: "The bind clock instant must be at or before the application's
    `bind_deadline_at`, or `ERR_BIND_DEADLINE_PASSED`."

    PRD: "The `effective_date` comes from the request and the `expiration_date` is set
    to three hundred sixty-five days after it, marking the exclusive end of the
    term."

    PRD: "The `coverage_status` starts at `IN_FORCE` when the `effective_date` is on or
    before the bind clock date, and at `BOUND` when the policy is future-dated."

    Design: Corner/validations/bind_at_exactly_the_bind_deadline_instant_is_accepted
    """
    client = roomy_foundations.client
    chain = build_bindable_application(
        client, roomy_foundations, observed_condition_score=72
    )
    assert_instant_equals(
        chain.application["bind_deadline_at"],
        "2026-10-01T00:00:00Z",
        "bind_deadline_at",
    )
    pin_clock(client, "2026-10-01T00:00:00Z")

    response = client.bind_policy(
        f.bind_payload(chain.application_id, "2026-10-01"), binder_headers()
    )

    policy = validate_success(response, 201)
    assert_field_equals(policy, "coverage_status", COVERAGE_STATUS_IN_FORCE)
    assert_date_equals(policy["effective_date"], "2026-10-01", "effective_date")
    assert_date_equals(policy["expiration_date"], "2027-10-01", "expiration_date")
    assert_field_equals(policy, "condition_score_at_bind", 72)
    assert_cents(policy["annual_premium_cents"], 577_125, "annual_premium_cents")
    assert_field_equals(
        read_application(client, chain.application_id), "status", APP_STATUS_BOUND
    )


def test_declination_sufficiency_runs_after_the_reviewable_state_check(client):
    """A held application is reviewable, so the refusal comes from the count rule.

    PRD: "A count of three or more routes `DRAFT → SUBMITTED`, leaving
    `eligibility_hold_reason` null. A count below three routes `DRAFT →
    ELIGIBILITY_HELD` and writes `eligibility_hold_reason` to the literal string
    `INSUFFICIENT_DECLINATIONS`."

    PRD: "If the recomputed count is below three the advance is refused with
    `ERR_INSUFFICIENT_DECLINATIONS` — a hard error, not a routing decision."

    PRD: "`DECLINE` moves the application to the terminal `DECLINED` from either
    `SUBMITTED` or `ELIGIBILITY_HELD`, writing `decline_reason` from the request."

    Design: Corner/validations/declination_sufficiency_runs_after_the_reviewable_state_check
    """
    foundations = build_foundations(
        client,
        member_specs=DEFAULT_MEMBER_SPECS[:2],
        zone_overrides={"exposure_cap_cents": 900_000_000},
    )
    chain = create_draft_application(client, foundations)
    add_declination(
        chain,
        foundations.member_ids[0],
        reason_code=REASON_CAT_EXPOSURE,
        evidence_reference="DEC-1",
    )
    add_declination(
        chain,
        foundations.member_ids[1],
        reason_code=REASON_APPETITE,
        evidence_reference="DEC-2",
    )
    held = submit(chain)
    assert_field_equals(held, "status", APP_STATUS_ELIGIBILITY_HELD)
    assert_field_equals(held, "declination_count", 2)

    refused = client.review_application_eligibility(
        chain.application_id,
        f.eligibility_review_payload(decision=ELIGIBILITY_DECISION_ADVANCE),
        reviewer_headers(),
    )

    validate_error(refused, ERR_INSUFFICIENT_DECLINATIONS)
    still_held = read_application(client, chain.application_id)
    assert_field_equals(still_held, "status", APP_STATUS_ELIGIBILITY_HELD)
    assert_field_null(still_held, "eligibility_reviewer_user_id")

    declined_response = client.review_application_eligibility(
        chain.application_id,
        f.eligibility_review_payload(
            decision=ELIGIBILITY_DECISION_DECLINE,
            decline_reason="voluntary market not exhausted",
        ),
        reviewer_headers(),
    )

    validate_success(declined_response, 200)
    declined = read_application(client, chain.application_id)
    assert_field_equals(declined, "status", APP_STATUS_DECLINED)
    assert_field_equals(declined, "eligibility_reviewer_user_id", "uw-1")
    _rows, meta = validate_paginated(
        client.list_application_inspections(
            chain.application_id, admin_headers(), {"limit": 10}
        )
    )
    assert_field_equals(meta, "total_count", 0)
