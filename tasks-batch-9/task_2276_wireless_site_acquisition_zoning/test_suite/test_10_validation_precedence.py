"""When two guards fail at once, the earlier tier is the one the client sees."""

from typing import Any, Dict

from test_helpers import constants as C
from test_helpers import fixtures as S
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ApiError
from test_helpers.assertions import assert_fields, assert_score, failed, ok, setup_data
from test_helpers.test_users import AGENT_OWNER


def _preparing_application(api: ApiClient) -> Dict[str, Any]:
    """A `CONDITIONAL_USE` filing that has never been submitted."""
    chain = S.base_reference_data(api)
    candidate = S.create_candidate(api, chain["ring_id"], chain["ll_id"], chain["jur_id"])
    application = S.create_zoning_application(api, candidate["id"])
    chain["cand_id"] = candidate["id"]
    chain["za_id"] = application["id"]
    return chain


def test_deem_granted_reports_the_zoning_state_not_the_unexpired_shot_clock(
    api: ApiClient,
) -> None:
    """A `PREPARING` filing breaks both guards; the earlier tier decides the response.

    PRD: "Many operations are guarded by several checks at once, and which error a
    client sees is determined by a single, system-wide precedence order."

    PRD: "Checks are evaluated in the order listed; the first failing check produces
    the response and later checks are not reached."

    PRD: "This is accepted from `SUBMITTED`, `UNDER_REVIEW`, `INCOMPLETE`,
    `HEARING_SCHEDULED` or `HEARING_HELD`, and requires the logical clock to be
    **strictly after** `shot_clock_deadline_date`; a clock resting exactly on the
    deadline has not yet run out, and the attempt is refused with
    `ERR_SHOT_CLOCK_NOT_EXPIRED`."

    Design: Difficulty/priority_pair_validation_conflict/deem_granted_state_gate_beats_shot_clock_window
    """
    chain = _preparing_application(api)

    refused = api.deem_granted(chain["za_id"], headers=S.director())

    failed(refused, ApiError.INVALID_ZONING_STATE, expected_status=409)
    assert refused.json()["data"]["error_id"] != ApiError.SHOT_CLOCK_NOT_EXPIRED.value, (
        "the shot-clock tier is never reached"
    )


def test_the_refused_deem_granted_leaves_the_filing_and_candidate_untouched(
    api: ApiClient,
) -> None:
    """No deadline is minted and no dimension moves on a refused declaration.

    PRD: "Zoning application state — `ERR_INVALID_ZONING_STATE`, on exactly six
    operations: attaching a visual simulation, submitting, recording a completeness
    determination, any hearing action, recording a decision, and declaring
    deemed-granted."

    PRD: "On success `decision_date` is stamped with the logical clock, the status
    becomes `DEEMED_GRANTED`, and the candidate is promoted `STRUCTURALLY_CLEARED →
    ENTITLED` when it is in `STRUCTURALLY_CLEARED`."

    Design: Difficulty/priority_pair_validation_conflict/deem_granted_state_gate_beats_shot_clock_window
    """
    chain = _preparing_application(api)

    failed(
        api.deem_granted(chain["za_id"], headers=S.director()),
        ApiError.INVALID_ZONING_STATE,
        expected_status=409,
    )

    application = ok(api.get_zoning_application(chain["za_id"], headers=S.planner()))
    assert_fields(application, status="PREPARING")
    assert application["shot_clock_deadline_date"] is None, (
        "an unsubmitted filing has no shot-clock deadline"
    )

    candidate = ok(api.get_candidate(chain["cand_id"], headers=S.director()))
    assert_fields(candidate, feasibility_status="UNSCREENED")


def _accepted_lease_under_suspended_landlord(api: ApiClient) -> Dict[str, Any]:
    """An `ACCEPTED` lease whose landlord lost good standing after acceptance."""
    chain = S.engaged_candidate(api)
    lease = S.create_lease(api, chain["cand_id"], chain["ll_id"])
    S.accept_lease(api, lease["id"])
    S.set_standing(api, chain["ll_id"], "SUSPENDED", "unresolved title exception")
    chain["lease_id"] = lease["id"]
    return chain


def test_execution_reports_segregation_of_duties_not_the_suspended_landlord(
    api: ApiClient,
) -> None:
    """The negotiating agent's own identity is refused before standing is consulted.

    PRD: "Segregation of duties — `ERR_SEGREGATION_OF_DUTIES`, on exactly two
    operations: lease execution and modification-design peer review."

    PRD: "A lease may not be executed by the agent who negotiated it: if the
    executing `ProgramDirector`'s `X-User-ID` equals the lease's
    `negotiating_agent_user_id`, the execution is refused with
    `ERR_SEGREGATION_OF_DUTIES` (403)."

    PRD: "Only `ACTIVE` standing permits the opening negotiation round or lease
    execution; anything else is refused with `ERR_LANDLORD_NOT_IN_GOOD_STANDING`."

    Design: Difficulty/priority_pair_validation_conflict/execute_segregation_of_duties_beats_landlord_standing
    """
    chain = _accepted_lease_under_suspended_landlord(api)

    refused = api.execute_lease(
        chain["lease_id"],
        {"execution_date": C.CLOCK_DEFAULT},
        headers=S.director(AGENT_OWNER),
    )

    failed(refused, ApiError.SEGREGATION_OF_DUTIES, expected_status=403)
    body = refused.json()["data"]
    assert body["error_id"] != ApiError.LANDLORD_NOT_IN_GOOD_STANDING.value, (
        "the landlord-standing tier is never reached"
    )


