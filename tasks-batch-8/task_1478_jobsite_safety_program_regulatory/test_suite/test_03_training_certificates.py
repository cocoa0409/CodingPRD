"""Training certificates: verification state gate, expiry at day granularity,
same-type window overlap, and the touching-renewal allowance (PRD §3.2, §2.12)."""
from test_helpers import (
    ApiErrorId, api_client,
    validate_error, validate_success,
    create_project, create_worker, create_certificate, verify_certificate,
    set_clock,
    make_safety_manager_headers, make_safety_inspector_headers,
    make_site_superintendent_headers,
)

SM = make_safety_manager_headers()
SS = make_site_superintendent_headers()
INSP1 = make_safety_inspector_headers("insp-1")
INSP2 = make_safety_inspector_headers("insp-2")


class TestCertificateVerification:

    def test_certificate_verify_twice_rejected(self, api):
        """PRD §3.2: "verification requires the certificate to still be
        `UNVERIFIED` (else `ERR_CERTIFICATE_INVALID_STATE`)"

        Design: Corner/state_machines/certificate_verify_twice_rejected
        """
        set_clock("2026-08-01T08:00:00Z")
        project = create_project(name="Central", annual_hours_worked=25000)
        worker = create_worker(project["id"], full_name="Q Russo")
        cert = create_certificate(worker["id"], cert_type="OSHA_10")
        verify_certificate(cert["id"], "insp-1")

        resp = api.verify_certificate(cert["id"], {}, INSP2)
        validate_error(resp, ApiErrorId.ERR_CERTIFICATE_INVALID_STATE)

    def test_expired_certificate_cannot_be_verified(self, api):
        """PRD §3.2: "verification requires the certificate to still be
        `UNVERIFIED` (else `ERR_CERTIFICATE_INVALID_STATE`) and requires that its
        expiry has not yet passed at end-of-day granularity (else
        `ERR_CERTIFICATE_EXPIRED`)"
        PRD §3.2: "Certificates begin `UNVERIFIED` with `verified_by_user_id` null."

        Design: Corner/validations/expired_certificate_cannot_be_verified
        """
        set_clock("2026-08-01T08:00:00Z")
        project = create_project(name="Montlake", annual_hours_worked=9000)
        worker = create_worker(project["id"], full_name="A Bly")
        # Registered while the logical clock is already past the expiry date;
        # no sweep has run since creation, so the record begins UNVERIFIED.
        cert = create_certificate(worker["id"], cert_type="OSHA_10",
                                  issued_date="2026-01-01", expires_date="2026-07-01")
        assert cert["status"] == "UNVERIFIED"

        resp = api.verify_certificate(cert["id"], {}, INSP1)
        validate_error(resp, ApiErrorId.ERR_CERTIFICATE_EXPIRED)

        after = validate_success(api.get_certificate(cert["id"], SM))
        assert after["status"] == "UNVERIFIED"


class TestCertificateWindows:

    def test_window_overlap_rejected_and_touching_renewal_allowed(self, api):
        """PRD §3.2: "one worker may not hold two certificates of the same
        `cert_type` whose date windows overlap while both are in any status other
        than `EXPIRED`; an overlapping registration is rejected with
        `ERR_CERTIFICATE_WINDOW_OVERLAP`."
        PRD §3.2: "a renewal whose `issued_date` is exactly the prior certificate's
        `expires_date` is allowed."

        Design: Corner/validations/certificate_window_overlap_and_touching_renewal
        """
        set_clock("2026-08-01T08:00:00Z")
        project = create_project(name="Laurelhurst", annual_hours_worked=12000)
        worker = create_worker(project["id"], full_name="Z Ahmed")
        cert1 = create_certificate(worker["id"], cert_type="OSHA_10",
                                   issued_date="2026-01-01", expires_date="2027-01-01")
        assert cert1["status"] == "UNVERIFIED"

        # Overlapping window [2026-06-01, 2026-12-01] vs [2026-01-01, 2027-01-01].
        resp_overlap = api.create_certificate(
            {"worker_id": worker["id"], "cert_type": "OSHA_10",
             "issued_date": "2026-06-01", "expires_date": "2026-12-01"},
            SS,
        )
        validate_error(resp_overlap, ApiErrorId.ERR_CERTIFICATE_WINDOW_OVERLAP)

        # Renewal starting exactly on the prior expires_date is allowed.
        resp_renewal = api.create_certificate(
            {"worker_id": worker["id"], "cert_type": "OSHA_10",
             "issued_date": "2027-01-01", "expires_date": "2028-01-01"},
            SS,
        )
        renewal = validate_success(resp_renewal, 201)
        assert renewal["status"] == "UNVERIFIED"

    def test_certificate_expires_at_end_of_expiry_day(self, api):
        """PRD §2.12: "certificate expiry is evaluated at day granularity: a
        certificate remains valid through the end of its `expires_date` — that is,
        while the current time is at or before 23:59:59 UTC on that date."
        PRD §2.5: "training certificates whose expiry has passed flip to `EXPIRED`
        from either `UNVERIFIED` or `VERIFIED`"

        Design: Corner/calculations/certificate_expiry_day_granularity
        """
        set_clock("2026-08-01T08:00:00Z")
        project = create_project(name="Madrona", annual_hours_worked=18000)
        worker = create_worker(project["id"], full_name="U Vargas")
        cert = create_certificate(worker["id"], cert_type="OSHA_10",
                                  issued_date="2026-07-01", expires_date="2026-08-10")
        verify_certificate(cert["id"], "insp-1")

        # Noon on the expiry date: still within the inclusive expiry day.
        set_clock("2026-08-10T12:00:00Z")
        mid = validate_success(api.get_certificate(cert["id"], SM))
        assert mid["status"] == "VERIFIED", (
            f"cert must remain VERIFIED through its expiry day, got {mid['status']}"
        )

        # The following day the expiry has fully passed: sweep flips to EXPIRED.
        set_clock("2026-08-11T00:00:00Z")
        end = validate_success(api.get_certificate(cert["id"], SM))
        assert end["status"] == "EXPIRED"
