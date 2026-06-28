"""Calculation tests for the provisional series-cost estimate and the
first-expiry-first-out (FEFO) lot allocation waterfall (§3.4, §3.6).
"""
from test_helpers import (
    validate_success,
    make_provider_headers,
    make_clinic_admin_headers,
    make_injector,
    make_director,
    make_lot,
    make_patient,
    sign_consent,
    make_consultation,
    complete_exam,
    make_standing_order,
    make_plan,
    activate_plan,
    book_session,
    setup_proposed_plan,
)


def test_provisional_series_cost_at_activation(api):
    """PRD §3.6: "The forward-looking `provisional_series_cost_cents` is an estimate
    over the sessions not yet committed: the number of remaining sessions — the
    plan's `planned_sessions` minus its `sessions_committed`, treated as 0 if that
    difference would be negative — multiplied by `planned_units_per_session`
    multiplied by `list_price_per_unit_cents`." PRD §3.3: "On activation the plan
    recomputes `provisional_series_cost_cents` over all planned sessions, none of
    which are committed yet ..."

    3 sessions * 30 units * 1333 cents = 119970 at activation (0 committed).

    Design: Corner/calculations/provisional_series_cost_at_activation_correct
    """
    sc = setup_proposed_plan(planned_sessions=3, planned_units_per_session=30,
                             list_price_per_unit_cents=1333, required_deposit_cents=0,
                             sign_order=False)
    inj = sc.injector_id
    plan = activate_plan(sc.plan_id, sc.plan_version, inj)
    assert plan["status"] == "ACTIVE"
    assert plan["provisional_series_cost_cents"] == 119970, (
        f"provisional should be 3*30*1333=119970, "
        f"got {plan['provisional_series_cost_cents']}")


def test_lot_fefo_straddles_two_lots_by_expiry(api):
    """PRD §3.4: "It gathers every lot whose product equals the plan's product,
    whose `status` is `AVAILABLE`, and whose `expiration_date` is strictly after the
    current clock, then orders that candidate set by `expiration_date` ascending
    and, where two lots share an expiration, by created_at ascending; the lot id
    is never used as a tiebreaker. Walking that ordered list, it takes from each
    lot the smaller of the units still needed and that lot's `remaining_units`,
    incrementing the lot's `reserved_units` and recomputing its `remaining_units`,
    until the full `planned_units` are reserved."

    Booking 60u against LotA (50u, exp 2026-03-01) and LotB (100u, exp 2026-06-01)
    reserves 50 from the earlier-expiring LotA and 10 from LotB.

    Design: Corner/calculations/lot_fefo_straddles_two_lots_by_expiry
    """
    admin = make_clinic_admin_headers()
    inj = make_injector(license_number="L-FF-I")["id"]
    director = make_director(license_number="L-FF-D")["id"]
    lot_a = make_lot(product="BOTOX", lot_number="LOT-FF-A",
                     expiration_date="2026-03-01T00:00:00Z", total_units=50)["id"]
    lot_b = make_lot(product="BOTOX", lot_number="LOT-FF-B",
                     expiration_date="2026-06-01T00:00:00Z", total_units=100)["id"]
    patient = make_patient(full_name="Ff Pat")["id"]
    sign_consent(patient, inj)
    cons = make_consultation(patient, inj)["id"]
    complete_exam(cons, inj)
    order = make_standing_order(cons, director, product="BOTOX",
                                max_units_authorized=60)["id"]
    plan = make_plan(patient, cons, inj, product="BOTOX", planned_sessions=1,
                     planned_units_per_session=60, list_price_per_unit_cents=1000)
    activated = activate_plan(plan["id"], plan["version"], inj)
    book_session(plan["id"], order, inj, lot_a, 60, activated["version"])

    a = validate_success(api.get_injectable_lot(lot_a, admin))
    b = validate_success(api.get_injectable_lot(lot_b, admin))
    assert a["reserved_units"] == 50, (
        f"LotA (earlier expiry) should reserve 50, got {a['reserved_units']}")
    assert a["remaining_units"] == 0, (
        f"LotA remaining should be 0, got {a['remaining_units']}")
    assert b["reserved_units"] == 10, (
        f"LotB should reserve the spillover 10, got {b['reserved_units']}")
    assert b["remaining_units"] == 90, (
        f"LotB remaining should be 90, got {b['remaining_units']}")
