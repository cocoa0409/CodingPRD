"""Role authorisation: what each of the six roles may do, and may not do.

Each positive case drives one role through the operations §2.1 and §4 reserve to
it, plus the operations it shares, and checks the state each one leaves behind.
The final case replays the exclusive operations from the wrong role.
"""

import pytest
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ABSENT_UUID,
    CLOCK_2026_08_20,
    CLOCK_2026_10_01,
    CLOCK_2026_10_05,
    CLOCK_2027_12_20,
    TEST_USERS,
    ApiErrorId,
    accept_as_officer,
    accept_cure_plan,
    api_client,
    application_version,
    assemble_funding_plan,
    complete_visit_payload,
    counter_payload,
    create_application_payload,
    create_parcel_payload,
    decide_amendment_payload,
    draft_amendment_payload,
    easement_version,
    engage_appraisal,
    engage_appraisal_payload,
    impervious_request_payload,
    issue_offer,
    issue_offer_payload,
    make_landowner_headers,
    open_violation_payload,
    parcel_version,
    patch_parcel_payload,
    rank_payload,
    rank_round,
    read_appraisal,
    read_application,
    read_easement,
    read_parcel,
    read_source,
    requirement_of_type,
    rescind_amendment_payload,
    run_sweep,
    schedule_visit_payload,
    set_clock,
    setup_certified_appraisal,
    setup_filed_application,
    setup_ranked_application,
    setup_recorded_easement,
    submit_appraisal,
    submit_appraisal_payload,
    submit_subordination_payload,
    submit_survey_payload,
    submit_title_payload,
    suspend_source_payload,
    verify_cure,
    withdrawal_payload,
)

ADMIN = TEST_USERS["program_admin_headers"]
OFFICER = TEST_USERS["acquisition_officer_headers"]
REVIEWER = TEST_USERS["appraisal_reviewer_headers"]
APPRAISER = TEST_USERS["appraiser_headers"]
APPRAISER_ALT = TEST_USERS["appraiser_alt_headers"]
MONITOR = TEST_USERS["stewardship_monitor_headers"]
LANDOWNER_UNBOUND = TEST_USERS["landowner_headers"]


