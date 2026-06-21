"""State-machine claims: permit revision cycle, cross-entity state gates,
precondition enforcement, terminal lockdown, invalid transitions, the
estimate redraft loop, and the accept supersede side effect
(PRD §3.3, §3.5, §3.6, §3.7, §3.9, §3.10).

Difficulty: non_linear_state_machine (permit cycle), cross_entity_state_dependency.
Corner: state_machines section.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_error_is_one_of,
    api_client,
    ApiErrorId,
    create_service_area,
    create_work_order,
    add_tree,
    assess,
    create_estimate,
    add_line_item,
    issue_estimate,
    accept_estimate,
    create_permit,
    submit_permit,
    decide_permit,
    create_crew,
    create_booking,
    setup_scheduled_with_crew,
    setup_permit_work_order_under_review,
    TEST_USERS,
    make_client_headers,
)


# ─── non_linear_state_machine / permit_revision_cycle ───


def test_permit_revision_cycle_bumps_count_each_round(api):
    """PRD §3.6: "Requesting changes sends the permit from `UNDER_REVIEW` back
    to `CHANGES_REQUESTED` and increments its `revision_count` by one; the
    permit may then be resubmitted, looping `UNDER_REVIEW` →
    `CHANGES_REQUESTED` → `UNDER_REVIEW` any number of times, each round-trip
    bumping `revision_count`."

    Design: Difficulty/non_linear_state_machine/permit_revision_cycle_under_review_changes_requested
    """
    area = create_service_area(disposal_fee_cents_per_ton=8000, requires_permit_authority=True)
    wo = create_work_order(area["id"], pricing_mode="PER_JOB")
    add_tree(wo["id"], species="Oak", dbh_inches=30, is_protected=True)
    assess(wo["id"])
    permit = create_permit(wo["id"], authority_ref="PRM-001")
    submit_permit(wo["id"], permit["id"])
    # cycle 1
    api.request_permit_changes(wo["id"], permit["id"], TEST_USERS["dispatcher_headers"])
    submit_permit(wo["id"], permit["id"])
    # cycle 2
    api.request_permit_changes(wo["id"], permit["id"], TEST_USERS["dispatcher_headers"])
    final = validate_success(api.submit_permit(wo["id"], permit["id"],
                                               TEST_USERS["arborist_headers"]), 200)
    assert final["revision_count"] == 2
    assert final["status"] == "UNDER_REVIEW"


def test_permit_submit_from_changes_requested_returns_under_review(api):
    """PRD §3.6: "Submitting a permit advances it to `UNDER_REVIEW`, whether
    from the initial `DRAFT` or from a later `CHANGES_REQUESTED` state"

    Design: Difficulty/non_linear_state_machine/permit_revision_cycle_under_review_changes_requested
    """
    area = create_service_area(disposal_fee_cents_per_ton=8000, requires_permit_authority=True)
    wo = create_work_order(area["id"], pricing_mode="PER_JOB")
    add_tree(wo["id"], species="Oak", dbh_inches=30, is_protected=True)
    assess(wo["id"])
    permit = create_permit(wo["id"], authority_ref="PRM-002")
    submit_permit(wo["id"], permit["id"])
    changed = validate_success(
        api.request_permit_changes(wo["id"], permit["id"],
                                   TEST_USERS["dispatcher_headers"]), 200,
    )
    assert changed["status"] == "CHANGES_REQUESTED"
    assert changed["revision_count"] == 1
    resubmitted = validate_success(
        api.submit_permit(wo["id"], permit["id"], TEST_USERS["arborist_headers"]), 200,
    )
    assert resubmitted["status"] == "UNDER_REVIEW"
    assert resubmitted["revision_count"] == 1


# ─── cross_entity_state_dependency / estimate_accept_requires_approved_permit ───


def test_accept_blocked_until_permit_approved(api):
    """PRD §3.7: "Before that happens, two guards run in order. First, if the
    work order `requires_permit`, an `APPROVED` permit must already exist on
    it; absent one, acceptance is refused with `ERR_PERMIT_REQUIRED`, and this
    gate is checked at priority 10 — ahead of ownership."

    Design: Difficulty/cross_entity_state_dependency/estimate_accept_requires_approved_permit
    """
    area, wo, tree, est, permit = setup_permit_work_order_under_review()
    blocked = api.accept_estimate(wo["id"], est["id"], make_client_headers("client-1"))
    validate_error(blocked, ApiErrorId.ERR_PERMIT_REQUIRED.value)


def test_accept_succeeds_after_permit_approved(api):
    """PRD §3.6: "a value of APPROVE drives `UNDER_REVIEW` → `APPROVED`"
    PRD §3.7: "When acceptance succeeds, the estimate moves `ISSUED` →
    `ACCEPTED`, the work order's `accepted_estimate_id` is set to that
    estimate, every other estimate on the work order still in `ISSUED` is
    superseded to `SUPERSEDED`, the work order advances `QUOTED` →
    `SCHEDULED`, and the work order's `version` increments by one."

    Design: Difficulty/cross_entity_state_dependency/estimate_accept_requires_approved_permit
    """
    area, wo, tree, est, permit = setup_permit_work_order_under_review()
    approved = decide_permit(wo["id"], permit["id"], "APPROVE")
    assert approved["status"] == "APPROVED"
    accepted = validate_success(
        api.accept_estimate(wo["id"], est["id"], make_client_headers("client-1")), 200,
    )
    assert accepted["status"] == "ACCEPTED"
    wo_after = validate_success(
        api.get_work_order(wo["id"], TEST_USERS["dispatcher_headers"]), 200,
    )
    assert wo_after["status"] == "SCHEDULED"


# ─── cross_entity_state_dependency / booking_finalize_requires_work_order_scheduled ───


def test_booking_finalize_rejected_after_work_order_cancelled(api):
    """PRD §3.9: "Finalization is permitted only while the work order is
    `SCHEDULED` (otherwise `ERR_WORK_ORDER_NOT_SCHEDULED`) and only on a
    booking still `RESERVED` (otherwise `ERR_BOOKING_NOT_RESERVED`)"
    PRD §3.10: "every `RESERVED` booking is released, freeing that resource's
    calendar window"

    Design: Difficulty/cross_entity_state_dependency/booking_finalize_requires_work_order_scheduled
    """
    area, wo, tree, est, crew = setup_scheduled_with_crew()
    bk = create_booking(
        wo["id"], "CREW", crew_id=crew["id"],
        start_at="2026-07-14T09:00:00Z", end_at="2026-07-14T17:00:00Z",
    )
    cancelled = validate_success(
        api.cancel_work_order(wo["id"], TEST_USERS["dispatcher_headers"]), 200,
    )
    assert cancelled["status"] == "CANCELLED"
    bk_after = validate_success(
        api.get_booking(bk["id"], TEST_USERS["dispatcher_headers"]), 200,
    )
    assert bk_after["status"] == "RELEASED"
    res = api.finalize_booking(bk["id"], {"actual_hours": 6},
                               TEST_USERS["dispatcher_headers"])
    # Booking is no longer RESERVED (released by cancel) and the work order is
    # not SCHEDULED; PRD §3.9 names both guards on finalize without pinning
    # which fires first when both fail, so either error_id is PRD-faithful.
    validate_error_is_one_of(res, [
        ApiErrorId.ERR_BOOKING_NOT_RESERVED.value,
        ApiErrorId.ERR_WORK_ORDER_NOT_SCHEDULED.value,
    ])


def test_booking_finalize_on_unscheduled_work_order_state_check(api):
    """PRD §3.9: "Finalization is permitted only while the work order is
    `SCHEDULED` (otherwise `ERR_WORK_ORDER_NOT_SCHEDULED`) and only on a
    booking still `RESERVED` (otherwise `ERR_BOOKING_NOT_RESERVED`)"

    Design: Difficulty/cross_entity_state_dependency/booking_finalize_requires_work_order_scheduled
    """
    area, wo, tree, est, crew = setup_scheduled_with_crew()
    bk = create_booking(
        wo["id"], "CREW", crew_id=crew["id"],
        start_at="2026-07-15T09:00:00Z", end_at="2026-07-15T17:00:00Z",
    )
    api.cancel_work_order(wo["id"], TEST_USERS["dispatcher_headers"])
    res = api.finalize_booking(bk["id"], {"actual_hours": 6},
                               TEST_USERS["dispatcher_headers"])
    # The booking was RELEASED and the work order CANCELLED by the cancel
    # cascade; PRD §3.9 names both guards (ERR_WORK_ORDER_NOT_SCHEDULED and
    # ERR_BOOKING_NOT_RESERVED) without pinning their relative precedence, so
    # either is PRD-faithful when both conditions hold.
    validate_error_is_one_of(res, [
        ApiErrorId.ERR_BOOKING_NOT_RESERVED.value,
        ApiErrorId.ERR_WORK_ORDER_NOT_SCHEDULED.value,
    ])


# ─── Corner / state_machines ────────────────────────────


def test_assess_with_no_trees_rejected(api):
    """PRD §3.3: "The assessment refuses to run if the work order has no tree
    assets at all, returning `ERR_NO_TREES_ASSESSED`."

    Design: Corner/state_machines/assess_with_no_trees_rejected
    """
    area = create_service_area(disposal_fee_cents_per_ton=8000)
    wo = create_work_order(area["id"], pricing_mode="PER_JOB")
    res = api.assess_work_order(wo["id"], TEST_USERS["arborist_headers"])
    validate_error(res, ApiErrorId.ERR_NO_TREES_ASSESSED.value)
    wo_after = validate_success(
        api.get_work_order(wo["id"], TEST_USERS["dispatcher_headers"]), 200,
    )
    assert wo_after["status"] == "DRAFT"


def test_issue_empty_estimate_rejected(api):
    """PRD §3.5: "Issuance is refused if the estimate holds no line items,
    returning `ERR_ESTIMATE_EMPTY`"

    Design: Corner/state_machines/issue_empty_estimate_rejected
    """
    area = create_service_area(disposal_fee_cents_per_ton=8000)
    wo = create_work_order(area["id"], pricing_mode="PER_JOB")
    add_tree(wo["id"], species="Pine", dbh_inches=12)
    assess(wo["id"])
    est = create_estimate(wo["id"])
    res = api.issue_estimate(wo["id"], est["id"], TEST_USERS["arborist_headers"])
    validate_error(res, ApiErrorId.ERR_ESTIMATE_EMPTY.value)


def test_cancel_completed_work_order_returns_terminal(api):
    """PRD §3.10: "A cancel against an already-terminal work order is refused
    with `ERR_WORK_ORDER_TERMINAL`."

    Design: Corner/state_machines/cancel_already_completed_returns_terminal
    """
    area = create_service_area(disposal_fee_cents_per_ton=8000)
    wo = create_work_order(area["id"], pricing_mode="HOURLY")
    tree = add_tree(wo["id"], species="Pine", dbh_inches=12)
    assess(wo["id"])
    est = create_estimate(wo["id"])
    add_line_item(est["id"], service_type="REMOVAL", quantity=1, tree_asset_id=tree["id"])
    issue_estimate(wo["id"], est["id"])
    accept_estimate(wo["id"], est["id"])
    validate_success(api.complete_work_order(wo["id"], TEST_USERS["dispatcher_headers"]), 200)
    res = api.cancel_work_order(wo["id"], TEST_USERS["dispatcher_headers"])
    validate_error(res, ApiErrorId.ERR_WORK_ORDER_TERMINAL.value)
    wo_after = validate_success(
        api.get_work_order(wo["id"], TEST_USERS["dispatcher_headers"]), 200,
    )
    assert wo_after["status"] == "COMPLETED"


def test_accept_draft_estimate_rejected_not_issued(api):
    """PRD §3.7: "Acceptance is also refused with `ERR_ESTIMATE_NOT_ISSUED` if
    the target estimate is not in `ISSUED`."

    Design: Corner/state_machines/accept_estimate_not_issued_rejected
    """
    area = create_service_area(disposal_fee_cents_per_ton=8000)
    wo = create_work_order(area["id"], pricing_mode="PER_JOB")
    tree = add_tree(wo["id"], species="Pine", dbh_inches=12)
    assess(wo["id"])
    est = create_estimate(wo["id"])
    add_line_item(est["id"], service_type="REMOVAL", quantity=1, tree_asset_id=tree["id"])
    res = api.accept_estimate(wo["id"], est["id"], make_client_headers("client-1"))
    validate_error(res, ApiErrorId.ERR_ESTIMATE_NOT_ISSUED.value)


def test_permit_submit_when_not_required_rejected(api):
    """PRD §3.6: "submission is only allowed when the work order actually
    `requires_permit`, and a submit against a work order that does not require
    one is refused with `ERR_PERMIT_NOT_REQUIRED`."

    Design: Corner/state_machines/permit_submit_when_not_required_rejected
    """
    area = create_service_area(disposal_fee_cents_per_ton=8000, requires_permit_authority=True)
    wo = create_work_order(area["id"], pricing_mode="PER_JOB")
    add_tree(wo["id"], species="Pine", dbh_inches=12)   # non-protected
    assess(wo["id"])
    permit = create_permit(wo["id"], authority_ref="PRM-X")
    res = api.submit_permit(wo["id"], permit["id"], TEST_USERS["arborist_headers"])
    validate_error(res, ApiErrorId.ERR_PERMIT_NOT_REQUIRED.value)


def test_request_changes_on_denied_permit_invalid_transition(api):
    """PRD §3.6: "Both `APPROVED` and `DENIED` are terminal." PRD §3.10:
    "Where a transition is requested that is not legal from the resource's
    current state and no more specific state error applies, the system
    responds with `ERR_INVALID_STATE_TRANSITION`."

    Design: Corner/state_machines/permit_deny_terminal_lockdown
    """
    area = create_service_area(disposal_fee_cents_per_ton=8000, requires_permit_authority=True)
    wo = create_work_order(area["id"], pricing_mode="PER_JOB")
    add_tree(wo["id"], species="Oak", dbh_inches=30, is_protected=True)
    assess(wo["id"])
    permit = create_permit(wo["id"], authority_ref="PRM-D")
    submit_permit(wo["id"], permit["id"])
    decide_permit(wo["id"], permit["id"], "DENY")
    res = api.request_permit_changes(wo["id"], permit["id"], TEST_USERS["dispatcher_headers"])
    validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value)
    permit_after = validate_success(
        api.get_permit(wo["id"], permit["id"], TEST_USERS["dispatcher_headers"]), 200,
    )
    assert permit_after["status"] == "DENIED"


def test_complete_with_open_reserved_booking_rejected(api):
    """PRD §3.10: "Completing the work order moves it `SCHEDULED` →
    `COMPLETED`, but only when no booking on it is still `RESERVED` (every
    booking must be `FINALIZED` or `RELEASED`, otherwise `ERR_OPEN_BOOKINGS`)"

    Design: Corner/state_machines/complete_with_open_reserved_booking_rejected
    """
    area, wo, tree, est, crew = setup_scheduled_with_crew()
    create_booking(
        wo["id"], "CREW", crew_id=crew["id"],
        start_at="2026-09-01T09:00:00Z", end_at="2026-09-01T12:00:00Z",
    )
    res = api.complete_work_order(wo["id"], TEST_USERS["dispatcher_headers"])
    validate_error(res, ApiErrorId.ERR_OPEN_BOOKINGS.value)
    wo_after = validate_success(
        api.get_work_order(wo["id"], TEST_USERS["dispatcher_headers"]), 200,
    )
    assert wo_after["status"] == "SCHEDULED"


def test_accept_supersedes_sibling_issued_estimate(api):
    """PRD §3.7: "every other estimate on the work order still in `ISSUED` is
    superseded to `SUPERSEDED`, the work order advances `QUOTED` →
    `SCHEDULED`" PRD §2.5: "When an estimate is accepted, every other estimate
    on that work order that is still `ISSUED` is superseded as a side effect."

    Design: Corner/state_machines/accept_supersedes_sibling_issued_estimate
    """
    area = create_service_area(disposal_fee_cents_per_ton=8000)
    wo = create_work_order(area["id"], pricing_mode="PER_JOB")
    tree = add_tree(wo["id"], species="Pine", dbh_inches=12)
    assess(wo["id"])
    e1 = create_estimate(wo["id"])
    add_line_item(e1["id"], service_type="REMOVAL", quantity=1, tree_asset_id=tree["id"])
    issue_estimate(wo["id"], e1["id"])
    e2 = create_estimate(wo["id"])
    add_line_item(e2["id"], service_type="REMOVAL", quantity=1, tree_asset_id=tree["id"])
    issue_estimate(wo["id"], e2["id"])
    accepted = validate_success(
        api.accept_estimate(wo["id"], e1["id"], make_client_headers("client-1")), 200,
    )
    assert accepted["status"] == "ACCEPTED"
    e2_after = validate_success(
        api.get_estimate(wo["id"], e2["id"], TEST_USERS["arborist_headers"]), 200,
    )
    assert e2_after["status"] == "SUPERSEDED"
    wo_after = validate_success(
        api.get_work_order(wo["id"], TEST_USERS["dispatcher_headers"]), 200,
    )
    assert wo_after["accepted_estimate_id"] == e1["id"]
    assert wo_after["status"] == "SCHEDULED"


def test_decline_then_redraft_keeps_work_order_quoted(api):
    """PRD §3.7: "A decline does not drag the work order backward: it stays in
    `QUOTED`, so the arborist may draft a fresh estimate and issue it again,
    redrafting as many times as needed until the client accepts one."

    Design: Corner/state_machines/decline_then_redraft_keeps_work_order_quoted
    """
    area = create_service_area(disposal_fee_cents_per_ton=8000)
    wo = create_work_order(area["id"], pricing_mode="PER_JOB")
    tree = add_tree(wo["id"], species="Pine", dbh_inches=12)
    assess(wo["id"])
    e1 = create_estimate(wo["id"])
    add_line_item(e1["id"], service_type="REMOVAL", quantity=1, tree_asset_id=tree["id"])
    issue_estimate(wo["id"], e1["id"])
    declined = validate_success(
        api.decline_estimate(wo["id"], e1["id"], make_client_headers("client-1")), 200,
    )
    assert declined["status"] == "DECLINED"
    wo_mid = validate_success(
        api.get_work_order(wo["id"], TEST_USERS["dispatcher_headers"]), 200,
    )
    assert wo_mid["status"] == "QUOTED"
    e2 = create_estimate(wo["id"])
    add_line_item(e2["id"], service_type="REMOVAL", quantity=1, tree_asset_id=tree["id"])
    e2_issued = issue_estimate(wo["id"], e2["id"])
    assert e2_issued["status"] == "ISSUED"
