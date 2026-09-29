"""Error triggerability: the twelve distinct path not-found codes, and the body
foreign-key tier answering ahead of ownership, the version guards and every state check."""

from prd_bench_local_runner.testing import validate_error

from test_helpers import factories
from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import (
    build_issued_assessment,
    list_all_installments,
    register_plan,
)
from test_helpers.test_users import (
    FUND_ADMINISTRATOR_HEADERS,
    PLAN_ACTUARY_HEADERS,
    make_employer_representative_headers,
)
from test_helpers.types import PaymentScheduleSource, ReportedCause

BASELINE_EMPLOYER = {"obligation_start_year": 2021, "cba_count": 1}

# Syntactically valid identifiers that name nothing, so the answer is genuine absence
# rather than a malformed path segment.
ABSENT_PLAN = "00000000-0000-0000-0000-0000000000a1"
ABSENT_GROUP = "00000000-0000-0000-0000-0000000000a2"
ABSENT_EMPLOYER = "00000000-0000-0000-0000-0000000000a3"
ABSENT_VALUATION = "00000000-0000-0000-0000-0000000000a4"
ABSENT_RECORD = "00000000-0000-0000-0000-0000000000a5"
ABSENT_EVENT = "00000000-0000-0000-0000-0000000000a6"
ABSENT_ASSESSMENT = "00000000-0000-0000-0000-0000000000a7"
ABSENT_SCHEDULE = "00000000-0000-0000-0000-0000000000a8"
ABSENT_INSTALLMENT = "00000000-0000-0000-0000-0000000000a9"
ABSENT_REVIEW_REQUEST = "00000000-0000-0000-0000-0000000000b1"
ABSENT_ARBITRATION = "00000000-0000-0000-0000-0000000000b2"
ABSENT_TRANSACTION = "00000000-0000-0000-0000-0000000000b3"

ABSENT_BODY_PLAN = "00000000-0000-0000-0000-0000000000c1"
ABSENT_BODY_EMPLOYER = "00000000-0000-0000-0000-0000000000c2"
ABSENT_BODY_EMPLOYER_TWO = "00000000-0000-0000-0000-0000000000c3"
ABSENT_BODY_EVENT = "00000000-0000-0000-0000-0000000000c4"
ABSENT_BODY_ASSESSMENT = "00000000-0000-0000-0000-0000000000c5"
ABSENT_BODY_ASSESSMENT_TWO = "00000000-0000-0000-0000-0000000000c6"
ABSENT_BODY_REVIEW_REQUEST = "00000000-0000-0000-0000-0000000000c7"
ABSENT_BODY_PLAN_TWO = "00000000-0000-0000-0000-0000000000c8"
ABSENT_BODY_GROUP = "00000000-0000-0000-0000-0000000000c9"
ABSENT_BODY_GROUP_TWO = "00000000-0000-0000-0000-0000000000d1"
ABSENT_BODY_PLAN_THREE = "00000000-0000-0000-0000-0000000000d2"
ABSENT_BODY_SELLER = "00000000-0000-0000-0000-0000000000d3"


