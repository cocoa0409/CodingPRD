"""Error catalogue, part two: enforcement-phase state gates, optimistic
concurrency, workpaper completeness, sampling bounds, lead-state election, the
examiner-slot ledger and the empty restitution pool.

Every scenario is built from scratch through the API declared by the PRD: the
harness relaunches the server before each test, so each test starts against an
empty database and owns all of its own state.
"""

from test_helpers import (
    ApiErrorId,
    COORDINATOR,
    EIC,
    SUPERVISOR,
    add_scope_area,
    assert_collaboration,
    assert_consent_order,
    assert_corrective_action_plan,
    assert_criticism,
    assert_scope_area,
    assert_slot_ledger_conserved,
    build_reviews,
    bulk_review,
    collaboration_payload,
    consent_order_payload,
    corrective_action_plan_payload,
    create_analysis_cycle,
    criticism_payload,
    data_call_payload,
    draft_consent_order,
    examination_payload,
    finalize_criticism,
    issue_criticism,
    issue_data_call,
    make_insurer_respondent_headers,
    open_collaboration,
    open_examination,
    propose_plan,
    publish_report_payload,
    read_collaboration,
    read_cycle,
    read_examination,
    read_exposure_summary,
    read_scope_area,
    record_fieldwork_activity,
    register_insurer,
    respond_to_criticism,
    score_cycle,
    scope_area_payload,
    select_targets,
    setup_area_in_fieldwork,
    setup_examination_in_criticism,
    setup_examination_in_negotiation,
    setup_examination_in_order_pending,
    setup_examination_in_scoping,
    setup_examination_with_executed_order,
    setup_locked_examination,
    validate_error,
    validate_paginated,
)

# The three-state panel whose members all declare that they cannot contribute
# examiners, and the same panel with one member resourced.
UNRESOURCED_PANEL = [
    {"state_code": "AZ", "policy_count_in_state": 50_000, "has_examiner_resources": False},
    {"state_code": "UT", "policy_count_in_state": 30_000, "has_examiner_resources": False},
    {"state_code": "NM", "policy_count_in_state": 12_000, "has_examiner_resources": False},
]
PANEL_WITH_ONE_RESOURCED_STATE = [
    {"state_code": "AZ", "policy_count_in_state": 50_000, "has_examiner_resources": False},
    {"state_code": "UT", "policy_count_in_state": 30_000, "has_examiner_resources": True},
    {"state_code": "NM", "policy_count_in_state": 12_000, "has_examiner_resources": False},
]


def _examination_in_criticism_with_one_issued_criticism():
    """One examination in CRITICISM carrying a single ISSUED criticism."""
    scenario = setup_examination_in_criticism()
    criticism = issue_criticism(
        scenario["exam_id"], scenario["scope_area_id"], "MATERIAL", 3
    )
    scenario["criticism"] = criticism
    scenario["criticism_id"] = criticism["id"]
    scenario["examination"] = read_examination(scenario["exam_id"])
    return scenario


# ─── ERR_EXAM_NOT_IN_NEGOTIATION ──────────────────────────────────────────


