"""Enforcement actions, penalty assessment cascades, and the certify precedence
pair.

Covers the penalty → facility/source/permit cascade, the suspended-beats-
unresolved precedence, the late-exceedance penalty escalation, and the variance
branch.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    setup_facility_with_source, register_operating_source, register_facility,
    setup_issued_permit, setup_submitted_inventory, create_enforcement_action,
    create_exceedance, current_facility_version,
    make_facility_operator_headers, TEST_USERS,
)

REVIEWER = TEST_USERS["permit_reviewer_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]
ENFORCER = TEST_USERS["enforcement_officer_headers"]


# ─── transitive_cascade / penalty_assessment_cascades_facility_and_sources ───

def test_penalty_suspends_facility_and_operating_source(api):
    """PRD §3.7: "Assessing the penalty moves the action INITIATED →
    PENALTY_ASSESSED, drives the facility to SUSPENDED, suspends every OPERATING
    source, and revokes every ISSUED permit, exactly as described in §2.7." PRD
    §3.7: "The penalty is 250,000 cents multiplied by the severity tier, plus
    50,000 cents for each whole day late, and is then capped at 2,500,000 cents."

    Design: Difficulty/transitive_cascade/penalty_assessment_cascades_facility_and_sources
    """
    facility, source = register_operating_source("Golf Co", max_hourly_rate_lbs=50)
    op = make_facility_operator_headers(facility["id"])
    action = create_enforcement_action(facility["id"], action_type="PENALTY", origin="MANUAL")
    assessed = validate_success(api.assess_penalty(action["id"], ENFORCER), 200)
    assert assessed["status"] == "PENALTY_ASSESSED"
    assert assessed["penalty_cents"] == 250000
    fac = validate_success(api.get_facility(facility["id"], op), 200)
    assert fac["compliance_status"] == "SUSPENDED"
    src = validate_success(api.get_source(source["id"], op), 200)
    assert src["lifecycle_status"] == "SUSPENDED"


def test_penalty_revokes_issued_permit(api):
    """PRD §2.7: "When a penalty is assessed, the facility moves to SUSPENDED, every
    one of its emission sources whose lifecycle_status is OPERATING moves to
    SUSPENDED, and any ISSUED permit on the facility moves to REVOKED."

    Design: Difficulty/transitive_cascade/penalty_assessment_cascades_facility_and_sources
    """
    facility, source = setup_facility_with_source(
        "Golf Permit Co", max_hourly_rate_lbs=10, operating_hours_per_year=8760, permit_limit_ppm=50)
    permit, notice = setup_issued_permit(facility["id"], "PERMIT_BY_RULE")
    action = create_enforcement_action(facility["id"], action_type="PENALTY", origin="MANUAL")
    validate_success(api.assess_penalty(action["id"], ENFORCER), 200)
    revoked = validate_success(api.get_permit(permit["id"], REVIEWER), 200)
    assert revoked["status"] == "REVOKED"


# ─── priority_pair_validation_conflict / certify_suspended_beats_unresolved_exceedance ───

def test_certify_suspended_beats_unresolved_exceedance(api):
    """PRD §2.10: "(6) the cross-entity facility-not-suspended gate where it
    applies, else ERR_FACILITY_SUSPENDED (409); ... (8) the unresolved-exceedance
    gate for certification, else ERR_UNRESOLVED_EXCEEDANCE (409)".

    Design: Difficulty/priority_pair_validation_conflict/certify_suspended_beats_unresolved_exceedance
    """
    facility, source = setup_facility_with_source("Hotel Co", max_hourly_rate_lbs=50)
    inv = setup_submitted_inventory(facility["id"], source["id"], [10.000])
    create_exceedance(source["id"], detected_at="2026-03-01T00:00:00Z",
                      event_type="EXCEEDANCE", magnitude_pct=20)
    action = create_enforcement_action(facility["id"], action_type="PENALTY", origin="MANUAL")
    validate_success(api.assess_penalty(action["id"], ENFORCER), 200)
    res = api.certify_inventory(
        inv["id"], {"expected_facility_version": current_facility_version(facility["id"])}, REVIEWER)
    validate_error(res, "ERR_FACILITY_SUSPENDED")


def test_certify_on_suspended_facility_rejected(api):
    """PRD §3.8: "Certifying an inventory ... is allowed ... only while the
    facility's compliance_status is not SUSPENDED (otherwise
    ERR_FACILITY_SUSPENDED)".

    Design: Difficulty/priority_pair_validation_conflict/certify_suspended_beats_unresolved_exceedance
    """
    facility, source = setup_facility_with_source("Hotel Solo Co", max_hourly_rate_lbs=50)
    inv = setup_submitted_inventory(facility["id"], source["id"], [10.000])
    action = create_enforcement_action(facility["id"], action_type="PENALTY", origin="MANUAL")
    validate_success(api.assess_penalty(action["id"], ENFORCER), 200)
    res = api.certify_inventory(
        inv["id"], {"expected_facility_version": current_facility_version(facility["id"])}, REVIEWER)
    validate_error(res, "ERR_FACILITY_SUSPENDED")


# ─── calculations corner ───

def test_late_exceedance_penalty_escalation(api):
    """PRD §3.7: "The penalty starts from a severity tier: the tier is 1 by default,
    becomes 2 when the governing exceedance's magnitude_pct is greater than 10, and
    becomes 3 when that magnitude is greater than 50." PRD §3.7: "The penalty is
    250,000 cents multiplied by the severity tier, plus 50,000 cents for each whole
    day late, and is then capped at 2,500,000 cents."

    Design: Corner/calculations/penalty_late_exceedance_escalation
    """
    facility, source = setup_facility_with_source("Foxtrot2 Co", max_hourly_rate_lbs=50)
    op = make_facility_operator_headers(facility["id"])
    exc = create_exceedance(source["id"], detected_at="2026-03-01T00:00:00Z",
                            event_type="EXCEEDANCE", magnitude_pct=20)
    validate_success(api.set_clock("2026-03-05T00:00:00Z", INSPECTOR), 200)
    validate_success(api.report_exceedance(exc["id"], op), 200)
    data, meta = validate_paginated(api.list_facility_enforcement_actions(facility["id"], ENFORCER))
    action = data[0]
    assessed = validate_success(api.assess_penalty(action["id"], ENFORCER), 200)
    assert assessed["penalty_cents"] == 700000


# ─── state_machines corner ───

def test_variance_granted_branch(api):
    """PRD §3.7: "Granting a variance is allowed only while the action is INITIATED,
    only when its action_type is VARIANCE, and only when variance_start and
    variance_end are supplied with variance_start strictly before variance_end ...
    it moves the action INITIATED → VARIANCE_GRANTED".

    Design: Corner/state_machines/enforcement_variance_granted_branch
    """
    facility = register_facility(name="Bravo2 Co")
    action = create_enforcement_action(facility["id"], action_type="VARIANCE", origin="MANUAL")
    granted = validate_success(api.grant_variance(action["id"], {
        "variance_start": "2026-04-01T00:00:00Z",
        "variance_end": "2026-05-01T00:00:00Z",
    }, ENFORCER), 200)
    assert granted["status"] == "VARIANCE_GRANTED"
