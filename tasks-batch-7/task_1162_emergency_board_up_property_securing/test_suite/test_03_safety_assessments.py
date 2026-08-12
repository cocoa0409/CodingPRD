"""Safety assessment scoring, bands, segregation of duties, supersession, and
the securing gate on cleared assessments."""
import pytest

from test_helpers import (
    add_scope_item,
    extend_on_site_job,
    get_job,
    install_scope_item,
    make_subcontractor_headers,
    mitigate_assessment,
    setup_network,
    setup_on_site_job,
    submit_assessment,
    validate_error,
    validate_success,
)


def test_hazard_score_cap_and_bands(api, dispatcher_headers):
    """PRD §3.4: "Each category contributes a fixed weight to the structural risk
    score — collapse 45 points, electrical 25, gas 20, water 15, asbestos 10 —
    and the assessment's `structural_risk_score` is the sum of the weights of the
    listed hazards, capped at 100."
    PRD §3.4: "The `hazard_level` derives from the score with inclusive lower
    bounds: `HIGH` at 70 or above, `MODERATE` at 30 or above but below 70, and
    `LOW` below 30. The flag `moderate_ppe_required` is true exactly when the
    level is `MODERATE`."

    Design: Corner/calculations/hazard_score_cap_and_bands
    """
    net = setup_network(max_concurrent_jobs=5)
    assessor = net["subs"][1]

    # Job 1: all five hazards — 45+25+20+15+10 = 115, capped at 100.
    j1 = extend_on_site_job(net, priority="P3", incident_type="FIRE", with_assessment=False)
    a1 = submit_assessment(j1["job"]["id"], assessor["id"],
                           ["COLLAPSE", "ELECTRICAL", "GAS", "ASBESTOS", "WATER"])
    assert a1["structural_risk_score"] == 100, "115 must cap at 100"
    assert a1["hazard_level"] == "HIGH"
    assert a1["status"] == "MITIGATION_REQUIRED"

    # Job 2: GAS + WATER = 35 -> MODERATE, auto-CLEARED with the PPE flag.
    j2 = extend_on_site_job(net, priority="P3", incident_type="STORM", with_assessment=False)
    a2 = submit_assessment(j2["job"]["id"], assessor["id"], ["GAS", "WATER"])
    assert a2["structural_risk_score"] == 35
    assert a2["hazard_level"] == "MODERATE"
    assert a2["status"] == "CLEARED"
    assert a2["moderate_ppe_required"] is True

    # Job 3: WATER alone = 15 -> LOW, no PPE flag.
    j3 = extend_on_site_job(net, priority="P3", incident_type="VANDALISM", with_assessment=False)
    a3 = submit_assessment(j3["job"]["id"], assessor["id"], ["WATER"])
    assert a3["structural_risk_score"] == 15
    assert a3["hazard_level"] == "LOW"
    assert a3["status"] == "CLEARED"
    assert a3["moderate_ppe_required"] is False


def test_assessment_supersede_on_new_submission(api, dispatcher_headers):
    """PRD §3.4: "Assessments supersede one another: creating a new assessment
    for a job immediately moves any still-open prior assessment of that job — one
    in `SUBMITTED` or `MITIGATION_REQUIRED` — to `SUPERSEDED`."
    PRD §3.4: "Clearing sets the job's `safety_cleared` flag true"

    Design: Corner/state_machines/assessment_supersede_on_new_submission
    """
    ctx = setup_on_site_job(priority="P2", with_assessment=False)
    assessor = ctx["subs"][1]

    first = submit_assessment(ctx["job"]["id"], assessor["id"], ["COLLAPSE", "ELECTRICAL"])
    assert first["status"] == "MITIGATION_REQUIRED", "score 70 must require mitigation"

    second = submit_assessment(ctx["job"]["id"], assessor["id"], ["WATER"])
    assert second["status"] == "CLEARED", "score 15 is below 30 and clears immediately"

    first_after = validate_success(
        api.get_safety_assessment(first["id"], dispatcher_headers), 200)
    assert first_after["status"] == "SUPERSEDED"
    assert get_job(ctx["job"]["id"])["safety_cleared"] is True


