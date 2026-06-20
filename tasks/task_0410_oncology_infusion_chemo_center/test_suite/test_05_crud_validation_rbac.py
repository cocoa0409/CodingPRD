"""CRUD validation, listing, RBAC, not-found, and error corners.

Queue B only: entities (required field, not-found, listing, invalid enum),
validations (missing dosing-specific field), rbac (peer-role denials, missing
auth), errors (PA not-requested, cycle-not-found), endpoints (FK list filter).
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    NON_EXISTENT_UUID,
    build_user_headers,
    factories as f,
    fixtures as fx,
    make_nurse_headers,
)
from test_helpers.test_users import TEST_USERS

PHARM = TEST_USERS["pharmacist_headers"]
NURSE = TEST_USERS["nurse_headers"]
PAC = TEST_USERS["prior_auth_coordinator_headers"]

FLAT_CHEMO = dict(drug_name="DrugC", role="CHEMO", dosing_method="FLAT",
                  flat_dose_mg=600, vial_size_mg=150, day_offset=1, sequence_index=1)


class TestEntityCrudCorners:
    def test_create_patient_missing_height_rejected(self):
        """PRD §3.1: "A `Pharmacist` registers a patient by supplying a unique
        medical record number `mrn`, the patient's `full_name`, a `height_cm` and
        `weight_kg` both required to be strictly greater than zero, and a
        `gfr_ml_min` glomerular filtration rate, also strictly greater than zero"
        PRD §2.10: "Request-body well-formedness is fourth: required fields
        present ... or the request is rejected with `ERR_INVALID_REQUEST` (400)."

        Omitting height_cm -> ERR_INVALID_REQUEST.

        Design: Corner/entities/create_patient_missing_required_field_returns_invalid_request
        """
        resp = api_client.create_patient(
            {"mrn": "C2-uniq", "full_name": "Corner Two", "weight_kg": 60, "gfr_ml_min": 90},
            PHARM)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_get_nonexistent_patient_returns_not_found(self):
        """PRD §2.10: "the first that fails to resolve yields its
        resource-specific not-found error (404): `ERR_PATIENT_NOT_FOUND` for a
        patient"

        Design: Corner/entities/get_patient_nonexistent_returns_not_found
        """
        resp = api_client.get_patient(NON_EXISTENT_UUID, PHARM)
        validate_error(resp, ApiErrorId.ERR_PATIENT_NOT_FOUND.value)

    def test_list_patients_returns_paginated_envelope(self):
        """PRD §2.3: "Every list response carries the pagination fields `limit`,
        `offset`, `total_count`, and `has_more` inside the `meta` object of the
        envelope."

        One patient created -> array response with total_count 1, has_more false.

        Design: Corner/entities/list_patients_paginated_envelope
        """
        fx.create_patient()
        data, meta = validate_paginated(api_client.list_patients(NURSE))
        assert meta["total_count"] == 1, f"expected total_count 1, got {meta['total_count']}"
        assert meta["has_more"] is False

    def test_order_set_item_invalid_dosing_enum_rejected(self):
        """PRD §3.2: "The item's `dosing_method` is one of `BSA`, `AUC`, or
        `FLAT`"
        PRD §2.10: "enums within their allowed sets ... must all hold, or the
        request is rejected with `ERR_INVALID_REQUEST` (400)."

        dosing_method='XYZ' -> ERR_INVALID_REQUEST.

        Design: Corner/entities/order_set_item_invalid_dosing_enum_rejected
        """
        protocol = fx.create_protocol()
        resp = api_client.create_order_set_item(
            {"regimen_protocol_id": protocol["id"], "drug_name": "DrugC", "role": "CHEMO",
             "dosing_method": "XYZ", "flat_dose_mg": 100, "vial_size_mg": 50,
             "day_offset": 1, "sequence_index": 1}, PHARM)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


class TestValidationCorners:
    def test_bsa_item_missing_dose_per_m2_rejected(self):
        """PRD §3.2: "a `BSA` item requires `dose_per_m2` (milligrams per square
        meter) ... Supplying the body of an item whose dosing method's required
        dose field is absent is a malformed request."

        BSA item with no dose_per_m2 -> ERR_INVALID_REQUEST.

        Design: Corner/validations/order_missing_dosing_specific_field_rejected
        """
        protocol = fx.create_protocol()
        resp = api_client.create_order_set_item(
            {"regimen_protocol_id": protocol["id"], "drug_name": "DrugB", "role": "CHEMO",
             "dosing_method": "BSA", "vial_size_mg": 50, "day_offset": 1, "sequence_index": 1},
            PHARM)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


class TestRbacCorners:
    def test_nurse_cannot_create_patient(self):
        """PRD §2.1: "The pharmacist owns patient, protocol, order-set, chair,
        nurse, treatment-cycle, and drug-order creation"
        PRD §2.1: "When a well-authenticated caller attempts an operation their
        role is not permitted to perform, the request is rejected with
        `ERR_FORBIDDEN_ROLE`."

        Design: Corner/rbac/rbac_nurse_cannot_create_patient
        """
        resp = api_client.create_patient(
            f.create_patient_payload(mrn="C20-uniq", full_name="Corner Twenty"),
            make_nurse_headers("nurse-x"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    def test_pharmacist_cannot_verify_drug_order(self):
        """PRD §2.1: "The nurse owns the chairside order actions and appointment
        check-in and completion."
        PRD §2.1: "When a well-authenticated caller attempts an operation their
        role is not permitted to perform, the request is rejected with
        `ERR_FORBIDDEN_ROLE`."

        Verify is Nurse-exclusive; a Pharmacist calling it is denied.

        Design: Corner/rbac/rbac_pharmacist_cannot_verify_drug_order
        """
        env = fx.setup_active_cycle(item_overrides=dict(FLAT_CHEMO))
        n1 = fx.create_nurse(full_name="N21", is_chemo_certified=True)
        order = fx.create_drug_order(env["cycle"]["id"], env["item"]["id"])
        fx.prepare_order(order["id"], n1["id"])
        resp = api_client.verify_drug_order(order["id"], f.verify_drug_order_payload(600), PHARM)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    def test_pharmacist_cannot_decide_prior_auth(self):
        """PRD §2.1: "The prior-authorization coordinator owns opening and deciding
        prior authorizations."
        PRD §2.1: "When a well-authenticated caller attempts an operation their
        role is not permitted to perform, the request is rejected with
        `ERR_FORBIDDEN_ROLE`."

        Design: Corner/rbac/rbac_pharmacist_cannot_decide_prior_auth
        """
        patient = fx.create_patient()
        pa = validate_success(api_client.create_prior_authorization(
            f.create_prior_authorization_payload(patient["id"], drug_name="SpecialtyX"), PAC), 201)
        resp = api_client.decide_prior_authorization(
            pa["id"], f.decide_prior_authorization_payload("APPROVE", authorized_units_mg=500), PHARM)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    def test_missing_auth_header_rejected(self):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
        identifying the acting user, and `X-User-Role`, declaring the capacity in
        which they act. A request missing either header, or carrying a malformed
        one, is rejected with `ERR_MISSING_AUTH`."

        Design: Corner/rbac/rbac_missing_auth_header_rejected
        """
        resp = api_client.create_patient(
            f.create_patient_payload(mrn="C23-uniq", full_name="Corner TwentyThree"), {})
        validate_error(resp, ApiErrorId.ERR_MISSING_AUTH.value)


