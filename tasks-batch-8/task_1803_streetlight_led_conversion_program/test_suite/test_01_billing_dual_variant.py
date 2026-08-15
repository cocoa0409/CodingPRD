"""Billing dual-variant calculations: municipal daily proration vs utility
whole-month deferral, and the paired savings-report methods."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_stop,
    attest_pole_nameplate,
    close_period,
    create_account,
    create_active_program,
    create_crew,
    create_district,
    create_pole,
    create_report,
    create_route,
    dispatch_and_complete,
    generate_lines,
    get_pole,
    get_program,
    get_report,
    list_lines,
    list_work_orders_for_route,
    release_route,
    set_clock,
    setup_effective_rate_schedule,
    submit_and_accept_audit,
    validate_success,
)

PM = TEST_USERS["program_manager_headers"]
BA = TEST_USERS["billing_analyst_headers"]

MUNI_RATES = {"T1": 700, "T2": 1100, "T3": 1500, "T4": 2000, "T5": 2600}
UTIL_RATES = {"T1": 900, "T2": 1300, "T3": 1800, "T4": 2400, "T5": 3000}


def _setup_dual_variant_scenario():
    """Two identical 250W poles (MUNICIPAL audit-cleared, UTILITY_OWNED attested),
    both converted to 90W at 2026-08-16; both rate classes EFFECTIVE from
    2026-01-01; one account per ownership class with current_period 2026-08."""
    program = create_active_program()
    district = create_district(program["id"], zone="RESIDENTIAL")
    crew = create_crew(program["id"])

    pole_m = create_pole(district["id"], pole_number="M-001", ownership_type="MUNICIPAL",
                         fixture_class="COBRA_HEAD", nameplate_wattage=250)
    submit_and_accept_audit(pole_m["id"], 250, crew["id"])
    pole_u = create_pole(district["id"], pole_number="U-001", ownership_type="UTILITY_OWNED",
                         fixture_class="COBRA_HEAD", nameplate_wattage=250)
    attest_pole_nameplate(pole_u["id"])

    setup_effective_rate_schedule(program["id"], "MUNICIPAL", tier_rates=MUNI_RATES)
    setup_effective_rate_schedule(program["id"], "UTILITY_OWNED", tier_rates=UTIL_RATES)
    acct_m = create_account(district["id"], "MUNICIPAL", account_number="AC-M")
    acct_u = create_account(district["id"], "UTILITY_OWNED", account_number="AC-U")

    route = create_route(district["id"], crew["id"], start="2026-08-16", end="2026-08-16")
    add_stop(route["id"], pole_m["id"], 1, difficulty_class="STANDARD")
    add_stop(route["id"], pole_u["id"], 2, difficulty_class="STANDARD")
    release_route(route["id"])
    wos = list_work_orders_for_route(route["id"])
    assert len(wos) == 2, "Setup failed: expected 2 work orders"
    wo_by_pole = {wo["pole_id"]: wo for wo in wos}

    set_clock("2026-08-16T09:00:00Z")
    for pole_id in (pole_m["id"], pole_u["id"]):
        dispatch_and_complete(wo_by_pole[pole_id]["id"], crew["id"],
                              wattage=90, cct=2700, shielding="FULL_CUTOFF")

    return {
        "program": program, "district": district, "crew": crew,
        "pole_m": get_pole(pole_m["id"]), "pole_u": get_pole(pole_u["id"]),
        "acct_m": acct_m, "acct_u": acct_u,
    }


def _line_for_pole(account_id, pole_id, period):
    lines = list_lines(account_id=account_id, pole_id=pole_id, period=period)
    assert len(lines) == 1, f"expected exactly one line for pole {pole_id} in {period}"
    return lines[0]


class TestBillingProrationVsWholeMonthDeferral:
    def test_conversion_month_charges_diverge_by_ownership(self, api):
        """PRD section 3.5: "For a MUNICIPAL pole the month prorates daily ...
        each prorated part computed as its rate times its day count divided by D
        and rounded half-up individually, the parts then summed, with
        billing_wattage and tier reflecting the LED. For a UTILITY_OWNED pole
        the conversion month defers wholesale: ... with an in-service date within
        the period, the entire conversion period still bills the old rate at
        effective_wattage and the new rate applies only from the next period".

        Design: Difficulty/dual_variant_calc/billing_proration_vs_whole_month_deferral
        """
        ctx = _setup_dual_variant_scenario()
        generate_lines(ctx["acct_m"]["id"])
        generate_lines(ctx["acct_u"]["id"])

        line_m = _line_for_pole(ctx["acct_m"]["id"], ctx["pole_m"]["id"], "2026-08")
        line_u = _line_for_pole(ctx["acct_u"]["id"], ctx["pole_u"]["id"], "2026-08")

        # MUNICIPAL: rhu(1500*15/31)=726 + rhu(700*16/31)=361 -> 1087
        assert line_m["charge_cents"] == 1087, (
            f"municipal prorated charge should be 1087, got {line_m['charge_cents']}"
        )
        # UTILITY_OWNED: whole conversion month at OLD utility T3 rate
        assert line_u["charge_cents"] == 1800, (
            f"utility deferred charge should be 1800, got {line_u['charge_cents']}"
        )
        assert line_m["charge_cents"] != line_u["charge_cents"]
        assert line_m["tier"] == "T1" and line_m["billing_wattage"] == 90
        assert line_u["tier"] == "T3" and line_u["billing_wattage"] == 250

    def test_next_period_lines_converge_to_new_tier_rates(self, api):
        """PRD section 3.5: "with an in-service date on or before the period's
        first day, the whole period bills the new rate with billing_wattage equal
        to led_wattage" (municipal); and for utility-owned, "with an in-service
        date before the period start, the new rate applies."

        Design: Difficulty/dual_variant_calc/billing_proration_vs_whole_month_deferral
        """
        ctx = _setup_dual_variant_scenario()
        generate_lines(ctx["acct_m"]["id"])
        generate_lines(ctx["acct_u"]["id"])
        close_period(ctx["acct_m"]["id"])
        close_period(ctx["acct_u"]["id"])
        generate_lines(ctx["acct_m"]["id"])
        generate_lines(ctx["acct_u"]["id"])

        line_m_sep = _line_for_pole(ctx["acct_m"]["id"], ctx["pole_m"]["id"], "2026-09")
        line_u_sep = _line_for_pole(ctx["acct_u"]["id"], ctx["pole_u"]["id"], "2026-09")
        # Municipal: full September at new T1 rate
        assert line_m_sep["charge_cents"] == 700
        # Utility: deferral ended; new T1 rate from the next period
        assert line_u_sep["charge_cents"] == 900
        assert line_m_sep["tier"] == "T1" and line_m_sep["billing_wattage"] == 90
        assert line_u_sep["tier"] == "T1" and line_u_sep["billing_wattage"] == 90


def _setup_savings_scenario():
    """One MUNICIPAL pole 250W audit-accepted, converted to 90W with
    led_in_service_date 2026-08-16. Returns (program, pole)."""
    program = create_active_program()
    district = create_district(program["id"], zone="RESIDENTIAL")
    crew = create_crew(program["id"])
    pole = create_pole(district["id"], pole_number="M-101", ownership_type="MUNICIPAL",
                       fixture_class="POST_TOP", nameplate_wattage=250)
    submit_and_accept_audit(pole["id"], 250, crew["id"])
    route = create_route(district["id"], crew["id"], start="2026-08-01", end="2026-08-31")
    add_stop(route["id"], pole["id"], 1, difficulty_class="STANDARD")
    release_route(route["id"])
    wo = list_work_orders_for_route(route["id"])[0]
    set_clock("2026-08-16T09:00:00Z")
    dispatch_and_complete(wo["id"], crew["id"], wattage=90, cct=2700, shielding="FULL_CUTOFF")
    return program, get_pole(pole["id"])


class TestSavingsEstimateVsMeteredActual:
    def test_engineering_estimate_credits_full_month(self, api):
        """PRD section 3.8: "Under ENGINEERING_ESTIMATE, each pole's baseline is
        its pre_conversion_wattage times the month's burn hours divided by 1000,
        and its actual is its led_wattage times burn hours divided by 1000 — the
        full month credited regardless of the in-service day."

        Design: Difficulty/dual_variant_calc/savings_estimate_vs_metered_actual
        """
        program, _pole = _setup_savings_scenario()
        rep = create_report(program["id"], period="2026-08", method="ENGINEERING_ESTIMATE")
        # Aug burn hours 310: baseline 250*310/1000 = 77.500; actual 90*310/1000 = 27.900
        assert rep["baseline_kwh"] == pytest.approx(77.500, abs=0.0005)
        assert rep["actual_kwh"] == pytest.approx(27.900, abs=0.0005)
        assert rep["savings_kwh"] == pytest.approx(49.600, abs=0.0005)

    def test_metered_actual_prorates_and_recreates_supersede(self, api):
        """PRD section 3.8: "Under METERED_ACTUAL, the baseline is the same
        full-month old-fixture figure, while the actual prorates: the old fixture
        burns the period's days before the in-service date and the LED burns from
        the in-service date onward".
        PRD section 3.8: "a prior DRAFT or REJECTED report for the same pair is
        automatically SUPERSEDED by the new create."

        Design: Difficulty/dual_variant_calc/savings_estimate_vs_metered_actual
        """
        program, _pole = _setup_savings_scenario()
        rep_est = create_report(program["id"], period="2026-08", method="ENGINEERING_ESTIMATE")
        rep_act = create_report(program["id"], period="2026-08", method="METERED_ACTUAL")

        # d_old = 15, d_new = 16 of 31; actual = (250*310*15/31 + 90*310*16/31)/1000 = 51.900
        assert rep_act["baseline_kwh"] == pytest.approx(77.500, abs=0.0005)
        assert rep_act["actual_kwh"] == pytest.approx(51.900, abs=0.0005)
        assert rep_act["savings_kwh"] == pytest.approx(25.600, abs=0.0005)
        # Same (program, period): second create supersedes the DRAFT first report
        superseded = get_report(rep_est["id"])
        assert superseded["status"] == "SUPERSEDED"
        assert rep_act["status"] == "DRAFT"
        assert rep_est["savings_kwh"] - rep_act["savings_kwh"] == pytest.approx(24.000, abs=0.001)
