"""
The vendor, submission, cycle, and sanction state machines and their guards.

Every test builds the state it needs through the documented endpoints, because
the server is restarted and the database emptied before each one runs.
"""

from test_helpers import (
    ANALYST_HEADERS,
    DEFAULT_LOGICAL_CLOCK_ISO,
    INVESTIGATOR_HEADERS,
    INVESTIGATOR_ONE,
    SUPERVISOR_HEADERS,
    ApiErrorId,
    assert_field_values,
    assert_peer_group,
    assert_price_cycle,
    assert_price_submission,
    assert_sanction_case,
    assert_sanction_schedule,
    assert_vendor,
    factories,
    fixtures,
    make_vendor_operator_headers,
    validate_error,
    validate_success,
)
from test_helpers.types import (
    BlockedReason,
    PeerGroupStatus,
    PriceCycleStatus,
    ReviewReason,
    SanctionResolution,
    SanctionStatus,
    SubmissionStatus,
    VendorStatus,
    ViolationCode,
    VoidedReason,
)


def test_new_vendor_starts_in_applicant_state(api):
    """
    A new application is an APPLICANT: only submitting it is legal from there.

    "The new Vendor begins in `authorization_status` `APPLICANT` with a null
    `peer_group_id`, a `risk_score` of 0.0, and a `risk_tier` of `LOW`."
    "When a request violates more than one rule, exactly one error is returned: the one
    belonging to the lowest-numbered rule in the ladder below."
    "The addressed entity is in a state that permits the requested transition, on every
    action endpoint. The error names the entity: `ERR_INVALID_VENDOR_STATE`,"
    "The vendor must actually be `IN_REVIEW`, or the request is refused with
    `ERR_INVALID_VENDOR_STATE`."
    "Completing reauthorization is a supervisor decision moving `REAUTH_PENDING →
    AUTHORIZED`, and it repeats the authorization gauntlet with one addition. The vendor
    must be `REAUTH_PENDING`;"
    "Submitting the application moves the vendor from `APPLICANT` to `IN_REVIEW` and is
    the moment the peer group is chosen. Only a vendor still in `APPLICANT` may be
    submitted; anything else is refused with `ERR_INVALID_VENDOR_STATE`."
    "the candidates are ordered by band width ascending, then by
    `min_monthly_redemption_cents` ascending, then by `created_at` ascending, and the
    first candidate in that order wins; the vendor's `peer_group_id` is set to that
    group's identifier."

    Design: Corner/state_machines/new_vendor_starts_in_applicant_state
    """
    peer_group = fixtures.create_peer_group(api)
    vendor = validate_success(
        api.create_vendor(factories.vendor_payload(), ANALYST_HEADERS), 201
    )

    assert_vendor(
        vendor,
        authorization_status=VendorStatus.APPLICANT.value,
        peer_group_id=None,
        version=1,
    )

    # No training has been recorded either, but the state rule outranks that check.
    validate_error(
        api.authorize_vendor(vendor["id"], None, SUPERVISOR_HEADERS),
        ApiErrorId.INVALID_VENDOR_STATE.value,
    )
    validate_error(
        api.complete_reauthorization(vendor["id"], None, SUPERVISOR_HEADERS),
        ApiErrorId.INVALID_VENDOR_STATE.value,
    )

    in_review = validate_success(
        api.submit_application(vendor["id"], None, ANALYST_HEADERS)
    )

    assert_vendor(
        in_review,
        id=vendor["id"],
        authorization_status=VendorStatus.IN_REVIEW.value,
        peer_group_id=peer_group["id"],
        authorization_blocked_reason=None,
    )


