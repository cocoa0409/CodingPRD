"""Two governance calculations that pick between genuinely different variants.

A scorecard run selects its evaluated rule set from the requested basis, so the
same measurement payload yields two different denominators and two different
scores. A merge decision selects its survivor from whether the authoritative
source stands behind exactly one of the two candidates, so the same pair of
records can hand the golden row to either candidate.
"""

from test_helpers import (
    GOVERNANCE_ADMIN_HEADERS,
    add_master_record,
    add_merge_proposal,
    assert_instant_equals,
    read_domain,
    register_source,
    run_scorecard,
    setup_governed_domain,
    validate_paginated,
    validate_success,
)


def _three_rule_budget():
    """Ninety weight points spread over three rules of different severities."""
    return [
        {
            "rule_code": "QR1",
            "dimension": "COMPLETENESS",
            "weight_points": 40,
            "threshold_pct": 90.00,
            "severity": "CRITICAL",
            "owner": "owner",
        },
        {
            "rule_code": "QR2",
            "dimension": "VALIDITY",
            "weight_points": 30,
            "threshold_pct": 80.00,
            "severity": "HIGH",
            "owner": "steward",
        },
        {
            "rule_code": "QR3",
            "dimension": "TIMELINESS",
            "weight_points": 20,
            "threshold_pct": 95.00,
            "severity": "MEDIUM",
            "owner": "steward",
        },
    ]


def _two_measurements():
    """QR1 exactly at its threshold, QR2 short of its own, QR3 unmeasured."""
    return [
        {"rule_code": "QR1", "measured_pct": 90.00},
        {"rule_code": "QR2", "measured_pct": 60.00},
    ]


def _erp_attributes():
    return {
        "legal_name": "Acme Industrial",
        "tax_id": "TX-77",
        "billing_city": "Austin",
        "contact_email": "ops@acme.test",
    }


def _crm_attributes():
    return {"legal_name": "Acme Ind.", "duns": "D-4410"}


def _domain_with_two_contributing_sources():
    """A domain whose authoritative registration sits on the tier-5 CRM, with a
    tier-4 ERP contributing and a tier-3 warehouse certified but unregistered."""
    return setup_governed_domain(
        activate=False,
        rules=[],
        sources=[
            {
                "code": "CRM",
                "name": "CRM Cloud",
                "trust_tier": 5,
                "role": "AUTHORITATIVE",
                "trust_rank": 1,
            },
            {
                "code": "ERP",
                "name": "ERP Core",
                "trust_tier": 4,
                "role": "CONTRIBUTING",
                "trust_rank": 2,
            },
            {
                "code": "WMS",
                "name": "Warehouse Master",
                "trust_tier": 3,
                "register": False,
            },
        ],
    )


def _duplicate_pair(ctx, erp_key, crm_key):
    """One ERP record with four populated keys and one CRM record with two."""
    erp_record = add_master_record(
        ctx,
        source_code="ERP",
        natural_key=erp_key,
        attributes=_erp_attributes(),
        last_verified_at="2026-07-01T00:00:00Z",
    )
    crm_record = add_master_record(
        ctx,
        source_code="CRM",
        natural_key=crm_key,
        attributes=_crm_attributes(),
        last_verified_at="2026-06-01T00:00:00Z",
    )
    return erp_record, crm_record


