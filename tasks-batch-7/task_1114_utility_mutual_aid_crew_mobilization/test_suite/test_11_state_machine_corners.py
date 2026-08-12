"""Corner tests for state machine initial states, terminal lockdowns, invalid
transitions, precondition gates, valid cycles, and parent auto-transitions
(PRD §3.1, §3.3, §3.4, §3.6, §3.7, §3.8, §3.9)."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, ApiErrorId,
    make_program_admin_headers, make_host_coordinator_headers,
    make_responding_coordinator_headers, make_crew_supervisor_headers,
    make_host_finance_headers, make_responding_finance_headers,
    set_clock, create_company, create_event, create_and_publish_schedule,
    create_request, create_accepted_request, commit_crew,
    conduct_and_acknowledge_briefing, arrive_crew, create_submitted_timesheet,
    certify_timesheet, create_approved_claim, create_draft_invoice,
    submit_invoice, setup_event_active, setup_event_with_accepted_request,
    setup_cleared_arrived_crew, setup_submitted_invoice,
    create_assistance_request_payload, create_timesheet_payload,
)


def test_request_created_in_draft_with_zero_round():
    """PRD §3.3: "A new request is a `DRAFT` with `amendment_round` zero, empty
    `counter_terms`, and all derived counts at zero."

    Design: Corner/state_machines/sm_request_initial_state_draft
    """
    host, rsp, event = setup_event_active()
    resp = api_client.create_assistance_request(
        create_assistance_request_payload(event_id=event["id"],
                                          responding_utility_id=rsp["id"]),
        make_host_coordinator_headers(host["id"]))
    request = validate_success(resp, expected_status=201)
    assert request["status"] == "DRAFT"
    assert request["amendment_round"] == 0
    assert request["counter_terms"] is None


def test_declined_request_cannot_be_accepted():
    """PRD §3.3: "`DECLINED` and `CANCELLED` are terminal" — accepting a
    DECLINED request is a state-legality violation rejected with
    `ERR_INVALID_STATE_TRANSITION` per §2.9.

    Design: Corner/state_machines/sm_declined_request_cannot_be_accepted
    """
    # Build: request SUBMITTED then DECLINED (schedule published so the schedule
    # precondition would otherwise pass).
    host, rsp, event = setup_event_active()
    create_and_publish_schedule(event["id"], rsp["id"])
    request = create_request(event["id"], host["id"], rsp["id"], submit=True)
    resp = api_client.decline_assistance_request(
        request["id"], {"reason": "mutual fatigue"},
        make_responding_coordinator_headers(rsp["id"]))
    assert validate_success(resp)["status"] == "DECLINED"
    resp = api_client.accept_assistance_request(
        request["id"], make_responding_coordinator_headers(rsp["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


def test_release_before_arrival_rejected():
    """PRD §3.7: "Release moves mobility from `ARRIVED` to `DEMOBILIZING`" —
    releasing a still-`COMMITTED` crew is not a permitted transition, rejected
    with `ERR_INVALID_STATE_TRANSITION` per §2.9.

    Design: Corner/state_machines/sm_release_before_arrival_rejected
    """
    ctx = setup_event_with_accepted_request()
    crew = commit_crew(ctx["request"]["id"], ctx["rsp"]["id"])
    resp = api_client.release_crew(crew["id"], make_host_coordinator_headers(ctx["host"]["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    resp = api_client.get_crew(crew["id"], make_program_admin_headers())
    assert validate_success(resp)["mobility_status"] == "COMMITTED"


def test_event_close_blocked_without_accepted_report():
    """PRD §3.9: "closing the event — a `ProgramAdmin` action moving it from
    `DEMOBILIZING` to `CLOSED` — requires an `ACCEPTED` after-action report for
    the event and every invoice on the event's requests standing at `PAID` or
    `VOID`; either gap rejects the close with `ERR_EVENT_CLOSE_BLOCKED`."

    Design: Corner/state_machines/sm_event_close_blocked_without_aar
    """
    host = create_company()
    event = create_event(host["id"], activate=True)
    resp = api_client.begin_demobilization(event["id"], make_host_coordinator_headers(host["id"]))
    assert resp.status_code == 200, f"Setup failed demobilizing: {resp.text}"
    resp = api_client.close_event(event["id"], make_program_admin_headers())
    validate_error(resp, ApiErrorId.ERR_EVENT_CLOSE_BLOCKED)
    resp = api_client.get_event(event["id"], make_program_admin_headers())
    assert validate_success(resp)["status"] == "DEMOBILIZING"


def test_invoice_dispute_cycle_applies_credit():
    """PRD §3.8: "The host may accept the proposal — `applied_credit_total_cents`
    grows by the proposed credit, `outstanding_cents` shrinks by the same amount,
    the dispute fields are cleared, and the invoice returns to `SUBMITTED`"

    Design: Corner/state_machines/sm_invoice_dispute_cycle_credit_applied
    """
    ctx = setup_submitted_invoice()
    inv_id = ctx["invoice"]["id"]
    resp = api_client.dispute_invoice(
        inv_id, {"reason": "HOURS_MISMATCH", "disputed_amount_cents": 50000},
        make_host_finance_headers(ctx["host"]["id"]))
    assert validate_success(resp)["status"] == "DISPUTED"
    resp = api_client.propose_credit(
        inv_id, {"credit_cents": 20000},
        make_responding_finance_headers(ctx["rsp"]["id"]))
    assert validate_success(resp)["status"] == "CREDIT_PROPOSED"
    resp = api_client.accept_credit(inv_id, make_host_finance_headers(ctx["host"]["id"]))
    invoice = validate_success(resp)
    assert invoice["status"] == "SUBMITTED"
    assert invoice["applied_credit_total_cents"] == 20000
    assert invoice["outstanding_cents"] == 181866
    assert invoice["disputed_amount_cents"] is None
    assert invoice["proposed_credit_cents"] is None


def test_timesheet_reject_revise_recertify_cycle():
    """PRD §3.6: "rejection by the host coordinator — optionally with a `reason`
    — moves it to `REJECTED`, and revision by the supervisor returns a
    `REJECTED` sheet to `DRAFT`, replacing prior values with any
    `day_classification`, `reported_work_minutes`, or `reported_travel_minutes`
    supplied in the correction."

    Design: Corner/state_machines/sm_timesheet_reject_revise_recertify_cycle
    """
    set_clock("2026-05-05T09:00:00Z")
    ctx = setup_cleared_arrived_crew(equipment_daily_rate_cents=35000,
                                     set_clock_first=False)
    ts = create_submitted_timesheet(ctx["crew"]["id"], work_date="2026-05-04",
                                    day_classification="WORK", reported_work_minutes=480)
    resp = api_client.reject_timesheet(ts["id"], {"reason": "hours look low"},
                                       make_host_coordinator_headers(ctx["host"]["id"]))
    assert validate_success(resp)["status"] == "REJECTED"
    resp = api_client.revise_timesheet(ts["id"], {"reported_work_minutes": 600},
                                       make_crew_supervisor_headers(ctx["crew"]["id"]))
    assert validate_success(resp)["status"] == "DRAFT"
    resp = api_client.submit_timesheet(ts["id"], {"submitted_by_operator_ref": "SUP-1"},
                                       make_crew_supervisor_headers(ctx["crew"]["id"]))
    assert resp.status_code == 200
    ts = certify_timesheet(ts["id"], ctx["host"]["id"])
    assert ts["status"] == "CERTIFIED"
    assert ts["certified_amount_cents"] == 180200  # corrected 600 minutes priced


def test_double_accept_rejected():
    """PRD §3.3: "Acceptance by the responding coordinator moves `SUBMITTED` to
    `ACCEPTED`" — a second acceptance against an already `ACCEPTED` request is
    a state-legality violation rejected with `ERR_INVALID_STATE_TRANSITION`
    per §2.9.

    Design: Corner/state_machines/sm_double_accept_rejected
    """
    ctx = setup_event_with_accepted_request()
    resp = api_client.accept_assistance_request(
        ctx["request"]["id"], make_responding_coordinator_headers(ctx["rsp"]["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


def test_request_bubbles_to_fulfilled_on_first_cleared_arrival():
    """PRD §3.4: "the request itself advances — from `ACCEPTED` to
    `IN_PROGRESS` on its first arrival, and onward from `IN_PROGRESS` to
    `FULFILLED` the moment the deployable count reaches
    `required_minimum_crews`." PRD §3.3: "the stricter `deployable_crew_count`
    tallies only crews that have both `ARRIVED` and `CLEARED_TO_WORK`"

    Design: Corner/state_machines/sm_request_fulfilled_bubble_up
    """
    set_clock("2026-05-01T08:00:00Z")
    ctx = setup_event_with_accepted_request(set_clock_first=False)
    crew = commit_crew(ctx["request"]["id"], ctx["rsp"]["id"])
    conduct_and_acknowledge_briefing(crew["id"], ctx["event"]["id"], ctx["host"]["id"])
    arrive_crew(crew["id"], ctx["host"]["id"])
    resp = api_client.get_assistance_request(ctx["request"]["id"], make_program_admin_headers())
    request = validate_success(resp)
    assert request["status"] == "FULFILLED"
    assert request["deployable_crew_count"] == 1


def test_cancel_from_countered_reconciles_open_count():
    """PRD §3.3: "or cancelled by the host coordinator from `DRAFT`,
    `SUBMITTED`, or `COUNTERED`" and "every acceptance, decline, and
    cancellation recomputes the event's open-request count" PRD §2.8: "The
    `open_request_count` itself counts the event's assistance requests whose
    `status` is `SUBMITTED` or `COUNTERED`."

    Design: Corner/state_machines/sm_cancel_from_countered
    """
    host, rsp, event = setup_event_active()
    request = create_request(event["id"], host["id"], rsp["id"], submit=True)
    resp = api_client.counter_assistance_request(
        request["id"], {"counter_crews": [{"crew_type": "LINE", "count": 1}]},
        make_responding_coordinator_headers(rsp["id"]))
    assert validate_success(resp)["status"] == "COUNTERED"
    resp = api_client.cancel_assistance_request(
        request["id"], make_host_coordinator_headers(host["id"]))
    assert validate_success(resp)["status"] == "CANCELLED"
    resp = api_client.get_event(event["id"], make_program_admin_headers())
    assert validate_success(resp)["open_request_count"] == 0
