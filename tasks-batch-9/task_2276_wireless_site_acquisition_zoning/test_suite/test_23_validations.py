"""Six guards that refuse a request the surrounding state would otherwise admit."""

from typing import Any, Dict

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as S
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ApiError
from test_helpers.assertions import assert_fields, assert_instant, assert_money, failed, ok
from test_helpers.constants import iso

ROUND_COUNTERS = (2400.00, 2500.00, 2420.00, 2480.00, 2430.00, 2435.00)
SEVENTH_COUNTER = 2432.00
PAST_HEARING_DATE = iso("2026-07-01")
BOOKED_HEARING_DATE = iso("2026-09-15")


def test_a_candidate_whose_landlord_serves_another_market_is_refused(
    api: ApiClient,
) -> None:
    """Market alignment compares the landlord against the ring, not against the agent.

    PRD: "A candidate binds one ring to one landlord and one jurisdiction, and both the
    landlord's `market_code` and the jurisdiction's `market_code` must equal the ring's
    `market_code`; otherwise the candidate is refused with `ERR_MARKET_MISMATCH` (409)."

    PRD: "Market alignment — `ERR_MARKET_MISMATCH`, on candidate creation."

    Design: Corner/validations/corner_candidate_create_market_mismatch_rejected
    """
    S.reset_clock(api)
    jurisdiction = S.create_jurisdiction(api)
    ring = S.create_open_ring(api)
    landlord = S.create_landlord(api, market_code=C.OTHER_MARKET_CODE)

    refused = api.create_candidate(
        F.candidate_payload(
            ring["id"],
            landlord["id"],
            jurisdiction["id"],
            site_type="ROOFTOP",
            agl_m=50,
        ),
        headers=S.agent(),
    )
    failed(refused, ApiError.MARKET_MISMATCH, expected_status=409)

    reread = ok(api.get_search_ring(ring["id"], headers=S.director()))
    assert_fields(reread, candidate_count=0)


def test_outreach_to_a_landlord_who_refused_contact_is_refused(api: ApiClient) -> None:
    """The opt-out flag blocks the event before the state machine is consulted.

    PRD: "The optional `outreach_optout` flag defaults to false; when it is true the
    landlord has refused contact, and both outreach events and lease drafting against
    that landlord are refused with `ERR_LANDLORD_OPTED_OUT`."

    PRD: "Every one of these three events additionally requires that the landlord has
    not opted out and that the acting `X-User-ID` matches `owning_agent_user_id`; a state
    that does not admit the requested event yields `ERR_INVALID_CANDIDATE_STATE`."

    Design: Corner/validations/corner_outreach_to_opted_out_landlord_rejected
    """
    S.reset_clock(api)
    jurisdiction = S.create_jurisdiction(api)
    ring = S.create_open_ring(api)
    landlord = S.create_landlord(api, outreach_optout=True)
    candidate = S.create_candidate(api, ring["id"], landlord["id"], jurisdiction["id"])

    refused = api.add_outreach_event(
        candidate["id"], {"event_type": "OUTREACH_SENT"}, headers=S.agent()
    )
    failed(refused, ApiError.LANDLORD_OPTED_OUT, expected_status=409)

    reread = ok(api.get_candidate(candidate["id"], headers=S.agent()))
    assert_fields(
        reread, acquisition_status="PROSPECTING", outreach_event_count=0, version=1
    )


