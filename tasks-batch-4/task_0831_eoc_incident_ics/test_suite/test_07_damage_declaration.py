"""Damage assessment validation, the verified-damage rollup, and the
declaration-threshold boundary that flips declaration eligibility.
"""
from test_helpers import (
    validate_success,
    get_success_data,
    TEST_USERS,
    create_activated_incident,
    create_damage_assessment,
    validate_damage_assessment,
    get_incident,
)

PLAN = TEST_USERS["planning_chief_headers"]


# ─── Difficulty: transitive_cascade / validate_damage_two_hop_declaration ───
def test_validate_damage_updates_verified_total(api):
    """PRD §3.7: "Validating one advances it from `DRAFT` to `VALIDATED`, stamps
    `validated_at`, and recomputes the incident's `total_verified_damage` as the sum of
    `estimated_loss` over the incident's assessments that are in `VALIDATED` status."

    Design: Difficulty/transitive_cascade/validate_damage_two_hop_declaration
    """
    inc = create_activated_incident(name="River Crest", hazard_type="FLOOD")
    da = create_damage_assessment(
        inc["id"], site_name="Water Plant", estimated_loss=5000000, infrastructure_category="CAT_E_BUILDINGS"
    )
    validate_damage_assessment(da["id"])
    assert get_incident(inc["id"])["total_verified_damage"] == 5000000


def test_validate_damage_flips_declaration_eligible(api):
    """PRD §3.7: "The incident's `declaration_status` is then recomputed: it becomes
    `ELIGIBLE` when `total_verified_damage` is at least the declaration threshold of 5,000,000
    dollars, and remains `INELIGIBLE` below that; a total exactly equal to 5,000,000 is `ELIGIBLE`."

    Design: Difficulty/transitive_cascade/validate_damage_two_hop_declaration
    """
    inc = create_activated_incident(name="River Crest", hazard_type="FLOOD")
    da = create_damage_assessment(
        inc["id"], site_name="Water Plant", estimated_loss=5000000, infrastructure_category="CAT_E_BUILDINGS"
    )
    validate_damage_assessment(da["id"])
    assert get_incident(inc["id"])["declaration_status"] == "ELIGIBLE"


# ─── Difficulty: boundary_precision_check / declaration_damage_exact_threshold ───
def test_verified_damage_below_threshold_stays_ineligible(api):
    """PRD §3.7: "it becomes `ELIGIBLE` when `total_verified_damage` is at least the
    declaration threshold of 5,000,000 dollars, and remains `INELIGIBLE` below that; a total
    exactly equal to 5,000,000 is `ELIGIBLE`."

    Design: Difficulty/boundary_precision_check/declaration_damage_exact_threshold
    """
    inc = create_activated_incident(name="Coastal Surge", hazard_type="HURRICANE")
    da1 = create_damage_assessment(
        inc["id"], site_name="Pier 1", estimated_loss=4999999, infrastructure_category="CAT_G_PARKS"
    )
    validate_damage_assessment(da1["id"])
    incident = get_incident(inc["id"])
    assert incident["total_verified_damage"] == 4999999
    assert incident["declaration_status"] == "INELIGIBLE", "4,999,999 is below the 5,000,000 threshold"


def test_verified_damage_at_exact_threshold_flips_eligible(api):
    """PRD §3.7: "it becomes `ELIGIBLE` when `total_verified_damage` is at least the
    declaration threshold of 5,000,000 dollars, and remains `INELIGIBLE` below that; a total
    exactly equal to 5,000,000 is `ELIGIBLE`."

    Design: Difficulty/boundary_precision_check/declaration_damage_exact_threshold
    """
    inc = create_activated_incident(name="Coastal Surge", hazard_type="HURRICANE")
    da1 = create_damage_assessment(
        inc["id"], site_name="Pier 1", estimated_loss=4999999, infrastructure_category="CAT_G_PARKS"
    )
    validate_damage_assessment(da1["id"])
    da2 = create_damage_assessment(
        inc["id"], site_name="Pier 2", estimated_loss=1, infrastructure_category="CAT_G_PARKS"
    )
    validate_damage_assessment(da2["id"])
    incident = get_incident(inc["id"])
    assert incident["total_verified_damage"] == 5000000
    assert incident["declaration_status"] == "ELIGIBLE", "exactly 5,000,000 is ELIGIBLE (>=, not >)"
