"""Governance loops that send work back to its author instead of forward.

A reviewer who asks for changes tears down the change request's impact
assessment so that the next submission rebuilds it from the new instant, and a
data owner who bounces a merge proposal for rework lets a fresh matching pass
lift a proposal that could not be merged at all into one that can.
"""

from test_helpers import (
    GOVERNANCE_ADMIN_HEADERS,
    add_change_request,
    add_consumer_subscription,
    add_master_record,
    add_merge_proposal,
    assert_instant_equals,
    set_clock,
    setup_governed_domain,
    validate_error,
    validate_success,
)


def _domain_with_two_consumers():
    """A live domain with a critical consumer needing ten days and a tier-two
    consumer needing three."""
    ctx = setup_governed_domain()
    critical = add_consumer_subscription(ctx)
    secondary = add_consumer_subscription(
        ctx,
        consumer_code="BI_CUSTOMER_SUMMARY",
        reporting_asset_key="RPT_CUST_SUMMARY",
        criticality="TIER2",
        required_lead_days=3,
    )
    return ctx, critical, secondary


def _domain_with_duplicate_candidates():
    """Two records of one domain, the authoritative ERP one better populated."""
    ctx = setup_governed_domain(
        activate=False,
        rules=[],
        sources=[
            {
                "code": "ERP",
                "name": "ERP Core",
                "trust_tier": 4,
                "role": "AUTHORITATIVE",
                "trust_rank": 1,
            },
            {
                "code": "CRM",
                "name": "CRM Cloud",
                "trust_tier": 5,
                "role": "CONTRIBUTING",
                "trust_rank": 2,
            },
        ],
    )
    nominee = add_master_record(
        ctx,
        source_code="ERP",
        natural_key="ERP-CUST-1001",
        attributes={
            "legal_name": "Acme Industrial",
            "tax_id": "TX-77",
            "billing_city": "Austin",
            "contact_email": "ops@acme.test",
        },
        last_verified_at="2026-07-01T00:00:00Z",
    )
    duplicate = add_master_record(
        ctx,
        source_code="CRM",
        natural_key="CRM-CUST-1001",
        attributes={"legal_name": "Acme Ind.", "duns": "D-4410"},
        last_verified_at="2026-06-01T00:00:00Z",
    )
    return ctx, nominee, duplicate


def _weakly_matched_proposal(ctx, nominee, duplicate):
    return add_merge_proposal(
        ctx,
        nominee,
        duplicate,
        name_similarity_pct=60.00,
        key_overlap_pct=50.00,
    )


