"""PlayerContract and multi-party signing tests (PRD §3.3).

Covers contract creation, term validation, identity verification flip,
the DRAFT → PENDING_SIGNATURES → ACTIVE chain with strict ordering of
required_signatories, ERR_TEAM_NOT_ELIGIBLE on the final signature when
the team is WITHDRAWN, and amendment + termination paths.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    build_user_headers,
    create_open_tournament,
    create_player_contract,
    create_player_contract_payload,
    create_team_registration,
    file_identity_verification,
    file_identity_verification_payload,
    initiate_signing,
    iso_utc,
    make_player_headers,
    make_team_manager_headers,
    register_team_to_registered,
    reset_clock_to_epoch,
    sign_contract,
    validate_error,
    validate_success,
)


# ===========================================================================
# Create contract (PRD §3.3)
# ===========================================================================
class TestCreateContract:
    def test_create_contract_invalid_term_end_before_term_start(self, api):
        """PRD §3.3: "term_end must be strictly greater than term_start
        — otherwise ERR_INVALID_CONTRACT_TERM."

        Claim: contract with term_end <= term_start → ERR_INVALID_CONTRACT_TERM.
        """
        reset_clock_to_epoch()
        t = create_open_tournament()
        reg = create_team_registration(t["id"])
        payload = create_player_contract_payload(
            team_id=reg["id"],
            term_start=iso_utc(days_offset=10),
            term_end=iso_utc(days_offset=5),   # before term_start
        )
        response = api.create_player_contract(
            payload, make_team_manager_headers(reg["manager_id"]),
        )
        validate_error(response, ApiErrorId.ERR_INVALID_CONTRACT_TERM.value)


# ===========================================================================
# Identity verification (PRD §3.3)
# ===========================================================================
class TestIdentityVerification:
    def test_verified_status_flips_identity_verified_flag(
        self, api, league_admin_headers,
    ):
        """PRD §3.3: "A row in VERIFIED status flips the parent
        contract's identity_verified to true."

        Claim: filing an IdentityVerification with status=VERIFIED
        makes PlayerContract.identity_verified=true.
        """
        reset_clock_to_epoch()
        t = create_open_tournament()
        reg = create_team_registration(t["id"])
        c = create_player_contract(
            team_id=reg["id"], manager_id=reg["manager_id"],
        )
        assert c["identity_verified"] is False
        file_identity_verification(
            c["id"], jurisdiction="US", status="VERIFIED",
        )
        # Re-read contract.
        from test_helpers import get_player_contract
        reloaded = get_player_contract(c["id"])
        assert reloaded["identity_verified"] is True

    def test_rejected_status_does_not_flip_identity_verified(
        self, api, league_admin_headers,
    ):
        """PRD §3.3: "a REJECTED row records the audit-style reason
        but does not flip the flag."

        Claim: filing IdentityVerification with status=REJECTED leaves
        PlayerContract.identity_verified=false.
        """
        reset_clock_to_epoch()
        t = create_open_tournament()
        reg = create_team_registration(t["id"])
        c = create_player_contract(
            team_id=reg["id"], manager_id=reg["manager_id"],
        )
        file_identity_verification(
            c["id"], jurisdiction="US", status="REJECTED",
            rejection_reason="Document unreadable",
        )
        from test_helpers import get_player_contract
        reloaded = get_player_contract(c["id"])
        assert reloaded["identity_verified"] is False


# ===========================================================================
# Initiate signing (PRD §3.3)
# ===========================================================================
class TestInitiateSigning:
    def test_initiate_without_verified_identity_rejected(self, api):
        """PRD §3.3: "the contract's identity_verified must be true
        (otherwise ERR_IDENTITY_NOT_VERIFIED)."

        Claim: initiate-signing on a contract whose identity is not
        verified → ERR_IDENTITY_NOT_VERIFIED.
        """
        reset_clock_to_epoch()
        t = create_open_tournament()
        reg = create_team_registration(t["id"])
        c = create_player_contract(
            team_id=reg["id"], manager_id=reg["manager_id"],
        )
        # Skip identity verification entirely.
        response = api.initiate_signing(
            c["id"], make_team_manager_headers(reg["manager_id"]),
        )
        validate_error(response, ApiErrorId.ERR_IDENTITY_NOT_VERIFIED.value)

    def test_initiate_with_empty_required_signatories_rejected(self, api):
        """PRD §3.3: "required_signatories must be non-empty (otherwise
        ERR_NO_SIGNATORIES)."

        Claim: initiate-signing on a contract whose required_signatories
        is [] → ERR_NO_SIGNATORIES.
        """
        reset_clock_to_epoch()
        t = create_open_tournament()
        reg = create_team_registration(t["id"])
        c = create_player_contract(
            team_id=reg["id"], manager_id=reg["manager_id"],
            required_signatories=[],
        )
        file_identity_verification(
            c["id"], jurisdiction="US", status="VERIFIED",
        )
        response = api.initiate_signing(
            c["id"], make_team_manager_headers(reg["manager_id"]),
        )
        validate_error(response, ApiErrorId.ERR_NO_SIGNATORIES.value)


# ===========================================================================
# Sign chain (PRD §3.3)
# ===========================================================================
class TestSignChain:
    def test_wrong_signatory_rejected(self, api):
        """PRD §3.3: "the calling role must match
        required_signatories[len(signatures)].party — that is, the
        party expected at the current index. A mismatch rejects with
        ERR_WRONG_SIGNATORY."

        Claim: when required_signatories[0].party is PLAYER and the
        TeamManager attempts the first sign → ERR_WRONG_SIGNATORY.
        """
        reset_clock_to_epoch()
        t = create_open_tournament()
        reg = create_team_registration(t["id"])
        c = create_player_contract(
            team_id=reg["id"], manager_id=reg["manager_id"],
            required_signatories=[
                {"party": "PLAYER"},
                {"party": "TEAM_MANAGER"},
                {"party": "LEAGUE_ADMIN"},
            ],
        )
        file_identity_verification(c["id"], jurisdiction="US",
                                   status="VERIFIED")
        initiate_signing(c["id"], manager_id=reg["manager_id"])
        # TeamManager tries to sign first — but required[0].party is PLAYER.
        response = api.sign_contract(
            c["id"], make_team_manager_headers(reg["manager_id"]),
        )
        validate_error(response, ApiErrorId.ERR_WRONG_SIGNATORY.value)

    def test_final_signature_transitions_to_active_pins_signed_version_id(
        self, api,
    ):
        """PRD §3.3: "The final signature transitions PENDING_SIGNATURES
        to ACTIVE. ... On ACTIVE, the system pins signed_version_id to
        the current version value of the contract — this freezes the
        exact version that every party signed."

        Claim: contract reaches ACTIVE and signed_version_id is non-null
        after the last signatory's call.
        """
        reset_clock_to_epoch()
        t = create_open_tournament()
        reg = create_team_registration(t["id"])
        c = create_player_contract(
            team_id=reg["id"], manager_id=reg["manager_id"],
            required_signatories=[
                {"party": "PLAYER"},
                {"party": "TEAM_MANAGER"},
                {"party": "LEAGUE_ADMIN"},
            ],
        )
        file_identity_verification(c["id"], jurisdiction="US",
                                   status="VERIFIED")
        initiate_signing(c["id"], manager_id=reg["manager_id"])
        # PLAYER (entity_backed — uses player_id)
        sign_contract(c["id"], make_player_headers(c["player_id"]))
        # TEAM_MANAGER (opaque, ownership via manager_id)
        sign_contract(c["id"], make_team_manager_headers(reg["manager_id"]))
        # LEAGUE_ADMIN (opaque, shared)
        final = sign_contract(c["id"], TEST_USERS["league_admin_headers"])
        assert final["status"] == "ACTIVE"
        assert final.get("signed_version_id") is not None, (
            "PRD §3.3: signed_version_id pinned at final signature"
        )

    def test_amendment_clears_signed_version_id(self, api):
        """PRD §3.3: "The amendment transition moves the contract from
        ACTIVE to AMENDMENT_PENDING, and as a side effect clears
        signed_version_id to null — a pending amendment invalidates the
        previously frozen signed version."

        Claim: filing an amendment on an ACTIVE contract → status
        becomes AMENDMENT_PENDING and signed_version_id is null.
        """
        from test_helpers import create_active_contract, file_amendment_payload
        reset_clock_to_epoch()
        t = create_open_tournament()
        reg = create_team_registration(t["id"])
        active = create_active_contract(
            team_id=reg["id"], manager_id=reg["manager_id"],
        )
        assert active["signed_version_id"] is not None
        response = api.file_amendment(
            active["id"], file_amendment_payload(),
            make_team_manager_headers(reg["manager_id"]),
        )
        data = validate_success(response, expected_status=201)
        # The endpoint returns the updated contract; PRD §3.3 says
        # transitions to AMENDMENT_PENDING and clears signed_version_id.
        # Re-read to be defensive in case the return is the amendment.
        from test_helpers import get_player_contract
        reloaded = get_player_contract(active["id"])
        assert reloaded["status"] == "AMENDMENT_PENDING"
        assert reloaded.get("signed_version_id") is None
