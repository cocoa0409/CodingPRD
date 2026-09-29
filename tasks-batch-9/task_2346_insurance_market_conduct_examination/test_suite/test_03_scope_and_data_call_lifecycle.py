"""Lifecycle transitions of the analysis cycle, the examination scope, the scope
area and the data call — the states each machine enters, the transitions it
refuses, and the counters a refused transition must leave alone.
"""

from test_helpers import (
    ANALYST,
    COORDINATOR,
    EIC,
    STANDARD_PARTICIPATING_STATES,
    SUPERVISOR,
    ApiErrorId,
    add_scope_area,
    analysis_cycle_payload,
    api_client,
    build_reviews,
    bulk_review,
    collaboration_payload,
    create_analysis_cycle,
    criticism_payload,
    data_call_payload,
    disposition_data_call,
    disposition_payload,
    examination_payload,
    fieldwork_activity_payload,
    file_review_payload,
    issue_data_call,
    lock_scope,
    read_cycle,
    read_examination,
    read_scope_area,
    record_standard_workpapers,
    register_insurer,
    respond_to_data_call,
    review_file_sample,
    scope_area_payload,
    score_cycle,
    setup_area_in_fieldwork,
    setup_examination_in_scoping,
    setup_locked_examination,
    systematic_file_references,
    validate_error,
    validate_paginated,
    validate_success,
)

CLAIMS_POPULATION = 4000
CLAIMS_SAMPLE = 10

# The standard claims batch: three MATERIAL files quantifying 25000, 18000 and
# 7333 cents of harm across ten reviewed files.
STANDARD_HARM_TOTAL_CENTS = 25_000 + 18_000 + 7_333
# 50333 / 10 reviewed files = 5033.3, rounded half up to 5033 cents per file,
# then multiplied by the 4000-file population.
EXTRAPOLATED_EXPOSURE_CENTS = 5_033 * CLAIMS_POPULATION


def test_every_lifecycle_machine_is_created_in_its_declared_initial_state():
    """Each lifecycle record enters the world in the state its workflow declares.

    PRD §3.2: "A new cycle opens in `DRAFT` with `slots_committed` at 0, `slots_available` equal to `target_slot_capacity`, and `scored_insurer_count` and `selected_target_count` both 0."
    PRD §3.3: "A newly opened examination sits in `SCOPING` with `scope_locked` false, `predecessor_exam_id` unset, and every derived counter at zero — `scope_area_count`, `rejected_data_call_count`, `open_criticism_count`, `sustained_criticism_count`, `pending_restitution_cents`, `aggregate_restitution_cents` and `penalty_units_total`."
    PRD §3.3: "Each new area starts in `PLANNED`, raises the examination's `scope_area_count` by 1 and increments the examination's `version` by 1."
    PRD §3.9: "The collaboration records `participant_count` as the roster's length, opens in `LEAD_ASSIGNED` with `allocated_total_cents` of 0, and elects its own `lead_state_code`."
    PRD §3.4: "The server stamps `issued_date` from the date part of the logical clock and opens the call in `ISSUED` with `records_received` 0, `is_late` false, `days_late` 0, `completeness_pct` 0.00, `effective_completeness_pct` 0.00, `sample_draw_interval` 0 and `samples_drawn_count` 0."
    PRD §3.6: "A new criticism opens in `ISSUED` with `response_round` 0 and `rebuttal_count` 0, records the acting `X-User-ID` as `issued_by_user_id` for the later segregation-of-duties comparison, raises the examination's `open_criticism_count` by 1 and its `pending_restitution_cents` by the frozen `restitution_exposure_cents`, and increments the examination's `version` by 1."

    Design: Corner/state_machines/every_state_machine_starts_in_its_declared_initial_state
    """
    cycle = validate_success(
        api_client.create_analysis_cycle(
            analysis_cycle_payload(
                cycle_label="2026-H2-MARKET-ANALYSIS", target_slot_capacity=3
            ),
            ANALYST,
        ),
        201,
    )
    assert cycle["status"] == "DRAFT"
    assert cycle["slots_committed"] == 0
    assert cycle["slots_available"] == 3
    assert cycle["scored_insurer_count"] == 0
    assert cycle["selected_target_count"] == 0

    insurer = register_insurer()

    examination = validate_success(
        api_client.open_examination(examination_payload(insurer["id"]), SUPERVISOR), 201
    )
    assert examination["status"] == "SCOPING"
    assert examination["scope_locked"] is False
    assert examination["scope_area_count"] == 0
    assert examination["open_criticism_count"] == 0

    area = validate_success(
        api_client.create_scope_area(
            examination["id"],
            scope_area_payload(
                "CLAIMS", population_size=CLAIMS_POPULATION, sample_size=CLAIMS_SAMPLE
            ),
            EIC,
        ),
        201,
    )
    assert area["status"] == "PLANNED"

    lock_scope(examination["id"])

    collaboration = validate_success(
        api_client.open_collaboration(
            examination["id"],
            collaboration_payload(STANDARD_PARTICIPATING_STATES),
            COORDINATOR,
        ),
        201,
    )
    assert collaboration["status"] == "LEAD_ASSIGNED"
    assert collaboration["participant_count"] == len(STANDARD_PARTICIPATING_STATES)
    assert collaboration["allocated_total_cents"] == 0

    data_call = validate_success(
        api_client.create_data_call(
            area["id"], data_call_payload(records_requested=CLAIMS_POPULATION), EIC
        ),
        201,
    )
    assert data_call["status"] == "ISSUED"
    assert data_call["records_received"] == 0
    assert data_call["is_late"] is False
    assert data_call["days_late"] == 0
    assert data_call["samples_drawn_count"] == 0

    respond_to_data_call(
        data_call["id"], insurer["id"], records_received=CLAIMS_POPULATION
    )
    disposition_data_call(data_call["id"], "ACCEPTED")
    record_standard_workpapers(examination["id"], "CLAIMS")
    bulk_review(
        data_call["id"],
        build_reviews(
            systematic_file_references("CLAIMS", CLAIMS_POPULATION, CLAIMS_SAMPLE)
        ),
    )

    criticism = validate_success(
        api_client.issue_criticism(
            criticism_payload(examination["id"], area["id"], "MATERIAL", 3), EIC
        ),
        201,
    )
    assert criticism["status"] == "ISSUED"
    assert criticism["response_round"] == 0
    assert criticism["rebuttal_count"] == 0


