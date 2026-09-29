"""Where the programme's concurrency guards and its rate thresholds interlock.

Three of the programme's hardest behaviours only show themselves when several
layers are driven at once. The two optimistic-concurrency guards protect
different parents, and the certification guard is the sharper of the pair
because syndication bumps the very version it was authorised with, so a dealer
replaying its own successful publication is stale against itself. The claim
axis and the audit axis both end in a dealer suspension, but they fire on
different quantities: the claim axis on a ratio crossing a threshold, where two
thresholds are crossed at once and the harsher must win, and the audit axis on a
cumulative count, so a dealer whose failure rate is already maximal keeps
trading until the second failure lands. Each suspension then drags the dealer's
pending certifications and published listings down with it, inside the request
that caused it.
"""

from test_helpers import (
    ADMIN,
    AUDIT_FAIL_SUSPENSION_COUNT,
    AUDIT_SAMPLE_MIN_PER_RUN,
    AUDIT_SAMPLE_PCT,
    CLOCK_EPOCH,
    LISTING_REMOVAL_SLA_HOURS,
    ApiErrorId,
    active_certification,
    approve_claim,
    assert_audit_run_summary,
    assert_audit_sample,
    assert_dealer,
    assert_instant_equals,
    audit_samples_of,
    ceil_count,
    claims_of,
    create_certification_payload,
    create_listing,
    create_vehicle,
    draw_audit_run,
    file_claim,
    iso_shift,
    listings_of,
    passed_inspection,
    read_certification,
    read_dealer,
    read_vehicle,
    record_finding,
    record_history_event,
    round_half_up,
    submit_certification,
    submitted_certification,
    syndicate_listing,
    syndicate_payload,
    syndicated_listing,
    validate_error,
    validate_paginated,
)


def _listing_row(api, certification_id, listing_id):
    """Re-read one listing through its certification's collection."""
    rows = [row for row in listings_of(api, certification_id) if row["id"] == listing_id]
    assert len(rows) == 1, f"exactly one listing must carry id {listing_id}"
    return rows[0]


def test_a_certification_submission_must_echo_the_vehicle_version_it_last_read(
    api, program
):
    """Opening the inspection invalidates the version captured at vehicle creation.

    PRD §2.8: "Submitting a certification requires `expected_vehicle_version`,
    carrying the `version` of the vehicle the submitting dealer last read. If
    that value does not equal the vehicle's current `version`, the submission is
    rejected with `ERR_STALE_VEHICLE_VERSION` (HTTP 412)."
    PRD §2.8: "so a client that wants to write twice in a row must re-read the
    parent between the two writes"
    PRD §3.2: "Every event sets `last_history_event_type` to the event just
    applied and `last_history_event_at` to the logical clock, and increments the
    vehicle's `version` by 1."

    Design: Corner/cross-cutting complexity layers/both_occ_rules_reject_stale_parent_versions
    """
    vehicle = create_vehicle(api)
    at_creation = vehicle["version"]
    assert at_creation == 1
    walk = passed_inspection(api, program, vehicle=vehicle)
    fresh = read_vehicle(api, walk.vehicle_id, program.dealer_headers)
    assert fresh["version"] > at_creation, "opening the inspection moved the vehicle"
    assert fresh["cpo_state"] == "CERTIFICATION_PENDING"

    stale = api.create_certification(
        create_certification_payload(walk.vehicle_id, walk.inspection_id, at_creation),
        program.dealer_headers,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VEHICLE_VERSION)

    dealer = read_dealer(api, program.dealer_id)
    assert dealer["lifetime_submitted_count"] == 0, "the refused submission minted nothing"
    assert dealer["active_certification_count"] == 0
    orphans, orphan_meta = validate_paginated(
        api.list_certifications(ADMIN, params={"vehicle_id": walk.vehicle_id})
    )
    assert orphans == []
    assert orphan_meta["total_count"] == 0
    untouched = read_vehicle(api, walk.vehicle_id, program.dealer_headers)
    assert untouched["version"] == fresh["version"], "a refused write moves no version"

    certification = submit_certification(
        api,
        program.dealer_headers,
        walk.vehicle_id,
        walk.inspection_id,
        expected_vehicle_version=fresh["version"],
    )
    assert certification["status"] == "SUBMITTED", (
        "the guard compares versions rather than refusing outright"
    )
    assert read_dealer(api, program.dealer_id)["lifetime_submitted_count"] == 1
    after_submission = read_vehicle(api, walk.vehicle_id, program.dealer_headers)
    assert after_submission["version"] == fresh["version"] + 1, (
        "the guarded write advances the parent it guarded against"
    )

    record_history_event(api, walk.vehicle_id, "ODOMETER_UPDATE", odometer_miles=63000)
    after_event = read_vehicle(api, walk.vehicle_id, program.dealer_headers)
    assert after_event["version"] == after_submission["version"] + 1, (
        "a write that carries no concurrency field still moves the guarded version"
    )
    assert after_event["odometer_miles"] == 63000
    assert after_event["last_history_event_type"] == "ODOMETER_UPDATE"


