"""E-visit claim lifecycle: creation gates, adjudication cascades, rework."""
from test_helpers import (
    ApiErrorId,
    chargeable_message,
    create_evisit_claim_payload,
    draft_claim,
    message_in_review_with_minutes,
    provider_pool_practice,
    record_adjudication_payload,
    resolved_chargeable_message,
    staff_headers,
    submitted_claim,
    validate_error,
)


class TestClaimCreationGates:
    def test_claim_create_on_in_review_message_rejected(self, api):
        """PRD §3.6: "Claim creation requires the message to stand in `RESOLVED`
        — else `ERR_MESSAGE_NOT_RESOLVED` — and to carry `billing_disposition`
        `CHARGEABLE`, meaning consent was granted and never superseded, else
        `ERR_MESSAGE_NOT_CHARGEABLE`."

        The message is CHARGEABLE but still IN_REVIEW (consent granted, work not
        yet completed), so creation fails.

        Design: Difficulty/cross_entity_state_dependency/claim_create_requires_message_resolved_chargeable
        """
        ctx = provider_pool_practice()
        msg, _consent = chargeable_message(ctx, minutes=8)
        assert msg["status"] == "IN_REVIEW"
        assert msg["billing_disposition"] == "CHARGEABLE"

        resp = api.create_evisit_claim(
            create_evisit_claim_payload(msg["id"], ctx["provider"]["id"]),
            staff_headers(ctx["biller"]))
        validate_error(resp, ApiErrorId.ERR_MESSAGE_NOT_RESOLVED)

    def test_claim_create_after_resolution_succeeds(self, api):
        """PRD §3.6: "At creation the server denormalizes `patient_id` from the
        message, computes `code` and `fee_cents` from the tier schedule above,
        computes `patient_responsibility_cents` as described next, and opens the
        claim in `DRAFT`."
        PRD §3.6: "Five through ten minutes — both bounds inclusive — selects
        `CPT_99421` with a 5000-cent fee."

        After the provider completes the message, the same creation call
        succeeds.

        Design: Difficulty/cross_entity_state_dependency/claim_create_requires_message_resolved_chargeable
        """
        ctx = provider_pool_practice()
        scn = ctx["scn"]
        msg, _consent = resolved_chargeable_message(ctx, minutes=8)
        assert msg["status"] == "RESOLVED"
        claim = scn.create_claim(msg["id"], ctx["provider"]["id"],
                                 ctx["biller"])
        assert claim["status"] == "DRAFT"
        assert claim["code"] == "CPT_99421"
        assert claim["fee_cents"] == 5000
        assert claim["patient_responsibility_cents"] == 2500
        assert claim["patient_id"] == ctx["patient"]["id"]


