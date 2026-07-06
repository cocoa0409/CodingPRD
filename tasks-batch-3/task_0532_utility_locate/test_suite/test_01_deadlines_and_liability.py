"""Deadline and money calculations: sla_due_at, assignment_sla, liability apportionment.

Covers Difficulty/dual_variant_calc, Difficulty/combinatorial_formula and the calculations
corner instances.
"""
from test_helpers import (
    validate_success,
    register_excavator, register_member, register_tech, create_ticket, submit_ticket,
    first_notification, post_response, dispatch, go_en_route, create_markout, complete_markout,
    setup_cleared_ticket, setup_marked_ticket, file_damage_report, review_damage_report,
    assert_liability_sums_to_cost,
    make_excavator_headers, make_facility_owner_headers,
    COVERING_POLYGON,
)


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty/dual_variant_calc/sla_due_emergency_vs_normal_ticket_time
# ─────────────────────────────────────────────────────────────────────────────

def test_sla_due_emergency_vs_normal_diverge_from_same_submit(api):
    """PRD §3.3: "For an EMERGENCY ticket the window is a flat wall-clock span: the deadline is
    the submit instant plus two hours, and weekend days are counted normally within that span."
    PRD §3.3: "starting from the submit instant, the cursor advances one calendar day at a time,
    keeping the same time-of-day as the submit instant, and each day that lands on Monday through
    Friday decrements a counter that begins at two business days, while each day that lands on
    Saturday or Sunday advances the cursor without decrementing the counter."

    Design: Difficulty/dual_variant_calc/sla_due_emergency_vs_normal_ticket_time
    """
    exc = register_excavator()
    mem = register_member(facility_type="GAS", service_polygon=COVERING_POLYGON)
    exc_h = make_excavator_headers(exc["id"])

    emerg = create_ticket(exc["id"], ticket_type="EMERGENCY")
    normal = create_ticket(exc["id"], ticket_type="NORMAL", is_white_lined=True)

    emerg_after = validate_success(api.submit_ticket(emerg["id"], exc_h), 200)
    normal_after = validate_success(api.submit_ticket(normal["id"], exc_h), 200)

    assert emerg_after["sla_due_at"] == "2026-05-01T02:00:00Z"
    assert normal_after["sla_due_at"] == "2026-05-05T00:00:00Z"
    assert emerg_after["sla_due_at"] != normal_after["sla_due_at"]


def test_sla_due_opens_at_equals_due_at(api):
    """PRD §3.3: "In both variants `dig_window_opens_at` is then set equal to `sla_due_at`,
    establishing the earliest legal moment the excavator may begin digging."

    Design: Difficulty/dual_variant_calc/sla_due_emergency_vs_normal_ticket_time
    """
    exc = register_excavator()
    register_member(facility_type="GAS", service_polygon=COVERING_POLYGON)
    exc_h = make_excavator_headers(exc["id"])
    emerg = create_ticket(exc["id"], ticket_type="EMERGENCY")
    after = validate_success(api.submit_ticket(emerg["id"], exc_h), 200)
    assert after["sla_due_at"] == "2026-05-01T02:00:00Z"
    assert after["dig_window_opens_at"] == after["sla_due_at"]


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty/dual_variant_calc/damage_liability_marked_vs_no_marks
# ─────────────────────────────────────────────────────────────────────────────

