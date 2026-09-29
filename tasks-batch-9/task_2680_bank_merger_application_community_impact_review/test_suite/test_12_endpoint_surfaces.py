"""Endpoint surfaces: the amendment patch, the clearance summary and cross-referenced writes."""
import pytest

from test_helpers import ApiErrorId, TEST_USERS, api_client
from test_helpers.assertions import (
    assert_approval_condition,
    assert_hearing_request,
    assert_same_instant,
)
from test_helpers.fixtures import (
    accept_application,
    application_decided,
    application_under_review,
    attach_condition,
    auto_comment_period,
    create_acquirer,
    create_application,
    create_regulatory_schedule,
    create_target,
    designate_for_divestiture,
    executed_standard_plan,
    file_substantive_protest,
    granite_market_world,
    read_application,
    read_condition,
    read_decision,
    request_hearing,
    reset_clock_to_epoch,
    satisfy_condition,
    set_clock,
    submit_application,
)
from test_helpers.test_users import COMMENTER_USER_ID, MONITOR_USER_ID
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

ANALYST = TEST_USERS["analyst_headers"]
OFFICIAL = TEST_USERS["official_headers"]
COMMENTER = TEST_USERS["commenter_headers"]
MONITOR = TEST_USERS["monitor_headers"]


class TestAmendmentPatch:
    """The amendment endpoint rescores the management assessment in place."""

    def test_01_amending_the_examiner_scores_rebands_the_management_rating(self):
        """PRD §3.2: "Amending an undecided application is open to both the `Filer` who owns it and
        to a `CaseAnalyst`, and any subset of `structure`, `consideration_type`,
        `total_consideration_usd`, `officer_experience_score`, `risk_management_score`,
        `compliance_history_score` and `integration_readiness_score` may be supplied."
        PRD §3.2: "Whenever any examiner score changes the composite and the rating are recomputed
        by the same per-product rounding procedure, and the amendment increments the application's
        `version` by 1."
        PRD §3.2: "The composite is then banded into `management_rating`: a composite of 70.00 or
        more is `SATISFACTORY`, a composite of at least 55.00 but below 70.00 is `CONDITIONAL`, and
        anything below 55.00 is `UNSATISFACTORY`."

        Design: Corner/endpoints/patching_examiner_scores_rescores_the_management_composite
        """
        reset_clock_to_epoch()
        acquirer = create_acquirer()
        target = create_target()
        application = create_application(
            acquirer["id"], target["id"], officer_experience_score=60,
            risk_management_score=60, compliance_history_score=60, integration_readiness_score=60,
        )
        assert application["management_composite_score"] == pytest.approx(60.00, abs=0.005)
        assert application["management_rating"] == "CONDITIONAL"

        amended = validate_success(api_client.amend_merger_application(
            application["id"],
            {"officer_experience_score": 72, "risk_management_score": 68,
             "compliance_history_score": 67, "integration_readiness_score": 73,
             "total_consideration_usd": 260_000_000},
            ANALYST,
        ))

        assert amended["officer_experience_score"] == 72
        assert amended["total_consideration_usd"] == 260_000_000
        assert amended["management_composite_score"] == pytest.approx(70.11, abs=0.005), (
            "25.20 + 20.40 + 11.73 + 12.78, each weighted product rounded before the sum"
        )
        assert amended["management_rating"] == "SATISFACTORY", (
            "the composite crossed 70.00, so the rating rebands away from CONDITIONAL"
        )
        assert amended["version"] == 2
        refetched = read_application(application["id"], acquirer["id"])
        assert refetched["management_composite_score"] == pytest.approx(70.11, abs=0.005)
        assert refetched["management_rating"] == "SATISFACTORY"
        assert refetched["total_consideration_usd"] == 260_000_000


