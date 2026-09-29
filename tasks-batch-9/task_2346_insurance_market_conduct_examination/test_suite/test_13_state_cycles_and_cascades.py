"""Non-linear state cycles and transitive cascades.

The criticism rebuttal loop, the data-call disposition branches with their
FIELDWORK -> PLANNED back edge, and the three cascades the PRD spells out:
the closing file review bubbling up to the collaboration, the last sustained
criticism syncing the restitution ledgers, and the abort fanning out to every
descendant and back up to the analysis cycle.
"""

from test_helpers import (
    DEFAULT_CLOCK_UTC,
    EIC,
    STANDARD_PARTICIPATING_STATES,
    SUPERVISING_EXAMINER_B_ID,
    SUPERVISOR,
    SUPERVISOR_B,
    ApiErrorId,
    abort_payload,
    add_scope_area,
    assert_restitution_ledgers_balance,
    bulk_review,
    company_response_payload,
    criticism_finalize_payload,
    disposition_payload,
    is_iso8601_timestamp,
    issue_criticism,
    issue_data_call,
    lock_scope,
    make_insurer_respondent_headers,
    open_collaboration,
    read_collaboration,
    read_criticism,
    read_cycle,
    read_data_call,
    read_examination,
    read_file_samples,
    read_insurer,
    read_scope_area,
    rebuttal_payload,
    record_standard_workpapers,
    respond_to_criticism,
    respond_to_data_call,
    setup_area_in_fieldwork,
    setup_cycle_with_selected_targets,
    setup_examination_in_criticism,
    setup_locked_examination,
    systematic_file_references,
    validate_error,
    validate_paginated,
    validate_success,
)

# The canonical CLAIMS sample: population 4000, sample 10, three MATERIAL files
# quantifying 25000 + 18000 + 7333 = 50333 cents of consumer harm over ten
# reviewed files.  Extrapolation rounds 50333 / 10 to 5033 cents per file and
# multiplies by the population of 4000.
SAMPLE_HARM_CENTS = 50_333
EXTRAPOLATED_EXPOSURE_CENTS = 20_132_000

CLAIMS_REFERENCES = systematic_file_references("CLAIMS", 4000, 10)


# ─── Instance: criticism rebuttal cycle ───────────────────────────────────


def _examination_with_issued_criticism() -> dict:
    """Examination in CRITICISM with one MATERIAL criticism ISSUED on a breached area."""
    scenario = setup_examination_in_criticism()
    criticism = issue_criticism(
        scenario["exam_id"], scenario["scope_area_id"], "MATERIAL", 3
    )
    scenario["criticism"] = criticism
    scenario["criticism_id"] = criticism["id"]
    return scenario


def _answer(api, criticism_id: str, insurer_id: str, position: str, narrative: str) -> dict:
    return validate_success(
        api.create_company_response(
            criticism_id,
            company_response_payload(position, narrative=narrative),
            make_insurer_respondent_headers(insurer_id),
        ),
        201,
    )


def _rebut(api, criticism_id: str, note: str):
    return api.rebut_criticism(criticism_id, rebuttal_payload(rebuttal_note=note), EIC)


def _spend_the_round_budget(api, scenario: dict) -> None:
    """Three answers and two rebuttals: the criticism parks in RESPONDED at round 3."""
    criticism_id = scenario["criticism_id"]
    insurer_id = scenario["insurer_id"]
    _answer(
        api,
        criticism_id,
        insurer_id,
        "DISPUTE",
        "Round one: the carrier disputes all three cited files.",
    )
    validate_success(
        _rebut(
            api,
            criticism_id,
            "Rebuttal one: the department is not persuaded and requests further documentation.",
        )
    )
    _answer(
        api,
        criticism_id,
        insurer_id,
        "PARTIAL_CONCUR",
        "Round two: the carrier concurs on one file and disputes two.",
    )
    validate_success(
        _rebut(api, criticism_id, "Rebuttal two: partial concurrence is insufficient.")
    )
    _answer(
        api,
        criticism_id,
        insurer_id,
        "CONCUR",
        "Round three: the carrier concurs and offers remediation.",
    )


def test_answer_and_rebuttal_edges_advance_their_own_counters(api):
    """The loop counter and the back-edge counter move on different edges.

    PRD §3.7: "Each answer materialises a `CompanyResponse` carrying its `criticism_id`, its `round_number` — one greater than the criticism's `response_round` before the answer, and therefore equal to the criticism's `response_round` immediately afterwards — and a `submitted_at` stamp from the logical clock."
    PRD §3.7: "The `ExaminerInCharge` may rebut a `RESPONDED` criticism, supplying a `rebuttal_note` of at least 20 characters, which returns the criticism to `ISSUED` for another round, raises `rebuttal_count` by 1 and increments the criticism's `version` by 1."

    Design: Difficulty/non_linear_state_machine/criticism_rebuttal_cycle_loops_to_issued_and_terminates_at_round_bound
    """
    scenario = _examination_with_issued_criticism()
    criticism_id = scenario["criticism_id"]
    insurer_id = scenario["insurer_id"]

    issued = read_criticism(criticism_id)
    assert issued["status"] == "ISSUED"
    assert issued["response_round"] == 0
    assert issued["rebuttal_count"] == 0

    first = _answer(
        api,
        criticism_id,
        insurer_id,
        "DISPUTE",
        "Round one: the carrier disputes all three cited files.",
    )
    assert first["round_number"] == 1
    after_first_answer = read_criticism(criticism_id)
    assert after_first_answer["status"] == "RESPONDED"
    assert after_first_answer["response_round"] == 1
    assert after_first_answer["rebuttal_count"] == 0

    first_rebuttal = validate_success(
        _rebut(
            api,
            criticism_id,
            "Rebuttal one: the department is not persuaded and requests further documentation.",
        )
    )
    assert first_rebuttal["status"] == "ISSUED"
    assert first_rebuttal["rebuttal_count"] == 1
    assert first_rebuttal["response_round"] == 1

    second = _answer(
        api,
        criticism_id,
        insurer_id,
        "PARTIAL_CONCUR",
        "Round two: the carrier concurs on one file and disputes two.",
    )
    assert second["round_number"] == 2
    after_second_answer = read_criticism(criticism_id)
    assert after_second_answer["status"] == "RESPONDED"
    assert after_second_answer["response_round"] == 2
    assert after_second_answer["rebuttal_count"] == 1

    second_rebuttal = validate_success(
        _rebut(api, criticism_id, "Rebuttal two: partial concurrence is insufficient.")
    )
    assert second_rebuttal["status"] == "ISSUED"
    assert second_rebuttal["rebuttal_count"] == 2
    assert second_rebuttal["response_round"] == 2

    third = _answer(
        api,
        criticism_id,
        insurer_id,
        "CONCUR",
        "Round three: the carrier concurs and offers remediation.",
    )
    assert third["round_number"] == 3
    after_third_answer = read_criticism(criticism_id)
    assert after_third_answer["status"] == "RESPONDED"
    assert after_third_answer["response_round"] == 3
    assert after_third_answer["rebuttal_count"] == 2

    rounds, meta = validate_paginated(api.list_company_responses(criticism_id, EIC))
    assert meta["total_count"] == 3
    assert [entry["round_number"] for entry in rounds] == [1, 2, 3]


