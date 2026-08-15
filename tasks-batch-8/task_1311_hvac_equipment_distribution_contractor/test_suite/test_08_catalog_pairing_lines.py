"""Equipment catalog rules: AHRI pairing sanity, order-line shape, orderability."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error,
    make_contractor_headers, TEST_USERS, ApiErrorId, NON_EXISTENT_UUID,
    make_contractor, make_model, make_system_rating,
    create_draft_order, add_line,
)

ADMIN = TEST_USERS["distributor_admin_headers"]


def test_pairing_refrigerant_mismatch_and_furnace_indoor_rejected(api, admin_headers):
    """PRD §3.2: "Registering one requires an `ahri_reference_number` (unique, duplicates rejected with `ERR_DUPLICATE`), an `outdoor_unit_id` referencing a model whose type is `CONDENSER` or `HEAT_PUMP`, an `indoor_unit_id` referencing a `COIL` or `AIR_HANDLER`, and optionally a `furnace_id` which, when present, must reference a `FURNACE`."
    PRD §3.2: "The outdoor and indoor units must also be refrigerant-compatible: their `refrigerant_type` values must match, unless the indoor unit ships dry with a type of `NONE`. A registration violating any of these component-type or compatibility rules is rejected with `ERR_INVALID_SYSTEM_PAIRING` (422)."

    Design: Corner/validations/invalid_system_pairing_refrigerant_mismatch
    """
    ou = make_model(model_number="OU-MIS", refrigerant_type="R454B", family_code="FAM-C")
    ah = make_model(model_number="AH-MIS", equipment_type="AIR_HANDLER",
                    refrigerant_type="R410A", family_code="FAM-C",
                    list_price_cents=300_000)
    furnace = make_model(model_number="FU-MIS", equipment_type="FURNACE",
                         refrigerant_type="NONE", capacity_btuh=80_000,
                         family_code="FAM-C", list_price_cents=400_000)
    mismatch = api.create_ahri_rating(
        {"ahri_reference_number": "AHRI-MIS1", "outdoor_unit_id": ou["id"],
         "indoor_unit_id": ah["id"], "seer2": 16.0, "eer2": 12.0}, admin_headers)
    validate_error(mismatch, ApiErrorId.ERR_INVALID_SYSTEM_PAIRING)
    furnace_indoor = api.create_ahri_rating(
        {"ahri_reference_number": "AHRI-MIS2", "outdoor_unit_id": ou["id"],
         "indoor_unit_id": furnace["id"], "seer2": 16.0, "eer2": 12.0}, admin_headers)
    validate_error(furnace_indoor, ApiErrorId.ERR_INVALID_SYSTEM_PAIRING)


def test_ahri_classification_high_boundary_and_tax_credit(api, admin_headers):
    """PRD §3.2: "First, `efficiency_class`: a rating with `seer2` at least 17.0 and `eer2` at least 12.0 is `PREMIUM`; otherwise one with `seer2` at least 15.2 and `eer2` at least 11.7 is `HIGH`; anything else is `STANDARD`."
    PRD §3.2: "Second, `tax_credit_eligible` is true precisely when the class is `PREMIUM`, or when the class is `HIGH` and a non-null `hspf2` of at least 8.1 is on record."

    Design: Corner/calculations/ahri_classification_high_boundary_and_tax_credit
    """
    hp = make_model(model_number="HP-B1", equipment_type="HEAT_PUMP",
                    refrigerant_type="R454B", family_code="FAM-G2",
                    list_price_cents=900_000)
    ah = make_model(model_number="AH-B1", equipment_type="AIR_HANDLER",
                    refrigerant_type="R454B", family_code="FAM-G2",
                    list_price_cents=300_000)
    eligible = validate_success(api.create_ahri_rating(
        {"ahri_reference_number": "AHRI-B1A", "outdoor_unit_id": hp["id"],
         "indoor_unit_id": ah["id"], "seer2": 15.2, "eer2": 11.7, "hspf2": 8.1},
        admin_headers), 201)
    assert eligible["efficiency_class"] == "HIGH", (
        "15.2/11.7 are the inclusive HIGH boundaries")
    assert eligible["tax_credit_eligible"] is True, (
        "HIGH with hspf2 of at least 8.1 on record is tax-credit eligible")

    not_eligible = validate_success(api.create_ahri_rating(
        {"ahri_reference_number": "AHRI-B1B", "outdoor_unit_id": hp["id"],
         "indoor_unit_id": ah["id"], "seer2": 15.2, "eer2": 11.7, "hspf2": 8.0},
        admin_headers), 201)
    assert not_eligible["efficiency_class"] == "HIGH"
    assert not_eligible["tax_credit_eligible"] is False, (
        "hspf2 8.0 is below the 8.1 minimum")


class TestOrderLineShape:
    """Each order line names exactly one of the two references and quantity >= 1."""

    def _setup_draft(self):
        contractor = make_contractor(license_number="LIC-C400")
        model = make_model(model_number="CU-L400", family_code="FAM-B",
                           list_price_cents=500_000)
        order = create_draft_order(contractor)
        return contractor, model, order

    def test_line_quantity_zero_rejected(self, api):
        """PRD §3.4: "Each **order line** names either an `ahri_rating_id` (a matched system) or an `equipment_model_id` (a part-only line) — exactly one of the two, never both, never neither — plus a `quantity` of at least one; violations are rejected with `ERR_INVALID_LINE` (422)."

        Design: Corner/validations/invalid_line_both_ids_rejected
        """
        contractor, model, order = self._setup_draft()
        res = api.add_order_line(
            order["id"], {"equipment_model_id": model["id"], "quantity": 0},
            make_contractor_headers(contractor["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_LINE)

    def test_line_with_both_ids_rejected(self, api):
        """PRD §3.4: "Each **order line** names either an `ahri_rating_id` (a matched system) or an `equipment_model_id` (a part-only line) — exactly one of the two, never both, never neither — plus a `quantity` of at least one; violations are rejected with `ERR_INVALID_LINE` (422)."

        Design: Corner/validations/invalid_line_both_ids_rejected
        """
        contractor, model, order = self._setup_draft()
        rating, _, _ = make_system_rating("FAM-B")
        res = api.add_order_line(
            order["id"], {"equipment_model_id": model["id"],
                          "ahri_rating_id": rating["id"], "quantity": 1},
            make_contractor_headers(contractor["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_LINE)

    def test_line_with_neither_id_rejected(self, api):
        """PRD §3.4: "Each **order line** names either an `ahri_rating_id` (a matched system) or an `equipment_model_id` (a part-only line) — exactly one of the two, never both, never neither — plus a `quantity` of at least one; violations are rejected with `ERR_INVALID_LINE` (422)."

        Design: Corner/validations/invalid_line_both_ids_rejected
        """
        contractor, _, order = self._setup_draft()
        res = api.add_order_line(order["id"], {"quantity": 1},
                                 make_contractor_headers(contractor["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_LINE)


def test_discontinued_model_not_orderable(api):
    """PRD §3.2: "Model status is `ACTIVE` by default; `DISCONTINUED` models may not be referenced by new order lines, and `ALLOCATED_ONLY` models may be ordered only while an open allocation pool covers their family. An order line referencing a discontinued model, or an allocated-only model with no covering pool, is rejected with `ERR_MODEL_NOT_ORDERABLE` (422)."

    Design: Corner/validations/discontinued_model_not_orderable
    """
    contractor = make_contractor(license_number="LIC-C401")
    headers = make_contractor_headers(contractor["id"])
    discontinued = make_model(model_number="CU-D401", family_code="FAM-A",
                              list_price_cents=500_000, status="DISCONTINUED")
    order = create_draft_order(contractor)
    res = api.add_order_line(
        order["id"], {"equipment_model_id": discontinued["id"], "quantity": 1}, headers)
    validate_error(res, ApiErrorId.ERR_MODEL_NOT_ORDERABLE)

    active = make_model(model_number="CU-A401", family_code="FAM-A",
                        list_price_cents=500_000)
    ok = api.add_order_line(
        order["id"], {"equipment_model_id": active["id"], "quantity": 1}, headers)
    validate_success(ok, 201)


def test_order_with_nonexistent_contractor_rejected(api):
    """PRD §2.8: "4. **Body reference existence** — foreign-key identifiers referenced in the payload (`contractor_id`, `order_id`, `ahri_rating_id`, and so on) must exist; failures yield `ERR_REFERENCE_NOT_FOUND` (404)."

    Design: Corner/validations/body_fk_reference_not_found
    """
    headers = make_contractor_headers(NON_EXISTENT_UUID)
    res = api.create_order({"contractor_id": NON_EXISTENT_UUID}, headers)
    validate_error(res, ApiErrorId.ERR_REFERENCE_NOT_FOUND)
