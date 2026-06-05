"""Auth/pagination validation, nested sub-resource reads, RBAC, OCC, cascade ordering, immediacy.

Breadth coverage for the validations, endpoints (nested sub-resource reads), rbac,
cross_cutting_complexity_layers, and consistency_model corner sections.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    make_physician_headers,
    make_patient_headers,
    board_headers,
    officer_headers,
    set_clock,
    create_physician,
    issue_license,
    create_patient,
    request_visit,
    setup_licensed_physician,
    setup_requested_visit,
    setup_cleared_visit,
    setup_visit_with_active_controlled_rx,
)


class TestAuthAndPagination:

    def test_missing_auth_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "When a request that requires authentication arrives without both
        headers present, or carries an `X-User-Role` that is not one of the declared roles,
        it is rejected with `ERR_UNAUTHENTICATED`."

        Design: Corner/validations/missing_auth_headers_returns_unauthenticated
        """
        physician, license_, patient, visit = setup_requested_visit(state_code="CA")
        # run-compliance is a protected write; send no auth headers.
        res = api.run_compliance(visit["id"], headers={})
        validate_error(res, "ERR_UNAUTHENTICATED")

    def test_pagination_limit_over_max_returns_pagination_invalid(self, api):
        """PRD §2.3: "A request whose `limit` falls outside the range of 1 to 100 inclusive,
        or whose `offset` is less than 0, is rejected with `ERR_PAGINATION_INVALID`."

        Design: Corner/validations/pagination_limit_over_max_returns_pagination_invalid
        """
        res = api.list_physicians(board_headers(), params={"limit": 101})
        validate_error(res, "ERR_PAGINATION_INVALID")


class TestNestedSubResourceReads:

    def test_list_state_licenses_by_physician_subresource(self, api):
        """PRD §2.5: "Many endpoints address a resource nested under a parent — for example,
        the prescriptions authored on a particular visit, or the state licenses held by a
        particular physician."

        Design: Corner/endpoints/list_state_licenses_by_physician_subresource
        """
        physician = create_physician(imlc_eligible=True, home_state_code="CA")
        issue_license(physician["id"], state_code="CA", issuance_type="FULL")
        issue_license(physician["id"], state_code="NV", issuance_type="COMPACT_EXPEDITED")
        data, meta = validate_paginated(api.list_state_licenses(physician["id"], board_headers()))
        assert meta["total_count"] == 2, (
            f"physician's licenses sub-resource should list 2, got {meta['total_count']}"
        )

    def test_list_compliance_checks_by_license_subresource(self, api):
        """PRD §2.5: "Many endpoints address a resource nested under a parent — for example,
        the prescriptions authored on a particular visit, or the state licenses held by a
        particular physician."
        PRD §3.3: "a `matched_license_id` set to the selected license's `id`".

        Design: Corner/endpoints/list_compliance_checks_by_license_subresource
        """
        physician, license_, patient, cleared = setup_cleared_visit(state_code="CA")
        data, meta = validate_paginated(api.list_license_compliance_checks(license_["id"], board_headers()))
        assert meta["total_count"] == 1, (
            f"one CLEARED check should be governed by this license, got {meta['total_count']}"
        )
        assert data[0]["outcome"] == "CLEARED", f"expected CLEARED, got {data[0]['outcome']}"
        assert data[0]["matched_license_id"] == license_["id"], (
            f"matched_license_id should be the governing license, got {data[0]['matched_license_id']}"
        )


