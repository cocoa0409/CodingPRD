"""Finding risk classification, the non-compliance rate thresholds and the two
evidence-of-standards-compliance deadline derivations (PRD §3.6, §3.7, §3.8)."""

from typing import Any, Dict

from test_helpers import (
    ApiErrorId,
    assert_four_decimal_places,
    assert_instant_equals,
    assert_survey_finding,
    create_chapter,
    create_standard,
    create_unit,
    setup_active_survey,
    setup_survey_finding,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# Private setup chains — built only from test_helpers primitives
# ===========================================================================

def _setup_ls_active_survey() -> Dict[str, Any]:
    """Chapter LS carrying one DIRECT_IMPACT and one SITUATIONAL_DECISION_RULE
    standard, one OR unit, and CYCLE-2026 driven to ACTIVE_SURVEY at
    2026-09-20T00:00:00Z."""
    chapter = create_chapter("LS", "Life Safety", 25, 1)
    direct_standard = create_standard(
        chapter["id"], "LS.01.01.01", "Egress protection", "DIRECT_IMPACT"
    )
    situational_standard = create_standard(
        chapter["id"], "LS.03.01.01", "Signage placement", "SITUATIONAL_DECISION_RULE"
    )
    unit = create_unit("OR-1", "OR", 8)
    survey = setup_active_survey("CYCLE-2026", "2025-03-15T00:00:00Z", "2026-09-20T00:00:00Z")
    return {
        "chapter": chapter,
        "direct_standard": direct_standard,
        "situational_standard": situational_standard,
        "unit": unit,
        "window": survey["window"],
    }


def _setup_pc_active_survey() -> Dict[str, Any]:
    """Chapter PC with one DIRECT_IMPACT standard, one MED_SURG unit and
    CYCLE-2026 in ACTIVE_SURVEY at 2026-09-20T00:00:00Z."""
    chapter = create_chapter("PC", "Provision of Care", 100, 1)
    standard = create_standard(chapter["id"], "PC.01.02.03", "Care planning", "DIRECT_IMPACT")
    unit = create_unit("MED-5", "MED_SURG", 22)
    survey = setup_active_survey("CYCLE-2026", "2025-03-15T00:00:00Z", "2026-09-20T00:00:00Z")
    return {
        "chapter": chapter,
        "standard": standard,
        "unit": unit,
        "window": survey["window"],
    }


def _setup_mm_response_pending_finding() -> Dict[str, Any]:
    """Chapter MM, an INDIRECT_IMPACT standard owned by owner-1 as ACTIVE
    PRIMARY, and a five-of-ten finding with patient harm observed, carried
    through survey close at 2026-09-25T00:00:00Z into RESPONSE_PENDING."""
    return setup_survey_finding(
        chapter_code="MM",
        chapter_name="Medication Management",
        weight_pct=30,
        evidence_min_count=1,
        standard_code="MM.05.01.01",
        standard_title="Medication order review",
        risk_tier="INDIRECT_IMPACT",
        unit_name="MED-2",
        unit_type="MED_SURG",
        bed_count=30,
        cycle_label="CYCLE-2026",
        prior_survey_end_date="2025-03-15T00:00:00Z",
        open_clock="2026-09-20T00:00:00Z",
        sampled_count=10,
        observed_noncompliance_count=5,
        patient_harm_observed=True,
        close_clock="2026-09-25T00:00:00Z",
    )


def _submit_esc_round(api, finding_id: str, owner_headers, summary: str, measure: str) -> None:
    """Read the finding's current version, then submit the next ESC round."""
    version = validate_success(api.get_finding(finding_id, owner_headers))["version"]
    validate_success(
        api.create_esc_submission(
            finding_id,
            {
                "corrective_action_summary": summary,
                "measure_of_success": measure,
                "leadership_signoff": True,
                "expected_finding_version": version,
            },
            owner_headers,
        ),
        201,
    )


# ===========================================================================
# Difficulty/combinatorial_formula/finding_risk_index_four_input_non_linear_cap
# ===========================================================================

def test_widespread_direct_impact_findings_saturate_risk_index_at_six(
    api, external_surveyor_headers
):
    """PRD §3.7: "Second, the rate produces a `classification`: it is `LIMITED` when the rate is strictly below 0.3400, `PATTERN` when the rate is at or above 0.3400 but strictly below 0.8000, and `WIDESPREAD` when the rate is at or above 0.8000."
    PRD §3.7: "The classification index is zero for `LIMITED`, one for `PATTERN` and two for `WIDESPREAD`."
    PRD §3.7: "The tier index comes from the referenced standard's own `risk_tier`: zero for `SITUATIONAL_DECISION_RULE`, one for `INDIRECT_IMPACT` and two for `DIRECT_IMPACT`."
    PRD §3.7: "To their sum, two further points are added when `patient_harm_observed` is true and none when it is false, and the total is then capped at six."
    PRD §3.7: "That capped index yields the `risk_level`: `LOW` when the index is one or less, `MODERATE` when it is exactly two, `HIGH` when it is three or four, and `IMMEDIATE_THREAT` when it is five or more."
    PRD §3.7: "`condition_level` is true when either the `risk_level` came out as `IMMEDIATE_THREAT`, or the `classification` came out as `WIDESPREAD` while the referenced standard's `risk_tier` is `DIRECT_IMPACT` — the second branch is what catches a hospital-wide failure of a high-impact standard even when no harm was observed."
    PRD §3.7: "And `response_deadline_days` is forty-five when the `risk_level` is `HIGH` or `IMMEDIATE_THREAT`, and sixty otherwise."

    Design: Difficulty/combinatorial_formula/finding_risk_index_four_input_non_linear_cap
    """
    built = _setup_ls_active_survey()

    # Eight of ten on a DIRECT_IMPACT standard, no harm: index 2 + 2 + 0 == 4.
    finding_a = validate_success(
        api.create_finding(
            built["window"]["id"],
            {
                "standard_id": built["direct_standard"]["id"],
                "unit_id": built["unit"]["id"],
                "observed_noncompliance_count": 8,
                "sampled_count": 10,
                "patient_harm_observed": False,
            },
            external_surveyor_headers,
        ),
        201,
    )
    assert_survey_finding(finding_a)
    assert float(finding_a["noncompliance_rate"]) == 0.8000
    assert finding_a["classification"] == "WIDESPREAD"
    assert finding_a["risk_level"] == "HIGH"
    assert finding_a["condition_level"] is True
    assert finding_a["response_deadline_days"] == 45

    # Ten of ten on the same standard with harm: raw index 2 + 2 + 2 == 6,
    # exactly the cap, so the level saturates at IMMEDIATE_THREAT.
    finding_b = validate_success(
        api.create_finding(
            built["window"]["id"],
            {
                "standard_id": built["direct_standard"]["id"],
                "unit_id": built["unit"]["id"],
                "observed_noncompliance_count": 10,
                "sampled_count": 10,
                "patient_harm_observed": True,
            },
            external_surveyor_headers,
        ),
        201,
    )
    assert_survey_finding(finding_b)
    assert float(finding_b["noncompliance_rate"]) == 1.0000
    assert finding_b["classification"] == "WIDESPREAD"
    assert finding_b["risk_level"] == "IMMEDIATE_THREAT"
    assert finding_b["condition_level"] is True
    assert finding_b["response_deadline_days"] == 45


def test_patient_harm_alone_lifts_limited_finding_to_moderate_without_condition_level(
    api, external_surveyor_headers, director_headers
):
    """PRD §3.7: "The tier index comes from the referenced standard's own `risk_tier`: zero for `SITUATIONAL_DECISION_RULE`, one for `INDIRECT_IMPACT` and two for `DIRECT_IMPACT`."
    PRD §3.7: "To their sum, two further points are added when `patient_harm_observed` is true and none when it is false, and the total is then capped at six."
    PRD §3.7: "That capped index yields the `risk_level`: `LOW` when the index is one or less, `MODERATE` when it is exactly two, `HIGH` when it is three or four, and `IMMEDIATE_THREAT` when it is five or more."
    PRD §3.7: "And `response_deadline_days` is forty-five when the `risk_level` is `HIGH` or `IMMEDIATE_THREAT`, and sixty otherwise."
    PRD §3.7: "When `condition_level` came out true, the window's `condition_level_finding_count` increases by one — which is exactly the counter that decides, at survey close, whether a follow-up survey will be required."

    Design: Difficulty/combinatorial_formula/finding_risk_index_four_input_non_linear_cap
    """
    built = _setup_ls_active_survey()
    window_id = built["window"]["id"]

    # Two condition-level findings on the DIRECT_IMPACT standard.
    for observed, harm in ((8, False), (10, True)):
        validate_success(
            api.create_finding(
                window_id,
                {
                    "standard_id": built["direct_standard"]["id"],
                    "unit_id": built["unit"]["id"],
                    "observed_noncompliance_count": observed,
                    "sampled_count": 10,
                    "patient_harm_observed": harm,
                },
                external_surveyor_headers,
            ),
            201,
        )

    # Three of ten on a SITUATIONAL_DECISION_RULE standard with harm:
    # index 0 + 0 + 2 == 2, so the harm bonus alone reaches MODERATE.
    finding_c = validate_success(
        api.create_finding(
            window_id,
            {
                "standard_id": built["situational_standard"]["id"],
                "unit_id": built["unit"]["id"],
                "observed_noncompliance_count": 3,
                "sampled_count": 10,
                "patient_harm_observed": True,
            },
            external_surveyor_headers,
        ),
        201,
    )
    assert_survey_finding(finding_c)
    assert float(finding_c["noncompliance_rate"]) == 0.3000
    assert finding_c["classification"] == "LIMITED"
    assert finding_c["risk_level"] == "MODERATE"
    assert finding_c["condition_level"] is False
    assert finding_c["response_deadline_days"] == 60

    window = validate_success(api.get_survey_window(window_id, director_headers))
    assert window["condition_level_finding_count"] == 2


# ===========================================================================
# Difficulty/boundary_precision_check/
#   noncompliance_rate_pattern_threshold_four_decimal_precision
# ===========================================================================

def test_noncompliance_rate_at_pattern_threshold_classifies_pattern(
    api, external_surveyor_headers
):
    """PRD §3.7: "First, `noncompliance_rate` is the observed count divided by the sampled count, rounded half up to four decimal places; every subsequent comparison uses that rounded value, not the raw quotient."
    PRD §3.7: "Second, the rate produces a `classification`: it is `LIMITED` when the rate is strictly below 0.3400, `PATTERN` when the rate is at or above 0.3400 but strictly below 0.8000, and `WIDESPREAD` when the rate is at or above 0.8000."
    PRD §3.7: "That capped index yields the `risk_level`: `LOW` when the index is one or less, `MODERATE` when it is exactly two, `HIGH` when it is three or four, and `IMMEDIATE_THREAT` when it is five or more."
    PRD §3.7: "`condition_level` is true when either the `risk_level` came out as `IMMEDIATE_THREAT`, or the `classification` came out as `WIDESPREAD` while the referenced standard's `risk_tier` is `DIRECT_IMPACT` — the second branch is what catches a hospital-wide failure of a high-impact standard even when no harm was observed."
    PRD §3.7: "And `response_deadline_days` is forty-five when the `risk_level` is `HIGH` or `IMMEDIATE_THREAT`, and sixty otherwise."

    Design: Difficulty/boundary_precision_check/noncompliance_rate_pattern_threshold_four_decimal_precision
    """
    built = _setup_pc_active_survey()
    window_id = built["window"]["id"]

    # Thirty-three of one hundred: 0.3300 is strictly below 0.3400.
    below = validate_success(
        api.create_finding(
            window_id,
            {
                "standard_id": built["standard"]["id"],
                "unit_id": built["unit"]["id"],
                "observed_noncompliance_count": 33,
                "sampled_count": 100,
                "patient_harm_observed": False,
            },
            external_surveyor_headers,
        ),
        201,
    )
    assert float(below["noncompliance_rate"]) == 0.3300
    assert below["classification"] == "LIMITED"
    assert below["risk_level"] == "MODERATE"
    assert below["response_deadline_days"] == 60

    # Thirty-four of one hundred: exactly 0.3400, and the threshold is inclusive.
    at_threshold = validate_success(
        api.create_finding(
            window_id,
            {
                "standard_id": built["standard"]["id"],
                "unit_id": built["unit"]["id"],
                "observed_noncompliance_count": 34,
                "sampled_count": 100,
                "patient_harm_observed": False,
            },
            external_surveyor_headers,
        ),
        201,
    )
    assert float(at_threshold["noncompliance_rate"]) == 0.3400
    assert at_threshold["classification"] == "PATTERN"
    assert at_threshold["risk_level"] == "HIGH"
    assert at_threshold["response_deadline_days"] == 45
    assert at_threshold["condition_level"] is False


def test_noncompliance_rate_one_of_three_rounds_to_four_decimals_and_stays_limited(
    api, external_surveyor_headers, director_headers
):
    """PRD §3.7: "First, `noncompliance_rate` is the observed count divided by the sampled count, rounded half up to four decimal places; every subsequent comparison uses that rounded value, not the raw quotient."
    PRD §3.7: "Second, the rate produces a `classification`: it is `LIMITED` when the rate is strictly below 0.3400, `PATTERN` when the rate is at or above 0.3400 but strictly below 0.8000, and `WIDESPREAD` when the rate is at or above 0.8000."
    PRD §3.7: "When `condition_level` came out true, the window's `condition_level_finding_count` increases by one — which is exactly the counter that decides, at survey close, whether a follow-up survey will be required."
    PRD §2.3: "Collection reads also accept filters that narrow the result set by a stored attribute before pagination."
    PRD §2.3: "The `meta` object of every collection response carries `limit`, `offset`, `total_count` and `has_more`, where `total_count` is the size of the filtered result set before pagination is applied and `has_more` indicates whether rows remain beyond the current page."

    Design: Difficulty/boundary_precision_check/noncompliance_rate_pattern_threshold_four_decimal_precision
    """
    built = _setup_pc_active_survey()
    window_id = built["window"]["id"]

    for observed, sampled in ((33, 100), (34, 100)):
        validate_success(
            api.create_finding(
                window_id,
                {
                    "standard_id": built["standard"]["id"],
                    "unit_id": built["unit"]["id"],
                    "observed_noncompliance_count": observed,
                    "sampled_count": sampled,
                    "patient_harm_observed": False,
                },
                external_surveyor_headers,
            ),
            201,
        )

    # One of three is 0.333333..., which rounds half up to 0.3333 — still LIMITED.
    rounded = validate_success(
        api.create_finding(
            window_id,
            {
                "standard_id": built["standard"]["id"],
                "unit_id": built["unit"]["id"],
                "observed_noncompliance_count": 1,
                "sampled_count": 3,
                "patient_harm_observed": False,
            },
            external_surveyor_headers,
        ),
        201,
    )
    assert float(rounded["noncompliance_rate"]) == 0.3333
    assert_four_decimal_places(float(rounded["noncompliance_rate"]))
    assert rounded["classification"] == "LIMITED"
    assert rounded["risk_level"] == "MODERATE"

    window = validate_success(api.get_survey_window(window_id, director_headers))
    assert window["condition_level_finding_count"] == 0

    findings, meta = validate_paginated(
        api.list_findings(director_headers, {"survey_window_id": window_id})
    )
    assert meta["total_count"] == 3
    assert len(findings) == 3


# ===========================================================================
# Difficulty/dual_variant_calc/esc_deadline_initial_vs_clarification_variant
# ===========================================================================

def test_initial_response_deadline_anchors_on_survey_close_plus_forty_five_days(
    api, standard_owner_headers
):
    """PRD §3.6: "Every finding of this window still in `DRAFT` moves to `RESPONSE_PENDING`, and each gets both `initial_response_due_at` and `response_due_at` set to `survey_closed_at` plus that finding's own `response_deadline_days` days, counted as exact twenty-four-hour multiples."
    PRD §3.7: "That capped index yields the `risk_level`: `LOW` when the index is one or less, `MODERATE` when it is exactly two, `HIGH` when it is three or four, and `IMMEDIATE_THREAT` when it is five or more."
    PRD §3.7: "And `response_deadline_days` is forty-five when the `risk_level` is `HIGH` or `IMMEDIATE_THREAT`, and sixty otherwise."

    Design: Difficulty/dual_variant_calc/esc_deadline_initial_vs_clarification_variant
    """
    built = _setup_mm_response_pending_finding()

    finding = validate_success(api.get_finding(built["finding"]["id"], standard_owner_headers))
    assert finding["state"] == "RESPONSE_PENDING"
    assert finding["risk_level"] == "HIGH"
    assert finding["condition_level"] is False
    assert finding["response_deadline_days"] == 45
    # Survey closed at 2026-09-25T00:00:00Z plus forty-five days.
    assert_instant_equals(finding["initial_response_due_at"], "2026-11-09T00:00:00.000Z")
    assert_instant_equals(finding["response_due_at"], "2026-11-09T00:00:00.000Z")


def test_clarification_decision_moves_response_deadline_earlier_than_initial_deadline(
    api, standard_owner_headers, external_surveyor_headers, director_headers
):
    """PRD §3.8: "On success the count increases by one, the newest submission's `decision` becomes `CLARIFICATION_REQUESTED`, the finding moves `RESPONSE_SUBMITTED → CLARIFICATION_REQUESTED`, and — critically — the effective deadline is recomputed."
    PRD §3.8: "The new `response_due_at` is the earlier of two candidates: the current logical clock plus twenty-one days, and `initial_response_due_at` plus ten days."
    PRD §3.8: "The cap is measured from `initial_response_due_at`, never from the previous `response_due_at`, so repeated clarifications cannot walk the deadline forward indefinitely; `initial_response_due_at` itself is frozen at survey close and is never rewritten."

    Design: Difficulty/dual_variant_calc/esc_deadline_initial_vs_clarification_variant
    """
    built = _setup_mm_response_pending_finding()
    finding_id = built["finding"]["id"]

    _submit_esc_round(
        api,
        finding_id,
        standard_owner_headers,
        "Pharmacist re-review of all orders",
        "100 percent review for 4 months",
    )

    validate_success(api.set_clock("2026-10-01T00:00:00Z", director_headers))
    validate_success(
        api.esc_review(
            finding_id,
            {
                "decision": "CLARIFICATION_REQUESTED",
                "decision_note": "Measure of success lacks a numeric target",
            },
            external_surveyor_headers,
        )
    )

    finding = validate_success(api.get_finding(finding_id, standard_owner_headers))
    assert finding["state"] == "CLARIFICATION_REQUESTED"
    assert finding["clarification_round_count"] == 1
    # 2026-10-01 plus twenty-one days, below the 2026-11-19 cap.
    assert_instant_equals(finding["response_due_at"], "2026-10-22T00:00:00.000Z")
    # Frozen at survey close, so the clarification left it alone.
    assert_instant_equals(finding["initial_response_due_at"], "2026-11-09T00:00:00.000Z")


# ===========================================================================
# Difficulty/non_linear_state_machine/
#   finding_clarification_cycle_bounded_at_two_rounds
# ===========================================================================

def test_two_clarification_rounds_recompute_deadline_then_hit_the_initial_due_cap(
    api, standard_owner_headers, external_surveyor_headers, director_headers
):
    """PRD §3.8: "On success the count increases by one, the newest submission's `decision` becomes `CLARIFICATION_REQUESTED`, the finding moves `RESPONSE_SUBMITTED → CLARIFICATION_REQUESTED`, and — critically — the effective deadline is recomputed."
    PRD §3.8: "The new `response_due_at` is the earlier of two candidates: the current logical clock plus twenty-one days, and `initial_response_due_at` plus ten days."
    PRD §3.8: "The cap is measured from `initial_response_due_at`, never from the previous `response_due_at`, so repeated clarifications cannot walk the deadline forward indefinitely; `initial_response_due_at` itself is frozen at survey close and is never rewritten."

    Design: Difficulty/non_linear_state_machine/finding_clarification_cycle_bounded_at_two_rounds
    """
    built = _setup_mm_response_pending_finding()
    finding_id = built["finding"]["id"]

    _submit_esc_round(
        api, finding_id, standard_owner_headers, "Round 1 plan", "Audit 30 charts monthly"
    )

    validate_success(api.set_clock("2026-10-01T00:00:00Z", director_headers))
    validate_success(
        api.esc_review(
            finding_id,
            {"decision": "CLARIFICATION_REQUESTED", "decision_note": "Quantify the target"},
            external_surveyor_headers,
        )
    )
    after_round_one = validate_success(api.get_finding(finding_id, standard_owner_headers))
    assert after_round_one["clarification_round_count"] == 1
    # 2026-10-01 plus twenty-one days is earlier than the 2026-11-19 cap.
    assert_instant_equals(after_round_one["response_due_at"], "2026-10-22T00:00:00.000Z")

    validate_success(api.set_clock("2026-10-10T00:00:00Z", director_headers))
    _submit_esc_round(
        api,
        finding_id,
        standard_owner_headers,
        "Round 2 plan",
        "90 percent compliance for 4 months",
    )

    validate_success(api.set_clock("2026-11-15T00:00:00Z", director_headers))
    validate_success(
        api.esc_review(
            finding_id,
            {"decision": "CLARIFICATION_REQUESTED", "decision_note": "Attach the audit tool"},
            external_surveyor_headers,
        )
    )
    after_round_two = validate_success(api.get_finding(finding_id, standard_owner_headers))
    assert after_round_two["state"] == "CLARIFICATION_REQUESTED"
    assert after_round_two["clarification_round_count"] == 2
    # Capped at initial_response_due_at plus ten days, not 2026-12-06.
    assert_instant_equals(after_round_two["response_due_at"], "2026-11-19T00:00:00.000Z")
    assert_instant_equals(after_round_two["initial_response_due_at"], "2026-11-09T00:00:00.000Z")


def test_third_clarification_on_finding_refused_at_the_two_round_ceiling(
    api, standard_owner_headers, external_surveyor_headers, director_headers
):
    """PRD §3.8: "A `CLARIFICATION_REQUESTED` decision requires that the finding's `clarification_round_count` is still strictly below two, the ceiling on clarification rounds; a third clarification is refused with `ERR_CLARIFICATION_LIMIT_EXCEEDED`."
    PRD §3.8: "On success the finding's `submission_count` increases by one and a submission record is created with `submission_round` equal to that new count — one for the first submission, two for the resubmission after a first clarification, and so on — with `submitted_by_user_id` stamped from the acting owner, `decision` at `PENDING` and `decision_note` null."
    PRD §3.8: "The finding moves to `RESPONSE_SUBMITTED`, and its `version` advances."

    Design: Difficulty/non_linear_state_machine/finding_clarification_cycle_bounded_at_two_rounds
    """
    built = _setup_mm_response_pending_finding()
    finding_id = built["finding"]["id"]

    _submit_esc_round(
        api, finding_id, standard_owner_headers, "Round 1 plan", "Audit 30 charts monthly"
    )
    validate_success(api.set_clock("2026-10-01T00:00:00Z", director_headers))
    validate_success(
        api.esc_review(
            finding_id,
            {"decision": "CLARIFICATION_REQUESTED", "decision_note": "Quantify the target"},
            external_surveyor_headers,
        )
    )

    validate_success(api.set_clock("2026-10-10T00:00:00Z", director_headers))
    _submit_esc_round(
        api,
        finding_id,
        standard_owner_headers,
        "Round 2 plan",
        "90 percent compliance for 4 months",
    )
    validate_success(api.set_clock("2026-11-15T00:00:00Z", director_headers))
    validate_success(
        api.esc_review(
            finding_id,
            {"decision": "CLARIFICATION_REQUESTED", "decision_note": "Attach the audit tool"},
            external_surveyor_headers,
        )
    )

    validate_success(api.set_clock("2026-11-16T00:00:00Z", director_headers))
    _submit_esc_round(
        api, finding_id, standard_owner_headers, "Round 3 plan", "Audit tool attached"
    )

    # The third clarification is over the ceiling.
    validate_error(
        api.esc_review(
            finding_id,
            {"decision": "CLARIFICATION_REQUESTED", "decision_note": "Third clarification attempt"},
            external_surveyor_headers,
        ),
        ApiErrorId.ERR_CLARIFICATION_LIMIT_EXCEEDED,
    )

    finding = validate_success(api.get_finding(finding_id, standard_owner_headers))
    assert finding["state"] == "RESPONSE_SUBMITTED"
    assert finding["clarification_round_count"] == 2
    assert finding["submission_count"] == 3

    submissions, meta = validate_paginated(
        api.list_esc_submissions(finding_id, standard_owner_headers)
    )
    assert meta["total_count"] == 3
    assert [row["submission_round"] for row in submissions] == [1, 2, 3]
