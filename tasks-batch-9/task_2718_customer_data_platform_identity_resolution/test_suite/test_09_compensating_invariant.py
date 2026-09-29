"""Two conserved ledgers, each measured on both sides of the cycle that moves it.

The hash ledger is rechargeable: every consumption by a dispatch or a resume is
matched by an equal refund when the activation pauses, so a whole cycle returns
the destination's remaining quota to its starting figure with no drift. The
customer-value ledger is redistributive: a confirmed merge moves money and record
counts onto the survivor and zeroes the loser, so the total visible over the
profiles that are not merged away is identical before and after.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    approx4,
    assert_profile_axes,
    assert_quota_conserved,
    sum_lifetime_value,
)
from test_helpers.test_users import ADMIN, STEWARD

# The destination's whole daily allowance, never reset during these tests.
DAILY_HASH_QUOTA = 500
# The UTC calendar date of the logical clock's boot instant.
EXPECTED_QUOTA_RESET_ON = "2026-08-01"

SURVIVOR_REVENUE_CENTS = 1000
LOSER_REVENUE_CENTS = 400
VISIBLE_VALUE_TOTAL_CENTS = SURVIVOR_REVENUE_CENTS + LOSER_REVENUE_CENTS


def _quota_environment(api, member_count=2):
    """Two emailable members, an approved segment and a DRAFT activation.

    The destination's whole allowance is five hundred hashes and the logical clock
    is left at its boot instant, so nothing but a refund can restore the quota.
    """
    fx.reset_clock(api)
    env = fx.activation_ready_environment(
        api,
        member_count=member_count,
        destination_overrides={"daily_hash_quota": DAILY_HASH_QUOTA},
    )
    destination = fx.reread_destination(api, env["destination"]["id"])
    assert destination["daily_hash_quota"] == DAILY_HASH_QUOTA
    assert destination["remaining_daily_hash_quota"] == DAILY_HASH_QUOTA
    assert destination["quota_reset_on"] == EXPECTED_QUOTA_RESET_ON
    env["destination"] = destination
    return env


def _remaining(api, destination_id):
    return fx.reread_destination(api, destination_id)["remaining_daily_hash_quota"]


def _merge_ready_environment(api):
    """Two profiles carrying different customer value and one PROPOSED link.

    A dispatched activation reports one conversion against each profile, so the
    visible value total is fourteen hundred cents before anything merges. The
    probabilistic rule is declared only afterwards, so the link below is the only
    one in the store, and its confidence lands inside the review band.
    """
    fx.reset_clock(api)
    env = fx.delivering_activation_environment(api, member_count=2)
    ordered = sorted(env["profiles"], key=lambda p: (p["created_at"], p["id"]))
    env["earlier"], env["later"] = ordered[0], ordered[1]

    env["activation"] = fx.report_match(
        api,
        env["activation"]["id"],
        env["destination"]["id"],
        vendor_matched_count=2,
        unusable_hash_count=0,
        attributed_conversions=[
            f.conversion(
                env["earlier"]["id"], "2026-08-02T10:00:00Z", SURVIVOR_REVENUE_CENTS
            ),
            f.conversion(
                env["later"]["id"], "2026-08-02T11:00:00Z", LOSER_REVENUE_CENTS
            ),
        ],
    )
    env["rule"] = fx.declare_probabilistic_rule(api, min_precision=0.40)
    env["link"] = fx.proposed_link(
        api,
        env["earlier"]["id"],
        env["later"]["id"],
        env["rule"]["id"],
        f.evidence(
            email_similarity=1.0,
            phone_similarity=1.0,
            name_similarity=1.0,
            address_similarity=0.0,
        ),
    )
    assert env["link"]["status"] == "PROPOSED", (
        f"setup expected a link inside the review band, got {env['link']['status']}"
    )
    # 0.40 + 0.25 + 0.20 + 0.00 over the full weight base of 1.00 under STRICT_ZERO,
    # which sits above the review floor of 0.65 and below the merge threshold of 0.92.
    assert env["link"]["confidence"] == approx4(0.85)
    env["earlier"] = fx.reread_profile(api, env["earlier"]["id"])
    env["later"] = fx.reread_profile(api, env["later"]["id"])
    return env


def _visible_value_total(api):
    """The money total over the profiles that are not merged away."""
    rows, _meta = validate_paginated(api.list_profiles(ADMIN, {"limit": 100, "offset": 0}))
    return sum_lifetime_value(rows)


def _visible_record_total(api):
    """The source-record total over the profiles that are not merged away."""
    rows, _meta = validate_paginated(api.list_profiles(ADMIN, {"limit": 100, "offset": 0}))
    return sum(
        row["source_record_count"]
        for row in rows
        if row["resolution_status"] != "MERGED_AWAY"
    )


# ---------------------------------------------------------------------------
# the hash quota ledger
# ---------------------------------------------------------------------------
def test_hash_quota_returns_to_full_after_a_dispatch_pause_resume_pause_cycle(api):
    """Dispatching consumes the two hashes of a two-member audience, pausing
    refunds exactly the same figure, resuming consumes it again and the final
    pause refunds it once more, so the destination's remaining quota is back at
    five hundred with no drift and no date-driven reset.

    "Dispatching or resuming an activation consumes `dispatched_hash_count` from the destination's remaining quota; pausing an activation, or terminating one that was still delivering, refunds exactly the same figure."

    "At every moment, and for as long as `quota_reset_on` is unchanged, `remaining_daily_hash_quota` equals `daily_hash_quota` minus the sum of `dispatched_hash_count` over that destination's activations whose status is `DISPATCHED`, `ACTIVE` or `UNDERPERFORMING`."

    "Every arm sets `status` to `PAUSED` and writes `paused_reason`: `OPERATOR` for the explicit call, or `CONSENT_WITHDRAWN` or `GOVERNANCE_EXPIRED` for the respective cascades."

    "On success the activation moves `PAUSED` → `ACTIVE`, `paused_reason` is cleared to null, the recomputed `dispatched_hash_count` is deducted from `remaining_daily_hash_quota`, the segment's `active_activation_count` increases by 1, and the activation's, destination's and segment's `version` each increment by 1."

    Design: Difficulty/compensating_invariant/hash_quota_conserved_by_dispatch_pause_resume_cycle
    """
    env = _quota_environment(api)
    activation_id = env["activation"]["id"]
    destination_id = env["destination"]["id"]
    segment_id = env["segment"]["id"]

    assert_quota_conserved(env["destination"], 0)

    dispatched = fx.dispatch(api, activation_id)
    assert dispatched["status"] == "DISPATCHED"
    assert dispatched["candidate_count"] == 2
    assert dispatched["audience_size"] == 2
    assert dispatched["dispatched_hash_count"] == 2
    assert_quota_conserved(fx.reread_destination(api, destination_id), 2)
    assert fx.reread_segment(api, segment_id)["active_activation_count"] == 1

    paused = fx.pause(api, activation_id)
    assert paused["status"] == "PAUSED"
    assert paused["paused_reason"] == "OPERATOR"
    assert_quota_conserved(fx.reread_destination(api, destination_id), 0)
    assert fx.reread_segment(api, segment_id)["active_activation_count"] == 0

    resumed = fx.resume(api, activation_id)
    assert resumed["status"] == "ACTIVE"
    assert resumed["paused_reason"] is None
    assert resumed["dispatched_hash_count"] == 2
    assert_quota_conserved(fx.reread_destination(api, destination_id), 2)
    assert fx.reread_segment(api, segment_id)["active_activation_count"] == 1

    paused_again = fx.pause(api, activation_id)
    assert paused_again["status"] == "PAUSED"
    assert paused_again["paused_reason"] == "OPERATOR"

    destination = fx.reread_destination(api, destination_id)
    assert destination["remaining_daily_hash_quota"] == DAILY_HASH_QUOTA
    assert_quota_conserved(destination, 0)
    assert destination["quota_reset_on"] == EXPECTED_QUOTA_RESET_ON, (
        "the restored quota must come from refunds, not from a new-day reset"
    )
    assert fx.reread_segment(api, segment_id)["active_activation_count"] == 0


def test_hash_quota_is_the_daily_figure_less_the_sum_over_delivering_activations(api):
    """Two activations delivering the same two-member audience on one destination
    hold four hashes between them, and pausing one returns exactly its own two, so
    the remaining quota tracks the sum over the delivering set rather than the last
    call alone.

    "Each destination declares `daily_hash_quota`; `remaining_daily_hash_quota` is that figure less the hashes consumed by deliveries that are still in flight."

    "At every moment, and for as long as `quota_reset_on` is unchanged, `remaining_daily_hash_quota` equals `daily_hash_quota` minus the sum of `dispatched_hash_count` over that destination's activations whose status is `DISPATCHED`, `ACTIVE` or `UNDERPERFORMING`."

    "Every arm refunds `dispatched_hash_count` to the destination's `remaining_daily_hash_quota` and decrements the segment's `active_activation_count` by 1."

    Design: Difficulty/compensating_invariant/hash_quota_conserved_by_dispatch_pause_resume_cycle
    """
    env = _quota_environment(api)
    destination_id = env["destination"]["id"]
    first_id = env["activation"]["id"]
    second_id = fx.draft_activation(api, env["segment"]["id"], destination_id)["id"]

    first = fx.dispatch(api, first_id)
    assert first["dispatched_hash_count"] == 2
    assert _remaining(api, destination_id) == DAILY_HASH_QUOTA - 2

    second = fx.dispatch(api, second_id)
    assert second["dispatched_hash_count"] == 2
    assert_quota_conserved(fx.reread_destination(api, destination_id), 4)
    assert fx.reread_segment(api, env["segment"]["id"])["active_activation_count"] == 2

    fx.pause(api, first_id)
    assert_quota_conserved(fx.reread_destination(api, destination_id), 2)
    assert fx.reread_activation(api, second_id)["status"] == "DISPATCHED"

    fx.pause(api, second_id)
    destination = fx.reread_destination(api, destination_id)
    assert destination["remaining_daily_hash_quota"] == DAILY_HASH_QUOTA
    assert_quota_conserved(destination, 0)
    assert destination["quota_reset_on"] == EXPECTED_QUOTA_RESET_ON
    assert fx.reread_segment(api, env["segment"]["id"])["active_activation_count"] == 0


def test_resume_consumes_only_the_recomputed_hash_count_and_the_pause_refunds_it(api):
    """A suppression raised while the activation was paused takes one member out of
    the eligible population, so the resume re-resolves a one-member audience and
    consumes a single hash instead of two, and the following pause refunds exactly
    that smaller figure.

    "It requires the activation to be `PAUSED`, the segment to be `APPROVED` and unexpired, the destination to be `ACTIVE`, and the sensitive-attribute clearances to still hold; it then recomputes `candidate_count`, `audience_size`, `suppressed_count` and `dispatched_hash_count` against the current consent and suppression state and re-applies all three gates in the same order — so an audience that has shrunk below k-anonymity, or a quota that other activations have since consumed, blocks the resume."

    "The eligible population is narrower still: only profiles whose `resolution_status` is not `MERGED_AWAY` and whose `privacy_status` is exactly `NORMAL` are considered."

    "At every moment, and for as long as `quota_reset_on` is unchanged, `remaining_daily_hash_quota` equals `daily_hash_quota` minus the sum of `dispatched_hash_count` over that destination's activations whose status is `DISPATCHED`, `ACTIVE` or `UNDERPERFORMING`."

    Design: Difficulty/compensating_invariant/hash_quota_conserved_by_dispatch_pause_resume_cycle
    """
    env = _quota_environment(api)
    activation_id = env["activation"]["id"]
    destination_id = env["destination"]["id"]

    assert fx.dispatch(api, activation_id)["dispatched_hash_count"] == 2
    assert_quota_conserved(fx.reread_destination(api, destination_id), 2)

    fx.pause(api, activation_id)
    assert_quota_conserved(fx.reread_destination(api, destination_id), 0)

    fx.add_suppression(api, env["profiles"][0]["id"])
    assert fx.reread_profile(api, env["profiles"][0]["id"])["privacy_status"] == "SUPPRESSED"

    resumed = fx.resume(api, activation_id)
    assert resumed["status"] == "ACTIVE"
    assert resumed["candidate_count"] == 1
    assert resumed["audience_size"] == 1
    assert resumed["dispatched_hash_count"] == 1
    assert_quota_conserved(fx.reread_destination(api, destination_id), 1)

    fx.pause(api, activation_id)
    destination = fx.reread_destination(api, destination_id)
    assert destination["remaining_daily_hash_quota"] == DAILY_HASH_QUOTA
    assert_quota_conserved(destination, 0)
    assert destination["quota_reset_on"] == EXPECTED_QUOTA_RESET_ON


# ---------------------------------------------------------------------------
# the customer-value ledger
# ---------------------------------------------------------------------------
def test_confirmed_merge_conserves_the_visible_lifetime_value_total(api):
    """One profile holds a thousand cents and the other four hundred, so the
    visible total is fourteen hundred; confirming the link between them moves the
    loser's balance onto the survivor and zeroes the loser, leaving the total over
    the profiles that are not merged away exactly where it was.

    "Summed over all profiles whose `resolution_status` is not `MERGED_AWAY`, both `lifetime_value_cents` and `source_record_count` are identical immediately before and immediately after any merge."

    "A merge redistributes those quantities onto the survivor and zeroes the loser's monetary balance; it never creates or destroys value."

    "Survivorship is decided by three discriminators applied in order, the first that separates the pair winning outright: the higher `source_record_count`; then the higher `trust_tier` of the feed named by the profile's `primary_source_system_id`; then the earlier `created_at`."

    "The loser is then torn down: its `resolution_status` moves `RESOLVED` → `MERGED_AWAY`, its `merged_into_profile_id` names the survivor, its `household_id` is cleared because household membership follows the surviving identity, its `lifetime_value_cents` is set to 0 because the value moved rather than duplicated, and its `activatable_channels` becomes empty."

    "At or above `review_floor` but below `auto_merge_threshold`, the link is created as `PROPOSED` and waits for a steward."

    "Alongside all of this, the rule's `confirmed_count` increases by 1 and its `precision_estimate` is recomputed."

    Design: Difficulty/compensating_invariant/lifetime_value_conserved_by_confirmed_merge
    """
    env = _merge_ready_environment(api)
    assert env["earlier"]["lifetime_value_cents"] == SURVIVOR_REVENUE_CENTS
    assert env["later"]["lifetime_value_cents"] == LOSER_REVENUE_CENTS
    assert _visible_value_total(api) == VISIBLE_VALUE_TOTAL_CENTS

    decided = validate_success(
        api.decide_identity_link(
            env["link"]["id"], f.link_decision_payload("CONFIRM"), STEWARD
        ),
        200,
    )
    assert decided["status"] == "CONFIRMED"
    # Both endpoints were minted by a single promotion at one logical instant, so
    # all three survivorship discriminators tie and the PRD states outright that
    # "the profile's `id` is never consulted as a tie-breaker" — the pair is read
    # back from the recorded survivor rather than from an id-derived guess.
    survivor_id = decided["survivor_profile_id"]
    assert survivor_id in (env["earlier"]["id"], env["later"]["id"])
    loser_id = (
        env["later"]["id"] if survivor_id == env["earlier"]["id"] else env["earlier"]["id"]
    )

    survivor = fx.reread_profile(api, survivor_id)
    loser = fx.reread_profile(api, loser_id)
    assert_profile_axes(survivor, "RESOLVED", "NORMAL")
    assert_profile_axes(loser, "MERGED_AWAY", "NORMAL")
    assert loser["merged_into_profile_id"] == survivor["id"]
    assert loser["lifetime_value_cents"] == 0
    assert survivor["lifetime_value_cents"] == VISIBLE_VALUE_TOTAL_CENTS

    assert _visible_value_total(api) == VISIBLE_VALUE_TOTAL_CENTS, (
        "the merge must neither create nor destroy customer value"
    )

    activation = fx.reread_activation(api, env["activation"]["id"])
    assert activation["attributed_conversion_count"] == 2, (
        "the conversion ledger is not rewritten by the merge"
    )
    assert fx.reread_rule(api, env["rule"]["id"])["confirmed_count"] == 1


def test_confirmed_merge_conserves_the_visible_source_record_count_total(api):
    """The same merge is measured on the other conserved quantity: two profiles of
    one source record each total two before the merge, and the survivor alone
    carries two afterwards, so the visible record total does not move either.

    "Summed over all profiles whose `resolution_status` is not `MERGED_AWAY`, both `lifetime_value_cents` and `source_record_count` are identical immediately before and immediately after any merge."

    "Four quantities roll up onto the survivor: `source_record_count` and `lifetime_value_cents` each increase by the loser's amount, `contributing_source_system_codes` becomes the sorted union of both lists, `last_activity_at` becomes the later of the two, and `loyalty_tier` becomes the higher of the two on the `NONE`-`SILVER`-`GOLD`-`PLATINUM` ordinal scale."

    "A merge redistributes those quantities onto the survivor and zeroes the loser's monetary balance; it never creates or destroys value."

    Design: Difficulty/compensating_invariant/lifetime_value_conserved_by_confirmed_merge
    """
    env = _merge_ready_environment(api)
    assert env["earlier"]["source_record_count"] == 1
    assert env["later"]["source_record_count"] == 1
    assert _visible_record_total(api) == 2

    decided = validate_success(
        api.decide_identity_link(
            env["link"]["id"], f.link_decision_payload("CONFIRM"), STEWARD
        ),
        200,
    )
    assert decided["status"] == "CONFIRMED"

    survivor = fx.reread_profile(api, decided["survivor_profile_id"])
    assert survivor["source_record_count"] == 2
    assert _visible_record_total(api) == 2, (
        "the merge must neither create nor destroy source records"
    )


def test_rejected_link_leaves_both_visible_ledgers_untouched(api):
    """The contrast arm: rejecting the same candidate link redistributes nothing,
    so each profile keeps its own balance, both stay visible on the resolution
    axis and the two conserved totals are unchanged.

    "No profile is mutated: `survivor_profile_id` stays null and both profiles keep `resolution_status` of `RESOLVED`."

    "This is a **branching fork**: the two branches share no side effect beyond the link's own status, `decided_by_user_id` (set to the acting `X-User-ID`), `decided_at` and its `version` increment."

    "Instead the rule's `rejected_count` increases by 1 and `precision_estimate` is recomputed as `confirmed_count` divided by the sum of `confirmed_count` and `rejected_count`, rounded half up to four decimal places, and held at exactly 1.0 while that denominator is 0."

    Design: Difficulty/compensating_invariant/lifetime_value_conserved_by_confirmed_merge
    """
    env = _merge_ready_environment(api)
    assert _visible_value_total(api) == VISIBLE_VALUE_TOTAL_CENTS
    assert _visible_record_total(api) == 2

    decided = validate_success(
        api.decide_identity_link(
            env["link"]["id"], f.link_decision_payload("REJECT"), STEWARD
        ),
        200,
    )
    assert decided["status"] == "REJECTED"
    assert decided["survivor_profile_id"] is None

    left = fx.reread_profile(api, env["earlier"]["id"])
    right = fx.reread_profile(api, env["later"]["id"])
    assert_profile_axes(left, "RESOLVED", "NORMAL")
    assert_profile_axes(right, "RESOLVED", "NORMAL")
    assert left["lifetime_value_cents"] == SURVIVOR_REVENUE_CENTS
    assert right["lifetime_value_cents"] == LOSER_REVENUE_CENTS
    assert left["source_record_count"] == 1
    assert right["source_record_count"] == 1

    assert _visible_value_total(api) == VISIBLE_VALUE_TOTAL_CENTS
    assert _visible_record_total(api) == 2

    rule = fx.reread_rule(api, env["rule"]["id"])
    assert rule["rejected_count"] == 1
    assert rule["confirmed_count"] == 0
    assert rule["precision_estimate"] == approx4(0.0)
