"""Rejection-band ordering on paired failures, and the inclusive-boundary arithmetic.

Two families of behaviour are exercised here.  The first pins the order of
rejection when two independent checks are live in one request: the earlier band
must answer, and the later rule must still be reachable once the earlier one is
cleared.  The second pins the comparisons that sit exactly on their stated
boundary — an error rate equal to its tolerance, an effective completeness of
exactly 95.00, a composite score exactly equal to the selection threshold — and
the degenerate zero-denominator input.
"""

from test_helpers import (
    ANALYST,
    EIC,
    SUPERVISOR,
    ApiErrorId,
    api_client as api,
    bulk_review,
    build_reviews,
    consent_order_payload,
    create_analysis_cycle,
    criticism_payload,
    data_call_response_payload,
    disposition_payload,
    issue_criticism,
    issue_data_call,
    make_insurer_respondent_headers,
    propose_plan,
    read_cycle,
    read_cycle_scores,
    read_data_call,
    read_examination,
    read_file_samples,
    read_insurer,
    read_scope_area,
    record_standard_workpapers,
    register_insurer,
    respond_to_data_call,
    review_file_sample,
    review_plan,
    score_cycle,
    select_targets,
    set_clock,
    setup_examination_in_negotiation,
    setup_locked_examination,
    systematic_file_references,
    validate_error,
    validate_paginated,
    validate_success,
)

# ─── Local compositions ───────────────────────────────────────────────────
#
# Each of these builds the exact precondition one instance needs out of the
# primitives the PRD declares; every test starts from an empty database.


def _setup_responded_claims_call_beside_issued_rating_call():
    """One CLAIMS call already RESPONDED, one RATING call still ISSUED."""
    scenario = setup_locked_examination(
        areas=(("CLAIMS", 4000, 10), ("RATING", 500, 10)),
    )
    claims_call = issue_data_call(
        scenario["scope_areas"]["CLAIMS"]["id"],
        records_requested=4000,
        response_due_date="2026-09-15",
    )
    rating_call = issue_data_call(
        scenario["scope_areas"]["RATING"]["id"],
        records_requested=500,
        response_due_date="2026-09-15",
    )
    respond_to_data_call(
        claims_call["id"], scenario["insurer_id"], records_received=4000
    )
    scenario["claims_data_call_id"] = claims_call["id"]
    scenario["rating_data_call_id"] = rating_call["id"]
    return scenario


def _setup_partially_reviewed_claims_area():
    """A CLAIMS area left in FIELDWORK with nine of ten samples reviewed."""
    scenario = setup_locked_examination(areas=(("CLAIMS", 4000, 10),))
    data_call = issue_data_call(
        scenario["scope_area_id"],
        records_requested=4000,
        response_due_date="2026-09-15",
    )
    respond_to_data_call(data_call["id"], scenario["insurer_id"], records_received=4000)
    api_response = api.disposition_data_call(
        data_call["id"], disposition_payload("ACCEPTED"), EIC
    )
    validate_success(api_response)
    record_standard_workpapers(scenario["exam_id"], "CLAIMS")
    references = systematic_file_references("CLAIMS", 4000, 10)
    bulk_result = bulk_review(
        data_call["id"], build_reviews(references, leave_unreviewed=1)
    )
    scenario["data_call_id"] = data_call["id"]
    scenario["file_references"] = references
    scenario["bulk_result"] = bulk_result
    return scenario


def _setup_two_areas_with_neighbouring_tolerances():
    """CLAIMS at tolerance 30.00 beside UNDERWRITING at tolerance 30.01."""
    scenario = setup_locked_examination(
        areas=(("CLAIMS", 4000, 10), ("UNDERWRITING", 4000, 10)),
        area_overrides={
            "CLAIMS": {"error_tolerance_pct": 30.00},
            "UNDERWRITING": {"error_tolerance_pct": 30.01},
        },
    )
    for area in ("CLAIMS", "UNDERWRITING"):
        data_call = issue_data_call(
            scenario["scope_areas"][area]["id"],
            records_requested=4000,
            response_due_date="2026-09-15",
        )
        respond_to_data_call(
            data_call["id"], scenario["insurer_id"], records_received=4000
        )
        validate_success(
            api.disposition_data_call(
                data_call["id"], disposition_payload("ACCEPTED"), EIC
            )
        )
        scenario[f"{area}_data_call_id"] = data_call["id"]
    record_standard_workpapers(scenario["exam_id"], "CLAIMS")
    return scenario


def _review_both_areas_identically(scenario):
    """Three MATERIAL files and seven clean ones in each of the two areas."""
    results = {}
    for area in ("CLAIMS", "UNDERWRITING"):
        references = systematic_file_references(area, 4000, 10)
        results[area] = bulk_review(
            scenario[f"{area}_data_call_id"], build_reviews(references)
        )
    return results


def _setup_two_areas_awaiting_production():
    """Two areas, one data call each, both still ISSUED and both due 2026-09-15."""
    scenario = setup_locked_examination(
        areas=(("CLAIMS", 4000, 10), ("UNDERWRITING", 4000, 10)),
    )
    for area in ("CLAIMS", "UNDERWRITING"):
        data_call = issue_data_call(
            scenario["scope_areas"][area]["id"],
            records_requested=4000,
            response_due_date="2026-09-15",
        )
        scenario[f"{area}_data_call_id"] = data_call["id"]
    return scenario


