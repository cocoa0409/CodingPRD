"""Validation corners: auth headers, ownership, fiscal gates, ordering (queue B)."""
import pytest

from test_helpers import (
    ApiErrorId,
    CSR,
    NO_AUTH_HEADERS,
    SHOP_MANAGER,
    TECHNICIAN,
    api_client,
    approve_quote,
    book_cell,
    complete_repair,
    create_customer,
    create_exchange_agreement,
    create_part,
    create_shop_pool_unit,
    create_test_cell,
    create_unit,
    create_work_order,
    customer_payload,
    fulfill_exchange,
    generate_invoice,
    get_exchange_agreement,
    get_unit,
    make_customer_headers,
    make_inspector_headers,
    set_clock,
    setup_work_order_in_teardown,
    setup_work_order_ready_for_test,
    setup_work_order_released,
    submit_quote,
    validate_error,
    validate_paginated,
    validate_success,
    work_order_payload,
)


def test_fulfill_blocked_by_credit_hold(api):
    """PRD §2.10: "A customer's `credit_hold` flag is true exactly when
    `current_exposure_cents` is greater than or equal to `credit_limit_cents`
    — the boundary is inclusive. While `credit_hold` is true, two operations
    are blocked with `ERR_CUSTOMER_CREDIT_HOLD` (HTTP 402): submitting a
    quote on one of the customer's work orders, and fulfilling an exchange
    agreement for the customer." A customer created with
    `credit_limit_cents` 0 starts at exposure 0, and 0 >= 0 holds from
    inception.

    Design: Corner/validations/fulfill_blocked_by_credit_hold
    """
    customer = create_customer(name="BrokeAir", certificate_number="AIR-002",
                               credit_limit_cents=0)
    part = create_part()
    pool_unit = create_shop_pool_unit(part["id"], serial_number="SN-P1")
    agreement = create_exchange_agreement(customer["id"], part["id"])

    res = api.fulfill_exchange(agreement["id"], CSR)
    validate_error(res, ApiErrorId.ERR_CUSTOMER_CREDIT_HOLD.value, expected_status=402)

    after = get_exchange_agreement(agreement["id"])
    assert after["status"] == "OPEN"
    pool_after = get_unit(pool_unit["id"])
    assert pool_after["custody_status"] == "IN_POOL"


def test_create_customer_missing_auth_header_returns_400(api):
    """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
    identifying the acting user, and `X-User-Role`, specifying their
    operational capacity. A request in which either header is missing or
    empty is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`
    (HTTP 400)."

    Design: Corner/validations/create_customer_missing_auth_header_returns_400
    """
    res = api.create_customer(customer_payload(), NO_AUTH_HEADERS)
    validate_error(res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value,
                   expected_status=400)


def test_wo_create_unit_owner_mismatch(api):
    """PRD §3.2: "for a `CUSTOMER`-owned unit the owner must match the work
    order's customer, otherwise `ERR_UNIT_OWNER_MISMATCH` (HTTP 422)."

    Design: Corner/validations/wo_create_unit_owner_mismatch
    """
    c1 = create_customer()
    c2 = create_customer(name="BetaAir", certificate_number="AIR-002")
    part = create_part()
    unit = create_unit(part["id"], owner_customer_id=c1["id"])

    res = api.create_work_order(
        work_order_payload(c2["id"], unit["id"], work_scope="OVERHAUL"), CSR)
    validate_error(res, ApiErrorId.ERR_UNIT_OWNER_MISMATCH.value, expected_status=422)


def test_core_return_part_mismatch(api):
    """PRD §3.7: "the core unit's part must equal the agreement's part,
    otherwise `ERR_CORE_PART_MISMATCH` (HTTP 422)." The check fires after the
    ownership match passes (the wrong-part core is still owned by the
    agreement's customer).

    Design: Corner/validations/core_return_part_mismatch
    """
    customer = create_customer()
    p1 = create_part()
    p2 = create_part(part_number="PN-72-X", ata_chapter="72",
                     replacement_value_cents=5000000, warranty_cycle_limit=300,
                     warranty_month_limit=12, flat_overhaul_price_cents=900000)
    create_shop_pool_unit(p1["id"], serial_number="SN-P1")
    wrong_core = create_unit(p2["id"], serial_number="SN-C9",
                             owner_customer_id=customer["id"],
                             total_cycles=8000, cycles_since_overhaul=700,
                             manufactured_at="2011-01-01")
    agreement = create_exchange_agreement(customer["id"], p1["id"])
    fulfill_exchange(agreement["id"])

    res = api.core_return_exchange(
        agreement["id"],
        {"core_unit_id": wrong_core["id"], "core_teardown_estimate_cents": 100000},
        TECHNICIAN)
    validate_error(res, ApiErrorId.ERR_CORE_PART_MISMATCH.value, expected_status=422)

    after = get_exchange_agreement(agreement["id"])
    assert after["status"] == "FULFILLED"


