"""Conservation invariants across a forward + compensating operation pair.

Translates difficulty (A) compensating_invariant instances on package credits
and owner wallet value.
"""
import pytest
from test_helpers import (
    api_client, validate_success,
    setup_package_funded_confirmed, setup_confirmed_reservation,
    TEST_USERS,
)

MGR = TEST_USERS["manager_headers"]


def test_cancel_preserves_package_credit_total(api):
    """PRD §3.6: "the system creates a `PackageRedemption` recording `credits_used` of 1
    with `reversed` false, sets the reservation's `redeemed_credit` to true, and recomputes
    the package's `credits_remaining`."
    PRD §3.8: "In addition, if the reservation's `redeemed_credit` is true, the linked
    `PackageRedemption` has its `reversed` set true (the first cascade hop, reservation
    driving the redemption) and the owning package's `credits_remaining` is then recomputed
    (the second hop)."

    Confirm consumes 1 (10 -> 9); cancel reverses it (9 -> 10) — total conserved.

    Design: Difficulty/compensating_invariant/cancel_preserves_package_credit_total
    """
    ctx = setup_package_funded_confirmed(tier="DAYCARE_10", start_date="2026-01-15")
    package, res = ctx["package"], ctx["reservation"]
    assert package["credits_remaining"] == 9, "forward consume leaves 9"
    validate_success(api.cancel_reservation(res["id"], MGR), 200)
    pkg_after = validate_success(api.get_package(package["id"], MGR), 200)
    assert pkg_after["credits_remaining"] == 10, "compensating reverse conserves credits_total"


def test_no_show_preserves_package_credit_total(api):
    """PRD §3.6: "the system creates a `PackageRedemption` recording `credits_used` of 1
    with `reversed` false, sets the reservation's `redeemed_credit` to true, and recomputes
    the package's `credits_remaining`."
    PRD §3.8: "As with cancellation, every `OCCUPIED` run assignment is released, and if
    `redeemed_credit` is true the linked `PackageRedemption` is reversed and the package's
    `credits_remaining` recomputed."

    A no-show (a different compensating trigger than cancel) on a package-funded
    reservation also restores the consumed credit (9 -> 10), conserving credits_total.

    Design: Difficulty/compensating_invariant/cancel_preserves_package_credit_total
    """
    ctx = setup_package_funded_confirmed(tier="DAYCARE_10", start_date="2026-01-10")
    facility, package, res = ctx["facility"], ctx["package"], ctx["reservation"]
    assert package["credits_remaining"] == 9
    # Advance the business date past start_date so a no-show is permitted.
    validate_success(api.advance_clock(facility["id"], {"to_date": "2026-01-12"}, MGR), 200)
    validate_success(api.mark_no_show(res["id"], MGR), 200)
    pkg_after = validate_success(api.get_package(package["id"], MGR), 200)
    assert pkg_after["credits_remaining"] == 10, "no-show reversal conserves credits_total"


def test_cancel_preserves_owner_wallet_value(api):
    """PRD §3.5: "When a deposit is paid toward a `REQUESTED` reservation, the request
    supplies `cash_cents`. The system first debits the owner's `wallet_credit_cents`,
    applying as much of it as the remaining deposit needs, and then applies the supplied
    `cash_cents`; the sum raises `deposit_paid_cents`."
    PRD §3.8: "Cancellation computes a refund into `refund_cents` and credits it to the
    owner's `wallet_credit_cents`."
    PRD §3.8: "when the lead is at least 7 days the refund is the full `deposit_paid_cents`".

    A 4320 cash deposit (wallet starts 0) comes back as wallet credit on a high-lead
    cancel: wallet 0 -> 4320, conserving the owner's value.

    Design: Difficulty/compensating_invariant/cancel_preserves_owner_wallet_value
    """
    ctx = setup_confirmed_reservation(
        service_type="OVERNIGHT", start_date="2026-02-01", end_date="2026-02-04",
        deposit_policy="STANDARD", weight_kg=18, pay_cash=4320)
    owner, res = ctx["owner"], ctx["reservation"]
    # Wallet was fully debited paying the cash deposit; starts at 0 by construction.
    owner_now = validate_success(api.get_owner(owner["id"], MGR), 200)
    assert owner_now["wallet_credit_cents"] == 0, "no leftover credit before cancel"
    validate_success(api.cancel_reservation(res["id"], MGR), 200)
    owner_after = validate_success(api.get_owner(owner["id"], MGR), 200)
    assert owner_after["wallet_credit_cents"] == 4320, "refund credit returns the deposit value"


def test_cancel_preserves_owner_wallet_value_strict_policy(api):
    """PRD §3.8: "Cancellation computes a refund into `refund_cents` and credits it to the
    owner's `wallet_credit_cents`."
    PRD §3.8: "when the lead is at least 7 days the refund is the full `deposit_paid_cents`".
    PRD §3.5: "The system first debits the owner's `wallet_credit_cents`, applying as much
    of it as the remaining deposit needs, and then applies the supplied `cash_cents`; the
    sum raises `deposit_paid_cents`. The owner's wallet is reduced by whatever credit was
    consumed."

    Under STRICT policy an OVERNIGHT/MEDIUM/3n deposit is 4000*1.2*3*0.50 = 7200; paid in
    cash from a zero wallet then cancelled at high lead returns 7200 to the wallet,
    conserving the owner's value at a different deposit magnitude.

    Design: Difficulty/compensating_invariant/cancel_preserves_owner_wallet_value
    """
    ctx = setup_confirmed_reservation(
        service_type="OVERNIGHT", start_date="2026-02-01", end_date="2026-02-04",
        deposit_policy="STRICT", weight_kg=18, pay_cash=7200)
    owner, res = ctx["owner"], ctx["reservation"]
    assert res["deposit_paid_cents"] == 7200
    validate_success(api.cancel_reservation(res["id"], MGR), 200)
    owner_after = validate_success(api.get_owner(owner["id"], MGR), 200)
    assert owner_after["wallet_credit_cents"] == 7200, "full deposit returns as wallet credit"
