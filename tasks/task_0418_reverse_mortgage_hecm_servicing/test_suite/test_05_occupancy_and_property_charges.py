"""Cyclic occupancy certification, certification annual-window overlap, the
half-open coverage-window overlap, and the LESA pool guards / conservation.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    assert_lesa_pool_conserved,
    make_borrower_headers,
    setup_loan_with_delinquent_cert,
    setup_loan_with_pending_cert,
    setup_originated_loan_with_lesa,
    setup_exhausted_lesa,
    pay_property_charge,
)

_SO = TEST_USERS["servicer_ops_headers"]


# ---------------------------------------------------------------------------
# non_linear_state_machine / occupancy_cert_cyclic_pending_delinquent_certified
# ---------------------------------------------------------------------------
def test_occupancy_cert_cyclic_delinquent_then_certified(api):
    """PRD §3.7: "The loan's `Borrower` — or a `ServicerOps` operator acting on the
    borrower's behalf — certifies a certification, which is defined from both
    `PENDING` and `DELINQUENT`, moving it to `CERTIFIED`"

    Design: Difficulty/non_linear_state_machine/occupancy_cert_cyclic_pending_delinquent_certified
    """
    lender, borrower, loan, cert = setup_loan_with_delinquent_cert()
    assert cert["status"] == "DELINQUENT"
    out = validate_success(api.certify_occupancy(cert["id"], make_borrower_headers(borrower["id"])))
    assert out["status"] == "CERTIFIED"
    assert out["certified_at"] is not None


def test_certify_from_delinquent_bubbles_servicing_back_to_current(api):
    """PRD §3.7: "It then performs a bubble-up cascade: if the loan's `servicing_status` is
    `DELINQUENT_OCCUPANCY` and no other certification on that loan remains
    `DELINQUENT`, the loan's `servicing_status` returns to `CURRENT`."

    Design: Difficulty/non_linear_state_machine/occupancy_cert_cyclic_pending_delinquent_certified
    """
    lender, borrower, loan, cert = setup_loan_with_delinquent_cert()
    assert loan["servicing_status"] == "DELINQUENT_OCCUPANCY"
    validate_success(api.certify_occupancy(cert["id"], make_borrower_headers(borrower["id"])))
    loan_after = validate_success(api.get_loan(loan["id"], _SO))
    assert loan_after["servicing_status"] == "CURRENT"


# ---------------------------------------------------------------------------
# resource_temporal_overlap / occupancy_cert_annual_bucket_overlap_rejected
# ---------------------------------------------------------------------------
def test_occupancy_cert_same_year_overlap_rejected(api):
    """PRD §3.7: "At most one certification may exist per loan per certification year, and a new
    year's annual window may not overlap an existing certification's window;
    an attempt to open an overlapping certification is rejected with
    `ERR_CERT_PERIOD_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/occupancy_cert_annual_bucket_overlap_rejected
    """
    lender, borrower, loan, cert = setup_loan_with_pending_cert(certification_year=1)
    validate_error(
        api.create_occupancy_certification({"loan_id": loan["id"], "certification_year": 1}, _SO),
        ApiErrorId.ERR_CERT_PERIOD_OVERLAP.value)


def test_occupancy_cert_different_year_allowed(api):
    """PRD §3.7: "At most one certification may exist per loan per certification year, and a new
    year's annual window may not overlap an existing certification's window;
    an attempt to open an overlapping certification is rejected with
    `ERR_CERT_PERIOD_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/occupancy_cert_annual_bucket_overlap_rejected
    """
    # A second cert for a DIFFERENT certification_year does not overlap year 1's
    # annual window and is accepted.
    lender, borrower, loan, cert = setup_loan_with_pending_cert(certification_year=1)
    out = validate_success(api.create_occupancy_certification(
        {"loan_id": loan["id"], "certification_year": 2}, _SO), expected_status=201)
    assert out["certification_year"] == 2
    assert out["status"] == "PENDING"


# ---------------------------------------------------------------------------
# resource_temporal_overlap /
#   property_charge_halfopen_window_overlap_rejected_adjacent_allowed
# ---------------------------------------------------------------------------
def test_property_charge_overlapping_window_rejected(api):
    """PRD §3.8: "The coverage window must not overlap an existing `POSTED` payment of the same
    `charge_type` on the same loan; because the window is half-open, two
    payments are adjacent and allowed when one window's `coverage_end` equals
    the next window's `coverage_start`, and only a genuine overlap is
    rejected, with `ERR_COVERAGE_WINDOW_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/property_charge_halfopen_window_overlap_rejected_adjacent_allowed
    """
    lender, borrower, loan, lesa = setup_originated_loan_with_lesa()
    pay_property_charge(loan["id"], lesa["id"], amount_cents=100000,
                        charge_type="PROPERTY_TAX",
                        coverage_start="2024-01-01", coverage_end="2024-07-01")
    validate_error(
        api.create_property_charge_payment(
            {"loan_id": loan["id"], "lesa_set_aside_id": lesa["id"],
             "charge_type": "PROPERTY_TAX", "coverage_start": "2024-06-01",
             "coverage_end": "2025-01-01", "amount_cents": 100000}, _SO),
        ApiErrorId.ERR_COVERAGE_WINDOW_OVERLAP.value)


def test_property_charge_adjacent_window_allowed(api):
    """PRD §3.8: "because the window is half-open, two payments are adjacent and allowed when
    one window's `coverage_end` equals the next window's `coverage_start`, and
    only a genuine overlap is rejected, with `ERR_COVERAGE_WINDOW_OVERLAP`
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/property_charge_halfopen_window_overlap_rejected_adjacent_allowed
    """
    lender, borrower, loan, lesa = setup_originated_loan_with_lesa()
    pay_property_charge(loan["id"], lesa["id"], amount_cents=100000,
                        charge_type="PROPERTY_TAX",
                        coverage_start="2024-01-01", coverage_end="2024-07-01")
    out = validate_success(api.create_property_charge_payment(
        {"loan_id": loan["id"], "lesa_set_aside_id": lesa["id"],
         "charge_type": "PROPERTY_TAX", "coverage_start": "2024-07-01",
         "coverage_end": "2025-01-01", "amount_cents": 100000}, _SO),
        expected_status=201)
    assert out["status"] == "POSTED"


# ---------------------------------------------------------------------------
# cross_entity_state_dependency / property_charge_payment_requires_lesa_funded
# ---------------------------------------------------------------------------
def test_property_charge_on_exhausted_lesa_rejected(api):
    """PRD §3.8: "The referenced set-aside must be `FUNDED` rather than `EXHAUSTED`, and it must
    belong to the same loan as the payment; a payment against an exhausted
    pool or against a pool belonging to a different loan is rejected with
    `ERR_LESA_EXHAUSTED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/property_charge_payment_requires_lesa_funded
    """
    lender, borrower, loan, lesa = setup_exhausted_lesa()
    assert lesa["status"] == "EXHAUSTED"
    assert lesa["remaining_cents"] == 0
    validate_error(
        api.create_property_charge_payment(
            {"loan_id": loan["id"], "lesa_set_aside_id": lesa["id"],
             "charge_type": "HAZARD_INSURANCE", "coverage_start": "2025-01-01",
             "coverage_end": "2026-01-01", "amount_cents": 100000}, _SO),
        ApiErrorId.ERR_LESA_EXHAUSTED.value)


def test_property_charge_on_funded_pool_posts_and_draws_down(api):
    """PRD §3.8: "The referenced set-aside must be `FUNDED` rather than `EXHAUSTED`, and it must
    belong to the same loan as the payment; a payment against an exhausted
    pool or against a pool belonging to a different loan is rejected with
    `ERR_LESA_EXHAUSTED` (HTTP 409)."
    PRD §3.8: "The set-aside's `drawn_cents` increases by the `amount_cents`, its
    `remaining_cents` decreases by the same `amount_cents".

    Design: Difficulty/cross_entity_state_dependency/property_charge_payment_requires_lesa_funded
    """
    # A FUNDED pool on the same loan accepts the payment (the FUNDED gate passes).
    lender, borrower, loan, lesa = setup_originated_loan_with_lesa()
    assert lesa["status"] == "FUNDED"
    pay = pay_property_charge(loan["id"], lesa["id"], amount_cents=100000)
    assert pay["status"] == "POSTED"
    lesa_after = validate_success(api.get_lesa(lesa["id"], _SO))
    assert lesa_after["status"] == "FUNDED"
    assert lesa_after["drawn_cents"] == 100000
    assert lesa_after["remaining_cents"] == 5900000


# ---------------------------------------------------------------------------
# validations / property_charge_over_lesa_remaining_returns_lesa_overdraw
# ---------------------------------------------------------------------------
def test_property_charge_one_cent_over_remaining_rejected(api):
    """PRD §3.8: "And the `amount_cents` may not exceed the set-aside's `remaining_cents`, since
    the pool cannot be overdrawn; an amount greater than the residual is
    rejected with `ERR_LESA_OVERDRAW` (HTTP 422)."

    Design: Corner/validations/property_charge_over_lesa_remaining_returns_lesa_overdraw
    """
    # PARTIALLY_FUNDED 120000*10/2 = 600000 remaining.
    lender, borrower, loan, lesa = setup_originated_loan_with_lesa(
        funding_mode="PARTIALLY_FUNDED", annual_property_charge_cents=120000,
        life_expectancy_years=10)
    assert lesa["remaining_cents"] == 600000
    validate_error(
        api.create_property_charge_payment(
            {"loan_id": loan["id"], "lesa_set_aside_id": lesa["id"],
             "charge_type": "PROPERTY_TAX", "coverage_start": "2024-01-01",
             "coverage_end": "2025-01-01", "amount_cents": 600001}, _SO),
        ApiErrorId.ERR_LESA_OVERDRAW.value)


# ---------------------------------------------------------------------------
# compensating_invariant / property_charge_reverse_restores_lesa_pool
# ---------------------------------------------------------------------------
def test_property_charge_reverse_restores_pool(api):
    """PRD §3.8: "Reversal is a compensating restoration of the pool: the set-aside's
    `drawn_cents` decreases by the `amount_cents`, its `remaining_cents`
    increases by the same `amount_cents`, and its `status` returns to
    `FUNDED`."

    Design: Difficulty/compensating_invariant/property_charge_reverse_restores_lesa_pool
    """
    lender, borrower, loan, lesa = setup_originated_loan_with_lesa()
    pay = pay_property_charge(loan["id"], lesa["id"], amount_cents=200000)
    before = validate_success(api.get_lesa(lesa["id"], _SO))
    assert before["drawn_cents"] == 200000
    assert before["remaining_cents"] == 5800000
    assert_lesa_pool_conserved(before)

    out = validate_success(api.reverse_property_charge_payment(pay["id"], _SO))
    assert out["status"] == "REVERSED"
    after = validate_success(api.get_lesa(lesa["id"], _SO))
    assert after["drawn_cents"] == 0
    assert after["remaining_cents"] == 6000000
    assert after["status"] == "FUNDED"
    assert_lesa_pool_conserved(after)


def test_property_charge_reverse_zero_drift(api):
    """PRD §3.8: "Reversal is a compensating restoration of the pool: the set-aside's
    `drawn_cents` decreases by the `amount_cents`, its `remaining_cents`
    increases by the same `amount_cents`, and its `status` returns to
    `FUNDED`."

    Design: Difficulty/compensating_invariant/property_charge_reverse_restores_lesa_pool
    """
    lender, borrower, loan, lesa = setup_originated_loan_with_lesa()
    pay = pay_property_charge(loan["id"], lesa["id"], amount_cents=200000)
    validate_success(api.reverse_property_charge_payment(pay["id"], _SO))
    after = validate_success(api.get_lesa(lesa["id"], _SO))
    assert after["drawn_cents"] + after["remaining_cents"] == after["initial_amount_cents"] == 6000000
