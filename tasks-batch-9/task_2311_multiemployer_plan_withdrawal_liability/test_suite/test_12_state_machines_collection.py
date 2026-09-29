"""State machines after the demand: what an ACTIVE generation refuses, what a
rescinded demand refuses, the arbitration cycle and its round limit, the
satisfaction bubble-up, the sweep's deemed denial and a rejected asset sale."""

import pytest
from prd_bench_local_runner.testing import validate_error

from test_helpers import factories
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import (
    BASELINE_NET_ASSESSED_CENTS,
    BASELINE_QUARTERLY_INSTALLMENT_CENTS,
)
from test_helpers.fixtures import (
    adjudicate_asset_sale,
    advance_arbitration,
    build_arbitration,
    build_asset_sale,
    build_issued_assessment,
    file_review_request,
    get_arbitration,
    get_assessment,
    get_employer,
    get_group,
    get_review_request,
    get_schedule,
    get_transaction,
    installment_at,
    issue_award,
    latest_schedule,
    list_all_installments,
    list_all_schedules,
    pay_installment,
    run_sweep,
    set_clock,
)
from test_helpers.test_users import (
    ARBITRATOR_HEADERS,
    PLAN_ACTUARY_HEADERS,
    PLAN_TRUSTEE_HEADERS,
    make_employer_representative_headers,
)
from test_helpers.types import (
    AdjudicationDisposition,
    ArbitrationStatus,
    AssumptionRuling,
    AwardOutcome,
    PaymentScheduleSource,
)

BASELINE_EMPLOYER = {"obligation_start_year": 2021, "cba_count": 1}

# A six-year record whose per-year contribution dollars put the gross share exactly
# on the de minimis phase-out start, leaving a five-million-cent demand.
SMALL_ASSESSMENT_HISTORY = (
    {
        "plan_year_start": 2020,
        "plan_year_end": 2025,
        "contribution_base_units": 600_000,
        "contribution_amount_cents": 12_000_004,
        "contribution_rate_cents_per_cbu": 1_000,
    },
)
SMALL_NET_ASSESSED_CENTS = 5_000_000
SMALL_INSTALLMENT_CENTS = 1_250_000

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
REJECTED_SALE = {
    "closing_date": "2026-05-01T00:00:00Z",
    "closing_plan_year": 2026,
    "purchase_price_cents": 300_000_000,
    "bond_amount_cents": 30_000_000,
    "buyer_assumes_contribution_obligation": True,
    "workforce_continuity_pct": 0.8,
    "asset_continuity_pct": 0.6,
    "customer_continuity_pct": 0.6,
}
# The greater of the 25000000-cent three-year average and the 30000000 cents of the
# single preceding plan year, under the purchase-price cap.
REQUIRED_BOND_CENTS = 30_000_000


class TestAnActiveGenerationRefusesTheCollectionEndgame:
    def test_notice_acceleration_and_cure_each_name_the_state_they_needed(self, api):
        """A freshly minted generation is nowhere near default, and the three collection acts
        come back with three different codes; the well-formed cure payment is never even
        compared.

        PRD 3.7: "**Default notice** is the trustee's act on a generation whose `status` is
        `DEFAULT_ELIGIBLE`; any other status is rejected with
        `ERR_SCHEDULE_NOT_DEFAULT_ELIGIBLE`." "The generation's `status` must be
        `DEFAULT_ELIGIBLE` or `NOTICED`; anything else is rejected with
        `ERR_SCHEDULE_NOT_ACTIVE`." "The generation's `status` must be `NOTICED`; anything
        else is rejected with `ERR_SCHEDULE_NOT_NOTICED`."

        Design: Corner/state_machines/an_active_schedule_rejects_a_default_notice_an_acceleration_and_a_cure
        """
        scenario = build_issued_assessment(api, employer_overrides=BASELINE_EMPLOYER)
        schedule_id = scenario["schedule"]["id"]

        validate_error(
            api.issue_default_notice(schedule_id, PLAN_TRUSTEE_HEADERS),
            ApiErrorId.SCHEDULE_NOT_DEFAULT_ELIGIBLE.value,
            409,
        )
        validate_error(
            api.accelerate_payment_schedule(schedule_id, PLAN_TRUSTEE_HEADERS),
            ApiErrorId.SCHEDULE_NOT_NOTICED.value,
            409,
        )
        validate_error(
            api.cure_payment_schedule(
                schedule_id,
                factories.payment_payload(BASELINE_QUARTERLY_INSTALLMENT_CENTS),
                make_employer_representative_headers(scenario["employer"]["id"]),
            ),
            ApiErrorId.SCHEDULE_NOT_ACTIVE.value,
            409,
        )

        untouched = get_schedule(api, schedule_id)
        assert untouched["status"] == "ACTIVE"
        assert untouched["consecutive_delinquent_count"] == 0
        assert untouched["default_notice_issued_at"] is None
        assert untouched["cure_deadline_at"] is None
        assert untouched["accelerated_balance_cents"] == 0
        assert get_assessment(api, scenario["assessment"]["id"])["collection_status"] == (
            "NOT_YET_DUE"
        )


