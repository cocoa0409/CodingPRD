"""Manual void, auto-void, and re-initiation.

Covers PRD §3.7 (manual void, auto-void via /_sweep/run, re-initiation
with reinitiated_from_contract_id).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    activate_contract,
    add_seconds,
    advance_clock,
    api_client,
    append_signing_party,
    append_signing_step,
    create_contract_in_draft,
    create_contract_payload,
    create_identity_verification,
    create_published_template,
    current_clock_iso,
    get_contract,
    make_contract_initiator_headers,
    run_sweep,
    setup_completed_single_party_contract,
    setup_pending_sign_single_party,
    setup_reinitiation_chain,
    setup_single_party_contract,
    sign_party,
    stable_user_id,
    validate_error,
    validate_success,
)


class TestManualVoid:

    def test_manual_void_in_pending_sign_succeeds(self, api):
        """PRD §3.7: 'The ContractInitiator may manually void their
        Contract, but only while the Contract is in PENDING_SIGN and no
        SigningParty has reached SIGNED yet. On a successful manual void,
        the Contract status flips to VOIDED, voided_at is stamped to the
        current server time, and void_reason is set to MANUAL.'

        Claim: manual void on a PENDING_SIGN contract with no SIGNED
        parties -> status VOIDED, void_reason MANUAL, voided_at set.
        """
        ctx = setup_pending_sign_single_party()
        res = api.void_contract(
            ctx["contract"]["id"],
            make_contract_initiator_headers(ctx["initiator_id"]),
        )
        data = validate_success(res)
        assert data["status"] == "VOIDED"
        assert data["void_reason"] == "MANUAL"
        assert data["voided_at"] is not None

    def test_manual_void_in_partially_signed_rejected(self, api):
        """PRD §3.7: 'If the Contract is already past the gate -- for
        example, it has a signed party, or it is PARTIALLY_SIGNED -- the
        manual void is rejected with ERR_INVALID_STATE.'

        Claim: manual void on a contract whose first party has signed
        (and so it is at least PARTIALLY_SIGNED, or COMPLETED for
        single-party) -> ERR_INVALID_STATE.
        """
        ctx = setup_completed_single_party_contract()
        res = api.void_contract(
            ctx["contract"]["id"],
            make_contract_initiator_headers(ctx["initiator_id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


class TestAutoVoidViaSweep:

    def test_auto_void_when_now_at_or_after_expires_at(self, api):
        """PRD §3.7: 'Every Contract whose status is in PENDING_SIGN or
        PARTIALLY_SIGNED and whose expires_at is on or before the current
        server time is auto-voided with void_reason = EXPIRED_AUTO'.
        PRD §3.7: 'The boundary is inclusive: the moment-on-the-line
        counts as expired'.

        Claim: advance the clock to exactly expires_at, run the sweep ->
        contract is VOIDED with void_reason EXPIRED_AUTO.
        """
        # Build a PENDING_SIGN single-party contract with an explicit
        # expires_at we know.
        bundle = create_published_template()
        from test_helpers import (
            append_signing_party,
            append_signing_step,
            create_contract_in_draft,
        )
        # expires_at 2 hours from current clock.
        from test_helpers import add_hours
        expires_at = add_hours(current_clock_iso(), 2)
        contract, init_id = create_contract_in_draft(
            template_version_id=bundle["version"]["id"],
            initiator_org_id=bundle["owner_org_id"],
            expires_at=expires_at,
        )
        step = append_signing_step(
            contract_id=contract["id"], initiator_id=init_id,
            step_index=1, mode="PARALLEL_COUNTERSIGN",
        )
        append_signing_party(
            contract_id=contract["id"], signing_step_id=step["id"],
            initiator_id=init_id, signer_user_id=stable_user_id("s"),
            role_key="PARTY_A",
        )
        activate_contract(contract_id=contract["id"], initiator_id=init_id)
        # Advance to exactly expires_at and run sweep.
        advance_clock(expires_at)
        run_sweep()
        # Re-read contract.
        c = get_contract(contract["id"])
        assert c["status"] == "VOIDED"
        assert c["void_reason"] == "EXPIRED_AUTO"


class TestReInitiation:

    def test_reinitiate_from_voided_contract_succeeds(self, api):
        """PRD §3.7: 'A previously voided or expired Contract may be
        re-initiated. The new Contract carries reinitiated_from_contract_id
        pointing back to the source Contract's id.'

        Claim: after voiding a contract, creating a new Contract with
        reinitiated_from_contract_id pointing to it succeeds (201) and
        the new Contract has reinitiated_from_contract_id == source.id.
        """
        ctx = setup_pending_sign_single_party()
        # Manually void the source.
        api.void_contract(
            ctx["contract"]["id"],
            make_contract_initiator_headers(ctx["initiator_id"]),
        )
        # Now create a new contract on the same TemplateVersion, same
        # initiator_org_id, pointing back via reinitiated_from_contract_id.
        from test_helpers import add_hours
        new_expires_at = add_hours(current_clock_iso(), 24)
        res = api.create_contract(
            create_contract_payload(
                template_version_id=ctx["version"]["id"],
                expires_at=new_expires_at,
                reinitiated_from_contract_id=ctx["contract"]["id"],
            ),
            make_contract_initiator_headers(ctx["initiator_id"]),
        )
        data = validate_success(res, expected_status=201)
        assert data["reinitiated_from_contract_id"] == ctx["contract"]["id"]
        assert data["status"] == "DRAFT"

    def test_reinitiate_from_completed_contract_rejected(self, api):
        """PRD §3.7: 'The source must be in either VOIDED or EXPIRED
        status'.

        Claim: re-initiate from a COMPLETED contract -> 409
        ERR_REINITIATE_INVALID.
        """
        ctx = setup_completed_single_party_contract()
        from test_helpers import add_hours
        new_expires_at = add_hours(current_clock_iso(), 24)
        res = api.create_contract(
            create_contract_payload(
                template_version_id=ctx["version"]["id"],
                expires_at=new_expires_at,
                reinitiated_from_contract_id=ctx["contract"]["id"],
            ),
            make_contract_initiator_headers(ctx["initiator_id"]),
        )
        validate_error(res, ApiErrorId.ERR_REINITIATE_INVALID.value)

    def test_double_reinitiation_rejected(self, api):
        """PRD §3.7: 'there must not already be a successful re-initiation
        pointing to that source -- only one chain may extend from any
        given voided source.'

        Claim: a second create-with-reinitiated_from_contract_id pointing
        at the same source -> ERR_REINITIATE_INVALID.
        """
        ctx = setup_pending_sign_single_party()
        api.void_contract(
            ctx["contract"]["id"],
            make_contract_initiator_headers(ctx["initiator_id"]),
        )
        from test_helpers import add_hours
        new_expires_at = add_hours(current_clock_iso(), 24)
        # First successful re-initiation.
        api.create_contract(
            create_contract_payload(
                template_version_id=ctx["version"]["id"],
                expires_at=new_expires_at,
                reinitiated_from_contract_id=ctx["contract"]["id"],
            ),
            make_contract_initiator_headers(ctx["initiator_id"]),
        )
        # Second attempt pointing to the same source must fail.
        res = api.create_contract(
            create_contract_payload(
                template_version_id=ctx["version"]["id"],
                expires_at=new_expires_at,
                reinitiated_from_contract_id=ctx["contract"]["id"],
            ),
            make_contract_initiator_headers(ctx["initiator_id"]),
        )
        validate_error(res, ApiErrorId.ERR_REINITIATE_INVALID.value)
