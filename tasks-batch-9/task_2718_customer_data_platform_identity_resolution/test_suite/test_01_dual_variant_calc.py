"""Two calculations that each carry two variants selected by a stored policy field.

The first is an identity link's `confidence`, whose denominator is chosen by the
minting match rule's `missing_identifier_policy`. The second is an activation's
`effective_match_rate`, chosen by the destination's `match_rate_basis`. In both
cases byte-identical input data lands the affected resource in a different state
depending only on which variant the parent resource nominated.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_CONFIDENCE_BELOW_FLOOR
from test_helpers.assertions import (
    approx4,
    assert_instant_equals,
    assert_profile_axes,
)
from test_helpers.constants import DEFAULT_CLOCK
from test_helpers.test_users import ADMIN, STEWARD

# The evidence shared by both policy arms: three perfect components and one that
# is absent on at least one side of the pair.
SPARSE_PERFECT_EVIDENCE = f.evidence(
    email_similarity=1.0,
    phone_similarity=1.0,
    name_similarity=1.0,
    address_similarity=None,
)


def _rule(api, policy):
    """A probabilistic rule differing from its sibling only in its policy."""
    return fx.declare_probabilistic_rule(
        api,
        missing_identifier_policy=policy,
        review_floor=0.65,
        auto_merge_threshold=0.92,
        min_precision=0.40,
    )


def _profiles_by_email(api, batch_id):
    """The profiles a promotion minted, keyed by their normalized email."""
    return {p["email_norm"]: p for p in fx.batch_profiles(api, batch_id)}


# ---------------------------------------------------------------------------
# Difficulty/dual_variant_calc/confidence_strict_zero_vs_renormalize_forks_link_state
# ---------------------------------------------------------------------------
def test_strict_zero_policy_scores_sparse_evidence_against_the_full_weight_base(api):
    """Evidence of three perfect components and one absent component scored under a
    STRICT_ZERO rule yields 0.8500, which sits inside the review band, so the link
    is created PROPOSED with no survivor and neither profile is merged.

    "Confidence is then computed from the four evidence values under a fixed weight table: an email component is worth 0.40, a phone 0.25, a name 0.20 and an address 0.15, the four summing to exactly 1.00."
    "The **raw** score is the sum, over only those components whose evidence value is non-null, of that component's weight multiplied by its similarity value."
    "Under `STRICT_ZERO` the confidence **is** the raw score, measured against the full weight base of 1.00; an absent component therefore contributes nothing and permanently caps what a sparse pair can score, no matter how perfect the evidence it does have."
    "At or above `review_floor` but below `auto_merge_threshold`, the link is created as `PROPOSED` and waits for a steward."
    "Every link records its `match_method` copied from the minting rule's `rule_kind`, and holds `survivor_profile_id`, `decided_by_user_id`, `decided_at` and `void_reason` null until something decides it."

    Design: Difficulty/dual_variant_calc/confidence_strict_zero_vs_renormalize_forks_link_state
    """
    fx.set_clock(api, DEFAULT_CLOCK)
    env = fx.two_profiles(api)
    rule = _rule(api, "STRICT_ZERO")

    link = validate_success(
        api.create_identity_link(
            f.identity_link_payload(
                env["left"]["id"],
                env["right"]["id"],
                rule["id"],
                SPARSE_PERFECT_EVIDENCE,
            ),
            STEWARD,
        ),
        201,
    )

    # 0.40 * 1.0 + 0.25 * 1.0 + 0.20 * 1.0 = 0.8500 over the full base of 1.00.
    assert link["confidence"] == approx4(0.8500)
    assert link["status"] == "PROPOSED"
    assert link["match_method"] == "PROBABILISTIC"
    assert link["survivor_profile_id"] is None
    assert link["decided_by_user_id"] is None
    assert link["decided_at"] is None
    assert link["void_reason"] is None

    left = fx.reread_profile(api, env["left"]["id"])
    right = fx.reread_profile(api, env["right"]["id"])
    assert_profile_axes(left, "RESOLVED", "NORMAL")
    assert_profile_axes(right, "RESOLVED", "NORMAL")
    assert left["source_record_count"] == 1
    assert right["source_record_count"] == 1
    assert left["merged_into_profile_id"] is None
    assert right["merged_into_profile_id"] is None

    unchanged_rule = fx.reread_rule(api, rule["id"])
    assert unchanged_rule["confirmed_count"] == 0
    assert unchanged_rule["rejected_count"] == 0
    assert unchanged_rule["precision_estimate"] == approx4(1.0)


def test_renormalize_policy_shrinks_the_denominator_and_auto_confirms_the_merge(api):
    """The same sparse evidence scored under a RENORMALIZE rule divides by the summed
    weight of the present components only, giving 1.0000, which is at or above the
    merge threshold, so the link confirms itself and the merge runs in that call.

    "Under `RENORMALIZE` the denominator shrinks to the summed weight of the present components only, so a pair that matches perfectly on everything it has scores 1.0000 even with two of the four components missing; where that summed present weight is 0 — every component absent — the confidence is exactly 0.0000 rather than an undefined division."
    "In both policies the result is rounded half up to four decimal places before any threshold comparison."
    "At or above `auto_merge_threshold` the link is created and immediately advanced `PROPOSED` → `CONFIRMED` with `decided_by_user_id` set to the literal string `system` rather than to any header value, `decided_at` stamped at the logical clock now, and the full merge run inside the creating call — the platform's only machine-authored merge."
    "The loser is then torn down: its `resolution_status` moves `RESOLVED` → `MERGED_AWAY`, its `merged_into_profile_id` names the survivor, its `household_id` is cleared because household membership follows the surviving identity, its `lifetime_value_cents` is set to 0 because the value moved rather than duplicated, and its `activatable_channels` becomes empty."
    "Alongside all of this, the rule's `confirmed_count` increases by 1 and its `precision_estimate` is recomputed."

    Design: Difficulty/dual_variant_calc/confidence_strict_zero_vs_renormalize_forks_link_state
    """
    fx.set_clock(api, DEFAULT_CLOCK)
    env = fx.two_profiles(api)
    rule = _rule(api, "RENORMALIZE")

    link = validate_success(
        api.create_identity_link(
            f.identity_link_payload(
                env["left"]["id"],
                env["right"]["id"],
                rule["id"],
                SPARSE_PERFECT_EVIDENCE,
            ),
            STEWARD,
        ),
        201,
    )

    # 0.8500 raw over a present weight of 0.40 + 0.25 + 0.20 = 0.85 is 1.0000.
    assert link["confidence"] == approx4(1.0000)
    assert link["status"] == "CONFIRMED"
    assert link["decided_by_user_id"] == "system"
    assert_instant_equals(link["decided_at"], DEFAULT_CLOCK, "decided_at")

    endpoints = {env["left"]["id"], env["right"]["id"]}
    survivor_id = link["survivor_profile_id"]
    assert survivor_id in endpoints, "the survivor must be one of the two endpoints"
    loser_id = (endpoints - {survivor_id}).pop()

    survivor = fx.reread_profile(api, survivor_id)
    loser = fx.reread_profile(api, loser_id)
    assert_profile_axes(survivor, "RESOLVED", "NORMAL")
    assert loser["resolution_status"] == "MERGED_AWAY"
    assert loser["merged_into_profile_id"] == survivor_id
    assert loser["lifetime_value_cents"] == 0
    assert loser["activatable_channels"] == []
    assert survivor["source_record_count"] == 2
    assert survivor["merged_into_profile_id"] is None

    decided_rule = fx.reread_rule(api, rule["id"])
    assert decided_rule["confirmed_count"] == 1
    assert decided_rule["rejected_count"] == 0
    assert decided_rule["precision_estimate"] == approx4(1.0)


def test_identical_evidence_forks_by_exactly_the_absent_component_weight(api):
    """Two rules that differ only in `missing_identifier_policy` score byte-identical
    evidence 0.8500 and 1.0000 — a gap of exactly the absent address component's
    weight — leaving one link PROPOSED and confirming the other on the spot.

    "Under `STRICT_ZERO` the confidence **is** the raw score, measured against the full weight base of 1.00; an absent component therefore contributes nothing and permanently caps what a sparse pair can score, no matter how perfect the evidence it does have."
    "Under `RENORMALIZE` the denominator shrinks to the summed weight of the present components only, so a pair that matches perfectly on everything it has scores 1.0000 even with two of the four components missing; where that summed present weight is 0 — every component absent — the confidence is exactly 0.0000 rather than an undefined division."
    "The rounded confidence decides the link's fate against the minting rule's own thresholds, and both boundaries are inclusive."
    "`resolution_status` records identity resolution and moves `UNRESOLVED` → `RESOLVED` → `MERGED_AWAY`."

    Design: Difficulty/dual_variant_calc/confidence_strict_zero_vs_renormalize_forks_link_state
    """
    fx.set_clock(api, DEFAULT_CLOCK)
    records = [
        f.raw_record("R1", email_raw="r1@example.com", loyalty_number="LY00000001"),
        f.raw_record("R2", email_raw="r2@example.com", loyalty_number="LY00000002"),
        f.raw_record("R3", email_raw="r3@example.com", loyalty_number="LY00000003"),
        f.raw_record("R4", email_raw="r4@example.com", loyalty_number="LY00000004"),
    ]
    env = fx.promoted_batch(api, records)
    minted = _profiles_by_email(api, env["batch"]["id"])
    assert len(minted) == 4, "setup expected four distinctly identified profiles"
    p1, p2 = minted["r1@example.com"], minted["r2@example.com"]
    p3, p4 = minted["r3@example.com"], minted["r4@example.com"]

    strict_rule = _rule(api, "STRICT_ZERO")
    renorm_rule = _rule(api, "RENORMALIZE")

    strict_link = validate_success(
        api.create_identity_link(
            f.identity_link_payload(
                p1["id"], p2["id"], strict_rule["id"], SPARSE_PERFECT_EVIDENCE
            ),
            STEWARD,
        ),
        201,
    )
    renorm_link = validate_success(
        api.create_identity_link(
            f.identity_link_payload(
                p3["id"], p4["id"], renorm_rule["id"], SPARSE_PERFECT_EVIDENCE
            ),
            STEWARD,
        ),
        201,
    )

    assert strict_link["confidence"] == approx4(0.8500)
    assert renorm_link["confidence"] == approx4(1.0000)
    assert renorm_link["confidence"] - strict_link["confidence"] == approx4(0.1500)
    assert strict_link["status"] == "PROPOSED"
    assert renorm_link["status"] == "CONFIRMED"

    # The strict pair is untouched; the renormalized pair merged.
    assert fx.reread_profile(api, p1["id"])["resolution_status"] == "RESOLVED"
    assert fx.reread_profile(api, p2["id"])["resolution_status"] == "RESOLVED"
    survivor_id = renorm_link["survivor_profile_id"]
    assert survivor_id in {p3["id"], p4["id"]}
    loser_id = ({p3["id"], p4["id"]} - {survivor_id}).pop()
    assert fx.reread_profile(api, survivor_id)["resolution_status"] == "RESOLVED"
    assert fx.reread_profile(api, loser_id)["resolution_status"] == "MERGED_AWAY"
    assert fx.reread_profile(api, loser_id)["merged_into_profile_id"] == survivor_id

    assert fx.reread_rule(api, strict_rule["id"])["confirmed_count"] == 0
    assert fx.reread_rule(api, renorm_rule["id"])["confirmed_count"] == 1


def test_renormalize_with_every_component_absent_scores_zero_and_mints_nothing(api):
    """When every evidence component is null the renormalized denominator would be
    zero, so the confidence is pinned at exactly 0.0000, which is below the review
    floor and refuses the proposal without creating a link.

    "Under `RENORMALIZE` the denominator shrinks to the summed weight of the present components only, so a pair that matches perfectly on everything it has scores 1.0000 even with two of the four components missing; where that summed present weight is 0 — every component absent — the confidence is exactly 0.0000 rather than an undefined division."
    "Below `review_floor` no link is created and the proposal fails with `ERR_CONFIDENCE_BELOW_FLOOR`."

    Design: Difficulty/dual_variant_calc/confidence_strict_zero_vs_renormalize_forks_link_state
    """
    fx.set_clock(api, DEFAULT_CLOCK)
    env = fx.two_profiles(api)
    rule = _rule(api, "RENORMALIZE")

    response = api.create_identity_link(
        f.identity_link_payload(
            env["left"]["id"],
            env["right"]["id"],
            rule["id"],
            f.evidence(None, None, None, None),
        ),
        STEWARD,
    )
    validate_error(response, ERR_CONFIDENCE_BELOW_FLOOR)

    assert fx.rows(api.list_identity_links(ADMIN, {"limit": 100, "offset": 0})) == []
    assert_profile_axes(fx.reread_profile(api, env["left"]["id"]), "RESOLVED", "NORMAL")
    assert_profile_axes(fx.reread_profile(api, env["right"]["id"]), "RESOLVED", "NORMAL")


# ---------------------------------------------------------------------------
# Difficulty/dual_variant_calc/match_rate_gross_vs_net_forks_activation_state
# ---------------------------------------------------------------------------
def _rate_destination(api, basis):
    """A destination differing from its sibling only in its nominated rate basis."""
    return fx.register_destination(
        api,
        match_rate_basis=basis,
        min_match_rate=0.70,
        min_audience_size=3,
        daily_hash_quota=100,
    )


def _delivery_environment(api, bases):
    """Three emailable members delivered to one dispatched activation per basis."""
    env = fx.emailable_profiles(api, 3)
    env["segment"] = fx.approved_segment(api, list(f.POSTAL_10001))
    env["arms"] = {}
    for basis in bases:
        destination = _rate_destination(api, basis)
        activation = fx.draft_activation(
            api, env["segment"]["id"], destination["id"]
        )
        env["arms"][basis] = {
            "destination": destination,
            "activation": fx.dispatch(api, activation["id"]),
        }
    return env


def test_gross_basis_divides_by_everything_dispatched_and_underperforms(api):
    """A destination on the GROSS basis takes its effective rate from the gross
    variant, so a report of two matches and one unusable hash out of three dispatched
    scores 0.6667, falls below the 0.70 floor and lands the activation UNDERPERFORMING.

    "`gross_match_rate` divides `vendor_matched_count` by `dispatched_hash_count`, or is exactly 0.0000 where nothing was dispatched."
    "`net_match_rate` divides `vendor_matched_count` by the usable count — `dispatched_hash_count` less `unusable_hash_count` — or is exactly 0.0000 where that usable count is zero or negative."
    "Both round half up to four decimal places."
    "`effective_match_rate` is the gross rate where the destination's `match_rate_basis` is `GROSS` and the net rate otherwise; all three are null until the first report arrives."
    "The effective rate routes the activation, inclusively at the boundary: at or above the destination's `min_match_rate` the activation becomes `ACTIVE`, and strictly below it becomes `UNDERPERFORMING`."
    "Every entry into `UNDERPERFORMING` increments the destination's `underperforming_activation_count` by 1 and every recovery to `ACTIVE` decrements it by 1."

    Design: Difficulty/dual_variant_calc/match_rate_gross_vs_net_forks_activation_state
    """
    fx.set_clock(api, DEFAULT_CLOCK)
    env = _delivery_environment(api, ["GROSS"])
    arm = env["arms"]["GROSS"]
    assert arm["activation"]["dispatched_hash_count"] == 3

    reported = fx.report_match(
        api, arm["activation"]["id"], arm["destination"]["id"], 2, 1
    )

    # 2 / 3 = 0.6667 gross; 2 / (3 - 1) = 1.0000 net; the gross variant governs.
    assert reported["gross_match_rate"] == approx4(0.6667)
    assert reported["net_match_rate"] == approx4(1.0000)
    assert reported["effective_match_rate"] == approx4(0.6667)
    assert reported["status"] == "UNDERPERFORMING"

    destination = fx.reread_destination(api, arm["destination"]["id"])
    assert destination["underperforming_activation_count"] == 1
    assert fx.reread_segment(api, env["segment"]["id"])["member_count"] == 3


def test_net_basis_removes_unusable_hashes_from_the_denominator_and_stays_active(api):
    """A destination on the NET basis takes its effective rate from the net variant, so
    the very same report scores 1.0000, clears the 0.70 floor and drives the activation
    to ACTIVE while the destination's underperforming counter never moves.

    "`net_match_rate` divides `vendor_matched_count` by the usable count — `dispatched_hash_count` less `unusable_hash_count` — or is exactly 0.0000 where that usable count is zero or negative."
    "The gross basis divides by everything that was sent, so hashes the platform could not even parse count against the marketer and the destination carries no credit for its own data hygiene; the net basis removes the unusable hashes from the denominator, so the rate measures only what the platform could actually evaluate."
    "`effective_match_rate` is the gross rate where the destination's `match_rate_basis` is `GROSS` and the net rate otherwise; all three are null until the first report arrives."
    "The effective rate routes the activation, inclusively at the boundary: at or above the destination's `min_match_rate` the activation becomes `ACTIVE`, and strictly below it becomes `UNDERPERFORMING`."

    Design: Difficulty/dual_variant_calc/match_rate_gross_vs_net_forks_activation_state
    """
    fx.set_clock(api, DEFAULT_CLOCK)
    env = _delivery_environment(api, ["NET"])
    arm = env["arms"]["NET"]
    assert arm["activation"]["dispatched_hash_count"] == 3

    reported = fx.report_match(
        api, arm["activation"]["id"], arm["destination"]["id"], 2, 1
    )

    assert reported["gross_match_rate"] == approx4(0.6667)
    assert reported["net_match_rate"] == approx4(1.0000)
    assert reported["effective_match_rate"] == approx4(1.0000)
    assert reported["status"] == "ACTIVE"

    destination = fx.reread_destination(api, arm["destination"]["id"])
    assert destination["underperforming_activation_count"] == 0


def test_both_rate_variants_are_stored_and_only_the_basis_forks_the_state(api):
    """Two destinations differing only in `match_rate_basis` receive identical reports:
    both activations store the same gross and net figures, but the GROSS arm lands
    UNDERPERFORMING while the NET arm lands ACTIVE.

    "Two rates are then computed and **both are always stored**, whichever one the destination has nominated."
    "Identical report data therefore yields a strictly higher net rate and can land the activation in a **different state** than the gross basis would."
    "`effective_match_rate` is the gross rate where the destination's `match_rate_basis` is `GROSS` and the net rate otherwise; all three are null until the first report arrives."
    "Every entry into `UNDERPERFORMING` increments the destination's `underperforming_activation_count` by 1 and every recovery to `ACTIVE` decrements it by 1."

    Design: Difficulty/dual_variant_calc/match_rate_gross_vs_net_forks_activation_state
    """
    fx.set_clock(api, DEFAULT_CLOCK)
    env = _delivery_environment(api, ["GROSS", "NET"])
    gross_arm = env["arms"]["GROSS"]
    net_arm = env["arms"]["NET"]
    assert gross_arm["activation"]["dispatched_hash_count"] == 3
    assert net_arm["activation"]["dispatched_hash_count"] == 3
    assert gross_arm["activation"]["gross_match_rate"] is None
    assert net_arm["activation"]["effective_match_rate"] is None

    gross_reported = fx.report_match(
        api, gross_arm["activation"]["id"], gross_arm["destination"]["id"], 2, 1
    )
    net_reported = fx.report_match(
        api, net_arm["activation"]["id"], net_arm["destination"]["id"], 2, 1
    )

    # Both variants are stored on both activations, identical in value.
    assert gross_reported["gross_match_rate"] == approx4(0.6667)
    assert gross_reported["net_match_rate"] == approx4(1.0000)
    assert net_reported["gross_match_rate"] == approx4(0.6667)
    assert net_reported["net_match_rate"] == approx4(1.0000)

    # Only the nominated basis, and therefore the state, differs.
    assert gross_reported["effective_match_rate"] == approx4(0.6667)
    assert net_reported["effective_match_rate"] == approx4(1.0000)
    assert gross_reported["status"] == "UNDERPERFORMING"
    assert net_reported["status"] == "ACTIVE"

    assert (
        fx.reread_destination(api, gross_arm["destination"]["id"])[
            "underperforming_activation_count"
        ]
        == 1
    )
    assert (
        fx.reread_destination(api, net_arm["destination"]["id"])[
            "underperforming_activation_count"
        ]
        == 0
    )


def test_net_rate_is_pinned_to_zero_when_every_dispatched_hash_is_unusable(api):
    """When all three dispatched hashes are reported unusable the net denominator is
    zero, so the net rate is pinned at exactly 0.0000 rather than divided, and the NET
    destination's activation falls below its floor into UNDERPERFORMING.

    "`net_match_rate` divides `vendor_matched_count` by the usable count — `dispatched_hash_count` less `unusable_hash_count` — or is exactly 0.0000 where that usable count is zero or negative."
    "`gross_match_rate` divides `vendor_matched_count` by `dispatched_hash_count`, or is exactly 0.0000 where nothing was dispatched."
    "The effective rate routes the activation, inclusively at the boundary: at or above the destination's `min_match_rate` the activation becomes `ACTIVE`, and strictly below it becomes `UNDERPERFORMING`."

    Design: Difficulty/dual_variant_calc/match_rate_gross_vs_net_forks_activation_state
    """
    fx.set_clock(api, DEFAULT_CLOCK)
    env = _delivery_environment(api, ["NET"])
    arm = env["arms"]["NET"]
    assert arm["activation"]["dispatched_hash_count"] == 3

    reported = fx.report_match(
        api, arm["activation"]["id"], arm["destination"]["id"], 0, 3
    )

    assert reported["gross_match_rate"] == approx4(0.0000)
    assert reported["net_match_rate"] == approx4(0.0000)
    assert reported["effective_match_rate"] == approx4(0.0000)
    assert reported["status"] == "UNDERPERFORMING"
    assert (
        fx.reread_destination(api, arm["destination"]["id"])[
            "underperforming_activation_count"
        ]
        == 1
    )
