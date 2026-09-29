"""Endorsement financing: a child work item in the right status gates a money
recomputation whose visible result lands on its own parent policy.
"""

from test_helpers import (
    ApiErrorId,
    add_on_finance_charge_cents,
    assert_installments_sum,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import ANALYST_ORIGIN


def _note_with_one_pending_endorsement(api):
    """The 600k note, ACTIVE and CURRENT, carrying one PENDING 50000 endorsement."""
    bundle = fixtures.canonical_600k_note(
        api, policy_number="MC-E-9101", activate_at="2026-09-01T00:00:00Z"
    )
    assert bundle["activated"]["amount_financed_cents"] == 502000
    assert bundle["activated"]["finance_charge_cents"] == 37650
    assert bundle["activated"]["total_of_payments_cents"] == 539650
    bundle["endorsement"] = validate_success(
        api.create_endorsement(
            bundle["policy_id"],
            factories.endorsement(50000, effective_date="2026-09-15"),
            bundle["agent_headers"],
        ),
        201,
    )
    return bundle


def _finance(api, bundle, expected_version=None):
    if expected_version is None:
        expected_version = fixtures.agreement_version(api, bundle["agreement_id"])
    return api.finance_endorsements(
        bundle["agreement_id"],
        {"expected_agreement_version": expected_version},
        ANALYST_ORIGIN,
    )


class TestVerifiedPolicyStateGatesEndorsementFinancing:
    """The recomputation is gated on the existence of a PENDING child, not on the
    concurrency token."""

    def _declined(self, api):
        """The only PENDING endorsement killed before it touched the ledger."""
        bundle = _note_with_one_pending_endorsement(api)
        assert bundle["endorsement"]["status"] == "PENDING"
        assert bundle["endorsement"]["signed_amount_cents"] == 50000, (
            "an ADDITIONAL_PREMIUM carries the amount itself"
        )
        bundle["declined"] = validate_success(
            api.decline_endorsement(
                bundle["endorsement"]["id"], ANALYST_ORIGIN, factories.decline_reason()
            ),
            200,
        )
        return bundle

    def _refinanced(self, api):
        """A second PENDING endorsement filed after the first was declined, then
        folded into the note."""
        bundle = self._declined(api)
        bundle["second_endorsement"] = validate_success(
            api.create_endorsement(
                bundle["policy_id"],
                factories.endorsement(50000, effective_date="2026-09-20"),
                bundle["agent_headers"],
            ),
            201,
        )
        bundle["financed"] = validate_success(
            _finance(api, bundle), 200
        )
        return bundle

    def test_declining_the_only_pending_endorsement_changes_nothing_else(self, api):
        """The decline moves the endorsement and leaves the ledger untouched.

        The PRD states: "declining a `PENDING` endorsement moves it `PENDING` →
        `DECLINED`, optionally recording a `reason`, and advances its `version`".

        Design: Difficulty/cross_entity_state_dependency/verified_policy_state_gates_endorsement_financing
        """
        bundle = self._declined(api)

        assert bundle["declined"]["status"] == "DECLINED"
        assert bundle["declined"]["version"] > bundle["endorsement"]["version"]

        policy = fixtures.read_policy(api, bundle["policy_id"])
        assert policy["endorsed_premium_cents"] == 0
        assert policy["financed_premium_cents"] == 600000, (
            "a DECLINED endorsement never enters the financed premium"
        )
        agreement = fixtures.read_agreement(api, bundle["agreement_id"])
        assert agreement["amount_financed_cents"] == 502000
        assert agreement["unpaid_finance_charge_cents"] == 37650

    def test_the_cross_entity_gate_refuses_even_with_a_correct_token(self, api):
        """With no PENDING child left, the correct version does not help.

        The PRD states: "and at least one `PENDING` endorsement must exist on a
        `VERIFIED` policy of that note, or it is refused with
        `ERR_NO_PENDING_ENDORSEMENTS` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/verified_policy_state_gates_endorsement_financing
        """
        bundle = self._declined(api)
        version = fixtures.agreement_version(api, bundle["agreement_id"])

        validate_error(
            _finance(api, bundle, expected_version=version),
            ApiErrorId.NO_PENDING_ENDORSEMENTS.value,
            422,
        )

        assert fixtures.agreement_version(api, bundle["agreement_id"]) == version, (
            "the refusal is the cross-entity gate and not a concurrency failure, "
            "and it leaves the note's version alone"
        )

    def test_filing_one_new_child_unblocks_the_parent_recomputation(self, api):
        """A single PENDING endorsement is enough to reprice the whole note.

        The PRD states: "The note is then repriced in the pricing engine's final
        variant over that new basis, which can move `total_premium_cents`,
        `amount_financed_cents`, the volume tier, `effective_annual_rate_bps`,
        `finance_charge_cents` and `total_of_payments_cents`, and the schedule is
        rebuilt over the unpaid tail only."

        Design: Difficulty/cross_entity_state_dependency/verified_policy_state_gates_endorsement_financing
        """
        bundle = self._declined(api)
        second = validate_success(
            api.create_endorsement(
                bundle["policy_id"],
                factories.endorsement(50000, effective_date="2026-09-20"),
                bundle["agent_headers"],
            ),
            201,
        )
        assert second["status"] == "PENDING"

        financed = validate_success(_finance(api, bundle), 200)

        assert financed["status"] == "ACTIVE"
        assert financed["total_premium_cents"] == 650000
        assert financed["amount_financed_cents"] == 552000
        assert financed["effective_annual_rate_bps"] == 1500
        assert financed["finance_charge_cents"] == add_on_finance_charge_cents(
            552000, 1500, 6
        ) == 41400
        assert financed["total_of_payments_cents"] == 593400

    def test_the_creation_of_the_child_does_not_move_the_parent_version(self, api):
        """Filing an endorsement writes a new row rather than mutating the note.

        The PRD states: "`version` starts at 1 when the row is created and
        increases by exactly 1 on every mutation of that row; `updated_at` is
        refreshed to the logical-clock instant on the same mutation."

        Design: Difficulty/cross_entity_state_dependency/verified_policy_state_gates_endorsement_financing
        """
        bundle = self._declined(api)
        before = fixtures.agreement_version(api, bundle["agreement_id"])

        validate_success(
            api.create_endorsement(
                bundle["policy_id"],
                factories.endorsement(50000, effective_date="2026-09-20"),
                bundle["agent_headers"],
            ),
            201,
        )

        assert fixtures.agreement_version(api, bundle["agreement_id"]) == before, (
            "creating the second endorsement mutates no field of the agreement, so "
            "the token read before the filing is still the current one"
        )
        validate_success(_finance(api, bundle, expected_version=before), 200)

    def test_the_financing_advances_the_note_version_and_burns_the_token(self, api):
        """Replaying the token that just worked is a stale-version failure.

        The PRD states: "Folding endorsements in rebuilds the remaining installment
        schedule from the agreement's current money fields, so if the stored
        `version` has moved on since that read, the schedule the request intends to
        supersede is not the schedule the server holds; the request is rejected
        with `ERR_STALE_AGREEMENT_VERSION` (HTTP 412)."

        Design: Difficulty/cross_entity_state_dependency/verified_policy_state_gates_endorsement_financing
        """
        bundle = self._declined(api)
        token = fixtures.agreement_version(api, bundle["agreement_id"])
        validate_success(
            api.create_endorsement(
                bundle["policy_id"],
                factories.endorsement(50000, effective_date="2026-09-20"),
                bundle["agent_headers"],
            ),
            201,
        )
        validate_success(_finance(api, bundle, expected_version=token), 200)

        assert fixtures.agreement_version(api, bundle["agreement_id"]) > token

        validate_success(
            api.create_endorsement(
                bundle["policy_id"],
                factories.endorsement(50000, effective_date="2026-09-25"),
                bundle["agent_headers"],
            ),
            201,
        )
        validate_error(
            _finance(api, bundle, expected_version=token),
            ApiErrorId.STALE_AGREEMENT_VERSION.value,
            412,
        )

    def test_the_result_lands_on_the_endorsements_own_parent_policy(self, api):
        """The policy's endorsed and financed premium are both re-derived.

        The PRD states: "Each affected policy's `endorsed_premium_cents` becomes the
        sum of `signed_amount_cents` over its `FINANCED` endorsements — so a return
        premium reduces it — and its `financed_premium_cents` is re-derived as
        `verified_premium_cents` plus `endorsed_premium_cents`."

        Design: Difficulty/cross_entity_state_dependency/verified_policy_state_gates_endorsement_financing
        """
        bundle = self._refinanced(api)

        policy = fixtures.read_policy(api, bundle["policy_id"])
        assert policy["endorsed_premium_cents"] == 50000, (
            "only the FINANCED endorsement contributes; the DECLINED one does not"
        )
        assert policy["financed_premium_cents"] == 650000

    def test_both_endorsements_end_in_their_own_terminal_status(self, api):
        """One DECLINED without a financing stamp, one FINANCED with one.

        The PRD states: "Every qualifying endorsement then moves `PENDING` →
        `FINANCED` and has its `financed_at` stamped from the logical clock."

        Design: Difficulty/cross_entity_state_dependency/verified_policy_state_gates_endorsement_financing
        """
        bundle = self._refinanced(api)

        rows, meta = validate_paginated(
            api.list_endorsements(bundle["policy_id"], ANALYST_ORIGIN, {"limit": 50})
        )
        assert meta["total_count"] == 2
        by_status = {row["status"]: row for row in rows}
        assert set(by_status) == {"DECLINED", "FINANCED"}
        assert by_status["DECLINED"]["financed_at"] is None
        assert by_status["FINANCED"]["financed_at"] is not None
        assert by_status["FINANCED"]["signed_amount_cents"] == 50000

    def test_the_note_balances_move_by_the_repricing_deltas(self, api):
        """Principal and unpaid finance charge absorb exactly the deltas.

        The PRD states: "The note's `principal_balance_cents` and
        `unpaid_finance_charge_cents` are adjusted by the deltas the repricing
        produced, and its `version` advances."

        Design: Difficulty/cross_entity_state_dependency/verified_policy_state_gates_endorsement_financing
        """
        bundle = self._refinanced(api)

        agreement = fixtures.read_agreement(api, bundle["agreement_id"])
        assert agreement["principal_balance_cents"] == 552000
        assert agreement["unpaid_finance_charge_cents"] == 41400
        assert agreement["principal_balance_cents"] - 502000 == 50000
        assert agreement["unpaid_finance_charge_cents"] - 37650 == 3750

    def test_the_unpaid_tail_is_rebuilt_with_no_drift(self, api):
        """Six untouched installments split the new total exactly.

        The PRD states: "the new `total_of_payments_cents` less the amounts already
        paid is redistributed across the installments whose `status` is `SCHEDULED`
        or `PAST_DUE`, taken in ascending `installment_number` order, applying the
        same discipline as a fresh schedule to that tail".

        Design: Difficulty/cross_entity_state_dependency/verified_policy_state_gates_endorsement_financing
        """
        bundle = self._refinanced(api)

        rows, meta = validate_paginated(
            api.list_installments(bundle["agreement_id"], ANALYST_ORIGIN, {"limit": 100})
        )
        assert meta["total_count"] == 6, (
            "folding endorsements in rebuilds the existing tail rather than "
            "lengthening the schedule"
        )
        rows.sort(key=lambda row: row["installment_number"])
        for row in rows:
            assert row["amount_cents"] == 98900, (
                "593400 divides across six installments with no remainder, so even "
                "the last installment of the tail takes the same share"
            )
            assert row["finance_charge_component_cents"] == 6900
            assert row["principal_component_cents"] == 92000
        assert_installments_sum(rows, 593400, 41400)
