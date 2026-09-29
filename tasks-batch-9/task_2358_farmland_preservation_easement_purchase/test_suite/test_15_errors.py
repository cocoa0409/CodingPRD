"""The error catalogue, triggered code by code on the paths that reach it.

Each case drives one family of failures to its own boundary and then shows the
adjacent success, so the code under test is the discriminating observation rather
than an incidental side effect.
"""

import pytest
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ABSENT_UUID,
    CLOCK_2026_10_01,
    CLOCK_2026_10_12,
    CLOCK_2026_12_15,
    CLOCK_2027_06_03,
    TEST_USERS,
    ApiErrorId,
    accept_cure_plan,
    api_client,
    commitments_of,
    create_application_payload,
    create_parcel_payload,
    create_program,
    cure_plan_payload,
    decide_amendment,
    decide_amendment_payload,
    draft_amendment,
    draft_amendment_payload,
    easement_version,
    impervious_request_payload,
    issue_offer_payload,
    list_requirements,
    make_landowner_headers,
    open_violation,
    rank_payload,
    read_application,
    read_easement,
    read_parcel,
    read_source,
    read_violation,
    record_closing,
    record_closing_payload,
    requirement_of_type,
    review_requirement_payload,
    run_sweep,
    satisfy_all_requirements,
    schedule_visit,
    schedule_visit_payload,
    set_clock,
    setup_accepted_application,
    setup_program_with_round,
    setup_recorded_easement,
    setup_two_applications_competing_for_headroom,
    submit_amendment,
    submit_and_accept_requirement,
    submit_appraisal_payload,
    submit_subordination_payload,
    submit_survey_payload,
    submit_title_payload,
    suspend_source_payload,
    cancel_visit,
    create_parcel,
    engage_appraisal_payload,
    review_appraisal_payload,
)

ADMIN = TEST_USERS["program_admin_headers"]
OFFICER = TEST_USERS["acquisition_officer_headers"]
REVIEWER = TEST_USERS["appraisal_reviewer_headers"]
APPRAISER = TEST_USERS["appraiser_headers"]
MONITOR = TEST_USERS["stewardship_monitor_headers"]


class TestNotFoundCodes:
    """Thirteen path families and two body foreign keys, each with its own code."""

    def test_every_path_identifier_reports_the_code_of_its_own_entity(self):
        """One absent id read against each resource family in turn.

        PRD §2.10: "Where a path is nested, identifiers are resolved strictly
        left to right and the response reports the first identifier that fails,
        using the not-found code belonging to that identifier's entity:
        `ERR_PROGRAM_NOT_FOUND`, `ERR_ROUND_NOT_FOUND`, `ERR_LANDOWNER_NOT_FOUND`,
        `ERR_PARCEL_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`,
        `ERR_APPRAISAL_NOT_FOUND`, `ERR_SOURCE_NOT_FOUND`,
        `ERR_COMMITMENT_NOT_FOUND`, `ERR_REQUIREMENT_NOT_FOUND`,
        `ERR_EASEMENT_NOT_FOUND`, `ERR_VISIT_NOT_FOUND`,
        `ERR_VIOLATION_NOT_FOUND` or `ERR_AMENDMENT_NOT_FOUND`, each with HTTP
        404."

        Design: Corner/errors/unknown_path_and_body_ids_each_return_their_own_not_found_code
        """
        # Only a program exists, so every identifier used below is genuinely absent.
        create_program()
        reads = [
            (api_client.get_program(ABSENT_UUID, ADMIN), "ERR_PROGRAM_NOT_FOUND"),
            (api_client.get_funding_round(ABSENT_UUID, ADMIN), "ERR_ROUND_NOT_FOUND"),
            (api_client.get_landowner(ABSENT_UUID, ADMIN), "ERR_LANDOWNER_NOT_FOUND"),
            (api_client.get_parcel(ABSENT_UUID, ADMIN), "ERR_PARCEL_NOT_FOUND"),
            (
                api_client.get_application(ABSENT_UUID, ADMIN),
                "ERR_APPLICATION_NOT_FOUND",
            ),
            (api_client.get_appraisal(ABSENT_UUID, ADMIN), "ERR_APPRAISAL_NOT_FOUND"),
            (api_client.get_funding_source(ABSENT_UUID, ADMIN), "ERR_SOURCE_NOT_FOUND"),
            (
                api_client.get_funding_commitment(ABSENT_UUID, ADMIN),
                "ERR_COMMITMENT_NOT_FOUND",
            ),
            (
                api_client.get_closing_requirement(ABSENT_UUID, ADMIN),
                "ERR_REQUIREMENT_NOT_FOUND",
            ),
            (api_client.get_easement(ABSENT_UUID, ADMIN), "ERR_EASEMENT_NOT_FOUND"),
            (
                api_client.get_monitoring_visit(ABSENT_UUID, MONITOR),
                "ERR_VISIT_NOT_FOUND",
            ),
            (api_client.get_violation(ABSENT_UUID, MONITOR), "ERR_VIOLATION_NOT_FOUND"),
            (api_client.get_amendment(ABSENT_UUID, ADMIN), "ERR_AMENDMENT_NOT_FOUND"),
        ]
        for response, expected in reads:
            validate_error(response, expected, 404)

    def test_a_body_foreign_key_reports_the_same_code_one_rung_later(self):
        """An absent `easement_id` and an absent `landowner_id` in request bodies.

        PRD §2.10: "Foreign keys supplied inside a request body are resolved the
        same way and with the same codes, one step later in the ladder: a
        `program_id` that names no program yields `ERR_PROGRAM_NOT_FOUND`, and
        likewise for `funding_round_id`, `parcel_id`, `landowner_id`,
        `easement_id` and `monitoring_visit_id`."

        Design: Corner/errors/unknown_path_and_body_ids_each_return_their_own_not_found_code
        """
        create_program()

        visit = api_client.schedule_monitoring_visit(
            schedule_visit_payload(ABSENT_UUID), MONITOR
        )
        validate_error(visit, ApiErrorId.ERR_EASEMENT_NOT_FOUND.value, 404)

        # A ProgramAdmin may register a parcel, so the role gate passes and the
        # body foreign key is reported ahead of the ownership check.
        parcel = api_client.create_parcel(create_parcel_payload(ABSENT_UUID), ADMIN)
        validate_error(parcel, ApiErrorId.ERR_LANDOWNER_NOT_FOUND.value, 404)

        _, meta = validate_paginated(api_client.list_parcels(ADMIN))
        assert meta["total_count"] == 0