class TestARescindedDemandIsDeadForever:
    def test_a_vacated_assessment_refuses_a_further_generation_on_its_lifecycle(self, api):
        """The lifecycle guard answers before the conceded-amount check, so a source with no
        reduction behind it still reports the rescission.

        PRD 3.8: "An assessment still in `DRAFT`, or already `FINAL`, is rejected with
        `ERR_ASSESSMENT_NOT_ISSUED`; one that has been `RESCINDED` is rejected with
        `ERR_ASSESSMENT_RESCINDED`. That same pair of codes guards four operations in total:
        filing a request for review, minting a schedule generation, deciding a request for
        review, and initiating an arbitration."

        Design: Corner/state_machines/a_rescinded_assessment_rejects_a_new_payment_schedule_generation
        """
        scenario = build_arbitration(
            api,
            advance_to_hearing=True,
            assumption_ruling=AssumptionRuling.REJECTED.value,
            employer_overrides=BASELINE_EMPLOYER,
        )
        issue_award(
            api,
            scenario["arbitration"]["id"],
            AwardOutcome.VACATE.value,
            assumption_ruling=AssumptionRuling.SUSTAINED.value,
        )

        rescinded = get_assessment(api, scenario["assessment"]["id"])
        assert rescinded["lifecycle_status"] == "RESCINDED"
        assert rescinded["review_status"] == "ARBITRATED"
        assert rescinded["collection_status"] == "NOT_YET_DUE"

        response = api.create_payment_schedule(
            factories.payment_schedule_payload(
                scenario["assessment"]["id"],
                rescinded["version"],
                source=PaymentScheduleSource.ARBITRATION_AWARD.value,
            ),
            PLAN_ACTUARY_HEADERS,
        )
        validate_error(response, ApiErrorId.ASSESSMENT_RESCINDED.value, 409)

        schedules = list_all_schedules(api, scenario["assessment"]["id"])
        assert len(schedules) == 1
        assert schedules[0]["generation_seq"] == 1
        assert schedules[0]["status"] == "VOID"


