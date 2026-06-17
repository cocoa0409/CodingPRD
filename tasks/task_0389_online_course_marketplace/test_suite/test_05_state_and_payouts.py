"""State-eligibility precedence, cross-entity state dependencies, the retire cascade,
and the payout / bundle optimistic-concurrency checks (PRD §2.10, §2.11, §3.3, §3.11).

Queue A: priority_pair_validation_conflict (state beats refund-window / insufficient-
balance), cross_entity_state_dependency (retire blocked by active enrollment; approve
blocked by balance), transitive_cascade (retire -> bundle RETIRED). Queue B: payout OCC
success and stale rejection, bundle-enroll stale rejection, course state-machine corners.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_error_is_one_of,
    ApiErrorId,
    set_clock,
    create_instructor,
    create_learner,
    create_published_course,
    create_draft_course,
    add_lesson,
    publish_course,
    create_bundle_of_published_courses,
    create_bundle,
    enroll_in_course,
    request_payout,
    make_instructor_headers,
    make_learner_headers,
    make_admin_headers,
    create_payout_payload,
    approve_payout_payload,
    enroll_bundle_payload,
)


# ===========================================================================
# Queue A — priority_pair_validation_conflict / refund_invalid_state_beats_refund_window_closed
# ===========================================================================
def test_refund_on_refunded_enrollment_returns_invalid_state_not_window_closed(api):
    """PRD §2.11: "State eligibility comes fourth: a target resource that is not in a
    state permitting the requested transition fails with `ERR_INVALID_STATE` (409). Domain
    business rules ... are evaluated after those four, each carrying its own specific
    error."

    A second refund on an already-REFUNDED enrollment, after the clock has also passed the
    refund deadline, triggers both the state check (p4) and the window check (p8); the
    higher-priority state check wins with ERR_INVALID_STATE.

    Design: Difficulty/priority_pair_validation_conflict/refund_invalid_state_beats_refund_window_closed
    """
    set_clock("2026-06-01T00:00:00Z")
    instructor = create_instructor(revenue_share_pct=0.50)
    learner = create_learner()
    course, _ = create_published_course(instructor["id"], list_price_cents=1000,
                                        refund_window_days=5)
    enrollment = enroll_in_course(learner["id"], course["id"])
    validate_success(
        api.refund_enrollment(enrollment["id"], make_learner_headers(learner["id"])), 200
    )
    set_clock("2026-07-01T00:00:00Z")  # well past the deadline 2026-06-06
    res = api.refund_enrollment(enrollment["id"], make_learner_headers(learner["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


def test_refund_on_refunded_enrollment_inside_window_still_invalid_state(api):
    """PRD §2.11: "State eligibility comes fourth: a target resource that is not in a
    state permitting the requested transition fails with `ERR_INVALID_STATE` (409)."

    A second refund on an already-REFUNDED enrollment while the clock is still inside the
    refund window (so the temporal check could not fire) is still rejected on the state
    check with ERR_INVALID_STATE — isolating the higher-priority path.

    Design: Difficulty/priority_pair_validation_conflict/refund_invalid_state_beats_refund_window_closed
    """
    set_clock("2026-06-01T00:00:00Z")
    instructor = create_instructor(revenue_share_pct=0.50)
    learner = create_learner()
    course, _ = create_published_course(instructor["id"], list_price_cents=1000,
                                        refund_window_days=30)
    enrollment = enroll_in_course(learner["id"], course["id"])
    validate_success(
        api.refund_enrollment(enrollment["id"], make_learner_headers(learner["id"])), 200
    )
    set_clock("2026-06-05T00:00:00Z")  # still strictly before the deadline 2026-07-01
    res = api.refund_enrollment(enrollment["id"], make_learner_headers(learner["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Queue A — priority_pair_validation_conflict / payout_invalid_state_beats_insufficient_balance
# ===========================================================================
def test_approve_rejected_payout_returns_invalid_state_not_insufficient_balance(api):
    """PRD §2.11: "State eligibility comes fourth: a target resource that is not in a
    state permitting the requested transition fails with `ERR_INVALID_STATE` (409). Domain
    business rules ... are evaluated after those four, each carrying its own specific
    error."

    Approving an already-REJECTED payout triggers the state-eligibility check (p4) before
    the insufficient-balance business rule (p9); the higher-priority state check wins with
    ERR_INVALID_STATE. A payout can only be requested while the instructor's balance is at
    least 1 (PRD §3.11), so the instructor is first funded by a window-expiry flip; the
    state check still preempts the balance rule on the REJECTED payout regardless of the
    balance value.

    Design: Difficulty/priority_pair_validation_conflict/payout_invalid_state_beats_insufficient_balance
    """
    set_clock("2026-06-01T00:00:00Z")
    instructor = create_instructor(revenue_share_pct=0.50)
    learner = create_learner()
    course, _ = create_published_course(instructor["id"], list_price_cents=4000,
                                        refund_window_days=5)
    enrollment = enroll_in_course(learner["id"], course["id"])
    set_clock("2026-06-10T00:00:00Z")
    validate_success(
        api.get_enrollment(enrollment["id"], make_learner_headers(learner["id"])), 200
    )  # window-expiry flip makes 2000c payable
    payout = validate_success(
        api.create_payout(create_payout_payload(instructor["id"], 500),
                          make_instructor_headers(instructor["id"])), 201,
    )
    validate_success(api.reject_payout(payout["id"], make_admin_headers()), 200)
    inst = validate_success(
        api.get_instructor(instructor["id"], make_instructor_headers(instructor["id"])), 200
    )
    res = api.approve_payout(
        payout["id"], approve_payout_payload(inst["version"]), make_admin_headers()
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


def test_approve_rejected_payout_invalid_state_even_with_positive_balance(api):
    """PRD §2.11: "State eligibility comes fourth: a target resource that is not in a
    state permitting the requested transition fails with `ERR_INVALID_STATE` (409). Domain
    business rules ... are evaluated after those four".

    Approving an already-REJECTED payout when the instructor has a positive payable
    balance (so the insufficient-balance check could not fire) is still rejected on the
    state check with ERR_INVALID_STATE — isolating the higher-priority path.

    Design: Difficulty/priority_pair_validation_conflict/payout_invalid_state_beats_insufficient_balance
    """
    set_clock("2026-06-01T00:00:00Z")
    instructor = create_instructor(revenue_share_pct=0.50)
    learner = create_learner()
    course, _ = create_published_course(instructor["id"], list_price_cents=4000,
                                        refund_window_days=5)
    enrollment = enroll_in_course(learner["id"], course["id"])
    set_clock("2026-06-10T00:00:00Z")
    validate_success(
        api.get_enrollment(enrollment["id"], make_learner_headers(learner["id"])), 200
    )  # window-expiry flip makes 2000c payable
    payout = validate_success(
        api.create_payout(create_payout_payload(instructor["id"], 500),
                          make_instructor_headers(instructor["id"])), 201,
    )
    validate_success(api.reject_payout(payout["id"], make_admin_headers()), 200)
    inst = validate_success(
        api.get_instructor(instructor["id"], make_instructor_headers(instructor["id"])), 200
    )
    assert inst["payout_balance_cents"] >= 1, "precondition: positive payable balance"
    res = api.approve_payout(
        payout["id"], approve_payout_payload(inst["version"]), make_admin_headers()
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Queue A — cross_entity_state_dependency / course_retire_blocked_by_active_enrollment
# ===========================================================================
def test_retire_blocked_by_active_child_enrollment(api):
    """PRD §3.3: "An instructor may retire a course from either `PUBLISHED` or
    `UNPUBLISHED` status, but only when the course has no enrollment still in `ACTIVE`
    status; if any active enrollment remains, the retire is rejected with
    `ERR_INVALID_STATE`."

    A PUBLISHED course with one ACTIVE enrollment cannot be retired.

    Design: Difficulty/cross_entity_state_dependency/course_retire_blocked_by_active_enrollment
    """
    set_clock("2026-06-01T00:00:00Z")
    instructor = create_instructor(revenue_share_pct=0.50)
    learner = create_learner()
    course, _ = create_published_course(instructor["id"], list_price_cents=1000,
                                        refund_window_days=30)
    enroll_in_course(learner["id"], course["id"])
    res = api.retire_course(course["id"], make_instructor_headers(instructor["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


def test_retire_succeeds_once_no_active_enrollment_remains(api):
    """PRD §3.3: "An instructor may retire a course from either `PUBLISHED` or
    `UNPUBLISHED` status, but only when the course has no enrollment still in `ACTIVE`
    status".

    The same course becomes retirable once its sole ACTIVE enrollment is refunded away
    (leaving it REFUNDED, not ACTIVE) — the transition's validity flips with the child
    enrollment's state.

    Design: Difficulty/cross_entity_state_dependency/course_retire_blocked_by_active_enrollment
    """
    set_clock("2026-06-01T00:00:00Z")
    instructor = create_instructor(revenue_share_pct=0.50)
    learner = create_learner()
    course, _ = create_published_course(instructor["id"], list_price_cents=1000,
                                        refund_window_days=30)
    enrollment = enroll_in_course(learner["id"], course["id"])
    validate_success(
        api.refund_enrollment(enrollment["id"], make_learner_headers(learner["id"])), 200
    )  # no ACTIVE child remains
    retired = validate_success(
        api.retire_course(course["id"], make_instructor_headers(instructor["id"])), 200
    )
    assert retired["status"] == "RETIRED"


# ===========================================================================
# Queue A — cross_entity_state_dependency / payout_approve_depends_on_instructor_balance
# ===========================================================================
def test_approve_blocked_by_zero_instructor_balance(api):
    """PRD §3.11: "Approving a payout (the `REQUESTED → PAID` transition) is allowed only
    while the payout is `REQUESTED`, requires the instructor's `payout_balance_cents` to
    still be at least 1 (otherwise `ERR_INSUFFICIENT_BALANCE`, HTTP 422)".

    A REQUESTED payout for an instructor with payout_balance_cents 0 is rejected on
    approval with ERR_INSUFFICIENT_BALANCE. A payout cannot be requested at all while the
    balance is below 1 (PRD §3.11), so the zero-balance condition is reached by funding the
    instructor, requesting two payouts while funds exist, then approving the first to drain
    the payable balance to 0 — leaving the second REQUESTED payout to be approved against a
    now-zero balance.

    Design: Difficulty/cross_entity_state_dependency/payout_approve_depends_on_instructor_balance
    """
    set_clock("2026-06-01T00:00:00Z")
    instructor = create_instructor(revenue_share_pct=0.50)
    learner = create_learner()
    course, _ = create_published_course(instructor["id"], list_price_cents=4000,
                                        refund_window_days=5)
    enrollment = enroll_in_course(learner["id"], course["id"])
    set_clock("2026-06-10T00:00:00Z")
    validate_success(
        api.get_enrollment(enrollment["id"], make_learner_headers(learner["id"])), 200
    )  # 2000c becomes payable
    first = request_payout(instructor["id"], 2000)
    second = request_payout(instructor["id"], 2000)
    inst = validate_success(
        api.get_instructor(instructor["id"], make_instructor_headers(instructor["id"])), 200
    )
    # Approve the first payout: it pays 2000c and drains payout_balance_cents to 0.
    validate_success(
        api.approve_payout(first["id"], approve_payout_payload(inst["version"]),
                           make_admin_headers()),
        200,
    )
    inst = validate_success(
        api.get_instructor(instructor["id"], make_instructor_headers(instructor["id"])), 200
    )
    assert inst["payout_balance_cents"] == 0, "precondition: payable balance drained to 0"
    res = api.approve_payout(
        second["id"], approve_payout_payload(inst["version"]), make_admin_headers()
    )
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_BALANCE.value)


def test_approve_succeeds_when_instructor_balance_sufficient(api):
    """PRD §3.11: "Approving a payout (the `REQUESTED → PAID` transition) is allowed only
    while the payout is `REQUESTED`, requires the instructor's `payout_balance_cents` to
    still be at least 1".

    The same approve transition that is blocked at balance 0 succeeds once the
    instructor's payable balance is at least 1 — its validity depends on the Instructor's
    computed balance state.

    Design: Difficulty/cross_entity_state_dependency/payout_approve_depends_on_instructor_balance
    """
    set_clock("2026-06-01T00:00:00Z")
    instructor = create_instructor(revenue_share_pct=0.50)
    learner = create_learner()
    course, _ = create_published_course(instructor["id"], list_price_cents=4000,
                                        refund_window_days=5)
    enrollment = enroll_in_course(learner["id"], course["id"])
    set_clock("2026-06-10T00:00:00Z")
    validate_success(
        api.get_enrollment(enrollment["id"], make_learner_headers(learner["id"])), 200
    )  # 2000c becomes payable
    payout = request_payout(instructor["id"], 2000)
    inst = validate_success(
        api.get_instructor(instructor["id"], make_instructor_headers(instructor["id"])), 200
    )
    res = api.approve_payout(
        payout["id"], approve_payout_payload(inst["version"]), make_admin_headers()
    )
    approved = validate_success(res, 200)
    assert approved["status"] == "PAID", "balance >= 1 permits the REQUESTED->PAID transition"


# ===========================================================================
# Queue A — transitive_cascade / retire_course_cascade_retires_member_bundle_depth2
# ===========================================================================
def test_retire_course_retires_member_course(api):
    """PRD §3.3: "An instructor may retire a course from either `PUBLISHED` or
    `UNPUBLISHED` status, but only when the course has no enrollment still in `ACTIVE`
    status".

    Retiring a course with no active enrollments transitions it to RETIRED (hop A of the
    cascade).

    Design: Difficulty/transitive_cascade/retire_course_cascade_retires_member_bundle_depth2
    """
    instructor = create_instructor(revenue_share_pct=0.50)
    bundle, courses = create_bundle_of_published_courses(
        instructor["id"], list_prices=[3000, 2000], bundle_price_cents=4000
    )
    retired = validate_success(
        api.retire_course(courses[0]["id"], make_instructor_headers(instructor["id"])), 200
    )
    assert retired["status"] == "RETIRED"


def test_retire_course_cascades_member_bundle_to_retired(api):
    """PRD §3.3: "Retiring a course (both the `PUBLISHED → RETIRED` and the
    `UNPUBLISHED → RETIRED` transitions) cascades to bundles: every bundle currently in
    `ACTIVE` status whose `course_ids` includes the retired course is itself transitioned
    to `RETIRED`".

    Retiring C1 cascades the ACTIVE bundle over {C1,C2} to RETIRED (hop B).

    Design: Difficulty/transitive_cascade/retire_course_cascade_retires_member_bundle_depth2
    """
    instructor = create_instructor(revenue_share_pct=0.50)
    bundle, courses = create_bundle_of_published_courses(
        instructor["id"], list_prices=[3000, 2000], bundle_price_cents=4000
    )
    validate_success(
        api.retire_course(courses[0]["id"], make_instructor_headers(instructor["id"])), 200
    )
    refreshed = validate_success(
        api.get_bundle(bundle["id"], make_instructor_headers(instructor["id"])), 200
    )
    assert refreshed["status"] == "RETIRED", "member-course retire cascades bundle to RETIRED"


# ===========================================================================
# Queue B — cross_cutting_complexity_layers / occ_payout_approve_correct_version_succeeds
# ===========================================================================
def test_payout_approve_with_current_version_succeeds(api):
    """PRD §3.11: "On approval the system sets `paid_amount_cents` to the lesser of the
    `requested_amount_cents` and the instructor's current `payout_balance_cents`, writes a
    `PAYOUT` `RevenueLedgerEntry` ... recomputes the instructor's `payout_balance_cents`
    (debited by the paid amount), and increments the instructor's `version` by 1."

    Approving a 2000c payout against an instructor with 2000c available and the current
    version sets PAID, paid_amount 2000, and leaves payout_balance 0.

    Design: Corner/cross_cutting_complexity_layers/occ_payout_approve_correct_version_succeeds
    """
    set_clock("2026-06-01T00:00:00Z")
    instructor = create_instructor(revenue_share_pct=0.50)
    learner = create_learner()
    course, _ = create_published_course(instructor["id"], list_price_cents=4000,
                                        refund_window_days=5)
    enrollment = enroll_in_course(learner["id"], course["id"])
    set_clock("2026-06-10T00:00:00Z")
    validate_success(
        api.get_enrollment(enrollment["id"], make_learner_headers(learner["id"])), 200
    )  # lazy EXPIRE flips SALE to AVAILABLE
    payout = request_payout(instructor["id"], 2000)
    inst = validate_success(
        api.get_instructor(instructor["id"], make_instructor_headers(instructor["id"])), 200
    )
    res = api.approve_payout(
        payout["id"], approve_payout_payload(inst["version"]), make_admin_headers()
    )
    approved = validate_success(res, 200)
    assert approved["status"] == "PAID"
    assert approved["paid_amount_cents"] == 2000
    inst_after = validate_success(
        api.get_instructor(instructor["id"], make_instructor_headers(instructor["id"])), 200
    )
    assert inst_after["payout_balance_cents"] == 0, (
        f"balance debited by paid amount -> 0, got {inst_after['payout_balance_cents']}"
    )


# ===========================================================================
# Queue B — cross_cutting_complexity_layers / occ_payout_approve_stale_version_rejected
# ===========================================================================
def test_payout_approve_with_stale_version_rejected(api):
    """PRD §2.10: "If a SALE-window expiry flip or an earlier payout has advanced that
    instructor's `version` since the client read it, the carried value will no longer
    equal the instructor's current `version`, and the approval is rejected with
    `ERR_STALE_VERSION` (HTTP 412)".

    Two sales expire: the first makes a payout requestable and the version is captured
    after the request; a second window-expiry flip then advances the instructor version
    beyond the captured value, so approving with the stale version is rejected.

    Design: Corner/cross_cutting_complexity_layers/occ_payout_approve_stale_version_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    instructor = create_instructor(revenue_share_pct=0.50)
    learner_a = create_learner()
    learner_b = create_learner()
    course_a, _ = create_published_course(instructor["id"], title="SA",
                                          list_price_cents=4000, refund_window_days=5)
    course_b, _ = create_published_course(instructor["id"], title="SB",
                                          list_price_cents=4000, refund_window_days=5)
    enr_a = enroll_in_course(learner_a["id"], course_a["id"])
    enr_b = enroll_in_course(learner_b["id"], course_b["id"])
    set_clock("2026-06-10T00:00:00Z")
    validate_success(
        api.get_enrollment(enr_a["id"], make_learner_headers(learner_a["id"])), 200
    )  # first SALE flips to AVAILABLE: payout_balance becomes 2000
    payout = request_payout(instructor["id"], 2000)
    inst_pre = validate_success(
        api.get_instructor(instructor["id"], make_instructor_headers(instructor["id"])), 200
    )
    validate_success(
        api.get_enrollment(enr_b["id"], make_learner_headers(learner_b["id"])), 200
    )  # second window-expiry AVAILABLE flip bumps the instructor version above inst_pre
    res = api.approve_payout(
        payout["id"], approve_payout_payload(inst_pre["version"]), make_admin_headers()
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION.value)


