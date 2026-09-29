"""Derived governance arithmetic: master-record completeness and survivorship,
scorecard scoring on both bases, the conserved governance counters, and the
downstream notification lead time.

Every test stands its own governed domain up from scratch through the published
endpoints and positions the logical clock explicitly, because each figure under
test reads the clock, the domain's declared attribute denominator, or the
domain's own quality-rule set.
"""

from test_helpers import (
    GOVERNANCE_ADMIN_HEADERS,
    add_change_request,
    add_consumer_subscription,
    assert_instant_equals,
    assert_two_decimal_places,
    list_findings,
    master_record_payload,
    read_domain,
    setup_draft_domain,
    setup_governed_domain,
    validate_error,
    validate_success,
)

TWO_RULE_SET = [
    {
        "rule_code": "QR1",
        "dimension": "COMPLETENESS",
        "weight_points": 40,
        "threshold_pct": 90.00,
        "severity": "HIGH",
        "owner": "steward",
    },
    {
        "rule_code": "QR2",
        "dimension": "TIMELINESS",
        "weight_points": 60,
        "threshold_pct": 80.00,
        "severity": "LOW",
        "owner": "steward",
    },
]


def _product_domain_expecting_three_attributes():
    """A PRODUCT domain whose complete record carries three attribute keys."""
    return setup_draft_domain(
        clock="2026-08-01T00:00:00Z",
        domain_overrides={
            "code": "PRODUCT",
            "name": "Product Master",
            "expected_attribute_count": 3,
        },
        sources=[
            {
                "code": "ERP",
                "name": "ERP Core",
                "trust_tier": 4,
                "certify": True,
                "register": False,
            }
        ],
        rules=[],
    )


# --------------------------------------------------------------------------
# Record completeness
# --------------------------------------------------------------------------


def test_two_of_three_populated_attributes_reads_as_sixty_six_point_six_seven(api):
    """PRD §3.6: "The system counts the attribute keys that are physically present in `attributes` with a value that is neither null nor the empty string — an absent key and a null-valued key are both counted as missing, and so is an empty string. That count is divided by the domain's `expected_attribute_count`, multiplied by one hundred, and rounded half up to two decimal places; the result is then capped at 100.00, so a record carrying more populated keys than the domain expects reads as exactly complete rather than over-complete."
    PRD §2.7: "Every monetary-style and percentage-style quantity in this system is carried to two decimal places and rounded half up."

    Design: Corner/calculations/completeness_pct_rounds_half_up_to_two_decimals
    """
    ctx = _product_domain_expecting_three_attributes()

    record = validate_success(
        api.create_master_record(
            master_record_payload(
                ctx["domain"]["id"],
                ctx["sources"]["ERP"]["id"],
                natural_key="ERP-PROD-1",
                attributes={"sku": "SKU-1", "description": "Widget"},
                last_verified_at="2026-08-01T00:00:00Z",
            ),
            ctx["steward_headers"],
        ),
        201,
    )

    assert_two_decimal_places(record["completeness_pct"], "completeness_pct")
    assert record["completeness_pct"] == 66.67, (
        "two of three expected attribute keys must be recorded as 66.67 percent "
        f"complete, rounded half up, got {record['completeness_pct']}"
    )


def test_null_valued_attribute_key_is_counted_as_missing_for_completeness(api):
    """PRD §3.6: "The system counts the attribute keys that are physically present in `attributes` with a value that is neither null nor the empty string — an absent key and a null-valued key are both counted as missing, and so is an empty string. That count is divided by the domain's `expected_attribute_count`, multiplied by one hundred, and rounded half up to two decimal places; the result is then capped at 100.00, so a record carrying more populated keys than the domain expects reads as exactly complete rather than over-complete."

    Design: Corner/calculations/completeness_pct_rounds_half_up_to_two_decimals
    """
    ctx = _product_domain_expecting_three_attributes()

    record = validate_success(
        api.create_master_record(
            master_record_payload(
                ctx["domain"]["id"],
                ctx["sources"]["ERP"]["id"],
                natural_key="ERP-PROD-2",
                attributes={"sku": "SKU-2", "description": None},
                last_verified_at="2026-08-01T00:00:00Z",
            ),
            ctx["steward_headers"],
        ),
        201,
    )

    assert_two_decimal_places(record["completeness_pct"], "completeness_pct")
    assert record["completeness_pct"] == 33.33, (
        "the null-valued attribute key must not count as populated, leaving one "
        f"of three keys and 33.33 percent completeness, got "
        f"{record['completeness_pct']}"
    )