class TestLifecycleConflictCodes:
    """Five state codes, each raised by repeating a transition already taken."""

    def test_a_second_attempt_at_a_completed_transition_reports_its_own_state_code(
        self,
    ):
        """Closing, visit, amendment, violation and source, in the forced order.

        PRD §2.11: "9. The subject row is in a state from which the requested
        transition exists — the state code for that entity and dimension."

        Design: Corner/errors/five_lifecycle_conflict_codes_fire_on_a_second_attempt_at_a_completed_transition
        """
        scenario = setup_accepted_application()
        application_id = scenario["application"]["id"]
        state_source_id = scenario["sources"]["state"]["id"]

        # Only CLEARED admits closing; the file is still PENDING_REQUIREMENTS.
        premature = api_client.record_closing(
            application_id,
            record_closing_payload(recorded_on=CLOCK_2026_10_12),
            ADMIN,
        )
        validate_error(premature, ApiErrorId.ERR_INVALID_CLOSING_STATE.value, 409)
        assert read_application(application_id)["closing_status"] == "PENDING_REQUIREMENTS"
        _, easement_meta = validate_paginated(api_client.list_easements(ADMIN))
        assert easement_meta["total_count"] == 0

        satisfy_all_requirements(application_id)
        set_clock(CLOCK_2026_12_15)
        easement = record_closing(application_id)
        easement_id = easement["id"]

        visit = schedule_visit(easement_id)
        assert visit["status"] == "SCHEDULED"
        cancelled = cancel_visit(visit["id"], "landowner rescheduled the site walk")
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancellation_reason"] == "landowner rescheduled the site walk"
        replayed_cancel = api_client.cancel_monitoring_visit(
            visit["id"], {"reason": "duplicate cancellation"}, MONITOR
        )
        validate_error(replayed_cancel, ApiErrorId.ERR_INVALID_VISIT_STATE.value, 409)
        assert (
            validate_success(api_client.get_monitoring_visit(visit["id"], MONITOR))[
                "cancellation_reason"
            ]
            == "landowner rescheduled the site walk"
        )

        # The amendment must reach UNDER_REVIEW before the violation opens,
        # because an open violation suspends it.
        amendment = draft_amendment(easement_id, amendment_type="BOUNDARY_ADJUSTMENT")
        assert amendment["status"] == "DRAFT"
        assert submit_amendment(amendment["id"])["status"] == "UNDER_REVIEW"
        early_reinstate = api_client.reinstate_amendment(amendment["id"], ADMIN)
        validate_error(early_reinstate, ApiErrorId.ERR_INVALID_AMENDMENT_STATE.value, 409)
        assert (
            validate_success(api_client.get_amendment(amendment["id"], ADMIN))["status"]
            == "UNDER_REVIEW"
        )

        violation = open_violation(
            easement_id,
            violation_type="PROHIBITED_USE",
            notes="commercial equipment storage yard observed",
        )
        assert violation["status"] == "OPEN"
        assert violation["severity"] == "MINOR"
        # 2026-12-15 advanced by the 180-day minor cure window.
        assert violation["cure_deadline_on"].startswith("2027-06-13")
        held = read_easement(easement_id)
        assert held["compliance_status"] == "VIOLATION_OPEN"
        assert held["stewardship_hold"] is True
        suspended = validate_success(api_client.get_amendment(amendment["id"], ADMIN))
        assert suspended["status"] == "SUSPENDED"
        assert suspended["suspended_reason"] == "VIOLATION_OPEN"

        planned = accept_cure_plan(
            violation["id"], cure_plan_note="yard to be removed and reseeded"
        )
        assert planned["status"] == "CURE_PLAN_ACCEPTED"
        replayed_plan = api_client.accept_cure_plan(
            violation["id"], cure_plan_payload("second plan filed in error"), MONITOR
        )
        validate_error(replayed_plan, ApiErrorId.ERR_INVALID_VIOLATION_STATE.value, 409)
        assert (
            read_violation(violation["id"])["cure_plan_note"]
            == "yard to be removed and reseeded"
        )

        suspension = validate_success(
            api_client.suspend_funding_source(
                state_source_id, suspend_source_payload("state appropriation frozen"), ADMIN
            )
        )
        assert suspension["status"] == "SUSPENDED"
        replayed_suspension = api_client.suspend_funding_source(
            state_source_id, suspend_source_payload("duplicate suspension"), ADMIN
        )
        validate_error(replayed_suspension, ApiErrorId.ERR_INVALID_SOURCE_STATE.value, 409)
        # Every commitment was already DISBURSED, so the suspension lapsed nothing.
        assert read_application(application_id)["funding_plan_status"] == "DISBURSED"


