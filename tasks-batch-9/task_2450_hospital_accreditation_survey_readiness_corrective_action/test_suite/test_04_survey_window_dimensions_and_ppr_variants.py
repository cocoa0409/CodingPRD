"""Survey-window state dimensions, hospital-wide window occupancy, and the two
periodic performance review score variants."""

from test_helpers import (
    ApiErrorId,
    validate_error,
    validate_success,
)

# ---------------------------------------------------------------------------
# Private setup helpers, built only from api_client primitives.
# ---------------------------------------------------------------------------

CYCLE_2026_ANCHOR = "2025-03-15T00:00:00Z"


def _create_window(api, headers, cycle_label, prior_survey_end_date):
    """Create one survey window for an accreditation cycle."""
    return validate_success(
        api.create_survey_window(
            {"cycle_label": cycle_label, "prior_survey_end_date": prior_survey_end_date},
            headers,
        ),
        201,
    )


def _window_action(api, headers, window_id, action):
    return validate_success(
        api.transition_survey_window(window_id, {"action": action}, headers)
    )


def _projected_window_at_command_center_lead(api, headers):
    """CYCLE-2026 anchored at 2025-03-15 with the clock moved to 2026-08-20,
    past the command-center lead date but before the predicted open date."""
    window = _create_window(api, headers, "CYCLE-2026", CYCLE_2026_ANCHOR)
    validate_success(api.set_clock("2026-08-20T00:00:00Z", headers))
    return window


def _chapter_with_two_mapped_standards(api, headers):
    """Chapter IC with exactly two standards, each carrying one ACTIVE owner
    assignment and no evidence at all, so both sit in MAPPED."""
    chapter = validate_success(
        api.create_chapter(
            {
                "code": "IC",
                "name": "Infection Control",
                "weight_pct": 50,
                "evidence_min_count": 1,
            },
            headers,
        ),
        201,
    )
    first = validate_success(
        api.create_standard(
            chapter["id"],
            {
                "standard_code": "IC.01.01.01",
                "title": "Hand hygiene program",
                "risk_tier": "DIRECT_IMPACT",
            },
            headers,
        ),
        201,
    )
    second = validate_success(
        api.create_standard(
            chapter["id"],
            {
                "standard_code": "IC.02.01.01",
                "title": "Sterilization log",
                "risk_tier": "INDIRECT_IMPACT",
            },
            headers,
        ),
        201,
    )
    validate_success(
        api.create_owner_assignment(
            first["id"], {"owner_user_id": "owner-1", "designation": "PRIMARY"}, headers
        ),
        201,
    )
    validate_success(
        api.create_owner_assignment(
            second["id"], {"owner_user_id": "owner-2", "designation": "PRIMARY"}, headers
        ),
        201,
    )
    return chapter, first, second


# ===========================================================================
# Difficulty/non_linear_state_machine/survey_window_two_dimensions_advance_independently
# ===========================================================================


def test_command_center_activation_leaves_window_state_projected(api, director_headers):
    """PRD §3.6: "`predicted_open_date` is the anchor shifted eighteen months forward, the earliest an unannounced survey may arrive."

    PRD §3.6: "`command_center_activation_allowed_from` is thirty days before `predicted_open_date`, counted as exact twenty-four-hour multiples — the lead time within which the hospital is permitted to stand up its survey command center."

    PRD §3.6: "Activation deliberately does **not** touch `window_state`, which may perfectly well still be `PROJECTED` — the whole point of the thirty-day lead is that the command center stands up before the window opens."

    Design: Difficulty/non_linear_state_machine/survey_window_two_dimensions_advance_independently
    """
    window = _projected_window_at_command_center_lead(api, director_headers)

    assert window["predicted_open_date"] == "2026-09-15T00:00:00.000Z"
    assert window["command_center_activation_allowed_from"] == "2026-08-16T00:00:00.000Z"
    assert window["window_state"] == "PROJECTED"
    assert window["command_center_state"] == "STANDBY"

    activated = _window_action(
        api, director_headers, window["id"], "ACTIVATE_COMMAND_CENTER"
    )

    assert activated["command_center_state"] == "ACTIVATED"
    assert activated["window_state"] == "PROJECTED"


