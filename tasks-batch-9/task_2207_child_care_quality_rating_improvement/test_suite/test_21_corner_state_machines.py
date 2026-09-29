"""State machines: initial states, illegal transitions, auto-advance, branching and cascades."""
import pytest

from test_helpers import (
    REVIEWER_USER_ID,
    TEST_USERS,
    accept_grant,
    build_rating_spine,
    create_enrolled_provider,
    dispute_action,
    make_observer_headers,
    make_provider_headers,
    make_reviewer_headers,
    offer_grant,
    points_map,
    run_expiry_run,
    schedule_session,
    score_payload,
    set_clock,
    setup_active_allocation,
    setup_appeal_under_review,
    setup_dispute_in_triage,
    setup_tier_one_active_spine,
    setup_tier_one_published_spine,
    submit_expenditure,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]

CLOCK_T0 = "2026-08-03T00:00:00Z"
TIER_ONE_POINTS = points_map(learning=12, staff=8)


def test_rating_cycle_starts_in_draft_and_unpublished(api):
    """PRD §3.3: "A cycle that passes those gates is created in `DRAFT` with `opened_on`
    stamped from the logical clock, with `provider_id` recording the owning provider, and
    with `supersedes_cycle_id` pointed at the provider's currently active cycle when one
    exists and left null when this is the provider's first cycle."
    PRD §3.3: "A cycle's `publication_status` begins at `UNPUBLISHED`, its `appeal_adjusted`
    flag begins as false, and its `superseded_by_cycle_id`, `awarded_tier`, `awarded_on`,
    `awarded_by_user_id`, `published_at`, `published_snapshot`, `observation_composite`,
    `reliability_pct`, `effective_date`, `expires_on`, `validity_months`, and
    `rerating_window_opens_on` all begin null."

    Design: Corner/state_machines/rating_cycle_starts_in_draft_and_unpublished
    """
    ctx = build_rating_spine(
        stop_at="DRAFT", enrol_clock=CLOCK_T0, cycle_clock=CLOCK_T0
    )
    cycle = validate_success(api.get_rating_cycle(ctx["cycle"]["id"], ADMIN))

    assert cycle["status"] == "DRAFT", f"a new cycle starts in DRAFT, got {cycle['status']}"
    assert cycle["publication_status"] == "UNPUBLISHED", (
        f"publication_status begins at UNPUBLISHED, got {cycle['publication_status']}"
    )
    assert cycle["appeal_adjusted"] is False, (
        f"appeal_adjusted begins false, got {cycle['appeal_adjusted']}"
    )
    assert cycle["provider_id"] == ctx["provider"]["id"], (
        f"provider_id records the owning provider, got {cycle['provider_id']}"
    )
    assert cycle["supersedes_cycle_id"] is None, (
        f"a first cycle supersedes nothing, got {cycle['supersedes_cycle_id']}"
    )
    assert cycle["opened_on"].startswith("2026-08-03"), (
        f"opened_on is stamped from the logical clock date, got {cycle['opened_on']}"
    )
    for field in (
        "superseded_by_cycle_id",
        "awarded_tier",
        "awarded_on",
        "awarded_by_user_id",
        "published_at",
        "published_snapshot",
        "observation_composite",
        "reliability_pct",
        "effective_date",
        "expires_on",
        "validity_months",
        "rerating_window_opens_on",
    ):
        assert cycle[field] is None, f"{field} must begin null, got {cycle[field]!r}"


def test_award_from_docs_verified_returns_cycle_state_invalid(api):
    """PRD §3.5: "Issuing the award is an administrator action against a cycle sitting in
    `OBSERVATION_FINALIZED`, and it carries a `score_variant` input recording which variant
    produced the tier."
    PRD §2.7: "Tenth, the target resource's own state must be one from which the requested
    transition is declared, producing the state-family code for that entity —
    `ERR_PROVIDER_STATE_INVALID`, `ERR_CYCLE_STATE_INVALID`, `ERR_VISIT_STATE_INVALID`,
    `ERR_APPEAL_STATE_INVALID`, `ERR_DISPUTE_STATE_INVALID`, `ERR_GRANT_NOT_OPEN`,
    `ERR_EXPENDITURE_STATE_INVALID`, `ERR_ALLOCATION_STATE_INVALID`,
    `ERR_SESSION_STATE_INVALID`, or `ERR_CLAIM_STATE_INVALID` — each with HTTP 409."
    PRD §3.3: "On approval the self-assessment moves to `VERIFIED`, `verified_on` is stamped
    from the logical clock, the cycle advances `SELF_ASSESSMENT_SUBMITTED → DOCS_VERIFIED`,
    and the cycle's `domain_points` map is provisionally recomputed under the provisional
    scoring variant described in §3.5."

    Design: Corner/state_machines/award_from_docs_verified_returns_cycle_state_invalid
    """
    ctx = build_rating_spine(
        stop_at="DOCS_VERIFIED", claimed=TIER_ONE_POINTS, verified=TIER_ONE_POINTS
    )
    cycle_id = ctx["cycle"]["id"]
    assert ctx["cycle"]["status"] == "DOCS_VERIFIED", (
        f"the spine must stop at DOCS_VERIFIED, got {ctx['cycle']['status']}"
    )

    validate_error(
        api.award_cycle(cycle_id, {"score_variant": "FINAL"}, ADMIN),
        "ERR_CYCLE_STATE_INVALID",
        409,
    )

    cycle = validate_success(api.get_rating_cycle(cycle_id, ADMIN))
    assert cycle["status"] == "DOCS_VERIFIED", (
        f"the refused award must not move the cycle, got {cycle['status']}"
    )
    assert cycle["awarded_tier"] is None, (
        f"awarded_tier must stay null, got {cycle['awarded_tier']!r}"
    )
    assert cycle["awarded_on"] is None, f"awarded_on must stay null, got {cycle['awarded_on']!r}"
    assert cycle["awarded_by_user_id"] is None, (
        f"awarded_by_user_id must stay null, got {cycle['awarded_by_user_id']!r}"
    )
    assert cycle["domain_points"]["LEARNING_ENVIRONMENT"] == 12, (
        "the provisional recomputation at DOCS_VERIFIED keeps the claimed 12 points for the "
        f"observation-linked domain, got {cycle['domain_points']['LEARNING_ENVIRONMENT']}"
    )
    assert cycle["domain_points"]["STAFF_QUALIFICATIONS"] == 8, (
        f"STAFF_QUALIFICATIONS must be 8, got {cycle['domain_points']['STAFF_QUALIFICATIONS']}"
    )
    assert cycle["domain_points"]["FAMILY_PARTNERSHIP"] == 0
    assert cycle["domain_points"]["ADMINISTRATION"] == 0
    assert cycle["domain_points"]["CHILD_ASSESSMENT"] == 0


