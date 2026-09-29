"""State machines up to the demand: valuation certification, the withdrawal
event's determination fork, and the assessment's three opening dimensions."""

import pytest
from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import factories
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import (
    BASELINE_ANNUAL_PAYMENT_CENTS,
    BASELINE_INTEREST_RATE_BPS,
    BASELINE_NET_ASSESSED_CENTS,
    BASELINE_UVB_TOTAL_CENTS,
)
from test_helpers.fixtures import (
    build_priced_assessment,
    certify_valuation,
    determine_withdrawal_event,
    file_certified_valuations,
    file_valuation,
    get_assessment,
    get_employer,
    get_event,
    get_valuation,
    issue_assessment,
    register_controlled_group,
    register_employer,
    register_plan,
    report_withdrawal_event,
)
from test_helpers.test_users import (
    FUND_ADMINISTRATOR_HEADERS,
    PLAN_ACTUARY_HEADERS,
    PLAN_TRUSTEE_HEADERS,
    TEST_USERS,
    make_employer_representative_headers,
    make_headers,
)
from test_helpers.types import CoveredWorkStatus, Industry, UserRole

CERTIFYING_ACTUARY_ID = TEST_USERS["plan_actuary"]["user_id"]
ISSUING_TRUSTEE_ID = TEST_USERS["plan_trustee"]["user_id"]

# The same human being as the certifying actuary, acting under a trustee's role.
ACTUARY_WEARING_A_TRUSTEE_HAT = make_headers(
    CERTIFYING_ACTUARY_ID, UserRole.PLAN_TRUSTEE.value
)

BASELINE_EMPLOYER = {"obligation_start_year": 2021, "cba_count": 1}


class TestValuationCertification:
    def test_certifying_a_draft_stamps_the_actuary_and_seeds_the_conserved_pair(self, api):
        """The two-step path records the acting actuary, opens the allocation pair at
        0 against the whole total, and leaves the create-and-certify audit flag false.

        PRD 3.2: "Certification is the `DRAFT → CERTIFIED` transition and is the actuary's
        act: it stamps `certified_by_user_id` with the acting `X-User-ID` and
        `certified_at` with the current logical clock, recomputes `allocated_uvb_cents` —
        which is 0 at the moment of certification, since no assessment can yet reference
        the row — and sets `unallocated_uvb_cents` equal to `uvb_total_cents`."

        Design: Corner/state_machines/valuation_certify_moves_a_draft_to_certified_and_stamps_the_certifier
        """
        plan = register_plan(api)
        draft = file_valuation(api, plan["id"], 2021, certify_on_create=False)
        assert draft["status"] == "DRAFT"

        certified = certify_valuation(api, draft["id"])

        assert certified["status"] == "CERTIFIED"
        assert certified["certified_by_user_id"] == CERTIFYING_ACTUARY_ID
        assert certified["certified_at"].startswith("2026-08-01T00:00:00")
        assert certified["certify_on_create_used"] is False
        assert certified["allocated_uvb_cents"] == 0
        assert certified["unallocated_uvb_cents"] == BASELINE_UVB_TOTAL_CENTS
        assert (
            certified["allocated_uvb_cents"] + certified["unallocated_uvb_cents"]
            == certified["uvb_total_cents"]
        )
        assert certified["version"] == 2

    def test_a_second_certification_of_the_same_row_is_refused(self, api):
        """Re-certifying would re-stamp the segregation-of-duties key, so the second call
        is a conflict and every stamp from the first survives.

        PRD 3.2: "Certifying a valuation whose `status` is not `DRAFT` is rejected with
        `ERR_VALUATION_ALREADY_CERTIFIED`. The dedicated certification act also increments
        the valuation's `version`."

        Design: Corner/state_machines/certifying_the_same_valuation_twice_is_rejected
        """
        plan = register_plan(api)
        draft = file_valuation(api, plan["id"], 2021, certify_on_create=False)
        certify_valuation(api, draft["id"])

        response = api.certify_plan_year_valuation(draft["id"], PLAN_ACTUARY_HEADERS)
        validate_error(response, ApiErrorId.VALUATION_ALREADY_CERTIFIED.value, 409)

        unchanged = get_valuation(api, draft["id"])
        assert unchanged["status"] == "CERTIFIED"
        assert unchanged["certified_by_user_id"] == CERTIFYING_ACTUARY_ID
        assert unchanged["certified_at"].startswith("2026-08-01T00:00:00")
        assert unchanged["version"] == 2


