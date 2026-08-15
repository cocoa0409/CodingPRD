"""Transitive cascades and cross-entity state dependencies."""
from test_helpers import (
    ApiErrorId,
    CHEM,
    EHS,
    MGR,
    OP,
    add_line_item,
    complete_load_run,
    create_compat_rule,
    create_customer,
    create_fixture,
    create_manifest,
    create_permit,
    create_titrated_bath,
    dose_bath,
    get_bath,
    get_bath_version,
    get_manifest,
    get_permit,
    get_success_data,
    get_work_order,
    inspect_work_order,
    make_customer_headers,
    make_ehs_officer_headers,
    prepare_work_order,
    record_sample,
    route_work_order,
    setup_awaiting_inspection,
    setup_routed_order,
    start_load_run,
    titrate_bath,
    validate_error,
)
from test_helpers.api_client import api_client
from test_helpers.factories import (
    create_discharge_permit_payload,
    create_waste_sample_payload,
    create_work_order_payload,
)


def _setup_nickel_exceedance_scenario():
    """NICKEL bath with a ROUTED order + a NICKEL permit ready to receive a sample."""
    customer = create_customer(company_name="Eta Stampings")
    create_compat_rule(alloy_code="CRS1018", process_type="PLATE",
                       chemistry_family="NICKEL", compatibility="COMPATIBLE")
    bath = create_titrated_bath(
        bath_code="PLT-7", process_type="PLATE", chemistry_family="NICKEL",
        routing_modes_supported=["BARREL"],
        titration_overrides={"titrant_volume_ml": 20.0, "titrant_normality": 0.1,
                             "sample_volume_ml": 11.74},
    )
    wo = setup_routed_order(customer["id"], bath["id"], part_number="PN-700",
                            alloy_code="CRS1018", process_type="PLATE")
    permit = create_permit(outfall_code="OUTFALL-NI", effective_from="2026-08-01",
                           effective_to="2026-08-31",
                           limits=[{"analyte_code": "NICKEL", "max_concentration_mg_l": 2.0,
                                    "monthly_mass_cap_g": 500.0}])
    return customer, bath, wo, permit


def test_discharge_exceedance_cascade_three_hops():
    """PRD §3.8: "Recording an exceedance sample flips the permit from `ACTIVE` to
    `EXCEEDED`, sets `exceedance_active` true, and cascades in the same request: every
    `ACTIVE` bath whose chemistry family maps to an exceeded analyte is quarantined
    with `quarantine_cause` `DISCHARGE_EXCEEDANCE`, and every work order `ROUTED` on
    those baths moves to `ROUTE_HELD`."

    Design: Difficulty/transitive_cascade/discharge_exceedance_cascade
    """
    _customer, bath, wo, permit = _setup_nickel_exceedance_scenario()
    assert get_work_order(wo["id"])["status"] == "ROUTED"
    sample = record_sample(permit["id"], flow_liters=5000,
                           readings=[{"analyte_code": "NICKEL", "concentration_mg_l": 2.5}])
    assert sample["is_exceedance"] is True  # 2.5 > 2.0 strict
    # Hop 1: permit EXCEEDED.
    assert get_permit(permit["id"])["status"] == "EXCEEDED"
    # Hop 2: bath quarantined with DISCHARGE_EXCEEDANCE cause.
    bath_detail = get_bath(bath["id"])
    assert bath_detail["status"] == "QUARANTINED"
    assert bath_detail["quarantine_cause"] == "DISCHARGE_EXCEEDANCE"
    # Hop 3: routed order held.
    assert get_work_order(wo["id"])["status"] == "ROUTE_HELD"


