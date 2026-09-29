"""Error catalogue, part one: authentication through the early lifecycle codes.

The authorisation band (unauthenticated, role, carrier ownership, segregation of
duties), the four not-found families, request shape, uniqueness, and the
lifecycle-state refusals that guard the cycle machine, the scope freeze, the
data-call machine, file review, criticism issuance and plan filing.
"""

from test_helpers import (
    ANALYST,
    COORDINATOR,
    EIC,
    EXAMINER_IN_CHARGE_ID,
    NON_EXISTENT_UUID,
    SUPERVISOR,
    SUPERVISOR_B,
    ApiErrorId,
    analysis_cycle_payload,
    assert_error_envelope_meta,
    build_user_headers,
    build_reviews,
    bulk_review,
    bulk_review_payload,
    collaboration_payload,
    company_response_payload,
    consent_order_payload,
    corrective_action_plan_payload,
    create_analysis_cycle,
    criticism_finalize_payload,
    criticism_payload,
    data_call_payload,
    disposition_data_call,
    disposition_payload,
    examination_payload,
    fieldwork_activity_payload,
    file_review_payload,
    insurer_payload,
    issue_criticism,
    issue_data_call,
    lock_scope,
    make_insurer_respondent_headers,
    make_supervising_examiner_headers,
    open_examination,
    propose_plan,
    publish_report_payload,
    read_criticism,
    read_cycle_scores,
    read_examination,
    read_file_samples,
    read_scope_area,
    record_standard_workpapers,
    register_insurer,
    respond_to_criticism,
    respond_to_data_call,
    review_file_sample,
    scope_area_payload,
    score_cycle,
    select_targets,
    setup_area_in_fieldwork,
    setup_examination_in_criticism,
    setup_examination_with_executed_order,
    setup_locked_examination,
    systematic_file_references,
    validate_error,
    validate_paginated,
    validate_success,
)

CLAIMS_REFERENCES = systematic_file_references("CLAIMS", 4000, 10)

# A header pair that names a role but carries no acting user identity at all.
NO_USER_ID_HEADERS = {
    "X-User-Role": "SupervisingExaminer",
    "Content-Type": "application/json",
}
# A header pair whose X-User-ID is present but is not a well-formed UUID.
MALFORMED_USER_ID_HEADERS = build_user_headers("12345", "MarketAnalyst")


# ─── Authorisation band ───────────────────────────────────────────────────


