"""Financing schedules, credit limits, conversion, and default cascade (PRD §3.5)."""
import pytest
from test_helpers import (
    validate_success, validate_error,
    create_customer, create_available_instrument, create_order, order_line,
    get_order, get_instrument, get_customer,
    create_delivery_crew, create_delivery_job,
    create_financing, approve_financing, create_active_financing,
    post_financing_payment, get_financing,
    set_clock, TEST_USERS,
)

ASSOCIATE = TEST_USERS["sales_associate_headers"]
FINANCE = TEST_USERS["finance_officer_headers"]
COORDINATOR = TEST_USERS["service_coordinator_headers"]


def _order_615(api, customer, serial):
    instrument = create_available_instrument(
        serial_number=serial, category="UPRIGHT", manufacturer="Yamaha", model="U3",
        year_built=2024, condition_grade="EXCELLENT", list_price_cents=600_000,
        floor_price_cents=500_000)
    order = create_order(customer["id"], [order_line(instrument["id"], 600_000)])
    assert order["total_cents"] == 615_000
    return instrument, order


def test_standard_vs_rent_to_own_monthly_amount(api):
    """PRD §3.5: "Under `STANDARD`, the monthly rate is one twelfth of the `apr`, and the
    `monthly_amount_cents` is the principal multiplied by that monthly rate, divided by one
    minus the quantity one plus the monthly rate raised to the negative power of
    `term_months`, rounded half-up to whole cents — the classic annuity. Under
    `RENT_TO_OWN`, the monthly rent is a flat 1.2 percent of the principal, rounded half-up,
    and the agreement accrues a purchase credit: `purchase_credit_cents` is sixty percent of
    the monthly rent multiplied by the number of payments made, counting at most twenty-four
    payments, rounded half-up"
    PRD §3.5: "A `FinanceOfficer` applies for a financing agreement against an order whose
    `payment_status` is still `UNPAID`, supplying the `order_id`, a `program` of `STANDARD`
    or `RENT_TO_OWN`, a `principal_cents` that must equal the order's `total_cents` (a
    mismatch is rejected with `ERR_INVALID_REQUEST`), a `term_months` count, and — for
    `STANDARD` only — an `apr` as a fraction (the rate is ignored for `RENT_TO_OWN`). The
    agreement starts in `APPLIED`."
    (Principal 615000, 12 months: STANDARD at apr 0.12 -> 54642; RENT_TO_OWN -> 7380.)

    Design: Corner/calculations/financing_standard_vs_rent_to_own_monthly
    """
    customer = create_customer(full_name="Fiona Finance", email="fiona@x.com",
                               credit_limit_cents=2_000_000)
    _, o1 = _order_615(api, customer, "SN-FN-1")
    _, o2 = _order_615(api, customer, "SN-FN-2")

    standard = create_financing(o1["id"], "STANDARD", 615_000, 12, apr=0.12)
    rto = create_financing(o2["id"], "RENT_TO_OWN", 615_000, 12)
    assert standard["monthly_amount_cents"] == 54_642, (
        f"STANDARD annuity, got {standard['monthly_amount_cents']}")
    assert rto["monthly_amount_cents"] == 7_380, (
        f"RENT_TO_OWN flat 1.2%, got {rto['monthly_amount_cents']}")
    assert standard["status"] == "APPLIED"
    assert rto["status"] == "APPLIED"


def test_rent_to_own_purchase_credit_and_conversion(api):
    """PRD §3.5: "Under `RENT_TO_OWN`, the monthly rent is a flat 1.2 percent of the
    principal, rounded half-up, and the agreement accrues a purchase credit:
    `purchase_credit_cents` is sixty percent of the monthly rent multiplied by the number of
    payments made, counting at most twenty-four payments, rounded half-up"
    PRD §3.5: "On conversion the `purchase_credit_cents` is computed as above, the agreement
    moves to `CONVERTED_TO_PURCHASE`, and the order's `payment_status` advances from
    `FINANCED_ACTIVE` to `PAID_IN_FULL`."
    (After 3 payments of 7380: round(0.60 * 7380 * 3) == 13284.)

    Design: Corner/calculations/rent_to_own_purchase_credit_and_conversion
    """
    customer = create_customer(full_name="Rhea Rento", email="rhea@x.com",
                               credit_limit_cents=1_000_000)
    _, order = _order_615(api, customer, "SN-RTO-1")
    agreement = create_active_financing(order, "RENT_TO_OWN", 36)
    for _ in range(3):
        post_financing_payment(agreement["id"], 7_380)

    converted = validate_success(api.convert_to_purchase(agreement["id"], FINANCE), 200)
    assert converted["purchase_credit_cents"] == 13_284, (
        f"got {converted['purchase_credit_cents']}")
    assert converted["status"] == "CONVERTED_TO_PURCHASE"
    assert get_order(order["id"])["payment_status"] == "PAID_IN_FULL"