def test_second_enrollment_approve_on_enrolled_provider_rejected(api):
    """PRD §3.1: "An enrollment decision resolves the application. The request carries a
    `decision` of either approval or denial, and the provider must still be in `APPLIED` —
    otherwise `ERR_PROVIDER_STATE_INVALID` is returned."
    PRD §3.1: "Approval moves the provider `APPLIED → ENROLLED`, stamps `enrolled_on` with
    the logical clock date, and recomputes `credential_compliance_pct`; it also re-confirms
    that no other provider holds the same `license_number`."
    PRD §3.1: "Either way, the provider's `version` increments by 1."

    Design: Corner/state_machines/second_enrollment_approve_on_enrolled_provider_rejected
    """
    set_clock(CLOCK_T0)
    provider = create_enrolled_provider(legal_name="Twice Approved Center")
    assert provider["status"] == "ENROLLED", (
        f"the first approval must leave the provider ENROLLED, got {provider['status']}"
    )

    validate_error(
        api.decide_enrollment(provider["id"], {"decision": "APPROVE"}, ADMIN),
        "ERR_PROVIDER_STATE_INVALID",
        409,
    )

    refreshed = validate_success(api.get_provider(provider["id"], ADMIN))
    assert refreshed["status"] == "ENROLLED", (
        f"the refused second decision must not move the provider, got {refreshed['status']}"
    )
    assert refreshed["enrolled_on"].startswith("2026-08-03"), (
        f"enrolled_on keeps its original stamp, got {refreshed['enrolled_on']}"
    )
    assert refreshed["version"] == 2, (
        "one accepted mutation took the provider from version 1 to 2 and the refusal adds "
        f"nothing, got {refreshed['version']}"
    )


def test_sixth_lead_subscale_auto_advances_visit_to_scores_entered(api):
    """PRD §3.4: "Score submissions drive the visit through its states without any explicit
    administrative action. The first accepted score advances the visit `SCHEDULED →
    IN_PROGRESS`, and that first score is admitted only when the logical clock instant is at
    or after `window_start`. Once the lead observer holds a current row for all six subscale
    codes the visit advances `IN_PROGRESS → SCORES_ENTERED` and the visit's `composite` is
    computed."
    PRD §3.4: "Otherwise the six raw scores are added together without any intermediate
    rounding, the sum is divided by six, and only that quotient is rounded half up to two
    decimal places."

    Design: Corner/state_machines/sixth_lead_subscale_auto_advances_visit_to_scores_entered
    """
    ctx = build_rating_spine(
        stop_at="OBSERVATION_SCHEDULED", claimed=TIER_ONE_POINTS, verified=TIER_ONE_POINTS
    )
    visit_id = ctx["visit"]["id"]
    lead_headers = make_observer_headers(ctx["lead"]["id"])
    set_clock("2026-08-06T09:00:00Z")

    five = [
        ("SPACE_FURNISHINGS", 5.5),
        ("PERSONAL_CARE", 6.0),
        ("LANGUAGE_REASONING", 6.5),
        ("ACTIVITIES", 5.0),
        ("INTERACTION", 6.0),
    ]
    for code, value in five:
        validate_success(api.submit_score(visit_id, score_payload(code, value), lead_headers), 201)

    partway = validate_success(api.get_observation_visit(visit_id, ADMIN))
    assert partway["status"] == "IN_PROGRESS", (
        f"five of six subscales leave the visit IN_PROGRESS, got {partway['status']}"
    )
    assert partway["composite"] is None, (
        f"the composite cannot be computed from five rows, got {partway['composite']!r}"
    )

    validate_success(
        api.submit_score(visit_id, score_payload("PROGRAM_STRUCTURE", 5.5), lead_headers), 201
    )

    visit = validate_success(api.get_observation_visit(visit_id, ADMIN))
    assert visit["status"] == "SCORES_ENTERED", (
        f"the sixth lead row advances the visit to SCORES_ENTERED, got {visit['status']}"
    )
    assert visit["composite"] == pytest.approx(5.75, abs=0.005), (
        f"34.5 divided by six rounds half up to 5.75, got {visit['composite']}"
    )
    assert visit["reliability_pct"] is None, (
        f"a single-observer visit has no reliability yet, got {visit['reliability_pct']!r}"
    )
    assert visit["rescore_count"] == 0, (
        f"no rescore has happened, got {visit['rescore_count']}"
    )

    cycle = validate_success(api.get_rating_cycle(ctx["cycle"]["id"], ADMIN))
    assert cycle["status"] == "OBSERVATION_SCHEDULED", (
        f"scoring does not move the cycle, got {cycle['status']}"
    )
    assert cycle["observation_composite"] is None, (
        "the composite reaches the cycle only at finalization, got "
        f"{cycle['observation_composite']!r}"
    )