def test_provisional_basis_scores_only_the_rules_the_payload_measured(api):
    """A provisional run keeps unmeasured rules out of both sides of the ratio.

    On a `PROVISIONAL` basis the evaluated set is exactly those `ACTIVE` rules for which the payload supplied a `measured_pct`; an `ACTIVE` rule left unmeasured is excluded from the numerator, excluded from the denominator, and produces no finding.
    Otherwise each evaluated rule earns points: a rule whose `measured_pct` is greater than or equal to its `threshold_pct` earns its full `weight_points` — exact equality is a pass and earns the full weight — while a rule that falls short earns its `weight_points` multiplied by the ratio of its `measured_pct` to its `threshold_pct`, and that per-rule figure is rounded half up to two decimal places *before* anything is added up.
    The denominator is the plain sum of `weight_points` over the evaluated rules.
    The run's `weighted_score` is one hundred times the earned total divided by that denominator, rounded half up to two decimal places — a second and final rounding.
    A `PROVISIONAL` run writes its `weighted_score` to the domain's `quality_score_provisional`; a `CERTIFIED` run writes it to `quality_score_certified`.
    The other basis's stored score is not touched, so a domain that has only ever run provisionally keeps a null `quality_score_certified`.

    Design: Difficulty/dual_variant_calc/scorecard_provisional_vs_certified_denominator_divergence
    """
    ctx = setup_governed_domain(rules=_three_rule_budget())

    run = validate_success(
        api.create_scorecard_run(
            ctx["domain"]["id"],
            {"basis": "PROVISIONAL", "measurements": _two_measurements()},
            ctx["steward_headers"],
        ),
        201,
    )

    assert run["basis"] == "PROVISIONAL", (
        f"the run must record the requested basis, got {run['basis']}"
    )
    assert run["rules_evaluated_count"] == 2, (
        "a provisional run over a two-entry measurement payload must evaluate "
        f"only those two rules, got {run['rules_evaluated_count']}"
    )
    assert run["rules_failed_count"] == 1, (
        "only the validity rule fell short of its threshold, so exactly one "
        f"rule must count as failed, got {run['rules_failed_count']}"
    )
    assert run["weighted_score"] == 89.29, (
        "forty full points plus 22.50 earned points over a seventy point "
        f"denominator must score 89.29, got {run['weighted_score']}"
    )
    assert run["run_seq"] == 1, (
        f"the domain's first run must carry sequence 1, got {run['run_seq']}"
    )

    domain = read_domain(ctx["domain"]["id"])
    assert domain["quality_score_provisional"] == 89.29, (
        "a provisional run must publish its score as the domain's provisional "
        f"quality score, got {domain['quality_score_provisional']}"
    )
    assert domain["quality_score_certified"] is None, (
        "a domain that has only ever run provisionally must keep a null "
        f"certified score, got {domain['quality_score_certified']}"
    )


def test_certified_basis_keeps_every_active_rule_in_the_denominator(api):
    """A certified run treats a rule nobody measured as measured at zero.

    On a `CERTIFIED` basis the evaluated set is *every* `ACTIVE` rule of the domain, and an `ACTIVE` rule left unmeasured is treated as having a `measured_pct` of 0.00 — it stays in the denominator, earns zero points, and produces a finding.
    The denominator is the plain sum of `weight_points` over the evaluated rules.
    The run's `weighted_score` is one hundred times the earned total divided by that denominator, rounded half up to two decimal places — a second and final rounding.
    `rules_evaluated_count` records how many rules entered the denominator and `rules_failed_count` how many of them had a `measured_pct` strictly below their `threshold_pct`.
    A `PROVISIONAL` run writes its `weighted_score` to the domain's `quality_score_provisional`; a `CERTIFIED` run writes it to `quality_score_certified`.

    Design: Difficulty/dual_variant_calc/scorecard_provisional_vs_certified_denominator_divergence
    """
    ctx = setup_governed_domain(rules=_three_rule_budget())

    run = validate_success(
        api.create_scorecard_run(
            ctx["domain"]["id"],
            {"basis": "CERTIFIED", "measurements": _two_measurements()},
            ctx["steward_headers"],
        ),
        201,
    )

    assert run["rules_evaluated_count"] == 3, (
        "a certified run must draw the unmeasured timeliness rule into the "
        f"denominator as well, got {run['rules_evaluated_count']}"
    )
    assert run["rules_failed_count"] == 2, (
        "the validity rule and the unmeasured timeliness rule both fall below "
        f"their thresholds, got {run['rules_failed_count']} failures"
    )
    assert run["weighted_score"] == 69.44, (
        "the same 62.50 earned points over a ninety point denominator must "
        f"score 69.44 on the certified basis, got {run['weighted_score']}"
    )

    domain = read_domain(ctx["domain"]["id"])
    assert domain["quality_score_certified"] == 69.44, (
        "a certified run must publish its score as the domain's certified "
        f"quality score, got {domain['quality_score_certified']}"
    )


