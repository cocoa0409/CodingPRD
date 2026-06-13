"""Risk scoring (LSI-R band vs clinical override) and the supervision-level
posture cascade on adoption.

Difficulty queue: dual_variant_calc, transitive_cascade (adopt branch).
Corner queue: calculations (band lookup), validations (override), entities
(computed fields server-initialized).
"""
import pytest

from test_helpers import (
    api_client,
    validate_success, validate_error,
    create_supervisee_payload, create_risk_assessment_payload,
    domain_scores_for_total, domain_scores_uniform,
    make_officer_headers,
    create_officer, open_supervisee, add_draft_assessment, adopt_assessment,
    setup_active_supervisee, add_active_condition,
)


# ─── Difficulty: dual_variant_calc / lsi_r_actuarial_vs_clinical_override_level ───
def test_clinical_override_raises_level_above_actuarial_band(api):
    """PRD §3.2: "The effective level the assessment will impose is the higher of
    the derived band and the override: when no override is given, the effective
    level equals derived_level; when an override is given, the effective level
    equals override_level (which by the rule above is at least the derived band)."
    PRD §3.2: "a total from 24 through 33 derives MEDIUM"

    A total of 28 derives MEDIUM, but an adopted override_level=MAXIMUM makes the
    supervisee's effective supervision_level MAXIMUM.

    Design: Difficulty/dual_variant_calc/lsi_r_actuarial_vs_clinical_override_level
    """
    officer = create_officer(role_type="PROBATION")
    sup = open_supervisee(officer["id"], supervision_type="PROBATION")
    oh = make_officer_headers(officer["id"])

    scores = domain_scores_for_total(28)
    base = add_draft_assessment(sup["id"], officer["id"], domain_scores=scores)
    assert base["derived_level"] == "MEDIUM"

    ovr = add_draft_assessment(
        sup["id"], officer["id"], domain_scores=scores,
        override_level="MAXIMUM", override_reason="documented absconding risk",
    )
    assert ovr["derived_level"] == "MEDIUM"
    assert ovr["override_level"] == "MAXIMUM"

    validate_success(api.adopt_risk_assessment(sup["id"], ovr["id"], oh), 200)
    sup_after = validate_success(api.get_supervisee(sup["id"], oh), 200)
    assert sup_after["supervision_level"] == "MAXIMUM", \
        "override raises effective supervision_level to MAXIMUM"


def test_actuarial_band_adoption_sets_derived_level(api):
    """PRD §3.2: "the supervisee's supervision_level is recomputed from this
    assessment's effective level (the override_level when set, otherwise the
    derived_level)"
    PRD §3.2: "a total from 24 through 33 derives MEDIUM"

    With no override, identical 28-point scores set supervision_level to MEDIUM
    (the actuarial band), divergent from the override variant above.

    Design: Difficulty/dual_variant_calc/lsi_r_actuarial_vs_clinical_override_level
    """
    officer = create_officer(role_type="PROBATION")
    sup = open_supervisee(officer["id"], supervision_type="PROBATION")
    oh = make_officer_headers(officer["id"])

    scores = domain_scores_for_total(28)
    base = add_draft_assessment(sup["id"], officer["id"], domain_scores=scores)
    assert base["derived_level"] == "MEDIUM"

    validate_success(api.adopt_risk_assessment(sup["id"], base["id"], oh), 200)
    sup_after = validate_success(api.get_supervisee(sup["id"], oh), 200)
    assert sup_after["supervision_level"] == "MEDIUM", \
        "no override -> supervision_level equals derived_level MEDIUM"


# ─── Difficulty: transitive_cascade / adopt_supersede_level_drop_suspends_condition ──
def test_adopt_lower_assessment_supersedes_prior_and_drops_level(api):
    """PRD §3.2: "any other assessment for the same supervisee that was previously
    ADOPTED transitions to SUPERSEDED; the supervisee's supervision_level is
    recomputed from this assessment's effective level"
    PRD §3.2: "a total of 13 or below derives ADMINISTRATIVE"

    Adopting an ADMINISTRATIVE assessment after a MAXIMUM one supersedes the prior
    and recomputes the root posture downward to ADMINISTRATIVE.

    Design: Difficulty/transitive_cascade/adopt_supersede_level_drop_suspends_condition
    """
    officer = create_officer(role_type="PROBATION")
    sup = open_supervisee(officer["id"], supervision_type="PROBATION")
    oh = make_officer_headers(officer["id"])

    ra_max = add_draft_assessment(sup["id"], officer["id"], total=40)
    assert ra_max["derived_level"] == "MAXIMUM"
    adopt_assessment(sup["id"], ra_max["id"], officer["id"])
    validate_success(api.activate_supervisee(sup["id"], oh), 200)

    ra_admin = add_draft_assessment(sup["id"], officer["id"], total=10)
    validate_success(api.adopt_risk_assessment(sup["id"], ra_admin["id"], oh), 200)

    prior = validate_success(api.get_risk_assessment(sup["id"], ra_max["id"], oh), 200)
    assert prior["assessment_status"] == "SUPERSEDED"
    sup_after = validate_success(api.get_supervisee(sup["id"], oh), 200)
    assert sup_after["supervision_level"] == "ADMINISTRATIVE"


