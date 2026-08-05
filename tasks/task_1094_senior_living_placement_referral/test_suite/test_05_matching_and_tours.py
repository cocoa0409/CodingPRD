"""Match fit scoring, match lifecycle, tour scheduling constraints and the
shortlist/tour/hold/close cycles.
"""
from test_helpers import (
    TEST_USERS, ApiErrorId,
    validate_success, validate_error, validate_paginated,
    get_success_data,
    create_advisor, create_community, create_inventory, create_family, create_inquiry,
    assign_advisor, create_approved_assessment, set_clock,
    make_advisor_headers,
    create_match_payload, create_tour_payload,
    build_scenario,
)

ADMIN = TEST_USERS["platform_admin_headers"]


# ---------------------------------------------------------------------------
# Local composite builders.
# ---------------------------------------------------------------------------

def _shortlisted(api, **kw):
    sc = build_scenario(api, "matched", **kw)
    api.shortlist_match(sc["match"]["id"], sc["advisor_headers"])
    sc["match"] = validate_success(api.get_match(sc["match"]["id"], ADMIN))
    return sc


def _toured(api, **kw):
    sc = _shortlisted(api, **kw)
    tour = get_success_data(api.create_tour(create_tour_payload(sc["match"]["id"]), sc["advisor_headers"]))
    api.complete_tour(tour["id"], {"outcome_rating": 3}, sc["advisor_headers"])
    sc["tour"] = tour
    sc["match"] = validate_success(api.get_match(sc["match"]["id"], ADMIN))
    return sc


def _two_matches_one_inquiry_two_communities(api, c1_cap=5, c2_cap=5):
    """Inquiry Q1 with APPROVED assessment and two SHORTLISTED matches at two
    different ACTIVE communities."""
    set_clock(api, "2026-06-01T00:00:00Z")
    ann = create_advisor(api, full_name="Ann Reyes")
    c1 = create_community(api, name="Cedar Grove", tour_slot_capacity=c1_cap)
    c2 = create_community(api, name="Willow Bend", contract_tier="STANDARD",
                          referral_fee_pct=0.80, tour_slot_capacity=c2_cap, quality_rating=3.5)
    create_inventory(api, c1["id"], monthly_rate_cents=500000)
    create_inventory(api, c2["id"], monthly_rate_cents=480000)
    family = create_family(api)
    inquiry = create_inquiry(api, family["id"])
    assign_advisor(api, inquiry["id"], ann["id"])
    create_approved_assessment(api, inquiry["id"], ann["id"])
    ahdr = make_advisor_headers(ann["id"])
    m1 = get_success_data(api.create_match(create_match_payload(inquiry["id"], c1["id"]), ahdr))
    m2 = get_success_data(api.create_match(create_match_payload(inquiry["id"], c2["id"]), ahdr))
    api.shortlist_match(m1["id"], ahdr)
    api.shortlist_match(m2["id"], ahdr)
    return {"ann": ann, "ahdr": ahdr, "c1": c1, "c2": c2, "inquiry": inquiry,
            "m1": m1, "m2": m2}


def _two_advisors_two_matches_one_community(api, cap):
    """One community (tour_slot_capacity cap). Ann owns Q1/M1, Ben owns Q2/M2, both
    SHORTLISTED at that community. Ben's calendar is empty."""
    set_clock(api, "2026-06-01T00:00:00Z")
    ann = create_advisor(api, full_name="Ann Reyes")
    ben = create_advisor(api, full_name="Ben Cho", is_va_certified=True)
    c1 = create_community(api, name="Cedar Grove", tour_slot_capacity=cap)
    create_inventory(api, c1["id"], monthly_rate_cents=500000)
    fam1 = create_family(api)
    fam2 = create_family(api)
    q1 = create_inquiry(api, fam1["id"])
    q2 = create_inquiry(api, fam2["id"])
    assign_advisor(api, q1["id"], ann["id"])
    assign_advisor(api, q2["id"], ben["id"])
    create_approved_assessment(api, q1["id"], ann["id"])
    create_approved_assessment(api, q2["id"], ben["id"])
    ahdr, bhdr = make_advisor_headers(ann["id"]), make_advisor_headers(ben["id"])
    m1 = get_success_data(api.create_match(create_match_payload(q1["id"], c1["id"]), ahdr))
    m2 = get_success_data(api.create_match(create_match_payload(q2["id"], c1["id"]), bhdr))
    api.shortlist_match(m1["id"], ahdr)
    api.shortlist_match(m2["id"], bhdr)
    return {"ann": ann, "ben": ben, "ahdr": ahdr, "bhdr": bhdr, "c1": c1,
            "q1": q1, "q2": q2, "m1": m1, "m2": m2}


