"""Drawing samples, sizing them, testing items, the two conclusion arms, exception
evaluation and the compensating void."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_audit_sample,
    conclude_sample,
    control_version,
    draw_sample,
    list_exceptions,
    read_control,
    read_engagement,
    read_readiness_summary,
    record_items,
    review_evidence,
    set_clock,
    setup_engagement_at,
    setup_sample_in_testing,
    submit_evidence,
    validate_error,
    validate_paginated,
    validate_success,
)

CL_HEADERS = TEST_USERS["compliance_lead_headers"]
AUD_HEADERS = TEST_USERS["auditor_headers"]

SOC1_CRITERIA = [
    {
        "criterion_code": "CC1.1",
        "category": "SECURITY",
        "title": "Control environment",
        "min_primary_controls": 1,
        "applies_to_report_types": ("SOC_1_TYPE_2",),
    }
]


def test_short_sample_and_over_full_sample_report_distinct_errors(api):
    """PRD 3.6: "Conclusion is refused unless `items_recorded` equals `sample_size`, with a
    short sample rejected as `ERR_SAMPLE_INCOMPLETE`."
    PRD 3.6: "Once `items_recorded` has reached `sample_size` no further item may be
    recorded, and the attempt is `ERR_SAMPLE_FULL`."

    Design: Corner/errors/corner_sample_incomplete_then_sample_full_are_separate_errors
    """
    scenario = setup_sample_in_testing(["PASS"], client_name="Counting")
    sample_id = scenario["sample"]["id"]
    assert scenario["sample"]["sample_size"] == 4

    validate_error(
        api.conclude_audit_sample(sample_id, AUD_HEADERS),
        ApiErrorId.ERR_SAMPLE_INCOMPLETE.value,
        409,
    )

    record_items(sample_id, ["PASS", "PASS", "PASS"])

    validate_error(
        api.record_sample_item(sample_id, {"outcome": "PASS"}, AUD_HEADERS),
        ApiErrorId.ERR_SAMPLE_FULL.value,
        409,
    )

    stored = validate_success(api.get_audit_sample(sample_id, AUD_HEADERS))
    assert_audit_sample(stored)
    assert stored["sample_size"] == 4
    assert stored["items_recorded"] == 4
    assert stored["items_passed"] == 4
    assert stored["items_failed"] == 0
    assert stored["status"] == "TESTING"


def test_sample_window_reaching_past_the_observation_period_is_rejected(api):
    """PRD 3.6: "Draws are permitted only while the engagement is in `OBSERVATION` or
    `FIELDWORK`; the control must be in scope and not carved out, else
    `ERR_CONTROL_OUT_OF_SCOPE`; the tested window must sit inside the examination window,
    with `period_start` at or after the engagement's `observation_period_start` and
    `period_end` at or before its `observation_period_end`, else
    `ERR_SAMPLE_WINDOW_INVALID`; and every evidence request of the control must already be
    settled — `ACCEPTED`, `MISSED` or `WAIVED` — with any request still in `SCHEDULED`,
    `SUBMITTED` or `REJECTED` rejected as `ERR_EVIDENCE_NOT_SETTLED`."
    PRD 2.7: "**Sample window inside the observation period**, else
    `ERR_SAMPLE_WINDOW_INVALID` (409)."

    Design: Corner/errors/corner_sample_window_outside_observation_period_rejected
    """
    scenario = setup_engagement_at(phase="OBSERVATION", client_name="Out Of Window")
    control = scenario["controls"]["S-01"]

    response = api.draw_audit_sample(
        {
            "control_id": control["id"],
            "period_start": "2026-09-01T00:00:00.000Z",
            "period_end": "2026-12-31T00:00:00.000Z",
            "expected_control_version": control_version(control["id"]),
        },
        AUD_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_SAMPLE_WINDOW_INVALID.value, 409)

    _, meta = validate_paginated(
        api.list_audit_samples(AUD_HEADERS, params={"control_id": control["id"]})
    )
    assert meta["total_count"] == 0, "The rejected draw must store no sample"
    assert read_control(control["id"])["operating_status"] == "IN_OBSERVATION"
    assert validate_success(
        api.get_evidence_request(scenario["evidence"]["S-01"]["id"], CL_HEADERS)
    )["status"] == "SCHEDULED"


def test_draw_carrying_a_stale_control_version_is_rejected(api):
    """PRD 2.5: "Drawing an audit sample — `POST /soc/audit-samples` — requires a
    non-optional `expected_control_version` field carrying the `version` of the target
    control as the client last observed it. A mismatch with the control's current `version`
    is rejected with `ERR_STALE_CONTROL_VERSION` (HTTP 412)."
    PRD 2.4: "Most resources additionally carry `updated_at`, refreshed on every mutation
    of that row, and `version`, an integer that starts at 1 when the row is created and
    increases by exactly one on every mutation."

    Design: Corner/cross_cutting_complexity_layers/corner_occ_stale_control_version_rejects_sample_draw
    """
    scenario = setup_engagement_at(phase="OBSERVATION", client_name="Version Drift")
    control = scenario["controls"]["S-01"]
    set_clock("2026-10-05T00:00:00.000Z")

    response = api.draw_audit_sample(
        {
            "control_id": control["id"],
            "period_start": "2026-09-01T00:00:00.000Z",
            "period_end": "2026-11-30T00:00:00.000Z",
            "expected_control_version": 1,
        },
        AUD_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_STALE_CONTROL_VERSION.value, 412)

    _, meta = validate_paginated(
        api.list_audit_samples(AUD_HEADERS, params={"control_id": control["id"]})
    )
    assert meta["total_count"] == 0
    assert control_version(control["id"]) > 1, (
        "Mapping, ownership and design approval have all mutated the control since creation"
    )
    assert validate_success(
        api.get_evidence_request(scenario["evidence"]["S-01"]["id"], CL_HEADERS)
    )["status"] == "SCHEDULED"


def build_two_automated_controls():
    """A SOC_1_TYPE_2 engagement in FIELDWORK with a DAILY / AUTOMATED / MODERATE control
    over a population of 100 and a WEEKLY / AUTOMATED / LOW control over a population of 4."""
    return setup_engagement_at(
        phase="FIELDWORK",
        client_name="Contoso",
        report_type="SOC_1_TYPE_2",
        criteria=SOC1_CRITERIA,
        controls=[
            {
                "control_ref": "D-01",
                "title": "Daily batch reconciliation",
                "frequency": "DAILY",
                "automation": "AUTOMATED",
                "risk_rating": "MODERATE",
                "population_size": 100,
                "owner": "own-1",
            },
            {
                "control_ref": "W-01",
                "title": "Weekly vulnerability scan",
                "frequency": "WEEKLY",
                "automation": "AUTOMATED",
                "risk_rating": "LOW",
                "population_size": 4,
                "owner": "own-2",
            },
        ],
    )


def test_sample_size_composes_automation_risk_and_the_report_type_addendum(api):
    """PRD 3.6: "Start from the frequency base: 25 for a `DAILY` control, 15 for `WEEKLY`,
    5 for `MONTHLY`, 2 for `QUARTERLY`, 1 for `ANNUAL` and 8 for `ADHOC`."
    PRD 3.6: "If the control's `automation` is `AUTOMATED`, that base shrinks to 40 percent
    of itself rounded upward to the next whole number, but never below 1 — take the larger
    of 1 and that rounded-up value."
    PRD 3.6: "Add the risk bump: nothing for a `LOW` control, 2 for a `MODERATE` one and 5
    for a `HIGH` one. If the engagement's `report_type` is `SOC_1_TYPE_2`, add a further 1."
    PRD 3.6: "The deviation budget, `allowed_deviations`, is 10 percent of `sample_size`
    truncated downward to a whole number."

    Design: Difficulty/combinatorial_formula/sample_size_nested_min_max_with_automation_and_report_type_branches
    """
    scenario = build_two_automated_controls()
    daily = scenario["controls"]["D-01"]

    sample = draw_sample(daily["id"])
    assert sample["population_size_snapshot"] == 100
    assert sample["sample_size"] == 13, (
        "25 shrinks to 10, plus 2 for MODERATE and 1 for the SOC 1 addendum gives 13, "
        f"got {sample['sample_size']}"
    )
    assert sample["allowed_deviations"] == 1, "floor(13 * 0.10) is 1"
    assert sample["zero_population"] is False
    assert sample["status"] == "DRAWN"


def test_sample_size_is_capped_by_the_control_population(api):
    """PRD 3.6: "The result is then capped by the population: `sample_size` is the smaller
    of that computed figure and the control's `population_size`, which is copied onto the
    sample as `population_size_snapshot` at draw time so that later changes to the control
    never retro-alter the sample."
    PRD 3.6: "The deviation budget, `allowed_deviations`, is 10 percent of `sample_size`
    truncated downward to a whole number."

    Design: Difficulty/combinatorial_formula/sample_size_nested_min_max_with_automation_and_report_type_branches
    """
    scenario = build_two_automated_controls()
    weekly = scenario["controls"]["W-01"]

    sample = draw_sample(weekly["id"])
    assert sample["population_size_snapshot"] == 4
    assert sample["sample_size"] == 4, (
        "15 shrinks to 6, plus 0 for LOW and 1 for the SOC 1 addendum gives a raw 7 that "
        f"the population of 4 caps, got {sample['sample_size']}"
    )
    assert sample["allowed_deviations"] == 0, "floor(4 * 0.10) is 0"
    assert sample["status"] == "DRAWN"


def build_zero_population_scenario():
    """A SOC_1_TYPE_2 engagement in FIELDWORK whose only control has a population of 0."""
    return setup_engagement_at(
        phase="FIELDWORK",
        client_name="Wingtip",
        report_type="SOC_1_TYPE_2",
        criteria=SOC1_CRITERIA,
        controls=[
            {
                "control_ref": "Z-01",
                "title": "Emergency change review",
                "frequency": "ADHOC",
                "automation": "MANUAL",
                "risk_rating": "LOW",
                "population_size": 0,
            }
        ],
    )


def test_zero_population_sample_is_created_already_concluded_clean(api):
    """PRD 3.6: "A sample drawn against a control whose population is 0 is a special case:
    `zero_population` is true, `sample_size` and `allowed_deviations` are both 0,
    `deviation_rate` is 0.0000 and `projected_failures` is 0.00, and the row is minted
    **directly into `CONCLUDED_CLEAN` inside the create call, never passing through
    `TESTING`**."

    Design: Difficulty/boundary_precision_check/zero_population_control_mints_sample_directly_into_concluded_clean
    """
    scenario = build_zero_population_scenario()
    control = scenario["controls"]["Z-01"]

    sample = validate_success(
        api.draw_audit_sample(
            {
                "control_id": control["id"],
                "period_start": "2026-09-01T00:00:00.000Z",
                "period_end": "2026-11-30T00:00:00.000Z",
                "expected_control_version": control_version(control["id"]),
            },
            AUD_HEADERS,
        ),
        201,
    )
    assert sample["population_size_snapshot"] == 0
    assert sample["zero_population"] is True
    assert sample["sample_size"] == 0
    assert sample["allowed_deviations"] == 0
    assert sample["items_recorded"] == 0
    assert sample["deviation_rate"] == 0.0000
    assert sample["projected_failures"] == 0.00
    assert sample["status"] == "CONCLUDED_CLEAN"


def test_zero_population_conclusion_carries_the_control_to_tested_effective(api):
    """PRD 3.6: "That immediate conclusion moves the control `IN_OBSERVATION →
    TESTED_EFFECTIVE` and recomputes the engagement's attestation coverage percentage."
    PRD 3.3: "Under the **attestation view**, an in-scope criterion counts as covered only
    when the number of criteria mappings that are `ACTIVE`, that have `mapping_type`
    `PRIMARY`, that name this criterion, and whose control belongs to this engagement with
    `in_scope` true, `design_status` exactly `DESIGN_APPROVED` and `operating_status`
    exactly `TESTED_EFFECTIVE`, is greater than or equal to that criterion's
    `min_primary_controls`."

    Design: Difficulty/boundary_precision_check/zero_population_control_mints_sample_directly_into_concluded_clean
    """
    scenario = build_zero_population_scenario()
    control = scenario["controls"]["Z-01"]

    draw_sample(control["id"])

    assert read_control(control["id"])["operating_status"] == "TESTED_EFFECTIVE"
    engagement = read_engagement(scenario["engagement_id"])
    assert engagement["criteria_coverage_pct_attestation"] == 100.00, (
        "The only in-scope criterion is now covered under the attestation view"
    )


def test_draw_with_an_unsettled_evidence_request_is_rejected(api):
    """PRD 3.6: "Draws are permitted only while the engagement is in `OBSERVATION` or
    `FIELDWORK`; the control must be in scope and not carved out, else
    `ERR_CONTROL_OUT_OF_SCOPE`; the tested window must sit inside the examination window,
    with `period_start` at or after the engagement's `observation_period_start` and
    `period_end` at or before its `observation_period_end`, else
    `ERR_SAMPLE_WINDOW_INVALID`; and every evidence request of the control must already be
    settled — `ACCEPTED`, `MISSED` or `WAIVED` — with any request still in `SCHEDULED`,
    `SUBMITTED` or `REJECTED` rejected as `ERR_EVIDENCE_NOT_SETTLED`."

    Design: Difficulty/cross_entity_state_dependency/sample_draw_requires_every_evidence_request_settled
    """
    scenario = setup_engagement_at(phase="OBSERVATION", client_name="Cascade")
    control = scenario["controls"]["S-01"]
    set_clock("2026-10-05T00:00:00.000Z")

    response = api.draw_audit_sample(
        {
            "control_id": control["id"],
            "period_start": "2026-09-01T00:00:00.000Z",
            "period_end": "2026-11-30T00:00:00.000Z",
            "expected_control_version": control_version(control["id"]),
        },
        AUD_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_EVIDENCE_NOT_SETTLED.value, 409)

    _, meta = validate_paginated(
        api.list_audit_samples(AUD_HEADERS, params={"control_id": control["id"]})
    )
    assert meta["total_count"] == 0


def test_the_same_draw_succeeds_once_the_evidence_is_accepted(api):
    """PRD 3.6: "The draw stamps `drawn_by_user_id` from the header and `drawn_at` from the
    logical clock, sets `supersedes_audit_sample_id` to the identifier of the prior
    non-voided sample on the same control (null when there is none) and voids that prior
    sample through that supersession, and increments the control's `version` by one."
    PRD 3.4: "`SUBMITTED → ACCEPTED` stamps `reviewed_at` and `reviewed_by_user_id` and
    increases the control's `evidence_accepted_count` by one."

    Design: Difficulty/cross_entity_state_dependency/sample_draw_requires_every_evidence_request_settled
    """
    scenario = setup_engagement_at(phase="OBSERVATION", client_name="Cascade")
    control = scenario["controls"]["S-01"]
    request_id = scenario["evidence"]["S-01"]["id"]
    set_clock("2026-10-05T00:00:00.000Z")

    rejected = api.draw_audit_sample(
        {
            "control_id": control["id"],
            "period_start": "2026-09-01T00:00:00.000Z",
            "period_end": "2026-11-30T00:00:00.000Z",
            "expected_control_version": control_version(control["id"]),
        },
        AUD_HEADERS,
    )
    assert rejected.status_code == 409

    submit_evidence(request_id, "own-1", "art-1")
    review_evidence(request_id, "ACCEPT", "rev-1")
    assert validate_success(api.get_evidence_request(request_id, CL_HEADERS))["status"] == "ACCEPTED"

    sample = validate_success(
        api.draw_audit_sample(
            {
                "control_id": control["id"],
                "period_start": "2026-09-01T00:00:00.000Z",
                "period_end": "2026-11-30T00:00:00.000Z",
                "expected_control_version": control_version(control["id"]),
            },
            AUD_HEADERS,
        ),
        201,
    )
    assert sample["sample_size"] == 4
    assert sample["allowed_deviations"] == 0
    assert sample["status"] == "DRAWN"
    assert sample["supersedes_audit_sample_id"] is None

    _, meta = validate_paginated(
        api.list_audit_samples(AUD_HEADERS, params={"control_id": control["id"]})
    )
    assert meta["total_count"] == 1


def build_budget_boundary_scenario():
    """A MONTHLY / MANUAL / HIGH control over a population of 40 gives sample_size 10 and
    allowed_deviations 1; nine passes and exactly one failure are recorded."""
    return setup_sample_in_testing(
        ["PASS"] * 9 + [("FAIL", "One reviewer signature missing")],
        client_name="Coho",
        controls=[
            {
                "control_ref": "S-01",
                "title": "Monthly access review",
                "frequency": "MONTHLY",
                "automation": "MANUAL",
                "risk_rating": "HIGH",
                "population_size": 40,
            }
        ],
    )


def test_failures_equal_to_the_budget_take_the_clean_arm(api):
    """PRD 3.6: "The **clean arm** is taken when `items_failed` is less than or equal to
    `allowed_deviations`. The sample moves `TESTING → CONCLUDED_CLEAN`, the control moves
    `IN_OBSERVATION → TESTED_EFFECTIVE` with `tested_item_count` recomputed as the sum of
    `items_recorded` across the control's non-voided samples, and the engagement's
    attestation coverage percentage and `readiness_score` are recomputed."
    PRD 3.6: "Both arms first compute `deviation_rate` — exactly 0.0000 when `sample_size`
    is 0, and otherwise `items_failed` divided by `sample_size`, rounded half up to four
    decimal places — and then stamp `projected_failures` as that rounded rate multiplied by
    `population_size_snapshot`, rounded half up to two decimal places."

    Design: Difficulty/boundary_precision_check/deviation_equal_to_allowed_budget_concludes_clean_not_exceptions
    """
    scenario = build_budget_boundary_scenario()
    sample_id = scenario["sample"]["id"]
    assert scenario["sample"]["sample_size"] == 10
    assert scenario["sample"]["allowed_deviations"] == 1

    concluded = conclude_sample(sample_id)
    assert concluded["items_recorded"] == 10
    assert concluded["items_failed"] == 1
    assert concluded["status"] == "CONCLUDED_CLEAN", (
        "The exception arm requires strictly more failures than the budget allows"
    )
    assert concluded["deviation_rate"] == 0.1000
    assert concluded["projected_failures"] == 4.00
    assert read_control(scenario["control"]["id"])["operating_status"] == "TESTED_EFFECTIVE"


def test_clean_arm_at_the_budget_creates_no_exception_and_leaves_the_posture_open(api):
    """PRD 3.6: "No exception row is created and `open_exception_count` is unchanged."
    PRD 2.8: "Failing all three, the engagement is `RESTRICTED` when `gap_debt_points` is
    11.00 or more, or `open_exception_count` is 1 or more. Otherwise it is `OPEN`."

    Design: Difficulty/boundary_precision_check/deviation_equal_to_allowed_budget_concludes_clean_not_exceptions
    """
    scenario = build_budget_boundary_scenario()
    conclude_sample(scenario["sample"]["id"])

    _, meta = validate_paginated(
        api.list_audit_exceptions(
            AUD_HEADERS, params={"audit_sample_id": scenario["sample"]["id"]}
        )
    )
    assert meta["total_count"] == 0, "The clean arm creates no exception rows"

    engagement = read_engagement(scenario["engagement_id"])
    assert engagement["open_exception_count"] == 0
    assert engagement["gap_debt_points"] == 0.00
    assert engagement["gap_posture"] == "OPEN"


def build_one_failure_scenario(failure=("FAIL", "No approval record"), client_name="Northwind"):
    """A QUARTERLY / MANUAL / MODERATE control over a population of 20 gives sample_size 4
    and allowed_deviations 0; three passes and one deviation are recorded."""
    return setup_sample_in_testing(["PASS", "PASS", "PASS", failure], client_name=client_name)


def test_conclusion_stamps_the_plain_proportional_population_projection(api):
    """PRD 3.6: "Both arms first compute `deviation_rate` — exactly 0.0000 when
    `sample_size` is 0, and otherwise `items_failed` divided by `sample_size`, rounded half
    up to four decimal places — and then stamp `projected_failures` as that rounded rate
    multiplied by `population_size_snapshot`, rounded half up to two decimal places."
    PRD 3.6: "This sample-level projection adds no allowance; it is the plain proportional
    effect the auditor reports."

    Design: Difficulty/dual_variant_calc/exception_projection_deviation_rate_view_vs_upper_precision_view
    """
    scenario = build_one_failure_scenario(("FAIL", "Approval ticket missing"))
    concluded = conclude_sample(scenario["sample"]["id"])

    assert concluded["sample_size"] == 4
    assert concluded["allowed_deviations"] == 0
    assert concluded["items_failed"] == 1
    assert concluded["deviation_rate"] == 0.2500
    assert concluded["projected_failures"] == 5.00, (
        f"0.2500 of a population of 20 is 5.00, got {concluded['projected_failures']}"
    )
    assert concluded["status"] == "CONCLUDED_EXCEPTIONS"


def test_exception_evaluation_stamps_the_ceiling_plus_precision_allowance(api):
    """PRD 3.6: "Both dispositions first stamp the exception-level projection, which is
    deliberately more conservative than the sample-level one: `projected_failures_upper` is
    the rounded `deviation_rate` multiplied by `population_size_snapshot`, **rounded upward
    to the next whole number**, plus a precision allowance keyed to the control's
    `risk_rating` — 0 for `LOW`, 1 for `MODERATE`, 2 for `HIGH`."
    PRD 3.6: "Both dispositions also stamp `pervasive_recommended`, which is true exactly
    when `projected_failures_upper` is strictly greater than 20 percent of
    `population_size_snapshot`."
    PRD 3.6: "`UNEVALUATED → ISOLATED` sets `severity_assigned` to `MODERATE` and stops
    there; the gap raised by the cascade keeps its severity `HIGH`, because an isolated
    disposition never de-escalates a gap that already exists."

    Design: Difficulty/dual_variant_calc/exception_projection_deviation_rate_view_vs_upper_precision_view
    """
    scenario = build_one_failure_scenario(("FAIL", "Approval ticket missing"))
    conclude_sample(scenario["sample"]["id"])
    exception_row = list_exceptions(scenario["sample"]["id"])[0]

    evaluated = validate_success(
        api.evaluate_audit_exception(
            exception_row["id"],
            {"disposition": "ISOLATED", "evaluation_note": "Single missing ticket"},
            AUD_HEADERS,
        )
    )
    assert evaluated["projected_failures_upper"] == 6, (
        "ceil(0.2500 * 20) is 5 and the MODERATE allowance adds 1, "
        f"got {evaluated['projected_failures_upper']}"
    )
    assert evaluated["pervasive_recommended"] is True, "6 is strictly greater than 20% of 20"
    assert evaluated["disposition"] == "ISOLATED"
    assert evaluated["severity_assigned"] == "MODERATE"


def test_concluding_with_exceptions_moves_only_the_operating_track(api):
    """PRD 3.3: "A control carries **two independent state dimensions on the same row**."
    PRD 3.3: "The two advance on disjoint triggers and neither is a precondition of the
    other's forward edges, with a single exception noted in §3.4: leaving `NOT_TESTED`
    reads the design track."
    PRD 3.6: "Creating those rows moves the control `IN_OBSERVATION → TESTED_EXCEPTION`,
    recomputes `tested_item_count`, and raises the engagement's `open_exception_count` by
    the number of rows created."

    Design: Difficulty/non_linear_state_machine/control_design_and_operating_dimensions_advance_on_disjoint_triggers
    """
    scenario = build_one_failure_scenario()
    control_id = scenario["control"]["id"]

    before = read_control(control_id)
    assert before["design_status"] == "DESIGN_APPROVED"
    assert before["operating_status"] == "IN_OBSERVATION"

    conclude_sample(scenario["sample"]["id"])

    after = read_control(control_id)
    assert after["design_status"] == "DESIGN_APPROVED", (
        "Concluding the sample must leave the design track untouched"
    )
    assert after["operating_status"] == "TESTED_EXCEPTION"


def test_a_pervasive_evaluation_moves_only_the_design_track(api):
    """PRD 3.6: "`UNEVALUATED → PERVASIVE` sets `severity_assigned` to `CRITICAL` and moves
    the control `DESIGN_APPROVED → DESIGN_DEFICIENT`; that design move escalates the gap
    whose `audit_exception_id` names this exception from severity `HIGH` to severity
    `CRITICAL`; and that escalation drives the recompute of `base_debt_points`,
    `gap_debt_points` and `gap_posture`."
    PRD 3.3: "The two advance on disjoint triggers and neither is a precondition of the
    other's forward edges, with a single exception noted in §3.4: leaving `NOT_TESTED`
    reads the design track."

    Design: Difficulty/non_linear_state_machine/control_design_and_operating_dimensions_advance_on_disjoint_triggers
    """
    scenario = build_one_failure_scenario(("FAIL", "Systemic approval breakdown"))
    control_id = scenario["control"]["id"]
    conclude_sample(scenario["sample"]["id"])
    exception_row = list_exceptions(scenario["sample"]["id"])[0]

    evaluated = validate_success(
        api.evaluate_audit_exception(
            exception_row["id"],
            {"disposition": "PERVASIVE", "evaluation_note": "Systemic approval breakdown"},
            AUD_HEADERS,
        )
    )
    assert evaluated["disposition"] == "PERVASIVE"
    assert evaluated["severity_assigned"] == "CRITICAL"

    after = read_control(control_id)
    assert after["design_status"] == "DESIGN_DEFICIENT"
    assert after["operating_status"] == "TESTED_EXCEPTION", (
        "The pervasive finding moves the design track while the operating track stands still"
    )


def build_branch_scenario():
    """One engagement in FIELDWORK carrying two controls: S-01 (MODERATE, sample_size 4)
    with four passes recorded, and S-02 (LOW, sample_size 2) with one pass and one failure."""
    scenario = setup_engagement_at(
        phase="FIELDWORK",
        client_name="Northwind",
        controls=[
            {"control_ref": "S-01", "title": "Change approvals", "owner": "own-1"},
            {
                "control_ref": "S-02",
                "title": "Quarterly vendor review",
                "risk_rating": "LOW",
                "owner": "own-2",
            },
        ],
    )
    clean_sample = draw_sample(scenario["controls"]["S-01"]["id"])
    record_items(clean_sample["id"], ["PASS", "PASS", "PASS", "PASS"])
    exception_sample = draw_sample(scenario["controls"]["S-02"]["id"])
    record_items(
        exception_sample["id"], ["PASS", ("FAIL", "Vendor review not performed")]
    )
    scenario["clean_sample"] = clean_sample
    scenario["exception_sample"] = exception_sample
    return scenario


def test_the_clean_arm_produces_no_exception_rows(api):
    """PRD 3.6: "The **clean arm** is taken when `items_failed` is less than or equal to
    `allowed_deviations`. The sample moves `TESTING → CONCLUDED_CLEAN`, the control moves
    `IN_OBSERVATION → TESTED_EFFECTIVE` with `tested_item_count` recomputed as the sum of
    `items_recorded` across the control's non-voided samples, and the engagement's
    attestation coverage percentage and `readiness_score` are recomputed."
    PRD 3.6: "No exception row is created and `open_exception_count` is unchanged."

    Design: Difficulty/non_linear_state_machine/audit_sample_branch_yields_divergent_side_effect_sets
    """
    scenario = build_branch_scenario()
    concluded = conclude_sample(scenario["clean_sample"]["id"])

    assert concluded["status"] == "CONCLUDED_CLEAN"
    assert concluded["sample_size"] == 4
    assert concluded["items_failed"] == 0
    assert concluded["projected_failures"] == 0.00
    assert read_control(scenario["controls"]["S-01"]["id"])["operating_status"] == "TESTED_EFFECTIVE"

    _, meta = validate_paginated(
        api.list_audit_exceptions(
            AUD_HEADERS, params={"audit_sample_id": scenario["clean_sample"]["id"]}
        )
    )
    assert meta["total_count"] == 0
    assert read_engagement(scenario["engagement_id"])["open_exception_count"] == 0


def test_the_exception_arm_adds_a_gap_and_restricts_the_engagement(api):
    """PRD 3.6: "The **exception arm** is taken when `items_failed` is strictly greater than
    `allowed_deviations`, and its side-effect set is strictly larger."
    PRD 3.6: "The control entering `TESTED_EXCEPTION` in turn creates exactly one gap, with
    `source` `EXCEPTION_CASCADE`, severity `HIGH`, this control as its `control_id`, and
    `audit_exception_id` pointing at the created exception with the lowest `item_ordinal`."
    PRD 2.8: "Failing all three, the engagement is `RESTRICTED` when `gap_debt_points` is
    11.00 or more, or `open_exception_count` is 1 or more. Otherwise it is `OPEN`."

    Design: Difficulty/non_linear_state_machine/audit_sample_branch_yields_divergent_side_effect_sets
    """
    scenario = build_branch_scenario()
    conclude_sample(scenario["clean_sample"]["id"])
    concluded = conclude_sample(scenario["exception_sample"]["id"])

    assert concluded["status"] == "CONCLUDED_EXCEPTIONS"
    assert concluded["sample_size"] == 2
    assert concluded["allowed_deviations"] == 0
    assert concluded["items_failed"] == 1
    assert concluded["deviation_rate"] == 0.5000
    assert concluded["projected_failures"] == 10.00
    assert read_control(scenario["controls"]["S-02"]["id"])["operating_status"] == "TESTED_EXCEPTION"

    _, exception_meta = validate_paginated(
        api.list_audit_exceptions(
            AUD_HEADERS, params={"audit_sample_id": scenario["exception_sample"]["id"]}
        )
    )
    assert exception_meta["total_count"] == 1

    gaps, gap_meta = validate_paginated(
        api.list_gaps(
            CL_HEADERS,
            params={
                "engagement_id": scenario["engagement_id"],
                "source": "EXCEPTION_CASCADE",
            },
        )
    )
    assert gap_meta["total_count"] == 1
    assert gaps[0]["severity"] == "HIGH"
    assert gaps[0]["control_id"] == scenario["controls"]["S-02"]["id"]

    engagement = read_engagement(scenario["engagement_id"])
    assert engagement["open_exception_count"] == 1
    assert engagement["base_debt_points"] == 8
    assert engagement["gap_debt_points"] == 8.00
    assert engagement["gap_posture"] == "RESTRICTED"


def test_conclusion_creates_the_exception_row_and_advances_the_control(api):
    """PRD 3.6: "One audit exception row is created for every recorded item whose outcome
    was `FAIL` or `NOT_PROVIDED`, in ascending `item_ordinal` order, each carrying
    `audit_sample_id`, the control's identifier denormalised as `control_id`, the breaching
    item's `item_ordinal`, that item's reason copied into `failure_reason`, a `disposition`
    of `UNEVALUATED`, a null `severity_assigned`, a `projected_failures_upper` of 0 and a
    `pervasive_recommended` of false, with `evaluated_by_user_id` and `evaluated_at` null."
    PRD 3.6: "The item's ordinal is the sample's `items_recorded` value as it stood
    immediately before the call, so ordinals are zero-based and consecutive."
    PRD 3.6: "Creating those rows moves the control `IN_OBSERVATION → TESTED_EXCEPTION`,
    recomputes `tested_item_count`, and raises the engagement's `open_exception_count` by
    the number of rows created."

    Design: Difficulty/transitive_cascade/sample_conclusion_cascades_exception_to_control_to_gap_to_posture
    """
    scenario = build_one_failure_scenario()
    concluded = conclude_sample(scenario["sample"]["id"])
    assert concluded["status"] == "CONCLUDED_EXCEPTIONS"

    rows, meta = validate_paginated(
        api.list_audit_exceptions(
            AUD_HEADERS, params={"audit_sample_id": scenario["sample"]["id"]}
        )
    )
    assert meta["total_count"] == 1
    exception_row = rows[0]
    assert exception_row["control_id"] == scenario["control"]["id"]
    assert exception_row["item_ordinal"] == 3, (
        "The fourth recorded item carries the zero-based ordinal 3"
    )
    assert exception_row["disposition"] == "UNEVALUATED"

    assert read_control(scenario["control"]["id"])["operating_status"] == "TESTED_EXCEPTION"
    assert read_engagement(scenario["engagement_id"])["open_exception_count"] == 1


def test_the_cascade_gap_points_back_at_the_exception_and_moves_the_posture(api):
    """PRD 3.6: "The control entering `TESTED_EXCEPTION` in turn creates exactly one gap,
    with `source` `EXCEPTION_CASCADE`, severity `HIGH`, this control as its `control_id`,
    and `audit_exception_id` pointing at the created exception with the lowest
    `item_ordinal`."
    PRD 3.6: "That gap creation in turn drives the recompute of `base_debt_points`,
    `gap_debt_points` and `gap_posture`. Four levels of cascade, all inside one request."

    Design: Difficulty/transitive_cascade/sample_conclusion_cascades_exception_to_control_to_gap_to_posture
    """
    scenario = build_one_failure_scenario()
    conclude_sample(scenario["sample"]["id"])
    exception_row = list_exceptions(scenario["sample"]["id"])[0]

    gaps, meta = validate_paginated(
        api.list_gaps(
            CL_HEADERS,
            params={
                "engagement_id": scenario["engagement_id"],
                "source": "EXCEPTION_CASCADE",
            },
        )
    )
    assert meta["total_count"] == 1
    gap = gaps[0]
    assert gap["severity"] == "HIGH"
    assert gap["status"] == "OPEN"
    assert gap["control_id"] == scenario["control"]["id"]
    assert gap["audit_exception_id"] == exception_row["id"]

    engagement = read_engagement(scenario["engagement_id"])
    assert engagement["base_debt_points"] == 8
    assert engagement["gap_debt_points"] == 8.00
    assert engagement["gap_posture"] == "RESTRICTED"


def test_voiding_the_sample_returns_the_open_exception_count_to_zero(api):
    """PRD 3.6: "Voiding a `CONCLUDED_EXCEPTIONS` sample does more: every exception of that
    sample moves to `disposition` `VOIDED` with `severity_assigned` reset to null, every gap
    whose `audit_exception_id` names one of those exceptions moves to `WITHDRAWN` with
    `debt_points` 0, the control moves `TESTED_EXCEPTION → IN_OBSERVATION` with
    `tested_item_count` recomputed, and `open_exception_count`, `base_debt_points`,
    `gap_debt_points` and `gap_posture` are all recomputed — leaving `open_exception_count`
    back at its pre-conclusion value."
    PRD 3.6: "Recording increases `items_recorded` by one and increments the matching tally:
    `items_passed` for a pass, `items_failed` for both a failure and a not-provided outcome
    — a missing artifact is treated as a deviation — and `items_not_provided` additionally
    for the not-provided case, which is therefore a subset of `items_failed`."

    Design: Difficulty/compensating_invariant/sample_void_conserves_engagement_open_exception_count
    """
    scenario = build_one_failure_scenario(
        ("NOT_PROVIDED", "Ticket export unavailable"), client_name="Elmwood"
    )
    conclude_sample(scenario["sample"]["id"])

    middle = read_readiness_summary(scenario["engagement_id"])
    assert middle["open_exception_count"] == 1
    assert middle["gap_debt_points"] == 8.00
    assert middle["gap_posture"] == "RESTRICTED"

    voided = validate_success(
        api.void_audit_sample(
            scenario["sample"]["id"], {"reason": "Population extract was wrong"}, AUD_HEADERS
        )
    )
    assert voided["status"] == "VOIDED"
    assert voided["items_not_provided"] == 1
    assert voided["items_failed"] == 1

    after = read_readiness_summary(scenario["engagement_id"])
    assert after["open_exception_count"] == 0, (
        "Voiding must return the live exception count to its pre-conclusion value"
    )
    assert after["gap_debt_points"] == 0.00
    assert after["gap_posture"] == "OPEN"


def test_voiding_withdraws_the_cascade_gap_and_restores_the_control(api):
    """PRD 3.6: "Voiding a `CONCLUDED_EXCEPTIONS` sample does more: every exception of that
    sample moves to `disposition` `VOIDED` with `severity_assigned` reset to null, every gap
    whose `audit_exception_id` names one of those exceptions moves to `WITHDRAWN` with
    `debt_points` 0, the control moves `TESTED_EXCEPTION → IN_OBSERVATION` with
    `tested_item_count` recomputed, and `open_exception_count`, `base_debt_points`,
    `gap_debt_points` and `gap_posture` are all recomputed — leaving `open_exception_count`
    back at its pre-conclusion value."
    PRD 3.6: "Exceptions reach `VOIDED` only this way, from any of `UNEVALUATED`,
    `ISOLATED` or `PERVASIVE`, and never by direct request."

    Design: Difficulty/compensating_invariant/sample_void_conserves_engagement_open_exception_count
    """
    scenario = build_one_failure_scenario(
        ("NOT_PROVIDED", "Ticket export unavailable"), client_name="Elmwood"
    )
    conclude_sample(scenario["sample"]["id"])
    exception_row = list_exceptions(scenario["sample"]["id"])[0]

    validate_success(
        api.void_audit_sample(
            scenario["sample"]["id"], {"reason": "Population extract was wrong"}, AUD_HEADERS
        )
    )

    exception_after = validate_success(
        api.get_audit_exception(exception_row["id"], AUD_HEADERS)
    )
    assert exception_after["disposition"] == "VOIDED"
    assert exception_after["severity_assigned"] is None

    control_after = read_control(scenario["control"]["id"])
    assert control_after["operating_status"] == "IN_OBSERVATION"
    assert control_after["tested_item_count"] == 0

    gaps, meta = validate_paginated(
        api.list_gaps(
            CL_HEADERS,
            params={
                "engagement_id": scenario["engagement_id"],
                "source": "EXCEPTION_CASCADE",
            },
        )
    )
    assert meta["total_count"] == 1
    assert gaps[0]["status"] == "WITHDRAWN"
    assert gaps[0]["debt_points"] == 0
