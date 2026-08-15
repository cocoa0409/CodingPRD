"""Rebate cap evaluation order: attested credit excludes the report itself and
lands exactly on the fiscal-year cap boundary."""
from test_helpers import (
    TEST_USERS,
    add_stop,
    attest_pole_nameplate,
    attest_report,
    close_period,
    create_account,
    create_active_program,
    create_crew,
    create_district,
    create_pole,
    create_report,
    create_route,
    dispatch_and_complete,
    get_pole,
    get_program,
    get_report,
    list_work_orders_for_route,
    release_route,
    submit_report,
    validate_success,
)
import pytest

PM = TEST_USERS["program_manager_headers"]


def _setup_rebate_cap_scenario():
    """Program (budget 500000, fy cap 10000, rebate 50c/kWh); four UTILITY_OWNED
    250W poles converted to 90W on 2026-08-01 (full-month credit both methods);
    MUNICIPAL account closed past 2026-08 then 2026-09 so both periods submit;
    report A (2026-08) attested at 9920."""
    program = create_active_program(budget=500000, rebate_cap=10000, rebate_per_kwh=50)
    district = create_district(program["id"], zone="RESIDENTIAL")
    crew = create_crew(program["id"])
    poles = []
    for i in range(1, 5):
        pole = create_pole(district["id"], pole_number=f"R-{i:02d}",
                           ownership_type="UTILITY_OWNED", fixture_class="COBRA_HEAD",
                           nameplate_wattage=250)
        attest_pole_nameplate(pole["id"])
        poles.append(pole)
    route = create_route(district["id"], crew["id"], start="2026-08-01", end="2026-08-01")
    for i, pole in enumerate(poles):
        add_stop(route["id"], pole["id"], i + 1, difficulty_class="STANDARD")
    release_route(route["id"])
    for wo in list_work_orders_for_route(route["id"]):
        dispatch_and_complete(wo["id"], crew["id"], wattage=90, cct=2700,
                              shielding="FULL_CUTOFF")
    acct = create_account(district["id"], "MUNICIPAL", account_number="AC-M")
    close_period(acct["id"])  # current_period 2026-08 -> 2026-09

    rep_a = create_report(program["id"], period="2026-08", method="METERED_ACTUAL",
                          fiscal_year_label="FY2026")
    submit_report(rep_a["id"])
    attest_report(rep_a["id"], auditor_user_id="auditor-1")

    close_period(acct["id"])  # current_period 2026-09 -> 2026-10
    rep_b = create_report(program["id"], period="2026-09", method="METERED_ACTUAL",
                          fiscal_year_label="FY2026")
    submit_report(rep_b["id"])
    return program["id"], rep_a["id"], rep_b["id"], acct["id"]


class TestRebateCapEvaluationOrderExcludesSelf:
    def test_second_attestation_capped_to_remaining_headroom(self, api):
        """PRD section 3.8: "Attestation computes the capped credit in pinned
        order: start from raw_credit_cents; total the attested_credit_cents of
        the program's other ATTESTED reports sharing the same fiscal_year_label —
        REJECTED, SUPERSEDED, DRAFT, and SUBMITTED reports contribute nothing,
        and the report under attestation excludes itself; the remaining headroom
        is fy_rebate_cap_cents minus that total, floored at zero; and
        attested_credit_cents is the smaller of the raw credit and the headroom."

        Design: Difficulty/combinatorial_formula/rebate_cap_evaluation_order_excludes_self
        """
        _pgm, rep_a_id, rep_b_id, _acct = _setup_rebate_cap_scenario()
        resp = api.attest_savings_report(
            rep_b_id, TEST_USERS["auditor_headers"])
        rep_b = validate_success(resp)
        rep_a = get_report(rep_a_id)

        # 4 poles in-service 2026-08-01 -> Sep: d_new = 30 (full month).
        # baseline 4 x 250*340/1000 = 340.0; actual 4 x 90*340/1000 = 122.4; savings 217.600
        assert rep_b["savings_kwh"] == pytest.approx(217.600, abs=0.0005)
        assert rep_b["raw_credit_cents"] == 10880  # rhu(217.600 * 50), uncapped
        assert rep_b["attested_credit_cents"] == 80  # min(10880, max(0, 10000-9920))
        assert rep_a["attested_credit_cents"] == 9920  # rhu(198.400 * 50)

    def test_attested_credits_land_exactly_on_cap_and_post_to_budget(self, api):
        """PRD section 3.8: "the remaining headroom is fy_rebate_cap_cents minus
        that total, floored at zero; and attested_credit_cents is the smaller of
        the raw credit and the headroom. The credit posts to budget_balance_cents
        exactly once".

        Design: Difficulty/combinatorial_formula/rebate_cap_evaluation_order_excludes_self
        """
        pgm, rep_a_id, rep_b_id, _acct = _setup_rebate_cap_scenario()
        api.attest_savings_report(rep_b_id, TEST_USERS["auditor_headers"])
        rep_a = get_report(rep_a_id)
        rep_b = get_report(rep_b_id)

        total = rep_a["attested_credit_cents"] + rep_b["attested_credit_cents"]
        assert total == 10000, f"FY2026 attested total should land exactly on the cap, got {total}"

        program = get_program(pgm)
        # 500000 - 4*4500 labor + 9920 + 80
        assert program["budget_balance_cents"] == 492000
