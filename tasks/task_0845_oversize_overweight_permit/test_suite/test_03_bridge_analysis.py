"""Bridge analysis: dual rating methods (LFR/LRFR), the CONDITIONAL->CLEARED
branch, cross-entity approval gating on analysis status, and analysis-state
errors.
"""
import pytest

from test_helpers import (
    TEST_USERS, make_carrier_headers,
    validate_success, validate_error,
    ApiErrorId,
    new_carrier, new_structure, new_permit, add_segment, submit, begin_review,
    first_bridge_analysis_id, review_bridge,
)

OFFICER = TEST_USERS["permit_officer_headers"]


def _permit_crossing_under_review(api, structure, gross=120000,
                                  cross_start="2026-06-05T10:00:00Z",
                                  cross_end="2026-06-05T10:30:00Z"):
    carrier = new_carrier(api)
    permit = new_permit(api, carrier["id"], gross_weight_lbs=gross)
    add_segment(api, permit["id"], carrier["id"], structure_id=structure["id"],
                planned_cross_start_utc=cross_start, planned_cross_end_utc=cross_end)
    submit(api, permit["id"], carrier["id"])
    begin_review(api, permit["id"], actor="officer")
    ba_id = first_bridge_analysis_id(api, permit["id"])
    return carrier, permit["id"], ba_id


# ---------------------------------------------------------------------------
# Difficulty: dual_variant_calc / bridge_lfr_vs_lrfr_rating
# ---------------------------------------------------------------------------
def test_bridge_rating_lfr(api):
    """PRD §3.4: "The two factors depend on the method: `LFR` uses a dead-load
    factor of 1.30 and a live-load factor of 2.17, while `LRFR` uses a dead-load
    factor of 1.25 and a live-load factor of 1.75 — so the same structure and load
    yield a different rating factor under each method."
    PRD §3.4: "a factor of at least 1.00 clears it, moving the status to
    `CLEARED`".

    Design: Difficulty/dual_variant_calc/bridge_lfr_vs_lrfr_rating
    """
    structure = new_structure(api, rated_capacity_tonnage=200, dead_load_tonnage=40)
    _c, _p, ba_id = _permit_crossing_under_review(api, structure, gross=120000)
    ba = review_bridge(api, ba_id, method="LFR")
    assert ba["rating_factor"] == pytest.approx(1.1367, abs=1e-4)
    assert ba["status"] == "CLEARED"


def test_bridge_rating_lrfr_differs(api):
    """PRD §3.4: "`LFR` uses a dead-load factor of 1.30 and a live-load factor of
    2.17, while `LRFR` uses a dead-load factor of 1.25 and a live-load factor of
    1.75 — so the same structure and load yield a different rating factor under
    each method."

    Design: Difficulty/dual_variant_calc/bridge_lfr_vs_lrfr_rating
    """
    structure = new_structure(api, rated_capacity_tonnage=200, dead_load_tonnage=40)
    _c1, _p1, ba1 = _permit_crossing_under_review(api, structure, gross=120000,
                                                  cross_start="2026-06-05T10:00:00Z",
                                                  cross_end="2026-06-05T10:30:00Z")
    _c2, _p2, ba2 = _permit_crossing_under_review(api, structure, gross=120000,
                                                  cross_start="2026-06-06T10:00:00Z",
                                                  cross_end="2026-06-06T10:30:00Z")
    lfr = review_bridge(api, ba1, method="LFR")
    lrfr = review_bridge(api, ba2, method="LRFR")
    assert lrfr["rating_factor"] == pytest.approx(1.4286, abs=1e-4)
    assert lrfr["status"] == "CLEARED"
    assert lfr["rating_factor"] != lrfr["rating_factor"]


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine / bridge_conditional_then_cleared_branch
# ---------------------------------------------------------------------------
def test_bridge_review_conditional_branch(api):
    """PRD §3.4: "a factor of at least 0.90 but below 1.00 makes it `CONDITIONAL`
    and records a `conditions_note` describing the restriction (for example
    reduced speed or single-lane crossing)".

    Design: Difficulty/non_linear_state_machine/bridge_conditional_then_cleared_branch
    """
    structure = new_structure(api, rated_capacity_tonnage=130, dead_load_tonnage=20)
    _c, _p, ba_id = _permit_crossing_under_review(api, structure, gross=100000)
    ba = review_bridge(api, ba_id, method="LFR")
    assert ba["rating_factor"] == pytest.approx(0.9585, abs=1e-4)
    assert ba["status"] == "CONDITIONAL"