class TestClearanceSummary:
    """The consolidated read assembles the competitive, capital and protest picture."""

    def test_02_the_clearance_summary_reports_the_derived_case_posture(self):
        """PRD §3.13: "It reports the `application_id`; the application's `competitive_posture`;
        `worst_screen_result`, the most severe `screen_result` across the application's analyses;
        `max_hhi_delta_unmitigated`, the largest `hhi_delta_unmitigated` across them;
        `total_required_divestiture_usd` and `total_designated_divestiture_usd`, the sums of
        `required_divestiture_deposits_usd` and of `designated_divestiture_deposits_usd` across
        them; `all_markets_mitigated`, true only when every analysis has `mitigation_satisfied`
        true; `current_regulatory_cet1_pct` and `current_regulatory_capital_flag`, taken from the
        `CURRENT` `REGULATORY_ADJUSTED` schedule's `pro_forma_cet1_ratio_pct` and
        `capital_adequacy_flag`; `substantive_protest_count` and `unresolved_protest_count` as the
        application carries them; `granted_hearing_count`, the number of hearing requests on the
        application whose `status` is `GRANTED`; `earliest_decision_at`; `expedited_eligible`,
        applying the four expedited tests of §3.10 to the application as it currently stands; and
        `projected_waiting_period_days`, the waiting period the same arithmetic would produce were
        the order issued now."
        PRD §3.10: "The application is eligible for `expedited_processing` — a boolean stored on the
        order — when four things hold together: its `unresolved_protest_count` is 0, no hearing
        request on it has been granted, the largest `hhi_delta_unmitigated` across its analyses is
        at most 200 (taken as 0 when it has no analyses), and its `management_rating` is exactly
        `SATISFACTORY`."
        PRD §3.10: "The base period is 30 days when the `structure` is `HOLDCO_ACQUISITION` and 15
        days for either bank-level structure."

        Design: Corner/endpoints/clearance_summary_reports_the_derived_competitive_and_capital_picture
        """
        world = granite_market_world()
        application_id = world["application"]["id"]
        acquirer_id = world["acquirer"]["id"]
        create_regulatory_schedule(application_id, acquirer_id)
        submit_application(application_id, acquirer_id)
        accept_application(application_id)
        auto_comment_period(application_id)
        designate_for_divestiture(world["branch_target"]["id"], application_id, acquirer_id)

        summary = validate_success(api_client.get_clearance_summary(application_id, OFFICIAL))

        assert summary["application_id"] == application_id
        assert summary["competitive_posture"] == "CLEARED_WITH_DIVESTITURE"
        assert summary["worst_screen_result"] == "PRESUMPTIVE_VIOLATION"
        assert summary["max_hhi_delta_unmitigated"] == 1200
        assert summary["total_required_divestiture_usd"] == 139_000_000
        assert summary["total_designated_divestiture_usd"] == 200_000_000
        assert summary["all_markets_mitigated"] is True
        assert summary["current_regulatory_cet1_pct"] == pytest.approx(7.74, abs=0.005)
        assert summary["current_regulatory_capital_flag"] == "WELL_CAPITALIZED"
        assert summary["substantive_protest_count"] == 0
        assert summary["unresolved_protest_count"] == 0
        assert summary["granted_hearing_count"] == 0
        assert_same_instant(summary["earliest_decision_at"], "2026-09-15T00:00:00Z",
                            "earliest_decision_at")
        assert summary["expedited_eligible"] is False, (
            "the unmitigated delta of 1200 exceeds the 200-point safe harbour"
        )
        assert summary["projected_waiting_period_days"] == 15, (
            "a statutory merger is bank level, and nothing adds to or reduces the base"
        )


class TestCommunityBenefitsConditionSatisfaction:
    """A commitment condition is only closable once the package is executed."""

    def _decided_case_with_a_benefits_condition(self):
        world = application_decided()
        world["condition"] = attach_condition(
            world["decision"]["id"], condition_type="COMMUNITY_BENEFITS",
            timing="PRE_CONSUMMATION", threshold_usd=392_000_000,
            description="Execute the community benefits plan before closing.",
        )
        return world

    def test_03_satisfying_a_commitment_condition_without_an_executed_plan_is_refused(self):
        """PRD §3.10: "A `COMMUNITY_BENEFITS` condition additionally requires an `EXECUTED`
        community benefits plan to exist on the application, its absence yielding
        `ERR_BENEFITS_PLAN_NOT_EXECUTED`."
        PRD §3.10: "A condition is created with `status` `OPEN` and with `satisfied_at` and
        `satisfied_by_user_id` null."

        Design: Corner/endpoints/satisfying_a_community_benefits_condition_requires_an_executed_plan
        """
        world = self._decided_case_with_a_benefits_condition()
        condition = world["condition"]
        assert_approval_condition(condition)
        assert condition["threshold_usd"] == 392_000_000

        response = api_client.satisfy_approval_condition(condition["id"], MONITOR)

        validate_error(response, ApiErrorId.ERR_BENEFITS_PLAN_NOT_EXECUTED.value, 422)
        refetched = read_condition(condition["id"])
        assert refetched["status"] == "OPEN"
        assert refetched["satisfied_at"] is None
        assert refetched["satisfied_by_user_id"] is None
        assert read_decision(world["decision"]["id"])["status"] == "ISSUED", (
            "the refusal left the order itself untouched"
        )

    def test_04_the_same_call_succeeds_once_the_package_is_executed(self):
        """PRD §3.10: "A `ComplianceMonitor` records satisfaction, driving `OPEN → SATISFIED`."
        PRD §3.10: "Satisfaction stamps `satisfied_at` from the logical clock and
        `satisfied_by_user_id` with the acting `X-User-ID`."
        PRD §3.9: "Execution is the filer's commitment and drives `PROPOSED → EXECUTED`."

        Design: Corner/endpoints/satisfying_a_community_benefits_condition_requires_an_executed_plan
        """
        world = self._decided_case_with_a_benefits_condition()
        condition = world["condition"]
        executed = executed_standard_plan(world["application"]["id"], world["acquirer"]["id"])
        assert executed["plan"]["status"] == "EXECUTED"

        satisfied = satisfy_condition(condition["id"], MONITOR)

        assert satisfied["status"] == "SATISFIED", (
            "the identical call is admissible only under the stated condition"
        )
        assert satisfied["satisfied_by_user_id"] == MONITOR_USER_ID
        assert_same_instant(satisfied["satisfied_at"], "2026-09-15T00:00:00Z", "satisfied_at")


