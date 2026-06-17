"""State-machine transitions, incident lifecycle, gate events, and derivable
calculation outputs.

Corner queue (B): state_machines, calculations, and endpoints sections.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, assert_festival,
    assert_incident, assert_addon, assert_performance,
    create_festival, create_zone, create_stage, create_parking_lot, open_sales,
    go_live, open_day, weather_hold, create_festival_with_zone_and_stage,
    create_on_sale_festival, sell_ticket, issue_wristband, activate_wristband, topup,
    setup_live_festival_with_active_wristband, setup_approved_application,
    schedule_performance, sell_parking_addon, gate_enter,
    create_incident_payload, create_camping_area, TEST_USERS,
)

_DIRECTOR = TEST_USERS["director_headers"]
_BOXOFFICE = TEST_USERS["boxoffice_headers"]
_VENDOR_MANAGER = TEST_USERS["vendor_manager_headers"]
_GATE = TEST_USERS["gate_attendant_headers"]


# ─── state_machines / open_sales_from_planning_succeeds ───

def test_open_sales_from_planning(api):
    """PRD §3.1: "From `PLANNING`, opening sales moves the festival to `ON_SALE`, but
    only if the festival already has at least one zone and at least one stage; this
    transition is what makes ticket sales permissible to the box office."

    Opening sales on a PLANNING festival that has a zone and a stage moves the
    operational_posture to ON_SALE.

    Design: Corner/state_machines/open_sales_from_planning_succeeds
    """
    festival, zone, stage = create_festival_with_zone_and_stage(start_date="2026-08-01",
                                                                end_date="2026-08-02",
                                                                name="OpenS F")
    res = api.open_sales(festival["id"], _DIRECTOR)
    after = validate_success(res, 200)
    assert_festival(after)
    assert after["operational_posture"] == "ON_SALE"


# ─── state_machines / go_live_from_planning_invalid_state ───

def test_go_live_from_planning_invalid_state(api):
    """PRD §3.1: "Every posture transition is guarded. Attempting a transition from a
    posture in which it is not defined — for example resuming a festival that is not
    suspended, or closing one that is not live — is rejected with `ERR_INVALID_STATE`."

    Going live while the festival is still PLANNING (sales never opened) is rejected
    with ERR_INVALID_STATE (409).

    Design: Corner/state_machines/go_live_from_planning_invalid_state
    """
    festival, zone, stage = create_festival_with_zone_and_stage(start_date="2026-08-01",
                                                                end_date="2026-08-02",
                                                                name="BadLive F")
    res = api.go_live(festival["id"], _DIRECTOR)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ─── state_machines / resolve_from_resolved_terminal_lockdown ───

def test_resolve_already_resolved_incident_invalid_state(api):
    """PRD §3.10: "An incident may be resolved to the terminal `RESOLVED` from either
    `OPEN` or `ESCALATED` ... A transition attempted from a state where it is not
    defined is rejected with `ERR_INVALID_STATE`."

    Resolving an incident that is already RESOLVED (a terminal state) is rejected with
    ERR_INVALID_STATE (409).

    Design: Corner/state_machines/resolve_from_resolved_terminal_lockdown
    """
    festival = create_festival(start_date="2026-08-01", end_date="2026-08-02", name="Inc F")
    incident = validate_success(api.create_incident(
        festival["id"], create_incident_payload("LOST_CHILD", "LOW"), _GATE), 201)
    validate_success(api.resolve_incident(incident["id"], _GATE), 200)
    res = api.resolve_incident(incident["id"], _GATE)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ─── state_machines / escalate_low_severity_incident_invalid_state ───

def test_escalate_low_severity_incident_invalid_state(api):
    """PRD §3.10: "From `OPEN`, it may be escalated to `ESCALATED`, but only when its
    `severity` is `HIGH` or `CRITICAL`; escalation is open to a director or a gate
    attendant. ... A transition attempted from a state where it is not defined is
    rejected with `ERR_INVALID_STATE`."

    Escalating a LOW-severity OPEN incident violates the severity precondition and is
    rejected with ERR_INVALID_STATE (409).

    Design: Corner/state_machines/escalate_low_severity_incident_invalid_state
    """
    festival = create_festival(start_date="2026-08-01", end_date="2026-08-02", name="Esc F")
    incident = validate_success(api.create_incident(
        festival["id"], create_incident_payload("MEDICAL", "LOW"), _GATE), 201)
    res = api.escalate_incident(incident["id"], _GATE)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ─── state_machines / incident_revert_escalated_to_open ───

def test_incident_deescalate_back_to_open(api):
    """PRD §3.10: "From `ESCALATED`, only a `FestivalDirector` may de-escalate it back
    to `OPEN`."

    De-escalating an ESCALATED incident returns its status to OPEN (the revert edge).

    Design: Corner/state_machines/incident_revert_escalated_to_open
    """
    festival = create_festival(start_date="2026-08-01", end_date="2026-08-02", name="Deesc F")
    incident = validate_success(api.create_incident(
        festival["id"], create_incident_payload("MEDICAL", "HIGH"), _GATE), 201)
    validate_success(api.escalate_incident(incident["id"], _GATE), 200)
    res = api.deescalate_incident(incident["id"], _DIRECTOR)
    reverted = validate_success(res, 200)
    assert_incident(reverted)
    assert reverted["status"] == "OPEN"


# ─── state_machines / gate_exit_allowed_while_suspended ───

def test_gate_exit_allowed_while_suspended(api):
    """PRD §3.7: "An exit scan requires the wristband to be `INSIDE`, moves
    `presence_status` back to `OUTSIDE`, and writes a gate event with outcome `EXITED`;
    exits are accepted even while the festival is `SUSPENDED`."

    An EXIT scan on an INSIDE wristband succeeds while the festival is SUSPENDED: the
    gate event outcome is EXITED and presence_status returns to OUTSIDE.

    Design: Corner/state_machines/gate_exit_allowed_while_suspended
    """
    festival, ticket, wristband = setup_live_festival_with_active_wristband(
        start_date="2026-08-01", end_date="2026-08-02", name="ExitSusp F",
        rfid_uid="RF-EX-1", max_reentries=1)
    validate_success(gate_enter(festival["id"], wristband["id"]), 201)
    weather_hold(festival["id"])
    from test_helpers import gate_exit
    res = gate_exit(festival["id"], wristband["id"])
    event = validate_success(res, 201)
    assert event["outcome"] == "EXITED"
    after = validate_success(api.get_wristband(wristband["id"], _GATE), 200)
    assert after["presence_status"] == "OUTSIDE"


# ─── state_machines / preevent_cancel_full_refund_cascade ───

def test_preevent_cancel_refunds_ticket_addon_and_cancels_performance(api):
    """PRD §3.1: "In both cases, every ticket whose `status` is `SOLD` or `ACTIVATED`
    is refunded by the weather pro-rata refund algorithm ... the ticket's `status` is
    set to `REFUNDED` ... The cascade also transitions every performance whose `status`
    is `SCHEDULED` to `CANCELLED` and every add-on whose `status` is `SOLD` to
    `REFUNDED`. ... Both `CLOSED` and `CANCELLED` are terminal postures."

    Cancelling from ON_SALE moves the festival to CANCELLED, sets the SOLD ticket to
    REFUNDED, the SOLD add-on to REFUNDED, and the SCHEDULED performance to CANCELLED.

    Design: Corner/state_machines/preevent_cancel_full_refund_cascade
    """
    festival = create_festival(start_date="2026-08-01", end_date="2026-08-03", name="PreCancel F")
    create_zone(festival["id"], code="A", slot_capacity=1)
    stage = create_stage(festival["id"], name="Main", changeover_minutes=30)
    lot = create_parking_lot(festival["id"], capacity=10, price_per_pass=25.00)
    perf = schedule_performance(stage["id"], "Echo", "2026-08-01T18:00:00Z",
                                "2026-08-01T19:00:00Z")
    open_sales(festival["id"])
    ticket = sell_ticket(festival["id"], ticket_type="GA", day_count=3, purchaser_email="pc@x.com")
    addon = sell_parking_addon(ticket["id"], lot["id"], lot["version"])

    res = api.cancel_festival(festival["id"], _DIRECTOR)
    cancelled = validate_success(res, 200)
    assert cancelled["operational_posture"] == "CANCELLED"

    ticket_after = validate_success(api.get_ticket(ticket["id"], _BOXOFFICE), 200)
    assert ticket_after["status"] == "REFUNDED"
    addon_after = validate_success(api.get_addon(addon["id"], _BOXOFFICE), 200)
    assert addon_after["status"] == "REFUNDED"
    perf_after = validate_success(api.get_performance(perf["id"], _DIRECTOR), 200)
    assert perf_after["status"] == "CANCELLED"


# ─── calculations / cashout_fee_three_percent ───

def test_cashout_fee_three_percent_writes_two_txns(api):
    """PRD §3.6: "The cash-out computes a fee as the pre-cash-out `balance` multiplied
    by the festival's `wristband_cashout_pct`, rounded to two decimal places, and a
    refund equal to the pre-cash-out balance minus that fee, again rounded to two
    decimal places. It writes two wallet transactions — one of `kind` `CASHOUT` and one
    of `kind` `CASHOUT_FEE` — sets the `balance` to 0."

    Cashing out a 70.00 balance at 3%: fee 2.10, refund 67.90, balance 0, with a CASHOUT
    txn of 67.90 and a CASHOUT_FEE txn of 2.10 written to the wallet ledger.

    Design: Corner/calculations/cashout_fee_three_percent
    """
    festival, ticket, wristband = setup_live_festival_with_active_wristband(
        start_date="2026-08-01", end_date="2026-08-02", name="CashF",
        rfid_uid="RF-CF-1", balance=70.00, wristband_cashout_pct=0.03)
    res = api.cashout_wristband(wristband["id"], _BOXOFFICE)
    closed = validate_success(res, 200)
    assert closed["balance"] == 0

    txns = validate_success(api.list_wristband_wallet_txns(wristband["id"], _BOXOFFICE), 200)
    cashout = [t for t in txns if t["kind"] == "CASHOUT"]
    cashout_fee = [t for t in txns if t["kind"] == "CASHOUT_FEE"]
    assert len(cashout) == 1 and cashout[0]["amount"] == 67.90, (
        f"expected one CASHOUT of 67.90, got {[t['amount'] for t in cashout]}")
    assert len(cashout_fee) == 1 and cashout_fee[0]["amount"] == 2.10, (
        f"expected one CASHOUT_FEE of 2.10, got {[t['amount'] for t in cashout_fee]}")


# ─── calculations / booth_fee_zone_c_no_surcharge ───

def test_booth_fee_zone_c_no_surcharge(api):
    """PRD §3.8: "A surcharge is the base multiplied by the zone-code surcharge fraction,
    which is 0.20 for zone code `A`, 0.10 for zone code `B`, and 0.00 for zone code `C`.
    ... If `power_addon` is requested, a power fee is the daily power rate of 40.00
    multiplied by `day_count`, rounded to two decimal places."

    STANDARD/zone-C/2-day/power: base 150*2=300, surcharge 0.00, location 300, power
    40*2=80 -> booth_fee 380.00, verifying ZONE_SURCHARGE[C]=0.

    Design: Corner/calculations/booth_fee_zone_c_no_surcharge
    """
    festival = create_festival(start_date="2026-08-01", end_date="2026-08-03", name="ZoneC F")
    zone = create_zone(festival["id"], code="C", slot_capacity=1)
    zone = validate_success(api.get_zone(zone["id"], _DIRECTOR), 200)
    from test_helpers import setup_application_under_review
    vendor, app = setup_application_under_review(festival["id"], zone, booth_tier="STANDARD",
                                                 day_count=2, power_addon=True, vendor_name="ZC Co")
    res = api.approve_application(app["id"], {"expected_zone_version": zone["version"]},
                                  _VENDOR_MANAGER)
    approved = validate_success(res, 200)
    assert approved["booth_fee"] == 380.00, f"expected 380.00, got {approved['booth_fee']}"


# ─── calculations / voluntary_refund_no_fee_tier_14_days ───

def test_voluntary_refund_no_fee_at_14_days(api):
    """PRD §3.5: "If that count of days before the event is at least 14, no fee is
    withheld and the fee fraction is 0.00. ... The `fee_withheld` is the ticket's
    `face_value` multiplied by the applicable fee fraction, rounded to two decimal
    places ... A voluntary refund sets `refund_kind` to `VOLUNTARY_TIERED`."

    A voluntary refund requested exactly 14 days before start falls in the >=14 tier:
    the fee fraction is 0.00 so fee_withheld is 0.00, and refund_kind is VOLUNTARY_TIERED.

    Design: Corner/calculations/voluntary_refund_no_fee_tier_14_days
    """
    from test_helpers import set_clock
    set_clock("2026-08-01T00:00:00Z")
    festival = create_festival(start_date="2026-08-15", end_date="2026-08-17", name="Vol14 F")
    create_zone(festival["id"], code="A", slot_capacity=1)
    create_stage(festival["id"])
    open_sales(festival["id"])
    ticket = sell_ticket(festival["id"], ticket_type="GA", day_count=2, purchaser_email="v14@x.com")
    res = api.refund_ticket(ticket["id"], _BOXOFFICE)
    refund = validate_success(res, 201)
    assert refund["refund_kind"] == "VOLUNTARY_TIERED"
    assert refund["fee_withheld"] == 0.00, f"expected fee_withheld 0.00, got {refund['fee_withheld']}"


# ─── endpoints / list_tickets_pagination_envelope ───

def test_list_tickets_pagination(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; it defaults
    to 10, with a minimum of 1 and a maximum of 100. ... Every list response carries the
    pagination bookkeeping in the `meta` object of the envelope: `limit`, `offset`,
    `total_count`, and `has_more`."

    With two sold tickets, GET /festivals/{id}/tickets?limit=1&offset=0 returns an array
    of exactly one item with total_count 2 and has_more true.

    Design: Corner/endpoints/list_tickets_pagination_envelope
    """
    festival = create_festival(start_date="2026-08-01", end_date="2026-08-02", name="Page F")
    create_zone(festival["id"], code="A", slot_capacity=1)
    create_stage(festival["id"])
    open_sales(festival["id"])
    sell_ticket(festival["id"], purchaser_email="p1@x.com")
    sell_ticket(festival["id"], purchaser_email="p2@x.com")
    res = api.list_festival_tickets(festival["id"], _BOXOFFICE, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(res)
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


# ─── endpoints / gate_scan_emits_admitted_event_computed_read ───

def test_gate_scan_admitted_event_and_entry_count(api):
    """PRD §3.7: "On a successful entry the server moves `presence_status` to `INSIDE`,
    increases `entry_count` by one ... then writes a gate event with outcome `ADMITTED`."

    The first ENTER on an ACTIVE wristband at a LIVE festival emits a gate event with
    outcome ADMITTED, and the wristband reads entry_count 1 with presence_status INSIDE.

    Design: Corner/endpoints/gate_scan_emits_admitted_event_computed_read
    """
    festival, ticket, wristband = setup_live_festival_with_active_wristband(
        start_date="2026-08-01", end_date="2026-08-02", name="Adm F",
        rfid_uid="RF-AD-1", max_reentries=1)
    res = gate_enter(festival["id"], wristband["id"])
    event = validate_success(res, 201)
    assert event["outcome"] == "ADMITTED"
    after = validate_success(api.get_wristband(wristband["id"], _GATE), 200)
    assert after["entry_count"] == 1
    assert after["presence_status"] == "INSIDE"