def _register_zero_policy_carrier():
    return register_insurer(
        name="Zero Point Assurance Company",
        naic_code="10009",
        annual_premium_written_cents=100_000_000,
        policy_count_in_force=0,
        confirmed_complaints_12mo=7,
        financial_stress_score=20,
        consumer_trend_score=10,
    )


def _register_cedar_carrier():
    return register_insurer(
        name="Cedar Ridge Mutual Insurance Company",
        naic_code="10003",
        annual_premium_written_cents=800_000_000,
        policy_count_in_force=30_000,
        confirmed_complaints_12mo=60,
        financial_stress_score=40,
        consumer_trend_score=30,
    )


def _score_row_for(scores, insurer_id):
    matches = [row for row in scores if row["insurer_id"] == insurer_id]
    assert len(matches) == 1, "the scoring pass writes one AnalysisScore per carrier"
    return matches[0]


# ─── priority_pair_validation_conflict ────────────────────────────────────


class TestDataCallRespondStateBeatsRecordCountConstraint:
    def test_already_responded_call_answers_with_the_state_error(self):
        """The lifecycle band answers before the numeric-constraint band.

        PRD §2.11: "Checks are evaluated in the following bands, in this order, and the first band that produces a rejection determines the response:"
        PRD §2.11: "8. **Lifecycle state** — `ERR_CYCLE_STATE_INVALID`, `ERR_EXAM_NOT_IN_SCOPING`, `ERR_SCOPE_NOT_LOCKED`, `ERR_DATA_CALL_NOT_AWAITING_RESPONSE`, `ERR_DATA_CALL_NOT_RESPONDED`, `ERR_SAMPLE_ALREADY_REVIEWED`, `ERR_EXAM_NOT_IN_CRITICISM_PHASE`, `ERR_CRITICISM_STATE_INVALID`, `ERR_EXAM_NOT_IN_NEGOTIATION`, `ERR_ENFORCEMENT_RECORD_STATE_INVALID`, `ERR_EXAM_NOT_READY_FOR_PUBLICATION` and `ERR_EXAM_ALREADY_TERMINAL`."
        PRD §2.11: "13. **Numeric constraints**, in this internal order — `ERR_RECORDS_EXCEED_REQUEST` and `ERR_SAMPLE_EXCEEDS_POPULATION` together, then `ERR_AFFECTED_FILES_EXCEED_ERRORS`, then `ERR_RESPONSE_INCOMPLETE`, then `ERR_CYCLE_SLOTS_EXHAUSTED`."
        PRD §3.4: "A call in any other state is rejected with `ERR_DATA_CALL_NOT_AWAITING_RESPONSE`; the owning examination must be in `DATA_CALL` or `FIELDWORK`; and the acting `X-User-ID` must equal the examination's `insurer_id` or the request is rejected with `ERR_NOT_EXAM_SUBJECT`."

        Design: Difficulty/priority_pair_validation_conflict/state_priority_40_beats_constraint_priority_65_on_data_call_respond
        """
        scenario = _setup_responded_claims_call_beside_issued_rating_call()
        respondent = make_insurer_respondent_headers(scenario["insurer_id"])

        response = api.respond_to_data_call(
            scenario["claims_data_call_id"],
            data_call_response_payload(records_received=9999),
            respondent,
        )
        validate_error(response, ApiErrorId.ERR_DATA_CALL_NOT_AWAITING_RESPONSE.value)

        call = read_data_call(scenario["claims_data_call_id"])
        assert call["status"] == "RESPONDED"
        assert call["records_received"] == 4000
        assert read_examination(scenario["exam_id"])["status"] == "DATA_CALL"

    def test_oversized_production_on_an_issued_call_trips_the_constraint(self):
        """The outranked numeric rule still fires on a call awaiting production.

        PRD §3.4: "`records_received` may not exceed the call's `records_requested`; an excess is rejected with `ERR_RECORDS_EXCEED_REQUEST`."
        PRD §2.11: "13. **Numeric constraints**, in this internal order — `ERR_RECORDS_EXCEED_REQUEST` and `ERR_SAMPLE_EXCEEDS_POPULATION` together, then `ERR_AFFECTED_FILES_EXCEED_ERRORS`, then `ERR_RESPONSE_INCOMPLETE`, then `ERR_CYCLE_SLOTS_EXHAUSTED`."

        Design: Difficulty/priority_pair_validation_conflict/state_priority_40_beats_constraint_priority_65_on_data_call_respond
        """
        scenario = _setup_responded_claims_call_beside_issued_rating_call()
        respondent = make_insurer_respondent_headers(scenario["insurer_id"])

        response = api.respond_to_data_call(
            scenario["rating_data_call_id"],
            data_call_response_payload(records_received=9999),
            respondent,
        )
        validate_error(response, ApiErrorId.ERR_RECORDS_EXCEED_REQUEST.value)

        call = read_data_call(scenario["rating_data_call_id"])
        assert call["status"] == "ISSUED"
        assert call["records_received"] == 0
        assert read_examination(scenario["exam_id"])["status"] == "DATA_CALL"


