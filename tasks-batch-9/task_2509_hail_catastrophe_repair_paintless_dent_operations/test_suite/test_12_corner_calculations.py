"""Rounding orders, inclusive floors and conserved purses at their exact edges."""

from test_helpers import (
    CLOCK_T0,
    DIRECTOR,
    SHOP_ESTIMATOR,
    activate_rate_agreement,
    add_damage_line,
    assert_damage_line_pricing,
    assert_money_chain,
    assert_rental_exposure,
    assert_supplement_state,
    assert_technician_pay,
    assert_ticket_pay,
    assert_triage_outcome,
    assert_vehicle_variants,
    assert_warranty_minted,
    bring_vehicle_to,
    draft_rate_agreement,
    estimate_vehicle,
    file_supplement,
    ids_of,
    line_by_panel,
    read_damage_lines,
    read_facility,
    read_insurer,
    read_rate_agreement,
    read_technician,
    read_vehicle,
    read_work_ticket,
    record_inspection,
    release_vehicle,
    review_supplement,
    set_clock,
    setup_operational_facility,
    tech_id,
    ticket_by_technician,
    triage_vehicle,
    validate_error,
    validate_paginated,
)

SECOND_VIN = "1HGCM82633A004353"
SECOND_OWNER = "M. Vasquez"


def _two_rental_cars_finished_on_the_same_day(api):
    """Two rental-bearing cars taken in at `CLOCK_T0` and already `READY`."""
    scenario = setup_operational_facility(api, technicians=("TA", "TB"))
    first = bring_vehicle_to(
        api,
        scenario,
        "READY",
        damage_profile="single_panel_conventional",
        inspector="TB",
    )
    second = bring_vehicle_to(
        api,
        scenario,
        "READY",
        damage_profile="single_panel_conventional",
        inspector="TB",
        vin=SECOND_VIN,
        owner_name=SECOND_OWNER,
    )
    return scenario, first, second


def test_the_rental_cap_day_is_inclusive_and_the_next_day_costs_the_shop(api):
    """PRD §3.9: "With a rental open, `rental_days_billed` is the whole number of
    calendar days between the date of `rental_opened_at` and the date of
    `rental_closed_at`, floored at a minimum of one day so that a same-day
    turnaround still bills a day; the difference is a calendar-date difference, not
    an elapsed-hours conversion."

    PRD §3.9: "Excess days are the billed days minus `rental_cap_days`, floored at
    zero, and `shop_absorbed_rental_cents` is those excess days multiplied by the
    sheet's `rental_daily_rate_cents` — the exposure the carrier will not cover and
    the shop eats. A rental that lands on exactly `rental_cap_days` absorbs
    nothing."

    PRD §2.8: "`absorbed_rental_cents` is the sum of `shop_absorbed_rental_cents`
    over that facility's vehicles whose `repair_status` is `RELEASED` or
    `TOWED_OUT`."

    Design: Corner/calculations/rental_absorption_starts_only_past_the_cap_day
    """
    scenario, first, second = _two_rental_cars_finished_on_the_same_day(api)
    assert read_vehicle(api, first["vehicle_id"])["rental_opened_at"] == CLOCK_T0
    assert read_vehicle(api, second["vehicle_id"])["rental_opened_at"] == CLOCK_T0

    # Exactly ten calendar days later — the cap day itself.
    set_clock(api, "2026-08-15T09:00:00Z")
    on_the_cap = release_vehicle(api, first["vehicle_id"])
    assert_rental_exposure(
        on_the_cap, rental_days_billed=10, shop_absorbed_rental_cents=0
    )
    assert on_the_cap["rental_closed_at"] == "2026-08-15T09:00:00Z"
    assert_warranty_minted(
        on_the_cap,
        warranty_number="PDR-0001",
        warranty_expires_at="2026-11-13T09:00:00Z",
    )

    # One day past it, and the shop eats a single day at 4,500 cents.
    set_clock(api, "2026-08-16T09:00:00Z")
    past_the_cap = release_vehicle(api, second["vehicle_id"])
    assert_rental_exposure(
        past_the_cap, rental_days_billed=11, shop_absorbed_rental_cents=4500
    )
    assert_warranty_minted(
        past_the_cap,
        warranty_number="PDR-0002",
        warranty_expires_at="2026-11-14T09:00:00Z",
    )

    # The absorbed exposure never reaches the carrier's bill.
    assert on_the_cap["net_billable_cents"] == 80850
    assert past_the_cap["net_billable_cents"] == 80850

    facility = read_facility(api, scenario["facility_id"])
    assert facility["absorbed_rental_cents"] == 4500
    assert facility["warranty_counter"] == 2
    assert facility["billable_accrued_cents"] == 161700
    assert facility["staging_slots_occupied"] == 0