def test_third_rebuttal_is_refused_once_the_round_budget_is_spent(api):
    """The shared guard is strict, so 3 < 3 is false and the back edge does not fire.

    PRD §3.7: "Both sides of the cycle share one guard, and the comparison is strict: an answer or a rebuttal is permitted only while the criticism's `response_round` is strictly below three. Once `response_round` has reached three, both are rejected with `ERR_REBUTTAL_ROUNDS_EXHAUSTED`."

    Design: Difficulty/non_linear_state_machine/criticism_rebuttal_cycle_loops_to_issued_and_terminates_at_round_bound
    """
    scenario = _examination_with_issued_criticism()
    criticism_id = scenario["criticism_id"]
    _spend_the_round_budget(api, scenario)

    refused = _rebut(
        api,
        criticism_id,
        "Rebuttal three: an attempt to rebut a third time, after the round budget is spent.",
    )
    validate_error(refused, ApiErrorId.ERR_REBUTTAL_ROUNDS_EXHAUSTED.value, 409)

    parked = read_criticism(criticism_id)
    assert parked["status"] == "RESPONDED"
    assert parked["response_round"] == 3
    assert parked["rebuttal_count"] == 2

    _, meta = validate_paginated(api.list_company_responses(criticism_id, EIC))
    assert meta["total_count"] == 3


def test_fourth_answer_is_refused_by_the_criticism_state_band(api):
    """A criticism parked in RESPONDED fails the lifecycle-state band before the round guard.

    PRD §3.7: "The carrier answers a criticism that is in `ISSUED`, moving it to `RESPONDED`."
    PRD §3.7: "The acting `X-User-ID` must equal the examination's `insurer_id`, otherwise `ERR_NOT_EXAM_SUBJECT`; a criticism in any state other than `ISSUED` yields `ERR_CRITICISM_STATE_INVALID`."
    PRD §2.11: "Checks are evaluated in the following bands, in this order, and the first band that produces a rejection determines the response:"

    Design: Difficulty/non_linear_state_machine/criticism_rebuttal_cycle_loops_to_issued_and_terminates_at_round_bound
    """
    scenario = _examination_with_issued_criticism()
    criticism_id = scenario["criticism_id"]
    _spend_the_round_budget(api, scenario)

    refused = api.create_company_response(
        criticism_id,
        company_response_payload(
            "DISPUTE", narrative="Round four: an attempt to answer a fourth time."
        ),
        make_insurer_respondent_headers(scenario["insurer_id"]),
    )
    validate_error(refused, ApiErrorId.ERR_CRITICISM_STATE_INVALID.value, 409)

    _, meta = validate_paginated(api.list_company_responses(criticism_id, EIC))
    assert meta["total_count"] == 3
    assert read_criticism(criticism_id)["response_round"] == 3


def test_exposure_frozen_at_issuance_survives_the_whole_cycle_and_finalization(api):
    """Looping never recomputes the exposure, and the parked criticism is still finalizable.

    PRD §3.7: "Rebuttal explicitly does **not** recompute the exposure: `restitution_method` and `restitution_exposure_cents` keep the values frozen at issuance, however many rounds the cycle runs."
    PRD §3.7: "The practical consequence is that after the third answer the criticism sits in `RESPONDED` with `response_round` at 3 and can only be finalized; `rebuttal_count` therefore never exceeds two on a criticism that reaches finalization."

    Design: Difficulty/non_linear_state_machine/criticism_rebuttal_cycle_loops_to_issued_and_terminates_at_round_bound
    """
    scenario = _examination_with_issued_criticism()
    criticism_id = scenario["criticism_id"]
    exam_id = scenario["exam_id"]

    at_issuance = read_criticism(criticism_id)
    assert at_issuance["restitution_method"] == "POPULATION_EXTRAPOLATED"
    assert at_issuance["restitution_exposure_cents"] == EXTRAPOLATED_EXPOSURE_CENTS

    _spend_the_round_budget(api, scenario)

    after_cycle = read_criticism(criticism_id)
    assert after_cycle["restitution_method"] == "POPULATION_EXTRAPOLATED"
    assert after_cycle["restitution_exposure_cents"] == EXTRAPOLATED_EXPOSURE_CENTS

    finalized = validate_success(
        api.finalize_criticism(
            criticism_id,
            criticism_finalize_payload(
                "SUSTAINED",
                12,
                disposition_note="Sustained after three rounds of correspondence.",
            ),
            SUPERVISOR_B,
        )
    )
    assert finalized["status"] == "SUSTAINED"
    assert finalized["response_round"] == 3
    assert finalized["rebuttal_count"] == 2
    assert finalized["restitution_exposure_cents"] == EXTRAPOLATED_EXPOSURE_CENTS

    examination = read_examination(exam_id)
    assert examination["aggregate_restitution_cents"] == EXTRAPOLATED_EXPOSURE_CENTS
    assert examination["pending_restitution_cents"] == 0
    assert examination["open_criticism_count"] == 0
    assert examination["status"] == "NEGOTIATION"


