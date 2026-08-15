"""Certificate lifecycle: suspend/reinstate cycles, clock-driven expiration,
reinstatement window, and revocation under audit."""
from test_helpers import (
    ApiErrorId,
    advance_days,
    create_approved_certificate,
    create_onboarded_customer,
    create_order_with_lines,
    open_campaign_with_samples,
    setup_customer_with_approved_cert,
    setup_tenant_config,
    submit_order,
    TEST_USERS,
    validate_error,
    validate_success,
)

AUD1 = TEST_USERS["auditor_headers"]


class TestSuspendReinstateCycle:
    def test_suspend_then_reinstate_round_trip(self, api, compliance_officer_headers):
        """PRD §3.4: "A `ComplianceOfficer` may suspend an `APPROVED` certificate, moving it `APPROVED` → `SUSPENDED`."
        PRD §3.4: "Reinstatement moves a `SUSPENDED` certificate back to `APPROVED`, but only while today is on or before the certificate's `expiration_date`; a reinstatement attempted after expiry is rejected with `ERR_CERT_EXPIRED` (HTTP 409)."

        Design: Difficulty/non_linear_state_machine/certificate_approved_suspended_cycle
        """
        # validity_window_days=0: the certificate never expires (expiration_date null),
        # so reinstatement is always inside the window.
        tenant, cust, cert = setup_customer_with_approved_cert()
        tid = tenant["id"]

        suspended = validate_success(api.suspend_certificate(tid, cert["id"], compliance_officer_headers), 200)
        assert suspended["status"] == "SUSPENDED"
        reinstated = validate_success(api.reinstate_certificate(tid, cert["id"], compliance_officer_headers), 200)
        assert reinstated["status"] == "APPROVED"

    def test_suspend_reinstate_cycle_is_repeatable(self, api, compliance_officer_headers):
        """PRD §3.4: "`REVOKED` and `SUPERSEDED` are terminal; `EXPIRED` certificates may be superseded but never reinstated; `SUSPENDED` is the only state that returns to `APPROVED`."

        Design: Difficulty/non_linear_state_machine/certificate_approved_suspended_cycle
        """
        tenant, cust, cert = setup_customer_with_approved_cert()
        tid = tenant["id"]

        observed = []
        for _ in range(2):
            observed.append(
                validate_success(api.suspend_certificate(tid, cert["id"], compliance_officer_headers), 200)["status"])
            observed.append(
                validate_success(api.reinstate_certificate(tid, cert["id"], compliance_officer_headers), 200)["status"])
        assert observed == ["SUSPENDED", "APPROVED", "SUSPENDED", "APPROVED"], (
            f"two full suspend/reinstate cycles must be permitted, got {observed}")
        final = validate_success(
            api.get_certificate(tid, cert["id"], compliance_officer_headers), 200)
        assert final["status"] == "APPROVED"