class TestChargeableBeforeMinutes:
    def _setup_resolved_not_billable_low_minutes(self):
        """Message RESOLVED with billing_disposition NOT_BILLABLE and only 3
        provider clinical minutes (below the five-minute e-visit minimum)."""
        ctx = provider_pool_practice()
        scn = ctx["scn"]
        msg = message_in_review_with_minutes(ctx, minutes=3,
                                             urgency="ROUTINE")
        scn.determine_billing(msg["id"], ctx["provider"], "NOT_BILLABLE")
        scn.complete(msg["id"], ctx["provider"],
                     summary="answered, no charge")
        after = scn.get_message(msg["id"])
        assert after["status"] == "RESOLVED"
        assert after["billing_disposition"] == "NOT_BILLABLE"
        assert after["clinical_minutes_total"] == 3
        return ctx, msg

    def test_claim_create_not_chargeable_rejected(self, api):
        """PRD §2.6: "the server evaluates them in a fixed priority order and
        reports the first failure."
        PRD §2.6: "safety rules (the education gate `ERR_EDUCATION_ACK_REQUIRED`;
        the chargeable-message requirement `ERR_MESSAGE_NOT_CHARGEABLE`;
        cosigner identity `ERR_NOT_AUTHORIZED_COSIGNER`; the clinical-category
        requirement `ERR_CATEGORY_NOT_CLINICAL`)".
        PRD §2.6: "then fiscal rules (e-visit minimum minutes
        `ERR_EVISIT_MINUTES_BELOW_MINIMUM`; disclosed-fee ceiling
        `ERR_DISCLOSED_FEE_EXCEEDED`)" — the safety tier runs before the fiscal
        tier.

        Both the chargeable requirement (safety) and the five-minute minimum
        (fiscal) fail here; the safety error must win.

        Design: Difficulty/priority_pair_validation_conflict/chargeable_safety_before_minutes_fiscal
        """
        ctx, msg = self._setup_resolved_not_billable_low_minutes()
        resp = api.create_evisit_claim(
            create_evisit_claim_payload(msg["id"], ctx["provider"]["id"]),
            staff_headers(ctx["biller"]))
        validate_error(resp, ApiErrorId.ERR_MESSAGE_NOT_CHARGEABLE)

    def test_not_chargeable_rejection_creates_no_claim(self, api):
        """PRD §3.6: "no other claim for the message may stand in `DRAFT`,
        `SUBMITTED`, or `DENIED`, else `ERR_CLAIM_ALREADY_EXISTS`".
        PRD §3.6: "Claim creation requires the message to stand in `RESOLVED` —
        else `ERR_MESSAGE_NOT_RESOLVED` — and to carry `billing_disposition`
        `CHARGEABLE`, meaning consent was granted and never superseded, else
        `ERR_MESSAGE_NOT_CHARGEABLE`."

        The rejected creation leaves no claim behind: the message's claim list
        stays empty.

        Design: Difficulty/priority_pair_validation_conflict/chargeable_safety_before_minutes_fiscal
        """
        ctx, msg = self._setup_resolved_not_billable_low_minutes()
        resp = api.create_evisit_claim(
            create_evisit_claim_payload(msg["id"], ctx["provider"]["id"]),
            staff_headers(ctx["biller"]))
        validate_error(resp, ApiErrorId.ERR_MESSAGE_NOT_CHARGEABLE)
        _claims, meta = ctx["scn"].list_claims(message_id=msg["id"])
        assert meta["total_count"] == 0, (
            "a rejected claim creation must not persist a claim"
        )


