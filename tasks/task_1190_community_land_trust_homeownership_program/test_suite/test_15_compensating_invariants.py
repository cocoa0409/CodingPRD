"""Compensating invariants — subsidy/proceeds conservation, fee arrears conservation."""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    create_lease_payload,
    create_resale_listing_payload,
    get_success_data,
    setup_active_lease,
    setup_defaulted_lease,
    setup_program,
    make_household_headers,
)


def _pa():
    return TEST_USERS["platform_admin_headers"]


def _lm():
    return TEST_USERS["lease_manager_headers"]


def test_indexed_subsidy_plus_proceeds_conservation():
    """PRD §3.5: "Across both variants a conservation invariant holds: the
    seller's gain plus the program's retained gain equals the total
    appreciation. ... for the indexed variant, subsidy retained plus seller
    proceeds equals S0 plus A1 minus P0 whenever A1 exceeds the asking
    price."

    Design: Difficulty/compensating_invariant/subsidy_plus_proceeds_conservation_across_resale
    """
    prog = setup_program(
        name="P-INV-I",
        resale_formula_kind="INDEXED",
        indexed_annual_appreciation_pct=0.015,
    )
    # PRD §3.5/§3.9: opening a listing requires the seller ELIGIBLE and the
    # unit OCCUPIED by the seller's ACTIVE lease. Lease start 2016-04-01 pins
    # Y = floor(3682 / 365.25) = 10 at the 2026-05-01 startup clock.
    _, unit, _, lease = setup_active_lease(
        prog["id"],
        start_date="2016-04-01T00:00:00Z",
        purchase_price_cents=20_000_000,
    )
    listing = get_success_data(
        api_client.create_resale_listing(
            prog["id"],
            unit["id"],
            create_resale_listing_payload(
                seller_lease_id=lease["id"], appraisal_at_listing_cents=35_000_000
            ),
            _lm(),
        )
    )
    # INDEXED: indexed = 20_000_000 * (1 + 0.015 * 10) = 23_000_000 < A1, so
    # asking = 23_000_000; proceeds = 23_000_000 - 20_000_000 = 3_000_000.
    # subsidy_retained = 5_000_000 + (35_000_000 - 23_000_000) = 17_000_000.
    # Conservation: subsidy_retained + seller_proceeds == S0 + A1 - P0
    #             = 5_000_000 + 35_000_000 - 20_000_000 = 20_000_000.
    lhs = listing["subsidy_retained_cents"] + listing["seller_proceeds_cents"]
    rhs = 5_000_000 + 35_000_000 - 20_000_000
    assert lhs == rhs, (
        f"Conservation violated: {listing['subsidy_retained_cents']} + "
        f"{listing['seller_proceeds_cents']} = {lhs}, expected {rhs}"
    )


def test_appraisal_based_subsidy_plus_proceeds_conservation():
    """PRD §3.5: "Across both variants a conservation invariant holds: the
    seller's gain plus the program's retained gain equals the total
    appreciation. ... The invariant can also be phrased as: subsidy retained
    plus seller proceeds, plus P0, equals A1 when appreciation is positive
    (for the appraisal variant)..."

    The phrased invariant reduces, via the §3.5 formula definitions
    (subsidy_retained = S0 + appreciation - seller_share;
    seller_proceeds = seller_share; appreciation = A1 - A0), to
    S0 + A1 - A0 + P0 == A1, i.e. it holds exactly when A0 == S0 + P0.
    A0 is "the unit's `appraisal_value_cents` captured at the time of the
    seller's purchase" and §3.3 initializes it to 0, so this test arranges
    A0 = S0 + P0 = 25_000_000 through the only PRD pathway that sets it: a
    refinance approval on a prior lease (§3.8: "Approval ... refreshes the
    unit's `appraisal_value_cents` to the request's `appraised_value_cents`").

    Design: Difficulty/compensating_invariant/subsidy_plus_proceeds_conservation_across_resale
    """
    prog = setup_program(
        name="P-INV-A",
        resale_formula_kind="APPRAISAL_BASED",
        appraisal_seller_share_pct=0.25,
    )
    # Prior occupant: activates a lease, then an approved refinance refreshes
    # the unit's appraisal_value_cents to S0 + P0 = 5_000_000 + 20_000_000.
    _, unit, hh0, lease0 = setup_active_lease(
        prog["id"], purchase_price_cents=20_000_000
    )
    hh0_headers = make_household_headers(hh0["id"])
    refi = get_success_data(
        api_client.create_refinance_request(
            prog["id"],
            unit["id"],
            lease0["id"],
            {
                "lender_name": "Appraisal Bank",
                "requested_loan_cents": 20_000_000,
                "requested_cash_out_cents": 0,
                "appraised_value_cents": 25_000_000,
            },
            hh0_headers,
        )
    )
    get_success_data(
        api_client.submit_refi_to_lender(
            prog["id"], unit["id"], lease0["id"], refi["id"], hh0_headers
        )
    )
    get_success_data(
        api_client.approve_refinance(
            prog["id"], unit["id"], lease0["id"], refi["id"], _lm()
        )
    )
    # Terminate the prior lease so the unit is VACANT for the seller.
    lease0_now = get_success_data(
        api_client.get_lease(prog["id"], unit["id"], lease0["id"], _lm())
    )
    get_success_data(
        api_client.terminate_lease(
            prog["id"],
            unit["id"],
            lease0["id"],
            {"expected_lease_version": lease0_now["version"]},
            _lm(),
        )
    )
    # Seller activates a fresh lease; A0 is captured as the unit's current
    # appraisal_value_cents = 25_000_000 = S0 + P0.
    from test_helpers import setup_eligible_household

    hh_s, _, _ = setup_eligible_household(prog["id"], legal_name="Seller")
    lease_s = get_success_data(
        api_client.create_lease(
            prog["id"],
            unit["id"],
            create_lease_payload(
                household_id=hh_s["id"], purchase_price_cents=20_000_000
            ),
            _lm(),
        )
    )
    unit_now = get_success_data(api_client.get_unit(prog["id"], unit["id"], _lm()))
    lease_s = get_success_data(
        api_client.activate_lease(
            prog["id"],
            unit["id"],
            lease_s["id"],
            {"expected_unit_version": unit_now["version"]},
            _lm(),
        )
    )
    listing = get_success_data(
        api_client.create_resale_listing(
            prog["id"],
            unit["id"],
            create_resale_listing_payload(
                seller_lease_id=lease_s["id"], appraisal_at_listing_cents=35_000_000
            ),
            _lm(),
        )
    )
    # APPRAISAL_BASED with A0 = 25_000_000: appreciation = 10_000_000;
    # seller_share = 2_500_000; asking = 22_500_000;
    # subsidy_retained = 5_000_000 + 7_500_000 = 12_500_000;
    # proceeds = 2_500_000 → 12_500_000 + 2_500_000 + 20_000_000 = 35_000_000.
    p0 = 20_000_000
    a1 = 35_000_000
    lhs = listing["subsidy_retained_cents"] + listing["seller_proceeds_cents"] + p0
    assert lhs == a1, (
        f"Conservation violated: subsidy_retained + proceeds + P0 = {lhs}, expected {a1}"
    )


