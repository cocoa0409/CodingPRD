"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build the full precondition chains — from
an active program with a contractor through a closed, invoiced work order —
out of PRD-declared endpoints only. All setup calls go through
get_success_data() so failures surface as clear "Setup failed" errors.

Time model: accounts carry last_billed_read_at 2026-04-15 by default; the
startup clock is 2026-05-01T00:00:00Z; the canonical swap clock is
2026-05-06T09:00:00Z (21 whole days after the last billed read).
"""
import itertools

from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import api_client
from .constants import TEST_DEFAULTS
from .test_users import TEST_USERS, make_field_contractor_headers

_wave_counter = itertools.count(1)

PM = TEST_USERS["program_manager_headers"]
SCHED = TEST_USERS["scheduler_headers"]
AUDITOR = TEST_USERS["quality_auditor_headers"]
AMI = TEST_USERS["ami_operator_headers"]
CS = TEST_USERS["customer_service_headers"]

DEFAULT_SLOT_DATE = TEST_DEFAULTS["SLOT_DATE"]  # 2026-05-06
DEFAULT_CLOCK_ON_SLOT = TEST_DEFAULTS["SWAP_CLOCK"]  # 2026-05-06T09:00:00Z
DEFAULT_READ_AT = TEST_DEFAULTS["READ_AT"]  # 2026-05-06T09:30:00Z


def fc(contractor_id: str) -> dict:
    """Entity-backed FieldContractor headers for ownership-gated calls."""
    return make_field_contractor_headers(contractor_id)


def create_program(active=True, **overrides) -> dict:
    """Create a program; activate it unless active=False."""
    prog = get_success_data(api_client.create_program(
        factories.create_program_payload(**overrides), PM))
    if active:
        prog = get_success_data(api_client.activate_program(prog["id"], PM))
    return prog


def create_contractor(program_id: str, **overrides) -> dict:
    """Onboard a contractor (program must be ACTIVE)."""
    return get_success_data(api_client.create_contractor(
        factories.create_contractor_payload(program_id, **overrides), PM))


def create_account(**overrides) -> dict:
    """Register a service account (ELIGIBLE)."""
    return get_success_data(api_client.create_account(
        factories.create_account_payload(**overrides), SCHED))


def create_meter(**overrides) -> dict:
    """Register a meter (IN_STOCK)."""
    return get_success_data(api_client.create_meter(
        factories.create_meter_payload(**overrides), SCHED))


def create_installed_account(last_billed_read_value=TEST_DEFAULTS["LAST_BILLED_READ_VALUE"],
                             **account_overrides):
    """Account + legacy meter INSTALLED on it. Returns (account, meter)."""
    acct = create_account(last_billed_read_value=last_billed_read_value, **account_overrides)
    oldm = create_meter(technology="LEGACY")
    get_success_data(api_client.install_meter(oldm["id"], {
        "service_account_id": acct["id"],
        "initial_read_value": last_billed_read_value,
        "installed_at": TEST_DEFAULTS["LEGACY_INSTALLED_AT"],
    }, SCHED))
    return acct, get_success_data(api_client.get_meter(oldm["id"], SCHED))


def create_wave(program_id: str, open_it=True, **overrides) -> dict:
    """Create a wave (DRAFT); open it unless open_it=False. When the caller
    does not pin wave_number/window, defaults are derived from a monotonic
    counter so repeated waves in the same program never collide on
    wave_number and never overlap windows."""
    if "wave_number" not in overrides:
        k = next(_wave_counter)
        overrides["wave_number"] = k
        if "window_start" not in overrides and "window_end" not in overrides:
            m = 1 + (k - 1) % 12
            y = 2026 + (k - 1) // 12
            m2 = m % 12 + 1
            y2 = y + (1 if m == 12 else 0)
            overrides["window_start"] = f"{y:04d}-{m:02d}-01T00:00:00Z"
            overrides["window_end"] = f"{y2:04d}-{m2:02d}-01T00:00:00Z"
    wave = get_success_data(api_client.create_wave(
        factories.create_wave_payload(program_id, **overrides), PM))
    if open_it:
        wave = get_success_data(api_client.open_wave(wave["id"], PM))
    return wave


def create_work_order(wave_id: str, account_id: str) -> dict:
    """Create a work order in an OPEN wave. Captures the account's INSTALLED
    meter as old_meter_id and commits the program default allowance."""
    return get_success_data(api_client.create_work_order(
        factories.create_work_order_payload(wave_id, account_id), SCHED))


def assign_contractor(work_order_id: str, contractor_id: str) -> dict:
    """Assign a contractor (OCC: reads current version first)."""
    wo = get_success_data(api_client.get_work_order(work_order_id, SCHED))
    return get_success_data(api_client.assign_work_order(
        work_order_id,
        {"contractor_id": contractor_id, "expected_work_order_version": wo["version"]},
        SCHED))


def send_and_deliver_notification(work_order_id: str, channel="USPS_MAIL",
                                  delivered_at=TEST_DEFAULTS["DELIVERED_AT"]) -> dict:
    """Create a notification and confirm DELIVERED. The first DELIVERED
    notification moves the work order CREATED -> NOTIFIED."""
    notif = get_success_data(api_client.create_notification(
        factories.create_notification_payload(work_order_id, channel=channel), SCHED))
    return get_success_data(api_client.confirm_delivery(
        notif["id"],
        factories.confirm_delivery_payload(outcome="DELIVERED", delivered_at=delivered_at),
        SCHED))


def book_appointment(work_order_id: str, slot_date=DEFAULT_SLOT_DATE, window="AM") -> dict:
    """Book an appointment (OCC: reads current version first)."""
    wo = get_success_data(api_client.get_work_order(work_order_id, SCHED))
    return get_success_data(api_client.create_appointment(
        factories.create_appointment_payload(
            work_order_id, wo["version"], slot_date=slot_date, window=window),
        SCHED))


def complete_appointment(appointment_id: str, contractor_id: str) -> dict:
    return get_success_data(api_client.complete_appointment(
        appointment_id, fc(contractor_id)))


def no_access(appointment_id: str, contractor_id: str) -> dict:
    return get_success_data(api_client.no_access_appointment(
        appointment_id, fc(contractor_id)))


def swap_work_order(work_order_id: str, new_meter_id: str,
                    contractor_id: str,
                    final_read_value=TEST_DEFAULTS["SWAP_FINAL_READ"],
                    initial_read_value=TEST_DEFAULTS["SWAP_INITIAL_READ"]) -> dict:
    """Record the swap (OCC: reads current version first)."""
    wo = get_success_data(api_client.get_work_order(work_order_id, SCHED))
    return get_success_data(api_client.swap_work_order(
        work_order_id, {
            "expected_work_order_version": wo["version"],
            "new_meter_id": new_meter_id,
            "final_read_value": final_read_value,
            "initial_read_value": initial_read_value,
        }, fc(contractor_id)))


def post_final_initial_readings(work_order_id: str, old_meter_id: str, new_meter_id: str,
                                contractor_id: str,
                                final_read_value=TEST_DEFAULTS["SWAP_FINAL_READ"],
                                initial_read_value=TEST_DEFAULTS["SWAP_INITIAL_READ"],
                                read_at=DEFAULT_READ_AT):
    """Append the FINAL (old meter) and INITIAL (new meter) readings required
    before reconcile."""
    get_success_data(api_client.create_reading(
        factories.create_reading_payload(
            work_order_id, old_meter_id, read_type="FINAL",
            value=final_read_value, read_at=read_at),
        fc(contractor_id)))
    get_success_data(api_client.create_reading(
        factories.create_reading_payload(
            work_order_id, new_meter_id, read_type="INITIAL",
            value=initial_read_value, read_at=read_at),
        fc(contractor_id)))


def reconcile_work_order(work_order_id: str, contractor_id: str) -> dict:
    wo = get_success_data(api_client.get_work_order(work_order_id, SCHED))
    return get_success_data(api_client.reconcile_work_order(
        work_order_id, {"expected_work_order_version": wo["version"]}, fc(contractor_id)))


def register_endpoint(work_order_id: str, endpoint_serial=None) -> dict:
    payload = factories.create_endpoint_registration_payload(work_order_id)
    if endpoint_serial is not None:
        payload["endpoint_serial"] = endpoint_serial
    return get_success_data(api_client.create_endpoint_registration(payload, AMI))


def ingest_reads(registration_id: str, count: int, rssi_dbm=-90, read_ats=None):
    """Ingest `count` AMI reads at the given rssi / times."""
    if read_ats is None:
        read_ats = [f"2026-05-0{6 + (i // 2)}T{12 if i % 2 == 0 else 18}:00:00Z"
                    for i in range(count)]
    for i in range(count):
        get_success_data(api_client.ingest_ami_read(
            factories.ingest_read_payload(
                registration_id, rssi_dbm=rssi_dbm, read_at=read_ats[i]), AMI))


def verify_registration(registration_id: str) -> dict:
    return get_success_data(api_client.verify_endpoint_registration(registration_id, AMI))


def setup_program_with_wave(**program_overrides):
    """ACTIVE program + OPEN wave. Returns (program, wave)."""
    prog = create_program(**program_overrides)
    wave = create_wave(prog["id"])
    return prog, wave


def setup_program_wave_contractor(contractor_overrides=None, **program_overrides):
    """ACTIVE program + OPEN wave + ACTIVE contractor.
    Returns (program, wave, contractor)."""
    prog = create_program(**program_overrides)
    wave = create_wave(prog["id"])
    contr = create_contractor(prog["id"], **(contractor_overrides or {}))
    return prog, wave, contr


def setup_work_order_created(contractor_id=None, account_overrides=None,
                             program_overrides=None, program=None, wave=None):
    """Program ACTIVE + wave OPEN + account with INSTALLED legacy meter +
    work order CREATED (assigned when contractor_id given). Pass `program`
    (and optionally `wave`) to reuse an existing program instead of creating
    a fresh default one. When only `contractor_id` is given, the new work
    order's program is anchored to that contractor's program so the
    assignment satisfies the same-program rule.
    Returns a context dict with program, wave, account, old_meter, work_order.
    """
    if program is None and contractor_id is not None:
        contr = get_success_data(api_client.get_contractor(contractor_id, SCHED))
        program = get_success_data(api_client.get_program(contr["program_id"], SCHED))
    prog = program if program is not None else create_program(**(program_overrides or {}))
    wave = wave if wave is not None else create_wave(prog["id"])
    acct, oldm = create_installed_account(**(account_overrides or {}))
    wo = create_work_order(wave["id"], acct["id"])
    if contractor_id is not None:
        wo = assign_contractor(wo["id"], contractor_id)
    return {"program": prog, "wave": wave, "account": acct,
            "old_meter": oldm, "work_order": wo}


def setup_work_order_notified(contractor_id=None, slot_ready=False, **kwargs):
    """Like setup_work_order_created plus a DELIVERED notification
    (work order NOTIFIED). Optionally books the first appointment when
    slot_ready=True. Returns the context dict (plus 'appointment' when booked).
    """
    ctx = setup_work_order_created(contractor_id=contractor_id, **kwargs)
    ctx["notification"] = send_and_deliver_notification(ctx["work_order"]["id"])
    ctx["work_order"] = get_success_data(
        api_client.get_work_order(ctx["work_order"]["id"], SCHED))
    if slot_ready:
        ctx["appointment"] = book_appointment(ctx["work_order"]["id"])
        ctx["work_order"] = get_success_data(
            api_client.get_work_order(ctx["work_order"]["id"], SCHED))
    return ctx


def setup_work_order_scheduled(contractor_id: str, slot_date=DEFAULT_SLOT_DATE,
                               window="AM", clock=DEFAULT_CLOCK_ON_SLOT,
                               **kwargs):
    """Work order SCHEDULED: created, assigned, notified, appointment BOOKED;
    clock advanced to the slot date. Returns context with appointment."""
    ctx = setup_work_order_notified(contractor_id=contractor_id, **kwargs)
    appt = book_appointment(ctx["work_order"]["id"], slot_date=slot_date, window=window)
    if clock is not None:
        get_success_data(api_client.set_clock(clock, PM))
    ctx["appointment"] = appt
    ctx["work_order"] = get_success_data(
        api_client.get_work_order(ctx["work_order"]["id"], SCHED))
    return ctx


def setup_work_order_completed_visit(contractor_id: str, slot_date=DEFAULT_SLOT_DATE,
                                     window="AM", clock=DEFAULT_CLOCK_ON_SLOT,
                                     **kwargs):
    """SCHEDULED + appointment COMPLETED (ready to swap)."""
    ctx = setup_work_order_scheduled(contractor_id, slot_date=slot_date,
                                     window=window, clock=clock, **kwargs)
    complete_appointment(ctx["appointment"]["id"], contractor_id)
    ctx["work_order"] = get_success_data(
        api_client.get_work_order(ctx["work_order"]["id"], SCHED))
    return ctx


def setup_work_order_swapped(contractor_id: str, new_meter=None,
                             final_read_value=TEST_DEFAULTS["SWAP_FINAL_READ"],
                             initial_read_value=TEST_DEFAULTS["SWAP_INITIAL_READ"],
                             with_readings=False, **kwargs):
    """Work order SWAPPED. Adds a fresh IN_STOCK AMI meter unless new_meter
    given. Optionally posts FINAL+INITIAL readings. Returns context with
    new_meter; work_order refreshed."""
    ctx = setup_work_order_completed_visit(contractor_id, **kwargs)
    if new_meter is None:
        new_meter = create_meter(technology="AMI")
    wo = swap_work_order(ctx["work_order"]["id"], new_meter["id"], contractor_id,
                         final_read_value=final_read_value,
                         initial_read_value=initial_read_value)
    ctx["new_meter"] = new_meter
    ctx["work_order"] = wo
    if with_readings:
        post_final_initial_readings(wo["id"], ctx["old_meter"]["id"], new_meter["id"],
                                    contractor_id,
                                    final_read_value=final_read_value,
                                    initial_read_value=initial_read_value)
    return ctx


def setup_work_order_reconciled(contractor_id: str, new_meter=None, **kwargs):
    """Work order RECONCILED (swap + FINAL/INITIAL readings + reconcile)."""
    ctx = setup_work_order_swapped(contractor_id, new_meter=new_meter,
                                   with_readings=True, **kwargs)
    ctx["work_order"] = reconcile_work_order(ctx["work_order"]["id"], contractor_id)
    return ctx


def setup_work_order_qa_review(contractor_id: str, endpoint_serial=None, **kwargs):
    """Work order RECONCILED -> AMI_VERIFIED -> QA_REVIEW via endpoint
    registration with 4 passing reads (-90 dBm) and verify.
    Returns context with 'registration'."""
    ctx = setup_work_order_reconciled(contractor_id, **kwargs)
    reg = register_endpoint(ctx["work_order"]["id"], endpoint_serial=endpoint_serial)
    ingest_reads(reg["id"], 4, rssi_dbm=-90)
    ctx["registration"] = verify_registration(reg["id"])
    ctx["work_order"] = get_success_data(
        api_client.get_work_order(ctx["work_order"]["id"], SCHED))
    return ctx


def setup_work_order_closed(contractor_id: str, **kwargs):
    """Work order QA_REVIEW -> CLOSED. Requires no PENDING audit: callers must
    not leave a SAMPLED audit pending on this work order (sampling fires on
    every 5th QA_REVIEW entry of the contractor)."""
    ctx = setup_work_order_qa_review(contractor_id, **kwargs)
    ctx["work_order"] = get_success_data(
        api_client.close_work_order(ctx["work_order"]["id"], SCHED))
    return ctx


def setup_no_access_case(contractor_id: str, account_overrides=None,
                         program_overrides=None, **kwargs):
    """Work order ACCESS_FAILED with exactly 3 strikes and the auto-created
    OPEN NoAccessCase at STAGE_1_DOOR_HANGER (stage notification still SENT).
    Extra kwargs (e.g. program=..., wave=...) forward to the work-order setup
    chain. Returns context with 'case' and 'appointments'."""
    account_overrides = dict(account_overrides or {})
    account_overrides.setdefault("meter_location", "INSIDE")
    ctx = setup_work_order_notified(
        contractor_id=contractor_id,
        account_overrides=account_overrides,
        program_overrides=program_overrides,
        **kwargs)
    appointments = []
    for i, day in enumerate(("2026-05-06", "2026-05-07", "2026-05-08")):
        appt = book_appointment(ctx["work_order"]["id"], slot_date=day)
        no_access(appt["id"], contractor_id)
        appointments.append(appt)
    cases, meta = _list_cases(ctx["work_order"]["id"])
    assert meta["total_count"] == 1, "Setup failed: expected exactly one no-access case"
    ctx["appointments"] = appointments
    ctx["case"] = cases[0]
    ctx["work_order"] = get_success_data(
        api_client.get_work_order(ctx["work_order"]["id"], SCHED))
    return ctx


def _list_cases(work_order_id):
    from prd_bench_local_runner.testing import validate_paginated
    resp = api_client.list_no_access_cases(SCHED, params={"work_order_id": work_order_id})
    return validate_paginated(resp)


def record_for_cause_fail(work_order_id: str, contractor_id: str,
                          checks_total=10, checks_passed=9, defects_found=1) -> dict:
    """Create a FOR_CAUSE audit on a QA_REVIEW/QA_FAILED work order and record
    it FAIL. Returns the recorded audit. (Work order moves to QA_FAILED.)"""
    audit = get_success_data(api_client.create_quality_audit(
        factories.create_quality_audit_payload(work_order_id), AUDITOR))
    return get_success_data(api_client.record_quality_audit(
        audit["id"], factories.record_audit_payload(
            checks_total=checks_total, checks_passed=checks_passed,
            defects_found=defects_found), AUDITOR))


def submit_rework(work_order_id: str, contractor_id: str) -> dict:
    """QA_FAILED -> QA_REVIEW (OCC: reads current version first)."""
    wo = get_success_data(api_client.get_work_order(work_order_id, SCHED))
    return get_success_data(api_client.submit_rework(
        work_order_id, {"expected_work_order_version": wo["version"]}, fc(contractor_id)))


def create_invoice(contractor_id: str,
                   period_start=TEST_DEFAULTS["INVOICE_PERIOD_START"],
                   period_end=TEST_DEFAULTS["INVOICE_PERIOD_END"]) -> dict:
    return get_success_data(api_client.create_invoice(
        factories.create_invoice_payload(
            contractor_id, period_start=period_start, period_end=period_end),
        fc(contractor_id)))


def setup_filed_complaint(ctx: dict, claimed_bill_cents=16800, baseline_bill_cents=12000,
                          triage=False):
    """File a complaint against the context's swapped work order. Sets the
    work order hold ON_HOLD. Returns the complaint."""
    cmp = get_success_data(api_client.create_complaint(
        factories.create_complaint_payload(
            ctx["account"]["id"], ctx["work_order"]["id"],
            claimed_bill_cents=claimed_bill_cents,
            baseline_bill_cents=baseline_bill_cents), CS))
    if triage:
        cmp = get_success_data(api_client.triage_complaint(cmp["id"], CS))
    return cmp
