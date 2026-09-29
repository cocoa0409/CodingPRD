"""Transitions the machines refuse, and one revocation that walks a candidate back."""

from typing import Any, Dict

from test_helpers import constants as C
from test_helpers import fixtures as S
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ApiError
from test_helpers.assertions import assert_fields, assert_instant, failed, ok
from test_helpers.constants import iso

HEARING_DATE = iso("2026-10-01")
PERMIT_EXPIRY_DATE = iso("2027-03-30")


def test_opening_an_already_open_ring_is_refused(api: ApiClient) -> None:
    """`OPEN` is not a legal from-state for the opening transition, and nothing moves.

    PRD: "The ring's `status` moves `DRAFT → OPEN` when the `RfEngineer` opens it for
    candidate development; an attempt to open a ring that is not in `DRAFT` is refused
    with `ERR_INVALID_RING_STATE`."

    PRD: "Ring transition state (opening requires `DRAFT`, reopening requires
    `SITE_SELECTED`) — `ERR_INVALID_RING_STATE`."

    Design: Corner/state_machines/corner_ring_open_twice_rejected
    """
    S.reset_clock(api)
    ring = S.create_open_ring(api)

    refused = api.open_search_ring(ring["id"], headers=S.rf())
    failed(refused, ApiError.INVALID_RING_STATE, expected_status=409)

    reread = ok(api.get_search_ring(ring["id"], headers=S.rf()))
    assert_fields(reread, status="OPEN", version=2)


def test_a_landlord_reply_before_any_outreach_is_refused(api: ApiClient) -> None:
    """`LANDLORD_REPLY` only leaves `OUTREACH_SENT`, so a `PROSPECTING` record refuses it.

    PRD: "A `LANDLORD_REPLY` event moves it `OUTREACH_SENT → LANDLORD_ENGAGED` and is
    only accepted while the candidate is in `OUTREACH_SENT`."

    PRD: "Each recorded event increments `outreach_event_count` by one and increments
    the candidate's `version`."

    Design: Corner/state_machines/corner_landlord_reply_before_outreach_rejected
    """
    chain = S.base_reference_data(api)
    candidate = S.create_candidate(api, chain["ring_id"], chain["ll_id"], chain["jur_id"])
    assert_fields(candidate, acquisition_status="PROSPECTING", outreach_event_count=0)

    refused = api.add_outreach_event(
        candidate["id"], {"event_type": "LANDLORD_REPLY"}, headers=S.agent()
    )
    failed(refused, ApiError.INVALID_CANDIDATE_STATE, expected_status=409)

    reread = ok(api.get_candidate(candidate["id"], headers=S.agent()))
    assert_fields(reread, acquisition_status="PROSPECTING", outreach_event_count=0)


def test_a_terminated_lease_cannot_be_executed_again(api: ApiClient) -> None:
    """`TERMINATED` is terminal, so the second execution is a lease-state conflict.

    PRD: "`WITHDRAWN` and `TERMINATED` are both terminal."

    PRD: "Only a `ProgramDirector` may execute an `ACCEPTED` lease, and only one who
    did not negotiate it — the segregation-of-duties rule of §2.11 applies here."

    PRD: "A `ProgramDirector` terminates an `EXECUTED` lease with a `reason`, moving it
    `EXECUTED → TERMINATED`; this recomputes the landlord's `executed_lease_count`,
    drives the candidate's `acquisition_status` to `RELINQUISHED`, and recomputes the
    ring's `candidate_count` and `committed_capex_usd`."

    Design: Corner/state_machines/corner_terminated_lease_rejects_further_execution
    """
    chain = S.executed_lease_chain(api)
    ok(
        api.terminate_lease(
            chain["lease_id"], {"reason": "title defect found"}, headers=S.director()
        )
    )

    refused = api.execute_lease(
        chain["lease_id"], {"execution_date": C.CLOCK_DEFAULT}, headers=S.director()
    )
    failed(refused, ApiError.INVALID_LEASE_STATE, expected_status=409)

    lease = ok(api.get_lease(chain["lease_id"], headers=S.agent()))
    assert_fields(lease, status="TERMINATED")

    landlord = ok(api.get_landlord(chain["ll_id"], headers=S.agent()))
    assert_fields(landlord, executed_lease_count=0)

    candidate = ok(api.get_candidate(chain["cand_id"], headers=S.agent()))
    assert_fields(candidate, acquisition_status="RELINQUISHED")


