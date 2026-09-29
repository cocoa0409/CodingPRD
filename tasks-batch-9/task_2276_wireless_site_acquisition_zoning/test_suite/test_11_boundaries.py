"""Threshold equality, an empty selector pool and a ledger one cent over budget."""

from typing import Any, Dict

from test_helpers import constants as C
from test_helpers import fixtures as S
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ApiError
from test_helpers.assertions import assert_fields, assert_money, assert_score, failed, ok

QUALIFY_MIN_SCORE = 55.00
BELOW_MIN_SCORE = 54.80
AT_THRESHOLD_CAPACITY_GBPS = 2.5
BELOW_THRESHOLD_CAPACITY_GBPS = 2.4
EDGE_HALFWAY_DISTANCE_M = 400
GRACE_MONTHS = 6
DESIGN_AT_BUDGET_USD = 250000.00
DESIGN_ONE_CENT_USD = 0.01


def _two_borderline_candidates(api: ApiClient) -> Dict[str, Any]:
    """Two `RAW_LAND` sites identical but for one tenth of a Gbps."""
    chain = S.base_reference_data(api)
    shared = {
        "site_type": "RAW_LAND",
        "distance_from_center_m": EDGE_HALFWAY_DISTANCE_M,
        "agl_m": C.RING_REQUIRED_AGL_M,
        "months_to_availability": GRACE_MONTHS,
        "measured_rsrp_dbm": C.RING_TARGET_RSRP_DBM,
    }
    at_threshold = S.create_candidate(
        api,
        chain["ring_id"],
        chain["ll_id"],
        chain["jur_id"],
        lat=42.3560,
        lon=-71.0660,
        offered_capacity_gbps=AT_THRESHOLD_CAPACITY_GBPS,
        **shared,
    )
    below = S.create_candidate(
        api,
        chain["ring_id"],
        chain["ll_id"],
        chain["jur_id"],
        lat=42.3570,
        lon=-71.0670,
        offered_capacity_gbps=BELOW_THRESHOLD_CAPACITY_GBPS,
        **shared,
    )
    chain["at_id"] = at_threshold["id"]
    chain["below_id"] = below["id"]
    return chain


def test_a_score_of_exactly_the_minimum_qualifies_and_one_step_below_does_not(
    api: ApiClient,
) -> None:
    """55.00 is inclusive; 54.80 falls on the other side of the same comparison.

    PRD: "A score of at least 55.00 moves the feasibility dimension `UNSCREENED →
    RF_QUALIFIED`."

    PRD: "A score below 55.00 moves it `UNSCREENED → DISQUALIFIED` and recomputes the
    ring's `committed_capex_usd`."

    PRD: "For the other two objectives it is 100 multiplied by the candidate's
    `offered_capacity_gbps` divided by the ring's `target_capacity_gbps`, clamped to 0
    through 100."

    Design: Difficulty/boundary_precision_check/rf_score_exactly_at_qualify_minimum_versus_one_step_below
    """
    chain = _two_borderline_candidates(api)

    at_threshold = ok(api.rf_qualify(chain["at_id"], headers=S.rf()))
    below = ok(api.rf_qualify(chain["below_id"], headers=S.rf()))

    assert_score(
        at_threshold["rf_qualification_score"], QUALIFY_MIN_SCORE, "rf_qualification_score"
    )
    assert_fields(at_threshold, feasibility_status="RF_QUALIFIED")

    assert_score(
        below["rf_qualification_score"], BELOW_MIN_SCORE, "rf_qualification_score"
    )
    assert_fields(below, feasibility_status="DISQUALIFIED")


def test_a_disqualifying_score_is_a_result_rather_than_an_error(api: ApiClient) -> None:
    """The failing screen still answers 200, writes the score and leaves capex at zero.

    PRD: "Either way the score is written and the candidate's `version` increments;
    the request is not an error in the failing case, because a disqualifying score is
    a legitimate screening result."

    PRD: "The four components are then combined with fixed weights that sum to one:
    0.35 on the signal component, 0.25 on the distance component, 0.20 on the height
    component and 0.20 on the capacity component."

    PRD: "The resulting figure is clamped to the range 0 through 100 and only then
    rounded, half up, to two decimal places, and stored as
    `rf_qualification_score`."

    Design: Difficulty/boundary_precision_check/rf_score_exactly_at_qualify_minimum_versus_one_step_below
    """
    chain = _two_borderline_candidates(api)
    S.rf_qualify(api, chain["at_id"])

    response = api.rf_qualify(chain["below_id"], headers=S.rf())
    scored = ok(response, expected_status=200)

    assert_score(
        scored["rf_qualification_score"], BELOW_MIN_SCORE, "rf_qualification_score"
    )
    assert scored["version"] > 1, "writing the score increments the candidate's version"

    ring = ok(api.get_search_ring(chain["ring_id"], headers=S.director()))
    assert_money(ring["committed_capex_usd"], 0.00, "committed_capex_usd")


