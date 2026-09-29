"""Four authorization checks: a wrong role, a wrong owner, a wrong reviewer, a reader."""

from typing import Any, Dict

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as S
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ApiError
from test_helpers.assertions import (
    assert_fields,
    assert_money,
    assert_pagination_meta,
    assert_score,
    failed,
    ok,
    page,
)
from test_helpers.test_users import AGENT_OWNER, AGENT_PEER, CERTIFIER

DESIGN_COST_USD = 45000.00
SECOND_RING_NAME = "Ring 2276-B"


def test_an_rf_engineer_may_not_draft_the_ground_lease(api: ApiClient) -> None:
    """Lease drafting belongs to the owning agent, so the RF role is turned away.

    PRD: "If the header is well formed but the role is not authorized for the target
    operation, the rejection is `ERR_UNAUTHORIZED` (403)."

    PRD: "The owning `SiteAcquisitionAgent` drafts a ground lease against a candidate,
    naming the candidate through `candidate_id`, repeating the property owner through
    `landlord_id` — which must equal the candidate's own landlord, or the draft is
    refused with `ERR_LANDLORD_MISMATCH` — and recording the opaque negotiator through
    `negotiating_agent_user_id`."

    PRD: "2. Role authorization — `ERR_UNAUTHORIZED`, on every endpoint."

    Design: Corner/rbac/corner_rf_engineer_cannot_draft_lease
    """
    chain = S.engaged_candidate(api)

    refused = api.create_lease(
        F.lease_payload(chain["cand_id"], chain["ll_id"]), headers=S.rf()
    )
    failed(refused, ApiError.UNAUTHORIZED, expected_status=403)

    rows, meta = page(
        api.list_leases({"candidate_id": chain["cand_id"]}, headers=S.director())
    )
    assert rows == [], "the refused draft left no lease behind"
    assert_pagination_meta(meta, total_count=0)

    candidate = ok(api.get_candidate(chain["cand_id"], headers=S.agent()))
    assert_fields(candidate, acquisition_status="LANDLORD_ENGAGED")


def test_only_the_owning_agent_may_record_the_outreach_event(api: ApiClient) -> None:
    """A second agent is refused as a non-owner; the recorded owner succeeds.

    PRD: "A candidate carries `owning_agent_user_id`, supplied when the candidate is
    created; when a `SiteAcquisitionAgent` acts on a candidate or its lease, the server
    compares `X-User-ID` to that stored value and rejects a mismatch with
    `ERR_NOT_CANDIDATE_OWNER` (403)."

    PRD: "Each recorded event increments `outreach_event_count` by one and increments the
    candidate's `version`."

    PRD: "An `OUTREACH_SENT` event moves the acquisition dimension `PROSPECTING →
    OUTREACH_SENT` and is only accepted while the candidate is in `PROSPECTING`."

    Design: Corner/rbac/corner_non_owning_agent_cannot_send_outreach
    """
    chain = S.base_reference_data(api)
    candidate = S.create_candidate(api, chain["ring_id"], chain["ll_id"], chain["jur_id"])
    assert_fields(candidate, owning_agent_user_id=AGENT_OWNER)

    refused = api.add_outreach_event(
        candidate["id"], {"event_type": "OUTREACH_SENT"}, headers=S.agent(AGENT_PEER)
    )
    failed(refused, ApiError.NOT_CANDIDATE_OWNER, expected_status=403)

    untouched = ok(api.get_candidate(candidate["id"], headers=S.agent()))
    assert_fields(
        untouched,
        acquisition_status="PROSPECTING",
        outreach_event_count=0,
        version=1,
    )

    recorded = ok(
        api.add_outreach_event(
            candidate["id"], {"event_type": "OUTREACH_SENT"}, headers=S.agent()
        )
    )
    assert_fields(
        recorded, acquisition_status="OUTREACH_SENT", outreach_event_count=1
    )


def _design_in_peer_review(api: ApiClient) -> Dict[str, Any]:
    """A 45000.00 design in `PEER_REVIEW` over an analysis performed by `sengr-001`."""
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
    completed = S.complete_analysis(api, analysis["id"])
    design = S.create_design(api, analysis["id"], DESIGN_COST_USD, scope="REINFORCEMENT")
    S.submit_design(api, design["id"])
    chain.update(
        {
            "cand_id": candidate["id"],
            "sa_id": analysis["id"],
            "analysis": completed,
            "md_id": design["id"],
        }
    )
    return chain


