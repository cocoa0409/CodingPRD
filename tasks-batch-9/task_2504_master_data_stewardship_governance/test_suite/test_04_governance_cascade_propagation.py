"""Single requests whose consequences travel several entities downstream.

Decertifying a source system revokes its registrations, freezes the domains
left without an authoritative source, quarantines their published records and
stales the lineage their consumers documented. Applying a classification uplift
raises the domain's classification, suspends the consumers that fall below it,
and re-assesses the change requests still waiting on the shrunken consumer set.
"""

from test_helpers import (
    GOVERNANCE_ADMIN_HEADERS,
    acknowledge_subscription,
    add_change_request,
    add_consumer_subscription,
    add_master_record,
    assert_instant_equals,
    read_domain,
    set_clock,
    setup_governed_domain,
    validate_success,
)


def _domain_with_published_record_and_documented_consumer():
    """A live open domain publishing one record and feeding one critical consumer."""
    ctx = setup_governed_domain()
    consumer = add_consumer_subscription(ctx, document_lineage=True)
    record = add_master_record(ctx, source_code="ERP", curate=True, publish=True)
    return ctx, consumer, record


def _domain_awaiting_a_classification_uplift():
    """A scheduled uplift to RESTRICTED, one acknowledged under-cleared critical
    consumer, one sufficiently cleared secondary consumer, and a second change
    request still sitting in the review queue."""
    ctx = setup_governed_domain()
    critical = add_consumer_subscription(ctx, document_lineage=True)
    secondary = add_consumer_subscription(
        ctx,
        consumer_code="BI_CUSTOMER_SUMMARY",
        reporting_asset_key="RPT_CUST_SUMMARY",
        clearance_level="RESTRICTED",
        criticality="TIER2",
        required_lead_days=3,
    )
    uplift = add_change_request(
        ctx,
        stage="SCHEDULED",
        scheduled_apply_at="2026-08-15T00:00:00Z",
        change_type="CLASSIFICATION_UPLIFT",
        title="Uplift customer master to RESTRICTED",
        proposed_values={"target_classification_level": "RESTRICTED"},
        review_note="Sensitive handling controls approved by the governance board",
    )
    reference_addition = add_change_request(ctx, stage="SUBMITTED")
    acknowledged = acknowledge_subscription(critical)
    return ctx, uplift, reference_addition, critical, secondary, acknowledged


def test_decertification_revokes_the_registration_and_freezes_the_domain(api):
    """Losing the certified source strips the domain of its authoritative pointer.

    **Hop 1** moves the source system `CERTIFIED → DECERTIFIED`, stamps `decertified_at` from the clock, and stores the supplied reason as `decertification_reason`.
    **Hop 2**, caused by hop 1, drives every `SourceRegistration` on that system whose `status` is `ACTIVE` from `ACTIVE` to `REVOKED`, writing the literal string `SOURCE_DECERTIFIED` into each one's `revoked_reason`.
    **Hop 3**, caused by hop 2, visits every domain that is thereby left holding no `ACTIVE` `AUTHORITATIVE` registration, sets that domain's `authoritative_source_code` to null, and recomputes `governance_posture` — which necessarily yields `FROZEN`, since absence of an active authoritative registration is itself a freezing condition.
    Posture evolves independently of the domain's own `status` dimension.

    Design: Difficulty/transitive_cascade/source_decertification_five_hop_cascade_to_consumer_lineage
    """
    ctx, _consumer, _record = _domain_with_published_record_and_documented_consumer()
    before = read_domain(ctx["domain"]["id"])
    assert before["governance_posture"] == "OPEN", (
        "a live domain with a certified authoritative source and no quality "
        f"debt is open, got {before['governance_posture']}"
    )
    assert before["authoritative_source_code"] == "ERP", (
        "the domain's authoritative pointer must name the ERP source, got "
        f"{before['authoritative_source_code']}"
    )

    validate_success(
        api.decertify_source_system(
            ctx["sources"]["ERP"]["id"],
            {"reason": "Source retired following the finance platform migration"},
            GOVERNANCE_ADMIN_HEADERS,
        )
    )

    source = validate_success(
        api.get_source_system(ctx["sources"]["ERP"]["id"], GOVERNANCE_ADMIN_HEADERS)
    )
    assert source["status"] == "DECERTIFIED", (
        f"the decertified source must leave CERTIFIED, got {source['status']}"
    )
    assert_instant_equals(
        source["decertified_at"], "2026-08-05T00:00:00Z", "decertified_at"
    )

    registration = validate_success(
        api.get_source_registration(
            ctx["registrations"]["ERP"]["id"], GOVERNANCE_ADMIN_HEADERS
        )
    )
    assert registration["status"] == "REVOKED", (
        "an active registration on a decertified system must be revoked rather "
        f"than superseded, got {registration['status']}"
    )
    assert registration["revoked_reason"] == "SOURCE_DECERTIFIED", (
        "the revocation must record that the source lost its certification, got "
        f"{registration['revoked_reason']}"
    )

    domain = read_domain(ctx["domain"]["id"])
    assert domain["governance_posture"] == "FROZEN", (
        "a domain with no active authoritative registration must freeze, got "
        f"{domain['governance_posture']}"
    )
    assert domain["authoritative_source_code"] is None, (
        "the domain's authoritative pointer must be cleared, got "
        f"{domain['authoritative_source_code']}"
    )
    assert domain["status"] == "ACTIVE", (
        "posture moves independently of the domain's own status, which must "
        f"stay ACTIVE, got {domain['status']}"
    )


