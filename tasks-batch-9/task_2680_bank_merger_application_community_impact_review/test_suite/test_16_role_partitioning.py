"""Role partitioning: exclusive write surfaces, the one shared write, and entity-backed filers."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    make_filer_headers,
)
from test_helpers.factories import (
    merger_application_payload,
    pro_forma_schedule_payload,
)
from test_helpers.fixtures import (
    accept_application,
    application_recommended,
    create_acquirer,
    create_application,
    create_regulatory_schedule,
    create_target,
    create_third_party,
    read_application,
    read_schedule,
    reset_clock_to_epoch,
    set_clock,
    submit_application,
)
from test_helpers.test_users import ANALYST_USER_ID, OFFICIAL_USER_ID
from prd_bench_local_runner.testing import (
    build_user_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

ANALYST = TEST_USERS["analyst_headers"]
OFFICIAL = TEST_USERS["official_headers"]
COMMENTER = TEST_USERS["commenter_headers"]
MONITOR = TEST_USERS["monitor_headers"]


class TestExclusiveWriteSurfaces:
    """Each write belongs to exactly one role, and the gate runs before everything else."""

    def test_01_a_role_reaching_for_another_roles_write_is_refused(self):
        """PRD §2.1: "Writes are tightly partitioned."
        PRD §2.1: "If both headers are present and well-formed but the acting role is not among the
        roles authorized for the endpoint being called, the request is rejected with
        `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
        PRD §2.5: "Checks run in the following sequence, and the first violated check ends the
        request:"
        PRD §2.5: "Endpoint role authorization — `ERR_ROLE_NOT_PERMITTED`."

        Design: Corner/rbac/each_role_is_blocked_from_the_other_roles_exclusive_operations
        """
        reset_clock_to_epoch()
        acquirer = create_acquirer()
        target = create_target()
        application = create_application(acquirer["id"], target["id"])
        application_id = application["id"]
        filer_headers = make_filer_headers(acquirer["id"])

        filer_decides = api_client.create_approval_decision(
            {"application_id": application_id, "decision": "APPROVED"}, filer_headers)
        analyst_submits = api_client.submit_merger_application(application_id, ANALYST)
        filer_registers_institution = api_client.create_institution(
            {"legal_name": "Filer Made This", "charter_type": "NATIONAL",
             "primary_regulator": "OCC"}, filer_headers)
        official_accepts = api_client.accept_merger_application(application_id, OFFICIAL)
        monitor_drives_clock = api_client.set_clock("2026-08-02T00:00:00Z", MONITOR)
        commenter_files = api_client.create_merger_application(
            merger_application_payload(acquirer["id"], target["id"], consideration_type="ALL_CASH",
                                       total_consideration_usd=1_000_000),
            COMMENTER)

        for response in (filer_decides, analyst_submits, filer_registers_institution,
                         official_accepts, monitor_drives_clock, commenter_files):
            validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)
        refetched = read_application(application_id, acquirer["id"])
        assert refetched["filing_status"] == "DRAFT", (
            "the filer's decision attempt was refused on role, not on the application's state"
        )
        decisions, decision_meta = validate_paginated(api_client.list_approval_decisions(ANALYST))
        assert decision_meta["total_count"] == 0
        assert decisions == []
        institutions, institution_meta = validate_paginated(
            api_client.list_institutions(ANALYST))
        assert institution_meta["total_count"] == 2, "the filer registered nothing"
        applications, application_meta = validate_paginated(
            api_client.list_merger_applications(ANALYST))
        assert application_meta["total_count"] == 1, "the commenter filed nothing"
        assert [record["id"] for record in applications] == [application_id]

    def test_02_each_of_those_writes_succeeds_under_its_declared_role(self):
        """PRD §2.1: "Only a `CaseAnalyst` registers institutions, creates deposit markets, adds
        branches, runs competitive analyses, opens and closes comment periods, accepts a filing for
        substantive review, returns a filing for amendment, records the staff recommendation, and
        drives the logical clock."
        PRD §2.1: "Only a `Filer` opens a merger application, submits it, designates and rescinds
        branch designations, proposes and executes community benefits plans and their line items,
        responds to public comments, consummates, registers and discloses and completes a systems
        conversion, and files performance reports."
        PRD §2.4: "The service holds a logical UTC clock that a `CaseAnalyst` may set to an arbitrary
        instant by supplying `now`; the response echoes `now`."
        PRD §3.4: "It creates a public comment period for the application, opening at the current
        clock instant with a `duration_days` of 30 and `status` `OPEN`."

        Design: Corner/rbac/each_role_is_blocked_from_the_other_roles_exclusive_operations
        """
        reset_clock_to_epoch()
        acquirer = create_acquirer()
        target = create_target()
        application = create_application(acquirer["id"], target["id"])
        application_id = application["id"]
        create_regulatory_schedule(application_id, acquirer["id"])

        echoed = set_clock("2026-08-02T00:00:00Z")
        submitted = submit_application(application_id, acquirer["id"])
        accepted = accept_application(application_id)

        assert echoed["now"].startswith("2026-08-02T00:00:00"), (
            "the analyst's clock write took effect where the monitor's was refused"
        )
        assert submitted["filing_status"] == "SUBMITTED"
        assert accepted["filing_status"] == "UNDER_REVIEW"
        periods, meta = validate_paginated(api_client.list_comment_periods(
            ANALYST, params={"application_id": application_id}))
        assert meta["total_count"] == 1
        assert periods[0]["opens_at"].startswith("2026-08-02T00:00:00"), (
            "acceptance opened the window at the instant the analyst had set"
        )
        assert periods[0]["duration_days"] == 30
        assert periods[0]["status"] == "OPEN"


class TestSharedScheduleWrite:
    """The capital schedule is exactly two roles wide."""

    def test_03_the_filer_and_the_case_analyst_both_build_schedules(self):
        """PRD §2.1: "Two write surfaces are shared: amending an application's structure or examiner
        scores is open to both `Filer` and `CaseAnalyst`, and building a pro forma capital schedule is
        likewise open to both."
        PRD §3.3: "Building a new schedule on a basis moves the prior current schedule of that same
        basis to `SUPERSEDED`, and increments the application's `version` by 1."
        PRD §3.3: "The resulting pair of ratios is banded into `capital_adequacy_flag`."

        Design: Corner/rbac/the_pro_forma_schedule_write_is_shared_by_filer_and_case_analyst
        """
        reset_clock_to_epoch()
        acquirer = create_acquirer()
        target = create_target()
        application = create_application(acquirer["id"], target["id"])
        application_id = application["id"]
        assert application["version"] == 1

        first = validate_success(api_client.create_pro_forma_schedule(
            pro_forma_schedule_payload(application_id, 1), make_filer_headers(acquirer["id"])), 201)
        after_filer = read_application(application_id, acquirer["id"])
        second = validate_success(api_client.create_pro_forma_schedule(
            pro_forma_schedule_payload(application_id, after_filer["version"]), ANALYST), 201)
        monitor_attempt = api_client.create_pro_forma_schedule(
            pro_forma_schedule_payload(application_id, 3), MONITOR)

        assert after_filer["version"] == 2, "the filer's schedule bumped the parent application"
        validate_error(monitor_attempt, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)
        assert read_schedule(first["id"])["status"] == "SUPERSEDED"
        assert read_schedule(second["id"])["status"] == "CURRENT"
        for schedule in (first, second):
            assert schedule["pro_forma_cet1_ratio_pct"] == pytest.approx(7.74, abs=0.005), (
                "the acting role does not change the arithmetic"
            )
            assert schedule["capital_adequacy_flag"] == "WELL_CAPITALIZED"
        assert read_application(application_id, acquirer["id"])["version"] == 3, (
            "the analyst's schedule bumped the parent application too"
        )


class TestSegregationOfDuties:
    """The decision check compares identities, not roles."""

    def test_04_the_recommending_analyst_cannot_issue_the_order(self):
        """PRD §2.1: "Segregation of duties requires that the `ApprovingOfficial` who issues the
        decision be a different person from the `CaseAnalyst` who recorded the staff recommendation:
        the acting `X-User-ID` at decision time must differ from the application's stored
        `recommended_by_user_id`."
        PRD §2.1: "When the two are equal the decision is refused with `ERR_SEGREGATION_OF_DUTIES`
        (HTTP 403)."
        PRD §3.10: "Either way the order records `decided_by_user_id` from the acting `X-User-ID` and
        stamps `decided_at` from the logical clock, and both consummation timestamps are anchored to
        `decided_at`."

        Design: Corner/rbac/the_recommending_analyst_cannot_also_issue_the_decision
        """
        world = application_recommended(recommendation="APPROVE")
        application_id = world["application"]["id"]
        assert world["application"]["recommended_by_user_id"] == ANALYST_USER_ID

        refused = api_client.create_approval_decision(
            {"application_id": application_id, "decision": "APPROVED"},
            build_user_headers(ANALYST_USER_ID, "ApprovingOfficial"))

        validate_error(refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)
        decisions, meta = validate_paginated(api_client.list_approval_decisions(
            ANALYST, params={"application_id": application_id}))
        assert meta["total_count"] == 0, "the rejected call created nothing"
        assert read_application(application_id, world["acquirer"]["id"])["filing_status"] == (
            "RECOMMENDED"), "the refusal left the filing where the recommendation put it"

        issued = validate_success(api_client.create_approval_decision(
            {"application_id": application_id, "decision": "APPROVED"}, OFFICIAL), 201)

        assert issued["decided_by_user_id"] == OFFICIAL_USER_ID, (
            "the check is on user identity, not on the role header"
        )
        assert issued["status"] == "ISSUED"


class TestEntityBackedFilerIdentity:
    """A filer's identity is an institution id; reads stay open to everyone."""

    def test_05_every_role_reads_the_same_application(self):
        """PRD §2.1: "Read access is broad."
        PRD §2.1: "Every role may read institutions, deposit markets, branches, merger applications,
        competitive analyses, comment periods, public comments, hearing requests, community benefits
        plans, commitment line items, approval decisions, approval conditions and performance
        reports."

        Design: Corner/rbac/filer_identity_is_entity_backed_while_reads_stay_open_to_every_role
        """
        reset_clock_to_epoch()
        acquirer = create_acquirer()
        target = create_target()
        stranger = create_third_party()
        application = create_application(acquirer["id"], target["id"])
        application_id = application["id"]

        seen_by_stranger = validate_success(api_client.get_merger_application(
            application_id, make_filer_headers(stranger["id"])))
        seen_by_commenter = validate_success(api_client.get_merger_application(
            application_id, COMMENTER))
        seen_by_monitor = validate_success(api_client.get_merger_application(
            application_id, MONITOR))
        seen_by_official = validate_success(api_client.get_merger_application(
            application_id, OFFICIAL))

        assert seen_by_stranger["id"] == application_id
        assert seen_by_commenter["id"] == application_id
        assert seen_by_monitor["id"] == application_id
        assert seen_by_official["id"] == application_id
        assert seen_by_stranger["acquirer_id"] == acquirer["id"], (
            "an unrelated filer reads the record without owning it"
        )

    def test_06_a_stranger_files_its_own_case_but_cannot_amend_another(self):
        """PRD §2.1: "When `X-User-Role` is `Filer`, `X-User-ID` is the `id` of the acting
        `Institution`; ownership checks on any resource that references an `Institution` compare the
        resource's foreign-key field to `X-User-ID`."
        PRD §2.1: "A `Filer` whose `X-User-ID` does not match the application's `acquirer_id` is
        rejected with `ERR_NOT_APPLICATION_FILER` (HTTP 403)."
        PRD §3.2: "Amending an undecided application is open to both the `Filer` who owns it and to a
        `CaseAnalyst`, and any subset of `structure`, `consideration_type`, `total_consideration_usd`,
        `officer_experience_score`, `risk_management_score`, `compliance_history_score` and
        `integration_readiness_score` may be supplied."

        Design: Corner/rbac/filer_identity_is_entity_backed_while_reads_stay_open_to_every_role
        """
        reset_clock_to_epoch()
        acquirer = create_acquirer()
        target = create_target()
        stranger = create_third_party()
        application = create_application(acquirer["id"], target["id"])
        assert application["total_consideration_usd"] == 250_000_000

        own_filing = create_application(
            stranger["id"], target["id"], structure="PURCHASE_AND_ASSUMPTION",
            consideration_type="ALL_CASH", total_consideration_usd=80_000_000,
            officer_experience_score=65, risk_management_score=65, compliance_history_score=65,
            integration_readiness_score=65)
        refused = api_client.amend_merger_application(
            application["id"], {"total_consideration_usd": 999},
            make_filer_headers(stranger["id"]))

        assert own_filing["acquirer_id"] == stranger["id"], (
            "the Filer role is entity-backed, so the stranger acts freely on what it owns"
        )
        assert own_filing["filing_status"] == "DRAFT"
        validate_error(refused, ApiErrorId.ERR_NOT_APPLICATION_FILER.value, 403)
        refetched = read_application(application["id"], acquirer["id"])
        assert refetched["total_consideration_usd"] == 250_000_000
        assert refetched["version"] == 1, "the refused amendment bumped nothing"
