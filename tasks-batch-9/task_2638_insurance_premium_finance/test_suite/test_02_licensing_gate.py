"""The licensing gate: its precedence over the scheduling window at origination,
and its re-evaluation of `is_effective` at activation.
"""

from test_helpers import (
    ApiErrorId,
    factories,
    fixtures,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import ANALYST_ORIGIN, COMPLIANCE


def _unlicensed_tx_context(api):
    """A TX regime whose only licence has been suspended, plus the parties."""
    fixtures.set_clock(api, "2026-08-15T00:00:00Z")
    tx = fixtures.create_state_regime(
        api,
        rule_payload=factories.tx_state_rate_rule(),
        license_payload=factories.license_payload(license_number="PFC-TX-001"),
    )
    suspended = validate_success(
        api.suspend_license(tx["license_id"], COMPLIANCE), 200
    )
    assert suspended["status"] == "SUSPENDED", (
        "suspension moves the licence status ACTIVE -> SUSPENDED"
    )
    assert suspended["is_effective"] is False, (
        "suspension sets is_effective to false immediately"
    )
    parties = fixtures.create_parties(api)
    tx.update(parties)
    return tx


def _agreement_payload(ctx, first_installment_due_date):
    return factories.agreement(
        ctx["insured_id"],
        ctx["agent_id"],
        ctx["rule_id"],
        down_payment_cents=100000,
        service_fee_cents=2000,
        installment_count=6,
        first_installment_due_date=first_installment_due_date,
    )


class TestLicensingBeatsTheSchedulingWindow:
    """Statutory checks run before temporal ones on agreement creation."""

    def test_unlicensed_and_backdated_reports_the_licensing_failure(self, api):
        """A request that violates both the licensing gate and the first-due-date
        window reports the licensing gate.

        The PRD states: "A request that is both unlicensed and mispriced reports
        the licensing failure, because pricing a deal the company may not legally
        write is moot."  The requested first installment falls on 2026-08-10,
        before the clock date of 2026-08-15, so both rules are violated at once.

        Design: Difficulty/priority_pair_validation_conflict/licensing_beats_temporal_due_date_on_origination
        """
        ctx = _unlicensed_tx_context(api)

        validate_error(
            api.create_agreement(_agreement_payload(ctx, "2026-08-10"), ANALYST_ORIGIN),
            ApiErrorId.STATE_NOT_LICENSED.value,
            422,
        )

    def test_licensing_violation_alone_reports_the_licensing_failure(self, api):
        """With a perfectly valid schedule, the suspended licence still refuses
        the note.

        The PRD states: "Licensing is enforced at four points in a note's life:
        when an agreement is created, when it is submitted, when it is activated,
        and when it is restructured."

        Design: Difficulty/priority_pair_validation_conflict/licensing_beats_temporal_due_date_on_origination
        """
        ctx = _unlicensed_tx_context(api)

        validate_error(
            api.create_agreement(_agreement_payload(ctx, "2026-10-01"), ANALYST_ORIGIN),
            ApiErrorId.STATE_NOT_LICENSED.value,
            422,
        )

    def test_temporal_violation_alone_reports_the_due_date_failure(self, api):
        """Once an effective licence exists, the same backdated request reaches
        the scheduling window and reports it.

        The PRD states: "The first installment must also fall in a narrow window:
        the clock date must be strictly earlier than `first_installment_due_date`,
        and that date must be no more than 60 days after the clock date."

        Design: Difficulty/priority_pair_validation_conflict/licensing_beats_temporal_due_date_on_origination
        """
        ctx = _unlicensed_tx_context(api)
        second = get_success_data(
            api.create_license(
                ctx["rule_id"],
                factories.license_payload(
                    license_number="PFC-TX-002",
                    effective_date="2026-06-01",
                    expiration_date="2027-12-31",
                ),
                COMPLIANCE,
            )
        )
        assert second["is_effective"] is True, (
            "an ACTIVE licence whose window contains the clock date is effective"
        )

        validate_error(
            api.create_agreement(_agreement_payload(ctx, "2026-08-10"), ANALYST_ORIGIN),
            ApiErrorId.INVALID_FIRST_DUE_DATE.value,
            422,
        )

    def test_neither_violation_creates_the_draft(self, api):
        """With an effective licence and a due date inside the window the note is
        created.

        The PRD states: "The new note is stamped `DRAFT` in its financing
        `status` and `CURRENT` in its `delinquency_stage`".

        Design: Difficulty/priority_pair_validation_conflict/licensing_beats_temporal_due_date_on_origination
        """
        ctx = _unlicensed_tx_context(api)
        get_success_data(
            api.create_license(
                ctx["rule_id"],
                factories.license_payload(
                    license_number="PFC-TX-002",
                    effective_date="2026-06-01",
                    expiration_date="2027-12-31",
                ),
                COMPLIANCE,
            )
        )

        created = validate_success(
            api.create_agreement(_agreement_payload(ctx, "2026-10-01"), ANALYST_ORIGIN),
            201,
        )

        assert created["status"] == "DRAFT"
        assert created["id"], "a created note must carry an identifier"


class TestLicenceEffectivenessGatesActivation:
    """`is_effective` folds status, window and clock together, and activation
    re-tests it."""

    def _verified_note(self, api):
        """A PENDING_VERIFICATION note whose only policy is already VERIFIED."""
        ctx = fixtures.origination_context(api)
        bundle = fixtures.verified_agreement(
            api,
            ctx=ctx,
            policies=[
                factories.financed_policy(
                    ctx["insurer_id"], policy_number="MC-L-9001"
                )
            ],
        )
        policy = fixtures.read_policy(api, bundle["policy_id"])
        assert policy["status"] == "VERIFIED", (
            "both parties confirmed, so the policy must be VERIFIED before the "
            "licence is touched"
        )
        return bundle

    def test_suspending_the_licence_blocks_activation_without_touching_the_note(
        self, api
    ):
        """Suspending a licence three hops away refuses the activation and leaves
        the note where it was.

        The PRD states: "When a regulator acts against the company, a compliance
        officer suspends the license: `status` moves `ACTIVE` → `SUSPENDED`,
        `is_effective` becomes false, the license's `version` advances, and
        origination in that state stops from that instant, because the licensing
        gate re-evaluates on every affected operation rather than caching a
        decision."

        Design: Difficulty/cross_entity_state_dependency/license_effectiveness_gates_agreement_activation
        """
        bundle = self._verified_note(api)
        assert bundle["license"]["is_effective"] is True, (
            "the licence must start effective so the suspension is the only change"
        )

        suspended = validate_success(
            api.suspend_license(bundle["license_id"], COMPLIANCE), 200
        )
        assert suspended["status"] == "SUSPENDED"
        assert suspended["is_effective"] is False

        validate_error(
            api.activate_agreement(bundle["agreement_id"], ANALYST_ORIGIN),
            ApiErrorId.STATE_NOT_LICENSED.value,
            422,
        )
        after = fixtures.read_agreement(api, bundle["agreement_id"])
        assert after["status"] == "PENDING_VERIFICATION", (
            "a refused activation leaves the financing status untouched"
        )

    def test_an_expired_licence_row_does_not_unblock_activation(self, api):
        """A licence whose window has closed is not effective, so adding it
        changes nothing.

        The PRD states: "The derived flag `is_effective` is true when, and only
        when, `status` is `ACTIVE` and the clock date falls inside the window with
        both bounds inclusive — that is, the clock date is on or after
        `effective_date` and on or before `expiration_date`."

        Design: Difficulty/cross_entity_state_dependency/license_effectiveness_gates_agreement_activation
        """
        bundle = self._verified_note(api)
        validate_success(api.suspend_license(bundle["license_id"], COMPLIANCE), 200)

        expired = validate_success(
            api.create_license(
                bundle["rule_id"],
                factories.license_payload(
                    license_number="PFC-TX-EXPIRED",
                    effective_date="2024-01-01",
                    expiration_date="2025-12-31",
                ),
                COMPLIANCE,
            ),
            201,
        )
        assert expired["is_effective"] is False, (
            "the clock date of 2026-08-15 is past 2025-12-31, so the licence is "
            "not effective despite its ACTIVE status"
        )

        validate_error(
            api.activate_agreement(bundle["agreement_id"], ANALYST_ORIGIN),
            ApiErrorId.STATE_NOT_LICENSED.value,
            422,
        )

    def test_an_effective_licence_unblocks_activation_and_prices_the_final_quote(
        self, api
    ):
        """Recording one in-window licence lets the same activation request
        succeed and cut the schedule.

        The PRD states: "The regime must still be licensed at the current clock
        date, or `ERR_STATE_NOT_LICENSED`."

        Design: Difficulty/cross_entity_state_dependency/license_effectiveness_gates_agreement_activation
        """
        bundle = self._verified_note(api)
        validate_success(api.suspend_license(bundle["license_id"], COMPLIANCE), 200)
        validate_success(
            api.create_license(
                bundle["rule_id"],
                factories.license_payload(
                    license_number="PFC-TX-EXPIRED",
                    effective_date="2024-01-01",
                    expiration_date="2025-12-31",
                ),
                COMPLIANCE,
            ),
            201,
        )
        fresh = validate_success(
            api.create_license(
                bundle["rule_id"],
                factories.license_payload(
                    license_number="PFC-TX-002",
                    effective_date="2026-06-01",
                    expiration_date="2027-12-31",
                ),
                COMPLIANCE,
            ),
            201,
        )
        assert fresh["is_effective"] is True

        activated = validate_success(
            api.activate_agreement(bundle["agreement_id"], ANALYST_ORIGIN), 200
        )

        assert activated["status"] == "ACTIVE"
        assert activated["quote_basis"] == "FINAL", (
            "activation reprices the note in the final variant and stamps "
            "quote_basis as FINAL"
        )
        assert activated["amount_financed_cents"] == 502000
        assert activated["finance_charge_cents"] == 37650

        licences, meta = validate_paginated(
            api.list_licenses(bundle["rule_id"], COMPLIANCE, {"limit": 50})
        )
        assert meta["total_count"] == 3, "three licence rows were recorded"
        effective_flags = sorted(row["is_effective"] for row in licences)
        assert effective_flags == [False, False, True], (
            "the suspended licence and the expired licence are both ineffective; "
            "only the in-window ACTIVE licence is effective"
        )

        rows = fixtures.read_installments(api, bundle["agreement_id"])
        rows.sort(key=lambda row: row["installment_number"])
        assert [row["amount_cents"] for row in rows] == [
            89941,
            89941,
            89941,
            89941,
            89941,
            89945,
        ], (
            "the arithmetic remainder always lands on the final installment so "
            "that the amounts sum to total_of_payments_cents exactly"
        )