def _two_matches_same_advisor_one_community(api, cap):
    """One advisor owns two inquiries, each SHORTLISTED at the same community."""
    set_clock(api, "2026-06-01T00:00:00Z")
    ann = create_advisor(api, full_name="Ann Reyes")
    c1 = create_community(api, name="Cedar Grove", tour_slot_capacity=cap)
    create_inventory(api, c1["id"], monthly_rate_cents=500000)
    fam = create_family(api)
    q1 = create_inquiry(api, fam["id"])
    q2 = create_inquiry(api, fam["id"], origin="PHONE", target_move_in_date="2026-06-25")
    assign_advisor(api, q1["id"], ann["id"])
    assign_advisor(api, q2["id"], ann["id"])
    create_approved_assessment(api, q1["id"], ann["id"])
    create_approved_assessment(api, q2["id"], ann["id"])
    ahdr = make_advisor_headers(ann["id"])
    m1 = get_success_data(api.create_match(create_match_payload(q1["id"], c1["id"]), ahdr))
    m2 = get_success_data(api.create_match(create_match_payload(q2["id"], c1["id"]), ahdr))
    api.shortlist_match(m1["id"], ahdr)
    api.shortlist_match(m2["id"], ahdr)
    return {"ann": ann, "ahdr": ahdr, "c1": c1, "m1": m1, "m2": m2}


def _submitted_not_approved(api):
    """Inquiry with a SUBMITTED (not APPROVED) assessment."""
    set_clock(api, "2026-06-01T00:00:00Z")
    ann = create_advisor(api, full_name="Ann Reyes")
    community = create_community(api)
    create_inventory(api, community["id"], monthly_rate_cents=500000)
    family = create_family(api)
    inquiry = create_inquiry(api, family["id"])
    assign_advisor(api, inquiry["id"], ann["id"])
    ahdr = make_advisor_headers(ann["id"])
    s = get_success_data(api.create_assessment(
        {"inquiry_id": inquiry["id"], "adl_score": 6, "cognitive_score": 4,
         "mobility_score": 5, "budget_monthly_cents": 520000,
         "gross_monthly_income_cents": 320000, "va_eligible": True,
         "marital_status": "MARRIED"}, ahdr))
    api.submit_assessment(s["id"], ahdr)
    return {"ann": ann, "ahdr": ahdr, "community": community, "inquiry": inquiry, "assessment": s}


# ---------------------------------------------------------------------------
# Difficulty: match_fit_score four-input formula (>=2 tests).
# ---------------------------------------------------------------------------

def test_match_fit_score_four_input_value(api):
    """PRD §3.6: "The four factors are weighted 0.40 on care fit, 0.35 on budget
    fit, 0.15 on quality fit and 0.10 on availability fit; the weighted terms are
    summed at full precision and the total is rounded half up once to 2 decimals."

    Design: Difficulty/combinatorial_formula/match_fit_score_four_input_nested_min_max_with_conditional_branches
    """
    sc = build_scenario(api, "matched")
    m = sc["match"]
    assert m["quoted_monthly_rate_cents"] == 500000
    assert m["fit_score"] == 94.47


def test_match_fit_score_snapshot_and_inquiry_progression(api):
    """PRD §3.6: "`quoted_monthly_rate_cents` is copied from the resolved unit
    pool's `monthly_rate_cents` at creation and never re-snapshotted".
    PRD §3.6: "On the first match created for an inquiry, the inquiry moves
    `ASSESSED → MATCHING`, its `match_count` is incremented by 1 and its `version`
    bumped".

    Design: Difficulty/combinatorial_formula/match_fit_score_four_input_nested_min_max_with_conditional_branches
    """
    sc = build_scenario(api, "matched")
    m = sc["match"]
    assert m["status"] == "PROPOSED"
    s = validate_success(api.get_assessment(sc["assessment"]["id"], ADMIN))
    assert s["recommended_care_level"] == "ASSISTED_LIVING"
    assert s["affordability_ceiling_cents"] == 572000
    inq = validate_success(api.get_inquiry(sc["inquiry"]["id"], ADMIN))
    assert inq["status"] == "MATCHING"
    assert inq["match_count"] == 1


def test_match_fit_score_at_exact_budget_comfort_ratio(api):
    """PRD §3.6: "**Budget fit** works from the ratio of rate to ceiling: if that
    ratio exceeds 1.0 the budget fit is 0.00; if it is at most 0.85 the budget fit
    is 100.00".

    Design: Corner/calculations/match_fit_score_at_the_exact_budget_comfort_ratio_scores_full_budget_fit
    """
    sc = build_scenario(api, "matched", inventory_overrides={"monthly_rate_cents": 486200})
    m = sc["match"]
    assert m["quoted_monthly_rate_cents"] == 486200
    assert m["fit_score"] == 97.00


