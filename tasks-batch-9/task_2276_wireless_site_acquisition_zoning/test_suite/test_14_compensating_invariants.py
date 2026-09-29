"""Three ledgers that a compensating action must return to exactly where it started."""

from typing import Any, Dict

from test_helpers import constants as C
from test_helpers import fixtures as S
from test_helpers.api_client import ApiClient
from test_helpers.assertions import assert_fields, assert_money, assert_score, ok
from test_helpers.constants import iso
from test_helpers.test_users import CERTIFIER

FINAL_RENT_AT_BENCHMARK = 562431.16
WINDOW_START = iso("2026-09-01")
WINDOW_END = iso("2026-09-05")
CREW_DAYS = 4
DESIGN_COST_USD = 45000.00


def _accepted_lease(api: ApiClient) -> Dict[str, Any]:
    """An `ACCEPTED` lease at the benchmark rent on an `ACTIVE` landlord."""
    chain = S.engaged_candidate(api)
    lease = S.create_lease(api, chain["cand_id"], chain["ll_id"])
    S.accept_lease(api, lease["id"])
    chain["lease_id"] = lease["id"]
    return chain


def test_execute_then_terminate_returns_the_executed_lease_count_to_zero(
    api: ApiClient,
) -> None:
    """The count is recomputed from the rows, so the compensating action cancels out exactly.

    PRD: "Rollups are always *recomputed from the underlying rows*, never adjusted
    incrementally, so that a compensating action leaves the ledger exactly where it
    started."

    PRD: "Reopening a ring after a selection restores the same `committed_capex_usd`
    the ring had before selection; terminating a lease immediately after executing it
    leaves the landlord's `executed_lease_count` exactly as it was before the
    execution."

    Design: Difficulty/compensating_invariant/execute_then_terminate_conserves_landlord_executed_lease_count
    """
    chain = _accepted_lease(api)

    before = ok(api.get_landlord(chain["ll_id"], headers=S.agent()))
    assert_fields(before, executed_lease_count=0)

    executed = ok(
        api.execute_lease(
            chain["lease_id"], {"execution_date": C.CLOCK_DEFAULT}, headers=S.director()
        )
    )
    assert_money(
        executed["committed_rent_final_usd"],
        FINAL_RENT_AT_BENCHMARK,
        "committed_rent_final_usd",
    )
    mid_landlord = ok(api.get_landlord(chain["ll_id"], headers=S.agent()))
    assert_fields(mid_landlord, executed_lease_count=1)
    mid_candidate = ok(api.get_candidate(chain["cand_id"], headers=S.agent()))
    assert_fields(mid_candidate, acquisition_status="LEASE_EXECUTED")

    ok(
        api.terminate_lease(
            chain["lease_id"],
            {"reason": "landlord withdrew consent"},
            headers=S.director(),
        )
    )

    after = ok(api.get_landlord(chain["ll_id"], headers=S.agent()))
    assert_fields(after, executed_lease_count=0)


def test_termination_keeps_the_priced_rent_while_unwinding_the_candidate_and_ring(
    api: ApiClient,
) -> None:
    """The conserved counter returns to zero without erasing what execution computed.

    PRD: "A `ProgramDirector` terminates an `EXECUTED` lease with a `reason`, moving it
    `EXECUTED → TERMINATED`; this recomputes the landlord's `executed_lease_count`,
    drives the candidate's `acquisition_status` to `RELINQUISHED`, and recomputes the
    ring's `candidate_count` and `committed_capex_usd`."

    PRD: "`candidate_count` tracks the number of candidates attached to the ring whose
    `acquisition_status` is anything other than `RELINQUISHED`, and is recomputed
    whenever a candidate joins the ring or is relinquished or disqualified."

    Design: Difficulty/compensating_invariant/execute_then_terminate_conserves_landlord_executed_lease_count
    """
    chain = _accepted_lease(api)
    S.execute_lease(api, chain["lease_id"])

    terminated = ok(
        api.terminate_lease(
            chain["lease_id"],
            {"reason": "landlord withdrew consent"},
            headers=S.director(),
        )
    )
    assert_fields(terminated, status="TERMINATED")
    assert_money(
        terminated["committed_rent_final_usd"],
        FINAL_RENT_AT_BENCHMARK,
        "committed_rent_final_usd",
    )

    candidate = ok(api.get_candidate(chain["cand_id"], headers=S.agent()))
    assert_fields(candidate, acquisition_status="RELINQUISHED")

    ring = ok(api.get_search_ring(chain["ring_id"], headers=S.director()))
    assert_fields(ring, candidate_count=0)


