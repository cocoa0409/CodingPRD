"""List endpoints, pagination envelope, filters, and reverse-FK traceback
reads (PRD §2.2, §2.3, §3.2, §3.4, §3.5, §3.7, §3.8)."""
from test_helpers import (
    create_draft_certificate,
    create_premises,
    create_scheduled_record,
    create_veterinarian,
    setup_issued_certificate_with_permit,
    validate_paginated,
    validate_success,
)


class TestCertificateListFilters:
    def test_certificate_list_filters_pagination_envelope(
        self, api, admin_headers, auditor_headers
    ):
        """PRD §3.4: "Certificates are listed with filters supporting
        traceback: `vet_id`, `origin_premises_id`, `test_record_id`, `status`,
        and `destination_state_code`, alongside `limit` and `offset`."
        PRD §2.3: "`limit` defaults to 10, must be at least 1, and may not
        exceed 100. `offset` defaults to 0. List responses are sorted by
        `created_at` ascending, and the `meta` block of a list response carries
        the pagination fields `limit`, `offset`, `total_count`, and `has_more`".
        PRD §2.2: "The `response_type` is either "object" for a single resource
        or "array" for a list of resources."

        Design: Corner/entities/certificate_list_filters_pagination_envelope
        """
        premises = create_premises(name="Ranch D16", initial_head_count=40)
        vet = create_veterinarian()
        # Clock at the startup default, so inspection 2026-08-01 is legal.
        cert_ks = create_draft_certificate(
            premises["id"], vet["id"], head_count=5,
            destination_state_code="KS", inspection_date="2026-08-01T00:00:00Z",
        )
        cert_tx = create_draft_certificate(
            premises["id"], vet["id"], head_count=5,
            destination_state_code="TX", inspection_date="2026-08-01T00:00:00Z",
        )

        data, meta = validate_paginated(
            api.list_certificates(auditor_headers, params={"origin_premises_id": premises["id"]})
        )
        assert meta["total_count"] == 2 and meta["has_more"] is False

        page0, meta0 = validate_paginated(
            api.list_certificates(
                auditor_headers,
                params={"origin_premises_id": premises["id"], "limit": 1, "offset": 0},
            )
        )
        assert len(page0) == 1 and meta0["total_count"] == 2 and meta0["has_more"] is True

        page1, meta1 = validate_paginated(
            api.list_certificates(
                auditor_headers,
                params={"origin_premises_id": premises["id"], "limit": 1, "offset": 1},
            )
        )
        assert len(page1) == 1 and meta1["total_count"] == 2 and meta1["has_more"] is False
        assert page0[0]["id"] != page1[0]["id"], "pages must be disjoint"

        filtered, meta_f = validate_paginated(
            api.list_certificates(
                auditor_headers,
                params={"destination_state_code": "TX", "vet_id": vet["id"]},
            )
        )
        assert meta_f["total_count"] == 1
        assert filtered[0]["id"] == cert_tx["id"]
        assert filtered[0]["id"] != cert_ks["id"]


class TestTracebackReverseReachability:
    def test_traceback_reverse_reachability_lists(
        self, api, admin_headers, officer_headers, auditor_headers
    ):
        """PRD §3.2: "the test-records listing under a premises supports the
        usual `limit` and `offset` pagination."
        PRD §3.4: "Certificates are listed with filters supporting traceback:
        `vet_id`, `origin_premises_id`, `test_record_id`, `status`, and
        `destination_state_code`, alongside `limit` and `offset`."
        PRD §3.5: "Permits attached to a certificate, and movement records
        under a permit, are both listable with `limit` and `offset`".
        PRD §3.7: "Quarantine orders for a premises are listable with `limit`
        and `offset`."
        PRD §3.8: "The full audit trail for a certificate is listable by all
        roles with `limit` and `offset`".

        Design: Corner/entities/traceback_reverse_reachability_lists
        """
        # Full chain: NEGATIVE test -> ISSUED certificate -> ISSUED permit ->
        # SCHEDULED record -> QUEUED transmission.
        scenario, cert, permit = setup_issued_certificate_with_permit(
            allocation=10, none_matrix=False
        )
        record = create_scheduled_record(permit["id"], scenario["vet"]["id"], head_count=4)
        audit = validate_success(
            api.transmit_certificate(cert["id"], {"channel": "XML_GATEWAY"}, officer_headers),
            201,
        )

        tests, meta_t = validate_paginated(
            api.list_test_records_for_premises(scenario["premises"]["id"], auditor_headers)
        )
        assert [t["id"] for t in tests] == [scenario["test"]["id"]]

        permits, meta_p = validate_paginated(
            api.list_permits_for_certificate(cert["id"], auditor_headers)
        )
        assert [p["id"] for p in permits] == [permit["id"]]

        records, meta_r = validate_paginated(
            api.list_movement_records_for_permit(permit["id"], auditor_headers)
        )
        assert [r["id"] for r in records] == [record["id"]]

        audits, meta_a = validate_paginated(
            api.list_transmissions_for_certificate(cert["id"], auditor_headers)
        )
        assert [a["id"] for a in audits] == [audit["id"]]
        assert audits[0]["status"] == "QUEUED"

        orders, meta_q = validate_paginated(
            api.list_quarantine_orders_for_premises(scenario["premises"]["id"], auditor_headers)
        )
        assert meta_q["total_count"] == 0 and orders == []

        certs, meta_c = validate_paginated(
            api.list_certificates(
                auditor_headers, params={"test_record_id": scenario["test"]["id"]}
            )
        )
        assert [c["id"] for c in certs] == [cert["id"]], "traceback by test record"