# ─── Instance: scope area loops back to PLANNED on rejection ──────────────


def _area_with_two_accepted_and_responded_calls() -> dict:
    """DC1 accepted (samples drawn, area FIELDWORK) plus DC2 awaiting disposition."""
    scenario = setup_area_in_fieldwork(area="CLAIMS", population_size=4000, sample_size=10)
    second_call = issue_data_call(
        scenario["scope_area_id"],
        records_requested=4000,
        response_due_date="2026-09-20",
    )
    respond_to_data_call(second_call["id"], scenario["insurer_id"], records_received=4000)
    scenario["second_call_id"] = second_call["id"]
    return scenario


def test_rejection_reverts_the_area_to_planned_and_deletes_its_unreviewed_samples(api):
    """The back edge deletes the earlier call's samples and zeroes every derived counter.

    PRD §3.4: "If the area is in `FIELDWORK` and its `reviewed_sample_count` is 0, the area reverts `FIELDWORK → PLANNED`: every one of its file samples is deleted (all of them are necessarily `UNREVIEWED`), `reviewed_sample_count`, `error_count`, `material_error_count`, `error_rate_pct` and `material_error_rate_pct` are reset to 0 or 0.00, `tolerance_breached` and `escalation_required` are reset to false, `samples_drawn_count` is reset to 0 on every already-`ACCEPTED` data call of the area whose samples were just deleted, and the area's `version` is incremented by 1."

    Design: Difficulty/non_linear_state_machine/scope_area_loops_back_to_planned_on_data_call_rejection_voiding_samples
    """
    scenario = _area_with_two_accepted_and_responded_calls()
    first_call_id = scenario["data_call_id"]
    area_id = scenario["scope_area_id"]

    before = read_data_call(first_call_id)
    assert before["status"] == "ACCEPTED"
    assert before["sample_draw_interval"] == 400
    assert before["samples_drawn_count"] == 10
    assert read_scope_area(area_id)["status"] == "FIELDWORK"
    _, before_meta = validate_paginated(api.list_file_samples(first_call_id, EIC))
    assert before_meta["total_count"] == 10

    rejected = validate_success(
        api.disposition_data_call(
            scenario["second_call_id"],
            disposition_payload(
                "REJECTED",
                disposition_reason=(
                    "The supplemental production is unusable: key claim dates are missing."
                ),
            ),
            EIC,
        )
    )
    assert rejected["status"] == "REJECTED"
    assert rejected["samples_drawn_count"] == 0

    area = read_scope_area(area_id)
    assert area["status"] == "PLANNED"
    assert area["reviewed_sample_count"] == 0
    assert area["error_count"] == 0
    assert area["material_error_count"] == 0
    assert area["error_rate_pct"] == 0.00
    assert area["material_error_rate_pct"] == 0.00
    assert area["tolerance_breached"] is False
    assert area["escalation_required"] is False

    _, after_meta = validate_paginated(api.list_file_samples(first_call_id, EIC))
    assert after_meta["total_count"] == 0
    assert read_data_call(first_call_id)["samples_drawn_count"] == 0


def test_examination_does_not_roll_back_out_of_fieldwork_on_a_rejection(api):
    """Only the examination-level rejection counter moves; the examination stays in FIELDWORK.

    PRD §3.4: "Rejecting draws no samples at all and never advances the examination into `FIELDWORK`. It raises the examination's `rejected_data_call_count` by 1 in every case, and increments the call's `version` by 1."
    PRD §3.4: "In none of these cases does the examination roll back out of `FIELDWORK`."

    Design: Difficulty/non_linear_state_machine/scope_area_loops_back_to_planned_on_data_call_rejection_voiding_samples
    """
    scenario = _area_with_two_accepted_and_responded_calls()
    exam_id = scenario["exam_id"]

    before = read_examination(exam_id)
    assert before["status"] == "FIELDWORK"
    assert before["rejected_data_call_count"] == 0

    validate_success(
        api.disposition_data_call(
            scenario["second_call_id"],
            disposition_payload(
                "REJECTED",
                disposition_reason=(
                    "The supplemental production is unusable: key claim dates are missing."
                ),
            ),
            EIC,
        )
    )

    after = read_examination(exam_id)
    assert after["rejected_data_call_count"] == 1
    assert after["status"] == "FIELDWORK"


def test_replacement_data_call_redraws_the_identical_sample_from_scratch(api):
    """The reverted area is re-enterable: a third call redraws the same ten references.

    PRD §3.4: "That reversion exists so a replacement data call can re-draw the whole sample, subject to the three-day spacing rule."
    PRD §3.4: "Second, the owning scope area advances `PLANNED → FIELDWORK` and its file samples are materialised, its own `version` incremented by 1."
    PRD §3.5: "The plan then walks the sample positions in order: the first sampled file sits at `population_index` 1, and each subsequent file sits one draw interval further along, so the k-th file after the first sits at 1 plus k times the interval."

    Design: Difficulty/non_linear_state_machine/scope_area_loops_back_to_planned_on_data_call_rejection_voiding_samples
    """
    scenario = _area_with_two_accepted_and_responded_calls()
    area_id = scenario["scope_area_id"]
    exam_id = scenario["exam_id"]

    validate_success(
        api.disposition_data_call(
            scenario["second_call_id"],
            disposition_payload(
                "REJECTED",
                disposition_reason=(
                    "The supplemental production is unusable: key claim dates are missing."
                ),
            ),
            EIC,
        )
    )
    assert read_scope_area(area_id)["status"] == "PLANNED"

    third_call = issue_data_call(
        area_id, records_requested=4000, response_due_date="2026-09-25"
    )
    respond_to_data_call(third_call["id"], scenario["insurer_id"], records_received=4000)
    accepted = validate_success(
        api.disposition_data_call(
            third_call["id"],
            disposition_payload(
                "ACCEPTED", disposition_reason="Replacement production is complete."
            ),
            EIC,
        )
    )
    assert accepted["status"] == "ACCEPTED"
    assert accepted["sample_draw_interval"] == 400
    assert accepted["samples_drawn_count"] == 10

    redrawn, meta = validate_paginated(api.list_file_samples(third_call["id"], EIC))
    assert meta["total_count"] == 10
    assert [sample["file_reference"] for sample in redrawn] == [
        "CLM-000001",
        "CLM-000401",
        "CLM-000801",
        "CLM-001201",
        "CLM-001601",
        "CLM-002001",
        "CLM-002401",
        "CLM-002801",
        "CLM-003201",
        "CLM-003601",
    ]
    assert [sample["population_index"] for sample in redrawn] == [
        1,
        401,
        801,
        1201,
        1601,
        2001,
        2401,
        2801,
        3201,
        3601,
    ]

    assert read_scope_area(area_id)["status"] == "FIELDWORK"
    assert read_examination(exam_id)["rejected_data_call_count"] == 1