class TestConsentOrderReferentialBeatsFiscalCeiling:
    def test_missing_approved_plan_answers_before_the_penalty_cap(self):
        """The referential band answers before the fiscal-ceiling band.

        PRD §2.11: "12. **Referential prerequisites**, in this internal order — `ERR_CAP_NOT_APPROVED`, then `ERR_ORDER_NOT_EXECUTED`, then `ERR_NO_TOLERANCE_BREACH`, then `ERR_NO_ELIGIBLE_LEAD_STATE`."
        PRD §2.11: "14. **Fiscal ceilings**, in this internal order — `ERR_PENALTY_CAP_EXCEEDED`, then `ERR_RESTITUTION_NOT_CONSERVED`."
        PRD §3.8: "The examination's `status` must be `NEGOTIATION` or `ORDER_PENDING`, otherwise `ERR_EXAM_NOT_IN_NEGOTIATION`, and the examination must already hold a corrective action plan in `APPROVED`, otherwise `ERR_CAP_NOT_APPROVED`."

        Design: Difficulty/priority_pair_validation_conflict/referential_priority_60_beats_fiscal_priority_70_on_consent_order_draft
        """
        scenario = setup_examination_in_negotiation(
            criticism_severity="MATERIAL",
            affected_file_count=3,
            penalty_units=2001,
            harm_cents=(30_000, 20_000, 10_000),
        )
        examination = read_examination(scenario["exam_id"])
        assert examination["status"] == "NEGOTIATION"
        assert examination["aggregate_restitution_cents"] == 24000000
        assert examination["penalty_units_total"] == 2001

        response = api.draft_consent_order(
            scenario["exam_id"],
            consent_order_payload(
                examination["version"], "MC-2026-0002", "PER_VIOLATION"
            ),
            SUPERVISOR,
        )
        validate_error(response, ApiErrorId.ERR_CAP_NOT_APPROVED.value)

        orders, meta = validate_paginated(
            api.list_consent_orders(scenario["exam_id"], SUPERVISOR)
        )
        assert meta["total_count"] == 0
        assert orders == []

    def test_penalty_cap_surfaces_once_the_plan_is_approved(self):
        """With the prerequisite cleared the identical draft trips the statutory ceiling.

        PRD §3.8: "The **per-violation** algorithm ignores restitution size entirely: the gross penalty is the examination's `penalty_units_total` multiplied by 25,000 cents (250 dollars per statutory violation unit)."
        PRD §3.8: "Whichever variant the department elects, the gross figure is stored as `penalty_gross_cents`, and if it exceeds 50,000,000 cents the draft is rejected outright with `ERR_PENALTY_CAP_EXCEEDED` at HTTP 422 — the statutory ceiling is never silently applied as a clamp, and the department must elect the other variant instead."
        PRD §3.8: "`APPROVE` moves the plan to `APPROVED` and cascades: the examination advances `NEGOTIATION → ORDER_PENDING` and its `version` is incremented by 1."

        Design: Difficulty/priority_pair_validation_conflict/referential_priority_60_beats_fiscal_priority_70_on_consent_order_draft
        """
        scenario = setup_examination_in_negotiation(
            criticism_severity="MATERIAL",
            affected_file_count=3,
            penalty_units=2001,
            harm_cents=(30_000, 20_000, 10_000),
        )
        plan = propose_plan(scenario["exam_id"], scenario["insurer_id"])
        plan = review_plan(plan["id"], "APPROVE")
        assert plan["status"] == "APPROVED"

        examination = read_examination(scenario["exam_id"])
        assert examination["status"] == "ORDER_PENDING"

        response = api.draft_consent_order(
            scenario["exam_id"],
            consent_order_payload(
                examination["version"], "MC-2026-0002", "PER_VIOLATION"
            ),
            SUPERVISOR,
        )
        validate_error(response, ApiErrorId.ERR_PENALTY_CAP_EXCEEDED.value)

        orders, meta = validate_paginated(
            api.list_consent_orders(scenario["exam_id"], SUPERVISOR)
        )
        assert meta["total_count"] == 0
        assert orders == []
        assert read_examination(scenario["exam_id"])["status"] == "ORDER_PENDING"

    def test_order_number_survives_the_capped_draft_for_the_other_variant(self):
        """A draft rejected on the ceiling persists nothing, so its order number is still free.

        PRD §3.8: "Whichever variant the department elects, the gross figure is stored as `penalty_gross_cents`, and if it exceeds 50,000,000 cents the draft is rejected outright with `ERR_PENALTY_CAP_EXCEEDED` at HTTP 422 — the statutory ceiling is never silently applied as a clamp, and the department must elect the other variant instead."
        PRD §3.8: "The `SupervisingExaminer` drafts a consent order on the examination, supplying the `expected_examination_version` pin, an `order_number` unique across all consent orders (a collision is `ERR_DUPLICATE_IDENTIFIER`), and a `penalty_variant` of either `PER_VIOLATION` or `TIERED_AGGREGATE`."

        Design: Difficulty/priority_pair_validation_conflict/referential_priority_60_beats_fiscal_priority_70_on_consent_order_draft
        """
        scenario = setup_examination_in_negotiation(
            criticism_severity="MATERIAL",
            affected_file_count=3,
            penalty_units=2001,
            harm_cents=(30_000, 20_000, 10_000),
        )
        plan = propose_plan(scenario["exam_id"], scenario["insurer_id"])
        review_plan(plan["id"], "APPROVE")

        examination = read_examination(scenario["exam_id"])
        validate_error(
            api.draft_consent_order(
                scenario["exam_id"],
                consent_order_payload(
                    examination["version"], "MC-2026-0002", "PER_VIOLATION"
                ),
                SUPERVISOR,
            ),
            ApiErrorId.ERR_PENALTY_CAP_EXCEEDED.value,
        )

        examination = read_examination(scenario["exam_id"])
        order = validate_success(
            api.draft_consent_order(
                scenario["exam_id"],
                consent_order_payload(
                    examination["version"], "MC-2026-0002", "TIERED_AGGREGATE"
                ),
                SUPERVISOR,
            ),
            201,
        )
        assert order["order_number"] == "MC-2026-0002"
        assert order["status"] == "DRAFT"
        assert order["penalty_variant"] == "TIERED_AGGREGATE"


