"""Validation gates: authorisation, segregation of duties, shape, uniqueness and ceilings.

Every scenario is built from scratch through the API — the harness relaunches the
server before each test, so each test starts against an empty database.
"""

from test_helpers import (
    ANALYST,
    COORDINATOR,
    EIC,
    NON_EXISTENT_UUID,
    SUPERVISING_EXAMINER_B_ID,
    SUPERVISING_EXAMINER_ID,
    SUPERVISOR,
    SUPERVISOR_B,
    TEST_DEFAULTS,
    ApiErrorId,
    add_scope_area,
    analysis_cycle_payload,
    assert_collaboration,
    assert_consent_order,
    assert_criticism,
    assert_examination,
    assert_scope_area,
    assert_slot_ledger_conserved,
    build_reviews,
    build_user_headers,
    bulk_review,
    clock_payload,
    collaboration_payload,
    consent_order_payload,
    create_analysis_cycle,
    criticism_finalize_payload,
    criticism_payload,
    data_call_payload,
    data_call_response_payload,
    draft_consent_order,
    examination_payload,
    insurer_payload,
    is_iso8601_timestamp,
    issue_criticism,
    issue_data_call,
    lock_scope,
    make_examiner_in_charge_headers,
    make_insurer_respondent_headers,
    open_collaboration,
    open_examination,
    publish_report_payload,
    read_collaboration,
    read_criticism,
    read_cycle,
    read_data_call,
    read_examination,
    read_exposure_summary,
    read_insurer,
    record_fieldwork_activity,
    register_insurer,
    respond_to_criticism,
    scope_area_payload,
    score_cycle,
    select_targets,
    setup_area_in_fieldwork,
    setup_examination_in_criticism,
    setup_examination_in_order_pending,
    setup_examination_in_scoping,
    setup_examination_with_executed_order,
    setup_locked_examination,
    validate_error,
    validate_paginated,
    validate_success,
)

# A second carrier, so a scenario can hold two examinations without the exclusive
# fieldwork occupancy rule on one carrier getting in the way.
BOREAL = {"name": "Boreal Casualty Company", "naic_code": "10002"}

# The frozen exposure the canonical claims sample produces: three MATERIAL files
# quantifying 25000 + 18000 + 7333 cents over ten reviewed files, extrapolated
# across a population of 4000.
EXTRAPOLATED_EXPOSURE_CENTS = 20_132_000