class TestClaimDeniedReworkCycle:
    def test_claim_denial_reopens_source_message(self, api):
        """PRD §3.6: "`DENIED` additionally requires a `denial_reason` (absent
        it, `ERR_INVALID_REQUEST`), stamps `adjudicated_at`, leaves
        `outstanding_billed_cents` unchanged because a denied claim remains in
        the outstanding set, and fires a three-hop cascade: the message moves
        from `RESOLVED` to `REOPENED` with `assignee_id` set to the claim's
        rendering provider, `reopen_count` incremented, and `response_due_at`
        cleared until the next triage".

        Design: Difficulty/non_linear_state_machine/claim_denied_rework_resubmit_cycle
        """
        ctx = provider_pool_practice()
        scn = ctx["scn"]
        msg, _consent, claim = submitted_claim(ctx, minutes=8)

        denied = scn.adjudicate(claim["id"], ctx["biller"], "DENIED",
                                denial_reason="Insufficient documentation")
        assert denied["status"] == "DENIED"
        after = scn.get_message(msg["id"])
        assert after["status"] == "REOPENED", (
            "denial cascades the RESOLVED message to REOPENED"
        )
        assert after["reopen_count"] == 1
        assert after["assignee_id"] == ctx["provider"]["id"], (
            "the rendering provider becomes the assignee"
        )

    def test_claim_rework_recomputes_and_pays_out(self, api):
        """PRD §3.6: "Once the message has been worked back to `RESOLVED` — a
        rework attempted earlier fails with `ERR_MESSAGE_NOT_RESOLVED` — a
        `DENIED` claim may be returned to `DRAFT` via rework (from any other
        claim state, `ERR_CLAIM_INVALID_STATE`): its `code`, `fee_cents`, and
        `patient_responsibility_cents` are recomputed from the message's current
        `clinical_minutes_total`, and the patient's outstanding balance is
        credited by the old responsibility amount as the claim leaves the
        outstanding set."
        PRD §3.6: "when the message stands `RESOLVED` — cascades the message to
        `CLOSED`" (on PAID adjudication).

        The full cycle DRAFT -> SUBMITTED -> DENIED -> DRAFT -> SUBMITTED ->
        PAID is traversed, ending with the message auto-closed and the patient's
        outstanding balance back to zero.

        Design: Difficulty/non_linear_state_machine/claim_denied_rework_resubmit_cycle
        """
        ctx = provider_pool_practice()
        scn = ctx["scn"]
        msg, _consent, claim = submitted_claim(ctx, minutes=8)

        scn.adjudicate(claim["id"], ctx["biller"], "DENIED",
                       denial_reason="Insufficient documentation")
        assert scn.get_message(msg["id"])["status"] == "REOPENED"

        # Work the message back to RESOLVED.
        scn.triage(msg["id"], ctx["nurse"], "URGENT", "CLINICAL",
                   ctx["pool"]["id"])
        scn.assign(msg["id"], ctx["nurse"], staff_id=ctx["provider"]["id"])
        scn.start_review(msg["id"], ctx["provider"])
        scn.complete(msg["id"], ctx["provider"], summary="v2 done")
        assert scn.get_message(msg["id"])["status"] == "RESOLVED"

        reworked = scn.rework_claim(claim["id"], ctx["biller"])
        assert reworked["status"] == "DRAFT"
        assert reworked["code"] == "CPT_99421", (
            "rework recomputes from the current 8 minutes"
        )
        assert reworked["fee_cents"] == 5000
        assert reworked["patient_responsibility_cents"] == 2500
        assert scn.get_patient(ctx["patient"]["id"])[
            "outstanding_billed_cents"] == 0, (
            "rework credits the old responsibility as the claim leaves the "
            "outstanding set"
        )

        scn.submit_claim(claim["id"], ctx["biller"])
        paid = scn.adjudicate(claim["id"], ctx["biller"], "PAID")
        assert paid["status"] == "PAID"
        assert scn.get_message(msg["id"])["status"] == "CLOSED", (
            "PAID adjudication auto-closes the RESOLVED message"
        )
        assert scn.get_patient(ctx["patient"]["id"])[
            "outstanding_billed_cents"] == 0


class TestClaimDenialCascadeOverload:
    def _setup_provider_at_four_with_submitted_claim(self):
        """Provider P holds 4 filler ASSIGNED messages; the main message runs
        the full billing flow to a SUBMITTED claim (rendering provider P), then
        resolves, returning P to 4 open messages."""
        ctx = provider_pool_practice()
        scn = ctx["scn"]
        provider = ctx["provider"]
        for i in range(1, 5):
            filler = scn.send_message(ctx["patient"], subject=f"F{i}",
                                      body=f"f{i}")
            scn.triage(filler["id"], ctx["nurse"], "ROUTINE",
                       "ADMINISTRATIVE", ctx["pool"]["id"])
            scn.assign(filler["id"], ctx["nurse"], staff_id=provider["id"])
        msg, consent, claim = submitted_claim(ctx, minutes=8, subject="Main")
        pre = scn.get_staff(provider["id"])
        assert pre["open_inbox_count"] == 4, (
            f"after the main message resolves, P must be back at 4, "
            f"got {pre['open_inbox_count']}"
        )
        assert pre["inbox_overloaded"] is False
        return ctx, msg, claim

    def test_denial_cascade_reopens_message_to_rendering_provider(self, api):
        """PRD §3.6: "fires a three-hop cascade: the message moves from
        `RESOLVED` to `REOPENED` with `assignee_id` set to the claim's rendering
        provider, `reopen_count` incremented, and `response_due_at` cleared
        until the next triage; the rendering provider's `open_inbox_count` rises
        by one; and if that count reaches five or more their `inbox_overloaded`
        flips true."

        Hop 1 (message REOPENED to the rendering provider) and hop 2 (count 4 ->
        5).

        Design: Difficulty/transitive_cascade/claim_denial_reopens_message_and_trips_overload
        """
        ctx, msg, claim = \
            self._setup_provider_at_four_with_submitted_claim()
        scn = ctx["scn"]
        denied = scn.adjudicate(claim["id"], ctx["biller"], "DENIED",
                                denial_reason="No established patient")
        assert denied["status"] == "DENIED"

        after = scn.get_message(msg["id"])
        assert after["status"] == "REOPENED"
        assert after["assignee_id"] == ctx["provider"]["id"]
        assert after["reopen_count"] == 1
        assert after.get("response_due_at") is None

        staff_after = scn.get_staff(ctx["provider"]["id"])
        assert staff_after["open_inbox_count"] == 5, (
            f"hop 2: 4 fillers + reopened message = 5, got "
            f"{staff_after['open_inbox_count']}"
        )

    def test_denial_cascade_trips_overload_flag(self, api):
        """PRD §3.6: "and if that count reaches five or more their
        `inbox_overloaded` flips true."
        PRD §2.11: "it is true exactly when the count is five or more."
        PRD §3.6: "leaves `outstanding_billed_cents` unchanged because a denied
        claim remains in the outstanding set".

        Hop 3: the fifth open message flips the provider's overload flag; the
        denied claim's responsibility stays in the patient's outstanding
        balance.

        Design: Difficulty/transitive_cascade/claim_denial_reopens_message_and_trips_overload
        """
        ctx, msg, claim = \
            self._setup_provider_at_four_with_submitted_claim()
        scn = ctx["scn"]
        scn.adjudicate(claim["id"], ctx["biller"], "DENIED",
                       denial_reason="No established patient")

        staff_after = scn.get_staff(ctx["provider"]["id"])
        assert staff_after["open_inbox_count"] == 5
        assert staff_after["inbox_overloaded"] is True, (
            "hop 3: reaching five open messages flips inbox_overloaded"
        )
        patient_after = scn.get_patient(ctx["patient"]["id"])
        assert patient_after["outstanding_billed_cents"] == 2500, (
            "DENIED stays in the outstanding set"
        )