def test_selection_refuses_an_empty_eligible_pool_rather_than_taking_a_near_miss(
    api: ApiClient,
) -> None:
    """An `RF_QUALIFIED` candidate is not in the pool: the pool needs both states at once.

    PRD: "Selection requires the ring to be `OPEN`, requires the
    `expected_search_ring_version` guard of §2.7, and requires at least one candidate
    of that ring to be simultaneously `LEASE_EXECUTED` on the acquisition dimension
    and `BUILD_READY` on the feasibility dimension."

    PRD: "Exactly those candidates form the eligible pool; `RELINQUISHED` and
    `DISQUALIFIED` candidates are excluded, as is any candidate that has not reached
    both states."

    PRD: "If the pool is empty, no candidate is selected, the ring stays `OPEN`, and
    the request is refused with `ERR_NO_ELIGIBLE_CANDIDATE`."

    Design: Difficulty/boundary_precision_check/select_site_on_empty_eligible_pool
    """
    chain = S.base_reference_data(api)
    candidate = S.create_candidate(api, chain["ring_id"], chain["ll_id"], chain["jur_id"])
    S.rf_qualify(api, candidate["id"])

    refused = api.select_site(
        chain["ring_id"],
        {"expected_search_ring_version": S.ring_version(api, chain["ring_id"])},
        headers=S.director(),
    )

    failed(refused, ApiError.NO_ELIGIBLE_CANDIDATE, expected_status=409)


def test_the_refused_selection_leaves_the_ring_open_and_unreopened(api: ApiClient) -> None:
    """No selection is written and no reopen is implied by the refusal.

    PRD: "A new ring begins in `DRAFT` with `candidate_count` at 0,
    `committed_capex_usd` at 0, `reopen_count` at 0 and `selected_candidate_id`
    null."

    PRD: "The winner is written to the ring's `selected_candidate_id`, the ring moves
    `OPEN → SITE_SELECTED`, and `committed_capex_usd` is recomputed."

    Design: Difficulty/boundary_precision_check/select_site_on_empty_eligible_pool
    """
    chain = S.base_reference_data(api)
    candidate = S.create_candidate(api, chain["ring_id"], chain["ll_id"], chain["jur_id"])
    S.rf_qualify(api, candidate["id"])

    failed(
        api.select_site(
            chain["ring_id"],
            {"expected_search_ring_version": S.ring_version(api, chain["ring_id"])},
            headers=S.director(),
        ),
        ApiError.NO_ELIGIBLE_CANDIDATE,
        expected_status=409,
    )

    ring = ok(api.get_search_ring(chain["ring_id"], headers=S.director()))
    assert_fields(ring, status="OPEN", reopen_count=0)
    assert ring["selected_candidate_id"] is None, "no near-miss row is selected"