def test_decertification_retracts_and_quarantines_the_published_record(api):
    """The golden record cannot stay published once its source is discredited.

    **Hop 4**, caused by hop 3's freeze, takes every master record of those domains whose `publication_status` is `PUBLISHED` and drives it to `publication_status` `RETRACTED` and `curation_status` `QUARANTINED`, writing the literal string `AUTHORITATIVE_SOURCE_LOST` into each record's `quarantine_reason`; because the entire published set is retracted, the domain's `published_master_record_count` lands at 0.
    `Domain.published_master_record_count` is the exact integer count of the domain's master records whose `publication_status` is `PUBLISHED`.

    Design: Difficulty/transitive_cascade/source_decertification_five_hop_cascade_to_consumer_lineage
    """
    ctx, _consumer, record = _domain_with_published_record_and_documented_consumer()
    before = read_domain(ctx["domain"]["id"])
    assert before["published_master_record_count"] == 1, (
        "the domain must be publishing exactly one record before the cascade, "
        f"got {before['published_master_record_count']}"
    )
    assert record["completeness_pct"] == 80.00, (
        "four populated keys against an expected five must read 80.00, got "
        f"{record['completeness_pct']}"
    )

    validate_success(
        api.decertify_source_system(
            ctx["sources"]["ERP"]["id"],
            {"reason": "Source retired following the finance platform migration"},
            GOVERNANCE_ADMIN_HEADERS,
        )
    )

    after = validate_success(
        api.get_master_record(record["id"], GOVERNANCE_ADMIN_HEADERS)
    )
    assert after["publication_status"] == "RETRACTED", (
        "the published record must be pulled back from downstream, got "
        f"{after['publication_status']}"
    )
    assert after["curation_status"] == "QUARANTINED", (
        "the record must be quarantined on the curation dimension, got "
        f"{after['curation_status']}"
    )
    assert after["quarantine_reason"] == "AUTHORITATIVE_SOURCE_LOST", (
        "the quarantine must record that the authoritative source was lost, got "
        f"{after['quarantine_reason']}"
    )

    domain = read_domain(ctx["domain"]["id"])
    assert domain["published_master_record_count"] == 0, (
        "retracting the whole published set must leave the count at 0, got "
        f"{domain['published_master_record_count']}"
    )


