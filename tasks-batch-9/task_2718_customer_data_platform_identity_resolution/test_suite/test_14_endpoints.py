"""Endpoint round trips: create, transition and computed reads over live HTTP.

Every test here drives the real API through the declared endpoints only, building
each precondition from scratch because the harness restarts the server before
each test with an empty store and the logical clock at its startup value.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_EMPTY_AUDIENCE
from test_helpers.assertions import (
    approx4,
    assert_instant_equals,
    assert_new_match_rule,
    assert_task_counters,
)
from test_helpers.constants import DEFAULT_CLOCK
from test_helpers.test_users import (
    ADMIN,
    ANALYST,
    GOVERNANCE,
    PRIVACY,
    STEWARD,
)


def test_match_rule_create_read_list_round_trip(api):
    """Declaring a deterministic rule returns it, and the same row comes back
    from the item read and from the list read under both of its filters.

    "The two kinds have complementary shape requirements on `deterministic_key`, which must name one of `EMAIL_NORM`, `PHONE_NORM` or `LOYALTY_NUMBER` when the kind is deterministic and must be null when it is probabilistic; either mismatch — a deterministic rule with no key, or a probabilistic rule that supplies one — is refused with `ERR_DETERMINISTIC_KEY_MISMATCH`."
    "Finally `missing_identifier_policy`, defaulting to `STRICT_ZERO`, chooses how sparse evidence is scored."
    "A new rule is `ENABLED` with `confirmed_count` and `rejected_count` at 0 and `precision_estimate` at 1.0."
    "Rules are readable individually — exposing the live `precision_estimate` — and as a list ordered by `created_at` ascending, which is exactly the order the resolution passes scan them in, filterable by `rule_kind` and `status`."
    "`total_count` is the number of records matching the filters before pagination is applied, and `has_more` is true when records remain beyond the current page."

    Design: Corner/endpoints/match_rule_create_read_list_round_trip
    """
    payload = f.deterministic_rule_payload(
        "EMAIL_NORM",
        code="EP_DET_EMAIL",
        review_floor=0.70,
        auto_merge_threshold=0.95,
        min_precision=0.80,
    )
    rule = get_success_data(api.create_match_rule(payload, ADMIN), 201)

    assert_new_match_rule(rule)
    assert rule["code"] == "EP_DET_EMAIL"
    assert rule["rule_kind"] == "DETERMINISTIC"
    assert rule["deterministic_key"] == "EMAIL_NORM"
    assert rule["review_floor"] == approx4(0.70)
    assert rule["auto_merge_threshold"] == approx4(0.95)
    assert rule["min_precision"] == approx4(0.80)
    assert rule["missing_identifier_policy"] == "STRICT_ZERO"
    assert_instant_equals(rule["created_at"], DEFAULT_CLOCK, "created_at")
    assert_instant_equals(rule["updated_at"], DEFAULT_CLOCK, "updated_at")

    fetched = get_success_data(api.get_match_rule(rule["id"], ADMIN), 200)
    assert fetched["id"] == rule["id"]
    assert fetched["code"] == "EP_DET_EMAIL"
    assert fetched["rule_kind"] == "DETERMINISTIC"
    assert fetched["deterministic_key"] == "EMAIL_NORM"
    assert fetched["status"] == "ENABLED"
    assert fetched["confirmed_count"] == 0
    assert fetched["rejected_count"] == 0
    assert fetched["precision_estimate"] == approx4(1.0)
    assert fetched["version"] == 1

    matching, meta = validate_paginated(
        api.list_match_rules(ADMIN, {"rule_kind": "DETERMINISTIC", "status": "ENABLED"})
    )
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert [row["id"] for row in matching] == [rule["id"]]

    other_kind, other_meta = validate_paginated(
        api.list_match_rules(ADMIN, {"rule_kind": "PROBABILISTIC"})
    )
    assert other_meta["total_count"] == 0
    assert other_kind == []

    disabled, disabled_meta = validate_paginated(
        api.list_match_rules(ADMIN, {"status": "DISABLED"})
    )
    assert disabled_meta["total_count"] == 0
    assert disabled == []


def test_governance_decision_reject_reverts_segment_to_draft(api):
    """Rejecting a submitted segment sends it back to DRAFT, counts the
    rejection, clears the submitter and leaves the approval history alone, and
    the analyst may then submit the segment again.

    "Rejecting reverts the segment `PENDING_GOVERNANCE_REVIEW` → `DRAFT`, increments `rejection_count` by 1, forces `sensitive_use_approved` back to false, and **clears `submitted_by_user_id`** so that the next submission re-arms the segregation check against whoever resubmits."
    "Crucially, a rejection leaves `approved_at` and `governance_expires_at` untouched: a later rejection never rewrites the history of an earlier approval, and those two timestamps continue to describe the approval that once happened."
    "Both branches require the segment to be `PENDING_GOVERNANCE_REVIEW` and both enforce segregation of duties — the deciding `X-User-ID` must differ from `submitted_by_user_id`, an author approving their own audience being refused with `ERR_SEGREGATION_OF_DUTIES` — and both stamp `decided_by_user_id` and increment the segment's `version`."
    "An analyst submits a segment that is `DRAFT` or `GOVERNANCE_EXPIRED`, moving it to `PENDING_GOVERNANCE_REVIEW`, stamping `submitted_by_user_id` with the acting `X-User-ID` and recomputing `member_count` over the current population so the reviewer sees a current figure rather than an authoring-time one."

    Design: Corner/endpoints/governance_decision_reject_reverts_segment_to_draft
    """
    segment = fx.draft_segment(api, list(f.POSTAL_10001), name="Rejected Audience")
    submitted = fx.submit_segment(api, segment["id"])
    assert submitted["status"] == "PENDING_GOVERNANCE_REVIEW"
    assert submitted["submitted_by_user_id"] == ANALYST["X-User-ID"]

    decided = get_success_data(
        api.decide_segment_governance(
            segment["id"], f.governance_decision_payload("REJECT", False), GOVERNANCE
        ),
        200,
    )

    assert decided["status"] == "DRAFT"
    assert decided["rejection_count"] == 1
    assert decided["sensitive_use_approved"] is False
    assert decided["submitted_by_user_id"] is None
    assert decided["decided_by_user_id"] == GOVERNANCE["X-User-ID"]
    assert decided["approved_at"] is None
    assert decided["governance_expires_at"] is None
    assert decided["version"] == submitted["version"] + 1

    resubmitted = get_success_data(
        api.submit_segment_for_review(segment["id"], ANALYST), 200
    )
    assert resubmitted["status"] == "PENDING_GOVERNANCE_REVIEW"
    assert resubmitted["submitted_by_user_id"] == ANALYST["X-User-ID"]
    assert resubmitted["rejection_count"] == 1


def test_propagate_mints_one_vendor_task_per_qualifying_destination(api):
    """Fan-out mints a vendor task only for the destination that has actually
    taken a delivery, stamps its acknowledgement deadline from that
    destination's own SLA, and skips the platform holding only a draft.

    "Where no hold applies, the qualifying destinations are those whose `status` is `ACTIVE` and which have at least one activation whose `status` is not `DRAFT` — a platform that never received a delivery has nothing to erase, and an inactive platform is skipped."
    "Where at least one qualifies, the request moves `RECEIVED` → `PROPAGATING`, one **vendor deletion task** is minted per qualifying destination in destination `created_at` ascending order, `propagated_at` is stamped at the logical clock now, the five counters are recomputed and the request's `version` increments."
    "Each task is created `PENDING` and immediately advanced `PENDING` → `DISPATCHED` within the same call, with `dispatched_at` at the logical clock now, `attempt_count` at 1, and `ack_deadline_at` set to `dispatched_at` advanced by that destination's `deletion_ack_sla_hours` hours."
    "The request's five counters are derived from its children at all times: `total_vendor_task_count` is every task minted across all propagate calls, `pending_vendor_task_count` counts those in `PENDING` or `DISPATCHED`, and `acknowledged_vendor_task_count`, `failed_vendor_task_count` and `timed_out_vendor_task_count` count the three remaining statuses one for one."
    "Recording the request moves the subject `NORMAL` → `DELETION_PENDING`, empties its `activatable_channels`, and mints a system-owned suppression entry whose `entry_type` is `PRIVACY_DELETE`, whose `deletion_request_id` names this request, whose `created_by_user_id` is the literal string `system`, whose `effective_at` is the logical clock now and whose `expires_at` is null — an open-ended guard that keeps the subject out of every audience for as long as the erasure is in flight and that no operator may release."

    Design: Corner/endpoints/propagate_mints_one_vendor_task_per_qualifying_destination
    """
    env = fx.emailable_profile(api)
    subject_id = env["profile"]["id"]

    delivered_to = fx.register_destination(
        api, daily_hash_quota=300, deletion_ack_sla_hours=48
    )
    never_delivered_to = fx.register_destination(
        api, daily_hash_quota=300, deletion_ack_sla_hours=72
    )
    segment = fx.approved_segment(api, list(f.POSTAL_10001))

    delivering = fx.draft_activation(
        api,
        segment["id"],
        delivered_to["id"],
        "2026-08-05T00:00:00Z",
        "2026-08-05T02:00:00Z",
    )
    fx.draft_activation(
        api,
        segment["id"],
        never_delivered_to["id"],
        "2026-08-05T00:00:00Z",
        "2026-08-05T02:00:00Z",
    )
    fx.dispatch(api, delivering["id"])

    request = fx.record_erasure(api, subject_id)
    assert request["status"] == "RECEIVED"

    propagated = get_success_data(
        api.propagate_deletion_request(
            request["id"], f.propagate_payload(request["version"]), PRIVACY
        ),
        200,
    )

    assert propagated["status"] == "PROPAGATING"
    assert_instant_equals(propagated["propagated_at"], DEFAULT_CLOCK, "propagated_at")
    assert_task_counters(
        propagated,
        total_vendor_task_count=1,
        pending_vendor_task_count=1,
        acknowledged_vendor_task_count=0,
        failed_vendor_task_count=0,
        timed_out_vendor_task_count=0,
    )
    assert propagated["version"] == request["version"] + 1

    tasks, meta = validate_paginated(
        api.list_vendor_tasks(ADMIN, {"deletion_request_id": request["id"]})
    )
    assert meta["total_count"] == 1
    task = tasks[0]
    assert task["destination_id"] == delivered_to["id"]
    assert task["deletion_request_id"] == request["id"]
    assert task["status"] == "DISPATCHED"
    assert task["attempt_count"] == 1
    assert_instant_equals(task["dispatched_at"], DEFAULT_CLOCK, "dispatched_at")
    assert_instant_equals(
        task["ack_deadline_at"], "2026-08-03T00:00:00Z", "ack_deadline_at"
    )
    assert task["acknowledged_at"] is None

    _, skipped_meta = validate_paginated(
        api.list_vendor_tasks(ADMIN, {"destination_id": never_delivered_to["id"]})
    )
    assert skipped_meta["total_count"] == 0

    subject = fx.reread_profile(api, subject_id)
    assert subject["privacy_status"] == "DELETION_PENDING"


def test_household_assignment_links_profile_to_existing_household(api):
    """Moving a member from the full first bucket into the overflow bucket at the
    same address recomputes both buckets' derived fields, including the
    alphabetical tie-break on the surname the receiving bucket now shares.

    "An `IdentitySteward` may override the waterfall to reconcile an address verified by hand, moving a profile into an explicitly named `household_id`."
    "On success the profile's `household_id` is set to the target, all three derived fields are recomputed on **both** the vacated household and the receiving one, the vacated household dissolves if the move emptied it, and the profile's `version` plus the `version` of each touched household each increment by 1."
    "`member_count` is the number of profiles whose `household_id` names this household and whose `resolution_status` is not `MERGED_AWAY` and whose `privacy_status` is not `DELETED`."
    "`dominant_last_name` is the most frequent non-null `last_name` among those members, ties broken alphabetically ascending, and is null when every member's last name is null."
    "The consequence is a strictly ordered overflow: the sixth profile to arrive at an address still joins bucket 1, and the seventh opens bucket 2."

    Design: Corner/endpoints/household_assignment_links_profile_to_existing_household
    """
    stamps = [
        "2026-07-30T10:00:00Z",
        "2026-07-30T10:10:00Z",
        "2026-07-30T10:20:00Z",
        "2026-07-30T10:30:00Z",
        "2026-07-30T10:40:00Z",
        "2026-07-30T10:50:00Z",
        "2026-07-30T11:00:00Z",
    ]
    records = [
        f.raw_record(
            f"HH{index + 1:02d}",
            last_name="Alpha" if index < 6 else "Bravo",
            address_line="4 Birch Lane",
            event_timestamp=stamp,
        )
        for index, stamp in enumerate(stamps)
    ]
    env = fx.promoted_batch(api, records)
    profiles = env["profiles"]
    assert len(profiles) == 7

    first_bucket_id = profiles[0]["household_id"]
    overflow_bucket_id = profiles[6]["household_id"]
    assert first_bucket_id is not None
    assert overflow_bucket_id is not None
    assert first_bucket_id != overflow_bucket_id

    before_first = fx.reread_household(api, first_bucket_id)
    before_overflow = fx.reread_household(api, overflow_bucket_id)
    assert before_first["member_count"] == 6
    assert before_first["sequence_no"] == 1
    assert before_first["dominant_last_name"] == "Alpha"
    assert before_overflow["member_count"] == 1
    assert before_overflow["sequence_no"] == 2
    assert before_overflow["dominant_last_name"] == "Bravo"
    assert before_first["address_hash"] == before_overflow["address_hash"]

    mover = profiles[0]
    moved = get_success_data(
        api.assign_household(
            mover["id"], f.household_assignment_payload(overflow_bucket_id), STEWARD
        ),
        200,
    )

    assert moved["id"] == mover["id"]
    assert moved["household_id"] == overflow_bucket_id
    assert moved["version"] == mover["version"] + 1

    after_first = fx.reread_household(api, first_bucket_id)
    assert after_first["status"] == "ACTIVE"
    assert after_first["member_count"] == 5
    assert after_first["dominant_last_name"] == "Alpha"
    assert after_first["combined_lifetime_value_cents"] == 0
    assert after_first["version"] == before_first["version"] + 1

    after_overflow = fx.reread_household(api, overflow_bucket_id)
    assert after_overflow["status"] == "ACTIVE"
    assert after_overflow["member_count"] == 2
    assert after_overflow["dominant_last_name"] == "Alpha"
    assert after_overflow["combined_lifetime_value_cents"] == 0
    assert after_overflow["version"] == before_overflow["version"] + 1


def test_segment_performance_incremental_basis_returns_first_touch_totals(api):
    """With one member converting twice, the incremental basis credits only each
    person's first purchase while the total basis counts every one, and the
    revenue-per-member figure is summed first and rounded exactly once.

    "Under `TOTAL`, the default, `conversion_count` is the number of qualifying conversions and `attributed_revenue_cents` is the sum of their `revenue_cents` — every repeat purchase by the same person counts again."
    "Under `INCREMENTAL`, only each distinct `profile_id`'s **chronologically first** conversion in the window is credited, so `conversion_count` is the number of distinct first touches and `attributed_revenue_cents` sums only those; a repeat purchase inside the window is treated as retained rather than incremental revenue."
    "Two outputs are identical under both bases: `unique_converter_count` is the number of distinct `profile_id` values across the qualifying conversions, and `member_count` is the segment's member-set size at read time."
    "`revenue_per_member_cents` is 0 where `member_count` is 0, and otherwise the `attributed_revenue_cents` figure divided by `member_count`, rounded half up to whole cents."
    "A report also appends its conversions to `attributed_conversions` — appended, never replaced, so the array accumulates across reports — recomputes `attributed_conversion_count` as the array's length, and cascades: each referenced profile's `lifetime_value_cents` increases by the reported `revenue_cents` and each such profile's household `combined_lifetime_value_cents` is recomputed."

    Design: Corner/endpoints/segment_performance_incremental_basis_returns_first_touch_totals
    """
    env = fx.emailable_profiles(api, 2)
    repeat_buyer, single_buyer = env["profiles"][0], env["profiles"][1]

    destination = fx.register_destination(api, daily_hash_quota=300)
    segment = fx.approved_segment(api, list(f.POSTAL_10001))
    assert_instant_equals(segment["approved_at"], DEFAULT_CLOCK, "approved_at")

    activation = fx.draft_activation(
        api,
        segment["id"],
        destination["id"],
        "2026-08-05T00:00:00Z",
        "2026-08-11T00:00:00Z",
    )

    fx.set_clock(api, "2026-08-10T00:00:00Z")
    dispatched = fx.dispatch(api, activation["id"])
    assert dispatched["dispatched_hash_count"] == 2

    reported = fx.report_match(
        api,
        activation["id"],
        destination["id"],
        2,
        0,
        [
            f.conversion(repeat_buyer["id"], "2026-08-06T12:00:00Z", 12000),
            f.conversion(single_buyer["id"], "2026-08-07T12:00:00Z", 5000),
            f.conversion(repeat_buyer["id"], "2026-08-09T12:00:00Z", 8000),
        ],
    )
    assert reported["attributed_conversion_count"] == 3
    assert reported["status"] == "ACTIVE"

    assert fx.reread_profile(api, repeat_buyer["id"])["lifetime_value_cents"] == 20000
    assert fx.reread_profile(api, single_buyer["id"])["lifetime_value_cents"] == 5000

    before_read = fx.reread_segment(api, segment["id"])

    total = get_success_data(
        api.get_segment_performance(
            segment["id"], ANALYST, {"attribution_basis": "TOTAL"}
        ),
        200,
    )
    assert total["segment_id"] == segment["id"]
    assert total["attribution_basis"] == "TOTAL"
    assert total["member_count"] == 2
    assert total["conversion_count"] == 3
    assert total["unique_converter_count"] == 2
    assert total["attributed_revenue_cents"] == 25000
    assert total["revenue_per_member_cents"] == 12500

    incremental = get_success_data(
        api.get_segment_performance(
            segment["id"], GOVERNANCE, {"attribution_basis": "INCREMENTAL"}
        ),
        200,
    )
    assert incremental["attribution_basis"] == "INCREMENTAL"
    assert incremental["member_count"] == 2
    assert incremental["conversion_count"] == 2
    assert incremental["unique_converter_count"] == 2
    assert incremental["attributed_revenue_cents"] == 17000
    assert incremental["revenue_per_member_cents"] == 8500

    defaulted = get_success_data(api.get_segment_performance(segment["id"], ANALYST), 200)
    assert defaulted["attribution_basis"] == "TOTAL"
    assert defaulted["conversion_count"] == 3
    assert defaulted["attributed_revenue_cents"] == 25000
    assert defaulted["revenue_per_member_cents"] == 12500

    after_read = fx.reread_segment(api, segment["id"])
    assert after_read["version"] == before_read["version"]


def test_resume_after_consent_loss_fails_on_empty_audience(api):
    """A later opt-out outranks the opt-in captured at ingest, which pauses the
    delivering activation and refunds its hashes, and the resume then fails on
    the first dispatch gate because the audience is now empty.

    "Qualifying elections are ranked by `captured_at` descending — the most recent decision wins — then, where two elections were captured at the same instant, by the `trust_tier` of the capture feed descending, and finally by the election's own `created_at` ascending."
    "When a channel drops out of a subject's `activatable_channels`, every delivering activation whose destination uses that channel recomputes its audience, and an activation whose `audience_size` reaches 0 is paused with `paused_reason` of `CONSENT_WITHDRAWN` and its dispatched hashes refunded, as §3.9 sets out."
    "Every arm refunds `dispatched_hash_count` to the destination's `remaining_daily_hash_quota` and decrements the segment's `active_activation_count` by 1."
    "It requires the activation to be `PAUSED`, the segment to be `APPROVED` and unexpired, the destination to be `ACTIVE`, and the sensitive-attribute clearances to still hold; it then recomputes `candidate_count`, `audience_size`, `suppressed_count` and `dispatched_hash_count` against the current consent and suppression state and re-applies all three gates in the same order — so an audience that has shrunk below k-anonymity, or a quota that other activations have since consumed, blocks the resume."
    "`audience_size` must be at least 1, an audience emptied by consent or suppression being refused with `ERR_EMPTY_AUDIENCE`."

    Design: Corner/endpoints/resume_after_consent_loss_fails_on_empty_audience
    """
    env = fx.delivering_activation_environment(
        api, 1, destination_overrides={"daily_hash_quota": 300}
    )
    activation_id = env["activation"]["id"]
    destination_id = env["destination"]["id"]
    subject_id = env["profiles"][0]["id"]

    assert env["activation"]["status"] == "DISPATCHED"
    assert env["activation"]["dispatched_hash_count"] == 1
    assert env["destination"]["remaining_daily_hash_quota"] == 299

    fx.capture_consent(
        api,
        subject_id,
        env["feed"]["id"],
        channel="EMAIL",
        purpose="MARKETING",
        consent_state="OPT_OUT",
        captured_at=DEFAULT_CLOCK,
    )

    subject = fx.reread_profile(api, subject_id)
    assert "EMAIL" not in subject["activatable_channels"]

    paused = fx.reread_activation(api, activation_id)
    assert paused["status"] == "PAUSED"
    assert paused["paused_reason"] == "CONSENT_WITHDRAWN"

    refunded = fx.reread_destination(api, destination_id)
    assert refunded["remaining_daily_hash_quota"] == 300

    validate_error(api.resume_activation(activation_id, ANALYST), ERR_EMPTY_AUDIENCE)

    still_paused = fx.reread_activation(api, activation_id)
    assert still_paused["status"] == "PAUSED"
    assert still_paused["paused_reason"] == "CONSENT_WITHDRAWN"
    assert still_paused["version"] == paused["version"]
    assert fx.reread_destination(api, destination_id)["remaining_daily_hash_quota"] == 300
    assert fx.reread_segment(api, env["segment"]["id"])["active_activation_count"] == 0
