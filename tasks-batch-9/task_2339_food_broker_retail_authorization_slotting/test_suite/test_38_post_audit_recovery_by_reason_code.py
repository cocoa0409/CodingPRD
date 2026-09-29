"""The same approval endpoint recovers four different amounts, one per reason code."""

import pytest

from test_helpers import (
    ApiErrorId,
    DeductionReasonCode,
    DeductionSettlementState,
    DisputeState,
    SHORTAGE_ALLOWANCE_BPS,
    fixtures,
    make_retailer_buyer_headers,
    validate_error,
)
from test_helpers import factories as F
from test_helpers.assertions import (
    assert_deduction_money_conserved,
    expected_compliance_fine_recovery,
    expected_duplicate_billback_recovery,
    expected_shortage_recovery,
)

ORIGINAL_AMOUNT_CENTS = 60000
SHORTAGE_AMOUNT_CENTS = 90001
SHORTAGE_RECOVERABLE_CENTS = 45000
COMPLIANCE_FINE_AMOUNT_CENTS = 75000


@pytest.fixture
def chain_with_an_original_deduction(api):
    """A retailer, a principal and one untouched 60,000 deduction to link duplicates against."""
    retailer = fixtures.create_retailer(api, total_store_count=1200)
    bundle = fixtures.active_principal(api, retailer["id"])
    principal = bundle["principal"]
    original = fixtures.create_deduction(
        api,
        retailer["id"],
        principal["id"],
        reason_code=DeductionReasonCode.SHORTAGE,
        amount_cents=ORIGINAL_AMOUNT_CENTS,
    )
    return {"retailer": retailer, "principal": principal, "original": original}


def attempt_deduction(api, scope, **overrides):
    return api.create_deduction(
        F.deduction_payload(scope["retailer"]["id"], scope["principal"]["id"], **overrides),
        make_retailer_buyer_headers(scope["retailer"]["id"]),
    )


def settle(api, scope, *, reason_code, amount_cents, **overrides):
    """File the whole amount as the claim, substantiate twice and approve."""
    deduction = fixtures.substantiated_deduction(
        api,
        scope["retailer"]["id"],
        scope["principal"]["id"],
        amount_cents=amount_cents,
        reason_code=reason_code,
        **overrides,
    )
    return fixtures.approve_recovery(api, deduction["id"])


