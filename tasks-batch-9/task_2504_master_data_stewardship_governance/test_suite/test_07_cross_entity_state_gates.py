"""Writes gated on the state of entities they never name.

Publishing a master record is refused not because of anything on the record but
because the domain is carrying an unresolved critical finding; accepting a merge
is refused not because of the source the proposer nominated but because of the
source behind the survivor the system itself selected. Both gates are exercised
here together with the state changes that open and close them, so the refusal and
the acceptance of the very same call are both observed.
"""

from test_helpers import (
    GOVERNANCE_ADMIN_HEADERS,
    add_master_record,
    add_merge_proposal,
    assert_instant_equals,
    refresh_domain,
    setup_domain_with_duplicate_records,
    setup_domain_with_open_critical_finding,
    validate_error,
    validate_success,
)

DECERTIFY_REASON = "CRM tenant migration invalidated the extract pipeline"
MERGE_JUSTIFICATION = "Stewardship board confirmed these are one legal entity"
RESOLUTION_NOTE = "Backfilled the missing contact attributes from the ERP extract"


def test_publish_refused_while_one_critical_finding_holds_the_domain_restricted(api):
    """PRD §3.6: "The owning domain's `status` must be `ACTIVE`, otherwise
    `ERR_DOMAIN_NOT_ACTIVE`, and its `governance_posture` must be `OPEN` —
    `RESTRICTED` is not good enough for publication — otherwise
    `ERR_DOMAIN_POSTURE_BLOCKED`."
    PRD §2.6: "The posture is then determined in this priority order: it is
    `FROZEN` if the domain holds no such active authoritative registration, or
    if `open_finding_weight` is at least 40.00; otherwise it is `RESTRICTED` if
    `open_finding_weight` is at least 15.00, or if at least one finding in the
    open set is governed by a rule whose `severity` is `CRITICAL`; otherwise it
    is `OPEN`."
    PRD §3.6: "And the record's `completeness_pct` must be at least 60.00, with
    exactly 60.00 acceptable, otherwise `ERR_RECORD_INCOMPLETE`."

    Design: Difficulty/cross_entity_state_dependency/publish_blocked_until_domain_posture_returns_to_open
    """
    ctx, run, finding = setup_domain_with_open_critical_finding()
    record = add_master_record(ctx)

    assert record["completeness_pct"] == 80.00, (
        "four populated keys against an expected five read as 80.00 complete, "
        f"got {record['completeness_pct']}"
    )
    assert record["curation_status"] == "CURATED", (
        f"the record must be endorsed before publication, got {record['curation_status']}"
    )
    assert run["weighted_score"] == 55.55, (
        "a measurement of 50.00 against a threshold of 90.00 earns 22.22 of the "
        f"40 weight points, so the weighted score is 55.55, got {run['weighted_score']}"
    )
    assert finding["severity_weight"] == 20.00, (
        "a CRITICAL breach pinned while the posture was OPEN weighs 20 base "
        f"points times a 1.00 multiplier, got {finding['severity_weight']}"
    )
    assert run["posture_after"] == "RESTRICTED", (
        "one open critical finding restricts the domain, got "
        f"{run['posture_after']}"
    )
    assert ctx["domain"]["governance_posture"] == "RESTRICTED", (
        "the domain itself must read RESTRICTED, got "
        f"{ctx['domain']['governance_posture']}"
    )
    assert ctx["domain"]["open_finding_weight"] == 20.00, (
        "the domain carries the single pinned weight of 20.00, got "
        f"{ctx['domain']['open_finding_weight']}"
    )

    response = api.publish_master_record(record["id"], ctx["steward_headers"])
    validate_error(response, "ERR_DOMAIN_POSTURE_BLOCKED")