def test_syndication_invalidates_the_certification_version_it_was_authorised_with(
    api, active_walk
):
    """Replaying a successful publication is stale against the publication itself.

    PRD §2.8: "Syndicating a listing requires `expected_certification_version`,
    carrying the `version` of the certification the dealer last read."
    PRD §2.8: "If that value does not equal the certification's current
    `version`, the syndication is rejected with
    `ERR_STALE_CERTIFICATION_VERSION` (HTTP 412)."
    PRD §3.8: "the published content generation must name the generation the
    publication itself produced"

    Design: Corner/cross-cutting complexity layers/both_occ_rules_reject_stale_parent_versions
    """
    listing = create_listing(api, active_walk.dealer_headers, active_walk.certification_id)
    assert listing["status"] == "DRAFT"
    assert listing["syndicated_snapshot_version"] is None
    authorised = read_certification(api, active_walk.certification_id)["version"]

    published = syndicate_listing(
        api, listing["id"], active_walk.dealer_headers, authorised
    )
    assert published["status"] == "SYNDICATED"
    assert published["syndicated_snapshot_version"] == authorised + 1, (
        "the snapshot names the generation syndication itself produced"
    )
    assert published["syndicated_snapshot_version"] > authorised
    assert_instant_equals(published["syndicated_at"], CLOCK_EPOCH, "syndicated_at")
    assert read_certification(api, active_walk.certification_id)["version"] == authorised + 1

    replay = api.syndicate_listing(
        listing["id"], syndicate_payload(authorised), active_walk.dealer_headers
    )
    validate_error(replay, ApiErrorId.ERR_STALE_CERTIFICATION_VERSION)

    survived = _listing_row(api, active_walk.certification_id, listing["id"])
    assert survived["status"] == "SYNDICATED"
    assert survived["syndicated_snapshot_version"] == published["syndicated_snapshot_version"]
    assert survived["version"] == published["version"], "the refused replay moved nothing"
    refreshed_parent = read_certification(api, active_walk.certification_id)
    assert refreshed_parent["version"] == authorised + 1

    republished = syndicate_listing(
        api, listing["id"], active_walk.dealer_headers, refreshed_parent["version"]
    )
    assert republished["status"] == "SYNDICATED", (
        "the self-loop back into SYNDICATED is reachable only after a re-read"
    )
    assert republished["syndicated_snapshot_version"] == authorised + 2
    assert (
        republished["syndicated_snapshot_version"]
        > published["syndicated_snapshot_version"]
    )
    assert read_certification(api, active_walk.certification_id)["version"] == authorised + 2


