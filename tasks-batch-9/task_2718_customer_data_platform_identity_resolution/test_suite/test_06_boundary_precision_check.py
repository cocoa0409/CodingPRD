"""Boundary-precision compliance tests.

Two boundaries are pinned here. The first is the inclusive review-floor boundary
of an identity link's four-decimal confidence under the STRICT_ZERO missing
identifier policy. The second is the zero-cardinality boundary of the qualifying
destination set on an erasure propagation, where the erasure completes inside the
propagate call itself.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_CONFIDENCE_BELOW_FLOOR
from test_helpers.assertions import (
    approx4,
    assert_instant_equals,
    assert_tombstoned_identifiers,
)
from test_helpers.test_users import ADMIN, PRIVACY, STEWARD

# The instant the server's logical clock reads before any operator moves it.
BOOT_CLOCK = "2026-08-01T00:00:00Z"


def _four_resolved_profiles(api):
    """Four promoted profiles, each minted from its own fully valid record.

    No match rule exists during the promotion, so every valid record mints its
    own profile and phase three settles all four to RESOLVED.
    """
    fx.reset_clock(api)
    env = fx.promoted_batch(api, [f.raw_record() for _ in range(4)])
    assert len(env["profiles"]) == 4, (
        f"setup expected four minted profiles, got {len(env['profiles'])}"
    )
    return env


def _boundary_rule(api):
    """A probabilistic rule whose review band opens at exactly 0.6500."""
    return fx.declare_probabilistic_rule(
        api,
        code="PROB_BOUND",
        missing_identifier_policy="STRICT_ZERO",
        review_floor=0.65,
        auto_merge_threshold=0.92,
        min_precision=0.40,
    )


def _propose(api, left_id, right_id, rule_id, evidence_values):
    return api.create_identity_link(
        f.identity_link_payload(left_id, right_id, rule_id, evidence_values),
        STEWARD,
    )


# --------------------------------------------------------------------------
# the inclusive review-floor boundary of an identity link's confidence
# --------------------------------------------------------------------------
def test_confidence_exactly_at_review_floor_creates_the_link(api):
    """Evidence of a perfect email and a perfect phone with both other components
    absent scores exactly the rule's review floor under STRICT_ZERO, and the link
    is created because the boundary is inclusive on the passing side.

    "Confidence is then computed from the four evidence values under a fixed weight table: an email component is worth 0.40, a phone 0.25, a name 0.20 and an address 0.15, the four summing to exactly 1.00."
    "The **raw** score is the sum, over only those components whose evidence value is non-null, of that component's weight multiplied by its similarity value."
    "Under `STRICT_ZERO` the confidence **is** the raw score, measured against the full weight base of 1.00; an absent component therefore contributes nothing and permanently caps what a sparse pair can score, no matter how perfect the evidence it does have."
    "In both policies the result is rounded half up to four decimal places before any threshold comparison."
    "The rounded confidence decides the link's fate against the minting rule's own thresholds, and both boundaries are inclusive."
    "At or above `review_floor` but below `auto_merge_threshold`, the link is created as `PROPOSED` and waits for a steward."

    Design: Difficulty/boundary_precision_check/confidence_exactly_at_review_floor_creates_link
    """
    env = _four_resolved_profiles(api)
    rule = _boundary_rule(api)
    left, right = env["profiles"][0], env["profiles"][1]

    response = _propose(
        api,
        left["id"],
        right["id"],
        rule["id"],
        f.evidence(
            email_similarity=1.0,
            phone_similarity=1.0,
            name_similarity=None,
            address_similarity=None,
        ),
    )
    link = validate_success(response, 201)

    assert link["confidence"] == approx4(0.65)
    assert link["status"] == "PROPOSED"
    assert link["match_method"] == "PROBABILISTIC"
    assert link["match_rule_id"] == rule["id"]


def test_link_at_the_review_floor_waits_in_the_review_band(api):
    """A confidence sitting exactly on the review floor is far below the merge
    threshold, so the link stays undecided: no survivor is elected, no operator is
    recorded and neither endpoint is merged away.

    "At or above `review_floor` but below `auto_merge_threshold`, the link is created as `PROPOSED` and waits for a steward."
    "Every link records its `match_method` copied from the minting rule's `rule_kind`, and holds `survivor_profile_id`, `decided_by_user_id`, `decided_at` and `void_reason` null until something decides it."
    "A new rule is `ENABLED` with `confirmed_count` and `rejected_count` at 0 and `precision_estimate` at 1.0."

    Design: Difficulty/boundary_precision_check/confidence_exactly_at_review_floor_creates_link
    """
    env = _four_resolved_profiles(api)
    rule = _boundary_rule(api)
    left, right = env["profiles"][0], env["profiles"][1]

    link = validate_success(
        _propose(
            api,
            left["id"],
            right["id"],
            rule["id"],
            f.evidence(
                email_similarity=1.0,
                phone_similarity=1.0,
                name_similarity=None,
                address_similarity=None,
            ),
        ),
        201,
    )

    assert link["confidence"] == approx4(0.65)
    assert link["status"] == "PROPOSED"
    assert link["survivor_profile_id"] is None
    assert link["decided_by_user_id"] is None
    assert link["decided_at"] is None
    assert link["void_reason"] is None

    for endpoint in (left, right):
        reread = fx.reread_profile(api, endpoint["id"])
        assert reread["resolution_status"] == "RESOLVED"
        assert reread["merged_into_profile_id"] is None

    rule_after = fx.reread_rule(api, rule["id"])
    assert rule_after["confirmed_count"] == 0
    assert rule_after["rejected_count"] == 0
    assert rule_after["status"] == "ENABLED"


def test_confidence_one_notch_below_review_floor_is_refused(api):
    """The same rule refuses evidence worth 0.6000 — a perfect email plus a partial
    phone and a partial address — because that sits strictly below the review floor,
    and nothing at all is persisted by the refused call.

    "Below `review_floor` no link is created and the proposal fails with `ERR_CONFIDENCE_BELOW_FLOOR`."
    "The **raw** score is the sum, over only those components whose evidence value is non-null, of that component's weight multiplied by its similarity value."
    "`review_floor`, defaulting to 0.65, is the minimum confidence at which a candidate link may be created at all."
    "There is exactly one deliberate exception to the rule that an error response leaves state untouched, and it is described in §3.2: the requeue attempt that exhausts a batch's retry budget both fails and advances the batch to `REJECTED`."

    Design: Difficulty/boundary_precision_check/confidence_exactly_at_review_floor_creates_link
    """
    env = _four_resolved_profiles(api)
    rule = _boundary_rule(api)
    left, right = env["profiles"][2], env["profiles"][3]

    response = _propose(
        api,
        left["id"],
        right["id"],
        rule["id"],
        f.evidence(
            email_similarity=1.0,
            phone_similarity=0.5,
            name_similarity=None,
            address_similarity=0.5,
        ),
    )
    validate_error(response, ERR_CONFIDENCE_BELOW_FLOOR)

    links, meta = validate_paginated(
        api.list_identity_links(
            ADMIN, {"left_profile_id": left["id"], "limit": 100, "offset": 0}
        )
    )
    assert meta["total_count"] == 0
    assert links == []

    rule_after = fx.reread_rule(api, rule["id"])
    assert rule_after["confirmed_count"] == 0
    assert rule_after["rejected_count"] == 0
    assert rule_after["status"] == "ENABLED"

    for endpoint in (left, right):
        reread = fx.reread_profile(api, endpoint["id"])
        assert reread["resolution_status"] == "RESOLVED"
        assert reread["privacy_status"] == "NORMAL"


# --------------------------------------------------------------------------
# the zero-cardinality boundary of the qualifying-destination set
# --------------------------------------------------------------------------
def _subject_awaiting_erasure(api):
    """One promoted, emailable subject whose erasure sits in RECEIVED.

    The record carries an EMAIL / MARKETING opt-in, so promotion materialises one
    election for the subject, and no destination exists yet.
    """
    fx.reset_clock(api)
    env = fx.emailable_profile(api)
    elections = fx.rows(
        api.list_consent_records(
            ADMIN, {"profile_id": env["profile"]["id"], "limit": 100, "offset": 0}
        )
    )
    assert len(elections) == 1, (
        f"setup expected one materialised election, got {len(elections)}"
    )
    env["election"] = elections[0]
    env["request"] = fx.record_erasure(api, env["profile"]["id"])
    assert env["request"]["status"] == "RECEIVED"
    return env


def _propagate(api, deletion_request_id):
    """Propagate under the request's live version guard."""
    current = fx.reread_deletion_request(api, deletion_request_id)
    return api.propagate_deletion_request(
        deletion_request_id, f.propagate_payload(current["version"]), PRIVACY
    )


