"""Tenant creation defaults and tenant-configuration uniqueness rules."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    add_exemption_reason,
    add_jurisdiction_rule,
    assert_tenant,
    create_exemption_reason_payload,
    create_jurisdiction_rule_payload,
    create_tenant,
    create_tenant_payload,
    validate_error,
    validate_success,
)


class TestTenantConfig:
    def test_tenant_creation_returns_defaults(self, api, tenant_admin_headers):
        """PRD §3.1: "A new tenant starts with `audit_clock_day_index` at 0, `audit_posture` of `CLEAR`, and `open_exposure_cents` of 0."

        Design: Corner/entities/tenant_creation_returns_defaults
        """
        res = api.create_tenant(
            create_tenant_payload(legal_name="T1", home_state_code="NY"),
            tenant_admin_headers,
        )
        tenant = validate_success(res, 201)
        assert_tenant(tenant)
        assert tenant["audit_clock_day_index"] == 0, "new tenant clock must start at day index 0"
        assert tenant["audit_posture"] == "CLEAR"
        assert tenant["open_exposure_cents"] == 0

    def test_tenant_not_found_returns_404(self, api, tenant_admin_headers):
        """PRD §2.6: "The request is rejected immediately with a 404 carrying `ERR_NOT_FOUND` at the first path identifier that does not resolve to a live record inside the tenant scope; later segments are not examined."

        Design: Corner/entities/tenant_not_found_returns_404
        """
        res = api.get_tenant(NON_EXISTENT_UUID, tenant_admin_headers)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)

    def test_jurisdiction_rule_duplicate_state_rejected(self, api, tenant_admin_headers):
        """PRD §3.1: "One rule may exist per state per tenant: creating a second rule with a `state_code` already present for the tenant is rejected with `ERR_DUPLICATE_JURISDICTION` (HTTP 409)."

        Design: Corner/entities/jurisdiction_rule_duplicate_state_rejected
        """
        tenant = create_tenant(legal_name="T1")
        add_jurisdiction_rule(tenant["id"], state_code="CA")
        res = api.create_jurisdiction_rule(
            tenant["id"],
            create_jurisdiction_rule_payload(
                state_code="CA",
                accepted_form_types=["EXEMPT_ORG"],
                validity_window_days=365,
                anchor_rule="SIGNED_DATE",
                allows_drop_ship_resale=True,
                requires_state_registration_number=True,
                blanket_cert_allowed=True,
            ),
            tenant_admin_headers,
        )
        validate_error(res, ApiErrorId.ERR_DUPLICATE_JURISDICTION, expected_status=409)

    def test_exemption_reason_duplicate_code_rejected(self, api, tenant_admin_headers):
        """PRD §3.1: "A duplicate `code` within the tenant is rejected with `ERR_DUPLICATE_REASON_CODE` (HTTP 409)."

        Design: Corner/entities/exemption_reason_duplicate_code_rejected
        """
        tenant = create_tenant(legal_name="T1")
        add_exemption_reason(tenant["id"], code="RES")
        res = api.create_exemption_reason(
            tenant["id"],
            create_exemption_reason_payload(
                code="RES", description="Duplicate", tax_engine_code="R2",
                requires_certificate=False, allowed_form_types=[],
            ),
            tenant_admin_headers,
        )
        validate_error(res, ApiErrorId.ERR_DUPLICATE_REASON_CODE, expected_status=409)
