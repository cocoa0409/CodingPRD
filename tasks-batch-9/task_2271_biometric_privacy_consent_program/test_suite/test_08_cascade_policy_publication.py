"""The re-publication chain fired by publishing a second policy version.

Publishing v2.0 supersedes v1.0, sends every consent obtained under it back for
re-solicitation, gates and re-pins the points that relied on it, and restricts the
program.
"""

from test_helpers import (
    assert_asset_state,
    assert_program_state,
    baseline_with_granted_consent,
    create_published_policy,
    read_asset,
    read_consent,
    read_policy,
    read_program,
)


def _baseline_then_publish_v2(api, **policy_overrides):
    ctx = baseline_with_granted_consent(api, activation_clock="2026-08-15T00:00:00Z")
    payload = {"version_label": "v2.0", "retention_days": 60}
    payload.update(policy_overrides)
    ctx["policy_v2"] = create_published_policy(
        api, ctx["program_id"], [ctx["jurisdiction_id"]], **payload
    )
    return ctx


def test_publishing_a_new_version_supersedes_the_old_one_and_resolicits_its_consents(api):
    """Hops one and two: the old policy is superseded and its grants lapse.

    PRD §3.3: "**Hop 2**: because that policy was superseded, every consent
    record whose `pinned_policy_id` is the superseded policy and whose status is
    `GRANTED` transitions `GRANTED` → `RESOLICIT_REQUIRED`."

    The consent keeps pointing at the policy it was actually obtained under: only
    collection points re-pin, so the record's `pinned_policy_id` still names
    v1.0.

    Design: Difficulty/transitive_cascade/policy_publication_supersedes_resolicits_consents_then_gates_and_repins_assets
    """
    ctx = _baseline_then_publish_v2(api)

    assert ctx["policy_v2"]["status"] == "PUBLISHED"
    assert read_policy(api, ctx["policy_id"])["status"] == "SUPERSEDED"

    consent = read_consent(api, ctx["consent_id"])
    assert consent["status"] == "RESOLICIT_REQUIRED"
    assert consent["pinned_policy_id"] == ctx["policy_id"], (
        "a consent record is never re-pinned by the supersession cascade"
    )


def test_the_affected_point_is_gated_repinned_and_given_the_new_retention_horizon(api):
    """Hop three: the point re-pins to v2.0 and re-derives its horizon.

    PRD §3.3: "**Hop 3**: because those consents lost their grant, every
    collection point whose `pinned_policy_id` is the superseded policy and whose
    status is `ACTIVE` transitions `ACTIVE` → `GATED`, and re-pins its
    `pinned_policy_id` to the newly published policy when that point's state
    profile appears in the new policy's `jurisdiction_scope`."

    Collection still started on 2026-08-15, and v2.0 promises 60 days, so the new
    horizon is 2026-10-14.

    Design: Difficulty/transitive_cascade/policy_publication_supersedes_resolicits_consents_then_gates_and_repins_assets
    """
    ctx = _baseline_then_publish_v2(api)

    asset = read_asset(api, ctx["asset_id"])

    assert_asset_state(
        asset,
        status="GATED",
        pinned_policy_id=ctx["policy_v2"]["id"],
        collection_started_at="2026-08-15T00:00:00.000Z",
        destruction_due_at="2026-10-14T00:00:00.000Z",
        enrolled_subject_count=0,
        consent_gap_count=1,
    )


def test_publication_restricts_the_program_once_a_point_has_been_gated(api):
    """Hop four: posture follows the newly gated point and the new gap.

    PRD §3.3: "**Hop 4**: because collection points became gated, the program's
    `posture` is recomputed — a positive `gated_asset_count` raises it to at
    least `RESTRICTED`."

    Design: Difficulty/transitive_cascade/policy_publication_supersedes_resolicits_consents_then_gates_and_repins_assets
    """
    ctx = baseline_with_granted_consent(api, activation_clock="2026-08-15T00:00:00Z")

    assert_program_state(
        read_program(api, ctx["program_id"]),
        posture="OPEN",
        gated_asset_count=0,
        consent_gap_count=0,
    )

    create_published_policy(
        api,
        ctx["program_id"],
        [ctx["jurisdiction_id"]],
        version_label="v2.0",
        retention_days=60,
    )

    assert_program_state(
        read_program(api, ctx["program_id"]),
        posture="RESTRICTED",
        gated_asset_count=1,
        consent_gap_count=1,
    )