# --------------------------------------------------------------------------
# Retiring a rule and the certified denominator
# --------------------------------------------------------------------------


def test_retired_rule_code_is_no_longer_a_measurable_rule_of_the_domain(api):
    """PRD §3.3: "A retired rule leaves the scorecard denominator from the next run onward — it never enters either numerator or denominator again — but findings already opened against it keep the `severity_weight` they were pinned with, so retiring a rule does not quietly deflate the domain's quality debt."
    PRD §3.4: "A measurement naming a `rule_code` that is not an `ACTIVE` rule of the scored domain is rejected with `ERR_UNKNOWN_RULE_CODE`."
    PRD §3.4: "The domain's `scorecard_run_seq` is incremented by one and the resulting value is copied onto the run as `run_seq`, the run's `measured_at` is stamped from the logical clock, and the run's `domain_id` records the domain scored."

    Design: Corner/calculations/retired_rule_leaves_the_certified_denominator
    """
    ctx = setup_draft_domain(rules=TWO_RULE_SET)

    retired = validate_success(
        api.update_quality_rule(
            ctx["rules"]["QR2"]["id"], {"status": "RETIRED"}, ctx["steward_headers"]
        )
    )
    assert retired["status"] == "RETIRED", (
        "a rule carrying no open finding must retire cleanly, got status "
        f"{retired['status']}"
    )

    rejected = api.create_scorecard_run(
        ctx["domain"]["id"],
        {
            "basis": "CERTIFIED",
            "measurements": [
                {"rule_code": "QR1", "measured_pct": 45.00},
                {"rule_code": "QR2", "measured_pct": 90.00},
            ],
        },
        ctx["steward_headers"],
    )
    validate_error(rejected, "ERR_UNKNOWN_RULE_CODE")

    domain = read_domain(ctx["domain"]["id"])
    assert domain["scorecard_run_seq"] == 0, (
        "a rejected scorecard run must not consume a scorecard epoch, got "
        f"scorecard_run_seq {domain['scorecard_run_seq']}"
    )


def test_certified_denominator_shrinks_to_the_surviving_active_rule(api):
    """PRD §3.4: "On a `CERTIFIED` basis the evaluated set is *every* `ACTIVE` rule of the domain, and an `ACTIVE` rule left unmeasured is treated as having a `measured_pct` of 0.00 — it stays in the denominator, earns zero points, and produces a finding."
    PRD §3.4: "Otherwise each evaluated rule earns points: a rule whose `measured_pct` is greater than or equal to its `threshold_pct` earns its full `weight_points` — exact equality is a pass and earns the full weight — while a rule that falls short earns its `weight_points` multiplied by the ratio of its `measured_pct` to its `threshold_pct`, and that per-rule figure is rounded half up to two decimal places *before* anything is added up."
    PRD §3.4: "The already-rounded per-rule figures are then summed to give the earned total. The denominator is the plain sum of `weight_points` over the evaluated rules. The run's `weighted_score` is one hundred times the earned total divided by that denominator, rounded half up to two decimal places — a second and final rounding."
    PRD §3.4: "`rules_evaluated_count` records how many rules entered the denominator and `rules_failed_count` how many of them had a `measured_pct` strictly below their `threshold_pct`."
    PRD §3.4: "A `PROVISIONAL` run writes its `weighted_score` to the domain's `quality_score_provisional`; a `CERTIFIED` run writes it to `quality_score_certified`."

    Design: Corner/calculations/retired_rule_leaves_the_certified_denominator
    """
    ctx = setup_draft_domain(rules=TWO_RULE_SET)
    validate_success(
        api.update_quality_rule(
            ctx["rules"]["QR2"]["id"], {"status": "RETIRED"}, ctx["steward_headers"]
        )
    )

    run = validate_success(
        api.create_scorecard_run(
            ctx["domain"]["id"],
            {
                "basis": "CERTIFIED",
                "measurements": [{"rule_code": "QR1", "measured_pct": 45.00}],
            },
            ctx["steward_headers"],
        ),
        201,
    )

    assert run["rules_evaluated_count"] == 1, (
        "only the surviving active rule may enter the certified denominator, got "
        f"rules_evaluated_count {run['rules_evaluated_count']}"
    )
    assert run["rules_failed_count"] == 1, (
        "the surviving rule was measured below its threshold, so exactly one "
        f"rule failed, got {run['rules_failed_count']}"
    )
    assert run["weighted_score"] == 50.00, (
        "the retired rule must leave the denominator, scoring the run at 50.00, "
        f"got {run['weighted_score']}"
    )
    assert run["run_seq"] == 1, (
        f"the first recorded run of the domain carries run_seq 1, got {run['run_seq']}"
    )

    domain = read_domain(ctx["domain"]["id"])
    assert domain["quality_score_certified"] == 50.00, (
        "a certified run stores its weighted score as the domain's certified "
        f"quality score, got {domain['quality_score_certified']}"
    )
    assert domain["scorecard_run_seq"] == 1, (
        "the accepted run advances the domain's scorecard epoch to 1, got "
        f"{domain['scorecard_run_seq']}"
    )


