"""Layered governance flows: concurrency anchors, counters and same-response state.

Three behaviours are exercised here, each of which spans several moving parts of
one request. The domain row is the concurrency anchor for the whole governance
graph, so a version-checked registration must refuse a caller whose picture of
the authoritative designation is out of date and must accept the very same body
once the caller re-reads the anchor. The published-record counter must stay
reconciled with the collection it summarises across ingestion, publication and
the indirect retraction a merge decision forces. And a mutating response must
already report the posture the request moved the domain to, so a client never
needs a follow-up read to learn it — and the follow-up read must agree exactly.
"""

import pytest

from test_helpers import (
    AUDITOR_HEADERS,
    GOVERNANCE_ADMIN_HEADERS,
    add_master_record,
    create_domain,
    create_source_system,
    domain_version,
    is_iso8601_timestamp,
    merge_proposal_payload,
    read_domain,
    refresh_domain,
    run_scorecard,
    set_clock,
    setup_governed_domain,
    source_registration_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

FIVE_ATTRIBUTES_A = {
    "legal_name": "Mu Co",
    "tax_id": "TX-15",
    "billing_city": "Meridian",
    "contact_email": "a@mu.test",
    "duns": "15-150",
}
FIVE_ATTRIBUTES_B = {
    "legal_name": "Mu Co",
    "tax_id": "TX-15",
    "billing_city": "Meridian",
    "contact_email": "b@mu.test",
    "duns": "15-150",
}


# ---------------------------------------------------------------------------
# The domain version is the concurrency anchor for a source registration
# ---------------------------------------------------------------------------


def _domain_with_two_certified_sources(api):
    """A DRAFT domain plus two certified source systems, ERP and CRM."""
    set_clock("2026-08-01T00:00:00Z")
    domain = create_domain()
    erp = create_source_system(code="ERP", name="ERP Core", trust_tier=4)
    crm = create_source_system(code="CRM", name="CRM Cloud", trust_tier=5)
    assert domain["version"] == 1, (
        f"a newly defined domain starts at version 1, got {domain['version']}"
    )
    return domain, erp, crm


def test_authoritative_registration_refuses_an_anchor_an_accepted_write_moved(api):
    """PRD §2.5: "Creating a source registration requires a non-optional
    `expected_domain_version` field in the request body, carrying the client's
    last observed `version` of the target `Domain`. If that value does not equal
    the domain's current `version`, the create is rejected with
    `ERR_STALE_DOMAIN_VERSION` (HTTP 412)."
    PRD §2.5: "A single request that creates a source registration, flips the
    posture from `FROZEN` to `OPEN` and rewrites `authoritative_source_code`
    therefore moves the version from N to N+1, not to N+3."

    Design: Corner/complexity_layers/authoritative_registration_rejects_a_stale_domain_version
    """
    domain, erp, crm = _domain_with_two_certified_sources(api)
    remembered_version = domain["version"]

    accepted = validate_success(
        api.create_source_registration(
            source_registration_payload(
                domain["id"],
                erp["id"],
                remembered_version,
                role="AUTHORITATIVE",
                trust_rank=1,
                effective_from="2026-08-01T00:00:00Z",
            ),
            GOVERNANCE_ADMIN_HEADERS,
        ),
        201,
    )
    assert accepted["status"] == "ACTIVE", (
        f"a new registration is created ACTIVE, got {accepted['status']}"
    )

    after_accepted = read_domain(domain["id"])
    assert after_accepted["version"] == remembered_version + 1, (
        "the accepted registration must move the anchor exactly one step, from "
        f"{remembered_version} to {remembered_version + 1}, got "
        f"{after_accepted['version']}"
    )
    assert after_accepted["governance_posture"] == "OPEN", (
        "designating a certified authoritative source with no open findings "
        f"leaves the domain OPEN, got {after_accepted['governance_posture']}"
    )
    assert after_accepted["authoritative_source_code"] == "ERP", (
        "the authoritative pointer must name the newly registered source, got "
        f"{after_accepted['authoritative_source_code']!r}"
    )

    stale = api.create_source_registration(
        source_registration_payload(
            domain["id"],
            crm["id"],
            remembered_version,
            role="AUTHORITATIVE",
            trust_rank=1,
            effective_from="2026-08-03T00:00:00Z",
        ),
        GOVERNANCE_ADMIN_HEADERS,
    )
    validate_error(stale, "ERR_STALE_DOMAIN_VERSION")

    registrations, meta = validate_paginated(
        api.list_source_registrations(
            GOVERNANCE_ADMIN_HEADERS, params={"domain_id": domain["id"]}
        )
    )
    assert meta["total_count"] == 1, (
        "the refused registration must not have been recorded; expected only the "
        f"accepted one, got {meta['total_count']}"
    )
    assert read_domain(domain["id"])["version"] == remembered_version + 1, (
        "a request that mutates nothing must leave the anchor untouched"
    )


def test_authoritative_registration_supersedes_the_incumbent_on_a_fresh_anchor(api):
    """PRD §2.5: "Because cascades make the exact number of intervening bumps
    hard for a client to predict, any client about to perform a version-checked
    write should read the domain immediately beforehand and send back the value
    it just observed."
    PRD §3.2: "When an incoming registration declares `role` of `AUTHORITATIVE`
    for a domain that already holds an `ACTIVE` `AUTHORITATIVE` registration,
    the incumbent moves `ACTIVE → SUPERSEDED`: its `superseded_at` is stamped
    from the clock and its `effective_to` is back-filled to the incoming
    registration's `effective_from`, so the two intervals abut without a gap."
    PRD §3.2: "The domain's `authoritative_source_code` is then rewritten to the
    `code` of the incoming registration's source system, and the domain's
    `governance_posture` is recomputed — which is how designating a certified
    authoritative source can lift a domain out of `FROZEN` in a single request."

    Design: Corner/complexity_layers/authoritative_registration_rejects_a_stale_domain_version
    """
    domain, erp, crm = _domain_with_two_certified_sources(api)
    remembered_version = domain["version"]

    incumbent = validate_success(
        api.create_source_registration(
            source_registration_payload(
                domain["id"],
                erp["id"],
                remembered_version,
                role="AUTHORITATIVE",
                trust_rank=1,
                effective_from="2026-08-01T00:00:00Z",
            ),
            GOVERNANCE_ADMIN_HEADERS,
        ),
        201,
    )

    stale = api.create_source_registration(
        source_registration_payload(
            domain["id"],
            crm["id"],
            remembered_version,
            role="AUTHORITATIVE",
            trust_rank=1,
            effective_from="2026-08-03T00:00:00Z",
        ),
        GOVERNANCE_ADMIN_HEADERS,
    )
    validate_error(stale, "ERR_STALE_DOMAIN_VERSION")

    fresh_version = domain_version(domain["id"])
    retried = validate_success(
        api.create_source_registration(
            source_registration_payload(
                domain["id"],
                crm["id"],
                fresh_version,
                role="AUTHORITATIVE",
                trust_rank=1,
                effective_from="2026-08-03T00:00:00Z",
            ),
            GOVERNANCE_ADMIN_HEADERS,
        ),
        201,
    )
    assert retried["role"] == "AUTHORITATIVE", (
        f"the retried registration keeps its declared role, got {retried['role']}"
    )
    assert retried["status"] == "ACTIVE", (
        f"the retried registration is created ACTIVE, got {retried['status']}"
    )

    superseded = validate_success(
        api.get_source_registration(incumbent["id"], AUDITOR_HEADERS)
    )
    assert superseded["status"] == "SUPERSEDED", (
        "the incumbent authoritative registration must step aside, got "
        f"{superseded['status']}"
    )
    assert is_iso8601_timestamp(superseded["superseded_at"]), (
        "the incumbent's superseded_at must be stamped from the clock, got "
        f"{superseded['superseded_at']!r}"
    )

    final = read_domain(domain["id"])
    assert final["authoritative_source_code"] == "CRM", (
        "the authoritative pointer must be rewritten to the incoming source, got "
        f"{final['authoritative_source_code']!r}"
    )
    assert final["version"] == fresh_version + 1, (
        "the accepted retry must move the anchor exactly one step, from "
        f"{fresh_version} to {fresh_version + 1}, got {final['version']}"
    )


# ---------------------------------------------------------------------------
# The published-record counter stays reconciled with its collection
# ---------------------------------------------------------------------------


def _domain_with_two_curated_records(api):
    """An OPEN active domain carrying two fully populated curated ERP records."""
    ctx = setup_governed_domain()
    assert ctx["domain"]["status"] == "ACTIVE", (
        f"publication requires an active domain, got {ctx['domain']['status']}"
    )
    assert ctx["domain"]["governance_posture"] == "OPEN", (
        "publication requires an open posture, got "
        f"{ctx['domain']['governance_posture']}"
    )
    first = add_master_record(
        ctx,
        natural_key="CUST-A",
        attributes=FIVE_ATTRIBUTES_A,
        last_verified_at="2026-08-01T00:00:00Z",
    )
    second = add_master_record(
        ctx,
        natural_key="CUST-B",
        attributes=FIVE_ATTRIBUTES_B,
        last_verified_at="2026-08-01T00:00:00Z",
    )
    return ctx, first, second


def test_published_record_counter_counts_only_records_actually_released(api):
    """PRD §2.8: "`Domain.published_master_record_count` is the exact integer
    count of the domain's master records whose `publication_status` is
    `PUBLISHED`."
    PRD §3.6: "A newly ingested record begins with `curation_status` `CANDIDATE`
    and `publication_status` `UNPUBLISHED`, and with
    `superseded_by_master_record_id`, `published_at` and `quarantine_reason` all
    null."
    PRD §3.6: "On success `publication_status` becomes `PUBLISHED`,
    `published_at` is stamped from the logical clock, the domain's
    `published_master_record_count` is incremented by one, and the domain's
    `version` advances by one."

    Design: Corner/complexity_layers/published_record_counter_reconciles_after_create_publish_and_merge
    """
    ctx, first, second = _domain_with_two_curated_records(api)
    for record in (first, second):
        assert record["curation_status"] == "CURATED", (
            "an endorsed record is CURATED before publication, got "
            f"{record['curation_status']}"
        )
        assert record["publication_status"] == "UNPUBLISHED", (
            "ingestion and curation release nothing downstream, got "
            f"{record['publication_status']}"
        )

    after_curation = refresh_domain(ctx)
    assert after_curation["published_master_record_count"] == 0, (
        "ingesting and curating records releases nothing downstream, so the "
        "published count must still be 0, got "
        f"{after_curation['published_master_record_count']}"
    )

    for record in (first, second):
        published = validate_success(
            api.publish_master_record(record["id"], ctx["steward_headers"])
        )
        assert published["publication_status"] == "PUBLISHED", (
            f"publication must release the record, got "
            f"{published['publication_status']}"
        )
        assert is_iso8601_timestamp(published["published_at"]), (
            f"published_at must be stamped, got {published['published_at']!r}"
        )

    after_publication = refresh_domain(ctx)
    assert after_publication["published_master_record_count"] == 2, (
        "both published records must be counted, expected 2, got "
        f"{after_publication['published_master_record_count']}"
    )

    records, meta = validate_paginated(
        api.list_master_records(
            AUDITOR_HEADERS,
            params={"domain_id": ctx["domain"]["id"], "publication_status": "PUBLISHED"},
        )
    )
    assert meta["total_count"] == 2, (
        "the collection read must agree with the domain counter, expected 2, got "
        f"{meta['total_count']}"
    )


def test_merge_decision_retracts_the_loser_and_decrements_the_published_count(api):
    """PRD §3.7: "**Hop 3**, caused by hop 2's absorption of the loser, drives
    the loser's `curation_status` to `MERGED_AWAY` and writes the effective
    survivor's identifier into the loser's `superseded_by_master_record_id`; if
    the loser was `PUBLISHED` its `publication_status` becomes `RETRACTED` and
    the domain's `published_master_record_count` is decremented by one."
    PRD §3.7: "That weighted sum is rounded half up to two decimal places."
    PRD §3.7: "Then a structural discount applies: intra-source duplicates are
    inherently less trustworthy, so when the survivor candidate and the
    duplicate candidate share the same `source_system_id`, the whole rounded
    composite is multiplied by eight tenths and the product is rounded half up
    to two decimal places again — the discount is applied *after* the weighted
    sum has been rounded, not folded into it."
    PRD §3.7: "In that case the survivor is the candidate with the higher
    `survivorship_score`, breaking ties first by the later `last_verified_at`
    and then by the earlier `created_at`, and never by `id`."

    Design: Corner/complexity_layers/published_record_counter_reconciles_after_create_publish_and_merge
    """
    ctx, first, second = _domain_with_two_curated_records(api)
    for record in (first, second):
        validate_success(
            api.publish_master_record(record["id"], ctx["steward_headers"])
        )

    proposal = validate_success(
        api.create_merge_proposal(
            merge_proposal_payload(
                first["id"],
                second["id"],
                name_similarity_pct=100.00,
                key_overlap_pct=100.00,
            ),
            ctx["steward_headers"],
        ),
        201,
    )
    assert proposal["match_score"] == pytest.approx(80.00, abs=0.01), (
        "a perfect intra-source match scores 100.00 discounted by eight tenths, "
        f"expected 80.00, got {proposal['match_score']}"
    )
    assert proposal["match_confidence"] == "MEDIUM", (
        f"a match score of 80.00 reads as MEDIUM, got {proposal['match_confidence']}"
    )

    validate_success(api.review_merge_proposal(proposal["id"], ctx["steward_headers"]))
    merged = validate_success(
        api.decide_merge_proposal(
            proposal["id"],
            {
                "decision": "MERGE",
                "override_justification": (
                    "Identical tax id and address confirmed by the vendor master team"
                ),
            },
            ctx["owner_headers"],
        )
    )
    assert merged["status"] == "MERGED", (
        f"the decision must complete the merge, got {merged['status']}"
    )
    assert merged["effective_survivor_master_record_id"] == first["id"], (
        "with equal survivorship scores and equal verification instants the "
        "earlier-created record survives, expected the first record, got "
        f"{merged['effective_survivor_master_record_id']}"
    )
    assert merged["survivor_swapped"] is False, (
        "the nominated survivor was also the selected one, so no swap is "
        f"recorded, got {merged['survivor_swapped']}"
    )

    after_merge = refresh_domain(ctx)
    assert after_merge["published_master_record_count"] == 1, (
        "the loser's forced retraction must decrement the counter with no "
        f"publication call, expected 1, got "
        f"{after_merge['published_master_record_count']}"
    )

    loser = validate_success(api.get_master_record(second["id"], AUDITOR_HEADERS))
    assert loser["publication_status"] == "RETRACTED", (
        f"the absorbed record must be pulled back, got {loser['publication_status']}"
    )
    assert loser["curation_status"] == "MERGED_AWAY", (
        f"the absorbed record leaves the golden set, got {loser['curation_status']}"
    )
    assert loser["superseded_by_master_record_id"] == first["id"], (
        "the loser must point at the effective survivor, got "
        f"{loser['superseded_by_master_record_id']}"
    )

    survivor = validate_success(api.get_master_record(first["id"], AUDITOR_HEADERS))
    assert survivor["publication_status"] == "PUBLISHED", (
        "the survivor's own publication is untouched, got "
        f"{survivor['publication_status']}"
    )
    assert survivor["completeness_pct"] == pytest.approx(100.00, abs=0.01), (
        "the survivor carries every expected attribute, so it reads as exactly "
        f"complete, got {survivor['completeness_pct']}"
    )

    records, meta = validate_paginated(
        api.list_master_records(
            AUDITOR_HEADERS,
            params={"domain_id": ctx["domain"]["id"], "publication_status": "PUBLISHED"},
        )
    )
    assert meta["total_count"] == 1, (
        "the collection endpoint and the domain counter must still agree, "
        f"expected 1, got {meta['total_count']}"
    )


# ---------------------------------------------------------------------------
# A posture move is visible in the response that caused it
# ---------------------------------------------------------------------------


def _domain_with_one_critical_rule(api):
    """A DRAFT domain sitting at an OPEN posture behind one CRITICAL rule."""
    ctx = setup_governed_domain(
        activate=False,
        rules=[
            {
                "rule_code": "QR1",
                "dimension": "CONSISTENCY",
                "weight_points": 40,
                "threshold_pct": 90.00,
                "severity": "CRITICAL",
                "owner": "owner",
            }
        ],
    )
    assert ctx["domain"]["governance_posture"] == "OPEN", (
        "the registration recompute found a certified authoritative source and "
        f"no findings, so the posture is OPEN, got "
        f"{ctx['domain']['governance_posture']}"
    )
    return ctx


def test_scorecard_run_response_reports_the_posture_it_moved_the_domain_to(api):
    """PRD §3.4: "The multiplier is derived from the posture as it stood at the
    instant the run started, which the run records as `posture_before`; it is
    computed once and recorded as `posture_multiplier_applied`, and the *same*
    multiplier is applied to every finding the run creates."
    PRD §3.4: "Only after every finding of the run exists does the system
    recompute `open_finding_weight` and the `governance_posture`, exactly once,
    and the resulting posture is recorded on the run as `posture_after`."
    PRD §3.4: "The run's `weighted_score` is one hundred times the earned total
    divided by that denominator, rounded half up to two decimal places — a
    second and final rounding."
    PRD §2.6: "The posture is then determined in this priority order: it is
    `FROZEN` if the domain holds no such active authoritative registration, or if
    `open_finding_weight` is at least 40.00; otherwise it is `RESTRICTED` if
    `open_finding_weight` is at least 15.00, or if at least one finding in the
    open set is governed by a rule whose `severity` is `CRITICAL`; otherwise it
    is `OPEN`."

    Design: Corner/consistency_model/posture_transition_is_visible_inside_the_same_response
    """
    ctx = _domain_with_one_critical_rule(api)

    run = run_scorecard(
        ctx,
        basis="CERTIFIED",
        measurements=[{"rule_code": "QR1", "measured_pct": 50.00}],
    )
    assert run["weighted_score"] == pytest.approx(55.55, abs=0.01), (
        "a rule earning 22.22 of its 40 points scores 55.55 out of a hundred, "
        f"got {run['weighted_score']}"
    )
    assert run["rules_evaluated_count"] == 1, (
        f"the single active rule entered the denominator, got "
        f"{run['rules_evaluated_count']}"
    )
    assert run["rules_failed_count"] == 1, (
        f"that rule fell short of its threshold, got {run['rules_failed_count']}"
    )
    assert run["findings_created_count"] == 1, (
        "the breach was not previously known, so one finding was genuinely "
        f"created, got {run['findings_created_count']}"
    )
    assert run["posture_before"] == "OPEN", (
        f"the run began while the domain was OPEN, got {run['posture_before']}"
    )
    assert run["posture_multiplier_applied"] == pytest.approx(1.00, abs=0.01), (
        "an OPEN posture pins a multiplier of 1.00, got "
        f"{run['posture_multiplier_applied']}"
    )
    assert run["posture_after"] == "RESTRICTED", (
        "the open critical finding must move the domain to RESTRICTED, and the "
        f"mutating response itself must say so, got {run['posture_after']}"
    )


def test_domain_and_run_reads_agree_with_the_scorecard_response(api):
    """PRD §3.4: "Each finding's `severity_weight` is the base points times that
    multiplier, rounded half up to two decimal places, and it is frozen on the
    finding row forever after — nothing recomputes it."
    PRD §3.4: "If the rule already carries a finding in `OPEN` or
    `REMEDIATION_PLANNED` status, no new finding is created; instead that
    existing finding's `measured_pct` is refreshed to the newly observed value
    and its `gap_pct` is recomputed as the rule's `threshold_pct` minus the new
    `measured_pct`, rounded half up to two decimal places, and its
    `severity_weight` is left strictly untouched."
    PRD §3.4: "Only where no such open finding exists is a new one created, in
    `status` `OPEN`, carrying the observed `measured_pct`, the corresponding
    `gap_pct`, and a freshly pinned `severity_weight`."
    PRD §3.4: "A `PROVISIONAL` run writes its `weighted_score` to the domain's
    `quality_score_provisional`; a `CERTIFIED` run writes it to
    `quality_score_certified`."
    PRD §3.4: "The other basis's stored score is not touched, so a domain that
    has only ever run provisionally keeps a null `quality_score_certified`."

    Design: Corner/consistency_model/posture_transition_is_visible_inside_the_same_response
    """
    ctx = _domain_with_one_critical_rule(api)
    rule = ctx["rules"]["QR1"]

    run = run_scorecard(
        ctx,
        basis="CERTIFIED",
        measurements=[{"rule_code": "QR1", "measured_pct": 50.00}],
    )

    domain = refresh_domain(ctx)
    assert domain["governance_posture"] == run["posture_after"], (
        "the immediately following read must report the same posture the run "
        f"reported, expected {run['posture_after']}, got "
        f"{domain['governance_posture']}"
    )
    assert domain["open_finding_weight"] == pytest.approx(20.00, abs=0.01), (
        "one critical finding weighted at the pinned multiplier of 1.00 charges "
        f"20.00 of quality debt, got {domain['open_finding_weight']}"
    )
    assert domain["quality_score_certified"] == pytest.approx(55.55, abs=0.01), (
        "a certified run writes its score to the certified ledger field, got "
        f"{domain['quality_score_certified']}"
    )
    assert domain["quality_score_provisional"] is None, (
        "the other basis's stored score must be untouched, got "
        f"{domain['quality_score_provisional']!r}"
    )

    findings, finding_meta = validate_paginated(
        api.list_quality_findings(
            AUDITOR_HEADERS,
            params={"scorecard_run_id": run["id"], "quality_rule_id": rule["id"]},
        )
    )
    assert finding_meta["total_count"] == 1, (
        f"the run opened exactly one finding on the rule, got "
        f"{finding_meta['total_count']}"
    )
    finding = findings[0]
    assert finding["status"] == "OPEN", (
        f"a freshly created finding is OPEN, got {finding['status']}"
    )
    assert finding["severity_weight"] == pytest.approx(20.00, abs=0.01), (
        "a critical rule contributes 20 base points at a multiplier of 1.00, got "
        f"{finding['severity_weight']}"
    )
    assert finding["measured_pct"] == pytest.approx(50.00, abs=0.01), (
        f"the finding carries the observed measurement, got {finding['measured_pct']}"
    )
    assert finding["gap_pct"] == pytest.approx(40.00, abs=0.01), (
        "the gap is the rule's threshold less the measurement, expected 40.00, "
        f"got {finding['gap_pct']}"
    )

    runs, run_meta = validate_paginated(
        api.list_scorecard_runs(
            AUDITOR_HEADERS,
            params={"domain_id": ctx["domain"]["id"], "basis": "CERTIFIED"},
        )
    )
    assert run_meta["total_count"] == 1, (
        f"exactly one certified run was recorded, got {run_meta['total_count']}"
    )
    assert runs[0]["weighted_score"] == pytest.approx(55.55, abs=0.01), (
        "the immutable run row stores what its own response reported, got "
        f"{runs[0]['weighted_score']}"
    )
    assert runs[0]["posture_after"] == "RESTRICTED", (
        "the immutable run row stores the posture it moved the domain to, got "
        f"{runs[0]['posture_after']}"
    )