def test_serve_notice_moves_sanction_case_to_notice_served_with_response_due(api):
    """
    Serving a notice starts a fifteen-day election clock and leaves a tier-2 vendor alone.

    "**Opening a sanction case** by hand is a `ComplianceInvestigator` action."
    "The new case begins in `status` `OPENED` with `resolution` `NONE`, `cmp_paid_cents`
    0, and `notice_served_at`, `response_due_at`, and `dismissal_reason` null.
    `opened_by_user_id` is stamped from the acting `X-User-ID`."
    "A successful create increments the vendor's `version` by one."
    "The `base_tier` comes from the violation class: `CLASS_A` is tier 4, `CLASS_B` is
    tier 3, `CLASS_C` is tier 2, and `CLASS_D` is tier 1."
    "The `case_points` come from the **base** tier and never from the effective one: tier
    1 carries 1 point, tier 2 carries 2, tier 3 carries 4, and tier 4 carries 8."
    "The `cumulative_points_at_open` snapshot is the sum of those same base-tier point
    values over the vendor's **other** sanction cases whose `status` is `CMP_ELECTED`,
    `DISQUALIFICATION_IMPOSED`, or `CLOSED`."
    "The escalation step is the number of escalation thresholds — there are two, at 4
    points and at 8 points — that the snapshot plus this case's own `case_points` reaches
    or exceeds."
    "The `effective_tier` is the base tier plus that escalation step, capped at 4."
    "`disqualification_months` is 0 at tier 1, 6 at tier 2, 12 at tier 3, and 36 at tier 4
    — a tier-1 case therefore carries no disqualification at all."
    "`cmp_permitted` is true for every violation class except `CLASS_A`, which may never
    be settled by money."
    "The `cmp_amount_cents` is the vendor's `avg_monthly_redemption_cents` multiplied by
    the tier's monthly multiplier — 0.05 at tier 1, 0.10 at tier 2, 0.25 at tier 3, and
    0.50 at tier 4 — multiplied again by the tier's month count — 1 month at tier 1, 3 at
    tier 2, 6 at tier 3, and 12 at tier 4 — then rounded half up to a whole cent, and
    finally capped: the penalty is the lesser of that rounded figure and 5,625,000 cents,
    which is the statutory ceiling of fifty-six thousand two hundred fifty dollars."
    "If no such claim exists, `avg_monthly_redemption_cents` falls back to the vendor's
    self-reported `reported_monthly_redemption_cents`."
    "The case must be `OPENED`, or the request is refused with
    `ERR_INVALID_SANCTION_STATE`. The transition `OPENED → NOTICE_SERVED` stamps
    `notice_served_at` from the logical clock and sets `response_due_at` to fifteen days
    later — that is the election deadline. If the case's `base_tier` is exactly 4, serving
    the notice also moves an `AUTHORIZED` vendor `AUTHORIZED → SUSPENDED`"
    "Note that this suspension keys off `base_tier`, not `effective_tier`: a tier-3
    violation escalated to effective tier 4 does not suspend on notice."

    Design: Corner/state_machines/serve_notice_moves_sanction_case_to_notice_served_with_response_due
    """
    bundle = fixtures.published_ceiling_setup(api)
    vendor_before = fixtures.get_vendor(api, bundle["vendor"]["id"])

    assert_field_values(
        vendor_before,
        authorization_status=VendorStatus.AUTHORIZED.value,
        avg_monthly_redemption_cents=6_000_000,  # no claims, so the reported figure stands
    )

    case = fixtures.open_sanction_case(
        api,
        vendor_before["id"],
        vendor_before["version"],
        violation_code=ViolationCode.CLASS_C.value,
    )

    assert_sanction_case(
        case,
        vendor_id=vendor_before["id"],
        violation_code=ViolationCode.CLASS_C.value,
        source_visit_id=None,
        status=SanctionStatus.OPENED.value,
        resolution=SanctionResolution.NONE.value,
        cmp_paid_cents=0,
        notice_served_at=None,
        response_due_at=None,
        dismissal_reason=None,
        opened_by_user_id=INVESTIGATOR_ONE,
        version=1,
    )
    assert_sanction_schedule(
        case,
        base_tier=2,
        case_points=2,
        cumulative_points_at_open=0,
        effective_tier=2,  # no other case, so 0 + 2 points clears neither threshold
        disqualification_months=6,
        cmp_permitted=True,
        cmp_amount_cents=1_800_000,  # 6,000,000 x 0.10 x 3 months, under the cap
    )

    vendor_after_open = fixtures.get_vendor(api, vendor_before["id"])
    assert vendor_after_open["version"] == vendor_before["version"] + 1, (
        f"expected opening the case to increment the vendor version from "
        f"{vendor_before['version']}, got {vendor_after_open['version']}"
    )

    served = validate_success(
        api.serve_notice(case["id"], None, INVESTIGATOR_HEADERS)
    )

    assert_sanction_case(
        served,
        id=case["id"],
        status=SanctionStatus.NOTICE_SERVED.value,
        notice_served_at=DEFAULT_LOGICAL_CLOCK_ISO,
        response_due_at="2026-08-16T00:00:00.000Z",  # 2026-08-01 plus fifteen days
        resolution=SanctionResolution.NONE.value,
        cmp_paid_cents=0,
        cmp_amount_cents=1_800_000,
        base_tier=2,
    )

    # base_tier is 2, not 4, so the vendor is untouched and stays a counted member.
    vendor_after_notice = validate_success(
        api.get_vendor(vendor_before["id"], SUPERVISOR_HEADERS)
    )
    assert_field_values(
        vendor_after_notice, authorization_status=VendorStatus.AUTHORIZED.value
    )

    peer_group = validate_success(
        api.get_peer_group(bundle["peer_group"]["id"], SUPERVISOR_HEADERS)
    )
    assert_field_values(peer_group, member_count=1)