class TestClosingInputGuards:
    """The survey tolerance, the rights ceiling and the scope test, in order."""

    def test_the_three_closing_guards_fire_before_any_easement_is_written(self):
        """159.00 rejected, 159.60 accepted, then rights before scope.

        PRD §3.7: "`protected_acres`, strictly positive with 2 decimals, which
        must equal the `surveyed_acres` of the application's accepted
        `BOUNDARY_SURVEY` requirement, or the parcel's `acres` when that
        requirement was waived, failing which the answer is
        `ERR_REQUIREMENT_SCOPE_MISMATCH`; `residential_rights_retained`, the
        count of building rights the landowner keeps, which must lie between 0
        and the parcel's `baseline_dwelling_rights` inclusive, failing which the
        answer is `ERR_RESIDENTIAL_RIGHTS_OVERDRAWN`"

        Design: Corner/errors/closing_input_guards_fire_in_ladder_order_before_the_easement_is_recorded
        """
        scenario = setup_accepted_application()
        application_id = scenario["application"]["id"]
        submit_and_accept_requirement(
            requirement_of_type(application_id, "TITLE_COMMITMENT")["id"],
            submit_title_payload(0),
        )
        submit_and_accept_requirement(
            requirement_of_type(application_id, "MORTGAGE_SUBORDINATION")["id"],
            submit_subordination_payload(),
        )
        survey_id = requirement_of_type(application_id, "BOUNDARY_SURVEY")["id"]

        # |159.00 - 160.00| == 1.00 acre, past the 0.50-acre tolerance.
        too_far = api_client.submit_closing_requirement(
            survey_id, submit_survey_payload(159.00), OFFICER
        )
        validate_error(too_far, ApiErrorId.ERR_SURVEY_ACREAGE_MISMATCH.value, 409)
        assert (
            validate_success(api_client.get_closing_requirement(survey_id, ADMIN))[
                "status"
            ]
            == "OUTSTANDING"
        )

        # |159.60 - 160.00| == 0.40 acre, exactly inside the tolerance.
        submitted = validate_success(
            api_client.submit_closing_requirement(
                survey_id, submit_survey_payload(159.60), OFFICER
            )
        )
        assert submitted["status"] == "SUBMITTED"
        assert submitted["surveyed_acres"] == pytest.approx(159.60, abs=0.01)
        accepted = validate_success(
            api_client.review_closing_requirement(
                survey_id, review_requirement_payload("ACCEPT"), ADMIN
            )
        )
        assert accepted["status"] == "SATISFIED"
        cleared = read_application(application_id)
        assert cleared["closing_status"] == "CLEARED"
        assert cleared["requirement_satisfied_count"] == 3

        set_clock(CLOCK_2026_12_15)
        scope = api_client.record_closing(
            application_id,
            record_closing_payload(recorded_on=CLOCK_2026_12_15, protected_acres=160.00),
            ADMIN,
        )
        validate_error(scope, ApiErrorId.ERR_REQUIREMENT_SCOPE_MISMATCH.value, 409)

        # The rights ceiling sits above the scope test, so 5 rights is reported
        # even though 159.60 acres would have cleared the scope check.
        overdrawn = api_client.record_closing(
            application_id,
            record_closing_payload(
                recorded_on=CLOCK_2026_12_15,
                protected_acres=159.60,
                residential_rights_retained=5,
            ),
            ADMIN,
        )
        validate_error(overdrawn, ApiErrorId.ERR_RESIDENTIAL_RIGHTS_OVERDRAWN.value, 409)
        _, meta = validate_paginated(api_client.list_easements(ADMIN))
        assert meta["total_count"] == 0
        assert read_application(application_id)["closing_status"] == "CLEARED"

        easement = validate_success(
            api_client.record_closing(
                application_id,
                record_closing_payload(
                    recorded_on=CLOCK_2026_12_15,
                    protected_acres=159.60,
                    residential_rights_retained=2,
                ),
                ADMIN,
            ),
            201,
        )
        assert easement["protected_acres"] == pytest.approx(159.60, abs=0.01)
        # floor(159.60 * 43,560 * 0.02) == 139,043, not the 139,392 the parcel
        # acreage would have produced.
        assert easement["impervious_allowance_sqft"] == 139_043
        assert easement["residential_rights_retained"] == 2
        assert easement["residential_rights_extinguished"] == 2
        closed = read_application(application_id)
        assert closed["status"] == "CLOSED_RECORDED"
        assert closed["closing_status"] == "CLOSED"
        assert closed["funding_plan_status"] == "DISBURSED"