class TestHearingPetitionLinkage:
    """A petition must name a comment that exists, and it copies that comment's requester."""

    def test_05_a_petition_naming_an_unknown_comment_is_not_found(self):
        """PRD §2.4: "A foreign key carried in a request body that does not resolve produces the same
        family of not-found errors at HTTP 404: an unresolvable institution reference yields
        `ERR_INSTITUTION_NOT_FOUND`, an unresolvable market reference `ERR_MARKET_NOT_FOUND`, an
        unresolvable application reference `ERR_APPLICATION_NOT_FOUND`, an unresolvable
        comment-period reference `ERR_COMMENT_PERIOD_NOT_FOUND`, an unresolvable comment reference
        `ERR_COMMENT_NOT_FOUND`, an unresolvable benefits-plan reference `ERR_PLAN_NOT_FOUND` and an
        unresolvable decision reference `ERR_DECISION_NOT_FOUND`."

        Design: Corner/endpoints/hearing_request_links_an_application_to_an_existing_comment
        """
        world = application_under_review()
        set_clock("2026-08-10T00:00:00Z")
        file_substantive_protest(
            world["period"]["id"], commenter_name="Kestrel Housing Coalition",
            commenter_type="COMMUNITY_ORGANIZATION",
            body="Small-business lending in low-income tracts fell 40 percent.",
        )

        response = api_client.create_hearing_request(
            {"application_id": world["application"]["id"], "comment_id": NON_EXISTENT_UUID,
             "basis": "Oral testimony is needed."},
            COMMENTER,
        )

        validate_error(response, ApiErrorId.ERR_COMMENT_NOT_FOUND.value, 404)
        requests, meta = validate_paginated(api_client.list_hearing_requests(
            ANALYST, params={"application_id": world["application"]["id"]}))
        assert meta["total_count"] == 0, "the refused petition was never recorded"
        assert requests == []

    def test_06_a_petition_founded_on_a_protest_links_both_records(self):
        """PRD §3.8: "The petition is created with `status` `PENDING`, `requested_at` stamped from the
        logical clock, `requester_user_id` taken from the acting `X-User-ID`,
        `extension_days_granted` at 0, and `decided_at`, `decided_by_user_id` and
        `decision_rationale` null."
        PRD §3.8: "Its creation moves the application's community-review axis `PROTEST_PENDING →
        HEARING_PENDING`."
        PRD §2.3: "the hearing-request list accepts `application_id`, `comment_id` and `status`"

        Design: Corner/endpoints/hearing_request_links_an_application_to_an_existing_comment
        """
        world = application_under_review()
        application_id = world["application"]["id"]
        set_clock("2026-08-10T00:00:00Z")
        protest = file_substantive_protest(
            world["period"]["id"], commenter_name="Kestrel Housing Coalition",
            commenter_type="COMMUNITY_ORGANIZATION",
            body="Small-business lending in low-income tracts fell 40 percent.",
        )

        petition = request_hearing(
            application_id, protest["id"],
            basis="Oral testimony is needed on the lending record.",
        )

        assert_hearing_request(petition)
        assert petition["application_id"] == application_id
        assert petition["comment_id"] == protest["id"]
        assert petition["requester_user_id"] == COMMENTER_USER_ID
        assert petition["requester_user_id"] == protest["commenter_user_id"]
        assert_same_instant(petition["requested_at"], "2026-08-10T00:00:00Z", "requested_at")
        assert petition["status"] == "PENDING"
        assert petition["extension_days_granted"] == 0
        application = read_application(application_id, world["acquirer"]["id"])
        assert application["public_review_status"] == "HEARING_PENDING"
        requests, meta = validate_paginated(api_client.list_hearing_requests(
            ANALYST, params={"comment_id": protest["id"]}))
        assert meta["total_count"] == 1
        assert [record["id"] for record in requests] == [petition["id"]]
