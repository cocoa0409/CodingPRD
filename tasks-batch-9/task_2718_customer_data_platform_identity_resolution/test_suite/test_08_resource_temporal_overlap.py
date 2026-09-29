"""Interval semantics on two different resources.

Activation windows on a destination are CLOSED intervals separated by a mandatory
cooldown gap, so disjointness alone is not enough to be accepted. Suppression
windows on a profile are HALF-OPEN intervals with no gap requirement at all, so a
window that starts exactly where the incumbent ends merely touches it.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_ACTIVATION_COOLDOWN_VIOLATION,
    ERR_SUPPRESSION_WINDOW_OVERLAP,
)
from test_helpers.assertions import assert_ids_in_order, assert_instant_equals
from test_helpers.test_users import ADMIN, ANALYST, PRIVACY

# The incumbent activation window, a closed interval on the destination.
INCUMBENT_START = "2026-08-02T00:00:00Z"
INCUMBENT_END = "2026-08-02T02:00:00Z"
COOLDOWN_MINUTES = 60

# The incumbent suppression window, half-open on the profile.
SUPPRESSION_EFFECTIVE_AT = "2026-08-01T00:00:00Z"
SUPPRESSION_EXPIRES_AT = "2026-08-10T00:00:00Z"


def _cooldown_environment(api):
    """One promoted member, an approved segment, and one DRAFT activation.

    The destination carries a sixty-minute cooldown and a concurrency cap of two,
    so the cooldown gap is the only limit a disjoint second window can trip.
    """
    fx.reset_clock(api)
    return fx.activation_ready_environment(
        api,
        member_count=1,
        destination_overrides={
            "cooldown_minutes": COOLDOWN_MINUTES,
            "max_concurrent_activations": 2,
            "daily_hash_quota": 1000,
            "min_audience_size": 1,
        },
        window_start_at=INCUMBENT_START,
        window_end_at=INCUMBENT_END,
    )


def _create_second_activation(api, env, window_start_at, window_end_at):
    """Attempt a second activation on the same destination, returning the response.

    The segment's live version is read first so that the optimistic-concurrency
    guard on activation creation is satisfied and cannot mask the temporal check.
    """
    segment = fx.reread_segment(api, env["segment"]["id"])
    payload = f.activation_payload(
        env["segment"]["id"],
        env["destination"]["id"],
        segment["version"],
        window_start_at,
        window_end_at,
    )
    return segment, api.create_activation(payload, ANALYST)


def _suppressed_subject(api):
    """One promoted profile carrying an ACTIVE DO_NOT_SELL window over nine days."""
    fx.reset_clock(api)
    env = fx.single_profile(api)
    env["incumbent"] = fx.add_suppression(
        api,
        env["profile"]["id"],
        entry_type="DO_NOT_SELL",
        reason_code="CCPA_OPT_OUT",
        effective_at=SUPPRESSION_EFFECTIVE_AT,
        expires_at=SUPPRESSION_EXPIRES_AT,
    )
    return env


# ---------------------------------------------------------------------------
# closed activation windows and the cooldown gap
# ---------------------------------------------------------------------------
def test_disjoint_window_inside_the_cooldown_gap_is_refused(api):
    """A second window that starts thirty minutes after the incumbent's end is
    disjoint from it, yet the destination's sixty-minute cooldown has not elapsed,
    so creation is refused and the parent segment is left exactly as it was.

    "For every existing non-terminated activation on the same destination whose window is disjoint from the new one, the two must be separated by at least `cooldown_minutes` of clear time, measured end-to-start in both directions and inclusive at equality: either the new window starts at or after the other window's end advanced by the cooldown, or the other window starts at or after the new window's end advanced by the cooldown."

    "A violation is `ERR_ACTIVATION_COOLDOWN_VIOLATION`."

    "There is exactly one deliberate exception to the rule that an error response leaves state untouched, and it is described in §3.2: the requeue attempt that exhausts a batch's retry budget both fails and advances the batch to `REJECTED`."

    Design: Difficulty/resource_temporal_overlap/destination_cooldown_closed_interval_gap_boundary
    """
    env = _cooldown_environment(api)

    segment_before, response = _create_second_activation(
        api, env, "2026-08-02T02:30:00Z", "2026-08-02T04:00:00Z"
    )
    validate_error(response, ERR_ACTIVATION_COOLDOWN_VIOLATION)

    segment_after = fx.reread_segment(api, env["segment"]["id"])
    assert segment_after["version"] == segment_before["version"], (
        "a refused activation creation must not advance the parent segment's version"
    )
    assert segment_after["active_activation_count"] == 0

    rows, meta = validate_paginated(
        api.list_activations(
            ADMIN,
            {"destination_id": env["destination"]["id"], "limit": 100, "offset": 0},
        )
    )
    assert meta["total_count"] == 1, "the refused window must not have been persisted"
    assert_ids_in_order(rows, [env["activation"]["id"]])
    assert rows[0]["status"] == "DRAFT"


def test_disjoint_window_exactly_one_cooldown_after_the_previous_end_is_accepted(api):
    """A second window starting at exactly the incumbent's end advanced by the
    destination's cooldown clears the gap check, because the separation is
    inclusive at equality, and both windows then sit on the destination in
    creation order.

    "For every existing non-terminated activation on the same destination whose window is disjoint from the new one, the two must be separated by at least `cooldown_minutes` of clear time, measured end-to-start in both directions and inclusive at equality: either the new window starts at or after the other window's end advanced by the cooldown, or the other window starts at or after the new window's end advanced by the cooldown."

    "A new activation is `DRAFT` with every audience and match-rate field at its default, and the parent segment's `version` increments by 1."

    "Profiles, identity links, suppression entries, activations and downstream deletion tasks are ordered `created_at` ascending and then `id` ascending, so that the profiles minted by a single promotion appear in the record processing order described in §3.3, and the deletion tasks of a single fan-out appear in the destination registration order described in §3.11."

    Design: Difficulty/resource_temporal_overlap/destination_cooldown_closed_interval_gap_boundary
    """
    env = _cooldown_environment(api)

    _segment_before, response = _create_second_activation(
        api, env, "2026-08-02T03:00:00Z", "2026-08-02T04:00:00Z"
    )
    created = validate_success(response, 201)
    assert created["status"] == "DRAFT"
    assert_instant_equals(
        created["window_start_at"], "2026-08-02T03:00:00Z", "window_start_at"
    )
    assert_instant_equals(
        created["window_end_at"], "2026-08-02T04:00:00Z", "window_end_at"
    )

    rows, meta = validate_paginated(
        api.list_activations(
            ADMIN,
            {"destination_id": env["destination"]["id"], "limit": 100, "offset": 0},
        )
    )
    assert meta["total_count"] == 2
    assert_ids_in_order(rows, [env["activation"]["id"], created["id"]])
    assert rows[0]["status"] == "DRAFT"


def test_touching_closed_windows_are_outside_the_cooldown_scope(api):
    """A second window starting at the exact instant the incumbent ends shares
    that instant, because activation windows are closed at both ends, so the
    cooldown never applies and the pair is accepted under a concurrency cap of
    two.

    "Activation windows are closed intervals — both endpoints inclusive — so two windows that merely touch at a single instant do intersect and are therefore outside the cooldown's scope entirely."

    "No instant may be covered by more than `max_concurrent_activations` windows among this destination's activations in `DRAFT`, `DISPATCHED`, `ACTIVE`, `UNDERPERFORMING` or `PAUSED` — note that draft and paused activations still hold their slot, and only terminated ones release it."

    "The check sweeps the closed intervals, and a window that touches another only at an endpoint still counts as covering that shared instant."

    Design: Difficulty/resource_temporal_overlap/destination_cooldown_closed_interval_gap_boundary
    """
    env = _cooldown_environment(api)

    _segment_before, response = _create_second_activation(
        api, env, INCUMBENT_END, "2026-08-02T04:00:00Z"
    )
    created = validate_success(response, 201)
    assert created["status"] == "DRAFT"
    assert_instant_equals(created["window_start_at"], INCUMBENT_END, "window_start_at")

    rows, meta = validate_paginated(
        api.list_activations(
            ADMIN,
            {"destination_id": env["destination"]["id"], "limit": 100, "offset": 0},
        )
    )
    assert meta["total_count"] == 2
    assert_ids_in_order(rows, [env["activation"]["id"], created["id"]])


# ---------------------------------------------------------------------------
# half-open suppression windows on one subject
# ---------------------------------------------------------------------------
def test_suppression_window_overlapping_the_incumbent_of_the_same_type_is_refused(api):
    """A second DO_NOT_SELL window that starts one day before the incumbent's
    exclusive end genuinely overlaps it, so the platform refuses it and leaves
    the subject holding exactly one entry of that type.

    "Two entries of the same subject and the **same** `entry_type` may not overlap in time, a collision being `ERR_SUPPRESSION_WINDOW_OVERLAP`."

    "Only a `PrivacyOfficer` may add one, naming the subject with `profile_id`, an `entry_type`, a `reason_code` of one to forty characters after trimming, an `effective_at` that starts the window inclusively, and an optional `expires_at` that ends it exclusively and that must be strictly after `effective_at` when supplied."

    Design: Difficulty/resource_temporal_overlap/suppression_half_open_window_touching_is_accepted
    """
    env = _suppressed_subject(api)

    response = api.create_suppression_entry(
        f.suppression_entry_payload(
            env["profile"]["id"],
            entry_type="DO_NOT_SELL",
            reason_code="CCPA_OPT_OUT",
            effective_at="2026-08-09T00:00:00Z",
            expires_at="2026-08-15T00:00:00Z",
        ),
        PRIVACY,
    )
    validate_error(response, ERR_SUPPRESSION_WINDOW_OVERLAP)

    rows, meta = validate_paginated(
        api.list_suppression_entries(
            ADMIN,
            {
                "profile_id": env["profile"]["id"],
                "entry_type": "DO_NOT_SELL",
                "limit": 100,
                "offset": 0,
            },
        )
    )
    assert meta["total_count"] == 1, "the refused window must not have been persisted"
    assert_ids_in_order(rows, [env["incumbent"]["id"]])


def test_suppression_window_starting_exactly_on_the_incumbent_expiry_is_accepted(api):
    """Because the window is half-open, a second DO_NOT_SELL window whose
    effective_at equals the incumbent's expires_at merely touches it, so it is
    accepted and the subject ends up holding two active entries of that type.

    "Two entries of the same subject and the **same** `entry_type` may not overlap in time, a collision being `ERR_SUPPRESSION_WINDOW_OVERLAP`."

    "Because the window is half-open, a new entry whose `effective_at` falls exactly on an existing entry's `expires_at` merely touches it and is accepted; and because a null `expires_at` extends forever, an open-ended entry collides with every later window of its type."

    "The three narrow-purpose types move it `NORMAL` → `SUPPRESSED`; note that `DO_NOT_SELL` moves the axis to `SUPPRESSED` too, even though only the advertising channel is actually masked, because the subject is no longer in an unqualified normal state."

    Design: Difficulty/resource_temporal_overlap/suppression_half_open_window_touching_is_accepted
    """
    env = _suppressed_subject(api)

    response = api.create_suppression_entry(
        f.suppression_entry_payload(
            env["profile"]["id"],
            entry_type="DO_NOT_SELL",
            reason_code="CCPA_OPT_OUT",
            effective_at=SUPPRESSION_EXPIRES_AT,
            expires_at="2026-08-15T00:00:00Z",
        ),
        PRIVACY,
    )
    created = validate_success(response, 201)
    assert created["status"] == "ACTIVE"
    assert_instant_equals(
        created["effective_at"], SUPPRESSION_EXPIRES_AT, "effective_at"
    )
    assert created["entry_type"] == "DO_NOT_SELL"

    rows, meta = validate_paginated(
        api.list_suppression_entries(
            ADMIN,
            {
                "profile_id": env["profile"]["id"],
                "entry_type": "DO_NOT_SELL",
                "limit": 100,
                "offset": 0,
            },
        )
    )
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {env["incumbent"]["id"], created["id"]}

    subject = fx.reread_profile(api, env["profile"]["id"])
    assert subject["privacy_status"] == "SUPPRESSED"


def test_suppression_window_of_a_different_type_may_sit_inside_the_incumbent(api):
    """The overlap check is scoped to one subject and one entry type, so a
    GLOBAL_OPT_OUT window lying entirely inside the subject's DO_NOT_SELL window
    is accepted and both entries stay active side by side.

    "Two entries of the same subject and the **same** `entry_type` may not overlap in time, a collision being `ERR_SUPPRESSION_WINDOW_OVERLAP`."

    "Entries of *different* types never collide with each other, so a subject may simultaneously carry a `DO_NOT_SELL` and a `LEGAL_HOLD` covering the same days."

    "Entries are readable individually — exposing the window and the release audit fields — and as a list filterable by `profile_id`, `deletion_request_id`, `entry_type` and `status`, the first two being the reverse traversals of the entry's two foreign keys."

    Design: Difficulty/resource_temporal_overlap/suppression_half_open_window_touching_is_accepted
    """
    env = _suppressed_subject(api)

    response = api.create_suppression_entry(
        f.suppression_entry_payload(
            env["profile"]["id"],
            entry_type="GLOBAL_OPT_OUT",
            reason_code="CCPA_OPT_OUT",
            effective_at="2026-08-05T00:00:00Z",
            expires_at="2026-08-06T00:00:00Z",
        ),
        PRIVACY,
    )
    created = validate_success(response, 201)
    assert created["status"] == "ACTIVE"
    assert created["entry_type"] == "GLOBAL_OPT_OUT"

    do_not_sell_rows, do_not_sell_meta = validate_paginated(
        api.list_suppression_entries(
            ADMIN,
            {
                "profile_id": env["profile"]["id"],
                "entry_type": "DO_NOT_SELL",
                "limit": 100,
                "offset": 0,
            },
        )
    )
    assert do_not_sell_meta["total_count"] == 1
    assert_ids_in_order(do_not_sell_rows, [env["incumbent"]["id"]])

    all_rows, all_meta = validate_paginated(
        api.list_suppression_entries(
            ADMIN, {"profile_id": env["profile"]["id"], "limit": 100, "offset": 0}
        )
    )
    assert all_meta["total_count"] == 2
    assert {row["id"] for row in all_rows} == {env["incumbent"]["id"], created["id"]}
    assert all(row["status"] == "ACTIVE" for row in all_rows)

    subject = fx.reread_profile(api, env["profile"]["id"])
    assert subject["privacy_status"] == "SUPPRESSED"
