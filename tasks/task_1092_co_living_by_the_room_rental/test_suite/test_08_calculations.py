"""Corner queue B — calculation correctness, boundaries, and input-set filtering."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    active_tenancy, base_portfolio, new_room, new_member, new_application,
    screen, decide, new_membership, do_move_in, new_invoice, open_ticket,
    resolve_ticket, file_incident, adjudicate, set_clock,
    read_membership, read_room, read_house, read_member, read_invoice, read_ticket,
    create_invoice_payload,
    manager_headers, compliance_headers, make_member_headers, finance_headers,
)


def test_maintenance_rent_credit_weighted_by_area_and_capped(api):
    """PRD §3.9: "the daily rate is the affected tenancy's pinned
    base_period_rate_cents divided by its period_days, rounded half up; the breach
    is converted to whole days by dividing breach_hours by twenty-four and rounding
    up to the next whole day; the raw credit is the daily rate multiplied by that
    breach-day count and by the area weight, rounded half up; and a cap equal to
    the tenancy's base_period_rate_cents times one quarter, rounded half up, bounds
    the result."

    Design: Corner/calculations/corner_maintenance_rent_credit_weighted_by_area_and_capped
    """
    ctx = active_tenancy(api, weekly=25000, monthly=100000, budget=60000)
    set_clock(api, "2026-06-02T00:00:00Z")
    ticket = open_ticket(api, ctx["house"]["id"], headers=make_member_headers(ctx["member"]["id"]),
                         area="SHARED_KITCHEN", severity="HIGH",
                         description="Only working oven is dead",
                         affected_membership_id=ctx["membership"]["id"])
    assert ticket["sla_deadline_at"] == "2026-06-05T00:00:00.000Z"
    set_clock(api, "2026-06-08T00:00:00Z")
    resolved = resolve_ticket(api, ticket["id"], resolution_note="New oven installed")
    assert resolved["breach_hours"] == 72
    assert resolved["rent_credit_cents"] == 5357
    assert resolved["status"] == "RESOLVED"
    assert resolved["resolved_at"] == "2026-06-08T00:00:00.000Z"


def test_maintenance_credit_zero_when_resolved_exactly_at_sla_deadline(api):
    """PRD §3.9: "breach_hours is that elapsed figure minus the severity's SLA
    window, floored at zero (never negative). If the ticket has no
    affected_membership_id, or if breach_hours is zero, the rent_credit_cents is
    zero."

    Design: Corner/calculations/corner_maintenance_credit_zero_when_resolved_exactly_at_sla_deadline
    """
    ctx = active_tenancy(api, weekly=25000, monthly=100000, budget=60000)
    set_clock(api, "2026-06-02T00:00:00Z")
    ticket = open_ticket(api, ctx["house"]["id"], headers=make_member_headers(ctx["member"]["id"]),
                         area="SHARED_KITCHEN", severity="HIGH", description="Fridge running warm",
                         affected_membership_id=ctx["membership"]["id"])
    set_clock(api, "2026-06-05T00:00:00Z")
    resolved = resolve_ticket(api, ticket["id"], resolution_note="Thermostat recalibrated")
    assert resolved["breach_hours"] == 0
    assert resolved["rent_credit_cents"] == 0
    assert resolved["status"] == "RESOLVED"
    assert read_ticket(api, ticket["id"])["sla_deadline_at"] == "2026-06-05T00:00:00.000Z"


def test_utility_share_denominator_counts_every_occupied_tenancy(api):
    """PRD §3.5: "occupied_rooms_at_period_start is the count of distinct
    memberships of the same house whose tenancy_status is ACTIVE or NOTICE_GIVEN
    and whose closed occupancy interval covers period_start". PRD §3.5: "The
    monthly utility slice is the house budget divided by the greater of that count
    and one, rounded up to the next whole cent."

    Design: Corner/calculations/corner_utility_share_denominator_counts_every_occupied_tenancy_in_the_house
    """
    ctx = active_tenancy(api, weekly=25000, monthly=100000, budget=60000)
    house_id, host_id = ctx["house"]["id"], ctx["host"]["id"]
    room2 = new_room(api, house_id, host_id, "102", weekly_rate_cents=20000,
                     monthly_rate_cents=80000, private_bath=False)
    bea = new_member(api, full_name="Bea Novak", email="bea@resident.example",
                     declared_monthly_income_cents=400000)
    app2 = new_application(api, bea["id"], room2["id"],
                           requested_move_in_date="2026-06-01", billing_cycle="WEEKLY")
    screen(api, app2["id"], verified_monthly_income_cents=400000, report_reference="SCR-B1")
    decide(api, app2["id"], decision="APPROVE")
    mem2 = new_membership(api, app2["id"], "2026-06-01")
    do_move_in(api, mem2["id"])
    inv2 = new_invoice(api, mem2["id"], "2026-06-01", "2026-06-07")
    assert inv2["occupied_rooms_at_period_start"] == 2
    assert inv2["utility_share_cents"] == 7000
    assert inv2["base_rent_cents"] == 20000 and inv2["subtotal_cents"] == 27000
    assert inv2["total_amount_cents"] == 27000
    inv1 = new_invoice(api, ctx["membership"]["id"], "2026-06-01", "2026-06-07")
    assert inv1["utility_share_cents"] == 7000 and inv1["base_rent_cents"] == 25000
    assert inv1["subtotal_cents"] == 32000
    assert read_membership(api, mem2["id"])["balance_due_cents"] == 27000
    assert read_membership(api, ctx["membership"]["id"])["balance_due_cents"] == 32000
    assert read_house(api, house_id)["occupied_room_count"] == 2


def test_monthly_membership_uses_thirty_day_period_not_calendar_month(api):
    """PRD §3.4: "period_days is fixed at 7 when the billing cycle is WEEKLY and 30
    when MONTHLY (calendar month length is never used)". PRD §3.5: "the inclusive
    length — period_end minus period_start plus one day — must equal the tenancy's
    period_days, seven for weekly and thirty for monthly (ERR_INVALID_PERIOD_LENGTH)."

    Design: Corner/calculations/corner_monthly_membership_uses_thirty_day_period_not_calendar_month
    """
    ctx = active_tenancy(api, billing_cycle="MONTHLY", weekly=30000, monthly=120000,
                         room_number="103", budget=60000, verified_income=500000,
                         declared_income=500000, member_name="Cyd Alvarez",
                         member_email="cyd@resident.example")
    mem = read_membership(api, ctx["membership"]["id"])
    assert mem["period_days"] == 30 and mem["base_period_rate_cents"] == 120000
    assert mem["deposit_cents"] == 30000
    inv = new_invoice(api, ctx["membership"]["id"], "2026-06-01", "2026-06-30")
    assert inv["utility_share_cents"] == 60000
    assert inv["subtotal_cents"] == 180000 and inv["total_amount_cents"] == 180000
    resp = api.create_invoice(
        create_invoice_payload(ctx["membership"]["id"], "2026-07-01", "2026-07-31"),
        finance_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_PERIOD_LENGTH.value)
    assert read_membership(api, ctx["membership"]["id"])["balance_due_cents"] == 180000


def test_strike_points_ignore_dismissed_incidents(api):
    """PRD §3.7: "Only UPHELD incidents count — REPORTED, DISPUTED, and DISMISSED
    contribute zero. The standing_band follows the total: GOOD at zero points,
    WATCH at one through five points, and PROBATION at six points or more."

    Design: Corner/calculations/corner_strike_points_ignore_dismissed_incidents
    """
    ctx = active_tenancy(api, weekly=25000, monthly=100000, budget=60000)
    set_clock(api, "2026-06-03T00:00:00Z")
    incA = file_incident(api, ctx["membership"]["id"], co="co-2", rule_code="CLEANLINESS",
                         severity="MINOR", description="Sink left full",
                         occurred_at="2026-06-02T09:00:00.000Z")
    incB = file_incident(api, ctx["membership"]["id"], co="co-2", rule_code="SMOKING",
                         severity="SEVERE", description="Cigarette smell reported in the hallway",
                         occurred_at="2026-06-02T22:00:00.000Z")
    upheld = adjudicate(api, incA["id"], "UPHOLD", co="co-1")
    dismissed = adjudicate(api, incB["id"], "DISMISS", co="co-1",
                           adjudication_note="no corroborating evidence")
    assert upheld["status"] == "UPHELD" and upheld["severity_points"] == 1
    assert dismissed["status"] == "DISMISSED" and dismissed["severity_points"] == 6
    m = read_member(api, ctx["member"]["id"])
    assert m["strike_points"] == 1 and m["standing_band"] == "WATCH"
    mem = read_membership(api, ctx["membership"]["id"])
    assert mem["tenancy_status"] == "ACTIVE" and mem["notice_reason"] is None
    assert read_house(api, ctx["house"]["id"])["compliance_posture"] == "OPEN"


def test_deposit_doubles_on_conditional_decision(api):
    """PRD §3.3: "The application lands in CONDITIONAL when the latest
    background_result is FLAGGED". PRD §3.3: "A CONDITIONAL decision sets it to the
    weekly rate multiplied by a conditional deposit multiple of two — a doubled
    deposit — rounded half up."

    Design: Corner/calculations/corner_deposit_doubles_on_conditional_decision
    """
    base = base_portfolio(api, clock="2026-06-01T00:00:00Z", budget=60000)
    room = new_room(api, base["house"]["id"], base["host"]["id"], "102",
                    weekly_rate_cents=20000, monthly_rate_cents=80000, private_bath=False)
    member = new_member(api, full_name="Bea Novak", email="bea@resident.example",
                        declared_monthly_income_cents=400000)
    app = new_application(api, member["id"], room["id"],
                          requested_move_in_date="2026-06-05", billing_cycle="WEEKLY")
    screen(api, app["id"], background_result="FLAGGED", verified_monthly_income_cents=400000,
           report_reference="SCR-B1")
    result = decide(api, app["id"], decision="APPROVE",
                    decision_note="flagged record, conditional offer")
    assert result["status"] == "CONDITIONAL"
    assert result["required_deposit_cents"] == 40000
    assert result["monthly_equivalent_cents"] == 86667 and result["required_income_cents"] == 260001
    assert read_room(api, room["id"])["occupancy_state"] == "VACANT"
