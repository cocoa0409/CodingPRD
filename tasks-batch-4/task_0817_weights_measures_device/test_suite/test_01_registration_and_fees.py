"""Device registration, the prorated registration fee, and establishment creation.

Covers difficulty instances fee_full_year_vs_prorated_registration and
fee_quarter_boundary_april_first, plus corner entity/calculation/fee instances.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    assert_establishment, assert_fee_invoice,
    create_establishment, register_device, set_clock,
    first_fee_invoice_for_device, get_establishment,
    api_client,
)

ADMIN = TEST_USERS["program_admin_headers"]


# --------------------------------------------------------------------------- #
# Difficulty/dual_variant_calc/fee_full_year_vs_prorated_registration
# --------------------------------------------------------------------------- #
def test_scale_q3_registration_fee_prorated_to_6000():
    """PRD §3.2: "The quarter factor is 1.00 when the registration month is January,
    February, or March; 0.75 when it is April, May, or June; 0.50 when it is July,
    August, or September; and 0.25 when it is October, November, or December."
    PRD §3.2: "The amount due is the base fee multiplied by this quarter factor,
    rounded half up to a whole number of cents."

    Design: Difficulty/dual_variant_calc/fee_full_year_vs_prorated_registration
    """
    est = create_establishment(name="Q3 Store", jurisdiction="CA-01")
    set_clock("2026-07-01T00:00:00Z")  # July -> Q3 -> factor 0.50
    dev = register_device(est["id"], device_type="SCALE", serial_number="SN-Q3")
    invoice = first_fee_invoice_for_device(dev["id"])
    assert invoice["amount_due_cents"] == 6000, (
        f"SCALE base 12000 * 0.50 must be 6000, got {invoice['amount_due_cents']}")


def test_scale_q3_registration_marks_proration_applied():
    """PRD §3.2: "The boolean `proration_applied` is set to true whenever the applied
    quarter factor is less than 1.00 — that is, for any registration outside the first
    quarter — and false otherwise."

    Design: Difficulty/dual_variant_calc/fee_full_year_vs_prorated_registration
    """
    est = create_establishment(name="Q3 Store", jurisdiction="CA-01")
    set_clock("2026-07-01T00:00:00Z")
    dev = register_device(est["id"], device_type="SCALE", serial_number="SN-Q3")
    invoice = first_fee_invoice_for_device(dev["id"])
    assert invoice["proration_applied"] is True, "Q3 factor 0.50 < 1.00 -> proration_applied true"


# --------------------------------------------------------------------------- #
# Difficulty/boundary_precision_check/fee_quarter_boundary_april_first
# --------------------------------------------------------------------------- #
def test_april_first_registration_fee_is_9000():
    """PRD §3.2: "The quarter factor is 1.00 when the registration month is January,
    February, or March; 0.75 when it is April, May, or June; 0.50 when it is July,
    August, or September; and 0.25 when it is October, November, or December."

    Design: Difficulty/boundary_precision_check/fee_quarter_boundary_april_first
    """
    est = create_establishment(name="Apr Store", jurisdiction="CA-12")
    set_clock("2026-04-01T00:00:00Z")  # first instant of Q2 -> factor 0.75
    dev = register_device(est["id"], device_type="SCALE", serial_number="SN-APR")
    invoice = first_fee_invoice_for_device(dev["id"])
    assert invoice["amount_due_cents"] == 9000, (
        f"SCALE base 12000 * 0.75 must be 9000, got {invoice['amount_due_cents']}")


def test_april_first_registration_marks_proration_applied():
    """PRD §3.2: "The boolean `proration_applied` is set to true whenever the applied
    quarter factor is less than 1.00 — that is, for any registration outside the first
    quarter — and false otherwise."

    Design: Difficulty/boundary_precision_check/fee_quarter_boundary_april_first
    """
    est = create_establishment(name="Apr Store", jurisdiction="CA-12")
    set_clock("2026-04-01T00:00:00Z")
    dev = register_device(est["id"], device_type="SCALE", serial_number="SN-APR")
    invoice = first_fee_invoice_for_device(dev["id"])
    assert invoice["proration_applied"] is True


# --------------------------------------------------------------------------- #
# Corner/entities/establishment_create_returns_201_with_fields
# --------------------------------------------------------------------------- #
def test_establishment_create_returns_active_with_zeroed_ledger():
    """PRD §3.1: "A newly registered establishment begins in `status` `ACTIVE`, with
    `balance_due_cents` of 0 and `sealed_device_count` of 0."

    Design: Corner/entities/establishment_create_returns_201_with_fields
    """
    resp = api_client.create_establishment({"name": "New Store", "jurisdiction": "CA-20"}, ADMIN)
    data = validate_success(resp, 201)
    assert_establishment(data)
    assert data["status"] == "ACTIVE"
    assert data["balance_due_cents"] == 0
    assert data["sealed_device_count"] == 0


# --------------------------------------------------------------------------- #
# Corner/entities/device_create_missing_required_returns_validation
# --------------------------------------------------------------------------- #
def test_device_missing_device_type_returns_validation():
    """PRD §2.7: "A malformed body yields `ERR_VALIDATION` (400); a non-strictly-ordered
    inspection window yields `ERR_SCHEDULE_WINDOW_INVALID` (400)."

    Design: Corner/entities/device_create_missing_required_returns_validation
    """
    est = create_establishment(name="Val Store", jurisdiction="CA-21")
    resp = api_client.create_device(
        {"establishment_id": est["id"], "serial_number": "SN-NO-TYPE"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


# --------------------------------------------------------------------------- #
# Corner/entities/device_get_nonexistent_returns_not_found
# --------------------------------------------------------------------------- #
def test_get_unknown_device_returns_device_not_found():
    """PRD §2.7: "every path identifier and every foreign key in the body resolves to a
    real resource, validated left to right, else the corresponding 404
    (`ERR_ESTABLISHMENT_NOT_FOUND`, `ERR_INSPECTOR_NOT_FOUND`, `ERR_DEVICE_NOT_FOUND`,
    ...)."

    Design: Corner/entities/device_get_nonexistent_returns_not_found
    """
    resp = api_client.get_device("00000000-0000-0000-0000-000000000000", ADMIN)
    validate_error(resp, ApiErrorId.ERR_DEVICE_NOT_FOUND.value)


# --------------------------------------------------------------------------- #
# Corner/entities/device_default_class_applied
# --------------------------------------------------------------------------- #
def test_device_defaults_to_class_iii_when_omitted():
    """PRD §3.2: "The `device_class` is the accuracy class that later selects the
    tolerance tier and is one of `CLASS_III` or `CLASS_IIIL`; when omitted it defaults
    to `CLASS_III`."

    Design: Corner/entities/device_default_class_applied
    """
    est = create_establishment(name="Def Store", jurisdiction="CA-22")
    dev = register_device(est["id"], device_type="SCALE", serial_number="SN-DEF")
    assert dev["device_class"] == "CLASS_III"


# --------------------------------------------------------------------------- #
# Corner/entities/scanner_registration_fee_full_q1
# --------------------------------------------------------------------------- #
def test_scanner_q1_registration_fee_full_15000():
    """PRD §3.2: "Its `base_amount_cents` is the full annual base fee for the device's
    type before any proration: 12000 cents for a `SCALE`, 8000 cents for a `FUEL_PUMP`,
    and 15000 cents for a `SCANNER`."
    PRD §3.2: "The boolean `proration_applied` is set to true whenever the applied
    quarter factor is less than 1.00 — that is, for any registration outside the first
    quarter — and false otherwise."

    Design: Corner/entities/scanner_registration_fee_full_q1
    """
    # Default clock is 2026-03-01 (Q1, factor 1.00).
    est = create_establishment(name="Scan Fee Store", jurisdiction="CA-23")
    dev = register_device(est["id"], device_type="SCANNER", serial_number="SN-SCFEE")
    invoice = first_fee_invoice_for_device(dev["id"])
    assert_fee_invoice(invoice)
    assert invoice["amount_due_cents"] == 15000
    assert invoice["proration_applied"] is False


# --------------------------------------------------------------------------- #
# Corner/calculations/fuel_pump_registration_fee_full_q1
# --------------------------------------------------------------------------- #
def test_fuel_pump_q1_registration_fee_full_8000():
    """PRD §3.2: "Its `base_amount_cents` is the full annual base fee for the device's
    type before any proration: 12000 cents for a `SCALE`, 8000 cents for a `FUEL_PUMP`,
    and 15000 cents for a `SCANNER`."

    Design: Corner/calculations/fuel_pump_registration_fee_full_q1
    """
    est = create_establishment(name="Pump Store", jurisdiction="CA-33")
    dev = register_device(est["id"], device_type="FUEL_PUMP", serial_number="SN-PUMP")
    invoice = first_fee_invoice_for_device(dev["id"])
    assert invoice["amount_due_cents"] == 8000


# --------------------------------------------------------------------------- #
# Corner/entities/devices_list_pagination_by_establishment
# --------------------------------------------------------------------------- #
def test_devices_list_by_establishment_paginated():
    """PRD §2.3: "Every list response includes the following fields inside the
    envelope's `meta` object: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/devices_list_pagination_by_establishment
    """
    est = create_establishment(name="List Store", jurisdiction="CA-24")
    register_device(est["id"], device_type="SCALE", serial_number="SN-L1")
    register_device(est["id"], device_type="FUEL_PUMP", serial_number="SN-L2")
    resp = api_client.list_devices(ADMIN, {"establishment_id": est["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert len(data) == 2


# --------------------------------------------------------------------------- #
# Corner/entities/device_invalid_type_enum_returns_validation
# --------------------------------------------------------------------------- #
def test_device_illegal_type_enum_returns_validation():
    """PRD §3.2: "The `device_type` is one of `SCALE`, `FUEL_PUMP`, or `SCANNER`."
    PRD §2.7: "A malformed body yields `ERR_VALIDATION` (400); a non-strictly-ordered
    inspection window yields `ERR_SCHEDULE_WINDOW_INVALID` (400)."

    Design: Corner/entities/device_invalid_type_enum_returns_validation
    """
    est = create_establishment(name="Enum Store", jurisdiction="CA-25")
    resp = api_client.create_device(
        {"establishment_id": est["id"], "device_type": "THERMOMETER", "serial_number": "SN-BAD"},
        ADMIN)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


# --------------------------------------------------------------------------- #
# Corner/state_machines/pay_fee_reduces_balance_side_effect
# --------------------------------------------------------------------------- #
def test_pay_fee_invoice_moves_to_paid_and_zeroes_balance():
    """PRD §3.9: "Payment moves the invoice from `DUE` to `PAID` and recomputes the
    establishment's `balance_due_cents`, removing that invoice's `amount_due_cents` from
    the total."

    Design: Corner/state_machines/pay_fee_reduces_balance_side_effect
    """
    est = create_establishment(name="Fee Store", jurisdiction="CA-31")
    dev = register_device(est["id"], device_type="SCALE", serial_number="SN-FEE")
    invoice = first_fee_invoice_for_device(dev["id"])
    assert get_establishment(est["id"])["balance_due_cents"] == 12000
    resp = api_client.pay_fee_invoice(invoice["id"], ADMIN)
    paid = validate_success(resp, 200)
    assert paid["status"] == "PAID"
    assert get_establishment(est["id"])["balance_due_cents"] == 0