class TestPlanAndOrderRequireNegotiation:
    def test_plan_filed_from_criticism_is_refused_even_with_the_right_version(self, api):
        """The carrier cannot file a remediation plan before the criticism is disposed of.

        PRD §3.8: "The acting `X-User-ID` must equal the examination's `insurer_id`, otherwise `ERR_NOT_EXAM_SUBJECT`; the examination's `status` must be `NEGOTIATION`, otherwise `ERR_EXAM_NOT_IN_NEGOTIATION`."
        PRD §3.7: "Third, if that leaves the examination with `open_criticism_count` of 0 and `sustained_criticism_count` of 1 or more, the examination advances `CRITICISM → NEGOTIATION`, incrementing its `version` again and raising the subject carrier's `pending_enforcement_exam_count` by 1."

        Design: Corner/errors/err_exam_not_in_negotiation_before_a_plan_is_invited
        """
        scenario = _examination_in_criticism_with_one_issued_criticism()
        exam_id = scenario["exam_id"]
        respondent = make_insurer_respondent_headers(scenario["insurer_id"])
        assert scenario["examination"]["status"] == "CRITICISM"

        # The pinned version is correct, so only the lifecycle state can refuse.
        refused = api.propose_corrective_action_plan(
            exam_id,
            corrective_action_plan_payload(scenario["examination"]["version"]),
            respondent,
        )
        validate_error(refused, ApiErrorId.ERR_EXAM_NOT_IN_NEGOTIATION.value, 409)

        _, meta = validate_paginated(
            api.list_corrective_action_plans(exam_id, SUPERVISOR)
        )
        assert meta["total_count"] == 0, "the refused filing created no plan row"

        # Sustaining the criticism opens the negotiation phase.
        respond_to_criticism(scenario["criticism_id"], scenario["insurer_id"], "DISPUTE")
        finalize_criticism(scenario["criticism_id"], "SUSTAINED", 20)
        assert read_examination(exam_id)["status"] == "NEGOTIATION"

        plan = propose_plan(exam_id, scenario["insurer_id"])
        assert_corrective_action_plan(plan)
        assert plan["status"] == "PROPOSED"
        assert plan["revision_round"] == 1

    def test_consent_order_drafted_from_criticism_is_refused_on_state(self, api):
        """An order drafted before the criticism phase closes answers on state.

        PRD §3.8: "The examination's `status` must be `NEGOTIATION` or `ORDER_PENDING`, otherwise `ERR_EXAM_NOT_IN_NEGOTIATION`, and the examination must already hold a corrective action plan in `APPROVED`, otherwise `ERR_CAP_NOT_APPROVED`."

        Design: Corner/errors/err_exam_not_in_negotiation_before_a_plan_is_invited
        """
        scenario = _examination_in_criticism_with_one_issued_criticism()
        exam_id = scenario["exam_id"]
        assert scenario["examination"]["status"] == "CRITICISM"

        refused = api.draft_consent_order(
            exam_id,
            consent_order_payload(
                scenario["examination"]["version"], "NV-MC-2026-0042", "PER_VIOLATION"
            ),
            SUPERVISOR,
        )
        validate_error(refused, ApiErrorId.ERR_EXAM_NOT_IN_NEGOTIATION.value, 409)

        _, meta = validate_paginated(api.list_consent_orders(exam_id, SUPERVISOR))
        assert meta["total_count"] == 0, "the refused draft created no consent order row"


# ─── ERR_EXAM_NOT_READY_FOR_PUBLICATION ───────────────────────────────────


class TestPublicationIsLegalFromTwoStatesOnly:
    def test_publication_from_the_data_call_stage_is_refused(self, api):
        """A wholly premature publication attempt is refused on state.

        PRD §3.10: "Publication from any state other than `CRITICISM` or `ORDER_PENDING` is rejected with `ERR_EXAM_NOT_READY_FOR_PUBLICATION`, and so is publication from `CRITICISM` when the examination already has one or more `SUSTAINED` criticisms — such an examination must route through `NEGOTIATION` and an executed order rather than publishing directly."

        Design: Corner/errors/err_exam_not_ready_for_publication_from_the_data_call_stage
        """
        scenario = setup_locked_examination()
        exam_id = scenario["exam_id"]
        assert scenario["examination"]["status"] == "DATA_CALL"

        refused = api.publish_report(
            exam_id,
            publish_report_payload(
                public_summary=(
                    "The department attempts to publish before any fieldwork has "
                    "been performed."
                )
            ),
            SUPERVISOR,
        )
        validate_error(refused, ApiErrorId.ERR_EXAM_NOT_READY_FOR_PUBLICATION.value, 409)

        after = read_examination(exam_id)
        assert after["status"] == "DATA_CALL"
        assert after.get("report_published_at") is None

    def test_publication_from_negotiation_is_refused_and_changes_nothing(self, api):
        """NEGOTIATION sits outside the two permitted publication states.

        PRD §3.10: "Publication from any state other than `CRITICISM` or `ORDER_PENDING` is rejected with `ERR_EXAM_NOT_READY_FOR_PUBLICATION`, and so is publication from `CRITICISM` when the examination already has one or more `SUSTAINED` criticisms — such an examination must route through `NEGOTIATION` and an executed order rather than publishing directly."

        Design: Corner/errors/err_exam_not_ready_for_publication_from_the_data_call_stage
        """
        scenario = setup_examination_in_negotiation()
        exam_id = scenario["exam_id"]
        assert scenario["examination"]["status"] == "NEGOTIATION"

        refused = api.publish_report(
            exam_id,
            publish_report_payload(
                public_summary=(
                    "The department attempts to publish while an enforcement track "
                    "is still open."
                )
            ),
            SUPERVISOR,
        )
        validate_error(refused, ApiErrorId.ERR_EXAM_NOT_READY_FOR_PUBLICATION.value, 409)

        after = read_examination(exam_id)
        assert after["status"] == "NEGOTIATION"
        assert after.get("report_published_at") is None

        # Publication would have closed the tested area; the refusal closed nothing.
        area = read_scope_area(scenario["scope_area_id"])
        assert_scope_area(area)
        assert area["status"] == "TESTED"

        _, meta = validate_paginated(
            api.list_examinations(SUPERVISOR, {"predecessor_exam_id": exam_id})
        )
        assert meta["total_count"] == 0, "no follow-up examination was created"