def test_decertification_stales_documented_lineage_without_suspending_it(api):
    """A documented flow whose first node is gone is no longer truthful.

    **Hop 5**, caused by hop 4's retraction of the published set, takes every consumer subscription of those domains that is still `ACTIVE` and whose `lineage_status` is `DOCUMENTED` and moves it to `lineage_status` `STALE`, on the grounds that a documented flow whose first node no longer exists is no longer a truthful description.
    The subscription row, like the master record, runs two independent dimensions.
    `status` moves `ACTIVE → SUSPENDED` when a classification uplift leaves the consumer under-cleared, and `lineage_status` moves independently among `UNDOCUMENTED`, `DOCUMENTED` and `STALE`.

    Design: Difficulty/transitive_cascade/source_decertification_five_hop_cascade_to_consumer_lineage
    """
    ctx, consumer, _record = _domain_with_published_record_and_documented_consumer()
    assert consumer["lineage_status"] == "DOCUMENTED", (
        "the consumer's lineage must be documented before the cascade, got "
        f"{consumer['lineage_status']}"
    )
    assert consumer["lineage_revision"] == 0, (
        "lineage documented against an unchanged domain captures revision 0, "
        f"got {consumer['lineage_revision']}"
    )

    validate_success(
        api.decertify_source_system(
            ctx["sources"]["ERP"]["id"],
            {"reason": "Source retired following the finance platform migration"},
            GOVERNANCE_ADMIN_HEADERS,
        )
    )

    after = validate_success(
        api.get_consumer_subscription(consumer["id"], GOVERNANCE_ADMIN_HEADERS)
    )
    assert after["lineage_status"] == "STALE", (
        "losing the authoritative source must stale the documented lineage, got "
        f"{after['lineage_status']}"
    )
    assert after["status"] == "ACTIVE", (
        "staling lineage is not a suspension, so the subscription must remain "
        f"ACTIVE, got {after['status']}"
    )


def test_applying_the_uplift_raises_the_classification_and_the_revision(api):
    """Hop one lands the new classification and releases the change calendar.

    Third, a floor lead time is taken as the domain's `notification_lead_days_floor` when at least one consumer is impacted, and zero when none is.
    In other words, a structural change impacts every active consumer regardless of criticality, whereas a plain reference-value addition impacts only the `TIER1` consumers.
    Finally, `earliest_apply_at` is set to `submitted_at` advanced by `required_lead_days` whole days.
    The freeze window is a closed interval around that instant whose extent depends on whether the change is structural: a structural change reserves 24 hours of lead before the instant and 48 hours of trail after it, while a non-structural change reserves no lead at all and 12 hours of trail.
    On success `acknowledged_at` is stamped from the logical clock and `acknowledged_revision` captures the domain's `reference_data_revision` at acknowledgement time, giving an auditable record of exactly which revision of the reference data the consumer signed off against.
    **Hop 1** sets `status` to `APPLIED`, stamps `applied_at` from the clock, increments the domain's `reference_data_revision` by one, decrements the domain's `scheduled_change_count` by one, releases the freeze window by setting both `freeze_window_start` and `freeze_window_end` to null, and advances the domain's `version` by one; when the `change_type` is `CLASSIFICATION_UPLIFT` it additionally writes the payload's `target_classification_level` into the domain's `classification_level` and recomputes `sensitive_handling_required` from the new level.

    Design: Difficulty/transitive_cascade/classification_uplift_apply_three_hop_impact_reassessment
    """
    (
        ctx,
        uplift,
        _reference_addition,
        _critical,
        _secondary,
        acknowledged,
    ) = _domain_awaiting_a_classification_uplift()

    assert uplift["structural"] is True, (
        f"a classification uplift is a structural change, got {uplift['structural']}"
    )
    assert uplift["impact_consumer_count"] == 2, (
        "a structural change impacts both active consumers regardless of "
        f"criticality, got {uplift['impact_consumer_count']}"
    )
    assert uplift["required_lead_days"] == 10, (
        "the ten day critical requirement beats the five day floor and earns no "
        f"surcharge below three impacted consumers, got {uplift['required_lead_days']}"
    )
    assert_instant_equals(
        uplift["earliest_apply_at"], "2026-08-15T00:00:00Z", "earliest_apply_at"
    )
    assert_instant_equals(
        uplift["freeze_window_start"],
        "2026-08-14T00:00:00Z",
        "freeze_window_start",
    )
    assert_instant_equals(
        uplift["freeze_window_end"], "2026-08-17T00:00:00Z", "freeze_window_end"
    )
    assert_instant_equals(
        acknowledged["acknowledged_at"], "2026-08-05T00:00:00Z", "acknowledged_at"
    )
    assert acknowledged["acknowledged_revision"] == 0, (
        "the consumer signed off against the domain's revision 0, got "
        f"{acknowledged['acknowledged_revision']}"
    )

    set_clock("2026-08-15T00:00:00Z")
    applied = validate_success(
        api.apply_change_request(uplift["id"], GOVERNANCE_ADMIN_HEADERS)
    )

    assert applied["status"] == "APPLIED", (
        f"the scheduled uplift must land, got {applied['status']}"
    )
    assert_instant_equals(applied["applied_at"], "2026-08-15T00:00:00Z", "applied_at")
    assert applied["freeze_window_start"] is None, (
        "applying releases the freeze window, got "
        f"{applied['freeze_window_start']}"
    )
    assert applied["freeze_window_end"] is None, (
        f"applying releases the freeze window, got {applied['freeze_window_end']}"
    )

    domain = read_domain(ctx["domain"]["id"])
    assert domain["classification_level"] == "RESTRICTED", (
        "the uplift must write its target classification onto the domain, got "
        f"{domain['classification_level']}"
    )
    assert domain["sensitive_handling_required"] is True, (
        "a restricted domain requires sensitive handling, got "
        f"{domain['sensitive_handling_required']}"
    )
    assert domain["reference_data_revision"] == 1, (
        "the domain's first applied change advances the reference data revision "
        f"to 1, got {domain['reference_data_revision']}"
    )
    assert domain["scheduled_change_count"] == 0, (
        "the applied request no longer occupies the change calendar, got "
        f"{domain['scheduled_change_count']}"
    )


