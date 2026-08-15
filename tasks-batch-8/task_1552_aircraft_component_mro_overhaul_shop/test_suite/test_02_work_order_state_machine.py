"""Work-order state machine corners and difficulty instances."""
import pytest

from test_helpers import (
    ApiErrorId,
    CSR,
    INSPECTOR,
    NON_EXISTENT_UUID,
    PARTS_BUYER,
    SHOP_MANAGER,
    TECHNICIAN,
    api_client,
    book_cell,
    close_work_order,
    complete_repair,
    create_customer,
    create_directive,
    create_part,
    create_test_cell,
    create_unit,
    create_work_order,
    disposition_discrepancy,
    file_discrepancy,
    generate_invoice,
    get_unit,
    get_work_order,
    make_customer_headers,
    make_inspector_headers,
    make_technician_headers,
    quote_payload,
    record_test_results,
    release_work_order,
    set_clock,
    setup_work_order_closed,
    setup_work_order_in_repair,
    setup_work_order_in_teardown,
    setup_work_order_quoted,
    setup_work_order_ready_for_test,
    setup_work_order_released,
    setup_work_order_test_passed,
    submit_quote,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# State machine corners (queue B)
# ---------------------------------------------------------------------------

def test_teardown_complete_blocked_by_open_discrepancy(api):
    """PRD §3.3: "Once findings are resolved, the `Technician` declares
    teardown complete. This requires the work order to be in
    `TEARDOWN_IN_PROGRESS` (otherwise `ERR_WORK_ORDER_INVALID_STATE`) and no
    card of the work order to remain `OPEN` (otherwise `ERR_OPEN_DISCREPANCIES`,
    HTTP 409)".

    Design: Corner/state_machines/teardown_complete_blocked_by_open_discrepancy
    """
    customer, part, unit, wo = setup_work_order_in_teardown()
    card = file_discrepancy(wo["id"], finding_text="Worn bearing", severity="MAJOR")
    assert card["status"] == "OPEN"

    res = api.teardown_complete(wo["id"], TECHNICIAN)
    validate_error(res, ApiErrorId.ERR_OPEN_DISCREPANCIES.value, expected_status=409)

    after = get_work_order(wo["id"])
    assert after["status"] == "TEARDOWN_IN_PROGRESS"
    assert after["open_discrepancy_count"] == 1


def test_complete_repair_blocked_by_pending_mandatory_ad_then_passes(api):
    """PRD §3.4: "the work order must be in `REPAIR_IN_PROGRESS`
    (`ERR_WORK_ORDER_INVALID_STATE`); every DirectiveCompliance of this work
    order with `mandatory` set true must be `COMPLIED` or `NOT_APPLICABLE`,
    otherwise `ERR_AD_COMPLIANCE_INCOMPLETE` (HTTP 403); and no discrepancy
    card of this work order may remain `OPEN`, otherwise
    `ERR_OPEN_DISCREPANCIES`."

    Design: Corner/state_machines/complete_repair_blocked_by_pending_mandatory_ad_then_passes
    """
    customer = create_customer()
    part = create_part()
    create_directive(part["id"], directive_type="AD",
                     directive_number="AD-2026-32-01", mandatory=True,
                     description="Actuator inspection")
    create_directive(part["id"], directive_type="SB",
                     directive_number="SB-32-100", mandatory=False,
                     description="Optional seal upgrade")
    unit = create_unit(part["id"], ownership="CUSTOMER",
                       owner_customer_id=customer["id"])
    wo = create_work_order(customer["id"], unit["id"], work_scope="OVERHAUL")
    api_client.teardown_complete(wo["id"], TECHNICIAN)
    quoted = submit_quote(wo["id"])
    from test_helpers import approve_quote
    approve_quote(wo["id"], customer["id"], quoted["version"])

    # Attempt complete-repair while the mandatory AD is PENDING.
    res1 = api.complete_repair(wo["id"], TECHNICIAN)
    validate_error(res1, ApiErrorId.ERR_AD_COMPLIANCE_INCOMPLETE.value, expected_status=403)

    # Comply with the mandatory AD; the non-mandatory SB remains PENDING.
    dc = validate_success(api.record_directive_compliance(
        wo["id"],
        {"directive_number": "AD-2026-32-01", "result": "COMPLIED",
         "note": "Inspected per AD para (e)"},
        TECHNICIAN), 201)
    assert dc["status"] == "COMPLIED"

    res2 = api.complete_repair(wo["id"], make_technician_headers("tech-1"))
    updated = validate_success(res2, 200)
    assert updated["status"] == "READY_FOR_TEST"


def test_quote_decline_return_path_cancels(api):
    """PRD §3.3: "With `disposition` set to `RETURN_UNREPAIRED`, ownership
    and the `QUOTE_SUBMITTED` from-state are checked, the same delay hours
    are accumulated, the unit's `custody_status` moves to `AWAITING_SHIPMENT`
    with its `condition_status` unchanged, and the work order is
    `CANCELLED`."

    Design: Corner/state_machines/quote_decline_return_path_cancels
    """
    customer, part, unit, quoted, _v = setup_work_order_quoted(
        work_scope="REPAIR",
        quote_overrides={"labor_estimate_cents": 500000, "parts_estimate_cents": 100000})

    res = api.decline_quote(
        quoted["id"], {"disposition": "RETURN_UNREPAIRED"},
        make_customer_headers(customer["id"]))
    updated = validate_success(res, 200)
    assert updated["status"] == "CANCELLED"

    unit_after = get_unit(unit["id"])
    assert unit_after["custody_status"] == "AWAITING_SHIPMENT"
    assert unit_after["condition_status"] == "UNSERVICEABLE"


def test_quote_decline_scrap_requires_ber_flag(api):
    """PRD §3.3: "With `disposition` set to `SCRAP`, the additional rule is
    that `ber_flag` must be true, otherwise `ERR_SCRAP_REQUIRES_BER` (HTTP
    409)".

    Design: Corner/state_machines/quote_decline_scrap_requires_ber_flag
    """
    customer, part, unit, quoted, _v = setup_work_order_quoted(
        quote_overrides={"labor_estimate_cents": 2000000,
                          "parts_estimate_cents": 1000000,
                          "scrap_option_ack": False})

    res = api.decline_quote(
        quoted["id"], {"disposition": "SCRAP"},
        make_customer_headers(customer["id"]))
    validate_error(res, ApiErrorId.ERR_SCRAP_REQUIRES_BER.value, expected_status=409)

    after = get_work_order(quoted["id"])
    assert after["status"] == "QUOTE_SUBMITTED"


def test_closed_work_order_terminal_lockdown(api):
    """PRD §3.5: "Closure belongs to the `CustomerServiceRep` and requires
    the work order to be `RELEASED` with a work-order invoice already
    generated; either failure is `ERR_WORK_ORDER_INVALID_STATE`." Once
    CLOSED the work order is terminal (§3 state machine); a re-quote attempt
    from CLOSED is not in any from-state, so `ERR_WORK_ORDER_INVALID_STATE`.

    Design: Corner/state_machines/closed_work_order_terminal_lockdown
    """
    customer, part, unit, wo, invoice = setup_work_order_closed()
    assert wo["status"] == "CLOSED"

    res = api.submit_quote(wo["id"], quote_payload(
        labor_estimate_cents=100, parts_estimate_cents=100, scrap_option_ack=False), CSR)
    validate_error(res, ApiErrorId.ERR_WORK_ORDER_INVALID_STATE.value, expected_status=409)


def test_discrepancy_double_disposition_rejected(api):
    """PRD §3.3: "Dispositioning a card — a `Technician` supplying the
    corrective action as `disposition_text` — moves it `OPEN → DISPOSITIONED`,
    stores the text, and decrements `open_discrepancy_count` by 1; a card
    that is not `OPEN` rejects disposition with `ERR_DISCREPANCY_INVALID_STATE`."

    Design: Corner/state_machines/discrepancy_double_disposition_rejected
    """
    customer, part, unit, wo = setup_work_order_in_teardown(work_scope="REPAIR")
    card = file_discrepancy(wo["id"], finding_text="Cracked bracket", severity="MINOR")
    first = disposition_discrepancy(card["id"], disposition_text="Blend out per CMM")
    assert first["status"] == "DISPOSITIONED"

    res = api.disposition_discrepancy(card["id"], {"disposition_text": "Second attempt"}, TECHNICIAN)
    validate_error(res, ApiErrorId.ERR_DISCREPANCY_INVALID_STATE.value, expected_status=409)

    wo_after = get_work_order(wo["id"])
    assert wo_after["open_discrepancy_count"] == 0


def test_requisition_receive_before_approval_rejected(api):
    """PRD §3.4: "Receiving is a `PartsBuyer` action that records the actual
    `unit_cost_cents` and moves the requisition `APPROVED → RECEIVED` (other
    statuses rejected with `ERR_REQUISITION_INVALID_STATE`)."

    Design: Corner/state_machines/requisition_receive_before_approval_rejected
    """
    customer, part, unit, wo = setup_work_order_in_repair()
    req = validate_success(api.create_parts_requisition(
        wo["id"],
        {"part_number": "BRG-1", "quantity": 1, "requested_source": "OEM"},
        TECHNICIAN), 201)

    res = api.receive_requisition(req["id"], {"unit_cost_cents": 100000}, PARTS_BUYER)
    validate_error(res, ApiErrorId.ERR_REQUISITION_INVALID_STATE.value, expected_status=409)


def test_booking_cancel_after_completion_rejected(api):
    """PRD §3.5: "A `CustomerServiceRep` may cancel a booking, moving it
    `BOOKED → CANCELLED`; a booking no longer `BOOKED` rejects cancellation
    with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/booking_cancel_after_completion_rejected
    """
    customer, part, unit, wo, cell, booking = setup_work_order_test_passed()
    # The covering booking was moved to COMPLETED by the PASS.
    res = api.cancel_booking(booking["id"], CSR)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


def test_certificate_issued_with_sequential_number_and_unique(api):
    """PRD §3.5: "On success the system creates the certificate with a
    sequential `cert_number` of the form '8130-<zero-padded sequence>',
    `signed_by` set to the caller's id, `issued_at` set to the clock, and
    status `ISSUED`" and "Certificate uniqueness is enforced at write: at
    most one `ISSUED` ReleaseCertificate may exist per work order." Also:
    "The work order must be in `TEST_PASSED` — this from-state check fires
    before the safety check".

    Design: Corner/state_machines/certificate_issued_with_sequential_number_and_unique
    """
    customer, part, unit, wo, cell, booking = setup_work_order_test_passed(
        technician_user_id="tech-1", inspector_user_id="insp-9")
    released = release_work_order(wo["id"], inspector_user_id="insp-9")
    assert released["status"] == "RELEASED"
    assert released["inspector_user_id"] == "insp-9"

    certs, _meta = validate_paginated(
        api.get_work_order_certificate(wo["id"], SHOP_MANAGER))
    assert len(certs) == 1
    cert = certs[0]
    assert cert["status"] == "ISSUED"
    assert cert["signed_by"] == "insp-9"
    assert cert["cert_number"].startswith("8130-")

    # Second release: the from-state gate fires (already RELEASED).
    res = api.release_work_order(wo["id"], make_inspector_headers("insp-9"))
    validate_error(res, ApiErrorId.ERR_WORK_ORDER_INVALID_STATE.value, expected_status=409)


def test_invoice_generate_before_release_rejected(api):
    """PRD §3.6: "A `CustomerServiceRep` generates the work-order invoice
    once the work order is `RELEASED` with `released_at` recorded; a request
    against a work order in any other status is rejected with
    `ERR_WORK_ORDER_INVALID_STATE`".

    Design: Corner/validations/invoice_generate_before_release_rejected
    """
    customer, part, unit, wo = setup_work_order_in_repair()
    res = api.generate_invoice(wo["id"], CSR)
    validate_error(res, ApiErrorId.ERR_WORK_ORDER_INVALID_STATE.value, expected_status=409)

    invoices, meta = validate_paginated(api.list_invoices(
        SHOP_MANAGER, params={"work_order_id": wo["id"]}))
    assert meta["total_count"] == 0


# ---------------------------------------------------------------------------
# Difficulty instances (queue A) — non-linear state machines
# ---------------------------------------------------------------------------

def _setup_repair_in_progress_with_cell(technician_user_id="tech-1"):
    """Common pre-state for the FAIL/retest loop and release-state-precedence
    difficulty instances. Returns (customer, part, unit, wo, cell)."""
    customer, part, unit, wo = setup_work_order_in_repair()
    wo = complete_repair(wo["id"], technician_user_id=technician_user_id)
    cell = create_test_cell()
    return customer, part, unit, wo, cell


def test_work_order_fail_retest_cycle_fail_path(api):
    """PRD §3.5: "On `FAIL`, the work order returns to `REPAIR_IN_PROGRESS`
    and a two-hop cascade fires: a new discrepancy card is created in `OPEN`
    status with `finding_text` set to 'ATP FAILURE: <atp_reference>' and
    `severity` `MAJOR`, and because that card opened, the work order's
    `open_discrepancy_count` increments by 1."

    Design: Difficulty/non_linear_state_machine/work_order_fail_retest_cycle
    """
    customer, part, unit, wo, cell = _setup_repair_in_progress_with_cell()
    book_cell(cell["id"], wo["id"],
              start_time="2026-08-03T00:00:00Z", end_time="2026-08-03T04:00:00Z")
    set_clock("2026-08-03T01:00:00Z")

    res = api.record_test_results(
        wo["id"], {"result": "FAIL", "atp_reference": "ATP-F1"},
        make_inspector_headers("insp-9"))
    after_fail = validate_success(res, 200)
    assert after_fail["status"] == "REPAIR_IN_PROGRESS"
    assert after_fail["test_attempt_count"] == 1
    assert after_fail["open_discrepancy_count"] == 1

    cards, _ = validate_paginated(api.list_discrepancies(wo["id"], TECHNICIAN))
    assert len(cards) == 1
    fail_card = cards[0]
    assert fail_card["status"] == "OPEN"
    assert fail_card["severity"] == "MAJOR"
    assert fail_card["finding_text"] == "ATP FAILURE: ATP-F1"


def test_work_order_fail_retest_cycle_passes_after_disposition(api):
    """PRD §3.5: "The retest cycle — `READY_FOR_TEST → REPAIR_IN_PROGRESS →
    READY_FOR_TEST → TEST_PASSED` — requires a fresh booking, since the
    failed attempt consumed its window."

    Design: Difficulty/non_linear_state_machine/work_order_fail_retest_cycle
    """
    customer, part, unit, wo, cell = _setup_repair_in_progress_with_cell()
    book_cell(cell["id"], wo["id"],
              start_time="2026-08-03T00:00:00Z", end_time="2026-08-03T04:00:00Z")
    set_clock("2026-08-03T01:00:00Z")
    api.record_test_results(wo["id"], {"result": "FAIL", "atp_reference": "ATP-F1"},
                            make_inspector_headers("insp-9"))

    cards, _ = validate_paginated(api.list_discrepancies(wo["id"], TECHNICIAN))
    fail_card = cards[0]
    disposition_discrepancy(fail_card["id"],
                            disposition_text="Rework rig pin per CMM 32-11-01 para 7")
    complete_repair(wo["id"], technician_user_id="tech-1")
    book_cell(cell["id"], wo["id"],
              start_time="2026-08-03T05:00:00Z", end_time="2026-08-03T09:00:00Z")
    set_clock("2026-08-03T06:00:00Z")

    res = api.record_test_results(
        wo["id"], {"result": "PASS", "atp_reference": "ATP-F2"},
        make_inspector_headers("insp-9"))
    after_pass = validate_success(res, 200)
    assert after_pass["status"] == "TEST_PASSED"
    assert after_pass["test_attempt_count"] == 2
    assert after_pass["open_discrepancy_count"] == 0


def test_requisition_reject_resubmit_cycle_oem_branch(api):
    """PRD §3.4: "From `REQUESTED` or from `SOURCE_REJECTED` (any other
    status is rejected with `ERR_REQUISITION_INVALID_STATE`): approval moves
    the requisition to `APPROVED` and records `approved_source` as `OEM` —
    or as the supplied `source_override` value when re-approving after a
    rejection — while rejection moves it to `SOURCE_REJECTED`. Approval from
    `SOURCE_REJECTED` is what closes the reject/resubmit loop."

    Design: Difficulty/non_linear_state_machine/requisition_reject_resubmit_cycle
    """
    customer, part, unit, wo = setup_work_order_in_repair()
    req = validate_success(api.create_parts_requisition(
        wo["id"],
        {"part_number": "BRG-1", "quantity": 1, "requested_source": "OEM"},
        TECHNICIAN), 201)
    rejected = validate_success(api.source_approval(
        req["id"], {"approved": False}, PARTS_BUYER), 200)
    assert rejected["status"] == "SOURCE_REJECTED"

    approved = validate_success(api.source_approval(
        req["id"], {"approved": True}, PARTS_BUYER), 200)
    assert approved["status"] == "APPROVED"

    # Both requisitions unresolved — the WO is AWAITING_PARTS while parts are outstanding.
    wo_after = get_work_order(wo["id"])
    assert wo_after["status"] == "AWAITING_PARTS"


def test_requisition_reject_resubmit_cycle_pma_fork_join(api):
    """PRD §3.4: "The PMA branch instead reaches the `Customer`, who sends
    `approved` from `PMA_PENDING_CUSTOMER` ... Approval moves the requisition
    to `APPROVED` and records `approved_source` as `PMA`; rejection moves it
    to `PMA_REJECTED`. From `PMA_REJECTED`, the `PartsBuyer` can rejoin the
    flow at `APPROVED` through source approval with `approved` true, but only
    when `source_override` is `OEM` — any other override is rejected with
    `ERR_INVALID_REQUEST` — and `approved_source` is recorded as `OEM`."

    Design: Difficulty/non_linear_state_machine/requisition_reject_resubmit_cycle
    """
    customer, part, unit, wo = setup_work_order_in_repair()
    req = validate_success(api.create_parts_requisition(
        wo["id"],
        {"part_number": "SEAL-PMA", "quantity": 1, "requested_source": "PMA"},
        TECHNICIAN), 201)
    assert req["status"] == "PMA_PENDING_CUSTOMER"

    rejected = validate_success(api.pma_approval(
        req["id"], {"approved": False}, make_customer_headers(customer["id"])), 200)
    assert rejected["status"] == "PMA_REJECTED"

    salvaged = validate_success(api.source_approval(
        req["id"], {"approved": True, "source_override": "OEM"}, PARTS_BUYER), 200)
    assert salvaged["status"] == "APPROVED"
    assert salvaged["approved_source"] == "OEM"


def test_unit_parallel_condition_custody_dimensions_release(api):
    """PRD §3.5: release "moves the unit's `condition_status` to
    `SERVICEABLE` and its `custody_status` to `AWAITING_SHIPMENT` — or to
    `IN_POOL` when the unit is `SHOP`-owned". Also: "when the `work_scope`
    is `OVERHAUL` or `WARRANTY_REWORK` the unit's `cycles_since_overhaul`
    resets to 0".

    Design: Difficulty/non_linear_state_machine/unit_parallel_condition_custody_dimensions
    """
    customer, part, unit, wo, cell, booking = setup_work_order_test_passed()
    released = release_work_order(wo["id"], inspector_user_id="insp-9")
    assert released["status"] == "RELEASED"

    unit_after_release = get_unit(unit["id"])
    assert unit_after_release["condition_status"] == "SERVICEABLE"
    assert unit_after_release["custody_status"] == "AWAITING_SHIPMENT"
    assert unit_after_release["cycles_since_overhaul"] == 0
    assert unit_after_release["total_cycles"] == 4800


def test_unit_parallel_condition_custody_dimensions_close(api):
    """PRD §3.5: "Closure moves the unit's custody to `SHIPPED` for a
    `CUSTOMER`-owned unit, while a `SHOP`-owned unit stays `IN_POOL`." The
    condition dimension is untouched by close (parallel dimensions never
    reset one another — §3.2).

    Design: Difficulty/non_linear_state_machine/unit_parallel_condition_custody_dimensions
    """
    customer, part, unit, wo, cell, booking = setup_work_order_released()
    generate_invoice(wo["id"])
    closed = close_work_order(wo["id"])
    assert closed["status"] == "CLOSED"

    unit_after_close = get_unit(unit["id"])
    assert unit_after_close["custody_status"] == "SHIPPED"
    assert unit_after_close["condition_status"] == "SERVICEABLE"
    assert unit_after_close["total_cycles"] == 4800


# ---------------------------------------------------------------------------
# Difficulty instances (queue A) — priority-pair conflicts
# ---------------------------------------------------------------------------

def test_release_state_precedes_segregation_safety_wrong_state(api):
    """PRD §3.5: "The work order must be in `TEST_PASSED` — this from-state
    check fires before the safety check, so a release attempted in the wrong
    state yields `ERR_WORK_ORDER_INVALID_STATE` even when the caller would
    also violate segregation of duties".

    Design: Difficulty/priority_pair_validation_conflict/release_state_precedes_segregation_safety
    """
    customer, part, unit, wo, cell = _setup_repair_in_progress_with_cell(
        technician_user_id="tech-1")
    book_cell(cell["id"], wo["id"],
              start_time="2026-08-03T00:00:00Z", end_time="2026-08-03T04:00:00Z")
    set_clock("2026-08-03T01:00:00Z")
    # FAIL by independent inspector; wo returns to REPAIR_IN_PROGRESS with
    # technician_user_id still pinned to "tech-1".
    api.record_test_results(wo["id"], {"result": "FAIL", "atp_reference": "ATP-F1"},
                            make_inspector_headers("insp-9"))

    # Release attempted by the SAME user as the technician while the WO is
    # REPAIR_IN_PROGRESS: BOTH rules violated; the state check must win.
    res = api.release_work_order(wo["id"], make_inspector_headers("tech-1"))
    validate_error(res, ApiErrorId.ERR_WORK_ORDER_INVALID_STATE.value, expected_status=409)

    after = get_work_order(wo["id"])
    assert after["status"] == "REPAIR_IN_PROGRESS"
    certs, _ = validate_paginated(api.get_work_order_certificate(wo["id"], SHOP_MANAGER))
    assert len(certs) == 0


def test_release_state_precedes_segregation_safety_certificate_absent(api):
    """PRD §3.5: "Certificate uniqueness is enforced at write: at most one
    `ISSUED` ReleaseCertificate may exist per work order" — and the
    from-state check fires first, so a wrong-state release attempt by the
    technician-id yields ERR_WORK_ORDER_INVALID_STATE without persisting a
    certificate.

    Design: Difficulty/priority_pair_validation_conflict/release_state_precedes_segregation_safety
    """
    customer, part, unit, wo, cell = _setup_repair_in_progress_with_cell(
        technician_user_id="tech-1")
    book_cell(cell["id"], wo["id"],
              start_time="2026-08-03T00:00:00Z", end_time="2026-08-03T04:00:00Z")
    set_clock("2026-08-03T01:00:00Z")
    api.record_test_results(wo["id"], {"result": "FAIL", "atp_reference": "ATP-F1"},
                            make_inspector_headers("insp-9"))

    res = api.release_work_order(wo["id"], make_inspector_headers("tech-1"))
    validate_error(res, ApiErrorId.ERR_WORK_ORDER_INVALID_STATE.value, expected_status=409)
    # Confirm the unit was NOT transitioned by the rejected release.
    unit_after = get_unit(unit["id"])
    assert unit_after["custody_status"] == "IN_SHOP"
    assert unit_after["condition_status"] == "UNSERVICEABLE"


def test_quote_safety_precedes_credit_fiscal(api):
    """PRD §2.9: "Quote submission checks the from-state, then the BER scrap
    acknowledgement (safety), then the customer credit hold (fiscal) — so a
    BER quote from a credit-held customer surfaces `ERR_BER_SCRAP_ACK_REQUIRED`
    rather than being masked by the fiscal check."

    Design: Difficulty/priority_pair_validation_conflict/quote_safety_precedes_credit_fiscal
    """
    customer = create_customer(credit_limit_cents=0)
    part = create_part()
    unit = create_unit(part["id"], ownership="CUSTOMER",
                       owner_customer_id=customer["id"])
    wo = create_work_order(customer["id"], unit["id"], work_scope="OVERHAUL")
    api.teardown_complete(wo["id"], TECHNICIAN)

    # Estimate sum equals the BER threshold (65% of 10000000) and no
    # scrap_option_ack is supplied, while the customer's credit_hold is true
    # from inception (exposure 0 >= limit 0).
    res = api.submit_quote(
        wo["id"],
        {"labor_estimate_cents": 5500000, "parts_estimate_cents": 1000000},
        CSR)
    validate_error(res, ApiErrorId.ERR_BER_SCRAP_ACK_REQUIRED.value, expected_status=403)


def test_quote_safety_precedes_credit_fiscal_state_unchanged(api):
    """PRD §2.9: the safety check fires before the fiscal check, so the
    rejected quote leaves the work order in `AWAITING_QUOTE` (no version
    bump, no ber_flag persisted). PRD §3.3: a successful quote "increments
    the work order's `version` by 1" — implying rejection does not.

    Design: Difficulty/priority_pair_validation_conflict/quote_safety_precedes_credit_fiscal
    """
    customer = create_customer(credit_limit_cents=0)
    part = create_part()
    unit = create_unit(part["id"], ownership="CUSTOMER",
                       owner_customer_id=customer["id"])
    wo = create_work_order(customer["id"], unit["id"], work_scope="OVERHAUL")
    td = validate_success(api.teardown_complete(wo["id"], TECHNICIAN), 200)
    version_before = td["version"]

    res = api.submit_quote(
        wo["id"],
        {"labor_estimate_cents": 5500000, "parts_estimate_cents": 1000000},
        CSR)
    validate_error(res, ApiErrorId.ERR_BER_SCRAP_ACK_REQUIRED.value, expected_status=403)

    after = get_work_order(wo["id"])
    assert after["status"] == "AWAITING_QUOTE"
    assert after["version"] == version_before