def test_pma_approval_by_non_owner_customer_forbidden(api):
    """PRD §3.4: "The PMA branch instead reaches the `Customer`, who sends
    `approved` from `PMA_PENDING_CUSTOMER` (other statuses rejected with
    `ERR_REQUISITION_INVALID_STATE`), with ownership enforced against the
    work order's customer (`ERR_NOT_RESOURCE_OWNER`)."

    Design: Corner/validations/pma_approval_by_non_owner_customer_forbidden
    """
    c1 = create_customer()
    c2 = create_customer(name="BetaAir", certificate_number="AIR-002")
    part = create_part()
    unit = create_unit(part["id"], owner_customer_id=c1["id"])
    wo = create_work_order(c1["id"], unit["id"], work_scope="OVERHAUL")
    api_client.teardown_complete(wo["id"], TECHNICIAN)
    quoted = submit_quote(wo["id"], scrap_option_ack=False)
    approve_quote(wo["id"], c1["id"], quoted["version"])
    req = validate_success(api.create_parts_requisition(
        wo["id"],
        {"part_number": "SEAL-PMA", "quantity": 1, "requested_source": "PMA"},
        TECHNICIAN), 201)
    assert req["status"] == "PMA_PENDING_CUSTOMER"

    res = api.pma_approval(req["id"], {"approved": True},
                           make_customer_headers(c2["id"]))
    validate_error(res, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, expected_status=403)

    reqs, _ = validate_paginated(api.list_parts_requisitions(wo["id"], TECHNICIAN))
    assert len(reqs) == 1
    assert reqs[0]["status"] == "PMA_PENDING_CUSTOMER"


def test_payment_wrong_amount_then_double_pay_rejected(api):
    """PRD §3.6: "The checks, in order: the invoice must be `ISSUED`,
    otherwise `ERR_INVOICE_INVALID_STATE`; the caller must be the billed
    customer, otherwise `ERR_NOT_RESOURCE_OWNER`; and `amount_cents` must
    equal `total_cents` exactly, otherwise `ERR_PAYMENT_AMOUNT_MISMATCH`
    (HTTP 422). Success moves the invoice `ISSUED → PAID`, stamps `paid_at`
    with the clock, and subtracts `total_cents` from the customer's
    `current_exposure_cents` as the compensating action."

    Design: Corner/validations/payment_wrong_amount_then_double_pay_rejected
    """
    customer, part, unit, wo, cell, booking = setup_work_order_released()
    invoice = generate_invoice(wo["id"])
    # labor 2000000 + 4h booking fee 400000, released inside TAT -> penalty 0.
    assert invoice["total_cents"] == 2400000

    res1 = api.pay_invoice(invoice["id"], {"amount_cents": 1},
                           make_customer_headers(customer["id"]))
    validate_error(res1, ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH.value,
                   expected_status=422)
    still_issued = validate_success(api.get_invoice(invoice["id"], SHOP_MANAGER), 200)
    assert still_issued["status"] == "ISSUED"

    paid = validate_success(api.pay_invoice(
        invoice["id"], {"amount_cents": 2400000},
        make_customer_headers(customer["id"])), 200)
    assert paid["status"] == "PAID"

    res2 = api.pay_invoice(invoice["id"], {"amount_cents": 2400000},
                           make_customer_headers(customer["id"]))
    validate_error(res2, ApiErrorId.ERR_INVOICE_INVALID_STATE.value,
                   expected_status=409)


