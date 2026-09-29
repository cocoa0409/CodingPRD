"""Three different pairs of simultaneously violated rules, each resolved by the
screening ladder's tier order."""

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import factories
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import BASELINE_NET_ASSESSED_CENTS
from test_helpers.fixtures import (
    build_asset_sale,
    build_issued_assessment,
    file_review_request,
    get_assessment,
    get_employer,
    get_group,
    get_installment,
    get_review_request,
    get_transaction,
    installment_at,
    set_clock,
)
from test_helpers.test_users import (
    FUND_ADMINISTRATOR_HEADERS,
    PLAN_TRUSTEE_HEADERS,
    make_employer_representative_headers,
)
from test_helpers.types import AdjudicationDisposition

UNDERBONDED_SALE = {
    "closing_date": "2026-02-01T00:00:00Z",
    "closing_plan_year": 2026,
    "purchase_price_cents": 300_000_000,
    "bond_amount_cents": 0,
    "buyer_assumes_contribution_obligation": False,
    "workforce_continuity_pct": 0.80,
    "asset_continuity_pct": 0.60,
    "customer_continuity_pct": 0.60,
}

RISING_SELLER_HISTORY = (
    {
        "plan_year_start": 2023,
        "plan_year_end": 2023,
        "contribution_base_units": 20_000,
        "contribution_amount_cents": 20_000_000,
        "contribution_rate_cents_per_cbu": 1_000,
    },
    {
        "plan_year_start": 2024,
        "plan_year_end": 2024,
        "contribution_base_units": 25_000,
        "contribution_amount_cents": 25_000_000,
        "contribution_rate_cents_per_cbu": 1_000,
    },
    {
        "plan_year_start": 2025,
        "plan_year_end": 2025,
        "contribution_base_units": 30_000,
        "contribution_amount_cents": 30_000_000,
        "contribution_rate_cents_per_cbu": 1_000,
    },
)


def _underbonded_sale(api):
    return build_asset_sale(
        api,
        contribution_entries=RISING_SELLER_HISTORY,
        sale_overrides=dict(UNDERBONDED_SALE),
        employer_overrides={"obligation_start_year": 2021, "cba_count": 2},
    )


def _pending_review_past_the_outer_bound(api):
    scenario = build_issued_assessment(
        api, employer_overrides={"obligation_start_year": 2021, "cba_count": 1}
    )
    set_clock(api, "2026-09-01T00:00:00Z")
    scenario["review_request"] = file_review_request(
        api,
        scenario["assessment"]["id"],
        scenario["employer"]["id"],
        challenged_assumption="UVB_POOL_ALLOCATION",
    )
    set_clock(api, "2027-03-01T00:00:00Z")
    return scenario


class TestStateBeatsFiscalExactness:
    def test_an_unswept_installment_reports_the_state_error_not_the_amount_error(self, api):
        """Tendering one cent against an instalment that is still SCHEDULED violates both
        the payability rule and the exactness rule; payability is screened first.

        PRD 2.9: "**State preconditions.** Every "the row is not in a state that permits
        this" rejection, all at HTTP 409"

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_when_paying_a_scheduled_installment_with_a_wrong_amount
        """
        scenario = build_issued_assessment(
            api, employer_overrides={"obligation_start_year": 2021, "cba_count": 1}
        )
        first = installment_at(api, scenario["schedule"]["id"], 1)
        assert first["status"] == "SCHEDULED"

        response = api.pay_installment(
            first["id"],
            factories.payment_payload(1),
            make_employer_representative_headers(scenario["employer"]["id"]),
        )
        validate_error(response, ApiErrorId.INSTALLMENT_NOT_PAYABLE.value, 409)

    def test_the_rejected_payment_moves_no_money(self, api):
        """The instalment keeps its SCHEDULED status with nothing paid and the employer's
        balance is untouched.

        PRD 3.7: "The instalment must be payable, which means its `status` is `DUE` or
        `DELINQUENT`; anything else is rejected with `ERR_INSTALLMENT_NOT_PAYABLE`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_when_paying_a_scheduled_installment_with_a_wrong_amount
        """
        scenario = build_issued_assessment(
            api, employer_overrides={"obligation_start_year": 2021, "cba_count": 1}
        )
        first = installment_at(api, scenario["schedule"]["id"], 1)

        response = api.pay_installment(
            first["id"],
            factories.payment_payload(1),
            make_employer_representative_headers(scenario["employer"]["id"]),
        )
        validate_error(response, ApiErrorId.INSTALLMENT_NOT_PAYABLE.value, 409)

        unchanged = get_installment(api, first["id"])
        assert unchanged["status"] == "SCHEDULED"
        assert unchanged["amount_paid_cents"] == 0
        assert (
            get_employer(api, scenario["employer"]["id"])["outstanding_liability_cents"]
            == BASELINE_NET_ASSESSED_CENTS
        )


