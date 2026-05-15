"""Client and agreement lifecycle tests (PRD §3.1, §3.2)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    ApiErrorId,
    activate_agreement,
    advance_clock_to,
    assert_client_company,
    assert_commission_agreement,
    create_agreement,
    create_agreement_payload,
    create_client,
    create_client_payload,
    create_declaration,
    iso_utc,
    make_client_user_headers,
    random_tax_id,
    request_signature,
    request_signature_payload,
    reset_clock_to_epoch,
    setup_active_agreement,
    sign_agreement,
    sign_agreement_payload,
    terminate_agreement_payload,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.1 — ClientCompany creation & defaults
# ===========================================================================
class TestClientCreation:

    def test_create_client_initial_state_is_active(self, api, broker_ops_headers):
        """PRD §3.1: "A newly recorded client lands in ACTIVE status".

        Claim: POST /customs/clients with valid input → status=ACTIVE.
        """
        resp = api.create_client(create_client_payload(), broker_ops_headers)
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "ACTIVE"
        assert_client_company(data)

    def test_create_client_country_code_must_be_two_upper_letters(
        self, api, broker_ops_headers,
    ):
        """PRD §3.1: "their ISO 3166-1 alpha-2 country_code (exactly two
        uppercase letters)".

        Claim: country_code that is not exactly 2 uppercase letters →
        ERR_INVALID_INPUT.
        """
        resp = api.create_client(
            create_client_payload(country_code="cn"), broker_ops_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_INPUT.value)

    def test_tax_id_is_immutable(self, api, broker_ops_headers):
        """PRD §3.1: "Patching a client may update legal_name,
        contact_email, default_settlement_currency, and status — the
        tax_id is immutable once set."

        Claim: PATCH attempting to mutate tax_id → ERR_INVALID_INPUT.
        """
        client = create_client()
        resp = api.update_client(
            client["id"],
            {"tax_id": random_tax_id("NEW"), "version": client["version"]},
            broker_ops_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_INPUT.value)

    def test_archived_client_excluded_from_uniqueness(self, api, broker_ops_headers):
        """PRD §3.1: "an ARCHIVED client is excluded from uniqueness
        checks on legal_name and tax_id."

        Claim: archive client A, then create client B with same
        legal_name → succeeds.
        """
        ln = "ArchTest Co. " + random_tax_id("LN")
        ti = random_tax_id("TID")
        c1 = create_client(legal_name=ln, tax_id=ti)
        # Archive c1.
        archived_resp = api.update_client(
            c1["id"], {"status": "ARCHIVED", "version": c1["version"]},
            broker_ops_headers,
        )
        validate_success(archived_resp)
        # Now recreate.
        ti2 = random_tax_id("TID2")
        resp = api.create_client(
            create_client_payload(legal_name=ln, tax_id=ti2),
            broker_ops_headers,
        )
        validate_success(resp, expected_status=201)


# ===========================================================================
# §3.1 — Agreement creation: fee_schedule keys must match scope_of_service
# ===========================================================================
class TestFeeScheduleValidation:

    def test_fee_schedule_missing_scope_key_rejected(self, api, broker_ops_headers):
        """PRD §3.1: "every key in fee_schedule must equal some entry in
        scope_of_service, and every entry in scope_of_service must appear
        as a key in fee_schedule. Any mismatch — a service in scope without
        a fee, or a fee for a service not in scope — is rejected with
        ERR_FEE_SCHEDULE_INVALID and HTTP 422."

        Claim: scope contains AMENDMENT but fee_schedule omits it →
        ERR_FEE_SCHEDULE_INVALID.
        """
        client = create_client()
        payload = create_agreement_payload(
            client_id=client["id"],
            scope_of_service=["DECLARATION", "AMENDMENT"],
            fee_schedule={"DECLARATION": 100},  # AMENDMENT missing
        )
        resp = api.create_agreement(payload, broker_ops_headers)
        validate_error(resp, ApiErrorId.ERR_FEE_SCHEDULE_INVALID.value)

    def test_fee_schedule_extra_key_not_in_scope_rejected(self, api,
                                                          broker_ops_headers):
        """PRD §3.1: "every key in fee_schedule must equal some entry in
        scope_of_service ... a fee for a service not in scope — is rejected
        with ERR_FEE_SCHEDULE_INVALID and HTTP 422."

        Claim: fee_schedule includes RETURN_SHIP not in scope →
        ERR_FEE_SCHEDULE_INVALID.
        """
        client = create_client()
        payload = create_agreement_payload(
            client_id=client["id"],
            scope_of_service=["DECLARATION"],
            fee_schedule={"DECLARATION": 100, "RETURN_SHIP": 200},
        )
        resp = api.create_agreement(payload, broker_ops_headers)
        validate_error(resp, ApiErrorId.ERR_FEE_SCHEDULE_INVALID.value)

    def test_agreement_created_in_draft(self, api, broker_ops_headers):
        """PRD §3.1: "An agreement is born in DRAFT status with signed_at
        and signature_token and pinned_fee_schedule_version all initialised
        to null".

        Claim: newly-created agreement has status=DRAFT, signature_token=null.
        """
        client = create_client()
        payload = create_agreement_payload(client_id=client["id"])
        resp = api.create_agreement(payload, broker_ops_headers)
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "DRAFT"
        assert data.get("signed_at") is None
        assert data.get("signature_token") is None
        assert_commission_agreement(data)


# ===========================================================================
# §3.2 — Signature workflow
# ===========================================================================
class TestSignatureWorkflow:

    def test_request_signature_advances_to_awaiting_and_mints_token(
        self, api, broker_ops_headers,
    ):
        """PRD §3.2: "On success the agreement advances from DRAFT to
        AWAITING_SIGNATURE and the server mints an opaque signature_token
        and persists it on the record."

        Claim: status moves to AWAITING_SIGNATURE; signature_token set.
        """
        client = create_client()
        agreement = create_agreement(client["id"])
        result = request_signature(agreement)
        assert result["status"] == "AWAITING_SIGNATURE"
        assert result.get("signature_token"), (
            "signature_token must be minted (PRD §3.2)"
        )

    def test_sign_advances_to_active_and_sets_signed_at(self, api):
        """PRD §3.2: "On success the agreement advances from
        AWAITING_SIGNATURE to ACTIVE, signed_at is set to the current
        instant, and pinned_fee_schedule_version is snapshotted to the
        agreement's post-increment version".

        Claim: status=ACTIVE, signed_at set, pinned_fee_schedule_version
        equals current version after sign.
        """
        client = create_client()
        agreement = activate_agreement(client["id"])
        assert agreement["status"] == "ACTIVE"
        assert agreement.get("signed_at"), "signed_at must be set"
        assert agreement.get("pinned_fee_schedule_version") == agreement["version"], (
            "pinned_fee_schedule_version must equal post-increment version"
        )

    # DELETED test_sign_requires_matching_token — PRD §3.2 names the check
    # ("the server verifies that the submitted token matches the stored
    # signature_token") but is silent on the surface error_id for a
    # mismatch; both ERR_INVALID_INPUT and ERR_INVALID_STATE are
    # PRD-faithful. Fails STEP 1b unique-derivability.


# ===========================================================================
# §3.2 — Termination
# ===========================================================================
class TestTermination:

    def test_terminate_draft_with_valid_reason(self, api, broker_ops_headers):
        """PRD §3.2: "Termination is reachable from either DRAFT or ACTIVE.
        A BrokerOps operator initiates it, providing a terminated_reason
        from the set CLIENT_REQUEST, BREACH, or REGULATORY."

        Claim: terminate from DRAFT with CLIENT_REQUEST → TERMINATED.
        """
        client = create_client()
        agreement = create_agreement(client["id"])
        resp = api.terminate_agreement(
            agreement["id"],
            terminate_agreement_payload(
                terminated_reason="CLIENT_REQUEST",
                version=agreement["version"],
            ),
            broker_ops_headers,
        )
        data = validate_success(resp)
        assert data["status"] == "TERMINATED"
        assert data["terminated_reason"] == "CLIENT_REQUEST"

    def test_terminate_active_blocked_by_open_declaration(
        self, api, broker_ops_headers,
    ):
        """PRD §3.2: "from ACTIVE the agreement is additionally guarded so
        that termination is blocked if any declaration under it is still
        in any of the non-terminal declaration states DRAFT, DOCS_PENDING,
        PRE_VALIDATED, FILED, QUERIED, INSPECTING, or AMENDING."

        Claim: an ACTIVE agreement with a DRAFT declaration cannot
        terminate → ERR_INVALID_STATE.
        """
        client, agreement = setup_active_agreement()
        # Open a declaration that lands in DRAFT.
        create_declaration(agreement["id"])
        resp = api.terminate_agreement(
            agreement["id"],
            terminate_agreement_payload(
                terminated_reason="CLIENT_REQUEST",
                version=agreement["version"],
            ),
            broker_ops_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# §2.5 — Optimistic concurrency on agreement mutations
# ===========================================================================
class TestOptimisticConcurrency:

    def test_request_signature_with_stale_version_rejected(
        self, api, broker_ops_headers,
    ):
        """PRD §2.5: "When present, the server compares it against the
        current version of the target resource; if the values differ, the
        request is rejected with ERR_VERSION_CONFLICT and HTTP 409 with
        no state change."

        Claim: request-signature with stale version → ERR_VERSION_CONFLICT.
        """
        client = create_client()
        agreement = create_agreement(client["id"])
        resp = api.request_signature(
            agreement["id"],
            request_signature_payload(version=agreement["version"] + 99),
            broker_ops_headers,
        )
        validate_error(resp, ApiErrorId.ERR_VERSION_CONFLICT.value)

    def test_version_omitted_skips_check(self, api, broker_ops_headers):
        """PRD §2.5: "When version is omitted from the request body, the
        server skips the comparison and proceeds (a deliberate escape
        hatch for callers that have already serialized externally)."

        Claim: omitting version on request-signature proceeds normally.
        """
        client = create_client()
        agreement = create_agreement(client["id"])
        resp = api.request_signature(
            agreement["id"], {}, broker_ops_headers,
        )
        data = validate_success(resp)
        assert data["status"] == "AWAITING_SIGNATURE"


# ===========================================================================
# §2.6 — 404 ordering left-to-right
# ===========================================================================
class TestNotFound:

    def test_unknown_client_id_returns_not_found(self, api, broker_ops_headers):
        """PRD §2.6: "When multiple identifiers appear in a path, the
        server validates them left-to-right and returns ERR_NOT_FOUND on
        the first missing identifier."

        Claim: GET /customs/clients/{unknown-id} → ERR_NOT_FOUND.
        """
        resp = api.get_client("00000000-0000-0000-0000-000000000000",
                              broker_ops_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_unknown_agreement_id_in_body_returns_not_found(
        self, api, declaration_officer_headers,
    ):
        """PRD §2.6: "Identifiers carried in the request body (the
        agreement_id on declaration creation ...) are also resolved and
        the same ERR_NOT_FOUND is returned with HTTP 404 if the referenced
        resource does not exist."

        Claim: POST /customs/declarations with unknown agreement_id →
        ERR_NOT_FOUND.
        """
        from test_helpers import create_declaration_payload
        resp = api.create_declaration(
            create_declaration_payload(
                agreement_id="00000000-0000-0000-0000-000000000000",
            ),
            declaration_officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)