def test_adopt_lower_assessment_force_suspends_over_level_condition(api):
    """PRD §3.2: "any condition that is currently ACTIVE but whose
    minimum_level_required now exceeds the new supervision level is
    force-suspended to SUSPENDED."

    A MEDIUM-required ACTIVE condition is force-suspended when a later
    ADMINISTRATIVE assessment drops the posture below MEDIUM.

    Design: Difficulty/transitive_cascade/adopt_supersede_level_drop_suspends_condition
    """
    officer = create_officer(role_type="PROBATION")
    sup = open_supervisee(officer["id"], supervision_type="PROBATION")
    oh = make_officer_headers(officer["id"])

    ra_max = add_draft_assessment(sup["id"], officer["id"], total=40)
    adopt_assessment(sup["id"], ra_max["id"], officer["id"])
    validate_success(api.activate_supervisee(sup["id"], oh), 200)

    cond = add_active_condition(
        sup["id"], officer["id"],
        condition_type="ELECTRONIC_MONITORING", minimum_level_required="MEDIUM",
    )
    assert cond["status"] == "ACTIVE"

    ra_admin = add_draft_assessment(sup["id"], officer["id"], total=10)
    validate_success(api.adopt_risk_assessment(sup["id"], ra_admin["id"], oh), 200)

    cond_after = validate_success(api.get_condition(sup["id"], cond["id"], oh), 200)
    assert cond_after["status"] == "SUSPENDED"


# ─── Corner: calculations / lsi_r_band_lookup_maximum_boundary ───
def test_lsi_r_band_lookup_maximum_boundary_at_34(api):
    """PRD §3.2: "a total of 34 or above (up through the maximum of 54) derives
    MAXIMUM"
    PRD §3.2: "The assessment's total_score is the sum of all ten domain
    sub-scores"

    A domain-score set summing to exactly 34 (one above MEDIUM's ceiling of 33)
    produces total_score=34 and derived_level=MAXIMUM.

    Design: Corner/calculations/lsi_r_band_lookup_maximum_boundary
    """
    officer = create_officer(role_type="PROBATION")
    sup = open_supervisee(officer["id"], supervision_type="PROBATION")
    oh = make_officer_headers(officer["id"])

    res = api.create_risk_assessment(
        sup["id"],
        create_risk_assessment_payload(domain_scores=domain_scores_for_total(34)),
        oh,
    )
    ra = validate_success(res, 201)
    assert ra["total_score"] == 34
    assert ra["derived_level"] == "MAXIMUM"


def test_lsi_r_band_lookup_medium_just_below_maximum_at_33(api):
    """PRD §3.2: "a total from 24 through 33 derives MEDIUM"

    A total of exactly 33 (the MEDIUM ceiling) derives MEDIUM, confirming the
    34 boundary above is the first MAXIMUM value.

    Design: Corner/calculations/lsi_r_band_lookup_maximum_boundary
    """
    officer = create_officer(role_type="PROBATION")
    sup = open_supervisee(officer["id"], supervision_type="PROBATION")
    oh = make_officer_headers(officer["id"])

    res = api.create_risk_assessment(
        sup["id"],
        create_risk_assessment_payload(domain_scores=domain_scores_for_total(33)),
        oh,
    )
    ra = validate_success(res, 201)
    assert ra["total_score"] == 33
    assert ra["derived_level"] == "MEDIUM"


# ─── Corner: validations / invalid_override_below_derived_rejected ───
def test_override_below_derived_level_rejected(api):
    """PRD §3.2: "An override below the derived level, or an override supplied
    without a reason, is rejected with ERR_INVALID_OVERRIDE (HTTP 422)."

    A 28-point (MEDIUM) assessment with override_level=MINIMUM is rejected.

    Design: Corner/validations/invalid_override_below_derived_rejected
    """
    officer = create_officer(role_type="PROBATION")
    sup = open_supervisee(officer["id"], supervision_type="PROBATION")
    oh = make_officer_headers(officer["id"])

    res = api.create_risk_assessment(
        sup["id"],
        create_risk_assessment_payload(
            domain_scores=domain_scores_for_total(28),
            override_level="MINIMUM", override_reason="too lenient",
        ),
        oh,
    )
    validate_error(res, "ERR_INVALID_OVERRIDE")


# ─── Corner: calculations / lsir_incomplete_domains_rejected ───
def test_incomplete_lsir_domains_rejected(api):
    """PRD §3.2: "If domain_scores does not contain exactly these ten keys, or if
    any value is negative, the request is rejected with
    ERR_INCOMPLETE_LSIR_DOMAINS (HTTP 422)."

    A domain_scores map with only nine of the ten keys is rejected.

    Design: Corner/calculations/lsir_incomplete_domains_rejected
    """
    officer = create_officer(role_type="PROBATION")
    sup = open_supervisee(officer["id"], supervision_type="PROBATION")
    oh = make_officer_headers(officer["id"])

    nine = domain_scores_uniform(1)
    nine.pop("attitudes_orientation")
    res = api.create_risk_assessment(
        sup["id"], create_risk_assessment_payload(domain_scores=nine), oh
    )
    validate_error(res, "ERR_INCOMPLETE_LSIR_DOMAINS")


# ─── Corner: entities / supervisee_computed_fields_ignore_input ───
def test_supervisee_computed_fields_server_initialized(api):
    """PRD §3.1: "the supervisee is minted in INTAKE status with a default
    supervision_level of MINIMUM, a cumulative_violation_points of 0, and both
    restitution_balance_cents and fee_balance_cents at 0."

    Design: Corner/entities/supervisee_computed_fields_ignore_input
    """
    officer = create_officer(role_type="PROBATION")
    oh = make_officer_headers(officer["id"])
    res = api.create_supervisee(
        create_supervisee_payload(officer["id"], docket_number="DK-CMP-1"), oh
    )
    sup = validate_success(res, 201)
    assert sup["supervision_level"] == "MINIMUM"
    assert sup["cumulative_violation_points"] == 0
    assert sup["restitution_balance_cents"] == 0
    assert sup["fee_balance_cents"] == 0
    assert sup["status"] == "INTAKE"