class TestReferentialBeatsTemporal:
    def test_a_pending_gateway_reports_the_referential_error_not_the_closed_window(self, api):
        """A request for review that was never decided and whose outer bound has also
        passed is refused for its status, not for its timing.

        PRD 3.8: "First, the referenced request's own `status` must be `DECIDED` or
        `DEEMED_DENIED`; a `PENDING` or `WITHDRAWN` request is not a gateway to
        arbitration and is rejected with `ERR_REVIEW_REQUEST_NOT_DECIDED`."

        Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_when_arbitrating_a_pending_review_after_the_outer_window
        """
        scenario = _pending_review_past_the_outer_bound(api)

        response = api.create_arbitration(
            factories.arbitration_payload(
                scenario["assessment"]["id"], scenario["review_request"]["id"]
            ),
            make_employer_representative_headers(scenario["employer"]["id"]),
        )
        validate_error(response, ApiErrorId.REVIEW_REQUEST_NOT_DECIDED.value, 422)

    def test_a_pending_request_carries_the_outer_bound_and_no_arbitration_is_created(self, api):
        """While the request is still PENDING there is no inner bound, so the arbitration
        deadline is filing plus one hundred and eighty days, and the refused initiation
        leaves the dispute exactly where it was.

        PRD 3.8: "An outer bound is always `filed_at` advanced by one hundred and eighty
        days. `arbitration_deadline_at` is the outer bound where there is no inner bound,
        and otherwise the earlier of the inner and outer bounds."

        Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_when_arbitrating_a_pending_review_after_the_outer_window
        """
        scenario = _pending_review_past_the_outer_bound(api)
        request = get_review_request(api, scenario["review_request"]["id"])
        assert request["plan_response_deadline_at"].startswith("2026-12-30T00:00:00")
        assert request["arbitration_deadline_at"].startswith("2027-02-28T00:00:00")

        response = api.create_arbitration(
            factories.arbitration_payload(
                scenario["assessment"]["id"], scenario["review_request"]["id"]
            ),
            make_employer_representative_headers(scenario["employer"]["id"]),
        )
        validate_error(response, ApiErrorId.REVIEW_REQUEST_NOT_DECIDED.value, 422)

        assert get_review_request(api, scenario["review_request"]["id"])["status"] == "PENDING"
        assert get_assessment(api, scenario["assessment"]["id"])["review_status"] == "REQUESTED"
        _data, meta = validate_paginated(
            api.list_arbitrations(
                FUND_ADMINISTRATOR_HEADERS,
                {"liability_assessment_id": scenario["assessment"]["id"]},
            )
        )
        assert meta["total_count"] == 0


class TestSafetyBeatsRemainingConstraint:
    def test_an_underbonded_unassumed_sale_reports_the_bond_error(self, api):
        """A sale that posts nothing against a required bond of 30000000 cents and also
        assumes no obligation is rejected on the bond, which is screened first.

        PRD 2.9: "On an asset-sale exemption certification, the bond-sufficiency test sits
        at tier 9 while the obligation-assumption test sits at tier 12, so a submission
        that both under-bonds *and* fails to assume the contribution obligation is
        rejected with `ERR_4204_BOND_INSUFFICIENT`, not with
        `ERR_4204_OBLIGATION_NOT_ASSUMED`."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_when_certifying_an_underbonded_unassumed_sale
        """
        scenario = _underbonded_sale(api)
        assert scenario["transaction"]["required_bond_cents"] == 30_000_000

        response = api.adjudicate_asset_sale_transaction(
            scenario["transaction"]["id"],
            factories.adjudication_payload(
                AdjudicationDisposition.CERTIFY_4204_EXEMPTION.value
            ),
            PLAN_TRUSTEE_HEADERS,
        )
        validate_error(response, ApiErrorId.BOND_INSUFFICIENT_4204.value, 422)

    def test_the_refused_certification_opens_no_bond_period(self, api):
        """The transaction stays submitted and pending, and the buying group is neither
        bonded nor exposed.

        PRD 3.9: "On success `exemption_status` becomes `EXEMPT_4204`,
        `bond_period_end_plan_year` is set to the closing plan year advanced by five plan
        years, `adjudicated_at` is stamped with the logical clock, the buying controlled
        group's `bond_posture` becomes `BONDED`, its `contingent_exposure_cents` rises by
        `required_bond_cents`, and its `exposure_score` is recomputed under the
        seller-continuing weighting."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_when_certifying_an_underbonded_unassumed_sale
        """
        scenario = _underbonded_sale(api)

        response = api.adjudicate_asset_sale_transaction(
            scenario["transaction"]["id"],
            factories.adjudication_payload(
                AdjudicationDisposition.CERTIFY_4204_EXEMPTION.value
            ),
            PLAN_TRUSTEE_HEADERS,
        )
        validate_error(response, ApiErrorId.BOND_INSUFFICIENT_4204.value, 422)

        transaction = get_transaction(api, scenario["transaction"]["id"])
        assert transaction["status"] == "SUBMITTED"
        assert transaction["exemption_status"] == "PENDING"
        assert transaction["adjudicated_at"] is None

        buyer = get_group(api, scenario["buyer_group"]["id"])
        assert buyer["bond_posture"] == "UNBONDED"
        assert buyer["contingent_exposure_cents"] == 0