class TestPostAuditRecoveryByReasonCode:
    def test_a_duplicate_billback_must_match_its_original_amount(
        self, api, chain_with_an_original_deduction
    ):
        """60,001 cannot be a duplicate of a 60,000 charge.

        PRD: "A `DUPLICATE_BILLBACK` requires `original_deduction_id` referencing a *different*
        deduction of the same chain and principal with an equal `amount_cents`, otherwise
        `ERR_DUPLICATE_LINK_INVALID`; that field too must be omitted for every other reason code."

        Design: Corner/calculations/post_audit_recoverable_amount_differs_by_reason_code
        """
        scope = chain_with_an_original_deduction

        response = attempt_deduction(
            api,
            scope,
            reason_code=DeductionReasonCode.DUPLICATE_BILLBACK,
            amount_cents=ORIGINAL_AMOUNT_CENTS + 1,
            original_deduction_id=scope["original"]["id"],
        )

        validate_error(response, ApiErrorId.DUPLICATE_LINK_INVALID, 422)

    def test_a_promotional_billback_without_its_event_is_refused(
        self, api, chain_with_an_original_deduction
    ):
        """There is no promotion to net the claim against, so the link is invalid.

        PRD: "A `PROMO_BILLBACK` requires `promotion_event_id`, and the referenced event's
        authorization must belong to the same principal and the same chain, otherwise
        `ERR_PROMO_LINK_INVALID`; the field must be omitted for every other reason code."

        Design: Corner/calculations/post_audit_recoverable_amount_differs_by_reason_code
        """
        response = attempt_deduction(
            api,
            chain_with_an_original_deduction,
            reason_code=DeductionReasonCode.PROMO_BILLBACK,
            amount_cents=50000,
        )

        validate_error(response, ApiErrorId.PROMO_LINK_INVALID, 422)

    def test_a_shortage_recovers_half_the_charge_floored(
        self, api, chain_with_an_original_deduction
    ):
        """Half of 90,001 is 45,000.5, and the allowance floors it to 45,000.

        PRD: "A `SHORTAGE` is capped by a contractual allowance of 5,000 basis points: the
        recoverable amount is the smaller of `claim_amount_cents` and half of `amount_cents` floored
        to whole cents."

        Design: Corner/calculations/post_audit_recoverable_amount_differs_by_reason_code
        """
        settled = settle(
            api,
            chain_with_an_original_deduction,
            reason_code=DeductionReasonCode.SHORTAGE,
            amount_cents=SHORTAGE_AMOUNT_CENTS,
        )

        assert SHORTAGE_AMOUNT_CENTS * SHORTAGE_ALLOWANCE_BPS // 10000 == SHORTAGE_RECOVERABLE_CENTS
        assert expected_shortage_recovery(
            SHORTAGE_AMOUNT_CENTS, SHORTAGE_AMOUNT_CENTS
        ) == SHORTAGE_RECOVERABLE_CENTS
        assert settled["recovered_cents"] == SHORTAGE_RECOVERABLE_CENTS
        assert settled["conceded_cents"] == SHORTAGE_AMOUNT_CENTS - SHORTAGE_RECOVERABLE_CENTS
        assert settled["open_cents"] == 0
        assert settled["settlement_state"] == DeductionSettlementState.RECOVERED

    def test_an_approved_compliance_fine_settles_conceded(
        self, api, chain_with_an_original_deduction
    ):
        """The claim dimension reaches APPROVED while the money dimension concedes everything.

        PRD: "A `COMPLIANCE_FINE` is never recoverable at all — its recoverable amount is zero."

        PRD: "`settlement_state` moves `OPEN` → `RECOVERED` when the recoverable amount is above
        zero, and `OPEN` → `CONCEDED` when it is zero — so an approved compliance fine still records
        `dispute_state` as `APPROVED` while its money lands in `CONCEDED`."

        Design: Corner/calculations/post_audit_recoverable_amount_differs_by_reason_code
        """
        settled = settle(
            api,
            chain_with_an_original_deduction,
            reason_code=DeductionReasonCode.COMPLIANCE_FINE,
            amount_cents=COMPLIANCE_FINE_AMOUNT_CENTS,
        )

        assert expected_compliance_fine_recovery() == 0
        assert settled["recovered_cents"] == 0
        assert settled["conceded_cents"] == COMPLIANCE_FINE_AMOUNT_CENTS
        assert settled["open_cents"] == 0
        assert settled["settlement_state"] == DeductionSettlementState.CONCEDED
        assert settled["dispute_state"] == DisputeState.APPROVED

    def test_a_duplicate_billback_recovers_the_whole_claim(
        self, api, chain_with_an_original_deduction
    ):
        """The original charge already covers the goods, so nothing is conceded.

        PRD: "A `DUPLICATE_BILLBACK` is fully recoverable up to the claim: the recoverable amount is
        `claim_amount_cents`, because the original deduction already covers the charge."

        Design: Corner/calculations/post_audit_recoverable_amount_differs_by_reason_code
        """
        scope = chain_with_an_original_deduction

        settled = settle(
            api,
            scope,
            reason_code=DeductionReasonCode.DUPLICATE_BILLBACK,
            amount_cents=ORIGINAL_AMOUNT_CENTS,
            original_deduction_id=scope["original"]["id"],
        )

        assert expected_duplicate_billback_recovery(ORIGINAL_AMOUNT_CENTS) == ORIGINAL_AMOUNT_CENTS
        assert settled["recovered_cents"] == ORIGINAL_AMOUNT_CENTS
        assert settled["conceded_cents"] == 0
        assert settled["settlement_state"] == DeductionSettlementState.RECOVERED

    def test_only_the_untouched_deduction_still_counts_as_open(
        self, api, chain_with_an_original_deduction
    ):
        """Three settlements later, the principal's open deduction total is the original alone.

        PRD: "On a deduction, `amount_cents` always equals `recovered_cents` plus `conceded_cents`
        plus `open_cents`."

        PRD: "In every case the principal's `open_deduction_cents` and `liability_ratio_bps` are
        recomputed and `credit_posture` re-derived."

        Design: Corner/calculations/post_audit_recoverable_amount_differs_by_reason_code
        """
        scope = chain_with_an_original_deduction

        shortage = settle(
            api,
            scope,
            reason_code=DeductionReasonCode.SHORTAGE,
            amount_cents=SHORTAGE_AMOUNT_CENTS,
        )
        fine = settle(
            api,
            scope,
            reason_code=DeductionReasonCode.COMPLIANCE_FINE,
            amount_cents=COMPLIANCE_FINE_AMOUNT_CENTS,
        )
        duplicate = settle(
            api,
            scope,
            reason_code=DeductionReasonCode.DUPLICATE_BILLBACK,
            amount_cents=ORIGINAL_AMOUNT_CENTS,
            original_deduction_id=scope["original"]["id"],
        )

        for settled in (shortage, fine, duplicate):
            assert_deduction_money_conserved(settled)

        original = fixtures.get_deduction(api, scope["original"]["id"])
        assert original["settlement_state"] == DeductionSettlementState.OPEN
        assert original["open_cents"] == ORIGINAL_AMOUNT_CENTS

        principal = fixtures.get_principal(api, scope["principal"]["id"])
        assert principal["open_deduction_cents"] == ORIGINAL_AMOUNT_CENTS