class TestCriticismSafetyBeatsAffectedFileConstraint:
    def test_untested_area_answers_before_the_affected_file_count(self):
        """The business-safety band answers before the numeric-constraint band.

        PRD §3.6: "Five business gates guard the issuance and, per §2.11, they are evaluated in this order."
        PRD §3.6: "The referenced scope area's `status` must be `TESTED` — still `PLANNED`, still in `FIELDWORK`, or already `CLOSED` all fail with `ERR_SCOPE_AREA_NOT_TESTED`."
        PRD §3.6: "And `affected_file_count` must be at least 1 and no greater than the referenced area's `error_count`; an excess is `ERR_AFFECTED_FILES_EXCEED_ERRORS`."
        PRD §2.11: "10. **Business safety**, in this internal order — `ERR_INSURER_NOT_EXAMINABLE`, then `ERR_SCOPE_AREA_NOT_TESTED`, then `ERR_FIELDWORK_NOT_DOCUMENTED`, then `ERR_SAMPLE_SIZE_BELOW_MINIMUM`, then `ERR_REBUTTAL_ROUNDS_EXHAUSTED`."

        Design: Difficulty/priority_pair_validation_conflict/safety_priority_51_beats_constraint_priority_66_on_criticism_issuance
        """
        scenario = _setup_partially_reviewed_claims_area()
        bulk_result = scenario["bulk_result"]
        assert bulk_result["scope_area_status"] == "FIELDWORK"
        assert bulk_result["error_count"] == 3
        assert bulk_result["error_rate_pct"] == 33.33
        assert bulk_result["tolerance_breached"] is True

        response = api.issue_criticism(
            criticism_payload(
                scenario["exam_id"],
                scenario["scope_area_id"],
                "MATERIAL",
                5,
            ),
            EIC,
        )
        validate_error(response, ApiErrorId.ERR_SCOPE_AREA_NOT_TESTED.value)

        criticisms, meta = validate_paginated(
            api.list_criticisms(EIC, {"exam_id": scenario["exam_id"]})
        )
        assert meta["total_count"] == 0
        assert criticisms == []
        assert read_examination(scenario["exam_id"])["open_criticism_count"] == 0

    def test_closing_review_flips_the_state_gate_and_exposes_the_constraint(self):
        """One clean closing review makes the area TESTED without moving error_count.

        PRD §3.5: "When the last `UNREVIEWED` file of an area is reviewed, whether by a single review or as part of a bulk batch, the area advances `FIELDWORK → TESTED` and cascades in two further hops."
        PRD §3.5: "`error_rate_pct` is `error_count` multiplied by one hundred and divided by `reviewed_sample_count`, rounded half up to two decimals, or 0.00 when nothing has been reviewed; `material_error_rate_pct` is the same computation over `material_error_count`."
        PRD §3.6: "And `affected_file_count` must be at least 1 and no greater than the referenced area's `error_count`; an excess is `ERR_AFFECTED_FILES_EXCEED_ERRORS`."

        Design: Difficulty/priority_pair_validation_conflict/safety_priority_51_beats_constraint_priority_66_on_criticism_issuance
        """
        scenario = _setup_partially_reviewed_claims_area()

        samples = read_file_samples(scenario["data_call_id"], {"limit": 100})
        unreviewed = [s for s in samples if s["review_status"] == "UNREVIEWED"]
        assert len(unreviewed) == 1
        assert unreviewed[0]["file_reference"] == "CLM-003601"
        review_file_sample(unreviewed[0]["id"], "NONE")

        area = read_scope_area(scenario["scope_area_id"])
        assert area["status"] == "TESTED"
        assert area["error_count"] == 3
        assert area["error_rate_pct"] == 30.00
        assert read_examination(scenario["exam_id"])["status"] == "CRITICISM"

        response = api.issue_criticism(
            criticism_payload(
                scenario["exam_id"],
                scenario["scope_area_id"],
                "MATERIAL",
                5,
            ),
            EIC,
        )
        validate_error(response, ApiErrorId.ERR_AFFECTED_FILES_EXCEED_ERRORS.value)

        _, meta = validate_paginated(
            api.list_criticisms(EIC, {"exam_id": scenario["exam_id"]})
        )
        assert meta["total_count"] == 0
        assert read_examination(scenario["exam_id"])["open_criticism_count"] == 0


# ─── boundary_precision_check ─────────────────────────────────────────────