def test_unauthenticated_is_raised_for_an_absent_and_a_malformed_user_id(api):
    """An absent and a syntactically invalid X-User-ID are both 401.

    PRD §2.1: "If `X-User-ID` is absent, empty, or not a well-formed UUID, the
    request is rejected with `ERR_UNAUTHENTICATED`."

    PRD §2.11 places authentication first: "1. **Authentication** —
    `ERR_UNAUTHENTICATED`.", so the malformed-header write is refused before its
    body is ever considered and nothing is persisted.

    Design: Corner/errors/err_unauthenticated_is_the_outermost_gate
    """
    missing = api.list_examinations(NO_USER_ID_HEADERS)
    validate_error(missing, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
    assert_error_envelope_meta(missing.json())

    malformed = api.register_insurer(insurer_payload(), MALFORMED_USER_ID_HEADERS)
    validate_error(malformed, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
    assert_error_envelope_meta(malformed.json())

    carriers, meta = validate_paginated(api.list_insurers(ANALYST))
    assert meta["total_count"] == 0, (
        "the unauthenticated registration attempt must not have written a carrier"
    )
    assert carriers == []


def test_role_not_permitted_is_a_function_of_the_called_endpoint(api):
    """Four authenticated callers are refused on endpoints outside their grant.

    PRD §2.1: "If the value of `X-User-Role` is not one of the roles the called
    endpoint declares, the request is rejected with `ERR_ROLE_NOT_PERMITTED`."

    PRD §2.11 orders role permission above existence, so scoring a cycle that
    does not exist still answers `ERR_ROLE_NOT_PERMITTED`: "2. **Role
    permission** — `ERR_ROLE_NOT_PERMITTED`."

    Design: Corner/errors/err_role_not_permitted_on_an_endpoint_outside_the_role_grant
    """
    insurer = register_insurer()
    examination = open_examination(insurer["id"])

    validate_error(
        api.register_insurer(
            insurer_payload(
                name="Self Registered Insurance Company",
                naic_code="10002",
                annual_premium_written_cents=1000,
                policy_count_in_force=10,
                confirmed_complaints_12mo=0,
                financial_stress_score=1,
                consumer_trend_score=1,
            ),
            make_insurer_respondent_headers(insurer["id"]),
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
        403,
    )
    # Scope-area creation on this examination belongs to the ExaminerInCharge,
    # but locking the scope does not: the grant is declared per endpoint.
    validate_error(
        api.lock_scope(examination["id"], EIC),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
        403,
    )
    validate_error(
        api.score_analysis_cycle(NON_EXISTENT_UUID, SUPERVISOR),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
        403,
    )
    validate_error(
        api.list_insurer_analysis_scores(insurer["id"], COORDINATOR),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
        403,
    )

    _, meta = validate_paginated(api.list_insurers(ANALYST))
    assert meta["total_count"] == 1, "no carrier was registered by the refused write"
    assert read_examination(examination["id"])["status"] == "SCOPING"


def test_not_exam_subject_for_a_carrier_that_is_not_the_examination_subject(api):
    """A second carrier is refused on both a write and a read it does not own.

    PRD §2.1: "A mismatch is rejected with `ERR_NOT_EXAM_SUBJECT`. That check
    guards the respondent's four writes — producing records against a data call,
    answering a criticism, proposing a corrective action plan, and executing a
    consent order — and equally every read the respondent makes against a record
    whose owning examination belongs to another carrier."

    PRD §3.7: "The acting `X-User-ID` must equal the examination's `insurer_id`,
    otherwise `ERR_NOT_EXAM_SUBJECT`; a criticism in any state other than
    `ISSUED` yields `ERR_CRITICISM_STATE_INVALID`."

    Design: Corner/errors/err_not_exam_subject_for_a_foreign_carrier
    """
    scenario = setup_examination_in_criticism()
    criticism = issue_criticism(scenario["exam_id"], scenario["scope_area_id"])
    stranger = register_insurer(name="Boreal Casualty Company", naic_code="10002")
    stranger_headers = make_insurer_respondent_headers(stranger["id"])

    validate_error(
        api.create_company_response(
            criticism["id"],
            company_response_payload(
                "DISPUTE",
                narrative="A carrier that is not the examination subject attempts to answer.",
            ),
            stranger_headers,
        ),
        ApiErrorId.ERR_NOT_EXAM_SUBJECT.value,
        403,
    )
    validate_error(
        api.get_criticism(criticism["id"], stranger_headers),
        ApiErrorId.ERR_NOT_EXAM_SUBJECT.value,
        403,
    )

    answer = validate_success(
        api.create_company_response(
            criticism["id"],
            company_response_payload("DISPUTE"),
            make_insurer_respondent_headers(scenario["insurer_id"]),
        ),
        201,
    )
    assert answer["round_number"] == 1, "the subject carrier's own answer is round 1"
    assert read_criticism(criticism["id"])["response_round"] == 1, (
        "the refused foreign answer consumed no response round"
    )


def test_segregation_of_duties_blocks_the_issuing_examiner_from_finalizing(api):
    """The user recorded as issued_by_user_id may not sustain the criticism.

    PRD §2.9: "A criticism may not be sustained or withdrawn by the examiner who
    issued it: when finalizing a criticism, if `X-User-ID` equals that
    criticism's `issued_by_user_id`, the request is rejected with
    `ERR_SEGREGATION_OF_DUTIES`."

    PRD §2.9: "Both checks carry HTTP 403 and both are evaluated in the
    authorisation band, before any existence or state check on the target
    record."

    Design: Corner/errors/err_segregation_of_duties_guards_both_finalisation_and_publication
    """
    scenario = setup_examination_in_criticism()
    criticism = issue_criticism(scenario["exam_id"], scenario["scope_area_id"])
    assert criticism["issued_by_user_id"] == EXAMINER_IN_CHARGE_ID
    respond_to_criticism(criticism["id"], scenario["insurer_id"], "DISPUTE")

    validate_error(
        api.finalize_criticism(
            criticism["id"],
            criticism_finalize_payload(
                "SUSTAINED",
                20,
                disposition_note="The issuing examiner attempts to sustain their own criticism.",
            ),
            make_supervising_examiner_headers(EXAMINER_IN_CHARGE_ID),
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        403,
    )
    assert read_criticism(criticism["id"])["status"] == "RESPONDED", (
        "the refusal left the criticism exactly where it stood"
    )

    finalized = validate_success(
        api.finalize_criticism(
            criticism["id"], criticism_finalize_payload("SUSTAINED", 20), SUPERVISOR_B
        )
    )
    assert finalized["status"] == "SUSTAINED"


def test_segregation_of_duties_blocks_the_order_drafter_from_publishing(api):
    """The supervisor recorded as drafted_by_user_id may not publish the report.

    PRD §2.9: "A report resting on an executed consent order may not be published
    by the supervising examiner who drafted that order: when publishing, if
    `X-User-ID` equals the executed order's `drafted_by_user_id`, the request is
    likewise rejected with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/errors/err_segregation_of_duties_guards_both_finalisation_and_publication
    """
    scenario = setup_examination_with_executed_order()
    order = scenario["consent_order"]
    assert order["status"] == "EXECUTED"

    drafter_headers = make_supervising_examiner_headers(order["drafted_by_user_id"])
    validate_error(
        api.publish_report(
            scenario["exam_id"],
            publish_report_payload(
                public_summary="The drafting supervisor attempts to publish the order they negotiated."
            ),
            drafter_headers,
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        403,
    )
    assert read_examination(scenario["exam_id"])["status"] == "ORDER_PENDING", (
        "the refusal is an authorisation outcome and left the examination in place"
    )

    published = validate_success(
        api.publish_report(scenario["exam_id"], publish_report_payload(), SUPERVISOR_B)
    )
    assert published["status"] == "PUBLISHED"


# ─── Existence band ───────────────────────────────────────────────────────


def test_insurer_not_found_by_path_and_by_body_reference(api):
    """A carrier identifier that matches no row answers the carrier not-found code.

    PRD §2.8: "A request naming an insurer that does not exist fails with
    `ERR_INSURER_NOT_FOUND`; a cycle that does not exist, with
    `ERR_CYCLE_NOT_FOUND`."

    PRD §2.8: "Likewise, an `insurer_id` in a body that matches no carrier is
    `ERR_INSURER_NOT_FOUND`, and a `cycle_id` in a body that matches no cycle is
    `ERR_CYCLE_NOT_FOUND`."

    Design: Corner/errors/err_insurer_not_found_for_an_absent_carrier
    """
    validate_error(
        api.get_insurer(NON_EXISTENT_UUID, ANALYST),
        ApiErrorId.ERR_INSURER_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.refresh_market_data(
            NON_EXISTENT_UUID, {"confirmed_complaints_12mo": 5}, ANALYST
        ),
        ApiErrorId.ERR_INSURER_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.open_examination(examination_payload(NON_EXISTENT_UUID), SUPERVISOR),
        ApiErrorId.ERR_INSURER_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.list_insurer_analysis_scores(NON_EXISTENT_UUID, ANALYST),
        ApiErrorId.ERR_INSURER_NOT_FOUND.value,
        404,
    )

    _, meta = validate_paginated(api.list_examinations(SUPERVISOR))
    assert meta["total_count"] == 0, "no examination was opened against a missing carrier"


def test_cycle_not_found_by_path_and_by_optional_body_reference(api):
    """A cycle identifier that matches no row answers the cycle not-found code.

    PRD §2.8: "A request naming an insurer that does not exist fails with
    `ERR_INSURER_NOT_FOUND`; a cycle that does not exist, with
    `ERR_CYCLE_NOT_FOUND`."

    PRD §2.8: "Likewise, an `insurer_id` in a body that matches no carrier is
    `ERR_INSURER_NOT_FOUND`, and a `cycle_id` in a body that matches no cycle is
    `ERR_CYCLE_NOT_FOUND`."

    Design: Corner/errors/err_cycle_not_found_for_an_absent_analysis_cycle
    """
    insurer = register_insurer()

    validate_error(
        api.score_analysis_cycle(NON_EXISTENT_UUID, ANALYST),
        ApiErrorId.ERR_CYCLE_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.list_cycle_scores(NON_EXISTENT_UUID, ANALYST),
        ApiErrorId.ERR_CYCLE_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.select_targets(NON_EXISTENT_UUID, ANALYST),
        ApiErrorId.ERR_CYCLE_NOT_FOUND.value,
        404,
    )
    # cycle_id is optional on examination creation, but a supplied value is still resolved.
    validate_error(
        api.open_examination(
            examination_payload(insurer["id"], cycle_id=NON_EXISTENT_UUID), SUPERVISOR
        ),
        ApiErrorId.ERR_CYCLE_NOT_FOUND.value,
        404,
    )

    _, meta = validate_paginated(api.list_examinations(SUPERVISOR))
    assert meta["total_count"] == 0, "no examination was opened against a missing cycle"


def test_examination_not_found_by_path_and_by_criticism_body_exam_id(api):
    """An examination identifier that matches no row answers the examination code.

    PRD §2.8: "A request naming an examination that does not exist fails with
    `ERR_EXAMINATION_NOT_FOUND` regardless of whether the child identifier
    further right would have resolved."

    PRD §2.8: "When a criticism is issued, its body carries both an `exam_id` and
    a `scope_area_id`; an `exam_id` matching no examination is
    `ERR_EXAMINATION_NOT_FOUND`, and a `scope_area_id` that either matches no
    scope area **or** matches one whose own `exam_id` differs from the supplied
    `exam_id` is `ERR_EXAM_RECORD_NOT_FOUND`."

    Design: Corner/errors/err_examination_not_found_for_an_absent_examination
    """
    validate_error(
        api.get_examination(NON_EXISTENT_UUID, SUPERVISOR),
        ApiErrorId.ERR_EXAMINATION_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.create_scope_area(NON_EXISTENT_UUID, scope_area_payload("CLAIMS"), EIC),
        ApiErrorId.ERR_EXAMINATION_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_exposure_summary(NON_EXISTENT_UUID, SUPERVISOR),
        ApiErrorId.ERR_EXAMINATION_NOT_FOUND.value,
        404,
    )
    # Both body identifiers are absent: the examination is resolved first.
    validate_error(
        api.issue_criticism(
            criticism_payload(NON_EXISTENT_UUID, NON_EXISTENT_UUID, "MATERIAL", 1), EIC
        ),
        ApiErrorId.ERR_EXAMINATION_NOT_FOUND.value,
        404,
    )


def test_exam_record_not_found_on_every_absent_child_path(api):
    """Six child record families share one not-found code.

    PRD §2.8: "A scope area, data call, file sample, criticism, corrective action
    plan, consent order or collaboration identifier that matches no row of that
    type fails with `ERR_EXAM_RECORD_NOT_FOUND`."

    Design: Corner/errors/err_exam_record_not_found_by_path_and_by_body_reference
    """
    for response in (
        api.get_scope_area(NON_EXISTENT_UUID, EIC),
        api.get_data_call(NON_EXISTENT_UUID, EIC),
        api.get_file_sample(NON_EXISTENT_UUID, EIC),
        api.get_corrective_action_plan(NON_EXISTENT_UUID, SUPERVISOR),
        api.get_consent_order(NON_EXISTENT_UUID, SUPERVISOR),
        api.get_collaboration(NON_EXISTENT_UUID, COORDINATOR),
    ):
        validate_error(response, ApiErrorId.ERR_EXAM_RECORD_NOT_FOUND.value, 404)


def test_exam_record_not_found_for_a_scope_area_of_a_sibling_examination(api):
    """A real scope area belonging to another examination is 404, not a criticism.

    PRD §2.8: "When a criticism is issued, its body carries both an `exam_id` and
    a `scope_area_id`; an `exam_id` matching no examination is
    `ERR_EXAMINATION_NOT_FOUND`, and a `scope_area_id` that either matches no
    scope area **or** matches one whose own `exam_id` differs from the supplied
    `exam_id` is `ERR_EXAM_RECORD_NOT_FOUND`."

    PRD §2.8: "The cross-parent case is checked immediately after plain
    existence, before any request-shape or business rule runs."

    Design: Corner/errors/err_exam_record_not_found_by_path_and_by_body_reference
    """
    scenario = setup_examination_in_criticism()
    sibling_insurer = register_insurer(name="Boreal Casualty Company", naic_code="10002")
    sibling_exam = open_examination(sibling_insurer["id"])
    sibling_area = validate_success(
        api.create_scope_area(sibling_exam["id"], scope_area_payload("CLAIMS"), EIC), 201
    )

    validate_error(
        api.issue_criticism(
            criticism_payload(scenario["exam_id"], sibling_area["id"], "MATERIAL", 1), EIC
        ),
        ApiErrorId.ERR_EXAM_RECORD_NOT_FOUND.value,
        404,
    )

    _, meta = validate_paginated(
        api.list_criticisms(EIC, {"exam_id": scenario["exam_id"]})
    )
    assert meta["total_count"] == 0, "no criticism was issued against either examination"


# ─── Request shape and uniqueness bands ───────────────────────────────────


def test_invalid_request_across_the_declared_shape_families(api):
    """Ordered dates, numeric floors, percentage bands, free-text minimums, roster well-formedness and enum membership all answer one code.

    PRD §2.11: "6. **Request shape** — `ERR_INVALID_REQUEST`."

    PRD §2.11: "Malformed-request rejection in band 6 covers, across all write endpoints: a required field missing; a field carrying the wrong JSON type; an enum field carrying a value outside its declared set; a monetary or count field that is negative; `sample_size`, `population_size`, `records_requested`, `milestone_count` or `target_slot_capacity` that is not at least 1; a date field that is not formatted `YYYY-MM-DD`; `fieldwork_end_date` that is not strictly after `fieldwork_start_date`; `reference_period_end` that is not strictly after `reference_period_start`; `default_fieldwork_end` that is not strictly after `default_fieldwork_start`; a percentage field outside the inclusive range 0.00 to 100.00; a `narrative`, `summary`, `public_summary` or `rebuttal_note` shorter than 20 characters; a `participating_states` array that is empty, contains a duplicate `state_code`, contains a `state_code` that is not exactly two uppercase letters, or whose `policy_count_in_state` values total zero; a `reviews` array that is empty or contains a duplicate `file_reference`; a `min_composite_score` outside the inclusive range 0.00 to 100.00; a `to_iso8601` that is not an RFC3339 UTC instant; and a scope-lock attempt on an examination that has no scope areas at all."

    Design: Corner/errors/err_invalid_request_across_five_shape_families
    """
    insurer = register_insurer()
    examination = open_examination(insurer["id"])
    cycle = create_analysis_cycle(
        cycle_label="2026-H2-MARKET-ANALYSIS", target_slot_capacity=3
    )

    # reference_period_end equal to its start is not strictly after it.
    validate_error(
        api.create_analysis_cycle(
            analysis_cycle_payload(
                cycle_label="2027-H1-MARKET-ANALYSIS",
                reference_period_start="2025-07-01",
                reference_period_end="2025-07-01",
                default_fieldwork_start="2027-01-01",
                default_fieldwork_end="2027-03-31",
            ),
            ANALYST,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        422,
    )
    # target_slot_capacity has a floor of 1.
    validate_error(
        api.create_analysis_cycle(
            analysis_cycle_payload(
                cycle_label="2027-H2-MARKET-ANALYSIS",
                target_slot_capacity=0,
                default_fieldwork_start="2027-01-01",
                default_fieldwork_end="2027-03-31",
            ),
            ANALYST,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        422,
    )
    # A percentage above 100.00, on a DRAFT cycle: band 6 outranks band 8.
    validate_error(
        api.select_targets(cycle["id"], ANALYST, {"min_composite_score": 100.01}),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        422,
    )
    # A workpaper summary of ten characters is below the twenty-character minimum.
    validate_error(
        api.create_fieldwork_activity(
            examination["id"],
            fieldwork_activity_payload(
                "INTERVIEW",
                "CLAIMS",
                participant_name="L. Ortiz",
                participant_title="Claims Manager",
                summary="Too short.",
                evidence_ref="WP-CLM-09",
            ),
            EIC,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        422,
    )
    # A duplicated state_code inside the roster.
    validate_error(
        api.open_collaboration(
            examination["id"],
            collaboration_payload(
                [
                    {
                        "state_code": "NV",
                        "policy_count_in_state": 100,
                        "has_examiner_resources": True,
                    },
                    {
                        "state_code": "NV",
                        "policy_count_in_state": 50,
                        "has_examiner_resources": True,
                    },
                ],
                call_reference="NAIC-CAWG-2026-0401",
            ),
            COORDINATOR,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        422,
    )
    # A state_code that is not exactly two uppercase letters.
    validate_error(
        api.open_collaboration(
            examination["id"],
            collaboration_payload(
                [
                    {
                        "state_code": "Nevada",
                        "policy_count_in_state": 100,
                        "has_examiner_resources": True,
                    }
                ],
                call_reference="NAIC-CAWG-2026-0402",
            ),
            COORDINATOR,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        422,
    )
    # An exam_type outside its declared set.
    validate_error(
        api.open_examination(
            examination_payload(
                insurer["id"],
                exam_type="ROUTINE_AUDIT",
                fieldwork_start_date="2027-01-01",
                fieldwork_end_date="2027-03-31",
            ),
            SUPERVISOR,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        422,
    )

    _, cycles_meta = validate_paginated(api.list_analysis_cycles(ANALYST))
    assert cycles_meta["total_count"] == 1, "no cycle was created by the refused writes"
    _, activity_meta = validate_paginated(
        api.list_fieldwork_activities(examination["id"], EIC)
    )
    assert activity_meta["total_count"] == 0
    _, collab_meta = validate_paginated(
        api.list_collaborations(examination["id"], COORDINATOR)
    )
    assert collab_meta["total_count"] == 0
    _, exam_meta = validate_paginated(api.list_examinations(SUPERVISOR))
    assert exam_meta["total_count"] == 1


def test_duplicate_identifier_on_a_reused_naic_code(api):
    """A second carrier under an existing NAIC code is a 409, and the name is not a uniqueness scope.

    PRD §3.1: "A `MarketAnalyst` registers a regulated carrier by supplying its
    `name` (between 1 and 120 characters), its `naic_code` (exactly five digits,
    unique across all carriers — a collision is `ERR_DUPLICATE_IDENTIFIER`), its
    `annual_premium_written_cents` for the reference period, its
    `policy_count_in_force` at period end, its `confirmed_complaints_12mo`, and
    the two supplied indicators: `financial_stress_score` and
    `consumer_trend_score`, each an integer between 0 and 100 inclusive."

    Design: Corner/errors/err_duplicate_identifier_on_a_reused_naic_code
    """
    first = register_insurer()

    validate_error(
        api.register_insurer(
            insurer_payload(
                name="Entirely Different Legal Name Company",
                naic_code=first["naic_code"],
                annual_premium_written_cents=500,
                policy_count_in_force=5,
                confirmed_complaints_12mo=0,
                financial_stress_score=2,
                consumer_trend_score=3,
            ),
            ANALYST,
        ),
        ApiErrorId.ERR_DUPLICATE_IDENTIFIER.value,
        409,
    )

    twin = validate_success(
        api.register_insurer(
            insurer_payload(
                name=first["name"],
                naic_code="10002",
                annual_premium_written_cents=500,
                policy_count_in_force=5,
                confirmed_complaints_12mo=0,
                financial_stress_score=2,
                consumer_trend_score=3,
            ),
            ANALYST,
        ),
        201,
    )
    assert twin["name"] == first["name"], "name is not a uniqueness scope"

    _, meta = validate_paginated(api.list_insurers(ANALYST))
    assert meta["total_count"] == 2


# ─── Lifecycle-state band ─────────────────────────────────────────────────


def test_cycle_state_invalid_on_rescoring_and_on_early_selection(api):
    """The linear cycle machine refuses both a re-score and a selection out of order.

    PRD §3.2: "Running the pass on a cycle in any other state is
    `ERR_CYCLE_STATE_INVALID`, and that includes re-running it on a cycle that
    has already been scored."

    PRD §3.2: "Selection on a cycle that is not `SCORED` is
    `ERR_CYCLE_STATE_INVALID`, and a cycle with no remaining examiner slot —
    `slots_available` of 0 — cannot select at all and is rejected with
    `ERR_CYCLE_SLOTS_EXHAUSTED`."

    Design: Corner/errors/err_cycle_state_invalid_on_rescoring_and_early_selection
    """
    register_insurer()
    cycle = create_analysis_cycle(
        cycle_label="2026-H2-MARKET-ANALYSIS", target_slot_capacity=3
    )

    validate_error(
        api.select_targets(cycle["id"], ANALYST),
        ApiErrorId.ERR_CYCLE_STATE_INVALID.value,
        409,
    )

    scored = score_cycle(cycle["id"])
    assert scored["status"] == "SCORED"
    assert scored["scored_insurer_count"] == 1

    validate_error(
        api.score_analysis_cycle(cycle["id"], ANALYST),
        ApiErrorId.ERR_CYCLE_STATE_INVALID.value,
        409,
    )

    selected = select_targets(cycle["id"])
    assert selected["status"] == "TARGETS_SELECTED"

    validate_error(
        api.select_targets(cycle["id"], ANALYST),
        ApiErrorId.ERR_CYCLE_STATE_INVALID.value,
        409,
    )

    assert len(read_cycle_scores(cycle["id"])) == 1, "scoring ran exactly once"
    _, meta = validate_paginated(api.list_examinations(SUPERVISOR))
    assert meta["total_count"] == 1, "selection ran exactly once"


def test_exam_not_in_scoping_on_a_second_lock_and_a_later_scope_area(api):
    """Locking is single-shot and closes the scope to further areas.

    PRD §3.3: "Locking is possible only from `SCOPING` (otherwise
    `ERR_EXAM_NOT_IN_SCOPING`), requires at least one scope area to exist (an
    examination with `scope_area_count` of 0 is a malformed request,
    `ERR_INVALID_REQUEST`), and requires the subject carrier's `license_status`
    still to be `LICENSED` or `SUSPENDED` — a carrier that has become
    `WITHDRAWN` since the examination opened blocks the lock with
    `ERR_INSURER_NOT_EXAMINABLE`."

    PRD §3.3: "From that moment the areas are immutable: any further attempt to
    add a scope area is rejected with `ERR_EXAM_NOT_IN_SCOPING`."

    Design: Corner/errors/err_exam_not_in_scoping_on_a_second_lock
    """
    insurer = register_insurer()
    examination = open_examination(insurer["id"])
    validate_success(
        api.create_scope_area(examination["id"], scope_area_payload("CLAIMS"), EIC), 201
    )

    locked = validate_success(api.lock_scope(examination["id"], SUPERVISOR))
    assert locked["scope_locked"] is True
    assert locked["status"] == "DATA_CALL"
    assert locked["scope_area_count"] == 1

    validate_error(
        api.lock_scope(examination["id"], SUPERVISOR),
        ApiErrorId.ERR_EXAM_NOT_IN_SCOPING.value,
        409,
    )
    validate_error(
        api.create_scope_area(
            examination["id"],
            scope_area_payload("RATING", population_size=500, sample_size=10),
            EIC,
        ),
        ApiErrorId.ERR_EXAM_NOT_IN_SCOPING.value,
        409,
    )

    final = read_examination(examination["id"])
    assert final["status"] == "DATA_CALL"
    assert final["scope_locked"] is True
    assert final["scope_area_count"] == 1


def test_scope_not_locked_blocks_data_calls_and_workpapers(api):
    """Both a scope-area-scoped write and an examination-scoped write read the same freeze.

    PRD §3.4: "Issuing a data call while the owning examination is still in
    `SCOPING` — before scope was locked — is rejected with
    `ERR_SCOPE_NOT_LOCKED`."

    PRD §3.6: "Recording an activity while the examination is still in `SCOPING`
    is rejected with `ERR_SCOPE_NOT_LOCKED`."

    Design: Corner/errors/err_scope_not_locked_before_the_scope_is_frozen
    """
    insurer = register_insurer()
    examination = open_examination(insurer["id"])
    area = validate_success(
        api.create_scope_area(examination["id"], scope_area_payload("CLAIMS"), EIC), 201
    )

    validate_error(
        api.create_data_call(area["id"], data_call_payload(), EIC),
        ApiErrorId.ERR_SCOPE_NOT_LOCKED.value,
        409,
    )
    validate_error(
        api.create_fieldwork_activity(
            examination["id"],
            fieldwork_activity_payload(
                summary="Walked the claims platform before the scope was frozen.",
                evidence_ref="WP-CLM-00",
            ),
            EIC,
        ),
        ApiErrorId.ERR_SCOPE_NOT_LOCKED.value,
        409,
    )
    _, calls_meta = validate_paginated(api.list_scope_area_data_calls(area["id"], EIC))
    assert calls_meta["total_count"] == 0, "no data call existed before the lock"
    _, activity_meta = validate_paginated(
        api.list_fieldwork_activities(examination["id"], EIC)
    )
    assert activity_meta["total_count"] == 0, "no workpaper existed before the lock"

    lock_scope(examination["id"])

    data_call = validate_success(
        api.create_data_call(area["id"], data_call_payload(), EIC), 201
    )
    assert data_call["status"] == "ISSUED"
    validate_success(
        api.create_fieldwork_activity(
            examination["id"], fieldwork_activity_payload(), EIC
        ),
        201,
    )


def test_data_call_not_responded_on_disposition_and_on_bulk_review(api):
    """Disposition demands RESPONDED and bulk review demands ACCEPTED, under one code.

    PRD §3.4: "A call that is not in `RESPONDED` is rejected with
    `ERR_DATA_CALL_NOT_RESPONDED`."

    PRD §3.5: "Bulk review against a data call whose `status` is not `ACCEPTED`
    is rejected with `ERR_DATA_CALL_NOT_RESPONDED`."

    Design: Corner/errors/err_data_call_not_responded_on_disposition_and_bulk_review
    """
    scenario = setup_locked_examination()
    data_call = issue_data_call(scenario["scope_area_id"])

    validate_error(
        api.disposition_data_call(
            data_call["id"],
            disposition_payload(
                "ACCEPTED",
                disposition_reason="Disposition attempted before the carrier answered.",
            ),
            EIC,
        ),
        ApiErrorId.ERR_DATA_CALL_NOT_RESPONDED.value,
        409,
    )

    responded = respond_to_data_call(data_call["id"], scenario["insurer_id"])
    assert responded["status"] == "RESPONDED"

    validate_error(
        api.bulk_review(
            data_call["id"],
            bulk_review_payload(
                [{"file_reference": CLAIMS_REFERENCES[0], "error_severity": "NONE"}]
            ),
            EIC,
        ),
        ApiErrorId.ERR_DATA_CALL_NOT_RESPONDED.value,
        409,
    )

    accepted = disposition_data_call(data_call["id"], "ACCEPTED")
    assert accepted["status"] == "ACCEPTED"
    assert len(read_file_samples(data_call["id"], {"limit": 100})) == 10

    result = bulk_review(data_call["id"], build_reviews(CLAIMS_REFERENCES))
    assert result["scope_area_status"] == "TESTED"


def test_sample_already_reviewed_on_a_repeat_single_file_review(api):
    """A sampled file is reviewed exactly once and the endpoint is not idempotent.

    PRD §3.5: "Reviewing a file whose `review_status` is already `COMPLIANT` or
    `ERROR` is rejected with `ERR_SAMPLE_ALREADY_REVIEWED`."

    Design: Corner/errors/err_sample_already_reviewed_on_a_repeat_review
    """
    scenario = setup_area_in_fieldwork()
    sample = scenario["file_samples"][0]
    review_file_sample(
        sample["id"], "MATERIAL", underpaid_amount_cents=25_000, days_to_pay=61
    )

    validate_error(
        api.review_file_sample(sample["id"], file_review_payload("NONE"), EIC),
        ApiErrorId.ERR_SAMPLE_ALREADY_REVIEWED.value,
        409,
    )
    validate_error(
        api.review_file_sample(
            sample["id"],
            file_review_payload(
                "MATERIAL", underpaid_amount_cents=25_000, days_to_pay=61
            ),
            EIC,
        ),
        ApiErrorId.ERR_SAMPLE_ALREADY_REVIEWED.value,
        409,
    )

    stored = validate_success(api.get_file_sample(sample["id"], EIC))
    assert stored["review_status"] == "ERROR"
    assert stored["error_severity"] == "MATERIAL"
    assert stored["underpaid_amount_cents"] == 25_000
    assert read_scope_area(scenario["scope_area_id"])["reviewed_sample_count"] == 1, (
        "the refusals did not double-count the review"
    )


def test_exam_not_in_criticism_phase_while_the_examination_is_in_data_call(api):
    """Criticism issuance is open only across FIELDWORK and CRITICISM.

    PRD §3.6: "The examination's `status` must be `FIELDWORK` or `CRITICISM`,
    otherwise `ERR_EXAM_NOT_IN_CRITICISM_PHASE`."

    PRD §2.11 puts lifecycle state (band 8) above business safety (band 10), so
    an examination in `DATA_CALL` answers on the examination stage even though
    the referenced area is not yet `TESTED`.

    Design: Corner/errors/err_exam_not_in_criticism_phase_during_the_data_call_stage
    """
    scenario = setup_locked_examination()
    data_call = issue_data_call(scenario["scope_area_id"])
    assert read_examination(scenario["exam_id"])["status"] == "DATA_CALL"

    validate_error(
        api.issue_criticism(
            criticism_payload(scenario["exam_id"], scenario["scope_area_id"], "MATERIAL", 1),
            EIC,
        ),
        ApiErrorId.ERR_EXAM_NOT_IN_CRITICISM_PHASE.value,
        409,
    )

    respond_to_data_call(data_call["id"], scenario["insurer_id"])
    disposition_data_call(data_call["id"], "ACCEPTED")
    assert read_examination(scenario["exam_id"])["status"] == "FIELDWORK"

    record_standard_workpapers(scenario["exam_id"])
    bulk_review(data_call["id"], build_reviews(CLAIMS_REFERENCES))
    before = read_examination(scenario["exam_id"])
    assert before["status"] == "CRITICISM"
    assert before["open_criticism_count"] == 0

    criticism = validate_success(
        api.issue_criticism(
            criticism_payload(scenario["exam_id"], scenario["scope_area_id"], "MATERIAL", 3),
            EIC,
        ),
        201,
    )
    assert criticism["status"] == "ISSUED"
    assert read_examination(scenario["exam_id"])["open_criticism_count"] == 1


def test_exam_not_in_negotiation_for_a_plan_and_an_order_filed_from_criticism(api):
    """The state gate outranks the version pin on both enforcement writes.

    PRD §3.8: "The acting `X-User-ID` must equal the examination's `insurer_id`,
    otherwise `ERR_NOT_EXAM_SUBJECT`; the examination's `status` must be
    `NEGOTIATION`, otherwise `ERR_EXAM_NOT_IN_NEGOTIATION`."

    PRD §3.8: "The examination's `status` must be `NEGOTIATION` or
    `ORDER_PENDING`, otherwise `ERR_EXAM_NOT_IN_NEGOTIATION`, and the
    examination must already hold a corrective action plan in `APPROVED`,
    otherwise `ERR_CAP_NOT_APPROVED`."

    Design: Corner/errors/err_exam_not_in_negotiation_before_a_plan_is_invited
    """
    scenario = setup_examination_in_criticism()
    criticism = issue_criticism(scenario["exam_id"], scenario["scope_area_id"])
    observed_version = read_examination(scenario["exam_id"])["version"]
    respondent_headers = make_insurer_respondent_headers(scenario["insurer_id"])

    validate_error(
        api.propose_corrective_action_plan(
            scenario["exam_id"],
            corrective_action_plan_payload(
                observed_version,
                narrative=(
                    "The carrier files a remediation plan before the criticism has "
                    "been resolved."
                ),
            ),
            respondent_headers,
        ),
        ApiErrorId.ERR_EXAM_NOT_IN_NEGOTIATION.value,
        409,
    )
    validate_error(
        api.draft_consent_order(
            scenario["exam_id"],
            consent_order_payload(observed_version, "NV-MC-2026-0042", "PER_VIOLATION"),
            SUPERVISOR,
        ),
        ApiErrorId.ERR_EXAM_NOT_IN_NEGOTIATION.value,
        409,
    )
    _, plans_meta = validate_paginated(
        api.list_corrective_action_plans(scenario["exam_id"], SUPERVISOR)
    )
    assert plans_meta["total_count"] == 0
    _, orders_meta = validate_paginated(
        api.list_consent_orders(scenario["exam_id"], SUPERVISOR)
    )
    assert orders_meta["total_count"] == 0

    respond_to_criticism(criticism["id"], scenario["insurer_id"], "DISPUTE")
    validate_success(
        api.finalize_criticism(
            criticism["id"], criticism_finalize_payload("SUSTAINED", 20), SUPERVISOR_B
        )
    )
    assert read_examination(scenario["exam_id"])["status"] == "NEGOTIATION"

    plan = propose_plan(scenario["exam_id"], scenario["insurer_id"])
    assert plan["status"] == "PROPOSED"
    assert plan["revision_round"] == 1