# ─── Instance: disjoint disposition branches ──────────────────────────────


def _two_areas_awaiting_disposition() -> dict:
    """CLAIMS 300/10 and RATING 500/10, one RESPONDED data call each."""
    scenario = setup_locked_examination(
        areas=(("CLAIMS", 300, 10), ("RATING", 500, 10))
    )
    claims_call = issue_data_call(
        scenario["scope_areas"]["CLAIMS"]["id"],
        records_requested=300,
        response_due_date="2026-09-15",
    )
    rating_call = issue_data_call(
        scenario["scope_areas"]["RATING"]["id"],
        records_requested=500,
        response_due_date="2026-09-15",
    )
    respond_to_data_call(claims_call["id"], scenario["insurer_id"], records_received=300)
    respond_to_data_call(rating_call["id"], scenario["insurer_id"], records_received=500)
    scenario["claims_call_id"] = claims_call["id"]
    scenario["rating_call_id"] = rating_call["id"]
    return scenario


def test_accepted_branch_draws_the_systematic_sample_and_advances_both_parents(api):
    """Acceptance cascades in three hops: the call, its area, then the examination.

    PRD §3.4: "A successful acceptance cascades in three hops. First, the call records its sampling plan — `sample_draw_interval` and `samples_drawn_count` — and moves to `ACCEPTED`, its `version` incremented by 1. Second, the owning scope area advances `PLANNED → FIELDWORK` and its file samples are materialised, its own `version` incremented by 1. Third, if this is the first data call of the examination to reach `ACCEPTED`, the examination itself advances `DATA_CALL → FIELDWORK` and its `version` is incremented by 1."
    PRD §3.5: "Each starts with `review_status` of `UNREVIEWED`, `error_severity` of `NONE`, `underpaid_amount_cents` of 0 and `days_to_pay` of 0."

    Design: Difficulty/non_linear_state_machine/data_call_disposition_branches_have_disjoint_side_effects
    """
    scenario = _two_areas_awaiting_disposition()

    accepted = validate_success(
        api.disposition_data_call(
            scenario["claims_call_id"],
            disposition_payload(
                "ACCEPTED", disposition_reason="Claims production is complete."
            ),
            EIC,
        )
    )
    assert accepted["status"] == "ACCEPTED"
    assert accepted["sample_draw_interval"] == 30
    assert accepted["samples_drawn_count"] == 10

    samples, meta = validate_paginated(
        api.list_file_samples(scenario["claims_call_id"], EIC)
    )
    assert meta["total_count"] == 10
    assert [sample["file_reference"] for sample in samples] == [
        "CLM-000001",
        "CLM-000031",
        "CLM-000061",
        "CLM-000091",
        "CLM-000121",
        "CLM-000151",
        "CLM-000181",
        "CLM-000211",
        "CLM-000241",
        "CLM-000271",
    ]
    for sample in samples:
        assert sample["review_status"] == "UNREVIEWED"
        assert sample["error_severity"] == "NONE"
        assert sample["underpaid_amount_cents"] == 0

    assert read_scope_area(scenario["scope_areas"]["CLAIMS"]["id"])["status"] == "FIELDWORK"
    assert read_examination(scenario["exam_id"])["status"] == "FIELDWORK"


def test_rejected_branch_draws_nothing_and_leaves_the_planned_sibling_untouched(api):
    """The rejection branch touches only the examination counter; a PLANNED area is untouched.

    PRD §3.4: "Rejecting draws no samples at all and never advances the examination into `FIELDWORK`. It raises the examination's `rejected_data_call_count` by 1 in every case, and increments the call's `version` by 1."
    PRD §3.4: "If the area is still in `PLANNED`, nothing further happens to it."
    PRD §3.4: "The server stamps `issued_date` from the date part of the logical clock and opens the call in `ISSUED` with `records_received` 0, `is_late` false, `days_late` 0, `completeness_pct` 0.00, `effective_completeness_pct` 0.00, `sample_draw_interval` 0 and `samples_drawn_count` 0."

    Design: Difficulty/non_linear_state_machine/data_call_disposition_branches_have_disjoint_side_effects
    """
    scenario = _two_areas_awaiting_disposition()
    rating_area_id = scenario["scope_areas"]["RATING"]["id"]

    validate_success(
        api.disposition_data_call(
            scenario["claims_call_id"],
            disposition_payload(
                "ACCEPTED", disposition_reason="Claims production is complete."
            ),
            EIC,
        )
    )
    rejected = validate_success(
        api.disposition_data_call(
            scenario["rating_call_id"],
            disposition_payload(
                "REJECTED",
                disposition_reason="Rating production omits the rating factors requested.",
            ),
            EIC,
        )
    )
    assert rejected["status"] == "REJECTED"
    assert rejected["sample_draw_interval"] == 0
    assert rejected["samples_drawn_count"] == 0

    _, meta = validate_paginated(api.list_file_samples(scenario["rating_call_id"], EIC))
    assert meta["total_count"] == 0

    rating_area = read_scope_area(rating_area_id)
    assert rating_area["status"] == "PLANNED"
    assert rating_area["reviewed_sample_count"] == 0
    assert rating_area["tolerance_breached"] is False

    examination = read_examination(scenario["exam_id"])
    assert examination["rejected_data_call_count"] == 1
    assert examination["status"] == "FIELDWORK"


