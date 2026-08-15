"""Beneficiary claims and the competing-claims machinery: validation gates,
the rival-filing dispute cascade into legal hold, the hold round trip and its
conserved payable liability, and the interpleader gate."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    begin_review,
    create_designation,
    create_policy_with_statute,
    file_beneficiary_claim,
    file_claim,
    file_claim_with_verified_docs,
    get_beneficiary_claim,
    get_claim,
    list_elections,
    set_clock,
    setup_approved_claim,
    setup_election,
    validate_beneficiary_claim,
    validate_error,
    validate_success,
    withdraw_beneficiary_claim,
)

POLICY_ADMIN = TEST_USERS["policy_administrator_headers"]


class TestDisputeCycle:
    def test_rival_filing_disputes_incumbent_from_under_review(
        self, api, claims_examiner_headers
    ):
        """PRD §3.7: "If a rival beneficiary claim on the same designation
        already stands `VALIDATED` or `PAYABLE` under a different
        `claimant_name`, the rival — not the new filing — is cascaded to
        `DISPUTED`, its `version` incrementing, and the parent claim is placed
        in `LEGAL_HOLD`: the claim records its pre-hold state in
        `hold_return_state` (one of `UNDER_REVIEW`, `CONTESTABILITY_REVIEW`, or
        `APPROVED`), every payout election of the claim's beneficiary claims in
        `ELECTED` or `CONFIRMED` is suspended to `SUSPENDED`, and the claim's
        `version` increments."
        PRD §3.7: "The filing itself is always accepted into `SUBMITTED`
        status."

        Design: Difficulty/non_linear_state_machine/beneficiary_claim_dispute_cycle
        """
        policy, designation, claim, alice = _setup_validated_alice()
        eve = file_beneficiary_claim(claim["id"], designation_id=designation["id"],
                                     claimant_name="Eve Smith")
        assert eve["status"] == "SUBMITTED", "The new filing itself is accepted"
        assert get_beneficiary_claim(alice["id"])["status"] == "DISPUTED"
        held = get_claim(claim["id"])
        assert held["status"] == "LEGAL_HOLD"
        assert held["hold_return_state"] == "UNDER_REVIEW"

    def test_dispute_cycle_reentry_releases_hold_to_under_review(
        self, api
    ):
        """PRD §3.7: "A `ClaimsExaminer` validates a beneficiary claim from
        `SUBMITTED` or `DISPUTED` — any other state is rejected with
        `ERR_BENEFICIARY_CLAIM_INVALID_STATE`."
        PRD §3.7: "The legal hold releases automatically: whenever no
        beneficiary claim of the claim remains in `DISPUTED` — because rivals
        were validated, rejected, or withdrawn — the claim returns to the state
        recorded in `hold_return_state`, the field is cleared to null, every
        election suspended by the hold returns from `SUSPENDED` to `ELECTED`
        and must be re-confirmed, and the claim's `version` increments."

        Cycle re-entry: SUBMITTED -> VALIDATED -> DISPUTED (rival filing) ->
        VALIDATED (re-validation after the rival withdraws), releasing the hold.

        Design: Difficulty/non_linear_state_machine/beneficiary_claim_dispute_cycle
        """
        policy, designation, claim, alice = _setup_validated_alice()
        eve = file_beneficiary_claim(claim["id"], designation_id=designation["id"],
                                     claimant_name="Eve Smith")
        withdraw_beneficiary_claim(eve["id"])
        # Alice is still DISPUTED, so the hold persists until she is re-validated.
        assert get_claim(claim["id"])["status"] == "LEGAL_HOLD"

        revalidated = validate_beneficiary_claim(alice["id"])
        assert revalidated["status"] == "VALIDATED", "Cycle re-entry into VALIDATED"
        released = get_claim(claim["id"])
        assert released["status"] == "UNDER_REVIEW", "Hold releases to the recorded return state"
        assert released["hold_return_state"] is None


class TestRivalFilingCascadeFromApproved:
    def test_rival_filing_disputes_incumbent_and_holds_claim(
        self, api
    ):
        """PRD §3.7: "If a rival beneficiary claim on the same designation
        already stands `VALIDATED` or `PAYABLE` under a different
        `claimant_name`, the rival — not the new filing — is cascaded to
        `DISPUTED`, its `version` incrementing, and the parent claim is placed
        in `LEGAL_HOLD`: the claim records its pre-hold state in
        `hold_return_state` (one of `UNDER_REVIEW`, `CONTESTABILITY_REVIEW`, or
        `APPROVED`), every payout election of the claim's beneficiary claims in
        `ELECTED` or `CONFIRMED` is suspended to `SUSPENDED`, and the claim's
        `version` increments."

        Cascade links 1 and 2 from an APPROVED claim: the PAYABLE incumbent
        flips to DISPUTED and the claim drops into LEGAL_HOLD with
        hold_return_state APPROVED; the dispute does not touch the computed
        total.

        Design: Difficulty/transitive_cascade/rival_beneficiary_filing_cascade
        """
        ctx = _setup_approved_pair_with_confirmed_election()
        claim_id = ctx["claim"]["id"]
        alice = ctx["beneficiary_claims"][0]

        eve = file_beneficiary_claim(claim_id,
                                     designation_id=ctx["designations"][0]["id"],
                                     claimant_name="Eve Smith")
        assert eve["status"] == "SUBMITTED", "The rival filing itself stays SUBMITTED"
        assert get_beneficiary_claim(alice["id"])["status"] == "DISPUTED"

        held = get_claim(claim_id)
        assert held["status"] == "LEGAL_HOLD"
        assert held["hold_return_state"] == "APPROVED"
        assert held["total_payable_cents"] == 25068493, (
            "The dispute cascade must not change total_payable_cents")

    def test_rival_filing_suspends_confirmed_election(
        self, api
    ):
        """PRD §3.7: "the parent claim is placed in `LEGAL_HOLD`: the claim
        records its pre-hold state in `hold_return_state` (one of
        `UNDER_REVIEW`, `CONTESTABILITY_REVIEW`, or `APPROVED`), every payout
        election of the claim's beneficiary claims in `ELECTED` or `CONFIRMED`
        is suspended to `SUSPENDED`, and the claim's `version` increments."

        Cascade link 3: the incumbent's CONFIRMED election is driven to
        SUSPENDED by the hold.

        Design: Difficulty/transitive_cascade/rival_beneficiary_filing_cascade
        """
        ctx = _setup_approved_pair_with_confirmed_election()
        claim_id = ctx["claim"]["id"]
        alice = ctx["beneficiary_claims"][0]
        election = ctx["election"]
        assert election["status"] == "CONFIRMED"

        file_beneficiary_claim(claim_id,
                               designation_id=ctx["designations"][0]["id"],
                               claimant_name="Eve Smith")

        elections = list_elections(alice["id"])
        by_id = {e["id"]: e for e in elections}
        assert by_id[election["id"]]["status"] == "SUSPENDED", (
            "CONFIRMED election must be suspended when the claim enters LEGAL_HOLD")


class TestLegalHoldRoundTrip:
    def test_hold_roundtrip_restores_allocations_and_total(
        self, api
    ):
        """PRD §3.7: "When the recorded return state is `APPROVED`, the
        allocation waterfall of §3.6 re-runs so that the validated pool members
        return to `PAYABLE` with recomputed `allocated_amount_cents`; the hold
        never touched `total_payable_cents`, so the restored allocations match
        the pre-hold amounts exactly."

        The conserved quantity is the claim's payable liability:
        15041096 + 10027397 == 25068493 across the hold round trip.

        Design: Difficulty/compensating_invariant/legal_hold_roundtrip_conserves_payable_liability
        """
        ctx = _setup_approved_pair_with_confirmed_election()
        claim_id = ctx["claim"]["id"]
        alice = ctx["beneficiary_claims"][0]
        bob = ctx["beneficiary_claims"][1]
        total_pre = ctx["claim"]["total_payable_cents"]
        assert total_pre == 25068493

        eve = file_beneficiary_claim(claim_id,
                                     designation_id=ctx["designations"][0]["id"],
                                     claimant_name="Eve Smith")
        withdraw_beneficiary_claim(eve["id"])
        validate_beneficiary_claim(alice["id"])  # DISPUTED -> VALIDATED; releases hold

        claim_after = get_claim(claim_id)
        assert claim_after["status"] == "APPROVED"
        assert claim_after["hold_return_state"] is None
        assert claim_after["total_payable_cents"] == total_pre, (
            "No liability drift from the dispute round trip")

        alice_after = get_beneficiary_claim(alice["id"])
        bob_after = get_beneficiary_claim(bob["id"])
        assert alice_after["status"] == "PAYABLE"
        assert alice_after["allocated_amount_cents"] == 15041096
        assert bob_after["allocated_amount_cents"] == 10027397
        assert (alice_after["allocated_amount_cents"]
                + bob_after["allocated_amount_cents"]) == 25068493, (
            "Allocation conservation across the round trip")

    def test_hold_roundtrip_election_drops_back_to_elected(
        self, api
    ):
        """PRD §3.7: "every election suspended by the hold returns from
        `SUSPENDED` to `ELECTED` and must be re-confirmed".

        The one sanctioned drift of the round trip: the incumbent's election
        loses CONFIRMED and must be confirmed again.

        Design: Difficulty/compensating_invariant/legal_hold_roundtrip_conserves_payable_liability
        """
        ctx = _setup_approved_pair_with_confirmed_election()
        claim_id = ctx["claim"]["id"]
        alice = ctx["beneficiary_claims"][0]
        election = ctx["election"]

        eve = file_beneficiary_claim(claim_id,
                                     designation_id=ctx["designations"][0]["id"],
                                     claimant_name="Eve Smith")
        withdraw_beneficiary_claim(eve["id"])
        validate_beneficiary_claim(alice["id"])

        elections = list_elections(alice["id"])
        by_id = {e["id"]: e for e in elections}
        assert by_id[election["id"]]["status"] == "ELECTED", (
            "CONFIRMED was lost through SUSPENDED; re-confirmation is required")
        assert get_claim(claim_id)["status"] == "APPROVED"


class TestValidationReferentialGates:
    def test_designation_policy_mismatch_rejected(
        self, api, claims_examiner_headers
    ):
        """PRD §3.7: "When the claim references a designation, two referential
        checks apply, both at filing and at validation: the designation must
        belong to the same policy as the claim, else
        `ERR_DESIGNATION_POLICY_MISMATCH`, and the designation must have been
        active on the claim's `date_of_death` — the death occurring on or after
        the designation's `effective_date` and, where the designation has been
        revoked, strictly before the revocation date — else
        `ERR_DESIGNATION_NOT_ACTIVE_AT_DEATH`."

        Design: Corner/validations/c_designation_policy_mismatch_rejected
        """
        create_policy_with_statute("IL", policy_number="P-VAL-5A")
        policy_b = create_policy_with_statute("IL", policy_number="P-VAL-5B",
                                              insured_name="Bob Doe",
                                              insured_dob="1971-08-08")
        designation = create_designation(policy_b["id"],
                                         beneficiary_name="Alice Doe",
                                         share_percent=100)
        policies = api.list_policies(claims_examiner_headers).json()["data"]
        policy_a = next(p for p in policies if p["policy_number"] == "P-VAL-5A")
        set_clock("2026-03-05T00:00:00Z")
        claim = file_claim(policy_a["id"], "2026-03-01")

        # The mismatch is a referential violation enforced at filing already.
        resp = api.file_beneficiary_claim(
            claim["id"],
            {"designation_id": designation["id"], "claimant_name": "Alice Doe",
             "claimant_type": "NAMED_BENEFICIARY"},
            claims_examiner_headers)
        validate_error(resp, ApiErrorId.ERR_DESIGNATION_POLICY_MISMATCH)

    def test_designation_already_claimed_rejected(self, api,
                                                  claims_examiner_headers):
        """PRD §3.7: "Exclusivity follows: no other beneficiary claim in
        `VALIDATED` or `PAYABLE` may already hold the same designation, else
        `ERR_DESIGNATION_ALREADY_CLAIMED`."

        The second filing uses the SAME claimant name, so no dispute cascade
        fires; capacity and dispute are distinct mechanisms.

        Design: Corner/validations/c_designation_already_claimed_rejected
        """
        policy = create_policy_with_statute("IL", policy_number="P-VAL-6")
        designation = create_designation(policy["id"], beneficiary_name="Alice Doe",
                                         share_percent=100)
        set_clock("2026-03-05T00:00:00Z")
        claim = file_claim(policy["id"], "2026-03-01")
        begin_review(claim["id"])
        bc1 = file_beneficiary_claim(claim["id"], designation_id=designation["id"],
                                     claimant_name="Alice Doe")
        validate_beneficiary_claim(bc1["id"])
        bc2 = file_beneficiary_claim(claim["id"], designation_id=designation["id"],
                                     claimant_name="Alice Doe")

        resp = api.validate_beneficiary_claim(bc2["id"], claims_examiner_headers)
        validate_error(resp, ApiErrorId.ERR_DESIGNATION_ALREADY_CLAIMED)

        assert get_beneficiary_claim(bc1["id"])["status"] == "VALIDATED"
        assert get_claim(claim["id"])["status"] == "UNDER_REVIEW", (
            "Same claimant_name means no DISPUTED cascade fired")

    def test_validate_designation_effective_after_death_rejected(
        self, api, claims_examiner_headers
    ):
        """PRD §3.7: "the designation must have been active on the claim's
        `date_of_death` — the death occurring on or after the designation's
        `effective_date` and, where the designation has been revoked, strictly
        before the revocation date — else `ERR_DESIGNATION_NOT_ACTIVE_AT_DEATH`."

        A designation whose effective_date (2026-06-01) postdates the death
        (2026-03-01) was not active at death.

        Design: Difficulty/cross_entity_state_dependency/validate_blocked_when_designation_inactive_at_death
        """
        policy = create_policy_with_statute("IL", policy_number="P-XD-2")
        designation = create_designation(policy["id"],
                                         beneficiary_name="Late Larry",
                                         share_percent=100,
                                         effective_date="2026-06-01")
        set_clock("2026-03-05T00:00:00Z")
        claim = file_claim(policy["id"], "2026-03-01")
        bc = file_beneficiary_claim(claim["id"], designation_id=designation["id"],
                                    claimant_name="Late Larry")

        resp = api.validate_beneficiary_claim(bc["id"], claims_examiner_headers)
        validate_error(resp, ApiErrorId.ERR_DESIGNATION_NOT_ACTIVE_AT_DEATH)
        assert get_beneficiary_claim(bc["id"])["status"] == "SUBMITTED"

    def test_validate_designation_revoked_before_death_rejected(
        self, api, claims_examiner_headers
    ):
        """PRD §3.7: "the designation must have been active on the claim's
        `date_of_death` — the death occurring on or after the designation's
        `effective_date` and, where the designation has been revoked, strictly
        before the revocation date — else `ERR_DESIGNATION_NOT_ACTIVE_AT_DEATH`."

        Revocation leg: the designation was revoked (revocation date
        2026-01-15) before the death (2026-03-01), so it was not active at
        death.

        Design: Difficulty/cross_entity_state_dependency/validate_blocked_when_designation_inactive_at_death
        """
        policy = create_policy_with_statute("IL", policy_number="P-XD-2")
        designation = create_designation(policy["id"],
                                         beneficiary_name="Gone Gina",
                                         share_percent=100,
                                         effective_date="2024-03-01")
        set_clock("2026-01-15T00:00:00Z")
        revoked = validate_success(
            api.revoke_beneficiary_designation(designation["id"], POLICY_ADMIN))
        assert revoked["status"] == "REVOKED"

        set_clock("2026-03-05T00:00:00Z")
        claim = file_claim(policy["id"], "2026-03-01")
        bc = file_beneficiary_claim(claim["id"], designation_id=designation["id"],
                                    claimant_name="Gone Gina")

        resp = api.validate_beneficiary_claim(bc["id"], claims_examiner_headers)
        validate_error(resp, ApiErrorId.ERR_DESIGNATION_NOT_ACTIVE_AT_DEATH)
        assert get_beneficiary_claim(bc["id"])["status"] == "SUBMITTED"

    def test_validate_aggregate_capacity_exceeded(
        self, api, claims_examiner_headers
    ):
        """PRD §3.7: "Finally, aggregate capacity caps the whole claim: the sum
        of shares across the beneficiary claims in `VALIDATED` or `PAYABLE`
        plus the candidate — each share being its designation's `share_percent`,
        or 100 for an `ESTATE` claimant — must not exceed 100, else validation
        is rejected with `ERR_ALLOCATION_CAPACITY_EXCEEDED`".

        60 (VALIDATED primary) + 100 (candidate contingent) = 160 > 100.

        Design: Corner/calculations/c_validate_aggregate_capacity_exceeded_rejected
        """
        policy = create_policy_with_statute("TX", policy_number="P-CALC-3")
        d1 = create_designation(policy["id"], beneficiary_name="Alice Roe",
                                share_percent=60)
        d2 = create_designation(policy["id"], beneficiary_name="Carol Roe",
                                beneficiary_type="CONTINGENT", share_percent=100)
        set_clock("2026-03-05T00:00:00Z")
        claim = file_claim(policy["id"], "2026-03-01")
        begin_review(claim["id"])
        bc1 = file_beneficiary_claim(claim["id"], designation_id=d1["id"],
                                     claimant_name="Alice Roe")
        bc2 = file_beneficiary_claim(claim["id"], designation_id=d2["id"],
                                     claimant_name="Carol Roe")
        validate_beneficiary_claim(bc1["id"])

        resp = api.validate_beneficiary_claim(bc2["id"], claims_examiner_headers)
        validate_error(resp, ApiErrorId.ERR_ALLOCATION_CAPACITY_EXCEEDED)
        assert get_beneficiary_claim(bc2["id"])["status"] == "SUBMITTED"
        assert get_beneficiary_claim(bc1["id"])["status"] == "VALIDATED"


class TestBeneficiaryClaimStateGates:
    def test_withdraw_payable_beneficiary_claim_rejected(
        self, api, claims_examiner_headers
    ):
        """PRD §3.7: "Withdrawal is permitted from `SUBMITTED` or `DISPUTED`."
        PRD §3.7: "From any other status, either action is rejected with
        `ERR_BENEFICIARY_CLAIM_INVALID_STATE`."

        Design: Corner/state_machines/c_withdraw_payable_beneficiary_claim_rejected
        """
        ctx = setup_approved_claim(state="TX", policy_overrides={
            "policy_number": "P-SM-9"})
        bc = ctx["beneficiary_claims"][0]
        assert get_beneficiary_claim(bc["id"])["status"] == "PAYABLE"

        resp = api.withdraw_beneficiary_claim(bc["id"], claims_examiner_headers)
        validate_error(resp, ApiErrorId.ERR_BENEFICIARY_CLAIM_INVALID_STATE)
        assert get_beneficiary_claim(bc["id"])["status"] == "PAYABLE"

    def test_interpleader_requires_legal_hold(self, api, legal_counsel_headers):
        """PRD §3.7: "Referral requires the claim to be in `LEGAL_HOLD` — from
        any other state it is rejected with `ERR_CLAIM_NOT_IN_LEGAL_HOLD` — and
        requires a `court_reference`."

        Design: Corner/state_machines/c_interpleader_requires_legal_hold
        """
        policy = create_policy_with_statute("IL", policy_number="P-SM-10")
        claim, _docs = file_claim_with_verified_docs(policy["id"], "2026-03-01")
        assert claim["status"] == "UNDER_REVIEW"

        resp = api.refer_interpleader(claim["id"],
                                      {"court_reference": "2026-CV-0001"},
                                      legal_counsel_headers)
        validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_IN_LEGAL_HOLD)
        assert get_claim(claim["id"])["status"] == "UNDER_REVIEW"


# ---------------------------------------------------------------------------
# Shared scenario builders
# ---------------------------------------------------------------------------

def _setup_validated_alice():
    """IL policy + non-contestable claim UNDER_REVIEW + Alice's beneficiary
    claim VALIDATED against her 100% PRIMARY designation."""
    policy = create_policy_with_statute("IL", policy_number="P-CYC-1")
    designation = create_designation(policy["id"], beneficiary_name="Alice Doe",
                                     share_percent=100)
    claim, _docs = file_claim_with_verified_docs(policy["id"], "2026-03-01")
    alice = file_beneficiary_claim(claim["id"], designation_id=designation["id"],
                                   claimant_name="Alice Doe")
    validate_beneficiary_claim(alice["id"])
    return policy, designation, claim, alice


def _setup_approved_pair_with_confirmed_election():
    """IL policy face 25000000, Alice 60% / Bob 40% PRIMARY; claim approved at
    the 2026-04-10 logical clock (total 25068493; allocations 15041096 /
    10027397); Alice's LUMP_SUM election CONFIRMED."""
    ctx = setup_approved_claim(
        state="IL",
        face_amount_cents=25000000,
        beneficiaries=[
            {"name": "Alice Doe", "type": "PRIMARY", "share": 60},
            {"name": "Bob Doe", "type": "PRIMARY", "share": 40},
        ],
        approve_clock="2026-04-10T00:00:00Z",
        policy_overrides={"policy_number": "P-CAS-1"},
    )
    assert ctx["claim"]["total_payable_cents"] == 25068493
    setup_election(ctx, option="LUMP_SUM", confirm=True, beneficiary_index=0)
    return ctx