def test_clock_sweep_moves_window_state_to_eligible_leaving_command_center_dimension(
    api, director_headers
):
    """PRD §3.6: "The survey dimension's first advance needs no human at all: as described in §2.4, a window in `PROJECTED` moves `PROJECTED → ELIGIBLE` on a clock advance whose new value is at or after `predicted_open_date` and at or before `predicted_close_date`."

    PRD §3.6: "That transition leaves `command_center_state` completely untouched."

    PRD §2.4: "`expired_evidence_count` is the number of evidence items expired by the sweep and `eligible_window_count` is the number of windows that became eligible."

    PRD §3.6: "`DEMOBILIZE_COMMAND_CENTER` moves `ACTIVATED → DEMOBILIZED` and requires only that `window_state` is not `ACTIVE_SURVEY`; a command center may not be torn down while surveyors are in the building."

    Design: Difficulty/non_linear_state_machine/survey_window_two_dimensions_advance_independently
    """
    window = _projected_window_at_command_center_lead(api, director_headers)
    _window_action(api, director_headers, window["id"], "ACTIVATE_COMMAND_CENTER")

    swept = validate_success(api.set_clock("2026-09-20T00:00:00Z", director_headers))
    assert swept["eligible_window_count"] == 1

    demobilized = _window_action(
        api, director_headers, window["id"], "DEMOBILIZE_COMMAND_CENTER"
    )

    assert demobilized["window_state"] == "ELIGIBLE"
    assert demobilized["command_center_state"] == "DEMOBILIZED"


def test_command_center_reactivation_then_open_survey_advances_only_its_own_dimension(
    api, director_headers
):
    """PRD §3.6: "`ACTIVATE_COMMAND_CENTER` has two declared entry points, `STANDBY → ACTIVATED` and `DEMOBILIZED → ACTIVATED`, both requiring the logical clock to be at or after `command_center_activation_allowed_from` and both refused with `ERR_COMMAND_CENTER_WINDOW_NOT_OPEN` when it is earlier."

    PRD §3.6: "It has two declared entry points: `ELIGIBLE → ACTIVE_SURVEY` for the initial survey and `CLOSED → ACTIVE_SURVEY` for a follow-up survey, making the survey dimension cyclic too."

    PRD §3.6: "On success — identically for both entry points — `survey_opened_at` is stamped with the current logical clock and every hospital unit is driven to `LOCKED_FOR_SURVEY`, each such move aborting that unit's `SCHEDULED` tracers with `abort_reason` `SURVEY_ACTIVE`, zeroing its `scheduled_tracer_count` and recomputing its `readiness_score` and `readiness_band`."

    Design: Difficulty/non_linear_state_machine/survey_window_two_dimensions_advance_independently
    """
    window = _projected_window_at_command_center_lead(api, director_headers)
    _window_action(api, director_headers, window["id"], "ACTIVATE_COMMAND_CENTER")
    validate_success(api.set_clock("2026-09-20T00:00:00Z", director_headers))
    _window_action(api, director_headers, window["id"], "DEMOBILIZE_COMMAND_CENTER")

    reactivated = _window_action(
        api, director_headers, window["id"], "ACTIVATE_COMMAND_CENTER"
    )

    assert reactivated["command_center_state"] == "ACTIVATED"
    assert reactivated["window_state"] == "ELIGIBLE"

    opened = _window_action(api, director_headers, window["id"], "OPEN_SURVEY")

    assert opened["window_state"] == "ACTIVE_SURVEY"
    assert opened["command_center_state"] == "ACTIVATED"
    assert opened["survey_opened_at"] == "2026-09-20T00:00:00.000Z"


# ===========================================================================
# Difficulty/dual_variant_calc/ppr_self_reported_vs_evidence_verified_chapter_score
# ===========================================================================


def test_ppr_self_reported_and_evidence_verified_variants_diverge_on_mapped_standards(
    api, director_headers
):
    """PRD §3.9: "The whole value of this exercise is that the same chapter is scored twice from two different sources, and the two scores share one denominator: the chapter's `standard_count`, meaning **every** standard in the chapter, not merely the ones that were rated."

    PRD §3.9: "Each supplied rating earns points — one hundred for `COMPLIANT`, fifty for `PARTIAL`, zero for `NON_COMPLIANT` — and `self_score` is the sum of those points divided by the denominator, rounded half up to two decimal places."

    PRD §3.9: "Each standard of the chapter earns points from its `compliance_state` — one hundred for `EVIDENCE_COMPLETE`, fifty for `MAPPED`, and zero for both `UNMAPPED` and `DEFICIENT` — and `verified_score` is the sum of those points across every standard of the chapter, divided by the same denominator, rounded half up to two decimal places."

    Design: Difficulty/dual_variant_calc/ppr_self_reported_vs_evidence_verified_chapter_score
    """
    chapter, first, second = _chapter_with_two_mapped_standards(api, director_headers)

    ppr = validate_success(
        api.create_ppr_self_assessment(
            chapter["id"],
            {
                "period_label": "2026-H2",
                "self_ratings": [
                    {"standard_id": first["id"], "rating": "COMPLIANT"},
                    {"standard_id": second["id"], "rating": "COMPLIANT"},
                ],
            },
            director_headers,
        ),
        201,
    )

    assert float(ppr["self_score"]) == 100.00
    assert float(ppr["verified_score"]) == 50.00