def test_fee_arrears_late_then_pay_returns_to_zero():
    """PRD §3.3: "The system automatically transitions a `PENDING` fee to
    `LATE` at `due_date` plus 5 days of grace. That transition increments the
    lease's `fee_arrears_cents` by the fee's `amount_cents`..."
    PRD §3.3: "...if the sum of the existing `paid_amount_cents` and the new
    `payment_amount_cents` is at least `amount_cents`, the fee transitions
    to `PAID` with `paid_at` set to now, and the lease's `fee_arrears_cents`
    is decremented by `amount_cents` (capped so it cannot go below 0)."

    Design: Difficulty/compensating_invariant/fee_arrears_compensating_pay_and_waive
    """
    prog = setup_program(name="P-FEE1")
    _, unit, hh, lease = setup_active_lease(prog["id"])

    # First fee was created at activation in PENDING.
    fees = get_success_data(
        api_client.list_fees(prog["id"], unit["id"], lease["id"], _lm())
    )
    assert len(fees) >= 1
    fee = fees[0]
    assert fee["status"] == "PENDING"

    # Push clock past due_date + 5 days grace. Fee was created for period
    # 2026-05; due_date = 2026-05-01T00:00:00Z. Set clock to 2026-06-10
    # to mark it LATE.
    pa = _pa()
    get_success_data(api_client.set_clock("2026-06-10T00:00:00Z", pa))

    fee_after_late = get_success_data(
        api_client.get_fee(prog["id"], unit["id"], lease["id"], fee["id"], _lm())
    )
    assert fee_after_late["status"] == "LATE"

    lease_after_late = get_success_data(
        api_client.get_lease(prog["id"], unit["id"], lease["id"], _lm())
    )
    arrears_mid = lease_after_late["fee_arrears_cents"]
    assert arrears_mid == fee_after_late["amount_cents"], (
        f"After LATE, arrears == fee amount; got {arrears_mid}, "
        f"amount={fee_after_late['amount_cents']}"
    )

    # Compensating action: pay in full.
    hh_headers = make_household_headers(hh["id"])
    paid = get_success_data(
        api_client.pay_fee(
            prog["id"],
            unit["id"],
            lease["id"],
            fee["id"],
            {"payment_amount_cents": fee_after_late["amount_cents"]},
            hh_headers,
        )
    )
    assert paid["status"] == "PAID"

    lease_after_pay = get_success_data(
        api_client.get_lease(prog["id"], unit["id"], lease["id"], _lm())
    )
    assert lease_after_pay["fee_arrears_cents"] == 0, (
        f"After LATE then PAY, fee_arrears_cents must return to 0; got "
        f"{lease_after_pay['fee_arrears_cents']}"
    )


def test_fee_arrears_late_then_waive_returns_to_zero():
    """PRD §3.3: "A `LeaseManager` may waive a fee in `PENDING` or `LATE`
    status, moving it to `WAIVED` and decrementing `fee_arrears_cents` by the
    unpaid balance (the difference between `amount_cents` and
    `paid_amount_cents`, again capped at 0)."

    Design: Difficulty/compensating_invariant/fee_arrears_compensating_pay_and_waive
    """
    prog = setup_program(name="P-FEE2")
    _, unit, _, lease = setup_active_lease(prog["id"])

    fees = get_success_data(
        api_client.list_fees(prog["id"], unit["id"], lease["id"], _lm())
    )
    fee = fees[0]

    pa = _pa()
    get_success_data(api_client.set_clock("2026-06-10T00:00:00Z", pa))
    fee_late = get_success_data(
        api_client.get_fee(prog["id"], unit["id"], lease["id"], fee["id"], _lm())
    )
    assert fee_late["status"] == "LATE"

    get_success_data(
        api_client.waive_fee(prog["id"], unit["id"], lease["id"], fee["id"], _lm())
    )
    lease_after = get_success_data(
        api_client.get_lease(prog["id"], unit["id"], lease["id"], _lm())
    )
    assert lease_after["fee_arrears_cents"] == 0
