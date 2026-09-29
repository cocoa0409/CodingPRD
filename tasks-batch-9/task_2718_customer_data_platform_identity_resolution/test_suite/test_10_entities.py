"""Entity-level compliance tests for the Customer Data Platform API.

Every test below drives a live server through the endpoints the PRD declares and
asserts a rule quoted from the PRD in the test's own docstring. Nothing is
mocked, and every precondition is built from an empty store because the harness
restarts the server before each test with the logical clock at its boot instant.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_INVALID_REQUEST,
    ERR_PROFILE_NOT_FOUND,
    ERR_SOURCE_SYSTEM_NOT_FOUND,
)
from test_helpers.assertions import (
    approx2,
    approx4,
    assert_activatable,
    assert_common_fields,
    assert_created_at_ascending,
    assert_envelope_meta,
    assert_instant_equals,
    assert_new_segment,
    assert_new_source_system,
    assert_profile_axes,
)
from test_helpers.test_users import (
    ADMIN,
    ANALYST,
    ENGINEER,
    PRIVACY,
    STEWARD,
)

CLOCK = "2026-08-01T00:00:00Z"


def test_create_source_system_returns_201_with_envelope_and_defaults(api):
    """Registering a retail feed with only its three required inputs answers 201
    inside the standard object envelope and seeds every system-owned field.

    "A newly registered feed is `REGISTERED`, not `ACTIVE`."
    "Its `dq_window_start_at` is stamped at the logical clock now, opening a rolling data-quality window; `submitted_record_total` and `valid_record_total` start at 0, `dq_pass_rate` starts at 1.0, and `quarantine_count` starts at 0 with `last_reinstated_at` null."
    "`version` (integer): starts at 1 and increments by exactly 1 on every mutation of that resource."
    "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."

    Design: Corner/entities/create_source_system_returns_201_with_envelope_and_defaults
    """
    fx.set_clock(api, CLOCK)

    response = api.create_source_system(
        {
            "code": "POS_MAIN",
            "display_name": "Point of Sale Main",
            "channel_type": "TRANSACTIONS",
        },
        ADMIN,
    )
    feed = validate_success(response, 201)
    body = response.json()

    assert body["response_type"] == "object"
    assert_envelope_meta(body)

    assert feed["code"] == "POS_MAIN"
    assert feed["display_name"] == "Point of Sale Main"
    assert feed["channel_type"] == "TRANSACTIONS"
    assert_new_source_system(feed, CLOCK)
    assert_common_fields(feed, expected_version=1)
    assert_instant_equals(feed["created_at"], CLOCK, "created_at")
    assert_instant_equals(feed["updated_at"], CLOCK, "updated_at")


def test_get_destination_returns_stored_configuration(api):
    """Reading a destination back echoes exactly the commercial envelope that was
    registered, together with the two figures registration derived from it.

    "On registration `remaining_daily_hash_quota` is set equal to `daily_hash_quota`, `quota_reset_on` is set to the UTC calendar date of the logical clock now in year-month-day form, and `underperforming_activation_count` starts at 0."
    "Destinations are readable individually — exposing the live `remaining_daily_hash_quota` and `underperforming_activation_count` — and as a list ordered by `created_at` ascending, which is the same order erasure fan-out visits them in, filterable by `platform_kind`, `channel` and `status`."
    "A destination's `status` is `ACTIVE` or `INACTIVE`, defaulting to active; an inactive destination refuses activation creation, dispatch and resume with `ERR_DESTINATION_INACTIVE` and is skipped entirely by erasure fan-out."

    Design: Corner/entities/get_destination_returns_stored_configuration
    """
    fx.set_clock(api, CLOCK)
    created = validate_success(
        api.create_destination(
            {
                "code": "ADNET_READ",
                "platform_kind": "ADVERTISING",
                "channel": "EMAIL",
                "hashing_algorithm": "SHA256_EMAIL_LOWER",
                "daily_hash_quota": 750,
                "match_rate_basis": "NET",
                "min_match_rate": 0.6500,
                "min_audience_size": 5,
                "cooldown_minutes": 30,
                "max_concurrent_activations": 3,
                "sensitive_attribute_permitted": True,
                "deletion_ack_sla_hours": 48,
            },
            ADMIN,
        ),
        201,
    )

    destination = validate_success(api.get_destination(created["id"], ANALYST), 200)

    assert destination["match_rate_basis"] == "NET"
    assert destination["min_match_rate"] == approx4(0.6500)
    assert destination["min_audience_size"] == 5
    assert destination["cooldown_minutes"] == 30
    assert destination["max_concurrent_activations"] == 3
    assert destination["deletion_ack_sla_hours"] == 48
    assert destination["sensitive_attribute_permitted"] is True
    assert destination["status"] == "ACTIVE"
    assert destination["daily_hash_quota"] == 750
    assert destination["remaining_daily_hash_quota"] == 750
    assert destination["quota_reset_on"] == "2026-08-01"
    assert destination["underperforming_activation_count"] == 0


def test_list_profiles_pagination_reports_total_count_and_has_more(api):
    """Paging the profile collection two at a time over a three-profile promotion
    reports the unpaged total on both pages and flips has_more on the last one.

    "Every list endpoint accepts two optional query parameters. `limit` controls page size: it defaults to `10`, its minimum accepted value is `1`, and its maximum accepted value is `100`."
    "`total_count` is the number of records matching the filters before pagination is applied, and `has_more` is true when records remain beyond the current page."
    "Unless a specific collection states otherwise below, list results are ordered by `created_at` ascending."

    Design: Corner/entities/list_profiles_pagination_reports_total_count_and_has_more
    """
    fx.set_clock(api, CLOCK)
    env = fx.promoted_batch(
        api,
        [
            f.raw_record(
                "PG1",
                first_name="Ada",
                last_name="Alpha",
                postal_code="10001",
                event_timestamp="2026-07-20T10:00:00Z",
            ),
            f.raw_record(
                "PG2",
                first_name="Ben",
                last_name="Bravo",
                postal_code="10002",
                event_timestamp="2026-07-20T11:00:00Z",
            ),
            f.raw_record(
                "PG3",
                first_name="Cleo",
                last_name="Charlie",
                postal_code="10003",
                event_timestamp="2026-07-20T12:00:00Z",
            ),
        ],
    )
    batch_id = env["batch"]["id"]

    first_response = api.list_profiles(
        STEWARD, {"origin_batch_id": batch_id, "limit": 2, "offset": 0}
    )
    first_page, first_meta = validate_paginated(first_response)
    assert first_response.json()["response_type"] == "array"
    assert len(first_page) == 2
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0

    second_page, second_meta = validate_paginated(
        api.list_profiles(STEWARD, {"origin_batch_id": batch_id, "limit": 2, "offset": 2})
    )
    assert len(second_page) == 1
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False
    assert second_meta["offset"] == 2

    assert first_page[0]["id"] != second_page[0]["id"]
    combined = first_page + second_page
    assert len({row["id"] for row in combined}) == 3
    assert_created_at_ascending(combined)


def test_get_profile_with_unknown_id_not_found(api):
    """Reading a profile that was never minted answers the profile existence error
    rather than an empty object, even against a completely empty store.

    "Rungs 5 through 17 are existence, in this fixed order: (5) the retail feed named by `{sourceSystemId}` or by a `source_system_id` body field exists, else `ERR_SOURCE_SYSTEM_NOT_FOUND`; (6) the batch named by `{batchId}` exists, else `ERR_INGEST_BATCH_NOT_FOUND`; (7) every profile named by `{profileId}`, `profile_id`, `left_profile_id` or `right_profile_id` exists, else `ERR_PROFILE_NOT_FOUND`; (8) the household named by `{householdId}` or by the `household_id` body field exists, else `ERR_HOUSEHOLD_NOT_FOUND`; (9) the rule named by `{matchRuleId}` or `match_rule_id` exists, else `ERR_MATCH_RULE_NOT_FOUND`; (10) the link named by `{linkId}` exists, else `ERR_IDENTITY_LINK_NOT_FOUND`; (11) the consent record named by `{consentRecordId}` exists, else `ERR_CONSENT_RECORD_NOT_FOUND`; (12) the suppression entry named by `{suppressionId}` exists, else `ERR_SUPPRESSION_ENTRY_NOT_FOUND`; (13) the segment named by `{segmentId}`, `segment_id` or the `other_segment_id` query parameter exists, else `ERR_SEGMENT_NOT_FOUND`; (14) the destination named by `{destinationId}` or `destination_id` exists, else `ERR_DESTINATION_NOT_FOUND`; (15) the activation named by `{activationId}` exists, else `ERR_ACTIVATION_NOT_FOUND`; (16) the erasure request named by `{deletionRequestId}` exists, else `ERR_DELETION_REQUEST_NOT_FOUND`; (17) the vendor task named by `{taskId}` exists, else `ERR_VENDOR_TASK_NOT_FOUND`."

    Design: Corner/entities/get_profile_with_unknown_id_not_found
    """
    validate_error(api.get_profile(NON_EXISTENT_UUID, STEWARD), ERR_PROFILE_NOT_FOUND)

    rows, meta = validate_paginated(api.list_profiles(STEWARD, {"limit": 10, "offset": 0}))
    assert rows == []
    assert meta["total_count"] == 0


def test_create_destination_without_hashing_algorithm_rejected(api):
    """A destination registration that omits the hashing algorithm is malformed, so
    it is refused at the request-shape rung and no destination is stored.

    "Rung 4 is request shape, applied to every endpoint: every required input field present and non-null, every field of its declared type, every enum value drawn from its declared set, every number inside its declared range and decimal width, every string matching its declared pattern and length bounds, every array inside its declared cardinality bounds, and every query parameter well-formed — `limit` in the inclusive range 1 through 100, `offset` at least 0, and `attribution_basis` either `TOTAL` or `INCREMENTAL`. Any violation is `ERR_INVALID_REQUEST`."
    "Its `hashing_algorithm` fixes the identifier contract: `SHA256_EMAIL_LOWER` requires a profile's `email_norm`, while `SHA256_PHONE_E164` requires its `phone_norm`."

    Design: Corner/entities/create_destination_without_hashing_algorithm_rejected
    """
    validate_error(
        api.create_destination(f.destination_payload(hashing_algorithm=f.OMIT), ADMIN),
        ERR_INVALID_REQUEST,
    )

    validate_error(
        api.create_destination(f.destination_payload(hashing_algorithm=None), ADMIN),
        ERR_INVALID_REQUEST,
    )

    validate_error(
        api.create_destination(
            f.destination_payload(hashing_algorithm="SHA256_LOYALTY"), ADMIN
        ),
        ERR_INVALID_REQUEST,
    )

    rows, meta = validate_paginated(api.list_destinations(ADMIN, {"limit": 10, "offset": 0}))
    assert rows == []
    assert meta["total_count"] == 0


def test_destination_optional_config_defaults_applied(api):
    """Registering a destination with only its five required inputs applies all
    seven documented defaults of the commercial and safety envelope.

    "`match_rate_basis` chooses which match-rate variant drives the performance state machine, either `GROSS` (the default) or `NET`."
    "`min_match_rate`, defaulting to 0.70 at no more than four decimals, is the rate at or above which a reported activation is considered healthy."
    "`min_audience_size`, an integer of at least 1 defaulting to 50, is the k-anonymity floor."
    "`cooldown_minutes`, an integer of at least 0 defaulting to 60 — one hour — is the clear time that must separate two **disjoint** delivery windows on this destination."
    "`max_concurrent_activations`, an integer of at least 1 defaulting to 2, caps how many windows may cover any single instant."
    "`sensitive_attribute_permitted`, defaulting to false, states whether audiences built on sensitive attributes may be sent here at all."
    "And `deletion_ack_sla_hours`, an integer of at least 1 defaulting to 72 — three days — is how long the platform has to acknowledge an erasure task."

    Design: Corner/entities/destination_optional_config_defaults_applied
    """
    fx.set_clock(api, CLOCK)

    destination = validate_success(
        api.create_destination(
            {
                "code": "DEST_MIN",
                "platform_kind": "MESSAGING",
                "channel": "SMS",
                "hashing_algorithm": "SHA256_PHONE_E164",
                "daily_hash_quota": 400,
            },
            ADMIN,
        ),
        201,
    )

    assert destination["match_rate_basis"] == "GROSS"
    assert destination["min_match_rate"] == approx4(0.70)
    assert destination["min_audience_size"] == 50
    assert destination["cooldown_minutes"] == 60
    assert destination["max_concurrent_activations"] == 2
    assert destination["sensitive_attribute_permitted"] is False
    assert destination["deletion_ack_sla_hours"] == 72
    assert destination["status"] == "ACTIVE"
    assert destination["daily_hash_quota"] == 400
    assert destination["remaining_daily_hash_quota"] == 400
    assert destination["quota_reset_on"] == "2026-08-01"
    assert destination["underperforming_activation_count"] == 0
    assert_common_fields(destination, expected_version=1)


def test_segment_uses_sensitive_attributes_is_computed_from_criteria(api):
    """Two segments authored over an empty population differ only in their criteria,
    and the sensitivity flag follows the attributes each one names.

    "`uses_sensitive_attributes` is **derived, never supplied**: it is true when any criterion's `attribute` is one of the three sensitive attributes `inferred_health_interest`, `inferred_ethnicity_affinity` or `precise_geolocation_grid`, and a client value for it is not accepted."
    "A new segment is `DRAFT` with `sensitive_use_approved` false, `rejection_count` at 0, and its `member_count` computed immediately."

    Design: Corner/entities/segment_uses_sensitive_attributes_is_computed_from_criteria
    """
    ordinary = validate_success(
        api.create_segment(
            {
                "name": "Postal Ten Thousand One",
                "criteria": [f.criterion("postal_code", "EQ", "10001")],
            },
            ANALYST,
        ),
        201,
    )
    assert ordinary["uses_sensitive_attributes"] is False
    assert ordinary["member_count"] == 0
    assert_new_segment(ordinary)

    sensitive = validate_success(
        api.create_segment(
            {
                "name": "Fitness Interest Audience",
                "criteria": [
                    f.criterion("postal_code", "EQ", "10001"),
                    f.criterion("inferred_health_interest", "EQ", "FITNESS"),
                ],
            },
            ANALYST,
        ),
        201,
    )
    assert sensitive["uses_sensitive_attributes"] is True
    assert sensitive["member_count"] == 0
    assert_new_segment(sensitive)


def test_create_source_system_with_invalid_channel_type_enum_rejected(api):
    """A feed registration whose channel_type is outside the declared set of five
    retail streams is malformed, including a merely lower-cased spelling.

    "Rung 4 is request shape, applied to every endpoint: every required input field present and non-null, every field of its declared type, every enum value drawn from its declared set, every number inside its declared range and decimal width, every string matching its declared pattern and length bounds, every array inside its declared cardinality bounds, and every query parameter well-formed — `limit` in the inclusive range 1 through 100, `offset` at least 0, and `attribution_basis` either `TOTAL` or `INCREMENTAL`. Any violation is `ERR_INVALID_REQUEST`."
    "A `DataPlatformAdmin` registers one by supplying a `code` — a stable operator-assigned identifier of three to twenty characters drawn only from upper-case letters, digits and underscores, which must be unique across all feeds, a second feed reusing an existing code being refused with `ERR_DUPLICATE_CODE` — together with a `display_name` of one to one hundred and twenty characters after trimming, and a `channel_type` naming which retail stream the feed carries: `TRANSACTIONS`, `LOYALTY`, `WEB`, `APP` or `SUPPORT`."

    Design: Corner/entities/create_source_system_with_invalid_channel_type_enum_rejected
    """
    for bad_channel_type in ("IN_STORE", "transactions", "", "CALL_CENTER"):
        validate_error(
            api.create_source_system(
                f.source_system_payload(channel_type=bad_channel_type), ADMIN
            ),
            ERR_INVALID_REQUEST,
        )

    validate_error(
        api.create_source_system(f.source_system_payload(channel_type=f.OMIT), ADMIN),
        ERR_INVALID_REQUEST,
    )

    stored, meta = validate_paginated(
        api.list_source_systems(ADMIN, {"limit": 10, "offset": 0})
    )
    assert stored == []
    assert meta["total_count"] == 0

    accepted = validate_success(
        api.create_source_system(f.source_system_payload(channel_type="SUPPORT"), ADMIN), 201
    )
    assert accepted["channel_type"] == "SUPPORT"


def test_consent_record_is_append_only_and_corrected_by_supersession(api):
    """A later decision on the same subject, channel and purpose does not edit the
    earlier election: the earlier row survives unchanged but demoted to rank two.

    "The elections of one subject, channel and purpose form a **group**, and within a group precedence is total."
    "Qualifying elections are ranked by `captured_at` descending — the most recent decision wins — then, where two elections were captured at the same instant, by the `trust_tier` of the capture feed descending, and finally by the election's own `created_at` ascending."
    "Rank one is the winner and is the **only** election in its group whose `status` is `ACTIVE`; every lower-ranked sibling carries rank two, three and so on with `status` of `SUPERSEDED`, each such displacement moving that record `ACTIVE` → `SUPERSEDED` and incrementing its `version`."
    "A channel is activatable for a subject only where its resolution is `OPT_IN`."

    Design: Corner/entities/consent_record_is_append_only_and_corrected_by_supersession
    """
    env = fx.single_profile(api)
    profile_id = env["profile"]["id"]
    feed_id = env["feed"]["id"]

    first = validate_success(
        api.create_consent_record(
            f.consent_record_payload(
                profile_id,
                feed_id,
                env["profile"]["version"],
                consent_state="OPT_IN",
                captured_at="2026-07-20T10:00:00Z",
            ),
            PRIVACY,
        ),
        201,
    )
    assert first["precedence_rank"] == 1
    assert first["status"] == "ACTIVE"
    assert first["consent_state"] == "OPT_IN"
    assert_common_fields(first, expected_version=1)
    assert_activatable(fx.reread_profile(api, profile_id), ["EMAIL"])

    live = fx.reread_profile(api, profile_id)
    second = validate_success(
        api.create_consent_record(
            f.consent_record_payload(
                profile_id,
                feed_id,
                live["version"],
                consent_state="OPT_OUT",
                captured_at="2026-07-25T10:00:00Z",
            ),
            PRIVACY,
        ),
        201,
    )
    assert second["id"] != first["id"]
    assert second["precedence_rank"] == 1
    assert second["status"] == "ACTIVE"
    assert second["consent_state"] == "OPT_OUT"
    assert_common_fields(second, expected_version=1)

    demoted = validate_success(api.get_consent_record(first["id"], PRIVACY), 200)
    assert demoted["precedence_rank"] == 2
    assert demoted["status"] == "SUPERSEDED"
    assert demoted["consent_state"] == "OPT_IN"
    assert demoted["channel"] == "EMAIL"
    assert demoted["purpose"] == "MARKETING"
    assert_instant_equals(demoted["captured_at"], "2026-07-20T10:00:00Z", "captured_at")
    assert demoted["version"] == 2

    group, meta = validate_paginated(
        api.list_consent_records(
            PRIVACY,
            {"profile_id": profile_id, "channel": "EMAIL", "purpose": "MARKETING"},
        )
    )
    assert meta["total_count"] == 2
    assert [row["id"] for row in group] == [second["id"], first["id"]]
    assert [row["precedence_rank"] for row in group] == [1, 2]

    assert_activatable(fx.reread_profile(api, profile_id), [])
    assert fx.reread_profile(api, profile_id)["channel_engagement_score"] == approx2(0.00)


def test_create_ingest_batch_with_unknown_source_system_not_found(api):
    """Submitting a batch against a feed id that was never registered answers the
    feed existence error, while a malformed body outranks that existence check.

    "Rungs 5 through 17 are existence, in this fixed order: (5) the retail feed named by `{sourceSystemId}` or by a `source_system_id` body field exists, else `ERR_SOURCE_SYSTEM_NOT_FOUND`; (6) the batch named by `{batchId}` exists, else `ERR_INGEST_BATCH_NOT_FOUND`; (7) every profile named by `{profileId}`, `profile_id`, `left_profile_id` or `right_profile_id` exists, else `ERR_PROFILE_NOT_FOUND`; (8) the household named by `{householdId}` or by the `household_id` body field exists, else `ERR_HOUSEHOLD_NOT_FOUND`; (9) the rule named by `{matchRuleId}` or `match_rule_id` exists, else `ERR_MATCH_RULE_NOT_FOUND`; (10) the link named by `{linkId}` exists, else `ERR_IDENTITY_LINK_NOT_FOUND`; (11) the consent record named by `{consentRecordId}` exists, else `ERR_CONSENT_RECORD_NOT_FOUND`; (12) the suppression entry named by `{suppressionId}` exists, else `ERR_SUPPRESSION_ENTRY_NOT_FOUND`; (13) the segment named by `{segmentId}`, `segment_id` or the `other_segment_id` query parameter exists, else `ERR_SEGMENT_NOT_FOUND`; (14) the destination named by `{destinationId}` or `destination_id` exists, else `ERR_DESTINATION_NOT_FOUND`; (15) the activation named by `{activationId}` exists, else `ERR_ACTIVATION_NOT_FOUND`; (16) the erasure request named by `{deletionRequestId}` exists, else `ERR_DELETION_REQUEST_NOT_FOUND`; (17) the vendor task named by `{taskId}` exists, else `ERR_VENDOR_TASK_NOT_FOUND`."
    "All checks that could apply to a request are evaluated in ascending priority number, and the **first** violated rule alone determines the response; later violations are never reported and never merged into a multi-error body."
    "An empty array is refused as a malformed request."

    Design: Corner/entities/create_ingest_batch_with_unknown_source_system_not_found
    """
    validate_error(
        api.create_ingest_batch(f.ingest_batch_payload(NON_EXISTENT_UUID), ENGINEER),
        ERR_SOURCE_SYSTEM_NOT_FOUND,
    )

    validate_error(
        api.create_ingest_batch(
            f.ingest_batch_payload(NON_EXISTENT_UUID, records=[]), ENGINEER
        ),
        ERR_INVALID_REQUEST,
    )

    stored, meta = validate_paginated(
        api.list_ingest_batches(ENGINEER, {"limit": 10, "offset": 0})
    )
    assert stored == []
    assert meta["total_count"] == 0


def test_identity_link_junction_is_reverse_listable_from_both_profiles(api):
    """One proposed link between two promoted profiles is reachable through each of
    its foreign keys, and the endpoint filters distinguish the two orientations.

    "Links are readable individually and as a list, the latter filterable by `left_profile_id`, `right_profile_id`, `match_rule_id`, `survivor_profile_id` and `status`, which together expose the reverse traversal of all four of the link's foreign keys."
    "Under `STRICT_ZERO` the confidence **is** the raw score, measured against the full weight base of 1.00; an absent component therefore contributes nothing and permanently caps what a sparse pair can score, no matter how perfect the evidence it does have."
    "At or above `review_floor` but below `auto_merge_threshold`, the link is created as `PROPOSED` and waits for a steward."
    "Every link records its `match_method` copied from the minting rule's `rule_kind`, and holds `survivor_profile_id`, `decided_by_user_id`, `decided_at` and `void_reason` null until something decides it."

    Design: Corner/entities/identity_link_junction_is_reverse_listable_from_both_profiles
    """
    env = fx.two_profiles(
        api,
        left_overrides={"first_name": "Ada", "last_name": "Alpha", "postal_code": "10001"},
        right_overrides={"first_name": "Ben", "last_name": "Bravo", "postal_code": "20002"},
    )
    left_id = env["left"]["id"]
    right_id = env["right"]["id"]

    rule = fx.declare_probabilistic_rule(api)
    link = validate_success(
        api.create_identity_link(
            f.identity_link_payload(
                left_id, right_id, rule["id"], f.evidence(1.0, 1.0, 1.0, 0.0)
            ),
            STEWARD,
        ),
        201,
    )

    assert link["status"] == "PROPOSED"
    assert link["confidence"] == approx4(0.8500)
    assert link["match_method"] == "PROBABILISTIC"
    assert link["left_profile_id"] == left_id
    assert link["right_profile_id"] == right_id
    assert link["match_rule_id"] == rule["id"]
    assert link["survivor_profile_id"] is None
    assert link["decided_by_user_id"] is None
    assert link["decided_at"] is None
    assert link["void_reason"] is None

    from_left, left_meta = validate_paginated(
        api.list_identity_links(STEWARD, {"left_profile_id": left_id})
    )
    assert left_meta["total_count"] == 1
    assert [row["id"] for row in from_left] == [link["id"]]

    from_right, right_meta = validate_paginated(
        api.list_identity_links(STEWARD, {"right_profile_id": right_id})
    )
    assert right_meta["total_count"] == 1
    assert [row["id"] for row in from_right] == [link["id"]]

    by_rule, rule_meta = validate_paginated(
        api.list_identity_links(STEWARD, {"match_rule_id": rule["id"], "status": "PROPOSED"})
    )
    assert rule_meta["total_count"] == 1
    assert [row["id"] for row in by_rule] == [link["id"]]

    by_survivor, survivor_meta = validate_paginated(
        api.list_identity_links(STEWARD, {"survivor_profile_id": left_id})
    )
    assert survivor_meta["total_count"] == 0
    assert by_survivor == []

    _, swapped_meta = validate_paginated(
        api.list_identity_links(STEWARD, {"left_profile_id": right_id})
    )
    assert swapped_meta["total_count"] == 0

    fetched = validate_success(api.get_identity_link(link["id"], STEWARD), 200)
    assert fetched["id"] == link["id"]
    assert fetched["status"] == "PROPOSED"


def test_merged_away_profile_is_reachable_by_merged_into_profile_id_filter(api):
    """After a steward confirms a link the loser is torn down but still readable, and
    the profile list exposes it through the survivor it now points at.

    "Survivorship is decided by three discriminators applied in order, the first that separates the pair winning outright: the higher `source_record_count`; then the higher `trust_tier` of the feed named by the profile's `primary_source_system_id`; then the earlier `created_at`."
    "The profile's `id` is never consulted as a tie-breaker."
    "The loser is then torn down: its `resolution_status` moves `RESOLVED` → `MERGED_AWAY`, its `merged_into_profile_id` names the survivor, its `household_id` is cleared because household membership follows the surviving identity, its `lifetime_value_cents` is set to 0 because the value moved rather than duplicated, and its `activatable_channels` becomes empty."
    "Profiles themselves are readable individually and as a list filterable by `origin_batch_id`, `primary_source_system_id`, `household_id`, `merged_into_profile_id`, `resolution_status` and `privacy_status` — the first four being the reverse traversals of the profile's four foreign keys."

    Design: Corner/entities/merged_away_profile_is_reachable_by_merged_into_profile_id_filter
    """
    env = fx.two_profiles(api)
    left_id = env["left"]["id"]
    right_id = env["right"]["id"]

    rule = fx.declare_probabilistic_rule(api)
    link = validate_success(
        api.create_identity_link(
            f.identity_link_payload(
                left_id, right_id, rule["id"], f.evidence(1.0, 1.0, 1.0, 0.0)
            ),
            STEWARD,
        ),
        201,
    )
    assert link["status"] == "PROPOSED"

    decided = validate_success(
        api.decide_identity_link(link["id"], f.link_decision_payload("CONFIRM"), STEWARD), 200
    )
    assert decided["status"] == "CONFIRMED"
    survivor_id = decided["survivor_profile_id"]
    assert survivor_id in (left_id, right_id)
    loser_id = right_id if survivor_id == left_id else left_id

    loser = validate_success(api.get_profile(loser_id, STEWARD), 200)
    assert_profile_axes(loser, "MERGED_AWAY", "NORMAL")
    assert loser["merged_into_profile_id"] == survivor_id
    assert loser["household_id"] is None
    assert loser["lifetime_value_cents"] == 0
    assert loser["activatable_channels"] == []

    survivor = validate_success(api.get_profile(survivor_id, STEWARD), 200)
    assert_profile_axes(survivor, "RESOLVED", "NORMAL")
    assert survivor["merged_into_profile_id"] is None
    assert survivor["source_record_count"] == 2

    by_survivor, survivor_meta = validate_paginated(
        api.list_profiles(STEWARD, {"merged_into_profile_id": survivor_id})
    )
    assert survivor_meta["total_count"] == 1
    assert [row["id"] for row in by_survivor] == [loser_id]

    merged_away, merged_meta = validate_paginated(
        api.list_profiles(STEWARD, {"resolution_status": "MERGED_AWAY"})
    )
    assert merged_meta["total_count"] == 1
    assert [row["id"] for row in merged_away] == [loser_id]

    resolved, resolved_meta = validate_paginated(
        api.list_profiles(STEWARD, {"resolution_status": "RESOLVED"})
    )
    assert resolved_meta["total_count"] == 1
    assert [row["id"] for row in resolved] == [survivor_id]