# ─── Instance: closing review cascades to the collaboration ───────────────


def _area_with_one_unreviewed_file() -> dict:
    """Nine of ten CLAIMS files reviewed; CLM-000801 is the single UNREVIEWED file."""
    scenario = setup_area_in_fieldwork(area="CLAIMS", population_size=4000, sample_size=10)
    collaboration = open_collaboration(scenario["exam_id"], STANDARD_PARTICIPATING_STATES)
    scenario["collaboration"] = collaboration
    scenario["collaboration_id"] = collaboration["id"]
    record_standard_workpapers(scenario["exam_id"], "CLAIMS")

    reviews = [
        {
            "file_reference": "CLM-000001",
            "error_severity": "MATERIAL",
            "underpaid_amount_cents": 25_000,
            "days_to_pay": 61,
        },
        {
            "file_reference": "CLM-000401",
            "error_severity": "MATERIAL",
            "underpaid_amount_cents": 18_000,
            "days_to_pay": 47,
        },
    ]
    reviews += [
        {"file_reference": reference, "error_severity": "NONE"}
        for reference in CLAIMS_REFERENCES
        if reference not in ("CLM-000001", "CLM-000401", "CLM-000801")
    ]
    scenario["bulk_result"] = bulk_review(scenario["data_call_id"], reviews)

    samples = read_file_samples(scenario["data_call_id"])
    unreviewed = [s for s in samples if s["review_status"] == "UNREVIEWED"]
    assert len(unreviewed) == 1
    assert unreviewed[0]["file_reference"] == "CLM-000801"
    scenario["last_sample"] = unreviewed[0]
    scenario["last_sample_id"] = unreviewed[0]["id"]
    return scenario


def test_closing_review_marks_the_file_an_error_and_drives_the_area_to_tested(api):
    """Hops 1 and 2: the smallest write closes out testing on the area.

    PRD §3.5: "The review derives `review_status` from severity: `COMPLIANT` when `error_severity` is `NONE`, and `ERROR` for both `MINOR` and `MATERIAL`."
    PRD §3.5: "When the last `UNREVIEWED` file of an area is reviewed, whether by a single review or as part of a bulk batch, the area advances `FIELDWORK → TESTED` and cascades in two further hops. First, every counter and both flags above are recomputed, `tested_at` is stamped from the logical clock, and the area's `version` is incremented by 1."

    Design: Difficulty/transitive_cascade/final_sample_review_cascades_area_exam_and_collaboration
    """
    scenario = _area_with_one_unreviewed_file()
    assert scenario["bulk_result"]["applied_count"] == 9
    assert scenario["bulk_result"]["scope_area_status"] == "FIELDWORK"
    assert scenario["bulk_result"]["error_rate_pct"] == 22.22

    reviewed = validate_success(
        api.review_file_sample(
            scenario["last_sample_id"],
            {"error_severity": "MATERIAL", "underpaid_amount_cents": 7_333, "days_to_pay": 39},
            EIC,
        )
    )
    assert reviewed["review_status"] == "ERROR"
    assert reviewed["error_severity"] == "MATERIAL"
    assert reviewed["underpaid_amount_cents"] == 7_333
    assert is_iso8601_timestamp(reviewed["reviewed_at"])

    area = read_scope_area(scenario["scope_area_id"])
    assert area["status"] == "TESTED"
    assert is_iso8601_timestamp(area["tested_at"])


def test_closing_review_recomputes_both_error_rates_and_both_tolerance_flags(api):
    """Hop 2's derived counters: three errors over ten reviewed files breach and escalate.

    PRD §3.5: "`error_rate_pct` is `error_count` multiplied by one hundred and divided by `reviewed_sample_count`, rounded half up to two decimals, or 0.00 when nothing has been reviewed; `material_error_rate_pct` is the same computation over `material_error_count`."
    PRD §3.5: "`tolerance_breached` is true when `error_rate_pct` is greater than or equal to the area's own `error_tolerance_pct`; an error rate exactly equal to the tolerance breaches it. `escalation_required` is true when `material_error_rate_pct` is greater than or equal to 10.00 percent; again exact equality escalates."

    Design: Difficulty/transitive_cascade/final_sample_review_cascades_area_exam_and_collaboration
    """
    scenario = _area_with_one_unreviewed_file()

    validate_success(
        api.review_file_sample(
            scenario["last_sample_id"],
            {"error_severity": "MATERIAL", "underpaid_amount_cents": 7_333, "days_to_pay": 39},
            EIC,
        )
    )

    area = read_scope_area(scenario["scope_area_id"])
    assert area["error_tolerance_pct"] == 3.00
    assert area["reviewed_sample_count"] == 10
    assert area["error_count"] == 3
    assert area["material_error_count"] == 3
    assert area["error_rate_pct"] == 30.00
    assert area["material_error_rate_pct"] == 30.00
    assert area["tolerance_breached"] is True
    assert area["escalation_required"] is True


