"""Corner tests for the validation families: auth headers, role admission,
ownership scope, intake posture, schedule gating, temporal windows,
uniqueness, fiscal bounds, segregation of duties, and referential integrity
(PRD §2.1, §2.8, §2.9, §3.2–§3.9)."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, ApiErrorId,
    NON_EXISTENT_UUID, build_user_headers,
    make_program_admin_headers, make_host_coordinator_headers,
    make_responding_coordinator_headers, make_crew_supervisor_headers,
    make_host_safety_officer_headers, make_host_finance_headers,
    make_responding_finance_headers,
    set_clock, create_company, create_event, create_and_publish_schedule,
    create_request, create_accepted_request, commit_crew,
    conduct_and_acknowledge_briefing, arrive_crew, create_submitted_timesheet,
    certify_timesheet, create_approved_claim, create_draft_invoice,
    submit_invoice, setup_event_active, setup_event_with_accepted_request,
    setup_cleared_arrived_crew, setup_demobilized_with_certified_rows,
    setup_submitted_invoice, setup_approved_invoice,
    create_after_action_report,
    create_utility_company_payload, create_event_payload,
    create_assistance_request_payload, create_safety_briefing_payload,
    create_timesheet_payload, create_per_diem_claim_payload,
    create_invoice_payload,
)


# --- auth / role / scope ----------------------------------------------------

def test_missing_auth_headers_rejected():
    """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
    identifying the acting user, and `X-User-Role`, naming the operational
    capacity in which they act. A request in which either header is missing or
    malformed is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`
    (HTTP 400)."

    Design: Corner/validations/val_missing_auth_header_rejected
    """
    resp = api_client.create_event(
        create_event_payload(host_utility_id=NON_EXISTENT_UUID),
        headers={"Content-Type": "application/json"})
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


def test_forbidden_role_rejected():
    """PRD §2.1: "Each endpoint admits a fixed set of roles; a caller whose
    role is not admitted is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
    Event activation is ProgramAdmin-only (§4).

    Design: Corner/validations/val_forbidden_role_rejected
    """
    host, rsp, event = setup_event_active(set_clock_first=False)
    # event is still OPEN; activate as the responding coordinator
    resp = api_client.activate_event(
        event["id"], make_responding_coordinator_headers(rsp["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)


def test_scope_mismatch_rejected():
    """PRD §2.1: "Any mismatch between an entity-backed caller's `X-User-ID`
    and the resource's owning scope is rejected with `ERR_SCOPE_MISMATCH`
    (HTTP 403)." Arrival confirmation is scoped to the event's host utility
    (§3.4).

    Design: Corner/validations/val_scope_mismatch_rejected
    """
    ctx = setup_event_with_accepted_request()
    other = create_company(name="Other Utility", company_code="OTH",
                           role_capability="BOTH", home_region="Plains")
    crew = commit_crew(ctx["request"]["id"], ctx["rsp"]["id"])
    resp = api_client.confirm_arrival(
        crew["id"], make_host_coordinator_headers(other["id"]))
    validate_error(resp, ApiErrorId.ERR_SCOPE_MISMATCH)


# --- intake posture ---------------------------------------------------------

def test_intake_posture_restricts_at_threshold():
    """PRD §2.8: "otherwise it is `RESTRICTED` once the event's
    `open_request_count` reaches three or more — exactly three open requests is
    enough to flip the posture" and "Both `RESTRICTED` and `SEALED` block the
    creation of new assistance requests with
    `ERR_EVENT_NOT_ACCEPTING_REQUESTS` (HTTP 409); only an `ACCEPTING` event
    admits them." plus "The posture and the underlying count are recomputed
    immediately whenever the open-request population changes — on request
    submission, acceptance, decline, or cancellation"

    Design: Corner/validations/val_intake_posture_restricts_at_threshold
    """
    host, rsp, event = setup_event_active()
    ids = []
    for crew_type in ("LINE", "TREE", "SUPPORT"):
        r = create_request(event["id"], host["id"], rsp["id"], submit=True,
                           requested_crews=[{"crew_type": crew_type, "count": 1}])
        ids.append(r["id"])
    # 4th create while 3 open must fail
    resp = api_client.create_assistance_request(
        create_assistance_request_payload(event_id=event["id"],
                                          responding_utility_id=rsp["id"],
                                          requested_crews=[{"crew_type": "LINE", "count": 1}]),
        make_host_coordinator_headers(host["id"]))
    validate_error(resp, ApiErrorId.ERR_EVENT_NOT_ACCEPTING_REQUESTS)
    resp = api_client.get_event(event["id"], make_program_admin_headers())
    assert validate_success(resp)["intake_posture"] == "RESTRICTED"
    # Declining one reopens intake (derived, not latched)
    resp = api_client.decline_assistance_request(
        ids[0], {}, make_responding_coordinator_headers(rsp["id"]))
    assert resp.status_code == 200, f"Setup failed declining: {resp.text}"
    resp = api_client.create_assistance_request(
        create_assistance_request_payload(event_id=event["id"],
                                          responding_utility_id=rsp["id"],
                                          requested_crews=[{"crew_type": "LINE", "count": 1}]),
        make_host_coordinator_headers(host["id"]))
    validate_success(resp, expected_status=201)


def test_accept_without_published_schedule_rejected():
    """PRD §3.3: "Acceptance by the responding coordinator moves `SUBMITTED` to
    `ACCEPTED`, but only when a billing-rate schedule for this event and
    responding utility exists in `PUBLISHED` or `LOCKED` status; otherwise the
    acceptance is rejected with `ERR_SCHEDULE_NOT_PUBLISHED`."

    Design: Corner/validations/val_accept_without_published_schedule_rejected
    """
    host, rsp, event = setup_event_active()
    request = create_request(event["id"], host["id"], rsp["id"], submit=True)
    resp = api_client.accept_assistance_request(
        request["id"], make_responding_coordinator_headers(rsp["id"]))
    validate_error(resp, ApiErrorId.ERR_SCHEDULE_NOT_PUBLISHED)


# --- temporal windows -------------------------------------------------------

def test_invoice_submit_before_demobilization_rejected():
    """PRD §3.8: "the event must stand at `DEMOBILIZING`
    (`ERR_EVENT_NOT_DEMOBILIZING`)"

    Design: Corner/validations/val_invoice_submit_before_demobilization_rejected
    """
    set_clock("2026-05-05T09:00:00Z")
    host = create_company(name="Host Power", company_code="HST",
                          role_capability="BOTH", home_region="Coastal")
    rsp = create_company(name="Responder Electric", company_code="RSP",
                         role_capability="RESPONDING", home_region="Inland")
    event = create_event(host["id"], activate=True)
    schedule = create_and_publish_schedule(event["id"], rsp["id"])
    request = create_accepted_request(event["id"], host["id"], rsp["id"])
    crew = commit_crew(request["id"], rsp["id"])
    arrive_crew(crew["id"], host["id"])
    invoice = create_draft_invoice(request["id"], schedule["id"], rsp["id"])
    resp = api_client.submit_invoice(invoice["id"], make_responding_finance_headers(rsp["id"]))
    validate_error(resp, ApiErrorId.ERR_EVENT_NOT_DEMOBILIZING)
    resp = api_client.get_invoice(invoice["id"], make_responding_finance_headers(rsp["id"]))
    assert validate_success(resp)["status"] == "DRAFT"


def test_invoice_window_closed_rejected():
    """PRD §3.8: "the current logical time must be no later than thirty days
    after the event's `demobilized_at` (`ERR_INVOICE_WINDOW_CLOSED`)"

    Design: Corner/validations/val_invoice_window_closed_rejected
    """
    set_clock("2026-05-05T09:00:00Z")
    host = create_company(name="Host Power", company_code="HST",
                          role_capability="BOTH", home_region="Coastal")
    rsp = create_company(name="Responder Electric", company_code="RSP",
                         role_capability="RESPONDING", home_region="Inland")
    event = create_event(host["id"], activate=True)
    schedule = create_and_publish_schedule(event["id"], rsp["id"])
    request = create_accepted_request(event["id"], host["id"], rsp["id"])
    crew = commit_crew(request["id"], rsp["id"])
    arrive_crew(crew["id"], host["id"])
    resp = api_client.begin_demobilization(event["id"], make_host_coordinator_headers(host["id"]))
    assert resp.status_code == 200, f"Setup failed demobilizing: {resp.text}"
    # demobilized_at anchors at the current clock (2026-05-05); window closes
    # thirty days later (2026-06-04).
    invoice = create_draft_invoice(request["id"], schedule["id"], rsp["id"])
    set_clock("2026-06-05T09:00:00Z")
    resp = api_client.submit_invoice(invoice["id"], make_responding_finance_headers(rsp["id"]))
    validate_error(resp, ApiErrorId.ERR_INVOICE_WINDOW_CLOSED)


def test_certification_window_closed_rejected():
    """PRD §3.6: "the current date must be no later than fourteen days after
    the `work_date` (`ERR_CERTIFICATION_WINDOW_CLOSED`)"

    Design: Corner/validations/val_certification_window_closed_rejected
    """
    set_clock("2026-05-05T09:00:00Z")
    ctx = setup_cleared_arrived_crew(set_clock_first=False)
    ts = create_submitted_timesheet(ctx["crew"]["id"], work_date="2026-05-04",
                                    day_classification="WORK", reported_work_minutes=480)
    set_clock("2026-05-25T09:00:00Z")
    resp = api_client.certify_timesheet(
        ts["id"], {"certifier_operator_ref": "HC-1"},
        make_host_coordinator_headers(ctx["host"]["id"]))
    validate_error(resp, ApiErrorId.ERR_CERTIFICATION_WINDOW_CLOSED)


def test_mobilization_deadline_passed_rejected():
    """PRD §3.4: "the logical clock must not have passed the event's
    `mobilization_deadline`, else the confirmation is rejected with
    `ERR_MOBILIZATION_DEADLINE_PASSED`."

    Design: Corner/validations/val_mobilization_deadline_passed_rejected
    """
    ctx = setup_event_with_accepted_request()
    crew = commit_crew(ctx["request"]["id"], ctx["rsp"]["id"])
    set_clock("2026-05-11T08:00:00Z")  # past the 2026-05-10T18:00:00Z deadline
    resp = api_client.confirm_arrival(crew["id"], make_host_coordinator_headers(ctx["host"]["id"]))
    validate_error(resp, ApiErrorId.ERR_MOBILIZATION_DEADLINE_PASSED)
    resp = api_client.get_crew(crew["id"], make_program_admin_headers())
    assert validate_success(resp)["mobility_status"] == "COMMITTED"


# --- uniqueness -------------------------------------------------------------

def test_duplicate_timesheet_rejected():
    """PRD §3.6: "Only one timesheet may exist per crew and date; a second
    draft reusing the pair is rejected with `ERR_DUPLICATE_TIMESHEET`."

    Design: Corner/validations/val_duplicate_timesheet_rejected
    """
    ctx = setup_event_with_accepted_request()
    crew = commit_crew(ctx["request"]["id"], ctx["rsp"]["id"])
    first = api_client.create_timesheet(
        create_timesheet_payload(crew_id=crew["id"], work_date="2026-05-04"),
        make_crew_supervisor_headers(crew["id"]))
    assert first.status_code == 201, f"Setup failed creating timesheet: {first.text}"
    resp = api_client.create_timesheet(
        create_timesheet_payload(crew_id=crew["id"], work_date="2026-05-04",
                                 day_classification="STANDBY"),
        make_crew_supervisor_headers(crew["id"]))
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_TIMESHEET)


def test_duplicate_claim_rejected():
    """PRD §3.6: "The responding coordinator files a claim with the `crew_id`,
    the `claim_date` — unique per crew, with duplicates rejected as
    `ERR_DUPLICATE_CLAIM`"

    Design: Corner/validations/val_duplicate_claim_rejected
    """
    ctx = setup_event_with_accepted_request()
    crew = commit_crew(ctx["request"]["id"], ctx["rsp"]["id"])
    first = api_client.create_per_diem_claim(
        create_per_diem_claim_payload(crew_id=crew["id"], claim_date="2026-05-03"),
        make_responding_coordinator_headers(ctx["rsp"]["id"]))
    assert first.status_code == 201, f"Setup failed creating claim: {first.text}"
    resp = api_client.create_per_diem_claim(
        create_per_diem_claim_payload(crew_id=crew["id"], claim_date="2026-05-03",
                                      meals_provided_count=1, day_factor_type="FULL"),
        make_responding_coordinator_headers(ctx["rsp"]["id"]))
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_CLAIM)


def test_second_invoice_rejected():
    """PRD §3.8: "at most one live invoice may exist per request — a second
    invoice while a non-`DRAFT`, non-`VOID` one exists is `ERR_INVOICE_EXISTS`."

    Design: Corner/validations/val_second_invoice_rejected
    """
    ctx = setup_submitted_invoice()
    resp = api_client.create_invoice(
        create_invoice_payload(request_id=ctx["request"]["id"],
                               rate_schedule_id=ctx["schedule"]["id"]),
        make_responding_finance_headers(ctx["rsp"]["id"]))
    validate_error(resp, ApiErrorId.ERR_INVOICE_EXISTS)


def test_second_after_action_report_rejected():
    """PRD §3.9: "The host coordinator opens it with the `event_id` — one
    report per event, a second attempt rejected with `ERR_AAR_EXISTS`"

    Design: Corner/validations/val_second_aar_rejected
    """
    host, rsp, event = setup_event_active()
    create_after_action_report(event["id"], host["id"], summary="first")
    resp = api_client.create_after_action_report(
        {"event_id": event["id"], "summary": "second"},
        make_host_coordinator_headers(host["id"]))
    validate_error(resp, ApiErrorId.ERR_AAR_EXISTS)


def test_empty_invoice_rejected():
    """PRD §3.8: "the computed `final_total_cents` must be greater than zero,
    since an invoice with nothing newly billable in the period is
    `ERR_EMPTY_INVOICE`."

    Design: Corner/validations/val_empty_invoice_rejected
    """
    set_clock("2026-05-05T09:00:00Z")
    host = create_company(name="Host Power", company_code="HST",
                          role_capability="BOTH", home_region="Coastal")
    rsp = create_company(name="Responder Electric", company_code="RSP",
                         role_capability="RESPONDING", home_region="Inland")
    event = create_event(host["id"], activate=True)
    schedule = create_and_publish_schedule(event["id"], rsp["id"])
    request = create_accepted_request(event["id"], host["id"], rsp["id"])
    crew = commit_crew(request["id"], rsp["id"])
    arrive_crew(crew["id"], host["id"])
    resp = api_client.begin_demobilization(event["id"], make_host_coordinator_headers(host["id"]))
    assert resp.status_code == 200, f"Setup failed demobilizing: {resp.text}"
    # No certified timesheets, no approved claims in the period.
    invoice = create_draft_invoice(request["id"], schedule["id"], rsp["id"])
    resp = api_client.submit_invoice(invoice["id"], make_responding_finance_headers(rsp["id"]))
    validate_error(resp, ApiErrorId.ERR_EMPTY_INVOICE)


# --- fiscal bounds ----------------------------------------------------------

def test_dispute_and_credit_bounds_rejected():
    """PRD §3.8: "a `disputed_amount_cents` of at least one and at most the
    current `outstanding_cents` (`ERR_DISPUTE_AMOUNT_INVALID`)" and "`credit_cents`
    of at least one and at most the disputed amount
    (`ERR_CREDIT_EXCEEDS_DISPUTED`), recorded as `proposed_credit_cents`,
    moving the invoice from `DISPUTED` to `CREDIT_PROPOSED`."

    Design: Corner/validations/val_dispute_bounds_rejected
    """
    ctx = setup_submitted_invoice()
    inv_id = ctx["invoice"]["id"]
    resp = api_client.dispute_invoice(
        inv_id, {"reason": "HOURS_MISMATCH", "disputed_amount_cents": 999999},
        make_host_finance_headers(ctx["host"]["id"]))
    validate_error(resp, ApiErrorId.ERR_DISPUTE_AMOUNT_INVALID)
    resp = api_client.dispute_invoice(
        inv_id, {"reason": "HOURS_MISMATCH", "disputed_amount_cents": 50000},
        make_host_finance_headers(ctx["host"]["id"]))
    assert resp.status_code == 200, f"Setup failed disputing: {resp.text}"
    resp = api_client.propose_credit(
        inv_id, {"credit_cents": 60000},
        make_responding_finance_headers(ctx["rsp"]["id"]))
    validate_error(resp, ApiErrorId.ERR_CREDIT_EXCEEDS_DISPUTED)
    resp = api_client.propose_credit(
        inv_id, {"credit_cents": 20000},
        make_responding_finance_headers(ctx["rsp"]["id"]))
    assert validate_success(resp)["status"] == "CREDIT_PROPOSED"


def test_payment_mismatch_then_exact_boundary():
    """PRD §3.8: "marking paid requires a positive `amount_cents` — zero or
    less is `ERR_INVALID_AMOUNT` — that equals `outstanding_cents` exactly,
    otherwise `ERR_PAYMENT_AMOUNT_MISMATCH`. A clean payment records
    `amount_paid_cents`, stamps `paid_at`, drives `outstanding_cents` to zero"
    and "when the underlying request already stands at `RELEASED` — closes the
    request" (this request is FULFILLED, not RELEASED, so it stays).

    Design: Corner/validations/val_payment_mismatch_then_exact_boundary
    """
    ctx = setup_approved_invoice()
    inv_id = ctx["invoice"]["id"]
    resp = api_client.mark_invoice_paid(
        inv_id, {"amount_cents": 201865},
        make_host_finance_headers(ctx["host"]["id"]))
    validate_error(resp, ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH)
    resp = api_client.mark_invoice_paid(
        inv_id, {"amount_cents": 201866},
        make_host_finance_headers(ctx["host"]["id"]))
    invoice = validate_success(resp)
    assert invoice["status"] == "PAID"
    assert invoice["outstanding_cents"] == 0
    resp = api_client.get_assistance_request(ctx["request"]["id"], make_program_admin_headers())
    assert validate_success(resp)["status"] == "FULFILLED"


def test_nonpositive_payment_rejected():
    """PRD §3.8: "marking paid requires a positive `amount_cents` — zero or
    less is `ERR_INVALID_AMOUNT`"

    Design: Corner/errors/err_nonpositive_payment_rejected
    """
    ctx = setup_approved_invoice()
    resp = api_client.mark_invoice_paid(
        ctx["invoice"]["id"], {"amount_cents": 0},
        make_host_finance_headers(ctx["host"]["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_AMOUNT)
    resp = api_client.get_invoice(ctx["invoice"]["id"], make_host_finance_headers(ctx["host"]["id"]))
    assert validate_success(resp)["status"] == "APPROVED"


# --- segregation of duties --------------------------------------------------

def test_invoice_approver_who_certified_covered_timesheet_rejected():
    """PRD §3.8: "the presented `approver_operator_ref` must differ from the
    `certified_by_operator_ref` of every timesheet the invoice covers, so no
    operator who certified field time can approve its billing — a collision is
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/validations/val_sod_invoice_approver_was_certifier_rejected
    """
    ctx = setup_submitted_invoice()
    resp = api_client.approve_invoice(
        ctx["invoice"]["id"], {"approver_operator_ref": "HC-1"},
        make_host_finance_headers(ctx["host"]["id"]))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    resp = api_client.get_invoice(ctx["invoice"]["id"], make_host_finance_headers(ctx["host"]["id"]))
    assert validate_success(resp)["status"] == "SUBMITTED"


def test_certifier_equal_to_submitter_rejected():
    """PRD §3.6: "the certifier must differ from `submitted_by_operator_ref`
    (`ERR_SEGREGATION_OF_DUTIES`)"

    Design: Corner/validations/val_sod_certifier_equals_submitter_rejected
    """
    set_clock("2026-05-05T09:00:00Z")
    ctx = setup_cleared_arrived_crew(set_clock_first=False)
    ts = create_submitted_timesheet(ctx["crew"]["id"], work_date="2026-05-04",
                                    day_classification="WORK", reported_work_minutes=480,
                                    submitted_by="SUP-1")
    resp = api_client.certify_timesheet(
        ts["id"], {"certifier_operator_ref": "SUP-1"},
        make_host_coordinator_headers(ctx["host"]["id"]))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)


def test_briefing_conductor_cannot_acknowledge():
    """PRD §3.5: "The acknowledging `supervisor_operator_ref` must differ from
    the `conductor_operator_ref` — the program forbids one operator from
    standing on both sides of the safety record, rejecting such an
    acknowledgment with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/validations/val_sod_briefing_conductor_cannot_acknowledge
    """
    ctx = setup_event_with_accepted_request()
    crew = commit_crew(ctx["request"]["id"], ctx["rsp"]["id"])
    resp = api_client.create_safety_briefing(
        create_safety_briefing_payload(crew_id=crew["id"], event_id=ctx["event"]["id"]),
        make_host_safety_officer_headers(ctx["host"]["id"]))
    assert resp.status_code == 201, f"Setup failed creating briefing: {resp.text}"
    briefing = get_success_data(resp)
    resp = api_client.acknowledge_safety_briefing(
        briefing["id"], {"supervisor_operator_ref": "OFF-1"},
        make_crew_supervisor_headers(crew["id"]))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    resp = api_client.get_safety_briefing(briefing["id"], make_program_admin_headers())
    assert validate_success(resp)["status"] == "CONDUCTED"


# --- referential integrity --------------------------------------------------

def test_briefing_with_wrong_event_rejected():
    """PRD §3.5: "the `event_id` — which must equal the crew's event, else
    `ERR_REFERENTIAL_INTEGRITY`"

    Design: Corner/validations/val_referential_briefing_wrong_event_rejected
    """
    host = create_company()
    rsp = create_company(name="Responder Electric", company_code="RSP",
                         role_capability="RESPONDING", home_region="Inland")
    event_a = create_event(host["id"], activate=True)
    event_b = create_event(host["id"], event_name="Wildfire Creek",
                           event_type="WILDFIRE", declared_start_date="2026-06-01",
                           premium_window_start="2026-06-01",
                           premium_window_end="2026-06-15",
                           mobilization_deadline="2026-06-05T18:00:00Z")
    create_and_publish_schedule(event_a["id"], rsp["id"])
    request = create_accepted_request(event_a["id"], host["id"], rsp["id"])
    crew = commit_crew(request["id"], rsp["id"])
    resp = api_client.create_safety_briefing(
        create_safety_briefing_payload(crew_id=crew["id"], event_id=event_b["id"]),
        make_host_safety_officer_headers(host["id"]))
    validate_error(resp, ApiErrorId.ERR_REFERENTIAL_INTEGRITY)


def test_certify_with_no_effective_schedule_rejected():
    """PRD §3.6: "the effective-schedule selector must find a `PUBLISHED` or
    `LOCKED` schedule for the crew's event and owning utility covering the
    `work_date` (`ERR_NO_EFFECTIVE_SCHEDULE`)"

    Design: Corner/validations/val_no_effective_schedule_rejected
    """
    set_clock("2026-05-05T09:00:00Z")
    host = create_company(name="Host Power", company_code="HST",
                          role_capability="BOTH", home_region="Coastal")
    rsp = create_company(name="Responder Electric", company_code="RSP",
                         role_capability="RESPONDING", home_region="Inland")
    event = create_event(host["id"], activate=True,
                         mobilization_deadline="2026-06-20T18:00:00Z")
    # Schedule covers 2026-05-01..2026-05-31 only; work_date 2026-06-15 is outside.
    schedule = create_and_publish_schedule(event["id"], rsp["id"])
    request = create_accepted_request(event["id"], host["id"], rsp["id"],
                                      latest_end_date="2026-06-18")
    crew = commit_crew(request["id"], rsp["id"])
    conduct_and_acknowledge_briefing(crew["id"], event["id"], host["id"])
    set_clock("2026-06-16T09:00:00Z")
    ts = create_submitted_timesheet(crew["id"], work_date="2026-06-15",
                                    day_classification="WORK", reported_work_minutes=480)
    resp = api_client.certify_timesheet(
        ts["id"], {"certifier_operator_ref": "HC-1"},
        make_host_coordinator_headers(host["id"]))
    validate_error(resp, ApiErrorId.ERR_NO_EFFECTIVE_SCHEDULE)


def test_aar_submit_with_crews_not_home_rejected():
    """PRD §3.9: "Submission requires that every crew on the event's requests
    has reached terminal mobility, `RETURNED` or `WITHDRAWN` — any crew still
    outstanding rejects the submission with `ERR_EVENT_NOT_FULLY_DEMOBILIZED`"

    Design: Corner/validations/val_aar_submit_crews_not_home_rejected
    """
    host = create_company()
    rsp = create_company(name="Responder Electric", company_code="RSP",
                         role_capability="RESPONDING", home_region="Inland")
    event = create_event(host["id"], activate=True)
    create_and_publish_schedule(event["id"], rsp["id"])
    request = create_accepted_request(event["id"], host["id"], rsp["id"])
    crew = commit_crew(request["id"], rsp["id"])
    arrive_crew(crew["id"], host["id"])
    resp = api_client.begin_demobilization(event["id"], make_host_coordinator_headers(host["id"]))
    assert resp.status_code == 200, f"Setup failed demobilizing: {resp.text}"
    aar = create_after_action_report(event["id"], host["id"], summary="early draft")
    resp = api_client.submit_after_action_report(
        aar["id"], make_host_coordinator_headers(host["id"]))
    validate_error(resp, ApiErrorId.ERR_EVENT_NOT_FULLY_DEMOBILIZED)
    resp = api_client.get_after_action_report(aar["id"], make_program_admin_headers())
    assert validate_success(resp)["status"] == "DRAFTING"