def _provider_and_candidate(api: ApiClient) -> Dict[str, Any]:
    """A two-crew provider with an empty ledger and one candidate to book against."""
    chain = S.base_reference_data(api)
    candidate = S.create_candidate(api, chain["ring_id"], chain["ll_id"], chain["jur_id"])
    provider = S.create_provider(api)
    chain["cand_id"] = candidate["id"]
    chain["prov_id"] = provider["id"]
    return chain


def test_create_then_cancel_returns_the_committed_crew_days_to_zero(
    api: ApiClient,
) -> None:
    """Booking four crew days and cancelling the booking leaves the ledger at zero.

    PRD: "A provider's `committed_crew_days` is the sum of `crew_days` across that
    provider's orders whose status is `REQUESTED` or `SCHEDULED`; `DELIVERED` and
    `CANCELLED` orders are excluded both from that sum and from the day-coverage
    count."

    PRD: "Each action recomputes the provider's `committed_crew_days`."

    Design: Difficulty/compensating_invariant/order_create_then_cancel_conserves_provider_committed_crew_days
    """
    chain = _provider_and_candidate(api)

    before = ok(api.get_utility_provider(chain["prov_id"], headers=S.cm()))
    assert_fields(before, committed_crew_days=0)

    order = S.create_order(
        api, chain["cand_id"], chain["prov_id"], "POWER", WINDOW_START, WINDOW_END
    )
    booked = ok(api.get_utility_provider(chain["prov_id"], headers=S.cm()))
    assert_fields(booked, committed_crew_days=CREW_DAYS)

    ok(api.order_status_action(order["id"], {"action": "CANCEL"}, headers=S.cm()))

    after = ok(api.get_utility_provider(chain["prov_id"], headers=S.cm()))
    assert_fields(after, committed_crew_days=0)


def test_a_cancelled_order_keeps_its_own_crew_day_width(api: ApiClient) -> None:
    """The ledger drops the row rather than zeroing the width stored on it.

    PRD: "`CANCEL` is accepted from either `REQUESTED` or `SCHEDULED` and moves the
    order to `CANCELLED` from either."

    PRD: "The order's `crew_days` is the whole UTC days spanned by that half-open
    window, discarding any partial day; a window that spans fewer than one whole day
    yields `ERR_INVALID_WINDOW` (422)."

    Design: Difficulty/compensating_invariant/order_create_then_cancel_conserves_provider_committed_crew_days
    """
    chain = _provider_and_candidate(api)
    order = S.create_order(
        api, chain["cand_id"], chain["prov_id"], "POWER", WINDOW_START, WINDOW_END
    )

    cancelled = ok(
        api.order_status_action(order["id"], {"action": "CANCEL"}, headers=S.cm())
    )

    assert_fields(cancelled, status="CANCELLED", crew_days=CREW_DAYS)

    reread = ok(api.get_backhaul_order(order["id"], headers=S.cm()))
    assert_fields(reread, status="CANCELLED", crew_days=CREW_DAYS)


def _design_awaiting_certification(api: ApiClient) -> Dict[str, Any]:
    """A 45000.00 reinforcement design in `PEER_REVIEW` on a `PASS_WITH_MOD` analysis."""
    chain = S.base_reference_data(api)
    candidate = S.create_candidate(api, chain["ring_id"], chain["ll_id"], chain["jur_id"])
    S.rf_qualify(api, candidate["id"])
    analysis = S.create_analysis(
        api,
        candidate["id"],
        analysis_type=C.TIA_222_H,
        existing_load_pct=C.HEAVY_EXISTING_LOAD_PCT,
        appurtenance_count=C.HEAVY_APPURTENANCE_COUNT,
        wind_speed_mph=C.HEAVY_WIND_SPEED_MPH,
        ice_thickness_in=C.HEAVY_ICE_THICKNESS_IN,
    )
    S.complete_analysis(api, analysis["id"])
    design = S.create_design(
        api, analysis["id"], DESIGN_COST_USD, scope="REINFORCEMENT"
    )
    S.submit_design(api, design["id"])
    chain.update({"cand_id": candidate["id"], "md_id": design["id"]})
    return chain


