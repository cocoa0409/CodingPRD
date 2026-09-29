"""
Vendor authorization lifecycle.

Four things are pinned here: the reauthorization loop that returns a vendor to
``AUTHORIZED`` without re-stamping its original authorization, the rejection ladder
that makes lapsed training outrank a retired peer group on authorize, the inclusive
peer group volume band bounds at submit-application, and the conservation of the
denormalized peer group membership headcount across a disqualification and its
closure.
"""

from test_helpers import (
    ANALYST_HEADERS,
    SUPERVISOR_HEADERS,
    assert_field_values,
    assert_peer_group,
    assert_sanction_case,
    assert_sanction_schedule,
    assert_vendor,
    factories,
    fixtures,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

# "A peer group's `member_count` is the number of vendors assigned to it whose
# `authorization_status` is `AUTHORIZED`, `REAUTH_PENDING`, or `SUSPENDED`."
_MEMBERSHIP_STATUSES = ("AUTHORIZED", "REAUTH_PENDING", "SUSPENDED")


# ---------------------------------------------------------------------------
# Local helpers
# ---------------------------------------------------------------------------


def _membership_headcount(api, peer_group_id):
    """A full recount of the vendors a peer group's ``member_count`` denormalizes."""
    vendors, _ = validate_paginated(
        api.list_vendors(
            SUPERVISOR_HEADERS, {"peer_group_id": peer_group_id, "limit": 100}
        )
    )
    return sum(
        1
        for vendor in vendors
        if vendor["peer_group_id"] == peer_group_id
        and vendor["authorization_status"] in _MEMBERSHIP_STATUSES
    )


def _retire_peer_group(api, peer_group_id):
    """Retire a peer group as the supervisor who owns configuration."""
    return get_success_data(
        api.retire_peer_group(peer_group_id, None, SUPERVISOR_HEADERS)
    )


def _authorized_vendor_at_the_reauth_window(api):
    """
    One AUTHORIZED vendor whose reauthorization window has just opened.

    Authorized at 2026-08-01, so ``reauthorization_due_at`` is 2029-08-01; the clock
    is then moved to 2029-05-03, exactly ninety days earlier, and a fresh ANNUAL
    session is recorded so training is current again.
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    bundle = fixtures.authorized_vendor_setup(api)
    fixtures.set_clock(api, "2029-05-03T00:00:00Z")
    fixtures.record_training(
        api,
        bundle["vendor"]["id"],
        completed_at="2029-05-01T00:00:00Z",
        training_type="ANNUAL",
    )
    return bundle


def _in_review_vendor_under_a_retired_group_with_lapsed_training(api):
    """
    A vendor IN_REVIEW whose readiness is complete but whose two gates both fail.

    Its peer group is retired at 2026-08-01 and the clock is then moved to
    2027-08-01, past the 2027-07-15 expiry of the INITIAL training session.
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    bundle = fixtures.bootstrap_catalogue(api)
    accepted = fixtures.vendor_with_accepted_price(
        api, bundle["milk_item"]["id"], bundle["cycle"]["id"]
    )
    bundle["vendor"] = accepted["vendor"]
    bundle["submission"] = accepted["submission"]
    _retire_peer_group(api, bundle["peer_group"]["id"])
    fixtures.set_clock(api, "2027-08-01T00:00:00Z")
    return bundle


def _two_touching_supermarket_bands(api):
    """
    Two ACTIVE supermarket peer groups whose volume bands touch at 20,000,000 cents.

    PG-SUPER-A covers [5000000, 20000000] and PG-SUPER-B covers
    [20000000, 40000000], so the shared bound is eligible for both.
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    group_a = fixtures.create_peer_group(
        api,
        code="PG-SUPER-A",
        store_type="SUPERMARKET",
        min_monthly_redemption_cents=5_000_000,
        max_monthly_redemption_cents=20_000_000,
        mar_method="PEER_MEDIAN",
        competitive_allowance_pct=0.05,
        min_submissions_for_ceiling=3,
        min_stock_multiplier=1.5,
    )
    group_b = fixtures.create_peer_group(
        api,
        code="PG-SUPER-B",
        store_type="SUPERMARKET",
        min_monthly_redemption_cents=20_000_000,
        max_monthly_redemption_cents=40_000_000,
        mar_method="PEER_MEDIAN",
        competitive_allowance_pct=0.05,
        min_submissions_for_ceiling=3,
        min_stock_multiplier=2.0,
    )
    return group_a, group_b


def _supermarket_applicant(api, store_name, reported_monthly_redemption_cents):
    """An APPLICANT supermarket reporting the given monthly redemption volume."""
    return fixtures.create_vendor(
        api,
        store_name=store_name,
        store_type="SUPERMARKET",
        reported_monthly_redemption_cents=reported_monthly_redemption_cents,
    )


def _served_class_b_case_on_one_of_two_members(api):
    """
    Two AUTHORIZED vendors in one peer group, with a CLASS_B notice served on one.

    The cycle is deliberately left OPEN so the disqualification void cascade has a
    live submission to act on. The clock ends at 2026-08-17, one day past the
    2026-08-16 election deadline, so disqualification may be imposed.
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    bundle = fixtures.two_authorized_vendors_setup(api)
    vendor_one = fixtures.get_vendor(api, bundle["vendor"]["id"])
    bundle["vendor_version_at_open"] = vendor_one["version"]
    case = fixtures.open_sanction_case(
        api, vendor_one["id"], vendor_one["version"], violation_code="CLASS_B"
    )
    bundle["case"] = fixtures.serve_notice(api, case["id"])
    fixtures.set_clock(api, "2026-08-17T00:00:00Z")
    return bundle


# ---------------------------------------------------------------------------
# The reauthorization loop
# ---------------------------------------------------------------------------


def test_start_reauthorization_at_exactly_ninety_days_before_the_due_date(api):
    """
    Opening the cycle at the inclusive window boundary moves the vendor to REAUTH_PENDING.

    "An analyst opens it, moving `AUTHORIZED → REAUTH_PENDING`, but only once the
    window has been reached: the logical clock must be at or after ninety days before
    `reauthorization_due_at`, and the boundary is inclusive, so a clock landing
    exactly ninety days before the due date qualifies." "Opening the cycle recomputes
    `accepted_submission_count` and `price_submission_complete` against the current
    cycle, and stamps `reauth_blocked_reason` with the explanation
    `PENDING_COMPLIANCE_BUY` when `reauthorization_hold` is already true at that
    moment; otherwise the reason is set to null." "On success the vendor gains
    `authorized_at` from the logical clock and a `reauthorization_due_at` set to
    thirty-six calendar months after `authorized_at`."

    Design: Difficulty/non_linear_state_machine/vendor_reauthorization_cycle_returns_to_authorized
    """
    bundle = _authorized_vendor_at_the_reauth_window(api)

    vendor = validate_success(
        api.start_reauthorization(bundle["vendor"]["id"], None, ANALYST_HEADERS)
    )

    assert_vendor(
        vendor,
        authorization_status="REAUTH_PENDING",
        reauth_blocked_reason=None,
        reauth_completed_count=0,
        # authorized 2026-08-01, so the due date is 36 calendar months later
        reauthorization_due_at="2029-08-01T00:00:00.000Z",
        accepted_submission_count=1,
        price_submission_complete=True,
        reauthorization_hold=False,
    )


def test_completing_reauthorization_advances_the_due_date_from_its_previous_value(api):
    """
    The loop closes back on AUTHORIZED and the next due date comes from the old one.

    "Completing reauthorization is a supervisor decision moving
    `REAUTH_PENDING → AUTHORIZED`, and it repeats the authorization gauntlet with one
    addition." "On success, `reauthorization_due_at` is advanced by thirty-six
    calendar months **from its own previous value**, never from the logical clock, so
    that a vendor completing late does not gain extra time and cycles never drift;
    `reauth_completed_count` rises by one; and `reauth_blocked_reason` is cleared to
    null." "This closes the cycle `AUTHORIZED → REAUTH_PENDING → AUTHORIZED`."

    Design: Difficulty/non_linear_state_machine/vendor_reauthorization_cycle_returns_to_authorized
    """
    bundle = _authorized_vendor_at_the_reauth_window(api)
    get_success_data(
        api.start_reauthorization(bundle["vendor"]["id"], None, ANALYST_HEADERS)
    )

    vendor = validate_success(
        api.complete_reauthorization(bundle["vendor"]["id"], None, SUPERVISOR_HEADERS)
    )

    assert_vendor(
        vendor,
        authorization_status="AUTHORIZED",
        reauth_completed_count=1,
        reauth_blocked_reason=None,
        # 2029-08-01 plus 36 calendar months, not 2032-05-03 from the 2029-05-03 clock
        reauthorization_due_at="2032-08-01T00:00:00.000Z",
    )


def test_reauthorization_loop_preserves_the_original_authorization_and_the_headcount(api):
    """
    Re-entering AUTHORIZED does not re-stamp authorized_at or move the member count.

    "On success the vendor gains `authorized_at` from the logical clock and a
    `reauthorization_due_at` set to thirty-six calendar months after `authorized_at`."
    "A peer group's `member_count` is the number of vendors assigned to it whose
    `authorization_status` is `AUTHORIZED`, `REAUTH_PENDING`, or `SUSPENDED`." "From
    that instant the server derives `training_expires_at` by adding twelve calendar
    months to `training_completed_at` under the month arithmetic of §2.5."

    Design: Difficulty/non_linear_state_machine/vendor_reauthorization_cycle_returns_to_authorized
    """
    bundle = _authorized_vendor_at_the_reauth_window(api)
    peer_group_id = bundle["peer_group"]["id"]

    get_success_data(
        api.start_reauthorization(bundle["vendor"]["id"], None, ANALYST_HEADERS)
    )
    pending_group = fixtures.get_peer_group(api, peer_group_id)
    # a REAUTH_PENDING vendor is still a counted member
    assert_peer_group(pending_group, member_count=1)
    assert _membership_headcount(api, peer_group_id) == 1

    vendor = validate_success(
        api.complete_reauthorization(bundle["vendor"]["id"], None, SUPERVISOR_HEADERS)
    )

    assert_vendor(
        vendor,
        # the vendor was authorized at the default logical clock and never re-stamped
        authorized_at="2026-08-01T00:00:00.000Z",
        training_type="ANNUAL",
        # ANNUAL session completed 2029-05-01 plus twelve calendar months
        training_expires_at="2030-05-01T00:00:00.000Z",
    )
    assert_peer_group(fixtures.get_peer_group(api, peer_group_id), member_count=1)
    assert _membership_headcount(api, peer_group_id) == 1


# ---------------------------------------------------------------------------
# The rejection ladder on authorize
# ---------------------------------------------------------------------------


def test_authorize_reports_lapsed_training_before_a_retired_peer_group(api):
    """
    With both gates failing, only the training rejection surfaces.

    "When a request violates more than one rule, exactly one error is returned: the
    one belonging to the lowest-numbered rule in the ladder below." "On
    `POST /vendors/{id}/authorize` and `POST /vendors/{id}/complete-reauthorization`,
    training currency — otherwise `ERR_VENDOR_TRAINING_EXPIRED`." "Ordered as the
    ladder requires, training currency is checked before the open-case test, the
    open-case test before the peer group test, and the peer group test before
    submission completeness — so a vendor with lapsed training and a retired peer
    group reports the training failure." "Training is **current** if and only if
    `training_expires_at` is not null and the logical clock is strictly earlier than
    it; a clock exactly equal to `training_expires_at` means the training has lapsed."

    Design: Difficulty/priority_pair_validation_conflict/training_safety_beats_peer_group_referential_on_authorize
    """
    bundle = _in_review_vendor_under_a_retired_group_with_lapsed_training(api)

    response = api.authorize_vendor(bundle["vendor"]["id"], None, SUPERVISOR_HEADERS)
    validate_error(response, "ERR_VENDOR_TRAINING_EXPIRED")

    vendor = fixtures.get_vendor(api, bundle["vendor"]["id"])
    assert_vendor(
        vendor,
        # INITIAL session completed 2026-07-15 plus twelve calendar months
        training_expires_at="2027-07-15T00:00:00.000Z",
        price_submission_complete=True,
    )


def test_refreshing_training_reveals_the_retired_peer_group_rejection(api):
    """
    Satisfying the higher rule makes the lower-numbered failure observable.

    "On `POST /vendors/{id}/authorize` and
    `POST /vendors/{id}/complete-reauthorization`, the vendor's assigned peer group is
    `ACTIVE` — otherwise `ERR_PEER_GROUP_RETIRED`." "Recording a new session simply
    overwrites `training_type`, `training_completed_at`, and `training_expires_at`;
    the system keeps only the most recent session." "And `price_submission_complete`
    must be true, or `ERR_PRICE_SUBMISSIONS_INCOMPLETE`."

    Design: Difficulty/priority_pair_validation_conflict/training_safety_beats_peer_group_referential_on_authorize
    """
    bundle = _in_review_vendor_under_a_retired_group_with_lapsed_training(api)

    refreshed = get_success_data(
        api.record_training(
            bundle["vendor"]["id"],
            factories.training_payload(
                training_type="ANNUAL", completed_at="2027-08-01T00:00:00Z"
            ),
            ANALYST_HEADERS,
        )
    )
    # 2027-08-01 plus twelve calendar months, so training is current again
    assert_vendor(refreshed, training_expires_at="2028-08-01T00:00:00.000Z")

    response = api.authorize_vendor(bundle["vendor"]["id"], None, SUPERVISOR_HEADERS)
    validate_error(response, "ERR_PEER_GROUP_RETIRED")

    assert_vendor(fixtures.get_vendor(api, bundle["vendor"]["id"]), authorized_at=None)


def test_retiring_a_group_blocks_its_member_under_review_without_counting_it(api):
    """
    Retirement stamps the block reason on the member under review and leaves the count at zero.

    "Retirement, restricted to a `VendorUnitSupervisor`, sets `status` to `RETIRED`
    and stamps `retired_at` with the logical clock." "A `RETIRED` group never enters
    the candidate set for a new assignment, and it blocks the authorization of members
    that were still being processed: every vendor assigned to the retiring group whose
    `authorization_status` is `IN_REVIEW` or `REAUTH_PENDING` has its
    `authorization_blocked_reason` stamped with the explanation `PEER_GROUP_RETIRED`."
    "Vendors in `APPLICANT`, `IN_REVIEW`, `DENIED`, or `DISQUALIFIED` are not counted,
    and vendors with no peer group assigned are not counted at all."

    Design: Difficulty/priority_pair_validation_conflict/training_safety_beats_peer_group_referential_on_authorize
    """
    bundle = _in_review_vendor_under_a_retired_group_with_lapsed_training(api)

    peer_group = fixtures.get_peer_group(api, bundle["peer_group"]["id"])
    assert_peer_group(
        peer_group,
        status="RETIRED",
        # retirement happened while the clock read the default instant
        retired_at="2026-08-01T00:00:00.000Z",
        member_count=0,
    )

    assert_vendor(
        fixtures.get_vendor(api, bundle["vendor"]["id"]),
        authorization_status="IN_REVIEW",
        authorization_blocked_reason="PEER_GROUP_RETIRED",
    )


# ---------------------------------------------------------------------------
# Peer group band bounds at submit-application
# ---------------------------------------------------------------------------


def test_volume_one_cent_below_the_lower_band_bound_matches_no_peer_group(api):
    """
    A reported volume just under the lowest band leaves the applicant unassigned.

    "First, the eligible candidates are collected: every peer group whose `status` is
    `ACTIVE`, whose `store_type` equals the vendor's `store_type`, whose
    `min_monthly_redemption_cents` is less than or equal to the vendor's
    `reported_monthly_redemption_cents`, and whose `max_monthly_redemption_cents` is
    either null or greater than or equal to the vendor's reported volume." "Fourth, if
    the candidate set is empty, no assignment happens and the submission is refused
    with `ERR_NO_PEER_GROUP_MATCH` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/peer_group_band_upper_bound_is_inclusive_on_submit_application
    """
    _two_touching_supermarket_bands(api)
    # one cent below PG-SUPER-A's inclusive lower bound of 5,000,000
    vendor = _supermarket_applicant(api, "Below Lower Bound", 4_999_999)

    response = api.submit_application(vendor["id"], None, ANALYST_HEADERS)
    validate_error(response, "ERR_NO_PEER_GROUP_MATCH")

    assert_vendor(
        fixtures.get_vendor(api, vendor["id"]),
        authorization_status="APPLICANT",
        peer_group_id=None,
    )


def test_volume_exactly_at_the_lower_band_bound_is_assigned_inclusively(api):
    """
    The lower bound is inclusive, and assignment alone does not create a member.

    "Both bounds are inclusive when a vendor is matched against them." "Submitting the
    application moves the vendor from `APPLICANT` to `IN_REVIEW` and is the moment the
    peer group is chosen." "Vendors in `APPLICANT`, `IN_REVIEW`, `DENIED`, or
    `DISQUALIFIED` are not counted, and vendors with no peer group assigned are not
    counted at all."

    Design: Difficulty/boundary_precision_check/peer_group_band_upper_bound_is_inclusive_on_submit_application
    """
    group_a, group_b = _two_touching_supermarket_bands(api)
    # exactly PG-SUPER-A's inclusive lower bound
    applicant = _supermarket_applicant(api, "At Lower Bound", 5_000_000)

    vendor = validate_success(
        api.submit_application(applicant["id"], None, ANALYST_HEADERS)
    )

    assert_vendor(
        vendor, authorization_status="IN_REVIEW", peer_group_id=group_a["id"]
    )
    assert_peer_group(fixtures.get_peer_group(api, group_a["id"]), member_count=0)
    assert_peer_group(fixtures.get_peer_group(api, group_b["id"]), member_count=0)


def test_volume_at_the_shared_band_bound_picks_the_narrower_band(api):
    """
    At the instant both bands cover, the narrower band width wins.

    "Both bounds are inclusive when a vendor is matched against them." "Second, each
    candidate is measured by band width: the upper bound minus the lower bound, where a
    null upper bound is treated as the sentinel value of one trillion cents — that is,
    1,000,000,000,000 cents — so an unbounded band is always the widest and therefore
    the least specific match." "Third, the candidates are ordered by band width
    ascending, then by `min_monthly_redemption_cents` ascending, then by `created_at`
    ascending, and the first candidate in that order wins; the vendor's
    `peer_group_id` is set to that group's identifier."

    Design: Difficulty/boundary_precision_check/peer_group_band_upper_bound_is_inclusive_on_submit_application
    """
    group_a, group_b = _two_touching_supermarket_bands(api)
    # 20,000,000 is PG-SUPER-A's inclusive upper bound and PG-SUPER-B's inclusive lower bound
    applicant = _supermarket_applicant(api, "At Shared Bound", 20_000_000)

    vendor = validate_success(
        api.submit_application(applicant["id"], None, ANALYST_HEADERS)
    )

    # widths 20,000,000 - 5,000,000 = 15,000,000 against 40,000,000 - 20,000,000 = 20,000,000
    assert_vendor(vendor, peer_group_id=group_a["id"])
    assert vendor["peer_group_id"] != group_b["id"]


def test_volume_one_cent_past_the_upper_band_bound_falls_to_the_next_band(api):
    """
    One cent past the inclusive upper bound leaves only the wider band eligible.

    "The group declares the `store_type` it covers, one of `SUPERMARKET`,
    `SUPERSTORE`, `MEDIUM_GROCERY`, `SMALL_GROCERY`, or `PHARMACY`, and a monthly
    redemption volume band whose lower bound `min_monthly_redemption_cents` must be at
    least 0 and whose upper bound `max_monthly_redemption_cents` is either null,
    meaning the band is unbounded above, or a value at least equal to the lower bound."
    "Both bounds are inclusive when a vendor is matched against them."

    Design: Difficulty/boundary_precision_check/peer_group_band_upper_bound_is_inclusive_on_submit_application
    """
    group_a, group_b = _two_touching_supermarket_bands(api)
    # one cent past PG-SUPER-A's inclusive upper bound of 20,000,000
    applicant = _supermarket_applicant(api, "Above Upper Bound", 20_000_001)

    vendor = validate_success(
        api.submit_application(applicant["id"], None, ANALYST_HEADERS)
    )

    assert_vendor(
        vendor, authorization_status="IN_REVIEW", peer_group_id=group_b["id"]
    )
    assert vendor["peer_group_id"] != group_a["id"]


# ---------------------------------------------------------------------------
# Membership headcount across a disqualification and its closure
# ---------------------------------------------------------------------------


def test_class_b_case_on_a_two_member_group_escalates_to_effective_tier_four(api):
    """
    The schedule fixed at open time escalates a tier-3 base to effective tier 4 and caps the penalty.

    "The `base_tier` comes from the violation class: `CLASS_A` is tier 4, `CLASS_B` is
    tier 3, `CLASS_C` is tier 2, and `CLASS_D` is tier 1." "The `case_points` come from
    the **base** tier and never from the effective one: tier 1 carries 1 point, tier 2
    carries 2, tier 3 carries 4, and tier 4 carries 8." "The escalation step is the
    number of escalation thresholds — there are two, at 4 points and at 8 points — that
    the snapshot plus this case's own `case_points` reaches or exceeds." "The
    `effective_tier` is the base tier plus that escalation step, capped at 4."
    "`disqualification_months` is 0 at tier 1, 6 at tier 2, 12 at tier 3, and 36 at
    tier 4 — a tier-1 case therefore carries no disqualification at all." "The
    `cmp_amount_cents` is the vendor's `avg_monthly_redemption_cents` multiplied by the
    tier's monthly multiplier — 0.05 at tier 1, 0.10 at tier 2, 0.25 at tier 3, and
    0.50 at tier 4 — multiplied again by the tier's month count — 1 month at tier 1, 3
    at tier 2, 6 at tier 3, and 12 at tier 4 — then rounded half up to a whole cent,
    and finally capped: the penalty is the lesser of that rounded figure and 5,625,000
    cents, which is the statutory ceiling of fifty-six thousand two hundred fifty
    dollars." "A successful create increments the vendor's `version` by one."

    Design: Difficulty/compensating_invariant/authorize_then_disqualify_conserves_peer_group_membership_headcount
    """
    bundle = _served_class_b_case_on_one_of_two_members(api)

    case = fixtures.get_sanction_case(api, bundle["case"]["id"])
    assert_sanction_schedule(
        case,
        base_tier=3,
        case_points=4,
        cumulative_points_at_open=0,
        # 0 + 4 reaches the first threshold of 4 but not the second of 8, so 3 + 1
        effective_tier=4,
        disqualification_months=36,
        cmp_permitted=True,
        # tier 4 x 12 months on 6,000,000 -> round_half_up(6000000 x 0.50 x 12)
        # = 36,000,000, clamped to the statutory ceiling of 5,625,000
        cmp_amount_cents=5_625_000,
    )
    assert_sanction_case(
        case,
        status="NOTICE_SERVED",
        resolution="NONE",
        cmp_paid_cents=0,
        notice_served_at="2026-08-01T00:00:00.000Z",
        # fifteen days after the notice
        response_due_at="2026-08-16T00:00:00.000Z",
    )

    vendor = fixtures.get_vendor(api, bundle["vendor"]["id"])
    assert vendor["version"] == bundle["vendor_version_at_open"] + 1
    assert_peer_group(
        fixtures.get_peer_group(api, bundle["peer_group"]["id"]), member_count=2
    )


def test_imposing_disqualification_decrements_the_headcount_exactly_once(api):
    """
    Disqualifying one of two members drops the denormalized count to a true recount of one.

    "A `VendorUnitSupervisor` or a `ComplianceInvestigator` imposes disqualification,
    moving the case `NOTICE_SERVED → DISQUALIFICATION_IMPOSED` and setting `resolution`
    to `DISQUALIFICATION`." "`disqualified_until` is set to the logical clock plus
    `disqualification_months` calendar months." "`sanction_points` rises by the case's
    `case_points`." "The vendor's peer group has its `member_count` decremented by one
    and its `version` incremented by one." "Summed across all peer groups,
    `member_count` always equals the number of vendors with a non-null `peer_group_id`
    in one of those three statuses — a global invariant that must survive every forward
    action and every compensating one."

    Design: Difficulty/compensating_invariant/authorize_then_disqualify_conserves_peer_group_membership_headcount
    """
    bundle = _served_class_b_case_on_one_of_two_members(api)
    group_before = fixtures.get_peer_group(api, bundle["peer_group"]["id"])

    case = validate_success(
        api.impose_disqualification(bundle["case"]["id"], None, SUPERVISOR_HEADERS)
    )

    assert_sanction_case(
        case, status="DISQUALIFICATION_IMPOSED", resolution="DISQUALIFICATION"
    )
    assert_vendor(
        fixtures.get_vendor(api, bundle["vendor"]["id"]),
        authorization_status="DISQUALIFIED",
        # 2026-08-17 plus 36 calendar months
        disqualified_until="2029-08-17T00:00:00.000Z",
        sanction_points=4,
    )

    group_after = fixtures.get_peer_group(api, bundle["peer_group"]["id"])
    assert_peer_group(group_after, member_count=1)
    assert group_after["version"] == group_before["version"] + 1
    assert _membership_headcount(api, bundle["peer_group"]["id"]) == 1
    assert_vendor(
        fixtures.get_vendor(api, bundle["vendor_two"]["id"]),
        authorization_status="AUTHORIZED",
    )


def test_disqualification_voids_only_the_disqualified_vendors_live_submissions(api):
    """
    The void cascade is scoped to the disqualified vendor and to open or closed cycles.

    "Every PriceSubmission of the vendor whose `status` is `SUBMITTED` or `ACCEPTED`,
    and whose price cycle is `OPEN` or `CLOSED`, moves to `VOIDED` with `voided_reason`
    `VENDOR_DISQUALIFIED`." "Because those visits are now cancelled,
    `compliance_buy_required` is set to false and `reauthorization_hold` is recomputed
    to false."

    Design: Difficulty/compensating_invariant/authorize_then_disqualify_conserves_peer_group_membership_headcount
    """
    bundle = _served_class_b_case_on_one_of_two_members(api)

    validate_success(
        api.impose_disqualification(bundle["case"]["id"], None, SUPERVISOR_HEADERS)
    )

    assert_field_values(
        fixtures.get_price_submission(api, bundle["submission"]["id"]),
        status="VOIDED",
        voided_reason="VENDOR_DISQUALIFIED",
    )
    assert_field_values(
        fixtures.get_price_submission(api, bundle["submission_two"]["id"]),
        status="ACCEPTED",
        voided_reason=None,
    )
    assert_vendor(
        fixtures.get_vendor(api, bundle["vendor"]["id"]),
        compliance_buy_required=False,
        reauthorization_hold=False,
    )


def test_closing_the_disqualification_branch_neither_recredits_points_nor_the_headcount(api):
    """
    The join point moves no money, adds no points, and leaves the headcount alone.

    "Closing from `DISQUALIFICATION_IMPOSED` needs no payment and moves no money; the
    vendor's `sanction_points` were already incremented when the disqualification was
    imposed and are emphatically not incremented a second time." "Either way the case's
    `status` becomes `CLOSED`." "Every transition into or out of that membership set
    adjusts the count by one and increments the peer group's `version` by one."

    Design: Difficulty/compensating_invariant/authorize_then_disqualify_conserves_peer_group_membership_headcount
    """
    bundle = _served_class_b_case_on_one_of_two_members(api)
    fixtures.impose_disqualification(api, bundle["case"]["id"], headers=SUPERVISOR_HEADERS)
    group_after_impose = fixtures.get_peer_group(api, bundle["peer_group"]["id"])

    case = validate_success(
        api.close_sanction_case(bundle["case"]["id"], None, SUPERVISOR_HEADERS)
    )

    assert_sanction_case(
        case,
        status="CLOSED",
        resolution="DISQUALIFICATION",
        # no payment is carried on this branch
        cmp_paid_cents=0,
    )
    assert_vendor(
        fixtures.get_vendor(api, bundle["vendor"]["id"]),
        # the four points were credited at imposition, not again at closure
        sanction_points=4,
        authorization_status="DISQUALIFIED",
    )

    group_after_close = fixtures.get_peer_group(api, bundle["peer_group"]["id"])
    assert_peer_group(group_after_close, member_count=1)
    assert group_after_close["version"] == group_after_impose["version"]
    assert _membership_headcount(api, bundle["peer_group"]["id"]) == 1