def test_financing_approve_above_credit_limit_rejected(api):
    """PRD §3.5: "Approval requires the agreement to be `APPLIED` and the principal to be no
    more than the customer's `credit_limit_cents`; a principal above that limit is rejected
    with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 422)."
    (Principal 615000 against credit_limit 500000.)

    Design: Corner/validations/financing_approve_above_credit_limit_rejected
    """
    customer = create_customer(full_name="Cole Credit", email="cole@x.com",
                               credit_limit_cents=500_000)
    _, order = _order_615(api, customer, "SN-CR-1")
    agreement = create_financing(order["id"], "RENT_TO_OWN", 615_000, 36)

    res = api.approve_financing_agreement(agreement["id"], FINANCE)
    validate_error(res, "ERR_CREDIT_LIMIT_EXCEEDED")
    after = get_financing(agreement["id"])
    assert after["status"] == "APPLIED", "rejected approval must not activate"
    assert get_order(order["id"])["payment_status"] == "UNPAID"


def test_convert_standard_agreement_rejected(api):
    """PRD §3.5: "A `RENT_TO_OWN` agreement in `ACTIVE` may instead be converted to purchase
    by a `FinanceOfficer`. Conversion against an agreement that is not `ACTIVE`, or not
    `RENT_TO_OWN`, is rejected with `ERR_AGREEMENT_NOT_CONVERTIBLE`."

    Design: Corner/validations/convert_standard_agreement_rejected
    """
    customer = create_customer(full_name="Stan Standard", email="stan@x.com",
                               credit_limit_cents=2_000_000)
    _, order = _order_615(api, customer, "SN-ST-1")
    agreement = create_active_financing(order, "STANDARD", 12, apr=0.12)

    res = api.convert_to_purchase(agreement["id"], FINANCE)
    validate_error(res, "ERR_AGREEMENT_NOT_CONVERTIBLE")
    assert get_financing(agreement["id"])["status"] == "ACTIVE"


def _defaulted_scenario(api):
    """ACTIVE RENT_TO_OWN agreement, delivered order, clock advanced 4 whole months."""
    customer = create_customer(full_name="Doug Default", email="doug@x.com",
                               credit_limit_cents=1_000_000)
    instrument, order = _order_615(api, customer, "SN-D-1")
    agreement = create_active_financing(order, "RENT_TO_OWN", 36)
    crew = create_delivery_crew(crew_name="Crew Gamma", climate_certified=False)
    job = create_delivery_job(order["id"], crew["id"],
                              "2026-05-02T09:00:00Z", "2026-05-02T12:00:00Z")
    validate_success(api.start_delivery_job(job["id"], COORDINATOR), 200)
    validate_success(api.complete_delivery_job(job["id"], COORDINATOR), 200)
    set_clock("2026-09-01T00:00:00Z")  # 4 whole months after activation at 2026-05-01
    return customer, instrument, order, agreement


def test_financing_default_moves_agreement_and_order(api):
    """PRD §3.5: "`missed_payments` is the number of whole calendar months elapsed between
    `activated_at` and the current logical clock — a month counting only once its
    day-of-month has been reached — minus `payments_made`, floored at zero, and it is
    recomputed on every read and write of the agreement."
    PRD §3.5: "When an `ACTIVE` agreement shows at least three missed payments, a
    `FinanceOfficer` may declare default; fewer than three is rejected with
    `ERR_INVALID_REQUEST`. Default moves the agreement to `DEFAULTED`, flips the order from
    `FINANCED_ACTIVE` to `COLLECTIONS`, moves each delivered line instrument from
    `DELIVERED` to `REPOSSESSION_HOLD`"
    (Activated 2026-05-01, clock 2026-09-01, zero payments -> 4 missed.)

    Design: Difficulty/transitive_cascade/financing_default_repossession_cascade_depth2
    """
    _, _, order, agreement = _defaulted_scenario(api)
    defaulted = validate_success(api.declare_default(agreement["id"], FINANCE), 200)
    assert defaulted["status"] == "DEFAULTED"
    assert defaulted["missed_payments"] == 4, (
        f"4 whole months elapsed, 0 payments, got {defaulted['missed_payments']}")
    assert get_order(order["id"])["payment_status"] == "COLLECTIONS", "cascade link 1"


def test_financing_default_repossesses_instrument_and_docks_score(api):
    """PRD §3.5: "Default moves the agreement to `DEFAULTED`, flips the order from
    `FINANCED_ACTIVE` to `COLLECTIONS`, moves each delivered line instrument from
    `DELIVERED` to `REPOSSESSION_HOLD` (a `StoreManager` later releases such an instrument
    back to `AVAILABLE` via the release-hold action, which requires the instrument to be in
    `REPOSSESSION_HOLD`), and subtracts 150 from the customer's `risk_score`, subject to the
    300 floor."
    PRD §2.9: "`risk_score` begins at 700, loses 25 points per warranty voided by a return
    and 150 points per financing default, and is clamped to the band from 300 to 850."

    Design: Difficulty/transitive_cascade/financing_default_repossession_cascade_depth2
    """
    customer, instrument, _, agreement = _defaulted_scenario(api)
    validate_success(api.declare_default(agreement["id"], FINANCE), 200)
    assert get_instrument(instrument["id"])["status"] == "REPOSSESSION_HOLD", "cascade link 2"
    assert get_customer(customer["id"])["risk_score"] == 550, "700 - 150"