class TestOutstandingBilledConservation:
    def test_outstanding_draft_zero_then_submit_debits(self, api):
        """PRD §3.6: "Submitting moves a `DRAFT` claim to `SUBMITTED` (any other
        state is `ERR_CLAIM_INVALID_STATE`), re-checks the disclosed-fee ceiling
        against the granted consent (`ERR_DISCLOSED_FEE_EXCEEDED`), stamps
        `submitted_at`, and debits the patient's `outstanding_billed_cents` by
        the claim's `patient_responsibility_cents`."
        PRD §3.6: "The patient's `outstanding_billed_cents` is always the sum of
        `patient_responsibility_cents` over their claims standing in `SUBMITTED`
        or `DENIED`."

        A DRAFT claim is not in the outstanding set; submit debits +2500.

        Design: Difficulty/compensating_invariant/outstanding_billed_conservation
        """
        ctx = provider_pool_practice()
        scn = ctx["scn"]
        msg, _consent, claim = draft_claim(ctx, minutes=8)
        assert scn.get_patient(ctx["patient"]["id"])[
            "outstanding_billed_cents"] == 0, (
            "DRAFT is not in the outstanding set"
        )

        submitted = scn.submit_claim(claim["id"], ctx["biller"])
        assert submitted["status"] == "SUBMITTED"
        assert scn.get_patient(ctx["patient"]["id"])[
            "outstanding_billed_cents"] == 2500, (
            "submit debits the patient by patient_responsibility_cents"
        )

    def test_outstanding_paid_credits_back_and_autocloses(self, api):
        """PRD §3.6: "`PAID` stamps `adjudicated_at`, credits
        `outstanding_billed_cents` back by the responsibility amount, and — when
        the message stands `RESOLVED` — cascades the message to `CLOSED`".
        PRD §3.6: "This makes the conservation property plain: a submit followed
        by a payment nets zero, as does a denial followed by a void."

        Design: Difficulty/compensating_invariant/outstanding_billed_conservation
        """
        ctx = provider_pool_practice()
        scn = ctx["scn"]
        msg, _consent, claim = submitted_claim(ctx, minutes=8)
        paid = scn.adjudicate(claim["id"], ctx["biller"], "PAID")
        assert paid["status"] == "PAID"
        assert scn.get_patient(ctx["patient"]["id"])[
            "outstanding_billed_cents"] == 0, (
            "submit followed by PAID nets to zero"
        )
        assert scn.get_message(msg["id"])["status"] == "CLOSED", (
            "PAID auto-closes the RESOLVED message"
        )