class TestMoneyCeilings:
    """Both price ceilings, one cent past the boundary and then exactly at it."""

    def test_the_request_ceiling_admits_only_the_rounded_boundary(self):
        """173,690,000 is the ceiling; 173,700,000 is refused.

        PRD §3.3: "The landowner's `requested_price_cents` may not exceed that
        figure multiplied by 1.10 and rounded half up — a ten percent ask above
        the assessor proxy — and a higher request is rejected with
        `ERR_REQUESTED_PRICE_ABOVE_PRELIMINARY_CEILING`."

        Design: Corner/errors/price_ceiling_and_certified_value_guards_admit_only_the_boundary_amount
        """
        scenario = setup_program_with_round()
        landowner_headers = scenario["landowner_headers"]
        parcel = create_parcel(scenario["landowner"]["id"])
        keys = (scenario["round"]["id"], parcel["id"], scenario["landowner"]["id"])

        # floor(0.90 * (288,000,000 - 112,450,000) / 100,000) * 100,000 is
        # 157,900,000, whose 1.10 ceiling rounds half up to 173,690,000.
        above = api_client.create_application(
            create_application_payload(*keys, requested_price_cents=173_700_000),
            landowner_headers,
        )
        validate_error(
            above, ApiErrorId.ERR_REQUESTED_PRICE_ABOVE_PRELIMINARY_CEILING.value, 409
        )
        _, meta = validate_paginated(api_client.list_applications(ADMIN))
        assert meta["total_count"] == 0

        at_ceiling = validate_success(
            api_client.create_application(
                create_application_payload(*keys, requested_price_cents=173_690_000),
                landowner_headers,
            ),
            201,
        )
        assert at_ceiling["preliminary_easement_value_cents"] == 157_900_000
        assert at_ceiling["requested_price_cents"] == 173_690_000

    def test_the_certified_ceiling_binds_twice_and_acceptance_needs_a_plan(self):
        """No certified appraisal, then one cent over, then the exact value.

        PRD §3.5: "A `CERTIFIED` appraisal must already exist on the application,
        and `offer_cents` may not exceed the application's
        `certified_easement_value_cents`; either failure is reported as
        `ERR_OFFER_EXCEEDS_CERTIFIED_VALUE`."

        Design: Corner/errors/price_ceiling_and_certified_value_guards_admit_only_the_boundary_amount
        """
        scenario = setup_program_with_round()
        parcel = create_parcel(scenario["landowner"]["id"])
        landowner_headers = scenario["landowner_headers"]
        application = validate_success(
            api_client.create_application(
                create_application_payload(
                    scenario["round"]["id"],
                    parcel["id"],
                    scenario["landowner"]["id"],
                    requested_price_cents=173_690_000,
                ),
                landowner_headers,
            ),
            201,
        )
        application_id = application["id"]

        set_clock(CLOCK_2026_10_01)
        ranked = validate_success(
            api_client.rank_funding_round(scenario["round"]["id"], rank_payload(), ADMIN)
        )
        assert ranked["ranked_count"] == 1
        assert ranked["selected_count"] == 1
        pinned = read_application(application_id)
        assert pinned["status"] == "RANKED"
        assert pinned["composite_score"] == pytest.approx(73.40, abs=0.01)

        # No appraisal has been certified at all, which is the first clause.
        uncertified = api_client.issue_offer(
            application_id,
            issue_offer_payload(pinned["version"], 100_000_000),
            OFFICER,
        )
        validate_error(
            uncertified, ApiErrorId.ERR_OFFER_EXCEEDS_CERTIFIED_VALUE.value, 409
        )
        assert read_application(application_id)["version"] == pinned["version"]

        appraisal = validate_success(
            api_client.engage_appraisal(
                application_id,
                engage_appraisal_payload(
                    engagement_start="2026-10-03T00:00:00Z",
                    engagement_end="2026-10-17T00:00:00Z",
                ),
                OFFICER,
            ),
            201,
        )
        set_clock("2026-10-05T00:00:00Z")
        validate_success(
            api_client.submit_appraisal(
                appraisal["id"], submit_appraisal_payload(), APPRAISER
            )
        )
        validate_success(
            api_client.review_appraisal(
                appraisal["id"], review_appraisal_payload("CERTIFY"), REVIEWER
            )
        )
        certified = read_application(application_id)
        assert certified["certified_easement_value_cents"] == 175_550_000

        one_cent_over = api_client.issue_offer(
            application_id,
            issue_offer_payload(certified["version"], 175_550_001),
            OFFICER,
        )
        validate_error(
            one_cent_over, ApiErrorId.ERR_OFFER_EXCEEDS_CERTIFIED_VALUE.value, 409
        )
        assert read_application(application_id)["version"] == certified["version"]

        offered = validate_success(
            api_client.issue_offer(
                application_id,
                issue_offer_payload(certified["version"], 175_550_000),
                OFFICER,
            )
        )
        assert offered["status"] == "OFFER_ISSUED"
        assert offered["current_offer_cents"] == 175_550_000
        assert offered["negotiation_round_count"] == 1

        # No plan has been assembled, so the acceptance branch join refuses.
        unfunded = api_client.accept_application(application_id, landowner_headers)
        validate_error(unfunded, ApiErrorId.ERR_FUNDING_PLAN_INCOMPLETE.value, 409)
        still_open = read_application(application_id)
        assert still_open["status"] == "OFFER_ISSUED"
        assert still_open["funding_plan_status"] == "UNFUNDED"
        assert list_requirements(application_id) == []