def test_certification_raises_the_ring_capex_ledger_and_clears_the_candidate(
    api: ApiClient,
) -> None:
    """The ledger picks the certified design up, and the certifier is recorded.

    PRD: "`CERTIFY` moves the design `PEER_REVIEW → CERTIFIED`, which is terminal; it
    enforces both halves of the segregation-of-duties rule from §2.11, writes the
    acting `X-User-ID` into `certified_by_user_id`, recomputes the ring's
    `committed_capex_usd`, and clears the candidate `STRUCTURAL_HOLD →
    STRUCTURALLY_CLEARED` when the candidate is in `STRUCTURAL_HOLD`."

    PRD: "A ring's `committed_capex_usd` is the sum of `estimated_cost_usd` across
    every modification design that is `CERTIFIED`, whose backing analysis is
    `COMPLETED`, and whose candidate belongs to that ring and is neither
    `RELINQUISHED` on the acquisition dimension nor `DISQUALIFIED` on the feasibility
    dimension — over all time, with the sum rounded half up to two decimal places."

    Design: Difficulty/compensating_invariant/certify_then_disqualify_conserves_ring_committed_capex
    """
    chain = _design_awaiting_certification(api)

    before = ok(api.get_search_ring(chain["ring_id"], headers=S.director()))
    assert_money(before["committed_capex_usd"], 0.00, "committed_capex_usd")

    certified = ok(
        api.peer_review(chain["md_id"], {"action": "CERTIFY"}, headers=S.certifier())
    )
    assert_fields(certified, status="CERTIFIED", certified_by_user_id=CERTIFIER)

    ring = ok(api.get_search_ring(chain["ring_id"], headers=S.director()))
    assert_money(ring["committed_capex_usd"], DESIGN_COST_USD, "committed_capex_usd")

    candidate = ok(api.get_candidate(chain["cand_id"], headers=S.analyst()))
    assert_fields(candidate, feasibility_status="STRUCTURALLY_CLEARED")


def test_disqualifying_the_candidate_releases_the_same_capex_back_to_the_ring(
    api: ApiClient,
) -> None:
    """The design row stays certified at full cost while the ledger returns to zero.

    PRD: "Because the ledger is always recomputed from the qualifying rows rather than
    adjusted incrementally, a candidate later relinquished or disqualified silently
    releases its certified capex back to the ring's budget."

    PRD: "Anything above 100.00 is a `FAIL`."

    Design: Difficulty/compensating_invariant/certify_then_disqualify_conserves_ring_committed_capex
    """
    chain = _design_awaiting_certification(api)
    S.certify_design(api, chain["md_id"])

    superseding = S.create_analysis(
        api,
        chain["cand_id"],
        analysis_type=C.TIA_222_H,
        existing_load_pct=C.FAIL_EXISTING_LOAD_PCT,
        appurtenance_count=C.FAIL_APPURTENANCE_COUNT,
        wind_speed_mph=C.FAIL_WIND_SPEED_MPH,
        ice_thickness_in=C.FAIL_ICE_THICKNESS_IN,
    )
    failed_analysis = ok(
        api.complete_structural_analysis(superseding["id"], headers=S.analyst())
    )
    assert_score(
        failed_analysis["capacity_utilization_pct"],
        C.FAIL_UTILIZATION_PCT,
        "capacity_utilization_pct",
    )
    assert_fields(failed_analysis, result="FAIL")

    candidate = ok(api.get_candidate(chain["cand_id"], headers=S.analyst()))
    assert_fields(candidate, feasibility_status="DISQUALIFIED")

    ring = ok(api.get_search_ring(chain["ring_id"], headers=S.director()))
    assert_money(ring["committed_capex_usd"], 0.00, "committed_capex_usd")

    design = ok(api.get_modification_design(chain["md_id"], headers=S.designer()))
    assert_fields(design, status="CERTIFIED")
    assert_money(design["estimated_cost_usd"], DESIGN_COST_USD, "estimated_cost_usd")