def _two_identical_triaged_cars(api):
    """Two three-panel cars triaged at the same 202,886-cent approved repair."""
    scenario = setup_operational_facility(api)
    first = bring_vehicle_to(api, scenario, "TRIAGED", rental_required=False)
    second = bring_vehicle_to(
        api,
        scenario,
        "TRIAGED",
        rental_required=False,
        vin=SECOND_VIN,
        owner_name=SECOND_OWNER,
    )
    return scenario, first, second


def test_one_more_cent_of_supplement_lowers_the_carrier_bill_by_4999(api):
    """PRD §3.6: "Step four selects a volume discount rate from the gross amount,
    checking the higher tier first: 4 percent when `gross_billable_cents` is at or
    above 500,000 cents (5,000 dollars), otherwise 2 percent when it is at or above
    250,000 cents (2,500 dollars), and otherwise 0 percent. Both tier comparisons
    are inclusive at their floor, so a gross of exactly 250,000 cents earns the 2
    percent tier."

    PRD §2.7: "Second, in the billable waterfall the administrative fee is keyed on
    the repair subtotal while the volume discount is keyed on the gross amount that
    already contains that fee; the fee is never keyed on the discounted amount, and
    the chain is never iterated to a fixed point."

    PRD §3.8: "`APPROVE` moves `UNDER_REVIEW` → `APPROVED`, terminal, sets
    `approved_amount_cents` to `requested_amount_cents`, stamps `decided_at`,
    increments the supplement's `version`, and runs exactly the same three-hop
    cascade as an auto-approval: vehicle money chain first, then the facility's
    `billable_accrued_cents` when the vehicle's `billing_status` is `AUTHORIZED`,
    `BILLED` or `PAID`, then the carrier's `outstanding_direct_bill_cents`."

    Design: Corner/calculations/one_extra_cent_of_subtotal_crosses_the_volume_discount_floor
    """
    scenario, first, second = _two_identical_triaged_cars(api)
    insurer_id = scenario["insurer_id"]

    # 35,208 and 35,209 both clear the 81,154 cumulative cap and both exceed the
    # 20,289 auto-approve threshold, so each needs the carrier's own APPROVE.
    below = file_supplement(
        api, first["vehicle_id"], 35208, reason_code="ADDITIONAL_PANEL"
    )
    above = file_supplement(
        api, second["vehicle_id"], 35209, reason_code="ADDITIONAL_PANEL"
    )
    assert_supplement_state(below, status="UNDER_REVIEW", round_index=1)
    assert_supplement_state(above, status="UNDER_REVIEW", round_index=1)

    decided_below = review_supplement(api, below["id"], insurer_id, "APPROVE")
    decided_above = review_supplement(api, above["id"], insurer_id, "APPROVE")
    assert_supplement_state(
        decided_below, status="APPROVED", approved_amount_cents=35208
    )
    assert_supplement_state(
        decided_above, status="APPROVED", approved_amount_cents=35209
    )

    under_the_floor = read_vehicle(api, first["vehicle_id"])
    assert under_the_floor["approved_supplement_cents"] == 35208
    assert_money_chain(
        under_the_floor,
        admin_fee_cents=11905,
        gross_billable_cents=249999,
        discount_cents=0,
        net_billable_cents=249999,
    )

    on_the_floor = read_vehicle(api, second["vehicle_id"])
    assert on_the_floor["approved_supplement_cents"] == 35209
    assert_money_chain(
        on_the_floor,
        admin_fee_cents=11905,
        gross_billable_cents=250000,
        discount_cents=5000,
        net_billable_cents=245000,
    )

    # One extra cent of subtotal makes the carrier bill 4,999 cents less.
    assert (
        on_the_floor["net_billable_cents"]
        == under_the_floor["net_billable_cents"] - 4999
    )
    assert under_the_floor["approved_repair_cents"] == 202886
    assert on_the_floor["approved_repair_cents"] == 202886
    assert under_the_floor["matrix_variant_total_cents"] == 202886
    assert on_the_floor["matrix_variant_total_cents"] == 202886

    # Neither car was ever authorized, so nothing reached the ledgers.
    assert read_facility(api, scenario["facility_id"])["billable_accrued_cents"] == 0
    assert read_insurer(api, insurer_id)["outstanding_direct_bill_cents"] == 0


