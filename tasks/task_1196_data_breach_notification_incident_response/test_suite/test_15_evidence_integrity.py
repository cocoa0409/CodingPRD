"""Evidence hash validation (corner design — entities section)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_evidence_item_payload,
    create_forensic_scope_payload,
    create_incident,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)

IC = TEST_USERS["incident_commander_headers"]
FL = TEST_USERS["forensic_lead_headers"]


class TestEvidenceHashFormat:
    def test_seal_with_malformed_hash_rejected(self, api):
        """PRD §3.2: "Sealing the item requires the `preservation_hash` to be
        present and well-formed as 64 lowercase hexadecimal characters". PRD
        §2.7 step 7 assigns this check to `ERR_CUSTODY_OVERLAP` (409); §5
        catalogues `ERR_INVALID_REQUEST` (422) for schema validation failure.
        Either error_id is a faithful surface of the malformed-hash rule.

        Design: Corner/entities/evidence_item_invalid_hash_rejected
        """
        inc = create_incident()
        scope_resp = api.create_forensic_scope(
            inc["id"], create_forensic_scope_payload(), FL
        )
        scope = validate_success(scope_resp, expected_status=201)
        api.baseline_forensic_scope(inc["id"], scope["id"], FL)
        ev_resp = api.create_evidence_item(
            inc["id"],
            create_evidence_item_payload(preservation_hash="xyz"),
            FL,
        )
        ev = validate_success(ev_resp, expected_status=201)
        seal_resp = api.seal_evidence_item(inc["id"], ev["id"], FL)
        validate_error_is_one_of(
            seal_resp,
            [
                ApiErrorId.ERR_CUSTODY_OVERLAP.value,
                ApiErrorId.ERR_INVALID_REQUEST.value,
            ],
        )
