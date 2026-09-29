"""A failing analysis unwinds entitlement, crew bookings and the crew-day ledger."""

from typing import Any, Dict

from test_helpers import constants as C
from test_helpers import fixtures as S
from test_helpers.api_client import ApiClient
from test_helpers.assertions import assert_fields, assert_money, assert_score, ok
from test_helpers.constants import iso

WINDOW_START = iso("2026-09-01")
WINDOW_END = iso("2026-09-05")
CREW_DAYS = 4


def _live_pipeline_with_failing_analysis(api: ApiClient) -> Dict[str, Any]:
    """A cleared candidate under review, with a crew window booked and a FAIL pending."""
    chain = S.executed_lease_chain(api)
    passing = S.run_analysis(api, chain["cand_id"])

    application = S.create_zoning_application(api, chain["cand_id"])
    S.add_visual_simulations(api, application["id"])
    S.submit_zoning_application(api, application["id"])
    S.set_completeness(api, application["id"], "COMPLETE")

    provider = S.create_provider(api)
    order = S.create_order(
        api, chain["cand_id"], provider["id"], "POWER", WINDOW_START, WINDOW_END
    )

    failing = S.create_analysis(
        api,
        chain["cand_id"],
        existing_load_pct=C.FAIL_EXISTING_LOAD_PCT,
        appurtenance_count=C.FAIL_APPURTENANCE_COUNT,
        wind_speed_mph=C.FAIL_WIND_SPEED_MPH,
        ice_thickness_in=C.FAIL_ICE_THICKNESS_IN,
    )
    chain.update(
        {
            "sa_pass": passing["id"],
            "sa_fail": failing["id"],
            "za_id": application["id"],
            "prov_id": provider["id"],
            "order_id": order["id"],
        }
    )
    return chain


def test_a_failing_completion_withdraws_entitlement_and_cancels_the_crew_window(
    api: ApiClient,
) -> None:
    """Each hop is caused by the previous hop, not by the completing call.

    PRD: "Anything above 100.00 is a `FAIL`."

    PRD: "When a structural analysis completes with a failing result, the
    candidate's `feasibility_status` becomes `DISQUALIFIED`."

    PRD: "That disqualification withdraws every zoning application of that
    candidate whose status is not already `APPROVED`, `DENIED`, `DEEMED_GRANTED` or
    `WITHDRAWN`, setting each to `WITHDRAWN`."

    PRD: "Each withdrawn application in turn cancels every backhaul order of the
    same candidate whose status is `REQUESTED` or `SCHEDULED`, setting each to
    `CANCELLED` and recomputing the affected provider's `committed_crew_days`."

    Design: Difficulty/transitive_cascade/structural_fail_cascades_to_backhaul_cancellation_and_crew_ledger
    """
    chain = _live_pipeline_with_failing_analysis(api)

    failed_analysis = ok(
        api.complete_structural_analysis(chain["sa_fail"], headers=S.analyst())
    )

    assert_score(
        failed_analysis["capacity_utilization_pct"],
        C.FAIL_UTILIZATION_PCT,
        "capacity_utilization_pct",
    )
    assert_fields(failed_analysis, result="FAIL", status="COMPLETED")

    candidate = ok(api.get_candidate(chain["cand_id"], headers=S.director()))
    assert_fields(candidate, feasibility_status="DISQUALIFIED")

    application = ok(api.get_zoning_application(chain["za_id"], headers=S.director()))
    assert_fields(application, status="WITHDRAWN")

    order = ok(api.get_backhaul_order(chain["order_id"], headers=S.director()))
    assert_fields(order, status="CANCELLED", crew_days=CREW_DAYS)


def test_the_cascade_releases_the_provider_and_ring_ledgers(api: ApiClient) -> None:
    """Cancelled crew days leave the provider ledger, and the prior analysis is superseded.

    PRD: "A provider's `committed_crew_days` is the sum of `crew_days` across that
    provider's orders whose status is `REQUESTED` or `SCHEDULED`; `DELIVERED` and
    `CANCELLED` orders are excluded both from that sum and from the day-coverage
    count."

    PRD: "Any prior analysis of the same candidate is superseded — a prior analysis
    in `IN_PROGRESS` moves `IN_PROGRESS → SUPERSEDED` and one in `COMPLETED` moves
    `COMPLETED → SUPERSEDED`, `SUPERSEDED` being terminal."

    PRD: "The disqualification also recomputes the ring's `candidate_count` and
    `committed_capex_usd`, and if the disqualified candidate was the ring's
    `selected_candidate_id`, the ring's `selected_candidate_id` is cleared to null
    and its `status` returns to `OPEN`."

    Design: Difficulty/transitive_cascade/structural_fail_cascades_to_backhaul_cancellation_and_crew_ledger
    """
    chain = _live_pipeline_with_failing_analysis(api)

    booked = ok(api.get_utility_provider(chain["prov_id"], headers=S.cm()))
    assert_fields(booked, committed_crew_days=CREW_DAYS)

    ok(api.complete_structural_analysis(chain["sa_fail"], headers=S.analyst()))

    released = ok(api.get_utility_provider(chain["prov_id"], headers=S.cm()))
    assert_fields(released, committed_crew_days=0)

    superseded = ok(api.get_structural_analysis(chain["sa_pass"], headers=S.analyst()))
    assert_fields(superseded, status="SUPERSEDED")

    ring = ok(api.get_search_ring(chain["ring_id"], headers=S.director()))
    assert_money(ring["committed_capex_usd"], 0.00, "committed_capex_usd")
