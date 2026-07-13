"""Artist calls, panel scoring, tabulation, and the composite score."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    TEST_USERS, ApiErrorId,
    make_call_payload, make_score_payload,
    make_panelist_headers, make_artist_headers,
    create_certified_project, create_commission, create_call, create_artist,
    setup_open_call_with_submission, setup_scored_submission, add_score, set_clock,
)

ADMIN = TEST_USERS["program_admin_headers"]


def test_invalid_call_type_enum_rejected(api):
    """PRD §3.3: "A `ProgramAdmin` opens a call by supplying its `call_type` —
    either `RFQ` or `RFP` — the `submission_deadline` (an ISO 8601 UTC instant),
    and the `quorum_min`, which must be at least 1"
    PRD §2.9: "The generic body-validation failure (a missing or malformed
    required field, an out-of-range enum, or a missing required
    `expected_project_version` or `expected_contract_version`) surfaces as
    `ERR_VALIDATION` (HTTP 422)."

    Design: Corner/entities/invalid_call_type_enum_rejected
    """
    proj = create_certified_project(api)
    comm = create_commission(api, proj["id"], allocation_cents=900000)
    resp = api.create_call(comm["id"], make_call_payload(call_type="BID", quorum_min=1), ADMIN)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, 422)


def test_weighted_value_computed_on_score_create(api):
    """PRD §3.4: "Each accepted score carries a computed `weighted_value`: the sum
    of 0.40 times `artistic_merit`, 0.25 times `feasibility`, 0.20 times
    `community_impact`, and 0.15 times `durability`."

    Design: Corner/entities/weighted_value_computed_on_score_create
    """
    ctx = setup_open_call_with_submission(api, num_panelists=1)
    pan = ctx["panelists"][0]
    data = validate_success(api.create_score(
        ctx["submission"]["id"], make_score_payload(pan["id"], 80, 70, 60, 50),
        make_panelist_headers(pan["id"])), 201)
    assert data["weighted_value"] == 69.0


def test_recused_panelist_cannot_score(api):
    """PRD §3.4: "a recused panelist (one whose declared conflict left
    `has_conflict` true) may not score at all, and an attempt to do so is rejected
    first with `ERR_PANELIST_CONFLICT` (HTTP 422)"

    Design: Corner/validations/recused_panelist_cannot_score
    """
    ctx = setup_open_call_with_submission(api, num_panelists=1, panelist_conflicts=[True])
    pan = ctx["panelists"][0]
    resp = api.create_score(
        ctx["submission"]["id"], make_score_payload(pan["id"], 80, 80, 80, 80),
        make_panelist_headers(pan["id"]))
    validate_error(resp, ApiErrorId.ERR_PANELIST_CONFLICT.value, 422)


def test_duplicate_score_by_panelist_rejected(api):
    """PRD §3.4: "a panelist may hold at most one score per submission, so a second
    score for the same submission is then rejected with `ERR_DUPLICATE_SCORE`
    (HTTP 409)."

    Design: Corner/validations/duplicate_score_by_panelist_rejected
    """
    ctx = setup_open_call_with_submission(api, num_panelists=1)
    pan = ctx["panelists"][0]
    add_score(api, ctx["submission"]["id"], pan["id"], 70, 70, 70, 70)
    resp = api.create_score(
        ctx["submission"]["id"], make_score_payload(pan["id"], 90, 90, 90, 90),
        make_panelist_headers(pan["id"]))
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_SCORE.value, 409)


def test_panelist_scoring_with_wrong_user_id_not_owner(api):
    """PRD §2.1: "when a `Panelist` scores a submission, the `panelist_id` on the
    new score must equal `X-User-ID`"
    PRD §2.1: "Any of these ownership mismatches is rejected with `ERR_NOT_OWNER`
    (HTTP 403)."

    Design: Corner/rbac/panelist_scoring_with_wrong_user_id_not_owner
    """
    ctx = setup_open_call_with_submission(api, num_panelists=2)
    pan1, pan2 = ctx["panelists"]
    resp = api.create_score(
        ctx["submission"]["id"], make_score_payload(pan1["id"], 80, 80, 80, 80),
        make_panelist_headers(pan2["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_OWNER.value, 403)


def test_submission_after_deadline_rejected(api):
    """PRD §3.3: "the moment of submission — the logical clock — must fall strictly
    before the call's `submission_deadline`; a submission at or after the deadline
    is rejected with `ERR_DEADLINE_PASSED` (HTTP 422)."

    Design: Corner/validations/submission_after_deadline_rejected
    """
    proj = create_certified_project(api)
    comm = create_commission(api, proj["id"], allocation_cents=900000)
    call = create_call(api, comm["id"], call_type="RFP",
                       submission_deadline="2026-06-01T00:00:00Z", quorum_min=1)
    artist = create_artist(api)
    set_clock(api, "2026-06-02T00:00:00Z")
    resp = api.create_submission(
        call["id"], {"artist_id": artist["id"], "proposed_budget_cents": 700000},
        make_artist_headers(artist["id"]))
    validate_error(resp, ApiErrorId.ERR_DEADLINE_PASSED.value, 422)


def test_close_call_twice_returns_invalid_state(api):
    """PRD §3.4: "A `ProgramAdmin` closes an `OPEN` call, moving it
    `OPEN → CLOSED`; once closed, new submissions to it are refused on state
    grounds."
    PRD §2.9: "State legality (whether the target resource is in a state that
    permits the requested transition) is checked next, yielding `ERR_INVALID_STATE`
    (HTTP 409)."

    Design: Corner/state_machines/close_call_twice_returns_invalid_state
    """
    proj = create_certified_project(api)
    comm = create_commission(api, proj["id"], allocation_cents=500000)
    call = create_call(api, comm["id"], call_type="RFQ", quorum_min=1)
    validate_success(api.close_call(call["id"], ADMIN), 200)
    resp = api.close_call(call["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
    refreshed = get_success_data(api.get_call(call["id"], ADMIN))
    assert refreshed["status"] == "CLOSED"


def test_tabulate_uses_trimmed_variant_with_three_scores(api):
    """PRD §3.4: "**Trimmed variant** — when there are at least three counted
    scores: drop exactly one score with the highest `weighted_value` and exactly
    one score with the lowest `weighted_value` (if two scores tie for an extreme,
    drop the one with the earlier `created_at`), then take the mean of the
    remaining `weighted_value` figures and round it half-up to two decimal places."

    Design: Difficulty/dual_variant_calc/submission_composite_mean_vs_trimmed
    """
    ctx = setup_scored_submission(
        api, [(80, 70, 60, 50), (90, 60, 80, 70), (60, 90, 50, 45)], quorum_min=3)
    validate_success(api.tabulate_call(ctx["call"]["id"], ADMIN), 200)
    sub = get_success_data(api.get_submission(ctx["submission"]["id"], ADMIN))
    assert sub["composite_score"] == 69.00
    assert sub["status"] == "SCORED"


def test_trimmed_variant_diverges_from_simple_mean(api):
    """PRD §3.4: "**Trimmed variant** — when there are at least three counted
    scores: drop exactly one score with the highest `weighted_value` and exactly
    one score with the lowest `weighted_value` (if two scores tie for an extreme,
    drop the one with the earlier `created_at`), then take the mean of the
    remaining `weighted_value` figures and round it half-up to two decimal places."

    Design: Difficulty/dual_variant_calc/submission_composite_mean_vs_trimmed
    """
    ctx = setup_scored_submission(
        api, [(80, 70, 60, 50), (90, 60, 80, 70), (60, 90, 50, 45)], quorum_min=3)
    validate_success(api.tabulate_call(ctx["call"]["id"], ADMIN), 200)
    sub = get_success_data(api.get_submission(ctx["submission"]["id"], ADMIN))
    # Trimmed keeps only the middle weighted_value (69.0); the simple mean of all
    # three weighted_values would be 69.92.
    assert sub["composite_score"] == 69.00
    assert sub["composite_score"] != 69.92


def test_durability_gate_disqualifies_submission(api):
    """PRD §3.4: "First the durability gate: take the mean of the `durability`
    criterion across the counted scores; if that mean is below the durability floor
    of 40, the submission is disqualified — its `composite_score` is set to 0 and
    it transitions `SUBMITTED → DISQUALIFIED`."

    Design: Difficulty/combinatorial_formula/composite_weighted_with_durability_gate
    """
    ctx = setup_scored_submission(
        api, [(90, 90, 90, 30), (85, 85, 85, 35), (80, 80, 80, 20)], quorum_min=3)
    validate_success(api.tabulate_call(ctx["call"]["id"], ADMIN), 200)
    sub = get_success_data(api.get_submission(ctx["submission"]["id"], ADMIN))
    assert sub["composite_score"] == 0
    assert sub["status"] == "DISQUALIFIED"


def test_low_durability_forces_zero_composite(api):
    """PRD §3.4: "First the durability gate: take the mean of the `durability`
    criterion across the counted scores; if that mean is below the durability floor
    of 40, the submission is disqualified — its `composite_score` is set to 0 and
    it transitions `SUBMITTED → DISQUALIFIED`."

    Design: Difficulty/combinatorial_formula/composite_weighted_with_durability_gate
    """
    ctx = setup_scored_submission(
        api, [(90, 90, 90, 30), (85, 85, 85, 35), (80, 80, 80, 20)], quorum_min=3)
    validate_success(api.tabulate_call(ctx["call"]["id"], ADMIN), 200)
    sub = get_success_data(api.get_submission(ctx["submission"]["id"], ADMIN))
    assert sub["status"] == "DISQUALIFIED"
    assert sub["composite_score"] == 0


def test_request_revision_moves_to_revision_requested(api):
    """PRD §3.3: "A `ProgramAdmin` may request a revision on a submission that is
    `SUBMITTED` while its call is still `OPEN`, moving it
    `SUBMITTED → REVISION_REQUESTED`; as a side effect, any existing `Score` rows
    for that submission are discarded, because a revised proposal must be re-scored
    from scratch."

    Design: Difficulty/non_linear_state_machine/submission_revision_cycle_back_to_submitted
    """
    ctx = setup_open_call_with_submission(api)
    data = validate_success(api.request_revision(ctx["submission"]["id"], ADMIN), 200)
    assert data["status"] == "REVISION_REQUESTED"


def test_resubmit_returns_submission_to_submitted(api):
    """PRD §3.3: "the owner moves a `REVISION_REQUESTED` submission back to
    `SUBMITTED`, re-entering the scoring pool."
    PRD §3.3: "This forms the cycle `SUBMITTED → REVISION_REQUESTED → SUBMITTED`."

    Design: Difficulty/non_linear_state_machine/submission_revision_cycle_back_to_submitted
    """
    ctx = setup_open_call_with_submission(api)
    artist_id = ctx["artist"]["id"]
    validate_success(api.request_revision(ctx["submission"]["id"], ADMIN), 200)
    data = validate_success(
        api.resubmit_submission(ctx["submission"]["id"], make_artist_headers(artist_id)), 200)
    assert data["status"] == "SUBMITTED"


def test_tabulate_below_quorum_rejected(api):
    """PRD §3.4: "the number of non-recused panelists on the call who have scored
    **every** non-withdrawn submission on that call must be at least the call's
    `quorum_min` (the boundary is inclusive — exactly `quorum_min` such panelists
    suffices). If fewer qualify, tabulation is rejected with `ERR_QUORUM_NOT_MET`
    (HTTP 409)."

    Design: Difficulty/boundary_precision_check/quorum_below_min_blocks_tabulation
    """
    ctx = setup_scored_submission(api, [(80, 80, 80, 80)], quorum_min=2)
    resp = api.tabulate_call(ctx["call"]["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_QUORUM_NOT_MET.value, 409)


def test_call_remains_closed_after_quorum_failure(api):
    """PRD §3.4: "the number of non-recused panelists on the call who have scored
    **every** non-withdrawn submission on that call must be at least the call's
    `quorum_min` (the boundary is inclusive — exactly `quorum_min` such panelists
    suffices). If fewer qualify, tabulation is rejected with `ERR_QUORUM_NOT_MET`
    (HTTP 409)."

    Design: Difficulty/boundary_precision_check/quorum_below_min_blocks_tabulation
    """
    ctx = setup_scored_submission(api, [(80, 80, 80, 80)], quorum_min=2)
    api.tabulate_call(ctx["call"]["id"], ADMIN)
    refreshed = get_success_data(api.get_call(ctx["call"]["id"], ADMIN))
    assert refreshed["status"] == "CLOSED"
