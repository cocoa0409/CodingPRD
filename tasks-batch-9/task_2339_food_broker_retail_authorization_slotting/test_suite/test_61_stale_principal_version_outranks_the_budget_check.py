"""Fixing the budget invalidates the pin, so the client must re-read before it can accept."""

import pytest

from test_helpers import (
    BROKER_ADMIN_HEADERS,
    ApiErrorId,
    AuthorizationState,
    CreditPosture,
    DealState,
    UPC_1,
    fixtures,
    get_success_data,
    make_retailer_buyer_headers,
    validate_error,
)
from test_helpers import factories as F

CHAIN_STORES = 1200
FULL_BUDGET_CENTS = 20000000
REDUCED_BUDGET_CENTS = 4000000
FEE_PER_STORE_CENTS = 12500
STORE_COUNT = 400
FORECAST_UNITS = 100000
GROSS_FEE_CENTS = 5000000
VOLUME_CREDIT_CENTS = 300000
NET_BEFORE_ADMIN_CENTS = 4700000
ADMIN_FEE_CENTS = 117500
QUOTED_FEE_CENTS = 4817500
EXPECTED_RATIO_BPS = 2408


@pytest.fixture
def proposed_deal_over_a_shrinkable_budget(api):
    """A decided review, an accepted deck and a standing broker offer of 4,817,500 cents."""
    retailer = fixtures.create_retailer(api, total_store_count=CHAIN_STORES)
    bundle = fixtures.active_principal(api, retailer["id"])
    principal = bundle["principal"]
    item = fixtures.validated_item(api, principal["id"], retailer["id"], upc=UPC_1)
    review = fixtures.opened_review(api, retailer["id"])
    presentation = fixtures.submitted_presentation(
        api, review["id"], principal["id"], [item["id"]]
    )
    deal = fixtures.proposed_deal(
        api,
        presentation["id"],
        fee_per_store_cents=FEE_PER_STORE_CENTS,
        store_count_in_scope=STORE_COUNT,
        item_count_in_scope=1,
        forecast_annual_units=FORECAST_UNITS,
        amortization_periods=4,
    )
    review = fixtures.lock_and_decide(api, review["id"], retailer["id"], [item["id"]])
    return {
        "retailer": retailer,
        "principal": principal,
        "agreement": bundle["agreement"],
        "item": item,
        "review": review,
        "presentation": presentation,
        "deal": deal,
        "base_version": fixtures.get_principal(api, principal["id"])["version"],
        "buyer_headers": make_retailer_buyer_headers(retailer["id"]),
    }


def set_budget(api, scope, slotting_budget_cents):
    return get_success_data(
        api.patch_principal(
            scope["principal"]["id"],
            F.principal_patch_payload(slotting_budget_cents=slotting_budget_cents),
            BROKER_ADMIN_HEADERS,
        ),
        200,
    )


def attempt_accept(api, scope, expected_principal_version):
    return api.accept_deal(
        scope["deal"]["id"],
        F.accept_payload(expected_principal_version),
        scope["buyer_headers"],
    )


def read_principal(api, scope):
    return fixtures.get_principal(api, scope["principal"]["id"])