def test_a_filing_one_simulation_short_of_the_minimum_is_refused(api: ApiClient) -> None:
    """The jurisdiction demands two renderings, so a single simulation blocks submission.

    PRD: "And where the jurisdiction's `requires_visual_simulation` is true, the
    application's `visual_simulation_count` must be at least the jurisdiction's
    `min_visual_simulations`; a shortfall yields `ERR_VISUAL_SIMULATION_REQUIRED` (422)."

    PRD: "Submission stamps `submitted_date` with the logical clock, prices the filing
    fee into `zoning_fee_total_usd`, and computes the initial `shot_clock_deadline_date`."

    Design: Corner/validations/corner_submit_with_insufficient_visual_simulations_rejected
    """
    chain = S.executed_lease_chain(api)
    application = S.create_zoning_application(
        api, chain["cand_id"], application_type="VARIANCE"
    )
    S.add_visual_simulations(api, application["id"], count=1)

    refused = api.submit_zoning_application(application["id"], headers=S.planner())
    failed(refused, ApiError.VISUAL_SIMULATION_REQUIRED, expected_status=422)

    reread = ok(api.get_zoning_application(application["id"], headers=S.planner()))
    assert_fields(reread, status="PREPARING", visual_simulation_count=1)
    assert reread["submitted_date"] is None, "nothing was filed"
    assert reread["zoning_fee_total_usd"] is None, "no fee was priced"
    assert reread["shot_clock_deadline_date"] is None, "no shot clock was started"


def _lease_after_six_rounds(api: ApiClient) -> Dict[str, Any]:
    """A `COUNTERED` lease that has already recorded the six permitted rounds."""
    chain = S.engaged_candidate(api)
    lease = S.create_lease(api, chain["cand_id"], chain["ll_id"])
    actions = ("SUBMIT", "COUNTER", "REVISE", "COUNTER", "REVISE", "COUNTER")
    for action, counter in zip(actions, ROUND_COUNTERS):
        S.lease_round(api, lease["id"], action, counter)
    chain["lease_id"] = lease["id"]
    return chain


def test_a_seventh_negotiation_round_is_refused(api: ApiClient) -> None:
    """Six rounds are on the record, so the legal `REVISE` is stopped by the ceiling.

    PRD: "All three also require that fewer than six rounds have already been recorded;
    a seventh round is refused with `ERR_NEGOTIATION_ROUND_LIMIT`."

    PRD: "`REVISE` records the carrier's revised offer and is accepted only from
    `COUNTERED`, moving the lease to `REVISED`."

    PRD: "All three of these actions require `counter_rent_usd` to be present, store it
    as `last_counter_rent_usd`, increment `round_count` by one, recompute
    `rent_variance_pct`, and increment the lease's `version`."

    Design: Corner/validations/corner_negotiation_round_limit_reached_on_seventh_round
    """
    chain = _lease_after_six_rounds(api)

    refused = api.add_lease_round(
        chain["lease_id"],
        {"action": "REVISE", "counter_rent_usd": SEVENTH_COUNTER},
        headers=S.agent(),
    )
    failed(refused, ApiError.NEGOTIATION_ROUND_LIMIT, expected_status=409)

    lease = ok(api.get_lease(chain["lease_id"], headers=S.agent()))
    assert_fields(lease, status="COUNTERED", round_count=6)
    assert_money(
        lease["last_counter_rent_usd"], ROUND_COUNTERS[-1], "last_counter_rent_usd"
    )


def _application_under_review(api: ApiClient) -> str:
    """A `CONDITIONAL_USE` filing that has cleared its completeness determination."""
    chain = S.executed_lease_chain(api)
    application = S.create_zoning_application(api, chain["cand_id"])
    S.add_visual_simulations(api, application["id"])
    S.submit_zoning_application(api, application["id"])
    S.set_completeness(api, application["id"], "COMPLETE")
    return application["id"]