class TestTheArbitrationCycle:
    def test_an_award_from_briefing_is_early_and_a_closed_proceeding_is_locked(self, api):
        """Only a hearing can produce an award, only a hearing follows a briefing, and once
        closed both verbs answer with the closure code rather than the state-specific ones.

        PRD 3.8: "An advance to a status not reachable from the current one is rejected with
        `ERR_INVALID_ARBITRATION_ADVANCE`, and any advance or award attempted on a `CLOSED`
        arbitration is rejected with `ERR_ARBITRATION_ALREADY_CLOSED`."

        Design: Corner/state_machines/the_arbitration_cycle_rejects_an_early_award_and_locks_after_closing
        """
        scenario = build_arbitration(
            api,
            assumption_ruling=AssumptionRuling.REJECTED.value,
            employer_overrides=BASELINE_EMPLOYER,
        )
        arbitration_id = scenario["arbitration"]["id"]
        assert scenario["arbitration"]["status"] == "BRIEFING"

        early = api.award_arbitration(
            arbitration_id,
            factories.arbitration_award_payload(
                AwardOutcome.AFFIRM.value, AssumptionRuling.REJECTED.value
            ),
            ARBITRATOR_HEADERS,
        )
        validate_error(early, ApiErrorId.ARBITRATION_NOT_IN_AWARDABLE_STATE.value, 409)

        sideways = api.advance_arbitration(
            arbitration_id,
            factories.arbitration_advance_payload(ArbitrationStatus.BRIEFING.value),
            ARBITRATOR_HEADERS,
        )
        validate_error(sideways, ApiErrorId.INVALID_ARBITRATION_ADVANCE.value, 409)

        heard = advance_arbitration(api, arbitration_id, ArbitrationStatus.HEARING.value)
        assert heard["status"] == "HEARING"
        assert heard["round_number"] == 1

        closed = issue_award(
            api,
            arbitration_id,
            AwardOutcome.AFFIRM.value,
            assumption_ruling=AssumptionRuling.REJECTED.value,
        )
        assert closed["status"] == "CLOSED"
        assert closed["award_outcome"] == "AFFIRM"
        assert closed["closed_at"].startswith("2026-10-15T00:00:00")

        affirmed = get_assessment(api, scenario["assessment"]["id"])
        assert affirmed["review_status"] == "ARBITRATED"
        assert affirmed["net_assessed_cents"] == BASELINE_NET_ASSESSED_CENTS
        assert affirmed["award_adjustment_cents"] == 0

        validate_error(
            api.advance_arbitration(
                arbitration_id,
                factories.arbitration_advance_payload(ArbitrationStatus.HEARING.value),
                ARBITRATOR_HEADERS,
            ),
            ApiErrorId.ARBITRATION_ALREADY_CLOSED.value,
            409,
        )
        validate_error(
            api.award_arbitration(
                arbitration_id,
                factories.arbitration_award_payload(
                    AwardOutcome.AFFIRM.value, AssumptionRuling.REJECTED.value
                ),
                ARBITRATOR_HEADERS,
            ),
            ApiErrorId.ARBITRATION_ALREADY_CLOSED.value,
            409,
        )

    def test_the_third_round_may_be_heard_but_not_remanded_again(self, api):
        """Two remands carry the proceeding to round three, where a third remand is barred
        while a terminating award still lands.

        PRD 3.8: "Remands are bounded at three rounds: `round_number` must be strictly below
        three before a remand award, and at most three before advancing back to `BRIEFING`; a
        violation of either bound is rejected with `ERR_ARBITRATION_ROUND_LIMIT`."

        Design: Corner/state_machines/a_remand_at_the_third_round_is_rejected_by_the_round_limit
        """
        scenario = build_arbitration(
            api,
            advance_to_hearing=True,
            assumption_ruling=AssumptionRuling.REJECTED.value,
            employer_overrides=BASELINE_EMPLOYER,
        )
        arbitration_id = scenario["arbitration"]["id"]

        issue_award(api, arbitration_id, AwardOutcome.REMAND.value)
        after_first = advance_arbitration(
            api, arbitration_id, ArbitrationStatus.BRIEFING.value
        )
        assert after_first["round_number"] == 2
        advance_arbitration(api, arbitration_id, ArbitrationStatus.HEARING.value)

        issue_award(api, arbitration_id, AwardOutcome.REMAND.value)
        after_second = advance_arbitration(
            api, arbitration_id, ArbitrationStatus.BRIEFING.value
        )
        assert after_second["round_number"] == 3
        advance_arbitration(api, arbitration_id, ArbitrationStatus.HEARING.value)

        third_remand = api.award_arbitration(
            arbitration_id,
            factories.arbitration_award_payload(
                AwardOutcome.REMAND.value, AssumptionRuling.NOT_RAISED.value
            ),
            ARBITRATOR_HEADERS,
        )
        validate_error(third_remand, ApiErrorId.ARBITRATION_ROUND_LIMIT.value, 409)

        held = get_arbitration(api, arbitration_id)
        assert held["status"] == "HEARING"
        assert held["round_number"] == 3
        assert held["award_outcome"] == "REMAND"
        assert held["closed_at"] is None

        closed = issue_award(
            api,
            arbitration_id,
            AwardOutcome.AFFIRM.value,
            assumption_ruling=AssumptionRuling.REJECTED.value,
        )
        assert closed["status"] == "CLOSED"