# ---------------------------------------------------------------------------
# Difficulty: community suspended blocks tour (>=2 tests).
# ---------------------------------------------------------------------------

def test_tour_blocked_while_community_suspended(api):
    """PRD §3.7: "The match must be `SHORTLISTED` (else `ERR_MATCH_INVALID_STATE`)
    and its community `ACTIVE` (else `ERR_COMMUNITY_NOT_ACTIVE`)."

    Design: Difficulty/cross_entity_state_dependency/tour_booking_blocked_while_community_is_suspended
    """
    sc = _shortlisted(api)
    validate_success(api.update_community(sc["community"]["id"], {"status": "SUSPENDED"}, ADMIN))
    resp = api.create_tour(create_tour_payload(sc["match"]["id"]), sc["advisor_headers"])
    validate_error(resp, ApiErrorId.ERR_COMMUNITY_NOT_ACTIVE)
    community = validate_success(api.get_community(sc["community"]["id"], ADMIN))
    assert community["status"] == "SUSPENDED"


def test_tour_blocked_community_suspended_leaves_match_and_inquiry(api):
    """PRD §3.7: "The match must be `SHORTLISTED` (else `ERR_MATCH_INVALID_STATE`)
    and its community `ACTIVE` (else `ERR_COMMUNITY_NOT_ACTIVE`)."
    PRD §3.1: "moving it to `SUSPENDED` or `TERMINATED` blocks new matches, tours
    and placements at that community while leaving existing rows untouched."

    Design: Difficulty/cross_entity_state_dependency/tour_booking_blocked_while_community_is_suspended
    """
    sc = _shortlisted(api)
    validate_success(api.update_community(sc["community"]["id"], {"status": "SUSPENDED"}, ADMIN))
    resp = api.create_tour(create_tour_payload(sc["match"]["id"]), sc["advisor_headers"])
    validate_error(resp, ApiErrorId.ERR_COMMUNITY_NOT_ACTIVE)
    m = validate_success(api.get_match(sc["match"]["id"], ADMIN))
    assert m["status"] == "SHORTLISTED" and m["tour_round"] == 0
    inq = validate_success(api.get_inquiry(sc["inquiry"]["id"], ADMIN))
    assert inq["status"] == "MATCHING"
    rows, _ = validate_paginated(api.list_tours(ADMIN, params={"match_id": sc["match"]["id"]}))
    assert rows == []


# ---------------------------------------------------------------------------
# Difficulty: match creation blocked while assessment only SUBMITTED (>=2 tests).
# ---------------------------------------------------------------------------

def test_match_creation_blocked_while_assessment_submitted(api):
    """PRD §3.6: "The inquiry must have an `APPROVED` assessment (else
    `ERR_ASSESSMENT_NOT_APPROVED`), and once approved its status must be one of
    `ASSESSED`, `MATCHING` or `TOURING`".

    Design: Difficulty/cross_entity_state_dependency/match_creation_blocked_while_needs_assessment_is_only_submitted
    """
    ctx = _submitted_not_approved(api)
    resp = api.create_match(
        create_match_payload(ctx["inquiry"]["id"], ctx["community"]["id"]), ctx["ahdr"])
    validate_error(resp, ApiErrorId.ERR_ASSESSMENT_NOT_APPROVED)
    s = validate_success(api.get_assessment(ctx["assessment"]["id"], ADMIN))
    assert s["status"] == "SUBMITTED"
    assert s["affordability_ceiling_cents"] == 0


def test_match_blocked_submitted_leaves_inquiry_assigned(api):
    """PRD §3.6: "The inquiry must have an `APPROVED` assessment (else
    `ERR_ASSESSMENT_NOT_APPROVED`)".

    Design: Difficulty/cross_entity_state_dependency/match_creation_blocked_while_needs_assessment_is_only_submitted
    """
    ctx = _submitted_not_approved(api)
    resp = api.create_match(
        create_match_payload(ctx["inquiry"]["id"], ctx["community"]["id"]), ctx["ahdr"])
    validate_error(resp, ApiErrorId.ERR_ASSESSMENT_NOT_APPROVED)
    inq = validate_success(api.get_inquiry(ctx["inquiry"]["id"], ADMIN))
    assert inq["status"] == "ASSIGNED" and inq["match_count"] == 0
    rows, _ = validate_paginated(api.list_matches(ADMIN, params={"inquiry_id": ctx["inquiry"]["id"]}))
    assert rows == []