# ─── ERR_STALE_EXAMINATION_VERSION ────────────────────────────────────────


class TestStaleExaminationVersionOnBothPinnedWrites:
    def test_replaying_a_spent_version_on_a_second_plan_is_refused(self, api):
        """Creating the first plan is itself what invalidates the carrier's token.

        PRD §2.6: "If `expected_examination_version` does not equal the examination's current `version`, the request is rejected with `ERR_STALE_EXAMINATION_VERSION` and HTTP 412."
        PRD §3.8: "A new plan opens in `PROPOSED` and supersedes any earlier plan on the examination whose `status` is `PROPOSED` or `REVISION_REQUESTED`: that earlier plan moves to `SUPERSEDED` and has its `version` incremented by 1, and the new plan takes a `revision_round` one greater than the superseded plan's."

        Design: Corner/errors/err_stale_examination_version_on_both_optimistic_concurrency_endpoints
        """
        scenario = setup_examination_in_negotiation()
        exam_id = scenario["exam_id"]
        respondent = make_insurer_respondent_headers(scenario["insurer_id"])

        v0 = read_examination(exam_id)["version"]
        first = propose_plan(exam_id, scenario["insurer_id"], v0)
        assert first["revision_round"] == 1
        v1 = read_examination(exam_id)["version"]
        assert v1 == v0 + 1, "proposing a plan increments the examination version"

        refused = api.propose_corrective_action_plan(
            exam_id,
            corrective_action_plan_payload(
                v0, milestone_count=5, completion_due_date="2027-04-30"
            ),
            respondent,
        )
        validate_error(refused, ApiErrorId.ERR_STALE_EXAMINATION_VERSION.value, 412)

        second = propose_plan(
            exam_id,
            scenario["insurer_id"],
            v1,
            milestone_count=5,
            completion_due_date="2027-04-30",
        )
        assert second["revision_round"] == 2

        plans, meta = validate_paginated(
            api.list_corrective_action_plans(exam_id, SUPERVISOR)
        )
        assert meta["total_count"] == 2, "the refused plan created nothing"
        by_id = {plan["id"]: plan for plan in plans}
        assert by_id[first["id"]]["status"] == "SUPERSEDED"
        assert by_id[second["id"]]["status"] == "PROPOSED"

    def test_replaying_a_spent_version_on_a_second_order_is_refused(self, api):
        """The refused draft neither creates a row nor voids the standing one.

        PRD §2.6: "A mismatch against the examination's current `version` is rejected with `ERR_STALE_EXAMINATION_VERSION` and HTTP 412."
        PRD §3.8: "Drafting voids any existing `DRAFT` order on the examination — that order moves to `VOIDED` and has its `version` incremented by 1 — records `drafted_by_user_id` from `X-User-ID` as the segregation-of-duties key, opens the new order in `DRAFT`, and increments the examination's `version` by 1."

        Design: Corner/errors/err_stale_examination_version_on_both_optimistic_concurrency_endpoints
        """
        scenario = setup_examination_in_order_pending()
        exam_id = scenario["exam_id"]

        v0 = read_examination(exam_id)["version"]
        first = draft_consent_order(
            exam_id,
            v0,
            order_number="NV-MC-2026-0042",
            penalty_variant="PER_VIOLATION",
        )
        assert_consent_order(first)
        assert read_examination(exam_id)["version"] == v0 + 1

        refused = api.draft_consent_order(
            exam_id,
            consent_order_payload(v0, "NV-MC-2026-0043", "TIERED_AGGREGATE"),
            SUPERVISOR,
        )
        validate_error(refused, ApiErrorId.ERR_STALE_EXAMINATION_VERSION.value, 412)

        orders, meta = validate_paginated(api.list_consent_orders(exam_id, SUPERVISOR))
        assert meta["total_count"] == 1
        assert orders[0]["id"] == first["id"]
        assert orders[0]["status"] == "DRAFT", "the standing draft was not voided"


