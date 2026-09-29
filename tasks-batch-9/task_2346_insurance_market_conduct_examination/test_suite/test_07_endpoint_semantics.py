"""Endpoint semantics: the query filters each collection declares, the pagination
envelope every list shares, the partial-success bulk review, the purely computed
exposure read, and the parent scoping of every nested collection.
"""

from test_helpers import (
    ANALYST,
    COORDINATOR,
    EIC,
    SUPERVISOR,
    SUPERVISOR_B,
    ApiErrorId,
    abort_payload,
    add_scope_area,
    api_client,
    build_reviews,
    bulk_review,
    collaboration_payload,
    company_response_payload,
    consent_order_payload,
    corrective_action_plan_payload,
    criticism_finalize_payload,
    data_call_payload,
    disposition_data_call,
    file_review_payload,
    is_iso8601_timestamp,
    issue_criticism,
    issue_data_call,
    lock_scope,
    make_insurer_respondent_headers,
    open_examination,
    order_execution_payload,
    plan_review_payload,
    publish_report_payload,
    rebuttal_payload,
    read_criticism,
    read_examination,
    read_scope_area,
    record_standard_workpapers,
    register_insurer,
    respond_to_data_call,
    scope_area_payload,
    setup_area_in_fieldwork,
    setup_examination_in_criticism,
    setup_examination_in_negotiation,
    setup_examination_in_scoping,
    setup_examination_with_drafted_order,
    systematic_file_references,
    validate_error,
    validate_paginated,
    validate_success,
)

CLAIMS_POPULATION = 4000
CLAIMS_SAMPLE = 10
RATING_POPULATION = 500
RATING_SAMPLE = 10

# The standard claims batch: three MATERIAL files quantifying 25000, 18000 and
# 7333 cents of harm across ten reviewed files.
CLAIMS_HARM_CENTS = (25_000, 18_000, 7_333)
CLAIMS_HARM_TOTAL_CENTS = 25_000 + 18_000 + 7_333
# 50333 / 10 reviewed files = 5033.3, rounded half up to 5033 cents per file,
# then multiplied by the 4000-file population.
EXTRAPOLATED_EXPOSURE_CENTS = 5_033 * CLAIMS_POPULATION
# The single MINOR rating file quantifies 1200 cents of harm.
RATING_HARM_CENTS = 1_200


def _two_areas_in_criticism_phase():
    """One carrier, one examination, a tested CLAIMS area and a tested RATING area.

    Both areas are carried through their own data call and bulk review so the
    examination reaches the criticism phase with two independently tested areas.
    """
    insurer = register_insurer()
    examination = open_examination(insurer["id"])
    exam_id = examination["id"]
    claims_area = add_scope_area(
        exam_id, "CLAIMS", population_size=CLAIMS_POPULATION, sample_size=CLAIMS_SAMPLE
    )
    rating_area = add_scope_area(
        exam_id, "RATING", population_size=RATING_POPULATION, sample_size=RATING_SAMPLE
    )
    lock_scope(exam_id)

    claims_call = issue_data_call(
        claims_area["id"], records_requested=CLAIMS_POPULATION
    )
    rating_call = issue_data_call(
        rating_area["id"], records_requested=RATING_POPULATION
    )
    respond_to_data_call(
        claims_call["id"], insurer["id"], records_received=CLAIMS_POPULATION
    )
    respond_to_data_call(
        rating_call["id"], insurer["id"], records_received=RATING_POPULATION
    )
    disposition_data_call(claims_call["id"], "ACCEPTED")
    disposition_data_call(rating_call["id"], "ACCEPTED")

    record_standard_workpapers(exam_id, "CLAIMS")

    bulk_review(
        claims_call["id"],
        build_reviews(
            systematic_file_references("CLAIMS", CLAIMS_POPULATION, CLAIMS_SAMPLE),
            CLAIMS_HARM_CENTS,
            "MATERIAL",
        ),
    )
    bulk_review(
        rating_call["id"],
        build_reviews(
            systematic_file_references("RATING", RATING_POPULATION, RATING_SAMPLE),
            (RATING_HARM_CENTS,),
            "MINOR",
            days_to_pay=(22,),
        ),
    )
    return {
        "insurer_id": insurer["id"],
        "respondent_headers": make_insurer_respondent_headers(insurer["id"]),
        "exam_id": exam_id,
        "claims_area_id": claims_area["id"],
        "rating_area_id": rating_area["id"],
    }


