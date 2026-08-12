"""Composite setup helpers (PRD §3 workflows).

Every helper builds preconditions from scratch using only PRD-declared
endpoints: the harness restarts the server (empty database) before each test.
Setup calls use get_success_data() so a setup failure surfaces as a clear
"Setup failed" assertion, not a confusing downstream error.
"""
import pytest

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_carrier_payload,
    create_security_plan_payload,
    create_material_payload,
    create_packaging_spec_payload,
    create_driver_payload,
    create_training_record_payload,
    create_vehicle_payload,
    create_shipment_payload,
    create_shipping_paper_payload,
    create_load_payload,
    create_route_payload,
    create_incident_report_payload,
)
from .test_users import TEST_USERS, make_officer_headers

ADMIN = TEST_USERS["carrier_admin_headers"]
OFFICER_A = TEST_USERS["officer_a_headers"]
OFFICER_B = TEST_USERS["officer_b_headers"]
REGULATOR = TEST_USERS["regulator_headers"]


def _ok(resp, step: str):
    data = get_success_data(resp)
    assert isinstance(data, dict), f"Setup failed at {step}: {resp.status_code} {resp.text}"
    return data


def _ok_list(resp, step: str):
    data = get_success_data(resp)
    assert isinstance(data, list), f"Setup failed at {step}: {resp.status_code} {resp.text}"
    return data


# ---------------------------------------------------------------------------
# Tier 1: carrier registration lifecycle
# ---------------------------------------------------------------------------

def create_carrier(**overrides):
    """Create a DRAFT carrier. Returns the carrier dict."""
    return _ok(api_client.create_carrier(create_carrier_payload(**overrides), ADMIN), "create_carrier")


def submit_registration(carrier):
    """Submit the carrier's registration with the current version. Returns invoice."""
    resp = api_client.submit_registration(
        carrier["id"], {"expected_carrier_version": carrier["version"]}, ADMIN
    )
    return _ok(resp, "submit_registration")


def approve_registration(carrier, verified_fleet_size=None):
    """Approve a SUBMITTED registration. Returns the updated carrier."""
    payload = {"verified_fleet_size": verified_fleet_size if verified_fleet_size is not None else carrier["fleet_size_declared"]}
    resp = api_client.approve_registration(carrier["id"], payload, REGULATOR)
    return _ok(resp, "approve_registration")


def pay_outstanding(carrier_id):
    """Pay exactly the carrier's current outstanding balance. Returns updated carrier."""
    carrier = _ok(api_client.get_carrier(carrier_id, REGULATOR), "get_carrier(pay_outstanding)")
    due = carrier["outstanding_balance_cents"]
    if due > 0:
        carrier = _ok(
            api_client.pay_carrier(carrier_id, {"amount_cents": due}, ADMIN),
            "pay_outstanding",
        )
    assert carrier["outstanding_balance_cents"] == 0, f"Setup failed: balance {carrier['outstanding_balance_cents']} after full payment"
    return carrier


def create_approved_carrier_paid(pay=True, **carrier_overrides):
    """Carrier walked DRAFT -> SUBMITTED -> APPROVED_ACTIVE, fees fully paid.

    Returns the carrier dict (freshly re-read after payment when pay=True).
    """
    carrier = create_carrier(**carrier_overrides)
    submit_registration(carrier)
    approved = approve_registration(carrier)
    if pay:
        approved = pay_outstanding(approved["id"])
    return approved


def list_invoices(carrier_id):
    return _ok_list(api_client.list_carrier_invoices(carrier_id, REGULATOR), "list_invoices")


# ---------------------------------------------------------------------------
# Tier 1: catalog
# ---------------------------------------------------------------------------

def create_material(**overrides):
    return _ok(api_client.create_material(create_material_payload(**overrides), REGULATOR), "create_material")


def create_packaging_spec(**overrides):
    return _ok(api_client.create_packaging_spec(create_packaging_spec_payload(**overrides), REGULATOR), "create_packaging_spec")


def create_route(**overrides):
    return _ok(api_client.create_route(create_route_payload(**overrides), REGULATOR), "create_route")


def create_standard_catalog(hazard_class="CLASS_3", packing_group="PG_II",
                            placard_table="TABLE_2", transport_category="FLAMMABLE_LIQUID",
                            max_packing_group="PG_II", max_net_quantity_kg=500.0,
                            authorized_hazard_classes=None, **material_overrides):
    """A flammable-liquid TABLE_2 material plus a compatible spec. Returns (material, spec)."""
    material = create_material(
        hazard_class=hazard_class,
        packing_group=packing_group,
        placard_table=placard_table,
        transport_category=transport_category,
        **material_overrides,
    )
    spec = create_packaging_spec(
        authorized_hazard_classes=authorized_hazard_classes or [hazard_class],
        max_packing_group=max_packing_group,
        max_net_quantity_kg=max_net_quantity_kg,
    )
    return material, spec


