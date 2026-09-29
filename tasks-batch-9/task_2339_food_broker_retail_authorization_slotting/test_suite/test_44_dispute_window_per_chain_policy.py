"""Two chains, one deduction date, one clock: the dispute window is a per-chain policy field."""

import pytest

from test_helpers import (
    ACCOUNT_MANAGER_HEADERS,
    ApiErrorId,
    DeductionReasonCode,
    DeductionSettlementState,
    DisputeState,
    FILER_USER_ID,
    fixtures,
    validate_error,
)
from test_helpers import factories as F

AMOUNT_CENTS = 40000
DEDUCTION_DATE = "2026-08-01"
SHORT_WINDOW_DAYS = 5
LAST_OPEN_INSTANT = "2026-08-06T23:59:59Z"
FIRST_CLOSED_INSTANT = "2026-08-07T00:00:00Z"


@pytest.fixture
def two_chains_with_different_dispute_windows(api):
    """BIGMART keeps the 90-day default; SHORTCO cuts its window to five days."""
    default_chain = fixtures.create_retailer(api, total_store_count=1200)
    short_chain = fixtures.create_retailer(
        api,
        name="Shortco",
        chain_code="SHORTCO",
        total_store_count=90,
        deduction_dispute_window_days=SHORT_WINDOW_DAYS,
    )
    principal = fixtures.create_principal(api, slotting_budget_cents=20000000)

    def deduct(retailer):
        return fixtures.create_deduction(
            api,
            retailer["id"],
            principal["id"],
            reason_code=DeductionReasonCode.SHORTAGE,
            amount_cents=AMOUNT_CENTS,
            deduction_date=DEDUCTION_DATE,
        )

    return {
        "default_chain": default_chain,
        "short_chain": short_chain,
        "principal": principal,
        "under_default_window": deduct(default_chain),
        "first_under_short_window": deduct(short_chain),
        "second_under_short_window": deduct(short_chain),
    }


def attempt_claim(api, deduction):
    return api.dispute_deduction(
        deduction["id"], F.dispute_payload(AMOUNT_CENTS), ACCOUNT_MANAGER_HEADERS
    )


class TestDisputeWindowPerChainPolicy:
    def test_the_final_day_of_the_short_window_still_admits_a_claim(
        self, api, two_chains_with_different_dispute_windows
    ):
        """2026-08-06 is exactly the deduction date plus five days, and that day is still inside.

        PRD: "It requires `settlement_state` to still be `OPEN`, otherwise
        `ERR_DEDUCTION_ALREADY_SETTLED`; the logical-clock date to be no later than `deduction_date`
        plus the chain's `deduction_dispute_window_days`, with that final day itself still inside the
        window, otherwise `ERR_DISPUTE_WINDOW_CLOSED`; and `claim_amount_cents` to be no greater than
        `amount_cents`, otherwise `ERR_CLAIM_EXCEEDS_DEDUCTION`."

        PRD: "Filing persists the claim, records the acting `X-User-ID` as `filed_by_user_id`, and
        resets `substantiation_doc_count` to 0."

        Design: Corner/validations/dispute_window_length_is_conditional_on_the_retailers_own_policy
        """
        scope = two_chains_with_different_dispute_windows
        fixtures.set_clock(api, LAST_OPEN_INSTANT)

        filed = fixtures.file_claim(
            api, scope["first_under_short_window"]["id"], AMOUNT_CENTS
        )

        assert filed["dispute_state"] == DisputeState.FILED
        assert filed["claim_amount_cents"] == AMOUNT_CENTS
        assert filed["filed_by_user_id"] == FILER_USER_ID
        assert filed["substantiation_doc_count"] == 0

    def test_one_day_later_the_short_window_is_closed(
        self, api, two_chains_with_different_dispute_windows
    ):
        """The very next instant refuses an identically shaped claim under the same chain.

        PRD: "`deduction_dispute_window_days` defaults to 90 days and bounds how long after a
        deduction a claim may still be filed."

        PRD: "`ERR_DISPUTE_WINDOW_CLOSED` guards filing and refiling a post-audit claim;
        `ERR_PROMO_WINDOW_IN_PAST` guards committing a promotion and `ERR_PROMO_NOT_ELAPSED` guards
        executing one."

        Design: Corner/validations/dispute_window_length_is_conditional_on_the_retailers_own_policy
        """
        scope = two_chains_with_different_dispute_windows
        fixtures.set_clock(api, FIRST_CLOSED_INSTANT)

        response = attempt_claim(api, scope["second_under_short_window"])

        validate_error(response, ApiErrorId.DISPUTE_WINDOW_CLOSED, 422)
        untouched = fixtures.get_deduction(api, scope["second_under_short_window"]["id"])
        assert untouched["dispute_state"] == DisputeState.NOT_DISPUTED
        assert untouched["filed_by_user_id"] is None

    def test_the_default_window_is_still_open_on_the_very_same_clock(
        self, api, two_chains_with_different_dispute_windows
    ):
        """Same date, same instant, different chain policy — and this one accepts the claim.

        PRD: "The chain record is also where the retailer's operating policy lives, and each policy
        field has a declared default that applies when the field is omitted at registration."

        PRD: "`deduction_dispute_window_days` defaults to 90 days and bounds how long after a
        deduction a claim may still be filed."

        Design: Corner/validations/dispute_window_length_is_conditional_on_the_retailers_own_policy
        """
        scope = two_chains_with_different_dispute_windows
        fixtures.set_clock(api, FIRST_CLOSED_INSTANT)
        validate_error(
            attempt_claim(api, scope["second_under_short_window"]),
            ApiErrorId.DISPUTE_WINDOW_CLOSED,
            422,
        )

        filed = fixtures.file_claim(api, scope["under_default_window"]["id"], AMOUNT_CENTS)

        assert filed["dispute_state"] == DisputeState.FILED
        assert filed["retailer_id"] == scope["default_chain"]["id"]

    def test_filing_a_claim_never_moves_money(
        self, api, two_chains_with_different_dispute_windows
    ):
        """Both accepted filings leave the whole charge open on the money dimension.

        PRD: "While a dispute is merely `FILED`, `SUBSTANTIATED` or `DENIED`, both `recovered_cents`
        and `conceded_cents` are 0 and `open_cents` equals `amount_cents` — a denial followed by a
        refile is money-neutral."

        Design: Corner/validations/dispute_window_length_is_conditional_on_the_retailers_own_policy
        """
        scope = two_chains_with_different_dispute_windows
        fixtures.set_clock(api, LAST_OPEN_INSTANT)
        short_chain_claim = fixtures.file_claim(
            api, scope["first_under_short_window"]["id"], AMOUNT_CENTS
        )
        default_chain_claim = fixtures.file_claim(
            api, scope["under_default_window"]["id"], AMOUNT_CENTS
        )

        for filed in (short_chain_claim, default_chain_claim):
            assert filed["settlement_state"] == DeductionSettlementState.OPEN
            assert filed["open_cents"] == AMOUNT_CENTS
            assert filed["recovered_cents"] == 0
            assert filed["conceded_cents"] == 0
