"""Document records: retention computation, purge gate, soft delete
(PRD §3.9)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
    ApiErrorId,
)
from test_helpers.fixtures import CO, HA, READER, set_clock
from test_helpers.factories import create_document_record_payload

CO_H = TEST_USERS["compliance_officer_headers"]
HA_H = TEST_USERS["holder_admin_headers"]


class TestRetentionComputation:
    def test_retention_until_computed_per_artifact_type(self, api):
        """PRD §3.9: "Registration computes the `retention_until` as the
        creation date plus the retention years for the artifact type — five
        years for `LETTER_COPY`, seven for `CLAIM_EVIDENCE`, ten for
        `REPORT_FILE`, and ten for `REMITTANCE_RECEIPT` — and the record begins
        `REGISTERED` with `purged_at` null."
        PRD §2.5: "Before any explicit adjustment, the logical clock reads
        exactly `2026-08-01T00:00:00Z`."

        Design: Corner/entities/document_record_retention_until_computed
        """
        cases = [
            ("LETTER_COPY", "DueDiligenceLetter", "2031-08-01"),
            ("REPORT_FILE", "HolderReport", "2036-08-01"),
            ("CLAIM_EVIDENCE", "OwnerClaim", "2033-08-01"),
            ("REMITTANCE_RECEIPT", "Remittance", "2036-08-01"),
        ]
        for artifact_type, related_type, expected_until in cases:
            record = validate_success(
                api.create_document_record(
                    create_document_record_payload(
                        artifact_type=artifact_type,
                        related_entity_type=related_type,
                        related_entity_id=NON_EXISTENT_UUID,
                    ),
                    CO_H,
                ),
                201,
            )
            assert record["retention_until"] == expected_until, (
                f"{artifact_type}: expected {expected_until}, "
                f"got {record['retention_until']}"
            )
            assert record["status"] == "REGISTERED"
            assert record["purged_at"] is None


class TestPurgeGate:
    def test_purge_boundary_and_second_purge(self, api):
        """PRD §3.9: "A `HolderAdmin` purges a record that is still
        `REGISTERED` — a second purge is refused with
        `ERR_DOCUMENT_ALREADY_PURGED` — and only once the logical clock date
        has reached the `retention_until`: an earlier attempt is refused with
        `ERR_RETENTION_PERIOD_NOT_ELAPSED`, while a purge landing exactly on
        the `retention_until` date is allowed."

        Design: Corner/errors/retention_purge_boundary
        """
        record = get_success_data(
            api.create_document_record(
                create_document_record_payload(
                    artifact_type="REPORT_FILE",
                    related_entity_type="HolderReport",
                    related_entity_id=NON_EXISTENT_UUID,
                ),
                CO_H,
            ),
            201,
        )
        assert record["retention_until"] == "2036-08-01"
        set_clock("2036-07-31T00:00:00Z")
        early = api.purge_document_record(record["id"], HA_H)
        validate_error(early, ApiErrorId.ERR_RETENTION_PERIOD_NOT_ELAPSED, 409)
        set_clock("2036-08-01T00:00:00Z")  # exactly on retention_until
        purged = get_success_data(api.purge_document_record(record["id"], HA_H), 200)
        assert purged["status"] == "PURGED"
        assert purged["purged_at"] is not None
        again = api.purge_document_record(record["id"], HA_H)
        validate_error(again, ApiErrorId.ERR_DOCUMENT_ALREADY_PURGED, 409)


class TestPurgedVisibility:
    def test_purged_records_hidden_from_default_listing(self, api):
        """PRD §3.9: "The purge is a soft delete: purged records disappear from
        the document listing unless the caller passes `include_purged` set to
        true, and they remain readable by their `id`."

        Design: Corner/endpoints/document_list_excludes_purged_by_default
        """
        record = get_success_data(
            api.create_document_record(
                create_document_record_payload(
                    artifact_type="CLAIM_EVIDENCE",
                    related_entity_type="OwnerClaim",
                    related_entity_id=NON_EXISTENT_UUID,
                ),
                CO_H,
            ),
            201,
        )
        set_clock("2033-08-01T00:00:00Z")  # retention_until for CLAIM_EVIDENCE
        get_success_data(api.purge_document_record(record["id"], HA_H), 200)
        _, meta_default = validate_paginated(api.list_document_records(READER))
        assert meta_default["total_count"] == 0
        data_inc, meta_inc = validate_paginated(
            api.list_document_records(READER, params={"include_purged": "true"})
        )
        assert meta_inc["total_count"] == 1
        assert data_inc[0]["status"] == "PURGED"
        assert data_inc[0]["purged_at"] is not None
        by_id = get_success_data(api.get_document_record(record["id"], READER), 200)
        assert by_id["status"] == "PURGED"
