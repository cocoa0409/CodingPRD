"""Endpoint-contract corners for the read routes, the list envelope and the
merchant-side action endpoints.

Every test builds its own world from the public endpoints: the harness restarts
the server and empties the store before each one, with the logical clock at
``2026-08-01T00:00:00Z``.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as E
from test_helpers import factories as F
from test_helpers import fixtures as S
from test_helpers.assertions import assert_empty, assert_fields, ratio_bps
from test_helpers.test_users import (
    ADMIN_HEADERS,
    AGENT_HEADERS,
    ANALYST_HEADERS,
    UNDERWRITER_HEADERS,
)

#: A syntactically valid UUID that names no merchant row.
_ABSENT_MERCHANT_ID = "22222222-2222-4222-8222-222222222222"

#: A syntactically valid UUID that names no promotion plan row.
_ABSENT_PLAN_ID = "33333333-3333-4333-8333-333333333333"

#: The seven counters the operations checkpoint reports.
_SWEEP_COUNTERS = (
    "expired_licenses",
    "expired_offers",
    "expired_disclosures",
    "capitalized_loans",
    "delinquent_loans",
    "charged_off_loans",
    "escalated_disputes",
)


def _assert_sweep_counters(counts, **expected):
    """Assert every one of the seven counters, defaulting the unnamed ones to zero."""
    full = {name: 0 for name in _SWEEP_COUNTERS}
    full.update(expected)
    assert_fields(counts, **full)


def _settled_reserve_merchant(api):
    """A merchant whose single settled draw of 1050000 leaves reserve and target at 42000.

    Trailing-180-day volume including the draw is 1050000; the merchant is held
    at ``STANDARD`` for want of five settled draws, so the target is
    1050000 * 400 / 10000 == 42000, the gap is 42000 - 0, the base withholding is
    1050000 * 500 / 10000 == 52500 and the per-draw ceiling is 157500 — the
    smallest of the three is 42000.
    """
    return S.settled_draw(api, amount_cents=1050000, releases=(3000,), verify=(0,))


def test_one_enrollment_reads_identically_through_its_three_routes(api):
    """One enrollment row is reachable through the flat item, the nested list and the flat filter.

    PRD: "Enrollments are discoverable both under their merchant and across merchants, filtered by `merchant_id`, by `promotion_plan_id` or by `status`, and a single enrollment may be read directly by its own identifier."

    Design: Corner/endpoints/enrollment_is_readable_through_both_its_nested_and_flat_routes
    """
    scenario = S.enrolled_merchant(api)
    enrollment_id = scenario.enrollment["id"]

    item = validate_success(api.get_promotion_enrollment(enrollment_id, AGENT_HEADERS))
    assert_fields(
        item,
        id=enrollment_id,
        merchant_id=scenario.merchant_id,
        promotion_plan_id=scenario.plan_id,
        status="ACTIVE",
        negotiated_discount_bps=449,
        window_start_date="2026-08-01",
        window_end_date="2026-12-31",
        version=1,
    )

    nested, nested_meta = validate_paginated(
        api.list_merchant_promotion_enrollments(
            scenario.merchant_id, UNDERWRITER_HEADERS, {"status": "ACTIVE"}
        )
    )
    assert nested_meta["total_count"] == 1, "The merchant has exactly one enrollment"
    assert nested == [item], "The nested route must return the very same row"

    flat, flat_meta = validate_paginated(
        api.list_promotion_enrollments(
            ADMIN_HEADERS,
            {
                "merchant_id": scenario.merchant_id,
                "promotion_plan_id": scenario.plan_id,
                "status": "ACTIVE",
                "limit": 10,
                "offset": 0,
            },
        )
    )
    assert flat_meta["total_count"] == 1, "total_count counts matches before pagination"
    assert flat_meta["has_more"] is False, "One row on a page of ten leaves nothing behind"
    assert [row["id"] for row in flat] == [enrollment_id]


def test_consumer_read_exposes_zero_program_debt_before_any_loan(api):
    """A consumer read carries the registered facts and both program aggregates at zero.

    PRD: "A newly registered consumer carries `existing_program_debt_cents` of zero and `active_loan_count` of zero."

    Design: Corner/endpoints/enrollment_is_readable_through_both_its_nested_and_flat_routes
    """
    scenario = S.enrolled_merchant(api)
    consumer = S.register_consumer(api, scenario.merchant_id)

    read = validate_success(api.get_consumer(consumer["id"], AGENT_HEADERS))
    assert_fields(
        read,
        id=consumer["id"],
        full_name="Dana Ruiz",
        fico_score=742,
        annual_income_cents=9600000,
        existing_program_debt_cents=0,
        active_loan_count=0,
    )


def test_reserve_release_above_the_balance_is_refused_and_moves_nothing(api):
    """A release of one cent more than the reserve balance is refused and the reserve stands.

    PRD: "A `DEPOSIT` raises `holdback_reserve_cents` by `amount_cents`; a `RELEASE` lowers it by `amount_cents` and may not exceed the current balance, with an over-release refused as `ERR_RESERVE_RELEASE_EXCEEDS_BALANCE`."

    Design: Corner/endpoints/holdback_adjustment_action_moves_the_reserve_under_an_occ_guard
    """
    scenario = _settled_reserve_merchant(api)
    before = S.read_merchant(api, scenario.merchant_id)
    assert_fields(
        before,
        holdback_reserve_cents=42000,
        holdback_target_cents=42000,
        reserve_coverage_bps=10000,
    )

    response = api.post_holdback_adjustment(
        scenario.merchant_id,
        F.holdback_adjustment_payload(
            "RELEASE", 42001, before["version"], reason_code="OVER_RELEASE_ATTEMPT"
        ),
        AGENT_HEADERS,
    )
    validate_error(response, E.ERR_RESERVE_RELEASE_EXCEEDS_BALANCE)

    after = S.read_merchant(api, scenario.merchant_id)
    assert_fields(
        after,
        holdback_reserve_cents=42000,
        holdback_target_cents=42000,
        reserve_coverage_bps=10000,
        version=before["version"],
    )


def test_legal_release_recomputes_coverage_against_an_unchanged_target(api):
    """A release of half the reserve halves coverage while the target stays where settlement left it.

    PRD: "Either way `reserve_coverage_bps` is recomputed against the unchanged `holdback_target_cents` and the merchant's `version` increments."

    Design: Corner/endpoints/holdback_adjustment_action_moves_the_reserve_under_an_occ_guard
    """
    scenario = _settled_reserve_merchant(api)
    version = S.merchant_version(api, scenario.merchant_id)

    merchant = validate_success(
        api.post_holdback_adjustment(
            scenario.merchant_id,
            F.holdback_adjustment_payload(
                "RELEASE", 21000, version, reason_code="QUARTERLY_RELEASE"
            ),
            AGENT_HEADERS,
        )
    )
    assert_fields(
        merchant,
        holdback_reserve_cents=21000,
        holdback_target_cents=42000,
        # 21000 * 10000 / 42000 == 5000 exactly.
        reserve_coverage_bps=ratio_bps(21000, 42000),
        enrollment_status="APPROVED",
        version=version + 1,
    )
    assert merchant["reserve_coverage_bps"] == 5000


def test_deposit_lifts_coverage_without_re_deriving_the_target(api):
    """A deposit raises the reserve numerator only; the target and funded volume never move.

    PRD: "Reserve adjustments are legitimately repeatable — the same deposit may be posted twice on purpose — which is exactly why they are version-guarded rather than state-guarded."

    Design: Corner/endpoints/holdback_adjustment_action_moves_the_reserve_under_an_occ_guard
    """
    scenario = _settled_reserve_merchant(api)
    first_version = S.merchant_version(api, scenario.merchant_id)
    validate_success(
        api.post_holdback_adjustment(
            scenario.merchant_id,
            F.holdback_adjustment_payload("RELEASE", 21000, first_version),
            AGENT_HEADERS,
        )
    )

    merchant = validate_success(
        api.post_holdback_adjustment(
            scenario.merchant_id,
            F.holdback_adjustment_payload(
                "DEPOSIT", 1000, first_version + 1, reason_code="MERCHANT_TOP_UP"
            ),
            AGENT_HEADERS,
        )
    )
    assert_fields(
        merchant,
        holdback_reserve_cents=22000,
        holdback_target_cents=42000,
        # 22000 * 10000 / 42000 == 5238.0952..., rounded half up to 5238.
        reserve_coverage_bps=5238,
        funded_volume_cents=1050000,
        version=first_version + 2,
    )
    assert merchant["reserve_coverage_bps"] == ratio_bps(22000, 42000)


def _suspended_merchant_with_open_alert(api):
    """An enrolled merchant suspended by an analyst while one `OPEN` alert stands.

    The alert carries a severity weight of 100, so the aggregate open total halved
    and rounded half up is 50 — below the sixty-point termination trigger.
    """
    scenario = S.enrolled_merchant(api)
    alert = S.raise_fraud_alert(
        api, scenario.merchant_id, "DUPLICATE_CONSUMER", 100, evidence_ref="EV-DUP-1"
    )
    S.program_action(api, scenario.merchant_id, "SUSPEND", reason_code="ANALYST_ACTION")
    return scenario, alert


def test_reinstatement_is_refused_while_a_fraud_alert_is_open(api):
    """A suspended merchant may not be reinstated while any of its fraud alerts is still open.

    PRD: "`SUSPENDED → APPROVED` reverses the posture, but only when two conditions hold: the merchant's `reserve_coverage_bps` must be at least five thousand, and no fraud alert of that merchant may still be `OPEN`."

    Design: Corner/endpoints/reinstatement_is_conditional_on_no_open_fraud_alert
    """
    scenario, _alert = _suspended_merchant_with_open_alert(api)
    suspended = S.read_merchant(api, scenario.merchant_id)
    assert_fields(
        suspended,
        enrollment_status="SUSPENDED",
        suspension_reason_code="ANALYST_ACTION",
        phantom_risk_score=50,
        # No settled draws means no target, and no target is trivially full coverage.
        reserve_coverage_bps=10000,
    )

    response = api.program_action(
        scenario.merchant_id,
        F.program_action_payload("REINSTATE", reason_code="APPEAL_GRANTED"),
        ADMIN_HEADERS,
    )
    validate_error(response, E.ERR_INVALID_MERCHANT_STATE)

    assert_fields(
        S.read_merchant(api, scenario.merchant_id),
        enrollment_status="SUSPENDED",
        version=suspended["version"],
    )
    assert_fields(
        validate_success(api.get_promotion_enrollment(scenario.enrollment["id"], ADMIN_HEADERS)),
        status="SUSPENDED",
    )


def test_clearing_the_alert_drops_the_phantom_score_and_regrades_the_merchant(api):
    """Clearing the only open alert removes its weight entirely and stamps the deciding analyst.

    PRD: "`OPEN → CLEARED` instead recomputes `phantom_risk_score` with the alert dropped entirely, and recomputes `risk_tier`, `portfolio_grade`, `termination_recommended` and `holdback_target_cents`."

    Design: Corner/endpoints/reinstatement_is_conditional_on_no_open_fraud_alert
    """
    scenario, alert = _suspended_merchant_with_open_alert(api)

    cleared = validate_success(
        api.investigate_fraud_alert(
            scenario.merchant_id,
            alert["id"],
            F.investigation_payload("CLEARED", investigation_note="Distinct households"),
            ANALYST_HEADERS,
        )
    )
    assert_fields(cleared, status="CLEARED", investigated_by_user_id="ra-1")

    assert_fields(
        S.read_merchant(api, scenario.merchant_id),
        phantom_risk_score=0,
        portfolio_grade="A",
        termination_recommended=False,
    )


def test_reinstatement_succeeds_once_the_alert_is_cleared(api):
    """With the alert cleared the same reinstatement now lands and revives the enrollment.

    PRD: "Reinstatement clears `suspension_reason_code`, returns every `SUSPENDED` promotion enrollment of that merchant to `ACTIVE`, and increments `version`."

    Design: Corner/endpoints/reinstatement_is_conditional_on_no_open_fraud_alert
    """
    scenario, alert = _suspended_merchant_with_open_alert(api)
    S.set_clock(api, "2026-08-01T00:00:00Z")
    validate_success(
        api.investigate_fraud_alert(
            scenario.merchant_id,
            alert["id"],
            F.investigation_payload("CLEARED"),
            ANALYST_HEADERS,
        )
    )
    before_version = S.merchant_version(api, scenario.merchant_id)

    merchant = validate_success(
        api.program_action(
            scenario.merchant_id,
            F.program_action_payload("REINSTATE", reason_code="APPEAL_GRANTED"),
            ADMIN_HEADERS,
        )
    )
    assert_fields(merchant, enrollment_status="APPROVED", version=before_version + 1)
    assert_empty(merchant, "suspension_reason_code")

    assert_fields(
        validate_success(api.get_promotion_enrollment(scenario.enrollment["id"], ADMIN_HEADERS)),
        status="ACTIVE",
    )


def test_sweep_at_the_offer_expiry_instant_expires_only_the_disclosure(api):
    """At an instant equal to `offer_expires_at` the offer survives and only the disclosure lapses.

    PRD: "A disclosure standing at `DELIVERED` moves `DELIVERED → EXPIRED_UNACKNOWLEDGED` once the clock is more than three days past `disclosure_delivered_at`."

    Design: Corner/endpoints/expiration_sweep_reports_per_dimension_counters_and_is_idempotent
    """
    scenario = S.disclosed_application(api, acknowledge=False)
    S.set_clock(api, "2026-08-15T00:00:00Z")

    counts = S.run_sweep(api)
    _assert_sweep_counters(counts, expired_disclosures=1)

    assert_fields(
        S.read_application(api, scenario.application_id),
        disclosure_status="EXPIRED_UNACKNOWLEDGED",
        decision="APPROVED",
    )


def test_sweep_one_day_later_expires_the_offer_and_leaves_the_disclosure_terminal(api):
    """Once the clock is genuinely past `offer_expires_at` the offer counter fires exactly once.

    PRD: "An offer whose `decision` is `APPROVED` or `COUNTER_OFFERED` moves to `EXPIRED` once the clock is past `offer_expires_at`."

    Design: Corner/endpoints/expiration_sweep_reports_per_dimension_counters_and_is_idempotent
    """
    scenario = S.disclosed_application(api, acknowledge=False)
    S.set_clock(api, "2026-08-15T00:00:00Z")
    S.run_sweep(api)

    S.set_clock(api, "2026-08-16T00:00:00Z")
    counts = S.run_sweep(api)
    _assert_sweep_counters(counts, expired_offers=1)

    assert_fields(
        S.read_application(api, scenario.application_id),
        decision="EXPIRED",
        disclosure_status="EXPIRED_UNACKNOWLEDGED",
    )


def test_sweep_re_run_at_an_unchanged_clock_reports_all_counters_zero(api):
    """A second checkpoint at the same instant finds nothing left to expire.

    PRD: "It is idempotent for a fixed clock — run it twice without moving the clock and the second run reports all zeros."

    Design: Corner/endpoints/expiration_sweep_reports_per_dimension_counters_and_is_idempotent
    """
    S.disclosed_application(api, acknowledge=False)
    S.set_clock(api, "2026-08-16T00:00:00Z")
    first = S.run_sweep(api)
    _assert_sweep_counters(first, expired_disclosures=1, expired_offers=1)

    second = S.run_sweep(api)
    _assert_sweep_counters(second)


def test_enrollment_link_rejects_an_unknown_merchant_in_the_path_first(api):
    """An enrollment aimed at a merchant that does not exist fails on the path identifier.

    PRD: "Identifiers are resolved strictly left to right, and the request fails on the first identifier that does not resolve, with the not-found code belonging to that identifier rather than to any identifier further right."

    Design: Corner/endpoints/enrollment_link_requires_both_the_path_merchant_and_the_body_plan
    """
    scenario = S.approved_merchant(api)

    response = api.create_promotion_enrollment(
        _ABSENT_MERCHANT_ID,
        F.promotion_enrollment_payload(scenario.plan_id),
        UNDERWRITER_HEADERS,
    )
    validate_error(response, E.ERR_MERCHANT_NOT_FOUND)


def test_enrollment_link_rejects_an_unknown_plan_in_the_body(api):
    """With the path merchant real, an unknown plan in the body raises the plan's own code.

    PRD: "Foreign keys carried in a request body are resolved after path identifiers, and among themselves in the order in which they are declared in the payload: `consumer_id`, then `merchant_id`, then `promotion_plan_id`, then `loan_account_id`, then `project_milestone_id`, then `project_id`, then `reopens_case_id`."

    Design: Corner/endpoints/enrollment_link_requires_both_the_path_merchant_and_the_body_plan
    """
    scenario = S.approved_merchant(api)

    response = api.create_promotion_enrollment(
        scenario.merchant_id,
        F.promotion_enrollment_payload(_ABSENT_PLAN_ID),
        UNDERWRITER_HEADERS,
    )
    validate_error(response, E.ERR_PROMOTION_PLAN_NOT_FOUND)


def test_enrollment_link_with_both_sides_real_creates_exactly_one_active_row(api):
    """The accepted call answers 201 with both foreign keys, and the refused ones left no row.

    PRD: "An enrollment is born `ACTIVE`."

    Design: Corner/endpoints/enrollment_link_requires_both_the_path_merchant_and_the_body_plan
    """
    scenario = S.approved_merchant(api)
    validate_error(
        api.create_promotion_enrollment(
            _ABSENT_MERCHANT_ID,
            F.promotion_enrollment_payload(scenario.plan_id),
            UNDERWRITER_HEADERS,
        ),
        E.ERR_MERCHANT_NOT_FOUND,
    )
    validate_error(
        api.create_promotion_enrollment(
            scenario.merchant_id,
            F.promotion_enrollment_payload(_ABSENT_PLAN_ID),
            UNDERWRITER_HEADERS,
        ),
        E.ERR_PROMOTION_PLAN_NOT_FOUND,
    )

    created = validate_success(
        api.create_promotion_enrollment(
            scenario.merchant_id,
            F.promotion_enrollment_payload(scenario.plan_id),
            UNDERWRITER_HEADERS,
        ),
        201,
    )
    assert_fields(
        created,
        merchant_id=scenario.merchant_id,
        promotion_plan_id=scenario.plan_id,
        status="ACTIVE",
        negotiated_discount_bps=449,
    )

    rows, meta = validate_paginated(
        api.list_promotion_enrollments(ADMIN_HEADERS, {"merchant_id": scenario.merchant_id})
    )
    assert meta["total_count"] == 1, "The two refused calls must not have left a row behind"
    assert [row["id"] for row in rows] == [created["id"]]