def test_scoring_a_cycle_twice_is_rejected_and_writes_no_second_score_batch():
    """A second scoring pass over a SCORED cycle is refused and adds no score row.

    PRD §3.2: "Running the pass on a cycle in any other state is `ERR_CYCLE_STATE_INVALID`, and that includes re-running it on a cycle that has already been scored."

    Design: Corner/state_machines/scoring_an_already_scored_cycle_is_rejected
    """
    register_insurer()
    cycle = create_analysis_cycle(target_slot_capacity=3)
    scored = score_cycle(cycle["id"])
    assert scored["status"] == "SCORED"
    assert scored["scored_insurer_count"] == 1

    validate_error(
        api_client.score_analysis_cycle(cycle["id"], ANALYST),
        ApiErrorId.ERR_CYCLE_STATE_INVALID.value,
    )

    after = read_cycle(cycle["id"])
    assert after["status"] == "SCORED"
    assert after["scored_insurer_count"] == 1

    _, meta = validate_paginated(api_client.list_cycle_scores(cycle["id"], ANALYST))
    assert meta["total_count"] == 1, "no duplicate analysis score row was written"


def test_select_targets_is_refused_before_scoring_and_after_selection():
    """Target selection is legal from SCORED alone: too early and too late both fail.

    PRD §3.2: "Selection on a cycle that is not `SCORED` is `ERR_CYCLE_STATE_INVALID`, and a cycle with no remaining examiner slot — `slots_available` of 0 — cannot select at all and is rejected with `ERR_CYCLE_SLOTS_EXHAUSTED`."

    Design: Corner/state_machines/selecting_targets_out_of_order_is_rejected_on_both_sides
    """
    register_insurer()
    cycle = create_analysis_cycle(target_slot_capacity=3)

    validate_error(
        api_client.select_targets(cycle["id"], ANALYST),
        ApiErrorId.ERR_CYCLE_STATE_INVALID.value,
    )
    _, meta = validate_paginated(
        api_client.list_examinations(SUPERVISOR, {"cycle_id": cycle["id"]})
    )
    assert meta["total_count"] == 0, "the rejected selection leaked no examination"
    assert read_cycle(cycle["id"])["slots_committed"] == 0

    score_cycle(cycle["id"])
    selected = validate_success(api_client.select_targets(cycle["id"], ANALYST))
    assert selected["status"] == "TARGETS_SELECTED"
    assert selected["selected_target_count"] == 1
    assert selected["slots_committed"] == 1

    validate_error(
        api_client.select_targets(cycle["id"], ANALYST),
        ApiErrorId.ERR_CYCLE_STATE_INVALID.value,
    )
    after = read_cycle(cycle["id"])
    assert after["selected_target_count"] == 1
    assert after["slots_committed"] == 1


