"""State-machine corners: declared initial states, the two happy-path
transitions and their side-effect lists, refused transitions, terminal lockdown,
non-idempotent compensations and the conditional cancellation cascade.
"""

from test_helpers import (
    ApiErrorId,
    add_on_finance_charge_cents,
    assert_installments_sum,
    factories,
    fixtures,
    late_fee_cents,
    pro_rata_unearned_premium_cents,
    round_half_up,
    rule_of_78_rebate_cents,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import (
    ANALYST_NOTICE,
    ANALYST_ORIGIN,
    ANALYST_POA,
    COMPLIANCE,
    COMPLIANCE_WAIVER,
)


class TestValidTransitionDraftToPendingVerificationOnSubmit:
    """Submission prices the note provisionally and cuts no schedule."""

    def _drafted(self, api):
        ctx = fixtures.origination_context(api)
        return fixtures.draft_agreement(
            api,
            ctx,
            policies=[
                factories.financed_policy(ctx["insurer_id"], policy_number="MC-VT-1")
            ],
        )

    def test_the_two_state_dimensions_start_independently(self, api):
        """A fresh note is DRAFT and CURRENT with no quote at all.

        The PRD states: "The new note is stamped `DRAFT` in its financing `status`
        and `CURRENT` in its `delinquency_stage`, its `originated_by_user_id` is
        frozen from `X-User-ID` for the later two-person control, and every balance,
        derived money field and counter is zeroed".

        Design: Corner/state_machines/valid_transition_draft_to_pending_verification_on_submit
        """
        bundle = self._drafted(api)

        assert bundle["agreement"]["status"] == "DRAFT"
        assert bundle["agreement"]["delinquency_stage"] == "CURRENT"
        assert bundle["agreement"]["quote_basis"] is None
        assert bundle["agreement"]["version"] == 1

    def test_the_submit_moves_only_the_status_dimension(self, api):
        """The delinquency stage is untouched by the pricing transition.

        The PRD states: "Submitting the draft advances the financing status `DRAFT` →
        `PENDING_VERIFICATION` and prices the note provisionally."

        Design: Corner/state_machines/valid_transition_draft_to_pending_verification_on_submit
        """
        bundle = self._drafted(api)

        submitted = validate_success(
            api.submit_agreement(bundle["agreement_id"], ANALYST_ORIGIN), 200
        )

        assert submitted["status"] == "PENDING_VERIFICATION"
        assert submitted["delinquency_stage"] == "CURRENT"

    def test_the_provisional_quote_is_written_in_full(self, api):
        """Basis, amount financed, tier rate, finance charge and total.

        The PRD states: "A successful submission runs the pricing engine in its
        **provisional** variant, stamps `quote_basis` as `PROVISIONAL`, increments the
        regime's `active_agreement_count` by 1 and advances the note's `version`."

        Design: Corner/state_machines/valid_transition_draft_to_pending_verification_on_submit
        """
        bundle = self._drafted(api)

        submitted = validate_success(
            api.submit_agreement(bundle["agreement_id"], ANALYST_ORIGIN), 200
        )

        assert submitted["quote_basis"] == "PROVISIONAL"
        assert submitted["total_premium_cents"] == 600000
        assert submitted["amount_financed_cents"] == 502000
        assert submitted["effective_annual_rate_bps"] == 1500, (
            "the tier-2 rate of 1500 is smaller than the statutory ceiling of 1800"
        )
        assert submitted["finance_charge_cents"] == add_on_finance_charge_cents(
            502000, 1500, 6
        ) == 37650
        assert submitted["total_of_payments_cents"] == 539650
        assert submitted["version"] == 3, (
            "1 at creation, +1 for the policy attachment, +1 for the submit"
        )

    def test_the_regime_counter_is_incremented_by_submission(self, api):
        """The counter the create deliberately left alone now moves.

        The PRD states: "The state regime's `active_agreement_count` is deliberately
        *not* touched at creation; submission owns that increment."

        Design: Corner/state_machines/valid_transition_draft_to_pending_verification_on_submit
        """
        bundle = self._drafted(api)
        before = validate_success(
            api.get_state_rate_rule(bundle["rule_id"], COMPLIANCE), 200
        )
        assert before["active_agreement_count"] == 0

        validate_success(api.submit_agreement(bundle["agreement_id"], ANALYST_ORIGIN), 200)

        after = validate_success(
            api.get_state_rate_rule(bundle["rule_id"], COMPLIANCE), 200
        )
        assert after["active_agreement_count"] == 1

    def test_the_schedule_and_the_opening_balances_belong_to_activation(self, api):
        """No installment row exists yet and nothing has been funded.

        The PRD states: "With the final quote in hand the platform cuts the schedule,
        inserting exactly `installment_count` installment rows in `SCHEDULED` status,
        each carrying a 1-based `installment_number`, a `due_date`, an `amount_cents`,
        its split into `principal_component_cents` and
        `finance_charge_component_cents`, and a `paid_cents` of 0."

        Design: Corner/state_machines/valid_transition_draft_to_pending_verification_on_submit
        """
        bundle = self._drafted(api)

        submitted = validate_success(
            api.submit_agreement(bundle["agreement_id"], ANALYST_ORIGIN), 200
        )

        assert submitted["principal_balance_cents"] == 0
        assert submitted["activated_at"] is None
        _rows, meta = validate_paginated(
            api.list_installments(bundle["agreement_id"], ANALYST_ORIGIN, {"limit": 100})
        )
        assert meta["total_count"] == 0, (
            "generating the schedule at submission would fund a note the two parties "
            "have not yet attested to"
        )


class TestEveryMachineIsBornInItsDeclaredInitialState:
    """Rows created by an explicit POST and rows created inside a side effect."""

    def _through_activation(self, api):
        bundle = fixtures.canonical_600k_note(api, policy_number="MC-IS-1")
        bundle["installments_at_birth"] = fixtures.read_installments(
            api, bundle["agreement_id"]
        )
        return bundle

    def test_the_explicitly_created_rows_choose_their_own_state(self, api):
        """License, agency, note, policy and payment are all server-stamped.

        The PRD states: "the platform stamps `status` as `ACTIVE` and derives
        `is_effective` immediately from that status, the recorded window and the clock
        date."

        Design: Corner/state_machines/initial_state_every_state_machine_is_born_in_its_declared_initial_state
        """
        ctx = fixtures.origination_context(api)

        assert ctx["license"]["status"] == "ACTIVE"
        assert ctx["license"]["is_effective"] is True
        assert ctx["agent"]["status"] == "ACTIVE"

        bundle = fixtures.draft_agreement(
            api,
            ctx,
            policies=[
                factories.financed_policy(ctx["insurer_id"], policy_number="MC-IS-1")
            ],
        )
        assert bundle["agreement"]["status"] == "DRAFT"
        assert bundle["policies"][0]["status"] == "PENDING_VERIFICATION"

    def test_no_create_endpoint_accepts_a_nominated_state(self, api):
        """A client-supplied status is ignored rather than honoured.

        The PRD states: "The new note is stamped `DRAFT` in its financing `status` and
        `CURRENT` in its `delinquency_stage`".

        Design: Corner/state_machines/initial_state_every_state_machine_is_born_in_its_declared_initial_state
        """
        ctx = fixtures.origination_context(api)

        agreement = validate_success(
            api.create_agreement(
                factories.agreement(
                    ctx["insured_id"],
                    ctx["agent_id"],
                    ctx["rule_id"],
                    status="ACTIVE",
                    delinquency_stage="NOIC_ISSUED",
                ),
                ANALYST_ORIGIN,
            ),
            201,
        )

        assert agreement["status"] == "DRAFT"
        assert agreement["delinquency_stage"] == "CURRENT", (
            "the second state dimension has its own initial state, independent of the "
            "financing status"
        )

    def test_the_installments_born_inside_activation_are_scheduled_and_unpaid(
        self, api
    ):
        """Six rows no client ever posted, all in the declared initial state.

        The PRD states: "With the final quote in hand the platform cuts the schedule,
        inserting exactly `installment_count` installment rows in `SCHEDULED` status,
        each carrying a 1-based `installment_number`, a `due_date`, an `amount_cents`,
        its split into `principal_component_cents` and
        `finance_charge_component_cents`, and a `paid_cents` of 0."

        Design: Corner/state_machines/initial_state_every_state_machine_is_born_in_its_declared_initial_state
        """
        bundle = self._through_activation(api)

        rows = bundle["installments_at_birth"]
        assert len(rows) == 6
        for row in rows:
            assert row["status"] == "SCHEDULED", "not PAST_DUE and not PAID"
            assert row["paid_cents"] == 0

        _filtered, meta = validate_paginated(
            api.list_installments(
                bundle["agreement_id"],
                ANALYST_ORIGIN,
                {"status": "SCHEDULED", "limit": 100},
            )
        )
        assert meta["total_count"] == 6

    def test_the_late_fee_born_inside_the_sweep_is_outstanding(self, api):
        """The fee is computed on the installment's full amount, not its remainder.

        The PRD states: "The new assessment is written with that `amount_cents`, a
        `status` of `OUTSTANDING`, an `assessed_date` equal to the clock date, and the
        `installment_number` of the installment that triggered it — a plain integer
        identifying the position in the schedule, not a reference to the installment
        row."

        Design: Corner/state_machines/initial_state_every_state_machine_is_born_in_its_declared_initial_state
        """
        bundle = self._through_activation(api)
        fixtures.post_payment(api, bundle["agreement_id"], 1000, "2026-08-15")

        run = fixtures.advance_and_service(api, "2026-10-12T00:00:00Z")

        assert run["late_fees_assessed"] == 1
        fees = fixtures.read_late_fees(api, bundle["agreement_id"])
        assert fees[0]["status"] == "OUTSTANDING"
        assert fees[0]["amount_cents"] == late_fee_cents(89941, 500, 500, 10000) == 4497
        assert fees[0]["installment_number"] == 1
        assert fees[0]["assessed_date"] == "2026-10-12"

    def test_the_notice_is_born_uncured_and_unexecuted(self, api):
        """A notice of intent to cancel starts in ISSUED with both dates null.

        The PRD states: "A successful issuance writes a notice in `ISSUED` status with
        `issued_date` set to the clock date, `issued_by_user_id` taken from
        `X-User-ID`, `notice_days` snapshotted from the regime's `noic_notice_days` at
        that moment, and `effective_cancel_date` set to `issued_date` advanced by
        `notice_days` calendar days."

        Design: Corner/state_machines/initial_state_every_state_machine_is_born_in_its_declared_initial_state
        """
        bundle = fixtures.noticed_note(api, policy_number="MC-IS-1")

        notice = bundle["notice"]
        assert notice["status"] == "ISSUED"
        assert notice["cured_date"] is None
        assert notice["executed_date"] is None
        assert notice["notice_days"] == 10
        assert notice["effective_cancel_date"] == "2026-10-22"

    def test_the_payment_the_attestation_and_the_endorsement_start_clean(self, api):
        """POSTED, un-superseded and unfinanced respectively.

        The PRD states: "Every qualifying endorsement then moves `PENDING` →
        `FINANCED` and has its `financed_at` stamped from the logical clock."

        Design: Corner/state_machines/initial_state_every_state_machine_is_born_in_its_declared_initial_state
        """
        bundle = self._through_activation(api)

        payment = fixtures.post_payment(api, bundle["agreement_id"], 1000, "2026-08-15")
        assert payment["status"] == "POSTED"
        assert payment["reversed_at"] is None

        rows = fixtures.read_verifications(api, bundle["policy_id"])
        assert rows and all(row["superseded"] is False for row in rows)

        endorsement = validate_success(
            api.create_endorsement(
                bundle["policy_id"],
                factories.endorsement(60000, effective_date="2026-09-15"),
                bundle["agent_headers"],
            ),
            201,
        )
        assert endorsement["status"] == "PENDING"
        assert endorsement["financed_at"] is None


class TestSubmitPreconditionsAreEvaluatedAtSubmitTime:
    """Two different preconditions of one transition, two different codes."""

    def test_a_note_financing_nothing_cannot_be_submitted(self, api):
        """policy_count of zero is its own refusal.

        The PRD states: "at least one non-cancelled policy must be attached, or
        `ERR_NO_FINANCED_POLICIES` (HTTP 422)".

        Design: Corner/state_machines/precondition_enforcement_submit_with_no_policies_and_suspended_agent
        """
        ctx = fixtures.origination_context(api)
        bundle = fixtures.draft_agreement(api, ctx, policies=[])
        assert bundle["agreement"]["policy_count"] == 0

        validate_error(
            api.submit_agreement(bundle["agreement_id"], ANALYST_ORIGIN),
            ApiErrorId.NO_FINANCED_POLICIES.value,
            422,
        )

        assert fixtures.read_agreement(api, bundle["agreement_id"])["status"] == "DRAFT"

    def test_a_suspension_after_origination_still_blocks_the_submit(self, api):
        """The agency's current status decides, not the status at creation.

        The PRD states: "Both suspensions block new origination identically: any
        attempt to create, submit or restructure an agreement naming a suspended
        agency is refused with `ERR_AGENT_SUSPENDED` (HTTP 422)."

        Design: Corner/state_machines/precondition_enforcement_submit_with_no_policies_and_suspended_agent
        """
        ctx = fixtures.origination_context(
            api,
            agent_payload=factories.producer_agent(
                agency_name="Rio Grande Brokers",
                agent_commission_bps=1100,
                initial_reserve_balance_cents=50000,
            ),
        )
        bundle = fixtures.draft_agreement(
            api,
            ctx,
            policies=[
                factories.financed_policy(ctx["insurer_id"], policy_number="MC-PE-1")
            ],
        )

        suspended = validate_success(
            api.suspend_agent(
                ctx["agent_id"],
                COMPLIANCE,
                {"reason": "appointment revoked by the department of insurance"},
            ),
            200,
        )
        assert suspended["status"] == "SUSPENDED_BY_COMPLIANCE", (
            "the compliance suspension is a distinct enum value from the "
            "chargeback-driven one"
        )

        validate_error(
            api.submit_agreement(bundle["agreement_id"], ANALYST_ORIGIN),
            ApiErrorId.AGENT_SUSPENDED.value,
            422,
        )

    def test_a_refused_submit_writes_no_provisional_quote(self, api):
        """The note stays DRAFT with a null basis and an unmoved counter.

        The PRD states: "A successful submission runs the pricing engine in its
        **provisional** variant, stamps `quote_basis` as `PROVISIONAL`, increments the
        regime's `active_agreement_count` by 1 and advances the note's `version`."

        Design: Corner/state_machines/precondition_enforcement_submit_with_no_policies_and_suspended_agent
        """
        ctx = fixtures.origination_context(api)
        empty = fixtures.draft_agreement(api, ctx, policies=[])
        stocked = fixtures.draft_agreement(
            api,
            ctx,
            policies=[
                factories.financed_policy(ctx["insurer_id"], policy_number="MC-PE-1")
            ],
        )
        validate_error(
            api.submit_agreement(empty["agreement_id"], ANALYST_ORIGIN),
            ApiErrorId.NO_FINANCED_POLICIES.value,
            422,
        )

        # The agency suspension is filed only now: PRD §2.10 ranks
        # ERR_AGENT_SUSPENDED (23) ahead of ERR_NO_FINANCED_POLICIES (29), so
        # suspending first would mask the empty-note refusal above.
        validate_success(api.suspend_agent(ctx["agent_id"], COMPLIANCE), 200)

        validate_error(
            api.submit_agreement(stocked["agreement_id"], ANALYST_ORIGIN),
            ApiErrorId.AGENT_SUSPENDED.value,
            422,
        )

        after = fixtures.read_agreement(api, stocked["agreement_id"])
        assert after["status"] == "DRAFT"
        assert after["quote_basis"] is None
        rule = validate_success(api.get_state_rate_rule(ctx["rule_id"], COMPLIANCE), 200)
        assert rule["active_agreement_count"] == 0


class TestActivationWritesScheduleBalancesAndActivatedAt:
    """Every clause of the activation side-effect list, in one pass."""

    def _pending(self, api):
        ctx = fixtures.origination_context(api)
        bundle = fixtures.verified_agreement(
            api,
            ctx=ctx,
            policies=[
                factories.financed_policy(ctx["insurer_id"], policy_number="MC-SE-1")
            ],
        )
        assert bundle["submitted"]["quote_basis"] == "PROVISIONAL", (
            "the create response is still DRAFT with a null basis; the provisional "
            "quote is written by the submit"
        )
        return bundle

    def _activated(self, api):
        bundle = self._pending(api)
        fixtures.set_clock(api, "2026-09-10T00:00:00Z")
        bundle["activated"] = validate_success(
            api.activate_agreement(bundle["agreement_id"], ANALYST_ORIGIN), 200
        )
        return bundle

    def test_the_final_quote_replaces_the_provisional_one(self, api):
        """The basis flips and the five money fields are rewritten.

        The PRD states: "All five money fields — `total_premium_cents`,
        `amount_financed_cents`, `effective_annual_rate_bps`, `finance_charge_cents`
        and `total_of_payments_cents` — are rewritten, and `quote_basis` is stamped
        `FINAL`."

        Design: Corner/state_machines/side_effect_execution_activate_writes_schedule_balances_and_activated_at
        """
        bundle = self._activated(api)

        activated = bundle["activated"]
        assert activated["quote_basis"] == "FINAL"
        assert activated["status"] == "ACTIVE"
        assert activated["delinquency_stage"] == "CURRENT", (
            "activation does not touch the delinquency dimension"
        )
        assert activated["total_premium_cents"] == 600000
        assert activated["amount_financed_cents"] == 502000
        assert activated["finance_charge_cents"] == 37650
        assert activated["total_of_payments_cents"] == 539650

    def test_the_opening_balances_are_the_quote_and_nothing_else(self, api):
        """Principal and unpaid finance charge open exactly at the quote.

        The PRD states: "The note's `principal_balance_cents` is set to
        `amount_financed_cents`, its `unpaid_finance_charge_cents` to
        `finance_charge_cents`, its `activated_at` to the current logical-clock
        instant, its financing status to `ACTIVE`, and its `version` advances."

        Design: Corner/state_machines/side_effect_execution_activate_writes_schedule_balances_and_activated_at
        """
        bundle = self._activated(api)

        activated = bundle["activated"]
        assert activated["principal_balance_cents"] == 502000
        assert activated["unpaid_finance_charge_cents"] == 37650
        assert activated["late_fee_balance_cents"] == 0
        assert activated["unapplied_credit_cents"] == 0
        assert activated["activated_at"].startswith("2026-09-10"), (
            "the stamp comes from the logical clock rather than from wall-clock time"
        )
        assert activated["version"] == 4, (
            "version 1 at create, 2 at the policy attachment, 3 at submit, 4 at "
            "activate; the two attestations bumped the policy's version, not the note's"
        )

    def test_the_schedule_is_cut_with_the_declared_shape(self, api):
        """Six rows, ascending, the first one carrying the base amounts.

        The PRD states: "Under `ADD_ON` the note pays level installments: the base
        amount is `total_of_payments_cents` divided by `installment_count` and
        truncated down to whole cents, every installment except the last takes that
        base amount, and the last installment takes `total_of_payments_cents` minus the
        base amount multiplied by one less than the installment count."

        Design: Corner/state_machines/side_effect_execution_activate_writes_schedule_balances_and_activated_at
        """
        bundle = self._activated(api)

        rows = fixtures.read_installments(api, bundle["agreement_id"])
        assert len(rows) == 6
        assert [row["installment_number"] for row in rows] == [1, 2, 3, 4, 5, 6]
        first = rows[0]
        assert first["due_date"] == "2026-10-01"
        assert first["amount_cents"] == 539650 // 6 == 89941
        assert first["finance_charge_component_cents"] == round_half_up(37650, 6) == 6275
        assert first["principal_component_cents"] == 83666
        assert first["paid_cents"] == 0
        assert first["status"] == "SCHEDULED"

    def test_the_remainder_lands_on_the_last_installment(self, api):
        """Four cents of arithmetic remainder go to installment six.

        The PRD states: "The arithmetic remainder always lands on the final
        installment so that the installment amounts sum to `total_of_payments_cents`
        exactly and the finance-charge components sum to `finance_charge_cents`
        exactly; rounding each installment independently would leave a one-cent drift
        and is wrong."

        Design: Corner/state_machines/side_effect_execution_activate_writes_schedule_balances_and_activated_at
        """
        bundle = self._activated(api)

        rows = fixtures.read_installments(api, bundle["agreement_id"])
        last = rows[-1]
        assert last["installment_number"] == 6
        assert last["due_date"] == "2027-03-01", (
            "the first due date advanced by five calendar months"
        )
        assert last["amount_cents"] == 89945
        assert last["finance_charge_component_cents"] == 6275
        assert last["principal_component_cents"] == 83670
        assert_installments_sum(rows, 539650, 37650)
        assert sum(row["principal_component_cents"] for row in rows) == 502000

    def test_every_row_was_created_in_the_initial_state(self, api):
        """The SCHEDULED filter finds all six.

        The PRD states: "The schedule of a note may be listed by an analyst, a
        compliance officer or the borrower, optionally filtered by installment `status`,
        and installment `status` is one of `SCHEDULED`, `PAST_DUE`, `PAID` or
        `VOIDED`."

        Design: Corner/state_machines/side_effect_execution_activate_writes_schedule_balances_and_activated_at
        """
        bundle = self._activated(api)

        _rows, meta = validate_paginated(
            api.list_installments(
                bundle["agreement_id"],
                ANALYST_ORIGIN,
                {"status": "SCHEDULED", "limit": 100},
            )
        )
        assert meta["total_count"] == 6


class TestTriggersOutsideTheOutboundEdgeListAreRefused:
    """Submitting an ACTIVE note and activating a DRAFT note are mirror
    images."""

    def test_an_active_note_has_no_outbound_submit_edge(self, api):
        """The note is already funded; resubmission is a state conflict.

        The PRD states: "The agreement's financing `status` permits the operation —
        otherwise `ERR_AGREEMENT_STATE_INVALID`. `DRAFT` accepts policy attachment,
        submission, voiding and rate-exception approval; `PENDING_VERIFICATION` accepts
        activation, voiding and rate-exception approval; `ACTIVE` accepts payments,
        notices, cancellation execution, endorsement financing and restructuring;
        `PAID_IN_FULL` accepts nothing except payment reversal; and `VOID`,
        `RESTRUCTURED`, `CANCELLED_DEFICIENT` and `CLOSED_ZERO` are terminal and accept
        nothing."

        Design: Corner/state_machines/invalid_transitions_submit_on_active_and_activate_on_draft_rejected
        """
        bundle = fixtures.canonical_600k_note(api, policy_number="MC-IV-A")
        assert bundle["activated"]["status"] == "ACTIVE"

        validate_error(
            api.submit_agreement(bundle["agreement_id"], ANALYST_ORIGIN),
            ApiErrorId.AGREEMENT_STATE_INVALID.value,
            409,
        )

        after = fixtures.read_agreement(api, bundle["agreement_id"])
        assert after["status"] == "ACTIVE"
        assert after["total_of_payments_cents"] == 539650
        assert len(fixtures.read_installments(api, bundle["agreement_id"])) == 6

    def test_verification_cannot_be_skipped_by_activating_a_draft(self, api):
        """Every other activation precondition passes and it still refuses.

        The PRD states: "Activation is the moment the note becomes a receivable. A
        `FinanceAnalyst` activates a `PENDING_VERIFICATION` note, and four
        preconditions are re-tested at that instant rather than trusted from
        submission."

        Design: Corner/state_machines/invalid_transitions_submit_on_active_and_activate_on_draft_rejected
        """
        ctx = fixtures.origination_context(api)
        bundle = fixtures.draft_agreement(
            api,
            ctx,
            policies=[
                factories.financed_policy(ctx["insurer_id"], policy_number="MC-IV-B")
            ],
        )

        validate_error(
            api.activate_agreement(bundle["agreement_id"], ANALYST_ORIGIN),
            ApiErrorId.AGREEMENT_STATE_INVALID.value,
            409,
        )

    def test_a_current_version_token_leaves_the_state_gate_to_speak(self, api):
        """Endorsement financing on a DRAFT note is a state conflict, not a stale
        token.

        The PRD states: "Folding the pending endorsements into the note is a separate,
        deliberate act by a `FinanceAnalyst`, permitted only while the note's financing
        status is `ACTIVE` and its `delinquency_stage` is `CURRENT` — a delinquent
        account is not re-financed, it is restructured."

        Design: Corner/state_machines/invalid_transitions_submit_on_active_and_activate_on_draft_rejected
        """
        ctx = fixtures.origination_context(api)
        bundle = fixtures.draft_agreement(
            api,
            ctx,
            policies=[
                factories.financed_policy(ctx["insurer_id"], policy_number="MC-IV-B")
            ],
        )
        token = fixtures.agreement_version(api, bundle["agreement_id"])

        validate_error(
            api.finance_endorsements(
                bundle["agreement_id"],
                {"expected_agreement_version": token},
                ANALYST_ORIGIN,
            ),
            ApiErrorId.AGREEMENT_STATE_INVALID.value,
            409,
        )

    def test_three_refusals_produced_zero_writes(self, api):
        """The draft is still a draft with no quote and no schedule.

        The PRD states: "This gate guards policy attachment, submission, activation,
        voiding, payment posting, notice issuance, cancellation execution, endorsement
        financing, restructuring and rate-exception approval."

        Design: Corner/state_machines/invalid_transitions_submit_on_active_and_activate_on_draft_rejected
        """
        ctx = fixtures.origination_context(api)
        bundle = fixtures.draft_agreement(
            api,
            ctx,
            policies=[
                factories.financed_policy(ctx["insurer_id"], policy_number="MC-IV-B")
            ],
        )
        token = fixtures.agreement_version(api, bundle["agreement_id"])

        validate_error(
            api.activate_agreement(bundle["agreement_id"], ANALYST_ORIGIN),
            ApiErrorId.AGREEMENT_STATE_INVALID.value,
            409,
        )
        validate_error(
            api.finance_endorsements(
                bundle["agreement_id"],
                {"expected_agreement_version": token},
                ANALYST_ORIGIN,
            ),
            ApiErrorId.AGREEMENT_STATE_INVALID.value,
            409,
        )

        after = fixtures.read_agreement(api, bundle["agreement_id"])
        assert after["status"] == "DRAFT"
        assert after["quote_basis"] is None
        _rows, meta = validate_paginated(
            api.list_installments(bundle["agreement_id"], ANALYST_ORIGIN, {"limit": 100})
        )
        assert meta["total_count"] == 0


class TestVoidedAgreementRefusesEveryTrigger:
    """A terminal state has no outbound edges at all."""

    def _void(self, api):
        ctx = fixtures.origination_context(api)
        bundle = fixtures.submitted_agreement(
            api,
            ctx=ctx,
            policies=[
                factories.financed_policy(ctx["insurer_id"], policy_number="MC-TL-1")
            ],
        )
        assert bundle["submitted"]["status"] == "PENDING_VERIFICATION"
        bundle["voided"] = validate_success(
            api.void_agreement(
                bundle["agreement_id"],
                ANALYST_ORIGIN,
                {"reason": "the insured funded the premium from operating cash"},
            ),
            200,
        )
        return bundle

    def test_the_void_writes_the_terminal_state_and_advances_the_version(self, api):
        """One bump for the void, on top of create and submit.

        The PRD states: "The note's `version` advances either way."

        Design: Corner/state_machines/terminal_state_lockdown_voided_agreement_refuses_every_trigger
        """
        bundle = self._void(api)

        assert bundle["voided"]["status"] == "VOID"
        assert bundle["voided"]["version"] == 4, (
            "1 at creation, 2 at the policy attachment, 3 at submission, 4 at the void"
        )

    def test_the_void_cancels_the_policies_without_a_coverage_date(self, api):
        """Coverage was never pulled, so there is no effective date to record.

        The PRD states: "Voiding is permitted only from `DRAFT` or
        `PENDING_VERIFICATION`, and only while no `Payment` row exists against the
        note; the financing status moves to `VOID`, and every policy of the note moves
        to `CANCELLED` with its `cancellation_effective_date` left null, because
        coverage was never pulled — it was never funded."

        Design: Corner/state_machines/terminal_state_lockdown_voided_agreement_refuses_every_trigger
        """
        bundle = self._void(api)

        policy = fixtures.read_policy(api, bundle["policy_id"])
        assert policy["status"] == "CANCELLED"
        assert policy["cancellation_effective_date"] is None

    def test_the_void_out_of_pending_verification_returns_the_counter(self, api):
        """The submission's increment is given back.

        The PRD states: "Whether the regime's `active_agreement_count` is decremented
        depends on where the void came from: a void out of `PENDING_VERIFICATION`
        decrements it by 1, while a void out of `DRAFT` leaves it untouched, since a
        draft was never counted in the first place."

        Design: Corner/state_machines/terminal_state_lockdown_voided_agreement_refuses_every_trigger
        """
        ctx = fixtures.origination_context(api)
        bundle = fixtures.submitted_agreement(
            api,
            ctx=ctx,
            policies=[
                factories.financed_policy(ctx["insurer_id"], policy_number="MC-TL-1")
            ],
        )
        counted = validate_success(
            api.get_state_rate_rule(bundle["rule_id"], COMPLIANCE), 200
        )
        assert counted["active_agreement_count"] == 1

        validate_success(
            api.void_agreement(
                bundle["agreement_id"],
                ANALYST_ORIGIN,
                {"reason": "the insured funded the premium from operating cash"},
            ),
            200,
        )

        after = validate_success(
            api.get_state_rate_rule(bundle["rule_id"], COMPLIANCE), 200
        )
        assert after["active_agreement_count"] == 0

    def test_no_trigger_reopens_the_terminal_note(self, api):
        """Submit, activate, void again and pay are all state conflicts.

        The PRD states: "`VOID`, `RESTRUCTURED`, `CANCELLED_DEFICIENT` and
        `CLOSED_ZERO` are terminal and accept nothing."

        Design: Corner/state_machines/terminal_state_lockdown_voided_agreement_refuses_every_trigger
        """
        bundle = self._void(api)
        conflict = ApiErrorId.AGREEMENT_STATE_INVALID.value

        validate_error(api.submit_agreement(bundle["agreement_id"], ANALYST_ORIGIN), conflict, 409)
        validate_error(api.activate_agreement(bundle["agreement_id"], ANALYST_ORIGIN), conflict, 409)
        validate_error(
            api.void_agreement(
                bundle["agreement_id"], ANALYST_ORIGIN, {"reason": "second attempt"}
            ),
            conflict,
            409,
        )
        validate_error(
            api.create_payment(
                bundle["agreement_id"],
                factories.payment(89941, "2026-08-15"),
                ANALYST_ORIGIN,
            ),
            conflict,
            409,
        )

    def test_the_four_refusals_left_the_terminal_row_untouched(self, api):
        """Still VOID, still version 4, and no payment row was minted.

        The PRD states: "This gate guards policy attachment, submission, activation,
        voiding, payment posting, notice issuance, cancellation execution, endorsement
        financing, restructuring and rate-exception approval."

        Design: Corner/state_machines/terminal_state_lockdown_voided_agreement_refuses_every_trigger
        """
        bundle = self._void(api)
        conflict = ApiErrorId.AGREEMENT_STATE_INVALID.value

        validate_error(api.submit_agreement(bundle["agreement_id"], ANALYST_ORIGIN), conflict, 409)
        validate_error(
            api.create_payment(
                bundle["agreement_id"],
                factories.payment(89941, "2026-08-15"),
                ANALYST_ORIGIN,
            ),
            conflict,
            409,
        )

        _rows, meta = validate_paginated(
            api.list_payments(bundle["agreement_id"], ANALYST_ORIGIN, {"limit": 50})
        )
        assert meta["total_count"] == 0
        after = fixtures.read_agreement(api, bundle["agreement_id"])
        assert after["status"] == "VOID"
        assert after["version"] == 4, "a refused trigger is not a mutation"


class TestReplayedCompensationsAreRejectedRatherThanApplied:
    """A second reverse and a second waive each carry their own 409."""

    def _reversed_once(self, api):
        bundle = fixtures.delinquent_note(api, policy_number="MC-ID-1")
        assert bundle["late_fee_amount_cents"] == late_fee_cents(89941, 500, 500, 10000)
        assert bundle["late_fee_amount_cents"] == 4497
        bundle["payment"] = fixtures.post_payment(
            api, bundle["agreement_id"], 94438, "2026-10-12"
        )
        assert bundle["payment"]["applied_principal_cents"] == 83666, (
            "94438 settles the 4497 fee whole and then retires installment 1's "
            "6275 of finance charge before its 83666 of principal"
        )
        bundle["reversal"] = validate_success(
            api.reverse_payment(
                bundle["payment"]["id"], factories.reversal(), ANALYST_ORIGIN
            ),
            200,
        )
        return bundle

    def test_the_first_reversal_restores_the_pre_payment_ledger(self, api):
        """Principal, finance charge and fee balance all come back exactly.

        The PRD states: "Posting an ordinary payment must reduce total receivable by
        exactly the amount tendered, and reversing a payment must restore total
        receivable to exactly the value it had before that payment was posted, together
        with the `paid_cents` and `status` of every installment the payment touched and
        the status of every late fee it settled."

        Design: Corner/state_machines/idempotency_second_reverse_and_second_waive_rejected
        """
        bundle = self._reversed_once(api)

        assert bundle["reversal"]["status"] == "REVERSED"
        agreement = fixtures.read_agreement(api, bundle["agreement_id"])
        assert agreement["principal_balance_cents"] == 502000
        assert agreement["unpaid_finance_charge_cents"] == 37650
        assert agreement["late_fee_balance_cents"] == 4497

    def test_a_different_legal_reason_does_not_make_a_new_reversal(self, api):
        """REVERSED is terminal for a payment however the replay is phrased.

        The PRD states: "Reversing a payment already `REVERSED` is refused with
        `ERR_PAYMENT_ALREADY_REVERSED` (HTTP 409)."

        Design: Corner/state_machines/idempotency_second_reverse_and_second_waive_rejected
        """
        bundle = self._reversed_once(api)

        validate_error(
            api.reverse_payment(
                bundle["payment"]["id"],
                factories.reversal(reversal_reason="BANK_ERROR"),
                ANALYST_ORIGIN,
            ),
            ApiErrorId.PAYMENT_ALREADY_REVERSED.value,
            409,
        )

    def test_the_replayed_reversal_does_not_credit_the_ledger_twice(self, api):
        """The balances stay at the restored figures rather than doubling.

        The PRD states: "The payment has status `POSTED` when it is reversed —
        otherwise `ERR_PAYMENT_ALREADY_REVERSED`."

        Design: Corner/state_machines/idempotency_second_reverse_and_second_waive_rejected
        """
        bundle = self._reversed_once(api)

        validate_error(
            api.reverse_payment(
                bundle["payment"]["id"],
                factories.reversal(reversal_reason="BANK_ERROR"),
                ANALYST_ORIGIN,
            ),
            ApiErrorId.PAYMENT_ALREADY_REVERSED.value,
            409,
        )

        agreement = fixtures.read_agreement(api, bundle["agreement_id"])
        assert agreement["principal_balance_cents"] == 502000, (
            "a second unwind would add the same 83666 again and read 585666"
        )
        assert agreement["unpaid_finance_charge_cents"] == 37650
        assert agreement["late_fee_balance_cents"] == 4497

    def test_the_first_waive_settles_the_restored_fee(self, api):
        """OUTSTANDING to WAIVED, and the balance drops to zero.

        The PRD states: "The waiver moves the fee `OUTSTANDING` → `WAIVED`, records
        the acting officer in `waived_by_user_id`, decrements the note's
        `late_fee_balance_cents` by the fee amount, and advances both rows' `version`."

        Design: Corner/state_machines/idempotency_second_reverse_and_second_waive_rejected
        """
        bundle = self._reversed_once(api)

        waived = validate_success(
            api.waive_late_fee(
                bundle["late_fee_id"],
                factories.waiver(justification="first concession"),
                COMPLIANCE_WAIVER,
            ),
            200,
        )

        assert waived["status"] == "WAIVED"
        agreement = fixtures.read_agreement(api, bundle["agreement_id"])
        assert agreement["late_fee_balance_cents"] == 0

    def test_the_replayed_waive_carries_its_own_distinct_code(self, api):
        """The late-fee conflict is not the payment conflict.

        The PRD states: "A compliance officer may waive an `OUTSTANDING` fee as a
        concession, supplying a mandatory `justification`; a fee that is `PAID`, already
        `WAIVED` or `REVERSED` cannot be waived and yields
        `ERR_LATE_FEE_NOT_OUTSTANDING` (HTTP 409)."

        Design: Corner/state_machines/idempotency_second_reverse_and_second_waive_rejected
        """
        bundle = self._reversed_once(api)
        validate_success(
            api.waive_late_fee(
                bundle["late_fee_id"],
                factories.waiver(justification="first concession"),
                COMPLIANCE_WAIVER,
            ),
            200,
        )

        validate_error(
            api.waive_late_fee(
                bundle["late_fee_id"],
                factories.waiver(justification="replay of the same concession"),
                COMPLIANCE_WAIVER,
            ),
            ApiErrorId.LATE_FEE_NOT_OUTSTANDING.value,
            409,
        )

    def test_the_lifetime_counter_survives_the_waiver_and_both_replays(self, api):
        """One fee was ever assessed, and it still counts against the cap.

        The PRD states: "One counter is deliberately excluded from this identity:
        `late_fee_count` is a lifetime counter that never moves backwards, so neither a
        waiver nor a reversal restores it."

        Design: Corner/state_machines/idempotency_second_reverse_and_second_waive_rejected
        """
        bundle = self._reversed_once(api)
        before = fixtures.read_agreement(api, bundle["agreement_id"])

        validate_error(
            api.reverse_payment(
                bundle["payment"]["id"],
                factories.reversal(reversal_reason="BANK_ERROR"),
                ANALYST_ORIGIN,
            ),
            ApiErrorId.PAYMENT_ALREADY_REVERSED.value,
            409,
        )
        validate_success(
            api.waive_late_fee(
                bundle["late_fee_id"],
                factories.waiver(justification="first concession"),
                COMPLIANCE_WAIVER,
            ),
            200,
        )
        validate_error(
            api.waive_late_fee(
                bundle["late_fee_id"],
                factories.waiver(justification="replay of the same concession"),
                COMPLIANCE_WAIVER,
            ),
            ApiErrorId.LATE_FEE_NOT_OUTSTANDING.value,
            409,
        )

        after = fixtures.read_agreement(api, bundle["agreement_id"])
        assert after["late_fee_count"] == 1
        assert after["late_fee_balance_cents"] == 0
        assert after["version"] == before["version"] + 1, (
            "only the successful waiver mutated the note; the two rejected replays "
            "bumped nothing"
        )

    def test_the_reversed_payment_stays_visible_as_a_single_row(self, api):
        """The ledger keeps the returned item on the record.

        The PRD states: "Payments of a note can be listed and filtered by `status`, and
        reversed payments remain visible in that list."

        Design: Corner/state_machines/idempotency_second_reverse_and_second_waive_rejected
        """
        bundle = self._reversed_once(api)
        validate_error(
            api.reverse_payment(
                bundle["payment"]["id"],
                factories.reversal(reversal_reason="BANK_ERROR"),
                ANALYST_ORIGIN,
            ),
            ApiErrorId.PAYMENT_ALREADY_REVERSED.value,
            409,
        )

        rows, meta = validate_paginated(
            api.list_payments(bundle["agreement_id"], COMPLIANCE, {"limit": 50})
        )
        assert meta["total_count"] == 1, (
            "a rejected replay writes no second payment row"
        )
        assert rows[0]["status"] == "REVERSED"


class TestExecutionVoidsOnlyUntouchedScheduledInstallments:
    """One note carrying a PAID row, a partly paid PAST_DUE row and four
    untouched rows."""

    def _partly_paid(self, api):
        """The 600k note with 100000 posted while every row was still SCHEDULED."""
        bundle = fixtures.canonical_600k_note(
            api, policy_number="MC-CC-1", activate_at="2026-09-01T00:00:00Z"
        )
        fixtures.set_clock(api, "2026-09-05T00:00:00Z")
        bundle["payment"] = fixtures.post_payment(
            api, bundle["agreement_id"], 100000, "2026-09-05"
        )
        return bundle

    def _noticed(self, api):
        """Servicing on 2026-11-12 then a notice from the analyst who will not
        execute it."""
        bundle = self._partly_paid(api)
        bundle["servicing_run"] = fixtures.advance_and_service(
            api, "2026-11-12T00:00:00Z"
        )
        bundle["notice"] = validate_success(
            api.issue_cancellation_notice(bundle["agreement_id"], ANALYST_NOTICE), 201
        )
        return bundle

    def _executed(self, api):
        bundle = self._noticed(api)
        fixtures.set_clock(api, "2026-11-22T00:00:00Z")
        bundle["execution"] = validate_success(
            api.execute_cancellation(bundle["agreement_id"], ANALYST_POA), 200
        )
        return bundle

    def test_the_partial_payment_lands_across_two_scheduled_rows(self, api):
        """Bucket three fills installment 1 whole and part-pays installment 2.

        The PRD states: "Bucket three does the same for `SCHEDULED` installments while
        any money remains, always taking the lowest `installment_number` first and
        retiring finance charge before principal within each."

        Design: Corner/state_machines/side_effect_conditional_cascade_execution_voids_only_untouched_scheduled_installments
        """
        bundle = self._partly_paid(api)

        payment = bundle["payment"]
        assert payment["allocation_variant"] == "STANDARD", (
            "100000 is far short of the 502000 net payoff at that date"
        )
        assert payment["applied_finance_charge_cents"] == 12550, (
            "6275 of finance charge is retired on each of installments 1 and 2"
        )
        assert payment["applied_principal_cents"] == 87450
        assert payment["applied_unapplied_cents"] == 0

        rows = fixtures.read_installments(api, bundle["agreement_id"])
        rows.sort(key=lambda row: row["installment_number"])
        assert rows[0]["status"] == "PAID"
        assert rows[0]["paid_cents"] == 89941
        assert rows[1]["status"] == "SCHEDULED"
        assert rows[1]["paid_cents"] == 10059

        agreement = fixtures.read_agreement(api, bundle["agreement_id"])
        assert agreement["principal_balance_cents"] == 414550
        assert agreement["unpaid_finance_charge_cents"] == 25100
        assert agreement["late_fee_balance_cents"] == 0

    def test_the_servicing_pass_skips_the_paid_row_and_charges_the_other(self, api):
        """Only installment 2 is marked past due and only it earns a fee.

        The PRD states: "Only notes whose financing status is `ACTIVE` are considered,
        and only those whose `delinquency_stage` is `CURRENT`, `LATE` or `NOIC_ISSUED`;
        drafts, pending notes and terminal notes are skipped entirely, as are
        installments already `PAID` or `VOIDED`."

        Design: Corner/state_machines/side_effect_conditional_cascade_execution_voids_only_untouched_scheduled_installments
        """
        bundle = self._partly_paid(api)

        run = fixtures.advance_and_service(api, "2026-11-12T00:00:00Z")

        assert run["past_due_marked"] == 1, (
            "installment 1's due date is long past, but it is PAID and therefore "
            "outside the pass's candidate set"
        )
        assert run["late_fees_assessed"] == 1
        fees = fixtures.read_late_fees(api, bundle["agreement_id"])
        assert len(fees) == 1
        assert fees[0]["installment_number"] == 2
        assert fees[0]["amount_cents"] == late_fee_cents(89941, 500, 500, 10000) == 4497

    def test_the_notice_freezes_the_unpaid_remainder_plus_the_fee(self, api):
        """84379 is the shortfall on installment 2 plus the outstanding fee.

        The PRD states: "It also snapshots `past_due_amount_cents`: the sum, over the
        note's installments whose `status` is `PAST_DUE`, of each installment's
        `amount_cents` minus its `paid_cents`, plus the note's `late_fee_balance_cents`."

        Design: Corner/state_machines/side_effect_conditional_cascade_execution_voids_only_untouched_scheduled_installments
        """
        bundle = self._noticed(api)

        notice = bundle["notice"]
        assert notice["status"] == "ISSUED"
        assert notice["effective_cancel_date"] == "2026-11-22"
        assert notice["past_due_amount_cents"] == (89941 - 10059) + 4497 == 84379

    def test_the_execution_reports_its_request_count_and_capped_rebate(self, api):
        """One request per cancelled policy, and the rebate cannot exceed what is
        owed.

        The PRD states: "One carrier cancellation request is created per cancelled
        policy, in `REQUESTED` status, carrying the `agreement_id` and `policy_id` it
        concerns, a `requested_date` of the clock date, the same
        `cancellation_effective_date`, the acting analyst as `requested_by_user_id`, the
        estimate as `computed_unearned_premium_cents`, and the regime's
        `unearned_premium_method` snapshotted as `estimate_method`."

        Design: Corner/state_machines/side_effect_conditional_cascade_execution_voids_only_untouched_scheduled_installments
        """
        bundle = self._executed(api)

        execution = bundle["execution"]
        assert execution["requests_created"] == 1
        assert rule_of_78_rebate_cents(37650, 5, 6) == 26893, (
            "five of the six installments are not yet retired"
        )
        assert execution["rebate_applied_cents"] == 25100, (
            "the sum-of-digits figure of 26893 is capped at the 25100 of finance "
            "charge the note still owes"
        )

    def test_the_estimate_uses_the_statutory_date_rather_than_the_clock(self, api):
        """82 earned days out of a 365-day term leave 283 unearned.

        The PRD states: "The elapsed length is the number of days from
        `verified_effective_date` to the `cancellation_effective_date`."

        Design: Corner/state_machines/side_effect_conditional_cascade_execution_voids_only_untouched_scheduled_installments
        """
        bundle = self._executed(api)

        assert bundle["execution"]["estimated_unearned_premium_cents"] == 465205
        policy = fixtures.read_policy(api, bundle["policy_id"])
        assert policy["earned_days"] == 82
        assert policy["unearned_premium_estimate_cents"] == (
            pro_rata_unearned_premium_cents(600000, 365 - 82, 365)
        ) == 465205

    def test_the_cascade_reads_each_installments_own_state(self, api):
        """PAID stays paid, PAST_DUE keeps its partial, untouched rows are voided.

        The PRD states: "Every installment still `SCHEDULED` with a `paid_cents` of
        zero moves to `VOIDED`, while `PAST_DUE` installments stay past due and are
        settled at the balance level rather than the schedule level."

        Design: Corner/state_machines/side_effect_conditional_cascade_execution_voids_only_untouched_scheduled_installments
        """
        bundle = self._executed(api)

        rows = fixtures.read_installments(api, bundle["agreement_id"])
        rows.sort(key=lambda row: row["installment_number"])
        assert rows[0]["status"] == "PAID"
        assert rows[0]["paid_cents"] == 89941
        assert rows[1]["status"] == "PAST_DUE", (
            "voiding this row would discard the 10059 already applied to it"
        )
        assert rows[1]["paid_cents"] == 10059
        assert rows[2]["status"] == "VOIDED"
        assert rows[2]["paid_cents"] == 0
        assert rows[5]["status"] == "VOIDED"

    def test_exactly_four_rows_were_voided(self, api):
        """The filter counts installments 3, 4, 5 and 6 and nothing else.

        The PRD states: "The schedule of a note may be listed by an analyst, a
        compliance officer or the borrower, optionally filtered by installment `status`,
        and installment `status` is one of `SCHEDULED`, `PAST_DUE`, `PAID` or
        `VOIDED`."

        Design: Corner/state_machines/side_effect_conditional_cascade_execution_voids_only_untouched_scheduled_installments
        """
        bundle = self._executed(api)

        _rows, meta = validate_paginated(
            api.list_installments(
                bundle["agreement_id"],
                ANALYST_ORIGIN,
                {"status": "VOIDED", "limit": 100},
            )
        )
        assert meta["total_count"] == 4

    def test_the_policy_is_cancelled_on_the_statutory_date(self, api):
        """The date comes from the notice, not from the day the analyst acted.

        The PRD states: "Every policy of the note whose `status` is `VERIFIED` moves to
        `CANCELLED`, its `cancellation_effective_date` set to the notice's
        `effective_cancel_date` — the statutory date, not the date the analyst happened
        to act — and its `earned_days` and `unearned_premium_estimate_cents` are
        computed."

        Design: Corner/state_machines/side_effect_conditional_cascade_execution_voids_only_untouched_scheduled_installments
        """
        bundle = self._executed(api)

        policy = fixtures.read_policy(api, bundle["policy_id"])
        assert policy["status"] == "CANCELLED"
        assert policy["cancellation_effective_date"] == "2026-11-22"

    def test_the_rebate_is_netted_against_finance_charge_only(self, api):
        """Principal and the late-fee balance are left where they were.

        The PRD states: "The unearned finance charge rebate is granted by the rule of
        section 3.6 and `unpaid_finance_charge_cents` is reduced by it."

        Design: Corner/state_machines/side_effect_conditional_cascade_execution_voids_only_untouched_scheduled_installments
        """
        bundle = self._executed(api)

        agreement = fixtures.read_agreement(api, bundle["agreement_id"])
        assert agreement["delinquency_stage"] == "CANCELLATION_REQUESTED"
        assert agreement["principal_balance_cents"] == 414550
        assert agreement["unpaid_finance_charge_cents"] == 0, (
            "the 25100 cap means the rebate exhausts the finance charge exactly"
        )
        assert agreement["late_fee_balance_cents"] == 4497

    def test_the_notice_reaches_its_executed_terminal_state(self, api):
        """One notice, EXECUTED, stamped at the clock date.

        The PRD states: "The notice moves `ISSUED` → `EXECUTED` with `executed_date`
        set to the clock date."

        Design: Corner/state_machines/side_effect_conditional_cascade_execution_voids_only_untouched_scheduled_installments
        """
        bundle = self._executed(api)

        rows, meta = validate_paginated(
            api.list_cancellation_notices(
                bundle["agreement_id"], COMPLIANCE, {"limit": 50}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["status"] == "EXECUTED"
        assert rows[0]["executed_date"] == "2026-11-22"


class TestVerifiedPolicyCountBubblesUpToTheAgreement:
    """A two-policy note whose ancestor counter follows verified policies, not
    verification records."""

    def _two_policy_note(self, api):
        ctx = fixtures.origination_context(api)
        bundle = fixtures.submitted_agreement(
            api,
            ctx=ctx,
            policies=[
                factories.financed_policy(
                    ctx["insurer_id"],
                    policy_number="MC-LS-1",
                    gross_premium_cents=600000,
                ),
                factories.financed_policy(
                    ctx["insurer_id"],
                    policy_number="MC-LS-2",
                    gross_premium_cents=400000,
                ),
            ],
            down_payment_cents=200000,
            service_fee_cents=2000,
            installment_count=6,
            first_installment_due_date="2026-10-01",
        )
        return bundle

    def _attest(self, api, bundle, policy_id, headers):
        return validate_success(
            api.create_verification(
                policy_id, factories.confirmed_verification(), headers
            ),
            201,
        )

    def _first_policy_verified(self, api):
        bundle = self._two_policy_note(api)
        self._attest(api, bundle, bundle["policy_ids"][0], bundle["insurer_headers"])
        self._attest(api, bundle, bundle["policy_ids"][0], bundle["agent_headers"])
        return bundle

    def _third_attestation(self, api):
        """Policy 1 complete, policy 2 carrying only the carrier's record."""
        bundle = self._first_policy_verified(api)
        self._attest(api, bundle, bundle["policy_ids"][1], bundle["insurer_headers"])
        return bundle

    def test_the_counters_start_split_at_submission(self, api):
        """Two attached policies and none of them verified yet.

        The PRD states: "A successful attachment stamps the policy
        `PENDING_VERIFICATION`, sets `carried_over` to false, provisionally sets
        `financed_premium_cents` equal to `gross_premium_cents`, increments the
        agreement's `policy_count` and advances the agreement's `version`."

        Design: Corner/state_machines/side_effect_ledger_sync_verification_count_bubbles_to_the_agreement
        """
        bundle = self._two_policy_note(api)

        submitted = bundle["submitted"]
        assert submitted["total_premium_cents"] == 1000000
        assert submitted["policy_count"] == 2
        assert submitted["verified_policy_count"] == 0

    def test_one_completed_pair_moves_the_counter_by_one(self, api):
        """The increment happens on the policy fork, not on each filing.

        The PRD states: "In that case the agreed figures are stamped as
        `verified_premium_cents` and `verified_effective_date`,
        `financed_premium_cents` is recomputed as `verified_premium_cents` plus
        `endorsed_premium_cents`, the agreement's `verified_policy_count` increases by
        1, and the policy's `version` advances."

        Design: Corner/state_machines/side_effect_ledger_sync_verification_count_bubbles_to_the_agreement
        """
        bundle = self._first_policy_verified(api)

        agreement = fixtures.read_agreement(api, bundle["agreement_id"])
        assert agreement["verified_policy_count"] == 1, (
            "two records landed, but they belong to one policy"
        )
        assert agreement["policy_count"] == 2
        assert fixtures.read_policy(api, bundle["policy_ids"][0])["status"] == "VERIFIED"

    def test_a_lone_carrier_record_on_the_second_policy_changes_nothing(self, api):
        """After three attestations overall the counter still reads one.

        The PRD states: "Nothing happens to the policy while only one side has spoken;
        the policy stays `PENDING_VERIFICATION` until both parties hold a non-superseded
        record."

        Design: Corner/state_machines/side_effect_ledger_sync_verification_count_bubbles_to_the_agreement
        """
        bundle = self._third_attestation(api)

        agreement = fixtures.read_agreement(api, bundle["agreement_id"])
        assert agreement["verified_policy_count"] == 1, (
            "a counter driven by verification records rather than by verified "
            "policies would read 3 at this point"
        )
        assert (
            fixtures.read_policy(api, bundle["policy_ids"][1])["status"]
            == "PENDING_VERIFICATION"
        )

    def test_the_counter_gap_is_what_blocks_activation(self, api):
        """One verified policy out of two is not enough to fund the note.

        The PRD states: "At least one policy must be attached and every attached policy
        must be `VERIFIED` — formally, `verified_policy_count` must equal `policy_count`
        with `policy_count` at least 1 — and any policy still `PENDING_VERIFICATION` or
        sitting in `DISPUTED` blocks activation with `ERR_POLICY_NOT_VERIFIED`
        (HTTP 422)."

        Design: Corner/state_machines/side_effect_ledger_sync_verification_count_bubbles_to_the_agreement
        """
        bundle = self._third_attestation(api)

        validate_error(
            api.activate_agreement(bundle["agreement_id"], ANALYST_ORIGIN),
            ApiErrorId.POLICY_NOT_VERIFIED.value,
            422,
        )

        after = fixtures.read_agreement(api, bundle["agreement_id"])
        assert after["status"] == "PENDING_VERIFICATION"
        assert after["quote_basis"] == "PROVISIONAL"

    def test_the_fourth_attestation_closes_the_gap_and_unblocks_the_note(self, api):
        """The second pair completes and activation goes through.

        The PRD states: "Once the second record lands, the pair is evaluated and the
        policy forks."

        Design: Corner/state_machines/side_effect_ledger_sync_verification_count_bubbles_to_the_agreement
        """
        bundle = self._third_attestation(api)
        self._attest(api, bundle, bundle["policy_ids"][1], bundle["agent_headers"])

        agreement = fixtures.read_agreement(api, bundle["agreement_id"])
        assert agreement["verified_policy_count"] == 2
        assert agreement["policy_count"] == 2

        activated = validate_success(
            api.activate_agreement(bundle["agreement_id"], ANALYST_ORIGIN), 200
        )
        assert activated["status"] == "ACTIVE"

    def test_the_final_quote_is_priced_over_both_attested_policies(self, api):
        """Both verified premiums enter the basis and the tier follows.

        The PRD states: "The five steps are exactly those described in section 3.2 —
        premium basis, amount financed, volume tier, statutory capping, method branch —
        with one difference in step one: the final variant sums
        `financed_premium_cents` (the attested premium plus any financed endorsements)
        over the note's policies whose `status` is `VERIFIED` and whose `carried_over`
        flag is false, rather than the agency-quoted gross premiums over pending
        policies."

        Design: Corner/state_machines/side_effect_ledger_sync_verification_count_bubbles_to_the_agreement
        """
        bundle = self._third_attestation(api)
        self._attest(api, bundle, bundle["policy_ids"][1], bundle["agent_headers"])

        activated = validate_success(
            api.activate_agreement(bundle["agreement_id"], ANALYST_ORIGIN), 200
        )

        assert activated["total_premium_cents"] == 1000000
        assert activated["amount_financed_cents"] == 802000
        assert activated["effective_annual_rate_bps"] == 1500, (
            "802000 sits in the second volume tier"
        )
        assert activated["finance_charge_cents"] == add_on_finance_charge_cents(
            802000, 1500, 6
        ) == 60150

    def test_both_policies_are_listable_in_the_verified_state(self, api):
        """The filtered listing agrees with the counter.

        The PRD states: "Every foreign key in the model is reverse-reachable: an
        agreement can be listed by borrower, agency, state regime, restructure
        predecessor, financing status or collection stage; policies by agreement,
        carrier or status; carrier cancellation requests by agreement, policy or status;
        chargebacks by agency, agreement or status."

        Design: Corner/state_machines/side_effect_ledger_sync_verification_count_bubbles_to_the_agreement
        """
        bundle = self._third_attestation(api)
        self._attest(api, bundle, bundle["policy_ids"][1], bundle["agent_headers"])

        _rows, meta = validate_paginated(
            api.list_policies(
                ANALYST_ORIGIN,
                {
                    "agreement_id": bundle["agreement_id"],
                    "status": "VERIFIED",
                    "limit": 50,
                },
            )
        )
        assert meta["total_count"] == 2