def test_exceedance_quarantine_release_blocked_until_permit_cleared():
    """PRD §3.3: "and, when the `quarantine_cause` is `DISCHARGE_EXCEEDANCE`, no
    discharge permit may currently have `exceedance_active` true with a limit on an
    analyte of this bath's chemistry family (else `ERR_DISCHARGE_EXCEEDANCE_HOLD`,
    evaluated at tier 8 for this operation)."
    PRD §3.3: "Only when the bath actually reaches `ACTIVE` does the cascade run: every
    work order in `ROUTE_HELD` linked to the bath returns to `ROUTED`, the
    `quarantine_cause` clears to null, and the bath's `version` increments."

    Design: Difficulty/transitive_cascade/discharge_exceedance_cascade
    """
    _customer, bath, wo, permit = _setup_nickel_exceedance_scenario()
    record_sample(permit["id"], flow_liters=5000,
                  readings=[{"analyte_code": "NICKEL", "concentration_mg_l": 2.5}])
    # Release while the permit is EXCEEDED is rejected.
    resp = api_client.release_quarantine(bath["id"], EHS)
    validate_error(resp, ApiErrorId.ERR_DISCHARGE_EXCEEDANCE_HOLD)
    # Clear the permit, then release succeeds and the order returns to ROUTED.
    get_success_data(api_client.clear_exceedance(permit["id"], EHS))
    released = get_success_data(api_client.release_quarantine(bath["id"], EHS))
    assert released["status"] == "ACTIVE"
    assert get_work_order(wo["id"])["status"] == "ROUTED"


def _drive_bath_to_used(bath_id, customer_id, count, duration_minutes=300,
                        current_density_a_dm2=1.8, alloy_code="AL2024",
                        part_number_prefix="PN-80"):
    """Run `count` clean PASS loads on the bath. Returns list of order ids."""
    ids = []
    for i in range(count):
        wo = setup_routed_order(
            customer_id, bath_id,
            part_number=f"{part_number_prefix}{i + 1}", alloy_code=alloy_code,
            part_count=10, surface_area_dm2_per_part=1.0,
            planned_duration_minutes=duration_minutes,
            planned_current_density_a_dm2=current_density_a_dm2,
        )
        lr = start_load_run(wo["id"], bath_id=bath_id,
                            duration_minutes=duration_minutes,
                            current_density_a_dm2=current_density_a_dm2)
        complete_load_run(lr["id"])
        inspect_work_order(wo["id"], thickness_readings_um=[13.0, 14.0, 15.0],
                           defect_type="NONE")
        ids.append(wo["id"])
    return ids


def test_load_completion_exhaustion_cascade_at_exact_capacity():
    """PRD §3.5: "If the debit makes the bath's used reach or exceed its capacity, the
    bath becomes `EXHAUSTED` in the same request and every `ROUTED` order on it
    cascades to `ROUTE_HELD`."
    PRD §3.5: "the nameplate ceiling must hold, meaning the bath's used plus reserved
    plus the new estimate is at most `amp_hour_capacity` with equality permitted (else
    `ERR_BATH_CAPACITY_EXCEEDED`)"

    Design: Difficulty/transitive_cascade/load_completion_exhaustion_cascade
    """
    customer = create_customer(company_name="Theta Panels")
    create_compat_rule(alloy_code="AL2024", process_type="ANODIZE",
                       chemistry_family="SULFURIC", compatibility="COMPATIBLE")
    bath = create_titrated_bath(
        bath_code="ANO-8", routing_modes_supported=["BARREL"], amp_hour_capacity=540,
    )
    waiting = setup_routed_order(customer["id"], bath["id"], part_number="PN-800W",
                                 alloy_code="AL2024", part_count=10,
                                 surface_area_dm2_per_part=1.0)
    # 5 loads of 90 Ah each -> used 450.
    _drive_bath_to_used(bath["id"], customer["id"], 5)
    assert get_bath(bath["id"])["amp_hour_used"] == 450.0
    # Mid-sequence maintenance: dose restores 5.000, titration clears verification.
    # After 5 loads: dragout removed 5 x (10 x 0.0008) = 0.04 -> 4.96; dose 32 g -> +0.04.
    v = get_bath_version(bath["id"])
    dose_bath(bath["id"], v, chemical_code="H2SO4", quantity_g=32.0)
    titrate_bath(bath["id"])
    # Driver 6: effective == 90 == estimate 90.0 (boundary route passes);
    # nameplate check 450 + 0 + 90.0 == 540 (inclusive start passes).
    d6 = setup_routed_order(customer["id"], bath["id"], part_number="PN-806",
                            alloy_code="AL2024", part_count=10,
                            surface_area_dm2_per_part=1.0,
                            planned_duration_minutes=300,
                            planned_current_density_a_dm2=1.8)
    assert d6["status"] == "ROUTED"
    lr6 = start_load_run(d6["id"], bath_id=bath["id"],
                         duration_minutes=300, current_density_a_dm2=1.8)
    assert lr6["status"] == "RUNNING"
    completed = complete_load_run(lr6["id"])
    assert completed["status"] == "COMPLETED"
    detail = get_bath(bath["id"])
    assert detail["amp_hour_used"] == 540.0
    assert detail["status"] == "EXHAUSTED"
    assert get_work_order(waiting["id"])["status"] == "ROUTE_HELD"