# --------------------------------------------------------------------------
# An empty evaluated rule set
# --------------------------------------------------------------------------


def test_provisional_run_with_no_measurements_scores_zero_and_opens_no_finding(api):
    """PRD §3.4: "On a `PROVISIONAL` basis the evaluated set is exactly those `ACTIVE` rules for which the payload supplied a `measured_pct`; an `ACTIVE` rule left unmeasured is excluded from the numerator, excluded from the denominator, and produces no finding."
    PRD §3.4: "If that set is empty, the run's `weighted_score` is 0.00 and no findings are created at all."
    PRD §3.4: "`rules_evaluated_count` records how many rules entered the denominator and `rules_failed_count` how many of them had a `measured_pct` strictly below their `threshold_pct`."
    PRD §3.4: "The count of genuinely new findings is recorded as `findings_created_count`, which is therefore not the same number as `rules_failed_count` whenever a breach was already known."

    Design: Corner/calculations/empty_evaluated_rule_set_scores_zero_and_opens_nothing
    """
    ctx = setup_draft_domain(sources=[])

    run = validate_success(
        api.create_scorecard_run(
            ctx["domain"]["id"],
            {"basis": "PROVISIONAL", "measurements": []},
            ctx["steward_headers"],
        ),
        201,
    )

    assert run["weighted_score"] == 0.00, (
        "an empty evaluated rule set scores exactly 0.00 rather than a full "
        f"score or an error, got {run['weighted_score']}"
    )
    assert run["rules_evaluated_count"] == 0, (
        "the unmeasured active rule stays out of the provisional denominator, "
        f"got rules_evaluated_count {run['rules_evaluated_count']}"
    )
    assert run["rules_failed_count"] == 0, (
        f"no rule was evaluated, so none can fail, got {run['rules_failed_count']}"
    )
    assert run["findings_created_count"] == 0, (
        "an empty evaluated set opens no quality finding, got "
        f"findings_created_count {run['findings_created_count']}"
    )


def test_provisional_run_over_an_empty_rule_set_still_advances_the_epoch(api):
    """PRD §3.4: "The domain's `scorecard_run_seq` is incremented by one and the resulting value is copied onto the run as `run_seq`, the run's `measured_at` is stamped from the logical clock, and the run's `domain_id` records the domain scored."
    PRD §3.4: "A `PROVISIONAL` run writes its `weighted_score` to the domain's `quality_score_provisional`; a `CERTIFIED` run writes it to `quality_score_certified`."
    PRD §2.8: "`Domain.open_finding_weight` is the two-decimal, half-up-rounded sum of `severity_weight` over the domain's findings whose `status` is `OPEN` or `REMEDIATION_PLANNED`."

    Design: Corner/calculations/empty_evaluated_rule_set_scores_zero_and_opens_nothing
    """
    ctx = setup_draft_domain(sources=[])

    run = validate_success(
        api.create_scorecard_run(
            ctx["domain"]["id"],
            {"basis": "PROVISIONAL", "measurements": []},
            ctx["steward_headers"],
        ),
        201,
    )
    assert run["run_seq"] == 1, (
        f"the run must claim scorecard epoch 1, got run_seq {run['run_seq']}"
    )

    domain = read_domain(ctx["domain"]["id"])
    assert domain["scorecard_run_seq"] == 1, (
        "the scorecard epoch advances even when nothing was measured, got "
        f"{domain['scorecard_run_seq']}"
    )
    assert domain["quality_score_provisional"] == 0.00, (
        "the provisional score ledger records the empty run's 0.00, got "
        f"{domain['quality_score_provisional']}"
    )
    assert domain["open_finding_weight"] == 0.00, (
        "no finding was opened, so the domain carries no open finding weight, "
        f"got {domain['open_finding_weight']}"
    )