def test_the_engineer_who_ran_the_analysis_may_not_certify_the_design(
    api: ApiClient,
) -> None:
    """Segregation reaches the analyst as well as the author; a third engineer signs.

    PRD: "A modification design may not be certified by its author, nor by the engineer
    who performed the analysis it rests on: if the certifying `StructuralEngineer`'s
    `X-User-ID` equals either the design's `designed_by_user_id` or the backing
    analysis's `performed_by_user_id`, certification is refused with the same error."

    PRD: "A utilization above 85.00 but no greater than 100.00 is a `PASS_WITH_MOD` — the
    structure can carry the build, but only after reinforcement."

    PRD: "`CERTIFY` moves the design `PEER_REVIEW → CERTIFIED`, which is terminal; it
    enforces both halves of the segregation-of-duties rule from §2.11, writes the acting
    `X-User-ID` into `certified_by_user_id`, recomputes the ring's `committed_capex_usd`,
    and clears the candidate `STRUCTURAL_HOLD → STRUCTURALLY_CLEARED` when the candidate
    is in `STRUCTURAL_HOLD`."

    Design: Corner/rbac/corner_design_certification_by_analysis_author_rejected
    """
    chain = _design_in_peer_review(api)
    assert_score(
        chain["analysis"]["capacity_utilization_pct"],
        C.HEAVY_UTILIZATION_H_PCT,
        "capacity_utilization_pct",
    )
    assert_fields(chain["analysis"], result="PASS_WITH_MOD")

    refused = api.peer_review(
        chain["md_id"], {"action": "CERTIFY"}, headers=S.analyst()
    )
    failed(refused, ApiError.SEGREGATION_OF_DUTIES, expected_status=403)

    uncertified = ok(api.get_modification_design(chain["md_id"], headers=S.designer()))
    assert_fields(uncertified, status="PEER_REVIEW")
    assert uncertified["certified_by_user_id"] is None, "nothing was certified"

    unchanged_ring = ok(api.get_search_ring(chain["ring_id"], headers=S.director()))
    assert_money(unchanged_ring["committed_capex_usd"], 0.00, "committed_capex_usd")

    certified = ok(
        api.peer_review(chain["md_id"], {"action": "CERTIFY"}, headers=S.certifier())
    )
    assert_fields(certified, status="CERTIFIED", certified_by_user_id=CERTIFIER)

    ring = ok(api.get_search_ring(chain["ring_id"], headers=S.director()))
    assert_money(ring["committed_capex_usd"], DESIGN_COST_USD, "committed_capex_usd")

    candidate = ok(api.get_candidate(chain["cand_id"], headers=S.analyst()))
    assert_fields(candidate, feasibility_status="STRUCTURALLY_CLEARED")


def test_the_environmental_reviewer_reads_a_ring_but_cannot_create_one(
    api: ApiClient,
) -> None:
    """Ring reads are open to all seven roles; minting a ring is the RF engineer's.

    PRD: "The seven roles are `RfEngineer`, `SiteAcquisitionAgent`, `ZoningPlanner`,
    `StructuralEngineer`, `EnvironmentalReviewer`, `ConstructionManager`, and
    `ProgramDirector`."

    PRD: "An `RfEngineer` defines search rings from RF design objectives and scores
    candidates against coverage and capacity targets."

    PRD: "An `EnvironmentalReviewer` runs NEPA and Section 106 screening, the
    public-notice branch, and tribal consultation."

    PRD: "If the header is well formed but the role is not authorized for the target
    operation, the rejection is `ERR_UNAUTHORIZED` (403)."

    Design: Corner/rbac/corner_environmental_reviewer_can_read_search_ring
    """
    S.reset_clock(api)
    ring = S.create_search_ring(api)

    reread = ok(api.get_search_ring(ring["id"], headers=S.reviewer()))
    assert_fields(reread, id=ring["id"], status="DRAFT")

    refused = api.create_search_ring(
        F.search_ring_payload(name=SECOND_RING_NAME, priority_rank=2),
        headers=S.reviewer(),
    )
    failed(refused, ApiError.UNAUTHORIZED, expected_status=403)

    rows, meta = page(api.list_search_rings(headers=S.director()))
    assert len(rows) == 1, "only the RF engineer's ring exists"
    assert_pagination_meta(meta, total_count=1)
