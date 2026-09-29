"""
Derived-figure behaviour: the gated zone premium on enforcement cost, the
four-place signage ratio and the audit it is selected from, the two pinned
media branch orders, the ceiling on service hours, the signed ledger identity,
and the inclusive due-date comparison behind a delinquency assessment.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
    validate_success,
)

from test_helpers import factories, fixtures
from test_helpers.assertions import (
    assert_citation_money_identity,
    assert_instant_equals,
    assert_ledger_row,
    assert_rate_equals,
    ledger_sources,
)
from test_helpers.constants import (
    DEPLOYMENT_STATUS_CLOSED,
    IDENTITY_SELF_REPORTED,
    MEDIA_MOBILE_QR,
    MEDIA_PAPER_TRANSFER,
    MEDIA_SMARTCARD,
    OUTCOME_COMPLIANT,
    OUTCOME_PENDING,
    PAYMENT_SOURCE_DIRECT,
    PAYMENT_SOURCE_SERVICE_CREDIT,
    PLAN_STATUS_DEFAULTED,
    SERVICE_STATUS_ACTIVE,
    SETTLEMENT_OUTSTANDING,
    SETTLEMENT_SATISFIED,
    SETTLEMENT_SERVICE_ACTIVE,
    VALIDATION_EXPIRED,
    VALIDATION_NO_PROOF,
    VALIDATION_UNVALIDATED_TAP,
    VALIDATION_VALID,
)
from test_helpers.fixtures import WINDOW_END
from test_helpers.test_users import ANALYST_HEADERS, PLANNER_HEADERS, make_rider_headers

FIRST_DUE_AT = "2026-09-04T09:00:00Z"
SIXTY_DAYS_ON = "2026-10-04T09:00:00Z"


def test_a_default_multiplier_zone_pays_no_premium_on_its_enforcement_cost(api):
    """
    A zone premium of 500 basis points — 5 percent of the labour total, rounded
    half up — is added when and only when the governing zone's
    `penalty_multiplier_bps` is strictly greater than 10000; for a zone at
    exactly 10000 the premium is zero.

    Design: Corner/calculations/enforcement_cost_applies_no_zone_premium_when_multiplier_is_exactly_ten_thousand
    """
    env = fixtures.build_environment(api, penalty_multiplier_bps=None, enforcement_policy=None)
    deployment = fixtures.build_active_deployment(api, env, target_sample_size=1)

    encounter = fixtures.build_pending_encounter(
        api,
        env,
        deployment,
        fare_media_type=MEDIA_SMARTCARD,
        media_reference="SC-1",
        media_validated_at="2026-08-05T06:50:00Z",
        media_expires_at="2026-08-05T08:00:00Z",
        media_zone_code="ZN1",
        identity_capture_method=IDENTITY_SELF_REPORTED,
    )
    assert encounter["validation_result"] == VALIDATION_VALID
    fixtures.resolve(api, encounter["id"], env["inspector"]["id"], OUTCOME_COMPLIANT)

    fixtures.move_clock(api, WINDOW_END)
    closed = validate_success(api.close_deployment(deployment["id"], PLANNER_HEADERS))

    assert closed["status"] == DEPLOYMENT_STATUS_CLOSED
    assert closed["enforcement_cost_cents"] == 129600
    assert closed["measured_evasion_rate_bps"] == 0
    assert closed["resolved_evasion_rate_bps"] == 0
    assert closed["achieved_sample_count"] == 1
    assert_rate_equals(
        closed["sample_adequacy_ratio"], 1.0000, "deployment.sample_adequacy_ratio"
    )


def test_the_signage_ratio_rounds_half_up_at_the_fourth_place_and_caps_at_one(api):
    """
    `signage_compliance_pct` becomes `verified_sign_count` divided by
    `required_sign_count`, rounded half up to 4 decimal places, then capped so
    that a zone with more verified notices than statute requires reports exactly
    1.0000 rather than a figure above one.

    Design: Corner/calculations/signage_compliance_rounds_half_up_to_four_places_and_caps_at_one
    """
    fixtures.move_clock(api, fixtures.CLOCK_EPOCH)
    zone = fixtures.register_zone(
        api,
        required_sign_count=3,
        penalty_multiplier_bps=None,
        enforcement_policy=None,
        max_concurrent_deployments=None,
    )

    fixtures.file_audit(api, zone["id"], 2, audited_at="2026-08-01T01:00:00Z")
    two_of_three = fixtures.read_zone(api, zone["id"])
    assert two_of_three["verified_sign_count"] == 2
    assert_rate_equals(
        two_of_three["signage_compliance_pct"], 0.6667, "zone.signage_compliance_pct"
    )

    fixtures.file_audit(api, zone["id"], 4, audited_at="2026-08-01T02:00:00Z")
    four_of_three = fixtures.read_zone(api, zone["id"])
    assert four_of_three["verified_sign_count"] == 4
    assert_rate_equals(
        four_of_three["signage_compliance_pct"], 1.0000, "zone.signage_compliance_pct"
    )


def test_the_signage_ratio_follows_the_greatest_audited_at_not_the_newest_row(api):
    """
    Among all audits filed against the zone ... exactly one is authoritative: the
    audit with the greatest `audited_at`, and where two audits share the same
    `audited_at`, the one with the later `created_at`.

    Design: Corner/calculations/signage_compliance_uses_only_the_latest_audit_by_audited_at
    """
    fixtures.move_clock(api, fixtures.CLOCK_EPOCH)
    zone = fixtures.register_zone(
        api,
        penalty_multiplier_bps=None,
        enforcement_policy=None,
        max_concurrent_deployments=None,
    )

    fixtures.file_audit(api, zone["id"], 7, audited_at="2026-08-01T03:00:00Z")
    fixtures.file_audit(api, zone["id"], 9, audited_at="2026-08-01T05:00:00Z")
    fixtures.file_audit(api, zone["id"], 4, audited_at="2026-08-01T01:00:00Z")

    read = fixtures.read_zone(api, zone["id"])
    assert read["verified_sign_count"] == 9
    assert_rate_equals(read["signage_compliance_pct"], 0.9000, "zone.signage_compliance_pct")

    rows, meta = validate_paginated(api.list_zone_signage_audits(zone["id"], ANALYST_HEADERS))
    assert meta["total_count"] == 3
    assert [row["signs_verified_count"] for row in rows] == [7, 9, 4]


def test_the_media_verdict_checks_expiry_before_zone_only_on_the_paper_branch(api):
    """
    A paper transfer that is both expired and sold for the wrong zone therefore
    reads `EXPIRED`, while an equivalent smartcard reads `WRONG_ZONE`.

    Design: Corner/calculations/media_branch_order_differs_between_electronic_and_paper_fare_media
    """
    env = fixtures.build_environment(api)
    deployment = fixtures.build_active_deployment(api, env)

    electronic = fixtures.build_pending_encounter(
        api,
        env,
        deployment,
        occurred_at="2026-08-05T07:00:00Z",
        fare_media_type=MEDIA_MOBILE_QR,
        media_reference="QR-1",
        media_expires_at="2026-08-05T06:00:00Z",
        media_zone_code="ZN9",
        identity_capture_method=IDENTITY_SELF_REPORTED,
    )
    assert electronic["validation_result"] == VALIDATION_UNVALIDATED_TAP

    paper = fixtures.build_pending_encounter(
        api,
        env,
        deployment,
        occurred_at="2026-08-05T07:10:00Z",
        fare_media_type=MEDIA_PAPER_TRANSFER,
        media_reference="PT-1",
        media_validated_at="2026-08-05T06:30:00Z",
        media_expires_at="2026-08-05T06:40:00Z",
        media_zone_code="ZN9",
        identity_capture_method=IDENTITY_SELF_REPORTED,
    )
    assert paper["validation_result"] == VALIDATION_EXPIRED

    without_expiry = fixtures.build_pending_encounter(
        api,
        env,
        deployment,
        occurred_at="2026-08-05T07:20:00Z",
        fare_media_type=MEDIA_SMARTCARD,
        media_reference="SC-1",
        media_validated_at="2026-08-05T06:45:00Z",
        media_zone_code="ZN1",
        identity_capture_method=IDENTITY_SELF_REPORTED,
    )
    assert without_expiry["validation_result"] == VALIDATION_NO_PROOF

    for created in (electronic, paper, without_expiry):
        assert created["outcome"] == OUTCOME_PENDING
        assert fixtures.read_encounter(api, created["id"])["validation_result"] == (
            created["validation_result"]
        )


def test_required_service_hours_round_the_balance_up_to_a_whole_hour(api):
    """
    `required_hours` is the citation's `outstanding_balance_cents` divided by 1500
    and rounded **up** to a whole hour, so a balance of 8100 cents requires 6
    hours rather than 5.4.

    Design: Corner/calculations/service_hours_required_ceils_the_outstanding_balance
    """
    chain = fixtures.build_citation_chain(api)
    citation = chain["citation"]
    assert citation["total_due_cents"] == 9720
    assert citation["outstanding_balance_cents"] == 9720

    assignment = validate_success(
        api.create_service_assignment(
            factories.service_assignment_payload(
                citation_id=citation["id"],
                partner_org_name="Riverside Food Bank",
                expected_citation_version=citation["version"],
            ),
            make_rider_headers(chain["rider"]["id"]),
        ),
        expected_status=201,
    )
    assert assignment["required_hours"] == 7
    assert (
        fixtures.read_citation(api, citation["id"])["settlement_status"]
        == SETTLEMENT_SERVICE_ACTIVE
    )

    worked = get_success_data(
        api.log_service_hours(assignment["id"], factories.log_hours_payload(2), PLANNER_HEADERS)
    )
    assert worked["hours_completed"] == 2
    assert worked["credited_cents"] == 3000
    assert worked["status"] == SERVICE_STATUS_ACTIVE

    after = fixtures.read_citation(api, citation["id"])
    assert after["service_credit_cents"] == 3000
    assert after["outstanding_balance_cents"] == 6720
    assert_citation_money_identity(after)

    ledger = fixtures.citation_ledger(api, citation["id"])
    assert len(ledger) == 1
    assert_ledger_row(
        ledger[0],
        PAYMENT_SOURCE_SERVICE_CREDIT,
        3000,
        hours_credited=2,
        label="service credit row",
    )


def test_partial_direct_payments_subtract_exactly_and_the_remainder_satisfies(api):
    """
    A partial payment is allowed and simply appends a `DIRECT` ledger row ...
    raising `amount_paid_cents` by the paid amount and lowering
    `outstanding_balance_cents` accordingly while the citation stays
    `OUTSTANDING`.  A payment that exactly equals the outstanding balance closes
    the citation out.

    Design: Corner/calculations/outstanding_balance_is_an_exact_signed_aggregation_over_the_ledger
    """
    chain = fixtures.build_citation_chain(api)
    citation = chain["citation"]
    rider_id = chain["rider"]["id"]
    assert citation["total_due_cents"] == 9720

    fixtures.pay_direct(api, citation["id"], 3000, rider_id)
    first = fixtures.read_citation(api, citation["id"])
    assert first["amount_paid_cents"] == 3000
    assert first["outstanding_balance_cents"] == 6720
    assert first["settlement_status"] == SETTLEMENT_OUTSTANDING

    fixtures.pay_direct(api, citation["id"], 2000, rider_id)
    second = fixtures.read_citation(api, citation["id"])
    assert second["amount_paid_cents"] == 5000
    assert second["outstanding_balance_cents"] == 4720
    assert second["settlement_status"] == SETTLEMENT_OUTSTANDING

    fixtures.pay_direct(api, citation["id"], 4720, rider_id)

    settled = fixtures.read_citation(api, citation["id"])
    assert settled["amount_paid_cents"] == 9720
    assert settled["outstanding_balance_cents"] == 0
    assert settled["settlement_status"] == SETTLEMENT_SATISFIED
    assert settled["version"] == 4
    assert_citation_money_identity(settled)

    ledger = fixtures.citation_ledger(api, citation["id"])
    assert ledger_sources(ledger) == [PAYMENT_SOURCE_DIRECT] * 3
    assert [row["amount_cents"] for row in ledger] == [3000, 2000, 4720]
    for row in ledger:
        assert not row.get("plan_id")


def test_two_installments_already_due_and_unpaid_default_the_plan(api):
    """
    The due-date comparison is inclusive: an installment falling due at exactly
    the current clock instant already counts as due.  Where the recomputed count
    reaches 2 or more, the plan moves `ACTIVE → DEFAULTED` and the citation's
    `settlement_status` reverts `PLAN_ACTIVE → OUTSTANDING`.

    Design: Corner/calculations/delinquency_counts_due_installments_inclusively_at_the_second_miss
    """
    chain = fixtures.build_citation_chain(api)
    citation = chain["citation"]

    plan = validate_success(
        api.create_payment_plan(
            factories.payment_plan_payload(
                citation_id=citation["id"],
                installment_count=3,
                down_payment_cents=1000,
                expected_citation_version=citation["version"],
            ),
            make_rider_headers(chain["rider"]["id"]),
        ),
        expected_status=201,
    )
    assert plan["financed_cents"] == 8720
    assert plan["installments_paid_count"] == 0
    assert plan["missed_installment_count"] == 0
    assert_instant_equals(plan["first_due_at"], FIRST_DUE_AT, "plan.first_due_at")

    fixtures.move_clock(api, SIXTY_DAYS_ON)
    assessed = get_success_data(api.assess_delinquency(plan["id"], PLANNER_HEADERS))

    assert assessed["missed_installment_count"] == 2
    assert assessed["status"] == PLAN_STATUS_DEFAULTED

    after = fixtures.read_citation(api, citation["id"])
    assert after["settlement_status"] == SETTLEMENT_OUTSTANDING
    assert after["outstanding_balance_cents"] == 8720
    assert after["amount_paid_cents"] == 1000
    assert_citation_money_identity(after)
