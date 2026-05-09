"""Contract creation, signing, signature ordering, fully-signed cascade
into License.SIGNED, and supplementary contracts (PRD §3.5, §3.6)."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    create_rights_holder,
    create_two_rights_holders,
    create_registered_work,
    create_offered_license,
    accept_offered_license,
    setup_accepted_license,
    setup_signed_license,
    setup_effective_license,
    create_pending_contract,
    sign_contract_in_order,
    create_contract_payload,
    signature_payload,
    list_rights_chain_events,
    list_audit_logs_filtered,
    advance_clock_to,
    assert_contract,
    assert_signature,
    make_rights_holder_headers,
    ADMIN_HEADERS,
)


# ---------------------------------------------------------------------------
# Contract creation guards
# ---------------------------------------------------------------------------

class TestContractCreationGuards:
    """PRD §3.5: "From an ACCEPTED license, any participant can create a
    primary contract by submitting the license_id (which must currently be
    in ACCEPTED, otherwise ERR_LICENSE_NOT_ACCEPTED)."
    """

    def test_create_contract_on_offered_license_rejected(self, api):
        """PRD §3.5: license must be ACCEPTED → ERR_LICENSE_NOT_ACCEPTED.

        # difficulty: cross_entity_state_dependency/contract_create_requires_license_accepted
        """
        licensor, licensee = create_two_rights_holders(api)
        work, _ = create_registered_work(api, owner=licensor)
        # License remains in OFFERED — not accepted.
        license_data = create_offered_license(api, work, licensor, licensee)
        headers = make_rights_holder_headers(licensor["id"])
        payload = create_contract_payload(
            license_id=license_data["id"],
            signing_order=[licensor["id"], licensee["id"]],
            effective_date_target="2099-03-01T00:00:00.000Z",
        )
        resp = api.create_contract(payload, headers)
        validate_error(resp, ApiErrorId.ERR_LICENSE_NOT_ACCEPTED.value)

    def test_create_contract_on_withdrawn_license_rejected(self, api):
        """PRD §3.5: license must be ACCEPTED → ERR_LICENSE_NOT_ACCEPTED.

        Even a previously offered license that has been withdrawn (now in
        the terminal WITHDRAWN state) cannot have a contract created against
        it.

        # difficulty: cross_entity_state_dependency/contract_create_requires_license_accepted
        """
        licensor, licensee = create_two_rights_holders(api)
        work, _ = create_registered_work(api, owner=licensor)
        license_data = create_offered_license(api, work, licensor, licensee)
        # Licensor withdraws.
        from test_helpers import round_payload
        headers_l = make_rights_holder_headers(licensor["id"])
        api.submit_round(license_data["id"],
                           round_payload(action="WITHDRAW",
                                           version=license_data["version"]),
                           headers_l)
        # License is now WITHDRAWN. Try to create a contract.
        resp = api.create_contract(create_contract_payload(
            license_id=license_data["id"],
            signing_order=[licensor["id"], licensee["id"]],
            effective_date_target="2099-03-01T00:00:00.000Z",
        ), headers_l)
        validate_error(resp, ApiErrorId.ERR_LICENSE_NOT_ACCEPTED.value)

    def test_create_contract_effective_date_before_term_start_rejected(self, api):
        """PRD §3.5: 'The target effective date must satisfy term_start <=
        effective_date_target and effective_date_target < term_end of the
        underlying license; ... a target outside this half-open interval is
        rejected with ERR_EFFECTIVE_DATE_OUT_OF_TERM.'"""
        bundle = setup_accepted_license(
            api,
            term_start="2099-06-01T00:00:00.000Z",
            term_end="2099-12-01T00:00:00.000Z",
        )
        license_data = bundle["license"]
        licensor, licensee = bundle["licensor"], bundle["licensee"]
        headers = make_rights_holder_headers(licensor["id"])
        # effective_date_target before term_start
        payload = create_contract_payload(
            license_id=license_data["id"],
            signing_order=[licensor["id"], licensee["id"]],
            effective_date_target="2099-01-01T00:00:00.000Z",
        )
        resp = api.create_contract(payload, headers)
        validate_error(resp, ApiErrorId.ERR_EFFECTIVE_DATE_OUT_OF_TERM.value)

    def test_create_contract_effective_date_at_term_end_rejected(self, api):
        """PRD §3.5: '... effective_date_target < term_end' (upper bound exclusive)."""
        bundle = setup_accepted_license(
            api,
            term_start="2099-01-01T00:00:00.000Z",
            term_end="2099-12-01T00:00:00.000Z",
        )
        license_data = bundle["license"]
        licensor, licensee = bundle["licensor"], bundle["licensee"]
        headers = make_rights_holder_headers(licensor["id"])
        payload = create_contract_payload(
            license_id=license_data["id"],
            signing_order=[licensor["id"], licensee["id"]],
            effective_date_target="2099-12-01T00:00:00.000Z",  # equals term_end
        )
        resp = api.create_contract(payload, headers)
        validate_error(resp, ApiErrorId.ERR_EFFECTIVE_DATE_OUT_OF_TERM.value)

    def test_create_contract_pending_signatures_initial_state(self, api):
        """PRD §3.5: 'The new contract begins in PENDING_SIGNATURES with
        signed_count of 0 and fully_signed_at unset.'"""
        bundle = setup_accepted_license(api)
        # effective_date_target defaults to license.term_start (PRD §3.5 lower
        # bound inclusive). The specific date is irrelevant to this assertion.
        contract = create_pending_contract(
            api, bundle["license"],
            licensor=bundle["licensor"], licensee=bundle["licensee"],
        )
        assert contract["status"] == "PENDING_SIGNATURES"
        assert contract["signed_count"] == 0
        assert contract.get("fully_signed_at") is None