def test_certified_run_opens_a_finding_only_for_the_newly_exposed_breach(api):
    """The breach the provisional run already exposed is refreshed, not reopened.

    If the rule already carries a finding in `OPEN` or `REMEDIATION_PLANNED` status, no new finding is created; instead that existing finding's `measured_pct` is refreshed to the newly observed value and its `gap_pct` is recomputed as the rule's `threshold_pct` minus the new `measured_pct`, rounded half up to two decimal places, and its `severity_weight` is left strictly untouched.
    Only where no such open finding exists is a new one created, in `status` `OPEN`, carrying the observed `measured_pct`, the corresponding `gap_pct`, and a freshly pinned `severity_weight`.
    The count of genuinely new findings is recorded as `findings_created_count`, which is therefore not the same number as `rules_failed_count` whenever a breach was already known.
    On a `CERTIFIED` basis the evaluated set is *every* `ACTIVE` rule of the domain, and an `ACTIVE` rule left unmeasured is treated as having a `measured_pct` of 0.00 — it stays in the denominator, earns zero points, and produces a finding.
    Otherwise each evaluated rule earns points: a rule whose `measured_pct` is greater than or equal to its `threshold_pct` earns its full `weight_points` — exact equality is a pass and earns the full weight — while a rule that falls short earns its `weight_points` multiplied by the ratio of its `measured_pct` to its `threshold_pct`, and that per-rule figure is rounded half up to two decimal places *before* anything is added up.
    The domain's `scorecard_run_seq` is incremented by one and the resulting value is copied onto the run as `run_seq`, the run's `measured_at` is stamped from the logical clock, and the run's `domain_id` records the domain scored.

    Design: Difficulty/dual_variant_calc/scorecard_provisional_vs_certified_denominator_divergence
    """
    ctx = setup_governed_domain(rules=_three_rule_budget())
    run_scorecard(ctx, basis="PROVISIONAL", measurements=_two_measurements())

    certified_run = validate_success(
        api.create_scorecard_run(
            ctx["domain"]["id"],
            {"basis": "CERTIFIED", "measurements": _two_measurements()},
            ctx["steward_headers"],
        ),
        201,
    )

    assert certified_run["run_seq"] == 2, (
        "the certified run is the domain's second run and must carry sequence "
        f"2, got {certified_run['run_seq']}"
    )
    assert certified_run["findings_created_count"] == 1, (
        "the validity breach was already known, so only the timeliness rule "
        f"may open a new finding, got {certified_run['findings_created_count']}"
    )

    timeliness_findings, timeliness_meta = validate_paginated(
        api.list_quality_findings(
            GOVERNANCE_ADMIN_HEADERS,
            params={"quality_rule_id": ctx["rules"]["QR3"]["id"]},
        )
    )
    assert timeliness_meta["total_count"] == 1, (
        "the unmeasured timeliness rule must carry exactly one finding, got "
        f"{timeliness_meta['total_count']}"
    )
    timeliness_finding = timeliness_findings[0]
    assert timeliness_finding["status"] == "OPEN", (
        f"a freshly created finding must be OPEN, got {timeliness_finding['status']}"
    )
    assert timeliness_finding["measured_pct"] == 0.00, (
        "an unmeasured rule on a certified basis must record a measured "
        f"percentage of 0.00, got {timeliness_finding['measured_pct']}"
    )
    assert timeliness_finding["gap_pct"] == 95.00, (
        "a 95.00 threshold measured at 0.00 must record a gap of 95.00, got "
        f"{timeliness_finding['gap_pct']}"
    )

    _, completeness_meta = validate_paginated(
        api.list_quality_findings(
            GOVERNANCE_ADMIN_HEADERS,
            params={"quality_rule_id": ctx["rules"]["QR1"]["id"]},
        )
    )
    assert completeness_meta["total_count"] == 0, (
        "a completeness rule measured exactly at its threshold passes and must "
        f"carry no finding at all, got {completeness_meta['total_count']}"
    )