class TestToleranceBreachAtExactEquality:
    def test_equal_rate_breaches_while_one_hundredth_more_does_not(self):
        """Identical rates of 30.00 breach a 30.00 tolerance but not a 30.01 one.

        PRD §3.5: "`tolerance_breached` is true when `error_rate_pct` is greater than or equal to the area's own `error_tolerance_pct`; an error rate exactly equal to the tolerance breaches it."
        PRD §3.5: "`escalation_required` is true when `material_error_rate_pct` is greater than or equal to 10.00 percent; again exact equality escalates."
        PRD §3.5: "Second, when **every** scope area of the examination has reached `TESTED`, the examination bubbles up `FIELDWORK → CRITICISM`, stamps `criticism_phase_opened_at` from the logical clock and increments its `version` by 1 — and that examination transition in turn advances any multistate collaboration on the examination that is still in `LEAD_ASSIGNED` to `ACTIVE`, incrementing the collaboration's `version` by 1."

        Design: Difficulty/boundary_precision_check/tolerance_breach_at_exact_error_rate_equality
        """
        scenario = _setup_two_areas_with_neighbouring_tolerances()
        _review_both_areas_identically(scenario)

        claims = read_scope_area(scenario["scope_areas"]["CLAIMS"]["id"])
        underwriting = read_scope_area(scenario["scope_areas"]["UNDERWRITING"]["id"])

        for area in (claims, underwriting):
            assert area["error_rate_pct"] == 30.00
            assert area["material_error_rate_pct"] == 30.00
            assert area["escalation_required"] is True
            assert area["status"] == "TESTED"

        assert claims["error_tolerance_pct"] == 30.00
        assert claims["tolerance_breached"] is True
        assert underwriting["error_tolerance_pct"] == 30.01
        assert underwriting["tolerance_breached"] is False

        assert read_examination(scenario["exam_id"])["status"] == "CRITICISM"

    def test_egregious_criticism_refused_on_the_within_tolerance_area(self):
        """A hundredth of a point of head-room blocks the EGREGIOUS finding.

        PRD §3.6: "An `EGREGIOUS` criticism must rest on an area whose `tolerance_breached` is true; issuing one against a within-tolerance area is rejected with `ERR_NO_TOLERANCE_BREACH` at HTTP 422."
        PRD §3.5: "`tolerance_breached` is true when `error_rate_pct` is greater than or equal to the area's own `error_tolerance_pct`; an error rate exactly equal to the tolerance breaches it."

        Design: Difficulty/boundary_precision_check/tolerance_breach_at_exact_error_rate_equality
        """
        scenario = _setup_two_areas_with_neighbouring_tolerances()
        _review_both_areas_identically(scenario)

        response = api.issue_criticism(
            criticism_payload(
                scenario["exam_id"],
                scenario["scope_areas"]["UNDERWRITING"]["id"],
                "EGREGIOUS",
                3,
                statute_citation="NRS 686A.310(1)(a)",
            ),
            EIC,
        )
        validate_error(response, ApiErrorId.ERR_NO_TOLERANCE_BREACH.value)

        _, meta = validate_paginated(
            api.list_criticisms(EIC, {"exam_id": scenario["exam_id"]})
        )
        assert meta["total_count"] == 0
        assert read_examination(scenario["exam_id"])["open_criticism_count"] == 0

    def test_egregious_criticism_on_the_breached_area_extrapolates_exposure(self):
        """The area whose rate exactly equals its tolerance carries the EGREGIOUS finding.

        PRD §3.6: "The method is `POPULATION_EXTRAPOLATED` when the `severity` is `EGREGIOUS`, or when the `severity` is `MATERIAL` **and** the area's `tolerance_breached` is true."
        PRD §3.6: "Under `POPULATION_EXTRAPOLATED`, the summed underpayment is first divided by the reviewed-sample count and **that per-file average is rounded half up to a whole cent**, and only then is the rounded average multiplied by the area's `population_size` to give `restitution_exposure_cents`."
        PRD §3.6: "A new criticism opens in `ISSUED` with `response_round` 0 and `rebuttal_count` 0, records the acting `X-User-ID` as `issued_by_user_id` for the later segregation-of-duties comparison, raises the examination's `open_criticism_count` by 1 and its `pending_restitution_cents` by the frozen `restitution_exposure_cents`, and increments the examination's `version` by 1."

        Design: Difficulty/boundary_precision_check/tolerance_breach_at_exact_error_rate_equality
        """
        scenario = _setup_two_areas_with_neighbouring_tolerances()
        _review_both_areas_identically(scenario)

        criticism = issue_criticism(
            scenario["exam_id"],
            scenario["scope_areas"]["CLAIMS"]["id"],
            "EGREGIOUS",
            3,
            statute_citation="NRS 686A.310(1)(a)",
        )
        assert criticism["restitution_method"] == "POPULATION_EXTRAPOLATED"
        assert criticism["restitution_exposure_cents"] == 20132000

        examination = read_examination(scenario["exam_id"])
        assert examination["open_criticism_count"] == 1
        assert examination["pending_restitution_cents"] == 20132000


