"""Policy terms and the two-party verification cycle: half-open overlap
exclusion, and the dispute / reopen loop that drags the note backwards.
"""

from test_helpers import (
    ApiErrorId,
    add_on_finance_charge_cents,
    factories,
    fixtures,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import ANALYST_ORIGIN, COMPLIANCE


def _term_context(api):
    """Clock at 2026-08-15, a licensed TX regime, parties, three DRAFT notes."""
    ctx = fixtures.origination_context(api)
    notes = []
    for _ in range(3):
        notes.append(
            get_success_data(
                api.create_agreement(
                    factories.agreement(
                        ctx["insured_id"], ctx["agent_id"], ctx["rule_id"]
                    ),
                    ANALYST_ORIGIN,
                )
            )["id"]
        )
    ctx["note_ids"] = notes
    return ctx


def _policy(ctx, policy_number, gross, effective, expiration):
    return factories.financed_policy(
        ctx["insurer_id"],
        policy_number=policy_number,
        gross_premium_cents=gross,
        effective_date=effective,
        expiration_date=expiration,
    )


class TestPolicyTermOverlapExclusion:
    """The exclusion is a half-open interval intersection scoped to one carrier's
    policy number."""

    def test_adjacent_renewal_terms_are_accepted(self, api):
        """A renewal starting on the day the prior term expires shares no covered
        day and is accepted.

        The PRD states: "terms that merely touch, where the earlier expiration
        date equals the new effective date, are accepted."

        Design: Difficulty/resource_temporal_overlap/policy_term_half_open_overlap_and_adjacency
        """
        ctx = _term_context(api)
        anchor_note, touching_note, chain_note = ctx["note_ids"]

        anchor = validate_success(
            api.attach_policy(
                anchor_note,
                _policy(ctx, "MC-TX-3001", 600000, "2026-09-01", "2027-09-01"),
                ANALYST_ORIGIN,
            ),
            201,
        )
        assert anchor["status"] == "PENDING_VERIFICATION", (
            "a successful attachment stamps the policy PENDING_VERIFICATION"
        )

        touching = validate_success(
            api.attach_policy(
                touching_note,
                _policy(ctx, "MC-TX-3001", 620000, "2027-09-01", "2028-09-01"),
                ANALYST_ORIGIN,
            ),
            201,
        )
        assert touching["status"] == "PENDING_VERIFICATION"

        chained = validate_success(
            api.attach_policy(
                chain_note,
                _policy(ctx, "MC-TX-3001", 640000, "2028-09-01", "2029-09-01"),
                ANALYST_ORIGIN,
            ),
            201,
        )
        assert chained["status"] == "PENDING_VERIFICATION", (
            "the chain of adjacent terms may keep extending"
        )

    def test_one_shared_day_is_rejected(self, api):
        """A term sharing a single day with an existing term is refused.

        The PRD states: "A new policy may not overlap an existing one: if any
        other policy with the same carrier and the same `policy_number` whose
        `status` is not `CANCELLED` has a half-open term that overlaps the new
        term, the attachment is refused with `ERR_POLICY_TERM_OVERLAP` (HTTP
        409)".

        Design: Difficulty/resource_temporal_overlap/policy_term_half_open_overlap_and_adjacency
        """
        ctx = _term_context(api)
        anchor_note, _touching_note, third_note = ctx["note_ids"]
        validate_success(
            api.attach_policy(
                anchor_note,
                _policy(ctx, "MC-TX-3001", 600000, "2026-09-01", "2027-09-01"),
                ANALYST_ORIGIN,
            ),
            201,
        )
        validate_success(
            api.attach_policy(
                _touching_note,
                _policy(ctx, "MC-TX-3001", 620000, "2027-09-01", "2028-09-01"),
                ANALYST_ORIGIN,
            ),
            201,
        )

        validate_error(
            api.attach_policy(
                third_note,
                _policy(ctx, "MC-TX-3001", 640000, "2027-08-31", "2028-08-31"),
                ANALYST_ORIGIN,
            ),
            ApiErrorId.POLICY_TERM_OVERLAP.value,
            409,
        )

    def test_a_straddling_term_is_rejected(self, api):
        """A short term that brackets an existing effective date is refused, so
        the check is a real interval intersection.

        The PRD states: "The coverage interval is half-open — the effective date
        is inside the term and the expiration date is the exclusive upper bound".

        Design: Difficulty/resource_temporal_overlap/policy_term_half_open_overlap_and_adjacency
        """
        ctx = _term_context(api)
        anchor_note, _second, third_note = ctx["note_ids"]
        validate_success(
            api.attach_policy(
                anchor_note,
                _policy(ctx, "MC-TX-3001", 600000, "2026-09-01", "2027-09-01"),
                ANALYST_ORIGIN,
            ),
            201,
        )

        validate_error(
            api.attach_policy(
                third_note,
                _policy(ctx, "MC-TX-3001", 640000, "2026-08-31", "2026-09-02"),
                ANALYST_ORIGIN,
            ),
            ApiErrorId.POLICY_TERM_OVERLAP.value,
            409,
        )

    def test_a_different_policy_number_may_occupy_the_same_dates(self, api):
        """The exclusion is keyed on the carrier and the policy number together,
        and rejected attachments create nothing.

        The PRD states: "A successful attachment stamps the policy
        `PENDING_VERIFICATION`, sets `carried_over` to false, provisionally sets
        `financed_premium_cents` equal to `gross_premium_cents`, increments the
        agreement's `policy_count` and advances the agreement's `version`."

        Design: Difficulty/resource_temporal_overlap/policy_term_half_open_overlap_and_adjacency
        """
        ctx = _term_context(api)
        anchor_note, touching_note, third_note = ctx["note_ids"]
        validate_success(
            api.attach_policy(
                anchor_note,
                _policy(ctx, "MC-TX-3001", 600000, "2026-09-01", "2027-09-01"),
                ANALYST_ORIGIN,
            ),
            201,
        )
        validate_success(
            api.attach_policy(
                touching_note,
                _policy(ctx, "MC-TX-3001", 620000, "2027-09-01", "2028-09-01"),
                ANALYST_ORIGIN,
            ),
            201,
        )
        validate_error(
            api.attach_policy(
                third_note,
                _policy(ctx, "MC-TX-3001", 640000, "2027-08-31", "2028-08-31"),
                ANALYST_ORIGIN,
            ),
            ApiErrorId.POLICY_TERM_OVERLAP.value,
            409,
        )
        validate_success(
            api.attach_policy(
                third_note,
                _policy(ctx, "MC-TX-3001", 640000, "2028-09-01", "2029-09-01"),
                ANALYST_ORIGIN,
            ),
            201,
        )

        unrelated = validate_success(
            api.attach_policy(
                third_note,
                _policy(ctx, "MC-TX-9999", 300000, "2026-09-01", "2027-09-01"),
                ANALYST_ORIGIN,
            ),
            201,
        )
        assert unrelated["status"] == "PENDING_VERIFICATION", (
            "a different policy number of the same carrier may occupy exactly "
            "the anchor term's dates"
        )
        assert unrelated["financed_premium_cents"] == 300000, (
            "attachment provisionally sets financed_premium_cents equal to "
            "gross_premium_cents"
        )
        assert unrelated["carried_over"] is False

        validate_error(
            api.attach_policy(
                third_note,
                _policy(ctx, "MC-TX-3001", 640000, "2026-08-31", "2026-09-02"),
                ANALYST_ORIGIN,
            ),
            ApiErrorId.POLICY_TERM_OVERLAP.value,
            409,
        )

        _rows, meta = validate_paginated(
            api.list_policies(COMPLIANCE, {"insurer_id": ctx["insurer_id"], "limit": 50})
        )
        assert meta["total_count"] == 4, (
            "the two refused attachments must have created nothing, leaving four "
            "policies for this carrier"
        )
        third = fixtures.read_agreement(api, third_note)
        assert third["policy_count"] == 2, (
            "only the two accepted attachments may increment policy_count"
        )


class TestPolicyDisputeRevisionCycle:
    """The policy runs PENDING_VERIFICATION -> DISPUTED -> PENDING_VERIFICATION
    -> VERIFIED and drags the note back to DRAFT on the way."""

    def _submitted(self, api):
        ctx = fixtures.origination_context(api)
        bundle = fixtures.submitted_agreement(
            api,
            ctx=ctx,
            policies=[
                _policy(ctx, "MC-D-5001", 1200000, "2026-09-01", "2027-09-01")
            ],
            down_payment_cents=300000,
            service_fee_cents=2000,
            installment_count=9,
            first_installment_due_date="2026-10-01",
        )
        return bundle

    def _dispute(self, api, bundle):
        """The carrier corrects to 1250000, the agency confirms 1200000."""
        insurer_record = validate_success(
            api.create_verification(
                bundle["policy_id"],
                factories.corrected_verification(1250000, note="audited exposure"),
                bundle["insurer_headers"],
            ),
            201,
        )
        agent_record = validate_success(
            api.create_verification(
                bundle["policy_id"],
                factories.confirmed_verification(),
                bundle["agent_headers"],
            ),
            201,
        )
        return insurer_record, agent_record

    def test_one_attestation_leaves_the_policy_pending(self, api):
        """The first filing stamps its own derived figures but does not move the
        policy.

        The PRD states: "Nothing happens to the policy while only one side has
        spoken; the policy stays `PENDING_VERIFICATION` until both parties hold a
        non-superseded record."

        Design: Difficulty/non_linear_state_machine/policy_dispute_revision_cycle
        """
        bundle = self._submitted(api)
        submitted = bundle["submitted"]
        assert submitted["status"] == "PENDING_VERIFICATION"
        assert submitted["total_premium_cents"] == 1200000, (
            "the provisional basis sums the agency-quoted gross premiums"
        )
        assert submitted["amount_financed_cents"] == 902000, (
            "1200000 - 300000 + 2000 == 902000"
        )
        assert submitted["finance_charge_cents"] == add_on_finance_charge_cents(
            902000, 1500, 9
        ) == 101475

        record = validate_success(
            api.create_verification(
                bundle["policy_id"],
                factories.corrected_verification(1250000, note="audited exposure"),
                bundle["insurer_headers"],
            ),
            201,
        )
        assert record["party"] == "INSURER", (
            "party becomes INSURER when the caller acts as Insurer"
        )
        assert record["effective_premium_cents"] == 1250000, (
            "on CORRECTED the derived comparison fields take "
            "corrected_premium_cents and corrected_effective_date"
        )

        policy = fixtures.read_policy(api, bundle["policy_id"])
        assert policy["status"] == "PENDING_VERIFICATION", (
            "one attestation is not enough to fork the policy"
        )

    def test_the_second_attestation_disputes_and_unprices_the_note(self, api):
        """The pair disagrees on premium, so the policy disputes and the parent
        falls back to DRAFT with its provisional money fields cleared.

        The PRD states: "A dispute also reaches up into the note: if the parent
        agreement is sitting in `PENDING_VERIFICATION`, it falls back to `DRAFT`,
        its provisional money fields — `total_premium_cents`,
        `amount_financed_cents`, `effective_annual_rate_bps`,
        `finance_charge_cents` and `total_of_payments_cents` — are all reset to 0,
        its `quote_basis` returns to null, the regime's `active_agreement_count`
        is decremented by 1, and the agreement's `version` advances."

        Design: Difficulty/non_linear_state_machine/policy_dispute_revision_cycle
        """
        bundle = self._submitted(api)
        _insurer_record, agent_record = self._dispute(api, bundle)

        assert agent_record["effective_premium_cents"] == 1200000, (
            "on CONFIRMED effective_premium_cents takes the policy's quoted "
            "gross_premium_cents"
        )
        policy = fixtures.read_policy(api, bundle["policy_id"])
        assert policy["status"] == "DISPUTED"
        assert policy["dispute_reason"] == "PREMIUM_MISMATCH", (
            "dispute_reason is stamped by a strict precedence, and with no "
            "repudiation the differing premiums decide it"
        )

        agreement = fixtures.read_agreement(api, bundle["agreement_id"])
        assert agreement["status"] == "DRAFT"
        assert agreement["verified_policy_count"] == 0
        assert agreement["quote_basis"] is None
        assert agreement["total_premium_cents"] == 0
        assert agreement["amount_financed_cents"] == 0
        assert agreement["effective_annual_rate_bps"] == 0
        assert agreement["finance_charge_cents"] == 0
        assert agreement["total_of_payments_cents"] == 0
        regime = validate_success(
            api.get_state_rate_rule(bundle["rule_id"], COMPLIANCE), 200
        )
        assert regime["active_agreement_count"] == 0, (
            "the dispute decrements the counter the submission had incremented"
        )

    def test_the_reverted_note_cannot_be_activated(self, api):
        """A note dragged back to DRAFT refuses activation.

        The PRD states: "`DRAFT` accepts policy attachment, submission, voiding
        and rate-exception approval; `PENDING_VERIFICATION` accepts activation,
        voiding and rate-exception approval".

        Design: Difficulty/non_linear_state_machine/policy_dispute_revision_cycle
        """
        bundle = self._submitted(api)
        self._dispute(api, bundle)

        validate_error(
            api.activate_agreement(bundle["agreement_id"], ANALYST_ORIGIN),
            ApiErrorId.AGREEMENT_STATE_INVALID.value,
            409,
        )

    def test_reopening_supersedes_the_history_and_reenters_pending(self, api):
        """Reopening retires both attestations without deleting them and returns
        the policy to a state it has already left.

        The PRD states: "Reopening verification on a `DISPUTED` policy —
        permitted only while the parent agreement is in `DRAFT` or
        `PENDING_VERIFICATION` — sets `superseded` to true on every existing
        attestation of that policy, clears `dispute_reason`, moves the policy
        `DISPUTED` → `PENDING_VERIFICATION` and advances its `version`."

        Design: Difficulty/non_linear_state_machine/policy_dispute_revision_cycle
        """
        bundle = self._submitted(api)
        self._dispute(api, bundle)

        reopened = validate_success(
            api.reopen_verification(bundle["policy_id"], ANALYST_ORIGIN), 200
        )
        assert reopened["status"] == "PENDING_VERIFICATION"
        assert reopened["dispute_reason"] is None

        records, meta = validate_paginated(
            api.list_verifications(bundle["policy_id"], ANALYST_ORIGIN, {"limit": 50})
        )
        assert meta["total_count"] == 2, (
            "superseded records are never deleted, so both filings remain listed"
        )
        assert all(record["superseded"] is True for record in records), (
            "reopening sets superseded to true on every existing attestation"
        )

    def test_the_second_lap_reproduces_the_quote_and_reaches_verified(self, api):
        """Resubmitting reprices identically, and two fresh attestations that
        agree carry the policy to VERIFIED.

        The PRD states: "Both parties may then file fresh attestations, since the
        retired records no longer count as live voices, and the cycle may repeat
        without limit until the two sides agree."

        Design: Difficulty/non_linear_state_machine/policy_dispute_revision_cycle
        """
        bundle = self._submitted(api)
        self._dispute(api, bundle)
        validate_success(
            api.reopen_verification(bundle["policy_id"], ANALYST_ORIGIN), 200
        )

        resubmitted = validate_success(
            api.submit_agreement(bundle["agreement_id"], ANALYST_ORIGIN), 200
        )
        assert resubmitted["status"] == "PENDING_VERIFICATION"
        assert resubmitted["total_premium_cents"] == 1200000
        assert resubmitted["amount_financed_cents"] == 902000
        assert resubmitted["finance_charge_cents"] == 101475, (
            "the second lap through the cycle must reproduce the provisional "
            "quote exactly"
        )

        validate_success(
            api.create_verification(
                bundle["policy_id"],
                factories.corrected_verification(1250000),
                bundle["insurer_headers"],
            ),
            201,
        )
        validate_success(
            api.create_verification(
                bundle["policy_id"],
                factories.corrected_verification(1250000),
                bundle["agent_headers"],
            ),
            201,
        )

        policy = fixtures.read_policy(api, bundle["policy_id"])
        assert policy["status"] == "VERIFIED", (
            "both records are CORRECTED and their asserted premiums and "
            "effective dates are equal"
        )
        assert policy["verified_premium_cents"] == 1250000
        assert policy["financed_premium_cents"] == 1250000, (
            "financed_premium_cents is recomputed as verified_premium_cents plus "
            "endorsed_premium_cents"
        )

    def test_activation_prices_the_attested_basis_and_cuts_nine_installments(
        self, api
    ):
        """The final quote runs over the attested premium, not the agency quote.

        The PRD states: "the final variant sums `financed_premium_cents` (the
        attested premium plus any financed endorsements) over the note's policies
        whose `status` is `VERIFIED` and whose `carried_over` flag is false,
        rather than the agency-quoted gross premiums over pending policies."

        Design: Difficulty/non_linear_state_machine/policy_dispute_revision_cycle
        """
        bundle = self._submitted(api)
        self._dispute(api, bundle)
        validate_success(
            api.reopen_verification(bundle["policy_id"], ANALYST_ORIGIN), 200
        )
        validate_success(api.submit_agreement(bundle["agreement_id"], ANALYST_ORIGIN), 200)
        validate_success(
            api.create_verification(
                bundle["policy_id"],
                factories.corrected_verification(1250000),
                bundle["insurer_headers"],
            ),
            201,
        )
        validate_success(
            api.create_verification(
                bundle["policy_id"],
                factories.corrected_verification(1250000),
                bundle["agent_headers"],
            ),
            201,
        )
        fixtures.set_clock(api, "2026-09-01T00:00:00Z")

        activated = validate_success(
            api.activate_agreement(bundle["agreement_id"], ANALYST_ORIGIN), 200
        )

        assert activated["status"] == "ACTIVE"
        assert activated["total_premium_cents"] == 1250000
        assert activated["amount_financed_cents"] == 952000, (
            "1250000 - 300000 + 2000 == 952000"
        )
        assert activated["finance_charge_cents"] == 107100
        assert activated["total_of_payments_cents"] == 1059100

        rows = fixtures.read_installments(api, bundle["agreement_id"])
        assert len(rows) == 9, "exactly installment_count installment rows are cut"
        rows.sort(key=lambda row: row["installment_number"])
        assert rows[0]["amount_cents"] == 117677
        assert rows[0]["finance_charge_component_cents"] == 11900
        assert rows[0]["principal_component_cents"] == 105777
        assert rows[8]["amount_cents"] == 117684, (
            "the last installment takes total_of_payments_cents minus the base "
            "amount multiplied by one less than the installment count"
        )
