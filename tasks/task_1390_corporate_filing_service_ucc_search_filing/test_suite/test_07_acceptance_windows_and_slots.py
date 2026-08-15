"""Acceptance: sixty-month expiration, immediate consistency, collateral DELETE
presence, filed_at bracketing, continuation window boundaries, and the perfection
slot's half-open effectiveness interval."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_attempt,
    approve_preparation,
    create_draft_attempt,
    create_ready_request,
    create_ucc3_request,
    get_filing,
    get_request,
    list_filing_events,
    register_debtor,
    set_clock_to,
    setup_active_initial_filing,
    setup_client_world,
    submit_attempt,
    submit_intake,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
SPECIALIST = TEST_USERS["specialist_headers"]
OFFICER = TEST_USERS["officer_headers"]


def test_initial_filing_expiration_sixty_months(api):
    """PRD §3.5: "- **`INITIAL`.** The attempt's `expiration_at` is set to exactly
    sixty calendar months after `filed_at`, preserving the day of month."

    Design: Corner/calculations/initial_filing_expiration_sixty_months
    """
    world = setup_client_world()
    request = create_ready_request(world["client"], world["debtor"], world["secured_party"])
    attempt = create_draft_attempt(request["id"])
    submit_attempt(attempt["id"])
    filing = accept_attempt(attempt["id"], filing_number="CA-2026-0001",
                            filed_at="2026-08-01T00:00:00Z")
    assert filing["filed_at"] == "2026-08-01T00:00:00Z"
    assert filing["expiration_at"] == "2031-08-01T00:00:00Z", (
        f"filed_at + 60 calendar months must be 2031-08-01, got {filing['expiration_at']}"
    )


def test_acceptance_response_immediately_visible(api):
    """PRD §3.5: "A successful acceptance stores `filing_number` and `filed_at`, moves
    the attempt `SUBMITTED` → `ACTIVE`, and appends an `ACCEPTED` event."
    PRD §3.5: "In all cases the parent request moves `IN_PROCESS` → `FULFILLED`".
    PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will
    return the created or updated resource object in the data field."

    Design: Corner/consistency_model/immediate_visibility_after_acceptance
    """
    world = setup_client_world()
    request = create_ready_request(world["client"], world["debtor"], world["secured_party"])
    attempt = create_draft_attempt(request["id"])
    submit_attempt(attempt["id"])
    resp = api.record_acceptance(
        attempt["id"],
        {"filing_number": "CA-2026-0001", "filed_at": "2026-08-01T00:00:00Z"},
        OFFICER,
    )
    data = validate_success(resp, expected_status=200)
    # The acceptance response itself carries the new state — no re-read needed.
    assert data["effectiveness_status"] == "ACTIVE"
    assert data["filing_number"] == "CA-2026-0001"
    assert data["expiration_at"] == "2031-08-01T00:00:00Z"
    assert get_request(request["id"])["status"] == "FULFILLED", (
        "the parent request is FULFILLED in the same instant"
    )


def test_collateral_delete_not_present(api):
    """PRD §3.5: "a "DELETE" operation removes the supplied text as a substring of the
    root's `collateral_text`, and if that text is not present the acceptance fails
    with `ERR_COLLATERAL_NOT_PRESENT`".

    Design: Corner/validations/collateral_delete_not_present
    """
    ctx = setup_active_initial_filing()
    root_id = ctx["filing"]["id"]
    amendment = create_ucc3_request(
        "AMENDMENT", ctx["client"], ctx["debtor"], ctx["secured_party"], root_id)
    submit_intake(amendment["id"], user_id="spec-1")
    approve_preparation(amendment["id"])
    attempt = create_draft_attempt(
        amendment["id"],
        debtor_name_on_filing="Acme Manufacturing, Inc.",
        amendment_scope="COLLATERAL", collateral_change_op="DELETE",
        collateral_text="All inventory stored at 200 Dock Street")
    submit_attempt(attempt["id"])
    resp = api.record_acceptance(
        attempt["id"],
        {"filing_number": "CA-2026-0010", "filed_at": "2026-08-01T00:00:00Z"},
        OFFICER,
    )
    validate_error(resp, ApiErrorId.ERR_COLLATERAL_NOT_PRESENT)
    root = get_filing(root_id)
    assert root["collateral_text"] == (
        "All manufacturing equipment located at 100 Industrial Way"
    ), "a failed DELETE acceptance must leave the root collateral unchanged"
    assert get_filing(attempt["id"])["effectiveness_status"] == "SUBMITTED"


def test_filed_at_before_submitted_rejected(api):
    """PRD §3.5: "`filed_at` must be no earlier than the attempt's `submitted_at` and
    no later than the current instant — both boundaries inclusive — or acceptance
    fails with `ERR_INVALID_FILED_AT`."

    Design: Corner/validations/filed_at_before_submitted_rejected
    """
    world = setup_client_world()
    request = create_ready_request(world["client"], world["debtor"], world["secured_party"])
    attempt = create_draft_attempt(request["id"])
    submit_attempt(attempt["id"])  # submitted_at == 2026-08-01T00:00:00Z
    resp = api.record_acceptance(
        attempt["id"],
        {"filing_number": "CA-2026-0001", "filed_at": "2026-07-31T23:59:59Z"},
        OFFICER,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_FILED_AT)
    assert get_filing(attempt["id"])["effectiveness_status"] == "SUBMITTED"


def test_continuation_extends_from_prior_expiration(api):
    """PRD §3.5: "- **`CONTINUATION`.** The root's effectiveness is extended by reading
    the root's currently stored `expiration_at`, adding sixty calendar months to that
    stored value, and persisting the result — the continuation's own `filed_at` is
    never the anchor, because a continuation extends from the date the filing would
    have lapsed, not from when it was filed."

    Design: Difficulty/combinatorial_formula/continuation_expiration_anchored_to_prior_expiration
    """
    ctx = _setup_root_with_submitted_continuation()
    set_clock_to("2030-12-01T00:00:00Z")  # inside the window 2030-09-10 .. 2031-03-10
    accepted = accept_attempt(ctx["continuation_attempt"]["id"],
                              filing_number="CA-2030-9001",
                              filed_at="2030-12-01T00:00:00Z")
    assert accepted["effectiveness_status"] == "ACTIVE"
    root = get_filing(ctx["root"]["id"])
    # 2031-03-10 stored + 60 months = 2036-03-10; anchoring to filed_at (2030-12-01)
    # would wrongly give 2035-12-01.
    assert root["expiration_at"] == "2036-03-10T00:00:00Z", (
        f"continuation must extend from the stored expiration, got {root['expiration_at']}"
    )
    assert root["expiration_at"] != "2035-12-01T00:00:00Z"
    assert root["effectiveness_status"] == "ACTIVE"
    assert get_request(ctx["continuation_request"]["id"])["status"] == "FULFILLED"


def test_continuation_appends_continued_event_and_bumps_root(api):
    """PRD §3.5: "The root receives a `CONTINUED` event and a `version` increment".
    PRD §3.5: "In all cases the parent request moves `IN_PROCESS` → `FULFILLED`; when
    the request kind is not `NEW_UCC1`, fulfillment also decreases the target root's
    `open_ucc3_request_count` by one and increments the root's `version` by one."

    Design: Difficulty/combinatorial_formula/continuation_expiration_anchored_to_prior_expiration
    """
    ctx = _setup_root_with_submitted_continuation()
    set_clock_to("2030-12-01T00:00:00Z")
    version_before = get_filing(ctx["root"]["id"])["version"]
    accept_attempt(ctx["continuation_attempt"]["id"],
                   filing_number="CA-2030-9001", filed_at="2030-12-01T00:00:00Z")
    root = get_filing(ctx["root"]["id"])
    event_types = [e["event_type"] for e in list_filing_events(root["id"])]
    assert "CONTINUED" in event_types, f"root must carry a CONTINUED event, got {event_types}"
    assert root["version"] > version_before, "continuation increments the root's version"
    assert root["open_ucc3_request_count"] == 0, (
        "fulfillment of the continuation request decrements the open count back to 0"
    )


def test_continuation_window_open_inclusive(api):
    """PRD §3.5: "For a `CONTINUATION`, the supplied `filed_at` must fall inside the
    continuation window: the window opens exactly six calendar months before the
    root's currently stored `expiration_at` and closes at that expiration, with the
    lower bound inclusive and the upper bound exclusive; a `filed_at` outside it is
    rejected with `ERR_CONTINUATION_OUTSIDE_WINDOW`."

    Design: Difficulty/boundary_precision_check/continuation_window_open_inclusive
    """
    ctx = _setup_root_with_submitted_continuation(filed_at="2026-03-10T00:00:00Z")
    # Window opens exactly 2030-09-10T00:00:00Z (expiration 2031-03-10 minus 6 months).
    set_clock_to("2030-09-10T00:00:00Z")
    accepted = accept_attempt(ctx["continuation_attempt"]["id"],
                              filing_number="CA-2030-9001",
                              filed_at="2030-09-10T00:00:00Z")
    assert accepted["effectiveness_status"] == "ACTIVE", (
        "filed_at exactly at the window open is inside (lower bound inclusive)"
    )
    assert get_filing(ctx["root"]["id"])["expiration_at"] == "2036-03-10T00:00:00Z"


def test_continuation_one_second_before_window_open_rejected(api):
    """PRD §3.5: "the window opens exactly six calendar months before the root's
    currently stored `expiration_at` and closes at that expiration, with the lower
    bound inclusive and the upper bound exclusive; a `filed_at` outside it is rejected
    with `ERR_CONTINUATION_OUTSIDE_WINDOW`."

    Design: Difficulty/boundary_precision_check/continuation_window_open_inclusive
    """
    ctx = _setup_root_with_submitted_continuation(filed_at="2026-03-10T00:00:00Z")
    set_clock_to("2030-09-10T00:00:00Z")
    resp = api.record_acceptance(
        ctx["continuation_attempt"]["id"],
        {"filing_number": "CA-2030-9002", "filed_at": "2030-09-09T23:59:59Z"},
        OFFICER,
    )
    validate_error(resp, ApiErrorId.ERR_CONTINUATION_OUTSIDE_WINDOW)
    assert get_filing(ctx["continuation_attempt"]["id"])["effectiveness_status"] == "SUBMITTED", (
        "a rejected acceptance leaves the attempt in place"
    )
    assert get_filing(ctx["root"]["id"])["expiration_at"] == "2031-03-10T00:00:00Z", (
        "the root's expiration is unchanged by a rejected continuation"
    )


def test_overlapping_active_initial_filing_rejected(api):
    """PRD §3.5: "For an `INITIAL` filing, no other `INITIAL` filing for the same
    `debtor_id`, `jurisdiction_code`, and `filing_office` may currently be `ACTIVE`;
    effectiveness runs from `filed_at` up to but not including `expiration_at`, so
    `LAPSED` or `TERMINATED` filings free the slot, while a live overlap is rejected
    with `ERR_OVERLAPPING_ACTIVE_FILING`."

    Design: Difficulty/resource_temporal_overlap/perfection_slot_overlap_half_open_with_truncation
    """
    ctx = setup_active_initial_filing(filed_at="2026-08-01T00:00:00Z",
                                      filing_number="CA-2026-0001")
    second_request = create_ready_request(ctx["client"], ctx["debtor"],
                                          ctx["secured_party"])
    second = create_draft_attempt(
        second_request["id"], collateral_text="All inventory and equipment of debtor")
    submit_attempt(second["id"])
    resp = api.record_acceptance(
        second["id"],
        {"filing_number": "CA-2026-0002", "filed_at": "2026-08-01T00:00:00Z"},
        OFFICER,
    )
    validate_error(resp, ApiErrorId.ERR_OVERLAPPING_ACTIVE_FILING)
    assert get_filing(second["id"])["effectiveness_status"] == "SUBMITTED", (
        "the overlapping acceptance leaves the second attempt SUBMITTED"
    )


def test_slot_freed_after_termination_allows_retry(api):
    """PRD §3.5: "effectiveness runs from `filed_at` up to but not including
    `expiration_at`, so `LAPSED` or `TERMINATED` filings free the slot, while a live
    overlap is rejected with `ERR_OVERLAPPING_ACTIVE_FILING`."
    PRD §3.5: "A successful acceptance stores `filing_number` and `filed_at`, moves the
    attempt `SUBMITTED` → `ACTIVE`, and appends an `ACCEPTED` event."

    Design: Difficulty/resource_temporal_overlap/perfection_slot_overlap_half_open_with_truncation
    """
    ctx = setup_active_initial_filing(filed_at="2026-08-01T00:00:00Z",
                                      filing_number="CA-2026-0001")
    root_id = ctx["filing"]["id"]
    second_request = create_ready_request(ctx["client"], ctx["debtor"],
                                          ctx["secured_party"])
    second = create_draft_attempt(
        second_request["id"], collateral_text="All inventory and equipment of debtor")
    submit_attempt(second["id"])
    resp = api.record_acceptance(
        second["id"],
        {"filing_number": "CA-2026-0002", "filed_at": "2026-08-01T00:00:00Z"},
        OFFICER,
    )
    validate_error(resp, ApiErrorId.ERR_OVERLAPPING_ACTIVE_FILING)
    # Truncate the slot early: terminate the root, then retry the same acceptance.
    termination = create_ucc3_request(
        "TERMINATION", ctx["client"], ctx["debtor"], ctx["secured_party"], root_id)
    submit_intake(termination["id"], user_id="spec-1")
    approve_preparation(termination["id"])
    term_attempt = create_draft_attempt(
        termination["id"], debtor_name_on_filing="Acme Manufacturing, Inc.",
        collateral_text=None)
    submit_attempt(term_attempt["id"])
    accept_attempt(term_attempt["id"], filing_number="CA-2026-0009",
                   filed_at="2026-08-01T00:00:00Z")
    assert get_filing(root_id)["effectiveness_status"] == "TERMINATED", (
        "termination truncates the effectiveness interval early"
    )
    retried = accept_attempt(second["id"], filing_number="CA-2026-0002",
                             filed_at="2026-08-01T00:00:00Z")
    assert retried["effectiveness_status"] == "ACTIVE", (
        "the freed slot accepts the previously rejected attempt"
    )
    assert retried["filing_number"] == "CA-2026-0002"


def _setup_root_with_submitted_continuation(filed_at="2026-03-10T00:00:00Z"):
    """Root INITIAL filed 2026-03-10 (expiration 2031-03-10); a CONTINUATION request
    against it taken to READY with its attempt SUBMITTED. The continuation attempt is
    created while the clock sits inside the continuation window."""
    set_clock_to(filed_at)
    ctx = setup_active_initial_filing(filed_at=filed_at, filing_number="CA-2026-0001")
    # Set up the continuation just before the window opens so the boundary filed_at
    # values remain within [submitted_at, now] when the acceptance is recorded.
    set_clock_to("2030-09-09T00:00:00Z")
    continuation = create_ucc3_request(
        "CONTINUATION", ctx["client"], ctx["debtor"], ctx["secured_party"],
        ctx["filing"]["id"])
    submit_intake(continuation["id"], user_id="spec-1")
    approve_preparation(continuation["id"])
    attempt = create_draft_attempt(
        continuation["id"], debtor_name_on_filing="Acme Manufacturing, Inc.",
        collateral_text=None)
    submit_attempt(attempt["id"])
    ctx["root"] = ctx["filing"]
    ctx["continuation_request"] = continuation
    ctx["continuation_attempt"] = attempt
    return ctx
