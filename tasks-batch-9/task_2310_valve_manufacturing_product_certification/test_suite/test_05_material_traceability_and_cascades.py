"""Material traceability: the quarantine recall, the draw gates and the mass balance.

A lot disposition is the longest lever in the system — one quarantine walks the chain
from metal to money. The draw gates behind a component are ordered so that a
referential objection is reported ahead of a mass objection, and the lot's mass balance
distinguishes metal that has been thrown away from metal that was never really drawn.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    BuildStatus,
    CertStatus,
    ComponentStatus,
    DocPackageStatus,
    ErrorId,
    FoundryStatus,
    HeatLotStatus,
    OrderStatus,
    QualificationStatus,
    assert_foundry_band,
    assert_index_band_consistent,
    assert_lot_mass_balance,
    assert_mass,
    assert_unit_dimensions,
    factories,
    fixtures,
    make_procurement_specialist_headers,
)


# ─── The four-hop quarantine recall ───


def _issued_programme_on_one_lot(api):
    """A closed loop from metal to paperwork: one 500.000 kg lot, one body, one certified
    and packaged unit, and its order in production with an issued documentation package."""
    line = fixtures.build_traceable_line(
        api,
        foundry_code="FDY-06",
        foundry_name="Zeta Castings",
        country_code="IN",
        heat_number="H-6001",
        mtr_document_ref="MTR-6001",
        model_code="BV-300-ORD",
        license_code="MON-07",
        scope_valve_types=["BALL"],
    )
    order = fixtures.create_order(
        api,
        line["model"]["id"],
        order_code="ETO-CAS",
        ordered_qty=1,
        unit_price_cents=1_000_000,
        customer_credit_limit_cents=5_000_000,
        datasheet_break_torque_nm=420.0,
        datasheet_torque_source="VENDOR_MEASURED",
    )
    fixtures.approve_order(api, order["id"])
    fixtures.release_order_to_production(api, order["id"])
    unit = fixtures.open_unit(
        api,
        line["model"]["id"],
        line["component"]["id"],
        line["license"]["id"],
        serial_number="SN-ORD-1",
        engineered_order_id=order["id"],
    )
    fixtures.advance_to_assembled(api, unit["id"])
    fixtures.record_pass_run(api, unit["id"], test_types=("SHELL", "SEAT"))
    unit = fixtures.certify_unit(api, unit["id"])
    fixtures.advance_build(api, unit["id"], "PACKAGED")
    fixtures.append_documents(
        api,
        order["id"],
        (
            "MATERIAL_TEST_REPORT",
            "TEST_CERTIFICATE",
            "DIMENSIONAL_REPORT",
            "NDE_REPORT",
            "DECLARATION_OF_CONFORMITY",
        ),
    )
    fixtures.lifecycle_action(api, order["id"], "ISSUE_DOC_PACKAGE")
    return {"line": line, "order": order, "unit": unit}


def test_01_quarantine_holds_the_lot_s_components_and_decertifies_their_units(api):
    """The first two links: the component records where it was and goes on hold, and the
    unit built from it loses its certification and falls back off the packing line.

    PRD §3.2: "First, every component of the lot in `CREATED`, `ISSUED_TO_MACHINING` or
    `CONSUMED` records its current status into `pre_hold_status` and moves to `HOLD`.
    Second — caused by the first — every valve unit whose `body_component_id` is one of
    those held components and whose `cert_status` is `TESTS_PASSED` or `CERTIFIED` moves to
    `DECERTIFIED` with `decertification_reason` set to `LOT_QUARANTINE`, and any such unit
    sitting at `build_status` `PACKAGED` falls back to `REWORK`."

    Design: Difficulty/transitive_cascade/heat_lot_quarantine_cascades_four_hops_to_order_hold
    """
    scenario = _issued_programme_on_one_lot(api)

    fixtures.dispose_lot(
        api,
        scenario["line"]["lot"]["id"],
        "QUARANTINE",
        quarantine_reason="MTR retest showed low impact energy",
    )

    lot = fixtures.read_lot(api, scenario["line"]["lot"]["id"])
    component = fixtures.read_component(api, scenario["line"]["component"]["id"])
    unit = fixtures.read_unit(api, scenario["unit"]["id"])

    assert lot["status"] == HeatLotStatus.QUARANTINED
    assert component["status"] == ComponentStatus.HOLD
    assert component["pre_hold_status"] == ComponentStatus.CONSUMED
    assert_unit_dimensions(unit, build_status=BuildStatus.REWORK, cert_status=CertStatus.DECERTIFIED)
    assert unit["decertification_reason"] == "LOT_QUARANTINE"
    assert unit["certified_by_user_id"] is None


def test_02_the_recall_reaches_the_paperwork_and_then_the_programme_itself(api):
    """The third and fourth links: the issued package is voided and the order it belongs
    to comes off production, its held reason carrying the last cause to be written.

    PRD §3.2: "Third — caused by the second — for each decertified unit that names an
    `engineered_order_id`, that order's documentation package, if it is `ISSUED`, moves to
    `VOIDED` with `held_reason` set to `DOC_PACKAGE_VOIDED`. Fourth — caused by the second
    and third — that same order, if its `status` is `IN_PRODUCTION`, moves to `HELD`, and
    if its `status` is `CLOSED`, reopens to `IN_PRODUCTION`, with `held_reason` set to
    `UNIT_DECERTIFIED`."

    Design: Difficulty/transitive_cascade/heat_lot_quarantine_cascades_four_hops_to_order_hold
    """
    scenario = _issued_programme_on_one_lot(api)
    before = fixtures.read_order(api, scenario["order"]["id"])
    assert before["doc_package_status"] == DocPackageStatus.ISSUED
    assert before["status"] == OrderStatus.IN_PRODUCTION

    fixtures.dispose_lot(
        api,
        scenario["line"]["lot"]["id"],
        "QUARANTINE",
        quarantine_reason="MTR retest showed low impact energy",
    )

    order = fixtures.read_order(api, scenario["order"]["id"])

    assert order["doc_package_status"] == DocPackageStatus.VOIDED
    assert order["status"] == OrderStatus.HELD
    assert order["held_reason"] == "UNIT_DECERTIFIED", (
        "The fourth link writes the held reason after the third one"
    )
    assert order["certified_unit_count"] == 0


def test_03_the_quarantine_rebands_the_foundry_while_the_metal_stays_committed(api):
    """A single rejected lot out of a single lot is a total rejection rate, dropping the
    works to probation; the held component's mass is still counted as committed.

    PRD §3.2: "the foundry's `rejected_lot_count` increases by 1 and its index and band
    are recomputed." PRD §3.1: "The index is then 100 reduced by 40 times that rate,
    reduced further by 8 for each revoked qualification, rounded half up to 2 decimal
    places and finally clamped into the range 0.00 to 100.00 after the rounding." PRD §3.2:
    "`qty_committed_kg` is the total `net_weight_kg` of components in `CREATED`,
    `ISSUED_TO_MACHINING`, `CONSUMED` or `HOLD`."

    Design: Difficulty/transitive_cascade/heat_lot_quarantine_cascades_four_hops_to_order_hold
    """
    scenario = _issued_programme_on_one_lot(api)

    fixtures.dispose_lot(
        api,
        scenario["line"]["lot"]["id"],
        "QUARANTINE",
        quarantine_reason="MTR retest showed low impact energy",
    )

    foundry = fixtures.read_foundry(api, scenario["line"]["foundry"]["id"])
    lot = fixtures.read_lot(api, scenario["line"]["lot"]["id"])

    assert foundry["total_lot_count"] == 1
    assert foundry["rejected_lot_count"] == 1
    assert_foundry_band(foundry, 60.00, FoundryStatus.PROBATION)
    assert_index_band_consistent(foundry)
    assert_mass(lot["qty_committed_kg"], 120.500, "qty_committed_kg")
    assert_mass(lot["qty_available_kg"], 379.500, "qty_available_kg")
    assert_lot_mass_balance(lot)


# ─── Two draw gates violated at once ───


def _over_committed_unreleased_lot(api):
    """A verified-but-not-released lot of 500.000 kg and a design to draw against, so a
    600.000 kg draw would breach both the release gate and the mass gate."""
    works = fixtures.create_qualified_foundry(
        api, foundry_code="FDY-09", name="Iota Castings", country_code="IN"
    )
    model = fixtures.create_model(
        api,
        model_code="BV-300-MASS",
        valve_type="BALL",
        pressure_class=300,
        body_material_grade="CF8M",
        bore_size_mm=100,
        seat_type="METAL",
        base_break_torque_nm=420.0,
    )
    lot = fixtures.create_heat_lot(
        api,
        works["foundry"]["id"],
        heat_number="H-9001",
        mtr_document_ref="MTR-9001",
        qty_received_kg=500.000,
    )
    lot = fixtures.dispose_lot(api, lot["id"], "VERIFY")
    return {"works": works, "model": model, "lot": lot}


def _draw(api, lot_id, model_id, net_weight_kg):
    return api.create_component(
        factories.component_payload(lot_id, model_id, "BODY", net_weight_kg),
        make_procurement_specialist_headers(),
    )


def test_04_the_referential_gate_is_reported_ahead_of_the_mass_gate(api):
    """One draw breaches both gates at once, and the lot-status objection is the one the
    caller is told about.

    PRD §2.10: "A component drawn from an over-committed lot that is still merely
    `VERIFIED` must report the referential error `ERR_HEAT_LOT_NOT_RELEASED` (HTTP 409)
    from band 13, not the mass error `ERR_LOT_INSUFFICIENT_MASS` (HTTP 422) from band 17."

    Design: Difficulty/priority_pair_validation_conflict/component_referential_error_outranks_lot_mass_error
    """
    scenario = _over_committed_unreleased_lot(api)

    response = _draw(api, scenario["lot"]["id"], scenario["model"]["id"], 600.000)

    error_id = validate_error(response, ErrorId.HEAT_LOT_NOT_RELEASED, 409)["error_id"]
    assert error_id != ErrorId.LOT_INSUFFICIENT_MASS

    lot = fixtures.read_lot(api, scenario["lot"]["id"])
    assert_mass(lot["qty_committed_kg"], 0.000, "qty_committed_kg")
    assert_mass(lot["qty_available_kg"], 500.000, "qty_available_kg")


def test_05_the_mass_gate_surfaces_once_the_lot_is_released(api):
    """Releasing the lot removes the referential objection, and the same over-sized draw
    now meets the mass objection the referential one had been masking.

    PRD §3.2: "the requested `net_weight_kg` may not exceed the lot's `qty_available_kg`,
    otherwise `ERR_LOT_INSUFFICIENT_MASS`." PRD §3.2: "Releasing moves `VERIFIED →
    RELEASED`, which is the only status in which a lot may serve as a component's
    traceability parent."

    Design: Difficulty/priority_pair_validation_conflict/component_referential_error_outranks_lot_mass_error
    """
    scenario = _over_committed_unreleased_lot(api)
    released = fixtures.dispose_lot(api, scenario["lot"]["id"], "RELEASE")
    assert released["status"] == HeatLotStatus.RELEASED

    response = _draw(api, scenario["lot"]["id"], scenario["model"]["id"], 600.000)

    validate_error(response, ErrorId.LOT_INSUFFICIENT_MASS, 422)
    lot = fixtures.read_lot(api, scenario["lot"]["id"])
    assert_mass(lot["qty_committed_kg"], 0.000, "qty_committed_kg")
    assert_mass(lot["qty_available_kg"], 500.000, "qty_available_kg")


# ─── Scrapping versus voiding: two dispositions, two mass outcomes ───


def _lot_with_a_scrapped_bonnet(api):
    """A released 500.000 kg lot carrying a 120.500 kg body and a 60.250 kg bonnet, the
    bonnet already scrapped."""
    works = fixtures.create_qualified_foundry(
        api, foundry_code="FDY-16", name="Pi Castings", country_code="IN"
    )
    model = fixtures.create_model(
        api,
        model_code="BV-300-MASSBAL",
        valve_type="BALL",
        pressure_class=300,
        body_material_grade="CF8M",
        bore_size_mm=100,
        seat_type="METAL",
        base_break_torque_nm=420.0,
    )
    lot = fixtures.create_released_lot(
        api,
        works["foundry"]["id"],
        heat_number="H-1601",
        mtr_document_ref="MTR-1601",
        qty_received_kg=500.000,
    )
    body = fixtures.draw_component(api, lot["id"], model["id"], "BODY", 120.500)
    bonnet = fixtures.draw_component(api, lot["id"], model["id"], "BONNET", 60.250)
    fixtures.dispose_component(api, bonnet["id"], "SCRAP")
    return {"works": works, "model": model, "lot": lot, "body": body, "bonnet": bonnet}


def test_06_scrapping_moves_the_mass_across_without_returning_it(api):
    """The scrapped bonnet leaves the committed total for the scrapped total, and the
    available figure does not move.

    PRD §3.2: "Scrapping is permitted from `CREATED`, `ISSUED_TO_MACHINING` or `HOLD` and
    moves the mass from `qty_committed_kg` into `qty_scrapped_kg`, leaving
    `qty_available_kg` untouched — scrapped metal is gone, not returned."

    Design: Difficulty/compensating_invariant/component_void_returns_lot_mass_while_scrap_retains_it
    """
    scenario = _lot_with_a_scrapped_bonnet(api)

    lot = fixtures.read_lot(api, scenario["lot"]["id"])
    bonnet = fixtures.read_component(api, scenario["bonnet"]["id"])

    assert bonnet["status"] == ComponentStatus.SCRAPPED
    assert_mass(lot["qty_committed_kg"], 120.500, "qty_committed_kg")
    assert_mass(lot["qty_scrapped_kg"], 60.250, "qty_scrapped_kg")
    assert_mass(lot["qty_available_kg"], 319.250, "qty_available_kg")
    assert_lot_mass_balance(lot)


def test_07_voiding_returns_the_mass_while_the_scrapped_mass_stays_gone(api):
    """The two dispositions are deliberately asymmetric: the voided draw's mass comes back
    into what is available, the scrapped draw's mass never does.

    PRD §3.2: "Voiding is the compensating disposition for a mis-issued draw: it is
    permitted from `CREATED` or `ISSUED_TO_MACHINING`, requires that no valve unit
    references the component as its `body_component_id` (otherwise
    `ERR_COMPONENT_NOT_AVAILABLE`), removes the mass from `qty_committed_kg` and returns it
    to `qty_available_kg`." PRD §3.2: "Components in `VOIDED` contribute to neither total,
    which is exactly how their mass finds its way back into what is available."

    Design: Difficulty/compensating_invariant/component_void_returns_lot_mass_while_scrap_retains_it
    """
    scenario = _lot_with_a_scrapped_bonnet(api)

    fixtures.dispose_component(api, scenario["body"]["id"], "VOID")

    lot = fixtures.read_lot(api, scenario["lot"]["id"])
    body = fixtures.read_component(api, scenario["body"]["id"])
    bonnet = fixtures.read_component(api, scenario["bonnet"]["id"])

    assert body["status"] == ComponentStatus.VOIDED
    assert bonnet["status"] == ComponentStatus.SCRAPPED
    assert_mass(lot["qty_received_kg"], 500.000, "qty_received_kg")
    assert_mass(lot["qty_committed_kg"], 0.000, "qty_committed_kg")
    assert_mass(lot["qty_scrapped_kg"], 60.250, "qty_scrapped_kg")
    assert_mass(lot["qty_available_kg"], 439.750, "qty_available_kg")
    assert_lot_mass_balance(lot)


# ─── The qualification's pressure-class ceiling ───


def _works_qualified_only_to_class_300(api):
    """A works qualified for CF8M castings up to class 300, holding a released lot, with a
    class-600 design and a class-300 design to draw against."""
    works = fixtures.create_qualified_foundry(
        api,
        foundry_code="FDY-13",
        name="Nu Castings",
        country_code="IN",
        process="CASTING",
        material_grade="CF8M",
        max_pressure_class=300,
    )
    over_ceiling = fixtures.create_model(
        api,
        model_code="BV-600-CEIL",
        valve_type="BALL",
        pressure_class=600,
        body_material_grade="CF8M",
        bore_size_mm=100,
        seat_type="METAL",
        base_break_torque_nm=900.0,
    )
    at_ceiling = fixtures.create_model(
        api,
        model_code="BV-300-CEIL",
        valve_type="BALL",
        pressure_class=300,
        body_material_grade="CF8M",
        bore_size_mm=100,
        seat_type="METAL",
        base_break_torque_nm=420.0,
    )
    lot = fixtures.create_released_lot(
        api,
        works["foundry"]["id"],
        heat_number="H-1301",
        mtr_document_ref="MTR-1301",
        qty_received_kg=500.000,
    )
    return {"works": works, "over_ceiling": over_ceiling, "at_ceiling": at_ceiling, "lot": lot}


def test_08_a_draw_for_a_design_above_the_qualified_ceiling_is_refused(api):
    """Nothing is wrong with the lot or the qualification in themselves; the objection is
    that the design being cut for is a pressure class the works is not qualified to.

    PRD §3.2: "there must exist a qualification for the lot's foundry with `status`
    `QUALIFIED`, a matching `process` and `material_grade`, a `max_pressure_class` at or
    above the target design's `pressure_class`, and the current logical clock inside its
    closed window, otherwise `ERR_FOUNDRY_NOT_QUALIFIED`".

    Design: Difficulty/cross_entity_state_dependency/component_creation_blocked_by_qualification_pressure_class_ceiling
    """
    scenario = _works_qualified_only_to_class_300(api)

    response = _draw(api, scenario["lot"]["id"], scenario["over_ceiling"]["id"], 120.500)

    validate_error(response, ErrorId.FOUNDRY_NOT_QUALIFIED, 409)
    lot = fixtures.read_lot(api, scenario["lot"]["id"])
    qualification = fixtures.read_qualification(api, scenario["works"]["qualification"]["id"])
    assert qualification["status"] == QualificationStatus.QUALIFIED
    assert_mass(lot["qty_committed_kg"], 0.000, "qty_committed_kg")
    assert_mass(lot["qty_available_kg"], 500.000, "qty_available_kg")


def test_09_a_design_exactly_at_the_ceiling_draws_from_the_same_lot(api):
    """The ceiling is inclusive, so the identical draw succeeds for a class-300 design
    from the same lot under the same qualification.

    PRD §3.2: "there must exist a qualification for the lot's foundry with `status`
    `QUALIFIED`, a matching `process` and `material_grade`, a `max_pressure_class` at or
    above the target design's `pressure_class`, and the current logical clock inside its
    closed window, otherwise `ERR_FOUNDRY_NOT_QUALIFIED`". PRD §3.2: "A new component opens
    at `status` `CREATED`, raising the lot's `qty_committed_kg` by its mass and lowering
    `qty_available_kg` accordingly."

    Design: Difficulty/cross_entity_state_dependency/component_creation_blocked_by_qualification_pressure_class_ceiling
    """
    scenario = _works_qualified_only_to_class_300(api)

    component = fixtures.draw_component(
        api, scenario["lot"]["id"], scenario["at_ceiling"]["id"], "BODY", 120.500
    )

    assert component["status"] == ComponentStatus.CREATED
    lot = fixtures.read_lot(api, scenario["lot"]["id"])
    assert_mass(lot["qty_committed_kg"], 120.500, "qty_committed_kg")
    assert_mass(lot["qty_available_kg"], 379.500, "qty_available_kg")
    assert_lot_mass_balance(lot)


# ─── The empty rejection rate ───


def test_10_a_works_with_no_lots_at_all_reads_a_perfect_index(api):
    """An empty history is a clean history: the rate is zero rather than undefined, so the
    index sits at the top of the scale and the works is active.

    PRD §3.1: "A freshly registered foundry starts with `total_lot_count` 0,
    `rejected_lot_count` 0, `revoked_qualification_count` 0, a `quality_index` of 100.00
    and a `status` of `ACTIVE`." PRD §3.1: "the rate is zero when the foundry has no lots at
    all — an empty history is a clean history, not a division by zero and not a zero score
    — and is otherwise the rejected count divided by the total count."

    Design: Difficulty/boundary_precision_check/foundry_quality_index_empty_lot_set_reads_one_hundred
    """
    foundry = fixtures.create_foundry(api, "FDY-10", "Kappa Castings", "IN")

    read_back = fixtures.read_foundry(api, foundry["id"])

    assert read_back["total_lot_count"] == 0
    assert read_back["rejected_lot_count"] == 0
    assert read_back["revoked_qualification_count"] == 0
    assert_foundry_band(read_back, 100.00, FoundryStatus.ACTIVE)
    assert_index_band_consistent(read_back)


def test_11_a_clean_non_empty_history_reads_the_same_perfect_index(api):
    """Adding a lot that has not been rejected raises the total count and leaves the index
    alone, because the rate is the rejected count over the total count.

    PRD §3.1: "`total_lot_count` is the number of heat lots naming this foundry, in any
    status. `rejected_lot_count` is the number of those lots whose status is `QUARANTINED`
    or `REJECTED`." PRD §3.1: "The index is then 100 reduced by 40 times that rate, reduced
    further by 8 for each revoked qualification, rounded half up to 2 decimal places and
    finally clamped into the range 0.00 to 100.00 after the rounding."

    Design: Difficulty/boundary_precision_check/foundry_quality_index_empty_lot_set_reads_one_hundred
    """
    foundry = fixtures.create_foundry(api, "FDY-10", "Kappa Castings", "IN")
    fixtures.create_heat_lot(
        api, foundry["id"], heat_number="H-1001", mtr_document_ref="MTR-1001"
    )

    read_back = fixtures.read_foundry(api, foundry["id"])

    assert read_back["total_lot_count"] == 1
    assert read_back["rejected_lot_count"] == 0
    assert_foundry_band(read_back, 100.00, FoundryStatus.ACTIVE)
    assert_index_band_consistent(read_back)
