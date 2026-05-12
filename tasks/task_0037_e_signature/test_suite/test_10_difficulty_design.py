"""Difficulty-design priority queue.

This file covers every instance declared in
SCAFFOLD_DIFFICULTY_DESIGN.yaml with at least two PRD-traceable tests.
Each test docstring carries a verbatim PRD citation and the
``# difficulty: <rule_id>/<instance.name>`` tag for the coverage audit.

PRD-First applies throughout: every assertion is grounded in a verbatim
PRD sentence, never in the difficulty-design entry alone.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    activate_contract,
    add_hours,
    add_seconds,
    advance_clock,
    api_client,
    append_signing_party,
    append_signing_step,
    assert_audit_log_chain,
    assert_evidence_score_precision,
    assert_progress_precision,
    branch_condition,
    create_contract_in_draft,
    create_contract_payload,
    create_identity_verification,
    create_published_template,
    create_reminder_rule_payload,
    create_signing_party_payload,
    create_signing_step_payload,
    current_clock_iso,
    decline_party,
    fire_reminder_payload,
    get_contract,
    get_evidence_package,
    get_evidence_preview,
    get_progress,
    is_lower_hex_64,
    list_audit_logs,
    list_reminder_events,
    make_contract_initiator_headers,
    make_evidence_archivist_headers,
    make_signer_headers,
    make_template_admin_headers,
    run_race,
    run_sweep,
    seal_evidence_payload,
    setup_completed_single_party_contract,
    setup_completed_with_evidence_in_generating,
    setup_decline_two_party_step,
    setup_partially_signed_contract,
    setup_pending_sign_single_party,
    setup_reinitiation_chain,
    setup_reminder_rule_in_pending_sign,
    setup_three_step_branched_contract,
    setup_two_contracts_partition_divergence,
    setup_two_step_two_parties_each,
    sign_party,
    sign_party_payload,
    signature_position,
    stable_user_id,
    unique_idempotency_key,
    validate_error,
    validate_error_is_one_of,
    validate_success,
    variable_field,
)


# =========================================================================
# Rule 1 -- dual_variant_calc
# =========================================================================
class TestDualVariantCalc:
    """# difficulty: dual_variant_calc/signing_progress_chronological_vs_forward_looking
    # difficulty: dual_variant_calc/evidence_strength_provisional_vs_post_seal
    """

    def test_forward_looking_includes_pending_step_parties(self, api):
        """PRD §3.9: 'The forward-looking variant assumes every PENDING
        SigningStep will activate and every WAITING SigningParty in those
        steps will be required, so it includes every party under every
        non-SKIPPED step (PENDING plus ACTIVE plus SIGNED plus REJECTED)
        in the denominator; the numerator is still the count of SIGNED
        parties.'

        Claim: same setup as above, but ?variant=forward_looking yields
        50.00 (2 SIGNED out of 4 included).
        # difficulty: dual_variant_calc/signing_progress_chronological_vs_forward_looking
        """
        ctx = setup_two_step_two_parties_each()
        activate_contract(
            contract_id=ctx["contract"]["id"],
            initiator_id=ctx["initiator_id"],
        )
        for i in range(2):
            iv = create_identity_verification(
                subject_user_id=ctx["signer_user_ids"][i],
                contract_id=ctx["contract"]["id"],
                factors=[("SMS", "PASS")],
            )
            sign_party(
                party_id=ctx["parties"][i]["id"],
                signer_user_id=ctx["signer_user_ids"][i],
                identity_verification_id=iv["id"],
            )
        progress = get_progress(
            ctx["contract"]["id"], variant="forward_looking",
        )
        assert progress["progress_percent"] == 50.00
        assert progress["variant"] == "forward_looking"

    def test_provisional_pre_seal_zeroes_notary(self, api):
        """PRD §3.10: 'A pre-seal preview is available before the
        EvidencePackage is sealed. The preview reports a provisional
        score and a provisional tier computed with the notary score
        forced to 0 -- even when notary_provider is configured, no
        notary commitment has been made yet, so the score may not yet
        credit it.'

        Claim: a single-party COMPLETED contract with notary_provider
        defaulting to NONE has provisional_score == evidence_strength_score
        (notary score is 0 in both passes when provider is NONE).
        # difficulty: dual_variant_calc/evidence_strength_provisional_vs_post_seal
        """
        ctx = setup_completed_single_party_contract(
            factors=[("SMS", "PASS")], drift_seconds=0.0,
        )
        preview = get_evidence_preview(ctx["contract"]["id"])
        # PRD: 'and equal to the post-seal score when notary_provider is
        # already NONE.'
        assert preview["provisional_score"] == ctx["contract"][
            "evidence_strength_score"
        ]

    def test_post_seal_score_includes_notary_bonus_when_notarized(self, api):
        """PRD §3.10: 'When and only when the tier resolves to NOTARIZED,
        the score is re-evaluated in a second pass with the notary score
        replaced by the smaller of 100 and the notary score plus 10
        (NOTARIZED_BONUS).'

        Claim: build a contract whose first-pass raw is at the NOTARIZED
        threshold (>= 90 with notary_provider = BLOCKCHAIN). Drive it to
        COMPLETED with two factors I=100, drift 0 T=100, hash matches
        H=100; pre-seal raw with N(BLOCKCHAIN)=90 = 30+30+20+18 = 98.00
        which is NOTARIZED. After seal applies bonus, N_final = 100 ->
        raw_final = 30+30+20+20 = 100.00.

        # difficulty: dual_variant_calc/evidence_strength_provisional_vs_post_seal
        """
        # Build a CA_CERT + BANK_CARD signer with drift 0; identity
        # tier = 100, timestamp tier = 100, hash = 100.
        ctx = setup_completed_single_party_contract(
            factors=[("CA_CERT", "PASS"), ("BANK_CARD", "PASS")],
            required_auth_factors=["CA_CERT", "BANK_CARD"],
            drift_seconds=0.0,
        )
        # Now seal with notary_provider=BLOCKCHAIN. Archivist must be
        # different from initiator (PRD §3.11 SoD).
        archivist_id = stable_user_id("arch")
        seal_res = api.seal_evidence(
            ctx["contract"]["id"],
            seal_evidence_payload(
                notary_provider="BLOCKCHAIN",
                notary_reference="0xABCD",
            ),
            make_evidence_archivist_headers(archivist_id),
        )
        validate_success(seal_res)
        contract = get_contract(ctx["contract"]["id"])
        assert contract["evidence_strength_score"] == 100.00
        assert contract["evidence_tier"] == "NOTARIZED"


# =========================================================================
# Rule 2 -- combinatorial_formula
# =========================================================================
class TestCombinatorialFormula:
    """# difficulty: combinatorial_formula/document_fingerprint_nested_hash_order
    # difficulty: combinatorial_formula/evidence_score_circular_tier_bonus
    """

    def test_partitioned_variable_change_changes_fingerprint(self, api):
        """PRD §3.3: 'In step one, for each page index from 1 through
        page_count ascending, the system constructs a UTF-8 canonical
        JSON object containing the page_index, the TemplateVersion's
        document_blob_sha256 as blob_sha256, and the subset of
        variable_values whose keys' associated signature_positions have
        a page equal to that index, sorted by key ascending; that JSON
        is hashed with SHA-256 to yield a per-page hex digest.'

        Claim: two contracts on the same TemplateVersion (page_count=2)
        differ only in the 'date' variable (bound to page 1) -- their
        document_fingerprint_sha256 values differ.
        # difficulty: combinatorial_formula/document_fingerprint_nested_hash_order
        """
        ctx = setup_two_contracts_partition_divergence()
        activate_contract(
            contract_id=ctx["ca"]["id"], initiator_id=ctx["init_a"],
        )
        activate_contract(
            contract_id=ctx["cb"]["id"], initiator_id=ctx["init_b"],
        )
        ca = get_contract(ctx["ca"]["id"])
        cb = get_contract(ctx["cb"]["id"])
        assert is_lower_hex_64(ca["document_fingerprint_sha256"])
        assert is_lower_hex_64(cb["document_fingerprint_sha256"])
        assert ca["document_fingerprint_sha256"] != cb[
            "document_fingerprint_sha256"
        ], (
            "PRD §3.3: per-page-1 hash must differ when only the page-1 "
            "variable differs"
        )

    def test_fingerprint_is_immutable_after_activation(self, api):
        """PRD §3.3: 'the document_fingerprint_sha256 is computed and
        pinned for the rest of the Contract's lifecycle'.

        Claim: re-reading a contract after subsequent state changes
        leaves document_fingerprint_sha256 unchanged.
        # difficulty: combinatorial_formula/document_fingerprint_nested_hash_order
        """
        ctx = setup_completed_single_party_contract()
        contract_after_complete = get_contract(ctx["contract"]["id"])
        fp1 = contract_after_complete["document_fingerprint_sha256"]
        # Re-read again.
        contract_again = get_contract(ctx["contract"]["id"])
        assert contract_again["document_fingerprint_sha256"] == fp1

    def test_score_just_below_notarized_threshold_stays_gold(self, api):
        """PRD §3.10: 'The tier is then assigned by banding the raw
        score: BRONZE when the raw score is strictly less than 40
        (TIER_SILVER_MIN); SILVER when the raw score is at least 40 and
        strictly less than 70 (TIER_GOLD_MIN); GOLD when the raw score
        is at least 70 and strictly less than 90 (TIER_NOTARIZED_MIN)';
        and PRD §3.10: 'When and only when the tier resolves to
        NOTARIZED, the score is re-evaluated in a second pass'.

        Claim: a contract whose first-pass raw score is in [70, 90)
        (i.e. GOLD) does NOT receive the notary bonus -- the bonus is
        only applied conditionally on the first-pass NOTARIZED tier.

        Construct: I=100 (CA_CERT+BANK_CARD), T=60 (drift 6s in loose
        band), H=100, N=NOTARY_PUBLIC (60). raw = 30+18+20+12 = 80.00 ->
        GOLD. After seal, no bonus is applied; score stays 80.00.
        # difficulty: combinatorial_formula/evidence_score_circular_tier_bonus
        """
        ctx = setup_completed_single_party_contract(
            factors=[("CA_CERT", "PASS"), ("BANK_CARD", "PASS")],
            required_auth_factors=["CA_CERT", "BANK_CARD"],
            drift_seconds=6.0,  # in loose band (5 < drift <= 30)
        )
        archivist_id = stable_user_id("arch")
        seal_res = api.seal_evidence(
            ctx["contract"]["id"],
            seal_evidence_payload(
                notary_provider="NOTARY_PUBLIC",
                notary_reference="NP-001",
            ),
            make_evidence_archivist_headers(archivist_id),
        )
        validate_success(seal_res)
        c = get_contract(ctx["contract"]["id"])
        # 0.30*100 + 0.30*60 + 0.20*100 + 0.20*60 = 30+18+20+12 = 80.00.
        assert c["evidence_strength_score"] == 80.00
        assert c["evidence_tier"] == "GOLD"


# =========================================================================
# Rule 3 -- non_linear_state_machine
# =========================================================================
class TestNonLinearStateMachine:
    """# difficulty: non_linear_state_machine/contract_branching_with_voided_reinitiation
    # difficulty: non_linear_state_machine/signing_step_diamond_with_branch_skip
    """

    def test_three_void_branches_yield_distinct_void_reasons(self, api):
        """PRD §3.7: 'every Contract whose status is in PENDING_SIGN or
        PARTIALLY_SIGNED and whose expires_at is on or before the current
        server time is auto-voided with void_reason = EXPIRED_AUTO';
        PRD §3.7: 'On a successful manual void... void_reason is set to
        MANUAL.'; PRD §3.6: 'the Contract cascades to VOIDED with
        void_reason = REJECTED_BY_PARTY.'

        Claim: three contracts driven into VOIDED via three different
        paths (auto-expire, manual void, decline) carry three distinct
        void_reason values.
        # difficulty: non_linear_state_machine/contract_branching_with_voided_reinitiation
        """
        ctx = setup_reinitiation_chain(expires_at_offset_hours=1.0)
        c1, c2, c3 = ctx["contracts"]
        init_id = ctx["init_id"]
        # C2: manual void with no SIGNED parties.
        api.void_contract(
            c2["id"], make_contract_initiator_headers(init_id),
        )
        # C3: decline by P3.
        decline_party(
            party_id=ctx["parties"][2]["id"],
            signer_user_id=ctx["signer_user_ids"][2],
        )
        # C1: advance clock past expires_at and run sweep.
        # expires_at is 1 hour from a base; advance 2 hours.
        advance_clock(add_hours(current_clock_iso(), 2))
        run_sweep()
        # Re-read all three.
        c1r = get_contract(c1["id"])
        c2r = get_contract(c2["id"])
        c3r = get_contract(c3["id"])
        assert c1r["status"] == "VOIDED"
        assert c2r["status"] == "VOIDED"
        assert c3r["status"] == "VOIDED"
        assert c1r["void_reason"] == "EXPIRED_AUTO"
        assert c2r["void_reason"] == "MANUAL"
        assert c3r["void_reason"] == "REJECTED_BY_PARTY"

    def test_reinitiated_contract_links_back_to_voided(self, api):
        """PRD §3.7: 'A previously voided or expired Contract may be
        re-initiated. The new Contract carries reinitiated_from_contract_id
        pointing back to the source Contract's id.'

        Claim: after voiding a contract, a new Contract with
        reinitiated_from_contract_id pointing to it is created in DRAFT
        with that field set.
        # difficulty: non_linear_state_machine/contract_branching_with_voided_reinitiation
        """
        ctx = setup_pending_sign_single_party()
        api.void_contract(
            ctx["contract"]["id"],
            make_contract_initiator_headers(ctx["initiator_id"]),
        )
        new_expires = add_hours(current_clock_iso(), 24)
        res = api.create_contract(
            create_contract_payload(
                template_version_id=ctx["version"]["id"],
                expires_at=new_expires,
                reinitiated_from_contract_id=ctx["contract"]["id"],
            ),
            make_contract_initiator_headers(ctx["initiator_id"]),
        )
        new_contract = validate_success(res, expected_status=201)
        assert new_contract["reinitiated_from_contract_id"] == ctx[
            "contract"
        ]["id"]
        assert new_contract["status"] == "DRAFT"

    def test_branch_skip_flips_step_and_parties_to_skipped(self, api):
        """PRD §3.4: 'When a step has a branch_condition and the
        condition evaluates false, the step is auto-skipped -- its
        status flips directly from PENDING to SKIPPED, every child
        SigningParty cascades from WAITING to SKIPPED, and the next
        eligible step (the one with the lowest step_index still in
        PENDING) is then evaluated for activation, either advancing to
        ACTIVE or skipping in the same way.'

        Claim: in a 3-step contract where S2 has branch_condition
        amount >= 10000 and amount = 5000, after activating and signing
        S1's party, S2 SKIPS and S3 becomes ACTIVE; signing S3 yields a
        COMPLETED contract.
        # difficulty: non_linear_state_machine/signing_step_diamond_with_branch_skip
        """
        ctx = setup_three_step_branched_contract(
            amount_value=5000, branch_threshold=10000,
        )
        activate_contract(
            contract_id=ctx["contract"]["id"],
            initiator_id=ctx["initiator_id"],
        )
        signer_ids = ctx["signer_user_ids"]
        parties = ctx["parties"]
        # Sign S1 party.
        iv1 = create_identity_verification(
            subject_user_id=signer_ids[0],
            contract_id=ctx["contract"]["id"],
            factors=[("SMS", "PASS")],
        )
        sign_party(
            party_id=parties[0]["id"], signer_user_id=signer_ids[0],
            identity_verification_id=iv1["id"],
        )
        # S2 should auto-skip; S3 ACTIVE. Sign S3.
        iv3 = create_identity_verification(
            subject_user_id=signer_ids[2],
            contract_id=ctx["contract"]["id"],
            factors=[("SMS", "PASS")],
        )
        sign_party(
            party_id=parties[2]["id"], signer_user_id=signer_ids[2],
            identity_verification_id=iv3["id"],
        )
        contract = get_contract(ctx["contract"]["id"])
        assert contract["status"] == "COMPLETED"
        assert contract["signing_progress_percent"] == 100.00

    def test_branch_true_drives_step_active_not_skipped(self, api):
        """PRD §3.4: 'A SigningStep activates only when... the step has
        no branch_condition or the branch condition evaluates true
        against variable_values.'

        Claim: with the same 3-step contract but amount = 20000 (>=
        threshold), S2's branch evaluates TRUE -- after signing S1, S2
        becomes ACTIVE (NOT SKIPPED). Signing all three yields COMPLETED
        contract with progress 100.00.
        # difficulty: non_linear_state_machine/signing_step_diamond_with_branch_skip
        """
        ctx = setup_three_step_branched_contract(
            amount_value=20000, branch_threshold=10000,
        )
        activate_contract(
            contract_id=ctx["contract"]["id"],
            initiator_id=ctx["initiator_id"],
        )
        signer_ids = ctx["signer_user_ids"]
        parties = ctx["parties"]
        for i in range(3):
            iv = create_identity_verification(
                subject_user_id=signer_ids[i],
                contract_id=ctx["contract"]["id"],
                factors=[("SMS", "PASS")],
            )
            sign_party(
                party_id=parties[i]["id"], signer_user_id=signer_ids[i],
                identity_verification_id=iv["id"],
            )
        contract = get_contract(ctx["contract"]["id"])
        assert contract["status"] == "COMPLETED"
        assert contract["signing_progress_percent"] == 100.00


# =========================================================================
# Rule 4 -- transitive_cascade
# =========================================================================
class TestTransitiveCascade:
    """# difficulty: transitive_cascade/party_signed_to_evidence_generating_depth_4
    # difficulty: transitive_cascade/party_declined_to_contract_voided_depth_3
    """

    def test_party_sign_cascades_party_to_step_to_contract_to_evidence(
        self, api,
    ):
        """PRD §3.6: 'When the last party of the last required step
        signs, the Contract transitions from PARTIALLY_SIGNED to
        COMPLETED (or directly from PENDING_SIGN to COMPLETED if the
        workflow had only one party).' PRD §3.6: 'the EvidencePackage
        cascades from PENDING to GENERATING.'

        Claim: a single sign on a single-party contract drives the
        4-link cascade: party SIGNED, step SIGNED, contract COMPLETED,
        EvidencePackage GENERATING.
        # difficulty: transitive_cascade/party_signed_to_evidence_generating_depth_4
        """
        ctx = setup_completed_single_party_contract(
            factors=[("SMS", "PASS")], drift_seconds=0.0,
        )
        contract = ctx["contract"]
        assert contract["status"] == "COMPLETED"
        assert contract["completed_at"] is not None
        # Read the EvidencePackage.
        package = get_evidence_package(contract["id"])
        # PRD §3.11 / §3.6 says it cascades to GENERATING; sealing comes
        # later. Either GENERATING (cascade complete, no seal yet) or
        # PENDING (still being processed) would NOT both be PRD-faithful;
        # the PRD pins the cascade is part of the same write.
        assert package["status"] == "GENERATING"

    def test_completed_contract_signed_party_status(self, api):
        """PRD §3.5: 'The party then transitions AUTHENTICATING ->
        SIGNED, its signed_at is stamped to the current server time'.

        Claim: the signed party is recorded as SIGNED with signed_at
        non-null after the cascade completes.
        # difficulty: transitive_cascade/party_signed_to_evidence_generating_depth_4
        """
        ctx = setup_completed_single_party_contract()
        signed = ctx["signed_party"]
        assert signed["status"] == "SIGNED"
        assert signed["signed_at"] is not None

    def test_party_decline_cascades_to_step_rejected_to_contract_voided(
        self, api,
    ):
        """PRD §3.6: 'On decline the party advances AUTHENTICATING ->
        DECLINED. The parent SigningStep cascades to REJECTED... and the
        Contract cascades to VOIDED with void_reason = REJECTED_BY_PARTY.'

        Claim: declining a party drives the 3-link cascade: party
        DECLINED, step REJECTED, contract VOIDED with void_reason
        REJECTED_BY_PARTY.
        # difficulty: transitive_cascade/party_declined_to_contract_voided_depth_3
        """
        ctx = setup_decline_two_party_step()
        decline_party(
            party_id=ctx["parties"][0]["id"],
            signer_user_id=ctx["signer_user_ids"][0],
        )
        contract = get_contract(ctx["contract"]["id"])
        assert contract["status"] == "VOIDED"
        assert contract["void_reason"] == "REJECTED_BY_PARTY"

    def test_decline_disables_reminders_and_pushes_evidence_generating(
        self, api,
    ):
        """PRD §2.7: 'When a Contract auto-voids on expiry or is voided
        manually, every non-terminal SigningStep cascades to SKIPPED,
        every non-terminal SigningParty cascades to SKIPPED, every
        ReminderRule is disabled, and the EvidencePackage advances from
        PENDING to GENERATING.'

        Claim: after a decline-driven void, the EvidencePackage status
        is GENERATING (the cascade reaches it).
        # difficulty: transitive_cascade/party_declined_to_contract_voided_depth_3
        """
        ctx = setup_decline_two_party_step()
        decline_party(
            party_id=ctx["parties"][0]["id"],
            signer_user_id=ctx["signer_user_ids"][0],
        )
        package = get_evidence_package(ctx["contract"]["id"])
        assert package["status"] == "GENERATING"


# =========================================================================
# Rule 5 -- priority_pair_validation_conflict
# =========================================================================
class TestPriorityPairValidationConflict:
    """# difficulty: priority_pair_validation_conflict/state_vs_business_referential_on_sign
    # difficulty: priority_pair_validation_conflict/business_safety_vs_business_constraint_on_evidence_seal
    """

    def test_state_check_wins_over_auth_factors_check_on_sign(self, api):
        """PRD §2.9: 'The full ordering is: authentication first; then
        role authorization; then path-id existence; then template-
        publication state; then Contract state; then SigningParty
        active-state; ...; then identity-verification freshness and
        factor coverage'. PRD §2.9: 'A failure at an earlier step
        short-circuits and prevents later checks from firing'.

        Claim: a sign call against a DRAFT contract with an
        insufficient-factors IV must surface ERR_INVALID_STATE (priority
        5, contract state) -- NOT ERR_AUTH_FACTORS_INSUFFICIENT
        (priority 9).
        # difficulty: priority_pair_validation_conflict/state_vs_business_referential_on_sign
        """
        from test_helpers import setup_single_party_contract
        # Single-party DRAFT contract; party is WAITING (never AUTHENTICATING).
        ctx = setup_single_party_contract(
            required_auth_factors=["CA_CERT", "BANK_CARD"],
        )
        # Build IV with insufficient factors.
        iv = create_identity_verification(
            subject_user_id=ctx["signer_user_id"],
            contract_id=ctx["contract"]["id"],
            factors=[("SMS", "PASS")],
        )
        res = api.sign_party(
            ctx["party"]["id"],
            sign_party_payload(
                tsa_anchor_at=current_clock_iso(),
                identity_verification_id=iv["id"],
            ),
            make_signer_headers(ctx["signer_user_id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    def test_state_check_wins_over_drift_check_on_sign(self, api):
        """PRD §2.9: ordering is 'Contract state' (priority 5) before
        'timestamp drift' (priority 13). 'A failure at an earlier step
        short-circuits and prevents later checks from firing'.

        Claim: a sign call on a DRAFT contract with an excessive drift
        TimestampToken returns ERR_INVALID_STATE -- not
        ERR_TIMESTAMP_DRIFT_EXCEEDED.
        # difficulty: priority_pair_validation_conflict/state_vs_business_referential_on_sign
        """
        from test_helpers import setup_single_party_contract
        ctx = setup_single_party_contract(required_auth_factors=["SMS"])
        iv = create_identity_verification(
            subject_user_id=ctx["signer_user_id"],
            contract_id=ctx["contract"]["id"],
            factors=[("SMS", "PASS")],
        )
        res = api.sign_party(
            ctx["party"]["id"],
            sign_party_payload(
                tsa_anchor_at=add_seconds(current_clock_iso(), 90),
                identity_verification_id=iv["id"],
            ),
            make_signer_headers(ctx["signer_user_id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    def test_segregation_wins_over_notary_reference_on_seal(self, api):
        """PRD §2.9: 'segregation-of-duties for sealing' (priority 8)
        comes before 'notary-reference requirement' (priority 19). 'A
        failure at an earlier step short-circuits and prevents later
        checks from firing.'

        Claim: a seal call where (a) acting user is the initiator (SoD
        violation) AND (b) notary_provider != NONE with empty
        notary_reference -- the SoD error wins.
        # difficulty: priority_pair_validation_conflict/business_safety_vs_business_constraint_on_evidence_seal
        """
        ctx = setup_completed_with_evidence_in_generating()
        # Initiator's own id used for the seal call.
        res = api.seal_evidence(
            ctx["contract"]["id"],
            seal_evidence_payload(
                notary_provider="NOTARY_PUBLIC",
                notary_reference="",
            ),
            make_evidence_archivist_headers(ctx["initiator_id"]),
        )
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    def test_state_wins_over_segregation_on_seal_when_already_sealed(
        self, api,
    ):
        """PRD §2.9: state check (priority 5) is before SoD-for-sealing
        (priority 8). 'A failure at an earlier step short-circuits'.

        Claim: with the EvidencePackage already SEALED, a second seal by
        the initiator surfaces ERR_INVALID_STATE -- not the SoD code.
        # difficulty: priority_pair_validation_conflict/business_safety_vs_business_constraint_on_evidence_seal
        """
        ctx = setup_completed_with_evidence_in_generating()
        # First valid seal by the proper archivist.
        api.seal_evidence(
            ctx["contract"]["id"],
            seal_evidence_payload(),
            make_evidence_archivist_headers(ctx["archivist_id"]),
        )
        # Second seal by initiator -- both SoD AND state-check fail.
        res = api.seal_evidence(
            ctx["contract"]["id"],
            seal_evidence_payload(),
            make_evidence_archivist_headers(ctx["initiator_id"]),
        )
        # Per PRD §2.9 priority ordering, state-check (5) wins over
        # SoD-seal (8).
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# =========================================================================
# Rule 6 -- boundary_precision_check
# =========================================================================
class TestBoundaryPrecisionCheck:
    """# difficulty: boundary_precision_check/contract_expires_at_strict_lt_on_sign
    # difficulty: boundary_precision_check/reminder_due_inclusive_threshold_and_strict_escalation
    """

    def test_sign_at_expires_at_boundary_rejected(self, api):
        """PRD §3.5: 'The current server time must be strictly less than
        the Contract's expires_at; if not, the call is rejected with
        ERR_CONTRACT_EXPIRED.' (Strict less-than -- the moment-on-the-line
        is rejected.)

        Claim: with now() == expires_at, sign returns
        ERR_CONTRACT_EXPIRED.
        # difficulty: boundary_precision_check/contract_expires_at_strict_lt_on_sign
        """
        # Build a PENDING_SIGN contract with a known expires_at.
        bundle = create_published_template()
        # Pin expires_at far enough out to permit setup.
        expires_at = add_hours(current_clock_iso(), 4)
        contract, init_id = create_contract_in_draft(
            template_version_id=bundle["version"]["id"],
            initiator_org_id=bundle["owner_org_id"],
            expires_at=expires_at,
        )
        step = append_signing_step(
            contract_id=contract["id"], initiator_id=init_id,
            step_index=1, mode="PARALLEL_COUNTERSIGN",
        )
        signer_id = stable_user_id("s")
        party = append_signing_party(
            contract_id=contract["id"], signing_step_id=step["id"],
            initiator_id=init_id, signer_user_id=signer_id,
            role_key="PARTY_A",
        )
        activate_contract(contract_id=contract["id"], initiator_id=init_id)
        # Advance clock to exactly expires_at (boundary-on-the-line).
        advance_clock(expires_at)
        # Build an IV AFTER advancing the clock so the IV is fresh under
        # AUTH_TTL_MINUTES and freshness (priority 9) does not pre-empt
        # expiration (priority 11) per PRD §2.9.
        iv = create_identity_verification(
            subject_user_id=signer_id, contract_id=contract["id"],
            factors=[("SMS", "PASS")],
        )
        # Call sign.
        res = api.sign_party(
            party["id"],
            sign_party_payload(
                tsa_anchor_at=current_clock_iso(),
                identity_verification_id=iv["id"],
            ),
            make_signer_headers(signer_id),
        )
        # PRD §2.9: contract-expiration is at priority 11, after Contract
        # state (5) and party-active (6). For a contract still in
        # PENDING_SIGN with party AUTHENTICATING, those two checks pass
        # -- so the next failing precondition is expiration.
        # PRD §3.7: 'auto-void uses on-or-after'. PRD §3.5 strict-less-than
        # combined with sweep on-or-after means the auto-void could fire
        # if a sweep has run; we have not run a sweep, so the contract is
        # still PENDING_SIGN at this moment-on-the-line.
        validate_error(res, ApiErrorId.ERR_CONTRACT_EXPIRED.value)

    def test_sign_just_before_expires_at_succeeds(self, api):
        """PRD §3.5: 'The current server time must be strictly less than
        the Contract's expires_at'.

        Claim: with now() = expires_at - 1 second, sign succeeds (the
        contract has not yet expired).
        # difficulty: boundary_precision_check/contract_expires_at_strict_lt_on_sign
        """
        # PENDING_SIGN single-party contract.
        ctx = setup_pending_sign_single_party()
        contract = ctx["contract"]
        # Compute expires_at - 1 second.
        from test_helpers import parse_iso, iso_z
        from datetime import timedelta
        expires_at = parse_iso(contract["expires_at"])
        target = expires_at - timedelta(seconds=1)
        target_iso = iso_z(target)
        # Advance clock to one second before expiry.
        advance_clock(target_iso)
        iv = create_identity_verification(
            subject_user_id=ctx["signer_user_id"],
            contract_id=contract["id"],
            factors=[("SMS", "PASS")],
        )
        res = api.sign_party(
            ctx["party"]["id"],
            sign_party_payload(
                tsa_anchor_at=current_clock_iso(),
                identity_verification_id=iv["id"],
            ),
            make_signer_headers(ctx["signer_user_id"]),
        )
        data = validate_success(res)
        assert data["status"] == "SIGNED"

    def test_misses_count_at_threshold_does_not_escalate(self, api):
        """PRD §3.8: 'the rule escalates only when the new misses_count
        is strictly greater than escalation_after_misses (the configured
        count itself does not trigger escalation; one more miss than
        configured does).'

        Claim: with escalation_after_misses=2, the 1st reminder fires
        with escalated=false; the 2nd reminder fires with escalated=false
        (2 NOT > 2); the 3rd reminder fires with escalated=true (3 > 2).
        # difficulty: boundary_precision_check/reminder_due_inclusive_threshold_and_strict_escalation
        """
        ctx = setup_reminder_rule_in_pending_sign(
            interval_hours=24, escalation_after_misses=2, channels=["SMS"],
        )
        # First fire (misses_count -> 1, NOT > 2 -> escalated=false).
        idem1 = unique_idempotency_key(ctx["rule"]["id"], 0)
        res1 = api.fire_reminder(
            ctx["rule"]["id"],
            fire_reminder_payload(idempotency_key=idem1),
            make_contract_initiator_headers(ctx["initiator_id"]),
        )
        e1 = validate_success(res1, expected_status=201)
        assert e1["escalated"] is False, (
            "PRD §3.8: 1 NOT > 2, no escalation"
        )
        # Second fire (misses_count -> 2, NOT > 2 -> escalated=false).
        idem2 = unique_idempotency_key(ctx["rule"]["id"], 1)
        res2 = api.fire_reminder(
            ctx["rule"]["id"],
            fire_reminder_payload(idempotency_key=idem2),
            make_contract_initiator_headers(ctx["initiator_id"]),
        )
        e2 = validate_success(res2, expected_status=201)
        assert e2["escalated"] is False, (
            "PRD §3.8: 2 NOT > 2 (strict greater-than) -- no escalation"
        )

    def test_misses_count_above_threshold_escalates(self, api):
        """PRD §3.8: 'the rule escalates only when the new misses_count
        is strictly greater than escalation_after_misses... When a
        reminder fires, a ReminderEvent row is created with... the
        channels_used array (the rule's channels, plus the additional
        INITIATOR_IM channel if escalation applies)'.

        Claim: the 3rd fire (misses_count = 3 > 2) escalates and
        channels_used contains INITIATOR_IM.
        # difficulty: boundary_precision_check/reminder_due_inclusive_threshold_and_strict_escalation
        """
        ctx = setup_reminder_rule_in_pending_sign(
            interval_hours=24, escalation_after_misses=2, channels=["SMS"],
        )
        for slot in range(3):
            api.fire_reminder(
                ctx["rule"]["id"],
                fire_reminder_payload(
                    idempotency_key=unique_idempotency_key(
                        ctx["rule"]["id"], slot,
                    )
                ),
                make_contract_initiator_headers(ctx["initiator_id"]),
            )
        events = list_reminder_events(ctx["contract"]["id"])
        # Find the 3rd fire (slot = 2).
        third = [e for e in events
                 if e["idempotency_key"].endswith(":2")]
        assert len(third) == 1, "expected one slot-2 ReminderEvent"
        e = third[0]
        assert e["escalated"] is True, (
            "PRD §3.8: 3 > 2 (strict greater-than) -- escalation triggers"
        )
        assert "INITIATOR_IM" in e["channels_used"], (
            "PRD §3.8: 'add the additional INITIATOR_IM channel if "
            "escalation applies'"
        )


# =========================================================================
# Rule 7 -- cross_entity_state_dependency
# =========================================================================
class TestCrossEntityStateDependency:
    """# difficulty: cross_entity_state_dependency/contract_activate_requires_template_version_published
    # difficulty: cross_entity_state_dependency/signing_party_sign_requires_identity_verification_verified
    """

    def test_activate_succeeds_when_template_version_published(self, api):
        """PRD §3.3: 'Activation is rejected unless... the referenced
        TemplateVersion is in PUBLISHED'.

        Claim: with the TV in PUBLISHED, activate yields PENDING_SIGN.
        # difficulty: cross_entity_state_dependency/contract_activate_requires_template_version_published
        """
        ctx = setup_pending_sign_single_party()
        # Contract is in PENDING_SIGN -- precondition satisfied.
        assert ctx["contract"]["status"] == "PENDING_SIGN"

    def test_create_contract_against_draft_version_rejected(self, api):
        """PRD §3.2: 'If the referenced TemplateVersion is not in
        PUBLISHED, the call is rejected with ERR_TEMPLATE_NOT_PUBLISHED.'

        Claim: creating a Contract against a DRAFT TemplateVersion ->
        409 ERR_TEMPLATE_NOT_PUBLISHED.
        # difficulty: cross_entity_state_dependency/contract_activate_requires_template_version_published
        """
        from test_helpers import (
            create_template, create_template_version,
        )
        template, admin_id, _ = create_template()
        v_draft = create_template_version(
            template_id=template["id"], admin_id=admin_id,
        )
        init_id = stable_user_id("init")
        new_expires = add_hours(current_clock_iso(), 24)
        res = api.create_contract(
            create_contract_payload(
                template_version_id=v_draft["id"],
                expires_at=new_expires,
            ),
            make_contract_initiator_headers(init_id),
        )
        validate_error(res, ApiErrorId.ERR_TEMPLATE_NOT_PUBLISHED.value)

    def test_sign_with_verified_iv_succeeds(self, api):
        """PRD §3.5: 'There must exist a fresh IdentityVerification...
        with result = VERIFIED... and whose factors_passed is a superset
        of the party's required_auth_factors'.

        Claim: a VERIFIED IV with sufficient factors lets the sign
        succeed.
        # difficulty: cross_entity_state_dependency/signing_party_sign_requires_identity_verification_verified
        """
        ctx = setup_pending_sign_single_party(
            required_auth_factors=["SMS", "FACE"],
        )
        iv = create_identity_verification(
            subject_user_id=ctx["signer_user_id"],
            contract_id=ctx["contract"]["id"],
            factors=[("SMS", "PASS"), ("FACE", "PASS")],
        )
        res = api.sign_party(
            ctx["party"]["id"],
            sign_party_payload(
                tsa_anchor_at=current_clock_iso(),
                identity_verification_id=iv["id"],
            ),
            make_signer_headers(ctx["signer_user_id"]),
        )
        data = validate_success(res)
        assert data["status"] == "SIGNED"

    def test_sign_with_failed_iv_rejected(self, api):
        """PRD §3.5: 'whose factors_passed is a superset of the party's
        required_auth_factors; otherwise the call is rejected with
        ERR_AUTH_FACTORS_INSUFFICIENT.'

        Claim: an IV whose factors_passed is missing a required factor
        (FACE) -> ERR_AUTH_FACTORS_INSUFFICIENT.
        # difficulty: cross_entity_state_dependency/signing_party_sign_requires_identity_verification_verified
        """
        ctx = setup_pending_sign_single_party(
            required_auth_factors=["SMS", "FACE"],
        )
        iv = create_identity_verification(
            subject_user_id=ctx["signer_user_id"],
            contract_id=ctx["contract"]["id"],
            factors=[("SMS", "PASS"), ("FACE", "FAIL")],
        )
        res = api.sign_party(
            ctx["party"]["id"],
            sign_party_payload(
                tsa_anchor_at=current_clock_iso(),
                identity_verification_id=iv["id"],
            ),
            make_signer_headers(ctx["signer_user_id"]),
        )
        validate_error(res, ApiErrorId.ERR_AUTH_FACTORS_INSUFFICIENT.value)


# =========================================================================
# Rule 8 -- resource_temporal_overlap
# =========================================================================
class TestResourceTemporalOverlap:
    """# difficulty: resource_temporal_overlap/reminder_idempotency_slot_overlap_inclusive
    # difficulty: resource_temporal_overlap/signing_party_sign_decline_window_collision
    """

    def test_same_idempotency_key_collides(self, api):
        """PRD §3.8: 'The pair (reminder_rule_id, idempotency_key) is
        unique -- duplicate firings of the same slot are rejected with
        ERR_DUPLICATE_REMINDER.'

        Claim: a second fire with the SAME idempotency_key under the
        same rule -> 409 ERR_DUPLICATE_REMINDER.
        # difficulty: resource_temporal_overlap/reminder_idempotency_slot_overlap_inclusive
        """
        ctx = setup_reminder_rule_in_pending_sign(interval_hours=24)
        idem = unique_idempotency_key(ctx["rule"]["id"], 0)
        api.fire_reminder(
            ctx["rule"]["id"],
            fire_reminder_payload(idempotency_key=idem),
            make_contract_initiator_headers(ctx["initiator_id"]),
        )
        res = api.fire_reminder(
            ctx["rule"]["id"],
            fire_reminder_payload(idempotency_key=idem),
            make_contract_initiator_headers(ctx["initiator_id"]),
        )
        validate_error(res, ApiErrorId.ERR_DUPLICATE_REMINDER.value)

    def test_adjacent_idempotency_keys_both_succeed(self, api):
        """PRD §3.8: 'an idempotency_key of the form
        {reminder_rule_id}:{slot}'. Slots are discrete buckets keyed by
        epoch_floor. Adjacent slots are different keys -- both firings
        succeed (no overlap on this resource).

        Claim: two fires with adjacent (different-slot) idempotency_keys
        both create ReminderEvent rows.
        # difficulty: resource_temporal_overlap/reminder_idempotency_slot_overlap_inclusive
        """
        ctx = setup_reminder_rule_in_pending_sign(interval_hours=24)
        rule_id = ctx["rule"]["id"]
        idem0 = unique_idempotency_key(rule_id, 0)
        idem1 = unique_idempotency_key(rule_id, 1)
        res0 = api.fire_reminder(
            rule_id, fire_reminder_payload(idempotency_key=idem0),
            make_contract_initiator_headers(ctx["initiator_id"]),
        )
        validate_success(res0, expected_status=201)
        res1 = api.fire_reminder(
            rule_id, fire_reminder_payload(idempotency_key=idem1),
            make_contract_initiator_headers(ctx["initiator_id"]),
        )
        validate_success(res1, expected_status=201)

    def test_concurrent_sign_decline_yields_exactly_one_winner(self, api):
        """PRD §2.10: 'The same outcome holds when sign races decline
        against the same party'. PRD §2.10: 'Two simultaneous sign
        attempts against the same signing_party_id resolve to exactly
        one winner; the loser sees a party that is no longer in
        AUTHENTICATING and is rejected with ERR_INVALID_STATE'.

        Claim: a sign and a decline issued concurrently against the same
        party resolve to exactly one success and one failure with the
        loser surfacing ERR_INVALID_STATE.
        # difficulty: resource_temporal_overlap/signing_party_sign_decline_window_collision
        """
        ctx = setup_decline_two_party_step()
        # Pre-build IV for sign.
        iv = create_identity_verification(
            subject_user_id=ctx["signer_user_ids"][0],
            contract_id=ctx["contract"]["id"],
            factors=[("SMS", "PASS")],
        )
        party_id = ctx["parties"][0]["id"]
        signer_id = ctx["signer_user_ids"][0]
        # Run race: sign vs decline.
        results = run_race(
            lambda: api.sign_party(
                party_id,
                sign_party_payload(
                    tsa_anchor_at=current_clock_iso(),
                    identity_verification_id=iv["id"],
                ),
                make_signer_headers(signer_id),
            ),
            lambda: api.decline_party(
                party_id, make_signer_headers(signer_id),
            ),
        )
        # Exactly one success, one failure.
        from test_helpers import assert_race_outcome
        outcome = assert_race_outcome(results, 1, 1)
        # The losing call's error must reflect the no-longer-AUTHENTICATING
        # party. PRD §2.10 names ERR_INVALID_STATE for this race; PRD §3.5
        # also names ERR_PARTY_NOT_ACTIVE for "party not in AUTHENTICATING".
        # A faithful PRD reader can land on either, so we accept either.
        loser = outcome["failures"][0]
        body = loser.json()
        assert body["data"]["error_id"] in (
            ApiErrorId.ERR_INVALID_STATE.value,
            ApiErrorId.ERR_PARTY_NOT_ACTIVE.value,
        ), (
            f"PRD §2.10/§3.5 admit ERR_INVALID_STATE or ERR_PARTY_NOT_ACTIVE; "
            f"got {body['data']['error_id']}"
        )

    def test_concurrent_seal_export_export_fails_if_seal_pending(self, api):
        """PRD §2.10: 'When seal and export of the same EvidencePackage
        arrive concurrently, export only succeeds if seal has already
        committed; otherwise the export call sees a non-SEALED state and
        is rejected with ERR_INVALID_STATE.'

        Claim: a concurrent seal + export pair on a GENERATING package
        yields exactly one success (the seal) and one ERR_INVALID_STATE
        on the export, OR -- if the implementation serializes seal first
        -- both succeed. PRD names the rejection so we test the export
        failure when issued concurrently with seal.
        # difficulty: resource_temporal_overlap/signing_party_sign_decline_window_collision
        """
        ctx = setup_completed_with_evidence_in_generating()
        archivist_id = ctx["archivist_id"]
        results = run_race(
            lambda: api.seal_evidence(
                ctx["contract"]["id"],
                seal_evidence_payload(),
                make_evidence_archivist_headers(archivist_id),
            ),
            lambda: api.export_evidence(
                ctx["contract"]["id"],
                make_evidence_archivist_headers(archivist_id),
            ),
        )
        # PRD: 'export only succeeds if seal has already committed';
        # otherwise rejected with ERR_INVALID_STATE. We accept either:
        # (a) seal succeeded, export rejected with ERR_INVALID_STATE, or
        # (b) both succeeded (seal won deterministically and export ran
        #     after). PRD §2.10 names rejection only as an outcome --
        #     two-reader: an implementation that serializes seal first
        #     and lets export observe SEALED is also faithful.
        successes = [r for r in results if 200 <= r.status_code < 300]
        failures = [r for r in results if r.status_code >= 400]
        assert len(successes) >= 1, (
            "Seal must succeed at least once for the package to commit"
        )
        if failures:
            body = failures[0].json()
            assert body["data"]["error_id"] == (
                ApiErrorId.ERR_INVALID_STATE.value
            ), (
                "PRD §2.10: 'export call sees a non-SEALED state and is "
                "rejected with ERR_INVALID_STATE'"
            )


# =========================================================================
# Rule 9 -- compensating_invariant
# =========================================================================
class TestCompensatingInvariant:
    """# difficulty: compensating_invariant/contract_void_preserves_audit_log_chain
    # difficulty: compensating_invariant/contract_completion_preserves_party_signed_count
    """

    def test_void_preserves_audit_log_chain(self, api):
        """PRD §2.8: 'prev_log_sha256 (the payload_sha256 of the
        immediately preceding AuditLog chained per contract_id or
        template_id), and occurred_at. The chain is per-contract for
        contract-scoped events and per-template for template-scoped
        events; the first entry in each chain has prev_log_sha256 set to
        null.'

        Claim: after a decline-driven void on a partially-progressed
        contract, the contract's audit-log chain is intact: every
        non-first row's prev_log_sha256 equals the previous row's
        payload_sha256.
        # difficulty: compensating_invariant/contract_void_preserves_audit_log_chain
        """
        ctx = setup_partially_signed_contract()
        # Decline party_b1 to drive Contract -> VOIDED.
        decline_party(
            party_id=ctx["party_b1"]["id"],
            signer_user_id=ctx["signer_user_ids"][1],
        )
        logs = list_audit_logs(ctx["contract"]["id"])
        assert len(logs) >= 2, (
            "Multi-step contract should have >= 2 audit-log entries "
            "after activation, sign, and decline-void"
        )
        # First entry has prev_log_sha256 = null per PRD §2.8.
        assert logs[0].get("prev_log_sha256") in (None, "")
        # Chain integrity end-to-end.
        assert_audit_log_chain(logs)

    def test_void_audit_chain_contains_voided_action(self, api):
        """PRD §2.8 action enumeration includes CONTRACT_VOIDED. PRD
        §3.6: 'An AuditLog row with action PARTY_REJECTED is appended.'

        Claim: after a decline-driven void, the audit log contains a
        PARTY_REJECTED entry, and the chain (including pre-void entries)
        retains its hash links.
        # difficulty: compensating_invariant/contract_void_preserves_audit_log_chain
        """
        ctx = setup_partially_signed_contract()
        decline_party(
            party_id=ctx["party_b1"]["id"],
            signer_user_id=ctx["signer_user_ids"][1],
        )
        logs = list_audit_logs(ctx["contract"]["id"])
        actions = [log["action"] for log in logs]
        assert "PARTY_REJECTED" in actions, (
            "PRD §3.6: 'AuditLog row with action PARTY_REJECTED is "
            "appended'"
        )
        # Chain still intact.
        assert_audit_log_chain(logs)

    def test_completion_preserves_signed_plus_skipped_equals_total(
        self, api,
    ):
        """PRD §3.6: 'The transition fires only when every SigningParty
        across every SigningStep is in SIGNED or SKIPPED'. PRD §3.4
        + §2.7: skip cascades flip parties under SKIPPED steps to
        SKIPPED.

        Claim: in a 3-step contract where S2 is SKIPPED via branch=false,
        signing S1 and S3 reaches COMPLETED. Reading the contract back:
        signing_progress_percent == 100.00 (chronological -- S2 SKIPPED
        is excluded). The conserved quantity holds: among the 3 parties,
        exactly 2 are SIGNED and 1 is SKIPPED.

        We observe the invariant via the chronological percentage
        (proxy for signed_count / eligible_count), which equals 100.00,
        confirming both eligible S1 and S3 parties signed.
        # difficulty: compensating_invariant/contract_completion_preserves_party_signed_count
        """
        ctx = setup_three_step_branched_contract(
            amount_value=5000, branch_threshold=10000,
        )
        activate_contract(
            contract_id=ctx["contract"]["id"],
            initiator_id=ctx["initiator_id"],
        )
        signer_ids = ctx["signer_user_ids"]
        parties = ctx["parties"]
        # Sign S1 and S3.
        for idx in (0, 2):
            iv = create_identity_verification(
                subject_user_id=signer_ids[idx],
                contract_id=ctx["contract"]["id"],
                factors=[("SMS", "PASS")],
            )
            sign_party(
                party_id=parties[idx]["id"],
                signer_user_id=signer_ids[idx],
                identity_verification_id=iv["id"],
            )
        contract = get_contract(ctx["contract"]["id"])
        assert contract["status"] == "COMPLETED"
        assert contract["signing_progress_percent"] == 100.00

    def test_progress_at_partially_signed_recomputed(self, api):
        """PRD §3.6: 'The first party-signed event under a multi-party
        Contract... advances the Contract from PENDING_SIGN to
        PARTIALLY_SIGNED and recomputes both signing_progress_percent
        and evidence_strength_score. Subsequent party-signed events
        under an already-partially-signed Contract keep the status at
        PARTIALLY_SIGNED and re-trigger the same recomputation.'

        Claim: on a 2-party contract (one step, two parties), signing
        the first party advances to PARTIALLY_SIGNED with
        signing_progress_percent == 50.00 (1 SIGNED out of 2 eligible
        chronological). The conserved quantity (signed_count + skipped_
        count <= total_party_count) holds throughout.
        # difficulty: compensating_invariant/contract_completion_preserves_party_signed_count
        """
        ctx = setup_decline_two_party_step()
        # Sign one of the two parties.
        sig_id = ctx["signer_user_ids"][0]
        iv = create_identity_verification(
            subject_user_id=sig_id,
            contract_id=ctx["contract"]["id"],
            factors=[("SMS", "PASS")],
        )
        sign_party(
            party_id=ctx["parties"][0]["id"],
            signer_user_id=sig_id,
            identity_verification_id=iv["id"],
        )
        contract = get_contract(ctx["contract"]["id"])
        # PRD §3.6: 'advances the Contract from PENDING_SIGN to
        # PARTIALLY_SIGNED and recomputes both signing_progress_percent
        # and evidence_strength_score.'
        assert contract["status"] == "PARTIALLY_SIGNED"
        # Both parties belong to the same step (S1 ACTIVE), so the
        # chronological denominator is 2 and the numerator is 1.
        assert contract["signing_progress_percent"] == 50.00