def test_route_at_effective_boundary_and_start_at_nameplate_boundary():
    """PRD §3.3: "a route is accepted only when `effective_remaining_ah` is at least
    the planned load's estimated amp-hours, else `ERR_BATH_LIFE_INSUFFICIENT`."
    PRD §3.5: "the nameplate ceiling must hold, meaning the bath's used plus reserved
    plus the new estimate is at most `amp_hour_capacity` with equality permitted (else
    `ERR_BATH_CAPACITY_EXCEEDED`)"

    Design: Difficulty/transitive_cascade/load_completion_exhaustion_cascade
    """
    customer = create_customer(company_name="Theta Panels Boundary")
    create_compat_rule(alloy_code="AL2024", process_type="ANODIZE",
                       chemistry_family="SULFURIC", compatibility="COMPATIBLE")
    bath = create_titrated_bath(
        bath_code="ANO-8B", routing_modes_supported=["BARREL"], amp_hour_capacity=540,
    )
    _drive_bath_to_used(bath["id"], customer["id"], 5)
    v = get_bath_version(bath["id"])
    dose_bath(bath["id"], v, chemical_code="H2SO4", quantity_g=32.0)
    titrate_bath(bath["id"])
    detail = get_bath(bath["id"])
    # efficiency 1.0 (concentration restored to 5.000 >= target); effective == 90.
    assert detail["effective_remaining_ah"] == 90
    d6 = setup_routed_order(customer["id"], bath["id"], part_number="PN-806B",
                            alloy_code="AL2024", part_count=10,
                            surface_area_dm2_per_part=1.0,
                            planned_duration_minutes=300,
                            planned_current_density_a_dm2=1.8)
    assert d6["status"] == "ROUTED"
    lr6 = start_load_run(d6["id"], bath_id=bath["id"],
                         duration_minutes=300, current_density_a_dm2=1.8)
    assert lr6["estimated_amp_hours"] == 90.0
    assert lr6["status"] == "RUNNING"


def test_load_start_gated_by_bath_quarantine():
    """PRD §3.3: "Either way, every work order in `ROUTED` status linked to the bath is
    cascaded to `ROUTE_HELD` in the same request, and the bath's `version` increments."
    PRD §3.5: "The order must be `ROUTED` (else `ERR_WORK_ORDER_NOT_ROUTED`)"

    Design: Difficulty/cross_entity_state_dependency/load_start_gated_by_bath_state
    """
    customer = create_customer(company_name="Nu Marine")
    create_compat_rule()
    bath = create_titrated_bath(bath_code="ANO-14", routing_modes_supported=["BARREL"])
    wo = setup_routed_order(customer["id"], bath["id"], part_number="PN-1400")
    quarantined = get_success_data(api_client.quarantine_bath(bath["id"], EHS))
    assert quarantined["status"] == "QUARANTINED"
    assert quarantined["quarantine_cause"] == "MANUAL"
    assert get_work_order(wo["id"])["status"] == "ROUTE_HELD"
    # Load start while held is rejected on the work order's own state.
    resp = api_client.start_load_run(
        wo["id"],
        {"duration_minutes": 40, "current_density_a_dm2": 1.5,
         "expected_bath_version": get_bath_version(bath["id"])},
        OP,
    )
    validate_error(resp, ApiErrorId.ERR_WORK_ORDER_NOT_ROUTED)


