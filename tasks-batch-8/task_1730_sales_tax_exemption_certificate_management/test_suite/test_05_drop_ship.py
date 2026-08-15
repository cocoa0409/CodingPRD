"""Drop-ship resale verification checks (PRD §3.6)."""
from test_helpers import (
    ApiErrorId,
    create_approved_certificate,
    create_certificate_draft,
    create_drop_ship_link_payload,
    create_onboarded_customer,
    setup_tenant_config,
    validate_error,
    validate_success,
)


class TestDropShipVerification:
    def test_drop_ship_verify_with_unapproved_cert(self, api, compliance_officer_headers):
        """PRD §3.6: "First, the referenced resale certificate must be in `APPROVED` status; verifying against a certificate in any other status is rejected with `ERR_RESALE_CERT_NOT_APPROVED` (HTTP 409)."

        Design: Corner/state_machines/drop_ship_verify_with_unapproved_cert
        """
        tenant = setup_tenant_config()
        cust = create_onboarded_customer(tid=tenant["id"])
        cert = create_certificate_draft(tenant["id"], cust["id"])  # stays DRAFT
        link = validate_success(api.create_drop_ship_link(
            tenant["id"],
            create_drop_ship_link_payload(cust["id"], cert["id"], ship_to_state="CA"),
            compliance_officer_headers), 201)
        assert link["status"] == "PENDING_VERIFICATION"
        res = api.verify_drop_ship_link(tenant["id"], link["id"], compliance_officer_headers)
        validate_error(res, ApiErrorId.ERR_RESALE_CERT_NOT_APPROVED, expected_status=409)

    def test_drop_ship_state_mismatch_when_disallowed(self, api, compliance_officer_headers):
        """PRD §3.6: "Second, state alignment depends on the jurisdiction rule for the link's `ship_to_state`: when that rule's `allows_drop_ship_resale` is false, the resale certificate's own `ship_to_state` must equal the link's `ship_to_state`, and a mismatch is rejected with `ERR_DROP_SHIP_STATE_MISMATCH` (HTTP 422); when the rule's `allows_drop_ship_resale` is true, an out-of-state resale certificate is accepted as-is."

        Design: Corner/state_machines/drop_ship_state_mismatch_when_disallowed
        """
        tenant = setup_tenant_config(rule_specs=[
            {"state_code": "CA", "allows_drop_ship_resale": False},
            {"state_code": "TX", "allows_drop_ship_resale": False},
        ])
        cust = create_onboarded_customer(tid=tenant["id"], primary_ship_to_state="TX")
        cert = create_approved_certificate(tenant["id"], cust["id"],
                                           cert_overrides={"ship_to_state": "TX"})
        # Link ships into CA, but the resale certificate covers TX.
        link = validate_success(api.create_drop_ship_link(
            tenant["id"],
            create_drop_ship_link_payload(cust["id"], cert["id"], ship_to_state="CA"),
            compliance_officer_headers), 201)
        res = api.verify_drop_ship_link(tenant["id"], link["id"], compliance_officer_headers)
        validate_error(res, ApiErrorId.ERR_DROP_SHIP_STATE_MISMATCH, expected_status=422)