class TestProgramAdminAuthority:
    """The program authority: parcel maintenance, the amendment lifecycle,
    source suspension and the sweep."""

    def test_the_admin_drives_the_whole_amendment_lifecycle_and_the_sweep(self):
        """Patch, draft, submit, approve, rescind, suspend, sweep and set the clock.

        PRD §2.1: "`ProgramAdmin` is the program authority. It configures
        programs, funding rounds and funding sources; maintains parcel
        attributes; assembles funding plans; reviews and waives closing
        requirements; records easements; cancels closings; and drafts, submits,
        decides, reinstates and rescinds amendments."

        Design: Corner/rbac/program_admin_can_perform_its_exclusive_writes_and_its_shared_operations
        """
        scenario = setup_recorded_easement()
        easement_id = scenario["easement"]["id"]
        parcel_id = scenario["parcel"]["id"]

        # Parcel maintenance is the admin's alone, and contiguity grows as
        # neighbouring land is preserved.
        before_patch = parcel_version(parcel_id)
        patched = validate_success(
            api_client.patch_parcel(
                parcel_id,
                patch_parcel_payload(
                    before_patch, contiguous_preserved_acres=100.00
                ),
                ADMIN,
            )
        )
        assert patched["contiguous_preserved_acres"] == pytest.approx(100.00, abs=0.01)
        assert patched["version"] == before_patch + 1

        drafted = validate_success(
            api_client.draft_amendment(
                easement_id,
                draft_amendment_payload(
                    easement_version(easement_id),
                    amendment_type="BOUNDARY_ADJUSTMENT",
                    net_conservation_benefit_cents=300_000,
                ),
                ADMIN,
            ),
            201,
        )
        amendment_id = drafted["id"]
        assert drafted["status"] == "DRAFT"

        submitted = validate_success(api_client.submit_amendment(amendment_id, ADMIN))
        assert submitted["status"] == "UNDER_REVIEW"

        approved = validate_success(
            api_client.decide_amendment(
                amendment_id, decide_amendment_payload("APPROVE"), ADMIN
            )
        )
        assert approved["status"] == "APPROVED"
        amended = read_easement(easement_id)
        assert amended["status"] == "AMENDED"
        assert amended["amendment_count"] == 1

        reason = "boundary line re-surveyed, amendment no longer needed"
        rescinded = validate_success(
            api_client.rescind_amendment(
                amendment_id, rescind_amendment_payload(reason), ADMIN
            )
        )
        assert rescinded["status"] == "RESCINDED"
        assert rescinded["rescission_reason"] == reason
        reversed_easement = read_easement(easement_id)
        # `amendment_count` back at 0 returns the deed dimension to RECORDED.
        assert reversed_easement["amendment_count"] == 0
        assert reversed_easement["status"] == "RECORDED"

        state_source_id = scenario["sources"]["state"]["id"]
        suspended = validate_success(
            api_client.suspend_funding_source(
                state_source_id,
                suspend_source_payload("state appropriation frozen mid-year"),
                ADMIN,
            )
        )
        assert suspended["status"] == "SUSPENDED"
        assert suspended["suspension_reason"] == "state appropriation frozen mid-year"
        # Suspension is a status change only: the money already disbursed at
        # closing stays disbursed.
        assert suspended["disbursed_cents"] == 64_145_970

        metered = validate_success(
            api_client.record_impervious_request(
                easement_id,
                impervious_request_payload(500, "gravel apron at the existing barn"),
                ADMIN,
            )
        )
        assert metered["impervious_used_sqft"] == 500

        # Opening a violation is shared with the StewardshipMonitor.
        opened = validate_success(
            api_client.open_violation(
                open_violation_payload(
                    easement_id,
                    violation_type="PROHIBITED_USE",
                    notes="equipment rental yard observed from the road",
                ),
                ADMIN,
            ),
            201,
        )
        assert opened["status"] == "OPEN"

        swept = run_sweep(ADMIN)
        # The round's only application closed, so nothing on it is still live.
        assert swept["closed_round_count"] == 1
        assert swept["terminated_easement_count"] == 0

        moved = validate_success(api_client.set_clock("2026-12-20T00:00:00Z", ADMIN))
        assert moved["previous_utc"].startswith("2026-12-15")
        assert moved["current_utc"].startswith("2026-12-20")

        _, easement_meta = validate_paginated(
            api_client.list_easements(ADMIN, {"parcel_id": parcel_id})
        )
        assert easement_meta["total_count"] == 1
        _, round_meta = validate_paginated(
            api_client.list_funding_rounds(
                ADMIN, {"program_id": scenario["program"]["id"], "status": "CLOSED"}
            )
        )
        assert round_meta["total_count"] == 1


