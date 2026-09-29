"""Scoring market position: the two assessment variants, the component
arithmetic they share, the supersession they perform and the concurrency guard
that protects the unit they rewrite.
"""
from test_helpers import (
    COUNSEL, ApiErrorId, assert_risk_assessment, create_risk_assessment_payload,
    log_and_escalate_contact, make_business_lead_headers, open_document_audit,
    read_assessment, read_business_unit, read_document_audit,
    record_audit_findings, register_business_unit, register_employee,
    run_assessment, set_clock, unit_version, validate_error, validate_paginated,
    validate_success,
)

# market_share_bps 3000 -> 45, interaction 0 -> 0, overlap 5 -> 1.00: base 46.00
BASE_46_UNIT = {
    "market_share_bps": 3000,
    "interaction_point_count": 0,
    "competitor_overlap_pct": 5,
}


def _unit_with_one_escalated_contact():
    unit = register_business_unit(**BASE_46_UNIT)
    employee = register_employee(unit["id"], role_category="LEGAL")
    contact = log_and_escalate_contact(
        unit["id"], employee["id"], competitor_name="Rivex SA",
        contact_channel="WRITTEN_FORMAL", topic_tags=["STANDARDS"],
        pricing_topic=False, occurred_at="2026-07-20T10:00:00Z")
    return unit, employee, contact


def test_baseline_variant_stores_incident_counters_as_zero(api):
    """PRD §3.3: "Under `BASELINE` — the position-only view used for periodic
    programme reporting — the incident load is forced to zero, and the three
    incident counters `escalated_contact_count`, `flagged_attendance_count` and
    `document_violation_count` are stored on the assessment as zero without ever
    being consulted."
    PRD §3.3: "The `risk_band` follows from the index with lower edges inclusive
    and upper edges exclusive: `LOW` below 25, `MODERATE` from 25 up to but not
    including 50, `HIGH` from 50 up to but not including 75, and `SEVERE` at 75
    and above."

    Design: Difficulty/dual_variant_calc/risk_index_variant_divergence_on_business_unit
    """
    set_clock()
    unit, _employee, _contact = _unit_with_one_escalated_contact()

    baseline = validate_success(api.create_risk_assessment(
        create_risk_assessment_payload(unit["id"], unit_version(unit["id"]),
                                       "BASELINE"),
        COUNSEL), 201)

    assert_risk_assessment(baseline)
    assert baseline["market_risk_index"] == 46.00
    assert baseline["risk_band"] == "MODERATE"
    assert baseline["incident_load"] == 0
    assert baseline["escalated_contact_count"] == 0, (
        "the BASELINE variant never consults the escalated contact count")


def test_incident_adjusted_variant_adds_the_escalated_contact_load(api):
    """PRD §3.3: "The incident load is then 5 points for each escalated contact
    plus 3 points for each flagged attendance plus 2 points for each document
    violation, with the total capped at 25 — whichever is smaller of 25 and that
    weighted sum."
    PRD §3.3: "The assessment is created in `ACTIVE`; the unit's prior `ACTIVE`
    assessment, if there is one, moves to the terminal `SUPERSEDED`; the unit's
    `risk_band` is rewritten to the new assessment's band; the unit's `version`
    increments by 1 and its posture is recomputed."
    PRD §2.8: "Otherwise the posture is `RESTRICTED` when `exposure_points` is
    at least 40.00, **or** when `risk_band` is `HIGH` or `SEVERE`."

    Design: Difficulty/dual_variant_calc/risk_index_variant_divergence_on_business_unit
    """
    set_clock()
    unit, _employee, _contact = _unit_with_one_escalated_contact()
    baseline = run_assessment(unit["id"], "BASELINE")

    adjusted = validate_success(api.create_risk_assessment(
        create_risk_assessment_payload(unit["id"], unit_version(unit["id"]),
                                       "INCIDENT_ADJUSTED"),
        COUNSEL), 201)

    assert adjusted["escalated_contact_count"] == 1
    assert adjusted["incident_load"] == 5
    assert adjusted["market_risk_index"] == 51.00, "46.00 structural base plus 5"
    assert adjusted["risk_band"] == "HIGH"
    assert read_assessment(baseline["id"])["status"] == "SUPERSEDED"

    stored_unit = read_business_unit(unit["id"])
    assert stored_unit["risk_band"] == "HIGH"
    assert stored_unit["posture"] == "RESTRICTED"
    # base 4, written correspondence 0, STANDARDS 0, LEGAL 0, doubled on escalation
    assert stored_unit["exposure_points"] == 8.00


