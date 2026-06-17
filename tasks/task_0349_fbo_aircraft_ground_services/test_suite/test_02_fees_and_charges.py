"""Parking/ramp fee (standard vs waived) and the de-ice service charge (pinned
rounding order, free-holdover boundary) (PRD §3.5, §3.8).

Difficulty queue (A) instances:
  - dual_variant_calc / ramp_fee_standard_vs_waived
  - combinatorial_formula / deice_pinned_rounding_order
Corner queue (B) instances:
  - calculations / deice_no_holdover_surcharge_at_free_boundary
"""
from test_helpers import (
    api_client as api,
    get_success_data,
    setup_operator_aircraft_contract,
    setup_on_ground_visit,
    setup_servicing_visit,
    create_fueled_fuel_order,
    post_into_plane_ticket,
    create_parking_assignment_payload,
    create_deice_service_payload,
    occupy_payload,
    TEST_USERS,
)

OPS = TEST_USERS["ops_dispatcher_headers"]
FUEL = TEST_USERS["fuel_tech_headers"]
LINE = TEST_USERS["line_manager_headers"]


def test_standard_ramp_fee_mid_three_nights_is_45000():
    """PRD §3.5: "The per-night rate is read from the weight class of the aircraft on
    the parent visit: 7,500 cents per night for a `LIGHT` aircraft, 15,000 cents per
    night for a `MID` aircraft, and 32,500 cents per night for a `HEAVY` aircraft."
    PRD §3.5: "A `HANGAR` or `TIE_DOWN` spot never waives, and a `RAMP` spot below the
    200-gallon threshold pays the full weight-class rate times nights."

    A MID aircraft, 3-night RAMP occupation with no fuel delivered prices
    15,000 * 3 = 45,000 cents (standard variant).

    Design: Difficulty/dual_variant_calc/ramp_fee_standard_vs_waived
    """
    operator, aircraft, _contract = setup_operator_aircraft_contract()
    visit = setup_on_ground_visit(operator["id"], aircraft["id"],
                                  visit_overrides={"arrival_utc": "2026-06-14T08:00:00.000Z",
                                                   "departure_utc": "2026-06-17T08:00:00.000Z"})
    spot = get_success_data(api.create_parking_spot(
        {"label": "RAMP-A", "spot_type": "RAMP", "max_weight_class": "HEAVY"}, OPS))
    assignment = get_success_data(api.create_parking_assignment(
        create_parking_assignment_payload(visit["id"], spot["id"],
                                          occupy_start_utc="2026-06-14T08:00:00.000Z",
                                          occupy_end_utc="2026-06-17T08:00:00.000Z"), OPS))
    occupied = get_success_data(api.occupy_parking_assignment(
        assignment["id"], occupy_payload(assignment["version"]), OPS))
    assert occupied["fee_cents"] == 45000, (
        f"MID 3-night RAMP with no waiver should be 45000, got {occupied['fee_cents']}"
    )


def test_ramp_fee_waived_to_zero_when_200_jeta_gallons_delivered():
    """PRD §3.5: "If, at occupy time, the same operator has at least 200 Jet-A gallons
    delivered on this visit — measured as the sum of `delivered_gallons` across the
    into-plane tickets of this visit's `FUELED`, non-tankering, Jet-A fuel orders —
    then the parking fee is forced to 0 cents, but only for a `RAMP` spot (transient
    ramp parking)."

    A MID 3-night RAMP occupation on a visit with a FUELED 6000-gal Jet-A order (ticket
    delivered 6000 >= 200) waives the fee to 0, diverging from the standard variant.

    Design: Difficulty/dual_variant_calc/ramp_fee_standard_vs_waived
    """
    operator, aircraft, contract = setup_operator_aircraft_contract()
    visit = setup_on_ground_visit(operator["id"], aircraft["id"],
                                  visit_overrides={"arrival_utc": "2026-06-20T08:00:00.000Z",
                                                   "departure_utc": "2026-06-23T08:00:00.000Z"})
    order = create_fueled_fuel_order(visit["id"], aircraft["id"], contract["id"],
                                     ordered_gallons=6000, tankering=False)
    post_into_plane_ticket(order["id"], 6000)
    spot = get_success_data(api.create_parking_spot(
        {"label": "RAMP-B", "spot_type": "RAMP", "max_weight_class": "HEAVY"}, OPS))
    assignment = get_success_data(api.create_parking_assignment(
        create_parking_assignment_payload(visit["id"], spot["id"],
                                          occupy_start_utc="2026-06-20T08:00:00.000Z",
                                          occupy_end_utc="2026-06-23T08:00:00.000Z"), OPS))
    occupied = get_success_data(api.occupy_parking_assignment(
        assignment["id"], occupy_payload(assignment["version"]), OPS))
    assert occupied["fee_cents"] == 0, (
        f"RAMP fee should waive to 0 with >=200 Jet-A delivered, got {occupied['fee_cents']}"
    )