class TestAcquisitionOfficerAuthority:
    """The negotiator: offers, requirement packages and acceptance from
    `COUNTERED`."""

    def test_the_officer_offers_then_accepts_the_standing_counter(self):
        """One offer, one counter, one plan and the officer's own acceptance.

        PRD §2.1: "`AcquisitionOfficer` is the negotiator. It engages
        appraisers, issues offers, accepts standing counters and submits
        closing-requirement packages."

        Design: Corner/rbac/acquisition_officer_can_perform_its_exclusive_writes_and_the_shared_acceptance_from_countered
        """
        scenario = setup_ranked_application()
        application_id = scenario["application"]["id"]
        landowner_id = scenario["landowner"]["id"]
        set_clock(CLOCK_2026_10_05)

        offered = validate_success(
            api_client.issue_offer(
                application_id,
                issue_offer_payload(
                    application_version(application_id),
                    170_000_000,
                    "FULL_PURCHASE",
                    offer_expires_on="2026-11-19T00:00:00Z",
                ),
                OFFICER,
            )
        )
        assert offered["status"] == "OFFER_ISSUED"
        assert offered["negotiation_round_count"] == 1
        # 170,000,000 cash, admin fee at the 1.5 percent tier: 2,550,000.
        assert offered["total_program_cost_cents"] == 172_550_000

        countered = validate_success(
            api_client.file_counter(
                application_id,
                counter_payload(
                    172_000_000,
                    rationale="neighbouring sale supports a higher easement value",
                ),
                make_landowner_headers(landowner_id),
            )
        )
        assert countered["status"] == "COUNTERED"
        assert countered["last_counter_cents"] == 172_000_000
        assert countered["total_program_cost_cents"] == 174_580_000

        plan = assemble_funding_plan(application_id)
        assert plan["commitment_count"] == 3
        assert plan["funded_cost_cents"] == 174_580_000

        accepted = accept_as_officer(application_id)
        assert accepted["status"] == "ACCEPTED"
        # From COUNTERED the price locked is `last_counter_cents`.
        assert accepted["agreed_price_cents"] == 172_000_000
        assert accepted["closing_status"] == "PENDING_REQUIREMENTS"
        assert accepted["requirement_total"] == 3
        assert accepted["funding_plan_status"] == "OBLIGATED"

        for requirement_type, payload in (
            ("TITLE_COMMITMENT", submit_title_payload(0)),
            ("MORTGAGE_SUBORDINATION", submit_subordination_payload()),
            ("BOUNDARY_SURVEY", submit_survey_payload(160.00)),
        ):
            requirement = requirement_of_type(application_id, requirement_type)
            submitted = validate_success(
                api_client.submit_closing_requirement(
                    requirement["id"], payload, OFFICER
                )
            )
            assert submitted["status"] == "SUBMITTED"

        commitments, commitment_meta = validate_paginated(
            api_client.list_funding_commitments(
                OFFICER, {"application_id": application_id}
            )
        )
        assert commitment_meta["total_count"] == 3
        assert {row["status"] for row in commitments} == {"OBLIGATED"}

        # The LOCAL appropriation was drawn to its full 60,000,000, at or above
        # floor(60,000,000 x 0.95) = 57,000,000.
        assert read_source(scenario["sources"]["local"]["id"])["status"] == (
            "FULLY_OBLIGATED"
        )

        validate_success(api_client.set_clock("2026-10-06T00:00:00Z", OFFICER))