def test_load_start_succeeds_after_quarantine_release():
    """PRD §3.3: "Only when the bath actually reaches `ACTIVE` does the cascade run:
    every work order in `ROUTE_HELD` linked to the bath returns to `ROUTED`, the
    `quarantine_cause` clears to null, and the bath's `version` increments."
    PRD §3.5: "On success the load run is created `RUNNING` with `bath_id` copied from
    the order's routing"

    Design: Difficulty/cross_entity_state_dependency/load_start_gated_by_bath_state
    """
    customer = create_customer(company_name="Nu Marine 2")
    create_compat_rule()
    bath = create_titrated_bath(bath_code="ANO-14B", routing_modes_supported=["BARREL"])
    wo = setup_routed_order(customer["id"], bath["id"], part_number="PN-1401")
    get_success_data(api_client.quarantine_bath(bath["id"], EHS))
    released = get_success_data(api_client.release_quarantine(bath["id"], EHS))
    assert released["status"] == "ACTIVE"
    assert get_work_order(wo["id"])["status"] == "ROUTED"
    lr = start_load_run(wo["id"], bath_id=bath["id"])
    assert lr["status"] == "RUNNING"


def test_ship_gated_by_customer_credit_hold():
    """PRD §3.7: "Shipping a `COMPLETE` order — a `LineOperator` or `ShopManager`
    action, rejected with `ERR_WORK_ORDER_NOT_COMPLETE` from any other state — runs the
    customer fiscal gates one last time: `credit_hold` true rejects with
    `ERR_CUSTOMER_CREDIT_HOLD` and a non-`ACTIVE` customer with
    `ERR_CUSTOMER_SUSPENDED`."

    Design: Difficulty/cross_entity_state_dependency/ship_gated_by_customer_credit_hold
    """
    customer = create_customer(company_name="Xi Optics")
    create_compat_rule()
    fixture = create_fixture(fixture_code="RACK-15", routing_mode="RACK", capacity_dm2=500,
                             purchase_cost_cents=120000, rated_uses=50)
    bath = create_titrated_bath(bath_code="ANO-15", routing_modes_supported=["RACK"])
    wo, _lr = setup_awaiting_inspection(customer["id"], bath["id"],
                                        fixture_id=fixture["id"], routing_mode="RACK",
                                        part_number="PN-1500")
    inspect_work_order(wo["id"])
    assert get_work_order(wo["id"])["status"] == "COMPLETE"
    # Ship under credit hold is rejected.
    get_success_data(api_client.patch_customer(customer["id"], {"credit_hold": True}, MGR))
    resp = api_client.ship_work_order(wo["id"], OP)
    validate_error(resp, ApiErrorId.ERR_CUSTOMER_CREDIT_HOLD)
    assert get_work_order(wo["id"])["status"] == "COMPLETE"