class TestSatisfactionBubblesUpThreeLevels:
    def test_the_last_payment_settles_the_schedule_the_demand_and_the_employer(self, api):
        """Four quarterly cheques of 1250000 cents clear a five-million-cent demand, and only
        the fourth moves the generation, the assessment and the employer to their terminal
        states.

        PRD 3.7: "Where the payment settles the last unpaid instalment — so that every
        instalment on the generation is now `PAID` or `VOID` — the assessment moves
        `CURRENT → SATISFIED`, the generation moves `ACTIVE → SATISFIED`, the employer's
        `outstanding_liability_cents` becomes 0, the employer moves `COMPLETE_WITHDRAWN →
        LIABILITY_SATISFIED` (or `PARTIAL_WITHDRAWN → LIABILITY_SATISFIED`), and the
        controlled group's `joint_exposure_cents` is recomputed to drop that employer's
        contribution."

        Design: Corner/state_machines/paying_every_installment_bubbles_the_schedule_assessment_and_employer_to_terminal
        """
        scenario = build_issued_assessment(
            api,
            employer_overrides=BASELINE_EMPLOYER,
            contribution_entries=SMALL_ASSESSMENT_HISTORY,
        )
        assert scenario["assessment"]["net_assessed_cents"] == SMALL_NET_ASSESSED_CENTS
        schedule_id = scenario["schedule"]["id"]
        assert scenario["schedule"]["quarterly_installment_cents"] == SMALL_INSTALLMENT_CENTS
        assert scenario["schedule"]["final_installment_cents"] == SMALL_INSTALLMENT_CENTS

        installments = list_all_installments(api, schedule_id)
        assert len(installments) == 4
        expected_due_dates = (
            "2026-09-30T00:00:00",
            "2026-12-30T00:00:00",
            "2027-03-30T00:00:00",
            "2027-06-30T00:00:00",
        )
        for installment, due_date in zip(installments, expected_due_dates):
            assert installment["due_date"].startswith(due_date)
            assert installment["principal_cents"] == SMALL_INSTALLMENT_CENTS
            assert installment["amount_due_cents"] == SMALL_INSTALLMENT_CENTS

        remaining = (3_750_000, 2_500_000, 1_250_000, 0)
        for sequence_number, clock, balance in zip(
            (1, 2, 3, 4),
            (
                "2026-09-30T00:00:00Z",
                "2026-12-30T00:00:00Z",
                "2027-03-30T00:00:00Z",
                "2027-06-30T00:00:00Z",
            ),
            remaining,
        ):
            set_clock(api, clock)
            run_sweep(api, scenario["plan"]["id"])
            paid = pay_installment(
                api,
                installment_at(api, schedule_id, sequence_number),
                scenario["employer"]["id"],
            )
            assert paid["status"] == "PAID"
            assert (
                get_employer(api, scenario["employer"]["id"])["outstanding_liability_cents"]
                == balance
            )
            if sequence_number == 1:
                assert get_assessment(api, scenario["assessment"]["id"])[
                    "collection_status"
                ] == "CURRENT"

        assert get_schedule(api, schedule_id)["status"] == "SATISFIED"
        settled = get_assessment(api, scenario["assessment"]["id"])
        assert settled["collection_status"] == "SATISFIED"
        assert settled["lifecycle_status"] == "FINAL"

        employer = get_employer(api, scenario["employer"]["id"])
        assert employer["status"] == "LIABILITY_SATISFIED"
        assert employer["credit_watch"] is False
        assert employer["delinquency_strikes"] == 0

        group = get_group(api, scenario["group"]["id"])
        assert group["joint_exposure_cents"] == 0
        assert group["exposure_score"] == pytest.approx(0.0, abs=0.0001)