def test_start_reauthorization_one_day_before_window_opens_rejected(api):
    """
    The reauthorization window opens exactly ninety days before the due date, inclusive.

    "On success the vendor gains `authorized_at` from the logical clock and a
    `reauthorization_due_at` set to thirty-six calendar months after `authorized_at`."
    "An analyst opens it, moving `AUTHORIZED → REAUTH_PENDING`, but only once the window
    has been reached: the logical clock must be at or after ninety days before
    `reauthorization_due_at`, and the boundary is inclusive, so a clock landing exactly
    ninety days before the due date qualifies. An earlier attempt is refused with
    `ERR_REAUTH_WINDOW_NOT_OPEN`."
    "Opening the cycle recomputes `accepted_submission_count` and
    `price_submission_complete` against the current cycle, and stamps
    `reauth_blocked_reason` with the explanation `PENDING_COMPLIANCE_BUY` when
    `reauthorization_hold` is already true at that moment; otherwise the reason is set to
    null."
    "**Day arithmetic** — cure periods, blackout buffers, election windows,
    reauthorization windows, and risk windows — adds or subtracts a fixed number of
    24-hour days."
    "A peer group's `member_count` is the number of vendors assigned to it whose
    `authorization_status` is `AUTHORIZED`, `REAUTH_PENDING`, or `SUSPENDED`."

    Design: Corner/state_machines/start_reauthorization_one_day_before_window_opens_rejected
    """
    bundle = fixtures.published_ceiling_setup(api)
    vendor = fixtures.get_vendor(api, bundle["vendor"]["id"])

    assert_field_values(
        vendor,
        authorization_status=VendorStatus.AUTHORIZED.value,
        authorized_at=DEFAULT_LOGICAL_CLOCK_ISO,
        # thirty-six calendar months after 2026-08-01
        reauthorization_due_at="2029-08-01T00:00:00.000Z",
    )

    # One millisecond before 2029-05-03, which is 2029-08-01 less ninety days.
    fixtures.set_clock(api, "2029-05-02T23:59:59.999Z")

    validate_error(
        api.start_reauthorization(vendor["id"], None, ANALYST_HEADERS),
        ApiErrorId.REAUTH_WINDOW_NOT_OPEN.value,
    )

    still_authorized = fixtures.get_vendor(api, vendor["id"])
    assert_field_values(
        still_authorized,
        authorization_status=VendorStatus.AUTHORIZED.value,
        reauth_blocked_reason=None,
    )

    fixtures.set_clock(api, "2029-05-03T00:00:00Z")

    reauth_pending = validate_success(
        api.start_reauthorization(vendor["id"], None, ANALYST_HEADERS)
    )

    assert_vendor(
        reauth_pending,
        id=vendor["id"],
        authorization_status=VendorStatus.REAUTH_PENDING.value,
        reauth_blocked_reason=None,
        reauthorization_hold=False,
        reauthorization_due_at="2029-08-01T00:00:00.000Z",
        accepted_submission_count=1,
        price_submission_complete=True,
    )

    peer_group = validate_success(
        api.get_peer_group(bundle["peer_group"]["id"], SUPERVISOR_HEADERS)
    )
    assert_field_values(peer_group, member_count=1)