def test_a_past_hearing_date_and_an_early_hold_are_both_refused(api: ApiClient) -> None:
    """Booking looks forward and holding waits for the clock to arrive.

    PRD: "The requested `hearing_date` must be at or after the current logical clock; an
    earlier date yields `ERR_HEARING_DATE_IN_PAST` (422)."

    PRD: "`HOLD` records that the hearing actually took place, is accepted only from
    `HEARING_SCHEDULED`, requires the logical clock to have reached or passed the stored
    `hearing_date` — an earlier attempt yields `ERR_HEARING_NOT_YET_HELD` — and moves the
    application `HEARING_SCHEDULED → HEARING_HELD` while incrementing
    `hearings_held_count` by one."

    PRD: "`SCHEDULE` books a hearing and is accepted from `UNDER_REVIEW` or from
    `HEARING_HELD`, storing the supplied `hearing_date` and moving the application to
    `HEARING_SCHEDULED`; it does not touch `continuance_count`."

    Design: Corner/validations/corner_hearing_date_guards_reject_past_schedule_and_early_hold
    """
    za_id = _application_under_review(api)

    in_the_past = api.hearing_action(
        za_id,
        {"action": "SCHEDULE", "hearing_date": PAST_HEARING_DATE},
        headers=S.planner(),
    )
    failed(in_the_past, ApiError.HEARING_DATE_IN_PAST, expected_status=422)
    unbooked = ok(api.get_zoning_application(za_id, headers=S.planner()))
    assert_fields(unbooked, status="UNDER_REVIEW")
    assert unbooked["hearing_date"] is None, "the refused request booked nothing"

    booked = ok(
        api.hearing_action(
            za_id,
            {"action": "SCHEDULE", "hearing_date": BOOKED_HEARING_DATE},
            headers=S.planner(),
        )
    )
    assert_fields(booked, status="HEARING_SCHEDULED", hearings_held_count=0)
    assert_instant(booked["hearing_date"], BOOKED_HEARING_DATE, "hearing_date")

    too_early = api.hearing_action(za_id, {"action": "HOLD"}, headers=S.planner())
    failed(too_early, ApiError.HEARING_NOT_YET_HELD, expected_status=409)
    still_scheduled = ok(api.get_zoning_application(za_id, headers=S.planner()))
    assert_fields(still_scheduled, status="HEARING_SCHEDULED", hearings_held_count=0)

    S.set_clock(api, BOOKED_HEARING_DATE)
    held = ok(api.hearing_action(za_id, {"action": "HOLD"}, headers=S.planner()))
    assert_fields(held, status="HEARING_HELD", hearings_held_count=1)


def test_a_cleared_candidate_without_any_permit_cannot_be_marked_build_ready(
    api: ApiClient,
) -> None:
    """Environmental clearance passes; the permit prerequisite is the one that fails.

    PRD: "Past that gate, three prerequisites are checked in order:
    `environmental_cleared` must be true, or `ERR_ENVIRONMENTAL_NOT_CLEARED`;
    `permit_issued` must be true and the candidate must actually have a permit in
    `ISSUED` status, or `ERR_PERMIT_NOT_ISSUED`; and that issued permit must not have
    passed its `expiry_date` at the current logical clock, or `ERR_PERMIT_EXPIRED`."

    PRD: "A utilization of 85.00 or less is a `PASS`."

    PRD: "Completion sets `status` to `COMPLETED` and then acts on the candidate: a
    `PASS` moves the candidate `STRUCTURAL_HOLD → STRUCTURALLY_CLEARED`; a `FAIL` moves
    it `STRUCTURAL_HOLD → DISQUALIFIED` and starts the feasibility cascade of §2.10 — the
    candidate's live zoning applications are withdrawn, that candidate's open backhaul
    orders are cancelled, the affected providers' `committed_crew_days` are recomputed,
    the ring's `candidate_count` and `committed_capex_usd` are recomputed, and the ring's
    selection is cleared if this candidate held it."

    Design: Corner/validations/corner_mark_build_ready_without_permit_rejected
    """
    chain = S.executed_lease_chain(api)
    analysis = S.run_analysis(api, chain["cand_id"])
    assert_fields(analysis, result="PASS", status="COMPLETED")
    assert_money(
        analysis["capacity_utilization_pct"],
        C.BASE_UTILIZATION_PCT,
        "capacity_utilization_pct",
    )
    S.clear_environmental(api, chain["cand_id"])

    refused = api.mark_build_ready(chain["cand_id"], headers=S.cm())
    failed(refused, ApiError.PERMIT_NOT_ISSUED, expected_status=409)

    candidate = ok(api.get_candidate(chain["cand_id"], headers=S.cm()))
    assert_fields(
        candidate,
        feasibility_status="STRUCTURALLY_CLEARED",
        acquisition_status="LEASE_EXECUTED",
        environmental_cleared=True,
        permit_issued=False,
    )
