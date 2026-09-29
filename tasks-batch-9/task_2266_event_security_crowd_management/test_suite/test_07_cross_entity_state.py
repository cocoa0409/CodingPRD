"""Operations whose legality is decided by the state of some other row entirely.

Nothing is wrong with the row being acted on in any of these cases. A booking is
refused because of a guard's credential file; a publish is refused because of an
assessment's approval state; a verification is refused because of a vendor's
standing. In each pair the blocking row is then moved into the right state and
the identical request is replayed to prove that was the only obstacle.
"""

from test_helpers import (
    AUDITOR_HEADERS,
    COORDINATOR_HEADERS,
    DIRECTOR_HEADERS,
    ApiClient,
    ApiErrorId,
    AssessmentStatus,
    AssignmentStatus,
    DutyStatus,
    EventStatus,
    PayBasis,
    PlanStatus,
    PostStatus,
    PostType,
    ReadinessPosture,
    SubcontractorStatus,
    VerificationStatus,
    World,
    action,
    assert_assignment_cost,
    assert_assignment_state,
    assert_coverage,
    assert_ledger,
    assert_post_fill,
    build_clock_world,
    build_published_plan_with_posts_world,
    build_submitted_assessment_world,
    create_assignment,
    create_verified_guard,
    guard_payload,
    post_payload,
    read_event_version,
    staffing_plan_payload,
    subcontracted_guard_payload,
    subcontractor_payload,
    validate_error,
    validate_success,
)

PLANNING_INSTANT = "2026-09-01T00:00:00Z"
MID_SHIFT_EXPIRY = "2026-09-12T18:00:00Z"


def _credential_world(api: ApiClient) -> World:
    """One guard never verified, one verified but holding a card that lapses mid-shift."""
    world = build_published_plan_with_posts_world(
        api,
        [
            {"code": "P1", "post_type": PostType.PERIMETER, "required_guard_count": 1},
            {"code": "PF", "post_type": PostType.PERIMETER, "required_guard_count": 4},
        ],
    )
    unverified = validate_success(
        api.create_guard(guard_payload("GC-5001", full_name="Gale One"), COORDINATOR_HEADERS),
        expected_status=201,
    )
    world.g1_id = unverified["id"]
    world.g2_id = create_verified_guard(
        api, "GC-5002", full_name="Gale Two", credential_expires_on=MID_SHIFT_EXPIRY
    )
    world.a1 = create_assignment(api, world.p1_id, world.g1_id)
    world.a2 = create_assignment(api, world.p1_id, world.g2_id)
    return world


def test_confirmation_is_refused_for_both_kinds_of_credential_defect():
    """An unverified card and a card that lapses before the shift ends fail the same rule.

    The first guard was never taken to the auditor at all. The second was cleared
    on 1 September but their card runs out at 18:00 on the night, four and a half
    hours before the post window closes, and the comparison is against the shift's
    end rather than its start.

    PRD: "**Guard credential currency** — the guard's `verification_status` is `VERIFIED` and their `credential_expires_on` is strictly after the assignment's `window_end`, else `ERR_GUARD_CREDENTIAL_INVALID` (422)."
    Design: Difficulty/cross_entity_state_dependency/confirm_blocked_by_guard_verification_status
    """
    api = ApiClient()
    world = _credential_world(api)

    validate_error(
        api.post_assignment_duty_event(world.a1, action("CONFIRM"), COORDINATOR_HEADERS),
        ApiErrorId.GUARD_CREDENTIAL_INVALID,
    )
    validate_error(
        api.post_assignment_duty_event(world.a2, action("CONFIRM"), COORDINATOR_HEADERS),
        ApiErrorId.GUARD_CREDENTIAL_INVALID,
    )

    plan = validate_success(api.get_staffing_plan(world.plan_id, COORDINATOR_HEADERS))
    assert_ledger(plan, 0, 0.00, budget_remaining_cents=500000)