def test_revise_price_submission_beyond_two_revisions_rejected(api):
    """
    Two revisions are allowed and the third is refused, leaving the second one standing.

    "A decision of `REJECT` moves it `SUBMITTED → REJECTED` and requires a
    `review_reason` in the body, one of `PRICE_IMPLAUSIBLE`, `MISSING_DOCUMENTATION`, or
    `ABOVE_STATEWIDE_OUTLIER`; a rejection with no reason supplied is refused with
    `ERR_INVALID_REQUEST`."
    "Both outcomes stamp `reviewed_by_user_id` from the acting `X-User-ID` and
    `reviewed_at` from the logical clock, and both recompute the submitting vendor's
    `accepted_submission_count` and `price_submission_complete`"
    "The `VendorOperator` supplies a replacement `shelf_price_cents`, which moves the
    submission `REJECTED → SUBMITTED` for a fresh review, increments `revision_count` by
    one, and resets `review_reason`, `reviewed_by_user_id`, and `reviewed_at` to null."
    "The revision budget must not be exhausted: a submission may be revised while its
    `revision_count` is strictly less than two, so the first and second revisions are
    allowed and a third attempt — arriving when `revision_count` already stands at 2 — is
    refused with `ERR_REVISION_LIMIT_REACHED`."

    Design: Corner/state_machines/revise_price_submission_beyond_two_revisions_rejected
    """
    category = fixtures.create_food_category(api)
    item = fixtures.create_food_item(api, category["id"])
    cycle = fixtures.create_price_cycle(api)
    vendor = fixtures.create_vendor(api)
    vendor_headers = make_vendor_operator_headers(vendor["id"])

    submission = fixtures.submit_price(
        api, vendor["id"], item["id"], cycle["id"], shelf_price_cents=320
    )
    assert_price_submission(
        submission,
        status=SubmissionStatus.SUBMITTED.value,
        shelf_price_cents=320,
        revision_count=0,
        review_reason=None,
        reviewed_by_user_id=None,
        reviewed_at=None,
    )

    fixtures.reject_submission(
        api, submission["id"], review_reason=ReviewReason.PRICE_IMPLAUSIBLE.value
    )

    first_revision = validate_success(
        api.revise_price_submission(
            submission["id"], factories.revise_payload(330), vendor_headers
        )
    )
    assert_price_submission(
        first_revision,
        id=submission["id"],
        status=SubmissionStatus.SUBMITTED.value,
        shelf_price_cents=330,
        revision_count=1,
        review_reason=None,
        reviewed_by_user_id=None,
        reviewed_at=None,
    )

    fixtures.reject_submission(
        api, submission["id"], review_reason=ReviewReason.MISSING_DOCUMENTATION.value
    )

    second_revision = validate_success(
        api.revise_price_submission(
            submission["id"], factories.revise_payload(340), vendor_headers
        )
    )
    assert_price_submission(
        second_revision,
        id=submission["id"],
        status=SubmissionStatus.SUBMITTED.value,
        shelf_price_cents=340,
        revision_count=2,
        review_reason=None,
        reviewed_by_user_id=None,
        reviewed_at=None,
    )

    fixtures.reject_submission(
        api, submission["id"], review_reason=ReviewReason.ABOVE_STATEWIDE_OUTLIER.value
    )

    validate_error(
        api.revise_price_submission(
            submission["id"], factories.revise_payload(350), vendor_headers
        ),
        ApiErrorId.REVISION_LIMIT_REACHED.value,
    )

    frozen = validate_success(api.get_price_submission(submission["id"], vendor_headers))

    assert_price_submission(
        frozen,
        id=submission["id"],
        status=SubmissionStatus.REJECTED.value,
        shelf_price_cents=340,
        revision_count=2,
        review_reason=ReviewReason.ABOVE_STATEWIDE_OUTLIER.value,
    )


