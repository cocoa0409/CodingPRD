"""Validations where a single cent or a single second decides the outcome: the
all-or-nothing cure, the exact instalment, the monotonic clock and the purchaser who
assumed nothing."""

import pytest
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import (
    BASELINE_NET_ASSESSED_CENTS,
    BASELINE_QUARTERLY_INSTALLMENT_CENTS,
)
from test_helpers.fixtures import (
    build_asset_sale,
    build_issued_assessment,
    build_noticed_schedule,
    cure_schedule,
    get_assessment,
    get_employer,
    get_group,
    get_schedule,
    get_transaction,
    installment_at,
    pay_installment,
    run_sweep,
    set_clock,
)
from test_helpers.test_users import (
    FUND_ADMINISTRATOR_HEADERS,
    PLAN_TRUSTEE_HEADERS,
    make_employer_representative_headers,
)
from test_helpers.types import AdjudicationDisposition

BASELINE_EMPLOYER = {"obligation_start_year": 2021, "cba_count": 1}

# Two delinquent instalments of 8928571 cents each.
EXACT_CURE_CENTS = 2 * BASELINE_QUARTERLY_INSTALLMENT_CENTS

SELLER_HISTORY = tuple(
    {
        "plan_year_start": year,
        "plan_year_end": year,
        "contribution_base_units": cbu,
        "contribution_amount_cents": cents,
        "contribution_rate_cents_per_cbu": 1_000,
    }
    for year, cbu, cents in (
        (2023, 20_000, 20_000_000),
        (2024, 25_000, 25_000_000),
        (2025, 30_000, 30_000_000),
    )
)

# A purchase price low enough that the required bond is trimmed to it, matched exactly
# by the bond actually posted, but with nothing assumed.
UNASSUMED_SALE = {
    "closing_date": "2026-05-01T00:00:00Z",
    "closing_plan_year": 2026,
    "purchase_price_cents": 20_000_000,
    "bond_amount_cents": 20_000_000,
    "buyer_assumes_contribution_obligation": False,
    "workforce_continuity_pct": 0.8,
    "asset_continuity_pct": 0.6,
    "customer_continuity_pct": 0.6,
}


class TestTheAllOrNothingCure:
    def test_a_cure_one_cent_light_leaves_the_notice_standing(self, api):
        """The aggregate must match the delinquent instalments to the cent: one cent short
        changes nothing, and the exact figure restores the generation.

        PRD 3.7: "The supplied `payment_amount_cents` must equal the sum of
        `amount_due_cents` over exactly the generation's `DELINQUENT` instalments; any other
        figure is rejected with `ERR_CURE_AMOUNT_MISMATCH`."

        Design: Corner/validations/curing_with_the_wrong_aggregate_amount_is_rejected_before_the_exact_amount_restores_the_schedule
        """
        scenario = build_noticed_schedule(api, employer_overrides=BASELINE_EMPLOYER)
        schedule_id = scenario["schedule"]["id"]
        employer_id = scenario["employer"]["id"]

        noticed = scenario["schedule"]
        assert noticed["status"] == "NOTICED"
        assert noticed["consecutive_delinquent_count"] == 2
        assert noticed["default_notice_issued_at"].startswith("2027-02-28T00:00:00")
        assert noticed["cure_deadline_at"].startswith("2027-04-29T00:00:00")
        assert scenario["assessment"]["collection_status"] == "DEFAULTED"

        short = api.cure_payment_schedule(
            schedule_id,
            factories.payment_payload(EXACT_CURE_CENTS - 1),
            make_employer_representative_headers(employer_id),
        )
        validate_error(short, ApiErrorId.CURE_AMOUNT_MISMATCH.value, 422)

        blocked = get_schedule(api, schedule_id)
        assert blocked["status"] == "NOTICED"
        assert blocked["consecutive_delinquent_count"] == 2
        assert blocked["cure_deadline_at"].startswith("2027-04-29T00:00:00")

        cured = cure_schedule(api, schedule_id, employer_id, EXACT_CURE_CENTS)
        assert cured["status"] == "ACTIVE"
        assert cured["consecutive_delinquent_count"] == 0
        assert cured["default_notice_issued_at"] is None
        assert cured["cure_deadline_at"] is None

        for sequence_number in (1, 2):
            settled = installment_at(api, schedule_id, sequence_number)
            assert settled["status"] == "PAID"
            assert settled["amount_paid_cents"] == BASELINE_QUARTERLY_INSTALLMENT_CENTS
            assert settled["amount_due_cents"] == BASELINE_QUARTERLY_INSTALLMENT_CENTS

        assert get_assessment(api, scenario["assessment"]["id"])["collection_status"] == (
            "CURRENT"
        )

        employer = get_employer(api, employer_id)
        assert employer["credit_watch"] is False
        # PRD 3.7: `delinquency_strikes` is never decremented by a cure.
        assert employer["delinquency_strikes"] == 2
        assert employer["outstanding_liability_cents"] == (
            BASELINE_NET_ASSESSED_CENTS - EXACT_CURE_CENTS
        )