# ---------------------------------------------------------------------------
# Signature ordering and duplicate detection
# ---------------------------------------------------------------------------

class TestSignatureOrdering:
    """PRD §3.5: "signer_id must equal the element of signing_order at the
    index signed_count (treating signing_order as 0-indexed) — that is, the
    contract demands signers in the exact order they were listed, and any
    mismatch is rejected with ERR_SIGNATURE_OUT_OF_ORDER."
    """

    def test_first_signer_must_match_signing_order_zero(self, api):
        """PRD §3.5: out-of-order signer → ERR_SIGNATURE_OUT_OF_ORDER."""
        bundle = setup_accepted_license(api)
        licensor, licensee = bundle["licensor"], bundle["licensee"]
        contract = create_pending_contract(
            api, bundle["license"],
            licensor=licensor, licensee=licensee,
            signing_order=[licensor["id"], licensee["id"]],
        )
        # licensee tries to sign first, but signing_order[0] == licensor.
        headers = make_rights_holder_headers(licensee["id"])
        resp = api.submit_signature(
            contract["id"],
            signature_payload(signer_id=licensee["id"], version=contract["version"]),
            headers,
        )
        validate_error(resp, ApiErrorId.ERR_SIGNATURE_OUT_OF_ORDER.value)

    def test_signer_id_mismatching_x_user_id_forbidden(self, api):
        """PRD §2.1 / §4: 'POST /contracts/{contractId}/signatures (caller
        must equal signer_id ...)'. The caller's X-User-ID must match the
        submitted signer_id (RightsHolder ownership semantics)."""
        bundle = setup_accepted_license(api)
        licensor, licensee = bundle["licensor"], bundle["licensee"]
        contract = create_pending_contract(
            api, bundle["license"],
            licensor=licensor, licensee=licensee,
            signing_order=[licensor["id"], licensee["id"]],
        )
        # Licensee headers but signer_id=licensor → ownership mismatch.
        headers = make_rights_holder_headers(licensee["id"])
        resp = api.submit_signature(
            contract["id"],
            signature_payload(signer_id=licensor["id"], version=contract["version"]),
            headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_duplicate_signature_rejected(self, api):
        """PRD §3.5: 'the same signer_id must not already have a Signature on
        this contract; a repeat is rejected with ERR_DUPLICATE_SIGNATURE.'

        We force a duplicate by configuring a signing order that lists the
        same signer twice — the platform must detect this on the second
        submission. This is the only PRD-faithful path to the dup error.
        """
        bundle = setup_accepted_license(api)
        licensor, licensee = bundle["licensor"], bundle["licensee"]
        # signing_order lists licensor twice. signed_count starts at 0 ->
        # licensor signs (signed_count=1). signed_count=1 still expects
        # licensor (per signing_order[1]) so licensor's second submission
        # passes the ordering gate; the duplicate check then triggers.
        contract = create_pending_contract(
            api, bundle["license"],
            licensor=licensor, licensee=licensee,
            signing_order=[licensor["id"], licensor["id"]],
        )
        headers = make_rights_holder_headers(licensor["id"])
        # First signature OK
        resp = api.submit_signature(
            contract["id"],
            signature_payload(signer_id=licensor["id"], version=contract["version"]),
            headers,
        )
        validate_success(resp, expected_status=201)
        # Re-fetch contract for new version
        contract = api.get_contract(contract["id"], ADMIN_HEADERS).json()["data"]
        # Second signature by same signer — duplicate.
        resp = api.submit_signature(
            contract["id"],
            signature_payload(signer_id=licensor["id"], version=contract["version"]),
            headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_SIGNATURE.value)


# ---------------------------------------------------------------------------
# Signature completion cascades to FULLY_SIGNED + License.SIGNED
# ---------------------------------------------------------------------------

class TestSignatureCompletionCascade:
    """PRD §3.5: "When signed_count reaches len(signing_order) ... the server
    auto-transitions the contract from PENDING_SIGNATURES to FULLY_SIGNED,
    sets fully_signed_at to the current instant, writes an AuditLog of
    CONTRACT_AMENDED, and propagates the cascade to the underlying license:
    the License.status advances from ACCEPTED to SIGNED."
    """

    def test_signature_completion_cascades_license_to_signed(self, api):
        """PRD §3.5: depth-2 cascade Contract.FULLY_SIGNED → License.SIGNED.
        PRD §3.5: 'appends a RightsChainEvent of event_type LICENSE_SIGNED.'

        # difficulty: transitive_cascade/signature_completion_cascade_depth_two
        """
        bundle = setup_accepted_license(api)
        licensor, licensee = bundle["licensor"], bundle["licensee"]
        contract = create_pending_contract(
            api, bundle["license"],
            licensor=licensor, licensee=licensee,
            signing_order=[licensor["id"], licensee["id"]],
        )
        contract = sign_contract_in_order(api, contract, [licensor, licensee])
        assert contract["status"] == "FULLY_SIGNED"
        assert contract.get("fully_signed_at") is not None
        # License must have cascaded to SIGNED.
        license_data = api.get_license(bundle["license"]["id"], ADMIN_HEADERS).json()["data"]
        assert license_data["status"] == "SIGNED", (
            f"PRD §3.5: License must auto-cascade to SIGNED; got {license_data['status']}"
        )
        # Rights chain must show LICENSE_SIGNED for the work.
        events = list_rights_chain_events(api, bundle["work"]["id"])
        assert any(
            e["event_type"] == "LICENSE_SIGNED" and e["ref_id"] == bundle["license"]["id"]
            and e["ref_entity"] == "License"
            for e in events
        ), (
            "PRD §3.5: License entering SIGNED must append RightsChainEvent "
            "with event_type=LICENSE_SIGNED and ref_id=license.id"
        )

    def test_full_signing_writes_contract_amended_audit_log(self, api):
        """PRD §3.5: 'writes an AuditLog of CONTRACT_AMENDED, and propagates
        the cascade to the underlying license.'

        # difficulty: transitive_cascade/signature_completion_cascade_depth_two
        """
        bundle = setup_accepted_license(api)
        licensor, licensee = bundle["licensor"], bundle["licensee"]
        contract = create_pending_contract(
            api, bundle["license"],
            licensor=licensor, licensee=licensee,
            signing_order=[licensor["id"], licensee["id"]],
        )
        sign_contract_in_order(api, contract, [licensor, licensee])
        logs = list_audit_logs_filtered(api,
                                          subject_id=contract["id"],
                                          change_type="CONTRACT_AMENDED")
        assert len(logs) >= 1, (
            "PRD §3.5: contract reaching FULLY_SIGNED must write an AuditLog "
            "of change_type CONTRACT_AMENDED"
        )

    def test_first_signature_does_not_advance_license(self, api):
        """PRD §3.5: cascade only fires when signed_count == len(signing_order)."""
        bundle = setup_accepted_license(api)
        licensor, licensee = bundle["licensor"], bundle["licensee"]
        contract = create_pending_contract(
            api, bundle["license"],
            licensor=licensor, licensee=licensee,
            signing_order=[licensor["id"], licensee["id"]],
        )
        # Only the licensor signs (1 of 2).
        sign_contract_in_order(api, contract, [licensor])
        contract = api.get_contract(contract["id"], ADMIN_HEADERS).json()["data"]
        assert contract["status"] == "PENDING_SIGNATURES"
        assert contract["signed_count"] == 1
        license_data = api.get_license(bundle["license"]["id"], ADMIN_HEADERS).json()["data"]
        assert license_data["status"] == "ACCEPTED"


# ---------------------------------------------------------------------------
# Effective-date boundary
# ---------------------------------------------------------------------------

class TestEffectiveDateBoundary:
    """PRD §3.6: "the candidate effective instant is the later of
    Contract.effective_date_target and License.term_start (max of the two),
    and the system advances the license to EFFECTIVE only when the wall
    clock reaches that candidate, with the boundary inclusive — at the
    precise instant the clock equals the candidate, the transition fires."
    """

    def test_clock_one_second_before_does_not_fire(self, api):
        """PRD §3.6: 'Before that instant the license stays SIGNED and
        effective_date remains unset.'

        # difficulty: boundary_precision_check/clock_advance_exact_effective_date
        """
        bundle = setup_signed_license(
            api,
            term_start="2099-01-01T00:00:00.000Z",
            term_end="2100-01-01T00:00:00.000Z",
            effective_date_target="2099-03-01T00:00:00.000Z",
        )
        # Advance clock to one second BEFORE candidate.
        advance_clock_to(api, "2099-02-28T23:59:59.000Z")
        license_data = api.get_license(bundle["license"]["id"], ADMIN_HEADERS).json()["data"]
        assert license_data["status"] == "SIGNED", (
            f"PRD §3.6: clock < candidate must NOT fire SIGNED→EFFECTIVE; "
            f"got status={license_data['status']}"
        )
        assert license_data.get("effective_date") is None

    def test_clock_at_exact_instant_fires_transition(self, api):
        """PRD §3.6: 'at the precise instant the clock equals the candidate,
        the transition fires.'

        # difficulty: boundary_precision_check/clock_advance_exact_effective_date
        """
        bundle = setup_signed_license(
            api,
            term_start="2099-01-01T00:00:00.000Z",
            term_end="2100-01-01T00:00:00.000Z",
            effective_date_target="2099-03-01T00:00:00.000Z",
        )
        advance_clock_to(api, "2099-03-01T00:00:00.000Z")
        license_data = api.get_license(bundle["license"]["id"], ADMIN_HEADERS).json()["data"]
        assert license_data["status"] == "EFFECTIVE", (
            f"PRD §3.6: clock == candidate must fire SIGNED→EFFECTIVE; "
            f"got status={license_data['status']}"
        )
        assert license_data.get("effective_date") is not None
        # Contract should have advanced jointly.
        contract = api.get_contract(bundle["contract"]["id"], ADMIN_HEADERS).json()["data"]
        assert contract["status"] == "EFFECTIVE", (
            "PRD §3.6: 'the contract advances jointly from FULLY_SIGNED to EFFECTIVE'"
        )


# ---------------------------------------------------------------------------
# Manual termination + supplementary contract = SUPERSEDED
# ---------------------------------------------------------------------------

class TestContractTerminationAndSupersedence:
    """PRD §3.6: "Manual termination is restricted to the licensor_id
    (ERR_FORBIDDEN otherwise) ... cascades the underlying contract: any
    EFFECTIVE contract whose License.status has just become TERMINATED
    advances itself from EFFECTIVE to TERMINATED."
    """

    def test_manual_terminate_by_licensor_cascades_contract(self, api):
        """PRD §3.6: License manual terminate → Contract auto-transitions to
        TERMINATED with AuditLog CONTRACT_AMENDED.

        # difficulty: non_linear_state_machine/contract_branching_supersede_or_terminate
        """
        bundle = setup_effective_license(api)
        licensor = bundle["licensor"]
        license_data = bundle["license"]
        headers = make_rights_holder_headers(licensor["id"])
        resp = api.terminate_license(license_data["id"], headers,
                                       payload={"version": license_data["version"]})
        validate_success(resp)
        # Re-read License + Contract
        license_data = api.get_license(license_data["id"], ADMIN_HEADERS).json()["data"]
        contract = api.get_contract(bundle["contract"]["id"], ADMIN_HEADERS).json()["data"]
        assert license_data["status"] == "TERMINATED"
        assert contract["status"] == "TERMINATED", (
            "PRD §3.6: License → TERMINATED cascades Contract → TERMINATED"
        )
        # Rights chain records LICENSE_TERMINATED with reason MANUAL.
        events = list_rights_chain_events(api, bundle["work"]["id"])
        manual_terminations = [
            e for e in events
            if e["event_type"] == "LICENSE_TERMINATED"
            and (e.get("payload") or {}).get("reason") == "MANUAL"
        ]
        assert len(manual_terminations) >= 1, (
            "PRD §3.6: 'appends a RightsChainEvent of LICENSE_TERMINATED whose "
            "payload reason is MANUAL'"
        )

    def test_manual_terminate_by_non_licensor_rejected(self, api):
        """PRD §3.6: 'Manual termination is restricted to the licensor_id
        (ERR_FORBIDDEN otherwise).'"""
        bundle = setup_effective_license(api)
        licensee = bundle["licensee"]
        headers = make_rights_holder_headers(licensee["id"])
        resp = api.terminate_license(bundle["license"]["id"], headers,
                                       payload={"version": bundle["license"]["version"]})
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    # DELETED: test_supplementary_contract_supersedes_parent
    # PRD §3.5 states "From an ACCEPTED license, any participant can create
    # a primary contract by submitting the license_id (which must currently
    # be in ACCEPTED, otherwise ERR_LICENSE_NOT_ACCEPTED) ... A supplementary
    # agreement is created the same way but supplies parent_contract_id ...
    # the parent must be EFFECTIVE to be supplemented".
    # PRD §3.6 then asserts a parent EFFECTIVE→SUPERSEDED cascade when a
    # supplementary reaches FULLY_SIGNED.
    # These two clauses are mutually exclusive in normal flow: once the
    # parent is EFFECTIVE, the underlying License has cascaded past
    # ACCEPTED. PRD does not state which clause prevails for supplementary
    # contracts, so a faithful PRD-only reader can produce two divergent
    # implementations: (a) relax the ACCEPTED check for supplementary so
    # the §3.6 cascade is reachable, or (b) keep the ACCEPTED check and
    # treat the §3.6 cascade as unreachable in the modeled state space.
    # Per the Step 1b unique-derivability rule the test must be deleted —
    # the PRD does not uniquely determine the asserted behavior.
