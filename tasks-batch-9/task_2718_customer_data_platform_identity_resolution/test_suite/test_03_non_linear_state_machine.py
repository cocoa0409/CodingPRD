"""Profile axis independence and the steward's branching decision fork.

A profile carries two lifecycle axes on one row, and the PRD forbids either from
gating the other: the privacy axis travels NORMAL -> SUPPRESSED -> NORMAL while
resolution_status stays RESOLVED, and the resolution axis then travels
RESOLVED -> MERGED_AWAY while privacy_status stays NORMAL. The second half of the
file exercises the identity-link decision fork, whose CONFIRM and REJECT branches
share no side effect beyond the link's own fields.
"""

from prd_bench_local_runner.testing import (  # noqa: F401
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    approx4,
    assert_activatable,
    assert_instant_equals,
    assert_profile_axes,
)
from test_helpers.test_users import PRIVACY, STEWARD

# The evidence the two instances of this file share: three components matched
# exactly and the address absent on at least one side. Under STRICT_ZERO the raw
# score 0.40 + 0.25 + 0.20 is the confidence itself, which is 0.8500 — inside the
# review band of a rule whose review_floor is 0.65 and whose auto_merge_threshold
# is 0.92.
SPARSE_PERFECT_EVIDENCE = dict(
    email_similarity=1.0,
    phone_similarity=1.0,
    name_similarity=1.0,
    address_similarity=None,
)
EXPECTED_CONFIDENCE = 0.8500


def _axis_environment(api, min_precision: float = 0.40):
    """Two promoted profiles and one probabilistic rule declared after the promote.

    Both profiles are RESOLVED and NORMAL with source_record_count 1, and neither
    is joined to the other, because the rule is declared only once the promotion
    has finished. The earlier-created profile therefore wins survivorship on the
    third discriminator, both profiles tying on the first two.
    """
    env = fx.two_profiles(api)
    env["rule"] = fx.declare_probabilistic_rule(api, min_precision=min_precision)
    return env


def _four_profiles(api, min_precision: float = 0.40):
    """Four promoted profiles plus one probabilistic rule, for the decision fork.

    Two disjoint pairs are available, so one link can be confirmed and a second,
    independent link rejected without either decision touching the other's
    endpoints.
    """
    records = [f.raw_record() for _ in range(4)]
    env = fx.promoted_batch(api, records)
    assert len(env["profiles"]) == 4, (
        f"setup expected four minted profiles, got {len(env['profiles'])}"
    )
    env["p1"], env["p2"], env["p3"], env["p4"] = env["profiles"]
    env["rule"] = fx.declare_probabilistic_rule(api, min_precision=min_precision)
    return env


def test_do_not_sell_moves_the_privacy_axis_and_leaves_the_resolution_axis_alone(api):
    """A DO_NOT_SELL suppression drives privacy_status to SUPPRESSED while the
    subject's resolution_status stays exactly where the promotion left it.

    "A profile carries two independent lifecycle axes on the same row, and the platform must never let one gate the other."

    "Each axis gates different operations, and no transition on one axis is ever a precondition of a transition on the other; in particular, tombstoning a profile at the end of an erasure leaves `resolution_status` exactly as it found it."

    "The three narrow-purpose types move it `NORMAL` → `SUPPRESSED`; note that `DO_NOT_SELL` moves the axis to `SUPPRESSED` too, even though only the advertising channel is actually masked, because the subject is no longer in an unqualified normal state."

    Design: Difficulty/non_linear_state_machine/profile_privacy_axis_moves_without_touching_resolution_axis
    """
    env = _axis_environment(api)
    subject = env["right"]
    assert_profile_axes(subject, "RESOLVED", "NORMAL")

    entry = fx.add_suppression(
        api,
        subject["id"],
        entry_type="DO_NOT_SELL",
        reason_code="DNS_REQUEST",
        expires_at=None,
    )
    assert entry["entry_type"] == "DO_NOT_SELL"
    assert entry["status"] == "ACTIVE"

    after = fx.reread_profile(api, subject["id"])
    assert_profile_axes(after, "RESOLVED", "SUPPRESSED")
    # No election was ever captured for this subject, so silence alone already
    # leaves every channel unauthorised.
    assert_activatable(after, [])

    # The other endpoint of the pair was never named, so both of its axes stand.
    untouched = fx.reread_profile(api, env["left"]["id"])
    assert_profile_axes(untouched, "RESOLVED", "NORMAL")