# ---------------------------------------------------------------------------
# Tier 2: drivers, vehicles, security plans
# ---------------------------------------------------------------------------

def create_qualified_driver(carrier_id, endorsement_expires_at="2027-01-01T00:00:00Z",
                            training_completed_at="2026-04-01T00:00:00Z", **overrides):
    """Driver with a fresh INITIAL training record -> posture QUALIFIED (PRD §3.5)."""
    driver = _ok(
        api_client.create_driver(
            carrier_id,
            create_driver_payload(hazmat_endorsement_expires_at=endorsement_expires_at, **overrides),
            ADMIN,
        ),
        "create_driver",
    )
    _ok(
        api_client.create_training_record(
            driver["id"],
            create_training_record_payload(completed_at=training_completed_at),
            ADMIN,
        ),
        "create_training_record",
    )
    return _ok(api_client.get_driver(driver["id"], REGULATOR), "get_driver")


def create_vehicle(carrier_id, **overrides):
    return _ok(api_client.create_vehicle(carrier_id, create_vehicle_payload(**overrides), ADMIN), "create_vehicle")


def create_approved_security_plan(carrier_id, coverage_categories=None, **overrides):
    """Plan walked DRAFT -> SUBMITTED -> APPROVED. Returns the approved plan."""
    payload = create_security_plan_payload(**overrides)
    if coverage_categories is not None:
        payload["coverage_categories"] = coverage_categories
    plan = _ok(api_client.create_security_plan(carrier_id, payload, ADMIN), "create_security_plan")
    _ok(api_client.submit_security_plan(plan["id"], ADMIN), "submit_security_plan")
    return _ok(api_client.approve_security_plan(plan["id"], REGULATOR), "approve_security_plan")


# ---------------------------------------------------------------------------
# Tier 3: shipment pipeline lifecycle shortcuts
# ---------------------------------------------------------------------------

def create_shipment(carrier_id, material_id, spec_id, headers=None, **overrides):
    return _ok(
        api_client.create_shipment(
            carrier_id,
            create_shipment_payload(material_id, spec_id, **overrides),
            headers or OFFICER_A,
        ),
        "create_shipment",
    )


def classify_shipment(shipment_id, headers=None):
    return _ok(api_client.classify_shipment(shipment_id, headers or OFFICER_A), "classify_shipment")


def create_and_certify_paper(shipment_id, create_headers=None, certify_headers=None):
    """Create the shipment's paper and certify it with a DIFFERENT officer (SoD).

    Defaults: officer-a creates/classifies, officer-b certifies (PRD §3.4).
    """
    paper = _ok(
        api_client.create_shipping_paper(
            shipment_id, create_shipping_paper_payload(), create_headers or OFFICER_A
        ),
        "create_shipping_paper",
    )
    return _ok(
        api_client.certify_shipping_paper(paper["id"], certify_headers or OFFICER_B),
        "certify_shipping_paper",
    )


def create_classified_shipment(carrier_id, material_id, spec_id, headers=None, **overrides):
    shipment = create_shipment(carrier_id, material_id, spec_id, headers=headers, **overrides)
    return classify_shipment(shipment["id"], headers=headers)


def create_verified_shipment(carrier_id, material_id, spec_id, headers=None, **overrides):
    shipment = create_classified_shipment(carrier_id, material_id, spec_id, headers=headers, **overrides)
    return _ok(api_client.verify_packaging(shipment["id"], headers or OFFICER_A), "verify_packaging")


def create_documented_shipment(carrier_id, material_id, spec_id, headers=None,
                               certify_headers=None, **overrides):
    """Shipment walked DRAFT -> CLASSIFIED -> paper CERTIFIED -> PACKAGING_VERIFIED
    -> DOCUMENTED. Classifier (default officer-a) and certifier (default officer-b)
    differ per the segregation-of-duties rule (PRD §3.4)."""
    shipment = create_classified_shipment(carrier_id, material_id, spec_id, headers=headers, **overrides)
    create_and_certify_paper(shipment["id"], create_headers=headers, certify_headers=certify_headers)
    _ok(api_client.verify_packaging(shipment["id"], headers or OFFICER_A), "verify_packaging")
    return _ok(api_client.document_shipment(shipment["id"], headers or OFFICER_A), "document_shipment")


