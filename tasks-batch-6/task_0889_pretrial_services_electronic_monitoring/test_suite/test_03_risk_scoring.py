"""Risk-score computation, recommended-level ladder + violent override, threshold
boundaries, assessment revision cycle, and court-event reminder computation.

Translates SCAFFOLD_DIFFICULTY_DESIGN.yaml rules dual_variant_calc, combinatorial_formula,
boundary_precision_check, non_linear_state_machine; and SCAFFOLD_CORNER_DESIGN.yaml
calculations.courtevent_reminder_due_at_computed.
"""
from test_helpers import (
    validate_success, TEST_USERS,
    create_defendant, create_draft_assessment, create_court_event_payload,
)

INTAKE = TEST_USERS["intake_headers"]
JUDICIAL = TEST_USERS["judicial_headers"]
SUPERVISING = TEST_USERS["supervising_headers"]


def _submit(api, defendant_id, **assessment_overrides):
    a = create_draft_assessment(defendant_id, **assessment_overrides)
    return validate_success(api.transition_assessment(a["id"], "SUBMITTED", INTAKE), 200)


# ─── dual_variant_calc / risk_score_screening_vs_full ───────────────────────

def test_screening_instrument_scores_two_factors_only(api):
    """PRD §3.2: "The `SCREENING` instrument uses only two factors: it adds four points per
    prior failure-to-appear (`prior_failures`) and two points per pending charge
    (`pending_charges_count`)."

    Design: Difficulty/dual_variant_calc/risk_score_screening_vs_full
    """
    d = create_defendant()
    a = _submit(api, d["id"], instrument_type="SCREENING", prior_failures=1,
                pending_charges_count=1, employment_status="UNEMPLOYED",
                residence_stability="UNSTABLE", substance_flag=True)
    assert a["raw_score"] == 6, f"SCREENING 1*4+1*2 == 6, got {a['raw_score']}"
    assert a["recommended_level"] == "MINIMUM"


def test_full_instrument_adds_three_extra_factors(api):
    """PRD §3.2: "The `FULL` instrument adds three more factors on top of those two: an
    additional three points if `employment_status` is `UNEMPLOYED`, an additional three
    points if `residence_stability` is `UNSTABLE`, and an additional five points if
    `substance_flag` is true."

    Design: Difficulty/dual_variant_calc/risk_score_screening_vs_full
    """
    d = create_defendant()
    a = _submit(api, d["id"], instrument_type="FULL", prior_failures=1,
                pending_charges_count=1, employment_status="UNEMPLOYED",
                residence_stability="UNSTABLE", substance_flag=True)
    assert a["raw_score"] == 17, f"FULL 6+3+3+5 == 17, got {a['raw_score']}"
    assert a["recommended_level"] == "MAXIMUM"


# ─── combinatorial_formula / recommended_level_tiered_with_override ─────────

def test_violent_charge_forces_maximum_over_zero_score(api):
    """PRD §3.2: "If `pending_violent_charge` is true, the recommended level is `MAXIMUM`
    regardless of the score — this violent-charge override supersedes the numeric ladder
    entirely."

    Design: Difficulty/combinatorial_formula/recommended_level_tiered_with_override
    """
    d = create_defendant()
    a = _submit(api, d["id"], instrument_type="FULL", prior_failures=0,
                pending_charges_count=0, pending_violent_charge=True,
                employment_status="EMPLOYED", residence_stability="STABLE",
                substance_flag=False)
    assert a["raw_score"] == 0
    assert a["recommended_level"] == "MAXIMUM"


def test_no_violent_charge_zero_score_yields_minimum(api):
    """PRD §3.2: "and any lower score yields `MINIMUM`." (with the violent override off,
    the numeric ladder governs, and a raw score of 0 is below both thresholds).

    Design: Difficulty/combinatorial_formula/recommended_level_tiered_with_override
    """
    d = create_defendant()
    a = _submit(api, d["id"], instrument_type="FULL", prior_failures=0,
                pending_charges_count=0, pending_violent_charge=False,
                employment_status="EMPLOYED", residence_stability="STABLE",
                substance_flag=False)
    assert a["raw_score"] == 0
    assert a["recommended_level"] == "MINIMUM"