def test_clearing_the_card_lets_the_identical_confirmation_through():
    """Verifying the guard is the only change needed for the same request to succeed.

    The auditor's fast path takes the guard straight from UNVERIFIED to VERIFIED
    and stamps the clearance with the logical clock. The replayed confirmation
    then commits 16500 cents and 7.50 hours, while the guard with the short-dated
    card is still stuck at TENTATIVE.

    PRD: "Success sets `verification_status` to `VERIFIED`, stamps `verified_at` with the logical clock, recomputes the vendor's `verified_guard_count` when a vendor is involved, and increments the guard's `version`."
    Design: Difficulty/cross_entity_state_dependency/confirm_blocked_by_guard_verification_status
    """
    api = ApiClient()
    world = _credential_world(api)
    validate_error(
        api.post_assignment_duty_event(world.a1, action("CONFIRM"), COORDINATOR_HEADERS),
        ApiErrorId.GUARD_CREDENTIAL_INVALID,
    )

    verified = validate_success(
        api.guard_credential_verification(world.g1_id, action("VERIFY"), AUDITOR_HEADERS)
    )
    assert verified["verification_status"] == VerificationStatus.VERIFIED
    assert verified["verified_at"] == PLANNING_INSTANT

    confirmed = validate_success(
        api.post_assignment_duty_event(world.a1, action("CONFIRM"), COORDINATOR_HEADERS)
    )
    assert_assignment_state(confirmed, AssignmentStatus.CONFIRMED, DutyStatus.PENDING_BRIEF)
    assert_assignment_cost(confirmed, 7.50, 16500, PayBasis.EMPLOYEE_STRAIGHT)

    still_blocked = validate_success(api.get_post_assignment(world.a2, COORDINATOR_HEADERS))
    assert still_blocked["assignment_status"] == AssignmentStatus.TENTATIVE

    post = validate_success(api.get_post(world.p1_id, COORDINATOR_HEADERS))
    assert_post_fill(post, 1, PostStatus.FILLED)

    plan = validate_success(api.get_staffing_plan(world.plan_id, COORDINATOR_HEADERS))
    assert_ledger(plan, 16500, 7.50, budget_remaining_cents=483500)
    assert_coverage(plan, 5, 1, 0.20, ReadinessPosture.BLOCKED)


def _unapproved_assessment_world(api: ApiClient) -> World:
    """Plan drafted against an assessment that is still only SUBMITTED."""
    world = build_submitted_assessment_world(api)
    plan = validate_success(
        api.create_staffing_plan(
            world.event_id,
            staffing_plan_payload(world.ra_id, read_event_version(api, world.event_id)),
            COORDINATOR_HEADERS,
        ),
        expected_status=201,
    )
    world.plan_id = plan["id"]
    validate_success(
        api.create_post(
            world.plan_id,
            post_payload(world.zf_id, "P1", PostType.PERIMETER, required_guard_count=5),
            COORDINATOR_HEADERS,
        ),
        expected_status=201,
    )
    return world


def test_a_plan_cannot_be_published_against_a_merely_submitted_assessment():
    """The plan is complete and correctly sized; its assessment is simply not approved yet.

    Drafting a plan against a submitted assessment is allowed, because the
    approval requirement bites at publication rather than at creation. The
    refusal leaves the plan in DRAFT and the assessment untouched at SUBMITTED.

    PRD: "**Assessment approval** — the plan's risk assessment has `status` equal to `APPROVED` before a publish, else `ERR_ASSESSMENT_NOT_APPROVED` (409)."
    Design: Difficulty/cross_entity_state_dependency/publish_blocked_by_unapproved_risk_assessment
    """
    api = ApiClient()
    world = _unapproved_assessment_world(api)

    validate_error(
        api.staffing_plan_lifecycle(world.plan_id, action("PUBLISH"), COORDINATOR_HEADERS),
        ApiErrorId.ASSESSMENT_NOT_APPROVED,
    )

    plan = validate_success(api.get_staffing_plan(world.plan_id, COORDINATOR_HEADERS))
    assert plan["status"] == PlanStatus.DRAFT
    assert plan["pinned_risk_assessment_version"] is None

    assessment = validate_success(api.get_risk_assessment(world.ra_id, DIRECTOR_HEADERS))
    assert assessment["status"] == AssessmentStatus.SUBMITTED


def test_approving_the_assessment_unblocks_the_publish_and_pins_its_version():
    """Approval moves the event to RISK_ASSESSED and the same publish then succeeds.

    Approval is the third mutation on the assessment, so it lands at version 3,
    and that is exactly the snapshot the plan pins. The plan is sized to the
    assessed five staff but has nobody booked, so it publishes BLOCKED.

    PRD: "Publishing, performed by the coordinator, requires the referenced assessment's `status` to be `APPROVED` (else `ERR_ASSESSMENT_NOT_APPROVED`), at least one non-`CLOSED` post (else `ERR_PLAN_HAS_NO_POSTS`), the plan's `required_total_staff` to be at least the assessment's `required_total_staff` (else `ERR_STAFFING_BELOW_ASSESSED_REQUIREMENT`), and `budget_cents` to be at least the assessment's `minimum_staffing_cost_floor_cents` (else `ERR_PLAN_BUDGET_BELOW_FLOOR`); the gate interlock also applies."
    Design: Difficulty/cross_entity_state_dependency/publish_blocked_by_unapproved_risk_assessment
    """
    api = ApiClient()
    world = _unapproved_assessment_world(api)
    validate_error(
        api.staffing_plan_lifecycle(world.plan_id, action("PUBLISH"), COORDINATOR_HEADERS),
        ApiErrorId.ASSESSMENT_NOT_APPROVED,
    )

    approved = validate_success(
        api.risk_assessment_decision(world.ra_id, action("APPROVE"), DIRECTOR_HEADERS)
    )
    assert approved["status"] == AssessmentStatus.APPROVED
    assert approved["version"] == 3

    event = validate_success(api.get_event(world.event_id, DIRECTOR_HEADERS))
    assert event["status"] == EventStatus.RISK_ASSESSED

    published = validate_success(
        api.staffing_plan_lifecycle(world.plan_id, action("PUBLISH"), COORDINATOR_HEADERS)
    )
    assert published["status"] == PlanStatus.PUBLISHED
    assert published["pinned_risk_assessment_version"] == 3
    assert_coverage(published, 5, 0, 0.00, ReadinessPosture.BLOCKED)