class TestCoinsuranceRounding:
    def _setup_two_coinsurance_claims(self):
        """A COINSURANCE (0.3333) patient runs two full billing flows 192 hours
        apart (outside the 168-hour dedupe window), each at 7 provider minutes
        (CPT_99421, 5000-cent fee); both claims are submitted."""
        ctx = provider_pool_practice(plan_type="COINSURANCE", copay_cents=None,
                                     coinsurance_pct=0.3333)
        scn = ctx["scn"]

        _m1, _c1, claim1 = submitted_claim(ctx, minutes=7, subject="E1")
        out_mid = scn.get_patient(ctx["patient"]["id"])[
            "outstanding_billed_cents"]

        scn.set_clock("2026-08-11T10:00:00Z")
        _m2, _c2, claim2 = draft_claim(ctx, minutes=7, subject="E2")
        claim2 = scn.submit_claim(claim2["id"], ctx["biller"])
        out_end = scn.get_patient(ctx["patient"]["id"])[
            "outstanding_billed_cents"]
        return ctx, claim1, claim2, out_mid, out_end

    def test_coinsurance_per_claim_round_half_up(self, api):
        """PRD §3.6: "Under `COINSURANCE`, it is the lesser of `fee_cents` and
        the product of `fee_cents` and `coinsurance_pct` rounded half-up to
        integer cents."
        PRD §2.10: "For example, two claims each with a 5000-cent fee and a
        coinsurance fraction of 0.3333 yield a per-claim responsibility of
        round-half-up of 1666.5, that is 1667 cents, for a patient total of 3334
        cents; summing the unrounded products first would incorrectly yield 3333
        cents."

        Design: Difficulty/combinatorial_formula/coinsurance_per_claim_rounding
        """
        ctx, claim1, claim2, _out_mid, _out_end = \
            self._setup_two_coinsurance_claims()
        assert claim1["patient_responsibility_cents"] == 1667, (
            f"round_half_up(5000 * 0.3333) = 1667, got "
            f"{claim1['patient_responsibility_cents']}"
        )
        assert claim2["patient_responsibility_cents"] == 1667

    def test_outstanding_billed_uses_per_claim_rounded_sum(self, api):
        """PRD §2.10: "Each individual claim's patient responsibility is rounded
        to integer cents using round-half-up at the moment the claim is created
        or reworked; patient-level totals such as `outstanding_billed_cents` are
        then plain integer sums of those already-rounded per-claim values. The
        system must never sum unrounded products and round once at the end — the
        two orders diverge."

        After the first submit the balance is 1667; after the second it is 3334
        (1667 + 1667), never 3333.

        Design: Difficulty/combinatorial_formula/coinsurance_per_claim_rounding
        """
        _ctx, _claim1, _claim2, out_mid, out_end = \
            self._setup_two_coinsurance_claims()
        assert out_mid == 1667
        assert out_end == 3334, (
            f"per-claim rounding then integer sum: 1667 + 1667 = 3334, "
            f"got {out_end}"
        )