def test_bridge_accept_conditions_clears(api):
    """PRD §3.4: "When an analysis is `CONDITIONAL`, the owning carrier may accept
    the conditions, which advances the analysis to `CLEARED` so that it counts as
    cleared for approval."

    Design: Difficulty/non_linear_state_machine/bridge_conditional_then_cleared_branch
    """
    structure = new_structure(api, rated_capacity_tonnage=130, dead_load_tonnage=20)
    carrier, _p, ba_id = _permit_crossing_under_review(api, structure, gross=100000)
    review_bridge(api, ba_id, method="LFR")
    resp = api.accept_conditions(ba_id, make_carrier_headers(carrier["id"]))
    ba = validate_success(resp, 200)
    assert ba["status"] == "CLEARED"


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency / approve_requires_all_bridges_cleared
# ---------------------------------------------------------------------------
def test_approve_blocked_by_unreviewed_bridge(api):
    """PRD §3.6: "Next, every bridge analysis must be `CLEARED` — none may still
    be `REQUESTED` or `CONDITIONAL` (that is, pending) — or approval is refused
    with `ERR_BRIDGE_ANALYSIS_INCOMPLETE`."

    Design: Difficulty/cross_entity_state_dependency/approve_requires_all_bridges_cleared
    """
    structure = new_structure(api, rated_capacity_tonnage=200, dead_load_tonnage=40)
    _c, permit_id, _ba = _permit_crossing_under_review(api, structure, gross=120000)
    resp = api.approve_permit(permit_id, OFFICER)
    validate_error(resp, ApiErrorId.ERR_BRIDGE_ANALYSIS_INCOMPLETE)


def test_approve_blocked_leaves_permit_in_review(api):
    """PRD §3.6: "Next, every bridge analysis must be `CLEARED` — none may still
    be `REQUESTED` or `CONDITIONAL` (that is, pending) — or approval is refused
    with `ERR_BRIDGE_ANALYSIS_INCOMPLETE`."

    Design: Difficulty/cross_entity_state_dependency/approve_requires_all_bridges_cleared
    """
    structure = new_structure(api, rated_capacity_tonnage=200, dead_load_tonnage=40)
    _c, permit_id, _ba = _permit_crossing_under_review(api, structure, gross=120000)
    api.approve_permit(permit_id, OFFICER)
    permit = validate_success(api.get_permit(permit_id, OFFICER), 200)
    assert permit["status"] == "UNDER_STANDARD_REVIEW"


# ---------------------------------------------------------------------------
# Corner: validations / error_bridge_rejected_on_approve
# ---------------------------------------------------------------------------
def test_bridge_rejected_blocks_approve(api):
    """PRD §3.6: "First, no bridge analysis for the permit may be `REJECTED`; if
    one is, approval is refused with `ERR_BRIDGE_REJECTED`."
    PRD §3.4: "a factor below 0.90 rejects it, moving the status to `REJECTED`".

    Design: Corner/validations/error_bridge_rejected_on_approve
    """
    structure = new_structure(api, rated_capacity_tonnage=100, dead_load_tonnage=50)
    _c, permit_id, ba_id = _permit_crossing_under_review(api, structure, gross=120000)
    ba = review_bridge(api, ba_id, method="LFR")
    assert ba["status"] == "REJECTED"
    resp = api.approve_permit(permit_id, OFFICER)
    validate_error(resp, ApiErrorId.ERR_BRIDGE_REJECTED)


# ---------------------------------------------------------------------------
# Corner: state_machines / error_accept_conditions_on_requested_analysis
# ---------------------------------------------------------------------------
def test_accept_conditions_on_requested_rejected(api):
    """PRD §3.4: "When an analysis is `CONDITIONAL`, the owning carrier may accept
    the conditions, which advances the analysis to `CLEARED`".
    PRD §2.10: "the state-machine precondition that the target is in a state from
    which the transition is defined (... `ERR_INVALID_ANALYSIS_STATE` ...)".

    Design: Corner/state_machines/error_accept_conditions_on_requested_analysis
    """
    structure = new_structure(api, rated_capacity_tonnage=200, dead_load_tonnage=40)
    carrier = new_carrier(api)
    permit = new_permit(api, carrier["id"], gross_weight_lbs=120000)
    add_segment(api, permit["id"], carrier["id"], structure_id=structure["id"],
                planned_cross_start_utc="2026-06-05T10:00:00Z", planned_cross_end_utc="2026-06-05T10:30:00Z")
    submit(api, permit["id"], carrier["id"])
    ba_id = first_bridge_analysis_id(api, permit["id"])
    resp = api.accept_conditions(ba_id, make_carrier_headers(carrier["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_ANALYSIS_STATE)