def test_damage_liability_marked_within_vs_no_marks(api):
    """PRD §3.8: "when `dug_within_marks` is true, the excavator exercised care and bears only 25
    percent, so `excavator_liability_cents` is `repair_cost_cents` multiplied by 0.25"
    PRD §3.8: "If no `markout_id` was recorded — meaning no valid mark-out was in force and the
    excavator dug blind — the excavator bears the entire cost: `excavator_liability_cents` equals
    `repair_cost_cents`."

    Design: Difficulty/dual_variant_calc/damage_liability_marked_vs_no_marks
    """
    base = setup_marked_ticket()
    mem_id = base["member"]["id"]
    tid = base["ticket"]["id"]
    mk_id = base["markout"]["id"]

    dr_marked = file_damage_report(tid, mem_id, 10000, dug_within_marks=True, markout_id=mk_id)
    dr_nomarks = file_damage_report(tid, mem_id, 10000, dug_within_marks=False)

    mem_h = make_facility_owner_headers(mem_id)
    marked = validate_success(api.review_damage_report(dr_marked["id"], mem_h), 200)
    nomarks = validate_success(api.review_damage_report(dr_nomarks["id"], mem_h), 200)

    assert marked["excavator_liability_cents"] == 2500
    assert marked["member_liability_cents"] == 7500
    assert nomarks["excavator_liability_cents"] == 10000
    assert nomarks["member_liability_cents"] == 0


def test_damage_liability_shares_sum_to_cost(api):
    """PRD §3.8: "In every case, `member_liability_cents` is then taken as `repair_cost_cents`
    minus `excavator_liability_cents`, so the two shares always sum exactly to the reported cost."

    Design: Difficulty/dual_variant_calc/damage_liability_marked_vs_no_marks
    """
    base = setup_marked_ticket()
    mem_id = base["member"]["id"]
    dr = file_damage_report(base["ticket"]["id"], mem_id, 10000, dug_within_marks=True,
                            markout_id=base["markout"]["id"])
    reviewed = validate_success(
        api.review_damage_report(dr["id"], make_facility_owner_headers(mem_id)), 200
    )
    assert_liability_sums_to_cost(reviewed)


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty/combinatorial_formula/assignment_sla_three_input_nonlinear
# ─────────────────────────────────────────────────────────────────────────────

def test_assignment_sla_emergency_high_priority_lowload(api):
    """PRD §3.6: "The base number of minutes is the member's `emergency_contact_minutes` when the
    ticket is `EMERGENCY`, and 240 minutes when the ticket is `NORMAL`. If the notification is high
    priority, that minute figure is multiplied by one-half and rounded up to the next whole minute;
    this high-priority tightening is applied first."

    Design: Difficulty/combinatorial_formula/assignment_sla_three_input_nonlinear
    """
    base = setup_cleared_ticket(ticket_type="EMERGENCY", member_facility="GAS",
                                emergency_contact_minutes=60)
    asg = validate_success(
        api.create_locate_assignment(
            {"ticket_id": base["ticket"]["id"], "notification_id": base["notification"]["id"],
             "locate_tech_id": base["tech"]["id"]},
            make_facility_owner_headers(base["member"]["id"]),
        ), 201,
    )
    # base 60 -> high-priority ceil(60*0.5)=30 -> load < 3 so no slack -> +30min.
    assert asg["sla_deadline_at"] == "2026-05-01T00:30:00Z"