def test_incident_adjusted_collapses_onto_baseline_with_no_incidents(api):
    """PRD §3.3: "Those three components sum to the structural base, which is
    identical under both variants."
    PRD §3.3: "The incident load is then 5 points for each escalated contact
    plus 3 points for each flagged attendance plus 2 points for each document
    violation, with the total capped at 25 — whichever is smaller of 25 and that
    weighted sum."

    Design: Difficulty/boundary_precision_check/risk_variants_converge_on_empty_incident_set
    """
    set_clock()
    unit = register_business_unit(name="Greenfield Pigments", market_code="EU-PIG",
                                  **BASE_46_UNIT)
    baseline = run_assessment(unit["id"], "BASELINE")
    adjusted = run_assessment(unit["id"], "INCIDENT_ADJUSTED")

    assert baseline["market_risk_index"] == 46.00
    assert adjusted["market_risk_index"] == 46.00, (
        "an empty incident set must collapse onto the structural base")
    assert adjusted["incident_load"] == 0
    assert adjusted["escalated_contact_count"] == 0
    assert adjusted["flagged_attendance_count"] == 0
    assert adjusted["document_violation_count"] == 0
    assert adjusted["risk_band"] == "MODERATE"
    assert read_business_unit(unit["id"])["posture"] == "OPEN"


def test_zero_interaction_points_contribute_zero_not_the_cap(api):
    """PRD §3.3: "The `share_component` is a tiered read of the unit's
    `market_share_bps`: 10 points when the share is below 1500 basis points, 25
    points when it is at least 1500 and below 3000, 45 points when it is at
    least 3000 and below 5000, and 70 points once the share reaches 5000 basis
    points — that is, once the unit holds half its relevant market."
    PRD §3.3: "The `interaction_component` charges 3 points for each recurring
    structural interaction point the unit reported, but the component is capped:
    whichever is smaller of 30 and three times `interaction_point_count` is what
    the assessment carries."
    PRD §3.3: "The `overlap_component` weights the unit's
    `competitor_overlap_pct` at one fifth — the percentage multiplied by 0.20 —
    with the product rounded half up to 2 decimal places."

    Design: Difficulty/boundary_precision_check/risk_variants_converge_on_empty_incident_set
    """
    set_clock()
    unit = register_business_unit(name="Greenfield Pigments", market_code="EU-PIG",
                                  **BASE_46_UNIT)

    baseline = run_assessment(unit["id"], "BASELINE")

    assert baseline["share_component"] == 45
    assert baseline["interaction_component"] == 0, (
        "zero interaction points contribute zero, not the cap")
    assert baseline["overlap_component"] == 1.00
    assert baseline["market_risk_index"] == 46.00


def test_interaction_component_saturates_at_its_cap(api):
    """PRD §3.3: "The `interaction_component` charges 3 points for each
    recurring structural interaction point the unit reported, but the component
    is capped: whichever is smaller of 30 and three times
    `interaction_point_count` is what the assessment carries. A unit with eleven
    interaction points and a unit with forty both contribute the capped 30."

    Design: Corner/calculations/risk_index_interaction_component_saturates_at_its_cap
    """
    set_clock()
    unit = register_business_unit(
        name="Saturated Interaction Unit", market_code="EU-SAT",
        market_share_bps=900, interaction_point_count=40,
        competitor_overlap_pct=0)

    assessment = run_assessment(unit["id"], "BASELINE")

    assert assessment["share_component"] == 10
    assert assessment["interaction_component"] == 30, "40 x 3 is held at the cap"
    assert assessment["overlap_component"] == 0.00
    assert assessment["market_risk_index"] == 40.00
    assert assessment["risk_band"] == "MODERATE"
    assert read_business_unit(unit["id"])["posture"] == "OPEN"


def test_stored_assessment_exposes_every_component_of_the_index(api):
    """PRD §3.3: "Each component is stored on the assessment row so the
    arithmetic is auditable after the fact."
    PRD §3.3: "The `overlap_component` weights the unit's
    `competitor_overlap_pct` at one fifth — the percentage multiplied by 0.20 —
    with the product rounded half up to 2 decimal places."

    Design: Corner/entities/risk_assessment_retrieval_exposes_every_index_component
    """
    set_clock()
    unit = register_business_unit(
        name="Component Unit", market_code="EU-CMP", market_share_bps=1500,
        interaction_point_count=4, competitor_overlap_pct=40)
    created = run_assessment(unit["id"], "BASELINE")

    data = validate_success(api.get_risk_assessment(created["id"], COUNSEL))

    assert_risk_assessment(data)
    assert data["share_component"] == 25
    assert data["interaction_component"] == 12
    assert data["overlap_component"] == 8.00
    assert data["market_risk_index"] == 45.00
    assert data["risk_band"] == "MODERATE"
    assert data["status"] == "ACTIVE"