class TestErrorCorners:
    def test_decide_already_approved_pa_rejected(self):
        """PRD §3.4: "Deciding is legal only while the authorization is
        `REQUESTED`; deciding one in any other state is rejected with
        `ERR_PA_NOT_REQUESTED`."

        Deciding (DENY) a PA that is already APPROVED -> ERR_PA_NOT_REQUESTED.

        Design: Corner/errors/error_pa_decide_not_requested_stub
        """
        patient = fx.create_patient()
        fx.create_approved_pa(patient["id"], "SpecialtyX", 600)
        # create_approved_pa returns the APPROVED PA
        pa = validate_success(api_client.create_prior_authorization(
            f.create_prior_authorization_payload(patient["id"], drug_name="SpecialtyY"), PAC), 201)
        validate_success(api_client.decide_prior_authorization(
            pa["id"], f.decide_prior_authorization_payload("APPROVE", authorized_units_mg=600), PAC), 200)
        resp = api_client.decide_prior_authorization(
            pa["id"], f.decide_prior_authorization_payload("DENY"), PAC)
        validate_error(resp, ApiErrorId.ERR_PA_NOT_REQUESTED.value)

    def test_create_order_nonexistent_cycle_returns_not_found(self):
        """PRD §2.10: "the first that fails to resolve yields its
        resource-specific not-found error (404): ... `ERR_CYCLE_NOT_FOUND` for a
        treatment cycle"

        Creating a drug order referencing a non-existent treatment_cycle_id (with
        a valid order_set_item_id) -> ERR_CYCLE_NOT_FOUND.

        Design: Corner/errors/error_cycle_not_found_on_create_order
        """
        protocol, item = fx.setup_published_protocol_with_item(item_overrides=dict(FLAT_CHEMO))
        resp = api_client.create_drug_order(
            f.create_drug_order_payload(NON_EXISTENT_UUID, item["id"]), PHARM)
        validate_error(resp, ApiErrorId.ERR_CYCLE_NOT_FOUND.value)


class TestEndpointFilterCorners:
    def test_list_drug_orders_filtered_by_cycle(self):
        """PRD §3.7: "Drug orders can be listed — filterable by
        `treatment_cycle_id`, `order_set_item_id`, `prior_authorization_id`,
        `prepared_by_nurse_id`, or `verified_by_nurse_id` — and fetched by id."

        GET /drug-orders?treatment_cycle_id={id} returns only that cycle's orders.

        Design: Corner/endpoints/fk_list_drug_orders_by_cycle
        """
        env = fx.setup_active_cycle(item_overrides=dict(FLAT_CHEMO))
        order = fx.create_drug_order(env["cycle"]["id"], env["item"]["id"])
        data, meta = validate_paginated(
            api_client.list_drug_orders(NURSE, params={"treatment_cycle_id": env["cycle"]["id"]}))
        assert meta["total_count"] == 1, f"expected total_count 1, got {meta['total_count']}"
        assert all(o["treatment_cycle_id"] == env["cycle"]["id"] for o in data)
        assert order["id"] in {o["id"] for o in data}
