"""Medical certificates: half-open window overlap/adjacency, renewal limit,
and renewal state precondition."""
from test_helpers import (
    api_client, validate_success, validate_error,
    ApiErrorId, assert_date_eq, assert_certificate,
    create_account, create_certificate, set_clock, run_sweep,
    create_certificate_payload,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
CSR = TEST_USERS["csr_headers"]


class TestCertificateWindowOverlapHalfOpenAdjacency:
    def _account_with_c1(self, api):
        """Certificate C1 covering [2026-01-05, 2026-02-04); clock 2026-01-10."""
        account = create_account(service_address="61 Interval Ave")
        set_clock("2026-01-10T00:00:00Z")
        cert = create_certificate(account["id"], "2026-01-05",
                                  physician_name="Dr. C", physician_license_number="L-3")
        assert_date_eq(cert["effective_to"], "2026-02-04", "C1 effective_to")
        return account, cert

    def test_overlapping_window_rejected(self, api):
        """PRD §3.6: "Registration is rejected with `ERR_CERTIFICATE_WINDOW_OVERLAP`
        (HTTP 422) when an existing `ACTIVE` certificate on the same account
        overlaps the new window — overlap meaning the new start falls before the
        existing window's end and the existing start falls before the new window's
        end."

        Design: Difficulty/resource_temporal_overlap/certificate_window_overlap_half_open_adjacency
        """
        account, _c1 = self._account_with_c1(api)
        resp = api.create_certificate(
            create_certificate_payload(account["id"], "2026-01-20",
                                       physician_name="Dr. D",
                                       physician_license_number="L-4"), CSR)
        validate_error(resp, ApiErrorId.ERR_CERTIFICATE_WINDOW_OVERLAP)

    def test_adjacent_window_accepted(self, api):
        """PRD §3.6: "Because the windows are half-open, adjacency is not overlap:
        a new certificate starting exactly on the day an existing window ends is
        accepted."
        PRD §3.6: "The certificate is born `ACTIVE` with an `effective_to` exactly
        30 days after `effective_from`".

        Design: Difficulty/resource_temporal_overlap/certificate_window_overlap_half_open_adjacency
        """
        account, _c1 = self._account_with_c1(api)
        resp = api.create_certificate(
            create_certificate_payload(account["id"], "2026-02-04",
                                       physician_name="Dr. E",
                                       physician_license_number="L-5"), CSR)
        data = validate_success(resp, 201)
        assert_certificate(data)
        assert data["status"] == "ACTIVE"
        assert_date_eq(data["effective_to"], "2026-03-06", "effective_to")


def test_renewal_limit_reached(api):
    """PRD §3.6: "Certificates renew twice at most."
    PRD §3.6: "then requires `renewal_count` to still be below 2, with a third
    extension refused as `ERR_RENEWAL_LIMIT_REACHED` (HTTP 422)".
    PRD §3.6: "Each renewal extends `effective_to` by another 30 days and
    increments `renewal_count` by 1, so a certificate covers at most 90 days in
    total."

    Design: Corner/validations/renewal_limit_reached
    """
    account = create_account(service_address="46 Renew Rd")
    cert = create_certificate(account["id"], "2026-08-01",
                              physician_name="Dr. N", physician_license_number="L-7")
    # Born with effective_to exactly 30 days after effective_from (PRD §3.6):
    # 2026-08-01 -> 2026-08-31; each renewal adds another 30 days.
    first = validate_success(api.renew_certificate(cert["id"], CSR), 200)
    assert first["renewal_count"] == 1
    assert_date_eq(first["effective_to"], "2026-09-30", "effective_to after renewal 1")
    second = validate_success(api.renew_certificate(cert["id"], CSR), 200)
    assert second["renewal_count"] == 2
    assert_date_eq(second["effective_to"], "2026-10-30", "effective_to after renewal 2")
    resp = api.renew_certificate(cert["id"], CSR)
    validate_error(resp, ApiErrorId.ERR_RENEWAL_LIMIT_REACHED)
    stayed = validate_success(api.get_certificate(cert["id"], CSR), 200)
    assert stayed["renewal_count"] == 2
    assert_date_eq(stayed["effective_to"], "2026-10-30", "effective_to unchanged")


def test_certificate_not_renewable_after_expiry(api):
    """PRD §3.6: "Renewal by a `CustomerServiceRep` first requires the certificate
    to be `ACTIVE` — anything else fails with `ERR_CERTIFICATE_NOT_RENEWABLE`
    (HTTP 409)".
    PRD §3.6: "the daily sweep expires a certificate once the clock date reaches
    its `effective_to`, moving it to `EXPIRED`."

    Design: Corner/validations/certificate_not_renewable_after_expiry
    """
    account = create_account(service_address="47 Expired Exe")
    cert = create_certificate(account["id"], "2026-08-01",
                              physician_name="Dr. X", physician_license_number="L-8")
    set_clock("2026-09-05T00:00:00Z")  # window [2026-08-01, 2026-08-31) has passed
    sweep = run_sweep()
    assert sweep["certificates_expired"] == 1
    resp = api.renew_certificate(cert["id"], CSR)
    validate_error(resp, ApiErrorId.ERR_CERTIFICATE_NOT_RENEWABLE)