def _cleared_candidate_with_a_submitted_permit(api: ApiClient) -> Dict[str, Any]:
    """A `STRUCTURALLY_CLEARED`, environmentally cleared candidate with no entitlement."""
    chain = S.base_reference_data(api)
    candidate = S.create_candidate(api, chain["ring_id"], chain["ll_id"], chain["jur_id"])
    S.rf_qualify(api, candidate["id"])
    S.run_analysis(api, candidate["id"])
    S.clear_environmental(api, candidate["id"])
    permit = S.create_permit(api, candidate["id"])
    chain.update({"cand_id": candidate["id"], "cp_id": permit["id"]})
    return chain


def test_a_permit_cannot_be_issued_before_the_entitlement_is_in_hand(
    api: ApiClient,
) -> None:
    """Structural and environmental clearance are not enough: issuance needs zoning.

    PRD: "It requires the candidate's `feasibility_status` to be `ENTITLED` or
    `BUILD_READY` — the zoning entitlement must already be in hand, and a candidate
    that has not reached one of those two states yields `ERR_ZONING_NOT_APPROVED` — and
    it requires `environmental_cleared` to be true."

    PRD: "On success the supplied `issued_date` is stored, `expiry_date` is set to
    `issued_date` advanced by `valid_days` days, and the candidate's `permit_issued`
    becomes true."

    Design: Corner/state_machines/corner_permit_issue_without_zoning_approval_rejected
    """
    chain = _cleared_candidate_with_a_submitted_permit(api)

    refused = api.issue_permit(
        chain["cp_id"], {"issued_date": C.CLOCK_DEFAULT}, headers=S.cm()
    )
    failed(refused, ApiError.ZONING_NOT_APPROVED, expected_status=409)

    permit = ok(api.get_permit(chain["cp_id"], headers=S.cm()))
    assert_fields(permit, status="SUBMITTED")
    assert permit["expiry_date"] is None, "an unissued permit has no expiry"
    assert permit["issued_date"] is None, "an unissued permit has no issue date"

    candidate = ok(api.get_candidate(chain["cand_id"], headers=S.cm()))
    assert_fields(
        candidate,
        feasibility_status="STRUCTURALLY_CLEARED",
        environmental_cleared=True,
        permit_issued=False,
    )


def test_revoking_the_permit_walks_a_build_ready_candidate_back_and_unselects_it(
    api: ApiClient,
) -> None:
    """Revocation reverts the candidate to `ENTITLED` and returns the ring to `OPEN`.

    PRD: "In either case the candidate's `permit_issued` is set back to false, a
    candidate sitting in `BUILD_READY` is reverted `BUILD_READY → ENTITLED`, and if that
    candidate was the ring's `selected_candidate_id`, the ring's selection is cleared to
    null and the ring returns to `OPEN`."

    PRD: "Revocation is deliberate: the manager supplies a `revocation_reason`, which
    is stored, and the permit moves `ISSUED → REVOKED`."

    PRD: "Or the selected candidate may fall out of `BUILD_READY` when its issued permit
    is revoked or expires, which likewise clears the selection and returns the ring to
    `OPEN`."

    Design: Corner/state_machines/corner_permit_revocation_reverts_build_ready_candidate
    """
    chain = S.build_selected_chain(api, hearing_date=HEARING_DATE)

    revoked = ok(
        api.revoke_permit(
            chain["cp_id"],
            {"revocation_reason": "as-built drawings rejected"},
            headers=S.cm(),
        )
    )
    assert_fields(
        revoked, status="REVOKED", revocation_reason="as-built drawings rejected"
    )
    assert_instant(revoked["expiry_date"], PERMIT_EXPIRY_DATE, "expiry_date")

    candidate = ok(api.get_candidate(chain["cand_id"], headers=S.cm()))
    assert_fields(candidate, feasibility_status="ENTITLED", permit_issued=False)

    application = ok(api.get_zoning_application(chain["za_id"], headers=S.planner()))
    assert_fields(application, status="APPROVED")

    ring = ok(api.get_search_ring(chain["ring_id"], headers=S.director()))
    assert_fields(ring, status="OPEN")
    assert ring["selected_candidate_id"] is None, "the selection is cleared"