def test_propagate_with_zero_qualifying_destinations_verifies_immediately(api):
    """With no destination registered at all, the fan-out has nothing to reach, so
    the propagate call itself carries the request to VERIFIED without ever minting
    a vendor task.

    "Where **zero** destinations qualify, there is nothing downstream to verify and the erasure completes inside the propagate call itself: `total_vendor_task_count` stays 0, the request moves `RECEIVED` → `VERIFIED`, `verified_at` is stamped, and the subject is tombstoned immediately."
    "The request's five counters are derived from its children at all times: `total_vendor_task_count` is every task minted across all propagate calls, `pending_vendor_task_count` counts those in `PENDING` or `DISPATCHED`, and `acknowledged_vendor_task_count`, `failed_vendor_task_count` and `timed_out_vendor_task_count` count the three remaining statuses one for one."
    "Before any operator sets it, the logical clock reads exactly `2026-08-01T00:00:00Z`; the server must not fall back to real time."

    Design: Difficulty/boundary_precision_check/propagate_with_zero_qualifying_destinations_verifies_immediately
    """
    env = _subject_awaiting_erasure(api)
    request_id = env["request"]["id"]

    updated = validate_success(_propagate(api, request_id), 200)

    assert updated["status"] == "VERIFIED"
    assert updated["total_vendor_task_count"] == 0
    assert updated["pending_vendor_task_count"] == 0
    assert updated["acknowledged_vendor_task_count"] == 0
    assert updated["failed_vendor_task_count"] == 0
    assert updated["timed_out_vendor_task_count"] == 0
    assert_instant_equals(updated["verified_at"], BOOT_CLOCK, "verified_at")

    tasks, meta = validate_paginated(
        api.list_vendor_tasks(
            ADMIN, {"deletion_request_id": request_id, "limit": 100, "offset": 0}
        )
    )
    assert meta["total_count"] == 0
    assert tasks == []