def test_single_observer_finalize_branch_nulls_reliability_pct(api):
    """PRD §3.4: "The single-observer branch runs from `SCORES_ENTERED → FINALIZED` and is
    legal only below the upper tiers. It requires that the visit have no
    `secondary_observer_id` at all, that the tier implied by a provisional
    tier-determination run be no greater than 3, and that the lead observer be in
    `RELIABLE` standing with certification covering `window_start`. It stamps
    `finalized_on`, sets the visit's `reliability_pct` to null rather than to a computed
    value, propagates the composite onto the cycle while leaving the cycle's
    `reliability_pct` null, advances the cycle to `OBSERVATION_FINALIZED`, and likewise
    reruns the final points award."

    Design: Corner/state_machines/single_observer_finalize_branch_nulls_reliability_pct
    """
    ctx = build_rating_spine(
        stop_at="SCORES_ENTERED",
        claimed=TIER_ONE_POINTS,
        verified=TIER_ONE_POINTS,
        raw_score=4.0,
    )
    assert ctx["visit"]["status"] == "SCORES_ENTERED", (
        f"the spine must stop at SCORES_ENTERED, got {ctx['visit']['status']}"
    )
    assert ctx["visit"]["secondary_observer_id"] is None, (
        "the single-observer branch requires no secondary observer, got "
        f"{ctx['visit']['secondary_observer_id']!r}"
    )

    visit = validate_success(api.finalize_visit(ctx["visit"]["id"], ADMIN))

    assert visit["status"] == "FINALIZED", (
        f"the single-observer branch drives the visit to FINALIZED, got {visit['status']}"
    )
    assert visit["reliability_pct"] is None, (
        "the single-observer branch sets reliability_pct to null rather than a computed "
        f"value, got {visit['reliability_pct']!r}"
    )
    assert visit["composite"] == pytest.approx(4.00, abs=0.005), (
        f"six rows of 4.0 average to 4.00, got {visit['composite']}"
    )
    assert visit["finalized_on"].startswith("2026-08-06T09:00:00"), (
        f"finalized_on is stamped from the logical clock, got {visit['finalized_on']}"
    )

    cycle = validate_success(api.get_rating_cycle(ctx["cycle"]["id"], ADMIN))
    assert cycle["status"] == "OBSERVATION_FINALIZED", (
        f"finalization advances the cycle to OBSERVATION_FINALIZED, got {cycle['status']}"
    )
    assert cycle["observation_composite"] == pytest.approx(4.00, abs=0.005), (
        f"the composite propagates onto the cycle, got {cycle['observation_composite']}"
    )
    assert cycle["reliability_pct"] is None, (
        f"the cycle's reliability_pct stays null, got {cycle['reliability_pct']!r}"
    )
    assert cycle["domain_points"]["LEARNING_ENVIRONMENT"] == 12, (
        "the rerun final award derives the observation-linked domain from the 4.00 composite "
        f"as 20 x 0.60, got {cycle['domain_points']['LEARNING_ENVIRONMENT']}"
    )
    assert cycle["domain_points"]["STAFF_QUALIFICATIONS"] == 8, (
        f"STAFF_QUALIFICATIONS must be 8, got {cycle['domain_points']['STAFF_QUALIFICATIONS']}"
    )
    assert cycle["awarded_tier"] is None, (
        f"finalization is not an award, got {cycle['awarded_tier']!r}"
    )


