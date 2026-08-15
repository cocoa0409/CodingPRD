"""Response envelope shape, pagination semantics, filtered listing, and the
not-found error family."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    create_class_code,
    create_policy,
    run_selection,
    validate_error,
    validate_paginated,
    validate_success,
)

UNDERWRITER = TEST_USERS["underwriter_headers"]
MANAGER = TEST_USERS["audit_manager_headers"]
AUDITOR_FALLBACK = TEST_USERS["auditor_headers"]


class TestPagination:
    def test_policy_list_pagination_envelope(self, api):
        """PRD: "The `limit` parameter sets the maximum number of items
        returned; it defaults to 10, with a minimum of 1 and a maximum of 100.
        The `offset` parameter sets the number of items skipped and defaults
        to 0."
        PRD: "Paginated list responses include `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the envelope."

        Design: Corner/entities/policy_list_pagination_envelope
        """
        cc = create_class_code()
        for number in ("WC-PG1", "WC-PG2", "WC-PG3"):
            create_policy(number, [cc["id"]],
                          expiration_date="2026-12-31T00:00:00Z")

        page1, meta1 = validate_paginated(
            api.list_policies(MANAGER, params={"limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2
        assert meta1["offset"] == 0

        page2, meta2 = validate_paginated(
            api.list_policies(MANAGER, params={"limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

    def test_work_order_list_filters_compose(self, api):
        """PRD: "Several list endpoints accept additional optional filters
        named in the workflows below: the policies list accepts `status` and
        `coverage_line`; the classification-code list accepts `state_code` and
        `coverage_line`; and the work-order list accepts `policy_id`,
        `selection_run_id`, `assigned_auditor_id`, and `status`."

        Design: Corner/cross_cutting_complexity_layers/filtered_list_status_and_policy_interplay
        """
        cc = create_class_code()
        pol_a = create_policy("WC-O4A", [cc["id"]],
                              estimated_annual_premium_cents=2000000,
                              minimum_premium_cents=100000)
        create_policy("WC-O4B", [cc["id"]],
                      estimated_annual_premium_cents=600000)
        run_selection()

        selected, meta_sel = validate_paginated(
            api.list_work_orders(MANAGER, params={"status": "SELECTED"}))
        assert meta_sel["total_count"] == 2

        narrowed, meta_narrow = validate_paginated(
            api.list_work_orders(MANAGER, params={"status": "SELECTED",
                                                  "policy_id": pol_a["id"]}))
        assert meta_narrow["total_count"] == 1
        assert narrowed[0]["audit_type"] == "PHYSICAL"
        assert narrowed[0]["policy_id"] == pol_a["id"]

        closed, meta_closed = validate_paginated(
            api.list_work_orders(MANAGER, params={"status": "CLOSED"}))
        assert meta_closed["total_count"] == 0
        assert closed == []


class TestEnvelopeShape:
    def test_response_envelope_success_and_error_shape(self, api):
        """PRD: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`."
        PRD: "The `response_type` is either "object" for a single resource or
        "array" for a list of resources."
        PRD: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."
        PRD: "The `message` provides a human-readable explanation of what went
        wrong."

        Design: Corner/endpoints/response_envelope_success_and_error_shape
        """
        cc = create_class_code()
        policy = create_policy("WC-E1", [cc["id"]],
                               expiration_date="2026-12-31T00:00:00Z")

        ok = api.get_policy(policy["id"], MANAGER)
        data = validate_success(ok, 200)
        body = ok.json()
        assert body["meta"]["api_request_id"].startswith("req_")
        assert isinstance(body["meta"]["api_request_timestamp"], str)
        assert body["response_type"] == "object"
        assert data["id"] == policy["id"]

        err = api.get_policy(NON_EXISTENT_UUID, MANAGER)
        error_data = validate_error(err, ApiErrorId.ERR_POLICY_NOT_FOUND)
        err_body = err.json()
        assert err_body["response_type"] == "error"
        assert isinstance(error_data["message"], str)
        assert error_data["message"].strip()


class TestNotFoundFamily:
    def test_not_found_errors_across_entities(self, api):
        """PRD: "6. **Existence** — path identifiers and foreign-key inputs
        resolve, validated left to right; failure yields the matching one of
        `ERR_POLICY_NOT_FOUND`, `ERR_AUDITOR_NOT_FOUND`,
        `ERR_CLASS_CODE_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`,
        `ERR_RECORDS_REQUEST_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`,
        `ERR_ALLOCATION_NOT_FOUND`, `ERR_SUB_EXPOSURE_NOT_FOUND`,
        `ERR_CERTIFICATE_NOT_FOUND`, `ERR_AUDIT_RESULT_NOT_FOUND`,
        `ERR_DISPUTE_NOT_FOUND`, `ERR_BILLING_NOT_FOUND`, or
        `ERR_MOD_REVISION_NOT_FOUND` (all 404)."

        Design: Corner/errors/not_found_errors_across_entities
        """
        checks = [
            (api.get_auditor(NON_EXISTENT_UUID, MANAGER),
             ApiErrorId.ERR_AUDITOR_NOT_FOUND),
            (api.get_classification_code(NON_EXISTENT_UUID, MANAGER),
             ApiErrorId.ERR_CLASS_CODE_NOT_FOUND),
            (api.get_work_order(NON_EXISTENT_UUID, MANAGER),
             ApiErrorId.ERR_WORK_ORDER_NOT_FOUND),
            (api.receive_records_request(NON_EXISTENT_UUID, AUDITOR_FALLBACK),
             ApiErrorId.ERR_RECORDS_REQUEST_NOT_FOUND),
            (api.get_appointment(NON_EXISTENT_UUID, MANAGER),
             ApiErrorId.ERR_APPOINTMENT_NOT_FOUND),
            (api.get_payroll_allocation(NON_EXISTENT_UUID, MANAGER),
             ApiErrorId.ERR_ALLOCATION_NOT_FOUND),
            (api.get_subcontractor_exposure(NON_EXISTENT_UUID, MANAGER),
             ApiErrorId.ERR_SUB_EXPOSURE_NOT_FOUND),
            (api.verify_certificate(NON_EXISTENT_UUID, AUDITOR_FALLBACK),
             ApiErrorId.ERR_CERTIFICATE_NOT_FOUND),
            (api.get_audit_result(NON_EXISTENT_UUID, MANAGER),
             ApiErrorId.ERR_AUDIT_RESULT_NOT_FOUND),
            (api.get_dispute(NON_EXISTENT_UUID, MANAGER),
             ApiErrorId.ERR_DISPUTE_NOT_FOUND),
            (api.get_billing_transaction(NON_EXISTENT_UUID, MANAGER),
             ApiErrorId.ERR_BILLING_NOT_FOUND),
            (api.apply_mod_revision(NON_EXISTENT_UUID, UNDERWRITER),
             ApiErrorId.ERR_MOD_REVISION_NOT_FOUND),
        ]
        for resp, expected in checks:
            validate_error(resp, expected)
