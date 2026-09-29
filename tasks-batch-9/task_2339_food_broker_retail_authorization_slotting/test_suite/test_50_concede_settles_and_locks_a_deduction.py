"""Conceding settles the money dimension alone, and a settled deduction is inert afterwards."""

import pytest

from test_helpers import (
    ACCOUNT_MANAGER_HEADERS,
    AUDIT_MANAGER_HEADERS,
    ApiErrorId,
    CreditPosture,
    DeductionReasonCode,
    DeductionSettlementState,
    DisputeState,
    fixtures,
    get_success_data,
    validate_error,
    validate_paginated,
)
from test_helpers import factories as F

SLOTTING_BUDGET_CENTS = 1000000
LARGE_AMOUNT_CENTS = 800000
SMALL_AMOUNT_CENTS = 100000


@pytest.fixture
def two_open_deductions_against_a_small_budget(api):
    """900,000 open against a 1,000,000 budget, which is already a RESTRICTED posture."""
    retailer = fixtures.create_retailer(api, total_store_count=1200)
    principal = fixtures.create_principal(api, slotting_budget_cents=SLOTTING_BUDGET_CENTS)

    def deduct(amount_cents):
        return fixtures.create_deduction(
            api,
            retailer["id"],
            principal["id"],
            reason_code=DeductionReasonCode.SHORTAGE,
            amount_cents=amount_cents,
            deduction_date="2026-08-01",
        )

    return {
        "retailer": retailer,
        "principal": principal,
        "large": deduct(LARGE_AMOUNT_CENTS),
        "small": deduct(SMALL_AMOUNT_CENTS),
    }


def concede(api, deduction):
    return api.concede_deduction(deduction["id"], ACCOUNT_MANAGER_HEADERS)


def concede_the_large_deduction(api, scope):
    return get_success_data(concede(api, scope["large"]), 200)


