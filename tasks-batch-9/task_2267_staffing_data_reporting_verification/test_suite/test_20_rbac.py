"""Who may act: the seven roles walking their own exclusive steps, and the
identity gates that stop everyone else."""

from test_helpers import (
    ApiErrorId,
    AppealScenario,
    AppealStatus,
    AuthorizedRole,
    MeasureScenario,
    PublicationStatus,
    ReportingPeriodStatus,
    SubmissionStatus,
    TEST_DEFAULTS,
    VendorScenario,
    VendorSubmissionStatus,
    WorkerStatus,
    approx_score,
    build_supported_quarter,
    create_hour_entry_payload,
    create_staffing_measure_payload,
    create_vendor_payload,
    make_facility_administrator_headers,
    make_staffing_coordinator_headers,
    make_state_auditor_headers,
    make_vendor_representative_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import (
    ACCEPTING_AUDITOR_USER_ID,
    VERIFYING_AUDITOR_USER_ID,
)

DENIAL_NOTE = "The keyed job category does not move the star rating."
FOREIGN_COORDINATOR_NAME = "Noel Othercoord"
SECOND_VENDOR_NAME = "Southgate Agency Staffing"
SECOND_VENDOR_TAX_ID = "74-3310077"
SECOND_VENDOR_CONTACT = "ops@southgate.example"
DUAL_ROLE_WORKER_NAME = "Quinn Dualrole"


class TestEachRoleWalksItsOwnStep:
    def test_01_the_approval_chain_is_walkable_when_every_step_is_taken_by_its_own_role(
        self, api, client
    ):
        """PRD: "`PlatformAdmin` operates the reporting platform itself: it
        registers facilities, opens and closes reporting periods, defines job
        categories, and drives the logical clock." PRD: "`StaffingCoordinator` is the
        facility staffing office. It captures hours, census days, and vendor batch
        acceptances, and runs the validation pass." PRD: "`FacilityAdministrator` is
        facility leadership. It attests and submits the quarter, answers discrepancy
        information requests, and files rating appeals." PRD: "`StateAuditor` is the state
        survey agency. It accepts or rejects submissions, verifies payroll support on
        individual hours, waives findings, suspends vendors, and runs discrepancy
        investigations." PRD: "`CmsPublisher` is the national rating publisher. It computes
        staffing measures from accepted submissions and publishes star ratings." PRD:
        "`AppealsReviewer` is an independent reviewer that grants or denies rating
        appeals". PRD: "`VendorRepresentative` is the staffing agency contact. It files,
        attests, and revokes agency hour batches."

        Design: Corner/rbac/each_role_performs_its_own_exclusive_operations
        """
        scenario = build_supported_quarter(client)
        universe = scenario.universe
        vendor = VendorScenario(universe)
        vendor.file_batch([vendor.batch_line("2026-04-06")])

        facility = validate_success(
            api.get_facility(universe.facility_id, universe.admin_headers)
        )
        assert facility["ccn"] == TEST_DEFAULTS["FACILITY_CCN"]
        period = validate_success(
            api.get_reporting_period(universe.period_id, universe.admin_headers)
        )
        assert period["period_code"] == TEST_DEFAULTS["PERIOD_CODE"]
        assert period["status"] == ReportingPeriodStatus.OPEN.value
        job_category = validate_success(
            api.get_job_category(universe.jc_rn["id"], universe.admin_headers)
        )
        assert job_category["code"] == "RN"

        validated = scenario.validate()
        assert validated["status"] == SubmissionStatus.VALIDATED.value
        assert validated["validated_by_worker_id"] == universe.w_coord["id"]

        submitted = scenario.submit()
        assert submitted["status"] == SubmissionStatus.SUBMITTED.value
        assert submitted["attested_by_worker_id"] == universe.w_admin["id"]

        accepted = scenario.accept()
        assert accepted["status"] == SubmissionStatus.ACCEPTED.value
        assert accepted["audit_support_score"] == approx_score(100.00)

        measure = MeasureScenario(scenario)
        assert measure.measure["staffing_rating"] == 1
        published = measure.publish()
        assert published["publication_status"] == PublicationStatus.PUBLISHED.value

        appeal = AppealScenario(measure)
        assert appeal.appeal["status"] == AppealStatus.SUBMITTED.value
        assert appeal.appeal["filed_by_worker_id"] == universe.w_admin["id"]
        denied = appeal.deny(DENIAL_NOTE)
        assert denied["status"] == AppealStatus.DENIED.value

        batch = vendor.submit_batch()
        assert batch["status"] == VendorSubmissionStatus.SUBMITTED.value


class TestNoRoleReachesAnothersOperation:
    def test_01_peer_roles_are_partitioned_with_no_hierarchical_override(
        self,
        api,
        submitted_quarter,
        cms_publisher_headers,
        accepting_auditor_headers,
        appeals_reviewer_headers,
    ):
        """PRD: "If the role is recognised but is not among the roles listed for the
        target endpoint in §4, the request is rejected with `ERR_FORBIDDEN_ROLE`." PRD:
        "3. The acting role is listed for the target endpoint — otherwise
        `ERR_FORBIDDEN_ROLE`." PRD: "18. The target submission is in a status the
        requested operation accepts". PRD: "`AppealsReviewer` is an independent reviewer
        that grants or denies rating appeals; it may not compute, publish, or audit
        measures."

        Design: Corner/rbac/a_role_cannot_perform_another_roles_exclusive_operation
        """
        scenario = submitted_quarter
        universe = scenario.universe
        other_vendor = validate_success(
            api.create_vendor(
                create_vendor_payload(universe.facility_id), universe.admin_headers
            ),
            expected_status=201,
        )
        version_before = scenario.refresh()["version"]

        probes = [
            api.accept_submission(scenario.id, cms_publisher_headers),
            api.validate_submission(scenario.id, accepting_auditor_headers),
            api.create_hour_entry(
                create_hour_entry_payload(
                    scenario.id,
                    universe.w_rn["id"],
                    universe.jc_rn["id"],
                    version_before,
                    work_date="2026-04-08",
                ),
                universe.fac_admin_headers,
            ),
            api.create_staffing_measure(
                create_staffing_measure_payload(scenario.id), appeals_reviewer_headers
            ),
            api.list_facilities(
                make_vendor_representative_headers(other_vendor["id"]),
                {"state_code": TEST_DEFAULTS["FACILITY_STATE_CODE"]},
            ),
        ]
        for response in probes:
            validate_error(
                response, ApiErrorId.ERR_FORBIDDEN_ROLE.value, expected_status=403
            )

        after = scenario.refresh()
        assert after["status"] == SubmissionStatus.SUBMITTED.value
        assert after["version"] == version_before

        _, hour_meta = validate_paginated(
            api.list_hour_entries(
                universe.coord_headers, {"submission_id": scenario.id}
            )
        )
        assert hour_meta["total_count"] == 1
        _, measure_meta = validate_paginated(
            api.list_staffing_measures(
                cms_publisher_headers, {"submission_id": scenario.id}
            )
        )
        assert measure_meta["total_count"] == 0


class TestWorkerIdentityGates:
    def test_01_the_header_role_is_not_enough_for_a_worker_backed_identity(
        self, api, draft_submission
    ):
        """PRD: "the acting `Worker`'s `authorized_roles` array must contain the acting
        role name — the array holds the literal strings `STAFFING_COORDINATOR` and
        `FACILITY_ADMINISTRATOR` — and if it does not, the request is rejected with
        `ERR_WORKER_ROLE_NOT_AUTHORIZED`. Second, the acting `Worker`'s `status` must be
        `ACTIVE`; a `TERMINATED` worker is rejected with `ERR_ACTOR_INACTIVE`." PRD:
        "Terminating a worker moves `status` to `TERMINATED`, after which that identity is
        refused with `ERR_ACTOR_INACTIVE`."

        Design: Corner/rbac/unauthorized_or_terminated_worker_cannot_act
        """
        scenario = draft_submission
        universe = scenario.universe
        scenario.report_census("2026-04-01", 5, 5)

        unauthorized = api.validate_submission(
            scenario.id, make_staffing_coordinator_headers(universe.w_rn["id"])
        )
        validate_error(
            unauthorized,
            ApiErrorId.ERR_WORKER_ROLE_NOT_AUTHORIZED.value,
            expected_status=403,
        )
        assert universe.w_rn["authorized_roles"] == []

        terminated = validate_success(
            api.terminate_worker(universe.w_coord["id"], universe.admin_headers)
        )
        assert terminated["status"] == WorkerStatus.TERMINATED.value

        inactive = api.validate_submission(scenario.id, universe.coord_headers)
        validate_error(
            inactive, ApiErrorId.ERR_ACTOR_INACTIVE.value, expected_status=403
        )
        assert AuthorizedRole.STAFFING_COORDINATOR.value in (
            universe.w_coord["authorized_roles"]
        )

        after = validate_success(
            api.get_submission(scenario.id, universe.admin_headers)
        )
        assert after["status"] == SubmissionStatus.DRAFT.value
        assert after["validated_by_worker_id"] is None


class TestScopeIsCheckedAgainstTheTargetRow:
    def test_01_a_foreign_facility_worker_and_a_foreign_vendor_are_both_refused(
        self, api, draft_submission
    ):
        """PRD: "On any write, the acting `Worker`'s `facility_id` must equal the
        `facility_id` of the target resource, or of the target resource's parent
        submission when the target is nested beneath one; a mismatch is rejected with
        `ERR_FACILITY_SCOPE_VIOLATION`. For a `VendorRepresentative` acting on batch
        creation, batch submission, or batch revocation, an `X-User-ID` that does not match
        the batch's owning vendor is rejected with `ERR_VENDOR_SCOPE_VIOLATION`."

        Design: Corner/rbac/cross_facility_and_cross_vendor_actors_cannot_reach_foreign_rows
        """
        scenario = draft_submission
        universe = scenario.universe
        scenario.report_census("2026-04-01", 5, 5)
        version_before_refusals = scenario.refresh()["version"]
        vendor = VendorScenario(universe)
        vendor.file_batch([vendor.batch_line("2026-04-06")])

        other_facility = universe.register_facility(
            ccn=TEST_DEFAULTS["SECOND_FACILITY_CCN"],
            name=TEST_DEFAULTS["SECOND_FACILITY_NAME"],
            certified_bed_count=TEST_DEFAULTS["SECOND_FACILITY_BED_COUNT"],
        )
        foreign_coordinator = universe.register_worker(
            other_facility["id"],
            universe.jc_admin["id"],
            full_name=FOREIGN_COORDINATOR_NAME,
            authorized_roles=[AuthorizedRole.STAFFING_COORDINATOR.value],
        )
        second_vendor = validate_success(
            api.create_vendor(
                create_vendor_payload(
                    universe.facility_id,
                    vendor_name=SECOND_VENDOR_NAME,
                    tax_id=SECOND_VENDOR_TAX_ID,
                    attestation_contact=SECOND_VENDOR_CONTACT,
                ),
                universe.admin_headers,
            ),
            expected_status=201,
        )

        foreign_validate = api.validate_submission(
            scenario.id, make_staffing_coordinator_headers(foreign_coordinator["id"])
        )
        validate_error(
            foreign_validate,
            ApiErrorId.ERR_FACILITY_SCOPE_VIOLATION.value,
            expected_status=403,
        )
        assert foreign_coordinator["facility_id"] == other_facility["id"]

        cross_vendor_submit = api.submit_vendor_submission(
            vendor.batch["id"],
            make_vendor_representative_headers(second_vendor["id"]),
        )
        validate_error(
            cross_vendor_submit,
            ApiErrorId.ERR_VENDOR_SCOPE_VIOLATION.value,
            expected_status=403,
        )

        after = scenario.refresh()
        assert after["status"] == SubmissionStatus.DRAFT.value
        assert after["version"] == version_before_refusals
        batch = vendor.refresh()
        assert batch["status"] == VendorSubmissionStatus.DRAFT.value
        assert batch["vendor_id"] == vendor.vendor_id


class TestSegregationOfDuties:
    def test_01_neither_separated_duty_may_be_taken_twice_by_one_identity(
        self, api, client
    ):
        """PRD: "The `Worker` who ran the validation pass may not be the `Worker` who
        attests and submits the quarter, and the `StateAuditor` identity that verified any
        hour of a submission may not be the identity that accepts that submission." PRD:
        "9. On attestation of a quarter, the acting `Worker`'s `id` differs from the
        submission's `validated_by_worker_id` — otherwise `ERR_SEGREGATION_OF_DUTIES`. 10.
        On acceptance of a quarter, the acting `X-User-ID` differs from
        `verified_by_user_id` on every hour entry of that submission — otherwise
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/segregation_of_duties_separates_validation_attestation_and_acceptance
        """
        scenario = build_supported_quarter(client)
        universe = scenario.universe
        dual_worker = universe.register_worker(
            universe.facility_id,
            universe.jc_admin["id"],
            full_name=DUAL_ROLE_WORKER_NAME,
            authorized_roles=[
                AuthorizedRole.STAFFING_COORDINATOR.value,
                AuthorizedRole.FACILITY_ADMINISTRATOR.value,
            ],
        )

        validated = validate_success(
            api.validate_submission(
                scenario.id, make_staffing_coordinator_headers(dual_worker["id"])
            )
        )
        assert validated["status"] == SubmissionStatus.VALIDATED.value
        assert validated["validated_by_worker_id"] == dual_worker["id"]

        self_attestation = api.submit_submission(
            scenario.id, make_facility_administrator_headers(dual_worker["id"])
        )
        validate_error(
            self_attestation,
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
            expected_status=403,
        )

        submitted = scenario.submit()
        assert submitted["status"] == SubmissionStatus.SUBMITTED.value
        assert submitted["attested_by_worker_id"] == universe.w_admin["id"]

        verifier_accept = api.accept_submission(
            scenario.id, make_state_auditor_headers(VERIFYING_AUDITOR_USER_ID)
        )
        validate_error(
            verifier_accept,
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
            expected_status=403,
        )

        accepted = scenario.accept()
        assert accepted["status"] == SubmissionStatus.ACCEPTED.value
        assert accepted["accepted_by_user_id"] == ACCEPTING_AUDITOR_USER_ID