def test_scores_on_finalized_visit_returns_visit_state_invalid(api):
    """PRD §3.4: "A visit in `SCORES_ENTERED`, `RELIABILITY_CHECK`, or already `FINALIZED`
    cannot be cancelled; `FINALIZED` and `CANCELLED` are both terminal for a visit."
    PRD §2.7: "Tenth, the target resource's own state must be one from which the requested
    transition is declared, producing the state-family code for that entity —
    `ERR_PROVIDER_STATE_INVALID`, `ERR_CYCLE_STATE_INVALID`, `ERR_VISIT_STATE_INVALID`,
    `ERR_APPEAL_STATE_INVALID`, `ERR_DISPUTE_STATE_INVALID`, `ERR_GRANT_NOT_OPEN`,
    `ERR_EXPENDITURE_STATE_INVALID`, `ERR_ALLOCATION_STATE_INVALID`,
    `ERR_SESSION_STATE_INVALID`, or `ERR_CLAIM_STATE_INVALID` — each with HTTP 409."

    Design: Corner/state_machines/scores_on_finalized_visit_returns_visit_state_invalid
    """
    ctx = build_rating_spine(
        stop_at="OBSERVATION_FINALIZED",
        claimed=TIER_ONE_POINTS,
        verified=TIER_ONE_POINTS,
        raw_score=4.0,
    )
    visit_id = ctx["visit"]["id"]
    lead_headers = make_observer_headers(ctx["lead"]["id"])

    validate_error(
        api.submit_score(visit_id, score_payload("INTERACTION", 7.0), lead_headers),
        "ERR_VISIT_STATE_INVALID",
        409,
    )

    visit = validate_success(api.get_observation_visit(visit_id, ADMIN))
    assert visit["status"] == "FINALIZED", (
        f"FINALIZED is terminal for a visit, got {visit['status']}"
    )
    assert visit["composite"] == pytest.approx(4.00, abs=0.005), (
        f"the frozen composite must stay 4.00, got {visit['composite']}"
    )
    assert visit["rescore_count"] == 0, (
        f"the refused submission increments no counter, got {visit['rescore_count']}"
    )

    rows, meta = validate_paginated(
        api.list_observation_scores(ADMIN, params={"observation_visit_id": visit_id})
    )
    assert meta["total_count"] == 6, (
        f"the refused submission appends no row, got total_count {meta['total_count']}"
    )
    assert len(rows) == 6, f"exactly the six finalized rows must be listed, got {len(rows)}"

    one, one_meta = validate_paginated(
        api.list_observation_scores(
            ADMIN, params={"observation_visit_id": visit_id, "subscale_code": "INTERACTION"}
        )
    )
    assert one_meta["total_count"] == 1, (
        f"INTERACTION must still hold a single attempt, got {one_meta['total_count']}"
    )
    assert one[0]["raw_score"] == pytest.approx(4.0, abs=0.005), (
        f"the stored INTERACTION score must stay 4.0, got {one[0]['raw_score']}"
    )


def test_appeal_info_requested_loop_returns_to_under_review(api):
    """PRD §3.6: "Requesting information moves the appeal `UNDER_REVIEW → INFO_REQUESTED`
    and increments `info_request_count` by 1, and it is available only while
    `info_request_count` is less than 2 — a third request is `ERR_APPEAL_INFO_ROUND_LIMIT`
    with HTTP 409 — and only to the reviewer already recorded on the appeal."
    PRD §3.6: "The provider answers with its own action: responding moves the appeal
    `INFO_REQUESTED → UNDER_REVIEW`, appending the supplied `narrative` and changing no
    counter, and it requires the acting identifier to be the cycle's provider."
    PRD §3.6: "Filing immediately drives the cycle to `UNDER_APPEAL`, drives its publication
    state to `SUPPRESSED`, sets the provider's `public_listing_visible` to false, and
    increments the provider's `version` by 1."

    Design: Corner/state_machines/appeal_info_requested_loop_returns_to_under_review
    """
    ctx, appeal = setup_appeal_under_review()
    appeal_id = appeal["id"]
    assert appeal["status"] == "UNDER_REVIEW", (
        f"the fixture must leave the appeal UNDER_REVIEW, got {appeal['status']}"
    )
    assert appeal["reviewer_user_id"] == REVIEWER_USER_ID, (
        f"reviewer_user_id records the acting reviewer, got {appeal['reviewer_user_id']}"
    )
    assert appeal["info_request_count"] == 0, (
        f"info_request_count starts at 0, got {appeal['info_request_count']}"
    )

    requested = validate_success(
        api.appeal_review_action(
            appeal_id,
            {"action": "REQUEST_INFO", "note": "supply the lead observer's field notes"},
            make_reviewer_headers(REVIEWER_USER_ID),
        )
    )
    assert requested["status"] == "INFO_REQUESTED", (
        f"requesting information moves the appeal to INFO_REQUESTED, got {requested['status']}"
    )
    assert requested["info_request_count"] == 1, (
        f"info_request_count increments by 1, got {requested['info_request_count']}"
    )
    assert requested["decided_on"] is None, (
        f"an information request decides nothing, got {requested['decided_on']!r}"
    )

    responded = validate_success(
        api.appeal_provider_action(
            appeal_id,
            {"action": "RESPOND", "narrative": "field notes attached for all six subscales"},
            make_provider_headers(ctx["provider"]["id"]),
        )
    )
    assert responded["status"] == "UNDER_REVIEW", (
        f"responding returns the appeal to UNDER_REVIEW, got {responded['status']}"
    )
    assert responded["info_request_count"] == 1, (
        f"responding changes no counter, got {responded['info_request_count']}"
    )
    assert responded["reviewer_user_id"] == REVIEWER_USER_ID, (
        f"the recorded reviewer is unchanged, got {responded['reviewer_user_id']}"
    )
    assert responded["decided_on"] is None, (
        f"the loop decides nothing, got {responded['decided_on']!r}"
    )

    cycle = validate_success(api.get_rating_cycle(ctx["cycle"]["id"], ADMIN))
    assert cycle["status"] == "UNDER_APPEAL", (
        f"the cycle stays UNDER_APPEAL across the loop, got {cycle['status']}"
    )
    assert cycle["publication_status"] == "SUPPRESSED", (
        f"publication stays SUPPRESSED across the loop, got {cycle['publication_status']}"
    )
    provider = validate_success(api.get_provider(ctx["provider"]["id"], ADMIN))
    assert provider["public_listing_visible"] is False, (
        f"the provider stays delisted across the loop, got {provider['public_listing_visible']}"
    )


