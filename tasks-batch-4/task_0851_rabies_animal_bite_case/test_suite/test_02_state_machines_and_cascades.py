"""Depth probes: non-linear state machines and transitive cascade chains.

Covers Difficulty rules non_linear_state_machine and transitive_cascade — the
QuarantineOrder branching fork, PEPRecommendation supersede/initiate branches,
the lab-positive depth-4 cascade, and the quarantine-breach depth-3 cascade.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_paginated,
    setup_active_facility_order,
    setup_pep_initiated,
    setup_lab_pending_specimen,
    create_animal,
    create_bite_case,
    create_pep,
    refetch_case,
    refetch_owner,
    refetch_animal,
    refetch_region,
    set_clock,
)


# ---------------------------------------------------------------------------
# non_linear_state_machine / quarantine_order_branching_divergent_side_effects
# ---------------------------------------------------------------------------
def test_breach_branch_issues_citation_and_flags_animal_control(api, animal_control_officer_headers):
    """PRD §3.4: "A breach also triggers an enforcement cascade: the system
    auto-issues a `Citation` to the order's owner carrying the single violation
    `QUARANTINE_BREACH`; that citation increases the owner's
    `outstanding_fines_cents` and drives the owner's `compliance_status` to
    `DELINQUENT`; and the animal's `control_status` is set to
    `DISPATCH_REQUESTED` to trigger animal-control seizure."

    Design: Difficulty/non_linear_state_machine/quarantine_order_branching_divergent_side_effects
    """
    state = setup_active_facility_order(vaccination_status="NONE", region_code="RB-SM1")
    order = validate_success(
        api.breach_quarantine_order(state["order"]["id"], animal_control_officer_headers), 200)
    assert order["status"] == "BREACHED"
    assert refetch_owner(state["owner"]["id"])["compliance_status"] == "DELINQUENT"
    assert refetch_animal(state["animal"]["id"])["control_status"] == "DISPATCH_REQUESTED"


def test_complete_branch_releases_animal_without_citation(api, veterinarian_headers):
    """PRD §3.4: "On success the order moves from `ACTIVE` to `COMPLETED`, its
    `actual_release_date` is set to the clock's current value, its
    `boarding_cost_cents` is recomputed to the actual variant, the animal moves
    from `UNDER_OBSERVATION` to `RELEASED` with its `disposition` set to
    `RELEASED`, the bite case moves from `OBSERVATION_PENDING` to `CLEARED`, and
    for a facility order the facility's `current_occupancy` is decreased by one."

    Design: Difficulty/non_linear_state_machine/quarantine_order_branching_divergent_side_effects
    """
    state = setup_active_facility_order(vaccination_status="CURRENT", region_code="RB-SM1b")
    set_clock("2026-03-11T00:00:00Z")
    order = validate_success(
        api.complete_quarantine_order(
            state["order"]["id"], {"observation_outcome": "HEALTHY"}, veterinarian_headers), 200)
    assert order["status"] == "COMPLETED"
    assert refetch_animal(state["animal"]["id"])["status"] == "RELEASED"
    # The COMPLETED branch issues no citation, so the owner stays COMPLIANT.
    assert refetch_owner(state["owner"]["id"])["compliance_status"] == "COMPLIANT"


# ---------------------------------------------------------------------------
# non_linear_state_machine / pep_recommendation_branching_supersede
# ---------------------------------------------------------------------------
def test_new_recommendation_supersedes_prior_recommended(api, epidemiologist_headers):
    """PRD §3.6: "Creating a recommendation for a case requires the
    `expected_bite_case_version` concurrency guard of Section 2.6; on success any
    prior recommendation on the case that is still `RECOMMENDED` is moved to
    `SUPERSEDED`, a new recommendation is created, and the bite case's `version`
    is incremented by one."

    Design: Difficulty/non_linear_state_machine/pep_recommendation_branching_supersede
    """
    animal = create_animal(species="DOG", animal_class="DOMESTIC",
                           vaccination_status="EXPIRED")
    case = create_bite_case(region_code="RB-SM2", wound_category="CATEGORY_II",
                            animal_id=animal["id"])
    pep1 = create_pep(case["id"], case["version"])
    fresh_version = refetch_case(case["id"])["version"]
    pep2 = validate_success(
        api.create_pep_recommendation(
            case["id"], {"expected_bite_case_version": fresh_version}, epidemiologist_headers), 201)
    # Re-fetch both recommendations via the case list to confirm terminal states.
    peps, _ = validate_paginated(api.list_pep_recommendations(case["id"], epidemiologist_headers))
    by_id = {p["id"]: p for p in peps}
    assert by_id[pep1["id"]]["status"] == "SUPERSEDED"
    assert by_id[pep2["id"]]["status"] == "RECOMMENDED"


def test_recommended_advances_to_initiated_on_first_dose(api, epidemiologist_headers):
    """PRD §3.6: "Administering the first dose is permitted only when the
    recommendation is `RECOMMENDED` and its `indication` is `INITIATE` or
    `DEFER`; it moves the recommendation from `RECOMMENDED` to `INITIATED` and
    sets `doses_administered` to one."

    Design: Difficulty/non_linear_state_machine/pep_recommendation_branching_supersede
    """
    state = setup_pep_initiated(wound_category="CATEGORY_II", doses=0)
    assert state["pep"]["status"] == "RECOMMENDED"
    pep = validate_success(
        api.administer_dose(state["pep"]["id"], {}, epidemiologist_headers), 200)
    assert pep["status"] == "INITIATED"
    assert pep["doses_administered"] == 1


# ---------------------------------------------------------------------------
# transitive_cascade / lab_positive_cascade_depth4
# ---------------------------------------------------------------------------
def test_positive_result_drives_confirmed_rabid_and_outbreak(api, veterinarian_headers):
    """PRD §3.5: "The case moves from `LAB_PENDING` to `CONFIRMED_RABID`. ... The
    surveillance region whose `region_code` equals the case's `region_code` has
    its `confirmed_positive_count` increased by one, and that region's
    `alert_status` is then recomputed (Section 3.8)."
    PRD §3.8: "and `OUTBREAK` when the count is at or above the
    `positive_threshold` (the threshold comparison is inclusive)."

    Design: Difficulty/transitive_cascade/lab_positive_cascade_depth4
    """
    state = setup_lab_pending_specimen(region_code="RB-CASC1", positive_threshold=1)
    specimen = validate_success(
        api.report_result(state["specimen"]["id"],
                          {"test_method": "DFA", "result": "POSITIVE"}, veterinarian_headers), 200)
    assert specimen["status"] == "RESULTED"
    assert refetch_case(state["case"]["id"])["status"] == "CONFIRMED_RABID"
    region = refetch_region(state["region"]["id"])
    assert region["confirmed_positive_count"] == 1
    assert region["alert_status"] == "OUTBREAK"


def test_positive_result_increments_count_to_elevated(api, veterinarian_headers):
    """PRD §3.5: "The surveillance region whose `region_code` equals the case's
    `region_code` has its `confirmed_positive_count` increased by one, and that
    region's `alert_status` is then recomputed (Section 3.8)."
    PRD §3.8: "`ELEVATED` when the count is greater than zero but less than the
    region's `positive_threshold`".

    Design: Difficulty/transitive_cascade/lab_positive_cascade_depth4
    """
    state = setup_lab_pending_specimen(region_code="RB-CASC1b", positive_threshold=3)
    validate_success(
        api.report_result(state["specimen"]["id"],
                          {"test_method": "DFA", "result": "POSITIVE"}, veterinarian_headers), 200)
    region = refetch_region(state["region"]["id"])
    assert region["confirmed_positive_count"] == 1
    assert region["alert_status"] == "ELEVATED"


# ---------------------------------------------------------------------------
# transitive_cascade / quarantine_breach_cascade_depth3
# ---------------------------------------------------------------------------
def test_breach_raises_owner_fines_and_flags_control(api, animal_control_officer_headers):
    """PRD §3.4: "A breach also triggers an enforcement cascade: the system
    auto-issues a `Citation` to the order's owner carrying the single violation
    `QUARANTINE_BREACH`; that citation increases the owner's
    `outstanding_fines_cents` and drives the owner's `compliance_status` to
    `DELINQUENT`; and the animal's `control_status` is set to
    `DISPATCH_REQUESTED` to trigger animal-control seizure."

    Design: Difficulty/transitive_cascade/quarantine_breach_cascade_depth3
    """
    state = setup_active_facility_order(vaccination_status="NONE", region_code="RB-CASC2")
    order = validate_success(
        api.breach_quarantine_order(state["order"]["id"], animal_control_officer_headers), 200)
    assert order["status"] == "BREACHED"
    owner = refetch_owner(state["owner"]["id"])
    assert owner["outstanding_fines_cents"] == 54250
    assert owner["compliance_status"] == "DELINQUENT"
    assert refetch_animal(state["animal"]["id"])["control_status"] == "DISPATCH_REQUESTED"


def test_breach_auto_issues_quarantine_breach_citation(api, animal_control_officer_headers):
    """PRD §3.4: "the system auto-issues a `Citation` to the order's owner
    carrying the single violation `QUARANTINE_BREACH`; that citation increases
    the owner's `outstanding_fines_cents` and drives the owner's
    `compliance_status` to `DELINQUENT`".

    Design: Difficulty/transitive_cascade/quarantine_breach_cascade_depth3
    """
    state = setup_active_facility_order(vaccination_status="NONE", region_code="RB-CASC2b")
    validate_success(
        api.breach_quarantine_order(state["order"]["id"], animal_control_officer_headers), 200)
    citations, _ = validate_paginated(
        api.list_citations(animal_control_officer_headers,
                           params={"owner_id": state["owner"]["id"]}))
    assert len(citations) == 1
    assert citations[0]["violations"] == ["QUARANTINE_BREACH"]
    assert citations[0]["total_fine_cents"] == 54250
    assert citations[0]["status"] == "ISSUED"
