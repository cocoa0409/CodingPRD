"""Non-linear state-machine tests: the cyclic TRY_IN -> REVISION -> DESIGN loop,
the Invoice's parallel billing/delivery dimensions, plus turnaround-promise and
immediate-visibility corner instances.
"""
import pytest
from test_helpers import (
    api_client, get_success_data, validate_success, validate_paginated,
    TEST_USERS, make_doctor_headers,
    tryin_verdict_payload, create_restoration_payload, create_case_payload,
    setup_case_at_tryin, setup_shipped_case, setup_submitted_case,
    get_invoice_for_case, get_case, create_doctor, create_material,
    set_clock,
)
from test_helpers.fixtures import list_units

ADMIN = TEST_USERS["labadmin_headers"]
TECH = TEST_USERS["labtech_headers"]
BILLING = TEST_USERS["billing_headers"]
SCHED = TEST_USERS["scheduler_headers"]


def test_revise_verdict_enters_revision_increments_count(api):
    """PRD §3.5: "A verdict of REVISE sends the case from TRY_IN to REVISION."
    PRD §3.5: "When a revision is accepted, the server increments revision_count
    by one, sends each milled billable unit back to QUEUED for re-milling,
    creates a ShadeRecord with matched false for each restoration flagged in the
    verdict, and increments the case's version."

    Design: Difficulty/non_linear_state_machine/case_tryin_revision_cycle
    """
    built = setup_case_at_tryin(
        material_overrides={"base_unit_price_cents": 12000, "fabrication_process": "MILLED"})
    case = built["case"]
    rest = built["restorations"][0]
    res = api.tryin_verdict(
        case["id"],
        tryin_verdict_payload("REVISE", case["version"], revise_restoration_ids=[rest["id"]]),
        make_doctor_headers(built["doctor"]["id"]))
    updated = validate_success(res, 200)
    assert updated["status"] == "REVISION"
    assert updated["revision_count"] == 1


def test_revise_requeues_milled_unit(api):
    """PRD §3.5: "When a revision is accepted, the server increments
    revision_count by one, sends each milled billable unit back to QUEUED for
    re-milling, creates a ShadeRecord with matched false for each restoration
    flagged in the verdict, and increments the case's version."

    Design: Difficulty/non_linear_state_machine/case_tryin_revision_cycle
    """
    built = setup_case_at_tryin(
        material_overrides={"base_unit_price_cents": 12000, "fabrication_process": "MILLED"})
    case = built["case"]
    rest = built["restorations"][0]
    api.tryin_verdict(
        case["id"],
        tryin_verdict_payload("REVISE", case["version"], revise_restoration_ids=[rest["id"]]),
        make_doctor_headers(built["doctor"]["id"]))
    units = list_units(rest["id"])
    assert len(units) == 1
    assert units[0]["status"] == "QUEUED", (
        f"the milled crown unit must be requeued for re-milling, got {units[0]['status']}"
    )


def test_pay_advances_billing_only_delivery_unchanged(api):
    """PRD §3.6: "Marking an invoice paid moves it from ISSUED to PAID and
    requires the invoice to currently be ISSUED." PRD §3.6: "On the delivery
    dimension delivery_status runs PENDING then IN_TRANSIT then DELIVERED,
    untouched by billing transitions."

    Design: Difficulty/non_linear_state_machine/invoice_parallel_billing_and_delivery_dimensions
    """
    built = setup_shipped_case(
        material_overrides={"base_unit_price_cents": 12000, "fabrication_process": "MILLED"})
    invoice = built["invoice"]
    assert invoice["billing_status"] == "ISSUED"
    assert invoice["delivery_status"] == "IN_TRANSIT"

    res = api.pay_invoice(invoice["id"], BILLING)
    paid = validate_success(res, 200)
    assert paid["billing_status"] == "PAID"
    assert paid["delivery_status"] == "IN_TRANSIT", (
        "paying the invoice is a billing-dimension move and must leave "
        "delivery_status at IN_TRANSIT"
    )


def test_ship_sets_billing_issued_delivery_in_transit(api):
    """PRD §3.6: "The ship transition also sets the invoice's billing_status to
    ISSUED and its delivery_status to IN_TRANSIT." PRD §3.6: "The
    DRAFT-to-ISSUED billing move and the PENDING-to-IN_TRANSIT delivery move both
    fire together at ship, the billing move conditioned on the invoice's kind
    having already flipped to FINAL."

    Design: Difficulty/non_linear_state_machine/invoice_parallel_billing_and_delivery_dimensions
    """
    built = setup_shipped_case(
        material_overrides={"base_unit_price_cents": 12000, "fabrication_process": "MILLED"})
    invoice = built["invoice"]
    assert invoice["kind"] == "FINAL"
    assert invoice["billing_status"] == "ISSUED"
    assert invoice["delivery_status"] == "IN_TRANSIT"


