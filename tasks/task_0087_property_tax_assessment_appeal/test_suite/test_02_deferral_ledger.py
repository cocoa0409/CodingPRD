"""Deferral interest accrual, the payment waterfall, and the satisfy cascade.

Covers difficulty queue instances:
  dual_variant_calc / declining_balance_vs_originated_principal_on_deferral
  transitive_cascade / payment_satisfies_deferral_then_releases_depth2
  resource_temporal_overlap / deferral_payment_exceeds_balance_overlap_on_ledger_quantity
  compensating_invariant / deferral_payment_then_overpay_reject_conserves_balance
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    assert_deferral_balance_identity,
    setup_deferral_with_accrual,
    setup_deferral_after_payment,
    get_deferral,
)
from test_helpers import factories as f

ASSESSOR = TEST_USERS["assessor_headers"]


# ===========================================================================
# dual_variant_calc / declining_balance_vs_originated_principal_on_deferral
# ===========================================================================
def test_second_accrual_uses_declining_principal_base(api):
    """PRD §3.9: "the outstanding principal is `deferred_principal_cents` minus the principal
    that prior payments have already retired; the period's interest is that outstanding
    principal multiplied by the `annual_interest_rate`, rounded half-up to a whole cent".
    PRD §3.9: "Because the base shrinks as principal is repaid, each successive accrual after
    a principal-reducing payment charges less than it otherwise would."

    Design: Difficulty/dual_variant_calc/declining_balance_vs_originated_principal_on_deferral
    """
    # principal 200000 @0.05; period-1 accrual 10000; 60000 payment (10000->int, 50000->prin).
    # principal now reduced by 50000 to 150000. Re-accrue: round(150000*0.05) = 7500.
    owner, roll, parcel, final, bill, deferral = setup_deferral_after_payment(
        principal_market=200000, annual_interest_rate=0.05, first_payment_cents=60000
    )
    assert deferral["accrued_interest_cents"] == 10000
    after = validate_success(api.accrue_interest(deferral["id"], ASSESSOR))
    # declining base: 10000 + 7500 = 17500 (NOT 10000 + 10000 = 20000 originated).
    assert after["accrued_interest_cents"] == 17500, (
        f"second accrual should add 7500 on declining principal 150000, "
        f"total 17500; got {after['accrued_interest_cents']}"
    )


def test_first_accrual_charges_full_principal(api):
    """PRD §3.9: "The sanctioned method is a **declining-balance** accrual: interest is
    charged only on principal not yet repaid, never on principal already paid down."
    PRD §3.9: "the period's interest is that outstanding principal multiplied by the
    `annual_interest_rate`, rounded half-up to a whole cent; this period interest is added to
    `accrued_interest_cents`, and `outstanding_balance_cents` is recomputed."

    Design: Difficulty/dual_variant_calc/declining_balance_vs_originated_principal_on_deferral
    """
    # First accrual on principal 200000 @0.05 with no payments = round(200000*0.05) = 10000.
    owner, roll, parcel, final, bill, deferral = setup_deferral_with_accrual(
        principal_market=200000, annual_interest_rate=0.05
    )
    assert deferral["accrued_interest_cents"] == 10000, \
        f"first accrual on 200000 @0.05 should be 10000, got {deferral['accrued_interest_cents']}"
    assert deferral["outstanding_balance_cents"] == 210000
    assert_deferral_balance_identity(deferral)


# ===========================================================================
# transitive_cascade / payment_satisfies_deferral_then_releases_depth2
# ===========================================================================
def test_full_payment_drives_balance_to_zero_and_satisfies(api):
    """PRD §3.9: "The applied interest and applied principal are then added to
    `total_paid_cents` and `outstanding_balance_cents` is recomputed."
    PRD §3.9: "When an applied payment brings `outstanding_balance_cents` to exactly 0, the
    agreement automatically moves `ACTIVE → SATISFIED` and its lien is released."

    Design: Difficulty/transitive_cascade/payment_satisfies_deferral_then_releases_depth2
    """
    # principal 200000 + accrued 10000 = outstanding 210000; pay exactly 210000.
    owner, roll, parcel, final, bill, deferral = setup_deferral_with_accrual(
        principal_market=200000, annual_interest_rate=0.05
    )
    assert deferral["outstanding_balance_cents"] == 210000
    payment = validate_success(
        api.create_payment(
            deferral["id"], f.create_payment_payload(210000, deferral["version"]), ASSESSOR
        ),
        expected_status=201,
    )
    assert payment["applied_to_interest_cents"] == 10000
    assert payment["applied_to_principal_cents"] == 200000
    after = get_deferral(deferral["id"])
    assert after["outstanding_balance_cents"] == 0, \
        f"balance should reach 0, got {after['outstanding_balance_cents']}"
    assert after["status"] == "SATISFIED", \
        f"agreement should auto-satisfy at zero balance, got {after['status']}"


def test_full_payment_waterfall_splits_interest_then_principal(api):
    """PRD §3.9: "`applied_to_interest_cents` is the smaller of the payment's `amount_cents`
    and that remaining interest. Whatever of the payment is left after interest is
    `applied_to_principal_cents`, capped at the principal not yet retired. The interest bucket
    is always exhausted before any cent touches principal".

    Design: Difficulty/transitive_cascade/payment_satisfies_deferral_then_releases_depth2
    """
    # outstanding 210000 (principal 200000 + interest 10000); pay 210000 in full.
    owner, roll, parcel, final, bill, deferral = setup_deferral_with_accrual(
        principal_market=200000, annual_interest_rate=0.05
    )
    payment = validate_success(
        api.create_payment(
            deferral["id"], f.create_payment_payload(210000, deferral["version"]), ASSESSOR
        ),
        expected_status=201,
    )
    # Interest bucket (10000) fills first, principal (200000) after.
    assert payment["applied_to_interest_cents"] == 10000, \
        f"interest bucket should absorb 10000 first, got {payment['applied_to_interest_cents']}"
    assert payment["applied_to_principal_cents"] == 200000, \
        f"remaining 200000 should hit principal, got {payment['applied_to_principal_cents']}"


# ===========================================================================
# resource_temporal_overlap / deferral_payment_exceeds_balance_overlap_on_ledger_quantity
# ===========================================================================
def test_payment_exceeding_balance_rejected(api):
    """PRD §3.9: "A payment whose `amount_cents` would carry the agreement past a zero
    balance — that is, an overpayment beyond the full outstanding balance — is rejected with
    `ERR_PAYMENT_EXCEEDS_BALANCE` rather than refunded."

    Design: Difficulty/resource_temporal_overlap/deferral_payment_exceeds_balance_overlap_on_ledger_quantity
    """
    owner, roll, parcel, final, bill, deferral = setup_deferral_with_accrual(
        principal_market=200000, annual_interest_rate=0.05
    )  # outstanding 210000
    resp = api.create_payment(
        deferral["id"], f.create_payment_payload(210001, deferral["version"]), ASSESSOR
    )
    validate_error(resp, ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE)


def test_payment_one_cent_over_remaining_balance_rejected(api):
    """PRD §3.9: "A payment whose `amount_cents` would carry the agreement past a zero
    balance — that is, an overpayment beyond the full outstanding balance — is rejected with
    `ERR_PAYMENT_EXCEEDS_BALANCE` rather than refunded."

    Design: Difficulty/resource_temporal_overlap/deferral_payment_exceeds_balance_overlap_on_ledger_quantity
    """
    # After a 60000 payment outstanding is 150000; 150001 is one cent over and rejected.
    owner, roll, parcel, final, bill, deferral = setup_deferral_after_payment(
        principal_market=200000, annual_interest_rate=0.05, first_payment_cents=60000
    )
    assert deferral["outstanding_balance_cents"] == 150000
    resp = api.create_payment(
        deferral["id"], f.create_payment_payload(150001, deferral["version"]), ASSESSOR
    )
    validate_error(resp, ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE)


# ===========================================================================
# compensating_invariant / deferral_payment_then_overpay_reject_conserves_balance
# ===========================================================================
def test_rejected_overpayment_conserves_ledger_after_valid_payment(api):
    """PRD §3.9: "`outstanding_balance_cents`, which always equals `deferred_principal_cents`
    plus `accrued_interest_cents` minus `total_paid_cents`."
    PRD §3.9: "A payment whose `amount_cents` would carry the agreement past a zero balance —
    that is, an overpayment beyond the full outstanding balance — is rejected with
    `ERR_PAYMENT_EXCEEDS_BALANCE` rather than refunded."

    Design: Difficulty/compensating_invariant/deferral_payment_then_overpay_reject_conserves_balance
    """
    # After a valid 60000 payment, outstanding 150000, total_paid 60000.
    owner, roll, parcel, final, bill, deferral = setup_deferral_after_payment(
        principal_market=200000, annual_interest_rate=0.05, first_payment_cents=60000
    )
    assert deferral["outstanding_balance_cents"] == 150000
    assert deferral["total_paid_cents"] == 60000
    # Overpay 210000 against the 150000 remaining balance -> rejected.
    resp = api.create_payment(
        deferral["id"], f.create_payment_payload(210000, deferral["version"]), ASSESSOR
    )
    validate_error(resp, ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE)
    after = get_deferral(deferral["id"])
    assert after["outstanding_balance_cents"] == 150000, \
        f"rejected overpayment must not change balance, got {after['outstanding_balance_cents']}"
    assert after["total_paid_cents"] == 60000, \
        f"rejected overpayment must not change total_paid, got {after['total_paid_cents']}"
    assert_deferral_balance_identity(after)


def test_valid_payment_then_rejected_overpay_leaves_status_active(api):
    """PRD §3.9: "When an applied payment brings `outstanding_balance_cents` to exactly 0, the
    agreement automatically moves `ACTIVE → SATISFIED` and its lien is released."
    PRD §3.9: "A payment whose `amount_cents` would carry the agreement past a zero balance —
    that is, an overpayment beyond the full outstanding balance — is rejected with
    `ERR_PAYMENT_EXCEEDS_BALANCE` rather than refunded."

    Design: Difficulty/compensating_invariant/deferral_payment_then_overpay_reject_conserves_balance
    """
    # A valid 60000 payment leaves outstanding 150000 > 0, so the agreement stays ACTIVE;
    # a rejected overpayment must not flip it to SATISFIED.
    owner, roll, parcel, final, bill, deferral = setup_deferral_after_payment(
        principal_market=200000, annual_interest_rate=0.05, first_payment_cents=60000
    )
    assert deferral["status"] == "ACTIVE"
    resp = api.create_payment(
        deferral["id"], f.create_payment_payload(210000, deferral["version"]), ASSESSOR
    )
    validate_error(resp, ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE)
    after = get_deferral(deferral["id"])
    assert after["status"] == "ACTIVE", \
        f"a rejected overpayment must leave the agreement ACTIVE, got {after['status']}"