class TestClaimBlockingRules:
    def test_claim_in_flight_blocks_close(self, api):
        """PRD §3.4: "A `TriageNurse` or `Provider` may close a message only
        from `RESOLVED` (else `ERR_MESSAGE_INVALID_STATE`) and only while no
        e-visit claim for the message sits in `DRAFT`, `SUBMITTED`, or `DENIED`
        — an in-flight claim blocks closure with `ERR_CLAIM_IN_FLIGHT`."

        Design: Corner/validations/claim_in_flight_blocks_close
        """
        ctx = provider_pool_practice()
        scn = ctx["scn"]
        msg, _consent, _claim = draft_claim(ctx, minutes=8)
        resp = api.close_message(msg["id"], staff_headers(ctx["provider"]))
        validate_error(resp, ApiErrorId.ERR_CLAIM_IN_FLIGHT)
        assert scn.get_message(msg["id"])["status"] == "RESOLVED"

    def test_rendering_provider_must_have_thread_minutes(self, api):
        """PRD §3.6: "the named `rendering_provider_id` must reference a
        `PROVIDER` who logged at least one `CLINICAL_REVIEW` time entry on the
        message, else `ERR_RENDERING_PROVIDER_NOT_ON_THREAD`".

        All 8 clinical minutes were logged by P1; naming P2 (no entries on the
        thread) is rejected.

        Design: Corner/validations/rendering_provider_must_have_thread_minutes
        """
        ctx = provider_pool_practice()
        scn = ctx["scn"]
        other_provider = scn.add_staff("PROVIDER", "Dr P2")
        msg, _consent = resolved_chargeable_message(ctx, minutes=8)
        resp = api.create_evisit_claim(
            create_evisit_claim_payload(msg["id"], other_provider["id"]),
            staff_headers(ctx["biller"]))
        validate_error(resp, ApiErrorId.ERR_RENDERING_PROVIDER_NOT_ON_THREAD)
        _claims, meta = scn.list_claims(message_id=msg["id"])
        assert meta["total_count"] == 0

    def test_duplicate_active_claim_rejected(self, api):
        """PRD §3.6: "no other claim for the message may stand in `DRAFT`,
        `SUBMITTED`, or `DENIED`, else `ERR_CLAIM_ALREADY_EXISTS`".

        A second claim for a message whose DRAFT claim already exists is
        rejected.

        Design: Corner/validations/duplicate_active_claim_rejected
        """
        ctx = provider_pool_practice()
        scn = ctx["scn"]
        msg, _consent, claim = draft_claim(ctx, minutes=8)
        resp = api.create_evisit_claim(
            create_evisit_claim_payload(msg["id"], ctx["provider"]["id"]),
            staff_headers(ctx["biller"]))
        validate_error(resp, ApiErrorId.ERR_CLAIM_ALREADY_EXISTS)
        _claims, meta = scn.list_claims(message_id=msg["id"])
        assert meta["total_count"] == 1

    def test_denial_adjudication_requires_reason(self, api):
        """PRD §3.6: "`DENIED` additionally requires a `denial_reason` (absent
        it, `ERR_INVALID_REQUEST`)".

        Design: Corner/validations/denial_adjudication_requires_reason
        """
        ctx = provider_pool_practice()
        scn = ctx["scn"]
        msg, _consent, claim = submitted_claim(ctx, minutes=8)
        resp = api.record_adjudication(
            claim["id"], record_adjudication_payload("DENIED"),
            staff_headers(ctx["biller"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        assert scn.get_claim(claim["id"])["status"] == "SUBMITTED", (
            "a rejected adjudication must not move the claim"
        )
        assert scn.get_message(msg["id"])["status"] == "RESOLVED", (
            "no denial cascade fires without the denial"
        )

    def test_void_submitted_claim_rejected(self, api):
        """PRD §3.6: "Alternatively, a claim in `DRAFT` or `DENIED` may be
        voided as a write-off; voiding from `DRAFT` leaves the outstanding
        balance untouched, while voiding from `DENIED` credits it by the
        responsibility amount. `PAID` and `VOID` are terminal."
        PRD §2.6: "claim-state failures `ERR_CLAIM_INVALID_STATE`".

        A SUBMITTED claim cannot be voided; it must be adjudicated first.

        Design: Corner/validations/void_submitted_claim_rejected
        """
        ctx = provider_pool_practice()
        scn = ctx["scn"]
        _msg, _consent, claim = submitted_claim(ctx, minutes=8)
        resp = api.void_claim(claim["id"], staff_headers(ctx["biller"]))
        validate_error(resp, ApiErrorId.ERR_CLAIM_INVALID_STATE)
        assert scn.get_claim(claim["id"])["status"] == "SUBMITTED"
        assert scn.get_patient(ctx["patient"]["id"])[
            "outstanding_billed_cents"] == 2500, (
            "the rejected void must not touch the outstanding balance"
        )
