"""Application lifecycle, jury scoring, decisions, waitlist ranking, and the
fixed decide-time check ordering (posture -> state -> quorum -> ... -> OCC)."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    make_vendor_headers, make_juror_headers, make_event_coordinator_headers,
    assert_jury_score, assert_vendor_application,
    create_application, submit_application, post_jury_scores,
    decide_application, begin_scheduling, get_event, get_assignment_for_app,
    list_assignments_for_app, create_vendor, open_applications,
    close_applications, create_event, create_zone, create_booth,
    reset_clock, setup_in_review_ctx, setup_approved_ctx,
    api_client,
)


# ─── Cross-entity posture gating of submit ──────────────────────────────────

def test_submit_rejected_when_event_not_in_application_open(api):
    """PRD §3.2: "The event's posture must be `APPLICATION_OPEN`; the logical clock
    must sit inside the half-open intake window — on or after
    `application_window_start` and strictly before `application_window_end`, with
    attempts outside that span rejected as `ERR_APPLICATION_WINDOW_CLOSED`; the
    vendor's profile must be `ACTIVE`; and the requested category's cap must not
    already be exhausted by approved applications."
    PRD §2.4: "When the current posture does not permit the requested child write,
    the request is rejected with `ERR_POSTURE_FORBIDS`."

    Design: Difficulty/cross_entity_state_dependency/application_submit_gated_by_event_posture
    """
    reset_clock()
    coordinator = TEST_USERS["event_coordinator_headers"]
    event = create_event(coordinator, name="Gated Fair")
    vendor = create_vendor()
    # Event stays in PLANNING (open-applications never called); the clock sits
    # inside the intake window, so only the posture gate can fail.
    app = create_application(event["id"], vendor)
    res = api_client.submit_application(
        event["id"], app["id"], make_vendor_headers(vendor["id"])
    )
    validate_error(res, ApiErrorId.ERR_POSTURE_FORBIDS, expected_status=409)
    after = get_success_data(
        api_client.get_application(event["id"], app["id"], coordinator)
    )
    assert after["status"] == "DRAFT", (
        f"rejected submit must leave the application DRAFT, got {after['status']}"
    )


def test_submit_succeeds_while_application_open(api):
    """PRD §3.2: "The event's posture must be `APPLICATION_OPEN`; the logical clock
    must sit inside the half-open intake window — on or after
    `application_window_start` and strictly before `application_window_end`, with
    attempts outside that span rejected as `ERR_APPLICATION_WINDOW_CLOSED`; the
    vendor's profile must be `ACTIVE`; and the requested category's cap must not
    already be exhausted by approved applications."

    Design: Difficulty/cross_entity_state_dependency/application_submit_gated_by_event_posture
    """
    reset_clock()
    coordinator = TEST_USERS["event_coordinator_headers"]
    event = create_event(coordinator, name="Open Fair")
    create_zone(event["id"], coordinator)
    vendor = create_vendor()
    open_applications(event["id"], coordinator)
    app = create_application(event["id"], vendor)
    submitted = validate_success(
        api_client.submit_application(
            event["id"], app["id"], make_vendor_headers(vendor["id"])
        ),
        200,
    )
    assert submitted["status"] == "SUBMITTED"


# ─── Branching decide (APPROVE / WAITLIST / REJECT) ─────────────────────────

def test_decide_approve_grants_booth_assignment(api):
    """PRD §3.3: "Against that booth it creates a BoothAssignment in
    `PENDING_PAYMENT` status, linked to the application it places through the
    system-maintained `vendor_application_id`, stamping `assigned_at` with the
    current logical instant, setting `payment_due_at` exactly 72 hours — three
    days — after `assigned_at`, and snapshotting the event's current `version`
    into the assignment's `expected_event_version`."

    Design: Difficulty/non_linear_state_machine/vendor_application_branching_decide
    """
    ctx = setup_approved_ctx(begin_schedule=False)
    decided = ctx["decided_app"]
    assert_vendor_application(decided)
    assert decided["status"] == "APPROVED"
    assignment = ctx["assignment"]
    assert assignment["status"] == "PENDING_PAYMENT"
    assert assignment["vendor_application_id"] == ctx["app"]["id"]


def test_decide_waitlist_and_reject_mint_no_assignment(api):
    """PRD §3.3: "A `WAITLIST` outcome moves the application to `WAITLISTED` — its
    `waitlist_rank` remaining unset until scheduling begins, since `waitlist_rank`
    is null unless the application is `WAITLISTED` and the ranking has been
    materialized — and a `REJECT` outcome moves it to `REJECTED`; neither mints an
    assignment."

    Design: Difficulty/non_linear_state_machine/vendor_application_branching_decide
    """
    coordinator = TEST_USERS["event_coordinator_headers"]
    reset_clock()
    event = create_event(coordinator, name="Branch Fair")
    zone = create_zone(event["id"], coordinator, category_cap=1)
    create_booth(event["id"], zone["id"], coordinator)
    v2, v3 = create_vendor(), create_vendor()
    open_applications(event["id"], coordinator)
    app_wait = create_application(event["id"], v2)
    submit_application(event["id"], app_wait["id"], v2["id"])
    app_rej = create_application(event["id"], v3)
    submit_application(event["id"], app_rej["id"], v3["id"])
    close_applications(event["id"], coordinator)
    post_jury_scores(event["id"], app_wait["id"])
    post_jury_scores(event["id"], app_rej["id"],
                     cards=((5, 5, 5), (5, 5, 5)))

    res_wait = decide_application(event["id"], app_wait["id"], "WAITLIST", coordinator)
    decided_wait = validate_success(res_wait, 200)
    assert decided_wait["status"] == "WAITLISTED"

    res_rej = decide_application(event["id"], app_rej["id"], "REJECT", coordinator)
    decided_rej = validate_success(res_rej, 200)
    assert decided_rej["status"] == "REJECTED"

    assert list_assignments_for_app(event["id"], app_wait["id"], coordinator) == [], (
        "WAITLIST must not mint a BoothAssignment"
    )
    assert list_assignments_for_app(event["id"], app_rej["id"], coordinator) == [], (
        "REJECT must not mint a BoothAssignment"
    )


# ─── Fixed decide-time check ordering: posture masks quorum ─────────────────

def test_decide_posture_gate_fires_before_quorum(api):
    """PRD §3.3: "The checks guarding a decision run in a fixed order, so that
    earlier failures mask later ones: the posture gate first (the event must be in
    `JURY_REVIEW`, else `ERR_POSTURE_FORBIDS`), then the application's own state (it
    must be `IN_REVIEW`, else `ERR_INVALID_STATE`), then quorum (`jury_score_count`
    must reach the event's `jury_quorum`, else `ERR_JURY_QUORUM_NOT_MET`), then the
    booth constraint for the auto-grant (the granted booth's tier must equal the
    application's `requested_tier`, else `ERR_BOOTH_CONSTRAINT_VIOLATION`), then the
    category cap (approving must not push the count of `APPROVED` applications for
    the `requested_category` above the effective cap for that category, else
    `ERR_CATEGORY_CAP_EXCEEDED`), then booth occupancy (no other non-terminal
    assignment on the chosen booth, else `ERR_BOOTH_DOUBLE_BOOKED`), and only last
    the version check (a stale `expected_event_version` is rejected with
    `ERR_STALE_VERSION`)."

    Design: Difficulty/priority_pair_validation_conflict/posture_forbids_vs_quorum_not_met
    """
    coordinator = TEST_USERS["event_coordinator_headers"]
    reset_clock()
    event = create_event(coordinator, name="Priority Fair")
    zone = create_zone(event["id"], coordinator)
    create_booth(event["id"], zone["id"], coordinator)
    v1, v2 = create_vendor(), create_vendor()
    open_applications(event["id"], coordinator)
    # app1 is created but NEVER submitted -> DRAFT -> WITHDRAWN at close, and it
    # carries zero jury scores (quorum cannot be met). app2 is decided WAITLIST so
    # that begin-scheduling can proceed with no unresolved applications.
    app1 = create_application(event["id"], v1)
    app2 = create_application(event["id"], v2)
    submit_application(event["id"], app2["id"], v2["id"])
    close_applications(event["id"], coordinator)
    post_jury_scores(event["id"], app2["id"])
    res = decide_application(event["id"], app2["id"], "WAITLIST", coordinator)
    validate_success(res, 200)
    begin_scheduling(event["id"], coordinator)

    # Posture is SCHEDULING: decide is forbidden regardless of app1's zero-score
    # quorum shortfall; the posture gate masks the quorum check.
    res = decide_application(event["id"], app1["id"], "APPROVE", coordinator)
    validate_error(res, ApiErrorId.ERR_POSTURE_FORBIDS, expected_status=409)


def test_decide_quorum_check_fires_when_posture_allows(api):
    """PRD §3.3: "The checks guarding a decision run in a fixed order, so that
    earlier failures mask later ones: the posture gate first (the event must be in
    `JURY_REVIEW`, else `ERR_POSTURE_FORBIDS`), then the application's own state (it
    must be `IN_REVIEW`, else `ERR_INVALID_STATE`), then quorum (`jury_score_count`
    must reach the event's `jury_quorum`, else `ERR_JURY_QUORUM_NOT_MET`), then the
    booth constraint for the auto-grant (the granted booth's tier must equal the
    application's `requested_tier`, else `ERR_BOOTH_CONSTRAINT_VIOLATION`), then the
    category cap (approving must not push the count of `APPROVED` applications for
    the `requested_category` above the effective cap for that category, else
    `ERR_CATEGORY_CAP_EXCEEDED`), then booth occupancy (no other non-terminal
    assignment on the chosen booth, else `ERR_BOOTH_DOUBLE_BOOKED`), and only last
    the version check (a stale `expected_event_version` is rejected with
    `ERR_STALE_VERSION`)."

    Design: Difficulty/priority_pair_validation_conflict/posture_forbids_vs_quorum_not_met
    """
    # Contrast leg: posture permits decide (JURY_REVIEW) and the application is
    # IN_REVIEW, but zero scores against jury_quorum=2 surfaces the quorum error.
    ctx = setup_in_review_ctx(score_cards=())
    res = decide_application(ctx["event"]["id"], ctx["app"]["id"], "APPROVE",
                             ctx["coordinator_headers"])
    validate_error(res, ApiErrorId.ERR_JURY_QUORUM_NOT_MET, expected_status=409)


# ─── Segregation of duties at jury-score time ───────────────────────────────

def test_vendor_scoring_own_application_rejected(api):
    """PRD §2.9: "A juror scoring an application must not be the vendor who filed
    it, and must not be the coordinator who created the event; the submitted
    `juror_user_id` is checked against both, and a collision is rejected with
    `ERR_SOD_VIOLATION`."

    Design: Difficulty/priority_pair_validation_conflict/sod_vs_quorum_pair
    """
    ctx = setup_in_review_ctx()
    event_id, app_id = ctx["event"]["id"], ctx["app"]["id"]
    # A neutral juror card already exists; the applicant now attempts to score
    # their own application. Only the segregation-of-duties check can fail.
    res = api_client.create_jury_score(
        event_id, app_id,
        {"craftsmanship": 10, "originality": 10, "booth_presentation": 10},
        make_juror_headers(ctx["vendor"]["id"]),
    )
    validate_error(res, ApiErrorId.ERR_SOD_VIOLATION, expected_status=403)


def test_event_coordinator_scoring_application_rejected(api):
    """PRD §2.9: "A juror scoring an application must not be the vendor who filed
    it, and must not be the coordinator who created the event; the submitted
    `juror_user_id` is checked against both, and a collision is rejected with
    `ERR_SOD_VIOLATION`."

    Design: Difficulty/priority_pair_validation_conflict/sod_vs_quorum_pair
    """
    ctx = setup_in_review_ctx(coordinator_user_id="coordinator-self-score")
    res = api_client.create_jury_score(
        ctx["event"]["id"], ctx["app"]["id"],
        {"craftsmanship": 7, "originality": 7, "booth_presentation": 7},
        make_juror_headers("coordinator-self-score"),
    )
    validate_error(res, ApiErrorId.ERR_SOD_VIOLATION, expected_status=403)


# ─── Waitlist ranking materialization ───────────────────────────────────────

def test_waitlist_rank_materialized_by_score_then_created_at(api):
    """PRD §3.4: "Independently within each `requested_category`, the system sorts
    that category's `WAITLISTED` applications by `jury_score_total` from highest to
    lowest, breaks ties by the application's `created_at` from earliest to latest,
    and breaks any remaining tie by `vendor_profile_id` in ascending lexicographic
    order — a last-resort determinism device, never a business signal."
    PRD §3.4: "The sorted applications receive `waitlist_rank` values 1 through N in
    that order, and rank 1 is the head of the line for its category."

    Design: Difficulty/combinatorial_formula/waitlist_rank_combinatorial_scoring
    """
    coordinator = TEST_USERS["event_coordinator_headers"]
    reset_clock()
    event = create_event(coordinator, name="Fall Fair")
    zone = create_zone(event["id"], coordinator, category_cap=1)
    create_booth(event["id"], zone["id"], coordinator)
    open_applications(event["id"], coordinator)

    # Creation order fixes created_at: fast earliest, then slow, then low.
    # fast and slow tie on jury_score_total 50, so created_at breaks the tie;
    # low trails on score 40 despite being created last.
    specs = []
    for name, cards in (
        ("fast", ((9, 8, 8), (8, 8, 9))),   # total 50
        ("slow", ((9, 8, 8), (8, 8, 9))),   # total 50, created later than fast
        ("low", ((7, 7, 6), (7, 6, 7))),    # total 40
    ):
        vendor = create_vendor(display_name=f"Vendor {name}")
        app = create_application(event["id"], vendor)
        submit_application(event["id"], app["id"], vendor["id"])
        specs.append((name, app, cards))

    close_applications(event["id"], coordinator)
    for _name, app, cards in specs:
        post_jury_scores(event["id"], app["id"], cards=cards)
    for _name, app, _cards in specs:
        res = decide_application(event["id"], app["id"], "WAITLIST", coordinator)
        validate_success(res, 200)

    begin_scheduling(event["id"], coordinator)

    apps = {
        name: get_success_data(api_client.get_application(event["id"], app["id"],
                                                          coordinator))
        for name, app, _ in specs
    }
    assert apps["fast"]["jury_score_total"] == 50
    assert apps["slow"]["jury_score_total"] == 50
    assert apps["low"]["jury_score_total"] == 40
    assert apps["fast"]["waitlist_rank"] == 1, (
        f"score tie breaks by earliest created_at: fast={apps['fast']['waitlist_rank']}"
    )
    assert apps["slow"]["waitlist_rank"] == 2
    assert apps["low"]["waitlist_rank"] == 3


def test_waitlist_rank_unset_until_scheduling_begins(api):
    """PRD §3.3: "A `WAITLIST` outcome moves the application to `WAITLISTED` — its
    `waitlist_rank` remaining unset until scheduling begins, since `waitlist_rank`
    is null unless the application is `WAITLISTED` and the ranking has been
    materialized — and a `REJECT` outcome moves it to `REJECTED`; neither mints an
    assignment."

    Design: Difficulty/combinatorial_formula/waitlist_rank_combinatorial_scoring
    """
    ctx = setup_in_review_ctx()
    event_id = ctx["event"]["id"]
    res = decide_application(event_id, ctx["app"]["id"], "WAITLIST",
                             ctx["coordinator_headers"])
    decided = validate_success(res, 200)
    assert decided["status"] == "WAITLISTED"
    assert decided.get("waitlist_rank") is None, (
        "waitlist_rank must remain unset until scheduling materializes the ranking"
    )
    begin_scheduling(event_id, ctx["coordinator_headers"])
    ranked = get_success_data(
        api_client.get_application(event_id, ctx["app"]["id"],
                                   ctx["coordinator_headers"])
    )
    assert ranked["waitlist_rank"] == 1


# ─── Jury score record shape ────────────────────────────────────────────────

def test_jury_score_append_only_and_total_is_sum(api):
    """PRD §2.6: "JuryScore, Attendance, and SalesLedgerEntry are append-only
    records: they carry `id` and `created_at` only, and both `updated_at` and
    `version` are absent from them."
    PRD §3.3: "A `Juror` submits a scorecard for an application with three criteria —
    `craftsmanship`, `originality`, and `booth_presentation` — each an integer from 0
    to 10, and the card's `total` is their sum, from 0 to 30."

    Design: Corner/entities/jury_score_common_fields_false_no_version
    """
    ctx = setup_in_review_ctx(score_cards=())
    res = api_client.create_jury_score(
        ctx["event"]["id"], ctx["app"]["id"],
        {"craftsmanship": 8, "originality": 8, "booth_presentation": 8},
        make_juror_headers("juror-1"),
    )
    score = validate_success(res, 201)
    assert_jury_score(score)
    assert score["total"] == 24, f"total must be 8+8+8=24, got {score['total']}"


# ─── Corner validations around decide ───────────────────────────────────────

def test_decide_in_application_open_rejected_by_posture_gate(api):
    """PRD §3.3: "The checks guarding a decision run in a fixed order, so that
    earlier failures mask later ones: the posture gate first (the event must be in
    `JURY_REVIEW`, else `ERR_POSTURE_FORBIDS`), then the application's own state (it
    must be `IN_REVIEW`, else `ERR_INVALID_STATE`), then quorum (`jury_score_count`
    must reach the event's `jury_quorum`, else `ERR_JURY_QUORUM_NOT_MET`), then the
    booth constraint for the auto-grant (the granted booth's tier must equal the
    application's `requested_tier`, else `ERR_BOOTH_CONSTRAINT_VIOLATION`), then the
    category cap (approving must not push the count of `APPROVED` applications for
    the `requested_category` above the effective cap for that category, else
    `ERR_CATEGORY_CAP_EXCEEDED`), then booth occupancy (no other non-terminal
    assignment on the chosen booth, else `ERR_BOOTH_DOUBLE_BOOKED`), and only last
    the version check (a stale `expected_event_version` is rejected with
    `ERR_STALE_VERSION`)."

    Design: Corner/state_machines/approve_from_wrong_state_returns_invalid_state
    """
    coordinator = TEST_USERS["event_coordinator_headers"]
    reset_clock()
    event = create_event(coordinator, name="S")
    vendor = create_vendor()
    open_applications(event["id"], coordinator)
    app = create_application(event["id"], vendor)  # stays DRAFT
    version = get_event(event["id"], coordinator)["version"]
    res = api_client.decide_application(
        event["id"], app["id"],
        {"outcome": "APPROVE", "expected_event_version": version},
        coordinator,
    )
    # Posture is APPLICATION_OPEN (not JURY_REVIEW): the posture gate precedes the
    # per-entity state gate in the fixed decide ordering.
    validate_error(res, ApiErrorId.ERR_POSTURE_FORBIDS, expected_status=409)


def test_decide_with_insufficient_jury_scores_rejected(api):
    """PRD §3.3: "The checks guarding a decision run in a fixed order, so that
    earlier failures mask later ones: the posture gate first (the event must be in
    `JURY_REVIEW`, else `ERR_POSTURE_FORBIDS`), then the application's own state (it
    must be `IN_REVIEW`, else `ERR_INVALID_STATE`), then quorum (`jury_score_count`
    must reach the event's `jury_quorum`, else `ERR_JURY_QUORUM_NOT_MET`), then the
    booth constraint for the auto-grant (the granted booth's tier must equal the
    application's `requested_tier`, else `ERR_BOOTH_CONSTRAINT_VIOLATION`), then the
    category cap (approving must not push the count of `APPROVED` applications for
    the `requested_category` above the effective cap for that category, else
    `ERR_CATEGORY_CAP_EXCEEDED`), then booth occupancy (no other non-terminal
    assignment on the chosen booth, else `ERR_BOOTH_DOUBLE_BOOKED`), and only last
    the version check (a stale `expected_event_version` is rejected with
    `ERR_STALE_VERSION`)."

    Design: Corner/validations/jury_quorum_not_met_at_decide
    """
    # Exactly one distinct juror score against jury_quorum=2.
    ctx = setup_in_review_ctx(score_cards=((8, 8, 8),))
    res = decide_application(ctx["event"]["id"], ctx["app"]["id"], "APPROVE",
                             ctx["coordinator_headers"])
    validate_error(res, ApiErrorId.ERR_JURY_QUORUM_NOT_MET, expected_status=409)


def test_category_cap_exceeded_rejected(api):
    """PRD §3.3: "The checks guarding a decision run in a fixed order, so that
    earlier failures mask later ones: the posture gate first (the event must be in
    `JURY_REVIEW`, else `ERR_POSTURE_FORBIDS`), then the application's own state (it
    must be `IN_REVIEW`, else `ERR_INVALID_STATE`), then quorum (`jury_score_count`
    must reach the event's `jury_quorum`, else `ERR_JURY_QUORUM_NOT_MET`), then the
    booth constraint for the auto-grant (the granted booth's tier must equal the
    application's `requested_tier`, else `ERR_BOOTH_CONSTRAINT_VIOLATION`), then the
    category cap (approving must not push the count of `APPROVED` applications for
    the `requested_category` above the effective cap for that category, else
    `ERR_CATEGORY_CAP_EXCEEDED`), then booth occupancy (no other non-terminal
    assignment on the chosen booth, else `ERR_BOOTH_DOUBLE_BOOKED`), and only last
    the version check (a stale `expected_event_version` is rejected with
    `ERR_STALE_VERSION`)."
    PRD §3.1: "for any given craft category, the effective ceiling for the whole
    event is the maximum `category_cap` among the event's zones carrying that
    category, and it bounds the number of applications that may simultaneously hold
    `APPROVED` status for that category across the entire event."

    Design: Corner/validations/category_cap_exceeded_rejected
    """
    coordinator = TEST_USERS["event_coordinator_headers"]
    reset_clock()
    event = create_event(coordinator, name="Cap Fair")
    zone = create_zone(event["id"], coordinator, category_cap=1)
    create_booth(event["id"], zone["id"], coordinator, code="H-01")
    create_booth(event["id"], zone["id"], coordinator, code="H-02")
    v1, v2 = create_vendor(), create_vendor()
    open_applications(event["id"], coordinator)
    app1 = create_application(event["id"], v1)
    submit_application(event["id"], app1["id"], v1["id"])
    app2 = create_application(event["id"], v2)
    submit_application(event["id"], app2["id"], v2["id"])
    close_applications(event["id"], coordinator)
    post_jury_scores(event["id"], app1["id"], cards=((9, 9, 9), (9, 9, 9)))
    post_jury_scores(event["id"], app2["id"])

    res1 = decide_application(event["id"], app1["id"], "APPROVE", coordinator)
    validate_success(res1, 200)
    # Second approval would push CERAMICS APPROVED count to 2 > effective cap 1.
    res2 = decide_application(event["id"], app2["id"], "APPROVE", coordinator)
    validate_error(res2, ApiErrorId.ERR_CATEGORY_CAP_EXCEEDED, expected_status=409)


def test_decide_bumps_event_version(api):
    """PRD §3.3: "Every decision, whatever its outcome, mutates the event itself:
    the MakerEvent's `version` advances by one and its `updated_at` refreshes."

    Design: Corner/endpoints/decide_bumps_event_version
    """
    ctx = setup_in_review_ctx()
    event_id = ctx["event"]["id"]
    before = get_event(event_id, ctx["coordinator_headers"])["version"]
    res = api_client.decide_application(
        event_id, ctx["app"]["id"],
        {"outcome": "APPROVE", "expected_event_version": before},
        ctx["coordinator_headers"],
    )
    validate_success(res, 200)
    after = get_event(event_id, ctx["coordinator_headers"])["version"]
    assert after == before + 1, (
        f"MakerEvent.version must advance by exactly one per decision: "
        f"{before} -> {after}"
    )


def test_decide_with_stale_event_version_rejected(api):
    """PRD §2.8: "Deciding an application (the write that can grant a booth)
    requires the request to carry `expected_event_version`, holding the MakerEvent
    `version` the coordinator last observed. If the event's current `version` no
    longer matches — because the event has been mutated since the coordinator read
    it — the decision is rejected with `ERR_STALE_VERSION` (HTTP 412), and the
    coordinator must re-read the event and its booth pool before retrying."

    Design: Corner/errors/err_stale_version_on_decide
    """
    coordinator = TEST_USERS["event_coordinator_headers"]
    reset_clock()
    event = create_event(coordinator, name="OCC Fair")
    zone = create_zone(event["id"], coordinator)
    create_booth(event["id"], zone["id"], coordinator, code="H-01")
    create_booth(event["id"], zone["id"], coordinator, code="H-02")
    v1, v2 = create_vendor(), create_vendor()
    open_applications(event["id"], coordinator)
    app1 = create_application(event["id"], v1)
    submit_application(event["id"], app1["id"], v1["id"])
    app2 = create_application(event["id"], v2)
    submit_application(event["id"], app2["id"], v2["id"])
    close_applications(event["id"], coordinator)
    post_jury_scores(event["id"], app1["id"])
    post_jury_scores(event["id"], app2["id"])

    stale_version = get_event(event["id"], coordinator)["version"]
    # A first decision mutates the event, advancing its version.
    res1 = api_client.decide_application(
        event["id"], app1["id"],
        {"outcome": "WAITLIST", "expected_event_version": stale_version},
        coordinator,
    )
    validate_success(res1, 200)
    # app2 is IN_REVIEW with quorum met, cap and booth available: only the OCC
    # token is stale, so the version check fires last with ERR_STALE_VERSION.
    res2 = api_client.decide_application(
        event["id"], app2["id"],
        {"outcome": "APPROVE", "expected_event_version": stale_version},
        coordinator,
    )
    validate_error(res2, ApiErrorId.ERR_STALE_VERSION, expected_status=412)


def test_decide_response_reflects_status_immediately(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data field."
    PRD §3.3: "The system grants a booth by selector policy: among booths whose zone
    category matches the `requested_category`, whose `tier` matches the
    `requested_tier`, and which are unoccupied, it chooses the lowest-priced; ties
    break by booth `code` in ascending order, and any remaining tie by the booth's
    `created_at` in ascending order."

    Design: Corner/consistency_model/decide_response_reflects_status_immediately
    """
    ctx = setup_in_review_ctx()
    res = decide_application(ctx["event"]["id"], ctx["app"]["id"], "APPROVE",
                             ctx["coordinator_headers"])
    decided = validate_success(res, 200)
    assert decided["status"] == "APPROVED", (
        f"decide response must carry the updated status APPROVED, got "
        f"{decided['status']}"
    )
    assert decided["id"] == ctx["app"]["id"]