def test_ship_after_credit_hold_cleared_computes_invoice():
    """PRD §3.7: "Shipment computes `final_invoice_cents`, the final variant of the
    pricing formula, and moves the order to the terminal `SHIPPED` state."

    Design: Difficulty/cross_entity_state_dependency/ship_gated_by_customer_credit_hold
    """
    customer = create_customer(company_name="Xi Optics 2")
    create_compat_rule()
    fixture = create_fixture(fixture_code="RACK-15B", routing_mode="RACK", capacity_dm2=500,
                             purchase_cost_cents=120000, rated_uses=50)
    bath = create_titrated_bath(bath_code="ANO-15B", routing_modes_supported=["RACK"])
    wo, _lr = setup_awaiting_inspection(customer["id"], bath["id"],
                                        fixture_id=fixture["id"], routing_mode="RACK",
                                        part_number="PN-1501")
    inspect_work_order(wo["id"])
    get_success_data(api_client.patch_customer(customer["id"], {"credit_hold": True}, MGR))
    validate_error(api_client.ship_work_order(wo["id"], OP),
                   ApiErrorId.ERR_CUSTOMER_CREDIT_HOLD)
    get_success_data(api_client.patch_customer(customer["id"], {"credit_hold": False}, MGR))
    shipped = get_success_data(api_client.ship_work_order(wo["id"], OP))
    assert shipped["status"] == "SHIPPED"
    # fixture 2400 x 1 run + processing round(25 x 15.0 x 15) = 5625 -> 8025
    assert shipped["final_invoice_cents"] == 8025, (
        f"Final invoice: expected 8025, got {shipped['final_invoice_cents']}"
    )


def test_manifest_finalize_gated_by_permit_exceedance():
    """PRD §3.9: "Finalizing — an `EHSOfficer` or `ShopManager` action — requires the
    manifest to be `DRAFT` (else `ERR_MANIFEST_NOT_DRAFT`), at least one line item (else
    `ERR_MANIFEST_EMPTY`), and no discharge permit anywhere with `exceedance_active`
    true (else `ERR_DISCHARGE_EXCEEDANCE_HOLD`, evaluated at tier 12 for this
    operation)."

    Design: Difficulty/cross_entity_state_dependency/manifest_finalize_gated_by_permit_exceedance
    """
    manifest = create_manifest(creator_user_id="ehs-1", generator_epa_id="EPA-GEN-16")
    add_line_item(manifest["id"], manifest["version"],
                  headers=make_ehs_officer_headers("ehs-1"),
                  waste_code="F006", source_type="SLUDGE_PRESS",
                  description="Filter press cake", volume_liters=100)
    permit = create_permit(outfall_code="OUTFALL-16", effective_from="2026-08-01",
                           effective_to="2026-08-31",
                           limits=[{"analyte_code": "ZINC", "max_concentration_mg_l": 1.0,
                                    "monthly_mass_cap_g": 100.0}])
    sample = record_sample(permit["id"], flow_liters=100,
                           readings=[{"analyte_code": "ZINC", "concentration_mg_l": 5.0}])
    assert sample["is_exceedance"] is True
    assert get_permit(permit["id"])["status"] == "EXCEEDED"
    # Finalize during exceedance is rejected; manifest stays DRAFT.
    resp = api_client.finalize_manifest(manifest["id"], make_ehs_officer_headers("ehs-2"))
    validate_error(resp, ApiErrorId.ERR_DISCHARGE_EXCEEDANCE_HOLD)
    assert get_manifest(manifest["id"])["status"] == "DRAFT"
    # After clear-exceedance, finalize succeeds.
    get_success_data(api_client.clear_exceedance(permit["id"], EHS))
    finalized = get_success_data(
        api_client.finalize_manifest(manifest["id"], make_ehs_officer_headers("ehs-2"))
    )
    assert finalized["status"] == "FINALIZED"
    assert finalized["finalized_by_user_id"] == "ehs-2"