def test_appeal_deny_restores_cycle_active_and_republished_listing(api):
    """PRD §3.6: "Denying an appeal from `UNDER_REVIEW` moves it to `DENIED`, stamps
    `decided_on`, and returns the cycle `UNDER_APPEAL → ACTIVE`; the cycle's publication
    state returns to `PUBLISHED` when `published_at` is non-null and otherwise stays
    `UNPUBLISHED`, and the held subsidy claims become adjudicable again."
    PRD §3.6: "That visibility flag is true exactly when the provider's
    `current_rating_cycle_id` is non-null and the cycle it names has publication state
    `PUBLISHED`."
    PRD §3.6: "`SUSTAINED`, `DENIED`, and `WITHDRAWN` are the terminal states of an appeal."

    Design: Corner/state_machines/appeal_deny_restores_cycle_active_and_republished_listing
    """
    ctx, appeal = setup_appeal_under_review()

    denied = validate_success(
        api.appeal_review_action(
            appeal["id"],
            {"action": "DENY", "note": "the scoring record is sound"},
            make_reviewer_headers(REVIEWER_USER_ID),
        )
    )
    assert denied["status"] == "DENIED", (
        f"denial from UNDER_REVIEW moves the appeal to DENIED, got {denied['status']}"
    )
    assert denied["decided_on"] is not None, "denial must stamp decided_on"
    assert denied["adjusted_tier"] is None, (
        f"a denial orders no tier change, got {denied['adjusted_tier']!r}"
    )

    cycle = validate_success(api.get_rating_cycle(ctx["cycle"]["id"], ADMIN))
    assert cycle["status"] == "ACTIVE", (
        f"denial returns the cycle UNDER_APPEAL -> ACTIVE, got {cycle['status']}"
    )
    assert cycle["published_at"] is not None, (
        "the fixture published the cycle before the appeal, so published_at is non-null"
    )
    assert cycle["publication_status"] == "PUBLISHED", (
        "publication returns to PUBLISHED because published_at is non-null, got "
        f"{cycle['publication_status']}"
    )
    assert cycle["appeal_adjusted"] is False, (
        f"a denied appeal adjusts nothing, got {cycle['appeal_adjusted']}"
    )
    assert cycle["awarded_tier"] == 1, (
        f"the awarded tier is untouched by a denial, got {cycle['awarded_tier']}"
    )

    provider = validate_success(api.get_provider(ctx["provider"]["id"], ADMIN))
    assert provider["current_rating_cycle_id"] == ctx["cycle"]["id"], (
        f"the provider still names the cycle, got {provider['current_rating_cycle_id']}"
    )
    assert provider["public_listing_visible"] is True, (
        "the flag is true exactly when the named cycle is PUBLISHED, got "
        f"{provider['public_listing_visible']}"
    )

    rows, meta = validate_paginated(api.list_public_ratings(TEST_USERS["family_headers"]))
    assert meta["total_count"] == 1, (
        f"the republished cycle reappears in the family directory, got {meta['total_count']}"
    )
    assert len(rows) == 1, f"exactly one published rating must be visible, got {len(rows)}"


