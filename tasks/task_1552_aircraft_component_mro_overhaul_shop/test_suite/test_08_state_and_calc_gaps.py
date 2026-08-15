"""State-machine lockdowns, warranty-limit rejection, and the exposure
compensating invariant (queue B state_machines/calculations; queue A rule 9)."""
import pytest

from test_helpers import (
    ApiErrorId,
    CSR,
    SHOP_MANAGER,
    TECHNICIAN,
    api_client,
    approve_quote,
    book_cell,
    close_work_order,
    complete_repair,
    create_customer,
    create_part,
    create_parts_requisition,
    create_test_cell,
    create_unit,
    create_warranty_claim,
    create_work_order,
    generate_invoice,
    get_customer,
    issue_received_requisition,
    make_customer_headers,
    record_test_results,
    release_work_order,
    review_warranty_claim,
    set_clock,
    setup_warranty_claim_submitted,
    setup_work_order_closed,
    setup_work_order_released,
    submit_quote,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_claim_denied_terminal_then_review_rejected(api):
    """PRD §3.9: "Review belongs to the `ShopManager`, who sends a `decision`
    of `ACCEPT` or `DENY` against a claim in `SUBMITTED` (otherwise
    `ERR_CLAIM_INVALID_STATE`). A `DENY` decision requires `denial_reason` to
    be present, otherwise `ERR_INVALID_REQUEST`, and moves the claim to
    `DENIED`."

    Design: Corner/state_machines/claim_denied_terminal_then_review_rejected
    """
    customer, part, unit, wo, invoice, claim = setup_warranty_claim_submitted()
    denied = review_warranty_claim(
        claim["id"], "DENY",
        denial_reason="Damage consistent with FOD, not workmanship")
    assert denied["status"] == "DENIED"

    res = api.review_warranty_claim(claim["id"], {"decision": "ACCEPT"}, SHOP_MANAGER)
    validate_error(res, ApiErrorId.ERR_CLAIM_INVALID_STATE.value, expected_status=409)


def test_invoice_double_generate_rejected(api):
    """PRD §3.6: "A `CustomerServiceRep` generates the work-order invoice
    once the work order is `RELEASED` with `released_at` recorded; a request
    against a work order in any other status is rejected with
    `ERR_WORK_ORDER_INVALID_STATE`, and a second invoice for the same work
    order is rejected with `ERR_INVOICE_ALREADY_EXISTS` (HTTP 409)."

    Design: Corner/state_machines/invoice_double_generate_rejected
    """
    customer, part, unit, wo, cell, booking = setup_work_order_released()
    invoice = generate_invoice(wo["id"])
    # labor 2000000 + 4h booking fee 400000, released inside TAT -> penalty 0.
    assert invoice["total_cents"] == 2400000
    assert get_customer(customer["id"])["current_exposure_cents"] == 2400000

    res = api.generate_invoice(wo["id"], CSR)
    validate_error(res, ApiErrorId.ERR_INVOICE_ALREADY_EXISTS.value,
                   expected_status=409)

    # The rejected regeneration did not debit exposure twice.
    assert get_customer(customer["id"])["current_exposure_cents"] == 2400000


def test_rework_close_bubbles_claim_to_settled(api):
    """PRD §3.5: "When the closed work order is a warranty rework —
    `work_scope` equal to `WARRANTY_REWORK` — the warranty claim whose
    `rework_work_order_id` names this work order bubbles up from `ACCEPTED`
    to `SETTLED`." PRD §3.6: "For a `WARRANTY_REWORK` work order the penalty
    mechanics switch off entirely: `penalty_credit_cents` is 0 and
    `penalty_variant` is `NONE`, while `warranty_credit_applied_cents`
    carries the claim credit computed in §3.9." and "for `WARRANTY_REWORK`
    it is the same sum minus the warranty credit, floored at zero".

    Design: Corner/state_machines/rework_close_bubbles_claim_to_settled
    """
    # Original OVERHAUL with one requisition: invoice base 2000000 + 575000.
    customer = create_customer()
    part = create_part()
    unit = create_unit(part["id"], owner_customer_id=customer["id"])
    wo = create_work_order(customer["id"], unit["id"], work_scope="OVERHAUL")
    api_client.teardown_complete(wo["id"], TECHNICIAN)
    quoted = submit_quote(wo["id"], scrap_option_ack=False)
    approve_quote(wo["id"], customer["id"], quoted["version"])
    req = create_parts_requisition(wo["id"], part_number="BRG-32-99",
                                    quantity=2, requested_source="OEM")
    issue_received_requisition(req["id"], 250000)
    complete_repair(wo["id"], technician_user_id="tech-1")
    cell = create_test_cell()
    book_cell(cell["id"], wo["id"],
              start_time="2026-08-02T01:00:00Z", end_time="2026-08-02T05:00:00Z")
    set_clock("2026-08-02T02:00:00Z")
    record_test_results(wo["id"], result="PASS", atp_reference="ATP-1",
                        inspector_user_id="insp-9")
    release_work_order(wo["id"], inspector_user_id="insp-9")
    generate_invoice(wo["id"])
    close_work_order(wo["id"])

    # Claim at 200 cycles on a 500-cycle limit -> FULL credit of 2575000.
    claim = create_warranty_claim(wo["id"], customer["id"],
                                  claim_cycles_used=200, claim_months_used=10,
                                  failure_description="Bearing spalling")
    accepted = review_warranty_claim(claim["id"], "ACCEPT")
    rework_id = accepted["rework_work_order_id"]

    # Drive the rework order (spawned in REPAIR_IN_PROGRESS) through to CLOSED.
    complete_repair(rework_id, technician_user_id="tech-2")
    book_cell(cell["id"], rework_id,
              start_time="2026-08-02T05:00:00Z", end_time="2026-08-02T09:00:00Z")
    set_clock("2026-08-02T06:00:00Z")
    record_test_results(rework_id, result="PASS", atp_reference="ATP-R1",
                        inspector_user_id="insp-9")
    release_work_order(rework_id, inspector_user_id="insp-9")

    rw_invoice = generate_invoice(rework_id)
    assert rw_invoice["warranty_credit_applied_cents"] == 2575000
    # Rework charges (labor 2000000 + 4h test fee 400000) are below the
    # credit, so the floored total is 0; no TAT penalty applies to rework.
    assert rw_invoice["total_cents"] == 0
    assert rw_invoice["penalty_variant"] == "NONE"

    close_work_order(rework_id)
    claim_after = validate_success(api.get_warranty_claim(claim["id"], SHOP_MANAGER), 200)
    assert claim_after["status"] == "SETTLED"


def test_warranty_limits_exceeded_rejected(api):
    """PRD §3.9: "the claim must lie within both coverage ceilings, inclusive
    — `claim_cycles_used` at most the part's `warranty_cycle_limit` and
    `claim_months_used` at most its `warranty_month_limit` — otherwise
    `ERR_WARRANTY_LIMIT_EXCEEDED` (HTTP 422)."

    Design: Corner/calculations/warranty_limits_exceeded_rejected
    """
    customer, part, unit, wo, invoice = setup_work_order_closed()
    # Limits on the default part: 500 cycles / 24 months.

    res1 = api.create_warranty_claim(
        {"original_work_order_id": wo["id"], "claim_cycles_used": 501,
         "claim_months_used": 10, "failure_description": "Over cycle limit"},
        make_customer_headers(customer["id"]))
    validate_error(res1, ApiErrorId.ERR_WARRANTY_LIMIT_EXCEEDED.value,
                   expected_status=422)

    res2 = api.create_warranty_claim(
        {"original_work_order_id": wo["id"], "claim_cycles_used": 100,
         "claim_months_used": 25, "failure_description": "Over month limit"},
        make_customer_headers(customer["id"]))
    validate_error(res2, ApiErrorId.ERR_WARRANTY_LIMIT_EXCEEDED.value,
                   expected_status=422)

    claims, meta = validate_paginated(api.list_warranty_claims(
        SHOP_MANAGER, params={"customer_id": customer["id"]}))
    assert meta["total_count"] == 0


def test_customer_exposure_conserved_across_issue_and_pay(api):
    """PRD §2.10: "When an invoice is `ISSUED`, its `total_cents` is added to
    `current_exposure_cents`; when an invoice is `PAID`, its `total_cents` is
    subtracted as a compensating action. The invariant is that
    `current_exposure_cents` always equals the sum of `total_cents` across
    that customer's invoices in `ISSUED` status."

    Design: Difficulty/compensating_invariant/customer_exposure_conserved_across_issue_and_pay
    """
    customer, part, unit, wo, cell, booking = setup_work_order_released()
    # Pre-issue baseline: a new customer starts at zero exposure.
    assert get_customer(customer["id"])["current_exposure_cents"] == 0

    invoice = generate_invoice(wo["id"])
    # labor 2000000 + 4h booking fee 400000, released inside TAT -> penalty 0.
    assert invoice["total_cents"] == 2400000
    mid = get_customer(customer["id"])
    assert mid["current_exposure_cents"] == 2400000

    paid = validate_success(api.pay_invoice(
        invoice["id"], {"amount_cents": 2400000},
        make_customer_headers(customer["id"])), 200)
    assert paid["status"] == "PAID"

    # The ISSUED+PAID pair conserves exposure at the pre-issue baseline.
    end = get_customer(customer["id"])
    assert end["current_exposure_cents"] == 0
    assert end["credit_hold"] is False