def test_last_tested_area_bubbles_to_criticism_and_activates_the_collaboration(api):
    """Hops 3 and 4: the examination transition itself activates the LEAD_ASSIGNED collaboration.

    PRD §3.5: "Second, when **every** scope area of the examination has reached `TESTED`, the examination bubbles up `FIELDWORK → CRITICISM`, stamps `criticism_phase_opened_at` from the logical clock and increments its `version` by 1 — and that examination transition in turn advances any multistate collaboration on the examination that is still in `LEAD_ASSIGNED` to `ACTIVE`, incrementing the collaboration's `version` by 1."
    PRD §3.9: "Activation is not a client action: as described in §3.5, a collaboration in `LEAD_ASSIGNED` advances to `ACTIVE` when its examination bubbles up from `FIELDWORK` to `CRITICISM`, and its `version` is incremented by 1."

    Design: Difficulty/transitive_cascade/final_sample_review_cascades_area_exam_and_collaboration
    """
    scenario = _area_with_one_unreviewed_file()
    exam_id = scenario["exam_id"]
    collaboration_id = scenario["collaboration_id"]

    before_collaboration = read_collaboration(collaboration_id)
    assert before_collaboration["status"] == "LEAD_ASSIGNED"
    assert read_examination(exam_id)["status"] == "FIELDWORK"

    validate_success(
        api.review_file_sample(
            scenario["last_sample_id"],
            {"error_severity": "MATERIAL", "underpaid_amount_cents": 7_333, "days_to_pay": 39},
            EIC,
        )
    )

    examination = read_examination(exam_id)
    assert examination["status"] == "CRITICISM"
    assert is_iso8601_timestamp(examination["criticism_phase_opened_at"])
    assert examination["criticism_phase_opened_at"].startswith(DEFAULT_CLOCK_UTC[:10])
    assert examination["open_criticism_count"] == 0
    assert examination["pending_restitution_cents"] == 0

    collaboration = read_collaboration(collaboration_id)
    assert collaboration["status"] == "ACTIVE"
    assert collaboration["lead_state_code"] == "NV"
    assert collaboration["participant_count"] == 3
    assert collaboration["allocated_total_cents"] == 0

    insurer = read_insurer(scenario["insurer_id"])
    assert insurer["open_exam_count"] == 1
    assert insurer["pending_enforcement_exam_count"] == 0


# ─── Instance: sustained criticism cascades the ledgers ───────────────────


MINOR_EXPOSURE_CENTS = SAMPLE_HARM_CENTS  # SAMPLE_ACTUAL charges the observed harm exactly
TOTAL_ISSUED_EXPOSURE_CENTS = EXTRAPOLATED_EXPOSURE_CENTS + MINOR_EXPOSURE_CENTS


def _examination_with_two_responded_criticisms() -> dict:
    """C1 MATERIAL (extrapolated) and C2 MINOR (sample actual), both RESPONDED."""
    scenario = setup_examination_in_criticism()
    material = issue_criticism(
        scenario["exam_id"], scenario["scope_area_id"], "MATERIAL", 3
    )
    minor = issue_criticism(
        scenario["exam_id"],
        scenario["scope_area_id"],
        "MINOR",
        1,
        statute_citation="NRS 686A.310(1)(n)",
    )
    respond_to_criticism(material["id"], scenario["insurer_id"], "DISPUTE")
    respond_to_criticism(
        minor["id"],
        scenario["insurer_id"],
        "CONCUR",
        narrative="The carrier concurs with the minor documentation criticism.",
    )
    scenario["material_criticism"] = material
    scenario["material_criticism_id"] = material["id"]
    scenario["minor_criticism"] = minor
    scenario["minor_criticism_id"] = minor["id"]
    return scenario


def test_first_sustain_accrues_only_its_own_exposure_and_holds_the_examination(api):
    """Sustaining one of two open criticisms moves that exposure only and does not release NEGOTIATION.

    PRD §3.7: "Second, the frozen exposure moves from provisional to accrued on the examination: `open_criticism_count` is lowered by 1 and `pending_restitution_cents` is lowered by the criticism's `restitution_exposure_cents`, while `sustained_criticism_count` is raised by 1, `aggregate_restitution_cents` is raised by that same `restitution_exposure_cents`, and `penalty_units_total` is raised by the criticism's `penalty_units`; the examination's `version` is incremented by 1."
    PRD §3.7: "Third, if that leaves the examination with `open_criticism_count` of 0 and `sustained_criticism_count` of 1 or more, the examination advances `CRITICISM → NEGOTIATION`, incrementing its `version` again and raising the subject carrier's `pending_enforcement_exam_count` by 1."

    Design: Difficulty/transitive_cascade/sustained_criticism_cascades_ledgers_exam_state_and_insurer_counter
    """
    scenario = _examination_with_two_responded_criticisms()
    assert scenario["material_criticism"]["restitution_exposure_cents"] == (
        EXTRAPOLATED_EXPOSURE_CENTS
    )
    assert scenario["minor_criticism"]["restitution_exposure_cents"] == MINOR_EXPOSURE_CENTS

    before = read_examination(scenario["exam_id"])
    assert before["open_criticism_count"] == 2
    assert before["sustained_criticism_count"] == 0
    assert before["pending_restitution_cents"] == TOTAL_ISSUED_EXPOSURE_CENTS
    assert before["aggregate_restitution_cents"] == 0

    sustained = validate_success(
        api.finalize_criticism(
            scenario["minor_criticism_id"],
            criticism_finalize_payload(
                "SUSTAINED",
                1,
                disposition_note="Minor criticism sustained on concurrence.",
            ),
            SUPERVISOR_B,
        )
    )
    assert sustained["status"] == "SUSTAINED"

    midpoint = read_examination(scenario["exam_id"])
    assert midpoint["open_criticism_count"] == 1
    assert midpoint["sustained_criticism_count"] == 1
    assert midpoint["pending_restitution_cents"] == EXTRAPOLATED_EXPOSURE_CENTS
    assert midpoint["aggregate_restitution_cents"] == MINOR_EXPOSURE_CENTS
    assert midpoint["penalty_units_total"] == 1
    assert midpoint["status"] == "CRITICISM"

    assert read_insurer(scenario["insurer_id"])["pending_enforcement_exam_count"] == 0