def test_dispute_escalate_then_reopen_triage_increments_round_only(api):
    """PRD §3.6: "Opening triage from `FILED` requires the cycle's publication state to be
    `PUBLISHED` and increments `triage_round` by 1."
    PRD §3.6: "Escalation moves the dispute `TRIAGE → ESCALATED` and is available only when
    the `disputed_field` is `PUBLISHED_TIER`, `PUBLISHED_SCORE`, or `DOMAIN_POINTS` — the two
    provider-attribute fields are never escalated — and it changes no counter."
    PRD §3.6: "Returning from `ESCALATED` to `TRIAGE` likewise requires `triage_round` to be
    less than 3 and increments it by 1."
    PRD §3.6: "Filing a dispute does not suspend publication; families continue to see the
    snapshot while the dispute is worked."
    PRD §3.6: "Publishing drives the cycle's `publication_status` to `PUBLISHED`, stamps
    `published_at` from the logical clock, and freezes a `published_snapshot` containing the
    awarded tier, the `weighted_total`, the `domain_points` map, the provider's
    `licensed_capacity`, and its `county_code`."

    Design: Corner/state_machines/dispute_escalate_then_reopen_triage_increments_round_only
    """
    ctx, dispute = setup_dispute_in_triage(
        disputed_field="DOMAIN_POINTS", claimed_value="LEARNING_ENVIRONMENT=16"
    )
    assert dispute["status"] == "TRIAGE", (
        f"the fixture must leave the dispute in TRIAGE, got {dispute['status']}"
    )
    assert dispute["triage_round"] == 1, (
        f"opening triage from FILED increments triage_round to 1, got {dispute['triage_round']}"
    )

    escalated = dispute_action(ADMIN, dispute["id"], "ESCALATE")
    assert escalated["status"] == "ESCALATED", (
        f"escalation moves the dispute to ESCALATED, got {escalated['status']}"
    )
    assert escalated["triage_round"] == 1, (
        f"escalation changes no counter, got {escalated['triage_round']}"
    )

    returned = dispute_action(ADMIN, dispute["id"], "OPEN_TRIAGE")
    assert returned["status"] == "TRIAGE", (
        f"returning from ESCALATED lands back in TRIAGE, got {returned['status']}"
    )
    assert returned["triage_round"] == 2, (
        f"the return increments triage_round to 2, got {returned['triage_round']}"
    )
    assert returned["resolved_on"] is None, (
        f"the loop resolves nothing, got {returned['resolved_on']!r}"
    )
    assert returned["linked_appeal_id"] is None, (
        f"no appeal is linked by the loop, got {returned['linked_appeal_id']!r}"
    )
    assert returned["disputed_field"] == "DOMAIN_POINTS", (
        f"the disputed field is unchanged, got {returned['disputed_field']}"
    )

    cycle = validate_success(api.get_rating_cycle(ctx["cycle"]["id"], ADMIN))
    assert cycle["publication_status"] == "PUBLISHED", (
        "a dispute does not suspend publication, got "
        f"{cycle['publication_status']}"
    )
    snapshot = cycle["published_snapshot"]
    assert snapshot["weighted_total"] == pytest.approx(26.00, abs=0.005), (
        f"the frozen snapshot keeps weighted_total 26.00, got {snapshot['weighted_total']}"
    )
    assert snapshot["licensed_capacity"] == 60, (
        f"the frozen snapshot keeps licensed_capacity 60, got {snapshot['licensed_capacity']}"
    )
    assert snapshot["county_code"] == "DANE", (
        f"the frozen snapshot keeps county_code DANE, got {snapshot['county_code']}"
    )
    assert snapshot["domain_points"]["LEARNING_ENVIRONMENT"] == 12, (
        "the snapshot is untouched by the unresolved dispute, got "
        f"{snapshot['domain_points']['LEARNING_ENVIRONMENT']}"
    )


def test_provider_suspend_cascades_three_hops_to_coaching_sessions(api):
    """PRD §3.1: "Suspension is available only from `ACTIVE` and is a three-hop cascade: the
    provider's active cycle has its publication state set to `SUPPRESSED` and the provider's
    `public_listing_visible` becomes false; then, as a second hop, every coaching allocation
    of that provider whose own state is `ACTIVE` becomes `SUSPENDED`; then, as a third hop
    caused by each allocation's suspension, every coaching session under that allocation
    still in `SCHEDULED` becomes `CANCELLED` and its scheduled hours return to that
    allocation's remaining hours."
    PRD §3.1: "All three actions increment the provider's `version` by 1, and `WITHDRAWN` is
    terminal for a provider."

    Design: Corner/state_machines/provider_suspend_cascades_three_hops_to_coaching_sessions
    """
    ctx = setup_tier_one_published_spine()
    provider_id = ctx["provider"]["id"]
    ctx, allocation = setup_active_allocation(
        spine=ctx,
        allocated_hours=10.0,
        hourly_rate_cents=5_000,
        period_start="2026-09-01",
        period_end="2026-09-30",
    )
    assert allocation["status"] == "ACTIVE", (
        f"the allocation must be ACTIVE before the cascade, got {allocation['status']}"
    )
    session = schedule_session(
        allocation["id"], "2026-09-07T09:00:00Z", "2026-09-07T12:00:00Z"
    )
    assert session["status"] == "SCHEDULED", (
        f"the session must be SCHEDULED before the cascade, got {session['status']}"
    )

    suspended = validate_success(
        api.change_provider_status(
            provider_id,
            {"action": "SUSPEND", "reason": "license inspection finding"},
            ADMIN,
        )
    )
    assert suspended["status"] == "SUSPENDED", (
        f"suspension from ACTIVE moves the provider to SUSPENDED, got {suspended['status']}"
    )
    assert suspended["public_listing_visible"] is False, (
        f"the first hop delists the provider, got {suspended['public_listing_visible']}"
    )

    cycle = validate_success(api.get_rating_cycle(ctx["cycle"]["id"], ADMIN))
    assert cycle["publication_status"] == "SUPPRESSED", (
        f"the first hop suppresses the active cycle, got {cycle['publication_status']}"
    )
    assert cycle["status"] == "ACTIVE", (
        f"suspension does not change the cycle's own state, got {cycle['status']}"
    )

    alloc = validate_success(api.get_coaching_allocation(allocation["id"], ADMIN))
    assert alloc["status"] == "SUSPENDED", (
        f"the second hop suspends the ACTIVE allocation, got {alloc['status']}"
    )
    assert float(alloc["scheduled_hours"]) == pytest.approx(0.0, abs=0.05), (
        f"the cancelled session's hours leave scheduled_hours, got {alloc['scheduled_hours']}"
    )
    assert float(alloc["delivered_hours"]) == pytest.approx(0.0, abs=0.05), (
        f"nothing was delivered, got {alloc['delivered_hours']}"
    )
    assert float(alloc["remaining_hours"]) == pytest.approx(10.0, abs=0.05), (
        f"the 3 scheduled hours return to remaining_hours, got {alloc['remaining_hours']}"
    )

    sess = validate_success(api.get_coaching_session(session["id"], ADMIN))
    assert sess["status"] == "CANCELLED", (
        f"the third hop cancels the SCHEDULED session, got {sess['status']}"
    )

    rows, meta = validate_paginated(api.list_public_ratings(TEST_USERS["family_headers"]))
    assert meta["total_count"] == 0, (
        f"a suppressed cycle leaves the family directory, got {meta['total_count']}"
    )
    assert rows == [], f"the family directory must be empty, got {rows}"