def test_authoritative_source_candidate_survives_a_lower_survivorship_score(api):
    """The authoritative contributor wins the golden row on source priority.

    The **source-priority** variant applies when exactly one of the two candidates was contributed by the source system behind the domain's `AUTHORITATIVE` registration that is `ACTIVE` at decision time.
    In that case the survivor is that single authoritative-source candidate *even if its `survivorship_score` is strictly lower than the other candidate's*; the score plays no part in choosing the survivor and is used only afterwards to fill in the field map.
    Whichever variant ran is recorded as `survivorship_variant`, the chosen record's identifier is recorded as `effective_survivor_master_record_id`, and `survivor_swapped` is set true exactly when that identifier differs from the `survivor_master_record_id` the proposer originally nominated.
    **Hop 3**, caused by hop 2's absorption of the loser, drives the loser's `curation_status` to `MERGED_AWAY` and writes the effective survivor's identifier into the loser's `superseded_by_master_record_id`; if the loser was `PUBLISHED` its `publication_status` becomes `RETRACTED` and the domain's `published_master_record_count` is decremented by one.

    Design: Difficulty/dual_variant_calc/survivorship_source_priority_vs_score_priority_survivor_swap
    """
    ctx = _domain_with_two_contributing_sources()
    erp_record, crm_record = _duplicate_pair(ctx, "ERP-CUST-1001", "CRM-CUST-1001")

    assert erp_record["completeness_pct"] == 80.00, (
        "four populated keys against an expected five must read 80.00, got "
        f"{erp_record['completeness_pct']}"
    )
    assert erp_record["survivorship_score"] == 88.00, (
        "a tier-4 record 80.00 complete and one whole month stale must score "
        f"88.00, got {erp_record['survivorship_score']}"
    )
    assert crm_record["completeness_pct"] == 40.00, (
        "two populated keys against an expected five must read 40.00, got "
        f"{crm_record['completeness_pct']}"
    )
    assert crm_record["survivorship_score"] == 78.00, (
        "a tier-5 record 40.00 complete and two whole months stale must score "
        f"78.00, got {crm_record['survivorship_score']}"
    )

    proposal = add_merge_proposal(
        ctx,
        erp_record,
        crm_record,
        name_similarity_pct=90.00,
        key_overlap_pct=70.00,
    )
    assert proposal["match_score"] == 74.00, (
        "45.00 plus 21.00 plus 8.00 across two different source systems must "
        f"give a match score of 74.00, got {proposal['match_score']}"
    )
    assert proposal["match_confidence"] == "MEDIUM", (
        f"a 74.00 match score must read MEDIUM, got {proposal['match_confidence']}"
    )

    decided = validate_success(
        api.decide_merge_proposal(
            proposal["id"],
            {
                "decision": "MERGE",
                "override_justification": (
                    "Duplicate confirmed via tax id and DUNS cross-check"
                ),
            },
            ctx["owner_headers"],
        )
    )

    assert decided["status"] == "MERGED", (
        f"an accepted merge must reach MERGED, got {decided['status']}"
    )
    assert decided["effective_survivor_master_record_id"] == crm_record["id"], (
        "the candidate contributed by the authoritative source must survive "
        "even though it scores 78.00 against the nominee's 88.00, got "
        f"{decided['effective_survivor_master_record_id']}"
    )
    assert decided["survivor_swapped"] is True, (
        "the system overruled the proposer's nomination, so survivor_swapped "
        f"must be true, got {decided['survivor_swapped']}"
    )

    loser = validate_success(
        api.get_master_record(erp_record["id"], GOVERNANCE_ADMIN_HEADERS)
    )
    assert loser["curation_status"] == "MERGED_AWAY", (
        "the record that lost the survivorship selection must be merged away, "
        f"got {loser['curation_status']}"
    )
    assert loser["superseded_by_master_record_id"] == crm_record["id"], (
        "the loser must point at the effective survivor, got "
        f"{loser['superseded_by_master_record_id']}"
    )