# ===========================================================================
# Queue B — cross_cutting_complexity_layers / bundle_enroll_stale_bundle_rejected
# ===========================================================================
def test_bundle_enroll_with_stale_version_after_retire_cascade_rejected(api):
    """PRD §2.10: "If a retire cascade (triggered when one of the bundle's member courses
    is retired) has moved the bundle to `RETIRED` and advanced its `version` since the
    client read it, the carried value will no longer equal the bundle's current `version`,
    and the bundle enrollment is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    A bundle whose version was observed before a member-course retire cascade is enrolled
    with the stale version and rejected. The same cascade that bumps the bundle's version
    also moves it to RETIRED, so a precedence-respecting implementation (PRD §2.11: state
    eligibility is evaluated before optimistic-concurrency version checks) reports
    ERR_INVALID_STATE for the non-enrollable bundle, while PRD §2.10 names ERR_STALE_VERSION
    for the stale carried version; either PRD-grounded outcome is accepted.

    Design: Corner/cross_cutting_complexity_layers/bundle_enroll_stale_bundle_rejected
    """
    instructor = create_instructor(revenue_share_pct=0.50)
    learner = create_learner()
    bundle, courses = create_bundle_of_published_courses(
        instructor["id"], list_prices=[3000, 2000], bundle_price_cents=4000
    )
    stale_version = bundle["version"]
    validate_success(
        api.retire_course(courses[0]["id"], make_instructor_headers(instructor["id"])), 200
    )  # cascades the bundle to RETIRED and bumps its version
    res = api.enroll_bundle(
        bundle["id"], enroll_bundle_payload(learner["id"], stale_version),
        make_learner_headers(learner["id"]),
    )
    validate_error_is_one_of(
        res, [ApiErrorId.ERR_STALE_VERSION.value, ApiErrorId.ERR_INVALID_STATE.value]
    )


