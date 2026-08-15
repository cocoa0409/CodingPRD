"""Acquisition intake defaults, response envelope, authentication, and RBAC."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_acquisition,
    create_acquisition_payload,
    get_success_data,
    make_vendor_manager_headers,
    validate_error,
    validate_success,
)

ANALYST = TEST_USERS["analyst_headers"]
HR1 = TEST_USERS["hr_partner_headers"]


class TestAcquisitionIntakeDefaults:
    def test_create_acquisition_applies_defaults_and_system_fields(self, api):
        """PRD §3.1: "A new acquisition opens in `DRAFT` status with
        `readiness_posture` `ON_TRACK` and every computed money field at zero:
        `deferred_maintenance_total_cents`, `rent_roll_variance_cents`,
        `deposit_variance_cents`, `payroll_accrual_cents`, and
        `net_proration_cents` all start at 0, and `closing_executed_at` stays
        null until closing executes."
        PRD §3.1: "`true_up_window_days` defaults to 90 days after closing
        during which post-closing adjustments may be asserted;
        `maintenance_estimate_basis` defaults to `INSPECTOR_BASIS` (the
        alternative being `SELLER_BASIS`) and selects which cost estimate feeds
        the deferred-maintenance rollup; and `interest_accrual_method` defaults
        to `DAILY_ACCRUAL` (the alternative being `SIMPLE_ANNUAL`) and governs
        deposit interest."
        PRD §2.5: "`version` is an integer that starts at 1 on creation and
        increments by exactly one on every mutation of the resource"

        Design: Corner/entities/create_acquisition_applies_defaults_and_system_fields
        """
        resp = api.create_acquisition(
            create_acquisition_payload(property_name="Default Deal"), ANALYST)
        acq = validate_success(resp, 201)
        assert_acquisition(acq)
        assert acq["status"] == "DRAFT"
        assert acq["readiness_posture"] == "ON_TRACK"
        for field in ("deferred_maintenance_total_cents", "rent_roll_variance_cents",
                      "deposit_variance_cents", "payroll_accrual_cents",
                      "net_proration_cents"):
            assert acq[field] == 0, f"{field} should start at 0, got {acq[field]}"
        assert acq["version"] == 1
        assert acq["true_up_window_days"] == 90
        assert acq["maintenance_estimate_basis"] == "INSPECTOR_BASIS"
        assert acq["interest_accrual_method"] == "DAILY_ACCRUAL"
        assert acq["closing_executed_at"] is None

    def test_get_acquisition_not_found_returns_404(self, api):
        """PRD §2.4: "The 404 family is one error per entity type:
        `ERR_ACQUISITION_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`, ..."

        Design: Corner/entities/get_acquisition_not_found_returns_404
        """
        resp = api.get_acquisition(NON_EXISTENT_UUID, ANALYST)
        validate_error(resp, ApiErrorId.ERR_ACQUISITION_NOT_FOUND, 404)


class TestResponseEnvelope:
    def test_response_envelope_shape_on_success_and_error(self, api):
        """PRD §2.2: "The `response_type` is either \"object\" for a single
        resource or \"array\" for a list of resources."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."
        PRD §2.3: "The `meta` object of a list response carries `limit`,
        `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/response_envelope_shape_on_success_and_error
        """
        create_resp = api.create_acquisition(
            create_acquisition_payload(property_name="Env Deal"), ANALYST)
        acq = validate_success(create_resp, 201)
        body = create_resp.json()
        assert body["response_type"] == "object"
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert isinstance(body["meta"]["api_request_timestamp"], str)

        err_resp = api.get_acquisition(NON_EXISTENT_UUID, ANALYST)
        err_body = err_resp.json()
        assert err_body["response_type"] == "error"
        assert err_body["data"]["error_id"] == "ERR_ACQUISITION_NOT_FOUND"
        assert isinstance(err_body["data"]["message"], str)
        assert err_body["data"]["message"].strip()

        list_resp = api.list_units(ANALYST, params={"acquisition_id": acq["id"]})
        list_body = list_resp.json()
        assert list_body["response_type"] == "array"
        for field in ("limit", "offset", "total_count", "has_more"):
            assert field in list_body["meta"], f"list meta must carry {field}"


class TestAuthentication:
    def test_unauthenticated_request_returns_401(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role
        outside the declared catalog, is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."

        Design: Corner/validations/unauthenticated_request_returns_401
        """
        resp = api.create_acquisition(
            create_acquisition_payload(property_name="No Auth"), headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)


class TestRbacDenials:
    def test_rbac_hrpartner_cannot_create_acquisition(self, api):
        """PRD §2.1: "A request whose role is authenticated but not listed among
        the roles authorized for the target endpoint is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."
        PRD §2.1: "Every read endpoint is available to all seven roles; write
        authorization is enumerated per endpoint in §4."

        Design: Corner/rbac/rbac_hrpartner_cannot_create_acquisition
        """
        acq = get_success_data(api.create_acquisition(
            create_acquisition_payload(property_name="RBAC Deal"), ANALYST), 201)

        resp = api.create_acquisition(
            create_acquisition_payload(property_name="HR Attempt"), HR1)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)

        read_resp = api.get_acquisition(acq["id"], HR1)
        read_back = validate_success(read_resp, 200)
        assert read_back["id"] == acq["id"], "every role shares read access"

    def test_rbac_analyst_cannot_approve_tax_projection(self, api):
        """PRD §4: the approve endpoint's authorized role is
        "UnderwritingManager".
        PRD §2.1: "A request whose role is authenticated but not listed among
        the roles authorized for the target endpoint is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/rbac_analyst_cannot_approve_tax_projection
        """
        acq = get_success_data(api.create_acquisition(
            create_acquisition_payload(property_name="RBAC Two"), ANALYST), 201)
        proj = get_success_data(api.create_tax_projection(
            acq["id"],
            {"method": "PURCHASE_PRICE_ANCHORED",
             "expected_acquisition_version": acq["version"]},
            ANALYST), 201)
        computed = get_success_data(api.compute_tax_projection(proj["id"], ANALYST))
        assert computed["status"] == "COMPUTED"

        resp = api.approve_tax_projection(proj["id"], ANALYST)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)
        after = get_success_data(api.get_tax_projection(proj["id"], ANALYST))
        assert after["status"] == "COMPUTED", "failed approve must not mutate"

    def test_rbac_authorization_precedes_existence(self, api):
        """PRD §2.4: "The server applies a fixed validation order to every
        request, from cheapest and most general to most specific: first
        authentication (`ERR_UNAUTHENTICATED`), then role authorization
        (`ERR_FORBIDDEN`), then existence of every identifier referenced by the
        request (the 404 family), ..."

        Design: Corner/rbac/rbac_authorization_precedes_existence
        """
        vm = make_vendor_manager_headers("vm-1")
        resp = api.queue_deposit_escrow(
            "00000000-0000-0000-0000-0000000000aa", vm)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)

    def test_rbac_non_admin_cannot_set_clock(self, api):
        """PRD §2.7: "A `PlatformAdmin` may advance the clock by supplying a
        `to_iso8601` instant through the test-driving clock capability"
        PRD §4: the clock endpoint's authorized role is "PlatformAdmin".

        Design: Corner/rbac/rbac_non_admin_cannot_set_clock
        """
        resp = api.set_clock("2026-09-12T00:00:00Z", ANALYST)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)