def _role_only_headers(role: str) -> dict:
    """Headers carrying X-User-Role but no X-User-ID at all."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def _claims_area_tested_with_walkthrough_only(mode: str, insurer_overrides=None) -> dict:
    """One examination whose CLAIMS area is TESTED with a single walkthrough on file.

    The interview workpaper is deliberately withheld so the mode-conditional
    documentation requirement can be observed at criticism issuance.
    """
    scenario = setup_area_in_fieldwork(insurer_overrides=insurer_overrides, mode=mode)
    record_fieldwork_activity(scenario["exam_id"], "SYSTEM_WALKTHROUGH", "CLAIMS")
    bulk_review(scenario["data_call_id"], build_reviews(scenario["file_references"]))
    return scenario


# ─── The control case: every gate is simultaneously satisfiable ────────────


class TestFullLifecycleSatisfiesEveryGate:
    def test_the_chain_from_scoping_to_publication_clears_every_gate(self, api):
        """A licensed carrier walks the whole workflow and the report publishes.

        PRD §3.8: "Execution stamps `executed_at` from the logical clock, moves the order to `EXECUTED`, increments the order's `version` by 1, and raises the subject carrier's `lifetime_restitution_ordered_cents` by the order's frozen `restitution_cents`."
        PRD §3.10: "The examination advances `ORDER_PENDING → PUBLISHED`, stamping `report_published_at` and recording `public_summary` as before, but here `followup_required` is set to true and `followup_due_date` is computed."
        PRD §3.10: "It carries the same `insurer_id`, a `predecessor_exam_id` pointing at the examination just published, no `cycle_id`, an `exam_type` of `TARGETED_EXAM`, a `mode` of `DESK` regardless of the predecessor's mode, the predecessor's `lead_state_code` copied across, a `fieldwork_start_date` equal to `followup_due_date`, and a `fieldwork_end_date` sixty days after `followup_due_date`."
        PRD §3.10: "Every `TESTED` scope area moves to `CLOSED`."

        Design: Corner/validations/the_full_lifecycle_satisfies_every_gate_from_selection_to_publication
        """
        scenario = setup_examination_with_executed_order(
            penalty_variant="PER_VIOLATION", order_number="NV-MC-2026-0042"
        )
        exam_id = scenario["exam_id"]
        assert scenario["consent_order"]["status"] == "EXECUTED"
        assert scenario["consent_order"]["restitution_cents"] == EXTRAPOLATED_EXPOSURE_CENTS

        published = validate_success(
            api.publish_report(exam_id, publish_report_payload(), SUPERVISOR_B)
        )
        assert_examination(published)
        assert published["status"] == "PUBLISHED"
        assert is_iso8601_timestamp(published["report_published_at"])
        assert published["public_summary"] == TEST_DEFAULTS["PUBLIC_SUMMARY"]
        assert published["followup_required"] is True
        assert published["followup_due_date"] is not None

        followups, followup_meta = validate_paginated(
            api.list_examinations(
                SUPERVISOR, {"predecessor_exam_id": exam_id, "limit": 100}
            )
        )
        assert followup_meta["total_count"] == 1
        followup = followups[0]
        assert followup["insurer_id"] == scenario["insurer_id"]
        assert followup["predecessor_exam_id"] == exam_id
        assert followup["exam_type"] == "TARGETED_EXAM"
        assert followup["mode"] == "DESK"
        assert followup["status"] == "SCOPING"
        assert followup["cycle_id"] is None
        assert followup["lead_state_code"] == TEST_DEFAULTS["LEAD_STATE_CODE"]
        assert followup["fieldwork_start_date"] == published["followup_due_date"]

        areas, _ = validate_paginated(api.list_scope_areas(exam_id, SUPERVISOR))
        assert [area["status"] for area in areas] == ["CLOSED"]

        insurer = read_insurer(scenario["insurer_id"])
        assert insurer["open_exam_count"] == 1
        assert insurer["pending_enforcement_exam_count"] == 0
        assert insurer["lifetime_restitution_ordered_cents"] == EXTRAPOLATED_EXPOSURE_CENTS


# ─── Band ordering across independent gates ────────────────────────────────


class TestBandOrdering:
    def test_a_negative_population_answers_shape_before_scope_state(self, api):
        """A locked examination breaks the state gate; a negative count breaks shape first.

        PRD §2.11: "Checks are evaluated in the following bands, in this order, and the first band that produces a rejection determines the response:"
        PRD §2.11: "Malformed-request rejection in band 6 covers, across all write endpoints: a required field missing; a field carrying the wrong JSON type; an enum field carrying a value outside its declared set; a monetary or count field that is negative; `sample_size`, `population_size`, `records_requested`, `milestone_count` or `target_slot_capacity` that is not at least 1; a date field that is not formatted `YYYY-MM-DD`; `fieldwork_end_date` that is not strictly after `fieldwork_start_date`; `reference_period_end` that is not strictly after `reference_period_start`; `default_fieldwork_end` that is not strictly after `default_fieldwork_start`; a percentage field outside the inclusive range 0.00 to 100.00; a `narrative`, `summary`, `public_summary` or `rebuttal_note` shorter than 20 characters; a `participating_states` array that is empty, contains a duplicate `state_code`, contains a `state_code` that is not exactly two uppercase letters, or whose `policy_count_in_state` values total zero; a `reviews` array that is empty or contains a duplicate `file_reference`; a `min_composite_score` outside the inclusive range 0.00 to 100.00; a `to_iso8601` that is not an RFC3339 UTC instant; and a scope-lock attempt on an examination that has no scope areas at all."
        PRD §3.3: "Adding an area to an examination that is no longer in `SCOPING` is rejected with `ERR_EXAM_NOT_IN_SCOPING`."

        Design: Corner/validations/shape_validation_outranks_state_validation_on_scope_area_creation
        """
        scenario = setup_locked_examination()
        exam_id = scenario["exam_id"]

        validate_error(
            api.create_scope_area(
                exam_id,
                scope_area_payload("RATING", population_size=-500, sample_size=10),
                EIC,
            ),
            ApiErrorId.ERR_INVALID_REQUEST.value,
        )
        validate_error(
            api.create_scope_area(
                exam_id,
                scope_area_payload("RATING", population_size=500, sample_size=10),
                EIC,
            ),
            ApiErrorId.ERR_EXAM_NOT_IN_SCOPING.value,
        )

        areas, area_meta = validate_paginated(api.list_scope_areas(exam_id, EIC))
        assert area_meta["total_count"] == 1
        assert [area["area"] for area in areas] == ["CLAIMS"]
        assert read_examination(exam_id)["scope_area_count"] == 1

    def test_the_role_gate_answers_before_any_resource_lookup(self, api):
        """An unauthorised caller learns nothing about which identifiers exist.

        PRD §2.11: "Checks are evaluated in the following bands, in this order, and the first band that produces a rejection determines the response:"
        PRD §2.1: "If the value of `X-User-Role` is not one of the roles the called endpoint declares, the request is rejected with `ERR_ROLE_NOT_PERMITTED`."
        PRD §2.8: "A request naming an examination that does not exist fails with `ERR_EXAMINATION_NOT_FOUND` regardless of whether the child identifier further right would have resolved."
        PRD §2.8: "A request naming an insurer that does not exist fails with `ERR_INSURER_NOT_FOUND`; a cycle that does not exist, with `ERR_CYCLE_NOT_FOUND`."
        PRD §2.8: "A scope area, data call, file sample, criticism, corrective action plan, consent order or collaboration identifier that matches no row of that type fails with `ERR_EXAM_RECORD_NOT_FOUND`."

        Design: Corner/validations/role_authorisation_outranks_resource_existence
        """
        missing = NON_EXISTENT_UUID

        validate_error(
            api.lock_scope(missing, ANALYST), ApiErrorId.ERR_ROLE_NOT_PERMITTED.value
        )
        validate_error(
            api.lock_scope(missing, SUPERVISOR),
            ApiErrorId.ERR_EXAMINATION_NOT_FOUND.value,
        )
        validate_error(
            api.create_data_call(
                missing, data_call_payload(records_requested=100), EIC
            ),
            ApiErrorId.ERR_EXAM_RECORD_NOT_FOUND.value,
        )
        validate_error(
            api.get_insurer(missing, ANALYST), ApiErrorId.ERR_INSURER_NOT_FOUND.value
        )
        validate_error(
            api.get_analysis_cycle(missing, ANALYST),
            ApiErrorId.ERR_CYCLE_NOT_FOUND.value,
        )

    def test_authentication_answers_before_role_existence_and_shape(self, api):
        """A request that breaks four gates at once still answers 401.

        PRD §2.1: "If `X-User-ID` is absent, empty, or not a well-formed UUID, the request is rejected with `ERR_UNAUTHENTICATED`."
        PRD §2.1: "The clock endpoint is the single exception to the `X-User-ID` requirement; all five roles may drive it."
        PRD §2.4: "A test-driving capability sets it to an explicit RFC3339 UTC instant supplied as `to_iso8601`, and answers with the object `{ current_utc, data_calls_flagged_overdue }` where `current_utc` echoes the new instant and `data_calls_flagged_overdue` counts the data calls the move swept into `OVERDUE`."
        PRD §2.11: "Malformed-request rejection in band 6 covers, across all write endpoints: a required field missing; a field carrying the wrong JSON type; an enum field carrying a value outside its declared set; a monetary or count field that is negative; `sample_size`, `population_size`, `records_requested`, `milestone_count` or `target_slot_capacity` that is not at least 1; a date field that is not formatted `YYYY-MM-DD`; `fieldwork_end_date` that is not strictly after `fieldwork_start_date`; `reference_period_end` that is not strictly after `reference_period_start`; `default_fieldwork_end` that is not strictly after `default_fieldwork_start`; a percentage field outside the inclusive range 0.00 to 100.00; a `narrative`, `summary`, `public_summary` or `rebuttal_note` shorter than 20 characters; a `participating_states` array that is empty, contains a duplicate `state_code`, contains a `state_code` that is not exactly two uppercase letters, or whose `policy_count_in_state` values total zero; a `reviews` array that is empty or contains a duplicate `file_reference`; a `min_composite_score` outside the inclusive range 0.00 to 100.00; a `to_iso8601` that is not an RFC3339 UTC instant; and a scope-lock attempt on an examination that has no scope areas at all."

        Design: Corner/validations/authentication_outranks_every_other_gate_including_the_role_gate
        """
        # Missing identity, wrong role for the endpoint and a target that does not exist.
        validate_error(
            api.lock_scope(NON_EXISTENT_UUID, _role_only_headers("MarketAnalyst")),
            ApiErrorId.ERR_UNAUTHENTICATED.value,
        )
        # A non-UUID identity outranks the shape defects in the same body.
        validate_error(
            api.register_insurer(
                {
                    "name": "Aurora Mutual Insurance Company",
                    "naic_code": "1",
                    "annual_premium_written_cents": -5,
                },
                build_user_headers("not-a-uuid", "MarketAnalyst"),
            ),
            ApiErrorId.ERR_UNAUTHENTICATED.value,
        )
        # The gate is not write-only.
        validate_error(
            api.list_examinations(_role_only_headers("SupervisingExaminer")),
            ApiErrorId.ERR_UNAUTHENTICATED.value,
        )

        clock = validate_success(
            api.set_clock(
                clock_payload("2026-09-20T00:00:00Z"),
                _role_only_headers("SupervisingExaminer"),
            )
        )
        assert clock["current_utc"].startswith("2026-09-20T00:00:00")
        assert clock["data_calls_flagged_overdue"] == 0

        validate_error(
            api.set_clock(clock_payload("20 September 2026"), SUPERVISOR),
            ApiErrorId.ERR_INVALID_REQUEST.value,
        )


# ─── Carrier ownership and segregation of duties ───────────────────────────


class TestIdentityScopedGates:
    def test_a_second_carrier_is_refused_on_reads_as_well_as_writes(self, api):
        """The respondent's identity filters every record it can reach.

        PRD §2.1: "When `X-User-Role` is `InsurerRespondent`, by contrast, `X-User-ID` is the `id` of the acting `Insurer`; ownership checks on any record the respondent touches walk up to the owning `Examination` and compare its `insurer_id` to `X-User-ID`."
        PRD §2.1: "A mismatch is rejected with `ERR_NOT_EXAM_SUBJECT`."
        PRD §2.1: "That check guards the respondent's four writes — producing records against a data call, answering a criticism, proposing a corrective action plan, and executing a consent order — and equally every read the respondent makes against a record whose owning examination belongs to another carrier."

        Design: Corner/validations/respondent_scope_is_enforced_on_reads_as_well_as_writes
        """
        aurora = register_insurer()
        boreal = register_insurer(**BOREAL)
        aurora_exam = open_examination(aurora["id"])
        boreal_exam = open_examination(boreal["id"])
        area = add_scope_area(aurora_exam["id"], "CLAIMS")
        lock_scope(aurora_exam["id"])
        data_call = issue_data_call(
            area["id"], records_requested=4000, response_due_date="2026-09-15"
        )

        boreal_headers = make_insurer_respondent_headers(boreal["id"])
        validate_error(
            api.respond_to_data_call(
                data_call["id"],
                data_call_response_payload(
                    records_received=4000,
                    submitted_by_contact="Wrong carrier compliance desk",
                ),
                boreal_headers,
            ),
            ApiErrorId.ERR_NOT_EXAM_SUBJECT.value,
        )
        validate_error(
            api.get_data_call(data_call["id"], boreal_headers),
            ApiErrorId.ERR_NOT_EXAM_SUBJECT.value,
        )
        validate_error(
            api.get_scope_area(area["id"], boreal_headers),
            ApiErrorId.ERR_NOT_EXAM_SUBJECT.value,
        )
        validate_error(
            api.get_examination(aurora_exam["id"], boreal_headers),
            ApiErrorId.ERR_NOT_EXAM_SUBJECT.value,
        )

        own = validate_success(api.get_examination(boreal_exam["id"], boreal_headers))
        assert own["id"] == boreal_exam["id"]
        assert own["status"] == "SCOPING"

        untouched = read_data_call(data_call["id"])
        assert untouched["status"] == "ISSUED"
        assert untouched["records_received"] == 0
        assert untouched["version"] == data_call["version"]

        produced = validate_success(
            api.respond_to_data_call(
                data_call["id"],
                data_call_response_payload(records_received=4000),
                make_insurer_respondent_headers(aurora["id"]),
            )
        )
        assert produced["status"] == "RESPONDED"

    def test_the_issuing_examiner_cannot_finalize_their_own_criticism(self, api):
        """The comparison is against the stored issuer identity, not the claimed role.

        PRD §2.9: "A criticism may not be sustained or withdrawn by the examiner who issued it: when finalizing a criticism, if `X-User-ID` equals that criticism's `issued_by_user_id`, the request is rejected with `ERR_SEGREGATION_OF_DUTIES`."
        PRD §3.6: "A new criticism opens in `ISSUED` with `response_round` 0 and `rebuttal_count` 0, records the acting `X-User-ID` as `issued_by_user_id` for the later segregation-of-duties comparison, raises the examination's `open_criticism_count` by 1 and its `pending_restitution_cents` by the frozen `restitution_exposure_cents`, and increments the examination's `version` by 1."
        PRD §3.7: "Either disposition records `finalized_by_user_id` from `X-User-ID`, stamps `finalized_at` from the logical clock, and increments the criticism's `version` by 1; both `SUSTAINED` and `WITHDRAWN` are terminal for the criticism."

        Design: Corner/validations/the_issuing_examiner_cannot_finalise_their_own_criticism
        """
        scenario = setup_examination_in_criticism()
        criticism = issue_criticism(
            scenario["exam_id"],
            scenario["scope_area_id"],
            "MATERIAL",
            3,
            headers=make_examiner_in_charge_headers(SUPERVISING_EXAMINER_ID),
        )
        assert_criticism(criticism)
        assert criticism["issued_by_user_id"] == SUPERVISING_EXAMINER_ID
        respond_to_criticism(criticism["id"], scenario["insurer_id"], "DISPUTE")

        validate_error(
            api.finalize_criticism(
                criticism["id"], criticism_finalize_payload("SUSTAINED", 20), SUPERVISOR
            ),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        )
        mid = read_criticism(criticism["id"])
        assert mid["status"] == "RESPONDED"
        assert mid["response_round"] == 1
        assert read_examination(scenario["exam_id"])["status"] == "CRITICISM"

        finalized = validate_success(
            api.finalize_criticism(
                criticism["id"],
                criticism_finalize_payload("SUSTAINED", 20),
                SUPERVISOR_B,
            )
        )
        assert finalized["status"] == "SUSTAINED"
        assert finalized["finalized_by_user_id"] == SUPERVISING_EXAMINER_B_ID
        assert is_iso8601_timestamp(finalized["finalized_at"])
        assert read_examination(scenario["exam_id"])["status"] == "NEGOTIATION"

    def test_the_order_drafter_cannot_publish_the_report(self, api):
        """Publication keys on the executed order's drafter, a second independent rule.

        PRD §2.9: "A report resting on an executed consent order may not be published by the supervising examiner who drafted that order: when publishing, if `X-User-ID` equals the executed order's `drafted_by_user_id`, the request is likewise rejected with `ERR_SEGREGATION_OF_DUTIES`."
        PRD §3.10: "It requires a consent order on the examination whose `status` is `EXECUTED`, otherwise `ERR_ORDER_NOT_EXECUTED`, and the acting `X-User-ID` must differ from that order's `drafted_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/validations/the_order_drafter_cannot_publish_the_report
        """
        scenario = setup_examination_with_executed_order(
            penalty_variant="PER_VIOLATION", order_number="NV-MC-2026-0042"
        )
        exam_id = scenario["exam_id"]
        order = scenario["consent_order"]
        assert_consent_order(order)
        assert order["drafted_by_user_id"] == SUPERVISING_EXAMINER_ID
        assert order["status"] == "EXECUTED"

        validate_error(
            api.publish_report(exam_id, publish_report_payload(), SUPERVISOR),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        )
        mid = read_examination(exam_id)
        assert mid["status"] == "ORDER_PENDING"
        assert mid["report_published_at"] is None
        _, followup_meta = validate_paginated(
            api.list_examinations(SUPERVISOR, {"predecessor_exam_id": exam_id})
        )
        assert followup_meta["total_count"] == 0

        published = validate_success(
            api.publish_report(exam_id, publish_report_payload(), SUPERVISOR_B)
        )
        assert published["status"] == "PUBLISHED"


# ─── Numeric bounds, documentation and uniqueness ──────────────────────────


class TestBusinessSafetyAndNumericBounds:
    def test_the_statutory_sample_minimum_answers_before_the_population_bound(self, api):
        """A three-file sample over a two-file population breaks both numeric rules.

        PRD §2.11: "Checks are evaluated in the following bands, in this order, and the first band that produces a rejection determines the response:"
        PRD §3.3: "Statutory minimum sample sizes depend on the examination's `mode`: an `ON_SITE` examination requires a `sample_size` of at least 10, a `DESK` examination at least 5, and a smaller figure is rejected with `ERR_SAMPLE_SIZE_BELOW_MINIMUM` at HTTP 422."
        PRD §3.3: "A `sample_size` exceeding the `population_size` is rejected with `ERR_SAMPLE_EXCEEDS_POPULATION`."
        PRD §3.3: "An optional `error_tolerance_pct` between 0.00 and 100.00 inclusive overrides the statutory default; when it is omitted the default is read from the per-area statutory table — 7.00 percent for `UNDERWRITING`, 5.00 percent for `RATING`, 3.00 percent for `CLAIMS` and 10.00 percent for `PRODUCER`."
        PRD §3.4: "The examiner supplies `records_requested` (at least 1, and never more than the area's `population_size` — an excess is `ERR_SAMPLE_EXCEEDS_POPULATION`) and a `response_due_date`."

        Design: Corner/validations/the_sample_minimum_outranks_the_population_bound
        """
        scenario = setup_examination_in_scoping()
        exam_id = scenario["exam_id"]
        assert scenario["examination"]["mode"] == "ON_SITE"

        validate_error(
            api.create_scope_area(
                exam_id,
                scope_area_payload("CLAIMS", population_size=2, sample_size=3),
                EIC,
            ),
            ApiErrorId.ERR_SAMPLE_SIZE_BELOW_MINIMUM.value,
        )
        validate_error(
            api.create_scope_area(
                exam_id,
                scope_area_payload("CLAIMS", population_size=10, sample_size=12),
                EIC,
            ),
            ApiErrorId.ERR_SAMPLE_EXCEEDS_POPULATION.value,
        )

        area = validate_success(
            api.create_scope_area(
                exam_id,
                scope_area_payload("CLAIMS", population_size=10, sample_size=10),
                EIC,
            ),
            201,
        )
        assert_scope_area(area)
        assert area["population_size"] == 10
        assert area["sample_size"] == 10
        assert area["error_tolerance_pct"] == 3.00

        lock_scope(exam_id)
        validate_error(
            api.create_data_call(
                area["id"],
                data_call_payload(records_requested=25, response_due_date="2026-09-15"),
                EIC,
            ),
            ApiErrorId.ERR_SAMPLE_EXCEEDS_POPULATION.value,
        )

    def test_the_interview_workpaper_is_required_only_on_site(self, api):
        """Two identically documented examinations answer differently on mode alone.

        PRD §3.6: "The examination's fieldwork must be documented: it must hold at least one fieldwork activity whose `activity_type` is `SYSTEM_WALKTHROUGH`, and — only when the examination's `mode` is `ON_SITE` — at least one whose `activity_type` is `INTERVIEW`; a `DESK` examination requires the walkthrough alone."
        PRD §3.6: "A missing requirement is `ERR_FIELDWORK_NOT_DOCUMENTED`."

        Design: Corner/validations/workpaper_completeness_is_required_conditionally_on_examination_mode
        """
        onsite = _claims_area_tested_with_walkthrough_only("ON_SITE")
        desk = _claims_area_tested_with_walkthrough_only("DESK", insurer_overrides=BOREAL)

        validate_error(
            api.issue_criticism(
                criticism_payload(
                    onsite["exam_id"], onsite["scope_area_id"], "MATERIAL", 3
                ),
                EIC,
            ),
            ApiErrorId.ERR_FIELDWORK_NOT_DOCUMENTED.value,
        )
        desk_criticism = validate_success(
            api.issue_criticism(
                criticism_payload(desk["exam_id"], desk["scope_area_id"], "MATERIAL", 3),
                EIC,
            ),
            201,
        )
        assert desk_criticism["status"] == "ISSUED"

        # Filing the missing interview workpaper is itself never refused.
        record_fieldwork_activity(
            onsite["exam_id"],
            "INTERVIEW",
            "CLAIMS",
            participant_name="L. Ortiz",
            participant_title="Claims Manager",
            summary="Interviewed the claims manager on prompt-pay handling and denials.",
            evidence_ref="WP-CLA-02",
        )
        onsite_criticism = validate_success(
            api.issue_criticism(
                criticism_payload(
                    onsite["exam_id"], onsite["scope_area_id"], "MATERIAL", 3
                ),
                EIC,
            ),
            201,
        )
        assert onsite_criticism["status"] == "ISSUED"

        interviews, interview_meta = validate_paginated(
            api.list_fieldwork_activities(
                onsite["exam_id"], EIC, {"activity_type": "INTERVIEW"}
            )
        )
        assert interview_meta["total_count"] == 1
        assert [activity["activity_type"] for activity in interviews] == ["INTERVIEW"]

    def test_the_five_uniqueness_scopes_are_mutually_independent(self, api):
        """One error code covers two global scopes, one per-parent scope and one cardinality limit.

        PRD §2.11: "Duplicate-identifier rejection in band 7 covers five uniqueness rules: a `naic_code` that already exists on another carrier, a `cycle_label` that already exists on another cycle, an `order_number` that already exists on another consent order, a second scope area with the same `area` value on one examination, and a second collaboration on one examination."
        PRD §3.3: "The `area` value is one of `UNDERWRITING`, `RATING`, `CLAIMS` or `PRODUCER`, and at most one area of each value may exist on one examination — a repeat is `ERR_DUPLICATE_IDENTIFIER`."
        PRD §3.9: "At most one collaboration may exist per examination; a second attempt is `ERR_DUPLICATE_IDENTIFIER`."

        Design: Corner/validations/the_five_uniqueness_scopes_are_mutually_independent
        """
        scenario = setup_examination_in_order_pending()
        exam_id = scenario["exam_id"]
        create_analysis_cycle(cycle_label="2026-H2-MARKET-ANALYSIS")
        boreal = register_insurer(**BOREAL)
        boreal_exam = open_examination(boreal["id"])
        add_scope_area(boreal_exam["id"], "CLAIMS")
        order = draft_consent_order(
            exam_id, order_number="NV-MC-2026-0042", penalty_variant="PER_VIOLATION"
        )
        collaboration = open_collaboration(exam_id)
        assert_collaboration(collaboration)

        # A global string scope: the code alone, regardless of legal name.
        validate_error(
            api.register_insurer(
                insurer_payload(
                    name="Different Legal Name Insurance Company",
                    naic_code=TEST_DEFAULTS["NAIC_CODE"],
                ),
                ANALYST,
            ),
            ApiErrorId.ERR_DUPLICATE_IDENTIFIER.value,
        )
        # A second global string scope: the label alone, regardless of periods.
        validate_error(
            api.create_analysis_cycle(
                analysis_cycle_payload(
                    cycle_label="2026-H2-MARKET-ANALYSIS",
                    reference_period_start="2024-07-01",
                    reference_period_end="2025-06-30",
                    target_slot_capacity=1,
                    default_fieldwork_start="2027-01-01",
                    default_fieldwork_end="2027-03-31",
                ),
                ANALYST,
            ),
            ApiErrorId.ERR_DUPLICATE_IDENTIFIER.value,
        )
        # A per-parent enum scope.
        validate_error(
            api.create_scope_area(
                boreal_exam["id"],
                scope_area_payload("CLAIMS", population_size=900, sample_size=10),
                EIC,
            ),
            ApiErrorId.ERR_DUPLICATE_IDENTIFIER.value,
        )
        rating = validate_success(
            api.create_scope_area(
                boreal_exam["id"],
                scope_area_payload("RATING", population_size=900, sample_size=10),
                EIC,
            ),
            201,
        )
        assert rating["area"] == "RATING"
        _, aurora_area_meta = validate_paginated(api.list_scope_areas(exam_id, EIC))
        assert aurora_area_meta["total_count"] == 1

        # A third global string scope, and the refusal must not void the live draft.
        validate_error(
            api.draft_consent_order(
                exam_id,
                consent_order_payload(
                    read_examination(exam_id)["version"],
                    "NV-MC-2026-0042",
                    "TIERED_AGGREGATE",
                ),
                SUPERVISOR,
            ),
            ApiErrorId.ERR_DUPLICATE_IDENTIFIER.value,
        )
        assert validate_success(api.get_consent_order(order["id"], SUPERVISOR))[
            "status"
        ] == "DRAFT"

        # A cardinality scope, with no field collision at all.
        validate_error(
            api.open_collaboration(
                exam_id,
                collaboration_payload(call_reference="NAIC-CAWG-2026-0999"),
                COORDINATOR,
            ),
            ApiErrorId.ERR_DUPLICATE_IDENTIFIER.value,
        )
        collaborations, collaboration_meta = validate_paginated(
            api.list_collaborations(exam_id, COORDINATOR)
        )
        assert collaboration_meta["total_count"] == 1
        assert [row["id"] for row in collaborations] == [collaboration["id"]]

    def test_a_spent_cycle_ledger_refuses_the_next_attachment(self, api):
        """Selection spends the only slot, so a manual attachment to that cycle is refused.

        PRD §2.10: "`slots_committed` is defined as the number of examinations attributed to that cycle whose `status` is neither `PUBLISHED` nor `ABORTED`, and `slots_available` is `target_slot_capacity` less `slots_committed`."
        PRD §3.3: "An optional `cycle_id` attributes the examination to an existing cycle and consumes one of its slots; a `cycle_id` naming a cycle whose `slots_available` is 0 is rejected with `ERR_CYCLE_SLOTS_EXHAUSTED`."
        PRD §3.2: "Each creation raises the carrier's `open_exam_count` by 1 and the cycle's `slots_committed` by 1, thereby lowering `slots_available` by 1."

        Design: Corner/validations/cycle_slots_are_a_conserved_ledger_that_refuses_the_next_attachment
        """
        register_insurer(
            policy_count_in_force=100_000,
            confirmed_complaints_12mo=500,
            financial_stress_score=100,
            consumer_trend_score=100,
        )
        boreal = register_insurer(
            policy_count_in_force=40_000,
            confirmed_complaints_12mo=40,
            financial_stress_score=10,
            consumer_trend_score=10,
            **BOREAL,
        )
        cycle = create_analysis_cycle(
            cycle_label="2026-H2-MARKET-ANALYSIS", target_slot_capacity=1
        )
        score_cycle(cycle["id"])
        selected = select_targets(cycle["id"])
        assert selected["selected_target_count"] == 1
        assert selected["slots_committed"] == 1
        assert selected["slots_available"] == 0

        validate_error(
            api.open_examination(
                examination_payload(
                    boreal["id"],
                    exam_type="TARGETED_EXAM",
                    mode="DESK",
                    cycle_id=cycle["id"],
                ),
                SUPERVISOR,
            ),
            ApiErrorId.ERR_CYCLE_SLOTS_EXHAUSTED.value,
        )
        standalone = validate_success(
            api.open_examination(
                examination_payload(
                    boreal["id"], exam_type="TARGETED_EXAM", mode="DESK"
                ),
                SUPERVISOR,
            ),
            201,
        )
        assert standalone["cycle_id"] is None

        after = read_cycle(cycle["id"])
        assert_slot_ledger_conserved(after)
        assert after["target_slot_capacity"] == 1
        assert after["slots_committed"] == 1
        assert after["slots_available"] == 0

    def test_allocation_refuses_an_empty_restitution_pool(self, api):
        """A sustained criticism with no measured harm leaves nothing to conserve.

        PRD §3.9: "A collaboration whose `status` is not `ACTIVE` is rejected with `ERR_ENFORCEMENT_RECORD_STATE_INVALID`; the examination must already hold a consent order in `EXECUTED`, otherwise `ERR_ORDER_NOT_EXECUTED`; and an examination whose `aggregate_restitution_cents` is 0 has nothing to allocate, so the attempt is rejected with `ERR_RESTITUTION_NOT_CONSERVED`."
        PRD §3.6: "In every other case the method is `SAMPLE_ACTUAL`."
        PRD §3.8: "The **per-violation** algorithm ignores restitution size entirely: the gross penalty is the examination's `penalty_units_total` multiplied by 25,000 cents (250 dollars per statutory violation unit)."
        PRD §3.8: "Step three: `cooperation_credit_pct` is fifteen hundredths when the subtotal is 25,000,000 cents or more, and five hundredths otherwise."
        PRD §3.8: "Step four: `penalty_net_cents` is the gross penalty multiplied by one minus the credit rate, rounded half up to a whole cent."
        PRD §3.8: "Step five: `order_total_cents` is the restitution aggregate plus the net penalty."

        Design: Corner/validations/multistate_allocation_refuses_an_empty_restitution_pool
        """
        scenario = setup_examination_with_executed_order(
            penalty_variant="PER_VIOLATION",
            order_number="NV-MC-2026-0042",
            criticism_severity="MINOR",
            penalty_units=5,
            severity="MINOR",
            harm_cents=(0, 0, 0),
            with_collaboration=True,
        )
        criticism = read_criticism(scenario["criticism_id"])
        assert criticism["status"] == "SUSTAINED"
        assert criticism["restitution_method"] == "SAMPLE_ACTUAL"
        assert criticism["restitution_exposure_cents"] == 0

        order = scenario["consent_order"]
        assert_consent_order(order)
        assert order["restitution_cents"] == 0
        assert order["penalty_gross_cents"] == 125_000
        assert order["cooperation_credit_pct"] == 0.05
        assert order["penalty_net_cents"] == 118_750
        assert order["order_total_cents"] == 118_750

        before = read_collaboration(scenario["collaboration_id"])
        assert before["status"] == "ACTIVE"
        assert before["allocated_total_cents"] == 0

        validate_error(
            api.allocate_restitution(scenario["collaboration_id"], COORDINATOR),
            ApiErrorId.ERR_RESTITUTION_NOT_CONSERVED.value,
        )

        after = read_collaboration(scenario["collaboration_id"])
        assert after["status"] == "ACTIVE"
        assert after["allocated_total_cents"] == 0
        assert all(
            participant["allocated_cents"] == 0
            for participant in after["participating_states"]
        )

        summary = read_exposure_summary(scenario["exam_id"], COORDINATOR)
        assert summary["aggregate_restitution_cents"] == 0
        assert summary["penalty_units_total"] == 5
