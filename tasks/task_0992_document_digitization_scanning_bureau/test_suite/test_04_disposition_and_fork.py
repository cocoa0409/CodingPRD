"""Disposition sweep, return-vs-destroy fork, custody-flag cascade."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, validate_paginated,
    ApiErrorId,
    create_client_with_agreement, create_batch, create_box, create_document,
    create_scanner_unit, create_shelf_slot, shelve_box, set_clock,
    batch_in_scanning, scan_and_commit, index_document,
    get_box, get_shelf_slot, get_shelf_assignment, get_batch_version,
    make_platform_admin_headers, make_intake_clerk_headers,
    make_prep_technician_headers, make_scan_operator_headers,
    make_qa_reviewer_headers, make_indexer_headers,
    make_destruction_specialist_headers, make_compliance_officer_headers,
    make_client_user_headers, make_billing_clerk_headers,
    ADMIN, CLERK, PREP, SCAN, QA, IDX, DS, CO, BILL, WITNESS,
)


def _build_delivered_batch_with_shelved_boxes(
    box_weights=(600,), retention_days=5, deliver_at="2026-05-10T00:00:00Z",
):
    """Build a batch, shelve each box, run full pipeline to DELIVERED at
    deliver_at. Returns (client, ctx, slot, boxes)."""
    client, _ = create_client_with_agreement(
        name="Dispo Co", hipaa_covered=False,
        price_tier="STANDARD", rush_multiplier=1.75,
        storage_free_days=10, storage_daily_rate_cents=55,
        retention_days=retention_days, max_boxes_per_batch=5,
    )
    slot = create_shelf_slot(shelf_code="SH-D", zone="GENERAL", capacity_grams=4000)
    ctx = batch_in_scanning(
        [{"doc_type": "CONTRACT", "pages": 100, "ocr_confidence": 95}],
        client_id=client["id"],
    )
    # batch_in_scanning created one box; create additional boxes if needed
    boxes = [ctx["box"]]
    for i, w in enumerate(box_weights[1:], start=2):
        # Additional boxes can only be created while INTAKE; since we are past
        # that, rebuild path: instead build boxes BEFORE start_prep. To keep
        # this helper simple we only support a single box here.
        raise NotImplementedError("use _build_two_box_fork for two boxes")
    shelve_box(ctx["box"]["id"], slot["id"])
    specs = [(d["id"], d["pages"]) for d in ctx["documents"]]
    scan_and_commit(ctx, specs)
    get_success_data(api_client.submit_qa(ctx["batch"]["id"], make_scan_operator_headers(SCAN)))
    get_success_data(api_client.pass_qa(ctx["batch"]["id"], make_qa_reviewer_headers(QA)))
    get_success_data(index_document(ctx["documents"][0]["id"], title="T1", record_date="2026-01-01", subject="S1", ocr_text_ref="ocr://t1"))
    set_clock(deliver_at)
    get_success_data(api_client.deliver_batch(ctx["batch"]["id"], make_qa_reviewer_headers(QA)))
    return client, ctx, slot


def _build_two_box_fork(retention_days=5, deliver_at="2026-05-10T00:00:00Z"):
    """Two-box batch: boxA 600g (return branch), boxB 500g (destroy branch)."""
    client, _ = create_client_with_agreement(
        name="Fork Client", hipaa_covered=False,
        price_tier="STANDARD", rush_multiplier=1.75,
        storage_free_days=10, storage_daily_rate_cents=55,
        retention_days=retention_days, max_boxes_per_batch=5,
    )
    slot = create_shelf_slot(shelf_code="SH-G1", zone="GENERAL", capacity_grams=2000)
    batch = create_batch(client["id"])
    box_a = create_box(batch["id"], box_label="BX-A", intake_weight_grams=600)
    box_b = create_box(batch["id"], box_label="BX-B", intake_weight_grams=500)
    shelve_box(box_a["id"], slot["id"])
    shelve_box(box_b["id"], slot["id"])
    doc = create_document(box_a["id"], doc_type="CONTRACT", pages=100, ocr_confidence=95)
    # Advance batch to SCANNING
    get_success_data(api_client.start_prep(batch["id"], make_intake_clerk_headers(CLERK)))
    get_success_data(api_client.start_scan(batch["id"], make_scan_operator_headers(SCAN)))
    scanner = create_scanner_unit(scanner_code="SCN-1", capacity=500)
    ctx = {"client": client, "batch": batch, "scanner": scanner, "box": box_a, "documents": [doc]}
    scan_and_commit(ctx, [(doc["id"], 100)])
    get_success_data(api_client.submit_qa(batch["id"], make_scan_operator_headers(SCAN)))
    get_success_data(api_client.pass_qa(batch["id"], make_qa_reviewer_headers(QA)))
    get_success_data(index_document(doc["id"], title="T1", record_date="2026-01-01", subject="S1", ocr_text_ref="ocr://t1"))
    set_clock(deliver_at)
    get_success_data(api_client.deliver_batch(batch["id"], make_qa_reviewer_headers(QA)))
    return client, batch, slot, box_a, box_b, doc


# ---------------------------------------------------------------------------
# Queue A — Difficulty / non_linear_state_machine (box fork)
# ---------------------------------------------------------------------------

class TestBoxDispositionBranchForkReturnVsDestroy:
    """Two tests for Difficulty instance
    `box_disposition_branch_fork_return_vs_destroy`."""

    def test_return_branch_produces_return_event_no_certificate(self, api):
        """PRD §3.7: "an `IntakeClerk` marks the box returned, requiring
        `return_requested` set (else `ERR_BOX_NOT_RETURN_COMMITTED`, HTTP 409),
        moving the box to `RETURNED` and appending a `RETURN` custody link."

        Design: Difficulty/non_linear_state_machine/box_disposition_branch_fork_return_vs_destroy
        """
        client, batch, _slot, box_a, box_b, _doc = _build_two_box_fork()
        # Return branch on box A while batch DELIVERED.
        get_success_data(api_client.request_return(box_a["id"], make_client_user_headers(client["id"])))
        get_success_data(api_client.mark_returned(box_a["id"], make_intake_clerk_headers(CLERK)))
        box_a_after = get_box(box_a["id"])
        assert box_a_after["status"] == "RETURNED"
        assert box_a_after["return_requested"] is True

        # Custody trail contains a RETURN event and no DESTRUCTION event.
        events, _meta = validate_paginated(api_client.list_custody_events(box_a["id"], make_compliance_officer_headers(CO)))
        stages = [e["to_stage"] for e in events]
        assert "RETURN" in stages
        assert "DESTRUCTION" not in stages

        # No destruction certificate for box A.
        certs, _ = validate_paginated(api_client.get_box_destruction_certificates(box_a["id"], make_compliance_officer_headers(CO)))
        assert certs == []

    def test_destroy_branch_mints_certificate_and_closes_batch(self, api):
        """PRD §3.7: "On acceptance the box moves `IN_DESTRUCTION → DESTROYED`,
        the certificate is minted with a unique server-generated
        `certificate_code` and `destroyed_at` stamped from the clock."

        Design: Difficulty/non_linear_state_machine/box_disposition_branch_fork_return_vs_destroy
        """
        client, batch, _slot, box_a, box_b, _doc = _build_two_box_fork()
        # Return branch on A
        get_success_data(api_client.request_return(box_a["id"], make_client_user_headers(client["id"])))
        get_success_data(api_client.mark_returned(box_a["id"], make_intake_clerk_headers(CLERK)))

        # Advance clock past disposition_at -> box B swept to AWAITING_DISPOSITION
        set_clock("2026-05-15T00:00:00Z")
        box_b_now = get_box(box_b["id"])
        assert box_b_now["status"] == "AWAITING_DISPOSITION"

        # Destroy branch on B. PRD §3.3: the begin-destruction DESTRUCTION
        # link counts as the previous custody link, so the certificate must be
        # recorded by a different DestructionSpecialist (ds-2).
        get_success_data(api_client.begin_destruction(box_b["id"], make_destruction_specialist_headers(DS)))
        cert = get_success_data(api_client.create_destruction_certificate(
            box_b["id"],
            {"witness_user_id": WITNESS, "method": "SHRED"},
            make_destruction_specialist_headers("ds-2"),
        ))
        assert cert["method"] == "SHRED"
        # PRD §2.4: timestamps carry three fractional digits.
        assert cert["destroyed_at"] == "2026-05-15T00:00:00.000Z"
        assert cert["certificate_code"]

        box_b_after = get_box(box_b["id"])
        assert box_b_after["status"] == "DESTROYED"

        # Close the batch (all boxes final).
        get_success_data(api_client.close_batch(batch["id"], make_compliance_officer_headers(CO)))
        batch_after = get_success_data(api_client.get_batch(batch["id"], make_compliance_officer_headers(CO)))
        assert batch_after["status"] == "CLOSED"


# ---------------------------------------------------------------------------
# Queue A — Difficulty / transitive_cascade
# ---------------------------------------------------------------------------

class TestClockSweepCascadeBatchBoxShelf:
    """Two tests for Difficulty instance `clock_sweep_cascade_batch_box_shelf`."""

    def test_sweep_moves_batch_to_disposition_pending_and_boxes_awaiting(self, api):
        """PRD §3.7: "When the logical clock reaches a delivered batch's
        `disposition_at`, the batch automatically transitions `DELIVERED →
        DISPOSITION_PENDING`. Every box of the batch sitting in `STORED` or
        `SCAN_COMPLETE` moves to `AWAITING_DISPOSITION`."

        Design: Difficulty/transitive_cascade/clock_sweep_cascade_batch_box_shelf
        """
        client, ctx, _slot = _build_delivered_batch_with_shelved_boxes()
        # disposition_at = 2026-05-10 + 5d = 2026-05-15
        set_clock("2026-05-15T00:00:00Z")
        batch = get_success_data(api_client.get_batch(ctx["batch"]["id"], make_compliance_officer_headers(CO)))
        assert batch["status"] == "DISPOSITION_PENDING"
        box = get_box(ctx["box"]["id"])
        assert box["status"] == "AWAITING_DISPOSITION"

    def test_sweep_releases_shelf_assignment_and_debits_slot(self, api):
        """PRD §3.7: "every `ACTIVE` shelf assignment of those boxes is
        released with `released_at` stamped and the slot's occupied weight
        debited per box."

        Design: Difficulty/transitive_cascade/clock_sweep_cascade_batch_box_shelf
        """
        client, ctx, slot = _build_delivered_batch_with_shelved_boxes()
        # Snapshot the assignment id before sweep
        assignments, _ = validate_paginated(api_client.list_box_shelf_assignments(ctx["box"]["id"], make_intake_clerk_headers(CLERK)))
        assert len(assignments) == 1
        assignment_id = assignments[0]["id"]
        assert assignments[0]["status"] == "ACTIVE"

        set_clock("2026-05-15T00:00:00Z")
        asg = get_shelf_assignment(assignment_id)
        assert asg["status"] == "RELEASED"
        # PRD §2.4: timestamps carry three fractional digits.
        assert asg["released_at"] == "2026-05-15T00:00:00.000Z"
        slot_after = get_shelf_slot(slot["id"])
        assert slot_after["occupied_weight_grams"] == 0


# ---------------------------------------------------------------------------
# Queue B — Corner / errors
# ---------------------------------------------------------------------------

class TestReturnWindowExpiredAfterSweep:
    """Corner: error_return_window_expired_after_sweep."""

    def test_request_return_after_disposition_pending_rejected(self, api):
        """PRD §3.7: "The request is temporal — it must be recorded before the
        batch reaches `DISPOSITION_PENDING` or `CLOSED`, and a late request is
        rejected with `ERR_RETURN_WINDOW_EXPIRED` (HTTP 409)."

        Design: Corner/errors/error_return_window_expired_after_sweep
        """
        client, ctx, _slot = _build_delivered_batch_with_shelved_boxes()
        set_clock("2026-05-15T00:00:00Z")  # fires sweep
        resp = api_client.request_return(ctx["box"]["id"], make_client_user_headers(client["id"]))
        validate_error(resp, ApiErrorId.ERR_RETURN_WINDOW_EXPIRED, expected_status=409)
        box = get_box(ctx["box"]["id"])
        assert box["return_requested"] is False


class TestBranchExclusivityReturnCommittedVsNot:
    """Corner: error_branch_exclusivity_return_committed_vs_not."""

    def test_begin_destruction_on_return_committed_and_mark_returned_on_uncommitted(self, api):
        """PRD §3.7: "an `IntakeClerk` marks the box returned, requiring
        `return_requested` set (else `ERR_BOX_NOT_RETURN_COMMITTED`, HTTP 409),
        moving the box to `RETURNED` and appending a `RETURN` custody link; or
        a `DestructionSpecialist` begins destruction, requiring
        `return_requested` unset (else `ERR_BOX_RETURN_COMMITTED`, HTTP 409)."

        Design: Corner/errors/error_branch_exclusivity_return_committed_vs_not
        """
        client, batch, _slot, box_a, box_b, _doc = _build_two_box_fork()
        # Box A pinned to return while batch DELIVERED
        get_success_data(api_client.request_return(box_a["id"], make_client_user_headers(client["id"])))
        # Sweep: box B (STORED) -> AWAITING_DISPOSITION
        set_clock("2026-05-15T00:00:00Z")

        # Box A: begin-destruction must be rejected (return committed).
        resp_a = api_client.begin_destruction(box_a["id"], make_destruction_specialist_headers(DS))
        validate_error(resp_a, ApiErrorId.ERR_BOX_RETURN_COMMITTED, expected_status=409)

        # Box B: mark-returned must be rejected (return NOT requested).
        resp_b = api_client.mark_returned(box_b["id"], make_intake_clerk_headers(CLERK))
        validate_error(resp_b, ApiErrorId.ERR_BOX_NOT_RETURN_COMMITTED, expected_status=409)

        box_a_after = get_box(box_a["id"])
        box_b_after = get_box(box_b["id"])
        assert box_a_after["status"] == "AWAITING_DISPOSITION"
        assert box_b_after["status"] == "AWAITING_DISPOSITION"


class TestCustodyFlagBlocksAndComplianceClearReleases:
    """Corner: error_custody_flag_blocks_and_compliance_clear_releases."""

    def test_destruction_cascade_flags_sibling_boxes_compliance_clears(self, api):
        """PRD §3.7: "a client-wide cascade fires: every other non-final box —
        any box not yet `DESTROYED` or `RETURNED` — belonging to any
        non-`CLOSED` batch of the same client has its `custody_flagged`
        raised." PRD §3.7: "A flagged box is frozen mid-custody: custody
        hand-offs, begin-destruction, destruction-certificate recording, and
        shelf-assignment creation on it are all rejected with
        `ERR_CUSTODY_FLAGGED` (HTTP 409) until a `ComplianceOfficer` clears the
        flag through the clear-custody-flag action, restoring `custody_flagged`
        to false."

        Design: Corner/errors/error_custody_flag_blocks_and_compliance_clear_releases
        """
        # Build B1 fully destroyed, B2 still INTAKE with a STORED box.
        client, _ = create_client_with_agreement(
            name="Flag Co", hipaa_covered=False,
            price_tier="STANDARD", rush_multiplier=1.75,
            storage_free_days=10, storage_daily_rate_cents=55,
            retention_days=5, max_boxes_per_batch=5,
        )
        slot = create_shelf_slot(shelf_code="SH-F", zone="GENERAL", capacity_grams=4000)
        ctx1 = batch_in_scanning(
            [{"doc_type": "CONTRACT", "pages": 100, "ocr_confidence": 95}],
            client_id=client["id"],
        )
        shelve_box(ctx1["box"]["id"], slot["id"])
        specs = [(d["id"], d["pages"]) for d in ctx1["documents"]]
        scan_and_commit(ctx1, specs)
        get_success_data(api_client.submit_qa(ctx1["batch"]["id"], make_scan_operator_headers(SCAN)))
        get_success_data(api_client.pass_qa(ctx1["batch"]["id"], make_qa_reviewer_headers(QA)))
        get_success_data(index_document(ctx1["documents"][0]["id"], title="T1", record_date="2026-01-01", subject="S1", ocr_text_ref="ocr://t1"))
        set_clock("2026-05-10T00:00:00Z")
        get_success_data(api_client.deliver_batch(ctx1["batch"]["id"], make_qa_reviewer_headers(QA)))
        set_clock("2026-05-15T00:00:00Z")

        # B2 with a STORED box
        batch2 = create_batch(client["id"])
        box2 = create_box(batch2["id"], box_label="BX-2", intake_weight_grams=400)
        shelve_box(box2["id"], slot["id"])

        # Destroy box on B1 — triggers cascade flag on box2. The certificate
        # is recorded by a different DestructionSpecialist than begin-destruction
        # (PRD §3.3 custody adjacency applies to certificate recording).
        get_success_data(api_client.begin_destruction(ctx1["box"]["id"], make_destruction_specialist_headers(DS)))
        get_success_data(api_client.create_destruction_certificate(
            ctx1["box"]["id"],
            {"witness_user_id": WITNESS, "method": "SHRED"},
            make_destruction_specialist_headers("ds-2"),
        ))
        box2_flagged = get_box(box2["id"])
        assert box2_flagged["custody_flagged"] is True

        # Custody hand-off on flagged box is rejected.
        resp = api_client.create_custody_event(box2["id"], {"to_stage": "PREP"}, make_prep_technician_headers(PREP))
        validate_error(resp, ApiErrorId.ERR_CUSTODY_FLAGGED, expected_status=409)

        # Compliance clears; retry succeeds.
        get_success_data(api_client.clear_custody_flag(box2["id"], make_compliance_officer_headers(CO)))
        get_success_data(api_client.create_custody_event(box2["id"], {"to_stage": "PREP"}, make_prep_technician_headers(PREP)))
        box2_after = get_box(box2["id"])
        assert box2_after["status"] == "IN_PREP"
        assert box2_after["custody_flagged"] is False
