"""Tender gate ordering, driver posture boundaries, training-renewal windows,
and route window overlap semantics."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, is_valid_uuid,
    ApiErrorId, assert_same_instant,
    create_approved_carrier_paid, create_standard_catalog, create_material,
    create_packaging_spec, create_documented_shipment, create_qualified_driver,
    create_approved_security_plan, create_shipment, set_clock, create_incident,
)
from test_helpers.fixtures import ADMIN, OFFICER_A, OFFICER_B, REGULATOR, _ok
from test_helpers.factories import create_route_payload, create_training_record_payload


# ---------------------------------------------------------------------------
# priority_pair_validation_conflict / business_safety_vs_business_fiscal_tender
# ---------------------------------------------------------------------------

def _setup_reinstated_carrier_with_plan_requiring_shipment(api):
    """EXPLOSIVE carrier APPROVED_ACTIVE with fees paid, then suspended and
    reinstated (REINSTATEMENT invoice OPEN: outstanding 75000); qualified
    driver; DOCUMENTED TABLE_1 CLASS_1_1 shipment (requires a security plan).
    NO security plan exists."""
    carrier = create_approved_carrier_paid(hazmat_categories=["EXPLOSIVE"])
    _ok(api.suspend_carrier(carrier["id"], REGULATOR), "suspend")
    _ok(api.reinstate_carrier(carrier["id"], REGULATOR), "reinstate")
    material = create_material(
        un_na_number="UN0335", proper_shipping_name="FIREWORKS",
        hazard_class="CLASS_1_1", packing_group="PG_NONE", placard_table="TABLE_1",
        transport_category="EXPLOSIVE", reportable_quantity_lbs=1,
        erg_guide_number="112")
    spec = create_packaging_spec(authorized_hazard_classes=["CLASS_1_1"])
    driver = create_qualified_driver(carrier["id"])
    shipment = create_documented_shipment(carrier["id"], material["id"], spec["id"],
                                          declared_shipping_name="FIREWORKS",
                                          quantity_kg=10.0)
    return carrier, material, spec, driver, shipment


def test_security_plan_gate_beats_fiscal_gate_at_tender(api):
    """PRD §3.6: "When the material `requires_security_plan`, a security plan
    must be selectable (below), else `ERR_SECURITY_PLAN_REQUIRED`."
    PRD §3.6: "The fiscal gate comes last among these checks: the carrier's
    `outstanding_balance_cents` must be exactly 0, else `ERR_OUTSTANDING_FEES`
    (HTTP 402)."

    Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_fiscal_tender
    """
    carrier, material, spec, driver, shipment = _setup_reinstated_carrier_with_plan_requiring_shipment(api)
    # Both gates violated: no plan AND outstanding 75000 — safety must win
    resp = api.tender_shipment(shipment["id"], {"driver_id": driver["id"]}, OFFICER_A)
    validate_error(resp, ApiErrorId.ERR_SECURITY_PLAN_REQUIRED)


def test_fiscal_gate_fires_once_plan_exists_and_tender_pins_plan(api):
    """PRD §3.6: "The fiscal gate comes last among these checks: the carrier's
    `outstanding_balance_cents` must be exactly 0, else `ERR_OUTSTANDING_FEES`
    (HTTP 402)."
    PRD §3.6: "A successful tender stores `driver_id` and pins the selected
    plan's identity and current `version` onto the shipment as
    `pinned_security_plan_id` and `pinned_security_plan_version`".

    Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_fiscal_tender
    """
    carrier, material, spec, driver, shipment = _setup_reinstated_carrier_with_plan_requiring_shipment(api)
    plan = create_approved_security_plan(carrier["id"], coverage_categories=["EXPLOSIVE"])

    resp = api.tender_shipment(shipment["id"], {"driver_id": driver["id"]}, OFFICER_A)
    validate_error(resp, ApiErrorId.ERR_OUTSTANDING_FEES)

    _ok(api.pay_carrier(carrier["id"], {"amount_cents": 75000}, ADMIN), "pay reinstatement")
    tendered = validate_success(api.tender_shipment(shipment["id"], {"driver_id": driver["id"]}, OFFICER_A))
    assert tendered["status"] == "TENDERED"
    assert tendered["pinned_security_plan_id"] == plan["id"]
    assert tendered["pinned_security_plan_version"] == plan["version"]


# ---------------------------------------------------------------------------
# boundary_precision_check / endorsement_expiry_strict_boundary
# ---------------------------------------------------------------------------

def _setup_driver_at_endorsement_edge(api):
    """Driver with endorsement expiring 2026-05-01T12:00:00Z and training valid
    to 2029-04-01; two DOCUMENTED shipments ready to tender."""
    carrier = create_approved_carrier_paid(hazmat_categories=["FLAMMABLE_LIQUID"])
    material, spec = create_standard_catalog()
    driver = create_qualified_driver(
        carrier["id"], endorsement_expires_at="2026-05-01T12:00:00Z",
        training_completed_at="2026-04-01T00:00:00Z")
    sh1 = create_documented_shipment(carrier["id"], material["id"], spec["id"])
    sh2 = create_documented_shipment(carrier["id"], material["id"], spec["id"])
    return carrier, driver, sh1, sh2


def test_tender_at_exact_endorsement_expiry_instant_succeeds(api):
    """PRD §3.5: "when the clock is strictly later than
    `hazmat_endorsement_expires_at` the posture is `ENDORSEMENT_EXPIRED` — at
    the exact expiry instant the endorsement is still valid".

    Design: Difficulty/boundary_precision_check/endorsement_expiry_strict_boundary
    """
    carrier, driver, sh1, _ = _setup_driver_at_endorsement_edge(api)
    set_clock("2026-05-01T12:00:00Z")
    tendered = validate_success(api.tender_shipment(sh1["id"], {"driver_id": driver["id"]}, OFFICER_A))
    assert tendered["status"] == "TENDERED", "exactly at the expiry instant the endorsement is still valid"


def test_tender_one_second_after_endorsement_expiry_fails(api):
    """PRD §3.5: "when the clock is strictly later than
    `hazmat_endorsement_expires_at` the posture is `ENDORSEMENT_EXPIRED`".
    PRD §3.6: "that driver's `qualification_posture` must be `QUALIFIED` at this
    instant, else `ERR_DRIVER_NOT_QUALIFIED` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/endorsement_expiry_strict_boundary
    """
    carrier, driver, _, sh2 = _setup_driver_at_endorsement_edge(api)
    set_clock("2026-05-01T12:00:01Z")
    resp = api.tender_shipment(sh2["id"], {"driver_id": driver["id"]}, OFFICER_A)
    validate_error(resp, ApiErrorId.ERR_DRIVER_NOT_QUALIFIED)
    fresh = validate_success(api.get_driver(driver["id"], REGULATOR))
    assert fresh["qualification_posture"] == "ENDORSEMENT_EXPIRED"


# ---------------------------------------------------------------------------
# resource_temporal_overlap / route_window_closed_adjacency_conflicts
# ---------------------------------------------------------------------------

def test_route_windows_touching_closed_endpoints_conflict(api):
    """PRD §3.8: "Windows for the same `route_code` must not overlap, and here
    too closed-interval semantics mean touching endpoints conflict, yielding
    `ERR_ROUTE_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/route_window_closed_adjacency_conflicts
    """
    _ok(api.create_route(create_route_payload(
        route_code="R-TOUCH", effective_from="2026-01-01T00:00:00Z",
        effective_to="2026-06-30T00:00:00Z"), REGULATOR), "route1")
    resp = api.create_route(create_route_payload(
        route_code="R-TOUCH", effective_from="2026-06-30T00:00:00Z",
        effective_to="2026-12-31T00:00:00Z"), REGULATOR)
    validate_error(resp, ApiErrorId.ERR_ROUTE_WINDOW_CONFLICT)


def test_route_windows_with_gap_or_different_code_accepted(api):
    """PRD §3.8: "Windows for the same `route_code` must not overlap, and here
    too closed-interval semantics mean touching endpoints conflict, yielding
    `ERR_ROUTE_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/route_window_closed_adjacency_conflicts
    """
    _ok(api.create_route(create_route_payload(
        route_code="R-GAP", effective_from="2026-01-01T00:00:00Z",
        effective_to="2026-06-30T00:00:00Z"), REGULATOR), "route1")
    # one-day gap: starts strictly after the existing window ends
    gapped = validate_success(api.create_route(create_route_payload(
        route_code="R-GAP", effective_from="2026-07-01T00:00:00Z",
        effective_to="2026-12-31T00:00:00Z"), REGULATOR), expected_status=201)
    assert is_valid_uuid(gapped["id"])
    # overlapping window under a DIFFERENT code never conflicts
    other = validate_success(api.create_route(create_route_payload(
        route_code="R-OTHER", effective_from="2026-03-01T00:00:00Z",
        effective_to="2026-05-01T00:00:00Z"), REGULATOR), expected_status=201)
    assert is_valid_uuid(other["id"])


# ---------------------------------------------------------------------------
# Corner/calculations/training_expiry_anchored_at_window_edge
# ---------------------------------------------------------------------------

def test_training_expiry_anchored_at_window_edge(api):
    """PRD §3.5: "When such a prior record exists and the new completion falls
    inside the early-renewal window — the closed interval from ninety days
    before the prior record's `expires_at` through the prior `expires_at`
    itself, both bounds inclusive — the new `expires_at` anchors to the prior
    one: prior `expires_at` plus three years. A completion exactly ninety days
    before the prior expiry anchors; a completion exactly at the prior expiry
    anchors; one second after the prior expiry does not. In every other case the
    new `expires_at` is simply the new `completed_at` plus three years."

    Design: Corner/calculations/training_expiry_anchored_at_window_edge
    """
    carrier = create_approved_carrier_paid(hazmat_categories=["FLAMMABLE_LIQUID"])
    driver = create_qualified_driver(carrier["id"], training_completed_at="2023-08-01T00:00:00Z")
    records, _ = validate_paginated(api.list_training_records(driver["id"], REGULATOR))
    # no prior record: completed + 3 years
    assert_same_instant(records[0]["expires_at"], "2026-08-01T00:00:00Z")

    # completed exactly at prev.expires_at - 90 days (2026-05-03): anchored
    anchored = validate_success(api.create_training_record(
        driver["id"],
        create_training_record_payload(training_type="RECURRENT",
                                       completed_at="2026-05-03T00:00:00Z"),
        ADMIN), expected_status=201)
    assert_same_instant(anchored["expires_at"], "2029-08-01T00:00:00Z")

    # one day BEFORE the window opens: not anchored -> completed + 3 years.
    # The prior record for this completion is the INITIAL one (the 2026-05-03
    # record is not strictly before 2026-05-02), so the window is unchanged.
    plain = validate_success(api.create_training_record(
        driver["id"],
        create_training_record_payload(training_type="RECURRENT",
                                       completed_at="2026-05-02T00:00:00Z"),
        ADMIN), expected_status=201)
    assert_same_instant(plain["expires_at"], "2029-05-02T00:00:00Z")