# ─── boundary_precision_check / risk_score_medium_threshold_boundary ────────

def test_score_exactly_eight_is_medium(api):
    """PRD §3.2: "a raw score of at least 8 (but below 16) yields `MEDIUM` ... Both
    threshold comparisons are inclusive (a score exactly equal to a threshold lands in the
    higher band)."

    Design: Difficulty/boundary_precision_check/risk_score_medium_threshold_boundary
    """
    d = create_defendant()
    a = _submit(api, d["id"], instrument_type="FULL", prior_failures=2,
                pending_charges_count=0)
    assert a["raw_score"] == 8
    assert a["recommended_level"] == "MEDIUM"


def test_score_exactly_sixteen_is_maximum_and_six_is_minimum(api):
    """PRD §3.2: "a raw score of at least 16 yields `MAXIMUM` ... and any lower score
    yields `MINIMUM`. Both threshold comparisons are inclusive."

    Design: Difficulty/boundary_precision_check/risk_score_medium_threshold_boundary
    """
    d = create_defendant()
    a_max = _submit(api, d["id"], instrument_type="FULL", prior_failures=4,
                    pending_charges_count=0)
    assert a_max["raw_score"] == 16
    assert a_max["recommended_level"] == "MAXIMUM"

    a_min = _submit(api, d["id"], instrument_type="FULL", prior_failures=1,
                    pending_charges_count=1)
    assert a_min["raw_score"] == 6
    assert a_min["recommended_level"] == "MINIMUM"


# ─── non_linear_state_machine / assessment_revision_cycle ──────────────────

def test_assessment_kickback_then_resubmit_returns_to_submitted(api):
    """PRD §3.1: "then `SUBMITTED` either loops back to `DRAFT` (a revision kickback) or
    advances to the terminal `APPROVED` or `REJECTED`."

    Design: Difficulty/non_linear_state_machine/assessment_revision_cycle
    """
    d = create_defendant()
    a = create_draft_assessment(d["id"], instrument_type="FULL", prior_failures=2,
                                pending_charges_count=0)
    s1 = validate_success(api.transition_assessment(a["id"], "SUBMITTED", INTAKE), 200)
    assert s1["status"] == "SUBMITTED"
    s2 = validate_success(api.transition_assessment(a["id"], "DRAFT", JUDICIAL), 200)
    assert s2["status"] == "DRAFT"
    s3 = validate_success(api.transition_assessment(a["id"], "SUBMITTED", INTAKE), 200)
    assert s3["status"] == "SUBMITTED"
    assert s3["raw_score"] == 8


def test_kickback_clears_submitted_by_user_id(api):
    """PRD §3.1: "**Kickback** (`SUBMITTED → DRAFT`) requires the assessment to be in
    `SUBMITTED` and clears `submitted_by_user_id` so the assessment can be resubmitted."

    Design: Difficulty/non_linear_state_machine/assessment_revision_cycle
    """
    d = create_defendant()
    a = create_draft_assessment(d["id"], instrument_type="FULL", prior_failures=2,
                                pending_charges_count=0)
    submitted = validate_success(
        api.transition_assessment(a["id"], "SUBMITTED", INTAKE), 200)
    assert submitted["submitted_by_user_id"] == "u_intake"
    kicked = validate_success(api.transition_assessment(a["id"], "DRAFT", JUDICIAL), 200)
    assert kicked["submitted_by_user_id"] is None, \
        "kickback must clear submitted_by_user_id"


# ─── Corner: calculations.courtevent_reminder_due_at_computed ───────────────

def test_court_event_reminder_due_at_computed(api):
    """PRD §3.6: "On creation the system computes `reminder_due_at` as the hearing instant
    minus that whole number of lead days."

    Design: Corner/calculations/courtevent_reminder_due_at_computed
    """
    d = create_defendant()
    ce = validate_success(api.create_court_event(
        create_court_event_payload(d["id"], hearing_at="2026-06-20T09:00:00Z",
                                   reminder_lead_days=3), SUPERVISING), 201)
    assert ce["reminder_due_at"].startswith("2026-06-17T09:00:00"), \
        f"reminder_due_at must be 2026-06-17T09:00:00, got {ce['reminder_due_at']}"