def _suspended_vendor_world(api: ApiClient) -> World:
    """Approved-then-suspended vendor holding one unverified subcontracted guard."""
    world = build_clock_world(api)
    vendor = validate_success(
        api.create_subcontractor(
            subcontractor_payload(
                company_name="Meridian Guarding",
                license_number="SC-6001",
                insurance_expires_on="2026-12-31T00:00:00Z",
                markup_pct=0.35,
            ),
            COORDINATOR_HEADERS,
        ),
        expected_status=201,
    )
    world.vendor_id = vendor["id"]
    validate_success(
        api.subcontractor_decision(world.vendor_id, action("APPROVE"), AUDITOR_HEADERS)
    )
    suspended = validate_success(
        api.subcontractor_decision(world.vendor_id, action("SUSPEND"), AUDITOR_HEADERS)
    )
    assert suspended["status"] == SubcontractorStatus.SUSPENDED

    guard = validate_success(
        api.create_guard(
            subcontracted_guard_payload(
                "GC-6001",
                world.vendor_id,
                full_name="Vera Hand",
                credential_level=2,
                credential_expires_on="2026-12-31T00:00:00Z",
            ),
            COORDINATOR_HEADERS,
        ),
        expected_status=201,
    )
    world.g1_id = guard["id"]
    return world


def test_a_suspended_vendors_guard_cannot_be_verified():
    """The guard's own card is perfectly current; their employer is not in good standing.

    The card runs to the end of the year, so the guard fails nothing on their own
    account. The vendor's suspension alone blocks the clearance, and the refusal
    leaves the guard UNVERIFIED and the vendor's verified headcount at zero.

    PRD: "Either way, verification requires `credential_expires_on` to be strictly after the logical clock (else `ERR_GUARD_CREDENTIAL_INVALID`) and, for a subcontracted guard, requires the vendor's `status` to be `APPROVED` with `insurance_expires_on` strictly after the logical clock (else `ERR_SUBCONTRACTOR_NOT_ELIGIBLE`)."
    Design: Difficulty/cross_entity_state_dependency/guard_verify_blocked_by_suspended_subcontractor
    """
    api = ApiClient()
    world = _suspended_vendor_world(api)

    validate_error(
        api.guard_credential_verification(world.g1_id, action("VERIFY"), AUDITOR_HEADERS),
        ApiErrorId.SUBCONTRACTOR_NOT_ELIGIBLE,
    )

    guard = validate_success(api.get_guard(world.g1_id, COORDINATOR_HEADERS))
    assert guard["verification_status"] == VerificationStatus.UNVERIFIED
    assert guard["verified_at"] is None

    vendor = validate_success(api.get_subcontractor(world.vendor_id, COORDINATOR_HEADERS))
    assert vendor["verified_guard_count"] == 0


def test_re_approving_the_vendor_does_not_auto_verify_but_does_unblock_verification():
    """The vendor comes back to APPROVED and the guard still has to be cleared by hand.

    Re-approval is explicitly not a re-verification: immediately afterwards the
    guard is still UNVERIFIED. Only the replayed VERIFY clears the card, stamps
    the clearance from the logical clock and lifts the vendor's verified headcount
    to one.

    PRD: "Re-approving a suspended vendor does **not** auto-re-verify anybody: each guard must be verified again individually."
    Design: Difficulty/cross_entity_state_dependency/guard_verify_blocked_by_suspended_subcontractor
    """
    api = ApiClient()
    world = _suspended_vendor_world(api)
    validate_error(
        api.guard_credential_verification(world.g1_id, action("VERIFY"), AUDITOR_HEADERS),
        ApiErrorId.SUBCONTRACTOR_NOT_ELIGIBLE,
    )

    reapproved = validate_success(
        api.subcontractor_decision(world.vendor_id, action("APPROVE"), AUDITOR_HEADERS)
    )
    assert reapproved["status"] == SubcontractorStatus.APPROVED

    still_unverified = validate_success(api.get_guard(world.g1_id, COORDINATOR_HEADERS))
    assert still_unverified["verification_status"] == VerificationStatus.UNVERIFIED

    verified = validate_success(
        api.guard_credential_verification(world.g1_id, action("VERIFY"), AUDITOR_HEADERS)
    )
    assert verified["verification_status"] == VerificationStatus.VERIFIED
    assert verified["verified_at"] == PLANNING_INSTANT

    vendor = validate_success(api.get_subcontractor(world.vendor_id, COORDINATOR_HEADERS))
    assert vendor["verified_guard_count"] == 1
