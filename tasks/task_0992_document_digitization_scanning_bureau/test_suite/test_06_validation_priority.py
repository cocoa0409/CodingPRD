"""Validation priority ordering tests."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_client, create_client_with_agreement, create_batch, create_box,
    create_document, create_shelf_slot, shelve_box, set_clock,
    batch_in_scanning, scan_and_commit, index_document,
    batch_in_intake,
    get_box, get_shelf_slot,
    make_platform_admin_headers, make_intake_clerk_headers,
    make_destruction_specialist_headers, make_compliance_officer_headers,
    make_scan_operator_headers, make_qa_reviewer_headers,
    ADMIN, CLERK, DS, CO, WITNESS, SCAN, QA,
    NON_EXISTENT_UUID,
)


# ---------------------------------------------------------------------------
# Queue A — Difficulty / priority_pair_validation_conflict
# ---------------------------------------------------------------------------

class TestStatePreconditionBeatsWitnessSegregation:
    """Two tests for Difficulty instance
    `state_precondition_beats_witness_segregation`."""

    def _setup_awaiting_disposition_box(self):
        """Delivered batch swept at 2026-05-15 -> box AWAITING_DISPOSITION."""
        client, _ = create_client_with_agreement(
            name="Prio One", hipaa_covered=False,
            price_tier="STANDARD", rush_multiplier=1.75,
            storage_free_days=10, storage_daily_rate_cents=55,
            retention_days=5, max_boxes_per_batch=5,
        )
        slot = create_shelf_slot(shelf_code="SH-G1", zone="GENERAL", capacity_grams=2000)
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
        return client, ctx

    def test_state_violation_returns_409_not_422(self, api):
        """PRD §2.8: "first authentication (missing or malformed identity
        headers, `ERR_UNAUTHENTICATED`), then authorization (role permission
        and client-subtree scoping, `ERR_FORBIDDEN`), then existence and
        nesting of path and body-referenced ids (`ERR_NOT_FOUND`), then
        request-body well-formedness — required fields present, types correct,
        enums within their declared sets, numeric ranges honored, and no
        unknown or server-computed keys in the payload (`ERR_INVALID_REQUEST`),
        then client suspension (`ERR_CLIENT_SUSPENDED`), then state-machine
        legality (`ERR_INVALID_STATE`, or `ERR_DOCUMENT_NOT_DELIVERED` on the
        download path), then the business-safety checks in the order custody
        segregation (`ERR_CUSTODY_SEGREGATION` / `ERR_WITNESS_SEGREGATION`)"

        Design: Difficulty/priority_pair_validation_conflict/state_precondition_beats_witness_segregation
        """
        _client, ctx = self._setup_awaiting_disposition_box()
        # Attempt a destruction-certificate on a box that is NOT yet
        # IN_DESTRUCTION, AND name the recorder as the witness.
        resp = api_client.create_destruction_certificate(
            ctx["box"]["id"],
            {"witness_user_id": DS, "method": "SHRED"},
            make_destruction_specialist_headers(DS),
        )
        # State (priority 5) beats business_safety (priority 6): 409 not 422.
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        box = get_box(ctx["box"]["id"])
        assert box["status"] == "AWAITING_DISPOSITION"

    def test_no_certificate_created_when_state_check_fires(self, api):
        """PRD §2.8: "then state-machine legality (`ERR_INVALID_STATE`, or
        `ERR_DOCUMENT_NOT_DELIVERED` on the download path), then the
        business-safety checks in the order custody segregation
        (`ERR_CUSTODY_SEGREGATION` / `ERR_WITNESS_SEGREGATION`)"

        Design: Difficulty/priority_pair_validation_conflict/state_precondition_beats_witness_segregation
        """
        _client, ctx = self._setup_awaiting_disposition_box()
        api_client.create_destruction_certificate(
            ctx["box"]["id"],
            {"witness_user_id": DS, "method": "SHRED"},
            make_destruction_specialist_headers(DS),
        )
        # Certificate list for the box is empty.
        from test_helpers import validate_paginated
        certs, _meta = validate_paginated(api_client.get_box_destruction_certificates(
            ctx["box"]["id"], make_compliance_officer_headers(CO),
        ))
        assert certs == []


class TestVaultZoneSafetyBeatsShelfCapacity:
    """Two tests for Difficulty instance
    `vault_zone_safety_beats_shelf_capacity`."""

    def _setup(self):
        client, _ = create_client_with_agreement(
            name="HIPAA Clinic", hipaa_covered=True,
            price_tier="STANDARD", rush_multiplier=1.75,
            storage_free_days=10, storage_daily_rate_cents=55,
            retention_days=30, max_boxes_per_batch=5,
        )
        # Tiny GENERAL slot: capacity 100 — box is 600g so capacity ALSO fails.
        slot = create_shelf_slot(shelf_code="SH-TINY", zone="GENERAL", capacity_grams=100)
        ctx = batch_in_intake(client_id=client["id"])
        box = create_box(ctx["batch"]["id"], box_label="BX-1", intake_weight_grams=600)
        create_document(box["id"], doc_type="MEDICAL_RECORD", pages=40, contains_phi=True, ocr_confidence=95)
        return client, ctx, slot, box

    def test_vault_zone_error_returned_over_capacity(self, api):
        """PRD §2.8: "then the business-safety checks in the order custody
        segregation (`ERR_CUSTODY_SEGREGATION` / `ERR_WITNESS_SEGREGATION`),
        custody flag (`ERR_CUSTODY_FLAGGED`), and vault-zone / grant-channel /
        scope (`ERR_VAULT_ZONE_REQUIRED` / `ERR_GRANT_VAULT_ONLY` /
        `ERR_SCOPE_INSUFFICIENT`), then temporal windows
        (`ERR_RETURN_WINDOW_EXPIRED` / `ERR_GRANT_EXPIRED`), then metadata
        completeness (`ERR_METADATA_INCOMPLETE`), then capacity and uniqueness
        ceilings (`ERR_SCANNER_OVER_CAPACITY`, `ERR_SHELF_OVER_CAPACITY`,
        `ERR_MAX_BOXES_EXCEEDED`, `ERR_RUSH_CAPACITY_FULL`, `ERR_SCANNER_BUSY`,
        `ERR_AGREEMENT_EXISTS`)"

        Design: Difficulty/priority_pair_validation_conflict/vault_zone_safety_beats_shelf_capacity
        """
        _client, _ctx, slot, box = self._setup()
        resp = api_client.create_shelf_assignment(
            box["id"], {"shelf_slot_id": slot["id"]}, make_intake_clerk_headers(CLERK),
        )
        validate_error(resp, ApiErrorId.ERR_VAULT_ZONE_REQUIRED, expected_status=422)

    def test_no_side_effects_when_vault_zone_fires(self, api):
        """PRD §3.2: "And when the batch's client is `hipaa_covered` and any
        document in the box has `contains_phi` set, the chosen slot's `zone`
        must be `VAULT`; placing such a box on a `GENERAL` shelf is rejected
        with `ERR_VAULT_ZONE_REQUIRED` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/vault_zone_safety_beats_shelf_capacity
        """
        _client, _ctx, slot, box = self._setup()
        api_client.create_shelf_assignment(
            box["id"], {"shelf_slot_id": slot["id"]}, make_intake_clerk_headers(CLERK),
        )
        box_after = get_box(box["id"])
        assert box_after["status"] == "RECEIVED"
        slot_after = get_shelf_slot(slot["id"])
        assert slot_after["occupied_weight_grams"] == 0


# ---------------------------------------------------------------------------
# Queue B — Corner / validations
# ---------------------------------------------------------------------------

class TestRequestMissingAuthHeadersReturnsUnauthenticated:
    """Corner: request_missing_auth_headers_returns_unauthenticated."""

    def test_missing_auth_headers_yields_401_before_existence(self, api):
        """PRD §2.1: "A request missing either header, or carrying a role
        string outside the declared set, is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)." PRD §2.8: "first authentication (missing or malformed
        identity headers, `ERR_UNAUTHENTICATED`), then authorization (role
        permission and client-subtree scoping, `ERR_FORBIDDEN`), then
        existence and nesting of path and body-referenced ids
        (`ERR_NOT_FOUND`)"

        Design: Corner/validations/request_missing_auth_headers_returns_unauthenticated
        """
        resp = api_client.start_prep(NON_EXISTENT_UUID, headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


class TestSuspendedClientMutationBlockedBeforeStateChecks:
    """Corner: suspended_client_mutation_blocked_before_state_checks."""

    def test_suspended_client_rejects_state_valid_start_prep(self, api):
        """PRD §3.1: "While a client is `SUSPENDED`, every mutation on its
        subtree and every use of its access grants is rejected with
        `ERR_CLIENT_SUSPENDED` (HTTP 403)." PRD §2.8: "then client suspension
        (`ERR_CLIENT_SUSPENDED`), then state-machine legality
        (`ERR_INVALID_STATE`, or `ERR_DOCUMENT_NOT_DELIVERED` on the download
        path)"

        Design: Corner/validations/suspended_client_mutation_blocked_before_state_checks
        """
        client, _ = create_client_with_agreement(
            name="Susp Co", hipaa_covered=False,
            price_tier="STANDARD", rush_multiplier=1.75,
            storage_free_days=10, storage_daily_rate_cents=55,
            retention_days=30, max_boxes_per_batch=5,
        )
        batch = create_batch(client["id"])
        # Suspend the client; the batch is still in INTAKE so start-prep would
        # otherwise be legal on state (needs a box though). Use a different
        # state-valid mutation: create_box on INTAKE batch.
        get_success_data(api_client.suspend_client(client["id"], make_platform_admin_headers(ADMIN)))
        resp = api_client.create_box(
            batch["id"], {"box_label": "BX-1", "intake_weight_grams": 100},
            make_intake_clerk_headers(CLERK),
        )
        validate_error(resp, ApiErrorId.ERR_CLIENT_SUSPENDED, expected_status=403)
        # Batch remains INTAKE
        b = get_success_data(api_client.get_batch(batch["id"], make_platform_admin_headers(ADMIN)))
        assert b["status"] == "INTAKE"