class TestSourceCapacityAtAcceptance:
    """Two reserved plans against one appropriation; only the first obligates."""

    def test_the_second_acceptance_runs_the_ledger_past_its_authority(self):
        """Reserved holds are not netted, so the capacity test binds at acceptance.

        PRD §3.6: "And no source may be committed beyond its `available_cents`,
        nor may a source's `OBLIGATED` plus `DISBURSED` total ever exceed its
        `authorized_cents`, otherwise `ERR_SOURCE_WINDOW_CAPACITY_EXCEEDED` — a
        test that binds both at assembly time and again at acceptance."

        Design: Corner/errors/accepting_a_second_plan_against_drained_local_headroom_raises_source_window_capacity_exceeded
        """
        scenario = setup_two_applications_competing_for_headroom()
        local_id = scenario["sources"]["local"]["id"]
        application_a = scenario["application_a"]
        application_b = scenario["application_b"]

        before = read_source(local_id)
        # Both plans hold 56,127,723 of the same 60,000,000 appropriation.
        assert before["reserved_cents"] == 112_255_446
        assert before["committed_cents"] == 0
        assert before["available_cents"] == 60_000_000

        accepted = validate_success(
            api_client.accept_application(
                application_a["id"], make_landowner_headers(scenario["landowner_a"]["id"])
            )
        )
        assert accepted["status"] == "ACCEPTED"
        assert accepted["funding_plan_status"] == "OBLIGATED"

        # 56,127,723 < floor(60,000,000 * 0.95) == 57,000,000, so the source
        # stays ACTIVE and no FULLY_OBLIGATED cascade rescues the second plan.
        midway = read_source(local_id)
        assert midway["committed_cents"] == 56_127_723
        assert midway["available_cents"] == 3_872_277
        assert midway["status"] == "ACTIVE"

        denied = api_client.accept_application(
            application_b["id"], make_landowner_headers(scenario["landowner_b"]["id"])
        )
        validate_error(
            denied, ApiErrorId.ERR_SOURCE_WINDOW_CAPACITY_EXCEEDED.value, 409
        )

        untouched = read_application(application_b["id"])
        assert untouched["status"] == "OFFER_ISSUED"
        assert untouched["funding_plan_status"] == "FUNDED"
        assert untouched["closing_status"] == "NOT_APPLICABLE"
        assert list_requirements(application_b["id"]) == []
        commitments = commitments_of(application_b["id"])
        assert len(commitments) == 3
        assert {row["status"] for row in commitments} == {"RESERVED"}
        assert read_source(local_id)["committed_cents"] == 56_127_723