def test_the_uplift_suspends_the_consumer_it_leaves_under_cleared(api):
    """Hop two suspends the internal consumer and spares the restricted one.

    **Hop 2**, caused by hop 1's new classification, takes every `ACTIVE` consumer subscription of the domain whose `clearance_level` rank has fallen below the new `classification_level` rank and drives it `ACTIVE → SUSPENDED`, writing the literal string `CLEARANCE_BELOW_CLASSIFICATION` into its `suspended_reason` and clearing its `pending_change_request_id`, `notified_at` and `acknowledged_at` to null.
    Two further effects complete the apply: every consumer subscription of the domain whose `lineage_status` is `DOCUMENTED` and whose `lineage_revision` is lower than the domain's new `reference_data_revision` is moved to `lineage_status` `STALE`, and every subscription still `ACTIVE` that was notified about this request has its `pending_change_request_id`, `notified_at` and `acknowledged_at` cleared to null now that the change has landed.
    Suspension never clears documented lineage, and re-documenting lineage never un-suspends a subscription.

    Design: Difficulty/transitive_cascade/classification_uplift_apply_three_hop_impact_reassessment
    """
    (
        ctx,
        uplift,
        _reference_addition,
        critical,
        secondary,
        _acknowledged,
    ) = _domain_awaiting_a_classification_uplift()

    set_clock("2026-08-15T00:00:00Z")
    validate_success(api.apply_change_request(uplift["id"], GOVERNANCE_ADMIN_HEADERS))

    critical_after = validate_success(
        api.get_consumer_subscription(critical["id"], GOVERNANCE_ADMIN_HEADERS)
    )
    assert critical_after["status"] == "SUSPENDED", (
        "an internally cleared consumer cannot keep consuming a restricted "
        f"domain, got {critical_after['status']}"
    )
    assert critical_after["suspended_reason"] == "CLEARANCE_BELOW_CLASSIFICATION", (
        "the suspension must record the clearance shortfall, got "
        f"{critical_after['suspended_reason']}"
    )
    assert critical_after["lineage_status"] == "STALE", (
        "lineage documented against revision 0 goes stale once the domain "
        f"reaches revision 1, got {critical_after['lineage_status']}"
    )
    assert critical_after["pending_change_request_id"] is None, (
        "the landed change leaves no pending notification, got "
        f"{critical_after['pending_change_request_id']}"
    )

    secondary_after = validate_success(
        api.get_consumer_subscription(secondary["id"], GOVERNANCE_ADMIN_HEADERS)
    )
    assert secondary_after["status"] == "ACTIVE", (
        "a consumer cleared to the new classification must keep consuming, got "
        f"{secondary_after['status']}"
    )
    assert secondary_after["pending_change_request_id"] is None, (
        "the landed change leaves no pending notification, got "
        f"{secondary_after['pending_change_request_id']}"
    )