class TestThePathNotFoundCodes:
    def test_each_of_the_twelve_resource_kinds_owns_its_own_not_found_code(self, api):
        """A live plan keeps the database non-empty, and each of the twelve reads still
        answers with the code belonging to its own resource kind rather than a shared one.

        PRD 2.4: "Each identifier has its own not-found code: `plan_id` yields
        `ERR_PLAN_NOT_FOUND`, `controlled_group_id` yields `ERR_CONTROLLED_GROUP_NOT_FOUND`,
        `employer_id` yields `ERR_EMPLOYER_NOT_FOUND`, `plan_year_valuation_id` yields
        `ERR_VALUATION_NOT_FOUND`, `contribution_record_id` yields
        `ERR_CONTRIBUTION_RECORD_NOT_FOUND`, `withdrawal_event_id` yields
        `ERR_WITHDRAWAL_EVENT_NOT_FOUND`, `liability_assessment_id` yields
        `ERR_ASSESSMENT_NOT_FOUND`, `payment_schedule_id` yields `ERR_SCHEDULE_NOT_FOUND`,
        `installment_id` yields `ERR_INSTALLMENT_NOT_FOUND`, `review_request_id` yields
        `ERR_REVIEW_REQUEST_NOT_FOUND`, `arbitration_id` yields `ERR_ARBITRATION_NOT_FOUND`,
        and `asset_sale_transaction_id` yields `ERR_TRANSACTION_NOT_FOUND`."

        Design: Corner/errors/every_path_id_not_found_error_is_triggerable
        """
        register_plan(api)

        reads = (
            (api.get_plan, ABSENT_PLAN, ApiErrorId.PLAN_NOT_FOUND),
            (api.get_controlled_group, ABSENT_GROUP, ApiErrorId.CONTROLLED_GROUP_NOT_FOUND),
            (api.get_employer, ABSENT_EMPLOYER, ApiErrorId.EMPLOYER_NOT_FOUND),
            (api.get_plan_year_valuation, ABSENT_VALUATION, ApiErrorId.VALUATION_NOT_FOUND),
            (
                api.get_contribution_record,
                ABSENT_RECORD,
                ApiErrorId.CONTRIBUTION_RECORD_NOT_FOUND,
            ),
            (api.get_withdrawal_event, ABSENT_EVENT, ApiErrorId.WITHDRAWAL_EVENT_NOT_FOUND),
            (
                api.get_liability_assessment,
                ABSENT_ASSESSMENT,
                ApiErrorId.ASSESSMENT_NOT_FOUND,
            ),
            (api.get_payment_schedule, ABSENT_SCHEDULE, ApiErrorId.SCHEDULE_NOT_FOUND),
            (api.get_installment, ABSENT_INSTALLMENT, ApiErrorId.INSTALLMENT_NOT_FOUND),
            (
                api.get_review_request,
                ABSENT_REVIEW_REQUEST,
                ApiErrorId.REVIEW_REQUEST_NOT_FOUND,
            ),
            (api.get_arbitration, ABSENT_ARBITRATION, ApiErrorId.ARBITRATION_NOT_FOUND),
            (
                api.get_asset_sale_transaction,
                ABSENT_TRANSACTION,
                ApiErrorId.TRANSACTION_NOT_FOUND,
            ),
        )

        seen = []
        for read, absent_id, expected in reads:
            response = read(absent_id, FUND_ADMINISTRATOR_HEADERS)
            error = validate_error(response, expected.value, 404)
            seen.append(error["error_id"])
            assert error["message"].strip() != ""
            # PRD 2.2: the error envelope carries only the two meta keys.
            assert response.json()["meta"]["api_request_id"] is not None

        assert seen == [expected.value for _read, _id, expected in reads]
        assert len(set(seen)) == 12


