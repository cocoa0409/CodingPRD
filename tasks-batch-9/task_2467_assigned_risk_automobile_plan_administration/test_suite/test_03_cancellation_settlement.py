"""Cancellation settlement: the two refund bases and the deposit ledger invariant."""
from test_helpers import (
    SIX_POINT_VIOLATIONS,
    YOUTHFUL_APPLICANT,
    accept_assignment,
    api_client,
    assert_deposit_ledger_conserved,
    assignment_for_application,
    bootstrap_plan,
    bring_application_to_certified,
    create_cancellation_payload,
    create_policy_payload,
    make_producer_agent_headers,
    make_servicing_carrier_headers,
    read_application,
    read_assignment,
    read_carrier,
    read_policy,
    run_cycle,
    schedule_cycle,
    set_clock,
    setup_policy_in_force,
    validate_success,
)

CANCELLATION_DATE = "2026-12-15T00:00:00Z"


def _two_identical_paid_in_full_policies():
    """Issue two byte-identical six-point policies, each paid in full at issuance."""
    env = bootstrap_plan()
    first = bring_application_to_certified(
        env,
        applicant_overrides=dict(YOUTHFUL_APPLICANT, full_name="Rosa Vance",
                                 driver_license_number="D-99001"),
        vehicle_overrides={"vin": "1HGCM82633A004352"},
        application_overrides={"declared_violations": SIX_POINT_VIOLATIONS},
        deposit_cents=246834,
        document_prefix="DEC-10",
    )
    second = bring_application_to_certified(
        env,
        applicant_overrides=dict(YOUTHFUL_APPLICANT, full_name="Dale Ortiz",
                                 driver_license_number="D-99002"),
        vehicle_overrides={"vin": "1HGCM82633A004353"},
        application_overrides={"declared_violations": SIX_POINT_VIOLATIONS},
        deposit_cents=246834,
        document_prefix="DEC-11",
    )
    cycle = schedule_cycle(env["plan_period"]["id"])
    run_cycle(cycle["id"])
    first_assignment = assignment_for_application(first["application"]["id"])
    second_assignment = assignment_for_application(second["application"]["id"])
    accept_assignment(first_assignment["id"], first_assignment["carrier_id"])
    accept_assignment(second_assignment["id"], second_assignment["carrier_id"])
    set_clock("2026-09-15T00:00:00Z")
    first_policy = validate_success(api_client.create_policy(
        create_policy_payload(first_assignment["id"], policy_number="AR-100001"),
        make_servicing_carrier_headers(first_assignment["carrier_id"])), 201)
    second_policy = validate_success(api_client.create_policy(
        create_policy_payload(second_assignment["id"], policy_number="AR-100002"),
        make_servicing_carrier_headers(second_assignment["carrier_id"])), 201)
    assert first_policy["premium_settlement_status"] == "PAID_IN_FULL"
    assert second_policy["premium_settlement_status"] == "PAID_IN_FULL"
    set_clock(CANCELLATION_DATE)
    return env, first_assignment, first_policy, second_assignment, second_policy


def test_a_carrier_initiated_cancellation_settles_on_the_pro_rata_basis():
    """The carrier as initiating party fixes the pro-rata basis and keeps 61539 cents.

    A term charge of 246834 cents cancelled 91 whole days into the term earns
    246834 multiplied by 91 and divided by 365, rounded half up, which is 61539
    cents. There is no penalty multiplier and no minimum retained premium, so the
    insured receives every unearned cent — a refund of 185295.

    PRD: "On the **pro-rata** basis, `earned_premium_cents` is
    `total_annual_charge_cents` multiplied by days in force, divided by 365, and
    rounded half up to whole cents; the insured keeps every unearned cent, with no
    penalty and no minimum retained premium."
    Design: Difficulty/dual_variant_calc/cancellation_refund_pro_rata_versus_short_rate_divergence
    """
    _, first_assignment, first_policy, _, _ = _two_identical_paid_in_full_policies()

    validate_success(api_client.cancel_policy(
        first_policy["id"],
        create_cancellation_payload("NON_PAYMENT_OF_PREMIUM", CANCELLATION_DATE),
        make_servicing_carrier_headers(first_assignment["carrier_id"])))

    settled = read_policy(first_policy["id"])
    assert settled["total_annual_charge_cents"] == 246834
    assert settled["cancellation_initiated_by"] == "CARRIER"
    assert settled["refund_basis"] == "PRO_RATA"
    assert settled["earned_premium_cents"] == 61539
    assert settled["refund_paid_cents"] == 185295
    assert settled["premium_credited_cents"] == 61539
    assert settled["balance_due_cents"] == 0
    assert settled["premium_settlement_status"] == "REFUND_ISSUED"