def test_merge_fills_only_the_survivors_gaps_and_rescores_it(api):
    """Enrichment never overwrites the survivor and records provenance per key.

    **Hop 2**, caused by hop 1, enriches the effective survivor from the loser: for every attribute key appearing on either record, the winning value is the effective survivor's value when that key is present and non-null on the survivor, and otherwise the loser's value — so the survivor's data is never overwritten, only its gaps are filled.
    For each key the `survivorship_field_map` records the `natural_key` of whichever record supplied the winning value, giving a field-by-field audit of provenance.
    The survivor's `last_verified_at` is set to the later of the two records' values, and its `completeness_pct` and `survivorship_score` are both recomputed against the enriched attribute set.
    That count is divided by the domain's `expected_attribute_count`, multiplied by one hundred, and rounded half up to two decimal places; the result is then capped at 100.00, so a record carrying more populated keys than the domain expects reads as exactly complete rather than over-complete.
    The three components are added and the total rounded half up to two decimal places.

    Design: Difficulty/dual_variant_calc/survivorship_source_priority_vs_score_priority_survivor_swap
    """
    ctx = _domain_with_two_contributing_sources()
    erp_record, crm_record = _duplicate_pair(ctx, "ERP-CUST-1001", "CRM-CUST-1001")
    proposal = add_merge_proposal(
        ctx,
        erp_record,
        crm_record,
        name_similarity_pct=90.00,
        key_overlap_pct=70.00,
    )

    decided = validate_success(
        api.decide_merge_proposal(
            proposal["id"],
            {
                "decision": "MERGE",
                "override_justification": (
                    "Duplicate confirmed via tax id and DUNS cross-check"
                ),
            },
            ctx["owner_headers"],
        )
    )

    assert decided["survivorship_field_map"] == {
        "legal_name": "CRM-CUST-1001",
        "duns": "CRM-CUST-1001",
        "tax_id": "ERP-CUST-1001",
        "billing_city": "ERP-CUST-1001",
        "contact_email": "ERP-CUST-1001",
    }, (
        "the survivor must keep its own legal name and DUNS and take the three "
        "keys it lacked from the loser, got "
        f"{decided['survivorship_field_map']}"
    )

    survivor = validate_success(
        api.get_master_record(crm_record["id"], GOVERNANCE_ADMIN_HEADERS)
    )
    assert survivor["attributes"]["legal_name"] == "Acme Ind.", (
        "the survivor's own legal name must not be overwritten by the loser's, "
        f"got {survivor['attributes']['legal_name']}"
    )
    assert survivor["completeness_pct"] == 100.00, (
        "five populated keys against an expected five must read 100.00 after "
        f"enrichment, got {survivor['completeness_pct']}"
    )
    assert survivor["survivorship_score"] == 106.00, (
        "a tier-5 record fully complete and one whole month stale must score "
        f"106.00 after enrichment, got {survivor['survivorship_score']}"
    )
    assert_instant_equals(
        survivor["last_verified_at"],
        "2026-07-01T00:00:00Z",
        "the enriched survivor's last_verified_at",
    )


