"""Both liability thresholds are inclusive, and only RESTRICTED closes the door on new decks."""

import pytest

from test_helpers import (
    ACCOUNT_MANAGER_HEADERS,
    BROKER_ADMIN_HEADERS,
    ApiErrorId,
    CreditPosture,
    PresentationStatus,
    UPC_1,
    UPC_2,
    fixtures,
    get_success_data,
    validate_error,
)
from test_helpers import factories as F
from test_helpers.assertions import (
    assert_version_bumped_by,
    expected_credit_posture,
    expected_liability_ratio_bps,
)

DAIRY = "DAIRY"
ACCEPTED_FEE_CENTS = 5125000
ORIGINAL_BUDGET_CENTS = 20000000
WATCH_BUDGET_CENTS = 10250000
NORMAL_BUDGET_CENTS = 10250001
JUST_UNDER_RESTRICTED_BUDGET_CENTS = 6833334
RESTRICTED_BUDGET_CENTS = 6833333
DAIRY_DEADLINE = "2026-09-25T00:00:00Z"


@pytest.fixture
def principal_carrying_one_accepted_deal(api):
    """5,125,000 of open slotting liability against a 20,000,000 budget, plus a DRAFT DAIRY deck."""
    retailer = fixtures.create_retailer(api, total_store_count=1200)
    bundle = fixtures.active_principal(
        api,
        retailer["id"],
        principal_overrides={"slotting_budget_cents": ORIGINAL_BUDGET_CENTS},
    )
    principal = bundle["principal"]
    fixtures.create_agreement(
        api, principal["id"], retailer["id"], activate=True, category_code=DAIRY
    )
    frozen_item = fixtures.validated_item(api, principal["id"], retailer["id"], upc=UPC_1)
    dairy_item = fixtures.validated_item(api, principal["id"], retailer["id"], upc=UPC_2)

    frozen_review = fixtures.opened_review(api, retailer["id"])
    presentation = fixtures.submitted_presentation(
        api, frozen_review["id"], principal["id"], [frozen_item["id"]]
    )
    deal = fixtures.proposed_deal(
        api,
        presentation["id"],
        fee_per_store_cents=12500,
        store_count_in_scope=400,
        item_count_in_scope=1,
        forecast_annual_units=0,
        amortization_periods=6,
    )
    fixtures.lock_and_decide(
        api, frozen_review["id"], retailer["id"], [frozen_item["id"]]
    )
    fixtures.accept_as_buyer(api, deal["id"], retailer["id"], principal["id"])

    dairy_review = fixtures.opened_review(
        api,
        retailer["id"],
        category_code=DAIRY,
        review_window_start="2026-10-01",
        review_window_end="2026-10-15",
        submission_deadline=DAIRY_DEADLINE,
    )
    dairy_presentation = fixtures.create_presentation(
        api, dairy_review["id"], principal["id"], [dairy_item["id"]]
    )
    return {
        "retailer": retailer,
        "principal": principal,
        "dairy_review": dairy_review,
        "dairy_presentation": dairy_presentation,
    }


def set_budget(api, scope, slotting_budget_cents):
    response = api.patch_principal(
        scope["principal"]["id"],
        F.principal_patch_payload(slotting_budget_cents=slotting_budget_cents),
        BROKER_ADMIN_HEADERS,
    )
    return get_success_data(response, 200)


def submit_the_dairy_deck(api, scope):
    return api.submit_presentation(
        scope["dairy_presentation"]["id"], ACCOUNT_MANAGER_HEADERS
    )


