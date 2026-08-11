"""API contracts: entity defaults, required fields, enums, not-found,
uniqueness, RBAC, validation ordering, pagination, filtered lists, and OCC."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, NON_EXISTENT_UUID,
    ApiErrorId,
    create_carrier, submit_registration, approve_registration,
    create_approved_carrier_paid, create_standard_catalog, create_material,
    create_packaging_spec, create_shipment, create_classified_shipment,
    list_invoices,
)
from test_helpers.fixtures import ADMIN, OFFICER_A, OFFICER_B, REGULATOR, _ok
from test_helpers.factories import (
    create_carrier_payload, create_material_payload, create_shipment_payload,
    create_shipping_paper_payload,
)
from test_helpers.test_users import make_officer_headers


# ===========================================================================
# entities
# ===========================================================================

def test_carrier_create_applies_defaults(api):
    """PRD §3.1: "A new carrier starts in `DRAFT` with `safety_rating` at 100,
    `credit_balance_cents` at 0, and `verified_fleet_size` and
    `registration_expires_at` both null until the first approval."
    PRD §3.1: "When the carrier's `hazmat_categories` intersect `EXPLOSIVE`,
    `RADIOACTIVE`, or `INHALATION_TOXIC` — which is precisely the condition
    recorded on the carrier as `security_plan_required`".

    Design: Corner/entities/carrier_create_applies_defaults
    """
    carrier = validate_success(api.create_carrier(create_carrier_payload(
        legal_name="Acme Hazmat LLC", fleet_size_declared=5,
        hazmat_categories=["FLAMMABLE_LIQUID"],
        accepts_dangerous_placard_substitution=False,
    ), ADMIN), expected_status=201)
    assert carrier["registration_status"] == "DRAFT"
    assert carrier["safety_rating"] == 100
    assert carrier["credit_balance_cents"] == 0
    assert carrier["security_plan_required"] is False
    assert carrier["verified_fleet_size"] is None
    assert carrier["registration_expires_at"] is None


def test_carrier_create_missing_usdot_returns_invalid_request(api):
    """PRD §2.8: "required fields present, types valid, enum members valid, and
    numeric/date ranges valid — `quantity_kg` must be greater than 0,
    `fleet_size_declared` must be at least 0, `declared_value_cents` must be at
    least 0, a plan's or route's `effective_to` must be strictly later than its
    `effective_from`, a load's `planned_arrival_at` must be strictly later than
    its `planned_departure_at`, a payment's `amount_cents` must be greater than
    0, and `shipper_certification_signed` must be a boolean; any violation
    yields `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §3.1: "supplying its `legal_name`, its `usdot_number`, the declared
    power-unit count `fleet_size_declared`".

    Design: Corner/entities/carrier_create_missing_usdot_returns_invalid_request
    """
    payload = create_carrier_payload()
    del payload["usdot_number"]
    resp = api.create_carrier(payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_material_invalid_hazard_class_rejected(api):
    """PRD §2.8: "required fields present, types valid, enum members valid, and
    numeric/date ranges valid" and "any violation yields `ERR_INVALID_REQUEST`
    (HTTP 400)."
    PRD §3.3: "a `hazard_class` drawn from `CLASS_1_1`, `CLASS_1_2`,
    `CLASS_1_3`, `CLASS_2_1`, `CLASS_2_2`, `CLASS_2_3`, `CLASS_3`, `CLASS_4_1`,
    `CLASS_4_2`, `CLASS_4_3`, `CLASS_5_1`, `CLASS_5_2`, `CLASS_6_1`,
    `CLASS_6_2`, `CLASS_7`, `CLASS_8`, and `CLASS_9`".

    Design: Corner/entities/material_invalid_hazard_class_rejected
    """
    resp = api.create_material(create_material_payload(hazard_class="CLASS_10"), REGULATOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_material_requires_security_plan_computed(api):
    """PRD §3.3: "A material is computed to `requires_security_plan` when any of
    three conditions holds: its `placard_table` is `TABLE_1`, or
    `is_inhalation_hazard` is true, or its `hazard_class` is `CLASS_7`."

    Design: Corner/entities/material_requires_security_plan_computed
    """
    plain = validate_success(api.create_material(create_material_payload(
        placard_table="TABLE_2", is_inhalation_hazard=False, hazard_class="CLASS_3",
    ), REGULATOR), expected_status=201)
    assert plain["requires_security_plan"] is False

    table1 = validate_success(api.create_material(create_material_payload(
        placard_table="TABLE_1", hazard_class="CLASS_1_1", packing_group="PG_NONE",
        transport_category="EXPLOSIVE", proper_shipping_name="FIREWORKS",
    ), REGULATOR), expected_status=201)
    assert table1["requires_security_plan"] is True


def test_get_carrier_not_found_returns_404(api):
    """PRD §2.8: "a missing resource yields its specific not-found error
    (`ERR_CARRIER_NOT_FOUND`, `ERR_SECURITY_PLAN_NOT_FOUND`,
    `ERR_DRIVER_NOT_FOUND`, `ERR_VEHICLE_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`,
    `ERR_SHIPPING_PAPER_NOT_FOUND`, `ERR_LOAD_NOT_FOUND`,
    `ERR_INCIDENT_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, each HTTP 404)".

    Design: Corner/entities/get_carrier_not_found_returns_404
    """
    resp = api.get_carrier(NON_EXISTENT_UUID, REGULATOR)
    validate_error(resp, ApiErrorId.ERR_CARRIER_NOT_FOUND)


def test_duplicate_usdot_rejected(api):
    """PRD §2.9: "Five identifiers are globally unique and a duplicate create is
    rejected: `usdot_number` with `ERR_DUPLICATE_USDOT`".

    Design: Corner/entities/duplicate_usdot_rejected
    """
    payload = create_carrier_payload()
    _ok(api.create_carrier(payload, ADMIN), "carrier1")
    resp = api.create_carrier({**payload, "legal_name": "Copycat Carriers"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_USDOT)


def test_shipment_create_bogus_material_returns_invalid_reference(api):
    """PRD §2.8: "After shape validation, body foreign-key references are
    resolved (`material_id`, `packaging_spec_id`, `driver_id`, `vehicle_id`,
    `route_id`, `shipment_id`); a reference to a nonexistent resource yields
    `ERR_INVALID_REFERENCE` (HTTP 422)."

    Design: Corner/entities/shipment_create_bogus_material_returns_invalid_reference
    """
    carrier = create_approved_carrier_paid(hazmat_categories=["FLAMMABLE_LIQUID"])
    resp = api.create_shipment(carrier["id"], create_shipment_payload(
        NON_EXISTENT_UUID, NON_EXISTENT_UUID,
        declared_shipping_name="X", quantity_kg=1.0, declared_value_cents=1,
    ), OFFICER_A)
    validate_error(resp, ApiErrorId.ERR_INVALID_REFERENCE)


# ===========================================================================
# validations: auth, ordering, SoD
# ===========================================================================

def test_missing_auth_header_returns_400(api):
    """PRD §2.1: "A request missing either header, or presenting a role outside
    the declared set, is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/validations/missing_auth_header_returns_400
    """
    headers = {"X-User-ID": "anon", "Content-Type": "application/json"}  # no role
    resp = api.list_carriers(headers)
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


def test_carrier_admin_cannot_approve_registration(api):
    """PRD §2.8: "Authentication headers come first (§2.1), then role
    authorization, then path-parameter existence".
    PRD §2.1: "A request whose role is well-formed but not permitted for the
    target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
    (HTTP 403)."

    Design: Corner/validations/carrier_admin_cannot_approve_registration
    """
    # Nonexistent carrier id: authorization (403) must precede existence (404)
    resp = api.approve_registration(NON_EXISTENT_UUID, {"verified_fleet_size": 5}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


def test_path_existence_validated_left_to_right(api):
    """PRD §2.8: "path identifiers are validated left-to-right, so on a nested
    path the outermost resource is checked before the inner one, and a missing
    resource yields its specific not-found error".

    Design: Corner/validations/path_existence_validated_left_to_right
    """
    resp = api.list_drivers(NON_EXISTENT_UUID, REGULATOR)
    validate_error(resp, ApiErrorId.ERR_CARRIER_NOT_FOUND)


def test_sod_violation_on_certify_same_officer(api):
    """PRD §3.4: "Segregation of duties is enforced at this step: if the
    certifying officer's `X-User-ID` equals the shipment's
    `classified_by_user_id`, the request is rejected with `ERR_SOD_VIOLATION`
    (HTTP 403)."
    PRD §3.4: "A certified paper records the certifier as
    `certified_by_user_id`".

    Design: Corner/validations/sod_violation_on_certify_same_officer
    """
    carrier = create_approved_carrier_paid(hazmat_categories=["FLAMMABLE_LIQUID"])
    material, spec = create_standard_catalog()
    officer_a = make_officer_headers("officer-a")
    shipment = create_classified_shipment(carrier["id"], material["id"], spec["id"],
                                          headers=officer_a)
    paper = _ok(api.create_shipping_paper(
        shipment["id"], create_shipping_paper_payload(), officer_a), "paper")

    resp = api.certify_shipping_paper(paper["id"], officer_a)  # same officer as classifier
    validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)

    certified = validate_success(api.certify_shipping_paper(paper["id"], make_officer_headers("officer-b")))
    assert certified["status"] == "CERTIFIED"
    assert certified["certified_by_user_id"] == "officer-b"


# ===========================================================================
# endpoints: pagination and filters
# ===========================================================================

def test_carriers_pagination_envelope(api):
    """PRD §2.3: "The default `limit` is 10, with a minimum accepted value of 1
    and a maximum of 100; `offset` defaults to 0. Every list response's `meta`
    block carries `limit`, `offset`, `total_count`, and `has_more`."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for
    the request that starts with `req_`."

    Design: Corner/endpoints/carriers_pagination_envelope
    """
    for i in range(3):
        _ok(api.create_carrier(create_carrier_payload(), ADMIN), f"carrier{i}")

    page1, meta1 = validate_paginated(api.list_carriers(REGULATOR, params={"limit": 2, "offset": 0}))
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    assert meta1["limit"] == 2
    assert meta1["offset"] == 0

    page2, meta2 = validate_paginated(api.list_carriers(REGULATOR, params={"limit": 2, "offset": 2}))
    assert len(page2) == 1
    assert meta2["has_more"] is False

    # default limit is 10
    _, meta_default = validate_paginated(api.list_carriers(REGULATOR))
    assert meta_default["limit"] == 10

    # every response's meta carries the request id and timestamp
    body = api.list_carriers(REGULATOR).json()
    assert body["meta"]["api_request_id"].startswith("req_")
    assert "api_request_timestamp" in body["meta"]


def test_shipments_filtered_list_by_status(api):
    """PRD §2.3: "the invoice, security-plan, packaging-spec, driver, vehicle,
    shipment, load, and incident lists each filter by `status`" and "shipment
    lists filter by `material_id`, `packaging_spec_id`, and `driver_id`".

    Design: Corner/endpoints/shipments_filtered_list_by_status
    """
    carrier = create_approved_carrier_paid(hazmat_categories=["FLAMMABLE_LIQUID"])
    material, spec = create_standard_catalog()
    sh1 = create_shipment(carrier["id"], material["id"], spec["id"])
    sh2 = create_shipment(carrier["id"], material["id"], spec["id"],
                          quantity_kg=50.0, declared_value_cents=500)
    _ok(api.cancel_shipment(sh2["id"], OFFICER_A), "cancel sh2")

    drafts, meta_d = validate_paginated(api.list_carrier_shipments(
        carrier["id"], REGULATOR, params={"status": "DRAFT"}))
    assert meta_d["total_count"] == 1
    assert drafts[0]["id"] == sh1["id"]

    by_material, meta_m = validate_paginated(api.list_carrier_shipments(
        carrier["id"], REGULATOR, params={"material_id": material["id"]}))
    assert meta_m["total_count"] == 2


# ===========================================================================
# rbac
# ===========================================================================

def test_officer_cannot_create_material(api):
    """PRD §2.1: "`Regulator` — the regulatory authority: material and packaging
    catalog management".
    PRD §2.1: "A request whose role is well-formed but not permitted for the
    target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
    (HTTP 403)."

    Design: Corner/rbac/officer_cannot_create_material
    """
    resp = api.create_material(create_material_payload(), OFFICER_A)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


def test_regulator_cannot_create_carrier(api):
    """PRD §2.1: "`CarrierAdmin` — the carrier-side administrator responsible
    for registration submission, payments, security plans, drivers, and
    vehicles."
    PRD §2.1: "A request whose role is well-formed but not permitted for the
    target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
    (HTTP 403)."

    Design: Corner/rbac/regulator_cannot_create_carrier
    """
    resp = api.create_carrier(create_carrier_payload(), REGULATOR)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


def test_carrier_admin_cannot_close_incident(api):
    """PRD §3.9: "Closing belongs to the `Regulator`".
    PRD §2.8: "Authentication headers come first (§2.1), then role
    authorization, then path-parameter existence".

    Design: Corner/rbac/carrier_admin_cannot_close_incident
    """
    resp = api.close_incident_report(
        NON_EXISTENT_UUID, {"confirmed_severity": "MINOR", "adjustment_percent": 0}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


# ===========================================================================
# cross_cutting_layers: optimistic concurrency
# ===========================================================================

def test_occ_shipment_amend_stale_version(api):
    """PRD §2.6: "Amending a shipment requires the request to carry
    `expected_shipment_version`, the value of the shipment's `version` as last
    observed by the client; if the shipment's current `version` differs —
    because another writer has since amended the same shipment, a legitimate
    superseding edit — the request is rejected with `ERR_STALE_VERSION`
    (HTTP 412)."
    PRD §3.4: "a change to any of the four classification-relevant fields —
    `material_id`, `packaging_spec_id`, `quantity_kg`, or
    `declared_shipping_name` — reverts the shipment to `DRAFT` and clears
    `normalized_shipping_name` and `classified_by_user_id`, and every amendment
    increments the shipment's `version` by 1."

    Design: Corner/cross_cutting_layers/occ_shipment_amend_stale_version
    """
    carrier = create_approved_carrier_paid(hazmat_categories=["FLAMMABLE_LIQUID"])
    material, spec = create_standard_catalog()
    shipment = create_shipment(carrier["id"], material["id"], spec["id"])
    v1 = shipment["version"]

    # stale version rejected
    resp = api.amend_shipment(shipment["id"], {
        "expected_shipment_version": v1 - 1, "declared_value_cents": 2000}, OFFICER_A)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    # current version succeeds; value-only edit keeps DRAFT and bumps version
    amended = validate_success(api.amend_shipment(shipment["id"], {
        "expected_shipment_version": v1, "declared_value_cents": 2000}, OFFICER_A))
    assert amended["version"] == v1 + 1
    assert amended["status"] == "DRAFT"

    # classification-relevant edit in DRAFT stays DRAFT, version still bumps
    amended2 = validate_success(api.amend_shipment(shipment["id"], {
        "expected_shipment_version": amended["version"], "quantity_kg": 150.0}, OFFICER_A))
    assert amended2["status"] == "DRAFT"
    assert amended2["version"] == v1 + 2


def test_occ_carrier_submit_stale_version(api):
    """PRD §2.6: "Submitting a carrier's registration likewise requires
    `expected_carrier_version`; if the carrier's `version` has advanced since
    the client last read it (another writer's submission having superseded the
    draft under the renewal flow), the submission is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."
    PRD §2.8: "OCC version checks follow, then the carrier-active aggregate
    gate, then the target resource's from-state gate".

    Design: Corner/cross_cutting_layers/occ_carrier_submit_stale_version
    """
    carrier = create_carrier(fleet_size_declared=5, hazmat_categories=["MISC"])
    v1 = carrier["version"]

    invoice = validate_success(api.submit_registration(
        carrier["id"], {"expected_carrier_version": v1}, ADMIN), expected_status=201)
    # SMALL fleet 5, MISC => no surcharge: 25000 + flat 2500
    assert invoice["provisional_total_cents"] == 27500

    # second submit with the pre-submit version: OCC (412) fires before the
    # from-state rejection (409 ERR_CARRIER_NOT_SUBMITTABLE)
    resp = api.submit_registration(carrier["id"], {"expected_carrier_version": v1}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


# ===========================================================================
# errors: category gate and 1:1 paper
# ===========================================================================

def test_category_not_authorized_rejected(api):
    """PRD §3.4: "the material's `transport_category` must lie within the
    carrier's `hazmat_categories`, else `ERR_CATEGORY_NOT_AUTHORIZED`
    (HTTP 409)."

    Design: Corner/errors/category_not_authorized_rejected
    """
    carrier = create_approved_carrier_paid(hazmat_categories=["FLAMMABLE_LIQUID"])
    corrosive = create_material(
        un_na_number="UN1789", proper_shipping_name="HYDROCHLORIC ACID",
        hazard_class="CLASS_8", transport_category="CORROSIVE",
        reportable_quantity_lbs=5000, segregation_group="SG_ACID",
        erg_guide_number="157")
    spec = create_packaging_spec(authorized_hazard_classes=["CLASS_8"])
    resp = api.create_shipment(carrier["id"], create_shipment_payload(
        corrosive["id"], spec["id"], declared_shipping_name="HYDROCHLORIC ACID",
        quantity_kg=10.0, declared_value_cents=100), OFFICER_A)
    validate_error(resp, ApiErrorId.ERR_CATEGORY_NOT_AUTHORIZED)


def test_duplicate_shipping_paper_rejected(api):
    """PRD §2.9: "a shipment has at most one shipping paper — a second create
    yields `ERR_DUPLICATE_SHIPPING_PAPER`".

    Design: Corner/errors/duplicate_shipping_paper_rejected
    """
    carrier = create_approved_carrier_paid(hazmat_categories=["FLAMMABLE_LIQUID"])
    material, spec = create_standard_catalog()
    shipment = create_shipment(carrier["id"], material["id"], spec["id"])
    _ok(api.create_shipping_paper(shipment["id"], create_shipping_paper_payload(), OFFICER_A), "paper1")

    resp = api.create_shipping_paper(shipment["id"], create_shipping_paper_payload(
        emergency_contact_phone="+1-800-555-0101"), OFFICER_A)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_SHIPPING_PAPER)
