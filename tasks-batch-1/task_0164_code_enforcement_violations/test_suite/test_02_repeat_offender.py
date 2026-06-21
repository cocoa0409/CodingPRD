"""Repeat-offender escalation: the multiplier frozen onto a notice at issuance
versus the live tier recomputed on an owner read.

PRD coverage: §3.5 (the rolling-window count, the >=2 REPEAT / >=4 CHRONIC
thresholds, the at-issuance freeze, and the live-on-read recomputation).
"""
from test_helpers import validate_success
from test_helpers import fixtures as F


OFFICER = F.OFFICER


def test_notice_freezes_first_tier_multiplier_at_issuance(api):
    """PRD §3.5: "At issuance, the tier is computed once and its multiplier is
    frozen onto the notice as `escalation_multiplier`; that frozen value never
    changes for that notice afterward, no matter how the owner's history later
    shifts."
    PRD §3.5: "The tier maps to a multiplier of exactly `1.0` for `FIRST`, `1.5`
    for `REPEAT`, and `2.0` for `CHRONIC`."

    Design: Difficulty/dual_variant_calc/repeat_offender_tier_at_issuance_vs_live_on_owner
    """
    F.set_clock("2026-01-01T00:00:00Z")
    F.seed_fee_schedule("MAJOR")
    owner = F.create_owner()

    # Prior #1 cured to COMPLIED (its own case stays open on its own parcel; the
    # rolling repeat count keys on notice status, not case closure — PRD §3.5).
    prop1 = F.create_property(owner["id"])
    case1 = F.create_case(prop1["id"])
    insp1 = F.add_violation_found_inspection(case1["id"])
    notice1 = F.issue_notice(case1["id"], insp1["id"], "MAJOR")
    F.cure_notice_to_complied(notice1["id"])

    # N3 issued NOW while the owner still has only 1 prior COMPLIED -> frozen FIRST (1.0).
    prop2 = F.create_property(owner["id"])
    case2 = F.create_case(prop2["id"])
    insp2 = F.add_violation_found_inspection(case2["id"])
    notice3 = F.issue_notice(case2["id"], insp2["id"], "MAJOR")

    got = validate_success(api.get_notice(notice3["id"], OFFICER))
    assert got["escalation_multiplier"] == 1.0, (
        f"expected frozen 1.0 (FIRST at issuance, 1 prior), got {got['escalation_multiplier']}"
    )


def test_owner_live_tier_repeat_after_two_prior_complied(api):
    """PRD §3.5: "An owner's `prior_violation_count` is the number of that owner's
    violation notices, across all of the owner's properties, whose status is
    `COMPLIED` or `UPHELD` and whose `effective_date` falls within a rolling window"
    PRD §3.5: "the tier is `CHRONIC` when the prior count is at least four,
    otherwise `REPEAT` when the prior count is at least two, otherwise `FIRST`."
    PRD §3.5: "On an owner read, by contrast, the tier is recomputed live against
    the current clock and reported as the owner's `repeat_tier` alongside the live
    `prior_violation_count`"

    Design: Difficulty/dual_variant_calc/repeat_offender_tier_at_issuance_vs_live_on_owner
    """
    F.set_clock("2026-01-01T00:00:00Z")
    F.seed_fee_schedule("MAJOR")
    owner = F.create_owner()
    # Two notices cured to COMPLIED within the 365-day window.
    F.raise_owner_to_repeat(owner["id"], "MAJOR")

    got = validate_success(api.get_owner(owner["id"], OFFICER))
    assert got["prior_violation_count"] == 2, (
        f"expected prior_violation_count 2, got {got['prior_violation_count']}"
    )
    assert got["repeat_tier"] == "REPEAT", (
        f"expected live REPEAT (>= threshold of 2), got {got['repeat_tier']}"
    )