def test_zero_destination_propagation_tombstones_the_subject(api):
    """The same empty-set propagation is what tombstones the subject: the profile
    reaches DELETED, its identifiers are nulled, its channel list is empty and its
    election is tombstoned with a zeroed precedence rank.

    "Reaching `VERIFIED` tombstones the subject, moving it `DELETION_PENDING` → `DELETED`."
    "Seven fields are nulled: `email_norm`, `phone_norm`, `first_name`, `last_name`, `inferred_health_interest`, `inferred_ethnicity_affinity` and `precise_geolocation_grid`."
    "Every consent election of the subject becomes `TOMBSTONED` with `precedence_rank` forced to 0, whatever it held before — active, superseded or expired — and `TOMBSTONED` is terminal for an election."
    "A `privacy_status` other than `NORMAL` opts the subject out of every channel."
    "A channel is activatable for a subject only where its resolution is `OPT_IN`."

    Design: Difficulty/boundary_precision_check/propagate_with_zero_qualifying_destinations_verifies_immediately
    """
    env = _subject_awaiting_erasure(api)
    assert env["election"]["status"] == "ACTIVE"

    updated = validate_success(_propagate(api, env["request"]["id"]), 200)
    assert updated["status"] == "VERIFIED"

    profile = fx.reread_profile(api, env["profile"]["id"])
    assert profile["privacy_status"] == "DELETED"
    assert_tombstoned_identifiers(profile)
    assert profile["activatable_channels"] == []

    election = fx.acted(api.get_consent_record(env["election"]["id"], ADMIN))
    assert election["status"] == "TOMBSTONED"
    assert election["precedence_rank"] == 0


