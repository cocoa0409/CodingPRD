"""Role access control: exclusive writes, carrier scoping and segregation of duties.

Every scenario is built from scratch through the API the PRD declares: the
harness relaunches the server before each test, so each test starts against an
empty database and builds all of its own state.
"""

from test_helpers import (
    ANALYST,
    COORDINATOR,
    EIC,
    EXAMINER_IN_CHARGE_ID,
    STANDARD_PARTICIPATING_STATES,
    SUPERVISING_EXAMINER_ID,
    SUPERVISOR,
    SUPERVISOR_B,
    ApiErrorId,
    analysis_cycle_payload,
    clock_payload,
    collaboration_payload,
    company_response_payload,
    consent_order_payload,
    corrective_action_plan_payload,
    criticism_finalize_payload,
    criticism_payload,
    data_call_payload,
    data_call_response_payload,
    examination_payload,
    issue_criticism,
    make_insurer_respondent_headers,
    order_execution_payload,
    plan_review_payload,
    publish_report_payload,
    read_examination,
    rebuttal_payload,
    register_insurer,
    respond_to_criticism,
    scope_area_payload,
    setup_examination_in_criticism,
    setup_examination_in_negotiation,
    setup_examination_in_scoping,
    add_scope_area,
    open_examination,
    validate_error,
    validate_paginated,
    validate_success,
)

# The logical clock reads 2026-08-01T00:00:00Z before any client moves it, so
# these dates sit inside the examination's fieldwork window.
FIELDWORK_START = "2026-09-01"
FIELDWORK_END = "2026-11-30"
RESPONSE_DUE = "2026-09-15"


