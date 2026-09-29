"""A policy carries two state axes, and a move on one never writes the other."""
from test_helpers import (
    SIX_POINT_VIOLATIONS,
    YOUTHFUL_APPLICANT,
    api_client,
    create_exit_notice_payload,
    make_plan_administrator_headers,
    read_application,
    read_carrier,
    read_policy,
    record_deposit,
    setup_policy_in_force,
    validate_success,
)


def _outstanding_policy():
    """A six-point policy in force with only its 61709-cent deposit credited."""
    env = setup_policy_in_force(
        applicant_overrides=YOUTHFUL_APPLICANT,
        application_overrides={"declared_violations": SIX_POINT_VIOLATIONS},
    )
    assert env["policy"]["premium_settlement_status"] == "PREMIUM_OUTSTANDING"
    assert env["policy"]["total_annual_charge_cents"] == 246834
    assert env["policy"]["premium_credited_cents"] == 61709
    return env


def test_paying_the_balance_moves_the_money_axis_and_leaves_coverage_untouched():
    """A deposit that completes the term charge settles the money axis only.

    Recording the outstanding 185125 cents sweeps into the policy, brings the
    credited premium up to the full term charge of 246834 and clears the amount
    still due, so the money axis reaches PAID_IN_FULL. The coverage axis is not
    consulted and the policy stays in force.

    PRD: "when a deposit sweep or a downward re-rating brings
    `premium_credited_cents` up to at least `total_annual_charge_cents`, the money
    axis moves `PREMIUM_OUTSTANDING → PAID_IN_FULL` and sets
    `additional_premium_due_cents` to zero while `policy_status` is not touched at
    all"
    Design: Difficulty/non_linear_state_machine/policy_money_axis_and_coverage_axis_advance_independently
    """
    env = _outstanding_policy()

    record_deposit(env["application"]["id"], env["producer"]["id"], 185125)

    policy = read_policy(env["policy"]["id"])
    assert policy["premium_settlement_status"] == "PAID_IN_FULL"
    assert policy["premium_credited_cents"] == 246834
    assert policy["additional_premium_due_cents"] == 0
    assert policy["policy_status"] == "IN_FORCE"
    application = read_application(env["application"]["id"])
    assert application["deposit_paid_total_cents"] == 246834
    assert application["deposit_balance_cents"] == 0


def test_a_carrier_exit_notice_moves_the_coverage_axis_and_leaves_the_money_alone():
    """Pending reassignment is a coverage-axis state; the settled premium stays settled.

    Once the policy is paid in full, the withdrawal of its servicing carrier moves
    the coverage axis to REASSIGNMENT_PENDING and flags the policy for transfer,
    but the money axis remains PAID_IN_FULL with nothing refunded and nothing due.

    PRD: "Second, every policy of the carrier whose `policy_status` is `IN_FORCE`
    moves `IN_FORCE → REASSIGNMENT_PENDING` with `reassignment_required` set to
    true."
    Design: Difficulty/non_linear_state_machine/policy_money_axis_and_coverage_axis_advance_independently
    """
    env = _outstanding_policy()
    record_deposit(env["application"]["id"], env["producer"]["id"], 185125)

    validate_success(api_client.file_carrier_exit_notice(
        env["carrier"]["id"], create_exit_notice_payload("2027-01-01T00:00:00Z"),
        make_plan_administrator_headers()))

    policy = read_policy(env["policy"]["id"])
    assert policy["policy_status"] == "REASSIGNMENT_PENDING"
    assert policy["reassignment_required"] is True
    assert policy["premium_settlement_status"] == "PAID_IN_FULL"
    assert policy["refund_paid_cents"] == 0
    assert policy["balance_due_cents"] == 0
    assert read_carrier(env["carrier"]["id"])["status"] == "EXIT_NOTICED"