def test_sustaining_the_last_open_criticism_releases_negotiation_and_the_insurer_counter(api):
    """Emptying open_criticism_count cascades to the examination status and up to the carrier.

    PRD §3.7: "Either disposition records `finalized_by_user_id` from `X-User-ID`, stamps `finalized_at` from the logical clock, and increments the criticism's `version` by 1; both `SUSTAINED` and `WITHDRAWN` are terminal for the criticism."
    PRD §3.7: "Third, if that leaves the examination with `open_criticism_count` of 0 and `sustained_criticism_count` of 1 or more, the examination advances `CRITICISM → NEGOTIATION`, incrementing its `version` again and raising the subject carrier's `pending_enforcement_exam_count` by 1."

    Design: Difficulty/transitive_cascade/sustained_criticism_cascades_ledgers_exam_state_and_insurer_counter
    """
    scenario = _examination_with_two_responded_criticisms()

    validate_success(
        api.finalize_criticism(
            scenario["minor_criticism_id"],
            criticism_finalize_payload(
                "SUSTAINED", 1, disposition_note="Minor criticism sustained on concurrence."
            ),
            SUPERVISOR_B,
        )
    )
    final = validate_success(
        api.finalize_criticism(
            scenario["material_criticism_id"],
            criticism_finalize_payload(
                "SUSTAINED",
                12,
                disposition_note=(
                    "Material criticism sustained after the carrier rebuttal was considered."
                ),
            ),
            SUPERVISOR_B,
        )
    )
    assert final["status"] == "SUSTAINED"
    assert final["finalized_by_user_id"] == SUPERVISING_EXAMINER_B_ID
    assert is_iso8601_timestamp(final["finalized_at"])

    examination = read_examination(scenario["exam_id"])
    assert examination["open_criticism_count"] == 0
    assert examination["sustained_criticism_count"] == 2
    assert examination["pending_restitution_cents"] == 0
    assert examination["aggregate_restitution_cents"] == TOTAL_ISSUED_EXPOSURE_CENTS
    assert examination["penalty_units_total"] == 13
    assert examination["status"] == "NEGOTIATION"

    insurer = read_insurer(scenario["insurer_id"])
    assert insurer["pending_enforcement_exam_count"] == 1
    assert insurer["open_exam_count"] == 1


def test_restitution_is_conserved_at_every_point_of_the_finalization_cascade(api):
    """Provisional plus accrued restitution stays at the issued exposure throughout.

    PRD §3.6: "A new criticism opens in `ISSUED` with `response_round` 0 and `rebuttal_count` 0, records the acting `X-User-ID` as `issued_by_user_id` for the later segregation-of-duties comparison, raises the examination's `open_criticism_count` by 1 and its `pending_restitution_cents` by the frozen `restitution_exposure_cents`, and increments the examination's `version` by 1."
    PRD §3.7: "Second, the frozen exposure moves from provisional to accrued on the examination: `open_criticism_count` is lowered by 1 and `pending_restitution_cents` is lowered by the criticism's `restitution_exposure_cents`, while `sustained_criticism_count` is raised by 1, `aggregate_restitution_cents` is raised by that same `restitution_exposure_cents`, and `penalty_units_total` is raised by the criticism's `penalty_units`; the examination's `version` is incremented by 1."

    Design: Difficulty/transitive_cascade/sustained_criticism_cascades_ledgers_exam_state_and_insurer_counter
    """
    scenario = _examination_with_two_responded_criticisms()
    exam_id = scenario["exam_id"]

    assert_restitution_ledgers_balance(
        read_examination(exam_id), TOTAL_ISSUED_EXPOSURE_CENTS
    )

    validate_success(
        api.finalize_criticism(
            scenario["minor_criticism_id"],
            criticism_finalize_payload(
                "SUSTAINED", 1, disposition_note="Minor criticism sustained on concurrence."
            ),
            SUPERVISOR_B,
        )
    )
    assert_restitution_ledgers_balance(
        read_examination(exam_id), TOTAL_ISSUED_EXPOSURE_CENTS
    )

    validate_success(
        api.finalize_criticism(
            scenario["material_criticism_id"],
            criticism_finalize_payload(
                "SUSTAINED",
                12,
                disposition_note=(
                    "Material criticism sustained after the carrier rebuttal was considered."
                ),
            ),
            SUPERVISOR_B,
        )
    )
    assert_restitution_ledgers_balance(
        read_examination(exam_id), TOTAL_ISSUED_EXPOSURE_CENTS
    )


# ─── Instance: abort fans out and closes the cycle ────────────────────────

BOREAL = {
    "name": "Boreal Indemnity Company",
    "naic_code": "10002",
    "annual_premium_written_cents": 6_000_000_000,
    "policy_count_in_force": 50_000,
    "confirmed_complaints_12mo": 300,
    "financial_stress_score": 80,
    "consumer_trend_score": 90,
}


def _cycle_examination_ready_to_abort(api) -> dict:
    """The single cycle-spawned examination, with an area, a collaboration and a RESPONDED call.

    The carrier's composite score of 90.20 clears the 40.00 default threshold, so
    the one-slot cycle selects it and spawns exactly one examination.
    """
    scenario = setup_cycle_with_selected_targets(
        carriers=[BOREAL],
        cycle_label="FY2026 Single Slot Cycle",
        target_slot_capacity=1,
    )
    assert len(scenario["examinations"]) == 1
    exam_id = scenario["exam_id"]
    examination = scenario["examination"]
    assert examination["cycle_id"] == scenario["cycle_id"]
    assert examination["mode"] == "ON_SITE"
    assert examination["lead_state_code"] == "NV"
    assert examination["fieldwork_start_date"] == "2026-09-01"
    assert examination["fieldwork_end_date"] == "2026-11-30"
    assert examination["status"] == "SCOPING"

    scope_area = add_scope_area(exam_id, "CLAIMS", population_size=4000, sample_size=10)
    lock_scope(exam_id)
    collaboration = open_collaboration(exam_id, STANDARD_PARTICIPATING_STATES)
    data_call = issue_data_call(
        scope_area["id"], records_requested=4000, response_due_date="2026-09-15"
    )
    responded = respond_to_data_call(
        data_call["id"], scenario["insurer_id"], records_received=4000
    )
    assert responded["status"] == "RESPONDED"

    scenario["scope_area"] = scope_area
    scenario["scope_area_id"] = scope_area["id"]
    scenario["collaboration"] = collaboration
    scenario["collaboration_id"] = collaboration["id"]
    scenario["data_call"] = data_call
    scenario["data_call_id"] = data_call["id"]
    return scenario


