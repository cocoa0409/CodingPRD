"""A claim carries two independent state axes on one row.

The adjustment axis moves under its own triggers; the payment axis moves only
as a consequence of loss payments. Closure is the one place they touch.
"""
from prd_bench_local_runner.testing import get_success_data

from test_helpers import api_client
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_claim, assert_loss_payment
from test_helpers.factories import loss_item

TRANSIT_PART_PLAN = (
    ("IN_TRANSIT", 200000000),
    ("MATERIALS_ON_SITE", 1000000000),
)

THEFT_ITEMS = [loss_item("IN_TRANSIT", 12345670)]


def _settled_theft_claim():
    account = fx.in_force_account(parts=TRANSIT_PART_PLAN)
    claim = fx.adjusted_claim(
        account,
        THEFT_ITEMS,
        adjustment_basis="ACTUAL_LOSS",
        peril="THEFT",
        loss_date="2027-01-20T00:00:00Z",
    )
    assert claim["indemnity_cents"] == 2345670, claim["indemnity_cents"]
    return account, fx.settle_claim(claim, headers=fx.UM)


def test_the_two_axes_hold_different_values_and_a_full_payment_closes_the_claim():
    """Settlement moves the adjustment axis ADJUSTED -> SETTLED and leaves the
    payment axis untouched, so one row reads SETTLED and UNPAID at once. A
    payment whose amount takes paid_cents up to indemnity_cents moves the
    payment axis to PAID, and because the adjustment axis is SETTLED it follows
    SETTLED -> CLOSED.

    Design: Difficulty/non_linear_state_machine/claim_parallel_adjustment_and_payment_axes
    """
    account, claim = _settled_theft_claim()

    assert_claim(claim, adjustment_status="SETTLED", payment_status="UNPAID")

    fx.issue_payment(account, claim, "IN_TRANSIT", 2345670)
    paid = get_success_data(api_client.get_claim(claim["id"], fx.CA))

    assert_claim(paid, adjustment_status="CLOSED", payment_status="PAID")
    assert paid["paid_cents"] == 2345670, paid["paid_cents"]
    assert paid["outstanding_reserve_cents"] == 0, paid["outstanding_reserve_cents"]


def test_voiding_the_only_payment_steps_both_axes_backwards_together():
    """Voiding drops paid_cents by the voided amount, walks the payment axis
    PAID -> UNPAID because no issued payments remain, and returns the
    adjustment axis CLOSED -> SETTLED as soon as paid_cents falls below
    indemnity_cents. Erosion is recomputed from the surviving issued rows, so
    the coverage part is back to zero erosion.

    Design: Difficulty/non_linear_state_machine/claim_parallel_adjustment_and_payment_axes
    """
    account, claim = _settled_theft_claim()
    payment = fx.issue_payment(account, claim, "IN_TRANSIT", 2345670)

    voided = fx.void_payment(account, payment)
    after = get_success_data(api_client.get_claim(claim["id"], fx.CA))

    assert_loss_payment(voided, status="VOIDED")
    assert_claim(after, adjustment_status="SETTLED", payment_status="UNPAID")
    assert after["paid_cents"] == 0, after["paid_cents"]
    assert after["outstanding_reserve_cents"] == 2345670, (
        after["outstanding_reserve_cents"])
    assert account.part("IN_TRANSIT")["eroded_cents"] == 0, account.parts