def test_destination_that_never_took_a_delivery_leaves_the_set_empty(api):
    """A registered, active destination whose only activation is still a draft has
    never received a delivery, so it does not qualify and the qualifying set is
    still empty — the erasure verifies inside the propagate call all the same.

    "Where no hold applies, the qualifying destinations are those whose `status` is `ACTIVE` and which have at least one activation whose `status` is not `DRAFT` — a platform that never received a delivery has nothing to erase, and an inactive platform is skipped."
    "Where **zero** destinations qualify, there is nothing downstream to verify and the erasure completes inside the propagate call itself: `total_vendor_task_count` stays 0, the request moves `RECEIVED` → `VERIFIED`, `verified_at` is stamped, and the subject is tombstoned immediately."

    Design: Difficulty/boundary_precision_check/propagate_with_zero_qualifying_destinations_verifies_immediately
    """
    fx.reset_clock(api)
    env = fx.emailable_profile(api)
    segment = fx.approved_segment(api, list(f.POSTAL_10001))
    destination = fx.register_destination(api)
    activation = fx.draft_activation(api, segment["id"], destination["id"])
    assert activation["status"] == "DRAFT"
    assert destination["status"] == "ACTIVE"

    request = fx.record_erasure(api, env["profile"]["id"])
    updated = validate_success(_propagate(api, request["id"]), 200)

    assert updated["status"] == "VERIFIED"
    assert updated["total_vendor_task_count"] == 0
    assert_instant_equals(updated["verified_at"], BOOT_CLOCK, "verified_at")

    tasks, meta = validate_paginated(
        api.list_vendor_tasks(
            ADMIN, {"deletion_request_id": request["id"], "limit": 100, "offset": 0}
        )
    )
    assert meta["total_count"] == 0
    assert tasks == []

    profile = fx.reread_profile(api, env["profile"]["id"])
    assert profile["privacy_status"] == "DELETED"


def test_one_qualifying_destination_propagates_instead_of_verifying(api):
    """One notch above the empty-set boundary: a destination that has taken a
    delivery does qualify, so the very same propagate call mints a dispatched task
    and parks the request in PROPAGATING with the subject still deletion-pending.

    "Where at least one qualifies, the request moves `RECEIVED` → `PROPAGATING`, one **vendor deletion task** is minted per qualifying destination in destination `created_at` ascending order, `propagated_at` is stamped at the logical clock now, the five counters are recomputed and the request's `version` increments."
    "Each task is created `PENDING` and immediately advanced `PENDING` → `DISPATCHED` within the same call, with `dispatched_at` at the logical clock now, `attempt_count` at 1, and `ack_deadline_at` set to `dispatched_at` advanced by that destination's `deletion_ack_sla_hours` hours."
    "Reaching `VERIFIED` tombstones the subject, moving it `DELETION_PENDING` → `DELETED`."

    Design: Difficulty/boundary_precision_check/propagate_with_zero_qualifying_destinations_verifies_immediately
    """
    fx.reset_clock(api)
    env = fx.delivering_activation_environment(api, member_count=2)
    subject = env["profiles"][0]
    request = fx.record_erasure(api, subject["id"])

    updated = validate_success(_propagate(api, request["id"]), 200)

    assert updated["status"] == "PROPAGATING"
    assert updated["total_vendor_task_count"] == 1
    assert updated["pending_vendor_task_count"] == 1
    assert updated["verified_at"] is None
    assert_instant_equals(updated["propagated_at"], BOOT_CLOCK, "propagated_at")

    tasks, meta = validate_paginated(
        api.list_vendor_tasks(
            ADMIN, {"deletion_request_id": request["id"], "limit": 100, "offset": 0}
        )
    )
    assert meta["total_count"] == 1
    assert tasks[0]["destination_id"] == env["destination"]["id"]
    assert tasks[0]["status"] == "DISPATCHED"
    assert tasks[0]["attempt_count"] == 1

    profile = fx.reread_profile(api, subject["id"])
    assert profile["privacy_status"] == "DELETION_PENDING"