def test_abort_sweeps_every_descendant_of_the_examination(api):
    """Hops 1 and 2: the data call, the scope area and the collaboration are all swept.

    PRD §3.10: "The first hop records `abort_reason` and moves the examination to `ABORTED`. The second hop sweeps the descendants: every data call whose `status` is `ISSUED`, `OVERDUE` or `RESPONDED` moves to `CANCELLED`; every scope area whose `status` is `PLANNED`, `FIELDWORK` or `TESTED` moves to `CLOSED`; every criticism whose `status` is `ISSUED` or `RESPONDED` moves to `WITHDRAWN`; every corrective action plan whose `status` is `PROPOSED` or `REVISION_REQUESTED` moves to `REJECTED`; every consent order whose `status` is `DRAFT` moves to `VOIDED`; and a collaboration whose `status` is `LEAD_ASSIGNED` or `ACTIVE` moves to `DISSOLVED`, resetting every participant's `allocated_cents` and the collaboration's `allocated_total_cents` to 0."

    Design: Difficulty/transitive_cascade/abort_cascades_children_insurer_counters_and_closes_the_cycle
    """
    scenario = _cycle_examination_ready_to_abort(api)

    aborted = validate_success(
        api.abort_examination(scenario["exam_id"], abort_payload(), SUPERVISOR)
    )
    assert aborted["status"] == "ABORTED"
    assert aborted["abort_reason"]

    assert read_data_call(scenario["data_call_id"])["status"] == "CANCELLED"
    assert read_scope_area(scenario["scope_area_id"])["status"] == "CLOSED"

    collaboration = read_collaboration(scenario["collaboration_id"])
    assert collaboration["status"] == "DISSOLVED"
    assert collaboration["allocated_total_cents"] == 0
    assert all(
        participant["allocated_cents"] == 0
        for participant in collaboration["participating_states"]
    )


def test_abort_returns_the_carrier_counters_and_the_examiner_slot(api):
    """Hop 3: the carrier's open exam count drops and the cycle's slot is restored exactly.

    PRD §3.10: "Because the examination has become terminal, the carrier's `open_exam_count` is lowered by 1; the carrier's `pending_enforcement_exam_count` is lowered by 1 as well, but only when the examination's status immediately before the abort was `NEGOTIATION` or `ORDER_PENDING`; and when the examination carries a `cycle_id`, that cycle's `slots_committed` is lowered by 1, restoring `slots_available` exactly."
    PRD §2.10: "An abandoned examination gives its slot back exactly, leaving the ledger where it stood before the examination was opened."

    Design: Difficulty/transitive_cascade/abort_cascades_children_insurer_counters_and_closes_the_cycle
    """
    scenario = _cycle_examination_ready_to_abort(api)

    before_cycle = read_cycle(scenario["cycle_id"])
    assert before_cycle["selected_target_count"] == 1
    assert before_cycle["slots_committed"] == 1
    assert before_cycle["slots_available"] == 0
    assert before_cycle["status"] == "TARGETS_SELECTED"
    assert read_insurer(scenario["insurer_id"])["open_exam_count"] == 1

    validate_success(
        api.abort_examination(scenario["exam_id"], abort_payload(), SUPERVISOR)
    )

    insurer = read_insurer(scenario["insurer_id"])
    assert insurer["open_exam_count"] == 0
    assert insurer["pending_enforcement_exam_count"] == 0

    cycle = read_cycle(scenario["cycle_id"])
    assert cycle["slots_committed"] == 0
    assert cycle["slots_available"] == 1


def test_released_slot_closes_the_analysis_cycle(api):
    """Hop 4: the freed slot drives the cycle terminal without rewriting its history.

    PRD §3.10: "The fourth hop propagates that slot release upward: if the release leaves the cycle with `slots_committed` of 0 while its `selected_target_count` is 1 or more, the cycle advances `TARGETS_SELECTED → CLOSED` and stamps `closed_at`."
    PRD §3.2: "When the last examination attributed to the cycle reaches `PUBLISHED` or `ABORTED` — that is, when `slots_committed` falls to 0 while `selected_target_count` is 1 or more — the cycle advances `TARGETS_SELECTED → CLOSED`, stamps `closed_at` from the logical clock and increments its `version` by 1."

    Design: Difficulty/transitive_cascade/abort_cascades_children_insurer_counters_and_closes_the_cycle
    """
    scenario = _cycle_examination_ready_to_abort(api)
    assert read_cycle(scenario["cycle_id"])["status"] == "TARGETS_SELECTED"

    validate_success(
        api.abort_examination(scenario["exam_id"], abort_payload(), SUPERVISOR)
    )

    cycle = read_cycle(scenario["cycle_id"])
    assert cycle["status"] == "CLOSED"
    assert is_iso8601_timestamp(cycle["closed_at"])
    assert cycle["selected_target_count"] == 1


def test_second_abort_attempt_is_rejected_as_already_terminal(api):
    """A second abandonment lands on the terminal guard and changes nothing.

    PRD §3.10: "An examination already in `PUBLISHED` or `ABORTED` is rejected with `ERR_EXAM_ALREADY_TERMINAL`, which also covers a second abort attempt."

    Design: Difficulty/transitive_cascade/abort_cascades_children_insurer_counters_and_closes_the_cycle
    """
    scenario = _cycle_examination_ready_to_abort(api)

    validate_success(
        api.abort_examination(scenario["exam_id"], abort_payload(), SUPERVISOR)
    )
    after_first = read_examination(scenario["exam_id"])

    validate_error(
        api.abort_examination(scenario["exam_id"], abort_payload(), SUPERVISOR),
        ApiErrorId.ERR_EXAM_ALREADY_TERMINAL.value,
        409,
    )

    unchanged = read_examination(scenario["exam_id"])
    assert unchanged["status"] == "ABORTED"
    assert unchanged["version"] == after_first["version"]

    cycle = read_cycle(scenario["cycle_id"])
    assert cycle["status"] == "CLOSED"
    assert cycle["slots_committed"] == 0
    assert cycle["slots_available"] == 1