# ─── ERR_FIELDWORK_NOT_DOCUMENTED ─────────────────────────────────────────


class TestFieldworkDocumentationGate:
    def test_criticism_needs_an_interview_workpaper_on_an_on_site_examination(self, api):
        """A walkthrough alone does not document an ON_SITE examination.

        PRD §3.6: "The examination's fieldwork must be documented: it must hold at least one fieldwork activity whose `activity_type` is `SYSTEM_WALKTHROUGH`, and — only when the examination's `mode` is `ON_SITE` — at least one whose `activity_type` is `INTERVIEW`; a `DESK` examination requires the walkthrough alone."
        PRD §3.6: "A missing requirement is `ERR_FIELDWORK_NOT_DOCUMENTED`."

        Design: Corner/errors/err_fieldwork_not_documented_without_an_interview_workpaper
        """
        scenario = setup_area_in_fieldwork()
        exam_id = scenario["exam_id"]
        area_id = scenario["scope_area_id"]

        walkthrough = record_fieldwork_activity(exam_id, "SYSTEM_WALKTHROUGH", "CLAIMS")
        assert walkthrough["activity_type"] == "SYSTEM_WALKTHROUGH"
        assert walkthrough["documented"] is True

        bulk_review(
            scenario["data_call_id"], build_reviews(scenario["file_references"])
        )
        assert read_scope_area(area_id)["status"] == "TESTED"
        assert read_examination(exam_id)["status"] == "CRITICISM"
        assert read_examination(exam_id)["mode"] == "ON_SITE"

        refused = api.issue_criticism(
            criticism_payload(exam_id, area_id, "MATERIAL", 3), EIC
        )
        validate_error(refused, ApiErrorId.ERR_FIELDWORK_NOT_DOCUMENTED.value, 409)

        record_fieldwork_activity(
            exam_id,
            "INTERVIEW",
            "CLAIMS",
            participant_name="L. Ortiz",
            participant_title="Claims Manager",
            summary="Interviewed the claims manager on prompt-pay handling and denials.",
            evidence_ref="WP-CLM-02",
        )
        criticism = issue_criticism(exam_id, area_id, "MATERIAL", 3)
        assert_criticism(criticism)
        assert criticism["status"] == "ISSUED"


# ─── ERR_SAMPLE_SIZE_BELOW_MINIMUM ────────────────────────────────────────


class TestStatutoryMinimumSampleSize:
    def test_on_site_examination_requires_a_sample_of_at_least_ten(self, api):
        """Nine files are below the ON_SITE floor; exactly ten clears it.

        PRD §3.3: "Statutory minimum sample sizes depend on the examination's `mode`: an `ON_SITE` examination requires a `sample_size` of at least 10, a `DESK` examination at least 5, and a smaller figure is rejected with `ERR_SAMPLE_SIZE_BELOW_MINIMUM` at HTTP 422."

        Design: Corner/errors/err_sample_size_below_minimum_in_both_modes
        """
        scenario = setup_examination_in_scoping(mode="ON_SITE")
        exam_id = scenario["exam_id"]

        refused = api.create_scope_area(
            exam_id,
            scope_area_payload("CLAIMS", population_size=4000, sample_size=9),
            EIC,
        )
        validate_error(refused, ApiErrorId.ERR_SAMPLE_SIZE_BELOW_MINIMUM.value, 422)

        accepted = add_scope_area(
            exam_id, "CLAIMS", population_size=4000, sample_size=10
        )
        assert_scope_area(accepted)
        assert accepted["sample_size"] == 10

    def test_desk_examination_requires_a_sample_of_at_least_five(self, api):
        """Four files are below the DESK floor; five and nine both clear it.

        PRD §3.3: "Statutory minimum sample sizes depend on the examination's `mode`: an `ON_SITE` examination requires a `sample_size` of at least 10, a `DESK` examination at least 5, and a smaller figure is rejected with `ERR_SAMPLE_SIZE_BELOW_MINIMUM` at HTTP 422."

        Design: Corner/errors/err_sample_size_below_minimum_in_both_modes
        """
        scenario = setup_examination_in_scoping(mode="DESK")
        exam_id = scenario["exam_id"]

        refused = api.create_scope_area(
            exam_id,
            scope_area_payload("CLAIMS", population_size=4000, sample_size=4),
            EIC,
        )
        validate_error(refused, ApiErrorId.ERR_SAMPLE_SIZE_BELOW_MINIMUM.value, 422)

        at_floor = add_scope_area(exam_id, "CLAIMS", population_size=4000, sample_size=5)
        assert at_floor["sample_size"] == 5

        # Nine is illegal ON_SITE and legal here, so the bound is read from the mode.
        above_floor = add_scope_area(
            exam_id, "RATING", population_size=500, sample_size=9
        )
        assert above_floor["sample_size"] == 9