# --------------------------------------------------------------------------
# Notification lead time on submission
# --------------------------------------------------------------------------


def _domain_with_two_impacted_consumers():
    """An ACTIVE INTERNAL domain with a five-day floor and two active consumers
    needing ten and four days of notice."""
    ctx = setup_governed_domain(clock="2026-08-05T00:00:00Z")
    add_consumer_subscription(
        ctx,
        consumer_code="BI_A",
        reporting_asset_key="RPT_A",
        clearance_level="INTERNAL",
        criticality="TIER2",
        required_lead_days=10,
    )
    add_consumer_subscription(
        ctx,
        consumer_code="BI_B",
        reporting_asset_key="RPT_B",
        clearance_level="INTERNAL",
        criticality="TIER2",
        required_lead_days=4,
    )
    return ctx


def _raise_hierarchy_restructure(ctx, title, child_node_key):
    return add_change_request(
        ctx,
        stage="DRAFT",
        change_type="HIERARCHY_RESTRUCTURE",
        title=title,
        proposed_values={"parent_node_key": "GLOBAL", "child_node_key": child_node_key},
    )


def test_two_impacted_consumers_earn_no_breadth_surcharge_on_the_lead_time(api):
    """PRD §3.8: "In other words, a structural change impacts every active consumer regardless of criticality, whereas a plain reference-value addition impacts only the `TIER1` consumers."
    PRD §3.8: "Second, a base lead time is taken as the largest `required_lead_days` among the impacted consumers, or zero when the impacted set is empty."
    PRD §3.8: "Third, a floor lead time is taken as the domain's `notification_lead_days_floor` when at least one consumer is impacted, and zero when none is."
    PRD §3.8: "Fourth, a breadth surcharge is derived from the *count* rather than from the days: three extra days when at least five consumers are impacted, one extra day when at least three but fewer than five are impacted, and none below three."
    PRD §3.8: "Fifth, a classification surcharge of two extra days applies when the domain's `classification_level` is `CONFIDENTIAL` or `RESTRICTED`, and none otherwise."
    PRD §3.8: "Sixth — and this ordering is normative — the greater of the base lead and the floor lead is taken *first*, the two surcharges are added to that, and only then is the result capped at thirty days; the capped figure is stored as `required_lead_days`."
    PRD §3.8: "Finally, `earliest_apply_at` is set to `submitted_at` advanced by `required_lead_days` whole days."

    Design: Corner/calculations/lead_time_breadth_surcharge_appears_at_three_impacted_consumers
    """
    ctx = _domain_with_two_impacted_consumers()
    request = _raise_hierarchy_restructure(ctx, "Split EMEA node", "EMEA_SALES")

    submitted = validate_success(
        api.submit_change_request(request["id"], ctx["steward_headers"])
    )

    assert submitted["impact_consumer_count"] == 2, (
        "a structural change impacts both active consumers regardless of their "
        f"criticality, got impact_consumer_count {submitted['impact_consumer_count']}"
    )
    assert submitted["required_lead_days"] == 10, (
        "the largest consumer requirement of ten days beats the five-day floor "
        "and earns no surcharge below three impacted consumers, got "
        f"{submitted['required_lead_days']}"
    )
    assert_instant_equals(
        submitted["submitted_at"], "2026-08-05T00:00:00Z", "submitted_at"
    )
    assert_instant_equals(
        submitted["earliest_apply_at"],
        "2026-08-15T00:00:00Z",
        "earliest_apply_at ten whole days after submission",
    )