class TestTheExactInstalment:
    def test_neither_a_cent_short_nor_two_instalments_at_once_is_accepted(self, api):
        """A remittance must equal the instalment's own amount: both the short payment and
        the overpayment are refused, and only the exact figure settles the cheque.

        PRD 3.7: "Remitting against an instalment requires `payment_amount_cents` to equal
        that instalment's `amount_due_cents` precisely; both a short payment and an
        overpayment are rejected with `ERR_PAYMENT_AMOUNT_MISMATCH`."

        Design: Corner/validations/paying_an_installment_one_cent_short_is_rejected_and_the_exact_amount_is_accepted
        """
        scenario = build_issued_assessment(api, employer_overrides=BASELINE_EMPLOYER)
        employer_id = scenario["employer"]["id"]
        employer_headers = make_employer_representative_headers(employer_id)

        set_clock(api, "2026-09-30T00:00:00Z")
        sweep = run_sweep(api, scenario["plan"]["id"])
        assert sweep["installments_marked_due"] == 1
        assert sweep["installments_marked_delinquent"] == 0

        first = installment_at(api, scenario["schedule"]["id"], 1)
        assert first["status"] == "DUE"
        assert first["amount_due_cents"] == BASELINE_QUARTERLY_INSTALLMENT_CENTS

        short = api.pay_installment(
            first["id"],
            factories.payment_payload(BASELINE_QUARTERLY_INSTALLMENT_CENTS - 1),
            employer_headers,
        )
        validate_error(short, ApiErrorId.PAYMENT_AMOUNT_MISMATCH.value, 422)

        over = api.pay_installment(
            first["id"],
            factories.payment_payload(2 * BASELINE_QUARTERLY_INSTALLMENT_CENTS),
            employer_headers,
        )
        validate_error(over, ApiErrorId.PAYMENT_AMOUNT_MISMATCH.value, 422)

        untouched = installment_at(api, scenario["schedule"]["id"], 1)
        assert untouched["status"] == "DUE"
        assert untouched["amount_paid_cents"] == 0
        assert untouched["paid_at"] is None

        paid = pay_installment(api, first, employer_id)
        assert paid["status"] == "PAID"
        assert paid["amount_paid_cents"] == BASELINE_QUARTERLY_INSTALLMENT_CENTS
        assert paid["paid_at"].startswith("2026-09-30T00:00:00")

        assert get_assessment(api, scenario["assessment"]["id"])["collection_status"] == (
            "CURRENT"
        )

        employer = get_employer(api, employer_id)
        assert employer["outstanding_liability_cents"] == (
            BASELINE_NET_ASSESSED_CENTS - BASELINE_QUARTERLY_INSTALLMENT_CENTS
        )

        group = get_group(api, scenario["group"]["id"])
        assert group["joint_exposure_cents"] == employer["outstanding_liability_cents"]
        assert group["exposure_score"] == pytest.approx(2410.7143, abs=0.0001)