# ─── ERR_NO_ELIGIBLE_LEAD_STATE ───────────────────────────────────────────


class TestLeadStateElectionNeedsAResourcedParticipant:
    def test_wholly_unresourced_panel_creates_no_collaboration_row(self, api):
        """The lead is mandatory, so an unelectable panel is refused outright.

        PRD §3.9: "If no participant has examiner resources, the request is rejected with `ERR_NO_ELIGIBLE_LEAD_STATE` at HTTP 422 and **no** collaboration row is created."
        PRD §3.9: "Only participants whose `has_examiner_resources` is true are eligible."

        Design: Corner/errors/err_no_eligible_lead_state_for_an_unresourced_panel
        """
        scenario = setup_examination_in_scoping()
        exam_id = scenario["exam_id"]

        refused = api.open_collaboration(
            exam_id,
            collaboration_payload(
                UNRESOURCED_PANEL, call_reference="NAIC-CAWG-2026-0117"
            ),
            COORDINATOR,
        )
        validate_error(refused, ApiErrorId.ERR_NO_ELIGIBLE_LEAD_STATE.value, 422)

        _, meta = validate_paginated(api.list_collaborations(exam_id, COORDINATOR))
        assert meta["total_count"] == 0, "no row with a null lead survived"

        # The same call reference is still available because nothing was persisted.
        collaboration = open_collaboration(
            exam_id,
            PANEL_WITH_ONE_RESOURCED_STATE,
            call_reference="NAIC-CAWG-2026-0117",
        )
        assert_collaboration(collaboration)
        assert collaboration["participant_count"] == 3
        # UT leads over the larger AZ because resources filter before ranking.
        assert collaboration["lead_state_code"] == "UT"


# ─── ERR_SAMPLE_EXCEEDS_POPULATION ────────────────────────────────────────


class TestSampleAndRequestBoundedByPopulation:
    def test_sample_size_may_not_exceed_the_area_population(self, api):
        """Eleven files out of ten is refused; exactly ten is accepted.

        PRD §3.3: "A `sample_size` exceeding the `population_size` is rejected with `ERR_SAMPLE_EXCEEDS_POPULATION`."

        Design: Corner/errors/err_sample_exceeds_population_on_area_and_data_call
        """
        scenario = setup_examination_in_scoping()
        exam_id = scenario["exam_id"]

        refused = api.create_scope_area(
            exam_id,
            scope_area_payload("CLAIMS", population_size=10, sample_size=11),
            EIC,
        )
        validate_error(refused, ApiErrorId.ERR_SAMPLE_EXCEEDS_POPULATION.value, 422)

        accepted = add_scope_area(exam_id, "CLAIMS", population_size=10, sample_size=10)
        assert_scope_area(accepted)
        assert accepted["population_size"] == 10
        assert accepted["sample_size"] == 10

    def test_records_requested_may_not_exceed_the_area_population(self, api):
        """The same code guards the data-call request count against the population.

        PRD §3.4: "The examiner supplies `records_requested` (at least 1, and never more than the area's `population_size` — an excess is `ERR_SAMPLE_EXCEEDS_POPULATION`) and a `response_due_date`."

        Design: Corner/errors/err_sample_exceeds_population_on_area_and_data_call
        """
        scenario = setup_locked_examination(areas=(("CLAIMS", 10, 10),))
        area_id = scenario["scope_area_id"]

        refused = api.create_data_call(
            area_id,
            data_call_payload(records_requested=11, response_due_date="2026-09-15"),
            EIC,
        )
        validate_error(refused, ApiErrorId.ERR_SAMPLE_EXCEEDS_POPULATION.value, 422)

        data_call = issue_data_call(
            area_id, records_requested=10, response_due_date="2026-09-15"
        )
        assert data_call["records_requested"] == 10
        assert data_call["status"] == "ISSUED"


# ─── ERR_CYCLE_SLOTS_EXHAUSTED ────────────────────────────────────────────