class TestRbac:

    def test_patient_cannot_run_compliance_returns_forbidden(self, api):
        """PRD §2.1: "When the headers are well-formed but the role is not permitted to
        perform the requested operation — or an ownership-bound actor targets a resource it
        does not own — the request is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/patient_cannot_run_compliance_returns_forbidden
        """
        physician, license_, patient, visit = setup_requested_visit(state_code="CA")
        # run-compliance is a Physician operation; a Patient invoking it is forbidden.
        res = api.run_compliance(visit["id"], make_patient_headers(patient["id"]))
        validate_error(res, "ERR_FORBIDDEN")

    def test_physician_cannot_suspend_license_returns_forbidden(self, api):
        """PRD §2.1: "When the headers are well-formed but the role is not permitted to
        perform the requested operation — or an ownership-bound actor targets a resource it
        does not own — the request is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/physician_cannot_suspend_license_returns_forbidden
        """
        physician, license_ = setup_licensed_physician(state_code="CA")
        # suspend is a LicensingBoard operation; a Physician invoking it is forbidden.
        res = api.suspend_state_license(license_["id"], {"suspension_reason": "x"},
                                        make_physician_headers(physician["id"]))
        validate_error(res, "ERR_FORBIDDEN")

    def test_physician_cannot_act_on_other_physicians_visit_returns_forbidden(self, api):
        """PRD §2.1: "a `Physician` may act only on a `Visit` whose `physician_id` equals
        their `X-User-ID`."

        Design: Corner/rbac/physician_cannot_act_on_other_physicians_visit_returns_forbidden
        """
        set_clock("2026-04-01T09:00:00.000Z")
        phys_a = create_physician(full_name="Dr A", npi="1111111111", home_state_code="CA")
        issue_license(phys_a["id"], state_code="CA", issuance_type="FULL")
        phys_b = create_physician(full_name="Dr B", npi="2222222222", home_state_code="CA")
        patient = create_patient(residence_state_code="CA")
        visit = request_visit(phys_a["id"], patient["id"], determined_state_code="CA")
        # Physician B (does not own the visit) runs compliance on Physician A's visit.
        res = api.run_compliance(visit["id"], make_physician_headers(phys_b["id"]))
        validate_error(res, "ERR_FORBIDDEN")


class TestOptimisticConcurrency:

    def test_stale_prescription_version_returns_412(self, api):
        """PRD §2.7: "If that supplied value does not equal the target visit's current
        `prescription_version` — that is, if another accepted authoring has advanced the
        counter since the client last read it — the request is rejected with
        `ERR_STALE_PRESCRIPTION_VERSION` at HTTP 412."
        PRD §3.7: "the new prescription becomes the `ACTIVE` one, the prior prescription of
        that drug transitions from `ACTIVE` to `SUPERSEDED`, and the visit's
        `prescription_version` is incremented by one."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_prescription_version_returns_412
        """
        _, _, _, cleared = setup_cleared_visit(controlled=True, dea_number="BV1234567", state_code="CA")
        phys_headers = make_physician_headers(cleared["physician_id"])
        v0 = cleared["prescription_version"]
        assert v0 == 0, f"a fresh visit's prescription_version starts at 0, got {v0}"
        # rx1: first controlled rx, no prior to supersede -> version stays 0.
        validate_success(api.create_prescription(
            cleared["id"],
            {"drug_name": "Lorazepam", "dea_schedule": "IV", "days_supply": 30,
             "expected_visit_prescription_version": 0}, phys_headers), 201)
        after_rx1 = validate_success(api.get_visit(cleared["id"], phys_headers), 200)
        assert after_rx1["prescription_version"] == 0, (
            f"first rx (no prior) must not bump the counter, got {after_rx1['prescription_version']}"
        )
        # rx2: same drug supersede with the fresh version 0 -> bumps to 1.
        validate_success(api.create_prescription(
            cleared["id"],
            {"drug_name": "Lorazepam", "dea_schedule": "IV", "days_supply": 30,
             "expected_visit_prescription_version": 0}, phys_headers), 201)
        after_rx2 = validate_success(api.get_visit(cleared["id"], phys_headers), 200)
        assert after_rx2["prescription_version"] == 1, (
            f"supersede must bump the counter to 1, got {after_rx2['prescription_version']}"
        )
        # trigger: a third authoring still carrying the now-stale version 0 -> 412.
        res = api.create_prescription(
            cleared["id"],
            {"drug_name": "Lorazepam", "dea_schedule": "IV", "days_supply": 30,
             "expected_visit_prescription_version": 0}, phys_headers)
        validate_error(res, "ERR_STALE_PRESCRIPTION_VERSION")