def test_requesting_changes_tears_down_the_impact_assessment(api):
    """The reviewer steps back and the notice numbers go back to zero.

    Both paths stamp `submitted_at` from the logical clock and then compute `impact_consumer_count`, `required_lead_days` and `earliest_apply_at` from scratch against the *current* consumer set and the *new* `submitted_at` — a resubmission does not reuse the numbers from the first submission.
    In other words, a structural change impacts every active consumer regardless of criticality, whereas a plain reference-value addition impacts only the `TIER1` consumers.
    Sixth — and this ordering is normative — the greater of the base lead and the floor lead is taken *first*, the two surcharges are added to that, and only then is the result capped at thirty days; the capped figure is stored as `required_lead_days`.
    Finally, `earliest_apply_at` is set to `submitted_at` advanced by `required_lead_days` whole days.
    The transition records the acting `X-User-ID` as `reviewer_steward_id`.
    `REQUEST_CHANGES` drives `UNDER_REVIEW → CHANGES_REQUESTED`, stores the `review_note`, clears `reviewer_steward_id` back to null, and resets the impact assessment — `impact_consumer_count` back to 0, `required_lead_days` back to 0 and `earliest_apply_at` back to null — because the next submission will recompute all three.
    The derived boolean `structural` is true for exactly the two non-additive types, `HIERARCHY_RESTRUCTURE` and `CLASSIFICATION_UPLIFT`, and false for `REFERENCE_VALUE_ADD`; it is never supplied by the client.

    Design: Difficulty/non_linear_state_machine/change_request_changes_requested_branch_resets_impact_then_recycles
    """
    ctx, _critical, _secondary = _domain_with_two_consumers()
    request = add_change_request(ctx)

    submitted = validate_success(
        api.submit_change_request(request["id"], ctx["steward_headers"])
    )
    assert submitted["structural"] is False, (
        "a reference value addition is not a structural change, got "
        f"{submitted['structural']}"
    )
    assert submitted["impact_consumer_count"] == 1, (
        "only the critical consumer is impacted by a reference value addition, "
        f"got {submitted['impact_consumer_count']}"
    )
    assert submitted["required_lead_days"] == 10, (
        "the critical consumer's ten days beats the five day floor and earns no "
        f"surcharge, got {submitted['required_lead_days']}"
    )
    assert_instant_equals(
        submitted["submitted_at"], "2026-08-05T00:00:00Z", "submitted_at"
    )
    assert_instant_equals(
        submitted["earliest_apply_at"],
        "2026-08-15T00:00:00Z",
        "earliest_apply_at",
    )

    under_review = validate_success(
        api.review_change_request(request["id"], ctx["owner_headers"])
    )
    assert under_review["reviewer_steward_id"] == ctx["owner"]["id"], (
        "the data owner who picked the request up must be recorded as its "
        f"reviewer, got {under_review['reviewer_steward_id']}"
    )

    bounced = validate_success(
        api.decide_change_request(
            request["id"],
            {
                "decision": "REQUEST_CHANGES",
                "review_note": "Name the affected reference hierarchy explicitly",
            },
            ctx["owner_headers"],
        )
    )

    assert bounced["status"] == "CHANGES_REQUESTED", (
        f"the request must go back to its author, got {bounced['status']}"
    )
    assert bounced["reviewer_steward_id"] is None, (
        "asking for changes releases the reviewer, got "
        f"{bounced['reviewer_steward_id']}"
    )
    assert bounced["impact_consumer_count"] == 0, (
        "the impact assessment must be torn down, got "
        f"{bounced['impact_consumer_count']}"
    )
    assert bounced["required_lead_days"] == 0, (
        f"the notice requirement must be torn down, got {bounced['required_lead_days']}"
    )
    assert bounced["earliest_apply_at"] is None, (
        "the earliest apply instant must be torn down, got "
        f"{bounced['earliest_apply_at']}"
    )
    assert bounced["revision_cycle_count"] == 0, (
        "no revision cycle has been completed until the author resubmits, got "
        f"{bounced['revision_cycle_count']}"
    )