def test_close_price_cycle_twice_second_call_rejected(api):
    """
    A cycle closes once and publishes once; the repeat calls are state rejections.

    "A new cycle starts `OPEN`, with `closed_at`, `published_at` null and
    `provisional_ceiling_count`, `published_ceiling_count`, and `skipped_pair_count` at 0."
    "Closing moves a cycle `OPEN → CLOSED` — a cycle in any other status is refused with
    `ERR_INVALID_CYCLE_STATE` — stamps `closed_at` with the logical clock, and sweeps
    every pair consisting of an `ACTIVE` peer group and an `ACTIVE` authorized food item."
    "For each pair with a non-empty candidate set, a PriceCeiling row is written with
    `status` `PROVISIONAL`; the number written becomes the cycle's
    `provisional_ceiling_count`, and the number of pairs skipped for having an empty
    candidate set becomes its `skipped_pair_count`."
    "Publishing moves a cycle `CLOSED → PUBLISHED` — again `ERR_INVALID_CYCLE_STATE` for
    any other status — stamps `published_at`, and performs three passes."
    "The response to publication reports the `price_cycle_id`, the resulting `status`, the
    `published_ceiling_count`, the `skipped_pair_count`, a `superseded_ceiling_count`
    covering every row this call moved to `SUPERSEDED`, and the `published_at` instant."

    Design: Corner/state_machines/close_price_cycle_twice_second_call_rejected
    """
    cycle = fixtures.create_price_cycle(api)

    assert_price_cycle(
        cycle,
        status=PriceCycleStatus.OPEN.value,
        closed_at=None,
        published_at=None,
        provisional_ceiling_count=0,
        published_ceiling_count=0,
        skipped_pair_count=0,
    )

    closed = validate_success(
        api.close_price_cycle(cycle["id"], None, SUPERVISOR_HEADERS)
    )

    # No peer group and no item exist, so the sweep visits no pair at all.
    assert_price_cycle(
        closed,
        id=cycle["id"],
        status=PriceCycleStatus.CLOSED.value,
        closed_at=DEFAULT_LOGICAL_CLOCK_ISO,
        provisional_ceiling_count=0,
        skipped_pair_count=0,
    )

    fixtures.set_clock(api, "2026-08-02T00:00:00Z")

    validate_error(
        api.close_price_cycle(cycle["id"], None, SUPERVISOR_HEADERS),
        ApiErrorId.INVALID_CYCLE_STATE.value,
    )

    unchanged = validate_success(api.get_price_cycle(cycle["id"], SUPERVISOR_HEADERS))
    assert_price_cycle(
        unchanged,
        status=PriceCycleStatus.CLOSED.value,
        closed_at=DEFAULT_LOGICAL_CLOCK_ISO,
        published_at=None,
    )

    summary = validate_success(
        api.publish_ceilings(cycle["id"], None, SUPERVISOR_HEADERS)
    )

    assert_field_values(
        summary,
        price_cycle_id=cycle["id"],
        status=PriceCycleStatus.PUBLISHED.value,
        published_ceiling_count=0,
        skipped_pair_count=0,
        superseded_ceiling_count=0,
        published_at="2026-08-02T00:00:00.000Z",
    )

    validate_error(
        api.publish_ceilings(cycle["id"], None, SUPERVISOR_HEADERS),
        ApiErrorId.INVALID_CYCLE_STATE.value,
    )


def test_denied_vendor_terminal_state_rejects_further_transitions(api):
    """
    Denial voids the vendor's live submissions and closes every further transition.

    "A supervisor may deny a vendor whose `authorization_status` is either `IN_REVIEW` or
    `REAUTH_PENDING`, supplying a `denial_reason` that is stored on the vendor; any other
    starting status is refused with `ERR_INVALID_VENDOR_STATE`. `DENIED` is terminal."
    "Denial carries the same submission cascade in both cases: every PriceSubmission of
    the vendor whose `status` is `SUBMITTED` or `ACCEPTED`, and whose price cycle is
    `OPEN` or `CLOSED`, moves to `VOIDED` with `voided_reason` `VENDOR_DISQUALIFIED`."
    "a vendor denied out of `REAUTH_PENDING` was a counted member of its peer group, so
    that group's `member_count` is decremented by one and its `version` increments by one,
    whereas a vendor denied out of `IN_REVIEW` was never counted and no peer group is
    touched."
    "Only a vendor still in `APPLICANT` may be submitted; anything else is refused with
    `ERR_INVALID_VENDOR_STATE`."
    "The vendor must actually be `IN_REVIEW`, or the request is refused with
    `ERR_INVALID_VENDOR_STATE`."
    "The addressed entity is in a state that permits the requested transition, on every
    action endpoint. The error names the entity: `ERR_INVALID_VENDOR_STATE`,"

    Design: Corner/state_machines/denied_vendor_terminal_state_rejects_further_transitions
    """
    peer_group = fixtures.create_peer_group(api)
    category = fixtures.create_food_category(api)
    item = fixtures.create_food_item(api, category["id"])
    cycle = fixtures.create_price_cycle(api)
    vendor = fixtures.vendor_in_review(api, with_training=False)
    submission = fixtures.submit_price(
        api, vendor["id"], item["id"], cycle["id"], shelf_price_cents=320
    )

    denial_reason = "The store failed the on-site minimum stock pre-check."
    denied = validate_success(
        api.deny_vendor(
            vendor["id"],
            factories.denial_payload(denial_reason=denial_reason),
            SUPERVISOR_HEADERS,
        )
    )

    assert_vendor(
        denied,
        id=vendor["id"],
        authorization_status=VendorStatus.DENIED.value,
        denial_reason=denial_reason,
        peer_group_id=peer_group["id"],
    )

    voided = validate_success(api.get_price_submission(submission["id"], ANALYST_HEADERS))
    assert_price_submission(
        voided,
        id=submission["id"],
        status=SubmissionStatus.VOIDED.value,
        voided_reason=VoidedReason.VENDOR_DISQUALIFIED.value,
    )

    # The vendor was only IN_REVIEW, so it was never counted and the group is untouched.
    untouched = validate_success(api.get_peer_group(peer_group["id"], SUPERVISOR_HEADERS))
    assert_peer_group(untouched, member_count=0, version=1)

    validate_error(
        api.submit_application(vendor["id"], None, ANALYST_HEADERS),
        ApiErrorId.INVALID_VENDOR_STATE.value,
    )
    validate_error(
        api.authorize_vendor(vendor["id"], None, SUPERVISOR_HEADERS),
        ApiErrorId.INVALID_VENDOR_STATE.value,
    )
    validate_error(
        api.start_reauthorization(vendor["id"], None, ANALYST_HEADERS),
        ApiErrorId.INVALID_VENDOR_STATE.value,
    )
    validate_error(
        api.deny_vendor(
            vendor["id"],
            factories.denial_payload(denial_reason="A second denial attempt."),
            SUPERVISOR_HEADERS,
        ),
        ApiErrorId.INVALID_VENDOR_STATE.value,
    )

    final = validate_success(api.get_vendor(vendor["id"], SUPERVISOR_HEADERS))
    assert_vendor(
        final,
        authorization_status=VendorStatus.DENIED.value,
        denial_reason=denial_reason,
        authorized_at=None,
        reauthorization_due_at=None,
    )