def test_business_lead_may_not_run_a_risk_assessment(api):
    """PRD §2.1: "A syntactically valid role that is simply not listed among an
    endpoint's authorised roles yields `ERR_FORBIDDEN_ROLE` with HTTP 403."
    PRD §2.1: "An `AntitrustCounsel` is corporate antitrust counsel and
    adjudicates everything: association approval and prohibition, participation
    legal clearance, minutes review, competitor-contact review and clearance and
    escalation, market-position risk assessment, HSR analysis and filing,
    document audits, and leniency strategy."

    Design: Corner/rbac/business_lead_cannot_run_a_risk_assessment
    """
    set_clock()
    unit = register_business_unit()
    lead = make_business_lead_headers(unit["id"])

    resp = api.create_risk_assessment(
        create_risk_assessment_payload(unit["id"], unit["version"], "BASELINE"),
        lead)

    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)
    assert resp.status_code == 403

    _rows, meta = validate_paginated(api.list_risk_assessments(
        COUNSEL, params={"business_unit_id": unit["id"]}))
    assert meta["total_count"] == 0
    assert read_business_unit(unit["id"])["risk_band"] == "LOW"


def test_second_assessment_carrying_the_stale_unit_version_is_refused(api):
    """PRD §2.6: "A `POST /compliance/risk-assessments` request must carry
    `expected_business_unit_version` as a required, non-optional field whose
    value is the `version` the client last observed on the target business
    unit."
    PRD §2.6: "If the supplied value does not equal the business unit's current
    `version`, the request is rejected with `ERR_STALE_VERSION` and HTTP 412,
    and no assessment is created."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_business_unit_version_on_risk_assessment_returns_412
    """
    set_clock()
    unit = register_business_unit(**BASE_46_UNIT)
    stale_version = unit_version(unit["id"])

    first = validate_success(api.create_risk_assessment(
        create_risk_assessment_payload(unit["id"], stale_version, "BASELINE"),
        COUNSEL), 201)
    assert first["status"] == "ACTIVE"

    second = api.create_risk_assessment(
        create_risk_assessment_payload(unit["id"], stale_version,
                                       "INCIDENT_ADJUSTED"),
        COUNSEL)
    validate_error(second, ApiErrorId.ERR_STALE_VERSION.value)
    assert second.status_code == 412

    assert read_assessment(first["id"])["status"] == "ACTIVE"
    _rows, meta = validate_paginated(api.list_risk_assessments(
        COUNSEL, params={"business_unit_id": unit["id"]}))
    assert meta["total_count"] == 1, "the refused create persists nothing"
    assert read_business_unit(unit["id"])["risk_band"] == "MODERATE"


def test_closed_audit_violations_feed_the_next_incident_adjusted_assessment(api):
    """PRD §3.8: "Closing the audit also recomputes the unit's
    `document_violation_count` as the sum of `violation_count` across all its
    completed audits and increments the unit's `version` by 1 — which is what
    makes those violations available to the next incident-adjusted risk
    assessment."
    PRD §3.8: "Then the score is 100 minus that rounded ratio minus 2 points for
    each high-risk phrase occurrence, rounded half up to 2 decimal places and
    floored at 0.00 so a badly failing sample bottoms out rather than going
    negative."
    PRD §3.3: "`document_violation_count` sums `violation_count` across the
    unit's `COMPLETED` document audits, with `OPEN` audits excluded."

    Design: Corner/cross_cutting_complexity_layers/document_audit_findings_feed_the_incident_adjusted_variant
    """
    set_clock()
    unit = register_business_unit(name="Document Audit Unit", market_code="EU-DOC",
                                  **BASE_46_UNIT)
    audit = open_document_audit(unit["id"], sample_size=40)

    record_audit_findings(audit["id"], violation_count=4, high_risk_phrase_count=3)

    assert read_document_audit(audit["id"])["guideline_score"] == 84.00
    assert read_business_unit(unit["id"])["document_violation_count"] == 4

    adjusted = run_assessment(unit["id"], "INCIDENT_ADJUSTED")
    assert adjusted["document_violation_count"] == 4
    assert adjusted["incident_load"] == 8, "2 points for each document violation"
    assert adjusted["market_risk_index"] == 54.00
    assert adjusted["risk_band"] == "HIGH"

    baseline = run_assessment(unit["id"], "BASELINE")
    assert baseline["incident_load"] == 0
    assert baseline["market_risk_index"] == 46.00
    assert baseline["risk_band"] == "MODERATE"

    stored_unit = read_business_unit(unit["id"])
    assert stored_unit["risk_band"] == "MODERATE"
    assert stored_unit["posture"] == "OPEN"
