"""The two retention-horizon variants of a collection point.

Identical retention inputs produce two different destruction horizons depending
on the pinned policy's destruction trigger and the point's own retention basis.
"""

from test_helpers import (
    PRIVACY_OFFICER,
    access_control_asset_payload,
    assert_asset_state,
    assert_instant_equals,
    baseline_with_active_asset,
    create_asset,
    parse_instant,
    read_asset,
    set_clock,
    validate_success,
)


def test_purpose_limited_point_destroys_seven_days_after_the_purpose_was_satisfied(api):
    """A purpose-limited point under a purpose-satisfied policy destroys early.

    PRD §3.5: "The *purpose-satisfied-or-max* variant governs only when all three
    conditions hold together: the pinned policy's `destruction_trigger` is
    `PURPOSE_SATISFIED_OR_MAX`, the point's `retention_basis` is
    `PURPOSE_LIMITED`, and `purpose_satisfied_at` is not null. Under it,
    `destruction_due_at` is the earlier of two instants: `purpose_satisfied_at`
    plus a seven-day grace period, or the schedule horizon."

    Collection starts 2026-08-15 and the effective retention is 30 days, so the
    schedule horizon is 2026-09-14; the purpose was satisfied on 2026-08-20, so
    the graced purpose instant 2026-08-27 is the earlier one and governs.

    Design: Difficulty/dual_variant_calc/retention_destruction_purpose_limited_vs_schedule_only_divergence
    """
    ctx = baseline_with_active_asset(
        api,
        activation_clock="2026-08-15T00:00:00Z",
        policy_overrides={"destruction_trigger": "PURPOSE_SATISFIED_OR_MAX"},
        asset_overrides={"retention_basis": "PURPOSE_LIMITED"},
    )
    assert_asset_state(
        ctx["asset"],
        status="ACTIVE",
        pinned_policy_id=ctx["policy_id"],
        collection_started_at="2026-08-15T00:00:00.000Z",
        destruction_due_at="2026-09-14T00:00:00.000Z",
    )

    updated = validate_success(
        api.update_asset(
            ctx["asset_id"], {"purpose_satisfied_at": "2026-08-20T00:00:00Z"}, PRIVACY_OFFICER
        )
    )

    assert_instant_equals(updated["purpose_satisfied_at"], "2026-08-20T00:00:00.000Z", "purpose_satisfied_at")
    assert_asset_state(
        updated,
        collection_started_at="2026-08-15T00:00:00.000Z",
        destruction_due_at="2026-08-27T00:00:00.000Z",
        pinned_policy_id=ctx["policy_id"],
    )


def test_schedule_only_point_ignores_a_reported_purpose_instant(api):
    """A schedule-only point keeps its schedule horizon.

    PRD §3.5: "The *fixed-schedule* variant governs whenever the pinned policy's
    `destruction_trigger` is `FIXED_SCHEDULE`, **or** the point's
    `retention_basis` is `SCHEDULE_ONLY`, **or** `purpose_satisfied_at` is null.
    Under it, `destruction_due_at` is simply the schedule horizon, and a
    reported `purpose_satisfied_at` is ignored entirely."

    The pinned policy asks for purpose-driven destruction, but the point's basis
    is `SCHEDULE_ONLY`, so reporting a purpose instant of 2026-08-20 leaves the
    horizon at 2026-08-15 plus 30 days.

    Design: Difficulty/dual_variant_calc/retention_destruction_purpose_limited_vs_schedule_only_divergence
    """
    ctx = baseline_with_active_asset(
        api,
        activation_clock="2026-08-15T00:00:00Z",
        policy_overrides={"destruction_trigger": "PURPOSE_SATISFIED_OR_MAX"},
        asset_overrides={"retention_basis": "SCHEDULE_ONLY"},
    )

    updated = validate_success(
        api.update_asset(
            ctx["asset_id"], {"purpose_satisfied_at": "2026-08-20T00:00:00Z"}, PRIVACY_OFFICER
        )
    )

    assert_instant_equals(updated["purpose_satisfied_at"], "2026-08-20T00:00:00.000Z", "purpose_satisfied_at")
    assert_asset_state(
        updated,
        collection_started_at="2026-08-15T00:00:00.000Z",
        destruction_due_at="2026-09-14T00:00:00.000Z",
        pinned_policy_id=ctx["policy_id"],
    )


def test_two_points_under_one_policy_diverge_by_eighteen_days_on_retention_basis(api):
    """The same policy and the same purpose instant give two horizons.

    PRD §3.5: "Identical retention inputs therefore destroy templates strictly
    earlier under this variant whenever the graced purpose instant precedes the
    horizon."

    Both points start collecting on 2026-08-15 under the same 30-day policy and
    both report the purpose satisfied on 2026-08-20, so the purpose-limited
    point is due on 2026-08-27 while the schedule-only point is due on
    2026-09-14.

    Design: Difficulty/dual_variant_calc/retention_destruction_purpose_limited_vs_schedule_only_divergence
    """
    ctx = baseline_with_active_asset(
        api,
        activation_clock="2026-08-15T00:00:00Z",
        policy_overrides={"destruction_trigger": "PURPOSE_SATISFIED_OR_MAX"},
        asset_overrides={"retention_basis": "PURPOSE_LIMITED"},
    )
    purpose_limited_id = ctx["asset_id"]

    schedule_only = create_asset(
        api,
        ctx["program_id"],
        ctx["jurisdiction_id"],
        target_status="CLASSIFIED",
        payload_builder=access_control_asset_payload,
        retention_basis="SCHEDULE_ONLY",
    )
    set_clock(api, "2026-08-15T00:00:00Z")
    schedule_only = validate_success(
        api.transition_asset(schedule_only["id"], {"to_status": "ACTIVE"}, PRIVACY_OFFICER)
    )

    validate_success(
        api.update_asset(
            purpose_limited_id, {"purpose_satisfied_at": "2026-08-20T00:00:00Z"}, PRIVACY_OFFICER
        )
    )
    validate_success(
        api.update_asset(
            schedule_only["id"], {"purpose_satisfied_at": "2026-08-20T00:00:00Z"}, PRIVACY_OFFICER
        )
    )

    purpose_limited = read_asset(api, purpose_limited_id)
    schedule_only = read_asset(api, schedule_only["id"])

    assert_asset_state(
        purpose_limited,
        collection_started_at="2026-08-15T00:00:00.000Z",
        destruction_due_at="2026-08-27T00:00:00.000Z",
        pinned_policy_id=ctx["policy_id"],
    )
    assert_asset_state(
        schedule_only,
        collection_started_at="2026-08-15T00:00:00.000Z",
        destruction_due_at="2026-09-14T00:00:00.000Z",
        pinned_policy_id=ctx["policy_id"],
    )
    assert parse_instant(purpose_limited["destruction_due_at"]) < parse_instant(
        schedule_only["destruction_due_at"]
    ), "the purpose-limited horizon must be strictly earlier than the schedule horizon"