class TestInitialStates:
    def test_a_new_valuation_and_a_new_event_sit_at_their_declared_starting_values(self, api):
        """Neither row has done any work yet: the valuation is an uncertified draft and the
        event carries no classification.

        PRD 3.4: "On creation the event's `status` is `REPORTED`, its `determined_type` is
        `NONE`, and its `rules_variant` is fixed from the plan's `industry`: a
        `CONSTRUCTION` plan yields `CONSTRUCTION_RULES`, an `ENTERTAINMENT` plan yields
        `ENTERTAINMENT_RULES`, and every other industry — including both `GENERAL` and
        `TRUCKING` — yields `GENERAL_RULES`."

        Design: Corner/state_machines/a_new_valuation_and_a_new_withdrawal_event_start_in_their_declared_initial_states
        """
        plan = register_plan(api)
        group = register_controlled_group(api)
        employer = register_employer(api, plan["id"], group["id"], **BASELINE_EMPLOYER)

        valuation = file_valuation(api, plan["id"], 2021, certify_on_create=False)
        assert valuation["status"] == "DRAFT"
        assert valuation["certified_by_user_id"] is None
        assert valuation["certified_at"] is None
        assert valuation["certify_on_create_used"] is False

        event = report_withdrawal_event(api, employer["id"])
        assert event["status"] == "REPORTED"
        assert event["determined_type"] == "NONE"
        assert event["rules_variant"] == "GENERAL_RULES"
        assert event["ceased_cba_count"] == 0
        assert event["determined_at"] is None
        # PRD 3.4: for `NONE` the fraction is exactly 0.0000.
        assert event["partial_withdrawal_fraction"] == pytest.approx(0.0, abs=0.0001)

    def test_a_draft_assessment_carries_the_full_price_in_all_three_dimensions_at_rest(
        self, api
    ):
        """A priced draft is a proposal: no schedule, no review window, and a request for
        review filed against it is refused.

        PRD 3.5: "A freshly computed assessment sits at `lifecycle_status` `DRAFT`,
        `review_status` `NONE`, `collection_status` `NOT_YET_DUE`, `award_adjustment_cents` 0
        and `active_schedule_generation` 0."

        Design: Corner/state_machines/a_draft_assessment_starts_in_three_dimensions_and_rejects_a_review_request
        """
        scenario = build_priced_assessment(api, employer_overrides=BASELINE_EMPLOYER)
        assessment = scenario["assessment"]

        assert assessment["lifecycle_status"] == "DRAFT"
        assert assessment["review_status"] == "NONE"
        assert assessment["collection_status"] == "NOT_YET_DUE"
        assert assessment["gross_allocated_cents"] == BASELINE_NET_ASSESSED_CENTS
        assert assessment["de_minimis_reduction_cents"] == 0
        assert assessment["award_adjustment_cents"] == 0
        assert assessment["net_assessed_cents"] == BASELINE_NET_ASSESSED_CENTS
        assert assessment["annual_payment_cents"] == BASELINE_ANNUAL_PAYMENT_CENTS
        assert assessment["allocation_method_applied"] == "MODIFIED_PRESUMPTIVE"
        assert assessment["de_minimis_variant_applied"] == "STATUTORY"
        assert assessment["interest_rate_bps_applied"] == BASELINE_INTEREST_RATE_BPS
        assert assessment["pool_term_breakdown"] == []
        assert assessment["issued_at"] is None
        assert assessment["issued_by_user_id"] is None
        assert assessment["review_deadline_at"] is None
        assert assessment["active_schedule_generation"] == 0

        _rows, meta = validate_paginated(
            api.list_payment_schedules(
                FUND_ADMINISTRATOR_HEADERS, {"liability_assessment_id": assessment["id"]}
            )
        )
        assert meta["total_count"] == 0

        refused = api.create_review_request(
            factories.review_request_payload(assessment["id"]),
            make_employer_representative_headers(scenario["employer"]["id"]),
        )
        validate_error(refused, ApiErrorId.ASSESSMENT_NOT_ISSUED.value, 409)