def test_resubmission_counts_the_cycle_and_recomputes_from_the_new_instant(api):
    """The second submission rebuilds the notice window off the later day.

    `DRAFT → SUBMITTED` is the first submission; `CHANGES_REQUESTED → SUBMITTED` is a resubmission after the reviewer asked for revisions, and it differs in exactly one respect — it increments `revision_cycle_count` by one.
    Both paths stamp `submitted_at` from the logical clock and then compute `impact_consumer_count`, `required_lead_days` and `earliest_apply_at` from scratch against the *current* consumer set and the *new* `submitted_at` — a resubmission does not reuse the numbers from the first submission.
    Sixth — and this ordering is normative — the greater of the base lead and the floor lead is taken *first*, the two surcharges are added to that, and only then is the result capped at thirty days; the capped figure is stored as `required_lead_days`.
    Finally, `earliest_apply_at` is set to `submitted_at` advanced by `required_lead_days` whole days.
    `APPROVE` drives `UNDER_REVIEW → APPROVED`, stores the `review_note`, retains `reviewer_steward_id`, and retains the impact assessment as computed; for a structural change it carries one extra precondition — every `ACTIVE` `TIER1` consumer of the domain must already have `lineage_status` `DOCUMENTED`, and if any does not, the approval is refused with `ERR_LINEAGE_INCOMPLETE`.

    Design: Difficulty/non_linear_state_machine/change_request_changes_requested_branch_resets_impact_then_recycles
    """
    ctx, _critical, _secondary = _domain_with_two_consumers()
    request = add_change_request(ctx)
    validate_success(api.submit_change_request(request["id"], ctx["steward_headers"]))
    validate_success(api.review_change_request(request["id"], ctx["owner_headers"]))
    validate_success(
        api.decide_change_request(
            request["id"],
            {
                "decision": "REQUEST_CHANGES",
                "review_note": "Name the affected reference hierarchy explicitly",
            },
            ctx["owner_headers"],
        )
    )

    set_clock("2026-08-06T00:00:00Z")
    resubmitted = validate_success(
        api.submit_change_request(request["id"], ctx["steward_headers"])
    )

    assert resubmitted["status"] == "SUBMITTED", (
        f"a revised request re-enters the review queue, got {resubmitted['status']}"
    )
    assert resubmitted["revision_cycle_count"] == 1, (
        "the resubmission is the request's first revision cycle, got "
        f"{resubmitted['revision_cycle_count']}"
    )
    assert_instant_equals(
        resubmitted["submitted_at"], "2026-08-06T00:00:00Z", "submitted_at"
    )
    assert resubmitted["impact_consumer_count"] == 1, (
        "the impact assessment must be rebuilt over the critical consumer, got "
        f"{resubmitted['impact_consumer_count']}"
    )
    assert resubmitted["required_lead_days"] == 10, (
        f"ten days of notice are required again, got {resubmitted['required_lead_days']}"
    )
    assert_instant_equals(
        resubmitted["earliest_apply_at"],
        "2026-08-16T00:00:00Z",
        "earliest_apply_at",
    )

    validate_success(api.review_change_request(request["id"], ctx["owner_headers"]))
    approved = validate_success(
        api.decide_change_request(
            request["id"],
            {
                "decision": "APPROVE",
                "review_note": "Revised scope approved by the reference data board",
            },
            ctx["owner_headers"],
        )
    )

    assert approved["status"] == "APPROVED", (
        f"the revised request must be approvable, got {approved['status']}"
    )
    assert approved["reviewer_steward_id"] == ctx["owner"]["id"], (
        "approval retains the reviewer who disposed of the request, got "
        f"{approved['reviewer_steward_id']}"
    )
    assert approved["impact_consumer_count"] == 1, (
        "approval retains the impact assessment as computed, got "
        f"{approved['impact_consumer_count']}"
    )
    assert approved["required_lead_days"] == 10, (
        "approval retains the notice requirement as computed, got "
        f"{approved['required_lead_days']}"
    )
    assert_instant_equals(
        approved["earliest_apply_at"],
        "2026-08-16T00:00:00Z",
        "earliest_apply_at",
    )


