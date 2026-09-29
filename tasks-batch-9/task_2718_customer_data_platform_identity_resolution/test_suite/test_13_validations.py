"""Refusals and inclusive boundaries on the validation ladder.

Each test drives one constraint to its exact edge — a reused feed code, an
audience of precisely the k-anonymity floor, a third window over a cap of two, a
sensitive audience on an uncleared destination, and a transition named on an
activation that does not exist — and then reads the store back to confirm the
refused call left nothing behind.
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
    ERR_ACTIVATION_CONCURRENCY_EXCEEDED,
    ERR_ACTIVATION_NOT_FOUND,
    ERR_DUPLICATE_CODE,
    ERR_EMPTY_AUDIENCE,
    ERR_SENSITIVE_ATTRIBUTE_NOT_PERMITTED,
)
from test_helpers.assertions import assert_version_unchanged
from test_helpers.test_users import ADMIN, ANALYST

EMAIL_OPT_IN_SIGNAL = [
    {"channel": "EMAIL", "purpose": "MARKETING", "consent_state": "OPT_IN"}
]


def test_duplicate_source_system_code_rejected(api):
    """A second feed reusing an existing operator code is refused, and the incumbent
    feed keeps the display name and trust tier it was registered with.

    "A `DataPlatformAdmin` registers one by supplying a `code` — a stable operator-assigned identifier of three to twenty characters drawn only from upper-case letters, digits and underscores, which must be unique across all feeds, a second feed reusing an existing code being refused with `ERR_DUPLICATE_CODE` — together with a `display_name` of one to one hundred and twenty characters after trimming, and a `channel_type` naming which retail stream the feed carries: `TRANSACTIONS`, `LOYALTY`, `WEB`, `APP` or `SUPPORT`."

    "Retail feeds are listed newest first — `created_at` descending — because operators triage recent registrations."

    Design: Corner/validations/duplicate_source_system_code_rejected
    """
    incumbent = validate_success(
        api.create_source_system(
            f.source_system_payload(
                code="VA_DUP",
                display_name="Original Feed",
                channel_type="TRANSACTIONS",
                trust_tier=3,
            ),
            ADMIN,
        ),
        201,
    )
    assert incumbent["code"] == "VA_DUP"

    validate_error(
        api.create_source_system(
            f.source_system_payload(
                code="VA_DUP",
                display_name="Impostor Feed",
                channel_type="LOYALTY",
                trust_tier=1,
            ),
            ADMIN,
        ),
        ERR_DUPLICATE_CODE,
    )

    feeds, meta = validate_paginated(
        api.list_source_systems(ADMIN, {"limit": 100, "offset": 0})
    )
    # The refusal wrote nothing, so exactly one feed carries the code.
    assert meta["total_count"] == 1
    assert len(feeds) == 1

    survivor = fx.reread_feed(api, incumbent["id"])
    assert survivor["code"] == "VA_DUP"
    assert survivor["display_name"] == "Original Feed"
    assert survivor["channel_type"] == "TRANSACTIONS"
    assert survivor["trust_tier"] == 3
    assert_version_unchanged(incumbent, survivor)


def test_activation_at_exactly_min_audience_size_dispatches(api):
    """An audience of exactly two against a destination whose k-anonymity floor is
    exactly two dispatches, the gate being inclusive at equality.

    "Three gates then fire in this fixed order, each inclusive at equality on the passing side."

    "`audience_size` must be at least the destination's `min_audience_size`, a smaller audience being `ERR_AUDIENCE_BELOW_K_ANONYMITY`."

    "`min_audience_size`, an integer of at least 1 defaulting to 50, is the k-anonymity floor."

    "The audience is those candidates whose `activatable_channels` contains the destination's `channel`, and `audience_size` is its size."

    "On success the activation moves `DRAFT` → `DISPATCHED`, `dispatched_at` is stamped at the logical clock now, the destination's `remaining_daily_hash_quota` decreases by `dispatched_hash_count`, the segment's `active_activation_count` increases by 1, and the activation's, the destination's and the segment's `version` each increment by 1."

    Design: Corner/validations/activation_at_exactly_min_audience_size_dispatches
    """
    env = fx.promoted_batch(
        api,
        [
            f.raw_record(
                "KA1",
                email_raw="ka1@example.com",
                postal_code="10001",
                consent_signals=EMAIL_OPT_IN_SIGNAL,
            ),
            f.raw_record(
                "KA2",
                email_raw="ka2@example.com",
                postal_code="10001",
                consent_signals=EMAIL_OPT_IN_SIGNAL,
            ),
        ],
        {
            "code": "VA_KANON",
            "display_name": "K Anonymity Feed",
            "channel_type": "WEB",
            "trust_tier": 3,
        },
    )
    assert len(env["profiles"]) == 2

    destination = fx.register_destination(
        api,
        permissive=False,
        code="VA_KANON_DEST",
        channel="EMAIL",
        hashing_algorithm="SHA256_EMAIL_LOWER",
        daily_hash_quota=300,
        min_audience_size=2,
        min_match_rate=0.10,
    )
    assert destination["min_audience_size"] == 2

    segment = fx.approved_segment(api, f.POSTAL_10001, name="Exactly Two")
    assert segment["member_count"] == 2

    activation = fx.draft_activation(api, segment["id"], destination["id"])
    dispatched = validate_success(
        api.dispatch_activation(activation["id"], ANALYST), 200
    )

    assert dispatched["candidate_count"] == 2
    # Equal to the floor, not above it, and that is enough.
    assert dispatched["audience_size"] == 2
    assert dispatched["suppressed_count"] == 0
    assert dispatched["dispatched_hash_count"] == 2
    assert dispatched["status"] == "DISPATCHED"

    assert fx.reread_destination(api, destination["id"])["remaining_daily_hash_quota"] == 298
    assert fx.reread_segment(api, segment["id"])["active_activation_count"] == 1


def test_third_overlapping_window_exceeds_destination_concurrency_cap(api):
    """Two accepted activations already cover 2026-08-02T01:00:00Z, so a third window
    inside theirs breaches a cap of two and is refused on the concurrency rung rather
    than on the cooldown, which a zero clear time disarms entirely.

    "The **concurrency cap** governs exactly what the cooldown does not: simultaneous coverage. No instant may be covered by more than `max_concurrent_activations` windows among this destination's activations in `DRAFT`, `DISPATCHED`, `ACTIVE`, `UNDERPERFORMING` or `PAUSED` — note that draft and paused activations still hold their slot, and only terminated ones release it. The check sweeps the closed intervals, and a window that touches another only at an endpoint still counts as covering that shared instant. Breaching it is `ERR_ACTIVATION_CONCURRENCY_EXCEEDED`."

    "Activation windows are closed intervals — both endpoints inclusive — so two windows that merely touch at a single instant do intersect and are therefore outside the cooldown's scope entirely."

    "A `cooldown_minutes` of 0 therefore imposes no separation at all."

    "A new activation is `DRAFT` with every audience and match-rate field at its default, and the parent segment's `version` increments by 1."

    Design: Corner/validations/third_overlapping_window_exceeds_destination_concurrency_cap
    """
    env = fx.promoted_batch(
        api,
        [
            f.raw_record(
                "CC1",
                email_raw="cc1@example.com",
                postal_code="10001",
                consent_signals=EMAIL_OPT_IN_SIGNAL,
            )
        ],
        {
            "code": "VA_CONC",
            "display_name": "Concurrency Feed",
            "channel_type": "WEB",
            "trust_tier": 3,
        },
    )
    destination = fx.register_destination(
        api,
        permissive=False,
        code="VA_CONC_DEST",
        channel="EMAIL",
        hashing_algorithm="SHA256_EMAIL_LOWER",
        daily_hash_quota=500,
        min_audience_size=1,
        min_match_rate=0.10,
        cooldown_minutes=0,
        max_concurrent_activations=2,
    )
    assert destination["max_concurrent_activations"] == 2
    assert destination["cooldown_minutes"] == 0

    segment = fx.approved_segment(api, f.POSTAL_10001, name="Concurrency Audience")

    # Two windows covering the same two hours; the cap of two is now exactly full.
    first = fx.draft_activation(
        api,
        segment["id"],
        destination["id"],
        "2026-08-02T00:00:00Z",
        "2026-08-02T02:00:00Z",
    )
    second = fx.draft_activation(
        api,
        segment["id"],
        destination["id"],
        "2026-08-02T00:00:00Z",
        "2026-08-02T02:00:00Z",
    )
    assert first["status"] == "DRAFT"
    assert second["status"] == "DRAFT"

    before = fx.reread_segment(api, segment["id"])
    validate_error(
        api.create_activation(
            f.activation_payload(
                segment["id"],
                destination["id"],
                before["version"],
                "2026-08-02T01:00:00Z",
                "2026-08-02T01:30:00Z",
            ),
            ANALYST,
        ),
        ERR_ACTIVATION_CONCURRENCY_EXCEEDED,
    )

    activations, meta = validate_paginated(
        api.list_activations(
            ADMIN, {"destination_id": destination["id"], "limit": 100, "offset": 0}
        )
    )
    # Only the two accepted drafts exist; the refusal minted nothing.
    assert meta["total_count"] == 2
    assert sorted(a["id"] for a in activations) == sorted([first["id"], second["id"]])

    after = fx.reread_segment(api, segment["id"])
    assert_version_unchanged(before, after)


def test_sensitive_segment_requires_destination_permission_and_governance_flag(api):
    """A sensitive audience cleared by governance is still refused by a destination that
    was never permitted to receive one, and is accepted by an otherwise identical
    destination that was — after which dispatch fails on the empty-audience gate.

    "`uses_sensitive_attributes` is **derived, never supplied**: it is true when any criterion's `attribute` is one of the three sensitive attributes `inferred_health_interest`, `inferred_ethnicity_affinity` or `precise_geolocation_grid`, and a client value for it is not accepted."

    "`sensitive_attribute_permitted`, defaulting to false, states whether audiences built on sensitive attributes may be sent here at all."

    "Creation also refuses an inactive destination, and refuses a sensitive audience that either the segment or the destination has not cleared, with `ERR_SENSITIVE_ATTRIBUTE_NOT_PERMITTED`."

    "Where `uses_sensitive_attributes` is true, an approval whose body `sensitive_use_approved` is not true is refused with `ERR_GOVERNANCE_JUSTIFICATION_REQUIRED` — sensitive use must be affirmed explicitly, not inherited from a general approval."

    "A new activation is `DRAFT` with every audience and match-rate field at its default, and the parent segment's `version` increments by 1."

    "A null attribute **never** satisfies any operator: absence is not a match, and a segment on an inferred attribute silently excludes every profile for which that attribute was never inferred."

    "`audience_size` must be at least 1, an audience emptied by consent or suppression being refused with `ERR_EMPTY_AUDIENCE`."

    Design: Corner/validations/sensitive_segment_requires_destination_permission_and_governance_flag
    """
    fx.promoted_batch(
        api,
        [
            f.raw_record(
                "SS1",
                email_raw="ss1@example.com",
                postal_code="10001",
                consent_signals=EMAIL_OPT_IN_SIGNAL,
            )
        ],
        {
            "code": "VA_SENS",
            "display_name": "Sensitive Feed",
            "channel_type": "WEB",
            "trust_tier": 3,
        },
    )

    forbidden = fx.register_destination(
        api,
        permissive=False,
        code="VA_SENS_NO",
        channel="EMAIL",
        hashing_algorithm="SHA256_EMAIL_LOWER",
        daily_hash_quota=300,
        min_audience_size=1,
        min_match_rate=0.10,
        sensitive_attribute_permitted=False,
    )
    permitted = fx.register_destination(
        api,
        permissive=False,
        code="VA_SENS_YES",
        channel="EMAIL",
        hashing_algorithm="SHA256_EMAIL_LOWER",
        daily_hash_quota=300,
        min_audience_size=1,
        min_match_rate=0.10,
        sensitive_attribute_permitted=True,
    )
    assert forbidden["sensitive_attribute_permitted"] is False
    assert permitted["sensitive_attribute_permitted"] is True

    segment = fx.approved_sensitive_segment(
        api,
        [f.criterion("inferred_health_interest", "EQ", "FITNESS")],
        name="Fitness Interest",
    )
    assert segment["uses_sensitive_attributes"] is True
    assert segment["sensitive_use_approved"] is True
    assert segment["status"] == "APPROVED"

    before = fx.reread_segment(api, segment["id"])
    validate_error(
        api.create_activation(
            f.activation_payload(
                segment["id"],
                forbidden["id"],
                before["version"],
                "2026-08-02T00:00:00Z",
                "2026-08-02T02:00:00Z",
            ),
            ANALYST,
        ),
        ERR_SENSITIVE_ATTRIBUTE_NOT_PERMITTED,
    )
    # The refused create left the guard token spendable, so the same version stands.
    after_refusal = fx.reread_segment(api, segment["id"])
    assert_version_unchanged(before, after_refusal)

    accepted = validate_success(
        api.create_activation(
            f.activation_payload(
                segment["id"],
                permitted["id"],
                after_refusal["version"],
                "2026-08-02T00:00:00Z",
                "2026-08-02T02:00:00Z",
            ),
            ANALYST,
        ),
        201,
    )
    assert accepted["status"] == "DRAFT"
    assert accepted["destination_id"] == permitted["id"]

    # No profile ever had a health interest inferred, so the audience is empty.
    validate_error(
        api.dispatch_activation(accepted["id"], ANALYST), ERR_EMPTY_AUDIENCE
    )


def test_existence_check_precedes_state_check_on_unknown_activation_not_found(api):
    """Pausing an activation that does not exist answers the existence rung, never the
    state rung, because the ladder resolves existence long before any lifecycle check.

    "Validation is a strict, absolute priority ladder. All checks that could apply to a request are evaluated in ascending priority number, and the **first** violated rule alone determines the response; later violations are never reported and never merged into a multi-error body. The ladder is global — it does not vary by endpoint — so a request that violates rules 4 and 26 simultaneously always answers rule 4's error. The rungs are as follows."

    "Rungs 5 through 17 are existence, in this fixed order: (5) the retail feed named by `{sourceSystemId}` or by a `source_system_id` body field exists, else `ERR_SOURCE_SYSTEM_NOT_FOUND`; (6) the batch named by `{batchId}` exists, else `ERR_INGEST_BATCH_NOT_FOUND`; (7) every profile named by `{profileId}`, `profile_id`, `left_profile_id` or `right_profile_id` exists, else `ERR_PROFILE_NOT_FOUND`; (8) the household named by `{householdId}` or by the `household_id` body field exists, else `ERR_HOUSEHOLD_NOT_FOUND`; (9) the rule named by `{matchRuleId}` or `match_rule_id` exists, else `ERR_MATCH_RULE_NOT_FOUND`; (10) the link named by `{linkId}` exists, else `ERR_IDENTITY_LINK_NOT_FOUND`; (11) the consent record named by `{consentRecordId}` exists, else `ERR_CONSENT_RECORD_NOT_FOUND`; (12) the suppression entry named by `{suppressionId}` exists, else `ERR_SUPPRESSION_ENTRY_NOT_FOUND`; (13) the segment named by `{segmentId}`, `segment_id` or the `other_segment_id` query parameter exists, else `ERR_SEGMENT_NOT_FOUND`; (14) the destination named by `{destinationId}` or `destination_id` exists, else `ERR_DESTINATION_NOT_FOUND`; (15) the activation named by `{activationId}` exists, else `ERR_ACTIVATION_NOT_FOUND`; (16) the erasure request named by `{deletionRequestId}` exists, else `ERR_DELETION_REQUEST_NOT_FOUND`; (17) the vendor task named by `{taskId}` exists, else `ERR_VENDOR_TASK_NOT_FOUND`."

    "Rungs 21 through 26 are state and referential integrity: (21) the target's current status permits the requested transition per its lifecycle, else `ERR_INVALID_STATE`; (22) no profile named as a link endpoint, consent subject, suppression subject or erasure subject has `resolution_status` of `MERGED_AWAY`, else `ERR_PROFILE_MERGED_AWAY`; (23) the referenced feed's `status` is not `QUARANTINED` when submitting a batch, validating one, promoting one, or capturing a consent record that names it, else `ERR_SOURCE_SYSTEM_QUARANTINED`; (24) a rule named on link creation has `status` of `ENABLED`, else `ERR_MATCH_RULE_DISABLED`; (25) the destination's `status` is `ACTIVE` when creating, dispatching or resuming an activation against it, else `ERR_DESTINATION_INACTIVE`; (26) no profile referenced by the write has `privacy_status` of `DELETED`, else `ERR_PROFILE_DELETED`."

    "An analyst may pause an activation that is `DISPATCHED`, `ACTIVE` or `UNDERPERFORMING` — a dispatched activation that has not yet received a single report is pausable — and the same three arms are driven by the consent and governance cascades described elsewhere."

    Design: Corner/validations/existence_check_precedes_state_check_on_unknown_activation_not_found
    """
    validate_error(
        api.pause_activation(NON_EXISTENT_UUID, ANALYST), ERR_ACTIVATION_NOT_FOUND
    )

    _, meta = validate_paginated(api.list_activations(ADMIN, {"limit": 100, "offset": 0}))
    assert meta["total_count"] == 0
