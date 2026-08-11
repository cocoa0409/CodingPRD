"""Retention, the six-hop purge cascade and continuous rap-back monitoring."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_notification_routing_conservation,
    assert_rapback_subscription,
    assert_same_instant,
    deliver_notification,
    issue_determination,
    post_result,
    request_purge,
    run_aging,
    set_clock,
    setup_transmitted_submission,
    subscribe_rapback,
    validate_error,
    validate_paginated,
    validate_success,
)

VA = TEST_USERS["vendor_admin_headers"]
TECH = TEST_USERS["technician_headers"]
ADJ = TEST_USERS["adjudicator_headers"]
DEST = TEST_USERS["destination_headers"]


def _fully_dressed_purge_grant():
    """A retained submission carrying responses, a determination, a subscription and a notification."""
    world = setup_transmitted_submission(
        clock_start="2026-06-01T09:00:00Z", score=88, retention_requested=True
    )
    post_result(
        world["submission"]["id"],
        "STATE",
        "ACCEPTED",
        record_count=2,
        disqualifying_offense_count=1,
        record_detail="1998 CA PC 459 conviction",
    )
    world["submission"] = post_result(
        world["submission"]["id"], "FBI", "ACCEPTED", record_count=0, disqualifying_offense_count=0
    )
    issue_determination(world, outcome="NOT_FIT")
    subscribe_rapback(world)
    deliver_notification(world)
    request_purge(world)
    world["submission"] = validate_success_purge(world["submission"]["id"])
    return world


def validate_success_purge(submission_id):
    from test_helpers import api_client

    return validate_success(api_client.decide_purge(submission_id, "GRANT", VA), 200)


def test_the_grant_purges_retention_and_voids_every_response(api):
    """PRD 3.7: "1. The submission's `retention_status` becomes `PURGED` — a terminal value — and
    `purge_decided_by_user_id` is stamped with the deciding `X-User-ID`."
    PRD 3.7: "2. Because the retention authority is revoked, every criminal-history response of this
    submission whose `routing_status` is `RECEIVED` or `ROUTED` moves to `VOIDED` and has its
    `record_detail` cleared to null. Responses already `VOIDED` or `SUPERSEDED` are left alone."

    Design: Difficulty/transitive_cascade/purge_grant_cascades_six_hops_to_tcn_ledger
    """
    world = _fully_dressed_purge_grant()

    assert world["submission"]["retention_status"] == "PURGED"

    rows, meta = validate_paginated(api.list_submission_responses(world["submission"]["id"], VA))
    assert meta["total_count"] == 2
    for row in rows:
        shell = validate_success(api.get_chr_response(row["id"], VA), 200)
        assert shell["routing_status"] == "VOIDED"
        detailed = validate_success(
            api.get_chr_response(row["id"], ADJ, {"include_detail": "true"}), 200
        )
        assert detailed["record_detail"] is None


def test_the_grant_terminates_the_subscription_and_voids_its_notification(api):
    """PRD 3.7: "3. Because the retained responses are void, the rap-back subscription of this
    submission moves to `TERMINATED` if its `status` is `ACTIVE` or `RENEWAL_DUE`. A subscription
    already `CANCELLED` or `LAPSED` is left exactly as it is — this leg does not fire for it."
    PRD 3.7: "4. Because the subscription terminated, every rap-back notification bound to it whose
    `status` is `ROUTED` moves to `VOIDED`, and the subscription's `notifications_voided_count` is
    updated accordingly."

    Design: Difficulty/transitive_cascade/purge_grant_cascades_six_hops_to_tcn_ledger
    """
    world = _fully_dressed_purge_grant()

    subscription = validate_success(api.get_rapback_subscription(world["subscription"]["id"], ADJ), 200)
    notification = validate_success(
        api.get_rapback_notification(world["notification"]["id"], ADJ), 200
    )

    assert_rapback_subscription(subscription)
    assert subscription["status"] == "TERMINATED"
    assert notification["status"] == "VOIDED"
    assert subscription["notifications_voided_count"] == 1
    assert subscription["notifications_received_count"] == 1
    assert subscription["notifications_routed_count"] == 0
    assert_notification_routing_conservation(subscription)


def test_the_grant_vacates_the_determination_and_releases_the_ledger(api):
    """PRD 3.7: "5. Because its evidentiary basis is void, the fitness determination whose
    `basis_response_id` names one of the responses voided in hop 2 moves to `VACATED`, provided its
    `status` is `ISSUED`, `CHALLENGED`, `REAFFIRMED` or `AMENDED`. Vacating from `ISSUED` clears
    `outcome` to null, because the determination has lost the record it rested on."
    PRD 3.7: "6. Because the record itself is gone, the ORI's `tcn_released_count` increases by the
    number of entries in the submission's `destinations` — but only when the purged submission is a
    root transmission, one whose `tcn_suffix` is 0. Purging a suffix reprint releases nothing, because
    a preserved-root reprint never consumed an allocation. In the same hop, the submission's
    fingerprint card moves to `SUPERSEDED` with a `taint_reason` of `PURGED_RECORD`."

    Design: Difficulty/transitive_cascade/purge_grant_cascades_six_hops_to_tcn_ledger
    """
    world = _fully_dressed_purge_grant()

    determination = validate_success(
        api.get_fitness_determination(world["determination"]["id"], ADJ), 200
    )
    assert determination["status"] == "VACATED"
    assert determination["outcome"] is None

    ori = validate_success(api.get_ori(world["ori"]["id"], VA), 200)
    assert ori["tcn_released_count"] == 2
    assert ori["tcn_consumed_count"] == 2

    card = validate_success(api.get_card(world["card"]["id"], TECH), 200)
    assert card["status"] == "SUPERSEDED"
    assert card["taint_reason"] == "PURGED_RECORD"


def _bare_purge_grant():
    """A retained transmission purged before any result, determination or subscription exists."""
    world = setup_transmitted_submission(
        clock_start="2026-06-01T09:00:00Z",
        score=90,
        retention_requested=True,
        ori_overrides={"ori_code": "CA1616161"},
    )
    request_purge(world, reason="record no longer needed")
    world["submission"] = validate_success_purge(world["submission"]["id"])
    return world


def test_a_purge_releases_exactly_the_allocations_the_transmission_consumed(api):
    """PRD 2.11: "**Transaction control number conservation.** For each ORI, the number of
    transaction control numbers consumed minus the number released — that is, `tcn_consumed_count`
    minus `tcn_released_count` — equals the total number of destinations across that ORI's *root*
    submissions that have not been purged."
    PRD 3.5: "An ORI with the code `CA0111111` transmitting its first card therefore mints
    `CA0111111-000001`."

    Design: Difficulty/compensating_invariant/purge_releases_exactly_the_tcns_the_transmission_consumed
    """
    world = _bare_purge_grant()

    assert world["submission"]["tcn_full"] == "CA1616161-000001"

    ori = validate_success(api.get_ori(world["ori"]["id"], VA), 200)
    assert ori["tcn_consumed_count"] == 2
    assert ori["tcn_released_count"] == 2
    assert ori["tcn_consumed_count"] - ori["tcn_released_count"] == 0


def test_the_bare_purge_still_supersedes_the_card_without_touching_missing_hops(api):
    """PRD 3.7: "In the same hop, the submission's fingerprint card moves to `SUPERSEDED` with a
    `taint_reason` of `PURGED_RECORD`."
    PRD 3.7: "1. The submission's `retention_status` becomes `PURGED` — a terminal value — and
    `purge_decided_by_user_id` is stamped with the deciding `X-User-ID`."

    Design: Difficulty/compensating_invariant/purge_releases_exactly_the_tcns_the_transmission_consumed
    """
    world = _bare_purge_grant()

    assert world["submission"]["retention_status"] == "PURGED"
    assert world["submission"]["tcn_full"] == "CA1616161-000001"

    card = validate_success(api.get_card(world["card"]["id"], TECH), 200)
    assert card["status"] == "SUPERSEDED"
    assert card["taint_reason"] == "PURGED_RECORD"

    _rows, meta = validate_paginated(
        api.list_rapback_subscriptions(ADJ, {"submission_id": world["submission"]["id"]})
    )
    assert meta["total_count"] == 0


def _cleared_submission_without_retention():
    world = setup_transmitted_submission(
        clock_start="2026-06-01T09:00:00Z", score=86, retention_requested=False
    )
    post_result(
        world["submission"]["id"], "STATE", "ACCEPTED", record_count=0, disqualifying_offense_count=0
    )
    world["submission"] = post_result(
        world["submission"]["id"], "FBI", "ACCEPTED", record_count=0, disqualifying_offense_count=0
    )
    return world


def test_rapback_needs_the_submissions_retention_not_just_the_authority(api):
    """PRD 3.7: "Two guards apply in this order: the submission's ORI must have `rapback_authority`
    true, failing which the answer is `ERR_RAPBACK_NOT_AUTHORIZED`; and the submission's
    `retention_status` must be `GRANTED`, `PURGE_REQUESTED` or `PURGE_DENIED`, failing which the
    answer is `ERR_RAPBACK_REQUIRES_RETENTION`."

    Design: Difficulty/cross_entity_state_dependency/rapback_subscription_depends_on_submission_retention_status
    """
    world = _cleared_submission_without_retention()

    response = api.create_rapback_subscription(world["submission"]["id"], ADJ)

    error = validate_error(response, ApiErrorId.ERR_RAPBACK_REQUIRES_RETENTION.value)
    assert error["error_id"] != ApiErrorId.ERR_RAPBACK_NOT_AUTHORIZED.value

    ori = validate_success(api.get_ori(world["ori"]["id"], VA), 200)
    assert ori["rapback_authority"] is True, "the ORI is not the reason the subscription failed"


def test_the_unretained_submission_keeps_its_cleared_disposition_and_no_subscription(api):
    """PRD 3.7: "Retention is the third axis a submission carries, and it moves entirely
    independently of the two destination axes. It starts at `NOT_REQUESTED`."
    PRD 3.5: "5. Otherwise neither is rejected, and the disposition turns on whether any record came
    back: if any criminal-history response of this submission whose `routing_status` is `RECEIVED` or
    `ROUTED` carries a `record_count` of at least 1, the disposition is `HIT`; otherwise it is
    `CLEARED`."

    Design: Difficulty/cross_entity_state_dependency/rapback_subscription_depends_on_submission_retention_status
    """
    world = _cleared_submission_without_retention()
    api.create_rapback_subscription(world["submission"]["id"], ADJ)

    submission = validate_success(api.get_submission(world["submission"]["id"], TECH), 200)
    assert submission["retention_status"] == "NOT_REQUESTED"
    assert submission["composite_disposition"] == "CLEARED"

    _rows, meta = validate_paginated(
        api.list_rapback_subscriptions(ADJ, {"submission_id": world["submission"]["id"]})
    )
    assert meta["total_count"] == 0


def _subscription_opened_on_a_leap_year_run_up():
    world = setup_transmitted_submission(
        clock_start="2026-06-01T09:00:00Z", score=80, retention_requested=True
    )
    set_clock("2027-03-01T00:00:00Z")
    subscribe_rapback(world)
    return world


def test_a_rapback_term_is_a_fixed_count_of_three_hundred_and_sixty_five_days(api):
    """PRD 3.7: "The term is a fixed day count, not a calendar anniversary, and the difference bites
    in leap years. A term starting `2027-03-01T00:00:00Z` runs 365 days to `2028-02-29T00:00:00Z`,
    and its renewal window opens 60 days earlier at `2027-12-31T00:00:00Z`."
    PRD 3.7: "A renewal attempted against a still-`ACTIVE` subscription outside its window is
    `ERR_RENEWAL_WINDOW_CLOSED`; a renewal attempted against a `LAPSED`, `CANCELLED` or `TERMINATED`
    subscription is `ERR_RECORD_STATE_INVALID`."

    Design: Corner/calculations/rapback_term_is_365_days_and_a_lapsed_subscription_orphans_later_events
    """
    world = _subscription_opened_on_a_leap_year_run_up()

    assert_same_instant(world["subscription"]["term_end"], "2028-02-29T00:00:00Z", "term_end")

    too_early = api.renew_rapback_subscription(world["subscription"]["id"], ADJ)
    validate_error(too_early, ApiErrorId.ERR_RENEWAL_WINDOW_CLOSED.value)


def test_the_subscription_becomes_renewal_due_then_lapses(api):
    """PRD 3.7: "It moves `ACTIVE → RENEWAL_DUE` once the clock is at or after `term_end` less 60
    days and at or before `term_end`, both boundaries inclusive; that is what unlocks renewal."
    PRD 3.7: "It moves to `LAPSED` once the clock passes `term_end`, and it does so from
    `RENEWAL_DUE` **and** directly from `ACTIVE` — the second leg exists precisely so that a
    subscription nobody ever read during its renewal window still lapses rather than hanging at
    `ACTIVE` for ever."

    Design: Corner/calculations/rapback_term_is_365_days_and_a_lapsed_subscription_orphans_later_events
    """
    world = _subscription_opened_on_a_leap_year_run_up()

    set_clock("2028-01-15T00:00:00Z")
    inside_window = validate_success(api.get_rapback_subscription(world["subscription"]["id"], ADJ), 200)
    assert inside_window["status"] == "RENEWAL_DUE"

    set_clock("2028-03-01T00:00:00Z")
    lapsed_renew = api.renew_rapback_subscription(world["subscription"]["id"], ADJ)
    validate_error(lapsed_renew, ApiErrorId.ERR_RECORD_STATE_INVALID.value)

    lapsed = validate_success(api.get_rapback_subscription(world["subscription"]["id"], ADJ), 200)
    assert lapsed["status"] == "LAPSED"
    assert lapsed["renewal_count"] == 0


def test_an_event_arriving_after_the_lapse_is_orphaned_and_unacknowledgeable(api):
    """PRD 3.7: "If one is found the notification is created at `ROUTED` with `subscription_id` set,
    and that subscription's `notifications_received_count` is incremented. If none is found the
    notification is created at `ORPHANED` with `subscription_id` null; it is retained for audit and
    can never be acknowledged."
    PRD 3.7: "Acknowledging an `ORPHANED` or `VOIDED` notification is `ERR_NOTIFICATION_UNROUTABLE`."
    PRD 2.11: "Orphaned notifications — those whose `subscription_id` is null — are counted on
    neither side of that equality, and are not counted by `notifications_received_count` either."

    Design: Corner/calculations/rapback_term_is_365_days_and_a_lapsed_subscription_orphans_later_events
    """
    world = _subscription_opened_on_a_leap_year_run_up()
    set_clock("2028-03-01T00:00:00Z")

    notification = validate_success(
        api.create_rapback_notification(
            {
                "ori_code": world["ori"]["ori_code"],
                "subject_submission_tcn": world["submission"]["tcn_full"],
                "event_type": "ARREST",
                "event_date": "2028-02-20",
            },
            DEST,
        ),
        201,
    )

    assert notification["status"] == "ORPHANED"
    assert notification["subscription_id"] is None

    refused = api.acknowledge_rapback_notification(notification["id"], ADJ)
    validate_error(refused, ApiErrorId.ERR_NOTIFICATION_UNROUTABLE.value)

    subscription = validate_success(api.get_rapback_subscription(world["subscription"]["id"], ADJ), 200)
    assert subscription["notifications_received_count"] == 0


def _stale_purge_request():
    world = setup_transmitted_submission(
        clock_start="2026-06-01T09:00:00Z", score=80, retention_requested=True
    )
    set_clock("2026-06-01T10:10:00Z")
    request_purge(world, reason="moved out of state")
    return world


def test_the_nightly_batch_auto_denies_a_stale_purge_request(api):
    """PRD 3.7: "A request that is never decided is denied by default: the nightly batch moves any
    submission whose `purge_requested_at` is more than 14 days behind the logical clock from
    `PURGE_REQUESTED` to `PURGE_DENIED`, and marks the automatic nature of that denial by setting
    `purge_decided_by_user_id` to null."
    PRD 3.9: "Run by a `VendorAdmin`, it optionally accepts `write_off_over_days` and returns an
    object with four counters: `invoices_aged`, `agencies_suspended`, `subscriptions_lapsed` and
    `purges_auto_denied`."

    Design: Corner/endpoints/purge_request_is_auto_denied_after_the_decision_window
    """
    world = _stale_purge_request()
    assert world["submission"]["retention_status"] == "PURGE_REQUESTED"

    set_clock("2026-06-16T00:00:00Z")
    summary = run_aging()

    assert summary["purges_auto_denied"] == 1

    submission = validate_success(api.get_submission(world["submission"]["id"], TECH), 200)
    assert submission["retention_status"] == "PURGE_DENIED"
    assert submission["purge_decided_by_user_id"] is None


def test_an_auto_denial_leaves_the_record_and_the_ledger_alone(api):
    """PRD 3.7: "The applicant themselves or an `AgencyAdjudicator` files a purge request with a
    written `reason`; it is admitted from `GRANTED` and from `PURGE_DENIED`, and it stamps
    `purge_requested_at` with the logical clock and `purge_requested_by_user_id` with the acting
    `X-User-ID`."
    PRD 3.7: "A denial moves `PURGE_REQUESTED → PURGE_DENIED`, stamps `purge_decided_by_user_id`, and
    — stated explicitly against the grant branch below — leaves every criminal-history response,
    every subscription, every notification and every determination completely untouched."

    Design: Corner/endpoints/purge_request_is_auto_denied_after_the_decision_window
    """
    world = _stale_purge_request()
    set_clock("2026-06-16T00:00:00Z")
    run_aging()

    submission = validate_success(api.get_submission(world["submission"]["id"], TECH), 200)
    assert submission["purge_requested_by_user_id"] == world["applicant"]["id"]

    card = validate_success(api.get_card(world["card"]["id"], TECH), 200)
    assert card["status"] == "SUBMITTED"
    assert card["taint_reason"] is None

    ori = validate_success(api.get_ori(world["ori"]["id"], VA), 200)
    assert ori["tcn_released_count"] == 0