def test_lock_scope_needs_at_least_one_scope_area_and_leaves_scoping_intact():
    """Locking an examination that holds no scope area is a malformed request.

    PRD §3.3: "Locking is possible only from `SCOPING` (otherwise `ERR_EXAM_NOT_IN_SCOPING`), requires at least one scope area to exist (an examination with `scope_area_count` of 0 is a malformed request, `ERR_INVALID_REQUEST`), and requires the subject carrier's `license_status` still to be `LICENSED` or `SUSPENDED` — a carrier that has become `WITHDRAWN` since the examination opened blocks the lock with `ERR_INSURER_NOT_EXAMINABLE`."
    PRD §3.3: "Locking sets `scope_locked` to true and increments the examination's `version` by 1."

    Design: Corner/state_machines/lock_scope_requires_at_least_one_scope_area
    """
    scenario = setup_examination_in_scoping()

    validate_error(
        api_client.lock_scope(scenario["exam_id"], SUPERVISOR),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )
    mid = read_examination(scenario["exam_id"])
    assert mid["status"] == "SCOPING"
    assert mid["scope_locked"] is False

    add_scope_area(
        scenario["exam_id"],
        "CLAIMS",
        population_size=CLAIMS_POPULATION,
        sample_size=CLAIMS_SAMPLE,
    )
    locked = validate_success(api_client.lock_scope(scenario["exam_id"], SUPERVISOR))
    assert locked["status"] == "DATA_CALL"
    assert locked["scope_locked"] is True
    assert locked["scope_area_count"] == 1


def test_locked_scope_refuses_both_a_further_area_and_a_second_lock():
    """Once locked, the scope-definition window is closed to both writes.

    PRD §3.3: "From that moment the areas are immutable: any further attempt to add a scope area is rejected with `ERR_EXAM_NOT_IN_SCOPING`."
    PRD §3.3: "Locking is possible only from `SCOPING` (otherwise `ERR_EXAM_NOT_IN_SCOPING`), requires at least one scope area to exist (an examination with `scope_area_count` of 0 is a malformed request, `ERR_INVALID_REQUEST`), and requires the subject carrier's `license_status` still to be `LICENSED` or `SUSPENDED` — a carrier that has become `WITHDRAWN` since the examination opened blocks the lock with `ERR_INSURER_NOT_EXAMINABLE`."

    Design: Corner/state_machines/scope_becomes_immutable_once_locked
    """
    scenario = setup_locked_examination()

    validate_error(
        api_client.create_scope_area(
            scenario["exam_id"],
            scope_area_payload(
                "UNDERWRITING",
                population_size=CLAIMS_POPULATION,
                sample_size=CLAIMS_SAMPLE,
            ),
            EIC,
        ),
        ApiErrorId.ERR_EXAM_NOT_IN_SCOPING.value,
    )
    validate_error(
        api_client.lock_scope(scenario["exam_id"], SUPERVISOR),
        ApiErrorId.ERR_EXAM_NOT_IN_SCOPING.value,
    )

    areas, meta = validate_paginated(
        api_client.list_scope_areas(scenario["exam_id"], EIC)
    )
    assert meta["total_count"] == 1
    assert areas[0]["area"] == "CLAIMS"
    assert areas[0]["exam_id"] == scenario["exam_id"]

    exam = read_examination(scenario["exam_id"])
    assert exam["scope_area_count"] == 1
    assert exam["status"] == "DATA_CALL"


