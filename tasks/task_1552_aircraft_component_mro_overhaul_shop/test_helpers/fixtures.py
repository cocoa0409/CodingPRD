"""Composite setup helpers.

Every helper builds its world through the public API only. The test harness
restarts the API server with an empty database before each test, so helpers
never assume any pre-existing row.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    booking_payload,
    clock_payload,
    core_return_payload,
    customer_payload,
    directive_payload,
    discrepancy_payload,
    exchange_agreement_payload,
    lease_agreement_payload,
    part_payload,
    parts_requisition_payload,
    pma_approval_payload,
    quote_approval_payload,
    quote_payload,
    receive_payload,
    source_approval_payload,
    test_cell_payload,
    test_results_payload,
    unit_payload,
    warranty_claim_payload,
    warranty_review_payload,
    work_order_payload,
)
from .test_users import (
    CSR,
    INSPECTOR,
    PARTS_BUYER,
    SHOP_MANAGER,
    TECHNICIAN,
    make_customer_headers,
    make_inspector_headers,
    make_technician_headers,
)


# ==========================================================================
# Tier 0 -- single-call primitives
# ==========================================================================

def set_clock(to_iso8601: str) -> dict:
    """PRD §2.5: advance the logical clock; sweeps DEFAULTED exchanges."""
    return get_success_data(api_client.set_clock(clock_payload(to_iso8601), SHOP_MANAGER))


def create_customer(**overrides) -> dict:
    return get_success_data(api_client.create_customer(customer_payload(**overrides), SHOP_MANAGER))


def create_part(**overrides) -> dict:
    return get_success_data(api_client.create_part(part_payload(**overrides), SHOP_MANAGER))


def create_directive(part_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_directive(part_id, directive_payload(**overrides), SHOP_MANAGER))


def create_unit(part_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_unit(unit_payload(part_id, **overrides), CSR))


def create_customer_unit(part_id: str, customer_id: str, **overrides) -> dict:
    """PRD §3.2: CUSTOMER-owned units require owner_customer_id and OFF_SITE custody."""
    overrides.setdefault("ownership", "CUSTOMER")
    overrides.setdefault("owner_customer_id", customer_id)
    overrides.setdefault("custody_status", "OFF_SITE")
    return create_unit(part_id, **overrides)


def create_shop_pool_unit(part_id: str, **overrides) -> dict:
    """PRD §3.2: SHOP-owned units register with custody IN_POOL or IN_SHOP and no owner."""
    overrides.setdefault("ownership", "SHOP")
    overrides.setdefault("condition_status", "SERVICEABLE")
    overrides.setdefault("custody_status", "IN_POOL")
    overrides.pop("owner_customer_id", None)
    return create_unit(part_id, **overrides)


def create_work_order(customer_id: str, unit_id: str, work_scope: str = "OVERHAUL", **overrides) -> dict:
    return get_success_data(api_client.create_work_order(
        work_order_payload(customer_id, unit_id, work_scope=work_scope, **overrides), CSR))


def get_work_order(work_order_id: str) -> dict:
    return get_success_data(api_client.get_work_order(work_order_id, SHOP_MANAGER))


def get_unit(unit_id: str) -> dict:
    return get_success_data(api_client.get_unit(unit_id, SHOP_MANAGER))


def get_customer(customer_id: str) -> dict:
    return get_success_data(api_client.get_customer(customer_id, SHOP_MANAGER))


def create_test_cell(**overrides) -> dict:
    return get_success_data(api_client.create_test_cell(test_cell_payload(**overrides), SHOP_MANAGER))


def book_cell(test_cell_id: str, work_order_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_booking(
        test_cell_id, booking_payload(work_order_id, **overrides), CSR))


def file_discrepancy(work_order_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_discrepancy(
        work_order_id, discrepancy_payload(**overrides), TECHNICIAN))


def disposition_discrepancy(discrepancy_id: str, disposition_text: str = "Reworked per CMM") -> dict:
    return get_success_data(api_client.disposition_discrepancy(
        discrepancy_id, {"disposition_text": disposition_text}, TECHNICIAN))


def record_directive_compliance(work_order_id: str, directive_number: str,
                                result: str = "COMPLIED", **overrides) -> dict:
    payload = {"directive_number": directive_number, "result": result}
    payload.update(overrides)
    return get_success_data(api_client.record_directive_compliance(work_order_id, payload, TECHNICIAN))


def submit_quote(work_order_id: str, **overrides) -> dict:
    return get_success_data(api_client.submit_quote(
        work_order_id, quote_payload(**overrides), CSR))


def approve_quote(work_order_id: str, customer_id: str, expected_work_order_version: int) -> dict:
    return get_success_data(api_client.approve_quote(
        work_order_id,
        quote_approval_payload(expected_work_order_version),
        make_customer_headers(customer_id)))


def complete_repair(work_order_id: str, technician_user_id: str = "tech-1") -> dict:
    return get_success_data(api_client.complete_repair(
        work_order_id, make_technician_headers(technician_user_id)))


def record_test_results(work_order_id: str, result: str = "PASS",
                        atp_reference: str = "ATP-1",
                        inspector_user_id: str = "insp-9") -> dict:
    return get_success_data(api_client.record_test_results(
        work_order_id,
        test_results_payload(result=result, atp_reference=atp_reference),
        make_inspector_headers(inspector_user_id)))


def release_work_order(work_order_id: str, inspector_user_id: str = "insp-9") -> dict:
    return get_success_data(api_client.release_work_order(
        work_order_id, make_inspector_headers(inspector_user_id)))


def close_work_order(work_order_id: str) -> dict:
    return get_success_data(api_client.close_work_order(work_order_id, CSR))


def generate_invoice(work_order_id: str) -> dict:
    return get_success_data(api_client.generate_invoice(work_order_id, CSR))


def create_parts_requisition(work_order_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_parts_requisition(
        work_order_id, parts_requisition_payload(**overrides), TECHNICIAN))


def source_approve(requisition_id: str, approved: bool, **overrides) -> dict:
    return get_success_data(api_client.source_approval(
        requisition_id, source_approval_payload(approved, **overrides), PARTS_BUYER))


def pma_approve(requisition_id: str, customer_id: str, approved: bool) -> dict:
    return get_success_data(api_client.pma_approval(
        requisition_id, pma_approval_payload(approved),
        make_customer_headers(customer_id)))


def receive_requisition(requisition_id: str, unit_cost_cents: int) -> dict:
    return get_success_data(api_client.receive_requisition(
        requisition_id, receive_payload(unit_cost_cents), PARTS_BUYER))


def issue_requisition(requisition_id: str) -> dict:
    return get_success_data(api_client.issue_requisition(requisition_id, TECHNICIAN))


def issue_received_requisition(requisition_id: str, unit_cost_cents: int) -> dict:
    """Approve (OEM) -> receive -> issue in one go."""
    source_approve(requisition_id, True)
    receive_requisition(requisition_id, unit_cost_cents)
    return issue_requisition(requisition_id)


def create_exchange_agreement(customer_id: str, part_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_exchange_agreement(
        exchange_agreement_payload(customer_id, part_id, **overrides), CSR))


def get_exchange_agreement(agreement_id: str) -> dict:
    return get_success_data(api_client.get_exchange_agreement(agreement_id, SHOP_MANAGER))


def fulfill_exchange(agreement_id: str) -> dict:
    return get_success_data(api_client.fulfill_exchange(agreement_id, CSR))


def core_return_exchange(agreement_id: str, core_unit_id: str,
                         core_teardown_estimate_cents: int) -> dict:
    return get_success_data(api_client.core_return_exchange(
        agreement_id,
        core_return_payload(core_unit_id, core_teardown_estimate_cents),
        TECHNICIAN))


def create_lease(customer_id: str, unit_id: str, expected_unit_version: int, **overrides) -> dict:
    return get_success_data(api_client.create_lease_agreement(
        lease_agreement_payload(customer_id, unit_id, expected_unit_version, **overrides), CSR))


def get_lease(agreement_id: str) -> dict:
    return get_success_data(api_client.get_lease_agreement(agreement_id, SHOP_MANAGER))


def return_lease(agreement_id: str) -> dict:
    return get_success_data(api_client.return_lease(agreement_id, CSR))


def create_warranty_claim(original_work_order_id: str, customer_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_warranty_claim(
        warranty_claim_payload(original_work_order_id, **overrides),
        make_customer_headers(customer_id)))


def review_warranty_claim(claim_id: str, decision: str, **overrides) -> dict:
    return get_success_data(api_client.review_warranty_claim(
        claim_id, warranty_review_payload(decision, **overrides), SHOP_MANAGER))


def pay_invoice(invoice_id: str, customer_id: str, amount_cents: int) -> dict:
    return get_success_data(api_client.pay_invoice(
        invoice_id, {"amount_cents": amount_cents}, make_customer_headers(customer_id)))


# ==========================================================================
# Tier 1: State Progression
# ==========================================================================

def setup_customer_part_unit(customer_overrides=None, part_overrides=None,
                             unit_overrides=None):
    """Customer + catalog part + CUSTOMER-owned OFF_SITE unit. Returns (c, p, u)."""
    customer = create_customer(**(customer_overrides or {}))
    part = create_part(**(part_overrides or {}))
    unit = create_customer_unit(part["id"], customer["id"], **(unit_overrides or {}))
    return customer, part, unit


def setup_work_order_in_teardown(work_scope: str = "OVERHAUL", **kwargs):
    """Customer + part + unit + work order in TEARDOWN_IN_PROGRESS."""
    customer, part, unit = setup_customer_part_unit(**kwargs)
    wo = create_work_order(customer["id"], unit["id"], work_scope=work_scope)
    return customer, part, unit, wo


def setup_work_order_awaiting_quote(work_scope: str = "OVERHAUL",
                                    discrepancy_specs=None, **kwargs):
    """Work order driven to AWAITING_QUOTE (teardown-complete).

    discrepancy_specs: optional list of dicts each passed to file_discrepancy.
    If provided AND disposition=True on a spec, the card is also dispositioned,
    leaving open_discrepancy_count at 0 before teardown-complete.
    """
    customer, part, unit, wo = setup_work_order_in_teardown(work_scope=work_scope, **kwargs)
    for spec in (discrepancy_specs or []):
        spec = dict(spec)
        do_disposition = spec.pop("disposition", False)
        card = file_discrepancy(wo["id"], **spec)
        if do_disposition:
            disposition_discrepancy(card["id"])
    wo = get_success_data(api_client.teardown_complete(wo["id"], TECHNICIAN))
    return customer, part, unit, wo


def setup_work_order_quoted(work_scope: str = "OVERHAUL",
                            quote_overrides=None,
                            directives=None, **kwargs):
    """Work order in QUOTE_SUBMITTED. Returns (customer, part, unit, wo, quote_version)."""
    # Pre-create directives BEFORE induction so compliance rows are PENDING
    customer = create_customer(**(kwargs.pop("customer_overrides", {}) or {}))
    part = create_part(**(kwargs.pop("part_overrides", {}) or {}))
    for d in (directives or []):
        create_directive(part["id"], **d)
    unit = create_customer_unit(part["id"], customer["id"], **(kwargs.pop("unit_overrides", {}) or {}))
    wo = create_work_order(customer["id"], unit["id"], work_scope=work_scope)
    get_success_data(api_client.teardown_complete(wo["id"], TECHNICIAN))
    quoted = submit_quote(wo["id"], **(quote_overrides or {}))
    return customer, part, unit, quoted, quoted["version"]


def setup_work_order_in_repair(work_scope: str = "OVERHAUL",
                               quote_overrides=None,
                               directives=None,
                               parts_requisitions=None,
                               approve_delay_iso=None,
                               **kwargs):
    """Work order in REPAIR_IN_PROGRESS.

    parts_requisitions: list of dicts each with `payload` (passed to
    create_parts_requisition) and optional `receive_cost` (if present, also
    source-approve / receive / issue with that unit_cost_cents).
    approve_delay_iso: optional ISO timestamp — if set, the clock is advanced
    to it BEFORE the customer approves the quote, accumulating delay hours.
    """
    customer, part, unit, quoted, v_q = setup_work_order_quoted(
        work_scope=work_scope, quote_overrides=quote_overrides,
        directives=directives, **kwargs)
    if approve_delay_iso is not None:
        set_clock(approve_delay_iso)
    approved = approve_quote(quoted["id"], customer["id"], v_q)
    return customer, part, unit, approved


def setup_work_order_ready_for_test(work_scope: str = "OVERHAUL",
                                    directives=None,
                                    directive_results=None,
                                    technician_user_id: str = "tech-1",
                                    **kwargs):
    """Work order in READY_FOR_TEST with technician_user_id pinned.

    directives: list of dicts to create BEFORE induction.
    directive_results: optional dict {directive_number: result} to comply with.
    By default every PENDING directive is marked COMPLIED so the complete-repair
    AD gate passes.
    """
    customer, part, unit, wo = setup_work_order_in_repair(
        work_scope=work_scope, directives=directives, **kwargs)
    results_map = directive_results or {}
    for d in (directives or []):
        record_directive_compliance(
            wo["id"], d["directive_number"],
            result=results_map.get(d["directive_number"], "COMPLIED"))
    wo = complete_repair(wo["id"], technician_user_id=technician_user_id)
    return customer, part, unit, wo


def setup_work_order_test_passed(work_scope: str = "OVERHAUL",
                                 booking_window=("2026-08-02T01:00:00Z",
                                                  "2026-08-02T05:00:00Z"),
                                 test_clock="2026-08-02T02:00:00Z",
                                 technician_user_id: str = "tech-1",
                                 inspector_user_id: str = "insp-9",
                                 cell_overrides=None,
                                 **kwargs):
    """Work order in TEST_PASSED. Books a cell, advances clock, records PASS."""
    customer, part, unit, wo = setup_work_order_ready_for_test(
        work_scope=work_scope, technician_user_id=technician_user_id, **kwargs)
    cell = create_test_cell(**(cell_overrides or {}))
    booking = book_cell(
        cell["id"], wo["id"],
        start_time=booking_window[0], end_time=booking_window[1])
    set_clock(test_clock)
    wo = record_test_results(wo["id"], result="PASS",
                             inspector_user_id=inspector_user_id)
    return customer, part, unit, wo, cell, booking


def setup_work_order_released(work_scope: str = "OVERHAUL",
                              technician_user_id: str = "tech-1",
                              inspector_user_id: str = "insp-9",
                              **kwargs):
    """Work order in RELEASED. Returns (customer, part, unit, wo, cell, booking)."""
    customer, part, unit, wo, cell, booking = setup_work_order_test_passed(
        work_scope=work_scope,
        technician_user_id=technician_user_id,
        inspector_user_id=inspector_user_id,
        **kwargs)
    wo = release_work_order(wo["id"], inspector_user_id=inspector_user_id)
    return customer, part, unit, wo, cell, booking


def setup_work_order_closed(work_scope: str = "OVERHAUL",
                            technician_user_id: str = "tech-1",
                            inspector_user_id: str = "insp-9",
                            **kwargs):
    """Work order fully CLOSED with invoice generated.

    Returns (customer, part, unit, wo, invoice).
    """
    customer, part, unit, wo, _cell, _booking = setup_work_order_released(
        work_scope=work_scope,
        technician_user_id=technician_user_id,
        inspector_user_id=inspector_user_id,
        **kwargs)
    invoice = generate_invoice(wo["id"])
    wo = close_work_order(wo["id"])
    return customer, part, unit, wo, invoice


# ==========================================================================
# Tier 2: full pipeline with parts & bookings
# ==========================================================================

def setup_released_overhaul_with_charges(
        customer_overrides=None,
        part_overrides=None,
        quote_overrides=None,
        requisition_specs=None,
        booking_specs=None,
        technician_user_id: str = "tech-1",
        inspector_user_id: str = "insp-9",
        test_clock="2026-08-02T02:00:00Z",
        approve_delay_iso=None,
        cell_name="CELL-A"):
    """Drive an OVERHAUL work order to RELEASED with configurable parts and
    bookings, returning (customer, part, unit, wo, invoice_inputs).

    requisition_specs: list of dicts each having `part_number`, `quantity`,
    `requested_source`, and `unit_cost_cents`. Each spec results in an ISSUED
    requisition on the work order.
    booking_specs: list of dicts each with `start_time`, `end_time`; all are
    booked against the same cell.
    """
    customer = create_customer(**(customer_overrides or {}))
    part = create_part(**(part_overrides or {}))
    unit = create_customer_unit(part["id"], customer["id"])
    wo = create_work_order(customer["id"], unit["id"], work_scope="OVERHAUL")
    get_success_data(api_client.teardown_complete(wo["id"], TECHNICIAN))
    quoted = submit_quote(wo["id"], **(quote_overrides or {}))
    if approve_delay_iso is not None:
        set_clock(approve_delay_iso)
    approved = approve_quote(wo["id"], customer["id"], quoted["version"])
    wo_id = approved["id"]
    for spec in (requisition_specs or []):
        spec = dict(spec)
        unit_cost = spec.pop("unit_cost_cents")
        req = create_parts_requisition(wo_id, **spec)
        issue_received_requisition(req["id"], unit_cost)
    wo = complete_repair(wo_id, technician_user_id=technician_user_id)
    cell = create_test_cell(name=cell_name)
    bookings = []
    for spec in (booking_specs or []):
        bookings.append(book_cell(cell["id"], wo_id, **spec))
    set_clock(test_clock)
    record_test_results(wo_id, result="PASS", inspector_user_id=inspector_user_id)
    wo = release_work_order(wo_id, inspector_user_id=inspector_user_id)
    return customer, part, unit, wo, cell, bookings


# ==========================================================================
# Tier 3: exchange-pool scenarios
# ==========================================================================

def setup_exchange_fulfilled(customer_overrides=None, part_overrides=None,
                             pool_unit_overrides=None, core_unit_overrides=None):
    """Customer + part + SHOP pool unit + CUSTOMER core + FULFILLED agreement.

    Returns (customer, part, pool_unit, core_unit, agreement).
    """
    customer = create_customer(**(customer_overrides or {}))
    part = create_part(**(part_overrides or {}))
    pool_unit = create_shop_pool_unit(part["id"], **(pool_unit_overrides or {}))
    core_unit = create_customer_unit(part["id"], customer["id"],
                                     serial_number="SN-C1",
                                     total_cycles=7000,
                                     cycles_since_overhaul=900,
                                     manufactured_at="2012-05-01",
                                     **(core_unit_overrides or {}))
    agreement = create_exchange_agreement(customer["id"], part["id"])
    agreement = fulfill_exchange(agreement["id"])
    return customer, part, pool_unit, core_unit, agreement


# ==========================================================================
# Tier 4: lease scenarios
# ==========================================================================

def setup_lease_active(customer_overrides=None, part_overrides=None,
                       unit_overrides=None, lease_overrides=None):
    """Customer + SHOP pool unit + ACTIVE lease. Returns (customer, part, unit, lease)."""
    customer = create_customer(**(customer_overrides or {}))
    part = create_part(**(part_overrides or {}))
    unit = create_shop_pool_unit(part["id"], **(unit_overrides or {}))
    lease = create_lease(customer["id"], unit["id"], unit["version"],
                         **(lease_overrides or {}))
    return customer, part, unit, lease


# ==========================================================================
# Tier 5: warranty scenarios
# ==========================================================================

def setup_warranty_claim_submitted(claim_overrides=None, **kwargs):
    """Closed OVERHAUL work order + SUBMITTED warranty claim.

    Returns (customer, part, unit, original_wo, original_invoice, claim).
    """
    customer, part, unit, wo, invoice = setup_work_order_closed(**kwargs)
    claim = create_warranty_claim(wo["id"], customer["id"], **(claim_overrides or {}))
    return customer, part, unit, wo, invoice, claim


def setup_warranty_claim_accepted(claim_overrides=None, **kwargs):
    """Closed original + ACCEPTED claim (rework work order spawned).

    Returns (customer, part, unit, original_wo, original_invoice, claim, rework_wo).
    """
    customer, part, unit, wo, invoice, claim = setup_warranty_claim_submitted(
        claim_overrides=claim_overrides, **kwargs)
    claim = review_warranty_claim(claim["id"], "ACCEPT")
    rework_wo = get_work_order(claim["rework_work_order_id"])
    return customer, part, unit, wo, invoice, claim, rework_wo