def test_retire_peer_group_stamps_blocked_reason_on_in_review_members(api):
    """
    Retiring a band blocks the members still under review and spares the authorized ones.

    "Retirement, restricted to a `VendorUnitSupervisor`, sets `status` to `RETIRED` and
    stamps `retired_at` with the logical clock."
    "every vendor assigned to the retiring group whose `authorization_status` is
    `IN_REVIEW` or `REAUTH_PENDING` has its `authorization_blocked_reason` stamped with
    the explanation `PEER_GROUP_RETIRED`."
    "Members already `AUTHORIZED` keep operating and remain counted in `member_count`;
    retirement does not change the count."
    "The same request also recomputes `price_submission_complete` against the current
    price cycle — it stays false while no required item has an accepted submission — and
    clears `authorization_blocked_reason` back to null, because entering review resets any
    block inherited from an earlier round."
    "Its assigned peer group must still be `ACTIVE`, or `ERR_PEER_GROUP_RETIRED`. And
    `price_submission_complete` must be true, or `ERR_PRICE_SUBMISSIONS_INCOMPLETE`."
    "the open-case test before the peer group test, and the peer group test before
    submission completeness"

    Design: Corner/endpoints/retire_peer_group_stamps_blocked_reason_on_in_review_members
    """
    bundle = fixtures.published_ceiling_setup(api)
    second_vendor = fixtures.vendor_in_review(
        api,
        store_name="Bravo Market",
        reported_monthly_redemption_cents=7_000_000,
        training_completed_at="2026-07-20T00:00:00Z",
    )

    assert_vendor(
        second_vendor,
        authorization_status=VendorStatus.IN_REVIEW.value,
        peer_group_id=bundle["peer_group"]["id"],
        authorization_blocked_reason=None,
        price_submission_complete=False,
    )

    retired = validate_success(
        api.retire_peer_group(bundle["peer_group"]["id"], None, SUPERVISOR_HEADERS)
    )

    assert_peer_group(
        retired,
        id=bundle["peer_group"]["id"],
        status=PeerGroupStatus.RETIRED.value,
        retired_at=DEFAULT_LOGICAL_CLOCK_ISO,
        member_count=1,  # the authorized vendor stays counted
    )

    blocked = validate_success(api.get_vendor(second_vendor["id"], ANALYST_HEADERS))
    assert_vendor(
        blocked,
        authorization_status=VendorStatus.IN_REVIEW.value,
        authorization_blocked_reason=BlockedReason.PEER_GROUP_RETIRED.value,
    )

    operating = validate_success(api.get_vendor(bundle["vendor"]["id"], ANALYST_HEADERS))
    assert_vendor(
        operating,
        authorization_status=VendorStatus.AUTHORIZED.value,
        authorization_blocked_reason=None,
    )

    # The retired group is checked before submission completeness, which is also false.
    validate_error(
        api.authorize_vendor(second_vendor["id"], None, SUPERVISOR_HEADERS),
        ApiErrorId.PEER_GROUP_RETIRED.value,
    )