class TestRankingGuards:
    """The intake window closes before emptiness can be observed."""

    def test_the_window_guard_outranks_the_emptiness_guard(self):
        """Rank early, then rank an empty round; the round stays OPEN.

        PRD §3.3: "It requires the round to be `OPEN` — a second attempt therefore
        fails with `ERR_INVALID_ROUND_STATE` — requires the logical clock to be
        strictly past `closes_on`, failing which the answer is
        `ERR_ROUND_WINDOW_CLOSED`, and requires at least one application on the
        round still in `RECEIVED`, failing which the answer is
        `ERR_NO_SCORED_APPLICATIONS`."

        Design: Corner/errors/ranking_an_empty_round_after_its_close_date_raises_no_scored_applications
        """
        scenario = setup_program_with_round()
        round_id = scenario["round"]["id"]

        # The clock sits inside intake, well before closes_on 2026-09-30.
        early = api_client.rank_funding_round(round_id, rank_payload(), ADMIN)
        validate_error(early, ApiErrorId.ERR_ROUND_WINDOW_CLOSED.value, 409)

        set_clock(CLOCK_2026_10_01)
        empty = api_client.rank_funding_round(round_id, rank_payload(), ADMIN)
        validate_error(empty, ApiErrorId.ERR_NO_SCORED_APPLICATIONS.value, 409)

        unmoved = validate_success(api_client.get_funding_round(round_id, ADMIN))
        assert unmoved["status"] == "OPEN"
        assert unmoved["application_count"] == 0
        assert unmoved["ranked_at"] is None


class TestZeroBenefitAmendment:
    """Zero is a legal draft, a legal submission and an illegal approval."""

    def test_the_benefit_test_binds_only_at_the_decision(self):
        """APPROVE is refused while REJECT on the same amendment succeeds.

        PRD §3.9: "Approval additionally requires `net_conservation_benefit_cents`
        to be strictly greater than 0 — a zero-benefit amendment may be drafted
        and submitted but can never be approved — and subdivision rights are
        never granted by amendment at all; either attempt is rejected with
        `ERR_NO_NET_CONSERVATION_BENEFIT`."

        Design: Corner/errors/approving_a_zero_benefit_amendment_raises_no_net_conservation_benefit_while_rejecting_it_succeeds
        """
        scenario = setup_recorded_easement()
        easement_id = scenario["easement"]["id"]

        amendment = draft_amendment(easement_id, net_conservation_benefit_cents=0)
        assert amendment["status"] == "DRAFT"
        assert amendment["net_conservation_benefit_cents"] == 0
        assert submit_amendment(amendment["id"])["status"] == "UNDER_REVIEW"
        assert read_easement(easement_id)["pending_amendment_count"] == 1

        refused = api_client.decide_amendment(
            amendment["id"], decide_amendment_payload("APPROVE"), ADMIN
        )
        validate_error(refused, ApiErrorId.ERR_NO_NET_CONSERVATION_BENEFIT.value, 409)
        unchanged = read_easement(easement_id)
        assert unchanged["status"] == "RECORDED"
        assert unchanged["amendment_count"] == 0
        assert unchanged["pending_amendment_count"] == 1

        rejected = decide_amendment(
            amendment["id"], "REJECT", reason="no measurable conservation benefit"
        )
        assert rejected["status"] == "REJECTED"
        assert rejected["decision_reason"] == "no measurable conservation benefit"
        settled = read_easement(easement_id)
        assert settled["pending_amendment_count"] == 0
        assert settled["status"] == "RECORDED"