def test_third_impacted_consumer_adds_one_breadth_day_to_the_lead_time(api):
    """PRD §3.8: "Fourth, a breadth surcharge is derived from the *count* rather than from the days: three extra days when at least five consumers are impacted, one extra day when at least three but fewer than five are impacted, and none below three."
    PRD §3.8: "Sixth — and this ordering is normative — the greater of the base lead and the floor lead is taken *first*, the two surcharges are added to that, and only then is the result capped at thirty days; the capped figure is stored as `required_lead_days`."
    PRD §3.8: "Finally, `earliest_apply_at` is set to `submitted_at` advanced by `required_lead_days` whole days."
    PRD §3.8: "Both paths stamp `submitted_at` from the logical clock and then compute `impact_consumer_count`, `required_lead_days` and `earliest_apply_at` from scratch against the *current* consumer set and the *new* `submitted_at` — a resubmission does not reuse the numbers from the first submission."

    Design: Corner/calculations/lead_time_breadth_surcharge_appears_at_three_impacted_consumers
    """
    ctx = _domain_with_two_impacted_consumers()
    first = _raise_hierarchy_restructure(ctx, "Split EMEA node", "EMEA_SALES")
    first = validate_success(
        api.submit_change_request(first["id"], ctx["steward_headers"])
    )

    add_consumer_subscription(
        ctx,
        consumer_code="BI_C",
        reporting_asset_key="RPT_C",
        clearance_level="INTERNAL",
        criticality="TIER3",
        required_lead_days=4,
    )

    second = _raise_hierarchy_restructure(ctx, "Split APAC node", "APAC_SALES")
    second = validate_success(
        api.submit_change_request(second["id"], ctx["steward_headers"])
    )

    assert second["impact_consumer_count"] == 3, (
        "all three active consumers are impacted by a structural change, got "
        f"impact_consumer_count {second['impact_consumer_count']}"
    )
    assert second["required_lead_days"] == 11, (
        "a third impacted consumer adds one breadth day on top of the ten-day "
        f"base lead even though it only needs four days, got "
        f"{second['required_lead_days']}"
    )
    assert_instant_equals(
        second["earliest_apply_at"],
        "2026-08-16T00:00:00Z",
        "earliest_apply_at eleven whole days after submission",
    )

    reread = validate_success(
        api.get_change_request(first["id"], ctx["steward_headers"])
    )
    assert reread["required_lead_days"] == 10, (
        "the earlier request's assessment was computed at its own submission and "
        f"is not re-derived when a later consumer registers, got "
        f"{reread['required_lead_days']}"
    )


# --------------------------------------------------------------------------
# Survivorship scoring
# --------------------------------------------------------------------------


def _domain_for_survivorship_scoring():
    """A CUSTOMER domain expecting five attributes, fed by a tier-4 system,
    with the clock parked at 2026-08-01T00:00:00Z."""
    return setup_draft_domain(
        clock="2026-08-01T00:00:00Z",
        sources=[
            {
                "code": "ERP",
                "name": "ERP Core",
                "trust_tier": 4,
                "certify": True,
                "register": False,
            }
        ],
        rules=[],
    )


def _ingest_fully_populated_record(api, ctx, natural_key, last_verified_at, prefix):
    return validate_success(
        api.create_master_record(
            master_record_payload(
                ctx["domain"]["id"],
                ctx["sources"]["ERP"]["id"],
                natural_key=natural_key,
                attributes={
                    "legal_name": f"{prefix} Co",
                    "tax_id": f"TX-{prefix}",
                    "billing_city": "Ames",
                    "contact_email": f"{prefix}@x.test",
                    "duns": f"{prefix}-1",
                },
                last_verified_at=last_verified_at,
            ),
            ctx["steward_headers"],
        ),
        201,
    )


