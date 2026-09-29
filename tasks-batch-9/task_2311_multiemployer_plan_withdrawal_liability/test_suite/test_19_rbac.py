"""Authority: every role reads everything, the writes are exclusive, a headerless caller
never gets past the first tier, one employer's counsel cannot touch another's money, and
the trustee who issued a demand cannot sit in judgement on it."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import factories
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import BASELINE_QUARTERLY_INSTALLMENT_CENTS
from test_helpers.fixtures import (
    build_issued_assessment,
    build_priced_assessment,
    file_review_request,
    get_assessment,
    get_review_request,
    installment_at,
    register_employer,
    register_plan,
)
from test_helpers.test_users import (
    ARBITRATOR_HEADERS,
    FUND_ADMINISTRATOR_HEADERS,
    NO_ROLE_HEADERS,
    PLAN_ACTUARY_HEADERS,
    PLAN_TRUSTEE_HEADERS,
    PLAN_TRUSTEE_SECONDARY_HEADERS,
    TEST_USERS,
    make_employer_representative_headers,
)
from test_helpers.types import AssumptionRuling, ReviewDecision

BASELINE_EMPLOYER = {"obligation_start_year": 2021, "cba_count": 1}

ISSUING_TRUSTEE_ID = TEST_USERS["plan_trustee"]["user_id"]
DECIDING_TRUSTEE_ID = TEST_USERS["plan_trustee_secondary"]["user_id"]

# An EmployerRepresentative identity that names no Employer row at all.
UNRELATED_REPRESENTATIVE_HEADERS = make_employer_representative_headers("employer-unrelated")

ABSENT_EMPLOYER = "00000000-0000-0000-0000-0000000000e1"


class TestTheOpenReadSurface:
    def test_all_five_roles_read_the_same_plan_payload(self, api):
        """Authority is segregated on writes only, so the neutral arbitrator and an
        employer's counsel read exactly what the fund office reads.

        PRD 2.1: "An `Arbitrator` is the neutral appointed under the mandatory arbitration
        rules: it advances the proceeding and issues awards, and it may neither initiate an
        arbitration nor decide a request for review. Every role may read every collection."

        Design: Corner/rbac/every_role_can_read_the_plan_registry
        """
        plan = register_plan(api)

        readers = (
            FUND_ADMINISTRATOR_HEADERS,
            PLAN_ACTUARY_HEADERS,
            PLAN_TRUSTEE_HEADERS,
            ARBITRATOR_HEADERS,
            # PRD 2.1: the ownership rule guards six writes, so this identity naming no
            # Employer row is still a legitimate reader.
            UNRELATED_REPRESENTATIVE_HEADERS,
        )

        payloads = []
        for headers in readers:
            data = validate_success(api.get_plan(plan["id"], headers), 200)
            payloads.append(data)
            assert data["allocation_method"] == "MODIFIED_PRESUMPTIVE"
            assert data["interest_rate_bps"] == 700
            assert data["employer_count"] == 0
            assert data["mass_withdrawal_declared"] is False

        for later in payloads[1:]:
            assert later == payloads[0]


class TestTheTrusteesExclusiveIssuance:
    def test_neither_the_fund_office_nor_the_employer_nor_the_actuary_may_issue(self, api):
        """The fund office created every row leading up to the demand and the actuary priced
        it, yet the demand is the trustee's act alone.

        PRD 2.9: "**Role authorisation.** The acting role appears in the endpoint's role
        list in §4 — otherwise `ERR_ROLE_NOT_PERMITTED` (403). Applies to every endpoint."

        Design: Corner/rbac/a_fund_administrator_cannot_issue_a_notice_and_demand
        """
        scenario = build_priced_assessment(api, employer_overrides=BASELINE_EMPLOYER)
        assessment_id = scenario["assessment"]["id"]
        employer_headers = make_employer_representative_headers(scenario["employer"]["id"])

        for headers in (FUND_ADMINISTRATOR_HEADERS, employer_headers, PLAN_ACTUARY_HEADERS):
            # PRD 2.9: the actuary certified the anchor valuation, so on role grounds alone
            # this request would earn the tier-9 ERR_SEGREGATION_OF_DUTIES; tier 2 answers
            # first.
            refused = api.issue_liability_assessment(assessment_id, headers)
            validate_error(refused, ApiErrorId.ROLE_NOT_PERMITTED.value, 403)

        assessment = get_assessment(api, assessment_id)
        assert assessment["lifecycle_status"] == "DRAFT"
        assert assessment["issued_at"] is None
        assert assessment["active_schedule_generation"] == 0


class TestTheArbitratorsNarrowReach:
    def test_the_arbitrator_may_neither_price_nor_determine_nor_sweep(self, api):
        """An award can vacate an assessment outright, but the role model is segregation of
        duties rather than hierarchy, so the arbitrator cannot create one.

        PRD 2.1: "A `PlanActuary` is the enrolled actuary: it files and certifies
        plan-year valuations, determines withdrawal type, computes draft assessments, and
        mints payment-schedule generations — but it can never issue a demand."

        Design: Corner/rbac/an_arbitrator_cannot_create_or_price_a_liability_assessment
        """
        scenario = build_priced_assessment(
            api, employer_overrides=BASELINE_EMPLOYER, price=False
        )
        event_id = scenario["event"]["id"]
        assert scenario["event"]["status"] == "COMPLETE_DETERMINED"

        validate_error(
            api.create_liability_assessment(
                factories.liability_assessment_payload(event_id), ARBITRATOR_HEADERS
            ),
            ApiErrorId.ROLE_NOT_PERMITTED.value,
            403,
        )

        # PRD 2.9: tier 2 precedes the tier-8 state precondition, so the already-determined
        # event does not answer with its own conflict.
        validate_error(
            api.determine_withdrawal_event(event_id, ARBITRATOR_HEADERS),
            ApiErrorId.ROLE_NOT_PERMITTED.value,
            403,
        )

        validate_error(
            api.run_collection_sweep(
                factories.collection_sweep_payload(scenario["plan"]["id"]), ARBITRATOR_HEADERS
            ),
            ApiErrorId.ROLE_NOT_PERMITTED.value,
            403,
        )

        _rows, meta = validate_paginated(
            api.list_liability_assessments(
                FUND_ADMINISTRATOR_HEADERS, {"withdrawal_event_id": event_id}
            )
        )
        assert meta["total_count"] == 0


class TestTheUnauthenticatedCaller:
    def test_a_missing_role_header_answers_before_the_body_and_before_every_404(self, api):
        """Authentication sits ahead of the shape check and every not-found, so a headerless
        caller learns neither which rows exist nor which fields its body was missing.

        PRD 2.9: "**Authentication.** `X-User-Role` and `X-User-ID` are both present and
        `X-User-Role` is one of the five declared roles — otherwise `ERR_UNAUTHENTICATED`
        (401). Applies to every endpoint."

        Design: Corner/rbac/a_request_with_no_role_header_is_unauthenticated
        """
        plan = register_plan(api)

        attempts = (
            api.get_plan(plan["id"], NO_ROLE_HEADERS),
            api.create_plan({"name": "Phantom Fund"}, NO_ROLE_HEADERS),
            api.get_employer(ABSENT_EMPLOYER, NO_ROLE_HEADERS),
            api.run_collection_sweep({}, NO_ROLE_HEADERS),
        )

        for response in attempts:
            error = validate_error(response, ApiErrorId.UNAUTHENTICATED.value, 401)
            assert error["message"].strip() != ""
            assert response.json()["meta"]["api_request_id"] is not None

        # PRD 2.9: a rejected sweep runs nothing, and there is nothing to have run against.
        for lister in (api.list_installments, api.list_review_requests):
            _rows, meta = validate_paginated(lister(FUND_ADMINISTRATOR_HEADERS))
            assert meta["total_count"] == 0


class TestTheStrangerEmployer:
    def test_ownership_answers_ahead_of_whether_the_instalment_was_even_payable(self, api):
        """The same role and the same endpoints are legitimate or forbidden purely on the
        acting identity, and the owner's identical payment shows what the stranger was
        spared from learning.

        PRD 2.1: "A mismatch is rejected with `ERR_NOT_RESOURCE_OWNER`. This ownership check
        guards exactly six operations: `POST /withdrawal-events`, `POST /review-requests`,
        `POST /arbitrations`, `POST /installments/{installment_id}/pay`,
        `POST /payment-schedules/{payment_schedule_id}/cure`, and
        `POST /asset-sale-transactions`."

        Design: Corner/rbac/an_employer_representative_cannot_act_on_another_employers_resources
        """
        scenario = build_issued_assessment(api, employer_overrides=BASELINE_EMPLOYER)
        assessment_id = scenario["assessment"]["id"]
        schedule_id = scenario["schedule"]["id"]
        owner_headers = make_employer_representative_headers(scenario["employer"]["id"])

        first = installment_at(api, schedule_id, 1)
        assert first["status"] == "SCHEDULED"

        stranger = register_employer(
            api, scenario["plan"]["id"], scenario["group"]["id"], **BASELINE_EMPLOYER
        )
        stranger_headers = make_employer_representative_headers(stranger["id"])

        # PRD 2.9: ownership resolves at tier 6, ahead of the tier-8 state check, so this is
        # not ERR_INSTALLMENT_NOT_PAYABLE.
        validate_error(
            api.pay_installment(
                first["id"],
                factories.payment_payload(BASELINE_QUARTERLY_INSTALLMENT_CENTS),
                stranger_headers,
            ),
            ApiErrorId.NOT_RESOURCE_OWNER.value,
            403,
        )

        validate_error(
            api.create_review_request(
                factories.review_request_payload(assessment_id), stranger_headers
            ),
            ApiErrorId.NOT_RESOURCE_OWNER.value,
            403,
        )

        # PRD 2.9: likewise this is not ERR_SCHEDULE_NOT_ACTIVE, though the generation is
        # ACTIVE rather than NOTICED.
        validate_error(
            api.cure_payment_schedule(
                schedule_id,
                factories.payment_payload(BASELINE_QUARTERLY_INSTALLMENT_CENTS),
                stranger_headers,
            ),
            ApiErrorId.NOT_RESOURCE_OWNER.value,
            403,
        )

        owner = api.pay_installment(
            first["id"],
            factories.payment_payload(BASELINE_QUARTERLY_INSTALLMENT_CENTS),
            owner_headers,
        )
        validate_error(owner, ApiErrorId.INSTALLMENT_NOT_PAYABLE.value, 409)

        assessment = get_assessment(api, assessment_id)
        assert assessment["review_status"] == "NONE"
        assert assessment["collection_status"] == "NOT_YET_DUE"


class TestTheSecondSegregationPair:
    def test_the_issuing_trustee_is_refused_and_a_different_trustee_decides(self, api):
        """The comparison is against the assessment's own `issued_by_user_id`, so the trustee
        who demanded payment cannot adjudicate the objection to it while a colleague can.

        PRD 2.11: "When a request for review is decided, the acting `X-User-ID` must differ
        from the `issued_by_user_id` recorded on the assessment."

        Design: Corner/rbac/the_trustee_who_issued_the_demand_cannot_decide_its_review
        """
        scenario = build_issued_assessment(api, employer_overrides=BASELINE_EMPLOYER)
        assessment_id = scenario["assessment"]["id"]
        assert scenario["assessment"]["issued_by_user_id"] == ISSUING_TRUSTEE_ID

        request = file_review_request(api, assessment_id, scenario["employer"]["id"])
        assert request["status"] == "PENDING"

        decision = factories.review_decision_payload(
            ReviewDecision.AFFIRMED.value, AssumptionRuling.REJECTED.value
        )

        conflicted = api.decide_review_request(
            request["id"], decision, PLAN_TRUSTEE_HEADERS
        )
        validate_error(conflicted, ApiErrorId.SEGREGATION_OF_DUTIES.value, 409)

        pending = get_review_request(api, request["id"])
        assert pending["status"] == "PENDING"
        assert pending["decided_by_user_id"] is None
        assert pending["decided_at"] is None

        decided = validate_success(
            api.decide_review_request(
                request["id"], decision, PLAN_TRUSTEE_SECONDARY_HEADERS
            ),
            200,
        )
        assert decided["status"] == "DECIDED"
        assert decided["decided_by_user_id"] == DECIDING_TRUSTEE_ID

        assessment = get_assessment(api, assessment_id)
        assert assessment["review_status"] == "DECIDED"
        assert assessment["issued_by_user_id"] == ISSUING_TRUSTEE_ID