class TestAppraiserOwnership:
    """The one opaque role that also carries an ownership gate."""

    def test_only_the_nominated_appraiser_may_submit(self):
        """A second appraiser is refused; the engaged one submits.

        PRD §2.1: "The `Appraiser` role is the one opaque role that also carries
        an ownership gate: an appraisal submission requires `X-User-ID` to equal
        the `appraiser_user_id` nominated on that appraisal when it was engaged,
        and a mismatch is likewise `ERR_NOT_RESOURCE_OWNER`."

        Design: Corner/rbac/appraiser_can_submit_only_the_appraisal_it_is_engaged_on
        """
        scenario = setup_filed_application()
        application_id = scenario["application"]["id"]
        appraisal = engage_appraisal(application_id, appraiser_user_id="appraiser-1")
        appraisal_id = appraisal["id"]
        set_clock(CLOCK_2026_08_20)

        engaged = validate_success(api_client.get_appraisal(appraisal_id, APPRAISER))
        assert engaged["status"] == "ASSIGNED"
        assert engaged["appraiser_user_id"] == "appraiser-1"

        intruder = api_client.submit_appraisal(
            appraisal_id,
            submit_appraisal_payload(288_000_000, 112_450_000),
            APPRAISER_ALT,
        )
        validate_error(intruder, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)
        assert read_appraisal(appraisal_id)["status"] == "ASSIGNED"

        submitted = validate_success(
            api_client.submit_appraisal(
                appraisal_id,
                submit_appraisal_payload(288_000_000, 112_450_000),
                APPRAISER,
            )
        )
        assert submitted["status"] == "SUBMITTED"
        assert submitted["submission_count"] == 1

        rows, meta = validate_paginated(
            api_client.list_appraisals(
                application_id, APPRAISER, {"status": "SUBMITTED"}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == appraisal_id

        validate_success(api_client.set_clock("2026-08-21T00:00:00Z", APPRAISER))


class TestAppraisalReviewerIndependence:
    """The reviewer is a third identifier, distinct from both the officer and
    the appraiser."""

    def test_a_third_party_reviewer_certifies_and_stamps_the_application(self):
        """The certification is the cross-entity effect that unlocks negotiation.

        PRD §2.9: "An appraisal review must be performed by a user who is
        neither the officer who engaged the appraisal nor the appraiser who
        submitted it: `X-User-ID` must differ from both `engaged_by_user_id` and
        `appraiser_user_id` on that appraisal, otherwise the review is rejected
        with `ERR_APPRAISAL_REVIEW_SOD`."

        Design: Corner/rbac/appraisal_reviewer_can_certify_an_appraisal_it_neither_engaged_nor_performed
        """
        scenario = setup_filed_application()
        application_id = scenario["application"]["id"]
        appraisal = engage_appraisal(application_id, appraiser_user_id="appraiser-1")
        appraisal_id = appraisal["id"]
        set_clock(CLOCK_2026_08_20)
        submit_appraisal(appraisal_id)

        pending = validate_success(api_client.get_appraisal(appraisal_id, REVIEWER))
        assert pending["status"] == "SUBMITTED"
        assert pending["engaged_by_user_id"] == "officer-1"
        assert pending["appraiser_user_id"] == "appraiser-1"

        note = "paired sales adequately support the restricted value"
        certified = validate_success(
            api_client.review_appraisal(
                appraisal_id, {"decision": "CERTIFY", "review_note": note}, REVIEWER
            )
        )
        assert certified["status"] == "CERTIFIED"
        assert certified["certified_by_user_id"] == "reviewer-1"
        assert certified["easement_value_cents"] == 175_550_000

        assert (
            read_application(application_id, REVIEWER)[
                "certified_easement_value_cents"
            ]
            == 175_550_000
        )
        # The reviewer's read surface reaches the parcel too.
        assert read_parcel(scenario["parcel"]["id"], REVIEWER)["status"] == (
            "UNDER_APPLICATION"
        )

        validate_success(api_client.set_clock("2026-08-22T00:00:00Z", REVIEWER))


class TestStewardshipMonitorAuthority:
    """Stewardship staff: visits, violations, cure plans and cures."""

    def test_the_monitor_runs_one_full_stewardship_year(self):
        """Schedule, complete, open, cure, re-schedule, cancel and meter.

        PRD §2.1: "`StewardshipMonitor` is stewardship staff: it schedules,
        completes and cancels monitoring visits, opens violations, accepts cure
        plans and verifies cures."

        Design: Corner/rbac/stewardship_monitor_can_perform_its_exclusive_stewardship_writes_and_the_shared_ones
        """
        scenario = setup_recorded_easement()
        easement_id = scenario["easement"]["id"]
        set_clock(CLOCK_2027_12_20)

        # The sweep is shared with the ProgramAdmin.
        swept = run_sweep(MONITOR)
        assert swept["due_count"] == 1
        assert swept["closed_round_count"] == 1
        assert read_easement(easement_id)["stewardship_status"] == "MONITORING_DUE"

        first_visit = validate_success(
            api_client.schedule_monitoring_visit(
                schedule_visit_payload(
                    easement_id,
                    window_start="2027-12-20T00:00:00Z",
                    window_end="2027-12-27T00:00:00Z",
                ),
                MONITOR,
            ),
            201,
        )
        assert first_visit["status"] == "SCHEDULED"

        completed = validate_success(
            api_client.complete_monitoring_visit(
                first_visit["id"],
                complete_visit_payload(
                    100, notes="barn apron only; no new construction"
                ),
                MONITOR,
            )
        )
        assert completed["status"] == "COMPLETED"
        assert completed["finding"] == "NO_ISSUE"
        rebased = read_easement(easement_id)
        assert rebased["stewardship_status"] == "MONITORING_CURRENT"
        # The anchor moves to the completion date, plus the 365-day interval.
        assert rebased["next_monitoring_due_on"].startswith("2028-12-19")

        violation = validate_success(
            api_client.open_violation(
                open_violation_payload(
                    easement_id,
                    violation_type="PROHIBITED_USE",
                    monitoring_visit_id=first_visit["id"],
                    notes="commercial storage yard behind the barn",
                ),
                MONITOR,
            ),
            201,
        )
        assert violation["status"] == "OPEN"
        assert violation["severity"] == "MINOR"
        # A MINOR violation gets the 180-day cure window.
        assert violation["cure_deadline_on"].startswith("2028-06-17")
        held = read_easement(easement_id)
        assert held["compliance_status"] == "VIOLATION_OPEN"
        assert held["stewardship_hold"] is True

        planned = accept_cure_plan(
            violation["id"], cure_plan_note="yard to be removed within 60 days"
        )
        assert planned["status"] == "CURE_PLAN_ACCEPTED"

        cured = verify_cure(
            violation["id"], verification_note="site re-walked, yard removed"
        )
        assert cured["status"] == "CURED"
        assert cured["cured_on"].startswith("2027-12-20")
        released = read_easement(easement_id)
        assert released["compliance_status"] == "VIOLATION_CURED"
        assert released["stewardship_hold"] is False
        assert released["open_violation_count"] == 0

        # Only possible because the cure released the hold.
        second_visit = validate_success(
            api_client.schedule_monitoring_visit(
                schedule_visit_payload(
                    easement_id,
                    window_start="2028-01-05T00:00:00Z",
                    window_end="2028-01-12T00:00:00Z",
                ),
                MONITOR,
            ),
            201,
        )
        cancelled = validate_success(
            api_client.cancel_monitoring_visit(
                second_visit["id"], {"reason": "access lane impassable"}, MONITOR
            )
        )
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancellation_reason"] == "access lane impassable"

        metered = validate_success(
            api_client.record_impervious_request(
                easement_id,
                impervious_request_payload(500, "gravel pad beside the barn"),
                MONITOR,
            )
        )
        assert metered["impervious_used_sqft"] == 500

        # Nothing is outstanding at this clock reading, so a second sweep is inert.
        again = run_sweep(MONITOR)
        for counter in (
            "due_count",
            "delinquent_count",
            "cleared_to_compliant_count",
            "terminated_easement_count",
            "lapsed_offer_count",
            "escalated_violation_count",
            "expired_source_count",
            "closed_round_count",
        ):
            assert again[counter] == 0

        _, cured_meta = validate_paginated(
            api_client.list_easement_violations(
                easement_id, MONITOR, {"status": "CURED"}
            )
        )
        assert cured_meta["total_count"] == 1
        _, visit_meta = validate_paginated(
            api_client.list_monitoring_visits(easement_id, MONITOR)
        )
        assert visit_meta["total_count"] == 2
        _, amendment_meta = validate_paginated(
            api_client.list_easement_amendments(easement_id, MONITOR)
        )
        assert amendment_meta["total_count"] == 0


class TestLandownerAuthority:
    """The applicant: registration, filing, countering, accepting, withdrawing."""

    def test_the_landowner_registers_files_withdraws_counters_and_accepts(self):
        """Two parcels, one withdrawn application and one accepted counter.

        PRD §2.1: "`Landowner` is the applicant. It registers parcels, files
        applications, counters offers, accepts standing offers and withdraws."

        Design: Corner/rbac/landowner_can_perform_its_exclusive_writes_and_the_shared_ones
        """
        scenario = setup_filed_application()
        application_a = scenario["application"]["id"]
        landowner_id = scenario["landowner"]["id"]
        landowner = make_landowner_headers(landowner_id)
        setup_certified_appraisal(application_a)

        extra_parcel = validate_success(
            api_client.create_parcel(
                create_parcel_payload(
                    landowner_id,
                    county="Berks",
                    acres=80.00,
                    prime_soil_acres=72.00,
                    statewide_important_soil_acres=8.00,
                    contiguous_preserved_acres=60.00,
                    road_frontage_feet=400,
                    sewer_available=True,
                    zoning_min_lot_acres=1.5,
                    baseline_dwelling_rights=3,
                    unrestricted_value_cents=120_000_000,
                    restricted_value_cents=45_500_000,
                ),
                landowner,
            ),
            201,
        )
        assert extra_parcel["status"] == "ELIGIBLE"
        # 72/80 prime plus 8/80 important at 0.60 gives 0.96.
        assert extra_parcel["soil_quality_score"] == pytest.approx(96.00, abs=0.01)
        # Four whole frontage units at 3, plus 25 for sewer, plus 35 for zoning
        # under 3 acres.
        assert extra_parcel["development_pressure_score"] == pytest.approx(
            72.00, abs=0.01
        )

        extra_application = validate_success(
            api_client.create_application(
                create_application_payload(
                    scenario["round"]["id"],
                    extra_parcel["id"],
                    landowner_id,
                    requested_price_cents=60_000_000,
                ),
                landowner,
            ),
            201,
        )
        assert extra_application["status"] == "RECEIVED"
        assert read_parcel(extra_parcel["id"])["status"] == "UNDER_APPLICATION"

        withdrawn = validate_success(
            api_client.withdraw_application(
                extra_application["id"],
                withdrawal_payload(
                    "family decided to keep development options on the Berks parcel"
                ),
                landowner,
            )
        )
        assert withdrawn["status"] == "WITHDRAWN"
        assert read_parcel(extra_parcel["id"])["status"] == "ELIGIBLE"

        ranked = rank_round(scenario["round"]["id"], clock=CLOCK_2026_10_01)
        # The withdrawn application is excluded from the pass entirely.
        assert ranked["ranked_count"] == 1
        assert ranked["ranked_application_ids"] == [application_a]

        set_clock(CLOCK_2026_10_05)
        issue_offer(application_a, 170_000_000, "FULL_PURCHASE")

        countered = validate_success(
            api_client.file_counter(
                application_a,
                counter_payload(
                    172_000_000,
                    rationale="a comparable easement sold higher this spring",
                ),
                landowner,
            )
        )
        assert countered["status"] == "COUNTERED"
        assert countered["last_counter_cents"] == 172_000_000

        reoffered = issue_offer(application_a, 172_000_000, "FULL_PURCHASE")
        assert reoffered["status"] == "OFFER_ISSUED"
        assert reoffered["negotiation_round_count"] == 2
        assert reoffered["total_program_cost_cents"] == 174_580_000

        plan = assemble_funding_plan(application_a)
        assert plan["funded_cost_cents"] == 174_580_000
        assert plan["commitment_count"] == 3

        accepted = validate_success(
            api_client.accept_application(application_a, landowner)
        )
        assert accepted["status"] == "ACCEPTED"
        # From OFFER_ISSUED the price locked is `current_offer_cents`.
        assert accepted["agreed_price_cents"] == 172_000_000

        log, log_meta = validate_paginated(
            api_client.list_negotiation_rounds(application_a, landowner)
        )
        assert log_meta["total_count"] == 4
        assert [entry["kind"] for entry in log] == [
            "OFFER",
            "COUNTER",
            "OFFER",
            "ACCEPTANCE",
        ]

        requirements, requirement_meta = validate_paginated(
            api_client.list_closing_requirements(application_a, landowner)
        )
        assert requirement_meta["total_count"] == 3
        assert {row["status"] for row in requirements} == {"OUTSTANDING"}

        validate_success(api_client.set_clock("2026-10-13T00:00:00Z", landowner))


class TestForbiddenRoles:
    """Every exclusive operation, replayed from a role the table does not list."""

    def test_no_role_may_perform_another_roles_exclusive_operation(self):
        """Twenty-two wrong-role attempts, all refused before anything else runs.

        PRD §2.1: "If the headers are well formed but the named role is not
        authorised for the endpoint per the table in §4, the request is rejected
        with `ERR_FORBIDDEN_ROLE` (403)."

        Design: Corner/rbac/every_role_cannot_perform_the_other_roles_exclusive_operations
        """
        scenario = setup_filed_application()
        application_id = scenario["application"]["id"]
        parcel_id = scenario["parcel"]["id"]
        round_id = scenario["round"]["id"]
        landowner = make_landowner_headers(scenario["landowner"]["id"])
        appraisal = engage_appraisal(application_id, appraiser_user_id="appraiser-1")
        set_clock(CLOCK_2026_08_20)
        parcel_before = parcel_version(parcel_id)

        attempts = [
            api_client.create_program({}, OFFICER),
            api_client.create_funding_round({}, landowner),
            api_client.rank_funding_round(round_id, rank_payload(), MONITOR),
            api_client.create_landowner({}, landowner),
            api_client.patch_parcel(parcel_id, patch_parcel_payload(1), landowner),
            api_client.create_funding_source({}, OFFICER),
            api_client.suspend_funding_source(
                scenario["sources"]["local"]["id"], suspend_source_payload(), MONITOR
            ),
            api_client.create_application({}, ADMIN),
            api_client.file_counter(
                application_id, counter_payload(180_000_000), OFFICER
            ),
            api_client.withdraw_application(
                application_id, withdrawal_payload(), ADMIN
            ),
            api_client.issue_offer(
                application_id, issue_offer_payload(1, 170_000_000), ADMIN
            ),
            api_client.engage_appraisal(
                application_id, engage_appraisal_payload(), REVIEWER
            ),
            api_client.assemble_funding_plan(application_id, {}, landowner),
            api_client.record_closing(application_id, {}, OFFICER),
            api_client.submit_appraisal(appraisal["id"], {}, OFFICER),
            api_client.review_appraisal(appraisal["id"], {}, APPRAISER),
            api_client.submit_closing_requirement(ABSENT_UUID, {}, ADMIN),
            api_client.review_closing_requirement(ABSENT_UUID, {}, OFFICER),
            api_client.schedule_monitoring_visit({}, ADMIN),
            api_client.draft_amendment(ABSENT_UUID, {}, MONITOR),
            api_client.decide_amendment(ABSENT_UUID, {}, MONITOR),
            api_client.accept_cure_plan(ABSENT_UUID, {}, ADMIN),
        ]
        assert len(attempts) == 22
        for response in attempts:
            # The role gate sits above body parsing and above identifier
            # resolution, so an absent path id and an empty body still get 403.
            validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)

        # Nothing was created and nothing moved.
        _, parcel_meta = validate_paginated(api_client.list_parcels(ADMIN))
        assert parcel_meta["total_count"] == 1
        _, application_meta = validate_paginated(api_client.list_applications(ADMIN))
        assert application_meta["total_count"] == 1
        _, round_meta = validate_paginated(api_client.list_funding_rounds(ADMIN))
        assert round_meta["total_count"] == 1
        _, source_meta = validate_paginated(api_client.list_funding_sources(ADMIN))
        assert source_meta["total_count"] == 3

        assert read_application(application_id)["status"] == "RECEIVED"
        assert read_appraisal(appraisal["id"])["status"] == "ASSIGNED"
        assert parcel_version(parcel_id) == parcel_before
        assert read_source(scenario["sources"]["local"]["id"])["status"] == "ACTIVE"
        assert read_parcel(parcel_id)["status"] == "UNDER_APPLICATION"

        # A forbidden role never reaches the unauthenticated-role branch either.
        validate_error(
            api_client.create_program({}, LANDOWNER_UNBOUND),
            ApiErrorId.ERR_FORBIDDEN_ROLE.value,
            403,
        )