def test_criticism_collections_compose_their_declared_query_filters():
    """The criticism filters narrow together and the response rounds filter on position.

    PRD §3.6: "Criticisms may be listed filtered by `exam_id`, `scope_area_id` or `status`."
    PRD §3.7: "Response rounds may be listed per criticism, filtered optionally by `position`."
    PRD §2.3: "For list responses the `meta` object carries `limit`, `offset`, `total_count` (the count of rows matching the filter before the window is applied) and `has_more` (true when rows remain beyond the current window)."
    PRD §3.6: "In every other case the method is `SAMPLE_ACTUAL`."
    PRD §3.6: "Under `SAMPLE_ACTUAL`, `restitution_exposure_cents` equals the observed sample harm exactly — the summed underpayment across the area's error files — and the unexamined remainder of the population is not charged."
    PRD §3.7: "The answer supplies a `position` of `CONCUR`, `PARTIAL_CONCUR` or `DISPUTE`, a `narrative` of at least 20 characters, and optionally a `remediation_offer_cents` figure naming restitution the carrier offers to pay voluntarily, which defaults to 0 and must be zero or greater."

    Design: Corner/endpoints/criticism_reads_honour_every_declared_query_filter
    """
    scenario = _two_areas_in_criticism_phase()
    exam_id = scenario["exam_id"]
    claims_area_id = scenario["claims_area_id"]
    rating_area_id = scenario["rating_area_id"]

    claims_criticism = issue_criticism(exam_id, claims_area_id, "MATERIAL", 3)
    rating_criticism = issue_criticism(
        exam_id, rating_area_id, "MINOR", 1, statute_citation="NRS 686B.020(1)"
    )
    validate_success(
        api_client.create_company_response(
            claims_criticism["id"],
            company_response_payload("DISPUTE"),
            scenario["respondent_headers"],
        ),
        201,
    )

    by_exam, meta = validate_paginated(
        api_client.list_criticisms(EIC, {"exam_id": exam_id})
    )
    assert meta["total_count"] == 2, "both criticisms of the examination match exam_id"
    assert {row["id"] for row in by_exam} == {
        claims_criticism["id"],
        rating_criticism["id"],
    }

    by_area, meta = validate_paginated(
        api_client.list_criticisms(
            EIC, {"exam_id": exam_id, "scope_area_id": rating_area_id}
        )
    )
    assert meta["total_count"] == 1, "adding scope_area_id narrows the same collection"
    assert by_area[0]["id"] == rating_criticism["id"]
    assert by_area[0]["severity"] == "MINOR"

    responded, meta = validate_paginated(
        api_client.list_criticisms(EIC, {"status": "RESPONDED"})
    )
    assert meta["total_count"] == 1
    assert responded[0]["id"] == claims_criticism["id"]
    assert responded[0]["response_round"] == 1

    conjunction, meta = validate_paginated(
        api_client.list_criticisms(
            EIC, {"scope_area_id": claims_area_id, "status": "ISSUED"}
        )
    )
    assert meta["total_count"] == 0, (
        "the claims criticism is RESPONDED, so an AND of two individually "
        "non-empty filters is empty"
    )
    assert conjunction == []

    detail = validate_success(api_client.get_criticism(rating_criticism["id"], EIC))
    assert detail["status"] == "ISSUED"
    assert detail["restitution_method"] == "SAMPLE_ACTUAL"
    assert detail["restitution_exposure_cents"] == RATING_HARM_CENTS
    assert detail["rebuttal_count"] == 0

    validate_success(
        api_client.create_company_response(
            rating_criticism["id"],
            company_response_payload(
                "CONCUR",
                narrative=(
                    "The carrier concurs with the rating documentation finding "
                    "and will refile."
                ),
            ),
            scenario["respondent_headers"],
        ),
        201,
    )

    disputes, meta = validate_paginated(
        api_client.list_company_responses(
            claims_criticism["id"], EIC, {"position": "DISPUTE"}
        )
    )
    assert meta["total_count"] == 1
    assert disputes[0]["round_number"] == 1
    assert disputes[0]["remediation_offer_cents"] == 0, (
        "remediation_offer_cents defaults to 0 when the carrier offers nothing"
    )

    concurs, meta = validate_paginated(
        api_client.list_company_responses(
            claims_criticism["id"], EIC, {"position": "CONCUR"}
        )
    )
    assert meta["total_count"] == 0, (
        "responses are scoped to their own criticism, not to the examination"
    )
    assert concurs == []