def test_survivorship_recency_decays_in_whole_thirty_day_buckets(api):
    """PRD §3.6: "The **trust component** is the contributing source system's `trust_tier` multiplied by ten, so it ranges from 10 points for a tier-1 system up to 50 points for a tier-5 one."
    PRD §3.6: "The **completeness component** is the record's `completeness_pct` multiplied by four tenths and rounded half up to two decimal places, so it ranges from 0 up to 40 points."
    PRD §3.6: "The **recency component** starts from a maximum of 20 points and decays by 4 points for every whole month of staleness, where staleness in months is the number of whole days between the record's `last_verified_at` and the current logical clock, divided by thirty and rounded down to a whole number; the component is floored at zero, so a record more than five whole months stale contributes 0 rather than a negative number."
    PRD §3.6: "The three components are added and the total rounded half up to two decimal places."

    Design: Corner/calculations/survivorship_recency_component_decays_then_floors_at_zero
    """
    ctx = _domain_for_survivorship_scoring()

    fresh = _ingest_fully_populated_record(
        api, ctx, "ERP-CUST-FRESH", "2026-07-15T00:00:00Z", "Fresh"
    )
    thirty = _ingest_fully_populated_record(
        api, ctx, "ERP-CUST-30D", "2026-07-02T00:00:00Z", "Thirty"
    )

    assert fresh["completeness_pct"] == 100.00, (
        "five of five expected attribute keys read as exactly complete, got "
        f"{fresh['completeness_pct']}"
    )
    assert fresh["survivorship_score"] == 100.00, (
        "seventeen whole days of staleness is under one thirty-day bucket, so "
        "the record keeps the full twenty recency points on top of forty trust "
        f"and forty completeness points, got {fresh['survivorship_score']}"
    )
    assert thirty["survivorship_score"] == 96.00, (
        "exactly thirty whole days of staleness is one bucket and costs four "
        f"recency points, got {thirty['survivorship_score']}"
    )
    assert_two_decimal_places(thirty["survivorship_score"], "survivorship_score")


def test_survivorship_recency_component_is_floored_at_zero(api):
    """PRD §3.6: "The **recency component** starts from a maximum of 20 points and decays by 4 points for every whole month of staleness, where staleness in months is the number of whole days between the record's `last_verified_at` and the current logical clock, divided by thirty and rounded down to a whole number; the component is floored at zero, so a record more than five whole months stale contributes 0 rather than a negative number."
    PRD §3.6: "The three components are added and the total rounded half up to two decimal places."

    Design: Corner/calculations/survivorship_recency_component_decays_then_floors_at_zero
    """
    ctx = _domain_for_survivorship_scoring()

    stale = _ingest_fully_populated_record(
        api, ctx, "ERP-CUST-STALE", "2026-01-01T00:00:00Z", "Stale"
    )

    assert stale["survivorship_score"] == 80.00, (
        "seven thirty-day buckets of staleness would subtract twenty-eight "
        "recency points, but the component is floored at zero so the total "
        f"stops at forty trust plus forty completeness points, got "
        f"{stale['survivorship_score']}"
    )
    assert_two_decimal_places(stale["survivorship_score"], "survivorship_score")


# --------------------------------------------------------------------------
# Conserved governance counters
# --------------------------------------------------------------------------


def test_open_finding_weight_sums_severity_weight_over_the_whole_open_set(api):
    """PRD §2.8: "`Domain.open_finding_weight` is the two-decimal, half-up-rounded sum of `severity_weight` over the domain's findings whose `status` is `OPEN` or `REMEDIATION_PLANNED`."
    PRD §3.4: "The base points come from the breached rule's `severity`: a `LOW`-severity rule contributes 1 point, `MEDIUM` contributes 3, `HIGH` contributes 8 and `CRITICAL` contributes 20."
    PRD §3.4: "Those base points are then multiplied by a posture multiplier: 1.00 when the domain's posture was `OPEN`, 1.25 when it was `RESTRICTED` and 1.50 when it was `FROZEN`."
    PRD §3.4: "Findings are then opened, in ascending `rule_code` order, for each evaluated rule that fell short — but with a deduplication rule that matters enormously in practice."
    PRD §3.4: "The already-rounded per-rule figures are then summed to give the earned total. The denominator is the plain sum of `weight_points` over the evaluated rules. The run's `weighted_score` is one hundred times the earned total divided by that denominator, rounded half up to two decimal places — a second and final rounding."

    Design: Corner/calculations/open_finding_weight_recounts_only_the_open_status_set
    """
    ctx = setup_draft_domain(rules=TWO_RULE_SET)

    run = validate_success(
        api.create_scorecard_run(
            ctx["domain"]["id"],
            {
                "basis": "PROVISIONAL",
                "measurements": [
                    {"rule_code": "QR2", "measured_pct": 40.00},
                    {"rule_code": "QR1", "measured_pct": 45.00},
                ],
            },
            ctx["steward_headers"],
        ),
        201,
    )

    assert run["findings_created_count"] == 2, (
        "both breached rules open a fresh finding, got findings_created_count "
        f"{run['findings_created_count']}"
    )
    assert run["weighted_score"] == 50.00, (
        "the two already-rounded earned figures of 20.00 and 30.00 over a "
        f"hundred-point denominator score the run at 50.00, got "
        f"{run['weighted_score']}"
    )

    high_findings = list_findings(
        ctx, scorecard_run_id=run["id"], quality_rule_id=ctx["rules"]["QR1"]["id"]
    )
    low_findings = list_findings(
        ctx, scorecard_run_id=run["id"], quality_rule_id=ctx["rules"]["QR2"]["id"]
    )
    assert len(high_findings) == 1 and len(low_findings) == 1, (
        "each breached rule must carry exactly one finding from this run, got "
        f"{len(high_findings)} and {len(low_findings)}"
    )
    assert high_findings[0]["severity_weight"] == 8.00, (
        "a HIGH-severity breach on an OPEN domain pins eight points of quality "
        f"debt, got {high_findings[0]['severity_weight']}"
    )
    assert low_findings[0]["severity_weight"] == 1.00, (
        "a LOW-severity breach on an OPEN domain pins one point of quality "
        f"debt, got {low_findings[0]['severity_weight']}"
    )

    domain = read_domain(ctx["domain"]["id"])
    assert domain["open_finding_weight"] == 9.00, (
        "the domain's open finding weight is the recount over the whole open "
        "set and is unaffected by the order the measurements arrived in, got "
        f"{domain['open_finding_weight']}"
    )


