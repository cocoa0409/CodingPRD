"""Two independent calculations that each publish two variants of one figure."""

from test_helpers import (
    assert_damage_line_pricing,
    assert_money_chain,
    assert_technician_pay,
    assert_ticket_pay,
    assert_triage_outcome,
    assert_vehicle_variants,
    bring_vehicle_to,
    line_by_panel,
    read_damage_lines,
    read_technician,
    read_vehicle,
    read_work_ticket,
    record_inspection,
    setup_operational_facility,
    tech_id,
    ticket_by_technician,
)

THREE_PANEL_MATRIX_TOTAL = 202886
THREE_PANEL_CONVENTIONAL_TOTAL = 257750


def test_estimate_prices_every_panel_under_both_philosophies(api):
    """PRD §3.5: "The **conventional variant** prices the same panel as
    `conventional_labor_hours` multiplied by the sheet's
    `labor_rate_cents_per_hour`, plus `conventional_paint_materials_cents`,
    rounded half up to whole cents and stored as `conventional_line_cents`; it
    ignores dent counts, tier multipliers and the aluminum multiplier entirely,
    and the paintless variant in turn ignores paint materials entirely, which is
    why identical panel rows produce genuinely different variant totals."

    PRD §3.5: "Both variants price every panel, and the vehicle's two totals are
    then the sums of the rounded per-panel values: `matrix_variant_total_cents`
    is the sum of every `pdr_line_cents` (post-cap, where a cap applied), and
    `conventional_variant_total_cents` is the sum of every
    `conventional_line_cents`."

    Design: Difficulty/dual_variant_calc/pdr_versus_conventional_variant_divergence_on_estimate
    """
    scenario = setup_operational_facility(api)
    car = bring_vehicle_to(api, scenario, "ESTIMATED", damage_profile="three_panel")
    vehicle = car["vehicle"]

    assert_vehicle_variants(
        vehicle,
        matrix_variant_total_cents=THREE_PANEL_MATRIX_TOTAL,
        conventional_variant_total_cents=THREE_PANEL_CONVENTIONAL_TOTAL,
        pdr_feasible=True,
    )
    assert (
        vehicle["conventional_variant_total_cents"]
        - vehicle["matrix_variant_total_cents"]
        == 54864
    )
    assert vehicle["pinned_rate_agreement_id"] == scenario["rate_agreement_id"]

    lines = read_damage_lines(api, car["vehicle_id"])
    assert_damage_line_pricing(
        line_by_panel(lines, "HOOD"),
        pdr_line_cents=110778,
        conventional_line_cents=77000,
        capped=False,
        routed_to="PDR",
    )
    assert_damage_line_pricing(
        line_by_panel(lines, "ROOF"),
        pdr_line_cents=42945,
        conventional_line_cents=104000,
        capped=False,
        routed_to="PDR",
    )
    assert_damage_line_pricing(
        line_by_panel(lines, "LEFT_QUARTER"),
        pdr_line_cents=49163,
        conventional_line_cents=76750,
        capped=False,
        routed_to="PDR",
    )


def test_triage_selects_the_cheaper_feasible_variant_as_the_approved_repair(api):
    """PRD §3.6: "Otherwise, if `matrix_variant_total_cents` is less than or
    equal to `conventional_variant_total_cents`, the candidate is `PDR_REPAIR`
    at the matrix total, ties going to paintless."

    PRD §3.6: "Otherwise `triage_disposition` becomes the candidate, either
    `PDR_REPAIR` or `CONVENTIONAL`, and `approved_repair_cents` becomes the
    candidate cost."

    Design: Difficulty/dual_variant_calc/pdr_versus_conventional_variant_divergence_on_estimate
    """
    scenario = setup_operational_facility(api)
    car = bring_vehicle_to(api, scenario, "TRIAGED", damage_profile="three_panel")
    vehicle = car["vehicle"]

    assert_vehicle_variants(
        vehicle,
        matrix_variant_total_cents=THREE_PANEL_MATRIX_TOTAL,
        conventional_variant_total_cents=THREE_PANEL_CONVENTIONAL_TOTAL,
        pdr_feasible=True,
    )
    assert_triage_outcome(
        vehicle,
        triage_disposition="PDR_REPAIR",
        approved_repair_cents=THREE_PANEL_MATRIX_TOTAL,
        repair_status="TRIAGED",
    )
    # The cheaper of the two variants is the one that reaches the money chain.
    assert_money_chain(
        vehicle,
        admin_fee_cents=10144,
        gross_billable_cents=213030,
        discount_cents=0,
        net_billable_cents=213030,
    )