def test_data_call_and_workpaper_are_both_refused_while_the_scope_is_unlocked():
    """One condition — the examination still in SCOPING — guards two endpoints.

    PRD §3.4: "Issuing a data call while the owning examination is still in `SCOPING` — before scope was locked — is rejected with `ERR_SCOPE_NOT_LOCKED`."
    PRD §3.6: "Recording an activity while the examination is still in `SCOPING` is rejected with `ERR_SCOPE_NOT_LOCKED`."

    Design: Corner/state_machines/data_calls_and_workpapers_both_require_a_locked_scope
    """
    scenario = setup_examination_in_scoping()
    area = add_scope_area(
        scenario["exam_id"],
        "CLAIMS",
        population_size=CLAIMS_POPULATION,
        sample_size=CLAIMS_SAMPLE,
    )

    validate_error(
        api_client.create_data_call(
            area["id"], data_call_payload(records_requested=CLAIMS_POPULATION), EIC
        ),
        ApiErrorId.ERR_SCOPE_NOT_LOCKED.value,
    )
    validate_error(
        api_client.create_fieldwork_activity(
            scenario["exam_id"],
            fieldwork_activity_payload("SYSTEM_WALKTHROUGH", "CLAIMS"),
            EIC,
        ),
        ApiErrorId.ERR_SCOPE_NOT_LOCKED.value,
    )

    _, meta = validate_paginated(
        api_client.list_scope_area_data_calls(area["id"], EIC)
    )
    assert meta["total_count"] == 0, "the rejected issuance persisted no data call"

    lock_scope(scenario["exam_id"])
    issued = validate_success(
        api_client.create_data_call(
            area["id"], data_call_payload(records_requested=CLAIMS_POPULATION), EIC
        ),
        201,
    )
    assert issued["status"] == "ISSUED"


def test_disposition_demands_a_responded_call_and_bulk_review_an_accepted_one():
    """One error code, two required predecessor states: RESPONDED then ACCEPTED.

    PRD §3.4: "A call that is not in `RESPONDED` is rejected with `ERR_DATA_CALL_NOT_RESPONDED`."
    PRD §3.5: "Bulk review against a data call whose `status` is not `ACCEPTED` is rejected with `ERR_DATA_CALL_NOT_RESPONDED`."

    Design: Corner/state_machines/disposition_and_bulk_review_each_demand_their_own_predecessor_state
    """
    scenario = setup_locked_examination()
    data_call = issue_data_call(
        scenario["scope_area_id"], records_requested=CLAIMS_POPULATION
    )
    one_review = [
        {
            "file_reference": "CLM-000001",
            "error_severity": "MATERIAL",
            "underpaid_amount_cents": 25_000,
            "days_to_pay": 61,
        }
    ]

    validate_error(
        api_client.disposition_data_call(
            data_call["id"], disposition_payload("ACCEPTED"), EIC
        ),
        ApiErrorId.ERR_DATA_CALL_NOT_RESPONDED.value,
    )
    validate_error(
        api_client.bulk_review(data_call["id"], {"reviews": one_review}, EIC),
        ApiErrorId.ERR_DATA_CALL_NOT_RESPONDED.value,
    )

    respond_to_data_call(
        data_call["id"], scenario["insurer_id"], records_received=CLAIMS_POPULATION
    )
    validate_error(
        api_client.bulk_review(data_call["id"], {"reviews": one_review}, EIC),
        ApiErrorId.ERR_DATA_CALL_NOT_RESPONDED.value,
    )

    accepted = validate_success(
        api_client.disposition_data_call(
            data_call["id"], disposition_payload("ACCEPTED"), EIC
        )
    )
    assert accepted["status"] == "ACCEPTED"
    assert accepted["samples_drawn_count"] == CLAIMS_SAMPLE

    result = validate_success(
        api_client.bulk_review(
            data_call["id"],
            {
                "reviews": build_reviews(
                    systematic_file_references(
                        "CLAIMS", CLAIMS_POPULATION, CLAIMS_SAMPLE
                    )
                )
            },
            EIC,
        )
    )
    assert result["applied_count"] == CLAIMS_SAMPLE
    assert result["scope_area_status"] == "TESTED"
    assert result["error_rate_pct"] == 30.00
    assert result["tolerance_breached"] is True


