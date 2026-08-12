"""Vehicle loads: handling fee rounding, placard thresholds, DANGEROUS
substitution, segregation pairs, seal/unseal cycles, and load windows."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, is_valid_uuid,
    ApiErrorId,
    create_approved_carrier_paid, create_standard_catalog, create_material,
    create_packaging_spec, create_documented_shipment, create_vehicle,
    create_route, create_load, add_item, create_shipment,
    create_classified_shipment,
)
from test_helpers.fixtures import ADMIN, OFFICER_A, OFFICER_B, REGULATOR, _ok
from test_helpers.factories import create_load_payload


def _three_item_load(api, value_cents=333, qty=200.0):
    """Carrier paid; three DOCUMENTED shipments on one STAGING load."""
    carrier = create_approved_carrier_paid(hazmat_categories=["FLAMMABLE_LIQUID"])
    material, spec = create_standard_catalog()
    vehicle = create_vehicle(carrier["id"])
    route = create_route()
    load = create_load(vehicle["id"], route["id"])
    shipments = []
    for i in range(3):
        sh = create_documented_shipment(carrier["id"], material["id"], spec["id"],
                                        quantity_kg=qty, declared_value_cents=value_cents)
        add_item(load["id"], sh["id"], position_code=f"A{i+1}")
        shipments.append(sh)
    return carrier, load, shipments


# ---------------------------------------------------------------------------
# combinatorial_formula / load_handling_fee_per_line_rounding
# ---------------------------------------------------------------------------

def test_handling_fee_rounds_each_line_before_summing(api):
    """PRD §2.7: "Every computed monetary component — the security surcharge,
    the late fee, the safety discount, the processing fee, each per-item
    handling line — is rounded half-up to whole cents at the step where it is
    produced, and components are then integer-summed; summing first and rounding
    once at the end is a different, rejected reading."
    PRD §3.7: "for each item, the shipment's `declared_value_cents` multiplied
    by 0.0625 and rounded half-up to whole cents, then summed as integers, plus
    a flat 725 cents per required placard".

    Design: Difficulty/combinatorial_formula/load_handling_fee_per_line_rounding
    """
    carrier, load, _ = _three_item_load(api, value_cents=333, qty=200.0)
    sealed = validate_success(api.seal_load(load["id"], OFFICER_A))
    # per-line round_half_up(333 * 0.0625) = 21, three times => 63;
    # W2 = 600.0 >= 454.0 => one placard (CLASS_3) => +725
    assert sealed["total_table2_weight_kg"] == pytest.approx(600.0)
    assert sealed["required_placards"] == ["CLASS_3"]
    assert sealed["handling_fee_cents"] == 788, (
        f"per-line rounding gives 788 (sum-then-round 787 is rejected); "
        f"got {sealed['handling_fee_cents']}")


def test_handling_fee_counts_one_placard_per_distinct_table2_class(api):
    """PRD §3.7: "when the aggregate Table-2 weight reaches at least 454.0 kg —
    the boundary is inclusive — every distinct `hazard_class` among the Table-2
    items contributes its label; the required set is the union of those two
    groups."
    PRD §3.7: "plus a flat 725 cents per required placard".

    Design: Difficulty/combinatorial_formula/load_handling_fee_per_line_rounding
    """
    carrier, load, _ = _three_item_load(api, value_cents=333, qty=200.0)
    sealed = validate_success(api.seal_load(load["id"], OFFICER_A))
    # three items of the SAME class: exactly one placard label, one 725 fee
    assert len(sealed["required_placards"]) == 1
    assert sealed["handling_fee_cents"] == 63 + 725


# ---------------------------------------------------------------------------
# boundary_precision_check / placard_threshold_454kg_exact
# ---------------------------------------------------------------------------

def test_placard_threshold_just_below_454kg_yields_no_table2_placard(api):
    """PRD §3.7: "when the aggregate Table-2 weight reaches at least 454.0 kg —
    the boundary is inclusive — every distinct `hazard_class` among the Table-2
    items contributes its label".

    Design: Difficulty/boundary_precision_check/placard_threshold_454kg_exact
    """
    carrier = create_approved_carrier_paid(hazmat_categories=["FLAMMABLE_LIQUID"])
    material, spec = create_standard_catalog()
    vehicle = create_vehicle(carrier["id"])
    route = create_route()
    load = create_load(vehicle["id"], route["id"])
    for i, qty in enumerate([227.0, 226.9]):
        sh = create_documented_shipment(carrier["id"], material["id"], spec["id"],
                                        quantity_kg=qty, declared_value_cents=0)
        add_item(load["id"], sh["id"], position_code=f"A{i+1}")
    sealed = validate_success(api.seal_load(load["id"], OFFICER_A))
    assert sealed["total_table2_weight_kg"] == pytest.approx(453.9)
    assert sealed["required_placards"] == [], "453.9 < 454.0: no Table-2 placard"


def test_placard_threshold_exactly_454kg_yields_class_label(api):
    """PRD §3.7: "when the aggregate Table-2 weight reaches at least 454.0 kg —
    the boundary is inclusive — every distinct `hazard_class` among the Table-2
    items contributes its label".

    Design: Difficulty/boundary_precision_check/placard_threshold_454kg_exact
    """
    carrier = create_approved_carrier_paid(hazmat_categories=["FLAMMABLE_LIQUID"])
    material, spec = create_standard_catalog()
    vehicle = create_vehicle(carrier["id"])
    route = create_route()
    load = create_load(vehicle["id"], route["id"])
    for i in range(2):
        sh = create_documented_shipment(carrier["id"], material["id"], spec["id"],
                                        quantity_kg=227.0, declared_value_cents=0)
        add_item(load["id"], sh["id"], position_code=f"A{i+1}")
    sealed = validate_success(api.seal_load(load["id"], OFFICER_A))
    assert sealed["total_table2_weight_kg"] == pytest.approx(454.0)
    assert sealed["required_placards"] == ["CLASS_3"], "454.0 >= 454.0 inclusive"


# ---------------------------------------------------------------------------
# non_linear_state_machine / vehicle_load_unseal_revert
# ---------------------------------------------------------------------------

def test_unseal_clears_placards_and_fee(api):
    """PRD §3.7: "Unsealing a `SEALED` load (otherwise `ERR_LOAD_NOT_SEALED`)
    returns it to `STAGING` with `required_placards` cleared to the empty list
    and `handling_fee_cents` zeroed."

    Design: Difficulty/non_linear_state_machine/vehicle_load_unseal_revert
    """
    carrier = create_approved_carrier_paid(hazmat_categories=["FLAMMABLE_LIQUID"])
    material, spec = create_standard_catalog()
    vehicle = create_vehicle(carrier["id"])
    route = create_route()
    load = create_load(vehicle["id"], route["id"])
    sh = create_documented_shipment(carrier["id"], material["id"], spec["id"],
                                    quantity_kg=200.0, declared_value_cents=333)
    add_item(load["id"], sh["id"])

    sealed = validate_success(api.seal_load(load["id"], OFFICER_A))
    # round_half_up(333*0.0625)=21; 200.0 < 454.0 so no placards
    assert sealed["status"] == "SEALED"
    assert sealed["handling_fee_cents"] == 21
    assert sealed["required_placards"] == []

    unsealed = validate_success(api.unseal_load(load["id"], OFFICER_A))
    assert unsealed["status"] == "STAGING"
    assert unsealed["handling_fee_cents"] == 0
    assert unsealed["required_placards"] == []


def test_second_seal_after_unseal_recomputes_identical_values(api):
    """PRD §3.7: "A successful seal computes and stores three things. The
    `total_table2_weight_kg` is recomputed. The `required_placards` are
    determined as follows" and "the `handling_fee_cents` is computed".
    PRD §3.7: "Unsealing a `SEALED` load (otherwise `ERR_LOAD_NOT_SEALED`)
    returns it to `STAGING` with `required_placards` cleared to the empty list
    and `handling_fee_cents` zeroed."

    Design: Difficulty/non_linear_state_machine/vehicle_load_unseal_revert
    """
    carrier = create_approved_carrier_paid(hazmat_categories=["FLAMMABLE_LIQUID"])
    material, spec = create_standard_catalog()
    vehicle = create_vehicle(carrier["id"])
    route = create_route()
    load = create_load(vehicle["id"], route["id"])
    sh = create_documented_shipment(carrier["id"], material["id"], spec["id"],
                                    quantity_kg=200.0, declared_value_cents=333)
    add_item(load["id"], sh["id"])

    first = validate_success(api.seal_load(load["id"], OFFICER_A))
    _ok(api.unseal_load(load["id"], OFFICER_A), "unseal")
    second = validate_success(api.seal_load(load["id"], OFFICER_A))
    assert second["status"] == "SEALED"
    assert second["handling_fee_cents"] == first["handling_fee_cents"]
    assert second["required_placards"] == first["required_placards"]


# ---------------------------------------------------------------------------
# Corner/calculations/dangerous_placard_substitution
# ---------------------------------------------------------------------------

def test_dangerous_placard_substitution(api):
    """PRD §3.7: "The DANGEROUS substitution then applies when three conditions
    hold together: the carrier's `accepts_dangerous_placard_substitution` is
    true, the Table-2 label set would contain at least two distinct classes, and
    the aggregate Table-2 weight reaches at least 2270.0 kg, again inclusive; in
    that case the required set becomes the Table-1 labels union the single label
    `DANGEROUS`."

    Design: Corner/calculations/dangerous_placard_substitution
    """
    carrier = create_approved_carrier_paid(
        hazmat_categories=["FLAMMABLE_LIQUID", "CORROSIVE"],
        accepts_dangerous_placard_substitution=True)
    flammable = create_material(
        hazard_class="CLASS_3", transport_category="FLAMMABLE_LIQUID",
        proper_shipping_name="FLAMMABLE LIQUID, N.O.S.")
    corrosive = create_material(
        un_na_number="UN1789", proper_shipping_name="HYDROCHLORIC ACID",
        hazard_class="CLASS_8", transport_category="CORROSIVE",
        reportable_quantity_lbs=5000, erg_guide_number="157")
    spec = create_packaging_spec(authorized_hazard_classes=["CLASS_3", "CLASS_8"],
                                 max_net_quantity_kg=1500.0)
    vehicle = create_vehicle(carrier["id"])
    route = create_route(allowed_hazard_classes=["CLASS_3", "CLASS_8"])
    load = create_load(vehicle["id"], route["id"])
    sh1 = create_documented_shipment(carrier["id"], flammable["id"], spec["id"],
                                     declared_shipping_name="FLAMMABLE LIQUID, N.O.S.",
                                     quantity_kg=1200.0, declared_value_cents=0)
    sh2 = create_documented_shipment(carrier["id"], corrosive["id"], spec["id"],
                                     declared_shipping_name="HYDROCHLORIC ACID",
                                     quantity_kg=1200.0, declared_value_cents=0)
    add_item(load["id"], sh1["id"], position_code="A1")
    add_item(load["id"], sh2["id"], position_code="A2")

    sealed = validate_success(api.seal_load(load["id"], OFFICER_A))
    assert sealed["total_table2_weight_kg"] == pytest.approx(2400.0)
    assert sealed["required_placards"] == ["DANGEROUS"]
    assert sealed["handling_fee_cents"] == 725  # 0 per-line values + one placard


# ---------------------------------------------------------------------------
# priority_pair_validation_conflict / state_vs_business_safety_item_add
# ---------------------------------------------------------------------------

def _setup_sealed_flammable_load_with_pending_oxidizer(api):
    """SEALED load holding a CLASS_3 shipment; a second DOCUMENTED CLASS_5_1
    shipment (forbidden pair {CLASS_5_1, CLASS_3}) waiting to be added."""
    carrier = create_approved_carrier_paid(
        hazmat_categories=["FLAMMABLE_LIQUID", "OXIDIZER"])
    flammable = create_material(
        hazard_class="CLASS_3", transport_category="FLAMMABLE_LIQUID",
        proper_shipping_name="FLAMMABLE LIQUID, N.O.S.")
    oxidizer = create_material(
        un_na_number="UN1479", proper_shipping_name="OXIDIZING SOLID, N.O.S.",
        hazard_class="CLASS_5_1", transport_category="OXIDIZER",
        segregation_group="SG_OXIDIZER", erg_guide_number="140")
    spec = create_packaging_spec(authorized_hazard_classes=["CLASS_3", "CLASS_5_1"])
    vehicle = create_vehicle(carrier["id"])
    route = create_route(allowed_hazard_classes=["CLASS_3", "CLASS_5_1"])
    load = create_load(vehicle["id"], route["id"])
    sh1 = create_documented_shipment(carrier["id"], flammable["id"], spec["id"],
                                     declared_shipping_name="FLAMMABLE LIQUID, N.O.S.",
                                     quantity_kg=200.0)
    add_item(load["id"], sh1["id"], position_code="A1")
    _ok(api.seal_load(load["id"], OFFICER_A), "seal")
    sh2 = create_documented_shipment(carrier["id"], oxidizer["id"], spec["id"],
                                     declared_shipping_name="OXIDIZING SOLID, N.O.S.",
                                     quantity_kg=100.0)
    return load, sh2


def test_state_gate_beats_segregation_on_item_add_to_sealed_load(api):
    """PRD §2.8: "OCC version checks follow, then the carrier-active aggregate
    gate, then the target resource's from-state gate, and only then the domain
    safety, temporal, fiscal, and uniqueness rules described in §3."
    PRD §3.6: "Items join a `STAGING` load — any other state yields
    `ERR_LOAD_NOT_STAGING`".

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_item_add
    """
    load, sh2 = _setup_sealed_flammable_load_with_pending_oxidizer(api)
    resp = api.add_load_item(load["id"], {"shipment_id": sh2["id"], "position_code": "A2"}, OFFICER_A)
    validate_error(resp, ApiErrorId.ERR_LOAD_NOT_STAGING)


def test_segregation_fires_once_load_is_staging(api):
    """PRD §3.7: "By hazard class, the forbidden unordered pairs are: any of
    `CLASS_1_1`, `CLASS_1_2`, or `CLASS_1_3` against `CLASS_5_1`; `CLASS_5_1`
    against `CLASS_3`; and `CLASS_2_3` against `CLASS_3`."
    PRD §3.6: "the segregation check runs against the items already aboard
    (§3.7), rejecting with `ERR_SEGREGATION_VIOLATION` on any forbidden
    pairing."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_item_add
    """
    load, sh2 = _setup_sealed_flammable_load_with_pending_oxidizer(api)
    _ok(api.unseal_load(load["id"], OFFICER_A), "unseal")
    resp = api.add_load_item(load["id"], {"shipment_id": sh2["id"], "position_code": "A2"}, OFFICER_A)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_VIOLATION)


# ---------------------------------------------------------------------------
# compensating_invariant / load_item_add_remove_restores_weight
# ---------------------------------------------------------------------------

def _setup_baseline_sealed_load(api):
    """Load with one item X (254.0 kg TABLE_2, value 1000), sealed once for the
    baseline, then unsealed; item Y (200.0 kg, value 500) DOCUMENTED and ready.
    Returns (load, baseline, shipment_y)."""
    carrier = create_approved_carrier_paid(hazmat_categories=["FLAMMABLE_LIQUID"])
    material, spec = create_standard_catalog()
    vehicle = create_vehicle(carrier["id"])
    route = create_route()
    load = create_load(vehicle["id"], route["id"])
    shx = create_documented_shipment(carrier["id"], material["id"], spec["id"],
                                     quantity_kg=254.0, declared_value_cents=1000)
    add_item(load["id"], shx["id"], position_code="A1")
    baseline = validate_success(api.seal_load(load["id"], OFFICER_A))
    _ok(api.unseal_load(load["id"], OFFICER_A), "unseal")
    shy = create_documented_shipment(carrier["id"], material["id"], spec["id"],
                                     quantity_kg=200.0, declared_value_cents=500)
    return load, baseline, shy


def test_item_add_then_remove_restores_consigned_weight(api):
    """PRD §3.6: "Each add recomputes the load's `total_table2_weight_kg`: the
    live sum of `quantity_kg` over the load's current items whose material's
    `placard_table` is `TABLE_2`, expressed to one decimal, with removed items
    leaving the sum immediately."
    PRD §3.6: "Removal likewise recomputes the weight."

    Design: Difficulty/compensating_invariant/load_item_add_remove_restores_weight
    """
    load, baseline, shy = _setup_baseline_sealed_load(api)
    # baseline seal: 254.0 kg, fee round_half_up(1000*0.0625)=63, no placards
    assert baseline["total_table2_weight_kg"] == pytest.approx(254.0)
    assert baseline["handling_fee_cents"] == 63
    assert baseline["required_placards"] == []

    add_item(load["id"], shy["id"], position_code="A2")
    with_y = validate_success(api.get_load(load["id"], REGULATOR))
    assert with_y["total_table2_weight_kg"] == pytest.approx(454.0)

    _ok(api.remove_load_item(load["id"], shy["id"], OFFICER_A), "remove Y")
    after = validate_success(api.get_load(load["id"], REGULATOR))
    assert after["total_table2_weight_kg"] == pytest.approx(254.0), (
        "compensating remove restores the conserved weight exactly")


def test_reseal_after_add_remove_roundtrip_shows_no_drift(api):
    """PRD §3.6: "Removing an item — the compensating action for an add — is
    permitted only while the load is `STAGING` and the shipment is still
    `DOCUMENTED`".
    PRD §3.7: "A successful seal computes and stores three things. The
    `total_table2_weight_kg` is recomputed."

    Design: Difficulty/compensating_invariant/load_item_add_remove_restores_weight
    """
    load, baseline, shy = _setup_baseline_sealed_load(api)
    add_item(load["id"], shy["id"], position_code="A2")
    _ok(api.remove_load_item(load["id"], shy["id"], OFFICER_A), "remove Y")

    resealed = validate_success(api.seal_load(load["id"], OFFICER_A))
    assert resealed["handling_fee_cents"] == baseline["handling_fee_cents"]
    assert resealed["required_placards"] == baseline["required_placards"]
    assert resealed["total_table2_weight_kg"] == pytest.approx(
        baseline["total_table2_weight_kg"])


# ---------------------------------------------------------------------------
# Corner/errors/seal_empty_load_rejected
# ---------------------------------------------------------------------------

def test_seal_empty_load_rejected(api):
    """PRD §3.7: "Sealing a load requires `STAGING` (`ERR_LOAD_NOT_STAGING`), at
    least one item aboard (`ERR_LOAD_EMPTY`)".

    Design: Corner/errors/seal_empty_load_rejected
    """
    carrier = create_approved_carrier_paid(hazmat_categories=["FLAMMABLE_LIQUID"])
    vehicle = create_vehicle(carrier["id"])
    route = create_route()
    load = create_load(vehicle["id"], route["id"])
    resp = api.seal_load(load["id"], OFFICER_A)
    validate_error(resp, ApiErrorId.ERR_LOAD_EMPTY)


# ---------------------------------------------------------------------------
# Corner/errors/shipment_already_loaded_rejected
# ---------------------------------------------------------------------------

def test_shipment_already_loaded_rejected(api):
    """PRD §2.9: "a shipment may appear on at most one non-terminal load at a
    time, enforced as `ERR_SHIPMENT_ALREADY_LOADED`".

    Design: Corner/errors/shipment_already_loaded_rejected
    """
    carrier = create_approved_carrier_paid(hazmat_categories=["FLAMMABLE_LIQUID"])
    material, spec = create_standard_catalog()
    route = create_route()
    v1 = create_vehicle(carrier["id"])
    v2 = create_vehicle(carrier["id"])
    shipment = create_documented_shipment(carrier["id"], material["id"], spec["id"])
    load1 = create_load(v1["id"], route["id"])
    add_item(load1["id"], shipment["id"])
    load2 = create_load(v2["id"], route["id"],
                        planned_departure_at="2026-05-11T08:00:00Z",
                        planned_arrival_at="2026-05-11T12:00:00Z")

    resp = api.add_load_item(load2["id"], {"shipment_id": shipment["id"], "position_code": "B1"}, OFFICER_A)
    validate_error(resp, ApiErrorId.ERR_SHIPMENT_ALREADY_LOADED)


# ---------------------------------------------------------------------------
# Corner/state_machines/vehicle_auto_loading_on_first_load
# ---------------------------------------------------------------------------

def test_vehicle_auto_loading_on_first_load(api):
    """PRD §3.6: "Creating the first non-terminal load on an `AVAILABLE` vehicle
    moves the vehicle to `LOADING`."
    PRD §3.6: "a new vehicle starts `AVAILABLE`".

    Design: Corner/state_machines/vehicle_auto_loading_on_first_load
    """
    carrier = create_approved_carrier_paid(hazmat_categories=["FLAMMABLE_LIQUID"])
    vehicle = create_vehicle(carrier["id"])
    assert vehicle["status"] == "AVAILABLE"
    route = create_route()
    _ok(api.create_load(vehicle["id"], create_load_payload(route["id"]), OFFICER_A), "load")
    fresh = validate_success(api.get_vehicle(vehicle["id"], REGULATOR))
    assert fresh["status"] == "LOADING"


# ---------------------------------------------------------------------------
# resource_temporal_overlap / vehicle_load_half_open_adjacency_allowed
# ---------------------------------------------------------------------------

def test_touching_load_windows_allowed(api):
    """PRD §3.6: "the window must not overlap any other non-terminal load on the
    same vehicle — with half-open semantics, two windows that merely touch at an
    endpoint do not conflict."

    Design: Difficulty/resource_temporal_overlap/vehicle_load_half_open_adjacency_allowed
    """
    carrier = create_approved_carrier_paid(hazmat_categories=["FLAMMABLE_LIQUID"])
    vehicle = create_vehicle(carrier["id"])
    route = create_route()
    _ok(api.create_load(vehicle["id"], create_load_payload(
        route["id"], planned_departure_at="2026-05-10T08:00:00Z",
        planned_arrival_at="2026-05-10T12:00:00Z"), OFFICER_A), "load1")

    touching = validate_success(api.create_load(vehicle["id"], create_load_payload(
        route["id"], planned_departure_at="2026-05-10T12:00:00Z",
        planned_arrival_at="2026-05-10T16:00:00Z"), OFFICER_A), expected_status=201)
    assert is_valid_uuid(touching["id"]), "half-open adjacency is NOT a conflict"


def test_overlapping_load_window_rejected(api):
    """PRD §3.6: "An overlap yields `ERR_LOAD_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/vehicle_load_half_open_adjacency_allowed
    """
    carrier = create_approved_carrier_paid(hazmat_categories=["FLAMMABLE_LIQUID"])
    vehicle = create_vehicle(carrier["id"])
    route = create_route()
    _ok(api.create_load(vehicle["id"], create_load_payload(
        route["id"], planned_departure_at="2026-05-10T08:00:00Z",
        planned_arrival_at="2026-05-10T12:00:00Z"), OFFICER_A), "load1")

    resp = api.create_load(vehicle["id"], create_load_payload(
        route["id"], planned_departure_at="2026-05-10T11:00:00Z",
        planned_arrival_at="2026-05-10T13:00:00Z"), OFFICER_A)
    validate_error(resp, ApiErrorId.ERR_LOAD_WINDOW_CONFLICT)