def test_the_refused_execution_prices_nothing_and_credits_no_lease(
    api: ApiClient,
) -> None:
    """A 403 leaves the lease `ACCEPTED`, the final rent unpriced and the ledger at zero.

    PRD: "On success the supplied `execution_date` is stored, the final
    committed-rent variant is computed into `committed_rent_final_usd`, the lease
    moves `ACCEPTED → EXECUTED`, the candidate's `acquisition_status` advances
    `LANDLORD_ENGAGED → LEASE_EXECUTED`, and the landlord's `executed_lease_count` is
    recomputed."

    PRD: "The landlord's `executed_lease_count` is, at all times, the count of that
    landlord's leases whose status is `EXECUTED` — recomputed after every execution,
    every termination and every blacklist cascade, and no other status contributes to
    it."

    Design: Difficulty/priority_pair_validation_conflict/execute_segregation_of_duties_beats_landlord_standing
    """
    chain = _accepted_lease_under_suspended_landlord(api)

    failed(
        api.execute_lease(
            chain["lease_id"],
            {"execution_date": C.CLOCK_DEFAULT},
            headers=S.director(AGENT_OWNER),
        ),
        ApiError.SEGREGATION_OF_DUTIES,
        expected_status=403,
    )

    lease = ok(api.get_lease(chain["lease_id"], headers=S.agent()))
    assert_fields(lease, status="ACCEPTED")
    assert lease["committed_rent_final_usd"] is None, (
        "the final variant is priced only at execution"
    )

    landlord = ok(api.get_landlord(chain["ll_id"], headers=S.agent()))
    assert_fields(landlord, executed_lease_count=0)


def test_mark_build_ready_reports_the_candidate_state_not_the_missing_clearance(
    api: ApiClient,
) -> None:
    """The state gate fires first even though the environmental prerequisite also fails.

    PRD: "The state gate admits a candidate whose `feasibility_status` is
    `STRUCTURALLY_CLEARED` or `ENTITLED` and whose `acquisition_status` is
    `LEASE_EXECUTED`; anything else yields `ERR_INVALID_CANDIDATE_STATE`."

    PRD: "Past that gate, three prerequisites are checked in order:
    `environmental_cleared` must be true, or `ERR_ENVIRONMENTAL_NOT_CLEARED`;
    `permit_issued` must be true and the candidate must actually have a permit in
    `ISSUED` status, or `ERR_PERMIT_NOT_ISSUED`; and that issued permit must not have
    passed its `expiry_date` at the current logical clock, or `ERR_PERMIT_EXPIRED`."

    Design: Difficulty/priority_pair_validation_conflict/mark_build_ready_state_gate_beats_environmental_gate
    """
    chain = S.base_reference_data(api)
    candidate = S.create_candidate(api, chain["ring_id"], chain["ll_id"], chain["jur_id"])
    setup_data(api.rf_qualify(candidate["id"], headers=S.rf()))

    refused = api.mark_build_ready(candidate["id"], headers=S.cm())

    failed(refused, ApiError.INVALID_CANDIDATE_STATE, expected_status=409)
    assert (
        refused.json()["data"]["error_id"] != ApiError.ENVIRONMENTAL_NOT_CLEARED.value
    ), "the environmental tier is never reached"


def test_the_refused_build_ready_leaves_both_dimensions_and_the_score_intact(
    api: ApiClient,
) -> None:
    """The candidate keeps its qualification score and gains no clearance.

    PRD: "Candidate dual-dimension state — `ERR_INVALID_CANDIDATE_STATE`, on exactly
    five operations: recording an outreach event, RF qualification, marking
    build-ready, creating a structural analysis, and updating survey inputs."

    PRD: "On success the candidate moves `ENTITLED → BUILD_READY`."

    Design: Difficulty/priority_pair_validation_conflict/mark_build_ready_state_gate_beats_environmental_gate
    """
    chain = S.base_reference_data(api)
    candidate = S.create_candidate(api, chain["ring_id"], chain["ll_id"], chain["jur_id"])
    S.rf_qualify(api, candidate["id"])

    failed(
        api.mark_build_ready(candidate["id"], headers=S.cm()),
        ApiError.INVALID_CANDIDATE_STATE,
        expected_status=409,
    )

    after = ok(api.get_candidate(candidate["id"], headers=S.cm()))
    assert_fields(
        after,
        feasibility_status="RF_QUALIFIED",
        acquisition_status="PROSPECTING",
        environmental_cleared=False,
    )
    assert_score(
        after["rf_qualification_score"], C.CANDIDATE_RF_SCORE, "rf_qualification_score"
    )
