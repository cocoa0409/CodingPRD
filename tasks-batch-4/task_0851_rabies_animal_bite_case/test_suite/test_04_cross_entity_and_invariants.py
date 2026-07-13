"""Depth probes: cross-entity state dependencies and compensating-action
invariants.

Covers Difficulty rules cross_entity_state_dependency and
compensating_invariant.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    make_owner_headers,
    setup_active_facility_order,
    setup_pep_initiated,
    setup_citation_issued,
    euthanize_animal,
    submit_specimen,
    report_result,
    refetch_case,
    refetch_animal,
    refetch_facility,
    refetch_owner,
    set_clock,
)


# ---------------------------------------------------------------------------
# cross_entity_state_dependency / case_cleared_depends_on_quarantine_completed
# ---------------------------------------------------------------------------
def test_case_stays_observation_pending_before_completion(api):
    """PRD §3.3: "A successful issuance creates the `QuarantineOrder` in status
    `ACTIVE`, sets its `actual_release_date` to null and its
    `observation_outcome` to `PENDING`, moves the referenced animal from
    `REPORTED` or `CAPTURED` to `UNDER_OBSERVATION`, moves the bite case from
    `OPEN` to `OBSERVATION_PENDING`, and increments the bite case's `version` by
    one."

    Design: Difficulty/cross_entity_state_dependency/case_cleared_depends_on_quarantine_completed
    """
    state = setup_active_facility_order(vaccination_status="CURRENT", region_code="RB-CE1")
    assert refetch_case(state["case"]["id"])["status"] == "OBSERVATION_PENDING"
    assert refetch_animal(state["animal"]["id"])["status"] == "UNDER_OBSERVATION"


def test_case_cleared_after_quarantine_completed(api, veterinarian_headers):
    """PRD §3.4: "On success the order moves from `ACTIVE` to `COMPLETED`, its
    `actual_release_date` is set to the clock's current value, its
    `boarding_cost_cents` is recomputed to the actual variant, the animal moves
    from `UNDER_OBSERVATION` to `RELEASED` with its `disposition` set to
    `RELEASED`, the bite case moves from `OBSERVATION_PENDING` to `CLEARED`, and
    for a facility order the facility's `current_occupancy` is decreased by one."

    Design: Difficulty/cross_entity_state_dependency/case_cleared_depends_on_quarantine_completed
    """
    state = setup_active_facility_order(vaccination_status="CURRENT", region_code="RB-CE1b")
    set_clock("2026-03-11T00:00:00Z")
    order = validate_success(api.complete_quarantine_order(
        state["order"]["id"], {"observation_outcome": "HEALTHY"}, veterinarian_headers), 200)
    assert order["status"] == "COMPLETED"
    assert refetch_case(state["case"]["id"])["status"] == "CLEARED"
    assert refetch_animal(state["animal"]["id"])["status"] == "RELEASED"


# ---------------------------------------------------------------------------
# cross_entity_state_dependency / pep_discontinue_depends_on_animal_cleared
# ---------------------------------------------------------------------------
def test_discontinue_blocked_when_animal_not_cleared(api, epidemiologist_headers):
    """PRD §3.6: "Discontinuation requires cross-entity clearance — the case's
    animal must be `RELEASED`, or the case must have a specimen whose `result` is
    `NEGATIVE` — and this clearance check has precedence over the state check;
    absent clearance the request is rejected with `ERR_ANIMAL_NOT_CLEARED`, and
    if the recommendation is not `INITIATED` it is rejected with
    `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/pep_discontinue_depends_on_animal_cleared
    """
    state = setup_pep_initiated(wound_category="CATEGORY_II", doses=1, region_code="RB-CE2")
    resp = api.discontinue_pep(state["pep"]["id"], epidemiologist_headers)
    validate_error(resp, ApiErrorId.ERR_ANIMAL_NOT_CLEARED)
    # The recommendation is untouched.
    peps, _ = validate_paginated(
        api.list_pep_recommendations(state["case"]["id"], epidemiologist_headers))
    by_id = {p["id"]: p for p in peps}
    assert by_id[state["pep"]["id"]]["status"] == "INITIATED"


def test_discontinue_allowed_after_negative_specimen(api, epidemiologist_headers):
    """PRD §3.6: "Discontinuation moves the recommendation to the terminal
    `DISCONTINUED` and fixes `final_cost_cents` at the actual doses
    administered."
    PRD §3.5: "A `NEGATIVE` result moves the case from `LAB_PENDING` to
    `CLEARED`, and any active `INITIATED` PEP recommendation on the case becomes
    eligible for discontinuation because the animal is cleared."

    Design: Difficulty/cross_entity_state_dependency/pep_discontinue_depends_on_animal_cleared
    """
    state = setup_pep_initiated(wound_category="CATEGORY_II", doses=1, region_code="RB-CE2b")
    # Establish clearance: euthanize the animal, submit and negatively result a specimen.
    euthanize_animal(state["animal"]["id"])
    specimen = submit_specimen(state["case"]["id"], state["animal"]["id"], condition="SATISFACTORY")
    report_result(specimen["id"], "NEGATIVE")
    pep = validate_success(api.discontinue_pep(state["pep"]["id"], epidemiologist_headers), 200)
    assert pep["status"] == "DISCONTINUED"


# ---------------------------------------------------------------------------
# compensating_invariant / facility_occupancy_conserved_on_issue_then_complete
# ---------------------------------------------------------------------------
def test_facility_occupancy_one_while_order_active(api):
    """PRD §3.3: "A facility begins with `current_occupancy` of zero, which is
    the count of its quarantine orders currently `ACTIVE`; occupancy is
    recomputed when an order activates and on every terminal transition of one
    of its orders."

    Design: Difficulty/compensating_invariant/facility_occupancy_conserved_on_issue_then_complete
    """
    state = setup_active_facility_order(vaccination_status="CURRENT", region_code="RB-CI1")
    assert refetch_facility(state["facility"]["id"])["current_occupancy"] == 1


def test_facility_occupancy_restored_to_zero_after_completion(api, veterinarian_headers):
    """PRD §3.4: "On success the order moves from `ACTIVE` to `COMPLETED`, ...
    and for a facility order the facility's `current_occupancy` is decreased by
    one."

    Design: Difficulty/compensating_invariant/facility_occupancy_conserved_on_issue_then_complete
    """
    state = setup_active_facility_order(vaccination_status="CURRENT", region_code="RB-CI1b")
    assert refetch_facility(state["facility"]["id"])["current_occupancy"] == 1
    set_clock("2026-03-11T00:00:00Z")
    validate_success(api.complete_quarantine_order(
        state["order"]["id"], {"observation_outcome": "HEALTHY"}, veterinarian_headers), 200)
    assert refetch_facility(state["facility"]["id"])["current_occupancy"] == 0


# ---------------------------------------------------------------------------
# compensating_invariant / owner_fine_balance_conserved_on_issue_then_dismiss
# ---------------------------------------------------------------------------
def test_owner_outstanding_fines_increase_on_issuance(api):
    """PRD §3.7: "Issuing a citation increases the cited owner's
    `outstanding_fines_cents` and sets the owner's `compliance_status` to
    `DELINQUENT`."

    Design: Difficulty/compensating_invariant/owner_fine_balance_conserved_on_issue_then_dismiss
    """
    state = setup_citation_issued(violations=("NO_CURRENT_VACCINATION", "UNLICENSED_ANIMAL"),
                                  region_code="RB-CI2")
    owner = refetch_owner(state["owner"]["id"])
    assert owner["outstanding_fines_cents"] == 43508
    assert owner["compliance_status"] == "DELINQUENT"


def test_owner_fine_balance_restored_after_dismissal(api, epidemiologist_headers):
    """PRD §3.7: "`DISMISSED` moves it from `CONTESTED` to the terminal
    `DISMISSED` and reduces the owner's `outstanding_fines_cents` by that
    citation's `total_fine_cents`, recomputing `compliance_status`."

    Design: Difficulty/compensating_invariant/owner_fine_balance_conserved_on_issue_then_dismiss
    """
    state = setup_citation_issued(violations=("NO_CURRENT_VACCINATION", "UNLICENSED_ANIMAL"),
                                  region_code="RB-CI2b")
    citation = state["citation"]
    validate_success(api.contest_citation(
        citation["id"], {"reason": "disputed"}, make_owner_headers(state["owner"]["id"])), 200)
    validate_success(api.resolve_citation(
        citation["id"], {"resolution": "DISMISSED"}, epidemiologist_headers), 200)
    owner = refetch_owner(state["owner"]["id"])
    assert owner["outstanding_fines_cents"] == 0
    assert owner["compliance_status"] == "COMPLIANT"