def test_reviewing_the_same_sampled_file_twice_is_rejected_and_changes_nothing():
    """A sampled file is reviewed once; the second review is refused, not applied.

    PRD §3.5: "Reviewing a file whose `review_status` is already `COMPLIANT` or `ERROR` is rejected with `ERR_SAMPLE_ALREADY_REVIEWED`."
    PRD §3.5: "The review derives `review_status` from severity: `COMPLIANT` when `error_severity` is `NONE`, and `ERROR` for both `MINOR` and `MATERIAL`."

    Design: Corner/state_machines/reviewing_the_same_sampled_file_twice_is_rejected
    """
    scenario = setup_area_in_fieldwork(
        area="CLAIMS", population_size=CLAIMS_POPULATION, sample_size=CLAIMS_SAMPLE
    )
    first_sample = scenario["file_samples"][0]
    review_file_sample(first_sample["id"], "NONE")

    validate_error(
        api_client.review_file_sample(
            first_sample["id"],
            file_review_payload(
                "MATERIAL", underpaid_amount_cents=99_999, days_to_pay=88
            ),
            EIC,
        ),
        ApiErrorId.ERR_SAMPLE_ALREADY_REVIEWED.value,
    )

    stored = validate_success(api_client.get_file_sample(first_sample["id"], EIC))
    assert stored["review_status"] == "COMPLIANT"
    assert stored["error_severity"] == "NONE"
    assert stored["underpaid_amount_cents"] == 0

    area = read_scope_area(scenario["scope_area_id"])
    assert area["reviewed_sample_count"] == 1
    assert area["error_count"] == 0
    assert area["status"] == "FIELDWORK"


def test_criticism_is_refused_in_data_call_but_issuable_from_fieldwork():
    """The criticism gate admits FIELDWORK as well as CRITICISM, but not DATA_CALL.

    PRD §3.6: "The examination's `status` must be `FIELDWORK` or `CRITICISM`, otherwise `ERR_EXAM_NOT_IN_CRITICISM_PHASE`."
    PRD §3.6: "Under `POPULATION_EXTRAPOLATED`, the summed underpayment is first divided by the reviewed-sample count and **that per-file average is rounded half up to a whole cent**, and only then is the rounded average multiplied by the area's `population_size` to give `restitution_exposure_cents`."

    Design: Corner/state_machines/criticism_issuance_is_open_in_fieldwork_but_closed_in_data_call
    """
    scenario = setup_locked_examination(
        areas=(
            ("CLAIMS", CLAIMS_POPULATION, CLAIMS_SAMPLE),
            ("UNDERWRITING", CLAIMS_POPULATION, CLAIMS_SAMPLE),
        )
    )
    claims = scenario["scope_areas"]["CLAIMS"]
    underwriting = scenario["scope_areas"]["UNDERWRITING"]

    validate_error(
        api_client.issue_criticism(
            criticism_payload(scenario["exam_id"], claims["id"], "MATERIAL", 3), EIC
        ),
        ApiErrorId.ERR_EXAM_NOT_IN_CRITICISM_PHASE.value,
    )

    data_call = issue_data_call(claims["id"], records_requested=CLAIMS_POPULATION)
    respond_to_data_call(
        data_call["id"], scenario["insurer_id"], records_received=CLAIMS_POPULATION
    )
    disposition_data_call(data_call["id"], "ACCEPTED")
    record_standard_workpapers(scenario["exam_id"], "CLAIMS")
    bulk_review(
        data_call["id"],
        build_reviews(
            systematic_file_references("CLAIMS", CLAIMS_POPULATION, CLAIMS_SAMPLE)
        ),
    )

    assert read_scope_area(claims["id"])["status"] == "TESTED"
    assert read_scope_area(underwriting["id"])["status"] == "PLANNED"
    assert read_examination(scenario["exam_id"])["status"] == "FIELDWORK"

    criticism = validate_success(
        api_client.issue_criticism(
            criticism_payload(scenario["exam_id"], claims["id"], "MATERIAL", 3), EIC
        ),
        201,
    )
    assert criticism["status"] == "ISSUED"
    assert criticism["restitution_method"] == "POPULATION_EXTRAPOLATED"
    assert criticism["restitution_exposure_cents"] == EXTRAPOLATED_EXPOSURE_CENTS

    exam = read_examination(scenario["exam_id"])
    assert exam["open_criticism_count"] == 1
    assert exam["pending_restitution_cents"] == EXTRAPOLATED_EXPOSURE_CENTS
