"""The environmental fork and the join that only the last branch closure fires."""

from typing import Any, Dict

from test_helpers import constants as C
from test_helpers import fixtures as S
from test_helpers.api_client import ApiClient
from test_helpers.assertions import assert_fields, assert_instant, ok
from test_helpers.constants import iso

TRIBAL_DEADLINE = iso("2026-08-31")


def _tribal_review(api: ApiClient) -> Dict[str, Any]:
    """An unscreened review on a candidate whose landlord is a tribal authority."""
    S.reset_clock(api)
    jurisdiction = S.create_jurisdiction(api)
    ring = S.create_open_ring(api)
    landlord = S.create_tribal_landlord(api)
    candidate = S.create_candidate(
        api,
        ring["id"],
        landlord["id"],
        jurisdiction["id"],
        site_type="RAW_LAND",
        lat=42.3530,
        lon=-71.0650,
        distance_from_center_m=250,
        agl_m=55,
        months_to_availability=4,
        measured_rsrp_dbm=-90,
        offered_capacity_gbps=9,
    )
    review = S.create_environmental_review(
        api,
        candidate["id"],
        nepa_category="ENVIRONMENTAL_ASSESSMENT",
        section106_required=True,
    )
    return {"cand_id": candidate["id"], "er_id": review["id"]}


def test_screening_forks_a_tribal_branch_because_the_landlord_is_a_tribal_authority(
    api: ApiClient,
) -> None:
    """The landlord alone puts tribal consultation in scope and starts its window.

    PRD: "It is true when the candidate's jurisdiction has
    `tribal_consultation_required` set to true, or when the candidate's landlord has
    `entity_type` equal to `TRIBAL_AUTHORITY`; either condition alone suffices, and
    it is false only when neither holds."

    PRD: "Screening always sets `public_notice_branch_status` to `PENDING`."

    PRD: "The tribal branch depends on scope: when `tribal_consultation_required` is
    true, `tribal_branch_status` becomes `PENDING`, `tcns_notice_date` is stamped
    with the logical clock as the moment the TCNS notice went out, and
    `tribal_response_deadline_date` is set to thirty days after `tcns_notice_date`;
    when `tribal_consultation_required` is false, `tribal_branch_status` becomes
    `NOT_APPLICABLE` and both dates stay null."

    Design: Difficulty/non_linear_state_machine/environmental_fork_join_requires_both_branches_complete
    """
    scenario = _tribal_review(api)

    screened = ok(api.screen_environmental_review(scenario["er_id"], headers=S.reviewer()))

    assert_fields(
        screened,
        tribal_consultation_required=True,
        status="SCREENING",
        public_notice_branch_status="PENDING",
        tribal_branch_status="PENDING",
    )
    assert_instant(screened["tcns_notice_date"], C.CLOCK_DEFAULT, "tcns_notice_date")
    assert_instant(
        screened["tribal_response_deadline_date"],
        TRIBAL_DEADLINE,
        "tribal_response_deadline_date",
    )


def test_only_the_second_branch_closure_clears_the_candidate(api: ApiClient) -> None:
    """One closed branch is consultation; both closed branches are clearance.

    PRD: "With a `NO_ADVERSE_EFFECT` finding, closing one branch while the other is
    still `PENDING` moves the review `SCREENING → IN_CONSULTATION`."

    PRD: "Closing the last `PENDING` branch — the point at which
    `public_notice_branch_status` is `COMPLETE` and `tribal_branch_status` is either
    `COMPLETE` or `NOT_APPLICABLE` — moves the review to `CLEARED` and sets the
    candidate's `environmental_cleared` to true; this join fires from
    `IN_CONSULTATION` in the two-branch case, and directly from `SCREENING` when the
    tribal branch was `NOT_APPLICABLE` and the public-notice branch is the only one
    to close."

    PRD: "Closing the `TRIBAL` branch additionally requires that the logical clock
    has reached or passed `tribal_response_deadline_date` — the tribes get their
    full window."

    Design: Difficulty/non_linear_state_machine/environmental_fork_join_requires_both_branches_complete
    """
    scenario = _tribal_review(api)
    S.screen_review(api, scenario["er_id"])

    half_closed = ok(
        api.complete_branch(
            scenario["er_id"],
            {"branch": "PUBLIC_NOTICE", "finding": "NO_ADVERSE_EFFECT"},
            headers=S.reviewer(),
        )
    )
    assert_fields(
        half_closed,
        status="IN_CONSULTATION",
        public_notice_branch_status="COMPLETE",
        tribal_branch_status="PENDING",
    )
    mid = ok(api.get_candidate(scenario["cand_id"], headers=S.reviewer()))
    assert_fields(mid, environmental_cleared=False)

    S.set_clock(api, TRIBAL_DEADLINE)
    joined = ok(
        api.complete_branch(
            scenario["er_id"],
            {"branch": "TRIBAL", "finding": "NO_ADVERSE_EFFECT"},
            headers=S.reviewer(),
        )
    )
    assert_fields(
        joined,
        status="CLEARED",
        public_notice_branch_status="COMPLETE",
        tribal_branch_status="COMPLETE",
    )
    after = ok(api.get_candidate(scenario["cand_id"], headers=S.reviewer()))
    assert_fields(after, environmental_cleared=True)
