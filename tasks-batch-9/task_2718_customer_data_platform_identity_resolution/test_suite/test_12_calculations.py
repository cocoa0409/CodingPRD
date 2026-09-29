"""Derived figures: data-quality scoring, rolling feed aggregates, consent
precedence, merge survivorship, household allocation, audience resolution and
the two match-rate variants.

Every figure asserted here is one the PRD pins to an exact width and an exact
formula, so each test reproduces the arithmetic from raw inputs through the
documented endpoints rather than trusting a round number.
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
    approx2,
    approx4,
    assert_instant_equals,
)
from test_helpers.test_users import (
    ADMIN,
    ANALYST,
    ENGINEER,
    PRIVACY,
    STEWARD,
    make_destination_platform_headers,
)


def _record(external_id, event_timestamp, **fields):
    """A raw record whose five identifier components are each stated explicitly.

    Every component starts null so that a test naming only the components it
    wants gets exactly the pass / fail / absent pattern it intends.
    """
    payload = dict(
        email_raw=None,
        phone_raw=None,
        loyalty_number=None,
        first_name=None,
        last_name=None,
        postal_code=None,
        address_line=None,
        consent_signals=[],
    )
    payload.update(fields)
    return f.raw_record(external_id, event_timestamp=event_timestamp, **payload)


EMAIL_OPT_IN_SIGNAL = [
    {"channel": "EMAIL", "purpose": "MARKETING", "consent_state": "OPT_IN"}
]
SMS_OPT_IN_SIGNAL = [
    {"channel": "SMS", "purpose": "MARKETING", "consent_state": "OPT_IN"}
]


def test_dq_pass_rate_aggregates_valid_over_submitted_records(api):
    """Validating a three-record batch under the default weighted mode produces the
    batch average over all records and then rolls the feed's window aggregate up.

    "Under `WEIGHTED_COMPONENTS`, the score is the sum of the weights of the passing components, over a weight base that is always the full 1.00: an email that passes contributes 0.30, a phone 0.20, a loyalty number 0.20, a name pair 0.15 and a postal code 0.15 — the five weights summing to exactly 1.00, so email is worth twice postal code — and failing is again indistinguishable from being absent."

    "The batch-level `dq_score` is the sum of the per-record scores over **all** records — invalid ones included — divided by `record_count`, rounded half up to two decimal places; it measures the feed, not the survivors."

    "A record is **valid** when its score is at least 0.60 and **invalid** when its score is strictly below 0.60; the boundary is inclusive on the valid side, so a score of exactly 0.60 is valid."

    "Alongside it, `dq_failure_breakdown` is written as a map from component name to the count of records in which that component was present but malformed; components that were merely absent never appear in those counts."

    "The format checks are exact: `email_raw` must consist of one or more characters that are neither whitespace nor an at-sign, then an at-sign, then one or more such characters, then a dot, then at least two letters — after which it is lower-cased and trimmed to become `email_norm`; `phone_raw` must reduce to exactly eleven digits beginning with the digit one once plus signs, hyphens, dots, spaces and parentheses are stripped, becoming `phone_norm`; `loyalty_number` must be the two letters `LY` followed by exactly eight digits; `postal_code` must be exactly five digits; and `name_pair` passes only when **both** `first_name` and `last_name` are non-blank after trimming."

    "Where the computed `dq_score` is at least the feed's `pii_completeness_floor` — inclusive at equality — the batch moves `RECEIVED` → `VALIDATED` and `validated_at` is stamped at the logical clock now."

    "`dq_pass_rate` is then the valid total divided by the submitted total, rounded half up to four decimal places, except that when the submitted total is 0 the rate is exactly 1.0000, because a feed with no evidence is presumed clean."

    "A feed is driven to `QUARANTINED` when, after a recomputation, its `submitted_record_total` has reached at least five records **and** its `dq_pass_rate` is strictly below its own `pii_completeness_floor`."

    Design: Corner/calculations/dq_pass_rate_aggregates_valid_over_submitted_records
    """
    env = fx.received_batch(
        api,
        [
            # All five components pass: 0.30 + 0.20 + 0.20 + 0.15 + 0.15 = 1.00.
            _record(
                "CR1",
                "2026-07-30T10:00:00Z",
                email_raw="cr1@example.com",
                phone_raw="+1 (555) 400-0001",
                loyalty_number="LY00004001",
                first_name="Ada",
                last_name="Alpha",
                postal_code="10001",
            ),
            # Phone present but only seven digits, loyalty absent:
            # 0.30 email + 0.15 name pair + 0.15 postal = 0.60.
            _record(
                "CR2",
                "2026-07-30T11:00:00Z",
                email_raw="cr2@example.com",
                phone_raw="555-0002",
                loyalty_number=None,
                first_name="Ben",
                last_name="Bravo",
                postal_code="20002",
            ),
            # Email and postal absent: 0.20 + 0.20 + 0.15 = 0.55.
            _record(
                "CR3",
                "2026-07-30T12:00:00Z",
                email_raw=None,
                phone_raw="+1 (555) 400-0003",
                loyalty_number="LY00004003",
                first_name="Cleo",
                last_name="Chase",
                postal_code=None,
            ),
        ],
        {
            "code": "CA_CORRECT",
            "display_name": "Correct Result Feed",
            "channel_type": "TRANSACTIONS",
            "trust_tier": 3,
        },
    )

    scored = validate_success(api.validate_batch(env["batch"]["id"], ENGINEER), 200)

    # (1.00 + 0.60 + 0.55) / 3 = 0.716666..., rounded half up to two places.
    assert scored["dq_score"] == approx2(0.72)
    assert scored["valid_record_count"] == 2
    assert scored["invalid_record_count"] == 1
    assert scored["dq_failure_breakdown"] == {"phone_norm": 1}
    assert scored["status"] == "VALIDATED"

    feed = fx.reread_feed(api, env["feed"]["id"])
    assert feed["submitted_record_total"] == 3
    assert feed["valid_record_total"] == 2
    assert feed["dq_pass_rate"] == approx4(0.6667)
    # 0.6667 is under the 0.70 floor, but three in-window records is short of the
    # five the quarantine gate demands, so the feed is left where it was.
    assert feed["status"] == "REGISTERED"
    assert feed["quarantine_count"] == 0


def test_dq_record_min_constant_splits_valid_from_invalid_records(api):
    """A record scoring exactly 0.60 is valid while one scoring 0.55 is not, and the
    batch score still averages both of them, which drives the batch to quarantine.

    "A record is **valid** when its score is at least 0.60 and **invalid** when its score is strictly below 0.60; the boundary is inclusive on the valid side, so a score of exactly 0.60 is valid."

    "The batch-level `dq_score` is the sum of the per-record scores over **all** records — invalid ones included — divided by `record_count`, rounded half up to two decimal places; it measures the feed, not the survivors."

    "Alongside it, `dq_failure_breakdown` is written as a map from component name to the count of records in which that component was present but malformed; components that were merely absent never appear in those counts."

    "Where the score is strictly below the floor, the batch moves `RECEIVED` → `QUARANTINED`, with `validated_at` stamped just the same."

    "`dq_pass_rate` is then the valid total divided by the submitted total, rounded half up to four decimal places, except that when the submitted total is 0 the rate is exactly 1.0000, because a feed with no evidence is presumed clean."

    "A feed is driven to `QUARANTINED` when, after a recomputation, its `submitted_record_total` has reached at least five records **and** its `dq_pass_rate` is strictly below its own `pii_completeness_floor`."

    Design: Corner/calculations/dq_record_min_constant_splits_valid_from_invalid_records
    """
    env = fx.received_batch(
        api,
        [
            # 0.30 email + 0.15 name pair + 0.15 postal = exactly 0.60.
            _record(
                "CN1",
                "2026-07-30T10:00:00Z",
                email_raw="cn1@example.com",
                first_name="Ada",
                last_name="Alpha",
                postal_code="10001",
            ),
            # 0.20 phone + 0.20 loyalty + 0.15 name pair = 0.55.
            _record(
                "CN2",
                "2026-07-30T11:00:00Z",
                phone_raw="+1 (555) 420-0002",
                loyalty_number="LY00004202",
                first_name="Ben",
                last_name="Bravo",
            ),
        ],
        {
            "code": "CA_CONST",
            "display_name": "Constant Feed",
            "channel_type": "SUPPORT",
            "trust_tier": 3,
        },
    )

    scored = validate_success(api.validate_batch(env["batch"]["id"], ENGINEER), 200)

    assert scored["valid_record_count"] == 1
    assert scored["invalid_record_count"] == 1
    # (0.60 + 0.55) / 2 = 0.575, rounded half up away from zero.
    assert scored["dq_score"] == approx2(0.58)
    # Nothing was malformed; every failing component was simply absent.
    assert scored["dq_failure_breakdown"] == {}
    assert scored["status"] == "QUARANTINED"

    feed = fx.reread_feed(api, env["feed"]["id"])
    assert feed["submitted_record_total"] == 2
    assert feed["valid_record_total"] == 1
    assert feed["dq_pass_rate"] == approx4(0.5000)
    assert feed["status"] == "REGISTERED"


def test_source_dq_scoring_mode_unweighted_mean_selected_by_source_config(api):
    """The very same component pattern scores 0.60 under a feed configured for the
    unweighted mean and 0.55 under a feed left on the weighted default.

    "The per-record score is then computed by one of three formulas, selected by the contributing feed's `dq_scoring_mode`, and the three genuinely disagree."

    "Under `UNWEIGHTED_MEAN`, the score is the number of passing components divided by five; the weight table is ignored entirely, so a record missing only its email scores exactly the same as a record missing only its postal code, and failing is indistinguishable from being absent."

    "Under `WEIGHTED_COMPONENTS`, the score is the sum of the weights of the passing components, over a weight base that is always the full 1.00: an email that passes contributes 0.30, a phone 0.20, a loyalty number 0.20, a name pair 0.15 and a postal code 0.15 — the five weights summing to exactly 1.00, so email is worth twice postal code — and failing is again indistinguishable from being absent."

    "A record is **valid** when its score is at least 0.60 and **invalid** when its score is strictly below 0.60; the boundary is inclusive on the valid side, so a score of exactly 0.60 is valid."

    "`dq_pass_rate` is then the valid total divided by the submitted total, rounded half up to four decimal places, except that when the submitted total is 0 the rate is exactly 1.0000, because a feed with no evidence is presumed clean."

    Design: Corner/calculations/source_dq_scoring_mode_unweighted_mean_selected_by_source_config
    """
    unweighted_env = fx.received_batch(
        api,
        [
            _record(
                "MU1",
                "2026-07-30T10:00:00Z",
                phone_raw="+1 (555) 490-0001",
                loyalty_number="LY00004901",
                first_name="Ada",
                last_name="Alpha",
            )
        ],
        {
            "code": "CA_MODE_U",
            "display_name": "Unweighted Mode Feed",
            "channel_type": "SUPPORT",
            "trust_tier": 3,
            "dq_scoring_mode": "UNWEIGHTED_MEAN",
            "pii_completeness_floor": 0.50,
        },
    )
    weighted_env = fx.received_batch(
        api,
        [
            _record(
                "MW1",
                "2026-07-30T11:00:00Z",
                phone_raw="+1 (555) 490-0002",
                loyalty_number="LY00004902",
                first_name="Ben",
                last_name="Bravo",
            )
        ],
        {
            "code": "CA_MODE_W",
            "display_name": "Weighted Mode Feed",
            "channel_type": "SUPPORT",
            "trust_tier": 3,
            "dq_scoring_mode": "WEIGHTED_COMPONENTS",
            "pii_completeness_floor": 0.50,
        },
    )

    unweighted = validate_success(
        api.validate_batch(unweighted_env["batch"]["id"], ENGINEER), 200
    )
    weighted = validate_success(
        api.validate_batch(weighted_env["batch"]["id"], ENGINEER), 200
    )

    # Three of the five components pass, and every component is worth one fifth.
    assert unweighted["dq_score"] == approx2(0.60)
    assert unweighted["valid_record_count"] == 1
    assert unweighted["invalid_record_count"] == 0
    assert unweighted["status"] == "VALIDATED"

    # The same three components carry 0.20 + 0.20 + 0.15 over the fixed 1.00 base.
    assert weighted["dq_score"] == approx2(0.55)
    assert weighted["valid_record_count"] == 0
    assert weighted["invalid_record_count"] == 1
    assert weighted["status"] == "VALIDATED"

    assert unweighted["dq_failure_breakdown"] == {}
    assert weighted["dq_failure_breakdown"] == {}

    unweighted_feed = fx.reread_feed(api, unweighted_env["feed"]["id"])
    weighted_feed = fx.reread_feed(api, weighted_env["feed"]["id"])
    assert unweighted_feed["dq_pass_rate"] == approx4(1.0000)
    assert weighted_feed["dq_pass_rate"] == approx4(0.0000)


def test_dq_pass_rate_reset_by_reinstate_excludes_prior_batches(api):
    """Five in-window records at a 0.4000 pass rate quarantine the feed even though
    the batch itself cleared the floor, and reinstating it moves the window forward
    so those same batches never count again.

    "A feed is driven to `QUARANTINED` when, after a recomputation, its `submitted_record_total` has reached at least five records **and** its `dq_pass_rate` is strictly below its own `pii_completeness_floor`."

    "The transition applies from either non-quarantined state — a feed already `ACTIVE` moves `ACTIVE` → `QUARANTINED`, and a feed that has never promoted anything moves `REGISTERED` → `QUARANTINED` — and in both cases the feed's `quarantine_count` increments by 1, its `version` increments by 1, and a cascade hop rejects every batch of that feed still sitting in `RECEIVED`, setting each of those batches' `rejection_reason` to `SOURCE_QUARANTINED`."

    "Reinstatement requires the feed to be `QUARANTINED`, moves it `QUARANTINED` → `ACTIVE`, stamps `last_reinstated_at` at the logical clock now, and — critically — **resets the quality baseline** by setting `dq_window_start_at` to the logical clock now as well."

    "Because the window now starts in the present, the in-window batch set is empty, so `submitted_record_total` and `valid_record_total` fall back to 0 and `dq_pass_rate` returns to 1.0."

    "Batches created before the reset never re-enter the window and can never trigger a second quarantine on their own."

    "A feed that has been quarantined and reinstated three times carries a `quarantine_count` of 3 and a `last_reinstated_at` of the most recent lift; the counter is never reset."

    Design: Corner/calculations/dq_pass_rate_reset_by_reinstate_excludes_prior_batches
    """
    records = [
        _record(
            "AG1",
            "2026-07-30T10:00:00Z",
            email_raw="ag1@example.com",
            phone_raw="+1 (555) 440-0001",
            loyalty_number="LY00004401",
            first_name="Ada",
            last_name="Alpha",
            postal_code="10001",
        ),
        _record(
            "AG2",
            "2026-07-30T11:00:00Z",
            email_raw="ag2@example.com",
            phone_raw="+1 (555) 440-0002",
            loyalty_number="LY00004402",
            first_name="Ben",
            last_name="Bravo",
            postal_code="10002",
        ),
    ]
    for index, (external_id, phone, loyalty, first, last) in enumerate(
        [
            ("AG3", "+1 (555) 440-0003", "LY00004403", "Cleo", "Chase"),
            ("AG4", "+1 (555) 440-0004", "LY00004404", "Dana", "Delta"),
            ("AG5", "+1 (555) 440-0005", "LY00004405", "Evan", "Echo"),
        ]
    ):
        records.append(
            _record(
                external_id,
                f"2026-07-30T1{2 + index}:00:00Z",
                phone_raw=phone,
                loyalty_number=loyalty,
                first_name=first,
                last_name=last,
            )
        )

    env = fx.received_batch(
        api,
        records,
        {
            "code": "CA_AGG",
            "display_name": "Aggregation Feed",
            "channel_type": "TRANSACTIONS",
            "trust_tier": 3,
        },
    )

    scored = validate_success(api.validate_batch(env["batch"]["id"], ENGINEER), 200)
    # (2 * 1.00 + 3 * 0.55) / 5 = 3.65 / 5, which clears the 0.70 floor.
    assert scored["dq_score"] == approx2(0.73)
    assert scored["status"] == "VALIDATED"

    quarantined = fx.reread_feed(api, env["feed"]["id"])
    assert quarantined["submitted_record_total"] == 5
    assert quarantined["valid_record_total"] == 2
    assert quarantined["dq_pass_rate"] == approx4(0.4000)
    # Exactly five in-window records is already enough evidence to act on.
    assert quarantined["status"] == "QUARANTINED"
    assert quarantined["quarantine_count"] == 1

    fx.set_clock(api, "2026-08-02T00:00:00Z")
    reinstated = validate_success(
        api.reinstate_source_system(env["feed"]["id"], ADMIN), 200
    )

    assert reinstated["status"] == "ACTIVE"
    assert reinstated["submitted_record_total"] == 0
    assert reinstated["valid_record_total"] == 0
    assert reinstated["dq_pass_rate"] == approx4(1.0000)
    assert_instant_equals(
        reinstated["dq_window_start_at"], "2026-08-02T00:00:00Z", "dq_window_start_at"
    )
    assert_instant_equals(
        reinstated["last_reinstated_at"], "2026-08-02T00:00:00Z", "last_reinstated_at"
    )
    assert reinstated["quarantine_count"] == 1

    # The reset moves the window; it does not rewrite the batch's history.
    batch = fx.reread_batch(api, env["batch"]["id"])
    assert batch["status"] == "VALIDATED"
    assert batch["dq_score"] == approx2(0.73)


def test_audience_resolution_excludes_members_lacking_the_destination_channel(api):
    """Two members of the same segment, one reachable on EMAIL and one only on SMS,
    resolve to an audience of one against an EMAIL destination, the other member
    landing in suppressed_count rather than being dispatched.

    "Membership is a conjunction: a profile is a member only when **every** predicate holds."

    "The eligible population is narrower still: only profiles whose `resolution_status` is not `MERGED_AWAY` and whose `privacy_status` is exactly `NORMAL` are considered."

    "`candidate_count` is the size of the segment's member set at this instant."

    "The audience is those candidates whose `activatable_channels` contains the destination's `channel`, and `audience_size` is its size."

    "`suppressed_count` is `candidate_count` less `audience_size` — the members removed by consent or suppression."

    "`dispatched_hash_count` is the number of audience members whose required identifier, selected by the destination's `hashing_algorithm`, is non-null."

    "A channel is activatable for a subject only where its resolution is `OPT_IN`."

    "On success the activation moves `DRAFT` → `DISPATCHED`, `dispatched_at` is stamped at the logical clock now, the destination's `remaining_daily_hash_quota` decreases by `dispatched_hash_count`, the segment's `active_activation_count` increases by 1, and the activation's, the destination's and the segment's `version` each increment by 1."

    Design: Corner/calculations/audience_resolution_excludes_members_lacking_the_destination_channel
    """
    env = fx.promoted_batch(
        api,
        [
            f.raw_record(
                "AU1",
                email_raw="au1@example.com",
                postal_code="10001",
                consent_signals=EMAIL_OPT_IN_SIGNAL,
            ),
            f.raw_record(
                "AU2",
                email_raw="au2@example.com",
                postal_code="10001",
                consent_signals=SMS_OPT_IN_SIGNAL,
            ),
        ],
        {
            "code": "CA_AUD",
            "display_name": "Audience Feed",
            "channel_type": "WEB",
            "trust_tier": 3,
        },
    )
    assert len(env["profiles"]) == 2

    destination = fx.register_destination(
        api,
        permissive=False,
        code="CA_AUD_DEST",
        channel="EMAIL",
        hashing_algorithm="SHA256_EMAIL_LOWER",
        daily_hash_quota=300,
        min_audience_size=1,
        min_match_rate=0.10,
    )
    segment = fx.approved_segment(api, f.POSTAL_10001, name="Postal Audience")
    assert segment["member_count"] == 2

    activation = fx.draft_activation(api, segment["id"], destination["id"])
    dispatched = validate_success(
        api.dispatch_activation(activation["id"], ANALYST), 200
    )

    assert dispatched["candidate_count"] == 2
    # Only the EMAIL opt-in carries EMAIL in its activatable channel set.
    assert dispatched["audience_size"] == 1
    assert dispatched["suppressed_count"] == 1
    assert dispatched["dispatched_hash_count"] == 1
    assert dispatched["status"] == "DISPATCHED"
    assert_instant_equals(
        dispatched["dispatched_at"], "2026-08-01T00:00:00Z", "dispatched_at"
    )

    after_destination = fx.reread_destination(api, destination["id"])
    assert after_destination["remaining_daily_hash_quota"] == 299
    after_segment = fx.reread_segment(api, segment["id"])
    assert after_segment["active_activation_count"] == 1


def test_overlap_jaccard_index_rounds_to_four_decimals(api):
    """Two segments sharing two of three profiles report a Jaccard index of 0.6667,
    and reading the same pair from the other side swaps the containment ratios while
    leaving the Jaccard index alone.

    "The read reports `segment_member_count` and `other_segment_member_count` as the two set sizes, `overlap_count` as the number of profiles in both, and `union_count` as the two sizes added together less the overlap."

    "Three ratios follow, each rounded half up to four decimal places: `jaccard_index` is the overlap divided by the union, or exactly 0.0000 where the union is empty; `containment_in_other` is the overlap divided by this segment's own size, or exactly 0.0000 where this segment is empty; and `containment_of_other` is the overlap divided by the other segment's size, or exactly 0.0000 where the other segment is empty."

    "The Jaccard index is symmetric, but the two containment ratios are not — reading the pair from the other side swaps them, which is what makes the direction of the read meaningful."

    "`activatable_channels` is the sorted alphabetical-ascending list of the activatable channels among the five, and `channel_engagement_score` is the count of those channels divided by five, rounded half up to two decimal places — so a subject reachable on every channel scores 1.00, one reachable on three scores 0.60, and a fully suppressed subject holds an empty channel list and a score of 0.00."

    "`GTE` holds when the attribute is non-null and at least the predicate value, numerically — it applies to `lifetime_value_cents` and `channel_engagement_score`, and to `loyalty_tier` on the ordinal scale where `NONE` counts as 0, `SILVER` as 1, `GOLD` as 2 and `PLATINUM` as 3."

    Design: Corner/calculations/overlap_jaccard_index_rounds_to_four_decimals
    """
    env = fx.promoted_batch(
        api,
        [
            f.raw_record(
                "OV1",
                email_raw="ov1@example.com",
                postal_code="10001",
                consent_signals=EMAIL_OPT_IN_SIGNAL,
            ),
            f.raw_record("OV2", email_raw="ov2@example.com", postal_code="10001"),
            f.raw_record(
                "OV3",
                email_raw="ov3@example.com",
                postal_code="10001",
                consent_signals=EMAIL_OPT_IN_SIGNAL,
            ),
        ],
        {
            "code": "CA_OVL",
            "display_name": "Overlap Feed",
            "channel_type": "WEB",
            "trust_tier": 3,
        },
    )
    assert len(env["profiles"]) == 3

    postal_segment = fx.draft_segment(api, f.POSTAL_10001, name="Postal Three")
    engaged_segment = fx.draft_segment(
        api,
        [f.criterion("channel_engagement_score", "GTE", 0.20)],
        name="Engaged Two",
    )
    assert postal_segment["member_count"] == 3
    # One of five channels resolves to OPT_IN for two of the three subjects.
    assert engaged_segment["member_count"] == 2

    forward = validate_success(
        api.get_segment_overlap(
            postal_segment["id"], ANALYST, {"other_segment_id": engaged_segment["id"]}
        ),
        200,
    )
    assert forward["segment_member_count"] == 3
    assert forward["other_segment_member_count"] == 2
    assert forward["overlap_count"] == 2
    # 3 + 2 - 2 leaves three distinct profiles across the pair.
    assert forward["union_count"] == 3
    assert forward["jaccard_index"] == approx4(0.6667)
    assert forward["containment_in_other"] == approx4(0.6667)
    assert forward["containment_of_other"] == approx4(1.0000)

    reverse = validate_success(
        api.get_segment_overlap(
            engaged_segment["id"], ANALYST, {"other_segment_id": postal_segment["id"]}
        ),
        200,
    )
    assert reverse["segment_member_count"] == 2
    assert reverse["other_segment_member_count"] == 3
    assert reverse["overlap_count"] == 2
    assert reverse["union_count"] == 3
    # Symmetric on the index, mirrored on the two containment ratios.
    assert reverse["jaccard_index"] == approx4(0.6667)
    assert reverse["containment_in_other"] == approx4(1.0000)
    assert reverse["containment_of_other"] == approx4(0.6667)


def test_consent_precedence_ranks_by_captured_at_then_trust_tier(api):
    """Three elections in one group settle by capture instant first and by the trust
    tier of the capturing feed only on a tie, so the later opt-in from the tier-four
    feed outranks the same-instant opt-out and the older opt-in alike.

    "Qualifying elections are ranked by `captured_at` descending — the most recent decision wins — then, where two elections were captured at the same instant, by the `trust_tier` of the capture feed descending, and finally by the election's own `created_at` ascending."

    "Rank one is the winner and is the **only** election in its group whose `status` is `ACTIVE`; every lower-ranked sibling carries rank two, three and so on with `status` of `SUPERSEDED`, each such displacement moving that record `ACTIVE` → `SUPERSEDED` and incrementing its `version`."

    "Capturing a new election therefore re-ranks the whole group, and the same re-ranking runs when promotion materialises the `consent_signals` of a raw record."

    "`precedence_rank` records that position as a one-based index."

    "The rank-one member's `consent_state` is the resolution."

    "A channel is activatable for a subject only where its resolution is `OPT_IN`."

    "`activatable_channels` is the sorted alphabetical-ascending list of the activatable channels among the five, and `channel_engagement_score` is the count of those channels divided by five, rounded half up to two decimal places — so a subject reachable on every channel scores 1.00, one reachable on three scores 0.60, and a fully suppressed subject holds an empty channel list and a score of 0.00."

    "`consent_record_count` counts the subject's elections whose `status` is `ACTIVE`."

    Design: Corner/calculations/consent_precedence_ranks_by_captured_at_then_trust_tier
    """
    env = fx.promoted_batch(
        api,
        [f.raw_record("PC1", email_raw="pc1@example.com", postal_code="10001")],
        {
            "code": "CA_PREC_MID",
            "display_name": "Mid Tier Feed",
            "channel_type": "TRANSACTIONS",
            "trust_tier": 2,
        },
    )
    profile = env["profiles"][0]
    low_feed = fx.register_feed(
        api,
        code="CA_PREC_LOW",
        display_name="Low Tier Feed",
        channel_type="SUPPORT",
        trust_tier=1,
    )
    high_feed = fx.register_feed(
        api,
        code="CA_PREC_HIGH",
        display_name="High Tier Feed",
        channel_type="LOYALTY",
        trust_tier=4,
    )

    fx.set_clock(api, "2026-08-13T00:00:00Z")

    # Same capture instant, different capturing feeds: the tier decides between them.
    opt_out_low = fx.capture_consent(
        api,
        profile["id"],
        low_feed["id"],
        channel="EMAIL",
        purpose="MARKETING",
        consent_state="OPT_OUT",
        captured_at="2026-08-12T00:00:00Z",
    )
    opt_in_high = fx.capture_consent(
        api,
        profile["id"],
        high_feed["id"],
        channel="EMAIL",
        purpose="MARKETING",
        consent_state="OPT_IN",
        captured_at="2026-08-12T00:00:00Z",
    )
    # Captured two days earlier, so it loses on the first discriminator outright.
    opt_in_older = fx.capture_consent(
        api,
        profile["id"],
        env["feed"]["id"],
        channel="EMAIL",
        purpose="MARKETING",
        consent_state="OPT_IN",
        captured_at="2026-08-10T00:00:00Z",
    )

    winner = validate_success(api.get_consent_record(opt_in_high["id"], PRIVACY), 200)
    assert winner["precedence_rank"] == 1
    assert winner["status"] == "ACTIVE"
    assert winner["consent_state"] == "OPT_IN"

    runner_up = validate_success(api.get_consent_record(opt_out_low["id"], PRIVACY), 200)
    assert runner_up["precedence_rank"] == 2
    assert runner_up["status"] == "SUPERSEDED"

    oldest = validate_success(api.get_consent_record(opt_in_older["id"], PRIVACY), 200)
    assert oldest["precedence_rank"] == 3
    assert oldest["status"] == "SUPERSEDED"

    after = fx.reread_profile(api, profile["id"])
    assert after["activatable_channels"] == ["EMAIL"]
    assert after["channel_engagement_score"] == approx2(0.20)
    # Only the rank-one election is ACTIVE, so only it is counted.
    assert after["consent_record_count"] == 1


def test_suppression_propagates_member_count_recompute_to_segment(api):
    """Suppressing one of two members re-derives the segment's member_count inside the
    suppressing request without disturbing the segment's place in the review loop.

    "The three narrow-purpose types move it `NORMAL` → `SUPPRESSED`; note that `DO_NOT_SELL` moves the axis to `SUPPRESSED` too, even though only the advertising channel is actually masked, because the subject is no longer in an unqualified normal state."

    "The eligible population is narrower still: only profiles whose `resolution_status` is not `MERGED_AWAY` and whose `privacy_status` is exactly `NORMAL` are considered."

    "Any change that moves a profile into or out of the eligible population — a merge setting `resolution_status` to `MERGED_AWAY`, a suppression setting `privacy_status` to `SUPPRESSED`, a conversion raising `lifetime_value_cents`, a consent change moving `channel_engagement_score` — re-derives `member_count` for every non-retired segment whose criteria touch the changed attribute, within the causing request."

    "The recomputation settles in a single pass because criteria never reference another segment's membership."

    "Recomputation always reaches a fixed point in a single pass, because no criterion and no derived field in this system references another segment's membership."

    Design: Corner/calculations/suppression_propagates_member_count_recompute_to_segment
    """
    env = fx.promoted_batch(
        api,
        [
            f.raw_record("SP1", email_raw="sp1@example.com", postal_code="10001"),
            f.raw_record("SP2", email_raw="sp2@example.com", postal_code="10001"),
        ],
        {
            "code": "CA_SUPP",
            "display_name": "Suppression Feed",
            "channel_type": "WEB",
            "trust_tier": 3,
        },
    )
    first, second = env["profiles"]

    segment = fx.draft_segment(api, f.POSTAL_10001, name="Postal Pair")
    submitted = fx.submit_segment(api, segment["id"])
    assert submitted["status"] == "PENDING_GOVERNANCE_REVIEW"
    assert submitted["member_count"] == 2

    entry = validate_success(
        api.create_suppression_entry(
            f.suppression_entry_payload(
                first["id"],
                entry_type="GLOBAL_OPT_OUT",
                reason_code="SUBJECT_REQUEST",
                effective_at="2026-08-01T00:00:00Z",
            ),
            PRIVACY,
        ),
        201,
    )
    assert entry["entry_type"] == "GLOBAL_OPT_OUT"

    suppressed = fx.reread_profile(api, first["id"])
    assert suppressed["privacy_status"] == "SUPPRESSED"
    assert fx.reread_profile(api, second["id"])["privacy_status"] == "NORMAL"

    recomputed = fx.reread_segment(api, segment["id"])
    # The suppressed subject has left the eligible population; the other stays.
    assert recomputed["member_count"] == 1
    # The recompute is a derivation, not a lifecycle move.
    assert recomputed["status"] == "PENDING_GOVERNANCE_REVIEW"

    # A second read of the same segment settles on the same figure.
    assert fx.reread_segment(api, segment["id"])["member_count"] == 1


def test_merge_survivorship_field_level_keeps_survivor_non_null_values(api):
    """A perfect match on the two components the pair actually has renormalises to a
    confidence of 1.0000, which auto-confirms the merge, and the survivor then keeps
    every non-null identifier of its own while adopting only what it was missing.

    "Confidence is then computed from the four evidence values under a fixed weight table: an email component is worth 0.40, a phone 0.25, a name 0.20 and an address 0.15, the four summing to exactly 1.00."

    "The **raw** score is the sum, over only those components whose evidence value is non-null, of that component's weight multiplied by its similarity value."

    "Under `RENORMALIZE` the denominator shrinks to the summed weight of the present components only, so a pair that matches perfectly on everything it has scores 1.0000 even with two of the four components missing; where that summed present weight is 0 — every component absent — the confidence is exactly 0.0000 rather than an undefined division."

    "In both policies the result is rounded half up to four decimal places before any threshold comparison."

    "At or above `auto_merge_threshold` the link is created and immediately advanced `PROPOSED` → `CONFIRMED` with `decided_by_user_id` set to the literal string `system` rather than to any header value, `decided_at` stamped at the logical clock now, and the full merge run inside the creating call — the platform's only machine-authored merge."

    "Survivorship is decided by three discriminators applied in order, the first that separates the pair winning outright: the higher `source_record_count`; then the higher `trust_tier` of the feed named by the profile's `primary_source_system_id`; then the earlier `created_at`."

    "Seven identifier fields — `email_norm`, `phone_norm`, `first_name`, `last_name`, `postal_code`, `address_hash` and `loyalty_number` — follow field-level survivorship: the survivor keeps each of its own non-null values and adopts the loser's value only where its own is null."

    "Four quantities roll up onto the survivor: `source_record_count` and `lifetime_value_cents` each increase by the loser's amount, `contributing_source_system_codes` becomes the sorted union of both lists, `last_activity_at` becomes the later of the two, and `loyalty_tier` becomes the higher of the two on the `NONE`-`SILVER`-`GOLD`-`PLATINUM` ordinal scale."

    "The loser is then torn down: its `resolution_status` moves `RESOLVED` → `MERGED_AWAY`, its `merged_into_profile_id` names the survivor, its `household_id` is cleared because household membership follows the surviving identity, its `lifetime_value_cents` is set to 0 because the value moved rather than duplicated, and its `activatable_channels` becomes empty."

    "Alongside all of this, the rule's `confirmed_count` increases by 1 and its `precision_estimate` is recomputed."

    Design: Corner/calculations/merge_survivorship_field_level_keeps_survivor_non_null_values
    """
    env = fx.promoted_batch(
        api,
        [
            # Every component passes and no address is supplied, so address_hash is null.
            f.raw_record(
                "PJ1",
                email_raw="pj1@example.com",
                phone_raw="+1 (555) 470-0001",
                loyalty_number="LY00004701",
                postal_code="10001",
                address_line=None,
            ),
            # No phone, but an address, so the two profiles are complementary.
            f.raw_record(
                "PJ2",
                email_raw="pj2@example.com",
                phone_raw=None,
                loyalty_number="LY00004702",
                postal_code="10001",
                address_line="9 Pine Road",
            ),
        ],
        {
            "code": "CA_PROJ",
            "display_name": "Projection Feed",
            "channel_type": "LOYALTY",
            "trust_tier": 3,
        },
    )
    assert len(env["profiles"]) == 2
    first, second = env["profiles"]
    assert first["phone_norm"] is not None
    assert first["address_hash"] is None
    assert second["phone_norm"] is None
    loser_address_hash = second["address_hash"]
    assert loser_address_hash is not None

    rule = fx.declare_probabilistic_rule(
        api,
        code="CA_PROJ_RULE",
        missing_identifier_policy="RENORMALIZE",
        auto_merge_threshold=0.92,
        review_floor=0.65,
        min_precision=0.60,
    )

    link = validate_success(
        api.create_identity_link(
            f.identity_link_payload(
                first["id"],
                second["id"],
                rule["id"],
                f.evidence(
                    email_similarity=1.0,
                    phone_similarity=None,
                    name_similarity=1.0,
                    address_similarity=None,
                ),
            ),
            STEWARD,
        ),
        201,
    )

    # Raw 0.40 + 0.20 over a present-weight base of 0.60 renormalises to 1.0000.
    assert link["confidence"] == approx4(1.0000)
    assert link["status"] == "CONFIRMED"
    assert link["decided_by_user_id"] == "system"
    assert_instant_equals(link["decided_at"], "2026-08-01T00:00:00Z", "decided_at")
    # Both profiles tie on record count and on feed trust tier, so the earlier of
    # the two survives on the third discriminator.
    assert link["survivor_profile_id"] == first["id"]

    survivor = fx.reread_profile(api, first["id"])
    assert survivor["resolution_status"] == "RESOLVED"
    # Its own non-null values stand, whatever the loser carried.
    assert survivor["email_norm"] == first["email_norm"]
    assert survivor["phone_norm"] == first["phone_norm"]
    assert survivor["loyalty_number"] == first["loyalty_number"]
    assert survivor["postal_code"] == "10001"
    # The one field it lacked is adopted from the loser.
    assert survivor["address_hash"] == loser_address_hash
    assert survivor["source_record_count"] == 2
    assert survivor["contributing_source_system_codes"] == ["CA_PROJ"]

    loser = fx.reread_profile(api, second["id"])
    assert loser["resolution_status"] == "MERGED_AWAY"
    assert loser["merged_into_profile_id"] == first["id"]
    assert loser["household_id"] is None
    assert loser["lifetime_value_cents"] == 0
    assert loser["activatable_channels"] == []

    after_rule = fx.reread_rule(api, rule["id"])
    assert after_rule["confirmed_count"] == 1
    assert after_rule["rejected_count"] == 0
    assert after_rule["precision_estimate"] == approx4(1.0000)


def test_household_grouping_fills_first_bucket_before_opening_the_second(api):
    """Seven profiles promoted at one address fill bucket one to its six-member
    ceiling and then open bucket two for the seventh, in strict sequence order.

    "A household holds at most six members."

    "Assignment is a strict waterfall. For a profile with a non-null `address_hash`, the buckets considered are the `ACTIVE` households at that same address, taken in `sequence_no` ascending order; the first bucket whose `member_count` is below six takes the profile and the search stops there."

    "Where no bucket has room, a new household is minted at that address whose `sequence_no` is one greater than the highest `sequence_no` among **all** households at that address — including `DISSOLVED` ones, so a dissolved bucket's index is retired and never re-issued — and the profile joins it."

    "The consequence is a strictly ordered overflow: the sixth profile to arrive at an address still joins bucket 1, and the seventh opens bucket 2."

    "Its grouping key is `address_hash`, minted by promotion when the first profile at that address appears, and its `sequence_no` is the overflow index at that address: the first household there is 1, the next 2, and so on."

    "`member_count` is the number of profiles whose `household_id` names this household and whose `resolution_status` is not `MERGED_AWAY` and whose `privacy_status` is not `DELETED`. `dominant_last_name` is the most frequent non-null `last_name` among those members, ties broken alphabetically ascending, and is null when every member's last name is null. `combined_lifetime_value_cents` is the sum of the members' `lifetime_value_cents`."

    "Households are ordered by `sequence_no` ascending within one address, then `created_at` ascending and `id` ascending across addresses, so that the overflow buckets at a single address read in bucket order."

    "If no rule attaches the record, a new profile is minted with `resolution_status` of `UNRESOLVED`, `privacy_status` of `NORMAL` and `source_record_count` of 1, and the batch's `new_profile_count` increments by 1."

    Design: Corner/calculations/household_grouping_fills_first_bucket_before_opening_the_second
    """
    records = [
        f.raw_record(
            f"HH{index + 1}",
            email_raw=f"hh{index + 1}@example.com",
            postal_code="10001",
            last_name="Alpha",
            address_line="12 Oak Street",
        )
        for index in range(7)
    ]
    env = fx.promoted_batch(
        api,
        records,
        {
            "code": "CA_HOUSE",
            "display_name": "Household Feed",
            "channel_type": "TRANSACTIONS",
            "trust_tier": 3,
        },
    )

    assert env["batch"]["new_profile_count"] == 7
    assert len(env["profiles"]) == 7

    households, meta = validate_paginated(
        api.list_households(ADMIN, {"limit": 100, "offset": 0})
    )
    # Six seats in bucket one, so the seventh arrival forces a second bucket.
    assert meta["total_count"] == 2
    assert [h["sequence_no"] for h in households] == [1, 2]

    first_bucket, second_bucket = households
    assert first_bucket["member_count"] == 6
    assert second_bucket["member_count"] == 1
    assert first_bucket["address_hash"] == second_bucket["address_hash"]
    for household in households:
        assert household["status"] == "ACTIVE"
        assert household["dominant_last_name"] == "Alpha"
        assert household["combined_lifetime_value_cents"] == 0

    feed = fx.reread_feed(api, env["feed"]["id"])
    assert feed["submitted_record_total"] == 7
    assert feed["valid_record_total"] == 7
    assert feed["dq_pass_rate"] == approx4(1.0000)
    assert feed["status"] == "ACTIVE"


def test_second_match_report_recovers_activation_from_underperforming_to_active(api):
    """A first report of nothing matched drives the activation under the destination's
    floor and raises the destination's underperforming counter, and a second report of
    a full match recovers it, taking the counter back down without touching the quota.

    "`gross_match_rate` divides `vendor_matched_count` by `dispatched_hash_count`, or is exactly 0.0000 where nothing was dispatched."

    "`net_match_rate` divides `vendor_matched_count` by the usable count — `dispatched_hash_count` less `unusable_hash_count` — or is exactly 0.0000 where that usable count is zero or negative."

    "Two rates are then computed and **both are always stored**, whichever one the destination has nominated."

    "`effective_match_rate` is the gross rate where the destination's `match_rate_basis` is `GROSS` and the net rate otherwise; all three are null until the first report arrives."

    "The effective rate routes the activation, inclusively at the boundary: at or above the destination's `min_match_rate` the activation becomes `ACTIVE`, and strictly below it becomes `UNDERPERFORMING`."

    "Every entry into `UNDERPERFORMING` increments the destination's `underperforming_activation_count` by 1 and every recovery to `ACTIVE` decrements it by 1."

    "Reports are accepted while the activation is `DISPATCHED`, `ACTIVE` or `UNDERPERFORMING`, so a destination may report repeatedly over the window."

    "At every moment, and for as long as `quota_reset_on` is unchanged, `remaining_daily_hash_quota` equals `daily_hash_quota` minus the sum of `dispatched_hash_count` over that destination's activations whose status is `DISPATCHED`, `ACTIVE` or `UNDERPERFORMING`."

    "`active_activation_count` separately counts this segment's activations in `DISPATCHED`, `ACTIVE` or `UNDERPERFORMING`."

    Design: Corner/calculations/second_match_report_recovers_activation_from_underperforming_to_active
    """
    env = fx.promoted_batch(
        api,
        [
            f.raw_record(
                "RC1",
                email_raw="rc1@example.com",
                postal_code="10001",
                consent_signals=EMAIL_OPT_IN_SIGNAL,
            ),
            f.raw_record(
                "RC2",
                email_raw="rc2@example.com",
                postal_code="10001",
                consent_signals=EMAIL_OPT_IN_SIGNAL,
            ),
        ],
        {
            "code": "CA_RECOVER",
            "display_name": "Recovery Feed",
            "channel_type": "WEB",
            "trust_tier": 3,
        },
    )
    assert len(env["profiles"]) == 2

    destination = fx.register_destination(
        api,
        permissive=False,
        code="CA_RECOVER_DEST",
        channel="EMAIL",
        hashing_algorithm="SHA256_EMAIL_LOWER",
        daily_hash_quota=300,
        match_rate_basis="GROSS",
        min_match_rate=0.50,
        min_audience_size=1,
    )
    segment = fx.approved_segment(api, f.POSTAL_10001, name="Recovery Audience")
    activation = fx.draft_activation(api, segment["id"], destination["id"])

    dispatched = validate_success(
        api.dispatch_activation(activation["id"], ANALYST), 200
    )
    assert dispatched["audience_size"] == 2
    assert dispatched["dispatched_hash_count"] == 2
    assert fx.reread_destination(api, destination["id"])["remaining_daily_hash_quota"] == 298

    headers = make_destination_platform_headers(destination["id"])
    first_report = validate_success(
        api.report_match(
            activation["id"], f.match_report_payload(0, 0), headers
        ),
        200,
    )
    assert first_report["gross_match_rate"] == approx4(0.0000)
    assert first_report["net_match_rate"] == approx4(0.0000)
    assert first_report["effective_match_rate"] == approx4(0.0000)
    # 0.0000 is strictly below the destination's 0.50 floor.
    assert first_report["status"] == "UNDERPERFORMING"
    assert (
        fx.reread_destination(api, destination["id"])["underperforming_activation_count"]
        == 1
    )

    second_report = validate_success(
        api.report_match(
            activation["id"], f.match_report_payload(2, 0), headers
        ),
        200,
    )
    assert second_report["vendor_matched_count"] == 2
    assert second_report["gross_match_rate"] == approx4(1.0000)
    assert second_report["net_match_rate"] == approx4(1.0000)
    assert second_report["effective_match_rate"] == approx4(1.0000)
    assert second_report["status"] == "ACTIVE"

    after_destination = fx.reread_destination(api, destination["id"])
    assert after_destination["underperforming_activation_count"] == 0
    # A report never moves money: the hashes are still held by a delivering activation.
    assert after_destination["remaining_daily_hash_quota"] == 298
    assert fx.reread_segment(api, segment["id"])["active_activation_count"] == 1