def test_the_capped_panel_takes_the_whole_car_off_the_paintless_path(api):
    """PRD §3.5: "The rounded value is then compared against the sheet's
    `panel_cap_cents`: if it is strictly greater than the cap, `capped` becomes true
    and `pdr_line_cents` is reduced to exactly the cap; otherwise `capped` stays
    false and the rounded value stands. A panel is routed to `CONVENTIONAL` in
    `routed_to` when it was capped or when its `oversize_dent_count` is greater than
    zero, and to `PDR` otherwise."

    PRD §3.5: "Feasibility follows from the panel-level findings: `pdr_feasible` is
    true only when no damage line of the vehicle was capped and the total of every
    line's `oversize_dent_count` across the vehicle is zero. A single capped panel
    or a single oversize dent anywhere on the car takes the whole vehicle off the
    paintless path."

    PRD §3.6: "It then picks a candidate. If `pdr_feasible` is false, the candidate
    is `CONVENTIONAL` at the vehicle's `conventional_variant_total_cents` — the
    paintless path is simply unavailable."

    Design: Corner/calculations/capped_panel_forces_the_conventional_variant_and_reprices_the_bill
    """
    scenario = setup_operational_facility(api)
    car = bring_vehicle_to(
        api,
        scenario,
        "MATRIX",
        damage_profile="capped_panel",
        rental_required=False,
    )
    vehicle_id = car["vehicle_id"]

    estimated = estimate_vehicle(api, vehicle_id)
    assert_vehicle_variants(
        estimated,
        matrix_variant_total_cents=140000,
        conventional_variant_total_cents=118500,
        pdr_feasible=False,
    )

    panel = line_by_panel(read_damage_lines(api, vehicle_id), "DECK_LID")
    assert_damage_line_pricing(
        panel,
        pdr_line_cents=140000,
        conventional_line_cents=118500,
        capped=True,
        routed_to="CONVENTIONAL",
    )

    rerouted, meta = validate_paginated(
        api.list_vehicle_damage_lines(
            vehicle_id, SHOP_ESTIMATOR, {"routed_to": "CONVENTIONAL"}
        )
    )
    assert meta["total_count"] == 1
    assert ids_of(rerouted) == [panel["id"]]

    triaged = triage_vehicle(api, vehicle_id)
    # The clamped matrix total is 140,000, but the conventional path is the one
    # that gets approved and billed.
    assert_triage_outcome(
        triaged,
        triage_disposition="CONVENTIONAL",
        approved_repair_cents=118500,
        repair_status="TRIAGED",
    )
    assert triaged["approved_repair_cents"] != 140000
    assert_money_chain(
        triaged,
        admin_fee_cents=5925,
        gross_billable_cents=124425,
        discount_cents=0,
        net_billable_cents=124425,
    )
    assert triaged["rework_count"] == 0


POOLED_TICKET_SPECS = [
    {"tech": "TA", "labor_units": 4.0, "dents_repaired": 42, "panels_worked": 1},
    {"tech": "TB", "labor_units": 4.0, "dents_repaired": 15, "panels_worked": 1},
    {"tech": "TD", "labor_units": 4.0, "dents_repaired": 9, "panels_worked": 1},
]