def test_manifest_finalize_succeeds_after_clear_exceedance_records_finalizer():
    """PRD §3.9: "Finalization records `finalized_by_user_id`, locks the line items, and
    moves the manifest to `FINALIZED`."
    PRD §3.8: "An `EHSOfficer` or `ShopManager` clears an exceeded permit after review;
    the permit must be `EXCEEDED`, else `ERR_PERMIT_NOT_EXCEEDED`. Clearing returns the
    permit to `ACTIVE` and sets `exceedance_active` false"

    Design: Difficulty/cross_entity_state_dependency/manifest_finalize_gated_by_permit_exceedance
    """
    manifest = create_manifest(creator_user_id="ehs-1", generator_epa_id="EPA-GEN-16B")
    add_line_item(manifest["id"], manifest["version"],
                  headers=make_ehs_officer_headers("ehs-1"), volume_liters=50,
                  source_type="RINSE_CONCENTRATE", waste_code="D007",
                  description="Rinse concentrate")
    permit = create_permit(outfall_code="OUTFALL-16B", effective_from="2026-08-01",
                           effective_to="2026-08-31",
                           limits=[{"analyte_code": "ZINC", "max_concentration_mg_l": 1.0,
                                    "monthly_mass_cap_g": 100.0}])
    record_sample(permit["id"], flow_liters=100,
                  readings=[{"analyte_code": "ZINC", "concentration_mg_l": 5.0}])
    cleared = get_success_data(api_client.clear_exceedance(permit["id"], EHS))
    assert cleared["status"] == "ACTIVE"
    assert cleared["exceedance_active"] is False
    finalized = get_success_data(
        api_client.finalize_manifest(manifest["id"], make_ehs_officer_headers("ehs-2"))
    )
    assert finalized["status"] == "FINALIZED"
    assert finalized["finalized_by_user_id"] == "ehs-2"
    assert finalized["created_by_user_id"] == "ehs-1"


def test_sulfuric_bath_immune_to_nickel_exceedance():
    """PRD §3.8: "The chemistry-to-analyte map is exact — a `NICKEL` bath answers to
    the `NICKEL` analyte, `ZINC` to `ZINC`, `COPPER` to `COPPER`, `CHROMIC` to
    `CHROME`, and `CYANIDE` to `CYANIDE` — while a `SULFURIC` bath maps to no analyte
    and is never quarantined by an exceedance."

    Design: Corner/state_machines/sulfuric_bath_immune_to_nickel_exceedance
    """
    customer = create_customer(company_name="Map Co")
    create_compat_rule(alloy_code="CRS1018", process_type="PLATE",
                       chemistry_family="NICKEL", compatibility="COMPATIBLE")
    create_compat_rule(alloy_code="AL6061", process_type="ANODIZE",
                       chemistry_family="SULFURIC", compatibility="COMPATIBLE")
    bath_ni = create_titrated_bath(
        bath_code="PLT-NI", process_type="PLATE", chemistry_family="NICKEL",
        routing_modes_supported=["BARREL"],
        titration_overrides={"titrant_volume_ml": 20.0, "titrant_normality": 0.1,
                             "sample_volume_ml": 11.74},
    )
    bath_su = create_titrated_bath(
        bath_code="ANO-SU", process_type="ANODIZE", chemistry_family="SULFURIC",
        routing_modes_supported=["BARREL"],
    )
    wo_ni = setup_routed_order(customer["id"], bath_ni["id"], part_number="PN-NI",
                               alloy_code="CRS1018", process_type="PLATE")
    wo_su = setup_routed_order(customer["id"], bath_su["id"], part_number="PN-SU",
                               alloy_code="AL6061")
    permit = create_permit(outfall_code="OUTFALL-M", effective_from="2026-08-01",
                           effective_to="2026-08-31",
                           limits=[{"analyte_code": "NICKEL", "max_concentration_mg_l": 2.0,
                                    "monthly_mass_cap_g": 500.0}])
    record_sample(permit["id"], flow_liters=1000,
                  readings=[{"analyte_code": "NICKEL", "concentration_mg_l": 3.0}])
    assert get_bath(bath_ni["id"])["status"] == "QUARANTINED"
    assert get_work_order(wo_ni["id"])["status"] == "ROUTE_HELD"
    assert get_bath(bath_su["id"])["status"] == "ACTIVE"
    assert get_work_order(wo_su["id"])["status"] == "ROUTED"
