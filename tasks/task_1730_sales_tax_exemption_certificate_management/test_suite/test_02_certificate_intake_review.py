"""Customer onboarding defaults, certificate intake validations, approval-time
segregation of duties, and the jurisdiction anchor-rule divergence."""
from test_helpers import (
    ApiErrorId,
    add_exemption_reason,
    assert_certificate,
    assert_customer,
    create_approved_certificate,
    create_certificate_draft,
    create_certificate_payload,
    create_customer,
    create_customer_payload,
    create_onboarded_customer,
    create_tenant,
    drive_certificate_to_under_review,
    get_customer_version,
    get_success_data,
    setup_tenant_config,
    TEST_USERS,
    upload_version,
    validate_error,
    validate_success,
)


class TestCustomerCreationDefaults:
    def test_customer_creation_returns_default_parallel_standing(self, api, compliance_officer_headers):
        """PRD §3.2: "Creation begins onboarding: the new customer's `onboarding_completed_at` is null, and orders cannot be submitted for the customer until a `ComplianceOfficer` marks onboarding complete, which stamps `onboarding_completed_at` with the current timestamp and increments the customer's `version`."
        PRD §3.2: "A customer is created at `MISSING`."
        PRD §3.2: "A customer starts at `CURRENT`."
        PRD §3.2: "A customer starts at `NOT_UNDER_AUDIT` and moves to `SAMPLED` the moment an audit sample row naming the customer is created during campaign sampling."

        Design: Corner/entities/customer_creation_returns_default_parallel_standing
        """
        tenant = create_tenant(legal_name="T1")
        add_exemption_reason(tenant["id"], code="RES")
        res = api.create_customer(
            tenant["id"],
            create_customer_payload(external_ref="C1", legal_name="Cust",
                                    primary_ship_to_state="CA", exemption_reason_code="RES"),
            compliance_officer_headers,
        )
        cust = validate_success(res, 201)
        assert_customer(cust)
        assert cust["cert_standing"] == "MISSING"
        assert cust["audit_standing"] == "NOT_UNDER_AUDIT"
        assert cust["collection_standing"] == "CURRENT"
        assert cust["onboarding_completed_at"] is None


class TestCertificateSubmitValidations:
    def test_cert_submit_without_version_rejected(self, api, compliance_officer_headers):
        """PRD §3.3: "Submission evaluates its checks in the global order of §2.10: the certificate must be in `DRAFT` (else `ERR_INVALID_STATE_TRANSITION`); then the certificate's `form_type` must appear in the `accepted_form_types` of the jurisdiction rule governing its `ship_to_state` (else `ERR_FORM_NOT_ACCEPTED_IN_STATE`, HTTP 422); then, when that rule's `requires_state_registration_number` is true, the certificate's `state_registration_number` must be non-empty (else `ERR_MISSING_STATE_REGISTRATION`, HTTP 422); and finally at least one `CertificateVersion` must have been uploaded, so that `current_version_id` is set (else `ERR_NO_CERT_VERSION`, HTTP 422)."

        Design: Corner/state_machines/cert_submit_without_version_rejected
        """
        tenant = setup_tenant_config()  # CA rule accepts RESALE, no registration required
        cust = create_onboarded_customer(tid=tenant["id"])
        cert = create_certificate_draft(tenant["id"], cust["id"])
        res = api.submit_certificate(tenant["id"], cert["id"], compliance_officer_headers)
        validate_error(res, ApiErrorId.ERR_NO_CERT_VERSION, expected_status=422)

    def test_cert_form_not_accepted_in_state(self, api, compliance_officer_headers):
        """PRD §3.3: "then the certificate's `form_type` must appear in the `accepted_form_types` of the jurisdiction rule governing its `ship_to_state` (else `ERR_FORM_NOT_ACCEPTED_IN_STATE`, HTTP 422)"

        Design: Corner/state_machines/cert_form_not_accepted_in_state
        """
        tenant = setup_tenant_config(rule_specs=[{
            "state_code": "CA", "accepted_form_types": ["EXEMPT_ORG"],
        }])
        cust = create_onboarded_customer(tid=tenant["id"])
        cert = create_certificate_draft(tenant["id"], cust["id"], form_type="RESALE")
        upload_version(tenant["id"], cert["id"], form_type="RESALE")
        res = api.submit_certificate(tenant["id"], cert["id"], compliance_officer_headers)
        validate_error(res, ApiErrorId.ERR_FORM_NOT_ACCEPTED_IN_STATE, expected_status=422)

    def test_cert_missing_state_registration(self, api, compliance_officer_headers):
        """PRD §3.3: "then, when that rule's `requires_state_registration_number` is true, the certificate's `state_registration_number` must be non-empty (else `ERR_MISSING_STATE_REGISTRATION`, HTTP 422)"

        Design: Corner/state_machines/cert_missing_state_registration
        """
        tenant = setup_tenant_config(rule_specs=[{
            "state_code": "CA", "requires_state_registration_number": True,
        }])
        cust = create_onboarded_customer(tid=tenant["id"])
        cert = create_certificate_draft(tenant["id"], cust["id"], state_registration_number="")
        upload_version(tenant["id"], cert["id"])
        res = api.submit_certificate(tenant["id"], cert["id"], compliance_officer_headers)
        validate_error(res, ApiErrorId.ERR_MISSING_STATE_REGISTRATION, expected_status=422)