def test_one_approved_claim_suspends_a_single_activation_dealer_and_forces_takedowns(
    api, program
):
    """A ratio of 1.00 crosses both thresholds and must resolve to the harsher one.

    PRD §3.9: "when `dealer_ratio_snapshot_before` is at or above the
    programme's probation threshold of 0.25, the share is the programme's
    probation claim share of 0.80, and otherwise the share is 1.00"
    PRD §3.9: "When the post-claim `claim_ratio_effective` is at or above the
    programme's suspension threshold of 0.40, `privilege_status` becomes
    `SUSPENDED` with `privilege_reason` `CLAIM_RATIO_SUSPENSION`."
    PRD §3.9: "every certification of that dealer still in `SUBMITTED` moves to
    `REJECTED` with `rejection_reason` `DEALER_SUSPENDED`, each releasing its
    vehicle's certification slot and moving that vehicle's `cpo_state` to
    `NOT_CERTIFIED`, and every listing of that dealer in `SYNDICATED` moves to
    `WITHDRAWN` with `withdrawal_reason` `DEALER_SUSPENDED` and a
    `removal_due_at` deadline"
    PRD §3.8: "a `removal_due_at` equal to `withdrawn_at` plus the programme's
    takedown window"

    Design: Corner/cross-cutting complexity layers/claim_ratio_crosses_suspension_threshold_and_forces_takedowns
    """
    live = active_certification(api, program)
    listing = syndicated_listing(api, live)
    pending = submitted_certification(api, program)
    assert pending.certification["status"] == "SUBMITTED"

    before = read_dealer(api, program.dealer_id)
    assert before["lifetime_activated_count"] == 1
    assert before["approved_claim_count_lifetime"] == 0
    assert before["claim_ratio_variant"] == "LIFETIME_CUMULATIVE"
    assert before["claim_ratio_effective"] == 0.00
    assert before["audit_fail_rate"] == 0.00
    assert before["risk_score"] == 0
    assert before["privilege_status"] == "ACTIVE"
    assert before["privilege_reason"] is None

    claim = file_claim(api, program.dealer_headers, live.certification_id)
    assert claim["status"] == "SUBMITTED"
    assert claim["claimed_amount_cents"] == 100000

    adjudicated = approve_claim(api, claim["id"])
    assert adjudicated["status"] == "APPROVED"
    assert adjudicated["dealer_ratio_snapshot_before"] == 0.00, (
        "the snapshot is taken before this claim joins the count"
    )
    assert adjudicated["approved_amount_cents"] == 100000, (
        "a snapshot below the probation threshold pays the claim in full"
    )
    assert_instant_equals(adjudicated["adjudicated_at"], CLOCK_EPOCH, "adjudicated_at")

    after = read_dealer(api, program.dealer_id)
    assert after["approved_claim_count_lifetime"] == 1
    assert after["approved_claim_count_window"] == 0, (
        "the repair date falls after the trailing window's closing edge"
    )
    assert after["claim_ratio_variant"] == "LIFETIME_CUMULATIVE"
    assert after["claim_ratio_effective"] == 1.00
    assert after["audit_fail_rate"] == 0.00
    assert after["risk_score"] == 60
    assert after["risk_score"] == round_half_up(1.00 * 100 * 0.60 + 0.00 * 100 * 0.40)
    assert after["privilege_status"] == "SUSPENDED"
    assert after["privilege_reason"] == "CLAIM_RATIO_SUSPENSION", (
        "1.00 clears the suspension threshold, so probation must not win"
    )
    assert after["lifetime_activated_count"] == 1
    assert after["active_certification_count"] == 1
    assert_dealer(after)

    withdrawn = _listing_row(api, live.certification_id, listing["id"])
    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["withdrawal_reason"] == "DEALER_SUSPENDED"
    assert_instant_equals(withdrawn["withdrawn_at"], CLOCK_EPOCH, "withdrawn_at")
    assert_instant_equals(
        withdrawn["removal_due_at"],
        iso_shift(CLOCK_EPOCH, hours=LISTING_REMOVAL_SLA_HOURS),
        "removal_due_at",
    )
    assert withdrawn["version"] == listing["version"] + 1

    rejected = read_certification(api, pending.certification_id)
    assert rejected["status"] == "REJECTED"
    assert rejected["rejection_reason"] == "DEALER_SUSPENDED"
    assert rejected["activated_at"] is None, "the rejected certification was never live"
    released = read_vehicle(api, pending.vehicle_id)
    assert released["cpo_state"] == "NOT_CERTIFIED"
    assert released["active_certification_count"] == 0
    assert released["certified_certification_id"] is None

    still_live = read_certification(api, live.certification_id)
    assert still_live["status"] == "ACTIVE", (
        "an already-active certification is not decertified by a claim"
    )
    assert still_live["approved_claim_count"] == 1
    assert still_live["approved_claim_amount_cents"] == 100000
    paid = claims_of(api, live.certification_id)
    assert [row["id"] for row in paid] == [claim["id"]]
    assert paid[0]["approved_amount_cents"] == 100000