class TestTheSweepDeemsPlanSilenceADenial:
    def test_one_pass_ages_the_installments_and_converts_silence_into_a_decision(self, api):
        """The same sweep marks two instalments due, one delinquent, and turns the
        unanswered request into a deemed denial without finalising the demand.

        PRD 3.8: "A request still `PENDING` whose `plan_response_deadline_at` has been
        reached by the logical clock moves `PENDING → DEEMED_DENIED`, its
        `arbitration_deadline_at` is recomputed as the earlier of
        `plan_response_deadline_at` advanced by sixty days and `filed_at` advanced by one
        hundred and eighty days, and the assessment moves `REQUESTED → DECIDED` on the
        review dimension"

        Design: Corner/state_machines/a_pending_review_request_is_deemed_denied_by_the_sweep
        """
        scenario = build_issued_assessment(api, employer_overrides=BASELINE_EMPLOYER)
        set_clock(api, "2026-09-01T00:00:00Z")
        filed = file_review_request(
            api, scenario["assessment"]["id"], scenario["employer"]["id"]
        )
        assert filed["filed_at"].startswith("2026-09-01T00:00:00")
        assert filed["plan_response_deadline_at"].startswith("2026-12-30T00:00:00")
        # A PENDING request has no trigger instant, so the outer bound stands alone.
        assert filed["arbitration_deadline_at"].startswith("2027-02-28T00:00:00")
        assert filed["status"] == "PENDING"

        awaiting = get_assessment(api, scenario["assessment"]["id"])
        assert awaiting["review_status"] == "REQUESTED"
        assert awaiting["collection_status"] == "NOT_YET_DUE"

        set_clock(api, "2026-12-30T00:00:00Z")
        sweep = run_sweep(api, scenario["plan"]["id"])
        assert sweep["installments_marked_due"] == 2
        assert sweep["installments_marked_delinquent"] == 1
        assert sweep["schedules_default_eligible"] == 0
        assert sweep["review_requests_deemed_denied"] == 1
        assert sweep["assessments_finalized"] == 0

        denied = get_review_request(api, filed["id"])
        assert denied["status"] == "DEEMED_DENIED"
        assert denied["decision"] == "NONE"
        assert denied["decided_at"] is None
        assert denied["decided_by_user_id"] is None
        assert denied["arbitration_deadline_at"].startswith("2027-02-28T00:00:00")

        assessment = get_assessment(api, scenario["assessment"]["id"])
        assert assessment["review_status"] == "DECIDED"
        assert assessment["lifecycle_status"] == "ISSUED"
        assert assessment["collection_status"] == "DELINQUENT"

        schedule = latest_schedule(api, scenario["assessment"]["id"])
        assert schedule["status"] == "ACTIVE"
        assert schedule["consecutive_delinquent_count"] == 1

        employer = get_employer(api, scenario["employer"]["id"])
        assert employer["credit_watch"] is True
        assert employer["delinquency_strikes"] == 1


class TestRejectingASaleMovesNoMoney:
    def test_a_rejected_sale_sets_both_dispositions_and_leaves_exposure_alone(self, api):
        """Rejection is the purely negative branch: no continuity score is computed, no bond
        period opens, and a second adjudication cannot re-route the sale.

        PRD 3.9: "**Rejecting the submission** — `SUBMITTED → REJECTED` — sets
        `exemption_status` to `NOT_EXEMPT` and `successor_determination` to
        `NO_SUCCESSOR_LIABILITY`, stamps `adjudicated_at`, and changes no exposure figure
        anywhere. All three dispositions are terminal."

        Design: Corner/state_machines/rejecting_an_asset_sale_leaves_every_exposure_figure_untouched
        """
        scenario = build_asset_sale(
            api,
            contribution_entries=SELLER_HISTORY,
            sale_overrides=REJECTED_SALE,
            employer_overrides=BASELINE_EMPLOYER,
        )
        submitted = scenario["transaction"]
        assert submitted["status"] == "SUBMITTED"
        assert submitted["required_bond_cents"] == REQUIRED_BOND_CENTS
        assert submitted["exemption_status"] == "PENDING"
        assert submitted["successor_determination"] == "PENDING"
        assert submitted["substantial_continuity_score"] == pytest.approx(0.0, abs=0.0001)
        assert submitted["bond_period_end_plan_year"] is None
        assert submitted["adjudicated_at"] is None

        rejected = adjudicate_asset_sale(
            api, submitted["id"], AdjudicationDisposition.REJECT.value
        )
        assert rejected["status"] == "REJECTED"
        assert rejected["exemption_status"] == "NOT_EXEMPT"
        assert rejected["successor_determination"] == "NO_SUCCESSOR_LIABILITY"
        assert rejected["adjudicated_at"].startswith("2026-08-01T00:00:00")
        assert rejected["substantial_continuity_score"] == pytest.approx(0.0, abs=0.0001)

        buyer = get_group(api, scenario["buyer_group"]["id"])
        assert buyer["bond_posture"] == "UNBONDED"
        assert buyer["contingent_exposure_cents"] == 0
        assert buyer["joint_exposure_cents"] == 0
        assert buyer["exposure_score"] == pytest.approx(0.0, abs=0.0001)

        assert get_employer(api, scenario["employer"]["id"])["status"] == "CONTRIBUTING"

        again = api.adjudicate_asset_sale_transaction(
            submitted["id"],
            factories.adjudication_payload(AdjudicationDisposition.REJECT.value),
            PLAN_TRUSTEE_HEADERS,
        )
        validate_error(again, ApiErrorId.TRANSACTION_ALREADY_ADJUDICATED.value, 409)

        assert get_transaction(api, submitted["id"])["status"] == "REJECTED"