class TestCertificateApproval:
    def test_cert_approve_immediate_visibility(self, api, compliance_officer_2_headers):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."
        PRD §3.3: "When the rule's `validity_window_days` is 0 the certificate never expires and `expiration_date` is null; otherwise `expiration_date` is the anchor date plus `validity_window_days` days, computed as whole-day date arithmetic with no rounding."

        Design: Corner/consistency_model/cert_approve_immediate_visibility
        """
        tenant = setup_tenant_config(rule_specs=[{
            "state_code": "CA", "validity_window_days": 30, "anchor_rule": "EFFECTIVE_DATE",
        }])
        cust = create_onboarded_customer(tid=tenant["id"])
        cert = drive_certificate_to_under_review(
            tenant["id"], cust["id"],
            cert_overrides={"signed_date": "2026-08-01", "effective_date": "2026-08-01"},
            version_overrides={"signed_date": "2026-08-01", "effective_date": "2026-08-01"})
        cust_v = get_customer_version(tenant["id"], cust["id"])
        res = api.approve_certificate(
            tenant["id"], cert["id"], {"expected_customer_version": cust_v},
            compliance_officer_2_headers)
        approved = validate_success(res, 200)
        assert_certificate(approved)
        # Approval response itself carries the new state and computed expiration:
        # EFFECTIVE_DATE anchor 2026-08-01 + 30 days == 2026-08-31.
        assert approved["status"] == "APPROVED"
        assert approved["expiration_date"] == "2026-08-31"
        fetched = validate_success(
            api.get_certificate(tenant["id"], cert["id"], compliance_officer_2_headers), 200)
        assert fetched["status"] == "APPROVED"
        assert fetched["expiration_date"] == "2026-08-31"

    def test_anchor_rule_produces_divergent_expirations(self, api, auditor_headers):
        """PRD §3.3: "the anchor date is the certificate's `effective_date` when the governing rule's `anchor_rule` is `EFFECTIVE_DATE`, and the certificate's `signed_date` when the `anchor_rule` is `SIGNED_DATE` — the two anchor variants can legitimately produce different expiration dates for the same certificate, and the rule alone decides which applies."
        PRD §3.3: "When the rule's `validity_window_days` is 0 the certificate never expires and `expiration_date` is null; otherwise `expiration_date` is the anchor date plus `validity_window_days` days, computed as whole-day date arithmetic with no rounding."

        Design: Difficulty/dual_variant_calc/cert_validity_anchor_divergence
        """
        tenant = setup_tenant_config(rule_specs=[
            {"state_code": "CA", "validity_window_days": 365, "anchor_rule": "EFFECTIVE_DATE"},
            {"state_code": "TX", "validity_window_days": 365, "anchor_rule": "SIGNED_DATE"},
        ])
        cust = create_onboarded_customer(tid=tenant["id"], primary_ship_to_state="CA")
        dates = {"signed_date": "2026-01-01", "effective_date": "2026-03-01"}
        cert_ca = create_approved_certificate(
            tenant["id"], cust["id"],
            cert_overrides={"ship_to_state": "CA", **dates},
            version_overrides={"file_uri": "s3://ca.pdf", **dates})
        cert_tx = create_approved_certificate(
            tenant["id"], cust["id"],
            cert_overrides={"ship_to_state": "TX", **dates},
            version_overrides={"file_uri": "s3://tx.pdf", **dates})

        exp_ca = validate_success(
            api.get_certificate(tenant["id"], cert_ca["id"], auditor_headers), 200)["expiration_date"]
        exp_tx = validate_success(
            api.get_certificate(tenant["id"], cert_tx["id"], auditor_headers), 200)["expiration_date"]
        # EFFECTIVE_DATE anchor: 2026-03-01 + 365 days; SIGNED_DATE anchor: 2026-01-01 + 365 days.
        assert exp_ca == "2027-03-01", f"EFFECTIVE_DATE anchor must anchor on 2026-03-01, got {exp_ca}"
        assert exp_tx == "2027-01-01", f"SIGNED_DATE anchor must anchor on 2026-01-01, got {exp_tx}"
        assert exp_ca != exp_tx, "the two anchor rules must diverge for identical certificate dates"

    def test_anchor_rule_signed_date_replication(self, api, auditor_headers):
        """PRD §3.3: "the anchor date is the certificate's `effective_date` when the governing rule's `anchor_rule` is `EFFECTIVE_DATE`, and the certificate's `signed_date` when the `anchor_rule` is `SIGNED_DATE` — the two anchor variants can legitimately produce different expiration dates for the same certificate, and the rule alone decides which applies."

        Design: Difficulty/dual_variant_calc/cert_validity_anchor_divergence
        """
        tenant = setup_tenant_config(rule_specs=[
            {"state_code": "TX", "validity_window_days": 365, "anchor_rule": "SIGNED_DATE"},
        ])
        cust = create_onboarded_customer(tid=tenant["id"], primary_ship_to_state="TX")
        cert = create_approved_certificate(
            tenant["id"], cust["id"],
            cert_overrides={"ship_to_state": "TX",
                            "signed_date": "2026-01-01", "effective_date": "2026-03-01"},
            version_overrides={"signed_date": "2026-01-01", "effective_date": "2026-03-01"})
        fetched = validate_success(
            api.get_certificate(tenant["id"], cert["id"], auditor_headers), 200)
        assert fetched["expiration_date"] == "2027-01-01"
        assert fetched["expiration_date"] != "2027-03-01", (
            "SIGNED_DATE anchoring must not use the effective date")


class TestApprovalSegregationPriority:
    def test_begin_review_by_uploader_violates_sod(self, api):
        """PRD §3.3: "the segregation rule of §2.9 applies, so an actor whose `X-User-ID` equals the current version's `uploaded_by_user_id` is rejected with `ERR_SOD_REVIEWER_IS_UPLOADER`."
        PRD §2.9: "The officer who moves a certificate into review, approves it, or rejects it must not be the officer who uploaded the certificate's current version."

        Design: Difficulty/priority_pair_validation_conflict/cert_approve_sod_vs_effective_date_priority
        """
        tenant = setup_tenant_config()
        cust = create_onboarded_customer(tid=tenant["id"])
        # Version is future-dated (2026-08-01 clock origin < 2099-01-01), but the
        # segregation rule fires on begin_review before any approve-time check exists.
        cert = create_certificate_draft(
            tenant["id"], cust["id"],
            signed_date="2026-01-01", effective_date="2099-01-01")
        upload_version(tenant["id"], cert["id"],
                       signed_date="2026-01-01", effective_date="2099-01-01")
        get_success_data(api.submit_certificate(
            tenant["id"], cert["id"], TEST_USERS["compliance_officer_headers"]))
        res = api.begin_review_certificate(
            tenant["id"], cert["id"], TEST_USERS["compliance_officer_headers"])
        validate_error(res, ApiErrorId.ERR_SOD_REVIEWER_IS_UPLOADER, expected_status=409)

    def test_approve_sod_fires_before_effective_date_check(self, api):
        """PRD §2.10: "Every request is evaluated against the checks below in exactly this order, and the first failing check determines the error response." (segregation reviewer-vs-uploader is check 7; the effective-date check is check 12.)
        PRD §3.3: "and finally the temporal check that the current version's `effective_date` is on or before today — today being the tenant logical clock of §2.4 — rejecting a future-dated certificate with `ERR_EFFECTIVE_DATE_IN_FUTURE` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/cert_approve_sod_vs_effective_date_priority
        """
        tenant = setup_tenant_config()
        cust = create_onboarded_customer(tid=tenant["id"])
        # UNDER_REVIEW reached via a distinct reviewer; approval is then attempted
        # by the uploader with a future-dated version, violating checks 7 and 12.
        cert = drive_certificate_to_under_review(
            tenant["id"], cust["id"],
            cert_overrides={"signed_date": "2026-01-01", "effective_date": "2099-01-01"},
            version_overrides={"signed_date": "2026-01-01", "effective_date": "2099-01-01"})
        cust_v = get_customer_version(tenant["id"], cust["id"])
        res = api.approve_certificate(
            tenant["id"], cert["id"], {"expected_customer_version": cust_v},
            TEST_USERS["compliance_officer_headers"])  # u_co1 == uploader
        validate_error(res, ApiErrorId.ERR_SOD_REVIEWER_IS_UPLOADER, expected_status=409)