# ---------------------------------------------------------------------------
# Difficulty: advisor calendar buffered strict overlap (>=2 tests).
# ---------------------------------------------------------------------------

def test_advisor_calendar_buffered_overlap_rejects_tour(api):
    """PRD §3.7: "The **advisor calendar** check looks at every scheduled tour
    already held by the inquiry's assigned advisor and rejects the candidate when
    the candidate start is earlier than the existing end plus a buffer and the
    existing start is earlier than the candidate end plus that buffer; the buffer is
    45 minutes when either tour is `IN_PERSON` and 0 minutes when both are
    `VIRTUAL`."

    Design: Difficulty/resource_temporal_overlap/advisor_calendar_buffered_strict_overlap_across_two_communities
    """
    ctx = _two_matches_one_inquiry_two_communities(api, c1_cap=5, c2_cap=5)
    get_success_data(api.create_tour(create_tour_payload(
        ctx["m1"]["id"], scheduled_start="2026-06-05T15:00:00Z",
        scheduled_end="2026-06-05T16:00:00Z", mode="IN_PERSON"), ctx["ahdr"]))
    resp = api.create_tour(create_tour_payload(
        ctx["m2"]["id"], scheduled_start="2026-06-05T16:30:00Z",
        scheduled_end="2026-06-05T17:30:00Z", mode="IN_PERSON"), ctx["ahdr"])
    err = validate_error(resp, ApiErrorId.ERR_ADVISOR_SCHEDULE_CONFLICT)
    assert err["error_id"] != ApiErrorId.ERR_TOUR_SLOT_CONFLICT.value


def test_advisor_calendar_conflict_leaves_second_match_shortlisted(api):
    """PRD §3.7: "the buffer is 45 minutes when either tour is `IN_PERSON` and 0
    minutes when both are `VIRTUAL`. The comparison is strict, so a gap of exactly
    the buffer is accepted; a violation is `ERR_ADVISOR_SCHEDULE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/advisor_calendar_buffered_strict_overlap_across_two_communities
    """
    ctx = _two_matches_one_inquiry_two_communities(api, c1_cap=5, c2_cap=5)
    t1 = get_success_data(api.create_tour(create_tour_payload(
        ctx["m1"]["id"], scheduled_start="2026-06-05T15:00:00Z",
        scheduled_end="2026-06-05T16:00:00Z", mode="IN_PERSON"), ctx["ahdr"]))
    resp = api.create_tour(create_tour_payload(
        ctx["m2"]["id"], scheduled_start="2026-06-05T16:30:00Z",
        scheduled_end="2026-06-05T17:30:00Z", mode="IN_PERSON"), ctx["ahdr"])
    validate_error(resp, ApiErrorId.ERR_ADVISOR_SCHEDULE_CONFLICT)
    m2 = validate_success(api.get_match(ctx["m2"]["id"], ADMIN))
    assert m2["status"] == "SHORTLISTED"
    rows, _ = validate_paginated(api.list_tours(ADMIN, params={"advisor_id": ctx["ann"]["id"]}))
    assert len(rows) == 1 and rows[0]["id"] == t1["id"]


# ---------------------------------------------------------------------------
# Difficulty: community tour-slot closed-interval capacity on touching (>=2 tests).
# ---------------------------------------------------------------------------

def test_community_tour_slot_touching_endpoints_conflict(api):
    """PRD §3.7: "counts the community's scheduled tours whose closed interval
    `[scheduled_start, scheduled_end]` intersects the candidate's closed interval —
    where two closed intervals intersect when the existing start is at or before the
    candidate end and the candidate start is at or before the existing end, so tours
    that merely touch at an endpoint do count as intersecting — and that count must
    be strictly less than the community's `tour_slot_capacity`, else
    `ERR_TOUR_SLOT_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/community_tour_slot_closed_interval_capacity_on_touching_endpoints
    """
    ctx = _two_advisors_two_matches_one_community(api, cap=1)
    get_success_data(api.create_tour(create_tour_payload(
        ctx["m1"]["id"], scheduled_start="2026-06-05T15:00:00Z",
        scheduled_end="2026-06-05T16:00:00Z", mode="IN_PERSON"), ctx["ahdr"]))
    resp = api.create_tour(create_tour_payload(
        ctx["m2"]["id"], scheduled_start="2026-06-05T16:00:00Z",
        scheduled_end="2026-06-05T17:00:00Z", mode="IN_PERSON"), ctx["bhdr"])
    err = validate_error(resp, ApiErrorId.ERR_TOUR_SLOT_CONFLICT)
    assert err["error_id"] != ApiErrorId.ERR_ADVISOR_SCHEDULE_CONFLICT.value


