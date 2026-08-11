"""Composite setup helpers.

Every fixture builds its preconditions from scratch through the public API
(the harness restarts the server before every test, so each test starts
against an empty database). Setup calls use the lenient get_success_data
validator so failures surface as clear "Setup failed" errors.

Canonical scenario vocabulary shared by most fixtures:
  host utility "Host Power" (code HST), responding utility "Responder
  Electric" (code RSP), event "Hurricane Idalia" (premium window
  2026-05-02..2026-05-20 inclusive, mobilization deadline
  2026-05-10T18:00:00Z), schedule S1 (LINE 12000c/h, OT 1.5x, DT 2x,
  premium 10%, per-diem 8950c, single fee tier 800bps from 0).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    DEFAULTS,
    create_utility_company_payload,
    create_event_payload,
    create_billing_rate_schedule_payload,
    create_assistance_request_payload,
    create_crew_payload,
    create_safety_briefing_payload,
    create_timesheet_payload,
    create_lodging_block_payload,
    create_lodging_assignment_payload,
    create_per_diem_claim_payload,
    create_invoice_payload,
    create_after_action_report_payload,
)
from .test_users import (
    make_program_admin_headers,
    make_host_coordinator_headers,
    make_responding_coordinator_headers,
    make_crew_supervisor_headers,
    make_host_safety_officer_headers,
    make_host_finance_headers,
    make_responding_finance_headers,
)


def _setup_fail(step: str, resp) -> AssertionError:
    body = ""
    try:
        body = resp.text
    except Exception:
        pass
    return AssertionError(f"Setup failed at step '{step}': HTTP {resp.status_code} {body}")


def _ok(resp, step: str) -> dict:
    data = get_success_data(resp)
    if not isinstance(data, dict) or "id" not in data and resp.status_code not in (200, 201):
        raise _setup_fail(step, resp)
    return data


# ---------------------------------------------------------------------------
# Tier 1: base actors, event, clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str = "2026-05-01T08:00:00Z"):
    """Advance the program logical clock."""
    resp = api_client.set_clock(to_iso8601, make_program_admin_headers())
    if resp.status_code != 200:
        raise _setup_fail("set_clock", resp)
    return get_success_data(resp)


def create_company(name="Host Power", company_code="HST", role_capability="BOTH",
                   home_region="Coastal") -> dict:
    resp = api_client.create_utility_company(
        create_utility_company_payload(
            name=name, company_code=company_code,
            role_capability=role_capability, home_region=home_region,
        ),
        make_program_admin_headers(),
    )
    if resp.status_code != 201:
        raise _setup_fail("create_company", resp)
    return get_success_data(resp)


def create_event(host_id: str, activate: bool = False, set_clock_first: bool = False,
                 **overrides) -> dict:
    """Create an event; optionally activate it (OPEN -> ACTIVE)."""
    if set_clock_first:
        set_clock()
    payload = create_event_payload(host_utility_id=host_id, **overrides)
    resp = api_client.create_event(payload, make_program_admin_headers())
    if resp.status_code != 201:
        raise _setup_fail("create_event", resp)
    event = get_success_data(resp)
    if activate:
        resp = api_client.activate_event(event["id"], make_program_admin_headers())
        if resp.status_code != 200:
            raise _setup_fail("activate_event", resp)
        event = get_success_data(resp)
    return event


def setup_companies(host_code="HST", rsp_code="RSP"):
    """Create the host and responding utility companies. Returns (host, rsp)."""
    host = create_company(name="Host Power", company_code=host_code,
                          role_capability="BOTH", home_region="Coastal")
    rsp = create_company(name="Responder Electric", company_code=rsp_code,
                         role_capability="RESPONDING", home_region="Inland")
    return host, rsp


def setup_event_active(set_clock_first=True, **event_overrides):
    """Host + responding companies and an ACTIVE event.

    Returns (host, rsp, event).
    """
    if set_clock_first:
        set_clock()
    host, rsp = setup_companies()
    event = create_event(host["id"], activate=True, **event_overrides)
    return host, rsp, event


# ---------------------------------------------------------------------------
# Tier 2: rate schedule
# ---------------------------------------------------------------------------

def create_and_publish_schedule(event_id: str, rsp_id: str, set_clock_first: bool = False,
                                **overrides) -> dict:
    """Create a DRAFT schedule for (event, caller's responding utility) and publish it."""
    if set_clock_first:
        set_clock()
    payload = create_billing_rate_schedule_payload(event_id=event_id, **overrides)
    resp = api_client.create_billing_rate_schedule(
        payload, make_responding_coordinator_headers(rsp_id))
    if resp.status_code != 201:
        raise _setup_fail("create_billing_rate_schedule", resp)
    schedule = get_success_data(resp)
    resp = api_client.publish_billing_rate_schedule(
        schedule["id"], {}, make_responding_coordinator_headers(rsp_id))
    if resp.status_code != 200:
        raise _setup_fail("publish_billing_rate_schedule", resp)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2/3: request negotiation to ACCEPTED, plus crew commitment
# ---------------------------------------------------------------------------

def create_request(event_id: str, host_id: str, rsp_id: str, submit: bool = True,
                   **overrides) -> dict:
    payload = create_assistance_request_payload(
        event_id=event_id, responding_utility_id=rsp_id, **overrides)
    resp = api_client.create_assistance_request(payload, make_host_coordinator_headers(host_id))
    if resp.status_code != 201:
        raise _setup_fail("create_assistance_request", resp)
    request = get_success_data(resp)
    if submit:
        resp = api_client.submit_assistance_request(request["id"], {}, make_host_coordinator_headers(host_id))
        if resp.status_code != 200:
            raise _setup_fail("submit_assistance_request", resp)
        request = get_success_data(resp)
    return request


def create_accepted_request(event_id: str, host_id: str, rsp_id: str, **overrides) -> dict:
    """Request walked DRAFT -> SUBMITTED -> ACCEPTED (requires a published schedule)."""
    request = create_request(event_id, host_id, rsp_id, submit=True, **overrides)
    resp = api_client.accept_assistance_request(
        request["id"], make_responding_coordinator_headers(rsp_id))
    if resp.status_code != 200:
        raise _setup_fail("accept_assistance_request", resp)
    return get_success_data(resp)


def setup_event_with_accepted_request(set_clock_first=True, **request_overrides):
    """Host + rsp + ACTIVE event + published S1 schedule + ACCEPTED request.

    Returns dict(host, rsp, event, schedule, request).
    """
    host, rsp, event = setup_event_active(set_clock_first=set_clock_first)
    schedule = create_and_publish_schedule(event["id"], rsp["id"])
    request = create_accepted_request(event["id"], host["id"], rsp["id"], **request_overrides)
    return {
        "host": host, "rsp": rsp, "event": event,
        "schedule": schedule, "request": request,
    }


def commit_crew(request_id: str, rsp_id: str, **overrides) -> dict:
    payload = create_crew_payload(request_id=request_id, **overrides)
    resp = api_client.create_crew(payload, make_responding_coordinator_headers(rsp_id))
    if resp.status_code != 201:
        raise _setup_fail("create_crew", resp)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 3: crew lifecycle — briefing, acknowledgment, arrival
# ---------------------------------------------------------------------------

def conduct_and_acknowledge_briefing(crew_id: str, event_id: str, host_id: str,
                                     conductor_ref="OFF-1", supervisor_ref="SUP-1",
                                     **overrides) -> dict:
    """Briefing CONDUCTED then ACKNOWLEDGED; crew becomes CLEARED_TO_WORK."""
    payload = create_safety_briefing_payload(
        crew_id=crew_id, event_id=event_id,
        conductor_operator_ref=conductor_ref, **overrides)
    resp = api_client.create_safety_briefing(payload, make_host_safety_officer_headers(host_id))
    if resp.status_code != 201:
        raise _setup_fail("create_safety_briefing", resp)
    briefing = get_success_data(resp)
    resp = api_client.acknowledge_safety_briefing(
        briefing["id"], {"supervisor_operator_ref": supervisor_ref},
        make_crew_supervisor_headers(crew_id))
    if resp.status_code != 200:
        raise _setup_fail("acknowledge_safety_briefing", resp)
    return get_success_data(resp)


def arrive_crew(crew_id: str, host_id: str) -> dict:
    resp = api_client.confirm_arrival(crew_id, make_host_coordinator_headers(host_id))
    if resp.status_code != 200:
        raise _setup_fail("confirm_arrival", resp)
    return get_success_data(resp)


def setup_cleared_arrived_crew(equipment_daily_rate_cents=None, set_clock_first=True,
                               clock_after_arrival=None, **request_overrides):
    """Full scenario through one ARRIVED + CLEARED_TO_WORK crew.

    equipment_daily_rate_cents: when given, the crew carries one bucket truck
    at that daily rate (35000 in the canonical scenario).
    clock_after_arrival: optional ISO instant the clock is advanced to after arrival.

    Returns dict(host, rsp, event, schedule, request, crew, briefing).
    """
    ctx = setup_event_with_accepted_request(set_clock_first=set_clock_first, **request_overrides)
    equipment_units = []
    if equipment_daily_rate_cents is not None:
        equipment_units = [{
            "unit_type": "bucket_truck", "unit_ref": "BT-1",
            "daily_rate_cents": equipment_daily_rate_cents,
        }]
    crew = commit_crew(ctx["request"]["id"], ctx["rsp"]["id"], equipment_units=equipment_units)
    briefing = conduct_and_acknowledge_briefing(crew["id"], ctx["event"]["id"], ctx["host"]["id"])
    crew = arrive_crew(crew["id"], ctx["host"]["id"])
    if clock_after_arrival is not None:
        set_clock(clock_after_arrival)
    ctx.update({"crew": crew, "briefing": briefing})
    return ctx


# ---------------------------------------------------------------------------
# Tier 3/4: timesheets and per-diem claims
# ---------------------------------------------------------------------------

def create_submitted_timesheet(crew_id: str, work_date="2026-05-04",
                               day_classification="WORK", reported_work_minutes=600,
                               reported_travel_minutes=None,
                               submitted_by="SUP-1") -> dict:
    payload = create_timesheet_payload(
        crew_id=crew_id, work_date=work_date, day_classification=day_classification,
        reported_work_minutes=reported_work_minutes,
    )
    if reported_travel_minutes is not None:
        payload["reported_travel_minutes"] = reported_travel_minutes
    if day_classification == "TRAVEL":
        payload.pop("reported_work_minutes", None)
        payload.setdefault("reported_travel_minutes", reported_travel_minutes or 300)
    resp = api_client.create_timesheet(payload, make_crew_supervisor_headers(crew_id))
    if resp.status_code != 201:
        raise _setup_fail("create_timesheet", resp)
    ts = get_success_data(resp)
    resp = api_client.submit_timesheet(
        ts["id"], {"submitted_by_operator_ref": submitted_by},
        make_crew_supervisor_headers(crew_id))
    if resp.status_code != 200:
        raise _setup_fail("submit_timesheet", resp)
    return get_success_data(resp)


def certify_timesheet(ts_id: str, host_id: str, certifier_ref="HC-1") -> dict:
    resp = api_client.certify_timesheet(
        ts_id, {"certifier_operator_ref": certifier_ref},
        make_host_coordinator_headers(host_id))
    if resp.status_code != 200:
        raise _setup_fail("certify_timesheet", resp)
    return get_success_data(resp)


def create_approved_claim(crew_id: str, rsp_id: str, host_id: str,
                          claim_date="2026-05-03", member_count=1,
                          meals_provided_count=0, day_factor_type="TRAVEL",
                          receipts_total_cents=None) -> dict:
    payload = create_per_diem_claim_payload(
        crew_id=crew_id, claim_date=claim_date, member_count=member_count,
        meals_provided_count=meals_provided_count, day_factor_type=day_factor_type,
    )
    if receipts_total_cents is not None:
        payload["receipts_total_cents"] = receipts_total_cents
    resp = api_client.create_per_diem_claim(payload, make_responding_coordinator_headers(rsp_id))
    if resp.status_code != 201:
        raise _setup_fail("create_per_diem_claim", resp)
    claim = get_success_data(resp)
    resp = api_client.approve_per_diem_claim(claim["id"], make_host_coordinator_headers(host_id))
    if resp.status_code != 200:
        raise _setup_fail("approve_per_diem_claim", resp)
    claim = get_success_data(resp)
    claim_id = claim["id"]
    claim["id"] = claim_id
    return claim


# ---------------------------------------------------------------------------
# Tier 5: demobilized event + canonical certified rows + invoice lifecycle
# ---------------------------------------------------------------------------

def setup_demobilized_with_certified_rows(equipment_daily_rate_cents=35000,
                                          clock_start="2026-05-01T08:00:00Z",
                                          certify_clock="2026-05-05T09:00:00Z",
                                          **request_overrides):
    """Canonical billing scenario.

    Event ACTIVE -> one ARRIVED+CLEARED crew -> clock to certify_clock ->
    T1 (WORK 600 on 2026-05-04) CERTIFIED (180200 with the canonical
    equipment/rates) -> P1 (TRAVEL per-diem 2026-05-03, 1 member, 0 meals)
    APPROVED (6713) -> event DEMOBILIZING.

    Returns dict(host, rsp, event, schedule, request, crew, briefing, ts1, pd1).
    """
    set_clock(clock_start)
    ctx = setup_cleared_arrived_crew(
        equipment_daily_rate_cents=equipment_daily_rate_cents,
        set_clock_first=False,
        clock_after_arrival=certify_clock,
        **request_overrides,
    )
    ts1 = create_submitted_timesheet(ctx["crew"]["id"], work_date="2026-05-04",
                                     day_classification="WORK", reported_work_minutes=600)
    ts1 = certify_timesheet(ts1["id"], ctx["host"]["id"])
    pd1 = create_approved_claim(ctx["crew"]["id"], ctx["rsp"]["id"], ctx["host"]["id"],
                                claim_date="2026-05-03")
    resp = api_client.begin_demobilization(
        ctx["event"]["id"], make_host_coordinator_headers(ctx["host"]["id"]))
    if resp.status_code != 200:
        raise _setup_fail("begin_demobilization", resp)
    ctx["event"] = get_success_data(resp)
    ctx.update({"ts1": ts1, "pd1": pd1})
    return ctx


def create_draft_invoice(request_id: str, schedule_id: str, rsp_id: str,
                         period_start="2026-05-01", period_end="2026-05-31") -> dict:
    resp = api_client.create_invoice(
        create_invoice_payload(
            request_id=request_id, rate_schedule_id=schedule_id,
            billing_period_start=period_start, billing_period_end=period_end,
        ),
        make_responding_finance_headers(rsp_id),
    )
    if resp.status_code != 201:
        raise _setup_fail("create_invoice", resp)
    return get_success_data(resp)


def submit_invoice(inv_id: str, rsp_id: str) -> dict:
    resp = api_client.submit_invoice(inv_id, make_responding_finance_headers(rsp_id))
    if resp.status_code != 200:
        raise _setup_fail("submit_invoice", resp)
    return get_success_data(resp)


def setup_submitted_invoice(**kwargs):
    """Canonical scenario through a SUBMITTED invoice of final_total 201866.

    Returns dict(..., invoice) with invoice.status == SUBMITTED and
    outstanding_cents == 201866.
    """
    ctx = setup_demobilized_with_certified_rows(**kwargs)
    invoice = create_draft_invoice(ctx["request"]["id"], ctx["schedule"]["id"], ctx["rsp"]["id"])
    invoice = submit_invoice(invoice["id"], ctx["rsp"]["id"])
    ctx["invoice"] = invoice
    return ctx


def setup_approved_invoice(**kwargs):
    """Canonical scenario through an APPROVED invoice (outstanding 201866)."""
    ctx = setup_submitted_invoice(**kwargs)
    resp = api_client.approve_invoice(
        ctx["invoice"]["id"], {"approver_operator_ref": "FIN-9"},
        make_host_finance_headers(ctx["host"]["id"]))
    if resp.status_code != 200:
        raise _setup_fail("approve_invoice", resp)
    ctx["invoice"] = get_success_data(resp)
    return ctx


# ---------------------------------------------------------------------------
# Lodging helpers
# ---------------------------------------------------------------------------

def create_lodging_block(event_id: str, host_id: str, **overrides) -> dict:
    resp = api_client.create_lodging_block(
        create_lodging_block_payload(event_id=event_id, **overrides),
        make_host_coordinator_headers(host_id))
    if resp.status_code != 201:
        raise _setup_fail("create_lodging_block", resp)
    return get_success_data(resp)


def create_lodging_assignment(block_id: str, crew_id: str, host_id: str, **overrides) -> dict:
    resp = api_client.create_lodging_assignment(
        create_lodging_assignment_payload(block_id=block_id, crew_id=crew_id, **overrides),
        make_host_coordinator_headers(host_id))
    if resp.status_code != 201:
        raise _setup_fail("create_lodging_assignment", resp)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# After-action report helpers
# ---------------------------------------------------------------------------

def create_after_action_report(event_id: str, host_id: str, summary="Idalia response",
                               **overrides) -> dict:
    resp = api_client.create_after_action_report(
        create_after_action_report_payload(event_id=event_id, summary=summary, **overrides),
        make_host_coordinator_headers(host_id))
    if resp.status_code != 201:
        raise _setup_fail("create_after_action_report", resp)
    return get_success_data(resp)