def create_tendered_shipment(carrier_id, material_id, spec_id, driver_id, headers=None, **overrides):
    """DOCUMENTED shipment tendered with the given driver. Returns the TENDERED shipment."""
    shipment = create_documented_shipment(carrier_id, material_id, spec_id, headers=headers, **overrides)
    return _ok(
        api_client.tender_shipment(shipment["id"], {"driver_id": driver_id}, headers or OFFICER_A),
        "tender_shipment",
    )


# ---------------------------------------------------------------------------
# Tier 3: loads
# ---------------------------------------------------------------------------

def create_load(vehicle_id, route_id, headers=None, **overrides):
    return _ok(
        api_client.create_load(vehicle_id, create_load_payload(route_id, **overrides), headers or OFFICER_A),
        "create_load",
    )


def add_item(load_id, shipment_id, position_code="A1", headers=None):
    return _ok(
        api_client.add_load_item(load_id, {"shipment_id": shipment_id, "position_code": position_code}, headers or OFFICER_A),
        "add_load_item",
    )


def create_sealed_load_with_tendered_shipment(carrier, material, spec, driver, vehicle, route,
                                              headers=None, **shipment_overrides):
    """Full chain: DOCUMENTED shipment on a STAGING load, tendered, then SEALED.

    Returns (shipment, load)."""
    headers = headers or OFFICER_A
    shipment = create_documented_shipment(carrier["id"], material["id"], spec["id"],
                                          headers=headers, **shipment_overrides)
    load = create_load(vehicle["id"], route["id"], headers=headers)
    add_item(load["id"], shipment["id"], headers=headers)
    shipment = _ok(api_client.tender_shipment(shipment["id"], {"driver_id": driver["id"]}, headers), "tender_shipment")
    load = _ok(api_client.seal_load(load["id"], headers), "seal_load")
    return shipment, load


# ---------------------------------------------------------------------------
# Tier 4: incidents
# ---------------------------------------------------------------------------

def create_incident(shipment_id, occurred_at="2026-05-02T00:00:00Z", severity="MINOR", headers=None):
    return _ok(
        api_client.create_incident_report(
            shipment_id,
            create_incident_report_payload(occurred_at=occurred_at, severity=severity),
            headers or OFFICER_A,
        ),
        "create_incident_report",
    )


def set_clock(to_iso8601):
    return _ok(api_client.set_clock({"to_iso8601": to_iso8601}, REGULATOR), "set_clock")


# ---------------------------------------------------------------------------
# Tier 5: full scenario bundles
# ---------------------------------------------------------------------------

def setup_active_carrier_with_catalog(hazard_class="CLASS_3", transport_category="FLAMMABLE_LIQUID",
                                      carrier_categories=None, **kwargs):
    """APPROVED_ACTIVE carrier (fees paid) + standard material/spec catalog.

    Returns (carrier, material, spec).
    """
    carrier = create_approved_carrier_paid(
        hazmat_categories=carrier_categories or [transport_category]
    )
    material, spec = create_standard_catalog(
        hazard_class=hazard_class, transport_category=transport_category, **kwargs
    )
    return carrier, material, spec


def setup_documented_scenario(**kwargs):
    """Active paid carrier + catalog + one DOCUMENTED shipment.

    Returns (carrier, material, spec, shipment).
    """
    carrier, material, spec = setup_active_carrier_with_catalog(**kwargs)
    shipment = create_documented_shipment(carrier["id"], material["id"], spec["id"])
    return carrier, material, spec, shipment


def setup_dispatchable_scenario(route_overrides=None, **catalog_kwargs):
    """Active paid carrier + catalog + qualified driver + vehicle + route +
    one TENDERED shipment on a SEALED load.

    Returns dict with keys: carrier, material, spec, driver, vehicle, route,
    shipment, load.
    """
    carrier, material, spec = setup_active_carrier_with_catalog(**catalog_kwargs)
    driver = create_qualified_driver(carrier["id"])
    vehicle = create_vehicle(carrier["id"])
    route = create_route(**(route_overrides or {}))
    shipment, load = create_sealed_load_with_tendered_shipment(
        carrier, material, spec, driver, vehicle, route
    )
    return {
        "carrier": carrier,
        "material": material,
        "spec": spec,
        "driver": driver,
        "vehicle": vehicle,
        "route": route,
        "shipment": shipment,
        "load": load,
    }