def test_community_slot_conflict_with_disjoint_advisor(api):
    """PRD §3.7: "so tours that merely touch at an endpoint do count as intersecting
    — and that count must be strictly less than the community's
    `tour_slot_capacity`, else `ERR_TOUR_SLOT_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/community_tour_slot_closed_interval_capacity_on_touching_endpoints
    """
    ctx = _two_advisors_two_matches_one_community(api, cap=1)
    t1 = get_success_data(api.create_tour(create_tour_payload(
        ctx["m1"]["id"], scheduled_start="2026-06-05T15:00:00Z",
        scheduled_end="2026-06-05T16:00:00Z", mode="IN_PERSON"), ctx["ahdr"]))
    resp = api.create_tour(create_tour_payload(
        ctx["m2"]["id"], scheduled_start="2026-06-05T16:00:00Z",
        scheduled_end="2026-06-05T17:00:00Z", mode="IN_PERSON"), ctx["bhdr"])
    validate_error(resp, ApiErrorId.ERR_TOUR_SLOT_CONFLICT)
    m2 = validate_success(api.get_match(ctx["m2"]["id"], ADMIN))
    assert m2["status"] == "SHORTLISTED"
    rows, _ = validate_paginated(api.list_tours(ADMIN, params={"community_id": ctx["c1"]["id"]}))
    assert len(rows) == 1 and rows[0]["id"] == t1["id"]


# ---------------------------------------------------------------------------
# Difficulty (Rule 5): community tour-slot beats advisor calendar (>=2 tests).
# ---------------------------------------------------------------------------

def test_tour_slot_conflict_wins_over_advisor_conflict(api):
    """PRD §3.7: "Then two overlap checks. The **community tour-slot** check counts
    the community's scheduled tours whose closed interval `[scheduled_start,
    scheduled_end]` intersects the candidate's closed interval ... else
    `ERR_TOUR_SLOT_CONFLICT`. The **advisor calendar** check looks at every
    scheduled tour already held by the inquiry's assigned advisor ... a violation is
    `ERR_ADVISOR_SCHEDULE_CONFLICT`."

    Design: Difficulty/priority_pair_validation_conflict/tour_community_slot_constraint_wins_over_advisor_temporal_conflict
    """
    ctx = _two_matches_same_advisor_one_community(api, cap=1)
    get_success_data(api.create_tour(create_tour_payload(
        ctx["m1"]["id"], scheduled_start="2026-06-05T15:00:00Z",
        scheduled_end="2026-06-05T16:00:00Z", mode="IN_PERSON"), ctx["ahdr"]))
    resp = api.create_tour(create_tour_payload(
        ctx["m2"]["id"], scheduled_start="2026-06-05T15:30:00Z",
        scheduled_end="2026-06-05T16:30:00Z", mode="IN_PERSON"), ctx["ahdr"])
    err = validate_error(resp, ApiErrorId.ERR_TOUR_SLOT_CONFLICT)
    assert err["error_id"] != ApiErrorId.ERR_ADVISOR_SCHEDULE_CONFLICT.value


def test_tour_slot_conflict_wins_leaves_match_shortlisted(api):
    """PRD §3.7: "The **community tour-slot** check ... else
    `ERR_TOUR_SLOT_CONFLICT`. The **advisor calendar** check ... a violation is
    `ERR_ADVISOR_SCHEDULE_CONFLICT`."

    Design: Difficulty/priority_pair_validation_conflict/tour_community_slot_constraint_wins_over_advisor_temporal_conflict
    """
    ctx = _two_matches_same_advisor_one_community(api, cap=1)
    get_success_data(api.create_tour(create_tour_payload(
        ctx["m1"]["id"], scheduled_start="2026-06-05T15:00:00Z",
        scheduled_end="2026-06-05T16:00:00Z", mode="IN_PERSON"), ctx["ahdr"]))
    resp = api.create_tour(create_tour_payload(
        ctx["m2"]["id"], scheduled_start="2026-06-05T15:30:00Z",
        scheduled_end="2026-06-05T16:30:00Z", mode="IN_PERSON"), ctx["ahdr"])
    validate_error(resp, ApiErrorId.ERR_TOUR_SLOT_CONFLICT)
    m2 = validate_success(api.get_match(ctx["m2"]["id"], ADMIN))
    assert m2["status"] == "SHORTLISTED"
    rows, _ = validate_paginated(api.list_tours(ADMIN, params={"match_id": ctx["m2"]["id"]}))
    assert rows == []


