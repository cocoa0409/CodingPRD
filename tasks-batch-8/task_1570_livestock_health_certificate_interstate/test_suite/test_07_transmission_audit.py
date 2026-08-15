"""Electronic transmission and the append-only audit trail (PRD §2.10, §3.8)."""
from test_helpers import (
    ApiErrorId,
    assert_transmission_audit,
    create_issued_certificate,
    get_certificate,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestTransmissionFailureAppendOnly:
    def test_transmission_failure_keeps_certificate_issued_append_only(
        self, api, admin_headers, officer_headers, auditor_headers
    ):
        """PRD §3.8: "Recording a failure instead moves the audit from `QUEUED`
        to `FAILED` and stores the request's `failure_reason` on the row (the
        field is null otherwise); the certificate stays `ISSUED`, and a later
        transmission simply appends a fresh `QUEUED` row."
        PRD §3.8: "Acting on an audit that is no longer `QUEUED` — either way —
        yields `ERR_TRANSMISSION_NOT_ADVANCEABLE` (HTTP 409)".
        PRD §3.8: "The row is born `QUEUED`, and the trail is append-only —
        old rows are never rewritten."

        Design: Corner/state_machines/transmission_failure_keeps_certificate_issued_append_only
        """
        scenario, cert = create_issued_certificate()

        audit1 = validate_success(
            api.transmit_certificate(cert["id"], {"channel": "XML_GATEWAY"}, officer_headers),
            201,
        )
        failed = validate_success(
            api.fail_transmission(audit1["id"], {"failure_reason": "GATEWAY_TIMEOUT"}, officer_headers),
            200,
        )
        assert_transmission_audit(failed)
        assert failed["status"] == "FAILED"
        assert failed["failure_reason"] == "GATEWAY_TIMEOUT"

        # The failure does not move the certificate.
        assert get_certificate(cert["id"])["status"] == "ISSUED"

        # The FAILED row is terminally locked.
        validate_error(
            api.acknowledge_transmission(audit1["id"], officer_headers),
            ApiErrorId.ERR_TRANSMISSION_NOT_ADVANCEABLE,
        )

        # Re-transmission appends a SECOND QUEUED row; the trail keeps both.
        audit2 = validate_success(
            api.transmit_certificate(cert["id"], {"channel": "EMAIL"}, officer_headers),
            201,
        )
        assert audit2["status"] == "QUEUED"
        assert audit2["id"] != audit1["id"]

        trail, meta = validate_paginated(
            api.list_transmissions_for_certificate(cert["id"], auditor_headers)
        )
        assert meta["total_count"] == 2, "append-only trail keeps both rows"
        statuses = {row["id"]: row["status"] for row in trail}
        assert statuses[audit1["id"]] == "FAILED", "old rows are never rewritten"
        assert statuses[audit2["id"]] == "QUEUED"