def test_open_findings_charge_no_steward_finding_load(api):
    """PRD §2.8: "`Steward.open_finding_load` is the exact integer count of findings whose `assigned_steward_id` is that steward and whose `status` is `REMEDIATION_PLANNED` — note the filter is `REMEDIATION_PLANNED` only, so an `OPEN` finding never charges anyone's load."
    PRD §3.1: "Its `open_finding_load` begins at 0 and is thereafter maintained by the system, never supplied."

    Design: Corner/calculations/open_finding_weight_recounts_only_the_open_status_set
    """
    ctx = setup_draft_domain(rules=TWO_RULE_SET)

    validate_success(
        api.create_scorecard_run(
            ctx["domain"]["id"],
            {
                "basis": "PROVISIONAL",
                "measurements": [
                    {"rule_code": "QR2", "measured_pct": 40.00},
                    {"rule_code": "QR1", "measured_pct": 45.00},
                ],
            },
            ctx["steward_headers"],
        ),
        201,
    )

    steward = validate_success(
        api.get_steward(ctx["steward"]["id"], GOVERNANCE_ADMIN_HEADERS)
    )
    owner = validate_success(
        api.get_steward(ctx["owner"]["id"], GOVERNANCE_ADMIN_HEADERS)
    )
    assert steward["open_finding_load"] == 0, (
        "findings that are merely OPEN charge no steward's remediation load, "
        f"got {steward['open_finding_load']} for the accountable steward"
    )
    assert owner["open_finding_load"] == 0, (
        "findings that are merely OPEN charge no steward's remediation load, "
        f"got {owner['open_finding_load']} for the data owner"
    )


# --------------------------------------------------------------------------
# The two score ledgers
# --------------------------------------------------------------------------