# ===========================================================================
# Queue B — state_machines / publish_from_published_returns_invalid_state
# ===========================================================================
def test_publish_already_published_course_invalid_state(api):
    """PRD §3.3: "An instructor may publish a course only from `DRAFT` (the
    `DRAFT → PUBLISHED` transition) or re-publish it from `UNPUBLISHED` (the
    `UNPUBLISHED → PUBLISHED` transition); attempting to publish a course in any other
    status is rejected with `ERR_INVALID_STATE`."

    Publishing a course that is already PUBLISHED is rejected.

    Design: Corner/state_machines/publish_from_published_returns_invalid_state
    """
    instructor = create_instructor(revenue_share_pct=0.50)
    course, _ = create_published_course(instructor["id"], list_price_cents=1000)
    res = api.publish_course(course["id"], make_instructor_headers(instructor["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Queue B — state_machines / publish_course_with_no_lessons_returns_not_publishable
# ===========================================================================
def test_publish_course_with_no_lessons_not_publishable(api):
    """PRD §3.3: "A first-time publish from `DRAFT` carries three further requirements,
    all enforced together with `ERR_COURSE_NOT_PUBLISHABLE` (HTTP 422): the course must
    have at least one lesson".

    Publishing a DRAFT course with zero lessons is rejected.

    Design: Corner/state_machines/publish_course_with_no_lessons_returns_not_publishable
    """
    instructor = create_instructor(revenue_share_pct=0.50)
    course = create_draft_course(instructor["id"], list_price_cents=1000)
    res = api.publish_course(course["id"], make_instructor_headers(instructor["id"]))
    validate_error(res, ApiErrorId.ERR_COURSE_NOT_PUBLISHABLE.value)


# ===========================================================================
# Queue B — state_machines / unpublish_blocks_new_enrollment_invalid_state
# ===========================================================================
def test_unpublished_course_blocks_new_enrollment(api):
    """PRD §3.3: "Unpublishing takes a course from `PUBLISHED` to `UNPUBLISHED`. Its sole
    effect is to make the course non-enrollable — new enrollments are blocked while it is
    unpublished".

    Enrolling in an UNPUBLISHED course is rejected with ERR_INVALID_STATE.

    Design: Corner/state_machines/unpublish_blocks_new_enrollment_invalid_state
    """
    instructor = create_instructor(revenue_share_pct=0.50)
    learner = create_learner()
    course, _ = create_published_course(instructor["id"], list_price_cents=1000)
    validate_success(
        api.unpublish_course(course["id"], make_instructor_headers(instructor["id"])), 200
    )
    from test_helpers import enroll_course_payload
    res = api.enroll_course(course["id"], enroll_course_payload(learner["id"]),
                            make_learner_headers(learner["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Queue B — state_machines / retire_is_terminal_no_republish
# ===========================================================================
def test_retired_course_cannot_be_republished(api):
    """PRD §3.3: "Retiring is terminal." and "attempting to publish a course in any other
    status is rejected with `ERR_INVALID_STATE`."

    Publishing a RETIRED course is rejected with ERR_INVALID_STATE.

    Design: Corner/state_machines/retire_is_terminal_no_republish
    """
    instructor = create_instructor(revenue_share_pct=0.50)
    course, _ = create_published_course(instructor["id"], list_price_cents=1000)
    validate_success(
        api.retire_course(course["id"], make_instructor_headers(instructor["id"])), 200
    )
    res = api.publish_course(course["id"], make_instructor_headers(instructor["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