def test_turnaround_promise_rush_halving(api):
    """PRD §3.3: "If the case is a rush, the promised hours equal the base
    divided by two using integer floor division, but never less than a floor of
    24 hours - that is, the larger of the floor-halved base and 24." PRD §3.3:
    "where a crown promises 120 hours". PRD §3.3: "The resulting
    promised_ready_at is scheduled_start_at advanced by the promised hours."

    Design: Corner/calculations/turnaround_promise_rush_halving
    """
    built = setup_submitted_case(
        restoration_specs=[{"restoration_type": "CROWN", "unit_count": 1}],
        case_overrides={"is_rush": True},
        material_overrides={"base_unit_price_cents": 12000, "fabrication_process": "MILLED"},
    )
    case = built["case"]
    # crown 120h halved = 60h; submit at 2026-01-01T00:00:00Z -> 2026-01-03T12:00:00Z.
    assert case["promised_ready_at"] == "2026-01-03T12:00:00.000Z", (
        f"rush crown promised_ready_at must be +60h; got {case['promised_ready_at']}"
    )


def test_turnaround_promise_uses_slowest_restoration_type(api):
    """PRD §3.3: "The base figure is the largest per-type turnaround among the
    case's restorations, where a crown promises 120 hours, a bridge 168 hours, a
    denture 240 hours, and an aligner 336 hours; the case takes the maximum of
    these across all its restorations." PRD §3.3: "If the case is not a rush, the
    promised hours equal that base."

    Design: Corner/calculations/turnaround_promise_uses_slowest_restoration_type
    """
    set_clock()
    doctor = create_doctor()
    zir = create_material(base_unit_price_cents=12000, fabrication_process="MILLED")
    acr = create_material(base_unit_price_cents=4000, fabrication_process="MILLED")
    case = get_success_data(api.create_case(
        create_case_payload(doctor["id"], intake_method="IMPRESSION"), TECH))
    get_success_data(api.create_restoration(
        case["id"], create_restoration_payload(zir["id"], restoration_type="CROWN",
                                               unit_count=1), TECH))
    get_success_data(api.create_restoration(
        case["id"], create_restoration_payload(acr["id"], restoration_type="DENTURE",
                                               unit_count=1), TECH))
    submitted = get_success_data(api.submit_case(case["id"], TECH))
    # max(120 crown, 240 denture) = 240h from 2026-01-01T00:00:00Z -> 2026-01-11T00:00:00Z.
    assert submitted["promised_ready_at"] == "2026-01-11T00:00:00.000Z"


def test_provisional_invoice_correct_no_rush_no_discount(api):
    """PRD §3.3: "tax_cents is that taxable amount multiplied by 0.0825 and
    rounded half up." PRD §3.3: "On the provisional invoice sla_credit_cents is
    always 0 (no shipment has happened yet)." PRD §3.3: "Finally, total_cents is
    the taxable amount plus tax minus the SLA credit."

    Design: Corner/calculations/provisional_invoice_correct_no_rush_no_discount
    """
    built = setup_submitted_case(
        restoration_specs=[{"restoration_type": "CROWN", "unit_count": 1}],
        material_overrides={"base_unit_price_cents": 12000, "fabrication_process": "MILLED"},
    )
    invoice = get_invoice_for_case(built["case"]["id"])
    assert invoice["subtotal_cents"] == 12000
    assert invoice["tax_cents"] == 990          # round(12000 * 0.0825)
    assert invoice["discount_cents"] == 0
    assert invoice["total_cents"] == 12990
    assert invoice["kind"] == "PROVISIONAL"


def test_provisional_invoice_visible_immediately_after_submit(api):
    """PRD §3.3: "Sixth, it creates exactly one Invoice for the case with kind
    PROVISIONAL, billing_status DRAFT, and delivery_status PENDING, and populates
    that invoice's amounts." PRD §3.3: "The invoice's subtotal_cents is the sum,
    over every billable fabrication unit on the case, of that unit's
    restoration's unit_price_cents."

    Design: Corner/consistency_model/immediate_visibility_of_provisional_invoice
    """
    built = setup_submitted_case(
        restoration_specs=[{"restoration_type": "CROWN", "unit_count": 1}],
        material_overrides={"base_unit_price_cents": 12000, "fabrication_process": "MILLED"},
    )
    invoice = get_invoice_for_case(built["case"]["id"])
    assert invoice["subtotal_cents"] == 12000, (
        "the provisional invoice subtotal must be visible immediately after submit"
    )
