"""Vetting: scheduling sittings, filing panel scores and closing the panel."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    assert_audition, assert_audition_score,
    create_audition_score_payload, decision_payload,
    create_zone, create_performer,
    setup_audition_scheduled, setup_audition_passed,
    file_panel_score, file_panel_scores, finalize_audition,
    read_application, read_audition,
    find_permit_for_application,
    make_officer_headers, make_panelist_headers,
    OFFICER_ALPHA, OFFICER_BETA, OFFICER_GAMMA,
)
from test_helpers.api_client import api_client


# ---------------------------------------------------------------------------
# Filing panel scores
# ---------------------------------------------------------------------------

def test_filed_panel_score_is_immutable_and_carries_no_version(api):
    """PRD §2.4: "Two resources are deliberately immutable once written and
    therefore carry only `id` and `created_at`: an `AuditionScore` (a panelist's
    filed subscores) and a `NoiseReading` (an inspector's metering record).
    Neither of these two has an `updated_at` field and neither has a `version`
    field, and no operation in this specification rewrites an already-filed
    score or reading."
    PRD §3.3: "The acting panelist's `X-User-ID` is stored on the filed row as
    `panelist_user_id`, alongside the `audition_id` of the sitting the row
    belongs to, and one panelist may file at most one score per sitting — a
    second filing by the same identifier is refused with
    `ERR_DUPLICATE_PANEL_SCORE`."
    PRD §3.3: "Filing also increments the sitting's `score_count` by one."

    Design: Corner/entities/corner_audition_score_is_immutable_and_has_no_version
    """
    zone = create_zone(weekend_noise_bonus_db=0, evening_penalty_db=0)
    ctx = setup_audition_scheduled(zone["id"])

    resp = api.create_audition_score(
        ctx["audition"]["id"], create_audition_score_payload(7, 7, 7),
        make_panelist_headers("panelist-1"))
    score = validate_success(resp, 201)
    assert_audition_score(score)
    assert float(score["composite_score"]) == 7.00, \
        f"(7,7,7) composites to 49/7 = 7.00, got {score['composite_score']}"
    assert score["panelist_user_id"] == "panelist-1"
    assert "version" not in score
    assert "updated_at" not in score

    assert read_audition(ctx["audition"]["id"])["score_count"] == 1


def test_same_panelist_filing_twice_is_refused(api):
    """PRD §3.3: "The acting panelist's `X-User-ID` is stored on the filed row as
    `panelist_user_id`, alongside the `audition_id` of the sitting the row
    belongs to, and one panelist may file at most one score per sitting — a
    second filing by the same identifier is refused with
    `ERR_DUPLICATE_PANEL_SCORE`."

    Design: Corner/errors/corner_error_duplicate_panel_score_rejected
    """
    zone = create_zone()
    ctx = setup_audition_scheduled(zone["id"])
    file_panel_score(ctx["audition"]["id"], 7, 7, 7, "panelist-1")

    resp = api.create_audition_score(
        ctx["audition"]["id"], create_audition_score_payload(9, 9, 9),
        make_panelist_headers("panelist-1"))
    assert resp.status_code == 409, f"Expected 409, got {resp.status_code}"
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_PANEL_SCORE)

    assert read_audition(ctx["audition"]["id"])["score_count"] == 1
    _, meta = validate_paginated(api.list_audition_scores(
        ctx["audition"]["id"], make_officer_headers()))
    assert meta["total_count"] == 1


# ---------------------------------------------------------------------------
# Queue A: combinatorial_formula / panel_score_rounds_each_panelist_before_averaging
# ---------------------------------------------------------------------------

def _circus_skill_sitting_with_three_scores():
    zone = create_zone(weekend_noise_bonus_db=0, evening_penalty_db=0)
    ctx = setup_audition_scheduled(
        zone["id"], act_type="CIRCUS_SKILL", amplification_requested=False,
        performer_overrides={"legal_name": "Dari Wend", "stage_name": "Dari",
                             "email": "dari@example.org"})
    scores = file_panel_scores(ctx["audition"]["id"],
                               [(8, 7, 6), (7, 8, 7), (6, 6, 7)])
    ctx["scores"] = scores
    return ctx


def test_each_panelist_composite_is_rounded_to_two_decimals_when_filed(api):
    """PRD §3.3: "The panelist's composite is a weighted average in which the
    technical mark counts 3, the suitability mark counts 2 and the safety mark
    counts 2, over a total weight of 7: multiply `technical_score` by 3,
    `suitability_score` by 2 and `safety_score` by 2, add the three products,
    divide by 7, and round the result half up to two decimal places."
    PRD §3.3: "That rounded value is what is persisted on the row."

    Design: Difficulty/combinatorial_formula/panel_score_rounds_each_panelist_before_averaging
    """
    ctx = _circus_skill_sitting_with_three_scores()
    rows, meta = validate_paginated(api.list_audition_scores(
        ctx["audition"]["id"], make_officer_headers()))
    assert meta["total_count"] == 3
    composites = [float(r["composite_score"]) for r in rows]
    assert composites == [7.14, 7.29, 6.29], (
        "50/7, 51/7 and 44/7 must be persisted rounded half up to two decimals, "
        f"got {composites}")


def test_panel_score_averages_the_already_rounded_composites(api):
    """PRD §3.3: "When the panel is complete, the sitting's `panel_score` is the
    mean of the **already-rounded** per-panelist composites: add up the
    `composite_score` values of the sitting's filed rows, traversed in
    `created_at` ascending order, divide by the sitting's `score_count`, and
    round that mean half up to two decimal places."
    PRD §3.3: "Summing raw unrounded composites and rounding only at the end
    produces a different number and is not what this program computes."
    PRD §3.3: "A score below 7.00 fails: the sitting goes `SCHEDULED → FAILED`
    and the application goes `AUDITION_SCHEDULED → AUDITION_FAILED`."

    Design: Difficulty/combinatorial_formula/panel_score_rounds_each_panelist_before_averaging
    """
    ctx = _circus_skill_sitting_with_three_scores()
    audition = finalize_audition(ctx["audition"]["id"], OFFICER_ALPHA)
    assert_audition(audition)
    assert audition["score_count"] == 3
    assert float(audition["panel_score"]) == 6.91, (
        "(7.14 + 7.29 + 6.29) / 3 rounds half up to 6.91; averaging the raw "
        f"composites would give 6.90, got {audition['panel_score']}")
    assert audition["status"] == "FAILED"
    assert read_application(ctx["application"]["id"])["status"] == "AUDITION_FAILED"


# ---------------------------------------------------------------------------
# Panel completeness and the pass threshold
# ---------------------------------------------------------------------------

def test_finalize_with_two_scores_is_refused_as_panel_incomplete(api):
    """PRD §3.3: "Closing the sitting is the officer's job, and it is refused
    with `ERR_AUDITION_PANEL_INCOMPLETE` unless at least three panel scores have
    been filed."

    Design: Corner/errors/corner_error_audition_panel_incomplete_blocks_finalize
    """
    zone = create_zone()
    ctx = setup_audition_scheduled(zone["id"])
    file_panel_scores(ctx["audition"]["id"], [(7, 7, 7), (8, 8, 8)])

    resp = api.finalize_audition(ctx["audition"]["id"], make_officer_headers())
    assert resp.status_code == 409, f"Expected 409, got {resp.status_code}"
    validate_error(resp, ApiErrorId.ERR_AUDITION_PANEL_INCOMPLETE)

    audition = read_audition(ctx["audition"]["id"])
    assert audition["status"] == "SCHEDULED"
    assert audition["panel_score"] is None
    assert read_application(ctx["application"]["id"])["status"] == "AUDITION_SCHEDULED"


def test_panel_score_of_exactly_seven_passes_the_sitting(api):
    """PRD §3.3: "A `panel_score` of 7.00 or more passes: the sitting goes
    `SCHEDULED → PASSED` and is thereafter `PASSED`, and the parent application
    goes `AUDITION_SCHEDULED → AUDITION_PASSED`."
    PRD §3.3: "Exactly 7.00 is a pass."

    Design: Corner/calculations/corner_audition_pass_threshold_admits_exactly_seven_point_zero
    """
    zone = create_zone()
    ctx = setup_audition_scheduled(zone["id"])
    file_panel_scores(ctx["audition"]["id"], [(7, 7, 7), (7, 7, 7), (7, 7, 7)])

    audition = finalize_audition(ctx["audition"]["id"], OFFICER_ALPHA)
    assert float(audition["panel_score"]) == 7.00, \
        f"three 7.00 composites mean exactly 7.00, got {audition['panel_score']}"
    assert audition["status"] == "PASSED", "exactly 7.00 is a pass"
    assert read_application(ctx["application"]["id"])["status"] == "AUDITION_PASSED"


def test_panel_average_counts_every_filed_score_not_just_the_minimum_three(api):
    """PRD §3.3: "When the panel is complete, the sitting's `panel_score` is the
    mean of the **already-rounded** per-panelist composites: add up the
    `composite_score` values of the sitting's filed rows, traversed in
    `created_at` ascending order, divide by the sitting's `score_count`, and
    round that mean half up to two decimal places."
    PRD §3.3: "Every filed row counts exactly once and none is filtered out."

    Design: Corner/calculations/corner_panel_score_input_set_counts_every_filed_score
    """
    zone = create_zone()
    ctx = setup_audition_scheduled(zone["id"])
    file_panel_scores(ctx["audition"]["id"],
                      [(7, 7, 7), (8, 8, 8), (6, 6, 6), (9, 9, 9)])

    rows, meta = validate_paginated(api.list_audition_scores(
        ctx["audition"]["id"], make_officer_headers()))
    assert meta["total_count"] == 4
    assert [float(r["composite_score"]) for r in rows] == [7.00, 8.00, 6.00, 9.00]

    audition = finalize_audition(ctx["audition"]["id"], OFFICER_ALPHA)
    assert audition["score_count"] == 4
    assert float(audition["panel_score"]) == 7.50, (
        "the mean is taken over score_count 4, not over the three-panelist "
        f"minimum, got {audition['panel_score']}")
    assert audition["status"] == "PASSED"


def test_second_finalize_on_a_failed_sitting_is_an_invalid_state(api):
    """PRD §3.3: "A score below 7.00 fails: the sitting goes `SCHEDULED →
    FAILED` and the application goes `AUDITION_SCHEDULED → AUDITION_FAILED`."
    PRD §3.3: "Both branches write the computed `panel_score` onto the sitting,
    record the closing officer as `finalized_by_user_id`, stamp `finalized_at`
    with the clock, and increment the sitting's `version` and the application's
    `version`."
    PRD §2.6: "The target resource is in a state from which the requested
    transition is declared, otherwise `ERR_INVALID_STATE`. This applies to every
    action endpoint: submit, review, revise, decide, finalize, pay, renew,
    revoke, reinstate, enter a draw, execute a draw, cancel a booking, triage,
    adjudicate and activate a closure."

    Design: Corner/state_machines/corner_finalize_on_terminal_audition_rejected
    """
    ctx = _circus_skill_sitting_with_three_scores()
    finalize_audition(ctx["audition"]["id"], OFFICER_ALPHA)

    resp = api.finalize_audition(ctx["audition"]["id"],
                                 make_officer_headers(OFFICER_GAMMA))
    assert resp.status_code == 409, f"Expected 409, got {resp.status_code}"
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    audition = read_audition(ctx["audition"]["id"])
    assert audition["status"] == "FAILED"
    assert float(audition["panel_score"]) == 6.91, \
        "the refused finalize must not recompute panel_score"
    assert audition["finalized_by_user_id"] == OFFICER_ALPHA


def test_rejecting_a_mid_vetting_application_cancels_the_scheduled_sitting(api):
    """PRD §3.4: "Rejecting from `AUDITION_SCHEDULED` additionally cancels the
    still-scheduled sitting, leaving its `panel_score` null; the other three
    rejection paths touch no audition, except that a rejection from
    `UNDER_REVIEW` also cancels any sitting on that application still in
    `SCHEDULED`."
    PRD §3.4: "Every rejection records `decided_by_user_id` and stamps
    `decided_at`."
    PRD §3.3: "When the parent application leaves the vetting branch without a
    verdict — because the applicant's revision was accepted, or because the
    officer rejected the application outright while the sitting was still
    `SCHEDULED` — the sitting moves `SCHEDULED → CANCELLED`, ending in the
    terminal status `CANCELLED`, its `panel_score` is left null, and its
    `version` is incremented."

    Design: Corner/state_machines/corner_scheduled_audition_cancelled_when_application_rejected
    """
    zone = create_zone()
    ctx = setup_audition_scheduled(zone["id"])

    resp = api.decide_application(
        ctx["application"]["id"],
        decision_payload("REJECTED", "Applicant withdrew before the sitting"),
        make_officer_headers(OFFICER_BETA))
    application = validate_success(resp, 200)
    assert application["status"] == "REJECTED"
    assert application["decided_by_user_id"] == OFFICER_BETA

    audition = read_audition(ctx["audition"]["id"])
    assert audition["status"] == "CANCELLED"
    assert audition["panel_score"] is None

    _, meta = validate_paginated(api.list_permits(
        make_officer_headers(),
        params={"application_id": ctx["application"]["id"]}))
    assert meta["total_count"] == 0, "a rejection mints no permit"


def test_panelist_may_not_finalize_the_sitting(api):
    """PRD §2.1: "If both headers are well formed but the named role is not one
    of the roles authorised for the endpoint being called (the authorised set
    for each endpoint is listed in section 4), the request is rejected with
    `ERR_FORBIDDEN_ROLE` and HTTP 403."
    PRD §3.3: "Closing the sitting is the officer's job, and it is refused with
    `ERR_AUDITION_PANEL_INCOMPLETE` unless at least three panel scores have been
    filed."

    Design: Corner/roles/corner_panelist_cannot_finalize_an_audition
    """
    zone = create_zone()
    ctx = setup_audition_scheduled(zone["id"])
    file_panel_scores(ctx["audition"]["id"], [(9, 8, 8), (8, 8, 7), (7, 8, 8)])

    resp = api.finalize_audition(ctx["audition"]["id"],
                                 make_panelist_headers("panelist-1"))
    assert resp.status_code == 403, f"Expected 403, got {resp.status_code}"
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    audition = read_audition(ctx["audition"]["id"])
    assert audition["status"] == "SCHEDULED"
    assert audition["panel_score"] is None


# ---------------------------------------------------------------------------
# Queue A: cross_entity_state_dependency /
#          application_approval_depends_on_audition_row_state
# ---------------------------------------------------------------------------

def test_approval_is_refused_while_the_linked_sitting_is_still_scheduled(api):
    """PRD §3.4: "Attempting to approve an application whose `requires_audition`
    is true from `AUDITION_REQUIRED`, `AUDITION_SCHEDULED` or `AUDITION_FAILED`
    is refused with `ERR_AUDITION_REQUIRED` rather than a generic state error."

    Design: Difficulty/cross_entity_state_dependency/application_approval_depends_on_audition_row_state
    """
    zone = create_zone()
    ctx = setup_audition_scheduled(zone["id"])
    file_panel_scores(ctx["audition"]["id"], [(9, 8, 8), (8, 8, 7), (7, 8, 8)])

    resp = api.decide_application(
        ctx["application"]["id"],
        decision_payload("APPROVED", "Premature approval attempt"),
        make_officer_headers(OFFICER_BETA))
    assert resp.status_code == 409, f"Expected 409, got {resp.status_code}"
    validate_error(resp, ApiErrorId.ERR_AUDITION_REQUIRED)

    assert read_application(ctx["application"]["id"])["status"] == "AUDITION_SCHEDULED"
    assert read_audition(ctx["audition"]["id"])["status"] == "SCHEDULED"


def test_approval_succeeds_the_moment_the_sitting_alone_moves_to_passed(api):
    """PRD §3.4: "Approval is admissible from exactly two places, and in both the
    application ends in the terminal status `APPROVED`: an application that never
    needed vetting goes `UNDER_REVIEW → APPROVED`, while an application that did
    need vetting goes `AUDITION_PASSED → APPROVED` and from nowhere else."
    PRD §3.4: "First, the approval **mints a permit** for the applicant: its
    `application_id` points back at the approved application, its `performer_id`
    at the applicant, its `season_year` is copied from the application's
    `season_year`, its `amplification_endorsed` flag is copied from the
    application's `amplification_requested`, its `lifecycle_status` starts at
    `PENDING_FEE` and its `compliance_status` at `CLEAR`."

    Design: Difficulty/cross_entity_state_dependency/application_approval_depends_on_audition_row_state
    """
    zone = create_zone()
    ctx = setup_audition_scheduled(zone["id"])
    file_panel_scores(ctx["audition"]["id"], [(9, 8, 8), (8, 8, 7), (7, 8, 8)])

    audition = finalize_audition(ctx["audition"]["id"], OFFICER_ALPHA)
    assert audition["status"] == "PASSED"
    assert float(audition["panel_score"]) == 7.90
    assert read_application(ctx["application"]["id"])["status"] == "AUDITION_PASSED"

    resp = api.decide_application(
        ctx["application"]["id"],
        decision_payload("APPROVED", "Panel passed"),
        make_officer_headers(OFFICER_BETA))
    application = validate_success(resp, 200)
    assert application["status"] == "APPROVED"

    permit = find_permit_for_application(ctx["application"]["id"])
    assert permit["lifecycle_status"] == "PENDING_FEE"
    assert permit["compliance_status"] == "CLEAR"
    assert permit["amplification_endorsed"] is True


def test_audition_finalizer_may_not_decide_the_same_application(api):
    """PRD §2.10: "An officer whose id was recorded as the
    `finalized_by_user_id` of an application's passed audition may not issue
    that application's decision; an officer whose id was recorded as a
    complaint's `triaged_by_user_id` may not adjudicate that complaint."
    PRD §3.4: "On the vetted branch the deciding officer must not be the officer
    recorded as `finalized_by_user_id` on that application's passed sitting; if
    they are, the decision is refused with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/roles/corner_audition_finalizer_cannot_decide_the_same_application
    """
    zone = create_zone()
    ctx = setup_audition_passed(zone["id"], finalize_officer=OFFICER_ALPHA)
    assert ctx["audition"]["finalized_by_user_id"] == OFFICER_ALPHA
    assert float(ctx["audition"]["panel_score"]) == 7.90

    same = api.decide_application(
        ctx["application"]["id"],
        decision_payload("APPROVED", "Self approval"),
        make_officer_headers(OFFICER_ALPHA))
    assert same.status_code == 403, f"Expected 403, got {same.status_code}"
    validate_error(same, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    assert read_application(ctx["application"]["id"])["status"] == "AUDITION_PASSED"

    other = api.decide_application(
        ctx["application"]["id"],
        decision_payload("APPROVED", "Independent approval"),
        make_officer_headers(OFFICER_BETA))
    application = validate_success(other, 200)
    assert application["status"] == "APPROVED"
    assert application["decided_by_user_id"] == OFFICER_BETA

    permit = find_permit_for_application(ctx["application"]["id"])
    assert permit["lifecycle_status"] == "PENDING_FEE"