class TestImperviousAllowanceCeiling:
    """One code, two clauses: the use meter and the amendment request."""

    def test_the_allowance_binds_on_the_use_request_and_on_the_amendment(self):
        """139,392 exactly is admitted; one square foot either side is not.

        PRD §3.8: "A request that would push `impervious_used_sqft` above the
        allowance is rejected outright with `ERR_IMPERVIOUS_ALLOWANCE_EXCEEDED`
        and nothing is recorded."

        Design: Corner/errors/impervious_allowance_exceeded_fires_on_both_the_use_request_and_the_amendment_clause
        """
        scenario = setup_recorded_easement()
        easement_id = scenario["easement"]["id"]

        over = api_client.record_impervious_request(
            easement_id,
            impervious_request_payload(139_393, "shed pad one square foot over"),
            ADMIN,
        )
        validate_error(over, ApiErrorId.ERR_IMPERVIOUS_ALLOWANCE_EXCEEDED.value, 409)
        assert read_easement(easement_id)["impervious_used_sqft"] == 0

        exact = validate_success(
            api_client.record_impervious_request(
                easement_id,
                impervious_request_payload(139_392, "shed pad at exactly the allowance"),
                ADMIN,
            )
        )
        assert exact["impervious_used_sqft"] == 139_392
        assert exact["impervious_allowance_sqft"] == 139_392

        one_more = api_client.record_impervious_request(
            easement_id,
            impervious_request_payload(1, "one more square foot of gravel apron"),
            MONITOR,
        )
        validate_error(one_more, ApiErrorId.ERR_IMPERVIOUS_ALLOWANCE_EXCEEDED.value, 409)
        assert read_easement(easement_id)["impervious_used_sqft"] == 139_392

        # The amendment clause requires strictly more than the current allowance.
        not_strictly_more = api_client.draft_amendment(
            easement_id,
            draft_amendment_payload(
                easement_version(easement_id),
                amendment_type="IMPERVIOUS_INCREASE",
                requested_impervious_sqft=139_392,
            ),
            ADMIN,
        )
        validate_error(
            not_strictly_more, ApiErrorId.ERR_IMPERVIOUS_ALLOWANCE_EXCEEDED.value, 409
        )

        drafted = draft_amendment(
            easement_id,
            amendment_type="IMPERVIOUS_INCREASE",
            requested_impervious_sqft=200_000,
        )
        assert drafted["status"] == "DRAFT"
        assert drafted["amendment_type"] == "IMPERVIOUS_INCREASE"
        assert drafted["requested_impervious_sqft"] == 200_000
        final = read_easement(easement_id)
        # Only an APPROVE decision rewrites the allowance.
        assert final["impervious_allowance_sqft"] == 139_392
        # An approved use request is not a violation.
        assert final["compliance_status"] == "COMPLIANT"