def test_provisional_and_certified_runs_write_separate_score_ledger_fields(api):
    """PRD §3.4: "On a `PROVISIONAL` basis the evaluated set is exactly those `ACTIVE` rules for which the payload supplied a `measured_pct`; an `ACTIVE` rule left unmeasured is excluded from the numerator, excluded from the denominator, and produces no finding."
    PRD §3.4: "On a `CERTIFIED` basis the evaluated set is *every* `ACTIVE` rule of the domain, and an `ACTIVE` rule left unmeasured is treated as having a `measured_pct` of 0.00 — it stays in the denominator, earns zero points, and produces a finding."
    PRD §3.4: "A `PROVISIONAL` run writes its `weighted_score` to the domain's `quality_score_provisional`; a `CERTIFIED` run writes it to `quality_score_certified`. The other basis's stored score is not touched, so a domain that has only ever run provisionally keeps a null `quality_score_certified`."
    PRD §3.4: "The domain's `scorecard_run_seq` is incremented by one and the resulting value is copied onto the run as `run_seq`, the run's `measured_at` is stamped from the logical clock, and the run's `domain_id` records the domain scored."

    Design: Corner/calculations/each_basis_writes_only_its_own_score_ledger_field
    """
    ctx = setup_draft_domain(rules=TWO_RULE_SET)

    provisional = validate_success(
        api.create_scorecard_run(
            ctx["domain"]["id"],
            {
                "basis": "PROVISIONAL",
                "measurements": [{"rule_code": "QR1", "measured_pct": 95.00}],
            },
            ctx["steward_headers"],
        ),
        201,
    )
    certified = validate_success(
        api.create_scorecard_run(
            ctx["domain"]["id"],
            {
                "basis": "CERTIFIED",
                "measurements": [{"rule_code": "QR1", "measured_pct": 95.00}],
            },
            ctx["steward_headers"],
        ),
        201,
    )

    assert provisional["weighted_score"] == 100.00, (
        "the unmeasured rule stays out of the provisional denominator, so the "
        f"single passing rule scores the run at 100.00, got "
        f"{provisional['weighted_score']}"
    )
    assert provisional["findings_created_count"] == 0, (
        "an unmeasured rule produces no finding on a provisional run, got "
        f"findings_created_count {provisional['findings_created_count']}"
    )
    assert certified["weighted_score"] == 40.00, (
        "the unmeasured rule is scored as 0.00 inside a hundred-point certified "
        f"denominator, scoring the run at 40.00, got {certified['weighted_score']}"
    )
    assert certified["findings_created_count"] == 1, (
        "the unmeasured rule breaches its threshold on a certified run and opens "
        f"one finding, got findings_created_count {certified['findings_created_count']}"
    )
    assert provisional["run_seq"] == 1 and certified["run_seq"] == 2, (
        "the two runs claim consecutive scorecard epochs, got run_seq "
        f"{provisional['run_seq']} then {certified['run_seq']}"
    )

    domain = read_domain(ctx["domain"]["id"])
    assert domain["quality_score_provisional"] == 100.00, (
        "the certified run must not overwrite the provisional score ledger, got "
        f"{domain['quality_score_provisional']}"
    )
    assert domain["quality_score_certified"] == 40.00, (
        "the certified run stores its own score in the certified ledger, got "
        f"{domain['quality_score_certified']}"
    )
    assert domain["scorecard_run_seq"] == 2, (
        f"two recorded runs advance the epoch to 2, got {domain['scorecard_run_seq']}"
    )


def test_certified_run_over_an_unmeasured_low_rule_adds_one_point_of_debt(api):
    """PRD §3.4: "On a `CERTIFIED` basis the evaluated set is *every* `ACTIVE` rule of the domain, and an `ACTIVE` rule left unmeasured is treated as having a `measured_pct` of 0.00 — it stays in the denominator, earns zero points, and produces a finding."
    PRD §3.4: "The base points come from the breached rule's `severity`: a `LOW`-severity rule contributes 1 point, `MEDIUM` contributes 3, `HIGH` contributes 8 and `CRITICAL` contributes 20."
    PRD §3.4: "Those base points are then multiplied by a posture multiplier: 1.00 when the domain's posture was `OPEN`, 1.25 when it was `RESTRICTED` and 1.50 when it was `FROZEN`."
    PRD §2.8: "`Domain.open_finding_weight` is the two-decimal, half-up-rounded sum of `severity_weight` over the domain's findings whose `status` is `OPEN` or `REMEDIATION_PLANNED`."

    Design: Corner/calculations/each_basis_writes_only_its_own_score_ledger_field
    """
    ctx = setup_draft_domain(rules=TWO_RULE_SET)

    validate_success(
        api.create_scorecard_run(
            ctx["domain"]["id"],
            {
                "basis": "PROVISIONAL",
                "measurements": [{"rule_code": "QR1", "measured_pct": 95.00}],
            },
            ctx["steward_headers"],
        ),
        201,
    )
    validate_success(
        api.create_scorecard_run(
            ctx["domain"]["id"],
            {
                "basis": "CERTIFIED",
                "measurements": [{"rule_code": "QR1", "measured_pct": 95.00}],
            },
            ctx["steward_headers"],
        ),
        201,
    )

    domain = read_domain(ctx["domain"]["id"])
    assert domain["open_finding_weight"] == 1.00, (
        "the single LOW-severity finding opened by the certified run weighs one "
        f"point at the open-posture multiplier, got {domain['open_finding_weight']}"
    )
    assert_two_decimal_places(domain["open_finding_weight"], "open_finding_weight")