def test_the_audit_axis_suspends_on_the_second_failure_not_on_the_maximal_rate(
    api, program
):
    """One failure maxes the rate but only the second reaches the cumulative count.

    PRD §3.10: "The number drawn is the smaller of the pool size and the greater
    of the programme's per-run minimum (1 by default) and the programme's
    sampling fraction (20 percent by default) multiplied by the pool size"
    PRD §3.2: "`audit_fail_rate` is the failure count divided by the sample
    count with 1 substituted for a zero sample count, rounded half up to 2
    decimals"
    PRD §3.10: "Hop 4, caused by hop 1's counter crossing its threshold, applies
    only when the dealer's `audit_fail_count` has reached the programme's
    audit-failure suspension count — two failures by default: the dealer's
    `privilege_status` moves to `SUSPENDED` with `privilege_reason`
    `AUDIT_FAILURE_SUSPENSION`."
    PRD §3.10: "An empty pool is not an error: a pool size of zero yields a
    `selected_count` of 0, creates no audit samples at all, and still returns a
    successful 201 Created response."

    Design: Corner/cross-cutting complexity layers/cumulative_audit_failure_count_reaches_its_threshold_on_the_second_failure
    """
    first = active_certification(api, program)
    second = active_certification(api, program)

    run_one = draw_audit_run(api)
    assert_audit_run_summary(run_one)
    assert run_one["audit_run_id"] == "AR-1"
    assert run_one["pool_size"] == 2
    assert run_one["selected_count"] == max(
        AUDIT_SAMPLE_MIN_PER_RUN, ceil_count(AUDIT_SAMPLE_PCT * 2)
    )
    assert run_one["selected_count"] == 1
    assert run_one["selected_certification_ids"] == [first.certification_id], (
        "the tie in risk score is broken by the earlier certification"
    )

    samples = audit_samples_of(api, first.certification_id)
    assert len(samples) == 1
    sample_one = samples[0]
    assert_audit_sample(sample_one)
    assert sample_one["status"] == "SELECTED"
    assert sample_one["audit_run_id"] == "AR-1"
    assert sample_one["selection_rank"] == 1
    assert sample_one["finding_code"] is None
    assert sample_one["reviewed_at"] is None
    assert sample_one["reviewer_user_id"] is None
    under_audit = read_certification(api, first.certification_id)
    assert under_audit["status"] == "UNDER_AUDIT"
    assert under_audit["audit_sampled"] is True

    record_finding(api, sample_one["id"], "FAIL", "DOCUMENTATION_MISSING")
    after_one = read_dealer(api, program.dealer_id)
    assert after_one["audit_sample_count"] == 1
    assert after_one["audit_fail_count"] == 1
    assert after_one["audit_fail_rate"] == 1.00
    assert after_one["claim_ratio_effective"] == 0.00
    assert after_one["risk_score"] == 40
    assert after_one["risk_score"] == round_half_up(0.00 * 100 * 0.60 + 1.00 * 100 * 0.40)
    assert after_one["privilege_status"] == "ACTIVE", (
        "the rate is already maximal, but one failure has not reached the count"
    )
    assert after_one["privilege_reason"] is None
    assert_dealer(after_one)
    decertified = read_certification(api, first.certification_id)
    assert decertified["status"] == "DECERTIFIED"
    assert decertified["decertification_reason"] == "POST_AUDIT_FAIL"
    assert decertified["fee_credited_cents"] == decertified["fee_charged_cents"]

    run_two = draw_audit_run(api)
    assert_audit_run_summary(run_two)
    assert run_two["audit_run_id"] == "AR-2"
    assert run_two["pool_size"] == 1, (
        "the failed certification is out of the pool on both counts"
    )
    assert run_two["selected_count"] == 1
    assert run_two["selected_certification_ids"] == [second.certification_id]
    sample_two = audit_samples_of(api, second.certification_id)[0]
    assert sample_two["status"] == "SELECTED"
    assert sample_two["audit_run_id"] == "AR-2"
    midway = read_dealer(api, program.dealer_id)
    assert midway["audit_sample_count"] == 2
    assert midway["audit_fail_count"] == 1
    assert midway["audit_fail_rate"] == 0.50
    assert midway["risk_score"] == 20
    assert midway["privilege_status"] == "ACTIVE"

    record_finding(api, sample_two["id"], "FAIL", "ELIGIBILITY_VIOLATION")
    after_two = read_dealer(api, program.dealer_id)
    assert after_two["audit_sample_count"] == 2
    assert after_two["audit_fail_count"] == 2
    assert after_two["audit_fail_count"] == AUDIT_FAIL_SUSPENSION_COUNT
    assert after_two["privilege_status"] == "SUSPENDED"
    assert after_two["privilege_reason"] == "AUDIT_FAILURE_SUSPENSION"
    assert after_two["audit_fail_rate"] == 1.00, "the rate returned to where it was"
    assert after_two["risk_score"] == 40, "the threshold that fired is the count"
    assert after_two["active_certification_count"] == 0
    assert_dealer(after_two)

    run_three = draw_audit_run(api)
    assert_audit_run_summary(run_three)
    assert run_three["audit_run_id"] == "AR-3"
    assert run_three["pool_size"] == 0, "a suspended dealer's cars leave the pool"
    assert run_three["selected_count"] == 0
    assert run_three["selected_certification_ids"] == []
    assert len(audit_samples_of(api, first.certification_id)) == 1
    assert len(audit_samples_of(api, second.certification_id)) == 1