def test_releasing_the_entry_returns_the_privacy_axis_to_normal_with_resolution_intact(api):
    """Releasing the only active entry of a subject returns privacy_status to
    NORMAL, completing a round trip on one axis while the other never moved.

    "A `PrivacyOfficer` releases an `ACTIVE` entry, which moves it `ACTIVE` → `RELEASED`, stamps `released_by_user_id` with the acting `X-User-ID` and `released_at` at the logical clock now, and increments the entry's `version`."

    "The precedence order of §2.10 is applied afresh: the subject returns to `LEGAL_HOLD` if another active hold remains, to `SUPPRESSED` if another active narrow entry remains, and only to `NORMAL` when no entry of that subject is still `ACTIVE`, at which point `activatable_channels` is recomputed from the surviving elections and the pre-suppression channel set is restored."

    "Each axis gates different operations, and no transition on one axis is ever a precondition of a transition on the other; in particular, tombstoning a profile at the end of an erasure leaves `resolution_status` exactly as it found it."

    Design: Difficulty/non_linear_state_machine/profile_privacy_axis_moves_without_touching_resolution_axis
    """
    env = _axis_environment(api)
    subject = env["right"]

    entry = fx.add_suppression(
        api,
        subject["id"],
        entry_type="DO_NOT_SELL",
        reason_code="DNS_REQUEST",
        expires_at=None,
    )
    suppressed = fx.reread_profile(api, subject["id"])
    assert_profile_axes(suppressed, "RESOLVED", "SUPPRESSED")

    released = fx.release_suppression(api, entry["id"], PRIVACY)
    assert released["status"] == "RELEASED"
    assert_instant_equals(released["released_at"], "2026-08-01T00:00:00Z", "released_at")

    after = fx.reread_profile(api, subject["id"])
    assert_profile_axes(after, "RESOLVED", "NORMAL")


def test_a_proposed_link_decides_nothing_and_leaves_both_axes_where_they_were(api):
    """A candidate link minted inside the review band waits for a steward: it is
    PROPOSED, it names no survivor, and neither endpoint has moved on either axis.

    "Confidence is then computed from the four evidence values under a fixed weight table: an email component is worth 0.40, a phone 0.25, a name 0.20 and an address 0.15, the four summing to exactly 1.00."

    "Under `STRICT_ZERO` the confidence **is** the raw score, measured against the full weight base of 1.00; an absent component therefore contributes nothing and permanently caps what a sparse pair can score, no matter how perfect the evidence it does have."

    "At or above `review_floor` but below `auto_merge_threshold`, the link is created as `PROPOSED` and waits for a steward."

    Design: Difficulty/non_linear_state_machine/profile_privacy_axis_moves_without_touching_resolution_axis
    """
    env = _axis_environment(api)

    link = fx.proposed_link(
        api,
        env["left"]["id"],
        env["right"]["id"],
        env["rule"]["id"],
        f.evidence(**SPARSE_PERFECT_EVIDENCE),
    )
    assert link["confidence"] == approx4(EXPECTED_CONFIDENCE)
    assert link["status"] == "PROPOSED"
    assert link["survivor_profile_id"] is None
    assert link["decided_by_user_id"] is None
    assert link["decided_at"] is None

    for profile in (env["left"], env["right"]):
        current = fx.reread_profile(api, profile["id"])
        assert_profile_axes(current, "RESOLVED", "NORMAL")
        assert current["merged_into_profile_id"] is None
        assert current["source_record_count"] == 1