class TestCreditPostureThresholdsGateSubmission:
    def test_the_starting_ratio_is_floored_and_leaves_the_principal_normal(
        self, api, principal_carrying_one_accepted_deal
    ):
        """5,125,000 against 20,000,000 is 2,562.5 basis points, floored to 2,562.

        PRD: "`liability_ratio_bps` is 0 whenever `slotting_budget_cents` is 0; otherwise it is the
        sum of `open_slotting_liability_cents` and `open_deduction_cents`, multiplied by 10,000,
        divided by `slotting_budget_cents`, floored to whole basis points."

        Design: Corner/calculations/credit_posture_thresholds_are_inclusive_and_gate_submission
        """
        principal = fixtures.get_principal(
            api, principal_carrying_one_accepted_deal["principal"]["id"]
        )

        assert principal["open_slotting_liability_cents"] == ACCEPTED_FEE_CENTS
        assert principal["open_deduction_cents"] == 0
        assert principal["at_risk_authorization_count"] == 0
        assert principal["liability_ratio_bps"] == expected_liability_ratio_bps(
            ACCEPTED_FEE_CENTS, 0, ORIGINAL_BUDGET_CENTS
        )
        assert principal["liability_ratio_bps"] == 2562
        assert principal["credit_posture"] == CreditPosture.NORMAL

    def test_the_watch_threshold_is_inclusive_and_one_cent_of_budget_undoes_it(
        self, api, principal_carrying_one_accepted_deal
    ):
        """Exactly 5,000 basis points is WATCH; 4,999 is not.

        PRD: "`credit_posture` is then derived against two inclusive thresholds and one count: it
        is `RESTRICTED` when `at_risk_authorization_count` is 2 or more, or `liability_ratio_bps` is
        7,500 or more — that is, when open liability plus open deductions reach seventy-five percent
        of the budget; failing that it is `WATCH` when `at_risk_authorization_count` is 1 or more,
        or `liability_ratio_bps` is 5,000 or more, being fifty percent of the budget; and otherwise
        it is `NORMAL`."

        Design: Corner/calculations/credit_posture_thresholds_are_inclusive_and_gate_submission
        """
        scope = principal_carrying_one_accepted_deal

        at_threshold = set_budget(api, scope, WATCH_BUDGET_CENTS)
        assert at_threshold["liability_ratio_bps"] == 5000
        assert at_threshold["credit_posture"] == CreditPosture.WATCH

        below_threshold = set_budget(api, scope, NORMAL_BUDGET_CENTS)
        assert below_threshold["liability_ratio_bps"] == 4999
        assert below_threshold["credit_posture"] == CreditPosture.NORMAL

    def test_the_restricted_threshold_is_inclusive_too(
        self, api, principal_carrying_one_accepted_deal
    ):
        """7,499 basis points is still only WATCH; exactly 7,500 is RESTRICTED.

        PRD: "`credit_posture` is then derived against two inclusive thresholds and one count: it
        is `RESTRICTED` when `at_risk_authorization_count` is 2 or more, or `liability_ratio_bps` is
        7,500 or more — that is, when open liability plus open deductions reach seventy-five percent
        of the budget; failing that it is `WATCH` when `at_risk_authorization_count` is 1 or more,
        or `liability_ratio_bps` is 5,000 or more, being fifty percent of the budget; and otherwise
        it is `NORMAL`."

        Design: Corner/calculations/credit_posture_thresholds_are_inclusive_and_gate_submission
        """
        scope = principal_carrying_one_accepted_deal

        below_threshold = set_budget(api, scope, JUST_UNDER_RESTRICTED_BUDGET_CENTS)
        assert below_threshold["liability_ratio_bps"] == 7499
        assert below_threshold["credit_posture"] == CreditPosture.WATCH

        at_threshold = set_budget(api, scope, RESTRICTED_BUDGET_CENTS)
        assert at_threshold["liability_ratio_bps"] == 7500
        assert at_threshold["credit_posture"] == expected_credit_posture(7500, 0)
        assert at_threshold["credit_posture"] == CreditPosture.RESTRICTED

    def test_a_restricted_posture_blocks_a_deck_that_is_otherwise_fully_covered(
        self, api, principal_carrying_one_accepted_deal
    ):
        """The DAIRY agreement is ACTIVE and date-covering, so only the posture can refuse this.

        PRD: "Last comes the fiscal gate: the principal's `credit_posture` must not be
        `RESTRICTED`, otherwise `ERR_PRINCIPAL_CREDIT_RESTRICTED`."

        Design: Corner/calculations/credit_posture_thresholds_are_inclusive_and_gate_submission
        """
        scope = principal_carrying_one_accepted_deal
        set_budget(api, scope, RESTRICTED_BUDGET_CENTS)

        response = submit_the_dairy_deck(api, scope)

        validate_error(response, ApiErrorId.PRINCIPAL_CREDIT_RESTRICTED, 409)
        assert (
            get_success_data(
                api.get_presentation(scope["dairy_presentation"]["id"], ACCOUNT_MANAGER_HEADERS),
                200,
            )["status"]
            == PresentationStatus.DRAFT
        )

    def test_restoring_the_budget_lets_the_same_deck_through(
        self, api, principal_carrying_one_accepted_deal
    ):
        """Nothing about the deck changed — only the denominator of the liability ratio did.

        PRD: "On success `submitted_at` is stamped from the logical clock and
        `prep_completeness_bps` is recomputed — necessarily 10,000, since every listed item has been
        validated."

        Design: Corner/calculations/credit_posture_thresholds_are_inclusive_and_gate_submission
        """
        scope = principal_carrying_one_accepted_deal
        set_budget(api, scope, RESTRICTED_BUDGET_CENTS)
        validate_error(
            submit_the_dairy_deck(api, scope), ApiErrorId.PRINCIPAL_CREDIT_RESTRICTED, 409
        )

        set_budget(api, scope, ORIGINAL_BUDGET_CENTS)

        submitted = get_success_data(submit_the_dairy_deck(api, scope), 200)
        assert submitted["status"] == PresentationStatus.SUBMITTED
        assert submitted["prep_completeness_bps"] == 10000

    def test_a_budget_adjustment_moves_the_version_but_never_the_committed_total(
        self, api, principal_carrying_one_accepted_deal
    ):
        """The budget is the denominator only; the money already committed is untouched.

        PRD: "A `BrokerAdmin` may later adjust the principal's `name` or `slotting_budget_cents`;
        because the budget is the denominator of the liability ratio, changing it immediately
        re-derives `liability_ratio_bps` and `credit_posture` and advances the principal's
        `version`."

        Design: Corner/calculations/credit_posture_thresholds_are_inclusive_and_gate_submission
        """
        scope = principal_carrying_one_accepted_deal
        before = fixtures.get_principal(api, scope["principal"]["id"])

        after_first = set_budget(api, scope, WATCH_BUDGET_CENTS)
        after_second = set_budget(api, scope, RESTRICTED_BUDGET_CENTS)

        assert_version_bumped_by(before, after_first, 1)
        assert_version_bumped_by(after_first, after_second, 1)
        assert after_first["slotting_committed_cents"] == ACCEPTED_FEE_CENTS
        assert after_second["slotting_committed_cents"] == ACCEPTED_FEE_CENTS
