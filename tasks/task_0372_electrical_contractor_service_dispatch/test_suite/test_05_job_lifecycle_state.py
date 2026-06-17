"""ServiceJob / Estimate / Permit / Callback state machines: valid and invalid
transitions, the cyclic warranty loop, the permit re-inspection loop, cascades,
and cross-entity state dependencies.

Queue A (Difficulty): non_linear_state_machine, transitive_cascade,
cross_entity_state_dependency.
Queue B (Corner): valid transitions, invalid transitions, terminal lockdown,
cancel cascade.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    make_customer_headers, make_technician_headers,
    make_customer, make_technician, make_job, current_job_version,
    quote_and_accept, dispatch_tech, depart_and_arrive, complete_job, invoice_job,
    file_permit, issue_permit, schedule_inspection, record_inspection,
    setup_permit_passed, file_callback, set_clock,
)

DISP = TEST_USERS["dispatcher_headers"]
INSP = TEST_USERS["inspector_headers"]


# ─── Queue A: non_linear_state_machine — ServiceJob warranty cycle ────────
def test_servicejob_warranty_cycle_reopen_and_reenter_in_progress(api):
    """PRD §3.8: "A callback that is covered opens in `OPEN` status and reopens the job:
    a job in `INVOICED` or `CLOSED` is moved to `WARRANTY`, re-entering the work cycle."
    PRD §3.8: "A technician is re-dispatched, and when that dispatch arrives on site the job
    moves from `WARRANTY` back into `IN_PROGRESS`."

    Design: Difficulty/non_linear_state_machine/nonlinear_servicejob_warranty_cycle
    """
    set_clock("2026-07-05T08:00:00Z")
    cust = make_customer(email="nl1@x.com", service_zip="40001")
    tech = make_technician(service_zone="400", license_class="JOURNEYMAN", hourly_rate_cents=10000)
    job = make_job(cust["id"], scope="OUTLET", job_class="SERVICE")
    quote_and_accept(job["id"], cust["id"], pricing_mode="FLAT_RATE", flat_rate_cents=10000)
    disp = dispatch_tech(job["id"], tech["id"], "2026-07-05T09:00:00Z", "2026-07-05T10:00:00Z")
    depart_and_arrive(disp["id"], tech["id"])
    complete_job(job["id"], tech["id"])
    invoice_job(job["id"])

    cb = file_callback(job["id"], cust["id"], reason="intermittent fault")
    assert cb["covered_by_warranty"] is True
    after_cb = validate_success(api.get_service_job(job["id"], DISP), 200)
    assert after_cb["status"] == "WARRANTY"

    disp2 = dispatch_tech(job["id"], tech["id"], "2026-07-06T09:00:00Z", "2026-07-06T10:00:00Z")
    th = make_technician_headers(tech["id"])
    validate_success(api.depart_dispatch(disp2["id"], th), 200)
    arrived = validate_success(api.arrive_dispatch(disp2["id"], th), 200)
    assert arrived["status"] == "ON_SITE"
    job_after = validate_success(api.get_service_job(job["id"], DISP), 200)
    assert job_after["status"] == "IN_PROGRESS"  # WARRANTY -> IN_PROGRESS cyclic edge


def test_servicejob_warranty_cycle_reinvoices_after_rework(api):
    """PRD §3.8: "the job moves from `WARRANTY` back into `IN_PROGRESS`, from which it again
    proceeds to `COMPLETED` and can be re-invoiced — the warranty work re-enters the same
    work-and-bill loop."

    Design: Difficulty/non_linear_state_machine/nonlinear_servicejob_warranty_cycle
    """
    set_clock("2026-07-25T08:00:00Z")
    cust = make_customer(email="nl1b@x.com", service_zip="40002")
    tech = make_technician(service_zone="400", license_class="JOURNEYMAN", hourly_rate_cents=10000)
    job = make_job(cust["id"], scope="OUTLET", job_class="SERVICE")
    quote_and_accept(job["id"], cust["id"], pricing_mode="FLAT_RATE", flat_rate_cents=10000)
    disp = dispatch_tech(job["id"], tech["id"], "2026-07-25T09:00:00Z", "2026-07-25T10:00:00Z")
    depart_and_arrive(disp["id"], tech["id"])
    complete_job(job["id"], tech["id"])
    invoice_job(job["id"])
    file_callback(job["id"], cust["id"], reason="rework")  # job -> WARRANTY

    disp2 = dispatch_tech(job["id"], tech["id"], "2026-07-26T09:00:00Z", "2026-07-26T10:00:00Z")
    depart_and_arrive(disp2["id"], tech["id"])  # WARRANTY -> IN_PROGRESS
    completed = complete_job(job["id"], tech["id"])  # IN_PROGRESS -> COMPLETED
    assert completed["status"] == "COMPLETED"
    reinvoiced = invoice_job(job["id"])             # COMPLETED -> INVOICED again
    assert reinvoiced["status"] == "INVOICED"


# ─── Queue A: non_linear_state_machine — Permit re-inspection cycle ───────
def test_permit_failed_reinspection_cycle(api):
    """PRD §3.6: "a `FAIL` result moves it from `INSPECTION_SCHEDULED` to `FAILED`. A failed
    permit is not the end of the road — a dispatcher may schedule a re-inspection on a
    `FAILED` permit, which again records the new `inspection_at` and returns the permit to
    `INSPECTION_SCHEDULED`, from which it can be recorded again."

    Design: Difficulty/non_linear_state_machine/nonlinear_permit_failed_reinspection_cycle
    """
    cust = make_customer(email="nl2@x.com", service_zip="41001")
    job = make_job(cust["id"], scope="PANEL", job_class="INSTALL")
    permit = file_permit(job["id"], jurisdiction="City", permit_number="PN-1")
    issue_permit(permit["id"])
    schedule_inspection(permit["id"], "2026-07-07T09:00:00Z")
    failed = record_inspection(permit["id"], "FAIL")
    assert failed["status"] == "FAILED"
    resched = schedule_inspection(permit["id"], "2026-07-08T09:00:00Z")
    assert resched["status"] == "INSPECTION_SCHEDULED"  # FAILED -> INSPECTION_SCHEDULED cyclic edge
    passed = record_inspection(permit["id"], "PASS")
    assert passed["status"] == "PASSED"


def test_permit_reschedule_records_new_inspection_time_on_failed(api):
    """PRD §3.6: "a dispatcher may schedule a re-inspection on a `FAILED` permit, which again
    records the new `inspection_at` and returns the permit to `INSPECTION_SCHEDULED`."

    Design: Difficulty/non_linear_state_machine/nonlinear_permit_failed_reinspection_cycle
    """
    cust = make_customer(email="nl2b@x.com", service_zip="41002")
    job = make_job(cust["id"], scope="EV_CHARGER", job_class="INSTALL")
    permit = file_permit(job["id"], jurisdiction="City", permit_number="PN-2")
    issue_permit(permit["id"])
    schedule_inspection(permit["id"], "2026-07-07T09:00:00Z")
    record_inspection(permit["id"], "FAIL")  # -> FAILED
    resched = schedule_inspection(permit["id"], "2026-07-09T15:00:00Z")  # re-inspection time recorded
    assert resched["status"] == "INSPECTION_SCHEDULED"
    assert resched["inspection_at"].startswith("2026-07-09T15:00:00")


# ─── Queue A: transitive_cascade ──────────────────────────────────────────
def test_cascade_estimate_accept_supersede_chain(api):
    """PRD §3.4: "on acceptance the estimate moves `SENT → ACCEPTED`, every sibling estimate
    on the same job that is still in `SENT` or `DRAFT` is moved to `SUPERSEDED`, the parent
    job's `pricing_mode` is copied from the accepted estimate, and a job in `DRAFT` or
    `QUOTED` is bubbled to `QUOTED`."

    Design: Difficulty/transitive_cascade/cascade_estimate_accept_supersede_chain_depth3
    """
    cust = make_customer(email="tc1@x.com", service_zip="50001")
    job = make_job(cust["id"], scope="OUTLET", job_class="SERVICE")
    v0 = job["version"]
    estA = validate_success(api.create_estimate(
        {"job_id": job["id"], "pricing_mode": "FLAT_RATE", "expected_job_version": v0, "flat_rate_cents": 30000},
        DISP), 201)
    v1 = current_job_version(job["id"])  # estimate-create bumped the job version (PRD §2.5)
    estB = validate_success(api.create_estimate(
        {"job_id": job["id"], "pricing_mode": "TIME_MATERIALS", "expected_job_version": v1,
         "estimated_labor_hours": 2, "estimated_material_cents": 500}, DISP), 201)
    api.send_estimate(estA["id"], DISP)
    api.send_estimate(estB["id"], DISP)

    accepted = validate_success(api.accept_estimate(estA["id"], make_customer_headers(cust["id"])), 200)
    assert accepted["status"] == "ACCEPTED"
    b_after = validate_success(api.get_estimate(estB["id"], DISP), 200)
    assert b_after["status"] == "SUPERSEDED"            # caused by A's acceptance
    job_after = validate_success(api.get_service_job(job["id"], DISP), 200)
    assert job_after["status"] == "QUOTED"               # bubbled by the acceptance chain
    assert job_after["pricing_mode"] == "FLAT_RATE"      # copied from accepted estimate A


def test_cascade_estimate_accept_copies_time_materials_pricing_mode(api):
    """PRD §3.4: "the parent job's `pricing_mode` is copied from the accepted estimate, and a
    job in `DRAFT` or `QUOTED` is bubbled to `QUOTED`."
    PRD §3.4: "every sibling estimate on the same job that is still in `SENT` or `DRAFT` is
    moved to `SUPERSEDED`."

    Design: Difficulty/transitive_cascade/cascade_estimate_accept_supersede_chain_depth3
    """
    cust = make_customer(email="tc1b@x.com", service_zip="50002")
    job = make_job(cust["id"], scope="OUTLET", job_class="SERVICE")
    v0 = job["version"]
    estA = validate_success(api.create_estimate(
        {"job_id": job["id"], "pricing_mode": "TIME_MATERIALS", "expected_job_version": v0,
         "estimated_labor_hours": 2, "estimated_material_cents": 500}, DISP), 201)
    v1 = current_job_version(job["id"])  # estimate-create bumped the job version (PRD §2.5)
    estB = validate_success(api.create_estimate(
        {"job_id": job["id"], "pricing_mode": "FLAT_RATE", "expected_job_version": v1, "flat_rate_cents": 30000},
        DISP), 201)
    api.send_estimate(estA["id"], DISP)
    api.send_estimate(estB["id"], DISP)
    api.accept_estimate(estA["id"], make_customer_headers(cust["id"]))  # accept the TIME_MATERIALS one

    job_after = validate_success(api.get_service_job(job["id"], DISP), 200)
    assert job_after["status"] == "QUOTED"
    assert job_after["pricing_mode"] == "TIME_MATERIALS"  # copied from accepted estimate A
    b_after = validate_success(api.get_estimate(estB["id"], DISP), 200)
    assert b_after["status"] == "SUPERSEDED"


def test_cascade_job_cancel_from_scheduled_cancels_dispatch(api):
    """PRD §3.9: "Cancelling a job that is `SCHEDULED` moves it to `CANCELLED`, supersedes
    its open estimates as above, and also cancels the active dispatch — moving that dispatch
    to `CANCELLED` and thereby freeing the technician's time window for other bookings."

    Design: Difficulty/transitive_cascade/cascade_job_cancel_dispatch_and_estimates_depth2
    """
    cust = make_customer(email="tc2@x.com", service_zip="51001")
    tech = make_technician(service_zone="510", license_class="JOURNEYMAN", hourly_rate_cents=10000)
    job = make_job(cust["id"], scope="OUTLET", job_class="SERVICE")
    quote_and_accept(job["id"], cust["id"], pricing_mode="FLAT_RATE", flat_rate_cents=12000)
    disp = dispatch_tech(job["id"], tech["id"], "2026-07-09T09:00:00Z", "2026-07-09T10:00:00Z")

    cancelled = validate_success(api.cancel_service_job(job["id"], make_customer_headers(cust["id"])), 200)
    assert cancelled["status"] == "CANCELLED"
    disp_after = validate_success(api.get_dispatch(disp["id"], DISP), 200)
    assert disp_after["status"] == "CANCELLED"  # cascaded from job cancel


def test_cascade_job_cancel_from_scheduled_supersedes_estimate(api):
    """PRD §3.9: "Cancelling a job that is `SCHEDULED` moves it to `CANCELLED`, supersedes
    its open estimates as above, and also cancels the active dispatch."

    Design: Difficulty/transitive_cascade/cascade_job_cancel_dispatch_and_estimates_depth2
    """
    cust = make_customer(email="tc2b@x.com", service_zip="51102")
    tech = make_technician(service_zone="511", license_class="JOURNEYMAN", hourly_rate_cents=10000)
    job = make_job(cust["id"], scope="OUTLET", job_class="SERVICE")
    v0 = job["version"]
    est = validate_success(api.create_estimate(
        {"job_id": job["id"], "pricing_mode": "FLAT_RATE", "expected_job_version": v0, "flat_rate_cents": 12000},
        DISP), 201)
    api.send_estimate(est["id"], DISP)
    api.accept_estimate(est["id"], make_customer_headers(cust["id"]))  # est ACCEPTED, job QUOTED
    # add a second SENT estimate that should be superseded by the cancel cascade.
    v_now = current_job_version(job["id"])
    est2 = validate_success(api.create_estimate(
        {"job_id": job["id"], "pricing_mode": "FLAT_RATE", "expected_job_version": v_now, "flat_rate_cents": 9000},
        DISP), 201)
    api.send_estimate(est2["id"], DISP)
    disp = dispatch_tech(job["id"], tech["id"], "2026-07-28T09:00:00Z", "2026-07-28T10:00:00Z")  # job SCHEDULED

    api.cancel_service_job(job["id"], make_customer_headers(cust["id"]))
    disp_after = validate_success(api.get_dispatch(disp["id"], DISP), 200)
    assert disp_after["status"] == "CANCELLED"
    est2_after = validate_success(api.get_estimate(est2["id"], DISP), 200)
    assert est2_after["status"] == "SUPERSEDED"  # open estimate superseded by the cancel cascade


# ─── Queue A: cross_entity_state_dependency ───────────────────────────────
def test_cross_entity_job_complete_requires_permit_passed(api):
    """PRD §3.5: "If the job's `requires_permit` flag is true, completion is blocked until a
    `Permit` for the job has reached `PASSED` status; attempting to complete a permitted job
    whose permit has not passed is rejected with `ERR_PERMIT_NOT_PASSED`."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_job_complete_requires_permit_passed
    """
    cust = make_customer(email="ce1@x.com", service_zip="80001")
    tech = make_technician(service_zone="800", license_class="MASTER", hourly_rate_cents=10000)
    job = make_job(cust["id"], scope="PANEL", job_class="INSTALL")
    quote_and_accept(job["id"], cust["id"], pricing_mode="FLAT_RATE", flat_rate_cents=50000)
    permit = file_permit(job["id"], jurisdiction="City", permit_number="CE1-PN")
    issue_permit(permit["id"])
    schedule_inspection(permit["id"], "2026-07-14T09:00:00Z")  # permit only INSPECTION_SCHEDULED, not PASSED
    disp = dispatch_tech(job["id"], tech["id"], "2026-07-14T10:00:00Z", "2026-07-14T11:00:00Z")
    depart_and_arrive(disp["id"], tech["id"])

    resp = api.complete_service_job(job["id"], {}, make_technician_headers(tech["id"]))
    validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_PASSED.value)
    job_after = validate_success(api.get_service_job(job["id"], DISP), 200)
    assert job_after["status"] == "IN_PROGRESS"  # unchanged


def test_cross_entity_job_complete_succeeds_once_permit_passed(api):
    """PRD §3.5: "If the job's `requires_permit` flag is true, completion is blocked until a
    `Permit` for the job has reached `PASSED` status."
    PRD §3.6: "a `PASS` result moves the permit from `INSPECTION_SCHEDULED` to `PASSED`,
    which unblocks job completion."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_job_complete_requires_permit_passed
    """
    cust = make_customer(email="ce1b@x.com", service_zip="80002")
    tech = make_technician(service_zone="800", license_class="MASTER", hourly_rate_cents=10000)
    job = make_job(cust["id"], scope="PANEL", job_class="INSTALL")
    quote_and_accept(job["id"], cust["id"], pricing_mode="FLAT_RATE", flat_rate_cents=50000)
    setup_permit_passed(job["id"], inspection_at="2026-07-29T09:00:00Z")  # permit driven to PASSED
    disp = dispatch_tech(job["id"], tech["id"], "2026-07-29T10:00:00Z", "2026-07-29T11:00:00Z")
    depart_and_arrive(disp["id"], tech["id"])
    completed = validate_success(api.complete_service_job(job["id"], {}, make_technician_headers(tech["id"])), 200)
    assert completed["status"] == "COMPLETED"  # permit PASSED unblocks completion


def test_cross_entity_callback_resolve_requires_job_back_done(api):
    """PRD §3.8: "resolution is permitted only when the callback is `OPEN` and the parent job
    has returned to `COMPLETED` or `INVOICED`, and it moves the callback from `OPEN` to
    `RESOLVED`."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_callback_resolve_requires_job_back_in_progress_done
    """
    set_clock("2026-07-15T08:00:00Z")
    cust = make_customer(email="ce2@x.com", service_zip="81001")
    tech = make_technician(service_zone="810", license_class="JOURNEYMAN", hourly_rate_cents=10000)
    job = make_job(cust["id"], scope="OUTLET", job_class="SERVICE")
    quote_and_accept(job["id"], cust["id"], pricing_mode="FLAT_RATE", flat_rate_cents=10000)
    disp = dispatch_tech(job["id"], tech["id"], "2026-07-15T09:00:00Z", "2026-07-15T10:00:00Z")
    depart_and_arrive(disp["id"], tech["id"])
    complete_job(job["id"], tech["id"])
    invoice_job(job["id"])
    cb = file_callback(job["id"], cust["id"], reason="loose ground")  # job -> WARRANTY, callback OPEN

    resp = api.resolve_callback(cb["id"], DISP)  # job still WARRANTY -> rejected
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    cb_after = validate_success(api.get_callback(cb["id"], DISP), 200)
    assert cb_after["status"] == "OPEN"
    job_after = validate_success(api.get_service_job(job["id"], DISP), 200)
    assert job_after["status"] == "WARRANTY"


def test_cross_entity_callback_resolve_allowed_once_job_completed(api):
    """PRD §3.8: "An open callback is resolved by a dispatcher once the warranty work is
    finished: resolution is permitted only when the callback is `OPEN` and the parent job has
    returned to `COMPLETED` or `INVOICED`, and it moves the callback from `OPEN` to `RESOLVED`."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_callback_resolve_requires_job_back_in_progress_done
    """
    set_clock("2026-07-31T08:00:00Z")
    cust = make_customer(email="ce2b@x.com", service_zip="81002")
    tech = make_technician(service_zone="810", license_class="JOURNEYMAN", hourly_rate_cents=10000)
    job = make_job(cust["id"], scope="OUTLET", job_class="SERVICE")
    quote_and_accept(job["id"], cust["id"], pricing_mode="FLAT_RATE", flat_rate_cents=10000)
    disp = dispatch_tech(job["id"], tech["id"], "2026-07-31T09:00:00Z", "2026-07-31T10:00:00Z")
    depart_and_arrive(disp["id"], tech["id"])
    complete_job(job["id"], tech["id"])
    invoice_job(job["id"])
    cb = file_callback(job["id"], cust["id"], reason="loose ground")  # job -> WARRANTY
    # perform the warranty rework so the parent job is back in COMPLETED.
    disp2 = dispatch_tech(job["id"], tech["id"], "2026-08-01T09:00:00Z", "2026-08-01T10:00:00Z")
    depart_and_arrive(disp2["id"], tech["id"])
    complete_job(job["id"], tech["id"])  # job -> COMPLETED
    resolved = validate_success(api.resolve_callback(cb["id"], DISP), 200)
    assert resolved["status"] == "RESOLVED"


# ─── Queue B: valid transitions ───────────────────────────────────────────
def test_estimate_send_from_draft_valid(api):
    """PRD §3.4: "A dispatcher sends an estimate, moving it from `DRAFT` to `SENT`; this is
    permitted only while the estimate is `DRAFT` and the parent job is in `DRAFT` or `QUOTED`."

    Design: Corner/state_machines/estimate_send_from_draft_valid
    """
    cust = make_customer(email="se@x.com", service_zip="15001")
    job = make_job(cust["id"], scope="OUTLET", job_class="SERVICE")
    v0 = job["version"]
    est = validate_success(api.create_estimate(
        {"job_id": job["id"], "pricing_mode": "FLAT_RATE", "expected_job_version": v0, "flat_rate_cents": 12000},
        DISP), 201)
    sent = validate_success(api.send_estimate(est["id"], DISP), 200)
    assert sent["status"] == "SENT"


def test_estimate_reject_from_sent_valid(api):
    """PRD §3.4: "Rejection is allowed only when the estimate is `SENT` and the rejecting
    customer owns the parent job; it simply moves the estimate `SENT → REJECTED` with no
    effect on siblings or the job."

    Design: Corner/state_machines/estimate_reject_from_sent_valid
    """
    cust = make_customer(email="rj@x.com", service_zip="16001")
    job = make_job(cust["id"], scope="OUTLET", job_class="SERVICE")
    v0 = job["version"]
    est = validate_success(api.create_estimate(
        {"job_id": job["id"], "pricing_mode": "FLAT_RATE", "expected_job_version": v0, "flat_rate_cents": 12000},
        DISP), 201)
    api.send_estimate(est["id"], DISP)
    rejected = validate_success(api.reject_estimate(est["id"], make_customer_headers(cust["id"])), 200)
    assert rejected["status"] == "REJECTED"
    job_after = validate_success(api.get_service_job(job["id"], DISP), 200)
    assert job_after["status"] == "DRAFT"  # unchanged


def test_dispatch_depart_from_assigned_valid(api):
    """PRD §3.5: "Departing moves the dispatch from `ASSIGNED` to `EN_ROUTE`, and is
    permitted only while the dispatch is `ASSIGNED` and only for the technician who is
    actually assigned to it."

    Design: Corner/state_machines/dispatch_depart_from_assigned_valid
    """
    cust = make_customer(email="dp@x.com", service_zip="17001")
    tech = make_technician(service_zone="170", license_class="JOURNEYMAN", hourly_rate_cents=9000)
    job = make_job(cust["id"], scope="OUTLET", job_class="SERVICE")
    quote_and_accept(job["id"], cust["id"], pricing_mode="FLAT_RATE", flat_rate_cents=12000)
    disp = dispatch_tech(job["id"], tech["id"], "2026-08-02T09:00:00Z", "2026-08-02T10:00:00Z")
    departed = validate_success(api.depart_dispatch(disp["id"], make_technician_headers(tech["id"])), 200)
    assert departed["status"] == "EN_ROUTE"


def test_permit_issue_from_applied_valid(api):
    """PRD §3.6: "An inspector issues the permit, moving it from `APPLIED` to `ISSUED`."

    Design: Corner/state_machines/permit_issue_from_applied_valid
    """
    cust = make_customer(email="pi@x.com", service_zip="18001")
    job = make_job(cust["id"], scope="PANEL", job_class="INSTALL")
    permit = file_permit(job["id"], jurisdiction="Town", permit_number="PI-1")
    issued = validate_success(api.issue_permit(permit["id"], INSP), 200)
    assert issued["status"] == "ISSUED"


def test_callback_resolve_from_open_valid(api):
    """PRD §3.8: "resolution is permitted only when the callback is `OPEN` and the parent job
    has returned to `COMPLETED` or `INVOICED`, and it moves the callback from `OPEN` to
    `RESOLVED`."

    Design: Corner/state_machines/callback_resolve_from_open_valid
    """
    set_clock("2026-08-03T08:00:00Z")
    cust = make_customer(email="cr@x.com", service_zip="19001")
    tech = make_technician(service_zone="190", license_class="JOURNEYMAN", hourly_rate_cents=9000)
    job = make_job(cust["id"], scope="OUTLET", job_class="SERVICE")
    quote_and_accept(job["id"], cust["id"], pricing_mode="FLAT_RATE", flat_rate_cents=10000)
    disp = dispatch_tech(job["id"], tech["id"], "2026-08-03T09:00:00Z", "2026-08-03T10:00:00Z")
    depart_and_arrive(disp["id"], tech["id"])
    complete_job(job["id"], tech["id"])
    invoice_job(job["id"])
    cb = file_callback(job["id"], cust["id"], reason="rework")  # job -> WARRANTY

    # re-dispatch the warranty visit, arrive, complete -> job back to COMPLETED
    disp2 = dispatch_tech(job["id"], tech["id"], "2026-08-04T09:00:00Z", "2026-08-04T10:00:00Z")
    depart_and_arrive(disp2["id"], tech["id"])
    complete_job(job["id"], tech["id"])

    resolved = validate_success(api.resolve_callback(cb["id"], DISP), 200)
    assert resolved["status"] == "RESOLVED"


# ─── Queue B: invalid transitions / terminal lockdown ─────────────────────
def test_invalid_transition_accept_from_draft_estimate(api):
    """PRD §3.4: "Acceptance is allowed only when the estimate is `SENT` and the accepting
    customer owns the parent job."
    PRD §3.6: "Each of these transitions is permitted only from the state named as its
    source; an attempt from any other state is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/invalid_transition_accept_from_draft_estimate
    """
    cust = make_customer(email="it@x.com", service_zip="21001")
    job = make_job(cust["id"], scope="OUTLET", job_class="SERVICE")
    v0 = job["version"]
    est = validate_success(api.create_estimate(
        {"job_id": job["id"], "pricing_mode": "FLAT_RATE", "expected_job_version": v0, "flat_rate_cents": 12000},
        DISP), 201)
    resp = api.accept_estimate(est["id"], make_customer_headers(cust["id"]))  # still DRAFT, never sent
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_invalid_transition_complete_from_scheduled(api):
    """PRD §3.5: "Completion is permitted only when the job is `IN_PROGRESS`."

    Design: Corner/state_machines/invalid_transition_complete_from_scheduled
    """
    cust = make_customer(email="ic@x.com", service_zip="23001")
    tech = make_technician(service_zone="230", license_class="JOURNEYMAN", hourly_rate_cents=9000)
    job = make_job(cust["id"], scope="OUTLET", job_class="SERVICE")
    quote_and_accept(job["id"], cust["id"], pricing_mode="FLAT_RATE", flat_rate_cents=12000)
    dispatch_tech(job["id"], tech["id"], "2026-08-05T09:00:00Z", "2026-08-05T10:00:00Z")  # SCHEDULED, never arrived
    resp = api.complete_service_job(job["id"], {}, make_technician_headers(tech["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_terminal_state_resolved_callback_cannot_resolve_again(api):
    """PRD §3.8: "resolution is permitted only when the callback is `OPEN`."
    PRD §3.6: "an attempt from any other state is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/terminal_state_resolved_callback_cannot_resolve_again
    """
    set_clock("2026-08-06T08:00:00Z")
    cust = make_customer(email="tr@x.com", service_zip="24001")
    tech = make_technician(service_zone="240", license_class="JOURNEYMAN", hourly_rate_cents=9000)
    job = make_job(cust["id"], scope="OUTLET", job_class="SERVICE")
    quote_and_accept(job["id"], cust["id"], pricing_mode="FLAT_RATE", flat_rate_cents=10000)
    disp = dispatch_tech(job["id"], tech["id"], "2026-08-06T09:00:00Z", "2026-08-06T10:00:00Z")
    depart_and_arrive(disp["id"], tech["id"])
    complete_job(job["id"], tech["id"])
    invoice_job(job["id"])
    cb = file_callback(job["id"], cust["id"], reason="rework")
    disp2 = dispatch_tech(job["id"], tech["id"], "2026-08-07T09:00:00Z", "2026-08-07T10:00:00Z")
    depart_and_arrive(disp2["id"], tech["id"])
    complete_job(job["id"], tech["id"])
    api.resolve_callback(cb["id"], DISP)  # first resolve -> RESOLVED

    resp = api.resolve_callback(cb["id"], DISP)  # resolve again
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_cancel_job_cascade_supersedes_estimates_from_draft(api):
    """PRD §3.9: "Cancelling a job that is `DRAFT` or `QUOTED` moves it to `CANCELLED` and
    supersedes any of its estimates still in `SENT` or `DRAFT`."

    Design: Corner/state_machines/cancel_job_cascade_supersedes_estimates_from_draft
    """
    cust = make_customer(email="cc@x.com", service_zip="25001")
    job = make_job(cust["id"], scope="OUTLET", job_class="SERVICE")
    v0 = job["version"]
    est = validate_success(api.create_estimate(
        {"job_id": job["id"], "pricing_mode": "FLAT_RATE", "expected_job_version": v0, "flat_rate_cents": 12000},
        DISP), 201)
    api.send_estimate(est["id"], DISP)
    cancelled = validate_success(api.cancel_service_job(job["id"], make_customer_headers(cust["id"])), 200)
    assert cancelled["status"] == "CANCELLED"
    est_after = validate_success(api.get_estimate(est["id"], DISP), 200)
    assert est_after["status"] == "SUPERSEDED"