class TestEffectiveCompletenessAcceptanceBoundary:
    def test_forward_clock_sweeps_issued_calls_once_only(self):
        """The sweep touches calls still in ISSUED, so a second move re-flags nothing.

        PRD §3.4: "When the logical clock is moved forward, every data call still in `ISSUED` whose `response_due_date` now lies before the new clock date is swept `ISSUED → OVERDUE`, each such call's `version` being incremented by 1, and the count of swept calls is returned as `data_calls_flagged_overdue`."

        Design: Difficulty/boundary_precision_check/data_call_acceptance_at_exact_effective_completeness_boundary
        """
        scenario = _setup_two_areas_awaiting_production()

        first = set_clock("2026-09-25T09:00:00Z", EIC)
        assert first["data_calls_flagged_overdue"] == 2
        for area in ("CLAIMS", "UNDERWRITING"):
            assert read_data_call(scenario[f"{area}_data_call_id"])["status"] == "OVERDUE"

        second = set_clock("2026-09-26T09:00:00Z", EIC)
        assert second["data_calls_flagged_overdue"] == 0
        for area in ("CLAIMS", "UNDERWRITING"):
            assert read_data_call(scenario[f"{area}_data_call_id"])["status"] == "OVERDUE"

    def test_exactly_95_effective_completeness_is_accepted(self):
        """Ten days late on a full production lands exactly on the acceptance floor.

        PRD §3.4: "`days_late` is the whole-day difference from `response_due_date` to the response date, floored at zero — a response on or before the due date yields 0 — and `is_late` is true exactly when `days_late` is 1 or more."
        PRD §3.4: "`completeness_pct` is `records_received` multiplied by one hundred and divided by `records_requested`, rounded half up to two decimals. The lateness penalty is then applied to that **already-rounded** figure: half a percentage point is deducted for each day late, the result is rounded half up to two decimals again, and the outcome is floored at 0.00 before being stored as `effective_completeness_pct`."
        PRD §3.4: "Accepting requires that `effective_completeness_pct` be at least 95.00; below that figure the acceptance is rejected with `ERR_RESPONSE_INCOMPLETE`, and a value of exactly 95.00 is accepted."
        PRD §3.5: "The draw interval is the population size divided by the sample size, discarding any fractional part, and is stored on the call as `sample_draw_interval`; because `sample_size` never exceeds `population_size`, the interval is always 1 or more."

        Design: Difficulty/boundary_precision_check/data_call_acceptance_at_exact_effective_completeness_boundary
        """
        scenario = _setup_two_areas_awaiting_production()
        set_clock("2026-09-25T09:00:00Z", EIC)

        produced = respond_to_data_call(
            scenario["CLAIMS_data_call_id"],
            scenario["insurer_id"],
            records_received=4000,
        )
        assert produced["is_late"] is True
        assert produced["days_late"] == 10
        assert produced["completeness_pct"] == 100.00
        assert produced["effective_completeness_pct"] == 95.00

        accepted = validate_success(
            api.disposition_data_call(
                scenario["CLAIMS_data_call_id"],
                disposition_payload(
                    "ACCEPTED",
                    disposition_reason=(
                        "Late but complete; effective completeness meets the "
                        "statutory floor."
                    ),
                ),
                EIC,
            )
        )
        assert accepted["status"] == "ACCEPTED"
        assert accepted["sample_draw_interval"] == 400
        assert accepted["samples_drawn_count"] == 10

        assert (
            read_scope_area(scenario["scope_areas"]["CLAIMS"]["id"])["status"]
            == "FIELDWORK"
        )
        examination = read_examination(scenario["exam_id"])
        assert examination["status"] == "FIELDWORK"
        assert examination["rejected_data_call_count"] == 0

    def test_one_further_day_late_falls_to_94_50_and_is_refused(self):
        """Eleven days late puts the same full production below the floor.

        PRD §3.4: "The lateness penalty is then applied to that **already-rounded** figure: half a percentage point is deducted for each day late, the result is rounded half up to two decimals again, and the outcome is floored at 0.00 before being stored as `effective_completeness_pct`."
        PRD §3.4: "Accepting requires that `effective_completeness_pct` be at least 95.00; below that figure the acceptance is rejected with `ERR_RESPONSE_INCOMPLETE`, and a value of exactly 95.00 is accepted."

        Design: Difficulty/boundary_precision_check/data_call_acceptance_at_exact_effective_completeness_boundary
        """
        scenario = _setup_two_areas_awaiting_production()
        set_clock("2026-09-25T09:00:00Z", EIC)
        respond_to_data_call(
            scenario["CLAIMS_data_call_id"],
            scenario["insurer_id"],
            records_received=4000,
        )
        validate_success(
            api.disposition_data_call(
                scenario["CLAIMS_data_call_id"], disposition_payload("ACCEPTED"), EIC
            )
        )

        set_clock("2026-09-26T09:00:00Z", EIC)
        produced = respond_to_data_call(
            scenario["UNDERWRITING_data_call_id"],
            scenario["insurer_id"],
            records_received=4000,
        )
        assert produced["days_late"] == 11
        assert produced["completeness_pct"] == 100.00
        assert produced["effective_completeness_pct"] == 94.50

        response = api.disposition_data_call(
            scenario["UNDERWRITING_data_call_id"],
            disposition_payload(
                "ACCEPTED",
                disposition_reason="Attempted acceptance of a production one day later.",
            ),
            EIC,
        )
        validate_error(response, ApiErrorId.ERR_RESPONSE_INCOMPLETE.value)

        refused = read_data_call(scenario["UNDERWRITING_data_call_id"])
        assert refused["status"] == "RESPONDED"
        assert refused["samples_drawn_count"] == 0
        _, meta = validate_paginated(
            api.list_file_samples(scenario["UNDERWRITING_data_call_id"], EIC)
        )
        assert meta["total_count"] == 0

        assert (
            read_scope_area(scenario["scope_areas"]["UNDERWRITING"]["id"])["status"]
            == "PLANNED"
        )
        assert (
            read_scope_area(scenario["scope_areas"]["CLAIMS"]["id"])["status"]
            == "FIELDWORK"
        )
        examination = read_examination(scenario["exam_id"])
        assert examination["status"] == "FIELDWORK"
        assert examination["rejected_data_call_count"] == 0


