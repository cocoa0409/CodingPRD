"""Money calculation depth tests (queue A): dual-variant overage & collision
waterfall, IFTA nested rounding, excess-wear threshold. PRD §3.7, §3.8, §3.9.
"""
from test_helpers import (
    TEST_USERS,
    api_client,
    assess_repair_payload,
    create_fuel_transaction_payload,
    create_repair_order_payload,
    create_telematics_reading_payload,
    get_success_data,
    setup_active_lease,
    setup_assessed_repair,
    setup_ifta_return_open,
    setup_settlement_open,
    validate_error,
    validate_success,
)

FM = TEST_USERS["fleet_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]
TG = TEST_USERS["telematics_gateway_headers"]


# ===========================================================================
# dual_variant_calc / overage_contract_flat_vs_tiered_charge_diverges
# ===========================================================================

def test_overage_contract_flat_charge(api):
    """PRD §3.7: "Under `CONTRACT_FLAT`, the charge is the excess miles
    multiplied by the lease's `per_mile_overage_cents` — a single flat rate
    on every excess mile."

    Excess 25000 (85000-0-60000) * 25c = 625000.

    Design: Difficulty/dual_variant_calc/overage_contract_flat_vs_tiered_charge_diverges
    """
    _, _, lease, settlement = setup_settlement_open(
        driven_odometer=85000, overage_model="CONTRACT_FLAT",
        contracted_miles=60000, per_mile_overage_cents=25,
    )
    data = validate_success(api.finalize_settlement(settlement["id"], FM), 200)
    assert data["excess_miles"] == 25000, data
    assert data["mileage_charge_cents"] == 625000, data
    assert data["net_charge_cents"] == 625000, data


def test_overage_tiered_excess_charge_diverges(api):
    """PRD §3.7: "Under `TIERED_EXCESS`, the excess miles are split into two
    tiers: the first ten thousand excess miles are charged at twenty cents
    each, and every excess mile beyond ten thousand is charged at thirty-five
    cents each; the charge is the sum of the two tiers."

    Same excess 25000: 10000*20 + 15000*35 = 725000 (diverges from flat).

    Design: Difficulty/dual_variant_calc/overage_contract_flat_vs_tiered_charge_diverges
    """
    _, _, lease, settlement = setup_settlement_open(
        driven_odometer=85000, overage_model="TIERED_EXCESS",
        contracted_miles=60000, per_mile_overage_cents=25,
        harsh_events=0, idle_minutes=0,
    )
    data = validate_success(api.finalize_settlement(settlement["id"], FM), 200)
    assert data["excess_miles"] == 25000, data
    assert data["mileage_charge_cents"] == 725000, data


# ===========================================================================
# dual_variant_calc / collision_waterfall_deductible_first_vs_insurance_first
# ===========================================================================

def test_waterfall_insurance_first_zero_lessee(api):
    """PRD §3.8: "Under `INSURANCE_FIRST`, the `insurance_paid_cents` is filled
    first as the lesser of the `estimate_cents` and the `insurance_cap_cents`;
    the remaining estimate after that funds the `driver_deductible_cents`,
    taken as the lesser of that remainder and the lease's
    `collision_deductible_cents`; whatever still remains is the overflow."

    est=550000, cap=800000, ded=100000: insurance=550000, remainder=0,
    deductible=0, overflow=0, lessee_responsible=0.

    Design: Difficulty/dual_variant_calc/collision_waterfall_deductible_first_vs_insurance_first_diverges
    """
    _, _, _, repair = setup_assessed_repair(
        estimate_cents=550000, insurance_cap_cents=800000,
        waterfall_model="INSURANCE_FIRST", collision_deductible_cents=100000,
    )
    data = validate_success(api.approve_repair(repair["id"], FM), 200)
    assert data["insurance_paid_cents"] == 550000, data
    assert data["driver_deductible_cents"] == 0, data
    assert data["lessee_responsible_cents"] == 0, data


def test_waterfall_deductible_first_diverges(api):
    """PRD §3.8: "Under `DEDUCTIBLE_FIRST`, the `driver_deductible_cents` is
    filled first as the lesser of the `estimate_cents` and the lease's
    `collision_deductible_cents`; the remaining estimate after that is the
    `insurance_paid_cents`, taken as the lesser of that remainder and the
    `insurance_cap_cents`; whatever still remains is the overflow."

    est=550000, cap=800000, ded=100000: deductible=100000, remainder=450000,
    insurance=450000, overflow=0, lessee_responsible=100000 (diverges from
    INSURANCE_FIRST's 0).

    Design: Difficulty/dual_variant_calc/collision_waterfall_deductible_first_vs_insurance_first_diverges
    """
    _, _, _, repair = setup_assessed_repair(
        estimate_cents=550000, insurance_cap_cents=800000,
        waterfall_model="DEDUCTIBLE_FIRST", collision_deductible_cents=100000,
    )
    data = validate_success(api.approve_repair(repair["id"], FM), 200)
    assert data["driver_deductible_cents"] == 100000, data
    assert data["insurance_paid_cents"] == 450000, data
    assert data["lessee_responsible_cents"] == 100000, data


# ===========================================================================
# combinatorial_formula / ifta_per_jurisdiction_round_then_sum_net_tax
# ===========================================================================

def _setup_ifta_three_jurisdictions(api):
    """HEAVY_DUTY vehicle, active lease, fuel card; CA/NV/AZ telematics
    (12000/8000/5000 mi) and CA/NV/AZ fuel (1500/2200/300 gal) in 2026Q1;
    IftaReturn 2026Q1 DRAFT. Returns the IftaReturn id."""
    lessee, vehicle, lease = setup_active_lease(
        vehicle_class="HEAVY_DUTY", lease_overrides={"contracted_miles": 100000}
    )
    card = get_success_data(
        api.create_fuel_card({"lease_id": lease["id"], "card_number": "CARD-IFTA-1"}, FM)
    )
    for juris, odo, seg, when in [
        ("CA", 12000, 12000, "2026-01-10T00:00:00Z"),
        ("NV", 20000, 8000, "2026-02-10T00:00:00Z"),
        ("AZ", 25000, 5000, "2026-03-10T00:00:00Z"),
    ]:
        get_success_data(api.create_telematics_reading(
            create_telematics_reading_payload(
                vehicle["id"], jurisdiction=juris, odometer_miles=odo,
                segment_miles=seg, recorded_at=when,
            ), TG))
    for juris, gal, when in [
        ("CA", 1500, "2026-01-11T00:00:00Z"),
        ("NV", 2200, "2026-02-11T00:00:00Z"),
        ("AZ", 300, "2026-03-11T00:00:00Z"),
    ]:
        get_success_data(api.create_fuel_transaction(
            create_fuel_transaction_payload(
                card["id"], jurisdiction=juris, gallons=gal, purchased_at=when,
            ), FM))
    ifta = get_success_data(
        api.create_ifta_return({"lessee_id": lessee["id"], "quarter": "2026Q1"}, CO)
    )
    return ifta["id"]


def test_ifta_fleet_mpg_round_then_sum(api):
    """PRD §3.9: "The `fleet_mpg` is the total qualified miles divided by the
    total qualified gallons, rounded half-up to three decimals."

    25000 miles / 4000 gallons = 6.250.

    Design: Difficulty/combinatorial_formula/ifta_per_jurisdiction_round_then_sum_net_tax
    """
    return_id = _setup_ifta_three_jurisdictions(api)
    data = validate_success(api.file_ifta_return(return_id, CO), 200)
    assert float(data["fleet_mpg"]) == 6.25, data
    assert data["status"] == "FILED", data


def test_ifta_net_tax_due_cents(api):
    """PRD §3.9: "The rounding order is fixed: round each jurisdiction's
    figures first, then sum the per-jurisdiction nets across all
    jurisdictions, and finally convert that dollar sum to an integer number
    of cents (multiply by one hundred and round half-up) to obtain
    `net_tax_due_cents`."

    Per-jurisdiction round-then-sum over CA/NV/AZ gives net_tax_due_cents=4960.

    Design: Difficulty/combinatorial_formula/ifta_per_jurisdiction_round_then_sum_net_tax
    """
    return_id = _setup_ifta_three_jurisdictions(api)
    data = validate_success(api.file_ifta_return(return_id, CO), 200)
    assert data["net_tax_due_cents"] == 4960, data


# ===========================================================================
# combinatorial_formula / collision_waterfall_nested_minmax_branch
# ===========================================================================

def test_waterfall_nested_minmax_deductible_first(api):
    """PRD §3.8: "Under `DEDUCTIBLE_FIRST`, the `driver_deductible_cents` is
    filled first as the lesser of the `estimate_cents` and the lease's
    `collision_deductible_cents`; the remaining estimate after that is the
    `insurance_paid_cents`, taken as the lesser of that remainder and the
    `insurance_cap_cents`; whatever still remains is the overflow."

    est=500000, cap=800000, ded=100000: deductible=100000, insurance=400000,
    lessee_responsible=100000.

    Design: Difficulty/combinatorial_formula/collision_waterfall_nested_minmax_branch
    """
    _, _, _, repair = setup_assessed_repair(
        estimate_cents=500000, insurance_cap_cents=800000,
        waterfall_model="DEDUCTIBLE_FIRST", collision_deductible_cents=100000,
    )
    data = validate_success(api.approve_repair(repair["id"], FM), 200)
    assert data["driver_deductible_cents"] == 100000, data
    assert data["insurance_paid_cents"] == 400000, data
    assert data["lessee_responsible_cents"] == 100000, data


def test_waterfall_lessee_responsible_is_deductible_plus_overflow(api):
    """PRD §3.8: "In both orderings the `lessee_responsible_cents` is the sum
    of the `driver_deductible_cents` and the overflow."

    est=500000, cap=800000, ded=100000 under DEDUCTIBLE_FIRST: deductible
    100000 + overflow 0 = lessee_responsible 100000.

    Design: Difficulty/combinatorial_formula/collision_waterfall_nested_minmax_branch
    """
    _, _, _, repair = setup_assessed_repair(
        estimate_cents=500000, insurance_cap_cents=800000,
        waterfall_model="DEDUCTIBLE_FIRST", collision_deductible_cents=100000,
    )
    data = validate_success(api.approve_repair(repair["id"], FM), 200)
    assert data["lessee_responsible_cents"] == (
        data["driver_deductible_cents"] + 0
    ), data
    assert data["lessee_responsible_cents"] == 100000, data


# ===========================================================================
# boundary_precision_check / excess_wear_score_strict_greater_than_threshold
# ===========================================================================

def test_excess_wear_score_and_charge_above_threshold(api):
    """PRD §3.7: "The `excess_wear_charge_cents` is a flat fifty thousand cents
    when the `excess_wear_score` is strictly greater than thirty, and zero
    otherwise."

    1000 harsh events over 85000 miles → score 58.82 (> 30) → charge 50000.

    Design: Difficulty/boundary_precision_check/excess_wear_score_strict_greater_than_threshold
    """
    _, _, lease, settlement = setup_settlement_open(
        driven_odometer=85000, overage_model="TIERED_EXCESS",
        contracted_miles=60000, per_mile_overage_cents=25,
        harsh_events=1000, idle_minutes=0,
    )
    data = validate_success(api.finalize_settlement(settlement["id"], FM), 200)
    assert float(data["excess_wear_score"]) == 58.82, data
    assert data["excess_wear_charge_cents"] == 50000, data


def test_excess_wear_net_charge_sums_mileage_and_wear(api):
    """PRD §3.7: "Finally, `net_charge_cents` is the sum of
    `mileage_charge_cents` and `excess_wear_charge_cents`."

    TIERED excess 25000 → mileage 725000; wear charge 50000; net 775000.

    Design: Difficulty/boundary_precision_check/excess_wear_score_strict_greater_than_threshold
    """
    _, _, lease, settlement = setup_settlement_open(
        driven_odometer=85000, overage_model="TIERED_EXCESS",
        contracted_miles=60000, per_mile_overage_cents=25,
        harsh_events=1000, idle_minutes=0,
    )
    data = validate_success(api.finalize_settlement(settlement["id"], FM), 200)
    assert data["mileage_charge_cents"] == 725000, data
    assert data["excess_wear_charge_cents"] == 50000, data
    assert data["net_charge_cents"] == 775000, data


# ===========================================================================
# boundary_precision_check / ifta_file_requires_nonzero_qualified_gallons_empty_set
# ===========================================================================

def test_ifta_file_rejected_with_no_qualified_fuel(api):
    """PRD §3.9: "Filing — the `DRAFT` to `FILED` transition, permitted only
    from `DRAFT` — is gated on there being qualifying fuel: the total
    qualified gallons in the quarter must be strictly greater than zero,
    meaning at least one `POSTED` fuel transaction tied to a qualified
    vehicle in that quarter exists; otherwise filing is rejected with
    `ERR_NO_QUALIFIED_FUEL` (HTTP 409)."

    A return for a lessee with zero POSTED fuel transactions in the quarter.

    Design: Difficulty/boundary_precision_check/ifta_file_requires_nonzero_qualified_gallons_empty_set
    """
    _, ifta = setup_ifta_return_open(quarter="2026Q1")
    resp = api.file_ifta_return(ifta["id"], CO)
    validate_error(resp, "ERR_NO_QUALIFIED_FUEL")


def test_ifta_file_succeeds_with_qualified_fuel(api):
    """PRD §3.9: "the total qualified gallons in the quarter must be strictly
    greater than zero, meaning at least one `POSTED` fuel transaction tied to
    a qualified vehicle in that quarter exists; otherwise filing is rejected
    with `ERR_NO_QUALIFIED_FUEL` (HTTP 409)."

    The positive arm: with qualified fuel present, filing reaches FILED.

    Design: Difficulty/boundary_precision_check/ifta_file_requires_nonzero_qualified_gallons_empty_set
    """
    return_id = _setup_ifta_three_jurisdictions(api)
    data = validate_success(api.file_ifta_return(return_id, CO), 200)
    assert data["status"] == "FILED", data