def test_assignment_dispatch_starts_dispatched_and_increments_load(api):
    """PRD §3.6: "On success the assignment stamps `dispatched_at` with the current clock, begins in
    `DISPATCHED`, and the technician's `active_assignment_count` is incremented by one."

    Design: Difficulty/combinatorial_formula/assignment_sla_three_input_nonlinear
    """
    base = setup_cleared_ticket(ticket_type="EMERGENCY", member_facility="GAS",
                                emergency_contact_minutes=60)
    asg = validate_success(
        api.create_locate_assignment(
            {"ticket_id": base["ticket"]["id"], "notification_id": base["notification"]["id"],
             "locate_tech_id": base["tech"]["id"]},
            make_facility_owner_headers(base["member"]["id"]),
        ), 201,
    )
    assert asg["status"] == "DISPATCHED"
    assert asg["dispatched_at"] == "2026-05-01T00:00:00Z"
    tech = validate_success(
        api.get_locate_tech(base["tech"]["id"], make_facility_owner_headers(base["member"]["id"])), 200
    )
    assert tech["active_assignment_count"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty/combinatorial_formula/sla_due_normal_business_day_skip_order
# ─────────────────────────────────────────────────────────────────────────────

def test_sla_due_normal_skips_weekend(api):
    """PRD §3.3: "starting from the submit instant, the cursor advances one calendar day at a time,
    keeping the same time-of-day as the submit instant, and each day that lands on Monday through
    Friday decrements a counter that begins at two business days, while each day that lands on
    Saturday or Sunday advances the cursor without decrementing the counter."

    Design: Difficulty/combinatorial_formula/sla_due_normal_business_day_skip_order
    """
    exc = register_excavator()
    register_member(facility_type="WATER", service_polygon=COVERING_POLYGON)
    ticket = create_ticket(exc["id"], ticket_type="NORMAL", is_white_lined=True)
    after = validate_success(
        api.submit_ticket(ticket["id"], make_excavator_headers(exc["id"])), 200
    )
    # Fri 05-01 -> Sat 05-02 (no dec) -> Sun 05-03 (no dec) -> Mon 05-04 (dec 1) -> Tue 05-05 (dec 0).
    assert after["sla_due_at"] == "2026-05-05T00:00:00Z"


def test_sla_due_normal_preserves_time_of_day_via_opens_at(api):
    """PRD §3.3: "In both variants `dig_window_opens_at` is then set equal to `sla_due_at`,
    establishing the earliest legal moment the excavator may begin digging."

    Design: Difficulty/combinatorial_formula/sla_due_normal_business_day_skip_order
    """
    exc = register_excavator()
    register_member(facility_type="WATER", service_polygon=COVERING_POLYGON)
    ticket = create_ticket(exc["id"], ticket_type="NORMAL", is_white_lined=True)
    after = validate_success(
        api.submit_ticket(ticket["id"], make_excavator_headers(exc["id"])), 200
    )
    assert after["sla_due_at"] == "2026-05-05T00:00:00Z"
    assert after["dig_window_opens_at"] == "2026-05-05T00:00:00Z"


# ─────────────────────────────────────────────────────────────────────────────
# Corner/calculations/assignment_sla_normal_lowload_baseline
# ─────────────────────────────────────────────────────────────────────────────

def test_assignment_sla_normal_lowload_baseline(api):
    """PRD §3.6: "The base number of minutes is the member's `emergency_contact_minutes` when the
    ticket is `EMERGENCY`, and 240 minutes when the ticket is `NORMAL`."

    Design: Corner/calculations/assignment_sla_normal_lowload_baseline
    """
    base = setup_cleared_ticket(ticket_type="NORMAL", member_facility="WATER",
                                tech_certified=("WATER",))
    asg = validate_success(
        api.create_locate_assignment(
            {"ticket_id": base["ticket"]["id"], "notification_id": base["notification"]["id"],
             "locate_tech_id": base["tech"]["id"]},
            make_facility_owner_headers(base["member"]["id"]),
        ), 201,
    )
    # NORMAL 240 min, WATER not high-priority, load 0 -> +240min = 04:00.
    assert asg["sla_deadline_at"] == "2026-05-01T04:00:00Z"


# ─────────────────────────────────────────────────────────────────────────────
# Corner/calculations/liability_outside_marks_apportionment
# ─────────────────────────────────────────────────────────────────────────────

def test_liability_outside_marks_apportionment(api):
    """PRD §3.8: "when `dug_within_marks` is false, the excavator dug outside the marks and bears
    the majority, so `excavator_liability_cents` is `repair_cost_cents` multiplied by 0.75."

    Design: Corner/calculations/liability_outside_marks_apportionment
    """
    base = setup_marked_ticket()
    mem_id = base["member"]["id"]
    dr = file_damage_report(base["ticket"]["id"], mem_id, 10000, dug_within_marks=False,
                            markout_id=base["markout"]["id"])
    reviewed = validate_success(
        api.review_damage_report(dr["id"], make_facility_owner_headers(mem_id)), 200
    )
    assert reviewed["excavator_liability_cents"] == 7500
    assert reviewed["member_liability_cents"] == 2500
