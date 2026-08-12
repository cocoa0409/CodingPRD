"""Custody segregation and destruction witness segregation tests."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_client_with_agreement, create_batch, create_box,
    create_shelf_slot, shelve_box, set_clock,
    batch_in_scanning, scan_and_commit, index_document, get_box,
    make_intake_clerk_headers, make_prep_technician_headers,
    make_scan_operator_headers, make_qa_reviewer_headers,
    make_destruction_specialist_headers, make_indexer_headers,
    CLERK, PREP, SCAN, QA, DS, IDX, WITNESS,
)


class TestCustodySegregationAdjacentActorRejected:
    """Corner: custody_segregation_adjacent_actor_rejected."""

    def test_same_user_adjacent_handoff_rejected_different_user_admitted(self, api):
        """PRD §3.3: "Chain-of-custody segregation is enforced on every
        explicit hand-off: the actor recording a custody event may not be the
        same user who authored the immediately preceding custody event on
        that box. Violations are rejected with `ERR_CUSTODY_SEGREGATION`
        (HTTP 422)."

        Design: Corner/calculations/custody_segregation_adjacent_actor_rejected
        """
        client, _ = create_client_with_agreement(name="Seg Co", hipaa_covered=False)
        slot = create_shelf_slot(shelf_code="SH-G1", zone="GENERAL", capacity_grams=2000)
        batch = create_batch(client["id"])
        box = create_box(batch["id"], box_label="BX-1", intake_weight_grams=600)
        # Auto-intake event recorded by clerk-1 at create_box, then STORAGE
        # link recorded by clerk-1 at shelf placement.
        shelve_box(box["id"], slot["id"])
        # Same user clerk-1 attempts the PREP hand-off: rejected.
        resp = api_client.create_custody_event(
            box["id"], {"to_stage": "PREP"}, make_prep_technician_headers(CLERK),
        )
        validate_error(resp, ApiErrorId.ERR_CUSTODY_SEGREGATION, expected_status=422)
        # Different user prep-1 retries: admitted.
        get_success_data(api_client.create_custody_event(
            box["id"], {"to_stage": "PREP"}, make_prep_technician_headers(PREP),
        ))
        box_after = get_box(box["id"])
        assert box_after["status"] == "IN_PREP"


class TestWitnessSegregationEqualIdsRejected:
    """Corner: witness_segregation_equal_ids_rejected."""

    def test_witness_equal_to_recorder_rejected(self, api):
        """PRD §3.7: "the witness must be a different bureau staffer than the
        recording actor — a `witness_user_id` equal to the actor's `X-User-ID`
        is rejected with `ERR_WITNESS_SEGREGATION` (HTTP 422)."

        Design: Corner/validations/witness_segregation_equal_ids_rejected
        """
        client, _ = create_client_with_agreement(
            name="Wit Co", hipaa_covered=False, retention_days=5,
        )
        slot = create_shelf_slot(shelf_code="SH-W", zone="GENERAL", capacity_grams=2000)
        ctx = batch_in_scanning(
            [{"doc_type": "CONTRACT", "pages": 100, "ocr_confidence": 95}],
            client_id=client["id"],
        )
        shelve_box(ctx["box"]["id"], slot["id"])
        scan_and_commit(ctx, [(ctx["documents"][0]["id"], 100)])
        get_success_data(api_client.submit_qa(ctx["batch"]["id"], make_scan_operator_headers(SCAN)))
        get_success_data(api_client.pass_qa(ctx["batch"]["id"], make_qa_reviewer_headers(QA)))
        get_success_data(index_document(ctx["documents"][0]["id"], title="T1", record_date="2026-01-01", subject="S1", ocr_text_ref="ocr://t1"))
        set_clock("2026-05-10T00:00:00Z")
        get_success_data(api_client.deliver_batch(ctx["batch"]["id"], make_qa_reviewer_headers(QA)))
        set_clock("2026-05-15T00:00:00Z")
        # Begin destruction with a DIFFERENT specialist (ds-2) so the custody
        # adjacency check (PRD §3.3, applied to certificate recording and
        # ordered before witness segregation per §2.8) does not fire — only the
        # witness-equals-actor rule is under test here.
        get_success_data(api_client.begin_destruction(ctx["box"]["id"], make_destruction_specialist_headers("ds-2")))

        # Witness equals the recording actor: rejected.
        resp = api_client.create_destruction_certificate(
            ctx["box"]["id"],
            {"witness_user_id": DS, "method": "SHRED"},
            make_destruction_specialist_headers(DS),
        )
        validate_error(resp, ApiErrorId.ERR_WITNESS_SEGREGATION, expected_status=422)
        box = get_box(ctx["box"]["id"])
        assert box["status"] == "IN_DESTRUCTION"