def test_expiry_run_cascades_four_hops_across_grants_and_coaching(api):
    """PRD §3.5: "On an expiry run, every cycle in `ACTIVE` whose `expires_on` is strictly
    earlier than the logical clock date moves `ACTIVE → EXPIRED` — the expiry boundary is
    inclusive, so a cycle survives a run whose clock date equals `expires_on` exactly and
    expires on the first run whose clock date is strictly greater. That transition fires four
    hops. First, the cycle's publication state becomes `WITHDRAWN`. Second, because the cycle
    has left `ACTIVE`, the provider's `current_rating_cycle_id` and `current_tier` become
    null and `public_listing_visible` becomes false. Third, because the provider has lost its
    tier, every coaching allocation of that provider in `ACTIVE` becomes `SUSPENDED` and
    every improvement grant of that provider in `OPEN` becomes `FROZEN`. Fourth, each of
    those consequences has its own consequence: every `SCHEDULED` coaching session under a
    newly suspended allocation becomes `CANCELLED` with its scheduled hours returned to the
    allocation's remaining hours, and every `SUBMITTED` expenditure under a newly frozen
    grant becomes `VOIDED` with its amount returned to the grant's available balance."

    Design: Corner/state_machines/expiry_run_cascades_four_hops_across_grants_and_coaching
    """
    ctx = setup_tier_one_published_spine()
    provider_id = ctx["provider"]["id"]
    assert ctx["cycle"]["expires_on"] == "2028-08-31T23:59:59.999Z", (
        f"a tier-1 award effective 2026-09-01 runs 24 months, got {ctx['cycle']['expires_on']}"
    )

    set_clock("2028-08-15T00:00:00Z")
    grant = offer_grant(provider_id, ctx["cycle"]["id"], 1_000_000, "2028-12-31")
    grant = accept_grant(provider_id, grant["id"])
    assert grant["status"] == "OPEN", (
        f"an accepted grant must be OPEN before the cascade, got {grant['status']}"
    )
    expenditure = submit_expenditure(
        provider_id, grant["id"], "EQUIPMENT", 200_000, "2028-08-15"
    )
    assert expenditure["status"] == "SUBMITTED", (
        f"the line must be SUBMITTED before the cascade, got {expenditure['status']}"
    )

    ctx, allocation = setup_active_allocation(
        spine=ctx,
        allocated_hours=10.0,
        hourly_rate_cents=5_000,
        period_start="2028-08-15",
        period_end="2028-08-31",
    )
    session = schedule_session(
        allocation["id"], "2028-08-28T09:00:00Z", "2028-08-28T12:00:00Z"
    )

    set_clock("2028-09-01T00:00:00Z")
    run_expiry_run()

    cycle = validate_success(api.get_rating_cycle(ctx["cycle"]["id"], ADMIN))
    assert cycle["status"] == "EXPIRED", (
        f"a clock date strictly past expires_on expires the cycle, got {cycle['status']}"
    )
    assert cycle["publication_status"] == "WITHDRAWN", (
        f"the first hop withdraws publication, got {cycle['publication_status']}"
    )

    provider = validate_success(api.get_provider(provider_id, ADMIN))
    assert provider["current_rating_cycle_id"] is None, (
        f"the second hop nulls current_rating_cycle_id, got {provider['current_rating_cycle_id']!r}"
    )
    assert provider["current_tier"] is None, (
        f"the second hop nulls current_tier, got {provider['current_tier']!r}"
    )
    assert provider["public_listing_visible"] is False, (
        f"the second hop delists the provider, got {provider['public_listing_visible']}"
    )

    alloc = validate_success(api.get_coaching_allocation(allocation["id"], ADMIN))
    assert alloc["status"] == "SUSPENDED", (
        f"the third hop suspends the ACTIVE allocation, got {alloc['status']}"
    )
    frozen = validate_success(api.get_improvement_grant(grant["id"], ADMIN))
    assert frozen["status"] == "FROZEN", (
        f"the third hop freezes the OPEN grant, got {frozen['status']}"
    )
    assert frozen["compliance_status"] == "COMPLIANT", (
        "freezing is a disbursement-dimension move and leaves compliance alone, got "
        f"{frozen['compliance_status']}"
    )

    sess = validate_success(api.get_coaching_session(session["id"], ADMIN))
    assert sess["status"] == "CANCELLED", (
        f"the fourth hop cancels the SCHEDULED session, got {sess['status']}"
    )
    assert float(alloc["scheduled_hours"]) == pytest.approx(0.0, abs=0.05), (
        f"the cancelled hours leave scheduled_hours, got {alloc['scheduled_hours']}"
    )
    assert float(alloc["remaining_hours"]) == pytest.approx(10.0, abs=0.05), (
        f"the 3 cancelled hours return to remaining_hours, got {alloc['remaining_hours']}"
    )

    voided = validate_success(api.get_grant_expenditure(expenditure["id"], ADMIN))
    assert voided["status"] == "VOIDED", (
        f"the fourth hop voids the SUBMITTED expenditure, got {voided['status']}"
    )
    assert frozen["committed_cents"] == 0, (
        f"the voided amount leaves committed_cents, got {frozen['committed_cents']}"
    )
    assert frozen["available_cents"] == 1_000_000, (
        f"the voided 200000 returns to available_cents, got {frozen['available_cents']}"
    )

    rows, meta = validate_paginated(api.list_public_ratings(TEST_USERS["family_headers"]))
    assert meta["total_count"] == 0, (
        f"an expired cycle leaves the family directory, got {meta['total_count']}"
    )
    assert rows == [], f"the family directory must be empty, got {rows}"


