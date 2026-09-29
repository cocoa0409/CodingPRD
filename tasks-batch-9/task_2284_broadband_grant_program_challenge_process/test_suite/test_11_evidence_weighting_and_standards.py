"""Evidence weighting: recency bands, staleness, the two standards, immutability."""

from test_helpers import (
    ApiErrorId,
    api_client,
    append_evidence,
    assert_challenge,
    assert_challenge_evidence,
    create_challenge_payload,
    create_evidence_payload,
    file_challenge,
    read_challenge,
    read_location,
    setup_challenge_open_program,
    setup_community_challenge_meeting_standard,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ADMIN, ANALYST, CHALLENGER
from test_helpers.test_users import TEST_USERS

PROVIDER_FILER = TEST_USERS["provider_other_headers"]


def test_the_recency_multiplier_switches_exactly_on_its_day_boundaries():
    """Four items straddle the two band edges at one-day resolution: 180 days keeps
    full weight, 181 days is halved, 365 days is still halved, and 366 days is
    excluded outright — and the excluded item is absent from both the score and the
    distinct-type count.

    PRD 3.2: "Age is measured in whole days from the artefact's `collected_at` to
    the challenge's `created_at`: take the elapsed time between those two
    instants, express it in seconds, divide by the 86400 seconds in a day, and
    discard any fraction."
    PRD 3.2: "The resulting `recency_multiplier` is 1.0 when that age is 180 days
    or fewer, 0.5 when it is between 181 and 365 days inclusive, and 0 when it is
    more than 365 days — that is, evidence stays at full weight for half a year,
    is halved for the remainder of the first year, and counts for nothing once it
    is more than a year old."
    PRD 3.2: "`STALE_EXCLUDED` items contribute nothing to either score and are
    excluded from the distinct-type count entirely."

    Design: Corner/calculations/challenge_evidence_recency_multiplier_day_boundaries
    """
    ctx = setup_challenge_open_program(("L3",))
    challenge = file_challenge(ctx["program_id"], ctx["location_ids"]["L3"], CHALLENGER)
    assert challenge["version"] == 1

    probes = [
        ("SERVICE_DENIAL_LETTER", "2026-02-11T00:00:00Z", 30, 1.0, 30.00, "ACCEPTED"),
        ("SUBSCRIBER_BILL", "2026-02-10T00:00:00Z", 25, 0.5, 12.50, "ACCEPTED"),
        ("FIELD_SURVEY", "2025-08-10T00:00:00Z", 20, 0.5, 10.00, "ACCEPTED"),
        ("MAP_DATA_EXPORT", "2025-08-09T00:00:00Z", 10, 0.0, 0.00, "STALE_EXCLUDED"),
    ]
    for kind, collected_at, base, multiplier, weighted, state in probes:
        item = append_evidence(challenge["id"], kind, collected_at, CHALLENGER)
        assert_challenge_evidence(item)
        assert item["base_weight"] == base, f"{kind} carries the type's base weight"
        assert item["recency_multiplier"] == multiplier, (
            f"{kind} collected at {collected_at} falls in the {multiplier} band"
        )
        assert item["weighted_value"] == weighted
        assert item["evidence_state"] == state
        assert item["submitter_side"] == "CHALLENGE"

    final = read_challenge(challenge["id"])
    assert_challenge(final)
    assert final["evidence_sufficiency_score"] == 52.50, (
        "30.00 plus 12.50 plus 10.00, with the year-old item excluded"
    )
    assert final["rebuttal_strength_score"] == 0.00
    assert final["distinct_evidence_type_count"] == 3
    assert final["version"] == 5, "One create plus four appends, each a mutation"

    items, meta = validate_paginated(
        api_client.list_challenge_evidence(challenge["id"], ADMIN)
    )
    assert meta["total_count"] == 4
    states = [i["evidence_state"] for i in items]
    assert states.count("ACCEPTED") == 3
    assert states.count("STALE_EXCLUDED") == 1


def test_a_stale_second_type_leaves_the_community_record_below_its_standard():
    """The record physically holds two evidence types, but the older one is stale
    and therefore counts for neither the score nor the distinct-type test, so the
    community standard is unmet and triage is refused with the challenge untouched.

    PRD 3.2: "Under the **community standard**, which applies when
    `challenger_type` is `COMMUNITY`, `LOCAL_GOVERNMENT` or `NONPROFIT`, the
    threshold is 40.00 and `distinct_evidence_type_count` must be at least 2; no
    privileged evidence type is required."
    PRD 3.2: "Alongside them the challenge carries `distinct_evidence_type_count`,
    the number of distinct `evidence_type` values among `ACCEPTED` items on the
    `CHALLENGE` side."
    PRD 3.3: "Triage is the `EligibilityAnalyst`'s decision to take a challenge
    seriously. It moves the challenge `SUBMITTED → REBUTTAL_OPEN` and requires the
    program to be in `CHALLENGE_OPEN`, `CHALLENGE_CLOSED` or `SCORING` and the
    evidence standard of §3.2 to be met in full — the score at or above the
    challenger type's threshold, plus the provider's privileged-item requirement or
    the community party's two-distinct-type requirement as applicable."
    PRD 3.2: "A challenge that fails its standard where the standard is required is
    refused with `ERR_EVIDENCE_STANDARD_NOT_MET`."

    Design: Corner/calculations/stale_evidence_excluded_from_distinct_types_triage_rejected
    """
    ctx = setup_challenge_open_program(("L3",))
    contested = ctx["location_ids"]["L3"]
    challenge = file_challenge(ctx["program_id"], contested, CHALLENGER)

    fresh = append_evidence(
        challenge["id"], "SERVICE_DENIAL_LETTER", "2026-06-01T00:00:00Z", CHALLENGER
    )
    stale = append_evidence(
        challenge["id"], "SPEED_TEST", "2025-01-01T00:00:00Z", CHALLENGER
    )
    assert fresh["evidence_state"] == "ACCEPTED"
    assert stale["evidence_state"] == "STALE_EXCLUDED"
    assert stale["weighted_value"] == 0.00

    before = read_challenge(challenge["id"])
    assert before["evidence_sufficiency_score"] == 30.00
    assert before["distinct_evidence_type_count"] == 1, (
        "The stale SPEED_TEST is excluded from the distinct-type count entirely"
    )
    assert before["required_sufficiency_threshold"] == 40.00

    refused = api_client.triage_challenge(challenge["id"], ANALYST)
    validate_error(refused, ApiErrorId.ERR_EVIDENCE_STANDARD_NOT_MET)

    after = read_challenge(challenge["id"])
    assert after["challenge_state"] == "SUBMITTED"
    assert after["triaged_by_user_id"] is None
    assert after["rebuttal_round"] == 0
    assert after["rebuttal_deadline"] is None
    assert read_location(contested)["eligibility_state"] == "MAPPED"

    _, meta = validate_paginated(
        api_client.list_challenge_evidence(challenge["id"], ADMIN)
    )
    assert meta["total_count"] == 2, "The refusal does not remove the appended items"


def test_the_same_record_passes_the_community_standard_and_fails_the_provider_one():
    """Two identical evidentiary records, 45.00 across two distinct types, diverge
    purely on the filer's declared type: the community filing is triaged, while the
    provider filing sits below its higher threshold and is refused.

    PRD 3.2: "A new challenge starts in `challenge_state` `SUBMITTED`, records the
    filer's `X-User-ID` as `submitter_user_id`, sets `rebuttal_round` and
    `resubmission_count` to 0, and stamps `required_sufficiency_threshold` from the
    challenger type: 60.00 when `challenger_type` is `PROVIDER`, and 40.00 for
    every other challenger type."
    PRD 3.2: "Under the **provider standard**, which applies when `challenger_type`
    is `PROVIDER`, the threshold is 60.00 and the record must also contain at least
    one `ACCEPTED` `CHALLENGE`-side item whose `evidence_type` is
    `PROVIDER_ATTESTATION` or `MAP_DATA_EXPORT`; the distinct-type rule does not
    apply to providers at all."
    PRD 3.2: "A challenge that fails its standard where the standard is required is
    refused with `ERR_EVIDENCE_STANDARD_NOT_MET`."

    Design: Corner/calculations/provider_versus_community_evidence_standard_divergence
    """
    ctx = setup_challenge_open_program(("L1", "L2"))
    community_target = ctx["location_ids"]["L1"]
    provider_target = ctx["location_ids"]["L2"]

    community = setup_community_challenge_meeting_standard(
        ctx["program_id"], community_target, CHALLENGER
    )
    provider = setup_community_challenge_meeting_standard(
        ctx["program_id"],
        provider_target,
        PROVIDER_FILER,
        challenger_type="PROVIDER",
        rationale="Provider filing with the same two evidence types.",
    )

    community_row = read_challenge(community["id"])
    provider_row = read_challenge(provider["id"])
    assert community_row["evidence_sufficiency_score"] == 45.00
    assert provider_row["evidence_sufficiency_score"] == 45.00, (
        "Both records carry the identical 30.00 plus 15.00 evidence"
    )
    assert community_row["distinct_evidence_type_count"] == 2
    assert provider_row["distinct_evidence_type_count"] == 2
    assert community_row["required_sufficiency_threshold"] == 40.00
    assert provider_row["required_sufficiency_threshold"] == 60.00

    triaged = validate_success(api_client.triage_challenge(community["id"], ANALYST))
    assert triaged["challenge_state"] == "REBUTTAL_OPEN"
    assert read_location(community_target)["eligibility_state"] == "CHALLENGED"

    refused = api_client.triage_challenge(provider["id"], ANALYST)
    validate_error(refused, ApiErrorId.ERR_EVIDENCE_STANDARD_NOT_MET)
    assert read_challenge(provider["id"])["challenge_state"] == "SUBMITTED"
    assert read_location(provider_target)["eligibility_state"] == "MAPPED"


def test_each_appended_item_is_its_own_immutable_row_without_a_version():
    """Two appends of the same evidence type produce two separate rows, each
    carrying an identifier and a creation instant and neither carrying the mutation
    fields, while the parent challenge absorbs both into one score.

    PRD 2.4: "Two resource families are append-only records of something that
    already happened and therefore carry only `id` and `created_at`: a
    `ChallengeEvidence` item and a `LedgerEntry`."
    PRD 2.4: "Neither exposes `updated_at` and neither exposes `version` — they are
    never mutated after creation, so there is nothing for those fields to
    describe."
    PRD 3.2: "Evidence is appended one item at a time, and each
    **ChallengeEvidence** item is immutable once written."

    Design: Corner/entities/challenge_evidence_is_immutable_and_carries_no_version
    """
    ctx = setup_challenge_open_program(("L3",))
    challenge = file_challenge(ctx["program_id"], ctx["location_ids"]["L3"], CHALLENGER)

    first = append_evidence(
        challenge["id"], "SPEED_TEST", "2026-07-01T00:00:00Z", CHALLENGER
    )
    second = append_evidence(
        challenge["id"], "SPEED_TEST", "2026-07-02T00:00:00Z", CHALLENGER
    )

    for item in (first, second):
        assert_challenge_evidence(item)
        assert "version" not in item
        assert "updated_at" not in item
        assert item["base_weight"] == 15
        assert item["weighted_value"] == 15.00
        assert item["challenge_id"] == challenge["id"]
        assert item["submitter_user_id"] == "comm-1"
    assert first["id"] != second["id"], "Each append is a new row, never an update"
    assert isinstance(first["created_at"], str)
    assert isinstance(second["created_at"], str)

    items, meta = validate_paginated(
        api_client.list_challenge_evidence(challenge["id"], ADMIN)
    )
    assert meta["total_count"] == 2
    assert {i["id"] for i in items} == {first["id"], second["id"]}

    parent = read_challenge(challenge["id"])
    assert parent["evidence_sufficiency_score"] == 30.00
    assert parent["distinct_evidence_type_count"] == 1
    assert parent["version"] == 3


def test_a_challenger_type_outside_the_enumeration_is_refused():
    """Both enumerated fields on a filing are closed sets, so a plausible but
    unlisted filer type and an unlisted asserted classification are each refused
    before any challenge row exists.

    PRD 3.2: "The `challenger_type` is one of `PROVIDER`, `COMMUNITY`,
    `LOCAL_GOVERNMENT` or `NONPROFIT`, and `asserted_classification` is one of
    `SERVED`, `UNDERSERVED` or `UNSERVED`."
    PRD 2.12: "3. **Priority 14 — request validity.** Body parses as JSON; every
    required input field present; enum values in range; integer fields integral;
    percentage fields within 0 through 100; every `*_cents` field at least 0; ISO
    8601 timestamps parse and carry an explicit UTC offset →
    `ERR_INVALID_REQUEST`."

    Design: Corner/validations/challenger_type_enum_out_of_range_rejected
    """
    ctx = setup_challenge_open_program(("L3",))
    contested = ctx["location_ids"]["L3"]

    bad_type = api_client.create_challenge(
        create_challenge_payload(
            ctx["program_id"], contested, challenger_type="MUNICIPAL_UTILITY"
        ),
        CHALLENGER,
    )
    validate_error(bad_type, ApiErrorId.ERR_INVALID_REQUEST)

    bad_classification = api_client.create_challenge(
        create_challenge_payload(
            ctx["program_id"], contested, asserted_classification="PARTIALLY_SERVED"
        ),
        CHALLENGER,
    )
    validate_error(bad_classification, ApiErrorId.ERR_INVALID_REQUEST)

    rows, meta = validate_paginated(api_client.list_challenges(ADMIN))
    assert rows == []
    assert meta["total_count"] == 0
    assert read_location(contested)["challenge_count"] == 0


def test_an_append_guarded_by_a_superseded_challenge_version_is_refused():
    """Every append recomputes the running scores and therefore moves the parent's
    version, so the guard value that admitted the first append is already stale for
    the second, and the refused append leaves the record exactly as it was.

    PRD 2.10: "If `expected_challenge_version` does not equal the challenge's
    current `version`, the append is rejected with
    `ERR_STALE_CHALLENGE_VERSION` (HTTP 412)."
    PRD 2.4: "Recomputing a derived field counts as a mutation."
    PRD 3.2: "Two running totals live on the challenge, and both are recomputed on
    every append."

    Design: Corner/cross-cutting complexity layers/occ_stale_challenge_version_on_evidence_append_rejected
    """
    ctx = setup_challenge_open_program(("L3",))
    challenge = file_challenge(ctx["program_id"], ctx["location_ids"]["L3"], CHALLENGER)
    assert challenge["version"] == 1

    accepted = append_evidence(
        challenge["id"],
        "SERVICE_DENIAL_LETTER",
        "2026-06-01T00:00:00Z",
        CHALLENGER,
        expected_challenge_version=1,
    )
    assert accepted["evidence_state"] == "ACCEPTED"
    assert read_challenge(challenge["id"])["version"] == 2

    stale = api_client.append_challenge_evidence(
        challenge["id"],
        create_evidence_payload("SUBSCRIBER_BILL", "2026-06-02T00:00:00Z", 1),
        CHALLENGER,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_CHALLENGE_VERSION, 412)

    unchanged = read_challenge(challenge["id"])
    assert unchanged["version"] == 2, "The refused append is not a mutation"
    assert unchanged["evidence_sufficiency_score"] == 30.00
    assert unchanged["distinct_evidence_type_count"] == 1
    _, meta = validate_paginated(
        api_client.list_challenge_evidence(challenge["id"], ADMIN)
    )
    assert meta["total_count"] == 1

    retried = validate_success(
        api_client.append_challenge_evidence(
            challenge["id"],
            create_evidence_payload("SUBSCRIBER_BILL", "2026-06-02T00:00:00Z", 2),
            CHALLENGER,
        ),
        201,
    )
    assert retried["weighted_value"] == 25.00
    refreshed = read_challenge(challenge["id"])
    assert refreshed["version"] == 3
    assert refreshed["evidence_sufficiency_score"] == 55.00
    assert refreshed["distinct_evidence_type_count"] == 2