def _crew_pay_scenario(api):
    """A FLAT lot with two workers on one car plus a separate inspector."""
    scenario = setup_operational_facility(api, technicians=("TA", "TB", "TC"))
    car = bring_vehicle_to(
        api,
        scenario,
        "QC_PENDING",
        damage_profile="three_panel",
        ticket_specs=[
            {"tech": "TA", "labor_units": 6.0, "dents_repaired": 40, "panels_worked": 2},
            {"tech": "TB", "labor_units": 4.0, "dents_repaired": 26, "panels_worked": 1},
        ],
    )
    return scenario, car


def test_qc_pass_stores_both_pay_variants_and_conserves_the_pooled_purse(api):
    """PRD §3.7: "The pay computation itself is where the two crew-pay models
    diverge, and both variants are always computed and stored so that the site's
    choice is auditable."

    PRD §3.7: "That ticket's `payable_pooled_cents` absorbs the residual,
    whether positive or negative, so that the pooled payouts sum to exactly the
    purse."

    Design: Difficulty/dual_variant_calc/flat_versus_pooled_crew_pay_variants_on_qc_pass
    """
    scenario, car = _crew_pay_scenario(api)
    record_inspection(api, car["vehicle_id"], tech_id(scenario, "TC"), "PASS")

    ticket_a = read_work_ticket(api, car["work_tickets"][0]["id"])
    ticket_b = read_work_ticket(api, car["work_tickets"][1]["id"])

    assert_ticket_pay(
        ticket_a,
        payable_flat_cents=30128,
        payable_pooled_cents=36387,
        status="APPROVED",
    )
    assert_ticket_pay(
        ticket_b,
        payable_flat_cents=17854,
        payable_pooled_cents=19407,
        status="APPROVED",
    )
    # The pooled variant is conserved to the cent; the flat variant is not.
    assert ticket_a["payable_pooled_cents"] + ticket_b["payable_pooled_cents"] == 55794
    assert ticket_a["payable_flat_cents"] + ticket_b["payable_flat_cents"] == 47982


def test_a_flat_site_pays_the_flat_variant_and_only_that_feeds_accrued_pay(api):
    """PRD §3.7: "Each approved ticket records `pay_model_applied` as a copy of
    the vehicle's facility `pay_model` at the moment of approval, and
    `payable_cents` is `payable_flat_cents` when that copy is `FLAT` and
    `payable_pooled_cents` when it is `POOLED`. Only `payable_cents` feeds a
    technician's `accrued_pay_cents`."

    Design: Difficulty/dual_variant_calc/flat_versus_pooled_crew_pay_variants_on_qc_pass
    """
    scenario, car = _crew_pay_scenario(api)
    record_inspection(api, car["vehicle_id"], tech_id(scenario, "TC"), "PASS")

    tickets = [read_work_ticket(api, t["id"]) for t in car["work_tickets"]]
    ticket_a = ticket_by_technician(tickets, tech_id(scenario, "TA"))
    ticket_b = ticket_by_technician(tickets, tech_id(scenario, "TB"))

    assert_ticket_pay(
        ticket_a,
        payable_flat_cents=30128,
        payable_pooled_cents=36387,
        payable_cents=30128,
        pay_model_applied="FLAT",
    )
    assert_ticket_pay(
        ticket_b,
        payable_flat_cents=17854,
        payable_pooled_cents=19407,
        payable_cents=17854,
        pay_model_applied="FLAT",
    )

    assert_technician_pay(
        read_technician(api, tech_id(scenario, "TA")),
        accrued_pay_cents=30128,
        approved_ticket_count=1,
    )
    assert_technician_pay(
        read_technician(api, tech_id(scenario, "TB")),
        accrued_pay_cents=17854,
        approved_ticket_count=1,
    )
    # The inspector claimed no labour, so nothing accrues to them.
    assert_technician_pay(
        read_technician(api, tech_id(scenario, "TC")),
        accrued_pay_cents=0,
        approved_ticket_count=0,
    )
    assert read_vehicle(api, car["vehicle_id"])["repair_status"] == "READY"