class TestDeterminationGatesThePrice:
    def test_a_no_withdrawal_event_refuses_both_redetermination_and_pricing(self, api):
        """Construction rules found no withdrawal, and the terminal event answers the two
        follow-up attempts with two different codes.

        PRD 3.5: "The event's `status` must be `COMPLETE_DETERMINED` or
        `PARTIAL_DETERMINED`: an event still in `REPORTED` is rejected with
        `ERR_WITHDRAWAL_NOT_DETERMINED`, and an event that reached `NO_WITHDRAWAL` is
        rejected with `ERR_NO_WITHDRAWAL_DETERMINED`."

        Design: Corner/state_machines/a_no_withdrawal_event_is_terminal_and_rejects_determine_and_assessment
        """
        plan = register_plan(api, industry=Industry.CONSTRUCTION.value)
        group = register_controlled_group(api)
        employer = register_employer(
            api,
            plan["id"],
            group["id"],
            covered_work_status=CoveredWorkStatus.CEASED.value,
            **BASELINE_EMPLOYER,
        )
        file_certified_valuations(api, plan["id"], years=(2025,))

        event = report_withdrawal_event(api, employer["id"])
        determined = determine_withdrawal_event(api, event["id"])
        assert determined["determined_type"] == "NONE"
        assert determined["partial_withdrawal_fraction"] == pytest.approx(0.0, abs=0.0001)
        assert determined["status"] == "NO_WITHDRAWAL"

        settled_employer = get_employer(api, employer["id"])
        assert settled_employer["status"] == "CONTRIBUTING"
        assert settled_employer["obligation_end_year"] is None

        again = api.determine_withdrawal_event(event["id"], PLAN_ACTUARY_HEADERS)
        validate_error(again, ApiErrorId.WITHDRAWAL_ALREADY_DETERMINED.value, 409)

        priced = api.create_liability_assessment(
            factories.liability_assessment_payload(event["id"]), PLAN_ACTUARY_HEADERS
        )
        validate_error(priced, ApiErrorId.NO_WITHDRAWAL_DETERMINED.value, 409)

        _rows, meta = validate_paginated(
            api.list_liability_assessments(
                FUND_ADMINISTRATOR_HEADERS, {"withdrawal_event_id": event["id"]}
            )
        )
        assert meta["total_count"] == 0

    def test_pricing_a_still_reported_event_is_refused_on_its_status(self, api):
        """Every input the assessment needs is already filed, so the only obstacle is the
        undetermined event, and it answers with its own code.

        PRD 3.5: "The actuary computes a draft **LiabilityAssessment** against a determined
        withdrawal event, the payload naming only the `withdrawal_event_id`; every other
        figure on the assessment is derived."

        Design: Corner/state_machines/assessment_creation_before_determination_is_rejected
        """
        scenario = build_priced_assessment(
            api, employer_overrides=BASELINE_EMPLOYER, determine=False, price=False
        )

        response = api.create_liability_assessment(
            factories.liability_assessment_payload(scenario["event"]["id"]),
            PLAN_ACTUARY_HEADERS,
        )
        validate_error(response, ApiErrorId.WITHDRAWAL_NOT_DETERMINED.value, 409)

        still_reported = get_event(api, scenario["event"]["id"])
        assert still_reported["status"] == "REPORTED"
        assert still_reported["determined_at"] is None


class TestIssuance:
    def test_the_certifying_actuary_may_not_issue_the_demand_they_priced(self, api):
        """The comparison is against the anchor valuation's certifier and ignores the acting
        role, so the same person in a trustee's seat is still barred; a second trustee
        issues cleanly.

        PRD 2.11: "When an assessment is issued, the acting `X-User-ID` must differ from the
        `certified_by_user_id` recorded on the anchor valuation named by the assessment's
        `valuation_id`."

        Design: Corner/state_machines/the_certifying_actuary_cannot_issue_the_demand_against_that_valuation
        """
        scenario = build_priced_assessment(api, employer_overrides=BASELINE_EMPLOYER)
        assessment_id = scenario["assessment"]["id"]

        refused = api.issue_liability_assessment(
            assessment_id, ACTUARY_WEARING_A_TRUSTEE_HAT
        )
        validate_error(refused, ApiErrorId.SEGREGATION_OF_DUTIES.value, 409)

        blocked = get_assessment(api, assessment_id)
        assert blocked["lifecycle_status"] == "DRAFT"
        assert blocked["issued_at"] is None
        _rows, meta = validate_paginated(
            api.list_payment_schedules(
                FUND_ADMINISTRATOR_HEADERS, {"liability_assessment_id": assessment_id}
            )
        )
        assert meta["total_count"] == 0

        issued = validate_success(
            api.issue_liability_assessment(assessment_id, PLAN_TRUSTEE_HEADERS), 200
        )
        assert issued["lifecycle_status"] == "ISSUED"
        assert issued["issued_by_user_id"] == ISSUING_TRUSTEE_ID
        assert issued["issued_at"].startswith("2026-08-01T00:00:00")
        assert issued["review_deadline_at"].startswith("2026-10-30T00:00:00")

    def test_issuing_twice_would_double_the_cascade_and_is_refused(self, api):
        """The guard is the lifecycle status, so the second issuance mints no second
        generation and re-allocates nothing on the anchor valuation.

        PRD 3.6: "It requires the `lifecycle_status` to be `DRAFT`, rejecting otherwise with
        `ERR_ASSESSMENT_ALREADY_ISSUED`; the same code is returned when a *different*
        assessment for the same withdrawal event has already reached `ISSUED` or `FINAL`,
        because a single event may support only one live demand."

        Design: Corner/state_machines/issuing_an_already_issued_assessment_is_rejected
        """
        scenario = build_priced_assessment(api, employer_overrides=BASELINE_EMPLOYER)
        assessment_id = scenario["assessment"]["id"]
        issue_assessment(api, assessment_id)

        response = api.issue_liability_assessment(assessment_id, PLAN_TRUSTEE_HEADERS)
        validate_error(response, ApiErrorId.ASSESSMENT_ALREADY_ISSUED.value, 409)

        rows, meta = validate_paginated(
            api.list_payment_schedules(
                FUND_ADMINISTRATOR_HEADERS, {"liability_assessment_id": assessment_id}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["generation_seq"] == 1

        assessment = get_assessment(api, assessment_id)
        assert assessment["issued_by_user_id"] == ISSUING_TRUSTEE_ID
        assert assessment["active_schedule_generation"] == 1

        anchor = get_valuation(api, scenario["valuations"][2025]["id"])
        assert anchor["allocated_uvb_cents"] == BASELINE_NET_ASSESSED_CENTS
