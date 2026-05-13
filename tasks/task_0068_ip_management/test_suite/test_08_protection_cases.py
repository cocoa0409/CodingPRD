"""ProtectionCase tests for the IP Management API.

Covers PRD §3.6:
- Routing preconditions: agent jurisdiction must match
  (ERR_AGENT_JURISDICTION_MISMATCH); LITIGATION requires evidence with
  chain_of_custody_hash (ERR_EVIDENCE_MISSING_FOR_LITIGATION)
- Resolution: outcome-vs-recovered_amount constraint
- Damages waterfall (legal → agent → punitive → rights_holder) conservation
"""

from test_helpers import (
    ApiErrorId,
    add_evidence,
    assert_damages_waterfall_invariant,
    assert_protection_case,
    expected_waterfall,
    resolve_protection_case_payload,
    route_protection_case_payload,
    setup_case_in_progress,
    setup_foundation,
    setup_protection_case_open,
    validate_error,
    validate_success,
)


# ─────────────────────────────────────────────────────────────
# Routing preconditions (PRD §3.6)
# ─────────────────────────────────────────────────────────────


class TestCaseRouting:
    """PRD §3.6 /route preconditions."""

    def test_litigation_without_chain_of_custody_evidence_rejected(
        self, api, counsel_headers
    ):
        """PRD §3.6: "when `route` is `LITIGATION`, at least one `Evidence`
        row on the case must have a non-null `chain_of_custody_hash` (failure
        returns `ERR_EVIDENCE_MISSING_FOR_LITIGATION`)".

        Claim: routing to LITIGATION on a case with only chain-of-custody-null
        evidence → ERR_EVIDENCE_MISSING_FOR_LITIGATION (422).
        """
        seed = setup_protection_case_open(api, walk_ip_to="REGISTERED")
        # Add evidence WITHOUT chain_of_custody_hash.
        add_evidence(
            api, case_id=seed["case"]["id"], with_chain_of_custody_hash=False
        )
        resp = api.route_protection_case(
            seed["case"]["id"],
            route_protection_case_payload("LITIGATION"),
            counsel_headers,
        )
        validate_error(
            resp,
            ApiErrorId.ERR_EVIDENCE_MISSING_FOR_LITIGATION,
            expected_status=422,
        )

    def test_route_demand_letter_succeeds(self, api, counsel_headers):
        """PRD §3.6: "The `Counsel` then routes the case from `OPEN` to
        `IN_PROGRESS` by supplying a `route` of `DEMAND_LETTER`, `LITIGATION`,
        `MEDIATION`, or `ARBITRATION`."

        Claim: routing OPEN case to DEMAND_LETTER (no LITIGATION evidence
        requirement) → IN_PROGRESS, route=DEMAND_LETTER.
        """
        seed = setup_protection_case_open(api, walk_ip_to="REGISTERED")
        resp = api.route_protection_case(
            seed["case"]["id"],
            route_protection_case_payload("DEMAND_LETTER"),
            counsel_headers,
        )
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "IN_PROGRESS"
        assert data["route"] == "DEMAND_LETTER"

    def test_route_with_jurisdiction_mismatch_rejected(self, api, counsel_headers):
        """PRD §3.6: "the case's `assigned_agent_id` must resolve to an
        `Agent` whose `jurisdictions` array contains the parent `IPRight`'s
        `primary_jurisdiction` (failure returns
        `ERR_AGENT_JURISDICTION_MISMATCH`)".

        Claim: agent with jurisdictions=['JP'] on a case for an IPRight
        with primary_jurisdiction='US' → ERR_AGENT_JURISDICTION_MISMATCH on
        /route.
        """
        seed = setup_protection_case_open(
            api,
            primary_jurisdiction="US",
            agent_jurisdictions=["JP"],  # mismatch
            walk_ip_to="REGISTERED",
        )
        # Add evidence so the evidence rule doesn't pre-empt.
        add_evidence(api, case_id=seed["case"]["id"])
        resp = api.route_protection_case(
            seed["case"]["id"],
            route_protection_case_payload("DEMAND_LETTER"),
            counsel_headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_AGENT_JURISDICTION_MISMATCH, expected_status=422
        )


# ─────────────────────────────────────────────────────────────
# Resolution (PRD §3.6)
# ─────────────────────────────────────────────────────────────


class TestResolution:
    """PRD §3.6 — outcome implies a constraint on recovered_amount_cents,
    and the damages waterfall conservation property holds."""

    # DELETED: test_resolution_won_with_zero_amount_rejected.
    # PRD §3.6 says "a `WON` outcome requires `recovered_amount_cents` strictly
    # greater than zero" but does NOT name an error_id for this constraint
    # failure. PRD §5's error catalogue contains no
    # ERR_OUTCOME_AMOUNT_MISMATCH, and PRD §2.7 priority 5 applies to entity
    # state, not to outcome/amount consistency. A faithful PRD reader could
    # implement this as ERR_INVALID_STATE OR ERR_BAD_REQUEST. PRD-unique-
    # derivability deletion.

    def test_waterfall_conservation_invariant(self, api, counsel_headers):
        """PRD §3.6: "The `distributed` object captures the four amounts as
        `legal_paid`, `agent_paid`, `punitive_paid`, and `rights_holder_paid`;
        their sum is exactly equal to `recovered_amount_cents`."

        Claim: after WON resolution, sum of distributed equals
        recovered_amount_cents exactly.
        """
        seed = setup_case_in_progress(api, route="LITIGATION")
        # recovered 10_000_000, legal 1_500_000, agent 800_000, punitive 2_000_000.
        resp = api.resolve_protection_case(
            seed["case"]["id"],
            resolve_protection_case_payload(
                outcome="WON",
                recovered_amount_cents=10_000_000,
                legal_fees_cents=1_500_000,
                agent_fees_cents=800_000,
                punitive_cap_cents=2_000_000,
            ),
            counsel_headers,
        )
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "RESOLVED"
        assert_damages_waterfall_invariant(data)
        # And the explicit per-bucket values: legal → agent → punitive → holder.
        expected = expected_waterfall(
            recovered=10_000_000,
            legal=1_500_000,
            agent=800_000,
            punitive_cap=2_000_000,
        )
        assert data["distributed"] == expected

    def test_waterfall_legal_clamped_to_remaining(self, api, counsel_headers):
        """PRD §3.6: "Starting from a remaining balance equal to
        `recovered_amount_cents`, the legal bucket is paid the minimum of the
        remaining balance and `legal_fees_cents`, and the remaining balance is
        reduced by that paid amount."

        Claim: when legal_fees > recovered_amount, legal_paid == recovered
        and downstream buckets are 0.
        """
        seed = setup_case_in_progress(api, route="LITIGATION")
        resp = api.resolve_protection_case(
            seed["case"]["id"],
            resolve_protection_case_payload(
                outcome="WON",
                recovered_amount_cents=500_000,
                legal_fees_cents=1_500_000,
                agent_fees_cents=800_000,
                punitive_cap_cents=2_000_000,
            ),
            counsel_headers,
        )
        data = validate_success(resp, expected_status=200)
        dist = data["distributed"]
        assert dist["legal_paid"] == 500_000
        assert dist["agent_paid"] == 0
        assert dist["punitive_paid"] == 0
        assert dist["rights_holder_paid"] == 0
        assert_damages_waterfall_invariant(data)