def test_grant_status_open_while_compliance_reaches_finding_issued(api):
    """PRD §3.8: "Every grant carries **two independent state dimensions**. The disbursement
    dimension runs through `OFFERED`, `ACCEPTED`, `OPEN`, `FROZEN`, `CLOSED`, and `DECLINED`,
    with `CLOSED` and `DECLINED` terminal. The compliance dimension runs through `COMPLIANT`,
    `UNDER_REVIEW`, `FINDING_ISSUED`, `REMEDIATED`, and `RECOVERY`, with `RECOVERY` terminal.
    The two evolve separately: a grant may be `OPEN` and `FINDING_ISSUED` at the same time, or
    `CLOSED` and still `COMPLIANT`."
    PRD §3.8: "Rejection moves the line `SUBMITTED → REJECTED` and unwinds the commitment
    exactly: `committed_cents` decreases by the line's `amount_cents`, `available_cents`
    increases by the same amount, and that category's `category_spend_cents` entry decreases
    by the same amount, so a submit-then-reject pair leaves the grant's ledger identity
    intact with zero drift. Rejection also drives the compliance dimension: a first rejection
    moves it `COMPLIANT → UNDER_REVIEW`, a second rejection on the same grant moves it
    `UNDER_REVIEW → FINDING_ISSUED`, and a rejection against a grant already `REMEDIATED`
    moves it back `REMEDIATED → UNDER_REVIEW`, making the compliance axis cyclic."

    Design: Corner/state_machines/grant_status_open_while_compliance_reaches_finding_issued
    """
    ctx = setup_tier_one_active_spine()
    provider_id = ctx["provider"]["id"]
    grant = offer_grant(provider_id, ctx["cycle"]["id"], 1_000_000, "2026-12-31")
    grant = accept_grant(provider_id, grant["id"])
    grant_id = grant["id"]
    assert grant["compliance_status"] == "COMPLIANT", (
        f"a new grant starts COMPLIANT, got {grant['compliance_status']}"
    )

    first = submit_expenditure(provider_id, grant_id, "EQUIPMENT", 100_000, "2026-09-01")
    second = submit_expenditure(provider_id, grant_id, "PROF_DEV", 50_000, "2026-09-01")

    once = validate_success(
        api.adjudicate_expenditure(first["id"], {"decision": "REJECT"}, ADMIN)
    )
    assert once["status"] == "REJECTED", (
        f"the first line must be REJECTED, got {once['status']}"
    )
    mid = validate_success(api.get_improvement_grant(grant_id, ADMIN))
    assert mid["compliance_status"] == "UNDER_REVIEW", (
        f"a first rejection moves compliance to UNDER_REVIEW, got {mid['compliance_status']}"
    )

    twice = validate_success(
        api.adjudicate_expenditure(second["id"], {"decision": "REJECT"}, ADMIN)
    )
    assert twice["status"] == "REJECTED", (
        f"the second line must be REJECTED, got {twice['status']}"
    )

    final = validate_success(api.get_improvement_grant(grant_id, ADMIN))
    assert final["status"] == "OPEN", (
        f"the disbursement dimension stays OPEN throughout, got {final['status']}"
    )
    assert final["compliance_status"] == "FINDING_ISSUED", (
        "a second rejection moves compliance UNDER_REVIEW -> FINDING_ISSUED, got "
        f"{final['compliance_status']}"
    )
    assert final["committed_cents"] == 0, (
        f"both rejections unwind their commitments, got {final['committed_cents']}"
    )
    assert final["reimbursed_cents"] == 0, (
        f"nothing was reimbursed, got {final['reimbursed_cents']}"
    )
    assert final["available_cents"] == 1_000_000, (
        f"the full award returns to available_cents with zero drift, got "
        f"{final['available_cents']}"
    )
    assert final["category_spend_cents"]["EQUIPMENT"] == 0, (
        f"the EQUIPMENT tally unwinds, got {final['category_spend_cents']['EQUIPMENT']}"
    )
    assert final["category_spend_cents"]["PROF_DEV"] == 0, (
        f"the PROF_DEV tally unwinds, got {final['category_spend_cents']['PROF_DEV']}"
    )

    rows, meta = validate_paginated(
        api.list_improvement_grants(
            ADMIN, params={"status": "OPEN", "compliance_status": "FINDING_ISSUED"}
        )
    )
    assert meta["total_count"] == 1, (
        f"the two dimensions filter independently, got total_count {meta['total_count']}"
    )
    assert rows[0]["id"] == grant_id, (
        f"the OPEN + FINDING_ISSUED grant must be returned, got {rows[0]['id']}"
    )