def _two_designs_against_one_budget(api: ApiClient) -> Dict[str, Any]:
    """Designs of 250000.00 and 0.01 in `PEER_REVIEW` on one ring's budget."""
    chain = S.base_reference_data(api)
    heavy = {
        "existing_load_pct": C.HEAVY_EXISTING_LOAD_PCT,
        "appurtenance_count": C.HEAVY_APPURTENANCE_COUNT,
        "wind_speed_mph": C.HEAVY_WIND_SPEED_MPH,
        "ice_thickness_in": C.HEAVY_ICE_THICKNESS_IN,
    }

    cand_a = S.create_candidate(api, chain["ring_id"], chain["ll_id"], chain["jur_id"])
    S.rf_qualify(api, cand_a["id"])
    cand_b = S.create_candidate(
        api,
        chain["ring_id"],
        chain["ll_id"],
        chain["jur_id"],
        lat=42.3520,
        lon=-71.0630,
        distance_from_center_m=220,
    )
    S.rf_qualify(api, cand_b["id"])

    sa_a = S.create_analysis(api, cand_a["id"], analysis_type=C.TIA_222_H, **heavy)
    S.complete_analysis(api, sa_a["id"])
    sa_b = S.create_analysis(api, cand_b["id"], analysis_type=C.TIA_222_H, **heavy)
    S.complete_analysis(api, sa_b["id"])

    md_a = S.create_design(api, sa_a["id"], DESIGN_AT_BUDGET_USD, scope="REINFORCEMENT")
    S.submit_design(api, md_a["id"])
    md_b = S.create_design(api, sa_b["id"], DESIGN_ONE_CENT_USD, scope="MOUNT_UPGRADE")
    S.submit_design(api, md_b["id"])

    chain.update(
        {
            "cand_a": cand_a["id"],
            "cand_b": cand_b["id"],
            "md_a": md_a["id"],
            "md_b": md_b["id"],
        }
    )
    return chain


def test_a_recomputed_total_exactly_equal_to_the_budget_is_permitted(
    api: ApiClient,
) -> None:
    """Equality passes the ledger gate and the certified design clears its candidate.

    PRD: "Certification is gated on that ledger: if the recomputed
    `committed_capex_usd` including the design being certified would exceed the ring's
    `capex_budget_usd`, certification is refused with `ERR_CAPEX_BUDGET_EXCEEDED`; a
    recomputed total exactly equal to the budget is permitted."

    PRD: "`CERTIFY` moves the design `PEER_REVIEW → CERTIFIED`, which is terminal; it
    enforces both halves of the segregation-of-duties rule from §2.11, writes the
    acting `X-User-ID` into `certified_by_user_id`, recomputes the ring's
    `committed_capex_usd`, and clears the candidate `STRUCTURAL_HOLD →
    STRUCTURALLY_CLEARED` when the candidate is in `STRUCTURAL_HOLD`."

    Design: Difficulty/boundary_precision_check/capex_budget_equality_passes_then_one_cent_over_fails
    """
    chain = _two_designs_against_one_budget(api)

    certified = ok(
        api.peer_review(chain["md_a"], {"action": "CERTIFY"}, headers=S.certifier())
    )
    assert_fields(certified, status="CERTIFIED")

    ring = ok(api.get_search_ring(chain["ring_id"], headers=S.director()))
    assert_money(ring["committed_capex_usd"], DESIGN_AT_BUDGET_USD, "committed_capex_usd")

    candidate = ok(api.get_candidate(chain["cand_a"], headers=S.analyst()))
    assert_fields(candidate, feasibility_status="STRUCTURALLY_CLEARED")


def test_one_cent_over_the_budget_is_refused_and_changes_nothing(api: ApiClient) -> None:
    """The second certification would total 250000.01, so the ledger and design hold still.

    PRD: "A ring's `committed_capex_usd` is the sum of `estimated_cost_usd` across
    every modification design that is `CERTIFIED`, whose backing analysis is
    `COMPLETED`, and whose candidate belongs to that ring and is neither
    `RELINQUISHED` on the acquisition dimension nor `DISQUALIFIED` on the feasibility
    dimension — over all time, with the sum rounded half up to two decimal places."

    PRD: "A `PASS_WITH_MOD` leaves the candidate in `STRUCTURAL_HOLD`: it takes a
    certified modification design to clear it."

    Design: Difficulty/boundary_precision_check/capex_budget_equality_passes_then_one_cent_over_fails
    """
    chain = _two_designs_against_one_budget(api)
    S.certify_design(api, chain["md_a"])

    refused = api.peer_review(
        chain["md_b"], {"action": "CERTIFY"}, headers=S.certifier()
    )
    failed(refused, ApiError.CAPEX_BUDGET_EXCEEDED, expected_status=409)

    design = ok(api.get_modification_design(chain["md_b"], headers=S.designer()))
    assert_fields(design, status="PEER_REVIEW")

    ring = ok(api.get_search_ring(chain["ring_id"], headers=S.director()))
    assert_money(ring["committed_capex_usd"], DESIGN_AT_BUDGET_USD, "committed_capex_usd")

    candidate = ok(api.get_candidate(chain["cand_b"], headers=S.analyst()))
    assert_fields(candidate, feasibility_status="STRUCTURAL_HOLD")