class TestTheBodyForeignKeyTier:
    def test_an_unresolved_body_key_answers_before_ownership_the_token_and_the_state(
        self, api
    ):
        """Every probe carries an otherwise perfectly good payload, so the only thing wrong
        is a parent that does not exist, and the answer is always the parent's own 404.

        PRD 2.9: "**Body foreign-key existence.** Every foreign key carried in the request
        body resolves, checked in the order the fields are declared for that endpoint,
        yielding the matching 404 code."

        Design: Corner/errors/body_foreign_keys_are_resolved_before_state_and_return_not_found
        """
        scenario = build_issued_assessment(api, employer_overrides=BASELINE_EMPLOYER)
        employer_id = scenario["employer"]["id"]
        employer_headers = make_employer_representative_headers(employer_id)
        assessment = scenario["assessment"]

        validate_error(
            api.create_plan_year_valuation(
                factories.valuation_payload(ABSENT_BODY_PLAN, 2026, certify_on_create=False),
                PLAN_ACTUARY_HEADERS,
            ),
            ApiErrorId.PLAN_NOT_FOUND.value,
            404,
        )

        # PRD 2.9: the body key resolves at tier 5, ahead of the tier-7 version guard, so
        # there is no row whose version could be compared.
        validate_error(
            api.create_contribution_record(
                factories.contribution_record_payload(
                    ABSENT_BODY_EMPLOYER,
                    2026,
                    2026,
                    scenario["employer"]["version"],
                    contribution_base_units=1_000,
                    contribution_amount_cents=1_000_000,
                ),
                FUND_ADMINISTRATOR_HEADERS,
            ),
            ApiErrorId.EMPLOYER_NOT_FOUND.value,
            404,
        )

        validate_error(
            api.create_withdrawal_event(
                factories.withdrawal_event_payload(
                    ABSENT_BODY_EMPLOYER_TWO,
                    reported_cause=ReportedCause.COVERED_WORK_CEASED.value,
                ),
                FUND_ADMINISTRATOR_HEADERS,
            ),
            ApiErrorId.EMPLOYER_NOT_FOUND.value,
            404,
        )

        # PRD 2.9: tier 5 precedes the tier-8 state preconditions, so this is not
        # ERR_WITHDRAWAL_NOT_DETERMINED.
        validate_error(
            api.create_liability_assessment(
                factories.liability_assessment_payload(ABSENT_BODY_EVENT),
                PLAN_ACTUARY_HEADERS,
            ),
            ApiErrorId.WITHDRAWAL_EVENT_NOT_FOUND.value,
            404,
        )

        validate_error(
            api.create_payment_schedule(
                factories.payment_schedule_payload(
                    ABSENT_BODY_ASSESSMENT,
                    assessment["version"],
                    source=PaymentScheduleSource.ACTUARIAL_CORRECTION.value,
                    override_net_assessed_cents=1_000_000,
                ),
                PLAN_ACTUARY_HEADERS,
            ),
            ApiErrorId.ASSESSMENT_NOT_FOUND.value,
            404,
        )

        validate_error(
            api.create_review_request(
                factories.review_request_payload(ABSENT_BODY_ASSESSMENT_TWO),
                employer_headers,
            ),
            ApiErrorId.ASSESSMENT_NOT_FOUND.value,
            404,
        )

        # PRD 2.9: the pairing cross-check sits at tier 12, so the absent request answers
        # first with its own 404.
        validate_error(
            api.create_arbitration(
                factories.arbitration_payload(
                    assessment["id"], ABSENT_BODY_REVIEW_REQUEST
                ),
                employer_headers,
            ),
            ApiErrorId.REVIEW_REQUEST_NOT_FOUND.value,
            404,
        )

        # PRD 3.1: the payload names the plan before the controlled group, and resolution
        # follows that declared order.
        validate_error(
            api.create_employer(
                factories.employer_payload(ABSENT_BODY_PLAN_TWO, ABSENT_BODY_GROUP),
                FUND_ADMINISTRATOR_HEADERS,
            ),
            ApiErrorId.PLAN_NOT_FOUND.value,
            404,
        )
        validate_error(
            api.create_employer(
                factories.employer_payload(scenario["plan"]["id"], ABSENT_BODY_GROUP_TWO),
                FUND_ADMINISTRATOR_HEADERS,
            ),
            ApiErrorId.CONTROLLED_GROUP_NOT_FOUND.value,
            404,
        )

        validate_error(
            api.run_collection_sweep(
                factories.collection_sweep_payload(ABSENT_BODY_PLAN_THREE),
                FUND_ADMINISTRATOR_HEADERS,
            ),
            ApiErrorId.PLAN_NOT_FOUND.value,
            404,
        )

        validate_error(
            api.create_asset_sale_transaction(
                factories.asset_sale_payload(
                    ABSENT_BODY_SELLER,
                    scenario["group"]["id"],
                    closing_date="2026-05-01T00:00:00Z",
                    closing_plan_year=2026,
                    purchase_price_cents=300_000_000,
                    bond_amount_cents=30_000_000,
                    buyer_assumes_contribution_obligation=True,
                    workforce_continuity_pct=0.8,
                    asset_continuity_pct=0.6,
                    customer_continuity_pct=0.6,
                ),
                FUND_ADMINISTRATOR_HEADERS,
            ),
            ApiErrorId.EMPLOYER_NOT_FOUND.value,
            404,
        )

        # PRD 2.9: a rejected sweep runs nothing at all, so no instalment aged.
        statuses = {
            row["status"] for row in list_all_installments(api, scenario["schedule"]["id"])
        }
        assert statuses == {"SCHEDULED"}
