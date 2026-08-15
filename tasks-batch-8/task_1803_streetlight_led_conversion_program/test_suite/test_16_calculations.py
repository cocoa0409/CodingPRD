"""Corner coverage: wattage tier boundaries, overtime marginal split, ISO week
reset, savings per-pole rounding order, audit retroactive adjustment chain,
and the ticket duplicate selector."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    attest_pole_nameplate,
    close_period,
    create_account,
    create_active_program,
    create_crew,
    create_district,
    create_pole,
    create_report,
    create_ticket,
    dispatch_and_complete,
    generate_lines,
    get_account,
    get_audit,
    get_pole,
    get_work_order,
    list_lines,
    make_citizen_reporter_headers,
    make_field_supervisor_headers,
    set_clock,
    setup_cleared_pole,
    setup_effective_rate_schedule,
    setup_program_district_crew,
    setup_released_route,
    submit_and_accept_audit,
    triage_and_dispatch_ticket,
    validate_error,
    validate_success,
)
from test_helpers import resolve_ticket as fx_resolve_ticket

PM = TEST_USERS["program_manager_headers"]
MUNI_RATES = {"T1": 700, "T2": 1100, "T3": 1500, "T4": 2000, "T5": 2600}


def test_wattage_tier_boundary_99_vs_100(api):
    """PRD section 2.6: "From billing_wattage the system derives wattage_tier:
    T1 below 100 watts, T2 from 100 up to 199 ... Lower bounds are inclusive —
    exactly 100 watts is T2".

    Design: Corner/calculations/calc_wattage_tier_boundary_99_vs_100
    """
    program, district, crew = setup_program_district_crew(zone="RESIDENTIAL")
    p99 = create_pole(district["id"], pole_number="TB-99", ownership_type="MUNICIPAL",
                      fixture_class="COBRA_HEAD", nameplate_wattage=99)
    submit_and_accept_audit(p99["id"], 99, crew["id"])
    p100 = create_pole(district["id"], pole_number="TB-100", ownership_type="MUNICIPAL",
                       fixture_class="COBRA_HEAD", nameplate_wattage=100)
    submit_and_accept_audit(p100["id"], 100, crew["id"])
    rs = setup_effective_rate_schedule(program["id"], "MUNICIPAL", tier_rates=MUNI_RATES)
    acct = create_account(district["id"], "MUNICIPAL", account_number="AC-M")
    generate_lines(acct["id"])

    lines = list_lines(account_id=acct["id"], period="2026-08")
    by_pole = {l["pole_id"]: l for l in lines}
    assert get_pole(p99["id"])["wattage_tier"] == "T1"
    assert by_pole[p99["id"]]["charge_cents"] == 700
    assert get_pole(p100["id"])["wattage_tier"] == "T2"
    assert by_pole[p100["id"]]["charge_cents"] == 1100
    for line in lines:
        assert line["status"] == "ESTIMATED"
        assert line["period"] == "2026-08"
        assert line["rate_schedule_id"] == rs["id"]


def test_overtime_marginal_split_and_full_ot(api):
    """PRD section 3.4: "Against the weekly overtime threshold of 2400 minutes:
    if the prior total is already at or beyond 2400, the entire order bills as
    overtime; if the prior total plus this order's minutes crosses 2400, only
    the minutes beyond the threshold are overtime and the rest bill
    straight-time; otherwise the whole order bills straight-time. Boundary
    semantics are exact — a prior total of exactly 2400 makes the whole stop
    overtime, while a running total landing exactly on 2400 bills no overtime
    on that stop. The order's overtime_minutes records the excess, and
    labor_cost_cents is the straight-time minutes at hourly_rate_cents per hour
    — rate times minutes divided by 60, rounded half-up — plus the overtime
    minutes at one and a half times the rate, also divided by 60 and rounded
    half-up, the two rounded parts then summed."

    Design: Corner/calculations/calc_overtime_marginal_split_and_full_ot
    """
    program, district, crew = setup_program_district_crew(zone="ARTERIAL")
    poles = [setup_cleared_pole(program, district, crew, pole_number=f"OT-{i:02d}",
                                ownership_type="UTILITY_OWNED", nameplate_wattage=250)
             for i in range(1, 23)]
    difficulties = ["COMPLEX"] * 19 + ["HEAVY"] + ["COMPLEX", "COMPLEX"]
    route, stops, wos = setup_released_route(
        program, district, crew, poles, start="2026-08-03", end="2026-08-08",
        difficulties=difficulties)
    # Work orders follow stop sequence order; stop seq determines processing
    # order at the frozen clock (tie-broken by sequence_number).
    assert len(wos) == 22, "Setup failed: expected 22 work orders"
    set_clock("2026-08-05T12:00:00Z")
    for wo in wos:
        dispatch_and_complete(wo["id"], crew["id"], wattage=90, cct=3000,
                              shielding="SEMI_CUTOFF")

    w19 = get_work_order(wos[18]["id"])  # seq 19 COMPLEX, prev 2160
    assert w19["labor_cost_cents"] == 12000 and w19["overtime_minutes"] == 0

    w20 = get_work_order(wos[19]["id"])  # seq 20 HEAVY, prev 2280: 2280+75=2355 <= 2400
    assert w20["cumulative_week_minutes_before"] == 2280
    assert w20["overtime_minutes"] == 0
    assert w20["labor_cost_cents"] == 7500  # rhu(6000*75/60)

    w21 = get_work_order(wos[20]["id"])  # seq 21 COMPLEX, prev 2355 -> splits 45 + 75
    assert w21["cumulative_week_minutes_before"] == 2355
    assert w21["overtime_minutes"] == 75
    assert w21["labor_cost_cents"] == 15750  # rhu(100c*45)=4500 + rhu(150c*75)=11250

    w22 = get_work_order(wos[21]["id"])  # seq 22 COMPLEX, prev 2475 >= 2400 -> all OT
    assert w22["cumulative_week_minutes_before"] == 2475
    assert w22["overtime_minutes"] == 120
    assert w22["labor_cost_cents"] == 18000  # rhu(150c*120)


def test_overtime_iso_week_reset(api):
    """PRD section 3.4: "The weekly accumulator scopes to the crew's completed
    work orders — execution COMPLETED regardless of QC state — whose
    completed_at falls in the same ISO-8601 week as this completion, the week
    running Monday 00:00 UTC through Sunday 24:00 UTC."

    Design: Corner/calculations/calc_overtime_iso_week_reset
    """
    program, district, crew = setup_program_district_crew(zone="ARTERIAL")
    q1 = setup_cleared_pole(program, district, crew, pole_number="WK-1",
                            ownership_type="UTILITY_OWNED", nameplate_wattage=250)
    q2 = setup_cleared_pole(program, district, crew, pole_number="WK-2",
                            ownership_type="UTILITY_OWNED", nameplate_wattage=250)
    # ISO week 2026-W32: Monday 2026-08-03
    route1, _s1, wos1 = setup_released_route(
        program, district, crew, [q1], start="2026-08-03", end="2026-08-03",
        difficulties=["COMPLEX"])
    set_clock("2026-08-03T10:00:00Z")
    dispatch_and_complete(wos1[0]["id"], crew["id"], wattage=90, cct=3000,
                          shielding="SEMI_CUTOFF")
    wo1 = get_work_order(wos1[0]["id"])
    assert wo1["labor_cost_cents"] == 12000

    # ISO week 2026-W33: Monday 2026-08-10 — disjoint closed windows, same crew
    route2, _s2, wos2 = setup_released_route(
        program, district, crew, [q2], start="2026-08-10", end="2026-08-10",
        difficulties=["COMPLEX"])
    set_clock("2026-08-10T09:00:00Z")
    dispatch_and_complete(wos2[0]["id"], crew["id"], wattage=90, cct=3000,
                          shielding="SEMI_CUTOFF")
    wo2 = get_work_order(wos2[0]["id"])
    # the week boundary resets the accumulator
    assert wo2["cumulative_week_minutes_before"] == 0
    assert wo2["overtime_minutes"] == 0
    assert wo2["labor_cost_cents"] == 12000


def test_savings_per_pole_rounding_order(api):
    """PRD section 3.8: "every per-pole quantity is rounded half-up to three
    decimals before any summation" and "The report's baseline_kwh and
    actual_kwh are the sums of the per-pole quantities, savings_kwh is their
    difference rounded half-up to three decimals".

    Design: Corner/calculations/calc_savings_per_pole_rounding_order
    """
    set_clock("2026-02-01T00:00:00Z")
    program = create_active_program()
    district = create_district(program["id"], zone="ARTERIAL")
    crew = create_crew(program["id"])
    q1 = setup_cleared_pole(program, district, crew, pole_number="FB-1",
                            ownership_type="UTILITY_OWNED", nameplate_wattage=190)
    q2 = setup_cleared_pole(program, district, crew, pole_number="FB-2",
                            ownership_type="UTILITY_OWNED", nameplate_wattage=190)
    route, stops, wos = setup_released_route(
        program, district, crew, [q1, q2], start="2026-02-19", end="2026-02-19")
    set_clock("2026-02-19T09:00:00Z")
    for wo in wos:
        dispatch_and_complete(wo["id"], crew["id"], wattage=90, cct=3000,
                              shielding="SEMI_CUTOFF")

    rep = create_report(program["id"], period="2026-02", method="METERED_ACTUAL",
                        fiscal_year_label="FY2026")
    # Feb: B=380, D=28, d_old=18, d_new=10; per pole actual =
    # (190*380*18/28 + 90*380*10/28)/1000 = 58.6285714 -> 58.629 (per-pole rounding first)
    assert rep["baseline_kwh"] == pytest.approx(144.400, abs=0.0005)  # 2 x 72.200
    assert rep["actual_kwh"] == pytest.approx(117.258, abs=0.0005)   # 2 x 58.629
    assert rep["actual_kwh"] != pytest.approx(117.257, abs=0.00005)  # sum-then-round forbidden
    assert rep["savings_kwh"] == pytest.approx(27.142, abs=0.0005)


def test_audit_retroactive_adjustment_chain(api):
    """PRD section 3.2: "Each BILLED REGULAR line is recomputed with the new
    wattage basis while dates, the proration split, and the ownership variant
    stay unchanged; when the recomputed charge differs from the stored one, the
    old line becomes SUPERSEDED and a new ADJUSTMENT line is created — born
    BILLED, its supersedes_line_id pointing at the old line, billing the same
    period, carrying charge_cents equal to the signed delta"; "any previously
    ACCEPTED audit for the same pole is automatically SUPERSEDED".

    Design: Corner/calculations/calc_audit_retroactive_adjustment_chain
    """
    program, district, crew = setup_program_district_crew(zone="RESIDENTIAL")
    pole = create_pole(district["id"], pole_number="RT-1", ownership_type="MUNICIPAL",
                       fixture_class="COBRA_HEAD", nameplate_wattage=250)
    aud1 = submit_and_accept_audit(pole["id"], 250, crew["id"])
    setup_effective_rate_schedule(program["id"], "MUNICIPAL", tier_rates=MUNI_RATES)
    acct = create_account(district["id"], "MUNICIPAL", account_number="AC-M")
    generate_lines(acct["id"])
    line = list_lines(account_id=acct["id"], period="2026-08")[0]
    assert line["charge_cents"] == 1500
    close_period(acct["id"])  # line BILLED; account now in 2026-09

    # second audit moves effective_wattage 250 -> 190 (T3 -> T2)
    pole_now = get_pole(pole["id"])
    resp = api.submit_audit(
        pole["id"],
        {"audited_wattage": 190, "expected_pole_version": pole_now["version"]},
        make_field_supervisor_headers(crew["id"]),
    )
    aud2 = validate_success(resp, expected_status=201)
    resp = api.accept_audit(aud2["id"], PM)
    validate_success(resp)

    lines = list_lines(account_id=acct["id"], period="2026-08")
    assert len(lines) == 2, f"expected original + adjustment lines, got {len(lines)}"
    by_type = {l["line_type"]: l for l in lines}
    orig = by_type["REGULAR"]
    adj = by_type["ADJUSTMENT"]
    assert orig["id"] == line["id"] and orig["status"] == "SUPERSEDED"
    assert adj["status"] == "BILLED"
    assert adj["charge_cents"] == -400  # 1100 - 1500 signed delta
    assert adj["period"] == "2026-08"
    assert adj["supersedes_line_id"] == orig["id"]

    assert get_audit(aud1["id"])["status"] == "SUPERSEDED"
    assert get_audit(aud2["id"])["status"] == "ACCEPTED"
    pole_after = get_pole(pole["id"])
    assert pole_after["effective_wattage"] == 190
    assert pole_after["wattage_tier"] == "T2"

    account = get_account(acct["id"])
    # REGULAR(BILLED+SUPERSEDED) 1500 + ADJUSTMENT -400
    assert account["ytd_billed_cents"] == 1100
    assert account["current_period_estimated_cents"] == 0  # no September lines exist


def test_ticket_duplicate_selector(api):
    """PRD section 3.6: "Duplicate detection runs at creation: if the pole
    already has a ticket in OPEN, TRIAGED, DISPATCHED, RESOLVED, or REOPENED
    (VERIFIED and DUPLICATE tickets do not count), the new ticket is created
    directly as DUPLICATE — terminal, carrying no priority or sla_hours, and it
    cannot be triaged — with duplicate_of_ticket_id pointing at the
    earliest-created candidate; with no candidates the ticket is created OPEN
    with duplicate_of_ticket_id null."

    Design: Corner/calculations/calc_ticket_duplicate_selector
    """
    program, district, crew = setup_program_district_crew(zone="RESIDENTIAL")
    pole = setup_cleared_pole(program, district, crew, pole_number="DP-1",
                              ownership_type="UTILITY_OWNED", nameplate_wattage=90)
    t1 = create_ticket(pole["id"], reporter_user_id="citizen-1", description="first",
                       hazard_flag=False)
    assert t1["status"] == "OPEN" and t1["duplicate_of_ticket_id"] is None

    # while t1 is OPEN, t2 auto-links to it
    t2 = create_ticket(pole["id"], reporter_user_id="citizen-2", description="second",
                       hazard_flag=False)
    assert t2["status"] == "DUPLICATE"
    assert t2["duplicate_of_ticket_id"] == t1["id"]
    assert t2["priority"] is None and t2["sla_hours"] is None

    # DUPLICATE tickets are terminal: triage on t2 fails
    resp = api.triage_ticket(t2["id"], PM)
    validate_error(resp, ApiErrorId.ERR_TICKET_NOT_OPEN, expected_status=409)

    # while t1 is RESOLVED (still a candidate) t3 links to t1 — never to t2
    triage_and_dispatch_ticket(t1["id"], crew["id"])
    fx_resolve_ticket(t1["id"], crew["id"], resolution_code="LIGHT_OUT_FIXED")
    t3 = create_ticket(pole["id"], reporter_user_id="citizen-3", description="third",
                       hazard_flag=False)
    assert t3["status"] == "DUPLICATE"
    assert t3["duplicate_of_ticket_id"] == t1["id"]

    # once t1 is VERIFIED the candidate set is empty
    resp = api.verify_ticket(t1["id"], make_citizen_reporter_headers("citizen-1"))
    validate_success(resp)
    t4 = create_ticket(pole["id"], reporter_user_id="citizen-4", description="fourth",
                       hazard_flag=False)
    assert t4["status"] == "OPEN"
    assert t4["duplicate_of_ticket_id"] is None


def test_sla_priority_critical_paths(api):
    """PRD section 3.6: "A hazard-flagged ticket is `CRITICAL`; otherwise a pole
    in an `ARTERIAL` district tiered `T4` or `T5` is `CRITICAL`; otherwise an
    `ARTERIAL` pole or any pole tiered `T3`, `T4`, or `T5` is `HIGH`;
    everything else is `STANDARD`. The SLA is 24 hours for `CRITICAL`, 48 for
    `HIGH`, 96 for `STANDARD`."

    Design: Corner/calculations/calc_sla_priority_critical_paths
    """
    program = create_active_program()
    dist_r = create_district(program["id"], zone="RESIDENTIAL", district_name="D1")
    dist_a = create_district(program["id"], zone="ARTERIAL", district_name="DA")
    crew = create_crew(program["id"])
    p1 = create_pole(dist_r["id"], pole_number="HZ-1", ownership_type="UTILITY_OWNED",
                     fixture_class="COBRA_HEAD", nameplate_wattage=90)
    attest_pole_nameplate(p1["id"])
    p2 = create_pole(dist_a["id"], pole_number="HZ-2", ownership_type="UTILITY_OWNED",
                     fixture_class="COBRA_HEAD", nameplate_wattage=300)
    attest_pole_nameplate(p2["id"])

    # hazard flag promotes a low-tier RESIDENTIAL report to CRITICAL
    t1 = create_ticket(p1["id"], reporter_user_id="citizen-1", description="sparking",
                       hazard_flag=True)
    resp = api.triage_ticket(t1["id"], PM)
    t1 = validate_success(resp)
    assert t1["priority"] == "CRITICAL" and t1["sla_hours"] == 24

    # ARTERIAL x T4 is CRITICAL without the hazard flag
    t2 = create_ticket(p2["id"], reporter_user_id="citizen-2",
                       description="out on arterial", hazard_flag=False)
    resp = api.triage_ticket(t2["id"], PM)
    t2 = validate_success(resp)
    assert t2["priority"] == "CRITICAL" and t2["sla_hours"] == 24

    # a non-hazard report on the same pole links to the open CRITICAL ticket
    t3 = create_ticket(p1["id"], reporter_user_id="citizen-3", description="out again",
                       hazard_flag=False)
    assert t3["status"] == "DUPLICATE"
    assert t3["duplicate_of_ticket_id"] == t1["id"]