class TestConcedeSettlesAndLocksADeduction:
    def test_two_open_deductions_already_restrict_the_principal(
        self, api, two_open_deductions_against_a_small_budget
    ):
        """900,000 of 1,000,000 is 9,000 basis points, past the inclusive 7,500 threshold.

        PRD: "`liability_ratio_bps` is 0 whenever `slotting_budget_cents` is 0; otherwise it is the sum
        of `open_slotting_liability_cents` and `open_deduction_cents`, multiplied by 10,000, divided by
        `slotting_budget_cents`, floored to whole basis points."

        PRD: "it is `RESTRICTED` when `at_risk_authorization_count` is 2 or more, or
        `liability_ratio_bps` is 7,500 or more — that is, when open liability plus open deductions reach
        seventy-five percent of the budget"

        Design: Corner/endpoints/concede_settles_a_never_disputed_deduction_and_locks_it
        """
        scope = two_open_deductions_against_a_small_budget

        principal = fixtures.get_principal(api, scope["principal"]["id"])

        assert principal["open_deduction_cents"] == LARGE_AMOUNT_CENTS + SMALL_AMOUNT_CENTS
        assert principal["liability_ratio_bps"] == 9000
        assert principal["credit_posture"] == CreditPosture.RESTRICTED

    def test_conceding_settles_the_money_and_leaves_the_dispute_dimension_alone(
        self, api, two_open_deductions_against_a_small_budget
    ):
        """No claim was ever filed, and conceding does not invent one.

        PRD: "A `BrokerAccountManager` conceding a deduction moves `settlement_state` from `OPEN` to
        `CONCEDED` while `dispute_state` is `NOT_DISPUTED`, `SUBSTANTIATED` or `DENIED`;
        `conceded_cents` becomes `amount_cents` less `recovered_cents`, `open_cents` goes to zero, the
        same `PROMO_BILLBACK` cascade to `settled_funding_cents` fires, and the principal's
        `open_deduction_cents` and `credit_posture` are re-derived."

        PRD: "The two dimensions of a deduction move independently."

        Design: Corner/endpoints/concede_settles_a_never_disputed_deduction_and_locks_it
        """
        scope = two_open_deductions_against_a_small_budget
        assert scope["large"]["dispute_state"] == DisputeState.NOT_DISPUTED

        conceded = concede_the_large_deduction(api, scope)

        assert conceded["settlement_state"] == DeductionSettlementState.CONCEDED
        assert conceded["conceded_cents"] == LARGE_AMOUNT_CENTS
        assert conceded["recovered_cents"] == 0
        assert conceded["open_cents"] == 0
        assert conceded["dispute_state"] == DisputeState.NOT_DISPUTED

    def test_the_settlement_re_derives_the_principals_posture_immediately(
        self, api, two_open_deductions_against_a_small_budget
    ):
        """Only the 100,000 charge is still open, which is 1,000 basis points of the budget.

        PRD: "In every case the principal's `open_deduction_cents` and `liability_ratio_bps` are
        recomputed and `credit_posture` re-derived."

        PRD: "and otherwise it is `NORMAL`"

        Design: Corner/endpoints/concede_settles_a_never_disputed_deduction_and_locks_it
        """
        scope = two_open_deductions_against_a_small_budget
        concede_the_large_deduction(api, scope)

        principal = fixtures.get_principal(api, scope["principal"]["id"])

        assert principal["open_deduction_cents"] == SMALL_AMOUNT_CENTS
        assert principal["liability_ratio_bps"] == 1000
        assert principal["credit_posture"] == CreditPosture.NORMAL

    def test_all_four_settlement_verbs_are_refused_once_the_money_has_settled(
        self, api, two_open_deductions_against_a_small_budget
    ):
        """Concede, dispute, approve and deny share the same `OPEN` precondition.

        PRD: "It requires `settlement_state` to still be `OPEN`, otherwise
        `ERR_DEDUCTION_ALREADY_SETTLED`; the logical-clock date to be no later than `deduction_date`
        plus the chain's `deduction_dispute_window_days`, with that final day itself still inside the
        window, otherwise `ERR_DISPUTE_WINDOW_CLOSED`; and `claim_amount_cents` to be no greater than
        `amount_cents`, otherwise `ERR_CLAIM_EXCEEDS_DEDUCTION`."

        PRD: "Approval further requires at least two substantiation documents, otherwise
        `ERR_SUBSTANTIATION_INSUFFICIENT`, and requires `settlement_state` to still be `OPEN`,
        otherwise `ERR_DEDUCTION_ALREADY_SETTLED`."

        Design: Corner/endpoints/concede_settles_a_never_disputed_deduction_and_locks_it
        """
        scope = two_open_deductions_against_a_small_budget
        concede_the_large_deduction(api, scope)
        deduction_id = scope["large"]["id"]

        validate_error(
            concede(api, scope["large"]), ApiErrorId.DEDUCTION_ALREADY_SETTLED, 409
        )
        validate_error(
            api.dispute_deduction(
                deduction_id, F.dispute_payload(LARGE_AMOUNT_CENTS), ACCOUNT_MANAGER_HEADERS
            ),
            ApiErrorId.DEDUCTION_ALREADY_SETTLED,
            409,
        )
        validate_error(
            api.approve_recovery(deduction_id, AUDIT_MANAGER_HEADERS),
            ApiErrorId.DEDUCTION_ALREADY_SETTLED,
            409,
        )
        validate_error(
            api.deny_recovery(deduction_id, F.deny_payload("late"), AUDIT_MANAGER_HEADERS),
            ApiErrorId.DEDUCTION_ALREADY_SETTLED,
            409,
        )

        inert = fixtures.get_deduction(api, deduction_id)
        assert inert["settlement_state"] == DeductionSettlementState.CONCEDED
        assert inert["conceded_cents"] == LARGE_AMOUNT_CENTS
        assert inert["dispute_state"] == DisputeState.NOT_DISPUTED

    def test_the_settlement_state_filter_sees_the_new_state_at_once(
        self, api, two_open_deductions_against_a_small_budget
    ):
        """Exactly one of the principal's two deductions is CONCEDED.

        PRD: "Deductions may be filtered by `retailer_id`, `principal_id`, `promotion_event_id`,
        `original_deduction_id`, `reason_code`, `settlement_state` and `dispute_state`."

        Design: Corner/endpoints/concede_settles_a_never_disputed_deduction_and_locks_it
        """
        scope = two_open_deductions_against_a_small_budget
        concede_the_large_deduction(api, scope)

        rows, meta = validate_paginated(
            api.list_deductions(
                AUDIT_MANAGER_HEADERS,
                {
                    "principal_id": scope["principal"]["id"],
                    "settlement_state": DeductionSettlementState.CONCEDED,
                },
            )
        )

        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [scope["large"]["id"]]
