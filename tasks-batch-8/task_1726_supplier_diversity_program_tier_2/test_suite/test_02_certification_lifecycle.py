"""Certification review state machine: SoD, temporal windows, overlap,
resubmission cycle, expiration sweep, and review-state lockdown."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_supplier,
    get_success_data,
    resubmit_certification_payload,
    set_clock,
    submit_certification,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN1 = TEST_USERS["admin_1_headers"]
ADMIN2 = TEST_USERS["admin_2_headers"]
ANALYST1 = TEST_USERS["analyst_1_headers"]
ANALYST2 = TEST_USERS["analyst_2_headers"]


def _under_review_cert(api, supplier_id, **kwargs):
    """Submit a certification and move it to UNDER_REVIEW."""
    cert = submit_certification(supplier_id, **kwargs)
    get_success_data(api.begin_review_certification(cert["id"], ANALYST1))
    return cert


class TestVerificationGuards:
    def test_certification_verify_own_submission_returns_sod_violation(
            self, api):
        """PRD §3.2: "Segregation of duties requires the caller's `X-User-ID`
        to differ from `submitted_by_user_id`; a match is
        `ERR_SOD_VIOLATION`."

        Design: Corner/validations/certification_verify_own_submission_returns_sod_violation
        """
        supplier = create_supplier(legal_name="SoD Co", tax_id="T-SOD")
        cert = _under_review_cert(api, supplier["id"], cert_type="VET",
                                  certificate_number="V-SOD")
        resp = api.verify_certification(cert["id"], ANALYST1)
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)
        certs, _meta = validate_paginated(
            api.list_certifications(supplier["id"], ADMIN1))
        assert certs[0]["status"] == "UNDER_REVIEW", (
            "The SoD-rejected verify leaves the certification UNDER_REVIEW"
        )

    def test_certification_verify_expired_window_returns_temporal_error(
            self, api):
        """PRD §3.2: "The window must not already be expired: `valid_to` must
        be on or after the current logical-clock date, otherwise
        `ERR_CERT_WINDOW_EXPIRED`."

        Design: Corner/validations/certification_verify_expired_window_returns_temporal_error
        """
        supplier = create_supplier(legal_name="Expired Co", tax_id="T-EXP")
        # valid_to 2026-07-01 is before the startup clock date 2026-08-01.
        cert = _under_review_cert(api, supplier["id"], cert_type="SDVET",
                                  certificate_number="V-EXP",
                                  valid_from="2026-01-01",
                                  valid_to="2026-07-01")
        resp = api.verify_certification(cert["id"], ADMIN1)
        validate_error(resp, ApiErrorId.ERR_CERT_WINDOW_EXPIRED)

    def test_certification_reject_terminal_lockdown(self, api):
        """PRD §3.2: "Any review action attempted from a state where that
        action is not defined — verifying an `EXPIRED`, `REVOKED`, or
        `REJECTED` certification, for example — is rejected with
        `ERR_CERT_NOT_REVIEWABLE`, a specialization of the generic state
        check."

        Design: Corner/state_machines/certification_reject_terminal_lockdown
        """
        supplier = create_supplier(legal_name="Rej Co", tax_id="T-REJ")
        cert = _under_review_cert(api, supplier["id"], cert_type="DOBE",
                                  certificate_number="D-1")
        rejected = validate_success(
            api.reject_certification(cert["id"], "illegible document", ADMIN1))
        assert rejected["status"] == "REJECTED"
        resp = api.verify_certification(cert["id"], ADMIN2)
        validate_error(resp, ApiErrorId.ERR_CERT_NOT_REVIEWABLE)
        certs, _meta = validate_paginated(
            api.list_certifications(supplier["id"], ADMIN1))
        assert certs[0]["status"] == "REJECTED", (
            "The certification stays terminally REJECTED"
        )


class TestInfoRequestResubmissionCycle:
    def test_certification_resubmission_cycle_reanchors_submitter(self, api):
        """PRD §3.2: "From `INFO_REQUESTED` the certification can be
        resubmitted with corrected `certificate_number`, `valid_from`, and
        `valid_to`, which moves it back to `SUBMITTED` and re-stamps
        `submitted_by_user_id` with the resubmitting caller."

        Design: Difficulty/non_linear_state_machine/certification_info_request_resubmission_cycle
        """
        supplier = create_supplier(legal_name="Cycle Co", tax_id="T-C1")
        cert = submit_certification(supplier["id"], cert_type="WBE",
                                    certificate_number="C-100")
        under_review = validate_success(
            api.begin_review_certification(cert["id"], ANALYST1))
        assert under_review["status"] == "UNDER_REVIEW"
        info = validate_success(api.request_info_certification(
            cert["id"], "certificate number illegible", ANALYST1))
        assert info["status"] == "INFO_REQUESTED"
        assert info.get("review_note") == "certificate number illegible"
        resubmitted = validate_success(api.resubmit_certification(
            cert["id"],
            resubmit_certification_payload(certificate_number="C-100-R"),
            ANALYST2))
        assert resubmitted["status"] == "SUBMITTED", (
            "The cycle SUBMITTED -> UNDER_REVIEW -> INFO_REQUESTED -> "
            "SUBMITTED is defined"
        )
        assert resubmitted["submitted_by_user_id"] == "analyst-2", (
            "Resubmission re-anchors submitted_by_user_id to the resubmitter"
        )
        assert resubmitted["certificate_number"] == "C-100-R", (
            "Resubmission replaces certificate_number"
        )

    def test_certification_cycle_verify_against_resubmitter_succeeds(
            self, api):
        """PRD §3.2: "Segregation of duties requires the caller's `X-User-ID`
        to differ from `submitted_by_user_id`; a match is
        `ERR_SOD_VIOLATION`."
        PRD §3.2: "If the supplier was `REGISTERED`, it becomes `ACTIVE` on
        its first verified certification."

        Design: Difficulty/non_linear_state_machine/certification_info_request_resubmission_cycle
        """
        supplier = create_supplier(legal_name="Cycle Co", tax_id="T-C1")
        cert = submit_certification(supplier["id"], cert_type="WBE",
                                    certificate_number="C-100")
        get_success_data(api.begin_review_certification(cert["id"], ANALYST1))
        get_success_data(api.request_info_certification(
            cert["id"], "certificate number illegible", ANALYST1))
        get_success_data(api.resubmit_certification(
            cert["id"],
            resubmit_certification_payload(certificate_number="C-100-R"),
            ANALYST2))
        get_success_data(api.begin_review_certification(cert["id"], ANALYST1))
        # admin-1 != analyst-2 (the resubmitter): SoD passes.
        verified = validate_success(
            api.verify_certification(cert["id"], ADMIN1))
        assert verified["status"] == "VERIFIED"
        assert verified["certificate_number"] == "C-100-R"
        assert verified["verified_by_user_id"] == "admin-1"
        stored = validate_success(api.get_supplier(supplier["id"], ADMIN1))
        assert stored["status"] == "ACTIVE", (
            "First verified certification activates the supplier"
        )


class TestClosedWindowOverlap:
    def test_certification_window_overlap_shared_boundary_day_rejected(
            self, api):
        """PRD §3.2: "the supplier must not already hold another certification
        of the same `cert_type` in `VERIFIED` or `EXPIRED` whose closed
        validity window overlaps the new one — because the windows are closed,
        sharing a single boundary day counts as overlap — otherwise
        `ERR_CERT_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/certification_closed_window_boundary_overlap
        """
        supplier = create_supplier(legal_name="Overlap Co", tax_id="T-OVL")
        # Existing VERIFIED window [2026-01-01, 2026-11-15] (verifiable at the
        # startup clock date 2026-08-01).
        c1 = _under_review_cert(api, supplier["id"], certificate_number="M-1",
                                valid_from="2026-01-01", valid_to="2026-11-15")
        get_success_data(api.verify_certification(c1["id"], ADMIN1))
        # Candidate window shares the boundary day 2026-11-15.
        c2 = _under_review_cert(api, supplier["id"], certificate_number="M-2",
                                valid_from="2026-11-15", valid_to="2027-06-30")
        resp = api.verify_certification(c2["id"], ADMIN1)
        validate_error(resp, ApiErrorId.ERR_CERT_WINDOW_OVERLAP)
        certs, _meta = validate_paginated(
            api.list_certifications(supplier["id"], ADMIN1))
        c2_stored = [c for c in certs if c["id"] == c2["id"]][0]
        assert c2_stored["status"] == "UNDER_REVIEW", (
            "The overlap-rejected certification stays UNDER_REVIEW"
        )

    def test_certification_window_day_after_boundary_accepted(self, api):
        """PRD §3.2: "the supplier must not already hold another certification
        of the same `cert_type` in `VERIFIED` or `EXPIRED` whose closed
        validity window overlaps the new one — because the windows are closed,
        sharing a single boundary day counts as overlap — otherwise
        `ERR_CERT_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/certification_closed_window_boundary_overlap
        """
        supplier = create_supplier(legal_name="Overlap Co", tax_id="T-OVL")
        c1 = _under_review_cert(api, supplier["id"], certificate_number="M-1",
                                valid_from="2026-01-01", valid_to="2026-11-15")
        get_success_data(api.verify_certification(c1["id"], ADMIN1))
        # Candidate starts the day after the existing window ends: no shared
        # day under closed-interval semantics, so verification succeeds.
        c3 = _under_review_cert(api, supplier["id"], certificate_number="M-3",
                                valid_from="2026-11-16", valid_to="2027-06-30")
        verified = validate_success(
            api.verify_certification(c3["id"], ADMIN1))
        assert verified["status"] == "VERIFIED"


class TestExpirationSweepAndStatePriority:
    def test_expired_cert_verify_returns_state_error_not_temporal(self, api):
        """PRD §3.2: "the certification must, however, be in `UNDER_REVIEW`
        first or the state-tier check fires `ERR_CERT_NOT_REVIEWABLE` before
        any of these."

        Design: Difficulty/priority_pair_validation_conflict/verify_expired_cert_state_error_beats_temporal
        """
        supplier = create_supplier(legal_name="Old Cert Co", tax_id="T-OLD")
        # Verified at the startup clock date 2026-08-01 (valid_to on or after
        # the clock date passes the temporal check).
        cert = _under_review_cert(api, supplier["id"], certificate_number="M-OLD",
                                  valid_from="2026-01-01", valid_to="2026-11-15")
        verified = validate_success(
            api.verify_certification(cert["id"], ADMIN1))
        assert verified["status"] == "VERIFIED"
        # Advancing past valid_to expires the certification; now BOTH the
        # state failure (EXPIRED is not reviewable) and the temporal failure
        # (valid_to before the clock date) hold.
        set_clock("2026-11-16T00:00:00Z")
        resp = api.verify_certification(cert["id"], ADMIN1)
        validate_error(resp, ApiErrorId.ERR_CERT_NOT_REVIEWABLE)

    def test_expiration_sweep_moves_verified_to_expired_after_valid_to(
            self, api):
        """PRD §3.5: "if its `valid_to` is strictly before the new clock date
        it becomes `EXPIRED`; if `valid_to` equals the new clock date it
        remains `VERIFIED`, because the validity window is closed and the
        boundary day is covered."

        Design: Difficulty/priority_pair_validation_conflict/verify_expired_cert_state_error_beats_temporal
        """
        supplier = create_supplier(legal_name="Old Cert Co", tax_id="T-OLD")
        cert = _under_review_cert(api, supplier["id"], certificate_number="M-OLD",
                                  valid_from="2026-01-01", valid_to="2026-11-15")
        verified = validate_success(
            api.verify_certification(cert["id"], ADMIN1))
        assert verified["status"] == "VERIFIED"
        set_clock("2026-11-16T00:00:00Z")
        certs, _meta = validate_paginated(
            api.list_certifications(supplier["id"], ADMIN1))
        assert certs[0]["status"] == "EXPIRED", (
            "valid_to strictly before the new clock date expires the cert"
        )

    def test_certification_expiration_sweep_boundary(self, api):
        """PRD §3.5: "if its `valid_to` is strictly before the new clock date
        it becomes `EXPIRED`; if `valid_to` equals the new clock date it
        remains `VERIFIED`, because the validity window is closed and the
        boundary day is covered."

        Design: Corner/calculations/certification_expiration_sweep_boundary
        """
        supplier = create_supplier(legal_name="Sweep Co", tax_id="T-SWP")
        cert = _under_review_cert(api, supplier["id"], certificate_number="M-SWP",
                                  valid_from="2026-01-01", valid_to="2026-11-15")
        get_success_data(api.verify_certification(cert["id"], ADMIN1))
        # On the valid_to day itself the certification stays VERIFIED.
        set_clock("2026-11-15T12:00:00Z")
        certs, _meta = validate_paginated(
            api.list_certifications(supplier["id"], ADMIN1))
        assert certs[0]["status"] == "VERIFIED", (
            "The boundary day is covered (closed window)"
        )
        # One day further, valid_to is strictly before the clock date.
        set_clock("2026-11-16T00:00:00Z")
        certs, _meta = validate_paginated(
            api.list_certifications(supplier["id"], ADMIN1))
        assert certs[0]["status"] == "EXPIRED"