class TestTheMonotonicClock:
    def test_the_clock_moves_only_forwards_and_a_single_second_is_enough(self, api):
        """Standing still and stepping back are both refused; one second forward is accepted
        and the response reports both instants.

        PRD 2.4: "The clock never runs backwards: a `to_iso8601` value at or before the
        current logical clock is rejected with `ERR_CLOCK_MUST_ADVANCE`."

        Design: Corner/validations/setting_the_clock_to_its_current_value_is_rejected_and_one_second_later_is_accepted
        """
        standing_still = api.set_clock(
            factories.clock_payload("2026-08-01T00:00:00Z"), FUND_ADMINISTRATOR_HEADERS
        )
        validate_error(standing_still, ApiErrorId.CLOCK_MUST_ADVANCE.value, 422)

        backwards = api.set_clock(
            factories.clock_payload("2026-07-31T23:59:59Z"), FUND_ADMINISTRATOR_HEADERS
        )
        validate_error(backwards, ApiErrorId.CLOCK_MUST_ADVANCE.value, 422)

        moved = validate_success(
            api.set_clock(
                factories.clock_payload("2026-08-01T00:00:01Z"),
                FUND_ADMINISTRATOR_HEADERS,
            ),
            200,
        )
        assert moved["current_utc"].startswith("2026-08-01T00:00:01")
        assert moved["previous_utc"].startswith("2026-08-01T00:00:00")

        # PRD 2.4: the accepted move is still only one second, so the same instant is now
        # itself the floor.
        again = api.set_clock(
            factories.clock_payload("2026-08-01T00:00:01Z"), FUND_ADMINISTRATOR_HEADERS
        )
        validate_error(again, ApiErrorId.CLOCK_MUST_ADVANCE.value, 422)


class TestThePurchaserWhoAssumedNothing:
    def test_a_fully_bonded_sale_still_fails_on_the_unassumed_obligation(self, api):
        """The bond covers the required amount exactly, so the refusal is about the
        obligation and not the money, and the same submission is still open to a successor
        determination.

        PRD 3.9: "**Certifying the sale-of-assets exemption** — `SUBMITTED →
        EXEMPTION_CERTIFIED` — requires that `bond_amount_cents` be greater than or equal
        to `required_bond_cents`, an insufficient bond being rejected with
        `ERR_4204_BOND_INSUFFICIENT`; that `buyer_assumes_contribution_obligation` be
        true, a purchaser who assumed nothing being rejected with
        `ERR_4204_OBLIGATION_NOT_ASSUMED`; and that the selling employer's `status` still
        be `CONTRIBUTING`."

        Design: Corner/validations/certifying_a_sale_exemption_the_buyer_has_not_assumed_is_rejected
        """
        scenario = build_asset_sale(
            api, contribution_entries=SELLER_HISTORY, sale_overrides=UNASSUMED_SALE
        )
        transaction_id = scenario["transaction"]["id"]

        assert scenario["transaction"]["required_bond_cents"] == 20_000_000
        assert scenario["transaction"]["bond_amount_cents"] == 20_000_000
        assert scenario["transaction"]["buyer_assumes_contribution_obligation"] is False

        refused = api.adjudicate_asset_sale_transaction(
            transaction_id,
            factories.adjudication_payload(
                AdjudicationDisposition.CERTIFY_4204_EXEMPTION.value
            ),
            PLAN_TRUSTEE_HEADERS,
        )
        validate_error(refused, ApiErrorId.OBLIGATION_NOT_ASSUMED_4204.value, 422)

        pending = get_transaction(api, transaction_id)
        assert pending["status"] == "SUBMITTED"
        assert pending["exemption_status"] == "PENDING"
        assert pending["successor_determination"] == "PENDING"
        assert pending["adjudicated_at"] is None
        assert pending["bond_period_end_plan_year"] is None

        buyer = get_group(api, scenario["buyer_group"]["id"])
        assert buyer["bond_posture"] == "UNBONDED"
        assert buyer["contingent_exposure_cents"] == 0

        determined = validate_success(
            api.adjudicate_asset_sale_transaction(
                transaction_id,
                factories.adjudication_payload(
                    AdjudicationDisposition.DETERMINE_SUCCESSOR.value
                ),
                PLAN_TRUSTEE_HEADERS,
            ),
            200,
        )
        assert determined["status"] == "SUCCESSOR_DETERMINED"
        assert determined["exemption_status"] == "NOT_EXEMPT"
        assert determined["successor_determination"] == "SUCCESSOR_LIABLE"
        assert determined["substantial_continuity_score"] == pytest.approx(0.7, abs=0.0001)
        assert determined["bond_period_end_plan_year"] is None
        assert determined["adjudicated_at"].startswith("2026-08-01T00:00:00")

        # PRD 3.9: the seller is still CONTRIBUTING with nothing outstanding, so nothing
        # lands in the buying group's joint exposure.
        assert get_employer(api, scenario["employer"]["id"])["status"] == "CONTRIBUTING"
        settled_buyer = get_group(api, scenario["buyer_group"]["id"])
        assert settled_buyer["joint_exposure_cents"] == 0
        assert settled_buyer["bond_posture"] == "UNBONDED"
        assert settled_buyer["exposure_score"] == pytest.approx(0.0, abs=0.0001)
