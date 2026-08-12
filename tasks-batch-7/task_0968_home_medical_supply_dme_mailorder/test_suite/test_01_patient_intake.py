"""Patient intake: enrollment defaults, HSA cascade, eligibility, listing,
ownership, authentication, and fitting-sample window limits."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_patient,
    assert_hsa_account,
    create_payer_plan,
    create_patient,
    verify_patient,
    create_active_patient,
    create_program,
    create_sample,
    create_manual_order,
    set_logical_clock,
    INTAKE,
    BILLING,
    make_patient_headers,
)


class TestPatientEnrollment:
    def test_patient_creation_defaults_and_hsa_cascade(self, api):
        """PRD §3.2: "Enrollment creates the patient in `PENDING_VERIFICATION`
        status and, in the same act, creates exactly one **HSA account** for the
        patient: the account's `initial_credit_cents` equals
        `hsa_initial_credit_cents`, and its opening `balance_cents` equals that
        same amount."

        Design: Corner/entities/patient_creation_defaults_and_hsa_cascade
        """
        plan = create_payer_plan()
        patient = create_patient(plan["id"], hsa_initial_credit_cents=750)

        assert_patient(patient)
        assert patient["status"] == "PENDING_VERIFICATION"

        data = validate_success(
            api.list_patient_hsa_accounts(patient["id"], INTAKE), expected_status=200
        )
        assert isinstance(data, list) and len(data) == 1, (
            f"expected exactly one HSA account, got {len(data)}"
        )
        account = data[0]
        assert_hsa_account(account)
        assert account["patient_id"] == patient["id"]
        assert account["balance_cents"] == pytest.approx(750, abs=0.001)
        assert account["initial_credit_cents"] == pytest.approx(750, abs=0.001)

    def test_immediate_read_after_write_visibility(self, api):
        """PRD §3.2: "Enrollment creates the patient in `PENDING_VERIFICATION`
        status and, in the same act, creates exactly one **HSA account** for the
        patient". PRD §2.9: "The system upholds the following propagation rules
        automatically, without requiring a client request against the affected
        resource".

        Design: Corner/consistency_model/immediate_read_after_write_visibility
        """
        plan = create_payer_plan()
        patient = create_patient(plan["id"], hsa_initial_credit_cents=42)

        fetched = validate_success(api.get_patient(patient["id"], INTAKE), expected_status=200)
        assert fetched["full_name"] == patient["full_name"]
        assert fetched["status"] == "PENDING_VERIFICATION"

        accounts = validate_success(
            api.list_patient_hsa_accounts(patient["id"], INTAKE), expected_status=200
        )
        assert len(accounts) == 1
        assert accounts[0]["balance_cents"] == pytest.approx(42, abs=0.001)

    def test_patient_get_not_found_returns_404(self, api):
        """PRD §2.6: "Identifiers in the URL path are resolved first, in the
        order they appear; if any path identifier does not correspond to an
        existing resource, the request is rejected immediately with
        `ERR_NOT_FOUND` (HTTP 404)".

        Design: Corner/entities/patient_get_not_found_returns_404
        """
        resp = api.get_patient(NON_EXISTENT_UUID, INTAKE)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_patient_list_pagination_envelope(self, api):
        """PRD §2.3: "Paginated list-based responses include the following
        fields in the `meta` object of the response envelope: `limit`, `offset`,
        `total_count`, and `has_more`."

        Design: Corner/endpoints/patient_list_pagination_envelope
        """
        plan = create_payer_plan()
        p1 = create_patient(plan["id"])
        p2 = create_patient(plan["id"])

        page1, meta1 = validate_paginated(api.list_patients(INTAKE, params={"limit": 1, "offset": 0}))
        assert len(page1) == 1, f"limit=1 must return exactly 1 item, got {len(page1)}"
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(api.list_patients(INTAKE, params={"limit": 1, "offset": 1}))
        assert len(page2) == 1
        assert meta2["total_count"] == 2
        assert meta2["has_more"] is False
        assert {page1[0]["id"], page2[0]["id"]} == {p1["id"], p2["id"]}


class TestEligibilityAndOwnership:
    def test_verify_eligibility_twice_returns_invalid_state(self, api):
        """PRD §3.2: "When `eligible` is true, the patient moves from
        `PENDING_VERIFICATION` to `ACTIVE`". PRD §2.10: "an unavailable
        transition or a locked terminal state yields `ERR_INVALID_STATE`".

        Design: Corner/state_machines/verify_eligibility_twice_returns_invalid_state
        """
        plan = create_payer_plan()
        patient = create_patient(plan["id"])
        verified = verify_patient(patient["id"], eligible=True)
        assert verified["status"] == "ACTIVE"

        resp = api.verify_eligibility(patient["id"], {"eligible": True}, INTAKE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        after = validate_success(api.get_patient(patient["id"], INTAKE), expected_status=200)
        assert after["version"] == verified["version"], (
            "rejected verify-eligibility must not mutate the patient"
        )

    def test_order_create_before_eligibility_rejected(self, api):
        """PRD §3.2: "creating a resupply program, creating an order, confirming
        a resupply cycle, and requesting a fitting sample each reject with
        `ERR_PATIENT_NOT_ACTIVE` (HTTP 409) unless the patient is `ACTIVE`."

        Design: Corner/validations/order_create_before_eligibility_rejected
        """
        plan = create_payer_plan()
        patient = create_patient(plan["id"])  # stays PENDING_VERIFICATION

        resp = api.create_order({"patient_id": patient["id"]}, make_patient_headers(patient["id"]))
        validate_error(resp, ApiErrorId.ERR_PATIENT_NOT_ACTIVE)

    def test_patient_cannot_access_other_patients_orders(self, api):
        """PRD §2.1: "A `Patient` acting on another patient's resource is
        rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/patient_cannot_access_other_patients_orders
        """
        plan = create_payer_plan(plan_type="CASH_HSA", coinsurance_pct=1.00, cycle_months=1)
        patient_a = create_active_patient(plan["id"])
        patient_b = create_active_patient(plan["id"])

        resp = api.list_patient_orders(patient_b["id"], make_patient_headers(patient_a["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestAuthentication:
    def test_missing_auth_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or carrying a role other
        than these six, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
        PRD §2.10: "Authentication and authorization come first".

        Design: Corner/validations/missing_auth_headers_returns_unauthenticated
        """
        resp = api.get_patient(NON_EXISTENT_UUID, headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestFittingSamples:
    def test_sample_rolling_window_third_rejected_then_allowed(self, api):
        """PRD §3.9: "within the closed lookback of the 90 days ending today —
        a sample created exactly 90 days ago still counts — at most two samples
        may exist for the patient and category across all statuses. The second
        sample within the window succeeds; a request that would create a third
        is rejected with `ERR_SAMPLE_LIMIT_EXCEEDED` (HTTP 422)." PRD §3.9:
        "the sample's `unit_price_cents` is always 0."

        Design: Corner/calculations/sample_rolling_window_third_rejected_then_allowed
        """
        plan = create_payer_plan()
        patient = create_active_patient(plan["id"])

        # Clock starts at 2026-05-01 (PRD startup default).
        create_sample(patient["id"], category="OSTOMY", size_code="45MM", item_name="Pouch sample")
        set_logical_clock("2026-05-10T00:00:00Z")
        create_sample(patient["id"], category="OSTOMY", size_code="45MM", item_name="Barrier sample")

        set_logical_clock("2026-05-20T00:00:00Z")
        resp = api.create_fitting_sample(
            {"patient_id": patient["id"], "category": "OSTOMY",
             "size_code": "45MM", "item_name": "Third sample"},
            INTAKE,
        )
        validate_error(resp, ApiErrorId.ERR_SAMPLE_LIMIT_EXCEEDED)

        # At 2026-08-10 the closed window starts 2026-05-12; both earlier
        # samples (05-01, 05-10) have aged out.
        set_logical_clock("2026-08-10T00:00:00Z")
        later = validate_success(
            api.create_fitting_sample(
                {"patient_id": patient["id"], "category": "OSTOMY",
                 "size_code": "45MM", "item_name": "Later sample"},
                INTAKE,
            ),
            expected_status=201,
        )
        assert later["unit_price_cents"] == 0
        assert later["status"] == "REQUESTED"