class TestCertificateExpirationWindow:
    def test_order_reheld_when_clock_passes_expiration(self, api, auditor_headers, tenant_admin_headers):
        """PRD §2.4: "Every certificate in `APPROVED` status whose `expiration_date` falls strictly before the new current day transitions to `EXPIRED`; a certificate whose expiration date equals the new current day remains valid through that day."
        PRD §3.4: "When a clock advance moves the current day strictly past an approved certificate's `expiration_date`, the certificate transitions `APPROVED` → `EXPIRED` automatically. Unless a superseding approved certificate is already in place, the customer's `collection_standing` falls to `LAPSED`; `cert_standing` is recomputed; and dependent orders in `READY_TO_SHIP` that lose coverage transition to `HELD_FOR_CERT` whenever their recomputed `uncovered_amount_cents` rises above zero, with the corresponding exposure increments."

        Design: Difficulty/resource_temporal_overlap/cert_expiration_window_vs_order_ship
        """
        # expiration_date = 2026-08-01 + 10 days = 2026-08-11 (day index 10).
        tenant, cust, cert = setup_customer_with_approved_cert(
            validity_window_days=10, signed_date="2026-08-01", effective_date="2026-08-01")
        tid = tenant["id"]
        # EX-prefixed SKU is fully covered under either coverage mode (PRD §3.5).
        order = create_order_with_lines(tid, cust["id"], (("EX-1", 1, 5000, True),))
        order = submit_order(tid, order["id"])
        assert order["status"] == "READY_TO_SHIP", f"setup: expected READY_TO_SHIP, got {order['status']}"

        advance_days(tid, 11)  # day 11 (2026-08-12) is strictly past 2026-08-11
        cert_after = validate_success(api.get_certificate(tid, cert["id"], auditor_headers), 200)
        order_after = validate_success(api.get_order(tid, order["id"], auditor_headers), 200)
        assert cert_after["status"] == "EXPIRED"
        assert order_after["status"] == "HELD_FOR_CERT", (
            "order that lost its only covering certificate must be re-held")

    def test_certificate_valid_through_expiration_day(self, api, auditor_headers):
        """PRD §2.4: "Every certificate in `APPROVED` status whose `expiration_date` falls strictly before the new current day transitions to `EXPIRED`; a certificate whose expiration date equals the new current day remains valid through that day."

        Design: Difficulty/resource_temporal_overlap/cert_expiration_window_vs_order_ship
        """
        tenant, cust, cert = setup_customer_with_approved_cert(
            validity_window_days=10, signed_date="2026-08-01", effective_date="2026-08-01")
        tid = tenant["id"]
        order = create_order_with_lines(tid, cust["id"], (("EX-1", 1, 5000, True),))
        order = submit_order(tid, order["id"])
        assert order["status"] == "READY_TO_SHIP"

        advance_days(tid, 10)  # lands exactly on expiration day 2026-08-11
        cert_after = validate_success(api.get_certificate(tid, cert["id"], auditor_headers), 200)
        order_after = validate_success(api.get_order(tid, order["id"], auditor_headers), 200)
        assert cert_after["status"] == "APPROVED", (
            "certificate whose expiration equals the current day remains valid through that day")
        assert order_after["status"] == "READY_TO_SHIP"


class TestReinstateAndRevoke:
    def test_reinstate_after_expiration_rejected(self, api, compliance_officer_headers):
        """PRD §3.4: "Reinstatement moves a `SUSPENDED` certificate back to `APPROVED`, but only while today is on or before the certificate's `expiration_date`; a reinstatement attempted after expiry is rejected with `ERR_CERT_EXPIRED` (HTTP 409)."

        Design: Corner/state_machines/cert_reinstate_after_expiration_rejected
        """
        # expiration_date = 2026-08-01 + 5 days = 2026-08-06 (day index 5).
        tenant, cust, cert = setup_customer_with_approved_cert(
            validity_window_days=5, signed_date="2026-08-01", effective_date="2026-08-01")
        tid = tenant["id"]
        validate_success(api.suspend_certificate(tid, cert["id"], compliance_officer_headers), 200)
        # Day 6 (2026-08-07) is past the 2026-08-06 expiration. The clock cascade in
        # §2.4 only expires APPROVED certificates, so this one is still SUSPENDED.
        advance_days(tid, 6)
        res = api.reinstate_certificate(tid, cert["id"], compliance_officer_headers)
        validate_error(res, ApiErrorId.ERR_CERT_EXPIRED, expected_status=409)

    def test_revoke_blocked_when_under_audit(self, api, compliance_officer_headers):
        """PRD §3.4: "A `ComplianceOfficer` may revoke an `APPROVED` certificate, but only when no audit sample in a non-terminal outcome references it — a certificate under active audit is frozen in place, and the revocation is rejected with `ERR_CERT_UNDER_AUDIT` (HTTP 409)."

        Design: Corner/state_machines/cert_revoke_blocked_when_under_audit
        """
        tenant, cust, cert = setup_customer_with_approved_cert()
        tid = tenant["id"]
        camp, samples = open_campaign_with_samples(
            tid=tid, population_state_filter=["CA"], floor_sample_size=1)
        # DOC_REQUESTED is a non-terminal outcome (PRD §3.8 terminal set:
        # PASSED / FAILED / WAIVED / EXPIRED_NO_RESPONSE).
        validate_success(api.request_docs(tid, samples[0]["id"], AUD1), 200)
        res = api.revoke_certificate(tid, cert["id"], compliance_officer_headers)
        validate_error(res, ApiErrorId.ERR_CERT_UNDER_AUDIT, expected_status=409)