# ---------------------------------------------------------------------------
# Corner: match validations and lifecycle.
# ---------------------------------------------------------------------------

def test_match_without_open_inventory_returns_care_level_unavailable(api):
    """PRD §3.6: "A unit pool with `status` `OPEN` must exist for the community and
    the proposed care level, else `ERR_CARE_LEVEL_UNAVAILABLE`."

    Design: Corner/validations/match_for_care_level_without_open_inventory_returns_care_level_unavailable
    """
    sc = build_scenario(api, "approved")
    resp = api.create_match(
        create_match_payload(sc["inquiry"]["id"], sc["community"]["id"], care_level="MEMORY_CARE"),
        sc["advisor_headers"])
    validate_error(resp, ApiErrorId.ERR_CARE_LEVEL_UNAVAILABLE)
    inq = validate_success(api.get_inquiry(sc["inquiry"]["id"], ADMIN))
    assert inq["status"] == "ASSESSED" and inq["match_count"] == 0


def test_match_rejected_when_rate_exceeds_affordability_ceiling(api):
    """PRD §3.6: "Finally the fiscal gate: the resolved pool's `monthly_rate_cents`
    must be at most the inquiry's assessment `affordability_ceiling_cents` —
    equality is accepted — else `ERR_BUDGET_EXCEEDED`."

    Design: Corner/validations/match_rejected_when_inventory_rate_exceeds_affordability_ceiling
    """
    sc = build_scenario(api, "approved", inventory_overrides={"monthly_rate_cents": 572001})
    resp = api.create_match(
        create_match_payload(sc["inquiry"]["id"], sc["community"]["id"]), sc["advisor_headers"])
    validate_error(resp, ApiErrorId.ERR_BUDGET_EXCEEDED)
    s = validate_success(api.get_assessment(sc["assessment"]["id"], ADMIN))
    assert s["affordability_ceiling_cents"] == 572000
    rows, _ = validate_paginated(api.list_matches(ADMIN, params={"inquiry_id": sc["inquiry"]["id"]}))
    assert rows == []


def test_second_match_same_inquiry_and_community_returns_duplicate(api):
    """PRD §3.6: "if a match for that `(inquiry_id, community_id)` exists whose
    status is anything other than `DECLINED` or `WITHDRAWN`, the request is rejected
    with `ERR_DUPLICATE_MATCH`."

    Design: Corner/validations/second_match_for_same_inquiry_and_community_returns_duplicate_match
    """
    sc = build_scenario(api, "matched")
    resp = api.create_match(
        create_match_payload(sc["inquiry"]["id"], sc["community"]["id"]), sc["advisor_headers"])
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_MATCH)
    inq = validate_success(api.get_inquiry(sc["inquiry"]["id"], ADMIN))
    assert inq["match_count"] == 1
    rows, _ = validate_paginated(api.list_matches(ADMIN, params={"inquiry_id": sc["inquiry"]["id"]}))
    assert len(rows) == 1 and rows[0]["id"] == sc["match"]["id"]


def test_selecting_a_shortlisted_match_rejected(api):
    """PRD §3.6: "Selecting moves a `TOURED` match to `SELECTED` and additionally
    requires the match's community to still be `ACTIVE` ... Each of these
    transitions rejects a match not in its from-set with `ERR_MATCH_INVALID_STATE`."

    Design: Corner/state_machines/selecting_a_shortlisted_match_rejected_before_any_tour_is_completed
    """
    sc = _shortlisted(api)
    resp = api.select_match(sc["match"]["id"], sc["advisor_headers"])
    validate_error(resp, ApiErrorId.ERR_MATCH_INVALID_STATE)
    m = validate_success(api.get_match(sc["match"]["id"], ADMIN))
    assert m["status"] == "SHORTLISTED"


# ---------------------------------------------------------------------------
# Corner: tour lifecycle and cycles.
# ---------------------------------------------------------------------------

def test_tour_shorter_than_thirty_minutes_rejected(api):
    """PRD §3.7: "The time window must be well-formed: `scheduled_end` strictly
    after `scheduled_start`, the duration between 30 and 180 minutes inclusive, and
    `scheduled_start` at or after the logical clock's current instant — any of these
    failing yields `ERR_TOUR_OUTSIDE_HOURS`."

    Design: Corner/validations/tour_shorter_than_thirty_minutes_returns_tour_outside_hours
    """
    sc = _shortlisted(api)
    resp = api.create_tour(create_tour_payload(
        sc["match"]["id"], scheduled_start="2026-06-05T15:00:00Z",
        scheduled_end="2026-06-05T15:20:00Z", mode="IN_PERSON"), sc["advisor_headers"])
    validate_error(resp, ApiErrorId.ERR_TOUR_OUTSIDE_HOURS)
    m = validate_success(api.get_match(sc["match"]["id"], ADMIN))
    assert m["status"] == "SHORTLISTED" and m["tour_round"] == 0
    rows, _ = validate_paginated(api.list_tours(ADMIN, params={"match_id": sc["match"]["id"]}))
    assert rows == []


