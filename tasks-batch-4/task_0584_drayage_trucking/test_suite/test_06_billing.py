"""Invoice generation (discount / fuel / floor), accessorial add-and-void
conservation, invoiceability guards, the accessorial subresource listing, and
billing authorization.

Covers Difficulty rules: combinatorial_formula, compensating_invariant.
Covers Corner sections: calculations, errors, endpoints, validations.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId,
    mk_terminal, mk_booking,
    create_invoice_payload, create_accessorial_payload,
    setup_delivered_booking, setup_invoiced_booking,
    TEST_USERS,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
BILLER = TEST_USERS["biller_headers"]


# --- combinatorial_formula: discount -> fuel -> sum -> floor ---------------

def test_invoice_applies_volume_discount_and_fuel_surcharge(api):
    """PRD §3.9: "if the booking's `linehaul_base_cents` is at least the volume
    threshold of 100000 cents, the effective linehaul is the base multiplied by one
    minus the volume discount of 0.10 (that is, by 0.90), rounded half-up to whole
    cents; otherwise the effective linehaul equals the base unchanged."
    PRD §3.9: "Then `fuel_surcharge_cents` is the effective linehaul multiplied by the
    fuel percentage of 0.22, rounded half-up to whole cents independently of the
    discount rounding."

    Design: Difficulty/combinatorial_formula/invoice_total_discount_fuel_floor_mode_a
    """
    ctx = setup_invoiced_booking(
        api, clock="2026-05-06T00:00:00Z", linehaul_base_cents=120000, container_number="MSCU3",
        accessorials=[("CHASSIS_RENTAL", 12000), ("PRE_PULL", 8000)])
    invoice = validate_success(api.get_invoice(ctx["invoice_id"], BILLER))
    assert invoice["effective_linehaul_cents"] == 108000
    assert invoice["fuel_surcharge_cents"] == 23760


def test_invoice_total_sums_all_line_items(api):
    """PRD §3.9: "The subtotal is the sum of `effective_linehaul_cents`,
    `fuel_surcharge_cents`, `accessorials_total_cents`, `demurrage_cents`, and
    `per_diem_cents`. Finally, `total_charge_cents` is the greater of that subtotal
    and the minimum charge of 50000 cents."
    PRD §3.9: "The `accessorials_total_cents` is the sum of `amount_cents` over the
    invoice's `ACTIVE` accessorial charges."

    Design: Difficulty/combinatorial_formula/invoice_total_discount_fuel_floor_mode_a
    """
    ctx = setup_invoiced_booking(
        api, clock="2026-05-06T00:00:00Z", linehaul_base_cents=120000, container_number="MSCU3",
        accessorials=[("CHASSIS_RENTAL", 12000), ("PRE_PULL", 8000)])
    invoice = validate_success(api.get_invoice(ctx["invoice_id"], BILLER))
    assert invoice["accessorials_total_cents"] == 20000
    # 108000 + 23760 + 20000 + 0 demurrage + 0 per_diem = 151760 (>= 50000 floor).
    assert invoice["total_charge_cents"] == 151760


# --- compensating_invariant: add then void conserves the total -------------

def test_invoice_total_before_any_accessorial(api):
    """PRD §3.9: "Then `fuel_surcharge_cents` is the effective linehaul multiplied by
    the fuel percentage of 0.22, rounded half-up to whole cents independently of the
    discount rounding."
    PRD §3.9: "Finally, `total_charge_cents` is the greater of that subtotal and the
    minimum charge of 50000 cents."

    Design: Difficulty/compensating_invariant/accessorial_add_void_invoice_total_conserved
    """
    ctx = setup_invoiced_booking(
        api, clock="2026-05-06T00:00:00Z", linehaul_base_cents=45000, container_number="MSCUM")
    invoice = validate_success(api.get_invoice(ctx["invoice_id"], BILLER))
    # 45000 (no discount) + round(45000*0.22)=9900 = 54900.
    assert invoice["total_charge_cents"] == 54900


def test_void_accessorial_restores_invoice_total(api):
    """PRD §3.9: "A biller may void an `ACTIVE` line, identified by its `accessorial_id`
    in the path, moving it to `VOIDED`. Adding a line and voiding a line each recompute
    the parent invoice's `accessorials_total_cents` and `total_charge_cents` using the
    same aggregation and floor described above, and each increments the affected line's
    `version`."

    Design: Difficulty/compensating_invariant/accessorial_add_void_invoice_total_conserved
    """
    ctx = setup_invoiced_booking(
        api, clock="2026-05-06T00:00:00Z", linehaul_base_cents=45000, container_number="MSCUM",
        accessorials=[("STORAGE", 7500)])
    with_acc = validate_success(api.get_invoice(ctx["invoice_id"], BILLER))
    assert with_acc["total_charge_cents"] == 62400
    voided = get_success_data(api.void_accessorial(ctx["invoice_id"], ctx["accessorial_ids"][0], BILLER))
    assert voided["status"] == "VOIDED"
    after = validate_success(api.get_invoice(ctx["invoice_id"], BILLER))
    assert after["total_charge_cents"] == 54900


# --- Corner: minimum-charge floor engages ---------------------------------

def test_invoice_minimum_charge_floor_applies(api):
    """PRD §3.9: "Then `fuel_surcharge_cents` is the effective linehaul multiplied by
    the fuel percentage of 0.22, rounded half-up to whole cents independently of the
    discount rounding."
    PRD §3.9: "Finally, `total_charge_cents` is the greater of that subtotal and the
    minimum charge of 50000 cents."

    Design: Corner/calculations/invoice_min_charge_floor_applies
    """
    ctx = setup_invoiced_booking(
        api, clock="2026-05-06T00:00:00Z", linehaul_base_cents=30000, container_number="MSCU13")
    invoice = validate_success(api.get_invoice(ctx["invoice_id"], BILLER))
    assert invoice["fuel_surcharge_cents"] == 6600
    # subtotal 30000 + 6600 = 36600 < 50000 -> floored to 50000.
    assert invoice["total_charge_cents"] == 50000


# --- Corner: invoiceability guards ----------------------------------------

def test_duplicate_invoice_rejected(api):
    """PRD §3.9: "Generation is only allowed when the booking's `status` is
    `DELIVERED` or `EMPTY_RETURNED` and no invoice already exists for that booking;
    otherwise the request is rejected with `ERR_NOT_INVOICEABLE`."

    Design: Corner/errors/duplicate_invoice_rejected
    """
    ctx = setup_invoiced_booking(api, clock="2026-05-06T00:00:00Z", container_number="MSCU21")
    resp = api.create_invoice(create_invoice_payload(ctx["booking_id"]), BILLER)
    validate_error(resp, ApiErrorId.ERR_NOT_INVOICEABLE, expected_status=409)


def test_invoice_on_draft_booking_rejected(api):
    """PRD §3.9: "Generation is only allowed when the booking's `status` is
    `DELIVERED` or `EMPTY_RETURNED` and no invoice already exists for that booking;
    otherwise the request is rejected with `ERR_NOT_INVOICEABLE`."

    Design: Corner/errors/invoice_on_draft_booking_rejected
    """
    terminal = mk_terminal(api, name="Berth 71", code="B71")
    booking = mk_booking(api, terminal["id"], container_number="MSCU22")
    resp = api.create_invoice(create_invoice_payload(booking["id"]), BILLER)
    validate_error(resp, ApiErrorId.ERR_NOT_INVOICEABLE, expected_status=409)


def test_add_accessorial_to_issued_invoice_rejected(api):
    """PRD §3.9: "Issuing an invoice advances it from `DRAFT` to `ISSUED`, freezes its
    accessorials so none can be added or voided afterward, and increments the invoice's
    `version`."
    PRD §3.9: "Adding or voiding is only permitted while the parent invoice is `DRAFT`;
    attempting either on a non-`DRAFT` invoice is rejected with `ERR_NOT_INVOICEABLE`."

    Design: Corner/errors/accessorial_add_on_issued_invoice_rejected
    """
    ctx = setup_invoiced_booking(api, clock="2026-05-06T00:00:00Z", container_number="MSCU23")
    issued = get_success_data(api.issue_invoice(ctx["invoice_id"], BILLER))
    assert issued["status"] == "ISSUED"
    resp = api.add_accessorial(ctx["invoice_id"], create_accessorial_payload(kind="STORAGE", amount_cents=5000), BILLER)
    validate_error(resp, ApiErrorId.ERR_NOT_INVOICEABLE, expected_status=409)


# --- Corner: accessorial subresource listing ------------------------------

def test_list_invoice_accessorials(api):
    """PRD §3.9: "While an invoice is `DRAFT`, a biller may add **accessorial charge**
    lines, each with a `kind` of `CHASSIS_RENTAL`, `PRE_PULL`, `STORAGE`, `HAZMAT`, or
    `REEFER` and an `amount_cents` (never negative). A new accessorial line's
    `invoice_id` is taken from the path, and it starts `ACTIVE`."

    Design: Corner/endpoints/accessorials_subresource_list
    """
    ctx = setup_invoiced_booking(
        api, clock="2026-05-06T00:00:00Z", container_number="MSCU20",
        accessorials=[("CHASSIS_RENTAL", 12000), ("PRE_PULL", 8000)])
    data, _meta = validate_paginated(api.list_accessorials(ctx["invoice_id"], BILLER))
    assert len(data) == 2
    assert {a["kind"] for a in data} == {"CHASSIS_RENTAL", "PRE_PULL"}
    assert all(a["status"] == "ACTIVE" for a in data)


# --- Corner: Dispatcher may not generate invoices -------------------------

def test_dispatcher_cannot_create_invoice(api):
    """PRD §2.1: "The `Biller` role owns billing — invoice generation, issuance, and
    the management of accessorial charge lines."
    PRD §2.1: "When a syntactically valid, known role attempts an operation it is not
    permitted to perform, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/validations/dispatcher_cannot_create_invoice_returns_unauthorized
    """
    ctx = setup_delivered_booking(api, clock="2026-05-06T00:00:00Z", container_number="MSCU16")
    resp = api.create_invoice(create_invoice_payload(ctx["booking_id"]), DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)