class TestZeroPolicyCountCarrier:
    def test_zero_policies_in_force_yields_unrated_tier_and_zero_ratio(self):
        """A carrier with no policies in force registers rather than dividing by zero.

        PRD §3.1: "A carrier with no policies in force is not a division error: when `policy_count_in_force` is zero, `complaint_ratio_per_1k` is set to 0.00 and `risk_tier` is set to `UNRATED`, and nothing further is computed."
        PRD §4: "Operations that create a new stand-alone record, or add a new distinct record to a collection — registering a carrier, opening a cycle, opening an examination, adding a scope area, issuing a data call, recording a workpaper, issuing a criticism, filing a company response, proposing a plan, drafting an order, opening a collaboration — return `201 Created`."

        Design: Difficulty/boundary_precision_check/zero_policy_count_yields_unrated_tier_and_zero_complaint_ratio
        """
        response = api.register_insurer(
            {
                "name": "Zero Point Assurance Company",
                "naic_code": "10009",
                "annual_premium_written_cents": 100_000_000,
                "policy_count_in_force": 0,
                "confirmed_complaints_12mo": 7,
                "financial_stress_score": 20,
                "consumer_trend_score": 10,
            },
            ANALYST,
        )
        carrier = validate_success(response, 201)
        assert carrier["policy_count_in_force"] == 0
        assert carrier["confirmed_complaints_12mo"] == 7
        assert carrier["complaint_ratio_per_1k"] == 0.00
        assert carrier["risk_tier"] == "UNRATED"

        stored = read_insurer(carrier["id"])
        assert stored["complaint_ratio_per_1k"] == 0.00
        assert stored["risk_tier"] == "UNRATED"

    def test_zero_policy_carrier_is_still_scored_from_its_other_components(self):
        """The degenerate ratio snapshots as 0.00 and the composite comes out at 14.00.

        PRD §3.2: "The pass writes one `AnalysisScore` per scored carrier, each recording its `cycle_id` and `insurer_id` and snapshotting the carrier's current `complaint_ratio_per_1k` into `complaint_ratio_at_scoring`, so that later data refreshes cannot retroactively alter a completed scoring run."
        PRD §3.2: "The **complaint component** is a tier lookup on the snapshotted ratio: 40 points when the ratio is 5.00 or more, otherwise 28 points when it is 2.50 or more, otherwise 16 points when it is 1.00 or more, otherwise 6 points; the result is stored as `complaint_component`."
        PRD §3.2: "The **financial component** is the carrier's `financial_stress_score` multiplied by three tenths, rounded half up to two decimals, then held to a ceiling of 30.00, and stored as `financial_component`."
        PRD §3.2: "The **trend component** is the carrier's `consumer_trend_score` multiplied by two tenths, rounded half up to two decimals, then held to a ceiling of 30.00, and stored as `trend_component`."
        PRD §3.2: "The **volume multiplier** is 1.10 for a carrier whose `annual_premium_written_cents` is 5,000,000,000 cents (fifty million dollars) or more, and 1.00 otherwise; it is stored as `volume_multiplier`."
        PRD §3.2: "Every score row also receives a 1-based `rank_position`, assigned by the cycle's ranking expression: `composite_score` descending, then `complaint_ratio_at_scoring` descending, then the score row's own `created_at` ascending."

        Design: Difficulty/boundary_precision_check/zero_policy_count_yields_unrated_tier_and_zero_complaint_ratio
        """
        zero = _register_zero_policy_carrier()
        cedar = _register_cedar_carrier()
        cycle = create_analysis_cycle(
            cycle_label="FY2026 Zero Denominator Cycle",
            reference_period_start="2025-07-01",
            reference_period_end="2026-06-30",
            target_slot_capacity=2,
            default_fieldwork_start="2026-09-01",
            default_fieldwork_end="2026-11-30",
        )
        cycle = score_cycle(cycle["id"])
        assert cycle["scored_insurer_count"] == 2

        scores = read_cycle_scores(cycle["id"])
        zero_score = _score_row_for(scores, zero["id"])
        cedar_score = _score_row_for(scores, cedar["id"])

        assert zero_score["complaint_ratio_at_scoring"] == 0.00
        assert zero_score["complaint_component"] == 6
        assert zero_score["financial_component"] == 6.00
        assert zero_score["trend_component"] == 2.00
        assert zero_score["volume_multiplier"] == 1.00
        assert zero_score["composite_score"] == 14.00
        assert zero_score["rank_position"] == 2

        assert cedar_score["composite_score"] == 34.00
        assert cedar_score["rank_position"] == 1

    def test_both_composites_below_the_default_threshold_select_nothing(self):
        """An empty candidate pool still advances the cycle, marking every row.

        PRD §3.2: "The request may carry an optional `min_composite_score`; when it is absent the threshold is 40.00."
        PRD §3.2: "Second, a row whose `composite_score` is below the threshold is marked `BELOW_THRESHOLD`; a score exactly equal to the threshold survives."
        PRD §3.2: "An empty candidate pool is explicitly not an error: the cycle still advances to `TARGETS_SELECTED`, with `selected_target_count` of 0 and no examination created."

        Design: Difficulty/boundary_precision_check/zero_policy_count_yields_unrated_tier_and_zero_complaint_ratio
        """
        _register_zero_policy_carrier()
        _register_cedar_carrier()
        cycle = create_analysis_cycle(
            cycle_label="FY2026 Zero Denominator Cycle",
            reference_period_start="2025-07-01",
            reference_period_end="2026-06-30",
            target_slot_capacity=2,
            default_fieldwork_start="2026-09-01",
            default_fieldwork_end="2026-11-30",
        )
        score_cycle(cycle["id"])

        cycle = select_targets(cycle["id"])
        assert cycle["selected_target_count"] == 0
        assert cycle["slots_available"] == 2
        assert cycle["status"] == "TARGETS_SELECTED"

        for row in read_cycle_scores(cycle["id"]):
            assert row["selected"] is False
            assert row["selection_reason"] == "BELOW_THRESHOLD"