def test_confirming_the_link_moves_the_resolution_axis_while_privacy_stays_normal(api):
    """Confirming the candidate merges the pair: the loser travels
    RESOLVED -> MERGED_AWAY on the resolution axis while its privacy_status is
    left at NORMAL, the two axes moving entirely independently of one another.

    "Survivorship is decided by three discriminators applied in order, the first that separates the pair winning outright: the higher `source_record_count`; then the higher `trust_tier` of the feed named by the profile's `primary_source_system_id`; then the earlier `created_at`."

    "The loser is then torn down: its `resolution_status` moves `RESOLVED` → `MERGED_AWAY`, its `merged_into_profile_id` names the survivor, its `household_id` is cleared because household membership follows the surviving identity, its `lifetime_value_cents` is set to 0 because the value moved rather than duplicated, and its `activatable_channels` becomes empty."

    "Four quantities roll up onto the survivor: `source_record_count` and `lifetime_value_cents` each increase by the loser's amount, `contributing_source_system_codes` becomes the sorted union of both lists, `last_activity_at` becomes the later of the two, and `loyalty_tier` becomes the higher of the two on the `NONE`-`SILVER`-`GOLD`-`PLATINUM` ordinal scale."

    Design: Difficulty/non_linear_state_machine/profile_privacy_axis_moves_without_touching_resolution_axis
    """
    env = _axis_environment(api)
    # The privacy axis has already made a full round trip on the loser, so the
    # merge below starts from privacy_status NORMAL.
    entry = fx.add_suppression(
        api,
        env["right"]["id"],
        entry_type="DO_NOT_SELL",
        reason_code="DNS_REQUEST",
        expires_at=None,
    )
    fx.release_suppression(api, entry["id"], PRIVACY)

    link = fx.proposed_link(
        api,
        env["left"]["id"],
        env["right"]["id"],
        env["rule"]["id"],
        f.evidence(**SPARSE_PERFECT_EVIDENCE),
    )
    decided = fx.decide_link(api, link["id"], "CONFIRM")

    assert decided["status"] == "CONFIRMED"
    assert decided["survivor_profile_id"] == env["left"]["id"]

    loser = fx.reread_profile(api, env["right"]["id"])
    assert_profile_axes(loser, "MERGED_AWAY", "NORMAL")
    assert loser["merged_into_profile_id"] == env["left"]["id"]
    assert loser["lifetime_value_cents"] == 0
    assert loser["activatable_channels"] == []

    survivor = fx.reread_profile(api, env["left"]["id"])
    assert_profile_axes(survivor, "RESOLVED", "NORMAL")
    assert survivor["merged_into_profile_id"] is None
    assert survivor["source_record_count"] == 2


def test_confirm_branch_of_the_decision_fork_merges_and_credits_the_rule(api):
    """The CONFIRM arm of the decision endpoint mutates both endpoint profiles and
    advances the minting rule's confirmed_count, the wide half of the fork.

    "A steward adjudicates a `PROPOSED` link by recording a `decision` of either `CONFIRM` or `REJECT`."

    "This is a **branching fork**: the two branches share no side effect beyond the link's own status, `decided_by_user_id` (set to the acting `X-User-ID`), `decided_at` and its `version` increment."

    "Alongside all of this, the rule's `confirmed_count` increases by 1 and its `precision_estimate` is recomputed."

    Design: Difficulty/non_linear_state_machine/identity_link_fork_confirm_and_reject_share_no_side_effect
    """
    env = _four_profiles(api)
    link = fx.proposed_link(
        api,
        env["p1"]["id"],
        env["p2"]["id"],
        env["rule"]["id"],
        f.evidence(**SPARSE_PERFECT_EVIDENCE),
    )
    assert link["status"] == "PROPOSED"

    decided = fx.decide_link(api, link["id"], "CONFIRM")
    assert decided["status"] == "CONFIRMED"
    assert decided["survivor_profile_id"] == env["p1"]["id"]
    assert decided["decided_by_user_id"] == STEWARD["X-User-ID"]
    assert_instant_equals(decided["decided_at"], "2026-08-01T00:00:00Z", "decided_at")

    loser = fx.reread_profile(api, env["p2"]["id"])
    assert_profile_axes(loser, "MERGED_AWAY", "NORMAL")
    assert loser["merged_into_profile_id"] == env["p1"]["id"]

    survivor = fx.reread_profile(api, env["p1"]["id"])
    assert survivor["source_record_count"] == 2

    rule = fx.reread_rule(api, env["rule"]["id"])
    assert rule["confirmed_count"] == 1
    assert rule["rejected_count"] == 0
    assert rule["precision_estimate"] == approx4(1.0)
    assert rule["status"] == "ENABLED"


