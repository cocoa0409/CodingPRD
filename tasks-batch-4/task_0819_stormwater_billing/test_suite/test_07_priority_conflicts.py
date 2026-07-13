"""Deterministic error selection when two rules could reject the same request,
plus the already-terminal void transition."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    create_bmp_credit_payload, create_payment_payload,
    create_active_parcel, setup_issued_bill, grant_exemption,
)

ASSESSOR = TEST_USERS["assessor_headers"]
BILLING_CLERK = TEST_USERS["billing_clerk_headers"]


def _void_bill(api, measured_sqft=6000):
    base = setup_issued_bill(api, measured_sqft=measured_sqft, land_use="RESIDENTIAL_MF")
    validate_success(api.void_bill(base["bill"]["id"], BILLING_CLERK))
    return base


def test_void_bill_state_beats_overpayment_fiscal(api):
    """PRD §2.8: "Only after those pass does the system check that all required
    body fields are present (`ERR_MISSING_FIELD`), that enum and numeric values
    are in range (`ERR_OUT_OF_RANGE`), then state legality, concurrency,
    referential-integrity, uniqueness, temporal, and fiscal rules in the order
    their sections describe."
    PRD §3.6: "A payment may only be applied to a payable bill — one whose status
    is `ISSUED`, `PARTIALLY_PAID`, or `DELINQUENT`; a bill that is `VOID`, `PAID`,
    or `ADJUSTED` is not payable, and a payment against it is rejected with
    `ERR_BILL_NOT_PAYABLE`."

    Design: Difficulty/priority_pair_validation_conflict/void_bill_state_beats_overpayment_fiscal
    """
    base = _void_bill(api)
    resp = api.create_payment(
        create_payment_payload(base["bill"]["id"], base["account"]["id"], 9999),
        BILLING_CLERK)
    validate_error(resp, ApiErrorId.ERR_BILL_NOT_PAYABLE.value)
    # State check pre-empts the fiscal check: no payment is created.
    payments = validate_success(
        api.list_payments(BILLING_CLERK, params={"bill_id": base["bill"]["id"]}))
    assert payments == []


def test_void_bill_state_beats_fiscal_small_amount(api):
    """PRD §3.6: "A payment may only be applied to a payable bill — one whose
    status is `ISSUED`, `PARTIALLY_PAID`, or `DELINQUENT`; a bill that is `VOID`,
    `PAID`, or `ADJUSTED` is not payable, and a payment against it is rejected
    with `ERR_BILL_NOT_PAYABLE`."
    PRD §3.6: "the `amount_cents` may not exceed the bill's current outstanding,
    defined as `net_fee_cents` minus `amount_paid_cents`, and an amount that
    exceeds it is rejected with `ERR_OVERPAYMENT`."

    Design: Difficulty/priority_pair_validation_conflict/void_bill_state_beats_overpayment_fiscal
    """
    # A VOID bill has outstanding 0, so even a 1-cent payment overpays; the state
    # check must still win and return ERR_BILL_NOT_PAYABLE (not ERR_OVERPAYMENT).
    base = _void_bill(api)
    resp = api.create_payment(
        create_payment_payload(base["bill"]["id"], base["account"]["id"], 1),
        BILLING_CLERK)
    validate_error(resp, ApiErrorId.ERR_BILL_NOT_PAYABLE.value)


def test_exempt_parcel_constraint_beats_credit_overlap(api):
    """PRD §2.8: "then state legality, concurrency, referential-integrity,
    uniqueness, temporal, and fiscal rules in the order their sections describe."
    PRD §3.4: "Because a granted exemption already waives the parcel's fee, a
    credit may not be created on a parcel that holds a `GRANTED` exemption; such
    an attempt is rejected with `ERR_PARCEL_EXEMPT`."
    PRD §3.4: "A new credit window may not overlap the window of an existing
    `ACTIVE` credit of the same `bmp_type` on the same parcel; because the window
    is half-open, two windows that merely touch at an endpoint do not conflict,
    but any genuine overlap is rejected with `ERR_CREDIT_WINDOW_OVERLAP`."

    Design: Difficulty/priority_pair_validation_conflict/exempt_parcel_constraint_beats_credit_overlap_temporal
    """
    base = create_active_parcel(api, measured_sqft=18000, land_use="INSTITUTIONAL")
    validate_success(
        api.create_bmp_credit(
            create_bmp_credit_payload(base["parcel"]["id"], bmp_type="RAIN_GARDEN",
                                      self_reported_score=80,
                                      effective_date="2026-01-01T00:00:00Z",
                                      expiry_date="2026-07-01T00:00:00Z"), ASSESSOR),
        expected_status=201)
    grant_exemption(api, base["parcel"]["id"], requested_pct=1.0, granted_pct=1.0,
                    category="GOVERNMENT")
    # New credit both overlaps the existing window AND sits on a GRANTED-exempt
    # parcel; the business-constraint check (exempt) is reported over the
    # temporal (overlap) check.
    resp = api.create_bmp_credit(
        create_bmp_credit_payload(base["parcel"]["id"], bmp_type="RAIN_GARDEN",
                                  self_reported_score=60,
                                  effective_date="2026-06-01T00:00:00Z",
                                  expiry_date="2026-12-01T00:00:00Z"), ASSESSOR)
    validate_error(resp, ApiErrorId.ERR_PARCEL_EXEMPT.value)


def test_exempt_parcel_beats_overlap_contained_window(api):
    """PRD §3.4: "Because a granted exemption already waives the parcel's fee, a
    credit may not be created on a parcel that holds a `GRANTED` exemption; such
    an attempt is rejected with `ERR_PARCEL_EXEMPT`."
    PRD §2.8: "then state legality, concurrency, referential-integrity,
    uniqueness, temporal, and fiscal rules in the order their sections describe."

    Design: Difficulty/priority_pair_validation_conflict/exempt_parcel_constraint_beats_credit_overlap_temporal
    """
    # A fully-contained overlapping window on a GRANTED-exempt parcel still yields
    # ERR_PARCEL_EXEMPT, confirming the constraint check pre-empts the overlap check.
    base = create_active_parcel(api, measured_sqft=18000, land_use="INSTITUTIONAL")
    validate_success(
        api.create_bmp_credit(
            create_bmp_credit_payload(base["parcel"]["id"], bmp_type="GREEN_ROOF",
                                      self_reported_score=80,
                                      effective_date="2026-01-01T00:00:00Z",
                                      expiry_date="2026-07-01T00:00:00Z"), ASSESSOR),
        expected_status=201)
    grant_exemption(api, base["parcel"]["id"], requested_pct=1.0, granted_pct=1.0,
                    category="RELIGIOUS")
    resp = api.create_bmp_credit(
        create_bmp_credit_payload(base["parcel"]["id"], bmp_type="GREEN_ROOF",
                                  self_reported_score=60,
                                  effective_date="2026-03-01T00:00:00Z",
                                  expiry_date="2026-05-01T00:00:00Z"), ASSESSOR)
    validate_error(resp, ApiErrorId.ERR_PARCEL_EXEMPT.value)


def test_void_already_void_bill_returns_invalid_state(api):
    """PRD §3.9: "Voiding is permitted only from `ISSUED`, `PARTIALLY_PAID`, or
    `DELINQUENT`, and only when the bill carries no `APPLIED` payment — any
    payment must be refunded first. A bill that is not in a voidable state, or
    that still has an applied payment, is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/void_already_void_bill_returns_invalid_state
    """
    base = _void_bill(api)
    resp = api.void_bill(base["bill"]["id"], BILLING_CLERK)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
