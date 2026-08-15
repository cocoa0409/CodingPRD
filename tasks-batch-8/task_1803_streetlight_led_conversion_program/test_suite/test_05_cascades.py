"""Transitive cascade instances: the work-order completion cascade (pole ->
billing line -> account -> program) and the FIXTURE_REPLACED resolution cascade
(ticket -> pole -> stop -> route auto-suspension)."""
from test_helpers import (
    TEST_USERS,
    add_stop,
    create_account,
    create_active_program,
    create_crew,
    create_district,
    create_pole,
    create_route,
    create_ticket,
    dispatch_and_complete,
    dispatch_work_order,
    generate_lines,
    get_account,
    get_pole,
    get_program,
    get_route,
    get_stop,
    get_work_order,
    list_lines,
    list_work_orders_for_route,
    make_field_supervisor_headers,
    release_route,
    set_clock,
    setup_cleared_pole,
    setup_effective_rate_schedule,
    setup_program_district_crew,
    submit_and_accept_audit,
    triage_and_dispatch_ticket,
    validate_success,
)
from test_helpers import resolve_ticket as fx_resolve_ticket

PM = TEST_USERS["program_manager_headers"]

MUNI_RATES = {"T1": 700, "T2": 1100, "T3": 1500, "T4": 2000, "T5": 2600}


class TestCompletionCascadePoleLineAccountProgram:
    def _setup(self):
        """MUNICIPAL pole 250W audit-accepted; schedule EFFECTIVE; account with
        one ESTIMATED August line (1500) generated BEFORE conversion; route
        2026-08-16 with the pole, RELEASED; clock at 2026-08-16T09:00:00Z;
        work order dispatched (90W/2700K/FULL_CUTOFF, estimate 4500 debited)."""
        program = create_active_program()
        district = create_district(program["id"], zone="RESIDENTIAL")
        crew = create_crew(program["id"])
        pole = create_pole(district["id"], pole_number="C-01", ownership_type="MUNICIPAL",
                           fixture_class="COBRA_HEAD", nameplate_wattage=250)
        submit_and_accept_audit(pole["id"], 250, crew["id"])
        setup_effective_rate_schedule(program["id"], "MUNICIPAL", tier_rates=MUNI_RATES)
        acct = create_account(district["id"], "MUNICIPAL", account_number="AC-M")
        route = create_route(district["id"], crew["id"], start="2026-08-16", end="2026-08-16")
        add_stop(route["id"], pole["id"], 1, difficulty_class="STANDARD")
        release_route(route["id"])
        gen = generate_lines(acct["id"])
        assert gen["created_count"] == 1, "Setup failed: expected one generated line"
        line = list_lines(account_id=acct["id"], pole_id=pole["id"], period="2026-08")[0]
        assert line["charge_cents"] == 1500 and line["status"] == "ESTIMATED", (
            f"Setup failed: pre-conversion line should be 1500 ESTIMATED, got {line}"
        )
        wo = list_work_orders_for_route(route["id"])[0]
        set_clock("2026-08-16T09:00:00Z")
        dispatch_work_order(wo["id"], crew["id"], wattage=90, cct=2700, shielding="FULL_CUTOFF")
        return program, district, crew, pole, acct, line, wo

    def test_completion_rerates_estimated_line_and_rollups(self, api):
        """PRD section 3.4: "Any ESTIMATED billing lines for the pole in open
        periods re-rate under §3.5"; PRD section 3.5: "re-rating rewrites an
        ESTIMATED line in place (charge_cents, billing_wattage, tier,
        rate_schedule_id recomputed)"; "the account's
        current_period_estimated_cents — the sum of charge_cents over its
        ESTIMATED REGULAR lines in current_period — and the program's
        current_billing_run_estimated_cents, the same quantity summed across all
        of the program's accounts, are recomputed."

        Design: Difficulty/transitive_cascade/completion_cascade_pole_line_account_program
        """
        program, _d, crew, pole, acct, line, wo = self._setup()
        resp = api.complete_work_order(wo["id"], make_field_supervisor_headers(crew["id"]))
        validate_success(resp)

        # hop2: the pre-existing ESTIMATED August line re-rated in place 1500 -> 1087
        after_line = [l for l in list_lines(account_id=acct["id"], period="2026-08")
                      if l["id"] == line["id"]][0]
        assert after_line["charge_cents"] == 1087  # rhu(1500*15/31)+rhu(700*16/31) = 726+361
        assert after_line["status"] == "ESTIMATED"
        assert after_line["tier"] == "T1" and after_line["billing_wattage"] == 90

        # hop3 / hop4: account and program estimated totals recomputed 1500 -> 1087
        account = get_account(acct["id"])
        assert account["current_period_estimated_cents"] == 1087
        program_after = get_program(program["id"])
        assert program_after["current_billing_run_estimated_cents"] == 1087

    def test_completion_moves_pole_and_posts_labor_and_salvage(self, api):
        """PRD section 3.4: "A conversion completion moves the pole into
        CONVERTED — from SCHEDULED on first conversion ... snapshots
        pre_conversion_wattage from effective_wattage at the first completion
        only, and records led_wattage from the order's new_fixture_wattage and
        led_in_service_date as the completion date"; "exactly one salvage item is
        auto-created for the removed fixture: unbatched with batch_id null".

        Design: Difficulty/transitive_cascade/completion_cascade_pole_line_account_program
        """
        program, _d, crew, pole, acct, _line, wo = self._setup()
        resp = api.complete_work_order(wo["id"], make_field_supervisor_headers(crew["id"]))
        completed = validate_success(resp)

        # hop1: pole CONVERTED with in-service snapshot
        pole_after = get_pole(pole["id"])
        assert pole_after["status"] == "CONVERTED"
        assert pole_after["led_in_service_date"] == "2026-08-16"
        assert pole_after["pre_conversion_wattage"] == 250
        assert pole_after["led_wattage"] == 90

        # labor: first completion of the week — prev 0, all straight time
        assert completed["labor_cost_cents"] == 4500
        assert completed["cumulative_week_minutes_before"] == 0
        assert completed["overtime_minutes"] == 0

        # one SalvageItem auto-created (weight 0, batch_id null)
        program_after = get_program(program["id"])
        assert program_after["pending_salvage_item_count"] == 1


