"""Reclassification: the cyclic review loop, direction derivation at submission,
and approval applying the grade and recomputing budget.

Queue A (Difficulty): non_linear_state_machine (reclass revision cycle).
Queue B (Corner): state_machines (direction, approve side effects, invalid
state, requisition close precondition).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, fixtures, factories,
)


# ===========================================================================
# Reclass revision cycle: SUBMITTED <-> UNDER_REVIEW any number of times
# ===========================================================================
def test_reclass_review_return_review_cycles_back_to_under_review(api, comp_headers):
    """PRD §3.7: "from UNDER_REVIEW may return it to SUBMITTED for revision; a
    request may bounce between UNDER_REVIEW and SUBMITTED any number of times."

    Design: Difficulty/non_linear_state_machine/nlsm_reclass_revision_cycle
    """
    g05 = fixtures.create_grade_g05()
    g07 = fixtures.create_grade_g07()
    cc = fixtures.create_cost_center(name="Eng", annual_budget_cents=100000000, fte_cap=5.0)
    pos = fixtures.create_funded_position(cc["id"], g05["id"], title="Engineer", fte=0.5)
    rr = fixtures.submit_reclass(pos["id"], g07["id"])

    fixtures.review_reclass(rr["id"])      # SUBMITTED -> UNDER_REVIEW (v2)
    fixtures.return_reclass(rr["id"])      # UNDER_REVIEW -> SUBMITTED (v3)
    resp = api.review_reclass_request(rr["id"], comp_headers)  # -> UNDER_REVIEW (v4)
    data = validate_success(resp, 200)

    assert data["status"] == "UNDER_REVIEW", \
        f"Expected UNDER_REVIEW after review->return->review, got {data['status']}"


def test_reclass_revision_cycle_increments_version_each_hop(api, comp_headers):
    """PRD §3.7: "Each review-loop and reject transition increments the reclass
    request's version by 1." PRD §3.7: "The request is born SUBMITTED with
    version 1."

    Design: Difficulty/non_linear_state_machine/nlsm_reclass_revision_cycle
    """
    g05 = fixtures.create_grade_g05()
    g07 = fixtures.create_grade_g07()
    cc = fixtures.create_cost_center(name="Eng", annual_budget_cents=100000000, fte_cap=5.0)
    pos = fixtures.create_funded_position(cc["id"], g05["id"], title="Engineer", fte=0.5)
    rr = fixtures.submit_reclass(pos["id"], g07["id"])  # version 1
    fixtures.review_reclass(rr["id"])      # version 2
    fixtures.return_reclass(rr["id"])      # version 3
    final = get_success_data(api.review_reclass_request(rr["id"], comp_headers))  # version 4
    assert final["version"] == 4, \
        f"Expected version 4 after 3 transitions from a v1 create, got {final['version']}"


# ===========================================================================
# Direction derivation at submission (Corner)
# ===========================================================================
def test_submit_reclass_computes_upgrade_and_snapshots_ranks(api, comp_headers):
    """PRD §3.7: "if the target rank is greater than the current rank the
    direction is UPGRADE ... the system snapshots the position's current grade
    rank into from_grade_rank and the target grade's rank into target_grade_rank".

    Design: Corner/state_machines/sm_reclass_direction_upgrade_computed
    """
    g05 = fixtures.create_grade_g05()  # rank 5
    g07 = fixtures.create_grade_g07()  # rank 7
    cc = fixtures.create_cost_center()
    pos = fixtures.create_position(cc["id"], g05["id"], title="P1", fte=0.5)

    resp = api.create_reclass_request(
        pos["id"], factories.create_reclass_request_payload(g07["id"], "promo"), comp_headers
    )
    data = validate_success(resp, 201)
    assert data["direction"] == "UPGRADE", f"Expected UPGRADE, got {data['direction']}"
    assert data["from_grade_rank"] == 5, f"Expected from_grade_rank 5, got {data['from_grade_rank']}"
    assert data["target_grade_rank"] == 7, f"Expected target_grade_rank 7, got {data['target_grade_rank']}"


# ===========================================================================
# Approve applies grade + recomputes budget (Corner)
# ===========================================================================
def test_approve_upgrade_swaps_grade_and_recomputes_committed_cost(api, director_headers):
    """PRD §3.7: "A successful approval sets the request's status to APPROVED,
    repoints the position's grade_id to the target_grade_id, and recomputes the
    position's planned_cost_cents against the new grade's midpoint. If the
    position is FUNDED, the cost center's committed_cost_cents and
    available_budget_cents are recomputed to reflect the new planned basis."

    Design: Corner/state_machines/sm_reclass_approve_applies_grade_and_recomputes_budget
    """
    g07 = fixtures.create_grade_g07()  # mid 12000000
    g09 = fixtures.create_grade_g09()  # mid 18000000
    cc = fixtures.create_cost_center(name="Eng", annual_budget_cents=100000000, fte_cap=5.0)
    pos = fixtures.create_funded_position(cc["id"], g07["id"], title="P1", fte=0.5)
    rr = fixtures.submit_reclass(pos["id"], g09["id"])
    fixtures.review_reclass(rr["id"])

    resp = api.approve_reclass_request(rr["id"], factories.approve_reclass_payload(), director_headers)
    data = validate_success(resp, 200)
    assert data["status"] == "APPROVED", f"Expected APPROVED, got {data['status']}"

    position = fixtures.get_position(pos["id"])
    assert position["grade_id"] == g09["id"], \
        f"grade_id must repoint to G09, got {position['grade_id']}"
    # 18000000 * 0.5 = 9000000.
    assert position["planned_cost_cents"] == 9000000, \
        f"planned_cost must recompute to 9000000, got {position['planned_cost_cents']}"
    cost_center = fixtures.get_cost_center(cc["id"])
    assert cost_center["committed_cost_cents"] == 9000000, \
        f"committed_cost must recompute to 9000000, got {cost_center['committed_cost_cents']}"


# ===========================================================================
# Invalid-state guards (Corner)
# ===========================================================================
def test_approve_reclass_from_submitted_rejected(api, director_headers):
    """PRD §3.7: "From UNDER_REVIEW, an HRDirector renders the final decision —
    approve or reject. Both are permitted only while the request is UNDER_REVIEW."

    Design: Corner/state_machines/sm_reclass_approve_from_submitted_invalid_state
    """
    g05 = fixtures.create_grade_g05()
    g07 = fixtures.create_grade_g07()
    cc = fixtures.create_cost_center(name="Eng", annual_budget_cents=100000000, fte_cap=5.0)
    pos = fixtures.create_funded_position(cc["id"], g05["id"], title="P1", fte=0.5)
    rr = fixtures.submit_reclass(pos["id"], g07["id"])  # SUBMITTED, never reviewed

    resp = api.approve_reclass_request(rr["id"], factories.approve_reclass_payload(), director_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    reclass = get_success_data(api.get_reclass_request(rr["id"], director_headers))
    assert reclass["status"] == "SUBMITTED", \
        f"Reclass must stay SUBMITTED, got {reclass['status']}"


def test_close_requisition_requires_filled_position(api, hrbp_headers):
    """PRD §3.6: "closing is permitted only when the requisition is APPROVED and
    the owning position is FILLED (else ERR_POSITION_NOT_FILLED)."

    Design: Corner/state_machines/sm_requisition_close_requires_filled_position
    """
    grade, cc, pos = fixtures.setup_funded_vacant_position(pos_overrides={"fte": 0.5})
    rq = fixtures.open_requisition(pos["id"], req_type="NEW_HIRE", justification="hire")
    fixtures.approve_requisition(rq["id"])

    # Position still VACANT -> closing rejected.
    resp = api.close_requisition(rq["id"], hrbp_headers)
    validate_error(resp, ApiErrorId.ERR_POSITION_NOT_FILLED.value)

    requisition = get_success_data(api.get_requisition(rq["id"], hrbp_headers))
    assert requisition["status"] == "APPROVED", \
        f"Requisition must stay APPROVED, got {requisition['status']}"