def test_no_consumer_is_notified_before_the_change_is_scheduled(api):
    """Submitting, bouncing and approving leaves the consumers untouched.

    On success the `status` becomes `SCHEDULED`, `scheduled_apply_at` and the two window boundaries are stored, the domain's `scheduled_change_count` is incremented by one and its `version` advances by one, and the notification fan-out runs: every consumer subscription in the impacted set — determined by exactly the same filter the impact assessment used — has its `pending_change_request_id` set to this request, its `notified_at` stamped from the clock, and its `acknowledged_at` and `acknowledged_revision` cleared to null so that a stale acknowledgement from an earlier notification cannot be mistaken for a fresh one.
    A new subscription begins with `status` `ACTIVE` and `lineage_status` `UNDOCUMENTED`, an empty `lineage_path`, and `lineage_revision`, `lineage_documented_at`, `pending_change_request_id`, `notified_at`, `acknowledged_at`, `acknowledged_revision` and `suspended_reason` all null.

    Design: Difficulty/non_linear_state_machine/change_request_changes_requested_branch_resets_impact_then_recycles
    """
    ctx, critical, secondary = _domain_with_two_consumers()
    request = add_change_request(ctx)
    validate_success(api.submit_change_request(request["id"], ctx["steward_headers"]))
    validate_success(api.review_change_request(request["id"], ctx["owner_headers"]))
    validate_success(
        api.decide_change_request(
            request["id"],
            {
                "decision": "REQUEST_CHANGES",
                "review_note": "Name the affected reference hierarchy explicitly",
            },
            ctx["owner_headers"],
        )
    )
    set_clock("2026-08-06T00:00:00Z")
    validate_success(api.submit_change_request(request["id"], ctx["steward_headers"]))
    validate_success(api.review_change_request(request["id"], ctx["owner_headers"]))
    validate_success(
        api.decide_change_request(
            request["id"],
            {
                "decision": "APPROVE",
                "review_note": "Revised scope approved by the reference data board",
            },
            ctx["owner_headers"],
        )
    )

    critical_after = validate_success(
        api.get_consumer_subscription(critical["id"], GOVERNANCE_ADMIN_HEADERS)
    )
    assert critical_after["pending_change_request_id"] is None, (
        "an approved but unscheduled change has notified nobody, got "
        f"{critical_after['pending_change_request_id']}"
    )
    secondary_after = validate_success(
        api.get_consumer_subscription(secondary["id"], GOVERNANCE_ADMIN_HEADERS)
    )
    assert secondary_after["pending_change_request_id"] is None, (
        "an approved but unscheduled change has notified nobody, got "
        f"{secondary_after['pending_change_request_id']}"
    )


def test_a_low_confidence_proposal_cannot_be_merged_at_all(api):
    """Even a data owner's justification cannot force a low-confidence merge.

    The system first forms a weighted sum of three inputs: five tenths of the `name_similarity_pct`, plus three tenths of the `key_overlap_pct`, plus two tenths of the lesser of the two candidates' `completeness_pct` values as those values stand persisted at the moment of the call.
    That weighted sum is rounded half up to two decimal places.
    When the two candidates come from different source systems no discount applies and the rounded weighted sum stands as the `match_score`.
    The derived `match_confidence` then reads `HIGH` when `match_score` is at least 85.00, `MEDIUM` when it is at least 60.00 but below 85.00, and `LOW` below 60.00.
    And the confidence bar must be met: a `HIGH`-confidence proposal merges freely, a `MEDIUM`-confidence proposal merges only when the data owner supplies an `override_justification` of at least 20 characters, and a `LOW`-confidence proposal cannot be merged at all — the failures in the medium-without-justification and low cases are both `ERR_MATCH_CONFIDENCE_TOO_LOW`.
    A new proposal is created in `status` `PROPOSED` with `reviewer_steward_id`, `effective_survivor_master_record_id`, `survivorship_variant`, `survivorship_field_map`, `override_justification` and `decided_at` all null, `survivor_swapped` false, and `rework_count` at 0.

    Design: Difficulty/non_linear_state_machine/merge_proposal_rework_cycle_upgrades_confidence_on_rescore
    """
    ctx, nominee, duplicate = _domain_with_duplicate_candidates()
    proposal = _weakly_matched_proposal(ctx, nominee, duplicate)

    assert proposal["match_score"] == 53.00, (
        "30.00 plus 15.00 plus 8.00 across two different source systems must "
        f"give a match score of 53.00, got {proposal['match_score']}"
    )
    assert proposal["match_confidence"] == "LOW", (
        f"a 53.00 match score must read LOW, got {proposal['match_confidence']}"
    )
    assert proposal["rework_count"] == 0, (
        f"a fresh proposal has been through no loops, got {proposal['rework_count']}"
    )

    response = api.decide_merge_proposal(
        proposal["id"],
        {
            "decision": "MERGE",
            "override_justification": (
                "Manual review of both records confirms a single legal entity"
            ),
        },
        ctx["owner_headers"],
    )
    validate_error(response, "ERR_MATCH_CONFIDENCE_TOO_LOW")