class TestOutageFixtureReplacementCascadeSuspendsRoute:
    def _setup(self):
        """ARTERIAL district; crews C1 (route crew) and C2 (repair crew);
        MUNICIPAL poles A and B audit-accepted; route 2026-08-10..12 with
        stop1=A, stop2=B, RELEASED; wo_b dispatched (route IN_PROGRESS);
        ticket on pole A triaged + dispatched to C2."""
        program = create_active_program()
        district = create_district(program["id"], zone="ARTERIAL")
        crew1 = create_crew(program["id"], crew_name="Crew-1")
        crew2 = create_crew(program["id"], crew_name="Crew-2")
        pole_a = create_pole(district["id"], pole_number="C-A", ownership_type="MUNICIPAL",
                             fixture_class="COBRA_HEAD", nameplate_wattage=250)
        submit_and_accept_audit(pole_a["id"], 250, crew1["id"])
        pole_b = create_pole(district["id"], pole_number="C-B", ownership_type="MUNICIPAL",
                             fixture_class="COBRA_HEAD", nameplate_wattage=250)
        submit_and_accept_audit(pole_b["id"], 250, crew1["id"])
        route = create_route(district["id"], crew1["id"], start="2026-08-10", end="2026-08-12")
        stop_a = add_stop(route["id"], pole_a["id"], 1, difficulty_class="STANDARD")
        add_stop(route["id"], pole_b["id"], 2, difficulty_class="STANDARD")
        release_route(route["id"])
        wos = list_work_orders_for_route(route["id"])
        wo_by_pole = {wo["pole_id"]: wo for wo in wos}
        dispatch_work_order(wo_by_pole[pole_b["id"]]["id"], crew1["id"],
                            wattage=90, cct=3500, shielding="SEMI_CUTOFF")
        ticket = create_ticket(pole_a["id"], reporter_user_id="citizen-9",
                               description="head dangling", hazard_flag=False)
        triage_and_dispatch_ticket(ticket["id"], crew2["id"])
        return (program, district, crew1, crew2, pole_a, pole_b, route, stop_a,
                wo_by_pole, ticket)

    def test_resolution_spawns_replacement_and_moves_pole_under_repair(self, api):
        """PRD section 3.6: "A resolution of FIXTURE_REPLACED fires the
        replacement cascade. The pole moves to UNDER_REPAIR with pre_repair_status
        recording where it came from ... A replacement work order is created with
        execution PENDING, its route_id and stop_id null, its crew_id set to the
        resolving crew, its ticket_id bound to this ticket, is_replacement true,
        and a flat 75-minute stop_minutes basis. A PENDING stop referencing the
        pole moves to BLOCKED".

        Design: Difficulty/transitive_cascade/outage_fixture_replacement_cascade_suspends_route
        """
        (_p, _d, _c1, crew2, pole_a, _pb, _route, stop_a, _wos, ticket) = self._setup()
        resolved = fx_resolve_ticket(ticket["id"], crew2["id"],
                                     resolution_code="FIXTURE_REPLACED")
        assert resolved["status"] == "RESOLVED"
        assert resolved["sla_breached"] is False  # resolved within minutes of report

        pole_after = get_pole(pole_a["id"])
        assert pole_after["status"] == "UNDER_REPAIR"
        assert pole_after["pre_repair_status"] == "SCHEDULED"

        resp = api.list_work_orders(PM, params={"ticket_id": ticket["id"]})
        repl = resp.json()["data"][0]
        assert repl["is_replacement"] is True
        assert repl["crew_id"] == crew2["id"]
        assert repl["execution_status"] == "PENDING"
        assert repl["route_id"] is None and repl["stop_id"] is None
        assert repl["stop_minutes"] == 75

        assert get_stop(stop_a["id"])["status"] == "BLOCKED"

    def test_half_blocked_route_auto_suspends_and_untouched_sibling_survives(self, api):
        """PRD section 3.3: "the system suspends automatically whenever a route's
        blocked_stop_count changes while the route is IN_PROGRESS with at least
        one counted stop: if twice the blocked count is greater than or equal to
        stop_count, the route suspends itself."

        Design: Difficulty/transitive_cascade/outage_fixture_replacement_cascade_suspends_route
        """
        (_p, _d, crew1, crew2, pole_a, pole_b, route, _stop_a, wos, ticket) = self._setup()
        fx_resolve_ticket(ticket["id"], crew2["id"], resolution_code="FIXTURE_REPLACED")

        route_after = get_route(route["id"])
        # 1 blocked of 2 stops: 1*2 >= 2 -> auto-suspension (boundary equality inclusive)
        assert route_after["status"] == "SUSPENDED"
        assert route_after["blocked_stop_count"] == 1

        # The cascade touches only the ticket pole
        assert get_pole(pole_b["id"])["status"] == "SCHEDULED"
        wo_b = get_work_order(wos[pole_b["id"]]["id"])
        assert wo_b["execution_status"] == "DISPATCHED"