def test_reject_branch_of_the_decision_fork_mutates_no_profile(api):
    """The REJECT arm shares no profile side effect with the CONFIRM arm: neither
    endpoint of the rejected link moves, and the link names no survivor.

    "The confirm branch additionally requires both profiles to be `RESOLVED` and neither to be under `LEGAL_HOLD`, `DELETED` or `DELETION_PENDING`; the reject branch imposes no profile condition at all, since it touches no profile."

    "No profile is mutated: `survivor_profile_id` stays null and both profiles keep `resolution_status` of `RESOLVED`."

    Design: Difficulty/non_linear_state_machine/identity_link_fork_confirm_and_reject_share_no_side_effect
    """
    env = _four_profiles(api)
    # The confirm arm runs first so the rule's precision never dips under its own
    # min_precision of 0.40 while the reject arm is being observed.
    confirm_link = fx.proposed_link(
        api,
        env["p1"]["id"],
        env["p2"]["id"],
        env["rule"]["id"],
        f.evidence(**SPARSE_PERFECT_EVIDENCE),
    )
    fx.decide_link(api, confirm_link["id"], "CONFIRM")

    reject_link = fx.proposed_link(
        api,
        env["p3"]["id"],
        env["p4"]["id"],
        env["rule"]["id"],
        f.evidence(**SPARSE_PERFECT_EVIDENCE),
    )
    decided = fx.decide_link(api, reject_link["id"], "REJECT")

    assert decided["status"] == "REJECTED"
    assert decided["survivor_profile_id"] is None
    assert decided["decided_by_user_id"] == STEWARD["X-User-ID"]

    for key in ("p3", "p4"):
        profile = fx.reread_profile(api, env[key]["id"])
        assert_profile_axes(profile, "RESOLVED", "NORMAL")
        assert profile["source_record_count"] == 1
        assert profile["merged_into_profile_id"] is None
        assert profile["lifetime_value_cents"] == 0


def test_reject_branch_moves_only_the_rule_counters_and_leaves_it_enabled(api):
    """One confirmation and one rejection put the rule's precision_estimate at
    0.5000, which is not below its min_precision of 0.40, so the rule survives.

    "Instead the rule's `rejected_count` increases by 1 and `precision_estimate` is recomputed as `confirmed_count` divided by the sum of `confirmed_count` and `rejected_count`, rounded half up to four decimal places, and held at exactly 1.0 while that denominator is 0."

    "Where the recomputed estimate falls strictly below the rule's own `min_precision`, hop two moves the rule `ENABLED` → `DISABLED`, and hop three voids every **other** link minted by that rule whose status is still `PROPOSED`, each with `void_reason` of `RULE_DISABLED`."

    Design: Difficulty/non_linear_state_machine/identity_link_fork_confirm_and_reject_share_no_side_effect
    """
    env = _four_profiles(api)
    confirm_link = fx.proposed_link(
        api,
        env["p1"]["id"],
        env["p2"]["id"],
        env["rule"]["id"],
        f.evidence(**SPARSE_PERFECT_EVIDENCE),
    )
    fx.decide_link(api, confirm_link["id"], "CONFIRM")

    reject_link = fx.proposed_link(
        api,
        env["p3"]["id"],
        env["p4"]["id"],
        env["rule"]["id"],
        f.evidence(**SPARSE_PERFECT_EVIDENCE),
    )
    fx.decide_link(api, reject_link["id"], "REJECT")

    rule = fx.reread_rule(api, env["rule"]["id"])
    assert rule["confirmed_count"] == 1
    assert rule["rejected_count"] == 1
    assert rule["precision_estimate"] == approx4(0.5)
    assert rule["status"] == "ENABLED"

    # The confirmed link is untouched by the later rejection, and the rejected
    # link never acquired a survivor.
    assert fx.reread_link(api, confirm_link["id"])["status"] == "CONFIRMED"
    assert fx.reread_link(api, reject_link["id"])["status"] == "REJECTED"