def test_pagination_defaults_bounds_and_total_count_are_uniform():
    """The window bounds, the defaults and the filtered total_count of a collection.

    PRD §2.3: "Every list endpoint accepts two optional query parameters."
    PRD §2.3: "`limit` defaults to 10, may be no lower than 1 and no higher than 100."
    PRD §2.3: "`offset` defaults to 0 and may be no lower than 0."
    PRD §2.3: "A value outside those ranges is a malformed request."
    PRD §2.3: "For list responses the `meta` object carries `limit`, `offset`, `total_count` (the count of rows matching the filter before the window is applied) and `has_more` (true when rows remain beyond the current window)."
    PRD §3.1: "Carriers may be listed with an optional `license_status` filter and an optional `risk_tier` filter."

    Design: Corner/endpoints/pagination_defaults_and_bounds_are_uniform_across_collections
    """
    first = register_insurer(name="Aurora Mutual Insurance Company", naic_code="10001")
    second = register_insurer(name="Boreal Casualty Company", naic_code="10002")
    third = register_insurer(name="Cascade Indemnity Group", naic_code="10003")
    all_ids = {first["id"], second["id"], third["id"]}

    defaulted, meta = validate_paginated(api_client.list_insurers(ANALYST))
    assert meta["limit"] == 10, "limit defaults to 10"
    assert meta["offset"] == 0, "offset defaults to 0"
    assert meta["total_count"] == 3
    assert meta["has_more"] is False
    assert len(defaulted) == 3
    for row in defaulted:
        for envelope_key in ("limit", "offset", "total_count", "has_more"):
            assert envelope_key not in row, (
                "the pagination fields live in meta and never inside data"
            )

    page_one, meta = validate_paginated(
        api_client.list_insurers(ANALYST, {"limit": 2, "offset": 0})
    )
    assert len(page_one) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True, "one row remains beyond the current window"

    page_two, meta = validate_paginated(
        api_client.list_insurers(ANALYST, {"limit": 2, "offset": 2})
    )
    assert len(page_two) == 1
    assert meta["total_count"] == 3
    assert meta["has_more"] is False
    assert {row["id"] for row in page_one} | {row["id"] for row in page_two} == all_ids

    past_end, meta = validate_paginated(
        api_client.list_insurers(ANALYST, {"limit": 2, "offset": 99})
    )
    assert past_end == [], "an offset past the end is an empty page, not an error"
    assert meta["total_count"] == 3
    assert meta["has_more"] is False

    validate_error(
        api_client.list_insurers(ANALYST, {"limit": 0}),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )
    validate_error(
        api_client.list_insurers(ANALYST, {"limit": 101}),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    at_maximum, meta = validate_paginated(api_client.list_insurers(ANALYST, {"limit": 100}))
    assert meta["limit"] == 100, "the maximum limit of 100 is accepted"
    assert len(at_maximum) == 3

    suspended, meta = validate_paginated(
        api_client.list_insurers(ANALYST, {"license_status": "SUSPENDED"})
    )
    assert suspended == []
    assert meta["total_count"] == 0, "all three carriers are LICENSED"

    elevated, meta = validate_paginated(
        api_client.list_insurers(ANALYST, {"risk_tier": "ELEVATED", "limit": 1})
    )
    assert len(elevated) == 1
    assert meta["total_count"] == 3, (
        "total_count counts the rows matching the filter before the window: all "
        "three carriers sit at a 3.00 ratio and are therefore ELEVATED"
    )


def test_bulk_review_applies_what_it_can_and_reports_what_it_skipped():
    """Bulk review skips an already-reviewed file where the single review refuses it.

    PRD §3.5: "Unlike the single-file review, the bulk action is forgiving about files already reviewed: it **skips** them rather than failing."
    PRD §3.5: "It answers with `{ applied_count, skipped_count, skipped_file_references, scope_area_status, reviewed_sample_count, error_count, error_rate_pct, material_error_rate_pct, tolerance_breached, escalation_required }`, where `applied_count` counts the files actually reviewed, `skipped_count` and `skipped_file_references` report the already-reviewed references that were passed over, and the remaining members mirror the owning area's state after the batch."
    PRD §3.5: "Reviewing a file whose `review_status` is already `COMPLIANT` or `ERROR` is rejected with `ERR_SAMPLE_ALREADY_REVIEWED`."
    PRD §3.5: "The array may not be empty and may not name the same `file_reference` twice."
    PRD §2.11: "Malformed-request rejection in band 6 covers, across all write endpoints: a required field missing; a field carrying the wrong JSON type; an enum field carrying a value outside its declared set; a monetary or count field that is negative; `sample_size`, `population_size`, `records_requested`, `milestone_count` or `target_slot_capacity` that is not at least 1; a date field that is not formatted `YYYY-MM-DD`; `fieldwork_end_date` that is not strictly after `fieldwork_start_date`; `reference_period_end` that is not strictly after `reference_period_start`; `default_fieldwork_end` that is not strictly after `default_fieldwork_start`; a percentage field outside the inclusive range 0.00 to 100.00; a `narrative`, `summary`, `public_summary` or `rebuttal_note` shorter than 20 characters; a `participating_states` array that is empty, contains a duplicate `state_code`, contains a `state_code` that is not exactly two uppercase letters, or whose `policy_count_in_state` values total zero; a `reviews` array that is empty or contains a duplicate `file_reference`; a `min_composite_score` outside the inclusive range 0.00 to 100.00; a `to_iso8601` that is not an RFC3339 UTC instant; and a scope-lock attempt on an examination that has no scope areas at all."
    PRD §2.3: "Two endpoints do state otherwise: the scores of one cycle are returned in rank order, and the file samples of one accepted data call are returned in ascending `population_index` order — which, because samples are materialised in ascending index order, coincides with `created_at` ascending anyway."

    Design: Corner/endpoints/bulk_review_applies_what_it_can_and_reports_what_it_skipped
    """
    scenario = setup_area_in_fieldwork(
        area="CLAIMS", population_size=CLAIMS_POPULATION, sample_size=CLAIMS_SAMPLE
    )
    samples = scenario["file_samples"]
    assert samples[0]["file_reference"] == "CLM-000001"
    assert samples[0]["population_index"] == 1

    reviewed = validate_success(
        api_client.review_file_sample(
            samples[0]["id"],
            file_review_payload(
                "MATERIAL", underpaid_amount_cents=25_000, days_to_pay=61
            ),
            EIC,
        )
    )
    assert reviewed["review_status"] == "ERROR"
    assert reviewed["error_severity"] == "MATERIAL"
    assert is_iso8601_timestamp(reviewed["reviewed_at"])

    validate_error(
        api_client.review_file_sample(
            samples[0]["id"],
            file_review_payload("MINOR", underpaid_amount_cents=1, days_to_pay=1),
            EIC,
        ),
        ApiErrorId.ERR_SAMPLE_ALREADY_REVIEWED.value,
    )

    batch = validate_success(
        api_client.bulk_review(
            scenario["data_call_id"],
            {
                "reviews": [
                    {
                        "file_reference": "CLM-000401",
                        "error_severity": "MINOR",
                        "underpaid_amount_cents": 4_000,
                        "days_to_pay": 33,
                    },
                    {"file_reference": "CLM-000801", "error_severity": "NONE"},
                    {"file_reference": "CLM-001201", "error_severity": "NONE"},
                    {"file_reference": "CLM-000001", "error_severity": "NONE"},
                ]
            },
            EIC,
        )
    )
    assert batch["applied_count"] == 3
    assert batch["skipped_count"] == 1
    assert batch["skipped_file_references"] == ["CLM-000001"]
    assert batch["reviewed_sample_count"] == 4, (
        "the individually reviewed file is included in the recomputed counters"
    )
    assert batch["error_count"] == 2
    assert batch["error_rate_pct"] == 50.00
    assert batch["material_error_rate_pct"] == 25.00
    assert batch["tolerance_breached"] is True, "50.00 breaches the 3.00 CLAIMS default"
    assert batch["escalation_required"] is True, "25.00 is at or above 10.00"
    assert batch["scope_area_status"] == "FIELDWORK", "only 4 of 10 drawn files are reviewed"

    area = read_scope_area(scenario["scope_area_id"])
    assert area["reviewed_sample_count"] == 4
    assert area["error_count"] == 2
    assert area["material_error_count"] == 1
    assert area["error_rate_pct"] == 50.00
    assert area["material_error_rate_pct"] == 25.00
    assert area["status"] == "FIELDWORK"

    drawn, meta = validate_paginated(
        api_client.list_file_samples(scenario["data_call_id"], EIC, {"limit": 100})
    )
    assert meta["total_count"] == CLAIMS_SAMPLE
    assert [row["population_index"] for row in drawn] == sorted(
        row["population_index"] for row in drawn
    ), "the drawn files are returned in ascending population_index order"
    unreviewed = [row for row in drawn if row["review_status"] == "UNREVIEWED"]
    assert len(unreviewed) == 6
    material = [row for row in drawn if row["error_severity"] == "MATERIAL"]
    assert len(material) == 1
    assert material[0]["underpaid_amount_cents"] == 25_000

    validate_error(
        api_client.bulk_review(scenario["data_call_id"], {"reviews": []}, EIC),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )


def test_the_exposure_summary_is_a_pure_computed_read():
    """Both penalty variants are projected side by side without persisting either.

    PRD §3.8: "Because the two variants can differ enormously for the same examination, a supervising examiner or multistate coordinator may ask for both side by side without persisting either."
    PRD §3.8: "Nothing is written and no cap rejection occurs on this read."
    PRD §3.8: "The **per-violation** algorithm ignores restitution size entirely: the gross penalty is the examination's `penalty_units_total` multiplied by 25,000 cents (250 dollars per statutory violation unit)."
    PRD §3.8: "Each tier's amount is multiplied by its own rate — one tenth for the first tier, six hundredths for the second, three hundredths for the third — and **each of those three products is rounded half up to a whole cent individually before the three are added together**."
    PRD §3.8: "Step three: `cooperation_credit_pct` is fifteen hundredths when the subtotal is 25,000,000 cents or more, and five hundredths otherwise."
    PRD §3.8: "Step four: `penalty_net_cents` is the gross penalty multiplied by one minus the credit rate, rounded half up to a whole cent."
    PRD §3.8: "Step five: `order_total_cents` is the restitution aggregate plus the net penalty."
    PRD §3.6: "Under `POPULATION_EXTRAPOLATED`, the summed underpayment is first divided by the reviewed-sample count and **that per-file average is rounded half up to a whole cent**, and only then is the rounded average multiplied by the area's `population_size` to give `restitution_exposure_cents`."

    Design: Corner/endpoints/the_exposure_summary_is_a_pure_computed_read
    """
    scenario = setup_examination_in_negotiation(
        criticism_severity="MATERIAL", affected_file_count=3, penalty_units=20
    )
    exam_id = scenario["exam_id"]

    # 20 penalty units at 25,000 cents each, credited 5 percent because the
    # gross subtotal stays below 25,000,000 cents.
    per_violation_gross = 20 * 25_000
    per_violation_net = 475_000
    per_violation_total = EXTRAPOLATED_EXPOSURE_CENTS + per_violation_net
    # Tier one: 5,000,000 at one tenth. Tier two: 15,132,000 at six hundredths.
    # Tier three: nothing. Plus 100,000 cents for the one sustained criticism.
    tiered_gross = 500_000 + 907_920 + 100_000
    tiered_net = 1_432_524
    tiered_total = EXTRAPOLATED_EXPOSURE_CENTS + tiered_net

    version_before = read_examination(exam_id)["version"]

    summary = validate_success(api_client.get_exposure_summary(exam_id, SUPERVISOR))
    assert summary["examination_id"] == exam_id
    assert summary["sustained_criticism_count"] == 1
    assert summary["aggregate_restitution_cents"] == EXTRAPOLATED_EXPOSURE_CENTS
    assert summary["penalty_units_total"] == 20
    assert summary["per_violation_penalty_gross_cents"] == per_violation_gross
    assert summary["per_violation_cooperation_credit_pct"] == 0.05
    assert summary["per_violation_penalty_net_cents"] == per_violation_net
    assert summary["per_violation_order_total_cents"] == per_violation_total
    assert summary["tiered_penalty_gross_cents"] == tiered_gross
    assert summary["tiered_cooperation_credit_pct"] == 0.05
    assert summary["tiered_penalty_net_cents"] == tiered_net
    assert summary["tiered_order_total_cents"] == tiered_total

    coordinator_summary = validate_success(
        api_client.get_exposure_summary(exam_id, COORDINATOR)
    )
    assert coordinator_summary == summary, (
        "the same object is readable by the supervising examiner and the coordinator"
    )

    assert read_examination(exam_id)["version"] == version_before, (
        "the computed read writes nothing to the examination"
    )

    orders, meta = validate_paginated(api_client.list_consent_orders(exam_id, SUPERVISOR))
    assert meta["total_count"] == 0, "no ConsentOrder was created by the read"
    assert orders == []

    plan = validate_success(
        api_client.propose_corrective_action_plan(
            exam_id,
            corrective_action_plan_payload(read_examination(exam_id)["version"]),
            scenario["respondent_headers"],
        ),
        201,
    )
    validate_success(
        api_client.review_corrective_action_plan(
            plan["id"], plan_review_payload("APPROVE"), SUPERVISOR
        )
    )
    order = validate_success(
        api_client.draft_consent_order(
            exam_id,
            consent_order_payload(
                read_examination(exam_id)["version"],
                "NV-MC-2026-0042",
                "PER_VIOLATION",
            ),
            SUPERVISOR,
        ),
        201,
    )
    assert order["order_total_cents"] == per_violation_total, (
        "the drafted variant carries exactly the figure the summary projected"
    )

    after_drafting = validate_success(api_client.get_exposure_summary(exam_id, SUPERVISOR))
    assert after_drafting["per_violation_order_total_cents"] == per_violation_total
    assert after_drafting["tiered_order_total_cents"] == tiered_total, (
        "drafting one variant does not suppress the projection of the other"
    )


def test_publication_from_order_pending_requires_an_executed_order():
    """A drafted but unsigned order is not enough to publish from ORDER_PENDING.

    PRD §3.10: "It requires a consent order on the examination whose `status` is `EXECUTED`, otherwise `ERR_ORDER_NOT_EXECUTED`, and the acting `X-User-ID` must differ from that order's `drafted_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.10: "The examination advances `ORDER_PENDING → PUBLISHED`, stamping `report_published_at` and recording `public_summary` as before, but here `followup_required` is set to true and `followup_due_date` is computed."
    PRD §3.8: "Execution stamps `executed_at` from the logical clock, moves the order to `EXECUTED`, increments the order's `version` by 1, and raises the subject carrier's `lifetime_restitution_ordered_cents` by the order's frozen `restitution_cents`."
    PRD §3.10: "The enforcement branch also creates the **follow-up examination** itself, in `SCOPING`."
    PRD §3.3: "Examinations can be listed filtered by `insurer_id`, `cycle_id`, `predecessor_exam_id` or `status`."

    Design: Corner/endpoints/publication_from_order_pending_requires_an_executed_order
    """
    scenario = setup_examination_with_drafted_order(
        penalty_variant="PER_VIOLATION", order_number="NV-MC-2026-0042"
    )
    exam_id = scenario["exam_id"]
    order_id = scenario["consent_order_id"]
    assert scenario["consent_order"]["status"] == "DRAFT"
    assert scenario["examination"]["status"] == "ORDER_PENDING"

    validate_error(
        api_client.publish_report(
            exam_id,
            publish_report_payload(
                public_summary=(
                    "The department attempts publication while the consent order "
                    "is still unsigned."
                )
            ),
            SUPERVISOR_B,
        ),
        ApiErrorId.ERR_ORDER_NOT_EXECUTED.value,
    )

    still_pending = read_examination(exam_id)
    assert still_pending["status"] == "ORDER_PENDING"
    assert still_pending["report_published_at"] is None
    assert still_pending["followup_required"] is False

    executed = validate_success(
        api_client.execute_consent_order(
            order_id,
            order_execution_payload(signed_by="M. Halloran, President and CEO"),
            scenario["respondent_headers"],
        )
    )
    assert executed["status"] == "EXECUTED"

    published = validate_success(
        api_client.publish_report(
            exam_id,
            publish_report_payload(
                public_summary=(
                    "The department publishes its market conduct examination "
                    "report for public inspection."
                )
            ),
            SUPERVISOR_B,
        )
    )
    assert published["status"] == "PUBLISHED"
    assert published["followup_required"] is True
    assert is_iso8601_timestamp(published["report_published_at"])

    followups, meta = validate_paginated(
        api_client.list_examinations(SUPERVISOR, {"predecessor_exam_id": exam_id})
    )
    assert meta["total_count"] == 1, "exactly one follow-up examination now exists"
    assert followups[0]["predecessor_exam_id"] == exam_id
    assert followups[0]["status"] == "SCOPING"


def test_abort_fires_from_any_non_terminal_state_and_only_once():
    """Abort has no source-state precondition, and the terminal guard outranks the rest.

    PRD §3.10: "A `SupervisingExaminer` may abort any examination whose `status` is not already terminal, supplying an `abort_reason` recording the justification."
    PRD §3.10: "An examination already in `PUBLISHED` or `ABORTED` is rejected with `ERR_EXAM_ALREADY_TERMINAL`, which also covers a second abort attempt."
    PRD §2.11: "Finally, `ERR_EXAM_ALREADY_TERMINAL` guards every write nested under an examination and every write on any of its descendants — scope areas, data calls, file samples, criticisms, company responses, corrective action plans, consent orders and the collaboration alike — once that examination's `status` is `PUBLISHED` or `ABORTED`."
    PRD §2.11: "Checks are evaluated in the following bands, in this order, and the first band that produces a rejection determines the response:"
    PRD §2.11: "Malformed-request rejection in band 6 covers, across all write endpoints: a required field missing; a field carrying the wrong JSON type; an enum field carrying a value outside its declared set; a monetary or count field that is negative; `sample_size`, `population_size`, `records_requested`, `milestone_count` or `target_slot_capacity` that is not at least 1; a date field that is not formatted `YYYY-MM-DD`; `fieldwork_end_date` that is not strictly after `fieldwork_start_date`; `reference_period_end` that is not strictly after `reference_period_start`; `default_fieldwork_end` that is not strictly after `default_fieldwork_start`; a percentage field outside the inclusive range 0.00 to 100.00; a `narrative`, `summary`, `public_summary` or `rebuttal_note` shorter than 20 characters; a `participating_states` array that is empty, contains a duplicate `state_code`, contains a `state_code` that is not exactly two uppercase letters, or whose `policy_count_in_state` values total zero; a `reviews` array that is empty or contains a duplicate `file_reference`; a `min_composite_score` outside the inclusive range 0.00 to 100.00; a `to_iso8601` that is not an RFC3339 UTC instant; and a scope-lock attempt on an examination that has no scope areas at all."
    PRD §3.3: "Examinations can be listed filtered by `insurer_id`, `cycle_id`, `predecessor_exam_id` or `status`."

    Design: Corner/endpoints/abort_is_reachable_from_every_non_terminal_state_and_only_once
    """
    scoping = setup_examination_in_scoping()
    scoping_exam_id = scoping["exam_id"]

    second_insurer = register_insurer(
        name="Boreal Casualty Company", naic_code="10002"
    )
    locked_exam = open_examination(second_insurer["id"])
    locked_exam_id = locked_exam["id"]
    locked_area = add_scope_area(
        locked_exam_id,
        "CLAIMS",
        population_size=CLAIMS_POPULATION,
        sample_size=CLAIMS_SAMPLE,
    )
    lock_scope(locked_exam_id)
    assert read_examination(locked_exam_id)["status"] == "DATA_CALL"

    scoping_reason = (
        "The examination is withdrawn following a company-wide receivership order."
    )
    aborted_from_scoping = validate_success(
        api_client.abort_examination(
            scoping_exam_id, abort_payload(abort_reason=scoping_reason), SUPERVISOR
        )
    )
    assert aborted_from_scoping["status"] == "ABORTED"
    assert aborted_from_scoping["abort_reason"] == scoping_reason

    data_call_reason = (
        "The second examination is withdrawn after the carrier entered rehabilitation."
    )
    aborted_from_data_call = validate_success(
        api_client.abort_examination(
            locked_exam_id, abort_payload(abort_reason=data_call_reason), SUPERVISOR
        )
    )
    assert aborted_from_data_call["status"] == "ABORTED", (
        "abort has no source-state precondition"
    )
    assert aborted_from_data_call["abort_reason"] == data_call_reason

    validate_error(
        api_client.abort_examination(
            scoping_exam_id,
            abort_payload(
                abort_reason="A second withdrawal is attempted on an already aborted examination."
            ),
            SUPERVISOR,
        ),
        ApiErrorId.ERR_EXAM_ALREADY_TERMINAL.value,
    )

    validate_error(
        api_client.create_scope_area(
            scoping_exam_id,
            scope_area_payload(
                "CLAIMS",
                population_size=CLAIMS_POPULATION,
                sample_size=CLAIMS_SAMPLE,
            ),
            EIC,
        ),
        ApiErrorId.ERR_EXAM_ALREADY_TERMINAL.value,
    )

    validate_error(
        api_client.abort_examination(locked_exam_id, {}, SUPERVISOR),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    validate_error(
        api_client.create_data_call(
            locked_area["id"], data_call_payload(records_requested=CLAIMS_POPULATION), EIC
        ),
        ApiErrorId.ERR_EXAM_ALREADY_TERMINAL.value,
    )

    aborted, meta = validate_paginated(
        api_client.list_examinations(SUPERVISOR, {"status": "ABORTED"})
    )
    assert meta["total_count"] == 2
    assert {row["id"] for row in aborted} == {scoping_exam_id, locked_exam_id}


def test_rebut_is_legal_only_from_responded_and_returns_the_criticism_to_issued():
    """Rebuttal and finalization share one precondition; their counters do not.

    PRD §3.7: "The `ExaminerInCharge` may rebut a `RESPONDED` criticism, supplying a `rebuttal_note` of at least 20 characters, which returns the criticism to `ISSUED` for another round, raises `rebuttal_count` by 1 and increments the criticism's `version` by 1."
    PRD §3.7: "Rebutting a criticism that is not `RESPONDED` is `ERR_CRITICISM_STATE_INVALID`."
    PRD §3.7: "Finalizing a criticism that is not `RESPONDED` is `ERR_CRITICISM_STATE_INVALID`, and the acting `X-User-ID` must differ from the criticism's `issued_by_user_id` or the request is rejected with `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.7: "Each answer materialises a `CompanyResponse` carrying its `criticism_id`, its `round_number` — one greater than the criticism's `response_round` before the answer, and therefore equal to the criticism's `response_round` immediately afterwards — and a `submitted_at` stamp from the logical clock."
    PRD §3.6: "A new criticism opens in `ISSUED` with `response_round` 0 and `rebuttal_count` 0, records the acting `X-User-ID` as `issued_by_user_id` for the later segregation-of-duties comparison, raises the examination's `open_criticism_count` by 1 and its `pending_restitution_cents` by the frozen `restitution_exposure_cents`, and increments the examination's `version` by 1."

    Design: Corner/endpoints/rebut_is_legal_only_from_responded_and_returns_the_criticism_to_issued
    """
    scenario = setup_examination_in_criticism()
    criticism = issue_criticism(
        scenario["exam_id"], scenario["scope_area_id"], "MATERIAL", 3
    )
    criticism_id = criticism["id"]
    assert criticism["status"] == "ISSUED"
    assert criticism["response_round"] == 0
    assert criticism["rebuttal_count"] == 0

    validate_error(
        api_client.rebut_criticism(
            criticism_id,
            rebuttal_payload(
                rebuttal_note="The department rebuts before the carrier has answered at all."
            ),
            EIC,
        ),
        ApiErrorId.ERR_CRITICISM_STATE_INVALID.value,
    )
    validate_error(
        api_client.finalize_criticism(
            criticism_id,
            criticism_finalize_payload(
                "SUSTAINED",
                20,
                disposition_note="The department sustains before the carrier has answered.",
            ),
            SUPERVISOR,
        ),
        ApiErrorId.ERR_CRITICISM_STATE_INVALID.value,
    )

    first_answer = validate_success(
        api_client.create_company_response(
            criticism_id, company_response_payload("DISPUTE"), scenario["respondent_headers"]
        ),
        201,
    )
    assert first_answer["round_number"] == 1
    assert first_answer["position"] == "DISPUTE"
    assert read_criticism(criticism_id)["status"] == "RESPONDED"

    rebutted = validate_success(
        api_client.rebut_criticism(
            criticism_id,
            rebuttal_payload(
                rebuttal_note="The department maintains the finding and rejects the carrier position."
            ),
            EIC,
        )
    )
    assert rebutted["status"] == "ISSUED"
    assert rebutted["rebuttal_count"] == 1
    assert rebutted["response_round"] == 1, "the two counters move on different schedules"

    validate_error(
        api_client.rebut_criticism(
            criticism_id,
            rebuttal_payload(
                rebuttal_note="The department rebuts twice in a row without an intervening answer."
            ),
            EIC,
        ),
        ApiErrorId.ERR_CRITICISM_STATE_INVALID.value,
    )
    validate_error(
        api_client.finalize_criticism(
            criticism_id,
            criticism_finalize_payload(
                "WITHDRAWN",
                None,
                disposition_note="The department withdraws while its own rebuttal is outstanding.",
            ),
            SUPERVISOR,
        ),
        ApiErrorId.ERR_CRITICISM_STATE_INVALID.value,
    )

    second_answer = validate_success(
        api_client.create_company_response(
            criticism_id,
            company_response_payload(
                "PARTIAL_CONCUR",
                narrative=(
                    "The carrier concurs on two files and continues to dispute "
                    "the extrapolation."
                ),
                remediation_offer_cents=9_000,
            ),
            scenario["respondent_headers"],
        ),
        201,
    )
    assert second_answer["round_number"] == 2
    assert second_answer["remediation_offer_cents"] == 9_000

    reread = read_criticism(criticism_id)
    assert reread["status"] == "RESPONDED"
    assert reread["response_round"] == 2
    assert reread["rebuttal_count"] == 1

    finalized = validate_success(
        api_client.finalize_criticism(
            criticism_id, criticism_finalize_payload("SUSTAINED", 20), SUPERVISOR_B
        )
    )
    assert finalized["status"] == "SUSTAINED"


def test_parent_scoped_collections_never_leak_across_parents():
    """Nested collections are keyed on the path parent, not on a repeated field value.

    PRD §2.7: "An `Examination` sits at the head of a hierarchy: scope areas hang off it, data calls hang off scope areas, file samples hang off accepted data calls, and criticisms, workpapers, corrective action plans, consent orders and the multistate collaboration all hang off the examination directly."
    PRD §3.3: "The `area` value is one of `UNDERWRITING`, `RATING`, `CLAIMS` or `PRODUCER`, and at most one area of each value may exist on one examination — a repeat is `ERR_DUPLICATE_IDENTIFIER`."
    PRD §3.9: "At most one collaboration may exist per examination; a second attempt is `ERR_DUPLICATE_IDENTIFIER`."

    Design: Corner/endpoints/parent_scoped_collections_never_leak_across_parents
    """
    first_insurer = register_insurer(
        name="Aurora Mutual Insurance Company", naic_code="10001"
    )
    second_insurer = register_insurer(
        name="Boreal Casualty Company", naic_code="10002"
    )
    first_exam = open_examination(first_insurer["id"])
    second_exam = open_examination(second_insurer["id"])

    first_claims = add_scope_area(
        first_exam["id"],
        "CLAIMS",
        population_size=CLAIMS_POPULATION,
        sample_size=CLAIMS_SAMPLE,
    )
    first_rating = add_scope_area(
        first_exam["id"],
        "RATING",
        population_size=RATING_POPULATION,
        sample_size=RATING_SAMPLE,
    )
    second_claims = add_scope_area(
        second_exam["id"],
        "CLAIMS",
        population_size=CLAIMS_POPULATION,
        sample_size=CLAIMS_SAMPLE,
    )
    lock_scope(first_exam["id"])
    lock_scope(second_exam["id"])

    first_call = issue_data_call(
        first_claims["id"], records_requested=CLAIMS_POPULATION
    )
    issue_data_call(second_claims["id"], records_requested=CLAIMS_POPULATION)

    collaboration = validate_success(
        api_client.open_collaboration(
            first_exam["id"],
            collaboration_payload(
                [
                    {
                        "state_code": "NV",
                        "policy_count_in_state": 40_000,
                        "has_examiner_resources": True,
                    },
                    {
                        "state_code": "AZ",
                        "policy_count_in_state": 25_000,
                        "has_examiner_resources": True,
                    },
                    {
                        "state_code": "UT",
                        "policy_count_in_state": 9_000,
                        "has_examiner_resources": False,
                    },
                ],
                call_reference="NAIC-CAWG-2026-0301",
            ),
            COORDINATOR,
        ),
        201,
    )

    first_areas, meta = validate_paginated(
        api_client.list_scope_areas(first_exam["id"], EIC)
    )
    assert meta["total_count"] == 2
    assert {row["id"] for row in first_areas} == {first_claims["id"], first_rating["id"]}
    for row in first_areas:
        assert row["exam_id"] == first_exam["id"]

    second_areas, meta = validate_paginated(
        api_client.list_scope_areas(second_exam["id"], EIC)
    )
    assert meta["total_count"] == 1, (
        "the second examination's single area shares the CLAIMS value with the first"
    )
    assert second_areas[0]["id"] == second_claims["id"]
    assert second_areas[0]["exam_id"] == second_exam["id"]

    claims_calls, meta = validate_paginated(
        api_client.list_scope_area_data_calls(first_claims["id"], EIC)
    )
    assert meta["total_count"] == 1
    assert claims_calls[0]["id"] == first_call["id"]
    assert claims_calls[0]["scope_area_id"] == first_claims["id"]
    assert claims_calls[0]["response_due_date"] == "2026-09-15"

    rating_calls, meta = validate_paginated(
        api_client.list_scope_area_data_calls(first_rating["id"], EIC)
    )
    assert meta["total_count"] == 0, "the sibling area's data call does not leak across"
    assert rating_calls == []

    first_collabs, meta = validate_paginated(
        api_client.list_collaborations(first_exam["id"], COORDINATOR)
    )
    assert meta["total_count"] == 1
    assert first_collabs[0]["id"] == collaboration["id"]
    assert first_collabs[0]["exam_id"] == first_exam["id"]

    second_collabs, meta = validate_paginated(
        api_client.list_collaborations(second_exam["id"], COORDINATOR)
    )
    assert meta["total_count"] == 0
    assert second_collabs == []
