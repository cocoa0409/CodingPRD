"""Blacklisting a landlord unwinds the lease, the candidate and the ring selection."""

from test_helpers import fixtures as S
from test_helpers.api_client import ApiClient
from test_helpers.assertions import assert_fields, ok

BLACKLIST_REASON = "title fraud finding"


def test_blacklisting_terminates_the_executed_lease_and_relinquishes_the_candidate(
    api: ApiClient,
) -> None:
    """The lease termination is what drives the candidate, not the standing change itself.

    PRD: "When a landlord's `standing` is set to `BLACKLISTED`, every lease of that
    landlord whose status is `EXECUTED` becomes `TERMINATED`."

    PRD: "Each terminated lease drives its candidate's `acquisition_status` to
    `RELINQUISHED`."

    PRD: "Setting `BLACKLISTED` triggers the landlord cascade described in §2.10."

    Design: Difficulty/transitive_cascade/landlord_blacklist_cascades_to_ring_unselection
    """
    chain = S.build_selected_chain(api)

    landlord = ok(
        api.set_landlord_standing(
            chain["ll_id"],
            {"standing": "BLACKLISTED", "reason": BLACKLIST_REASON},
            headers=S.director(),
        )
    )
    assert_fields(landlord, standing="BLACKLISTED")

    lease = ok(api.get_lease(chain["lease_id"], headers=S.agent()))
    assert_fields(lease, status="TERMINATED")

    candidate = ok(api.get_candidate(chain["cand_id"], headers=S.agent()))
    assert_fields(candidate, acquisition_status="RELINQUISHED")


def test_the_cascade_reopens_the_ring_and_recomputes_both_ledgers(api: ApiClient) -> None:
    """The ring loses its winner and both derived counters fall back to zero.

    PRD: "Each relinquished candidate recomputes the ring's `candidate_count` and
    `committed_capex_usd`, and clears the ring's selection back to `OPEN` with a null
    `selected_candidate_id` if that candidate had been the selected one."

    PRD: "The landlord's `executed_lease_count` is, at all times, the count of that
    landlord's leases whose status is `EXECUTED` — recomputed after every execution,
    every termination and every blacklist cascade, and no other status contributes to
    it."

    PRD: "`candidate_count` tracks the number of candidates attached to the ring
    whose `acquisition_status` is anything other than `RELINQUISHED`, and is
    recomputed whenever a candidate joins the ring or is relinquished or
    disqualified."

    Design: Difficulty/transitive_cascade/landlord_blacklist_cascades_to_ring_unselection
    """
    chain = S.build_selected_chain(api)

    before_ring = ok(api.get_search_ring(chain["ring_id"], headers=S.director()))
    assert_fields(
        before_ring,
        status="SITE_SELECTED",
        selected_candidate_id=chain["cand_id"],
        candidate_count=1,
    )
    before_landlord = ok(api.get_landlord(chain["ll_id"], headers=S.agent()))
    assert_fields(before_landlord, executed_lease_count=1)

    S.set_standing(api, chain["ll_id"], "BLACKLISTED", BLACKLIST_REASON)

    ring = ok(api.get_search_ring(chain["ring_id"], headers=S.director()))
    assert_fields(ring, status="OPEN", candidate_count=0)
    assert ring["selected_candidate_id"] is None, (
        "the blacklist cascade clears the ring's selection"
    )

    landlord = ok(api.get_landlord(chain["ll_id"], headers=S.agent()))
    assert_fields(landlord, executed_lease_count=0)
