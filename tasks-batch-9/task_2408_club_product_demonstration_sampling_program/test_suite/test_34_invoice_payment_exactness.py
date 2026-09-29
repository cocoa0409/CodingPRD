"""One settled event billed end to end, then paid to the cent."""

from decimal import Decimal

from prd_bench_local_runner.testing import (
    validate_error,
    validate_success,
)

from test_helpers import (
    ADMIN_BILLING_HEADERS,
    ADMIN_HQ_HEADERS,
    ApiErrorId,
    assert_cents,
)
from test_helpers.fixtures import (
    approve,
    assign,
    check_in,
    check_out,
    close_out,
    confirm_assignment,
    draft_invoice,
    file_reconciliation,
    issue_invoice,
    new_club,
    new_demo_event,
    new_demonstrator,
    new_manufacturer,
    new_non_food_product,
    receive,
    set_clock,
    ship,
    submit,
)
from test_helpers.types import (
    AssignmentRole,
    DayPart,
    InvoiceAction,
    InvoiceStatus,
    ProductCategory,
    ReconStatus,
)


def _decimal2(value):
    """Coerce a two-decimal API value into an exact Decimal for comparison."""
    return Decimal(str(value)).quantize(Decimal("0.01"))


def test_only_the_exact_amount_due_settles_an_issued_invoice(api):
    """PRD §3.9: "Recording a payment moves `invoice_status` from `ISSUED` to `PAID` and requires the supplied `amount_cents` to equal the invoice's `total_due_cents` exactly; a partial or excess payment is refused with `ERR_PAYMENT_AMOUNT_MISMATCH`."

    PRD §3.9: "Each line is the assignment's `billable_hours` multiplied by that demonstrator's `hourly_rate_cents` and multiplied again by a role multiplier of 1.20 for a `LEAD` or 1.00 for a `SUPPORT`, rounded half-up to whole cents."

    PRD §3.9: "One per-case handling line bills that case count multiplied by 900 cents."

    PRD §3.9: "Finally `total_due_cents` is `subtotal_cents` less `discount_cents` less `credit_applied_cents`, floored at zero so an invoice can never owe the vendor money."

    PRD §3.9: "A vendor's `outstanding_balance_cents` is the sum of `total_due_cents` over that vendor's invoices whose `invoice_status` is `ISSUED`; invoices in `DRAFT`, `VOID` and `PAID` contribute exactly zero, and invoices of other vendors never contribute."

    PRD §2.8: "**Payment exactness.** Recording a payment requires the supplied `amount_cents` to equal the invoice's `total_due_cents` exactly — otherwise `ERR_PAYMENT_AMOUNT_MISMATCH` (422)."

    Design: Corner/endpoints/record_payment_is_allowed_only_for_the_exact_amount_due
    """
    vendor = new_manufacturer(
        api,
        legal_name="Quarrybridge Home",
        credit_limit_cents=900_000,
        credit_terms_days=30,
    )
    club = new_club(
        api,
        club_number="C6037",
        name="Quarrybridge Club 6037",
        daily_event_capacity=3,
        food_station_count=1,
        health_permit_expires_on="2027-06-30",
    )
    product = new_non_food_product(
        api,
        vendor["id"],
        sku="QH-SPN-037",
        name="Sponge Multipack",
        category=ProductCategory.HOUSEHOLD,
        unit_cost_cents=500,
        samples_per_case=10,
        weekly_sample_case_pool=20,
    )
    worker = new_demonstrator(
        api, club["id"], full_name="Silas Renn", hourly_rate_cents=2000
    )
    event = new_demo_event(
        api,
        vendor["id"],
        club["id"],
        product["id"],
        event_date="2026-09-14",
        day_part=DayPart.MORNING,
        requested_sample_cases=2,
    )
    submit(api, event["id"], vendor["id"])
    approve(api, event["id"], club["id"])

    shipment = ship(api, event["id"], vendor["id"], 2, carrier_reference="TRK-66037")
    receive(api, shipment["id"], club["id"], 2)

    assignment = assign(api, event["id"], worker["id"], AssignmentRole.LEAD)
    set_clock(api, "2026-09-14T14:00:00Z")
    confirm_assignment(api, assignment["id"], worker["id"])
    check_in(api, assignment["id"], worker["id"], "2026-09-14T08:15:00Z")
    worked = check_out(api, assignment["id"], worker["id"], "2026-09-14T12:45:00Z")
    assert _decimal2(worked["hours_worked"]) == Decimal("4.50")
    assert _decimal2(worked["billable_hours"]) == Decimal("4.50")

    close_out(api, event["id"], club["id"])
    reconciliation = file_reconciliation(api, event["id"], club["id"], 20, 0, 0)
    assert reconciliation["recon_status"] == ReconStatus.BALANCED

    invoice = draft_invoice(api, event["id"])
    assert invoice["monthly_completed_event_count"] == 1
    assert_cents(invoice["base_fee_cents"], 28_000, "base_fee_cents")
    assert_cents(invoice["staffing_fee_cents"], 10_800, "staffing_fee_cents")
    assert_cents(invoice["sample_handling_fee_cents"], 1_800, "sample_handling_fee_cents")
    assert_cents(invoice["subtotal_cents"], 40_600, "subtotal_cents")
    assert_cents(invoice["discount_cents"], 0, "discount_cents")
    assert_cents(invoice["total_due_cents"], 40_600, "total_due_cents")
    assert invoice["credit_terms_days"] == 30

    issued = issue_invoice(api, invoice["id"])
    assert issued["invoice_status"] == InvoiceStatus.ISSUED

    exposed = validate_success(api.get_manufacturer(vendor["id"], ADMIN_HQ_HEADERS))
    assert_cents(exposed["outstanding_balance_cents"], 40_600, "outstanding_balance_cents")

    validate_error(
        api.invoice_transition(
            invoice["id"],
            {"action": InvoiceAction.RECORD_PAYMENT, "amount_cents": 40_000},
            ADMIN_BILLING_HEADERS,
        ),
        ApiErrorId.PAYMENT_AMOUNT_MISMATCH,
        422,
    )
    still_open = validate_success(api.get_invoice(invoice["id"], ADMIN_BILLING_HEADERS))
    assert still_open["invoice_status"] == InvoiceStatus.ISSUED

    paid = validate_success(
        api.invoice_transition(
            invoice["id"],
            {"action": InvoiceAction.RECORD_PAYMENT, "amount_cents": 40_600},
            ADMIN_BILLING_HEADERS,
        )
    )
    assert paid["invoice_status"] == InvoiceStatus.PAID
    assert paid["paid_at"] is not None

    settled = validate_success(api.get_manufacturer(vendor["id"], ADMIN_HQ_HEADERS))
    assert_cents(settled["outstanding_balance_cents"], 0, "outstanding_balance_cents")