def test_rework_bounces_the_proposal_and_releases_its_reviewer(api):
    """A bounced proposal is not decided, so nothing about it is stamped.

    `REWORK` drives `UNDER_REVIEW → REWORK`, requires a `rework_note` of at least 10 characters, clears `reviewer_steward_id` back to null, and deliberately leaves `decided_at` null because the proposal is not decided — it is bounced.
    On success `match_score` and `match_confidence` are recomputed from the new percentages by exactly the formula above, including the intra-source discount and the 45.00 floor, the `status` returns to `PROPOSED`, and `rework_count` is incremented by one so the audit trail records how many loops the proposal has been through.

    Design: Difficulty/non_linear_state_machine/merge_proposal_rework_cycle_upgrades_confidence_on_rescore
    """
    ctx, nominee, duplicate = _domain_with_duplicate_candidates()
    proposal = _weakly_matched_proposal(ctx, nominee, duplicate)

    bounced = validate_success(
        api.decide_merge_proposal(
            proposal["id"],
            {
                "decision": "REWORK",
                "rework_note": "Re-run the matching engine with the tax id block",
            },
            ctx["owner_headers"],
        )
    )

    assert bounced["status"] == "REWORK", (
        f"a bounced proposal must sit in REWORK, got {bounced['status']}"
    )
    assert bounced["reviewer_steward_id"] is None, (
        f"bouncing releases the reviewer, got {bounced['reviewer_steward_id']}"
    )
    assert bounced["decided_at"] is None, (
        f"a bounced proposal is not decided, got {bounced['decided_at']}"
    )
    assert bounced["rework_count"] == 0, (
        "the loop is only counted when the proposal is rescored, got "
        f"{bounced['rework_count']}"
    )


def test_rescoring_lifts_the_confidence_and_counts_the_loop(api):
    """Fresh matching percentages take the proposal back to a mergeable state.

    Rescoring drives `REWORK → PROPOSED` and takes fresh `name_similarity_pct` and `key_overlap_pct` values from the matching engine.
    On success `match_score` and `match_confidence` are recomputed from the new percentages by exactly the formula above, including the intra-source discount and the 45.00 floor, the `status` returns to `PROPOSED`, and `rework_count` is incremented by one so the audit trail records how many loops the proposal has been through.
    The system first forms a weighted sum of three inputs: five tenths of the `name_similarity_pct`, plus three tenths of the `key_overlap_pct`, plus two tenths of the lesser of the two candidates' `completeness_pct` values as those values stand persisted at the moment of the call.
    The derived `match_confidence` then reads `HIGH` when `match_score` is at least 85.00, `MEDIUM` when it is at least 60.00 but below 85.00, and `LOW` below 60.00.

    Design: Difficulty/non_linear_state_machine/merge_proposal_rework_cycle_upgrades_confidence_on_rescore
    """
    ctx, nominee, duplicate = _domain_with_duplicate_candidates()
    proposal = _weakly_matched_proposal(ctx, nominee, duplicate)
    validate_success(
        api.decide_merge_proposal(
            proposal["id"],
            {
                "decision": "REWORK",
                "rework_note": "Re-run the matching engine with the tax id block",
            },
            ctx["owner_headers"],
        )
    )

    rescored = validate_success(
        api.rescore_merge_proposal(
            proposal["id"],
            {"name_similarity_pct": 95.00, "key_overlap_pct": 90.00},
            ctx["steward_headers"],
        )
    )

    assert rescored["status"] == "PROPOSED", (
        f"a rescored proposal rejoins the review queue, got {rescored['status']}"
    )
    assert rescored["match_score"] == 82.50, (
        "47.50 plus 27.00 plus 8.00 must give a match score of 82.50, got "
        f"{rescored['match_score']}"
    )
    assert rescored["match_confidence"] == "MEDIUM", (
        f"an 82.50 match score must read MEDIUM, got {rescored['match_confidence']}"
    )
    assert rescored["rework_count"] == 1, (
        "rescoring records that the proposal has been round the loop once, got "
        f"{rescored['rework_count']}"
    )