def test_deice_charge_pinned_rounding_40gal_type_iv_25min_is_104800():
    """PRD §3.8: "The fluid base term is `deice_fluid_gallons` multiplied by 1,800 cents
    per gallon, multiplied by a dilution factor of 1.0 for `TYPE_I` fluid or 1.4 for
    `TYPE_IV` fluid. The holdover surcharge is the holdover minutes beyond a 15-minute
    free allowance — that is, the larger of zero and `deice_holdover_minutes` minus 15 —
    multiplied by 400 cents per minute. The final `charge_cents` is the fluid base term,
    rounded to whole cents half up, plus the (already whole-cent) surcharge; the rounding
    is applied to the fluid base term before the surcharge is added, and this order is
    fixed."

    40 gal TYPE_IV: base = 40*1800*1.4 = 100,800; surcharge = (25-15)*400 = 4,000;
    total = 104,800 cents.

    Design: Difficulty/combinatorial_formula/deice_pinned_rounding_order
    """
    operator, aircraft, _contract = setup_operator_aircraft_contract()
    visit, _spot, _assignment = setup_servicing_visit(
        operator["id"], aircraft["id"], spot_overrides={"label": "TD-1"})
    service = get_success_data(api.create_ramp_service(
        create_deice_service_payload(visit["id"], deice_fluid_gallons=40,
                                     deice_fluid_type="TYPE_IV", deice_holdover_minutes=25), OPS))
    get_success_data(api.start_ramp_service(service["id"], LINE))
    completed = get_success_data(api.complete_ramp_service(service["id"], LINE))
    assert completed["charge_cents"] == 104800, (
        f"40 gal TYPE_IV with 25 min holdover should charge 104800, got {completed['charge_cents']}"
    )


def test_deice_charge_no_surcharge_at_free_holdover_boundary():
    """PRD §3.8: "The holdover surcharge is the holdover minutes beyond a 15-minute free
    allowance — that is, the larger of zero and `deice_holdover_minutes` minus 15 —
    multiplied by 400 cents per minute."

    A DE_ICE service with exactly 15 holdover minutes incurs zero surcharge:
    30 gal TYPE_I base = 30*1800*1.0 = 54,000 cents, total 54,000.

    Design: Corner/calculations/deice_no_holdover_surcharge_at_free_boundary
    """
    operator, aircraft, _contract = setup_operator_aircraft_contract()
    visit, _spot, _assignment = setup_servicing_visit(
        operator["id"], aircraft["id"], spot_overrides={"label": "TD-44"})
    service = get_success_data(api.create_ramp_service(
        create_deice_service_payload(visit["id"], deice_fluid_gallons=30,
                                     deice_fluid_type="TYPE_I", deice_holdover_minutes=15), OPS))
    get_success_data(api.start_ramp_service(service["id"], LINE))
    completed = get_success_data(api.complete_ramp_service(service["id"], LINE))
    assert completed["charge_cents"] == 54000, (
        f"30 gal TYPE_I at the 15-min free boundary should charge 54000, got {completed['charge_cents']}"
    )