def test_blocked_publish_leaves_both_record_dimensions_untouched(api):
    """PRD §3.6: "It bears emphasising that a master record runs two state
    dimensions independently on the same row."
    PRD §3.6: "The owning domain's `status` must be `ACTIVE`, otherwise
    `ERR_DOMAIN_NOT_ACTIVE`, and its `governance_posture` must be `OPEN` —
    `RESTRICTED` is not good enough for publication — otherwise
    `ERR_DOMAIN_POSTURE_BLOCKED`."
    PRD §2.8: "`Domain.published_master_record_count` is the exact integer count
    of the domain's master records whose `publication_status` is `PUBLISHED`."

    Design: Difficulty/cross_entity_state_dependency/publish_blocked_until_domain_posture_returns_to_open
    """
    ctx, _run, _finding = setup_domain_with_open_critical_finding()
    record = add_master_record(ctx)

    validate_error(
        api.publish_master_record(record["id"], ctx["steward_headers"]),
        "ERR_DOMAIN_POSTURE_BLOCKED",
    )

    stored = validate_success(
        api.get_master_record(record["id"], GOVERNANCE_ADMIN_HEADERS)
    )
    assert stored["publication_status"] == "UNPUBLISHED", (
        "the refused publication must leave the publication dimension where it "
        f"was, got {stored['publication_status']}"
    )
    assert stored["curation_status"] == "CURATED", (
        "the refused publication must not disturb the curation dimension, got "
        f"{stored['curation_status']}"
    )
    assert stored["published_at"] is None, (
        f"nothing was published, so published_at stays null, got {stored['published_at']!r}"
    )

    domain = refresh_domain(ctx)
    assert domain["published_master_record_count"] == 0, (
        "no record of the domain is published, so the count stays 0, got "
        f"{domain['published_master_record_count']}"
    )


def test_resolving_the_critical_finding_clears_the_weight_and_reopens_the_domain(api):
    """PRD §3.5: "The caller supplies a `verified_measured_pct` and an optional
    `resolution_note`, and that percentage must be greater than or equal to the
    breached rule's `threshold_pct`; a shortfall is rejected with
    `ERR_RESOLUTION_BELOW_THRESHOLD`."
    PRD §3.5: "From `OPEN → RESOLVED`, everything is identical — `status`
    `RESOLVED`, `resolved_at` stamped, `measured_pct` overwritten, `gap_pct` set
    to 0.00, `open_finding_weight` recomputed and posture recomputed — except
    that no steward's `open_finding_load` moves, because no assignment was ever
    charged."
    PRD §3.2: "`RESTRICTED → OPEN` fires on a finding-set recompute triggered by
    resolving or waiving a finding, and requires both that an `ACTIVE`
    `AUTHORITATIVE` registration exists and that the recomputed
    `open_finding_weight` is below 15.00 with no remaining `OPEN` or
    `REMEDIATION_PLANNED` finding whose rule severity is `CRITICAL`; it sets the
    posture to `OPEN` and advances `version`."

    Design: Difficulty/cross_entity_state_dependency/publish_blocked_until_domain_posture_returns_to_open
    """
    ctx, _run, finding = setup_domain_with_open_critical_finding()

    resolved = validate_success(
        api.resolve_quality_finding(
            finding["id"],
            {"verified_measured_pct": 95.00, "resolution_note": RESOLUTION_NOTE},
            ctx["steward_headers"],
        )
    )

    assert resolved["status"] == "RESOLVED", (
        f"a verified measurement closes the finding, got {resolved['status']}"
    )
    assert resolved["gap_pct"] == 0.00, (
        f"a resolved finding carries no remaining gap, got {resolved['gap_pct']}"
    )
    assert resolved["severity_weight"] == 20.00, (
        "the pinned severity weight of 20.00 stays on the closed row, got "
        f"{resolved['severity_weight']}"
    )

    domain = refresh_domain(ctx)
    assert domain["open_finding_weight"] == 0.00, (
        "a RESOLVED finding leaves the open-set sum, so the weight clears to "
        f"0.00, got {domain['open_finding_weight']}"
    )
    assert domain["governance_posture"] == "OPEN", (
        "with no open critical finding remaining the posture returns to OPEN, "
        f"got {domain['governance_posture']}"
    )


