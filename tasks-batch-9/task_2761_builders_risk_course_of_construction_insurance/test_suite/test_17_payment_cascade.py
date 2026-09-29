"""Issuing indemnity: erosion, reserve, the payment axis and closure.

Four hops run off one payment, each caused by the one before it. Two payments
are issued so the intermediate PARTIALLY_PAID state is observable.
"""
from prd_bench_local_runner.testing import get_success_data

from test_helpers import api_client
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_claim,
    assert_claim_incurred_identity,
    assert_coverage_part,
    assert_erosion_reconciles,
)
from test_helpers.factories import loss_item

TWO_BUCKET_PART_PLAN = (
    ("MATERIALS_ON_SITE", 1000000000),
    ("IN_TRANSIT", 200000000),
)

TWO_BUCKET_ITEMS = [
    loss_item("MATERIALS_ON_SITE", 45678920),
    loss_item("IN_TRANSIT", 12345670),
]


def _settled_two_bucket_claim():
    """A settled claim with a lender loss payee alongside the owner."""
    account = fx.draft_account(parts=TWO_BUCKET_PART_PLAN)
    lender = fx.add_interest(
        account, party_role="LENDER", insurable_interest_pct=0,
        party_name="Seaboard Trust Bank", loss_payee_priority=2)
    fx.acknowledge_interest(account, lender)
    fx.incept_account(fx.bind_account(fx.quote_account(account)))
    claim = fx.adjusted_claim(
        account, TWO_BUCKET_ITEMS, adjustment_basis="ACTUAL_LOSS")
    assert claim["indemnity_cents"] == 48024590, claim["indemnity_cents"]
    return account, fx.settle_claim(claim, headers=fx.UM), lender


def test_the_first_payment_erodes_its_bucket_and_stops_the_axes_short_of_paid():
    """The payment raises the matching coverage part's eroded_cents and lowers
    its available_cents, which raises the policy's eroded_total_cents and the
    claim's paid_cents while lowering the outstanding reserve. Because the
    resulting paid_cents is strictly between zero and indemnity_cents the
    payment axis reads PARTIALLY_PAID and the adjustment axis stays SETTLED.

    Design: Difficulty/transitive_cascade/loss_payment_cascades_erosion_reserve_and_closure
    """
    account, claim, _ = _settled_two_bucket_claim()

    fx.issue_payment(account, claim, "MATERIALS_ON_SITE", 35678920)

    materials = account.part("MATERIALS_ON_SITE")
    assert_coverage_part(materials, status="ACTIVE")
    assert materials["eroded_cents"] == 35678920, materials["eroded_cents"]
    assert materials["available_cents"] == 964321080, materials["available_cents"]

    mid = get_success_data(api_client.get_claim(claim["id"], fx.CA))
    assert_claim(mid, adjustment_status="SETTLED", payment_status="PARTIALLY_PAID")
    assert mid["outstanding_reserve_cents"] == 12345670, (
        mid["outstanding_reserve_cents"])


def test_the_second_payment_exhausts_the_reserve_and_closes_the_adjustment_axis():
    """When paid_cents reaches indemnity_cents exactly the payment axis becomes
    PAID, and because the adjustment axis is SETTLED it follows SETTLED ->
    CLOSED. The policy's eroded_total_cents reconciles against the sum of the
    parts' erosion, and total_incurred_cents equals indemnity_cents.

    Design: Difficulty/transitive_cascade/loss_payment_cascades_erosion_reserve_and_closure
    """
    account, claim, lender = _settled_two_bucket_claim()

    fx.issue_payment(account, claim, "MATERIALS_ON_SITE", 35678920)
    mid = get_success_data(api_client.get_claim(claim["id"], fx.CA))
    fx.issue_payment(account, mid, "IN_TRANSIT", 12345670, payee=lender)

    in_transit = account.part("IN_TRANSIT")
    assert in_transit["eroded_cents"] == 12345670, in_transit["eroded_cents"]
    assert in_transit["available_cents"] == 187654330, in_transit["available_cents"]

    policy = account.refresh_policy()
    assert policy["eroded_total_cents"] == 48024590, policy["eroded_total_cents"]
    assert_erosion_reconciles(policy, list(account.parts.values()))

    final = get_success_data(api_client.get_claim(claim["id"], fx.CA))
    assert_claim(final, adjustment_status="CLOSED", payment_status="PAID")
    assert final["outstanding_reserve_cents"] == 0, final["outstanding_reserve_cents"]
    assert final["total_incurred_cents"] == 48024590, final["total_incurred_cents"]
    assert_claim_incurred_identity(final)