def test_booking_overlap_precedes_ata_capability(api):
    """PRD §2.9: "Booking creation checks the work order's from-state, then
    window overlap (temporal), then ATA capability (constraint)." PRD §3.5:
    "the window must not overlap any existing `BOOKED` window on the same
    cell — adjacency is allowed — otherwise `ERR_TEST_CELL_OVERLAP` (HTTP
    409); and the cell must support the ATA chapter of the work order's
    part, otherwise `ERR_CELL_ATA_UNSUPPORTED` (HTTP 422)."

    Design: Corner/validations/booking_overlap_precedes_ata_capability
    """
    customer = create_customer()
    p72 = create_part(part_number="PN-72-X", ata_chapter="72", is_rotable=False,
                      replacement_value_cents=5000000, warranty_cycle_limit=300,
                      warranty_month_limit=12, flat_overhaul_price_cents=900000)
    p32 = create_part(part_number="PN-32-ACT")
    unit_a = create_unit(p72["id"], serial_number="SN-A72",
                         owner_customer_id=customer["id"],
                         total_cycles=1000, cycles_since_overhaul=100,
                         manufactured_at="2018-01-01")
    unit_b = create_unit(p32["id"], serial_number="SN-B32",
                         owner_customer_id=customer["id"])
    wo_a = create_work_order(customer["id"], unit_a["id"], work_scope="REPAIR")
    api_client.teardown_complete(wo_a["id"], TECHNICIAN)
    quoted_a = submit_quote(wo_a["id"], labor_estimate_cents=500000,
                            parts_estimate_cents=100000, scrap_option_ack=False)
    approve_quote(wo_a["id"], customer["id"], quoted_a["version"])
    complete_repair(wo_a["id"], technician_user_id="tech-1")

    wo_b = create_work_order(customer["id"], unit_b["id"], work_scope="OVERHAUL")
    api_client.teardown_complete(wo_b["id"], TECHNICIAN)
    quoted_b = submit_quote(wo_b["id"], scrap_option_ack=False)
    approve_quote(wo_b["id"], customer["id"], quoted_b["version"])
    complete_repair(wo_b["id"], technician_user_id="tech-1")

    # CELL-X supports only ATA 72; wo_a's window [10:00, 14:00) occupies it.
    cell = create_test_cell(name="CELL-X", supported_ata_chapters=["72"])
    book_cell(cell["id"], wo_a["id"],
              start_time="2026-08-03T10:00:00Z", end_time="2026-08-03T14:00:00Z")

    # wo_b is ATA 32: overlapping window reports the temporal error first.
    res1 = api.create_booking(
        cell["id"],
        {"work_order_id": wo_b["id"],
         "start_time": "2026-08-03T13:00:00Z", "end_time": "2026-08-03T15:00:00Z"},
        CSR)
    validate_error(res1, ApiErrorId.ERR_TEST_CELL_OVERLAP.value, expected_status=409)

    # Once the window no longer overlaps, the ATA capability check surfaces.
    res2 = api.create_booking(
        cell["id"],
        {"work_order_id": wo_b["id"],
         "start_time": "2026-08-03T15:00:00Z", "end_time": "2026-08-03T16:00:00Z"},
        CSR)
    validate_error(res2, ApiErrorId.ERR_CELL_ATA_UNSUPPORTED.value, expected_status=422)


def test_segregation_of_duties_blocks_self_inspection(api):
    """PRD §3.5: "segregation of duties forbids the caller from being the
    technician who performed the repair, so `X-User-ID` must differ from the
    work order's `technician_user_id`, otherwise
    `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (HTTP 403)."

    Design: Corner/validations/segregation_of_duties_blocks_self_inspection
    """
    customer, part, unit, wo = setup_work_order_ready_for_test(
        technician_user_id="tech-1")
    cell = create_test_cell()
    book_cell(cell["id"], wo["id"],
              start_time="2026-08-02T01:00:00Z", end_time="2026-08-02T05:00:00Z")
    set_clock("2026-08-02T02:00:00Z")

    # The technician id pinned at complete-repair cannot self-inspect.
    res = api.record_test_results(
        wo["id"], {"result": "PASS", "atp_reference": "ATP-X"},
        make_inspector_headers("tech-1"))
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION.value,
                   expected_status=403)

    # An independent inspector passes on the same ready work order.
    passed = validate_success(api.record_test_results(
        wo["id"], {"result": "PASS", "atp_reference": "ATP-1"},
        make_inspector_headers("insp-9")), 200)
    assert passed["status"] == "TEST_PASSED"


def test_wo_create_unit_not_off_site_rejected(api):
    """PRD §3.2: "the unit's `custody_status` must be `OFF_SITE` — a unit
    already inducted, leased, or pooled is rejected with
    `ERR_UNIT_NOT_AVAILABLE` (HTTP 409)".

    Design: Corner/validations/wo_create_unit_not_off_site_rejected
    """
    customer, part, unit, wo1 = setup_work_order_in_teardown(work_scope="REPAIR")
    # WO1's induction already moved the unit OFF_SITE -> IN_SHOP.
    assert get_unit(unit["id"])["custody_status"] == "IN_SHOP"

    res = api.create_work_order(
        work_order_payload(customer["id"], unit["id"], work_scope="OVERHAUL"), CSR)
    validate_error(res, ApiErrorId.ERR_UNIT_NOT_AVAILABLE.value, expected_status=409)