class TestStalePrincipalVersionOutranksTheBudgetCheck:
    def test_the_standing_quote_is_the_figure_the_budget_check_will_use(
        self, api, proposed_deal_over_a_shrinkable_budget
    ):
        """400 stores at 12,500 cents, less a 300,000 volume credit, plus 250 basis points of admin.

        PRD: "The volume credit rewards forecast volume but is capped. The raw credit is
        `forecast_annual_units` multiplied by a credit rate of 3 cents per forecast case. The cap is
        4,000 basis points of the gross fee — forty percent of `gross_fee_cents`, floored to whole cents."

        PRD: "The administration rate is tiered on `net_before_admin_cents` and on nothing else: 250 basis
        points when `net_before_admin_cents` is at or below 5,000,000 cents (the fifty-thousand-dollar
        tier-1 ceiling, inclusive), and 150 basis points above it."

        Design: Corner/cross_cutting_complexity_layers/stale_principal_version_outranks_the_slotting_budget_check
        """
        scope = proposed_deal_over_a_shrinkable_budget

        deal = fixtures.get_deal(api, scope["deal"]["id"])

        assert deal["state"] == DealState.PROPOSED
        assert deal["gross_fee_cents"] == GROSS_FEE_CENTS
        assert deal["volume_credit_cents"] == VOLUME_CREDIT_CENTS
        assert deal["net_before_admin_cents"] == NET_BEFORE_ADMIN_CENTS
        assert deal["admin_fee_cents"] == ADMIN_FEE_CENTS
        assert deal["quoted_fee_cents"] == QUOTED_FEE_CENTS

    def test_the_awarded_slot_waits_in_pending_setup_while_the_deal_is_unaccepted(
        self, api, proposed_deal_over_a_shrinkable_budget
    ):
        """The award created the authorization; only acceptance turns it into shelf space.

        PRD: "The first hop moves every authorization linked to that deal on both dimensions at once:
        `authorization_state` from `PENDING_SETUP` to `AUTHORIZED`, and `settlement_state` from
        `UNBILLED` to `SLOTTING_AMORTIZING`. Distribution postings and promotion commitments only become
        possible once this has happened."

        PRD: "`slotting_committed_cents` is the sum of `accepted_fee_cents` over that principal's deals in
        state `ACCEPTED`, `AMORTIZING` or `RECOVERY_HOLD`"

        Design: Corner/cross_cutting_complexity_layers/stale_principal_version_outranks_the_slotting_budget_check
        """
        scope = proposed_deal_over_a_shrinkable_budget

        authorization = fixtures.authorization_for_deal(api, scope["deal"]["id"])

        assert authorization["authorization_state"] == AuthorizationState.PENDING_SETUP
        principal = read_principal(api, scope)
        assert principal["slotting_committed_cents"] == 0
        assert principal["slotting_budget_cents"] == FULL_BUDGET_CENTS

    def test_moving_the_budget_is_itself_a_write_on_the_principal(
        self, api, proposed_deal_over_a_shrinkable_budget
    ):
        """Nothing is committed yet, so a smaller denominator still leaves the posture at NORMAL.

        PRD: "A `BrokerAdmin` may later adjust the principal's `name` or `slotting_budget_cents`; because
        the budget is the denominator of the liability ratio, changing it immediately re-derives
        `liability_ratio_bps` and `credit_posture` and advances the principal's `version`."

        PRD: "Because a zero budget yields a ratio of 0, a zero-budget principal can never become
        `RESTRICTED` by ratio — only by accumulating at-risk authorizations."

        Design: Corner/cross_cutting_complexity_layers/stale_principal_version_outranks_the_slotting_budget_check
        """
        scope = proposed_deal_over_a_shrinkable_budget

        reduced = set_budget(api, scope, REDUCED_BUDGET_CENTS)

        assert reduced["slotting_budget_cents"] == REDUCED_BUDGET_CENTS
        assert reduced["version"] == scope["base_version"] + 1
        assert reduced["liability_ratio_bps"] == 0
        assert reduced["credit_posture"] == CreditPosture.NORMAL

    def test_the_stale_pin_hides_the_budget_problem_entirely(
        self, api, proposed_deal_over_a_shrinkable_budget
    ):
        """The same request breaks the concurrency rule and the fiscal rule; band 6 answers first.

        PRD: "`POST /slotting-deals/{dealId}/accept` requires `expected_principal_version`, carrying the
        client's last observed `version` of the `Principal` that owns the deal. Accepting a deal commits
        `quoted_fee_cents` against that principal's shared slotting budget; if another deal's acceptance, a
        status change or a deduction settlement has since advanced the principal's `version`, the
        acceptance is rejected with `ERR_STALE_PRINCIPAL_VERSION` (HTTP 412) instead of being evaluated
        against a budget the client never saw."

        PRD: "**Fiscal limits.** `ERR_REVIEW_SLOTS_EXCEEDED` on the award decision;
        `ERR_PRINCIPAL_CREDIT_RESTRICTED` on presentation submission and slotting-deal acceptance;
        `ERR_SLOTTING_BUDGET_EXCEEDED` on slotting-deal acceptance; `ERR_PROMO_FUNDING_OVERRUN` on
        promotion execution. All are HTTP 409."

        Design: Corner/cross_cutting_complexity_layers/stale_principal_version_outranks_the_slotting_budget_check
        """
        scope = proposed_deal_over_a_shrinkable_budget
        set_budget(api, scope, REDUCED_BUDGET_CENTS)

        response = attempt_accept(api, scope, scope["base_version"])

        validate_error(response, ApiErrorId.STALE_PRINCIPAL_VERSION, 412)

    def test_only_a_fresh_pin_exposes_the_real_fiscal_rejection(
        self, api, proposed_deal_over_a_shrinkable_budget
    ):
        """0 committed plus a 4,817,500 quote overruns the 4,000,000 budget, and the deal stays PROPOSED.

        PRD: "the principal's `slotting_committed_cents` plus this deal's `quoted_fee_cents` must not
        exceed its `slotting_budget_cents`, otherwise `ERR_SLOTTING_BUDGET_EXCEEDED`"

        PRD: "Later violations are never reported, so a request that breaks three rules always returns the
        code of the earliest band it fails."

        Design: Corner/cross_cutting_complexity_layers/stale_principal_version_outranks_the_slotting_budget_check
        """
        scope = proposed_deal_over_a_shrinkable_budget
        reduced = set_budget(api, scope, REDUCED_BUDGET_CENTS)
        validate_error(
            attempt_accept(api, scope, scope["base_version"]),
            ApiErrorId.STALE_PRINCIPAL_VERSION,
            412,
        )

        response = attempt_accept(api, scope, reduced["version"])

        validate_error(response, ApiErrorId.SLOTTING_BUDGET_EXCEEDED, 409)
        assert fixtures.get_deal(api, scope["deal"]["id"])["state"] == DealState.PROPOSED

    def test_neither_refused_acceptance_advanced_the_principal(
        self, api, proposed_deal_over_a_shrinkable_budget
    ):
        """A rejected write is not a partial write, so the pin the client just used is still valid.

        PRD: "Mutable resources additionally carry `updated_at`, an ISO 8601 UTC timestamp refreshed on
        every change to the resource, and `version`, an integer that is 1 when the resource is created and
        increases by exactly one on every mutation of that resource."

        Design: Corner/cross_cutting_complexity_layers/stale_principal_version_outranks_the_slotting_budget_check
        """
        scope = proposed_deal_over_a_shrinkable_budget
        reduced = set_budget(api, scope, REDUCED_BUDGET_CENTS)
        validate_error(
            attempt_accept(api, scope, scope["base_version"]),
            ApiErrorId.STALE_PRINCIPAL_VERSION,
            412,
        )
        validate_error(
            attempt_accept(api, scope, reduced["version"]),
            ApiErrorId.SLOTTING_BUDGET_EXCEEDED,
            409,
        )

        after = read_principal(api, scope)

        assert after["version"] == reduced["version"]
        assert after["slotting_committed_cents"] == 0

    def test_curing_the_budget_makes_the_clients_pin_stale_all_over_again(
        self, api, proposed_deal_over_a_shrinkable_budget
    ):
        """The fix for the 409 is itself a mutation, so the retry loop has to run twice.

        PRD: "If the pinned value does not equal the parent's current `version`, the write is refused
        rather than applied on top of a parent state the client never read."

        PRD: "**Concurrency.** The three version pins of §2.7, returning `ERR_STALE_PRINCIPAL_VERSION`,
        `ERR_STALE_AUTHORIZATION_VERSION` or `ERR_STALE_REVIEW_VERSION` (all 412)."

        Design: Corner/cross_cutting_complexity_layers/stale_principal_version_outranks_the_slotting_budget_check
        """
        scope = proposed_deal_over_a_shrinkable_budget
        reduced = set_budget(api, scope, REDUCED_BUDGET_CENTS)
        validate_error(
            attempt_accept(api, scope, reduced["version"]),
            ApiErrorId.SLOTTING_BUDGET_EXCEEDED,
            409,
        )

        restored = set_budget(api, scope, FULL_BUDGET_CENTS)

        assert restored["version"] == reduced["version"] + 1
        validate_error(
            attempt_accept(api, scope, reduced["version"]),
            ApiErrorId.STALE_PRINCIPAL_VERSION,
            412,
        )

    def test_the_third_attempt_accepts_and_commits_the_quote(
        self, api, proposed_deal_over_a_shrinkable_budget
    ):
        """Same deal, same fee, twice refused — and the accepted figure is the standing quote.

        PRD: "Acceptance freezes `accepted_fee_cents` at the standing `quoted_fee_cents`, sets
        `unamortized_balance_cents` to that same figure, and computes `cost_per_forecast_unit_cents` as
        `accepted_fee_cents` divided by `forecast_annual_units`, rounded half up to two decimal places —
        null when `forecast_annual_units` is zero."

        PRD: "The deal does not rest in `ACCEPTED`: the system advances it `ACCEPTED` → `AMORTIZING`
        inside the same request, which is where the cascade of §3.6 fires, and the principal's `version`
        advances by one."

        Design: Corner/cross_cutting_complexity_layers/stale_principal_version_outranks_the_slotting_budget_check
        """
        scope = proposed_deal_over_a_shrinkable_budget
        reduced = set_budget(api, scope, REDUCED_BUDGET_CENTS)
        validate_error(
            attempt_accept(api, scope, reduced["version"]),
            ApiErrorId.SLOTTING_BUDGET_EXCEEDED,
            409,
        )
        restored = set_budget(api, scope, FULL_BUDGET_CENTS)

        accepted = get_success_data(attempt_accept(api, scope, restored["version"]), 200)

        assert accepted["state"] == DealState.AMORTIZING
        assert accepted["accepted_fee_cents"] == QUOTED_FEE_CENTS
        assert accepted["unamortized_balance_cents"] == QUOTED_FEE_CENTS

    def test_the_acceptance_re_derives_the_principals_liability_ratio(
        self, api, proposed_deal_over_a_shrinkable_budget
    ):
        """4,817,500 of open liability against a 20,000,000 budget floors to 2,408 basis points.

        PRD: "The third hop re-derives the principal: `slotting_committed_cents`,
        `open_slotting_liability_cents` and `liability_ratio_bps` are recomputed and `credit_posture` is
        re-derived, which may move the principal from `NORMAL` to `WATCH` or `RESTRICTED` in the very
        request that accepted the deal."

        PRD: "otherwise it is the sum of `open_slotting_liability_cents` and `open_deduction_cents`,
        multiplied by 10,000, divided by `slotting_budget_cents`, floored to whole basis points."

        Design: Corner/cross_cutting_complexity_layers/stale_principal_version_outranks_the_slotting_budget_check
        """
        scope = proposed_deal_over_a_shrinkable_budget
        set_budget(api, scope, REDUCED_BUDGET_CENTS)
        restored = set_budget(api, scope, FULL_BUDGET_CENTS)
        get_success_data(attempt_accept(api, scope, restored["version"]), 200)

        after = read_principal(api, scope)

        assert after["version"] == restored["version"] + 1
        assert after["slotting_committed_cents"] == QUOTED_FEE_CENTS
        assert after["open_slotting_liability_cents"] == QUOTED_FEE_CENTS
        assert after["liability_ratio_bps"] == EXPECTED_RATIO_BPS
        assert after["credit_posture"] == CreditPosture.NORMAL
