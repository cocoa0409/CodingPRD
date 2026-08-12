"""Corner tests for the pricing calculations: TRAVEL and STANDBY day branches,
the premium window's inclusive end, and invoice period input filtering
(PRD §3.6, §3.8)."""
import pytest

from test_helpers import (
    api_client, validate_success, get_success_data,
    make_program_admin_headers, make_host_coordinator_headers,
    make_responding_coordinator_headers, make_responding_finance_headers,
    set_clock, create_company, create_event, create_and_publish_schedule,
    create_accepted_request, commit_crew, conduct_and_acknowledge_briefing,
    arrive_crew, create_submitted_timesheet, certify_timesheet,
    create_draft_invoice, setup_cleared_arrived_crew,
)


def test_travel_day_flat_rate_no_premium_no_equipment():
    """PRD §3.6: "A `TRAVEL` day bills travel time only:
    `reported_travel_minutes` multiplied by the line's `hourly_rate_cents` and
    divided by sixty, rounded half-up to whole cents — no overtime, no storm
    premium, and no equipment charge ever applies to a travel day."

    Design: Corner/calculations/calc_travel_day_flat_rate_no_premium
    """
    ctx = setup_cleared_arrived_crew(equipment_daily_rate_cents=35000)
    ts = create_submitted_timesheet(ctx["crew"]["id"], work_date="2026-05-04",
                                    day_classification="TRAVEL",
                                    reported_travel_minutes=300)
    ts = certify_timesheet(ts["id"], ctx["host"]["id"])
    # 300 * 12000 / 60 = 60000; no premium, no equipment
    assert ts["certified_amount_cents"] == 60000


def test_standby_day_flat_eight_hours_plus_equipment():
    """PRD §3.6: "A `STANDBY` day bills a flat eight hours: 480 minutes at the
    base rate, divided by sixty and rounded half-up, with reported minutes
    ignored and no premium applied, and then the crew's
    `equipment_daily_total_cents` is added."

    Design: Corner/calculations/calc_standby_day_flat_8h_plus_equipment
    """
    ctx = setup_cleared_arrived_crew(equipment_daily_rate_cents=35000)
    ts = create_submitted_timesheet(ctx["crew"]["id"], work_date="2026-05-04",
                                    day_classification="STANDBY",
                                    reported_work_minutes=120)
    ts = certify_timesheet(ts["id"], ctx["host"]["id"])
    # 480 * 12000 / 60 = 96000; + 35000 equipment; reported 120 ignored
    assert ts["certified_amount_cents"] == 131000


def test_premium_window_inclusive_end_boundary():
    """PRD §3.1: "work performed on or after `premium_window_start` and on or
    before `premium_window_end` — both bounds inclusive — earns the schedule's
    storm premium." PRD §3.6: "when the `work_date` falls inside the event's
    premium window — on or after `premium_window_start`, on or before
    `premium_window_end` — that already-rounded labor is uplifted by
    `storm_premium_bps` ten-thousandths and rounded half-up once more."

    Design: Corner/calculations/calc_premium_window_inclusive_end_boundary
    """
    ctx = setup_cleared_arrived_crew(latest_end_date="2026-05-25")
    ts_in = create_submitted_timesheet(ctx["crew"]["id"], work_date="2026-05-20",
                                       day_classification="WORK", reported_work_minutes=480)
    ts_out = create_submitted_timesheet(ctx["crew"]["id"], work_date="2026-05-21",
                                        day_classification="WORK", reported_work_minutes=480)
    ts_in = certify_timesheet(ts_in["id"], ctx["host"]["id"])
    ts_out = certify_timesheet(ts_out["id"], ctx["host"]["id"])
    # In-window: 96000 * 1.1 = 105600; outside window: 96000 (no premium).
    assert ts_in["certified_amount_cents"] == 105600
    assert ts_out["certified_amount_cents"] == 96000


def test_invoice_period_excludes_out_of_period_timesheet():
    """PRD §3.8: "`labor_subtotal_cents` sums `certified_amount_cents` over the
    request's crews' `CERTIFIED` timesheets whose `work_date` falls inside the
    billing period and whose `billed_invoice_id` is still empty" and "Submission
    sweeps the covered rows — stamping `billed_invoice_id` on each swept
    timesheet" — a certified sheet outside the period is neither summed nor
    swept.

    Design: Corner/calculations/calc_invoice_input_set_excludes_out_of_period
    """
    set_clock("2026-05-01T08:00:00Z")
    host = create_company(name="Host Power", company_code="HST",
                          role_capability="BOTH", home_region="Coastal")
    rsp = create_company(name="Responder Electric", company_code="RSP",
                         role_capability="RESPONDING", home_region="Inland")
    event = create_event(host["id"], activate=True)
    schedule = create_and_publish_schedule(event["id"], rsp["id"])
    request = create_accepted_request(event["id"], host["id"], rsp["id"])
    crew = commit_crew(request["id"], rsp["id"])  # no equipment
    conduct_and_acknowledge_briefing(crew["id"], event["id"], host["id"])
    arrive_crew(crew["id"], host["id"])
    set_clock("2026-05-07T09:00:00Z")
    ts1 = create_submitted_timesheet(crew["id"], work_date="2026-05-04",
                                     day_classification="WORK", reported_work_minutes=600)
    ts1 = certify_timesheet(ts1["id"], host["id"])
    # No equipment: 600 min WORK in window = 145200
    assert ts1["certified_amount_cents"] == 145200
    ts2 = create_submitted_timesheet(crew["id"], work_date="2026-05-06",
                                     day_classification="WORK", reported_work_minutes=480)
    ts2 = certify_timesheet(ts2["id"], host["id"])
    resp = api_client.begin_demobilization(event["id"], make_host_coordinator_headers(host["id"]))
    assert resp.status_code == 200, f"Setup failed demobilizing: {resp.text}"
    invoice = create_draft_invoice(request["id"], schedule["id"], rsp["id"],
                                   period_start="2026-05-01", period_end="2026-05-04")
    resp = api_client.submit_invoice(invoice["id"], make_responding_finance_headers(rsp["id"]))
    invoice = validate_success(resp)
    assert invoice["labor_subtotal_cents"] == 145200
    assert invoice["mobilization_fee_cents"] == 11616  # round(145200*800/10000)
    assert invoice["final_total_cents"] == 156816
    resp = api_client.get_timesheet(ts2["id"], make_program_admin_headers())
    assert validate_success(resp)["billed_invoice_id"] is None
