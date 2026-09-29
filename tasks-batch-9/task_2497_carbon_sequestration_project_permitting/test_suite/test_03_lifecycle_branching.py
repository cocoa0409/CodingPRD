"""Lifecycle branching that is not a single straight line.

Three shapes are exercised here: the injection well permit's regulatory and
physical dimensions advancing independently of one another, the monitoring plan's
two review tracks forking and then joining, and the pore space lease negotiation
cycling between developer offer and landowner counter before it settles.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import ApiErrorId, fixtures, make_landowner_headers
from test_helpers.constants import MRV_METHODS_SCORE_85
from test_helpers.factories import (
    advance_construction_payload,
    counter_offer_payload,
)
from test_helpers.test_users import SECOND_REVIEWER_USER_ID


def test_permit_regulatory_revision_cycle_leaves_construction_at_not_started(
    api, project_developer_headers, second_reviewer_headers
):
    """An injection well permit carries `permit_status` (the regulatory track)
    alongside `construction_status` (the physical track); activation is the single
    point at which both dimensions must agree. Advancing one dimension never
    implicitly advances a sibling dimension unless a rule below says so
    explicitly. Opening review records the reviewer's `X-User-ID` in
    `technical_reviewer_user_id` — the field that later disqualifies that same
    identity from certifying the project's closure — and moves `permit_status`
    `SUBMITTED → TECHNICAL_REVIEW`. `REQUEST_REVISION` moves `permit_status`
    `TECHNICAL_REVIEW → REVISION_REQUESTED`, from which a resubmission returns the
    permit to `SUBMITTED` and increments `revision_round_count` again; a
    resubmission from `REVISION_REQUESTED` carries no construction-standard or
    pressure re-check, since those were satisfied on the original submission.

    Design: Difficulty/non_linear_state_machine/permit_status_and_construction_status_advance_independently
    """
    ctx = fixtures.setup_project_with_finalized_aor(api)
    permit = fixtures.create_permit(api, ctx["project"]["id"], ctx["model"]["id"])
    fixtures.submit_permit(api, permit["id"])

    fixtures.rule_on_permit(
        api, permit["id"], "BEGIN_TECHNICAL_REVIEW", headers=second_reviewer_headers
    )
    revised = validate_success(
        api.review_injection_well_permit(
            permit["id"],
            {"decision": "REQUEST_REVISION", "review_note": "clarify cement bond plan"},
            second_reviewer_headers,
        )
    )
    assert revised["permit_status"] == "REVISION_REQUESTED"
    assert revised["construction_status"] == "NOT_STARTED"

    resubmitted = validate_success(
        api.submit_injection_well_permit(
            permit["id"], {"submission_note": "revision 2"}, project_developer_headers
        )
    )
    assert resubmitted["revision_round_count"] == 2

    fixtures.rule_on_permit(
        api, permit["id"], "BEGIN_TECHNICAL_REVIEW", headers=second_reviewer_headers
    )
    approved = validate_success(
        api.review_injection_well_permit(
            permit["id"],
            {"decision": "APPROVE", "review_note": "construction standards met"},
            second_reviewer_headers,
        )
    )
    assert approved["permit_status"] == "APPROVED"
    assert approved["construction_status"] == "NOT_STARTED"
    assert approved["revision_round_count"] == 2
    assert approved["technical_reviewer_user_id"] == SECOND_REVIEWER_USER_ID

    stored = fixtures.refresh_permit(api, permit["id"])
    assert stored["permit_status"] == "APPROVED"
    assert stored["construction_status"] == "NOT_STARTED"
    assert stored["revision_round_count"] == 2
    assert stored["technical_reviewer_user_id"] == SECOND_REVIEWER_USER_ID


def test_permit_construction_advances_while_permit_status_stays_approved(
    api, project_developer_headers, second_reviewer_headers
):
    """The construction dimension advances entirely independently, one step at a
    time, and the developer names the step it wants in `to_construction_status`.
    The first step, into `DRILLING`, has two extra preconditions the later steps do
    not: the permit's `permit_status` must already be `APPROVED`, and the project
    must not be `FROZEN`. Creation immediately derives the well's pressure ceiling:
    `max_injection_pressure_psi` is 90 percent of the referenced model's
    `fracture_pressure_psi`, rounded half up to 2 decimal places. On success the
    permit's `authorized_injection_rate_tpy` is set to the governing model's
    `effective_injection_rate_tpy`, `activated_at` is stamped with the logical
    clock, `permit_status` moves `APPROVED → ACTIVE`, and the permit's `version`
    increments.

    Design: Difficulty/non_linear_state_machine/permit_status_and_construction_status_advance_independently
    """
    ctx = fixtures.setup_project_with_finalized_aor(api)
    permit = fixtures.create_permit(api, ctx["project"]["id"], ctx["model"]["id"])
    fixtures.submit_permit(api, permit["id"])
    fixtures.rule_on_permit(
        api, permit["id"], "BEGIN_TECHNICAL_REVIEW", headers=second_reviewer_headers
    )
    fixtures.rule_on_permit(
        api, permit["id"], "REQUEST_REVISION", headers=second_reviewer_headers
    )
    fixtures.submit_permit(api, permit["id"], submission_note="revision 2")
    fixtures.rule_on_permit(
        api, permit["id"], "BEGIN_TECHNICAL_REVIEW", headers=second_reviewer_headers
    )
    fixtures.rule_on_permit(api, permit["id"], "APPROVE", headers=second_reviewer_headers)

    drilling = validate_success(
        api.advance_construction(
            permit["id"],
            advance_construction_payload("DRILLING"),
            project_developer_headers,
        )
    )
    assert drilling["permit_status"] == "APPROVED"
    assert drilling["construction_status"] == "DRILLING"

    cased = validate_success(
        api.advance_construction(
            permit["id"],
            advance_construction_payload("CASING_SET"),
            project_developer_headers,
        )
    )
    assert cased["construction_status"] == "CASING_SET"

    stored = fixtures.refresh_permit(api, permit["id"])
    assert stored["permit_status"] == "APPROVED"
    assert stored["construction_status"] == "CASING_SET"
    assert stored["authorized_injection_rate_tpy"] == 0
    assert stored["max_injection_pressure_psi"] == 4050.00


def test_monitoring_plan_public_comment_alone_does_not_admit_approval(
    api, regulatory_reviewer_headers
):
    """Symmetrically, the reviewer closes the public comment track with a
    `decision` of `COMPLETE_PUBLIC_COMMENT`, admissible only while `status` is
    `SUBMITTED` and `public_comment_complete` is still false; it sets
    `public_comment_complete` to true and sets `status` to `REVIEW_COMPLETE` only
    when `technical_review_complete` is already true, otherwise leaving `status` at
    `SUBMITTED`. From `REVIEW_COMPLETE` the reviewer rules with a `decision` of
    `APPROVE`, `REQUEST_REVISION` or `REJECT`, optionally with a `review_note`.
    Attempting to close a track that is already closed is refused with
    `ERR_INVALID_PLAN_STATE`.

    Design: Difficulty/non_linear_state_machine/monitoring_plan_fork_join_requires_both_review_tracks
    """
    fixtures.set_logical_clock(api)
    project = fixtures.open_project(api)
    plan, _methods = fixtures.create_monitoring_plan_with_methods(
        api, project["id"], methods=MRV_METHODS_SCORE_85
    )
    fixtures.submit_plan(api, plan["id"])

    after_public = validate_success(
        api.review_monitoring_plan(
            plan["id"],
            {
                "decision": "COMPLETE_PUBLIC_COMMENT",
                "review_note": "comment period closed first",
            },
            regulatory_reviewer_headers,
        )
    )
    assert after_public["public_comment_complete"] is True
    assert after_public["technical_review_complete"] is False
    assert after_public["status"] == "SUBMITTED"

    premature = api.review_monitoring_plan(
        plan["id"],
        {
            "decision": "APPROVE",
            "condition_count": 0,
            "review_note": "premature approval attempt",
        },
        regulatory_reviewer_headers,
    )
    validate_error(premature, ApiErrorId.ERR_INVALID_PLAN_STATE.value, 409)

    stored = fixtures.refresh_plan(api, plan["id"])
    assert stored["status"] == "SUBMITTED"
    assert stored["public_comment_complete"] is True
    assert stored["technical_review_complete"] is False


def test_monitoring_plan_second_track_closure_joins_the_fork_and_admits_approval(
    api, regulatory_reviewer_headers
):
    """A `RegulatoryReviewer` closes the technical track with a `decision` of
    `COMPLETE_TECHNICAL_REVIEW`, which is admissible only while `status` is
    `SUBMITTED` and `technical_review_complete` is still false; it sets
    `technical_review_complete` to true and, when `public_comment_complete` is
    already true, auto-advances the plan `SUBMITTED → REVIEW_COMPLETE` in the same
    request. Either track may be closed first, and closing whichever track comes
    second is what joins the fork. Each domain subscore is the sum of the
    `method_score` values of that domain's methods whose `status` is `ACTIVE`,
    capped at 1.0000 and rounded half up to 4 decimal places — so
    `subsurface_subscore`, `surface_subscore` and `atmospheric_subscore` each
    saturate, and piling a fourth seismic survey onto an already-saturated
    subsurface domain adds nothing. When `coverage_score` is at least 85.00, the
    plan moves `REVIEW_COMPLETE → APPROVED`. Its `condition_count` is set to 0
    regardless of anything supplied in the body, the reviewer's `X-User-ID` is
    recorded in `approved_by_user_id`, and the project's
    `effective_annual_monitoring_cost_usd` is left equal to its
    `annual_monitoring_cost_usd` — an unconditioned approval carries no cost
    uplift.

    Design: Difficulty/non_linear_state_machine/monitoring_plan_fork_join_requires_both_review_tracks
    """
    fixtures.set_logical_clock(api)
    project = fixtures.open_project(api)
    plan, _methods = fixtures.create_monitoring_plan_with_methods(
        api, project["id"], methods=MRV_METHODS_SCORE_85
    )
    fixtures.submit_plan(api, plan["id"])
    fixtures.rule_on_plan(
        api,
        plan["id"],
        "COMPLETE_PUBLIC_COMMENT",
        headers=regulatory_reviewer_headers,
        review_note="comment period closed first",
    )

    joined = validate_success(
        api.review_monitoring_plan(
            plan["id"],
            {
                "decision": "COMPLETE_TECHNICAL_REVIEW",
                "review_note": "technical track closed second",
            },
            regulatory_reviewer_headers,
        )
    )
    assert joined["status"] == "REVIEW_COMPLETE"
    assert joined["technical_review_complete"] is True
    assert joined["public_comment_complete"] is True

    ruled = validate_success(
        api.review_monitoring_plan(
            plan["id"],
            {
                "decision": "APPROVE",
                "condition_count": 0,
                "review_note": "coverage sufficient",
            },
            regulatory_reviewer_headers,
        )
    )
    assert ruled["status"] == "APPROVED"
    assert ruled["condition_count"] == 0

    stored = fixtures.refresh_plan(api, plan["id"])
    assert stored["status"] == "APPROVED"
    assert stored["technical_review_complete"] is True
    assert stored["public_comment_complete"] is True
    assert stored["subsurface_subscore"] == 1.0000
    assert stored["surface_subscore"] == 0.8000
    assert stored["atmospheric_subscore"] == 0.5500
    assert stored["coverage_score"] == 85.00

    stored_project = fixtures.refresh_project(api, project["id"])
    assert stored_project["effective_annual_monitoring_cost_usd"] == 200000


def test_tract_offer_counter_cycle_counts_every_round_and_clears_the_counter(api):
    """Every offer increments `negotiation_round_count` by one and sets
    `lease_status` to `OFFER_SENT`, bumping the tract's `version`. A `COUNTER`
    response must supply a `counter_bonus_per_acre_usd` strictly greater than the
    tract's `current_offer_bonus_per_acre_usd` — a counter that does not improve on
    the developer's own number is not a counter — and it stores that figure and
    moves the tract `OFFER_SENT → COUNTERED`. Sending an offer over an outstanding
    counter clears `counter_bonus_per_acre_usd` back to null, since the developer's
    new offer supersedes it. The cycle `OFFER_SENT → COUNTERED → OFFER_SENT` may
    repeat indefinitely until the landowner accepts or rejects.

    Design: Difficulty/non_linear_state_machine/tract_negotiation_cycle_counts_three_offer_rounds
    """
    fixtures.set_logical_clock(api)
    project = fixtures.open_project(api)
    tract = fixtures.register_tract(api, project["id"], "T1")
    landowner_headers = make_landowner_headers(tract["landowner_user_id"])

    round_1 = fixtures.send_offer(
        api, tract, bonus_per_acre_usd=15.00, royalty_rate_pct=12.5
    )
    assert round_1["negotiation_round_count"] == 1
    assert round_1["lease_status"] == "OFFER_SENT"

    countered = validate_success(
        api.respond_to_lease_offer(
            tract["id"], counter_offer_payload(25.00), landowner_headers
        )
    )
    assert countered["lease_status"] == "COUNTERED"
    assert countered["counter_bonus_per_acre_usd"] == 25.00

    round_2 = fixtures.send_offer(
        api, countered, bonus_per_acre_usd=18.00, royalty_rate_pct=13.0
    )
    assert round_2["negotiation_round_count"] == 2
    assert round_2["counter_bonus_per_acre_usd"] is None

    countered_again = validate_success(
        api.respond_to_lease_offer(
            tract["id"], counter_offer_payload(22.00), landowner_headers
        )
    )
    round_3 = fixtures.send_offer(
        api, countered_again, bonus_per_acre_usd=20.00, royalty_rate_pct=14.0
    )
    assert round_3["negotiation_round_count"] == 3
    assert round_3["lease_status"] == "OFFER_SENT"

    stored = fixtures.refresh_tract(api, tract["id"])
    assert stored["negotiation_round_count"] == 3
    assert stored["counter_bonus_per_acre_usd"] is None


def test_tract_acceptance_executes_the_third_offer_terms_and_settles_the_project(api):
    """Acceptance locks the terms: `executed_bonus_per_acre_usd` takes the value of
    `current_offer_bonus_per_acre_usd`, `executed_royalty_rate_pct` takes the value
    of `current_offer_royalty_rate_pct`, and the supplied term dates are stored.
    Per tract, `net_acreage` is `acreage` multiplied by `ownership_pct` divided by
    100.0, rounded half up to 4 decimal places, and `bonus_settlement_usd` is that
    `net_acreage` multiplied by `executed_bonus_per_acre_usd`, rounded half up to 2
    decimal places. At project level the holders are the tracts whose
    `lease_status` is `EXECUTED` or `UNITIZED`, summed in `created_at` ascending
    order: `secured_acreage` is the sum of their `net_acreage` values rounded half
    up to 4 decimal places, `outstanding_acreage` is `total_project_acreage` less
    `secured_acreage` rounded half up to 4 decimal places,
    `pore_space_consent_pct` is 100.0 multiplied by `secured_acreage` divided by
    `total_project_acreage` rounded half up to 2 decimal places, and
    `pore_space_bonus_total_usd` is the sum of the holders' already-rounded
    `bonus_settlement_usd` values rounded half up to 2 decimal places.

    Design: Difficulty/non_linear_state_machine/tract_negotiation_cycle_counts_three_offer_rounds
    """
    fixtures.set_logical_clock(api)
    project = fixtures.open_project(api)
    tract = fixtures.register_tract(api, project["id"], "T1")
    landowner_headers = make_landowner_headers(tract["landowner_user_id"])

    offered = fixtures.send_offer(
        api, tract, bonus_per_acre_usd=15.00, royalty_rate_pct=12.5
    )
    countered = validate_success(
        api.respond_to_lease_offer(
            offered["id"], counter_offer_payload(25.00), landowner_headers
        )
    )
    reoffered = fixtures.send_offer(
        api, countered, bonus_per_acre_usd=18.00, royalty_rate_pct=13.0
    )
    countered_again = validate_success(
        api.respond_to_lease_offer(
            reoffered["id"], counter_offer_payload(22.00), landowner_headers
        )
    )
    third_offer = fixtures.send_offer(
        api, countered_again, bonus_per_acre_usd=20.00, royalty_rate_pct=14.0
    )

    executed = fixtures.accept_offer(api, third_offer)
    assert executed["lease_status"] == "EXECUTED"
    assert executed["executed_bonus_per_acre_usd"] == 20.00
    assert executed["executed_royalty_rate_pct"] == 14.0

    stored = fixtures.refresh_tract(api, tract["id"])
    assert stored["lease_status"] == "EXECUTED"
    assert stored["negotiation_round_count"] == 3
    assert stored["executed_bonus_per_acre_usd"] == 20.00
    assert stored["executed_royalty_rate_pct"] == 14.0
    assert stored["counter_bonus_per_acre_usd"] is None
    assert stored["net_acreage"] == 1000.0000
    assert stored["bonus_settlement_usd"] == 20000.00

    stored_project = fixtures.refresh_project(api, project["id"])
    assert stored_project["secured_acreage"] == 1000.0000
    assert stored_project["pore_space_consent_pct"] == 25.00
    assert stored_project["pore_space_bonus_total_usd"] == 20000.00