def test_ppr_overstatement_gap_flags_assessment_and_charges_chapter_once(
    api, director_headers
):
    """PRD §3.9: "The `gap` is `self_score` minus `verified_score`, rounded half up to two decimal places, and `flagged_overstatement` is true when that gap is at least 10.00."

    PRD §3.9: "A flagged assessment increments the owning chapter's `ppr_escalation_count` by one, and once that counter reaches two the chapter's `readiness_flag` becomes `AT_RISK` — the second of the two independent routes into `AT_RISK` described in §3.1."

    PRD §3.1: "It flips from `ON_TRACK` to `AT_RISK` as soon as either the chapter accumulates two or more deficient standards or its overstatement escalations reach two."

    Design: Difficulty/dual_variant_calc/ppr_self_reported_vs_evidence_verified_chapter_score
    """
    chapter, first, second = _chapter_with_two_mapped_standards(api, director_headers)

    ppr = validate_success(
        api.create_ppr_self_assessment(
            chapter["id"],
            {
                "period_label": "2026-H2",
                "self_ratings": [
                    {"standard_id": first["id"], "rating": "COMPLIANT"},
                    {"standard_id": second["id"], "rating": "COMPLIANT"},
                ],
            },
            director_headers,
        ),
        201,
    )

    assert float(ppr["gap"]) == 50.00
    assert ppr["flagged_overstatement"] is True

    reread = validate_success(api.get_chapter(chapter["id"], director_headers))

    assert reread["ppr_escalation_count"] == 1
    assert reread["readiness_flag"] == "ON_TRACK"


# ===========================================================================
# Difficulty/resource_temporal_overlap/survey_window_hospital_wide_capacity_one_touching_endpoints
# ===========================================================================


def test_second_cycle_touching_the_predicted_close_date_is_rejected(
    api, director_headers
):
    """PRD §3.6: "`predicted_close_date` is the anchor shifted thirty-six months forward, the latest it may arrive."

    PRD §3.6: "Occupation is measured on the **closed** interval running from `predicted_open_date` through `predicted_close_date` inclusive, with capacity one hospital-wide, and touching endpoints count as an intersection: a proposed window is rejected when its `predicted_open_date` is at or before some existing window's `predicted_close_date` **and** its `predicted_close_date` is at or after that window's `predicted_open_date`."

    PRD §3.6: "A collision is rejected with `ERR_SURVEY_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/survey_window_hospital_wide_capacity_one_touching_endpoints
    """
    first = _create_window(api, director_headers, "CYCLE-2026", CYCLE_2026_ANCHOR)

    assert first["predicted_open_date"] == "2026-09-15T00:00:00.000Z"
    assert first["predicted_close_date"] == "2028-03-15T00:00:00.000Z"

    touching = api.create_survey_window(
        {
            "cycle_label": "CYCLE-2028-TOUCH",
            "prior_survey_end_date": "2026-09-15T00:00:00Z",
        },
        director_headers,
    )

    validate_error(touching, ApiErrorId.ERR_SURVEY_WINDOW_OVERLAP)


def test_second_cycle_one_day_clear_of_the_predicted_close_date_is_accepted(
    api, director_headers
):
    """PRD §3.6: "Occupation is measured on the **closed** interval running from `predicted_open_date` through `predicted_close_date` inclusive, with capacity one hospital-wide, and touching endpoints count as an intersection: a proposed window is rejected when its `predicted_open_date` is at or before some existing window's `predicted_close_date` **and** its `predicted_close_date` is at or after that window's `predicted_open_date`."

    PRD §3.6: "`command_center_activation_allowed_from` is thirty days before `predicted_open_date`, counted as exact twenty-four-hour multiples — the lead time within which the hospital is permitted to stand up its survey command center."

    PRD §3.6: "The survey dimension, `window_state`, takes `PROJECTED`, `ELIGIBLE`, `ACTIVE_SURVEY` and `CLOSED`, and starts at `PROJECTED`."

    Design: Difficulty/resource_temporal_overlap/survey_window_hospital_wide_capacity_one_touching_endpoints
    """
    _create_window(api, director_headers, "CYCLE-2026", CYCLE_2026_ANCHOR)

    clear = _create_window(
        api, director_headers, "CYCLE-2028-CLEAR", "2026-09-16T00:00:00Z"
    )

    assert clear["predicted_open_date"] == "2028-03-16T00:00:00.000Z"
    assert clear["predicted_close_date"] == "2029-09-16T00:00:00.000Z"

    reread = validate_success(api.get_survey_window(clear["id"], director_headers))

    assert reread["window_state"] == "PROJECTED"
    assert reread["command_center_activation_allowed_from"] == "2028-02-15T00:00:00.000Z"