def test_publish_succeeds_once_the_posture_is_open_and_raises_the_published_count(api):
    """PRD §3.6: "On success `publication_status` becomes `PUBLISHED`,
    `published_at` is stamped from the logical clock, the domain's
    `published_master_record_count` is incremented by one, and the domain's
    `version` advances by one."
    PRD §3.6: "The owning domain's `status` must be `ACTIVE`, otherwise
    `ERR_DOMAIN_NOT_ACTIVE`, and its `governance_posture` must be `OPEN` —
    `RESTRICTED` is not good enough for publication — otherwise
    `ERR_DOMAIN_POSTURE_BLOCKED`."
    PRD §2.4: "Every deadline, accountability interval, freeze window, lead-time
    comparison and staleness computation described in this document is evaluated
    against this logical clock, and every timestamp field the server writes —
    `activated_at`, `certified_at`, `decertified_at`, `superseded_at`,
    `opened_at`, `resolved_at`, `published_at`, `measured_at`, `decided_at`,
    `submitted_at`, `applied_at`, `lineage_documented_at`, `notified_at` and
    `acknowledged_at` — is stamped from it."

    Design: Difficulty/cross_entity_state_dependency/publish_blocked_until_domain_posture_returns_to_open
    """
    ctx, _run, finding = setup_domain_with_open_critical_finding()
    record = add_master_record(ctx)

    validate_error(
        api.publish_master_record(record["id"], ctx["steward_headers"]),
        "ERR_DOMAIN_POSTURE_BLOCKED",
    )
    validate_success(
        api.resolve_quality_finding(
            finding["id"],
            {"verified_measured_pct": 95.00, "resolution_note": RESOLUTION_NOTE},
            ctx["steward_headers"],
        )
    )

    published = validate_success(
        api.publish_master_record(record["id"], ctx["steward_headers"])
    )

    assert published["publication_status"] == "PUBLISHED", (
        "the very same call now succeeds against an OPEN posture, got "
        f"{published['publication_status']}"
    )
    assert_instant_equals(
        published["published_at"], "2026-08-05T00:00:00Z", "published_at"
    )

    domain = refresh_domain(ctx)
    assert domain["published_master_record_count"] == 1, (
        "the published set now holds one record, got "
        f"{domain['published_master_record_count']}"
    )


def test_survivorship_and_match_scores_rank_the_duplicate_above_the_nomination(api):
    """PRD §3.6: "The **trust component** is the contributing source system's
    `trust_tier` multiplied by ten, so it ranges from 10 points for a tier-1
    system up to 50 points for a tier-5 one."
    PRD §3.6: "The **completeness component** is the record's `completeness_pct`
    multiplied by four tenths and rounded half up to two decimal places, so it
    ranges from 0 up to 40 points."
    PRD §3.6: "The **recency component** starts from a maximum of 20 points and
    decays by 4 points for every whole month of staleness, where staleness in
    months is the number of whole days between the record's `last_verified_at`
    and the current logical clock, divided by thirty and rounded down to a whole
    number; the component is floored at zero, so a record more than five whole
    months stale contributes 0 rather than a negative number."
    PRD §3.7: "The system first forms a weighted sum of three inputs: five
    tenths of the `name_similarity_pct`, plus three tenths of the
    `key_overlap_pct`, plus two tenths of the lesser of the two candidates'
    `completeness_pct` values as those values stand persisted at the moment of
    the call."
    PRD §3.7: "The derived `match_confidence` then reads `HIGH` when
    `match_score` is at least 85.00, `MEDIUM` when it is at least 60.00 but
    below 85.00, and `LOW` below 60.00."

    Design: Difficulty/cross_entity_state_dependency/merge_blocked_when_effective_survivor_source_decertified
    """
    ctx, survivor, duplicate = setup_domain_with_duplicate_records()

    assert survivor["completeness_pct"] == 40.00, (
        "two populated keys against an expected five read as 40.00 complete, "
        f"got {survivor['completeness_pct']}"
    )
    assert survivor["survivorship_score"] == 72.00, (
        "a tier-4 record 35 days stale with 40.00 completeness scores 40 plus "
        f"16.00 plus 16, so 72.00, got {survivor['survivorship_score']}"
    )
    assert duplicate["completeness_pct"] == 80.00, (
        "four populated keys against an expected five read as 80.00 complete, "
        f"got {duplicate['completeness_pct']}"
    )
    assert duplicate["survivorship_score"] == 102.00, (
        "a tier-5 record 4 days stale with 80.00 completeness scores 50 plus "
        f"32.00 plus 20, so 102.00, got {duplicate['survivorship_score']}"
    )

    proposal = add_merge_proposal(ctx, survivor, duplicate)

    assert proposal["match_score"] == 77.00, (
        "45.00 of name similarity plus 24.00 of key overlap plus 8.00 of the "
        f"lesser completeness gives 77.00, got {proposal['match_score']}"
    )
    assert proposal["match_confidence"] == "MEDIUM", (
        f"77.00 sits between 60.00 and 85.00, got {proposal['match_confidence']}"
    )
    assert proposal["status"] == "UNDER_REVIEW", (
        f"the hand-off has been taken up, got {proposal['status']}"
    )