def test_only_the_rescored_second_pass_completes_the_merge(api):
    """The loop ends with the nominated authoritative record as the golden row.

    And the confidence bar must be met: a `HIGH`-confidence proposal merges freely, a `MEDIUM`-confidence proposal merges only when the data owner supplies an `override_justification` of at least 20 characters, and a `LOW`-confidence proposal cannot be merged at all — the failures in the medium-without-justification and low cases are both `ERR_MATCH_CONFIDENCE_TOO_LOW`.
    The **source-priority** variant applies when exactly one of the two candidates was contributed by the source system behind the domain's `AUTHORITATIVE` registration that is `ACTIVE` at decision time.
    Whichever variant ran is recorded as `survivorship_variant`, the chosen record's identifier is recorded as `effective_survivor_master_record_id`, and `survivor_swapped` is set true exactly when that identifier differs from the `survivor_master_record_id` the proposer originally nominated.
    The survivor's `last_verified_at` is set to the later of the two records' values, and its `completeness_pct` and `survivorship_score` are both recomputed against the enriched attribute set.
    **Hop 3**, caused by hop 2's absorption of the loser, drives the loser's `curation_status` to `MERGED_AWAY` and writes the effective survivor's identifier into the loser's `superseded_by_master_record_id`; if the loser was `PUBLISHED` its `publication_status` becomes `RETRACTED` and the domain's `published_master_record_count` is decremented by one.
    On success `match_score` and `match_confidence` are recomputed from the new percentages by exactly the formula above, including the intra-source discount and the 45.00 floor, the `status` returns to `PROPOSED`, and `rework_count` is incremented by one so the audit trail records how many loops the proposal has been through.

    Design: Difficulty/non_linear_state_machine/merge_proposal_rework_cycle_upgrades_confidence_on_rescore
    """
    ctx, nominee, duplicate = _domain_with_duplicate_candidates()
    proposal = _weakly_matched_proposal(ctx, nominee, duplicate)
    validate_success(
        api.decide_merge_proposal(
            proposal["id"],
            {
                "decision": "REWORK",
                "rework_note": "Re-run the matching engine with the tax id block",
            },
            ctx["owner_headers"],
        )
    )
    validate_success(
        api.rescore_merge_proposal(
            proposal["id"],
            {"name_similarity_pct": 95.00, "key_overlap_pct": 90.00},
            ctx["steward_headers"],
        )
    )
    validate_success(
        api.review_merge_proposal(proposal["id"], ctx["steward_headers"])
    )

    merged = validate_success(
        api.decide_merge_proposal(
            proposal["id"],
            {
                "decision": "MERGE",
                "override_justification": (
                    "Manual review of both records confirms a single legal entity"
                ),
            },
            ctx["owner_headers"],
        )
    )

    assert merged["status"] == "MERGED", (
        f"the rescored proposal must now merge, got {merged['status']}"
    )
    assert merged["rework_count"] == 1, (
        "the merge must preserve the single loop the audit trail recorded, got "
        f"{merged['rework_count']}"
    )
    assert merged["effective_survivor_master_record_id"] == nominee["id"], (
        "the authoritative ERP candidate must survive, got "
        f"{merged['effective_survivor_master_record_id']}"
    )
    assert merged["survivor_swapped"] is False, (
        "the system upheld the proposer's nomination, got "
        f"{merged['survivor_swapped']}"
    )

    survivor = validate_success(
        api.get_master_record(nominee["id"], GOVERNANCE_ADMIN_HEADERS)
    )
    assert survivor["completeness_pct"] == 100.00, (
        "the survivor gains the DUNS key it lacked and must read 100.00, got "
        f"{survivor['completeness_pct']}"
    )
    assert survivor["survivorship_score"] == 96.00, (
        "a tier-4 record fully complete and one whole month stale must score "
        f"96.00, got {survivor['survivorship_score']}"
    )

    loser = validate_success(
        api.get_master_record(duplicate["id"], GOVERNANCE_ADMIN_HEADERS)
    )
    assert loser["curation_status"] == "MERGED_AWAY", (
        f"the absorbed record must be merged away, got {loser['curation_status']}"
    )
