"""Corner coverage — validations: auth, authorization, ownership, existence,
uniqueness, referential and fiscal gates (PRD 2.1, 2.7, 3.2–3.9)."""
import pytest

from test_helpers import (
    ApiErrorId, NON_EXISTENT_ID, TEST_USERS, api_client, assign_contractor,
    book_appointment, complete_appointment, create_account_payload,
    create_complaint_payload, create_contractor, create_installed_account,
    create_invoice, create_meter, create_program, create_program_payload,
    create_wave, create_work_order, fc, get_success_data,
    post_final_initial_readings, register_endpoint,
    send_and_deliver_notification, setup_filed_complaint, setup_no_access_case,
    setup_program_wave_contractor, setup_work_order_completed_visit,
    setup_work_order_created, setup_work_order_notified,
    setup_work_order_reconciled,
    setup_work_order_swapped, validate_error, validate_success,
)

PM = TEST_USERS["program_manager_headers"]
SCHED = TEST_USERS["scheduler_headers"]
CS = TEST_USERS["customer_service_headers"]
AMI = TEST_USERS["ami_operator_headers"]
AUDITOR = TEST_USERS["quality_auditor_headers"]


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or carrying a role outside
    the declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/missing_auth_headers_returns_unauthenticated
    """
    resp = api.list_programs(headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value,
                   expected_status=401)


def test_scheduler_approve_invoice_forbidden(api):
    """PRD §2.1: "A request whose role is authenticated but not permitted on
    the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §2.7: "Every request passes through the same gauntlet of checks, and
    the stages are evaluated strictly in the order given here: a failure at an
    earlier stage is the one reported, even when a later stage would also have
    failed." (role authorization is stage 2, existence stage 4)

    Design: Corner/validations/scheduler_approve_invoice_forbidden
    """
    resp = api.approve_invoice(NON_EXISTENT_ID, SCHED)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value, expected_status=403)


def test_contractor_mismatch_on_complete(api):
    """PRD §2.1: "When `X-User-Role` is `FieldContractor`, `X-User-ID` is the
    `id` of the acting `Contractor`; ownership checks on any resource that
    references a contractor compare the resource's foreign-key field —
    `Appointment.contractor_id`, `WorkOrder.contractor_id`, or
    `ContractorInvoice.contractor_id` — to `X-User-ID`, and a mismatch is
    rejected with `ERR_CONTRACTOR_MISMATCH` (HTTP 403)."

    Design: Corner/validations/contractor_mismatch_on_complete
    """
    prog, wave, contr1 = setup_program_wave_contractor()
    contr2 = create_contractor(prog["id"], name="HydroPros",
                               unit_price_cents=19000)
    ctx = setup_work_order_notified(contractor_id=contr1["id"],
                                    program=prog, wave=wave)
    appt = book_appointment(ctx["work_order"]["id"])
    # C2 does not own the appointment (copied from the work order: contr1).
    resp = api.complete_appointment(appt["id"], fc(contr2["id"]))
    validate_error(resp, ApiErrorId.ERR_CONTRACTOR_MISMATCH.value,
                   expected_status=403)
    after = get_success_data(api_client.get_appointment(appt["id"], SCHED))
    assert after["status"] == "BOOKED"


def test_cross_program_assign_rejected(api):
    """PRD §3.3: "The contractor must be `ACTIVE`
    (`ERR_CONTRACTOR_NOT_ACTIVE`) and must belong to the same program as the
    work order's wave (`ERR_CROSS_PROGRAM_REFERENCE`)."

    Design: Corner/validations/cross_program_assign_rejected
    """
    progA = create_program(name="AMI-A")
    progB = create_program(name="AMI-B", fiscal_year="FY2028")
    contr = create_contractor(progA["id"])
    waveB = create_wave(progB["id"])
    acct, oldm = create_installed_account()
    wo = create_work_order(waveB["id"], acct["id"])
    resp = api.assign_work_order(wo["id"], {
        "contractor_id": contr["id"],
        "expected_work_order_version": wo["version"]}, SCHED)
    validate_error(resp, ApiErrorId.ERR_CROSS_PROGRAM_REFERENCE.value)
    after = get_success_data(api_client.get_work_order(wo["id"], SCHED))
    assert after["contractor_id"] is None


def test_swap_reading_sequence_rejected(api):
    """PRD §3.5: "the `final_read_value` must be no less than the account's
    `last_billed_read_value` (`ERR_READING_SEQUENCE_INVALID`); and the
    `initial_read_value` must not exceed one CCF, the factory ceiling for a
    new register (`ERR_READING_SEQUENCE_INVALID`)."

    Design: Corner/validations/swap_reading_sequence_rejected
    """
    prog, wave, contr = setup_program_wave_contractor(
        budget_total_cents=1000000, target_meter_count=100)
    ctx = setup_work_order_completed_visit(contr["id"], program=prog, wave=wave,
                                           account_overrides={
                                               "last_billed_read_value": 1000,
                                               "last_billed_read_at": "2026-04-01T00:00:00Z"})
    newm = create_meter(technology="AMI")
    wo = ctx["work_order"]
    # Arm 1: final 900 < last billed 1000.
    resp = api.swap_work_order(wo["id"], {
        "expected_work_order_version": wo["version"],
        "new_meter_id": newm["id"], "final_read_value": 900,
        "initial_read_value": 0}, fc(contr["id"]))
    validate_error(resp, ApiErrorId.ERR_READING_SEQUENCE_INVALID.value)
    # Arm 2: initial 2 > factory ceiling 1.
    resp = api.swap_work_order(wo["id"], {
        "expected_work_order_version": wo["version"],
        "new_meter_id": newm["id"], "final_read_value": 1060,
        "initial_read_value": 2}, fc(contr["id"]))
    validate_error(resp, ApiErrorId.ERR_READING_SEQUENCE_INVALID.value)
    after = get_success_data(api_client.get_work_order(wo["id"], SCHED))
    assert after["lifecycle_status"] == "SCHEDULED"


def test_reconcile_without_readings_rejected(api):
    """PRD §3.5: "Reconciliation, again by the assigned `FieldContractor` with
    `expected_work_order_version`, requires those two readings to exist
    (`ERR_RECONCILE_READINGS_INCOMPLETE`) and moves the work order `SWAPPED` →
    `RECONCILED`."

    Design: Corner/validations/reconcile_without_readings_rejected
    """
    prog, wave, contr = setup_program_wave_contractor(
        budget_total_cents=1000000, target_meter_count=100)
    ctx = setup_work_order_swapped(contr["id"], program=prog, wave=wave)
    wo = ctx["work_order"]
    resp = api.reconcile_work_order(wo["id"], {
        "expected_work_order_version": wo["version"]}, fc(contr["id"]))
    validate_error(resp, ApiErrorId.ERR_RECONCILE_READINGS_INCOMPLETE.value)
    post_final_initial_readings(wo["id"], ctx["old_meter"]["id"],
                                ctx["new_meter"]["id"], contr["id"])
    resp = api.reconcile_work_order(wo["id"], {
        "expected_work_order_version": wo["version"]}, fc(contr["id"]))
    data = validate_success(resp)
    assert data["lifecycle_status"] == "RECONCILED"


def test_second_open_complaint_rejected(api):
    """PRD §3.8: "no other open complaint may exist on the work order
    (`ERR_OPEN_COMPLAINT_EXISTS`)"

    Design: Corner/validations/second_open_complaint_rejected
    """
    prog, wave, contr = setup_program_wave_contractor()
    ctx = setup_work_order_swapped(contr["id"])
    cmp = setup_filed_complaint(ctx, claimed_bill_cents=16800,
                                baseline_bill_cents=12000)
    resp = api.create_complaint(
        create_complaint_payload(
            ctx["account"]["id"], ctx["work_order"]["id"],
            claimed_bill_cents=20000, baseline_bill_cents=12000), CS)
    validate_error(resp, ApiErrorId.ERR_OPEN_COMPLAINT_EXISTS.value,
                   expected_status=409)
    after = get_success_data(api_client.get_complaint(cmp["id"], CS))
    assert after["status"] == "FILED"


def test_wave_capacity_exceeded(api):
    """PRD §3.3: "Creation requires the program `ACTIVE`
    (`ERR_PROGRAM_NOT_ACTIVE`), the wave's `committed_count` still below its
    `capacity` (`ERR_WAVE_CAPACITY_EXCEEDED`), and no other open work order —
    one whose `lifecycle_status` is neither `CLOSED` nor `CANCELLED` — on the
    account (`ERR_ACCOUNT_ALREADY_IN_PROGRAM`)."

    Design: Corner/validations/wave_capacity_exceeded
    """
    prog = create_program(budget_total_cents=1000000, target_meter_count=100)
    wave = create_wave(prog["id"], capacity=1)
    acct1, _ = create_installed_account()
    create_work_order(wave["id"], acct1["id"])
    acct2, _ = create_installed_account()
    resp = api.create_work_order(
        {"wave_id": wave["id"], "service_account_id": acct2["id"]}, SCHED)
    validate_error(resp, ApiErrorId.ERR_WAVE_CAPACITY_EXCEEDED.value)
    w = get_success_data(api_client.get_wave(wave["id"], PM))
    assert w["committed_count"] == 1


def test_account_already_in_program(api):
    """PRD §3.3: "Creation requires the program `ACTIVE`
    (`ERR_PROGRAM_NOT_ACTIVE`), the wave's `committed_count` still below its
    `capacity` (`ERR_WAVE_CAPACITY_EXCEEDED`), and no other open work order —
    one whose `lifecycle_status` is neither `CLOSED` nor `CANCELLED` — on the
    account (`ERR_ACCOUNT_ALREADY_IN_PROGRAM`)."

    Design: Corner/validations/account_already_in_program
    """
    prog = create_program(budget_total_cents=1000000, target_meter_count=100)
    wave = create_wave(prog["id"], capacity=10)
    acct, _ = create_installed_account()
    create_work_order(wave["id"], acct["id"])
    resp = api.create_work_order(
        {"wave_id": wave["id"], "service_account_id": acct["id"]}, SCHED)
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_ALREADY_IN_PROGRAM.value,
                   expected_status=409)


def test_appointment_slot_past_rejected(api):
    """PRD §3.4: "The `slot_date` must not be earlier than the current
    logical-clock date (`ERR_APPOINTMENT_SLOT_PAST`)."

    Design: Corner/validations/appointment_slot_past_rejected
    """
    prog, wave, contr = setup_program_wave_contractor(
        budget_total_cents=1000000, target_meter_count=100)
    # Delivered 2026-04-25 -> eligible 2026-04-28; clock sits at the startup
    # default 2026-05-01, so a 2026-04-30 slot is notice-valid but in the past.
    ctx = setup_work_order_created(contractor_id=contr["id"], program=prog,
                                   wave=wave)
    send_and_deliver_notification(ctx["work_order"]["id"],
                                  delivered_at="2026-04-25T10:00:00Z")
    wo = get_success_data(api_client.get_work_order(ctx["work_order"]["id"], SCHED))
    resp = api.create_appointment({
        "work_order_id": wo["id"], "slot_date": "2026-04-30", "window": "AM",
        "expected_work_order_version": wo["version"]}, SCHED)
    validate_error(resp, ApiErrorId.ERR_APPOINTMENT_SLOT_PAST.value)
    after = get_success_data(api_client.get_work_order(wo["id"], SCHED))
    assert after["lifecycle_status"] == "NOTIFIED"


def test_critical_account_requires_certified_channel(api):
    """PRD §3.4: "among the work order's notifications in `DELIVERED` status,
    the qualifying ones — for a `CRITICAL`-tier account, only `CERTIFIED_MAIL`
    deliveries qualify; for other tiers, every delivered notification
    qualifies" and "Booking a `CRITICAL` account without any `DELIVERED`
    `CERTIFIED_MAIL` notification is refused outright with
    `ERR_CRITICAL_CHANNEL_REQUIRED`."

    Design: Corner/validations/critical_account_requires_certified_channel
    """
    prog, wave, contr = setup_program_wave_contractor(
        budget_total_cents=1000000, target_meter_count=100)
    ctx = setup_work_order_created(contractor_id=contr["id"], program=prog,
                                   wave=wave,
                                   account_overrides={
                                       "meter_location": "INSIDE",
                                       "priority_tier": "CRITICAL"})
    wo_id = ctx["work_order"]["id"]
    # USPS delivery moves the work order to NOTIFIED but does not qualify.
    send_and_deliver_notification(wo_id, channel="USPS_MAIL",
                                  delivered_at="2026-04-25T10:00:00Z")
    wo = get_success_data(api_client.get_work_order(wo_id, SCHED))
    assert wo["lifecycle_status"] == "NOTIFIED"
    resp = api.create_appointment({
        "work_order_id": wo_id, "slot_date": "2026-05-06", "window": "AM",
        "expected_work_order_version": wo["version"]}, SCHED)
    validate_error(resp, ApiErrorId.ERR_CRITICAL_CHANNEL_REQUIRED.value)
    # After a CERTIFIED_MAIL delivery, booking succeeds.
    send_and_deliver_notification(wo_id, channel="CERTIFIED_MAIL",
                                  delivered_at="2026-05-02T10:00:00Z")
    wo = get_success_data(api_client.get_work_order(wo_id, SCHED))
    resp = api.create_appointment({
        "work_order_id": wo_id, "slot_date": "2026-05-06", "window": "AM",
        "expected_work_order_version": wo["version"]}, SCHED)
    appt = validate_success(resp, expected_status=201)
    assert appt["status"] == "BOOKED"


def test_endpoint_serial_conflict_on_replace(api):
    """PRD §3.6: "A `COMM_FAILED` endpoint is replaced by the `AmiOperator`
    supplying a `new_endpoint_serial`, which must also be globally unique
    (`ERR_AMI_ENDPOINT_SERIAL_CONFLICT`)."

    Design: Corner/validations/endpoint_serial_conflict_on_replace
    """
    prog, wave, contr = setup_program_wave_contractor(
        budget_total_cents=1000000, target_meter_count=100)
    ctx = setup_work_order_reconciled(contr["id"], program=prog, wave=wave)
    reg = register_endpoint(ctx["work_order"]["id"], endpoint_serial="EP-DUP")
    # 0 in-window reads -> COMM_FAILED (the precondition for replace).
    failed = validate_success(api.verify_endpoint_registration(reg["id"], AMI))
    assert failed["status"] == "COMM_FAILED"
    resp = api.replace_endpoint_registration(
        reg["id"], {"new_endpoint_serial": "EP-DUP"}, AMI)
    validate_error(resp, ApiErrorId.ERR_AMI_ENDPOINT_SERIAL_CONFLICT.value,
                   expected_status=409)
    after = get_success_data(api_client.get_endpoint_registration(reg["id"], AMI))
    assert after["status"] == "COMM_FAILED"


def test_contractor_not_active_on_assign(api):
    """PRD §3.2: "While a contractor is `SUSPENDED`, assigning it to a work
    order and booking appointments against its crews are refused with
    `ERR_CONTRACTOR_NOT_ACTIVE`."

    Design: Corner/validations/contractor_not_active_on_assign
    """
    prog = create_program(budget_total_cents=1000000, target_meter_count=100)
    contr = create_contractor(prog["id"])
    get_success_data(api_client.suspend_contractor(contr["id"], PM))
    wave = create_wave(prog["id"])
    acct, _ = create_installed_account()
    wo = create_work_order(wave["id"], acct["id"])
    resp = api.assign_work_order(wo["id"], {
        "contractor_id": contr["id"],
        "expected_work_order_version": wo["version"]}, SCHED)
    validate_error(resp, ApiErrorId.ERR_CONTRACTOR_NOT_ACTIVE.value)
    after = get_success_data(api_client.get_work_order(wo["id"], SCHED))
    assert after["contractor_id"] is None


def test_invoice_period_empty_rejected(api):
    """PRD §3.9: "a period yielding zero units is refused with
    `ERR_INVOICE_PERIOD_EMPTY`."

    Design: Corner/validations/invoice_period_empty_rejected
    """
    prog = create_program(budget_total_cents=1000000, target_meter_count=100)
    contr = create_contractor(prog["id"])
    inv = create_invoice(contr["id"], period_start="2026-06-01T00:00:00Z",
                         period_end="2026-07-01T00:00:00Z")
    resp = api.submit_invoice(inv["id"], fc(contr["id"]))
    validate_error(resp, ApiErrorId.ERR_INVOICE_PERIOD_EMPTY.value)
    after = get_success_data(api_client.get_invoice(inv["id"], PM))
    assert after["status"] == "DRAFT"


def test_account_number_conflict(api):
    """PRD §3.2: "A service account is registered with its unique
    `account_number` (a duplicate is refused with
    `ERR_ACCOUNT_NUMBER_CONFLICT`)"

    Design: Corner/validations/account_number_conflict
    """
    first = create_account_payload(account_number="A-DUP",
                                   service_address="31 Test Way",
                                   customer_name="Val", customer_phone="555-0031")
    get_success_data(api_client.create_account(first, SCHED))
    second = create_account_payload(account_number="A-DUP",
                                    service_address="32 Test Way",
                                    meter_location="INSIDE",
                                    customer_name="Wes",
                                    customer_phone="555-0032")
    resp = api.create_account(second, SCHED)
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_NUMBER_CONFLICT.value,
                   expected_status=409)


def test_open_case_blocks_cancel_then_resolves(api):
    """PRD §3.4: "At most one case per work order is `OPEN` at a time, and an
    `OPEN` case blocks both cancellation and closure of the work order with
    `ERR_OPEN_NO_ACCESS_CASE`."
    PRD §3.3: "the account returns to `ELIGIBLE` if no other open work order
    remains"

    Design: Corner/validations/open_case_blocks_cancel_then_resolves
    """
    prog, wave, contr = setup_program_wave_contractor(
        contractor_overrides={"crew_capacity_per_window": 3},
        budget_total_cents=1000000, target_meter_count=100)
    ctx = setup_no_access_case(contr["id"], program=prog, wave=wave)
    resp = api.cancel_work_order(ctx["work_order"]["id"], SCHED)
    validate_error(resp, ApiErrorId.ERR_OPEN_NO_ACCESS_CASE.value,
                   expected_status=409)
    get_success_data(api_client.resolve_no_access_case(
        ctx["case"]["id"], {"resolution": "ACCESS_GAINED"}, SCHED))
    data = validate_success(api.cancel_work_order(ctx["work_order"]["id"], SCHED))
    assert data["lifecycle_status"] == "CANCELLED"
    acct = get_success_data(api_client.get_account(ctx["account"]["id"], SCHED))
    assert acct["status"] == "ELIGIBLE"


def test_stale_work_order_version_on_assign(api):
    """PRD §2.5: "If the supplied value does not match the work order's
    current `version` — because another writer has advanced the work order
    since the client last read it — the request is rejected with
    `ERR_STALE_WORK_ORDER_VERSION` (HTTP 412), preventing the client from
    acting on a stale decision basis."
    PRD §3.3: "Re-assignment is legitimate while the work order is in
    `CREATED`, `NOTIFIED`, `SCHEDULED`, or `ACCESS_FAILED`; each assignment
    reprices the work order's `committed_amount_cents` to the contractor's
    `unit_price_cents`, recomputes the program budget, and bumps the work
    order's `version`."

    Design: Corner/validations/stale_work_order_version_on_assign
    """
    prog = create_program(budget_total_cents=1000000, target_meter_count=100)
    contr1 = create_contractor(prog["id"], unit_price_cents=18500)
    contr2 = create_contractor(prog["id"], name="HydroPros",
                               unit_price_cents=19000)
    wave = create_wave(prog["id"])
    acct, _ = create_installed_account()
    wo = create_work_order(wave["id"], acct["id"])
    v1 = wo["version"]
    assigned = validate_success(api.assign_work_order(wo["id"], {
        "contractor_id": contr1["id"], "expected_work_order_version": v1}, SCHED))
    v2 = assigned["version"]
    assert v2 == v1 + 1
    resp = api.assign_work_order(wo["id"], {
        "contractor_id": contr2["id"], "expected_work_order_version": v1}, SCHED)
    validate_error(resp, ApiErrorId.ERR_STALE_WORK_ORDER_VERSION.value,
                   expected_status=412)
    # Re-read and retry with the fresh version: re-assignment is legitimate.
    reassigned = validate_success(api.assign_work_order(wo["id"], {
        "contractor_id": contr2["id"], "expected_work_order_version": v2}, SCHED))
    assert reassigned["contractor_id"] == contr2["id"]
    assert reassigned["committed_amount_cents"] == 19000


def test_complaint_account_mismatch_rejected(api):
    """PRD §3.8: "the complaint's account must be the work order's own account
    (`ERR_ACCOUNT_WORK_ORDER_MISMATCH`)"

    Design: Corner/validations/complaint_account_mismatch_rejected
    """
    prog, wave, contr = setup_program_wave_contractor()
    ctx = setup_work_order_swapped(contr["id"])
    other_acct, _ = create_installed_account()
    resp = api.create_complaint(
        create_complaint_payload(
            other_acct["id"], ctx["work_order"]["id"]), CS)
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_WORK_ORDER_MISMATCH.value)
    wo = get_success_data(api_client.get_work_order(ctx["work_order"]["id"], SCHED))
    assert wo["hold_status"] == "CLEAR"


def test_swap_legacy_new_meter_rejected(api):
    """PRD §3.5: "The new meter must be `IN_STOCK` and of `AMI` technology
    (`ERR_METER_NOT_AVAILABLE`)"

    Design: Corner/validations/swap_legacy_new_meter_rejected
    """
    prog, wave, contr = setup_program_wave_contractor(
        budget_total_cents=1000000, target_meter_count=100)
    ctx = setup_work_order_completed_visit(contr["id"], program=prog, wave=wave)
    legacynew = create_meter(technology="LEGACY")
    wo = ctx["work_order"]
    resp = api.swap_work_order(wo["id"], {
        "expected_work_order_version": wo["version"],
        "new_meter_id": legacynew["id"], "final_read_value": 1060,
        "initial_read_value": 0}, fc(contr["id"]))
    validate_error(resp, ApiErrorId.ERR_METER_NOT_AVAILABLE.value)
    after = get_success_data(api_client.get_work_order(wo["id"], SCHED))
    assert after["lifecycle_status"] == "SCHEDULED"
    meter = get_success_data(api_client.get_meter(legacynew["id"], SCHED))
    assert meter["status"] == "IN_STOCK"


def test_invoice_approve_over_budget_rejected(api):
    """PRD §3.9: "Approval requires the invoice's `net_amount_cents` to be no
    greater than the program's `budget_available_cents`, with equality allowed
    — a shortfall is refused with `ERR_BUDGET_AVAILABLE_EXCEEDED` — and on
    approval the invoice moves `SUBMITTED` → `APPROVED`, its net is added into
    the program's `budget_spent_cents`, and the budget posture is recomputed."

    Design: Corner/validations/invoice_approve_over_budget_rejected
    """
    from test_helpers import setup_work_order_closed
    prog = create_program(name="AMI-TINY", budget_total_cents=17000,
                          target_meter_count=100)
    contr = create_contractor(prog["id"], unit_price_cents=18500)
    wave = create_wave(prog["id"])
    ctx = setup_work_order_closed(contr["id"], program=prog, wave=wave)
    inv = create_invoice(contr["id"])
    get_success_data(api_client.submit_invoice(inv["id"], fc(contr["id"])))
    # Frozen net 17945 > budget_available 17000.
    resp = api.approve_invoice(inv["id"], PM)
    validate_error(resp, ApiErrorId.ERR_BUDGET_AVAILABLE_EXCEEDED.value)
    after = get_success_data(api_client.get_invoice(inv["id"], PM))
    assert after["status"] == "SUBMITTED"
    p = get_success_data(api_client.get_program(prog["id"], PM))
    assert p["budget_spent_cents"] == 0