class TestCascadeOrdering:

    def test_suspension_cascade_voids_visit_prescription_and_reverses_claim(self, api):
        """PRD §3.4: "an `APPROVED_INSURANCE` visit governed by it likewise transitions to
        `VOIDED`."
        PRD §3.4: "As part of a visit's transition to `VOIDED`, every `Prescription` on that
        visit (matched by `visit_id`) whose `status` is `ACTIVE` transitions from `ACTIVE`
        to `VOIDED`."
        PRD §3.4: "When the visit being voided is an `APPROVED_INSURANCE` visit, every
        `Claim` on that visit (matched by `visit_id`) whose `status` is `SUBMITTED` or
        `ADJUDICATED` transitions to `REVERSED`."

        Design: Corner/cross_cutting_complexity_layers/suspension_cascade_n_level_ordering_visit_then_prescription_then_claim
        """
        ctx = setup_visit_with_active_controlled_rx(
            insured=True,
            payer_overrides={"telehealth_parity": True, "copay_cents": 2500,
                             "covered_state_codes": ["CA"], "allowed_amount_cents": 8000},
            dea_schedule="IV", drug_name="Lorazepam",
        )
        api.suspend_state_license(ctx["license"]["id"], {"suspension_reason": "board action"}, board_headers())
        phys_headers = make_physician_headers(ctx["physician"]["id"])
        visit_after = validate_success(api.get_visit(ctx["visit"]["id"], phys_headers), 200)
        assert visit_after["status"] == "VOIDED", f"expected visit VOIDED, got {visit_after['status']}"
        rx_after = validate_success(api.get_prescription(ctx["prescription"]["id"], phys_headers), 200)
        assert rx_after["status"] == "VOIDED", f"expected prescription VOIDED, got {rx_after['status']}"
        claim_after = validate_success(api.get_claim(ctx["claim"]["id"], officer_headers()), 200)
        assert claim_after["status"] == "REVERSED", f"expected claim REVERSED, got {claim_after['status']}"


class TestImmediateConsistency:

    def test_approve_response_immediately_reflects_patient_cost(self, api):
        """PRD §3.5: "When the patient on the visit carries insurance — their
        `insurance_payer_id` is not null — approval routes to insurance: the visit moves
        from `COMPLIANCE_CLEARED` to `APPROVED_INSURANCE`, its `routing` is set to
        `INSURANCE`, and its `patient_cost_cents` is computed by the insurance cost path
        described below."
        PRD §3.5: "If the payer offers telehealth parity (`telehealth_parity` is true), the
        patient owes exactly the payer's `copay_cents`."

        Design: Corner/consistency_model/approve_response_immediately_reflects_patient_cost
        """
        # Build an insured, cleared visit explicitly so the approve response can be inspected directly.
        physician, license_ = setup_licensed_physician(state_code="CA")
        payer = validate_success(api.create_payer({
            "name": "Parity", "telehealth_parity": True, "copay_cents": 2500,
            "covered_state_codes": ["CA"], "allowed_amount_cents": 8000,
        }, officer_headers()), 201)
        patient = create_patient(email="a@x.com", residence_state_code="CA", insurance_payer_id=payer["id"])
        visit = request_visit(physician["id"], patient["id"], determined_state_code="CA", list_fee_cents=10000)
        phys_headers = make_physician_headers(physician["id"])
        validate_success(api.run_compliance(visit["id"], phys_headers), 200)
        approved = validate_success(api.approve_visit(visit["id"], phys_headers), 200)
        assert approved["routing"] == "INSURANCE", (
            f"approve response should carry routing INSURANCE, got {approved['routing']}"
        )
        assert approved["patient_cost_cents"] == 2500, (
            f"approve response should carry patient_cost_cents 2500 immediately, got {approved['patient_cost_cents']}"
        )