def test_toured_match_returns_to_shortlist_for_second_round(api):
    """PRD §3.6: "Shortlisting moves a `PROPOSED` match to `SHORTLISTED`, and also
    returns a `TOURED` match to `SHORTLISTED` when a family wants a repeat visit".
    PRD §3.7: "The shortlist-tour loop `SHORTLISTED → TOUR_SCHEDULED → SHORTLISTED`
    may repeat, and `tour_round` records how many times it ran."

    Design: Corner/state_machines/toured_match_returned_to_shortlist_supports_a_second_tour_round
    """
    sc = _toured(api)
    ahdr = sc["advisor_headers"]
    api.shortlist_match(sc["match"]["id"], ahdr)
    t2 = get_success_data(api.create_tour(create_tour_payload(
        sc["match"]["id"], scheduled_start="2026-06-12T15:00:00Z",
        scheduled_end="2026-06-12T16:00:00Z", mode="VIRTUAL"), ahdr))
    m = validate_success(api.get_match(sc["match"]["id"], ADMIN))
    assert m["status"] == "TOUR_SCHEDULED" and m["tour_round"] == 2
    assert validate_success(api.get_tour(sc["tour"]["id"], ADMIN))["status"] == "COMPLETED"
    t2r = validate_success(api.get_tour(t2["id"], ADMIN))
    assert t2r["status"] == "SCHEDULED" and t2r["mode"] == "VIRTUAL"
    rows, _ = validate_paginated(api.list_tours(ADMIN, params={"match_id": sc["match"]["id"]}))
    assert len(rows) == 2
    assert validate_success(api.get_inquiry(sc["inquiry"]["id"], ADMIN))["status"] == "TOURING"


def test_tour_cancel_returns_match_to_shortlist_and_frees_slot(api):
    """PRD §3.7: "Cancelling a scheduled tour records a `reason_code` into
    `cancel_reason_code`, moves the tour `SCHEDULED → CANCELLED`, returns its match
    `TOUR_SCHEDULED → SHORTLISTED`, and releases the community tour slot the tour
    occupied."

    Design: Corner/state_machines/tour_cancel_returns_match_to_shortlisted_and_frees_the_community_slot
    """
    sc = _shortlisted(api, community_overrides={"tour_slot_capacity": 1})
    ahdr = sc["advisor_headers"]
    t1 = get_success_data(api.create_tour(create_tour_payload(sc["match"]["id"]), ahdr))
    api.cancel_tour(t1["id"], {"reason_code": "FAMILY_RESCHEDULE"}, ahdr)
    resp = api.create_tour(create_tour_payload(sc["match"]["id"]), ahdr)
    t2 = validate_success(resp, 201)
    assert validate_success(api.get_tour(t1["id"], ADMIN))["cancel_reason_code"] == "FAMILY_RESCHEDULE"
    assert validate_success(api.get_tour(t1["id"], ADMIN))["status"] == "CANCELLED"
    assert t2["status"] == "SCHEDULED"
    m = validate_success(api.get_match(sc["match"]["id"], ADMIN))
    assert m["status"] == "TOUR_SCHEDULED" and m["tour_round"] == 2
    rows, _ = validate_paginated(api.list_tours(
        ADMIN, params={"community_id": sc["community"]["id"], "status": "SCHEDULED"}))
    assert len(rows) == 1 and rows[0]["id"] == t2["id"]


def test_completing_an_already_completed_tour_rejected(api):
    """PRD §3.7: "All three of these post-schedule actions require the tour to be
    `SCHEDULED`, else `ERR_TOUR_INVALID_STATE`."

    Design: Corner/state_machines/completing_an_already_completed_tour_returns_tour_invalid_state
    """
    sc = _toured(api)
    resp = api.complete_tour(sc["tour"]["id"], {"outcome_rating": 5}, sc["advisor_headers"])
    validate_error(resp, ApiErrorId.ERR_TOUR_INVALID_STATE)
    t = validate_success(api.get_tour(sc["tour"]["id"], ADMIN))
    assert t["status"] == "COMPLETED" and t["outcome_rating"] == 3
    m = validate_success(api.get_match(sc["match"]["id"], ADMIN))
    assert m["status"] == "TOURED" and m["tour_round"] == 1