def test_the_pooled_purse_is_conserved_by_docking_the_largest_fraction(api):
    """PRD §3.7: "Each ticket's exact share is the purse multiplied by that
    ticket's weight divided by the total weight across the set, and
    `payable_pooled_cents` is that exact share rounded half up to whole cents."

    PRD §3.7: "When the residual is not zero it is applied in full to a single
    ticket: the one whose exact share had the largest fractional part, with ties
    broken by `created_at` ascending and never by identifier. That ticket's
    `payable_pooled_cents` absorbs the residual, whether positive or negative, so
    that the pooled payouts sum to exactly the purse."

    PRD §3.7: "A ticket's work value is the labour pool multiplied by that ticket's
    `labor_units` divided by the total labour units, rounded half up to whole cents;
    the ticket's `payable_flat_cents` is that work value multiplied by the
    technician's own `flat_split_pct`, again rounded half up to whole cents. Nothing
    constrains the flat payouts to sum to any particular figure."

    Design: Corner/calculations/pooled_residual_adds_the_stray_cent_to_the_largest_fraction
    """
    scenario = setup_operational_facility(
        api, pay_model="POOLED", technicians=("TA", "TB", "TD", "TI")
    )
    car = bring_vehicle_to(
        api, scenario, "QC_PENDING", ticket_specs=POOLED_TICKET_SPECS
    )
    assert car["vehicle"]["approved_repair_cents"] == 202886

    inspection = record_inspection(api, car["vehicle_id"], tech_id(scenario, "TI"))
    assert inspection["result"] == "PASS"
    assert inspection["rework_index"] == 0
    assert read_vehicle(api, car["vehicle_id"])["repair_status"] == "READY"

    tickets = [read_work_ticket(api, t["id"]) for t in car["work_tickets"]]
    master = ticket_by_technician(tickets, tech_id(scenario, "TA"))
    journeyman = ticket_by_technician(tickets, tech_id(scenario, "TB"))
    apprentice = ticket_by_technician(tickets, tech_id(scenario, "TD"))

    assert_ticket_pay(
        master,
        payable_flat_cents=16738,
        payable_pooled_cents=22866,
        payable_cents=22866,
        pay_model_applied="POOLED",
        status="APPROVED",
    )
    assert_ticket_pay(
        journeyman,
        payable_flat_cents=14878,
        payable_pooled_cents=18293,
        payable_cents=18293,
        pay_model_applied="POOLED",
        status="APPROVED",
    )
    # 14,634 by independent rounding, plus the whole +1 residual.
    assert_ticket_pay(
        apprentice,
        payable_flat_cents=11159,
        payable_pooled_cents=14635,
        payable_cents=14635,
        pay_model_applied="POOLED",
        status="APPROVED",
    )

    pooled = [t["payable_pooled_cents"] for t in tickets]
    flat = [t["payable_flat_cents"] for t in tickets]
    assert sum(pooled) == 55794
    # The flat column conserves nothing, which is how the two variants are shown
    # to be computed independently of one another.
    assert sum(flat) == 42775
    assert sum(flat) != sum(pooled)

    assert_technician_pay(
        read_technician(api, tech_id(scenario, "TA")),
        accrued_pay_cents=22866,
        approved_ticket_count=1,
    )
    assert_technician_pay(
        read_technician(api, tech_id(scenario, "TB")),
        accrued_pay_cents=18293,
        approved_ticket_count=1,
    )
    assert_technician_pay(
        read_technician(api, tech_id(scenario, "TD")),
        accrued_pay_cents=14635,
        approved_ticket_count=1,
    )
    assert_technician_pay(
        read_technician(api, tech_id(scenario, "TI")),
        accrued_pay_cents=0,
        approved_ticket_count=0,
    )


ONE_CHEAP_HOOD = [
    {
        "panel_code": "HOOD",
        "dent_count": 20,
        "dent_size_class": "NICKEL",
        "aluminum": False,
        "r_and_i_hours": 0,
        "conventional_labor_hours": 8.0,
        "conventional_paint_materials_cents": 25000,
    },
]

TIED_TICKET_SPECS = [
    {"tech": "TB", "labor_units": 4.0, "dents_repaired": 10, "panels_worked": 1},
    {"tech": "TC", "labor_units": 4.0, "dents_repaired": 10, "panels_worked": 1},
]


def test_a_negative_residual_docks_the_older_of_two_tied_tickets(api):
    """PRD §3.7: "The vehicle's labour pool is 55 percent of its
    `approved_repair_cents`, rounded half up to whole cents — note that supplements
    never enter the labour pool, which is keyed on the approved repair value alone."

    PRD §3.7: "When the residual is not zero it is applied in full to a single
    ticket: the one whose exact share had the largest fractional part, with ties
    broken by `created_at` ascending and never by identifier. That ticket's
    `payable_pooled_cents` absorbs the residual, whether positive or negative, so
    that the pooled payouts sum to exactly the purse."

    PRD §3.7: "Each approved ticket records `pay_model_applied` as a copy of the
    vehicle's facility `pay_model` at the moment of approval, and `payable_cents` is
    `payable_flat_cents` when that copy is `FLAT` and `payable_pooled_cents` when it
    is `POOLED`."

    Design: Corner/calculations/negative_pooled_residual_breaks_a_fraction_tie_by_created_at
    """
    scenario = setup_operational_facility(
        api, pay_model="POOLED", technicians=("TB", "TC", "TI")
    )
    car = bring_vehicle_to(
        api,
        scenario,
        "QC_PENDING",
        damage_profile=ONE_CHEAP_HOOD,
        ticket_specs=TIED_TICKET_SPECS,
    )
    assert car["vehicle"]["approved_repair_cents"] == 51204
    assert car["vehicle"]["matrix_variant_total_cents"] == 51204

    record_inspection(api, car["vehicle_id"], tech_id(scenario, "TI"))
    assert read_vehicle(api, car["vehicle_id"])["repair_status"] == "READY"

    older = read_work_ticket(api, car["work_tickets"][0]["id"])
    newer = read_work_ticket(api, car["work_tickets"][1]["id"])
    assert older["created_at"] < newer["created_at"]
    assert older["technician_id"] == tech_id(scenario, "TB")
    assert newer["technician_id"] == tech_id(scenario, "TC")

    # Both exact shares are 7,040.5, so both round to 7,041 and the residual is
    # minus one cent; the older ticket is the one that gives it back.
    assert_ticket_pay(
        older,
        payable_flat_cents=5632,
        payable_pooled_cents=7040,
        payable_cents=7040,
        pay_model_applied="POOLED",
        status="APPROVED",
    )
    assert_ticket_pay(
        newer,
        payable_flat_cents=5632,
        payable_pooled_cents=7041,
        payable_cents=7041,
        pay_model_applied="POOLED",
        status="APPROVED",
    )
    assert older["payable_pooled_cents"] + newer["payable_pooled_cents"] == 14081

    assert_technician_pay(
        read_technician(api, tech_id(scenario, "TB")), accrued_pay_cents=7040
    )
    assert_technician_pay(
        read_technician(api, tech_id(scenario, "TC")), accrued_pay_cents=7041
    )


