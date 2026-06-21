"""Standalone validation and error triggers: tag uniqueness, waste
discriminator agreement, license-type gating, authentication, and RBAC denials."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_cultivation_license, create_testing_license,
    create_batch, create_cured_harvest, create_package, create_customer,
    cult_h, bud_h,
)
from test_helpers import api_client


# ---------------------------------------------------------------------------
# Tag uniqueness
# ---------------------------------------------------------------------------
def test_duplicate_lot_tag_rejected(api):
    """PRD §3.2: "a unique METRC plant-lot `lot_tag` (unique across all plant
    batches and non-empty)"
    PRD §3.2: "A duplicate `lot_tag` is rejected with `ERR_DUPLICATE_TAG`."

    Design: Corner/validations/duplicate_lot_tag_rejected
    """
    cul = create_cultivation_license()
    payload = {
        "license_id": cul["id"], "lot_tag": "LOT-DUP", "strain": "X",
        "plant_count": 10, "planted_at": "2026-01-01T00:00:00Z",
    }
    validate_success(api.create_plant_batch(payload, cult_h()), 201)
    dup = {**payload, "strain": "Y", "plant_count": 5}
    resp = api.create_plant_batch(dup, cult_h())
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_TAG.value)


# ---------------------------------------------------------------------------
# Waste discriminator agreement
# ---------------------------------------------------------------------------
def test_waste_discriminator_mismatch_rejected(api):
    """PRD §3.8: "a `PLANT_BATCH` event must carry `plant_batch_id` with a null
    `package_id`, and a `PACKAGE` event must carry `package_id` with a null
    `plant_batch_id`; a mismatch is rejected with
    `ERR_SOURCE_DISCRIMINATOR_MISMATCH`."

    Design: Corner/validations/waste_event_discriminator_mismatch_rejected
    """
    cul = create_cultivation_license()
    batch = create_batch(cul["id"], plant_count=10)
    # source_type PACKAGE but supplying plant_batch_id (no package_id).
    resp = api.create_waste_event({
        "source_type": "PACKAGE", "plant_batch_id": batch["id"], "reason": "MOLD",
        "destroyed_grams": 5, "destroyed_at": "2026-06-15T00:00:00Z",
    }, cult_h())
    validate_error(resp, ApiErrorId.ERR_SOURCE_DISCRIMINATOR_MISMATCH.value)


# ---------------------------------------------------------------------------
# License-type gating
# ---------------------------------------------------------------------------
def test_open_sale_on_cultivation_license_type_mismatch(api):
    """PRD §2.7: "A mismatch between `license_type` and the attempted operation
    is rejected with `ERR_LICENSE_TYPE_MISMATCH`. This type check applies to
    plant-batch creation, sale creation, lab-result recording, and manifest
    creation."

    Design: Corner/errors/license_type_mismatch_on_open_sale
    """
    cul = create_cultivation_license()
    cust = create_customer(is_medical=False)
    resp = api.create_sale({
        "retail_license_id": cul["id"], "customer_id": cust["id"],
        "sale_date": "2026-06-19T00:00:00Z",
    }, bud_h())
    validate_error(resp, ApiErrorId.ERR_LICENSE_TYPE_MISMATCH.value)


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
def test_missing_auth_headers_rejected(api):
    """PRD §2.1: "A request missing either header on a protected endpoint is
    rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/errors/unauthenticated_missing_headers
    """
    resp = api.create_plant_batch({
        "license_id": "00000000-0000-4000-8000-000000000001", "lot_tag": "LOT-NOAUTH",
        "strain": "X", "plant_count": 10, "planted_at": "2026-01-01T00:00:00Z",
    }, {})  # no X-User-ID / X-User-Role headers
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# ---------------------------------------------------------------------------
# RBAC denials
# ---------------------------------------------------------------------------
def test_budtender_cannot_register_license(api):
    """PRD §2.1: "When the headers are present but the declared role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_UNAUTHORIZED`."
    PRD §2.1: "A `StateRegulator` is the issuing authority. It registers
    licenses and drives the license lifecycle"

    Design: Corner/rbac/budtender_cannot_create_license
    """
    resp = api.create_license({
        "license_number": "LIC-RB1", "license_type": "RETAIL",
        "state_code": "CA", "expires_on": "2027-01-01T00:00:00Z",
    }, bud_h())
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_cultivator_cannot_record_lab_result(api):
    """PRD §2.1: "A `QALabUser` operates a testing license and records potency
    and pesticide laboratory results."
    PRD §2.1: "When the headers are present but the declared role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/cultivator_cannot_record_lab_result
    """
    cul = create_cultivation_license()
    lab = create_testing_license()
    harvest = create_cured_harvest(cul["id"], dry_weight_grams=500)
    pkg = create_package(harvest["id"], quantity_grams=50)
    resp = api.create_lab_result({
        "package_id": pkg["id"], "testing_license_id": lab["id"],
        "thc_pct": 18.0, "pesticide_pass": True, "tested_at": "2026-05-01T00:00:00Z",
    }, cult_h())  # Cultivator, not QALabUser
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)
