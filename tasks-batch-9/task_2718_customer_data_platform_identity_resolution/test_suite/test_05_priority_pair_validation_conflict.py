"""Dispatch calls that violate two ladder rungs at once.

Validation is one absolute ladder shared by every endpoint, so when a single
dispatch breaks two rules the lower rung number alone is reported. Two disjoint
pairs are exercised on the same endpoint: a role that is not listed for dispatch
re-firing an already-dispatched activation, where the authorization rung outranks
the state rung; and an audience that is at once too small for the destination's
k-anonymity floor and too expensive for its remaining quota, where the privacy
rung outranks the fiscal one. Each pair is followed by an arm proving the
outranked rule really was violated.
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
from test_helpers.api_errors import (
    ERR_AUDIENCE_BELOW_K_ANONYMITY,
    ERR_HASH_QUOTA_EXCEEDED,
    ERR_INVALID_STATE,
    ERR_UNAUTHORIZED,
)
from test_helpers.assertions import (
    assert_instant_equals,
    assert_unchanged,
    assert_version_unchanged,
)
from test_helpers.test_users import ANALYST, PRIVACY

BOOT_INSTANT = "2026-08-01T00:00:00Z"

# A destination roomy enough that the only thing standing in the way of a second
# dispatch is the activation's own status.
ROOMY_DESTINATION = dict(
    platform_kind="MESSAGING",
    channel="EMAIL",
    hashing_algorithm="SHA256_EMAIL_LOWER",
    daily_hash_quota=100,
    min_audience_size=1,
    min_match_rate=0.50,
)


def _dispatched_activation(api):
    """One emailable profile delivered once, leaving 99 of 100 hashes unspent.

    The activation is already DISPATCHED, so DRAFT -> DISPATCHED is no longer
    available on it and any further dispatch attempt violates the state rung.
    """
    env = fx.delivering_activation_environment(
        api, 1, destination_overrides=dict(ROOMY_DESTINATION)
    )
    assert env["activation"]["status"] == "DISPATCHED"
    assert env["activation"]["audience_size"] == 1
    assert env["activation"]["dispatched_hash_count"] == 1
    assert env["destination"]["remaining_daily_hash_quota"] == 99
    assert env["segment"]["active_activation_count"] == 1
    return env


def test_a_role_not_listed_for_dispatch_is_refused_before_the_state_of_the_target_is_judged(api):
    """A PrivacyOfficer re-firing an already-dispatched activation breaks both the
    authorization rung and the state rung, and only the authorization rung is
    reported.

    "Validation is a strict, absolute priority ladder. All checks that could apply to a request are evaluated in ascending priority number, and the **first** violated rule alone determines the response; later violations are never reported and never merged into a multi-error body."

    "If `X-User-Role` is not one of those seven strings, or is one of them but is not listed among the authorized roles for the endpoint being called (see the §4 table), the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    "Rungs 1 through 3 are authentication and actor identity: (1) both auth headers present and non-blank, else `ERR_MISSING_AUTH_HEADERS`; (2) `X-User-Role` is one of the seven declared roles *and* is listed for this endpoint, else `ERR_UNAUTHORIZED`; (3) on match reporting and on vendor-task acknowledgement, `X-User-ID` equals the target activation's or task's `destination_id`, else `ERR_DESTINATION_ACTOR_MISMATCH`."

    Design: Difficulty/priority_pair_validation_conflict/dispatch_conflict_unauthorized_outranks_invalid_state
    """
    env = _dispatched_activation(api)

    response = api.dispatch_activation(env["activation"]["id"], PRIVACY)
    validate_error(response, ERR_UNAUTHORIZED, 403)


def test_the_unauthorized_redispatch_leaves_the_activation_the_quota_and_the_segment_alone(api):
    """The refused call is inert: the activation keeps the counts its one real
    dispatch produced, the destination keeps its 99 remaining hashes and the
    segment keeps its single active activation.

    "This is the sole error-with-side-effect in the system and the only path by which that error code is reachable."

    "On success the activation moves `DRAFT` → `DISPATCHED`, `dispatched_at` is stamped at the logical clock now, the destination's `remaining_daily_hash_quota` decreases by `dispatched_hash_count`, the segment's `active_activation_count` increases by 1, and the activation's, the destination's and the segment's `version` each increment by 1."

    Design: Difficulty/priority_pair_validation_conflict/dispatch_conflict_unauthorized_outranks_invalid_state
    """
    env = _dispatched_activation(api)
    before_activation = env["activation"]
    before_destination = env["destination"]
    before_segment = env["segment"]

    response = api.dispatch_activation(before_activation["id"], PRIVACY)
    validate_error(response, ERR_UNAUTHORIZED, 403)

    after_activation = fx.reread_activation(api, before_activation["id"])
    assert after_activation["status"] == "DISPATCHED"
    assert after_activation["dispatched_hash_count"] == 1
    assert after_activation["audience_size"] == 1
    assert after_activation["candidate_count"] == 1
    assert_instant_equals(after_activation["dispatched_at"], BOOT_INSTANT, "dispatched_at")
    assert_version_unchanged(before_activation, after_activation)

    after_destination = fx.reread_destination(api, before_destination["id"])
    assert after_destination["remaining_daily_hash_quota"] == 99
    assert_version_unchanged(before_destination, after_destination)

    after_segment = fx.reread_segment(api, before_segment["id"])
    assert after_segment["active_activation_count"] == 1
    assert_version_unchanged(before_segment, after_segment)


def test_the_same_second_dispatch_by_the_listed_role_is_refused_on_state_instead(api):
    """The outranked rule really was broken: the identical call made by the role
    the endpoint does list gets past the authorization rung and is refused on the
    activation's status.

    "The platform never treats a repeated trigger as a silent no-op. Firing the same transition twice — validating an already-validated batch, dispatching an already-dispatched activation, releasing an already-released suppression, acknowledging an already-acknowledged vendor task — is rejected with `ERR_INVALID_STATE` (HTTP 409) on the second attempt, because the entity's status no longer permits the transition."

    "Rungs 21 through 26 are state and referential integrity: (21) the target's current status permits the requested transition per its lifecycle, else `ERR_INVALID_STATE`; (22) no profile named as a link endpoint, consent subject, suppression subject or erasure subject has `resolution_status` of `MERGED_AWAY`, else `ERR_PROFILE_MERGED_AWAY`; (23) the referenced feed's `status` is not `QUARANTINED` when submitting a batch, validating one, promoting one, or capturing a consent record that names it, else `ERR_SOURCE_SYSTEM_QUARANTINED`; (24) a rule named on link creation has `status` of `ENABLED`, else `ERR_MATCH_RULE_DISABLED`; (25) the destination's `status` is `ACTIVE` when creating, dispatching or resuming an activation against it, else `ERR_DESTINATION_INACTIVE`; (26) no profile referenced by the write has `privacy_status` of `DELETED`, else `ERR_PROFILE_DELETED`."

    Design: Difficulty/priority_pair_validation_conflict/dispatch_conflict_unauthorized_outranks_invalid_state
    """
    env = _dispatched_activation(api)

    response = api.dispatch_activation(env["activation"]["id"], ANALYST)
    validate_error(response, ERR_INVALID_STATE, 409)

    after = fx.reread_activation(api, env["activation"]["id"])
    assert after["status"] == "DISPATCHED"
    assert after["dispatched_hash_count"] == 1
    assert_version_unchanged(env["activation"], after)


# A destination whose k-anonymity floor of 5 and whose single day's hash both sit
# below a three-member audience, so one dispatch breaks the privacy gate and the
# fiscal gate at the same time.
TIGHT_DESTINATION = dict(
    platform_kind="MESSAGING",
    channel="EMAIL",
    hashing_algorithm="SHA256_EMAIL_LOWER",
    daily_hash_quota=1,
    min_audience_size=5,
    min_match_rate=0.50,
)


def _tight_environment(api, **destination_overrides):
    """Three emailable profiles, an approved postal segment and a DRAFT activation.

    Every member carries an EMAIL marketing opt-in and an email_norm, so the
    audience is all three candidates and all three produce a hash: audience_size
    is 3 and dispatched_hash_count is 3, whatever the destination's limits are.
    """
    overrides = dict(TIGHT_DESTINATION)
    overrides.update(destination_overrides)
    env = fx.activation_ready_environment(
        api,
        3,
        destination_overrides=overrides,
        segment_criteria=list(f.POSTAL_10001),
    )
    assert env["segment"]["member_count"] == 3, (
        f"setup expected a three-member segment, got {env['segment']['member_count']}"
    )
    assert env["activation"]["status"] == "DRAFT"
    assert env["destination"]["remaining_daily_hash_quota"] == overrides["daily_hash_quota"]
    return env


def test_an_audience_both_too_small_and_too_expensive_reports_the_privacy_failure(api):
    """One dispatch of three members to a destination whose floor is 5 and whose
    remaining quota is 1 breaks both gates, and the k-anonymity gate answers
    because it fires first.

    "`audience_size` must be at least the destination's `min_audience_size`, a smaller audience being `ERR_AUDIENCE_BELOW_K_ANONYMITY`."

    "Because the k-anonymity gate precedes the quota gate, an audience that is both too small and too expensive reports the privacy failure rather than the commercial one."

    "First, the k-anonymity floor at rung 33 is checked *before* the quota check at rung 48, so an audience that is both too small and too expensive reports the privacy failure."

    Design: Difficulty/priority_pair_validation_conflict/dispatch_conflict_k_anonymity_outranks_hash_quota
    """
    env = _tight_environment(api)

    response = api.dispatch_activation(env["activation"]["id"], ANALYST)
    validate_error(response, ERR_AUDIENCE_BELOW_K_ANONYMITY, 422)


def test_the_refused_dispatch_consumes_no_quota_and_activates_nothing(api):
    """Nothing moves on the refusal: the activation is still a draft with all four
    resolution counts at zero, the destination's single hash is still unspent and
    the segment has no active activation.

    "This is the sole error-with-side-effect in the system and the only path by which that error code is reachable."

    "And `dispatched_hash_count` must be at most `remaining_daily_hash_quota`, an over-budget dispatch being `ERR_HASH_QUOTA_EXCEEDED`."

    "On success the activation moves `DRAFT` → `DISPATCHED`, `dispatched_at` is stamped at the logical clock now, the destination's `remaining_daily_hash_quota` decreases by `dispatched_hash_count`, the segment's `active_activation_count` increases by 1, and the activation's, the destination's and the segment's `version` each increment by 1."

    Design: Difficulty/priority_pair_validation_conflict/dispatch_conflict_k_anonymity_outranks_hash_quota
    """
    env = _tight_environment(api)
    before_activation = env["activation"]
    before_destination = env["destination"]
    before_segment = fx.reread_segment(api, env["segment"]["id"])

    response = api.dispatch_activation(before_activation["id"], ANALYST)
    validate_error(response, ERR_AUDIENCE_BELOW_K_ANONYMITY, 422)

    after_activation = fx.reread_activation(api, before_activation["id"])
    assert after_activation["status"] == "DRAFT"
    assert after_activation["dispatched_hash_count"] == 0
    assert after_activation["dispatched_at"] is None
    assert_unchanged(
        before_activation,
        after_activation,
        "candidate_count",
        "audience_size",
        "suppressed_count",
    )
    assert_version_unchanged(before_activation, after_activation)

    after_destination = fx.reread_destination(api, before_destination["id"])
    assert after_destination["remaining_daily_hash_quota"] == 1
    assert_version_unchanged(before_destination, after_destination)

    after_segment = fx.reread_segment(api, before_segment["id"])
    assert after_segment["member_count"] == 3
    assert after_segment["active_activation_count"] == 0
    assert_version_unchanged(before_segment, after_segment)


def test_the_quota_gate_answers_once_the_k_anonymity_floor_is_out_of_the_way(api):
    """The outranked rule really was broken: the same three-member, three-hash
    dispatch against a destination whose floor is 1 clears the privacy gate and is
    then refused by the quota gate.

    "And `dispatched_hash_count` must be at most `remaining_daily_hash_quota`, an over-budget dispatch being `ERR_HASH_QUOTA_EXCEEDED`."

    "`dispatched_hash_count` is the number of audience members whose required identifier, selected by the destination's `hashing_algorithm`, is non-null."

    "Three gates then fire in this fixed order, each inclusive at equality on the passing side."

    Design: Difficulty/priority_pair_validation_conflict/dispatch_conflict_k_anonymity_outranks_hash_quota
    """
    env = _tight_environment(api, min_audience_size=1)

    response = api.dispatch_activation(env["activation"]["id"], ANALYST)
    validate_error(response, ERR_HASH_QUOTA_EXCEEDED, 409)

    after_activation = fx.reread_activation(api, env["activation"]["id"])
    assert after_activation["status"] == "DRAFT"
    assert after_activation["dispatched_hash_count"] == 0
    assert after_activation["dispatched_at"] is None

    after_destination = fx.reread_destination(api, env["destination"]["id"])
    assert after_destination["remaining_daily_hash_quota"] == 1