def test_higher_scoring_candidate_survives_once_authority_moves_elsewhere(api):
    """With authority on a third system the score alone picks the survivor.

    When an incoming registration declares `role` of `AUTHORITATIVE` for a domain that already holds an `ACTIVE` `AUTHORITATIVE` registration, the incumbent moves `ACTIVE → SUPERSEDED`: its `superseded_at` is stamped from the clock and its `effective_to` is back-filled to the incoming registration's `effective_from`, so the two intervals abut without a gap.
    The **score-priority** variant applies when both candidates share the authoritative `source_system_id`, and equally when neither of them carries it — including the case where the authoritative registration has been superseded onto some third source system altogether.
    In that case the survivor is the candidate with the higher `survivorship_score`, breaking ties first by the later `last_verified_at` and then by the earlier `created_at`, and never by `id`.
    Whichever variant ran is recorded as `survivorship_variant`, the chosen record's identifier is recorded as `effective_survivor_master_record_id`, and `survivor_swapped` is set true exactly when that identifier differs from the `survivor_master_record_id` the proposer originally nominated.
    **Hop 3**, caused by hop 2's absorption of the loser, drives the loser's `curation_status` to `MERGED_AWAY` and writes the effective survivor's identifier into the loser's `superseded_by_master_record_id`; if the loser was `PUBLISHED` its `publication_status` becomes `RETRACTED` and the domain's `published_master_record_count` is decremented by one.
    The survivor's `last_verified_at` is set to the later of the two records' values, and its `completeness_pct` and `survivorship_score` are both recomputed against the enriched attribute set.

    Design: Difficulty/dual_variant_calc/survivorship_source_priority_vs_score_priority_survivor_swap
    """
    ctx = _domain_with_two_contributing_sources()
    erp_record, crm_record = _duplicate_pair(ctx, "ERP-CUST-2002", "CRM-CUST-2002")
    proposal = add_merge_proposal(
        ctx,
        erp_record,
        crm_record,
        name_similarity_pct=90.00,
        key_overlap_pct=70.00,
    )

    crm_registration = ctx["registrations"]["CRM"]
    register_source(
        ctx["domain"]["id"],
        ctx["sources"]["WMS"]["id"],
        role="AUTHORITATIVE",
        trust_rank=1,
        effective_from="2026-08-05T00:00:00Z",
    )

    superseded = validate_success(
        api.get_source_registration(crm_registration["id"], GOVERNANCE_ADMIN_HEADERS)
    )
    assert superseded["status"] == "SUPERSEDED", (
        "the incumbent authoritative registration must be superseded rather "
        f"than refused, got {superseded['status']}"
    )
    assert_instant_equals(
        superseded["effective_to"],
        "2026-08-05T00:00:00Z",
        "the superseded registration's effective_to",
    )

    decided = validate_success(
        api.decide_merge_proposal(
            proposal["id"],
            {
                "decision": "MERGE",
                "override_justification": (
                    "Duplicate confirmed via tax id and DUNS cross-check"
                ),
            },
            ctx["owner_headers"],
        )
    )

    assert decided["effective_survivor_master_record_id"] == erp_record["id"], (
        "with authority moved to the warehouse system neither candidate is "
        "authoritative, so the 88.00 record must beat the 78.00 one, got "
        f"{decided['effective_survivor_master_record_id']}"
    )
    assert decided["survivor_swapped"] is False, (
        "the system upheld the proposer's nomination, so survivor_swapped must "
        f"be false, got {decided['survivor_swapped']}"
    )

    survivor = validate_success(
        api.get_master_record(erp_record["id"], GOVERNANCE_ADMIN_HEADERS)
    )
    assert survivor["completeness_pct"] == 100.00, (
        "the enriched survivor gains the DUNS key and must read 100.00, got "
        f"{survivor['completeness_pct']}"
    )
    assert survivor["survivorship_score"] == 96.00, (
        "a tier-4 record fully complete and one whole month stale must score "
        f"96.00 after enrichment, got {survivor['survivorship_score']}"
    )

    loser = validate_success(
        api.get_master_record(crm_record["id"], GOVERNANCE_ADMIN_HEADERS)
    )
    assert loser["curation_status"] == "MERGED_AWAY", (
        "the lower-scoring candidate must be merged away, got "
        f"{loser['curation_status']}"
    )
    assert loser["superseded_by_master_record_id"] == erp_record["id"], (
        "the loser must point at the effective survivor, got "
        f"{loser['superseded_by_master_record_id']}"
    )