class TestManualAttachmentSharesTheSlotLedger:
    def test_naming_a_spent_cycle_on_a_new_examination_is_refused(self, api):
        """A cycle whose capacity selection spent refuses the next attachment.

        PRD §3.3: "An optional `cycle_id` attributes the examination to an existing cycle and consumes one of its slots; a `cycle_id` naming a cycle whose `slots_available` is 0 is rejected with `ERR_CYCLE_SLOTS_EXHAUSTED`."

        Design: Corner/errors/err_cycle_slots_exhausted_on_a_manual_attachment
        """
        register_insurer(
            name="Aurora Mutual Insurance Company",
            naic_code="10001",
            policy_count_in_force=100_000,
            confirmed_complaints_12mo=500,
            financial_stress_score=100,
            consumer_trend_score=100,
        )
        boreal = register_insurer(
            name="Boreal Casualty Company",
            naic_code="10002",
            policy_count_in_force=40_000,
            confirmed_complaints_12mo=40,
            financial_stress_score=10,
            consumer_trend_score=10,
        )
        cycle = create_analysis_cycle(
            cycle_label="2026-H2-MARKET-ANALYSIS", target_slot_capacity=1
        )
        score_cycle(cycle["id"])
        cycle = select_targets(cycle["id"])
        assert cycle["slots_available"] == 0, "selection spent the only slot"

        attachment = examination_payload(
            boreal["id"],
            exam_type="TARGETED_EXAM",
            mode="DESK",
            fieldwork_start_date="2027-01-04",
            fieldwork_end_date="2027-03-31",
            cycle_id=cycle["id"],
        )
        refused = api.open_examination(attachment, SUPERVISOR)
        validate_error(refused, ApiErrorId.ERR_CYCLE_SLOTS_EXHAUSTED.value, 409)

        # The identical request without cycle_id consumes nothing and is accepted.
        standalone = open_examination(
            boreal["id"],
            exam_type="TARGETED_EXAM",
            mode="DESK",
            fieldwork_start_date="2027-01-04",
            fieldwork_end_date="2027-03-31",
        )
        assert standalone.get("cycle_id") is None

        after = read_cycle(cycle["id"])
        assert after["slots_committed"] == 1
        assert after["slots_available"] == 0
        assert_slot_ledger_conserved(after)


# ─── ERR_RESTITUTION_NOT_CONSERVED ────────────────────────────────────────


class TestAllocationRefusesAnEmptyRestitutionPool:
    def test_allocation_with_a_zero_restitution_aggregate_is_refused(self, api):
        """A real penalty with no measured harm leaves nothing to allocate.

        PRD §3.9: "A collaboration whose `status` is not `ACTIVE` is rejected with `ERR_ENFORCEMENT_RECORD_STATE_INVALID`; the examination must already hold a consent order in `EXECUTED`, otherwise `ERR_ORDER_NOT_EXECUTED`; and an examination whose `aggregate_restitution_cents` is 0 has nothing to allocate, so the attempt is rejected with `ERR_RESTITUTION_NOT_CONSERVED`."

        Design: Corner/errors/err_restitution_not_conserved_on_an_empty_pool
        """
        scenario = setup_examination_with_executed_order(
            penalty_variant="PER_VIOLATION",
            order_number="NV-MC-2026-0042",
            criticism_severity="MINOR",
            penalty_units=5,
            harm_cents=(0, 0, 0),
            severity="MINOR",
            with_collaboration=True,
        )
        collaboration_id = scenario["collaboration_id"]

        # Every earlier gate on the endpoint is satisfied.
        assert scenario["consent_order"]["status"] == "EXECUTED"
        assert scenario["consent_order"]["restitution_cents"] == 0
        before = read_collaboration(collaboration_id)
        assert before["status"] == "ACTIVE"
        assert scenario["examination"]["aggregate_restitution_cents"] == 0
        assert scenario["examination"]["penalty_units_total"] == 5

        refused = api.allocate_restitution(collaboration_id, COORDINATOR)
        validate_error(refused, ApiErrorId.ERR_RESTITUTION_NOT_CONSERVED.value, 409)

        after = read_collaboration(collaboration_id)
        assert after["status"] == "ACTIVE", "the panel is not driven to SETTLED"
        assert after["allocated_total_cents"] == 0
        assert all(
            state["allocated_cents"] == 0 for state in after["participating_states"]
        )

        summary = read_exposure_summary(scenario["exam_id"])
        assert summary["aggregate_restitution_cents"] == 0
        assert summary["penalty_units_total"] == 5