def _clock_headers_without_user_id(role: str) -> dict:
    """A role header carrying no ``X-User-ID`` at all."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


class TestExclusiveWritesPerRole:
    def test_each_role_holds_a_write_no_other_role_can_perform(self, api):
        """Five writes, five roles, and the same payload refused then accepted.

        PRD §2.1: "If the value of `X-User-Role` is not one of the roles the called endpoint declares, the request is rejected with `ERR_ROLE_NOT_PERMITTED`."
        PRD §2.1: "Owns the carrier data set, the scoring cycle and target selection; has no authority over examination fieldwork or enforcement."
        PRD §3.3: "A `SupervisingExaminer` may open a for-cause or targeted examination directly by supplying the subject `insurer_id`, an `exam_type` of either `MARKET_CONDUCT_EXAM` or `TARGETED_EXAM`, a `mode` of `ON_SITE` or `DESK`, a `lead_state_code` of exactly two uppercase letters, and the fieldwork occupancy window as `fieldwork_start_date` and `fieldwork_end_date`, the latter strictly after the former."
        PRD §3.3: "While the examination is in `SCOPING`, the `ExaminerInCharge` adds one **scope area** per statutory examination area."
        PRD §3.9: "A `MultistateCoordinator` opens the collaboration on an examination, supplying the `participating_states` roster and optionally the `call_reference` naming the NAIC collaborative-action call."
        PRD §3.4: "An `InsurerRespondent` produces records against a call in `ISSUED` or `OVERDUE`, which advances it to `RESPONDED`."

        Design: Corner/rbac/each_role_holds_at_least_one_exclusive_write
        """
        insurer = register_insurer()
        respondent = make_insurer_respondent_headers(insurer["id"])

        # 1. Opening an analysis cycle belongs to the market analyst alone.
        cycle_body = analysis_cycle_payload(
            cycle_label="2026-H2-MARKET-ANALYSIS", target_slot_capacity=3
        )
        validate_error(
            api.create_analysis_cycle(cycle_body, SUPERVISOR),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
        )
        validate_success(api.create_analysis_cycle(cycle_body, ANALYST), 201)

        # 2. Opening an examination belongs to the supervising examiner alone.
        exam_body = examination_payload(
            insurer["id"],
            fieldwork_start_date=FIELDWORK_START,
            fieldwork_end_date=FIELDWORK_END,
        )
        validate_error(
            api.open_examination(exam_body, EIC),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
        )
        examination = validate_success(api.open_examination(exam_body, SUPERVISOR), 201)
        exam_id = examination["id"]

        # 3. Declaring a scope area belongs to the examiner in charge alone.
        area_body = scope_area_payload("CLAIMS", population_size=4000, sample_size=10)
        validate_error(
            api.create_scope_area(exam_id, area_body, SUPERVISOR),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
        )
        scope_area = validate_success(
            api.create_scope_area(exam_id, area_body, EIC), 201
        )
        validate_success(api.lock_scope(exam_id, SUPERVISOR))

        # 4. Opening the collaboration belongs to the multistate coordinator alone.
        collab_body = collaboration_payload(
            STANDARD_PARTICIPATING_STATES, call_reference="NAIC-CAWG-2026-0117"
        )
        validate_error(
            api.open_collaboration(exam_id, collab_body, SUPERVISOR),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
        )
        validate_success(api.open_collaboration(exam_id, collab_body, COORDINATOR), 201)

        # 5. Producing records belongs to the carrier respondent alone.
        data_call = validate_success(
            api.create_data_call(
                scope_area["id"],
                data_call_payload(
                    records_requested=4000, response_due_date=RESPONSE_DUE
                ),
                EIC,
            ),
            201,
        )
        response_body = data_call_response_payload(records_received=4000)
        validate_error(
            api.respond_to_data_call(data_call["id"], response_body, EIC),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
        )
        produced = validate_success(
            api.respond_to_data_call(data_call["id"], response_body, respondent)
        )
        assert produced["status"] == "RESPONDED"


class TestCarrierAuthoredRecordsAreClosedToTheDepartment:
    def test_no_department_role_may_answer_a_criticism_for_the_carrier(self, api):
        """The company response is the carrier's own record of position.

        PRD §2.1: "`InsurerRespondent` — the compliance officer acting for the examined carrier. Produces records, answers criticisms, proposes corrective action plans and executes consent orders."
        PRD §2.1: "If the value of `X-User-Role` is not one of the roles the called endpoint declares, the request is rejected with `ERR_ROLE_NOT_PERMITTED`."
        PRD §3.7: "The carrier answers a criticism that is in `ISSUED`, moving it to `RESPONDED`."

        Design: Corner/rbac/department_roles_cannot_answer_a_criticism_for_the_carrier
        """
        scenario = setup_examination_in_criticism()
        criticism = issue_criticism(
            scenario["exam_id"], scenario["scope_area_id"], "MATERIAL", 3
        )

        for headers in (SUPERVISOR, EIC, COORDINATOR):
            validate_error(
                api.create_company_response(
                    criticism["id"], company_response_payload("CONCUR"), headers
                ),
                ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
            )

        # The coordinator that was refused the write may still read the criticism,
        # which is untouched by the three refusals.
        read_back = validate_success(api.get_criticism(criticism["id"], COORDINATOR))
        assert read_back["response_round"] == 0
        assert read_back["status"] == "ISSUED"
        rounds, meta = validate_paginated(
            api.list_company_responses(criticism["id"], COORDINATOR)
        )
        assert meta["total_count"] == 0
        assert rounds == []

        filed = validate_success(
            api.create_company_response(
                criticism["id"],
                company_response_payload("DISPUTE"),
                scenario["respondent_headers"],
            ),
            201,
        )
        assert filed["round_number"] == 1

    def test_the_department_neither_files_the_plan_nor_signs_the_order(self, api):
        """Adjacent enforcement endpoints on one examination have opposite grants.

        PRD §2.1: "`InsurerRespondent` — the compliance officer acting for the examined carrier. Produces records, answers criticisms, proposes corrective action plans and executes consent orders."
        PRD §3.8: "The `InsurerRespondent` proposes a plan against the examination, supplying the `expected_examination_version` pin described in §2.6, a `milestone_count` of at least 1 naming the number of remediation milestones committed to, a `completion_due_date` by which the carrier commits to completing them all, and a `narrative` of at least 20 characters."
        PRD §3.8: "The `SupervisingExaminer` dispositions a `PROPOSED` plan by supplying a `decision` of `APPROVE`, `REJECT` or `REQUEST_REVISION`, plus an optional `review_note`."
        PRD §3.8: "The `InsurerRespondent` executes a `DRAFT` order, supplying the `signed_by` name of the carrier officer who signed it."
        PRD §2.11: "Checks are evaluated in the following bands, in this order, and the first band that produces a rejection determines the response:"

        Design: Corner/rbac/department_roles_cannot_file_or_sign_the_carriers_enforcement_documents
        """
        scenario = setup_examination_in_negotiation()
        exam_id = scenario["exam_id"]
        respondent = scenario["respondent_headers"]

        # The pinned version is the examination's current version, so the refusal
        # cannot be the version-pinning band.
        plan_body = corrective_action_plan_payload(read_examination(exam_id)["version"])
        for headers in (SUPERVISOR, COORDINATOR):
            validate_error(
                api.propose_corrective_action_plan(exam_id, plan_body, headers),
                ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
            )
        plan = validate_success(
            api.propose_corrective_action_plan(exam_id, plan_body, respondent), 201
        )

        # The carrier cannot approve its own remediation plan.
        validate_error(
            api.review_corrective_action_plan(
                plan["id"], plan_review_payload("APPROVE"), respondent
            ),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
        )
        validate_success(
            api.review_corrective_action_plan(
                plan["id"], plan_review_payload("APPROVE"), SUPERVISOR
            )
        )

        order = validate_success(
            api.draft_consent_order(
                exam_id,
                consent_order_payload(
                    read_examination(exam_id)["version"],
                    order_number="NV-MC-2026-0042",
                    penalty_variant="PER_VIOLATION",
                ),
                SUPERVISOR,
            ),
            201,
        )

        # The department cannot sign the order it drafted.
        validate_error(
            api.execute_consent_order(
                order["id"], order_execution_payload(), SUPERVISOR
            ),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
        )
        executed = validate_success(
            api.execute_consent_order(
                order["id"],
                order_execution_payload(signed_by="M. Halloran, President and CEO"),
                respondent,
            )
        )
        assert executed["status"] == "EXECUTED"
        assert executed["signed_by"] == "M. Halloran, President and CEO"

        _, plan_meta = validate_paginated(
            api.list_corrective_action_plans(exam_id, SUPERVISOR)
        )
        _, order_meta = validate_paginated(api.list_consent_orders(exam_id, SUPERVISOR))
        assert plan_meta["total_count"] == 1
        assert order_meta["total_count"] == 1


class TestRespondentScoping:
    def test_a_foreign_carrier_is_refused_across_the_whole_respondent_surface(self, api):
        """The right role and the wrong carrier fail with a different code.

        PRD §2.1: "When `X-User-Role` is `InsurerRespondent`, by contrast, `X-User-ID` is the `id` of the acting `Insurer`; ownership checks on any record the respondent touches walk up to the owning `Examination` and compare its `insurer_id` to `X-User-ID`."
        PRD §2.1: "A mismatch is rejected with `ERR_NOT_EXAM_SUBJECT`."
        PRD §2.1: "That check guards the respondent's four writes — producing records against a data call, answering a criticism, proposing a corrective action plan, and executing a consent order — and equally every read the respondent makes against a record whose owning examination belongs to another carrier."

        Design: Corner/rbac/the_respondent_is_scoped_to_its_own_examination_on_every_endpoint_it_holds
        """
        scenario = setup_examination_in_negotiation()
        exam_id = scenario["exam_id"]
        subject = scenario["respondent_headers"]

        foreign_insurer = register_insurer(
            name="Boreal Casualty Company", naic_code="10002"
        )
        foreign = make_insurer_respondent_headers(foreign_insurer["id"])
        foreign_exam = open_examination(
            foreign_insurer["id"],
            fieldwork_start_date="2027-01-04",
            fieldwork_end_date="2027-03-31",
        )

        plan_body = corrective_action_plan_payload(read_examination(exam_id)["version"])
        validate_error(
            api.propose_corrective_action_plan(exam_id, plan_body, foreign),
            ApiErrorId.ERR_NOT_EXAM_SUBJECT.value,
        )
        plan = validate_success(
            api.propose_corrective_action_plan(exam_id, plan_body, subject), 201
        )
        validate_success(
            api.review_corrective_action_plan(
                plan["id"], plan_review_payload("APPROVE"), SUPERVISOR
            )
        )
        order = validate_success(
            api.draft_consent_order(
                exam_id,
                consent_order_payload(
                    read_examination(exam_id)["version"],
                    order_number="NV-MC-2026-0042",
                    penalty_variant="PER_VIOLATION",
                ),
                SUPERVISOR,
            ),
            201,
        )

        validate_error(
            api.execute_consent_order(order["id"], order_execution_payload(), foreign),
            ApiErrorId.ERR_NOT_EXAM_SUBJECT.value,
        )
        validate_error(
            api.list_consent_orders(exam_id, foreign),
            ApiErrorId.ERR_NOT_EXAM_SUBJECT.value,
        )

        # The same carrier reads its own examination without complaint.
        own = validate_success(api.get_examination(foreign_exam["id"], foreign))
        assert own["status"] == "SCOPING"

        executed = validate_success(
            api.execute_consent_order(
                order["id"],
                order_execution_payload(signed_by="M. Halloran, President and CEO"),
                subject,
            )
        )
        assert executed["status"] == "EXECUTED"


class TestSegregationOfDutiesIsNarrow:
    def test_one_supervisor_may_accumulate_every_role_but_the_two_named_acts(self, api):
        """The two rules compare against the issuer and the drafter and nothing else.

        PRD §2.9: "Two enforcement decisions may not be made by the user who set them up, and the service enforces both by comparing `X-User-ID` against an audit key stored earlier."
        PRD §2.9: "A criticism may not be sustained or withdrawn by the examiner who issued it: when finalizing a criticism, if `X-User-ID` equals that criticism's `issued_by_user_id`, the request is rejected with `ERR_SEGREGATION_OF_DUTIES`."
        PRD §2.9: "A report resting on an executed consent order may not be published by the supervising examiner who drafted that order: when publishing, if `X-User-ID` equals the executed order's `drafted_by_user_id`, the request is likewise rejected with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/segregation_of_duties_names_two_acts_and_no_more
        """
        # The examination is opened and its scope locked by the supervising
        # examiner who will also finalize, review and draft below.
        scenario = setup_examination_in_criticism()
        exam_id = scenario["exam_id"]
        criticism = issue_criticism(
            scenario["exam_id"], scenario["scope_area_id"], "MATERIAL", 3
        )
        assert criticism["issued_by_user_id"] == EXAMINER_IN_CHARGE_ID
        respond_to_criticism(criticism["id"], scenario["insurer_id"], "DISPUTE")

        sustained = validate_success(
            api.finalize_criticism(
                criticism["id"], criticism_finalize_payload("SUSTAINED", 20), SUPERVISOR
            )
        )
        assert sustained["status"] == "SUSTAINED"
        assert sustained["finalized_by_user_id"] == SUPERVISING_EXAMINER_ID

        plan = validate_success(
            api.propose_corrective_action_plan(
                exam_id,
                corrective_action_plan_payload(read_examination(exam_id)["version"]),
                scenario["respondent_headers"],
            ),
            201,
        )
        approved = validate_success(
            api.review_corrective_action_plan(
                plan["id"], plan_review_payload("APPROVE"), SUPERVISOR
            )
        )
        assert approved["status"] == "APPROVED"

        order = validate_success(
            api.draft_consent_order(
                exam_id,
                consent_order_payload(
                    read_examination(exam_id)["version"],
                    order_number="NV-MC-2026-0042",
                    penalty_variant="PER_VIOLATION",
                ),
                SUPERVISOR,
            ),
            201,
        )
        assert order["drafted_by_user_id"] == SUPERVISING_EXAMINER_ID
        assert order["drafted_by_user_id"] != criticism["issued_by_user_id"]

        validate_success(
            api.execute_consent_order(
                order["id"],
                order_execution_payload(),
                scenario["respondent_headers"],
            )
        )
        published = validate_success(
            api.publish_report(exam_id, publish_report_payload(), SUPERVISOR_B)
        )
        assert published["status"] == "PUBLISHED"


class TestSharedReads:
    def test_the_exposure_summary_is_narrower_than_the_examination_read(self, api):
        """Subject status does not widen a grant on the exposure summary.

        PRD §3.8: "Because the two variants can differ enormously for the same examination, a supervising examiner or multistate coordinator may ask for both side by side without persisting either."
        PRD §2.1: "If the value of `X-User-Role` is not one of the roles the called endpoint declares, the request is rejected with `ERR_ROLE_NOT_PERMITTED`."
        PRD §2.1: "That check guards the respondent's four writes — producing records against a data call, answering a criticism, proposing a corrective action plan, and executing a consent order — and equally every read the respondent makes against a record whose owning examination belongs to another carrier."

        Design: Corner/rbac/shared_reads_are_open_to_their_declared_roles_and_closed_to_the_rest
        """
        scenario = setup_examination_in_negotiation()
        exam_id = scenario["exam_id"]
        subject = scenario["respondent_headers"]

        for headers in (ANALYST, EIC, SUPERVISOR, COORDINATOR):
            validate_success(api.get_examination(exam_id, headers))
        as_carrier = validate_success(api.get_examination(exam_id, subject))
        assert as_carrier["status"] == "NEGOTIATION"

        for headers in (SUPERVISOR, COORDINATOR):
            summary = validate_success(api.get_exposure_summary(exam_id, headers))
            assert summary["examination_id"] == exam_id

        # The examiner in charge, the analyst and the subject carrier are all
        # outside the summary's declared roles.
        for headers in (EIC, ANALYST, subject):
            validate_error(
                api.get_exposure_summary(exam_id, headers),
                ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
            )

    def test_the_analyst_reads_the_examination_index_but_not_its_workpapers(self, api):
        """The analyst's grant stops at the index and the scope.

        PRD §2.1: "Owns the carrier data set, the scoring cycle and target selection; has no authority over examination fieldwork or enforcement."
        PRD §2.1: "If the value of `X-User-Role` is not one of the roles the called endpoint declares, the request is rejected with `ERR_ROLE_NOT_PERMITTED`."

        Design: Corner/rbac/the_analysis_role_reads_the_examination_index_but_not_the_examination_workpapers
        """
        scenario = setup_examination_in_scoping()
        exam_id = scenario["exam_id"]
        scope_area = add_scope_area(exam_id, "CLAIMS", population_size=4000, sample_size=10)

        index, _ = validate_paginated(
            api.list_examinations(ANALYST, {"insurer_id": scenario["insurer_id"]})
        )
        assert [row["id"] for row in index] == [exam_id]
        assert validate_success(api.get_examination(exam_id, ANALYST))["status"] == "SCOPING"
        areas, _ = validate_paginated(api.list_scope_areas(exam_id, ANALYST))
        assert areas[0]["area"] == "CLAIMS"
        _, score_meta = validate_paginated(
            api.list_insurer_analysis_scores(scenario["insurer_id"], ANALYST)
        )
        assert score_meta["total_count"] == 0

        validate_error(
            api.list_fieldwork_activities(exam_id, ANALYST),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
        )
        validate_error(
            api.list_criticisms(ANALYST), ApiErrorId.ERR_ROLE_NOT_PERMITTED.value
        )
        validate_error(
            api.list_consent_orders(exam_id, ANALYST),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
        )
        validate_error(
            api.get_scope_area(scope_area["id"], ANALYST),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
        )


class TestClockExemption:
    def test_every_role_drives_the_clock_and_none_needs_an_identity(self, api):
        """The clock is the one endpoint excluded from the identity requirement.

        PRD §2.1: "The clock endpoint is the single exception to the `X-User-ID` requirement; all five roles may drive it."
        PRD §2.4: "A test-driving capability sets it to an explicit RFC3339 UTC instant supplied as `to_iso8601`, and answers with the object `{ current_utc, data_calls_flagged_overdue }` where `current_utc` echoes the new instant and `data_calls_flagged_overdue` counts the data calls the move swept into `OVERDUE`."

        Design: Corner/rbac/the_clock_endpoint_is_the_single_authorisation_exemption
        """
        moves = (
            ("2026-09-01T09:00:00Z", ANALYST),
            ("2026-09-01T10:00:00Z", EIC),
            ("2026-09-01T11:00:00Z", SUPERVISOR),
            ("2026-09-01T12:00:00Z", COORDINATOR),
            (
                "2026-09-01T13:00:00Z",
                make_insurer_respondent_headers(
                    "77777777-7777-7777-7777-777777777777"
                ),
            ),
        )
        for instant, headers in moves:
            moved = validate_success(api.set_clock(clock_payload(instant), headers))
            assert moved["current_utc"] == instant

        # No X-User-ID header at all, which no other endpoint permits.
        anonymous = validate_success(
            api.set_clock(
                clock_payload("2026-09-01T14:00:00Z"),
                _clock_headers_without_user_id("InsurerRespondent"),
            )
        )
        assert anonymous["current_utc"] == "2026-09-01T14:00:00Z"
        assert anonymous["data_calls_flagged_overdue"] == 0

        anonymous_supervisor = validate_success(
            api.set_clock(
                clock_payload("2026-09-01T15:00:00Z"),
                _clock_headers_without_user_id("SupervisingExaminer"),
            )
        )
        assert anonymous_supervisor["current_utc"] == "2026-09-01T15:00:00Z"

    def test_the_clock_is_exempt_from_authentication_but_not_from_validation(self, api):
        """An infrastructure exemption is not an unguarded endpoint.

        PRD §2.11: "Malformed-request rejection in band 6 covers, across all write endpoints: a required field missing; a field carrying the wrong JSON type; an enum field carrying a value outside its declared set; a monetary or count field that is negative; `sample_size`, `population_size`, `records_requested`, `milestone_count` or `target_slot_capacity` that is not at least 1; a date field that is not formatted `YYYY-MM-DD`; `fieldwork_end_date` that is not strictly after `fieldwork_start_date`; `reference_period_end` that is not strictly after `reference_period_start`; `default_fieldwork_end` that is not strictly after `default_fieldwork_start`; a percentage field outside the inclusive range 0.00 to 100.00; a `narrative`, `summary`, `public_summary` or `rebuttal_note` shorter than 20 characters; a `participating_states` array that is empty, contains a duplicate `state_code`, contains a `state_code` that is not exactly two uppercase letters, or whose `policy_count_in_state` values total zero; a `reviews` array that is empty or contains a duplicate `file_reference`; a `min_composite_score` outside the inclusive range 0.00 to 100.00; a `to_iso8601` that is not an RFC3339 UTC instant; and a scope-lock attempt on an examination that has no scope areas at all."

        Design: Corner/rbac/the_clock_endpoint_is_the_single_authorisation_exemption
        """
        validate_error(
            api.set_clock(clock_payload("01/09/2026 15:00"), SUPERVISOR),
            ApiErrorId.ERR_INVALID_REQUEST.value,
        )
        validate_error(
            api.set_clock(clock_payload("2026-09-01T15:00:00+02:00"), SUPERVISOR),
            ApiErrorId.ERR_INVALID_REQUEST.value,
        )


class TestCriticismAuthorshipAlternates:
    def test_three_roles_author_four_hops_and_no_neighbour_may_substitute(self, api):
        """Issuance, response, rebuttal and finalization each belong to one role.

        PRD §3.6: "With an area tested, the `ExaminerInCharge` issues a **criticism** by supplying the `exam_id`, the `scope_area_id` the finding rests on, the `statute_citation` naming the statute or regulation cited, a `severity` of `MINOR`, `MATERIAL` or `EGREGIOUS`, and the `affected_file_count` of sampled files the criticism covers."
        PRD §3.7: "The `ExaminerInCharge` may rebut a `RESPONDED` criticism, supplying a `rebuttal_note` of at least 20 characters, which returns the criticism to `ISSUED` for another round, raises `rebuttal_count` by 1 and increments the criticism's `version` by 1."
        PRD §2.1: "Never finalizes a criticism, approves a plan, drafts an order or publishes a report."
        PRD §2.11: "Checks are evaluated in the following bands, in this order, and the first band that produces a rejection determines the response:"

        Design: Corner/rbac/the_criticism_negotiation_alternates_authorship_on_every_hop
        """
        scenario = setup_examination_in_criticism()
        criticism_body = criticism_payload(
            scenario["exam_id"], scenario["scope_area_id"], "MATERIAL", 3
        )
        validate_error(
            api.issue_criticism(criticism_body, SUPERVISOR),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
        )
        criticism = validate_success(api.issue_criticism(criticism_body, EIC), 201)

        # The criticism is ISSUED rather than RESPONDED, but the role band is
        # evaluated before the lifecycle-state band.
        validate_error(
            api.rebut_criticism(criticism["id"], rebuttal_payload(), SUPERVISOR),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
        )

        first = validate_success(
            api.create_company_response(
                criticism["id"],
                company_response_payload("DISPUTE"),
                scenario["respondent_headers"],
            ),
            201,
        )
        assert first["round_number"] == 1

        rebutted = validate_success(
            api.rebut_criticism(criticism["id"], rebuttal_payload(), EIC)
        )
        assert rebutted["status"] == "ISSUED"
        assert rebutted["response_round"] == 1
        assert rebutted["rebuttal_count"] == 1

        second = validate_success(
            api.create_company_response(
                criticism["id"],
                company_response_payload("DISPUTE"),
                scenario["respondent_headers"],
            ),
            201,
        )
        assert second["round_number"] == 2

        validate_error(
            api.finalize_criticism(
                criticism["id"], criticism_finalize_payload("SUSTAINED", 20), EIC
            ),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
        )
        finalized = validate_success(
            api.finalize_criticism(
                criticism["id"],
                criticism_finalize_payload("SUSTAINED", 20),
                SUPERVISOR_B,
            )
        )
        assert finalized["status"] == "SUSTAINED"