def test_decertifying_a_contributing_source_revokes_only_its_own_registration(api):
    """PRD §3.2: "**Hop 2**, caused by hop 1, drives every `SourceRegistration`
    on that system whose `status` is `ACTIVE` from `ACTIVE` to `REVOKED`,
    writing the literal string `SOURCE_DECERTIFIED` into each one's
    `revoked_reason`."
    PRD §3.2: "**Hop 3**, caused by hop 2, visits every domain that is thereby
    left holding no `ACTIVE` `AUTHORITATIVE` registration, sets that domain's
    `authoritative_source_code` to null, and recomputes `governance_posture` —
    which necessarily yields `FROZEN`, since absence of an active authoritative
    registration is itself a freezing condition."
    PRD §3.2: "Note that `authoritative_source_code` holds a source system's
    short code, not an identifier, and that it is derived rather than declared:
    it always reflects whichever registration currently has `role` of
    `AUTHORITATIVE` and `status` of `ACTIVE` for the domain, and it is null when
    no such registration exists."

    Design: Difficulty/cross_entity_state_dependency/merge_blocked_when_effective_survivor_source_decertified
    """
    ctx, _survivor, _duplicate = setup_domain_with_duplicate_records()

    validate_success(
        api.decertify_source_system(
            ctx["sources"]["CRM"]["id"],
            {"reason": DECERTIFY_REASON},
            GOVERNANCE_ADMIN_HEADERS,
        )
    )

    registration = validate_success(
        api.get_source_registration(
            ctx["registrations"]["CRM"]["id"], GOVERNANCE_ADMIN_HEADERS
        )
    )
    assert registration["status"] == "REVOKED", (
        "the decertified system's own active registration is revoked, got "
        f"{registration['status']}"
    )

    domain = refresh_domain(ctx)
    assert domain["authoritative_source_code"] == "WMS", (
        "the authoritative registration sits on a different system and survives "
        f"untouched, got {domain['authoritative_source_code']!r}"
    )
    assert domain["governance_posture"] == "OPEN", (
        "an active authoritative registration remains and no finding is open, "
        f"so the posture stays OPEN, got {domain['governance_posture']}"
    )


def test_merge_refused_when_the_selected_survivor_sits_on_a_decertified_source(api):
    """PRD §3.7: "The source system behind the effective survivor must be in
    `CERTIFIED` status, otherwise `ERR_SOURCE_NOT_CERTIFIED`."
    PRD §3.7: "The **score-priority** variant applies when both candidates share
    the authoritative `source_system_id`, and equally when neither of them
    carries it — including the case where the authoritative registration has
    been superseded onto some third source system altogether."
    PRD §3.7: "In that case the survivor is the candidate with the higher
    `survivorship_score`, breaking ties first by the later `last_verified_at`
    and then by the earlier `created_at`, and never by `id`."
    PRD §3.7: "a `HIGH`-confidence proposal merges freely, a `MEDIUM`-confidence
    proposal merges only when the data owner supplies an
    `override_justification` of at least 20 characters, and a `LOW`-confidence
    proposal cannot be merged at all"

    Design: Difficulty/cross_entity_state_dependency/merge_blocked_when_effective_survivor_source_decertified
    """
    ctx, survivor, duplicate = setup_domain_with_duplicate_records()
    proposal = add_merge_proposal(ctx, survivor, duplicate)

    validate_success(
        api.decertify_source_system(
            ctx["sources"]["CRM"]["id"],
            {"reason": DECERTIFY_REASON},
            GOVERNANCE_ADMIN_HEADERS,
        )
    )

    response = api.decide_merge_proposal(
        proposal["id"],
        {"decision": "MERGE", "override_justification": MERGE_JUSTIFICATION},
        ctx["owner_headers"],
    )
    validate_error(response, "ERR_SOURCE_NOT_CERTIFIED")


