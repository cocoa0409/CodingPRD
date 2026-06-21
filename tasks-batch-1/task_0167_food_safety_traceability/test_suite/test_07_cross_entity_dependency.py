"""Cross-entity state dependencies: a lot's RECEIVED->RELEASED transition gated on
its COA being ACCEPTED, and lot receipt gated on the supplier being APPROVED.

Queue A — Difficulty/cross_entity_state_dependency.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    create_facility, create_supplier, create_ingredient, receive_lot,
    attach_coa, decide_coa, setup_supplier_suspended,
    create_lot_payload, ApiErrorId,
    TEST_USERS,
)

QM = TEST_USERS["quality_manager_headers"]
CLERK = TEST_USERS["receiving_clerk_headers"]


# ---------------------------------------------------------------------------
# Difficulty/cross_entity_state_dependency/lot_release_requires_coa_accepted
# ---------------------------------------------------------------------------

def test_release_blocked_while_coa_pending():
    """PRD 3.2: "if the supplier requires a certificate and the lot is raw material,
    its `coa_status` is `ACCEPTED`, otherwise `ERR_COA_NOT_ACCEPTED`"

    Design: Difficulty/cross_entity_state_dependency/lot_release_requires_coa_accepted
    """
    facility = create_facility(initial_utc="2026-01-01T00:00:00Z")
    supplier = create_supplier(facility["id"], coa_required=True)
    ingredient = create_ingredient(facility["id"], storage_target_c=4,
                                   storage_tolerance_c=2, shelf_life_days=30,
                                   declared_allergen_codes=["EGG"])
    lot = receive_lot(facility["id"], ingredient["id"], "L", supplier_id=supplier["id"],
                      received_qty=5)
    attach_coa(lot["id"], measured_allergen_codes=["EGG"], pathogen_pass=True,
               declared_shelf_life_days=30)
    # COA still PENDING -> release blocked.
    res = api_client.release_lot(lot["id"], QM)
    validate_error(res, ApiErrorId.ERR_COA_NOT_ACCEPTED.value)


def test_release_succeeds_after_coa_accepted():
    """PRD 3.2: "A successful release sets `status` to `RELEASED` and increments the
    lot's `version`."

    Design: Difficulty/cross_entity_state_dependency/lot_release_requires_coa_accepted
    """
    facility = create_facility(initial_utc="2026-01-01T00:00:00Z")
    supplier = create_supplier(facility["id"], coa_required=True)
    ingredient = create_ingredient(facility["id"], storage_target_c=4,
                                   storage_tolerance_c=2, shelf_life_days=30,
                                   declared_allergen_codes=["EGG"])
    lot = receive_lot(facility["id"], ingredient["id"], "L", supplier_id=supplier["id"],
                      received_qty=5)
    coa = attach_coa(lot["id"], measured_allergen_codes=["EGG"], pathogen_pass=True,
                     declared_shelf_life_days=30)
    decide_coa(coa["id"], "ACCEPT")

    released = validate_success(api_client.release_lot(lot["id"], QM), 200)
    assert released["status"] == "RELEASED"


# ---------------------------------------------------------------------------
# Difficulty/cross_entity_state_dependency/lot_receive_requires_supplier_approved
# ---------------------------------------------------------------------------

def test_receive_blocked_from_suspended_supplier():
    """PRD 2.10: "a new raw-material lot may only be received from a supplier currently
    in `APPROVED` status, and an attempt to receive from a `SUSPENDED` supplier is
    rejected with `ERR_SUPPLIER_NOT_APPROVED`."

    Design: Difficulty/cross_entity_state_dependency/lot_receive_requires_supplier_approved
    """
    facility, supplier_id, ingredient = setup_supplier_suspended()
    # Supplier now SUSPENDED via three rejected COAs; receiving a new lot is blocked.
    payload = create_lot_payload(facility["id"], ingredient["id"], "L4",
                                 received_qty=5, supplier_id=supplier_id)
    res = api_client.create_lot(payload, CLERK)
    validate_error(res, ApiErrorId.ERR_SUPPLIER_NOT_APPROVED.value)


def test_receive_succeeds_from_approved_supplier():
    """PRD 2.10: "a new raw-material lot may only be received from a supplier currently
    in `APPROVED` status, and an attempt to receive from a `SUSPENDED` supplier is
    rejected with `ERR_SUPPLIER_NOT_APPROVED`."

    Design: Difficulty/cross_entity_state_dependency/lot_receive_requires_supplier_approved
    """
    facility = create_facility(initial_utc="2026-01-01T00:00:00Z")
    supplier = create_supplier(facility["id"], coa_required=True)   # APPROVED at registration
    ingredient = create_ingredient(facility["id"], storage_target_c=20,
                                   storage_tolerance_c=5, shelf_life_days=365,
                                   declared_allergen_codes=["SOY"])
    payload = create_lot_payload(facility["id"], ingredient["id"], "OK1",
                                 received_qty=5, supplier_id=supplier["id"])
    lot = validate_success(api_client.create_lot(payload, CLERK), 201)
    assert lot["status"] == "RECEIVED"