def test_the_estimate_gate_names_the_missing_sheet_before_the_missing_matrix(api):
    """PRD §3.5: "The candidate agreements are those whose `insurer_id` equals the
    vehicle's `insurer_id`, whose `storm_event_id` equals the storm event of the
    vehicle's facility, whose `status` is `ACTIVE`, and whose `effective_from` is no
    later than the current clock date. Drafted and superseded sheets are not
    candidates."

    PRD §3.5: "Any other repair state is rejected with
    `ERR_INVALID_VEHICLE_REPAIR_STATE`, and a vehicle with no damage lines at all
    is rejected with `ERR_NO_DAMAGE_LINES`."

    PRD §2.11: "**Rate agreement resolvable** — `ERR_NO_ACTIVE_RATE_AGREEMENT`
    (409), on `POST /hail-ops/vehicles/{id}/estimate` and `POST
    /hail-ops/supplements`."

    PRD §3.4: "The cascade then runs two hops: every other agreement sharing the
    same carrier and the same storm event that was `ACTIVE` is moved to
    `SUPERSEDED` with its own `version` increment, and the carrier's `version`
    increments by one while its `active_rate_agreement_count` is recomputed."

    Design: Corner/calculations/estimate_gate_walks_from_no_active_agreement_to_no_damage_lines
    """
    scenario = setup_operational_facility(
        api,
        rate_agreement_overrides={"effective_from": "2026-09-01"},
        activate_rate_sheet=False,
    )
    car = bring_vehicle_to(api, scenario, "INTAKE", rental_required=False)
    vehicle_id = car["vehicle_id"]
    insurer_id = scenario["insurer_id"]
    future_id = scenario["rate_agreement_id"]

    # A `DRAFT` sheet is invisible to the selector.
    validate_error(
        api.estimate_vehicle(vehicle_id, SHOP_ESTIMATOR),
        "ERR_NO_ACTIVE_RATE_AGREEMENT",
        409,
    )

    # So is an `ACTIVE` sheet whose `effective_from` is still in the future.
    activate_rate_agreement(api, future_id, insurer_id)
    validate_error(
        api.estimate_vehicle(vehicle_id, SHOP_ESTIMATOR),
        "ERR_NO_ACTIVE_RATE_AGREEMENT",
        409,
    )

    live = draft_rate_agreement(
        api, insurer_id, scenario["event_id"], effective_from="2026-08-01"
    )
    activate_rate_agreement(api, live["id"], insurer_id)

    # With the sheet resolvable the empty matrix is finally what answers.
    validate_error(
        api.estimate_vehicle(vehicle_id, SHOP_ESTIMATOR), "ERR_NO_DAMAGE_LINES", 422
    )

    add_damage_line(api, vehicle_id)
    estimated = estimate_vehicle(api, vehicle_id)
    assert estimated["repair_status"] == "ESTIMATED"
    assert_vehicle_variants(
        estimated,
        matrix_variant_total_cents=107528,
        conventional_variant_total_cents=77000,
        pdr_feasible=True,
    )
    assert estimated["pinned_rate_agreement_id"] == live["id"]

    assert read_rate_agreement(api, future_id)["status"] == "SUPERSEDED"
    assert read_rate_agreement(api, live["id"])["status"] == "ACTIVE"
    assert read_insurer(api, insurer_id)["active_rate_agreement_count"] == 1

    rows, meta = validate_paginated(
        api.list_rate_agreements(
            DIRECTOR, {"insurer_id": insurer_id, "status": "ACTIVE"}
        )
    )
    assert meta["total_count"] == 1
    assert ids_of(rows) == [live["id"]]