def test_refused_merge_leaves_the_proposal_under_review_with_no_survivor_decision(api):
    """PRD §3.7: "**Hop 1** selects the variant, computes and stores
    `effective_survivor_master_record_id`, `survivor_swapped`,
    `survivorship_variant` and `survivorship_field_map`, sets the proposal's
    `status` to `MERGED`, and stamps `decided_at` from the clock."
    PRD §3.7: "The source system behind the effective survivor must be in
    `CERTIFIED` status, otherwise `ERR_SOURCE_NOT_CERTIFIED`."
    PRD §3.7: "and `survivor_swapped` is set true exactly when that identifier
    differs from the `survivor_master_record_id` the proposer originally
    nominated."

    Design: Difficulty/cross_entity_state_dependency/merge_blocked_when_effective_survivor_source_decertified
    """
    ctx, survivor, duplicate = setup_domain_with_duplicate_records()
    proposal = add_merge_proposal(ctx, survivor, duplicate)
    validate_success(
        api.decertify_source_system(
            ctx["sources"]["CRM"]["id"],
            {"reason": DECERTIFY_REASON},
            GOVERNANCE_ADMIN_HEADERS,
        )
    )

    validate_error(
        api.decide_merge_proposal(
            proposal["id"],
            {"decision": "MERGE", "override_justification": MERGE_JUSTIFICATION},
            ctx["owner_headers"],
        ),
        "ERR_SOURCE_NOT_CERTIFIED",
    )

    stored = validate_success(
        api.get_merge_proposal(proposal["id"], GOVERNANCE_ADMIN_HEADERS)
    )
    assert stored["status"] == "UNDER_REVIEW", (
        f"the refused decision leaves the proposal awaiting a verdict, got "
        f"{stored['status']}"
    )
    assert stored["effective_survivor_master_record_id"] is None, (
        "no survivor was selected, got "
        f"{stored['effective_survivor_master_record_id']!r}"
    )
    assert stored["survivor_swapped"] is False, (
        f"no survivor swap was recorded, got {stored['survivor_swapped']!r}"
    )
    assert stored["decided_at"] is None, (
        f"the proposal is not decided, so decided_at stays null, got {stored['decided_at']!r}"
    )


def test_refused_merge_leaves_both_candidate_records_exactly_as_they_were(api):
    """PRD §3.7: "**Hop 2**, caused by hop 1, enriches the effective survivor
    from the loser: for every attribute key appearing on either record, the
    winning value is the effective survivor's value when that key is present and
    non-null on the survivor, and otherwise the loser's value — so the survivor's
    data is never overwritten, only its gaps are filled."
    PRD §3.7: "**Hop 3**, caused by hop 2's absorption of the loser, drives the
    loser's `curation_status` to `MERGED_AWAY` and writes the effective
    survivor's identifier into the loser's `superseded_by_master_record_id`; if
    the loser was `PUBLISHED` its `publication_status` becomes `RETRACTED` and
    the domain's `published_master_record_count` is decremented by one."
    PRD §3.7: "The source system behind the effective survivor must be in
    `CERTIFIED` status, otherwise `ERR_SOURCE_NOT_CERTIFIED`."

    Design: Difficulty/cross_entity_state_dependency/merge_blocked_when_effective_survivor_source_decertified
    """
    ctx, survivor, duplicate = setup_domain_with_duplicate_records()
    proposal = add_merge_proposal(ctx, survivor, duplicate)
    validate_success(
        api.decertify_source_system(
            ctx["sources"]["CRM"]["id"],
            {"reason": DECERTIFY_REASON},
            GOVERNANCE_ADMIN_HEADERS,
        )
    )

    validate_error(
        api.decide_merge_proposal(
            proposal["id"],
            {"decision": "MERGE", "override_justification": MERGE_JUSTIFICATION},
            ctx["owner_headers"],
        ),
        "ERR_SOURCE_NOT_CERTIFIED",
    )

    nominated = validate_success(
        api.get_master_record(survivor["id"], GOVERNANCE_ADMIN_HEADERS)
    )
    assert nominated["curation_status"] == "CURATED", (
        f"the nominated survivor is untouched, got {nominated['curation_status']}"
    )
    assert nominated["completeness_pct"] == 40.00, (
        "no attribute fill happened, so completeness stays at 40.00, got "
        f"{nominated['completeness_pct']}"
    )

    loser = validate_success(
        api.get_master_record(duplicate["id"], GOVERNANCE_ADMIN_HEADERS)
    )
    assert loser["curation_status"] == "CURATED", (
        f"the duplicate candidate is not merged away, got {loser['curation_status']}"
    )
    assert loser["superseded_by_master_record_id"] is None, (
        "nothing superseded the duplicate candidate, got "
        f"{loser['superseded_by_master_record_id']!r}"
    )