def test_segregation_assessor_is_assignee_rejected(api, dispatcher_headers):
    """PRD §3.4: "The creator's `X-User-ID` is recorded as the assessment's
    `assessor_subcontractor_id`; if that equals the job's assigned subcontractor,
    the submission is rejected with `ERR_SEGREGATION_OF_DUTIES` — the crew doing
    the work never grades its own site."

    Design: Corner/rbac/segregation_assessor_is_assignee_rejected
    """
    ctx = setup_on_site_job(priority="P3", with_assessment=False)
    assignee = ctx["assignee"]

    res = api.create_safety_assessment(
        ctx["job"]["id"], {"hazards": ["WATER"]},
        make_subcontractor_headers(assignee["id"]))
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES")
    assert get_job(ctx["job"]["id"])["safety_cleared"] is False


def test_mitigate_by_non_author_forbidden(api, dispatcher_headers):
    """PRD §3.4: "When mitigation is required, the original assessor — and only
    that assessor, else `ERR_FORBIDDEN` — later records completion with a
    `mitigation_note`, moving the assessment `MITIGATION_REQUIRED` → `CLEARED`
    with the same job-level effects."

    Design: Corner/rbac/mitigate_by_non_author_forbidden
    """
    ctx = setup_on_site_job(priority="P3", with_assessment=False)
    assignee = ctx["assignee"]
    assessor = ctx["subs"][1]
    assessment = submit_assessment(ctx["job"]["id"], assessor["id"],
                                   ["COLLAPSE", "ELECTRICAL"])
    assert assessment["status"] == "MITIGATION_REQUIRED"

    # The assignee (a different subcontractor) may not record the mitigation.
    res = api.mitigate_assessment(assessment["id"], {"mitigation_note": "shored by crew"},
                                  make_subcontractor_headers(assignee["id"]))
    validate_error(res, "ERR_FORBIDDEN")
    after = validate_success(api.get_safety_assessment(assessment["id"], dispatcher_headers), 200)
    assert after["status"] == "MITIGATION_REQUIRED"


def test_securing_blocked_until_assessment_cleared(api, dispatcher_headers):
    """PRD §3.5: "the job's `safety_cleared` flag must be true, meaning a cleared
    assessment is on file (`ERR_HAZARD_NOT_MITIGATED`)"
    PRD §3.4: "a score of 70 or more moves it to `MITIGATION_REQUIRED`, while
    anything below 70 moves it straight to `CLEARED`."

    Design: Difficulty/cross_entity_state_dependency/securing_gated_by_cleared_assessment
    """
    ctx = setup_on_site_job(priority="P2", with_assessment=False)
    assignee = ctx["assignee"]
    assessor = ctx["subs"][1]
    assessment = submit_assessment(ctx["job"]["id"], assessor["id"],
                                   ["COLLAPSE", "ELECTRICAL"])

    res = api.complete_securing(ctx["job"]["id"], make_subcontractor_headers(assignee["id"]))
    validate_error(res, "ERR_HAZARD_NOT_MITIGATED")

    mitigate_assessment(assessment["id"], assessor["id"], "shored the sagging header")
    item = add_scope_item(ctx["job"]["id"], kind="BOARD", opening_count=1,
                          width_in=48, height_in=36, door_count=0)
    install_scope_item(item["id"], assignee["id"], opening_count=1,
                       width_in=48, height_in=36, door_count=0)
    res = api.complete_securing(ctx["job"]["id"], make_subcontractor_headers(assignee["id"]))
    secured = validate_success(res, 200)
    assert secured["work_status"] == "SECURED"


def test_high_score_boundary_requires_mitigation(api, dispatcher_headers):
    """PRD §3.4: "The `hazard_level` derives from the score with inclusive lower
    bounds: `HIGH` at 70 or above, `MODERATE` at 30 or above but below 70, and
    `LOW` below 30."
    PRD §3.4: "Clearing sets the job's `safety_cleared` flag true"

    Design: Difficulty/cross_entity_state_dependency/securing_gated_by_cleared_assessment
    """
    ctx = setup_on_site_job(priority="P2", with_assessment=False)
    assessor = ctx["subs"][1]

    # COLLAPSE (45) + ELECTRICAL (25) lands exactly on the inclusive 70 bound.
    assessment = submit_assessment(ctx["job"]["id"], assessor["id"],
                                   ["COLLAPSE", "ELECTRICAL"])
    assert assessment["structural_risk_score"] == 70
    assert assessment["hazard_level"] == "HIGH", "score == 70 is HIGH (inclusive lower bound)"
    assert assessment["status"] == "MITIGATION_REQUIRED"
    assert get_job(ctx["job"]["id"])["safety_cleared"] is False

    cleared = mitigate_assessment(assessment["id"], assessor["id"], "shored the sagging header")
    assert cleared["status"] == "CLEARED"
    assert get_job(ctx["job"]["id"])["safety_cleared"] is True