class TestSelectionThresholdAtExactEquality:
    def test_default_threshold_leaves_an_empty_candidate_pool(self):
        """A composite of 34.00 is below the absent-threshold default of 40.00.

        PRD §3.2: "The request may carry an optional `min_composite_score`; when it is absent the threshold is 40.00."
        PRD §3.2: "Second, a row whose `composite_score` is below the threshold is marked `BELOW_THRESHOLD`; a score exactly equal to the threshold survives."
        PRD §3.2: "An empty candidate pool is explicitly not an error: the cycle still advances to `TARGETS_SELECTED`, with `selected_target_count` of 0 and no examination created."

        Design: Difficulty/boundary_precision_check/selection_threshold_at_exact_composite_equality_after_empty_pool
        """
        _register_cedar_carrier()
        cycle_one = create_analysis_cycle(
            cycle_label="FY2026 Cycle One",
            reference_period_start="2025-07-01",
            reference_period_end="2026-06-30",
            target_slot_capacity=2,
            default_fieldwork_start="2026-09-01",
            default_fieldwork_end="2026-11-30",
        )
        score_cycle(cycle_one["id"])

        selected_cycle = select_targets(cycle_one["id"])
        assert selected_cycle["selected_target_count"] == 0
        assert selected_cycle["slots_committed"] == 0
        assert selected_cycle["slots_available"] == 2
        assert selected_cycle["status"] == "TARGETS_SELECTED"

        rows = read_cycle_scores(cycle_one["id"])
        assert rows[0]["composite_score"] == 34.00
        assert rows[0]["rank_position"] == 1
        assert rows[0]["selected"] is False
        assert rows[0]["selection_reason"] == "BELOW_THRESHOLD"

        _, meta = validate_paginated(
            api.list_examinations(SUPERVISOR, {"cycle_id": cycle_one["id"]})
        )
        assert meta["total_count"] == 0

    def test_threshold_equal_to_the_composite_selects_the_same_carrier(self):
        """The very same 34.00 survives an explicit threshold of exactly 34.00.

        PRD §3.2: "Second, a row whose `composite_score` is below the threshold is marked `BELOW_THRESHOLD`; a score exactly equal to the threshold survives."
        PRD §3.2: "Each taken row has `selected` set to true and `selection_reason` set to `SELECTED`, and produces one examination."
        PRD §3.2: "Each examination created by selection is stamped with the carrier's `insurer_id`, the originating `cycle_id`, an `exam_type` of `MARKET_CONDUCT_EXAM`, a `mode` copied from the cycle's `default_exam_mode`, a `lead_state_code` of `NV` (the examining department's own state), a `fieldwork_start_date` and `fieldwork_end_date` copied from the cycle's defaults, and a `status` of `SCOPING`."
        PRD §3.2: "An optional `default_exam_mode` is stamped onto every examination the cycle creates and defaults to `ON_SITE`; the only alternative is `DESK`."
        PRD §3.2: "Each creation raises the carrier's `open_exam_count` by 1 and the cycle's `slots_committed` by 1, thereby lowering `slots_available` by 1."

        Design: Difficulty/boundary_precision_check/selection_threshold_at_exact_composite_equality_after_empty_pool
        """
        cedar = _register_cedar_carrier()
        cycle_one = create_analysis_cycle(
            cycle_label="FY2026 Cycle One",
            reference_period_start="2025-07-01",
            reference_period_end="2026-06-30",
            target_slot_capacity=2,
            default_fieldwork_start="2026-09-01",
            default_fieldwork_end="2026-11-30",
        )
        score_cycle(cycle_one["id"])
        cycle_two = create_analysis_cycle(
            cycle_label="FY2027 Cycle Two",
            reference_period_start="2026-07-01",
            reference_period_end="2026-12-31",
            target_slot_capacity=2,
            default_fieldwork_start="2027-02-01",
            default_fieldwork_end="2027-04-30",
        )
        score_cycle(cycle_two["id"])

        select_targets(cycle_one["id"])

        selected_cycle = select_targets(cycle_two["id"], 34.00)
        assert selected_cycle["selected_target_count"] == 1
        assert selected_cycle["slots_committed"] == 1
        assert selected_cycle["slots_available"] == 1

        rows = read_cycle_scores(cycle_two["id"])
        assert rows[0]["composite_score"] == 34.00
        assert rows[0]["rank_position"] == 1
        assert rows[0]["selected"] is True
        assert rows[0]["selection_reason"] == "SELECTED"

        examinations, meta = validate_paginated(
            api.list_examinations(SUPERVISOR, {"cycle_id": cycle_two["id"]})
        )
        assert meta["total_count"] == 1
        spawned = examinations[0]
        assert spawned["insurer_id"] == cedar["id"]
        assert spawned["mode"] == "ON_SITE"
        assert spawned["lead_state_code"] == "NV"
        assert spawned["fieldwork_start_date"] == "2027-02-01"
        assert spawned["fieldwork_end_date"] == "2027-04-30"
        assert spawned["status"] == "SCOPING"

        assert read_insurer(cedar["id"])["open_exam_count"] == 1
        assert read_cycle(cycle_one["id"])["slots_committed"] == 0
