"""Variance recommendation, the revision loop, and segregation of duties."""
from test_helpers import (
    validate_success, validate_error, NON_EXISTENT_UUID, ApiErrorId,
    make_planner_headers, make_zoningboard_headers, make_applicant_headers,
    setup_variance_under_review, recommend_variance,
)


# ── Cyclic revision loop (Difficulty) ────────────────────────────────────────
def test_revise_moves_variance_to_revision_requested(api):
    """PRD §3.3: "A `REVISE` decision advances `UNDER_REVIEW → REVISION_REQUESTED`,
    records `decided_by_user_id`, and returns the variance to the applicant's planner
    for re-recommendation — a re-recommend advances `REVISION_REQUESTED → UNDER_REVIEW`
    again, overwriting `recommendation` and `recommended_by_user_id`."

    Design: Difficulty/non_linear_state_machine/variance_revision_cycle_returns_to_under_review
    """
    parcel, applicant, app, var = setup_variance_under_review(api)
    revised = validate_success(
        api.decide_variance(var["id"], {"decision": "REVISE"}, make_zoningboard_headers("board-1"))
    )
    assert revised["status"] == "REVISION_REQUESTED"


def test_re_recommend_returns_variance_to_under_review(api):
    """PRD §3.3: "A `REVISE` decision advances `UNDER_REVIEW → REVISION_REQUESTED`,
    records `decided_by_user_id`, and returns the variance to the applicant's planner
    for re-recommendation — a re-recommend advances `REVISION_REQUESTED → UNDER_REVIEW`
    again, overwriting `recommendation` and `recommended_by_user_id`."

    Design: Difficulty/non_linear_state_machine/variance_revision_cycle_returns_to_under_review
    """
    parcel, applicant, app, var = setup_variance_under_review(api)
    validate_success(
        api.decide_variance(var["id"], {"decision": "REVISE"}, make_zoningboard_headers("board-1"))
    )
    rerecommended = recommend_variance(api, var["id"])
    assert rerecommended["status"] == "UNDER_REVIEW"


# ── Segregation of duties (Corner) ───────────────────────────────────────────
def test_decider_equal_to_recommender_rejected(api):
    """PRD §3.3: "the deciding user's `X-User-ID`, captured as `decided_by_user_id`, must
    differ from the `recommended_by_user_id`; if they are equal the decision is refused
    with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/validations/variance_decide_same_user_as_recommender_sod
    """
    parcel, applicant, app, var = setup_variance_under_review(api, recommender_id="dual-1")
    resp = api.decide_variance(
        var["id"], {"decision": "GRANT", "granted_value": 100},
        make_zoningboard_headers("dual-1"),
    )
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)


# ── RBAC & existence ─────────────────────────────────────────────────────────
def test_applicant_cannot_decide_variance(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted to
    perform the requested operation — or an ownership-scoped role acts on a resource it
    does not own — the request is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/applicant_cannot_decide_variance_unauthorized
    """
    parcel, applicant, app, var = setup_variance_under_review(api)
    resp = api.decide_variance(
        var["id"], {"decision": "GRANT", "granted_value": 100},
        make_applicant_headers(applicant["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_recommend_unknown_variance_generic_not_found(api):
    """PRD §2.8: "path- and body-referenced resources must exist, validated left to
    right; a missing generic resource yields `ERR_NOT_FOUND`."

    Design: Corner/entities/recommend_variance_generic_not_found
    """
    resp = api.recommend_variance(
        NON_EXISTENT_UUID, {"recommendation": "RECOMMEND_APPROVE"}, make_planner_headers())
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