class TestTerminatedEasement:
    """The 730-day escalation clock, walked to its boundary and one day past."""

    def test_termination_closes_the_easement_to_further_stewardship_writes(self):
        """Day 729 terminates nothing; day 730 terminates and refuses everything.

        PRD §3.8: "And where remediation never comes, the sweep terminates the
        easement: an easement whose `compliance_status` is `VIOLATION_ESCALATED`
        moves to `TERMINATED` once the clock reaches or passes the earliest
        `escalated_on` among its escalated violations advanced by 730 days.
        Termination returns the parcel `ENCUMBERED → ELIGIBLE` with its `version`
        incremented, recomputes the program's `total_preserved_acres`, and
        increments the easement's `version`."

        Design: Corner/errors/a_terminated_easement_refuses_visits_impervious_requests_and_amendments
        """
        scenario = setup_recorded_easement()
        easement_id = scenario["easement"]["id"]

        set_clock(CLOCK_2027_06_03)
        violation = open_violation(
            easement_id,
            violation_type="IMPERVIOUS_EXCEEDANCE",
            excess_sqft=2_608,
            notes="unpermitted paved lot measured over the allowance",
        )
        # 2,608 > 2,000 selects the 90-day cure window from 2027-06-03.
        assert violation["severity"] == "MAJOR"
        assert violation["cure_deadline_on"].startswith("2027-09-01")

        set_clock("2027-09-02T00:00:00Z")
        escalating = run_sweep(ADMIN)
        assert escalating["escalated_violation_count"] == 1
        assert escalating["terminated_easement_count"] == 0
        assert escalating["closed_round_count"] == 1
        # next_monitoring_due_on is still 2027-12-15, so nothing is due yet.
        assert escalating["due_count"] == 0
        escalated = read_violation(violation["id"])
        assert escalated["status"] == "ESCALATED"
        assert escalated["escalated_on"].startswith("2027-09-02")
        held = read_easement(easement_id)
        assert held["compliance_status"] == "VIOLATION_ESCALATED"
        assert held["stewardship_hold"] is True

        # 2029-08-31 is escalated_on advanced by 729 days.
        set_clock("2029-08-31T00:00:00Z")
        day_729 = run_sweep(ADMIN)
        assert day_729["terminated_easement_count"] == 0
        assert day_729["expired_source_count"] == 3
        assert read_easement(easement_id)["status"] == "RECORDED"

        # 2029-09-01 is escalated_on advanced by exactly 730 days.
        set_clock("2029-09-01T00:00:00Z")
        day_730 = run_sweep(ADMIN)
        assert day_730["terminated_easement_count"] == 1
        assert day_730["escalated_violation_count"] == 0
        assert day_730["expired_source_count"] == 0
        assert read_easement(easement_id)["status"] == "TERMINATED"
        assert read_parcel(scenario["parcel"]["id"])["status"] == "ELIGIBLE"
        assert validate_success(
            api_client.get_program(scenario["program"]["id"], ADMIN)
        )["total_preserved_acres"] == pytest.approx(0.00, abs=0.01)

        refused_visit = api_client.schedule_monitoring_visit(
            schedule_visit_payload(
                easement_id,
                window_start="2029-09-10T00:00:00Z",
                window_end="2029-09-17T00:00:00Z",
            ),
            MONITOR,
        )
        validate_error(refused_visit, ApiErrorId.ERR_INVALID_EASEMENT_STATE.value, 409)
        _, visit_meta = validate_paginated(
            api_client.list_monitoring_visits(easement_id, MONITOR)
        )
        assert visit_meta["total_count"] == 0

        # The version is current, so the 412 gate passed and the state check decided.
        refused_amendment = api_client.draft_amendment(
            easement_id, draft_amendment_payload(easement_version(easement_id)), ADMIN
        )
        validate_error(
            refused_amendment, ApiErrorId.ERR_INVALID_EASEMENT_STATE.value, 409
        )
        _, amendment_meta = validate_paginated(
            api_client.list_easement_amendments(easement_id, ADMIN)
        )
        assert amendment_meta["total_count"] == 0


class TestDefensiveInvariants:
    """The two guards that only the legal path can reach, on their passing side."""

    def test_the_closing_path_satisfies_both_defensive_checks(self):
        """A CLEARED file always carries an OBLIGATED plan and its own parcel.

        PRD §3.7: "it requires `funding_plan_status` to be `OBLIGATED`, so a plan
        whose commitments have lapsed or been released must be re-assembled first
        or the closing is rejected with `ERR_FUNDING_PLAN_STALE`."

        Design: Corner/errors/the_two_defensive_funding_and_scope_invariants_hold_on_the_only_path_that_reaches_them
        """
        scenario = setup_recorded_easement()
        application = read_application(scenario["application"]["id"])
        assert application["closing_status"] == "CLOSED"
        assert application["funding_plan_status"] == "DISBURSED"
        assert application["funded_cost_cents"] == application["total_program_cost_cents"]
        assert application["funded_cost_cents"] == 160_364_925

        easement = read_easement(scenario["easement"]["id"])
        # No endpoint accepts a parcel id for an existing easement, so the scope
        # guard can only ever be satisfied.
        assert easement["parcel_id"] == application["parcel_id"]
        assert easement["application_id"] == application["id"]

        commitments = commitments_of(application["id"])
        assert len(commitments) == 3
        assert {row["status"] for row in commitments} == {"DISBURSED"}