def test_an_insured_initiated_cancellation_settles_on_the_short_rate_basis():
    """The insured as initiating party fixes the short-rate basis and costs 6154 more.

    On the same term charge of 246834 cents and the same 91 days in force, the
    short-rate basis multiplies the pro-rata product by 1.10 before rounding, so
    the plan earns 67693 cents and refunds only 179141 — 6154 cents less than the
    otherwise identical carrier-initiated cancellation.

    PRD: "The divergence is material — on a policy whose
    `total_annual_charge_cents` is 246834, cancelled 91 days in, the pro-rata
    basis earns 61539 and refunds 185295, while the short-rate basis earns 67693
    and refunds only 179141."
    Design: Difficulty/dual_variant_calc/cancellation_refund_pro_rata_versus_short_rate_divergence
    """
    env, first_assignment, first_policy, _, second_policy = \
        _two_identical_paid_in_full_policies()

    validate_success(api_client.cancel_policy(
        first_policy["id"],
        create_cancellation_payload("NON_PAYMENT_OF_PREMIUM", CANCELLATION_DATE),
        make_servicing_carrier_headers(first_assignment["carrier_id"])))
    validate_success(api_client.cancel_policy(
        second_policy["id"],
        create_cancellation_payload("NON_PAYMENT_OF_PREMIUM", CANCELLATION_DATE),
        make_producer_agent_headers(env["producer"]["id"])))

    pro_rata = read_policy(first_policy["id"])
    short_rate = read_policy(second_policy["id"])
    assert short_rate["total_annual_charge_cents"] == 246834
    assert short_rate["cancellation_initiated_by"] == "INSURED"
    assert short_rate["refund_basis"] == "SHORT_RATE"
    assert short_rate["earned_premium_cents"] == 67693
    assert short_rate["refund_paid_cents"] == 179141
    assert short_rate["premium_settlement_status"] == "REFUND_ISSUED"
    assert pro_rata["refund_paid_cents"] - short_rate["refund_paid_cents"] == 6154


def test_the_deposit_ledger_balances_after_the_cancellation_refund():
    """Every cent of the deposit is either earned, refunded or still uncredited.

    The only money that ever entered was a 61709-cent deposit, swept whole into
    premium at issuance. Pro-rata settlement 91 days in earns 61539 and refunds
    170, and 61709 equals 0 uncredited plus 61539 credited plus 170 refunded.

    PRD: "Any operation that writes these figures must leave the invariant
    intact: no cent is created, and no cent vanishes."
    Design: Difficulty/compensating_invariant/deposit_ledger_conserved_across_issuance_credit_and_cancellation_refund
    """
    env = setup_policy_in_force(
        applicant_overrides=YOUTHFUL_APPLICANT,
        application_overrides={"declared_violations": SIX_POINT_VIOLATIONS},
        policy_number="AR-100013",
    )
    assert env["policy"]["premium_settlement_status"] == "PREMIUM_OUTSTANDING"
    set_clock(CANCELLATION_DATE)

    validate_success(api_client.cancel_policy(
        env["policy"]["id"],
        create_cancellation_payload("NON_PAYMENT_OF_PREMIUM", CANCELLATION_DATE),
        make_servicing_carrier_headers(env["carrier"]["id"])))

    settled = read_policy(env["policy"]["id"])
    application = read_application(env["application"]["id"])
    assert settled["refund_basis"] == "PRO_RATA"
    assert settled["earned_premium_cents"] == 61539
    assert settled["refund_paid_cents"] == 170
    assert settled["balance_due_cents"] == 0
    assert settled["premium_credited_cents"] == 61539
    assert application["deposit_paid_total_cents"] == 61709
    assert application["deposit_balance_cents"] == 0
    assert_deposit_ledger_conserved(application, [settled])


def test_cancellation_closes_the_assignment_the_application_and_the_headcount():
    """Settlement reduces the credited premium to the earned figure and closes the risk.

    Because the refund is positive the money axis lands on REFUND_ISSUED, the
    coverage axis lands on CANCELLED, the assignment closes, the application
    closes as cancelled, and the servicing carrier gives back the assigned risk.

    PRD: "On the coverage axis the policy moves `IN_FORCE → CANCELLED`, its
    `cancellation_reason_code`, `cancellation_effective_date` and
    `cancellation_initiated_by` are recorded, its assignment moves to `CLOSED`,
    its application moves `POLICY_ISSUED → CLOSED_CANCELLED`, and the servicing
    carrier's `assigned_risk_count` falls by 1 with `quota_variance_units`,
    `overallocated` and `posture` recomputed."
    Design: Difficulty/compensating_invariant/deposit_ledger_conserved_across_issuance_credit_and_cancellation_refund
    """
    env = setup_policy_in_force(
        applicant_overrides=YOUTHFUL_APPLICANT,
        application_overrides={"declared_violations": SIX_POINT_VIOLATIONS},
        policy_number="AR-100013",
    )
    set_clock(CANCELLATION_DATE)

    validate_success(api_client.cancel_policy(
        env["policy"]["id"],
        create_cancellation_payload("NON_PAYMENT_OF_PREMIUM", CANCELLATION_DATE),
        make_servicing_carrier_headers(env["carrier"]["id"])))

    settled = read_policy(env["policy"]["id"])
    assert settled["premium_settlement_status"] == "REFUND_ISSUED"
    assert settled["policy_status"] == "CANCELLED"
    assert read_assignment(env["assignment"]["id"])["status"] == "CLOSED"
    assert read_application(env["application"]["id"])["status"] == "CLOSED_CANCELLED"
    carrier = read_carrier(env["carrier"]["id"])
    assert carrier["assigned_risk_count"] == 0
    assert carrier["quota_variance_units"] == -1.0