def test_inquiry_hold_from_touring_cancels_tours_resume_lands_matching(api):
    """PRD §3.8: "When the hold is placed from `TOURING`, it also cancels every one
    of the inquiry's tours that is still `SCHEDULED` — setting each such tour's
    `cancel_reason_code` to `INQUIRY_ON_HOLD` — and returns each of those tours'
    matches `TOUR_SCHEDULED → SHORTLISTED`."
    PRD §3.8: "Resuming a paused inquiry clears its `hold_reason` and always returns
    it to `MATCHING`, regardless of whether the hold came from `MATCHING` or
    `TOURING`".

    Design: Corner/state_machines/inquiry_hold_from_touring_cancels_tours_and_resume_lands_on_matching
    """
    sc = _shortlisted(api)
    ahdr = sc["advisor_headers"]
    t1 = get_success_data(api.create_tour(create_tour_payload(sc["match"]["id"]), ahdr))
    validate_success(api.hold_inquiry(sc["inquiry"]["id"], {"reason": "Family postponed."}, ahdr))
    inq = validate_success(api.get_inquiry(sc["inquiry"]["id"], ADMIN))
    assert inq["status"] == "ON_HOLD"
    t = validate_success(api.get_tour(t1["id"], ADMIN))
    assert t["status"] == "CANCELLED" and t["cancel_reason_code"] == "INQUIRY_ON_HOLD"
    assert validate_success(api.get_match(sc["match"]["id"], ADMIN))["status"] == "SHORTLISTED"
    validate_success(api.resume_inquiry(sc["inquiry"]["id"], {}, ahdr))
    inq2 = validate_success(api.get_inquiry(sc["inquiry"]["id"], ADMIN))
    assert inq2["status"] == "MATCHING"
    assert inq2["hold_reason"] is None
    assert validate_success(api.get_tour(t1["id"], ADMIN))["status"] == "CANCELLED"


def test_resuming_an_inquiry_not_on_hold_rejected(api):
    """PRD §3.8: "Resuming a paused inquiry clears its `hold_reason` and always
    returns it to `MATCHING`, regardless of whether the hold came from `MATCHING` or
    `TOURING`; resume requires the inquiry to be `ON_HOLD`."

    Design: Corner/validations/resuming_an_inquiry_that_is_not_on_hold_returns_inquiry_invalid_state
    """
    sc = build_scenario(api, "matched")
    resp = api.resume_inquiry(sc["inquiry"]["id"], {}, sc["advisor_headers"])
    validate_error(resp, ApiErrorId.ERR_INQUIRY_INVALID_STATE)
    assert validate_success(api.get_inquiry(sc["inquiry"]["id"], ADMIN))["status"] == "MATCHING"


def test_closing_inquiry_withdraws_matches_and_releases_caseload(api):
    """PRD §3.8: "On close, every match of the inquiry whose status is `PROPOSED`,
    `SHORTLISTED`, `TOUR_SCHEDULED` or `TOURED` moves to `WITHDRAWN`; ... and the
    inquiry's `ACTIVE` caseload assignment moves to `RELEASED` with `release_reason`
    `CLOSED_LOST`, decrementing the owning advisor's `active_caseload_count` by 1 and
    recomputing both its load indices."

    Design: Corner/state_machines/closing_an_inquiry_withdraws_matches_and_releases_the_caseload_slot
    """
    sc = _shortlisted(api)
    validate_success(api.close_inquiry(sc["inquiry"]["id"], {"reason_code": "CHOSE_HOME_CARE"}, sc["advisor_headers"]))
    inq = validate_success(api.get_inquiry(sc["inquiry"]["id"], ADMIN))
    assert inq["status"] == "CLOSED_LOST" and inq["close_reason_code"] == "CHOSE_HOME_CARE"
    assert inq["match_count"] == 0
    assert validate_success(api.get_match(sc["match"]["id"], ADMIN))["status"] == "WITHDRAWN"
    advisor = validate_success(api.get_advisor(sc["advisor"]["id"], ADMIN))
    assert advisor["active_caseload_count"] == 0 and advisor["headcount_load_index"] == 0.0
    rows, _ = validate_paginated(api.list_caseload_assignments(ADMIN, params={"inquiry_id": sc["inquiry"]["id"]}))
    assert len(rows) == 1
    assert rows[0]["status"] == "RELEASED" and rows[0]["release_reason"] == "CLOSED_LOST"
