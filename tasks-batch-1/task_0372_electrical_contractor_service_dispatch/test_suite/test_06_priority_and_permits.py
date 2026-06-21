"""Validation precedence under dual-failure, plus permit-gated billing corners.

Queue A (Difficulty): priority_pair_validation_conflict.
Queue B (Corner): permit valid path, single-invoice, warranty-coverage gate,
existence-before-state precedence.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    make_customer_headers, make_technician_headers,
    make_customer, make_technician, make_job, current_job_version,
    quote_and_accept, dispatch_tech, depart_and_arrive, complete_job, invoice_job,
    setup_permit_passed, set_clock,
)

DISP = TEST_USERS["dispatcher_headers"]
INSP = TEST_USERS["inspector_headers"]


# ─── Queue A: priority_pair_validation_conflict ───────────────────────────
def test_priority_invalid_state_beats_permit_safety(api):
    """PRD §2.6: "first authentication ... then state-transition legality
    (`ERR_INVALID_STATE`); and finally the domain-specific business checks (license,
    on-call, zone, double-booking, permit, stock, single-invoice, open-callback,
    warranty-coverage, and uniqueness). A request that fails an earlier check is rejected
    with that check's error before any later check is considered."

    Design: Difficulty/priority_pair_validation_conflict/priority_conflict_invalid_state_beats_permit_safety
    """
    cust = make_customer(email="pv1@x.com", service_zip="60001")
    tech = make_technician(service_zone="600", license_class="MASTER", hourly_rate_cents=10000)
    job = make_job(cust["id"], scope="PANEL", job_class="INSTALL")
    quote_and_accept(job["id"], cust["id"], pricing_mode="FLAT_RATE", flat_rate_cents=50000)
    setup_permit_passed(job["id"], inspection_at="2026-07-10T09:00:00Z")
    disp = dispatch_tech(job["id"], tech["id"], "2026-07-10T10:00:00Z", "2026-07-10T11:00:00Z")
    depart_and_arrive(disp["id"], tech["id"])
    complete_job(job["id"], tech["id"])  # job now COMPLETED, permit PASSED

    # second /complete: job not IN_PROGRESS (state, prio 7) — wins over permit gate (prio 12)
    resp = api.complete_service_job(job["id"], {}, make_technician_headers(tech["id"]))
    err = validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    assert err["error_id"] != ApiErrorId.ERR_PERMIT_NOT_PASSED.value


def test_priority_permit_gate_fires_when_state_is_valid(api):
    """PRD §2.6: "then state-transition legality (`ERR_INVALID_STATE`); and finally the
    domain-specific business checks (license, on-call, zone, double-booking, permit, ...)."
    PRD §3.5: "attempting to complete a permitted job whose permit has not passed is rejected
    with `ERR_PERMIT_NOT_PASSED`."

    Design: Difficulty/priority_pair_validation_conflict/priority_conflict_invalid_state_beats_permit_safety
    """
    cust = make_customer(email="pv1b@x.com", service_zip="60002")
    tech = make_technician(service_zone="600", license_class="MASTER", hourly_rate_cents=10000)
    job = make_job(cust["id"], scope="PANEL", job_class="INSTALL")
    quote_and_accept(job["id"], cust["id"], pricing_mode="FLAT_RATE", flat_rate_cents=50000)
    from test_helpers import file_permit, issue_permit, schedule_inspection
    permit = file_permit(job["id"], jurisdiction="City", permit_number="PV1B-PN")
    issue_permit(permit["id"])
    schedule_inspection(permit["id"], "2026-07-10T09:00:00Z")  # permit only INSPECTION_SCHEDULED
    disp = dispatch_tech(job["id"], tech["id"], "2026-07-10T10:00:00Z", "2026-07-10T11:00:00Z")
    depart_and_arrive(disp["id"], tech["id"])
    # job IS IN_PROGRESS (state check passes), so the next check — permit gate — fires.
    resp = api.complete_service_job(job["id"], {}, make_technician_headers(tech["id"]))
    validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_PASSED.value)


def test_priority_license_beats_double_booking(api):
    """PRD §2.6: "A request that fails an earlier check is rejected with that check's error
    before any later check is considered." (license is enumerated before double-booking in
    the business-check order.)
    PRD §3.4: "When the job's `scope` is `PANEL` or `EV_CHARGER`, the assigned technician's
    `license_class` must be `MASTER`; a `JOURNEYMAN` assigned to such work is rejected with
    `ERR_LICENSE_INSUFFICIENT`."

    Design: Difficulty/priority_pair_validation_conflict/priority_conflict_license_beats_double_booking
    """
    custA = make_customer(email="pv2a@x.com", service_zip="61001")
    custB = make_customer(email="pv2b@x.com", service_zip="61002")
    tech = make_technician(service_zone="610", license_class="JOURNEYMAN", hourly_rate_cents=10000)

    jobA = make_job(custA["id"], scope="OUTLET", job_class="SERVICE")
    quote_and_accept(jobA["id"], custA["id"], pricing_mode="FLAT_RATE", flat_rate_cents=10000)
    dispatch_tech(jobA["id"], tech["id"], "2026-07-11T09:00:00Z", "2026-07-11T10:00:00Z")  # occupies [09,10)

    jobB = make_job(custB["id"], scope="PANEL", job_class="INSTALL")  # PANEL needs MASTER
    quote_and_accept(jobB["id"], custB["id"], pricing_mode="FLAT_RATE", flat_rate_cents=50000)
    vB = current_job_version(jobB["id"])
    # JOURNEYMAN tech (license fail, prio 8) into overlapping [09:30,10:30) (overlap, prio 11)
    resp = api.create_dispatch(
        {"job_id": jobB["id"], "technician_id": tech["id"],
         "window_start": "2026-07-11T09:30:00Z", "window_end": "2026-07-11T10:30:00Z",
         "expected_job_version": vB},
        DISP,
    )
    err = validate_error(resp, ApiErrorId.ERR_LICENSE_INSUFFICIENT.value)
    assert err["error_id"] != ApiErrorId.ERR_TECH_DOUBLE_BOOKED.value


def test_priority_double_booking_fires_when_license_ok(api):
    """PRD §3.4: "The new arrival window must not overlap any existing active dispatch on the
    same technician; an overlap is rejected with `ERR_TECH_DOUBLE_BOOKED`."
    PRD §2.6: a request "is rejected with that check's error before any later check is
    considered" — with the license check satisfied, the later double-booking check fires.

    Design: Difficulty/priority_pair_validation_conflict/priority_conflict_license_beats_double_booking
    """
    custA = make_customer(email="pv2c@x.com", service_zip="61001")
    custB = make_customer(email="pv2d@x.com", service_zip="61002")
    # MASTER tech -> the license check passes for PANEL work, isolating the overlap check.
    tech = make_technician(service_zone="610", license_class="MASTER", hourly_rate_cents=10000)
    jobA = make_job(custA["id"], scope="OUTLET", job_class="SERVICE")
    quote_and_accept(jobA["id"], custA["id"], pricing_mode="FLAT_RATE", flat_rate_cents=10000)
    dispatch_tech(jobA["id"], tech["id"], "2026-07-11T09:00:00Z", "2026-07-11T10:00:00Z")  # occupies [09,10)
    jobB = make_job(custB["id"], scope="PANEL", job_class="INSTALL")
    quote_and_accept(jobB["id"], custB["id"], pricing_mode="FLAT_RATE", flat_rate_cents=50000)
    vB = current_job_version(jobB["id"])
    resp = api.create_dispatch(
        {"job_id": jobB["id"], "technician_id": tech["id"],
         "window_start": "2026-07-11T09:30:00Z", "window_end": "2026-07-11T10:30:00Z",
         "expected_job_version": vB},
        DISP,
    )
    validate_error(resp, ApiErrorId.ERR_TECH_DOUBLE_BOOKED.value)


# ─── Queue B: permit / billing corners ────────────────────────────────────
def test_already_invoiced_second_invoice_rejected(api):
    """PRD §3.7: "Invoicing is permitted only when the job is `COMPLETED` and only when no
    `Invoice` already exists for the job; attempting to invoice a job that already has one is
    rejected with `ERR_ALREADY_INVOICED`."

    Design: Corner/validations/already_invoiced_second_invoice_rejected
    """
    cust = make_customer(email="ai@x.com", service_zip="36001")
    tech = make_technician(service_zone="360", license_class="JOURNEYMAN", hourly_rate_cents=9000)
    job = make_job(cust["id"], scope="OUTLET", job_class="SERVICE")
    quote_and_accept(job["id"], cust["id"], pricing_mode="FLAT_RATE", flat_rate_cents=10000)
    disp = dispatch_tech(job["id"], tech["id"], "2026-08-13T09:00:00Z", "2026-08-13T10:00:00Z")
    depart_and_arrive(disp["id"], tech["id"])
    complete_job(job["id"], tech["id"])
    invoice_job(job["id"])
    resp = api.invoice_service_job(job["id"], DISP)
    validate_error(resp, ApiErrorId.ERR_ALREADY_INVOICED.value)


def test_not_warranty_covered_callback_after_window(api):
    """PRD §3.8: "A callback filed after the warranty window has elapsed cannot reopen the
    job and is rejected with `ERR_NOT_WARRANTY_COVERED`."

    Design: Corner/validations/not_warranty_covered_callback_after_window
    """
    set_clock("2026-08-14T08:00:00Z")
    cust = make_customer(email="nw@x.com", service_zip="38001")
    tech = make_technician(service_zone="380", license_class="JOURNEYMAN", hourly_rate_cents=9000)
    job = make_job(cust["id"], scope="OUTLET", job_class="SERVICE")
    quote_and_accept(job["id"], cust["id"], pricing_mode="FLAT_RATE", flat_rate_cents=10000)
    disp = dispatch_tech(job["id"], tech["id"], "2026-08-14T09:00:00Z", "2026-08-14T10:00:00Z")
    depart_and_arrive(disp["id"], tech["id"])
    complete_job(job["id"], tech["id"])
    invoice_job(job["id"])
    set_clock("2027-08-14T08:00:00Z")  # well past warranty_until (invoice + 30 days)
    resp = api.create_callback({"job_id": job["id"], "reason": "too late"}, make_customer_headers(cust["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_WARRANTY_COVERED.value)
    job_after = validate_success(api.get_service_job(job["id"], DISP), 200)
    assert job_after["status"] == "INVOICED"  # not reopened


def test_priority_existence_before_state(api):
    """PRD §2.6: "then existence of every path- and body-referenced resource, validated
    left-to-right (`ERR_NOT_FOUND`) ... then state-transition legality (`ERR_INVALID_STATE`)."

    Design: Corner/validations/priority_existence_before_state
    """
    resp = api.send_estimate("00000000-0000-0000-0000-000000000000", DISP)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_close_succeeds_when_no_open_callback(api):
    """PRD §3.8: "After a job is `INVOICED`, a dispatcher closes it, advancing the `status`
    from `INVOICED` to `CLOSED`. Closing is blocked while any `Callback` for the job is still
    `OPEN`."

    Design: Corner/validations/close_succeeds_when_no_open_callback
    """
    set_clock("2026-08-20T08:00:00Z")
    cust = make_customer(email="cl@x.com", service_zip="54001")
    tech = make_technician(service_zone="540", license_class="JOURNEYMAN", hourly_rate_cents=9000)
    job = make_job(cust["id"], scope="OUTLET", job_class="SERVICE")
    quote_and_accept(job["id"], cust["id"], pricing_mode="FLAT_RATE", flat_rate_cents=10000)
    disp = dispatch_tech(job["id"], tech["id"], "2026-08-20T09:00:00Z", "2026-08-20T10:00:00Z")
    depart_and_arrive(disp["id"], tech["id"])
    complete_job(job["id"], tech["id"])
    invoice_job(job["id"])
    resp = api.close_service_job(job["id"], DISP)
    data = validate_success(resp, 200)
    assert data["status"] == "CLOSED"
