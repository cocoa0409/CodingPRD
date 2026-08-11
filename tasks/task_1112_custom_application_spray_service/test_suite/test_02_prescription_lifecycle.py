"""Prescription approval: OCC on the field version, supersede, label gates."""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_customer, create_field, create_product, create_product_p2,
    create_prescription, approve_prescription,
    create_prescription_payload, create_compatibility_rule,
    create_applicator, create_equipment,
    api_client, TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
AGRONOMIST = TEST_USERS["agronomist_headers"]


def _field_version(field_id):
    return get_success_data(api_client.get_field(field_id, ADMIN))["version"]


def test_approve_with_stale_field_version_rejected_then_supersedes(api):
    """PRD §2.7: "If `expected_field_version` does not equal the Field's
    current `version` — for example because another approval for the same field
    and season has just superseded the previously approved prescription and
    advanced the field's version — the approval is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.2: "Any other `APPROVED` prescription for the same field and
    `season_year` is automatically moved to `SUPERSEDED` — there is at most one
    approved prescription per field per season, and `DRAFT` prescriptions are
    never auto-superseded, so only the single approved one is replaced."

    Design: Corner/cross_cutting_complexity_layers/prescription_approve_stale_field_version
    """
    customer = create_customer(name="Solo Farm", billing_email="s@farm.test",
                               rate_per_acre_cents=900, credit_limit_cents=500000)
    field = create_field(customer["id"], label="F")
    product = create_product()
    rx1 = create_prescription(field["id"], [{"product_id": product["id"], "rate_per_acre": 1.5}])
    rx2 = create_prescription(field["id"], [{"product_id": product["id"], "rate_per_acre": 2.0}],
                              carrier_gpa=15)

    stale_version = _field_version(field["id"])
    approved1 = validate_success(api_client.approve_prescription(
        rx1["id"], {"expected_field_version": stale_version}, AGRONOMIST), 200)
    assert approved1["status"] == "APPROVED"

    # Same stale version after RX1's approval advanced the field's version.
    res = api_client.approve_prescription(
        rx2["id"], {"expected_field_version": stale_version}, AGRONOMIST)
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)

    fresh_version = _field_version(field["id"])
    approved2 = validate_success(api_client.approve_prescription(
        rx2["id"], {"expected_field_version": fresh_version}, AGRONOMIST), 200)
    assert approved2["status"] == "APPROVED"

    rx1_after = validate_success(api_client.get_prescription(rx1["id"], ADMIN), 200)
    assert rx1_after["status"] == "SUPERSEDED", \
        "RX1 must be SUPERSEDED once RX2 wins approval for the same field+season"


def test_approve_already_approved_prescription_returns_invalid_state(api):
    """PRD §3.2: "Approval turns a draft into the field's governing document"
    — approval is the DRAFT to APPROVED transition.
    PRD §2.9: "the target resource is in a valid from-state for the
    requested transition, and linked-entity state preconditions hold
    (prescription approved, applicator active, record certified), surfacing
    as `ERR_INVALID_STATE`"

    Design: Corner/state_machines/approve_already_approved_prescription_returns_invalid_state
    """
    customer = create_customer(name="Solo Farm", billing_email="s@farm.test",
                               rate_per_acre_cents=900, credit_limit_cents=500000)
    field = create_field(customer["id"], label="F")
    product = create_product()
    rx = create_prescription(field["id"], [{"product_id": product["id"], "rate_per_acre": 1.5}])
    approve_prescription(rx)

    # A fresh field version cannot rescue a bad from-state.
    res = api_client.approve_prescription(
        rx["id"], {"expected_field_version": _field_version(field["id"])}, AGRONOMIST)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_approve_prescription_with_buffer_violation_rejected(api):
    """PRD §3.2: "every line product's `required_buffer_ft` must be no greater
    than the field's `buffer_clearance_ft` (else `ERR_BUFFER_VIOLATION`)"

    Design: Corner/validations/approve_prescription_with_buffer_violation_rejected
    """
    customer = create_customer(name="Solo Farm", billing_email="s@farm.test",
                               rate_per_acre_cents=900, credit_limit_cents=500000)
    field = create_field(customer["id"], label="Tight Field", buffer_clearance_ft=100)
    hog = create_product(name="BufferHog", epa_registration_no="EPA-900-9",
                         required_buffer_ft=200)
    rx = create_prescription(field["id"], [{"product_id": hog["id"], "rate_per_acre": 1.5}])

    res = api_client.approve_prescription(
        rx["id"], {"expected_field_version": _field_version(field["id"])}, AGRONOMIST)
    validate_error(res, "ERR_BUFFER_VIOLATION", expected_status=409)

    rx_after = validate_success(api_client.get_prescription(rx["id"], ADMIN), 200)
    assert rx_after["status"] == "DRAFT", "rejected approval leaves the prescription DRAFT"


def test_approve_prescription_with_incompatible_mix_rejected(api):
    """PRD §3.2: "no pair of lines may carry a verdict of `INCOMPATIBLE` (else
    `ERR_INCOMPATIBLE_TANK_MIX`)."
    PRD §3.1: "a pair with no rule at all is treated as `COMPATIBLE`."

    Design: Corner/validations/approve_prescription_with_incompatible_mix_rejected
    """
    customer = create_customer(name="Solo Farm", billing_email="s@farm.test",
                               rate_per_acre_cents=900, credit_limit_cents=500000)
    field = create_field(customer["id"], label="North 40")
    p1 = create_product()
    p2 = create_product_p2()
    create_compatibility_rule(p1["id"], p2["id"], "INCOMPATIBLE", note="precipitates")
    rx = create_prescription(field["id"], [
        {"product_id": p1["id"], "rate_per_acre": 1.5},
        {"product_id": p2["id"], "rate_per_acre": 0.4},
    ])

    res = api_client.approve_prescription(
        rx["id"], {"expected_field_version": _field_version(field["id"])}, AGRONOMIST)
    validate_error(res, "ERR_INCOMPATIBLE_TANK_MIX", expected_status=409)

    rx_after = validate_success(api_client.get_prescription(rx["id"], ADMIN), 200)
    assert rx_after["status"] == "DRAFT"
