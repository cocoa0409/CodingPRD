"""CRUD surface, not-found and validation probes, defaults, listing,
immutability, withdraw transitions, duplicate identifiers, and RBAC
(forbidden role, unauthenticated, segregation of duties).

PRD §2.1 (RBAC), §2.3 (pagination), §2.4 (common properties), §2.5 (existence),
§3.1-§3.5 (reference data, filing, payment, withdraw).
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_jurisdiction,
    create_contractor,
    create_permit,
    create_permit_payload,
    create_contractor_payload,
    create_issued_permit_with_passed_rough,
    create_approved_permit,
    schedule_inspection,
    create_inspector,
    create_slot,
    pay_in_full,
    current_version,
    make_applicant_headers,
    make_clerk_headers,
    make_official_headers,
    make_inspector_headers,
    build_user_headers,
)

# A syntactically valid UUID that resolves to nothing (matches the design probes).
MISSING_UUID = "00000000-0000-4000-8000-000000000000"


class TestPermitCreation:
    def test_create_permit_returns_201_with_computed_fields(self, api):
        """PRD §3.2: "A freshly filed permit enters `status` `SUBMITTED`, takes
        `work_status` `NOT_STARTED`, and has its first audit event appended with
        `event_type` `SUBMITTED`."

        Design: Corner/entities/create_permit_returns_201_with_computed_fee_fields
        """
        jur = create_jurisdiction()
        con = create_contractor()
        resp = api.create_permit(
            create_permit_payload(jur["id"], con["id"],
                                  work_class="REPAIR", fee_method="VALUATION",
                                  declared_valuation=2000),
            make_applicant_headers())
        data = validate_success(resp, 201)
        assert data["status"] == "SUBMITTED"
        assert data["work_status"] == "NOT_STARTED"
        assert data["total_permit_fee"] == 165.00


class TestNotFound:
    @pytest.mark.parametrize("getter,error_id", [
        ("get_permit", ApiErrorId.ERR_PERMIT_NOT_FOUND),
        ("get_review", ApiErrorId.ERR_REVIEW_NOT_FOUND),
        ("get_correction_notice", ApiErrorId.ERR_CORRECTION_NOT_FOUND),
        ("get_inspection", ApiErrorId.ERR_INSPECTION_NOT_FOUND),
        ("get_slot", ApiErrorId.ERR_SLOT_NOT_FOUND),
        ("get_stop_work_order", ApiErrorId.ERR_SWO_NOT_FOUND),
        ("get_certificate", ApiErrorId.ERR_CO_NOT_FOUND),
    ])
    def test_get_missing_resource_returns_specific_not_found(self, api, getter, error_id):
        """PRD §2.5: "Each resource kind has its own not-found error: a missing
        permit yields `ERR_PERMIT_NOT_FOUND`, a missing contractor
        `ERR_CONTRACTOR_NOT_FOUND`, a missing jurisdiction
        `ERR_JURISDICTION_NOT_FOUND`, a missing plan review `ERR_REVIEW_NOT_FOUND`,
        a missing correction notice `ERR_CORRECTION_NOT_FOUND`, a missing
        inspection `ERR_INSPECTION_NOT_FOUND`, a missing inspection slot
        `ERR_SLOT_NOT_FOUND`, a missing stop-work order `ERR_SWO_NOT_FOUND`, and a
        missing certificate of occupancy `ERR_CO_NOT_FOUND`."

        Design: Corner/entities/get_permit_not_found_returns_404
        Design: Corner/entities/get_review_not_found_returns_404
        Design: Corner/entities/get_correction_not_found_returns_404
        Design: Corner/entities/get_inspection_not_found_returns_404
        Design: Corner/entities/get_slot_not_found_returns_404
        Design: Corner/entities/get_stop_work_order_not_found_returns_404
        Design: Corner/entities/get_certificate_not_found_returns_404
        """
        method = getattr(api, getter)
        resp = method(MISSING_UUID, make_official_headers())
        validate_error(resp, error_id.value)


class TestPermitInputValidation:
    def test_missing_fee_method_returns_invalid_request(self, api):
        """PRD §3.2: "the `fee_method`, which selects how the fee is computed and
        is one of `VALUATION` or `SQUARE_FOOT`."

        Design: Corner/entities/create_permit_missing_fee_method_returns_invalid_request
        """
        jur = create_jurisdiction()
        con = create_contractor()
        resp = api.create_permit(
            {"jurisdiction_id": jur["id"], "contractor_id": con["id"],
             "work_class": "REPAIR", "declared_valuation": 2000},
            make_applicant_headers())
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_bad_work_class_enum_returns_invalid_request(self, api):
        """PRD §3.2: "the `work_class` — one of `NEW_CONSTRUCTION`, `ADDITION`,
        `ALTERATION`, or `REPAIR`".

        Design: Corner/entities/create_permit_bad_work_class_enum_returns_invalid_request
        """
        jur = create_jurisdiction()
        con = create_contractor()
        resp = api.create_permit(
            create_permit_payload(jur["id"], con["id"],
                                  work_class="DEMOLITION", fee_method="VALUATION",
                                  declared_valuation=2000),
            make_applicant_headers())
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_unknown_jurisdiction_returns_not_found(self, api):
        """PRD §2.5: "a missing jurisdiction `ERR_JURISDICTION_NOT_FOUND`".

        Design: Corner/entities/create_permit_unknown_jurisdiction_returns_404
        """
        con = create_contractor()
        resp = api.create_permit(
            create_permit_payload(MISSING_UUID, con["id"],
                                  work_class="REPAIR", fee_method="VALUATION",
                                  declared_valuation=2000),
            make_applicant_headers())
        validate_error(resp, ApiErrorId.ERR_JURISDICTION_NOT_FOUND.value)

    def test_unknown_contractor_returns_not_found(self, api):
        """PRD §2.5: "a missing contractor `ERR_CONTRACTOR_NOT_FOUND`".

        Design: Corner/entities/create_permit_unknown_contractor_returns_404
        """
        jur = create_jurisdiction()
        resp = api.create_permit(
            create_permit_payload(jur["id"], MISSING_UUID,
                                  work_class="REPAIR", fee_method="VALUATION",
                                  declared_valuation=2000),
            make_applicant_headers())
        validate_error(resp, ApiErrorId.ERR_CONTRACTOR_NOT_FOUND.value)


class TestJurisdictionDefaults:
    def test_renewal_and_valid_days_defaults_applied(self, api):
        """PRD §3.1: "`renewal_fee_pct`, the renewal charge as a fraction of the
        original total fee, which defaults to 0.5 when omitted; and
        `permit_valid_days`, the number of days a permit stays valid from
        issuance, which must be at least 1 and defaults to 180 when omitted."

        Design: Corner/entities/jurisdiction_default_renewal_and_valid_days_applied
        """
        jur = create_jurisdiction()  # omits renewal_fee_pct and permit_valid_days
        assert jur["renewal_fee_pct"] == 0.5
        assert jur["permit_valid_days"] == 180


class TestPermitListing:
    def test_list_permits_pagination_envelope(self, api):
        """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`,
        and `has_more` in the `meta` object of the envelope, where `total_count`
        reflects the full size of the filtered collection before the page window
        is applied and `has_more` indicates whether records remain beyond the
        current page."

        Design: Corner/entities/list_permits_pagination_envelope
        """
        jur = create_jurisdiction()
        con = create_contractor()
        create_permit(jur["id"], con["id"], work_class="REPAIR",
                     fee_method="VALUATION", declared_valuation=2000)
        create_permit(jur["id"], con["id"], work_class="REPAIR",
                     fee_method="VALUATION", declared_valuation=2000)
        resp = api.list_permits(make_clerk_headers(),
                                params={"contractor_id": con["id"], "limit": 1, "offset": 0})
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 2
        assert meta["has_more"] is True
        assert len(data) == 1


class TestFeePaymentImmutability:
    def test_payment_response_has_no_version_field(self, api):
        """PRD §2.4: "A `FeePayment` is append-only — once recorded it is never
        edited — and a `PermitEvent` is an immutable audit record. Both therefore
        carry only `id` and `created_at`; neither exposes `updated_at` nor `version`."

        Design: Corner/entities/feepayment_is_immutable_no_version_field
        """
        jur = create_jurisdiction()
        con = create_contractor()
        permit = create_permit(jur["id"], con["id"], work_class="REPAIR",
                              fee_method="VALUATION", declared_valuation=2000)
        resp = api.create_payment(permit["id"], {"amount": 50.00}, make_applicant_headers())
        data = validate_success(resp, 201)
        assert "version" not in data, "FeePayment must not expose version"
        assert "created_at" in data and data["created_at"]


class TestWithdrawTransitions:
    def test_withdraw_submitted_permit_moves_to_withdrawn(self, api):
        """PRD §3.5: "Withdrawal is allowed from any pre-issuance status:
        `SUBMITTED`, `UNDER_REVIEW`, `CORRECTIONS_REQUIRED`, or `APPROVED` ...
        moves the permit to the terminal `WITHDRAWN` status".

        Design: Corner/state_machines/withdraw_submitted_permit_valid_transition
        """
        jur = create_jurisdiction()
        con = create_contractor()
        permit = create_permit(jur["id"], con["id"], work_class="REPAIR",
                              fee_method="VALUATION", declared_valuation=2000)
        resp = api.withdraw_permit(permit["id"], make_applicant_headers())
        data = validate_success(resp)
        assert data["status"] == "WITHDRAWN"

    def test_withdraw_twice_second_rejected_terminal(self, api):
        """PRD §3.5: "It is not allowed once the permit reaches `ISSUED`; an
        attempt from `ISSUED` or any later status is rejected with
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/withdraw_then_withdraw_terminal_lockdown
        """
        jur = create_jurisdiction()
        con = create_contractor()
        permit = create_permit(jur["id"], con["id"], work_class="REPAIR",
                              fee_method="VALUATION", declared_valuation=2000)
        validate_success(api.withdraw_permit(permit["id"], make_applicant_headers()))
        resp = api.withdraw_permit(permit["id"], make_applicant_headers())
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


class TestUniquenessAndPayment:
    def test_duplicate_license_number_rejected(self, api):
        """PRD §3.1: "The `license_number` must be unique across all contractors —
        a collision is rejected with `ERR_DUPLICATE_LICENSE`."

        Design: Corner/validations/contractor_create_duplicate_license_returns_409
        """
        validate_success(api.create_contractor(
            create_contractor_payload(license_number="DUP-1"), make_clerk_headers()), 201)
        resp = api.create_contractor(
            create_contractor_payload(business_name="Second", license_number="DUP-1"),
            make_clerk_headers())
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_LICENSE.value)

    def test_zero_amount_payment_rejected(self, api):
        """PRD §3.3: "A payment names an `amount`, which must be strictly greater
        than zero — a non-positive amount is rejected with `ERR_INVALID_REQUEST`".

        Design: Corner/validations/payment_zero_amount_returns_invalid_request
        """
        jur = create_jurisdiction()
        con = create_contractor()
        permit = create_permit(jur["id"], con["id"], work_class="REPAIR",
                              fee_method="VALUATION", declared_valuation=2000)
        resp = api.create_payment(permit["id"], {"amount": 0}, make_applicant_headers())
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


class TestRbac:
    def test_applicant_cannot_issue_permit(self, api):
        """PRD §2.1: "A syntactically valid request whose role is not authorized
        for the requested operation is rejected with `ERR_FORBIDDEN_ROLE`."

        Design: Corner/rbac/applicant_cannot_issue_permit_forbidden
        """
        permit, _review, _rev = create_approved_permit(
            work_class="REPAIR", fee_method="VALUATION", declared_valuation=2000)
        pay_in_full(permit["id"])
        pv = current_version(permit["id"])
        # An Applicant attempts the PermitClerk-exclusive issue op.
        resp = api.issue_permit(permit["id"],
                                {"expected_permit_application_version": pv},
                                make_applicant_headers())
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    def test_missing_auth_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "A request that omits either header, or that presents an
        `X-User-Role` value outside this set, is rejected with
        `ERR_UNAUTHENTICATED`."

        Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
        """
        resp = api._request("GET", "/permits", headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)

    def test_approver_cannot_field_sign_final(self, api):
        """PRD §3.8: "the acting inspector's `id` must differ from the permit's
        `approving_reviewer_id` — the plan reviewer who approved the design may
        not also field-sign the final inspection, and a violation is rejected with
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/segregation_of_duties_approver_cannot_field_sign_final
        """
        # Approve via a reviewer; ROUGH passed by a neutral inspector; FINAL slot
        # is published for inspector_id == reviewer's id; FINAL result attempted by
        # the approver acting as inspector.
        issued, reviewer, neutral_inspector, slot, rough_passed = (
            create_issued_permit_with_passed_rough(
                max_inspections=5, work_class="REPAIR",
                fee_method="VALUATION", declared_valuation=2000))
        # Publish a FINAL slot belonging to the approving reviewer (acting as inspector).
        dual_slot = create_slot(reviewer["id"],
                                window_start="2026-07-02T08:00:00Z",
                                window_end="2026-07-02T17:00:00Z",
                                max_inspections=5)
        final = schedule_inspection(issued["id"], dual_slot["id"], "FINAL",
                                    "2026-07-02T09:00:00Z", "2026-07-02T10:00:00Z")
        resp = api.record_inspection_result(
            final["id"], {"outcome": "PASS"},
            make_inspector_headers(reviewer["id"]))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