def test_the_uplift_reassesses_the_change_request_left_in_the_queue(api):
    """Hop three re-runs the sibling request's impact over the survivors.

    **Hop 3**, caused by hop 2 having shrunk the active consumer set, revisits every other change request of the domain whose `status` is `SUBMITTED` or `UNDER_REVIEW` and recomputes its `impact_consumer_count`, `required_lead_days` and `earliest_apply_at` against the surviving active consumer set — each such request keeping its own `submitted_at` as the base for the recomputed `earliest_apply_at`.
    In other words, a structural change impacts every active consumer regardless of criticality, whereas a plain reference-value addition impacts only the `TIER1` consumers.
    Second, a base lead time is taken as the largest `required_lead_days` among the impacted consumers, or zero when the impacted set is empty.
    Third, a floor lead time is taken as the domain's `notification_lead_days_floor` when at least one consumer is impacted, and zero when none is.
    Fifth, a classification surcharge of two extra days applies when the domain's `classification_level` is `CONFIDENTIAL` or `RESTRICTED`, and none otherwise.
    Sixth — and this ordering is normative — the greater of the base lead and the floor lead is taken *first*, the two surcharges are added to that, and only then is the result capped at thirty days; the capped figure is stored as `required_lead_days`.
    Finally, `earliest_apply_at` is set to `submitted_at` advanced by `required_lead_days` whole days.

    Design: Difficulty/transitive_cascade/classification_uplift_apply_three_hop_impact_reassessment
    """
    (
        _ctx,
        uplift,
        reference_addition,
        _critical,
        _secondary,
        _acknowledged,
    ) = _domain_awaiting_a_classification_uplift()

    assert reference_addition["impact_consumer_count"] == 1, (
        "before the uplift the reference addition impacts the one critical "
        f"consumer, got {reference_addition['impact_consumer_count']}"
    )
    assert reference_addition["required_lead_days"] == 10, (
        "before the uplift the critical consumer's ten days govern, got "
        f"{reference_addition['required_lead_days']}"
    )
    assert_instant_equals(
        reference_addition["earliest_apply_at"],
        "2026-08-15T00:00:00Z",
        "earliest_apply_at",
    )

    set_clock("2026-08-15T00:00:00Z")
    validate_success(api.apply_change_request(uplift["id"], GOVERNANCE_ADMIN_HEADERS))

    after = validate_success(
        api.get_change_request(reference_addition["id"], GOVERNANCE_ADMIN_HEADERS)
    )
    assert after["status"] == "SUBMITTED", (
        "re-assessment does not move the request through its lifecycle, got "
        f"{after['status']}"
    )
    assert_instant_equals(
        after["submitted_at"],
        "2026-08-05T00:00:00Z",
        "the re-assessed request's submitted_at",
    )
    assert after["impact_consumer_count"] == 0, (
        "with the only critical consumer suspended a reference addition impacts "
        f"nobody, got {after['impact_consumer_count']}"
    )
    assert after["required_lead_days"] == 2, (
        "an empty impacted set means no base lead and no floor, leaving only the "
        f"two day restricted classification surcharge, got {after['required_lead_days']}"
    )
    assert_instant_equals(
        after["earliest_apply_at"],
        "2026-08-07T00:00:00Z",
        "the re-assessed earliest_apply_at",
    )
